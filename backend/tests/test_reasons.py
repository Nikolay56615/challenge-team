"""Причины соответствуют признакам с положительным вкладом (docs/plan.md, 3.6)."""

from __future__ import annotations

import pytest

from app import vocab
from app.catalog.lexicon import parse_task
from app.catalog.models import HistoryEvent
from app.ranking import explain
from app.ranking.base import POPULAR_TOP_N, Context, HistoryIndex, Profile, Scored
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
    # Тема, выбранная в уточнении при пустой задаче
    ("Вы выбрали тему «", "topic"),
    ("Материал о теме", "signal"),
    # Фраза D01 с цитатой слов задачи (docs/plan.md, 3.6; решение 2026-11-11)
    ("В задаче вы назвали «", "signal"),
    ("стадии «", "stage"),
    ("Похоже, ", "stage"),
    ("На шаг ", "level"),
    ("сферы «", "industry"),
    ("Продолжает материал", "continuation"),
    ("Вы начали", "in_progress"),
    # Пилот «похожие курсы» (docs/plan.md, раздел 9, решение 2026-11-11)
    ("Тема из вашей истории", "history_topic"),
    ("Этот курс выбрал", "co_enrollment"),
)


def features_of(phrase: str) -> set[str]:
    return {feature for marker, feature in MARKERS if marker in phrase}


@pytest.mark.parametrize(
    "feature", ["topic", "signal", "continuation", "history_topic", "co_enrollment", "format", "effort", "fit"]
)
def test_feature_without_a_match_gives_no_phrase(catalog, feature):
    """Фраза признака опирается на совпадение: без темы, признака, источника продолжения или пары фразы нет.
    Формат и усилие фраз не дают вовсе: их показывают бейджи карточки."""
    ctx = Context(profile=Profile(), parsed=parse_task(""), topics=(), history=HistoryIndex.build(()),
                  disabled=frozenset(), catalog=catalog.materials)
    assert explain._phrase(feature, Scored(material=catalog.materials["M01"]), ctx) is None


def test_continuation_of_a_material_outside_the_catalog_gives_no_phrase(catalog):
    ctx = Context(profile=Profile(), parsed=parse_task(""), topics=(), history=HistoryIndex.build(()),
                  disabled=frozenset(), catalog=catalog.materials)
    item = Scored(material=catalog.materials["M01"], continuation_of="NOT-IN-CATALOG")
    assert explain._phrase("continuation", item, ctx) is None


@pytest.mark.parametrize("profile_id", PROFILES)
def test_each_reason_explains_ranking_or_starter_topic(run, profile_id):
    outcome = run(profile_id)
    for item, reasons in zip(outcome.items, outcome.reasons, strict=True):
        assert 1 <= len(reasons) <= MAX_REASON_PHRASES
        assert sum(len(r) for r in reasons) + 2 * (len(reasons) - 1) <= MAX_REASON_CHARS
        if item.starter_topic:
            assert reasons == [f"Стартовый материал по теме «{vocab.topic_label(item.starter_topic)}»"]
            continue
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
    for item, reasons in zip(outcome.items, outcome.reasons, strict=True):
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
    for item, reasons in zip(outcome.items, outcome.reasons, strict=True):
        text = " ".join(reasons)
        assert "стадии «недавно начали»" in text, item.material.id
        if item.material.id == "M01":
            assert "сферы «кафе и рестораны»" in text


def test_p02_course_reason_names_signal_without_restating_badges(run):
    outcome = run("P02")
    first = outcome.reasons[0]
    assert outcome.items[0].material.id == "M02"
    assert first[0] == "В задаче вы назвали «эффективность» — материал о теме «Рекламный бюджет и окупаемость»"
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
    # Без длительности — «глагол + объект»; у курса длительность относится ко всему курсу, а не к шагу
    assert next_step(catalog.materials["F02"]) == "Прочитайте и выберите один приём для проверки"
    assert next_step(catalog.materials["F03"]) == "Откройте программу и первый урок"
    # С известной длительностью шаблон называет время (правила микротекстов D19)
    assert next_step(catalog.materials["F01"]) == "Пройдите пункты и отметьте выполненное (около 15 минут)"
    assert next_step(catalog.materials["F04"]) == "Скопируйте документ и заполните под свой бизнес (около 20 минут)"


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
    marked = [i.material.id for i, r in zip(outcome.items, outcome.reasons, strict=True) if POPULARITY_PHRASE in r]
    # M07 и S04 выигрывают равенство, но в своих темах только четвёртые по популярности
    assert marked == ["M03", "S02", "M02", "S01", "M01", "S03"]


