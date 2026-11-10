"""Приложение FastAPI: API, раздача собранного фронтенда, единый формат ошибок (PLAN.md, 4.3–4.6)."""

from __future__ import annotations

import logging
import os
import re
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette._utils import get_route_path  # путь без root_path; так же сопоставляют пути Mount и роутер FastAPI
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match, Mount
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .api.routes import ApiProblem, problem_response, router, task_too_long_message
from .catalog.loader import load_catalog
from .catalog.models import CatalogError
from .config import Settings, load_settings
from .profiles.synthetic import load_profiles

log = logging.getLogger("app")

FIELD_NAMES = {
    "task": "задача",
    "stage": "стадия",
    "experience": "опыт",
    "format_pref": "формат",
    "industry": "сфера",
    "topic": "тема",
    "history": "история",
    "profile_id": "профиль",
    "limit": "число материалов",
    "method": "метод",
}

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
# Swagger UI и ReDoc грузят скрипты с CDN, поэтому их страницы отдаются без CSP. Сравнение только
# точное: по префиксу без CSP открывалась бы и страница приложения по адресу /docs%2f..%2findex.html.
DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})
SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"}

# Самый большой допустимый запрос — задача на 2000 символов и 200 событий истории — меньше 40 КБ
MAX_BODY_BYTES = 64 * 1024
MAX_ERROR_DETAILS = 10
INVALID_JSON = "Тело запроса не является корректным JSON"
BODY_NOT_OBJECT = "Тело запроса должно быть JSON-объектом с заголовком Content-Type: application/json"
# Так FastAPI сообщает о теле, которое не удалось разобрать как JSON: не UTF-8, слишком глубокая
# вложенность, число длиннее 4300 цифр. Для клиента это та же ошибка, что и синтаксис JSON.
FASTAPI_BODY_ERROR = "There was an error parsing the body"
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _printable(path: str, limit: int = 200) -> str:
    """Путь для журнала: управляющие символы экранированы, чтобы не подделать строку журнала."""
    path = _CONTROL_CHARS.sub(lambda m: f"\\x{ord(m.group()):02x}", path)
    return path if len(path) <= limit else path[:limit] + "…"


def _log_unhandled(exc: BaseException, path: str) -> None:
    # Текст исключения и трассировка могут содержать данные запроса, поэтому они пишутся только на DEBUG
    log.error("unhandled error: %s path=%s", type(exc).__name__, _printable(path))
    log.debug("unhandled error traceback", exc_info=exc)


def _internal_error() -> JSONResponse:
    return problem_response(ApiProblem(500, "internal_error", "Внутренняя ошибка сервиса"))


class EdgeMiddleware:
    """Самый внешний слой, снаружи обработчика 500 из Starlette.

    Добавляет заголовки безопасности к каждому ответу, включая 500, и пишет строку журнала
    со статусом для путей /api и для любых ответов 5xx.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        route_path = get_route_path(scope)
        started = time.perf_counter()
        status = 0

        async def send_with_headers(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", [])
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                if route_path not in DOCS_PATHS:
                    headers.setdefault("Content-Security-Policy", CSP)
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception as exc:
            # Обработчик 500 уже ответил и записал ошибку, а Starlette пробрасывает исключение дальше.
            # Здесь оно останавливается: иначе сервер записал бы трассировку второй раз.
            if not status:
                _log_unhandled(exc, path)
                await _internal_error()(scope, receive, send_with_headers)
        finally:
            if status and (route_path.startswith("/api/") or status >= 500):
                log.info(
                    "http %s %s status=%d ms=%.1f",
                    scope.get("method", ""),
                    _printable(path),
                    status,
                    (time.perf_counter() - started) * 1000,
                )


class BodyLimitMiddleware:
    """Отклоняет тело больше `max_bytes` до разбора JSON.

    Заявленный Content-Length проверяется сразу, без чтения тела. Тело без этого заголовка
    (chunked) читается не дальше предела. Принятое тело передаётся приложению одним сообщением.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if self._declared_length(scope) > self.max_bytes:
            await self._reject(scope, receive, send)
            return
        chunks: list[bytes] = []
        size = 0
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] != "http.request":
                return  # клиент отключился, не дослав тело: отвечать некому
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_bytes:
                await self._reject(scope, receive, send)
                return
            chunks.append(chunk)
            more_body = message.get("more_body", False)
        body = b"".join(chunks)
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay, send)

    @staticmethod
    def _declared_length(scope: Scope) -> int:
        try:
            return int(Headers(scope=scope).get("content-length") or 0)
        except ValueError:
            return 0

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        problem = ApiProblem(413, "payload_too_large", f"Тело запроса больше {self.max_bytes // 1024} КБ")
        # Без Connection: close: uvicorn сам дочитает и отбросит остаток тела по заявленной длине,
        # и клиент, который ещё отправляет тело, получит ответ 413. Если закрыть сокет
        # с непрочитанными данными, клиенту уходит RST и ответ 413 может до него не дойти.
        await problem_response(problem)(scope, receive, send)


