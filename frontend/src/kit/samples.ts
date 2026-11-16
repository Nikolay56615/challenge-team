// Вымышленные данные витрины: материалы из app/backend/data/catalog.synthetic.json,
// подписи из app/backend/app/vocab.py, профили из profiles.synthetic.json.
import type {
  CatalogInfo,
  Clarification,
  CompareResponse,
  Flag,
  Item,
  MetaResponse,
  Profile,
  RecommendResponse,
  Route,
  TopicCode,
} from '../api/types';
import { plural } from '../format';

type Material = Omit<Item, 'rank' | 'reasons' | 'flags' | 'score' | 'contributions'>;

const CATALOG: CatalogInfo = { source: 'synthetic', version: 'synthetic-2026-11-09', size: 23, disabled_features: [] };

const TOPIC_LABELS: Record<string, string> = {
  start: 'Старт бизнеса',
  taxes_law: 'Налоги и законы',
  finance: 'Финансы и учёт',
  marketing: 'Продвижение',
  sales: 'Продажи',
  operations: 'Организация работы',
};

function material(m: Omit<Material, 'topic_labels' | 'access_label' | 'is_paid'>): Material {
  return {
    ...m,
    topic_labels: m.topics.map((topic) => TOPIC_LABELS[topic] ?? topic),
    access_label: m.access === 'open' ? 'Бесплатно' : m.access === 'paid' ? 'Платно' : 'По подписке',
    is_paid: m.access !== 'open',
  };
}

const LEVEL = {
  intro: 'Для начинающих',
  practical: 'Практика',
  advanced: 'Продвинутый',
} as const;

export const M01 = material({
  material_id: 'M01',
  title: 'Чек-лист: первые шаги в продвижении',
  format: 'checklist',
  format_label: 'Чек-лист',
  topics: ['marketing'],
  signals: [
    { code: 'launch', label: 'Первые шаги при запуске бизнеса' },
    { code: 'audience', label: 'Выбор целевой аудитории' },
  ],
  level: 'intro',
  level_label: LEVEL.intro,
  industries: ['horeca', 'retail', 'services'],
  duration_minutes: 15,
  access: 'open',
  short_benefit: null,
  url: 'https://example.org/materials/m01',
  link_allowed: true,
  next_step: 'Отметьте три пункта, которые сделаете на этой неделе',
});

export const M02 = material({
  material_id: 'M02',
  title: 'Курс «Системный маркетинг для растущего бизнеса»',
  format: 'course',
  format_label: 'Курс',
  topics: ['marketing'],
  signals: [
    { code: 'ad_budget', label: 'Рекламный бюджет и окупаемость' },
    { code: 'profitability', label: 'Прибыль и рентабельность' },
  ],
  level: 'advanced',
  level_label: LEVEL.advanced,
  industries: [],
  duration_minutes: 360,
  access: 'paid',
  short_benefit: 'Воронка, план каналов и измеримые цели на квартал. Подробная программа — на странице курса',
  url: 'https://example.org/courses/m02',
  link_allowed: true,
  next_step: 'Откройте страницу курса: программа, сроки и условия',
});

export const M03 = material({
  material_id: 'M03',
  title: 'Шаблон: контент-план на месяц',
  format: 'template',
  format_label: 'Шаблон',
  topics: ['marketing'],
  signals: [{ code: 'social_media', label: 'Продвижение в социальных сетях' }],
  level: 'practical',
  level_label: LEVEL.practical,
  industries: ['ecom', 'retail'],
  duration_minutes: 20,
  access: 'open',
  short_benefit: null,
  url: 'https://example.org/materials/m03',
  link_allowed: true,
  next_step: 'Скопируйте шаблон и заполните первую неделю',
});

