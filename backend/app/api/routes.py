"""HTTP-слой: переводит запросы и ответы, правил подбора не содержит (docs/plan.md, 4.3–4.4).

Состояние запроса: `request.state.request_id` назначает EdgeMiddleware в `main.py`, маршруты подбора
записывают `request.state.rank_ms` для заголовка Server-Timing. Схема строк журнала — в `main.py`.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections.abc import Mapping
from typing import Literal, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from .. import schemas, vocab
from ..catalog.coverage import link_allowed
from ..catalog.models import Catalog, HistoryEvent
from ..ranking import explain
from ..ranking.base import HistoryIndex, Profile
from ..ranking.policy import Outcome, eligible, recommend, topics_with_materials

log = logging.getLogger("app.api")
router = APIRouter(prefix="/api")

# Ответы с ошибкой в схеме OpenAPI: тот же конверт `{"error": {...}}`, что отдаёт problem_response. Без них FastAPI
# описывал 422 своей моделью HTTPValidationError с полем `detail`, которой сервис не отвечает, а 404, 413 и 503
# в схеме не было; из такой схемы интерфейс получил бы неверные типы ошибок (кандидат W10).
# 405 и 500 не описаны: их нет в контракте операций.
ERROR_DESCRIPTIONS = {
    404: "Не найдено: тестовые профили выключены вне демо-режима (not_found)",
    413: "Тело запроса больше предела (payload_too_large)",
    422: "Неверный запрос: тело не JSON-объект, неизвестное поле, значение вне схемы или задача длиннее предела "
    "(validation_error)",
    503: "Каталог не загружен (catalog_unavailable)",
}


def _errors(*statuses: int) -> dict[int | str, dict[str, object]]:
    return {status: {"model": schemas.ErrorResponse, "description": ERROR_DESCRIPTIONS[status]} for status in statuses}


class ApiProblem(Exception):
    """Ошибка с кодом и сообщением для единого формата ответа."""

    def __init__(self, status: int, code: str, message: str, details: list[dict[str, str]] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or []


def problem_response(problem: ApiProblem, headers: Mapping[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content={"error": {"code": problem.code, "message": problem.message, "details": problem.details}},
        headers=headers,
    )


def task_too_long_message(limit: int) -> str:
    """«Запрос длиннее 21 символа», «… 22 символов»: после «длиннее» — родительный падеж."""
    return f"Запрос длиннее {limit} {explain.plural(limit, 'символа', 'символов', 'символов')}"


class ProbeResponse(BaseModel):
    """Ответ /api/live и /api/ready: только статус, без сведений о каталоге."""

    status: Literal["ok"]


def _request_id(request: Request) -> str:
    """Код запроса из EdgeMiddleware: тот же в заголовке X-Request-Id и в строках журнала."""
    return getattr(request.state, "request_id", None) or uuid.uuid4().hex


def _reference(model: BaseModel) -> Response:
    """Справочник: сильный ETag по телу и `no-cache` — браузер хранит копию и каждый раз сверяет её.

    Тело сериализуется так же, как FastAPI сериализует `response_model`. Совпавший If-None-Match
    превращает ответ в 304 в ConditionalGetMiddleware, после сжатия.
    """
    body = model.model_dump_json().encode()
    etag = f'"{hashlib.sha256(body).hexdigest()}"'
    return Response(body, media_type="application/json", headers={"ETag": etag, "Cache-Control": "no-cache"})


def _catalog(request: Request) -> Catalog:
    catalog: Catalog | None = getattr(request.app.state, "catalog", None)
    if catalog is None:
        raise ApiProblem(503, "catalog_unavailable", "Каталог не загружен. Повторите запрос позже.")
    return catalog


def _catalog_info(catalog: Catalog) -> schemas.CatalogInfo:
    return schemas.CatalogInfo(
        source=catalog.source,
        version=catalog.version,
        size=catalog.size,
        disabled_features=list(catalog.disabled_features),
    )


def _profile_from_request(body: schemas.RecommendRequest, request: Request) -> Profile:
    settings = request.app.state.settings
    task = body.task or ""
    if len(task) > settings.max_task_length:
        message = task_too_long_message(settings.max_task_length)
        raise ApiProblem(422, "validation_error", message, [{"field": "task", "message": message}])
    history: tuple[HistoryEvent, ...] = ()
    if body.history is not None:
        history = tuple(HistoryEvent(e.material_id, e.event, e.seq) for e in body.history)
    elif settings.demo_mode and body.profile_id:
        demo = request.app.state.profiles.get(body.profile_id)
        if demo is not None:
            history = demo.history
    return Profile(
        task=task,
        stage=body.stage,
        experience=body.experience,
        format_pref=body.format_pref,
        industry=body.industry,
        topic=body.topic,
        history=history,
        limit=body.limit,
    )


def _item(rank: int, outcome: Outcome, index: int) -> schemas.ItemOut:
    scored = outcome.items[index]
    material = scored.material
    allowed = link_allowed(material.url)
    return schemas.ItemOut(
        rank=rank,
        material_id=material.id,
        title=material.title,
        format=material.format,
        format_label=vocab.format_label(material.format),
        topics=list(material.topics),
        topic_labels=[vocab.topic_label(t) for t in material.topics],
        signals=[schemas.SignalOut(code=c, label=vocab.signal_label(c)) for c, _ in material.signals],
        level=material.level,
        level_label=vocab.level_label(material.level),
        industries=list(material.industries),
        duration_minutes=material.duration_minutes,
        # Коды ядро хранит строками; cast только для mypy: pydantic сверяет значение с Literal при создании модели
        access=cast(schemas.AccessCode, material.access),
        access_label=vocab.ACCESS[material.access],
        is_paid=material.is_paid,
        short_benefit=material.short_benefit if material.is_paid else None,
        url=material.url if allowed else None,
        link_allowed=allowed,
        reasons=outcome.reasons[index],
        next_step=explain.next_step(material),
        flags=[schemas.FlagOut(code=cast(schemas.FlagCode, f), label=vocab.FLAGS[f]) for f in scored.flags],
        score=round(scored.score, 2),
        contributions={k: round(v, 2) for k, v in scored.contributions.items()},
    )


def _response(outcome: Outcome, catalog: Catalog, request_id: str) -> schemas.RecommendResponse:
    clarification = None
    if outcome.clarification:
        clarification = schemas.Clarification(
            question=outcome.clarification["question"],
            text=outcome.clarification["text"],
            options=[schemas.Option(**o) for o in outcome.clarification["options"]],
        )
    route = None
    if outcome.route:
        route = schemas.Route(
            title=explain.ROUTE_TITLE,
            steps=[schemas.RouteStep(material_id=m.id, title=m.title) for m in outcome.route],
        )
    return schemas.RecommendResponse(
        request_id=request_id,
        method=cast(schemas.MethodCode, outcome.method),
        catalog=_catalog_info(catalog),
        status=cast(schemas.StatusCode, outcome.status),
        detected_topics=list(outcome.detected_topics),
        message=outcome.message,
        clarification=clarification,
        items=[_item(i + 1, outcome, i) for i in range(len(outcome.items))],
        route=route,
        total_candidates=outcome.total_candidates,
    )


def _log(request_id: str, kind: str, outcome: Outcome, started: float) -> None:
    log.info(
        "%s id=%s method=%s status=%s candidates=%d items=%d ms=%.1f",
        kind,
        request_id,
        outcome.method,
        outcome.status,
        outcome.total_candidates,
        len(outcome.items),
        (time.perf_counter() - started) * 1000,
    )


@router.get("/health", response_model=schemas.HealthResponse, responses=_errors(503))
def health(request: Request) -> schemas.HealthResponse:
    catalog = _catalog(request)
    info = _catalog_info(catalog)
    return schemas.HealthResponse(
        status="ok", catalog=schemas.HealthCatalog(**info.model_dump(), coverage=catalog.coverage)
    )


@router.get("/live", response_model=ProbeResponse)
def live() -> ProbeResponse:
    """Живость: процесс отвечает. Каталог не проверяется — перезапуск не загрузит его.

    Обычная функция, как у маршрутов подбора: она выполняется в том же пуле потоков, и зависший пул виден здесь.
    """
    return ProbeResponse(status="ok")


@router.get("/ready", response_model=ProbeResponse, responses=_errors(503))
def ready(request: Request) -> ProbeResponse:
    """Готовность: каталог загружен и подбор возможен, иначе 503 `catalog_unavailable`."""
    _catalog(request)
    return ProbeResponse(status="ok")


@router.get("/meta", response_model=schemas.MetaResponse, responses=_errors(503))
def meta(request: Request) -> Response:
    catalog = _catalog(request)
    settings = request.app.state.settings
    topics = topics_with_materials(eligible(catalog, HistoryIndex.build(())))
    body = schemas.MetaResponse(
        topics=[schemas.Option(label=vocab.topic_label(t), value=t) for t in topics],
        stages=[schemas.Option(label=label, value=code) for code, (label, _) in vocab.STAGES.items()],
        experience=[schemas.Option(label=label, value=code) for code, (label, _) in vocab.EXPERIENCE.items()],
        formats=[schemas.Option(label=label, value=code) for code, (label, _) in vocab.FORMAT_PREFS.items()],
        industries=[schemas.Option(label=label, value=code) for code, (label, _) in vocab.INDUSTRIES.items()],
        max_task_length=settings.max_task_length,
        demo_mode=settings.demo_mode,
    )
    return _reference(body)


@router.get("/profiles", response_model=schemas.ProfilesResponse, responses=_errors(404))
def profiles(request: Request) -> Response:
    if not request.app.state.settings.demo_mode:
        raise ApiProblem(404, "not_found", "Тестовые профили доступны только в демо-режиме")
    body = schemas.ProfilesResponse(
        profiles=[
            schemas.ProfileOut(
                id=p.id,
                label=p.label,
                description=p.description,
                task=p.task,
                stage=p.stage,
                experience=p.experience,
                format_pref=p.format_pref,
                industry=p.industry,
                history=[
                    schemas.HistoryEventOut(material_id=e.material_id, event=e.event, seq=e.seq) for e in p.history
                ],
            )
            for p in request.app.state.profiles.values()
        ]
    )
    return _reference(body)


@router.post("/recommend", response_model=schemas.RecommendResponse, responses=_errors(413, 422, 503))
def recommend_endpoint(body: schemas.RecommendRequest, request: Request) -> schemas.RecommendResponse:
    started = time.perf_counter()
    catalog = _catalog(request)
    profile = _profile_from_request(body, request)
    request_id = _request_id(request)
    ranking = time.perf_counter()
    outcome = recommend(catalog, profile, body.method)
    request.state.rank_ms = (time.perf_counter() - ranking) * 1000
    _log(request_id, "recommend", outcome, started)
    return _response(outcome, catalog, request_id)


@router.post("/compare", response_model=schemas.CompareResponse, responses=_errors(413, 422, 503))
def compare_endpoint(body: schemas.RecommendRequest, request: Request) -> schemas.CompareResponse:
    started = time.perf_counter()
    catalog = _catalog(request)
    profile = _profile_from_request(body, request)
    request_id = _request_id(request)
    ranking = time.perf_counter()
    base = recommend(catalog, profile, "baseline")
    personal = recommend(catalog, profile, "personal")
    request.state.rank_ms = (time.perf_counter() - ranking) * 1000
    compared = min(len(base.items), len(personal.items))
    changed = sum(1 for i in range(compared) if base.items[i].material.id != personal.items[i].material.id)
    _log(request_id, "compare", personal, started)
    return schemas.CompareResponse(
        baseline=_response(base, catalog, request_id),
        personal=_response(personal, catalog, request_id),
        diff=schemas.CompareDiff(changed_positions=changed, compared_positions=compared),
    )
