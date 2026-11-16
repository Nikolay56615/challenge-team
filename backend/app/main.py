"""Приложение FastAPI: API, раздача собранного фронтенда, единый формат ошибок, заголовки и кеширование
(docs/plan.md, 4.3–4.6).

Слои снаружи внутрь: EdgeMiddleware → ConditionalGetMiddleware → GZipMiddleware → обработчик 500 Starlette →
BodyLimitMiddleware → обработчики ошибок → маршруты API и статика интерфейса.

Схема журнала. Строка обработчика — `<время> <уровень> <журнал> <сообщение>`; время по часам процесса,
в контейнере это UTC. Сообщения уровня INFO и выше, поля разделены одним пробелом и идут в таком порядке:

- журнал `app`, событие `http` — каждый запрос к /api и любой ответ 5xx:
  `http <метод> <путь> status=<код ответа> ms=<длительность> id=<код запроса> trace=<trace-id или ->`;
- журнал `app.api`, события `recommend` и `compare` — каждый выполненный подбор:
  `<событие> id=<код запроса> method=<метод> status=<статус выдачи> candidates=<число> items=<число> ms=<длительность>`;
- журнал `app`, уровень ERROR — непредвиденная ошибка: `unhandled error: <тип исключения> path=<путь>`;
- при запуске: `catalog loaded …` (`app.catalog`), `catalog not loaded: …` (ERROR), `frontend build not found …`.

Длительность — миллисекунды с одним знаком после точки. Код запроса совпадает с заголовком X-Request-Id
и полем `request_id` ответа подбора. trace-id берётся из допустимого заголовка traceparent, иначе `-`.
В методе и пути управляющие и невидимые символы, пробелы, разделители строк и обратная косая черта записаны
как `\\xNN` или `\\uNNNN`, поэтому строка не разрывается и поле не подделать; путь длиннее 200 символов усечён.
Текст задачи, значения полей профиля, коды материалов из истории, тела запросов и ответов, текст исключения
и трассировка на уровне INFO не пишутся; трассировка — только на DEBUG.

Метрики (кандидат W12). Только при METRICS_ENABLED: `GET /metrics` отдаёт текстовый формат Prometheus 0.0.4
со счётчиком `http_server_requests_total` и гистограммой `http_server_request_duration_seconds`. Имена, единица
и границы корзин 0,005–10 с взяты из семантических конвенций OpenTelemetry для HTTP-сервера, суффиксы `_total`
и `_seconds` — из правил именования Prometheus. Меток три, имена — атрибуты OpenTelemetry после перевода в формат
Prometheus:

- `http_route` — шаблон маршрута из таблицы маршрутов, а не путь запроса. Со сборкой интерфейса всё, что
  разбирает его статика, включая 404 на неизвестный путь вне /api, получает `/{path:path}`. Запрос без маршрута
  получает `none`: это неизвестный адрес /api/…, а без сборки и любой другой неизвестный адрес;
- `http_request_method` — метод из RFC 9110 или PATCH, любой другой — `_OTHER`;
- `http_response_status_code` — код ответа приложения, в том числе 304, 413 и 500.

Значения меток задаёт код: запрос не может создать новое значение метки, а число рядов ограничено произведением
шаблонов маршрутов, десяти значений метода и кодов ответа. Первый запрос с новым сочетанием, например
`DELETE /api/meta` с ответом 405, добавляет ряд из этого набора. Текст задачи и данные профиля в метрики
не попадают. Файлы интерфейса учитываются: их отдаёт тот же процесс и тот же цикл событий. Запросы, которые
разбирает маршрут /metrics, не учитываются: опрос раз в 15 с заслонил бы редкие запросы демо, а о каждом опросе
Prometheus сам записывает `up` и `scrape_duration_seconds`. Длительность — от входа запроса в EdgeMiddleware
до передачи серверу последней части ответа. Не учитываются ответы самого uvicorn (503 сверх предела соединений,
400 на испорченный HTTP) и запросы, на которые ответ не начат, например клиент отключился, не дослав тело.
Значения хранятся в памяти процесса и обнуляются при перезапуске. Без METRICS_ENABLED маршрута нет: /metrics
отвечает 404, как любой неизвестный путь, и счётчики не ведутся.
"""

