"""GET /metrics за флагом METRICS_ENABLED: текстовый формат Prometheus 0.0.4, метки и их кардинальность, потоки,
заголовки, отсутствие данных запроса (кандидат W12; схема метрик — в начале app/main.py)."""

from __future__ import annotations

import asyncio
import math
import random
import re
import string
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.api import routes
from app.main import CSP, DURATION_BUCKETS, KNOWN_METHODS, MAX_BODY_BYTES, SECURITY_HEADERS, HttpMetrics
from app.ranking.policy import recommend

from .conftest import client_for, error_of

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
COUNTER = "http_server_requests_total"
HISTOGRAM = "http_server_request_duration_seconds"
LABELS = {"http_route", "http_request_method", "http_response_status_code"}
LE = ["0.005", "0.01", "0.025", "0.05", "0.075", "0.1", "0.25", "0.5", "0.75", "1.0", "2.5", "5.0", "7.5", "10.0",
      "+Inf"]
API_ROUTES = {"/api/health", "/api/live", "/api/ready", "/api/meta", "/api/profiles", "/api/recommend", "/api/compare"}
STATIC_ROUTE = "/{path:path}"
JSON = {"content-type": "application/json"}
HEX32 = re.compile(r"[0-9a-f]{32}")
MARKER = "QZX7METRICSMARKER"


# Маленький разборщик текстового формата 0.0.4: семейство — строки HELP и TYPE, затем образцы этого семейства


