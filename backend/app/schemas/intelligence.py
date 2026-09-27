"""Study intelligence, topic, package and split-suggestion schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import (
    Difficulty,
    KnowledgeState,
    PackageType,
    SplitStrategy,
    TopicStatus,
    UnitType,
)


class TopicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    module_title: str
    title: str
    position: int
    difficulty: Difficulty
    estimated_minutes: int
    revision_minutes: int
    importance: float
    keywords: list[str]
    learning_objectives: list[str]
    definitions: list[str]
    procedures: list[str]
    formulas: list[str]
    important_facts: list[str]
    subtopics: list[str]
    concepts: list[str]
    status: TopicStatus
    knowledge_state: KnowledgeState
    mastery: float


class ModuleOut(BaseModel):
    title: str
    position: int
    estimated_minutes: int
    topic_ids: list[int]
    summary: str = ""


class IntelligenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    source: str
    summary: str
    modules: list[dict]
    keywords: list[str]
    learning_objectives: list[str]
    formulas: list[str]
    total_minutes: int
    topic_count: int
    confidence: float
    created_at: datetime
    topics: list[TopicOut]


class DifficultyBreakdown(BaseModel):
    easy: int
    medium: int
    hard: int
    minutes_easy: int
    minutes_medium: int
    minutes_hard: int


class TimeEstimateOut(BaseModel):
    subject_id: int
    total_minutes: int
    revision_minutes: int
    grand_total_minutes: int
    per_module: list[dict]
    days_required: int
    feasible: bool
    message: str
    breakdown: DifficultyBreakdown


class AnalysisOut(BaseModel):
    """Everything the Analysis screen needs in one round trip."""

    subject: dict
    intelligence: IntelligenceOut | None
    estimates: TimeEstimateOut | None
    packages: list[PackageOut]
    warnings: list[str] = Field(default_factory=list)


class UnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    package_id: int
    topic_id: int | None
    type: UnitType
    title: str
    position: int
    minutes: int
    objectives: list[str]
    resources: list[str]
    done: bool


class PackageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    type: PackageType
    title: str
    position: int
    total_minutes: int
    difficulty: Difficulty
    topic_ids: list[int]
    revision_of_package_id: int | None
    suggested_owner_id: int | None
    completed: bool
    units: list[UnitOut]


class PackagesOut(BaseModel):
    subject_id: int
    strategy: str
    max_minutes_per_package: int
    packages: list[PackageOut]


class SplitSuggestion(BaseModel):
    strategy: SplitStrategy
    label: str
    rationale: str
    total_minutes: int
    assignments: list[SplitAssignment]


class SplitAssignment(BaseModel):
    user_id: int
    user_name: str
    package_ids: list[int]
    topic_ids: list[int]
    minutes: float
    difficulty_load: dict[str, int]
    balance_score: float
    teaching_topics: list[str] = Field(default_factory=list)
    revision_topic_ids: list[int] = Field(default_factory=list)
    note: str = ""


class TeamSplitOut(BaseModel):
    subject_id: int
    suggestions: list[SplitSuggestion]
    generated_at: datetime


AnalysisOut.model_rebuild()
SplitSuggestion.model_rebuild()
