"""Planner Engine: rules, priority formula, scheduling, adaptive replanning."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.enums import BlockStatus
from app.planner.adaptive import ExecutionSnapshot, analyse, remaining_minutes
from app.planner.rules import (
    BREAK_MINUTES,
    DEFAULT_RULES,
    MAX_BLOCK_MINUTES,
    MAX_DAILY_STUDY_MINUTES,
    MIN_BLOCK_MINUTES,
    TimeContext,
    UnitCandidate,
    deadline_pressure,
    effective_daily_budget,
    priority,
)
from app.planner.scheduler import build_schedule, revision_offsets

TODAY = date(2026, 3, 2)  # a Monday, so weekday maths is predictable


def unit(uid: int, minutes: int = 25, **kwargs) -> UnitCandidate:
    defaults = dict(
        package_id=1,
        topic_id=uid,
        title=f"Unit {uid}",
        kind="learn",
        difficulty=2,
        importance=0.5,
        mastery=0.0,
        status="pending",
        is_revision=False,
        revision_round=0,
    )
    defaults.update(kwargs)
    return UnitCandidate(unit_id=uid, minutes=minutes, **defaults)


def context(**kwargs) -> TimeContext:
    defaults = dict(
        today=TODAY,
        exam_date=TODAY + timedelta(days=14),
        daily_minutes=120,
        study_mode="fast_exam",
        knowledge_level_rank=2,
    )
    defaults.update(kwargs)
    return TimeContext(**defaults)


def study_blocks(result) -> list:
    return [b for day in result.days for b in day.blocks if not b.is_break]


# --------------------------------------------------------------------- hard rules
def test_planner_respects_the_spec_limits() -> None:
    assert MAX_DAILY_STUDY_MINUTES == 240
    assert (MIN_BLOCK_MINUTES, MAX_BLOCK_MINUTES) == (10, 30)
    assert BREAK_MINUTES == 10
    assert DEFAULT_RULES.blocks_before_break == 2
    assert DEFAULT_RULES.max_package_minutes == 90


def test_daily_study_time_never_exceeds_the_cap() -> None:
    units = [unit(i) for i in range(1, 200)]
    result = build_schedule(
        units, start=TODAY, horizon_days=7, daily_minutes=240, start_clock="08:00"
    )
    for day in result.days:
        assert day.planned_minutes <= MAX_DAILY_STUDY_MINUTES, (
            f"{day.day} hit {day.planned_minutes}"
        )


def test_every_study_block_is_between_ten_and_thirty_minutes() -> None:
    units = [unit(i, minutes=45) for i in range(1, 30)]
    result = build_schedule(units, start=TODAY, horizon_days=7, daily_minutes=120)
    for block in study_blocks(result):
        assert MIN_BLOCK_MINUTES <= block.minutes <= MAX_BLOCK_MINUTES


def test_break_is_inserted_after_every_two_blocks() -> None:
    units = [unit(i) for i in range(1, 20)]
    result = build_schedule(
        units, start=TODAY, horizon_days=5, daily_minutes=240, start_clock="08:00"
    )
    for day in result.days:
        studied = [b for b in day.blocks if not b.is_break]
        if len(studied) <= 2:
            continue
        # Walk the day: after two consecutive study blocks there must be a break.
        run = 0
        saw_break = False
        for block in day.blocks:
            if block.is_break:
                if run >= 2:
                    saw_break = True
                continue
            run += 1
            if run == 3 and not saw_break:
                pytest.fail(f"{day.day}: three study blocks with no break")


def test_breaks_do_not_consume_the_daily_budget() -> None:
    units = [unit(i) for i in range(1, 12)]
    result = build_schedule(units, start=TODAY, horizon_days=3, daily_minutes=120)
    for day in result.days:
        assert day.planned_minutes <= 120


def test_rest_days_are_left_empty() -> None:
    units = [unit(i) for i in range(1, 20)]
    result = build_schedule(units, start=TODAY, horizon_days=7, daily_minutes=120, rest_days=[6, 7])
    for day in result.days:
        if day.day.isoweekday() in (6, 7):
            assert day.is_rest_day
            assert day.planned_minutes == 0


# ------------------------------------------------------------------ priority
def test_deadline_pressure_decays_with_distance() -> None:
    exam = TODAY + timedelta(days=10)
    assert deadline_pressure(TODAY, exam) == pytest.approx(1.0 / (1 + 10 / 6))
    assert deadline_pressure(exam, exam) == 1.0  # due today
    assert deadline_pressure(exam + timedelta(days=5), exam) == 1.0  # already passed
    assert deadline_pressure(TODAY, TODAY + timedelta(days=1)) > deadline_pressure(
        TODAY, TODAY + timedelta(days=45)
    )
    # An undated subject must be *less* urgent than a real deadline two weeks out.
    assert deadline_pressure(TODAY, None) < deadline_pressure(TODAY, TODAY + timedelta(days=14))


def test_higher_priority_work_is_scheduled_first() -> None:
    urgent = unit(1, importance=0.95, difficulty=3, mastery=0.0)
    trivial = unit(2, importance=0.05, difficulty=1, mastery=0.0)
    ctx = context()
    assert priority(urgent, ctx) > priority(trivial, ctx)

    result = build_schedule(
        [trivial, urgent], start=TODAY, horizon_days=1, daily_minutes=60, start_clock="08:00"
    )
    first = study_blocks(result)[0]
    assert first.unit_id == 1


def test_completed_work_never_outranks_pending_work() -> None:
    done = unit(1, importance=1.0, status="completed")
    todo = unit(2, importance=0.1, status="pending")
    ctx = context()
    assert priority(todo, ctx) > priority(done, ctx)


def test_knowledge_level_changes_priority() -> None:
    candidate = unit(1, mastery=0.0)
    novice = priority(candidate, context(knowledge_level_rank=1))
    expert = priority(candidate, context(knowledge_level_rank=5))
    assert novice > expert


def test_priority_is_bounded() -> None:
    extreme = unit(1, importance=1.0, difficulty=3, mastery=0.0, kind="learn")
    for ctx in (
        context(),
        context(exam_date=None),
        context(today=TODAY, exam_date=TODAY),
        context(study_mode="college_pace"),
    ):
        value = priority(extreme, ctx)
        assert 0.0 <= value <= 1.0


def test_no_deadline_is_less_urgent_than_a_near_deadline() -> None:
    candidate = unit(1)
    assert priority(candidate, context(exam_date=None)) < priority(candidate, context())


# ------------------------------------------------------------------ scheduling
def test_scheduling_is_deterministic() -> None:
    units = [unit(i, importance=i / 20) for i in range(1, 25)]
    kwargs = dict(
        start=TODAY,
        horizon_days=7,
        daily_minutes=150,
        start_clock="18:00",
        exam_date=TODAY + timedelta(days=6),
    )
    first = build_schedule(list(units), **kwargs)
    second = build_schedule(list(reversed(units)), **kwargs)
    signature = lambda r: [  # noqa: E731
        (d.day, [(b.start_time, b.unit_id, b.minutes) for b in d.blocks]) for d in r.days
    ]
    assert signature(first) == signature(second)


def test_nothing_is_scheduled_after_the_exam_in_fast_mode() -> None:
    exam = TODAY + timedelta(days=3)
    result = build_schedule(
        [unit(i) for i in range(1, 60)],
        start=TODAY,
        horizon_days=21,
        daily_minutes=60,
        exam_date=exam,
    )
    for day in result.days:
        assert day.day <= exam
    assert result.end == exam


def test_overflow_is_reported_not_silently_dropped() -> None:
    result = build_schedule(
        [unit(i) for i in range(1, 200)],
        start=TODAY,
        horizon_days=3,
        daily_minutes=60,
        exam_date=TODAY + timedelta(days=3),
    )
    assert result.unscheduled_unit_ids
    assert "did not fit" in result.reason or "exceed" in result.reason
    assert result.meta["reason_code"] in ("exam_horizon_short", "capacity_short")


def test_long_units_are_split_across_days() -> None:
    long_unit = unit(1, minutes=70)
    result = build_schedule([long_unit], start=TODAY, horizon_days=4, daily_minutes=45)
    placed = [b for b in study_blocks(result) if b.unit_id == 1]
    assert len(placed) >= 2
    assert all(b.minutes <= MAX_BLOCK_MINUTES for b in placed)
    assert any("(cont.)" in b.title for b in placed)


def test_prerequisites_are_respected() -> None:
    advanced = unit(2, prerequisites=[1])
    result = build_schedule(
        [advanced, unit(1)],
        start=TODAY,
        horizon_days=3,
        daily_minutes=25,
        start_clock="08:00",
    )
    placed = [b.unit_id for b in study_blocks(result)]
    assert placed.index(1) < placed.index(2)


def test_revision_offsets_compress_near_an_exam() -> None:
    assert revision_offsets("fast_exam", 1) == (1,)
    assert revision_offsets("fast_exam", 4) == (1, 3)
    assert revision_offsets("fast_exam", 30) == (1, 3, 7)
    assert revision_offsets("college_pace", 30) == (3, 10, 21)


def test_revision_units_wait_for_their_interval() -> None:
    learn = unit(1, minutes=25, topic_id=1)
    revision = unit(2, minutes=10, topic_id=1, is_revision=True, revision_round=1, kind="revision")
    result = build_schedule(
        [learn, revision], start=TODAY, horizon_days=6, daily_minutes=25, start_clock="08:00"
    )
    learn_day = next(d.day for d in result.days for b in d.blocks if b.unit_id == 1)
    rev_days = [d.day for d in result.days for b in d.blocks if b.unit_id == 2]
    assert rev_days, "revision was never scheduled"
    assert all(day > learn_day for day in rev_days)


def test_exam_eve_budget_is_tightened() -> None:
    exam = TODAY + timedelta(days=1)
    assert effective_daily_budget(240, exam, TODAY, "fast_exam") < 240
    # College pace is never tightened.
    assert effective_daily_budget(240, exam, TODAY, "college_pace") == 240
    assert effective_daily_budget(400, None, TODAY, "fast_exam") == MAX_DAILY_STUDY_MINUTES


def test_all_rest_days_reports_a_clear_reason() -> None:
    result = build_schedule(
        [unit(i) for i in range(1, 6)],
        start=TODAY,
        horizon_days=7,
        daily_minutes=120,
        rest_days=[1, 2, 3, 4, 5, 6, 7],
    )
    assert result.meta["reason_code"] == "no_active_days"
    assert "rest day" in result.reason


# ------------------------------------------------------------------- adaptive
def _snapshot(**kwargs) -> ExecutionSnapshot:
    defaults = dict(
        as_of=TODAY,
        planned_minutes=120,
        completed_minutes=120,
        missed_minutes=0,
        topics_completed=3,
        topics_pending=5,
        overdue_units=0,
    )
    defaults.update(kwargs)
    return ExecutionSnapshot(**defaults)


def test_on_track_when_execution_matches_the_plan() -> None:
    result = analyse(
        [unit(i, status="pending" if i > 3 else "completed") for i in range(1, 9)],
        _snapshot(),
        current_daily_minutes=120,
        exam_date=TODAY + timedelta(days=10),
        study_mode="fast_exam",
        knowledge_level_rank=2,
        horizon_days=14,
    )
    assert result.status == "on_track"
    assert result.actions == [] or all(a.kind != "extend_horizon" for a in result.actions)


def test_falling_behind_is_detected_and_acted_on() -> None:
    result = analyse(
        [unit(i, status="pending") for i in range(1, 15)],
        _snapshot(planned_minutes=200, completed_minutes=70, overdue_units=3),
        current_daily_minutes=120,
        exam_date=TODAY + timedelta(days=10),
        study_mode="fast_exam",
        knowledge_level_rank=2,
        horizon_days=14,
    )
    assert result.status == "behind"
    assert result.actions
    assert result.actions[0].kind in ("drop_lowest_yield", "extend_horizon")
    assert "behind" in result.summary.lower()


def test_finishing_early_pulls_work_forward() -> None:
    result = analyse(
        [unit(i, status="pending") for i in range(1, 10)],
        _snapshot(planned_minutes=100, completed_minutes=180, topics_completed=6),
        current_daily_minutes=120,
        exam_date=TODAY + timedelta(days=20),
        study_mode="fast_exam",
        knowledge_level_rank=2,
        horizon_days=14,
    )
    assert result.status == "ahead"
    assert any(a.kind == "pull_forward" for a in result.actions)


def test_availability_change_is_reported() -> None:
    result = analyse(
        [unit(i) for i in range(1, 8)],
        _snapshot(availability_changed=True, new_daily_minutes=60),
        current_daily_minutes=120,
        exam_date=TODAY + timedelta(days=10),
        study_mode="fast_exam",
        knowledge_level_rank=2,
        horizon_days=14,
    )
    assert result.status == "availability_changed"
    assert result.actions[0].kind == "availability_changed"
    assert result.actions[0].daily_minutes == 60


def test_completing_everything_is_reported_as_complete() -> None:
    result = analyse(
        [unit(1, status="completed")],
        _snapshot(topics_completed=1, topics_pending=0),
        current_daily_minutes=120,
        exam_date=None,
        study_mode="fast_exam",
        knowledge_level_rank=2,
        horizon_days=14,
    )
    assert result.status == "complete"
    assert result.remaining_minutes == 0


def test_infeasible_workload_produces_a_capacity_warning() -> None:
    units = [unit(i, minutes=60, status="pending") for i in range(1, 21)]  # 1200 min
    result = analyse(
        units,
        _snapshot(),
        current_daily_minutes=60,
        exam_date=TODAY + timedelta(days=3),  # only 180 min of capacity
        study_mode="fast_exam",
        knowledge_level_rank=2,
        horizon_days=14,
    )
    assert result.feasible is False
    assert result.required_daily_minutes > 60
    assert any(a.kind == "capacity_warning" for a in result.actions)


def test_remaining_minutes_excludes_revision_when_asked() -> None:
    units = [
        unit(1, minutes=30, status="pending"),
        unit(2, minutes=10, status="pending", is_revision=True, revision_round=1),
        unit(3, minutes=30, status="completed"),
    ]
    assert remaining_minutes(units) == 40
    assert remaining_minutes(units, include_revision=False) == 30


def test_block_status_values_cover_execution_outcomes() -> None:
    assert {s.value for s in BlockStatus} == {
        "planned",
        "done",
        "partial",
        "missed",
        "skipped",
    }


def test_never_schedules_a_zero_or_oversized_block() -> None:
    units = [unit(i, minutes=m) for i, m in enumerate([5, 9, 11, 29, 31, 100, 240], start=1)]
    result = build_schedule(
        units, start=TODAY, horizon_days=14, daily_minutes=120, start_clock="08:00"
    )
    for block in study_blocks(result):
        assert MIN_BLOCK_MINUTES <= block.minutes <= MAX_BLOCK_MINUTES


def test_knowledge_level_rank_flows_into_the_schedule() -> None:
    units = [unit(i, mastery=0.0) for i in range(1, 9)]
    low = build_schedule(
        units, start=TODAY, horizon_days=3, daily_minutes=90, knowledge_level_rank=1
    )
    high = build_schedule(
        units, start=TODAY, horizon_days=3, daily_minutes=90, knowledge_level_rank=5
    )
    # The planner schedules the same work either way; knowledge level only
    # reorders it by priority, it never changes how much must be done.
    assert low.total_planned_minutes == high.total_planned_minutes
    assert {b.unit_id for b in study_blocks(low)} == {b.unit_id for b in study_blocks(high)}
