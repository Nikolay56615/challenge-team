"""HTTP-слой: предел тела, единый формат ошибок, заголовки, статика рядом с API, ошибки 500 (PLAN.md, 4.4–4.6)."""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import os

import pytest
from fastapi.testclient import TestClient

import app.api.routes as routes
from app.config import Settings
from app.main import CSP, MAX_BODY_BYTES, BodyLimitMiddleware, FrontendFiles, create_app

from .conftest import client_for, error_of

SECURITY = {"x-content-type-options": "nosniff", "referrer-policy": "no-referrer", "x-frame-options": "DENY"}
TOO_LARGE = {"code": "payload_too_large", "message": "Тело запроса больше 64 КБ", "details": []}
INVALID_JSON = "Тело запроса не является корректным JSON"
BODY_NOT_OBJECT = "Тело запроса должно быть JSON-объектом с заголовком Content-Type: application/json"
JSON = {"content-type": "application/json"}


def assert_secured(response, csp: bool = True) -> None:
    for name, value in SECURITY.items():
        assert response.headers.get(name) == value, name
    assert response.headers.get("content-security-policy") == (CSP if csp else None)


def http_log(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "app" and r.getMessage().startswith("http ")]


# Предел тела запроса


def test_body_over_limit_is_413_before_parsing(client, caplog):
    # 300 000 неизвестных полей: раньше 422 с 300 000 подробностей и ответом 22 МБ после 4–5 секунд разбора
    body = ("{" + ",".join(f'"f{i}":1' for i in range(300_000)) + "}").encode()
    response = client.post("/api/recommend", content=body, headers=JSON)
    assert response.status_code == 413 and error_of(response) == TOO_LARGE
    assert_secured(response)
    assert any(line.startswith("http POST /api/recommend status=413") for line in http_log(caplog))


def test_body_at_limit_passes_and_one_byte_more_is_413(client):
    padded = b'{"task": "' + b" " * (MAX_BODY_BYTES - len(b'{"task": ""}')) + b'"}'
    assert len(padded) == MAX_BODY_BYTES
    assert client.post("/api/recommend", content=padded, headers=JSON).status_code != 413
    assert client.post("/api/recommend", content=padded + b" ", headers=JSON).status_code == 413


def test_chunked_body_without_content_length_is_counted(client):
    body = b'{"task": "' + b"x" * MAX_BODY_BYTES + b'"}'
    response = client.post("/api/recommend", content=iter([body[:40_000], body[40_000:]]), headers=JSON)
    assert response.status_code == 413 and error_of(response) == TOO_LARGE


def test_largest_valid_request_fits_under_limit():
    # Задача на 2000 символов кириллицей с экранированием \uXXXX и 200 событий с кодами по 64 символа
    request = {
        "task": "я" * 2000, "stage": "growth", "experience": "experienced", "format_pref": "template",
        "industry": "manufacturing", "topic": "marketplaces", "profile_id": "P" * 16, "limit": 10, "method": "baseline",
        "history": [{"material_id": "x" * 64, "event": "purchase", "seq": 1_000_000_000} for _ in range(200)],
    }
    body = json.dumps(request).encode()
    assert len(body) < 40 * 1024
    with client_for(max_task_length=2000) as service:
        assert service.post("/api/recommend", content=body, headers=JSON).status_code == 200


def run_asgi(app, chunks: list[bytes], headers: list[tuple[bytes, bytes]] | None = None):
    """Вызывает ASGI-приложение с телом из нескольких сообщений; возвращает отправленное и непрочитанное."""
    pending = [{"type": "http.request", "body": c, "more_body": i < len(chunks) - 1} for i, c in enumerate(chunks)]
    sent: list[dict] = []

    async def receive():
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/api/recommend", "headers": headers or []}
    asyncio.run(app(scope, receive, send))
    return sent, pending


def test_body_limit_reads_no_further_than_limit():
    received: list[bytes] = []

    async def inner(scope, receive, send):
        received.append(b"")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    chunk = b"x" * 40_000
    sent, unread = run_asgi(BodyLimitMiddleware(inner), [chunk, chunk, chunk])
    assert sent[0]["status"] == 413 and json.loads(sent[1]["body"]) == {"error": TOO_LARGE}
    assert received == [] and len(unread) == 1  # третье сообщение не читалось, приложение не вызывалось

    sent, unread = run_asgi(BodyLimitMiddleware(inner), [b"{}"], headers=[(b"content-length", b"70000")])
    assert sent[0]["status"] == 413 and len(unread) == 1  # по Content-Length: тело не читалось вовсе


