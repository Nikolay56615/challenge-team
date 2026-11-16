"""Среда выполнения: модуль запуска uvicorn и меры OWASP, которые видны в коде.

Меры OWASP API Security Top 10 (2023) по API4 «неограниченное потребление ресурсов» и API8 «ошибки конфигурации
безопасности» собраны в таблице CONTROLS. В строке — мера, файл, где она задана, проверка в pytest
(test_owasp_control) и шаги CI. Меры образа и контейнера — пользователь, пределы, контекст сборки, блокировки —
проверяет CI на собранном образе, текст Dockerfile, compose и workflow тесты не сверяют.

Живые проверки запускают `python -m app.serve` на свободном порту 127.0.0.1 и останавливают его
сигналом: SIGTERM в Linux и macOS, CTRL_BREAK в Windows.
"""

from __future__ import annotations

import http.client
import http.server
import inspect
import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
import uvicorn
import yaml
from fastapi import FastAPI
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app import main, serve
from app.api import routes
from app.config import BACKEND_DIR, load_settings

from .conftest import NO_FRONTEND, client_for, error_of

ROOT = BACKEND_DIR.parent
JSON = {"content-type": "application/json"}
MARKER = "секретный-маркер-исключения"
# Переменные приложения: живой сервер получает только те, что задаёт тест
APP_VARIABLES = (
    "CATALOG_SOURCE", "CATALOG_PATH", "CATALOG_SIGNALS_PATH", "CATALOG_MAPPING", "CATALOG_PAIRS_PATH",
    "PAIRS_MIN_SUPPORT", "DEMO_MODE", "DEMO_PROFILES_PATH", "MAX_TASK_LENGTH",
    "METRICS_ENABLED", "LOG_LEVEL", "FRONTEND_DIST",
)
CONTAINER_OPTIONS = {
    "host": "0.0.0.0",
    "port": 8000,
    "log_level": "info",
    "limit_concurrency": 64,
    "timeout_keep_alive": 5,
    "timeout_graceful_shutdown": 10,
    "server_header": False,
    "proxy_headers": False,
}


# Чтение Dockerfile, compose и .dockerignore


def dockerfile_instructions(all_stages: bool = False) -> list[tuple[str, str]]:
    """Инструкции Dockerfile как (имя, аргументы) без комментариев, строки с `\\` склеены.

    По умолчанию — только последняя, рабочая стадия.
    """
    instructions: list[tuple[str, str]] = []
    pending = ""
    for line in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not pending and (not stripped or stripped.startswith("#")):
            continue
        if stripped.endswith("\\"):
            pending += stripped[:-1] + " "
            continue
        name, _, args = (pending + stripped).partition(" ")
        pending = ""
        if name.upper() == "FROM" and not all_stages:
            instructions.clear()
        instructions.append((name.upper(), args.strip()))
    return instructions


def instruction(name: str) -> str:
    found = [args for kind, args in dockerfile_instructions() if kind == name]
    assert len(found) == 1, f"{name}: {len(found)} в рабочей стадии"
    return found[0]


def container_command() -> list[str]:
    return json.loads(instruction("CMD"))


def service(name: str = "compose.yaml") -> dict:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))["services"]["app"]


def seconds(duration: str) -> float:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m)", str(duration))
    assert match, duration
    return float(match[1]) * {"ms": 0.001, "s": 1, "m": 60}[match[2]]


def ignore_patterns() -> list[re.Pattern[str]]:
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    return [_compile(line.strip()) for line in lines if line.strip() and not line.lstrip().startswith("#")]


def _compile(pattern: str) -> re.Pattern[str]:
    """Шаблон .dockerignore по правилам moby/patternmatcher: `**/` — любые папки, `*` и `?` — внутри одного имени.

    Исключения `!` и классы `[...]` не поддержаны: в .dockerignore их нет, иначе разбор был бы неверен.
    """
    assert not pattern.startswith("!") and "[" not in pattern and "\\" not in pattern, pattern
    pattern = pattern.strip("/")
    regex, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            i += 2 + pattern.startswith("/", i + 2)
            regex += ".*" if i >= len(pattern) else "(?:.*/)?"
        elif pattern[i] == "*":
            regex, i = regex + "[^/]*", i + 1
        elif pattern[i] == "?":
            regex, i = regex + "[^/]", i + 1
        else:
            regex, i = regex + re.escape(pattern[i]), i + 1
    return re.compile(regex)


