"""Service layer: engine <-> persistence.

The API routes stay thin; all orchestration lives here. Engines remain pure
(no SQLAlchemy imports below ``app/engine`` and ``app/planner``).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.enums import (
    BlockStatus,
    Difficulty,
    KnowledgeState,
    PackageType,
    SplitStrategy,
    TopicStatus,
    utcnow,
    week_start,
)
from app.db.models import (
    Document,
    PeerSignal,
    ProgressRecord,
    StudyBlock,
    StudyIntelligence,
    StudyPlan,
    StudySession,
    StudyUnit,
    Subject,
    Team,
    TeamMember,
    Topic,
    TopicOwnership,
    User,
    WorkPackage,
)
from app.engine import estimation
from app.engine.extraction.extractors import (
    ExtractedDocument,
    ExtractionError,
    extract,
    store_upload,
)
from app.engine.knowledge import IntelligenceRequest, StudyIntelligenceJSON, analyze
from app.engine.packages import (
    MAX_PACKAGE_MINUTES,
    PackagePlan,
    PackageTopic,
    build_packages,
)
from app.engine.splits import (
    Member,
    PackageView,
    SplitResult,
    generate_all,
    strategy_for,
)
from app.engine.team_intel import (
    MemberState,
    build_matrix,
    next_mastery,
    rank_experts,
    rank_learners,
    recommend_peer_teaching,
    state_for_mastery,
)
from app.planner.adaptive import ExecutionSnapshot
from app.planner.adaptive import analyse as adaptive_analyse
from app.planner.rules import UnitCandidate
from app.planner.scheduler import build_schedule

logger = logging.getLogger(__name__)


class ServiceError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class NotFound(ServiceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 404)


class Forbidden(ServiceError):
    def __init__(self, message: str = "You do not have access to this resource") -> None:
        super().__init__(message, 403)


# ======================================================================== access
def accessible_subjects(db: Session, user: User) -> list[Subject]:
    """Subjects the user owns plus every subject of a team they belong to."""
    team_ids = db.scalars(select(TeamMember.team_id).where(TeamMember.user_id == user.id)).all()
    conditions = [Subject.owner_id == user.id]
    if team_ids:
        conditions.append(Subject.team_id.in_(list(team_ids)))
    return list(db.scalars(select(Subject).where(*conditions)).unique().all())


def get_subject(db: Session, user: User, subject_id: int) -> Subject:
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise NotFound("Subject not found")
    if not can_access_subject(db, user, subject):
        raise Forbidden("This subject belongs to a team you are not a member of")
    return subject


def can_access_subject(db: Session, user: User, subject: Subject) -> bool:
    if subject.owner_id == user.id:
        return True
    if subject.team_id is None:
        return False
    return db.scalar(
        select(func.count(TeamMember.id)).where(
            TeamMember.team_id == subject.team_id, TeamMember.user_id == user.id
        )
    )


def is_team_lead(db: Session, user: User, team_id: int) -> bool:
    member = db.scalar(
        select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user.id)
    )
    if member is None:
        return False
    if member.role == "owner":
        return True
    team = db.get(Team, team_id)
    return bool(team and (team.owner_id == user.id or team.created_by_id == user.id))


# ======================================================================= uploads
def ingest_document(
    db: Session, subject: Subject, user: User, filename: str, data: bytes
) -> tuple[Document, ExtractedDocument]:
    try:
        extracted = extract(filename, data)
    except ExtractionError as exc:
        raise ServiceError(str(exc)) from exc

    path = ""
    try:
        path = store_upload(data, filename, subject.id)
    except OSError as exc:  # pragma: no cover - disk issues
        logger.warning("Could not store upload: %s", exc)

    document = Document(
        subject_id=subject.id,
        filename=Path(filename).name[:255],
        content_type="",
        size_bytes=len(data),
        stored_path=path,
        page_count=extracted.page_count,
        word_count=extracted.word_count,
        status="extracted",
        extractor=extracted.extractor,
        warnings=list(extracted.warnings),
        uploaded_by_id=user.id,
    )
    db.add(document)
    db.flush()
    return document, extracted


def load_extracted_text(document: Document) -> ExtractedDocument:
    if document.stored_path and Path(document.stored_path).exists():
        return extract(document.filename, Path(document.stored_path).read_bytes())
    raise ServiceError(
        f"The original file for '{document.filename}' is no longer on disk. Re-upload the notes."
    )


def subject_text(db: Session, subject: Subject) -> tuple[str, list[str]]:
    """Concatenate every document's text for the subject."""
    documents = list(db.scalars(select(Document).where(Document.subject_id == subject.id)).all())
    if not documents:
        raise ServiceError("Upload at least one PDF, DOCX or TXT file before analysing.")
    parts: list[str] = []
    warnings: list[str] = []
    for document in documents:
        try:
            extracted = load_extracted_text(document)
        except ServiceError:
            warnings.append(f"Skipped '{document.filename}': the stored file is missing.")
            continue
        # Provenance lives on the Document row. The concatenated text stays clean
        # so the section splitter is not handed synthetic headings to misread.
        parts.append(extracted.text)
        warnings.extend(extracted.warnings)
    if not parts:
        raise ServiceError("None of the uploaded files could be read. Re-upload the notes.")
    return "\n\n".join(parts), warnings