# Значение метки в кавычках может содержать «}», как в шаблоне /{path:path}
SAMPLE = re.compile(
    r'(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>(?:[^"}]|"(?:[^"\\]|\\.)*")*)\})? (?P<value>\S+)'
)
LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\\n]|\\[\\"n])*)"(?:,|$)')
SUFFIXES = {"counter": ("",), "histogram": ("_bucket", "_sum", "_count")}


def parse_labels(text: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    position = 0
    while position < len(text):
        match = LABEL.match(text, position)
        assert match, text
        name, raw = match.groups()
        assert name not in labels, text
        labels[name] = re.sub(r"\\(.)", lambda m: "\n" if m[1] == "n" else m[1], raw)
        position = match.end()
    return labels


def parse(text: str) -> dict[str, dict]:
    """Семейства: {имя: {"help", "type", "samples": [(имя образца, метки, значение)]}}; проверяет порядок строк."""
    assert text.endswith("\n") and "\r" not in text
    families: dict[str, dict] = {}
    current: str | None = None
    for line in text[:-1].split("\n"):
        if line.startswith("# HELP "):
            name, help_text = line.removeprefix("# HELP ").split(" ", 1)
            assert name not in families and help_text
            families[name] = {"help": help_text, "type": None, "samples": []}
            current = name
        elif line.startswith("# TYPE "):
            name, kind = line.removeprefix("# TYPE ").split(" ")
            assert name == current and families[name]["type"] is None and not families[name]["samples"]
            families[name]["type"] = kind
        else:
            match = SAMPLE.fullmatch(line)
            assert match and current is not None, line
            family = families[current]
            assert family["type"] in SUFFIXES, line
            assert match["name"] in {current + suffix for suffix in SUFFIXES[family["type"]]}, line
            family["samples"].append((match["name"], parse_labels(match["labels"] or ""), float(match["value"])))
    return families


def series(text: str) -> dict[tuple[str, str, str], dict]:
    """Ряды по (маршрут, метод, код): счётчик, накопленные корзины, сумма и число; проверяет инварианты."""
    families = parse(text)
    assert set(families) == {COUNTER, HISTOGRAM}
    assert families[COUNTER]["type"] == "counter" and families[HISTOGRAM]["type"] == "histogram"
    result: dict[tuple[str, str, str], dict] = {}
    for _, labels, value in families[COUNTER]["samples"]:
        assert set(labels) == LABELS, labels
        key = (labels["http_route"], labels["http_request_method"], labels["http_response_status_code"])
        assert key not in result and value == int(value) and value >= 1
        result[key] = {"total": int(value), "buckets": [], "sum": None, "count": None}
    for name, labels, value in families[HISTOGRAM]["samples"]:
        le = labels.pop("le", None)
        assert set(labels) == LABELS, labels
        entry = result[(labels["http_route"], labels["http_request_method"], labels["http_response_status_code"])]
        if name.endswith("_bucket"):
            assert le is not None
            entry["buckets"].append((le, value))
        elif name.endswith("_sum"):
            assert le is None and entry["sum"] is None
            entry["sum"] = value
        else:
            assert le is None and entry["count"] is None
            entry["count"] = value
    for key, entry in result.items():
        bounds = [le for le, _ in entry["buckets"]]
        counts = [n for _, n in entry["buckets"]]
        assert bounds == LE, key
        assert counts == sorted(counts), key  # накопленные корзины не убывают
        assert counts[-1] == entry["count"] == entry["total"], key  # +Inf = _count = счётчик
        assert entry["sum"] >= 0, key
    return result


def totals(text: str) -> dict[tuple[str, str, str], int]:
    return {key: entry["total"] for key, entry in series(text).items()}


@pytest.fixture
def metrics_client():
    with client_for(metrics_enabled=True) as service:
        yield service


@pytest.fixture
def metrics_frontend(frontend_dist):
    with client_for(metrics_enabled=True, frontend_dist=frontend_dist) as service:
        yield service


def _boom(*args, **kwargs):
    raise RuntimeError(f"сбой на задаче {MARKER}")


# Выключено: адреса нет, сбор не ведётся


def test_metrics_path_is_404_like_any_unknown_path_when_disabled(client):
    # client — обе сборки, без статики и со статикой на «/»: index.html с кодом 200 вместо 404 не отдаётся
    metrics, unknown = client.get("/metrics"), client.get("/no-such-page")
    assert metrics.status_code == unknown.status_code == 404
    assert error_of(metrics) == error_of(unknown) == {"code": "not_found", "message": "Не найдено", "details": []}
    assert metrics.headers["content-type"] == unknown.headers["content-type"] == "application/json"
    assert metrics.headers["cache-control"] == "no-store" and 'id="root"' not in metrics.text
    for name, value in {**SECURITY_HEADERS, "Content-Security-Policy": CSP}.items():
        assert metrics.headers[name] == value, name
    assert client.post("/metrics").status_code == client.post("/no-such-page").status_code
    assert "/metrics" not in client.get("/openapi.json").json()["paths"]


def test_nothing_is_collected_when_disabled(client):
    client.get("/api/meta")
    client.get("/metrics")
    assert client.app.state.metrics is None
    edge = client.app.middleware_stack
    assert type(edge).__name__ == "EdgeMiddleware" and edge.metrics is None and edge.routes is None


# Формат вывода


def test_enabled_metrics_follow_text_format(metrics_client):
    metrics_client.get("/api/meta")
    metrics_client.post("/api/recommend", json={"task": "налоги"})
    response = metrics_client.get("/metrics")
    assert response.status_code == 200 and response.headers["content-type"] == CONTENT_TYPE
    families = parse(response.text)
    assert {name: (f["type"], f["help"]) for name, f in families.items()} == {
        COUNTER: ("counter", "Number of HTTP server requests."),
        HISTOGRAM: ("histogram", "Duration of HTTP server requests."),
    }
    found = series(response.text)
    assert set(found) == {("/api/meta", "GET", "200"), ("/api/recommend", "POST", "200")}
    assert [float(le) for le in LE] == [*DURATION_BUCKETS, math.inf]
    assert response.text.isascii()


def test_fresh_service_exposes_families_without_samples(metrics_client):
    text = metrics_client.get("/metrics").text
    assert text == (
        f"# HELP {COUNTER} Number of HTTP server requests.\n# TYPE {COUNTER} counter\n"
        f"# HELP {HISTOGRAM} Duration of HTTP server requests.\n# TYPE {HISTOGRAM} histogram\n"
    )


# Счётчик и гистограмма по маршруту, методу и коду


def test_counter_and_histogram_by_route_method_and_status(metrics_client, monkeypatch):
    service = metrics_client
    etag = None
    for _ in range(3):
        etag = service.get("/api/meta").headers["etag"]
    service.get("/api/meta", headers={"if-none-match": etag})
    for _ in range(2):
        service.post("/api/recommend", json={"task": "Хочу начать продвигать свою кофейню"})
    service.post("/api/recommend", json={"limit": 0})
    service.post("/api/recommend", content=b"x" * (MAX_BODY_BYTES + 1), headers=JSON)
    service.get("/api/recommend")
    service.head("/api/live")
    service.get("/api/nothing")
    service.get("/no-such-page")
    service.get("/")
    monkeypatch.setattr(routes, "recommend", _boom)
    service.post("/api/recommend", json={"task": "налоги"})
    assert totals(service.get("/metrics").text) == {
        ("/api/meta", "GET", "200"): 3,
        ("/api/meta", "GET", "304"): 1,
        ("/api/recommend", "POST", "200"): 2,
        ("/api/recommend", "POST", "422"): 1,
        ("/api/recommend", "POST", "413"): 1,  # шаблон есть и у ответа, который дал предел тела до маршрута
        ("/api/recommend", "POST", "500"): 1,
        ("/api/recommend", "GET", "405"): 1,
        ("/api/live", "HEAD", "405"): 1,
        ("none", "GET", "404"): 2,  # без сборки интерфейса и /api/…, и прочий неизвестный адрес — без маршрута
        ("/", "GET", "200"): 1,  # корень сборки без интерфейса
    }


def test_counts_grow_by_one_per_request(metrics_client):
    before = totals(metrics_client.get("/metrics").text)
    for expected in range(1, 6):
        metrics_client.get("/api/live")
        assert totals(metrics_client.get("/metrics").text) == {**before, ("/api/live", "GET", "200"): expected}


def test_every_api_route_is_labelled_with_its_template(metrics_client):
    paths = metrics_client.get("/openapi.json").json()["paths"]
    assert set(paths) == API_ROUTES  # при новом маршруте дополните API_ROUTES
    expected: dict = {}
    for path, operations in paths.items():
        for method in operations:
            body = {"task": "налоги"} if method == "post" else None
            response = metrics_client.request(method.upper(), path, json=body)
            key = (path, method.upper(), str(response.status_code))
            expected[key] = expected.get(key, 0) + 1
    found = totals(metrics_client.get("/metrics").text)
    assert {k: v for k, v in found.items() if k[0] in API_ROUTES} == expected
    assert ("/openapi.json", "GET", "200") in found


def test_static_files_and_unknown_paths_under_frontend(metrics_frontend):
    statuses = {path: metrics_frontend.get(path).status_code for path in
                ("/", "/index.html", "/kit.html", "/assets/main.js", "/missing.html", "/nothing/here")}
    assert statuses == {"/": 200, "/index.html": 200, "/kit.html": 200, "/assets/main.js": 200,
                        "/missing.html": 404, "/nothing/here": 404}
    metrics_frontend.post("/index.html")
    metrics_frontend.get("/docs")
    metrics_frontend.get("/api/nothing")
    assert totals(metrics_frontend.get("/metrics").text) == {
        (STATIC_ROUTE, "GET", "200"): 4,
        (STATIC_ROUTE, "GET", "404"): 2,
        (STATIC_ROUTE, "POST", "405"): 1,
        ("/docs", "GET", "200"): 1,
        ("none", "GET", "404"): 1,  # пути /api статика не перехватывает
    }


@pytest.mark.parametrize("frontend", [False, True], ids=["api_only", "with_frontend"])
def test_metrics_scrapes_are_not_counted(frontend, frontend_dist):
    settings = {"frontend_dist": frontend_dist} if frontend else {}
    with client_for(metrics_enabled=True, **settings) as service:
        for _ in range(5):
            assert service.get("/metrics").status_code == 200
        assert totals(service.get("/metrics").text) == {}


def test_other_methods_on_metrics_path():
    # Без статики маршрут /metrics отвечает 405 и тоже не учитывается. Со статикой на «/» POST и HEAD
    # достаются ей, как и на /docs: Mount совпадает полностью, а маршрут только GET — лишь по пути
    with client_for(metrics_enabled=True) as service:
        wrong = service.post("/metrics")
        assert wrong.status_code == 405 and wrong.headers["allow"] == "GET"
        assert error_of(wrong)["code"] == "method_not_allowed"
        assert totals(service.get("/metrics").text) == {}


def test_other_methods_on_metrics_path_with_frontend(metrics_frontend):
    assert metrics_frontend.post("/metrics").status_code == metrics_frontend.post("/docs").status_code == 405
    assert metrics_frontend.head("/metrics").status_code == 404
    assert totals(metrics_frontend.get("/metrics").text) == {
        (STATIC_ROUTE, "POST", "405"): 2,
        (STATIC_ROUTE, "HEAD", "404"): 1,
    }


def test_duration_is_in_seconds(metrics_client, monkeypatch):
    # Маршрут вызывает recommend из ranking.policy через имя routes.recommend: его тест и подменяет
    real = recommend

    def slow(*args, **kwargs):
        time.sleep(0.06)
        return real(*args, **kwargs)

    monkeypatch.setattr(routes, "recommend", slow)
    started = time.perf_counter()
    assert metrics_client.post("/api/recommend", json={"task": "налоги"}).status_code == 200
    elapsed = time.perf_counter() - started
    entry = series(metrics_client.get("/metrics").text)[("/api/recommend", "POST", "200")]
    buckets = dict(entry["buckets"])
    assert 0.06 <= entry["sum"] <= elapsed
    assert buckets["0.05"] == 0 and buckets["+Inf"] == 1


def test_response_not_started_is_not_counted(metrics_client):
    # Клиент отключился, не дослав тело: BodyLimitMiddleware не отвечает, и наблюдения нет
    sent = []

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/api/recommend", "root_path": "", "query_string": b"",
             "headers": [(b"content-type", b"application/json")], "http_version": "1.1", "scheme": "http"}
    metrics_client.get("/api/live")  # стек приложения собран
    asyncio.run(metrics_client.app(scope, receive, send))
    assert sent == []
    assert totals(metrics_client.get("/metrics").text) == {("/api/live", "GET", "200"): 1}


# Кардинальность: запрос не создаёт новых значений меток


def test_random_paths_methods_and_bodies_do_not_create_label_values(metrics_frontend):
    rng = random.Random(20261112)
    alphabet = string.ascii_letters + string.digits + "-_"
    methods = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "FOO", "PROPFIND", "BREW", "M-SEARCH"]
    for i in range(300):
        word = "".join(rng.choices(alphabet, k=rng.randint(1, 40)))
        path = f"/api/{word}" if i % 2 else f"/{word}/{i}"
        metrics_frontend.request(rng.choice(methods), f"{path}?q={word}&id={i}")
    for _ in range(30):
        task = "".join(rng.choices(string.ascii_letters + "абвгдеёжз ", k=rng.randint(1, 200)))
        metrics_frontend.post("/api/recommend", json={"task": task, "limit": rng.randint(1, 10)})
    found = totals(metrics_frontend.get("/metrics").text)
    routes_seen = {route for route, _, _ in found}
    methods_seen = {method for _, method, _ in found}
    assert routes_seen == {"none", STATIC_ROUTE, "/api/recommend"}
    assert methods_seen <= KNOWN_METHODS | {"_OTHER"} and "_OTHER" in methods_seen
    # Разные тела — один ряд подбора; все 330 запросов уложились в несколько рядов
    assert found[("/api/recommend", "POST", "200")] == 30
    assert len(found) <= 2 * 7 * 2 + 1 and sum(found.values()) == 330


