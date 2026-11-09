from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.catalog.coverage import disabled_features, summarize
from app.catalog.loader import load_catalog
from app.catalog.models import Catalog
from app.catalog.synthetic_source import parse_materials
from app.config import DATA_DIR, Settings
from app.main import create_app
from app.profiles.synthetic import load_profiles
from app.ranking.base import Profile
from app.ranking.policy import recommend

NO_FRONTEND = Path("__no_frontend_build__")


@pytest.fixture(scope="session")
def catalog() -> Catalog:
    return load_catalog(Settings())


@pytest.fixture(scope="session")
def profiles():
    return load_profiles()


def make_profile(demo, **overrides) -> Profile:
    data = dict(
        task=demo.task,
        stage=demo.stage,
        experience=demo.experience,
        format_pref=demo.format_pref,
        industry=demo.industry,
        history=demo.history,
        limit=5,
    )
    data.update(overrides)
    return Profile(**data)


@pytest.fixture(scope="session")
def run(catalog, profiles):
    def _run(profile_id: str, method: str = "personal", catalog_override: Catalog | None = None, **overrides):
        return recommend(catalog_override or catalog, make_profile(profiles[profile_id], **overrides), method)

    return _run


def ids(outcome) -> list[str]:
    return [item.material.id for item in outcome.items]


def catalog_from_payloads(*payloads: dict, version: str = "test") -> Catalog:
    rows: list[dict] = []
    for payload in payloads:
        rows.extend(payload["materials"])
    materials, stats = parse_materials({"version": version, "popularity_scale": "single", "materials": rows})
    return Catalog(
        materials={m.id: m for m in materials},
        source="file",
        version=version,
        disabled_features=disabled_features(materials),
        coverage=summarize(materials, **stats),
    )


def read_json(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def frontend_dist(tmp_path_factory) -> Path:
    """Временная сборка интерфейса: статика подключена к `/`, как в Docker и при запуске по README."""
    dist = tmp_path_factory.mktemp("dist")
    (dist / "index.html").write_text('<!doctype html><div id="root"></div>', encoding="utf-8")
    (dist / "kit.html").write_text('<!doctype html><div id="kit"></div>', encoding="utf-8")
    (dist / "assets").mkdir()
    (dist / "assets" / "main.js").write_text("export {};", encoding="utf-8")
    return dist


@pytest.fixture(params=["api_only", "with_frontend"])
def client(request):
    # Контракт API проверяется в обеих сборках: без статики и со статикой на `/`
    dist = request.getfixturevalue("frontend_dist") if request.param == "with_frontend" else NO_FRONTEND
    with client_for(frontend_dist=dist) as test_client:
        yield test_client


@pytest.fixture
def frontend_client(frontend_dist):
    with client_for(frontend_dist=frontend_dist) as test_client:
        yield test_client


def client_for(**settings) -> TestClient:
    settings.setdefault("frontend_dist", NO_FRONTEND)
    return TestClient(create_app(Settings(**settings)))


def error_of(response) -> dict:
    body = response.json()
    assert set(body) == {"error"}
    return body["error"]


@pytest.fixture
def restore_log_levels():
    """create_app меняет уровни журналов процесса; после теста они возвращаются."""
    names = ("app", "uvicorn", "uvicorn.error", "uvicorn.access")
    saved = {name: logging.getLogger(name).level for name in names}
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)
