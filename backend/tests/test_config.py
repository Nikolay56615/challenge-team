"""Настройки из окружения: строгие значения, флаг метрик, порт контейнера, уровни журналов
(docs/plan.md, 4.5; кандидат W12)."""

from __future__ import annotations

import dataclasses
import logging

import pytest
import uvicorn

from app import serve
from app.config import Settings, load_settings
from app.main import create_app

from .conftest import NO_FRONTEND

LOGGERS = ("app", "uvicorn", "uvicorn.error", "uvicorn.access")


def test_defaults_without_environment():
    settings = load_settings({})
    assert settings == Settings()
    assert (settings.catalog_source, settings.demo_mode, settings.log_level, settings.max_task_length) == (
        "synthetic",
        True,
        "info",
        300,
    )
    # Пилот «похожие курсы»: без пути — синтетические пары для synthetic, порог поддержки 10
    assert (settings.catalog_pairs_path, settings.pairs_min_support) == (None, 10)
    # /metrics выключен, пока его не включили явно (кандидат W12)
    assert settings.metrics_enabled is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [("", 10), ("  ", 10), ("1", 1), (" 25 ", 25), ("10", 10), ("1000000", 1_000_000)],
)
def test_pairs_min_support_values(value, expected):
    assert load_settings({"PAIRS_MIN_SUPPORT": value}).pairs_min_support == expected


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("abc", "PAIRS_MIN_SUPPORT должен быть целым числом"),
        ("2.5", "PAIRS_MIN_SUPPORT должен быть целым числом"),
        ("десять", "PAIRS_MIN_SUPPORT должен быть целым числом"),
        ("0", "PAIRS_MIN_SUPPORT должен быть в диапазоне 1–1000000"),
        ("-3", "PAIRS_MIN_SUPPORT должен быть в диапазоне 1–1000000"),
        ("1000001", "PAIRS_MIN_SUPPORT должен быть в диапазоне 1–1000000"),
    ],
)
def test_invalid_pairs_min_support_stops_startup(value, message):
    with pytest.raises(ValueError, match=f"^{message}$"):
        load_settings({"PAIRS_MIN_SUPPORT": value})


def test_pairs_min_support_is_checked_in_settings_too():
    with pytest.raises(ValueError, match="^PAIRS_MIN_SUPPORT должен быть в диапазоне 1–1000000$"):
        Settings(pairs_min_support=0)


@pytest.mark.parametrize(("value", "expected"), [("", None), ("   ", None), (" /data/pairs.json ", "/data/pairs.json")])
def test_catalog_pairs_path_values(value, expected):
    path = load_settings({"CATALOG_PAIRS_PATH": value}).catalog_pairs_path
    assert (None if path is None else path.as_posix()) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("TRUE", True),
        (" yes ", True),
        ("1", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("Off", False),
        ("", True),
        ("  ", True),
    ],
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
    [
        ("true", True),
        ("TRUE", True),
        (" yes ", True),
        ("1", True),
        ("On", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("OFF", False),
        ("", False),
        ("  ", False),
    ],
)
def test_metrics_enabled_values(value, expected):
    # Те же значения, что у DEMO_MODE; пусто — выключено
    assert load_settings({"METRICS_ENABLED": value}).metrics_enabled is expected


@pytest.mark.parametrize("value", ["ture", "enable", "enabled", "2", "-1", "да", "prometheus"])
def test_metrics_enabled_typo_stops_startup(value):
    # Опечатка не должна молча оставить метрики выключенными
    message = "^METRICS_ENABLED должен быть одним из: true, false, 1, 0, yes, no, on, off$"
    with pytest.raises(ValueError, match=message):
        load_settings({"METRICS_ENABLED": value})


def test_metrics_enabled_typo_stops_launcher_before_uvicorn(monkeypatch, capsys):
    def _no_start(*args, **kwargs):
        raise AssertionError("uvicorn не должен запускаться")

    monkeypatch.setattr(uvicorn, "run", _no_start)
    for name in ("CATALOG_SOURCE", "PAIRS_MIN_SUPPORT", "DEMO_MODE", "MAX_TASK_LENGTH", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("METRICS_ENABLED", "ture")
    assert serve.main([]) == serve.CONFIG_ERROR == 1
    error = capsys.readouterr().err
    allowed = "true, false, 1, 0, yes, no, on, off"
    assert error.strip() == f"Запуск остановлен: METRICS_ENABLED должен быть одним из: {allowed}"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("debug", "debug"),
        ("INFO", "info"),
        (" Warning ", "warning"),
        ("error", "error"),
        ("CRITICAL", "critical"),
        ("", "info"),
    ],
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
        (
            {"CATALOG_RELEVANCE": "other"},
            "CATALOG_RELEVANCE должен быть одним из: legacy, task, lexical, hybrid, reranked",
        ),
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


@pytest.mark.parametrize(
    ("name", "level"), [("warning", logging.WARNING), ("debug", logging.DEBUG), ("info", logging.INFO)]
)
def test_log_level_applies_to_app_and_uvicorn_loggers(name, level, restore_log_levels):
    create_app(Settings(log_level=name, frontend_dist=NO_FRONTEND))
    assert {logger: logging.getLogger(logger).level for logger in LOGGERS} == {logger: level for logger in LOGGERS}
