"""Офлайн-оценка по записям на курсы на локальной копии выгрузки.

Протокол. Берутся пользователи с двумя и более курсами. У пользователей со строгим порядком
событий (все `EventOrder` различны) цель — последний курс по `EventOrder`, вход — остальные
записи. У остальных цель — один случайный курс с фиксированным зерном. Кандидаты — доступные
курсы каталога без курсов входа. Пользователи, чья цель в каталоге недоступна, в метрики не
входят и считаются отдельно.

Методы:
- популярность — число записей на курс;
- правила по темам — персональный подбор приложения без текста задачи: кандидаты тем курсов
  входа, вклад темы, продолжение по редакционным связям и история; остаток пятёрки — по
  популярности;
- совместные записи — сумма по курсам входа доли их пользователей, записавшихся и на кандидата.

Популярность и совместные записи считаются только по обучающей части: пользователи с двумя и
более курсами разбиты на пять частей, каждая по очереди проверочная (80 на 20), пользователи с
одним курсом всегда в обучающей части. Метрики — hit@3, hit@5, NDCG@5 с бинарной релевантностью
функциями `app/ranking/metrics.py`. База открывается только на чтение, выводятся только агрегаты.

Флаг `--extended` после основной оценки добавляет расширенный протокол (`offline_extended.py`): парный бутстреп и перестановочный тест с поправкой Холма — Бонферрони,
нормированные совместные записи и последовательные правила, EASE, обученные веса
правил и минимальный обнаружимый эффект. Вывод без флага не меняется.

Запуск из корня проекта:
  python -X utf8 evaluation/offline_courses.py data/local/catalog.sqlite3
  python -X utf8 evaluation/offline_courses.py data/local/catalog.sqlite3 --extended
"""

from __future__ import annotations

import random
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from math import log2, sqrt
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.catalog.lexicon import parse_task  # noqa: E402
from app.catalog.loader import load_catalog  # noqa: E402
from app.catalog.models import Catalog, HistoryEvent, Material  # noqa: E402
from app.config import Settings  # noqa: E402
from app.ranking import personal  # noqa: E402
from app.ranking.base import Context, HistoryIndex, Profile  # noqa: E402
from app.ranking.metrics import hit_at_k, ndcg_at_k  # noqa: E402

SEED = 20261110
FOLDS = 5
K = 5
STATUS_EVENT = {0: "view", 1: "start", 2: "complete"}
METHODS = ("popularity", "rules", "coenroll")
LABELS = {"popularity": "Популярность", "rules": "Правила по темам", "coenroll": "Совместные записи"}
GROUPS = {"strict": "Строгий порядок, цель — последний курс", "random": "Случайная цель", "all": "Все"}


@dataclass(frozen=True, slots=True)
class Binding:
    course: str  # код материала course:<Id>
    event: str
    paid: bool
    order: int


@dataclass(slots=True)
class Case:
    user: str
    strict: bool
    inputs: tuple[Binding, ...]
    target: str
    fold: int = -1


@dataclass(slots=True)
class Result:
    case: Case
    candidates: int
    ranked: dict[str, list[str]]
    topic_match: bool  # цель делит тему с курсами входа
    continuation: bool  # цель есть в recommended_next последнего курса входа
    rules_had_candidates: bool


@dataclass(slots=True)
class State:
    """Состояние основной оценки для расширенного протокола."""

    catalog: Catalog
    courses: dict[str, Material]  # все курсы каталога
    available: list[str]  # доступные курсы по коду
    by_user: dict[str, list[Binding]]
    cases: list[Case]
    single_users: list[list[Binding]]
    disabled: frozenset[str]
    results: list[Result]
    seed: int


def read_bindings(db: Path) -> tuple[dict[str, list[Binding]], Counter[str]]:
    con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        con.execute("PRAGMA query_only = ON")
        rows = con.execute(
            "SELECT [UserId], [CourseId], [Status], [IsPaid], [EventOrder], [IsDeleted] FROM [CourseUserBindings]"
        ).fetchall()
    finally:
        con.close()
    stats: Counter[str] = Counter()
    by_user: dict[str, list[Binding]] = defaultdict(list)
    for user, course, status, paid, order, deleted in rows:
        stats["rows"] += 1
        if deleted == 1:
            stats["deleted"] += 1
            continue
        if user is None or course is None or str(user).strip() == "" or str(course).strip() == "":
            stats["no_user_or_course"] += 1
            continue
        event = STATUS_EVENT.get(status)
        if event is None:
            stats["unknown_status"] += 1
            continue
        by_user[str(user).strip()].append(
            Binding(f"course:{str(course).strip()}", event, bool(paid), int(order) if order is not None else 0)
        )
    return by_user, stats


