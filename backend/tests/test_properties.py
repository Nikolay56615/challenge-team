"""Свойства подбора на сгенерированных профилях: Hypothesis над `ranking.policy.recommend()`.

Профиль собирается из значений, которые пропускает схема запроса: задача — пустая, реальная задача тестового
профиля, слова реальных задач, произвольный текст или их смесь; стадия, опыт, формат, сфера, тема и `limit`
из перечислений `schemas.py`; история — события с кодами из каталога и неизвестными кодами, с повторами `seq`.
Каталоги: синтетический с парами курсов, файл фикстур, синтетический вместе с фикстурами и сгенерированные
каталоги с копиями, недоступными материалами и одним форматом в теме. Методы: оба. Явные примеры — тестовые
профили P01–P12, покупка одной из копий M01 и F01 и семь примеров на трёх простых каталогах
(`GENERATED_EXAMPLES`). Поэтому статусы strong, weak, none, cold и empty, маршрут, подбор по истории, правило
разнообразия и копии купленного материала проверяются при любом исходе случайной выборки.

Свойства для каждого профиля:
- не больше `limit` материалов, без повторов, только доступные, ни одной копии купленного материала;
- тот же вход — тот же результат, в том числе в другом процессе с другим PYTHONHASHSEED, вплоть до порядка
  ключей во вкладах и уточнении;
- статус, метод, темы и варианты уточнения — из перечислений схемы ответа;
- каждая фраза причины персональной выдачи — положительный вклад того же признака
  (`test_explain_faithfulness.faithfulness_violations`); у подбора по теме фраза называет тему материала;
- порядок: подбор по теме и стартовая подборка идут по `sort_key`; персональная выдача после окна разнообразия
  идёт по `sort_key`, а в окне выполняется правило `personal._diversify` (см. `diversity_violations`);
- маршрут — только у персональной выдачи со статусом strong и только из первой страницы выдачи.

Hypothesis работает без базы примеров и с `derandomize`: прогон повторяется на той же версии Python, CI на 3.12
повторяет локальный прогон на 3.12. На другой версии выборка иная: строки зависят от её таблицы Unicode.
Контрпример Hypothesis печатает в отчёте pytest уже сжатым.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from typing import get_args

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from app import schemas, vocab
from app.catalog.lexicon import parse_task, title_matches_gaps
from app.catalog.models import Catalog, HistoryEvent, Material
from app.config import BACKEND_DIR
from app.profiles.synthetic import load_profiles
from app.ranking import explain, personal
from app.ranking.base import Context, HistoryIndex, Profile, Scored, sort_key
from app.ranking.policy import METHODS, recommend

from .conftest import catalog_from_payloads, make_profile, read_json
from .test_explain_faithfulness import TITLE_PREFIX, faithfulness_violations

# Примеров на сочетание каталога и метода сверх явных; каждый пример — два вызова recommend(). Мутационное
# тестирование (mutation.yml) уменьшает число через PROPERTY_MAX_EXAMPLES: там свойства проверяют каждого мутанта
MAX_EXAMPLES = int(os.environ.get("PROPERTY_MAX_EXAMPLES", "120"))
PROPERTY_SETTINGS = settings(
    max_examples=MAX_EXAMPLES,
    deadline=None,
    derandomize=True,
    database=None,
    suppress_health_check=[HealthCheck.too_slow],
)
# Задача длиннее рабочего предела MAX_TASK_LENGTH до подбора не доходит: обработчик отвечает 422
TASK_MAX = 300
UNKNOWN_IDS = ("X01", "M99", "F99", "course:404", "m01", "M01-copy")

STAGES = get_args(schemas.StageCode)
EXPERIENCE = get_args(schemas.ExperienceCode)
FORMATS = get_args(schemas.FormatPrefCode)
INDUSTRIES = get_args(schemas.IndustryCode)
TOPICS = get_args(schemas.TopicCode)
EVENTS = get_args(schemas.EventCode)
STATUSES = frozenset(get_args(schemas.StatusCode))

# Слова, на которые откликается разбор задачи: темы, понятия, сферы, стадии, уровни, форматы, пробелы каталога
EXTRA_WORDS = (
    "налоги", "налоговый", "режим", "ИП", "УСН", "декларацию", "штраф", "CRM", "маркетплейс", "Wildberries", "Ozon",
    "реклама", "продвигать", "кофейню", "магазин", "клиентов", "продажи", "нанять", "сотрудника", "команда",
    "финансы", "юнит-экономику", "окупаемость", "сертификат", "лицензия", "алкоголя", "шаблон", "курс", "чек-лист",
    "быстро", "новичок", "растущего", "бизнеса", "открыть", "с", "чего", "начать", "зарегистрировать",
    "контент-план", "интернет-магазина", "экспорт", "договор", "кредит", "займ", "цену", "спрос", "поставщика",
    "склад", "кофе", "стройка", "опытный", "видео", "вебинар", "как", "и", "не", "для",
)


def _task_vocabulary() -> tuple[tuple[str, ...], tuple[str, ...]]:
    tasks = tuple(sorted({demo.task for demo in load_profiles().values() if demo.task}))
    words = {word for task in tasks for word in task.replace(",", " ").replace("?", " ").split()}
    return tasks, tuple(sorted(words | set(EXTRA_WORDS)))


REAL_TASKS, TASK_WORDS = _task_vocabulary()


def task_strategy() -> st.SearchStrategy[str]:
    phrase = st.lists(st.sampled_from(TASK_WORDS), min_size=1, max_size=8).map(" ".join)
    noise = st.text(max_size=40)
    mixed = st.tuples(phrase, noise, phrase).map(" ".join)
    return st.one_of(st.just(""), st.sampled_from(REAL_TASKS), phrase, noise, mixed).map(lambda t: t[:TASK_MAX])


def history_strategy(material_ids: tuple[str, ...]) -> st.SearchStrategy[tuple[HistoryEvent, ...]]:
    ids = st.one_of(st.sampled_from(material_ids), st.sampled_from(UNKNOWN_IDS))
    # Малые seq дают равенства и смену последнего события, большие — края схемы
    seq = st.one_of(st.integers(0, 12), st.integers(0, 1_000_000_000))
    event = st.builds(HistoryEvent, material_id=ids, event=st.sampled_from(EVENTS), seq=seq)
    return st.lists(event, max_size=10).map(tuple)


def optional(values: tuple[str, ...]) -> st.SearchStrategy[str | None]:
    return st.one_of(st.none(), st.sampled_from(values))


def profile_strategy(material_ids: tuple[str, ...], **overrides: st.SearchStrategy) -> st.SearchStrategy[Profile]:
    """Профиль запроса; история — из кодов `material_ids` и неизвестных кодов."""
    fields: dict[str, st.SearchStrategy] = {
        "task": task_strategy(),
        "stage": optional(STAGES),
        "experience": optional(EXPERIENCE),
        "format_pref": optional(FORMATS),
        "industry": optional(INDUSTRIES),
        # Без темы — чаще: тема из списка заменяет темы задачи
        "topic": st.one_of(st.none(), st.none(), st.sampled_from(TOPICS)),
        "history": history_strategy(material_ids),
        "limit": st.integers(1, 10),
    }
    return st.builds(Profile, **{**fields, **overrides})


# Сгенерированный каталог. Код материала — по позиции: G00, G01…; связи «далее» и история берут коды из того же
# пула, коды вне каталога загрузчик и подбор считают неизвестными. Своё название у материала или общее слово:
# у материалов одного формата с общим словом — копии. Вариант «простой каталог»: у каждого материала три темы,
# каждый четвёртый — видео, остальные — статьи, без стадии, уровня, сферы и признаков; оценки близки, статей
# в окне больше трёх, и срабатывает правило разнообразия. Часть материалов недоступна.
GENERATED_IDS = tuple(f"G{n:02d}" for n in range(16))
TITLE_WORDS = ("Как", "найти", "клиентов", "налоги", "чек-лист", "продаж", "CRM", "шаблон", "договора")
CATALOG_TOPICS = ("marketing", "sales", "start")


def _codes(values, size: int) -> st.SearchStrategy[list[str]]:
    return st.lists(st.sampled_from(tuple(values)), max_size=size, unique=True)


def _row(plain: bool) -> st.SearchStrategy[dict]:
    nothing: st.SearchStrategy[list[str]] = st.just([])
    return st.fixed_dictionaries({
        "title": st.one_of(st.none(), st.sampled_from(TITLE_WORDS)),
        "format": st.just(None) if plain else st.sampled_from(sorted(vocab.FORMATS)),
        "topics": st.just(list(CATALOG_TOPICS)) if plain else st.lists(
            st.sampled_from(CATALOG_TOPICS), min_size=1, max_size=2, unique=True
        ),
        "signals": nothing if plain else _codes(vocab.SIGNALS, 2),
        "stage": nothing if plain else _codes(STAGES, 2),
        "level": st.none() if plain else optional(tuple(vocab.LEVELS)),
        "industries": nothing if plain else _codes(INDUSTRIES, 2),
        "duration_minutes": st.one_of(st.none(), st.integers(1, 120)),
        "access": st.sampled_from(tuple(vocab.ACCESS)),
        "available": st.sampled_from((True, True, True, False)),
        "popularity": st.integers(0, 100),
        "recommended_next": st.lists(st.sampled_from(GENERATED_IDS), min_size=1, max_size=3),
    })


def _catalog(rows: list[dict]) -> Catalog:
    materials = []
    for index, row in enumerate(rows):
        material_id = GENERATED_IDS[index]
        fmt = row["format"] or ("video" if index % 4 == 3 else "article")
        materials.append({**row, "id": material_id, "title": row["title"] or f"Материал {material_id}", "format": fmt})
    return catalog_from_payloads({"materials": materials})


# Крошечный каталог бывает целиком недоступен — статус empty; в большом есть выдача и окно разнообразия
GENERATED_CATALOGS = st.one_of(
    st.lists(_row(plain=False), min_size=1, max_size=3),
    st.lists(_row(plain=False), min_size=6, max_size=len(GENERATED_IDS)),
    st.lists(_row(plain=True), min_size=6, max_size=len(GENERATED_IDS)),
).map(_catalog)


def _plain_rows(count: int, unavailable: frozenset[int] = frozenset(), copies: int = 0) -> list[dict]:
    """Простой каталог для явных примеров: популярность убывает по позиции, у видео она нулевая, поэтому без
    правила разнообразия видео шли бы последними; связи «далее» G00 → G01 → G02 дают маршрут. Первые `copies`
    материалов — статьи с одним названием, то есть копии одного материала."""
    return [
        {
            "title": "Чек-лист продаж" if index < copies else None, "format": None, "topics": list(CATALOG_TOPICS),
            "signals": [], "stage": [], "level": None, "industries": [], "duration_minutes": None, "access": "open",
            "available": index not in unavailable, "popularity": 0 if index % 4 == 3 else 100 - index,
            "recommended_next": [GENERATED_IDS[index + 1]] if index < 2 else [],
        }
        for index in range(count)
    ]


def _purchase(material_id: str) -> tuple[HistoryEvent, ...]:
    return (HistoryEvent(material_id, "purchase", 1),)


# Явные примеры: окно разнообразия и маршрут, статус weak по двум темам задачи, стартовая подборка со статусами
# cold и none, статус empty, копии купленного материала. В каталоге копий G00, G01 и G02 — копии, G00 недоступна.
# Покупка доступной G01 или недоступной G00 убирает из выдачи все копии (фильтр допустимости, policy.eligible)
PLAIN_CATALOG = _catalog(_plain_rows(8))
COPIES_CATALOG = _catalog(_plain_rows(8, unavailable=frozenset({0}), copies=3))
GENERATED_EXAMPLES = (
    (PLAIN_CATALOG, Profile(topic="marketing", stage="start", limit=10)),
    (PLAIN_CATALOG, Profile(task="продажи и реклама", limit=10)),
    (PLAIN_CATALOG, Profile()),
    (PLAIN_CATALOG, Profile(task="Как оформить наследство")),
    (_catalog(_plain_rows(2, unavailable=frozenset({0, 1}))), Profile()),
    (COPIES_CATALOG, Profile(topic="marketing", history=_purchase("G01"), limit=10)),
    (COPIES_CATALOG, Profile(topic="marketing", history=_purchase("G00"), limit=10)),
)
# Профиль для сгенерированного каталога: темы каталога, чаще стадия старта и полная страница — так чаще видны
# маршрут и окно разнообразия. Hypothesis чаще выбирает первый вариант из перечисленных
GENERATED_PROFILES = profile_strategy(
    GENERATED_IDS,
    topic=optional(CATALOG_TOPICS),
    stage=st.sampled_from(("start", None, "idea", "growth")),
    limit=st.one_of(st.integers(5, 10), st.integers(1, 10)),
)


@pytest.fixture(scope="session")
def catalogs(catalog) -> dict[str, Catalog]:
    return {
        "synthetic": catalog,
        "fixtures": catalog_from_payloads(read_json("catalog.fixtures.json")),
        "synthetic+fixtures": catalog_from_payloads(
            read_json("catalog.synthetic.json"), read_json("catalog.fixtures.json")
        ),
    }


# Оракулы


def _copy_key(material: Material) -> tuple[str, str]:
    """Копии одного материала: одинаковые название и формат, как в policy.eligible."""
    return " ".join(material.title.casefold().split()), material.format


def _purchased(profile: Profile, catalog: Catalog) -> set[tuple[str, str]]:
    """Ключи копий купленных материалов каталога, в том числе недоступных."""
    return {
        _copy_key(catalog.materials[e.material_id])
        for e in profile.history
        if e.event == "purchase" and e.material_id in catalog.materials
    }


def _label(item: Scored) -> str:
    return f"{item.material.id}({item.material.format}, {item.score})"


def diversity_violations(items: list[Scored]) -> list[str]:
    """Порядок персональной выдачи по правилу `personal._diversify`, проверенный по видимой части выдачи.

    `_diversify` идёт по кандидатам в порядке `sort_key` и заполняет окно из DIVERSITY_WINDOW позиций. На каждом
    шаге он берёт первого из оставшихся — «голову». Если формат головы уже DIVERSITY_MAX_SAME_FORMAT раз есть
    в окне, вместо неё берётся первый из оставшихся материал другого формата с оценкой не ниже оценки лидера
    минус DIVERSITY_SCORE_GAP, если такой есть. После окна оставшиеся идут в порядке `sort_key`. Отсюда
    проверки для позиции i окна; все материалы после i на шаге i были среди оставшихся:
    - если ни один материал после i не идёт раньше него по `sort_key`, он мог быть головой. Тогда при формате,
      уже набравшем предел в окне, после него нет близкого по оценке материала другого формата: иначе взяли бы его;
    - иначе это замена: в окне до i ровно один формат набрал предел, у материала другой формат, оценка не ниже
      порога, а все материалы после i, идущие раньше него по `sort_key`, — того самого формата.
    Лидер — первый материал выдачи: на первом шаге окно пусто и берётся голова.
    """
    found: list[str] = []
    if not items:
        return found
    floor = items[0].score - personal.DIVERSITY_SCORE_GAP
    window = items[: personal.DIVERSITY_WINDOW]
    for i, item in enumerate(window):
        later = items[i + 1 :]
        counts = Counter(s.material.format for s in window[:i])
        ahead = [x for x in later if sort_key(x) < sort_key(item)]
        if not ahead:
            if counts[item.material.format] >= personal.DIVERSITY_MAX_SAME_FORMAT:
                close = [x for x in later if x.material.format != item.material.format and x.score >= floor]
                if close:
                    found.append(f"позиция {i + 1}: {_label(item)} при близкой замене {_label(close[0])}")
            continue
        crowded = [fmt for fmt, n in counts.items() if n >= personal.DIVERSITY_MAX_SAME_FORMAT]
        if (
            len(crowded) != 1
            or item.material.format == crowded[0]
            or item.score < floor
            or any(x.material.format != crowded[0] for x in ahead)
        ):
            found.append(f"позиция {i + 1}: {_label(item)} раньше {_label(ahead[0])} без правила разнообразия")
    tail = items[personal.DIVERSITY_WINDOW :]
    if [sort_key(x) for x in tail] != sorted(sort_key(x) for x in tail):
        found.append("после окна разнообразия порядок не по оценке")
    return found


def order_violations(outcome, method: str) -> list[str]:
    items = outcome.items
    starter = bool(items) and all(item.starter_topic for item in items)
    if method == "personal" and not starter:
        return diversity_violations(items)
    keys = [sort_key(item) for item in items]
    return [] if keys == sorted(keys) else [f"порядок не по оценке: {[_label(i) for i in items]}"]


def baseline_reason_violations(outcome, profile: Profile, catalog: Catalog) -> list[str]:
    """У подбора по теме вкладов нет: фраза называет тему материала или подтверждённое совпадение в названии."""
    gaps = parse_task(profile.task).gaps
    found: list[str] = []
    for item, reasons in zip(outcome.items, outcome.reasons, strict=True):
        material = item.material
        if item.starter_topic:
            if reasons != explain.starter_reasons(item) or item.starter_topic not in material.topics:
                found.append(f"{material.id}: стартовая причина {reasons}")
            continue
        labels = {f"«{vocab.topic_label(t)}»" for t in material.topics}
        if not reasons:
            found.append(f"{material.id}: нет причины")
        for phrase in reasons:
            if phrase.startswith(TITLE_PREFIX):
                if not (gaps and title_matches_gaps(material.title, gaps)):
                    found.append(f"{material.id}: совпадение в названии не подтверждено: {phrase}")
            elif not any(label in phrase for label in labels):
                found.append(f"{material.id}: фраза не называет тему материала: {phrase}")
    return found


def route_violations(outcome, profile: Profile, method: str, catalog: Catalog) -> list[str]:
    route = outcome.route
    if not route:
        return []
    ids = [step.id for step in route]
    window = {item.material.id for item in outcome.items[: min(profile.limit, personal.DIVERSITY_WINDOW)]}
    events: dict[str, set[str]] = {}
    for event in profile.history:
        events.setdefault(event.material_id, set()).add(event.event)
    found: list[str] = []
    if method != "personal" or outcome.status != "strong":
        found.append(f"маршрут при методе {method} и статусе {outcome.status}")
    if not 2 <= len(route) <= explain.ROUTE_MAX_STEPS or len(set(ids)) != len(ids):
        found.append(f"маршрут {ids}")
    if not set(ids) <= window:
        found.append(f"маршрут {ids} вне первой страницы {sorted(window)}")
    for step in route:
        if not step.available or events.get(step.id, set()) & {"complete", "purchase"}:
            found.append(f"шаг {step.id}: недоступен, пройден или куплен")
    for index, step in enumerate(route[1:], start=1):
        if not any(step.id in earlier.recommended_next for earlier in route[:index]):
            found.append(f"шаг {step.id} без редакционной связи")
    return found


def outcome_violations(outcome, profile: Profile, method: str, catalog: Catalog) -> list[str]:
    """Все свойства одного ответа; пустой список — свойства выполнены."""
    ids = [item.material.id for item in outcome.items]
    purchased = _purchased(profile, catalog)
    found: list[str] = []
    if len(ids) > profile.limit:
        found.append(f"{len(ids)} материалов при limit {profile.limit}")
    if len(set(ids)) != len(ids):
        found.append(f"повторы: {ids}")
    for item in outcome.items:
        material = catalog.materials.get(item.material.id)
        if material is None or not material.available:
            found.append(f"недоступный материал {item.material.id}")
        if _copy_key(item.material) in purchased:
            found.append(f"куплен материал или его копия: {item.material.id}")
    if outcome.method != method or outcome.status not in STATUSES:
        found.append(f"метод {outcome.method}, статус {outcome.status}")
    if outcome.status == "empty" and (outcome.items or outcome.clarification):
        found.append("статус empty с выдачей или уточнением")
    if len(outcome.reasons) != len(outcome.items) or outcome.total_candidates < len(outcome.items):
        found.append(f"причин {len(outcome.reasons)}, кандидатов {outcome.total_candidates}, выдача {len(ids)}")
    if not set(outcome.detected_topics) <= set(TOPICS):
        found.append(f"темы вне схемы: {outcome.detected_topics}")
    if outcome.clarification and not {o["value"] for o in outcome.clarification["options"]} <= set(TOPICS):
        found.append(f"варианты уточнения вне схемы: {outcome.clarification['options']}")
    found += order_violations(outcome, method)
    found += route_violations(outcome, profile, method, catalog)
    if method == "personal":
        found += faithfulness_violations(outcome, profile, catalog)
    else:
        found += baseline_reason_violations(outcome, profile, catalog)
    return found


def branches(outcome, profile: Profile, catalog: Catalog) -> set[str]:
    """Статус и пути подбора, которые прошёл ответ, — для проверки охвата выборки."""
    items = outcome.items
    found = {outcome.status}
    # Вход, на котором видно правило копий: у купленного материала есть другая, доступная копия
    purchased = _purchased(profile, catalog)
    bought = {e.material_id for e in profile.history if e.event == "purchase"}
    if any(m.available and m.id not in bought and _copy_key(m) in purchased for m in catalog.materials.values()):
        found.add("копия купленного")
    if items and all(item.starter_topic for item in items):
        return found | {"стартовая"}
    if any(r.startswith(TITLE_PREFIX) for reasons in outcome.reasons for r in reasons):
        found.add("название")
    if any({"co_enrollment", "history_topic"} & set(item.contributions) for item in items):
        found.add("история")
    if outcome.route:
        found.add("маршрут")
    # Порядок не по sort_key даёт только правило разнообразия: замена в окне идёт раньше «головы»
    keys = [sort_key(item) for item in items]
    if keys != sorted(keys):
        found.add("разнообразие")
    return found


STATUS_BRANCHES = {"strong", "weak", "none", "cold", "стартовая"}
# Задача о двух темах файла фикстур, продвижении и команде: статус weak и там, где нет P05
TWO_TOPICS = Profile(task="Как нанять сотрудника и продвигать кофейню", limit=10)
# M01 синтетического каталога и F01 фикстур — копии: одинаковые название и формат. В каталоге синтетики
# с фикстурами покупка F01 убирает из выдачи и M01; в каждом каталоге по отдельности код F01 неизвестен или копий нет
COPY_PURCHASE = Profile(topic="marketing", history=_purchase("F01"), limit=10)
# Пути, которые выборка обязана задеть: иначе свойства проверялись бы не на всех путях подбора
EXPECTED_BRANCHES = {
    ("synthetic", "personal"): STATUS_BRANCHES | {"история", "маршрут"},
    ("synthetic", "baseline"): STATUS_BRANCHES,
    ("fixtures", "personal"): STATUS_BRANCHES,
    ("fixtures", "baseline"): STATUS_BRANCHES,
    ("synthetic+fixtures", "personal"): STATUS_BRANCHES | {"маршрут", "копия купленного"},
    ("synthetic+fixtures", "baseline"): STATUS_BRANCHES | {"копия купленного"},
    ("generated", "personal"): STATUS_BRANCHES | {"empty", "маршрут", "разнообразие", "копия купленного"},
    ("generated", "baseline"): STATUS_BRANCHES | {"empty", "копия купленного"},
}


def check_outcome(catalog: Catalog, profile: Profile, method: str, reached: Counter[str]) -> None:
    outcome = recommend(catalog, profile, method)
    assert outcome_violations(outcome, profile, method, catalog) == []
    # Тот же вход — тот же результат: и тот же объект профиля, и равная ему копия
    assert recommend(catalog, replace(profile), method) == outcome
    reached.update(branches(outcome, profile, catalog))


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("name", ["synthetic", "fixtures", "synthetic+fixtures"])
def test_recommend_properties_on_generated_profiles(catalogs, profiles, name, method):
    """Явные примеры — тестовые профили P01–P12 на первой странице и после «Показать ещё», задача о двух темах
    и покупка копии, затем выборка."""
    catalog = catalogs[name]
    reached: Counter[str] = Counter()

    def check(profile: Profile) -> None:
        check_outcome(catalog, profile, method, reached)

    for demo in profiles.values():
        for limit in (5, 10):
            check = example(profile=make_profile(demo, limit=limit))(check)
    check = example(profile=TWO_TOPICS)(check)
    check = example(profile=COPY_PURCHASE)(check)
    PROPERTY_SETTINGS(given(profile=profile_strategy(tuple(sorted(catalog.materials))))(check))()
    assert set(reached) >= EXPECTED_BRANCHES[name, method], dict(reached)


@pytest.mark.parametrize("method", METHODS)
def test_recommend_properties_on_generated_catalogs(method):
    """Те же свойства на сгенерированных каталогах: копии, недоступные материалы, один формат в теме."""
    reached: Counter[str] = Counter()

    def check(catalog: Catalog, profile: Profile) -> None:
        check_outcome(catalog, profile, method, reached)

    for catalog, profile in GENERATED_EXAMPLES:
        check = example(catalog=catalog, profile=profile)(check)
    PROPERTY_SETTINGS(given(catalog=GENERATED_CATALOGS, profile=GENERATED_PROFILES)(check))()
    assert set(reached) >= EXPECTED_BRANCHES["generated", method], dict(reached)


def test_diversity_oracle_rejects_plain_score_order(catalog):
    """Контроль оракула: порядок без `_diversify` он отвергает, порядок `personal.rank` — принимает."""
    # Пять статей с равной оценкой и видео той же оценки, но наименее популярное: без правила оно шестое
    rows = [
        {"id": f"T{n}", "title": f"Статья {n}", "format": "article", "topics": ["marketing"], "popularity": 50 - n}
        for n in range(5)
    ] + [{"id": "V1", "title": "Видео", "format": "video", "topics": ["marketing"], "popularity": 1}]
    small = catalog_from_payloads({"materials": rows})
    profile = Profile(task="Как продвигать бизнес", limit=10)
    ctx = Context(
        profile=profile, parsed=parse_task(profile.task), topics=("marketing",),
        history=HistoryIndex.build(()), disabled=frozenset(), catalog=small.materials,
    )
    ranked = personal.rank(list(small.materials.values()), ctx)
    plain = sorted(ranked, key=sort_key)
    assert [s.material.id for s in plain] != [s.material.id for s in ranked]
    assert diversity_violations(ranked) == []
    assert diversity_violations(plain)


# Детерминизм между процессами: порядок множеств строк зависит от PYTHONHASHSEED

CROSS_PROCESS_PROFILES = 80
CROSS_PROCESS_SEED = 20261112
CROSS_PROCESS_SCRIPT = """
import json, sys
from app.catalog.loader import load_catalog
from app.catalog.models import HistoryEvent
from app.config import Settings
from app.ranking.base import Profile
from app.ranking.policy import recommend

