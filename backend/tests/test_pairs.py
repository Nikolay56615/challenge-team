"""Пары совместных записей: разбор, отбрасывание, загрузка и сводка (docs/plan.md, раздел 9, решение 2026-11-11).

Синтетические пары `data/course-pairs.synthetic.json` подключаются к синтетическому каталогу без настроек,
явный CATALOG_PAIRS_PATH их заменяет, источники sqlite и file получают пары только из CATALOG_PAIRS_PATH.
Без пар признак co_enrollment отключён, а каталог загружается. В сводке и журнале нет кодов и путей.
"""

from __future__ import annotations

import json
import logging
import re

import pytest

from app.catalog.loader import SYNTHETIC_PAIRS, load_catalog, pairs_path
from app.catalog.models import CatalogError
from app.catalog.pairs import DROP_REASONS, PAIRS_STATES, load_course_pairs, parse_pairs
from app.config import DATA_DIR, Settings

from .conftest import catalog_from_payloads, client_for, read_json

SYNTHETIC_COURSES = {"M02", "M08", "L02", "A03", "S03", "O03"}
# Код материала в сводке выдал бы данные: в агрегатах их быть не должно
MATERIAL_CODE = re.compile(r"\b(?:[A-Z]\d{2}|F\d{2}|course:)")


def pair(a: str, b: str, together: int, a_total: int, b_total: int) -> dict:
    return {"a": a, "b": b, "together": together, "a_total": a_total, "b_total": b_total}


def courses_catalog():
    rows = [
        {"id": "C1", "title": "Курс «Один»", "format": "course", "topics": ["sales"], "popularity": 10},
        {"id": "C2", "title": "Курс «Два»", "format": "course", "topics": ["finance"], "popularity": 20},
        {"id": "C3", "title": "Курс «Три»", "format": "course", "topics": ["finance"], "popularity": 30,
         "available": False},
        {"id": "A1", "title": "Статья", "format": "article", "topics": ["sales"], "popularity": 40},
    ]
    return catalog_from_payloads({"materials": rows})


def test_synthetic_pairs_file_is_consistent():
    """Синтетический файл правдоподобен: N не больше слушателей, у курса одно число слушателей."""
    payload = read_json("course-pairs.synthetic.json")
    assert set(payload) == {"version", "note", "pairs"} and payload["note"]
    catalog = load_catalog(Settings())
    totals: dict[str, set[int]] = {}
    together: dict[str, int] = {}
    for row in payload["pairs"]:
        assert {row["a"], row["b"]} <= SYNTHETIC_COURSES and row["a"] != row["b"]
        assert all(catalog.materials[code].format == "course" for code in (row["a"], row["b"]))
        assert 0 < row["together"] <= min(row["a_total"], row["b_total"])
        totals.setdefault(row["a"], set()).add(row["a_total"])
        totals.setdefault(row["b"], set()).add(row["b_total"])
        for code in (row["a"], row["b"]):
            together[code] = together.get(code, 0) + row["together"]
    assert all(len(values) == 1 for values in totals.values())
    assert all(together[code] <= next(iter(totals[code])) for code in together)
    counts = [row["together"] for row in payload["pairs"]]
    assert sum(n >= 10 for n in counts) >= 3 and sum(n < 10 for n in counts) >= 3 and 10 in counts


def test_synthetic_catalog_loads_synthetic_pairs_by_default():
    catalog = load_catalog(Settings())
    assert pairs_path(Settings()) == SYNTHETIC_PAIRS == DATA_DIR / "course-pairs.synthetic.json"
    assert catalog.course_pairs is not None and "co_enrollment" not in catalog.disabled_features
    assert catalog.disabled_features == ()
    summary = catalog.coverage["course_pairs"]
    assert summary == {
        "source": "loaded", "min_support": 10, "pairs": 7, "courses": 5,
        "dropped": {"below_support": 8, "unknown_course": 0, "not_course": 0, "inconsistent": 0, "duplicates": 0,
                    "invalid": 0},
        "total_conflicts": 0,
    }
    pairs = catalog.course_pairs
    assert pairs.size == 7 and pairs.neighbours("M08") == {"M02": 36, "L02": 48, "A03": 12}
    assert pairs.neighbours("O03") == {} and pairs.totals["O03"] == 25  # пары O03 ниже порога
    assert pairs.neighbours("M02")["L02"] == 10  # пара ровно на пороге загружается