def build_cases(by_user: dict[str, list[Binding]], known: set[str]) -> tuple[list[Case], Counter[str]]:
    rng = random.Random(SEED)
    cases: list[Case] = []
    stats: Counter[str] = Counter()
    for user in sorted(by_user):
        bindings = by_user[user]
        stats["bindings_unknown_course"] += sum(1 for b in bindings if b.course not in known)
        if len({b.course for b in bindings}) < 2:
            stats["single"] += 1
            continue
        stats["multi"] += 1
        orders = [b.order for b in bindings]
        strict = len(set(orders)) == len(orders)
        if strict:
            target = max(bindings, key=lambda b: b.order)
            stats["strict"] += 1
        else:
            target = rng.choice(sorted(bindings, key=lambda b: (b.order, b.course)))
        inputs = tuple(sorted((b for b in bindings if b.course != target.course), key=lambda b: (b.order, b.course)))
        cases.append(Case(user=user, strict=strict, inputs=inputs, target=target.course))
    rng_folds = random.Random(SEED + 1)
    order = list(range(len(cases)))
    rng_folds.shuffle(order)
    for position, index in enumerate(order):
        cases[index].fold = position % FOLDS
    return cases, stats


def train_stats(
    fold: int, cases: list[Case], single_users: list[list[Binding]]
) -> tuple[Counter[str], dict[str, Counter[str]], Counter[str]]:
    """Популярность, пары совместных записей и число пользователей курса по обучающей части."""
    popularity: Counter[str] = Counter()
    pairs: dict[str, Counter[str]] = defaultdict(Counter)
    users_with: Counter[str] = Counter()
    for bindings in single_users:
        for b in bindings:
            popularity[b.course] += 1
            users_with[b.course] += 1
    for case in cases:
        if case.fold == fold:
            continue
        courses = sorted({b.course for b in case.inputs} | {case.target})
        for course in courses:
            popularity[course] += 1
            users_with[course] += 1
        for a in courses:
            for b in courses:
                if a != b:
                    pairs[a][b] += 1
    return popularity, pairs, users_with


def rank_popularity(candidates: list[str], popularity: Counter[str]) -> list[str]:
    return sorted(candidates, key=lambda c: (-popularity.get(c, 0), c))


def rank_coenroll(
    candidates: list[str], inputs: tuple[Binding, ...], pairs: dict[str, Counter[str]], users_with: Counter[str],
    popularity: Counter[str],
) -> list[str]:
    score = {
        c: sum(pairs[b.course].get(c, 0) / users_with[b.course] for b in inputs if users_with.get(b.course))
        for c in candidates
    }
    return sorted(candidates, key=lambda c: (-score[c], -popularity.get(c, 0), c))


def rank_rules(
    case: Case, candidates: list[str], materials: dict[str, Material], disabled: frozenset[str],
    popularity: Counter[str],
) -> tuple[list[str], bool]:
    events: list[HistoryEvent] = []
    for b in case.inputs:
        events.append(HistoryEvent(b.course, b.event, b.order))
        if b.paid:
            events.append(HistoryEvent(b.course, "purchase", b.order))
    profile = Profile(history=tuple(events), limit=K)
    topics: list[str] = []
    for b in case.inputs:
        material = materials.get(b.course)
        for topic in material.topics if material else ():
            if topic not in topics:
                topics.append(topic)
    ctx = Context(
        profile=profile, parsed=parse_task(""), topics=tuple(topics), history=HistoryIndex.build(profile.history),
        disabled=disabled, catalog=materials,
    )
    matching = [materials[c] for c in candidates if set(materials[c].topics) & set(topics)]
    ranked = [s.material.id for s in personal.rank(matching, ctx)]
    rest = rank_popularity([c for c in candidates if c not in set(ranked)], popularity)
    return ranked + rest, bool(matching)


