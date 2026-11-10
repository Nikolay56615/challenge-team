"""Причины, следующий шаг, маршрут и тексты выдачи (PLAN.md, 3.5–3.6).

Каждая фраза причины соответствует признаку с положительным вкладом. Исключение —
фраза о востребованности: её получает материал, который выиграл равенство оценок по популярности
и входит в тройку самых популярных кандидатов своей темы.
"""

from __future__ import annotations

from collections.abc import Sequence

from .. import vocab
from ..catalog.models import Material
from .base import FEATURE_PRIORITY, Context, Scored

MAX_REASON_PHRASES = 3
MAX_REASON_CHARS = 180
POPULARITY_PHRASE = "Один из самых востребованных материалов по теме"
ROUTE_TITLE = "Маршрут на первую неделю"
ROUTE_MAX_STEPS = 3
TASK_ECHO_CHARS = 80
QUOTED_TITLE_CHARS = 60

# Служебные слова, на которых не обрывается сокращённое название
_DANGLING_WORDS = frozenset({
    "а", "без", "в", "во", "для", "до", "за", "и", "из", "или", "к", "ко", "на", "не", "но", "о", "об", "от",
    "по", "при", "с", "со", "у",
})

# Подсказка стадии из текста в строке состояния
STAGE_HINT_LABELS: dict[str, str] = {"start": "старт", "growth": "рост бизнеса"}


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
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


def minutes_phrase(n: int) -> str:
    """«Займёт около N минут»: после «около» нужен родительный падеж — 1 и 21 минуты, 2 и 5 минут."""
    return f"Займёт около {n} {plural(n, 'минуты', 'минут', 'минут')}"


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


def _phrase(feature: str, item: Scored, ctx: Context) -> str | None:
    material = item.material
    if feature == "topic" and item.matched_topic:
        return f"Тема «{vocab.topic_label(item.matched_topic)}» совпадает с задачей"
    if feature == "signal" and item.matched_signal:
        return f"Материал о теме «{vocab.signal_label(item.matched_signal)}»"
    if feature == "stage":
        stage = _stage_phrase(ctx)
        if stage:
            return f"Подходит для стадии «{stage}»"
        if ctx.stage_hint == "growth":
            return "Похоже, бизнес растёт — материал рассчитан на это"
        return "Похоже, вы на старте — материал рассчитан на это"
    if feature == "level":
        label = (vocab.level_label(material.level) or "").lower()
        if ctx.profile.experience:
            if item.level_direction > 0:
                return "На шаг глубже вашего уровня — пригодится как продолжение"
            if item.level_direction < 0:
                return "На шаг проще вашего уровня — подойдёт для повторения"
            return f"Уровень «{label}» соответствует вашему опыту"
        return f"Уровень «{label}» подходит по описанию задачи"
    if feature == "industry":
        industry = _industry_phrase(ctx)
        return f"Подходит для сферы «{industry}»" if industry else None
    if feature == "format":
        label = vocab.format_label(material.format).lower()
        if ctx.profile.format_pref:
            return f"Формат «{label}» — как вы просили"
        return f"Формат «{label}» — как в описании задачи"
    if feature == "effort" and material.duration_minutes:
        return minutes_phrase(material.duration_minutes)
    if feature == "continuation" and item.continuation_of:
        source = ctx.catalog.get(item.continuation_of)
        if source is None:
            return None
        return f"Продолжает материал «{inner_quotes(short_title(source.title))}» из вашей истории"
    if feature == "in_progress":
        if material.format == "course":
            return "Вы начали этот курс — продолжите с текущего урока"
        return "Вы начали этот материал — продолжите с того же места"
    return None


def _length(entries: list[tuple[str, str]]) -> int:
    return sum(len(phrase) for _, phrase in entries) + 2 * (len(entries) - 1)


def _fit(entries: list[tuple[str, str]]) -> list[str]:
    """Не больше трёх фраз и 180 символов вместе с разделителями.

    `entries` — пары (признак, фраза) от сильной к слабой. Лишнее отбрасывается со слабого конца,
    фраза о теме тоже. Сильнейшая фраза, кроме темы, остаётся всегда (PLAN.md, 3.6).
    """
    entries = entries[:MAX_REASON_PHRASES]
    keep = next((entry for entry in entries if entry[0] != "topic"), None)
    while len(entries) > 1 and _length(entries) > MAX_REASON_CHARS:
        drop = max(i for i, entry in enumerate(entries) if entry is not keep)
        del entries[drop]
    return [phrase for _, phrase in entries]


