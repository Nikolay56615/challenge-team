"""Подготовить две локальные SQLite-базы для сервиса из PostgreSQL-бэкапа."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, uuid4, uuid5

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.catalog.lexicon import parse_task
from app.catalog.course_details import CourseDetails
from app.catalog.mapping import norm_label
from app.catalog.models import Catalog, CatalogError
from app.catalog.sqlite_source import (
    DETAILS_TABLE,
    ENTITY_TABLES,
    OPTIONAL,
    PLATFORM_SECTIONS,
    REQUIRED,
    load_sqlite_catalog,
    platform_url,
)

POSTGRES_IMAGE = "postgres:17.6-bookworm"
CATALOG_FILE = "catalog.sqlite3"
SIGNALS_FILE = "catalog-signals.sqlite3"
TABLE_DATA = re.compile(r"^\d+; \d+ \d+ TABLE DATA public (\w+) ")

# Обязательные столбцы берём из контракта загрузчика. Дополнительно сохраняем
# поля, которые влияют на доступность, порядок и нормализацию материалов.
ENTITY_COLUMNS = ("StatusId", "IsDeleted", "IsClosed", "IsPublic", "Duration")
EXTRA_COLUMNS = {
    **dict.fromkeys(ENTITY_TABLES.values(), ENTITY_COLUMNS),
    **{ENTITY_TABLES[fmt]: (*ENTITY_COLUMNS, "Url") for fmt in PLATFORM_SECTIONS},
    "Articles": (*ENTITY_COLUMNS, "SubjectId", "Url"),
    "Courses": (*ENTITY_COLUMNS, "TypeId", "Url", "LessonQuantity", "IsCertified", "Description"),
    "ContentSettings": ("StatusId", "IsDeleted"),
    "ContentSettingsTopics": ("Order",),
    "ContentSettingsTags": ("Order",),
    "ContentSettingsIndustries": ("Order",),
    "RecommendedItems": ("Order",),
}
INTEGER_COLUMNS = frozenset({"IsDeleted", "IsClosed", "IsPublic", "Order"})
DETAIL_FIELDS = frozenset({"Url", "LessonQuantity", "IsCertified", "Description"})
COURSE_INFO_COLUMNS = {
    "CourseInfoTypes": ("Id", "Title", "IsDeleted"),
    "CourseInfoBindings": ("CourseId", "CourseInfoTypeId", "CourseTariffId", "Title", "Order"),
}
COURSE_SECTIONS = {"кому подойдет": "audiences", "что вы получите от обучения": "outcomes"}


class ImportErrorDetail(RuntimeError):
    """Сообщение об импорте без значений полей бэкапа."""


def docker(args: list[str], problem: str, *, stdin: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["docker", *args], input=stdin, capture_output=True, encoding="utf-8", errors="replace", check=False
        )
    except FileNotFoundError as exc:
        raise ImportErrorDetail("Команда docker недоступна") from exc
    if result.returncode:
        # Ошибки PostgreSQL могут включать значения из строк архива.
        raise ImportErrorDetail(problem)
    return result.stdout


def export_columns(schema: dict[str, set[str]]) -> dict[str, tuple[str, ...]]:
    """Выбрать столбцы для SQLite и проверить обязательную часть схемы."""
    columns: dict[str, tuple[str, ...]] = {}
    for table, minimum in (REQUIRED | OPTIONAL).items():
        source = schema.get(table, set())
        if missing := set(minimum) - source:
            if table not in REQUIRED:
                continue
            if table not in schema:
                raise ImportErrorDetail(f"Нет обязательной таблицы {table}")
            raise ImportErrorDetail(f"В таблице {table} нет обязательных столбцов: {', '.join(sorted(missing))}")
        columns[table] = (*minimum, *(col for col in EXTRA_COLUMNS.get(table, ()) if col in source))
    if all(set(names) <= schema.get(table, set()) for table, names in COURSE_INFO_COLUMNS.items()):
        columns.update(COURSE_INFO_COLUMNS)
    return columns


def read_backup(backup: Path) -> tuple[dict[str, tuple[str, ...]], dict[str, list[list]]]:
    return read_backup_rows(backup, export_columns)


def read_backup_rows(
    backup: Path, select_columns: Callable[[dict[str, set[str]]], dict[str, tuple[str, ...]]]
) -> tuple[dict[str, tuple[str, ...]], dict[str, list[list]]]:
    container = f"alfa-catalog-import-{uuid4().hex}"
    mounted = f"type=bind,source={backup},target=/backup.dump,readonly"
    docker(
        ["run", "--detach", "--rm", "--network", "none", "--name", container, "--user", "postgres",
         "--tmpfs", "/tmp:rw,nosuid,nodev,mode=1777", "--mount", mounted, "--entrypoint", "sleep",
         POSTGRES_IMAGE, "infinity"],
        f"Не удалось запустить {POSTGRES_IMAGE}. Проверьте Docker, наличие образа и доступ к бэкапу",
    )
    exec_args = ["exec", "-i", container]
    restore = ["pg_restore", "--exit-on-error", "--no-owner", "--no-privileges", "-h", "/tmp", "-d", "postgres"]
    psql = ["psql", "-XqAt", "-v", "ON_ERROR_STOP=1", "-h", "/tmp", "-d", "postgres"]
    try:
        toc = docker([*exec_args, "pg_restore", "--list", "/backup.dump"],
                     "Бэкап повреждён или не читается pg_restore 17.6")
        data_entries = {match[1]: line for line in toc.splitlines() if (match := TABLE_DATA.match(line))}
        docker([*exec_args, "initdb", "-D", "/tmp/pgdata", "--auth=trust", "--no-locale", "--encoding=UTF8"],
               "Не удалось подготовить временный PostgreSQL")
        docker(
            [*exec_args, "pg_ctl", "-D", "/tmp/pgdata", "-l", "/tmp/postgres.log",
             "-o", "-c listen_addresses='' -k /tmp", "-w", "start"],
            "Не удалось запустить временный PostgreSQL",
        )
        docker([*exec_args, *restore, "--section=pre-data", "/backup.dump"],
               "Не удалось восстановить схему бэкапа")
        schema_sql = (
            "SELECT json_build_array(table_name, column_name) FROM information_schema.columns "
            "WHERE table_schema = 'public';"
        )
        schema: dict[str, set[str]] = {}
        for line in docker([*exec_args, *psql], "Не удалось прочитать схему бэкапа", stdin=schema_sql).splitlines():
            table, column = json.loads(line)
            if table in data_entries:
                schema.setdefault(table, set()).add(column)
        columns = select_columns(schema)
        toc_list = "\n".join(data_entries[table] for table in columns) + "\n"
        docker(
            [*exec_args, *restore, "--data-only", "--use-list=/dev/stdin", "/backup.dump"],
            "Не удалось прочитать данные таблиц каталога",
            stdin=toc_list,
        )
        queries = []
        for table, names in columns.items():
            projection = ", ".join(f'"{name}"' for name in names)
            where = (
                ' WHERE "IsDeleted" IS NOT TRUE'
                if table == "CourseUserBindings" and "IsDeleted" in schema[table]
                else ""
            )
            queries.append(
                f"SELECT json_build_array('{table}', "
                f"COALESCE(json_agg(json_build_array({projection}) ORDER BY ctid), '[]'::json)) "
                f'FROM public."{table}"{where};'
            )
        exported = docker([*exec_args, *psql], "Не удалось выгрузить поля каталога", stdin="\n".join(queries))
        return columns, dict(json.loads(line) for line in exported.splitlines())
    finally:
        docker(["rm", "--force", container], "Не удалось удалить временный контейнер PostgreSQL")


def pseudonym(value: str) -> str:
    return uuid5(NAMESPACE_URL, f"alfa-course-catalog:{value}").hex


def course_sections(rows: dict[str, list[list]]) -> dict[tuple[str, str], list[str]]:
    types = {
        ref: COURSE_SECTIONS[label]
        for ref, title, deleted in rows.get("CourseInfoTypes", [])
        if not deleted and isinstance(title, str) and (label := norm_label(title)) in COURSE_SECTIONS
    }
    sections: dict[tuple[str, str], list[str]] = defaultdict(list)
    bindings = sorted(rows.get("CourseInfoBindings", []), key=lambda row: (row[4] is None, row[4]))
    for course, type_ref, tariff, title, _ in bindings:
        if course and tariff is None and (section := types.get(type_ref)):
            sections[pseudonym(course), section].append(title)
    return sections


def write_catalog(directory: Path, columns: dict[str, tuple[str, ...]], rows: dict[str, list[list]]) -> Catalog:
    catalog_path = directory / CATALOG_FILE
    signals_path = directory / SIGNALS_FILE
    entity_formats = {table: fmt for fmt, table in ENTITY_TABLES.items()}
    source_cards: dict[tuple[str, str], dict] = {}
    with closing(sqlite3.connect(catalog_path)) as database, database:
        for table, names in columns.items():
            if table in COURSE_INFO_COLUMNS:
                continue
            stored = tuple(name for name in names if name not in DETAIL_FIELDS)
            definitions = ", ".join(f'"{name}" {"INTEGER" if name in INTEGER_COLUMNS else "TEXT"}' for name in stored)
            database.execute(f'CREATE TABLE "{table}" ({definitions})')
            values = []
            for row in rows[table]:
                record = {
                    name: pseudonym(value) if value is not None and name.endswith("Id") else value
                    for name, value in zip(names, row, strict=True)
                }
                if table in entity_formats and record["Id"] is not None:
                    fmt = entity_formats[table]
                    ref = record["Id"]
                    source_cards.setdefault((fmt, ref), record.copy())
                    if record["Title"]:
                        record["Title"] = f"Материал {ref}"
                values.append(tuple(record[name] for name in stored))
            placeholders = ", ".join("?" for _ in stored)
            database.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', values)

    # Сохраняем оригинальные названия после проверки статусов и флагов загрузчиком.
    staged = load_sqlite_catalog(catalog_path)
    sections = course_sections(rows)
    signals = []
    details = []
    with closing(sqlite3.connect(catalog_path)) as database, database:
        for material in staged.materials.values():
            fmt, ref = material.id.split(":", 1)
            if not material.available:
                continue
            source = source_cards[fmt, ref]
            if title := source["Title"]:
                database.execute(f'UPDATE "{ENTITY_TABLES[fmt]}" SET "Title" = ? WHERE "Id" = ?', (title, ref))
                signals.extend((ref, fmt, code, 1) for code in parse_task(title).signals)
            url = platform_url(fmt, source.get("Url"))
            quantity = source.get("LessonQuantity")
            lesson_count = quantity if fmt == "course" and type(quantity) is int and quantity > 0 else None
            certificate = source.get("IsCertified") if fmt == "course" else None
            card = None
            if fmt == "course":
                card = CourseDetails.prepare(
                    source.get("Description"), sections.get((ref, "audiences")), sections.get((ref, "outcomes"))
                )
            if url or lesson_count is not None or certificate is not None or card:
                metadata = json.dumps(asdict(card), ensure_ascii=False) if card else None
                details.append((ref, fmt, url, lesson_count, certificate, metadata))
        database.execute(
            f'CREATE TABLE "{DETAILS_TABLE}" ('
            '"MaterialId" TEXT, "MaterialFormat" TEXT, "PlatformUrl" TEXT, '
            '"LessonCount" INTEGER, "HasCertificate" INTEGER, "CourseDetails" TEXT, '
            'PRIMARY KEY ("MaterialId", "MaterialFormat")) WITHOUT ROWID'
        )
        database.executemany(f'INSERT INTO "{DETAILS_TABLE}" VALUES (?, ?, ?, ?, ?, ?)', details)
    with closing(sqlite3.connect(signals_path)) as database, database:
        database.execute(
            'CREATE TABLE "MaterialSignals" ('
            '"MaterialId" TEXT, "MaterialFormat" TEXT, "SignalCode" TEXT, "MatchedTitle" INTEGER, '
            'PRIMARY KEY ("MaterialId", "MaterialFormat", "SignalCode")) WITHOUT ROWID'
        )
        database.executemany('INSERT INTO "MaterialSignals" VALUES (?, ?, ?, ?)', signals)

    catalog = load_sqlite_catalog(catalog_path, signals_path=signals_path)
    if catalog.coverage["signals_source"] != "loaded" or catalog.coverage["signal_links"]["loaded"] != len(signals):
        raise ImportErrorDetail("Проверка базы признаков не прошла")
    return catalog


def import_backup(backup: Path, output: Path) -> Catalog:
    if not backup.is_file():
        raise ImportErrorDetail("Файл бэкапа не найден")
    if output.exists() or output.is_symlink():
        raise ImportErrorDetail("Каталог назначения уже существует. Укажите новый путь")
    output.parent.mkdir(parents=True, exist_ok=True)
    columns, rows = read_backup(backup.resolve())
    with TemporaryDirectory(dir=output.parent, prefix=".alfa-import-") as temporary:
        staging = Path(temporary) / "catalog"
        staging.mkdir()
        catalog = write_catalog(staging, columns, rows)
        if output.exists() or output.is_symlink():
            raise ImportErrorDetail("Каталог назначения уже существует. Укажите новый путь")
        staging.rename(output)
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        catalog = import_backup(args.backup, args.output_dir)
    except (ImportErrorDetail, CatalogError) as exc:
        parser.exit(1, f"Ошибка импорта: {exc}\n")
    except (ValueError, OSError, sqlite3.Error):
        parser.exit(1, "Ошибка импорта: не удалось подготовить SQLite-каталог\n")
    print(json.dumps({
        "materials": catalog.size,
        "available": catalog.coverage["available"],
        "by_format": catalog.coverage["by_format"],
        "signal_links": catalog.coverage["signal_links"]["loaded"],
        "links_by_format": dict(sorted(Counter(m.format for m in catalog.materials.values() if m.url).items())),
        "courses_with_lesson_count": catalog.coverage["fields_count"]["lesson_count"],
        "courses_with_certificate": catalog.coverage["fields_count"]["certificate"],
        "courses_with_description": catalog.coverage["fields_count"]["course_description"],
        "courses_with_sections": catalog.coverage["fields_count"]["course_sections"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
