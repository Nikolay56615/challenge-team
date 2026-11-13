"""Контракт API, ошибки, ссылки и демо-режим (docs/plan.md, 4.4–4.6; проверки S2–S6).

Фикстура `client` запускает каждый тест дважды: без собранного интерфейса и со статикой на `/`.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.config import DATA_DIR

from .conftest import client_for, error_of

P01 = {
    "task": "Хочу начать продвигать свою кофейню, с чего начать?",
    "stage": "start",
    "experience": "none",
    "industry": "horeca",
    "history": [],
}
P02 = {
    "task": "Нужно выстроить системное продвижение и считать его эффективность",
    "stage": "growth",
    "experience": "experienced",
    "format_pref": "course",
    "history": [
        {"material_id": "M01", "event": "view", "seq": 1},
        {"material_id": "M03", "event": "complete", "seq": 2},
        {"material_id": "M07", "event": "view", "seq": 3},
    ],
}


def test_health_and_meta(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    catalog = health.json()["catalog"]
    assert catalog["source"] == "synthetic" and catalog["size"] == 23 and catalog["disabled_features"] == []
    assert catalog["coverage"]["materials"] == 23
    meta = client.get("/api/meta").json()
    assert [t["value"] for t in meta["topics"]] == ["start", "taxes_law", "finance", "marketing", "sales", "operations"]
    assert len(meta["industries"]) == 10 and meta["max_task_length"] == 300 and meta["demo_mode"] is True


def test_profiles_in_demo_mode(client):
    body = client.get("/api/profiles").json()
    assert [p["id"] for p in body["profiles"]][:2] == ["P01", "P02"]
    # P11 и P12 — пилот «похожие курсы»: пустая задача и курс в истории (docs/plan.md, 2.6)
    assert [p["id"] for p in body["profiles"]] == [f"P{n:02d}" for n in range(1, 13)]
    assert body["profiles"][1]["history"][1] == {"material_id": "M03", "event": "complete", "seq": 2}


def test_recommend_p01_contract(client):
    response = client.post("/api/recommend", json=P01)
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    body = response.json()
    assert body["status"] == "strong" and body["method"] == "personal"
    assert [i["material_id"] for i in body["items"]] == ["M01", "M07", "M04", "M08", "M03"]
    first = body["items"][0]
    assert first["rank"] == 1 and first["link_allowed"] is True and first["url"].startswith("https://")
    assert first["access_label"] == "Бесплатно" and first["format_label"] == "Чек-лист"
    assert first["reasons"] and first["next_step"]
    assert first["contributions"]["topic"] == 3.0
    assert [s["material_id"] for s in body["route"]["steps"]] == ["M01", "M04", "M03"]
    assert body["message"].startswith("Нашли 8 материалов по теме «Продвижение».")
    assert set(body) == {
        "request_id", "method", "catalog", "status", "detected_topics", "message", "clarification", "items", "route",
        "total_candidates",
    }


def test_recommend_p02_paid_cards_and_flags(client):
    body = client.post("/api/recommend", json=P02).json()
    items = {i["material_id"]: i for i in body["items"]}
    assert body["items"][0]["material_id"] == "M02"
    m02 = items["M02"]
    assert m02["is_paid"] and m02["short_benefit"] and m02["link_allowed"] and m02["url"]
    m05 = items["M05"]
    assert m05["is_paid"] and m05["short_benefit"] and m05["link_allowed"] is False and m05["url"] is None
    assert items["M07"]["flags"] == [{"code": "viewed", "label": "Вы уже открывали"}]


def test_free_card_never_sends_benefit(client):
    body = client.post("/api/recommend", json=P01).json()
    assert all(i["short_benefit"] is None for i in body["items"] if not i["is_paid"])


def test_parallel_requests_keep_profiles_apart(client):
    # S2: одновременные запросы P01 и P02 получают каждый свою выдачу, причины и пометки
    expected = {
        "P01": client.post("/api/recommend", json=P01).json(),
        "P02": client.post("/api/recommend", json=P02).json(),
    }
    jobs = [("P01", P01), ("P02", P02)] * 20
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda job: (job[0], client.post("/api/recommend", json=job[1]).json()), jobs))
    for name, body in results:
        want = expected[name]
        assert [i["material_id"] for i in body["items"]] == [i["material_id"] for i in want["items"]]
        assert [i["reasons"] for i in body["items"]] == [i["reasons"] for i in want["items"]]
        assert [i["flags"] for i in body["items"]] == [i["flags"] for i in want["items"]]


def test_profile_id_substitutes_history_only_in_demo_mode(client):
    with_profile = client.post("/api/recommend", json={**P02, "history": None, "profile_id": "P02"}).json()
    assert any(i["flags"] for i in with_profile["items"])
    explicit = client.post("/api/recommend", json={**P02, "history": [], "profile_id": "P02"}).json()
    assert not any(i["flags"] for i in explicit["items"])
    with client_for(demo_mode=False) as production:
        assert error_of(production.get("/api/profiles"))["code"] == "not_found"
        body = production.post("/api/recommend", json={**P02, "history": None, "profile_id": "P02"}).json()
        assert not any(i["flags"] for i in body["items"])  # S3: история только из запроса


def test_compare_baseline_same_personal_differs(client):
    first = client.post("/api/compare", json=P01).json()
    second = client.post("/api/compare", json=P02).json()
    base1 = [i["material_id"] for i in first["baseline"]["items"]]
    base2 = [i["material_id"] for i in second["baseline"]["items"]]
    assert base1 == base2 == ["M03", "M02", "M01", "M07", "M05"]
    first_ids = [i["material_id"] for i in first["personal"]["items"]]
    assert first_ids != [i["material_id"] for i in second["personal"]["items"]]
    assert first["diff"]["changed_positions"] == 5 and first["diff"]["compared_positions"] == 5
    assert first["baseline"]["items"][0]["reasons"] == ["Совпадает тема «Продвижение»"]


def test_empty_task_is_cold_start(client):
    body = client.post("/api/recommend", json={"task": ""}).json()
    assert body["status"] == "cold"
    assert len(body["items"]) == 5 and body["clarification"]["question"] == "С чего хотите начать?"


def test_validation_errors_have_clear_messages(client):
    cases = [
        ({"task": "а" * 301}, "Запрос длиннее 300 символов", "task"),
        ({"task": "а" * 10_000}, "Запрос длиннее 300 символов", "task"),
        ({"stage": "unknown"}, "Недопустимое значение поля «стадия»", "stage"),
        (
            {"history": [{"material_id": "M01", "event": "view", "seq": i} for i in range(201)]},
            "История длиннее 200 событий",
            "history",
        ),
        ({"limit": 0}, "Число материалов должно быть от 1 до 10", "limit"),
        ({"limit": 11}, "Число материалов должно быть от 1 до 10", "limit"),
        ({"surprise": 1}, "Неизвестное поле «surprise»", "surprise"),
        ({"method": "magic"}, "Недопустимое значение поля «метод»", "method"),
    ]
    for payload, message, field in cases:
        response = client.post("/api/recommend", json=payload)
        assert response.status_code == 422, payload
        error = error_of(response)
        assert error["code"] == "validation_error"
        assert error["message"] == message
        assert error["details"][0]["field"].split(".")[0] == field


@pytest.mark.parametrize(
    ("limit", "message"),
    [
        (1, "Запрос длиннее 1 символа"),
        (2, "Запрос длиннее 2 символов"),
        (21, "Запрос длиннее 21 символа"),
        (22, "Запрос длиннее 22 символов"),
        (111, "Запрос длиннее 111 символов"),
        (300, "Запрос длиннее 300 символов"),
    ],
)
def test_length_message_uses_genitive(limit, message):
    # Оба пути дают одну фразу: рабочий предел MAX_TASK_LENGTH и жёсткий предел схемы в 2000 символов
    with client_for(max_task_length=limit) as service:
        over_limit = service.post("/api/recommend", json={"task": "а" * (limit + 1)})
        over_schema = service.post("/api/recommend", json={"task": "а" * 2001})
    for response in (over_limit, over_schema):
        assert response.status_code == 422
        assert error_of(response) == {
            "code": "validation_error", "message": message, "details": [{"field": "task", "message": message}]
        }


def test_invalid_json_is_422(client):
    response = client.post("/api/recommend", content=b"{not json", headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert error_of(response)["message"] == "Тело запроса не является корректным JSON"


def test_markup_in_task_is_returned_as_plain_text(client):
    task = "<b>наследство</b> <script>alert(1)</script>"
    body = client.post("/api/recommend", json={"task": task}).json()
    assert body["status"] == "none"
    assert "<b>наследство</b>" in body["message"]  # строка не интерпретируется и не экранируется сервером


def test_unknown_api_path_is_json_404(client):
    response = client.get("/api/nothing")
    assert response.status_code == 404 and error_of(response)["code"] == "not_found"


def test_root_without_frontend_build_explains():
    with client_for() as api_only:
        response = api_only.get("/")
    assert response.status_code == 200 and "npm run build" in response.json()["message"]


def test_fixture_links_and_paid_without_link(tmp_path):
    with client_for(catalog_source="file", catalog_path=_fixture_path()) as fixtures:
        body = fixtures.post("/api/recommend", json={"task": "продвижение", "limit": 10}).json()
        items = {i["material_id"]: i for i in body["items"]}
        assert items["F04"]["link_allowed"] is False and items["F04"]["url"] is None  # S5: схема ftp
        assert items["F03"]["link_allowed"] is False and items["F03"]["url"] is None
        assert "F06" not in items
        health = fixtures.get("/api/health").json()
        assert health["catalog"]["coverage"]["links_invalid_scheme"] == 1


def test_empty_catalog_gives_503(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"version": "empty", "materials": []}), encoding="utf-8")
    with client_for(catalog_source="file", catalog_path=path) as broken:
        for response in (broken.get("/api/health"), broken.post("/api/recommend", json={"task": "налоги"})):
            assert response.status_code == 503
            assert error_of(response)["code"] == "catalog_unavailable"


def test_catalog_without_signals_disables_feature(tmp_path):
    path = tmp_path / "nosignals.json"
    rows = [{"id": "N1", "title": "Статья о налогах", "format": "article", "topics": ["taxes_law"], "popularity": 1}]
    path.write_text(json.dumps({"version": "n", "materials": rows}), encoding="utf-8")
    with client_for(catalog_source="file", catalog_path=path) as service:
        catalog = service.get("/api/health").json()["catalog"]
        assert "signal" in catalog["disabled_features"]
        assert service.post("/api/recommend", json={"task": "налоговый режим"}).json()["status"] == "strong"


def _fixture_path():
    return DATA_DIR / "catalog.fixtures.json"
