import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { chromium } from 'playwright-core';

export const [base = 'http://127.0.0.1:8000', outDir = join(import.meta.dirname, '.results')] = process.argv.slice(2);

export async function runBrowserChecks(reportName, results, run) {
  mkdirSync(outDir, { recursive: true });
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    await run(browser);
  } catch (error) {
    results.push({ error: error.stack || String(error) });
    throw error;
  } finally {
    writeFileSync(join(outDir, reportName), JSON.stringify(results, null, 2), 'utf8');
    await browser?.close();
  }
}

export async function chooseProfile(page, id) {
  await page.getByLabel('Тестовый профиль').selectOption(id);
}

export async function afterPost(page, action, endpoint = '/api/recommend') {
  const [response] = await Promise.all([
    page.waitForResponse((r) => new URL(r.url()).pathname === endpoint && r.request().method() === 'POST'),
    action(),
  ]);
  if (!response.ok()) throw new Error(`${endpoint} вернул HTTP ${response.status()}`);
  // React возвращает исходную подпись кнопки после применения результата запроса.
  await page.getByRole('button', { name: 'Подобрать материалы', exact: true }).waitFor();
  return response;
}

export function submit(page, endpoint) {
  return afterPost(page, () => page.getByRole('button', { name: 'Подобрать материалы', exact: true }).click(), endpoint);
}
