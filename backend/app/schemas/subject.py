"""Subject, upload and analysis schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import KnowledgeLevel, StudyMode


class SubjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    code: str = Field(default="", max_length=40)
    description: str = ""
    knowledge_level: KnowledgeLevel = KnowledgeLevel.BEGINNER
    exam_date: date | None = None
    study_mode: StudyMode = StudyMode.FAST_EXAM
    color: str = Field(default="#6366f1", max_length=16)
    daily_minutes: int = Field(default=120, ge=15, le=240)
    start_time: str = Field(default="18:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    rest_days: list[int] = Field(default_factory=list)
    team_id: int | None = None

    @field_validator("rest_days")
    @classmethod
    def _validate_rest_days(cls, v: list[int]) -> list[int]:
        for day in v:
            if day not in range(1, 8):
                raise ValueError("rest_days must contain ISO weekday numbers 1..7 (Mon=1)")
        return sorted(set(v))


class SubjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    code: str | None = None
    description: str | None = None
    knowledge_level: KnowledgeLevel | None = None
    exam_date: date | None = None
    study_mode: StudyMode | None = None
    color: str | None = None
    daily_minutes: int | None = Field(default=None, ge=15, le=240)
    start_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    rest_days: list[int] | None = None


class SubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    description: str
    knowledge_level: KnowledgeLevel
    exam_date: date | None
    study_mode: StudyMode
    color: str
    daily_minutes: int
    start_time: str
    rest_days: list[int]
    owner_id: int | None
    team_id: int | None
    created_at: datetime
    document_count: int = 0
    topic_count: int = 0
    total_minutes: int = 0
    completed_minutes: int = 0
    progress_percent: float = 0.0
    days_to_exam: int | None = None
    has_intelligence: bool = False
    has_active_plan: bool = False


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    filename: str
    content_type: str
    size_bytes: int
    page_count: int
    word_count: int
    status: str
    extractor: str
    warnings: list[str]
    created_at: datetime


class UploadResult(BaseModel):
    document: DocumentOut
    text_preview: str
    characters: int
