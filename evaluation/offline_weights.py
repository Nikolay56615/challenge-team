"""Проверка ручных весов персонального подбора попарной логистической регрессией (PLAN.md, 12.1, R08).

Признаки кандидата берутся из `personal.score_material` в том же контексте, что у метода
«правила по темам» O1: индикатор каждого признака с ненулевым вкладом и нормированная популярность
по обучающей части, которая в продукте решает равенства. Пара — цель пользователя против каждого
другого кандидата, без сэмплирования. Потеря — логистическая по разнице признаков пары (RankNet с
линейной функцией, research/literature-recsys.md, 1.6) с L2-штрафом; минимум ищется методом
Ньютона. Модуль только отчитывается: веса продукта не меняются.
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from math import exp
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.catalog.lexicon import parse_task  # noqa: E402
from app.catalog.models import HistoryEvent, Material  # noqa: E402
from app.ranking import personal  # noqa: E402
from app.ranking.base import Context, HistoryIndex, Profile  # noqa: E402

from offline_models import invert  # noqa: E402

FEATURES = ("topic", "continuation", "popularity")
MANUAL = {"topic": personal.WEIGHTS["topic"], "continuation": personal.WEIGHTS["continuation"]}
L2 = 1.0
_EMPTY_TASK = parse_task("")


def context(inputs: Sequence, materials: Mapping[str, Material], disabled: frozenset[str], limit: int) -> Context:
    """Контекст метода «правила по темам» O1: история из записей входа, темы курсов входа, задачи нет."""
    events: list[HistoryEvent] = []
    for b in inputs:
        events.append(HistoryEvent(b.course, b.event, b.order))
        if b.paid:
            events.append(HistoryEvent(b.course, "purchase", b.order))
    profile = Profile(history=tuple(events), limit=limit)
    topics: list[str] = []
    for b in inputs:
        material = materials.get(b.course)
        for topic in material.topics if material else ():
            if topic not in topics:
                topics.append(topic)
    return Context(
        profile=profile, parsed=_EMPTY_TASK, topics=tuple(topics), history=HistoryIndex.build(profile.history),
        disabled=disabled, catalog=dict(materials),
    )


def rule_features(ctx: Context, material: Material) -> tuple[dict[str, float], set[str]]:
    """Индикаторы признаков с ненулевым вкладом; второе значение — все сработавшие признаки."""
    item = personal.score_material(material, ctx)
    active = set(item.contributions)
    return {f: 1.0 if f in active else 0.0 for f in FEATURES if f != "popularity"}, active


def vector(indicators: Mapping[str, float], popularity: float) -> tuple[float, ...]:
    return tuple(popularity if f == "popularity" else indicators[f] for f in FEATURES)


def pair_differences(groups: Iterable[tuple[tuple[float, ...], Sequence[tuple[float, ...]]]]) -> Counter:
    """Кратности разниц «цель − другой кандидат»; нулевые разницы на потерю не влияют и пропускаются."""
    pairs: Counter = Counter()
    for target, others in groups:
        for other in others:
            diff = tuple(round(a - b, 12) for a, b in zip(target, other))
            if any(diff):
                pairs[diff] += 1
    return pairs


def _sigmoid_neg(z: float) -> float:
    """σ(−z) без переполнения."""
    if z >= 0:
        e = exp(-z)
        return e / (1 + e)
    return 1 / (1 + exp(z))


def fit(pairs: Mapping[tuple[float, ...], int], l2: float = L2, iterations: int = 100) -> list[float]:
    """Минимум Σ n · log(1 + exp(−w · Δx)) + l2 / 2 · |w|² методом Ньютона."""
    d = len(FEATURES)
    w = [0.0] * d
    for _ in range(iterations):
        grad = [l2 * wi for wi in w]
        hess = [[l2 if a == b else 0.0 for b in range(d)] for a in range(d)]
        for dx, n in pairs.items():
            s = _sigmoid_neg(sum(wi * xi for wi, xi in zip(w, dx)))
            curvature = n * s * (1 - s)
            for a in range(d):
                grad[a] -= n * s * dx[a]
                for b in range(d):
                    hess[a][b] += curvature * dx[a] * dx[b]
        inverse = invert(hess)
        step = [sum(inverse[a][b] * grad[b] for b in range(d)) for a in range(d)]
        w = [wi - si for wi, si in zip(w, step)]
        if max(abs(s) for s in step) < 1e-12:
            break
    return w


def score(weights: Sequence[float], x: Sequence[float]) -> float:
    return sum(w * v for w, v in zip(weights, x))
