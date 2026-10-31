"""Rules for the My Subjects pages: course progress, list ordering, module ordering and the
"recommended next" list. Pure functions, no database, so every number a student sees on those
pages can be checked by a unit test.

Progress is deliberately conservative. It is a blend of three measured things, and a course with
nothing measured beyond "files were uploaded" has no progress at all (None, shown as "Not
measured") instead of a flattering 100%.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

# ----------------------------------------------------------------------------- course progress

# Weights of the three signals. They are used as given when all three exist; when a signal has no
# data yet its weight is shared out among the others in proportion.
WEIGHT_MATERIALS = 0.3  # files that finished being read, out of every file in the course
WEIGHT_QUIZZES = 0.5  # points scored over points available across completed quiz attempts
WEIGHT_TASKS = 0.2  # study tasks done, out of tasks done plus tasks that were planned up to today

MAX_MODULE_NAME = 80
MAX_TOPIC_NAME = 80
MAX_TOPICS_PER_MODULE = 40


@dataclass(frozen=True)
class ProgressInputs:
    documents: int = 0
    documents_ready: int = 0
    quiz_attempts: int = 0
    quiz_accuracy: float | None = None  # 0..1
    tasks_total: int = 0  # done + planned up to today and still open
    tasks_done: int = 0


PartKey = Literal["materials", "quizzes", "tasks"]


@dataclass(frozen=True)
class ProgressPart:
    key: PartKey
    value: float | None  # 0..1, None = no data yet
    weight: float  # the weight as used (after sharing out the missing signals)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def progress_parts(inputs: ProgressInputs) -> list[ProgressPart]:
    """The three signals with the weight each one carries for this course."""
    materials = _clamp(inputs.documents_ready / inputs.documents) if inputs.documents > 0 else None
    quizzes = (
        _clamp(inputs.quiz_accuracy)
        if inputs.quiz_attempts > 0 and inputs.quiz_accuracy is not None
        else None
    )
    tasks = _clamp(inputs.tasks_done / inputs.tasks_total) if inputs.tasks_total > 0 else None
    raw: tuple[tuple[PartKey, float | None, float], ...] = (
        ("materials", materials, WEIGHT_MATERIALS),
        ("quizzes", quizzes, WEIGHT_QUIZZES),
        ("tasks", tasks, WEIGHT_TASKS),
    )
    present = sum(weight for _, value, weight in raw if value is not None)
    parts: list[ProgressPart] = []
    for key, value, weight in raw:
        used = weight / present if value is not None and present > 0 else 0.0
        parts.append(ProgressPart(key=key, value=value, weight=round(used, 4)))
    return parts


def course_progress(inputs: ProgressInputs) -> float | None:
    """0..1, or None when nothing but uploads exists.

    At least one learning signal (a completed quiz or a study task) is required: files that were
    merely read by the system say nothing about what the student has learned."""
    parts = {part.key: part for part in progress_parts(inputs)}
    if parts["quizzes"].value is None and parts["tasks"].value is None:
        return None
    total = sum(part.value * part.weight for part in parts.values() if part.value is not None)
    return round(_clamp(total), 4)


# ------------------------------------------------------------------------------ list ordering

SortKey = Literal["name", "recent", "progress", "semester"]
SORT_KEYS: tuple[str, ...] = ("name", "recent", "progress", "semester")
DEFAULT_DESCENDING: dict[str, bool] = {
    "name": False,
    "recent": True,
    "progress": True,
    "semester": False,
}


def natural_key(text: str) -> list[tuple[int, int | str]]:
    """"Unit 2" before "Unit 10", case-insensitive. Digits compare as numbers."""
    return [
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", text)
        if part != ""
    ]


class CourseSortable(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def semester(self) -> str | None: ...
    @property
    def last_activity_at(self) -> object | None: ...
    @property
    def progress(self) -> float | None: ...


def _progress_of(row: CourseSortable) -> Any:
    return row.progress


def _semester_of(row: CourseSortable) -> Any:
    return row.semester or None


def _activity_of(row: CourseSortable) -> Any:
    return row.last_activity_at


def sort_courses[C: CourseSortable](rows: Sequence[C], sort: str = "recent", descending: bool | None = None) -> list[C]:
    """Order courses for the list. Courses with no value for the sorted column (no progress, no
    semester, no activity) always come last, whichever way the column runs. Ties break on name."""
    if sort not in SORT_KEYS:
        raise ValueError(f"unknown sort {sort!r}")
    reverse = DEFAULT_DESCENDING[sort] if descending is None else descending

    by_name = sorted(rows, key=lambda r: natural_key(r.name))  # stable base order for ties
    if sort == "name":
        return sorted(by_name, key=lambda r: natural_key(r.name), reverse=reverse)

    getter: Callable[[C], Any]
    if sort == "progress":
        getter = _progress_of
    elif sort == "semester":
        getter = _semester_of
    else:
        getter = _activity_of

    have = [r for r in by_name if getter(r) is not None]
    missing = [r for r in by_name if getter(r) is None]
    if sort == "semester":
        have = sorted(have, key=lambda r: natural_key(r.semester or ""), reverse=reverse)
    else:
        # sorted() is stable, and reverse=True keeps the original order of equal elements.
        have = sorted(have, key=getter, reverse=reverse)
    return have + missing


# ---------------------------------------------------------------------------------- modules


def clean_module_name(raw: str) -> str:
    """One spelling of a module/chapter label: spaces collapsed, 1..80 characters."""
    name = " ".join(raw.split())
    if not name:
        raise ValueError("A module needs a name.")
    if len(name) > MAX_MODULE_NAME:
        raise ValueError(f"A module name can be at most {MAX_MODULE_NAME} characters.")
    return name


def clean_optional_label(raw: str | None) -> str | None:
    if raw is None:
        return None
    label = " ".join(raw.split())
    if not label:
        return None
    if len(label) > MAX_MODULE_NAME:
        raise ValueError(f"A label can be at most {MAX_MODULE_NAME} characters.")
    return label


def name_key(name: str) -> str:
    """Names that differ only in case or spacing are the same module."""
    return " ".join(name.split()).casefold()


def clean_topics(raw: Sequence[str]) -> list[str]:
    """A module's topic list: tidy spacing, no blanks, no repeats (case-insensitive), in order."""
    seen: set[str] = set()
    topics: list[str] = []
    for item in raw:
        topic = " ".join(item.split())
        if not topic:
            continue
        if len(topic) > MAX_TOPIC_NAME:
            raise ValueError(f"A topic can be at most {MAX_TOPIC_NAME} characters.")
        key = topic.casefold()
        if key in seen:
            continue
        seen.add(key)
        topics.append(topic)
    if len(topics) > MAX_TOPICS_PER_MODULE:
        raise ValueError(f"A module can list at most {MAX_TOPICS_PER_MODULE} topics.")
    return topics


