"""Бейзлайн: совпадение темы, порядок по популярности (PLAN.md, 3.1).

Профиль, стадия, опыт, формат и история на порядок не влияют. Пометки истории
выводятся для сравнения методов, но в оценке не участвуют.
"""

from __future__ import annotations

from ..catalog.models import Material
from .base import Context, Scored, sort_key


def rank(candidates: list[Material], ctx: Context) -> list[Scored]:
    scored: list[Scored] = []
    for material in candidates:
        item = Scored(material=material)
        item.matched_topic = next((t for t in ctx.topics if t in material.topics), None)
        item.flags = ctx.history.flags(material.id)
        scored.append(item)
    return sorted(scored, key=sort_key)
