"""Край HTTP: заголовки безопасности и CORS, кеширование и сжатие, код запроса и Server-Timing, живость
и готовность, журнал без данных запроса (кандидаты W01, W03, W11, W13, W16); тип содержимого с `charset`
и папки статики без листинга (evaluation/track1-asvs.md: V4.1.1, V13.4.3)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys

import pytest

from app.api import routes
from app.config import BACKEND_DIR
from app.main import MAX_BODY_BYTES, STATIC_TYPES

from .conftest import client_for, error_of

JSON = {"content-type": "application/json"}
IDENTITY = {"accept-encoding": "identity"}
GZIP = {"accept-encoding": "gzip"}
HEX32 = re.compile(r"[0-9a-f]{32}")
ASSET = "/assets/main-3f9a1c.js"
STYLESHEET = "/assets/main-5b2e7d.css"

# Эталон заголовков безопасности: одинаков для HTML, статики, API, ошибок и 304
REFERENCE_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "permissions-policy": (
        "accelerometer=(), autoplay=(), bluetooth=(), camera=(), display-capture=(), encrypted-media=(), "
        "fullscreen=(), geolocation=(), gyroscope=(), hid=(), idle-detection=(), local-fonts=(), magnetometer=(), "
        "microphone=(), midi=(), payment=(), picture-in-picture=(), publickey-credentials-get=(), "
        "screen-wake-lock=(), serial=(), usb=(), xr-spatial-tracking=()"
    ),
    "content-security-policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
        "font-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
}
IMMUTABLE = "public, max-age=31536000, immutable"
STATIC = "public, max-age=3600"

HTTP_LINE = re.compile(r"http [A-Z]+ \S+ status=\d{3} ms=\d+\.\d id=[A-Za-z0-9._-]{1,64} trace=(?:[0-9a-f]{32}|-)")
EVENT_LINE = re.compile(
    r"(?:recommend|compare) id=[A-Za-z0-9._-]{1,64} method=(?:personal|baseline) "
    r"status=(?:strong|weak|none|cold|empty) candidates=\d+ items=\d+ ms=\d+\.\d"
)
TIMING = re.compile(r"rank;dur=(\d+\.\d), total;dur=(\d+\.\d)")


@pytest.fixture(scope="module")
def edge_dist(tmp_path_factory):
    """Сборка интерфейса с файлами всех видов: HTML, хешированные скрипт больше 1 КБ и стили, шрифт, текст
    из public/."""
    dist = tmp_path_factory.mktemp("edge-dist")
    (dist / "index.html").write_text('<!doctype html><div id="root"></div>', encoding="utf-8")
    (dist / "kit.html").write_text('<!doctype html><div id="kit"></div>', encoding="utf-8")
    (dist / "assets").mkdir()
    (dist / "assets" / ASSET.rsplit("/", 1)[1]).write_text("export const x = 1;\n" * 200, encoding="utf-8")
    (dist / "assets" / STYLESHEET.rsplit("/", 1)[1]).write_text(":root { color-scheme: light; }\n", encoding="utf-8")
    (dist / "fonts").mkdir()
    (dist / "fonts" / "onest-latin.woff2").write_bytes(bytes(range(256)) * 8)
    (dist / "fonts" / "OFL.txt").write_text("SIL Open Font License\n" * 100, encoding="utf-8")
    return dist


@pytest.fixture
def edge(edge_dist):
    with client_for(frontend_dist=edge_dist) as service:
        yield service


def _boom(*args, **kwargs):
    raise RuntimeError("сбой при подборе")


def cors_headers(response) -> list[str]:
    return [name for name in response.headers if name.lower().startswith("access-control-")]


def log_lines(caplog, prefix: str = "http ") -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name.startswith("app") and r.getMessage().startswith(prefix)]


def sha_tag(body: bytes) -> str:
    return f'"{hashlib.sha256(body).hexdigest()}"'


# W01. Заголовки безопасности на шести типах ответа и на 304


def _revalidate(service):
    return service.get("/api/meta", headers={"if-none-match": service.get("/api/meta").headers["etag"]})


SIX_TYPES = {
    "api-200": (lambda s: s.get("/api/meta"), 200, "no-cache"),
    "api-4xx": (lambda s: s.post("/api/recommend", json={"stage": "unknown"}), 422, "no-store"),
    "api-500": (lambda s: s.post("/api/recommend", json={"task": "налоги"}), 500, "no-store"),
    "static": (lambda s: s.get(ASSET), 200, IMMUTABLE),
    "html": (lambda s: s.get("/"), 200, "no-cache"),
    "413": (lambda s: s.post("/api/recommend", content=b"x" * (MAX_BODY_BYTES + 1), headers=JSON), 413, "no-store"),
    "304": (_revalidate, 304, "no-cache"),
}


@pytest.mark.parametrize("kind", list(SIX_TYPES))
def test_reference_headers_on_every_response_type(edge, monkeypatch, kind):
    call, status, cache = SIX_TYPES[kind]
    if kind == "api-500":
        monkeypatch.setattr(routes, "recommend", _boom)
    response = call(edge)
    assert response.status_code == status
    for name, value in REFERENCE_HEADERS.items():
        assert response.headers.get_list(name) == [value], name
    assert "unsafe-" not in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == cache
    assert HEX32.fullmatch(response.headers["x-request-id"])
    assert not cors_headers(response)


def test_docs_pages_keep_headers_except_csp(edge):
    for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
        response = edge.get(path)
        assert response.status_code == 200, path
        for name, value in REFERENCE_HEADERS.items():
            assert response.headers.get(name) == (None if name == "content-security-policy" else value), (path, name)
        assert response.headers["cache-control"] == "no-cache"


def test_no_cors_even_for_foreign_origin_and_preflight(edge):
    origin = {"origin": "https://evil.example"}
    preflight = {**origin, "access-control-request-method": "POST", "access-control-request-headers": "content-type"}
    responses = {
        "GET /api/meta": edge.get("/api/meta", headers=origin),
        "POST /api/recommend": edge.post("/api/recommend", json={"task": "налоги"}, headers=origin),
        "GET /": edge.get("/", headers=origin),
        "OPTIONS /api/recommend": edge.options("/api/recommend", headers=preflight),
        "OPTIONS /api/meta": edge.options("/api/meta", headers=preflight),
        "OPTIONS /": edge.options("/", headers=preflight),
    }
    assert {k: r.status_code for k, r in responses.items()} == {
        "GET /api/meta": 200, "POST /api/recommend": 200, "GET /": 200,
        "OPTIONS /api/recommend": 405, "OPTIONS /api/meta": 405, "OPTIONS /": 405,
    }
    for name, response in responses.items():
        assert not cors_headers(response), name
    assert responses["OPTIONS /api/recommend"].headers["allow"] == "POST"


# W03. Cache-Control по типу ответа


@pytest.mark.parametrize(
    ("method", "path", "status", "cache"),
    [
        ("GET", ASSET, 200, IMMUTABLE),
        ("GET", "/docs%2f..%2f" + ASSET.lstrip("/").replace("/", "%2f"), 200, IMMUTABLE),
        ("GET", "/", 200, "no-cache"),
        ("GET", "/index.html", 200, "no-cache"),
        ("GET", "/kit.html", 200, "no-cache"),
        ("GET", "/fonts/onest-latin.woff2", 200, STATIC),
        ("GET", "/fonts/OFL.txt", 200, STATIC),
        ("GET", "/assets/missing.js", 404, "no-store"),
        ("GET", "/missing.html", 404, "no-store"),
        ("POST", "/index.html", 405, "no-store"),
        ("GET", "/api/health", 200, "no-store"),
        ("GET", "/api/live", 200, "no-store"),
        ("GET", "/api/ready", 200, "no-store"),
        ("GET", "/api/meta", 200, "no-cache"),
        ("GET", "/api/profiles", 200, "no-cache"),
        ("GET", "/api/nothing", 404, "no-store"),
        ("GET", "/api/recommend", 405, "no-store"),
        ("GET", "/openapi.json", 200, "no-cache"),
    ],
)
def test_cache_control_by_response_type(edge, method, path, status, cache):
    response = edge.request(method, path)
    assert response.status_code == status
    assert response.headers["cache-control"] == cache


# ASVS V4.1.1 и V13.4.3: тип содержимого с charset у текстовых файлов, папки статики без листинга


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/", "text/html; charset=utf-8"),
        ("/kit.html", "text/html; charset=utf-8"),
        (ASSET, "text/javascript; charset=utf-8"),
        (STYLESHEET, "text/css; charset=utf-8"),
        ("/fonts/OFL.txt", "text/plain; charset=utf-8"),
        ("/fonts/onest-latin.woff2", "font/woff2"),
        ("/api/meta", "application/json"),
        ("/api/nothing", "application/json"),
    ],
)
def test_text_responses_declare_utf8_charset(edge, path, content_type):
    # У application/json параметра charset нет (RFC 8259), у шрифта — тоже: это не текст
    response = edge.get(path, headers=IDENTITY)
    assert response.headers["content-type"] == content_type
    if not path.startswith("/api/"):
        assert edge.head(path).headers["content-type"] == content_type


def test_static_types_do_not_depend_on_system_database():
    """В Windows типы читаются из реестра поверх встроенных, и там бывает чужой тип. Тест подменяет реестр
    системной базой с чужими типами для всех расширений сборки: после импорта app.main действуют типы приложения."""
    foreign = {
        ".html": "application/octet-stream",
        ".js": "application/x-javascript",
        ".css": "text/plain",
        ".txt": "application/octet-stream",
        ".woff2": "application/font-woff2",
    }
    assert set(foreign) == set(STATIC_TYPES)
    code = (
        "import json, mimetypes, sys\n"
        "foreign = json.loads(sys.argv[1])\n"
        "for extension, kind in foreign.items(): mimetypes.add_type(kind, extension)\n"
        "import app.main\n"
        "print(json.dumps({extension: mimetypes.guess_type('a' + extension)[0] for extension in foreign}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, json.dumps(foreign)], cwd=BACKEND_DIR, capture_output=True, encoding="utf-8",
        timeout=60, env={**os.environ, "LOG_LEVEL": "warning", "PYTHONUTF8": "1"}, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {
        ".html": "text/html",
        ".js": "text/javascript",
        ".css": "text/css",
        ".txt": "text/plain",
        ".woff2": "font/woff2",
    }


def test_static_types_cover_frontend_build():
    # Расширения сборки: точки входа Vite (.html), скрипты и стили в assets/, файлы из public/ копируются как есть.
    # Если сборка уже есть, сверяется и она: так видны файлы, которые Vite выносит в assets/ из импортов
    frontend = BACKEND_DIR.parent / "frontend"
    public = {path.suffix for path in (frontend / "public").rglob("*") if path.is_file()}
    entries = {path.suffix for path in frontend.glob("*.html")}
    built = {path.suffix for path in (frontend / "dist").rglob("*") if path.is_file()}
    assert public and entries
    assert public | entries | built | {".js", ".css"} <= set(STATIC_TYPES)


@pytest.mark.parametrize("path", ["/assets/", "/assets", "/fonts/", "/fonts", "/fonts/%2e%2e/assets/"])
def test_static_directories_answer_404_without_listing(edge, path):
    response = edge.get(path)
    assert response.status_code == 404 and error_of(response)["code"] == "not_found"
    assert response.headers["content-type"] == "application/json"
    for name in (ASSET, STYLESHEET, "onest-latin.woff2", "OFL.txt"):
        assert name.rsplit("/", 1)[-1] not in response.text, name


@pytest.mark.parametrize("path", ["/", "/index.html", ASSET, "/fonts/OFL.txt"])
def test_trace_on_static_files_is_405(edge, path):
    # ASVS V13.4.4: TRACE не отражает запрос и на файлах интерфейса; методы API — test_runtime.py, API8.1
    response = edge.request("TRACE", path)
    assert response.status_code == 405 and error_of(response)["code"] == "method_not_allowed"
    assert response.headers["allow"] == "GET, HEAD"


def test_recommend_and_api_only_root_cache_control():
    with client_for() as api_only:
        assert api_only.get("/").headers["cache-control"] == "no-cache"
        assert api_only.post("/api/recommend", json={"task": "налоги"}).headers["cache-control"] == "no-store"
        assert api_only.post("/api/compare", json={"task": "налоги"}).headers["cache-control"] == "no-store"


# W03. ETag и 304 у справочников


@pytest.mark.parametrize("path", ["/api/meta", "/api/profiles"])
def test_reference_data_has_strong_etag_and_answers_304(client, path):
    first = client.get(path, headers=IDENTITY)
    etag = first.headers["etag"]
    assert first.status_code == 200 and etag == sha_tag(first.content)  # сильный ETag тела
    assert first.headers["cache-control"] == "no-cache"
    for condition in (etag, "W/" + etag, f'"other", {etag}', "*"):
        again = client.get(path, headers={**IDENTITY, "if-none-match": condition})
        assert again.status_code == 304 and again.content == b"", condition
        assert again.headers["etag"] == etag and again.headers["cache-control"] == "no-cache"
        assert again.headers.get("vary") == first.headers.get("vary")
        assert "content-type" not in again.headers and "server-timing" not in again.headers
    changed = client.get(path, headers={**IDENTITY, "if-none-match": '"other"'})
    assert changed.status_code == 200 and changed.content == first.content


def test_reference_body_is_unchanged_by_etag(client):
    meta = client.get("/api/meta").json()
    assert [t["value"] for t in meta["topics"]] == ["start", "taxes_law", "finance", "marketing", "sales", "operations"]
    assert client.get("/api/meta").headers["content-type"] == "application/json"


def test_gzip_makes_etag_weak_and_304_follows(client):
    identity = client.get("/api/profiles", headers=IDENTITY)
    zipped = client.get("/api/profiles", headers=GZIP)
    assert len(identity.content) >= 1024
    assert zipped.headers["content-encoding"] == "gzip" and "content-encoding" not in identity.headers
    assert zipped.content == identity.content  # httpx распаковал тело
    assert "accept-encoding" in zipped.headers["vary"].lower() and "accept-encoding" in identity.headers["vary"].lower()
    strong = identity.headers["etag"]
    weak = zipped.headers["etag"]
    assert weak == "W/" + strong  # у сжатого тела другие байты, сильный ETag ему не подходит
    for condition, encoding, expected in ((weak, GZIP, weak), (strong, GZIP, weak), (weak, IDENTITY, strong)):
        response = client.get("/api/profiles", headers={**encoding, "if-none-match": condition})
        assert response.status_code == 304 and response.content == b""
        assert response.headers["etag"] == expected
        assert "content-encoding" not in response.headers
        assert "accept-encoding" in response.headers["vary"].lower()


def test_small_responses_are_not_compressed(edge):
    for path in ("/api/health", "/", "/api/ready"):
        response = edge.get(path, headers=GZIP)
        assert len(response.content) < 1024, path
        assert "content-encoding" not in response.headers and "vary" not in response.headers, path
    assert not edge.get("/api/meta", headers=GZIP).headers["etag"].startswith('"')  # 1,5 КБ: сжат


def test_static_files_compress_by_type_and_answer_304(edge):
    asset = edge.get(ASSET, headers=GZIP)
    assert asset.headers["content-encoding"] == "gzip" and asset.headers["etag"].startswith('W/"')
    again = edge.get(ASSET, headers={**GZIP, "if-none-match": asset.headers["etag"]})
    assert again.status_code == 304 and again.content == b""
    assert again.headers["cache-control"] == IMMUTABLE and again.headers["etag"] == asset.headers["etag"]
    font = edge.get("/fonts/onest-latin.woff2", headers=GZIP)
    assert font.headers["content-type"] == "font/woff2"  # и на Python 3.12, где тип .woff2 не известен
    assert "content-encoding" not in font.headers and not font.headers["etag"].startswith("W/")
    text = edge.get("/fonts/OFL.txt", headers=GZIP)
    assert text.headers["content-encoding"] == "gzip" and text.headers["cache-control"] == STATIC


def test_if_modified_since_on_static_files(edge):
    page = edge.get("/", headers=IDENTITY)
    modified = page.headers["last-modified"]
    assert edge.get("/", headers={"if-modified-since": modified}).status_code == 304
    assert edge.get("/", headers={"if-modified-since": "Thu, 01 Jan 1970 00:00:00 GMT"}).status_code == 200
    assert edge.get("/", headers={"if-modified-since": "yesterday"}).status_code == 200
    assert edge.get("/", headers={"if-modified-since": "Thu, 01 Jan 2099 00:00:00 -0000"}).status_code == 200
    # If-None-Match главнее: несовпавший ETag даёт 200 даже при свежей дате
    both = {"if-none-match": '"other"', "if-modified-since": modified}
    assert edge.get("/", headers=both).status_code == 200
    head = edge.head("/", headers={"if-none-match": page.headers["etag"]})
    assert head.status_code == 304


def test_conditional_headers_do_not_affect_post_and_errors(edge):
    assert edge.post("/api/recommend", json={"task": "налоги"}, headers={"if-none-match": "*"}).status_code == 200
    missing = edge.get("/missing.html", headers={"if-none-match": "*"})
    assert missing.status_code == 404 and error_of(missing)["code"] == "not_found"
    assert edge.get("/api/health", headers={"if-none-match": "*"}).status_code == 200  # без ETag условия нет


# W11. X-Request-Id, traceparent, Server-Timing


def test_valid_request_id_is_echoed_in_header_body_and_log(client, caplog):
    rid = "demo.Run_42-a"
    response = client.post("/api/recommend", json={"task": "налоги"}, headers={"x-request-id": rid})
    assert response.headers["x-request-id"] == rid and response.json()["request_id"] == rid
    assert any(f" id={rid} trace=-" in line for line in log_lines(caplog))
    assert any(line.startswith(f"recommend id={rid} ") for line in log_lines(caplog, "recommend "))


@pytest.mark.parametrize("value", ["", "a b", "a/b", "a;b", "x" * 65, "a\tb", "<script>", "abcé"])
def test_invalid_request_id_is_replaced(edge, caplog, value):
    response = edge.get("/api/meta", headers={"x-request-id": value.encode()})
    rid = response.headers["x-request-id"]
    assert HEX32.fullmatch(rid) and rid != value
    assert any(f" id={rid} " in line for line in log_lines(caplog))


def test_generated_request_ids_are_unique_and_shared_with_body(edge):
    first, second = (edge.post("/api/compare", json={"task": "налоги"}) for _ in range(2))
    ids = [r.headers["x-request-id"] for r in (first, second)]
    assert ids[0] != ids[1] and all(HEX32.fullmatch(i) for i in ids)
    body = first.json()
    assert body["baseline"]["request_id"] == body["personal"]["request_id"] == ids[0]
    duplicated = edge.get("/api/meta", headers=[("x-request-id", "one"), ("x-request-id", "two")])
    assert HEX32.fullmatch(duplicated.headers["x-request-id"])


TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"


@pytest.mark.parametrize(
    ("traceparent", "logged"),
    [
        (f"00-{TRACE}-00f067aa0ba902b7-01", TRACE),
        (f"00-{TRACE}-00f067aa0ba902b7-00", TRACE),
        (f"01-{TRACE}-00f067aa0ba902b7-01", "-"),
        (f"ff-{TRACE}-00f067aa0ba902b7-01", "-"),
        (f"00-{TRACE.upper()}-00f067aa0ba902b7-01", "-"),
        (f"00-{'0' * 32}-00f067aa0ba902b7-01", "-"),
        (f"00-{TRACE}-{'0' * 16}-01", "-"),
        (f"00-{TRACE[:-1]}-00f067aa0ba902b7-01", "-"),
        (f"00-{TRACE}-00f067aa0ba902b7-01-extra", "-"),
        ("trace", "-"),
    ],
)
def test_traceparent_is_logged_only_when_valid(edge, caplog, traceparent, logged):
    response = edge.get("/api/health", headers={"traceparent": traceparent})
    assert response.status_code == 200 and "traceparent" not in response.headers
    rid = response.headers["x-request-id"]
    assert any(line.endswith(f" id={rid} trace={logged}") for line in log_lines(caplog))


@pytest.mark.parametrize("path", ["/api/recommend", "/api/compare"])
def test_server_timing_on_ranking_responses(client, path):
    response = client.post(path, json={"task": "Хочу начать продвигать свою кофейню"})
    match = TIMING.fullmatch(response.headers["server-timing"])
    assert response.status_code == 200 and match
    rank, total = (float(v) for v in match.groups())
    assert 0 <= rank <= total


def test_server_timing_only_on_successful_ranking(edge, monkeypatch):
    responses = [
        edge.get("/api/meta"), edge.get("/api/health"), edge.get("/"), edge.get(ASSET),
        edge.post("/api/recommend", json={"limit": 0}),
        edge.post("/api/compare", content=b"x" * (MAX_BODY_BYTES + 1), headers=JSON),
    ]
    monkeypatch.setattr(routes, "recommend", _boom)
    responses.append(edge.post("/api/recommend", json={"task": "налоги"}))
    assert [r.status_code for r in responses] == [200, 200, 200, 200, 422, 413, 500]
    assert all("server-timing" not in r.headers for r in responses)


# W13. Живость и готовность


def test_live_and_ready_with_catalog(client):
    for path in ("/api/live", "/api/ready"):
        response = client.get(path)
        assert response.status_code == 200 and response.json() == {"status": "ok"}, path
        assert response.headers["cache-control"] == "no-store"
    assert set(client.get("/api/health").json()) == {"status", "catalog"}  # прежний контракт


def test_ready_is_503_and_live_is_200_without_catalog(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text('{"version": "empty", "materials": []}', encoding="utf-8")
    with client_for(catalog_source="file", catalog_path=path) as broken:
        live, ready, health = broken.get("/api/live"), broken.get("/api/ready"), broken.get("/api/health")
    assert live.status_code == 200 and live.json() == {"status": "ok"}
    for response in (ready, health):
        assert response.status_code == 503 and error_of(response)["code"] == "catalog_unavailable"
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/api/live", "/api/ready"])
def test_probes_accept_only_get(client, path):
    for method in ("POST", "HEAD", "PUT"):
        response = client.request(method, path)
        assert response.status_code == 405 and response.headers["allow"] == "GET", method


# W16. Схема журнала, маркер, экранирование


MARKER = "QZX7MARKER"


def _boom_with_marker(*args, **kwargs):
    raise RuntimeError(f"сбой на задаче {MARKER}")


def test_marker_from_request_never_reaches_info_log(monkeypatch, caplog, restore_log_levels):
    caplog.set_level(logging.INFO)
    history = [{"material_id": MARKER, "event": "complete", "seq": 1}]
    profile = {"task": f"Продвижение кофейни {MARKER}", "profile_id": MARKER, "history": history, "stage": "start"}
    with client_for(log_level="info") as service:
        statuses = [
            service.post("/api/recommend", json=profile).status_code,
            service.post("/api/compare", json=profile).status_code,
            service.post("/api/recommend", json={**profile, "history": None}).status_code,
            service.post("/api/recommend", json={"task": MARKER, "stage": MARKER, "industry": MARKER}).status_code,
            service.post("/api/recommend", json={"topic": MARKER, MARKER: MARKER}).status_code,
            service.post("/api/recommend", json={"task": MARKER * 300}).status_code,
            service.post("/api/recommend", content=f'{{"task": "{MARKER}'.encode(), headers=JSON).status_code,
            service.post("/api/recommend", content=MARKER.encode() * 7000, headers=JSON).status_code,
        ]
        monkeypatch.setattr(routes, "recommend", _boom_with_marker)
        statuses.append(service.post("/api/recommend", json=profile).status_code)
    assert statuses == [200, 200, 200, 422, 422, 422, 422, 413, 500]
    app_records = [r for r in caplog.records if r.name.startswith("app")]
    assert len(log_lines(caplog)) == len(statuses)  # журнал писался: по строке http на каждый запрос
    assert len(log_lines(caplog, "recommend ")) == 2 and len(log_lines(caplog, "compare ")) == 1
    assert MARKER not in caplog.text
    assert not any(MARKER in r.getMessage() or r.exc_info for r in app_records)


def test_log_lines_follow_documented_schema(client, caplog):
    client.post("/api/recommend", json={"task": "налоги"}, headers={"traceparent": f"00-{TRACE}-00f067aa0ba902b7-01"})
    client.post("/api/compare", json={"task": "налоги"})
    client.get("/api/x%20y%0Az")
    client.post("/api/recommend", content=b"{", headers=JSON)
    lines = log_lines(caplog)
    assert len(lines) == 4 and all(HTTP_LINE.fullmatch(line) for line in lines), lines
    events = log_lines(caplog, "recommend ") + log_lines(caplog, "compare ")
    assert len(events) == 2 and all(EVENT_LINE.fullmatch(line) for line in events), events


def test_log_line_escapes_control_and_separator_characters(client, caplog):
    raw = "/api/a%0D%0Ab%09c%1Bd%00e%7Ff%C2%85g%E2%80%A8h%E2%80%AEi%5Cj%C2%A0k l"
    assert client.get(raw).status_code == 404
    [line] = [line for line in log_lines(caplog) if line.startswith("http GET /api/a")]
    path = "/api/a\\x0d\\x0ab\\x09c\\x1bd\\x00e\\x7ff\\x85g\\u2028h\\u202ei\\x5cj\\xa0k\\x20l"
    assert line.startswith(f"http GET {path} status=404 ")
    assert line.isprintable() and len(line.split(" ")) == 7
