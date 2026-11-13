"""Метрики точности ранжирования: ручные значения и крайние случаи (кандидат R05; находка 5.1)."""

from __future__ import annotations

import json
import random
from math import log2
from pathlib import Path

import pytest

from app.ranking.metrics import (
    average_precision_at_k,
    hit_at_k,
    mean_average_precision,
    mean_defined,
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    relevant_set,
)

from .conftest import ids

RELEVANCE = Path(__file__).with_name("relevance.json")
# Rel = {a, b, d} при пороге 2
GRADES = {"a": 3, "b": 2, "c": 0, "d": 2}
# Позиции: 1 — c, 2 — a, 3 — x вне разметки, 4 — b
RANKED = ["c", "a", "x", "b"]


def defined(value: float | None) -> float:
    """Значение метрики, которое в проверяемом случае определено: None — провал теста."""
    assert value is not None
    return value


def test_relevant_set_uses_the_threshold():
    assert relevant_set(GRADES) == {"a", "b", "d"}
    assert relevant_set(GRADES, threshold=3) == {"a"}
    assert relevant_set({}) == set()


def test_precision_counts_hits_over_k():
    assert precision_at_k(RANKED, GRADES) == pytest.approx(2 / 5)
    assert precision_at_k(RANKED, GRADES, k=2) == pytest.approx(1 / 2)
    assert precision_at_k(RANKED, GRADES, k=1) == 0.0
    # Короткая выдача не получает преимущества: знаменатель k
    assert precision_at_k(["a"], GRADES, k=5) == pytest.approx(1 / 5)
    assert precision_at_k(["a", "b", "d"], GRADES, k=3) == 1.0


def test_recall_counts_hits_over_relevant():
    assert recall_at_k(RANKED, GRADES) == pytest.approx(2 / 3)
    assert recall_at_k(RANKED, GRADES, k=2) == pytest.approx(1 / 3)
    # Релевантных больше k: идеальная выдача не достигает 1
    assert recall_at_k(["a", "b"], GRADES, k=2) == pytest.approx(2 / 3)


def test_reciprocal_rank_is_one_over_the_first_hit():
    assert reciprocal_rank(RANKED, GRADES) == pytest.approx(1 / 2)
    assert reciprocal_rank(["a"], GRADES) == 1.0
    assert reciprocal_rank(RANKED, GRADES, k=1) == 0.0
    assert reciprocal_rank([], GRADES) == 0.0


def test_average_precision_normalises_by_min_k_and_relevant():
    # (1/3) · (P@2 + P@4) = (1/3) · (1/2 + 2/4)
    assert average_precision_at_k(RANKED, GRADES) == pytest.approx(1 / 3)
    # k = 2: (1/2) · P@2
    assert average_precision_at_k(RANKED, GRADES, k=2) == pytest.approx(1 / 4)
    assert average_precision_at_k(["a", "b", "d"], GRADES) == pytest.approx(1.0)
    # Релевантных больше k: идеальная пара всё равно получает 1
    assert average_precision_at_k(["a", "b"], GRADES, k=2) == pytest.approx(1.0)
    # (1/3) · (1/2 + 2/3 + 3/4)
    assert average_precision_at_k(["x", "a", "b", "d"], GRADES) == pytest.approx((1 / 2 + 2 / 3 + 3 / 4) / 3)


def test_repeated_ids_count_once_in_all_accuracy_metrics():
    assert precision_at_k(["a", "a", "b"], GRADES) == pytest.approx(2 / 5)
    assert recall_at_k(["a", "a", "a"], GRADES) == pytest.approx(1 / 3)
    assert reciprocal_rank(["c", "c", "c", "a"], GRADES) == pytest.approx(1 / 2)
    assert average_precision_at_k(["a", "a", "b"], GRADES) == pytest.approx(2 / 3)


@pytest.mark.parametrize(
    ("metric", "with_lower_threshold"),
    [(precision_at_k, 1 / 5), (recall_at_k, 1.0), (reciprocal_rank, 1.0), (average_precision_at_k, 1.0)],
)
def test_accuracy_metrics_are_undefined_without_relevant_items_or_positions(metric, with_lower_threshold):
    assert metric(["a"], {"a": 1, "b": 0}) is None
    assert metric(["a"], {}) is None
    assert metric(["a"], GRADES, k=0) is None
    # Порог 1 делает тот же материал релевантным
    assert metric(["a"], {"a": 1}, threshold=1) == pytest.approx(with_lower_threshold)