class FrontendFiles(StaticFiles):
    """Файлы интерфейса: путь, недопустимый для файловой системы, даёт 404, а не 500.

    В Windows символы < > " | * ? в пути дают OSError (WinError 123), а Starlette превращает
    в 404 только FileNotFoundError и NotADirectoryError. PermissionError Starlette обрабатывает сам.
    """

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        try:
            return super().lookup_path(path)
        except PermissionError:
            raise
        except OSError:
            return "", None


class FrontendMount(Mount):
    """Интерфейс на `/` без путей API.

    Mount на `/` совпадает с любым путём полностью и выигрывал бы у маршрута API, где совпал только
    путь, но не метод. Пути /api разбирает только API: 405 с заголовком Allow и JSON 404 — как без фронтенда.
    """

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        route_path = get_route_path(scope)
        if route_path == "/api" or route_path.startswith("/api/"):
            return Match.NONE, {}
        return super().matches(scope)


class Service(FastAPI):
    def build_middleware_stack(self) -> ASGIApp:
        return EdgeMiddleware(super().build_middleware_stack())


def _validation_details(exc: RequestValidationError, settings: Settings) -> list[dict]:
    details: list[dict] = []
    for error in exc.errors()[:MAX_ERROR_DETAILS]:
        kind = error.get("type", "")
        loc = [str(part) for part in error.get("loc", ())]
        if loc[:1] == ["body"]:
            loc = loc[1:]
        if kind == "json_invalid":
            details.append({"field": "body", "message": INVALID_JSON})
            continue
        if not loc:
            # Тело целиком: не объект JSON, пустое или отправлено без Content-Type: application/json
            details.append({"field": "body", "message": BODY_NOT_OBJECT})
            continue
        field = ".".join(loc)
        root = loc[0]
        name = FIELD_NAMES.get(root, field)
        if root == "task" and kind == "string_too_long":
            message = task_too_long_message(settings.max_task_length)
        elif root == "history" and kind == "too_long":
            message = "История длиннее 200 событий"
        elif root == "limit":
            message = "Число материалов должно быть от 1 до 10"
        elif kind == "extra_forbidden":
            message = f"Неизвестное поле «{field}»"
        elif kind in {"literal_error", "enum"}:
            message = f"Недопустимое значение поля «{name}»"
        elif kind == "missing":
            message = f"Не заполнено поле «{name}»"
        else:
            message = f"Неверное значение поля «{name}»"
        details.append({"field": field, "message": message})
    return details or [{"field": "body", "message": "Неверный запрос"}]


def _configure_logging(level_name: str) -> None:
    level = logging.getLevelNamesMapping()[level_name.upper()]
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Уровень задаётся и журналам uvicorn: при warning строки доступа и проверки здоровья не пишутся
    for name in ("app", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).setLevel(level)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    _configure_logging(settings.log_level)
    app = Service(
        title="Подбор учебных материалов",
        version="0.1.0",
        description="Прототип трека 1: персональный подбор и подбор по теме на одном каталоге.",
    )
    app.state.settings = settings
    app.state.catalog = None
    try:
        app.state.catalog = load_catalog(settings)
    except CatalogError as exc:
        log.error("catalog not loaded: %s", exc)
    app.state.profiles = load_profiles() if settings.demo_mode else {}

    @app.exception_handler(ApiProblem)
    async def _api_problem(_: Request, exc: ApiProblem) -> JSONResponse:
        return problem_response(exc)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = _validation_details(exc, settings)
        return problem_response(ApiProblem(422, "validation_error", details[0]["message"], details))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            problem = ApiProblem(404, "not_found", "Не найдено")
        elif exc.status_code == 405:
            problem = ApiProblem(405, "method_not_allowed", "Метод не поддерживается")
        elif exc.status_code == 400 and exc.detail == FASTAPI_BODY_ERROR:
            problem = ApiProblem(422, "validation_error", INVALID_JSON, [{"field": "body", "message": INVALID_JSON}])
        else:
            problem = ApiProblem(exc.status_code, "http_error", "Запрос не выполнен")
        # Заголовки исключения сохраняются: например, Allow у ответа 405
        return problem_response(problem, headers=exc.headers)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        _log_unhandled(exc, request.scope.get("path", ""))
        return _internal_error()

    app.add_middleware(BodyLimitMiddleware)
    app.include_router(router)

    dist = settings.frontend_dist
    if (dist / "index.html").is_file():
        app.router.routes.append(FrontendMount("/", app=FrontendFiles(directory=dist, html=True), name="frontend"))
    else:
        log.warning("frontend build not found; serving API only")

        @app.get("/", include_in_schema=False)
        def _no_frontend() -> JSONResponse:
            return JSONResponse(
                {"message": "Интерфейс не собран: выполните npm run build в папке frontend. API доступен на /docs."}
            )

    return app


app = create_app()
