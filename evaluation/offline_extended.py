"""Расширенный протокол O1: статистика сравнения, настройка совместных записей, EASE, проверка весов.

PLAN.md, 12.1, R01, R03, R04 и R08. Вызывается из `offline_courses.py` с флагом `--extended`
после основной оценки и получает её состояние: случаи, части, результаты трёх исходных методов.

- R03 и R04: параметры выбираются вложенно. Для каждой внешней проверочной части четыре обучающие
  части по очереди служат валидационной, остальные три вместе с пользователями одного курса —
  обучающей. Выбирается сочетание с наибольшей средней NDCG@5 валидации, при равенстве — с
  большим hit@5, затем исходное. Счётчики для проверочной части считаются по всей обучающей.
- R08: веса учатся по обучающим частям внешней части и проверяются на её проверочной части.
- R01: парный бутстреп по пользователям и перестановочный тест со сменой знака для каждого
  сравнения, поправка Холма — Бонферрони на всё семейство сравнений обеих метрик.

Выводятся только агрегаты.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from itertools import product

import offline_models as models
import offline_stats as stats
import offline_weights as weights
from app.ranking.metrics import hit_at_k, ndcg_at_k

K = 5
RESAMPLES = 5000
PERMUTATIONS = 10000
ALPHAS = (0.0, 0.25, 0.5, 0.75, 1.0)
NEIGHBOURS: tuple[int | None, ...] = (None, 1, 2, 3, 5, 10)
SUPPORTS = (1, 2, 3, 5, 10)
LAMBDAS = (1.0, 3.0, 10.0, 30.0, 100.0, 300.0, 1000.0, 3000.0)
ORIGINAL = models.CoConfig(1.0, None, 1)
GRID = [ORIGINAL] + [
    models.CoConfig(a, k, s) for a, s, k in product(ALPHAS, SUPPORTS, NEIGHBOURS) if models.CoConfig(a, k, s) != ORIGINAL
]

METHODS = ("popularity", "rules", "coenroll", "coenroll_norm", "ease", "rules_learned")
LABELS = {
    "popularity": "Популярность",
    "rules": "Правила по темам",
    "coenroll": "Совместные записи",
    "coenroll_norm": "Нормированные совместные записи",
    "ease": "EASE",
    "rules_learned": "Правила с обученными весами",
    "sequential": "Последовательные правила",
}
FEATURE_LABELS = {"topic": "Тема", "continuation": "Продолжение", "popularity": "Популярность, нормированная"}


def fmt(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",").replace("-", "−")


def signed(value: float, digits: int = 3) -> str:
    text = fmt(abs(value), digits)
    return ("+" if value > 0 else "−" if value < 0 else "") + text if round(value, digits) else fmt(0.0, digits)


def pvalue(p: float) -> str:
    return "< 0,001" if p < 0.001 else fmt(p, 3)


def thousands(n: float) -> str:
    return f"{n:,.0f}".replace(",", " ")


def run(state) -> None:
    cases = state.cases
    available: list[str] = state.available
    universe = frozenset(available)
    items = sorted(state.courses)
    materials = state.catalog.materials
    disabled = state.disabled
    singles = [[(b.course, b.order) for b in bindings] for bindings in state.single_users]
    full = {case.user: [(b.course, b.order) for b in state.by_user[case.user]] for case in cases}
    results = state.results
    by_user = {r.case.user: r for r in results}
    folds = sorted({case.fold for case in cases})

    extra: dict[str, dict[str, list[str]]] = defaultdict(dict)
    co_rows: list[tuple[int, int, models.CoConfig, float, float]] = []
    alpha_best: dict[float, list[float]] = defaultdict(list)
    lam_rows: list[tuple[int, float, float]] = []
    lam_curve: dict[float, list[float]] = defaultdict(list)
    learned: list[list[float]] = []
    active_features: Counter[str] = Counter()
    pair_totals: list[tuple[int, int]] = []
    ordered_pairs: list[int] = []
    original_match = 0
    explanation: Counter[str] = Counter()
    top2_shares: list[float] = []

    for fold in folds:
        train_cases = [c for c in cases if c.fold != fold]
        co_score: dict[models.CoConfig, list[float]] = {cfg: [0.0, 0.0] for cfg in GRID}
        lam_score: dict[float, list[float]] = {lam: [0.0, 0.0] for lam in LAMBDAS}
        validated = 0
        for inner in folds:
            if inner == fold:
                continue
            counts = models.count(singles + [full[c.user] for c in train_cases if c.fold != inner])
            popularity = counts.users
            val = validation_cases([c for c in train_cases if c.fold == inner], universe, available)
            validated += len(val)
            for alpha, support in product(ALPHAS, SUPPORTS):
                base = models.similarity(counts, universe, alpha, support)
                for k in NEIGHBOURS:
                    sim = models.keep_neighbours(base, k, popularity)
                    accumulate(co_score[models.CoConfig(alpha, k, support)], sim, val, popularity)
            for lam in LAMBDAS:
                accumulate(lam_score[lam], models.ease(counts, items, lam), val, popularity)
        best = max(GRID, key=lambda cfg: (round(co_score[cfg][0], 9), round(co_score[cfg][1], 9)))
        co_rows.append(
            (fold, validated, best, co_score[best][0] / validated, co_score[ORIGINAL][0] / validated)
        )
        for alpha in ALPHAS:
            alpha_best[alpha].append(max(v[0] for cfg, v in co_score.items() if cfg.alpha == alpha) / validated)
        lam = max(LAMBDAS, key=lambda x: (round(lam_score[x][0], 9), round(lam_score[x][1], 9)))
        lam_rows.append((fold, lam, lam_score[lam][0] / validated))
        for x in LAMBDAS:
            lam_curve[x].append(lam_score[x][0] / validated)

        counts = models.count(singles + [full[c.user] for c in train_cases])
        popularity = counts.users
        top = max(popularity.values())
        ordered_pairs.append(sum(sum(row.values()) for row in counts.ordered.values()))
        original = models.keep_neighbours(models.similarity(counts, universe, 1.0, 1), None, popularity)
        tuned = models.keep_neighbours(models.similarity(counts, universe, best.alpha, best.support), best.neighbours, popularity)
        ease_weights = models.ease(counts, items, lam)
        sequential = models.sequential_weights(counts)

        groups = []
        for c in train_cases:
            if c.target not in universe:
                continue
            ctx = weights.context(c.inputs, materials, disabled, K)
            inputs = {b.course for b in c.inputs}
            vectors = {}
            for m in available:
                if m in inputs:
                    continue
                indicators, active = weights.rule_features(ctx, materials[m])
                active_features.update(active)
                own = 1 if m == c.target else 0
                vectors[m] = weights.vector(indicators, (popularity.get(m, 0) - own) / top)
            groups.append((vectors[c.target], [v for m, v in vectors.items() if m != c.target]))
        pairs = weights.pair_differences(groups)
        w = weights.fit(pairs)
        learned.append(w)
        pair_totals.append((sum(len(o) for _, o in groups), sum(pairs.values())))

        for r in (by_user[c.user] for c in cases if c.fold == fold and c.user in by_user):
            inputs = [b.course for b in r.case.inputs]
            candidates = [c for c in available if c not in set(inputs)]
            if models.rank(models.sum_scores(original, inputs, candidates), candidates, popularity) == r.ranked["coenroll"]:
                original_match += 1
            ranked = extra[r.case.user]
            ranked["coenroll_norm"] = models.rank(models.sum_scores(tuned, inputs, candidates), candidates, popularity)
            ranked["ease"] = models.rank(models.sum_scores(ease_weights, inputs, candidates), candidates, popularity)
            ranked["sequential"] = models.rank(models.sum_scores(sequential, inputs, candidates), candidates, popularity)
            ctx = weights.context(r.case.inputs, materials, disabled, K)
            learned_score = {
                m: weights.score(w, weights.vector(weights.rule_features(ctx, materials[m])[0], popularity.get(m, 0) / top))
                for m in candidates
            }
            ranked["rules_learned"] = models.rank(learned_score, candidates, popularity)
            explain(ease_weights, inputs, ranked["ease"][0], explanation, top2_shares)

    def ranking(r, method: str) -> list[str]:
        return r.ranked[method] if method in r.ranked else extra[r.case.user][method]

    strict = [r for r in results if r.case.strict]
    random_target = [r for r in results if not r.case.strict]
    series = {m: metric_series(results, ranking, m) for m in METHODS}
    strict_series = {m: metric_series(strict, ranking, m) for m in (*METHODS, "sequential")}
    random_series = {m: metric_series(random_target, ranking, m) for m in METHODS}

    print("## Расширенный протокол: R01, R03, R04, R08\n")
    print(
        f"Зёрна: разбиение {state.seed} и {state.seed + 1}, бутстреп {state.seed + 2}, перестановки {state.seed + 3}. "
        f"Повтор исходного метода: α 1, все соседи, поддержка 1 дают порядок исходных совместных записей у "
        f"{original_match} из {len(results)} пользователей.\n"
    )
    print("### Методы на проверочных частях\n")
    print("| Метод | Все, hit@5 | Все, NDCG@5 | Строгий порядок, hit@5 | NDCG@5 | Случайная цель, hit@5 | NDCG@5 |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for m in (*METHODS, "sequential"):
        cells = []
        for table in (series, strict_series, random_series):
            if m in table:
                hits, ndcgs = table[m]
                cells += [fmt(mean(hits)), fmt(mean(ndcgs))]
            else:
                cells += ["—", "—"]
        print(f"| {LABELS[m]} | {' | '.join(cells)} |")
    print(f"\nПользователей: все {len(results)}, строгий порядок {len(strict)}, случайная цель {len(random_target)}.\n")

    print("### R03. Нормированные совместные записи\n")
    print(
        f"Сетка: α {{{'; '.join(models.fmt_alpha(a) for a in ALPHAS)}}}, соседей {{все, "
        f"{', '.join(str(k) for k in NEIGHBOURS if k)}}}, минимальная поддержка {{{', '.join(map(str, SUPPORTS))}}} — "
        f"{len(GRID)} сочетаний.\n"
    )
    print("| Внешняя часть | Валидационных случаев | Выбрано | NDCG@5 валидации | NDCG@5 исходного метода на валидации |")
    print("| ---: | ---: | --- | ---: | ---: |")
    for fold, validated, cfg, value, base_value in co_rows:
        print(f"| {fold + 1} | {validated} | {cfg.label()} | {fmt(value, 3)} | {fmt(base_value, 3)} |")
    print()
    print("| α | Лучшая NDCG@5 валидации по соседям и поддержке, среднее по внешним частям |")
    print("| ---: | ---: |")
    for alpha in ALPHAS:
        print(f"| {models.fmt_alpha(alpha)} | {fmt(mean(alpha_best[alpha]), 3)} |")
    print()
    print(
        f"Последовательные правила: упорядоченных пар курсов в обучающей части в среднем "
        f"{thousands(mean(ordered_pairs))}; метод оценивается только на {len(strict)} пользователях со строгим "
        f"порядком, где все курсы входа предшествуют цели.\n"
    )

    print("### R04. EASE\n")
    print("| Внешняя часть | Выбранное λ | NDCG@5 валидации |")
    print("| ---: | ---: | ---: |")
    for fold, lam, value in lam_rows:
        print(f"| {fold + 1} | {thousands(lam)} | {fmt(value, 3)} |")
    print()
    print("| λ | NDCG@5 валидации, среднее по внешним частям |")
    print("| ---: | ---: |")
    for x in LAMBDAS:
        print(f"| {thousands(x)} | {fmt(mean(lam_curve[x]), 3)} |")
    print()
    multi = explanation["inputs_2plus"]
    print(
        f"Объяснение первой карточки EASE: положительное наибольшее слагаемое у {explanation['top_positive']} из "
        f"{explanation['users']} пользователей; при двух и более курсах входа оба наибольших слагаемых положительны у "
        f"{explanation['two_positive']} из {multi}; при трёх и более курсах входа два наибольших слагаемых дают в "
        f"среднем {fmt(mean(top2_shares) if top2_shares else 0.0)} суммы положительных слагаемых "
        f"({len(top2_shares)} пользователей).\n"
    )

    print("### R08. Обученные веса правил\n")
    print("| Признак | Ручной вес | Обученный вес, среднее по частям | Минимум — максимум | В масштабе «тема = 3,0» |")
    print("| --- | ---: | ---: | --- | ---: |")
    averages = [mean([w[i] for w in learned]) for i in range(len(weights.FEATURES))]
    topic_scale = 3.0 / averages[0] if averages[0] else 0.0
    for i, feature in enumerate(weights.FEATURES):
        values = [w[i] for w in learned]
        manual = fmt(weights.MANUAL[feature], 1) if feature in weights.MANUAL else "только равенства"
        print(
            f"| {FEATURE_LABELS[feature]} | {manual} | {fmt(averages[i], 3)} | {fmt(min(values), 3)} — "
            f"{fmt(max(values), 3)} | {fmt(averages[i] * topic_scale, 2)} |"
        )
    total_pairs = mean([p for p, _ in pair_totals])
    informative = mean([n for _, n in pair_totals])
    active = "; ".join(
        f"{FEATURE_LABELS.get(name, name).lower()} — {thousands(n)}" for name, n in sorted(active_features.items())
    )
    manual_order = sorted(weights.MANUAL, key=lambda f: -weights.MANUAL[f]) + ["popularity"]
    learned_order = [weights.FEATURES[i] for i in sorted(range(len(averages)), key=lambda i: -averages[i])]
    same_signs = all(a > 0 for a in averages)
    print(
        f"\nПар «цель — другой кандидат» на внешнюю часть в среднем {thousands(total_pairs)}, с ненулевой разницей "
        f"признаков {thousands(informative)}; L2-штраф {fmt(weights.L2, 1)}. Ненулевой вклад в обучающих парах "
        f"«пользователь — кандидат» за пять внешних частей дали только признаки: {active}.\n"
    )
    print(
        f"Знаки обученных весов {'совпадают с ручными: все положительны' if same_signs else 'расходятся с ручными'}. "
        f"Порядок ручных: {' > '.join(FEATURE_LABELS[f].lower() for f in manual_order)}; обученных: "
        f"{' > '.join(FEATURE_LABELS[f].lower() for f in learned_order)}.\n"
    )

    comparisons: list[tuple[str, str, str]] = [(m, "popularity", "all") for m in METHODS if m != "popularity"]
    ranked_methods = sorted(METHODS, key=lambda m: (-mean(series[m][1]), METHODS.index(m)))
    for pair in (
        (ranked_methods[0], ranked_methods[1], "all"),
        ("coenroll_norm", "coenroll", "all"),
        ("ease", "coenroll", "all"),
        ("rules_learned", "rules", "all"),
        ("sequential", "coenroll", "strict"),
        ("sequential", "popularity", "strict"),
    ):
        if not any({a, b} == {pair[0], pair[1]} and g == pair[2] for a, b, g in comparisons):
            comparisons.append(pair)
    tests = []
    for population, table, n in (("all", series, len(results)), ("strict", strict_series, len(strict))):
        diffs = {}
        for a, b, g in comparisons:
            if g != population:
                continue
            for metric in (0, 1):
                diffs[(a, b, g, metric)] = [x - y for x, y in zip(table[a][metric], table[b][metric])]
        intervals = stats.paired_bootstrap(diffs, RESAMPLES, state.seed + 2)
        for key, values in diffs.items():
            tests.append((key, n, mean(values), intervals[key], stats.sign_flip_pvalue(values, PERMUTATIONS, state.seed + 3)))
    adjusted = stats.holm([t[4] for t in tests])
    by_key = {t[0]: (t, adj) for t, adj in zip(tests, adjusted)}

    print("### R01. Парные сравнения\n")
    print(
        f"Две лучшие по NDCG@5 на всех пользователях: {LABELS[ranked_methods[0]]} и {LABELS[ranked_methods[1]]}. "
        f"Интервал — 95 % перцентильный парного бутстрепа по пользователям, {thousands(RESAMPLES)} выборок; p — "
        f"двусторонний перестановочный тест со сменой знака, {thousands(PERMUTATIONS)} перестановок; поправка "
        f"Холма — Бонферрони на семейство из {len(tests)} проверок.\n"
    )
    print("| Сравнение | Пользователей | Δ hit@5 [95 % ДИ] | p | p Холма | Δ NDCG@5 [95 % ДИ] | p | p Холма |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for a, b, g in comparisons:
        cells = []
        n = 0
        for metric in (0, 1):
            (key, n, value, (low, high), p), adj = by_key[(a, b, g, metric)]
            cells += [f"{signed(value)} [{signed(low)}; {signed(high)}]", pvalue(p), pvalue(adj)]
        group = "" if g == "all" else ", строгий порядок"
        print(f"| {LABELS[a]} − {LABELS[b]}{group} | {n} | {' | '.join(cells)} |")
    print()

    print_mde(state, comparisons, series, len(results))


def validation_cases(cases: Sequence, universe: frozenset[str], available: list[str]) -> list[tuple]:
    """Курсы входа, кандидаты и цель валидационных случаев с доступной целью."""
    prepared = []
    for case in cases:
        if case.target not in universe:
            continue
        inputs = [b.course for b in case.inputs]
        excluded = set(inputs)
        prepared.append((inputs, [c for c in available if c not in excluded], case.target))
    return prepared


def accumulate(acc: list[float], weights_: models.Similarity, val: Sequence, popularity: Counter[str]) -> None:
    for inputs, candidates, target in val:
        position = models.target_position(models.sum_scores(weights_, inputs, candidates), candidates, popularity, target)
        hit, ndcg = models.hit_ndcg(position, K)
        acc[0] += ndcg
        acc[1] += hit


def explain(ease_weights: models.Similarity, inputs: list[str], first: str, counter: Counter[str], shares: list[float]) -> None:
    """Агрегаты объяснения «два наибольших слагаемых» для первой карточки EASE."""
    parts = models.contributions(ease_weights, inputs, first)
    counter["users"] += 1
    if parts and parts[0][0] > 0:
        counter["top_positive"] += 1
    if len(inputs) >= 2:
        counter["inputs_2plus"] += 1
        if parts[1][0] > 0:
            counter["two_positive"] += 1
    if len(inputs) >= 3:
        positive = sum(v for v, _ in parts if v > 0)
        if positive > 0:
            shares.append(sum(v for v, _ in parts[:2] if v > 0) / positive)


def metric_series(results: Sequence, ranking, method: str) -> tuple[list[float], list[float]]:
    """hit@5 и NDCG@5 по пользователям функциями `app/ranking/metrics.py`."""
    hits, ndcgs = [], []
    for r in results:
        grades = {r.case.target: 2}
        ranked = ranking(r, method)
        hits.append(1.0 if hit_at_k(ranked, grades, K) else 0.0)
        ndcgs.append(ndcg_at_k(ranked, grades, K) or 0.0)
    return hits, ndcgs


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


PLAN_7_3 = {
    0.003: (547690, 143421, 26064),
    0.01: (163095, 42693, 7750),
    0.03: (53211, 13914, 2518),
    0.05: (31234, 8158, 1471),
}


def print_mde(state, comparisons, series, n_users: int) -> None:
    lifts = (0.1, 0.2, 0.5)
    matched = sum(
        stats.sample_size(p, p * (1 + lift)) == expected
        for p, row in PLAN_7_3.items()
        for lift, expected in zip(lifts, row)
    )
    bindings = [b for user in state.by_user.values() for b in user]
    users = len(state.by_user)
    multi = sum(1 for user in state.by_user.values() if len({b.course for b in user}) >= 2)
    started = sum(1 for b in bindings if b.event in ("start", "complete")) / len(bindings)
    completed = sum(1 for b in bindings if b.event == "complete") / len(bindings)
    paid = sum(1 for b in bindings if b.paid) / len(bindings)
    rows = (
        ("Клик по карточке", 0.30, "допущение, research/literature-recsys.md, 6.6"),
        ("Старт за 7 дней после показа (OEC)", 0.05, "допущение, research/literature-recsys.md, 6.6"),
        ("Запись на второй курс", multi / users, f"копия: {thousands(multi)} из {thousands(users)} пользователей"),
        ("Старт записанного курса", started, "копия: статус 1 или 2 у доли записей"),
        ("Завершение записанного курса", completed, "копия: статус 2 у доли записей"),
        ("Покупка, для сравнения с 7.3", paid, "копия: `IsPaid` у доли записей"),
    )
    sizes = (len(state.cases) // 2, users // 2, 10000, 30000)
    print("### Минимальный обнаружимый эффект\n")
    print(
        f"Формула объёма — две независимые доли, двусторонний α 0,05, мощность 0,8, как в PLAN.md, 7.3; "
        f"она повторяет {matched} из {len(PLAN_7_3) * len(lifts)} значений таблицы 7.3. В ячейке — относительный "
        f"прирост и в скобках абсолютный, в процентных пунктах. Столбцы — пользователей на группу: половина "
        f"{thousands(len(state.cases))} пользователей с двумя и более курсами, половина {thousands(users)} "
        f"пользователей с записями, 10 000 и 30 000.\n"
    )
    print(f"| Метрика | Базовая доля | Источник | {' | '.join(thousands(n) for n in sizes)} |")
    print(f"| --- | ---: | --- | {' | '.join('---:' for _ in sizes)} |")
    for title, p, source in rows:
        cells = []
        for n in sizes:
            delta = stats.mde_two_proportions(p, n)
            cells.append("недостижим" if delta is None else f"{fmt(100 * delta / p, 0)} % ({fmt(100 * delta, 1)})")
        print(f"| {title} | {fmt(p, 3)} | {source} | {' | '.join(cells)} |")
    print()
    print(
        f"Офлайн, парное сравнение hit@5 на {n_users} пользователях: обнаружимая разница при α 0,05 и мощности 0,8 "
        f"по формуле Макнемара для наблюдаемой доли несогласных пар.\n"
    )
    print("| Сравнение | Доля несогласных пар | Наблюдаемая разница hit@5 | Обнаружимая разница |")
    print("| --- | ---: | ---: | ---: |")
    for a, b, g in comparisons:
        if g != "all":
            continue
        ha, hb = series[a][0], series[b][0]
        discordant = sum(1 for x, y in zip(ha, hb) if x != y) / n_users
        delta = stats.mde_paired(n_users, discordant)
        print(
            f"| {LABELS[a]} − {LABELS[b]} | {fmt(discordant, 3)} | {signed(mean(ha) - mean(hb))} | "
            f"{'недостижима' if delta is None else fmt(delta, 3)} |"
        )
    print()
