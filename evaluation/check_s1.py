"""Проверка S1 (PLAN.md, 7.2): ответы API, журнал, ошибки и состав комплекта без утечек.

Что проверяется на тестовом клиенте, без сети и без запуска сервера:
- в ответах только поля контракта из `schemas.py`; у бесплатных материалов нет `short_benefit`,
  у материалов без разрешённой ссылки нет `url`; идентификаторов пользователей в контракте нет;
- журнал не содержит текст задачи, коды материалов из истории и значения полей, в том числе
  при ошибках 422 и 500;
- ошибки 404, 405, 413, 422 и 500 приходят в едином формате без трассировок, путей и текста исключений;
- на локальной копии: сводка `/api/health` без идентификаторов, названий и путей; в выдаче нет ссылок
  и описаний, названия — нейтральные подписи;
- в составе комплекта (корень репозитория без игнорируемых файлов) нет `.env`, баз SQLite, ключей и
  локальных путей автора.

Выводятся только агрегаты и статусы проверок. Код возврата 1 при любой неудаче.

Запуск из корня проекта:
  python -X utf8 evaluation/check_s1.py [data/local/catalog.sqlite3 [data/local/catalog-signals.sqlite3]]
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT
BACKEND = APP_DIR / "backend"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from app import schemas  # noqa: E402
from app.api import routes  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

NO_FRONTEND = Path("__no_frontend_build__")
SENTINEL_TASK = "СЕКРЕТНАЯ ЗАДАЧА QX7 про кофейню"
SENTINEL_ID = "ZZ-SENTINEL-77"
LEAK_WORDS = ("Traceback", ".py", "\\", "Exception", "Error(")
PATH_RE = re.compile(r"[\\/]|^[A-Za-z]:|Administrator")
ID_RE = re.compile(r"^(article|course|document|webinar|podcast):")
NEUTRAL_TITLE_RE = re.compile(r"^[^\d]+\d+$")
SKIP_DIRS = {"Personal", "local", "node_modules", "dist", ".venv", "__pycache__", ".pytest_cache", ".screenshots", ".git"}
FORBIDDEN_FILES = re.compile(r"(^\.env$|\.sqlite3(-.*)?$|\.pem$|\.key$|^id_rsa)", re.IGNORECASE)
FORBIDDEN_TEXT = ("Administrator", "C:\\Users", "BEGIN PRIVATE KEY", "ghp_", "AKIA", "sk-ant-", "xoxb-")
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".css", ".html", ".json", ".yaml", ".yml", ".md", ".txt", ".toml", ".example", ""}

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, note: str = "") -> None:
    results.append((name, bool(ok), note))
    print(f"{'PASS' if ok else 'FAIL'} {name}{' — ' + note if note else ''}")


def fields(model: type) -> set[str]:
    return set(model.model_fields)


class Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def client_for(**settings: Any) -> TestClient:
    settings.setdefault("frontend_dist", NO_FRONTEND)
    return TestClient(create_app(Settings(**settings)), raise_server_exceptions=False)


def leaves(value: Any) -> list[str]:
    """Все строковые листья JSON."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in [k, *leaves(v)]]
    if isinstance(value, list):
        return [s for v in value for s in leaves(v)]
    return []


