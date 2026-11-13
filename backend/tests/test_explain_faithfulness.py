"""Верность объяснения: каждая фраза причины — ненулевой вклад того же знака (docs/plan.md, 3.6; кандидат R21).

tests/test_reasons.py проверяет свойство для P01, P02 и P05–P10 на первой странице. Здесь оно
проверяется шире: все P01–P12 на первой странице и после «Показать ещё», выборка анкет, задач,
тем и историй на синтетическом каталоге, совпадение подписи во фразе с признаком материала и
шаблоны всех признаков: новый признак с фразой без маркера в MARKERS провалит проверку.
Фразы пилота «похожие курсы» — тема истории и совместные записи — сверяются с историей профиля
и с парами каталога (docs/plan.md, раздел 9, решение 2026-11-11); выборка пилота — в test_history_mode.py.
Фраза D01 «В задаче вы назвали «…» — материал о теме «…»» сверяется с текстом задачи: цитата — слова
задачи по порядку, и по ним одним находится тот же признак, а если задача называет понятие, то и понятие.
Цитата не вытесняет других фраз причины. Фраза «Вы выбрали тему «…»» — только для темы из уточнения,
которой нет в задаче.
"""

from __future__ import annotations

import random
from dataclasses import replace

import pytest

from app import vocab
from app.catalog.lexicon import ParsedTask, parse_task, signal_quote, title_matches_gaps
from app.catalog.models import HistoryEvent
from app.ranking import explain, personal
from app.ranking.base import FEATURE_PRIORITY, CoEnrollment, Context, HistoryIndex, Profile, Scored
from app.ranking.explain import HISTORY_TOPIC_PREFIX, POPULARITY_PHRASE, course_name, inner_quotes, short_title
from app.ranking.policy import recommend

from .conftest import catalog_from_payloads, make_profile
from .test_reasons import features_of

PROFILE_IDS = [f"P{n:02d}" for n in range(1, 13)]
TITLE_PREFIX = "В названии есть упоминание о "
TOPIC_CHOSEN = "Вы выбрали тему «"
SIGNAL_QUOTE = "В задаче вы назвали «"
# Маркеры, по которым тесты пилота узнают его фразы: фраза D01 их не содержит
FOREIGN_MARKERS = ("Тема «", "Тема из вашей истории", "Этот курс выбрал")
GRID_SIZE = 400
GRID_SEED = 20261111

EXTRA_TASKS = (
    "Какую CRM выбрать",
    "Я новичок, хочу быстро разобраться с налогами",
    "Нужен курс по продажам для растущего бизнеса",
    "Шаблон контент-плана для интернет-магазина",
    "Хочу открыть магазин, с чего начать",
    "Как нанять первого сотрудника",
    "Нужен сертификат на продукцию",
    "Как считать юнит-экономику и окупаемость рекламы",
)
HISTORIES = (
    (),
    (HistoryEvent("M01", "view", 1), HistoryEvent("M03", "complete", 2), HistoryEvent("M07", "view", 3)),
    (HistoryEvent("M01", "view", 1),),
    (HistoryEvent("M08", "start", 1),),
    (HistoryEvent("A02", "start", 1),),
    (HistoryEvent("M01", "complete", 1), HistoryEvent("M04", "view", 2)),
    (HistoryEvent("L01", "complete", 1), HistoryEvent("S01", "purchase", 2)),
)


def grid_profiles(profiles) -> list[Profile]:
    """Детерминированная выборка из сетки задач, анкет, явной темы и историй."""
    tasks = sorted({demo.task for demo in profiles.values()}) + list(EXTRA_TASKS)
    rng = random.Random(GRID_SEED)
    return [
        Profile(
            task=rng.choice(tasks),
            stage=rng.choice((None, *vocab.STAGES)),
            experience=rng.choice((None, *vocab.EXPERIENCE)),
            format_pref=rng.choice((None, *vocab.FORMAT_PREFS)),
            industry=rng.choice((None, "horeca", "ecom", "b2b")),
            topic=rng.choice((None, None, None, "marketing", "sales", "team")),
            history=rng.choice(HISTORIES),
            limit=rng.choice((5, 10)),
        )
        for _ in range(GRID_SIZE)
    ]


