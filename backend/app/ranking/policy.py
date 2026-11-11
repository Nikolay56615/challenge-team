"""Политика выдачи: допустимость, статусы, уточнения и стартовая подборка (PLAN.md, 3.2–3.5)."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .. import vocab
from ..catalog.lexicon import TOPIC_ORDER, ParsedTask, parse_task, title_matches_gaps
from ..catalog.models import Catalog, Material
from . import baseline, explain, personal
from .base import Context, HistoryIndex, MaterialFilters, Profile, Scored

METHODS = ("personal", "baseline")
FILTERS_EMPTY_MESSAGE = "По выбранным фильтрам материалов нет"


@dataclass(frozen=True, slots=True)
class FilterOptions:
    formats: tuple[str, ...]
    access: tuple[str, ...]


@dataclass(slots=True)
class Outcome:
    method: str
    status: str
    detected_topics: tuple[str, ...]
    items: list[Scored]
    reasons: list[list[str]]
    total_candidates: int
    message: str
    clarification: dict | None
    route: list[Material]
    filter_options: FilterOptions | None = None


def _filter_candidates(candidates: list[Material], filters: MaterialFilters) -> tuple[list[Material], FilterOptions]:
    formats = {m.format for m in candidates}
    access = {m.access for m in candidates}
    options = FilterOptions(
        formats=tuple(code for code in vocab.FORMATS if code in formats),
        access=tuple(code for code in vocab.ACCESS if code in access),
    )
    if filters.format is None and filters.access is None:
        return candidates, options
    return [
        m for m in candidates
        if (filters.format is None or m.format == filters.format)
        and (filters.access is None or m.access == filters.access)
    ], options


def _duplicate_key(material: Material) -> tuple[str, str]:
    return " ".join(material.title.casefold().split()), material.format


def eligible(catalog: Catalog, history: HistoryIndex) -> list[Material]:
    """Доступные материалы без дубликатов и без купленных (PLAN.md, 3.2).

    Дубликаты — материалы с одинаковыми названием и форматом. Если куплена хотя бы одна копия,
    в том числе недоступная, отбрасываются все копии; иначе остаётся самая популярная доступная.
    """
    purchased = {
        _duplicate_key(catalog.materials[material_id])
        for material_id, events in history.events.items()
        if "purchase" in events and material_id in catalog.materials
    }
    best: dict[tuple[str, str], Material] = {}
    for material in catalog.materials.values():
        if not material.available:
            continue
        key = _duplicate_key(material)
        if key in purchased:
            continue
        current = best.get(key)
        if current is None or (material.popularity, current.id) > (current.popularity, material.id):
            best[key] = material
    return sorted(best.values(), key=lambda m: m.id)


def topics_with_materials(pool: list[Material], *, order: tuple[str, ...] = TOPIC_ORDER) -> list[str]:
    present = {t for m in pool for t in m.topics}
    return [t for t in order if t in present]


def levels_beyond_courses(catalog: Catalog) -> bool:
    """Размечен ли уровень не только у курсов. В копии он есть только у курсов (PLAN.md, 3.4)."""
    return any(m.level for m in catalog.materials.values() if m.format != "course")


def _start_stage(material: Material) -> bool:
    """Стадия старта или без стадии; продвинутый уровень в стартовую подборку не берётся."""
    starts = not material.stages or bool({"idea", "start"} & set(material.stages))
    return starts and material.level != "advanced"


def starter_selection(pool: list[Material], history: HistoryIndex, *, by_level: bool = True) -> list[Scored]:
    """Самый популярный вводный бесплатный материал по каждой теме с чипом (PLAN.md, 3.4).

    `by_level` — уровень размечен не только у курсов: берётся вводный уровень, а если его в теме нет,
    правило стадии. Иначе, как в копии, правило стадии действует для всех тем: самый популярный
    открытый материал темы со стадией старта или без стадии.
    """
    picks: list[Scored] = []
    used: set[str] = set()
    for topic in vocab.CHIP_TOPICS:
        free = [
            m
            for m in pool
            if topic in m.topics and not m.is_paid and m.id not in used and "complete" not in history.of(m.id)
        ]
        intro = [m for m in free if m.level == "intro"] if by_level else []
        if not intro:
            intro = [m for m in free if _start_stage(m)]
        if not intro:
            continue
        chosen = min(intro, key=lambda m: (-m.popularity, m.id))
        used.add(chosen.id)
        picks.append(Scored(material=chosen, starter_topic=topic, flags=history.flags(chosen.id)))
    picks.sort(key=lambda s: (-s.material.popularity, s.material.id))
    return picks


def _options(topics: list[str] | tuple[str, ...]) -> list[dict]:
    return [{"label": vocab.topic_label(t), "value": t} for t in topics]


def _starter_outcome(
    *, method: str, status: str, message: str, pool: list[Material], history: HistoryIndex,
    limit: int, detected: tuple[str, ...], by_level: bool
) -> Outcome:
    picks = starter_selection(pool, history, by_level=by_level)
    options = topics_with_materials(pool)
    if not picks and not options:
        return Outcome(
            method=method, status="empty", detected_topics=detected, items=[], reasons=[], total_candidates=0,
            message=explain.EMPTY_MESSAGE, clarification=None, route=[],
        )
    items = picks[:limit]
    if status == "cold":
        question = explain.COLD_QUESTION
        text = explain.COLD_STARTER_TEXT if picks else explain.COLD_TEXT
        if not picks:
            message = explain.COLD_TEXT
    else:
        question = "Выберите тему"
        text = explain.none_clarification_text(options, has_starter=bool(picks))
    return Outcome(
        method=method,
        status=status,
        detected_topics=detected,
        items=items,
        reasons=[explain.starter_reasons(i) for i in items],
        total_candidates=len(picks),
        message=message,
        clarification={"question": question, "text": text, "options": _options(options)} if options else None,
        route=[],
    )


def _route_window(ranked: list[Scored], limit: int) -> list[Scored]:
    """Окно маршрута: первая страница, но не шире выдачи. «Показать ещё» (limit 10) маршрут не меняет,
    а при limit меньше 5 маршрут не называет материалов, которых нет на экране."""
    return ranked[: min(limit, personal.DIVERSITY_WINDOW)]


def _start_like(profile: Profile, stage_hint: str | None) -> bool:
    return profile.stage in {"idea", "start"} or (profile.stage is None and stage_hint == "start")


def _signal_outcome(
    catalog: Catalog, profile: Profile, parsed: ParsedTask, history: HistoryIndex, pool: list[Material]
) -> Outcome | None:
    """Задача называет понятие признака, но не тему («Какую CRM выбрать»): кандидаты — материалы с этим
    признаком из любых тем, без вклада темы. Понятия берутся из `parsed.concepts` — признаков, названных
    достаточно конкретно; широкие слова вроде «эффективно» материалы сами не отбирают. Если материалов
    с понятием нет, возвращается None, и подбор отвечает статусом none: сообщение, выбор темы и
    стартовая подборка."""
    disabled = frozenset(catalog.disabled_features)
    if "signal" in disabled or not parsed.concepts:
        return None
    wanted = set(parsed.concepts)
    candidates = [m for m in pool if wanted & {code for code, _ in m.signals}]
    if not candidates:
        return None
    available_signals = {code for m in candidates for code, _ in m.signals}
    candidates, filter_options = _filter_candidates(candidates, profile.filters)
    # Вклад признака и причина считаются только по понятиям, отобравшим кандидатов
    focused = replace(parsed, signals=parsed.concepts)
    ctx = Context(profile=profile, parsed=focused, topics=(), history=history, disabled=disabled, catalog=catalog.materials)
    ranked = personal.rank(candidates, ctx)
    items = ranked[: profile.limit]
    shown_signals = {code for m in candidates for code, _ in m.signals}
    found = tuple(s for s in parsed.concepts if s in shown_signals)
    missing = tuple(s for s in parsed.concepts if s not in available_signals)
    route: list[Material] = []
    if _start_like(profile, parsed.stage_hint):
        route = explain.build_route(_route_window(ranked, profile.limit), catalog.materials)
    return Outcome(
        method="personal",
        status="strong",
        detected_topics=(),
        items=items,
        reasons=[explain.personal_reasons(i, ctx) for i in items],
        total_candidates=len(candidates),
        message=explain.signal_results_message(
            signals=found, total=len(candidates), items=items, ctx=ctx, gaps=parsed.gaps, missing=missing
        ) if candidates else FILTERS_EMPTY_MESSAGE,
        clarification=None,
        route=route,
        filter_options=filter_options,
    )


def _title_match_outcome(
    catalog: Catalog, profile: Profile, parsed: ParsedTask, history: HistoryIndex, pool: list[Material], method: str
) -> Outcome:
    topics = set(parsed.topics)
    candidates = [
        material for material in pool
        if (method == "personal" or topics.intersection(material.topics))
        and title_matches_gaps(material.title, parsed.gaps)
    ]
    if not candidates:
        return _starter_outcome(
            method=method, status="none", message=explain.NO_TITLE_MATCH_MESSAGE,
            pool=pool, history=history, limit=profile.limit, detected=parsed.topics,
            by_level=levels_beyond_courses(catalog),
        )

    candidates, filter_options = _filter_candidates(candidates, profile.filters)
    ctx = Context(
        profile=profile, parsed=parsed, topics=parsed.topics if method == "baseline" else (),
        history=history, disabled=frozenset(catalog.disabled_features), catalog=catalog.materials,
    )
    ranked = personal.rank(candidates, ctx) if method == "personal" else baseline.rank(candidates, ctx)
    items = ranked[:profile.limit]
    route: list[Material] = []
    if method == "personal" and _start_like(profile, parsed.stage_hint):
        route = explain.build_route(_route_window(ranked, profile.limit), catalog.materials)
    ranking_reasons = (
        [explain.personal_reasons(item, ctx) for item in items]
        if method == "personal"
        else [explain.baseline_reasons(item) for item in items]
    )
    return Outcome(
        method=method, status="strong", detected_topics=parsed.topics, items=items,
        reasons=[explain.title_match_reasons(parsed.gaps, reasons) for reasons in ranking_reasons],
        total_candidates=len(candidates),
        message=explain.title_results_message(method=method, total=len(candidates), items=items, ctx=ctx)
        if candidates else FILTERS_EMPTY_MESSAGE,
        clarification=None, route=route,
        filter_options=filter_options,
    )


def recommend(catalog: Catalog, profile: Profile, method: str = "personal") -> Outcome:
    if method not in METHODS:
        raise ValueError(f"unknown method {method}")
    parsed = parse_task(profile.task)
    history = HistoryIndex.build(profile.history)
    pool = eligible(catalog, history)
    explicit = profile.topic is not None
    topics: tuple[str, ...] = (profile.topic,) if explicit else parsed.topics

    if not explicit and parsed.gaps and not parsed.concepts:
        return _title_match_outcome(catalog, profile, parsed, history, pool, method)

    # Тема выведена из понятия признака, сама задача её не называет
    signal_only = parsed.topics_from_signals and not explicit
    if signal_only:
        if method == "personal":
            outcome = _signal_outcome(catalog, profile, parsed, history, pool)
            if outcome is not None:
                return outcome
        # Подбор по теме признаков не видит; если материалов с понятием нет, ответ — статус none
        # с сообщением, выбором темы и стартовой подборкой
        topics = ()

    if not topics:
        if parsed.is_empty:
            return _starter_outcome(
                method=method, status="cold", message=explain.COLD_MESSAGE,
                pool=pool, history=history, limit=profile.limit, detected=(),
                by_level=levels_beyond_courses(catalog),
            )
        return _starter_outcome(
            method=method,
            status="none",
            message=explain.none_message(
                profile.task, gaps=parsed.gaps, baseline_without_topic=signal_only and method == "baseline"
            ),
            pool=pool, history=history, limit=profile.limit, detected=(),
            by_level=levels_beyond_courses(catalog),
        )

    candidates = [m for m in pool if set(m.topics) & set(topics)]
    if not candidates:
        return _starter_outcome(
            method=method,
            status="none",
            message=explain.no_materials_text(topics),
            pool=pool, history=history, limit=profile.limit, detected=topics,
            by_level=levels_beyond_courses(catalog),
        )

    # Статус и варианты уточнения опираются на темы исходных кандидатов.
    covered = tuple(t for t in topics if any(t in m.topics for m in candidates))
    missing = tuple(t for t in topics if t not in covered)
    original_count = len(candidates)
    candidates, filter_options = _filter_candidates(candidates, profile.filters)
    filtered_topics = tuple(t for t in covered if any(t in m.topics for m in candidates))
    ctx = Context(
        profile=profile,
        parsed=parsed,
        topics=filtered_topics,
        history=history,
        disabled=frozenset(catalog.disabled_features),
        catalog=catalog.materials,
    )
    ranked = personal.rank(candidates, ctx) if method == "personal" else baseline.rank(candidates, ctx)
    items = ranked[: profile.limit]

    if explicit:
        status = "strong"
    elif len(covered) >= 2 or parsed.gaps:
        status = "weak"
    else:
        status = "strong"

    clarification = None
    if status == "weak":
        options = list(covered) if len(covered) >= 2 else list(covered) + [
            t for t in topics_with_materials(pool, order=vocab.CHIP_TOPICS) if t not in covered
        ]
        clarification = {
            "question": "Уточните тему",
            "text": explain.weak_clarification_text(covered, parsed.gaps) if len(candidates) == original_count
            else "Выберите тему, чтобы уточнить подбор.",
            "options": _options(options),
        }

    route: list[Material] = []
    if method == "personal" and status == "strong" and _start_like(profile, parsed.stage_hint):
        route = explain.build_route(_route_window(ranked, profile.limit), catalog.materials)

    signal = next((i.matched_signal for i in items if i.matched_signal), None)
    message = FILTERS_EMPTY_MESSAGE
    if candidates:
        message = explain.results_message(
            method=method, topics=filtered_topics, total=len(candidates), items=items, ctx=ctx, signal=signal,
            missing=missing,
        )
    if method == "personal":
        reasons = [explain.personal_reasons(i, ctx) for i in items]
    else:
        reasons = [explain.baseline_reasons(i) for i in items]
    return Outcome(
        method=method,
        status=status,
        detected_topics=topics,
        items=items,
        reasons=reasons,
        total_candidates=len(candidates),
        message=message,
        clarification=clarification,
        route=route,
        filter_options=filter_options,
    )
