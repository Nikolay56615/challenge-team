"""Порядок выдачи на синтетическом каталоге и свойства выдачи."""

from __future__ import annotations

import pytest

from app.catalog.models import Catalog, HistoryEvent
from app.ranking.base import Profile
from app.ranking.policy import levels_beyond_courses, recommend

from .conftest import catalog_from_payloads, ids, read_json

TOP5_P01 = ["M01", "M07", "M04", "M08", "M03"]
TOP5_P02 = ["M02", "M05", "M06", "M08", "M07"]
BASELINE_MARKETING = ["M03", "M02", "M01", "M07", "M05"]
SHOW_MORE_LIMIT = 10  # «Показать ещё» повторяет запрос с этим пределом
NARROW_TASK = "Нужна лицензия на продажу алкоголя"


def synthetic_without(*topics: str) -> Catalog:
    """Синтетический каталог без материалов указанных тем."""
    rows = [r for r in read_json("catalog.synthetic.json")["materials"] if not set(r["topics"]) & set(topics)]
    return catalog_from_payloads({"materials": rows})


def test_baseline_is_the_same_for_p01_and_p02(run):
    assert ids(run("P01", "baseline")) == BASELINE_MARKETING
    assert ids(run("P02", "baseline")) == BASELINE_MARKETING


def test_baseline_ignores_history_and_profile(run):
    outcome = run("P02", "baseline")
    assert outcome.items[0].material.id == "M03"
    assert outcome.items[0].flags == ["completed"]
    assert all(item.score == 0 for item in outcome.items)


def test_p01_personal_order_and_scores(run):
    outcome = run("P01")
    assert outcome.status == "strong"
    assert ids(outcome) == TOP5_P01
    assert [item.score for item in outcome.items] == [8.5, 7.5, 7.5, 7.0, 6.5]
    assert outcome.total_candidates == 8


def test_p02_personal_order_and_history(run):
    outcome = run("P02")
    assert ids(outcome) == TOP5_P02
    assert [item.score for item in outcome.items] == [10.5, 9.5, 9.0, 4.5, 3.5]
    assert outcome.items[4].flags == ["viewed"]
    full = run("P02", limit=10)
    assert ids(full)[5:] == ["M04", "M03", "M01"]
    assert full.items[6].flags == ["completed"]


def test_personal_differs_between_p01_and_p02(run):
    assert ids(run("P01")) != ids(run("P02"))


def test_p01_route_follows_editorial_links(run):
    assert [m.id for m in run("P01").route] == ["M01", "M04", "M03"]


def test_p06_continuation_after_viewed_checklist(run):
    outcome = run("P06")
    assert ids(outcome)[:2] == ["M04", "M03"]
    assert outcome.items[0].continuation_of == "M01"
    viewed = next(i for i in outcome.items if i.material.id == "M01")
    assert viewed.flags == ["viewed"]


def test_p08_started_course_goes_first(run):
    outcome = run("P08")
    assert outcome.items[0].material.id == "M08"
    assert outcome.items[0].flags == ["in_progress"]


def test_p09_signal_agrees_with_popularity(run):
    assert ids(run("P09")) == ["A01", "A02", "A04"]
    assert ids(run("P09", "baseline")) == ["A01", "A02", "A04"]


def test_p10_signal_changes_order_inside_topic(run):
    assert ids(run("P10")) == ["A02", "A04", "A01"]
    assert ids(run("P10", "baseline")) == ["A01", "A02", "A04"]


def test_p05_is_ambiguous(run):
    outcome = run("P05")
    assert outcome.status == "weak"
    assert outcome.detected_topics == ("marketing", "sales")
    assert [o["value"] for o in outcome.clarification["options"]] == ["marketing", "sales"]
    assert outcome.total_candidates == 12
    assert ids(outcome) == ["M03", "S02", "M02", "S01", "M01"]


