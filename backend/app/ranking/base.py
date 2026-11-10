"""Общие типы ранжирования: профиль запроса, история и оценённый материал."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..catalog.lexicon import ParsedTask
from ..catalog.models import HistoryEvent, Material

# Порядок признаков при равном вкладе: определяет порядок фраз причины
FEATURE_PRIORITY: tuple[str, ...] = (
    "in_progress",
    "topic",
    "signal",
    "stage",
    "level",
    "industry",
    "format",
    "continuation",
    "effort",
)

# Фраза о востребованности — только для материалов из этой верхушки своей темы по популярности
POPULAR_TOP_N = 3


@dataclass(frozen=True, slots=True)
class Profile:
    """Нормализованный запрос: поля анкеты, история и предел выдачи."""

    task: str = ""
    stage: str | None = None
    experience: str | None = None
    format_pref: str | None = None
    industry: str | None = None
    topic: str | None = None
    history: tuple[HistoryEvent, ...] = ()
    limit: int = 5


@dataclass(frozen=True, slots=True)
class HistoryIndex:
    """События по материалам и последнее событие истории."""

    events: dict[str, frozenset[str]]
    last: HistoryEvent | None

    @classmethod
    def build(cls, history: tuple[HistoryEvent, ...]) -> HistoryIndex:
        events: dict[str, set[str]] = defaultdict(set)
        last: HistoryEvent | None = None
        for event in history:
            events[event.material_id].add(event.event)
            if last is None or event.seq >= last.seq:
                last = event
        return cls(events={k: frozenset(v) for k, v in events.items()}, last=last)

    def of(self, material_id: str) -> frozenset[str]:
        return self.events.get(material_id, frozenset())

    def flags(self, material_id: str) -> list[str]:
        """Пометки истории для показа: пройдено, в процессе или открывали."""
        seen = self.of(material_id)
        if "complete" in seen:
            return ["completed"]
        if "start" in seen:
            return ["in_progress"]
        if "view" in seen:
            return ["viewed"]
        return []


@dataclass(frozen=True, slots=True)
class Context:
    """Всё, что нужно для оценки: профиль, разбор задачи, темы кандидатов, история, отключённые признаки."""

    profile: Profile
    parsed: ParsedTask
    topics: tuple[str, ...]
    history: HistoryIndex
    disabled: frozenset[str]
    catalog: dict[str, Material]

    @property
    def industry(self) -> str | None:
        """Сфера из списка; из текста — только если список не заполнен."""
        return self.profile.industry or self.parsed.industry

    @property
    def stage_hint(self) -> str | None:
        return None if self.profile.stage else self.parsed.stage_hint

    @property
    def level_hint(self) -> str | None:
        return None if self.profile.experience else self.parsed.level_hint

    @property
    def format_hint(self) -> str | None:
        return None if self.profile.format_pref else self.parsed.format_hint


@dataclass(slots=True)
class Scored:
    """Материал с оценкой, вкладами признаков и сведениями для объяснения."""

    material: Material
    score: float = 0.0
    contributions: dict[str, float] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    matched_topic: str | None = None
    matched_signal: str | None = None
    level_direction: int = 0  # +1 материал глубже уровня профиля, −1 проще
    continuation_of: str | None = None
    tie_won: bool = False
    popular_in_topic: bool = False  # среди POPULAR_TOP_N самых популярных кандидатов своей темы
    starter_topic: str | None = None

    def add(self, feature: str, value: float) -> None:
        if value:
            self.contributions[feature] = round(self.contributions.get(feature, 0.0) + value, 4)
            self.score = round(self.score + value, 4)


def sort_key(item: Scored) -> tuple[float, float, str]:
    """Оценка по убыванию, затем нормированная популярность по убыванию, затем код."""
    return (-item.score, -item.material.popularity, item.material.id)


def mark_tie_winners(items: list[Scored], top_n: int = POPULAR_TOP_N) -> None:
    """Помечает победителей равенства и самые популярные материалы каждой темы.

    `items` — все кандидаты в порядке `sort_key`. `tie_won`: оценка равна следующей, а популярность
    выше. `popular_in_topic`: популярность не ниже `top_n`-й среди кандидатов темы, с которой материал
    совпал. Фразу о востребованности получает материал с обеими пометками.
    """
    for current, following in zip(items, items[1:]):
        if current.score == following.score and current.material.popularity > following.material.popularity:
            current.tie_won = True
    thresholds: dict[str, float] = {}
    for item in items:
        topic = item.matched_topic
        if topic is None:
            continue
        if topic not in thresholds:
            values = sorted((i.material.popularity for i in items if topic in i.material.topics), reverse=True)
            thresholds[topic] = values[min(top_n, len(values)) - 1]
        item.popular_in_topic = item.material.popularity >= thresholds[topic]
