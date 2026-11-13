"""Политика выдачи, включая поиск по задаче и подбор по истории (docs/plan.md, 3.2–3.5)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, cast

from .. import vocab
from ..catalog.global_search import SearchIndex, SearchUnavailable
from ..catalog.lexicon import TOPIC_ORDER, ParsedTask, parse_task, title_matches_gaps
from ..catalog.models import Catalog, Material
from ..catalog.reranked_search import RerankedIndex
from ..catalog.task_search import ARTICLE_PARAGRAPH, TITLE, Evidence
from ..catalog.text_search import TextMatches
from . import baseline, explain, personal
from .base import Context, HistoryIndex, HistorySignals, MaterialFilters, Profile, Scored

METHODS = ("personal", "baseline")
MIN_AMBIGUOUS_TOPICS = 2
TITLE_PRIORITY = 2
FILTERS_EMPTY_MESSAGE = "По выбранным фильтрам материалов нет"
CandidateObserver = Callable[[list[Material]], None]


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
    clarification: dict[str, Any] | None
    route: list[Material]
    filter_options: FilterOptions | None = None


def _filter_candidates(
    candidates: list[Material], filters: MaterialFilters, observe: CandidateObserver | None
) -> tuple[list[Material], FilterOptions]:
    formats = {m.format for m in candidates}
    access = {m.access for m in candidates}
    options = FilterOptions(
        formats=tuple(code for code in vocab.FORMATS if code in formats),
        access=tuple(code for code in vocab.ACCESS if code in access),
    )
    if filters.format is not None or filters.access is not None:
        candidates = [
            m
            for m in candidates
            if (filters.format is None or m.format == filters.format)
            and (filters.access is None or m.access == filters.access)
        ]
    if observe is not None:
        observe(candidates)
    return candidates, options


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


def _options(topics: list[str] | tuple[str, ...]) -> list[dict[str, str]]:
    return [{"label": vocab.topic_label(t), "value": t} for t in topics]


def _first(topics: list[str], preferred: tuple[str, ...]) -> list[str]:
    """Темы с материалами, сначала предпочтительные: так «товарный знак» первой предложит «Налоги и законы»."""
    return [t for t in preferred if t in topics] + [t for t in topics if t not in preferred]


def _starter_outcome(  # noqa: PLR0913 — common response for the cold and empty states
    *,
    method: str,
    status: str,
    message: str,
    pool: list[Material],
    history: HistoryIndex,
    limit: int,
    detected: tuple[str, ...],
    by_level: bool,
    preferred: tuple[str, ...] = (),
) -> Outcome:
    picks = starter_selection(pool, history, by_level=by_level)
    options = _first(topics_with_materials(pool), preferred)
    if not picks and not options:
        return Outcome(
            method=method,
            status="empty",
            detected_topics=detected,
            items=[],
            reasons=[],
            total_candidates=0,
            message=explain.EMPTY_MESSAGE,
            clarification=None,
            route=[],
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


def _rank_personal(
    candidates: list[Material], ctx: Context, matches: TextMatches, evidence: dict[str, Evidence]
) -> list[Scored]:
    ranked = personal.rank(candidates, ctx)
    if evidence:
        max_score = max((hit.score for key, hit in evidence.items() if not matches.priority(key)), default=0) or 1
        last = max(len(ranked) - 1, 1)
        positions = {item.material.id: index for index, item in enumerate(ranked)}
        ranked.sort(key=lambda item: _task_order(item, matches, evidence, positions, max_score, last))
    elif matches.titles or matches.descriptions:
        # Стабильная сортировка сохраняет персональный порядок внутри групп.
        ranked.sort(key=lambda item: -matches.priority(item.material.id))
    return ranked


def _task_order(  # noqa: PLR0917 — inputs shared by the ranking key
    item: Scored,
    matches: TextMatches,
    evidence: dict[str, Evidence],
    positions: dict[str, int],
    max_score: float,
    last: int,
) -> tuple[int, float]:
    material_id = item.material.id
    exact = matches.priority(material_id)
    hit = evidence.get(material_id)
    if exact >= TITLE_PRIORITY:
        return -exact - 3, 0
    if hit and hit.intent and hit.field == TITLE:
        return -4, 0
    if exact == 1:
        return -3, 0
    if hit and hit.intent:
        return -2, 0
    if hit:
        return -1, -(0.8 * hit.score / max_score + 0.2 * (1 - positions[material_id] / last))
    return 0, 0


def _personal_reasons(
    items: list[Scored], ctx: Context, matches: TextMatches, evidence: dict[str, Evidence]
) -> list[list[str]]:
    reasons = []
    for item in items:
        ranking = explain.personal_reasons(item, ctx)
        material_id = item.material.id
        hit = evidence.get(material_id)
        if material_id in matches.titles:
            ranking = explain.text_match_reasons("в названии", ranking)
        elif hit and hit.intent and hit.field == TITLE:
            ranking = explain.task_match_reasons(hit.field, ranking)
        elif material_id in matches.descriptions:
            ranking = explain.text_match_reasons("в кратком описании курса", ranking)
        elif hit and (hit.intent or hit.field == ARTICLE_PARAGRAPH):
            ranking = explain.task_match_reasons(hit.field, ranking)
        elif hit:
            ranking = explain.text_match_reasons(hit.field, ranking)
        reasons.append(ranking)
    return reasons


def _signal_outcome(  # noqa: PLR0917 — shared request inputs
    catalog: Catalog,
    profile: Profile,
    parsed: ParsedTask,
    history: HistoryIndex,
    pool: list[Material],
    matches: TextMatches,
    observe: CandidateObserver | None,
) -> Outcome | None:
    """Задача называет понятие признака, но не тему («Какую CRM выбрать»): кандидаты — материалы с этим
    признаком из любых тем, без вклада темы. Понятия берутся из `parsed.concepts` — признаков, названных
    достаточно конкретно; широкие слова вроде «эффективно» материалы сами не отбирают. Если материалов
    с понятием нет, возвращается None и проверяются совпадения по словам запроса."""
    disabled = frozenset(catalog.disabled_features)
    if "signal" in disabled or not parsed.concepts:
        return None
    wanted = set(parsed.concepts)
    candidates = [m for m in pool if wanted & {code for code, _ in m.signals}]
    if not candidates:
        return None
    available_signals = {code for m in candidates for code, _ in m.signals}
    candidates, filter_options = _filter_candidates(candidates, profile.filters, observe)
    # Вклад признака и причина считаются только по понятиям, отобравшим кандидатов
    focused = replace(parsed, signals=parsed.concepts)
    ctx = Context(
        profile=profile, parsed=focused, topics=(), history=history, disabled=disabled, catalog=catalog.materials
    )
    evidence = _task_evidence(catalog, profile, candidates)
    ranked = _rank_personal(candidates, ctx, matches, evidence)
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
        reasons=_personal_reasons(items, ctx, matches, evidence),
        total_candidates=len(candidates),
        message=explain.signal_results_message(
            signals=found,
            total=len(candidates),
            items=items,
            ctx=ctx,
            gaps=parsed.gaps,
            missing=missing,
            text_order=any(matches.priority(item.material.id) for item in items),
            task_order=any(item.material.id in evidence for item in items),
        )
        if candidates
        else FILTERS_EMPTY_MESSAGE,
        clarification=None,
        route=route,
        filter_options=filter_options,
    )


def _title_match_outcome(  # noqa: PLR0917 — shared request inputs
    catalog: Catalog,
    profile: Profile,
    parsed: ParsedTask,
    history: HistoryIndex,
    pool: list[Material],
    method: str,
    observe: CandidateObserver | None,
) -> Outcome:
    topics = set(parsed.topics)
    constrained = (
        cast(SearchIndex, catalog.search_index).constrained(profile.task, {m.id for m in pool})
        if (method == "personal" and catalog.search_index is not None and catalog.search_index.mode != "reranked")
        else None
    )
    candidates = [
        material
        for material in pool
        if (method == "personal" or topics.intersection(material.topics))
        and title_matches_gaps(material.title, parsed.gaps)
        and (constrained is None or material.id in constrained)
    ]
    if not candidates:
        return _starter_outcome(
            method=method,
            status="none",
            message=explain.NO_TITLE_MATCH_MESSAGE,
            pool=pool,
            history=history,
            limit=profile.limit,
            detected=parsed.topics,
            by_level=levels_beyond_courses(catalog),
        )

    candidates, filter_options = _filter_candidates(candidates, profile.filters, observe)
    ctx = Context(
        profile=profile,
        parsed=parsed,
        topics=parsed.topics if method == "baseline" else (),
        history=history,
        disabled=frozenset(catalog.disabled_features),
        catalog=catalog.materials,
    )
    ranked = personal.rank(candidates, ctx) if method == "personal" else baseline.rank(candidates, ctx)
    items = ranked[: profile.limit]
    route: list[Material] = []
    if method == "personal" and _start_like(profile, parsed.stage_hint):
        route = explain.build_route(_route_window(ranked, profile.limit), catalog.materials)
    lead = explain.title_match_phrase(parsed.gaps)
    reasons = (
        [explain.personal_reasons(item, ctx, lead=lead) for item in items]
        if method == "personal"
        else [explain.title_match_reasons(parsed.gaps, explain.baseline_reasons(item)) for item in items]
    )
    return Outcome(
        method=method,
        status="strong",
        detected_topics=parsed.topics,
        items=items,
        reasons=reasons,
        total_candidates=len(candidates),
        message=explain.title_results_message(method=method, total=len(candidates), items=items, ctx=ctx)
        if candidates
        else FILTERS_EMPTY_MESSAGE,
        clarification=None,
        route=route,
        filter_options=filter_options,
    )


def _task_evidence(catalog: Catalog, profile: Profile, candidates: list[Material]) -> dict[str, Evidence]:
    if catalog.task_index is None:
        return {}
    return catalog.task_index.match(profile.task, (material.id for material in candidates))


def _search_outcome(  # noqa: PLR0917, PLR0912, PLR0915 — search and its fallback use the same response
    catalog: Catalog,
    profile: Profile,
    parsed: ParsedTask,
    history: HistoryIndex,
    pool: list[Material],
    matches: TextMatches,
    observe: CandidateObserver | None,
) -> Outcome | None:
    topics = (profile.topic,) if profile.topic else parsed.topics
    scoped_pool = [m for m in pool if not profile.topic or profile.topic in m.topics]
    scoped = {m.id for m in scoped_pool}
    filter_options = None
    for index in (catalog.search_index, catalog.search_fallback):
        if index is None:
            return None
        try:
            reranked = index.mode == "reranked"
            if reranked:
                filtered_pool, filter_options = _filter_candidates(scoped_pool, profile.filters, None)
                constraints = parsed.gaps if not profile.topic and not parsed.concepts else ()
                hits = cast(RerankedIndex, index).match(
                    profile.task, {m.id for m in filtered_pool}, matches.titles, constraints
                )
                if len(filtered_pool) != len(scoped) and not hits:
                    return Outcome(
                        "personal", "weak", topics, [], [], 0, FILTERS_EMPTY_MESSAGE, None, [], filter_options
                    )
            else:
                filter_options = None
                if not profile.topic and parsed.gaps and not parsed.concepts:
                    return _title_match_outcome(catalog, profile, parsed, history, pool, "personal", observe)
                hits = index.match(profile.task, scoped, matches.titles)
            break
        except SearchUnavailable:
            continue
    else:
        return None
    if not hits:
        options = pool if not profile.topic else [m for m in pool if m.id in scoped]
        return _starter_outcome(
            method="personal",
            status="none",
            message="По этому запросу подходящих материалов не нашлось",
            pool=options,
            history=history,
            limit=profile.limit,
            detected=topics,
            by_level=levels_beyond_courses(catalog),
        )
    candidates = [m for m in pool if m.id in hits]
    ctx = Context(
        profile=profile,
        parsed=parsed,
        topics=topics,
        history=history,
        disabled=frozenset(catalog.disabled_features),
        catalog=catalog.materials,
    )
    protect_exact = cast(RerankedIndex, index).protect_exact if reranked else False
    ranked = personal.rank(candidates, ctx)
    positions = {item.material.id: i for i, item in enumerate(ranked)}
    max_score = max(hit.score for hit in hits.values()) or 1
    last = max(len(ranked) - 1, 1)

    def order(item: Scored) -> tuple[int, bool, float]:
        key = item.material.id
        hit = hits[key]
        exact = matches.priority(key) if key in matches.titles else 0
        if reranked:
            bonus = 0.015 * bool(exact) if not protect_exact else 0
            relevance = round((hit.score + bonus) / 0.025)
            return -exact if protect_exact and hit.strong else 0, False, -relevance
        score = 0.9 * hit.score / max_score + 0.1 * (1 - positions[key] / last)
        return -exact, not hit.strong, -score

    ranked.sort(key=order)
    filtered, hit_options = _filter_candidates(candidates, profile.filters, None)
    filter_options = filter_options or hit_options
    keys = {m.id for m in filtered}
    ranked = [item for item in ranked if item.material.id in keys]
    strong = hits[ranked[0].material.id].strong if ranked else any(hit.strong for hit in hits.values())
    if strong and not reranked:
        ranked = [item for item in ranked if hits[item.material.id].strong]
    if observe is not None:
        observe([item.material for item in ranked])
    items = ranked[: profile.limit]
    clarification = None
    message = (
        "Нашли материалы по задаче." if strong else "Нашли близкие материалы. Уточните действие или объект задачи."
    )
    if not items:
        message = FILTERS_EMPTY_MESSAGE
    elif not strong:
        available_topics = topics_with_materials(pool)
        clarification = (
            {
                "question": "Уточните задачу",
                "text": "Дополните запрос или выберите тему.",
                "options": _options(available_topics),
            }
            if available_topics
            else None
        )
    route = (
        explain.build_route(_route_window(ranked, profile.limit), catalog.materials)
        if (strong and _start_like(profile, parsed.stage_hint))
        else []
    )
    return Outcome(
        method="personal",
        status="strong" if strong else "weak",
        detected_topics=topics,
        items=items,
        reasons=[[hits[item.material.id].reason, *explain.personal_reasons(item, ctx)][:3] for item in items],
        total_candidates=len(ranked),
        message=message,
        clarification=clarification,
        route=route,
        filter_options=filter_options,
    )


def history_signals(catalog: Catalog, profile: Profile, parsed: ParsedTask, method: str) -> HistorySignals | None:
    """Данные истории для пилота «похожие курсы» или None, если пилот к запросу не применяется.

    Условие: персональный метод, пустая задача, загруженные пары и хотя бы один курс каталога в истории,
    доступный или нет. Задача с текстом и подбор по теме пилота не видят. Подбор по истории без выбранной
    темы требует ещё пары с допустимым курсом вне истории (`_history_outcome`).
    """
    if method != "personal" or not parsed.is_empty or catalog.course_pairs is None:
        return None
    if "co_enrollment" in catalog.disabled_features:
        return None
    signals = HistorySignals.build(profile.history, catalog.materials)
    return signals if signals.anchors else None


def _history_outcome(  # noqa: PLR0917 — shared request inputs
    catalog: Catalog,
    profile: Profile,
    parsed: ParsedTask,
    history: HistoryIndex,
    pool: list[Material],
    signals: HistorySignals,
    observe: CandidateObserver | None,
) -> Outcome | None:
    """Подбор по истории при пустой задаче (docs/plan.md, раздел 9, решение 2026-11-11).

    Кандидаты — материалы тем истории и курсы других тем, связанные парой совместных записей с курсом
    истории. Оценка — обычные признаки анкеты и истории без темы задачи, плюс тема истории и «похожие курсы».
    Статус weak: тема не выбрана, пользователь может её уточнить. Маршрута нет: он строится только при strong.

    Подбор включается, только если среди допустимых материалов есть курс с вкладом «похожих курсов»: пара
    от порога поддержки с курсом истории, у которого не меньше 10 слушателей. Такой курс вне истории, то
    есть новый для пользователя. Иначе функция возвращает None, и ответ остаётся прежней стартовой подборкой:
    подбор по истории без пары показал бы только темы истории, а без нового материала только карточки с
    пометкой «Пройдено» (уточнение решения 2026-11-11 после ревью, вывод O1: кандидатов не ограничивать
    темами истории).
    """
    ctx = Context(
        profile=profile,
        parsed=parsed,
        topics=(),
        history=history,
        disabled=frozenset(catalog.disabled_features),
        catalog=catalog.materials,
        pairs=catalog.course_pairs,
        anchors=signals.anchors,
        history_topics=signals.topics,
    )
    linked_ids = {m.id for m in pool if personal.co_enrollment(m, ctx)[1] is not None}
    if not linked_ids:
        return None
    wanted = set(signals.topics)
    candidates = [m for m in pool if wanted & set(m.topics) or m.id in linked_ids]
    candidates, filter_options = _filter_candidates(candidates, profile.filters, observe)
    ranked = personal.rank(candidates, ctx)
    items = ranked[: profile.limit]
    covered = tuple(t for t in signals.topics if any(t in m.topics for m in candidates))
    linked = [m for m in candidates if not wanted & set(m.topics)]
    sources = {anchor for m in linked for anchor in personal.co_enrollment_anchors(m, ctx)}
    options = _first(topics_with_materials(pool), signals.topics)
    clarification = None
    if options:
        clarification = {
            "question": explain.HISTORY_QUESTION,
            "text": explain.HISTORY_CLARIFICATION_TEXT,
            "options": _options(options),
        }
    return Outcome(
        method="personal",
        status="weak",
        detected_topics=(),
        items=items,
        reasons=[explain.personal_reasons(i, ctx) for i in items],
        total_candidates=len(candidates),
        message=explain.history_results_message(
            topics=covered,
            total=len(candidates),
            linked_courses=len(linked),
            linked_sources=len(sources),
            items=items,
            ctx=ctx,
        )
        if candidates
        else FILTERS_EMPTY_MESSAGE,
        clarification=clarification,
        filter_options=filter_options,
        route=[],
    )


def recommend(  # noqa: C901, PLR0911, PLR0912, PLR0915 — dispatch among search, topic and history outcomes
    catalog: Catalog, profile: Profile, method: str = "personal", *, observe: CandidateObserver | None = None
) -> Outcome:
    if method not in METHODS:
        raise ValueError(f"unknown method {method}")
    parsed = parse_task(profile.task)
    history = HistoryIndex.build(profile.history)
    pool = eligible(catalog, history)
    explicit = profile.topic is not None
    topics = (profile.topic,) if profile.topic is not None else parsed.topics
    pilot = history_signals(catalog, profile, parsed, method)
    if pilot is not None and not explicit:
        outcome = _history_outcome(catalog, profile, parsed, history, pool, pilot, observe)
        if outcome is not None:
            return outcome

    if (
        not explicit
        and parsed.gaps
        and not parsed.concepts
        and (method == "baseline" or not catalog.search_index or catalog.search_index.mode != "reranked")
    ):
        return _title_match_outcome(catalog, profile, parsed, history, pool, method, observe)

    matches = catalog.text_index.match(profile.task) if method == "personal" and catalog.text_index else TextMatches()
    if method == "personal" and catalog.search_index is not None and profile.task.strip():
        outcome = _search_outcome(catalog, profile, parsed, history, pool, matches, observe)
        if outcome is not None:
            return outcome
    if not explicit and parsed.gaps and not parsed.concepts:
        return _title_match_outcome(catalog, profile, parsed, history, pool, method, observe)

    # Тема выведена из понятия признака, сама задача её не называет
    signal_only = parsed.topics_from_signals and not explicit
    if signal_only:
        if method == "personal":
            outcome = _signal_outcome(catalog, profile, parsed, history, pool, matches, observe)
            if outcome is not None:
                return outcome
        # Без распознанной темы остаётся поиск по названиям или стартовая подборка.
        topics = ()

    text_candidates = [m for m in pool if m.id in matches.titles] if not topics and matches.titles else []
    if not topics and not text_candidates:
        if parsed.is_empty:
            return _starter_outcome(
                method=method,
                status="cold",
                message=explain.COLD_MESSAGE,
                pool=pool,
                history=history,
                limit=profile.limit,
                detected=(),
                by_level=levels_beyond_courses(catalog),
            )
        return _starter_outcome(
            method=method,
            status="none",
            message=explain.none_message(
                profile.task, gaps=parsed.gaps, baseline_without_topic=signal_only and method == "baseline"
            ),
            pool=pool,
            history=history,
            limit=profile.limit,
            detected=(),
            by_level=levels_beyond_courses(catalog),
            preferred=parsed.topics if signal_only else (),
        )

    candidates = text_candidates or [m for m in pool if set(m.topics) & set(topics)]
    if not candidates:
        return _starter_outcome(
            method=method,
            status="none",
            message=explain.no_materials_text(topics),
            pool=pool,
            history=history,
            limit=profile.limit,
            detected=topics,
            by_level=levels_beyond_courses(catalog),
        )

    # Статус и варианты уточнения опираются на темы исходных кандидатов.
    covered = tuple(t for t in topics if any(t in m.topics for m in candidates))
    missing = tuple(t for t in topics if t not in covered)
    original_count = len(candidates)
    candidates, filter_options = _filter_candidates(candidates, profile.filters, observe)
    filtered_topics = tuple(t for t in covered if any(t in m.topics for m in candidates))
    ctx = Context(
        profile=profile,
        parsed=parsed,
        topics=filtered_topics,
        history=history,
        disabled=frozenset(catalog.disabled_features),
        catalog=catalog.materials,
        pairs=catalog.course_pairs if pilot else None,
        anchors=pilot.anchors if pilot else (),
    )
    evidence = _task_evidence(catalog, profile, candidates) if method == "personal" else {}
    ranked = (
        _rank_personal(candidates, ctx, matches, evidence) if method == "personal" else baseline.rank(candidates, ctx)
    )
    items = ranked[: profile.limit]

    if explicit or text_candidates:
        status = "strong"
    elif len(covered) >= MIN_AMBIGUOUS_TOPICS or parsed.gaps:
        status = "weak"
    else:
        status = "strong"

    clarification = None
    if status == "weak":
        options = (
            list(covered)
            if len(covered) >= MIN_AMBIGUOUS_TOPICS
            else list(covered) + [t for t in topics_with_materials(pool, order=vocab.CHIP_TOPICS) if t not in covered]
        )
        clarification = {
            "question": "Уточните тему",
            "text": explain.weak_clarification_text(covered, parsed.gaps)
            if len(candidates) == original_count
            else "Выберите тему, чтобы уточнить подбор.",
            "options": _options(options),
        }

    route: list[Material] = []
    if method == "personal" and status == "strong" and _start_like(profile, parsed.stage_hint):
        route = explain.build_route(_route_window(ranked, profile.limit), catalog.materials)

    signal = next((i.matched_signal for i in items if i.matched_signal), None)
    message = FILTERS_EMPTY_MESSAGE
    if candidates and text_candidates:
        message = explain.title_results_message(
            method=method, total=len(candidates), items=items, ctx=ctx, text_order=True
        )
    elif candidates:
        message = explain.results_message(
            method=method,
            topics=filtered_topics,
            total=len(candidates),
            items=items,
            ctx=ctx,
            signal=signal,
            missing=missing,
            text_order=any(matches.priority(item.material.id) for item in items),
            task_order=any(item.material.id in evidence for item in items),
        )
    if method == "personal":
        reasons = _personal_reasons(items, ctx, matches, evidence)
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