def ignored(path: str, patterns: list[re.Pattern[str]]) -> bool:
    """Путь исключён, если шаблон совпал с ним или с одной из папок над ним, как в Docker."""
    parts = path.split("/")
    return any(p.fullmatch("/".join(parts[:n])) for n in range(1, len(parts) + 1) for p in patterns)


def build_context() -> list[str]:
    """Файлы, которые Docker отправит в контекст сборки из этого дерева; исключённые папки не обходятся."""
    patterns = ignore_patterns()
    kept: list[str] = []
    for directory, dirs, files in os.walk(ROOT):
        relative = Path(directory).relative_to(ROOT).as_posix()
        prefix = "" if relative == "." else relative + "/"
        dirs[:] = sorted(d for d in dirs if not ignored(prefix + d, patterns))
        kept.extend(prefix + f for f in sorted(files) if not ignored(prefix + f, patterns))
    return kept


# Тесты, кеши, зависимости и результаты сборки, локальные настройки, закрытые и локальные данные, служебные папки,
# результаты шагов CI: мутационное тестирование, аудит и SBOM, Lighthouse, копия mutmut; документация комплекта


# Живой сервер


@dataclass
class LiveServer:
    port: int
    process: subprocess.Popen
    log: Path

    def connect(self) -> socket.socket:
        return socket.create_connection(("127.0.0.1", self.port), timeout=10)

    def get(self, path: str) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
        finally:
            connection.close()

    def get_until(self, status: int, timeout: float = 10) -> tuple[int, dict[str, str], bytes]:
        """GET /api/live по новому соединению, пока не придёт `status`: сервер принимает соединения не сразу."""
        deadline = time.monotonic() + timeout
        while True:
            result = self.get("/api/live")
            if result[0] == status or time.monotonic() > deadline:
                return result
            time.sleep(0.05)

    def output(self) -> str:
        return self.log.read_text(encoding="utf-8", errors="replace")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _interrupt(process: subprocess.Popen) -> None:
    """Сигнал корректной остановки, как от docker stop: SIGTERM, а в Windows — CTRL_BREAK группе процесса."""
    if sys.platform == "win32":
        os.kill(process.pid, signal.CTRL_BREAK_EVENT)
    else:
        process.send_signal(signal.SIGTERM)


def _kill(process: subprocess.Popen) -> None:
    if sys.platform == "win32":
        # python.exe из venv в Windows — запускающий процесс: дерево снимается целиком
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, check=False)
    else:
        process.kill()
    process.wait(timeout=10)


# uvicorn после корректной остановки снова поднимает полученный сигнал. Вне контейнера процесс завершается им:
# -15 в Linux и macOS, код 3 после CTRL_BREAK в Windows. В контейнере Python — PID 1, ядро такой сигнал
# не доставляет, и код выхода 0.
GRACEFUL_EXIT_CODES = {0, 3} if sys.platform == "win32" else {0, -signal.SIGTERM}


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    port = _free_port()
    log = tmp_path_factory.mktemp("serve") / "serve.log"
    env = {name: value for name, value in os.environ.items() if name not in APP_VARIABLES}
    # Уровень в смешанном регистре: модуль запуска приводит его к нижнему для приложения и uvicorn
    env.update({"LOG_LEVEL": "Warning", "FRONTEND_DIST": str(NO_FRONTEND), "PYTHONUTF8": "1"})
    # Условие отдельным if: проверку платформы в условном выражении mypy не учитывает, а в Linux такой
    # константы нет
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP
    with log.open("wb") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "app.serve", "--port", str(port)],
            cwd=BACKEND_DIR, env=env, stdout=output, stderr=subprocess.STDOUT, creationflags=flags,
        )
    server = LiveServer(port, process, log)
    deadline = time.monotonic() + 60
    while True:
        if process.poll() is not None:
            pytest.fail(f"сервер завершился с кодом {process.returncode}:\n{server.output()}")
        try:
            if server.get("/api/live")[0] == 200:
                break
        except OSError:
            pass
        if time.monotonic() > deadline:
            _kill(process)
            pytest.fail(f"сервер не ответил за 60 с:\n{server.output()}")
        time.sleep(0.1)
    yield server
    if process.poll() is None:
        try:
            _interrupt(process)
            process.wait(timeout=serve.TIMEOUT_GRACEFUL_SHUTDOWN + 5)
        except (OSError, subprocess.TimeoutExpired):
            _kill(process)


