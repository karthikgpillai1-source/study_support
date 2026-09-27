"""Domain-wide enums shared by persistence models, schemas and the engines."""

from __future__ import annotations

import enum
from datetime import UTC, date, datetime, time, timedelta
from typing import TypeVar

StrEnumT = TypeVar("StrEnumT", bound="StrEnum")


class StrEnum(enum.StrEnum):
    """String enum with case-insensitive lookup.

    Query parameters and JSON both arrive in whatever case the client prefers
    (``"Fast_Exam"``, ``"FAST_EXAM"``), so parsing accepts any casing.
    """

    @classmethod
    def _missing_(cls: type[StrEnumT], value: object) -> StrEnumT | None:
        if isinstance(value, str):
            for member in cls:
                if member.value.lower() == value.lower() or member.name.lower() == value.lower():
                    return member
        return None


class KnowledgeLevel(StrEnum):
    NOVICE = "novice"
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"

    @property
    def rank(self) -> int:
        return _KNOWLEDGE_RANK[self]

    @classmethod
    def from_rank(cls, rank: int) -> KnowledgeLevel:
        rank = max(1, min(5, int(rank)))
        return _RANK_KNOWLEDGE[rank]

    @property
    def label(self) -> str:
        return self.value.capitalize()

    @property
    def description(self) -> str:
        return _KNOWLEDGE_DESCRIPTION[self]


_KNOWLEDGE_RANK: dict[KnowledgeLevel, int] = {
    KnowledgeLevel.NOVICE: 1,
    KnowledgeLevel.BEGINNER: 2,
    KnowledgeLevel.INTERMEDIATE: 3,
    KnowledgeLevel.ADVANCED: 4,
    KnowledgeLevel.EXPERT: 5,
}

_RANK_KNOWLEDGE: dict[int, KnowledgeLevel] = {v: k for k, v in _KNOWLEDGE_RANK.items()}

_KNOWLEDGE_DESCRIPTION: dict[KnowledgeLevel, str] = {
    KnowledgeLevel.NOVICE: "New to this subject - build foundations from scratch.",
    KnowledgeLevel.BEGINNER: "Recall the basics, needs guided coverage.",
    KnowledgeLevel.INTERMEDIATE: "Comfortable with fundamentals, needs depth and practice.",
    KnowledgeLevel.ADVANCED: "Strong grasp, focus on nuance, edge cases and application.",
    KnowledgeLevel.EXPERT: "Near mastery - prioritise verification and revision.",
}


class StudyMode(StrEnum):
    FAST_EXAM = "fast_exam"
    COLLEGE_PACE = "college_pace"

    @property
    def label(self) -> str:
        return "Fast exam preparation" if self is StudyMode.FAST_EXAM else "Follow college pace"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"

    @property
    def rank(self) -> int:
        return _DIFFICULTY_RANK[self]

    @property
    def label(self) -> str:
        return self.value.capitalize()


_DIFFICULTY_RANK: dict[Difficulty, int] = {
    Difficulty.EASY: 1,
    Difficulty.MEDIUM: 2,
    Difficulty.HARD: 3,
}
_RANK_DIFFICULTY: dict[int, Difficulty] = {v: k for k, v in _DIFFICULTY_RANK.items()}


class UnitType(StrEnum):
    LEARN = "learn"
    PRACTICE = "practice"
    TEACH = "teach"
    REVISION = "revision"
    MOCK_TEST = "mock_test"
    BREAK = "break"  # scheduled rest between study blocks; never counts as work


class PackageType(StrEnum):
    STUDY = "study"
    REVISION = "revision"


class TopicStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class BlockStatus(StrEnum):
    PLANNED = "planned"
    DONE = "done"
    PARTIAL = "partial"
    MISSED = "missed"
    SKIPPED = "skipped"


class KnowledgeState(StrEnum):
    UNKNOWN = "unknown"
    LEARNING = "learning"
    FAMILIAR = "familiar"
    STRONG = "strong"
    MASTERED = "mastered"


class ProgressEvent(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    PARTIAL = "partial"
    SKIPPED = "skipped"


class SplitStrategy(StrEnum):
    TOPIC = "topic"
    DIFFICULTY = "difficulty"
    TIME = "time"
    TEACHING = "teaching"
    REVISION = "revision"


def utcnow() -> datetime:
    return datetime.now(UTC)


def today() -> date:
    return utcnow().date()


def week_start(d: date) -> date:
    """Monday of the ISO week containing ``d``."""
    return d - timedelta(days=d.weekday())


def combine(day: date, block_time: time) -> datetime:
    return datetime.combine(day, block_time, tzinfo=UTC)
