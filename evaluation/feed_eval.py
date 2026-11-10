"""Офлайн-оценка ленты по профилю на журнале записей: выбор весов, метрика модели и её паспорт.

Запуск из корня проекта, одна команда воспроизводит все числа:
  python -X utf8 evaluation/feed_eval.py data/local/catalog.sqlite3 data/local/catalog-signals.sqlite3
Флаг `--card` записывает паспорт модели в backend/data/model-card.json: его читает `GET /api/model-card`.
Флаг `--articles` вместо этого запускает проверку весов для материалов без журнала на псевдоэталоне редакционных
связей; её протокол записан в функции `articles`.
Выводятся только агрегаты: без кодов, названий и идентификаторов.

Протокол, записан до прогона.

Данные. Случаи, части, цели и кандидаты — протокол O1 без изменений (`offline_courses.evaluate`): у пользователя
с двумя и более курсами одна запись скрыта, остальные — история; кандидаты — доступные курсы без курсов
истории. Пять частей, пары совместных записей и популярность считаются по обучающей части, порог поддержки 10.
Каталог — тот же, что в продукте, с базой признаков; популярность курсов нормирована внутри формата.

Модель. `app/ranking/feed.py`, функция `rank`: порядок курсов-кандидатов в ленте. Кандидаты, которых лента
не вернула (дубликаты названия), дописываются по популярности обучающей части, как в O1.

Выбор весов. Отправная точка — веса PRIOR, заданные до оценки. Меняется по одному весу, остальные стоят на
отправной точке: популярность, доступ и цена, выбор слушателей. Выбор идёт на частях 0–2 по
средней NDCG@5 всех пользователей; при равенстве до третьего знака остаётся отправное значение. Лучшие
значения собираются в одну конфигурацию; если на частях 0–2 она хуже лучшей одиночной замены, берётся
одиночная. Выбранная конфигурация сравнивается с отправной, с совместными записями и с популярностью
на частях 3–4: они в выборе не участвовали. Интервалы — парный бутстреп, 5 000 выборок, зерно 20261115.

Ожидание, записано до прогона. На курсах порядок задают совместные записи; совет редакции на журнале пользы
не давал, поэтому его вес уменьшится. Сходство содержания и популярность
курсы почти не различают. На этих частях уже испробовано 205 конфигураций, поэтому числа выбора
разведочные, а подтверждением служат только части 3–4.

Три проверки устройства модели, все на частях 0–2, и ни одна не меняет веса продукта.
Сходство содержания у курсов с журналом: к выбору слушателей добавляется косинус с весом 0,5, 1 и 2.
Совет редакции у курсов с журналом: надбавка 0,25, 0,5 и 1,5 курсу из блока «далее» у курса истории.
Глубина события: доля курса истории умножается на вес события «открыл» и «начал», вес делится на наибольший
вес среди курсов истории пользователя, поэтому у пользователя с одним курсом истории ничего не меняется.

Чего журнал не проверяет. Статей в журнале нет, поэтому вес сходства содержания и всё, что смешивает курсы
со статьями, анкета и задача остаются гипотезами. Смешанная лента на весь каталог описывается, но по ней веса
не настраиваются: иначе курсы вытеснят статьи. Разнообразие тем выбирается отдельным правилом: наибольший вес
из сетки, при котором NDCG@5 курсов в смешанной ленте на частях 0–2 ниже не более чем на 0,01.
Штраф кандидата — вес · ln(1 + n), где n — число уже отобранных карточек его первой темы; отбор жадный.

Изменения после первого прогона, записаны до повторного. Первый прогон шёл с моделью, где сходство содержания
начислялось всем материалам и входило в сетку: на частях 0–2 NDCG@5 падала с 0,594 при весе 0 до 0,557 при
весе 2, и правило выбрало вес 0. Тот же прогон проверил вес глубины без деления на наибольший: при весе 0,25
у события «открыл» NDCG@5 0,554 против 0,573 без веса. Поэтому в модели сходство содержания оставлено только
материалам без журнала, а вес глубины убран. Лучший вес выбора слушателей стоял на краю сетки, сетка
расширена до 12. Части 3–4 в первом прогоне уже показывались: их числа у курсов от изменения устройства
не зависят, потому что у курсов с журналом сходство содержания и раньше получило вес 0.

Изменения после второго прогона, записаны до третьего. Во втором прогоне совет редакции оставался в сетке:
на частях 0–2 NDCG@5 0,563 при весе 0 против 0,556 при весе 1,5, правило выбрало 0. Поэтому совет редакции,
как и сходство содержания, оставлен только материалам без журнала и из сетки убран в проверки устройства.
Числа курсов на частях 3–4 от этого не меняются: выбранная конфигурация второго прогона уже имела нулевой
вес совета редакции.

Режим оценки курса, записан перед итоговым прогоном. В третьем прогоне курс считался курсом с журналом по
числу записей на него самого. Новые курсы без записей получали сходство содержания и вставали выше курсов
с журналом, а скрытая запись — всегда курс с записями: на частях 3–4 лента уступила совместным записям,
NDCG@5 −0,025 [−0,043; −0,007]. Правило заменено: курс оценивается по журналу, если в истории клиента есть
курс с журналом. Показ новых курсов на пробу отложен отдельным решением и здесь не оценивается.

Отклонение от правила о весе популярности, записано после итогового прогона. С итоговым устройством правило
выбирает для курсов нулевой вес популярности: NDCG@5 на частях 0–2 0,609 при весе 0 против 0,590 при весе 1.
В продукте вес популярности 1,0: он общий для всех материалов, задаёт положение курсов среди статей и нужен
материалам без журнала. Цена на частях 3–4: лента продукта и совместные записи различаются по NDCG@5
на −0,006 [−0,022; +0,010]. Строка «Веса продукта совпадают с выбранными по правилу» поэтому отвечает «нет».

Курс обмена между курсами и материалами без журнала, записан до третьего прогона. Первый прогон `--articles`
выбрал отношение веса сходства содержания к весу популярности 5 : 3 (пары 0,5 и 0,3). С этими весами
и весом популярности курсов 1,0 первые десять карточек синтетических клиентов занимали одни курсы, в том
числе без личных свидетельств. Поэтому вес популярности сделан общим для всех материалов, 1,0, а вес
сходства содержания задан тем же отношением: 1,7. Порядок внутри курсов и внутри материалов без журнала
от этого не меняется, меняется только их взаимное положение, которое остаётся гипотезой.

Модель EASE вместо доли слушателей, записано перед шестым прогоном. Пользователь возразил на довод об
объяснимости: под капотом вклад можно считать любой моделью, а описать подробнее. До этого EASE сравнивался
с совместными записями только отдельно от ленты (O1: NDCG@5 +0,011, hit@5 +0,001). Разведочный прогон вне
репозитория проверил его внутри ленты с правилом, записанным заранее: метод принимается, если на всех 803
пользователях NDCG@5 ленты выше не меньше чем на 0,005 и ни одна из двух групп не ниже больше чем на 0,005;
значимость не требовалась. Результат: скрытый курс первым 0,46 против 0,42, разница +0,034 [+0,015; +0,054];
NDCG@5 +0,018 [+0,007; +0,029]; строгий порядок +0,016, случайная цель +0,018. Правило выполнено.
В продукте слагаемое «Выбор слушателей» теперь равно весу, умноженному на сумму весов EASE по курсам истории
в единицах доли слушателей (`app/catalog/ease.py`). Матрица строится по счётчикам файла пар: в частях этого
протокола это счётчики обучающей части, скрытая запись в них не входит. λ = 1000 взято из вложенного выбора O1,
где его выбрали четыре части из пяти, и здесь не подбирается. Сетка весов и правила выбора прежние. Строка
«Лента с долей слушателей вместо модели EASE» считает ту же ленту с прежней формулой и остаётся в отчёте,
чтобы разница воспроизводилась. Части 3–4 показаны и в этом прогоне.

Отклонение от правила о разнообразии, записано после второго прогона и прогона `--articles`. Правило допускало
вес 0,30: NDCG@5 курсов на частях 0–2 снижалась на 0,008, число тем в первой десятке росло с 5,6 до 7,8.
На псевдоэталоне статей тот же штраф снизил долю источников с целью в первых 10 карточках с 0,347 до 0,324
на половине подтверждения. Решение: разнообразие в модель не включено, порядок идёт строго по оценке. Штраф
остался в этом скрипте как проверенный вариант, чтобы его числа воспроизводились; веса продукта он не меняет.
"""

