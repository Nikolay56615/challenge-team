from dataclasses import replace

from app.catalog.course_details import CourseDetails
from app.catalog.models import Catalog, HistoryEvent, Material
from app.catalog.task_search import TaskIndex
from app.catalog.text_search import TextIndex
from app.ranking.base import MaterialFilters, Profile
from app.ranking.policy import recommend

from .conftest import ids


def indexed(*materials: Material) -> Catalog:
    return Catalog(
        materials={material.id: material for material in materials},
        source="sqlite",
        version="test",
        text_index=TextIndex(materials),
    )


def test_normalizes_word_forms_and_hyphens_and_requires_all_keywords():
    catalog = indexed(
        Material("exact", "Юнит-экономика маркетплейсов", "article"),
        Material("partial", "Юнит-экономика для кофейни", "article"),
        Material("schedule", "Штатное расписание", "document"),
        Material("unavailable", "Штатное расписание предприятия", "document", available=False),
        Material("fold", "Учёт расходов", "article"),
    )
    assert catalog.text_index is not None
    assert catalog.text_index.match("Как посчитать юнит экономику маркетплейса").titles == {"exact"}
    assert catalog.text_index.match("Как составить штатного расписания").titles == {"schedule"}
    assert catalog.text_index.match("Учет расхода").titles == {"fold"}
    assert catalog.text_index.match("Штатное штатного").titles == set()


def test_uses_whole_abbreviations_and_prioritizes_matching_qualifier():
    catalog = indexed(
        Material("high", "Как выбрать ОКВЭД", "article", topics=("start",), popularity=1),
        Material("ip", "ОКВЭД для ИП", "article"),
        Material("substring", "Справочник ОКВЭДЫ", "article", popularity=1),
    )
    profile = Profile(task="Как выбрать ОКВЭД для ИП")
    result = recommend(catalog, profile)
    assert result.status == "strong" and result.detected_topics == ()
    assert ids(result) == ["ip", "high"]
    assert all("в названии" in reasons[0] for reasons in result.reasons)
    assert recommend(catalog, profile, "baseline").status == "none"
    assert recommend(catalog, Profile(task="Нужна виза")).status == "none"


def test_title_then_description_then_topic_with_scope_and_filters():
    catalog = indexed(
        Material("general", "Ведение учёта", "article", topics=("taxes_law",), popularity=1),
        Material("description", "Отчётность предпринимателя", "course", topics=("taxes_law",), popularity=1,
                 course_details=CourseDetails("Как подготовить декларацию УСН", (), ())),
        Material("title", "Декларация по УСН", "document", topics=("taxes_law",)),
        Material("bought", "Декларация УСН для бизнеса", "document", topics=("taxes_law",), access="paid"),
        Material("another-topic", "Заполняем декларацию по УСН", "document", topics=("finance",)),
    )
    profile = Profile(task="Как заполнить декларацию по УСН",
                      history=(HistoryEvent("bought", "purchase", 1),))
    result = recommend(catalog, profile)
    assert ids(result) == ["title", "description", "general"]
    assert result.total_candidates == 3
    assert "в названии" in result.reasons[0][0]
    assert "в кратком описании курса" in result.reasons[1][0]
    assert "Ключевые слова" not in " ".join(result.reasons[2])
    assert ids(recommend(catalog, profile, "baseline"))[0] != "title"
    assert ids(recommend(catalog, replace(profile, topic="finance"))) == ["another-topic"]
    assert ids(recommend(catalog, replace(profile, filters=MaterialFilters(format="course")))) == ["description"]
    filtered = recommend(catalog, replace(profile, filters=MaterialFilters(access="paid")))
    assert filtered.items == [] and filtered.total_candidates == 0


def test_description_alone_does_not_open_global_search():
    catalog = indexed(
        Material("course", "Работа с сотрудниками", "course", topics=("team",),
                 course_details=CourseDetails("Штатное расписание", (), ())),
    )
    assert recommend(catalog, Profile(task="Как составить штатное расписание")).status == "none"


