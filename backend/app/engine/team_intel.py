"""Team Intelligence.

Produces the Topic x Member knowledge matrix, identifies experts and learners
from observed progress, and recommends peer teaching.

**Recommendations only.** This module never writes an assignment. A team lead
must explicitly accept a suggestion.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.enums import KnowledgeState, TopicStatus

# Mastery needed before someone counts as a peer teacher for a topic.
EXPERT_MASTERY = 0.75
STRONG_MASTERY = 0.55
# Below this, a member is a learner for the topic rather than a weak expert.
LEARNER_MASTERY = 0.35

STATE_RANK = {
    KnowledgeState.UNKNOWN: 0.0,
    KnowledgeState.LEARNING: 0.25,
    KnowledgeState.FAMILIAR: 0.5,
    KnowledgeState.STRONG: 0.7,
    KnowledgeState.MASTERED: 0.9,
}


@dataclass(slots=True)
class MemberState:
    user_id: int
    name: str
    # topic_id -> (mastery, knowledge_state, status)
    topics: dict[int, tuple[float, str, str]] = field(default_factory=dict)

    def mastery(self, topic_id: int) -> float:
        return self.topics.get(
            topic_id, (0.0, KnowledgeState.UNKNOWN.value, TopicStatus.PENDING.value)
        )[0]

    def state(self, topic_id: int) -> str:
        return self.topics.get(
            topic_id, (0.0, KnowledgeState.UNKNOWN.value, TopicStatus.PENDING.value)
        )[1]

    def owned(self, owned_topic_ids: set[int]) -> int:
        return len(owned_topic_ids)


@dataclass(slots=True)
class MatrixCell:
    user_id: int
    topic_id: int
    mastery: float
    knowledge_state: str
    status: str
    is_owner: bool


@dataclass(slots=True)
class MatrixRow:
    user_id: int
    name: str
    cells: list[MatrixCell]
    owned_topics: int

    @property
    def strong_count(self) -> int:
        return sum(1 for c in self.cells if c.mastery >= STRONG_MASTERY)

    @property
    def learning_count(self) -> int:
        return sum(1 for c in self.cells if LEARNER_MASTERY <= c.mastery < STRONG_MASTERY)

    @property
    def unknown_count(self) -> int:
        return sum(1 for c in self.cells if c.mastery < LEARNER_MASTERY)

    @property
    def coverage_percent(self) -> float:
        if not self.cells:
            return 0.0
        return round(sum(c.mastery for c in self.cells) / len(self.cells), 3)


@dataclass(slots=True)
class KnowledgeMatrix:
    topic_ids: list[int]
    topic_titles: dict[int, str]
    rows: list[MatrixRow]
    uncovered_topics: list[int]

    @property
    def concentration_warning(self) -> str | None:
        """Warn when team knowledge is concentrated in one person."""
        if len(self.rows) < 2 or not self.rows:
            return None
        for row in self.rows:
            share = row.coverage_percent
            if share >= 0.8:
                return (
                    f"{row.name} is the only strong member across most topics. "
                    "If they miss a session the team loses that knowledge - spread peer teaching."
                )
        # Nobody is strong anywhere: a sign the team has not started.
        if all(row.coverage_percent < LEARNER_MASTERY for row in self.rows):
            return (
                "No member has recorded progress yet. Start with the shared plan to "
                "build the matrix."
            )
        return None


@dataclass(slots=True)
class PeerRecommendation:
    topic_id: int
    topic_title: str
    expert_id: int
    expert_name: str
    learner_ids: list[int]
    learner_names: list[str]
    reason: str
    confidence: float
    action: str = "suggest_peer_teaching"


def build_matrix(
    members: list[MemberState],
    topic_ids: list[int],
    topic_titles: dict[int, str],
    ownership: dict[int, set[int]],
) -> KnowledgeMatrix:
    rows: list[MatrixRow] = []
    for member in members:
        owned = ownership.get(member.user_id, set())
        cells = [
            MatrixCell(
                user_id=member.user_id,
                topic_id=topic_id,
                mastery=round(member.mastery(topic_id), 3),
                knowledge_state=member.state(topic_id),
                status=member.topics.get(topic_id, (0.0, "", ""))[2],
                is_owner=topic_id in owned,
            )
            for topic_id in topic_ids
        ]
        rows.append(
            MatrixRow(
                user_id=member.user_id, name=member.name, cells=cells, owned_topics=len(owned)
            )
        )

    covered: set[int] = set()
    for row in rows:
        for cell in row.cells:
            if cell.mastery >= LEARNER_MASTERY:
                covered.add(cell.topic_id)
    uncovered = [topic_id for topic_id in topic_ids if topic_id not in covered]

    return KnowledgeMatrix(
        topic_ids=list(topic_ids),
        topic_titles=topic_titles,
        rows=rows,
        uncovered_topics=uncovered,
    )


def rank_experts(matrix: KnowledgeMatrix) -> list[dict]:
    """Per-member expert profile: where they can teach and how solid it is."""
    out: list[dict] = []
    for row in matrix.rows:
        strong = [c for c in row.cells if c.mastery >= EXPERT_MASTERY]
        near = [c for c in row.cells if STRONG_MASTERY <= c.mastery < EXPERT_MASTERY]
        if not strong and not near:
            continue
        total = sum(c.mastery for c in row.cells) or 1.0
        out.append(
            {
                "user_id": row.user_id,
                "name": row.name,
                "expert_topic_ids": [c.topic_id for c in strong],
                "near_expert_topic_ids": [c.topic_id for c in near],
                "teaching_load": len(strong) + len(near),
                "overall_mastery": round(total / len(row.cells), 3) if row.cells else 0.0,
                "confidence": round(
                    min(1.0, (len(strong) + 0.5 * len(near)) / max(1, len(row.cells)) * 2), 3
                ),
            }
        )
    out.sort(key=lambda item: (-item["teaching_load"], item["user_id"]))
    return out


def rank_learners(matrix: KnowledgeMatrix) -> list[dict]:
    """Per-member learner profile: where they most need help."""
    out: list[dict] = []
    for row in matrix.rows:
        weak = [c for c in row.cells if c.mastery < LEARNER_MASTERY]
        if not weak:
            continue
        out.append(
            {
                "user_id": row.user_id,
                "name": row.name,
                "help_topic_ids": [c.topic_id for c in weak],
                "help_needed": len(weak),
                "average_mastery": row.coverage_percent,
            }
        )
    out.sort(key=lambda item: (-item["help_needed"], item["user_id"]))
    return out


def recommend_peer_teaching(
    matrix: KnowledgeMatrix, *, min_confidence: float = 0.2, max_per_topic: int = 4
) -> list[PeerRecommendation]:
    """Suggest who should teach whom - nothing is assigned automatically."""
    experts = {e["user_id"]: e for e in rank_experts(matrix)}
    recommendations: list[PeerRecommendation] = []

    for topic_id in matrix.topic_ids:
        title = matrix.topic_titles.get(topic_id, f"Topic {topic_id}")
        strengths: list[tuple[float, int, str]] = []
        for row in matrix.rows:
            cell = next((c for c in row.cells if c.topic_id == topic_id), None)
            if cell is None:
                continue
            strengths.append((cell.mastery, row.user_id, row.name))
        strengths.sort(reverse=True)

        if not strengths or strengths[0][0] < EXPERT_MASTERY:
            continue  # nobody can teach this yet

        best_mastery, best_id, best_name = strengths[0]
        learners = [
            (mastery, uid, name)
            for mastery, uid, name in strengths[1:]
            if uid != best_id and mastery < LEARNER_MASTERY
        ]
        learners.sort()
        if not learners:
            continue

        confidence = round(
            min(1.0, (best_mastery - learners[0][0]) / 0.6 * 0.6 + best_mastery * 0.4), 3
        )
        if confidence < min_confidence:
            continue

        gap_topics = [
            t for t in experts.get(best_id, {}).get("expert_topic_ids", []) if t == topic_id
        ]
        reason = (
            f"{best_name} has {int(best_mastery * 100)}% mastery here; "
            f"{learners[0][2]} has {int(learners[0][0] * 100)}%. "
            + (
                "Already recorded as peer teacher for this topic."
                if gap_topics
                else "A 20-30 minute walkthrough would close the gap fastest."
            )
        )
        recommendations.append(
            PeerRecommendation(
                topic_id=topic_id,
                topic_title=title,
                expert_id=best_id,
                expert_name=best_name,
                learner_ids=[uid for _m, uid, _n in learners[:max_per_topic]],
                learner_names=[name for _m, _uid, name in learners[:max_per_topic]],
                reason=reason,
                confidence=confidence,
            )
        )

    recommendations.sort(key=lambda r: -r.confidence)
    return recommendations


def next_mastery(state: str, event: str, confidence: float) -> float:
    """Deterministic mastery update from a progress event.

    A simple saturating curve - enough to drive the matrix without pretending to
    be a learning model.
    """
    current = STATE_RANK.get(KnowledgeState(state), 0.0) if state else 0.0
    if event == "completed":
        gain = 0.35 + 0.25 * max(0.0, min(1.0, confidence))
    elif event == "partial":
        gain = 0.15
    elif event == "started":
        gain = 0.05
    else:  # skipped
        gain = -0.05
    # Diminishing returns: each success matters less than the last.
    updated = current + (1.0 - current) * gain
    return round(max(0.0, min(1.0, updated)), 3)


def state_for_mastery(mastery: float) -> KnowledgeState:
    if mastery >= 0.85:
        return KnowledgeState.MASTERED
    if mastery >= STRONG_MASTERY:
        return KnowledgeState.STRONG
    if mastery >= 0.4:
        return KnowledgeState.FAMILIAR
    if mastery >= LEARNER_MASTERY:
        return KnowledgeState.LEARNING
    return KnowledgeState.UNKNOWN
