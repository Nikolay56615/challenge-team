// Правила микротекстов для строк интерфейса. Обычный модуль без
// тестов: его импортирует tests/microcopy.test.mjs, а поток текстов может проверять им тексты API, не запуская
// разбор src. Парсер — rolldown/parseAst, пакет закреплён в devDependencies.
//   1. Стоп-слова: оценка вместо факта, долженствование, канцелярит.
//   2. Типографика: typo(строка) === строка, то есть неразрывные пробелы после однобуквенных слов, перед тире
//      и после числа уже стоят; нет прямых кавычек, трёх точек вместо многоточия, двойных пробелов.
import { parseAst } from 'rolldown/parseAst';
import { typo } from '../src/format.ts';

const CYRILLIC = /[А-Яа-яЁё]/;

const word = (stem) => new RegExp(`(?<!\\p{L})${stem}(?!\\p{L})`, 'iu');
/** Стоп-слова: research/literature-design.md, 2.1, 2.3 и 2.4; guides/russian-style.md */
export const STOP_WORDS = [
  // Оценка вместо факта
  ['оценка', word('лучш\\p{L}*')],
  ['оценка', word('уникальн\\p{L}*')],
  ['оценка', word('идеальн\\p{L}*')],
  ['оценка', word('эффективн\\p{L}*')],
  ['оценка', word('качественн\\p{L}*')],
  ['оценка', word('невероятн\\p{L}*')],
  ['оценка', word('потрясающ\\p{L}*')],
  ['оценка', word('гарантир\\p{L}*')],
  ['оценка', word('выгодн\\p{L}*')],
  ['оценка', word('легко')],
  ['оценка', word('просто')],
  // Долженствование: интерфейс предлагает действие, а не обязывает
  ['долженствование', word('необходимо')],
  ['долженствование', word('нужно')],
  ['долженствование', word('следует')],
  ['долженствование', word('должн\\p{L}*')],
  ['долженствование', word('обязан\\p{L}*')],
  ['долженствование', word('обязательно')],
  ['долженствование', word('требуется')],
  // Канцелярит
  ['канцелярит', word('осуществ\\p{L}*')],
  ['канцелярит', word('явля(?:ется|ются)')],
  ['канцелярит', word('данн(?:ый|ая|ого|ой|ому|ом|ым)')],
  ['канцелярит', word('в\\s+(?:целях|рамках|случае)')],
  ['канцелярит', word('в\\s+настоящее\\s+время')],
  ['канцелярит', word('на\\s+сегодняшний\\s+день')],
  ['канцелярит', word('имеет\\s+место')],
  ['канцелярит', word('производится')],
];

const ENTITIES = { nbsp: '\u00A0', laquo: '«', raquo: '»', mdash: '—', ndash: '–', hellip: '…', quot: '"', amp: '&', lt: '<', gt: '>', apos: "'" };

/** Сущности HTML в тексте и атрибутах JSX: парсер оставляет их как есть, React — раскрывает */
function decodeEntities(text) {
  return text.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (match, name) => {
    if (name[0] === '#') return String.fromCodePoint(name[1] === 'x' || name[1] === 'X' ? parseInt(name.slice(2), 16) : Number(name.slice(1)));
    return ENTITIES[name.toLowerCase()] ?? match;
  });
}

/** Текст JSX так, как его выведет React: переводы строк с отступами схлопываются в один пробел */
function jsxText(raw) {
  return decodeEntities(raw.replace(/[ \t]*\r?\n[ \t]*/g, ' '));
}

/** Строки с кириллицей из исходника: { text, offset, jsx } */
export function extractStrings(code, lang) {
  const ast = parseAst(code, { lang });
  const found = [];
  const visit = (node) => {
    if (Array.isArray(node)) return node.forEach(visit);
    if (!node || typeof node !== 'object') return;
    if (node.type === 'Literal' && typeof node.value === 'string') {
      found.push({ text: node.value, offset: node.start, jsx: false });
    } else if (node.type === 'TemplateElement') {
      found.push({ text: node.value.cooked ?? node.value.raw, offset: node.start, jsx: false });
    } else if (node.type === 'JSXText') {
      found.push({ text: jsxText(node.value), offset: node.start, jsx: true });
    } else if (node.type === 'JSXAttribute' && node.value?.type === 'Literal' && typeof node.value.value === 'string') {
      found.push({ text: decodeEntities(node.value.value), offset: node.value.start, jsx: true });
      return;
    }
    for (const [key, value] of Object.entries(node)) {
      if (key !== 'start' && key !== 'end' && value && typeof value === 'object') visit(value);
    }
  };
  visit(ast);
  return found.filter(({ text }) => CYRILLIC.test(text));
}

/** Нарушения правил в одной строке; jsx — текст JSX, его края рядом с выражениями не проверяются */
export function problems(text, { jsx = false } = {}) {
  const out = [];
  for (const [kind, pattern] of STOP_WORDS) {
    const hit = text.match(pattern);
    if (hit) out.push(`${kind}: «${hit[0]}»`);
  }
  // Текст JSX рядом с выражением начинается или кончается пробелом: края не проверяются
  const body = jsx ? text.trim() : text;
  const fixed = typo(body);
  if (fixed !== body) out.push(`типографика: «${body}» → «${fixed}» (⍽ — неразрывный пробел)`.replaceAll('\u00A0', '⍽'));
  if (/["']/.test(text)) out.push('прямые кавычки вместо «ёлочек»');
  if (text.includes('...')) out.push('три точки вместо «…»');
  if (/\S {2,}\S/.test(text)) out.push('двойной пробел');
  if (/[\p{L}\d»)] [,.:;!?…](?!\S)|[\p{L}\d»)] [,;:!?](?=\S)/u.test(text)) out.push('пробел перед знаком препинания');
  return out;
}
