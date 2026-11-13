"""Настройки из переменных окружения (docs/plan.md, 4.5).

Приложение читает только окружение процесса; файл `.env` читает docker compose. Порт задаёт
команда запуска uvicorn: в контейнере сервис всегда слушает 8000, а `APP_PORT` в compose —
порт на машине пользователя. Пустая переменная означает значение по умолчанию, неверное
значение останавливает запуск с сообщением, в котором названа переменная.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data"
DEFAULT_FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"

CATALOG_SOURCES = ("synthetic", "sqlite", "file")
CATALOG_RELEVANCE_MODES = ("legacy", "task", "lexical", "hybrid", "reranked")
LOG_LEVELS = ("debug", "info", "warning", "error", "critical")
FLAGS = {"true": True, "false": False, "1": True, "0": False, "yes": True, "no": False, "on": True, "off": False}
# Порог поддержки пары совместных записей: пара с меньшим числом общих слушателей не загружается
# (пилот «похожие курсы», docs/plan.md, раздел 9, решение 2026-11-11)
PAIRS_MIN_SUPPORT_DEFAULT = 10
PAIRS_MIN_SUPPORT_MAX = 1_000_000


def _choice(value: str | None, default: str, name: str, allowed: tuple[str, ...]) -> str:
    if value is None or value.strip() == "":
        return default
    choice = value.strip().lower()
    if choice not in allowed:
        raise ValueError(f"{name} должен быть одним из: {', '.join(allowed)}")
    return choice


def _flag(value: str | None, default: bool, name: str) -> bool:
    return FLAGS[_choice(value, str(default).lower(), name, tuple(FLAGS))]


def _path(value: str | None) -> Path | None:
    if value is None or value.strip() == "":
        return None
    return Path(value.strip())


def _int(value: str | None, default: int, name: str, low: int, high: int) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        number = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} должен быть целым числом") from exc
    if not low <= number <= high:
        raise ValueError(f"{name} должен быть в диапазоне {low}–{high}")
    return number


@dataclass(frozen=True, slots=True)
class Settings:
    catalog_source: str = "synthetic"
    catalog_path: Path | None = None
    catalog_signals_path: Path | None = None
    catalog_mapping: Path | None = None
    # Пары совместных записей на курсы. Пусто: для synthetic — data/course-pairs.synthetic.json,
    # для sqlite и file признак «похожие курсы» отключён (catalog/loader.py)
    catalog_pairs_path: Path | None = None
    pairs_min_support: int = PAIRS_MIN_SUPPORT_DEFAULT
    demo_mode: bool = True
    max_task_length: int = 300
    # GET /metrics в формате Prometheus; выключено — адреса нет и счётчики не ведутся (кандидат W12)
    metrics_enabled: bool = False
    log_level: str = "info"
    frontend_dist: Path = DEFAULT_FRONTEND_DIST
    catalog_relevance: str = "legacy"
    catalog_search_dir: Path | None = None
    catalog_model_dir: Path | None = None
    catalog_search_policy: Path | None = None
    catalog_rerank_dir: Path | None = None
    catalog_rerank_model_dir: Path | None = None
    catalog_rerank_encoder_dir: Path | None = None
    catalog_rerank_policy: Path | None = None

    def __post_init__(self) -> None:
        if self.log_level not in LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL должен быть одним из: {', '.join(LOG_LEVELS)}")
        if not 1 <= self.pairs_min_support <= PAIRS_MIN_SUPPORT_MAX:
            raise ValueError(f"PAIRS_MIN_SUPPORT должен быть в диапазоне 1–{PAIRS_MIN_SUPPORT_MAX}")


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    return Settings(
        catalog_source=_choice(env.get("CATALOG_SOURCE"), "synthetic", "CATALOG_SOURCE", CATALOG_SOURCES),
        catalog_path=_path(env.get("CATALOG_PATH")),
        catalog_signals_path=_path(env.get("CATALOG_SIGNALS_PATH")),
        catalog_mapping=_path(env.get("CATALOG_MAPPING")),
        catalog_pairs_path=_path(env.get("CATALOG_PAIRS_PATH")),
        pairs_min_support=_int(
            env.get("PAIRS_MIN_SUPPORT"), PAIRS_MIN_SUPPORT_DEFAULT, "PAIRS_MIN_SUPPORT", 1, PAIRS_MIN_SUPPORT_MAX
        ),
        demo_mode=_flag(env.get("DEMO_MODE"), True, "DEMO_MODE"),
        max_task_length=_int(env.get("MAX_TASK_LENGTH"), 300, "MAX_TASK_LENGTH", 1, 2000),
        metrics_enabled=_flag(env.get("METRICS_ENABLED"), False, "METRICS_ENABLED"),
        log_level=_choice(env.get("LOG_LEVEL"), "info", "LOG_LEVEL", LOG_LEVELS),
        frontend_dist=_path(env.get("FRONTEND_DIST")) or DEFAULT_FRONTEND_DIST,
        catalog_relevance=_choice(env.get("CATALOG_RELEVANCE"), "legacy", "CATALOG_RELEVANCE", CATALOG_RELEVANCE_MODES),
        catalog_search_dir=_path(env.get("CATALOG_SEARCH_DIR")),
        catalog_model_dir=_path(env.get("CATALOG_MODEL_DIR")),
        catalog_search_policy=_path(env.get("CATALOG_SEARCH_POLICY")),
        catalog_rerank_dir=_path(env.get("CATALOG_RERANK_DIR")),
        catalog_rerank_model_dir=_path(env.get("CATALOG_RERANK_MODEL_DIR")),
        catalog_rerank_encoder_dir=_path(env.get("CATALOG_RERANK_ENCODER_DIR")),
        catalog_rerank_policy=_path(env.get("CATALOG_RERANK_POLICY")),
    )