@pytest.fixture
def uvicorn_loggers():
    """uvicorn.Config меняет уровни своих журналов; после теста они возвращаются."""
    names = ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi")
    saved = {name: logging.getLogger(name).level for name in names}
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


def _boom(*args, **kwargs):
    raise RuntimeError(MARKER)


# Таблица OWASP API4 и API8: проверки строк


def check_body_limit(request: pytest.FixtureRequest) -> None:
    with client_for() as service_client:
        response = service_client.post("/api/recommend", content=b"{" + b" " * main.MAX_BODY_BYTES + b"}", headers=JSON)
    assert response.status_code == 413 and error_of(response)["code"] == "payload_too_large"


def check_input_sizes(request: pytest.FixtureRequest) -> None:
    cases = {
        "задача": {"task": "я" * 301},
        "история": {"history": [{"material_id": "M01", "event": "view", "seq": i} for i in range(201)]},
        "код материала": {"history": [{"material_id": "M" * 65, "event": "view", "seq": 1}]},
    }
    with client_for() as service_client:
        for name, body in cases.items():
            response = service_client.post("/api/recommend", json=body)
            assert response.status_code == 422 and error_of(response)["code"] == "validation_error", name
    with pytest.raises(ValueError, match="^MAX_TASK_LENGTH"):
        load_settings({"MAX_TASK_LENGTH": "2001"})


def check_page_size(request: pytest.FixtureRequest) -> None:
    with client_for() as service_client:
        assert [service_client.post("/api/recommend", json={"limit": n}).status_code for n in (0, 11)] == [422, 422]
        response = service_client.post("/api/recommend", json={"task": "маркетинг", "limit": 10})
    assert response.status_code == 200 and len(response.json()["items"]) <= 10


def check_concurrency_limit(request: pytest.FixtureRequest) -> None:
    assert serve.uvicorn_options({})["limit_concurrency"] == serve.LIMIT_CONCURRENCY == 64
    live = request.getfixturevalue("live_server")
    # uvicorn отвечает 503, если открытых соединений вместе с текущим не меньше предела: 62 простаивающих
    # и запрос — ещё 200, 63 и запрос — уже 503
    idle = [live.connect() for _ in range(serve.LIMIT_CONCURRENCY - 2)]
    try:
        assert live.get_until(200)[0] == 200
        idle.append(live.connect())
        status, headers, body = live.get_until(503)
        assert (status, body) == (503, b"Service Unavailable")
        assert "server" not in headers
    finally:
        for connection in idle:
            connection.close()
    assert live.get_until(200)[0] == 200


def check_timeouts(request: pytest.FixtureRequest) -> None:
    options = serve.uvicorn_options({})
    assert (options["timeout_keep_alive"], options["timeout_graceful_shutdown"]) == (5, 10)


def check_loopback_only(request: pytest.FixtureRequest) -> None:
    ports = service()["ports"]
    assert ports and all(str(port).startswith("127.0.0.1:") for port in ports)
    assert "ports" not in service("compose.data.yaml")
    assert serve.parse_args([]).host == "127.0.0.1"


NETWORK_CLIENTS = re.compile(
    r"^\s*(?:import|from)\s+(?:urllib\.request|http\.client|httpx|requests|aiohttp|socket|smtplib|ftplib)\b", re.M
)


def check_no_outbound_calls(request: pytest.FixtureRequest) -> None:
    sources = sorted((BACKEND_DIR / "app").rglob("*.py"))
    assert len(sources) > 10
    found = [p.relative_to(BACKEND_DIR).as_posix() for p in sources if NETWORK_CLIENTS.search(p.read_text("utf-8"))]
    assert found == []