export const M04 = material({
  material_id: 'M04',
  title: 'Статья: как выбрать аудиторию и первый рекламный канал',
  format: 'article',
  format_label: 'Статья',
  topics: ['marketing'],
  signals: [
    { code: 'audience', label: 'Выбор целевой аудитории' },
    { code: 'ad_campaign', label: 'Запуск рекламной кампании' },
  ],
  level: 'intro',
  level_label: LEVEL.intro,
  industries: ['retail', 'ecom'],
  duration_minutes: 10,
  access: 'open',
  short_benefit: null,
  url: 'https://example.org/materials/m04',
  link_allowed: true,
  next_step: 'Запишите один сегмент аудитории и один канал для первой рекламы',
});

export const M05 = material({
  material_id: 'M05',
  title: 'Вебинар: таргетированная реклама с бюджетом до 10 тысяч',
  format: 'webinar',
  format_label: 'Вебинар',
  topics: ['marketing'],
  signals: [
    { code: 'ad_campaign', label: 'Запуск рекламной кампании' },
    { code: 'ad_budget', label: 'Рекламный бюджет и окупаемость' },
  ],
  level: 'practical',
  level_label: LEVEL.practical,
  industries: ['ecom'],
  duration_minutes: 90,
  access: 'paid',
  short_benefit: 'Настройка первой кампании и чтение статистики без агентства',
  url: null,
  link_allowed: false,
  next_step: 'Запись откроется на платформе после подключения каталога',
});

export const M06 = material({
  material_id: 'M06',
  title: 'Шаблон: расчёт стоимости привлечения клиента',
  format: 'template',
  format_label: 'Шаблон',
  topics: ['marketing'],
  signals: [
    { code: 'ad_budget', label: 'Рекламный бюджет и окупаемость' },
    { code: 'profitability', label: 'Прибыль и рентабельность' },
  ],
  level: 'advanced',
  level_label: LEVEL.advanced,
  industries: [],
  duration_minutes: 30,
  access: 'open',
  short_benefit: null,
  url: 'https://example.org/materials/m06',
  link_allowed: true,
  next_step: 'Подставьте расходы за месяц и число новых клиентов',
});

export const M07 = material({
  material_id: 'M07',
  title: 'Видео: пять ошибок в продвижении малого бизнеса',
  format: 'video',
  format_label: 'Видео',
  topics: ['marketing'],
  signals: [{ code: 'launch', label: 'Первые шаги при запуске бизнеса' }],
  level: 'intro',
  level_label: LEVEL.intro,
  industries: [],
  duration_minutes: 12,
  access: 'open',
  short_benefit: null,
  url: 'https://example.org/materials/m07',
  link_allowed: true,
  next_step: 'Посмотрите и отметьте, какие ошибки уже есть у вас',
});

export const M08 = material({
  material_id: 'M08',
  title: 'Курс «Старт продвижения за 7 дней»',
  format: 'course',
  format_label: 'Курс',
  topics: ['marketing'],
  signals: [
    { code: 'ad_campaign', label: 'Запуск рекламной кампании' },
    { code: 'social_media', label: 'Продвижение в социальных сетях' },
  ],
  level: 'intro',
  level_label: LEVEL.intro,
  industries: [],
  duration_minutes: 180,
  access: 'paid',
  short_benefit: 'Программа на неделю: аудитория, канал, первое объявление и проверка результата',
  url: 'https://example.org/courses/m08',
  link_allowed: true,
  next_step: 'Откройте страницу курса и посмотрите программу первого дня',
});

export const L01 = material({
  material_id: 'L01',
  title: 'Чек-лист: выбрать форму бизнеса и зарегистрироваться',
  format: 'checklist',
  format_label: 'Чек-лист',
  topics: ['start'],
  signals: [{ code: 'registration', label: 'Регистрация бизнеса' }],
  level: 'intro',
  level_label: LEVEL.intro,
  industries: [],
  duration_minutes: 20,
  access: 'open',
  short_benefit: null,
  url: 'https://example.org/materials/l01',
  link_allowed: true,
  next_step: 'Пройдите пункты и выберите форму регистрации',
});

