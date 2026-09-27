"""SQLAlchemy ORM models.

SQLite today; the models stay portable so the same schema can move to
PostgreSQL by changing ``DATABASE_URL``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.enums import (
    BlockStatus,
    Difficulty,
    KnowledgeLevel,
    KnowledgeState,
    PackageType,
    StrEnum,
    StudyMode,
    TopicStatus,
    UnitType,
    utcnow,
)


def enum_column(python_enum: type[StrEnum], name: str) -> SAEnum:
    """A VARCHAR-backed SQLAlchemy Enum that stores the enum *value*.

    Storing values (not names) keeps the database human-readable and portable to
    PostgreSQL, while SQLAlchemy still coerces rows back into the Python enum so
    ``subject.knowledge_level.rank`` works after a commit/refresh cycle.
    """
    return SAEnum(
        python_enum,
        name=name,
        native_enum=False,
        validate_strings=True,
        values_callable=lambda e: [member.value for member in e],
    )


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


# --------------------------------------------------------------------------- auth
class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Default availability profile used when a student does not override per subject.
    daily_minutes: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    preferred_start_time: Mapped[str] = mapped_column(String(5), default="18:00", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)

    memberships: Mapped[list[TeamMember]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    subjects: Mapped[list[Subject]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


# --------------------------------------------------------------------------- teams
class Team(Base, TimestampMixin):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    join_code: Mapped[str] = mapped_column(String(12), unique=True, index=True, nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    description: Mapped[str] = mapped_column(Text, default="")

    members: Mapped[list[TeamMember]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )
    subjects: Mapped[list[Subject]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )


class TeamMember(Base, TimestampMixin):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member", nullable=False)  # owner|member
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    # Topic-ownership assignments, list of {"package_id": int, "strategy": str}
    assignments: Mapped[list[Any]] = mapped_column(JSON, default=list)

    team: Mapped[Team] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


# --------------------------------------------------------------------------- subjects
class Subject(Base, TimestampMixin):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    code: Mapped[str] = mapped_column(String(40), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    knowledge_level: Mapped[KnowledgeLevel] = mapped_column(
        enum_column(KnowledgeLevel, "knowledge_level"),
        default=KnowledgeLevel.BEGINNER,
        nullable=False,
    )
    exam_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    study_mode: Mapped[StudyMode] = mapped_column(
        enum_column(StudyMode, "study_mode"), default=StudyMode.FAST_EXAM, nullable=False
    )
    color: Mapped[str] = mapped_column(String(16), default="#6366f1", nullable=False)
    # Student availability for this subject (falls back to user defaults)
    daily_minutes: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    start_time: Mapped[str] = mapped_column(String(5), default="18:00", nullable=False)
    rest_days: Mapped[list[Any]] = mapped_column(JSON, default=list)  # ISO weekday numbers 1..7

    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )

    owner: Mapped[User | None] = relationship(back_populates="subjects")
    team: Mapped[Team | None] = relationship(back_populates="subjects")
    documents: Mapped[list[Document]] = relationship(
        back_populates="subject", cascade="all, delete-orphan"
    )
    intelligence: Mapped[StudyIntelligence | None] = relationship(
        back_populates="subject", cascade="all, delete-orphan", uselist=False
    )
    packages: Mapped[list[WorkPackage]] = relationship(
        back_populates="subject", cascade="all, delete-orphan"
    )
    plans: Mapped[list[StudyPlan]] = relationship(
        back_populates="subject", cascade="all, delete-orphan"
    )


# --------------------------------------------------------------------------- documents
class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stored_path: Mapped[str] = mapped_column(String(512), default="")
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="extracted", nullable=False)
    extractor: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    warnings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    subject: Mapped[Subject] = relationship(back_populates="documents")


# ------------------------------------------------------------------- intelligence
class StudyIntelligence(Base, TimestampMixin):
    """Structured knowledge extracted from a subject's documents."""

    __tablename__ = "study_intelligence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), unique=True, index=True
    )
    source: Mapped[str] = mapped_column(String(32), default="heuristic", nullable=False)
    # heuristic | gemini | local_llm
    summary: Mapped[str] = mapped_column(Text, default="")
    modules: Mapped[list[Any]] = mapped_column(JSON, default=list)
    keywords: Mapped[list[Any]] = mapped_column(JSON, default=list)
    learning_objectives: Mapped[list[Any]] = mapped_column(JSON, default=list)
    formulas: Mapped[list[Any]] = mapped_column(JSON, default=list)
    total_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    topic_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    subject: Mapped[Subject] = relationship(back_populates="intelligence")
    topics: Mapped[list[Topic]] = relationship(
        back_populates="intelligence", cascade="all, delete-orphan"
    )


class Topic(Base, TimestampMixin):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    intelligence_id: Mapped[int] = mapped_column(
        ForeignKey("study_intelligence.id", ondelete="CASCADE"), index=True
    )
    module_title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    difficulty: Mapped[Difficulty] = mapped_column(
        enum_column(Difficulty, "topic_difficulty"), default=Difficulty.MEDIUM, nullable=False
    )
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    revision_minutes: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    # 0..1 how important / exam-relevant this topic is
    importance: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    keywords: Mapped[list[Any]] = mapped_column(JSON, default=list)
    learning_objectives: Mapped[list[Any]] = mapped_column(JSON, default=list)
    definitions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    procedures: Mapped[list[Any]] = mapped_column(JSON, default=list)
    formulas: Mapped[list[Any]] = mapped_column(JSON, default=list)
    important_facts: Mapped[list[Any]] = mapped_column(JSON, default=list)
    subtopics: Mapped[list[Any]] = mapped_column(JSON, default=list)
    concepts: Mapped[list[Any]] = mapped_column(JSON, default=list)
    source_excerpt: Mapped[str] = mapped_column(Text, default="")

    # execution state
    status: Mapped[TopicStatus] = mapped_column(
        enum_column(TopicStatus, "topic_status"), default=TopicStatus.PENDING, index=True
    )
    knowledge_state: Mapped[KnowledgeState] = mapped_column(
        enum_column(KnowledgeState, "knowledge_state"),
        default=KnowledgeState.UNKNOWN,
        nullable=False,
    )
    mastery: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    intelligence: Mapped[StudyIntelligence] = relationship(back_populates="topics")
    units: Mapped[list[StudyUnit]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
    )
    progress_events: Mapped[list[ProgressRecord]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
    )


