"""Проверки проекции бэкапа и пригодности двух SQLite-файлов для сервиса."""

from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest

from app.ranking.base import HistoryIndex
from app.ranking.policy import eligible
from app.catalog.sqlite_source import DETAILS_TABLE, load_sqlite_catalog, platform_url

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from import_alfa_backup import (
    CATALOG_FILE,
    COURSE_INFO_COLUMNS,
    SIGNALS_FILE,
    ImportErrorDetail,
    export_columns,
    import_backup,
    pseudonym,
    write_catalog,
)

from .test_sqlite_source import base_tables
from .conftest import client_for


def test_sqlite_export_keeps_catalog_links_and_only_available_titles(tmp_path):
    source = base_tables()
    article_columns, article_rows = source["Articles"]
    first = list(article_rows[0])
    first[article_columns.index("Title")] = "Как выбрать налоговый режим для ИП"
    source["Articles"] = ([*article_columns, "Content", "Url"], [
        (*row, "закрытый текст", f"article_{index}") for index, row in enumerate([first, *article_rows[1:]])
    ])
    for table, slug in (("Documents", "document"), ("Webinars", "webinar"), ("Podcasts", "podcast")):
        names, original_rows = source[table]
        source[table] = ([*names, "Url"], [(*row, slug) for row in original_rows])
    names, original_rows = source["Courses"]
    source["Courses"] = ([*names, "Url", "LessonQuantity", "IsCertified", "Description"], [
        (*original_rows[0], "test-course", 22, True, "  Учимся\n планировать бюджет "),
        (*original_rows[1], "hidden-course", 7, True, "Описание скрытого курса"),
        (*original_rows[2], "https://other.example/test", 0, False, "Самостоятельный курс"),
    ])
    source["CourseInfoTypes"] = (list(COURSE_INFO_COLUMNS["CourseInfoTypes"]), [
        ("audience", "Кому подойдёт", False),
        ("outcome", "Что вы получите от обучения", False),
        ("removed", "Кому подойдет", True),
    ])
    source["CourseInfoBindings"] = (list(COURSE_INFO_COLUMNS["CourseInfoBindings"]), [
        ("C-201", "audience", None, " Владельцам\t магазинов ", 2),
        ("C-201", "audience", None, "Новичкам", 1),
        ("C-201", "audience", None, "новичкам", 3),
        ("C-201", "audience", None, "&lt;b&gt;HTML&lt;/b&gt;", 0),
        ("C-201", "audience", None, "  ", 0),
        ("C-201", "audience", "tariff", "Для тарифа", 0),
        ("C-201", "removed", None, "Удалённый тип", 0),
        ("C-202", "outcome", None, "Закрытый пункт", 0),
        *[("C-201", "outcome", None, f"Результат {index}", index) for index in range(6, 0, -1)],
    ])
    source["LessonEmbedItems"] = (["Id", "HtmlContent"], [("lesson-block", "полный текст урока")])
    columns = export_columns({table: set(names) for table, (names, _) in source.items()})
    rows = {}
    for table, names in columns.items():
        originals, original_rows = source[table]
        rows[table] = [
            [row[originals.index(name)] for name in names]
            for row in original_rows
            if table != "CourseUserBindings" or not row[originals.index("IsDeleted")]
        ]
    catalog = write_catalog(tmp_path, columns, rows)

    article = catalog.materials[f"article:{pseudonym('A-101')}"]
    assert article.available and article.title == "Как выбрать налоговый режим для ИП"
    assert "taxes_law" in article.topics and ("tax_regime", 2) in article.signals
    assert article.recommended_next[0] == f"document:{pseudonym('D-301')}"
    assert article.url == "https://kurs.alfabank.ru/articles/article_0/"
    assert catalog.materials[f"document:{pseudonym('D-301')}"].url == "https://kurs.alfabank.ru/documents/document/"
    assert catalog.materials[f"webinar:{pseudonym('W-401')}"].url == "https://kurs.alfabank.ru/webinars/webinar/"
    assert catalog.materials[f"podcast:{pseudonym('P-501')}"].url is None
    draft = catalog.materials[f"article:{pseudonym('A-103')}"]
    assert not draft.available and draft.title != "Вымышленная статья 3" and not draft.signals
    assert draft not in eligible(catalog, HistoryIndex.build(()))
    course = catalog.materials[f"course:{pseudonym('C-201')}"]
    assert course.popularity_raw == 3
    assert course.url == "https://kurs.alfabank.ru/courses/test-course/"
    assert course.lesson_count == 22 and course.has_certificate is True
    assert course.course_details.description == "Учимся планировать бюджет"
    assert course.course_details.audiences == ("Новичкам", "Владельцам магазинов")
    assert course.course_details.outcomes == tuple(f"Результат {index}" for index in range(1, 6))
    hidden = catalog.materials[f"course:{pseudonym('C-202')}"]
    assert hidden.url is None and hidden.lesson_count is None and hidden.has_certificate is None
    assert hidden.course_details is None
    incomplete = catalog.materials[f"course:{pseudonym('C-203')}"]
    assert incomplete.popularity_raw == 1
    assert incomplete.url is None and incomplete.lesson_count is None and incomplete.has_certificate is False
    assert incomplete.course_details.description == "Самостоятельный курс"
    assert incomplete.course_details.audiences == incomplete.course_details.outcomes == ()

    with closing(sqlite3.connect(tmp_path / CATALOG_FILE)) as database:
        table_names = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert table_names == (columns.keys() - COURSE_INFO_COLUMNS.keys()) | {DETAILS_TABLE}
        assert "Description" not in [row[1] for row in database.execute('PRAGMA table_info("Courses")')]
        assert [row[1] for row in database.execute('PRAGMA table_info("CourseUserBindings")')] == ["CourseId"]
        assert {"Content", "Url"}.isdisjoint(row[1] for row in database.execute('PRAGMA table_info("Articles")'))
        assert {row[0] for row in database.execute('SELECT "Id" FROM "Articles"')}.isdisjoint({"A-101", "A-103"})
        stored = {row[0] for row in database.execute(f'SELECT "MaterialId" FROM "{DETAILS_TABLE}"')}
        assert stored.isdisjoint({pseudonym("C-202"), pseudonym("A-103")})
    with closing(sqlite3.connect(tmp_path / SIGNALS_FILE)) as database:
        assert database.execute('SELECT COUNT(*) FROM "MaterialSignals"').fetchone()[0] > 0
    with client_for(catalog_source="sqlite", catalog_path=tmp_path / CATALOG_FILE) as client:
        response = client.post("/api/recommend", json={"task": "", "topic": course.topics[0]})
        assert response.status_code == 200
        item = next(item for item in response.json()["items"] if item["material_id"] == course.id)
        assert (item["url"], item["link_allowed"], item["lesson_count"], item["has_certificate"]) == (
            course.url, True, 22, True,
        )
        assert item["course_details"] == {
            "description": course.course_details.description,
            "audiences": list(course.course_details.audiences),
            "outcomes": list(course.course_details.outcomes),
        }
        comparison = client.post("/api/compare", json={"topic": course.topics[0]}).json()
        for method in ("baseline", "personal"):
            compared = next(row for row in comparison[method]["items"] if row["material_id"] == course.id)
            assert compared["course_details"] == item["course_details"]

    with closing(sqlite3.connect(tmp_path / CATALOG_FILE)) as database, database:
        database.execute(f'ALTER TABLE "{DETAILS_TABLE}" DROP COLUMN "CourseDetails"')
    old_details = load_sqlite_catalog(tmp_path / CATALOG_FILE).materials[course.id]
    assert old_details.course_details is None and old_details.url == course.url and old_details.lesson_count == 22

    with closing(sqlite3.connect(tmp_path / CATALOG_FILE)) as database, database:
        database.execute(f'UPDATE "{DETAILS_TABLE}" SET "PlatformUrl" = ?', ("https://other.example/courses/test/",))
    reloaded = load_sqlite_catalog(tmp_path / CATALOG_FILE)
    assert reloaded.materials[course.id].url is None

    with closing(sqlite3.connect(tmp_path / CATALOG_FILE)) as database, database:
        database.execute(f'DROP TABLE "{DETAILS_TABLE}"')
    legacy = load_sqlite_catalog(tmp_path / CATALOG_FILE).materials[course.id]
    assert legacy.url is None and legacy.lesson_count is None and legacy.has_certificate is None


@pytest.mark.parametrize("slug", [None, "", "../course", "//evil.example", "test?x=y", "test#x", "%2f", " тест", "UP"])
def test_platform_url_rejects_invalid_slugs(slug):
    assert platform_url("course", slug) is None


@pytest.mark.parametrize(("missing", "message"), [
    ("table", "Нет обязательной таблицы ContentSettings"),
    ("column", "В таблице ContentSettings нет обязательных столбцов: EntityId"),
])
def test_export_requires_catalog_schema(missing, message):
    schema = {table: set(names) for table, (names, _) in base_tables().items()}
    if missing == "table":
        del schema["ContentSettings"]
    else:
        schema["ContentSettings"].remove("EntityId")
    with pytest.raises(ImportErrorDetail, match=message):
        export_columns(schema)


def test_import_preserves_existing_destination(tmp_path):
    backup = tmp_path / "fixture.backup"
    backup.touch()
    output = tmp_path / "catalog"
    output.mkdir()
    existing = output / CATALOG_FILE
    existing.write_bytes(b"existing")
    with pytest.raises(ImportErrorDetail, match="Каталог назначения уже существует"):
        import_backup(backup, output)
    assert existing.read_bytes() == b"existing"
