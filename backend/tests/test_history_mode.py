"""Подбор по истории и «похожие курсы» при пустой задаче (docs/plan.md, раздел 9, решение 2026-11-11; 3.4–3.6).

Пилот действует только при пустой задаче и только в персональном методе. Проверяются: условия включения,
курсы других тем среди кандидатов, недоступные курсы истории как якоря без показа (R15), фраза только при
достаточной поддержке и фактическом вкладе (R18, R21), профили P11 и P12, неизменность P01–P10 и подбора
по теме, холодный старт без пар.

Подбор по истории включается, только если курс истории связан парой от порога с допустимым курсом вне
истории, то есть пилот может показать «похожий курс». Иначе остаётся прежняя стартовая подборка: так
P12, у курса которого все пары ниже порога, получает холодный старт (уточнение решения 2026-11-11 после
ревью, вывод O1: кандидатов не ограничивать темами истории).
"""

from __future__ import annotations

import dataclasses
import random

import pytest

from app import vocab
from app.catalog.lexicon import parse_task
from app.catalog.loader import load_catalog
from app.catalog.models import Catalog, HistoryEvent
from app.catalog.pairs import parse_pairs
from app.config import Settings
from app.ranking import explain, personal, policy
from app.ranking.base import Context, HistoryIndex, HistorySignals, Profile
from app.ranking.policy import eligible, recommend

from .conftest import catalog_from_payloads, client_for, ids, make_profile
from .test_explain_faithfulness import faithfulness_violations
from .test_reasons import features_of
from .test_route_properties import route_violations

P01_P10 = [f"P{n:02d}" for n in range(1, 11)]
CO_MARKER = "Этот курс выбрал"
M08_DONE = (HistoryEvent("M08", "complete", 1),)
O03_DONE = (HistoryEvent("O03", "complete", 1),)


def without_pairs(catalog: Catalog) -> Catalog:
    """Тот же каталог без пар: так выглядит источник sqlite или file без CATALOG_PAIRS_PATH."""
    return dataclasses.replace(
        catalog, course_pairs=None, disabled_features=(*catalog.disabled_features, "co_enrollment")
    )


def with_pairs(catalog: Catalog, rows: list[dict], min_support: int = 10) -> Catalog:
    pairs, summary = parse_pairs({"pairs": rows}, catalog.materials, min_support)
    return dataclasses.replace(catalog, course_pairs=pairs, coverage={**catalog.coverage, "course_pairs": summary})


def pair(a: str, b: str, together: int, a_total: int, b_total: int) -> dict:
    return {"a": a, "b": b, "together": together, "a_total": a_total, "b_total": b_total}


def co_phrases(outcome) -> list[str]:
    return [r for reasons in outcome.reasons for r in reasons if CO_MARKER in r]


def pilot_contributions(outcome) -> set[str]:
    return {f for item in outcome.items for f in item.contributions if f in {"co_enrollment", "history_topic"}}


# ---------- P11, P12 и тексты ----------


def test_p11_shows_a_course_of_another_topic_with_the_co_enrollment_phrase(run):
    outcome = run("P11")
    assert outcome.status == "weak" and outcome.detected_topics == () and outcome.route == []
    # Вес темы истории 0,1 (решение 2026-11-13): курсы других тем с парой поднимаются выше материалов темы истории
    assert ids(outcome) == ["M03", "L02", "M02", "A03", "M01"]
    other = [item for item in outcome.items if "marketing" not in item.material.topics]
    assert [item.material.id for item in other] == ["L02", "A03"]
    assert all(item.material.format == "course" for item in other)
    l02 = outcome.reasons[ids(outcome).index("L02")]
    assert l02 == ["Этот курс выбрали 48 из 120 слушателей курса «Старт продвижения за 7 дней» из вашей истории"]
    assert other[0].contributions == {"co_enrollment": 1.2}
    m02 = outcome.items[2]
    assert m02.contributions == {"history_topic": 0.1, "co_enrollment": 0.9}
    assert outcome.reasons[2] == [
        "Этот курс выбрали 36 из 120 слушателей курса «Старт продвижения за 7 дней» из вашей истории",
        "Тема из вашей истории: «Продвижение»",
    ]
    # Продолжение по редакционной связи пройденного курса остаётся сильнее «похожих курсов»
    assert outcome.items[0].contributions == {"continuation": 1.5, "history_topic": 0.1}


