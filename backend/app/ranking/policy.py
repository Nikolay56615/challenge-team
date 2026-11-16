"""Политика выдачи: допустимость, статусы, уточнения и стартовая подборка.

Пилот «похожие курсы» действует только при пустой задаче
и только в персональном методе, поэтому выдача по задаче с текстом и подбор по теме от него не зависят:
- подбор по истории — пустая задача, тема не выбрана, пары загружены, в истории есть курс каталога
  и хотя бы один курс истории связан парой с допустимым курсом вне истории: кандидаты — материалы тем
  истории и курсы, связанные парой с курсом истории; статус weak с выбором темы. Иначе остаётся прежняя
  стартовая подборка: без такой пары подбор по истории не показал бы ни одного «похожего курса»
  (уточнение решения 2026-11-11 после ревью: P12 с парами ниже порога получает холодный старт);
- явно выбранная тема при пустой задаче — обычный подбор по теме и вклад co_enrollment для курсов темы.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .. import vocab
from ..catalog.lexicon import ParsedTask, parse_task, title_matches_gaps
from ..catalog.models import Catalog, Material
from . import baseline, explain, personal
from .base import Context, HistoryIndex, HistorySignals, Profile, Scored

METHODS = ("personal", "baseline")
# С двух тем с кандидатами задача неоднозначна: статус weak и выбор между этими темами
MIN_AMBIGUOUS_TOPICS = 2


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


@dataclass(frozen=True, slots=True)
class _Request:
    """Запрос к политике: каталог, профиль, разбор задачи, история, допустимые материалы и метод."""

    catalog: Catalog
    profile: Profile
    parsed: ParsedTask
    history: HistoryIndex
    pool: list[Material]
    method: str


def _duplicate_key(material: Material) -> tuple[str, str]:
    return " ".join(material.title.casefold().split()), material.format


def eligible(catalog: Catalog, history: HistoryIndex) -> list[Material]:
    """Фильтр допустимости: доступные материалы без дубликатов и без купленных.

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


def topics_with_materials(pool: list[Material]) -> list[str]:
    present = {t for m in pool for t in m.topics}
    return [t for t in vocab.CHIP_TOPICS if t in present]


def levels_beyond_courses(catalog: Catalog) -> bool:
    """Размечен ли уровень не только у курсов. В копии он есть только у курсов."""
    return any(m.level for m in catalog.materials.values() if m.format != "course")


def _start_stage(material: Material) -> bool:
    """Стадия старта или без стадии; продвинутый уровень в стартовую подборку не берётся."""
    starts = not material.stages or bool({"idea", "start"} & set(material.stages))
    return starts and material.level != "advanced"


