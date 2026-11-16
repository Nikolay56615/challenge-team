"""Персональный подбор: правила с признаками профиля.

Признаки и порядок расчёта:
- продолжение начисляется по `recommended_next` последнего по `seq` события истории
  и только материалам, которых в истории ещё нет;
- популярность для разрешения равенств нормирует источник каталога;
- пилот «похожие курсы» (решение 2026-11-11): вклады `history_topic` и `co_enrollment` считаются,
  только если политика передала их данные в контексте, то есть при пустой задаче (ranking/policy.py).
"""

from __future__ import annotations

from .. import vocab
from ..catalog.lexicon import stage_hint_set
from ..catalog.models import Material
from .base import CoEnrollment, Context, Scored, mark_tie_winners, sort_key

# Вклады co_enrollment и history_topic — гипотезы пилота, как и прочие веса первого прототипа
#. co_enrollment — 3,0 × min(1, Σ N/M) по курсам истории:
# при половине доли слушателей вклад равен продолжению по редакционной связи. history_topic — 0,1 по вложенному
# выбору на разбиениях O1 : при 1,0 темы истории теснили курсы других тем.
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
    "co_enrollment": 3.0,
    "history_topic": 0.1,
}

EFFORT_MAX_MINUTES = 30
# Сила признака: 2 — слова найдены в названии материала, 1 — только в описании
SIGNAL_TITLE_STRENGTH = 2
DIVERSITY_WINDOW = 5
DIVERSITY_MAX_SAME_FORMAT = 3
DIVERSITY_SCORE_GAP = 2.0

# Сходство курсов — доля слушателей курса истории, записанных и на кандидата: c_ij / c_i, то есть
# формула R03 с α = 1. Подбор α на разбиениях O1 пользы не дал (evaluation/track1-offline-courses.md)
CO_ENROLLMENT_ALPHA = 1.0
# Фраза «N из M» говорит о доле только при M не меньше 10. Курс истории с меньшим числом
# слушателей вклада не даёт: вклад без фразы нарушил бы свойство 3.6. При пороге поддержки
# PAIRS_MIN_SUPPORT от 10 условие выполняется само: M не меньше N
CO_ENROLLMENT_MIN_ANCHOR_USERS = 10


def _level_index(code: str | None) -> int | None:
    return vocab.LEVEL_ORDER.index(code) if code in vocab.LEVEL_ORDER else None


def _anchor_shares(material: Material, ctx: Context) -> list[tuple[float, CoEnrollment]]:
    """Доли c_ij / c_i по курсам истории i, которые дают кандидату вклад, в порядке якорей контекста."""
    pairs = ctx.pairs
    if (
        pairs is None or not ctx.anchors or "co_enrollment" in ctx.disabled
        or material.format != "course" or ctx.history.of(material.id)
    ):
        return []
    shares: list[tuple[float, CoEnrollment]] = []
    for anchor in ctx.anchors:
        users = pairs.totals.get(anchor, 0)
        together = pairs.neighbours(anchor).get(material.id, 0)
        if anchor == material.id or users < CO_ENROLLMENT_MIN_ANCHOR_USERS or together <= 0:
            continue
        similarity = pairs.similarity(anchor, material.id, CO_ENROLLMENT_ALPHA)
        if similarity > 0:
            shares.append((similarity, CoEnrollment(anchor=anchor, together=together, total=users)))
    return shares


def co_enrollment(material: Material, ctx: Context) -> tuple[float, CoEnrollment | None]:
    """Доля «похожих курсов» для кандидата и пара для фразы.

    Доля — сумма c_ij / c_i по курсам истории i, не больше 1. Учитываются пары из файла пар, то есть
    с поддержкой не ниже порога, и курсы истории не меньше чем с CO_ENROLLMENT_MIN_ANCHOR_USERS слушателями.
    Курсы истории, в том числе недоступные, — якоря; сам кандидат якорем не бывает. Для фразы берётся
    курс истории с наибольшей долей, при равенстве — с более поздним событием. Без пар, без курсов
    в истории, для материала другого формата и для материала из истории — (0, None). Так же и для доли,
    вклад которой после округления оценки до 4 знаков равен нулю: пара без вклада не даёт ни кандидата,
    ни фразы.
    """
    shares = _anchor_shares(material, ctx)
    if not shares:
        return 0.0, None
    share = min(1.0, sum(similarity for similarity, _ in shares))
    if round(WEIGHTS["co_enrollment"] * share, 4) <= 0:
        return 0.0, None
    # max() берёт первую из равных долей, а якоря идут от последнего события истории
    return share, max(shares, key=lambda entry: entry[0])[1]


def co_enrollment_anchors(material: Material, ctx: Context) -> tuple[str, ...]:
    """Курсы истории, чьи пары дают кандидату вклад «похожих курсов»; для строки состояния."""
    if co_enrollment(material, ctx)[1] is None:
        return ()
    return tuple(pair.anchor for _, pair in _anchor_shares(material, ctx))


