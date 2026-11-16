"""Выбор источника каталога по `CATALOG_SOURCE` и подключение пар совместных записей.

Пары для признака «похожие курсы» берутся из `CATALOG_PAIRS_PATH`.
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
# Каталог ленты по профилю: те же материалы и пары и вымышленные материалы по всем темам
# (evaluation/build_feed_synthetic.py). Размеченный каталог подбора по задаче от него не зависит
FEED_CATALOG = DATA_DIR / "catalog.feed.synthetic.json"
FEED_PAIRS = DATA_DIR / "course-pairs.feed.synthetic.json"


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
    _log_loaded("catalog", catalog)
    return catalog


def load_feed_catalog(settings: Settings, catalog: Catalog) -> Catalog:
    """Каталог ленты по профилю.

    У синтетического источника это расширенный набор из комплекта. У `sqlite` и `file` лента строится по тому же
    каталогу, что и подбор по задаче. Ошибка расширенного набора оставляет ленте основной каталог.
    """
    if settings.catalog_source != "synthetic":
        return catalog
    try:
        extended = load_json_catalog(FEED_CATALOG, source="synthetic")
    except CatalogError as exc:
        log.error("feed catalog not loaded: %s", exc)
        return catalog
    attach_pairs(extended, settings.catalog_pairs_path or FEED_PAIRS, settings.pairs_min_support)
    _log_loaded("feed catalog", extended)
    return extended


def _log_loaded(name: str, catalog: Catalog) -> None:
    pairs = catalog.coverage["course_pairs"]
    log.info(
        "%s loaded source=%s version=%s size=%d disabled=%s pairs=%s:%d",
        name,
        catalog.source,
        catalog.version,
        catalog.size,
        ",".join(catalog.disabled_features) or "-",
        pairs["source"],
        pairs["pairs"],
    )