# ================================================================== intelligence
def run_analysis_sync(db: Session, subject: Subject, *, use_llm: bool = True) -> StudyIntelligence:
    """Blocking analysis for scripts and tests. Production routes use the async version."""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_analysis_async(db, subject, use_llm=use_llm))
    raise ServiceError("An event loop is already running; use `await run_analysis_async(...)`.")


async def run_analysis_async(
    db: Session, subject: Subject, *, use_llm: bool = True
) -> StudyIntelligence:
    text, warnings = subject_text(db, subject)
    document = ExtractedDocument(text=text, page_count=1, extractor="combined", warnings=warnings)
    request = IntelligenceRequest(
        subject_name=subject.name,
        knowledge_level=subject.knowledge_level,
        study_mode=subject.study_mode,
        exam_date=subject.exam_date,
        use_llm=use_llm,
    )
    payload = await analyze(document, request)
    return persist_intelligence(db, subject, payload)


def re_pages(text: str) -> list[str]:
    """Split concatenated source text back into per-document chunks."""
    return [chunk for chunk in text.split("\f") if chunk.strip()]


def persist_intelligence(
    db: Session, subject: Subject, payload: StudyIntelligenceJSON
) -> StudyIntelligence:
    old = db.scalar(select(StudyIntelligence).where(StudyIntelligence.subject_id == subject.id))
    if old is not None:
        db.delete(old)
        db.flush()

    intelligence = StudyIntelligence(
        subject_id=subject.id,
        source=payload.source,
        summary=payload.summary,
        modules=[m.model_dump() for m in payload.modules],
        keywords=list(payload.keywords),
        learning_objectives=list(payload.learning_objectives),
        formulas=list(payload.formulas),
        total_minutes=payload.total_minutes,
        topic_count=len(payload.topics),
        confidence=payload.confidence,
    )
    db.add(intelligence)
    db.flush()

    for position, topic in enumerate(payload.topics):
        db.add(
            Topic(
                intelligence_id=intelligence.id,
                module_title=topic.module_title,
                title=topic.title,
                position=position,
                difficulty=topic.difficulty,
                estimated_minutes=topic.estimated_minutes,
                revision_minutes=topic.revision_minutes,
                importance=topic.importance,
                keywords=list(topic.keywords),
                learning_objectives=list(topic.learning_objectives),
                definitions=list(topic.definitions),
                procedures=list(topic.procedures),
                formulas=list(topic.formulas),
                important_facts=list(topic.important_facts),
                subtopics=list(topic.subtopics),
                concepts=list(topic.concepts),
                source_excerpt=topic.source_excerpt,
            )
        )
    db.flush()
    db.refresh(intelligence)
    return intelligence


def load_intelligence(db: Session, subject_id: int) -> StudyIntelligence | None:
    return db.scalar(
        select(StudyIntelligence)
        .where(StudyIntelligence.subject_id == subject_id)
        .options(selectinload(StudyIntelligence.topics))
    )


def require_intelligence(db: Session, subject: Subject) -> StudyIntelligence:
    intelligence = load_intelligence(db, subject.id)
    if intelligence is None:
        raise ServiceError("Run analysis on this subject first.")
    return intelligence


def load_topics(db: Session, intelligence_id: int) -> list[Topic]:
    return list(
        db.scalars(
            select(Topic)
            .where(Topic.intelligence_id == intelligence_id)
            .order_by(Topic.position, Topic.id)
        ).all()
    )


# ======================================================================= packages
def generate_packages(
    db: Session, subject: Subject, *, include_revision: bool = True, regenerate: bool = True
) -> list[WorkPackage]:
    intelligence = require_intelligence(db, subject)
    topics = load_topics(db, intelligence.id)
    if not topics:
        raise ServiceError("Analysis produced no topics to package.")

    if regenerate:
        _delete_packages(db, subject.id)
        db.flush()

    package_topics = [
        PackageTopic(
            id=t.id,
            title=t.title,
            module_title=t.module_title or "General",
            difficulty=Difficulty(t.difficulty),
            minutes=t.estimated_minutes,
            revision_minutes=t.revision_minutes,
            importance=t.importance,
            learning_objectives=list(t.learning_objectives),
            keywords=list(t.keywords),
        )
        for t in topics
        if t.status is not TopicStatus.COMPLETED
    ] or [
        PackageTopic(
            id=t.id,
            title=t.title,
            module_title=t.module_title or "General",
            difficulty=Difficulty(t.difficulty),
            minutes=t.estimated_minutes,
            revision_minutes=t.revision_minutes,
            importance=t.importance,
            learning_objectives=list(t.learning_objectives),
            keywords=list(t.keywords),
        )
        for t in topics
    ]

    plans = build_packages(
        package_topics, max_minutes=MAX_PACKAGE_MINUTES, include_revision=include_revision
    )
    created = [
        _persist_package(db, subject, intelligence, plan, position)
        for position, plan in enumerate(plans)
    ]
    db.flush()
    return created