from __future__ import annotations

import contextlib
import heapq
import io
import json
import random
import sys
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, replace
from math import log1p, log2
from pathlib import Path

import offline_pilot as pilot  # первым: закрепляет пакет приложения из backend
import offline_courses as o1
import offline_stats as stats
from app.catalog.coverage import normalize_popularity
from app.catalog.loader import load_catalog
from app.catalog.models import Catalog, CoursePairs, Material
from app.config import Settings
from app.ranking import feed, personal
from app.ranking.base import CoEnrollment, Profile

K = 5
FEED = 50
SUPPORT = 10
SELECT_FOLDS = (0, 1, 2)
CONFIRM_FOLDS = (3, 4)
RESAMPLES = 5000
SEED = 20261115
PAIR_SAMPLES = 2000
VARIETY_GRID = (0.1, 0.2, 0.3)
CONTENT_ON_COURSES = (0.5, 1.0, 2.0)
DEPTH_VARIANTS = ((0.25, 0.5), (0.5, 0.75), (0.5, 1.0))  # вес события «открыл» и «начал»; «прошёл» и «оплатил» — 1
CARD = pilot.PROJECT / "backend" / "data" / "model-card.json"

# Веса до оценки: минимальный срез этапа 4
PRIOR: dict[str, float] = {"co_enrollment": 3.0, "popularity": 0.3, "access": 0.2}
GRID: dict[str, tuple[float, ...]] = {
    "popularity": (0.0, 0.3, 0.6, 1.0),
    "access": (0.0, 0.2),
    "co_enrollment": (1.5, 3.0, 6.0, 12.0),
}
LINK_ON_COURSES = (0.25, 0.5, 1.5)
LABELS = {
    "co_enrollment": "Выбор слушателей", "content": "Похожее содержание", "continuation": "Совет редакции",
    "popularity": "Популярность", "access": "Доступ и цена",
}
CHOSEN_HERE = ("co_enrollment", "popularity", "access")
Config = dict[str, float]
Places = dict[str, int]


