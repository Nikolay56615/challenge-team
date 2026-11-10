"""Синтетические тестовые профили для демо-режима (PLAN.md, 2.6)."""

from __future__ import annotations

import json
from pathlib import Path

from .. import vocab
from ..catalog.models import CatalogError, DemoProfile, HistoryEvent, valid_material_id
from ..config import DATA_DIR

PROFILES_PATH = DATA_DIR / "profiles.synthetic.json"


def _optional(value: object, allowed: dict) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def load_profiles(path: Path = PROFILES_PATH) -> dict[str, DemoProfile]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:  # ValueError включает ошибки JSON и кодировки
        raise CatalogError("Файл тестовых профилей не читается") from exc
    profiles: dict[str, DemoProfile] = {}
    for row in payload.get("profiles", []):
        # Историю профиля интерфейс отправляет обратно в запросе: код вне правила дал бы 422
        history = tuple(
            HistoryEvent(material_id=e["material_id"], event=e["event"], seq=int(e["seq"]))
            for e in row.get("history", [])
            if e.get("event") in vocab.EVENTS and valid_material_id(e.get("material_id"))
        )
        profiles[row["id"]] = DemoProfile(
            id=row["id"],
            label=row["label"],
            description=row.get("description", ""),
            task=row.get("task", ""),
            stage=_optional(row.get("stage"), vocab.STAGES),
            experience=_optional(row.get("experience"), vocab.EXPERIENCE),
            format_pref=_optional(row.get("format_pref"), vocab.FORMAT_PREFS),
            industry=_optional(row.get("industry"), vocab.INDUSTRIES),
            history=history,
        )
    return profiles