export const A01 = material({
  material_id: 'A01',
  title: 'Статья: как выбрать налоговый режим',
  format: 'article',
  format_label: 'Статья',
  topics: ['taxes_law'],
  signals: [{ code: 'tax_regime', label: 'Выбор налогового режима' }],
  level: 'intro',
  level_label: LEVEL.intro,
  industries: [],
  duration_minutes: 15,
  access: 'open',
  short_benefit: null,
  url: 'https://example.org/materials/a01',
  link_allowed: true,
  next_step: 'Сравните режимы по таблице в статье и отметьте подходящий',
});

export const S01 = material({
  material_id: 'S01',
  title: 'Чек-лист: первая продажа за неделю',
  format: 'checklist',
  format_label: 'Чек-лист',
  topics: ['sales'],
  signals: [
    { code: 'demand', label: 'Оценка спроса и выбор ниши' },
    { code: 'pricing', label: 'Цена товара или услуги' },
  ],
  level: 'intro',
  level_label: LEVEL.intro,
  industries: [],
  duration_minutes: 15,
  access: 'open',
  short_benefit: null,
  url: 'https://example.org/materials/s01',
  link_allowed: true,
  next_step: 'Выберите один канал и назначьте три разговора с клиентами',
});

export const S02 = material({
  material_id: 'S02',
  title: 'Шаблон: скрипт разговора с клиентом',
  format: 'template',
  format_label: 'Шаблон',
  topics: ['sales'],
  signals: [
    { code: 'negotiation', label: 'Переговоры и работа с возражениями' },
    { code: 'crm', label: 'Работа с CRM и клиентской базой' },
  ],
  level: 'practical',
  level_label: LEVEL.practical,
  industries: ['services', 'b2b'],
  duration_minutes: 20,
  access: 'open',
  short_benefit: null,
  url: 'https://example.org/materials/s02',
  link_allowed: true,
  next_step: 'Адаптируйте скрипт под свой продукт и проверьте его на трёх звонках',
});

export const S03 = material({
  material_id: 'S03',
  title: 'Курс «Отдел продаж с нуля»',
  format: 'course',
  format_label: 'Курс',
  topics: ['sales'],
  signals: [
    { code: 'hiring', label: 'Поиск и наём сотрудников' },
    { code: 'crm', label: 'Работа с CRM и клиентской базой' },
  ],
  level: 'advanced',
  level_label: LEVEL.advanced,
  industries: ['b2b'],
  duration_minutes: 420,
  access: 'paid',
  short_benefit: 'Найм первых менеджеров, скрипты, CRM и план продаж на квартал',
  url: 'https://example.org/courses/s03',
  link_allowed: true,
  next_step: 'Откройте страницу курса и посмотрите программу',
});

export const O01 = material({
  material_id: 'O01',
  title: 'Чек-лист: порядок в задачах за один вечер',
  format: 'checklist',
  format_label: 'Чек-лист',
  topics: ['operations'],
  signals: [{ code: 'automation', label: 'Автоматизация процессов' }],
  level: 'intro',
  level_label: LEVEL.intro,
  industries: [],
  duration_minutes: 20,
  access: 'open',
  short_benefit: null,
  url: 'https://example.org/materials/o01',
  link_allowed: true,
  next_step: 'Пройдите пункты и выберите один инструмент для задач',
});

// Вымышленные материалы только для витрины: в синтетическом каталоге нет подписки,
// а платные материалы со ссылкой там только курсы
export const X01 = material({
  material_id: 'X01',
  title: 'Видеоурок: как читать отчёт о прибылях и убытках',
  format: 'video',
  format_label: 'Видео',
  topics: ['finance'],
  signals: [{ code: 'profitability', label: 'Прибыль и рентабельность' }],
  level: 'practical',
  level_label: LEVEL.practical,
  industries: [],
  duration_minutes: 40,
  access: 'subscription',
  short_benefit: 'Разбор отчёта на примере кофейни: где теряется прибыль и что проверить первым',
  url: 'https://example.org/materials/x01',
  link_allowed: true,
  next_step: 'Откройте страницу материала и проверьте, входит ли он в вашу подписку',
});

