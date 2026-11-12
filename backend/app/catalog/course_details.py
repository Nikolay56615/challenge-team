"""Короткие сведения из карточки каталога в виде обычного текста."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape

_MARKUP = re.compile(r"<\s*(?:/?[a-z]|[!?])", re.IGNORECASE)


def _plain_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(unescape(value).split())
    return text if text and not _MARKUP.search(text) else None


def _points(values: object) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    points: dict[str, str] = {}
    for value in values:
        if text := _plain_text(value):
            points.setdefault(text.casefold().replace("ё", "е"), text)
        if len(points) == 5:
            break
    return tuple(points.values())


@dataclass(frozen=True, slots=True)
class CourseDetails:
    description: str | None
    audiences: tuple[str, ...]
    outcomes: tuple[str, ...]

    @classmethod
    def prepare(cls, description: object, audiences: object, outcomes: object) -> CourseDetails | None:
        details = cls(_plain_text(description), _points(audiences), _points(outcomes))
        return details if details.description or details.audiences or details.outcomes else None

    @classmethod
    def from_json(cls, value: object) -> CourseDetails | None:
        if not isinstance(value, str):
            return None
        try:
            payload = json.loads(value)
        except (ValueError, RecursionError):
            return None
        if not isinstance(payload, dict):
            return None
        return cls.prepare(payload.get("description"), payload.get("audiences"), payload.get("outcomes"))
