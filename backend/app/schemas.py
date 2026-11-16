"""Модели запроса и ответа API (docs/plan.md, 4.4). Иных полей в ответе нет."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from .catalog.models import MATERIAL_ID_MAX_LENGTH, MATERIAL_ID_PATTERN

StageCode = Literal["idea", "start", "growth"]
ExperienceCode = Literal["none", "some", "experienced"]
FormatPrefCode = Literal["quick", "template", "course"]
IndustryCode = Literal[
    "horeca", "retail", "ecom", "services", "construction", "logistics", "b2b", "manufacturing", "wholesale", "b2g"
]
TopicCode = Literal[
    "taxes_law", "finance", "team", "operations", "marketing", "start", "strategy", "sales", "tech", "service",
    "stories", "abroad", "marketplaces",
]
EventCode = Literal["view", "start", "complete", "purchase"]
MethodCode = Literal["personal", "baseline"]
StatusCode = Literal["strong", "weak", "none", "cold", "empty"]
FlagCode = Literal["in_progress", "completed", "viewed"]
AccessCode = Literal["open", "subscription", "paid"]

# Жёсткий предел длины задачи на уровне схемы. Рабочий предел MAX_TASK_LENGTH проверяется в обработчике.
TASK_HARD_LIMIT = 2000
HISTORY_LIMIT = 200


def json_integer(value: object) -> object:
    """Целое по правилам JSON Schema, как его описывает OpenAPI: 8 и 8.0 — целые, строка "8" и true — нет.

    Без этой проверки pydantic приводил строку и логическое значение к целому, и запрос, который схема называет
    неверным, проходил: `"seq": false` давал 200. Строгий режим pydantic отклонял бы и 8.0, а схема называет 8.0
    целым (находки Schemathesis, кандидат W10). Дробное 8.5 отклоняет сам pydantic.
    """
    if isinstance(value, (bool, str)):
        raise PydanticCustomError("int_type", "Input should be a valid integer")
    return value


def json_number(value: object) -> object:
    """Число по правилам JSON Schema: строка и логическое значение числом не считаются, null допустим."""
    if isinstance(value, (bool, str)):
        raise PydanticCustomError("float_type", "Input should be a valid number")
    return value


class HistoryEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_id: str = Field(min_length=1, max_length=MATERIAL_ID_MAX_LENGTH, pattern=MATERIAL_ID_PATTERN)
    event: EventCode
    seq: int = Field(ge=0, le=1_000_000_000)

    _integers = field_validator("seq", mode="before")(json_integer)


class RecommendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(default="", max_length=TASK_HARD_LIMIT)
    stage: StageCode | None = None
    experience: ExperienceCode | None = None
    format_pref: FormatPrefCode | None = None
    industry: IndustryCode | None = None
    topic: TopicCode | None = None
    history: list[HistoryEventIn] | None = Field(default=None, max_length=HISTORY_LIMIT)
    profile_id: str | None = Field(default=None, max_length=16, pattern=r"^[A-Za-z0-9_\-]+$")
    limit: int = Field(default=5, ge=1, le=10)
    method: MethodCode = "personal"

    _integers = field_validator("limit", mode="before")(json_integer)


class Option(BaseModel):
    label: str
    value: str


class SignalOut(BaseModel):
    code: str
    label: str


class FlagOut(BaseModel):
    code: FlagCode
    label: str


class ItemOut(BaseModel):
    rank: int
    material_id: str
    title: str
    format: str
    format_label: str
    topics: list[str]
    topic_labels: list[str]
    signals: list[SignalOut]
    level: str | None
    level_label: str | None
    industries: list[str]
    duration_minutes: int | None
    access: AccessCode
    access_label: str
    is_paid: bool
    short_benefit: str | None
    url: str | None
    link_allowed: bool
    reasons: list[str]
    next_step: str
    flags: list[FlagOut]
    score: float
    contributions: dict[str, float]


class Clarification(BaseModel):
    question: str
    text: str
    field: Literal["topic"] = "topic"
    options: list[Option]


class RouteStep(BaseModel):
    material_id: str
    title: str


class Route(BaseModel):
    title: str
    steps: list[RouteStep]


class CatalogInfo(BaseModel):
    source: str
    version: str
    size: int
    disabled_features: list[str]


class RecommendResponse(BaseModel):
    request_id: str
    method: MethodCode
    catalog: CatalogInfo
    status: StatusCode
    detected_topics: list[str]
    message: str
    clarification: Clarification | None
    items: list[ItemOut]
    route: Route | None
    total_candidates: int


class CompareDiff(BaseModel):
    changed_positions: int
    compared_positions: int


class CompareResponse(BaseModel):
    baseline: RecommendResponse
    personal: RecommendResponse
    diff: CompareDiff


FeedSourceCode = Literal[
    "progress", "history", "content", "links", "task", "profile", "access", "popularity", "seen"
]
FEED_LIMIT = 50
_MATERIAL_ID = Field(min_length=1, max_length=MATERIAL_ID_MAX_LENGTH, pattern=MATERIAL_ID_PATTERN)


class FeedRequest(BaseModel):
    """Запрос ленты по профилю (docs/plan.md, раздел 13).

    История берётся из `history`, а без неё — у клиента с кодом `user_id` (`GET /api/users`). Затем «что если»:
    события материалов из `exclude_history` убираются, события `add_history` добавляются после последнего
    события истории, их `seq` задаёт порядок между собой.
    """

    model_config = ConfigDict(extra="forbid")

    task: str = Field(default="", max_length=TASK_HARD_LIMIT)
    stage: StageCode | None = None
    experience: ExperienceCode | None = None
    format_pref: FormatPrefCode | None = None
    industry: IndustryCode | None = None
    history: list[HistoryEventIn] | None = Field(default=None, max_length=HISTORY_LIMIT)
    user_id: Annotated[str, _MATERIAL_ID] | None = None
    exclude_history: list[Annotated[str, _MATERIAL_ID]] = Field(default_factory=list, max_length=HISTORY_LIMIT)
    add_history: list[HistoryEventIn] = Field(default_factory=list, max_length=HISTORY_LIMIT)
    limit: int = Field(default=20, ge=1, le=FEED_LIMIT)
    # Вес источника «доступ и цена»; без поля — вес по умолчанию из ranking/feed.py, ноль выключает учёт цены
    price_weight: float | None = Field(default=None, ge=0, le=1)

    _integers = field_validator("limit", mode="before")(json_integer)
    _numbers = field_validator("price_weight", mode="before")(json_number)


class FeedPart(BaseModel):
    source: FeedSourceCode
    label: str
    value: float
    evidence: str | None
    # Как считается вклад, если его считает модель, а свидетельство называет только запись с наибольшим весом
    note: str | None


class FeedItemOut(BaseModel):
    rank: int
    material_id: str
    title: str
    format: str
    format_label: str
    topic_labels: list[str]
    level_label: str | None
    duration_minutes: int | None
    access: AccessCode
    access_label: str
    is_paid: bool
    short_benefit: str | None
    url: str | None
    link_allowed: bool
    next_step: str
    flags: list[FlagOut]
    score: float
    parts: list[FeedPart]
    reason: str


class FeedHistoryOut(BaseModel):
    material_id: str
    title: str | None
    format_label: str | None
    event: EventCode
    event_label: str


class FeedShare(BaseModel):
    label: str
    share: float


class FeedSourceShare(FeedShare):
    source: FeedSourceCode


class FeedFact(BaseModel):
    """Поле профиля клиента с подписью происхождения: анкета, вывод из истории или «не указано»."""

    name: str
    value: str | None
    origin: str


class UserOut(BaseModel):
    """Клиент из подключённого журнала: код, подпись, сегмент и размер истории."""

    id: str
    label: str
    segment: str | None
    materials: int
    paid: bool


class UsersResponse(BaseModel):
    """Клиенты, код которых начинается с запроса: первые `limit` из `matched`; `total` — всего в журнале."""

    source: str
    total: int
    matched: int
    users: list[UserOut]


class FeedResponse(BaseModel):
    request_id: str
    catalog: CatalogInfo
    user: UserOut | None
    status: Literal["history", "cold"]
    message: str
    items: list[FeedItemOut]
    total_candidates: int
    history: list[FeedHistoryOut]
    interests: list[FeedShare]
    facts: list[FeedFact]
    sources: list[FeedSourceShare]


class ModelCardRow(BaseModel):
    """Метод на журнале записей: доля пользователей, у которых скрытый курс стоит первым и в первых пяти."""

    method: str
    label: str
    hit1: float
    hit5: float
    ndcg5: float


class ModelCardGroup(BaseModel):
    code: str
    label: str
    users: int
    rows: list[ModelCardRow]


class ModelCardValue(BaseModel):
    label: str
    value: float
    share: bool  # значение — доля от 0 до 1; иначе число или вес


class ModelCardResponse(BaseModel):
    """Паспорт модели ленты: тип данных проверки, качество по группам, веса источников и свойства ленты."""

    data: str
    groups: list[ModelCardGroup]
    weights: list[ModelCardValue]
    feed: list[ModelCardValue]


class MetaResponse(BaseModel):
    topics: list[Option]
    stages: list[Option]
    experience: list[Option]
    formats: list[Option]
    industries: list[Option]
    max_task_length: int
    demo_mode: bool


class HistoryEventOut(BaseModel):
    material_id: str
    event: EventCode
    seq: int


class ProfileOut(BaseModel):
    id: str
    label: str
    description: str
    task: str
    stage: StageCode | None
    experience: ExperienceCode | None
    format_pref: FormatPrefCode | None
    industry: IndustryCode | None
    history: list[HistoryEventOut]


class ProfilesResponse(BaseModel):
    profiles: list[ProfileOut]


class HealthCatalog(CatalogInfo):
    coverage: dict[str, Any]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    catalog: HealthCatalog


class ErrorDetail(BaseModel):
    field: str
    message: str


class ErrorBody(BaseModel):
    # Модель только описывает ответ в схеме; problem_response всегда отдаёт details, хотя бы пустым списком
    code: str
    message: str
    details: list[ErrorDetail]


class ErrorResponse(BaseModel):
    error: ErrorBody
