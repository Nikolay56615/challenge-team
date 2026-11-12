from dataclasses import replace

from app.catalog.course_details import CourseDetails
from app.catalog.models import Catalog, HistoryEvent, Material
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