def _quoted(phrase: str, marker: str) -> str | None:
    """Подпись в кавычках после маркера: «Тема «Продвижение» совпадает…» → «Продвижение»."""
    start = phrase.find(marker)
    if start < 0:
        return None
    rest = phrase[start + len(marker):]
    return rest[: rest.find("»")]


def _history_violations(feature: str, phrase: str, item: Scored, profile: Profile, catalog) -> list[str]:
    """Фразы пилота «похожие курсы»: только при пустой задаче, подпись и числа — из истории и пар каталога."""
    material = item.material
    wrong: list[str] = []
    if not parse_task(profile.task).is_empty:
        wrong.append("вклад пилота при задаче с текстом")
    in_history = [e.material_id for e in profile.history if e.material_id in catalog.materials]
    if feature == "history_topic":
        topic = item.history_topic
        history_topics = {t for material_id in in_history for t in catalog.materials[material_id].topics}
        if profile.topic is not None:
            wrong.append("тема истории при явно выбранной теме")
        if topic is None or topic not in material.topics or topic not in history_topics:
            wrong.append("тема истории не у материала или не из истории")
        elif phrase != f"{HISTORY_TOPIC_PREFIX}«{vocab.topic_label(topic)}»":
            wrong.append("подпись темы истории")
    if feature == "co_enrollment":
        pair, pairs = item.co_enrollment, catalog.course_pairs
        if pair is None or pairs is None:
            return [*wrong, "фраза о совместных записях без пары"]
        anchors = [m for m in in_history if catalog.materials[m].format == "course"]
        if material.format != "course" or material.id in in_history or pair.anchor not in anchors:
            wrong.append("пара не курса истории с новым курсом")
        if pairs.neighbours(pair.anchor).get(material.id) != pair.together or pair.together < pairs.min_support:
            wrong.append("число общих слушателей не из пар или ниже порога")
        if pairs.totals.get(pair.anchor) != pair.total or pair.total < personal.CO_ENROLLMENT_MIN_ANCHOR_USERS:
            wrong.append("число слушателей курса истории не из пар или меньше 10")
        shares = [
            pairs.neighbours(a).get(material.id, 0) / pairs.totals[a]
            for a in anchors
            if pairs.totals.get(a, 0) >= personal.CO_ENROLLMENT_MIN_ANCHOR_USERS
        ]
        if pair.together / pair.total != max(shares, default=0.0):
            wrong.append("во фразе не курс истории с наибольшей долей")
        if f" {pair.together} из {pair.total} " not in phrase:
            wrong.append("числа во фразе")
        if f"курса «{course_name(catalog.materials[pair.anchor].title)}» из вашей истории" not in phrase:
            wrong.append("название курса истории")
    return wrong


def _quote_violations(phrase: str, item: Scored, profile: Profile, reasons: list[str]) -> list[str]:
    """Фраза D01: цитата — слова задачи по порядку, и по ним одним находится признак, давший вклад.

    Если задача называет признак как понятие, цитата — слова понятия, и по ним находится понятие. Если слова
    признака в задаче есть, фраза цитирует их; прежняя фраза без цитаты остаётся, только когда цитата не
    помещается в 180 символов вместе с остальными фразами причины (правило D01 о вытеснении).
    """
    code = item.matched_signal or ""
    concept = code in parse_task(profile.task).concepts
    expected = signal_quote(profile.task, code, concept=concept)
    if not phrase.startswith(SIGNAL_QUOTE):
        if expected is None:
            return []
        quoted = explain.signal_phrase(code, profile.task, concept=concept)
        longer = [quoted if p == phrase else p for p in reasons]
        if sum(len(p) for p in longer) + 2 * (len(longer) - 1) <= explain.MAX_REASON_CHARS:
            return ["фраза без цитаты, хотя цитата помещается в причину"]
        return []
    wrong: list[str] = []
    words = _quoted(phrase, SIGNAL_QUOTE) or ""
    if expected is None or words != short_title(expected, explain.TASK_WORDS_CHARS):
        wrong.append("цитата не из совпадения признака")
    position = 0
    for word in words.removesuffix("…").split():
        found = profile.task.find(word, position)
        if found < 0:
            wrong.append(f"слова «{word}» нет в задаче")
            break
        position = found + len(word)
    if not words.endswith("…"):
        own = parse_task(words)
        if code not in own.signals:
            wrong.append("по цитате признак не находится")
        if concept and code not in own.concepts:
            wrong.append("цитата не называет понятие, хотя задача его называет")
    if any(marker in phrase for marker in FOREIGN_MARKERS):
        wrong.append("маркер другой фразы")
    return wrong