from __future__ import annotations

import bisect
import logging
import mimetypes
import os
import re
import threading
import time
import unicodedata
import uuid
from collections.abc import Sequence
from email.utils import parsedate_to_datetime
from http import HTTPStatus
from pathlib import PurePath

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import RouteContext, iter_route_contexts
from fastapi.staticfiles import StaticFiles
from starlette._utils import get_route_path  # путь без root_path; так же сопоставляют пути Mount и роутер FastAPI
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import Response
from starlette.routing import BaseRoute, Match, Mount
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .api.routes import ApiProblem, problem_response, router, task_too_long_message
from .catalog.loader import load_catalog, load_feed_catalog
from .catalog.models import CatalogError
from .config import Settings, load_settings
from .model_card import load_model_card
from .profiles.clients import load_clients
from .profiles.synthetic import load_profiles

log = logging.getLogger("app")

# Типы файлов интерфейса задаются здесь для каждого расширения в сборке, а не берутся из системы. Python 3.12
# без /etc/mime.types не знает .woff2, и шрифт ушёл бы как text/plain, а GZip сжимал бы его повторно. В Windows
# типы читаются из реестра поверх встроенных, и для .js там бывает text/plain или application/x-javascript:
# браузер не выполнит модуль с text/plain, а к типу не из text/* Starlette не добавит charset=utf-8.
# Новое расширение в сборке добавьте сюда: test_edge.py сверяет словарь с файлами public/ и точками входа Vite
STATIC_TYPES = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".css": "text/css",
    ".txt": "text/plain",
    ".woff2": "font/woff2",
    ".jpg": "image/jpeg",
}
for _extension, _type in STATIC_TYPES.items():
    mimetypes.add_type(_type, _extension)

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

# Без 'unsafe-inline' в style-src: в сборке и исходниках нет атрибутов style и элементов <style> и <script>
# со встроенным кодом. Свойство style в React меняет стили через CSSOM, а CSP его не ограничивает.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "font-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
# Swagger UI и ReDoc грузят скрипты с CDN, поэтому их страницы отдаются без CSP. Сравнение только
# точное: по префиксу без CSP открывалась бы и страница приложения по адресу /docs%2f..%2findex.html.
DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})
# Возможности браузера, которые интерфейс не использует: запрещены странице и любым встроенным фреймам.
# Только имена, известные Chromium: о незнакомом имени браузер пишет в консоль ошибку разбора заголовка.
# web-share убран: Chrome Headless Shell 158, в котором браузерные проверки идут в CI, его не знает,
# и check:wcag ловил ошибку консоли (запуск из чистой копии 12 ноября 2026 года); Edge 157 имя знает.
DISABLED_FEATURES = (
    "accelerometer", "autoplay", "bluetooth", "camera", "display-capture", "encrypted-media", "fullscreen",
    "geolocation", "gyroscope", "hid", "idle-detection", "local-fonts", "magnetometer", "microphone", "midi",
    "payment", "picture-in-picture", "publickey-credentials-get", "screen-wake-lock", "serial", "usb",
    "xr-spatial-tracking",
)
PERMISSIONS_POLICY = ", ".join(f"{feature}=()" for feature in DISABLED_FEATURES)
# Одинаковы для всех ответов: HTML, статики, API, ошибок, 304. HSTS не ставится: TLS вне контейнера.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": PERMISSIONS_POLICY,
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