def test_p11_texts_name_the_history(run):
    outcome = run("P11")
    assert outcome.message == (
        "Нашли 8 материалов по теме «Продвижение», знакомой по вашей истории, и 2 курса других тем: их выбирали "
        "слушатели вашего курса. Показываем 5 с учётом истории."
    )
    assert outcome.total_candidates == 10
    clarification = outcome.clarification
    assert clarification["question"] == "Уточните тему"
    assert clarification["text"] == (
        "Задача не указана, поэтому подбор опирается на вашу историю. Выберите тему или опишите задачу."
    )
    values = [o["value"] for o in clarification["options"]]
    assert values[0] == "marketing" and set(values) == {"start", "taxes_law", "finance", "marketing", "sales",
                                                        "operations"}


def test_p11_show_more_keeps_the_completed_course_last(run):
    outcome = run("P11", limit=10)
    assert ids(outcome) == ["M03", "L02", "M02", "A03", "M01", "M07", "M05", "M04", "M06", "M08"]
    assert outcome.items[-1].flags == ["completed"]
    a03 = outcome.reasons[ids(outcome).index("A03")]
    assert a03 == ["Этот курс выбрали 12 из 120 слушателей курса «Старт продвижения за 7 дней» из вашей истории"]
    assert outcome.message.endswith("Показываем все с учётом истории.")


def cold_without_pairs(catalog: Catalog, profile: Profile):
    """Прежний ответ на тот же запрос: каталог без пар, то есть стартовая подборка без пилота."""
    return recommend(without_pairs(catalog), profile, "personal")


def test_p12_course_with_pairs_below_support_keeps_the_cold_start(run, catalog, profiles):
    """У O03 все пары ниже порога: «похожего курса» нет, подбор по истории не включается."""
    assert catalog.course_pairs.neighbours("O03") == {}
    for limit in (5, 10):
        outcome = run("P12", limit=limit)
        assert outcome.status == "cold" and ids(outcome) == ["A01", "L01", "S01", "M01", "O01"]
        assert pilot_contributions(outcome) == set() and co_phrases(outcome) == []
        assert outcome.message == explain.COLD_MESSAGE
        assert outcome.clarification["question"] == explain.COLD_QUESTION
        assert outcome == cold_without_pairs(catalog, make_profile(profiles["P12"], limit=limit))
        # Пройденный курс истории в стартовую подборку не попадает, как и раньше
        assert "O03" not in ids(outcome)


def test_p12_gets_similar_courses_once_the_threshold_is_lowered(profiles):
    """Тот же профиль при пороге 1: пары O03 загружены, и курсы других тем появляются с фразой."""
    loose = load_catalog(Settings(pairs_min_support=1))
    outcome = recommend(loose, make_profile(profiles["P12"], limit=10), "personal")
    assert {"S03", "M02", "L02", "A03"} <= set(ids(outcome)) and co_phrases(outcome)
    s03 = outcome.items[ids(outcome).index("S03")]
    assert s03.contributions["co_enrollment"] == pytest.approx(3.0 * 7 / 25)


@pytest.mark.parametrize("profile_id", ["P11", "P12"])
@pytest.mark.parametrize("limit", [5, 10])
def test_pilot_profiles_are_faithful_and_without_route(catalog, profiles, profile_id, limit):
    profile = make_profile(profiles[profile_id], limit=limit)
    outcome = recommend(catalog, profile, "personal")
    assert faithfulness_violations(outcome, profile, catalog) == []
    assert route_violations(catalog, profile, outcome) == [] and outcome.route == []
    for item, reasons in zip(outcome.items, outcome.reasons, strict=True):
        assert 1 <= len(reasons) <= explain.MAX_REASON_PHRASES
        assert sum(len(r) for r in reasons) + 2 * (len(reasons) - 1) <= explain.MAX_REASON_CHARS
        assert item.matched_topic is None and not any(r.startswith("Тема «") for r in reasons)


# ---------- когда пилот включается ----------


ALL_LINKED_SEEN = tuple(
    HistoryEvent(code, event, seq)
    for seq, (code, event) in enumerate(
        [("M08", "complete"), ("M02", "view"), ("L02", "view"), ("A03", "view"), ("S03", "view")], start=1
    )
)


