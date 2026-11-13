// Правила микротекстов для строк интерфейса (кандидат D19, часть фронтенда; docs/ui-kit.md, раздел 1).
// Тест разбирает исходники src и проверяет каждую строку с кириллицей: строковые литералы, части шаблонных строк,
// текст JSX и значения атрибутов JSX. Сами правила — в tests/microcopy-rules.mjs:
//   1. Стоп-слова: оценка вместо факта, долженствование, канцелярит.
//   2. Типографика: typo(строка) === строка, нет прямых кавычек, трёх точек вместо многоточия, двойных пробелов.
//   3. В исходнике нет символа U+00A0: неразрывный пробел записывается как \u00A0 или &nbsp;, иначе его не видно.
// Строки, которые собираются при выполнении из ответа API и чисел, проходят typo() в компонентах; тест их не видит.
// Витрина kit/Gallery.tsx, данные витрины kit/samples.ts и сгенерированный api/schema.gen.ts не проверяются.
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { test } from 'node:test';
import { extractStrings, problems } from './microcopy-rules.mjs';

const SRC = new URL('../src/', import.meta.url);
const SKIP = new Set(['kit/Gallery.tsx', 'kit/samples.ts', 'api/schema.gen.ts']);

function sources() {
  return readdirSync(SRC, { recursive: true })
    .map((path) => String(path).replaceAll('\\', '/'))
    .filter((path) => /\.(ts|tsx)$/.test(path) && !SKIP.has(path))
    .sort();
}

const lineOf = (code, offset) => code.slice(0, offset).split('\n').length;

test('правила срабатывают на заведомо плохих строках и пропускают исправленные', () => {
  const bad = [
    'Необходимо выбрать лучший курс',
    'Данный материал является эффективным',
    'Подходит в рамках обучения',
    'Нажмите кнопку - и подборка готова',
    'Займёт около 15 минут',
    'Материалы в порядке пользы',
    'Скопируйте "шаблон"',
    'Подбираем...',
    'Сравнение  готово',
  ];
  for (const text of bad) assert.ok(problems(text).length > 0, text);
  const good = ['Уточнения', 'необязательно', 'Нужный формат', 'Введённые данные сохранены\u00A0— повторите запрос.', 'Займёт около 15\u00A0минут', 'Показать ещё '];
  for (const text of good) assert.deepEqual(problems(text, { jsx: true }), [], text);
});

test('разбор находит строки JSX, атрибутов, литералов и шаблонов, раскрывает &nbsp;', () => {
  const code = 'const a = <p title="в&nbsp;поле">и&nbsp;мир {"в\\u00A0доме"}\n   вторая строка</p>; const t = `${1}\\u00A0мин`;';
  const texts = extractStrings(code, 'tsx').map(({ text }) => text);
  assert.deepEqual(texts, ['в\u00A0поле', 'и\u00A0мир ', 'в\u00A0доме', ' вторая строка', '\u00A0мин']);
});

test('строки интерфейса в src без стоп-слов и с экранной типографикой', () => {
  const report = [];
  let checked = 0;
  for (const path of sources()) {
    const code = readFileSync(new URL(path, SRC), 'utf8');
    const lang = path.endsWith('.tsx') ? 'tsx' : 'ts';
    for (const { text, offset, jsx } of extractStrings(code, lang)) {
      checked++;
      for (const problem of problems(text, { jsx })) report.push(`${path}:${lineOf(code, offset)}: ${problem}`);
    }
  }
  assert.ok(checked >= 60, `проверено строк: ${checked}; разбор, похоже, ничего не нашёл`);
  assert.deepEqual(report, [], `нарушений ${report.length}:\n${report.join('\n')}`);
});

test('в исходниках src нет неразрывного пробела U+00A0 в явном виде', () => {
  const report = [];
  for (const path of sources().concat(['styles/kit.css', 'styles/app.css', 'styles/tokens.css'])) {
    const code = readFileSync(new URL(path, SRC), 'utf8');
    code.split('\n').forEach((line, index) => {
      if (line.includes('\u00A0')) report.push(`${path}:${index + 1}`);
    });
  }
  assert.deepEqual(report, [], 'замените символ на \\u00A0 или &nbsp;');
});
