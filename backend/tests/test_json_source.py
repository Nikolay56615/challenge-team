"""Каталог из JSON: кодировка, типы полей, правило кодов материалов (PLAN.md, 2.5 и 4.4; проверка S6)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

import app.catalog.synthetic_source as synthetic_source
from app.catalog.models import CatalogError, valid_material_id
from app.catalog.synthetic_source import load_json_catalog
from app.profiles.synthetic import load_profiles
from app.schemas import HistoryEventIn

from .conftest import client_for, error_of

GOOD = {"id": "N1", "title": "Статья о налогах", "format": "article", "topics": ["taxes_law"], "popularity": 1}


def write_catalog(path, rows, encoding="utf-8"):
    path.write_text(json.dumps({"version": "t", "materials": rows}, ensure_ascii=False), encoding=encoding)
    return path


@pytest.mark.parametrize(
    "override",
    [
        {"popularity": "high"}, {"popularity": [1]}, {"popularity": True}, {"popularity": -1},
        {"popularity": float("nan")}, {"popularity": float("inf")}, {"popularity": 10**400},
        {"format": ["article"]}, {"level": ["intro"]}, {"access": {"x": 1}},
        {"recommended_next": 5}, {"recommended_next": "M01"}, {"topics": "taxes_law"}, {"signals": {"launch": 1}},
        {"stage": "start"}, {"industries": 5}, {"available": "false"}, {"available": 0},
        {"title": ["Статья"]}, {"id": 7},
    ],
    ids=lambda value: repr(value)[:30],
)
def test_wrongly_typed_row_is_skipped_and_counted(tmp_path, override):
    path = write_catalog(tmp_path / "catalog.json", [GOOD, {**GOOD, "id": "N2", **override}])
    catalog = load_json_catalog(path, source="file")
    assert list(catalog.materials) == ["N1"]
    assert catalog.coverage["skipped_records"] == 1


def test_service_starts_and_answers_with_a_bad_row(tmp_path):
    # Раньше одна такая запись роняла запуск: ValueError: could not convert string to float: 'high'
    path = write_catalog(tmp_path / "catalog.json", [GOOD, {**GOOD, "id": "N2", "popularity": "high"}])
    with client_for(catalog_source="file", catalog_path=path) as service:
        catalog = service.get("/api/health").json()["catalog"]
        assert catalog["size"] == 1 and catalog["coverage"]["skipped_records"] == 1
        assert service.post("/api/recommend", json={"task": "налоговый режим"}).status_code == 200


def test_nulls_in_optional_fields_keep_their_meaning(tmp_path):
    row = {**GOOD, "level": None, "access": None, "topics": None, "recommended_next": None, "popularity": None,
           "available": None, "duration_minutes": True}
    material = load_json_catalog(write_catalog(tmp_path / "catalog.json", [row]), source="file").materials["N1"]
    assert (material.level, material.topics, material.recommended_next, material.popularity_raw) == (None, (), (), 0.0)
    assert material.access == "paid" and material.available is False and material.duration_minutes is None


def test_utf8_with_bom_loads(tmp_path):
    # Так пишут Out-File и Set-Content -Encoding utf8 в Windows PowerShell 5.1
    path = write_catalog(tmp_path / "bom.json", [GOOD], encoding="utf-8-sig")
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert list(load_json_catalog(path, source="file").materials) == ["N1"]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ('{"materials": [{"id": "N1", "title": "Налоги"}]}'.encode("cp1251"), "Файл каталога не в кодировке UTF-8: catalog.json"),
        (b'{"materials": [', "Файл каталога не является корректным JSON: catalog.json"),
        (b'{"materials": []}', "Каталог пуст"),
    ],
)
def test_unreadable_file_gives_503_not_a_crash(tmp_path, caplog, content, message):
    path = tmp_path / "catalog.json"
    path.write_bytes(content)
    with pytest.raises(CatalogError, match=f"^{message}$"):
        load_json_catalog(path, source="file")
    with client_for(catalog_source="file", catalog_path=path) as service:
        response = service.get("/api/health")
    assert response.status_code == 503 and error_of(response)["code"] == "catalog_unavailable"
    assert f"catalog not loaded: {message}" in caplog.text


def test_unexpected_type_error_becomes_catalog_error(tmp_path, monkeypatch):
    def broken_summary(*args, **kwargs):
        raise TypeError("непредусмотренный тип")

    path = write_catalog(tmp_path / "catalog.json", [GOOD])
    monkeypatch.setattr(synthetic_source, "summarize", broken_summary)
    with pytest.raises(CatalogError, match="^В файле каталога неверные данные: catalog.json$"):
        load_json_catalog(path, source="file")
    with client_for(catalog_source="file", catalog_path=path) as service:
        assert service.get("/api/health").status_code == 503


@pytest.mark.parametrize(
    "value",
    ["M01", "course:42", "a-b_c", "x" * 64, "x" * 65, "", "M01\n", "статья-7", "article.101", "a b", "a/b", None, 7],
    ids=lambda value: repr(value) if len(repr(value)) <= 20 else f"len{len(value)}",
)
def test_loader_id_rule_matches_history_schema(value):
    try:
        HistoryEventIn(material_id=value, event="view", seq=1)
        accepted = True
    except ValidationError:
        accepted = False
    assert valid_material_id(value) is accepted


def test_every_loaded_material_can_be_marked_studied(tmp_path):
    valid = ["OK_1", "course:42", "a-b_c", "x" * 64]
    invalid = ["article.101", "статья-7", "article:" + "x" * 70]
    path = write_catalog(tmp_path / "catalog.json", [{**GOOD, "id": i} for i in valid + invalid])
    catalog = load_json_catalog(path, source="file")
    assert sorted(catalog.materials) == sorted(valid) and catalog.coverage["skipped_records"] == len(invalid)
    with client_for(catalog_source="file", catalog_path=path) as service:
        for material_id in valid:
            history = [{"material_id": material_id, "event": "complete", "seq": 1}]
            assert service.post("/api/recommend", json={"task": "налоги", "history": history}).status_code == 200


def test_profiles_skip_history_events_outside_id_rule(tmp_path):
    path = tmp_path / "profiles.json"
    history = [
        {"material_id": "M01", "event": "view", "seq": 1},
        {"material_id": "статья-7", "event": "view", "seq": 2},
        {"material_id": "M02", "event": "unknown", "seq": 3},
    ]
    payload = {"profiles": [{"id": "T1", "label": "Тест", "history": history}]}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")
    assert [e.material_id for e in load_profiles(path)["T1"].history] == ["M01"]