# ---------- D01: цитата слов задачи во фразе о признаке ----------


@pytest.mark.parametrize(
    ("profile_id", "cards", "phrase"),
    [
        ("P02", ["M02", "M05", "M06"],
         "В задаче вы назвали «эффективность» — материал о теме «Рекламный бюджет и окупаемость»"),
        ("P09", ["A01"], "В задаче вы назвали «налоговый режим» — материал о теме «Выбор налогового режима»"),
        # В задаче P10 признак находят «декларацию» и «штраф»; цитируется первое слева совпадение
        ("P10", ["A02", "A04"], "В задаче вы назвали «декларацию» — материал о теме «Налоги и отчётность»"),
    ],
)
@pytest.mark.parametrize("limit", [5, 10])
def test_d01_quotes_the_words_of_the_task(run, profile_id, cards, phrase, limit):
    outcome = run(profile_id, limit=limit)
    assert [i.material.id for i, r in zip(outcome.items, outcome.reasons, strict=True) if phrase in r] == cards
    assert not any(p.startswith("Материал о теме") for reasons in outcome.reasons for p in reasons)


def test_d01_changes_only_p02_p09_p10(run, profiles):
    """У остальных тестовых профилей признак из текста не дал вклада: фразы D01 у них нет."""
    quoted = {
        pid
        for pid in profiles
        for limit in (5, 10)
        if any("В задаче вы назвали" in p for reasons in run(pid, limit=limit).reasons for p in reasons)
    }
    assert quoted == {"P02", "P09", "P10"}


def test_d01_quotes_the_concept_as_typed():
    assert explain.signal_phrase("crm", "Какую CRM выбрать") == (
        "В задаче вы назвали «CRM» — материал о теме «Работа с CRM и клиентской базой»"
    )
    # Без слов признака в задаче остаётся прежняя фраза
    assert explain.signal_phrase("crm", "Как продвигать бизнес") == "Материал о теме «Работа с CRM и клиентской базой»"
    assert explain.signal_phrase("crm", "") == "Материал о теме «Работа с CRM и клиентской базой»"


@pytest.mark.parametrize(
    ("task", "topics", "words"),
    [
        # Задача без темы: материалы отобраны по понятию «CAC» или «ROMI»; широкое слово «эффективно»
        # понятия не называет
        ("Как эффективно снизить CAC", (), "CAC"),
        ("Эффективно ли тратить, какой ROMI нормальный", (), "ROMI"),
        # Задача с темой: понятие названо сочетанием, цитата — всё сочетание, а не одно широкое слово
        ("Эффективность рекламы упала", ("marketing",), "Эффективность рекламы"),
    ],
)
def test_d01_quotes_the_words_of_the_concept(catalog, task, topics, words):
    """Если задача называет признак как понятие, цитата называет слова понятия (ревью потока текстов)."""
    outcome = recommend(catalog, Profile(task=task), "personal")
    assert outcome.status == "strong" and outcome.detected_topics == topics
    quoted = {p for reasons in outcome.reasons for p in reasons if p.startswith("В задаче вы назвали")}
    assert quoted == {f"В задаче вы назвали «{words}» — материал о теме «Рекламный бюджет и окупаемость»"}


def test_d01_keeps_every_phrase_the_short_signal_phrase_keeps(catalog):
    """Цитата длиннее прежней фразы. Если из-за неё пределы 3.6 вытеснили бы другую верную фразу, остаётся
    «Материал о теме «…»» и все фразы (ревью потока текстов: продолжение истории A04 терялось)."""
    task = "Как сдать декларацию и не получить штраф"
    profile = Profile(task=task, stage="start", experience="some", industry="b2b",
                      history=(HistoryEvent("A02", "start", 1),))
    outcome = recommend(catalog, profile, "personal")
    reasons = dict(zip([i.material.id for i in outcome.items], outcome.reasons, strict=True))
    assert reasons["A04"] == [
        "Материал о теме «Налоги и отчётность»",
        "Подходит для стадии «недавно начали»",
        "Продолжает материал «Шаблон: календарь отчётности на год» из вашей истории",
    ]
    # Где цитата ничего не вытесняет, она остаётся: у A02 три фразы с цитатой помещаются в 180 символов
    assert "В задаче вы назвали «декларацию» — материал о теме «Налоги и отчётность»" in reasons["A02"]
    assert len(reasons["A02"]) == MAX_REASON_PHRASES