@pytest.mark.parametrize(
    ("overrides", "status"),
    [
        ({}, "weak"),                                                  # пустая задача, курс в истории
        ({"task": "?!"}, "weak"),                                      # задача без слов — тоже пустая
        ({"history": (HistoryEvent("M01", "view", 1),)}, "cold"),      # в истории нет курса
        ({"history": (HistoryEvent("ZZ9", "complete", 1),)}, "cold"),  # курса нет в каталоге
        ({"history": ()}, "cold"),
        ({"history": O03_DONE}, "cold"),                               # все пары курса истории ниже порога
        ({"history": ALL_LINKED_SEEN}, "cold"),                        # все связанные курсы уже в истории
        ({"history": (*O03_DONE, HistoryEvent("M08", "view", 2))}, "weak"),  # пара есть у второго курса
    ],
)
def test_history_mode_trigger(run, catalog, overrides, status):
    outcome = run("P11", **overrides)
    assert outcome.status == status
    assert bool(pilot_contributions(outcome)) == (status == "weak")
    assert bool(co_phrases(outcome)) == (status == "weak")
    if status == "cold":
        # Прежняя стартовая подборка без изменений: тот же ответ, что без файла пар
        assert outcome == run("P11", catalog_override=without_pairs(catalog), **overrides)


@pytest.mark.parametrize(
    ("history", "min_support", "status"),
    [
        ((HistoryEvent("C1", "complete", 1),), 10, "weak"),           # недоступный курс истории связал C2
        ((HistoryEvent("C3", "view", 1),), 10, "cold"),               # пара C1–C3 ниже порога
        ((HistoryEvent("C2", "complete", 1),), 10, "cold"),           # единственный сосед C1 недоступен
        ((HistoryEvent("C1", "view", 1), HistoryEvent("C2", "view", 2)), 10, "cold"),      # C2 уже в истории
        ((HistoryEvent("C1", "view", 1), HistoryEvent("C2", "purchase", 2)), 10, "cold"),  # C2 куплен
        ((HistoryEvent("C5", "start", 1),), 1, "cold"),               # у C5 меньше 10 слушателей
    ],
)
def test_history_mode_needs_a_linked_eligible_course(history, min_support, status):
    """Подбор по истории — только если пилот может показать курс с вкладом «похожих курсов»."""
    catalog = pilot_catalog(min_support)
    profile = Profile(history=history, limit=10)
    outcome = recommend(catalog, profile, "personal")
    assert outcome.status == status
    assert bool(co_phrases(outcome)) == (status == "weak")
    if status == "cold":
        assert outcome == cold_without_pairs(catalog, profile)


def test_everything_completed_keeps_the_cold_start(catalog, profiles):
    """Как в браузерной проверке E5: всё пройдено — нового по истории нет, остаётся выбор темы без карточек."""
    history = tuple(HistoryEvent(m, "complete", n) for n, m in enumerate(sorted(catalog.materials), start=1))
    outcome = recommend(catalog, Profile(history=history), "personal")
    assert outcome.status == "cold" and outcome.items == []
    assert outcome.clarification is not None and outcome.clarification["options"]
    assert outcome == recommend(without_pairs(catalog), Profile(history=history), "personal")
    # Если хотя бы один кандидат не пройден, подбор по истории работает
    partial = tuple(e for e in history if e.material_id != "L02")
    outcome = recommend(catalog, Profile(history=partial, limit=10), "personal")
    assert outcome.status == "weak" and ids(outcome)[0] == "L02"
    chosen = recommend(catalog, Profile(topic="marketing", history=history), "personal")
    assert chosen.status == "strong" and chosen.items


@pytest.mark.parametrize(("profile_id", "history"), [("P11", M08_DONE), ("P12", O03_DONE)])
def test_baseline_never_uses_history(run, profile_id, history):
    outcome = run(profile_id, "baseline")
    assert outcome.status == "cold" and ids(outcome) == ["A01", "L01", "S01", "M01", "O01"]
    assert outcome == run("P03", "baseline", history=history)


def test_task_with_text_ignores_the_pilot(run):
    """Задача с текстом при той же истории: обычный подбор по теме без вкладов пилота."""
    outcome = run("P11", task="Как продвигать бизнес", limit=10)
    assert outcome.status == "strong" and outcome.detected_topics == ("marketing",)
    assert pilot_contributions(outcome) == set() and co_phrases(outcome) == []
    assert "L02" not in ids(outcome)


