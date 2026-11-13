from dataclasses import replace
from threading import Event
from types import SimpleNamespace
from typing import cast

import pytest

from app.catalog.global_search import Card, Hit, SearchIndex, SearchUnavailable
from app.catalog.models import Catalog, HistoryEvent, Material
from app.catalog.reranked_search import RerankedIndex, requirement_state, write_passages
from app.catalog.text_search import TextIndex
from app.ranking.base import MaterialFilters, Profile
from app.ranking.policy import recommend


@pytest.mark.parametrize(
    ("query", "text", "expected"),
    [
        ("Продажи на Озон", "Старт продаж на Ozon", "confirmed"),
        ("Продажи на Озон", "Старт продаж на Wildberries", "conflict"),
        ("Продажи на Озон", "Старт продаж в интернете", "unknown"),
        ("Без НДС в 2026 году", "Работа без НДС в 2025 году", "conflict"),
        ("Без НДС в 2026 году", "Работа с НДС в 2026 году", "conflict"),
        ("Без НДС в 2026 году", "Работа без НДС в 2026 году", "confirmed"),
        ("Без налога на добавленную стоимость", "Продажи без НДС", "confirmed"),
        ("Как подать декларацию по УСН", "Отчётность на ОСНО", "conflict"),
        ("Как подать декларацию по УСН", "Переход с ОСНО на УСН", "confirmed"),
        ("НДС в Исландии", "НДС в России", "conflict"),
    ],
)
def test_query_constraints(query, text, expected):
    assert requirement_state(query, text) == expected


def test_retrieval_keeps_low_channel_scores_and_exact_and_uses_one_passage(tmp_path):
    cards = {
        key: Card(key, title)
        for key, title in (
            ("a", "Правила торговли"),
            ("b", "Обзор рынка"),
            ("c", "Другой материал"),
        )
    }
    fake = SimpleNamespace(
        cards=cards,
        _lexical=lambda terms, scope: [("b", 0.001, "")],
        _semantic=lambda query, scope: [("a", 0.01, "")],
    )
    tokenizer = SimpleNamespace(
        encode=lambda text, **kwargs: SimpleNamespace(
            offsets=[(i, i + 1) for i in range(len(text))],
        )
    )
    path = tmp_path / "passages.sqlite3"
    text = "Чтобы получить лицензию на продажу алкоголя"
    assert write_passages(path, {"a": [("Правила", text), ("Дубль", text)]}, tokenizer) == 1
    index = RerankedIndex(cast(SearchIndex, fake), passages=path)
    candidates, fragments, _ = index.retrieve("Продажа алкоголя", set(cards), frozenset({"c"}))
    assert list(candidates) == ["c", "a", "b"]
    assert fragments["a"] == ("Правила", text)
    assert list(index.retrieve("Лицензия на продажу алкоголя", set(cards), frozenset(), ("лицензировании",))[0]) == [
        "a"
    ]
    assert not index.retrieve("Продажа алкоголя", set(cards), frozenset(), ("визах",))[0]


def test_reranked_respects_filters_and_keeps_weaker_cards_after_strong():
    materials = [
        Material(key, key, fmt, topics=(topic,))
        for key, fmt, topic in (
            ("confirmed", "article", "team"),
            ("useful", "document", "team"),
            ("outside", "article", "finance"),
            ("bought", "article", "team"),
        )
    ]
    observed = []

    def match(task, allowed, exact, gaps):
        observed.append(allowed)
        return {
            key: hit
            for key, hit in {
                "confirmed": Hit(0.96, True, "Название"),
                "useful": Hit(0.6, False, "Описание"),
            }.items()
            if key in allowed
        }

    index = SimpleNamespace(mode="reranked", protect_exact=True, match=match)
    catalog = Catalog(
        {m.id: m for m in materials},
        "sqlite",
        "test",
        text_index=TextIndex(materials),
        search_index=cast(RerankedIndex, index),
    )
    profile = Profile(task="Как оформить сотрудника", topic="team", history=(HistoryEvent("bought", "purchase", 1),))
    response = recommend(catalog, profile)
    assert response.status == "strong"
    assert [item.material.id for item in response.items] == ["confirmed", "useful"]
    filtered = recommend(catalog, replace(profile, filters=MaterialFilters(format="document")))
    assert filtered.status == "weak" and filtered.total_candidates == 1
    assert observed == [{"confirmed", "useful"}, {"useful"}]


def test_deadline_does_not_enqueue_a_second_inference(monkeypatch):
    release = Event()
    index = RerankedIndex(cast(SearchIndex, SimpleNamespace(cards={})), timeout=0.03)
    monkeypatch.setattr(index, "_match", lambda *args: release.wait(1))
    try:
        with pytest.raises(SearchUnavailable, match="inference"):
            index.match("запрос", set(), frozenset())
        with pytest.raises(SearchUnavailable, match="busy"):
            index.match("запрос", set(), frozenset())
    finally:
        release.set()
        index.worker.shutdown()


def test_inference_error_falls_back_to_current_hybrid():
    material = Material("one", "Налоговый учёт", "article", topics=("taxes_law",))

    def failed(*args):
        raise SearchUnavailable("failed")

    current = SimpleNamespace(mode="hybrid", match=lambda *args: {"one": Hit(1, True, "Совпадение")})
    catalog = Catalog(
        {material.id: material},
        "sqlite",
        "test",
        search_index=cast(RerankedIndex, SimpleNamespace(mode="reranked", match=failed)),
        search_fallback=cast(SearchIndex, current),
    )
    assert recommend(catalog, Profile(task="Налоговый учёт")).items[0].material == material
