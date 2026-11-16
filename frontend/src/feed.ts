// Лента по профилю: расчёты для экрана (docs/plan.md, раздел 13). Оценка карточки равна сумме вкладов
// источников, поэтому полоса, таблица вкладов и сравнение двух карточек считаются вычитанием без остатка.
import type { FeedItem, FeedSourceCode } from './api/types';

// Модуль не импортирует код других модулей: тесты запускают его в Node без сборки, как format.ts и match.ts
const NBSP = '\u00A0';

/**
 * Цветовая группа сегмента полосы. Источников девять, цветов пять и штриховка: четыре оттенка проходят проверку
 * различимости для всех пар при трёх видах дальтонизма, популярность показана нейтральным цветом, доступ и цена —
 * штриховкой. Задача, анкета и начатое идут одной группой «от клиента»; точные подписи остаются в таблице вкладов.
 */
export type FeedFamily = 'history' | 'content' | 'links' | 'own' | 'access' | 'popularity';

export const FAMILY_OF: Record<FeedSourceCode, FeedFamily | null> = {
  history: 'history',
  content: 'content',
  links: 'links',
  progress: 'own',
  task: 'own',
  profile: 'own',
  access: 'access',
  popularity: 'popularity',
  // Отрицательный вклад в полосу не входит: он показан строкой в таблице вкладов
  seen: null,
};

export const FAMILY_ORDER: readonly FeedFamily[] = ['history', 'content', 'links', 'own', 'access', 'popularity'];

export const FAMILY_LABEL: Record<FeedFamily, string> = {
  history: 'Выбор слушателей',
  content: 'Похожее содержание',
  links: 'Совет редакции',
  own: 'От клиента: задача, анкета, начатое',
  access: 'Доступ и\u00A0цена',
  popularity: 'Популярность',
};

const MINUS = '−';

/** 2.27 → «2,27» */
export function formatScore(value: number): string {
  return Math.abs(value).toFixed(2).replace('.', ',').replace(/^/, value < 0 ? MINUS : '');
}

/** 1.5 → «+1,50», −0.1 → «−0,10» */
export function formatDelta(value: number): string {
  return `${value < 0 ? MINUS : '+'}${Math.abs(value).toFixed(2).replace('.', ',')}`;
}

/** 0.31 → «31 %» */
export function formatShare(share: number): string {
  return `${String(Math.round(share * 100))}${NBSP}%`;
}

export interface Segment {
  family: FeedFamily;
  value: number;
}

/** Положительные вклады карточки по цветовым группам в порядке легенды */
export function segments(item: FeedItem): Segment[] {
  const sums = new Map<FeedFamily, number>();
  for (const part of item.parts) {
    const family = FAMILY_OF[part.source];
    if (family && part.value > 0) sums.set(family, (sums.get(family) ?? 0) + part.value);
  }
  return FAMILY_ORDER.filter((family) => sums.has(family)).map((family) => ({ family, value: sums.get(family) ?? 0 }));
}

/** Доли источников ленты по цветовым группам в порядке легенды: для полосы «из чего сложились оценки» */
export function shareSegments(sources: readonly { source: FeedSourceCode; share: number }[]): Segment[] {
  const sums = new Map<FeedFamily, number>();
  for (const entry of sources) {
    const family = FAMILY_OF[entry.source];
    if (family && entry.share > 0) sums.set(family, (sums.get(family) ?? 0) + entry.share);
  }
  return FAMILY_ORDER.filter((family) => sums.has(family)).map((family) => ({ family, value: sums.get(family) ?? 0 }));
}

/** Сколько карточек из первых `depth` одной ленты есть среди первых `depth` другой */
export function sharedCards(a: readonly FeedItem[], b: readonly FeedItem[], depth: number): number {
  const other = new Set(b.slice(0, depth).map((item) => item.material_id));
  return a.slice(0, depth).filter((item) => other.has(item.material_id)).length;
}

/**
 * Причина в виде клиента: сервис пишет свидетельства для того, кто смотрит на клиента со стороны,
 * а сам клиент читает их о себе.
 */
export function clientReason(text: string): string {
  return text.replace('из истории клиента', 'из вашей истории');
}

/** Текст полосы для вспомогательных технологий: «Оценка 2,27: совет редакции 1,50; …» */
export function scoreLabel(item: FeedItem): string {
  const parts = item.parts.map((part) => `${lowerFirst(part.label)} ${formatScore(part.value)}`);
  return `Оценка ${formatScore(item.score)}: ${parts.join('; ')}`;
}

export interface CompareRow {
  source: FeedSourceCode;
  label: string;
  /** Вклад источника у первой карточки сравнения, у второй и разница между ними */
  a: number;
  b: number;
  delta: number;
}

const round2 = (value: number) => Math.round(value * 100) / 100;

/**
 * Две карточки рядом: вклад каждого источника у одной и у другой и разница. Сумма разниц равна разнице оценок,
 * потому что оценка каждой карточки равна сумме её вкладов. Строки идут по убыванию величины разницы.
 */
export function compareRows(a: FeedItem, b: FeedItem): CompareRow[] {
  const rows = new Map<FeedSourceCode, CompareRow>();
  for (const part of a.parts) rows.set(part.source, { source: part.source, label: part.label, a: part.value, b: 0, delta: 0 });
  for (const part of b.parts) {
    const row = rows.get(part.source) ?? { source: part.source, label: part.label, a: 0, b: 0, delta: 0 };
    rows.set(part.source, { ...row, b: part.value });
  }
  return [...rows.values()]
    .map((row) => ({ ...row, delta: round2(row.a - row.b) }))
    .sort((x, y) => Math.abs(y.delta) - Math.abs(x.delta) || x.label.localeCompare(y.label, 'ru'));
}

function lowerFirst(text: string): string {
  return text.charAt(0).toLowerCase() + text.slice(1);
}

export interface FeedChange {
  arrived: number;
  left: number;
  moved: number;
  /** Сдвиг места по коду материала: положительный — карточка поднялась; null — карточки раньше не было */
  shift: Map<string, number | null>;
}

/** Что изменилось в ленте после «что если»: места до и после по кодам материалов */
export function feedChange(before: ReadonlyMap<string, number>, items: readonly FeedItem[]): FeedChange {
  const shift = new Map<string, number | null>();
  let arrived = 0;
  let moved = 0;
  for (const item of items) {
    const was = before.get(item.material_id);
    if (was === undefined) {
      arrived += 1;
      shift.set(item.material_id, null);
    } else if (was !== item.rank) {
      moved += 1;
      shift.set(item.material_id, was - item.rank);
    }
  }
  const now = new Set(items.map((item) => item.material_id));
  const left = [...before.keys()].filter((id) => !now.has(id)).length;
  return { arrived, left, moved, shift };
}

/** «Новых карточек: 2. Ушло: 2. Сменили место: 7.» */
export function changeSentence(change: FeedChange): string {
  if (!change.arrived && !change.left && !change.moved) return 'Лента не изменилась.';
  return `Новых карточек: ${String(change.arrived)}. Ушло: ${String(change.left)}. Сменили место: ${String(change.moved)}.`;
}
