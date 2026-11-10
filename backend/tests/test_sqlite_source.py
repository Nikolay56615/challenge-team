"""Источник каталога из SQLite (PLAN.md, 2.2–2.4, 2.8) на вымышленных мини-базах.

Базы строятся во временной папке только с нужными таблицами. Идентификаторы и названия
вымышленные; подписи тем, тегов и отраслей — общие справочные значения из PLAN.md.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app.catalog.loader import load_catalog
from app.catalog.mapping import load_mapping
from app.catalog.models import CatalogError
from app.catalog.sqlite_source import _Database, load_sqlite_catalog
from app.config import DATA_DIR, Settings

Table = tuple[list[str], list[tuple]]

SIGNAL_COLUMNS = ["MaterialId", "MaterialFormat", "SignalCode", "SignalLabel", "MatchedTitle", "MatchedDescription"]
SIGNAL_ROWS = [
    ("A-101", "article", "tax_reporting", "Налоги и отчётность", 0, 1),
    ("A-101", "article", "tax_regime", "Выбор налогового режима", 1, 1),
    ("D-301", "document", "contracts", "Договоры и работа с контрагентами", 0, 1),
    ("A-101", "course", "launch", "Первые шаги при запуске бизнеса", 1, 0),  # формат не совпал
    ("Z-000", "article", "launch", "Первые шаги при запуске бизнеса", 1, 0),  # материала нет
    ("C-201", "course", "no_such_code", "Неизвестный признак", 1, 0),
]


def base_tables() -> dict[str, Table]:
    """Мини-каталог: 14 материалов пяти типов. Коды EntityTypeId и ItemTypeId нарочно одинаковые."""
    return {
        "Statuses": (["Id", "Title"], [("st-pub", "Опубликовано"), ("st-draft", "Черновик")]),
        "CourseTypes": (
            ["Id", "Title"],
            [("ty-open", "Открытый"), ("ty-sub", "По подписке"), ("ty-paid", "Платный"), ("ty-closed", "Закрытый")],
        ),
        "Articles": (
            ["Id", "StatusId", "Duration", "SubjectId", "Title", "IsDeleted", "IsPublic", "IsClosed", "TypeId"],
            [
                ("A-101", "st-pub", "7 минут", "sb-ip", "Вымышленная статья 1", 0, 1, 0, "ty-paid"),
                ("A-102", "st-pub", "1 час 30 минут", "sb-mp", "Вымышленная статья 2", 0, 0, 0, "ty-open"),
                ("A-103", "st-draft", "3 минуты", "sb-acq", "Вымышленная статья 3", 0, 1, 0, "ty-open"),
                ("A-104", "st-pub", "скоро", "sb-tax", "Вымышленная статья 4", 0, 1, 1, "ty-open"),
                ("A-105", "st-pub", None, "sb-mp", "Вымышленная статья 5", 0, 1, 0, "ty-open"),
                ("A-106", "st-pub", "12 минут", "sb-tax", "Вымышленная статья 6", 1, 1, 0, "ty-open"),
            ],
        ),
        "Courses": (
            ["Id", "StatusId", "Duration", "Title", "IsDeleted", "IsClosed", "TypeId"],
            [
                ("C-201", "st-pub", "1,5 часа", "Вымышленный курс 1", 0, 0, "ty-sub"),
                ("C-202", "st-pub", "2 часа", "Вымышленный курс 2", 0, 1, "ty-paid"),
                ("C-203", "st-pub", "45 минут", "Вымышленный курс 3", 0, 0, "ty-open"),
            ],
        ),
        "Documents": (
            ["Id", "StatusId", "Title", "IsDeleted"],
            [("D-301", "st-pub", "Вымышленный документ 1", 0), ("D-302", "st-pub", "Вымышленный документ 2", 0)],
        ),
        "Webinars": (
            ["Id", "StatusId", "Title", "IsDeleted", "IsClosed", "Duration"],
            [
                ("W-401", "st-pub", "Вымышленный вебинар 1", 0, 0, "1 час"),
                ("W-402", "st-draft", "Вымышленный вебинар 2", 0, 0, "1 час 15 минут"),
            ],
        ),
        "Podcasts": (
            ["Id", "StatusId", "Title", "IsDeleted", "IsClosed", "Duration"],
            [("P-501", "st-pub", "Вымышленный подкаст 1", 0, 0, "25 минут")],
        ),
        "ContentSettings": (
            ["Id", "EntityId", "EntityTypeId", "StatusId", "IsDeleted", "TypeId"],
            [
                ("cs-101", "A-101", "9", "st-pub", 0, "ty-open"),
                ("cs-102", "A-102", "9", "st-pub", 0, "ty-open"),
                ("cs-103", "A-103", "9", "st-draft", 0, "ty-open"),
                ("cs-104", "A-104", "9", "st-pub", 0, "ty-open"),
                ("cs-105", "A-105", "9", "st-pub", 0, "ty-closed"),
                ("cs-106", "A-106", "9", "st-pub", 0, "ty-open"),
                ("cs-201", "C-201", "9", "st-pub", 0, "ty-sub"),
                ("cs-202", "C-202", "9", "st-pub", 0, "ty-open"),
                ("cs-203", "C-203", "9", "st-pub", 0, "ty-paid"),
                ("cs-301", "D-301", "9", "st-pub", 0, "ty-open"),
                ("cs-302", "D-302", "9", "st-pub", 1, "ty-open"),
                ("cs-401", "W-401", "9", "st-pub", 0, "ty-open"),
                ("cs-402", "W-402", "9", "st-draft", 0, "ty-open"),
                ("cs-501", "P-501", "9", "st-pub", 0, "ty-sub"),
                ("cs-999", "L-999", "9", "st-pub", 0, "ty-open"),  # сущность вне каталога
            ],
        ),
        "Topics": (
            ["Id", "Title"],
            [
                ("tp-tax", "Налоги и законы"),
                ("tp-law", "Законы"),
                ("tp-mkt", "Маркетинг"),
                ("tp-first", "Первые шаги"),
                ("tp-svc", "Услуги"),
                ("tp-fin", "Финансы и учёт"),  # «ё» вместо «е» в файле соответствия
            ],
        ),
        "ContentSettingsTopics": (
            ["ContentSettingsId", "TopicId", "Order"],
            [
                ("cs-101", "tp-law", 1),
                ("cs-101", "tp-tax", 0),
                ("cs-102", "tp-mkt", 0),
                ("cs-201", "tp-first", 0),
                ("cs-201", "tp-svc", 1),
                ("cs-203", "tp-svc", 0),
                ("cs-301", "tp-tax", 0),
                ("cs-401", "tp-mkt", 0),
                ("cs-501", "tp-fin", 0),
                ("cs-999", "tp-mkt", 0),
            ],
        ),
        "ArticleSubjects": (
            ["Id", "Title"],
            [("sb-ip", "ИП"), ("sb-mp", "Маркетплейсы"), ("sb-acq", "Эквайринг и касса"), ("sb-tax", "Налоги")],
        ),
        "Tags": (
            ["Id", "Title"],
            [
                ("tg-start", "Старт бизнеса"),
                ("tg-grow", "Развитие бизнеса"),
                ("tg-tax", "Налоги и законы"),
                ("tg-skill", "Выбор ниши"),
            ],
        ),
        "ContentSettingsTags": (
            ["ContentSettingsId", "TagId", "Order"],
            [
                ("cs-101", "tg-start", 0),
                ("cs-102", "tg-grow", 0),
                ("cs-103", "tg-grow", 1),
                ("cs-103", "tg-start", 0),
                ("cs-201", "tg-skill", 0),
                ("cs-301", "tg-tax", 0),
            ],
        ),
        "Industries": (
            ["Id", "Title"],
            [
                ("in-horeca", "HoReCa"),
                ("in-ecom", "ECom"),
                ("in-intro", "Без опыта"),
                ("in-adv", "С опытом"),
                ("in-new", "Новинки"),
                ("in-seg", "Сегмент 001"),
                ("in-acc", "Бухгалтерия"),
            ],
        ),
        "ContentSettingsIndustries": (
            ["ContentSettingsId", "IndustryId", "Order"],
            [
                ("cs-101", "in-ecom", 1),
                ("cs-101", "in-horeca", 0),
                ("cs-101", "in-new", 2),
                ("cs-101", "in-seg", 3),
                ("cs-101", "in-acc", 4),
                ("cs-201", "in-intro", 0),
                ("cs-202", "in-intro", 0),
                ("cs-202", "in-adv", 1),
                ("cs-203", "in-adv", 0),
            ],
        ),
        "RecommendedItems": (
            ["Id", "ItemId", "ItemTypeId", "Order"],
            [
                ("A-101", "A-102", "7", 1),
                ("A-101", "D-301", "7", 0),
                ("A-101", "C-201", "7", 2),
                ("A-101", "C-201", "7", 3),  # повтор пары
                ("A-101", "Z-000", "7", 4),  # цели нет в каталоге
                ("X-900", "A-102", "7", 0),  # источник вне каталога: только популярность
                ("D-301", "D-301", "7", 0),  # ссылка на себя
                ("D-302", "A-102", "7", 0),
                ("D-302", "A-101", "7", 0),  # равный Order: порядок строк
            ],
        ),
        "CourseUserBindings": (
            ["Id", "CourseId", "UserId", "Status", "IsPaid", "IsDeleted"],
            [
                ("e-1", "C-201", "u-1", 0, 0, 0),
                ("e-2", "C-201", "u-2", 1, 0, 0),
                ("e-3", "C-201", "u-3", 2, 0, 0),
                ("e-4", "C-203", "u-1", 0, 0, 0),
                ("e-5", "C-203", "u-4", 1, 1, 1),  # удалённая запись не считается
            ],
        ),
    }


def write_db(path: Path, tables: dict[str, Table], *, keys: dict[str, tuple[str, ...]] | None = None) -> Path:
    """Создаёт базу. Таблицы из `keys` объявляются WITHOUT ROWID с этим первичным ключом."""
    con = sqlite3.connect(path)
    try:
        for name, (columns, rows) in tables.items():
            body = ", ".join(f"[{c}]" for c in columns)
            key = (keys or {}).get(name)
            if key:
                body += f", PRIMARY KEY ({', '.join(f'[{c}]' for c in key)})"
            con.execute(f"CREATE TABLE [{name}] ({body}){' WITHOUT ROWID' if key else ''}")
            con.executemany(f"INSERT INTO [{name}] VALUES ({', '.join('?' for _ in columns)})", rows)
        con.commit()
    finally:
        con.close()
    return path


def without(tables: dict[str, Table], *names: str) -> dict[str, Table]:
    return {name: table for name, table in tables.items() if name not in names}


def with_rows(tables: dict[str, Table], **extra: list[tuple]) -> dict[str, Table]:
    """Копия таблиц с добавленными строками: `with_rows(tables, Documents=[...])`."""
    assert set(extra) <= set(tables), "строки для неизвестной таблицы"
    return {name: (columns, [*rows, *extra.get(name, [])]) for name, (columns, rows) in tables.items()}


def drop_column(tables: dict[str, Table], table: str, column: str) -> dict[str, Table]:
    columns, rows = tables[table]
    index = columns.index(column)
    return {**tables, table: ([c for c in columns if c != column], [row[:index] + row[index + 1 :] for row in rows])}


def load_tables(tmp_path: Path, tables: dict[str, Table], **kwargs):
    return load_sqlite_catalog(write_db(tmp_path / "variant.sqlite3", tables), **kwargs)


@pytest.fixture
def catalog_db(tmp_path: Path) -> Path:
    return write_db(tmp_path / "catalog.sqlite3", base_tables())


@pytest.fixture
def signals_db(tmp_path: Path) -> Path:
    # Как в копии: первичный ключ (MaterialId, SignalCode) и WITHOUT ROWID
    return write_db(
        tmp_path / "catalog-signals.sqlite3",
        {"MaterialSignals": (SIGNAL_COLUMNS, SIGNAL_ROWS)},
        keys={"MaterialSignals": ("MaterialId", "SignalCode")},
    )


@pytest.fixture
def sqlite_catalog(catalog_db: Path, signals_db: Path):
    return load_sqlite_catalog(catalog_db, signals_path=signals_db)


def field_of(catalog, name: str) -> dict:
    return {key: getattr(m, name) for key, m in catalog.materials.items()}


def test_materials_ids_titles_formats_and_version(sqlite_catalog):
    assert sqlite_catalog.source == "sqlite"
    assert sqlite_catalog.size == 14
    article = sqlite_catalog.materials["article:A-101"]
    assert (article.title, article.format) == ("Вымышленная статья 1", "article")
    assert {m.format for m in sqlite_catalog.materials.values()} == {"article", "course", "document", "webinar", "podcast"}
    assert "course:C-201" in sqlite_catalog.materials and "document:D-302" in sqlite_catalog.materials
    assert all(m.url is None and m.short_benefit is None and m.next_step is None for m in sqlite_catalog.materials.values())
    assert re.fullmatch(r"sqlite-\d+-\d{4}-\d{2}-\d{2}", sqlite_catalog.version)
    assert sqlite_catalog.coverage["source_tables"]["Articles"] == 6
    assert sqlite_catalog.coverage["content_settings"]["unmatched"] == 1


def test_availability_uses_status_and_flags_where_present(sqlite_catalog):
    available = {key for key, m in sqlite_catalog.materials.items() if m.available}
    assert available == {
        "article:A-101",
        "article:A-105",
        "course:C-201",
        "course:C-203",
        "document:D-301",
        "webinar:W-401",
        "podcast:P-501",
    }
    # A-102 IsPublic = 0, A-103 черновик, A-104 закрыта, A-106 удалена, C-202 закрыт,
    # D-302 удалён в ContentSettings, W-402 черновик
    assert sqlite_catalog.coverage["available_by_format"] == {
        "article": 2,
        "course": 2,
        "document": 1,
        "podcast": 1,
        "webinar": 1,
    }
    assert sqlite_catalog.coverage["unavailable_by_reason"] == {"status": 2, "flags": 5, "no_settings": 0}


def test_status_must_be_published_in_both_tables(tmp_path):
    tables = with_rows(
        base_tables(),
        Documents=[
            ("D-303", "st-pub", "Вымышленный документ 3", 0),
            ("D-304", "st-draft", "Вымышленный документ 4", 0),
        ],
        ContentSettings=[
            ("cs-303", "D-303", "9", "st-draft", 0, "ty-open"),  # черновик только в ContentSettings
            ("cs-304", "D-304", "9", "st-pub", 0, "ty-open"),  # черновик только в таблице сущности
        ],
    )
    catalog = load_tables(tmp_path, tables)
    assert not catalog.materials["document:D-303"].available
    assert not catalog.materials["document:D-304"].available
    assert (catalog.coverage["by_format"]["document"], catalog.coverage["available_by_format"]["document"]) == (4, 1)
    assert catalog.coverage["unavailable_by_reason"] == {"status": 4, "flags": 5, "no_settings": 0}


def test_material_without_settings_unavailable(tmp_path):
    tables = with_rows(base_tables(), Podcasts=[("P-502", "st-pub", "Вымышленный подкаст 2", 0, 0, "30 минут")])
    catalog = load_tables(tmp_path, tables)
    podcast = catalog.materials["podcast:P-502"]
    assert (podcast.available, podcast.access, podcast.topics) == (False, "paid", ())
    assert catalog.coverage["content_settings"]["materials_without"] == 1
    assert catalog.coverage["unavailable_by_reason"]["no_settings"] == 1
    assert catalog.coverage["access_mapping"]["unknown"] == 2  # доступ неизвестен: осторожно как платный


@pytest.mark.parametrize("case", ["other-status-label", "no-status-columns"])
def test_no_available_materials_raises(tmp_path, case):
    tables, options = base_tables(), {}
    if case == "other-status-label":
        mapping = tmp_path / "mapping.yaml"
        mapping.write_text("published_statuses: [Published]\n", encoding="utf-8")
        options["mapping_path"] = mapping
    else:
        for table in ("Articles", "Courses", "Documents", "Webinars", "Podcasts", "ContentSettings"):
            tables = drop_column(tables, table, "StatusId")
    with pytest.raises(CatalogError, match="нет доступных материалов") as error:
        load_tables(tmp_path, tables, **options)
    message = str(error.value)
    assert "без статуса из published_statuses — 14, скрыто флагами — 5, без записи ContentSettings — 0" in message
    assert "published_statuses в файле соответствия" in message
    assert str(tmp_path) not in message


def test_topics_grouped_and_rubrics_added(sqlite_catalog):
    topics = field_of(sqlite_catalog, "topics")
    assert topics["article:A-101"] == ("taxes_law", "start")  # две исходные темы одной группы + рубрика «ИП»
    assert topics["article:A-102"] == ("marketing", "marketplaces")
    assert topics["article:A-103"] == ("finance",)  # только рубрика
    assert topics["article:A-104"] == ()  # рубрика без соответствия
    assert topics["course:C-201"] == ("start",)
    assert topics["course:C-203"] == ()  # только «Услуги»: нет группы
    assert topics["podcast:P-501"] == ("finance",)  # «учёт» и «учет» совпадают
    mapping_stats = sqlite_catalog.coverage["topics_mapping"]
    assert mapping_stats["links_by_group"] == {"taxes_law": 3, "marketing": 2, "finance": 1, "start": 1}
    assert mapping_stats["links_from_rubrics"] == {"marketplaces": 2, "finance": 1, "start": 1}
    assert (mapping_stats["unmapped_links"], mapping_stats["unmapped_titles"]) == (2, 1)
    # Рубрика «Налоги» без группы у A-104 и A-106: две статьи, одна подпись
    assert (mapping_stats["rubric_unmapped_articles"], mapping_stats["rubric_unmapped_labels"]) == (2, 1)


def test_rubric_does_not_duplicate_topic(tmp_path):
    tables = with_rows(
        base_tables(),
        Articles=[("A-107", "st-pub", "5 минут", "sb-acq", "Вымышленная статья 7", 0, 1, 0, "ty-open")],
        ContentSettings=[("cs-107", "A-107", "9", "st-pub", 0, "ty-open")],
        Topics=[("tp-fin2", "Финансы")],
        ContentSettingsTopics=[("cs-107", "tp-fin2", 0)],
    )
    catalog = load_tables(tmp_path, tables)
    # Тема «Финансы» и рубрика «Эквайринг и касса» дают одну группу: рубрика не добавляет повтор
    assert catalog.materials["article:A-107"].topics == ("finance",)
    mapping_stats = catalog.coverage["topics_mapping"]
    assert mapping_stats["links_by_group"]["finance"] == 2
    assert mapping_stats["links_from_rubrics"] == {"marketplaces": 2, "finance": 1, "start": 1}  # как без A-107
    assert mapping_stats["rubric_unmapped_articles"] == 2


def test_mapping_file_changes_result_without_code(tmp_path, catalog_db):
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text("topic_groups:\n  service: [Услуги]\n  marketing: [Маркетинг]\nrubrics: {}\n", encoding="utf-8")
    topics = field_of(load_sqlite_catalog(catalog_db, mapping_path=mapping), "topics")
    assert topics["course:C-203"] == ("service",)
    assert topics["course:C-201"] == ("service",)
    assert topics["article:A-101"] == ()  # раздел заменён целиком, рубрики выключены
    assert topics["article:A-102"] == ("marketing",)


def test_stage_from_tags(sqlite_catalog):
    stages = field_of(sqlite_catalog, "stages")
    assert stages["article:A-101"] == ("start",)
    assert stages["article:A-102"] == ("growth",)
    assert stages["article:A-103"] == ("start", "growth")
    assert stages["document:D-301"] == ()  # «Налоги и законы» нейтрален
    assert stages["course:C-201"] == ()  # прочие теги не задают стадию


def test_level_and_industries_without_service_labels(sqlite_catalog):
    levels = field_of(sqlite_catalog, "level")
    assert levels["course:C-201"] == "intro"
    assert levels["course:C-203"] == "advanced"
    assert levels["course:C-202"] is None  # обе метки уровня: противоречие
    assert levels["article:A-101"] is None
    industries = field_of(sqlite_catalog, "industries")
    assert industries["article:A-101"] == ("horeca", "ecom")
    assert all(not industries[key] for key in ("course:C-201", "course:C-202", "course:C-203"))
    assert sqlite_catalog.coverage["industries_mapping"] == {
        "service_links": 6,
        "unmapped_links": 1,
        "unmapped_labels": 1,
        "level_conflicts": 1,
    }


@pytest.mark.parametrize(
    ("text", "minutes"),
    [
        ("7 минут", 7),
        ("1 час 30 минут", 90),
        ("1,5 часа", 90),
        ("2 часа", 120),
        ("3 минуты", 3),
        ("1 минута", 1),
        ("5 часов", 300),
        ("45 мин.", 45),
        ("1 ч 5 мин", 65),
        ("1 час, 15 минут", 75),
        ("  10   МИНУТ ", 10),
        ("", None),
        (None, None),
        (30, None),
        ("скоро", None),
        ("15", None),
        ("2 суток", None),
        ("около 5 минут", None),
        ("0 минут", None),
    ],
)
def test_duration_parser(text, minutes):
    assert load_mapping().parse_duration(text) == minutes


def test_duration_in_catalog(sqlite_catalog):
    durations = field_of(sqlite_catalog, "duration_minutes")
    assert durations["article:A-101"] == 7
    assert durations["article:A-102"] == 90
    assert durations["course:C-201"] == 90
    assert durations["course:C-202"] == 120
    assert durations["webinar:W-402"] == 75
    assert durations["article:A-104"] is None  # не разобрано
    assert durations["document:D-301"] is None  # у документов нет столбца
    assert sqlite_catalog.coverage["duration_parse"] == {"parsed": 10, "unparsed": 1, "missing": 3}


def test_access_mapping(sqlite_catalog):
    access = field_of(sqlite_catalog, "access")
    assert access["article:A-101"] == "open"  # тип статьи в таблице сущности не используется
    assert access["article:A-105"] == "paid"  # «Закрытый» не сопоставлен: осторожно как платный
    assert access["course:C-201"] == "subscription"
    assert access["course:C-202"] == "paid"  # расхождение с Courses.TypeId: строже
    assert access["course:C-203"] == "paid"
    assert access["podcast:P-501"] == "subscription"
    assert sqlite_catalog.materials["course:C-201"].is_paid
    assert sqlite_catalog.coverage["by_access"] == {"open": 9, "paid": 3, "subscription": 2}
    assert sqlite_catalog.coverage["access_mapping"] == {"unknown": 1, "conflicts": 2}


def test_popularity_raw_and_rank_within_format(sqlite_catalog):
    raw = field_of(sqlite_catalog, "popularity_raw")
    assert (raw["course:C-201"], raw["course:C-203"], raw["course:C-202"]) == (3, 1, 0)
    assert (raw["article:A-102"], raw["article:A-101"], raw["article:A-103"]) == (3, 1, 0)
    assert (raw["document:D-301"], raw["document:D-302"]) == (1, 0)  # ссылка на себя не считается
    assert raw["webinar:W-401"] == raw["podcast:P-501"] == 0  # у вебинаров и подкастов нет источника
    # Точные доли задаёт coverage.normalize_popularity; здесь — порядок внутри формата
    popularity = field_of(sqlite_catalog, "popularity")
    assert popularity["course:C-201"] > popularity["course:C-203"] > popularity["course:C-202"]
    assert popularity["article:A-102"] > popularity["article:A-101"] > popularity["article:A-103"]
    assert popularity["document:D-301"] > popularity["document:D-302"]
    assert all(0 < popularity[key] <= 1 for key, value in raw.items() if value > 0)
    # Без записей и ссылок — 0, как без источника: документ без ссылок не обходит статью со ссылкой
    zero = {key for key, value in raw.items() if value == 0}
    assert {key for key, value in popularity.items() if value == 0} == zero
    assert popularity["document:D-302"] < popularity["article:A-101"]
    assert sqlite_catalog.coverage["popularity_scale"] == "per_format"


def test_signal_strength(sqlite_catalog):
    signals = field_of(sqlite_catalog, "signals")
    assert signals["article:A-101"] == (("tax_regime", 2), ("tax_reporting", 1))
    assert signals["document:D-301"] == (("contracts", 1),)
    assert signals["course:C-201"] == ()
    assert "signal" not in sqlite_catalog.disabled_features
    assert sqlite_catalog.coverage["signals_source"] == "loaded"
    assert sqlite_catalog.coverage["signal_links"] == {"loaded": 3, "unmatched": 2, "unknown_codes": 1}


def test_without_signals_path_signal_disabled(catalog_db):
    catalog = load_sqlite_catalog(catalog_db)
    assert "signal" in catalog.disabled_features
    assert all(not m.signals for m in catalog.materials.values())
    assert catalog.coverage["signals_source"] == "not_configured"


def test_missing_or_broken_signals_file_disables_signal(tmp_path, catalog_db, caplog):
    caplog.set_level(logging.WARNING, logger="app.catalog")
    broken = tmp_path / "broken.sqlite3"
    broken.write_bytes(b"not a database" * 100)
    no_table = write_db(tmp_path / "empty.sqlite3", {"Other": (["Id"], [])})
    cases = {tmp_path / "absent.sqlite3": "not_found", broken: "unreadable", no_table: "unreadable"}
    for path, status in cases.items():
        catalog = load_sqlite_catalog(catalog_db, signals_path=path)
        assert "signal" in catalog.disabled_features
        assert catalog.coverage["signals_source"] == status
    assert caplog.text.count("признак signal отключён") == len(cases)
    # В журнале только имя файла, без пути
    assert str(tmp_path) not in caplog.text and tmp_path.as_posix() not in caplog.text


def test_recommended_next_order_and_targets(sqlite_catalog):
    following = field_of(sqlite_catalog, "recommended_next")
    assert following["article:A-101"] == ("document:D-301", "article:A-102", "course:C-201")
    assert following["document:D-302"] == ("article:A-102", "article:A-101")
    assert following["document:D-301"] == ()
    assert sqlite_catalog.coverage["recommended_links"] == {
        "loaded": 5,
        "outside_catalog": 2,
        "self": 1,
        "duplicates": 1,
        "ambiguous": 0,
    }
    assert "continuation" not in sqlite_catalog.disabled_features


def test_ids_resolved_by_actual_match(tmp_path):
    tables = with_rows(base_tables(), Courses=[("A-101", "st-pub", "1 час", "Вымышленный курс 4", 0, 0, "ty-open")])
    catalog = load_tables(tmp_path, tables)
    assert {"article:A-101", "course:A-101"} <= set(catalog.materials)
    assert catalog.coverage["id_collisions"] == 1
    assert catalog.coverage["content_settings"]["ambiguous"] == 1  # не угадывается по EntityTypeId
    assert catalog.coverage["content_settings"]["materials_without"] == 2
    # Запись ContentSettings не приписана ни одному из двух: статус и доступ неизвестны, оба скрыты
    assert not catalog.materials["article:A-101"].available
    assert not catalog.materials["course:A-101"].available
    assert catalog.materials["article:A-101"].recommended_next == ()


def test_untitled_materials_get_distinct_titles(tmp_path):
    tables = with_rows(
        base_tables(),
        Articles=[
            ("A-107", "st-pub", "5 минут", None, None, 0, 1, 0, "ty-open"),
            ("A-108", "st-pub", "5 минут", None, "   ", 0, 1, 0, "ty-open"),
        ],
        ContentSettings=[
            ("cs-107", "A-107", "9", "st-pub", 0, "ty-open"),
            ("cs-108", "A-108", "9", "st-pub", 0, "ty-open"),
        ],
    )
    catalog = load_tables(tmp_path, tables)
    titles = [catalog.materials[key].title for key in ("article:A-107", "article:A-108")]
    assert titles == ["Статья без названия", "Статья без названия 2"]
    # Выдача убирает дубликаты по названию и формату: заглушки не должны совпадать
    available = [m for m in catalog.materials.values() if m.available]
    assert len({(m.title.casefold(), m.format) for m in available}) == len(available) == 9
    assert catalog.coverage["titles_missing"] == 2


def test_catalog_tables_without_rowid(tmp_path):
    keys = {"Articles": ("Id",), "ContentSettings": ("Id",), "ContentSettingsTopics": ("ContentSettingsId", "TopicId")}
    catalog = load_sqlite_catalog(write_db(tmp_path / "catalog.sqlite3", base_tables(), keys=keys))
    assert catalog.size == 14
    assert catalog.materials["article:A-101"].topics == ("taxes_law", "start")


def test_coverage_holds_only_aggregates(sqlite_catalog, tmp_path):
    text = json.dumps(sqlite_catalog.coverage, ensure_ascii=False)
    fragments = ("Вымышлен", "A-101", "C-201", "cs-101", "st-pub", "Услуги", "Бухгалтерия", "Налоги", "sqlite3")
    for fragment in (*fragments, str(tmp_path)):
        assert fragment not in text
    assert str(tmp_path) not in sqlite_catalog.version


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        pytest.param("topic_groups:\n  no_such_topic: [Маркетинг]\n", "topic_groups", id="unknown-topic-code"),
        pytest.param("topic_groups:\n  marketing: [Маркетинг]\n  sales: [маркетинг]\n", "две группы", id="title-twice"),
        pytest.param("topic_groups: [Маркетинг]\n", "topic_groups", id="section-type"),
        pytest.param("rubrics:\n  ИП: nowhere\n", "rubrics", id="unknown-rubric-code"),
        pytest.param("industries:\n  Без опыта: horeca\n", "служебная", id="industry-is-service-label"),
        pytest.param("stage_tags:\n  Старт бизнеса: launch\n", "stage_tags", id="unknown-stage"),
        pytest.param("access_titles:\n  Открытый: free\n", "access_titles", id="unknown-access"),
        pytest.param("duration_units:\n  минут: -1\n", "положительным", id="negative-unit"),
        pytest.param("duration_units:\n  2мин: 1\n", "одним словом", id="unit-with-digit"),
        pytest.param("history_events:\n  status:\n    0: watch\n", "history_events", id="unknown-event"),
        pytest.param("published_statuses: []\n", "published_statuses", id="no-published-status"),
        pytest.param("version: 2\n", "version", id="unknown-version"),
        pytest.param("unknown_section: 1\n", "неизвестные разделы", id="unknown-section"),
        pytest.param("- список\n", "словарь разделов", id="top-level-list"),
        pytest.param("topic_groups: {marketing: [Маркетинг]\n", "YAML", id="yaml-syntax"),
        pytest.param("", "пуст", id="empty-file"),
    ],
)
def test_invalid_mapping_raises_catalog_error(tmp_path, catalog_db, text, fragment):
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text(text, encoding="utf-8")
    with pytest.raises(CatalogError, match=fragment) as error:
        load_sqlite_catalog(catalog_db, mapping_path=mapping)
    assert str(error.value).startswith("Файл соответствия")
    assert str(tmp_path) not in str(error.value)


def test_missing_mapping_file(tmp_path, catalog_db):
    with pytest.raises(CatalogError, match="не найден: absent.yaml"):
        load_sqlite_catalog(catalog_db, mapping_path=tmp_path / "absent.yaml")


def test_example_mapping_matches_defaults():
    example = load_mapping(DATA_DIR / "mapping.example.yaml")
    assert example == load_mapping()
    assert example.history_status == {0: "view", 1: "start", 2: "complete"}
    assert example.history_paid == "purchase"


@pytest.mark.parametrize("table", ["Topics", "ContentSettings", "Podcasts", "CourseTypes"])
def test_missing_required_table(tmp_path, table):
    path = write_db(tmp_path / "catalog.sqlite3", without(base_tables(), table))
    with pytest.raises(CatalogError, match=f"нет обязательных таблиц: {table}") as error:
        load_sqlite_catalog(path)
    assert str(tmp_path) not in str(error.value)


def test_missing_required_column(tmp_path):
    with pytest.raises(CatalogError, match="В таблице Documents базы каталога нет столбцов: Title"):
        load_tables(tmp_path, drop_column(base_tables(), "Documents", "Title"))


def test_missing_or_unreadable_database(tmp_path):
    with pytest.raises(CatalogError, match="не найдена: absent.sqlite3") as error:
        load_sqlite_catalog(tmp_path / "absent.sqlite3")
    assert str(tmp_path) not in str(error.value)
    broken = tmp_path / "broken.sqlite3"
    broken.write_bytes(b"not a database" * 100)
    with pytest.raises(CatalogError, match="не читается: broken.sqlite3") as error:
        load_sqlite_catalog(broken)
    assert str(tmp_path) not in str(error.value)


def test_empty_catalog(tmp_path):
    tables = {name: (columns, []) for name, (columns, _) in base_tables().items()}
    with pytest.raises(CatalogError, match="Каталог пуст"):
        load_sqlite_catalog(write_db(tmp_path / "catalog.sqlite3", tables))


def test_optional_tables_missing_disable_features(tmp_path):
    optional = (
        "ArticleSubjects",
        "Tags",
        "ContentSettingsTags",
        "Industries",
        "ContentSettingsIndustries",
        "RecommendedItems",
        "CourseUserBindings",
    )
    catalog = load_sqlite_catalog(write_db(tmp_path / "catalog.sqlite3", without(base_tables(), *optional)))
    assert {"stage", "level", "industry", "continuation", "signal"} <= set(catalog.disabled_features)
    assert catalog.coverage["tables_missing"] == list(optional)
    assert catalog.coverage["tables_incomplete"] == {}
    assert catalog.materials["article:A-101"].topics == ("taxes_law",)
    assert all(m.popularity == 0.0 for m in catalog.materials.values())


@pytest.mark.parametrize(
    ("table", "column", "disabled"),
    [
        ("ArticleSubjects", "Title", set()),
        ("Tags", "Title", {"stage"}),
        ("ContentSettingsTags", "TagId", {"stage"}),
        ("Industries", "Title", {"level", "industry"}),
        ("ContentSettingsIndustries", "IndustryId", {"level", "industry"}),
        ("RecommendedItems", "ItemId", {"continuation"}),
        ("CourseUserBindings", "CourseId", set()),
    ],
)
def test_incomplete_optional_table_disables_only_its_feature(tmp_path, caplog, table, column, disabled):
    caplog.set_level(logging.WARNING, logger="app.catalog")
    catalog = load_tables(tmp_path, drop_column(base_tables(), table, column))
    assert catalog.size == 14
    assert (catalog.coverage["tables_missing"], catalog.coverage["tables_incomplete"]) == ([], {table: 1})
    assert set(catalog.disabled_features) == {"signal", *disabled}  # signal: вторая база не передана
    # Рубрики и популярность отключаются только вместе со своей таблицей
    raw = field_of(catalog, "popularity_raw")
    assert (catalog.coverage["topics_mapping"]["links_from_rubrics"] == {}) == (table == "ArticleSubjects")
    assert (raw["course:C-201"] == 0) == (table == "CourseUserBindings")
    assert (raw["article:A-102"] == 0) == (table == "RecommendedItems")
    assert f"В таблице {table} базы каталога нет столбцов {column}" in caplog.text


def test_databases_opened_read_only(tmp_path, catalog_db, signals_db, monkeypatch):
    opened: list[tuple[str, bool]] = []
    connect = sqlite3.connect

    def spy(database, *args, **kwargs):
        opened.append((str(database), kwargs.get("uri", False)))
        return connect(database, *args, **kwargs)

    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", spy)
        load_sqlite_catalog(catalog_db, signals_path=signals_db)
    after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    assert after == before  # ни изменений, ни журналов рядом с базой
    # Обе базы открываются по URI с mode=ro
    assert [Path(urlsplit(uri).path).name for uri, _ in opened] == [catalog_db.name, signals_db.name]
    assert all(uri_flag is True and parse_qs(urlsplit(uri).query).get("mode") == ["ro"] for uri, uri_flag in opened)
    # Соединение загрузчика отказывает в записи
    db = _Database(catalog_db, "каталога")
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.con.execute("CREATE TABLE [Extra] ([Id])")
    finally:
        db.close()


def test_loader_selects_sqlite_source(tmp_path, catalog_db, signals_db):
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text("topic_groups:\n  service: [Услуги]\n", encoding="utf-8")
    settings = Settings(
        catalog_source="sqlite", catalog_path=catalog_db, catalog_signals_path=signals_db, catalog_mapping=mapping
    )
    catalog = load_catalog(settings)
    assert (catalog.source, catalog.size, catalog.coverage["signals_source"]) == ("sqlite", 14, "loaded")
    assert catalog.materials["course:C-203"].topics == ("service",)  # CATALOG_MAPPING дошёл до загрузчика