Direction = Literal["up", "down", "top", "bottom"]


def move_item(order: Sequence[str], item: str, direction: Direction) -> list[str]:
    """The order after moving one item. Moving past an end leaves the order unchanged."""
    items = list(order)
    if item not in items:
        raise ValueError("That item is not in the list.")
    index = items.index(item)
    target = {"up": index - 1, "down": index + 1, "top": 0, "bottom": len(items) - 1}[direction]
    target = max(0, min(len(items) - 1, target))
    items.insert(target, items.pop(index))
    return items


def check_reorder(current: Sequence[str], requested: Sequence[str]) -> None:
    """A new order must list every existing item exactly once, so nothing is lost or invented."""
    if len(set(requested)) != len(requested):
        raise ValueError("The new order lists an item twice.")
    if set(requested) != set(current):
        raise ValueError("The new order does not match the current list.")


def next_position(positions: Sequence[int]) -> int:
    return (max(positions) + 1) if positions else 0


# --------------------------------------------------------------------------- material coverage


@dataclass(frozen=True)
class Coverage:
    documents: int
    documents_ready: int
    documents_practised: int  # ready files that at least one marked quiz answer cites
    modules_total: int  # modules in the list plus module labels files carry
    modules_with_files: int
    modules_practised: int


def material_coverage(
    files: Sequence[tuple[str, str | None, str]],
    practised_filenames: set[str],
    listed_modules: Sequence[str] = (),
) -> Coverage:
    """How much of the course has been read and tried. `files` is (filename, module, status)."""
    ready = [f for f in files if f[2] == "ready"]
    practised_docs = [f for f in ready if f[0] in practised_filenames]
    names = {name_key(m): m for m in listed_modules}
    with_files: set[str] = set()
    practised: set[str] = set()
    for filename, module, _status in files:
        if module is None:
            continue
        key = name_key(module)
        names.setdefault(key, module)
        with_files.add(key)
        if filename in practised_filenames:
            practised.add(key)
    return Coverage(
        documents=len(files),
        documents_ready=len(ready),
        documents_practised=len(practised_docs),
        modules_total=len(names),
        modules_with_files=len(with_files),
        modules_practised=len(practised),
    )