def test_explicit_topic_keeps_candidates_in_the_topic_and_adds_co_enrollment(run):
    outcome = run("P11", topic="start", limit=10)
    assert outcome.status == "strong" and outcome.detected_topics == ("start",)
    assert all("start" in item.material.topics for item in outcome.items)
    assert ids(outcome)[0] == "L02"
    assert outcome.items[0].contributions == {"topic": 3.0, "co_enrollment": 1.2}
    assert "history_topic" not in pilot_contributions(outcome)
    assert co_phrases(outcome) == [
        "Этот курс выбрали 48 из 120 слушателей курса «Старт продвижения за 7 дней» из вашей истории"
    ]
    # Без курса в истории та же тема даёт прежний порядок
    plain = run("P03", topic="start", limit=10)
    assert pilot_contributions(plain) == set() and ids(plain)[0] != "L02"


def test_explicit_topic_with_task_text_ignores_the_pilot(run):
    outcome = run("P11", task="Хочу составить бизнес-план", topic="start", limit=10)
    assert pilot_contributions(outcome) == set()


def test_without_pairs_the_pilot_keeps_the_old_cold_start(catalog, profiles):
    bare = without_pairs(catalog)
    for profile_id in ("P11", "P12"):
        for limit in (5, 10):
            profile = make_profile(profiles[profile_id], limit=limit)
            outcome = recommend(bare, profile, "personal")
            history = HistoryIndex.build(profile.history)
            expected = policy._starter_outcome(
                method="personal", status="cold", message=explain.COLD_MESSAGE, detected=(),
                pool=eligible(bare, history), history=history, limit=limit, by_level=policy.levels_beyond_courses(bare),
            )
            assert outcome == expected
    explicit = recommend(bare, make_profile(profiles["P11"], topic="start", limit=10), "personal")
    assert pilot_contributions(explicit) == set()


@pytest.mark.parametrize("profile_id", P01_P10)
@pytest.mark.parametrize("limit", [5, 10])
@pytest.mark.parametrize("method", ["personal", "baseline"])
def test_p01_p10_do_not_depend_on_pairs(catalog, profiles, profile_id, limit, method):
    """Охрана области: пары не меняют ни порядок, ни оценки, ни тексты P01–P10."""
    profile = make_profile(profiles[profile_id], limit=limit)
    assert recommend(catalog, profile, method) == recommend(without_pairs(catalog), profile, method)


def test_baseline_does_not_depend_on_pairs_on_a_grid(catalog):
    rng = random.Random(20261111)
    histories = ((), M08_DONE, (HistoryEvent("O03", "start", 1),), (HistoryEvent("M02", "view", 1),))
    bare = without_pairs(catalog)
    for _ in range(120):
        profile = Profile(
            task=rng.choice(("", "Как продвигать бизнес", "Какую CRM выбрать")),
            topic=rng.choice((None, "start", "marketing")),
            history=rng.choice(histories),
            limit=rng.choice((5, 10)),
        )
        assert recommend(catalog, profile, "baseline") == recommend(bare, profile, "baseline")


# ---------- кандидаты, недоступные курсы, фраза ----------


def pilot_catalog(min_support: int = 10) -> Catalog:
    rows = [
        {"id": "C1", "title": "Курс «Реклама с нуля»", "format": "course", "topics": ["marketing"],
         "popularity": 90, "available": False},
        {"id": "C2", "title": "Курс «Первые продажи»", "format": "course", "topics": ["sales"], "popularity": 10},
        {"id": "C3", "title": "Курс «Учёт для ИП»", "format": "course", "topics": ["finance"], "popularity": 80},
        {"id": "C4", "title": "Курс «Команда»", "format": "course", "topics": ["operations"], "popularity": 70},
        {"id": "C5", "title": "Курс «Маленький поток»", "format": "course", "topics": ["start"], "popularity": 60},
        {"id": "A1", "title": "Статья о рекламе", "format": "article", "topics": ["marketing"], "popularity": 20},
        {"id": "A2", "title": "Статья о продажах", "format": "article", "topics": ["sales"], "popularity": 30},
    ]
    catalog = catalog_from_payloads({"materials": rows})
    return with_pairs(catalog, [
        pair("C1", "C2", 30, 100, 60),   # от порога: курс другой темы среди кандидатов
        pair("C1", "C3", 5, 100, 80),    # ниже порога: курса нет
        pair("C5", "C4", 9, 9, 40),      # у C5 меньше 10 слушателей
    ], min_support)