def test_p05_with_chosen_topic_is_strong_and_single_topic(run):
    outcome = run("P05", topic="marketing")
    assert outcome.status == "strong"
    assert all("marketing" in item.material.topics for item in outcome.items)


@pytest.mark.parametrize("method", ["personal", "baseline"])
def test_p07_gives_starter_and_topic_choice_when_no_title_matches(run, method):
    outcome = run("P07", method)
    assert outcome.status == "none"
    assert outcome.detected_topics == ("sales",)
    assert outcome.message == "По этому запросу подходящих материалов не нашлось"
    assert ids(outcome) == ["A01", "L01", "S01", "M01", "O01"]
    assert all(item.starter_topic for item in outcome.items)
    assert any(option["value"] == "sales" for option in outcome.clarification["options"])
    narrowed = run("P07", method, topic="sales")
    assert narrowed.status == "strong" and set(ids(narrowed)) == {"S01", "S02", "S03", "S04"}


def test_narrow_request_requires_all_title_matches_and_personal_searches_across_topics():
    catalog = catalog_from_payloads({"materials": [
        {"id": "X01", "title": "Как получить лицензию на продажу алкоголя", "format": "article",
         "topics": ["taxes_law"]},
        {"id": "X02", "title": "Лицензия на ПО", "format": "article", "topics": ["sales"]},
        {"id": "X03", "title": "Продажа алкоголя", "format": "article", "topics": ["sales"]},
    ]})
    profile = Profile(task=NARROW_TASK)
    personal = recommend(catalog, profile, "personal")
    baseline = recommend(catalog, profile, "baseline")
    assert personal.status == "strong" and ids(personal) == ["X01"]
    assert personal.total_candidates == 1
    assert personal.reasons[0][0] == "В названии есть упоминание о лицензировании и продаже алкоголя"
    assert baseline.status == "none" and all(item.starter_topic for item in baseline.items)


@pytest.mark.parametrize("method", ["personal", "baseline"])
@pytest.mark.parametrize("exclusion", ["unavailable", "purchased"])
def test_narrow_request_applies_catalog_eligibility(method, exclusion):
    catalog = catalog_from_payloads({"materials": [
        {"id": "X01", "title": "Как получить лицензию на продажу алкоголя", "format": "article", "topics": ["sales"],
         "available": exclusion != "unavailable"},
        {"id": "X02", "title": "Продажа алкоголя и порядок получения лицензии", "format": "article",
         "topics": ["sales"]},
    ]})
    history = (HistoryEvent("X01", "purchase", 1),) if exclusion == "purchased" else ()
    outcome = recommend(catalog, Profile(task=NARROW_TASK, history=history), method)
    assert outcome.status == "strong" and ids(outcome) == ["X02"]
    assert outcome.total_candidates == 1


def test_narrow_request_ranks_title_matches_by_the_selected_method():
    catalog = catalog_from_payloads({"materials": [
        {"id": "X01", "title": "Лицензия на продажу алкоголя для нового бизнеса", "format": "article",
         "topics": ["sales"], "stage": ["start"], "popularity": 1},
        {"id": "X02", "title": "Продажа алкоголя и продление лицензии", "format": "article",
         "topics": ["sales"], "stage": ["growth"], "popularity": 10},
    ]})
    profile = Profile(task=NARROW_TASK, stage="start")
    assert ids(recommend(catalog, profile, "personal")) == ["X01", "X02"]
    assert ids(recommend(catalog, profile, "baseline")) == ["X02", "X01"]


def test_narrow_request_with_an_independent_concept_uses_concept_search(catalog):
    outcome = recommend(catalog, Profile(task="Какую CRM выбрать и как получить лицензию"))
    assert outcome.status == "strong" and ids(outcome) == ["S02", "S03"]
    assert "Материалов о лицензировании пока нет" in outcome.message


