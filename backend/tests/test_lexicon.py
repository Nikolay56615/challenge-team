"""Разбор задачи словарём запроса (catalog/lexicon.py).

Каждая строка таблицы фиксирует полный разбор: темы, признаки и понятия, сферу, слова-пробелы и
подсказки стадии, уровня и формата. Понятия по умолчанию совпадают с признаками; строка называет их
отдельно, когда широкое слово признака понятия не дало. Разбор P01–P10 закреплён точно: по их выдаче
проведена слепая оценка, и он не должен меняться. Запросы F01–F04 и F15 взяты из
инженерной проверки словаря, запросы с широкими словами — из итоговой проверки, остальные — типичные
вопросы малого бизнеса.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app import vocab
from app.catalog import lexicon
from app.catalog.lexicon import parse_task
from app.ranking.base import Profile
from app.ranking.policy import recommend


@dataclass(frozen=True)
class Parse:
    topics: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()
    concepts: tuple[str, ...] = ()
    industry: str | None = None
    stage: str | None = None
    level: str | None = None
    format: str | None = None
    gaps: tuple[str, ...] = ()


def parsed(task: str) -> Parse:
    p = parse_task(task)
    return Parse(p.topics, p.signals, p.concepts, p.industry, p.stage_hint, p.level_hint, p.format_hint, p.gaps)


def row(case_id: str, task: str, topics: str = "", signals: str = "", concepts: str | None = None, **rest):
    """Строка таблицы: темы, признаки и понятия — коды через пробел, слова-пробелы (gaps) — кортеж подписей.
    Без `concepts` понятия совпадают с признаками."""
    named = signals if concepts is None else concepts
    parse = Parse(tuple(topics.split()), tuple(signals.split()), tuple(named.split()), **rest)
    return pytest.param(task, parse, id=case_id)


P01_TASK = "Хочу начать продвигать свою кофейню, с чего начать?"

PROFILES = [
    row("P01", P01_TASK, "marketing", industry="horeca", stage="start"),
    # «Эффективность» поднимает материалы о рекламном бюджете внутри темы, но понятием не становится
    row("P02", "Нужно выстроить системное продвижение и считать его эффективность", "marketing", "ad_budget",
        concepts="", stage="growth"),
    row("P03", ""),
    row("P04", "Как оформить наследство на квартиру"),
    row("P05", "Хочу больше клиентов", "marketing sales"),
    row("P06", P01_TASK, "marketing", industry="horeca", stage="start"),
    row("P07", "Нужна лицензия на продажу алкоголя", "sales", gaps=("лицензировании", "продаже алкоголя")),
    row("P08", P01_TASK, "marketing", industry="horeca", stage="start"),
    row("P09", "Какой налоговый режим выбрать для ИП", "taxes_law", "tax_regime"),
    row("P10", "Как сдать декларацию и не получить штраф", "taxes_law", "tax_reporting"),
    row("P11", ""),
    row("P12", ""),
]

FINDINGS = [
    # F01: основа совпадала с посторонним словом и давала чужую тему
    row("F01-advanced-course", "Нужен продвинутый курс по налогам", "taxes_law", level="advanced", format="course"),
    row("F01-attract-investment", "Как привлечь инвестиции в бизнес", "finance", "financing"),
    row("F01-agree-with-supplier", "Как договориться с поставщиком о скидке", "sales", "negotiation"),
    row("F01-conformity-declaration", "Как получить декларацию соответствия на товар", gaps=("сертификации",)),
    row("F01-trademark", "Регистрация товарного знака", "taxes_law", "trademark"),
    row("F01-promote-verb", "Как продвинуть кофейню", "marketing", industry="horeca"),
    # F02: лишняя тема, признак, сфера или уровень
    row("F02-will-take", "Сколько займет регистрация ИП", "start", "registration"),
    row("F02-will-do", "Займусь продвижением в соцсетях", "marketing", "social_media"),
    row("F02-registration-procedure", "Порядок регистрации ИП", "start", "registration"),
    row("F02-filing-procedure", "Какой порядок сдачи декларации", "taxes_law", "tax_reporting"),
    row("F02-personal-data", "Как работать с персональными данными клиентов", "taxes_law", "personal_data"),
    row("F02-tiles", "Как продвигать услуги по укладке кафеля", "marketing", industry="services"),
    row("F02-for-business", "Как увеличить продажи для бизнеса", "sales"),
    row("F02-not-experienced", "Я не опытный предприниматель, хочу разобраться в налогах", "taxes_law",
        level="intro"),
    row("F02-selling-price", "Как рассчитать отпускную цену товара", "sales", "pricing"),
    row("F02-not-experienced-cafe", "Я не опытный, хочу продвигать кафе", "marketing", industry="horeca",
        level="intro"),
    # F03: частая формулировка не находила тему
    row("F03-opening-ip", "Открытие ИП: какие документы нужны", "start", "registration"),
    row("F03-opening-llc", "Открываю ООО, с чего начать", "start", "registration", stage="start"),
    row("F03-own-coffee-shop", "Хочу открыть свою кофейню", "start", industry="horeca", stage="start"),
    row("F03-bar", "Хочу открыть бар", "start", industry="horeca", stage="start"),
    row("F03-online-store", "Хочу открыть интернет-магазин одежды", "start", "online_store", industry="ecom",
        stage="start"),
    row("F03-expenses", "Как учитывать расходы ИП", "finance", "accounting"),
    row("F03-insurance-contributions", "Как платить страховые взносы ИП", "taxes_law"),
    row("F03-bank-account", "Как открыть расчетный счет", "finance"),
    row("F03-marketplace-brands", "Как продавать на Wildberries и Ozon", "sales marketplaces", "marketplace",
        industry="ecom"),
    # F04: понятие без тематического слова — тема понятия
    row("F04-crm", "Какую CRM выбрать", "sales", "crm"),
    row("F04-niche", "Как выбрать нишу", "sales", "demand"),
    row("F04-demand", "Как оценить спрос на товар", "sales", "demand"),
    row("F04-unit-economics", "Как рассчитать юнит-экономику", "finance", "profitability"),
    row("F04-ausn", "Что такое АУСН", "taxes_law", "tax_regime"),
    row("F04-primary-documents", "Как вести первичку", "finance", "accounting"),
    row("F04-first-employee", "Как нанять первого сотрудника", "team", "hiring"),
    # F15: формы слов-пробелов
    row("F15-certificate", "Нужен сертификат на продукцию", gaps=("сертификации",)),
    row("F15-visas", "Оформление виз сотрудникам", "team", gaps=("визах",)),
    row("F15-visas-trip", "Помогите с оформлением виз для поездки на переговоры", "sales", "negotiation",
        gaps=("визах",)),
    row("F15-visa-trip", "Нужна виза для поездки на переговоры", "sales", "negotiation", gaps=("визах",)),
    row("F15-gift-certificates", "Как продавать подарочные сертификаты", "sales"),
    # Запросы других замечаний проверки: разбор не изменился
    row("other-hire-and-promote", "Как нанять сотрудника и продвигать кафе", "marketing team", "hiring",
        industry="horeca"),
    row("other-retention", "Как удержать клиентов и собрать отзывы", "marketing sales service", "customer_service"),
    row("other-novice", "Я новичок, с чего начать продвижение?", "marketing", stage="start", level="intro"),
    row("other-template", "Нужен шаблон для продвижения", "marketing", format="template"),
    row("other-shop", "Как продвигать магазин", "marketing", industry="retail"),
    row("other-business", "Как продвигать бизнес", "marketing"),
    row("other-hire-and-reviews", "Как нанять сотрудника и работать с отзывами", "team service",
        "hiring customer_service"),
    row("other-marketplaces-export", "Как выйти на маркетплейсы и наладить экспорт", "abroad marketplaces",
        "marketplace foreign_trade", industry="ecom"),
    row("other-quoted-word", "Что такое «наследство»"),
]

EVERYDAY = [
    # Исключения: регистрируют не только бизнес, «доходы минус расходы» — объект налога, «учётная запись» — аккаунт
    row("register-cash-register", "Как зарегистрировать онлайн-кассу", "finance", "cash_register"),
    row("register-own-brand", "Как зарегистрировать свой бренд", "taxes_law", "trademark"),
    row("cash-gap", "Как закрыть кассовый разрыв", "finance", "cash_flow"),
    row("income-minus-expenses", "Что выбрать: УСН доходы или доходы минус расходы", "taxes_law", "tax_regime"),
    row("marketplace-account", "Как создать учетную запись на Ozon", "marketplaces", "marketplace", industry="ecom"),
    row("fire-safety", "Требования пожарной безопасности для кафе", industry="horeca"),
    row("gift-certificate-for-goods", "Подарочный сертификат на товар"),
    # Точные формы вместо основ
    row("ask-not-demand", "Хочу спросить про налоги на патенте", "taxes_law", "tax_regime"),
    row("price-not-warehouse", "Как складывается цена на кофе", "sales", "pricing"),
    row("staff-vacation", "Как оформить отпуск сотруднику", "team", "employment"),
    row("vacation-pay", "Как рассчитать отпускные сотруднику", "team", "employment"),
    row("labor-contract-template", "Нужен шаблон трудового договора", "taxes_law team", "employment contracts",
        format="template"),
    row("loan", "Как взять займ на развитие", "finance", "financing"),
    row("ozonation", "Как продвигать услуги озонирования", "marketing", industry="services"),
    # Новые сочетания
    row("attract-buyers", "Как привлечь покупателей в магазин", "marketing sales", industry="retail"),
    row("small-bakery", "Хочу открыть небольшую пекарню с нуля", "start", industry="horeca", stage="start",
        level="intro"),
    row("account-not-business", "Как открыть счет в банке для ИП", "finance"),
    row("ip-paperwork", "Порядок оформления ИП", "start", "registration"),
    row("register-llc-or-ip", "Стоит ли регистрировать ООО или хватит ИП", "start", "registration"),
    row("grant-for-opening", "Как получить грант на открытие бизнеса", "start", "launch financing"),
    row("order-in-tasks", "Как навести порядок в задачах команды", "operations team"),
    row("taxation-system", "Какую систему налогообложения выбрать для кофейни", "taxes_law", "tax_regime",
        industry="horeca"),
    row("consider-premises", "Что учитывать при выборе помещения под кафе", industry="horeca"),
    row("certify-cosmetics", "Нужно ли сертифицировать косметику", gaps=("сертификации",)),
    row("marketplace-on-ozon", "Как продвигать магазин на Ozon", "marketing marketplaces", "marketplace",
        industry="ecom"),
    # Тема понятия
    row("fraud", "Как защититься от мошенников при оплате картой", "finance", "fraud"),
    # Отрицание действует только на подсказки и только сразу перед словом
    row("not-a-novice", "Я не новичок, нужен курс по рекламе", "marketing", format="course"),
    row("not-advanced", "Мне нужен не продвинутый курс, а основы", level="intro", format="course"),
    row("do-not-know-where-to-start", "Не знаю, с чего начать", stage="start"),
    # Регистр, «ё» и латиница
    row("uppercase", "ОТКРЫТИЕ ИП", "start", "registration"),
    row("yo", "Расчётный счёт для ООО", "finance"),
    row("wb-latin", "Выход на WB с нуля", "marketplaces", "marketplace", industry="ecom", stage="start",
        level="intro"),
]

BROAD_WORDS = [
    # Широкое слово признака без темы: признак остаётся для порядка внутри темы, понятия и темы нет
    row("payback", "Как оценить окупаемость кофейни", signals="ad_budget", concepts="", industry="horeca"),
    row("plan-the-day", "Как эффективно планировать день", signals="ad_budget", concepts=""),
    row("work-efficiently", "Как работать эффективнее", signals="ad_budget", concepts=""),
    row("bankruptcy-notice", "Как подать объявление о банкротстве", signals="ad_campaign", concepts=""),
    row("rent-price", "Цена аренды помещения", signals="pricing", concepts=""),
    row("lower-the-rent", "Как снизить цену аренды", signals="pricing", concepts=""),
    row("first-steps-in-excel", "Первые шаги в Excel", signals="launch", concepts="", stage="start"),
    row("plan-a-vacation", "Как спланировать отпуск", signals="employment", concepts=""),
    row("office-safety", "Безопасность в офисе", signals="fraud", concepts=""),
    row("wiring", "Сломалась проводка в кафе", signals="accounting", concepts="", industry="horeca"),
    row("raise-demand", "Как повысить спрос", signals="demand", concepts=""),
    # Чужая цена и закупочная цена — не цена своего товара
    row("supplier-prices-rose", "У поставщика цены выросли", signals="pricing", concepts=""),
    row("supplies-and-prices", "Поставки и цены", signals="pricing", concepts=""),
    row("supplier-raised-prices", "Поставщик поднял цены на сырьё", signals="pricing", concepts=""),
    row("petrol-price", "Как снизить цену на бензин", signals="pricing", concepts=""),
    row("flat-price", "Определить цену квартиры", signals="pricing", concepts=""),
    row("share-price", "Как поднять цену акций", signals="pricing", concepts=""),
    row("my-car-price", "Какая цена на мой автомобиль", signals="pricing", concepts=""),
    row("business-analytics", "Первые шаги в бизнес-аналитике", signals="launch", concepts="", stage="start"),
    # Рядом с широким словом названо конкретное понятие: тема берётся по нему
    row("franchise-price", "Какая цена франшизы", "start", "franchise pricing", concepts="franchise"),
]

CONCEPTS = [
    # Понятие без темы: тема понятия, кандидаты — материалы с понятием
    row("counterparty", "Как проверить контрагента", "taxes_law", "contracts"),
    row("npd", "Что такое НПД", "start", "self_employment"),
    row("franchise", "Как купить франшизу", "start", "franchise"),
    row("tenders", "Как участвовать в тендерах", "sales", "procurement"),
    row("usp", "Как сформулировать УТП", "marketing", "product_positioning"),
    row("grant", "Как получить грант", "finance", "financing"),
    row("delivery", "Как организовать доставку еды", "operations", "logistics"),
    row("romi", "Как рассчитать ROMI", "marketing", "ad_budget"),
    # Широкое слово в сочетании, которое называет понятие
    row("price-of-goods", "Как поставить цену на товар", "sales", "pricing"),
    row("raise-prices", "Когда поднимать цены", "sales", "pricing"),
    row("menu-prices", "Как поставить цены на меню кофейни", "sales", "pricing", industry="horeca"),
    row("first-steps-for-ip", "Первые шаги для ИП", "start", "launch", stage="start"),
    row("vacation-schedule", "График отпусков на следующий год", "team", "employment"),
    row("vacation-paperwork", "Как оформить отпуск", "team", "employment"),
    row("vacation-pay-alone", "Как рассчитать отпускные", "team", "employment"),
    row("is-there-demand", "Есть ли спрос на домашнюю выпечку", "sales", "demand"),
    row("first-steps-in-business", "Первые шаги в бизнесе", "start", "launch", stage="start"),
    row("avito-ad", "Объявление на Авито для мастера маникюра", "marketing", "ad_campaign"),
    row("payment-safety", "Безопасность платежей в интернете", "finance", "fraud"),
    row("campaign-efficiency", "Как оценить эффективность кампании", "marketing", "ad_budget"),
    row("entries-in-1c", "Как сделать проводку в 1С", "finance", "accounting"),
    # При распознанной теме понятие на выдачу не влияет, но определяется по тем же правилам
    row("ad-payback", "Как считать окупаемость рекламы", "marketing", "ad_budget"),
    row("ad-text", "Как написать рекламное объявление", "marketing", "ad_campaign"),
]

ROWS = PROFILES + FINDINGS + EVERYDAY + BROAD_WORDS + CONCEPTS


@pytest.mark.parametrize(("task", "expected"), ROWS)
def test_parse(task, expected):
    assert parsed(task) == expected


def test_concepts_are_a_subset_of_signals():
    assert set(lexicon.CONCEPT_PATTERNS) == set(lexicon.SIGNAL_PATTERNS)
    for task in (r.values[0] for r in ROWS):
        p = parse_task(task)
        assert set(p.concepts) <= set(p.signals), task


def test_broad_words_and_contexts_must_come_from_the_signal():
    broad = lexicon._Broad
    # Сочетание сужает широкий шаблон, а исключение только убирает совпадения
    patterns = lexicon._concept_patterns("ad_budget", broad(("эффективн",), ("эффективност реклам", "!эффективн труд")))
    assert len(patterns.exclude) == 1
    with pytest.raises(ValueError):
        lexicon._concept_patterns("ad_budget", broad(("бюджет",)))  # у признака нет такого шаблона
    with pytest.raises(ValueError):
        lexicon._concept_patterns("launch", broad(("первые дни",)))
    with pytest.raises(ValueError):
        lexicon._concept_patterns("ad_budget", broad(("эффективн",), ("планирован",)))  # не сужает
    with pytest.raises(ValueError):
        lexicon._concept_patterns("ad_budget", broad(("эффективн",), ("romi отчет",)))  # сужает не широкий
    with pytest.raises(ValueError):
        lexicon._concept_patterns("no_such_signal", broad(("эффективн",)))


def test_pinned_tasks_are_the_profile_tasks(profiles):
    assert {r.id: r.values[0] for r in PROFILES} == {pid: demo.task for pid, demo in profiles.items()}


def test_every_signal_has_a_home_topic():
    assert set(vocab.SIGNAL_HOME_TOPIC) == set(vocab.SIGNALS) == set(lexicon.SIGNAL_PATTERNS)
    assert set(vocab.SIGNAL_HOME_TOPIC.values()) <= set(vocab.TOPICS)


def test_home_topic_only_when_no_topic_is_recognized():
    # Первичка ведёт в финансы, но тема продвижения уже распознана: другие темы не добавляются
    assert parsed("Как вести первичку и продвигать кофейню").topics == ("marketing",)
    # Темы понятий без повторов и в порядке TOPIC_ORDER
    assert parsed("CRM и юнит-экономика").topics == ("finance", "sales")
    assert parsed("Какую CRM выбрать и где искать нишу").topics == ("sales",)


def test_pattern_words_must_match_normalized_tokens():
    for bad in ("ёлка", "Налог", "налог!", "=", "| налог"):
        with pytest.raises(ValueError):
            lexicon._compile((bad,))


@pytest.mark.parametrize(
    ("task", "detected", "top"),
    [
        # Тема выведена из понятия признака: задача её не называет, кандидаты — материалы с признаком
        pytest.param("Какую CRM выбрать", (), ["S02", "S03"], id="crm"),
        pytest.param("Как выбрать нишу", (), ["S01"], id="niche"),
        pytest.param("Как поставить цену на товар", (), ["S01"], id="price-of-goods"),
        pytest.param("График отпусков на следующий год", (), ["O02"], id="vacation-schedule"),
        pytest.param("Хочу открыть свою кофейню", ("start",), ["L01"], id="own-coffee-shop"),
        pytest.param("Как учитывать расходы ИП", ("finance",), ["A03"], id="expenses"),
    ],
)
def test_recognized_task_gets_materials_instead_of_gap(catalog, task, detected, top):
    outcome = recommend(catalog, Profile(task=task))
    assert (outcome.status, outcome.detected_topics) == ("strong", detected)
    assert [item.material.id for item in outcome.items][: len(top)] == top


@pytest.mark.parametrize("task", [r.values[0] for r in BROAD_WORDS if not r.values[1].concepts])
def test_broad_word_alone_selects_no_materials(catalog, task):
    # Без темы и понятия ответ — статус none: выбор темы и стартовая подборка
    outcome = recommend(catalog, Profile(task=task))
    assert (outcome.status, outcome.detected_topics) == ("none", ())
    assert outcome.items and all(item.starter_topic for item in outcome.items)


@pytest.mark.parametrize(
    ("task", "topic"),
    [
        ("Нужен продвинутый курс по налогам", "taxes_law"),
        ("Как привлечь инвестиции в бизнес", "finance"),
        ("Сколько займет регистрация ИП", "start"),
        ("Порядок регистрации ИП", "start"),
    ],
)
def test_no_cards_from_a_spurious_topic(catalog, task, topic):
    outcome = recommend(catalog, Profile(task=task))
    assert outcome.status == "strong"
    assert all(topic in item.material.topics for item in outcome.items)


def test_hyphenated_cafe_compounds_keep_horeca():
    assert parsed("Как продвигать кафе-бар").industry == "horeca"
    assert parsed("кафе-пекарня у дома, как найти клиентов").industry == "horeca"
    assert parsed("Хочу открыть кафе-бар").topics == ("start",)
    assert parsed("Как продвигать услуги по укладке кафеля").industry != "horeca"


def test_stem_may_end_with_a_hyphen_but_an_exact_form_may_not():
    lexicon._compile(("кафе-",))
    with pytest.raises(ValueError):
        lexicon._compile(("=кафе-",))


@pytest.mark.parametrize(
    ("task", "code", "words"),
    [
        # Фраза D01 цитирует слова так, как их написал пользователь: регистр, форма, «ё»
        ("Какую CRM выбрать", "crm", "CRM"),
        ("Какой налоговый режим выбрать для ИП", "tax_regime", "налоговый режим"),
        # Два совпадения признака: «декларацию» и «штраф»; берётся первое слева
        ("Как сдать декларацию и не получить штраф", "tax_reporting", "декларацию"),
        ("Нужно выстроить системное продвижение и считать его эффективность", "ad_budget", "эффективность"),
        ("Как рассчитать Юнит-Экономику?", "profitability", "Юнит-Экономику"),
        ("Как сдать отчёт в налоговую", "tax_reporting", "сдать отчёт"),
        # Знаки между словами совпадения заменяются одним пробелом
        ("Какой налоговый,   режим выбрать", "tax_regime", "налоговый режим"),
        # Исключение отменяет совпадение: «декларация соответствия» не налоговая
        ("Декларация соответствия и налоговая декларация", "tax_reporting", "декларация"),
        ("Нужна декларация соответствия", "tax_reporting", None),
        # Признака нет в задаче или нет такого кода
        ("Как продвигать бизнес", "crm", None),
        ("", "crm", None),
        ("Какую CRM выбрать", "no_such_signal", None),
    ],
)
def test_signal_quote_returns_the_words_as_typed(task, code, words):
    assert lexicon.signal_quote(task, code) == words


@pytest.mark.parametrize("task", [r.values[0] for r in ROWS])
def test_signal_quote_exists_exactly_for_found_signals(task):
    """Цитата есть ровно у найденных признаков, состоит из слов задачи по порядку и снова даёт признак."""
    parsed_task = parse_task(task)
    for code in lexicon.SIGNAL_PATTERNS:
        words = lexicon.signal_quote(task, code)
        assert (words is not None) == (code in parsed_task.signals), (task, code)
        if words is None:
            continue
        position = 0
        for word in words.split():
            position = task.index(word, position) + len(word)
        assert code in parse_task(words).signals, (task, code, words)


@pytest.mark.parametrize(
    ("task", "code", "signal_words", "concept_words"),
    [
        # Широкое слово стоит раньше понятия: цитата понятия называет слова, по которым отобраны материалы
        ("Как эффективно снизить CAC", "ad_budget", "эффективно", "CAC"),
        ("Эффективно ли тратить, какой ROMI нормальный", "ad_budget", "Эффективно", "ROMI"),
        ("Первые шаги: как открыть свой бизнес", "launch", "Первые шаги", "открыть свой бизнес"),
        # Понятие в сочетании: широкое слово с контекстом
        ("Как безопасно принимать онлайн-платежи", "fraud", "безопасно", "безопасно принимать онлайн-платежи"),
        # Без широких слов цитаты совпадают
        ("Какую CRM выбрать", "crm", "CRM", "CRM"),
        # Понятия нет: цитата понятия падает на слова признака
        ("Нужно выстроить системное продвижение и считать его эффективность", "ad_budget", "эффективность",
         "эффективность"),
    ],
)
def test_signal_quote_of_a_concept_names_the_concept(task, code, signal_words, concept_words):
    assert lexicon.signal_quote(task, code) == signal_words
    assert lexicon.signal_quote(task, code, concept=True) == concept_words
    if code in parse_task(task).concepts:
        assert code in parse_task(concept_words).concepts


@pytest.mark.parametrize("task", [r.values[0] for r in ROWS])
def test_concept_quote_exists_exactly_for_found_concepts(task):
    """Цитата понятия — слова задачи по порядку, и по ним одним снова находится понятие."""
    parsed_task = parse_task(task)
    for code in parsed_task.concepts:
        words = lexicon.signal_quote(task, code, concept=True)
        assert words is not None, (task, code)
        position = 0
        for word in words.split():
            position = task.index(word, position) + len(word)
        assert code in parse_task(words).concepts, (task, code, words)


def test_signal_quote_keeps_the_original_letters():
    # Строчные буквы и «ё» не меняют границы слов; заглавная «Ё» сохраняется в цитате
    assert lexicon.signal_quote("СДАТЬ ОТЧЁТ ВОВРЕМЯ", "tax_reporting") == "СДАТЬ ОТЧЁТ"
    # Буква, которая в нижнем регистре даёт два знака, не сдвигает цитату
    assert lexicon.signal_quote("İ CRM", "crm") == "CRM"


def test_topics_from_signals_flag():
    assert parse_task("Какую CRM выбрать").topics_from_signals
    assert not parse_task("Как продвигать кофейню").topics_from_signals
    assert not parse_task("Как вести первичку и продвигать кофейню").topics_from_signals
    assert not parse_task("Как эффективно планировать день").topics_from_signals
    assert not parse_task("").topics_from_signals
