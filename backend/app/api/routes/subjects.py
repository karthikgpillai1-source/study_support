"""Subject CRUD, upload centre, analysis, packages."""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select

from app.api import services
from app.api.deps import CurrentUser, DbSession
from app.api.services import Forbidden, NotFound, ServiceError
from app.core.config import settings
from app.db.models import Document, Subject, Team
from app.engine.packages import MAX_PACKAGE_MINUTES
from app.schemas import (
    AnalysisOut,
    DocumentOut,
    IntelligenceOut,
    PackageOut,
    PackagesOut,
    SubjectCreate,
    SubjectOut,
    SubjectUpdate,
    TimeEstimateOut,
    UploadResult,
)
from app.schemas.intelligence import DifficultyBreakdown

router = APIRouter(tags=["subjects"])


# --------------------------------------------------------------------------- CRUD
@router.get("/subjects", response_model=list[SubjectOut])
def list_subjects(user: CurrentUser, db: DbSession) -> list[SubjectOut]:
    subjects = services.accessible_subjects(db, user)
    return [SubjectOut(**services.subject_summary(db, s)) for s in subjects]


@router.post("/subjects", response_model=SubjectOut, status_code=201)
def create_subject(payload: SubjectCreate, user: CurrentUser, db: DbSession) -> SubjectOut:
    if payload.team_id is not None:
        team = db.get(Team, payload.team_id)
        if team is None:
            raise NotFound("Team not found")
        if not services.is_team_lead(db, user, team.id) and not any(
            m.user_id == user.id for m in services.team_members(db, team.id)
        ):
            raise Forbidden("Join the team before adding subjects to it")
    subject = Subject(
        name=payload.name.strip(),
        code=payload.code.strip()[:40],
        description=payload.description,
        knowledge_level=payload.knowledge_level,
        exam_date=payload.exam_date,
        study_mode=payload.study_mode,
        color=payload.color,
        daily_minutes=payload.daily_minutes,
        start_time=payload.start_time,
        rest_days=payload.rest_days,
        owner_id=user.id,
        team_id=payload.team_id,
    )
    db.add(subject)
    db.commit()
    db.refresh(subject)
    return SubjectOut(**services.subject_summary(db, subject))


@router.get("/subjects/{subject_id}", response_model=SubjectOut)
def get_subject(subject_id: int, user: CurrentUser, db: DbSession) -> SubjectOut:
    subject = services.get_subject(db, user, subject_id)
    return SubjectOut(**services.subject_summary(db, subject))


@router.patch("/subjects/{subject_id}", response_model=SubjectOut)
def update_subject(
    subject_id: int, payload: SubjectUpdate, user: CurrentUser, db: DbSession
) -> SubjectOut:
    subject = services.get_subject(db, user, subject_id)
    if subject.team_id is not None and not services.is_team_lead(db, user, subject.team_id):
        raise Forbidden("Only a team lead can change a shared subject")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(subject, field, value)
    db.commit()
    db.refresh(subject)
    return SubjectOut(**services.subject_summary(db, subject))


@router.delete("/subjects/{subject_id}", status_code=204)
def delete_subject(subject_id: int, user: CurrentUser, db: DbSession) -> None:
    subject = services.get_subject(db, user, subject_id)
    if subject.team_id is not None and not services.is_team_lead(db, user, subject.team_id):
        raise Forbidden("Only a team lead can delete a shared subject")
    db.delete(subject)
    db.commit()


# ------------------------------------------------------------------------ uploads
@router.post(
    "/subjects/{subject_id}/documents",
    response_model=UploadResult,
    status_code=201,
)
async def upload_document(
    subject_id: int,
    user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
    analyze_now: bool = Form(default=True),
    use_llm: bool = Form(default=True),
) -> UploadResult:
    subject = services.get_subject(db, user, subject_id)
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename was provided")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")
    limit = settings.max_upload_bytes
    if len(data) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"File is larger than the {limit // (1024 * 1024)} MB limit",
        )

    document, extracted = services.ingest_document(db, subject, user, file.filename, data)
    if analyze_now:
        # Extraction already succeeded; a failed analysis can be retried explicitly.
        with contextlib.suppress(ServiceError):
            await services.run_analysis_async(db, subject, use_llm=use_llm)
    db.commit()
    db.refresh(document)
    return UploadResult(
        document=DocumentOut.model_validate(document),
        text_preview=extracted.text[:1500],
        characters=len(extracted.text),
    )