catalog = load_catalog(Settings())
result = []
for row in json.load(sys.stdin):
    history = tuple(HistoryEvent(*event) for event in row.pop("history"))
    profile = Profile(**row, history=history)
    for method in ("personal", "baseline"):
        outcome = recommend(catalog, profile, method)
        result.append([
            outcome.status, outcome.message, list(outcome.detected_topics), outcome.total_candidates,
            [[i.material.id, i.score, i.contributions, i.flags] for i in outcome.items], outcome.reasons,
            [m.id for m in outcome.route], outcome.clarification,
        ])
json.dump(result, sys.stdout, ensure_ascii=False)
"""


def _cross_process_profiles(catalog: Catalog) -> list[dict]:
    rng = random.Random(CROSS_PROCESS_SEED)
    ids = sorted(catalog.materials) + list(UNKNOWN_IDS)
    rows = []
    for _ in range(CROSS_PROCESS_PROFILES):
        words = rng.sample(TASK_WORDS, rng.randint(1, 6))
        rows.append({
            "task": rng.choice(["", rng.choice(REAL_TASKS), " ".join(words)]),
            "stage": rng.choice((None, *STAGES)),
            "experience": rng.choice((None, *EXPERIENCE)),
            "format_pref": rng.choice((None, *FORMATS)),
            "industry": rng.choice((None, *INDUSTRIES)),
            "topic": rng.choice((None, None, *TOPICS)),
            "history": [[rng.choice(ids), rng.choice(EVENTS), rng.randint(0, 5)] for _ in range(rng.randint(0, 5))],
            "limit": rng.randint(1, 10),
        })
    return rows


def test_outcome_does_not_depend_on_hash_seed(catalog):
    """Сравнивается текст JSON без сортировки ключей: порядок вкладов и полей уточнения тоже часть ответа API."""
    payload = json.dumps(_cross_process_profiles(catalog), ensure_ascii=False)
    outputs = []
    for seed in ("0", "1", "4242"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [sys.executable, "-c", CROSS_PROCESS_SCRIPT], input=payload.encode("utf-8"), capture_output=True,
            cwd=BACKEND_DIR, env=env, timeout=120, check=False,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        outputs.append(result.stdout.decode("utf-8"))
    assert len(json.loads(outputs[0])) == 2 * CROSS_PROCESS_PROFILES
    assert outputs[0] == outputs[1] == outputs[2]
