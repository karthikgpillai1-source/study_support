"""Progress tracking: topic events, study sessions, dashboards."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api import services
from app.api.deps import CurrentUser, DbSession
from app.api.services import NotFound
from app.db.models import StudySession
from app.schemas import (
    DashboardOut,
    ProgressUpdate,
    SessionCreate,
    SessionOut,
    SubjectProgressOut,
)

router = APIRouter(tags=["progress"])


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(user: CurrentUser, db: DbSession) -> dict:
    return services.dashboard(db, user)


@router.get("/subjects/{subject_id}/progress", response_model=SubjectProgressOut)
def subject_progress(subject_id: int, user: CurrentUser, db: DbSession) -> dict:
    subject = services.get_subject(db, user, subject_id)
    return services.subject_progress(db, subject)


@router.post("/progress", response_model=SubjectProgressOut)
def record_progress(payload: ProgressUpdate, user: CurrentUser, db: DbSession) -> dict:
    """Log a study event against a topic; updates mastery, package and block state."""
    topic = services.record_progress(
        db,
        user,
        topic_id=payload.topic_id,
        event=payload.event,
        minutes_spent=payload.minutes_spent,
        confidence=payload.confidence,
        knowledge_state=payload.knowledge_state,
        note=payload.note,
        block_id=payload.block_id,
        session_id=payload.session_id,
    )
    db.commit()
    db.refresh(topic)

    from app.db.models import StudyIntelligence, Subject

    intelligence = db.get(StudyIntelligence, topic.intelligence_id)
    if intelligence is None:
        raise NotFound("Topic is not linked to a subject")
    subject = db.get(Subject, intelligence.subject_id)
    if subject is None:
        raise NotFound("Subject not found")
    return services.subject_progress(db, subject)


@router.post("/sessions", response_model=SessionOut, status_code=201)
def start_session(payload: SessionCreate, user: CurrentUser, db: DbSession) -> StudySession:
    if payload.subject_id is not None:
        services.get_subject(db, user, payload.subject_id)
    session = services.start_session(db, user, payload.subject_id, payload.block_ids, payload.notes)
    db.commit()
    db.refresh(session)
    return session


@router.patch("/sessions/{session_id}", response_model=SessionOut)
def end_session(
    session_id: int,
    user: CurrentUser,
    db: DbSession,
    actual_minutes: int = Query(ge=0, le=600),
    focus_score: float = Query(default=1.0, ge=0.0, le=1.0),
) -> StudySession:
    session = db.get(StudySession, session_id)
    if session is None or session.user_id != user.id:
        raise NotFound("Study session not found")
    services.end_session(db, session, actual_minutes, focus_score)
    db.commit()
    db.refresh(session)
    return session


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(
    user: CurrentUser, db: DbSession, limit: int = Query(default=30, ge=1, le=200)
) -> list[StudySession]:
    sessions = db.scalars(
        select(StudySession)
        .where(StudySession.user_id == user.id)
        .order_by(StudySession.started_at.desc())
        .limit(limit)
    ).all()
    return list(sessions)
