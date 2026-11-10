"""Причины соответствуют признакам с положительным вкладом (PLAN.md, 3.6)."""

from __future__ import annotations

import pytest

from app.catalog.models import HistoryEvent
from app.ranking.base import POPULAR_TOP_N, HistoryIndex, Profile
from app.ranking.explain import (
    MAX_REASON_CHARS,
    MAX_REASON_PHRASES,
    POPULARITY_PHRASE,
    QUOTED_TITLE_CHARS,
    _fit,
    next_step,
    short_title,
)
from app.ranking.policy import eligible, recommend

from .conftest import catalog_from_payloads, read_json

PROFILES = ["P01", "P02", "P05", "P06", "P07", "P08", "P09", "P10"]
# Название предельной длины (MAX_TITLE = 120 в загрузчике JSON)
LONG_TITLE = (
    "Статья: как выбрать аудиторию, первый рекламный канал и бюджет для небольшой кофейни в городе до восьмисот "
    "тысяч жителей"
)

# Признак, который называет фраза, по устойчивым словам шаблонов
MARKERS = (
    ("Тема «", "topic"),
    ("Материал о теме", "signal"),
    ("стадии «", "stage"),
    ("Похоже, ", "stage"),
    ("На шаг ", "level"),
    ("сферы «", "industry"),
    ("Продолжает материал", "continuation"),
    ("Вы начали", "in_progress"),
)


def features_of(phrase: str) -> set[str]:
    return {feature for marker, feature in MARKERS if marker in phrase}


@pytest.mark.parametrize("profile_id", PROFILES)
def test_every_phrase_reflects_a_positive_contribution(run, profile_id):
    outcome = run(profile_id)
    for item, reasons in zip(outcome.items, outcome.reasons):
        assert 1 <= len(reasons) <= MAX_REASON_PHRASES
        assert sum(len(r) for r in reasons) + 2 * (len(reasons) - 1) <= MAX_REASON_CHARS
        for phrase in reasons:
            if phrase == POPULARITY_PHRASE:
                assert item.tie_won and item.popular_in_topic
                continue
            named = features_of(phrase)
            assert named, phrase
            for feature in named:
                assert item.contributions.get(feature, 0) > 0, (item.material.id, phrase)


@pytest.mark.parametrize("profile_id", PROFILES)
def test_strongest_profile_feature_is_explained(run, profile_id):
    outcome = run(profile_id)
    for item, reasons in zip(outcome.items, outcome.reasons):
        # Уровень, формат и длительность показывают бейджи, в причине они не повторяются
        badge_only = {"level", "format", "effort"}
        positive = {
            k: v
            for k, v in item.contributions.items()
            if v > 0 and k not in badge_only and k != "topic"
        }
        if not positive:
            continue
        top = max(positive.values())
        strongest = {k for k, v in positive.items() if v == top}
        named = set().union(*(features_of(r) for r in reasons))
        assert strongest & named, (item.material.id, reasons, item.contributions)


@pytest.mark.parametrize("profile_id", PROFILES)
def test_personal_reasons_do_not_restate_badges(run, profile_id):
    outcome = run(profile_id)
    for reasons in outcome.reasons:
        text = " ".join(reasons)
        assert "Уровень «" not in text
        assert "уровня «" not in text
        assert "Формат «" not in text
        assert "Займёт около" not in text


def test_p01_reasons_name_stage_and_m01_industry(run):
    outcome = run("P01")
    for item, reasons in zip(outcome.items, outcome.reasons):
        text = " ".join(reasons)
        assert "стадии «недавно начали»" in text, item.material.id
        if item.material.id == "M01":
            assert "сферы «кафе и рестораны»" in text


def test_p02_course_reason_names_signal_without_restating_badges(run):
    outcome = run("P02")
    first = outcome.reasons[0]
    assert outcome.items[0].material.id == "M02"
    assert any("Рекламный бюджет и окупаемость" in r for r in first)
    text = " ".join(first)
    assert "Формат «" not in text
    assert "уровня «" not in text
    assert "Займёт около" not in text


def test_history_flags_are_badges_not_reasons(run):
    outcome = run("P02")
    for reasons in outcome.reasons:
        assert not any("уже открывали" in r or "Пройдено" in r for r in reasons)


def test_baseline_reason_is_topic_only(run):
    outcome = run("P01", "baseline")
    assert all(r == ["Совпадает тема «Продвижение»"] for r in outcome.reasons)


