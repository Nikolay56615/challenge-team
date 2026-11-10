"""Модели запроса и ответа API (PLAN.md, 4.4). Иных полей в ответе нет."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class HistoryEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_id: str = Field(min_length=1, max_length=MATERIAL_ID_MAX_LENGTH, pattern=MATERIAL_ID_PATTERN)
    event: EventCode
    seq: int = Field(ge=0, le=1_000_000_000)


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
    coverage: dict


class HealthResponse(BaseModel):
    status: Literal["ok"]
    catalog: HealthCatalog


class ErrorDetail(BaseModel):
    field: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = []


class ErrorResponse(BaseModel):
    error: ErrorBody
