"""Каталог из локальной SQLite-копии выгрузки (PLAN.md, 2.1–2.4, 2.8).

Обе базы открываются только на чтение. Материалы — статьи, курсы, документы, вебинары и подкасты,
`id` = `{формат}:{Id}`. Метаданные приходят из `ContentSettings` по `EntityId`. Источник и цель
связей определяются по фактическому совпадению идентификаторов: коды `EntityTypeId` и `ItemTypeId`
технические и не используются. Подписи переводятся в коды файлом соответствия (`mapping.py`).

Доступность: однозначная запись `ContentSettings` и статус «Опубликовано» в ней и в таблице
сущности; флаги скрывают материал там, где они есть: `IsDeleted = 1`, `IsClosed = 1`, `IsPublic = 0`.
Каталог без доступных материалов не загружается. Популярность — ранг внутри формата; без записей
и ссылок она равна 0, как у форматов без источника, и равенства решает `id`. Необязательная таблица
(рубрики, теги, отрасли, связи, записи на курсы), которой нет или в которой не хватает столбцов,
отключает связанный признак. Сводка содержит только агрегаты: без названий, идентификаторов,
строк и путей.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Callable
from contextlib import closing, suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import vocab
from .course_details import CourseDetails
from .coverage import disabled_features, normalize_popularity, summarize
from .mapping import CatalogMapping, load_mapping, norm_label
from .models import Catalog, CatalogError, Material
from .text_search import TextIndex

log = logging.getLogger("app.catalog")

MAX_TITLE = 120

# Формат -> таблица сущности
ENTITY_TABLES: dict[str, str] = {
    "article": "Articles",
    "course": "Courses",
    "document": "Documents",
    "webinar": "Webinars",
    "podcast": "Podcasts",
}

# Обязательные таблицы и столбцы: без них каталог не строится
REQUIRED: dict[str, tuple[str, ...]] = {
    **{table: ("Id", "Title") for table in ENTITY_TABLES.values()},
    "ContentSettings": ("Id", "EntityId", "TypeId"),
    "Statuses": ("Id", "Title"),
    "CourseTypes": ("Id", "Title"),
    "Topics": ("Id", "Title"),
    "ContentSettingsTopics": ("ContentSettingsId", "TopicId"),
}

# Необязательные таблицы: без таблицы или без её столбцов отключается связанный признак
OPTIONAL: dict[str, tuple[str, ...]] = {
    "ArticleSubjects": ("Id", "Title"),
    "Tags": ("Id", "Title"),
    "ContentSettingsTags": ("ContentSettingsId", "TagId"),
    "Industries": ("Id", "Title"),
    "ContentSettingsIndustries": ("ContentSettingsId", "IndustryId"),
    "RecommendedItems": ("Id", "ItemId"),
    "CourseUserBindings": ("CourseId",),
}

COUNTED_TABLES: tuple[str, ...] = (
    *ENTITY_TABLES.values(),
    "ContentSettings",
    "ContentSettingsTopics",
    "ContentSettingsTags",
    "ContentSettingsIndustries",
    "RecommendedItems",
    "CourseUserBindings",
)

SIGNALS_TABLE = "MaterialSignals"
SIGNALS_COLUMNS = ("MaterialId", "MaterialFormat", "SignalCode", "MatchedTitle")
DETAILS_TABLE = "MaterialDetails"
DETAILS_COLUMNS = ("MaterialId", "MaterialFormat", "PlatformUrl", "LessonCount", "HasCertificate")
PLATFORM_SECTIONS = {"article": "articles", "course": "courses", "document": "documents", "webinar": "webinars"}
SLUG = re.compile(r"[a-z0-9_-]+")

# Источник популярности (PLAN.md, 2.2): записи на курсы, входящие редакционные ссылки
BY_ENROLLMENTS = frozenset({"course"})
BY_INCOMING_LINKS = frozenset({"article", "document"})

ACCESS_RANK = {"open": 0, "subscription": 1, "paid": 2}

# Поле -> есть ли сведения у материала; для сводки по форматам
FIELD_CHECKS: dict[str, Callable[[Material], bool]] = {
    "topics": lambda m: bool(m.topics),
    "signals": lambda m: bool(m.signals),
    "stage": lambda m: bool(m.stages),
    "level": lambda m: m.level is not None,
    "industries": lambda m: bool(m.industries),
    "duration": lambda m: m.duration_minutes is not None,
    "lesson_count": lambda m: m.lesson_count is not None,
    "certificate": lambda m: m.has_certificate is True,
    "course_description": lambda m: bool(m.course_details and m.course_details.description),
    "course_sections": lambda m: bool(m.course_details and (m.course_details.audiences or m.course_details.outcomes)),
    "popularity": lambda m: m.popularity_raw > 0,
    "recommended_next": lambda m: bool(m.recommended_next),
}


def platform_url(fmt: str, slug: object) -> str | None:
    section = PLATFORM_SECTIONS.get(fmt)
    if section and isinstance(slug, str) and SLUG.fullmatch(slug):
        return f"https://kurs.alfabank.ru/{section}/{slug}/"
    return None


def load_sqlite_catalog(
    db_path: Path, *, signals_path: Path | None = None, mapping_path: Path | None = None
) -> Catalog:
    mapping = load_mapping(mapping_path)
    path = Path(db_path)
    with closing(_Database(path, "каталога")) as db:
        db.require(REQUIRED)
        reader = _Reader(db, mapping)
        reader.read()
        version = _version(path)
    if not reader.entries:
        raise CatalogError("Каталог пуст: в таблицах материалов нет записей")
    stats = reader.stats
    signals = _read_signals(signals_path, reader.entries, stats)
    materials = _build(reader, signals)
    if not any(m.available for m in materials):
        raise CatalogError(
            "В каталоге нет доступных материалов: без статуса из published_statuses — {status}, "
            "скрыто флагами — {flags}, без записи ContentSettings — {no_settings}. "
            "Проверьте published_statuses в файле соответствия".format(**stats["unavailable_by_reason"])
        )
    stats["fields_count"] = {name: sum(1 for m in materials if check(m)) for name, check in FIELD_CHECKS.items()}
    stats["fields_by_format"] = {
        name: dict(sorted(Counter(m.format for m in materials if check(m)).items()))
        for name, check in FIELD_CHECKS.items()
    }
    return Catalog(
        materials={m.id: m for m in materials},
        source="sqlite",
        version=version,
        disabled_features=disabled_features(materials, signals_loaded=stats["signals_source"] == "loaded"),
        coverage=summarize(materials, **stats),
        text_index=TextIndex(materials),
    )


class _Database:
    """Соединение только на чтение и схема базы. Ошибки SQLite → CatalogError без путей."""

    def __init__(self, path: Path, role: str) -> None:
        self.role = role
        self.name = path.name
        if not path.is_file():
            raise CatalogError(f"База {role} не найдена: {self.name}")
        try:
            self.con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        except sqlite3.Error as exc:
            raise CatalogError(f"База {role} не открывается: {self.name}") from exc
        try:
            self.con.execute("PRAGMA query_only = ON")
            names = [row[0] for row in self.con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
            self.schema: dict[str, set[str]] = {
                name.lower(): {col[1].lower() for col in self.con.execute(f'PRAGMA table_info("{_quote(name)}")')}
                for name in names
            }
        except sqlite3.Error as exc:
            self.con.close()
            raise CatalogError(f"База {role} не читается: {self.name}. Нужен файл SQLite") from exc

    def close(self) -> None:
        self.con.close()

    def has(self, table: str, column: str | None = None) -> bool:
        columns = self.schema.get(table.lower())
        return columns is not None and (column is None or column.lower() in columns)

    def pick(self, table: str, column: str | None) -> str:
        """Столбец для SELECT или NULL, если его нет в таблице."""
        return f"[{column}]" if column and self.has(table, column) else "NULL"

    def order_by(self, table: str, *columns: str) -> str:
        """ORDER BY по имеющимся столбцам, затем по порядку строк, если он есть (не WITHOUT ROWID)."""
        keys = [f"[{column}]" for column in columns if self.has(table, column)]
        with suppress(sqlite3.Error):
            self.con.execute(f"SELECT rowid FROM [{table}] LIMIT 0")
            keys.append("rowid")
        return f" ORDER BY {', '.join(keys)}" if keys else ""

    def rows(self, table: str, sql: str) -> list[tuple[Any, ...]]:
        try:
            return self.con.execute(sql).fetchall()
        except sqlite3.Error as exc:
            raise CatalogError(f"Не удалось прочитать таблицу {table} из базы {self.role}: {self.name}") from exc

    def check(self, tables: dict[str, tuple[str, ...]]) -> tuple[list[str], dict[str, list[str]]]:
        """Отсутствующие таблицы и недостающие столбцы имеющихся таблиц."""
        absent = [table for table in tables if not self.has(table)]
        incomplete = {
            table: lost
            for table, columns in tables.items()
            if table not in absent and (lost := [column for column in columns if not self.has(table, column)])
        }
        return absent, incomplete

    def require(self, tables: dict[str, tuple[str, ...]]) -> None:
        """Обязательные таблицы и столбцы: без них — CatalogError."""
        absent, incomplete = self.check(tables)
        if absent:
            raise CatalogError(f"В базе {self.role} нет обязательных таблиц: {', '.join(absent)}")
        if incomplete:
            table, lost = next(iter(incomplete.items()))
            raise CatalogError(f"В таблице {table} базы {self.role} нет столбцов: {', '.join(lost)}")


@dataclass(slots=True)
class _Entry:
    """Черновик материала: сведения из таблиц до сборки канонической записи."""

    fmt: str
    title: str
    duration: Any = None
    url: str | None = None
    lesson_count: int | None = None
    has_certificate: bool | None = None
    course_details: CourseDetails | None = None
    statuses: list[str | None] = field(default_factory=list)
    hidden: bool = False
    settings_type: str | None = None
    course_type: str | None = None
    subject: str | None = None
    has_settings: bool = False
    topics: list[str] = field(default_factory=list)
    stages: set[str] = field(default_factory=set)
    levels: set[str] = field(default_factory=set)
    industries: list[str] = field(default_factory=list)
    next_items: list[str] = field(default_factory=list)


class _Reader:
    """Читает материалы и связи в черновики и копит агрегаты для сводки."""

    def __init__(self, db: _Database, mapping: CatalogMapping) -> None:
        self.db = db
        self.mapping = mapping
        self.entries: dict[str, _Entry] = {}
        self.index: dict[str, list[str]] = defaultdict(list)  # Id сущности -> ключи материалов
        self.by_settings: dict[str, str] = {}  # ContentSettings.Id -> ключ материала
        self.enrollments: Counter[str] = Counter()
        self.incoming: Counter[str] = Counter()
        absent, incomplete = db.check(OPTIONAL)
        for table, lost in incomplete.items():
            log.warning(
                "В таблице %s базы %s нет столбцов %s: таблица не используется", table, db.role, ", ".join(lost)
            )
        # Таблицы, из которых можно читать: обязательные проверены, необязательные — полные
        self.usable = frozenset(REQUIRED) | (frozenset(OPTIONAL) - {*absent, *incomplete})
        self.stats: dict[str, Any] = {
            "popularity_scale": "per_format",
            "tables_missing": absent,
            "tables_incomplete": {table: len(lost) for table, lost in incomplete.items()},
        }
        self.statuses = self.titles("Statuses")
        self.course_types = self.titles("CourseTypes")

    def read(self) -> None:
        self.stats["source_tables"] = {
            table: self.db.rows(table, f"SELECT COUNT(*) FROM [{table}]")[0][0]
            for table in COUNTED_TABLES
            if self.db.has(table)
        }
        self.read_entities()
        self.read_details()
        self.read_settings()
        self.read_topics()
        self.read_stages()
        self.read_industries()
        self.read_enrollments()
        self.read_recommended()

    def titles(self, table: str) -> dict[str, str]:
        rows = self.db.rows(table, f"SELECT [Id], [Title] FROM [{table}]")
        return {ref: title for raw, title in rows if (ref := _ref(raw)) is not None and isinstance(title, str)}

    def read_entities(self) -> None:
        skipped = 0
        untitled: Counter[str] = Counter()
        for fmt, table in ENTITY_TABLES.items():
            optional = (
                "StatusId",
                "IsDeleted",
                "IsClosed",
                "IsPublic",
                "Duration",
                "TypeId" if fmt == "course" else None,  # тип доступа курса сверяется с ContentSettings
                "SubjectId" if fmt == "article" else None,
            )
            columns = ", ".join(self.db.pick(table, column) for column in optional)
            has_status = self.db.has(table, "StatusId")
            sql = f"SELECT [Id], [Title], {columns} FROM [{table}]{self.db.order_by(table)}"
            for raw_id, title, status, deleted, closed, public, duration, type_id, subject in self.db.rows(table, sql):
                ref = _ref(raw_id)
                key = f"{fmt}:{ref}"
                if ref is None or key in self.entries:
                    skipped += 1
                    continue
                text = title.strip()[:MAX_TITLE] if isinstance(title, str) else ""
                if not text:
                    # Заглушка с номером: одинаковые название и формат выдача считает дубликатами
                    untitled[fmt] += 1
                    number = f" {untitled[fmt]}" if untitled[fmt] > 1 else ""
                    text = f"{vocab.format_label(fmt)} без названия{number}"
                entry = _Entry(fmt=fmt, title=text, duration=duration)
                if has_status:
                    entry.statuses.append(self.statuses.get(_ref(status) or ""))
                entry.hidden = _flag(deleted) is True or _flag(closed) is True or _flag(public) is False
                entry.course_type = self.course_types.get(_ref(type_id) or "")
                entry.subject = _ref(subject)
                self.entries[key] = entry
                self.index[ref].append(key)
        self.stats["skipped_records"] = skipped
        self.stats["titles_missing"] = sum(untitled.values())
        self.stats["id_collisions"] = sum(1 for keys in self.index.values() if len(keys) > 1)

    def read_details(self) -> None:
        table = DETAILS_TABLE
        if not all(self.db.has(table, column) for column in DETAILS_COLUMNS):
            return
        columns = ", ".join(f"[{column}]" for column in DETAILS_COLUMNS)
        details_column = self.db.pick(table, "CourseDetails")
        sql = f"SELECT {columns}, {details_column} FROM [{table}]"
        for ref, fmt, url, lessons, certificate, details in self.db.rows(table, sql):
            entry = self.entries.get(f"{fmt}:{ref}")
            if entry is None:
                continue
            if isinstance(url, str) and (canonical := platform_url(fmt, url.rstrip("/").rsplit("/", 1)[-1])):
                if url == canonical:
                    entry.url = canonical
            if fmt == "course":
                entry.lesson_count = lessons if type(lessons) is int and lessons > 0 else None
                entry.has_certificate = _flag(certificate)
                entry.course_details = CourseDetails.from_json(details)

    def read_settings(self) -> None:
        table = "ContentSettings"
        has_status = self.db.has(table, "StatusId")
        columns = ", ".join(self.db.pick(table, column) for column in ("StatusId", "IsDeleted"))
        counts: Counter[str] = Counter()
        sql = f"SELECT [Id], [EntityId], [TypeId], {columns} FROM [{table}]{self.db.order_by(table)}"
        for settings_id, entity_id, type_id, status, deleted in self.db.rows(table, sql):
            ref = _ref(settings_id)
            keys = self.index.get(_ref(entity_id) or "", [])
            if ref is None or not keys:
                counts["unmatched"] += 1
                continue
            if len(keys) > 1:
                counts["ambiguous"] += 1
                continue
            entry = self.entries[keys[0]]
            self.by_settings[ref] = keys[0]
            if entry.has_settings:
                counts["duplicates"] += 1  # связи берутся из всех записей, статус и доступ — из первой
                continue
            entry.has_settings = True
            counts["linked"] += 1
            if has_status:
                entry.statuses.append(self.statuses.get(_ref(status) or ""))
            entry.hidden = entry.hidden or _flag(deleted) is True
            entry.settings_type = self.course_types.get(_ref(type_id) or "")
        counts["materials_without"] = sum(1 for entry in self.entries.values() if not entry.has_settings)
        self.stats["content_settings"] = {
            key: counts[key] for key in ("linked", "materials_without", "unmatched", "ambiguous", "duplicates")
        }

    def links(self, table: str, dictionary: str, column: str) -> list[tuple[_Entry, str | None]]:
        """Связи ContentSettings со справочником в порядке Order: (черновик, подпись)."""
        if not {table, dictionary} <= self.usable:
            return []
        titles = self.titles(dictionary)
        result: list[tuple[_Entry, str | None]] = []
        sql = f"SELECT [ContentSettingsId], [{column}] FROM [{table}]{self.db.order_by(table, 'Order')}"
        for settings_id, ref in self.db.rows(table, sql):
            key = self.by_settings.get(_ref(settings_id) or "")
            if key is not None:
                result.append((self.entries[key], titles.get(_ref(ref) or "")))
        return result

    def read_topics(self) -> None:
        by_group: Counter[str] = Counter()
        unmapped_links = 0
        unmapped_titles: set[str] = set()
        for entry, title in self.links("ContentSettingsTopics", "Topics", "TopicId"):
            code = self.mapping.topic(title)
            if code is None:
                unmapped_links += 1
                if title:
                    unmapped_titles.add(norm_label(title))
                continue
            by_group[code] += 1
            if code not in entry.topics:
                entry.topics.append(code)
        from_rubrics: Counter[str] = Counter()
        rubric_unmapped = 0
        rubric_labels: set[str] = set()
        if "ArticleSubjects" in self.usable and self.db.has("Articles", "SubjectId"):
            subjects = self.titles("ArticleSubjects")
            for entry in self.entries.values():
                if entry.subject is None:
                    continue
                label = subjects.get(entry.subject)
                code = self.mapping.rubric(label)
                if code is None:
                    rubric_unmapped += 1  # рубрика без группы или ссылка на неизвестную рубрику
                    if label:
                        rubric_labels.add(norm_label(label))
                elif code not in entry.topics:
                    entry.topics.append(code)
                    from_rubrics[code] += 1
        self.stats["topics_mapping"] = {
            "links_by_group": _ranked(by_group),
            "links_from_rubrics": _ranked(from_rubrics),
            "unmapped_links": unmapped_links,
            "unmapped_titles": len(unmapped_titles),
            "rubric_unmapped_articles": rubric_unmapped,
            "rubric_unmapped_labels": len(rubric_labels),
        }

    def read_stages(self) -> None:
        for entry, title in self.links("ContentSettingsTags", "Tags", "TagId"):
            stage = self.mapping.stage(title)
            if stage is not None:
                entry.stages.add(stage)

    def read_industries(self) -> None:
        counts: Counter[str] = Counter()
        unmapped: set[str] = set()
        for entry, label in self.links("ContentSettingsIndustries", "Industries", "IndustryId"):
            if self.mapping.is_service(label):
                counts["service_links"] += 1
                level = self.mapping.level(label)
                if level is not None:
                    entry.levels.add(level)
                continue
            code = self.mapping.industry(label)
            if code is None:
                counts["unmapped_links"] += 1
                if label:
                    unmapped.add(norm_label(label))
            elif code not in entry.industries:
                entry.industries.append(code)
        self.stats["industries_mapping"] = {
            "service_links": counts["service_links"],
            "unmapped_links": counts["unmapped_links"],
            "unmapped_labels": len(unmapped),
            "level_conflicts": sum(1 for entry in self.entries.values() if len(entry.levels) > 1),
        }

    def read_enrollments(self) -> None:
        table = "CourseUserBindings"
        if table not in self.usable:
            return
        where = "WHERE COALESCE([IsDeleted], 0) <> 1" if self.db.has(table, "IsDeleted") else ""
        sql = f"SELECT [CourseId], COUNT(*) FROM [{table}] {where} GROUP BY [CourseId]"
        for course_id, count in self.db.rows(table, sql):
            key = f"course:{_ref(course_id)}"
            if key in self.entries:
                self.enrollments[key] += count

    def read_recommended(self) -> None:
        """Редакционные связи: источник `Id`, цель `ItemId`, порядок `Order`, при равенстве — порядок строк.

        Входящие ссылки на статьи и документы считаются от любых источников, в том числе вне
        каталога, без повторов пар и ссылок материала на себя.
        """
        table = "RecommendedItems"
        if table not in self.usable:
            return
        counts: Counter[str] = Counter()
        seen: set[tuple[str, str]] = set()
        sql = f"SELECT [Id], [ItemId] FROM [{table}]{self.db.order_by(table, 'Order')}"
        for source_id, item_id in self.db.rows(table, sql):
            source, item = _ref(source_id), _ref(item_id)
            if source is None or item is None:
                counts["outside_catalog"] += 1
                continue
            if source == item:
                counts["self"] += 1
                continue
            if (source, item) in seen:
                counts["duplicates"] += 1
                continue
            seen.add((source, item))
            sources, targets = self.index.get(source, []), self.index.get(item, [])
            if len(targets) == 1 and self.entries[targets[0]].fmt in BY_INCOMING_LINKS:
                self.incoming[targets[0]] += 1
            if len(sources) > 1 or len(targets) > 1:
                counts["ambiguous"] += 1
            elif not (sources and targets):
                counts["outside_catalog"] += 1
            else:
                self.entries[sources[0]].next_items.append(targets[0])
                counts["loaded"] += 1
        self.stats["recommended_links"] = {
            key: counts[key] for key in ("loaded", "outside_catalog", "self", "duplicates", "ambiguous")
        }


def _read_signals(
    path: Path | None, entries: dict[str, _Entry], stats: dict[str, Any]
) -> dict[str, dict[str, int]]:
    """Признаки из второй базы: сила 2 при совпадении в названии, иначе 1.

    Без файла или при ошибке чтения признак отключается, а каталог загружается (PLAN.md, 7.2, S6).
    """
    found: dict[str, dict[str, int]] = defaultdict(dict)
    counts: Counter[str] = Counter()
    records: list[tuple[Any, ...]] = []
    if path is None:
        status = "not_configured"
    else:
        try:
            with closing(_Database(Path(path), "признаков")) as db:
                db.require({SIGNALS_TABLE: SIGNALS_COLUMNS})
                columns = ", ".join(f"[{column}]" for column in SIGNALS_COLUMNS)
                records = db.rows(SIGNALS_TABLE, f"SELECT {columns} FROM [{SIGNALS_TABLE}]")  # порядок не важен
            status = "loaded"
        except CatalogError as exc:
            status = "unreadable" if Path(path).is_file() else "not_found"
            log.warning("%s; признак signal отключён", exc)
    for material_id, fmt, code, matched_title in records:
        ref = _ref(material_id)
        key = f"{str(fmt).strip().lower()}:{ref}"
        if ref is None or key not in entries:
            counts["unmatched"] += 1
        elif code not in vocab.SIGNALS:
            counts["unknown_codes"] += 1
        else:
            strength = 2 if _flag(matched_title) is True else 1
            found[key][code] = max(found[key].get(code, 0), strength)
    stats["signals_source"] = status
    stats["signal_links"] = {
        "loaded": sum(len(codes) for codes in found.values()),
        "unmatched": counts["unmatched"],
        "unknown_codes": counts["unknown_codes"],
    }
    return found


def _build(reader: _Reader, signals: dict[str, dict[str, int]]) -> list[Material]:
    entries, mapping, stats = reader.entries, reader.mapping, reader.stats
    raw: dict[str, float] = {}
    for key, entry in entries.items():
        if entry.fmt in BY_ENROLLMENTS:
            raw[key] = float(reader.enrollments[key])
        elif entry.fmt in BY_INCOMING_LINKS:
            raw[key] = float(reader.incoming[key])
        else:
            raw[key] = 0.0
    ranks = normalize_popularity(raw, {key: entry.fmt for key, entry in entries.items()}, "per_format")
    durations: Counter[str] = Counter()
    access_counts: Counter[str] = Counter()
    unavailable: Counter[str] = Counter()
    materials: list[Material] = []
    for key, entry in entries.items():
        minutes = mapping.parse_duration(entry.duration)
        blank = entry.duration is None or (isinstance(entry.duration, str) and not entry.duration.strip())
        durations["parsed" if minutes is not None else "missing" if blank else "unparsed"] += 1
        published = bool(entry.statuses) and all(mapping.is_published(status) for status in entry.statuses)
        failed = {"status": not published, "flags": entry.hidden, "no_settings": not entry.has_settings}
        reasons = [reason for reason, value in failed.items() if value]
        unavailable.update(reasons)
        materials.append(
            Material(
                id=key,
                title=entry.title,
                format=entry.fmt,
                topics=tuple(entry.topics),
                signals=tuple(sorted(signals.get(key, {}).items(), key=lambda kv: (-kv[1], kv[0]))),
                stages=tuple(code for code in vocab.STAGES if code in entry.stages),
                level=next(iter(entry.levels)) if len(entry.levels) == 1 else None,
                industries=tuple(entry.industries),
                duration_minutes=minutes,
                access=_access(entry, mapping, access_counts),
                available=not reasons,
                popularity_raw=raw[key],
                # Без записей и ссылок normalize_popularity даёт 0, как без источника. Равенства решает id
                popularity=ranks.get(key, 0.0),
                recommended_next=tuple(entry.next_items),
                url=entry.url if not reasons else None,
                lesson_count=entry.lesson_count if not reasons else None,
                has_certificate=entry.has_certificate if not reasons else None,
                course_details=entry.course_details if not reasons else None,
            )
        )
    stats["duration_parse"] = {key: durations[key] for key in ("parsed", "unparsed", "missing")}
    stats["access_mapping"] = {key: access_counts[key] for key in ("unknown", "conflicts")}
    # Причины недоступности; материал может попасть в несколько
    stats["unavailable_by_reason"] = {key: unavailable[key] for key in ("status", "flags", "no_settings")}
    return materials


def _access(entry: _Entry, mapping: CatalogMapping, counts: Counter[str]) -> str:
    """Доступ из ContentSettings.TypeId; у курсов сверяется с Courses.TypeId, при расхождении — строже."""
    access = mapping.access(entry.settings_type)
    if access is None:
        counts["unknown"] += 1
        return "paid"  # неизвестный доступ трактуется осторожно: как платный
    course = mapping.access(entry.course_type)
    if course is not None and course != access:
        counts["conflicts"] += 1
        return max(access, course, key=lambda code: ACCESS_RANK.get(code, len(ACCESS_RANK)))
    return access


def _version(path: Path) -> str:
    """Версия по размеру и дате изменения файла, без пути."""
    try:
        info = path.stat()
    except OSError as exc:
        raise CatalogError(f"База каталога не читается: {path.name}") from exc
    day = datetime.fromtimestamp(info.st_mtime, tz=timezone.utc).date().isoformat()
    return f"sqlite-{info.st_size}-{day}"


def _ref(value: Any) -> str | None:
    """Идентификатор строкой для сопоставления между таблицами; пустой — None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _flag(value: Any) -> bool | None:
    """Логическое поле 0/1, в том числе строкой. NULL и прочее — нет сведений."""
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str) and value.strip() in {"0", "1"}:
        return value.strip() == "1"
    return None


def _quote(name: str) -> str:
    return name.replace('"', '""')


def _ranked(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))