def _delete_packages(db: Session, subject_id: int) -> None:
    package_ids = list(
        db.scalars(select(WorkPackage.id).where(WorkPackage.subject_id == subject_id)).all()
    )
    if package_ids:
        db.query(StudyBlock).filter(StudyBlock.package_id.in_(package_ids)).update(
            {"package_id": None}, synchronize_session=False
        )
        db.query(StudyUnit).filter(StudyUnit.package_id.in_(package_ids)).delete(
            synchronize_session=False
        )
        db.query(WorkPackage).filter(WorkPackage.id.in_(package_ids)).delete(
            synchronize_session=False
        )
    db.flush()


def _persist_package(
    db: Session, subject: Subject, intelligence: StudyIntelligence, plan: PackagePlan, position: int
) -> WorkPackage:
    package = WorkPackage(
        subject_id=subject.id,
        intelligence_id=intelligence.id,
        type=plan.type,
        title=plan.title[:300],
        position=position,
        total_minutes=plan.minutes,
        difficulty=plan.difficulty,
        topic_ids=list(plan.topic_ids),
    )
    db.add(package)
    db.flush()
    for unit_position, unit in enumerate(plan.units):
        db.add(
            StudyUnit(
                package_id=package.id,
                topic_id=unit.topic_id,
                type=unit.type,
                title=unit.title[:300],
                position=unit_position,
                minutes=unit.minutes,
                objectives=list(unit.objectives),
                resources=list(unit.resources),
            )
        )
    return package


def load_packages(db: Session, subject_id: int) -> list[WorkPackage]:
    return list(
        db.scalars(
            select(WorkPackage)
            .where(WorkPackage.subject_id == subject_id)
            .options(selectinload(WorkPackage.units))
            .order_by(WorkPackage.position, WorkPackage.id)
        )
        .unique()
        .all()
    )


# ========================================================================== plans
def unit_candidates(db: Session, subject: Subject) -> list[UnitCandidate]:
    """Flatten a subject's study units into planner candidates."""
    packages = load_packages(db, subject.id)
    if not packages:
        raise ServiceError("Generate work packages before creating a plan.")

    topic_by_id: dict[int, Topic] = {}
    for package in packages:
        for topic_id in package.topic_ids:
            if topic_id not in topic_by_id:
                topic = db.get(Topic, topic_id)
                if topic is not None:
                    topic_by_id[topic_id] = topic

    revision_seen: dict[int, int] = {}
    candidates: list[UnitCandidate] = []
    for package in packages:
        is_revision = package.type is PackageType.REVISION
        for unit in sorted(package.units, key=lambda u: u.position):
            topic = topic_by_id.get(unit.topic_id) if unit.topic_id else None
            if is_revision:
                key = unit.topic_id or 0
                revision_seen[key] = revision_seen.get(key, 0) + 1
                revision_round = revision_seen[key]
            else:
                revision_round = 0
            candidates.append(
                UnitCandidate(
                    unit_id=unit.id,
                    package_id=package.id,
                    topic_id=unit.topic_id,
                    title=unit.title,
                    minutes=unit.minutes,
                    kind=unit.type,
                    difficulty=package.difficulty.rank,
                    importance=topic.importance if topic else 0.5,
                    mastery=topic.mastery if topic else 0.0,
                    status=topic.status if topic else TopicStatus.PENDING.value,
                    is_revision=is_revision,
                    revision_round=revision_round,
                )
            )
    return candidates


def generate_plan(
    db: Session,
    subject: Subject,
    *,
    horizon_days: int = 14,
    daily_minutes: int | None = None,
    start_date: date | None = None,
    include_revision: bool = True,
    respect_rest_days: bool = True,
    mode: str = "rebuild",
) -> StudyPlan:
    candidates = unit_candidates(db, subject)
    owner = subject.owner or db.get(User, subject.owner_id) if subject.owner_id else None
    budget = daily_minutes or subject.daily_minutes or (owner.daily_minutes if owner else 120)
    clock = subject.start_time or (owner.preferred_start_time if owner else "18:00")
    rest = list(subject.rest_days or []) if respect_rest_days else []

    existing = active_plan(db, subject.id)
    history_day = start_date or utcnow().date()
    plan: StudyPlan | None = None

    if existing is not None and mode == "keep_done":
        # Preserve execution history only. Every future *planned* block is dropped
        # and re-planned from scratch, so an availability change can never leave a
        # day over its new limit.
        plan = existing
        history_day = max(history_day, _first_open_day(db, existing))
        for block in list(existing.blocks):
            if not _is_history(block):
                _detach_block(db, block)
    elif existing is not None:
        db.delete(existing)
        db.flush()
        plan = None

    result = build_schedule(
        candidates,
        start=history_day,
        horizon_days=horizon_days,
        daily_minutes=budget,
        start_clock=clock,
        exam_date=subject.exam_date,
        study_mode=subject.study_mode.value,
        knowledge_level_rank=subject.knowledge_level.rank,
        rest_days=rest,
        include_revision=include_revision,
    )

    plan = plan or StudyPlan(subject_id=subject.id, generated_for=history_day)
    plan.generated_for = history_day
    plan.week_start = week_start(history_day)
    plan.strategy = str(result.meta.get("strategy", ""))[:24] or "priority"
    plan.study_mode = subject.study_mode.value
    plan.daily_budget_minutes = budget
    plan.planned_minutes = result.total_planned_minutes
    plan.reason = result.reason[:300]
    plan.meta = result.meta
    plan.is_active = True
    if plan.id is None:
        db.add(plan)
    db.flush()
    plan.version = (plan.version or 0) + 1

    position = 0
    for day in result.days:
        for scheduled in day.blocks:
            db.add(
                StudyBlock(
                    plan_id=plan.id,
                    unit_id=scheduled.unit_id,
                    package_id=scheduled.package_id,
                    topic_id=scheduled.topic_id,
                    day=scheduled.day,
                    start_time=scheduled.start_time,
                    end_time=scheduled.end_time,
                    minutes=scheduled.minutes,
                    block_index=scheduled.block_index,
                    position=position,
                    kind=scheduled.kind,
                    title=scheduled.title[:300],
                    priority=scheduled.priority,
                    is_break=scheduled.is_break,
                    note=scheduled.note,
                )
            )
            position += 1
    db.flush()
    return plan


