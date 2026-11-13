import json
from dataclasses import replace
from typing import cast

import pytest

from app.catalog.global_search import (
    DEFAULT_THRESHOLDS,
    Card,
    SearchIndex,
    SearchUnavailable,
    build,
    cards_for,
    configure,
    digest,
    fingerprint,
)
from app.catalog.models import Catalog, HistoryEvent, Material
from app.catalog.text_search import TextIndex
from app.config import Settings
from app.ranking.base import MaterialFilters, Profile
from app.ranking.policy import recommend

from .conftest import ids


@pytest.fixture
def indexed(tmp_path):
    materials = [
        Material("exact", "ОКВЭД для ИП", "article", topics=("taxes_law",)),
        Material("cross", "Коды экономической деятельности", "document", topics=("start",)),
        Material("hidden", "ОКВЭД скрытый", "article", available=False),
        Material("purchase", "Справочник ОКВЭД", "article", access="paid"),
        Material("license", "Как получить лицензию на продажу алкоголя", "article", topics=("taxes_law",)),
        Material("market", "Как разместить товар на Ozon", "article", topics=("marketplaces",)),
        Material("other", "Как разместить товар на Wildberries", "article", topics=("marketplaces",)),
    ]
    catalog = Catalog({m.id: m for m in materials}, "sqlite", "test", text_index=TextIndex(materials))
    cards = cards_for(catalog, {"cross": "ОКВЭД: как выбрать код деятельности"})
    build(tmp_path, cards, None)
    catalog.search_index = SearchIndex(tmp_path, cards, "lexical")
    return catalog, cards


def test_global_search_scope_filters_and_protected_routes(indexed):
    catalog, _ = indexed
    query = Profile(task="Как выбрать ОКВЭД для ИП", history=(HistoryEvent("purchase", "purchase", 1),))
    result = recommend(catalog, query)
    assert ids(result) == ["exact", "cross"]
    assert ids(recommend(catalog, replace(query, topic="start"))) == ["cross"]
    filtered = recommend(catalog, replace(query, filters=MaterialFilters(format="document")))
    assert ids(filtered) == ["cross"] and filtered.total_candidates == 1
    assert filtered.filter_options is not None and "article" in filtered.filter_options.formats
    assert ids(recommend(catalog, replace(query, limit=1))) == ids(result)[:1]
    assert "в кратком описании" in filtered.reasons[0][0]
    assert recommend(catalog, Profile(task="Нужна виза")).status == "none"
    assert ids(recommend(catalog, Profile(task="Нужна лицензия на продажу алкоголя"))) == ["license"]
    assert ids(recommend(catalog, Profile(task="Как разместить товар на Озон"))) == ["market"]
    assert recommend(catalog, query, "baseline") == recommend(replace(catalog, search_index=None), query, "baseline")


def test_constraints_distinguish_negation_and_year(tmp_path):
    cards = [
        Card("no-tax", "Продажа товаров без НДС в 2026 году"),
        Card("tax", "Продажа товаров с НДС в 2026 году"),
        Card("old", "Продажа товаров без НДС в 2025 году"),
    ]
    build(tmp_path, cards, None)
    index = SearchIndex(tmp_path, cards, "lexical")
    assert set(index.match("Продажа без НДС в 2026 году", {c.id for c in cards}, frozenset())) == {"no-tax"}
    with pytest.raises(SearchUnavailable):
        SearchIndex(tmp_path, cards[:-1], "lexical")


def test_missing_model_requires_released_lexical_fallback(indexed):
    catalog, cards = indexed
    assert isinstance(catalog.search_index, SearchIndex)
    directory = catalog.search_index.path.parent
    settings = Settings(
        catalog_path=directory / "catalog.sqlite3", catalog_relevance="hybrid", catalog_search_dir=directory
    )
    catalog.search_index = None
    configure(catalog, settings, cards)
    assert catalog.coverage["relevance"] == {"requested": "hybrid", "effective": "legacy"}
    assert catalog.search_index is None
    policy = directory / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "catalog": fingerprint(cards),
                "index": digest(directory / "manifest.json"),
                "thresholds": DEFAULT_THRESHOLDS,
                "lexical_released": True,
            }
        ),
        encoding="utf-8",
    )
    settings = replace(settings, catalog_search_policy=policy)
    configure(catalog, settings, cards)
    assert catalog.coverage["relevance"]["effective"] == "lexical"
    fallback = cast(SearchIndex | None, catalog.search_index)
    assert fallback is not None and fallback.mode == "lexical"