def fmt(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",").replace("-", "−")


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


@contextlib.contextmanager
def configured(config: Config) -> Iterator[None]:
    """Временные веса ленты; после блока восстанавливаются. Код приложения не меняется."""
    saved = dict(feed.FEED_WEIGHTS)
    try:
        feed.FEED_WEIGHTS.update(config)
        yield
    finally:
        feed.FEED_WEIGHTS.clear()
        feed.FEED_WEIGHTS.update(saved)


@contextlib.contextmanager
def patched(name: str, value: Callable) -> Iterator[None]:
    """Временная замена функции ленты для проверки устройства модели."""
    saved = getattr(feed, name)
    setattr(feed, name, value)
    try:
        yield
    finally:
        setattr(feed, name, saved)


def extra_on_courses(source: str, weight: float) -> Callable:
    """Оценка кандидата, где курс с журналом получает ещё и слагаемое материалов без журнала.

    `source` — `content`: сходство содержания; `continuation`: совет редакции.
    """
    original = feed._score

    def score_with_extra(material: Material, ctx, signals) -> object:
        item = original(material, ctx, signals)
        if feed._by_log(material, signals) and not signals.history.of(material.id):
            if source == "content":
                extra = round(weight * signals.interests.cosine(material), 2)
            else:
                extra = weight if material.id in signals.linked else 0.0
            if extra:
                item.contributions[source] = extra
                item.score = round(item.score + extra, 2)
        return item

    return score_with_extra


def select_with_variety(weight: float) -> Callable:
    """Жадный отбор со штрафом за повтор темы: проверенный вариант, в продукт не включён.

    Штраф кандидата — weight · ln(1 + n), где n — число уже отобранных карточек его первой темы. Он только
    растёт, поэтому ленивый пересчёт на куче точен, а оценки отобранных карточек не возрастают.
    """

    def select(scored: list, limit: int | None) -> list:
        count = len(scored) if limit is None else min(limit, len(scored))
        base = {item.material.id: item.score for item in scored}
        heap = [(feed.sort_key(item), item) for item in scored]
        heapq.heapify(heap)
        placed: Counter[str] = Counter()
        selected = []
        while heap and len(selected) < count:
            _, item = heapq.heappop(heap)
            topic = item.material.topics[0] if item.material.topics else None
            penalty = round(weight * log1p(placed[topic]), 2) if topic else 0.0
            current = round(base[item.material.id] - penalty, 2)
            if current != item.score:
                item.score = current
                heapq.heappush(heap, (feed.sort_key(item), item))
                continue
            if topic:
                placed[topic] += 1
            selected.append(item)
        return selected

    return select


# Вес глубины курсов истории текущего случая: заполняется перед оценкой случая
CASE_DEPTH: dict[str, float] = {}


def depth_of(view: float, start: float) -> Callable[[o1.Case], None]:
    weights = {"view": view, "start": start, "complete": 1.0}

    def prepare(case: o1.Case) -> None:
        CASE_DEPTH.clear()
        own = {b.course: 1.0 if b.paid else weights[b.event] for b in case.inputs}
        top = max(own.values())
        CASE_DEPTH.update({course: value / top for course, value in own.items()})

    return prepare


def co_enrollment_with_depth(
    material: Material, anchors: list[str], pairs: CoursePairs | None
) -> tuple[float, CoEnrollment | None]:
    """Как `feed._co_enrollment`, но доля курса истории умножена на вес глубины из CASE_DEPTH."""
    if pairs is None or material.format != "course":
        return 0.0, None
    total, best = 0.0, None
    for anchor in anchors:
        users = pairs.totals.get(anchor, 0)
        together = pairs.neighbours(anchor).get(material.id, 0)
        if anchor == material.id or users < personal.CO_ENROLLMENT_MIN_ANCHOR_USERS or together <= 0:
            continue
        share = CASE_DEPTH.get(anchor, 1.0) * together / users
        total += share
        if best is None or share > best[0]:
            best = (share, CoEnrollment(anchor=anchor, together=together, total=users))
    return min(1.0, total), best[1] if best else None


@dataclass(slots=True)
class Part:
    """Одна часть O1: каталог продукта с парами и популярностью обучающей части и проверочные случаи."""

    fold: int
    catalog: Catalog
    popularity: Counter[str]
    results: list[o1.Result]


