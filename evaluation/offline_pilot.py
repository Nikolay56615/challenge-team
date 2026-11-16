"""Офлайн-сравнение пилота «похожие курсы» на разбиениях O1 и проверка продукта на копии.

Сравнение с популярностью и текущими правилами на тех же
разбиениях O1, отдельно для целей внутри темы и вне её.

Протокол. Случаи, части, цели, кандидаты и три метода O1 берутся из `offline_courses.evaluate` без
изменений: те же 803 пользователя, зёрна 20261110 и 20261111, кандидаты — доступные курсы без курсов
входа. Пилот — подбор по истории самого приложения: `policy.recommend` в персональном методе при пустой
задаче и истории из курсов входа. Для каждой части пары совместных записей считаются только по её
обучающей части (`offline_courses.train_stats`), собираются в файл пар функцией `build_pairs.payload` и
разбираются `parse_pairs` из `app/catalog/pairs.py`, то есть тем же кодом, что читает
`CATALOG_PAIRS_PATH`. Каталог пилота — курсы копии с популярностью обучающей части, как в O1; курсы
входа помечены недоступными, поэтому кандидаты те же, что у методов O1, а курсы входа остаются
якорями пар и источником тем истории. Список пилота дополняется остальными кандидатами по популярности
обучающей части, как правила по темам в O1.

Порог поддержки PAIRS_MIN_SUPPORT = 10 зафиксирован до прогона, как значение по умолчанию в продукте.
Пороги 5 и 20 — анализ чувствительности: они ничего не выбирают. Статистика — как в R01: парный
бутстреп 5 000 выборок, зерно 20261112, перестановочный тест со сменой знака 10 000 перестановок,
зерно 20261113, поправка Холма — Бонферрони на семейство из 18 проверок: пилот против популярности,
правил по темам и совместных записей, по hit@5 и NDCG@5, на всех пользователях, при цели той же темы
и при цели другой темы.

Пятёрка на экране (добавлена после ревью, в семейство проверок не входит): тот же подбор по истории
на полном каталоге копии, где статьи и документы тем истории делят пятёрку с курсами. Популярность
курсов — по обучающей части, нормирована по формату, как в источнике `sqlite`; курсы входа недоступны,
как в O1; limit 5 без добора. Для сравнения — тот же запрос без файла пар (стартовая подборка) и
разбор с весом темы истории 0.

Проверка продукта (второй и третий аргументы): каталог копии с базой признаков загружается с файлом
пар и без него. P01–P10 при limit 5 и 10 в обоих методах должны совпасть. Для каждого доступного курса
и каждого недоступного курса с записями — запрос с пустой задачей и одним пройденным курсом в истории:
доля ответов с фразой о похожих курсах и с курсом другой темы в пятёрке, распределение числа пар
от порога на курс, число пользователей журнала, у которых подбор по истории не включается (стартовая
подборка) или идёт только по темам истории.

Вложенный выбор веса темы истории (флаг `--nested`, предрегистрация 2026-11-12 в
evaluation/track1-offline-courses.md): сетка NESTED_GRID, вес 0 — только справочная строка. Для каждой
внешней части O1 вес выбирается на четырёх внутренних частях её обучающей части, как R03 в
`offline_extended.py`: пары и популярность — по внутренней обучающей части, порог MIN_SUPPORT, критерий —
средняя NDCG@5 всех валидационных пользователей, при равенстве больший вес. На внешних проверочных частях
вложенный выбор сравнивается с пилотом при весе 1,0, совместными записями и популярностью; семейство из
18 проверок с поправкой Холма. Вес подменяется только в процессе оценки, код приложения не меняется.
Без флага вывод прежний.

Код приложения по умолчанию берётся из `app/backend`; переменная окружения OFFLINE_BACKEND задаёт другой
каталог бэкенда, например снимок `.work/waveA/app/backend`. Если она задана, скрипт пишет об этом в поток
ошибок; основной вывод от этого не меняется.

Выводятся только агрегаты: без кодов, названий и идентификаторов.

Запуск из корня проекта:
  python -X utf8 evaluation/offline_pilot.py data/local/catalog.sqlite3
С проверкой продукта после пути каталога передаются база признаков и файл пар:
  python -X utf8 evaluation/offline_pilot.py data/local/catalog.sqlite3 <база признаков> <файл пар>
например data/local/catalog-signals.sqlite3 и data/local/course-pairs.json. Флаг `--nested` добавляет
вложенный выбор веса после офлайн-сравнения.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
BACKEND = Path(os.environ.get("OFFLINE_BACKEND") or PROJECT / "backend").resolve()
sys.path.insert(0, str(BACKEND))
# Пакет приложения фиксируется до offline_courses и build_pairs: они добавляют в путь app/backend, а
# подмодули уже импортированного пакета ищутся в его каталоге
import app  # noqa: E402

if not Path(app.__file__).resolve().is_relative_to(BACKEND):
    raise SystemExit(f"пакет app импортирован не из {BACKEND}: {app.__file__}")

import offline_courses as o1  # noqa: E402
import offline_stats as stats  # noqa: E402
from app.catalog.coverage import normalize_popularity  # noqa: E402
from app.catalog.lexicon import parse_task  # noqa: E402
from app.catalog.loader import load_catalog  # noqa: E402
from app.catalog.models import Catalog, CoursePairs, HistoryEvent, Material  # noqa: E402
from app.catalog.pairs import parse_pairs  # noqa: E402
from app.config import Settings  # noqa: E402
from app.profiles.synthetic import load_profiles  # noqa: E402
from app.ranking import personal, policy  # noqa: E402
from app.ranking.base import Context, HistoryIndex, HistorySignals, Profile  # noqa: E402
from app.ranking.metrics import hit_at_k, ndcg_at_k  # noqa: E402
from build_pairs import Pair, payload  # noqa: E402
from offline_extended import pvalue, signed, thousands  # noqa: E402

if not Path(personal.__file__).resolve().is_relative_to(BACKEND):
    raise SystemExit(f"код приложения импортирован не из {BACKEND}: {personal.__file__}")

K = 5
MIN_SUPPORT = 10  # зафиксирован до прогона: значение по умолчанию PAIRS_MIN_SUPPORT
SENSITIVITY = (5, 20)
RESAMPLES = 5000
PERMUTATIONS = 10000
METHODS = ("popularity", "rules", "coenroll", "pilot")
LABELS = {**o1.LABELS, "pilot": "Пилот"}
POPULATIONS = {"all": "Все", "same": "Цель делит тему с входом", "other": "Цель другой темы"}
COMPARISONS = (("pilot", "popularity"), ("pilot", "rules"), ("pilot", "coenroll"))
PHRASE_MARK = "Этот курс выбрал"  # начало фразы explain.co_enrollment_phrase
PROFILES = tuple(f"P{n:02d}" for n in range(1, 11))

# Вложенный выбор веса темы истории: значения зафиксированы до прогона (предрегистрация 2026-11-12)
NESTED_FEATURE = "history_topic"
NESTED_GRID = (0.1, 0.25, 0.5, 1.0)  # все положительны: фраза «Тема из вашей истории» верна вкладу
NESTED_REFERENCE = 0.0  # справочная строка, не выбирается
NESTED_BASE = 1.0  # вес продукта, заданный до прогона пилота
NESTED_MAX_SAME_TOPIC_DROP = 0.05
NESTED_LABELS = {
    "popularity": o1.LABELS["popularity"],
    "coenroll": o1.LABELS["coenroll"],
    "pilot": "Пилот, вес 1,0",
    "nested": "Пилот, вложенный выбор",
    "reference": "Справочно: пилот, вес 0",
}
NESTED_COMPARISONS = (("nested", "pilot"), ("nested", "coenroll"), ("nested", "popularity"))


@dataclass(slots=True)
class PilotRun:
    """Выдача пилота при одном пороге и её свойства по пользователям."""

    ranked: dict[str, list[str]] = field(default_factory=dict)  # пользователь → порядок кандидатов
    own: dict[str, int] = field(default_factory=dict)  # длина списка самого пилота
    target_in_own: dict[str, bool] = field(default_factory=dict)
    shown_hit: dict[str, bool] = field(default_factory=dict)  # цель в пятёрке без добора
    statuses: Counter[str] = field(default_factory=Counter)
    other_in_top: Counter[str] = field(default_factory=Counter)  # пользователей с k курсами другой темы в пятёрке
    co_in_top: list[int] = field(default_factory=list)
    history_topic_candidates: dict[str, int] = field(default_factory=dict)  # кандидатов тем курсов входа
    pairs_loaded: list[int] = field(default_factory=list)
    courses_with_pairs: list[int] = field(default_factory=list)
    small_anchors: list[int] = field(default_factory=list)  # курсов с парами и меньше чем с 10 слушателями


@dataclass(slots=True)
class ScreenRun:
    """Пятёрка продукта на полном каталоге копии: курсы вместе со статьями и документами тем истории."""

    ranked: dict[str, list[str]] = field(default_factory=dict)  # пользователь → коды пятёрки
    statuses: Counter[str] = field(default_factory=Counter)
    courses: list[int] = field(default_factory=list)  # курсов в пятёрке
    other_courses: Counter[int] = field(default_factory=Counter)  # пользователей с k курсами другой темы
    formats: Counter[str] = field(default_factory=Counter)


def fmt(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",").replace("-", "−")


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def events_of(bindings: Sequence[o1.Binding]) -> tuple[HistoryEvent, ...]:
    """События истории из записей на курсы для правил подбора по темам."""
    events: list[HistoryEvent] = []
    for b in bindings:
        events.append(HistoryEvent(b.course, b.event, b.order))
        if b.paid:
            events.append(HistoryEvent(b.course, "purchase", b.order))
    return tuple(events)


def history(case: o1.Case) -> tuple[HistoryEvent, ...]:
    """История запроса из курсов входа."""
    return events_of(case.inputs)


def fold_pairs(
    together: dict[str, Counter[str]], users_with: Counter[str], materials: dict[str, Material], support: int
) -> tuple[CoursePairs, dict]:
    """Пары обучающей части в формате файла пар, разобранные кодом приложения."""
    counts: dict[Pair, int] = {(a, b): n for a, row in together.items() for b, n in row.items() if a < b}
    return parse_pairs(payload(counts, users_with, "обучающая часть", ""), materials, support)


@dataclass(slots=True)
class Fold:
    """Обучающая часть одной внешней части O1 и её проверочные пользователи."""

    popularity: Counter[str]
    together: dict[str, Counter[str]]
    users_with: Counter[str]
    courses: dict[str, Material]  # курсы каталога с популярностью обучающей части, как в O1
    results: list[o1.Result]
    # Полный каталог копии для пятёрки на экране: популярность курсов — по обучающей части, нормирована
    # по формату, как в источнике sqlite; у статей и документов она из каталога (ссылки, не записи)
    screen: dict[str, Material] = field(default_factory=dict)


def courses_with(state: o1.State, popularity: Counter[str]) -> dict[str, Material]:
    """Курсы каталога с популярностью обучающей части, нормированной делением на максимум, как в O1."""
    top = max(popularity.values())
    return {
        mid: replace(m, popularity_raw=float(popularity.get(mid, 0)), popularity=popularity.get(mid, 0) / top)
        for mid, m in state.courses.items()
    }


def folds(state: o1.State) -> list[Fold]:
    by_fold: dict[int, list[o1.Result]] = {}
    for r in state.results:
        by_fold.setdefault(r.case.fold, []).append(r)
    prepared = []
    for fold in sorted(by_fold):
        popularity, together, users_with = o1.train_stats(fold, state.cases, state.single_users)
        courses = courses_with(state, popularity)
        raw = {mid: float(popularity.get(mid, 0)) for mid in state.courses}
        ranks = normalize_popularity(raw, dict.fromkeys(state.courses, "course"), "per_format")
        screen = {
            mid: replace(m, popularity_raw=raw[mid], popularity=ranks[mid]) if mid in state.courses else m
            for mid, m in state.catalog.materials.items()
        }
        prepared.append(Fold(popularity, together, users_with, courses, by_fold[fold], screen))
    return prepared


def pilot_disabled(state: o1.State) -> tuple[str, ...]:
    """Отключённые признаки каталога с подключёнными парами, как после `loader.attach_pairs`."""
    return tuple(f for f in state.catalog.disabled_features if f != "co_enrollment")


@dataclass(slots=True)
class PilotOrder:
    """Порядок кандидатов O1 у пилота для одного случая."""

    outcome: policy.Outcome
    candidates: list[str]  # доступные курсы без курсов входа
    own: list[str]  # список самого пилота среди кандидатов
    ranked: list[str]  # список пилота, затем остальные кандидаты по популярности обучающей части


def pilot_order(
    state: o1.State, courses: dict[str, Material], pairs: CoursePairs, popularity: Counter[str], case: o1.Case
) -> PilotOrder:
    """`policy.recommend` при пустой задаче и истории из курсов входа; курсы входа недоступны, как в O1."""
    inputs = {b.course for b in case.inputs}
    candidates = [c for c in state.available if c not in inputs]
    materials = {mid: replace(m, available=False) if mid in inputs else m for mid, m in courses.items()}
    catalog = Catalog(
        materials=materials, source=state.catalog.source, version=state.catalog.version,
        disabled_features=pilot_disabled(state), course_pairs=pairs,
    )
    outcome = policy.recommend(catalog, Profile(history=history(case), limit=len(materials)), "personal")
    allowed = set(candidates)
    own = [i.material.id for i in outcome.items if i.material.id in allowed]
    rest = o1.rank_popularity([c for c in candidates if c not in set(own)], popularity)
    return PilotOrder(outcome, candidates, own, own + rest)


def run_pilot(state: o1.State, prepared: list[Fold], support: int) -> PilotRun:
    run = PilotRun()
    for part in prepared:
        courses, popularity = part.courses, part.popularity
        pairs, summary = fold_pairs(part.together, part.users_with, courses, support)
        run.pairs_loaded.append(summary["pairs"])
        run.courses_with_pairs.append(summary["courses"])
        small = personal.CO_ENROLLMENT_MIN_ANCHOR_USERS
        run.small_anchors.append(sum(1 for c, n in pairs.totals.items() if n < small and pairs.neighbours(c)))
        for r in part.results:
            user = r.case.user
            inputs = {b.course for b in r.case.inputs}
            order = pilot_order(state, courses, pairs, popularity, r.case)
            outcome, candidates, own = order.outcome, order.candidates, order.own
            allowed = set(candidates)
            run.ranked[user] = order.ranked
            run.own[user] = len(own)
            run.target_in_own[user] = r.case.target in own
            run.shown_hit[user] = r.case.target in own[:K]
            run.statuses[outcome.status] += 1
            topics = {t for c in inputs for t in courses[c].topics}
            run.history_topic_candidates[user] = sum(1 for c in candidates if topics & set(courses[c].topics))
            shown = [i for i in outcome.items if i.material.id in allowed][:K]
            run.other_in_top[str(sum(1 for i in shown if not topics & set(i.material.topics)))] += 1
            run.co_in_top.append(sum(1 for i in shown if i.contributions.get("co_enrollment", 0) > 0))
    return run


def run_share(state: o1.State, prepared: list[Fold], support: int) -> PilotRun:
    """Только доля «похожих курсов» пилота, `personal.co_enrollment`, на всех кандидатах O1, без темы истории.

    Порог поддержки, курс истории от 10 слушателей и потолок 1 — как в продукте; равенства решает
    популярность обучающей части. Для разбора разницы пилота и совместных записей O1.
    """
    run = PilotRun()
    disabled = frozenset(pilot_disabled(state))
    for part in prepared:
        pairs, _ = fold_pairs(part.together, part.users_with, part.courses, support)
        for r in part.results:
            events = history(r.case)
            index = HistoryIndex.build(events)
            ctx = Context(
                profile=Profile(history=events, limit=K), parsed=parse_task(""), topics=(), history=index,
                disabled=disabled, catalog=part.courses, pairs=pairs,
                anchors=HistorySignals.build(events, part.courses).anchors,
            )
            inputs = {b.course for b in r.case.inputs}
            candidates = [c for c in state.available if c not in inputs]
            share = {c: personal.co_enrollment(part.courses[c], ctx)[0] for c in candidates}
            run.ranked[r.case.user] = sorted(candidates, key=lambda c: (-share[c], -part.popularity.get(c, 0), c))
    return run


def run_screen(state: o1.State, prepared: list[Fold], with_pairs: bool) -> ScreenRun:
    """Пятёрка `policy.recommend` на полном каталоге копии при пустой задаче, limit 5, без добора.

    С парами обучающей части при пороге MIN_SUPPORT — подбор по истории пилота; без пар — стартовая
    подборка, как в продукте без файла пар. Курсы входа недоступны, как в O1.
    """
    run = ScreenRun()
    disabled = pilot_disabled(state) if with_pairs else state.catalog.disabled_features
    for part in prepared:
        pairs = fold_pairs(part.together, part.users_with, part.screen, MIN_SUPPORT)[0] if with_pairs else None
        for r in part.results:
            inputs = {b.course for b in r.case.inputs}
            materials = {mid: replace(m, available=False) if mid in inputs else m for mid, m in part.screen.items()}
            catalog = Catalog(
                materials=materials, source=state.catalog.source, version=state.catalog.version,
                disabled_features=disabled, course_pairs=pairs,
            )
            outcome = policy.recommend(catalog, Profile(history=history(r.case), limit=K), "personal")
            shown = [i.material for i in outcome.items]
            topics = {t for c in inputs for t in state.courses[c].topics}
            run.ranked[r.case.user] = [m.id for m in shown]
            run.statuses[outcome.status] += 1
            run.courses.append(sum(1 for m in shown if m.format == "course"))
            run.other_courses[sum(1 for m in shown if m.format == "course" and not topics & set(m.topics))] += 1
            run.formats.update(m.format for m in shown)
    return run


def screen_ranking(run: ScreenRun) -> Callable[[o1.Result], list[str]]:
    return lambda r: run.ranked[r.case.user]


@contextlib.contextmanager
def patched_weight(feature: str, value: float) -> Iterator[None]:
    """Временный вес признака приложения для разбора; после блока вес восстанавливается."""
    original = personal.WEIGHTS[feature]
    personal.WEIGHTS[feature] = value
    try:
        yield
    finally:
        personal.WEIGHTS[feature] = original


def population(results: list[o1.Result], name: str) -> list[o1.Result]:
    if name == "all":
        return results
    return [r for r in results if r.topic_match == (name == "same")]


def series(subset: list[o1.Result], ranking: Callable[[o1.Result], list[str]], k: int) -> list[float]:
    return [1.0 if hit_at_k(ranking(r), {r.case.target: 2}, k) else 0.0 for r in subset]


def ndcg_series(subset: list[o1.Result], ranking: Callable[[o1.Result], list[str]]) -> list[float]:
    return [ndcg_at_k(ranking(r), {r.case.target: 2}, K) or 0.0 for r in subset]


def ranking_of(run: PilotRun, method: str) -> Callable[[o1.Result], list[str]]:
    if method == "pilot":
        return lambda r: run.ranked[r.case.user]
    return lambda r: r.ranked[method]


def test_key(a: str, b: str, group: str, metric: int) -> str:
    """Ключ проверки в семействе: методы, группа пользователей и метрика (0 — hit@5, 1 — NDCG@5)."""
    return f"{a}|{b}|{group}|{metric}"


def metric_table(results: list[o1.Result], rows: list[tuple[str, Callable[[o1.Result], list[str]]]]) -> None:
    """Строки hit@5 и NDCG@5 по всем пользователям, при цели той же темы и другой темы."""
    for label, ranking in rows:
        cells = []
        for name in POPULATIONS:
            subset = population(results, name)
            cells += [fmt(mean(series(subset, ranking, K))), fmt(mean(ndcg_series(subset, ranking)))]
        print(f"| {label} | {' | '.join(cells)} |")
    print()


def offline(state: o1.State) -> tuple[list[Fold], PilotRun]:
    """Офлайн-сравнение; возвращает части и выдачу пилота при пороге MIN_SUPPORT для `--nested`."""
    results = state.results
    prepared = folds(state)
    runs = {support: run_pilot(state, prepared, support) for support in (MIN_SUPPORT, *SENSITIVITY)}
    main = runs[MIN_SUPPORT]
    share_only = run_share(state, prepared, MIN_SUPPORT)
    with patched_weight("history_topic", 0.0):
        without_topic = run_pilot(state, prepared, MIN_SUPPORT)
    titles = Counter(" ".join(state.courses[c].title.casefold().split()) for c in state.available)

    print("## Пилот «похожие курсы» на разбиениях O1\n")
    print(
        f"Каталог: {state.catalog.source}, версия {state.catalog.version}; курсов {len(state.courses)}, доступных "
        f"{len(state.available)}, повторов названия среди доступных {sum(n - 1 for n in titles.values())}. "
        f"Оценено пользователей: {len(results)}, со строгим порядком {sum(r.case.strict for r in results)}, "
        f"цель делит тему с входом у {sum(r.topic_match for r in results)}, цель другой темы у "
        f"{sum(not r.topic_match for r in results)}. Зёрна: цель {state.seed}, части {state.seed + 1}, бутстреп "
        f"{state.seed + 2}, перестановки {state.seed + 3}. Порог поддержки {MIN_SUPPORT} зафиксирован до прогона, "
        f"{' и '.join(map(str, SENSITIVITY))} — чувствительность.\n"
    )
    for support, run in runs.items():
        print(
            f"Пары обучающих частей при пороге {support}: загружено от {min(run.pairs_loaded)} до "
            f"{max(run.pairs_loaded)}, в среднем {fmt(mean(run.pairs_loaded), 1)}; курсов с парами от "
            f"{min(run.courses_with_pairs)} до {max(run.courses_with_pairs)}; из них меньше чем с "
            f"{personal.CO_ENROLLMENT_MIN_ANCHOR_USERS} слушателями — {sum(run.small_anchors)}."
        )
    listeners = min(min(part.users_with.values()) for part in prepared)
    print(f"Слушателей у курса с записями в обучающей части: не меньше {listeners}.")
    print()

    for name, label in POPULATIONS.items():
        subset = population(results, name)
        print(f"### {label}, пользователей: {len(subset)}\n")
        print("| Метод | hit@1 | hit@3 | hit@5 | NDCG@5 |")
        print("| --- | ---: | ---: | ---: | ---: |")
        for method in METHODS:
            ranking = ranking_of(main, method)
            cells = [fmt(mean(series(subset, ranking, k))) for k in (1, 3, 5)]
            cells.append(fmt(mean(ndcg_series(subset, ranking))))
            print(f"| {LABELS[method]} | {' | '.join(cells)} |")
        shown = mean([1.0 if main.shown_hit[r.case.user] else 0.0 for r in subset])
        print(f"| Пилот без добора по популярности, только курсы | — | — | {fmt(shown)} | — |")
        print()

    tests = []
    for name in POPULATIONS:
        subset = population(results, name)
        values_of = {(m, 0): series(subset, ranking_of(main, m), K) for m in METHODS}
        values_of |= {(m, 1): ndcg_series(subset, ranking_of(main, m)) for m in METHODS}
        diffs: dict[str, list[float]] = {}
        for a, b in COMPARISONS:
            for metric in (0, 1):
                pairs = zip(values_of[(a, metric)], values_of[(b, metric)], strict=True)
                diffs[test_key(a, b, name, metric)] = [x - y for x, y in pairs]
        intervals = stats.paired_bootstrap(diffs, RESAMPLES, state.seed + 2)
        for key, values in diffs.items():
            p = stats.sign_flip_pvalue(values, PERMUTATIONS, state.seed + 3)
            tests.append((key, len(subset), mean(values), intervals[key], p))
    adjusted = stats.holm([t[4] for t in tests])
    by_key = {t[0]: (t, adj) for t, adj in zip(tests, adjusted, strict=True)}
    print(
        f"### Парные сравнения\n\nИнтервал — 95 % перцентильный парного бутстрепа, {thousands(RESAMPLES)} выборок; "
        f"p — перестановочный тест со сменой знака, {thousands(PERMUTATIONS)} перестановок; поправка Холма — "
        f"Бонферрони на {len(tests)} проверок.\n"
    )
    print("| Сравнение | Группа | Пользователей | Δ hit@5 [95 % ДИ] | p | p Холма | Δ NDCG@5 [95 % ДИ] | p | p Холма |")
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for name, label in POPULATIONS.items():
        for a, b in COMPARISONS:
            cells, n = [], 0
            for metric in (0, 1):
                (_, n, value, (low, high), p), adj = by_key[test_key(a, b, name, metric)]
                cells += [f"{signed(value)} [{signed(low)}; {signed(high)}]", pvalue(p), pvalue(adj)]
            print(f"| {LABELS[a]} − {LABELS[b]} | {label} | {n} | {' | '.join(cells)} |")
    print()

    print("### Чувствительность к порогу поддержки\n")
    print("| Метод | Все, hit@5 | NDCG@5 | Та же тема, hit@5 | NDCG@5 | Другая тема, hit@5 | NDCG@5 |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    rows = [("Совместные записи, без порога", ranking_of(main, "coenroll"))]
    rows += [(f"Пилот, порог {s}", ranking_of(runs[s], "pilot")) for s in sorted(runs)]
    metric_table(results, rows)

    print("### Разбор разницы с совместными записями, после прогона\n")
    print("Ничего не выбирает: шаги от метода O1 к пилоту при пороге 10 на тех же проверочных частях.\n")
    print("| Метод | Все, hit@5 | NDCG@5 | Та же тема, hit@5 | NDCG@5 | Другая тема, hit@5 | NDCG@5 |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    metric_table(
        results,
        [
            ("Совместные записи O1: Σ c_ij / c_i, все кандидаты", ranking_of(main, "coenroll")),
            (
                "Доля пилота `personal.co_enrollment`: порог 10 и потолок 1; все кандидаты",
                ranking_of(share_only, "pilot"),
            ),
            ("Пилот без темы истории: кандидаты пилота, вес темы истории 0", ranking_of(without_topic, "pilot")),
            ("Пилот", ranking_of(main, "pilot")),
        ],
    )

    print("### Группы O1\n")
    strict = [r for r in results if r.case.strict]
    random_target = [r for r in results if not r.case.strict]
    print(
        f"Строгий порядок: пользователей {len(strict)}, цель той же темы у {sum(r.topic_match for r in strict)}. "
        f"Случайная цель: пользователей {len(random_target)}, цель той же темы у "
        f"{sum(r.topic_match for r in random_target)}.\n"
    )
    print("| Метод | Строгий порядок, hit@5 | NDCG@5 | Случайная цель, hit@5 | NDCG@5 |")
    print("| --- | ---: | ---: | ---: | ---: |")
    for method in METHODS:
        ranking = ranking_of(main, method)
        cells = []
        for subset in (strict, random_target):
            cells += [fmt(mean(series(subset, ranking, K))), fmt(mean(ndcg_series(subset, ranking)))]
        print(f"| {LABELS[method]} | {' | '.join(cells)} |")
    print()

    print(f"### Свойства выдачи пилота при пороге {MIN_SUPPORT}\n")
    n = len(results)
    statuses = ", ".join(f"{status} {count}" for status, count in sorted(main.statuses.items()))
    own = [main.own[r.case.user] for r in results]
    print(f"- Статус ответа: {statuses} из {n}.")
    print(
        f"- Длина списка пилота: в среднем {fmt(mean(own), 1)}, от {min(own)} до {max(own)}; меньше пяти — у "
        f"{sum(1 for x in own if x < K)} пользователей, тогда пятёрку добирает популярность."
    )
    for name in ("same", "other"):
        subset = population(results, name)
        inside = sum(1 for r in subset if main.target_in_own[r.case.user])
        same_topic = mean([main.history_topic_candidates[r.case.user] for r in subset])
        print(
            f"- {POPULATIONS[name]}: цель среди кандидатов пилота у {inside} из {len(subset)}; кандидатов тем курсов "
            f"входа в среднем {fmt(same_topic, 1)}."
        )
    other = ", ".join(f"{k} — {main.other_in_top[k]}" for k in sorted(main.other_in_top, key=int))
    print(f"- Курсов другой темы в первой пятёрке списка курсов пилота, пользователей: {other}.")
    print(
        f"- Карточек с вкладом похожих курсов в пятёрке: в среднем {fmt(mean(main.co_in_top), 2)}; хотя бы одна — у "
        f"{sum(1 for x in main.co_in_top if x)} из {n}.\n"
    )

    screens = {"pilot": run_screen(state, prepared, True), "cold": run_screen(state, prepared, False)}
    with patched_weight("history_topic", 0.0):
        screens["without_topic"] = run_screen(state, prepared, True)
    screen_labels = {
        "pilot": f"Пилот, порог {MIN_SUPPORT}",
        "cold": "Без файла пар: стартовая подборка",
        "without_topic": "Разбор после прогона: пилот с весом темы истории 0",
    }
    print("### Пятёрка на экране: полный каталог копии\n")
    print(
        f"Добавлено после ревью; описательные средние, в семейство проверок не входят и ничего не выбирают. Каталог — "
        f"все {thousands(state.catalog.size)} материалов копии, курсы входа недоступны, популярность курсов — по "
        f"обучающей части; "
        f"limit {K}, без добора.\n"
    )
    print("| Вариант | Все, hit@5 | NDCG@5 | Та же тема, hit@5 | NDCG@5 | Другая тема, hit@5 | NDCG@5 |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    metric_table(results, [(screen_labels[name], screen_ranking(view)) for name, view in screens.items()])
    print(
        "| Вариант | Статус ответа | Карточек по форматам | Курсов в пятёрке, среднее | "
        "Курсов другой темы в пятёрке, пользователей |"
    )
    print("| --- | --- | --- | ---: | --- |")
    for name, view in screens.items():
        statuses = ", ".join(f"{status} {count}" for status, count in sorted(view.statuses.items()))
        by_count = sorted(view.formats.items(), key=lambda kv: (-kv[1], kv[0]))
        cards = ", ".join(f"{kind} {count}" for kind, count in by_count)
        other = ", ".join(f"{k} — {view.other_courses[k]}" for k in sorted(view.other_courses))
        print(f"| {screen_labels[name]} | {statuses} | {cards} | {fmt(mean(view.courses), 1)} | {other} |")
    print()
    return prepared, main


def weight_label(value: float) -> str:
    return "0" if value == 0 else fmt(value, 1) if round(value, 1) == value else fmt(value, 2)


def same_topic(state: o1.State, case: o1.Case) -> bool:
    """Цель делит тему с курсами входа, как `topic_match` в O1."""
    topics = {t for b in case.inputs if b.course in state.courses for t in state.courses[b.course].topics}
    return bool(topics & set(state.courses[case.target].topics))


@dataclass(slots=True)
class InnerPart:
    """Внутренняя часть: курсы и пары её обучающей части и её валидационные случаи с группой по теме."""

    courses: dict[str, Material]
    popularity: Counter[str]
    pairs: CoursePairs
    validation: list[tuple[o1.Case, bool]]


@dataclass(slots=True)
class Selection:
    """Вложенный выбор для одной внешней части: метрики валидации по весам и выбранный вес."""

    outer: int
    scores: dict[float, list[tuple[float, float, bool]]]  # вес → (hit@5, NDCG@5, та же тема) по случаям
    chosen: float

    def mean(self, weight: float, metric: int, group: str = "all") -> float:
        rows = [s for s in self.scores[weight] if group == "all" or s[2] == (group == "same")]
        return mean([s[metric] for s in rows])


def inner_parts(state: o1.State, outer: int) -> list[InnerPart]:
    """Четыре внутренние части обучающей части внешней части `outer`, как R03 в `offline_extended.run`.

    Каждая внутренняя часть по очереди валидационная; популярность и пары — по трём остальным вместе
    с пользователями одного курса, порог MIN_SUPPORT. Валидационные случаи — с доступной целью.
    """
    train = [c for c in state.cases if c.fold != outer]
    available = set(state.available)
    parts = []
    for inner in sorted({c.fold for c in train}):
        popularity, together, users_with = o1.train_stats(inner, train, state.single_users)
        courses = courses_with(state, popularity)
        pairs, _ = fold_pairs(together, users_with, courses, MIN_SUPPORT)
        validation = [(c, same_topic(state, c)) for c in train if c.fold == inner and c.target in available]
        parts.append(InnerPart(courses, popularity, pairs, validation))
    return parts


def validate(state: o1.State, parts: list[InnerPart], weight: float) -> list[tuple[float, float, bool]]:
    """hit@5, NDCG@5 и группа каждого валидационного случая при весе темы истории `weight`."""
    rows = []
    with patched_weight(NESTED_FEATURE, weight):
        for part in parts:
            for case, same in part.validation:
                ranked = pilot_order(state, part.courses, part.pairs, part.popularity, case).ranked
                grades = {case.target: 2}
                rows.append((1.0 if hit_at_k(ranked, grades, K) else 0.0, ndcg_at_k(ranked, grades, K) or 0.0, same))
    return rows


def run_weights(state: o1.State, prepared: list[Fold], weights: Sequence[float]) -> dict[str, list[str]]:
    """Порядок пилота на внешних проверочных частях при пороге MIN_SUPPORT; у каждой части свой вес."""
    ranked: dict[str, list[str]] = {}
    for part, weight in zip(prepared, weights, strict=True):
        pairs, _ = fold_pairs(part.together, part.users_with, part.courses, MIN_SUPPORT)
        with patched_weight(NESTED_FEATURE, weight):
            for r in part.results:
                ranked[r.case.user] = pilot_order(state, part.courses, pairs, part.popularity, r.case).ranked
    return ranked


def metric_values(subset: list[o1.Result], ranking: Callable[[o1.Result], list[str]], metric: int) -> list[float]:
    return series(subset, ranking, K) if metric == 0 else ndcg_series(subset, ranking)


def nested(state: o1.State, prepared: list[Fold], main: PilotRun) -> None:
    """Вложенный выбор веса темы истории по предрегистрации 2026-11-12 (evaluation/track1-offline-courses.md)."""
    results = state.results
    outer_folds = sorted({r.case.fold for r in results})
    if [part.results[0].case.fold for part in prepared] != outer_folds:
        raise SystemExit("порядок частей не совпадает с внешними частями O1")
    mismatch = sum(1 for r in results if same_topic(state, r.case) != r.topic_match)
    if mismatch:
        raise SystemExit(f"группа по теме расходится с O1 у {mismatch} пользователей")
    weights = (NESTED_REFERENCE, *NESTED_GRID)
    selections = []
    for outer in outer_folds:
        parts = inner_parts(state, outer)
        scores = {w: validate(state, parts, w) for w in weights}
        # Критерий — средняя NDCG@5 валидации; при равенстве до 9 знаков — больший вес; вес 0 не выбирается
        best = max(NESTED_GRID, key=lambda w: (round(mean([s[1] for s in scores[w]]), 9), w))
        selections.append(Selection(outer, scores, best))
    chosen = [s.chosen for s in selections]
    nested_ranked = run_weights(state, prepared, chosen)
    base_ranked = run_weights(state, prepared, [NESTED_BASE] * len(prepared))
    reference_ranked = run_weights(state, prepared, [NESTED_REFERENCE] * len(prepared))
    rankings: dict[str, Callable[[o1.Result], list[str]]] = {
        "popularity": lambda r: r.ranked["popularity"],
        "coenroll": lambda r: r.ranked["coenroll"],
        "pilot": ranking_of(main, "pilot"),
        "nested": lambda r: nested_ranked[r.case.user],
        "reference": lambda r: reference_ranked[r.case.user],
    }
    repeated = sum(1 for r in results if base_ranked[r.case.user] == main.ranked[r.case.user])
    backend = backend_label()
    grid = "; ".join(weight_label(w) for w in NESTED_GRID)

    print("## Вложенный выбор веса темы истории\n")
    print(
        f"Предрегистрация 12 ноября 2026 года. Код приложения: `{backend}`. Сетка веса темы истории: {grid}; вес "
        f"{weight_label(NESTED_REFERENCE)} — справочная строка, не выбирается. Для каждой внешней части O1 вес "
        f"выбирается на четырёх внутренних частях её обучающей части: популярность и пары — по внутренней "
        f"обучающей части, порог {MIN_SUPPORT}; критерий — средняя NDCG@5 всех валидационных пользователей, при "
        f"равенстве — больший вес. Вес подменяется в `personal.WEIGHTS` только в процессе оценки.\n"
    )
    print("### Валидация внутри обучающих частей\n")
    header = " | ".join(f"NDCG@5 при {weight_label(w)}" for w in weights)
    print(f"| Внешняя часть | Валидационных случаев | {header} | Выбран вес |")
    print(f"| ---: | ---: | {' | '.join('---:' for _ in weights)} | ---: |")
    for s in selections:
        row = " | ".join(fmt(s.mean(w, 1), 3) for w in weights)
        print(f"| {s.outer + 1} | {len(s.scores[NESTED_BASE])} | {row} | {weight_label(s.chosen)} |")
    print()
    print("Средние валидации по внешним частям:\n")
    print("| Вес | Все, hit@5 | NDCG@5 | Та же тема, hit@5 | NDCG@5 | Другая тема, hit@5 | NDCG@5 |")
    print("| ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for w in weights:
        averages = [
            fmt(mean([s.mean(w, metric, group) for s in selections]), 3) for group in POPULATIONS for metric in (0, 1)
        ]
        suffix = ", справочно" if w == NESTED_REFERENCE else ""
        print(f"| {weight_label(w)}{suffix} | {' | '.join(averages)} |")
    print()

    print("### Внешние проверочные части\n")
    by_fold = ", ".join(f"{s.outer + 1} — {weight_label(s.chosen)}" for s in selections)
    print(
        f"Выбранные веса по внешним частям: {by_fold}. Пилот при весе {weight_label(NESTED_BASE)}, пересчитанный тем "
        f"же кодом, повторяет порядок основного сравнения у {repeated} из {len(results)} пользователей.\n"
    )
    print("| Метод | Все, hit@5 | NDCG@5 | Та же тема, hit@5 | NDCG@5 | Другая тема, hit@5 | NDCG@5 |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    order = ("popularity", "coenroll", "pilot", "nested", "reference")
    metric_table(results, [(NESTED_LABELS[name], rankings[name]) for name in order])

    tests = []
    for name in POPULATIONS:
        subset = population(results, name)
        diffs: dict[str, list[float]] = {}
        for a, b in NESTED_COMPARISONS:
            for metric in (0, 1):
                left, right = (metric_values(subset, rankings[m], metric) for m in (a, b))
                diffs[test_key(a, b, name, metric)] = [x - y for x, y in zip(left, right, strict=True)]
        intervals = stats.paired_bootstrap(diffs, RESAMPLES, state.seed + 2)
        for key, values in diffs.items():
            p = stats.sign_flip_pvalue(values, PERMUTATIONS, state.seed + 3)
            tests.append((key, len(subset), mean(values), intervals[key], p))
    adjusted = stats.holm([t[4] for t in tests])
    by_key = {t[0]: (t, adj) for t, adj in zip(tests, adjusted, strict=True)}
    print(
        f"### Парные сравнения вложенного выбора\n\nИнтервал — 95 % перцентильный парного бутстрепа, "
        f"{thousands(RESAMPLES)} выборок; p — перестановочный тест со сменой знака, {thousands(PERMUTATIONS)} "
        f"перестановок; поправка Холма — Бонферрони на {len(tests)} проверок этого семейства.\n"
    )
    print("| Сравнение | Группа | Пользователей | Δ hit@5 [95 % ДИ] | p | p Холма | Δ NDCG@5 [95 % ДИ] | p | p Холма |")
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for name, label in POPULATIONS.items():
        for a, b in NESTED_COMPARISONS:
            cells: list[str] = []
            n = 0
            for metric in (0, 1):
                (_, n, value, (low, high), p), adj = by_key[test_key(a, b, name, metric)]
                cells += [f"{signed(value)} [{signed(low)}; {signed(high)}]", pvalue(p), pvalue(adj)]
            print(f"| {NESTED_LABELS[a]} − {NESTED_LABELS[b]} | {label} | {n} | {' | '.join(cells)} |")
    print()

    def delta(group: str, metric: int) -> float:
        return by_key[test_key("nested", "pilot", group, metric)][0][2]

    conditions = (
        ("Все пользователи, Δ hit@5", delta("all", 0), 0.0),
        ("Все пользователи, Δ NDCG@5", delta("all", 1), 0.0),
        (f"{POPULATIONS['same']}, Δ hit@5", delta("same", 0), -NESTED_MAX_SAME_TOPIC_DROP),
    )
    passed = all(round(value, 9) >= bound for _, value, bound in conditions)
    frequency = Counter(chosen)
    selected = max(frequency, key=lambda w: (frequency[w], w))
    recommended = selected if passed else NESTED_BASE
    print("### Решение по правилу, заданному до прогона\n")
    print(
        f"Выбранный вес: {weight_label(selected)}, выбран в {frequency[selected]} из {len(chosen)} внешних частей. "
        f"Разницы — вложенный выбор минус пилот с весом {weight_label(NESTED_BASE)} на внешних проверочных частях.\n"
    )
    for label, value, bound in conditions:
        verdict = "выполнено" if round(value, 9) >= bound else "не выполнено"
        print(f"- {label}: {signed(value)}; условие «не меньше {fmt(bound) if bound else '0'}» {verdict}.")
    advice = (
        f"оставить вес {weight_label(NESTED_BASE)}" if recommended == NESTED_BASE
        else f"вес темы истории {weight_label(recommended)}"
    )
    print(f"\nРекомендация по правилу: {advice}.\n")
    if recommended == NESTED_BASE:
        return

    screens = {}
    for w in (NESTED_BASE, recommended):
        with patched_weight(NESTED_FEATURE, w):
            screens[w] = run_screen(state, prepared, True)
    print("### Пятёрка на экране при рекомендуемом весе\n")
    print(
        f"Описательно, после решения: в семейство проверок не входит и ничего не выбирает. Тот же запрос, что в "
        f"разделе о пятёрке на экране: полный каталог копии, порог {MIN_SUPPORT}, limit {K} без добора; вес один для "
        f"всех частей.\n"
    )
    print("| Вариант | Все, hit@5 | NDCG@5 | Та же тема, hit@5 | NDCG@5 | Другая тема, hit@5 | NDCG@5 |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    metric_table(results, [(f"Пилот, вес {weight_label(w)}", screen_ranking(view)) for w, view in screens.items()])
    print(
        "| Вариант | Карточек по форматам | Курсов в пятёрке, среднее | "
        "Курсов другой темы в пятёрке, пользователей |"
    )
    print("| --- | --- | ---: | --- |")
    for w, view in screens.items():
        by_count = sorted(view.formats.items(), key=lambda kv: (-kv[1], kv[0]))
        cards = ", ".join(f"{kind} {count}" for kind, count in by_count)
        other = ", ".join(f"{k} — {view.other_courses[k]}" for k in sorted(view.other_courses))
        print(f"| Пилот, вес {weight_label(w)} | {cards} | {fmt(mean(view.courses), 1)} | {other} |")
    print()


def outcome_key(outcome: policy.Outcome) -> tuple:
    return (
        outcome.status,
        outcome.detected_topics,
        tuple(i.material.id for i in outcome.items),
        tuple(tuple(r) for r in outcome.reasons),
        outcome.total_candidates,
        outcome.message,
        repr(outcome.clarification),
        tuple(m.id for m in outcome.route),
    )


def bucket(n: int) -> str:
    for low, high in ((0, 0), (1, 5), (6, 10), (11, 20)):
        if low <= n <= high:
            return str(low) if low == high else f"{low}–{high}"
    return "21 и больше"


def product(db: Path, signals: Path, pairs_path: Path) -> None:
    base = Settings(catalog_source="sqlite", catalog_path=db, catalog_signals_path=signals)
    without = load_catalog(base)
    with_pairs = load_catalog(replace(base, catalog_pairs_path=pairs_path))
    summary = with_pairs.coverage["course_pairs"]
    print("## Проверка продукта на копии\n")
    print(
        f"Каталог {with_pairs.source}, версия {with_pairs.version}, {with_pairs.size} материалов; пары: source "
        f"{summary['source']}, порог {summary['min_support']}, пар {summary['pairs']}, курсов {summary['courses']}, "
        f"ниже порога {summary['dropped']['below_support']}; отключённые признаки без пар: "
        f"{', '.join(without.disabled_features) or 'нет'}; с парами: "
        f"{', '.join(with_pairs.disabled_features) or 'нет'}.\n"
    )

    profiles = {pid: demo for pid, demo in load_profiles().items() if pid in PROFILES}
    same = total = 0
    for demo in profiles.values():
        for limit in (5, 10):
            for method in policy.METHODS:
                profile = Profile(
                    task=demo.task, stage=demo.stage, experience=demo.experience, format_pref=demo.format_pref,
                    industry=demo.industry, history=demo.history, limit=limit,
                )
                total += 1
                same += outcome_key(policy.recommend(without, profile, method)) == outcome_key(
                    policy.recommend(with_pairs, profile, method)
                )
    print(
        f"P01–P10 при limit 5 и 10, оба метода, с файлом пар и без него: совпадают {same} из {total} "
        f"(статус, темы, порядок, причины, сообщение, уточнение, маршрут).\n"
    )

    pairs = with_pairs.course_pairs
    courses = {mid: m for mid, m in with_pairs.materials.items() if m.format == "course"}
    available = {mid for mid, m in courses.items() if m.available}
    enrolled = {mid for mid in courses if pairs is not None and pairs.totals.get(mid, 0) > 0}
    groups = {
        "Доступные курсы": sorted(available),
        "Недоступные курсы с записями": sorted(enrolled - available),
    }
    print(
        "| История — один пройденный курс | Запросов | Подбор по истории | Фраза о похожих курсах в пятёрке | "
        "Курс другой темы в пятёрке | Курсов в пятёрке, среднее | Фраз о похожих курсах, среднее |"
    )
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    faith: Counter[str] = Counter()
    formats: dict[str, Counter[str]] = {}
    for label, group in groups.items():
        counts: Counter[str] = Counter()
        course_cards: list[int] = []
        phrases: list[int] = []
        formats[label] = Counter()
        for course in group:
            profile = Profile(history=(HistoryEvent(course, "complete", 1),), limit=K)
            outcome = policy.recommend(with_pairs, profile, "personal")
            topics = set(courses[course].topics)
            counts["history"] += outcome.status == "weak"
            formats[label].update(i.material.format for i in outcome.items)
            with_phrase = 0
            other = False
            for item, reasons in zip(outcome.items, outcome.reasons, strict=True):
                phrase = any(reason.startswith(PHRASE_MARK) for reason in reasons)
                contribution = item.contributions.get("co_enrollment", 0) > 0
                with_phrase += phrase
                faith["contribution"] += contribution
                faith["phrase"] += phrase
                faith["phrase_without_contribution"] += phrase and not contribution
                if item.material.format == "course" and not topics & set(item.material.topics):
                    other = True
                    faith["other_topic"] += 1
                    faith["other_topic_without_phrase"] += not phrase
            counts["phrase"] += with_phrase > 0
            counts["other"] += other
            course_cards.append(sum(1 for i in outcome.items if i.material.format == "course"))
            phrases.append(with_phrase)
        n = len(group)
        print(
            f"| {label} | {n} | {counts['history']} | {counts['phrase']} | {counts['other']} | "
            f"{fmt(mean(course_cards), 1)} | {fmt(mean(phrases), 1)} |"
        )
    print()
    print(
        f"Карточки пятёрок: с вкладом похожих курсов {faith['contribution']}, с фразой {faith['phrase']}, с фразой без "
        f"вклада {faith['phrase_without_contribution']}; курсов другой темы {faith['other_topic']}, из них без фразы "
        f"{faith['other_topic_without_phrase']}.\n"
    )
    for label, counter in formats.items():
        cards = ", ".join(f"{name} {n}" for name, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))
        print(f"Форматы карточек пятёрок, {label.lower()}: всего {sum(counter.values())}; {cards}.")
    print()

    print(f"Пары от порога {summary['min_support']} на курс:\n")
    print("| Курсы | Курсов | 0 | 1–5 | 6–10 | 11–20 | 21 и больше | Слушателей не меньше 10 |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for label, group in groups.items():
        for target, suffix in ((None, "все соседи"), (available, "доступные соседи")):
            dist: Counter[str] = Counter()
            for course in group:
                row = pairs.neighbours(course) if pairs is not None else {}
                dist[bucket(sum(1 for other in row if target is None or other in target))] += 1
            anchors = sum(1 for course in group if pairs is not None and pairs.totals.get(course, 0) >= 10)
            cells = " | ".join(str(dist[b]) for b in ("0", "1–5", "6–10", "11–20", "21 и больше"))
            print(f"| {label}, {suffix} | {len(group)} | {cells} | {anchors} |")
    print()

    # Замечание 6 ревью пилота. С уточнением условия 12 ноября 2026 года подбор по истории включается, только если
    # пара от порога приводит в кандидаты доступный курс вне истории; иначе ответ — стартовая подборка.
    # Курсы, которые пара приводит в кандидаты, считает сам продукт: personal.co_enrollment
    by_user, _ = o1.read_bindings(db)
    linked = {course for course in courses if pairs is not None and pairs.neighbours(course)}
    narrowed: Counter[str] = Counter()
    disabled = frozenset(with_pairs.disabled_features)
    for bindings in by_user.values():
        narrowed["no_pair"] += not {b.course for b in bindings} & linked
        events = events_of(bindings)
        built = HistorySignals.build(events, with_pairs.materials)
        ctx = Context(
            profile=Profile(history=events, limit=K), parsed=parse_task(""), topics=(),
            history=HistoryIndex.build(events), disabled=disabled, catalog=with_pairs.materials, pairs=pairs,
            anchors=built.anchors, history_topics=built.topics,
        )
        found = [courses[c] for c in sorted(available) if personal.co_enrollment(courses[c], ctx)[1] is not None]
        narrowed["no_linked"] += not found
        narrowed["no_other"] += not [m for m in found if not set(built.topics) & set(m.topics)]
    # Без связанного курса нет и связанного курса другой темы: такие пользователи получают стартовую подборку,
    # а подбор по истории без курсов других тем остаётся у разности счётчиков
    narrowed["restricted"] = narrowed["no_other"] - narrowed["no_linked"]
    users = len(by_user)
    share = {key: f"{value} ({fmt(100 * value / users, 1)} %)" for key, value in narrowed.items()}
    print(
        f"Пользователи журнала: {thousands(users)}. Ни у одного курса истории нет пары от порога у "
        f"{share['no_pair']}. Нет доступного курса вне истории, который пара приводит в кандидаты, у "
        f"{share['no_linked']}: подбор по истории не включается, ответ — стартовая подборка. Подбор по истории "
        f"без курсов других тем, только по темам истории, у {share['restricted']}.\n"
    )


def backend_label() -> str:
    return BACKEND.relative_to(PROJECT).as_posix() if BACKEND.is_relative_to(PROJECT) else str(BACKEND)


def main(argv: list[str]) -> int:
    args = argv[1:]
    with_nested = "--nested" in args
    args = [a for a in args if a != "--nested"]
    if len(args) not in (1, 3):
        print(__doc__)
        return 2
    if os.environ.get("OFFLINE_BACKEND"):
        # Только в поток ошибок: основной вывод и его побайтное совпадение не меняются. Переменная, оставленная
        # в окне PowerShell, иначе незаметно направила бы итоговый пересчёт на снимок кода
        print(f"OFFLINE_BACKEND задан: код приложения из {backend_label()}", file=sys.stderr)
    db = Path(args[0])
    with contextlib.redirect_stdout(io.StringIO()):
        state = o1.evaluate(db)
    prepared, pilot_run = offline(state)
    if with_nested:
        nested(state, prepared, pilot_run)
    if len(args) == 3:
        product(db, Path(args[1]), Path(args[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
