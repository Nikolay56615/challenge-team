// Форматирование текста карточек и полей (design/ui-kit.md, раздел 4).

/** Длительность: до 120 минут — «N мин», ровные часы — «N ч», иначе «N ч M мин». */
export function formatDuration(minutes: number | null | undefined): string | null {
  if (minutes == null || !Number.isFinite(minutes) || minutes <= 0) return null;
  const total = Math.round(minutes);
  if (total < 120) return `${total} мин`;
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  return rest === 0 ? `${hours} ч` : `${hours} ч ${rest} мин`;
}

const SENTENCE_END = /[.!?…]$/;

/** Фраза как предложение: обрезает пробелы и ставит точку, если конечного знака нет. */
export function toSentence(text: string | null | undefined): string {
  const value = (text ?? '').trim();
  if (!value) return '';
  return SENTENCE_END.test(value) ? value : `${value}.`;
}

/** Фразы `reasons` одним абзацем: каждое предложение заканчивается точкой. */
export function joinReasons(reasons: readonly string[]): string {
  return reasons.map(toSentence).filter(Boolean).join(' ');
}

/** «символа» или «символов» после «из N» и «до N». */
export function charsGenitive(n: number): string {
  return n % 10 === 1 && n % 100 !== 11 ? 'символа' : 'символов';
}

/** Счётчик поля: «N из 300 символов». */
export function formatCounter(length: number, max: number): string {
  return `${length} из ${max} ${charsGenitive(max)}`;
}

const number = new Intl.NumberFormat('ru-RU');
const plural = new Intl.PluralRules('ru-RU');

export function formatLessonCount(count: number): string {
  const form = plural.select(count);
  const noun = form === 'one' ? 'урок' : form === 'few' ? 'урока' : 'уроков';
  return `${number.format(count)} ${noun}`;
}

export function formatAvailableMaterials(total: number): string {
  const count = number.format(total);
  switch (plural.select(total)) {
    case 'one': return `${count} доступный материал`;
    case 'few': return `${count} доступных материала`;
    default: return `${count} доступных материалов`;
  }
}

export function formatShownMaterials(shown: number, total: number): string {
  if (shown === 1 && total === 1) return 'Показан 1 материал';
  const noun = plural.select(total) === 'one' ? 'материала' : 'материалов';
  return `Показано ${number.format(shown)} из ${number.format(total)} ${noun}`;
}