def check_methods(request: pytest.FixtureRequest) -> None:
    with client_for() as service_client:
        for method in ("GET", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE"):
            response = service_client.request(method, "/api/recommend")
            assert (response.status_code, response.headers.get("allow")) == (405, "POST"), method
        probes = [
            ("HEAD", "/api/live"), ("HEAD", "/api/ready"), ("HEAD", "/api/health"), ("POST", "/api/meta"),
            ("TRACE", "/api/meta"), ("TRACE", "/api/live"),
        ]
        for method, path in probes:
            response = service_client.request(method, path)
            assert (response.status_code, response.headers.get("allow")) == (405, "GET"), (method, path)


def check_no_cors(request: pytest.FixtureRequest) -> None:
    origin = {"Origin": "https://foreign.example"}
    with client_for() as service_client:
        responses = [
            service_client.get("/api/meta", headers=origin),
            service_client.post("/api/recommend", json={"task": "налоги"}, headers=origin),
            service_client.options("/api/recommend", headers={**origin, "Access-Control-Request-Method": "POST"}),
        ]
    assert [r.status_code for r in responses] == [200, 200, 405]
    assert [name for r in responses for name in r.headers if name.lower().startswith("access-control-")] == []


def check_security_headers(request: pytest.FixtureRequest) -> None:
    expected = {**main.SECURITY_HEADERS, "Content-Security-Policy": main.CSP}
    with client_for() as service_client:
        responses = [
            service_client.get("/api/meta"),
            service_client.get("/api/nothing"),
            service_client.post("/api/recommend", json={"limit": 0}),
        ]
        request.getfixturevalue("monkeypatch").setattr(routes, "recommend", _boom)
        responses.append(service_client.post("/api/recommend", json={"task": "налоги"}))
    assert [r.status_code for r in responses] == [200, 404, 422, 500]
    for response in responses:
        assert {name: response.headers.get(name) for name in expected} == expected, response.status_code


def check_errors_without_details(request: pytest.FixtureRequest) -> None:
    request.getfixturevalue("monkeypatch").setattr(routes, "recommend", _boom)
    with client_for() as service_client:
        assert isinstance(service_client.app, FastAPI) and service_client.app.debug is False
        response = service_client.post("/api/recommend", json={"task": "налоги"})
    assert response.status_code == 500
    assert error_of(response) == {"code": "internal_error", "message": "Внутренняя ошибка сервиса", "details": []}
    assert MARKER not in response.text and "Traceback" not in response.text and "RuntimeError" not in response.text


def check_json_only(request: pytest.FixtureRequest) -> None:
    body = json.dumps({"task": "налоги"}).encode()
    with client_for() as service_client:
        response = service_client.post("/api/recommend", content=body, headers={"content-type": "text/plain"})
    assert response.status_code == 422 and error_of(response)["code"] == "validation_error"


def check_no_server_header(request: pytest.FixtureRequest) -> None:
    assert serve.uvicorn_options({})["server_header"] is False
    status, headers, _ = request.getfixturevalue("live_server").get("/api/ready")
    assert status == 200 and "server" not in headers
    assert headers["x-content-type-options"] == "nosniff" and "date" in headers


def check_proxy_headers_off(request: pytest.FixtureRequest) -> None:
    request.getfixturevalue("uvicorn_loggers")
    options = serve.uvicorn_options({})
    config = uvicorn.Config(serve.APP, log_config=None, **options)
    config.load()
    assert not isinstance(config.loaded_app, ProxyHeadersMiddleware) and config.loaded_app is main.app
    assert b"server" not in dict(config.encoded_headers)
    # Контроль: со значениями uvicorn по умолчанию появились бы и заголовок Server, и разбор X-Forwarded-*
    default = uvicorn.Config(serve.APP, log_config=None, **{**options, "server_header": True, "proxy_headers": True})
    default.load()
    assert isinstance(default.loaded_app, ProxyHeadersMiddleware) and b"server" in dict(default.encoded_headers)


@dataclass(frozen=True)
class Control:
    id: str
    measure: str
    where: str
    check: Callable[[pytest.FixtureRequest], None] | None
    ci: tuple[str, ...] = ()
    reason: str = ""


IN_CONTAINER = "проверяет CI на собранном образе и запущенном контейнере"

CONTROLS = (
    # API4 — неограниченное потребление ресурсов
    Control("API4.1", "Тело запроса до 64 КБ: больше — 413 до разбора JSON, в том числе без Content-Length",
            "backend/app/main.py", check_body_limit),
    Control("API4.2", "Задача до MAX_TASK_LENGTH, не больше 2000 символов; история до 200 событий; код материала "
            "до 64 символов", "backend/app/schemas.py, config.py", check_input_sizes),
    Control("API4.3", "Число материалов в ответе: limit от 1 до 10", "backend/app/schemas.py", check_page_size),
    Control("API4.4", "Предел 64 соединения вместе с соединением запроса: при 63 открытых соединениях следующий "
            "запрос сразу получает 503 от uvicorn",
            "backend/app/serve.py", check_concurrency_limit),
    Control("API4.5", "Keep-alive 5 с, корректное завершение до 10 с; Docker ждёт 15 с до SIGKILL",
            "backend/app/serve.py, compose.yaml", check_timeouts, ci=("Корректная остановка",)),
    Control("API4.6", "Память контейнера 512 МБ без подкачки, 1 CPU", "compose.yaml", None,
            ci=("Пределы контейнера",), reason=IN_CONTAINER),
    Control("API4.7", "Процессы и потоки до 128, файловые дескрипторы до 1024", "compose.yaml", None,
            ci=("Пределы контейнера",), reason=IN_CONTAINER),
    Control("API4.8", "Частота запросов не ограничена. Компенсирующая мера: порт опубликован только на 127.0.0.1, "
            "без Docker сервис слушает 127.0.0.1", "compose.yaml, backend/app/serve.py", check_loopback_only,
            reason="лимит частоты — решение пользователя при публичном развёртывании"),
    Control("API4.9", "Расходов на внешние сервисы нет: код сервера не импортирует сетевые клиенты",
            "backend/app/", check_no_outbound_calls),
    # API8 — ошибки конфигурации безопасности
    Control("API8.1", "Лишние методы отключены: 405 с заголовком Allow, в том числе на HEAD, OPTIONS и TRACE",
            "backend/app/api/routes.py", check_methods),
    Control("API8.2", "CORS не включён: нет Access-Control-* для чужого Origin и на preflight",
            "backend/app/main.py", check_no_cors),
    Control("API8.3", "Заголовки безопасности и CSP на ответах 200, 404, 422 и 500", "backend/app/main.py",
            check_security_headers, ci=("Заголовки ответа",)),
    Control("API8.4", "Ошибка 500 — только конверт error, без трассировки и текста исключения; отладка выключена",
            "backend/app/main.py", check_errors_without_details),
    Control("API8.5", "Принимается только JSON: тело с другим Content-Type — 422", "backend/app/main.py",
            check_json_only),
    Control("API8.6", "Сервер себя не называет: нет заголовка Server", "backend/app/serve.py",
            check_no_server_header, ci=("Заголовки ответа",)),
    Control("API8.7", "X-Forwarded-For и X-Forwarded-Proto не меняют адрес клиента и схему: proxy_headers выключены",
            "backend/app/serve.py", check_proxy_headers_off),
    Control("API8.8", "Пользователь uid 10001, cap_drop ALL, no-new-privileges, корень только для чтения, "
            "данные монтируются только на чтение", "Dockerfile, compose.yaml, compose.data.yaml", None,
            ci=("Команда запуска и HEALTHCHECK образа", "Пределы контейнера"), reason=IN_CONTAINER),
    Control("API8.9", "В контексте сборки и образе нет тестов, кешей, .env, баз SQLite, закрытых и локальных данных",
            ".dockerignore", None, ci=("Контекст сборки", "Состав образа"), reason=IN_CONTAINER),
    Control("API8.10", "Dockerfile проходит проверки BuildKit и hadolint", "Dockerfile", None,
            ci=("Проверки BuildKit для Dockerfile", "hadolint"), reason="нужен Docker, проверка только в CI"),
    Control("API8.11", "TLS и HSTS", "—", None,
            reason="TLS завершается на обратном прокси вне комплекта, порт открыт только на 127.0.0.1"),
    Control("API8.12", "Зависимости Python ставятся только из блокировки с sha256; зависимости и образ сканируются, "
            "SBOM — артефакт CI. Базовые образы по digest не закреплены",
            "backend/requirements.lock, Dockerfile, CI", None,
            ci=("Аудит зависимостей Python", "Аудит зависимостей npm", "Сканирование образа trivy", "SBOM образа"),
            reason=IN_CONTAINER + "; digest базовых образов обновляет пользователь во внешнем репозитории"),
)


@pytest.mark.parametrize("control", [c for c in CONTROLS if c.check], ids=lambda c: c.id)
def test_owasp_control(control, request):
    control.check(request)


def test_owasp_table_rows_have_checks_or_reasons():
    ids = [control.id for control in CONTROLS]
    assert len(ids) == len(set(ids)) and {i.split(".")[0] for i in ids} == {"API4", "API8"}
    for control in CONTROLS:
        assert control.measure and control.where, control.id
        assert control.check or control.reason, control.id


# Модуль запуска


def test_launcher_listens_on_loopback_by_default():
    args = serve.parse_args([])
    assert (args.host, args.port) == ("127.0.0.1", 8000)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("WARNING", "warning"), (" Debug ", "debug"), ("Info", "info"), ("", "info"), ("critical", "critical")],
)
def test_log_level_is_normalized_for_uvicorn(value, expected):
    assert serve.uvicorn_options({"LOG_LEVEL": value})["log_level"] == expected