export const X02 = material({
  material_id: 'X02',
  title: 'Вебинар: разбор рекламных кабинетов на живых примерах',
  format: 'webinar',
  format_label: 'Вебинар',
  topics: ['marketing'],
  signals: [{ code: 'ad_campaign', label: 'Запуск рекламной кампании' }],
  level: 'practical',
  level_label: LEVEL.practical,
  industries: [],
  duration_minutes: 120,
  access: 'paid',
  short_benefit: 'Настройки кампаний трёх малых бизнесов и ошибки, которые съедают бюджет',
  url: 'https://example.org/materials/x02',
  link_allowed: true,
  next_step: 'Откройте страницу материала: дата, программа и условия участия',
});

export const FLAG_VIEWED: Flag = { code: 'viewed', label: 'Вы уже открывали' };
export const FLAG_IN_PROGRESS: Flag = { code: 'in_progress', label: 'В процессе' };
export const FLAG_COMPLETED: Flag = { code: 'completed', label: 'Пройдено' };

/** Позиция выдачи. contributions — вклады признаков, как в ответе API: из них карточка строит пометки «Совпало» */
export function at(
  m: Material,
  rank: number,
  reasons: string[],
  flags: Flag[] = [],
  contributions: Record<string, number> = {},
): Item {
  return { ...m, rank, reasons, flags, score: 0, contributions };
}

// Вклады признаков витрины: те же сочетания, что у профилей P01, P02 и P11 на синтетическом каталоге
const FIT_P01 = { topic: 3, stage: 2, level: 2, industry: 1, effort: 0.5 };
const FIT_P02 = { topic: 3, signal: 2, stage: 2, level: 2, format: 1.5 };

function option(value: TopicCode) {
  return { value, label: TOPIC_LABELS[value] ?? value };
}

function response(partial: Partial<RecommendResponse> & Pick<RecommendResponse, 'status' | 'message' | 'items'>): RecommendResponse {
  return {
    request_id: `sample-${partial.status}`,
    method: 'personal',
    catalog: CATALOG,
    detected_topics: [],
    clarification: null,
    route: null,
    total_candidates: partial.items.length,
    ...partial,
  };
}

// ---------- карточки витрины ----------
export const CARD_FREE = at(
  M01,
  1,
  ['Тема «Продвижение» совпадает с задачей', 'Подходит для стадии «недавно начали» и сферы «кафе и рестораны»', 'Займёт около 15 минут'],
  [],
  FIT_P01,
);
export const CARD_PAID_COURSE = at(
  M02,
  2,
  [
    'Тема «Продвижение» совпадает с задачей',
    'Подходит для стадии «работаю и расту» и уровня «уверенно разбираюсь»',
    'Формат «Курс» — как вы просили',
  ],
  [],
  FIT_P02,
);
export const CARD_PAID_NO_LINK = at(
  M05,
  3,
  ['Подходит для стадии «работаю и расту»', 'На шаг проще вашего уровня — подойдёт для повторения'],
  [],
  { topic: 3, signal: 2, stage: 2, level: 1, format: 1.5 },
);
export const CARD_VIEWED = at(M07, 4, ['Подходит для стадии «недавно начали»', 'Займёт около 12 минут'], [FLAG_VIEWED], {
  topic: 3,
  stage: 2,
  viewed: -1.5,
});
export const CARD_IN_PROGRESS = at(
  M08,
  5,
  ['Вы начали этот курс — продолжите с текущего урока', 'Подходит для стадии «недавно начали»'],
  [FLAG_IN_PROGRESS],
  { topic: 3, stage: 2, level: 2, in_progress: 2 },
);
export const CARD_COMPLETED = at(M03, 6, ['Тема «Продвижение» совпадает с задачей'], [FLAG_COMPLETED]);
export const CARD_TOPIC = at(
  S02,
  2,
  ['Тема «Продажи» совпадает с задачей', 'Один из самых востребованных материалов по теме'],
  [],
  { topic: 3 },
);
export const CARD_PAID_MATERIAL = at(X02, 2, [
  'Тема «Продвижение» совпадает с задачей',
  'Формат «Вебинар» — как вы просили',
]);
export const CARD_SUBSCRIPTION = at(X01, 3, ['Подходит для стадии «работаю и расту»', 'Займёт около 40 минут']);
export const CARD_COMPACT = at(M06, 3, ['Подходит для стадии «работаю и расту»', 'Займёт около 30 минут'], [], {
  topic: 3,
  signal: 2,
  stage: 2,
});
export const CARD_COMPACT_FLAG = at(M01, 4, ['Совпадает тема «Продвижение»'], [FLAG_VIEWED]);

