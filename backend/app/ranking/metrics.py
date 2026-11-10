"""Метрики офлайн-оценки на размеченном наборе (PLAN.md, 3.7).

NDCG использует линейную выгоду и логарифмическое дисконтирование, как `ndcg_score` в scikit-learn.
hit@k считает попадание материала с оценкой не ниже порога в первые k позиций.
Повторы кода в выдаче не учитываются: остаётся первое вхождение, поэтому NDCG не превышает 1.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import log2

RELEVANT_GRADE = 2


def dcg(gains: Sequence[float]) -> float:
    return sum(gain / log2(position + 2) for position, gain in enumerate(gains))


def unique(ranked: Sequence[str]) -> list[str]:
    """Коды выдачи без повторов, в порядке первого вхождения."""
    return list(dict.fromkeys(ranked))


def ndcg_at_k(ranked: Sequence[str], grades: Mapping[str, int], k: int = 5) -> float | None:
    """None, если в разметке нет ни одного полезного материала: метрика не определена."""
    ideal = dcg(sorted(grades.values(), reverse=True)[:k])
    if ideal == 0:
        return None
    return dcg([grades.get(material_id, 0) for material_id in unique(ranked)[:k]]) / ideal


def hit_at_k(ranked: Sequence[str], grades: Mapping[str, int], k: int = 3, threshold: int = RELEVANT_GRADE) -> bool:
    return any(grades.get(material_id, 0) >= threshold for material_id in unique(ranked)[:k])