def _is_history(block: StudyBlock) -> bool:
    """True for blocks that represent work already in the past or already done."""
    if block.status in (BlockStatus.DONE, BlockStatus.PARTIAL):
        return True
    return block.day < utcnow().date()


def _first_open_day(db: Session, plan: StudyPlan) -> date:
    today = utcnow().date()
    future = [
        b.day
        for b in plan.blocks
        if b.status is BlockStatus.PLANNED and b.day >= today and not b.is_break
    ]
    return min(future) if future else today


def _detach_block(db: Session, block: StudyBlock) -> None:
    """Remove a block from a plan without deleting its unit."""
    db.delete(block)
    db.flush()


def active_plan(db: Session, subject_id: int) -> StudyPlan | None:
    return db.scalar(
        select(StudyPlan)
        .where(StudyPlan.subject_id == subject_id, StudyPlan.is_active.is_(True))
        .order_by(StudyPlan.generated_for.desc(), StudyPlan.id.desc())
    )


def load_plan(db: Session, subject_id: int) -> StudyPlan | None:
    return active_plan(db, subject_id)


def execution_snapshot(db: Session, subject: Subject, plan: StudyPlan) -> ExecutionSnapshot:
    today = utcnow().date()
    blocks = list(
        db.scalars(
            select(StudyBlock).where(StudyBlock.plan_id == plan.id, StudyBlock.is_break.is_(False))
        ).all()
    )
    past = [
        b
        for b in blocks
        if b.day < today or (b.day == today and b.status is not BlockStatus.PLANNED)
    ]
    planned = sum(b.minutes for b in past)
    completed = sum(
        b.actual_minutes or (b.minutes if b.status is BlockStatus.DONE else 0) for b in past
    )
    missed = sum(b.minutes for b in past if b.status is BlockStatus.MISSED)
    overdue = len([b for b in blocks if b.day < today and b.status is BlockStatus.PLANNED])
    topics = load_topics(db, require_intelligence(db, subject).id)
    return ExecutionSnapshot(
        as_of=today,
        planned_minutes=planned,
        completed_minutes=completed,
        missed_minutes=missed,
        topics_completed=sum(1 for t in topics if t.status is TopicStatus.COMPLETED),
        topics_pending=sum(1 for t in topics if t.status is not TopicStatus.COMPLETED),
        overdue_units=overdue,
    )


def adaptive_report(db: Session, subject: Subject) -> dict:
    plan = active_plan(db, subject.id)
    if plan is None:
        raise ServiceError("Generate a plan before requesting an adaptive review.")
    candidates = unit_candidates(db, subject)
    snapshot = execution_snapshot(db, subject, plan)
    result = adaptive_analyse(
        candidates,
        snapshot,
        current_daily_minutes=subject.daily_minutes,
        exam_date=subject.exam_date,
        study_mode=subject.study_mode.value,
        knowledge_level_rank=subject.knowledge_level.rank,
        horizon_days=min(30, max(1, (plan.meta or {}).get("horizon_days", 14))),
    )
    return result.as_dict()