def parts(state: o1.State, catalog: Catalog) -> list[Part]:
    courses = [code for code, material in catalog.materials.items() if material.format == "course"]
    disabled = tuple(f for f in catalog.disabled_features if f != "co_enrollment")
    prepared = []
    for index, part in enumerate(pilot.folds(state)):
        raw = {code: float(part.popularity.get(code, 0)) for code in courses}
        ranks = normalize_popularity(raw, dict.fromkeys(courses, "course"), "per_format")
        materials = {
            code: replace(m, popularity_raw=raw[code], popularity=ranks[code]) if code in raw else m
            for code, m in catalog.materials.items()
        }
        pairs, _ = pilot.fold_pairs(part.together, part.users_with, materials, SUPPORT)
        fold_catalog = Catalog(
            materials=materials, source=catalog.source, version=catalog.version, disabled_features=disabled,
            course_pairs=pairs,
        )
        prepared.append(Part(index, fold_catalog, part.popularity, part.results))
    return prepared


def without_model(prepared: list[Part]) -> list[Part]:
    """Те же части без весов EASE: слагаемое «Выбор слушателей» считается долей слушателей, как до замены."""
    return [
        replace(part, catalog=replace(part.catalog, course_pairs=replace(part.catalog.course_pairs, weights={})))
        for part in prepared
    ]


def candidates_of(state: o1.State, case: o1.Case) -> list[str]:
    inputs = {b.course for b in case.inputs}
    return [c for c in state.available if c not in inputs]


def course_order(order: list[str], candidates: list[str], popularity: Counter[str]) -> list[str]:
    allowed = set(candidates)
    own = [code for code in order if code in allowed]
    return own + o1.rank_popularity([c for c in candidates if c not in set(own)], popularity)


def run_courses(
    state: o1.State, prepared: list[Part], config: Config, before: Callable[[o1.Case], None] | None = None
) -> Places:
    """Место скрытого курса среди курсов-кандидатов у ленты с весами `config`: пользователь → индекс с нуля."""
    places: Places = {}
    with configured(config):
        for part in prepared:
            for r in part.results:
                if before is not None:
                    before(r.case)
                candidates = candidates_of(state, r.case)
                order = feed.rank(part.catalog, Profile(history=pilot.history(r.case)), only=set(candidates)).order
                places[r.case.user] = course_order(order, candidates, part.popularity).index(r.case.target)
    return places


def baseline(results: list[o1.Result], method: str) -> Places:
    return {r.case.user: r.ranked[method].index(r.case.target) for r in results}


METRICS: dict[str, Callable[[int], float]] = {
    "hit@1": lambda place: 1.0 if place < 1 else 0.0,
    "hit@5": lambda place: 1.0 if place < K else 0.0,
    "MRR": lambda place: 1 / (place + 1),
    "NDCG@5": lambda place: 1 / log2(place + 2) if place < K else 0.0,
}


def score(places: Places, users: Sequence[str], metric: str = "NDCG@5") -> float:
    return mean([METRICS[metric](places[user]) for user in users])


def table(title: str, rows: list[tuple[str, Places]], users: Sequence[str]) -> None:
    print(f"{title}: {len(users)} пользователей\n")
    print("| Метод | hit@1 | hit@5 | MRR | NDCG@5 |")
    print("| --- | ---: | ---: | ---: | ---: |")
    for label, places in rows:
        print(f"| {label} | " + " | ".join(fmt(score(places, users, metric)) for metric in METRICS) + " |")
    print()


def difference(a: Places, b: Places, users: Sequence[str], metric: str) -> str:
    """Разница средних и 95 % интервал парного бутстрепа."""
    series = [METRICS[metric](a[user]) - METRICS[metric](b[user]) for user in users]
    low, high = stats.paired_bootstrap({"d": series}, RESAMPLES, SEED)["d"]
    return f"{pilot.signed(mean(series))} [{pilot.signed(low)}; {pilot.signed(high)}]"


def select(state: o1.State, prepared: list[Part], users: Sequence[str]) -> tuple[Config, dict[str, dict[float, float]]]:
    """Выбор по одному весу на частях выбора; возвращает конфигурацию и NDCG@5 каждого значения сетки."""
    reference = score(run_courses(state, prepared, PRIOR), users)
    scores: dict[str, dict[float, float]] = {}
    chosen = dict(PRIOR)
    best_single: tuple[float, Config] = (reference, dict(PRIOR))
    for name, values in GRID.items():
        scores[name] = {
            value: reference if value == PRIOR[name] else score(run_courses(state, prepared, {**PRIOR, name: value}), users)
            for value in sorted({*values, PRIOR[name]})
        }
        top = max(scores[name].values())
        # При равенстве до третьего знака остаётся отправное значение
        if round(top, 3) > round(scores[name][PRIOR[name]], 3):
            chosen[name] = max(scores[name], key=lambda v: (round(scores[name][v], 3), -abs(v - PRIOR[name])))
            if top > best_single[0]:
                best_single = (top, {**PRIOR, name: chosen[name]})
    combined = score(run_courses(state, prepared, chosen), users)
    scores["combined"] = {0.0: combined, 1.0: best_single[0], 2.0: reference}
    return (chosen if combined >= best_single[0] else best_single[1]), scores


