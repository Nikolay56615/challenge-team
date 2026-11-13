"""Общие типы ранжирования: профиль запроса, история и оценённый материал."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import pairwise

from ..catalog.lexicon import ParsedTask
from ..catalog.models import CoursePairs, HistoryEvent, Material

# Порядок признаков при равном вкладе: определяет порядок фраз причины. «Похожие курсы» (co_enrollment)
# стоят сразу после признака из текста: обе фразы говорят о самом материале и опираются на данные, а не
# на анкету. Тема истории (history_topic) — общая фраза, как тема задачи, но слабее: при равном вкладе
# она уступает всем конкретным фразам и стоит перед усилием (docs/plan.md, 3.6; раздел 9, решение 2026-11-11).
FEATURE_PRIORITY: tuple[str, ...] = (
    "in_progress",
    "topic",
    "signal",
    "co_enrollment",
    "stage",
    "level",
    "industry",
    "format",
    "continuation",
    "history_topic",
    "effort",
)

# Фраза о востребованности — только для материалов из этой верхушки своей темы по популярности
POPULAR_TOP_N = 3


@dataclass(frozen=True, slots=True)
class MaterialFilters:
    format: str | None = None
    access: str | None = None


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
    filters: MaterialFilters = field(default_factory=MaterialFilters)


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
class HistorySignals:
    """Что история даёт пилоту «похожие курсы» (docs/plan.md, раздел 9, решение 2026-11-11).

    `anchors` — курсы истории из каталога, в том числе недоступные: их пары переносят вес на доступных
    соседей (R15). `topics` — темы материалов истории из каталога. Порядок — от последнего события
    к первому, при равном `seq` — по коду.
    """

    anchors: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()

    @classmethod
    def build(cls, history: tuple[HistoryEvent, ...], catalog: dict[str, Material]) -> HistorySignals:
        latest: dict[str, int] = {}
        for event in history:
            if event.material_id in catalog:
                latest[event.material_id] = max(latest.get(event.material_id, event.seq), event.seq)
        order = sorted(latest, key=lambda material_id: (-latest[material_id], material_id))
        anchors = tuple(material_id for material_id in order if catalog[material_id].format == "course")
        topics: list[str] = []
        for material_id in order:
            topics.extend(t for t in catalog[material_id].topics if t not in topics)
        return cls(anchors=anchors, topics=tuple(topics))


@dataclass(frozen=True, slots=True)
class Context:
    """Всё, что нужно для оценки: профиль, разбор задачи, темы кандидатов, история, отключённые признаки.

    Поля пилота «похожие курсы» заполняет политика только при пустой задаче и персональном методе
    (ranking/policy.py): `pairs` и `anchors` включают вклад co_enrollment, `history_topics` — вклад
    history_topic. По умолчанию они пусты, и оценка совпадает с прежней.
    """

    profile: Profile
    parsed: ParsedTask
    topics: tuple[str, ...]
    history: HistoryIndex
    disabled: frozenset[str]
    catalog: dict[str, Material]
    pairs: CoursePairs | None = None
    anchors: tuple[str, ...] = ()
    history_topics: tuple[str, ...] = ()

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


@dataclass(frozen=True, slots=True)
class CoEnrollment:
    """Пара для фразы «похожие курсы»: курс истории с наибольшей долей, N общих слушателей из M слушателей курса."""

    anchor: str
    together: int
    total: int


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
    history_topic: str | None = None  # тема материала, которая есть у материалов истории
    co_enrollment: CoEnrollment | None = None

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
    for current, following in pairwise(items):
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