def test_body_limit_passes_accepted_body_whole():
    bodies: list[bytes] = []

    async def inner(scope, receive, send):
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        bodies.append(body)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    sent, _ = run_asgi(BodyLimitMiddleware(inner), [b"a" * 20_000, b"b" * 20_000])
    assert sent[0]["status"] == 200 and bodies == [b"a" * 20_000 + b"b" * 20_000]


def test_validation_details_are_capped_at_ten(client):
    body = json.dumps({f"f{i}": 1 for i in range(5000)}, separators=(",", ":")).encode()
    assert len(body) < MAX_BODY_BYTES
    response = client.post("/api/recommend", content=body, headers=JSON)
    error = error_of(response)
    assert response.status_code == 422 and error["message"] == "Неизвестное поле «f0»"
    assert [d["field"] for d in error["details"]] == [f"f{i}" for i in range(10)]


# Единый формат ошибок тела


@pytest.mark.parametrize(
    ("body", "content_type", "message"),
    [
        (b'{"task": "x"}', "text/plain", BODY_NOT_OBJECT),
        (b'{"task": "x"}', "application/x-www-form-urlencoded", BODY_NOT_OBJECT),
        (b'{"task": "x"}', None, BODY_NOT_OBJECT),
        (b"", "application/json", BODY_NOT_OBJECT),
        (b"[]", "application/json", BODY_NOT_OBJECT),
        (b"null", "application/json", BODY_NOT_OBJECT),
        ('{"task": "налоги"}'.encode("cp1251"), "application/json", INVALID_JSON),
        (b"[" * 30_000 + b"]" * 30_000, "application/json", INVALID_JSON),
        (b'{"limit": ' + b"9" * 5000 + b"}", "application/json", INVALID_JSON),
        (b"{not json", "application/json", INVALID_JSON),
    ],
    ids=["text-plain", "form", "no-content-type", "empty", "array", "null", "cp1251", "deep-nesting", "huge-number",
         "syntax"],
)
def test_body_errors_are_422_in_unified_format(client, body, content_type, message):
    headers = {"content-type": content_type} if content_type else {}
    response = client.post("/api/recommend", content=body, headers=headers)
    assert response.status_code == 422
    assert error_of(response) == {
        "code": "validation_error", "message": message, "details": [{"field": "body", "message": message}]
    }


def test_compare_requires_content_type(client):
    response = client.post("/api/compare", content=b'{"task": "x"}')
    assert response.status_code == 422
    assert error_of(response)["details"] == [{"field": "body", "message": BODY_NOT_OBJECT}]


@pytest.mark.parametrize("path", ["/api/recommend", "/api/compare"])
def test_size_limit_precedes_content_type_check(client, path):
    response = client.post(path, content=b"x" * (MAX_BODY_BYTES + 1))
    assert response.status_code == 413
    assert error_of(response)["code"] == "payload_too_large"


def test_field_named_body_is_reported_as_unknown_field(client):
    response = client.post("/api/recommend", json={"body": 1})
    assert error_of(response)["details"] == [{"field": "body", "message": "Неизвестное поле «body»"}]


# Пути API и статика на `/`


@pytest.mark.parametrize(
    ("method", "path", "status", "allow"),
    [
        ("GET", "/api/recommend", 405, "POST"),
        ("DELETE", "/api/compare", 405, "POST"),
        ("PUT", "/api/health", 405, "GET"),
        ("POST", "/api/meta", 405, "GET"),
        ("POST", "/api/nothing", 404, None),
        ("GET", "/api/nothing", 404, None),
        ("GET", "/api", 404, None),
    ],
)
def test_api_paths_answer_the_same_with_and_without_frontend(client, method, path, status, allow):
    response = client.request(method, path)
    assert response.status_code == status
    assert error_of(response)["code"] == ("method_not_allowed" if status == 405 else "not_found")
    assert response.headers.get("allow") == allow
    assert_secured(response)


def test_head_and_trailing_slash_on_api_with_frontend(frontend_client):
    head = frontend_client.head("/api/health")
    assert head.status_code == 405 and head.headers["allow"] == "GET"
    redirect = frontend_client.get("/api/health/", follow_redirects=False)
    assert redirect.status_code == 307 and redirect.headers["location"].endswith("/api/health")


def test_api_and_docs_rules_hold_under_root_path(frontend_dist):
    # За обратным прокси с uvicorn --root-path пути сравниваются без префикса, как в Mount и роутере
    with TestClient(create_app(Settings(frontend_dist=frontend_dist)), root_path="/prefix") as service:
        wrong_method = service.get("/prefix/api/recommend")
        assert wrong_method.status_code == 405 and wrong_method.headers["allow"] == "POST"
        assert service.post("/prefix/api/nothing").status_code == 404
        assert_secured(service.get("/prefix/docs"), csp=False)
        assert_secured(service.get("/prefix/index.html"))


