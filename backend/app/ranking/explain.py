"""Причины, следующий шаг, маршрут и тексты выдачи (docs/plan.md, 3.5–3.6).

Причины персонального подбора объясняют положительные вклады, разрешение равенств по популярности
и отбор по названию для узких задач. Фразы пилота «похожие курсы» (docs/plan.md, раздел 9, решение
2026-11-11) — тема истории и совместные записи — тоже называют только положительные вклады.
Фраза о признаке из текста цитирует слова задачи, по которым признак найден (кандидат D01, решение
2026-11-11); если цитата вытеснила бы другую фразу, остаётся фраза без цитаты. Правила микротекстов D19
проверяет tests/test_microcopy.py.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .. import vocab
from ..catalog.lexicon import signal_quote
from ..catalog.models import Material
from .base import FEATURE_PRIORITY, Context, Scored

MAX_REASON_PHRASES = 3
# Две–три фразы: фраза о теме опускается, только если остаётся не меньше двух, а фраза
# о востребованности добавляется к причине короче двух фраз
MIN_REASON_PHRASES = 2
# Части общей фразы «Подходит для …» — стадия и сфера; объединяются, только если есть обе
FIT_PARTS = 2
MAX_REASON_CHARS = 180
POPULARITY_PHRASE = "Один из самых востребованных материалов по теме"
ROUTE_TITLE = "Маршрут на первую неделю"
ROUTE_MAX_STEPS = 3
# Маршрут из одного материала ничего не связывает: его нет
ROUTE_MIN_STEPS = 2
TASK_ECHO_CHARS = 80
QUOTED_TITLE_CHARS = 60
# Цитата слов задачи во фразе о признаке (D01): не длиннее 30 символов, затем «…»
TASK_WORDS_CHARS = 30
# Фраза темы истории в подборе по истории (docs/plan.md, раздел 9, решение 2026-11-11). Начало отличается
# от фразы темы задачи «Тема «…» совпадает с задачей»: при пустой задаче с задачей совпадать нечему
HISTORY_TOPIC_PREFIX = "Тема из вашей истории: "
COURSE_PREFIX = "Курс «"

# Служебные слова, на которых не обрывается сокращённое название
_DANGLING_WORDS = frozenset({
    "а", "без", "в", "во", "для", "до", "за", "и", "из", "или", "к", "ко", "на", "не", "но", "о", "об", "от",
    "по", "при", "с", "со", "у",
})

# Подсказка стадии из текста в строке состояния
STAGE_HINT_LABELS: dict[str, str] = {"start": "старт", "growth": "рост бизнеса"}


def plural(n: int, one: str, few: str, many: str) -> str:
    # Числа в сравнениях — само правило согласования русских числительных: 1, 21 — но 11; 2–4, 22 — но 12–14
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:  # noqa: PLR2004
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:  # noqa: PLR2004
        return few
    return many


def join_ru(parts: list[str], conj: str = "и") -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} {conj} {parts[-1]}"


def quoted(labels: list[str]) -> list[str]:
    return [f"«{label}»" for label in labels]


def inner_quotes(text: str) -> str:
    """Кавычки внутри кавычек по правилам русской типографики: «…» → „…“."""
    return text.replace("«", "„").replace("»", "“")


def short_title(title: str, limit: int = QUOTED_TITLE_CHARS) -> str:
    """Название для цитаты внутри фразы: не длиннее `limit` символов и «…».

    Обрезка идёт по границе слова, без висящего предлога или союза. Если осталась открытая
    кавычка, она закрывается после многоточия.
    """
    text = " ".join(title.split())
    if len(text) <= limit:
        return text
    head = text[: limit + 1]
    space = head.rfind(" ")
    if space < limit // 2:
        head = text[:limit]
    else:
        words = head[:space].split(" ")
        while len(words) > 1 and words[-1].casefold() in _DANGLING_WORDS:
            words.pop()
        head = " ".join(words)
    short = head.rstrip(" ,.:;!?—–-«„(") + "…"
    if short.count("«") > short.count("»"):
        short += "»"
    return short


def no_materials_text(topics: Sequence[str]) -> str:
    """«По теме «…» материалов пока нет» или «По темам «…» и «…» материалов пока нет», без точки."""
    where = "По теме" if len(topics) == 1 else "По темам"
    return f"{where} {join_ru(quoted([vocab.topic_label(t) for t in topics]))} материалов пока нет"


def _stage_phrase(ctx: Context) -> str | None:
    if ctx.profile.stage:
        return vocab.STAGES[ctx.profile.stage][1]
    return None


def _industry_phrase(ctx: Context) -> str | None:
    code = ctx.industry
    return vocab.INDUSTRIES[code][1] if code in vocab.INDUSTRIES else None


def topic_phrase(topic: str, ctx: Context) -> str:
    """Фраза о теме. Тема, выбранная в уточнении, которую задача не называет, с задачей не совпадает:
    при пустой задаче или после ответа none («Как оформить наследство» → «Старт бизнеса») фраза называет
    выбор пользователя."""
    label = vocab.topic_label(topic)
    if ctx.profile.topic is not None and topic not in ctx.parsed.topics:
        return f"Вы выбрали тему «{label}»"
    return f"Тема «{label}» совпадает с задачей"


def signal_phrase(code: str, task: str, *, concept: bool = False) -> str:
    """Фраза о признаке из текста (docs/plan.md, 3.6; кандидат D01, решение 2026-11-11).

    Если слова, по которым найден признак, есть в задаче, фраза цитирует их так, как их написал
    пользователь: «В задаче вы назвали «CRM» — материал о теме «Работа с CRM и клиентской базой»».
    `concept` — задача называет признак как понятие: цитируются слова понятия, а не широкое слово
    («CAC», а не «эффективно»). Цитата сокращается, как название, до TASK_WORDS_CHARS символов. Без цитаты
    остаётся прежняя фраза «Материал о теме «…»».
    """
    label = vocab.signal_label(code)
    words = signal_quote(task, code, concept=concept)
    if words:
        return f"В задаче вы назвали «{short_title(words, TASK_WORDS_CHARS)}» — материал о теме «{label}»"
    return f"Материал о теме «{label}»"


def _topic_reason(item: Scored, ctx: Context) -> str | None:
    return topic_phrase(item.matched_topic, ctx) if item.matched_topic else None


def _signal_reason(item: Scored, ctx: Context) -> str | None:
    code = item.matched_signal
    if not code:
        return None
    return signal_phrase(code, ctx.profile.task, concept=code in ctx.parsed.concepts)


def _stage_reason(_: Scored, ctx: Context) -> str | None:
    stage = _stage_phrase(ctx)
    if stage:
        return f"Подходит для стадии «{stage}»"
    if ctx.stage_hint == "growth":
        return "Похоже, бизнес растёт — материал рассчитан на это"
    return "Похоже, вы на старте — материал рассчитан на это"


def _level_reason(item: Scored, _: Context) -> str | None:
    if item.level_direction > 0:
        return "На шаг глубже вашего уровня — пригодится как продолжение"
    if item.level_direction < 0:
        return "На шаг проще вашего уровня — подойдёт для повторения"
    return None


def _industry_reason(_: Scored, ctx: Context) -> str | None:
    industry = _industry_phrase(ctx)
    return f"Подходит для сферы «{industry}»" if industry else None


def _continuation_reason(item: Scored, ctx: Context) -> str | None:
    source = ctx.catalog.get(item.continuation_of) if item.continuation_of else None
    if source is None:
        return None
    return f"Продолжает материал «{inner_quotes(short_title(source.title))}» из вашей истории"


def _in_progress_reason(item: Scored, _: Context) -> str | None:
    if item.material.format == "course":
        return "Вы начали этот курс — продолжите с текущего урока"
    return "Вы начали этот материал — продолжите с того же места"


def _history_topic_reason(item: Scored, _: Context) -> str | None:
    if not item.history_topic:
        return None
    return f"{HISTORY_TOPIC_PREFIX}«{vocab.topic_label(item.history_topic)}»"


def _co_enrollment_reason(item: Scored, ctx: Context) -> str | None:
    pair = item.co_enrollment
    if not pair:
        return None
    return co_enrollment_phrase(pair.together, pair.total, pair.anchor, ctx)


# Фраза признака с положительным вкладом. Формат и усилие фразы не дают: их показывают бейджи карточки
_REASONS: dict[str, Callable[[Scored, Context], str | None]] = {
    "topic": _topic_reason,
    "signal": _signal_reason,
    "stage": _stage_reason,
    "level": _level_reason,
    "industry": _industry_reason,
    "continuation": _continuation_reason,
    "in_progress": _in_progress_reason,
    "history_topic": _history_topic_reason,
    "co_enrollment": _co_enrollment_reason,
}


def _phrase(feature: str, item: Scored, ctx: Context) -> str | None:
    reason = _REASONS.get(feature)
    return reason(item, ctx) if reason is not None else None


def course_name(title: str) -> str:
    """Название курса после слова «курса»: «Курс «Старт»» → «Старт», иначе название целиком.

    Так фраза не повторяет «курса «Курс …»». Название сокращается и получает внутренние кавычки, как в
    фразе о продолжении.
    """
    text = " ".join(title.split())
    if text.startswith(COURSE_PREFIX) and text.endswith("»") and _balanced(text[len(COURSE_PREFIX):-1]):
        text = text[len(COURSE_PREFIX):-1]
    return inner_quotes(short_title(text))


def _balanced(text: str) -> bool:
    """Кавычки «…» внутри текста закрыты по порядку: «Курс «A» и «B»» не превратится в «A» и «B»."""
    depth = 0
    for char in text:
        depth += {"«": 1, "»": -1}.get(char, 0)
        if depth < 0:
            return False
    return depth == 0 and bool(text.strip())


def co_enrollment_phrase(together: int, total: int, anchor: str, ctx: Context) -> str | None:
    """«Этот курс выбрали N из M слушателей курса «X» из вашей истории» (R18 в части курсов).

    N — слушатели обоих курсов, M — все слушатели курса истории X. Без «часто»: при пороге поддержки
    10 доля бывает и 10 %, а фраза называет число, а не оценку.
    """
    source = ctx.catalog.get(anchor)
    if source is None:
        return None
    verb = plural(together, "выбрал", "выбрали", "выбрали")
    listeners = plural(total, "слушателя", "слушателей", "слушателей")  # «из 21 слушателя», «из 120 слушателей»
    name = course_name(source.title)
    return f"Этот курс {verb} {together} из {total} {listeners} курса «{name}» из вашей истории"


def _length(entries: list[tuple[str, str]]) -> int:
    return sum(len(phrase) for _, phrase in entries) + 2 * (len(entries) - 1)


def _fit_entries(entries: list[tuple[str, str]], protected: str | None = None) -> list[tuple[str, str]]:
    """Не больше трёх фраз и 180 символов вместе с разделителями.

    `entries` — пары (признак, фраза) от сильной к слабой. Лишнее отбрасывается со слабого конца,
    фраза о теме тоже. Сильнейшая фраза, кроме темы, остаётся всегда (docs/plan.md, 3.6). Исключение —
    `protected`: фраза этого признака остаётся при любом сокращении, на своём месте по вкладу, а
    сильнейшая другая уходит последней. Так курс другой темы в подборе по истории всегда объясняет, откуда
    он взялся (docs/plan.md, раздел 9, решение 2026-11-11).
    """
    guard = next((entry for entry in entries if entry[0] == protected), None) if protected else None
    if guard is not None and entries.index(guard) >= MAX_REASON_PHRASES:
        entries = [*entries[: MAX_REASON_PHRASES - 1], guard]
    else:
        entries = entries[:MAX_REASON_PHRASES]
    keep = guard or next((entry for entry in entries if entry[0] != "topic"), None)
    while len(entries) > 1 and _length(entries) > MAX_REASON_CHARS:
        drop = max(i for i, entry in enumerate(entries) if entry is not keep)
        del entries[drop]
    return entries


def _fit(entries: list[tuple[str, str]], protected: str | None = None) -> list[str]:
    return [phrase for _, phrase in _fit_entries(entries, protected)]


def _fit_reason(entries: list[tuple[str, str]], protected: str | None, lead: str | None) -> list[str]:
    """Причина в пределах 3.6. `lead` — фраза отбора по названию: она встаёт первой, а причина
    ранжирования сокращается второй раз вместе с ней, как в `title_match_reasons`."""
    fitted = _fit_entries(entries, protected)
    if lead is not None:
        fitted = _fit_entries([("title", lead), *fitted])
    return [phrase for _, phrase in fitted]


def _fit_parts(item: Scored, ctx: Context) -> list[tuple[str, str]]:
    """Части общей фразы «Подходит для …»: стадия из чипа и сфера.

    Уровень, формат и длительность не повторяются: их показывают бейджи карточки.
    """
    contributions = item.contributions
    parts: list[tuple[str, str]] = []
    stage = _stage_phrase(ctx)
    if stage and contributions.get("stage", 0) > 0:
        parts.append(("stage", f"стадии «{stage}»"))
    industry = _industry_phrase(ctx)
    if industry and contributions.get("industry", 0) > 0:
        parts.append(("industry", f"сферы «{industry}»"))
    return parts


def personal_reasons(item: Scored, ctx: Context, *, lead: str | None = None) -> list[str]:
    """Две–три фразы из признаков с положительным вкладом, по убыванию вклада.

    Стадия и сфера объединяются в одну фразу «Подходит для …». Уровень, формат и длительность
    не повторяются: их показывают бейджи карточки. Фраза о теме
    опускается, если в выдаче одна тема и без неё остаётся не меньше двух фраз: тему уже
    называет строка состояния. Фразу о востребованности получает победитель равенства из тройки
    самых популярных кандидатов своей темы. Курс, который связан с запросом только парой совместных
    записей (ни темы задачи, ни темы истории), сохраняет фразу о похожих курсах при сокращении.
    Фраза D01 с цитатой длиннее прежней «Материал о теме «…»»: если из-за неё пределы 3.6 вытеснили бы
    другую верную фразу, остаётся прежняя фраза, и фраз в причине не меньше, чем без цитаты.
    `lead` — фраза отбора по названию для узкой задачи (`title_match_phrase`).
    """
    contributions = item.contributions
    features = [f for f in FEATURE_PRIORITY if contributions.get(f, 0) > 0]
    parts = _fit_parts(item, ctx)
    merged = {feature for feature, _ in parts} if len(parts) >= FIT_PARTS else set()
    entries: list[tuple[float, int, str, str]] = []
    if merged:
        weight = max(contributions[f] for f in merged)
        priority = min(FEATURE_PRIORITY.index(f) for f in merged)
        entries.append((weight, priority, "fit", "Подходит для " + join_ru([text for _, text in parts])))
    for feature in features:
        if feature in merged:
            continue
        phrase = _phrase(feature, item, ctx)
        if phrase:
            entries.append((contributions[feature], FEATURE_PRIORITY.index(feature), feature, phrase))
    entries.sort(key=lambda e: (-e[0], e[1]))
    others = [e for e in entries if e[2] != "topic"]
    if len(ctx.topics) == 1 and len(others) >= MIN_REASON_PHRASES:
        entries = others
    chosen: list[tuple[str, str]] = []
    for _, _, feature, phrase in entries:
        if all(phrase != existing for _, existing in chosen):
            chosen.append((feature, phrase))
    if item.tie_won and item.popular_in_topic and len(chosen) < MIN_REASON_PHRASES:
        chosen.append(("popularity", POPULARITY_PHRASE))
    linked_only = item.co_enrollment is not None and item.history_topic is None and item.matched_topic is None
    protected = "co_enrollment" if linked_only else None
    reasons = _fit_reason(chosen, protected, lead)
    if item.matched_signal and any(feature == "signal" for feature, _ in chosen):
        plain = signal_phrase(item.matched_signal, "")
        brief = _fit_reason([(f, plain if f == "signal" else p) for f, p in chosen], protected, lead)
        if len(brief) > len(reasons):
            return brief
    return reasons


def baseline_reasons(item: Scored) -> list[str]:
    topic = item.matched_topic or (item.material.topics[0] if item.material.topics else None)
    return [f"Совпадает тема «{vocab.topic_label(topic)}»"] if topic else []


def starter_reasons(item: Scored) -> list[str]:
    return [f"Стартовый материал по теме «{vocab.topic_label(item.starter_topic)}»"] if item.starter_topic else []


def title_match_phrase(gaps: tuple[str, ...]) -> str:
    return f"В названии есть упоминание о {join_ru(list(gaps))}"


def title_match_reasons(gaps: tuple[str, ...], ranking_reasons: list[str]) -> list[str]:
    """Фраза отбора по названию и причина подбора по теме. Персональный метод передаёт фразу в
    `personal_reasons(..., lead=...)`: так правило о фразе D01 действует и после второго сокращения."""
    return _fit([("title", title_match_phrase(gaps)), *[("ranking", reason) for reason in ranking_reasons]])


DEFAULT_NEXT_STEP = "Откройте материал и отметьте главное"
# Длительность курса относится ко всему курсу, а шаг курса открывает программу и первый урок:
# время шага неизвестно
UNTIMED_STEP_FORMATS = frozenset({"course"})


STEP_HOURS_FROM = 120


def step_time(minutes: int) -> str:
    """Время шага после «около»: «около 1 минуты», «около 12 минут», «около 21 минуты».

    Единицы те же, что у бейджа длительности (formatDuration во фронтенде, docs/ui-kit.md, раздел 4):
    от 120 минут — часы и минуты, «около 2 часов 30 минут». Так карточка не называет одну длительность
    в разных единицах.
    """
    if minutes < STEP_HOURS_FROM:
        return f"около {minutes} {plural(minutes, 'минуты', 'минут', 'минут')}"
    hours, rest = divmod(minutes, 60)
    text = f"около {hours} {plural(hours, 'часа', 'часов', 'часов')}"
    return f"{text} {rest} {plural(rest, 'минуты', 'минут', 'минут')}" if rest else text


def next_step(material: Material) -> str:
    """Следующий шаг: из данных материала, иначе по шаблону формата (docs/plan.md, 3.6).

    Шаблон формата строится как «глагол + объект + время» (правила микротекстов D19; обзор, находки
    2.3 и 7.4): если длительность известна, шаг называет её в скобках: «Пройдите пункты и отметьте
    выполненное (около 15 минут)». Шаг из данных материала не меняется: время показывает бейдж карточки.
    """
    if material.next_step:
        return material.next_step
    step = vocab.NEXT_STEP_BY_FORMAT.get(material.format, DEFAULT_NEXT_STEP)
    if material.duration_minutes and material.format not in UNTIMED_STEP_FORMATS:
        return f"{step} ({step_time(material.duration_minutes)})"
    return step


def build_route(items: list[Scored], catalog: dict[str, Material]) -> list[Material]:
    """До трёх материалов из `items` по редакционным связям `recommended_next`, начиная с первого.

    Политика передаёт окно первой страницы, поэтому маршрут не зависит от `limit`.
    """
    pool = [i.material for i in items if "completed" not in i.flags]
    if len(pool) < ROUTE_MIN_STEPS:
        return []
    in_items = {m.id for m in pool}
    route = [pool[0]]
    while len(route) < ROUTE_MAX_STEPS:
        nxt = None
        for step in reversed(route):
            nxt = next((x for x in step.recommended_next if x in in_items and x not in {r.id for r in route}), None)
            if nxt:
                break
        if not nxt:
            break
        route.append(catalog[nxt])
    return route if len(route) >= ROUTE_MIN_STEPS else []


def short_task(task: str) -> str:
    text = " ".join(task.split())
    return text if len(text) <= TASK_ECHO_CHARS else text[: TASK_ECHO_CHARS - 1].rstrip() + "…"


def considered_parts(ctx: Context, history_used: bool) -> list[str]:
    """Поля анкеты, которые учитывает подбор. Опыт «новичок» действует и через усилие,
    даже если уровень в каталоге не размечен."""
    parts: list[str] = []
    profile = ctx.profile
    if profile.stage and "stage" not in ctx.disabled:
        parts.append(f"стадии «{vocab.STAGES[profile.stage][1]}»")
    novice_effort = profile.experience == "none" and "effort" not in ctx.disabled
    if profile.experience and ("level" not in ctx.disabled or novice_effort):
        parts.append(f"уровня «{vocab.EXPERIENCE[profile.experience][1]}»")
    if profile.format_pref:
        parts.append(f"формата «{vocab.FORMAT_PREFS[profile.format_pref][0].lower()}»")
    if profile.industry and "industry" not in ctx.disabled:
        parts.append(f"сферы «{vocab.INDUSTRIES[profile.industry][1]}»")
    if history_used:
        parts.append("истории")
    return parts


def task_hint_parts(ctx: Context, items: Sequence[Scored]) -> list[str]:
    """Что из описания задачи изменило оценку показанных материалов: стадия, уровень, формат, сфера.

    Используется, когда анкета не заполнена: подсказки из текста действуют вместо чипов.
    Усилие начисляется по подсказке «новичок», поэтому называется как уровень.
    """
    used = {feature for item in items for feature, value in item.contributions.items() if value > 0}
    parts: list[str] = []
    if "stage" in used and ctx.stage_hint in STAGE_HINT_LABELS:
        parts.append(STAGE_HINT_LABELS[ctx.stage_hint])
    level = vocab.level_label(ctx.level_hint)
    if used & {"level", "effort"} and level:
        parts.append(f"уровень «{level.lower()}»")
    if "format" in used and ctx.format_hint in vocab.FORMAT_PREFS:
        parts.append(f"формат «{vocab.FORMAT_PREFS[ctx.format_hint][0].lower()}»")
    industry = _industry_phrase(ctx)
    if "industry" in used and industry:
        parts.append(f"сфера «{industry}»")
    return parts


ASSUMPTION = "Стадия и опыт не указаны."


def _order_sentence(*, method: str, ctx: Context, items: Sequence[Scored], total: int, signal: str | None) -> str:
    """Чем задан порядок: профилем, описанием задачи или популярностью.

    Без анкеты строка называет допущение «стадия и опыт не указаны» (docs/plan.md, 3.4) и говорит
    о востребованности, только если порядок задали тема и популярность. Если материал один,
    о порядке не говорится.
    """
    shown = len(items)
    everything = shown >= total
    count = "все" if everything else str(shown)
    parts = considered_parts(ctx, history_used=bool(ctx.profile.history)) if method == "personal" else []
    if total <= 1:
        if method == "baseline":
            return "Подбор по теме не учитывает профиль и историю."
        return "" if parts else ASSUMPTION
    if method == "baseline":
        return f"Показываем {count} по популярности: подбор по теме не учитывает профиль и историю."
    if parts:
        return f"Показываем {count} с учётом {join_ru(parts)}."
    hints = task_hint_parts(ctx, items)
    assumption = ASSUMPTION
    if hints:
        # Ветка без полей анкеты: ни стадия, ни опыт, ни формат, ни сфера не выбраны, поэтому подсказки
        # из текста действуют вместо них. «Опыт не указан» звучало бы противоречием после «Я новичок»
        assumption = f"Уточнения не заполнены, поэтому порядок учитывает описание задачи: {join_ru(hints)}."
    if signal:
        return f"Показываем {count}, выше — материалы на тему «{vocab.signal_label(signal)}». {assumption}"
    if hints or any(f != "topic" and v > 0 for item in items for f, v in item.contributions.items()):
        return assumption
    if everything:
        return "Стадия и опыт не указаны, поэтому порядок — по востребованности."
    return f"Показываем {count} самых востребованных: стадия и опыт не указаны."


def _with_tail(head: str, tail: str) -> str:
    return f"{head} {tail}" if tail else head


def results_message(
    *,
    method: str,
    topics: tuple[str, ...],
    total: int,
    items: Sequence[Scored],
    ctx: Context,
    signal: str | None,
    missing: tuple[str, ...] = (),
) -> str:
    """Строка состояния для `strong` и `weak`.

    `topics` — распознанные темы, по которым нашлись кандидаты; `missing` — распознанные темы
    без материалов, о них сообщается честно.
    """
    labels = quoted([vocab.topic_label(t) for t in topics])
    word = plural(total, "материал", "материала", "материалов")
    where = f"по теме {labels[0]}" if len(labels) == 1 else f"по темам {join_ru(labels)}"
    head = f"Нашли {total} {word} {where}."
    if missing:
        head = f"{head} {no_materials_text(missing)}."
    return _with_tail(head, _order_sentence(method=method, ctx=ctx, items=items, total=total, signal=signal))


def _about(labels: list[str]) -> str:
    return f"на тему {labels[0]}" if len(labels) == 1 else f"на темы {join_ru(labels)}"


def signal_results_message(
    *,
    signals: Sequence[str],
    total: int,
    items: Sequence[Scored],
    ctx: Context,
    gaps: Sequence[str] = (),
    missing: Sequence[str] = (),
) -> str:
    """Строка состояния, когда задача называет понятие признака, но не тему: «Какую CRM выбрать».

    Все кандидаты несут найденное понятие, поэтому оговорка «выше — материалы на тему …» не нужна.
    Понятия задачи без материалов называются честно, как темы без материалов в `results_message`.
    """
    word = plural(total, "материал", "материала", "материалов")
    head = f"Нашли {total} {word} {_about(quoted([vocab.signal_label(s) for s in signals]))}."
    if missing:
        head = f"{head} Материалов {_about(quoted([vocab.signal_label(s) for s in missing]))} пока нет."
    if gaps:
        head = f"Материалов о {gaps[0]} пока нет. {head}"
    return _with_tail(head, _order_sentence(method="personal", ctx=ctx, items=items, total=total, signal=None))


def history_results_message(
    *, topics: Sequence[str], total: int, linked_courses: int, linked_sources: int, items: Sequence[Scored],
    ctx: Context,
) -> str:
    """Строка состояния подбора по истории при пустой задаче (docs/plan.md, раздел 9, решение 2026-11-11).

    `topics` — темы истории, по которым нашлись кандидаты; `linked_courses` — курсы других тем, которые
    попали в кандидаты по парам совместных записей; `linked_sources` — сколько курсов истории их связали.
    Порядок называется честно: с учётом истории. Пример: «Нашли 3 материала по теме «Продажи», знакомой
    по вашей истории, и 1 курс другой темы: его выбирали слушатели вашего курса».
    """
    by_topic = total - linked_courses
    parts: list[str] = []
    if topics and by_topic:
        labels = quoted([vocab.topic_label(t) for t in topics])
        if len(labels) == 1:
            where = f"по теме {labels[0]}, знакомой по вашей истории"
        else:
            where = f"по темам {join_ru(labels)}, знакомым по вашей истории"
        word = plural(by_topic, "материал", "материала", "материалов")
        parts.append(f"{by_topic} {word} {where}")
    if linked_courses:
        courses = f"{linked_courses} {plural(linked_courses, 'курс', 'курса', 'курсов')}"
        if parts:
            # Запятая закрывает оборот «знакомой по вашей истории» перед «и»
            parts[-1] += ","
            courses += " другой темы" if linked_courses == 1 else " других тем"
        parts.append(courses)
    head = f"Нашли {join_ru(parts)}"
    if linked_courses:
        pronoun = "его" if linked_courses == 1 else "их"
        source = "вашего курса" if linked_sources == 1 else "ваших курсов"
        head += f": {pronoun} выбирали слушатели {source}"
    order = _order_sentence(method="personal", ctx=ctx, items=items, total=total, signal=None)
    return _with_tail(f"{head}.", order)


def title_results_message(*, method: str, total: int, items: Sequence[Scored], ctx: Context) -> str:
    word = plural(total, "материал", "материала", "материалов")
    head = f"Нашли {total} {word} по совпадению в названии."
    return _with_tail(head, _order_sentence(method=method, ctx=ctx, items=items, total=total, signal=None))


def none_message(task: str, *, gaps: Sequence[str] = (), baseline_without_topic: bool = False) -> str:
    """Заголовок пустой выдачи без распознанной темы, без точки.

    Слово-пробел называется прямо: «Материалов о сертификации пока нет». Подбору по теме, который
    не видит понятий признаков, честнее сказать, что тема в запросе не найдена.
    """
    if gaps:
        return f"Материалов о {gaps[0]} пока нет"
    echo = inner_quotes(short_task(task))
    if baseline_without_topic:
        return f"Подбор по теме не нашёл тему в запросе «{echo}»"
    return f"По запросу «{echo}» материалов пока нет"


def weak_clarification_text(topics: tuple[str, ...], gaps: tuple[str, ...]) -> str:
    labels = quoted([vocab.topic_label(t) for t in topics])
    if gaps and len(topics) == 1:
        return (
            f"Материалов о {gaps[0]} пока нет. Показываем материалы по теме {labels[0]} на случай, если вопрос о них."
        )
    both = "обеим темам" if len(topics) == 2 else "всем этим темам"  # noqa: PLR2004 — «обеим» значит ровно две
    text = f"Задача может относиться к темам {join_ru(labels, 'или')}. Пока показываем материалы по {both}."
    if gaps:
        text = f"Материалов о {gaps[0]} пока нет. {text}"
    return text


def none_clarification_text(topics: list[str], *, has_starter: bool) -> str:
    labels = [vocab.topic_label(t).lower() for t in topics]
    action = (
        "Выберите тему, переформулируйте запрос или начните со стартовой подборки."
        if has_starter
        else "Выберите тему или переформулируйте запрос."
    )
    return f"Каталог покрывает темы: {', '.join(labels)}. {action}"


HISTORY_QUESTION = "Уточните тему"
HISTORY_CLARIFICATION_TEXT = (
    "Задача не указана, поэтому подбор опирается на вашу историю. Выберите тему или опишите задачу."
)
COLD_QUESTION = "С чего хотите начать?"
COLD_TEXT = "Выберите тему или опишите задачу."
COLD_STARTER_TEXT = f"{COLD_TEXT} Ниже — вводные бесплатные материалы по каждой теме."
COLD_MESSAGE = "Показываем вводные бесплатные материалы по каждой теме."
NO_TITLE_MATCH_MESSAGE = "По этому запросу подходящих материалов не нашлось"
EMPTY_MESSAGE = "Подходящих материалов не нашлось. Измените запрос."
