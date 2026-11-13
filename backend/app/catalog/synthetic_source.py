"""Чтение каталога из JSON в каноническом формате: синтетический набор или согласованный файл.

Формат файла — как `data/catalog.synthetic.json`: объект с полями `version`, `popularity_scale`
и `materials`. Кодировка UTF-8, метка порядка байтов (BOM) допускается. Неизвестные коды
отбрасываются и считаются в сводке (`dropped_codes`). Запись пропускается и считается
в `skipped_records`, если у неё нет названия, формат неизвестен, код материала повторяется,
длиннее 64 символов или содержит что-то кроме латиницы, цифр и `:_-`, поле неверного типа
(строка вместо списка, список вместо строки) или популярность не является неотрицательным числом.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Collection
from pathlib import Path
from typing import Any

from .. import vocab
from .coverage import disabled_features, normalize_popularity, summarize
from .models import Catalog, CatalogError, Material, valid_material_id

MAX_TITLE = 120
MAX_BENEFIT = 200

# Поля с кодами: список строк или null
CODE_LISTS = ("topics", "signals", "stage", "industries", "recommended_next")
# Поля с одним кодом: строка или null
CODE_STRINGS = ("level", "access")


def _codes(values: Any, allowed: Collection[str], dropped: Counter[str], kind: str) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    result: list[str] = []
    for value in values:
        if isinstance(value, str) and value in allowed and value not in result:
            result.append(value)
        else:
            dropped[kind] += 1
    return tuple(result)


def _popularity(value: Any) -> float | None:
    """Популярность записи: неотрицательное конечное число, пропуск — 0. None — значение неверно."""
    if value is None:
        return 0.0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _well_typed(row: dict[str, Any]) -> bool:
    """Типы полей, которые разбор использует как коды и флаги. Популярность проверяет `_popularity`."""
    if any(row.get(key) is not None and not isinstance(row.get(key), list) for key in CODE_LISTS):
        return False
    if any(row.get(key) is not None and not isinstance(row.get(key), str) for key in CODE_STRINGS):
        return False
    return row.get("available") is None or isinstance(row.get("available"), bool)


def _accepted_rows(records: list[Any]) -> tuple[list[dict[str, Any]], dict[str, float], int]:
    """Записи, которые разбор принимает, их исходная популярность по коду и число пропущенных записей."""
    skipped = 0
    rows: list[dict[str, Any]] = []
    raw_popularity: dict[str, float] = {}
    for row in records:
        if not isinstance(row, dict):
            skipped += 1
            continue
        material_id = row.get("id")
        title = row.get("title")
        fmt = row.get("format")
        if not valid_material_id(material_id) or material_id in raw_popularity:
            skipped += 1
            continue
        if not isinstance(title, str) or not title.strip() or not isinstance(fmt, str) or fmt not in vocab.FORMATS:
            skipped += 1
            continue
        popularity_raw = _popularity(row.get("popularity"))
        if not _well_typed(row) or popularity_raw is None:
            skipped += 1
            continue
        rows.append(row)
        raw_popularity[material_id] = popularity_raw
    return rows, raw_popularity, skipped


def parse_materials(payload: dict[str, Any]) -> tuple[list[Material], dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("materials"), list):
        raise CatalogError("Файл каталога должен содержать список materials")
    scale = payload.get("popularity_scale", "single")
    if not isinstance(scale, str) or scale not in {"single", "per_format"}:
        raise CatalogError("popularity_scale должен быть single или per_format")
    dropped: Counter[str] = Counter()
    rows, raw_popularity, skipped = _accepted_rows(payload["materials"])
    # Коды принятых записей: ссылки recommended_next на прочие коды отбрасываются
    seen = set(raw_popularity)

    formats = {r["id"]: r["format"] for r in rows}
    popularity = normalize_popularity(raw_popularity, formats, scale)

    materials: list[Material] = []
    for row in rows:
        level = row.get("level")
        if level is not None and level not in vocab.LEVELS:
            dropped["level"] += 1
            level = None
        access = row.get("access", "open")
        if access not in vocab.ACCESS:
            dropped["access"] += 1
            access = "paid"  # неизвестный доступ трактуется осторожно: как платный
        duration = row.get("duration_minutes")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            duration = None
        benefit = row.get("short_benefit")
        benefit = benefit.strip()[:MAX_BENEFIT] if isinstance(benefit, str) and benefit.strip() else None
        next_step = row.get("next_step")
        next_step = next_step.strip() if isinstance(next_step, str) and next_step.strip() else None
        url = row.get("url")
        url = url.strip() if isinstance(url, str) and url.strip() else None
        signals = _codes(row.get("signals"), vocab.SIGNALS, dropped, "signals")
        materials.append(
            Material(
                id=row["id"],
                title=row["title"].strip()[:MAX_TITLE],
                format=row["format"],
                topics=_codes(row.get("topics"), vocab.TOPICS, dropped, "topics"),
                # В синтетическом наборе признаки считаются совпадением в названии: сила 2
                signals=tuple((code, 2) for code in signals),
                stages=_codes(row.get("stage"), vocab.STAGES, dropped, "stage"),
                level=level,
                industries=_codes(row.get("industries"), vocab.INDUSTRIES, dropped, "industries"),
                duration_minutes=duration,
                access=access,
                available=bool(row.get("available", True)),
                popularity_raw=raw_popularity[row["id"]],
                popularity=popularity.get(row["id"], 0.0),
                recommended_next=tuple(
                    x
                    for x in (row.get("recommended_next") or [])
                    if isinstance(x, str) and x in seen and x != row["id"]
                ),
                url=url,
                short_benefit=benefit,
                next_step=next_step,
            )
        )
    stats = {"skipped_records": skipped, "dropped_codes": dict(sorted(dropped.items())), "popularity_scale": scale}
    return materials, stats


def load_json_catalog(path: Path, *, source: str) -> Catalog:
    name = Path(path).name
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise CatalogError(f"Файл каталога не найден: {name}") from exc
    except UnicodeDecodeError as exc:
        raise CatalogError(f"Файл каталога не в кодировке UTF-8: {name}") from exc
    except OSError as exc:
        raise CatalogError(f"Файл каталога не читается: {name}") from exc
    try:
        payload = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise CatalogError(f"Файл каталога не является корректным JSON: {name}") from exc
    try:
        materials, stats = parse_materials(payload)
        if not materials:
            raise CatalogError("Каталог пуст")
        return Catalog(
            materials={m.id: m for m in materials},
            source=source,
            version=str(payload.get("version") or f"{source}-unversioned"),
            disabled_features=disabled_features(materials),
            coverage=summarize(materials, **stats),
        )
    except (TypeError, ValueError) as exc:
        # Запасной путь: неучтённый тип данных даёт 503 с записью в журнале, а не падение при запуске
        raise CatalogError(f"В файле каталога неверные данные: {name}") from exc
