"""Каноническая модель каталога. Источники приводят свои поля к этим типам (PLAN.md, 2.2)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .course_details import CourseDetails

if TYPE_CHECKING:
    from .global_search import SearchIndex
    from .task_search import TaskIndex
    from .text_search import TextIndex

# Код материала: одно правило для загрузчика JSON и для истории в запросе (schemas.HistoryEventIn).
# Материал с другим кодом нельзя было бы отметить изученным: запрос с такой историей получил бы 422.
MATERIAL_ID_MAX_LENGTH = 64
MATERIAL_ID_PATTERN = r"^[A-Za-z0-9:_\-]+$"
_MATERIAL_ID = re.compile(rf"[A-Za-z0-9:_\-]{{1,{MATERIAL_ID_MAX_LENGTH}}}")


def valid_material_id(value: object) -> bool:
    return isinstance(value, str) and _MATERIAL_ID.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class Material:
    """Материал каталога в канонических полях.

    Пустой кортеж или None означает «нет сведений»: связанный признак нейтрален.
    `popularity` нормирована в [0, 1] источником; `popularity_raw` — исходная величина.
    `signals` — пары (код признака, сила): 2 при совпадении в названии, 1 только в описании.
    """

    id: str
    title: str
    format: str
    topics: tuple[str, ...] = ()
    signals: tuple[tuple[str, int], ...] = ()
    stages: tuple[str, ...] = ()
    level: str | None = None
    industries: tuple[str, ...] = ()
    duration_minutes: int | None = None
    access: str = "open"
    available: bool = True
    popularity_raw: float = 0.0
    popularity: float = 0.0
    recommended_next: tuple[str, ...] = ()
    url: str | None = None
    short_benefit: str | None = None
    next_step: str | None = None
    lesson_count: int | None = None
    has_certificate: bool | None = None
    course_details: CourseDetails | None = None

    @property
    def is_paid(self) -> bool:
        return self.access != "open"


@dataclass(frozen=True, slots=True)
class HistoryEvent:
    material_id: str
    event: str  # view | start | complete | purchase
    seq: int


@dataclass(frozen=True, slots=True)
class DemoProfile:
    """Синтетический тестовый профиль для демо-режима (PLAN.md, 2.6)."""

    id: str
    label: str
    description: str
    task: str = ""
    stage: str | None = None
    experience: str | None = None
    format_pref: str | None = None
    industry: str | None = None
    history: tuple[HistoryEvent, ...] = ()


@dataclass(slots=True)
class Catalog:
    """Загруженный каталог.

    `disabled_features` — признаки ранжирования, для которых в источнике нет поля
    (имена из `vocab.FEATURES`). `coverage` — только агрегаты, без строк данных.
    """

    materials: dict[str, Material]
    source: str
    version: str
    disabled_features: tuple[str, ...] = ()
    coverage: dict[str, Any] = field(default_factory=dict)
    text_index: TextIndex | None = None
    task_index: TaskIndex | None = None
    search_index: SearchIndex | None = None
    search_fallback: SearchIndex | None = None

    @property
    def size(self) -> int:
        return len(self.materials)


class CatalogError(RuntimeError):
    """Каталог не удалось загрузить: неверный путь, формат или пустой источник."""
