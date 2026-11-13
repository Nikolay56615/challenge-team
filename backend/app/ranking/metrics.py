"""Метрики офлайн-оценки на размеченном наборе (docs/plan.md, 3.7; кандидаты R05 и R13).

NDCG использует линейную выгоду и логарифмическое дисконтирование, как `ndcg_score` в scikit-learn;
экспоненциальная выгода 2^g − 1 включается параметром `gain`.
hit@k считает попадание материала с оценкой не ниже порога в первые k позиций.
Повторы кода в выдаче не учитываются: остаётся первое вхождение, поэтому NDCG не превышает 1.

Остальные метрики и номера находок — по обзору research/literature-recsys.md, раздел 5:
точность ранжирования (5.1), покрытие (5.2), внутрисписочное разнообразие (5.3), неожиданность
и серендипность (5.4), неравномерность показов (5.5), калибровка (5.6), экспозиция групп (5.7).
Бинарная релевантность — оценка не ниже `RELEVANT_GRADE`. Функции чистые и не зависят от каталога:
выдачи передаются списками кодов, свойства материалов — словарями. Если метрика не определена,
функция возвращает None; `mean_defined` усредняет только определённые значения.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence, Set
from math import ceil, log, log2

RELEVANT_GRADE = 2
GAINS = ("linear", "exponential")
# Длина полного маршрута; совпадает с explain.ROUTE_MAX_STEPS, это проверяет тест
FULL_ROUTE_STEPS = 3
# Голова по популярности для доли длинного хвоста: верхние 20 % материалов (находка 5.5)
HEAD_SHARE = 0.2
# Сглаживание выдачи в C_KL, как у Steck (2018) (находка 5.6)
CALIBRATION_ALPHA = 0.01
# Статусы, при которых выдача отвечает на задачу; none, cold и empty — запасной ответ (находка 5.2)
SERVED_STATUSES = frozenset({"strong", "weak"})
UNKNOWN_GROUP = "unknown"

Run = tuple[Sequence[str], Mapping[str, int]]


def dcg(gains: Sequence[float]) -> float:
    return sum(gain / log2(position + 2) for position, gain in enumerate(gains))


def unique(ranked: Sequence[str]) -> list[str]:
    """Коды выдачи без повторов, в порядке первого вхождения."""
    return list(dict.fromkeys(ranked))


def _gain_function(gain: str) -> Callable[[float], float]:
    if gain == "linear":
        return lambda grade: grade
    if gain == "exponential":
        return lambda grade: 2**grade - 1
    raise ValueError(f"unknown gain {gain}")


def ndcg_at_k(
    ranked: Sequence[str], grades: Mapping[str, int], k: int = 5, *, gain: str = "linear"
) -> float | None:
    """NDCG@k = DCG@k / IDCG@k (находка 5.1).

    `gain="linear"` — выгода равна оценке, `gain="exponential"` — 2^g − 1: при оценках 0–3 веса
    7 : 3 : 1 вместо 3 : 2 : 1, попадание высшего класса весит больше. None, если в разметке нет ни
    одного полезного материала: метрика не определена.
    """
    to_gain = _gain_function(gain)
    ideal = dcg([to_gain(grade) for grade in sorted(grades.values(), reverse=True)[:k]])
    if ideal == 0:
        return None
    return dcg([to_gain(grades.get(material_id, 0)) for material_id in unique(ranked)[:k]]) / ideal


def hit_at_k(ranked: Sequence[str], grades: Mapping[str, int], k: int = 3, threshold: int = RELEVANT_GRADE) -> bool:
    return any(grades.get(material_id, 0) >= threshold for material_id in unique(ranked)[:k])


def mean_defined(values: Iterable[float | None]) -> float | None:
    """Среднее определённых значений; None, если определённых нет."""
    defined = [value for value in values if value is not None]
    return sum(defined) / len(defined) if defined else None


# ---------- точность ранжирования, находка 5.1 ----------


def relevant_set(grades: Mapping[str, int], threshold: int = RELEVANT_GRADE) -> set[str]:
    """Rel_u: материалы с оценкой не ниже порога."""
    return {material_id for material_id, grade in grades.items() if grade >= threshold}


def _hits(ranked: Sequence[str], relevant: Set[str], k: int) -> list[bool]:
    return [material_id in relevant for material_id in unique(ranked)[:k]]


def precision_at_k(
    ranked: Sequence[str], grades: Mapping[str, int], k: int = 5, threshold: int = RELEVANT_GRADE
) -> float | None:
    """P@k = |Rel ∩ L@k| / k.

    Знаменатель — k, а не длина выдачи: пустые позиции короткой выдачи считаются нерелевантными.
    None при k < 1 и для профиля без релевантных материалов в разметке: такой профиль не различает
    методы, поэтому в средние не входит, как и в R@k, AP@k и RR.
    """
    relevant = relevant_set(grades, threshold)
    if k < 1 or not relevant:
        return None
    return sum(_hits(ranked, relevant, k)) / k


def recall_at_k(
    ranked: Sequence[str], grades: Mapping[str, int], k: int = 5, threshold: int = RELEVANT_GRADE
) -> float | None:
    """R@k = |Rel ∩ L@k| / |Rel|. При |Rel| > k полнота меньше 1 даже у идеальной выдачи.

    None при k < 1 и без релевантных материалов в разметке.
    """
    relevant = relevant_set(grades, threshold)
    if k < 1 or not relevant:
        return None
    return sum(_hits(ranked, relevant, k)) / len(relevant)


def reciprocal_rank(
    ranked: Sequence[str], grades: Mapping[str, int], k: int = 5, threshold: int = RELEVANT_GRADE
) -> float | None:
    """RR@k = 1 / позиция первого релевантного в первых k; 0, если его там нет.

    None при k < 1 и без релевантных материалов в разметке.
    """
    relevant = relevant_set(grades, threshold)
    if k < 1 or not relevant:
        return None
    for position, hit in enumerate(_hits(ranked, relevant, k), start=1):
        if hit:
            return 1 / position
    return 0.0


def average_precision_at_k(
    ranked: Sequence[str], grades: Mapping[str, int], k: int = 5, threshold: int = RELEVANT_GRADE
) -> float | None:
    """AP@k = (1 / min(k, |Rel|)) Σ_{i ≤ k} rel_i · P@i.

    Нормировка на min(k, |Rel|): идеальная выдача получает 1, даже если релевантных больше k.
    None при k < 1 и без релевантных материалов в разметке.
    """
    relevant = relevant_set(grades, threshold)
    if k < 1 or not relevant:
        return None
    found = 0
    total = 0.0
    for position, hit in enumerate(_hits(ranked, relevant, k), start=1):
        if hit:
            found += 1
            total += found / position
    return total / min(k, len(relevant))


def mean_reciprocal_rank(runs: Iterable[Run], k: int = 5, threshold: int = RELEVANT_GRADE) -> float | None:
    """MRR@k: среднее RR@k по профилям, у которых RR определён. `runs` — пары (выдача, разметка)."""
    return mean_defined(reciprocal_rank(ranked, grades, k, threshold) for ranked, grades in runs)


def mean_average_precision(runs: Iterable[Run], k: int = 5, threshold: int = RELEVANT_GRADE) -> float | None:
    """MAP@k: среднее AP@k по профилям, у которых AP определён. `runs` — пары (выдача, разметка)."""
    return mean_defined(average_precision_at_k(ranked, grades, k, threshold) for ranked, grades in runs)


# ---------- покрытие и необслуженные профили, находка 5.2 ----------


def catalog_coverage(lists: Iterable[Sequence[str]], catalog: Collection[str], k: int = 5) -> float | None:
    """Покрытие каталога@k = |∪_u L_u@k ∩ I| / |I|.

    `catalog` — множество I, например доступные материалы или только курсы: коды выдачи вне I
    не считаются. None, если I пусто.
    """
    universe = set(catalog)
    if not universe:
        return None
    shown = {material_id for ranked in lists for material_id in unique(ranked)[:k]}
    return len(shown & universe) / len(universe)


def user_coverage(
    lists: Sequence[Sequence[str]], statuses: Sequence[str] | None = None, served: Set[str] = SERVED_STATUSES
) -> float | None:
    """Доля профилей с непустой выдачей.

    Если переданы статусы, профиль обслужен только при статусе из `served` (strong или weak):
    стартовая подборка при none и cold — запасной ответ, а не ответ на задачу. Доля необслуженных
    по статусам — 1 минус покрытие. None для пустого набора профилей.
    """
    if statuses is not None and len(statuses) != len(lists):
        raise ValueError("statuses and lists differ in length")
    if not lists:
        return None
    count = sum(
        1 for index, ranked in enumerate(lists) if ranked and (statuses is None or statuses[index] in served)
    )
    return count / len(lists)


def unserved_share(
    lists: Sequence[Sequence[str]],
    grades: Sequence[Mapping[str, int]],
    k: int = 5,
    threshold: int = RELEVANT_GRADE,
) -> float | None:
    """Доля профилей без пользы: выдача пуста или в первых k нет материала с оценкой не ниже порога.

    Профиль без релевантных материалов в разметке считается необслуженным: это пробел каталога,
    его метрика и должна показать. Равна 1 − среднее hit@k по всем профилям. None для пустого набора.
    """
    if len(grades) != len(lists):
        raise ValueError("grades and lists differ in length")
    if not lists:
        return None
    missed = sum(
        1 for ranked, labels in zip(lists, grades, strict=True) if not hit_at_k(ranked, labels, k, threshold)
    )
    return missed / len(lists)


# ---------- внутрисписочное разнообразие, находка 5.3 ----------


def jaccard_distance(a: Set[str], b: Set[str]) -> float | None:
    """1 − |a ∩ b| / |a ∪ b|. None, если оба множества пусты: сравнивать нечего."""
    union = a | b
    if not union:
        return None
    return 1 - len(a & b) / len(union)


def intra_list_diversity(features: Sequence[Set[str]]) -> float | None:
    """ILD = (2 / (n(n − 1))) Σ_{i<j} d(i, j), d — расстояние Жаккара (Ziegler et al., 2005).

    `features` — множества признаков материалов выдачи, например темы или темы вместе с признаками
    из текста. Пары, где у обоих материалов множество пусто, пропускаются, и среднее берётся по
    остальным парам. 0 — все материалы одинаковы, 1 — попарно без общих признаков. Позиция не
    учитывается. None, если материалов меньше двух или все пары пропущены.
    """
    distances = [
        distance
        for i in range(len(features))
        for j in range(i + 1, len(features))
        if (distance := jaccard_distance(features[i], features[j])) is not None
    ]
    return sum(distances) / len(distances) if distances else None


# ---------- неожиданность и серендипность, находка 5.4 ----------


def unexpectedness(ranked: Sequence[str], reference: Sequence[str], k: int = 5) -> float | None:
    """UNEXP = |L@k \\ PM@k| / |L@k| (Kaminskas, Bridge, 2016).

    PM — выдача примитивной модели; у нас это подбор по теме. 0 — выдача повторяет PM, 1 — не имеет
    с ней общих материалов. Порядок не учитывается. None для пустой выдачи.
    """
    shown = unique(ranked)[:k]
    if not shown:
        return None
    expected = set(unique(reference)[:k])
    return sum(1 for material_id in shown if material_id not in expected) / len(shown)


def serendipity(
    ranked: Sequence[str],
    reference: Sequence[str],
    grades: Mapping[str, int],
    k: int = 5,
    threshold: int = RELEVANT_GRADE,
) -> float | None:
    """SER = |(L@k \\ PM@k) ∩ Useful| / |L@k|, Useful — оценка не ниже порога по разметке.

    Доля выдачи, которую примитивная модель не предложила бы и которая полезна. None для пустой
    выдачи и для профиля без релевантных материалов в разметке.
    """
    shown = unique(ranked)[:k]
    useful = relevant_set(grades, threshold)
    if not shown or not useful:
        return None
    expected = set(unique(reference)[:k])
    return sum(1 for material_id in shown if material_id not in expected and material_id in useful) / len(shown)


# ---------- неравномерность показов и длинный хвост, находка 5.5 ----------


def exposure_counts(lists: Iterable[Sequence[str]], catalog: Collection[str], k: int = 5) -> dict[str, int]:
    """Число показов каждого материала I в первых k позициях; материалы без показов — с нулём.

    Коды выдачи вне I не считаются.
    """
    counts = dict.fromkeys(catalog, 0)
    for ranked in lists:
        for material_id in unique(ranked)[:k]:
            if material_id in counts:
                counts[material_id] += 1
    return counts


def gini_index(values: Iterable[float]) -> float | None:
    """Индекс Джини показов: G = (1 / (n − 1)) Σ_{j=1..n} (2j − n − 1) · p_j.

    p_j — доли показов, упорядоченные по возрастанию; n — число материалов, включая материалы без
    показов (Shani, Gunawardana, 2011). 0 — показы распределены поровну, 1 — все у одного материала.
    При m показах, разнесённых по m разным материалам, G = (n − m) / (n − 1): на большом каталоге
    и малом числе выдач индекс близок к 1 по построению, поэтому сравнивать стоит методы между собой.
    None при n < 2 или без показов. Отрицательное значение — ошибка.
    """
    shares = sorted(values)
    if any(value < 0 for value in shares):
        raise ValueError("exposure must be non-negative")
    n = len(shares)
    total = sum(shares)
    if n < 2 or total == 0:  # noqa: PLR2004 — формула делит на n − 1
        return None
    return sum((2 * j - n - 1) * value / total for j, value in enumerate(shares, start=1)) / (n - 1)


def long_tail(popularity: Mapping[str, float], head_share: float = HEAD_SHARE) -> frozenset[str]:
    """Хвост Γ: материалы вне головы по популярности.

    Голова — первые ⌈head_share · n⌉ материалов в порядке «популярность по убыванию, затем код»,
    как в разрешении равенств подбора; равные по популярности материалы на границе головы делятся
    по коду. При head_share = 0,2 и 23 материалах голова — 5 материалов, хвост — 18.
    """
    if not 0 <= head_share <= 1:
        raise ValueError("head_share must be within [0, 1]")
    ordered = sorted(popularity, key=lambda material_id: (-popularity[material_id], material_id))
    head_size = ceil(round(head_share * len(ordered), 9))
    return frozenset(ordered[head_size:])


def long_tail_share(lists: Iterable[Sequence[str]], tail: Set[str], k: int = 5) -> float | None:
    """APLT@k = (1 / |U|) Σ_u |L_u@k ∩ Γ| / |L_u@k| (Abdollahpouri et al., 2019).

    Среднее по профилям с непустой выдачей. None, если непустых выдач нет.
    """
    shares = []
    for ranked in lists:
        shown = unique(ranked)[:k]
        if shown:
            shares.append(sum(1 for material_id in shown if material_id in tail) / len(shown))
    return mean_defined(shares)


# ---------- экспозиция групп, находка 5.7 ----------


def position_discount(rank: int) -> float:
    """1 / log2(rank + 1), позиция с единицы: первая — 1, вторая — 0,63, пятая — 0,39."""
    if rank < 1:
        raise ValueError("rank starts at 1")
    return 1 / log2(rank + 1)


def exposure_share(
    lists: Iterable[Sequence[str]], group_of: Mapping[str, str], k: int = 5
) -> dict[str, float] | None:
    """Доля экспозиции группы с ранговым дисконтом (Mehrotra et al., 2018).

    Exp_g = Σ_u Σ_{i ∈ L_u@k, group(i) = g} disc(rank_i) / Σ_u Σ_{i ∈ L_u@k} disc(rank_i),
    disc — `position_discount`. Группа — формат или доступ; материал без группы попадает в
    `UNKNOWN_GROUP`. Доли в сумме дают 1. None, если все выдачи пусты.
    """
    weights: defaultdict[str, float] = defaultdict(float)
    for ranked in lists:
        for rank, material_id in enumerate(unique(ranked)[:k], start=1):
            weights[group_of.get(material_id, UNKNOWN_GROUP)] += position_discount(rank)
    total = sum(weights.values())
    if total == 0:
        return None
    return {group: weights[group] / total for group in sorted(weights)}


# ---------- калибровка по темам, находка 5.6 ----------


def topic_distribution(topic_sets: Iterable[Collection[str]]) -> dict[str, float]:
    """p(g) = Σ_i p(g | i) / N, p(g | i) = 1 / |темы i| (Steck, 2018), веса материалов равные.

    Материалы без тем пропускаются, N — число материалов с темами. Пустой словарь — тем нет.
    """
    mass: defaultdict[str, float] = defaultdict(float)
    count = 0
    for topics in topic_sets:
        distinct = set(topics)
        if not distinct:
            continue
        count += 1
        for topic in distinct:
            mass[topic] += 1 / len(distinct)
    return {topic: value / count for topic, value in sorted(mass.items())} if count else {}


def miscalibration(
    history: Mapping[str, float], recommended: Mapping[str, float], alpha: float = CALIBRATION_ALPHA
) -> float | None:
    """C_KL(p, q) = Σ_g p(g) · ln(p(g) / q̃(g)), q̃ = (1 − α) q + α p (Steck, 2018).

    p — распределение тем истории, q — тем выдачи, оба из `topic_distribution`. Сглаживание α = 0,01
    не даёт делить на ноль, когда тема истории в выдаче не встречается: такое слагаемое равно
    p(g) · ln(1 / α), а при выдаче совсем без тем истории C_KL = ln(1 / α) ≈ 4,61. 0 — темы выдачи
    повторяют темы истории. Логарифм натуральный. None, если p или q пусты.
    """
    if not 0 < alpha <= 1:
        raise ValueError("alpha must be within (0, 1]")
    if not history or not recommended:
        return None
    return sum(
        p * log(p / ((1 - alpha) * recommended.get(topic, 0.0) + alpha * p))
        for topic, p in history.items()
        if p > 0
    )


# ---------- маршрут на первую неделю, кандидат R13 (находка 3.2) ----------


def full_route_share(route_lengths: Sequence[int], steps: int = FULL_ROUTE_STEPS) -> float | None:
    """Доля профилей с полным маршрутом: в маршруте не меньше `steps` шагов.

    Передаются длины маршрутов профилей, которым маршрут положен (docs/plan.md, 3.6: статус strong,
    стадия idea или start); пустой маршрут — длина 0. None для пустого набора.
    """
    if not route_lengths:
        return None
    return sum(1 for length in route_lengths if length >= steps) / len(route_lengths)
