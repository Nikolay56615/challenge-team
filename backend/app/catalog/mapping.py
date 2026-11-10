"""Соответствие подписей выгрузки каноническим кодам (PLAN.md, 2.2, 2.3, 2.8).

Для другой выгрузки меняется YAML-файл (`CATALOG_MAPPING`), а не код загрузчика. Разделы
необязательны: пропущенный раздел берётся из встроенных значений, указанный заменяет встроенный
целиком. Образец с теми же значениями — `data/mapping.example.yaml`. Подписи сравниваются без
учёта регистра, лишних пробелов и различия «е» и «ё».
"""

from __future__ import annotations

import math
import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .. import vocab
from .models import CatalogError

DEFAULT_MAPPING: dict[str, Any] = {
    "version": 1,
    "published_statuses": ["Опубликовано"],
    "topic_groups": {
        "taxes_law": ["Налоги и законы", "Законы"],
        "finance": ["Финансы и учет", "Финансы"],
        "team": ["Управление командой"],
        "operations": ["Операционка"],
        "marketing": ["Маркетинг"],
        "start": ["Старт бизнеса", "Первые шаги", "Регистрация бизнеса"],
        "strategy": ["Стратегия и бизнес-модели"],
        "sales": ["Продажи и переговоры", "Продажи"],
        "tech": ["ИИ и автоматизация", "Технологии"],
        "service": ["Клиентский сервис"],
        "stories": ["Личный опыт"],
        "abroad": ["Бизнес за рубежом"],
        "marketplaces": ["Маркетплейсы"],
    },
    "rubrics": {
        "ИП": "start",
        "ООО": "start",
        "Самозанятость": "start",
        "Маркетплейсы": "marketplaces",
        "Эквайринг и касса": "finance",
        "Банковские продукты": "finance",
    },
    "industries": {
        "ECom": "ecom",
        "Розница": "retail",
        "Услуги": "services",
        "Строительство и недвижимость": "construction",
        "HoReCa": "horeca",
        "Транспорт и логистика": "logistics",
        "B2B": "b2b",
        "Производство": "manufacturing",
        "Оптовая торговля": "wholesale",
        "B2G": "b2g",
    },
    "service_labels": {
        "exact": ["Без опыта", "С опытом", "Новинки", "Актуальное", "Популярное", "Рекомендуемое"],
        "prefixes": ["Сегмент"],
    },
    "level_labels": {"Без опыта": "intro", "С опытом": "advanced"},
    "stage_tags": {"Старт бизнеса": "start", "Развитие бизнеса": "growth", "Налоги и законы": None},
    "access_titles": {"Открытый": "open", "По подписке": "subscription", "Платный": "paid"},
    "duration_units": {
        "минута": 1,
        "минуты": 1,
        "минут": 1,
        "мин": 1,
        "час": 60,
        "часа": 60,
        "часов": 60,
        "ч": 60,
    },
    "history_events": {"status": {0: "view", 1: "start", 2: "complete"}, "paid": "purchase"},
}

SECTIONS: tuple[str, ...] = tuple(DEFAULT_MAPPING)

_WORD = re.compile(r"[^\W\d_]+")
_DURATION_PART = re.compile(r"(\d+(?:[.,]\d+)?)\s*([^\W\d_]+)\.?")


def norm_label(value: str) -> str:
    """Ключ сравнения подписи: регистр, лишние пробелы и «ё» не важны."""
    return " ".join(value.replace("ё", "е").replace("Ё", "Е").split()).casefold()