@dataclass(slots=True)
class Mixed:
    """Смешанная лента на весь каталог: первые 50 карточек пользователя и место скрытого курса среди курсов."""

    top: dict[str, list[str]]
    places: Places
    hidden: dict[str, int | None]  # место скрытого курса в ленте из 50; None — не вошёл


def run_mixed(state: o1.State, prepared: list[Part], config: Config) -> Mixed:
    run = Mixed({}, {}, {})
    with configured(config):
        for part in prepared:
            for r in part.results:
                user, candidates = r.case.user, candidates_of(state, r.case)
                order = feed.rank(part.catalog, Profile(history=pilot.history(r.case))).order
                run.top[user] = order[:FEED]
                run.places[user] = course_order(order, candidates, part.popularity).index(r.case.target)
                run.hidden[user] = order.index(r.case.target) if r.case.target in order[:FEED] else None
    return run


def describe(run: Mixed, catalog: Catalog, users: Sequence[str]) -> dict[str, float]:
    """Описательные свойства ленты: что в первых десяти и пятидесяти карточках и насколько ленты различаются."""
    materials = catalog.materials
    first = [run.top[user][:10] for user in users]
    formats = Counter(materials[code].format for row in first for code in row)
    shown = sum(formats.values())
    rng = random.Random(SEED)
    overlap = []
    for _ in range(PAIR_SAMPLES):
        a, b = rng.sample(list(users), 2)
        overlap.append(len(set(run.top[a]) & set(run.top[b])) / FEED)
    available = sum(1 for m in materials.values() if m.available)
    return {
        "recall@10": mean([1.0 if (p := run.hidden[user]) is not None and p < 10 else 0.0 for user in users]),
        "recall@50": mean([1.0 if run.hidden[user] is not None else 0.0 for user in users]),
        "courses@10": formats["course"] / shown,
        "articles@10": formats["article"] / shown,
        "formats@10": mean([len({materials[c].format for c in row}) for row in first]),
        "topics@10": mean([len({t for c in row for t in materials[c].topics[:1]}) for row in first]),
        "paid@10": mean([sum(1 for c in row if materials[c].is_paid) / len(row) for row in first]),
        "coverage@50": len({code for user in users for code in run.top[user]}) / available,
        "overlap@50": mean(overlap),
        "distinct@10": len({tuple(row) for row in first}) / len(users),
    }


DESCRIPTION = {
    "recall@10": "Скрытый курс в первых 10 карточках ленты",
    "recall@50": "Скрытый курс в ленте из 50",
    "courses@10": "Доля курсов в первых 10",
    "articles@10": "Доля статей в первых 10",
    "formats@10": "Разных форматов в первых 10",
    "topics@10": "Разных тем в первых 10",
    "paid@10": "Доля платного и подписки в первых 10",
    "coverage@50": "Доля доступного каталога, попавшая в ленты",
    "overlap@50": "Пересечение лент двух случайных пользователей",
    "distinct@10": "Разных первых десяток на пользователя",
}


ARTICLE_GRID = tuple((content, popularity) for content in (0.5, 1.0, 2.0) for popularity in (0.0, 0.3, 0.6))
ARTICLE_MIN_GAIN = 0.005