def test_unavailable_history_course_passes_its_weight_but_is_never_shown():
    catalog = pilot_catalog()
    outcome = recommend(catalog, Profile(history=(HistoryEvent("C1", "complete", 1),), limit=10), "personal")
    assert outcome.status == "weak"
    assert "C1" not in ids(outcome) and "C3" not in ids(outcome) and "A2" not in ids(outcome)
    # При весе темы истории 0,1 курс с парой выше материала темы истории
    assert ids(outcome) == ["C2", "A1"]
    c2 = outcome.items[0]
    assert c2.contributions == {"co_enrollment": 0.9}
    assert outcome.reasons[0] == ["Этот курс выбрали 30 из 100 слушателей курса «Реклама с нуля» из вашей истории"]
    assert outcome.reasons[1] == ["Тема из вашей истории: «Продвижение»"]
    assert outcome.message.startswith(
        "Нашли 1 материал по теме «Продвижение», знакомой по вашей истории, и 1 курс другой темы: его выбирали "
        "слушатели вашего курса."
    )


def test_anchor_with_fewer_than_ten_listeners_gives_no_contribution():
    """При пороге 1 пара C5–C4 загружена, но у C5 девять слушателей: фразы «N из M» нет, вклада тоже.
    Показать «похожий курс» нечем, поэтому подбор по истории не включается."""
    rows = [pair("C5", "C4", 9, 9, 40)]
    catalog = with_pairs(pilot_catalog(), rows, min_support=1)
    assert catalog.course_pairs is not None and catalog.course_pairs.neighbours("C5") == {"C4": 9}
    profile = Profile(history=(HistoryEvent("C5", "start", 1),), limit=10)
    outcome = recommend(catalog, profile, "personal")
    assert outcome.status == "cold" and co_phrases(outcome) == [] and pilot_contributions(outcome) == set()
    assert outcome == cold_without_pairs(catalog, profile)
    # С выбранной темой C4 — курс темы, но вклада «похожих курсов» у него нет
    chosen = recommend(catalog, dataclasses.replace(profile, topic="operations"), "personal")
    assert ids(chosen) == ["C4"] and pilot_contributions(chosen) == set()


def test_only_linked_courses_of_other_topics_become_candidates():
    """Курс другой темы без пары от порога в кандидаты не попадает: у него не было бы причины."""
    catalog = pilot_catalog()
    outcome = recommend(catalog, Profile(history=(HistoryEvent("C1", "view", 1),), limit=10), "personal")
    assert set(ids(outcome)) == {"A1", "C2"}
    assert all(reasons for reasons in outcome.reasons)


def test_shares_of_several_history_courses_add_up_to_one():
    rows = [
        {"id": "K1", "title": "Курс «Один»", "format": "course", "topics": ["sales"], "popularity": 1},
        {"id": "K2", "title": "Курс «Два»", "format": "course", "topics": ["finance"], "popularity": 1},
        {"id": "K3", "title": "Курс «Три»", "format": "course", "topics": ["team"], "popularity": 1},
    ]
    catalog = with_pairs(catalog_from_payloads({"materials": rows}), [
        pair("K1", "K3", 30, 50, 90),   # доля 0,6
        pair("K2", "K3", 35, 50, 90),   # доля 0,7
    ])
    history = (HistoryEvent("K1", "complete", 1), HistoryEvent("K2", "complete", 2))
    outcome = recommend(catalog, Profile(history=history), "personal")
    k3 = outcome.items[ids(outcome).index("K3")]
    assert k3.contributions["co_enrollment"] == personal.WEIGHTS["co_enrollment"]  # 0,6 + 0,7 → не больше 1
    assert k3.co_enrollment is not None and k3.co_enrollment.anchor == "K2"  # во фразе курс с наибольшей долей
    reason = outcome.reasons[ids(outcome).index("K3")]
    assert reason == ["Этот курс выбрали 35 из 50 слушателей курса «Два» из вашей истории"]