def test_task_intent_uses_title_synonyms_and_one_field_at_a_time():
    catalog = indexed(
        Material("ordinary", "Как наладить работу команды", "article", topics=("team",), popularity=1),
        Material("intent", "Приём работника на работу", "article", topics=("team",)),
        Material("leave", "Оформление отпуска сотрудника", "article", topics=("team",), popularity=0.9),
        Material("split", "Кадровая работа", "course", topics=("team",), popularity=0.8,
                 course_details=CourseDetails(None, ("Сотрудники",), ("Как оформить",))),
        Material("description", "Первые шаги руководителя", "article", topics=("team",)),
    )
    catalog.task_index = TaskIndex(catalog.materials.values(), {"description": "Наём персонала"})
    profile = Profile(task="Как оформить сотрудника", topic="team")
    result = recommend(catalog, profile)
    assert ids(result)[:2] == ["intent", "description"]
    assert "Действие и объект задачи указаны в названии" in result.reasons[0]
    assert "Действие и объект задачи указаны в описании статьи" in result.reasons[1]
    assert "материалы, связанные с задачей" in result.message
    assert ids(recommend(catalog, profile, "baseline"))[0] == "ordinary"
    assert catalog.task_index.match("Как оформить отпуск сотрудника", ["intent"]) == {}
    assert catalog.task_index.match("Нужно оформить", ["intent", "description"]) == {}


def test_task_ranking_preserves_exact_results_scope_and_filters():
    catalog = indexed(
        Material("general", "Отчётность бизнеса", "article", topics=("taxes_law",), popularity=1),
        Material("exact", "Декларация УСН для бухгалтерской отчётности", "document", topics=("taxes_law",)),
        Material("description", "Календарь предпринимателя", "article", topics=("taxes_law",)),
        Material("substring", "Декларация и отчётность УСНка", "article", topics=("taxes_law",), popularity=0.9),
        Material("hidden", "Отчётность, декларация УСН", "article", topics=("taxes_law",), available=False),
        Material("bought", "Годовая декларация УСН", "article", topics=("taxes_law",), access="paid"),
        Material("outside", "Декларация УСН и бухгалтерская отчётность для бизнеса", "document", topics=("finance",)),
    )
    catalog.task_index = TaskIndex(catalog.materials.values(), {"description": "Годовая декларация УСН и отчётность"})
    profile = Profile(task="Бухгалтерская отчётность и декларация УСН", topic="taxes_law",
                      history=(HistoryEvent("bought", "purchase", 1),))
    result = recommend(catalog, profile)
    assert ids(result)[:2] == ["exact", "description"]
    assert "Ключевые слова запроса совпали в описании статьи" in result.reasons[1]
    assert result.total_candidates == 4
    assert ids(recommend(catalog, replace(profile, limit=3))) == ids(result)[:3]
    assert ids(recommend(catalog, replace(profile, topic="finance"))) == ["outside"]
    filtered = recommend(catalog, replace(profile, filters=MaterialFilters(format="article", access="open")))
    assert ids(filtered) == ["description", "general", "substring"]
    assert recommend(catalog, Profile(task="Нужна виза")).status == "none"


def test_paragraph_evidence_is_local_to_one_passage():
    materials = [
        Material("direct", "Советы руководителю", "article"),
        Material("split", "Годовой обзор", "article"),
        Material("closed", "Годовой курс", "article", access="paid"),
    ]
    index = TaskIndex(materials, passages={
        "direct": ("Расскажем, как нанять работника",),
        "split": ("Команда сотрудников", "Что нужно оформить"),
        "closed": ("Как нанять сотрудника",),
    })
    matched = index.match("Оформить сотрудника", ["direct", "split", "closed"])
    assert set(matched) == {"direct"}
    assert matched["direct"].field == "в тексте статьи"
