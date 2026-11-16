"""Нормировка популярности и проверка ссылок."""

from __future__ import annotations

import pytest

from app.catalog.coverage import link_allowed, normalize_popularity


def test_single_scale_divides_by_catalog_maximum() -> None:
    raw = {"a": 50.0, "b": 100.0, "c": 0.0}
    formats = {"a": "article", "b": "course", "c": "article"}
    assert normalize_popularity(raw, formats, "single") == {"a": 0.5, "b": 1.0, "c": 0.0}


def test_single_scale_all_zero_gives_zero() -> None:
    raw = {"a": 0.0, "b": 0.0}
    assert normalize_popularity(raw, {"a": "article", "b": "article"}, "single") == {"a": 0.0, "b": 0.0}


def test_per_format_is_rank_percentile_within_format() -> None:
    raw = {"a1": 1.0, "a2": 3.0, "a3": 3.0, "a4": 7.0, "c1": 10.0, "c2": 40.0}
    formats = {"a1": "article", "a2": "article", "a3": "article", "a4": "article", "c1": "course", "c2": "course"}
    result = normalize_popularity(raw, formats, "per_format")
    # (ниже + равные) / n внутри формата: шкалы статей и курсов не смешиваются
    assert result == {"a1": 0.25, "a2": 0.75, "a3": 0.75, "a4": 1.0, "c1": 0.5, "c2": 1.0}


def test_per_format_zero_evidence_gets_zero() -> None:
    raw = {"d1": 0.0, "d2": 0.0, "d3": 0.0, "d4": 1.0, "a1": 0.0, "a2": 2.0}
    formats = {"d1": "document", "d2": "document", "d3": "document", "d4": "document", "a1": "article", "a2": "article"}
    result = normalize_popularity(raw, formats, "per_format")
    # Материал без записей и ссылок не получает долю формата, иначе нули обходили бы другие форматы
    assert result["d1"] == result["d2"] == result["d3"] == result["a1"] == 0.0
    assert result["d4"] == 1.0
    assert result["a2"] == 1.0


def test_per_format_all_zero_format_stays_zero() -> None:
    result = normalize_popularity({"w1": 0.0, "w2": 0.0}, {"w1": "webinar", "w2": "webinar"}, "per_format")
    assert result == {"w1": 0.0, "w2": 0.0}


def test_empty_input() -> None:
    assert normalize_popularity({}, {}, "per_format") == {}


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://example.org/materials/m01", True),
        ("http://example.org/x", True),
        ("  HTTPS://example.org/x  ", True),
        ("ftp://example.org/file", False),
        ("javascript:alert(1)", False),
        ("data:text/html,<b>x</b>", False),
        ("https://", False),
        ("//example.org/x", False),
        ("", False),
        (None, False),
    ],
)
def test_link_allowed(url: str | None, allowed: bool) -> None:
    assert link_allowed(url) is allowed