# ======================================================================= progress
def record_progress(
    db: Session,
    user: User,
    *,
    topic_id: int,
    event: str,
    minutes_spent: int = 0,
    confidence: float = 0.0,
    knowledge_state: KnowledgeState | None = None,
    note: str = "",
    block_id: int | None = None,
    session_id: int | None = None,
) -> Topic:
    topic = db.get(Topic, topic_id)
    if topic is None:
        raise NotFound("Topic not found")
    subject = db.get(Subject, topic.intelligence.subject_id if topic.intelligence else 0)
    if subject is not None and not can_access_subject(db, user, subject):
        raise Forbidden()

    if knowledge_state is not None:
        topic.mastery = max(
            topic.mastery, 0.9 if knowledge_state is KnowledgeState.MASTERED else 0.0
        )
        topic.knowledge_state = knowledge_state
    else:
        topic.mastery = next_mastery(topic.knowledge_state, event, confidence)
        topic.knowledge_state = state_for_mastery(topic.mastery)

    if event == "completed":
        topic.status = TopicStatus.COMPLETED
        topic.completed_at = utcnow()
    elif event == "started":
        topic.status = TopicStatus.IN_PROGRESS
    elif event == "skipped":
        topic.status = TopicStatus.SKIPPED
    elif event == "partial":
        if topic.status is TopicStatus.PENDING:
            topic.status = TopicStatus.IN_PROGRESS

    record = ProgressRecord(
        user_id=user.id,
        topic_id=topic.id,
        session_id=session_id,
        block_id=block_id,
        event=event,
        minutes_spent=minutes_spent,
        confidence=confidence,
        note=note[:2000],
    )
    db.add(record)

    if block_id is not None:
        block = db.get(StudyBlock, block_id)
        if block is not None and block.topic_id == topic.id:
            block.actual_minutes = minutes_spent or block.actual_minutes
            if event == "completed":
                block.status = BlockStatus.DONE
                block.completed_at = utcnow()
            elif event == "partial":
                block.status = BlockStatus.PARTIAL
            elif event == "skipped":
                block.status = BlockStatus.SKIPPED

    _mark_packages(db, topic, event)
    db.flush()
    return topic


def _mark_packages(db: Session, topic: Topic, event: str) -> None:
    intelligence = db.get(StudyIntelligence, topic.intelligence_id)
    if intelligence is None:
        return
    for package in db.scalars(
        select(WorkPackage).where(WorkPackage.subject_id == intelligence.subject_id)
    ).all():
        if topic.id not in (package.topic_ids or []):
            continue
        if package.type is not PackageType.STUDY or event != "completed":
            continue
        siblings = [found for tid in package.topic_ids if (found := db.get(Topic, tid)) is not None]
        package.completed = bool(siblings) and all(
            sibling.status is TopicStatus.COMPLETED for sibling in siblings
        )


# ===================================================================== team work
def team_members(db: Session, team_id: int) -> list[TeamMember]:
    return list(
        db.scalars(
            select(TeamMember)
            .where(TeamMember.team_id == team_id)
            .options(selectinload(TeamMember.user))
            .order_by(TeamMember.joined_at, TeamMember.id)
        )
        .unique()
        .all()
    )


def package_views(db: Session, subject_id: int) -> list[PackageView]:
    packages = load_packages(db, subject_id)
    topics = {
        t.id: t
        for t in db.scalars(
            select(Topic)
            .join(StudyIntelligence, Topic.intelligence_id == StudyIntelligence.id)
            .where(StudyIntelligence.subject_id == subject_id)
        ).all()
    }
    views: list[PackageView] = []
    for p in packages:
        package_topics = [topics[t] for t in (p.topic_ids or []) if t in topics]
        module = package_topics[0].module_title if package_topics else "General"
        views.append(
            PackageView(
                id=p.id,
                title=p.title,
                minutes=p.total_minutes,
                difficulty=Difficulty(p.difficulty),
                topic_ids=list(p.topic_ids or []),
                type=PackageType(p.type),
                module_title=module or "General",
                topic_titles=[t.title for t in package_topics],
            )
        )
    return views


def member_profiles(db: Session, team_id: int) -> list[Member]:
    out: list[Member] = []
    for membership in team_members(db, team_id):
        out.append(
            Member(
                user_id=membership.user_id,
                name=membership.user.full_name if membership.user else f"User {membership.user_id}",
                daily_minutes=membership.user.daily_minutes if membership.user else 120,
            )
        )
    return out


def split_suggestions(
    db: Session, subject: Subject, strategy: SplitStrategy | None = None
) -> list[SplitResult]:
    if subject.team_id is None:
        raise ServiceError("This subject is solo. Create or join a team to use work distribution.")
    members = member_profiles(db, subject.team_id)
    if not members:
        raise ServiceError("The team has no members yet.")
    packages = package_views(db, subject.id)
    if not packages:
        raise ServiceError("Generate work packages before requesting a distribution.")
    if strategy is not None:
        return [strategy_for(strategy, members, packages)]
    return generate_all(members, packages)


def apply_suggestion(
    db: Session,
    subject: Subject,
    strategy: SplitStrategy,
    assignments: list[dict],
    *,
    requested_by: User,
) -> int:
    """Persist an *accepted* suggestion as topic ownership. Never automatic."""
    if subject.team_id is None:
        raise ServiceError("This subject is solo.")
    if not is_team_lead(db, requested_by, subject.team_id):
        raise Forbidden("Only a team owner or lead can accept a distribution.")
    valid_members = {m.user_id for m in member_profiles(db, subject.team_id)}
    applied = 0
    for assignment in assignments:
        user_id = assignment.get("user_id")
        if user_id not in valid_members:
            continue
        role = str(assignment.get("role", "owner"))
        for topic_id in assignment.get("topic_ids", []):
            existing = db.scalar(
                select(TopicOwnership).where(
                    TopicOwnership.topic_id == topic_id, TopicOwnership.user_id == user_id
                )
            )
            if existing is None:
                db.add(
                    TopicOwnership(
                        topic_id=topic_id,
                        user_id=user_id,
                        role=role if role in ("owner", "reviewer") else "owner",
                        strategy=strategy.value,
                        accepted=True,
                    )
                )
            else:
                existing.strategy = strategy.value
                existing.role = role if role in ("owner", "reviewer") else existing.role
                existing.accepted = True
            applied += 1
    db.flush()
    return applied