def articles(db: Path, signals: Path) -> None:
    """Материалы без журнала: веса сходства содержания и популярности на псевдоэталоне редакционных связей.

    Протокол, записан до прогона. Случаи и скрытие связи — как в R28 (`offline_r28.py`): источник — доступная
    статья или документ с редакционными ссылками на доступные материалы; ссылки источника скрыты, источник
    записан в историю единственным событием, вклад совета редакции отключён, популярность целей уменьшена
    на скрытую ссылку. Пар совместных записей в каталоге случая нет, поэтому все материалы оцениваются
    как материалы без журнала. Лента — `feed.rank` по всему каталогу, без разнообразия.

    Вопрос один: в каком отношении складывать сходство содержания и популярность. Сетка — вес сходства
    содержания 0,5, 1 и 2 и вес популярности 0, 0,3 и 0,6; пара весов продукта добавляется в сетку сама.
    Источники в порядке кода делятся через один: чётные — выбор, нечётные — подтверждение. Критерий — доля
    источников, у которых хотя бы одна цель стоит в первых 10 карточках; при равенстве — MRR. Порядок
    материалов задаёт отношение весов, а не их величина. Если лучшая пара превосходит пару продукта меньше
    чем на 0,005, веса продукта остаются.

    Уточнение после прогона. Из выбранной пары в продукт идёт только отношение весов: вес популярности
    в продукте общий для всех материалов и выбран на журнале. Лучшая пара половины выбора — 0,5 и 0,3,
    отношение 5 : 3; при весе популярности 1,0 оно даёт вес сходства 1,7, это пара продукта. Сама пара
    продукта на половине выбора ниже лучшей на 0,010, на половине подтверждения выше на 0,002: разница
    между парами одного отношения не воспроизводится, это шаг округления оценок до сотых.

    Ограничение: связи выражают мнение редакции, а не поведение читателей.
    """
    import offline_r28 as r28  # noqa: PLC0415 — нужен только этому режиму
    from app.catalog.models import HistoryEvent  # noqa: PLC0415

    catalog = load_catalog(Settings(catalog_source="sqlite", catalog_path=db, catalog_signals_path=signals))
    world = r28.World(catalog)
    cases = [case for case in r28.cases_of(world.base) if case.source.format in ("article", "document")]
    product = (feed.FEED_WEIGHTS["content"], feed.FEED_WEIGHTS["popularity"])
    grid = sorted({*ARTICLE_GRID, product})
    extra = {"только популярность": (0.0, product[1]), "с разнообразием 0,30": product}
    hits: dict[object, list[float]] = {key: [] for key in (*grid, *extra)}
    rr: dict[object, list[float]] = {key: [] for key in (*grid, *extra)}
    for case in cases:
        case_catalog = world.case_catalog(case)
        profile = Profile(history=(HistoryEvent(case.source.id, "complete", 1),))
        for key in (*grid, *extra):
            content, popularity = key if isinstance(key, tuple) else extra[str(key)]
            selector = select_with_variety(0.3) if key == "с разнообразием 0,30" else feed._select
            with configured({"content": content, "popularity": popularity}), patched("_select", selector):
                order = feed.rank(case_catalog, profile).order
            first = next((place for place, code in enumerate(order) if code in case.targets), None)
            hits[key].append(1.0 if first is not None and first < 10 else 0.0)  # noqa: PLR2004
            rr[key].append(1 / (first + 1) if first is not None else 0.0)
    halves = {"выбор": range(0, len(cases), 2), "подтверждение": range(1, len(cases), 2)}

    def value(series: list[float], half: str) -> float:
        return mean([series[i] for i in halves[half]])

    best = max(grid, key=lambda key: (round(value(hits[key], "выбор"), 3), round(value(rr[key], "выбор"), 3)))
    gain = value(hits[best], "выбор") - value(hits[product], "выбор")
    chosen = best if gain >= ARTICLE_MIN_GAIN else product
    print(
        f"## Материалы без журнала: псевдоэталон редакционных связей\n\nИсточников {len(cases)}: статьи и документы "
        f"с редакционными ссылками; половина выбора {len(halves['выбор'])}, половина подтверждения "
        f"{len(halves['подтверждение'])}.\n"
    )
    print("| Сходство содержания | Популярность | Цель в первых 10, выбор | MRR, выбор | Цель в первых 10, подтверждение | MRR, подтверждение |")
    print("| ---: | ---: | ---: | ---: | ---: | ---: |")
    for key in grid:
        mark = " (продукт)" if key == product else ""
        print(
            f"| {fmt(key[0])} | {fmt(key[1])}{mark} | {fmt(value(hits[key], 'выбор'), 3)} | {fmt(value(rr[key], 'выбор'), 3)} | "
            f"{fmt(value(hits[key], 'подтверждение'), 3)} | {fmt(value(rr[key], 'подтверждение'), 3)} |"
        )
    for label in extra:
        print(
            f"| {label} | | {fmt(value(hits[label], 'выбор'), 3)} | {fmt(value(rr[label], 'выбор'), 3)} | "
            f"{fmt(value(hits[label], 'подтверждение'), 3)} | {fmt(value(rr[label], 'подтверждение'), 3)} |"
        )
    ratio = {name: fmt(pair[0] / pair[1]) if pair[1] else "без популярности" for name, pair in (("best", best), ("own", product))}
    print(
        f"\nЛучшая пара на половине выбора: сходство {fmt(best[0])}, популярность {fmt(best[1])}; выигрыш у пары "
        f"продукта {pilot.signed(gain)} на половине выбора и "
        f"{pilot.signed(value(hits[best], 'подтверждение') - value(hits[product], 'подтверждение'))} на половине "
        f"подтверждения. Отношение веса сходства к весу популярности: у лучшей пары {ratio['best']}, у продукта "
        f"{ratio['own']}. По правилу о паре: сходство {fmt(chosen[0])}, популярность {fmt(chosen[1])}."
    )