def test_uvicorn_accepts_every_option(uvicorn_loggers):
    options = serve.uvicorn_options({"LOG_LEVEL": "WARNING"}, host="0.0.0.0")
    assert set(options) <= set(inspect.signature(uvicorn.Config).parameters)
    config = uvicorn.Config(serve.APP, log_config=None, **options)
    assert {name: getattr(config, name) for name in options} == {**CONTAINER_OPTIONS, "log_level": "warning"}
    assert logging.getLogger("uvicorn.error").level == logging.WARNING


def _clear_app_environment(monkeypatch) -> None:
    for name in APP_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_main_starts_uvicorn_with_options(monkeypatch):
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **options: calls.append((app, options)))
    _clear_app_environment(monkeypatch)
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    assert serve.main(container_command()[3:]) == 0
    assert calls == [("app.main:app", {**CONTAINER_OPTIONS, "log_level": "error"})]


@pytest.mark.parametrize(
    ("name", "value"),
    [("LOG_LEVEL", "verbose"), ("LOG_LEVEL", "warn"), ("DEMO_MODE", "ture"), ("METRICS_ENABLED", "ture"),
     ("MAX_TASK_LENGTH", "abc"), ("PAIRS_MIN_SUPPORT", "0"), ("PAIRS_MIN_SUPPORT", "abc"),
     ("CATALOG_SOURCE", "sqllite")],
)
def test_invalid_environment_stops_before_uvicorn(name, value, monkeypatch, capsys):
    def _no_start(*args, **kwargs):
        raise AssertionError("uvicorn не должен запускаться")

    monkeypatch.setattr(uvicorn, "run", _no_start)
    _clear_app_environment(monkeypatch)
    monkeypatch.setenv(name, value)
    assert serve.main([]) == serve.CONFIG_ERROR == 1
    error = capsys.readouterr().err
    assert error.startswith(f"Запуск остановлен: {name} должен ") and "Traceback" not in error