def _topic_label_violations(phrase: str, item: Scored, profile: Profile, parsed: ParsedTask) -> list[str]:
    wrong: list[str] = []
    chosen = phrase.startswith(TOPIC_CHOSEN)
    if _quoted(phrase, TOPIC_CHOSEN if chosen else "Тема «") != vocab.topic_label(item.matched_topic or ""):
        wrong.append("тема не та, что совпала")
    if chosen != (profile.topic is not None and item.matched_topic not in parsed.topics):
        wrong.append("«Вы выбрали тему» не для темы из уточнения, которой нет в задаче")
    return wrong


def _stage_label_violations(phrase: str, profile: Profile, parsed: ParsedTask) -> list[str]:
    if profile.stage:
        return ["стадия не из анкеты"] if _quoted(phrase, "стадии «") != vocab.STAGES[profile.stage][1] else []
    return ["подсказка стадии не из текста"] if ("растёт" in phrase) != (parsed.stage_hint == "growth") else []


def _label_violations(
    feature: str, phrase: str, item: Scored, profile: Profile, *, titles: dict[str, str], reasons: list[str]
) -> list[str]:
    """Подпись во фразе совпадает с признаком, за который начислен вклад."""
    parsed = parse_task(profile.task)
    material = item.material
    wrong: list[str] = []
    if feature == "topic":
        wrong.extend(_topic_label_violations(phrase, item, profile, parsed))
    if feature == "signal":
        if _quoted(phrase.replace("Материал о теме «", "материал о теме «"), "материал о теме «") != vocab.signal_label(
            item.matched_signal or ""
        ):
            wrong.append("признак не тот, что совпал")
        wrong.extend(_quote_violations(phrase, item, profile, reasons))
    if feature == "stage":
        wrong.extend(_stage_label_violations(phrase, profile, parsed))
    if feature == "level" and ("глубже" in phrase) != (item.level_direction > 0):
        wrong.append("направление уровня")
    if feature == "industry":
        code = profile.industry or parsed.industry
        if code not in vocab.INDUSTRIES or _quoted(phrase, "сферы «") != vocab.INDUSTRIES[code][1]:
            wrong.append("сфера не из анкеты или текста")
    if feature == "continuation":
        source = item.continuation_of
        if source is None or inner_quotes(short_title(titles[source])) not in phrase:
            wrong.append("продолжение не того материала")
    if feature == "in_progress":
        if item.flags != ["in_progress"] or ("курс" in phrase) != (material.format == "course"):
            wrong.append("пометка «в процессе»")
    return wrong


