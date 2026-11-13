import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { base, runBrowserChecks, submit } from './browser.mjs';

const rows = [];
const axe = readFileSync(new URL(import.meta.resolve('axe-core/axe.min.js')), 'utf8');
await runBrowserChecks('global-search-results.json', rows, async (browser) => {
  for (const width of [390, 1120]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, bypassCSP: true });
    try {
      const page = await context.newPage();
      const health = await (await context.request.get(base + '/api/health')).json();
      assert.ok(['lexical', 'hybrid'].includes(health.catalog.coverage.relevance.effective));
      await page.goto(base);
      const field = page.getByLabel('Что вы хотите сделать?');
      await field.fill('Как составить штатное расписание');
      const result = await (await submit(page)).json();
      assert.equal(result.status, 'strong');
      assert.equal(result.detected_topics.length, 0);
      await page.locator('article.card').first().getByText(/Ключевые слова совпали в названии|Ключевые слова запроса совпали в названии/).waitFor();
      await page.getByRole('checkbox', { name: 'Сравнить с подбором по теме' }).check();
      const compared = await (await submit(page, '/api/compare')).json();
      assert.equal(compared.baseline.status, 'none');
      assert.equal(compared.personal.items[0].material_id, result.items[0].material_id);
      await page.locator('.compare__col:visible').first().waitFor();
      await page.addScriptTag({ content: axe });
      const violations = await page.evaluate(async () => (await window.axe.run(document, {
        runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] },
      })).violations.map((item) => item.id));
      assert.deepEqual(violations, []);
      await page.getByRole('checkbox', { name: 'Сравнить с подбором по теме' }).uncheck();
      await field.fill('Как рассчитать налог с продаж в Техасе');
      const missing = await (await submit(page)).json();
      assert.equal(missing.status, 'none');
      await page.getByText('По этому запросу подходящих материалов не нашлось', { exact: true }).first().waitFor();
      rows.push({ width, mode: health.catalog.coverage.relevance.effective, violations });
      console.log(`PASS Глобальный поиск (${width} px)`);
    } finally {
      await context.close();
    }
  }
});