def test_invalid_log_level_stops_the_process():
    env = {name: value for name, value in os.environ.items() if name not in APP_VARIABLES}
    result = subprocess.run(
        [sys.executable, "-m", "app.serve", "--port", str(_free_port())], cwd=BACKEND_DIR,
        env={**env, "LOG_LEVEL": "verbose", "PYTHONUTF8": "1"}, capture_output=True, timeout=60, check=False,
    )
    assert result.returncode == 1 and result.stdout == b""
    assert result.stderr.decode("utf-8").strip() == (
        "Запуск остановлен: LOG_LEVEL должен быть одним из: debug, info, warning, error, critical"
    )


# HEALTHCHECK, compose и CI


# Цепочка поставки: блокировки, образ, аудит, SBOM


# Проверки интерфейса в CI: браузер, Lighthouse, тесты фронтенда


# Мутационное тестирование по расписанию


# Свойства, контракт API, типы интерфейса и нагрузочный прогон в CI


# Линтер, типы, покрытие ветвей и учёт нестабильных тестов


# .dockerignore и контекст сборки


def test_kit_docs_stay_in_repository_outside_build_context():
    """UI-кит доступен в репозитории, образ собирается без документации."""
    docs = ["docs/ui-kit.md"]
    assert [path for path in docs if not (ROOT / path).is_file()] == []
    patterns = [line.strip().strip("/") for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert [p for p in patterns if p in {"docs", "*.md", "**/*.md"} or p.startswith(("docs/", "**/docs"))] == []
    assert [path for path in build_context() if path.split("/")[0] == "docs"] == []


# Живой сервер: последняя проверка останавливает его


def test_access_log_line_has_no_query_string(uvicorn_loggers):
    """Код клиента из `GET /api/users?q=…` не попадает в строку доступа uvicorn: приложение убирает строку запроса."""
    lines: list[str] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(record.getMessage())

    with client_for():
        pass
    access = logging.getLogger("uvicorn.access")
    handler = Collect()
    access.addHandler(handler)
    access.setLevel(logging.INFO)
    try:
        # Формат и аргументы строки доступа uvicorn
        access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:50000", "GET", "/api/users?q=U0039&limit=5", "1.1", 200)
        access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:50000", "POST", "/api/feed", "1.1", 200)
    finally:
        access.removeHandler(handler)
    assert lines == [
        '127.0.0.1:50000 - "GET /api/users HTTP/1.1" 200',
        '127.0.0.1:50000 - "POST /api/feed HTTP/1.1" 200',
    ]


def _read_all(connection: socket.socket) -> bytes:
    data = b""
    while chunk := connection.recv(65536):
        data += chunk
    return data


def test_live_server_finishes_request_and_stops_on_signal(live_server):
    body = json.dumps({"task": "налоги"}).encode()
    with live_server.connect() as connection:
        connection.sendall(
            b"POST /api/recommend HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
            + f"Expect: 100-continue\r\nContent-Length: {len(body)}\r\n\r\n".encode()
        )
        # 100 Continue уходит, когда приложение начало читать тело: запрос уже в работе
        interim = b""
        while b"\r\n\r\n" not in interim and (chunk := connection.recv(64)):
            interim += chunk
        assert interim.startswith(b"HTTP/1.1 100 Continue")
        started = time.monotonic()
        try:
            _interrupt(live_server.process)
        except OSError as exc:  # pragma: no cover — Windows без консоли
            pytest.skip(f"сигнал остановки недоступен: {exc}")
        time.sleep(0.5)
        connection.sendall(body)
        response = _read_all(connection)
    assert response.startswith(b"HTTP/1.1 200 "), response
    grace = seconds(service()["stop_grace_period"])
    code = live_server.process.wait(timeout=grace + 5)
    elapsed = time.monotonic() - started
    output = live_server.output()
    # Процесс завершается сам раньше stop_grace_period, после которого Docker послал бы SIGKILL. Обычно это
    # доли секунды. В Windows цикл Proactor изредка не освобождает соединение, сброшенное клиентом: исключение
    # в _call_connection_lost, и uvicorn ждёт до timeout_graceful_shutdown. В Linux так не бывает.
    assert elapsed < grace, f"{elapsed:.1f} с\n{output}"
    assert code in GRACEFUL_EXIT_CODES, output
    # LOG_LEVEL=Warning: предупреждение приложения есть, строк INFO нет ни у приложения, ни у uvicorn
    assert "WARNING app frontend build not found" in output
    assert "INFO" not in output