def k_catalog(rows: list[dict], min_support: int = 10) -> Catalog:
    """Три курса трёх тем: K1 «Продажи», K2 «Финансы и учёт», K3 «Команда» — и пары между ними."""
    materials = [
        {"id": "K1", "title": "Курс «Один»", "format": "course", "topics": ["sales"], "popularity": 1},
        {"id": "K2", "title": "Курс «Два»", "format": "course", "topics": ["finance"], "popularity": 1},
        {"id": "K3", "title": "Курс «Три»", "format": "course", "topics": ["team"], "popularity": 1},
    ]
    return with_pairs(catalog_from_payloads({"materials": materials}), rows, min_support)


@pytest.mark.parametrize(
    ("history", "rows", "tail"),
    [
        # Один курс истории связал один курс другой темы
        ((HistoryEvent("K1", "complete", 1),), [pair("K1", "K3", 30, 50, 90)],
         ", знакомой по вашей истории, и 1 курс другой темы: его выбирали слушатели вашего курса."),
        # Два курса истории связали один курс
        ((HistoryEvent("K1", "complete", 1), HistoryEvent("K2", "complete", 2)),
         [pair("K1", "K3", 30, 50, 90), pair("K2", "K3", 35, 50, 90)],
         ", знакомым по вашей истории, и 1 курс другой темы: его выбирали слушатели ваших курсов."),
        # Один курс истории связал два курса
        ((HistoryEvent("K1", "complete", 1),), [pair("K1", "K3", 30, 50, 90), pair("K1", "K2", 20, 50, 60)],
         ", знакомой по вашей истории, и 2 курса других тем: их выбирали слушатели вашего курса."),
    ],
)
def test_history_message_agrees_with_the_numbers_of_courses(history, rows, tail):
    outcome = recommend(k_catalog(rows), Profile(history=history), "personal")
    assert outcome.status == "weak"
    head = outcome.message.split(". ")[0] + "."
    assert head.endswith(tail), outcome.message


def test_history_message_with_only_linked_courses():
    """Курс истории куплен и в кандидаты не входит, материалов его темы больше нет: остаются связанные курсы."""
    catalog = k_catalog([pair("K1", "K3", 30, 50, 90)])
    outcome = recommend(catalog, Profile(history=(HistoryEvent("K1", "purchase", 1),)), "personal")
    assert ids(outcome) == ["K3"]
    assert outcome.message.startswith("Нашли 1 курс: его выбирали слушатели вашего курса.")


def test_share_without_a_visible_contribution_gives_no_candidate():
    """Доля 1 из 1 000 000 даёт вклад 0,000003, после округления оценки — ноль: ни кандидата, ни фразы,
    и подбор по истории не включается. Доля 100 из 1 000 000 даёт вклад 0,0003 и включает его."""
    history = (HistoryEvent("K1", "start", 1),)
    tiny = k_catalog([pair("K1", "K3", 1, 1_000_000, 10)], min_support=1)
    outcome = recommend(tiny, Profile(history=history, limit=10), "personal")
    assert outcome.status == "cold" and co_phrases(outcome) == [] and pilot_contributions(outcome) == set()
    assert outcome == cold_without_pairs(tiny, Profile(history=history, limit=10))
    small = k_catalog([pair("K1", "K3", 100, 1_000_000, 100)], min_support=1)
    outcome = recommend(small, Profile(history=history, limit=10), "personal")
    assert ids(outcome) == ["K1", "K3"]
    assert outcome.items[1].contributions == {"co_enrollment": 0.0003} and len(co_phrases(outcome)) == 1


# ---------- фраза курса другой темы не вытесняется ----------


def test_fit_keeps_the_protected_phrase_in_its_place():
    stage, level = ("stage", "С" * 40), ("level", "У" * 40)
    industry, co = ("industry", "Ф" * 20), ("co_enrollment", "К" * 60)
    # Четвёртая по вкладу фраза остаётся вместо третьей, порядок по вкладу сохраняется
    assert explain._fit([stage, level, industry, co], "co_enrollment") == ["С" * 40, "У" * 40, "К" * 60]
    assert explain._fit([stage, level, industry, co]) == ["С" * 40, "У" * 40, "Ф" * 20]
    # При нехватке символов первой уходит слабейшая другая фраза, сильнейшая — последней
    long_stage, long_co = ("stage", "С" * 110), ("co_enrollment", "К" * 100)
    assert explain._fit([("stage", "С" * 70), ("level", "У" * 30), long_co], "co_enrollment") == ["С" * 70, "К" * 100]
    assert explain._fit([long_stage, ("level", "У" * 30), long_co], "co_enrollment") == ["К" * 100]
    assert explain._fit([long_stage, long_co]) == ["С" * 110]
    # Без признака в списке и без нехватки места — прежнее правило
    assert explain._fit([stage, level], "co_enrollment") == explain._fit([stage, level]) == ["С" * 40, "У" * 40]