def test_frontend_files_are_served_with_csp(frontend_client):
    for path, marker in (("/", 'id="root"'), ("/index.html", 'id="root"'), ("/kit.html", 'id="kit"')):
        page = frontend_client.get(path)
        assert page.status_code == 200 and marker in page.text, path
        assert_secured(page)
    script = frontend_client.get("/assets/main.js")
    assert script.status_code == 200
    assert_secured(script)
    missing = frontend_client.get("/missing.html")
    assert missing.status_code == 404 and error_of(missing)["code"] == "not_found"
    wrong_method = frontend_client.post("/index.html")
    assert wrong_method.status_code == 405 and wrong_method.headers["allow"] == "GET, HEAD"


def test_file_name_invalid_for_os_is_json_404(frontend_client, monkeypatch):
    # В Windows < > " | * ? в имени дают OSError (WinError 123); в Linux так ведёт себя подменённый os.stat
    real_stat = os.stat

    def stat(path, *args, **kwargs):
        if str(path).endswith("a<b"):
            raise OSError(errno.EINVAL, "The filename, directory name, or volume label syntax is incorrect", str(path))
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat)
    for path in ("/a%3Cb", "/a%7Cb", "/a%22b", "/a*b", "/a%3Fb", "/CON", "/a%00b"):
        response = frontend_client.get(path)
        assert response.status_code == 404 and error_of(response)["code"] == "not_found", path
        assert_secured(response)


def test_frontend_lookup_keeps_permission_error(frontend_dist, monkeypatch):
    files = FrontendFiles(directory=frontend_dist)
    real_stat = os.stat

    def stat(path, *args, **kwargs):
        name = str(path)
        if name.endswith("a<b"):
            raise OSError(errno.EINVAL, "invalid name", name)
        if name.endswith("locked.html"):
            raise PermissionError(errno.EACCES, "denied", name)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat)
    assert files.lookup_path("a<b") == ("", None)
    with pytest.raises(PermissionError):  # Starlette отвечает на него сам
        files.lookup_path("locked.html")


def test_csp_is_skipped_only_on_exact_docs_paths(frontend_client):
    for path in ("/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"):
        response = frontend_client.get(path)
        assert response.status_code == 200, path
        assert_secured(response, csp=False)
    # Раньше проверка по префиксу отдавала по этим адресам страницу приложения без CSP
    for path in ("/docs%2f..%2findex.html", "/docs%2F..%2Fkit.html", "/redoc%2f..%2findex.html",
                 "/docs%2f..%2fassets%2fmain.js", "/openapi.json%2f..%2findex.html"):
        response = frontend_client.get(path)
        assert response.status_code == 200, path
        assert_secured(response)


# Непредвиденные ошибки


def _boom(*args, **kwargs):
    raise RuntimeError("секретный текст задачи")


def test_unhandled_error_is_500_with_headers_and_status_line(monkeypatch, caplog, restore_log_levels):
    monkeypatch.setattr(routes, "recommend", _boom)
    # raise_server_exceptions=True: исключение не выходит за приложение, второй трассировки у сервера нет
    with client_for() as service:
        response = service.post("/api/recommend", json={"task": "налоги"})
    assert response.status_code == 500
    assert error_of(response) == {"code": "internal_error", "message": "Внутренняя ошибка сервиса", "details": []}
    assert_secured(response)
    app_records = [r for r in caplog.records if r.name == "app"]
    errors = [r for r in app_records if r.levelno == logging.ERROR]
    assert [r.getMessage() for r in errors] == ["unhandled error: RuntimeError path=/api/recommend"]
    assert not any(r.exc_info for r in app_records)  # трассировка только на DEBUG
    assert any(line.startswith("http POST /api/recommend status=500") for line in http_log(caplog))
    assert "секретный текст задачи" not in caplog.text


def test_traceback_is_logged_only_at_debug(monkeypatch, caplog, restore_log_levels):
    monkeypatch.setattr(routes, "recommend", _boom)
    with client_for(log_level="debug") as service:
        assert service.post("/api/recommend", json={"task": "налоги"}).status_code == 500
    traced = [r for r in caplog.records if r.name == "app" and r.exc_info]
    assert len(traced) == 1 and traced[0].levelno == logging.DEBUG and traced[0].exc_info[0] is RuntimeError


def test_log_line_escapes_control_characters(client, caplog):
    assert client.get("/api/x%0Afake%20status=200").status_code == 404
    lines = http_log(caplog)
    assert lines and all("\n" not in line for line in lines)
    assert any("/api/x\\x0afake status=200 status=404" in line for line in lines)
