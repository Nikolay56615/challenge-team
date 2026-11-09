"""Методы офлайн-сравнения по курсам: нормированные совместные записи, последовательные правила, EASE.


- Нормированные совместные записи: sim(i, j) = c_ij / (c_i^α · c_j^(1−α)), где c_i — обучающие
  пользователи с курсом i, c_ij — с обоими курсами. α = 1 даёт исходный метод O1 — долю
  пользователей курса входа, записавшихся и на кандидата; α = 0,5 — косинус. Пары с c_ij ниже
  минимальной поддержки обнуляются; у каждого курса входа остаются k соседей с наибольшим
  сходством среди доступных курсов. Оценка кандидата — сумма сходств по курсам входа.
- Последовательные правила: n(i → j) — обучающие пользователи, у которых i раньше j по
  `EventOrder`; оценка кандидата — сумма n(i → j) / c_i по курсам входа.
- EASE (Steck, 2019): B = −P / diag(P), P = (XᵀX + λI)⁻¹, diag(B) = 0; оценка кандидата j —
  сумма B_ij по курсам входа i. Обращение — метод Гаусса — Жордана без numpy.

Во всех методах равенства оценок решает популярность по обучающей части, затем код курса.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import log2
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

# Обращение матрицы — то же, что у модели EASE в продукте: `offline_weights.py` берёт его отсюда
from app.catalog.ease import invert  # noqa: E402, F401

Similarity = dict[str, dict[str, float]]


@dataclass(slots=True)
class Counts:
    users: Counter[str]  # c_i
    pairs: dict[str, Counter[str]]  # c_ij
    ordered: dict[str, Counter[str]]  # n(i → j)


@dataclass(frozen=True, slots=True)
class CoConfig:
    alpha: float
    neighbours: int | None  # None — все соседи
    support: int

    def label(self) -> str:
        k = "все" if self.neighbours is None else str(self.neighbours)
        return f"α {fmt_alpha(self.alpha)}, соседей {k}, поддержка {self.support}"


def fmt_alpha(alpha: float) -> str:
    return f"{alpha:g}".replace(".", ",")


def count(users: Iterable[Sequence[tuple[str, int]]]) -> Counts:
    """Счётчики по обучающим пользователям; пользователь — список пар (курс, EventOrder)."""
    counts = Counts(users=Counter(), pairs=defaultdict(Counter), ordered=defaultdict(Counter))
    for bindings in users:
        courses = sorted({course for course, _ in bindings})
        for course in courses:
            counts.users[course] += 1
        for a in courses:
            for b in courses:
                if a != b:
                    counts.pairs[a][b] += 1
        for a, order_a in bindings:
            for b, order_b in bindings:
                if a != b and order_a < order_b:
                    counts.ordered[a][b] += 1
    return counts


def similarity(counts: Counts, universe: frozenset[str], alpha: float, support: int) -> Similarity:
    """Сходство курса входа i с доступным курсом j без отбора соседей."""
    sim: Similarity = {}
    for i, row in counts.pairs.items():
        ci = counts.users[i]
        sim[i] = {
            j: cij / (ci**alpha * counts.users[j] ** (1 - alpha))
            for j, cij in row.items()
            if j in universe and cij >= support
        }
    return sim


def keep_neighbours(sim: Similarity, neighbours: int | None, popularity: Mapping[str, int]) -> Similarity:
    if neighbours is None:
        return sim
    return {
        i: {j: row[j] for j in sorted(row, key=lambda j: (-row[j], -popularity.get(j, 0), j))[:neighbours]}
        for i, row in sim.items()
    }


def sum_scores(weights: Similarity, inputs: Sequence[str], candidates: Iterable[str]) -> dict[str, float]:
    """Оценка кандидата — сумма весов по курсам входа в порядке входа."""
    rows = [weights[i] for i in inputs if i in weights]
    return {c: sum(row.get(c, 0.0) for row in rows) for c in candidates}


def sequential_weights(counts: Counts) -> Similarity:
    return {i: {j: n / counts.users[i] for j, n in row.items()} for i, row in counts.ordered.items() if counts.users[i]}


def rank(scores: Mapping[str, float], candidates: Iterable[str], popularity: Mapping[str, int]) -> list[str]:
    return sorted(candidates, key=lambda c: (-scores[c], -popularity.get(c, 0), c))


def target_position(
    scores: Mapping[str, float], candidates: Iterable[str], popularity: Mapping[str, int], target: str
) -> int:
    """Позиция цели с нуля в порядке `rank` без полной сортировки."""
    key = (-scores[target], -popularity.get(target, 0), target)
    return sum(1 for c in candidates if (-scores[c], -popularity.get(c, 0), c) < key)


def hit_ndcg(position: int, k: int) -> tuple[int, float]:
    """hit@k и NDCG@k одной цели с бинарной релевантностью: 1 / log2(позиция + 2) в первых k."""
    return (1, 1 / log2(position + 2)) if position < k else (0, 0.0)


def ease(counts: Counts, items: Sequence[str], lam: float) -> Similarity:
    """Веса EASE: B[i][j] — вклад курса входа i в оценку курса j; диагональ нулевая."""
    gram = [
        [counts.users[i] + lam if i == j else float(counts.pairs.get(i, {}).get(j, 0)) for j in items] for i in items
    ]
    p = invert(gram)
    return {
        i: {j: -p[a][b] / p[b][b] for b, j in enumerate(items) if a != b}
        for a, i in enumerate(items)
    }


def contributions(weights: Similarity, inputs: Sequence[str], candidate: str) -> list[tuple[float, str]]:
    """Слагаемые оценки кандидата по курсам входа, по убыванию."""
    return sorted(((weights.get(i, {}).get(candidate, 0.0), i) for i in inputs), key=lambda x: (-x[0], x[1]))