def evaluate(db: Path) -> State:
    catalog = load_catalog(Settings(catalog_source="sqlite", catalog_path=db))
    courses = {m.id: m for m in catalog.materials.values() if m.format == "course"}
    available = sorted(m.id for m in courses.values() if m.available)
    by_user, read_stats = read_bindings(db)
    cases, case_stats = build_cases(by_user, set(courses))
    single_users = [b for b in by_user.values() if len({x.course for x in b}) < 2]
    disabled = frozenset(catalog.disabled_features)

    results: list[Result] = []
    skipped: Counter[str] = Counter()
    for fold in range(FOLDS):
        popularity, pairs, users_with = train_stats(fold, cases, single_users)
        top = max(popularity.values()) if popularity else 1
        materials = {
            mid: replace(m, popularity_raw=float(popularity.get(mid, 0)), popularity=popularity.get(mid, 0) / top)
            if m.format == "course" else m
            for mid, m in catalog.materials.items()
        }
        for case in (c for c in cases if c.fold == fold):
            inputs = {b.course for b in case.inputs}
            candidates = [c for c in available if c not in inputs]
            if case.target not in candidates:
                skipped["target_unavailable"] += 1
                continue
            rules, had = rank_rules(case, candidates, materials, disabled, popularity)
            ranked = {
                "popularity": rank_popularity(candidates, popularity),
                "rules": rules,
                "coenroll": rank_coenroll(candidates, case.inputs, pairs, users_with, popularity),
            }
            input_topics = {t for b in case.inputs for t in courses[b.course].topics if b.course in courses}
            last = max(case.inputs, key=lambda b: b.order)
            results.append(
                Result(
                    case=case, candidates=len(candidates), ranked=ranked,
                    topic_match=bool(input_topics & set(courses[case.target].topics)),
                    continuation=case.target in courses[last.course].recommended_next if last.course in courses else False,
                    rules_had_candidates=had,
                )
            )

    print(f"Каталог: {catalog.source}, версия {catalog.version}; курсов {len(courses)}, доступных {len(available)}")
    print(
        f"Записи: строк {read_stats['rows']}, удалённых {read_stats['deleted']}, без пользователя или курса "
        f"{read_stats['no_user_or_course']}, с неизвестным статусом {read_stats['unknown_status']}, "
        f"с курсом вне каталога {case_stats['bindings_unknown_course']}"
    )
    print(
        f"Пользователи: с одним курсом {case_stats['single']}, с двумя и более {case_stats['multi']}, "
        f"из них со строгим порядком {case_stats['strict']}; исключены из метрик, цель недоступна: "
        f"{skipped['target_unavailable']}; оценено {len(results)}"
    )
    mean_candidates = sum(r.candidates for r in results) / len(results) if results else 0
    totals: Counter[str] = Counter(b.course for bindings in by_user.values() for b in bindings)
    on_unavailable = sum(n for course, n in totals.items() if course not in set(available))
    with_enrollments = sum(1 for course in available if totals.get(course))
    top5 = sorted((totals.get(course, 0) for course in available), reverse=True)[:5]
    print(
        f"Записей на недоступные курсы: {on_unavailable} из {sum(totals.values())}; доступных курсов с записями: "
        f"{with_enrollments} из {len(available)}; доля записей на пять самых популярных доступных курсов: "
        f"{fmt(sum(top5) / sum(totals.values()))}"
    )
    print(f"Кандидатов на пользователя в среднем: {fmt(mean_candidates)}; зерно {SEED}, частей {FOLDS}\n")

    grades = lambda target: {target: 2}  # noqa: E731
    for group, label in GROUPS.items():
        subset = [r for r in results if group == "all" or (group == "strict") == r.case.strict]
        if not subset:
            continue
        n = len(subset)
        print(f"### {label}: {n} пользователей\n")
        print("| Метод | hit@1 | hit@3 | hit@5 | NDCG@5 |")
        print("| --- | ---: | ---: | ---: | ---: |")
        for method in METHODS:
            hit1 = sum(hit_at_k(r.ranked[method], grades(r.case.target), 1) for r in subset) / n
            hit3 = sum(hit_at_k(r.ranked[method], grades(r.case.target), 3) for r in subset) / n
            hit5 = sum(hit_at_k(r.ranked[method], grades(r.case.target), 5) for r in subset) / n
            ndcg = sum(ndcg_at_k(r.ranked[method], grades(r.case.target), K) or 0.0 for r in subset) / n
            print(
                f"| {LABELS[method]} | {fmt(hit1)} | {fmt(hit3)} ± {fmt(ci(hit3, n))} | {fmt(hit5)} ± {fmt(ci(hit5, n))} | "
                f"{fmt(ndcg)} |"
            )
        rand1 = sum(1 / r.candidates for r in subset) / n
        rand3 = sum(min(3, r.candidates) / r.candidates for r in subset) / n
        rand5 = sum(min(K, r.candidates) / r.candidates for r in subset) / n
        rand_ndcg = sum(sum(1 / log2(p + 2) for p in range(min(K, r.candidates))) / r.candidates for r in subset) / n
        print(f"| Случайный порядок, ожидание | {fmt(rand1)} | {fmt(rand3)} | {fmt(rand5)} | {fmt(rand_ndcg)} |")
        print()
        topic = sum(1 for r in subset if r.topic_match)
        cont = sum(1 for r in subset if r.continuation)
        had = sum(1 for r in subset if r.rules_had_candidates)
        targets = Counter(r.case.target for r in subset)
        print(
            f"Цель делит тему с курсами входа у {topic} из {n}; цель в `recommended_next` последнего курса входа "
            f"у {cont}; у правил были кандидаты темы у {had}. Разных целей {len(targets)}, самая частая цель — "
            f"у {fmt(targets.most_common(1)[0][1] / n)} пользователей, две самые частые — "
            f"у {fmt(sum(c for _, c in targets.most_common(2)) / n)}.\n"
        )
        print("| Метод | Цель на позиции 1 | 2 | 3 | 4 | 5 | ниже 5 |")
        print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
        for method in METHODS:
            positions = Counter()
            for r in subset:
                index = r.ranked[method].index(r.case.target)
                positions[min(index, K)] += 1
            cells = " | ".join(fmt(positions[p] / n) for p in range(K + 1))
            print(f"| {LABELS[method]} | {cells} |")
        print()
        print("| Пара методов | hit@5 только у первого | только у второго | у обоих | ни у кого |")
        print("| --- | ---: | ---: | ---: | ---: |")
        for a, b in (("rules", "popularity"), ("coenroll", "popularity"), ("coenroll", "rules")):
            counts = Counter()
            for r in subset:
                ha = hit_at_k(r.ranked[a], grades(r.case.target), 5)
                hb = hit_at_k(r.ranked[b], grades(r.case.target), 5)
                counts["a" if ha and not hb else "b" if hb and not ha else "both" if ha else "none"] += 1
            print(f"| {LABELS[a]} и {LABELS[b]} | {counts['a']} | {counts['b']} | {counts['both']} | {counts['none']} |")
        print()
        if group == "all":
            print("| Подмножество | Пользователей | hit@5 популярность | hit@5 правила | hit@5 совместные |")
            print("| --- | ---: | ---: | ---: | ---: |")
            for title, part in (
                ("Цель делит тему с входом", [r for r in subset if r.topic_match]),
                ("Цель другой темы", [r for r in subset if not r.topic_match]),
                ("Один курс на входе", [r for r in subset if len(r.case.inputs) == 1]),
                ("Два и более курсов на входе", [r for r in subset if len(r.case.inputs) >= 2]),
            ):
                if not part:
                    continue
                cells = [
                    fmt(sum(hit_at_k(r.ranked[m], grades(r.case.target), 5) for r in part) / len(part))
                    for m in METHODS
                ]
                print(f"| {title} | {len(part)} | {cells[0]} | {cells[1]} | {cells[2]} |")
            print()
    return State(
        catalog=catalog, courses=courses, available=available, by_user=by_user, cases=cases,
        single_users=single_users, disabled=disabled, results=results, seed=SEED,
    )


def ci(p: float, n: int) -> float:
    """Половина 95 % доверительного интервала доли по нормальному приближению."""
    return 1.96 * sqrt(max(p * (1 - p), 0.0) / n) if n else 0.0


def fmt(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a for a in argv[1:] if a.startswith("--")}
    if len(args) != 1 or flags - {"--extended"}:
        print(__doc__)
        return 2
    state = evaluate(Path(args[0]))
    if "--extended" in flags:
        import offline_extended  # noqa: PLC0415 — нужен только с флагом

        offline_extended.run(state)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
