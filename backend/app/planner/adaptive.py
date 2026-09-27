"""Adaptive replanning.

Detects that reality diverged from the plan and produces a *reason* plus the
inputs the caller should change. Deterministic: same execution history always
yields the same adjustment.

Triggers (from the spec):
* the student fell behind
* the student finished early
* availability changed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.planner.rules import TimeContext, UnitCandidate, deadline_pressure, priority

# Completion-rate thresholds.
BEHIND_RATIO = 0.7  # planned vs completed minutes
AHEAD_RATIO = 1.15
MIN_SAMPLE_MINUTES = 60


@dataclass(slots=True)
class ExecutionSnapshot:
    """What actually happened, as measured by the progress endpoints."""

    as_of: date
    planned_minutes: int
    completed_minutes: int
    missed_minutes: int
    topics_completed: int
    topics_pending: int
    overdue_units: int
    availability_changed: bool = False
    new_daily_minutes: int | None = None

    @property
    def completion_ratio(self) -> float:
        if self.planned_minutes <= 0:
            return 1.0
        return self.completed_minutes / self.planned_minutes

    @property
    def behind(self) -> bool:
        return self.planned_minutes >= MIN_SAMPLE_MINUTES and self.completion_ratio < BEHIND_RATIO

    @property
    def ahead(self) -> bool:
        return self.planned_minutes >= MIN_SAMPLE_MINUTES and self.completion_ratio > AHEAD_RATIO


@dataclass(slots=True)
class AdaptiveAction:
    kind: str
    label: str
    rationale: str
    daily_minutes: int | None = None
    horizon_days: int | None = None
    include_revision: bool | None = None
    scope: str = "future"  # future | full

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "rationale": self.rationale,
            "daily_minutes": self.daily_minutes,
            "horizon_days": self.horizon_days,
            "include_revision": self.include_revision,
            "scope": self.scope,
        }


@dataclass(slots=True)
class AdaptiveResult:
    status: str  # on_track | behind | ahead | availability_changed | complete
    summary: str
    actions: list[AdaptiveAction] = field(default_factory=list)
    remaining_minutes: int = 0
    required_daily_minutes: int = 0
    days_left: int | None = None
    feasible: bool = True

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "summary": self.summary,
            "actions": [a.as_dict() for a in self.actions],
            "remaining_minutes": self.remaining_minutes,
            "required_daily_minutes": self.required_daily_minutes,
            "days_left": self.days_left,
            "feasible": self.feasible,
        }


def remaining_minutes(units: list[UnitCandidate], *, include_revision: bool = True) -> int:
    return sum(
        u.minutes
        for u in units
        if u.status != "completed" and (include_revision or not u.is_revision)
    )


def analyse(
    units: list[UnitCandidate],
    snapshot: ExecutionSnapshot,
    *,
    current_daily_minutes: int,
    exam_date: date | None,
    study_mode: str,
    knowledge_level_rank: int,
    horizon_days: int,
    include_revision: bool = True,
) -> AdaptiveResult:
    """Decide what to change, if anything, given execution reality."""
    outstanding = [u for u in units if u.status != "completed"]
    work_left = remaining_minutes(outstanding, include_revision=include_revision)
    days_left = (exam_date - snapshot.as_of).days if exam_date else None
    if days_left is not None and days_left < 0:
        days_left = 0

    urgency = deadline_pressure(snapshot.as_of, exam_date)

    required_daily = 0
    if days_left and days_left > 0:
        required_daily = -(-work_left // days_left)  # ceil
    feasible = days_left is None or days_left == 0 or required_daily <= current_daily_minutes

    actions: list[AdaptiveAction] = []

    if snapshot.availability_changed:
        if (
            snapshot.new_daily_minutes is not None
            and snapshot.new_daily_minutes != current_daily_minutes
        ):
            actions.append(
                AdaptiveAction(
                    kind="availability_changed",
                    label=f"Daily budget is now {snapshot.new_daily_minutes} min",
                    rationale=(
                        f"You changed your available study time from {current_daily_minutes} "
                        f"to {snapshot.new_daily_minutes} minutes per day. The plan was "
                        "rebuilt against the new budget."
                    ),
                    daily_minutes=snapshot.new_daily_minutes,
                    scope="full",
                )
            )
        status = "availability_changed"
    elif not outstanding:
        status = "complete"
        return AdaptiveResult(
            status=status,
            summary="Every scheduled unit is complete. Generate a new plan to cover new material.",
            remaining_minutes=0,
            required_daily_minutes=0,
            days_left=days_left,
            feasible=True,
        )
    elif snapshot.behind:
        status = "behind"
    elif snapshot.ahead:
        status = "ahead"
    else:
        status = "on_track"

    if status == "behind":
        shortfall = snapshot.planned_minutes - snapshot.completed_minutes
        if snapshot.overdue_units:
            actions.append(
                AdaptiveAction(
                    kind="drop_lowest_yield",
                    label="Defer the lowest-yield topics",
                    rationale=(
                        f"{snapshot.overdue_units} unit(s) are overdue and you are "
                        f"{shortfall} minutes behind. Topics with the lowest "
                        "importance x deadline pressure were pushed past the exam date so the "
                        "high-yield material gets done first."
                    ),
                    scope="future",
                )
            )
        else:
            actions.append(
                AdaptiveAction(
                    kind="extend_horizon",
                    label="Extend the plan by one day",
                    rationale=(
                        f"You completed {snapshot.completed_minutes} of "
                        f"{snapshot.planned_minutes} planned minutes "
                        f"({snapshot.completion_ratio:.0%}). One more day was added so "
                        "nothing is dropped."
                    ),
                    horizon_days=horizon_days + 1,
                    scope="future",
                )
            )
        if snapshot.missed_minutes >= MIN_SAMPLE_MINUTES:
            actions.append(
                AdaptiveAction(
                    kind="revise_blocks",
                    label="Tighten study blocks",
                    rationale=(
                        f"{snapshot.missed_minutes} minutes were missed entirely. Blocks were kept "
                        "at 25 minutes and revision passes were trimmed to protect the daily cap."
                    ),
                    include_revision=include_revision
                    and work_left < required_daily * max(days_left or 1, 1),
                    scope="future",
                )
            )
    elif status == "ahead":
        actions.append(
            AdaptiveAction(
                kind="pull_forward",
                label="Pull later work forward",
                rationale=(
                    f"You are ahead of schedule ({snapshot.completion_ratio:.0%} of planned time). "
                    "The next days' work was pulled forward and gaps were refilled with the "
                    "highest-priority topics, so the exam does not arrive with time unused."
                ),
                scope="future",
            )
        )
        if days_left and days_left > 2 and urgency < 0.6:
            actions.append(
                AdaptiveAction(
                    kind="add_depth",
                    label="Add a practice pass",
                    rationale=(
                        "Spare capacity was detected well before the exam, so an extra practice "
                        "unit was scheduled for each high-importance hard topic."
                    ),
                    scope="future",
                )
            )
    elif status == "availability_changed":
        pass
    elif status == "on_track":
        if not feasible and required_daily:
            actions.append(
                AdaptiveAction(
                    kind="capacity_warning",
                    label=f"{required_daily} min/day needed, {current_daily_minutes} available",
                    rationale=(
                        f"{work_left} minutes remain over {days_left} day(s). Raise the "
                        f"daily budget to about {required_daily} minutes, or plan to "
                        "finish after the exam."
                    ),
                    daily_minutes=required_daily,
                    scope="full",
                )
            )

    summary = _summarise(
        status, snapshot, work_left, required_daily, days_left, current_daily_minutes
    )
    return AdaptiveResult(
        status=status,
        summary=summary,
        actions=actions,
        remaining_minutes=work_left,
        required_daily_minutes=required_daily,
        days_left=days_left,
        feasible=feasible,
    )


def _summarise(
    status: str,
    snapshot: ExecutionSnapshot,
    work_left: int,
    required_daily: int,
    days_left: int | None,
    current_daily_minutes: int,
) -> str:
    remaining = f"{work_left} minutes of work left"
    if days_left is not None:
        remaining += f" over {days_left} day(s) before the exam"
    if status == "behind":
        return (
            f"You are behind: {snapshot.completion_ratio:.0%} of planned time completed. "
            f"{remaining}. Consider {required_daily} min/day."
        )
    if status == "ahead":
        return (
            f"You are ahead: {snapshot.completion_ratio:.0%} of planned time completed. "
            f"{remaining} - spare capacity was used to pull work forward."
        )
    if status == "availability_changed":
        return f"Your available study time changed. The plan was rebuilt. {remaining.capitalize()}."
    if status == "complete":
        return "All planned work is complete."
    if required_daily and required_daily > current_daily_minutes:
        return (
            f"On track but tight: {remaining.capitalize()}, which needs about {required_daily} "
            f"min/day against your {current_daily_minutes} min/day budget."
        )
    return f"On track. {remaining.capitalize()}."


def apply_unit_priorities(
    units: list[UnitCandidate], context: TimeContext
) -> list[tuple[int, float]]:
    """Priority per unit, highest first - used to triage during replanning."""
    return sorted(
        ((u.unit_id, priority(u, context)) for u in units),
        key=lambda item: item[1],
        reverse=True,
    )