// ---------- ответы API ----------
export const ROUTE: Route = {
  title: 'Маршрут на первую неделю',
  steps: [
    { material_id: 'M01', title: M01.title },
    { material_id: 'M04', title: M04.title },
    { material_id: 'M03', title: M03.title },
  ],
};

export const STRONG: RecommendResponse = response({
  status: 'strong',
  detected_topics: ['marketing'],
  message:
    'Нашли 8 материалов по теме «Продвижение». Показываем 3 с учётом стадии «недавно начали», уровня «новичок» и сферы «кафе и рестораны».',
  items: [
    CARD_FREE,
    at(M07, 2, ['Подходит для стадии «недавно начали» и уровня «новичок»', 'Займёт около 12 минут']),
    at(M04, 3, ['Подходит для стадии «недавно начали» и уровня «новичок»', 'Займёт около 10 минут']),
  ],
  route: ROUTE,
  total_candidates: 8,
});

export const WEAK_CLARIFICATION: Clarification = {
  question: 'Уточните тему',
  text: 'Задача может относиться к темам «Продвижение» или «Продажи». Пока показываем материалы по обеим темам.',
  field: 'topic',
  options: [option('marketing'), option('sales')],
};

const WEAK_REASONS = (topic: string) => [`Тема «${topic}» подходит к задаче`, 'Один из самых востребованных материалов по теме'];

export const WEAK: RecommendResponse = response({
  status: 'weak',
  detected_topics: ['marketing', 'sales'],
  message:
    'Нашли 12 материалов по темам «Продвижение» и «Продажи». Показываем 5 самых востребованных: стадия и опыт не указаны.',
  clarification: WEAK_CLARIFICATION,
  items: [
    at(M03, 1, WEAK_REASONS('Продвижение')),
    at(S02, 2, WEAK_REASONS('Продажи')),
    at(M02, 3, WEAK_REASONS('Продвижение')),
    at(S01, 4, ['Тема «Продажи» подходит к задаче', 'Займёт около 15 минут']),
    at(M01, 5, ['Тема «Продвижение» подходит к задаче', 'Займёт около 15 минут']),
  ],
  total_candidates: 12,
});

const STARTER_REASONS = (topic: string, minutes: number) => [
  `Стартовый материал по теме «${topic}»`,
  `Займёт около ${String(minutes)} ${plural(minutes, { one: 'минуты', few: 'минут', many: 'минут', other: 'минуты' })}`,
];

const TOPIC_OPTIONS = [option('start'), option('taxes_law'), option('finance'), option('marketing'), option('sales'), option('operations')];

const STARTER: Item[] = [
  at(A01, 1, STARTER_REASONS('Налоги и законы', 15)),
  at(L01, 2, STARTER_REASONS('Старт бизнеса', 20)),
  at(S01, 3, STARTER_REASONS('Продажи', 15)),
  at(M01, 4, STARTER_REASONS('Продвижение', 15)),
  at(O01, 5, STARTER_REASONS('Организация работы', 20)),
];

export const COLD: RecommendResponse = response({
  status: 'cold',
  message: 'Показываем вводные бесплатные материалы по каждой теме.',
  clarification: {
    question: 'С чего хотите начать?',
    text: 'Выберите тему или опишите задачу. Ниже — вводные бесплатные материалы по каждой теме.',
    field: 'topic',
    options: TOPIC_OPTIONS,
  },
  items: STARTER,
});

