"""Метрики за пределами точности: ручные значения и крайние случаи."""

from __future__ import annotations

from math import log, log2

import pytest

from app.ranking.metrics import (
    CALIBRATION_ALPHA,
    HEAD_SHARE,
    UNKNOWN_GROUP,
    catalog_coverage,
    exposure_counts,
    exposure_share,
    full_route_share,
    gini_index,
    hit_at_k,
    intra_list_diversity,
    jaccard_distance,
    long_tail,
    long_tail_share,
    miscalibration,
    position_discount,
    serendipity,
    topic_distribution,
    unexpectedness,
    unserved_share,
    user_coverage,
)

# ---------- покрытие и необслуженные, находка 5.2 ----------


def test_catalog_coverage_counts_distinct_shown_items_of_the_catalog():
    lists = [["a", "b"], ["b", "c", "z"]]
    assert catalog_coverage(lists, {"a", "b", "c", "d"}) == pytest.approx(3 / 4)
    assert catalog_coverage(lists, {"a", "b", "c", "d"}, k=1) == pytest.approx(2 / 4)
    # Подмножество каталога, например только курсы
    assert catalog_coverage(lists, {"c", "d"}) == pytest.approx(1 / 2)
    assert catalog_coverage([], {"a"}) == 0.0
    assert catalog_coverage(lists, set()) is None


def test_user_coverage_by_lists_and_statuses():
    assert user_coverage([["a"], [], ["b"]]) == pytest.approx(2 / 3)
    lists = [["a"], ["b"], ["c"], []]
    assert user_coverage(lists, ["strong", "cold", "weak", "strong"]) == pytest.approx(2 / 4)
    assert user_coverage(lists, ["none", "cold", "empty", "none"]) == 0.0
    assert user_coverage([]) is None
    with pytest.raises(ValueError):
        user_coverage([["a"]], ["strong", "weak"])


def test_unserved_share_is_one_minus_hit_rate_over_all_profiles():
    lists = [["a", "x"], ["x"], [], ["y", "z"]]
    grades = [{"a": 2}, {"a": 3}, {"a": 3}, {"y": 1}]
    # Обслужен только первый: у второго нет релевантного в выдаче, третий пуст, у четвёртого нет релевантных в разметке
    assert unserved_share(lists, grades) == pytest.approx(3 / 4)
    hits = sum(hit_at_k(r, g, 5) for r, g in zip(lists, grades, strict=True))
    assert unserved_share(lists, grades) == pytest.approx(1 - hits / 4)
    assert unserved_share([["x", "a"]], [{"a": 2}], k=1) == 1.0
    assert unserved_share([["y"]], [{"y": 1}], threshold=1) == 0.0
    assert unserved_share([], []) is None
    with pytest.raises(ValueError):
        unserved_share([["a"]], [])


# ---------- внутрисписочное разнообразие, находка 5.3 ----------


def test_jaccard_distance():
    assert jaccard_distance({"a", "b"}, {"b", "c"}) == pytest.approx(2 / 3)
    assert jaccard_distance({"a"}, {"a"}) == 0.0
    assert jaccard_distance({"a"}, set()) == 1.0
    assert jaccard_distance(set(), set()) is None


def test_intra_list_diversity_is_the_mean_pairwise_distance():
    # Пары: (m, m) — 0, (m, s) — 1, (m, s) — 1
    assert intra_list_diversity([{"m"}, {"m"}, {"s"}]) == pytest.approx(2 / 3)
    assert intra_list_diversity([{"m"}, {"m"}]) == 0.0
    assert intra_list_diversity([{"m"}, {"s"}, {"f"}]) == 1.0
    # Темы с признаками: |{m}| / |{m, x, y}| = 1/3, расстояние 2/3
    assert intra_list_diversity([{"m", "x"}, {"m", "y"}]) == pytest.approx(2 / 3)


def test_intra_list_diversity_skips_pairs_without_features():
    # Пара двух пустых множеств пропускается, остаются две пары с расстоянием 1
    assert intra_list_diversity([{"m"}, set(), set()]) == 1.0
    assert intra_list_diversity([set(), set()]) is None
    assert intra_list_diversity([{"m"}]) is None
    assert intra_list_diversity([]) is None


