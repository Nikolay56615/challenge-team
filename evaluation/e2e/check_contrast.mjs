// Контраст пар ролей из токенов кита (WCAG 2.2: 1.4.3 и 1.4.11; кандидаты W05 и D03; docs/ui-kit.md, 2.1).
// Читает tokens.css и пересчитывает каждую пару «цвет / фон», которую использует kit.css. Список пар — pairs.mjs.
// Текст — не ниже 4,5:1; границы элементов управления, признаки состояния и кольцо фокуса — не ниже 3:1.
// Пары ролей: цвета, которыми различаются состояния, отличаются по светлоте не меньше чем в 3 раза.
// Неактивные элементы и справочные пары различимости ролей выводятся без порога.
// Новый цветовой токен без пары и без пометки «декоративный» — тоже ошибка: таблица не отстаёт от кита.
//
// Запуск из корня проекта, сервис не нужен:
//   npm --prefix evaluation/e2e run check:contrast -- [папка результатов]

import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { contrast, fmt, readTokens } from './color.mjs';
import { DECORATIVE, LITERALS, PAIRS } from './pairs.mjs';

const outDir = process.argv[2] || join(import.meta.dirname, '.results');

let source;
try {
  source = readTokens();
} catch (error) {
  console.error(error.message);
  process.exit(1);
}
const { tokens, unparsed } = source;
const color = (name) => tokens[name] ?? LITERALS[name];
const KIND = { text: 'текст', ui: 'граница', role: 'роль', ref: 'справка' };

const rows = [];
let failed = 0;
for (const { kind, fg, bg, min, where } of PAIRS) {
  const a = color(fg);
  const b = color(bg);
  if (!a || !b) {
    failed++;
    rows.push({ fg, bg, min, kind, where, error: 'нет токена' });
    console.log(`FAIL ${fg} / ${bg}: нет токена в tokens.css`);
    continue;
  }
  const ratio = contrast(a, b);
  const ok = min === null || ratio >= min;
  if (!ok) failed++;
  rows.push({ fg, bg, fgValue: a, bgValue: b, ratio: Number(ratio.toFixed(2)), min, kind, where, ok });
  const limit = min === null ? 'без порога' : `порог ${fmt(min)}`;
  console.log(`${min === null ? 'INFO' : ok ? 'PASS' : 'FAIL'} ${KIND[kind]} ${fg} / ${bg}: ${fmt(ratio)}, ${limit} — ${where}`);
}

// Каждый цветовой токен либо в паре, либо помечен декоративным
const used = new Set(PAIRS.flatMap(({ fg, bg }) => [fg, bg]));
const uncovered = Object.keys(tokens).filter((name) => !used.has(name) && !DECORATIVE.has(name));
if (uncovered.length) {
  failed++;
  console.log(`FAIL токены без пары и без пометки «декоративный»: ${uncovered.join(', ')}`);
}
// Пометка «декоративный» у несуществующего токена — признак устаревшего списка
const stale = [...DECORATIVE].filter((name) => !(name in tokens));
if (stale.length) {
  failed++;
  console.log(`FAIL в списке декоративных токенов нет в tokens.css: ${stale.join(', ')}`);
}
if (unparsed.length) {
  failed++;
  console.log(`FAIL цветовые токены не в виде #rgb или #rrggbb, контраст не посчитать: ${unparsed.join('; ')}`);
}

mkdirSync(outDir, { recursive: true });
writeFileSync(join(outDir, 'contrast-results.json'), JSON.stringify({ tokens: source.path, rows, uncovered, stale, unparsed }, null, 2), 'utf8');
const enforced = rows.filter((row) => row.min !== null && row.min !== undefined);
const count = (kind) => enforced.filter((row) => row.kind === kind).length;
console.log(
  `\nИтого: пар с порогом ${enforced.length} (текст ${count('text')}, границы ${count('ui')}, роли ${count('role')}), ` +
    `ниже порога ${enforced.filter((row) => !row.ok).length}; справочных ${rows.length - enforced.length}; ` +
    `токенов без пары ${uncovered.length}; не в виде hex ${unparsed.length}`,
);
process.exit(failed ? 1 : 0);