def _fit_parts(item: Scored, ctx: Context) -> list[tuple[str, str]]:
    """Части общей фразы «Подходит для …»: стадия из чипа, точный уровень, сфера."""
    contributions = item.contributions
    parts: list[tuple[str, str]] = []
    stage = _stage_phrase(ctx)
    if stage and contributions.get("stage", 0) > 0:
        parts.append(("stage", f"стадии «{stage}»"))
    if ctx.profile.experience and contributions.get("level", 0) > 0 and item.level_direction == 0:
        parts.append(("level", f"уровня «{(vocab.level_label(item.material.level) or '').lower()}»"))
    industry = _industry_phrase(ctx)
    if industry and contributions.get("industry", 0) > 0:
        parts.append(("industry", f"сферы «{industry}»"))
    return parts


def personal_reasons(item: Scored, ctx: Context) -> list[str]:
    """Две–три фразы из признаков с положительным вкладом, по убыванию вклада.

    Стадия, точный уровень и сфера объединяются в одну фразу «Подходит для …». Фраза о теме
    опускается, если в выдаче одна тема и без неё остаётся не меньше двух фраз: тему уже
    называет строка состояния. Фразу о востребованности получает победитель равенства из тройки
    самых популярных кандидатов своей темы.
    """
    contributions = item.contributions
    features = [f for f in FEATURE_PRIORITY if contributions.get(f, 0) > 0]
    parts = _fit_parts(item, ctx)
    merged = {feature for feature, _ in parts} if len(parts) >= 2 else set()
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
    if len(ctx.topics) == 1 and len(others) >= 2:
        entries = others
    chosen: list[tuple[str, str]] = []
    for _, _, feature, phrase in entries:
        if all(phrase != existing for _, existing in chosen):
            chosen.append((feature, phrase))
    if item.tie_won and item.popular_in_topic and len(chosen) < 2:
        chosen.append(("popularity", POPULARITY_PHRASE))
    return _fit(chosen)


def baseline_reasons(item: Scored) -> list[str]:
    topic = item.matched_topic or (item.material.topics[0] if item.material.topics else None)
    return [f"Совпадает тема «{vocab.topic_label(topic)}»"] if topic else []


def starter_reasons(item: Scored) -> list[str]:
    phrases = [f"Стартовый материал по теме «{vocab.topic_label(item.starter_topic)}»"] if item.starter_topic else []
    if item.material.duration_minutes:
        phrases.append(minutes_phrase(item.material.duration_minutes))
    return phrases


def next_step(material: Material) -> str:
    return material.next_step or vocab.NEXT_STEP_BY_FORMAT.get(material.format, "Откройте материал и отметьте главное")


def build_route(items: list[Scored], catalog: dict[str, Material]) -> list[Material]:
    """До трёх материалов из `items` по редакционным связям `recommended_next`, начиная с первого.

    Политика передаёт окно первой страницы, поэтому маршрут не зависит от `limit`.
    """
    pool = [i.material for i in items if "completed" not in i.flags]
    if len(pool) < 2:
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
    return route if len(route) >= 2 else []


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

    Без анкеты строка называет допущение «стадия и опыт не указаны» (PLAN.md, 3.4) и говорит
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
        return f"Материалов о {gaps[0]} пока нет. Показываем материалы по теме {labels[0]} на случай, если вопрос о них."
    both = "обеим темам" if len(topics) == 2 else "всем этим темам"
    text = f"Задача может относиться к темам {join_ru(labels, 'или')}. Пока показываем материалы по {both}."
    if gaps:
        text = f"Материалов о {gaps[0]} пока нет. {text}"
    return text


def none_clarification_text(topics: list[str]) -> str:
    labels = [vocab.topic_label(t).lower() for t in topics]
    return (
        f"Каталог покрывает темы: {', '.join(labels)}. "
        "Выберите тему, переформулируйте запрос или начните со стартовой подборки."
    )


COLD_QUESTION = "С чего хотите начать?"
COLD_TEXT = "Выберите тему или опишите задачу. Ниже — вводные бесплатные материалы по каждой теме."
COLD_MESSAGE = "Показываем вводные бесплатные материалы по каждой теме."
EMPTY_MESSAGE = "Подходящих материалов не нашлось. Измените запрос или выберите другую тему."