def test_min_support_from_settings_filters_pairs():
    strict = load_catalog(Settings(pairs_min_support=40))
    assert strict.course_pairs is not None and strict.course_pairs.size == 1
    assert strict.course_pairs.neighbours("M08") == {"L02": 48}
    assert strict.coverage["course_pairs"]["dropped"]["below_support"] == 14
    loose = load_catalog(Settings(pairs_min_support=1))
    assert loose.course_pairs is not None and loose.course_pairs.size == 15


def test_no_pair_above_support_disables_the_feature(caplog):
    with caplog.at_level(logging.WARNING, logger="app.catalog"):
        catalog = load_catalog(Settings(pairs_min_support=1000))
    assert catalog.course_pairs is None and "co_enrollment" in catalog.disabled_features
    assert catalog.coverage["course_pairs"]["source"] == "empty"
    assert catalog.coverage["course_pairs"]["dropped"]["below_support"] == 15
    assert "не ниже 1000" in caplog.text


def test_explicit_pairs_path_overrides_synthetic_pairs(tmp_path):
    path = tmp_path / "pairs.json"
    path.write_text(json.dumps({"version": "t", "pairs": [pair("M08", "S03", 50, 120, 60)]}), encoding="utf-8")
    catalog = load_catalog(Settings(catalog_pairs_path=path))
    assert catalog.course_pairs is not None and catalog.course_pairs.neighbours("M08") == {"S03": 50}
    assert catalog.coverage["course_pairs"]["pairs"] == 1


@pytest.mark.parametrize("source", ["file", "sqlite"])
def test_file_and_sqlite_sources_get_pairs_only_from_the_variable(source):
    settings = Settings(catalog_source=source, catalog_path=DATA_DIR / "catalog.synthetic.json")
    assert pairs_path(settings) is None
    explicit = Settings(catalog_source=source, catalog_pairs_path=SYNTHETIC_PAIRS)
    assert pairs_path(explicit) == SYNTHETIC_PAIRS


def test_file_source_without_pairs_disables_feature_and_keeps_catalog():
    catalog = load_catalog(Settings(catalog_source="file", catalog_path=DATA_DIR / "catalog.synthetic.json"))
    assert catalog.size == 23 and catalog.course_pairs is None
    assert catalog.disabled_features == ("co_enrollment",)
    assert catalog.coverage["course_pairs"] == {
        "source": "not_configured", "min_support": 10, "pairs": 0, "courses": 0,
        "dropped": dict.fromkeys(DROP_REASONS, 0), "total_conflicts": 0,
    }


def test_file_source_with_pairs_path_loads_pairs():
    settings = Settings(
        catalog_source="file", catalog_path=DATA_DIR / "catalog.synthetic.json", catalog_pairs_path=SYNTHETIC_PAIRS
    )
    catalog = load_catalog(settings)
    assert catalog.course_pairs is not None and catalog.disabled_features == ()


@pytest.mark.parametrize(
    ("content", "state"),
    [
        (None, "not_found"),
        (b"\xff\xfe\x00not utf-8", "unreadable"),
        (b"{not json", "invalid"),
        (b'{"pairs": {}}', "invalid"),
        (b"[1, 2]", "invalid"),
        (b'{"version": "x"}', "invalid"),
    ],
)
def test_broken_pairs_file_disables_feature_not_catalog(tmp_path, caplog, content, state):
    folder = tmp_path / "закрытая-папка"
    folder.mkdir()
    path = folder / "pairs.json"
    if content is not None:
        path.write_bytes(content)
    with caplog.at_level(logging.WARNING, logger="app.catalog"):
        catalog = load_catalog(Settings(catalog_pairs_path=path))
    assert catalog.size == 23 and catalog.course_pairs is None
    assert "co_enrollment" in catalog.disabled_features
    assert catalog.coverage["course_pairs"]["source"] == state and state in PAIRS_STATES
    # В журнале только имя файла: путь и содержимое туда не попадают
    assert "pairs.json" in caplog.text and "закрытая-папка" not in caplog.text and "not json" not in caplog.text