# Кеширование (RFC 9111, RFC 8246). Файлы в /assets/ Vite называет по хешу содержимого: новая сборка — новый адрес.
CACHE_IMMUTABLE = "public, max-age=31536000, immutable"
# HTML, справочники API с ETag, документация API: копию можно хранить, но перед использованием — сверить.
CACHE_REVALIDATE = "no-cache"
# Файлы из public/ (шрифты и их лицензия) копируются без хеша в имени и при обновлении меняются по тому же адресу.
# Час: за время показа они не перезапрашиваются, обновлённый файл дойдёт не позже чем через час, дальше ETag даёт 304.
CACHE_STATIC = "public, max-age=3600"
# Ответы API и ошибки не хранятся: выдача зависит от тела запроса, а ошибка не должна пережить исправление.
CACHE_NO_STORE = "no-store"
# Ответ меньше килобайта помещается в один пакет, сжатие не окупается. Уровень 6 вместо 9 по умолчанию:
# тело сжимается при каждом ответе, а выигрыш уровня 9 в размере — доли процента.
GZIP_MIN_BYTES = 1024
GZIP_LEVEL = 6

# Код запроса из заголовка X-Request-Id: без пробелов и управляющих символов, его можно писать в журнал как есть
REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
# W3C Trace Context: версия 00, trace-id из 32 и parent-id из 16 строчных шестнадцатеричных цифр, флаги
TRACEPARENT = re.compile(r"00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}")

# Заголовки, которые повторяет ответ 304 (RFC 9110, 15.4.5)
NOT_MODIFIED_HEADERS = frozenset({b"cache-control", b"content-location", b"date", b"etag", b"expires", b"vary"})
CONDITIONAL_HEADERS = frozenset({b"if-none-match", b"if-modified-since"})

# Самый большой допустимый запрос — задача на 2000 символов и 200 событий истории — меньше 40 КБ
MAX_BODY_BYTES = 64 * 1024
MAX_ERROR_DETAILS = 10
INVALID_JSON = "Тело запроса не является корректным JSON"
BODY_NOT_OBJECT = "Тело запроса должно быть JSON-объектом с заголовком Content-Type: application/json"
# Так FastAPI сообщает о теле, которое не удалось разобрать как JSON: не UTF-8, слишком глубокая
# вложенность, число длиннее 4300 цифр. Для клиента это та же ошибка, что и синтаксис JSON.
FASTAPI_BODY_ERROR = "There was an error parsing the body"

# Метрики HTTP (кандидат W12; схема — в начале модуля)
METRICS_PATH = "/metrics"
METRICS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
REQUESTS_TOTAL = "http_server_requests_total"
REQUEST_DURATION = "http_server_request_duration_seconds"
# Описания на английском, как в семантических конвенциях OpenTelemetry и в экспортёрах Prometheus
REQUESTS_HELP = "Number of HTTP server requests."
DURATION_HELP = "Duration of HTTP server requests."
# Границы корзин в секундах, рекомендованные OpenTelemetry для http.server.request.duration
DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0)
BUCKET_BOUNDS = (*(repr(bound) for bound in DURATION_BUCKETS), "+Inf")
METRIC_LABELS = ("http_route", "http_request_method", "http_response_status_code")
# Методы, которые OpenTelemetry знает по имени: RFC 9110 и PATCH. Прочие — _OTHER, чтобы метод не создавал ряды
KNOWN_METHODS = frozenset({"CONNECT", "DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT", "TRACE"})
OTHER_METHOD = "_OTHER"
# Маршрут не найден. Шаблоны начинаются с «/», поэтому значение не совпадёт ни с одним из них
NO_ROUTE = "none"
# Границы записи символа в журнале: \xNN до U+00FF, \uNNNN до U+FFFF, дальше \UNNNNNNNN
MAX_LATIN1 = 0xFF
MAX_BMP = 0xFFFF


def _escape(char: str) -> str:
    code = ord(char)
    return f"\\x{code:02x}" if code <= MAX_LATIN1 else f"\\u{code:04x}" if code <= MAX_BMP else f"\\U{code:08x}"


def _printable(value: str, limit: int = 200) -> str:
    """Значение для журнала одним полем: строку не разорвать и соседнее поле не подделать.

    Экранируются символы категорий Unicode C* (управляющие, невидимые форматирующие) и Z* (пробелы,
    разделители строк и абзацев), а также обратная косая черта: `\\x0a` в журнале — всегда экранированный символ.
    """
    text = "".join(_escape(c) if c == "\\" or unicodedata.category(c)[0] in "CZ" else c for c in value[:limit])
    return text if len(value) <= limit else text + "…"


