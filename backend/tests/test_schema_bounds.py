"""Границы схемы запроса: значение на границе проходит, на единицу дальше — 422.

Пределы — договорённость контракта, поэтому в тестах они записаны числами, а не константами из `schemas.py`:
изменённая константа должна провалить тест. Границы проверяются на модели pydantic, путь через HTTP проверяет
test_schemathesis.py. Границы: код материала из 1 и 64 символов, `seq` 0 и 10⁹, `profile_id` из 16 символов,
`limit` 1 и 10, задача из 2000 символов, история из 200 событий. Целые — по правилам JSON Schema:
8.0 — целое, строка "8" и логическое значение — нет.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import HistoryEventIn, RecommendRequest

from .conftest import client_for, error_of


def event(material_id: str = "M01", seq: object = 1, kind: str = "view") -> dict:
    return {"material_id": material_id, "event": kind, "seq": seq}


# Запрос → принят ли он схемой. Задача длиннее рабочего предела MAX_TASK_LENGTH проходит схему,
# поэтому сервис в HTTP-проверке запускается с MAX_TASK_LENGTH = 2000
CASES = {
    "material_id из 1 символа": ({"history": [event("M")]}, True),
    "material_id из 64 символов": ({"history": [event("M" * 64)]}, True),
    "material_id из 65 символов": ({"history": [event("M" * 65)]}, False),
    "пустой material_id": ({"history": [event("")]}, False),
    "material_id с пробелом": ({"history": [event("M 1")]}, False),
    "seq 0": ({"history": [event(seq=0)]}, True),
    "seq -1": ({"history": [event(seq=-1)]}, False),
    "seq 1 000 000 000": ({"history": [event(seq=1_000_000_000)]}, True),
    "seq 1 000 000 001": ({"history": [event(seq=1_000_000_001)]}, False),
    "seq 1.0": ({"history": [event(seq=1.0)]}, True),
    "seq 1.5": ({"history": [event(seq=1.5)]}, False),
    "seq false": ({"history": [event(seq=False)]}, False),
    "seq true": ({"history": [event(seq=True)]}, False),
    "seq строкой": ({"history": [event(seq="1")]}, False),
    "profile_id из 16 символов": ({"profile_id": "P" * 16}, True),
    "profile_id из 17 символов": ({"profile_id": "P" * 17}, False),
    "limit 0": ({"limit": 0}, False),
    "limit 1": ({"limit": 1}, True),
    "limit 10": ({"limit": 10}, True),
    "limit 11": ({"limit": 11}, False),
    "limit 8.0": ({"limit": 8.0}, True),
    "limit строкой": ({"limit": "5"}, False),
    "limit true": ({"limit": True}, False),
    "задача из 2000 символов": ({"task": "я" * 2000}, True),
    "задача из 2001 символа": ({"task": "я" * 2001}, False),
    "история из 200 событий": ({"history": [event(seq=i) for i in range(200)]}, True),
    "история из 201 события": ({"history": [event(seq=i) for i in range(201)]}, False),
}


@pytest.mark.parametrize("name", list(CASES))
def test_schema_boundary_on_the_model(name):
    body, valid = CASES[name]
    if valid:
        RecommendRequest.model_validate(body)
    else:
        with pytest.raises(ValidationError):
            RecommendRequest.model_validate(body)


@pytest.fixture(scope="module")
def service():
    with client_for(max_task_length=2000) as client:
        yield client


def test_accepted_limit_and_seq_are_integers():
    request = RecommendRequest.model_validate({"limit": 8.0, "history": [event(seq=3.0)]})
    assert request.limit == 8 and type(request.limit) is int
    assert request.history is not None and type(request.history[0].seq) is int


@pytest.mark.parametrize(
    ("body", "loc"),
    [
        ({"limit": "5"}, ("limit",)),
        ({"limit": True}, ("limit",)),
        ({"history": [event(seq="1")]}, ("history", 0, "seq")),
        ({"history": [event(seq=False)]}, ("history", 0, "seq")),
    ],
)
def test_wrong_integer_type_is_int_type(body, loc):
    """`json_integer` отвечает той же ошибкой, что pydantic на нецелое: тип int_type и его текст."""
    with pytest.raises(ValidationError) as caught:
        RecommendRequest.model_validate(body)
    assert [(e["type"], e["loc"], e["msg"]) for e in caught.value.errors()] == [
        ("int_type", loc, "Input should be a valid integer")
    ]


def test_wrong_integer_type_is_reported_on_the_field(service):
    details = error_of(service.post("/api/recommend", json={"history": [event(seq=False)]}))["details"]
    assert details == [{"field": "history.0.seq", "message": "Неверное значение поля «история»"}]
    limit = error_of(service.post("/api/recommend", json={"limit": "5"}))
    assert limit["details"] == [{"field": "limit", "message": "Число материалов должно быть от 1 до 10"}]


def test_default_limit_is_five(service):
    assert RecommendRequest.model_validate({}).limit == 5
    body = service.post("/api/recommend", json={"task": "Как продвигать бизнес"}).json()
    assert len(body["items"]) == 5 and body["total_candidates"] > 5


def test_history_event_model_alone():
    assert HistoryEventIn.model_validate(event("A" * 64, 0)).seq == 0
    with pytest.raises(ValidationError):
        HistoryEventIn.model_validate(event(seq="0"))