def test_unknown_method_names_collapse_to_other():
    metrics = HttpMetrics()
    for method in ("FOO", "get", "Post", "PROPFIND", "M-SEARCH", "GET\n", 'GE"T', ""):
        metrics.observe("/api/meta", method, 405, 0.001)
    metrics.observe("/api/meta", "GET", 200, 0.001)
    assert totals(metrics.render()) == {("/api/meta", "_OTHER", "405"): 8, ("/api/meta", "GET", "200"): 1}


def test_label_values_are_escaped():
    # Шаблоны задаёт код, но экранирование не даёт значению метки сломать строку формата
    metrics = HttpMetrics()
    metrics.observe('/odd\\"\npath', "GET", 200, 0.001)
    text = metrics.render()
    assert 'http_route="/odd\\\\\\"\\npath"' in text
    assert totals(text) == {('/odd\\"\npath', "GET", "200"): 1}


# Корзины гистограммы


def test_bucket_boundaries_are_inclusive_and_cumulative():
    metrics = HttpMetrics()
    values = [0.0, 0.005, 0.0050001, 0.1, 0.10001, 1.0, 9.99, 10.0, 10.5, 120.0]
    for value in values:
        metrics.observe("/api/recommend", "POST", 200, value)
    entry = series(metrics.render())[("/api/recommend", "POST", "200")]
    expected = [sum(1 for v in values if v <= float(le)) for le in LE]
    assert [n for _, n in entry["buckets"]] == expected
    assert expected[:2] == [2, 3] and expected[-2:] == [8, 10]  # 0,005 входит в le="0.005"; 10,5 и 120 — только +Inf
    assert math.isclose(entry["sum"], sum(values)) and entry["count"] == len(values)