def check_contract(client: TestClient) -> None:
    health = client.get("/api/health").json()
    check("health: поля контракта", set(health) == fields(schemas.HealthResponse)
          and set(health["catalog"]) == fields(schemas.HealthCatalog))
    meta = client.get("/api/meta").json()
    check("meta: поля контракта", set(meta) == fields(schemas.MetaResponse))
    profiles = client.get("/api/profiles").json()
    check("profiles: поля контракта", set(profiles) == {"profiles"}
          and all(set(p) == fields(schemas.ProfileOut) for p in profiles["profiles"]))

    bodies = {
        "P01": {"task": "Хочу начать продвигать свою кофейню, с чего начать?", "stage": "start", "experience": "none",
                "industry": "horeca", "history": []},
        "P02": {"profile_id": "P02", "task": "Как настроить рекламу, чтобы она окупалась", "stage": "growth",
                "experience": "some", "format_pref": "course"},
        "P05": {"task": "Хочу больше клиентов"},
        "empty": {},
    }
    item_fields = fields(schemas.ItemOut)
    extra_keys: Counter[str] = Counter()
    paid_seen = free_seen = 0
    benefit_bad = url_bad = 0
    for name, body in bodies.items():
        response = client.post("/api/recommend", json=body)
        data = response.json()
        ok = response.status_code == 200 and set(data) == fields(schemas.RecommendResponse)
        if data.get("clarification") is not None:
            ok = ok and set(data["clarification"]) == fields(schemas.Clarification)
        if data.get("route") is not None:
            ok = ok and set(data["route"]) == fields(schemas.Route)
        for item in data.get("items", []):
            extra_keys.update(set(item) - item_fields)
            ok = ok and set(item) == item_fields
            if item["is_paid"]:
                paid_seen += 1
                if not isinstance(item["short_benefit"], (str, type(None))):
                    benefit_bad += 1
            else:
                free_seen += 1
                if item["short_benefit"] is not None:
                    benefit_bad += 1
            if (item["url"] is None) != (not item["link_allowed"]):
                url_bad += 1
            if item["url"] is not None and not re.match(r"^https?://", item["url"]):
                url_bad += 1
        check(f"recommend {name}: поля контракта", ok, f"лишние ключи: {dict(extra_keys) or 'нет'}")
    check("карточки: short_benefit только у платных, url только при разрешённой ссылке",
          benefit_bad == 0 and url_bad == 0, f"платных {paid_seen}, бесплатных {free_seen}")
    compare = client.post("/api/compare", json=bodies["P02"]).json()
    check("compare: поля контракта", set(compare) == fields(schemas.CompareResponse)
          and set(compare["diff"]) == fields(schemas.CompareDiff)
          and all(set(compare[m]) == fields(schemas.RecommendResponse) for m in ("baseline", "personal")))
    user_fields = {k for k in item_fields | fields(schemas.RecommendResponse) if "user" in k}
    check("в контракте нет полей пользователя", not user_fields, f"request_id — случайный код из {len(compare['personal']['request_id'])} символов")


def check_logs_and_errors(client: TestClient) -> None:
    capture = Capture()
    capture.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.addHandler(capture)
    try:
        ok_response = client.post("/api/recommend", json={
            "task": SENTINEL_TASK, "stage": "start", "history": [{"material_id": SENTINEL_ID, "event": "view", "seq": 1}],
        })
        invalid = client.post("/api/recommend", json={"task": SENTINEL_TASK, "stage": SENTINEL_ID, "bogus": SENTINEL_ID})
        too_long = client.post("/api/recommend", json={"task": "я" * 2001})
        # Путь запроса журнал пишет законно (экранированный и усечённый), поэтому маркер в путь не ставится
        not_found = client.get("/api/no-such-path")
        wrong_method = client.get("/api/recommend")
        too_big = client.post("/api/recommend", content=b"{" + b" " * (65 * 1024) + b"}",
                              headers={"Content-Type": "application/json"})
        original = routes.recommend

        def boom(*_: Any, **__: Any) -> Any:
            raise RuntimeError(f"boom {SENTINEL_TASK}")

        routes.recommend = boom
        try:
            crashed = client.post("/api/recommend", json={"task": SENTINEL_TASK})
        finally:
            routes.recommend = original
    finally:
        root.removeHandler(capture)

    joined = "\n".join(capture.lines)
    check("журнал: нет текста задачи и кодов истории", SENTINEL_TASK not in joined and "QX7" not in joined
          and SENTINEL_ID not in joined and "boom" not in joined, f"строк журнала {len(capture.lines)}")
    check("журнал: есть строки запроса и сбоя", any("recommend id=" in line for line in capture.lines)
          and any("unhandled error: RuntimeError" in line for line in capture.lines))
    check("успешный запрос с историей отвечает 200", ok_response.status_code == 200)

    def error_shape(response, status: int, code: str) -> bool:
        body = response.json()
        error = body.get("error", {})
        text = json.dumps(body, ensure_ascii=False)
        return (response.status_code == status and set(body) == {"error"} and set(error) == {"code", "message", "details"}
                and error["code"] == code and len(error["details"]) <= 10
                and not any(word in text for word in LEAK_WORDS) and SENTINEL_TASK not in text)

    check("422: единый формат, без значений полей", error_shape(invalid, 422, "validation_error")
          and SENTINEL_ID not in json.dumps(invalid.json(), ensure_ascii=False))
    check("422: задача длиннее предела", error_shape(too_long, 422, "validation_error"))
    check("404: единый формат, путь не повторяется", error_shape(not_found, 404, "not_found")
          and "no-such-path" not in json.dumps(not_found.json()))
    check("405: единый формат и заголовок Allow", error_shape(wrong_method, 405, "method_not_allowed")
          and "allow" in {k.lower() for k in wrong_method.headers})
    check("413: тело больше 64 КБ", error_shape(too_big, 413, "payload_too_large"))
    check("500: без текста исключения и трассировки", error_shape(crashed, 500, "internal_error"))
    headers = {k.lower() for k in ok_response.headers}
    check("заголовки безопасности на ответе API", {"x-content-type-options", "referrer-policy", "x-frame-options",
                                                     "content-security-policy"} <= headers)


