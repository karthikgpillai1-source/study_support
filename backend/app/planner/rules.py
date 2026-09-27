"""Planner Engine hard rules and the priority formula.

Everything here is deterministic by design. The spec is explicit: LLMs never
drive planning. Given the same inputs this module always produces the same
schedule, which is what makes the planner testable and trustworthy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# ------------------------------------------------------------------ hard limits
MAX_DAILY_STUDY_MINUTES = 240  # spec: maximum study time per day
MIN_BLOCK_MINUTES = 10  # spec: study block 10-30 minutes
MAX_BLOCK_MINUTES = 30
BREAK_MINUTES = 10  # spec: break after two blocks
BLOCKS_BEFORE_BREAK = 2
MAX_PACKAGE_MINUTES = 90  # spec: maximum package size
SPIKE_MINUTES = 8  # deliberate over-allocation, never above the daily cap

# ------------------------------------------------------------------- weighting
DEADLINE_WEIGHT = 0.42  # how urgent is it
GAP_WEIGHT = 0.30  # how much does the student not know this yet
MASTERY_WEIGHT = 0.18  # what the student already has
MODE_WEIGHT = 0.10  # study-mode shaping

# Revision intervals (days after first learning) per study mode.
FAST_EXAM_REVISION_GAPS = (1, 3, 7)
COLLEGE_PACE_REVISION_GAPS = (3, 10, 21)


@dataclass(frozen=True, slots=True)
class PlannerRules:
    max_daily_minutes: int = MAX_DAILY_STUDY_MINUTES
    min_block_minutes: int = MIN_BLOCK_MINUTES
    max_block_minutes: int = MAX_BLOCK_MINUTES
    break_minutes: int = BREAK_MINUTES
    blocks_before_break: int = BLOCKS_BEFORE_BREAK
    max_package_minutes: int = MAX_PACKAGE_MINUTES
    spike_minutes: int = SPIKE_MINUTES

    def clamp_daily(self, minutes: int) -> int:
        return max(self.min_block_minutes, min(self.max_daily_minutes, int(minutes)))


DEFAULT_RULES = PlannerRules()


@dataclass(slots=True)
class UnitCandidate:
    """A schedulable unit as the planner sees it - no ORM, no LLM."""

    unit_id: int
    package_id: int
    topic_id: int | None
    title: str
    minutes: int
    kind: str
    difficulty: int  # 1..3
    importance: float  # 0..1
    mastery: float  # 0..1
    status: str  # pending | in_progress | completed | skipped
    is_revision: bool
    revision_round: int = 0
    prerequisites: list[int] = field(default_factory=list)  # topic_ids


@dataclass(slots=True)
class TimeContext:
    """The availability + deadline facts the priority formula consumes."""

    today: date
    exam_date: date | None
    daily_minutes: int
    study_mode: str
    knowledge_level_rank: int


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def deadline_pressure(day: date, exam_date: date | None) -> float:
    """1.0 when the exam is today, decaying as the date recedes.

    Uses a hyperbolic curve so "tomorrow" is nearly as urgent as "today", which
    matches how students actually revise. With no exam date the pressure sits at
    a gentle 0.25 - deliberately *below* the value for a real deadline about two
    weeks out, so a dated exam always outranks an undated subject.
    """
    if exam_date is None:
        return 0.25
    days_left = (exam_date - day).days
    if days_left <= 0:
        return 1.0
    if days_left >= 60:
        return 0.05
    return clamp(1.0 / (1.0 + days_left / 6.0))


def knowledge_gap(mastery: float, knowledge_rank: int, is_revision: bool) -> float:
    """How much unlearned material this unit represents.

    Declared knowledge level shifts the whole curve: a novice's untouched topics
    count for more, an expert's for less.
    """
    if is_revision:
        # Revising something already partly learned: gap is the residual.
        return clamp(1.0 - mastery) * 0.7
    base = clamp(1.0 - mastery)
    adjustment = 1.0 + (3 - knowledge_rank) * 0.13
    return clamp(base * adjustment)


def mastery_bonus(mastery: float, is_revision: bool) -> float:
    """Confident material still deserves a slot, just not the first one."""
    if is_revision:
        return clamp(mastery)  # consolidating a strong topic is high value
    return clamp(mastery) * 0.6


def mode_factor(kind: str, study_mode: str, horizon_days: int, exam_date: date | None) -> float:
    """Study-mode shaping: fast exam compresses everything, college pace steadies it."""
    is_fast = study_mode == "fast_exam"
    if kind == "revision":
        return 0.75 if is_fast else 1.0
    if is_fast:
        # With a near exam, protect learn units over consolidation.
        return 1.0
    if horizon_days >= 14:
        return 1.0
    return 0.9  # college pace: front-load less, leave room for the weekly cycle


def priority(candidate: UnitCandidate, context: TimeContext) -> float:
    """The spec's priority formula, as a 0..1 score. Higher = schedule sooner."""
    pressure = deadline_pressure(context.today, context.exam_date)
    gap = knowledge_gap(candidate.mastery, context.knowledge_level_rank, candidate.is_revision)
    mastery = mastery_bonus(candidate.mastery, candidate.is_revision)
    difficulty = clamp((candidate.difficulty - 1) / 2.0)

    score = (
        DEADLINE_WEIGHT * pressure
        + GAP_WEIGHT * gap
        + MASTERY_WEIGHT * (mastery + difficulty * 0.35)
        + MODE_WEIGHT
        * (
            candidate.importance * 0.6
            + mode_factor(candidate.kind, context.study_mode, 14, context.exam_date) * 0.4
        )
    )
    # Status adjustments: done work never outranks pending work.
    if candidate.status == "completed":
        score *= 0.05
    elif candidate.status == "in_progress":
        score *= 0.9
    elif candidate.status == "skipped":
        score *= 0.6
    return round(clamp(score), 4)


def effective_daily_budget(
    daily_minutes: int,
    exam_date: date | None,
    today: date,
    study_mode: str,
    *,
    rules: PlannerRules = DEFAULT_RULES,
) -> int:
    """Daily budget, tightened as an exam approaches but never above the cap.

    A cramming phase is simulated rather than left to the student: in the last
    few days before an exam, the budget is reallocated to the highest-yield
    material, which is expressed here as a *reduction* to protect sleep and
    focus rather than a heroic all-nighter.
    """
    budget = rules.clamp_daily(daily_minutes)
    if exam_date is None or study_mode != "fast_exam":
        return budget
    days_left = (exam_date - today).days
    if days_left <= 1:
        return min(budget, int(budget * 0.7))  # exam-eve: consolidation over cramming
    if days_left <= 3:
        return min(budget, int(budget * 0.85))
    return budget


def utilisation(planned_minutes: int, budget: int) -> float:
    return round(min(1.0, planned_minutes / budget), 4) if budget else 0.0
