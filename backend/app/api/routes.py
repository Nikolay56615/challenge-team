"""HTTP-слой: переводит запросы и ответы, правил подбора не содержит.

Состояние запроса: `request.state.request_id` назначает EdgeMiddleware в `main.py`, маршруты подбора
записывают `request.state.rank_ms` для заголовка Server-Timing. Схема строк журнала — в `main.py`.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections.abc import Mapping
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from .. import schemas, vocab
from ..catalog.coverage import link_allowed
from ..catalog.models import MATERIAL_ID_MAX_LENGTH, Catalog, HistoryEvent
from ..profiles.clients import Client, Clients
from ..ranking import explain, feed
from ..ranking.base import HistoryIndex, Profile
from ..ranking.policy import Outcome, eligible, recommend, topics_with_materials

log = logging.getLogger("app.api")
router = APIRouter(prefix="/api")

# Ответы с ошибкой в схеме OpenAPI: тот же конверт `{"error": {...}}`, что отдаёт problem_response. Без них FastAPI
# описывал 422 своей моделью HTTPValidationError с полем `detail`, которой сервис не отвечает, а 404, 413 и 503
# в схеме не было; из такой схемы интерфейс получил бы неверные типы ошибок.
# 405 и 500 не описаны: их нет в контракте операций.
USER_NOT_FOUND = "Клиента с таким кодом нет в подключённом журнале"
ERROR_DESCRIPTIONS = {
    404: "Не найдено: тестовые профили и клиенты выключены вне демо-режима, клиента с таким кодом нет, "
    "паспорт модели не записан (not_found)",
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


def _catalog(request: Request, name: str = "catalog") -> Catalog:
    """Каталог подбора по задаче или, по имени `feed_catalog`, каталог ленты по профилю."""
    catalog: Catalog | None = getattr(request.app.state, name, None)
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


@router.get("/users", response_model=schemas.UsersResponse, responses=_errors(404, 422))
def users(
    request: Request,
    q: Annotated[str, Query(max_length=MATERIAL_ID_MAX_LENGTH, pattern=r"^[A-Za-z0-9:_\-]*$")] = "",
    limit: Annotated[int, Query(ge=1, le=schemas.FEED_LIMIT)] = schemas.FEED_LIMIT,
) -> schemas.UsersResponse:
    """Клиенты подключённого журнала для ленты по профилю: список и поиск по началу кода."""
    clients: Clients = request.app.state.clients
    if not request.app.state.settings.demo_mode:
        raise ApiProblem(404, "not_found", "Клиенты доступны только в демо-режиме")
    found, matched = clients.search(q, limit)
    return schemas.UsersResponse(
        source=clients.source, total=len(clients), matched=matched, users=[_user(client) for client in found]
    )


@router.get("/model-card", response_model=schemas.ModelCardResponse, responses=_errors(404))
def model_card(request: Request) -> Response:
    """Паспорт модели ленты: качество на журнале записей, веса источников и свойства ленты."""
    card: schemas.ModelCardResponse | None = request.app.state.model_card
    if card is None:
        raise ApiProblem(404, "not_found", "Паспорт модели не записан")
    return _reference(card)


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


def _user(client: Client) -> schemas.UserOut:
    return schemas.UserOut(
        id=client.id, label=client.label, segment=client.segment, materials=client.materials, paid=client.paid
    )


def _feed_profile(body: schemas.FeedRequest, request: Request) -> tuple[Profile, Client | None]:
    """Профиль ленты: история из запроса или клиента с кодом, затем «что если» — убранные и добавленные события."""
    settings = request.app.state.settings
    if len(body.task) > settings.max_task_length:
        message = task_too_long_message(settings.max_task_length)
        raise ApiProblem(422, "validation_error", message, [{"field": "task", "message": message}])
    history: tuple[HistoryEvent, ...] = ()
    client: Client | None = None
    if body.history is not None:
        history = tuple(HistoryEvent(e.material_id, e.event, e.seq) for e in body.history)
    elif body.user_id is not None:
        client = request.app.state.clients.find(body.user_id)
        if client is None:
            raise ApiProblem(404, "not_found", USER_NOT_FOUND)
        history = client.history
    excluded = set(body.exclude_history)
    history = tuple(e for e in history if e.material_id not in excluded)
    # Добавленные события идут после последнего события истории: порядок задаёт сервер, а не экран
    last = max((e.seq for e in history), default=0) + 1
    history += tuple(HistoryEvent(e.material_id, e.event, last + e.seq) for e in body.add_history)
    # Анкета клиента из файла профилей действует, пока запрос не задал поле сам
    profile = Profile(
        task=body.task,
        stage=body.stage or getattr(client, "stage", None),
        experience=body.experience or getattr(client, "experience", None),
        format_pref=body.format_pref or getattr(client, "format_pref", None),
        industry=body.industry or getattr(client, "industry", None),
        history=history,
        limit=body.limit,
    )
    return profile, client


def _feed_message(result: feed.Feed, profile: Profile) -> str:
    """Строка состояния ленты: что задаёт порядок и сколько карточек показано."""
    shown, total = len(result.items), result.total_candidates
    materials = explain.plural(total, "материала", "материалов", "материалов")
    if result.status == "history":
        return f"Лента построена по истории. Показаны первые {shown} из {total} {materials}."
    # Без истории порядок задают ответы анкеты и задача, если они есть, иначе одна популярность
    answered = any((profile.task.strip(), profile.stage, profile.experience, profile.format_pref, profile.industry))
    lead = "Материалов из истории нет в каталоге" if result.history else "Истории нет"
    order = "порядок задают ответы анкеты и популярность" if answered else "первыми идут популярные материалы"
    return f"{lead}, поэтому {order}. Показаны первые {shown} из {total}."


def _feed_item(rank: int, entry: feed.FeedItem) -> schemas.FeedItemOut:
    scored, material = entry.scored, entry.scored.material
    allowed = link_allowed(material.url)
    return schemas.FeedItemOut(
        rank=rank,
        material_id=material.id,
        title=material.title,
        format=material.format,
        format_label=vocab.format_label(material.format),
        topic_labels=[vocab.topic_label(t) for t in material.topics],
        level_label=vocab.level_label(material.level),
        duration_minutes=material.duration_minutes,
        access=cast(schemas.AccessCode, material.access),
        access_label=vocab.ACCESS[material.access],
        is_paid=material.is_paid,
        short_benefit=material.short_benefit if material.is_paid else None,
        url=material.url if allowed else None,
        link_allowed=allowed,
        next_step=explain.next_step(material),
        flags=[schemas.FlagOut(code=cast(schemas.FlagCode, f), label=vocab.FLAGS[f]) for f in scored.flags],
        score=round(scored.score, 2),
        parts=[
            schemas.FeedPart(
                source=cast(schemas.FeedSourceCode, p.source), label=feed.SOURCE_LABELS[p.source],
                value=round(p.value, 2), evidence=p.evidence, note=p.note,
            )
            for p in entry.parts
        ],
        reason=entry.reason,
    )


@router.post("/feed", response_model=schemas.FeedResponse, responses=_errors(404, 413, 422, 503))
def feed_endpoint(body: schemas.FeedRequest, request: Request) -> schemas.FeedResponse:
    """Лента по профилю: до 50 материалов по убыванию оценки с составом оценки по источникам."""
    started = time.perf_counter()
    catalog = _catalog(request, "feed_catalog")
    profile, client = _feed_profile(body, request)
    request_id = _request_id(request)
    ranking = time.perf_counter()
    result = feed.build_feed(catalog, profile, body.limit, body.price_weight)
    request.state.rank_ms = (time.perf_counter() - ranking) * 1000
    log.info(
        "feed id=%s method=personal status=%s candidates=%d items=%d ms=%.1f",
        request_id, result.status, result.total_candidates, len(result.items), (time.perf_counter() - started) * 1000,
    )
    return schemas.FeedResponse(
        request_id=request_id,
        catalog=_catalog_info(catalog),
        user=_user(client) if client else None,
        status=cast(Literal["history", "cold"], result.status),
        message=_feed_message(result, profile),
        items=[_feed_item(i + 1, entry) for i, entry in enumerate(result.items)],
        total_candidates=result.total_candidates,
        history=[
            schemas.FeedHistoryOut(
                material_id=e.material_id, title=e.title,
                format_label=vocab.format_label(e.format) if e.format else None,
                event=cast(schemas.EventCode, e.event), event_label=feed.EVENT_LABELS[e.event],
            )
            for e in result.history
        ],
        interests=[schemas.FeedShare(label=label, share=share) for label, share in result.interests],
        facts=[schemas.FeedFact(name=name, value=value, origin=origin) for name, value, origin in result.facts],
        sources=[
            schemas.FeedSourceShare(
                source=cast(schemas.FeedSourceCode, code), label=feed.SOURCE_LABELS[code], share=share
            )
            for code, share in result.sources
        ],
    )


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
