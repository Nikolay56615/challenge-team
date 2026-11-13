// Запуск против локального SQLite-каталога с CATALOG_RELEVANCE=task.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { afterPost, base, runBrowserChecks, submit } from './browser.mjs';

const rows = [];
const axeSource = readFileSync(new URL(import.meta.resolve('axe-core/axe.min.js')), 'utf8');
const reason = 'Действие и объект задачи указаны в названии';
const methods = [['Персональный подбор', 'personal'], ['Подбор по теме', 'baseline']];
const cards = (scope) => scope.locator('article.card h3');

async function checkOrder(scope, items) {
  const headings = cards(scope);
  await headings.nth(items.length - 1).waitFor();
  assert.ok(JSON.stringify(await headings.allTextContents()) === JSON.stringify(items.map((item) => item.title)),
    'Порядок карточек на экране должен совпадать с API');
}

await runBrowserChecks('task-search-results.json', rows, async (browser) => {
  for (const width of [390, 1120]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, locale: 'ru-RU', bypassCSP: true });
    try {
      const page = await context.newPage();
      await page.goto(base + '/');
      await page.getByLabel('Что вы хотите сделать?').fill('Как оформить сотрудника');
      const first = await (await submit(page)).json();
      await checkOrder(page, first.items);
      await page.locator('article.card').first().getByText(reason).waitFor();
      const expanded = await (await afterPost(page, () => page.getByRole('button', { name: 'Показать ещё 5' }).click())).json();
      assert.equal(first.total_candidates, expanded.total_candidates);
      assert.ok(first.items.every((item, index) => item.material_id === expanded.items[index].material_id));
      await checkOrder(page, expanded.items);
      await page.waitForFunction(() => document.activeElement === document.querySelectorAll('article.card')[5]);

      await page.getByRole('checkbox', { name: 'Сравнить с подбором по теме' }).check();
      const comparison = await (await submit(page, '/api/compare')).json();
      for (const [name, key] of methods) {
        if (width < 800) await page.getByRole('tab', { name, exact: true }).click();
        const column = page.locator('.compare__col').filter({ has: page.getByRole('heading', { name, exact: true }) });
        await checkOrder(column, comparison[key].items);
        assert.equal(await column.getByText(reason).first().isVisible(), key === 'personal');
      }
      assert.ok(comparison.personal.items.some((item, index) => item.material_id !== comparison.baseline.items[index]?.material_id));
      if (width < 800) await page.getByRole('tab', { name: methods[0][0], exact: true }).click();
      await page.addScriptTag({ content: axeSource });
      const violations = await page.evaluate(async () => (await window.axe.run(document, {
        runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] },
      })).violations.map((violation) => violation.id));
      assert.deepEqual(violations, []);
      rows.push({ width, ordering: true, reason: true, expansion: true, violations });
      console.log(`PASS Подбор по задаче и сравнение (${width} px)`);
    } finally {
      await context.close();
    }
  }
});