# ---------- неожиданность и серендипность, находка 5.4 ----------


def test_unexpectedness_is_the_share_outside_the_reference():
    assert unexpectedness(["a", "b", "c", "d"], ["b", "d", "e"]) == pytest.approx(2 / 4)
    assert unexpectedness(["a", "b"], ["a", "b"]) == 0.0
    assert unexpectedness(["a", "b"], []) == 1.0
    assert unexpectedness(["a", "a", "b"], ["b"]) == pytest.approx(1 / 2)
    # Эталон тоже обрезается до k: b на шестой позиции эталона не считается ожидаемым
    assert unexpectedness(["a", "b"], ["x", "y", "z", "w", "v", "b"]) == 1.0
    assert unexpectedness([], ["a"]) is None


def test_serendipity_is_the_share_outside_the_reference_and_useful():
    grades = {"a": 3, "b": 3, "c": 1, "d": 2}
    # Вне эталона a (полезен) и c (оценка 1)
    assert serendipity(["a", "b", "c", "d"], ["b", "d", "e"], grades) == pytest.approx(1 / 4)
    assert serendipity(["a", "b", "c", "d"], ["b", "d", "e"], grades, threshold=1) == pytest.approx(2 / 4)
    assert serendipity(["b", "d"], ["b", "d"], grades) == 0.0
    assert serendipity([], ["a"], grades) is None
    assert serendipity(["a"], [], {"a": 1}) is None


# ---------- неравномерность показов и длинный хвост, находка 5.5 ----------


def test_exposure_counts_include_items_without_exposure():
    assert exposure_counts([["a", "b"], ["b", "z"], ["b", "b"]], ["a", "b", "c"]) == {"a": 1, "b": 3, "c": 0}
    assert exposure_counts([["a", "b"]], ["a", "b"], k=1) == {"a": 1, "b": 0}


def test_gini_index_hand_values():
    assert gini_index([1, 1, 1, 1]) == pytest.approx(0.0)
    assert gini_index([0, 0, 0, 4]) == pytest.approx(1.0)
    # p = 0, 1/4, 1/4, 1/2: (−3·0 − 1·1/4 + 1·1/4 + 3·1/2) / 3
    assert gini_index([2, 1, 0, 1]) == pytest.approx(0.5)
    assert gini_index([1, 3]) == pytest.approx(0.5)
    # m показов на m разных материалах из n: (n − m) / (n − 1)
    assert gini_index([1, 1] + [0] * 8) == pytest.approx(8 / 9)
    assert gini_index({"a": 3, "b": 3}.values()) == pytest.approx(0.0)


def test_gini_index_edge_cases():
    assert gini_index([]) is None
    assert gini_index([5]) is None
    assert gini_index([0, 0, 0]) is None
    with pytest.raises(ValueError):
        gini_index([1, -1])


def test_long_tail_splits_by_popularity_rank_and_code():
    popularity = {"a": 10, "b": 9, "c": 9, "d": 1, "e": 0}
    # n = 5, голова ⌈0,2 · 5⌉ = 1
    assert long_tail(popularity) == {"b", "c", "d", "e"}
    # Голова 2: равенство b и c на границе решает код
    assert long_tail(popularity, head_share=0.4) == {"c", "d", "e"}
    assert long_tail(popularity, head_share=0) == set(popularity)
    assert long_tail(popularity, head_share=1) == set()
    assert long_tail({}) == set()
    assert HEAD_SHARE == 0.2
    with pytest.raises(ValueError):
        long_tail(popularity, head_share=1.5)


def test_long_tail_head_size_is_not_inflated_by_float_error():
    # 0,28 · 25 = 7,000000000000001 в двоичной арифметике; голова — ровно 7
    assert 0.28 * 25 > 7
    popularity = {f"m{i:02d}": 25 - i for i in range(25)}
    assert len(long_tail(popularity, head_share=0.28)) == 18
    assert len(long_tail({f"m{i:02d}": i for i in range(23)})) == 18


def test_long_tail_share_is_the_mean_share_over_non_empty_lists():
    tail = {"b", "c", "d", "e"}
    assert long_tail_share([["a", "b"], ["c", "d", "e"], []], tail) == pytest.approx((1 / 2 + 1) / 2)
    assert long_tail_share([["a", "a", "b"]], tail) == pytest.approx(1 / 2)
    assert long_tail_share([["a", "b"]], tail, k=1) == 0.0
    assert long_tail_share([[], []], tail) is None


