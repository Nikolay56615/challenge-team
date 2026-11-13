"""Правила микротекстов D19 (обзор research/literature-design.md, находки 2.1, 2.3–2.5, 7.3, 7.4).

Правила проверяются кодом на синтетическом каталоге, шаблонах следующего шага, подписях словаря и на всех
фразах причин, сообщениях и уточнениях, которые дают P01–P12 при `limit` 5 и 10 обоими методами, сетка
из 400 анкет (test_explain_faithfulness.py), выборка пилота из 300 историй (test_history_mode.py) и
задачи на ветки статусов `none`, `weak` и узкого запроса.

1. Стоп-слова (STOP_WORDS): оценка вместо факта, обещание результата, долженствование, преуменьшение
   трудности. Основания указаны в таблице.
2. Без восклицательных знаков: знак добавляет нажим, а не сведения (находки 2.4, 7.3).
3. Следующий шаг описывает одно действие: первым словом глагол в повелительном наклонении из списка
   IMPERATIVES, затем объект, не меньше трёх слов, без точки в конце, до NEXT_STEP_MAX символов. Список
   закрытый: новый глагол шага добавляется в него после проверки человеком, потому что по окончанию «-те»
   глагол не отличить от «вместе» или «работе». Шаблон формата строится как «глагол + объект + время»:
   объект закреплён таблицей TEMPLATE_OBJECTS, время называется, если длительность известна (находки 2.3,
   7.4), в тех же единицах, что бейдж длительности: от 120 минут — часы. У курса длительность относится ко
   всему курсу, время шага неизвестно.
4. Типографика (находка 2.5): кавычки «ёлочки», внутри них „лапки“, прямых кавычек нет; длинное тире
   с пробелами с двух сторон; короткое тире только между числами; без дефиса вместо тире, двойных пробелов,
   пробела перед знаком препинания и трёх точек вместо многоточия.
5. Длина: фраза причины до REASON_PHRASE_MAX символов, причина целиком до 180 (docs/plan.md, 3.6); предложение
   строки состояния и уточнения до SENTENCE_MAX_WORDS слов (простой язык, находка 2.3); краткая польза до
   BENEFIT_MAX символов (находка 2.1); следующий шаг до NEXT_STEP_MAX.

В созданных текстах правила 1, 2 и 4 действуют вне кавычек. В кавычках стоят слова пользователя (цитата
D01, эхо задачи), подписи словаря и названия каталога: подписи и названия проверяются здесь же как данные,
а слова пользователя не правятся. Парность кавычек проверяется по всему тексту. Объект шага в шагах из
данных каталога и «выгода как умение» (находка 7.3) кодом не проверяются: это ручной аудит
evaluation/track1-microcopy-audit.md.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from app import vocab
from app.catalog import lexicon
from app.ranking import explain
from app.ranking.base import Context, HistoryIndex, Profile, Scored
from app.ranking.policy import recommend

from .conftest import catalog_from_payloads, make_profile
from .test_explain_faithfulness import grid_profiles
from .test_history_mode import pilot_grid

# Стоп-слово задаётся основой или точной формой («=просто»), как шаблон словаря запроса (catalog/lexicon.py)
STOP_WORDS: dict[str, tuple[tuple[str, ...], str]] = {
    "оценка вместо факта": (
        ("лучш", "уникальн", "идеальн", "эффективн", "качествен", "=невероятно", "=потрясающе"),
        "«Маркетинговый» язык вызывал отторжение (2.1); информационный стиль заменяет оценку фактом (2.4)",
    ),
    "обещание результата": (
        ("гарант", "=наверняка", "=точно =получите"),
        "Объяснение не завышает ожидание (1.7; кандидат R17)",
    ),
    "долженствование": (
        (
            "=должен", "=должна", "=должно", "=должны", "обязательн", "=обязан", "=обязана", "=обязаны",
            "необходим", "=нужно", "=нужен", "=нужна", "=нужны", "=надо", "=следует", "=требуется",
        ),
        "Контролирующий язык снижает внутреннюю мотивацию (7.3); руководство проекта: без «вы должны»",
    ),
    "преуменьшение трудности": (
        ("=просто", "=легко", "=всего =лишь", "элементарн", "=без =труда", "=без =усилий", "=проще =простого"),
        "Неопределённые усилители убираются (2.4); обещание лёгкости завышает ожидание (1.7)",
    ),
}
_STOP_PATTERNS = [
    (category, word, lexicon._compile((word,))) for category, (words, _) in STOP_WORDS.items() for word in words
]

NEXT_STEP_MAX = 80
BENEFIT_MAX = 90
TITLE_MAX = 120
# Три четверти предела причины: рядом с самой длинной фразой помещается ещё одна короткая (3.6: две–три фразы)
REASON_PHRASE_MAX = 135
SENTENCE_MAX_WORDS = 30
# Объект действия в шаблоне шага по формату
TEMPLATE_OBJECTS = {
    "checklist": "пункты",
    "article": "приём",
    "template": "шаблон",
    "document": "документ",
    "video": "вывод",
    "webinar": "вывод",
    "podcast": "вывод",
    "course": "программу",
}
# Глаголы в повелительном наклонении, с которых начинаются шаги каталога и шаблонов, и частые глаголы шагов
IMPERATIVES = frozenset({
    "Адаптируйте", "Внесите", "Выберите", "Выпишите", "Запишите", "Заполните", "Назначьте", "Напишите",
    "Определите", "Откройте", "Отметьте", "Подставьте", "Позвоните", "Послушайте", "Посмотрите", "Посчитайте",
    "Проверьте", "Пройдите", "Прочитайте", "Разберите", "Скопируйте", "Составьте", "Сохраните", "Сравните",
    "Сформулируйте",
})
_TIME = re.compile(r" \(около \d+ (минуты?|часа|часов)( \d+ минуты?)?\)$")


@dataclass(frozen=True)
class Text:
    kind: str  # title, benefit, step, reason, message, clarification, label
    source: str
    text: str

    @property
    def generated(self) -> bool:
        """Текст собран кодом из шаблона: в кавычках у него данные и слова пользователя."""
        return self.kind in {"reason", "message", "clarification"}


# ---------- проверки ----------


def outside_quotes(text: str) -> str:
    """Текст без содержимого кавычек верхнего уровня: «Тема «Продажи» совпадает…» → «Тема «» совпадает…»."""
    out: list[str] = []
    depth = 0
    for char in text:
        if char == "«":
            if depth == 0:
                out.append(char)
            depth += 1
        elif char == "»" and depth:
            depth -= 1
            if depth == 0:
                out.append(char)
        elif depth == 0:
            out.append(char)
    return "".join(out)


def stop_words(text: str) -> list[str]:
    tokens = tuple(lexicon.tokenize(text))
    return [f"{category}: {word}" for category, word, patterns in _STOP_PATTERNS if lexicon._found(tokens, patterns)]


def quote_violations(text: str) -> list[str]:
    """«Ёлочки» снаружи, „лапки“ внутри, все кавычки закрыты; прямых кавычек нет."""
    if '"' in text or "'" in text:
        return ["прямые кавычки"]
    stack: list[str] = []
    for char in text:
        if char == "«":
            if stack:
                return ["«» внутри кавычек вместо „“"]
            stack.append(char)
        elif char == "„":
            if stack != ["«"]:
                return ["„“ не внутри «»"]
            stack.append(char)
        elif char in "»“":
            if not stack or stack[-1] != {"»": "«", "“": "„"}[char]:
                return [f"{char} без открывающей кавычки"]
            stack.pop()
    return ["незакрытая кавычка"] if stack else []


def typography_violations(text: str) -> list[str]:
    found: list[str] = []
    if re.search(r"\S—|—\S", text):
        found.append("длинное тире без пробела")
    if re.search(r"(?<!\d)–|–(?!\d)", text):
        found.append("короткое тире не между числами")
    if " - " in text or "--" in text:
        found.append("дефис вместо тире")
    if "  " in text:
        found.append("двойной пробел")
    if text != text.strip():
        found.append("пробел в начале или в конце")
    if re.search(r" [,.:;?!»“)]", text) or re.search(r"[«„(] ", text):
        found.append("пробел у знака препинания или кавычки")
    if "..." in text:
        found.append("три точки вместо многоточия")
    return found


def sentences(text: str) -> list[str]:
    """Предложения по точке, вопросу или восклицанию вне кавычек."""
    parts: list[str] = []
    depth = start = 0
    for index, char in enumerate(text):
        depth += {"«": 1, "»": -1}.get(char, 0)
        if depth == 0 and char in ".?!" and (index + 1 == len(text) or text[index + 1] == " "):
            parts.append(text[start : index + 1].strip())
            start = index + 1
    tail = text[start:].strip()
    return [*parts, tail] if tail else parts


def step_violations(step: str) -> list[str]:
    words = step.split()
    found: list[str] = []
    if not words or words[0].rstrip(",:;") not in IMPERATIVES:
        found.append("первое слово не глагол в повелительном наклонении")
    if len(words) < 3:
        found.append("меньше трёх слов: нет объекта")
    if step.endswith("."):
        found.append("точка в конце")
    if len(step) > NEXT_STEP_MAX:
        found.append(f"длиннее {NEXT_STEP_MAX} символов")
    return found


def violations(item: Text) -> list[str]:
    """Нарушения правил 1, 2, 4 и 5 для текста; шаг дополнительно проверяет step_violations."""
    checked = outside_quotes(item.text) if item.generated else item.text
    found = [f"стоп-слово {w}" for w in stop_words(checked)]
    if "!" in checked:
        found.append("восклицательный знак")
    found += quote_violations(item.text)
    found += typography_violations(checked)
    limits = {"benefit": BENEFIT_MAX, "title": TITLE_MAX, "reason": REASON_PHRASE_MAX}
    if item.kind in limits and len(item.text) > limits[item.kind]:
        found.append(f"длиннее {limits[item.kind]} символов")
    if item.kind in {"message", "clarification"}:
        long = [s for s in sentences(item.text) if len(s.split()) > SENTENCE_MAX_WORDS]
        found += [f"предложение длиннее {SENTENCE_MAX_WORDS} слов: {s}" for s in long]
    if item.kind == "step":
        found += step_violations(item.text)
    return found


def report(texts: list[Text]) -> list[str]:
    return [f"{t.kind} {t.source}: {t.text!r}: {v}" for t in texts for v in violations(t)]


# ---------- тексты ----------


EXTRA_TASKS = (
    "Нужна лицензия на продажу алкоголя",
    "Как продавать алкоголь и привлекать клиентов",
    "Какую CRM выбрать и как защитить товарный знак",
    "Регистрация товарного знака",
    "Как оформить наследство на квартиру",
    "Не успеваю с задачами, хочу передать часть работы сотрудникам",
    "Как продвигать бизнес и нанять сотрудников",
    "Хочу открыть магазин, с чего начать",
    "Я новичок, хочу быстро разобраться с налогами",
    "Нужен сертификат на продукцию",
)


def demo_profiles(profiles) -> Iterator[tuple[str, Profile]]:
    for pid, demo in profiles.items():
        for limit in (5, 10):
            yield f"{pid}/{limit}", make_profile(demo, limit=limit)
    for topic in vocab.CHIP_TOPICS:
        yield f"P03+{topic}", make_profile(profiles["P03"], topic=topic, limit=10)
        yield f"P11+{topic}", make_profile(profiles["P11"], topic=topic, limit=10)
    for task in EXTRA_TASKS:
        yield task, Profile(task=task, limit=10)
    for n, profile in enumerate(grid_profiles(profiles)):
        yield f"сетка {n}", profile
    for n, profile in enumerate(pilot_grid()):
        yield f"пилот {n}", profile


def outcome_texts(source: str, outcome) -> Iterator[Text]:
    yield Text("message", source, outcome.message)
    if outcome.clarification:
        yield Text("clarification", source, outcome.clarification["question"])
        yield Text("clarification", source, outcome.clarification["text"])
    for item, reasons in zip(outcome.items, outcome.reasons, strict=True):
        for phrase in reasons:
            yield Text("reason", f"{source} {item.material.id}", phrase)
        yield Text("step", f"{source} {item.material.id}", explain.next_step(item.material))


@pytest.fixture(scope="module")
def runs(catalog, profiles):
    return [
        (source, method, recommend(catalog, profile, method))
        for source, profile in demo_profiles(profiles)
        for method in ("personal", "baseline")
    ]


@pytest.fixture(scope="module")
def generated(runs) -> list[Text]:
    unique: dict[tuple[str, str], Text] = {}
    for source, method, outcome in runs:
        for text in outcome_texts(f"{source} {method}", outcome):
            unique.setdefault((text.kind, text.text), text)
    return list(unique.values())


def catalog_texts(catalog) -> list[Text]:
    texts: list[Text] = []
    for material in catalog.materials.values():
        texts.append(Text("title", material.id, material.title))
        if material.short_benefit:
            texts.append(Text("benefit", material.id, material.short_benefit))
        if material.next_step:
            texts.append(Text("step", material.id, material.next_step))
    return texts


def label_texts() -> list[Text]:
    labels = [
        *vocab.TOPICS.values(), *vocab.SIGNALS.values(), *vocab.LEVELS.values(), *vocab.FORMATS.values(),
        *vocab.ACCESS.values(), *vocab.FLAGS.values(), *explain.STAGE_HINT_LABELS.values(), *lexicon.GAP_PATTERNS,
        *(label for pair in vocab.STAGES.values() for label in pair),
        *(label for pair in vocab.EXPERIENCE.values() for label in pair),
        *(label for pair in vocab.INDUSTRIES.values() for label in pair),
        *(label for label, _ in vocab.FORMAT_PREFS.values()),
        explain.ROUTE_TITLE, explain.POPULARITY_PHRASE,
    ]
    constants = [
        explain.ASSUMPTION, explain.HISTORY_QUESTION, explain.HISTORY_CLARIFICATION_TEXT, explain.COLD_QUESTION,
        explain.COLD_TEXT, explain.COLD_STARTER_TEXT, explain.COLD_MESSAGE, explain.NO_TITLE_MATCH_MESSAGE,
        explain.EMPTY_MESSAGE,
    ]
    return [Text("label", "vocab", label) for label in labels] + [
        Text("message", "explain", text) for text in constants
    ]


# ---------- правила ----------


def test_catalog_texts_follow_the_rules(catalog):
    assert report(catalog_texts(catalog)) == []


def test_labels_and_fixed_texts_follow_the_rules():
    assert report(label_texts()) == []


def test_generated_texts_follow_the_rules(generated):
    assert report(generated) == []


STEP_TIMES = {1: "около 1 минуты", 12: "около 12 минут", 21: "около 21 минуты", 90: "около 90 минут",
              150: "около 2 часов 30 минут"}


@pytest.mark.parametrize("fmt", sorted(vocab.FORMATS))
@pytest.mark.parametrize("minutes", [None, *STEP_TIMES])
def test_format_template_is_verb_object_time(fmt, minutes):
    """Шаблон шага: «глагол + объект», время — если длительность известна и это не курс."""
    material = catalog_from_payloads({"materials": [
        {"id": "X1", "title": "Материал без шага", "format": fmt, "topics": ["sales"], "popularity": 1,
         "duration_minutes": minutes},
    ]}).materials["X1"]
    step = explain.next_step(material)
    base = vocab.NEXT_STEP_BY_FORMAT[fmt]
    assert step.startswith(base) and TEMPLATE_OBJECTS[fmt] in base.split()
    assert step_violations(step) == [] and report([Text("step", fmt, step)]) == []
    timed = minutes is not None and fmt not in explain.UNTIMED_STEP_FORMATS
    assert bool(_TIME.search(step)) == timed, step
    if timed:
        assert step == f"{base} ({STEP_TIMES[minutes]})"


def test_step_time_agrees_with_the_number_and_the_duration_badge():
    """Число и слово согласованы; от 120 минут — часы и минуты, как у бейджа длительности (formatDuration)."""
    assert [explain.step_time(n) for n in (1, 2, 5, 11, 21, 22, 90, 119)] == [
        "около 1 минуты", "около 2 минут", "около 5 минут", "около 11 минут", "около 21 минуты", "около 22 минут",
        "около 90 минут", "около 119 минут",
    ]
    assert [explain.step_time(n) for n in (120, 121, 150, 180, 1260, 1322)] == [
        "около 2 часов", "около 2 часов 1 минуты", "около 2 часов 30 минут", "около 3 часов", "около 21 часа",
        "около 22 часов 2 минут",
    ]


def test_editorial_steps_override_the_template(catalog):
    """Шаг из данных каталога выводится как есть, без времени: длительность показывает бейдж."""
    for material in catalog.materials.values():
        assert material.next_step and explain.next_step(material) == material.next_step


def test_worst_case_phrases_fit_the_length_limit():
    """Самые длинные подстановки: подпись признака, цитата D01, название курса в 120 символов, большие числа."""
    long_title = "Курс «" + "Очень длинное название курса о продажах и продвижении " * 3
    long_title = long_title[:119] + "»"
    catalog = catalog_from_payloads({"materials": [
        {"id": "K1", "title": long_title, "format": "course", "topics": ["sales"], "popularity": 1},
        {"id": "K2", "title": long_title.replace("Курс", "Статья"), "format": "article", "topics": ["sales"],
         "popularity": 1},
    ]})
    label = max(vocab.SIGNALS, key=lambda code: len(vocab.SIGNALS[code]))
    task = "Как позиционироватьсясредидесятковконкурентовнарынкеуслуг в городе"
    profile = Profile(task=task, stage="growth", industry="construction")
    ctx = Context(profile=profile, parsed=lexicon.parse_task(task), topics=("sales",), history=HistoryIndex.build(()),
                  disabled=frozenset(), catalog=catalog.materials)
    phrases = [
        explain.signal_phrase(label, task),
        explain.signal_phrase(label, ""),
        explain.co_enrollment_phrase(99_999, 99_999, "K1", ctx),
        explain._phrase("continuation", Scored(material=catalog.materials["K1"], continuation_of="K2"), ctx),
        explain.title_match_reasons(tuple(lexicon.GAP_PATTERNS), [])[0],
        explain._phrase("industry", Scored(material=catalog.materials["K1"]), ctx),
    ]
    quoted, plain = phrases[0], phrases[1]
    assert quoted is not None and quoted.startswith("В задаче вы назвали «")
    assert plain is not None and plain.startswith("Материал о теме «")
    for phrase in phrases:
        assert phrase
        assert len(phrase) <= REASON_PHRASE_MAX, (len(phrase), phrase)
        assert report([Text("reason", "худший случай", phrase)]) == []


def test_signal_phrases_of_every_feature_follow_the_rules():
    """Фраза о признаке с цитатой и без неё для каждого признака словаря. Фразу без цитаты дают задачи без
    слов признака и правило D01 о вытеснении (explain.personal_reasons)."""
    texts = [
        Text("reason", code, explain.signal_phrase(code, task))
        for code in vocab.SIGNALS
        for task in ("", "Как выбрать CRM и налоговый режим, сдать декларацию и посчитать юнит-экономику")
    ]
    assert report(texts) == []


def test_each_reason_fits_the_total_limit(runs):
    for source, _, outcome in runs:
        for reasons in outcome.reasons:
            assert sum(len(r) for r in reasons) + 2 * (len(reasons) - 1) <= explain.MAX_REASON_CHARS, source


def test_texts_reach_every_branch(runs, generated):
    """Выборка доходит до всех статусов и видов фраз, иначе правила выше их не видят."""
    assert {outcome.status for _, _, outcome in runs} >= {"strong", "weak", "none", "cold"}
    phrases = {t.text for t in generated if t.kind == "reason"}
    # «Материал о теме «…»» синтетика даёт только по правилу D01 о вытеснении: признак всегда находится по
    # словам задачи. «В названии есть упоминание…» синтетика не даёт: слов-пробелов в названиях нет, эту фразу
    # проверяет худший случай выше
    for start in ("В задаче вы назвали «", "Материал о теме «", "Вы выбрали тему «", "Тема «", "Тема из вашей истории",
                  "Этот курс выбрал", "Продолжает материал", "Вы начали", "Подходит для", "На шаг", "Похоже, ",
                  "Стартовый материал", "Совпадает тема"):
        assert any(p.startswith(start) for p in phrases), start
    assert explain.POPULARITY_PHRASE in phrases
    messages = {t.text for t in generated if t.kind == "message"}
    assert any("пока нет" in m for m in messages) and any("знаком" in m for m in messages)


# ---------- проверки не пустые: заведомые нарушения находятся ----------


@pytest.mark.parametrize(
    ("text", "kind", "expected"),
    [
        ("Лучший курс для вас!", "benefit", ["стоп-слово оценка вместо факта: лучш", "восклицательный знак"]),
        ("Вы должны пройти этот курс", "message", ["стоп-слово долженствование: =должны"]),
        ("Это всего лишь пять минут", "benefit", ["стоп-слово преуменьшение трудности: =всего =лишь"]),
        ("Гарантированный результат за неделю", "benefit", ["стоп-слово обещание результата: гарант"]),
        ("Запись откроется на платформе", "step", ["первое слово не глагол в повелительном наклонении"]),
        # Окончание «-те» без глагола: «вместе», «работе»
        ("Вместе с командой разберите воронку", "step", ["первое слово не глагол в повелительном наклонении"]),
        ("Работе с CRM посвящён урок", "step", ["первое слово не глагол в повелительном наклонении"]),
        ("Откройте программу курса.", "step", ["точка в конце"]),
        ("Откройте курс", "step", ["меньше трёх слов: нет объекта"]),
        ("Курс \"Старт\"", "title", ["прямые кавычки"]),
        ("Курс «Учёт «под ключ»»", "title", ["«» внутри кавычек вместо „“"]),
        ("Тема «Продажи» - совпадает", "reason", ["дефис вместо тире"]),
        ("Тема «Продажи»— совпадает", "reason", ["длинное тире без пробела"]),
        ("Около 10–15 минут и ещё  немного", "benefit", ["двойной пробел"]),
        ("Шаги 1 – 3", "benefit", ["короткое тире не между числами"]),
        ("Подождите...", "message", ["три точки вместо многоточия"]),
    ],
)
def test_checks_find_known_violations(text, kind, expected):
    assert violations(Text(kind, "пример", text)) == expected


def test_words_in_quotes_of_generated_texts_are_the_users():
    """Слова пользователя в цитате D01 и в эхе задачи не нарушают правил: «эффективность» — слово P02."""
    phrase = "В задаче вы назвали «эффективность» — материал о теме «Рекламный бюджет и окупаемость»"
    assert violations(Text("reason", "P02", phrase)) == []
    own = violations(Text("benefit", "данные", "Эффективность рекламы"))
    assert own == ["стоп-слово оценка вместо факта: эффективн"]
    echo = explain.none_message("Нужно срочно!!! Помогите, это просто ужас")
    assert violations(Text("message", "эхо", echo)) == []