def _is_api(route_path: str) -> bool:
    return route_path == "/api" or route_path.startswith("/api/")


def _request_id(headers: Headers) -> str:
    """Код запроса: входящий X-Request-Id, если заголовок один и допустим, иначе новый uuid4 в hex."""
    values = headers.getlist("x-request-id")
    if len(values) == 1 and REQUEST_ID.fullmatch(values[0]):
        return values[0]
    return uuid.uuid4().hex


def _trace_id(headers: Headers) -> str | None:
    """trace-id из заголовка traceparent версии 00; недопустимый заголовок не учитывается."""
    values = headers.getlist("traceparent")
    match = TRACEPARENT.fullmatch(values[0].strip(" \t")) if len(values) == 1 else None
    if match is None or match[1] == "0" * 32 or match[2] == "0" * 16:
        return None
    return match[1]


def _not_modified(headers: Headers, if_none_match: str | None, if_modified_since: str | None) -> bool:
    """Условие 304 для ответа с валидатором (RFC 9110, 13.1.2, 13.1.3, 13.2.2)."""
    if if_none_match is not None:
        # If-None-Match главнее If-Modified-Since; сравнение слабое, W/ не учитывается
        etag = headers.get("etag")
        if etag is None:
            return False
        tags = {tag.strip().removeprefix("W/") for tag in if_none_match.split(",")}
        return "*" in tags or etag.removeprefix("W/") in tags
    last_modified = headers.get("last-modified")
    if if_modified_since is None or last_modified is None:
        return False
    try:
        return parsedate_to_datetime(last_modified) <= parsedate_to_datetime(if_modified_since)
    except (TypeError, ValueError):  # недопустимая дата или дата без часового пояса
        return False


def _static_cache_control(path: str, file_name: str) -> str:
    if file_name.endswith(".html"):
        return CACHE_REVALIDATE
    if PurePath(path).parts[:1] == ("assets",):
        return CACHE_IMMUTABLE
    return CACHE_STATIC


def _log_unhandled(exc: BaseException, path: str) -> None:
    # Текст исключения и трассировка могут содержать данные запроса, поэтому они пишутся только на DEBUG
    log.error("unhandled error: %s path=%s", type(exc).__name__, _printable(path))
    log.debug("unhandled error traceback", exc_info=exc)


def _internal_error() -> JSONResponse:
    return problem_response(ApiProblem(500, "internal_error", "Внутренняя ошибка сервиса"))


def _metric_method(method: str) -> str:
    return method if method in KNOWN_METHODS else OTHER_METHOD


def _route_template(context: RouteContext) -> str:
    """Шаблон маршрута для метки: путь из таблицы маршрутов; у Mount — с хвостом `{path:path}`, как в Starlette."""
    if isinstance(context.original_route, Mount):
        return f"{context.path}/{{path:path}}"
    return context.path or NO_ROUTE


