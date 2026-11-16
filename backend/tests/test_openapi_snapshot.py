"""Снимок контракта API: `/openapi.json` против сохранённого `tests/openapi.snapshot.json` (кандидат W10).

Любое изменение схемы запроса или ответа, кодов ответа, путей и описаний меняет `/openapi.json`, и тест падает
с построчной разницей. Если изменение намеренное, снимок обновляется командой из папки backend:

    python -X utf8 -m tests.test_openapi_snapshot

Команда принимает пути дополнительных копий, например копии, из которой интерфейс генерирует типы:

    python -X utf8 -m tests.test_openapi_snapshot ../frontend/src/api/openapi.json

Снимок — JSON с ключами по алфавиту, отступом 2 и переводом строки в конце, кириллица без экранирования.
Схема не зависит от настроек: `/metrics` при METRICS_ENABLED и `/` без собранного интерфейса в схему не входят.
"""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

from .conftest import NO_FRONTEND, client_for

SNAPSHOT = Path(__file__).with_name("openapi.snapshot.json")
REFRESH = "python -X utf8 -m tests.test_openapi_snapshot"
MAX_DIFF_LINES = 200


def render(spec: dict) -> str:
    return json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def served_spec(**settings) -> dict:
    with client_for(**settings) as service:
        response = service.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


def test_openapi_matches_snapshot():
    current = render(served_spec())
    saved = SNAPSHOT.read_text(encoding="utf-8")
    if current != saved:
        diff = list(difflib.unified_diff(
            saved.splitlines(), current.splitlines(), "tests/openapi.snapshot.json", "/openapi.json", lineterm="", n=2
        ))
        shown = "\n".join(diff[:MAX_DIFF_LINES])
        more = f"\n… ещё {len(diff) - MAX_DIFF_LINES} строк" if len(diff) > MAX_DIFF_LINES else ""
        raise AssertionError(
            f"Контракт API изменился. Если изменение намеренное, обновите снимок: {REFRESH}\n{shown}{more}"
        )


def test_snapshot_does_not_depend_on_settings(frontend_dist):
    """Метрики, интерфейс, демо-режим и рабочий предел задачи схему не меняют."""
    reference = served_spec()
    variants = (
        {"metrics_enabled": True},
        {"frontend_dist": frontend_dist},
        {"demo_mode": False},
        {"max_task_length": 2000},
    )
    for variant in variants:
        assert served_spec(**variant) == reference, variant
    assert "/metrics" not in reference["paths"] and "/" not in reference["paths"]


def test_snapshot_is_canonical_json():
    text = SNAPSHOT.read_text(encoding="utf-8")
    assert text == render(json.loads(text)), f"снимок не в каноническом виде: {REFRESH}"


def test_errors_are_documented_with_the_error_envelope():
    """Каждый описанный код ошибки отвечает конвертом `{"error": {...}}`; модели FastAPI для 422 в схеме нет."""
    spec = served_spec()
    expected = {
        ("get", "/api/health"): {"503"}, ("get", "/api/live"): set(), ("get", "/api/ready"): {"503"},
        ("get", "/api/meta"): {"503"}, ("get", "/api/profiles"): {"404"},
        ("post", "/api/recommend"): {"413", "422", "503"}, ("post", "/api/compare"): {"413", "422", "503"},
        ("post", "/api/feed"): {"404", "413", "422", "503"}, ("get", "/api/users"): {"404", "422"},
        ("get", "/api/model-card"): {"404"},
    }
    found = {}
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            errors = {code for code in operation["responses"] if not code.startswith("2")}
            found[method, path] = errors
            for code in errors:
                schema = operation["responses"][code]["content"]["application/json"]["schema"]
                assert schema == {"$ref": "#/components/schemas/ErrorResponse"}, (method, path, code)
    assert found == expected
    assert not {"HTTPValidationError", "ValidationError"} & set(spec["components"]["schemas"])
    # problem_response всегда отдаёт все три поля, details — хотя бы пустым списком. В схеме они обязательные,
    # поэтому тип, сгенерированный для интерфейса, не делает details необязательным
    body = spec["components"]["schemas"]["ErrorBody"]
    assert sorted(body["required"]) == ["code", "details", "message"] and "default" not in body["properties"]["details"]


def main(argv: list[str]) -> int:
    with TestClient(create_app(Settings(frontend_dist=NO_FRONTEND))) as service:
        text = render(service.get("/openapi.json").json())
    for target in (SNAPSHOT, *map(Path, argv)):
        target.write_text(text, encoding="utf-8", newline="\n")
        print(f"записан {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
