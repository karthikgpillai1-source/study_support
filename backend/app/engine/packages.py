"""Work package generation.

A *work package* is a schedulable unit of work capped at 90 minutes. Packages
group topics, are split into 10-30 minute study units, and revision packages
mirror learn packages for the second pass.

Grouping is a bin-packing pass over topics ordered by module, so a package
almost never straddles two modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.enums import Difficulty, PackageType, UnitType

MAX_PACKAGE_MINUTES = 90
TARGET_PACKAGE_MINUTES = 75
MIN_UNIT_MINUTES = 10
MAX_UNIT_MINUTES = 30
DEFAULT_UNIT_MINUTES = 25

# A learn unit gets most of the topic's time; the remainder becomes practice.
PRACTICE_SHARE = 0.35


@dataclass(slots=True)
class PackageTopic:
    """The package generator's view of a topic (decoupled from the ORM)."""

    id: int
    title: str
    module_title: str
    difficulty: Difficulty
    minutes: int
    revision_minutes: int
    importance: float
    learning_objectives: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


@dataclass(slots=True)
class UnitPlan:
    title: str
    minutes: int
    type: UnitType
    topic_id: int
    objectives: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PackagePlan:
    title: str
    type: PackageType
    minutes: int
    difficulty: Difficulty
    topic_ids: list[int]
    units: list[UnitPlan]
    revision_of: int | None = None