def test_p04_unknown_topic_gives_gap_and_starter(run):
    outcome = run("P04")
    assert outcome.status == "none"
    assert ids(outcome) == ["A01", "L01", "S01", "M01", "O01"]
    assert "наследство" in outcome.message
    values = [o["value"] for o in outcome.clarification["options"]]
    assert "team" not in values and "marketing" in values


def test_p03_cold_start(run):
    outcome = run("P03")
    assert outcome.status == "cold"
    assert ids(outcome) == ["A01", "L01", "S01", "M01", "O01"]
    assert outcome.clarification["question"] == "С чего хотите начать?"
    assert all(not item.material.is_paid and item.material.level == "intro" for item in outcome.items)


def test_mark_studied_moves_card_down_and_lifts_continuation(run):
    before = run("P01")
    after = run("P01", history=(HistoryEvent("M01", "complete", 1),))
    assert ids(before)[0] == "M01"
    assert "M01" not in ids(after)
    assert ids(after)[:2] == ["M04", "M03"]
    full = run("P01", history=(HistoryEvent("M01", "complete", 1),), limit=10)
    assert next(i for i in full.items if i.material.id == "M01").flags == ["completed"]


def test_purchase_excludes_material(run):
    outcome = run("P01", history=(HistoryEvent("M01", "purchase", 1),), limit=10)
    assert "M01" not in ids(outcome)


def test_property_p01_top3_only_intro(run):
    assert all(item.material.level == "intro" for item in run("P01").items[:3])


def test_property_p02_completed_not_above_fifth(run):
    order = ids(run("P02", limit=10))
    assert "M03" not in order[:5]


def test_diversity_limits_one_format_in_top5():
    rows = [
        {"id": f"X0{i}", "title": f"Статья {i}", "format": "article", "topics": ["sales"], "popularity": 100 - i}
        for i in range(1, 6)
    ]
    rows.append({"id": "Y01", "title": "Чек-лист 1", "format": "checklist", "topics": ["sales"], "popularity": 2})
    rows.append({"id": "Y02", "title": "Чек-лист 2", "format": "checklist", "topics": ["sales"], "popularity": 1})
    catalog = catalog_from_payloads({"materials": rows})
    outcome = recommend(catalog, Profile(task="Как увеличить продажи"), "personal")
    formats = [item.material.format for item in outcome.items]
    assert formats.count("article") == 3
    assert [item.material.id for item in outcome.items][3:] == ["Y01", "Y02"]
    # Когда другого формата не осталось, правило не мешает четвёртой статье
    single = catalog_from_payloads({"materials": rows[:-1]})
    order = [i.material.id for i in recommend(single, Profile(task="Как увеличить продажи"), "personal").items]
    assert order == ["X01", "X02", "X03", "Y01", "X04"]


def test_fixtures_duplicates_unavailable_and_links():
    catalog = catalog_from_payloads(read_json("catalog.synthetic.json"), read_json("catalog.fixtures.json"))
    outcome = recommend(catalog, Profile(task="Хочу продвигать свой магазин", limit=10), "personal")
    found = ids(outcome)
    assert "M01" in found and "F01" not in found  # дубликат с меньшей популярностью отброшен
    assert "F06" not in found  # недоступный материал не попадает в выдачу
    cold = recommend(catalog, Profile(), "personal")
    assert "F05" not in ids(cold)  # тема без вводных бесплатных материалов не даёт стартовую позицию


def test_explicit_topic_without_materials_falls_back_to_starter(catalog):
    outcome = recommend(catalog, Profile(task="Как нанять первого сотрудника"), "personal")
    assert outcome.status == "none"
    assert outcome.detected_topics == ("team",)
    assert "Команда" in outcome.message
    assert len(outcome.items) == 5


def test_empty_catalog_gives_empty_status():
    catalog = catalog_from_payloads(
        {"materials": [{"id": "Z1", "title": "Скрытый", "format": "article", "topics": ["sales"], "available": False}]}
    )
    outcome = recommend(catalog, Profile(task=""), "personal")
    assert outcome.status == "empty"
    assert outcome.items == []
    assert outcome.clarification is None