def _labels(key: tuple[str, str, str]) -> str:
    # Экранирование значения метки в текстовом формате Prometheus: обратная косая черта, кавычка, перевод строки
    escaped = (value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") for value in key)
    return ",".join(f'{name}="{value}"' for name, value in zip(METRIC_LABELS, escaped, strict=True))


class RouteTable:
    """Шаблоны маршрутов приложения для метки `http_route`.

    Совпадение ищется так же, как его ищет роутер: первое полное, иначе первое только по пути — такой маршрут
    ответит 405. Таблица строится из маршрутов приложения, а вложенные роутеры FastAPI разворачивает
    `iter_route_contexts`. Метка определяется до обработки, поэтому 413 из BodyLimitMiddleware и 500
    из EdgeMiddleware тоже получают шаблон маршрута, к которому шёл запрос.
    """

    def __init__(self, routes: Sequence[BaseRoute]) -> None:
        self.routes = [(context, _route_template(context)) for context in iter_route_contexts(routes)]

    def template(self, scope: Scope) -> str:
        partial = NO_ROUTE
        for context, template in self.routes:
            match, _ = context.matches(scope)
            if match is Match.FULL:
                return template
            if match is Match.PARTIAL and partial == NO_ROUTE:
                partial = template
        return partial


class _Series:
    __slots__ = ("buckets", "count", "total")

    def __init__(self) -> None:
        self.buckets = [0] * len(BUCKET_BOUNDS)  # наблюдения по корзинам без накопления, последняя — больше 10 с
        self.count = 0
        self.total = 0.0


class HttpMetrics:
    """Счётчик запросов и гистограмма длительности в памяти процесса; вывод — текстовый формат Prometheus 0.0.4.

    Ряд — сочетание шаблона маршрута, метода и кода ответа. Счётчик и гистограмма ряда меняются под одной
    блокировкой, поэтому запись из нескольких потоков не теряет наблюдений, значение счётчика всегда равно
    `_count` гистограммы, а вывод — согласованный снимок. Наблюдение попадает в корзину с наименьшей границей `le`,
    не меньшей длительности.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._series: dict[tuple[str, str, str], _Series] = {}

    def observe(self, route: str, method: str, status: int, seconds: float) -> None:
        key = (route, _metric_method(method), str(status))
        index = bisect.bisect_left(DURATION_BUCKETS, seconds)
        with self._lock:
            series = self._series.get(key)
            if series is None:
                series = self._series[key] = _Series()
            series.buckets[index] += 1
            series.count += 1
            series.total += seconds

    def render(self) -> str:
        with self._lock:
            snapshot = [(key, list(s.buckets), s.count, s.total) for key, s in self._series.items()]
        rows = [(_labels(key), buckets, count, total) for key, buckets, count, total in sorted(snapshot)]
        lines = [f"# HELP {REQUESTS_TOTAL} {REQUESTS_HELP}", f"# TYPE {REQUESTS_TOTAL} counter"]
        lines += [f"{REQUESTS_TOTAL}{{{labels}}} {count}" for labels, _, count, _ in rows]
        lines += [f"# HELP {REQUEST_DURATION} {DURATION_HELP}", f"# TYPE {REQUEST_DURATION} histogram"]
        for labels, buckets, count, total in rows:
            cumulative = 0
            for bound, observed in zip(BUCKET_BOUNDS, buckets, strict=True):
                cumulative += observed
                lines.append(f'{REQUEST_DURATION}_bucket{{{labels},le="{bound}"}} {cumulative}')
            lines.append(f"{REQUEST_DURATION}_sum{{{labels}}} {total!r}")
            lines.append(f"{REQUEST_DURATION}_count{{{labels}}} {count}")
        return "\n".join(lines) + "\n"


class EdgeMiddleware:
    """Самый внешний слой, снаружи обработчика 500 из Starlette.

    Назначает код запроса и кладёт его в `request.state.request_id`. К каждому ответу, включая 304, 413
    и 500, добавляет заголовки безопасности, X-Request-Id и Cache-Control, если его не задал внутренний слой:
    `no-store` для /api и ошибок, `no-cache` для прочего. К успешному ответу, для которого маршрут записал
    `request.state.rank_ms`, добавляет Server-Timing. Пишет строку журнала `http` (схема — в начале модуля).
    При переданных `metrics` и `routes` учитывает ответ в метриках HTTP, кроме опросов /metrics.
    """

    def __init__(self, app: ASGIApp, metrics: HttpMetrics | None = None, routes: RouteTable | None = None) -> None:
        self.app = app
        self.metrics = metrics
        self.routes = routes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        route_path = get_route_path(scope)
        api = _is_api(route_path)
        request_headers = Headers(scope=scope)
        request_id = _request_id(request_headers)
        trace_id = _trace_id(request_headers)
        # Шаблон — до обработки: роутер дополняет scope, а внутренние слои могут передать дальше его копию
        route = self.routes.template(scope) if self.metrics is not None and self.routes is not None else None
        # Своё состояние на каждый запрос: сервер может передать общий словарь состояния приложения
        state = scope["state"] = {**scope.get("state", {}), "request_id": request_id}
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
                error = status >= HTTPStatus.BAD_REQUEST
                headers.setdefault("Cache-Control", CACHE_NO_STORE if api or error else CACHE_REVALIDATE)
                headers["X-Request-Id"] = request_id
                rank_ms = state.get("rank_ms")
                if rank_ms is not None and not error:
                    total_ms = (time.perf_counter() - started) * 1000
                    headers["Server-Timing"] = f"rank;dur={rank_ms:.1f}, total;dur={total_ms:.1f}"
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
            elapsed = time.perf_counter() - started
            if status and (api or status >= HTTPStatus.INTERNAL_SERVER_ERROR):
                log.info(
                    "http %s %s status=%d ms=%.1f id=%s trace=%s",
                    _printable(scope.get("method", ""), 16),
                    _printable(path),
                    status,
                    elapsed * 1000,
                    request_id,
                    trace_id or "-",
                )
            if status and self.metrics is not None and route is not None and route != METRICS_PATH:
                self.metrics.observe(route, scope.get("method", ""), status, elapsed)


class ConditionalGetMiddleware:
    """Условные GET и HEAD по итоговому представлению, снаружи сжатия (RFC 9110, 13).

    Внутренние слои не видят If-None-Match и If-Modified-Since и всегда строят полный ответ, поэтому
    решение о 304 принимается по тем же байтам и заголовкам, что ушли бы клиенту. ETag сжатого ответа
    становится слабым: у сжатого и несжатого тела разные байты, а сильный ETag обещает побайтное совпадение
    (RFC 9110, 8.8.3.3). Совпавший If-None-Match или неустаревший If-Modified-Since заменяют ответ 200 на 304
    без тела с теми же ETag, Cache-Control и Vary. Валидаторы ставят только статика и справочники API.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_headers = Headers(scope=scope)
        if_none_match = ", ".join(request_headers.getlist("if-none-match")) or None
        if_modified_since = request_headers.get("if-modified-since")
        conditional = if_none_match is not None or if_modified_since is not None
        if conditional:
            scope = {**scope, "headers": [(k, v) for k, v in scope["headers"] if k.lower() not in CONDITIONAL_HEADERS]}
        conditional = conditional and scope.get("method") in ("GET", "HEAD")
        replaced = False

        async def send_conditional(message: Message) -> None:
            nonlocal replaced
            kind = message["type"]
            if kind == "http.response.start":
                message.setdefault("headers", [])
                headers = MutableHeaders(scope=message)
                etag = headers.get("etag")
                if etag and not etag.startswith("W/") and "content-encoding" in headers:
                    headers["etag"] = "W/" + etag
                if (
                    conditional
                    and message["status"] in (200, 206)
                    and _not_modified(headers, if_none_match, if_modified_since)
                ):
                    replaced = True
                    kept = [(k, v) for k, v in headers.raw if k.lower() in NOT_MODIFIED_HEADERS]
                    message = {"type": kind, "status": 304, "headers": kept}
            elif replaced:
                if kind == "http.response.body" and message.get("more_body", False):
                    return
                if kind not in ("http.response.body", "http.response.pathsend"):
                    return
                message = {"type": "http.response.body", "body": b"", "more_body": False}
            await send(message)

        await self.app(scope, receive, send_conditional)


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
    """Файлы интерфейса: путь, недопустимый для файловой системы, даёт 404, а не 500; Cache-Control по типу файла.

    В Windows символы < > " | * ? в пути дают OSError (WinError 123), а Starlette превращает
    в 404 только FileNotFoundError и NotADirectoryError. PermissionError Starlette обрабатывает сам.
    Срок хранения: HTML — `no-cache`, файлы из /assets/ — год с `immutable`, прочие — час.
    """

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        try:
            return super().lookup_path(path)
        except PermissionError:
            raise
        except OSError:
            return "", None

    def file_response(
        self, full_path: str | os.PathLike[str], stat_result: os.stat_result, scope: Scope, status_code: int = 200
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        if status_code == HTTPStatus.OK:
            # Путь запроса после нормализации: /docs%2f..%2fassets%2fx.js тоже считается файлом из assets
            response.headers["Cache-Control"] = _static_cache_control(self.get_path(scope), os.fspath(full_path))
        return response


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
        # Сжатие внутри условных запросов: решение о 304 и слабый ETag — по уже сжатому ответу
        stack = super().build_middleware_stack()
        compressed = GZipMiddleware(stack, minimum_size=GZIP_MIN_BYTES, compresslevel=GZIP_LEVEL)
        # Стек строится при первом запросе, когда create_app уже добавил все маршруты, включая статику
        metrics: HttpMetrics | None = getattr(self.state, "metrics", None)
        routes = RouteTable(self.router.routes) if metrics is not None else None
        return EdgeMiddleware(ConditionalGetMiddleware(compressed), metrics=metrics, routes=routes)


def _validation_details(exc: RequestValidationError, settings: Settings) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
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
            # Длина задачи ограничена дважды. Схема OpenAPI объявляет жёсткий предел TASK_HARD_LIMIT = 2000
            # (maxLength) и от настроек не зависит, поэтому снимок схемы и типы интерфейса одни для любого
            # развёртывания. Рабочий предел MAX_TASK_LENGTH (по умолчанию 300, не больше 2000) публикует /api/meta,
            # а проверяет обработчик подбора с тем же ответом 422. Сообщение и здесь называет рабочий предел.
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


# Аргументы строки доступа uvicorn: адрес клиента, метод, путь со строкой запроса, версия HTTP, статус
_ACCESS_ARGS = 5
_ACCESS_PATH = 2


class _AccessWithoutQuery(logging.Filter):
    """Строка доступа uvicorn без строки запроса: в ней был бы код клиента из `GET /api/users?q=…`."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == _ACCESS_ARGS:
            target = args[_ACCESS_PATH]
            if isinstance(target, str):
                record.args = (*args[:_ACCESS_PATH], target.partition("?")[0], *args[_ACCESS_PATH + 1 :])
        return True


def _configure_logging(level_name: str) -> None:
    level = logging.getLevelNamesMapping()[level_name.upper()]
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Уровень задаётся и журналам uvicorn: при warning строки доступа и проверки здоровья не пишутся
    for name in ("app", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).setLevel(level)
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, _AccessWithoutQuery) for item in access.filters):
        access.addFilter(_AccessWithoutQuery())


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
    app.state.feed_catalog = None
    try:
        app.state.catalog = load_catalog(settings)
        app.state.feed_catalog = load_feed_catalog(settings, app.state.catalog)
    except CatalogError as exc:
        log.error("catalog not loaded: %s", exc)
    app.state.profiles = load_profiles(settings.demo_profiles_path) if settings.demo_mode else {}
    app.state.clients = load_clients(settings, app.state.feed_catalog, app.state.profiles)
    app.state.model_card = load_model_card()

    @app.exception_handler(ApiProblem)
    async def _api_problem(_: Request, exc: ApiProblem) -> JSONResponse:
        return problem_response(exc)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = _validation_details(exc, settings)
        return problem_response(ApiProblem(422, "validation_error", details[0]["message"], details))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == HTTPStatus.NOT_FOUND:
            problem = ApiProblem(404, "not_found", "Не найдено")
        elif exc.status_code == HTTPStatus.METHOD_NOT_ALLOWED:
            problem = ApiProblem(405, "method_not_allowed", "Метод не поддерживается")
        elif exc.status_code == HTTPStatus.BAD_REQUEST and exc.detail == FASTAPI_BODY_ERROR:
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

    # Без METRICS_ENABLED маршрута нет: /metrics отвечает 404, как любой неизвестный путь, и сбор не ведётся
    app.state.metrics = HttpMetrics() if settings.metrics_enabled else None
    if app.state.metrics is not None:
        metrics: HttpMetrics = app.state.metrics

        # async: опрос идёт в цикле событий и не ждёт пула потоков, занятого подбором, — насыщение видно в метриках
        @app.get(METRICS_PATH, include_in_schema=False)
        async def _metrics() -> Response:
            # Cache-Control как у API: снимок счётчиков устаревает сразу
            headers = {"Cache-Control": CACHE_NO_STORE}
            return Response(metrics.render(), media_type=METRICS_CONTENT_TYPE, headers=headers)

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