def split_minutes(total: int, *, max_unit: int = MAX_UNIT_MINUTES) -> list[int]:
    """Split a duration into blocks of 10-30 minutes (the spec's study block rule).

    Returns a list whose sum is exactly ``total`` whenever possible, with every
    entry inside [MIN_UNIT_MINUTES, max_unit]. A remainder below 10 minutes is
    merged into an earlier block rather than producing an invalid short block.
    """
    total = max(0, int(total))
    if total == 0:
        return []
    if total <= MAX_UNIT_MINUTES:
        return [max(MIN_UNIT_MINUTES, total)]

    count = max(1, -(-total // max_unit))  # ceil
    if count * MIN_UNIT_MINUTES > total:
        count = total // MIN_UNIT_MINUTES

    base, extra = divmod(total, count)
    blocks = [base + (1 if i < extra else 0) for i in range(count)]

    # Repair any block that fell outside the 10-30 window.
    for i, value in enumerate(blocks):
        if value > max_unit:
            overflow = value - max_unit
            blocks[i] = max_unit
            for j in range(len(blocks) - 1, -1, -1):
                if overflow <= 0:
                    break
                room = max_unit - blocks[j]
                take = min(room, overflow)
                blocks[j] += take
                overflow -= take
    for i, value in enumerate(blocks):
        if value < MIN_UNIT_MINUTES:
            deficit = MIN_UNIT_MINUTES - value
            blocks[i] = MIN_UNIT_MINUTES
            for j in range(len(blocks) - 1, -1, -1):
                if deficit <= 0:
                    break
                if j == i or blocks[j] <= MIN_UNIT_MINUTES:
                    continue
                give = min(blocks[j] - MIN_UNIT_MINUTES, deficit)
                blocks[j] -= give
                deficit -= give
    return [b for b in blocks if b > 0]


def _difficulty_of(topics: list[PackageTopic]) -> Difficulty:
    if not topics:
        return Difficulty.MEDIUM
    weight = sum(t.minutes for t in topics) or 1
    score = sum(t.difficulty.rank * t.minutes for t in topics) / weight
    if score < 1.55:
        return Difficulty.EASY
    if score < 2.45:
        return Difficulty.MEDIUM
    return Difficulty.HARD


def _learn_units(topic: PackageTopic) -> list[UnitPlan]:
    """Split one topic's learn time into learn + practice units."""
    if topic.minutes < 25:
        return [
            UnitPlan(
                title=f"Cover: {topic.title}",
                minutes=topic.minutes,
                type=UnitType.LEARN,
                topic_id=topic.id,
                objectives=list(topic.learning_objectives[:3]),
                resources=topic.keywords[:5],
            )
        ]

    practice = int(round(topic.minutes * PRACTICE_SHARE / 5.0) * 5)
    practice = max(MIN_UNIT_MINUTES, min(30, practice))
    learn = topic.minutes - practice
    if learn < MIN_UNIT_MINUTES:
        practice = max(MIN_UNIT_MINUTES, practice - (MIN_UNIT_MINUTES - learn))
        learn = topic.minutes - practice

    units = [
        UnitPlan(
            title=f"Learn: {topic.title}",
            minutes=learn,
            type=UnitType.LEARN,
            topic_id=topic.id,
            objectives=list(topic.learning_objectives[:3]) or [f"Understand {topic.title}"],
            resources=topic.keywords[:5],
        )
    ]
    if practice >= MIN_UNIT_MINUTES:
        units.append(
            UnitPlan(
                title=f"Apply: {topic.title}",
                minutes=practice,
                type=UnitType.PRACTICE,
                topic_id=topic.id,
                objectives=list(topic.learning_objectives[3:6])
                or [f"Solve and explain problems on {topic.title}"],
                resources=topic.keywords[:3],
            )
        )
    return units


def _revision_units(topic: PackageTopic) -> list[UnitPlan]:
    minutes = max(MIN_UNIT_MINUTES, topic.revision_minutes)
    return [
        UnitPlan(
            title=f"Revise: {topic.title}",
            minutes=minutes,
            type=UnitType.REVISION,
            topic_id=topic.id,
            objectives=[f"Recall and explain {topic.title} without notes"],
            resources=topic.keywords[:4],
        )
    ]


def _package_title(topics: list[PackageTopic], index: int) -> str:
    if len(topics) == 1:
        return f"{topics[0].module_title}: {topics[0].title}"
    return f"{topics[0].module_title}: {topics[0].title} +{len(topics) - 1} more"


def group_topics(
    topics: list[PackageTopic],
    *,
    max_minutes: int = MAX_PACKAGE_MINUTES,
    target_minutes: int = TARGET_PACKAGE_MINUTES,
) -> list[list[PackageTopic]]:
    """Greedy consecutive packing within a module, never exceeding ``max_minutes``.

    A topic longer than ``max_minutes`` on its own still gets a package - its
    units then span multiple daily blocks, which the Planner Engine handles.
    """
    max_minutes = max(MIN_UNIT_MINUTES, min(MAX_PACKAGE_MINUTES, max_minutes))
    target_minutes = min(target_minutes, max_minutes)

    buckets: list[list[PackageTopic]] = []
    current: list[PackageTopic] = []
    current_minutes = 0
    current_module: str | None = None

    for topic in topics:
        same_module = current_module is None or topic.module_title == current_module
        would_overflow = current_minutes + topic.minutes > max_minutes
        past_target = current_minutes >= target_minutes and not same_module

        if current and (not same_module or would_overflow or past_target):
            buckets.append(current)
            current, current_minutes, current_module = [], 0, None

        current.append(topic)
        current_minutes += topic.minutes
        current_module = topic.module_title

    if current:
        buckets.append(current)
    return buckets


def build_packages(
    topics: list[PackageTopic],
    *,
    max_minutes: int = MAX_PACKAGE_MINUTES,
    include_revision: bool = True,
) -> list[PackagePlan]:
    """Build study packages plus their revision mirrors, in learning order."""
    study: list[PackagePlan] = []
    for index, bucket in enumerate(group_topics(topics, max_minutes=max_minutes)):
        units: list[UnitPlan] = []
        for topic in bucket:
            units.extend(_learn_units(topic))
        minutes = sum(u.minutes for u in units)
        study.append(
            PackagePlan(
                title=_package_title(bucket, index),
                type=PackageType.STUDY,
                minutes=minutes,
                difficulty=_difficulty_of(bucket),
                topic_ids=[t.id for t in bucket],
                units=units,
            )
        )

    if not include_revision:
        return study

    plans: list[PackagePlan] = []
    for offset, package in enumerate(study):
        plans.append(package)
        bucket = [t for t in topics if t.id in set(package.topic_ids)]
        rev_units: list[UnitPlan] = []
        for topic in bucket:
            rev_units.extend(_revision_units(topic))
        rev_minutes = sum(u.minutes for u in rev_units)
        if rev_minutes > max_minutes:
            # Split the revision mirror so the 90-minute cap always holds.
            half = max(1, len(rev_units) // 2)
            for chunk_index, chunk in enumerate((rev_units[:half], rev_units[half:])):
                if not chunk:
                    continue
                plans.append(
                    PackagePlan(
                        title=f"Revise: {package.title} ({chunk_index + 1}/2)",
                        type=PackageType.REVISION,
                        minutes=sum(u.minutes for u in chunk),
                        difficulty=package.difficulty,
                        topic_ids=sorted({u.topic_id for u in chunk}),
                        units=chunk,
                        revision_of=offset + 1,
                    )
                )
            continue
        plans.append(
            PackagePlan(
                title=f"Revise: {package.title}",
                type=PackageType.REVISION,
                minutes=rev_minutes,
                difficulty=package.difficulty,
                topic_ids=list(package.topic_ids),
                units=rev_units,
                revision_of=offset + 1,
            )
        )
    return plans


def split_single_topic(topic: PackageTopic) -> list[UnitPlan]:
    """Expose a topic's own unit breakdown (used by the Analysis screen)."""
    return _learn_units(topic)