def faithfulness_violations(outcome, profile: Profile, catalog) -> list[str]:
    """Нарушения свойства 3.6 для персональной выдачи; пустой список — свойство выполнено."""
    parsed = parse_task(profile.task)
    titles = {material_id: material.title for material_id, material in catalog.materials.items()}
    found: list[str] = []
    for item, reasons in zip(outcome.items, outcome.reasons, strict=True):
        material = item.material
        if item.starter_topic:
            expected = [f"Стартовый материал по теме «{vocab.topic_label(item.starter_topic)}»"]
            if reasons != expected or item.starter_topic not in material.topics:
                found.append(f"{material.id}: стартовая причина {reasons}")
            continue
        if not reasons:
            found.append(f"{material.id}: нет причины")
        for phrase in reasons:
            if phrase == POPULARITY_PHRASE:
                if not (item.tie_won and item.popular_in_topic):
                    found.append(f"{material.id}: востребованность без равенства в верхушке темы")
                continue
            if phrase.startswith(TITLE_PREFIX):
                if not (parsed.gaps and title_matches_gaps(material.title, parsed.gaps)):
                    found.append(f"{material.id}: совпадение в названии не подтверждено")
                continue
            named = features_of(phrase)
            if not named:
                found.append(f"{material.id}: фраза без признака: {phrase}")
            for feature in named:
                if item.contributions.get(feature, 0) <= 0:
                    found.append(f"{material.id}: {feature} без положительного вклада: {phrase}")
                found.extend(
                    f"{material.id}: {w}: {phrase}"
                    for w in _label_violations(feature, phrase, item, profile, titles=titles, reasons=reasons)
                )
                if feature in {"history_topic", "co_enrollment"}:
                    found.extend(
                        f"{material.id}: {w}: {phrase}"
                        for w in _history_violations(feature, phrase, item, profile, catalog)
                    )
        found.extend(_pilot_violations(item, profile))
    return found


def _pilot_violations(item: Scored, profile: Profile) -> list[str]:
    """Вклады пилота — только при пустой задаче, даже если фразу вытеснили пределы 3.6."""
    if parse_task(profile.task).is_empty:
        return []
    return [
        f"{item.material.id}: вклад {feature} при задаче с текстом"
        for feature in ("history_topic", "co_enrollment")
        if item.contributions.get(feature, 0) > 0
    ]


@pytest.mark.parametrize("limit", [5, 10])
@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_every_phrase_is_a_positive_contribution_for_test_profiles(catalog, profiles, profile_id, limit):
    profile = make_profile(profiles[profile_id], limit=limit)
    outcome = recommend(catalog, profile, "personal")
    assert faithfulness_violations(outcome, profile, catalog) == []


@pytest.fixture(scope="module")
def grid_runs(catalog, profiles):
    return [(profile, recommend(catalog, profile, "personal")) for profile in grid_profiles(profiles)]


def test_every_phrase_is_a_positive_contribution_on_a_profile_grid(catalog, grid_runs):
    checked = 0
    violations: list[str] = []
    for profile, outcome in grid_runs:
        checked += len(outcome.items)
        violations.extend(f"{profile}: {v}" for v in faithfulness_violations(outcome, profile, catalog))
    assert checked > GRID_SIZE
    assert violations == []


def test_grid_reaches_every_phrase_feature(grid_runs):
    """Выборка должна вызывать фразы всех признаков и все ветви подбора, иначе проверка выше их не видит."""
    named: set[str] = set()
    for _, outcome in grid_runs:
        named.update(feature for reasons in outcome.reasons for phrase in reasons for feature in features_of(phrase))
    assert named >= {
        "topic", "signal", "stage", "level", "industry", "continuation", "in_progress",
        "history_topic", "co_enrollment",
    }
    assert {outcome.status for _, outcome in grid_runs} >= {"strong", "weak", "none", "cold"}
    phrases = [phrase for _, outcome in grid_runs for reasons in outcome.reasons for phrase in reasons]
    assert any(p == POPULARITY_PHRASE for p in phrases)
    # Обе формы фразы о теме и фраза D01 с цитатой: сверка выше их видит
    assert any(p.startswith(TOPIC_CHOSEN) for p in phrases) and any(p.startswith("Тема «") for p in phrases)
    assert any(p.startswith(SIGNAL_QUOTE) for p in phrases)


