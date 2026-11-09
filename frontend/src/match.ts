// Пометки «Совпало» на карточке.
// Источник — item.contributions: признаки, на которые повлиял пользователь задачей, уточнениями или историей.

/**
 * Короткие подписи признаков без чисел. Несколько признаков истории сводятся к одной подписи:
 * продолжение по редакционной связи и начатый материал — оба «продолжение».
 * Не входят: effort (длительность видна в бейдже), viewed и completed (вклад отрицательный),
 * popularity и прочие признаки, которые пользователь не задавал.
 */
export const MATCH_LABELS: Readonly<Record<string, string>> = {
  topic: 'тема',
  signal: 'суть задачи',
  stage: 'стадия',
  level: 'уровень',
  industry: 'сфера',
  format: 'формат',
  continuation: 'продолжение',
  in_progress: 'продолжение',
  history_topic: 'тема истории',
  co_enrollment: 'похожие курсы',
};

/** Сколько пометок видно на карточке: две–четыре самых сильных */
export const MATCH_MAX = 4;

/** Опыт из формы и уровень материала, которому он соответствует */
export const EXPERIENCE_LEVEL: Readonly<Record<string, string>> = {
  none: 'intro',
  some: 'practical',
  experienced: 'advanced',
};

export interface MatchContext {
  /** Уровень материала, item.level */
  level?: string | null;
  /** Опыт из запроса, по которому получена выдача; null или нет — опыт не указан */
  experience?: string | null;
  /** Сколько пометок показать, по умолчанию MATCH_MAX */
  max?: number;
}

const ORDER = Object.keys(MATCH_LABELS);

/**
 * Совпал ли уровень. Вклад уровня дают точное совпадение, смежный уровень и подсказка из текста задачи
 *. Смежный уровень — материал на шаг глубже или проще: его причина так и говорит,
 * поэтому «уровень» в «Совпало» ей противоречил бы. Без опыта в запросе вклад даёт только точное
 * совпадение с подсказкой, и ему можно верить.
 */
function levelMatches({ level, experience }: MatchContext): boolean {
  if (!experience) return true;
  const target = EXPERIENCE_LEVEL[experience];
  return target === undefined || level === target;
}

/**
 * Подписи признаков с положительным вкладом: по убыванию вклада, при равенстве — в порядке MATCH_LABELS.
 * Повторы подписи убираются, видно не больше max. Уровень помечается только при точном совпадении.
 */
export function matchLabels(
  contributions: Readonly<Record<string, number>> | null | undefined,
  context: MatchContext = {},
): string[] {
  const max = context.max ?? MATCH_MAX;
  const entries = Object.entries(contributions ?? {})
    .filter(([feature, value]) => Object.hasOwn(MATCH_LABELS, feature) && Number.isFinite(value) && value > 0)
    .filter(([feature]) => feature !== 'level' || levelMatches(context))
    .sort(([a, x], [b, y]) => y - x || ORDER.indexOf(a) - ORDER.indexOf(b));
  const labels: string[] = [];
  for (const [feature] of entries) {
    const label = MATCH_LABELS[feature];
    if (label && !labels.includes(label)) labels.push(label);
    if (labels.length >= max) break;
  }
  return labels;
}