# Потоки


def test_concurrent_observations_are_not_lost_and_snapshots_stay_consistent():
    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # частые переключения потоков: гонка проявилась бы чаще
    try:
        metrics = HttpMetrics()
        threads, per_thread = 8, 3000
        keys = [("/api/recommend", "POST", 200), ("/api/meta", "GET", 200), ("/api/meta", "GET", 304)]
        start = threading.Barrier(threads + 1)
        done = threading.Event()
        snapshots: list[str] = []

        def writer(seed: int) -> None:
            rng = random.Random(seed)
            start.wait()
            for i in range(per_thread):
                route, method, status = keys[i % len(keys)]
                metrics.observe(route, method, status, rng.choice([0.001, 0.02, 0.3, 4.0, 11.0]))

        def reader() -> None:
            start.wait()
            while not done.is_set():
                snapshots.append(metrics.render())

        with ThreadPoolExecutor(max_workers=threads + 1) as pool:
            scrape = pool.submit(reader)
            writes = [pool.submit(writer, seed) for seed in range(threads)]
            for future in writes:
                future.result()
            done.set()
            scrape.result()
    finally:
        sys.setswitchinterval(previous)
    for text in snapshots:
        series(text)  # в каждом снимке счётчик = _count = +Inf, корзины не убывают
    assert len(snapshots) > 1
    found = totals(metrics.render())
    assert sum(found.values()) == threads * per_thread
    assert found == {(r, m, str(s)): threads * per_thread // len(keys) for r, m, s in keys}


def test_concurrent_requests_are_all_counted(metrics_client):
    requests = 120
    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(lambda _: metrics_client.get("/api/live").status_code, range(requests)))
    assert statuses == [200] * requests
    assert totals(metrics_client.get("/metrics").text) == {("/api/live", "GET", "200"): requests}