def test_parse_pairs_drops_and_counts_every_reason():
    catalog = courses_catalog()
    rows = [
        pair("C1", "C2", 12, 40, 30),          # загружается
        pair("C2", "C1", 12, 30, 40),          # обратная запись — дубль
        pair("C1", "C3", 9, 40, 20),           # ниже порога; C3 недоступен, но пара допустима
        pair("C1", "ZZ", 12, 40, 30),          # курса нет в каталоге
        pair("C1", "A1", 12, 40, 30),          # статья, не курс
        pair("C2", "C3", 25, 30, 20),          # общих слушателей больше, чем у C3
        pair("C1", "C1", 12, 40, 40),          # пара курса с самим собой
        pair("C1", "C2 ", 12, 40, 30),         # код вне правила
        {"a": "C1", "b": "C3", "together": True, "a_total": 40, "b_total": 20},  # bool вместо числа
        {"a": "C1", "b": "C3", "together": 12, "a_total": -1, "b_total": 20},    # отрицательное
        {"a": "C1", "b": "C3", "together": 12.0, "a_total": 40, "b_total": 20},  # не целое
        {"a": "C1", "b": "C3"},                # нет счётчиков
        "C1,C3,12",                            # не объект
    ]
    pairs, summary = parse_pairs({"pairs": rows}, catalog.materials, 10)
    assert summary["dropped"] == {
        "below_support": 1, "unknown_course": 1, "not_course": 1, "inconsistent": 1, "duplicates": 1, "invalid": 7,
    }
    assert (summary["source"], summary["pairs"], summary["courses"], summary["total_conflicts"]) == ("loaded", 1, 2, 0)
    assert pairs.together == {"C1": {"C2": 12}, "C2": {"C1": 12}}
    # Число слушателей берётся и из пары ниже порога: доля N из M считается по всем слушателям курса
    assert pairs.totals == {"C1": 40, "C2": 30, "C3": 20}


def test_parse_pairs_counts_total_conflicts_and_keeps_the_largest():
    catalog = courses_catalog()
    rows = [pair("C1", "C2", 12, 40, 30), pair("C1", "C3", 11, 45, 20)]
    pairs, summary = parse_pairs({"pairs": rows}, catalog.materials, 10)
    assert summary["total_conflicts"] == 1 and pairs.totals["C1"] == 45
    assert pairs.size == 2


def test_parse_pairs_rejects_a_file_without_pair_list():
    with pytest.raises(CatalogError):
        parse_pairs({"version": "x"}, {}, 10)
    with pytest.raises(CatalogError):
        parse_pairs([], {}, 10)


def test_similarity_is_the_share_of_anchor_listeners():
    catalog = courses_catalog()
    pairs, _ = parse_pairs({"pairs": [pair("C1", "C2", 12, 40, 30)]}, catalog.materials, 10)
    assert pairs.similarity("C1", "C2", 1.0) == pytest.approx(12 / 40)
    assert pairs.similarity("C2", "C1", 1.0) == pytest.approx(12 / 30)
    assert pairs.similarity("C1", "C3", 1.0) == 0.0


def test_load_without_path_is_not_configured():
    pairs, summary = load_course_pairs(None, {}, 10)
    assert pairs is None and summary["source"] == "not_configured" and summary["min_support"] == 10


def test_health_reports_pairs_as_aggregates_only():
    with client_for() as service:
        catalog = service.get("/api/health").json()["catalog"]
    assert catalog["disabled_features"] == []
    summary = catalog["coverage"]["course_pairs"]
    assert summary["source"] == "loaded" and summary["pairs"] == 7 and summary["min_support"] == 10
    assert not MATERIAL_CODE.search(json.dumps(summary)), summary


def test_health_without_pairs_names_the_disabled_feature():
    with client_for(catalog_source="file", catalog_path=DATA_DIR / "catalog.fixtures.json") as service:
        health = service.get("/api/health").json()["catalog"]
        body = service.post("/api/recommend", json={"task": "", "history": [{"material_id": "F03", "event": "start",
                                                                             "seq": 1}]}).json()
    assert "co_enrollment" in health["disabled_features"]
    assert health["coverage"]["course_pairs"]["source"] == "not_configured"
    # Без пар пустая задача с курсом в истории остаётся холодным стартом
    assert body["status"] == "cold" and "co_enrollment" in body["catalog"]["disabled_features"]