def starter_selection(pool: list[Material], history: HistoryIndex, *, by_level: bool = True) -> list[Scored]:
    """Самый популярный вводный бесплатный материал по каждой теме с чипом.

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


def _starter_outcome(
    request: _Request, *, status: str, message: str, detected: tuple[str, ...], preferred: tuple[str, ...] = ()
) -> Outcome:
    method, pool = request.method, request.pool
    picks = starter_selection(pool, request.history, by_level=levels_beyond_courses(request.catalog))
    options = _first(topics_with_materials(pool), preferred)
    if not picks and not options:
        return Outcome(
            method=method, status="empty", detected_topics=detected, items=[], reasons=[], total_candidates=0,
            message=explain.EMPTY_MESSAGE, clarification=None, route=[],
        )
    items = picks[: request.profile.limit]
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


def _signal_outcome(request: _Request) -> Outcome | None:
    """Задача называет понятие признака, но не тему («Какую CRM выбрать»): кандидаты — материалы с этим
    признаком из любых тем, без вклада темы. Понятия берутся из `parsed.concepts` — признаков, названных
    достаточно конкретно; широкие слова вроде «эффективно» материалы сами не отбирают. Если материалов
    с понятием нет, возвращается None, и подбор отвечает статусом none: сообщение, выбор темы и
    стартовая подборка."""
    catalog, profile, parsed = request.catalog, request.profile, request.parsed
    disabled = frozenset(catalog.disabled_features)
    if "signal" in disabled or not parsed.concepts:
        return None
    wanted = set(parsed.concepts)
    candidates = [m for m in request.pool if wanted & {code for code, _ in m.signals}]
    if not candidates:
        return None
    # Вклад признака и причина считаются только по понятиям, отобравшим кандидатов
    focused = replace(parsed, signals=parsed.concepts)
    ctx = Context(
        profile=profile, parsed=focused, topics=(), history=request.history, disabled=disabled,
        catalog=catalog.materials,
    )
    ranked = personal.rank(candidates, ctx)
    items = ranked[: profile.limit]
    found = tuple(s for s in parsed.concepts if any(s in {code for code, _ in m.signals} for m in candidates))
    missing = tuple(s for s in parsed.concepts if s not in found)
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
        ),
        clarification=None,
        route=route,
    )


def _title_match_outcome(request: _Request) -> Outcome:
    catalog, profile, parsed, method = request.catalog, request.profile, request.parsed, request.method
    topics = set(parsed.topics)
    candidates = [
        material for material in request.pool
        if (method == "personal" or topics.intersection(material.topics))
        and title_matches_gaps(material.title, parsed.gaps)
    ]
    if not candidates:
        return _starter_outcome(
            request, status="none", message=explain.NO_TITLE_MATCH_MESSAGE, detected=parsed.topics
        )

    ctx = Context(
        profile=profile, parsed=parsed, topics=parsed.topics if method == "baseline" else (),
        history=request.history, disabled=frozenset(catalog.disabled_features), catalog=catalog.materials,
    )
    ranked = personal.rank(candidates, ctx) if method == "personal" else baseline.rank(candidates, ctx)
    items = ranked[:profile.limit]
    route: list[Material] = []
    if method == "personal" and _start_like(profile, parsed.stage_hint):
        route = explain.build_route(_route_window(ranked, profile.limit), catalog.materials)
    # Персональная причина сокращается вместе с фразой отбора по названию: правило о фразе D01 (explain.py)
    # тогда видит итоговую причину
    lead = explain.title_match_phrase(parsed.gaps)
    reasons = (
        [explain.personal_reasons(item, ctx, lead=lead) for item in items]
        if method == "personal"
        else [explain.title_match_reasons(parsed.gaps, explain.baseline_reasons(item)) for item in items]
    )
    return Outcome(
        method=method, status="strong", detected_topics=parsed.topics, items=items,
        reasons=reasons,
        total_candidates=len(candidates),
        message=explain.title_results_message(method=method, total=len(candidates), items=items, ctx=ctx),
        clarification=None, route=route,
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


def _history_outcome(request: _Request, signals: HistorySignals) -> Outcome | None:
    """Подбор по истории при пустой задаче.

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
    catalog, profile, pool = request.catalog, request.profile, request.pool
    ctx = Context(
        profile=profile, parsed=request.parsed, topics=(), history=request.history,
        disabled=frozenset(catalog.disabled_features), catalog=catalog.materials, pairs=catalog.course_pairs,
        anchors=signals.anchors, history_topics=signals.topics,
    )
    linked_ids = {m.id for m in pool if personal.co_enrollment(m, ctx)[1] is not None}
    if not linked_ids:
        return None
    wanted = set(signals.topics)
    candidates = [m for m in pool if wanted & set(m.topics) or m.id in linked_ids]
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
            topics=covered, total=len(candidates), linked_courses=len(linked), linked_sources=len(sources),
            items=items, ctx=ctx,
        ),
        clarification=clarification,
        route=[],
    )


def recommend(catalog: Catalog, profile: Profile, method: str = "personal") -> Outcome:
    if method not in METHODS:
        raise ValueError(f"unknown method {method}")
    parsed = parse_task(profile.task)
    history = HistoryIndex.build(profile.history)
    request = _Request(
        catalog=catalog, profile=profile, parsed=parsed, history=history, pool=eligible(catalog, history),
        method=method,
    )
    explicit = profile.topic is not None
    topics: tuple[str, ...] = (profile.topic,) if profile.topic is not None else parsed.topics
    pilot = history_signals(catalog, profile, parsed, method)

    if pilot is not None and not explicit:
        outcome = _history_outcome(request, pilot)
        if outcome is not None:
            return outcome

    if not explicit and parsed.gaps and not parsed.concepts:
        return _title_match_outcome(request)

    # Тема выведена из понятия признака, сама задача её не называет
    signal_only = parsed.topics_from_signals and not explicit
    if signal_only:
        if method == "personal":
            outcome = _signal_outcome(request)
            if outcome is not None:
                return outcome
        # Подбор по теме признаков не видит; если материалов с понятием нет, ответ — статус none
        # с сообщением, выбором темы и стартовой подборкой
        topics = ()

    if not topics:
        return _no_topic_outcome(request, signal_only=signal_only)
    return _topic_outcome(request, topics, pilot)


