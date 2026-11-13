"""Выбор источника каталога по `CATALOG_SOURCE` (PLAN.md, 2.8)."""

from __future__ import annotations

import logging

from ..config import DATA_DIR, Settings
from .models import Catalog, CatalogError
from .synthetic_source import load_json_catalog

log = logging.getLogger("app.catalog")

SYNTHETIC_CATALOG = DATA_DIR / "catalog.synthetic.json"


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
        from .sqlite_source import load_sqlite_catalog  # импорт по требованию: модуль нужен только локально

        catalog = load_sqlite_catalog(
            settings.catalog_path,
            signals_path=settings.catalog_signals_path,
            mapping_path=settings.catalog_mapping,
            relevance="task" if settings.catalog_relevance == "task" else "legacy",
        )
        if settings.catalog_relevance in {"lexical", "hybrid"}:
            from .global_search import configure
            from .sqlite_source import search_cards

            configure(catalog, settings, search_cards(settings.catalog_path, catalog))
    else:  # pragma: no cover - значение проверено в config
        raise CatalogError(f"Неизвестный источник каталога: {settings.catalog_source}")
    catalog.coverage.setdefault("relevance", {
        "requested": settings.catalog_relevance,
        "effective": "task" if catalog.task_index else "legacy",
    })
    log.info(
        "catalog loaded source=%s version=%s size=%d disabled=%s",
        catalog.source,
        catalog.version,
        catalog.size,
        ",".join(catalog.disabled_features) or "-",
    )
    return catalog
