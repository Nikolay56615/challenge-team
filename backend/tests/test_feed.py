"""Лента по профилю (`ranking/feed.py`, адреса `/api/feed` и `/api/users`).

Свойства: оценка равна сумме вкладов источников, порядок — по оценке, пройденного в ленте нет, тот же вход
даёт ту же ленту, «что если» согласовано с профилем, у которого событие уже есть или которого нет, причина
о задаче появляется только при введённой задаче. Подбор `/api/recommend` лента не меняет: её каталог
в комплекте — отдельный расширенный набор, а размеченный каталог входит в него без изменений.
Клиенты — вымышленные из комплекта или журнал записей подключённой локальной базы.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.catalog.loader import load_feed_catalog
from app.catalog.models import HistoryEvent
from app.config import Settings
from app.model_card import load_model_card
from app.profiles.clients import Client, Clients, load_json_clients
from app.ranking.base import Profile
from app.ranking.feed import FEED_MAX_LIMIT, FEED_WEIGHTS, LISTENERS_NOTE, SOURCES, _popularity_phrase, build_feed

from .conftest import client_for, error_of, read_json
from .test_sqlite_source import base_tables, write_db

WITH_HISTORY = ["P02", "P06", "P08", "P11", "P12"]
ALL_PROFILES = [f"P{n:02d}" for n in range(1, 13)]
CO_PHRASE = "Этот курс выбрали 48 из 120 слушателей курса «Старт продвижения за 7 дней» из истории клиента"


def feed_of(catalog, history=(), limit=FEED_MAX_LIMIT, **fields):
    return build_feed(catalog, Profile(history=tuple(history), **fields), limit)


def ids(feed) -> list[str]:
    return [entry.scored.material.id for entry in feed.items]


def parts_of(entry) -> dict[str, float]:
    return {part.source: part.value for part in entry.parts}


@pytest.mark.parametrize("profile_id", ALL_PROFILES)
def test_score_is_the_sum_of_source_parts_and_order_follows_it(catalog, profiles, profile_id):
    demo = profiles[profile_id]
    feed = feed_of(catalog, demo.history, task=demo.task, stage=demo.stage, experience=demo.experience)
    known = {code for code, _, _ in SOURCES}
    for entry in feed.items:
        assert {part.source for part in entry.parts} <= known
        assert round(sum(part.value for part in entry.parts), 2) == entry.scored.score
        assert all(part.evidence for part in entry.parts if part.value > 0), entry.scored.material.id
    scores = [entry.scored.score for entry in feed.items]
    assert scores == sorted(scores, reverse=True)
    assert len(set(ids(feed))) == len(feed.items) == feed.total_candidates


@pytest.mark.parametrize("profile_id", WITH_HISTORY)
def test_completed_materials_stay_in_history_only(catalog, profiles, profile_id):
    history = profiles[profile_id].history
    done = {e.material_id for e in history if e.event == "complete"}
    feed = feed_of(catalog, history)
    assert feed.status == "history" and not done & set(ids(feed))
    assert {entry.material_id for entry in feed.history} == {e.material_id for e in history}
    assert feed_of(catalog, history).items == feed.items  # тот же вход — та же лента


def test_p11_feed_explains_itself_by_history(catalog, profiles):
    """Первыми идут курсы, которые выбирали слушатели курса истории; у шаблона причина — содержание."""
    feed = feed_of(catalog, profiles["P11"].history, limit=5)
    by_id = {entry.scored.material.id: entry for entry in feed.items}
    assert ids(feed)[:4] == ["L02", "M02", "M03", "A03"]
    # Вклад считает модель EASE по файлу пар, свидетельством остаётся запись журнала с её счётчиками
    anchor = profiles["P11"].history[0].material_id
    weight = catalog.course_pairs.weight(anchor, "L02")
    assert weight > 0 and parts_of(by_id["L02"])["history"] == round(FEED_WEIGHTS["co_enrollment"] * weight, 2)
    assert by_id["L02"].reason == CO_PHRASE
    notes = {part.source: part.note for part in by_id["L02"].parts}
    assert notes.pop("history") == LISTENERS_NOTE and not any(notes.values())
    assert "content" not in parts_of(by_id["L02"])  # у курса с журналом записей сходство содержания не начисляется
    template = by_id["M03"]
    assert parts_of(template)["links"] == FEED_WEIGHTS["continuation"] and "history" not in parts_of(template)
    assert template.parts[0].source == "popularity" and template.reason.startswith("Похоже на материалы из истории")
    assert feed.interests == [("Продвижение", 1.0)]
    assert {code for code, _ in feed.sources} == {"history", "content", "links", "popularity"}
    stages = "только планирую, недавно начали"  # у пройденного курса две стадии
    assert feed.facts == [("Стадия бизнеса", stages, "выведено из истории"), ("Сфера", None, "не указано")]


def test_listeners_choice_without_model_weights_is_the_share_and_evidence_follows_the_sign(catalog, profiles):
    """Без весов модели вклад равен доле слушателей; вычет и пара ниже порога поддержки чисел не называют."""
    history = profiles["P11"].history
    anchor, pairs = history[0].material_id, catalog.course_pairs

    def card(weights: dict[str, dict[str, float]], code: str = "L02"):
        own = replace(catalog, course_pairs=replace(pairs, weights=weights))
        return next(entry for entry in feed_of(own, history).items if entry.scored.material.id == code)

    plain = card({})
    part = next(part for part in plain.parts if part.source == "history")
    assert part.value == round(FEED_WEIGHTS["co_enrollment"] * 48 / 120, 2) and part.note is None
    assert part.evidence == CO_PHRASE

    lower = next(part for part in card({anchor: {"L02": -0.05}}).parts if part.source == "history")
    assert lower.value == -0.6
    assert lower.evidence.startswith("Слушатели курсов из истории клиента выбирают этот курс реже")

    # Курс без пары от порога поддержки: модель даёт вес, счётчиков во фразе нет
    unpaired = next(
        code for code, m in catalog.materials.items()
        if m.format == "course" and m.available and code != anchor and code not in pairs.neighbours(anchor)
    )
    linked = next(part for part in card({anchor: {unpaired: 0.1}}, unpaired).parts if part.source == "history")
    assert linked.value == 1.2 and linked.evidence.startswith("По журналу записей курс связан с курсом «")
    assert not any(char.isdigit() for char in linked.evidence.replace("7 дней", ""))


def test_difference_of_two_cards_is_the_difference_of_their_parts(catalog, profiles):
    """Панель «Почему эта выше той»: разница оценок раскладывается по источникам без остатка."""
    feed = feed_of(catalog, profiles["P11"].history)
    first, last = feed.items[0], feed.items[-1]
    a, b = parts_of(first), parts_of(last)
    deltas = {source: round(a.get(source, 0.0) - b.get(source, 0.0), 2) for source in a.keys() | b.keys()}
    assert round(sum(deltas.values()), 2) == round(first.scored.score - last.scored.score, 2) > 0


def test_price_is_always_counted_and_follows_the_client(catalog, profiles):
    """Цена учитывается всегда: у платного материала вычет без оплат и надбавка после оплаты; вес 0 её выключает."""
    history = profiles["P11"].history
    free_first = feed_of(catalog, history)
    paid_first = feed_of(catalog, (*history, HistoryEvent("M08", "purchase", 1)))
    weight = FEED_WEIGHTS["access"]
    for feed, expected, start in (
        (free_first, -weight, "Оплаченных записей в истории нет, поэтому оценка материала с доступом «"),
        (paid_first, weight, "В истории есть оплаченная запись, поэтому материал с доступом «"),
    ):
        priced = [entry for entry in feed.items if "access" in parts_of(entry)]
        assert priced and all(entry.scored.material.is_paid for entry in priced)
        assert all(parts_of(e).get("access") == expected for e in feed.items if e.scored.material.is_paid)
        evidence = next(part.evidence for part in priced[0].parts if part.source == "access")
        assert evidence.startswith(start)
    off = build_feed(catalog, Profile(history=history), FEED_MAX_LIMIT, price_weight=0.0)
    assert all("access" not in parts_of(entry) for entry in off.items)


def test_cold_feed_has_no_history_sources(catalog):
    feed = feed_of(catalog)
    assert feed.status == "cold" and feed.history == [] and feed.interests == []
    assert {part.source for entry in feed.items for part in entry.parts} == {"popularity", "access"}
    assert feed.facts == [("Стадия бизнеса", None, "не указано"), ("Сфера", None, "не указано")]


def test_stage_and_industry_change_the_feed_of_a_new_client(feed_catalog):
    """Тип бизнеса участвует в расчёте: ответ анкеты даёт вклад «Анкета» и меняет порядок."""
    cold = feed_of(feed_catalog)
    for fields, word in (({"stage": "growth"}, "стади"), ({"industry": "horeca"}, "сфер")):
        answered = feed_of(feed_catalog, **fields)
        assert ids(answered) != ids(cold)
        first = answered.items[0]
        assert first.parts[0].source == "profile" and word in first.reason


@pytest.mark.parametrize("profile_id", ALL_PROFILES)
def test_task_reason_appears_only_when_a_task_is_given(catalog, profiles, profile_id):
    feed = feed_of(catalog, profiles[profile_id].history)
    assert all(part.source != "task" for entry in feed.items for part in entry.parts)
    assert not any("совпадает с задачей" in (part.evidence or "") for entry in feed.items for part in entry.parts)


def test_task_adds_its_own_source(catalog, profiles):
    """Задача становится ещё одним слагаемым: материал её темы поднимается, главный вклад у него даёт задача."""
    history = profiles["P11"].history
    plain, feed = feed_of(catalog, history), feed_of(catalog, history, task="Какой налоговый режим выбрать?")
    matched = next(entry for entry in feed.items if any(part.source == "task" for part in entry.parts))
    code = matched.scored.material.id
    assert matched.parts[0].source == "task" and "taxes_law" in matched.scored.material.topics
    assert ids(feed).index(code) < ids(plain).index(code)


@pytest.fixture(scope="module")
def feed_catalog(catalog):
    return load_feed_catalog(Settings(), catalog)


@pytest.fixture(scope="module")
def clients():
    return load_json_clients()


def test_feed_catalog_extends_the_labelled_one_without_changing_it(catalog, feed_catalog):
    """Подбор по задаче и его метрики не зависят от расширения: исходные записи и пары стоят в файлах дословно."""
    base, extended = read_json("catalog.synthetic.json"), read_json("catalog.feed.synthetic.json")
    assert extended["materials"][: len(base["materials"])] == base["materials"]
    pairs, more = read_json("course-pairs.synthetic.json"), read_json("course-pairs.feed.synthetic.json")
    assert more["pairs"][: len(pairs["pairs"])] == pairs["pairs"]
    assert feed_catalog.size > 150 and set(catalog.materials) < set(feed_catalog.materials)
    assert all(feed_catalog.materials[code].popularity == m.popularity for code, m in catalog.materials.items())
    assert feed_catalog.disabled_features == ()


def test_every_synthetic_client_gets_a_full_feed_with_exact_scores(feed_catalog, clients):
    segments = {"Начинающий предприниматель", "Малый бизнес с конкретной задачей", "Развивает бизнес системно"}
    assert len(clients) == 24 and {client.segment for client in clients.by_id.values()} == segments
    for client in clients.by_id.values():
        feed = feed_of(feed_catalog, client.history)
        assert feed.status == "history" and len(feed.items) == FEED_MAX_LIMIT, client.id
        assert all(entry.title for entry in feed.history), client.id  # история целиком из каталога ленты
        assert not {e.material_id for e in client.history if e.event == "complete"} & set(ids(feed))
        scores = [entry.scored.score for entry in feed.items]
        assert scores == sorted(scores, reverse=True), client.id
        for entry in feed.items:
            parts = parts_of(entry)
            assert round(sum(parts.values()), 2) == entry.scored.score
            assert all(part.evidence for part in entry.parts), entry.scored.material.id
            # Поведение там, где оно записано; содержание и совет редакции — где журнала нет
            assert not {"history"} & set(parts) or not {"content", "links"} & set(parts), entry.scored.material.id
            assert "history" not in parts or entry.scored.material.format == "course"


def test_courses_follow_content_for_a_client_without_courses_in_history(feed_catalog):
    """Выбору слушателей нужен курс в истории: без него курсы оцениваются по содержанию, как остальные материалы."""
    feed = feed_of(feed_catalog, (HistoryEvent("F046", "view", 1),))
    courses = [entry for entry in feed.items if entry.scored.material.format == "course"]
    assert all("history" not in parts_of(entry) for entry in feed.items)
    assert courses and any("content" in parts_of(entry) for entry in courses)


def test_what_if_matches_a_profile_with_and_without_the_event(feed_catalog, clients):
    history = clients.find("U0239").history
    events = [{"material_id": e.material_id, "event": e.event, "seq": e.seq} for e in history]
    last = max(e.seq for e in history)
    with client_for() as service:
        def post(**body):
            response = service.post("/api/feed", json={"limit": 50, **body})
            assert response.status_code == 200, response.text
            return response.json()

        base = post(user_id="u0239")  # код клиента — без учёта регистра
        explicit = post(history=events)
        without = post(user_id="U0239", exclude_history=["C008"])
        with_added = post(user_id="U0239", add_history=[{"material_id": "C009", "event": "complete", "seq": 1}])
        first_added = post(user_id="U0239", add_history=[{"material_id": "F046", "event": "view", "seq": 0}])
        missing = service.post("/api/feed", json={"user_id": "U9999"})
    as_ids = lambda body: [item["material_id"] for item in body["items"]]  # noqa: E731
    assert as_ids(base) == as_ids(explicit) == ids(feed_of(feed_catalog, history))
    assert base["user"]["id"] == "U0239" and explicit["user"] is None
    assert as_ids(without) == ids(feed_of(feed_catalog, [e for e in history if e.material_id != "C008"]))
    added = (*history, HistoryEvent("C009", "complete", last + 1))
    assert as_ids(with_added) == ids(feed_of(feed_catalog, added)) and "C009" not in as_ids(with_added)
    assert with_added["history"][0]["material_id"] == "C009"  # добавленное событие — последнее в истории
    assert first_added["history"][0]["material_id"] == "F046"  # и при seq 0: оно позже последнего события
    assert missing.status_code == 404 and error_of(missing)["code"] == "not_found"


def test_api_feed_contract(feed_catalog, clients):
    total = feed_of(feed_catalog, clients.find("U0239").history).total_candidates
    with client_for() as service:
        body = service.post("/api/feed", json={"user_id": "U0239", "limit": 5}).json()
        too_many = service.post("/api/feed", json={"limit": FEED_MAX_LIMIT + 1})
        unknown = service.post("/api/feed", json={"method": "baseline"})
    assert body["status"] == "history" and len(body["items"]) == 5 and body["total_candidates"] == total
    assert body["message"] == f"Лента построена по истории. Показаны первые 5 из {total} материалов."
    assert body["catalog"]["size"] == feed_catalog.size
    first = body["items"][0]
    assert first["rank"] == 1 and first["score"] == round(sum(p["value"] for p in first["parts"]), 2)
    assert first["reason"] == first["parts"][0]["evidence"]
    assert body["user"] == {
        "id": "U0239", "label": "U0239 · 3 курса · начинающий предприниматель",
        "segment": "Начинающий предприниматель", "materials": 3, "paid": True,
    }
    assert body["history"][0] == {
        "material_id": "C008", "title": "Курс «Бренд небольшой компании»", "format_label": "Курс",
        "event": "purchase", "event_label": "Куплено",
    }
    shown = [share["source"] for share in body["sources"]]
    assert shown == [code for code, _, _ in SOURCES if code in shown]  # порядок легенды
    measures = [part["evidence"] for item in body["items"] for part in item["parts"] if part["source"] == "popularity"]
    assert measures and all(text.startswith("По популярности ") for text in measures)  # у JSON мера не названа
    assert body["facts"][0]["origin"] == "выведено из истории" and body["facts"][1]["value"] is None
    assert too_many.status_code == 422 and unknown.status_code == 422


def test_users_api_lists_clients_and_finds_them_by_code(clients):
    with client_for() as service, client_for(demo_mode=False) as production:
        listed = service.get("/api/users").json()
        found = service.get("/api/users", params={"q": "u00", "limit": 3}).json()
        exact = service.get("/api/users", params={"q": "u0008"}).json()
        nobody = service.get("/api/users", params={"q": "zzz"}).json()
        bad = service.get("/api/users", params={"q": "нет"})
        assert production.get("/api/users").status_code == 404
        assert production.post("/api/feed", json={"user_id": "U0239"}).status_code == 404
    assert listed["source"] == "synthetic" and listed["total"] == listed["matched"] == len(listed["users"]) == 24
    assert [user["id"] for user in listed["users"]] == list(clients.by_id)
    assert listed["users"][0]["materials"] >= listed["users"][1]["materials"]  # сначала длинная история
    short = [code for code in clients.by_id if code.startswith("U00")]
    assert found["matched"] == len(short) > 3 and [user["id"] for user in found["users"]] == short[:3]
    assert exact["users"][0]["id"] == "U0008" and nobody == {**nobody, "matched": 0, "users": [], "total": 24}
    assert bad.status_code == 422


def test_profiles_from_a_file_open_as_clients_with_their_questionnaire(tmp_path):
    """Персонажи подключённого каталога: профиль с историей — клиент ленты, его анкета участвует в расчёте."""
    personas = {"profiles": [
        {"id": "D01", "label": "Персонаж · первый визит", "task": "", "history": []},
        # Код с пробелом запрос ленты отклонил бы: такой профиль в список клиентов не попадает
        {"id": "D 03", "label": "Код вне правила", "history": [{"material_id": "M08", "event": "view", "seq": 1}]},
        {
            "id": "D02", "label": "Персонаж · после курса", "task": "", "stage": "start", "industry": "horeca",
            "history": [{"material_id": "M08", "event": "complete", "seq": 1}],
        },
    ]}
    path = tmp_path / "personas.json"
    path.write_text(json.dumps(personas, ensure_ascii=False), encoding="utf-8")
    with client_for(demo_profiles_path=path) as service:
        listed = service.get("/api/users").json()
        body = service.post("/api/feed", json={"user_id": "D02", "limit": 50}).json()
    assert [user["id"] for user in listed["users"]][:2] == ["D02", "U0039"] and listed["total"] == 25
    assert [fact["origin"] for fact in body["facts"]] == ["указано в анкете", "указано в анкете"]
    profile_parts = [part for item in body["items"] for part in item["parts"] if part["source"] == "profile"]
    assert profile_parts and all(part["value"] > 0 and part["evidence"] for part in profile_parts)


def test_model_card_describes_the_shipped_weights():
    """Паспорт модели записан оценкой на журнале и относится к весам, с которыми работает лента."""
    assert load_model_card(Path("нет такого файла.json")) is None
    with client_for() as service:
        response = service.get("/api/model-card")
    assert response.status_code == 200, "паспорт не записан: python -X utf8 evaluation/feed_eval.py … --card"
    card = response.json()
    assert [group["code"] for group in card["groups"]] == ["confirmation", "strict", "random"]
    for group in card["groups"]:
        assert [row["method"] for row in group["rows"]] == ["product", "coenroll", "popularity"]
        assert all(0 <= row[metric] <= 1 for row in group["rows"] for metric in ("hit1", "hit5", "ndcg5"))
    assert [entry["value"] for entry in card["weights"]] == list(FEED_WEIGHTS.values())


def test_cold_message_names_what_orders_the_feed():
    """Строка состояния не говорит «первыми идут популярные», когда порядок задаёт анкета."""
    with client_for() as service:
        def message(**body):
            return service.post("/api/feed", json={"limit": 5, **body}).json()["message"]

        plain = message(history=[])
        answered = message(history=[], stage="growth")
        unknown = message(history=[{"material_id": "ZZZ", "event": "view", "seq": 1}])
    assert plain == "Истории нет, поэтому первыми идут популярные материалы. Показаны первые 5 из 165."
    assert answered == "Истории нет, поэтому порядок задают ответы анкеты и популярность. Показаны первые 5 из 165."
    assert unknown.startswith("Материалов из истории нет в каталоге, поэтому первыми идут популярные материалы.")


def test_popularity_phrase_agrees_the_count_and_codes_differ_by_case(catalog):
    article, course = catalog.materials["A01"], catalog.materials["M08"]
    assert _popularity_phrase(article, [0.0] * 31, measured=False).endswith("из 31 материала того же формата")
    assert _popularity_phrase(article, [0.0] * 5, measured=True).endswith("из 5 материалов того же формата")
    assert _popularity_phrase(course, [0.0] * 21, measured=True) == "По числу записей 1-е место из 21 курса"
    # Коды, которые различаются только регистром, остаются разными клиентами
    journal = Clients("sqlite", [Client(code, code, None, ()) for code in ("u-1", "U-1", "u-2")])
    by_code = [client.id if (client := journal.find(code)) else None for code in ("u-1", "U-1", "U-2")]
    assert by_code == ["u-1", "U-1", "u-2"]
    found, matched = journal.search("u-", 10)
    assert matched == 3 and {client.id for client in found} == {"u-1", "U-1", "u-2"}
    assert journal.search("U-1", 10)[0][0].id == "U-1"


def test_connected_base_serves_its_course_log_as_clients(tmp_path):
    """Локальная база: клиенты — её журнал записей без удалённых строк, сначала с длинной историей."""
    db = write_db(tmp_path / "copy.sqlite3", base_tables())
    with client_for(catalog_source="sqlite", catalog_path=db) as service:
        listed = service.get("/api/users").json()
        feed = service.post("/api/feed", json={"user_id": "u-1"}).json()
    assert listed["source"] == "sqlite" and [user["id"] for user in listed["users"]] == ["u-1", "u-2", "u-3"]
    assert listed["users"][0] == {"id": "u-1", "label": "u-1 · 2 курса", "segment": None, "materials": 2, "paid": False}
    assert [entry["material_id"] for entry in feed["history"]] == ["course:C-203", "course:C-201"]
    assert feed["status"] == "history" and feed["user"]["id"] == "u-1"
    # Выгрузка сама считает популярность, и подпись называет меру: записи у курсов, редакционные ссылки у остальных
    measures = {
        (item["format"] == "course", part["evidence"].split(" место ")[0].rsplit(" ", 1)[0])
        for item in feed["items"] for part in item["parts"] if part["source"] == "popularity"
    }
    assert measures == {(True, "По числу записей"), (False, "По числу редакционных ссылок")}
