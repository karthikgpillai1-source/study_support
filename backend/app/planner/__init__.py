"""Planner Engine: study intelligence + availability + deadlines -> a plan.

Pure deterministic Python. No LLM is involved anywhere in this package.
"""

from app.planner.adaptive import (
    AdaptiveAction,
    AdaptiveResult,
    ExecutionSnapshot,
    analyse,
    remaining_minutes,
)
from app.planner.rules import (
    BLOCKS_BEFORE_BREAK,
    BREAK_MINUTES,
    DEFAULT_RULES,
    MAX_BLOCK_MINUTES,
    MAX_DAILY_STUDY_MINUTES,
    MIN_BLOCK_MINUTES,
    PlannerRules,
    TimeContext,
    UnitCandidate,
    effective_daily_budget,
    priority,
)
from app.planner.scheduler import (
    DaySchedule,
    ScheduledBlock,
    ScheduleResult,
    build_schedule,
    revision_offsets,
)

__all__ = [
    "AdaptiveAction",
    "AdaptiveResult",
    "BLOCKS_BEFORE_BREAK",
    "BREAK_MINUTES",
    "DEFAULT_RULES",
    "DaySchedule",
    "ExecutionSnapshot",
    "MAX_BLOCK_MINUTES",
    "MAX_DAILY_STUDY_MINUTES",
    "MIN_BLOCK_MINUTES",
    "PlannerRules",
    "ScheduleResult",
    "ScheduledBlock",
    "TimeContext",
    "UnitCandidate",
    "analyse",
    "build_schedule",
    "effective_daily_budget",
    "priority",
    "remaining_minutes",
    "revision_offsets",
]