@pytest.mark.parametrize(("task", "status"), [("", "cold"), ("Наследство", "none")])
@pytest.mark.parametrize("method", ["personal", "baseline"])
def test_topics_remain_selectable_without_free_starter_materials(task, status, method):
    catalog = catalog_from_payloads(
        {"materials": [{"id": "Z1", "title": "Курс", "format": "course", "topics": ["sales"], "access": "paid"}]}
    )
    outcome = recommend(catalog, Profile(task=task), method)

    assert outcome.status == status
    assert outcome.items == [] and outcome.total_candidates == 0
    clarification = outcome.clarification
    assert clarification is not None
    assert "стартов" not in clarification["text"] and "Ниже" not in clarification["text"]
    topic, = [option["value"] for option in clarification["options"]]
    assert topic == "sales"
    result = recommend(catalog, Profile(task=task, topic=topic), method)
    assert result.status == "strong" and ids(result) == ["Z1"]


def test_topics_remain_selectable_after_completing_all_starter_materials():
    catalog = catalog_from_payloads(
        {"materials": [{"id": "Z1", "title": "Статья", "format": "article", "topics": ["sales"], "level": "intro"}]}
    )
    assert ids(recommend(catalog, Profile())) == ["Z1"]
    history = (HistoryEvent("Z1", "complete", 1),)
    outcome = recommend(catalog, Profile(history=history))

    assert outcome.status == "cold"
    assert outcome.items == [] and outcome.total_candidates == 0
    assert outcome.clarification is not None
    topic, = [option["value"] for option in outcome.clarification["options"]]
    assert topic == "sales"
    result = recommend(catalog, Profile(topic=topic, history=history))
    assert ids(result) == ["Z1"] and result.items[0].flags == ["completed"]


@pytest.mark.parametrize(
    ("profile_id", "route"), [("P01", ["M01", "M04", "M03"]), ("P06", []), ("P08", ["M08", "M03"])]
)
def test_show_more_keeps_the_route(run, profile_id, route):
    first_page = run(profile_id)
    more = run(profile_id, limit=SHOW_MORE_LIMIT)
    assert [m.id for m in first_page.route] == route
    assert [m.id for m in more.route] == route
    assert {m.id for m in more.route} <= set(ids(first_page))


def test_detected_topic_without_materials_is_named_not_offered(run):
    # P05 распознаёт продвижение и продажи; без материалов о продажах выдача однотемная и уверенная
    outcome = run("P05", catalog_override=synthetic_without("sales"))
    assert outcome.detected_topics == ("marketing", "sales")
    assert outcome.status == "strong" and outcome.clarification is None
    assert outcome.message.startswith(
        "Нашли 8 материалов по теме «Продвижение». По теме «Продажи» материалов пока нет."
    )
    assert all("marketing" in item.material.topics for item in outcome.items)


def test_weak_status_and_options_use_only_topics_with_materials():
    catalog = synthetic_without("taxes_law")
    task = "Хочу больше клиентов и выбрать налоговый режим"
    outcome = recommend(catalog, Profile(task=task), "personal")
    assert outcome.detected_topics == ("taxes_law", "marketing", "sales")
    assert outcome.status == "weak"
    assert outcome.message.startswith(
        "Нашли 12 материалов по темам «Продвижение» и «Продажи». По теме «Налоги и законы» материалов пока нет."
    )
    assert outcome.clarification is not None
    options = [o["value"] for o in outcome.clarification["options"]]
    assert options == ["marketing", "sales"]
    assert outcome.clarification["text"].endswith("Пока показываем материалы по обеим темам.")
    for topic in options:
        assert recommend(catalog, Profile(task=task, topic=topic), "personal").status == "strong"