Trend = Literal["improving", "steady", "declining"]
TREND_MIN_ATTEMPTS = 4
TREND_DELTA = 0.05


def accuracy_trend(percents: Sequence[float]) -> Trend | None:
    """Oldest-first attempt scores (0..1). Compares the average of the earlier half with the
    later half; fewer than four attempts is too little to call a direction (None)."""
    if len(percents) < TREND_MIN_ATTEMPTS:
        return None
    half = len(percents) // 2
    before = sum(percents[:half]) / half
    after = sum(percents[-half:]) / half
    if after - before >= TREND_DELTA:
        return "improving"
    if before - after >= TREND_DELTA:
        return "declining"
    return "steady"


def share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole > 0 else None


# -------------------------------------------------------------------------- recommended next

RecKind = Literal[
    "deadline", "revision_due", "weak_topic", "retry_failed", "first_quiz", "upload_first"
]
DEADLINE_HORIZON_DAYS = 21
MAX_RECOMMENDATIONS = 6


@dataclass(frozen=True)
class WeakTopic:
    name: str
    accuracy: float  # 0..1
    answers: int
    material_id: str | None = None


@dataclass(frozen=True)
class Deadline:
    kind: Literal["exam", "assignment"]
    ref_id: str
    title: str
    days_left: int  # negative = overdue


@dataclass(frozen=True)
class Signals:
    weak_topics: Sequence[WeakTopic] = ()
    revision_due: int = 0
    deadlines: Sequence[Deadline] = ()
    failed_materials: int = 0
    ready_materials: int = 0
    materials: int = 0
    quiz_attempts: int = 0


@dataclass(frozen=True)
class Recommendation:
    kind: RecKind
    priority: int
    ref_id: str | None = None
    label: str | None = None
    params: dict[str, int | float | str] = field(default_factory=dict)


def _deadline_priority(deadline: Deadline) -> int | None:
    days = deadline.days_left
    if deadline.kind == "assignment" and days < 0:
        return 100  # overdue work comes first
    if days < 0:
        return None  # an exam that has passed is not a to-do
    if days > DEADLINE_HORIZON_DAYS:
        return None
    if days <= 3:
        return 92 - days
    if days <= 7:
        return 82 - (days - 3)
    return 62 - (days - 7)


def recommend_next(signals: Signals, limit: int = MAX_RECOMMENDATIONS) -> list[Recommendation]:
    """The few things worth doing next, highest priority first, each from a measured signal.

    Nothing is invented: with no signals the list is empty."""
    found: list[Recommendation] = []
    for deadline in signals.deadlines:
        priority = _deadline_priority(deadline)
        if priority is None:
            continue
        found.append(
            Recommendation(
                kind="deadline",
                priority=priority,
                ref_id=deadline.ref_id,
                label=deadline.title,
                params={"what": deadline.kind, "days": deadline.days_left},
            )
        )
    if signals.revision_due > 0:
        found.append(
            Recommendation(
                kind="revision_due",
                priority=70 + min(signals.revision_due, 30) // 3,
                params={"count": signals.revision_due},
            )
        )
    for topic in signals.weak_topics:
        found.append(
            Recommendation(
                kind="weak_topic",
                priority=int(round(85 - 40 * max(0.0, min(1.0, topic.accuracy)))),
                ref_id=topic.material_id,
                label=topic.name,
                params={"accuracy": round(topic.accuracy, 4), "answers": topic.answers},
            )
        )
    if signals.failed_materials > 0:
        found.append(
            Recommendation(
                kind="retry_failed", priority=45, params={"count": signals.failed_materials}
            )
        )
    if signals.ready_materials > 0 and signals.quiz_attempts == 0:
        found.append(Recommendation(kind="first_quiz", priority=50))
    if signals.materials == 0:
        found.append(Recommendation(kind="upload_first", priority=40))
    order = {"deadline": 0, "revision_due": 1, "weak_topic": 2, "retry_failed": 3,
             "first_quiz": 4, "upload_first": 5}
    found.sort(key=lambda r: (-r.priority, order[r.kind], r.label or ""))
    return found[: max(0, limit)]
