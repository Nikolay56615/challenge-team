"""Свойства маршрута на первую неделю на синтетическом каталоге (docs/plan.md, 3.6; кандидат R13).

Проверяются свойства, а не коды: в маршруте нет пройденного и купленного, ни один формат не
встречается трижды, шаги — доступные материалы первой страницы, связанные редакционным «далее».
Профили — P01–P10 на первой странице и после «Показать ещё», те же профили после «Отметить
изученным» для каждого шага маршрута и выборка стартовых анкет.
"""

from __future__ import annotations

import random
from collections import Counter

import pytest

from app import vocab
from app.catalog.lexicon import parse_task
from app.catalog.models import HistoryEvent
from app.ranking import explain, personal
from app.ranking.base import HistoryIndex, Profile
from app.ranking.metrics import FULL_ROUTE_STEPS, full_route_share
from app.ranking.policy import eligible, recommend

from .conftest import make_profile

PROFILE_IDS = [f"P{n:02d}" for n in range(1, 11)]
GRID_SIZE = 300
GRID_SEED = 20261111
START_TASKS = (
    "Хочу начать продвигать свою кофейню, с чего начать?",
    "Хочу открыть магазин, с чего начать",
    "Как найти первых клиентов",
    "Какой налоговый режим выбрать для ИП",
    "Как сдать декларацию и не получить штраф",
    "Какую CRM выбрать",
    "Как зарегистрировать бизнес",
    "Как навести порядок в задачах",
)


def route_expected(profile: Profile, status: str) -> bool:
    """Маршрут положен при статусе strong и стадии idea или start, в том числе по подсказке из текста.

    Повторяет условие `policy._start_like` и статус из docs/plan.md, 3.6.
    """
    hint = parse_task(profile.task).stage_hint
    start_like = profile.stage in {"idea", "start"} or (profile.stage is None and hint == "start")
    return status == "strong" and start_like


def route_violations(catalog, profile: Profile, outcome) -> list[str]:
    """Нарушения свойств маршрута; пустой список — свойства выполнены."""
    route = outcome.route
    ids = [step.id for step in route]
    history = HistoryIndex.build(profile.history)
    window = {item.material.id for item in outcome.items[: min(profile.limit, personal.DIVERSITY_WINDOW)]}
    pool = {material.id for material in eligible(catalog, history)}
    found: list[str] = []
    if route and not route_expected(profile, outcome.status):
        found.append(f"маршрут при статусе {outcome.status} и стадии {profile.stage}")
    if route and not 2 <= len(route) <= explain.ROUTE_MAX_STEPS:
        found.append(f"длина {len(route)}")
    if len(set(ids)) != len(ids):
        found.append(f"повтор шага {ids}")
    for step in route:
        events = history.of(step.id)
        if "complete" in events:
            found.append(f"пройденный шаг {step.id}")
        if "purchase" in events:
            found.append(f"купленный шаг {step.id}")
        if not catalog.materials[step.id].available or step.id not in pool:
            found.append(f"недоступный шаг {step.id}")
        if step.id not in window:
            found.append(f"шаг {step.id} вне первой страницы")
    formats = Counter(step.format for step in route)
    if formats and max(formats.values()) >= 3:
        found.append(f"формат трижды: {dict(formats)}")
    for index, step in enumerate(route[1:], start=1):
        if not any(step.id in earlier.recommended_next for earlier in route[:index]):
            found.append(f"шаг {step.id} без редакционной связи")
    return found


def test_full_route_steps_match_the_route_builder():
    assert FULL_ROUTE_STEPS == explain.ROUTE_MAX_STEPS


@pytest.mark.parametrize("limit", [5, 10])
@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_route_properties_for_test_profiles(catalog, profiles, profile_id, limit):
    profile = make_profile(profiles[profile_id], limit=limit)
    outcome = recommend(catalog, profile, "personal")
    assert route_violations(catalog, profile, outcome) == []


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_marking_a_route_step_studied_removes_it_from_the_route(catalog, profiles, profile_id):
    """«Отметить изученным» добавляет событие complete: шаг уходит из маршрута, свойства сохраняются."""
    profile = make_profile(profiles[profile_id])
    route = recommend(catalog, profile, "personal").route
    next_seq = max((event.seq for event in profile.history), default=0) + 1
    for step in route:
        studied = make_profile(
            profiles[profile_id], history=(*profile.history, HistoryEvent(step.id, "complete", next_seq))
        )
        outcome = recommend(catalog, studied, "personal")
        assert step.id not in {m.id for m in outcome.route}
        assert route_violations(catalog, studied, outcome) == []


def test_route_properties_on_a_start_profile_grid(catalog):
    rng = random.Random(GRID_SEED)
    histories = (
        (),
        (HistoryEvent("M01", "view", 1),),
        (HistoryEvent("M01", "complete", 1),),
        (HistoryEvent("M08", "start", 1),),
        (HistoryEvent("L01", "complete", 1), HistoryEvent("A01", "view", 2)),
        (HistoryEvent("M04", "purchase", 1),),
    )
    routes = 0
    violations: list[str] = []
    for _ in range(GRID_SIZE):
        profile = Profile(
            task=rng.choice(START_TASKS),
            stage=rng.choice((None, "idea", "start")),
            experience=rng.choice((None, *vocab.EXPERIENCE)),
            format_pref=rng.choice((None, *vocab.FORMAT_PREFS)),
            industry=rng.choice((None, "horeca", "retail", "ecom")),
            history=rng.choice(histories),
            limit=rng.choice((3, 5, 10)),
        )
        outcome = recommend(catalog, profile, "personal")
        routes += bool(outcome.route)
        violations.extend(f"{profile}: {v}" for v in route_violations(catalog, profile, outcome))
    assert routes > GRID_SIZE // 4, "в выборке мало маршрутов"
    assert violations == []


def test_full_route_share_on_test_profiles(catalog, profiles):
    """Метрика R13: доля профилей с полным маршрутом среди тех, кому маршрут положен.

    Порог — текущее значение на синтетике; расширение маршрута может его только поднять.
    """
    lengths = []
    for demo in profiles.values():
        profile = make_profile(demo)
        outcome = recommend(catalog, profile, "personal")
        if route_expected(profile, outcome.status):
            lengths.append(len(outcome.route))
        else:
            assert outcome.route == []
    assert lengths, "среди P01–P10 нет профилей, которым положен маршрут"
    share = full_route_share(lengths)
    assert share is not None and share >= 1 / 3
