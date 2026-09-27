"""Team work-distribution *suggestions*.

Five strategies, all deterministic (longest-processing-time-first bin packing
plus difficulty balancing):

* ``topic``     - split topics round-robin by exam weight
* ``difficulty`` - every member gets a similar mix of easy/medium/hard
* ``time``       - equalise minutes
* ``teaching``   - flag a peer-teaching opportunity per package
* ``revision``   - assign revision ownership spread over time

These are **suggestions only**. Nothing is ever assigned automatically; a team
lead must accept them explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.enums import Difficulty, PackageType, SplitStrategy


@dataclass(slots=True)
class Member:
    user_id: int
    name: str
    daily_minutes: int = 120


@dataclass(slots=True)
class PackageView:
    id: int
    title: str
    minutes: int
    difficulty: Difficulty
    topic_ids: list[int]
    type: PackageType
    module_title: str = "General"
    topic_titles: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Assignment:
    user_id: int
    user_name: str
    package_ids: list[int] = field(default_factory=list)
    topic_ids: list[int] = field(default_factory=list)
    minutes: float = 0.0
    difficulty_load: dict[str, int] = field(
        default_factory=lambda: {"easy": 0, "medium": 0, "hard": 0}
    )
    balance_score: float = 0.0
    teaching_topics: list[str] = field(default_factory=list)
    revision_topic_ids: list[int] = field(default_factory=list)
    note: str = ""


@dataclass(slots=True)
class SplitResult:
    strategy: SplitStrategy
    label: str
    rationale: str
    assignments: list[Assignment]
    total_minutes: int


LABELS: dict[SplitStrategy, str] = {
    SplitStrategy.TOPIC: "Topic split",
    SplitStrategy.DIFFICULTY: "Difficulty split",
    SplitStrategy.TIME: "Time split",
    SplitStrategy.TEACHING: "Teaching split",
    SplitStrategy.REVISION: "Revision split",
}


def _empty(members: list[Member]) -> list[Assignment]:
    return [Assignment(user_id=m.user_id, user_name=m.name) for m in members]


def _add(a: Assignment, package: PackageView) -> None:
    a.package_ids.append(package.id)
    a.topic_ids.extend(t for t in package.topic_ids if t not in a.topic_ids)
    a.minutes += package.minutes
    a.difficulty_load[package.difficulty.value] += 1


def _balance_score(assignments: list[Assignment], total: int) -> list[Assignment]:
    """1.0 means perfectly even minutes; lower means more lopsided."""
    if not assignments:
        return assignments
    if len(assignments) == 1:
        assignments[0].balance_score = 1.0
        return assignments
    ideal = total / len(assignments)
    variance = sum((a.minutes - ideal) ** 2 for a in assignments) / len(assignments)
    deviation = variance**0.5
    score = ideal / (ideal + deviation) if ideal + deviation > 0 else 1.0
    for a in assignments:
        a.balance_score = round(score, 3)
    return assignments


def _study_packages(packages: list[PackageView], revision: bool) -> list[PackageView]:
    wanted = PackageType.REVISION if revision else PackageType.STUDY
    selected = [p for p in packages if p.type is wanted]
    return selected or packages


def split_by_time(
    members: list[Member], packages: list[PackageView], *, revision: bool = False
) -> SplitResult:
    """Longest-processing-time-first onto the currently lightest member."""
    pool = _study_packages(packages, revision)
    assignments = _empty(members)
    order = sorted(pool, key=lambda p: p.minutes, reverse=True)
    for package in order:
        target = min(assignments, key=lambda a: (a.minutes, len(a.package_ids)))
        _add(target, package)
    total = sum(p.minutes for p in pool)
    _balance_score(assignments, total)
    return SplitResult(
        strategy=SplitStrategy.TIME,
        label=LABELS[SplitStrategy.TIME],
        rationale=(
            f"Longest packages were placed on whoever currently has the least work. "
            f"{total} minutes across {len(members)} member(s)."
        ),
        assignments=assignments,
        total_minutes=total,
    )


def split_by_topic(
    members: list[Member], packages: list[PackageView], *, revision: bool = False
) -> SplitResult:
    """Assign whole modules, so no member owns half of one chapter.

    This is the syllabus-structure strategy: ownership follows the way the
    material is organised rather than raw minutes. Modules are dealt largest
    first to whoever currently has the least, which keeps the load close to even
    without slicing a module across two people.

    If there are fewer modules than members, someone would otherwise sit idle, so
    the largest module is then split open - atomicity yields to actually having
    work to do.
    """
    pool = _study_packages(packages, revision)
    assignments = _empty(members)

    by_module: dict[str, list[PackageView]] = {}
    for package in pool:
        by_module.setdefault(package.module_title or "General", []).append(package)

    modules = sorted(
        by_module.items(), key=lambda item: (-sum(p.minutes for p in item[1]), item[0])
    )
    for _module_title, module_packages in modules:
        target = min(assignments, key=lambda a: (a.minutes, len(a.package_ids)))
        for package in module_packages:
            _add(target, package)

    _rebalance_idle(assignments, modules)

    total = sum(p.minutes for p in pool)
    _balance_score(assignments, total)
    for assignment in assignments:
        owned = sorted({p.module_title for p in pool if p.id in set(assignment.package_ids)})
        split = len(owned) > 1
        assignment.note = (
            f"Owns {len(assignment.topic_ids)} topic(s) across "
            f"{', '.join(owned) if owned else 'no modules yet'}"
            + (
                ". Shares a module with the team because there were fewer modules than members."
                if split
                else "."
            )
        )
    return SplitResult(
        strategy=SplitStrategy.TOPIC,
        label=LABELS[SplitStrategy.TOPIC],
        rationale=(
            "Whole modules were dealt out, largest first, so each member owns a "
            "contiguous part of the syllabus instead of half a chapter. A module is only "
            "split when there are fewer modules than members."
        ),
        assignments=assignments,
        total_minutes=total,
    )


def _rebalance_idle(
    assignments: list[Assignment], modules: list[tuple[str, list[PackageView]]]
) -> None:
    """Move packages from the busiest module to idle members."""
    idle = [a for a in assignments if not a.package_ids]
    if not idle or not modules:
        return
    for target in idle:
        source = max(modules, key=lambda item: sum(p.minutes for p in item[1]))
        movable = sorted(source[1], key=lambda p: p.minutes, reverse=True)
        if len(source[1]) <= 1:
            return  # nothing left to give without emptying the source module
        for package in movable:
            if not target.package_ids:
                break
            holder = next((a for a in assignments if package.id in a.package_ids), None)
            if holder is None:
                break
            holder.package_ids.remove(package.id)
            holder.topic_ids = [t for t in holder.topic_ids if t not in package.topic_ids]
            holder.minutes -= package.minutes
            holder.difficulty_load[package.difficulty.value] -= 1
            _add(target, package)


def split_by_difficulty(
    members: list[Member], packages: list[PackageView], *, revision: bool = False
) -> SplitResult:
    """Balance the easy/medium/hard mix, not just the minutes."""
    pool = _study_packages(packages, revision)
    assignments = _empty(members)
    # Hard first, then medium, then easy: the scarcer skills go to whoever can absorb them.
    for difficulty in (Difficulty.HARD, Difficulty.MEDIUM, Difficulty.EASY):
        for package in sorted(
            (p for p in pool if p.difficulty is difficulty), key=lambda p: p.minutes, reverse=True
        ):
            target = min(
                assignments,
                key=lambda a: (
                    a.difficulty_load[difficulty.value],
                    a.minutes,
                ),
            )
            _add(target, package)
    total = sum(p.minutes for p in pool)
    _balance_score(assignments, total)

    for assignment in assignments:
        load = assignment.difficulty_load
        hardest = max(load, key=lambda k: load[k])
        assignment.note = (
            f"Load: {load['hard']} hard / {load['medium']} medium / {load['easy']} easy. "
            f"Heaviest band: {hardest}."
        )
    return SplitResult(
        strategy=SplitStrategy.DIFFICULTY,
        label=LABELS[SplitStrategy.DIFFICULTY],
        rationale=(
            "Hard topics were spread first so no member carries more than their share of "
            "difficult material. Review the hardest band before accepting."
        ),
        assignments=assignments,
        total_minutes=total,
    )


def split_by_teaching(members: list[Member], packages: list[PackageView]) -> SplitResult:
    """Base assignment is time-balanced, plus an explicit peer-teaching slot.

    Teaching is only *suggested*: the learner is whoever currently owns the least
    exposure to that topic's difficulty band.
    """
    base = split_by_time(members, packages, revision=False)
    pool = _study_packages(packages, revision=False)
    assignments = base.assignments

    for package in pool:
        owner = next((a for a in assignments if package.id in a.package_ids), None)
        if owner is None:
            continue
        # The natural presenter is the strongest member for that difficulty band.
        strongest = min(
            assignments,
            key=lambda a: (
                a.difficulty_load.get(package.difficulty.value, 0),
                -a.minutes,
            ),
        )
        if len(assignments) > 1 and strongest.user_id != owner.user_id:
            topic_label = package.topic_titles[0] if package.topic_titles else package.title
            strongest.teaching_topics.append(topic_label)
            owner.note = (owner.note + f" Could be taught by {strongest.user_name}.").strip()

    return SplitResult(
        strategy=SplitStrategy.TEACHING,
        label=LABELS[SplitStrategy.TEACHING],
        rationale=(
            "A time-balanced base split with one suggested presenter per package. "
            "Presenters are the members with the lightest load in that difficulty band."
        ),
        assignments=assignments,
        total_minutes=base.total_minutes,
    )


def split_by_revision(members: list[Member], packages: list[PackageView]) -> SplitResult:
    """Revision ownership is separated from learning ownership on purpose."""
    pool = [p for p in packages if p.type is PackageType.REVISION]
    if not pool:
        pool = _study_packages(packages, revision=True)
    assignments = _empty(members)
    for package in sorted(pool, key=lambda p: p.minutes, reverse=True):
        target = min(assignments, key=lambda a: (a.minutes, len(a.revision_topic_ids)))
        _add(target, package)
        target.revision_topic_ids = list(target.topic_ids)
    total = sum(p.minutes for p in pool)
    _balance_score(assignments, total)
    return SplitResult(
        strategy=SplitStrategy.REVISION,
        label=LABELS[SplitStrategy.REVISION],
        rationale=(
            "Revision ownership is balanced separately from learning ownership so the "
            "person who taught a topic is not always the one who re-tests it."
        ),
        assignments=assignments,
        total_minutes=total,
    )


def generate_all(members: list[Member], packages: list[PackageView]) -> list[SplitResult]:
    if not members or not packages:
        return []
    return [
        split_by_topic(members, packages),
        split_by_difficulty(members, packages),
        split_by_time(members, packages),
        split_by_teaching(members, packages),
        split_by_revision(members, packages),
    ]


def strategy_for(
    strategy: SplitStrategy, members: list[Member], packages: list[PackageView]
) -> SplitResult:
    builders = {
        SplitStrategy.TOPIC: split_by_topic,
        SplitStrategy.DIFFICULTY: split_by_difficulty,
        SplitStrategy.TIME: split_by_time,
        SplitStrategy.TEACHING: split_by_teaching,
        SplitStrategy.REVISION: split_by_revision,
    }
    return builders[strategy](members, packages)