def test_title_match_phrase_is_true_for_the_title():
    """В синтетическом каталоге нет названий со словами-пробелами, поэтому каталог свой."""
    rows = [
        {"id": "T1", "title": "Как получить лицензию на продажу алкоголя", "format": "article", "topics": ["sales"],
         "stage": ["start"], "popularity": 10},
        {"id": "T2", "title": "Чек-лист: первая продажа", "format": "checklist", "topics": ["sales"], "popularity": 20},
    ]
    catalog = catalog_from_payloads({"materials": rows})
    profile = Profile(task="Нужна лицензия на продажу алкоголя", stage="start")
    outcome = recommend(catalog, profile, "personal")
    assert [item.material.id for item in outcome.items] == ["T1"]
    assert outcome.reasons[0][0].startswith(TITLE_PREFIX) and len(outcome.reasons[0]) == 2
    assert faithfulness_violations(outcome, profile, catalog) == []


def test_negative_contributions_never_become_phrases(catalog, grid_runs):
    """«Просмотрено» и «Пройдено» снижают оценку, но фраз не дают: причина с отрицательным вкладом
    та же, что без него. У этих признаков нет маркеров, поэтому сверка по `features_of` их не видит."""
    seen_negative = 0
    for _, outcome in grid_runs:
        for item, reasons in zip(outcome.items, outcome.reasons, strict=True):
            negative = {f for f, v in item.contributions.items() if v < 0}
            seen_negative += bool(negative)
            named = set().union(*(features_of(r) for r in reasons))
            assert all(item.contributions.get(f, 0) > 0 for f in named), (item.material.id, reasons)
    assert seen_negative, "в выборке нет просмотренных или пройденных материалов"
    material = catalog.materials["M04"]
    profile = Profile(task="Хочу начать продвигать свою кофейню", stage="start")
    ctx = Context(
        profile=profile, parsed=parse_task(profile.task), topics=("marketing",), history=HistoryIndex.build(()),
        disabled=frozenset(), catalog=catalog.materials,
    )
    positive = {"topic": personal.WEIGHTS["topic"], "stage": personal.WEIGHTS["stage_chip"]}
    for feature in ("viewed", "completed"):
        weight = personal.WEIGHTS[feature]
        alone = Scored(material=material, contributions={feature: weight}, flags=[feature])
        assert explain.personal_reasons(alone, ctx) == [], feature
        mixed = Scored(material=material, contributions={**positive, feature: weight}, flags=[feature],
                       matched_topic="marketing")
        clean = Scored(material=material, contributions=dict(positive), matched_topic="marketing")
        assert explain.personal_reasons(mixed, ctx) == explain.personal_reasons(clean, ctx), feature


def test_phrase_templates_name_their_own_feature(catalog):
    """Каждый признак, у которого есть фраза, называет в ней себя и только себя.

    Признак добавляется в FEATURE_PRIORITY вместе с фразой; без маркера в MARKERS тест упадёт.
    Уровень, формат и усилие показывают бейджи: у точного уровня, формата и усилия фразы нет.
    """
    material = catalog.materials["M04"]
    profile = Profile(task="Хочу начать продвигать свою кофейню", stage="start", experience="none", industry="horeca")
    ctx = Context(
        profile=profile, parsed=parse_task(profile.task), topics=("marketing",), history=HistoryIndex.build(()),
        disabled=frozenset(), catalog=catalog.materials,
    )
    phrased = set()
    for feature in FEATURE_PRIORITY:
        item = Scored(
            material=material, contributions={feature: 1.0}, flags=["in_progress"], matched_topic="marketing",
            matched_signal="audience", level_direction=1, continuation_of="M01", history_topic="marketing",
            co_enrollment=CoEnrollment(anchor="M08", together=36, total=120),
        )
        phrase = explain._phrase(feature, item, ctx)
        if phrase is None:
            continue
        phrased.add(feature)
        assert features_of(phrase) == {feature}, (feature, phrase)
        reasons = explain.personal_reasons(item, ctx)
        assert all(features_of(r) <= {feature} for r in reasons), (feature, reasons)
    assert phrased == set(FEATURE_PRIORITY) - {"format", "effort"}
    # Отрицательные веса — только история; у них нет фраз, их показывают бейджи
    negative = {name for name, weight in personal.WEIGHTS.items() if weight < 0}
    assert negative == {"viewed", "completed"} and not negative & set(FEATURE_PRIORITY)


