"""Каноническая модель каталога. Источники приводят свои поля к этим типам (docs/plan.md, 2.2)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, TypeGuard

# Код материала: одно правило для загрузчика JSON и для истории в запросе (schemas.HistoryEventIn).
# Материал с другим кодом нельзя было бы отметить изученным: запрос с такой историей получил бы 422.
MATERIAL_ID_MAX_LENGTH = 64
MATERIAL_ID_PATTERN = r"^[A-Za-z0-9:_\-]+$"
_MATERIAL_ID = re.compile(rf"[A-Za-z0-9:_\-]{{1,{MATERIAL_ID_MAX_LENGTH}}}")


def valid_material_id(value: object) -> TypeGuard[str]:
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
    """Синтетический тестовый профиль для демо-режима (docs/plan.md, 2.6)."""

    id: str
    label: str
    description: str
    task: str = ""
    stage: str | None = None
    experience: str | None = None
    format_pref: str | None = None
    industry: str | None = None
    history: tuple[HistoryEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class CoursePairs:
    """Пары совместных записей на курсы для признака «похожие курсы» (docs/plan.md, раздел 9, решение 2026-11-11).

    `together[a][b]` — число пользователей с записями на оба курса, симметрично; `totals[a]` — число
    пользователей курса a. Хранятся только пары с поддержкой не ниже `min_support`: пара ниже порога
    не даёт ни вклада, ни фразы. Сходство по R03: sim(a, b) = together / (totals[a]^α · totals[b]^(1−α)).
    """

    together: dict[str, dict[str, int]]
    totals: dict[str, int]
    min_support: int

    def neighbours(self, course: str) -> dict[str, int]:
        return self.together.get(course, {})

    def similarity(self, anchor: str, course: str, alpha: float) -> float:
        """Сходство курса истории с кандидатом; 0 без пары, ниже порога или без пользователей у курса."""
        n = self.together.get(anchor, {}).get(course, 0)
        if n < self.min_support or n <= 0:
            return 0.0
        anchor_total, course_total = self.totals.get(anchor, 0), self.totals.get(course, 0)
        if anchor_total <= 0 or course_total <= 0:
            return 0.0
        # int ** float в typeshed — Any (отрицательное основание дало бы complex); здесь основания положительны
        denominator: float = anchor_total**alpha * course_total ** (1 - alpha)
        return n / denominator

    @property
    def size(self) -> int:
        """Число неупорядоченных пар."""
        return sum(len(row) for row in self.together.values()) // 2


@dataclass(slots=True)
class Catalog:
    """Загруженный каталог.

    `disabled_features` — признаки ранжирования, для которых в источнике нет поля
    (имена из `vocab.FEATURES`). `coverage` — только агрегаты, без строк данных.
    `course_pairs` — пары совместных записей; их подключает загрузчик (`loader.py`), без них
    признак `co_enrollment` отключён.
    """

    materials: dict[str, Material]
    source: str
    version: str
    disabled_features: tuple[str, ...] = ()
    coverage: dict[str, Any] = field(default_factory=dict)
    course_pairs: CoursePairs | None = None

    @property
    def size(self) -> int:
        return len(self.materials)


class CatalogError(RuntimeError):
    """Каталог не удалось загрузить: неверный путь, формат или пустой источник."""
