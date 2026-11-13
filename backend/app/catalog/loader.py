"""Выбор источника каталога по `CATALOG_SOURCE` (docs/plan.md, 2.8) и подключение пар совместных записей.

Пары для признака «похожие курсы» (docs/plan.md, раздел 9, решение 2026-11-11) берутся из `CATALOG_PAIRS_PATH`.
Если переменная пуста, синтетический каталог получает синтетические пары из комплекта, а `sqlite` и `file`
остаются без пар. Без пар признак `co_enrollment` попадает в `disabled_features`, каталог загружается
как обычно. В сводке покрытия пары описаны агрегатами в ключе `course_pairs` (catalog/pairs.py).
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import DATA_DIR, Settings
from .models import Catalog, CatalogError
from .pairs import load_course_pairs
from .synthetic_source import load_json_catalog

log = logging.getLogger("app.catalog")

SYNTHETIC_CATALOG = DATA_DIR / "catalog.synthetic.json"
SYNTHETIC_PAIRS = DATA_DIR / "course-pairs.synthetic.json"


def pairs_path(settings: Settings) -> Path | None:
    """Файл пар: явный `CATALOG_PAIRS_PATH`, иначе синтетические пары только для синтетического каталога."""
    if settings.catalog_pairs_path is not None:
        return settings.catalog_pairs_path
    return SYNTHETIC_PAIRS if settings.catalog_source == "synthetic" else None


def attach_pairs(catalog: Catalog, path: Path | None, min_support: int) -> Catalog:
    """Подключает пары к каталогу. Ошибка файла пар отключает признак, а не каталог."""
    pairs, summary = load_course_pairs(path, catalog.materials, min_support)
    catalog.course_pairs = pairs
    catalog.coverage = {**catalog.coverage, "course_pairs": summary}
    if pairs is None and "co_enrollment" not in catalog.disabled_features:
        catalog.disabled_features = (*catalog.disabled_features, "co_enrollment")
    return catalog


def load_catalog(settings: Settings) -> Catalog:
    if settings.catalog_source == "synthetic":
        catalog = load_json_catalog(SYNTHETIC_CATALOG, source="synthetic")
    elif settings.catalog_source == "file":
        if settings.catalog_path is None:
            raise CatalogError("Для CATALOG_SOURCE=file нужен CATALOG_PATH")
        catalog = load_json_catalog(settings.catalog_path, source="file")
    elif settings.catalog_source == "sqlite":
        if settings.catalog_path is None:
            raise CatalogError("Для CATALOG_SOURCE=sqlite нужен CATALOG_PATH")
        # Импорт по требованию: модуль нужен только локально
        from .sqlite_source import load_sqlite_catalog  # noqa: PLC0415

        catalog = load_sqlite_catalog(
            settings.catalog_path,
            signals_path=settings.catalog_signals_path,
            mapping_path=settings.catalog_mapping,
        )
    else:  # pragma: no cover - значение проверено в config
        raise CatalogError(f"Неизвестный источник каталога: {settings.catalog_source}")
    attach_pairs(catalog, pairs_path(settings), settings.pairs_min_support)
    pairs = catalog.coverage["course_pairs"]
    log.info(
        "catalog loaded source=%s version=%s size=%d disabled=%s pairs=%s:%d",
        catalog.source,
        catalog.version,
        catalog.size,
        ",".join(catalog.disabled_features) or "-",
        pairs["source"],
        pairs["pairs"],
    )
    return catalog
