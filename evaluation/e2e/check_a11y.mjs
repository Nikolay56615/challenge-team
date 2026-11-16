// Автоматическая проверка доступности axe-core по состояниям экрана (docs/plan.md, 5.5; docs/ui-kit.md, раздел 1).
// Ловит только часть нарушений WCAG: ручной проход клавиатурой из check_ui.mjs (E9) она не заменяет.
//
// Запуск из корня проекта при работающем сервисе с собранным интерфейсом:
//   npm --prefix evaluation/e2e run check:a11y -- [адрес] [папка результатов]

import { readFileSync } from 'node:fs';
import { base, chooseProfile, runBrowserChecks, submit, TASK_VIEW } from './browser.mjs';

const axeSource = readFileSync(new URL(import.meta.resolve('axe-core/axe.min.js')), 'utf8');
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

const rows = [];

async function audit(page, state, width) {
  // Цвета замеряются после переходов: кнопка отправки возвращается из неактивного вида плавно, и замер
  // посреди перехода давал ложное нарушение контраста с промежуточными цветами
  await page.evaluate(() => Promise.all(document.getAnimations().map((animation) => animation.finished.catch(() => null))));
  // CSP приложения запрещает встроенные скрипты; контекст проверки открыт с bypassCSP
  await page.addScriptTag({ content: axeSource });
  const result = await page.evaluate((tags) => window.axe.run(document, { runOnly: { type: 'tag', values: tags } }), TAGS);
  const violations = result.violations.map((v) => `${v.id} (${v.impact}, ${v.nodes.length})`);
  // incomplete — правила, которые axe не смог решить сам (W19): разбор и решения — evaluation/track1-a11y-manual.md
  const incomplete = result.incomplete.map((v) => {
    const first = v.nodes[0] || {};
    const reason = [...(first.any || []), ...(first.all || []), ...(first.none || [])].map((c) => c.message).find(Boolean) || '';
    return { id: v.id, nodes: v.nodes.length, targets: v.nodes.slice(0, 5).map((n) => n.target.join(' ')), reason };
  });
  rows.push({ state, width, violations, passes: result.passes.length, incomplete });
  console.log(`${violations.length ? 'FAIL' : 'PASS'} ${state} ${width}: нарушений ${violations.length}, правил пройдено ${result.passes.length}${violations.length ? ' — ' + violations.join('; ') : ''}`);
}

async function open(browser, width, path = TASK_VIEW) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, locale: 'ru-RU', bypassCSP: true });
  const page = await context.newPage();
  await page.goto(base + path);
  return { page, context };
}

await runBrowserChecks('a11y-results.json', rows, async (browser) => {
  // 320 px — ширина критерия 1.4.10 WCAG 2.2; проверки, которых нет в axe, — в check_wcag.mjs
  for (const width of [320, 390, 1120]) {
    const { page, context } = await open(browser, width);
    await page.getByLabel('Тестовый профиль').waitFor();
    await audit(page, 'начальный экран', width);

    for (const [id, state] of [
      ['P01', 'P01, выдача и маршрут'],
      ['P02', 'P02, платные карточки и пометки'],
      ['P05', 'P05, уточнение темы'],
      ['P04', 'P04, пробел и стартовая подборка'],
      ['P07', 'P07, узкий запрос без совпадений'],
    ]) {
      await chooseProfile(page, id);
      await submit(page);
      await audit(page, state, width);
    }

    await chooseProfile(page, 'P02');
    await page.getByRole('checkbox', { name: 'Сравнить с подбором по теме' }).check();
    await submit(page, '/api/compare');
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

    const kit = await open(browser, width, '/kit.html');
    await kit.page.getByRole('heading', { name: 'UI-кит трека 1 · витрина' }).waitFor();
    await audit(kit.page, 'витрина kit.html', width);
    await kit.context.close();
  }
});

// Сводка incomplete по правилам: проверку не валит, нужна для ручного разбора
const byRule = new Map();
for (const row of rows) {
  for (const item of row.incomplete || []) {
    const entry = byRule.get(item.id) || { nodes: 0, states: 0, reason: item.reason, targets: new Set() };
    entry.nodes += item.nodes;
    entry.states += 1;
    item.targets.forEach((t) => entry.targets.add(t));
    byRule.set(item.id, entry);
  }
}
for (const [id, entry] of byRule) {
  console.log(`INCOMPLETE ${id}: узлов ${entry.nodes} в ${entry.states} состояниях — ${entry.reason}; примеры: ${[...entry.targets].slice(0, 4).join(' | ')}`);
}

const failed = rows.filter((r) => r.violations.length > 0).length;
console.log(`\nИтого: состояний ${rows.length}, с нарушениями ${failed}, правил с неопределённым итогом ${byRule.size}`);
process.exit(failed ? 1 : 0);