# ------------------------------------------------------------------------- packages
class WorkPackage(Base, TimestampMixin):
    """A <=90 minute unit of work: topic groups, study units or revision units."""

    __tablename__ = "work_packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    intelligence_id: Mapped[int | None] = mapped_column(
        ForeignKey("study_intelligence.id", ondelete="CASCADE")
    )
    type: Mapped[PackageType] = mapped_column(
        enum_column(PackageType, "package_type"), default=PackageType.STUDY, nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    difficulty: Mapped[Difficulty] = mapped_column(
        enum_column(Difficulty, "package_difficulty"), default=Difficulty.MEDIUM, nullable=False
    )
    topic_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    revision_of_package_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_packages.id", ondelete="SET NULL")
    )
    suggested_owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    subject: Mapped[Subject] = relationship(back_populates="packages")
    units: Mapped[list[StudyUnit]] = relationship(
        back_populates="package", cascade="all, delete-orphan"
    )


class StudyUnit(Base, TimestampMixin):
    """Smallest schedulable slice; always between 10 and 30 minutes."""

    __tablename__ = "study_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    package_id: Mapped[int] = mapped_column(
        ForeignKey("work_packages.id", ondelete="CASCADE"), index=True
    )
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"))
    type: Mapped[UnitType] = mapped_column(
        enum_column(UnitType, "unit_type"), default=UnitType.LEARN, nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    objectives: Mapped[list[Any]] = mapped_column(JSON, default=list)
    resources: Mapped[list[Any]] = mapped_column(JSON, default=list)
    done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    package: Mapped[WorkPackage] = relationship(back_populates="units")
    topic: Mapped[Topic | None] = relationship(back_populates="units")


# --------------------------------------------------------------------------- plans
class StudyPlan(Base, TimestampMixin):
    __tablename__ = "study_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    generated_for: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    week_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(24), default="balanced")
    study_mode: Mapped[str] = mapped_column(String(20), default=StudyMode.FAST_EXAM)
    daily_budget_minutes: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    planned_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reason: Mapped[str] = mapped_column(String(300), default="")
    # Deterministic planner rationale: rules applied + per-day loads.
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    subject: Mapped[Subject] = relationship(back_populates="plans")
    blocks: Mapped[list[StudyBlock]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="StudyBlock.position"
    )


class StudyBlock(Base, TimestampMixin):
    __tablename__ = "study_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("study_plans.id", ondelete="CASCADE"), index=True
    )
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("study_units.id", ondelete="SET NULL"))
    package_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_packages.id", ondelete="SET NULL")
    )
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)
    end_time: Mapped[str] = mapped_column(String(5), nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    block_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    kind: Mapped[UnitType] = mapped_column(
        enum_column(UnitType, "block_kind"), default=UnitType.LEARN, nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    priority: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[BlockStatus] = mapped_column(
        enum_column(BlockStatus, "block_status"), default=BlockStatus.PLANNED, index=True
    )
    is_break: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    actual_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="")

    plan: Mapped[StudyPlan] = relationship(back_populates="blocks")
    unit: Mapped[StudyUnit | None] = relationship()
    package: Mapped[WorkPackage | None] = relationship()
    topic: Mapped[Topic | None] = relationship()


# ----------------------------------------------------------------- progress/session
class StudySession(Base, TimestampMixin):
    """A real study sitting: one or more blocks actually executed."""

    __tablename__ = "study_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    planned_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    actual_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    focus_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="")

    events: Mapped[list[ProgressRecord]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class ProgressRecord(Base, TimestampMixin):
    __tablename__ = "progress_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("study_sessions.id", ondelete="SET NULL")
    )
    block_id: Mapped[int | None] = mapped_column(ForeignKey("study_blocks.id", ondelete="SET NULL"))
    event: Mapped[str] = mapped_column(String(20), nullable=False)
    minutes_spent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="")

    topic: Mapped[Topic] = relationship(back_populates="progress_events")
    session: Mapped[StudySession | None] = relationship(back_populates="events")


# ------------------------------------------------------------- team intelligence
class TopicOwnership(Base, TimestampMixin):
    """Accepted (not merely suggested) topic ownership for a team subject."""

    __tablename__ = "topic_ownership"
    __table_args__ = (UniqueConstraint("topic_id", "user_id", name="uq_topic_owner"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="owner", nullable=False)  # owner|reviewer
    strategy: Mapped[str] = mapped_column(String(20), default="topic", nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PeerSignal(Base, TimestampMixin):
    """Observed peer-teaching signal used for recommendations only."""

    __tablename__ = "peer_signals"
    __table_args__ = (UniqueConstraint("topic_id", "user_id", name="uq_peer_signal"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # taught|mastered|struggling
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    note: Mapped[str] = mapped_column(String(300), default="")