def test_hiring_and_promotion_shows_promotion_without_false_clarification(catalog):
    outcome = recommend(catalog, Profile(task="Как нанять сотрудника и продвигать кафе"), "personal")
    assert outcome.status == "strong" and outcome.clarification is None
    assert "По теме «Команда» материалов пока нет." in outcome.message
    assert all("marketing" in item.material.topics for item in outcome.items)


def test_none_message_names_several_topics_in_plural(run):
    outcome = run("P05", catalog_override=synthetic_without("marketing", "sales"))
    assert outcome.status == "none"
    assert outcome.message == "По темам «Продвижение» и «Продажи» материалов пока нет"


def test_none_message_converts_quotes_in_the_task_echo(catalog):
    outcome = recommend(catalog, Profile(task="Что такое «наследство»"), "personal")
    assert outcome.status == "none"
    assert outcome.message == "По запросу «Что такое „наследство“» материалов пока нет"


@pytest.mark.parametrize(
    "task",
    [
        "Я новичок, с чего начать продвижение?",
        "Нужен шаблон для продвижения",
        "Как продвигать магазин",
        "Хочу больше клиентов",
        "Какой налоговый режим выбрать для ИП",
    ],
)
def test_popularity_claim_only_when_the_task_did_not_change_the_order(catalog, task):
    outcome = recommend(catalog, Profile(task=task), "personal")
    assert outcome.status in {"strong", "weak"}
    # Допущение 3.4 названо всегда: без подсказок «стадия и опыт не указаны», с подсказками —
    # «уточнения не заполнены, поэтому порядок учитывает описание задачи»
    message = outcome.message.lower()
    assert "стадия и опыт не указаны" in message or "уточнения не заполнены, поэтому" in message
    reordered = any(f != "topic" and v > 0 for item in outcome.items for f, v in item.contributions.items())
    assert ("востребован" in outcome.message) is not reordered


def test_status_line_names_what_was_taken_from_the_task(catalog):
    outcome = recommend(catalog, Profile(task="Я новичок, с чего начать продвижение?"), "personal")
    # «Я новичок» в задаче есть, поэтому «опыт не указан» звучало бы как противоречие
    assert outcome.message == (
        "Нашли 8 материалов по теме «Продвижение». Уточнения не заполнены, "
        "поэтому порядок учитывает описание задачи: старт и уровень «для начинающих»."
    )


def test_format_hint_is_explained_without_a_false_cause(catalog):
    outcome = recommend(catalog, Profile(task="Нужен шаблон для продвижения"), "personal")
    assert outcome.message.endswith(
        "Уточнения не заполнены, поэтому порядок учитывает описание задачи: формат «шаблон»."
    )


def test_popularity_wording_stays_for_p05(run):
    assert run("P05").message.endswith("Показываем 5 самых востребованных: стадия и опыт не указаны.")


def test_novice_chip_is_named_when_levels_are_not_marked():
    rows = [
        {"id": f"S{n}", "title": f"Статья {n}", "format": "article", "topics": ["sales"], "popularity": 10 * n,
         "duration_minutes": 10 * n}
        for n in (1, 2, 4)
    ]
    catalog = catalog_from_payloads({"materials": rows})
    outcome = recommend(catalog, Profile(task="Как увеличить продажи", experience="none"), "personal")
    assert "level" in catalog.disabled_features
    assert outcome.message == "Нашли 3 материала по теме «Продажи». Показываем все с учётом уровня «новичок»."


@pytest.mark.parametrize("bought", ["M01", "F01"])
def test_purchase_of_any_duplicate_hides_the_title(bought):
    catalog = catalog_from_payloads(read_json("catalog.synthetic.json"), read_json("catalog.fixtures.json"))
    history = (HistoryEvent(bought, "purchase", 1),)
    outcome = recommend(catalog, Profile(task="Хочу продвигать свой магазин", history=history, limit=10), "personal")
    assert not {"M01", "F01"} & set(ids(outcome))


