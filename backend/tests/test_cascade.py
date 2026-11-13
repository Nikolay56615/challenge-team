"""Каскад R06 (`personal.COMBINE = "cascade"`, docs/plan.md, раздел 9, решение 2026-11-13).

Режим по умолчанию — взвешенная сумма. Каскад меняет только подбор по истории: без пар в контексте порядок
тот же. Внутри отбора порядок задаёт доля «похожих курсов», затем оценка правил; причины остаются верными.
"""

from __future__ import annotations

import pytest

from app.ranking import personal

from .conftest import ids, make_profile
from .test_explain_faithfulness import faithfulness_violations

P01_P12 = [f"P{n:02d}" for n in range(1, 13)]
POOLS = [8, 12, None]


@pytest.fixture
def cascade_mode(monkeypatch):
    def _set(pool: int | None) -> None:
        monkeypatch.setattr(personal, "COMBINE", "cascade")
        monkeypatch.setattr(personal, "CASCADE_POOL", pool)

    return _set


def test_weighted_sum_is_the_default():
    assert personal.COMBINE == "weighted"


@pytest.mark.parametrize("pool", POOLS)
def test_cascade_changes_only_the_history_mode(run, cascade_mode, pool):
    weighted = {pid: ids(run(pid, limit=10)) for pid in P01_P12}
    cascade_mode(pool)
    assert {pid for pid in P01_P12 if ids(run(pid, limit=10)) != weighted[pid]} == {"P11"}


@pytest.mark.parametrize("pool", POOLS)
def test_pool_is_ordered_by_co_enrollment_then_rules(run, pool):
    items = run("P11", limit=50).items
    ordered = personal.cascade(items, pool)
    size = len(items) if pool is None else pool
    by_rules = sorted(items, key=lambda s: (-personal.rule_score(s), -s.material.popularity, s.material.id))
    head, tail = ordered[:size], ordered[size:]
    assert {s.material.id for s in head} == {s.material.id for s in by_rules[:size]}
    assert tail == by_rules[size:]
    keys = [(-s.contributions.get("co_enrollment", 0.0), -personal.rule_score(s)) for s in head]
    assert keys == sorted(keys)
    assert any(s.contributions.get("co_enrollment", 0.0) > 0 for s in head)


@pytest.mark.parametrize("pool", POOLS)
def test_cascade_reasons_stay_faithful(catalog, profiles, run, cascade_mode, pool):
    cascade_mode(pool)
    outcome = run("P11", limit=10)
    assert faithfulness_violations(outcome, make_profile(profiles["P11"], limit=10), catalog) == []