def _score_topic(item: Scored, ctx: Context) -> None:
    matched = next((t for t in ctx.topics if t in item.material.topics), None)
    if matched:
        item.matched_topic = matched
        item.add("topic", WEIGHTS["topic"])


def _score_signal(item: Scored, ctx: Context) -> None:
    """Признак: не более одного, по наибольшей силе."""
    if "signal" in ctx.disabled or not ctx.parsed.signals:
        return
    best: tuple[int, str] | None = None
    for code, strength in item.material.signals:
        if code in ctx.parsed.signals and (best is None or strength > best[0]):
            best = (strength, code)
    if best:
        item.matched_signal = best[1]
        title_match = best[0] >= SIGNAL_TITLE_STRENGTH
        item.add("signal", WEIGHTS["signal_title"] if title_match else WEIGHTS["signal_description"])


def _score_stage(item: Scored, ctx: Context) -> None:
    """Стадия: чип сильнее подсказки из текста; неизвестная стадия нейтральна."""
    material, profile = item.material, ctx.profile
    if "stage" in ctx.disabled or not material.stages:
        return
    if profile.stage:
        if profile.stage in material.stages:
            item.add("stage", WEIGHTS["stage_chip"])
    elif ctx.stage_hint and stage_hint_set(ctx.stage_hint) & set(material.stages):
        item.add("stage", WEIGHTS["stage_hint"])


def _score_level(item: Scored, ctx: Context) -> None:
    """Уровень: точное совпадение или смежный уровень."""
    material, profile = item.material, ctx.profile
    material_level = _level_index(material.level)
    if "level" in ctx.disabled or material_level is None:
        return
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


def _score_industry(item: Scored, ctx: Context) -> None:
    industry = ctx.industry
    if "industry" not in ctx.disabled and industry and industry in item.material.industries:
        item.add("industry", WEIGHTS["industry"])


def _score_format(item: Scored, ctx: Context) -> None:
    material, profile = item.material, ctx.profile
    if profile.format_pref:
        if material.format in vocab.FORMAT_PREFS[profile.format_pref][1]:
            item.add("format", WEIGHTS["format_chip"])
    elif ctx.format_hint and material.format in vocab.FORMAT_PREFS[ctx.format_hint][1]:
        item.add("format", WEIGHTS["format_hint"])


def _score_effort(item: Scored, ctx: Context) -> None:
    """Усилие: короткий материал для новичка без выбранного формата."""
    material, profile = item.material, ctx.profile
    novice = profile.experience == "none" or (not profile.experience and ctx.level_hint == "intro")
    if (
        "effort" not in ctx.disabled
        and novice
        and not profile.format_pref
        and not ctx.format_hint
        and material.duration_minutes
        and material.duration_minutes <= EFFORT_MAX_MINUTES
    ):
        item.add("effort", WEIGHTS["effort"])


def _score_continuation(item: Scored, ctx: Context) -> None:
    """История: продолжение по `recommended_next` последнего события."""
    material = item.material
    seen = ctx.history.of(material.id)
    last = ctx.history.last
    if "continuation" not in ctx.disabled and last and not seen and last.material_id in ctx.catalog:
        source = ctx.catalog[last.material_id]
        if material.id in source.recommended_next:
            item.continuation_of = source.id
            item.add("continuation", WEIGHTS["continuation"])


def _score_pilot(item: Scored, ctx: Context) -> None:
    """Пилот «похожие курсы»: тема истории вместо темы задачи и совместные записи на курсы."""
    material = item.material
    history_topic = next((t for t in ctx.history_topics if t in material.topics), None)
    if history_topic:
        item.history_topic = history_topic
        item.add("history_topic", WEIGHTS["history_topic"])
    share, pair = co_enrollment(material, ctx)
    if pair is not None:
        item.co_enrollment = pair
        item.add("co_enrollment", WEIGHTS["co_enrollment"] * share)


def _score_flags(item: Scored, ctx: Context) -> None:
    item.flags = ctx.history.flags(item.material.id)
    if "completed" in item.flags:
        item.add("completed", WEIGHTS["completed"])
    elif "in_progress" in item.flags:
        item.add("in_progress", WEIGHTS["in_progress"])
    elif "viewed" in item.flags:
        item.add("viewed", WEIGHTS["viewed"])


# Порядок вкладов определяет порядок ключей `contributions` и округление суммы, поэтому он закреплён
_SCORERS = (
    _score_topic,
    _score_signal,
    _score_stage,
    _score_level,
    _score_industry,
    _score_format,
    _score_effort,
    _score_continuation,
    _score_pilot,
    _score_flags,
)


def score_material(material: Material, ctx: Context) -> Scored:
    item = Scored(material=material)
    for scorer in _SCORERS:
        scorer(item, ctx)
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