def test_purchase_of_an_unavailable_copy_hides_the_available_one():
    rows = [
        {"id": "X1", "title": "Скрипт  продаж", "format": "template", "topics": ["sales"], "popularity": 10},
        {"id": "X2", "title": "скрипт продаж", "format": "template", "topics": ["sales"], "popularity": 90,
         "available": False},
        {"id": "X3", "title": "Скрипт продаж", "format": "article", "topics": ["sales"], "popularity": 5},
    ]
    catalog = catalog_from_payloads({"materials": rows})
    history = (HistoryEvent("X2", "purchase", 1),)
    outcome = recommend(catalog, Profile(task="Как увеличить продажи", history=history), "personal")
    assert ids(outcome) == ["X3"]  # статья с тем же названием — другой материал


def starter_catalog(*extra: dict) -> Catalog:
    """Каталог, где уровень размечен только у курсов, как в копии."""
    rows = [
        {"id": "C1", "title": "Курс для начинающих", "format": "course", "topics": ["marketing"], "level": "intro",
         "popularity": 5},
        {"id": "C2", "title": "Курс для опытных", "format": "course", "topics": ["marketing"], "level": "advanced",
         "popularity": 50},
        {"id": "A1", "title": "Статья о старте", "format": "article", "topics": ["marketing"], "stage": ["start"],
         "popularity": 40},
        {"id": "A2", "title": "Статья о росте", "format": "article", "topics": ["marketing"], "stage": ["growth"],
         "popularity": 45},
        {"id": "A3", "title": "Статья без стадии", "format": "article", "topics": ["marketing"], "popularity": 30},
        *extra,
    ]
    return catalog_from_payloads({"materials": rows})


def test_starter_uses_stage_rule_when_only_courses_have_levels():
    catalog = starter_catalog()
    assert not levels_beyond_courses(catalog)
    # Самый популярный открытый материал со стадией старта или без стадии, а не вводный курс;
    # продвинутый курс в стартовую подборку не попадает
    assert ids(recommend(catalog, Profile(), "personal")) == ["A1"]
    assert ids(recommend(catalog, Profile(task="Как оформить наследство"), "personal")) == ["A1"]


def test_starter_keeps_intro_filter_when_other_formats_have_levels():
    intro_article = {"id": "A4", "title": "Вводная статья", "format": "article", "topics": ["marketing"],
                     "level": "intro", "popularity": 10}
    catalog = starter_catalog(intro_article)
    assert levels_beyond_courses(catalog)
    assert ids(recommend(catalog, Profile(), "personal")) == ["A4"]


# ---------- задача называет понятие признака, но не тему ----------


def test_signal_only_task_takes_candidates_with_the_signal_from_any_topic(catalog):
    outcome = recommend(catalog, Profile(task="Как рассчитать юнит-экономику"), "personal")
    assert outcome.status == "strong" and outcome.detected_topics == ()
    # Признак «Прибыль и рентабельность» есть у L03, M02, M06 и S04 — в разных темах, но не в финансах
    assert sorted(ids(outcome)) == ["L03", "M02", "M06", "S04"]
    assert outcome.message.startswith("Нашли 4 материала на тему «Прибыль и рентабельность».")
    for item, reasons in zip(outcome.items, outcome.reasons, strict=True):
        assert "topic" not in item.contributions
        # Фраза D01 цитирует слово задачи так, как его написал пользователь
        assert "В задаче вы назвали «юнит-экономику» — материал о теме «Прибыль и рентабельность»" in reasons
        assert not any("совпадает с задачей" in r for r in reasons)


def test_signal_only_task_shows_only_materials_with_the_signal(catalog):
    outcome = recommend(catalog, Profile(task="Какую CRM выбрать"), "personal")
    assert outcome.status == "strong" and ids(outcome) == ["S02", "S03"]
    assert outcome.message == "Нашли 2 материала на тему «Работа с CRM и клиентской базой». Стадия и опыт не указаны."
    assert outcome.clarification is None
    assert all(
        reasons[0] == "В задаче вы назвали «CRM» — материал о теме «Работа с CRM и клиентской базой»"
        for reasons in outcome.reasons
    )