# Заголовки, схема OpenAPI, данные запроса


def test_metrics_response_headers(metrics_client):
    metrics_client.get("/api/live")  # один ряд — уже больше килобайта: ответ сжимается, как любой другой
    plain = metrics_client.get("/metrics", headers={"accept-encoding": "identity"})
    zipped = metrics_client.get("/metrics", headers={"accept-encoding": "gzip"})
    for response in (plain, zipped):
        assert response.status_code == 200 and response.headers["content-type"] == CONTENT_TYPE
        for name, value in {**SECURITY_HEADERS, "Content-Security-Policy": CSP}.items():
            assert response.headers.get_list(name) == [value], name
        assert response.headers["cache-control"] == "no-store"
        assert HEX32.fullmatch(response.headers["x-request-id"])
        assert "server-timing" not in response.headers and "etag" not in response.headers
        assert not [name for name in response.headers if name.lower().startswith("access-control-")]
    assert "content-encoding" not in plain.headers and zipped.headers["content-encoding"] == "gzip"
    assert zipped.text == plain.text and len(plain.content) >= 1024
    rid = metrics_client.get("/metrics", headers={"x-request-id": "scrape-1"}).headers["x-request-id"]
    assert rid == "scrape-1"


def test_metrics_endpoint_is_not_in_openapi(metrics_client):
    enabled = metrics_client.get("/openapi.json").json()
    with client_for() as disabled_client:
        disabled = disabled_client.get("/openapi.json").json()
    assert "/metrics" not in enabled["paths"] and enabled == disabled


def test_no_task_text_or_profile_data_in_metrics(metrics_client, monkeypatch):
    profile = metrics_client.get("/api/profiles").json()["profiles"][0]
    history = [{"material_id": MARKER, "event": "complete", "seq": 1}]
    body = {"task": f"Продвижение кофейни {MARKER}", "profile_id": profile["id"], "history": history, "stage": "start"}
    marked = {"x-request-id": MARKER, "traceparent": f"00-{'a' * 32}-{'b' * 16}-01", "user-agent": MARKER}
    metrics_client.post("/api/recommend", json=body, headers=marked)
    metrics_client.post("/api/compare", json=body)
    metrics_client.post("/api/recommend", json={"profile_id": profile["id"], "task": profile["task"]})
    metrics_client.post("/api/recommend", json={"task": MARKER * 400})
    metrics_client.post("/api/recommend", json={MARKER: MARKER})
    metrics_client.get(f"/api/{MARKER}?task={MARKER}")
    metrics_client.get(f"/{MARKER}")
    monkeypatch.setattr(routes, "recommend", _boom)
    metrics_client.post("/api/recommend", json=body)
    text = metrics_client.get("/metrics").text
    assert sum(totals(text).values()) == 9
    for secret in (MARKER, profile["id"], profile["task"], profile["label"], "кофейн", "сбой", "aaaaaaaa"):
        assert secret not in text, secret
    assert text.isascii()
