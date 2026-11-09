"""Метрики и сравнение методов на независимой разметке релевантности."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ranking.metrics import dcg, hit_at_k, ndcg_at_k

from .conftest import ids

RELEVANCE = Path(__file__).with_name("relevance.json")


def test_metric_functions():
    grades = {"a": 3, "b": 2, "c": 0}
    assert ndcg_at_k(["a", "b", "c"], grades) == pytest.approx(1.0)
    reversed_score = ndcg_at_k(["c", "b", "a"], grades)
    assert reversed_score is not None and reversed_score < 1.0
    assert ndcg_at_k(["x"], {"x": 0}) is None
    assert dcg([3, 2]) == pytest.approx(3 + 2 / 1.584962500721156)
    assert hit_at_k(["c", "c", "b"], grades) and not hit_at_k(["c"], grades)


def test_repeated_ids_count_once():
    grades = {"a": 3, "b": 2, "c": 0}
    assert ndcg_at_k(["a", "a"], {"a": 3, "b": 0}) == pytest.approx(1.0)
    assert ndcg_at_k(["a", "a", "b"], grades) == pytest.approx(ndcg_at_k(["a", "b"], grades))
    assert ndcg_at_k(["b"] * 6 + ["a"], grades) == pytest.approx(ndcg_at_k(["b", "a"], grades))
    scores = [ndcg_at_k(ranked, grades) for ranked in (["a"] * 5, ["a", "b", "a", "b"], ["b", "b", "a"])]
    assert all(score is not None and score <= 1.0 for score in scores)
    # Повтор не занимает позицию: после удаления повторов b оказывается второй
    assert hit_at_k(["c", "c", "c", "b"], grades) and not hit_at_k(["c", "c", "c"], grades)


@pytest.mark.skipif(not RELEVANCE.exists(), reason="разметка релевантности ещё не записана")
@pytest.mark.parametrize("profile_id", ["P01", "P02"])
def test_personal_beats_baseline_on_p01_p02(run, profile_id):
    labels = json.loads(RELEVANCE.read_text(encoding="utf-8"))["labels"][profile_id]
    personal = ndcg_at_k(ids(run(profile_id)), labels)
    baseline = ndcg_at_k(ids(run(profile_id, "baseline")), labels)
    assert personal is not None and baseline is not None and personal > baseline
    assert hit_at_k(ids(run(profile_id)), labels)
