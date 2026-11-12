"""Оценка одного следующего курса после завершения обучения на локальном бэкапе."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path
from statistics import NormalDist

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from import_alfa_backup import ImportErrorDetail, pseudonym, read_backup_rows

from app.catalog.sqlite_source import load_sqlite_catalog

TABLE = "CourseUserBindings"
COLUMNS = ("UserId", "CourseId", "Status", "Created", "StudyingStartDate", "Completed")
MIN_SUPPORT = 5


@dataclass(frozen=True)
class Enrollment:
    user: str
    course: str
    created: datetime
    started: datetime | None = None
    completed: datetime | None = None


@dataclass(frozen=True)
class Case:
    user: str
    at: datetime
    completed: frozenset[str]
    candidates: frozenset[str]
    target: str


def activity_columns(schema: dict[str, set[str]]) -> dict[str, tuple[str, ...]]:
    if TABLE not in schema:
        raise ImportErrorDetail(f"Нет обязательной таблицы {TABLE}")
    if missing := set(COLUMNS) - schema[TABLE]:
        raise ImportErrorDetail(f"В таблице {TABLE} нет столбцов: {', '.join(sorted(missing))}")
    return {TABLE: COLUMNS}


def timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    date = datetime.fromisoformat(value)
    return date if date.tzinfo else date.replace(tzinfo=timezone.utc)


def build_cases(records: list[Enrollment], available: frozenset[str]) -> list[Case]:
    by_user: dict[str, list[Enrollment]] = defaultdict(list)
    for row in records:
        by_user[row.user].append(row)
    cases = []
    for user, history in by_user.items():
        completions = [(row.completed, row.course) for row in history if row.completed is not None]
        possible = sorted({
            (row.started, row.course) for row in history
            if row.started is not None
            and any(course != row.course and end < row.started for end, course in completions)
        })
        if not possible or (len(possible) > 1 and possible[0][0] == possible[1][0]):
            continue
        start, target = possible[0]
        previous = [(end, course) for end, course in completions if end < start and course != target]
        at = max(end for end, _ in previous)
        completed = frozenset(course for _, course in previous)
        started = {row.course for row in history if row.started is not None and row.started <= at}
        candidates = available - completed - started
        if target in candidates:
            cases.append(Case(user, at, completed, candidates, target))
    return sorted(cases, key=lambda case: (case.at, case.user))


def paired_interval(deltas: list[int]) -> list[float] | None:
    if not deltas:
        return None
    # Agresti–Min Wald+2: по 0.5 наблюдения в каждой из четырёх клеток парных исходов.
    n = len(deltas) + 2
    mean = sum(deltas) / n
    discordant_share = (sum(abs(delta) for delta in deltas) + 1) / n
    margin = NormalDist().inv_cdf(0.975) * sqrt((discordant_share - mean**2) / n)
    return [max(-1.0, mean - margin), min(1.0, mean + margin)]


def evaluate(records: list[Enrollment], available: frozenset[str]) -> dict:
    cases = build_cases(records, available)
    events = iter(sorted(records, key=lambda row: row.created))
    event = next(events, None)
    course_users: Counter[str] = Counter()
    shared: Counter[frozenset[str]] = Counter()
    enrolled: dict[str, set[str]] = defaultdict(set)
    hits: Counter[str] = Counter()
    shown: Counter[str] = Counter()
    deltas = []
    for case in cases:
        while event is not None and event.created < case.at:
            history = enrolled[event.user]
            if event.course not in history:
                course_users[event.course] += 1
                shared.update(frozenset((event.course, other)) for other in history)
                history.add(event.course)
            event = next(events, None)

        own = enrolled.get(case.user, set())
        # Счётчики содержат только наблюдения до среза. Убираем вклад проверяемого пользователя.
        popularity = {course: course_users[course] - (course in own) for course in available}
        scores: Counter[str] = Counter()
        for source in sorted(case.completed):
            for candidate in case.candidates:
                support = shared[frozenset((source, candidate))] - (source in own and candidate in own)
                if support >= MIN_SUPPORT:
                    scores[candidate] += support / popularity[source]

        picks = {
            "popularity": min(case.candidates, key=lambda c: (-popularity[c], c), default=None),
            "coenrollment": min(scores, key=lambda c: (-scores[c], -popularity[c], c), default=None),
        }
        for method, pick in picks.items():
            shown[method] += pick is not None
            hits[method] += pick == case.target
        deltas.append(int(picks["coenrollment"] == case.target) - int(picks["popularity"] == case.target))

    n = len(cases)
    interval = paired_interval(deltas)
    return {
        "cases": n,
        "distinct_targets": len({case.target for case in cases}),
        "min_pair_support": MIN_SUPPORT,
        "methods": {
            method: {
                "shown": shown[method],
                "coverage": shown[method] / n if n else None,
                "hits_at_1": hits[method],
                "hit_at_1": hits[method] / n if n else None,
            }
            for method in ("popularity", "coenrollment")
        },
        "hit_at_1_delta": sum(deltas) / n if n else None,
        "paired_95_percent_interval": interval,
        "passes_gate": interval is not None and interval[0] > 0,
    }


def evaluate_backup(backup: Path, catalog_path: Path) -> None:
    if not backup.is_file():
        raise ImportErrorDetail("Файл бэкапа не найден")
    catalog = load_sqlite_catalog(catalog_path)
    available = frozenset(m.id for m in catalog.materials.values() if m.available and m.format == "course")
    _, data = read_backup_rows(backup.resolve(), activity_columns)
    records = []
    for user, course_id, status, created, started, completed in data[TABLE]:
        if not user or not course_id or status not in (0, 1, 2):
            continue
        course = f"course:{pseudonym(course_id)}"
        if course not in available or (created_at := timestamp(created)) is None:
            continue
        start = timestamp(started)
        end = timestamp(completed) if status == 2 else None
        if start and end and end < start:
            end = None
        records.append(Enrollment(user, course, created_at, start, end))
    if not records:
        raise ImportErrorDetail("Нет записей по доступным курсам. Укажите каталог, импортированный из этого бэкапа")
    print(json.dumps(evaluate(records, available), ensure_ascii=False, indent=2))