export const NONE: RecommendResponse = response({
  status: 'none',
  message: 'По запросу «Как оформить наследство на квартиру» материалов пока нет',
  clarification: {
    question: 'Выберите тему',
    text:
      'Каталог покрывает темы: старт бизнеса, налоги и законы, финансы и учёт, продвижение, продажи, организация работы. ' +
      'Выберите тему, переформулируйте запрос или начните со стартовой подборки.',
    field: 'topic',
    options: TOPIC_OPTIONS,
  },
  items: STARTER,
});

const BASELINE_REASON = ['Совпадает тема «Продвижение»'];

export const COMPARE: CompareResponse = {
  baseline: response({
    status: 'strong',
    method: 'baseline',
    message: 'Нашли 8 материалов по теме «Продвижение». Показываем 5 по популярности: подбор по теме не учитывает профиль и историю.',
    items: [
      at(M03, 1, BASELINE_REASON, [FLAG_COMPLETED]),
      at(M02, 2, BASELINE_REASON),
      at(M01, 3, BASELINE_REASON, [FLAG_VIEWED]),
      at(M07, 4, BASELINE_REASON, [FLAG_VIEWED]),
      at(M05, 5, BASELINE_REASON),
    ],
    total_candidates: 8,
  }),
  personal: response({
    status: 'strong',
    message: 'Нашли 8 материалов по теме «Продвижение». Показываем 5 с учётом стадии «работаю и расту», уровня «уверенно разбираюсь» и формата «курс или вебинар».',
    items: [
      at(M02, 1, [
        'Тема «Продвижение» совпадает с задачей',
        'Подходит для стадии «работаю и расту» и уровня «уверенно разбираюсь»',
        'Формат «Курс» — как вы просили',
      ]),
      at(M05, 2, ['Подходит для стадии «работаю и расту»', 'Формат «Вебинар» — как вы просили']),
      at(M06, 3, ['Подходит для стадии «работаю и расту» и уровня «уверенно разбираюсь»']),
      at(M08, 4, ['Формат «Курс» — как вы просили']),
      at(M07, 5, ['Подходит для стадии «работаю и расту»'], [FLAG_VIEWED]),
    ],
    total_candidates: 8,
  }),
  diff: { changed_positions: 5, compared_positions: 5 },
};

const CRM_REASON = ['Материал о теме «Работа с CRM и клиентской базой»'];

/**
 * Ответ сравнения на задачу «Какую CRM выбрать» без профиля. Подбор по теме не видит понятий признаков
 * и отвечает статусом none со стартовой подборкой, персональный находит материалы о CRM.
 */
export const COMPARE_NO_TOPIC: CompareResponse = {
  baseline: response({
    status: 'none',
    method: 'baseline',
    message: 'Подбор по теме не нашёл тему в запросе «Какую CRM выбрать»',
    clarification: {
      question: 'Выберите тему',
      text:
        'Каталог покрывает темы: продажи, старт бизнеса, налоги и законы, финансы и учёт, продвижение, организация работы. ' +
        'Выберите тему, переформулируйте запрос или начните со стартовой подборки.',
      field: 'topic',
      options: [option('sales'), option('start'), option('taxes_law'), option('finance'), option('marketing'), option('operations')],
    },
    items: STARTER,
  }),
  personal: response({
    status: 'strong',
    message: 'Нашли 2 материала на тему «Работа с CRM и клиентской базой». Стадия и опыт не указаны.',
    items: [at(S02, 1, CRM_REASON), at(S03, 2, CRM_REASON)],
  }),
  // Сервер считает позиции и здесь, но экран не сравнивает стартовую подборку с выдачей по запросу
  diff: { changed_positions: 2, compared_positions: 2 },
};

/**
 * Сравнение при пустой задаче и истории профиля, как у P11: подбор по теме отвечает cold со стартовой
 * подборкой, персональный подбирает по истории со статусом weak.
 * Фразы причин и сообщение — вымышленные примеры в форме ответа API.
 */
