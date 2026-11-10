"""Сводка покрытия каталога и список отключённых признаков. Только агрегаты, без строк данных."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit

from .. import vocab
from .models import Material


def normalize_popularity(raw: Mapping[str, float], formats: Mapping[str, str], scale: str) -> dict[str, float]:
    """Нормирует популярность в [0, 1].

    `single` — деление на максимум каталога: для источника с одной шкалой, как синтетический набор.
    `per_format` — ранговый процентиль внутри формата: (ниже + равные) / n. Нужен копии, где
    популярность курсов — записи, а статей и документов — входящие ссылки, и шкалы несопоставимы.
    Нулевое значение в любой шкале даёт 0: материал без записей и ссылок не получает долю формата,
    а равенство решает id (PLAN.md, 2.2).
    """
    if not raw:
        return {}
    if scale == "per_format":
        groups: dict[str, list[str]] = defaultdict(list)
        for material_id, fmt in formats.items():
            groups[fmt].append(material_id)
        result: dict[str, float] = {}
        for ids in groups.values():
            values = [raw[i] for i in ids]
            n = len(values)
            for material_id in ids:
                value = raw[material_id]
                at_or_below = sum(1 for v in values if v <= value)
                result[material_id] = round(at_or_below / n, 6) if n and value > 0 else 0.0
        return result
    top = max(raw.values())
    return {i: (round(v / top, 6) if top > 0 else 0.0) for i, v in raw.items()}


def link_allowed(url: str | None) -> bool:
    """Ссылка допустима, если схема http или https и указан хост."""
    if not url:
        return False
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    return parts.scheme.lower() in vocab.ALLOWED_URL_SCHEMES and bool(parts.netloc)


def _share(count: int, total: int) -> float:
    return round(100.0 * count / total, 1) if total else 0.0


def disabled_features(materials: Iterable[Material], *, signals_loaded: bool = True) -> tuple[str, ...]:
    """Признак отключается, если ни у одного материала нет нужного поля."""
    items = list(materials)
    disabled: list[str] = []
    if not signals_loaded or not any(m.signals for m in items):
        disabled.append("signal")
    if not any(m.stages for m in items):
        disabled.append("stage")
    if not any(m.level for m in items):
        disabled.append("level")
    if not any(m.industries for m in items):
        disabled.append("industry")
    if not any(m.duration_minutes for m in items):
        disabled.append("effort")
    if not any(m.recommended_next for m in items):
        disabled.append("continuation")
    return tuple(disabled)


def summarize(materials: Iterable[Material], **extra: Any) -> dict[str, Any]:
    """Сводка для журнала, `GET /api/health` и протокола прогона."""
    items = list(materials)
    total = len(items)
    available = [m for m in items if m.available]
    by_format = Counter(m.format for m in items)
    available_by_format = Counter(m.format for m in available)
    by_access = Counter(m.access for m in items)
    topic_links = Counter(t for m in items for t in m.topics)
    with_url = [m for m in items if m.url]
    summary: dict[str, Any] = {
        "materials": total,
        "available": len(available),
        "by_format": dict(sorted(by_format.items())),
        "available_by_format": dict(sorted(available_by_format.items())),
        "by_access": dict(sorted(by_access.items())),
        "topics_share": _share(sum(1 for m in items if m.topics), total),
        "topic_links": dict(sorted(topic_links.items(), key=lambda kv: (-kv[1], kv[0]))),
        "signals_share": _share(sum(1 for m in items if m.signals), total),
        "stage_share": _share(sum(1 for m in items if m.stages), total),
        "level_share": _share(sum(1 for m in items if m.level), total),
        "industries_share": _share(sum(1 for m in items if m.industries), total),
        "duration_share": _share(sum(1 for m in items if m.duration_minutes), total),
        "recommended_next_share": _share(sum(1 for m in items if m.recommended_next), total),
        "links_total": len(with_url),
        "links_invalid_scheme": sum(1 for m in with_url if not link_allowed(m.url)),
    }
    summary.update(extra)
    return summary
