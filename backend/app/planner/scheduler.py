"""Deterministic scheduler: turn study units into dated, timed blocks.

Two passes, both fully deterministic (no randomness, no clock reads):

1. **Learn pass** - score every learn unit with :func:`app.planner.rules.priority`
   and pack the highest-priority ready units into each day, up to that day's
   budget, inserting a 10-minute break after every two blocks (spec rule).
   Long units are split across days and resumed.
2. **Revision pass** - each scheduled learn block queues spaced revision passes
   (``+1/+3/+7`` days when cramming, ``+3/+10/+21`` when following college pace).
   Revision units are then packed into the leftover capacity of those days,
   competing on the same priority formula.

Given identical inputs the output is identical, which is what makes the planner
testable and reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.core.enums import UnitType
from app.planner.rules import (
    BLOCKS_BEFORE_BREAK,
    COLLEGE_PACE_REVISION_GAPS,
    DEFAULT_RULES,
    FAST_EXAM_REVISION_GAPS,
    PlannerRules,
    TimeContext,
    UnitCandidate,
    effective_daily_budget,
    priority,
)


@dataclass(slots=True)
class ScheduledBlock:
    day: date
    start_time: str
    end_time: str
    minutes: int
    block_index: int
    kind: str
    title: str
    unit_id: int | None
    package_id: int | None
    topic_id: int | None
    priority: float
    is_break: bool = False
    note: str = ""


@dataclass(slots=True)
class DaySchedule:
    day: date
    is_rest_day: bool
    budget_minutes: int
    blocks: list[ScheduledBlock] = field(default_factory=list)

    @property
    def planned_minutes(self) -> int:
        return sum(b.minutes for b in self.blocks if not b.is_break)


@dataclass(slots=True)
class ScheduleResult:
    start: date
    end: date
    days: list[DaySchedule]
    unscheduled_unit_ids: list[int]
    reason: str
    meta: dict

    @property
    def total_planned_minutes(self) -> int:
        return sum(day.planned_minutes for day in self.days)


def parse_hhmm(value: str) -> tuple[int, int]:
    try:
        hour_str, minute_str = str(value).split(":")[:2]
        hour, minute = int(hour_str), int(minute_str)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    except (ValueError, AttributeError):
        pass
    return 18, 0


def _format_hhmm(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def _cursor_on(day: date, start_clock: str) -> datetime:
    hour, minute = parse_hhmm(start_clock)
    return datetime.combine(day, datetime.min.time()) + timedelta(hours=hour, minutes=minute)


def is_rest_day(day: date, rest_days: list[int] | None) -> bool:
    return day.isoweekday() in set(rest_days or [])


def revision_offsets(study_mode: str, days_left: int | None) -> tuple[int, ...]:
    """Spaced-repetition gaps, compressed when an exam is imminent."""
    if days_left is not None and days_left <= 2:
        return (1,)
    if days_left is not None and days_left <= 5:
        return (1, 3)
    if days_left is not None and days_left <= 12:
        return (1, 3)
    if study_mode == "fast_exam":
        return FAST_EXAM_REVISION_GAPS
    return COLLEGE_PACE_REVISION_GAPS


# --------------------------------------------------------------------- placement
def _place(
    day: date,
    start_clock: str,
    placements: list[tuple[UnitCandidate, int, float]],
    budget: int,
    rules: PlannerRules,
) -> list[ScheduledBlock]:
    """Lay placements on one day, inserting the mandated breaks."""
    if not placements:
        return []
    ordered = sorted(placements, key=lambda item: (-item[2], item[0].unit_id))
    blocks: list[ScheduledBlock] = []
    cursor = _cursor_on(day, start_clock)
    used = 0
    since_break = 0
    index = 0

    for unit, minutes, score in ordered:
        if budget - used < rules.min_block_minutes:
            break
        if since_break >= BLOCKS_BEFORE_BREAK and blocks:
            blocks.append(
                ScheduledBlock(
                    day=day,
                    start_time=_format_hhmm(cursor),
                    end_time=_format_hhmm(cursor + timedelta(minutes=rules.break_minutes)),
                    minutes=rules.break_minutes,
                    block_index=index,
                    kind=UnitType.BREAK.value,
                    title="Break",
                    unit_id=None,
                    package_id=None,
                    topic_id=None,
                    priority=0.0,
                    is_break=True,
                )
            )
            cursor += timedelta(minutes=rules.break_minutes)
            index += 1
            since_break = 0

        end = cursor + timedelta(minutes=minutes)
        blocks.append(
            ScheduledBlock(
                day=day,
                start_time=_format_hhmm(cursor),
                end_time=_format_hhmm(end),
                minutes=minutes,
                block_index=index,
                kind=unit.kind,
                title=unit.title,
                unit_id=unit.unit_id,
                package_id=unit.package_id,
                topic_id=unit.topic_id,
                priority=score,
                note=(
                    f"Part of {unit.minutes} min; continues on a later day."
                    if minutes < unit.minutes
                    else ""
                ),
            )
        )
        cursor = end
        used += minutes
        index += 1
        since_break += 1

    return blocks


def _partial(unit: UnitCandidate, already: int) -> UnitCandidate:
    return UnitCandidate(
        unit_id=unit.unit_id,
        package_id=unit.package_id,
        topic_id=unit.topic_id,
        title=f"{unit.title} (cont.)",
        minutes=max(0, unit.minutes - already),
        kind=unit.kind,
        difficulty=unit.difficulty,
        importance=unit.importance,
        mastery=unit.mastery,
        status=unit.status,
        is_revision=unit.is_revision,
        revision_round=unit.revision_round,
        prerequisites=list(unit.prerequisites),
    )


# ------------------------------------------------------------------ main builder
def build_schedule(
    units: list[UnitCandidate],
    *,
    start: date,
    horizon_days: int,
    daily_minutes: int,
    start_clock: str = "18:00",
    exam_date: date | None = None,
    study_mode: str = "fast_exam",
    knowledge_level_rank: int = 2,
    rest_days: list[int] | None = None,
    include_revision: bool = True,
    rules: PlannerRules = DEFAULT_RULES,
) -> ScheduleResult:
    rest_days = list(rest_days or [])
    horizon_end = start + timedelta(days=max(0, horizon_days - 1))
    # In fast-exam mode nothing may be scheduled after the exam itself.
    last_day = (
        min(horizon_end, exam_date) if (exam_date and study_mode == "fast_exam") else horizon_end
    )
    days_left = (exam_date - start).days if exam_date else None

    context = TimeContext(
        today=start,
        exam_date=exam_date,
        daily_minutes=rules.clamp_daily(daily_minutes),
        study_mode=study_mode,
        knowledge_level_rank=knowledge_level_rank,
    )

    by_id = {unit.unit_id: unit for unit in units}
    scores = {unit.unit_id: priority(unit, context) for unit in units}
    ordered = sorted(by_id, key=lambda uid: (-scores[uid], uid))

    budgets: dict[date, int] = {}
    rests: dict[date, bool] = {}
    day_list: list[date] = []
    cursor_day = start
    while cursor_day <= last_day:
        rest = is_rest_day(cursor_day, rest_days)
        rests[cursor_day] = rest
        budgets[cursor_day] = (
            0
            if rest
            else effective_daily_budget(
                daily_minutes, exam_date, cursor_day, study_mode, rules=rules
            )
        )
        day_list.append(cursor_day)
        cursor_day += timedelta(days=1)

    placed_minutes: dict[date, int] = {day: 0 for day in day_list}
    day_placements: dict[date, list[tuple[UnitCandidate, int, float]]] = {
        day: [] for day in day_list
    }
    done: set[int] = set()
    partial: dict[int, int] = {}
    covered_topics: set[int] = set()
    #: (topic_id, revision_round) -> earliest eligible day
    revision_ready: dict[tuple[int, int], date] = {}
    #: (topic_id, revision_round) -> unit id chosen to satisfy that pass
    revision_claim: dict[tuple[int, int], int] = {}

    def _room(day: date) -> int:
        return budgets[day] - placed_minutes[day]

    def _take(day: date, unit: UnitCandidate, slot: int) -> None:
        day_placements[day].append((unit, slot, scores[unit.unit_id]))
        placed_minutes[day] += slot

    def _commit(unit: UnitCandidate, day: date, total: int) -> None:
        """Finish a unit and queue its spaced revision passes."""
        done.add(unit.unit_id)
        partial.pop(unit.unit_id, None)
        if unit.topic_id is None:
            return
        covered_topics.add(unit.topic_id)
        for round_index, gap in enumerate(revision_offsets(study_mode, days_left), start=1):
            revision_ready[(unit.topic_id, round_index)] = day + timedelta(days=gap)

    # ------------------------------------------------------------- pass 1: learn
    learn_queue = [
        uid for uid in ordered if not by_id[uid].is_revision and by_id[uid].status != "completed"
    ]
    for day in day_list:
        if budgets[day] <= 0:
            continue
        for uid in learn_queue:
            if _room(day) < rules.min_block_minutes:
                break
            if uid in done:
                continue
            unit = by_id[uid]
            if unit.prerequisites and not set(unit.prerequisites) <= covered_topics:
                continue
            view = _partial(unit, partial[uid]) if uid in partial else unit
            if view.minutes < rules.min_block_minutes:
                # Nothing meaningful left; treat as finished.
                _commit(unit, day, unit.minutes)
                continue
            slot = min(view.minutes, rules.max_block_minutes, _room(day))
            if slot < rules.min_block_minutes:
                continue
            _take(day, view, slot)
            total = partial.get(uid, 0) + slot
            if total >= unit.minutes:
                _commit(unit, day, total)
            else:
                partial[uid] = total

    # ---------------------------------------------------------- pass 2: revision
    revision_queue = [
        uid for uid in ordered if by_id[uid].is_revision and by_id[uid].status != "completed"
    ]
    revision_available: set[int] = set()
    if include_revision:
        for day in day_list:
            if budgets[day] <= 0:
                continue
            # Refresh which revision units are eligible today.
            for uid in revision_queue:
                if uid in done or uid in revision_available:
                    continue
                unit = by_id[uid]
                if unit.topic_id is None:
                    continue
                key = (unit.topic_id, unit.revision_round)
                earliest = revision_ready.get(key)
                if earliest is None or day < earliest:
                    continue
                if revision_claim.get(key) not in (None, uid):
                    # Another unit already covers this topic/round.
                    continue
                revision_available.add(uid)
                revision_claim[key] = uid

            for uid in revision_queue:
                if _room(day) < rules.min_block_minutes:
                    break
                if uid in done or uid not in revision_available:
                    continue
                unit = by_id[uid]
                view = _partial(unit, partial[uid]) if uid in partial else unit
                if view.minutes < rules.min_block_minutes:
                    done.add(uid)
                    partial.pop(uid, None)
                    continue
                slot = min(view.minutes, rules.max_block_minutes, _room(day))
                if slot < rules.min_block_minutes:
                    continue
                _take(day, view, slot)
                total = partial.get(uid, 0) + slot
                if total >= unit.minutes:
                    done.add(uid)
                    partial.pop(uid, None)
                else:
                    partial[uid] = total

    # ------------------------------------------------------------------- materialise
    days: list[DaySchedule] = []
    for day in day_list:
        days.append(
            DaySchedule(
                day=day,
                is_rest_day=rests[day],
                budget_minutes=budgets[day],
                blocks=_place(day, start_clock, day_placements[day], budgets[day], rules),
            )
        )

    unscheduled = sorted(uid for uid in ordered if uid not in done)
    reason, code = _explain(days, unscheduled, by_id, exam_date, study_mode, last_day, horizon_end)

    meta = {
        "strategy": (
            "priority-weighted deterministic packing (learn pass, then spaced revision pass)"
        ),
        "reason_code": code,
        "rules": {
            "max_daily_minutes": rules.max_daily_minutes,
            "block_minutes": [rules.min_block_minutes, rules.max_block_minutes],
            "break_minutes": rules.break_minutes,
            "blocks_before_break": rules.blocks_before_break,
            "max_package_minutes": rules.max_package_minutes,
        },
        "revision_offsets_days": list(revision_offsets(study_mode, days_left)),
        "days_left_at_start": days_left,
        "horizon_days": horizon_days,
        "daily_budgets": {str(d.day): d.budget_minutes for d in days},
        "unscheduled_unit_ids": unscheduled,
        "partial_unit_ids": sorted(partial),
    }
    return ScheduleResult(
        start=start,
        end=last_day,
        days=days,
        unscheduled_unit_ids=unscheduled,
        reason=reason,
        meta=meta,
    )


def _explain(
    days: list[DaySchedule],
    unscheduled: list[int],
    by_id: dict[int, UnitCandidate],
    exam_date: date | None,
    study_mode: str,
    last_day: date,
    horizon_end: date,
) -> tuple[str, str]:
    available = [d for d in days if not d.is_rest_day and d.budget_minutes > 0]
    loaded = [d for d in days if d.planned_minutes > 0]
    capacity = sum(d.budget_minutes for d in available)
    scheduled = sum(d.planned_minutes for d in days)
    if not by_id:
        return "No study units to schedule. Upload notes and run analysis first.", "empty"
    if not available:
        return (
            "Every day in the horizon is a rest day. Remove at least one rest day or "
            "extend the horizon.",
            "no_active_days",
        )
    if not unscheduled:
        spare = capacity - scheduled
        detail = (
            f"Scheduled every one of the {len(by_id)} unit(s) across {len(loaded)} of "
            f"{len(available)} available day(s): {scheduled} of {capacity} minutes used"
        )
        if spare > 0:
            detail += (
                f", leaving {spare} minutes spare. Pull later work forward or add a "
                "subject to make use of it"
            )
        return f"{detail}.", "fully_scheduled"
    backlog = sum(by_id[uid].minutes for uid in unscheduled)
    if last_day < horizon_end:
        return (
            f"{len(unscheduled)} unit(s) ({backlog} min) did not fit before the exam "
            "date. Raise the daily budget, extend past the exam, or accept these as "
            "post-exam material.",
            "exam_horizon_short",
        )
    return (
        f"{len(unscheduled)} unit(s) ({backlog} min) exceed the {capacity} minutes "
        f"available over {len(available)} day(s). Raise the daily budget, add study "
        "days, or reduce the workload.",
        "capacity_short",
    )
