"""Planner, progress and team schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import BlockStatus, KnowledgeState, SplitStrategy, UnitType
from app.schemas.intelligence import SplitAssignment


class PlanGenerateRequest(BaseModel):
    horizon_days: int = Field(default=14, ge=1, le=90)
    daily_minutes: int | None = Field(default=None, ge=15, le=240)
    start_date: date | None = None
    include_revision: bool = True
    respect_rest_days: bool = True
    # "rebuild" discards unscheduled planned blocks; "keep_done" preserves history.
    mode: str = Field(default="rebuild", pattern=r"^(rebuild|keep_done)$")


class AvailabilityUpdate(BaseModel):
    daily_minutes: int = Field(ge=15, le=240)
    start_time: str = Field(default="18:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    rest_days: list[int] = Field(default_factory=list)
    effective_from: date | None = None


class BlockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int
    unit_id: int | None
    package_id: int | None
    topic_id: int | None
    day: date
    start_time: str
    end_time: str
    minutes: int
    block_index: int
    kind: UnitType
    title: str
    priority: float
    status: BlockStatus
    is_break: bool
    actual_minutes: int
    completed_at: datetime | None
    locked: bool
    note: str


class DayPlanOut(BaseModel):
    day: date
    weekday: int
    is_rest_day: bool
    budget_minutes: int
    planned_minutes: int
    completed_minutes: int
    completion_percent: float
    blocks: list[BlockOut]


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    generated_for: date
    week_start: date
    strategy: str
    study_mode: str
    daily_budget_minutes: int
    planned_minutes: int
    version: int
    is_active: bool
    reason: str
    meta: dict
    created_at: datetime
    days: list[DayPlanOut] = Field(default_factory=list)


class WeekSummary(BaseModel):
    week_start: date
    week_end: date
    planned_minutes: int
    completed_minutes: int
    blocks_done: int
    blocks_total: int
    by_day: list[dict]
    by_kind: list[dict]


class BlockUpdate(BaseModel):
    status: BlockStatus | None = None
    actual_minutes: int | None = Field(default=None, ge=0, le=240)
    note: str | None = Field(default=None, max_length=2000)
    locked: bool | None = None


class SessionCreate(BaseModel):
    subject_id: int | None = None
    day: date | None = None
    block_ids: list[int] = Field(default_factory=list)
    notes: str = ""


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int | None
    day: date
    started_at: datetime
    ended_at: datetime | None
    planned_minutes: int
    actual_minutes: int
    focus_score: float
    notes: str


class ProgressUpdate(BaseModel):
    topic_id: int
    event: str = Field(pattern=r"^(started|completed|partial|skipped)$")
    minutes_spent: int = Field(default=0, ge=0, le=240)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    knowledge_state: KnowledgeState | None = None
    note: str = Field(default="", max_length=2000)
    block_id: int | None = None
    session_id: int | None = None


class TopicProgressOut(BaseModel):
    topic_id: int
    title: str
    status: str
    knowledge_state: KnowledgeState
    mastery: float
    minutes_spent: int
    events: int
    last_touched: datetime | None


class SubjectProgressOut(BaseModel):
    subject_id: int
    subject_name: str
    total_minutes: int
    completed_minutes: int
    progress_percent: float
    topics_total: int
    topics_completed: int
    topics_in_progress: int
    revision_minutes_completed: int
    streak_days: int
    daily_series: list[dict]
    topic_progress: list[TopicProgressOut]


class DashboardOut(BaseModel):
    subjects: list[dict]
    today: list[dict]
    upcoming_deadlines: list[dict]
    plans: list[dict]
    totals: dict
    team: dict | None = None


# --------------------------------------------------------------------------- team
class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = ""


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    join_code: str
    description: str
    owner_id: int
    created_by_id: int
    members: list[TeamMemberOut] = Field(default_factory=list)
    subjects: list[dict] = Field(default_factory=list)
    created_at: datetime


class TeamMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    role: str
    joined_at: datetime
    full_name: str
    email: str


class TeamJoin(BaseModel):
    join_code: str = Field(min_length=4, max_length=12)


class OwnershipAssign(BaseModel):
    topic_ids: list[int]
    user_id: int
    role: str = Field(default="owner", pattern=r"^(owner|reviewer)$")
    strategy: SplitStrategy = SplitStrategy.TOPIC


class KnowledgeMatrixRow(BaseModel):
    user_id: int
    user_name: str
    cells: list[dict]
    strong_count: int
    learning_count: int
    unknown_count: int
    owned_topics: int
    coverage_percent: float


class KnowledgeMatrixOut(BaseModel):
    subject_id: int
    topic_ids: list[int]
    topics: list[dict]
    members: list[KnowledgeMatrixRow]
    uncovered_topics: list[int]
    concentration_warning: str | None = None


class PeerRecommendation(BaseModel):
    topic_id: int
    topic_title: str
    expert_id: int
    expert_name: str
    learner_ids: list[int]
    learner_names: list[str]
    reason: str
    confidence: float
    action: str = "suggest_peer_teaching"


class PeerRecommendationsOut(BaseModel):
    subject_id: int
    experts: list[dict]
    learners: list[dict]
    recommendations: list[PeerRecommendation]
    note: str = "Recommendations only. Nothing is assigned automatically."


class AssignmentApplyRequest(BaseModel):
    strategy: SplitStrategy
    assignments: list[SplitAssignment] = Field(default_factory=list)


TeamOut.model_rebuild()
