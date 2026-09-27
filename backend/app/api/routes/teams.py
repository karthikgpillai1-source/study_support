"""Team routes: create/join, distribution suggestions, matrix, peer recommendations."""

from __future__ import annotations

import secrets
import string
from datetime import UTC, datetime

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api import services
from app.api.deps import CurrentUser, DbSession
from app.api.services import Forbidden, NotFound, ServiceError
from app.core.enums import SplitStrategy
from app.db.models import (
    Subject,
    Team,
    TeamMember,
    Topic,
    TopicOwnership,
)
from app.schemas import (
    AssignmentApplyRequest,
    KnowledgeMatrixOut,
    KnowledgeMatrixRow,
    OwnershipAssign,
    PeerRecommendationsOut,
    SplitSuggestion,
    TeamCreate,
    TeamJoin,
    TeamMemberOut,
    TeamOut,
    TeamSplitOut,
)

router = APIRouter(prefix="/teams", tags=["teams"])
subject_router = APIRouter(tags=["team intelligence"])

_ALPHABET = string.ascii_uppercase + string.digits


def _join_code(db: DbSession) -> str:
    while True:
        code = "".join(secrets.choice(_ALPHABET) for _ in range(6))
        if db.scalar(select(func.count(Team.id)).where(Team.join_code == code)) == 0:
            return code


def _team_out(db: DbSession, team: Team) -> TeamOut:
    members = services.team_members(db, team.id)
    return TeamOut(
        id=team.id,
        name=team.name,
        join_code=team.join_code,
        description=team.description,
        owner_id=team.owner_id,
        created_by_id=team.created_by_id,
        members=[
            TeamMemberOut(
                id=m.id,
                user_id=m.user_id,
                role=m.role,
                joined_at=m.joined_at,
                full_name=m.user.full_name if m.user else f"User {m.user_id}",
                email=m.user.email if m.user else "",
            )
            for m in members
        ],
        subjects=[
            {"id": s.id, "name": s.name, "exam_date": s.exam_date, "color": s.color}
            for s in team.subjects
        ],
        created_at=team.created_at,
    )


@router.get("", response_model=list[TeamOut])
def list_teams(user: CurrentUser, db: DbSession) -> list[TeamOut]:
    team_ids = db.scalars(select(TeamMember.team_id).where(TeamMember.user_id == user.id)).all()
    teams = db.scalars(select(Team).where(Team.id.in_(list(team_ids) or [0]))).unique().all()
    return [_team_out(db, t) for t in teams]


@router.post("", response_model=TeamOut, status_code=201)
def create_team(payload: TeamCreate, user: CurrentUser, db: DbSession) -> TeamOut:
    team = Team(
        name=payload.name.strip(),
        description=payload.description,
        join_code=_join_code(db),
        owner_id=user.id,
        created_by_id=user.id,
    )
    db.add(team)
    db.flush()
    db.add(TeamMember(team_id=team.id, user_id=user.id, role="owner"))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ServiceError("Could not create the team. Try again.") from exc
    db.refresh(team)
    return _team_out(db, team)


@router.post("/join", response_model=TeamOut)
def join_team(payload: TeamJoin, user: CurrentUser, db: DbSession) -> TeamOut:
    team = db.scalar(select(Team).where(Team.join_code == payload.join_code.strip().upper()))
    if team is None:
        raise NotFound("No team matches that join code")
    existing = db.scalar(
        select(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == user.id)
    )
    if existing is None:
        db.add(TeamMember(team_id=team.id, user_id=user.id, role="member"))
        db.commit()
    return _team_out(db, team)


@router.get("/{team_id}", response_model=TeamOut)
def get_team(team_id: int, user: CurrentUser, db: DbSession) -> TeamOut:
    team = db.get(Team, team_id)
    if team is None:
        raise NotFound("Team not found")
    if not db.scalar(
        select(func.count(TeamMember.id)).where(
            TeamMember.team_id == team_id, TeamMember.user_id == user.id
        )
    ):
        raise Forbidden("You are not a member of this team")
    return _team_out(db, team)


@router.delete("/{team_id}", status_code=204)
def delete_team(team_id: int, user: CurrentUser, db: DbSession) -> None:
    team = db.get(Team, team_id)
    if team is None:
        raise NotFound("Team not found")
    if team.owner_id != user.id and team.created_by_id != user.id:
        raise Forbidden("Only the team owner can delete it")
    db.delete(team)
    db.commit()


@router.post("/{team_id}/leave", status_code=204)
def leave_team(team_id: int, user: CurrentUser, db: DbSession) -> None:
    member = db.scalar(
        select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user.id)
    )
    if member is None:
        raise NotFound("You are not a member of this team")
    if member.role == "owner":
        raise ServiceError("Transfer ownership before leaving.")
    db.delete(member)
    db.commit()


# --------------------------------------------------------------- work distribution
@subject_router.get("/subjects/{subject_id}/split", response_model=TeamSplitOut)
def split_suggestions(
    subject_id: int, user: CurrentUser, db: DbSession, strategy: SplitStrategy | None = None
) -> TeamSplitOut:
    """All five distribution strategies. Suggestions only - nothing is applied."""
    subject = services.get_subject(db, user, subject_id)
    results = services.split_suggestions(db, subject, strategy)
    return TeamSplitOut(
        subject_id=subject_id,
        suggestions=[SplitSuggestion.model_validate(_as_dict(r)) for r in results],
        generated_at=datetime.now(UTC),
    )