@dataclass(frozen=True, slots=True)
class CatalogMapping:
    """Проверенное соответствие. Ключи словарей — подписи после `norm_label`."""

    published_statuses: frozenset[str]
    topic_titles: dict[str, str]
    rubrics: dict[str, str]
    industries: dict[str, str]
    service_labels: frozenset[str]
    service_prefixes: tuple[str, ...]
    level_labels: dict[str, str]
    stage_tags: dict[str, str | None]
    access_titles: dict[str, str]
    duration_units: dict[str, float]
    history_status: dict[int, str]
    history_paid: str | None

    def is_published(self, status: str | None) -> bool:
        return bool(status) and norm_label(status) in self.published_statuses

    def topic(self, title: str | None) -> str | None:
        return _lookup(self.topic_titles, title)

    def rubric(self, title: str | None) -> str | None:
        return _lookup(self.rubrics, title)

    def stage(self, tag: str | None) -> str | None:
        return _lookup(self.stage_tags, tag)

    def level(self, label: str | None) -> str | None:
        return _lookup(self.level_labels, label)

    def industry(self, label: str | None) -> str | None:
        return _lookup(self.industries, label)

    def access(self, title: str | None) -> str | None:
        return _lookup(self.access_titles, title)

    def is_service(self, label: str | None) -> bool:
        """Служебная метка отрасли: не сфера бизнеса. Метки уровня тоже служебные."""
        if not label:
            return False
        key = norm_label(label)
        if key in self.service_labels or key in self.level_labels:
            return True
        return any(key == prefix or key.startswith(prefix + " ") for prefix in self.service_prefixes)

    def parse_duration(self, text: Any) -> int | None:
        """«7 минут», «1 час 30 минут», «1,5 часа» → минуты. Нераспознанное → None."""
        if not isinstance(text, str):
            return None
        value = norm_label(text)
        total = 0.0
        position = 0
        for part in _DURATION_PART.finditer(value):
            factor = self.duration_units.get(part.group(2))
            if factor is None or value[position : part.start()].strip(" ,"):
                return None
            total += float(part.group(1).replace(",", ".")) * factor
            position = part.end()
        if position == 0 or value[position:].strip(" ,"):
            return None
        minutes = int(total + 0.5)
        return minutes if minutes > 0 else None


def _lookup(table: dict[str, Any], label: str | None) -> Any:
    return table.get(norm_label(label)) if label else None