def test_next_step_falls_back_to_format_template():
    catalog = catalog_from_payloads(read_json("catalog.fixtures.json"))
    assert next_step(catalog.materials["F02"]) == "Прочитайте и выберите один приём для проверки"
    assert next_step(catalog.materials["F03"]) == "Откройте программу и первый урок"


def test_nested_quotes_in_continuation_phrase(run):
    outcome = run("P08", limit=10)
    phrases = [r for reasons in outcome.reasons for r in reasons if r.startswith("Продолжает")]
    assert phrases and all("„" in p for p in phrases)


def test_long_title_keeps_the_continuation_reason():
    assert len(LONG_TITLE) == 120
    rows = [
        {"id": "A", "title": LONG_TITLE, "format": "article", "topics": ["marketing"], "popularity": 10,
         "recommended_next": ["B"]},
        {"id": "B", "title": "Шаблон: план публикаций", "format": "template", "topics": ["marketing"],
         "popularity": 50},
        {"id": "C", "title": "Статья: реклама у блогеров", "format": "article", "topics": ["marketing"],
         "popularity": 90},
    ]
    catalog = catalog_from_payloads({"materials": rows})
    profile = Profile(task="Как продвигать бизнес", history=(HistoryEvent("A", "view", 1),))
    outcome = recommend(catalog, profile, "personal")
    first, reasons = outcome.items[0], outcome.reasons[0]
    assert first.material.id == "B" and first.contributions == {"topic": 3.0, "continuation": 1.5}
    phrase = next(r for r in reasons if r.startswith("Продолжает материал «"))
    title = phrase.removeprefix("Продолжает материал «").removesuffix("» из вашей истории")
    assert title == "Статья: как выбрать аудиторию, первый рекламный канал…"
    assert len(title) <= QUOTED_TITLE_CHARS + 1 and LONG_TITLE.startswith(title[:-1])
    assert sum(len(r) for r in reasons) + 2 * (len(reasons) - 1) <= MAX_REASON_CHARS


def test_fit_drops_weaker_phrases_and_topic_before_the_strongest():
    topic, strongest, weak = "Т" * 80, "С" * 110, "У" * 20
    assert _fit([("topic", topic), ("continuation", strongest), ("effort", weak)]) == [strongest]
    assert _fit([("topic", topic), ("effort", weak)]) == [topic, weak]


def test_short_title_cuts_at_a_word_and_closes_the_quote():
    assert short_title("Шаблон: план публикаций") == "Шаблон: план публикаций"
    title = "Курс «Системный маркетинг для растущего бизнеса: от первой рекламы до отдела продаж»"
    assert short_title(title) == "Курс «Системный маркетинг для растущего бизнеса: от первой…»"
    assert short_title("А" * 130) == "А" * QUOTED_TITLE_CHARS + "…"


def test_personal_and_starter_reasons_do_not_duplicate_badges():
    rows = [{"id": "S1", "title": "Статья о первой продаже", "format": "article", "topics": ["sales"],
             "level": "intro", "popularity": 10, "duration_minutes": 21}]
    catalog = catalog_from_payloads({"materials": rows})
    personal = recommend(catalog, Profile(task="Как увеличить продажи", experience="none"), "personal")
    assert personal.reasons[0] == ["Тема «Продажи» совпадает с задачей"]
    cold = recommend(catalog, Profile(), "personal")
    assert cold.reasons[0] == ["Стартовый материал по теме «Продажи»"]


def test_popularity_phrase_after_show_more_only_for_top_of_topic(run):
    outcome = run("P05", limit=10)
    marked = [i.material.id for i, r in zip(outcome.items, outcome.reasons) if POPULARITY_PHRASE in r]
    # M07 и S04 выигрывают равенство, но в своих темах только четвёртые по популярности
    assert marked == ["M03", "S02", "M02", "S01", "M01", "S03"]


@pytest.mark.parametrize("profile_id", PROFILES)
def test_popularity_phrase_is_true_for_its_topic(run, catalog, profiles, profile_id):
    outcome = run(profile_id, limit=10)
    pool = eligible(catalog, HistoryIndex.build(profiles[profile_id].history))
    for item, reasons in zip(outcome.items, outcome.reasons):
        if POPULARITY_PHRASE not in reasons:
            continue
        values = sorted((m.popularity for m in pool if item.matched_topic in m.topics), reverse=True)
        assert item.material.popularity >= values[min(POPULAR_TOP_N, len(values)) - 1], item.material.id