def test_mean_metrics_skip_undefined_profiles():
    runs = [(RANKED, GRADES), (["a"], GRADES), (["x"], {"x": 0})]
    assert mean_reciprocal_rank(runs) == pytest.approx((1 / 2 + 1) / 2)
    runs = [(RANKED, GRADES), (["a", "b", "d"], GRADES), (["y"], {})]
    assert mean_average_precision(runs) == pytest.approx((1 / 3 + 1) / 2)
    assert mean_reciprocal_rank([]) is None and mean_average_precision([(["a"], {})]) is None
    assert mean_defined([None, 1.0, 0.0]) == pytest.approx(0.5)
    assert mean_defined([None]) is None and mean_defined([]) is None


def test_exponential_gain_weights_the_top_grade_more():
    grades = {"a": 3, "b": 2, "c": 0}
    l3 = log2(3)
    # Линейная: (0 + 2/log2 3 + 3/2) / (3 + 2/log2 3); экспоненциальная: (0 + 3/log2 3 + 7/2) / (7 + 3/log2 3)
    assert ndcg_at_k(["c", "b", "a"], grades) == pytest.approx((2 / l3 + 3 / 2) / (3 + 2 / l3))
    assert ndcg_at_k(["c", "b", "a"], grades) == pytest.approx(0.648041, abs=1e-6)
    assert ndcg_at_k(["c", "b", "a"], grades, gain="exponential") == pytest.approx(0.606423, abs=1e-6)
    assert ndcg_at_k(["a", "b", "c"], grades, gain="exponential") == pytest.approx(1.0)
    assert ndcg_at_k(["x"], {"x": 0}, gain="exponential") is None


def test_gain_choice_can_reverse_the_order_of_two_lists():
    """Смена порядка методов при смене выгоды — признак хрупкости вывода (находка 5.1)."""
    grades = {"a": 3, "b": 2, "c": 2}
    two_good, one_best = ["b", "c"], ["a", "z"]
    assert defined(ndcg_at_k(two_good, grades)) > defined(ndcg_at_k(one_best, grades))
    assert defined(ndcg_at_k(two_good, grades, gain="exponential")) < defined(
        ndcg_at_k(one_best, grades, gain="exponential")
    )


def test_linear_gain_is_the_default_and_unknown_gain_fails():
    grades = {"a": 3, "b": 2, "c": 0}
    for ranked in (["a", "b", "c"], ["c", "b", "a"], ["b"], ["a", "a", "c"]):
        assert ndcg_at_k(ranked, grades) == ndcg_at_k(ranked, grades, gain="linear")
    with pytest.raises(ValueError):
        ndcg_at_k(["a"], grades, gain="log")


def test_metric_bounds_and_identities_on_random_lists():
    rng = random.Random(20261111)
    codes = [f"m{i}" for i in range(12)]
    for _ in range(300):
        grades = {code: rng.choice((0, 0, 1, 2, 3)) for code in codes}
        ranked = rng.sample(codes, rng.randint(0, 8))
        k = rng.randint(1, 6)
        relevant = relevant_set(grades)
        values = [
            precision_at_k(ranked, grades, k), recall_at_k(ranked, grades, k),
            reciprocal_rank(ranked, grades, k), average_precision_at_k(ranked, grades, k),
            ndcg_at_k(ranked, grades, k), ndcg_at_k(ranked, grades, k, gain="exponential"),
        ]
        assert all(v is None or 0 <= v <= 1 + 1e-12 for v in values)
        if relevant:
            # P@k · k и R@k · |Rel| — одно и то же число попаданий
            hits = defined(recall_at_k(ranked, grades, k)) * len(relevant)
            assert defined(precision_at_k(ranked, grades, k)) * k == pytest.approx(hits)
            assert (defined(reciprocal_rank(ranked, grades, k)) > 0) == hit_at_k(ranked, grades, k)
            ideal = sorted(codes, key=lambda c: -grades[c])
            assert ndcg_at_k(ideal, grades, k, gain="exponential") == pytest.approx(1.0)
            assert average_precision_at_k(ideal, grades, k) == pytest.approx(1.0)


@pytest.mark.skipif(not RELEVANCE.exists(), reason="разметка релевантности ещё не записана")
def test_test_profiles_have_the_same_defined_set_for_all_accuracy_metrics(run, profiles):
    """NDCG определена у восьми профилей; у тех же восьми есть релевантные материалы для P@k, AP@k и RR.

    Разметка 3.7 слепая и покрывает P01–P10. P11 и P12 пилота «похожие курсы» в неё не входят.
    """
    labels = json.loads(RELEVANCE.read_text(encoding="utf-8"))["labels"]
    labelled = [pid for pid in profiles if pid in labels]
    assert labelled == [f"P{n:02d}" for n in range(1, 11)]
    defined_ndcg = {pid for pid in labelled if ndcg_at_k(ids(run(pid)), labels[pid]) is not None}
    defined_ap = {pid for pid in labelled if average_precision_at_k(ids(run(pid)), labels[pid]) is not None}
    assert len(defined_ndcg) == 8 and defined_ap == defined_ndcg