export const COMPARE_HISTORY: CompareResponse = {
  baseline: response({ status: 'cold', method: 'baseline', message: COLD.message, clarification: COLD.clarification, items: STARTER }),
  personal: response({
    status: 'weak',
    detected_topics: ['marketing'],
    message:
      'Нашли 8 материалов по теме «Продвижение», знакомой по вашей истории, и 1 курс другой темы: его выбирали слушатели вашего курса. Показываем 3 с учётом истории.',
    items: [
      at(M03, 1, ['Продолжает материал «Чек-лист: первые шаги в продвижении» из вашей истории', 'Тема из вашей истории: «Продвижение»'], [], {
        continuation: 1.5,
        history_topic: 1,
      }),
      at(M02, 2, ['Тема из вашей истории: «Продвижение»', 'Этот курс выбрали 12 из 40 слушателей курса «Старт продвижения за 7 дней» из вашей истории'], [], {
        history_topic: 1,
        co_enrollment: 0.9,
      }),
      at(S03, 3, ['Этот курс выбрали 16 из 40 слушателей курса «Старт продвижения за 7 дней» из вашей истории'], [], {
        co_enrollment: 1.2,
      }),
    ],
    total_candidates: 9,
  }),
  diff: { changed_positions: 3, compared_positions: 3 },
};

/** Задача ровно на предел поля, 300 символов: подсказка под полем называет предел */
export const LIMIT_TASK = (
  'Хочу начать продвигать свою кофейню рядом с университетом: выбрать первый канал рекламы, посчитать бюджет ' +
  'на месяц, подготовить меню для студентов и понять, как проверить результат через две недели. Опыта в рекламе нет, ' +
  'помогает один бариста, а на продвижение есть пара вечеров в неделю и небольшой бюджет на первые объявления.'
)
  .padEnd(300, '.')
  .slice(0, 300);

// ---------- справочники и профили ----------
export const META: MetaResponse = {
  topics: [option('start'), option('taxes_law'), option('finance'), option('marketing'), option('sales'), option('operations')],
  stages: [
    { value: 'idea', label: 'Только планирую' },
    { value: 'start', label: 'Недавно начал(а)' },
    { value: 'growth', label: 'Работаю и расту' },
  ],
  experience: [
    { value: 'none', label: 'Новичок' },
    { value: 'some', label: 'Кое-что знаю' },
    { value: 'experienced', label: 'Уверенно разбираюсь' },
  ],
  formats: [
    { value: 'quick', label: 'Быстрый ответ' },
    { value: 'template', label: 'Шаблон' },
    { value: 'course', label: 'Курс или вебинар' },
  ],
  industries: [
    { value: 'horeca', label: 'Кафе и рестораны' },
    { value: 'retail', label: 'Розничная торговля' },
    { value: 'ecom', label: 'Интернет-торговля' },
    { value: 'services', label: 'Услуги' },
    { value: 'construction', label: 'Строительство и недвижимость' },
    { value: 'logistics', label: 'Транспорт и логистика' },
    { value: 'b2b', label: 'Продажи бизнесу (B2B)' },
    { value: 'manufacturing', label: 'Производство' },
    { value: 'wholesale', label: 'Оптовая торговля' },
    { value: 'b2g', label: 'Госзаказ (B2G)' },
  ],
  max_task_length: 300,
  demo_mode: true,
};

export const PROFILES: Profile[] = [
  {
    id: 'P01',
    label: 'P01 · начинающий, первое продвижение',
    description: 'Новичок без истории, кофейня, недавно начал(а)',
    task: 'Хочу начать продвигать свою кофейню, с чего начать?',
    stage: 'start',
    experience: 'none',
    format_pref: null,
    industry: 'horeca',
    history: [],
  },
  {
    id: 'P02',
    label: 'P02 · опытный, нужен курс',
    description: 'Растущий бизнес, нужен курс; открывал чек-лист и видео, прошёл шаблон контент-плана',
    task: 'Нужно выстроить системное продвижение и считать его эффективность',
    stage: 'growth',
    experience: 'experienced',
    format_pref: 'course',
    industry: null,
    history: [
      { material_id: 'M01', event: 'view', seq: 1 },
      { material_id: 'M03', event: 'complete', seq: 2 },
      { material_id: 'M07', event: 'view', seq: 3 },
    ],
  },
];
