"""Видимость статей для MVP на вымышленной мини-базе.

Протокол записан до первого прогона. Текущая видимость сохраняется: `IsPublic = 0` убирает статью из
списка как редакционный фильтр, `IsClosed = 1` и статус не «Опубликовано» скрывают её. Приватный тип
доступа (`hidden_access_titles`, в копии «Закрытый») скрывает материал. Тип статьи сверяется с её записью
`ContentSettings`, при расхождении действует более строгий: приватный строже платного.

База — мини-каталог из test_sqlite_source.py и восемь вымышленных статей темы «Маркетинг». Каждый видимый
материал темы ссылается сначала на обе приватные статьи, затем на остальные видимые. Поэтому приватные
статьи самые популярные по входящим ссылкам, а A-707 ещё и открыта по настройкам. Ожидания:
- A-701 по подписке: в выдаче, доступ subscription, платная пометка «По подписке»;
- A-702 платная: в выдаче, доступ paid, пометка «Платно»;
- A-703, приватная по настройкам, и A-707, приватная по типу статьи: недоступны, нет в выдаче по теме и
  в стартовой подборке; без скрытия A-707 стала бы стартовой карточкой темы; причина private — 3 с A-105 базы;
- A-704 с IsClosed = 1: скрыта, причина flags — 6 с пятью скрытыми флагами базы;
- A-705 со статусом «Черновик» в таблице статьи: скрыта, причина status — 3 с двумя черновиками базы;
- A-706, платный тип статьи при открытых настройках: в выдаче с доступом paid; конфликтов 4: два курса базы,
  A-101 базы и A-706; неизвестных типов 0;
- переходы: после пройденной A-708 продолжение получают все видимые материалы темы, маршрут строится,
  приватные цели связей не попадают ни в выдачу, ни в маршрут.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app import vocab
from app.catalog.models import Catalog, HistoryEvent, Material
from app.catalog.sqlite_source import load_sqlite_catalog
from app.ranking.base import Profile
from app.ranking.policy import Outcome, recommend

from .test_sqlite_source import Table, base_tables, with_rows, write_db

# Id статьи: (статус статьи, IsClosed, тип статьи, тип в ContentSettings); у всех IsPublic = 1
ARTICLES: dict[str, tuple[str, int, str, str]] = {
    "A-701": ("st-pub", 0, "ty-sub", "ty-sub"),  # по подписке
    "A-702": ("st-pub", 0, "ty-paid", "ty-paid"),  # платная
    "A-703": ("st-pub", 0, "ty-closed", "ty-closed"),  # приватная
    "A-704": ("st-pub", 1, "ty-open", "ty-open"),  # закрытая
    "A-705": ("st-draft", 0, "ty-open", "ty-open"),  # неопубликованная
    "A-706": ("st-pub", 0, "ty-paid", "ty-open"),  # конфликт: платный тип статьи
    "A-707": ("st-pub", 0, "ty-closed", "ty-open"),  # конфликт: приватный тип статьи
    "A-708": ("st-pub", 0, "ty-open", "ty-open"),  # открытая
}
PRIVATE_REFS = ("A-703", "A-707")
VISIBLE_REFS = ("W-401", "A-701", "A-702", "A-706", "A-708")  # W-401 — вебинар темы из базы
PRIVATE = frozenset(f"article:{ref}" for ref in PRIVATE_REFS)
VISIBLE = frozenset(("webinar:" if ref.startswith("W") else "article:") + ref for ref in VISIBLE_REFS)


def visibility_tables() -> dict[str, Table]:
    links = [
        (source, target, "7", order)
        for source in VISIBLE_REFS
        for order, target in enumerate((*PRIVATE_REFS, *(ref for ref in VISIBLE_REFS if ref != source)))
    ]
    return with_rows(
        base_tables(),
        Articles=[
            (ref, status, "5 минут", None, f"Вымышленная статья {ref[2:]}", 0, 1, closed, own)
            for ref, (status, closed, own, _) in ARTICLES.items()
        ],
        ContentSettings=[(f"cs-{ref[2:]}", ref, "9", "st-pub", 0, cs) for ref, (*_, cs) in ARTICLES.items()],
        ContentSettingsTopics=[(f"cs-{ref[2:]}", "tp-mkt", 0) for ref in ARTICLES],
        RecommendedItems=links,
    )


@pytest.fixture(scope="module")
def visibility(tmp_path_factory: pytest.TempPathFactory) -> Catalog:
    path: Path = tmp_path_factory.mktemp("visibility") / "catalog.sqlite3"
    return load_sqlite_catalog(write_db(path, visibility_tables()))


def topic_items(catalog: Catalog) -> dict[str, Material]:
    outcome = recommend(catalog, Profile(topic="marketing", limit=10))
    assert outcome.total_candidates == len(VISIBLE)
    return {item.material.id: item.material for item in outcome.items}


def starter_picks(outcome: Outcome) -> dict[str | None, str]:
    assert outcome.status == "cold"
    return {item.starter_topic: item.material.id for item in outcome.items}


def test_subscription_article_is_shown_as_paid(visibility):
    material = topic_items(visibility)["article:A-701"]
    assert (material.access, material.is_paid, vocab.ACCESS[material.access]) == ("subscription", True, "По подписке")


def test_paid_article_is_shown(visibility):
    material = topic_items(visibility)["article:A-702"]
    assert (material.access, material.is_paid, vocab.ACCESS[material.access]) == ("paid", True, "Платно")


def test_private_article_is_hidden_from_ranking_and_starter(visibility):
    assert not any(visibility.materials[key].available for key in PRIVATE)
    assert visibility.coverage["unavailable_by_reason"]["private"] == 3  # A-703, A-707 и A-105 базы
    assert set(topic_items(visibility)) == VISIBLE
    assert starter_picks(recommend(visibility, Profile(limit=10)))["marketing"] == "article:A-708"
    # Контроль: без скрытия самая популярная открытая статья темы стала бы стартовой карточкой
    shown = replace(visibility.materials["article:A-707"], available=True)
    control = replace(visibility, materials={**visibility.materials, shown.id: shown})
    assert starter_picks(recommend(control, Profile(limit=10)))["marketing"] == "article:A-707"


def test_closed_article_is_hidden(visibility):
    assert not visibility.materials["article:A-704"].available
    assert "article:A-704" not in topic_items(visibility)
    assert visibility.coverage["unavailable_by_reason"]["flags"] == 6


def test_unpublished_article_is_hidden(visibility):
    assert not visibility.materials["article:A-705"].available
    assert "article:A-705" not in topic_items(visibility)
    assert visibility.coverage["unavailable_by_reason"]["status"] == 3


def test_stricter_type_wins_on_conflict(visibility):
    assert topic_items(visibility)["article:A-706"].access == "paid"  # платный тип статьи, открытые настройки
    assert visibility.materials["article:A-707"].available is False  # приватный тип статьи, открытые настройки
    assert visibility.materials["article:A-101"].access == "paid"  # то же расхождение в статье базы
    assert visibility.coverage["access_mapping"] == {"unknown": 0, "conflicts": 4}


def test_private_is_never_a_transition(visibility):
    assert all(set(visibility.materials[key].recommended_next[:2]) == PRIVATE for key in VISIBLE)
    history = (HistoryEvent("article:A-708", "complete", 1),)
    outcome = recommend(visibility, Profile(topic="marketing", stage="start", history=history, limit=10))
    continued = {item.material.id for item in outcome.items if item.continuation_of == "article:A-708"}
    assert continued == VISIBLE - {"article:A-708"}
    assert len(outcome.route) >= 2  # маршрут из видимых материалов строится
    assert not PRIVATE & ({item.material.id for item in outcome.items} | {m.id for m in outcome.route})