def check_sqlite(db: Path, signals: Path | None) -> None:
    client = client_for(catalog_source="sqlite", catalog_path=db, catalog_signals_path=signals)
    health = client.get("/api/health").json()
    strings = leaves(health["catalog"]["coverage"])
    suspicious = [s for s in strings if PATH_RE.search(s) or ID_RE.match(s)]
    check("копия, health: в сводке нет путей, идентификаторов и названий", not suspicious,
          f"строковых значений и ключей {len(strings)}, подозрительных {len(suspicious)}")
    check("копия, health: версия без пути", not PATH_RE.search(health["catalog"]["version"]))
    bodies = [
        {"task": "Хочу начать продвигать свою кофейню, с чего начать?", "stage": "start", "experience": "none", "industry": "horeca"},
        {"task": "Как выбрать налоговый режим"},
        {"task": "Как настроить рекламу, чтобы она окупалась", "stage": "growth", "format_pref": "course", "limit": 10},
        {},
    ]
    items = [item for body in bodies for item in client.post("/api/recommend", json=body).json()["items"]]
    titles_bad = sum(1 for item in items if not NEUTRAL_TITLE_RE.match(item["title"]))
    check("копия, карточки: нет ссылок и описаний", items and all(item["url"] is None and not item["link_allowed"]
                                                                and item["short_benefit"] is None for item in items),
          f"карточек {len(items)}")
    check("копия, карточки: названия — нейтральные подписи", titles_bad == 0, f"не по шаблону: {titles_bad}")
    text = json.dumps(items, ensure_ascii=False)
    check("копия, карточки: нет путей и имени автора", not re.search(r"Administrator|[A-Za-z]:\\", text))


def check_kit() -> None:
    counts: Counter[str] = Counter()
    forbidden_names: list[str] = []
    forbidden_text: list[str] = []
    total = 0
    for path in package_files():
        rel = path.relative_to(APP_DIR)
        total += 1
        counts[rel.parts[0] if len(rel.parts) > 1 else "."] += 1
        if FORBIDDEN_FILES.search(path.name) or path.suffix == ".pyc":
            forbidden_names.append(str(rel))
        if path.suffix.lower() in TEXT_SUFFIXES and path.stat().st_size < 2_000_000:
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if any(word in content for word in FORBIDDEN_TEXT):
                forbidden_text.append(str(rel))
    check("комплект: нет .env, баз SQLite, ключей и байткода", not forbidden_names, ", ".join(forbidden_names) or f"файлов {total}")
    check("комплект: нет локальных путей автора и ключей в тексте", not forbidden_text, ", ".join(forbidden_text) or "проверены текстовые файлы")
    print("Файлов по папкам комплекта: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))


def package_files():
    for base, dirs, files in os.walk(APP_DIR, followlinks=False):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
        for name in files:
            path = Path(base) / name
            if path != Path(__file__).resolve():
                yield path


def main(argv: list[str]) -> int:
    print("Синтетический каталог, тестовый клиент")
    client = client_for()
    check_contract(client)
    check_logs_and_errors(client)
    if len(argv) > 1:
        print("\nЛокальная копия")
        check_sqlite(Path(argv[1]), Path(argv[2]) if len(argv) > 2 else None)
    print("\nСостав комплекта")
    check_kit()
    failed = [name for name, ok, _ in results if not ok]
    print(f"\nИтог: {len(results) - len(failed)} из {len(results)} проверок пройдено" + (f"; не пройдено: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