def load_mapping(path: Path | None = None) -> CatalogMapping:
    """Читает YAML-файл соответствия; без пути — встроенные значения."""
    if path is None:
        return build_mapping(DEFAULT_MAPPING, source="встроенное соответствие")
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CatalogError(f"Файл соответствия не найден: {path.name}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise CatalogError(f"Файл соответствия не читается: {path.name}") from exc
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f", строка {mark.line + 1}" if mark is not None else ""
        raise CatalogError(f"Файл соответствия {path.name} не разбирается как YAML{where}") from exc
    if payload is None:
        raise CatalogError(f"Файл соответствия пуст: {path.name}")
    if not isinstance(payload, dict):
        raise CatalogError(f"Файл соответствия {path.name}: ожидается словарь разделов")
    return build_mapping(payload, source=f"Файл соответствия {path.name}")


def build_mapping(payload: dict[str, Any], *, source: str) -> CatalogMapping:
    """Проверяет разделы и строит соответствие. Ошибка — CatalogError с названием раздела."""
    unknown = [str(key) for key in payload if key not in SECTIONS]
    if unknown:
        raise _fail(source, f"неизвестные разделы {', '.join(unknown)}; допустимы: {', '.join(SECTIONS)}")
    data = {**DEFAULT_MAPPING, **payload}
    if type(data["version"]) is not int or data["version"] != 1:
        raise _fail(source, "поддерживается только version: 1")

    published = _labels(data["published_statuses"], source, "published_statuses", allow_empty=False)
    exact, prefixes = _service_labels(data["service_labels"], source)
    levels = _codes(data["level_labels"], source, "level_labels", vocab.LEVELS)
    industries = _codes(data["industries"], source, "industries", vocab.INDUSTRIES)
    for label in industries:
        if label in exact or label in levels or any(label == p or label.startswith(p + " ") for p in prefixes):
            raise _fail(source, f"метка «{label}» указана и как сфера в industries, и как служебная")
    status, paid = _history(data["history_events"], source)
    return CatalogMapping(
        published_statuses=frozenset(norm_label(s) for s in published),
        topic_titles=_topic_groups(data["topic_groups"], source),
        rubrics=_codes(data["rubrics"], source, "rubrics", vocab.TOPICS),
        industries=industries,
        service_labels=frozenset(exact),
        service_prefixes=tuple(prefixes),
        level_labels=levels,
        stage_tags=_codes(data["stage_tags"], source, "stage_tags", vocab.STAGES, nullable=True),
        access_titles=_codes(data["access_titles"], source, "access_titles", vocab.ACCESS),
        duration_units=_duration_units(data["duration_units"], source),
        history_status=status,
        history_paid=paid,
    )


def _fail(source: str, detail: str) -> CatalogError:
    return CatalogError(f"{source}: {detail}")


def _show(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 40 else text[:37] + "..."


def _label(value: Any, source: str, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(source, f"в разделе {where} ожидается непустая строка, получено {_show(value)}")
    return value.strip()


def _labels(value: Any, source: str, where: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        need = "списком строк" if allow_empty else "непустым списком строк"
        raise _fail(source, f"раздел {where} должен быть {need}")
    return [_label(item, source, where) for item in value]


def _mapping(value: Any, source: str, where: str, shape: str) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise _fail(source, f"раздел {where} должен быть словарём «{shape}»")
    return value


def _codes(
    value: Any, source: str, where: str, allowed: Collection[str], *, nullable: bool = False
) -> dict[str, Any]:
    """Словарь «подпись: код» с проверкой кодов по справочнику `vocab`."""
    result: dict[str, Any] = {}
    for label, code in _mapping(value, source, where, "подпись: код").items():
        key = norm_label(_label(label, source, where))
        if key in result:
            raise _fail(source, f"в разделе {where} подпись «{label}» повторяется")
        if code is None and nullable:
            result[key] = None
            continue
        if not isinstance(code, str) or code not in allowed:
            raise _fail(
                source,
                f"в разделе {where} у подписи «{label}» неизвестный код {_show(code)}; допустимы: {', '.join(allowed)}",
            )
        result[key] = code
    return result


def _topic_groups(value: Any, source: str) -> dict[str, str]:
    """Группы тем «код: исходные названия» → словарь «название: код»."""
    titles: dict[str, str] = {}
    for code, labels in _mapping(value, source, "topic_groups", "код темы: список названий").items():
        if not isinstance(code, str) or code not in vocab.TOPICS:
            raise _fail(
                source, f"в разделе topic_groups неизвестный код темы {_show(code)}; допустимы: {', '.join(vocab.TOPICS)}"
            )
        for label in _labels(labels, source, f"topic_groups.{code}"):
            key = norm_label(label)
            if titles.get(key, code) != code:
                raise _fail(source, f"тема «{label}» входит в две группы: {titles[key]} и {code}")
            titles[key] = code
    return titles


def _service_labels(value: Any, source: str) -> tuple[list[str], list[str]]:
    data = _mapping(value, source, "service_labels", "exact: […], prefixes: […]")
    extra = [str(key) for key in data if key not in {"exact", "prefixes"}]
    if extra:
        raise _fail(source, f"в разделе service_labels допустимы только exact и prefixes, получено {', '.join(extra)}")
    exact = [norm_label(s) for s in _labels(data.get("exact", []), source, "service_labels.exact")]
    prefixes = [norm_label(s) for s in _labels(data.get("prefixes", []), source, "service_labels.prefixes")]
    return exact, prefixes


def _duration_units(value: Any, source: str) -> dict[str, float]:
    units: dict[str, float] = {}
    data = _mapping(value, source, "duration_units", "единица: минут в единице")
    if not data:
        raise _fail(source, "раздел duration_units не должен быть пустым")
    for unit, minutes in data.items():
        key = norm_label(_label(unit, source, "duration_units"))
        if not _WORD.fullmatch(key):
            raise _fail(source, f"единица длительности «{unit}» должна быть одним словом без цифр")
        if key in units:
            raise _fail(source, f"в разделе duration_units единица «{unit}» повторяется")
        if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not (0 < minutes < math.inf):
            raise _fail(source, f"у единицы «{unit}» число минут должно быть положительным, получено {_show(minutes)}")
        units[key] = float(minutes)
    return units


def _history(value: Any, source: str) -> tuple[dict[int, str], str | None]:
    """Коды событий истории: `CourseUserBindings.Status` → событие, `IsPaid` → событие."""
    data = _mapping(value, source, "history_events", "status: {код: событие}, paid: событие")
    extra = [str(key) for key in data if key not in {"status", "paid"}]
    if extra:
        raise _fail(source, f"в разделе history_events допустимы только status и paid, получено {', '.join(extra)}")
    status: dict[int, str] = {}
    for code, event in _mapping(data.get("status", {}), source, "history_events.status", "код: событие").items():
        if isinstance(code, bool) or not isinstance(code, int):
            raise _fail(source, f"в разделе history_events.status код {_show(code)} должен быть целым числом")
        if event not in vocab.EVENTS:
            raise _fail(
                source,
                f"в разделе history_events.status неизвестное событие {_show(event)}; допустимы: {', '.join(vocab.EVENTS)}",
            )
        status[code] = event
    paid = data.get("paid")
    if paid is not None and paid not in vocab.EVENTS:
        raise _fail(source, f"в разделе history_events.paid неизвестное событие {_show(paid)}")
    return status, paid
