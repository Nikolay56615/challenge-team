"""Настройки из окружения: строгие значения, порт контейнера, уровни журналов (PLAN.md, 4.5)."""

from __future__ import annotations

import dataclasses
import logging

import pytest

from app.config import Settings, load_settings
from app.main import create_app

from .conftest import NO_FRONTEND

LOGGERS = ("app", "uvicorn", "uvicorn.error", "uvicorn.access")


def test_defaults_without_environment():
    settings = load_settings({})
    assert settings == Settings()
    assert (settings.catalog_source, settings.demo_mode, settings.log_level, settings.max_task_length) == (
        "synthetic", True, "info", 300
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), ("TRUE", True), (" yes ", True), ("1", True), ("on", True),
     ("false", False), ("0", False), ("no", False), ("Off", False), ("", True), ("  ", True)],
)
def test_demo_mode_values(value, expected):
    assert load_settings({"DEMO_MODE": value}).demo_mode is expected


@pytest.mark.parametrize("value", ["flase", "ture", "enabled", "2", "да"])
def test_demo_mode_typo_stops_startup(value):
    # Раньше опечатка молча выключала демо-режим: пропадали тестовые профили и сравнение
    with pytest.raises(ValueError, match="^DEMO_MODE должен быть одним из: true, false, 1, 0, yes, no, on, off$"):
        load_settings({"DEMO_MODE": value})


@pytest.mark.parametrize(
    ("value", "expected"),
    [("debug", "debug"), ("INFO", "info"), (" Warning ", "warning"), ("error", "error"), ("CRITICAL", "critical"),
     ("", "info")],
)
def test_log_level_values(value, expected):
    assert load_settings({"LOG_LEVEL": value}).log_level == expected


@pytest.mark.parametrize("value", ["verbose", "warn", "trace", "10"])
def test_log_level_typo_stops_startup(value):
    with pytest.raises(ValueError, match="^LOG_LEVEL должен быть одним из: debug, info, warning, error, critical$"):
        load_settings({"LOG_LEVEL": value})
    with pytest.raises(ValueError, match="^LOG_LEVEL"):
        Settings(log_level=value)


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"MAX_TASK_LENGTH": "abc"}, "MAX_TASK_LENGTH должен быть целым числом"),
        ({"MAX_TASK_LENGTH": "2001"}, "MAX_TASK_LENGTH должен быть в диапазоне 1–2000"),
        ({"CATALOG_SOURCE": "sqllite"}, "CATALOG_SOURCE должен быть одним из: synthetic, sqlite, file"),
        ({"CATALOG_RELEVANCE": "other"}, "CATALOG_RELEVANCE должен быть одним из: legacy, task, lexical, hybrid"),
    ],
)
def test_other_invalid_values_name_the_variable(env, message):
    with pytest.raises(ValueError, match=f"^{message}$"):
        load_settings(env)


def test_app_port_is_not_read_by_the_app():
    # В контейнере сервис всегда слушает 8000; APP_PORT — только порт на машине пользователя в compose
    assert "app_port" not in {f.name for f in dataclasses.fields(Settings)}
    assert load_settings({"APP_PORT": "not-a-port"}) == Settings()


def test_task_relevance_is_opt_in():
    assert load_settings({}).catalog_relevance == "legacy"
    assert load_settings({"CATALOG_RELEVANCE": " Task "}).catalog_relevance == "task"


@pytest.mark.parametrize(("name", "level"), [("warning", logging.WARNING), ("debug", logging.DEBUG), ("info", logging.INFO)])
def test_log_level_applies_to_app_and_uvicorn_loggers(name, level, restore_log_levels):
    create_app(Settings(log_level=name, frontend_dist=NO_FRONTEND))
    assert {logger: logging.getLogger(logger).level for logger in LOGGERS} == {logger: level for logger in LOGGERS}
