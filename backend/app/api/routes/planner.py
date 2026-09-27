"""Planner routes: generate plans, view daily/weekly schedule, adapt."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import CurrentUser, DbSession
from app.api.services import Forbidden, NotFound, ServiceError
from app.core.enums import BlockStatus, StudyMode, utcnow, week_start
from app.db.models import StudyBlock, StudyPlan
from app.schemas import (
    AvailabilityUpdate,
    BlockOut,
    BlockUpdate,
    DayPlanOut,
    PlanGenerateRequest,
    PlanOut,
    SubjectUpdate,
    WeekSummary,
)

router = APIRouter(tags=["planner"])


def _plan_out(db: Session, plan: StudyPlan, start: date, days: int) -> PlanOut:
    rows = services.day_plans(db, plan, start, days)
    return PlanOut(
        id=plan.id,
        subject_id=plan.subject_id,
        generated_for=plan.generated_for,
        week_start=plan.week_start,
        strategy=plan.strategy,
        study_mode=plan.study_mode,
        daily_budget_minutes=plan.daily_budget_minutes,
        planned_minutes=plan.planned_minutes,
        version=plan.version,
        is_active=plan.is_active,
        reason=plan.reason,
        meta=plan.meta or {},
        created_at=plan.created_at,
        days=[
            DayPlanOut(
                day=row["day"],
                weekday=row["weekday"],
                is_rest_day=row["is_rest_day"],
                budget_minutes=row["budget_minutes"],
                planned_minutes=row["planned_minutes"],
                completed_minutes=row["completed_minutes"],
                completion_percent=row["completion_percent"],
                blocks=[BlockOut.model_validate(b) for b in row["blocks"]],
            )
            for row in rows
        ],
    )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@router.post("/subjects/{subject_id}/plan", response_model=PlanOut, status_code=201)
def generate_plan(
    subject_id: int, payload: PlanGenerateRequest, user: CurrentUser, db: DbSession
) -> PlanOut:
    """Deterministic planning. No LLM is involved in this endpoint."""
    subject = services.get_subject(db, user, subject_id)
    plan = services.generate_plan(
        db,
        subject,
        horizon_days=payload.horizon_days,
        daily_minutes=payload.daily_minutes,
        start_date=payload.start_date,
        include_revision=payload.include_revision,
        respect_rest_days=payload.respect_rest_days,
        mode=payload.mode,
    )
    db.commit()
    db.refresh(plan)
    start = payload.start_date or max(plan.generated_for, utcnow().date())
    return _plan_out(db, plan, start=start, days=payload.horizon_days)


@router.get("/subjects/{subject_id}/plan", response_model=PlanOut)
def get_plan(
    subject_id: int,
    user: CurrentUser,
    db: DbSession,
    days: int = Query(default=14, ge=1, le=90),
    start: str | None = None,
) -> PlanOut:
    services.get_subject(db, user, subject_id)
    plan = services.load_plan(db, subject_id)
    if plan is None:
        raise ServiceError("No active plan for this subject. Generate one first.")
    start_date = _parse_date(start) or max(plan.generated_for, utcnow().date())
    return _plan_out(db, plan, start=start_date, days=days)


@router.get("/subjects/{subject_id}/plan/week", response_model=WeekSummary)
def week_summary(
    subject_id: int, user: CurrentUser, db: DbSession, start: str | None = None
) -> WeekSummary:
    services.get_subject(db, user, subject_id)
    plan = services.load_plan(db, subject_id)
    if plan is None:
        raise ServiceError("No active plan for this subject. Generate one first.")

    monday = week_start(_parse_date(start) or max(plan.generated_for, utcnow().date()))
    rows = services.day_plans(db, plan, monday, 7)

    by_kind: dict[str, int] = {}
    for row in rows:
        for block in row["blocks"]:
            key = "break" if block.is_break else str(block.kind)
            by_kind[key] = by_kind.get(key, 0) + block.minutes

    planned = sum(r["planned_minutes"] for r in rows)
    completed = sum(r["completed_minutes"] for r in rows)
    done = sum(
        1 for r in rows for b in r["blocks"] if not b.is_break and b.status is BlockStatus.DONE
    )
    total = sum(1 for r in rows for b in r["blocks"] if not b.is_break)
    return WeekSummary(
        week_start=monday,
        week_end=monday + timedelta(days=6),
        planned_minutes=planned,
        completed_minutes=completed,
        blocks_done=done,
        blocks_total=total,
        by_day=[
            {
                "day": r["day"],
                "planned_minutes": r["planned_minutes"],
                "completed_minutes": r["completed_minutes"],
                "completion_percent": r["completion_percent"],
                "is_rest_day": r["is_rest_day"],
            }
            for r in rows
        ],
        by_kind=[{"kind": k, "minutes": v} for k, v in sorted(by_kind.items())],
    )


@router.patch("/subjects/{subject_id}/availability")
def update_availability(
    subject_id: int, payload: AvailabilityUpdate, user: CurrentUser, db: DbSession
) -> dict:
    """Change available study time. The planner picks it up on the next generate."""
    subject = services.get_subject(db, user, subject_id)
    if subject.team_id is not None and not services.is_team_lead(db, user, subject.team_id):
        raise Forbidden("Only a team lead can change shared availability")
    subject.daily_minutes = payload.daily_minutes
    subject.start_time = payload.start_time
    subject.rest_days = payload.rest_days
    db.commit()
    return SubjectUpdate(
        daily_minutes=subject.daily_minutes,
        start_time=subject.start_time,
        rest_days=list(subject.rest_days or []),
    ).model_dump()


@router.get("/subjects/{subject_id}/plan/adaptive")
def adaptive(subject_id: int, user: CurrentUser, db: DbSession) -> dict:
    """Where reality diverged from the plan, and what to change about it."""
    subject = services.get_subject(db, user, subject_id)
    return services.adaptive_report(db, subject)


@router.get("/subjects/{subject_id}/plan/replan", response_model=PlanOut)
def replan(subject_id: int, user: CurrentUser, db: DbSession) -> PlanOut:
    """Regenerate against current progress without touching completed history."""
    subject = services.get_subject(db, user, subject_id)
    plan = services.generate_plan(db, subject, mode="keep_done")
    db.commit()
    db.refresh(plan)
    return _plan_out(
        db,
        plan,
        max(plan.generated_for, utcnow().date()),
        int((plan.meta or {}).get("horizon_days", 14)),
    )


@router.post("/subjects/{subject_id}/plan/mode", response_model=PlanOut)
def change_mode(subject_id: int, user: CurrentUser, db: DbSession, mode: StudyMode) -> PlanOut:
    """Switch between fast exam preparation and following college pace."""
    subject = services.get_subject(db, user, subject_id)
    subject.study_mode = mode
    db.flush()
    plan = services.generate_plan(db, subject, mode="keep_done")
    db.commit()
    db.refresh(plan)
    return _plan_out(
        db,
        plan,
        max(plan.generated_for, utcnow().date()),
        int((plan.meta or {}).get("horizon_days", 14)),
    )


@router.get("/plans/today", response_model=list[dict])
def today_across_subjects(user: CurrentUser, db: DbSession) -> list[dict]:
    today = utcnow().date()
    out: list[dict] = []
    for subject in services.accessible_subjects(db, user):
        plan = services.load_plan(db, subject.id)
        if plan is None:
            continue
        for row in services.day_plans(db, plan, today, 1):
            for block in row["blocks"]:
                out.append(
                    {
                        "block_id": block.id,
                        "subject_id": subject.id,
                        "subject_name": subject.name,
                        "color": subject.color,
                        "title": block.title,
                        "start_time": block.start_time,
                        "end_time": block.end_time,
                        "minutes": block.minutes,
                        "kind": block.kind,
                        "status": block.status,
                        "is_break": block.is_break,
                    }
                )
    out.sort(key=lambda item: item["start_time"])
    return out


@router.patch("/blocks/{block_id}", response_model=BlockOut)
def update_block(block_id: int, payload: BlockUpdate, user: CurrentUser, db: DbSession) -> BlockOut:
    block = db.get(StudyBlock, block_id)
    if block is None:
        raise NotFound("Block not found")
    plan = db.get(StudyPlan, block.plan_id)
    if plan is None:
        raise NotFound("Plan not found")
    services.get_subject(db, user, plan.subject_id)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(block, field, value)
    if block.status is BlockStatus.DONE and block.completed_at is None:
        block.completed_at = utcnow()
    db.commit()
    db.refresh(block)
    return BlockOut.model_validate(block)