def _as_dict(result) -> dict:
    """Project a split result onto the API schema shape."""
    return {
        "strategy": result.strategy,
        "label": result.label,
        "rationale": result.rationale,
        "total_minutes": result.total_minutes,
        "assignments": [
            {
                "user_id": a.user_id,
                "user_name": a.user_name,
                "package_ids": a.package_ids,
                "topic_ids": a.topic_ids,
                "minutes": a.minutes,
                "difficulty_load": a.difficulty_load,
                "balance_score": a.balance_score,
                "teaching_topics": a.teaching_topics,
                "revision_topic_ids": a.revision_topic_ids,
                "note": a.note,
            }
            for a in result.assignments
        ],
    }


@subject_router.post("/subjects/{subject_id}/split/apply")
def apply_split(
    subject_id: int, payload: AssignmentApplyRequest, user: CurrentUser, db: DbSession
) -> dict:
    """Accept a suggestion. This is the only path that creates topic ownership."""
    subject = services.get_subject(db, user, subject_id)
    applied = services.apply_suggestion(
        db,
        subject,
        payload.strategy,
        [a.model_dump() for a in payload.assignments],
        requested_by=user,
    )
    db.commit()
    return {
        "subject_id": subject_id,
        "strategy": payload.strategy.value,
        "assignments_applied": applied,
    }


@subject_router.get("/subjects/{subject_id}/ownership")
def ownership(subject_id: int, user: CurrentUser, db: DbSession) -> list[dict]:
    services.get_subject(db, user, subject_id)
    rows = db.execute(
        select(TopicOwnership, Topic, TeamMember)
        .join(Topic, TopicOwnership.topic_id == Topic.id)
        .join(TeamMember, TopicOwnership.user_id == TeamMember.user_id)
        .join(Subject, Topic.intelligence_id == Subject.id)
        .where(Subject.id == subject_id, TeamMember.team_id == Subject.team_id)
    ).all()
    return [
        {
            "topic_id": ownership_row.topic_id,
            "topic_title": topic.title,
            "user_id": membership.user_id,
            "user_name": membership.user.full_name
            if membership.user
            else f"User {membership.user_id}",
            "role": ownership_row.role,
            "strategy": ownership_row.strategy,
            "accepted": ownership_row.accepted,
        }
        for ownership_row, topic, membership in rows
    ]


@subject_router.post("/subjects/{subject_id}/ownership")
def set_ownership(
    subject_id: int, payload: OwnershipAssign, user: CurrentUser, db: DbSession
) -> dict:
    """Manually set topic ownership (peer review, hand-off, etc.)."""
    subject = services.get_subject(db, user, subject_id)
    if subject.team_id is None:
        raise ServiceError("This subject is solo.")
    valid = {m.user_id for m in services.member_profiles(db, subject.team_id)}
    if payload.user_id not in valid:
        raise ServiceError("That user is not a member of this team.")
    applied = services.apply_suggestion(
        db,
        subject,
        payload.strategy,
        [{"user_id": payload.user_id, "role": payload.role, "topic_ids": payload.topic_ids}],
        requested_by=user,
    )
    db.commit()
    return {"subject_id": subject_id, "assignments_applied": applied}


# ------------------------------------------------------------------- team matrix
@subject_router.get("/subjects/{subject_id}/matrix", response_model=KnowledgeMatrixOut)
def knowledge_matrix(subject_id: int, user: CurrentUser, db: DbSession) -> KnowledgeMatrixOut:
    """Topic x Member mastery grid."""
    subject = services.get_subject(db, user, subject_id)
    matrix, _states = services.knowledge_matrix(db, subject)
    return KnowledgeMatrixOut(
        subject_id=subject_id,
        topic_ids=matrix.topic_ids,
        topics=[
            {"topic_id": tid, "title": matrix.topic_titles.get(tid, ""), "position": i}
            for i, tid in enumerate(matrix.topic_ids)
        ],
        members=[
            KnowledgeMatrixRow(
                user_id=row.user_id,
                user_name=row.name,
                cells=[
                    {
                        "topic_id": c.topic_id,
                        "mastery": c.mastery,
                        "knowledge_state": c.knowledge_state,
                        "status": c.status,
                        "is_owner": c.is_owner,
                    }
                    for c in row.cells
                ],
                strong_count=row.strong_count,
                learning_count=row.learning_count,
                unknown_count=row.unknown_count,
                owned_topics=row.owned_topics,
                coverage_percent=row.coverage_percent,
            )
            for row in matrix.rows
        ],
        uncovered_topics=matrix.uncovered_topics,
        concentration_warning=matrix.concentration_warning,
    )


@subject_router.get("/subjects/{subject_id}/peers", response_model=PeerRecommendationsOut)
def peer_recommendations(
    subject_id: int, user: CurrentUser, db: DbSession
) -> PeerRecommendationsOut:
    """Expert/learner profiles and suggested peer teaching. Never auto-assigned."""
    subject = services.get_subject(db, user, subject_id)
    return PeerRecommendationsOut(**services.peer_recommendations(db, subject))


@subject_router.post("/subjects/{subject_id}/peers/signal")
def peer_signal(
    subject_id: int,
    user: CurrentUser,
    db: DbSession,
    topic_id: int = Query(...),
    kind: str = Query(..., pattern=r"^(taught|mastered|struggling)$"),
    note: str = Query(default=""),
) -> dict:
    """Record 'I taught this' / 'I mastered this' so peers can be recommended."""
    services.get_subject(db, user, subject_id)
    signal = services.signal_peer_activity(db, user, topic_id, kind, note)
    db.commit()
    return {
        "topic_id": signal.topic_id,
        "user_id": signal.user_id,
        "kind": signal.kind,
        "weight": signal.weight,
    }