def knowledge_matrix(db: Session, subject: Subject):
    if subject.team_id is None:
        raise ServiceError("The knowledge matrix is a team feature.")
    intelligence = require_intelligence(db, subject)
    topics = load_topics(db, intelligence.id)
    topic_ids = [t.id for t in topics]
    titles = {t.id: t.title for t in topics}

    progress_rows = list(
        db.scalars(
            select(ProgressRecord)
            .join(Topic, ProgressRecord.topic_id == Topic.id)
            .join(StudyIntelligence, Topic.intelligence_id == StudyIntelligence.id)
            .where(StudyIntelligence.subject_id == subject.id)
        ).all()
    )
    by_user_topic: dict[tuple[int, int], list[ProgressRecord]] = {}
    for record in progress_rows:
        by_user_topic.setdefault((record.user_id, record.topic_id), []).append(record)

    memberships = team_members(db, subject.team_id)
    topic_by_id = {t.id: t for t in topics}
    states: list[MemberState] = []
    for membership in memberships:
        member_state = MemberState(
            user_id=membership.user_id,
            name=membership.user.full_name if membership.user else f"User {membership.user_id}",
        )
        for topic_id in topic_ids:
            topic = topic_by_id[topic_id]
            records = by_user_topic.get((membership.user_id, topic_id), [])
            if records:
                mastery = float(topic.mastery)
                state = str(topic.knowledge_state)
                status = str(topic.status)
            else:
                mastery, state, status = 0.0, KnowledgeState.UNKNOWN, TopicStatus.PENDING
            member_state.topics[topic_id] = (mastery, state, status)
        states.append(member_state)

    ownership: dict[int, set[int]] = {}
    for row in db.scalars(
        select(TopicOwnership).where(TopicOwnership.topic_id.in_(topic_ids))
    ).all():
        ownership.setdefault(row.user_id, set()).add(row.topic_id)

    return build_matrix(states, topic_ids, titles, ownership), states


def peer_recommendations(db: Session, subject: Subject) -> dict:
    matrix, _states = knowledge_matrix(db, subject)
    recommendations = recommend_peer_teaching(matrix)
    return {
        "subject_id": subject.id,
        "experts": rank_experts(matrix),
        "learners": rank_learners(matrix),
        "recommendations": [
            {
                "topic_id": r.topic_id,
                "topic_title": r.topic_title,
                "expert_id": r.expert_id,
                "expert_name": r.expert_name,
                "learner_ids": r.learner_ids,
                "learner_names": r.learner_names,
                "reason": r.reason,
                "confidence": r.confidence,
                "action": r.action,
            }
            for r in recommendations
        ],
        "note": "Recommendations only. Nothing is assigned automatically.",
    }


def signal_peer_activity(
    db: Session, user: User, topic_id: int, kind: str, note: str = ""
) -> PeerSignal:
    signal = db.scalar(
        select(PeerSignal).where(PeerSignal.topic_id == topic_id, PeerSignal.user_id == user.id)
    )
    weight = {"taught": 1.0, "mastered": 0.8, "struggling": -0.5}.get(kind, 0.0)
    if signal is None:
        signal = PeerSignal(
            topic_id=topic_id, user_id=user.id, kind=kind, weight=weight, note=note[:300]
        )
        db.add(signal)
    else:
        signal.kind = kind
        signal.weight = weight
        signal.note = note[:300]
    db.flush()
    return signal


# ==================================================================== projections
def subject_summary(db: Session, subject: Subject) -> dict:
    document_count = (
        db.scalar(select(func.count(Document.id)).where(Document.subject_id == subject.id)) or 0
    )
    intelligence = load_intelligence(db, subject.id)
    plan = active_plan(db, subject.id)
    topics = load_topics(db, intelligence.id) if intelligence else []
    total = sum(t.estimated_minutes for t in topics)
    done = sum(1 for t in topics if t.status is TopicStatus.COMPLETED)
    completed_minutes = 0
    if plan:
        completed_minutes = (
            db.scalar(
                select(func.coalesce(func.sum(StudyBlock.actual_minutes), 0)).where(
                    StudyBlock.plan_id == plan.id, StudyBlock.is_break.is_(False)
                )
            )
            or 0
        )
    days_to_exam = None
    if subject.exam_date:
        days_to_exam = (subject.exam_date - utcnow().date()).days
    return {
        "id": subject.id,
        "name": subject.name,
        "code": subject.code,
        "description": subject.description,
        "color": subject.color,
        "knowledge_level": subject.knowledge_level,
        "study_mode": subject.study_mode,
        "exam_date": subject.exam_date,
        "team_id": subject.team_id,
        "owner_id": subject.owner_id,
        "daily_minutes": subject.daily_minutes,
        "start_time": subject.start_time,
        "rest_days": list(subject.rest_days or []),
        "created_at": subject.created_at,
        "document_count": int(document_count),
        "topic_count": len(topics),
        "total_minutes": total,
        "completed_minutes": int(completed_minutes),
        "progress_percent": round(100.0 * done / len(topics), 1) if topics else 0.0,
        "days_to_exam": days_to_exam,
        "has_intelligence": intelligence is not None,
        "has_active_plan": plan is not None,
    }