def main(argv: list[str]) -> int:  # noqa: PLR0915 — один линейный отчёт
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a for a in argv[1:] if a.startswith("--")}
    if len(args) != 2 or flags - {"--card", "--articles"}:
        print(__doc__)
        return 2
    db, signals = Path(args[0]), Path(args[1])
    if "--articles" in flags:
        articles(db, signals)
        return 0
    with contextlib.redirect_stdout(io.StringIO()):
        state = o1.evaluate(db)
    catalog = load_catalog(Settings(catalog_source="sqlite", catalog_path=db, catalog_signals_path=signals))
    prepared = parts(state, catalog)
    results = state.results
    users = [r.case.user for r in results]
    fold_of = {r.case.user: r.case.fold for r in results}
    strict = {r.case.user for r in results if r.case.strict}
    long_history = {r.case.user for r in results if len(r.case.inputs) > 1}
    selection = [u for u in users if fold_of[u] in SELECT_FOLDS]
    confirmation = [u for u in users if fold_of[u] in CONFIRM_FOLDS]
    selection_parts = [part for part in prepared if part.fold in SELECT_FOLDS]
    formats = Counter(m.format for m in catalog.materials.values() if m.available)
    print(
        f"Каталог: доступных материалов {sum(formats.values())}, из них курсов {formats['course']}, статей "
        f"{formats['article']}. Пользователей {len(users)}: части выбора {len(selection)}, части подтверждения "
        f"{len(confirmation)}; строгий порядок у {len(strict)}; два и более курса в истории у {len(long_history)}.\n"
    )

    chosen, scores = select(state, selection_parts, selection)
    print("## Выбор весов, части 0–2, NDCG@5\n")
    print("| Вес | Значения сетки и NDCG@5 | Отправное | Выбрано |")
    print("| --- | --- | ---: | ---: |")
    for name in GRID:
        cells = "; ".join(f"{fmt(v)} → {fmt(s, 3)}" for v, s in sorted(scores[name].items()))
        print(f"| {LABELS[name]} | {cells} | {fmt(PRIOR[name])} | {fmt(chosen[name])} |")
    print(
        f"\nСобранная конфигурация: {fmt(scores['combined'][0.0], 3)}; лучшая одиночная замена: "
        f"{fmt(scores['combined'][1.0], 3)}; отправная: {fmt(scores['combined'][2.0], 3)}.\n"
    )

    print("## Проверки устройства модели, части 0–2, NDCG@5 при выбранных весах\n")
    plain = run_courses(state, selection_parts, chosen)
    reference = score(plain, selection)
    long_selection = [u for u in selection if u in long_history]
    print(f"Модель: {fmt(reference, 3)}.\n")
    print("| Сходство содержания у курсов с журналом, вес | NDCG@5 | Разница |")
    print("| ---: | ---: | ---: |")
    for weight in CONTENT_ON_COURSES:
        with patched("_score", extra_on_courses("content", weight)):
            value = score(run_courses(state, selection_parts, chosen), selection)
        print(f"| {fmt(weight)} | {fmt(value, 3)} | {pilot.signed(value - reference)} |")
    print()
    print("| Совет редакции у курсов с журналом, вес | NDCG@5 | Разница |")
    print("| ---: | ---: | ---: |")
    for weight in LINK_ON_COURSES:
        with patched("_score", extra_on_courses("continuation", weight)):
            value = score(run_courses(state, selection_parts, chosen), selection)
        print(f"| {fmt(weight)} | {fmt(value, 3)} | {pilot.signed(value - reference)} |")
    print()
    print(f"| Вес глубины: открыл, начал | NDCG@5 | Разница | NDCG@5, два и более курса в истории: {len(long_selection)} |")
    print("| --- | ---: | ---: | ---: |")
    print(f"| без веса | {fmt(reference, 3)} | | {fmt(score(plain, long_selection), 3)} |")
    for view, start in DEPTH_VARIANTS:
        with patched("_co_enrollment", co_enrollment_with_depth):
            places = run_courses(state, selection_parts, chosen, before=depth_of(view, start))
        value = score(places, selection)
        print(
            f"| {fmt(view)}, {fmt(start)} | {fmt(value, 3)} | {pilot.signed(value - reference)} | "
            f"{fmt(score(places, long_selection), 3)} |"
        )
    print()

    product = dict(feed.FEED_WEIGHTS)
    same = all(abs(chosen[name] - product[name]) < 1e-9 for name in CHOSEN_HERE)  # noqa: PLR2004
    # Смешанная лента считается с весами продукта: веса материалов без журнала здесь не выбираются
    shipped = run_mixed(state, prepared, product)
    varied: dict[float, Mixed] = {}
    for value in VARIETY_GRID:
        with patched("_select", select_with_variety(value)):
            varied[value] = run_mixed(state, prepared, product)

    runs = {
        "popularity": baseline(results, "popularity"),
        "coenroll": baseline(results, "coenroll"),
        "prior": run_courses(state, prepared, PRIOR),
        "chosen": run_courses(state, prepared, chosen),
        "shares": run_mixed(state, without_model(prepared), product).places,
        "product": shipped.places,
    }
    names = [
        ("Популярность", "popularity"), ("Совместные записи", "coenroll"), ("Лента, отправные веса", "prior"),
        ("Лента, выбранные веса", "chosen"), ("Лента с долей слушателей вместо модели EASE", "shares"),
        ("Лента продукта: курсы из смешанной ленты", "product"),
    ]
    rows = [(label, runs[key]) for label, key in names]
    print("## Порядок курсов\n")
    table("Части 3–4, в выборе не участвовали", rows, confirmation)
    table("Все части, для справки: части 0–2 участвовали в выборе", rows, users)
    table("Строгий порядок, цель — последний курс", rows, [u for u in users if u in strict])
    table("Случайная скрытая запись", rows, [u for u in users if u not in strict])
    print("Разница на частях 3–4, парный бутстреп:\n")
    print("| Сравнение | hit@1 | hit@5 | NDCG@5 |")
    print("| --- | --- | --- | --- |")
    for label, a, b in (
        ("Выбранные веса и отправные", "chosen", "prior"),
        ("Выбранные веса и совместные записи", "chosen", "coenroll"),
        ("Выбранные веса и популярность", "chosen", "popularity"),
        ("Лента продукта и совместные записи", "product", "coenroll"),
        ("Лента продукта и популярность", "product", "popularity"),
        ("Лента продукта и лента с долей слушателей", "product", "shares"),
    ):
        cells = " | ".join(difference(runs[a], runs[b], confirmation, m) for m in ("hit@1", "hit@5", "NDCG@5"))
        print(f"| {label} | {cells} |")
    print()
    print("Модель EASE против доли слушателей в той же ленте, по группам:\n")
    print("| Группа | hit@1 | hit@5 | NDCG@5 |")
    print("| --- | --- | --- | --- |")
    for label, group in (
        ("Все части", users), ("Части 3–4", confirmation),
        ("Строгий порядок", [u for u in users if u in strict]), ("Случайная скрытая запись", [u for u in users if u not in strict]),
    ):
        cells = " | ".join(difference(runs["product"], runs["shares"], group, m) for m in ("hit@1", "hit@5", "NDCG@5"))
        print(f"| {label}, {len(group)} | {cells} |")
    print()

    print("## Вклад источников: порядок курсов без одного источника, все части\n")
    print("| Без источника | hit@1 | hit@5 | NDCG@5 | Разница NDCG@5 |")
    print("| --- | ---: | ---: | ---: | ---: |")
    full = score(runs["chosen"], users)
    for name in ("co_enrollment", "popularity", "access"):
        places = run_courses(state, prepared, {**chosen, name: 0.0})
        cells = " | ".join(fmt(score(places, users, m)) for m in ("hit@1", "hit@5", "NDCG@5"))
        print(f"| {LABELS[name]} | {cells} | {pilot.signed(score(places, users) - full)} |")
    print()

    print("## Смешанная лента на весь каталог: описание, веса по ней не настраиваются\n")
    shipped_summary = describe(shipped, catalog, users)
    summary = {value: describe(varied[value], catalog, users) for value in VARIETY_GRID}
    print("| Вес разнообразия | NDCG@5 курсов, части 0–2 | NDCG@5 курсов, части 3–4 | Разных тем в первых 10 | Скрытый курс в первых 10 |")
    print("| ---: | ---: | ---: | ---: | ---: |")
    for value, run, row in ((0.0, shipped, shipped_summary), *((v, varied[v], summary[v]) for v in VARIETY_GRID)):
        mark = " (продукт)" if value == 0 else ""
        print(
            f"| {fmt(value)}{mark} | {fmt(score(run.places, selection), 3)} | {fmt(score(run.places, confirmation), 3)} | "
            f"{fmt(row['topics@10'])} | {fmt(row['recall@10'])} |"
        )
    print()
    content_off = describe(run_mixed(state, prepared, {**product, "content": 0.0}), catalog, users)
    last = VARIETY_GRID[-1]
    print(f"| Свойство ленты | Лента продукта | С разнообразием {fmt(last)} | Без сходства содержания |")
    print("| --- | ---: | ---: | ---: |")
    for key, label in DESCRIPTION.items():
        print(f"| {label} | {fmt(shipped_summary[key])} | {fmt(summary[last][key])} | {fmt(content_off[key])} |")
    print()
    print("Веса по правилу: " + "; ".join(f"{LABELS[name]} {fmt(chosen[name])}" for name in CHOSEN_HERE) + ".")
    print("Веса продукта: " + "; ".join(f"{LABELS[name]} {fmt(product[name])}" for name in LABELS) + ".")
    print(f"Веса продукта совпадают с выбранными по правилу: {'да' if same else 'нет'}.")

    if "--card" in flags:
        def block(group: Sequence[str]) -> dict:
            return {
                "users": len(group),
                "methods": {
                    key: {m: round(score(runs[key], group, m), 2) for m in ("hit@1", "hit@5", "NDCG@5")}
                    for key in ("popularity", "coenroll", "product")
                },
            }

        card = {
            "data": "Журнал записей на курсы: у пользователя с двумя и более курсами одна запись скрыта",
            "weights": {name: product[name] for name in LABELS},
            "groups": {
                "strict": block([u for u in users if u in strict]),
                "random": block([u for u in users if u not in strict]),
                "confirmation": block(confirmation),
                "all": block(users),
            },
            "feed": {key: round(value, 2) for key, value in shipped_summary.items()},
        }
        CARD.write_text(json.dumps(card, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"\nПаспорт модели записан: {CARD.relative_to(pilot.PROJECT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