# ---------- экспозиция групп, находка 5.7 ----------


def test_position_discount():
    assert position_discount(1) == 1.0
    assert position_discount(2) == pytest.approx(1 / log2(3))
    assert position_discount(3) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        position_discount(0)


def test_exposure_share_discounts_by_position():
    groups = {"a": "x", "b": "y", "c": "x"}
    # x: 1 + 1/log2 4 = 1,5; y: 1/log2 3
    shares = exposure_share([["a", "b", "c"]], groups)
    assert shares == pytest.approx({"x": 1.5 / (1.5 + 1 / log2(3)), "y": (1 / log2(3)) / (1.5 + 1 / log2(3))})
    assert shares is not None and shares["x"] == pytest.approx(0.703918, abs=1e-6)
    two_lists = exposure_share([["a", "b"], ["b", "c", "z"]], groups)
    assert two_lists is not None and sum(two_lists.values()) == pytest.approx(1.0)


def test_exposure_share_edge_cases():
    assert exposure_share([["z"]], {"a": "x"}) == {UNKNOWN_GROUP: 1.0}
    assert exposure_share([["a", "a"]], {"a": "x"}) == {"x": 1.0}
    assert exposure_share([["a", "b"]], {"a": "x", "b": "y"}, k=1) == {"x": 1.0}
    assert exposure_share([[], []], {"a": "x"}) is None
    assert exposure_share([], {"a": "x"}) is None


# ---------- калибровка, находка 5.6 ----------


def test_topic_distribution_splits_a_material_across_its_topics():
    assert topic_distribution([["m"], ["m", "s"], []]) == pytest.approx({"m": 0.75, "s": 0.25})
    assert topic_distribution([["m", "m"]]) == {"m": 1.0}
    assert topic_distribution([[], []]) == {}
    assert topic_distribution([]) == {}


def test_miscalibration_hand_values():
    assert CALIBRATION_ALPHA == 0.01
    assert miscalibration({"m": 1.0}, {"m": 1.0}) == pytest.approx(0.0)
    # 0,5 · ln(0,5 / 0,995) + 0,5 · ln(0,5 / 0,005)
    half = miscalibration({"a": 0.5, "b": 0.5}, {"a": 1.0})
    assert half == pytest.approx(0.5 * log(0.5 / 0.995) + 0.5 * log(0.5 / 0.005))
    assert half == pytest.approx(1.958518, abs=1e-6)
    # Выдача без тем истории: ln(1/α)
    assert miscalibration({"a": 1.0}, {"b": 1.0}) == pytest.approx(log(100))
    # История — одна тема, в выдаче её доля 0,4: −ln(0,99 · 0,4 + 0,01)
    assert miscalibration({"m": 1.0}, {"m": 0.4, "s": 0.6}) == pytest.approx(0.901402, abs=1e-6)
    # Больше α — меньше штраф за выпавшую тему
    assert miscalibration({"a": 1.0}, {"b": 1.0}, alpha=0.1) == pytest.approx(log(10))


def test_miscalibration_edge_cases():
    assert miscalibration({}, {"a": 1.0}) is None
    assert miscalibration({"a": 1.0}, {}) is None
    for alpha in (0, -0.1, 1.5):
        with pytest.raises(ValueError):
            miscalibration({"a": 1.0}, {"a": 1.0}, alpha=alpha)


def test_miscalibration_is_non_negative_for_distributions():
    history = topic_distribution([["a"], ["a", "b"], ["c"]])
    for recommended in ([["a"]], [["b"], ["c"]], [["a", "b", "c"]], [["d"]]):
        value = miscalibration(history, topic_distribution(recommended))
        assert value is not None and value >= 0


# ---------- маршрут, R13 ----------


def test_full_route_share():
    assert full_route_share([3, 2, 0]) == pytest.approx(1 / 3)
    assert full_route_share([3, 3]) == 1.0
    assert full_route_share([0, 2]) == 0.0
    assert full_route_share([3, 2, 0], steps=2) == pytest.approx(2 / 3)
    assert full_route_share([]) is None
