"""Пары совместных записей на курсы из JSON (docs/plan.md, раздел 9, решение 2026-11-11 о пилоте «похожие курсы»).

Формат файла — как `data/course-pairs.synthetic.json`: объект с полями `version`, `note` и `pairs`;
элемент `pairs` — объект `{"a", "b", "together", "a_total", "b_total"}` с кодами материалов в формате API.
`together` — число слушателей, записанных на оба курса, `a_total` и `b_total` — число слушателей
каждого курса. Пара симметрична: порядок `a` и `b` не важен, обратная запись считается дублем. Для копии
выгрузки файл строится офлайн по журналу записей; в нём только коды курсов и счётчики, без
идентификаторов пользователей.

Отсутствующий, нечитаемый или неверный файл отключает признак `co_enrollment`, а не загрузку
каталога, как база признаков из текстов (docs/plan.md, 7.2, S6). Отбрасываются и считаются в сводке пары
с неверными полями (`invalid`), с кодами вне каталога (`unknown_course`), с материалами других
форматов (`not_course`), с `together` больше числа слушателей курса (`inconsistent`), повторы
(`duplicates`) и пары ниже порога поддержки (`below_support`). Если у одного курса в разных парах
разное число слушателей, берётся наибольшее, а расхождение считается в `total_conflicts`. В сводке
только агрегаты: без кодов, строк и путей.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import ease
from .models import CatalogError, CoursePairs, Material, valid_material_id

log = logging.getLogger("app.catalog")

COUNT_FIELDS = ("together", "a_total", "b_total")
MAX_COUNT = 1_000_000_000
DROP_REASONS = ("below_support", "unknown_course", "not_course", "inconsistent", "duplicates", "invalid")
# Состояние источника пар в сводке: loaded — признак включён; иначе признак отключён
PAIRS_STATES = ("loaded", "not_configured", "not_found", "unreadable", "invalid", "empty")


def _count(value: Any) -> int | None:
    """Счётчик: неотрицательное целое, не bool; None — значение неверно."""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_COUNT:
        return None
    return value


def empty_summary(min_support: int, source: str = "not_configured") -> dict[str, Any]:
    """Сводка пар без загруженных пар: состояние источника, порог и нулевые счётчики."""
    return {
        "source": source,
        "min_support": min_support,
        "pairs": 0,
        "courses": 0,
        "dropped": dict.fromkeys(DROP_REASONS, 0),
        "total_conflicts": 0,
    }


def _weights(
    totals: Mapping[str, int], every: Mapping[str, Mapping[str, int]], min_support: int
) -> dict[str, dict[str, float]]:
    """Веса модели EASE для ленты по профилю в единицах доли слушателей; пусто, если модель не построить."""
    if not every:
        return {}
    if len(totals) > ease.EASE_MAX_COURSES:
        log.warning(
            "Курсов в файле пар %d, больше предела модели %d: лента считает долю слушателей",
            len(totals), ease.EASE_MAX_COURSES,
        )
        return {}
    try:
        raw = ease.weights(totals, every)
    except ValueError:
        log.warning("Матрица счётчиков файла пар вырождена: лента считает долю слушателей")
        return {}
    return ease.in_share_units(raw, totals, every, min_support)


def parse_pairs(
    payload: Any, materials: Mapping[str, Material], min_support: int
) -> tuple[CoursePairs, dict[str, Any]]:
    """Пары из разобранного JSON и сводка. Ошибка структуры файла — CatalogError, ошибка отдельной пары — счётчик."""
    if not isinstance(payload, dict) or not isinstance(payload.get("pairs"), list):
        raise CatalogError("Файл пар должен содержать список pairs")
    counts: Counter[str] = Counter()
    together: dict[str, dict[str, int]] = {}
    every: dict[str, dict[str, int]] = {}  # все верные пары, и ниже порога: счётчики для модели EASE
    totals: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    for row in payload["pairs"]:
        if not isinstance(row, dict):
            counts["invalid"] += 1
            continue
        a, b = row.get("a"), row.get("b")
        n, a_total, b_total = (_count(row.get(name)) for name in COUNT_FIELDS)
        if (
            not valid_material_id(a) or not valid_material_id(b) or a == b
            or n is None or a_total is None or b_total is None
        ):
            counts["invalid"] += 1
            continue
        # Здесь a и b — строки: valid_material_id — TypeGuard[str]
        if a not in materials or b not in materials:
            counts["unknown_course"] += 1
            continue
        if materials[a].format != "course" or materials[b].format != "course":
            counts["not_course"] += 1
            continue
        if n > min(a_total, b_total):
            counts["inconsistent"] += 1
            continue
        key = (a, b) if a < b else (b, a)
        if key in seen:
            counts["duplicates"] += 1
            continue
        seen.add(key)
        # Число слушателей курса нужно и для пар ниже порога: доля N из M считается по всем слушателям курса
        for course, total in ((a, a_total), (b, b_total)):
            if course in totals and totals[course] != total:
                counts["total_conflicts"] += 1
            totals[course] = max(totals.get(course, 0), total)
        if n > 0:
            every.setdefault(a, {})[b] = n
            every.setdefault(b, {})[a] = n
        if n < min_support:
            counts["below_support"] += 1
            continue
        together.setdefault(a, {})[b] = n
        together.setdefault(b, {})[a] = n
    pairs = CoursePairs(
        together=together, totals=totals, min_support=min_support, weights=_weights(totals, every, min_support)
    )
    summary = empty_summary(min_support, "loaded" if together else "empty")
    summary.update(
        pairs=pairs.size,
        courses=len(together),
        dropped={reason: counts[reason] for reason in DROP_REASONS},
        total_conflicts=counts["total_conflicts"],
    )
    return pairs, summary


def load_course_pairs(
    path: Path | None, materials: Mapping[str, Material], min_support: int
) -> tuple[CoursePairs | None, dict[str, Any]]:
    """Пары из файла и сводка. Без файла, при ошибке или без пар не ниже порога — None и причина в `source`."""
    if path is None:
        return None, empty_summary(min_support)
    name = Path(path).name
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        log.warning("Файл пар совместных записей не найден: %s; признак co_enrollment отключён", name)
        return None, empty_summary(min_support, "not_found")
    except (OSError, UnicodeDecodeError):
        log.warning("Файл пар совместных записей не читается: %s; признак co_enrollment отключён", name)
        return None, empty_summary(min_support, "unreadable")
    try:
        pairs, summary = parse_pairs(json.loads(text), materials, min_support)
    except (ValueError, RecursionError, CatalogError) as exc:
        # Только тип ошибки: текст исключения мог бы процитировать содержимое файла
        log.warning(
            "Файл пар совместных записей неверен: %s (%s); признак co_enrollment отключён", name, type(exc).__name__
        )
        return None, empty_summary(min_support, "invalid")
    if not pairs.together:
        log.warning(
            "В файле пар нет пар с поддержкой не ниже %d: %s; признак co_enrollment отключён", min_support, name
        )
        return None, summary
    return pairs, summary
