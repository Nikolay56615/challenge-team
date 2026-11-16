"""Веса EASE по счётчикам совместных записей на курсы.

EASE (Steck, 2019) — линейная модель «объект — объект» с решением в замкнутом виде. G — матрица счётчиков
журнала: на диагонали число слушателей курса, вне диагонали число слушателей обоих курсов. P = (G + λI)⁻¹,
вес курса истории i для кандидата j: B[i][j] = −P[i][j] / P[j][j], диагональ B нулевая. Оценка кандидата —
сумма весов по курсам истории.

Чем вес отличается от доли слушателей. Доля N из M считает пару курсов отдельно от остальных. Вес EASE
подобран сразу по всем курсам: если курс j выбирают слушатели почти любого курса, его вес у каждого из них
меньше, а если его выбирают в основном слушатели курса i, вес у этого курса больше. Вес бывает
отрицательным: слушатели курса i берут курс j реже, чем следует из остальных их записей.

λ = 1000 выбрано вложенной проверкой на журнале обезличенной копии: наибольшая NDCG@5 в четырёх частях из пяти.
При таком λ и десятках курсов матрица хорошо обусловлена. Обращение — метод Гаусса — Жордана без сторонних
пакетов; оно кубическое по числу курсов, поэтому при числе курсов больше EASE_MAX_COURSES веса не строятся
и лента считает долю слушателей.

Масштаб. Веса EASE не доли. Чтобы вклад остался в прежних единицах, веса умножаются на один коэффициент каталога:
среднее по курсам с журналом наибольшей доли слушателей, делённое на среднее наибольшего веса.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

EASE_LAMBDA = 1000.0
EASE_MAX_COURSES = 300
_SINGULAR = 1e-12


def invert(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    """Обратная матрица методом Гаусса — Жордана с выбором главного элемента по столбцу."""
    n = len(matrix)
    a = [[float(v) for v in row] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < _SINGULAR:
            raise ValueError("матрица вырождена")
        a[col], a[pivot] = a[pivot], a[col]
        head = a[col][col]
        a[col] = [v / head for v in a[col]]
        lead = a[col]
        for r in range(n):
            factor = a[r][col]
            if r != col and factor != 0.0:
                a[r] = [v - factor * w for v, w in zip(a[r], lead, strict=True)]
    return [row[n:] for row in a]


def weights(
    totals: Mapping[str, int], together: Mapping[str, Mapping[str, int]], lam: float = EASE_LAMBDA
) -> dict[str, dict[str, float]]:
    """B[i][j] — вес курса истории i для кандидата j. `together` — все пары, а не только пары от порога поддержки."""
    items = sorted(totals)
    gram = [[totals[i] + lam if i == j else float(together.get(i, {}).get(j, 0)) for j in items] for i in items]
    p = invert(gram)
    return {i: {j: -p[a][b] / p[b][b] for b, j in enumerate(items) if a != b} for a, i in enumerate(items)}


def in_share_units(
    raw: Mapping[str, Mapping[str, float]],
    totals: Mapping[str, int],
    together: Mapping[str, Mapping[str, int]],
    min_users: int,
) -> dict[str, dict[str, float]]:
    """Веса в единицах доли слушателей: общий коэффициент по курсам, у которых слушателей не меньше `min_users`.

    Без таких курсов или без положительных весов возвращается пустой словарь: масштаб не определён.
    """
    logged = [course for course, users in totals.items() if users >= min_users and raw.get(course)]
    shares = [max(together.get(course, {}).values(), default=0) / totals[course] for course in logged]
    best = [max(raw[course].values()) for course in logged]
    mean_share = sum(shares) / len(shares) if shares else 0.0
    mean_weight = sum(best) / len(best) if best else 0.0
    if mean_share <= 0 or mean_weight <= 0:
        return {}
    scale = mean_share / mean_weight
    return {course: {other: value * scale for other, value in row.items()} for course, row in raw.items()}
