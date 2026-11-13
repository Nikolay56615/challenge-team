// Форматирование текста карточек и полей (docs/ui-kit.md, раздел 4).

/** Неразрывный пробел: строка не разрывается между словами, которые он связывает */
export const NBSP = '\u00A0';

/**
 * Экранная типографика строк интерфейса и ответа API (кандидат D09; docs/ui-kit.md, раздел 1).
 * Неразрывный пробел ставится после однобуквенного слова, перед тире и между числом и следующим словом;
 * диапазон чисел, записанный без пробелов, получает короткое тире: «10-15 мин» → «10–15 мин». Тире
 * с пробелами между числами — знак предложения: «Шаг 1 — 2 часа на настройку» остаётся фразой, а не
 * диапазоном. Дефис с пробелами между словами становится тире. Даты вида 2026-11-12 и цепочки чисел через
 * дефис не меняются. Повторный вызов результат не меняет.
 */
export function typo(text: string): string {
  return (
    text
      // Диапазон двух чисел без пробелов: «10-15», «10—15» → «10–15»; число перед или после цепочки не трогается
      .replace(/(?<![\d\-–—.,])(\d{1,4})[-–—](\d{1,4})(?![\d\-–—])/g, '$1–$2')
      // Дефис с пробелами между словами — это тире
      .replace(/ - /g, ' — ')
      // Тире не начинает строку: пробел перед ним неразрывный
      .replace(/ +—/g, `${NBSP}—`)
      // Однобуквенное слово не остаётся в конце строки: «в», «и», «с», «к», «у», «о», «а», «я»
      .replace(/(?<=^|[\s«„(—])([а-яё]) +(?=\S)/giu, `$1${NBSP}`)
      // Число и следующее слово или знак: «15 мин», «8 материалов», «5 %»
      .replace(/(\d) +(?=[\p{L}%№])/gu, `$1${NBSP}`)
      .replace(/№ +(?=\d)/g, `№${NBSP}`)
  );
}

/** Длительность: до 120 минут — «N мин», ровные часы — «N ч», иначе «N ч M мин». Число и единица не разрываются. */
export function formatDuration(minutes: number | null | undefined): string | null {
  if (minutes == null || !Number.isFinite(minutes) || minutes <= 0) return null;
  const total = Math.round(minutes);
  if (total < 120) return `${String(total)}\u00A0мин`;
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  return rest === 0 ? `${String(hours)}\u00A0ч` : `${String(hours)}\u00A0ч ${String(rest)}\u00A0мин`;
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

const PLURAL_RU = new Intl.PluralRules('ru');

/** Формы слова при числе. Категории CLDR: one — 1, 21, 101; few — 2–4, 22–24; many — 0, 5–20, 25–30; other — дроби. */
export interface PluralForms {
  one: string;
  few: string;
  many: string;
  /** Форма при дробном числе; по умолчанию — few: «1,5 материала» */
  other?: string;
}

/** Форма слова при числе n по Intl.PluralRules('ru'): plural(5, { one: 'материал', few: 'материала', many: 'материалов' }). */
export function plural(n: number, forms: PluralForms): string {
  switch (PLURAL_RU.select(n)) {
    case 'one':
      return forms.one;
    case 'few':
      return forms.few;
    case 'many':
      return forms.many;
    default:
      return forms.other ?? forms.few;
  }
}

/** «символа» или «символов» после «из N» и «до N»: родительный падеж. */
export function charsGenitive(n: number): string {
  return plural(n, { one: 'символа', few: 'символов', many: 'символов', other: 'символа' });
}

/** Счётчик поля: «N из 300 символов». */
export function formatCounter(length: number, max: number): string {
  return typo(`${String(length)} из ${String(max)} ${charsGenitive(max)}`);
}

/**
 * Сообщение у предела поля (evaluation/track1-heuristic-review.md, ИИ-5). Атрибут maxlength отбрасывает
 * хвост вставки без предупреждения, поэтому поле называет предел и на сколько вставка длиннее.
 * cut — сколько символов вставки или перетаскивания отброшено; 0 — предел достигнут при наборе.
 */
export function formatLimitNotice(max: number, cut: number): string {
  const limit = `Поле вмещает ${String(max)} ${charsGenitive(max)}.`;
  if (cut > 0) {
    // «на 1 символ», «на 2 символа», «на 20 символов»: винительный падеж после «на»
    const chars = plural(cut, { one: 'символ', few: 'символа', many: 'символов', other: 'символа' });
    return typo(`Вставка длиннее на ${String(cut)} ${chars}, её конец не поместился. ${limit}`);
  }
  return typo(`Это предел. ${limit}`);
}
