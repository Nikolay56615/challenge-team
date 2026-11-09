"""Статистика офлайн-сравнения методов.

- Парный бутстреп по пользователям: одни и те же выборки пользователей для всех серий разниц,
  95 % перцентильный интервал среднего.
- Парный перестановочный тест со сменой знака: при нулевой гипотезе методы взаимозаменяемы у
  каждого пользователя, поэтому знак его разницы случаен. Разницы группируются по значению, и
  число смен знака в группе из m пользователей берётся как число единиц в m случайных битах.
- Поправка Холма — Бонферрони на семейство сравнений.
- Объём выборки и минимальный обнаружимый эффект для двух независимых долей и для парного сравнения долей по формуле Макнемара (Connor, 1987).

Только стандартная библиотека; случайность задаётся зерном.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Mapping, Sequence
from math import ceil, sqrt
from statistics import NormalDist, quantiles

ALPHA = 0.05
POWER = 0.8


def paired_bootstrap(
    series: Mapping[str, Sequence[float]], resamples: int, seed: int
) -> dict[str, tuple[float, float]]:
    """95 % перцентильный интервал среднего каждой серии на общих бутстреп-выборках пользователей.

    Все серии одной длины и выровнены по пользователям. Выборки не зависят от состава серий,
    поэтому добавление серии не меняет интервалы остальных.
    """
    lengths = {len(values) for values in series.values()}
    if len(lengths) != 1:
        raise ValueError("серии разной длины")
    n = lengths.pop()
    rng = random.Random(seed)
    population = range(n)
    means: dict[str, list[float]] = {name: [] for name in series}
    for _ in range(resamples):
        sample = rng.choices(population, k=n)
        for name, values in series.items():
            means[name].append(sum(map(values.__getitem__, sample)) / n)
    return {name: percentile_interval(values) for name, values in means.items()}


def percentile_interval(values: Sequence[float]) -> tuple[float, float]:
    """2,5 и 97,5 перцентили с линейной интерполяцией, как `numpy.quantile` по умолчанию."""
    cuts = quantiles(values, n=40, method="inclusive")
    return cuts[0], cuts[-1]


def sign_flip_pvalue(differences: Sequence[float], rounds: int, seed: int) -> float:
    """Двусторонний p перестановочного теста со сменой знака для среднего парной разницы.

    p = (1 + число перестановок с |суммой| не меньше наблюдаемой) / (1 + число перестановок).
    """
    groups = Counter(round(d, 12) for d in differences if abs(d) > 1e-12)
    values = sorted(groups.items())
    observed = abs(sum(v * m for v, m in values))
    if observed < 1e-12:
        return 1.0
    rng = random.Random(seed)
    extreme = 0
    for _ in range(rounds):
        total = 0.0
        for value, count in values:
            flipped = rng.getrandbits(count).bit_count()
            total += value * (count - 2 * flipped)
        if abs(total) >= observed - 1e-9:
            extreme += 1
    return (extreme + 1) / (rounds + 1)


def holm(pvalues: Sequence[float]) -> list[float]:
    """p-значения с поправкой Холма — Бонферрони в исходном порядке."""
    m = len(pvalues)
    adjusted = [0.0] * m
    running = 0.0
    for rank, index in enumerate(sorted(range(m), key=lambda i: (pvalues[i], i))):
        running = max(running, min(1.0, (m - rank) * pvalues[index]))
        adjusted[index] = running
    return adjusted


def _z(alpha: float, power: float) -> tuple[float, float]:
    normal = NormalDist()
    return normal.inv_cdf(1 - alpha / 2), normal.inv_cdf(power)


def users_two_proportions(p1: float, p2: float, alpha: float = ALPHA, power: float = POWER) -> float:
    """Пользователей на группу для двух независимых долей, двусторонний критерий, без округления.

    n = (z_{1−α/2} · √(2 p̄ (1 − p̄)) + z_{1−β} · √(p1 (1 − p1) + p2 (1 − p2)))² / (p1 − p2)², p̄ = (p1 + p2) / 2.
    """
    za, zb = _z(alpha, power)
    mean = (p1 + p2) / 2
    numerator = za * sqrt(2 * mean * (1 - mean)) + zb * sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    return numerator**2 / (p1 - p2) ** 2


def sample_size(p1: float, p2: float, alpha: float = ALPHA, power: float = POWER) -> int:
    return ceil(users_two_proportions(p1, p2, alpha, power))


def mde_two_proportions(p: float, n: float, alpha: float = ALPHA, power: float = POWER) -> float | None:
    """Наименьший абсолютный рост доли p, обнаружимый при n пользователях на группу; None, если недостижим."""
    low, high = 0.0, 1.0 - p
    if high <= 0 or users_two_proportions(p, p + high * (1 - 1e-9), alpha, power) > n:
        return None
    for _ in range(200):
        middle = (low + high) / 2
        if middle > 0 and users_two_proportions(p, p + middle, alpha, power) <= n:
            high = middle
        else:
            low = middle
    return high


def users_paired(delta: float, discordant: float, alpha: float = ALPHA, power: float = POWER) -> float:
    """Пользователей для парного сравнения долей (Макнемар): δ — разница долей, ψ — доля несогласных пар.

    n = (z_{1−α/2} · √ψ + z_{1−β} · √(ψ − δ²))² / δ².
    """
    za, zb = _z(alpha, power)
    return (za * sqrt(discordant) + zb * sqrt(max(discordant - delta**2, 0.0))) ** 2 / delta**2


def mde_paired(n: int, discordant: float, alpha: float = ALPHA, power: float = POWER) -> float | None:
    """Наименьшая разница hit@k двух методов, обнаружимая на n пользователях при доле несогласных пар ψ."""
    if discordant <= 0 or users_paired(discordant, discordant, alpha, power) > n:
        return None
    low, high = 0.0, discordant
    for _ in range(200):
        middle = (low + high) / 2
        if middle > 0 and users_paired(middle, discordant, alpha, power) <= n:
            high = middle
        else:
            low = middle
    return high