@router.get("/subjects/{subject_id}/documents", response_model=list[DocumentOut])
def list_documents(subject_id: int, user: CurrentUser, db: DbSession) -> list[DocumentOut]:
    services.get_subject(db, user, subject_id)
    documents = db.scalars(
        select(Document)
        .where(Document.subject_id == subject_id)
        .order_by(Document.created_at.desc())
    ).all()
    return [DocumentOut.model_validate(d) for d in documents]


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: int, user: CurrentUser, db: DbSession) -> None:
    document = db.get(Document, document_id)
    if document is None:
        raise NotFound("Document not found")
    services.get_subject(db, user, document.subject_id)
    db.delete(document)
    db.commit()


# ----------------------------------------------------------------------- analysis
@router.get("/subjects/{subject_id}/intelligence", response_model=IntelligenceOut)
def get_intelligence(subject_id: int, user: CurrentUser, db: DbSession) -> IntelligenceOut:
    subject = services.get_subject(db, user, subject_id)
    intelligence = services.require_intelligence(db, subject)
    return IntelligenceOut.model_validate(intelligence)


@router.post("/subjects/{subject_id}/analyze", response_model=IntelligenceOut)
async def analyze_subject(
    subject_id: int, user: CurrentUser, db: DbSession, use_llm: bool = Query(default=True)
) -> IntelligenceOut:
    subject = services.get_subject(db, user, subject_id)
    intelligence = await services.run_analysis_async(db, subject, use_llm=use_llm)
    db.commit()
    db.refresh(intelligence)
    return IntelligenceOut.model_validate(intelligence)


@router.get("/subjects/{subject_id}/analysis", response_model=AnalysisOut)
def analysis_screen(subject_id: int, user: CurrentUser, db: DbSession) -> AnalysisOut:
    """Everything the Analysis screen renders, in one request."""
    subject = services.get_subject(db, user, subject_id)
    intelligence = services.load_intelligence(db, subject_id)
    estimates = services.time_estimates(db, subject)
    packages = [PackageOut.model_validate(p) for p in services.load_packages(db, subject_id)]

    warnings: list[str] = []
    if intelligence is None:
        warnings.append("No analysis yet. Upload notes and run analysis.")
    else:
        for document in db.scalars(select(Document).where(Document.subject_id == subject_id)).all():
            warnings.extend(document.warnings or [])

    return AnalysisOut(
        subject=services.subject_summary(db, subject),
        intelligence=IntelligenceOut.model_validate(intelligence) if intelligence else None,
        estimates=TimeEstimateOut(**estimates) if estimates else None,
        packages=packages,
        warnings=warnings,
    )


@router.get("/subjects/{subject_id}/estimates", response_model=TimeEstimateOut)
def estimates(subject_id: int, user: CurrentUser, db: DbSession) -> TimeEstimateOut:
    subject = services.get_subject(db, user, subject_id)
    data = services.time_estimates(db, subject)
    if data is None:
        raise ServiceError("Run analysis on this subject first.")
    return TimeEstimateOut(
        **{k: v for k, v in data.items() if k != "breakdown"},
        breakdown=DifficultyBreakdown(**data["breakdown"]),
    )


# ----------------------------------------------------------------------- packages
@router.post("/subjects/{subject_id}/packages", response_model=PackagesOut, status_code=201)
def create_packages(
    subject_id: int,
    user: CurrentUser,
    db: DbSession,
    include_revision: bool = Query(default=True),
    regenerate: bool = Query(default=True),
) -> PackagesOut:
    subject = services.get_subject(db, user, subject_id)
    services.generate_packages(
        db, subject, include_revision=include_revision, regenerate=regenerate
    )
    db.commit()
    packages = services.load_packages(db, subject_id)
    return PackagesOut(
        subject_id=subject_id,
        strategy="module-aware sequential packing, 90 min cap",
        max_minutes_per_package=MAX_PACKAGE_MINUTES,
        packages=[PackageOut.model_validate(p) for p in packages],
    )


@router.get("/subjects/{subject_id}/packages", response_model=PackagesOut)
def list_packages(subject_id: int, user: CurrentUser, db: DbSession) -> PackagesOut:
    services.get_subject(db, user, subject_id)
    packages = services.load_packages(db, subject_id)
    return PackagesOut(
        subject_id=subject_id,
        strategy="module-aware sequential packing, 90 min cap",
        max_minutes_per_package=MAX_PACKAGE_MINUTES,
        packages=[PackageOut.model_validate(p) for p in packages],
    )