def test_filled_questionnaire_keeps_the_phrase_of_a_linked_course(catalog):
    """Пример ревью: стадия и уровень дают две фразы сильнее, но курс L02 другой темы объясняет пара с M02."""
    profile = Profile(stage="idea", experience="some", format_pref="quick", industry="horeca",
                      history=(HistoryEvent("M02", "complete", 1),), limit=10)
    outcome = recommend(catalog, profile, "personal")
    l02 = outcome.items[ids(outcome).index("L02")]
    assert l02.contributions == {"stage": 2.0, "level": 1.0, "co_enrollment": 0.3333}
    reasons = outcome.reasons[ids(outcome).index("L02")]
    assert reasons[0] == "Подходит для стадии «только планирую»" and features_of(reasons[-1]) == {"co_enrollment"}
    assert sum(len(r) for r in reasons) + 2 * (len(reasons) - 1) <= explain.MAX_REASON_CHARS
    assert faithfulness_violations(outcome, profile, catalog) == []


def test_every_shown_course_of_another_topic_names_its_pair(catalog):
    """Свойство на выборке пустых задач с анкетой и без: курс без темы истории показан только с фразой о паре."""
    rng = random.Random(7)
    codes = sorted(catalog.materials)
    linked = tight = 0
    missing: list[str] = []
    for _ in range(1500):
        filled = rng.random() < 0.6
        history = tuple(
            HistoryEvent(rng.choice(codes), rng.choice(vocab.EVENTS), seq) for seq in range(1, rng.choice((2, 3, 4, 5)))
        )
        profile = Profile(
            stage=rng.choice(tuple(vocab.STAGES)) if filled else None,
            experience=rng.choice(tuple(vocab.EXPERIENCE)) if filled else None,
            format_pref=rng.choice((None, *vocab.FORMAT_PREFS)) if filled else None,
            industry=rng.choice((None, "horeca", "retail")) if filled else None,
            history=history, limit=rng.choice((5, 10)),
        )
        outcome = recommend(catalog, profile, "personal")
        if outcome.status != "weak":
            continue
        topics = set(HistorySignals.build(history, catalog.materials).topics)
        for item, reasons in zip(outcome.items, outcome.reasons, strict=True):
            if topics & set(item.material.topics):
                continue
            linked += 1
            positive = [f for f in item.contributions if item.contributions[f] > 0 and f not in {"format", "effort"}]
            tight += len(positive) >= 3
            if not any(CO_MARKER in r for r in reasons):
                missing.append(f"{profile}: {item.material.id} {reasons}")
    assert missing == []
    # Выборка доходит до курсов, у которых фраза о паре — одна из трёх и больше фраз
    assert linked > 500 and tight > 50


def test_equal_shares_name_the_latest_history_course():
    rows = [
        {"id": "K1", "title": "Курс «Один»", "format": "course", "topics": ["sales"], "popularity": 1},
        {"id": "K2", "title": "Курс «Два»", "format": "course", "topics": ["finance"], "popularity": 1},
        {"id": "K3", "title": "Курс «Три»", "format": "course", "topics": ["team"], "popularity": 1},
    ]
    catalog = with_pairs(catalog_from_payloads({"materials": rows}), [
        pair("K1", "K3", 20, 40, 90), pair("K2", "K3", 20, 40, 90),
    ])
    history = (HistoryEvent("K2", "complete", 1), HistoryEvent("K1", "start", 5))
    outcome = recommend(catalog, Profile(history=history), "personal")
    k3 = outcome.items[ids(outcome).index("K3")]
    assert k3.co_enrollment is not None and k3.co_enrollment.anchor == "K1"