def test_d01_phrase_appears_only_with_a_positive_signal_contribution(catalog, grid_runs):
    """На сетке анкет фраза D01 стоит только у материала с положительным вкладом признака, и её цитата —
    слова задачи; фраза о признаке без цитаты остаётся, только когда слов признака в задаче нет."""
    quoted = 0
    for profile, outcome in grid_runs:
        for item, reasons in zip(outcome.items, outcome.reasons, strict=True):
            for phrase in reasons:
                if not phrase.startswith(SIGNAL_QUOTE):
                    continue
                quoted += 1
                assert item.contributions.get("signal", 0) > 0 and item.matched_signal, (item.material.id, phrase)
                assert _quote_violations(phrase, item, profile, reasons) == [], phrase
    assert quoted


def test_d01_never_costs_a_phrase(catalog, grid_runs, monkeypatch):
    """Фраза D01 длиннее прежней «Материал о теме «…»», но не вытесняет других фраз: на сетке анкет в каждой
    причине столько же фраз, сколько без цитат (ревью потока текстов: терялись уровень, сфера и продолжение)."""
    monkeypatch.setattr(explain, "signal_quote", lambda text, code, **_: None)
    quoted = fallback = 0
    for profile, outcome in grid_runs:
        plain = recommend(catalog, profile, "personal")
        assert [i.material.id for i in plain.items] == [i.material.id for i in outcome.items]
        for item, reasons, short in zip(outcome.items, outcome.reasons, plain.reasons, strict=True):
            assert len(reasons) == len(short), (profile, reasons, short)
            if any(p.startswith(SIGNAL_QUOTE) for p in reasons):
                quoted += 1
                continue
            # Без цитаты причина та же, что при отключённых цитатах
            assert reasons == short, (profile, reasons, short)
            # signal_quote из lexicon не подменён: цитата была возможна, но вытеснила бы фразу
            if item.matched_signal and any(p.startswith("Материал о теме «") for p in reasons):
                fallback += signal_quote(profile.task, item.matched_signal) is not None
    assert quoted and fallback


def test_merged_fit_phrase_names_both_features(catalog):
    """«Подходит для стадии … и сферы …» называет оба признака, и оба с положительным вкладом."""
    profile = Profile(task="Хочу начать продвигать свою кофейню", stage="start", industry="horeca")
    outcome = recommend(catalog, profile, "personal")
    merged = [
        (item, phrase)
        for item, reasons in zip(outcome.items, outcome.reasons, strict=True)
        for phrase in reasons
        if features_of(phrase) == {"stage", "industry"}
    ]
    assert merged
    for item, _ in merged:
        assert item.contributions["stage"] > 0 and item.contributions["industry"] > 0


def test_level_below_profile_is_phrased_as_simpler(catalog):
    profile = Profile(task="Как продвигать бизнес", experience="experienced", limit=10)
    outcome = recommend(catalog, profile, "personal")
    simpler = [
        item
        for item, reasons in zip(outcome.items, outcome.reasons, strict=True)
        if any("На шаг проще" in r for r in reasons)
    ]
    assert simpler and all(item.level_direction < 0 and item.contributions["level"] > 0 for item in simpler)
    assert faithfulness_violations(outcome, profile, catalog) == []


def test_baseline_reason_names_a_topic_of_the_material(run):
    """У подбора по теме вкладов нет: его единственная фраза называет тему, которая есть у материала."""
    for profile_id in PROFILE_IDS:
        outcome = run(profile_id, "baseline")
        for item, reasons in zip(outcome.items, outcome.reasons, strict=True):
            if item.starter_topic:
                continue
            labels = {vocab.topic_label(t) for t in item.material.topics}
            topical = [r for r in reasons if not r.startswith(TITLE_PREFIX)]
            assert topical and all(_quoted(r, "Совпадает тема «") in labels for r in topical), reasons


def test_grid_is_deterministic(profiles):
    assert grid_profiles(profiles) == grid_profiles(profiles)
    assert len({replace(p, history=()) for p in grid_profiles(profiles)}) > GRID_SIZE // 2
