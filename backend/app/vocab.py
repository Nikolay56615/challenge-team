"""Канонические коды и подписи.

Один источник подписей для API, ранжирования и загрузчиков. Подписи признаков
совпадают с `MaterialSignals.SignalLabel` локальной копии.
"""

from __future__ import annotations

# Темы: код -> подпись (PLAN.md, 2.3)
TOPICS: dict[str, str] = {
    "taxes_law": "Налоги и законы",
    "finance": "Финансы и учёт",
    "team": "Команда",
    "operations": "Организация работы",
    "marketing": "Продвижение",
    "start": "Старт бизнеса",
    "strategy": "Стратегия",
    "sales": "Продажи",
    "tech": "Технологии и ИИ",
    "service": "Клиентский сервис",
    "stories": "Личный опыт",
    "abroad": "Бизнес за рубежом",
    "marketplaces": "Маркетплейсы",
}

# Темы, которые предлагаются чипами, в порядке показа
CHIP_TOPICS: tuple[str, ...] = ("start", "taxes_law", "finance", "marketing", "sales", "operations", "team")

# Стадия: код -> (подпись чипа, подпись во фразе)
STAGES: dict[str, tuple[str, str]] = {
    "idea": ("Только планирую", "только планирую"),
    "start": ("Недавно начал(а)", "недавно начали"),
    "growth": ("Работаю и расту", "работаю и расту"),
}

# Опыт: код -> (подпись чипа, подпись во фразе)
EXPERIENCE: dict[str, tuple[str, str]] = {
    "none": ("Новичок", "новичок"),
    "some": ("Кое-что знаю", "кое-что знаю"),
    "experienced": ("Уверенно разбираюсь", "уверенно разбираюсь"),
}

# Уровень материала
LEVELS: dict[str, str] = {
    "intro": "Для начинающих",
    "practical": "Практика",
    "advanced": "Продвинутый",
}
LEVEL_ORDER: tuple[str, ...] = ("intro", "practical", "advanced")
EXPERIENCE_TO_LEVEL: dict[str, str] = {"none": "intro", "some": "practical", "experienced": "advanced"}

# Формат материала
FORMATS: dict[str, str] = {
    "checklist": "Чек-лист",
    "article": "Статья",
    "template": "Шаблон",
    "document": "Документ",
    "video": "Видео",
    "course": "Курс",
    "webinar": "Вебинар",
    "podcast": "Подкаст",
}

# Предпочтение формата: код -> (подпись чипа, подходящие форматы)
FORMAT_PREFS: dict[str, tuple[str, frozenset[str]]] = {
    "quick": ("Быстрый ответ", frozenset({"article", "checklist", "video"})),
    "template": ("Шаблон", frozenset({"template", "document"})),
    "course": ("Курс или вебинар", frozenset({"course", "webinar", "podcast"})),
}

# Сфера: код -> (подпись списка, подпись во фразе)
INDUSTRIES: dict[str, tuple[str, str]] = {
    "horeca": ("Кафе и рестораны", "кафе и рестораны"),
    "retail": ("Розничная торговля", "розничная торговля"),
    "ecom": ("Интернет-торговля", "интернет-торговля"),
    "services": ("Услуги", "услуги"),
    "construction": ("Строительство и недвижимость", "строительство и недвижимость"),
    "logistics": ("Транспорт и логистика", "транспорт и логистика"),
    "b2b": ("Продажи бизнесу (B2B)", "продажи бизнесу (B2B)"),
    "manufacturing": ("Производство", "производство"),
    "wholesale": ("Оптовая торговля", "оптовая торговля"),
    "b2g": ("Госзаказ (B2G)", "госзаказ (B2G)"),
}

