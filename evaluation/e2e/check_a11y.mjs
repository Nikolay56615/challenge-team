// Автоматическая проверка доступности axe-core по состояниям экрана (PLAN.md, 5.5; design/ui-kit.md, раздел 1).
// Ловит только часть нарушений WCAG: ручной проход клавиатурой из check_ui.mjs (E9) она не заменяет.
//
// Запуск из корня проекта при работающем сервисе с собранным интерфейсом:
//   node evaluation/e2e/check_a11y.mjs <папка node_modules с playwright-core и axe-core> [адрес]
// Пример:
//   node evaluation/e2e/check_a11y.mjs <путь-к-node_modules> http://127.0.0.1:8000

import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const [modules, base = 'http://127.0.0.1:8000'] = process.argv.slice(2);
if (!modules) {
  console.error('Укажите папку node_modules с playwright-core и axe-core');
  process.exit(2);
}
const require = createRequire(import.meta.url);
const { chromium } = require(resolve(modules, 'playwright-core'));
const axeSource = readFileSync(join(resolve(modules, 'axe-core'), 'axe.min.js'), 'utf8');
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const rows = [];

async function audit(page, state, width) {
  // CSP приложения запрещает встроенные скрипты; контекст проверки открыт с bypassCSP
  await page.addScriptTag({ content: axeSource });
  const result = await page.evaluate((tags) => window.axe.run(document, { runOnly: { type: 'tag', values: tags } }), TAGS);
  const violations = result.violations.map((v) => `${v.id} (${v.impact}, ${v.nodes.length})`);
  rows.push({ state, width, violations: result.violations.length, passes: result.passes.length });
  console.log(`${violations.length ? 'FAIL' : 'PASS'} ${state} ${width}: нарушений ${violations.length}, правил пройдено ${result.passes.length}${violations.length ? ' — ' + violations.join('; ') : ''}`);
}

async function open(width, path = '/') {
  const context = await browser.newContext({ viewport: { width, height: 900 }, locale: 'ru-RU', bypassCSP: true });
  const page = await context.newPage();
  await page.goto(base + path);
  return { page, context };
}

async function chooseProfile(page, id) {
  const select = page.getByLabel('Тестовый профиль');
  const options = await select.locator('option').evaluateAll((els) => els.map((o) => ({ value: o.value, text: o.textContent })));
  await select.selectOption(options.find((o) => o.value === id || (o.text || '').startsWith(id)).value);
}

async function submit(page) {
  const response = page.waitForResponse((r) => /\/api\/(recommend|compare)$/.test(new URL(r.url()).pathname));
  await page.getByRole('button', { name: 'Подобрать материалы' }).click();
  await response;
  await page.waitForTimeout(250);
}

for (const width of [390, 1120]) {
  const { page, context } = await open(width);
  await page.getByRole('button', { name: 'Подобрать материалы' }).waitFor();
  await audit(page, 'начальный экран', width);

  for (const [id, state] of [['P01', 'P01, выдача и маршрут'], ['P02', 'P02, платные карточки и пометки'], ['P05', 'P05, уточнение темы'], ['P04', 'P04, пробел и стартовая подборка']]) {
    await chooseProfile(page, id);
    await submit(page);
    await audit(page, state, width);
  }

  await chooseProfile(page, 'P02');
  await page.getByRole('checkbox', { name: 'Сравнить с подбором по теме' }).check();
  await submit(page);
  await audit(page, 'сравнение P02', width);
  await page.getByRole('checkbox', { name: 'Сравнить с подбором по теме' }).uncheck();

  await page.getByRole('button', { name: 'Сбросить' }).click();
  await submit(page);
  await audit(page, 'пустая форма, стартовая подборка', width);

  await page.route('**/api/recommend', (route) => route.abort('failed'));
  await page.getByRole('button', { name: 'Подобрать материалы' }).click();
  await page.getByRole('alert').waitFor({ timeout: 5000 });
  await audit(page, 'ошибка запроса', width);
  await page.unroute('**/api/recommend');
  await context.close();

  const kit = await open(width, '/kit.html');
  await kit.page.waitForLoadState('networkidle');
  await audit(kit.page, 'витрина kit.html', width);
  await kit.context.close();
}

await browser.close();
const failed = rows.filter((r) => r.violations > 0).length;
console.log(`\nИтого: состояний ${rows.length}, с нарушениями ${failed}`);
process.exit(failed ? 1 : 0);