@pytest.mark.parametrize(
    ("together", "total", "expected"),
    [
        (21, 121, "Этот курс выбрал 21 из 121 слушателя курса «Старт продвижения за 7 дней» из вашей истории"),
        (12, 120, "Этот курс выбрали 12 из 120 слушателей курса «Старт продвижения за 7 дней» из вашей истории"),
        (11, 111, "Этот курс выбрали 11 из 111 слушателей курса «Старт продвижения за 7 дней» из вашей истории"),
        (10, 10, "Этот курс выбрали 10 из 10 слушателей курса «Старт продвижения за 7 дней» из вашей истории"),
    ],
)
def test_co_enrollment_phrase_agrees_with_numbers(catalog, together, total, expected):
    ctx = Context(profile=Profile(), parsed=parse_task(""), topics=(), history=HistoryIndex.build(()),
                  disabled=frozenset(), catalog=catalog.materials)
    phrase = explain.co_enrollment_phrase(together, total, "M08", ctx)
    assert phrase == expected and phrase is not None and features_of(phrase) == {"co_enrollment"}


@pytest.mark.parametrize(
    ("title", "name"),
    [
        ("Курс «Старт продвижения за 7 дней»", "Старт продвижения за 7 дней"),
        ("Курс «Учёт «под ключ»»", "Учёт „под ключ“"),
        ("Курс «A» и «B»", "Курс „A“ и „B“"),
        ("Вебинар о курсах", "Вебинар о курсах"),
        ("Курс «»", "Курс „“"),
    ],
)
def test_course_name_drops_the_generic_word_only_for_a_whole_quoted_title(title, name):
    assert explain.course_name(title) == name


# ---------- свойства на выборке пилота ----------


def pilot_grid(seed: int = 20261112, size: int = 300) -> list[Profile]:
    rng = random.Random(seed)
    courses = ("M02", "M08", "L02", "A03", "S03", "O03")
    others = ("M01", "M03", "A02", "S01", "O01", "L01")
    profiles = []
    for _ in range(size):
        events = [HistoryEvent(rng.choice(courses), rng.choice(vocab.EVENTS), 1)]
        for seq in range(2, rng.choice((2, 3, 4))):
            events.append(HistoryEvent(rng.choice(courses + others), rng.choice(vocab.EVENTS), seq))
        profiles.append(Profile(
            task=rng.choice(("", "", "", "Как продвигать бизнес")),
            stage=rng.choice((None, None, *vocab.STAGES)),
            experience=rng.choice((None, None, *vocab.EXPERIENCE)),
            format_pref=rng.choice((None, None, *vocab.FORMAT_PREFS)),
            industry=rng.choice((None, "horeca")),
            topic=rng.choice((None, None, None, "start", "marketing", "sales")),
            history=tuple(events),
            limit=rng.choice((3, 5, 10)),
        ))
    return profiles


def test_pilot_grid_is_faithful_and_never_shows_unavailable_or_purchased(catalog):
    reached: set[str] = set()
    statuses: set[str] = set()
    violations: list[str] = []
    for profile in pilot_grid():
        outcome = recommend(catalog, profile, "personal")
        statuses.add(outcome.status)
        violations.extend(f"{profile}: {v}" for v in faithfulness_violations(outcome, profile, catalog))
        violations.extend(f"{profile}: {v}" for v in route_violations(catalog, profile, outcome))
        pool = {m.id for m in eligible(catalog, HistoryIndex.build(profile.history))}
        violations.extend(
            f"{profile}: вне допустимых {i.material.id}" for i in outcome.items if i.material.id not in pool
        )
        if len({i.material.id for i in outcome.items}) != len(outcome.items):
            violations.append(f"{profile}: повтор материала")
        reached.update(f for reasons in outcome.reasons for r in reasons for f in features_of(r))
    assert violations == []
    assert {"co_enrollment", "history_topic", "continuation", "in_progress"} <= reached
    assert {"weak", "strong"} <= statuses


def test_api_p11_by_profile_and_compare():
    with client_for() as service:
        body = service.post("/api/recommend", json={"task": "", "profile_id": "P11"}).json()
        compare = service.post("/api/compare", json={"task": "", "profile_id": "P11"}).json()
    assert body["status"] == "weak" and body["route"] is None and body["detected_topics"] == []
    assert [i["material_id"] for i in body["items"]] == ["M03", "L02", "M02", "A03", "M01"]
    l02 = body["items"][1]
    assert l02["contributions"] == {"co_enrollment": 1.2} and l02["topics"] == ["start"]
    assert body["clarification"]["question"] == "Уточните тему" and body["clarification"]["field"] == "topic"
    assert compare["baseline"]["status"] == "cold" and compare["personal"]["status"] == "weak"
    assert compare["personal"]["items"] == body["items"]