# Признаки из названий и описаний (36 кодов)
SIGNALS: dict[str, str] = {
    "tax_reporting": "Налоги и отчётность",
    "employment": "Трудовые отношения и увольнение",
    "tax_regime": "Выбор налогового режима",
    "marketplace": "Продажи на маркетплейсах",
    "contracts": "Договоры и работа с контрагентами",
    "registration": "Регистрация бизнеса",
    "accounting": "Бухгалтерский учёт",
    "self_employment": "Самозанятость",
    "trademark": "Товарный знак и права на бренд",
    "ai": "Использование ИИ в бизнесе",
    "cash_register": "Онлайн-касса и приём платежей",
    "launch": "Первые шаги при запуске бизнеса",
    "franchise": "Выбор и запуск франшизы",
    "personal_data": "Работа с персональными данными",
    "logistics": "Доставка, склад и логистика",
    "procurement": "Закупки и тендеры",
    "negotiation": "Переговоры и работа с возражениями",
    "audience": "Выбор целевой аудитории",
    "business_plan": "Бизнес-план и бизнес-модель",
    "crm": "Работа с CRM и клиентской базой",
    "fraud": "Безопасность и защита от мошенничества",
    "hiring": "Поиск и наём сотрудников",
    "automation": "Автоматизация процессов",
    "demand": "Оценка спроса и выбор ниши",
    "online_store": "Запуск и развитие интернет-магазина",
    "profitability": "Прибыль и рентабельность",
    "pricing": "Цена товара или услуги",
    "social_media": "Продвижение в социальных сетях",
    "ad_campaign": "Запуск рекламной кампании",
    "cash_flow": "Денежный поток и кассовые разрывы",
    "customer_service": "Клиентский сервис и удержание",
    "foreign_trade": "Продажи и расчёты за рубежом",
    "ad_budget": "Рекламный бюджет и окупаемость",
    "financing": "Финансирование бизнеса",
    "product_positioning": "Позиционирование и ценностное предложение",
    "search_promotion": "Поисковое продвижение",
}

# Тема понятия: её берёт разбор задачи, когда по словарю тем ничего не найдено, а понятие найдено
# (catalog/lexicon.py). Тема выбрана по смыслу понятия. Подбор ищет кандидатов по самому понятию, а тема
# задаёт порядок вариантов, если материалов с понятием нет. Рекламный бюджет отнесён к продвижению:
# понятие дают только рекламные слова — ROMI, CAC, «стоимость привлечения», «окупаемость рекламы».
SIGNAL_HOME_TOPIC: dict[str, str] = {
    "tax_reporting": "taxes_law",
    "employment": "team",
    "tax_regime": "taxes_law",
    "marketplace": "marketplaces",
    "contracts": "taxes_law",
    "registration": "start",
    "accounting": "finance",
    "self_employment": "start",
    "trademark": "taxes_law",
    "ai": "tech",
    "cash_register": "finance",
    "launch": "start",
    "franchise": "start",
    "personal_data": "taxes_law",
    "logistics": "operations",
    "procurement": "sales",
    "negotiation": "sales",
    "audience": "marketing",
    "business_plan": "start",
    "crm": "sales",
    "fraud": "finance",
    "hiring": "team",
    "automation": "operations",
    "demand": "sales",
    "online_store": "sales",
    "profitability": "finance",
    "pricing": "sales",
    "social_media": "marketing",
    "ad_campaign": "marketing",
    "cash_flow": "finance",
    "customer_service": "service",
    "foreign_trade": "abroad",
    "ad_budget": "marketing",
    "financing": "finance",
    "product_positioning": "marketing",
    "search_promotion": "marketing",
}

# Доступ
ACCESS: dict[str, str] = {"open": "Бесплатно", "subscription": "По подписке", "paid": "Платно"}

# События истории и пометки
EVENTS: tuple[str, ...] = ("view", "start", "complete", "purchase")
FLAGS: dict[str, str] = {
    "in_progress": "В процессе",
    "completed": "Пройдено",
    "viewed": "Вы уже открывали",
}

# Следующий шаг по формату, если у материала нет своего (PLAN.md, 3.6)
NEXT_STEP_BY_FORMAT: dict[str, str] = {
    "checklist": "Пройдите пункты и отметьте выполненное",
    "article": "Прочитайте и выберите один приём для проверки",
    "template": "Скопируйте и заполните под свой бизнес",
    "document": "Скопируйте и заполните под свой бизнес",
    "video": "Посмотрите и запишите один вывод",
    "webinar": "Посмотрите и запишите один вывод",
    "podcast": "Послушайте и запишите один вывод",
    "course": "Откройте программу и первый урок",
}

# Признаки ранжирования, которые может отключить отсутствие поля в источнике
FEATURES: tuple[str, ...] = (
    "topic",
    "signal",
    "stage",
    "level",
    "industry",
    "format",
    "effort",
    "continuation",
    "history",
)

ALLOWED_URL_SCHEMES: frozenset[str] = frozenset({"http", "https"})


def topic_label(code: str) -> str:
    return TOPICS.get(code, code)


def format_label(code: str) -> str:
    return FORMATS.get(code, code)


def level_label(code: str | None) -> str | None:
    return LEVELS.get(code) if code else None


def signal_label(code: str) -> str:
    return SIGNALS.get(code, code)