def test_signal_only_task_without_such_materials_is_an_honest_gap(catalog):
    outcome = recommend(catalog, Profile(task="Регистрация товарного знака"), "personal")
    assert outcome.status == "none" and outcome.detected_topics == ()
    assert outcome.message == "По запросу «Регистрация товарного знака» материалов пока нет"
    # Первой предлагается тема понятия: товарный знак относится к «Налогам и законам»
    assert outcome.clarification is not None and outcome.clarification["options"][0]["value"] == "taxes_law"
    assert all(item.starter_topic for item in outcome.items)


def test_concept_without_materials_is_named_next_to_found_ones(catalog):
    outcome = recommend(catalog, Profile(task="Какую CRM выбрать и как защитить товарный знак"), "personal")
    assert outcome.status == "strong" and ids(outcome) == ["S02", "S03"]
    assert outcome.message.startswith(
        "Нашли 2 материала на тему «Работа с CRM и клиентской базой». "
        "Материалов на тему «Товарный знак и права на бренд» пока нет."
    )


def test_baseline_does_not_use_signal_concepts(catalog):
    outcome = recommend(catalog, Profile(task="Какую CRM выбрать"), "baseline")
    assert outcome.status == "none"
    assert outcome.message == "Подбор по теме не нашёл тему в запросе «Какую CRM выбрать»"


def test_signal_only_task_falls_back_to_none_when_signals_are_disabled():
    rows = [
        {"id": "S1", "title": "Статья о CRM", "format": "article", "topics": ["sales"], "popularity": 10},
        {"id": "S2", "title": "Чек-лист продаж", "format": "checklist", "topics": ["sales"], "popularity": 20},
    ]
    catalog = catalog_from_payloads({"materials": rows})
    assert "signal" in catalog.disabled_features
    outcome = recommend(catalog, Profile(task="Какую CRM выбрать"), "personal")
    assert outcome.status == "none"


def test_explicit_topic_wins_over_signal_inference(catalog):
    outcome = recommend(catalog, Profile(task="Регистрация товарного знака", topic="taxes_law"), "personal")
    assert outcome.status == "strong" and outcome.detected_topics == ("taxes_law",)


# ---------- пустая выдача со словом-пробелом, маршрут, один материал ----------


def test_narrow_request_without_any_topic_gives_a_starter_when_no_title_matches(catalog):
    outcome = recommend(catalog, Profile(task="Нужен сертификат на продукцию"), "personal")
    assert outcome.status == "none"
    assert outcome.message == "По этому запросу подходящих материалов не нашлось"
    assert all(item.starter_topic for item in outcome.items)


@pytest.mark.parametrize("limit", [1, 2, 3, 4, 5, 10])
def test_route_names_only_shown_materials(catalog, limit):
    profile = Profile(
        task="Хочу начать продвигать свою кофейню, с чего начать?", stage="start", experience="none",
        industry="horeca", limit=limit,
    )
    outcome = recommend(catalog, profile, "personal")
    shown = set(ids(outcome))
    assert all(step.id in shown for step in outcome.route)
    if limit >= 5:
        assert [step.id for step in outcome.route] == ["M01", "M04", "M03"]


def test_single_candidate_message_has_no_order_claim():
    rows = [{"id": "F1", "title": "Статья о налоге", "format": "article", "topics": ["finance"], "popularity": 5}]
    catalog = catalog_from_payloads({"materials": rows})
    personal = recommend(catalog, Profile(task="Как вести учёт финансов"), "personal")
    assert personal.message == "Нашли 1 материал по теме «Финансы и учёт». Стадия и опыт не указаны."
    baseline = recommend(catalog, Profile(task="Как вести учёт финансов"), "baseline")
    assert baseline.message == (
        "Нашли 1 материал по теме «Финансы и учёт». Подбор по теме не учитывает профиль и историю."
    )