def time_estimates(db: Session, subject: Subject) -> dict | None:
    intelligence = load_intelligence(db, subject.id)
    if intelligence is None:
        return None
    topics = load_topics(db, intelligence.id)
    if not topics:
        return None

    by_module: dict[str, dict] = {}
    for topic in topics:
        bucket = by_module.setdefault(
            topic.module_title or "General",
            {
                "module": topic.module_title or "General",
                "minutes": 0,
                "revision_minutes": 0,
                "topics": 0,
            },
        )
        bucket["minutes"] += topic.estimated_minutes
        bucket["revision_minutes"] += topic.revision_minutes
        bucket["topics"] += 1

    counts = {d: 0 for d in Difficulty}
    minutes = {d: 0 for d in Difficulty}
    for topic in topics:
        difficulty = Difficulty(topic.difficulty)
        counts[difficulty] += 1
        minutes[difficulty] += topic.estimated_minutes

    total = sum(t.estimated_minutes for t in topics)
    revision = sum(t.revision_minutes for t in topics)
    grand = total + revision
    days_left = (subject.exam_date - utcnow().date()).days if subject.exam_date else 30
    feasible, ratio, message = estimation.feasibility(
        grand, subject.daily_minutes, max(0, days_left)
    )
    return {
        "subject_id": subject.id,
        "total_minutes": total,
        "revision_minutes": revision,
        "grand_total_minutes": grand,
        "per_module": sorted(by_module.values(), key=lambda b: -b["minutes"]),
        "days_required": -(-grand // max(1, subject.daily_minutes)),
        "feasible": feasible,
        "message": message,
        "breakdown": {
            "easy": counts[Difficulty.EASY],
            "medium": counts[Difficulty.MEDIUM],
            "hard": counts[Difficulty.HARD],
            "minutes_easy": minutes[Difficulty.EASY],
            "minutes_medium": minutes[Difficulty.MEDIUM],
            "minutes_hard": minutes[Difficulty.HARD],
        },
    }


def day_plans(db: Session, plan: StudyPlan, start: date, days: int) -> list[dict]:
    end = start + timedelta(days=max(0, days - 1))
    blocks = list(
        db.scalars(
            select(StudyBlock)
            .where(StudyBlock.plan_id == plan.id, StudyBlock.day >= start, StudyBlock.day <= end)
            .order_by(StudyBlock.day, StudyBlock.block_index, StudyBlock.position)
        ).all()
    )
    out: list[dict] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        day_blocks = [b for b in blocks if b.day == day]
        planned = sum(b.minutes for b in day_blocks if not b.is_break)
        completed = sum(
            (b.actual_minutes or b.minutes) if b.status is BlockStatus.DONE else b.actual_minutes
            for b in day_blocks
            if not b.is_break
        )
        out.append(
            {
                "day": day,
                "weekday": day.isoweekday(),
                "is_rest_day": planned == 0 and not day_blocks,
                "budget_minutes": plan.daily_budget_minutes,
                "planned_minutes": planned,
                "completed_minutes": completed,
                "completion_percent": round(100.0 * completed / planned, 1) if planned else 0.0,
                "blocks": day_blocks,
            }
        )
    return out


def subject_progress(db: Session, subject: Subject) -> dict:
    intelligence = load_intelligence(db, subject.id)
    topics = load_topics(db, intelligence.id) if intelligence else []
    today = utcnow().date()

    records = []
    if intelligence:
        records = list(
            db.scalars(
                select(ProgressRecord).where(
                    ProgressRecord.topic_id.in_([t.id for t in topics] or [0])
                )
            ).all()
        )
    per_topic: dict[int, list[ProgressRecord]] = {}
    for record in records:
        per_topic.setdefault(record.topic_id, []).append(record)

    total = sum(t.estimated_minutes for t in topics)
    completed_topics = [t for t in topics if t.status is TopicStatus.COMPLETED]
    completed_minutes = sum(t.estimated_minutes for t in completed_topics)

    by_day: dict[date, int] = {}
    for record in records:
        by_day[record.created_at.date()] = (
            by_day.get(record.created_at.date(), 0) + record.minutes_spent
        )
    series = [
        {"day": today - timedelta(days=i), "minutes": by_day.get(today - timedelta(days=i), 0)}
        for i in range(13, -1, -1)
    ]

    return {
        "subject_id": subject.id,
        "subject_name": subject.name,
        "total_minutes": total,
        "completed_minutes": completed_minutes,
        "progress_percent": round(100.0 * len(completed_topics) / len(topics), 1)
        if topics
        else 0.0,
        "topics_total": len(topics),
        "topics_completed": len(completed_topics),
        "topics_in_progress": sum(1 for t in topics if t.status is TopicStatus.IN_PROGRESS),
        "revision_minutes_completed": sum(
            r.minutes_spent for r in records if r.event == "completed" and r.minutes_spent
        ),
        "streak_days": _streak(by_day, today),
        "daily_series": series,
        "topic_progress": [
            {
                "topic_id": t.id,
                "title": t.title,
                "status": t.status,
                "knowledge_state": t.knowledge_state,
                "mastery": t.mastery,
                "minutes_spent": sum(r.minutes_spent for r in per_topic.get(t.id, [])),
                "events": len(per_topic.get(t.id, [])),
                "last_touched": max((r.created_at for r in per_topic.get(t.id, [])), default=None),
            }
            for t in topics
        ],
    }


def _streak(by_day: dict[date, int], today: date) -> int:
    streak = 0
    cursor = today
    if not by_day.get(cursor):
        cursor = today - timedelta(days=1)
    while by_day.get(cursor, 0) > 0:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def dashboard(db: Session, user: User) -> dict:
    subjects = accessible_subjects(db, user)
    summaries = [subject_summary(db, s) for s in subjects]
    today = utcnow().date()

    today_blocks: list[dict] = []
    for subject in subjects:
        plan = active_plan(db, subject.id)
        if plan is None:
            continue
        for block in db.scalars(
            select(StudyBlock)
            .where(
                StudyBlock.plan_id == plan.id,
                StudyBlock.day == today,
                StudyBlock.is_break.is_(False),
            )
            .order_by(StudyBlock.block_index)
        ).all():
            today_blocks.append(
                {
                    "id": block.id,
                    "subject_id": subject.id,
                    "subject_name": subject.name,
                    "color": subject.color,
                    "title": block.title,
                    "start_time": block.start_time,
                    "end_time": block.end_time,
                    "minutes": block.minutes,
                    "kind": block.kind,
                    "status": block.status,
                }
            )

    deadlines = [
        {
            "subject_id": s["id"],
            "name": s["name"],
            "exam_date": s["exam_date"],
            "days_left": s["days_to_exam"],
            "progress_percent": s["progress_percent"],
            "feasible": (
                time_estimates(db, next(x for x in subjects if x.id == s["id"])) or {}
            ).get("feasible", True),
        }
        for s in summaries
        if s["exam_date"] and s["days_to_exam"] is not None and s["days_to_exam"] >= 0
    ]
    deadlines.sort(key=lambda d: d["days_left"])

    plans = []
    for subject in subjects:
        plan = active_plan(db, subject.id)
        if plan is None:
            continue
        plans.append(
            {
                "id": plan.id,
                "subject_id": subject.id,
                "subject_name": subject.name,
                "color": subject.color,
                "generated_for": plan.generated_for,
                "horizon_days": (plan.meta or {}).get("horizon_days", 14),
                "planned_minutes": plan.planned_minutes,
                "daily_budget_minutes": plan.daily_budget_minutes,
                "unscheduled": len((plan.meta or {}).get("unscheduled_unit_ids", [])),
                "reason": plan.reason,
            }
        )

    membership = db.scalar(select(TeamMember).where(TeamMember.user_id == user.id))
    team_block = None
    if membership:
        team = db.get(Team, membership.team_id)
        if team:
            team_block = {
                "id": team.id,
                "name": team.name,
                "join_code": team.join_code,
                "role": membership.role,
                "members": len(team_members(db, team.id)),
                "subjects": len(team.subjects),
            }

    return {
        "subjects": summaries,
        "today": today_blocks,
        "upcoming_deadlines": deadlines,
        "plans": plans,
        "totals": {
            "subjects": len(summaries),
            "topics": sum(s["topic_count"] for s in summaries),
            "minutes_planned": sum(s["total_minutes"] for s in summaries),
            "minutes_completed": sum(s["completed_minutes"] for s in summaries),
            "blocks_today": len(today_blocks),
            "minutes_today": sum(b["minutes"] for b in today_blocks),
        },
        "team": team_block,
    }


def start_session(
    db: Session, user: User, subject_id: int | None, block_ids: list[int], notes: str
) -> StudySession:
    blocks = [db.get(StudyBlock, bid) for bid in block_ids]
    session = StudySession(
        user_id=user.id,
        subject_id=subject_id,
        day=utcnow().date(),
        planned_minutes=sum(b.minutes for b in blocks if b),
        notes=notes[:2000],
    )
    db.add(session)
    db.flush()
    return session


def end_session(
    db: Session, session: StudySession, actual_minutes: int, focus_score: float
) -> StudySession:
    session.ended_at = utcnow()
    session.actual_minutes = max(0, min(240, actual_minutes))
    session.focus_score = max(0.0, min(1.0, focus_score))
    db.flush()
    return session