def test_d01_shortens_a_long_quote():
    task = "Как автоматизировать-документооборот-склад-и-кассу без ошибок"
    phrase = explain.signal_phrase("automation", task)
    words = phrase.removeprefix("В задаче вы назвали «").split("»")[0]
    assert words.endswith("…") and len(words) <= explain.TASK_WORDS_CHARS + 1
    assert task.startswith("Как " + words[:-1])
    assert len(phrase) <= MAX_REASON_CHARS


@pytest.mark.parametrize("profile_id", ["P03", "P04", "P07"])
def test_explicit_topic_the_task_does_not_name_is_named_as_chosen(run, profile_id):
    """Тема из уточнения, которой нет в задаче: «Вы выбрали тему …», а не «совпадает с задачей». P03 — пустая
    задача, P04 и P07 — ответ none, после которого пользователь выбирает тему, а текст задачи остаётся."""
    outcome = run(profile_id, topic="start", limit=10)
    phrases = [p for reasons in outcome.reasons for p in reasons]
    assert "Вы выбрали тему «Старт бизнеса»" in phrases
    assert not any("совпадает с задачей" in p for p in phrases)


def test_explicit_topic_named_by_the_task_still_matches_it(run):
    """Задача P05 называет и продажи, и продвижение: выбранная из них тема совпадает с задачей."""
    for topic, label in (("sales", "Продажи"), ("marketing", "Продвижение")):
        chosen = run("P05", topic=topic, limit=10)
        assert any(p == f"Тема «{label}» совпадает с задачей" for reasons in chosen.reasons for p in reasons)
        assert not any("Вы выбрали тему" in p for reasons in chosen.reasons for p in reasons)


@pytest.mark.parametrize(
    "task", ["Как продвигать кофейню", "Нужно выстроить системное продвижение и считать его эффективность"]
)
def test_title_match_reason_keeps_the_two_step_fit(catalog, task):
    """Персональный метод передаёт фразу отбора по названию в personal_reasons. Итог тот же, что у
    title_match_reasons поверх готовой причины, или в нём больше фраз: правило D01 о вытеснении видит
    итоговую причину."""
    profile = Profile(task=task, stage="start", experience="experienced", industry="horeca",
                      history=(HistoryEvent("M01", "complete", 1), HistoryEvent("M04", "view", 2)), limit=10)
    outcome = recommend(catalog, profile, "personal")
    ctx = Context(profile=profile, parsed=parse_task(profile.task), topics=("marketing",),
                  history=HistoryIndex.build(profile.history), disabled=frozenset(), catalog=catalog.materials)
    gaps = ("лицензировании", "продаже алкоголя")
    lead = explain.title_match_phrase(gaps)
    for item in outcome.items:
        once = explain.personal_reasons(item, ctx, lead=lead)
        twice = explain.title_match_reasons(gaps, explain.personal_reasons(item, ctx))
        assert once[0] == lead and (once == twice or len(once) > len(twice)), (item.material.id, once, twice)


@pytest.mark.parametrize("profile_id", PROFILES)
def test_popularity_phrase_is_true_for_its_topic(run, catalog, profiles, profile_id):
    outcome = run(profile_id, limit=10)
    pool = eligible(catalog, HistoryIndex.build(profiles[profile_id].history))
    for item, reasons in zip(outcome.items, outcome.reasons, strict=True):
        if POPULARITY_PHRASE not in reasons:
            continue
        values = sorted((m.popularity for m in pool if item.matched_topic in m.topics), reverse=True)
        assert item.material.popularity >= values[min(POPULAR_TOP_N, len(values)) - 1], item.material.id
