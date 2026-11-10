"""Персональный подбор: правила с признаками профиля (PLAN.md, 3.2).

Уточнения к плану, записанные в PLAN.md, раздел 9:
- продолжение начисляется по `recommended_next` последнего по `seq` события истории
  и только материалам, которых в истории ещё нет;
- популярность для разрешения равенств нормирует источник каталога.
"""

from __future__ import annotations

from .. import vocab
from ..catalog.lexicon import stage_hint_set
from ..catalog.models import Material
from .base import Context, Scored, mark_tie_winners, sort_key

WEIGHTS: dict[str, float] = {
    "topic": 3.0,
    "signal_title": 2.0,
    "signal_description": 1.0,
    "stage_chip": 2.0,
    "stage_hint": 1.0,
    "level_exact": 2.0,
    "level_adjacent": 1.0,
    "level_hint": 1.0,
    "industry": 1.0,
    "format_chip": 1.5,
    "format_hint": 1.0,
    "effort": 0.5,
    "continuation": 1.5,
    "in_progress": 2.0,
    "viewed": -1.5,
    "completed": -4.0,
}

EFFORT_MAX_MINUTES = 30
DIVERSITY_WINDOW = 5
DIVERSITY_MAX_SAME_FORMAT = 3
DIVERSITY_SCORE_GAP = 2.0


def _level_index(code: str | None) -> int | None:
    return vocab.LEVEL_ORDER.index(code) if code in vocab.LEVEL_ORDER else None


def score_material(material: Material, ctx: Context) -> Scored:
    item = Scored(material=material)
    profile = ctx.profile
    disabled = ctx.disabled

    # Тема
    matched = next((t for t in ctx.topics if t in material.topics), None)
    if matched:
        item.matched_topic = matched
        item.add("topic", WEIGHTS["topic"])

    # Признак: не более одного, по наибольшей силе
    if "signal" not in disabled and ctx.parsed.signals:
        best: tuple[int, str] | None = None
        for code, strength in material.signals:
            if code in ctx.parsed.signals and (best is None or strength > best[0]):
                best = (strength, code)
        if best:
            item.matched_signal = best[1]
            item.add("signal", WEIGHTS["signal_title"] if best[0] >= 2 else WEIGHTS["signal_description"])

    # Стадия: чип сильнее подсказки из текста; неизвестная стадия нейтральна
    if "stage" not in disabled and material.stages:
        if profile.stage:
            if profile.stage in material.stages:
                item.add("stage", WEIGHTS["stage_chip"])
        elif ctx.stage_hint and stage_hint_set(ctx.stage_hint) & set(material.stages):
            item.add("stage", WEIGHTS["stage_hint"])

    # Уровень: точное совпадение или смежный уровень
    material_level = _level_index(material.level)
    if "level" not in disabled and material_level is not None:
        if profile.experience:
            target = _level_index(vocab.EXPERIENCE_TO_LEVEL[profile.experience])
            if target is not None:
                distance = abs(material_level - target)
                if distance == 0:
                    item.add("level", WEIGHTS["level_exact"])
                elif distance == 1:
                    item.level_direction = 1 if material_level > target else -1
                    item.add("level", WEIGHTS["level_adjacent"])
        elif ctx.level_hint and material.level == ctx.level_hint:
            item.add("level", WEIGHTS["level_hint"])

    # Сфера
    industry = ctx.industry
    if "industry" not in disabled and industry and industry in material.industries:
        item.add("industry", WEIGHTS["industry"])

    # Формат
    if profile.format_pref:
        if material.format in vocab.FORMAT_PREFS[profile.format_pref][1]:
            item.add("format", WEIGHTS["format_chip"])
    elif ctx.format_hint and material.format in vocab.FORMAT_PREFS[ctx.format_hint][1]:
        item.add("format", WEIGHTS["format_hint"])

    # Усилие: короткий материал для новичка без выбранного формата
    novice = profile.experience == "none" or (not profile.experience and ctx.level_hint == "intro")
    if (
        "effort" not in disabled
        and novice
        and not profile.format_pref
        and not ctx.format_hint
        and material.duration_minutes
        and material.duration_minutes <= EFFORT_MAX_MINUTES
    ):
        item.add("effort", WEIGHTS["effort"])

    # История
    seen = ctx.history.of(material.id)
    last = ctx.history.last
    if "continuation" not in disabled and last and not seen and last.material_id in ctx.catalog:
        source = ctx.catalog[last.material_id]
        if material.id in source.recommended_next:
            item.continuation_of = source.id
            item.add("continuation", WEIGHTS["continuation"])
    item.flags = ctx.history.flags(material.id)
    if "completed" in item.flags:
        item.add("completed", WEIGHTS["completed"])
    elif "in_progress" in item.flags:
        item.add("in_progress", WEIGHTS["in_progress"])
    elif "viewed" in item.flags:
        item.add("viewed", WEIGHTS["viewed"])
    return item


def _diversify(ranked: list[Scored]) -> list[Scored]:
    """В пятёрке не больше трёх материалов одного формата, если другой формат близок по оценке к лидеру."""
    if not ranked:
        return ranked
    leader = ranked[0].score
    remaining = list(ranked)
    selected: list[Scored] = []
    while remaining and len(selected) < DIVERSITY_WINDOW:
        head = remaining[0]
        same = sum(1 for s in selected if s.material.format == head.material.format)
        if same >= DIVERSITY_MAX_SAME_FORMAT:
            alternative = next(
                (
                    r
                    for r in remaining[1:]
                    if r.material.format != head.material.format and r.score >= leader - DIVERSITY_SCORE_GAP
                ),
                None,
            )
            if alternative is not None:
                selected.append(alternative)
                remaining.remove(alternative)
                continue
        selected.append(head)
        remaining.pop(0)
    return selected + remaining


def rank(candidates: list[Material], ctx: Context) -> list[Scored]:
    scored = sorted((score_material(m, ctx) for m in candidates), key=sort_key)
    mark_tie_winners(scored)
    return _diversify(scored)