def _no_topic_outcome(request: _Request, *, signal_only: bool) -> Outcome:
    """Тема не распознана: при пустой задаче — холодный старт, иначе статус none со стартовой подборкой."""
    parsed = request.parsed
    if parsed.is_empty:
        return _starter_outcome(request, status="cold", message=explain.COLD_MESSAGE, detected=())
    message = explain.none_message(
        request.profile.task, gaps=parsed.gaps, baseline_without_topic=signal_only and request.method == "baseline"
    )
    preferred = parsed.topics if signal_only else ()
    return _starter_outcome(request, status="none", message=message, detected=(), preferred=preferred)


def _topic_status(*, explicit: bool, covered: tuple[str, ...], gaps: tuple[str, ...]) -> str:
    """Явно выбранная тема — strong; несколько тем с кандидатами или слово-пробел — weak."""
    if explicit:
        return "strong"
    if len(covered) >= MIN_AMBIGUOUS_TOPICS or gaps:
        return "weak"
    return "strong"


def _weak_clarification(covered: tuple[str, ...], gaps: tuple[str, ...], pool: list[Material]) -> dict[str, Any]:
    """Уточнение при статусе weak: темы с кандидатами, а при одной теме — ещё прочие темы с материалами."""
    options = list(covered) if len(covered) >= MIN_AMBIGUOUS_TOPICS else list(covered) + [
        t for t in topics_with_materials(pool) if t not in covered
    ]
    return {
        "question": "Уточните тему",
        "text": explain.weak_clarification_text(covered, gaps),
        "options": _options(options),
    }


def _topic_outcome(request: _Request, topics: tuple[str, ...], pilot: HistorySignals | None) -> Outcome:
    """Подбор по распознанным или выбранной темам."""
    catalog, profile, parsed, method = request.catalog, request.profile, request.parsed, request.method
    candidates = [m for m in request.pool if set(m.topics) & set(topics)]
    if not candidates:
        return _starter_outcome(request, status="none", message=explain.no_materials_text(topics), detected=topics)

    # Статус, строка состояния и уточнение опираются на темы с кандидатами; распознанные темы
    # без материалов называются в строке состояния
    covered = tuple(t for t in topics if any(t in m.topics for m in candidates))
    missing = tuple(t for t in topics if t not in covered)
    # Явно выбранная тема при пустой задаче и курсе в истории: кандидаты в пределах темы, курсы темы
    # получают вклад «похожих курсов». Темы истории не добавляются: тема уже выбрана
    ctx = Context(
        profile=profile,
        parsed=parsed,
        topics=covered,
        history=request.history,
        disabled=frozenset(catalog.disabled_features),
        catalog=catalog.materials,
        pairs=catalog.course_pairs if pilot is not None else None,
        anchors=pilot.anchors if pilot is not None else (),
    )
    ranked = personal.rank(candidates, ctx) if method == "personal" else baseline.rank(candidates, ctx)
    items = ranked[: profile.limit]

    status = _topic_status(explicit=profile.topic is not None, covered=covered, gaps=parsed.gaps)
    clarification = _weak_clarification(covered, parsed.gaps, request.pool) if status == "weak" else None

    route: list[Material] = []
    if method == "personal" and status == "strong" and _start_like(profile, parsed.stage_hint):
        route = explain.build_route(_route_window(ranked, profile.limit), catalog.materials)

    signal = next((i.matched_signal for i in items if i.matched_signal), None)
    message = explain.results_message(
        method=method, topics=covered, total=len(candidates), items=items, ctx=ctx, signal=signal, missing=missing
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
    )
