import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { chromium } from 'playwright-core';

export const [base = 'http://127.0.0.1:8000', outDir = join(import.meta.dirname, '.results')] = process.argv.slice(2);

// Проверки идут в Chromium из Playwright (npm run install:browser), как в CI.
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
  // На быстром ответе подпись не меняется. Ждём снятия aria-disabled после применения результата.
  await page.locator('.actions .btn--primary:not([aria-disabled="true"])').waitFor();
  return response;
}

export function submit(page, endpoint) {
  return afterPost(page, () => page.getByRole('button', { name: 'Подобрать материалы', exact: true }).click(), endpoint);
}

export const TASK_LABEL = 'Что вы хотите сделать?';

/**
 * Проход по состояниям экрана для check_wcag.mjs и check_cvd.mjs; visit(state) вызывается в каждом.
 * На 1120 px — 15 состояний, на узком экране ещё две вкладки «Подбор по теме» в сравнении.
 */
export async function walkStates(page, width, visit) {
  const narrow = width < 800;
  const compareBox = page.getByRole('checkbox', { name: 'Сравнить с подбором по теме' });
  const methodTab = (name) => page.getByRole('tablist', { name: 'Метод подбора' }).getByRole('tab', { name });

  await page.getByRole('button', { name: 'Подобрать материалы' }).waitFor();
  await visit('начальный экран');
  await page.locator('summary').filter({ hasText: 'Уточнения' }).click();
  await visit('уточнения раскрыты');

  await chooseProfile(page, 'P01');
  await submit(page);
  await visit('P01: выдача и маршрут');
  await chooseProfile(page, 'P02');
  await submit(page);
  await visit('P02: платные карточки и пометки');

  await compareBox.check();
  await submit(page, '/api/compare');
  await visit('сравнение P02: персональный подбор');
  if (narrow) {
    await methodTab('Подбор по теме').click();
    await visit('сравнение P02: подбор по теме');
  }
  await page.getByRole('button', { name: 'Сбросить', exact: true }).click();
  await page.getByLabel(TASK_LABEL).fill('Какую CRM выбрать');
  await compareBox.check();
  await submit(page, '/api/compare');
  await visit('сравнение без темы: персональный подбор');
  if (narrow) {
    await methodTab('Подбор по теме').click();
    await visit('сравнение без темы: подбор по теме');
  }
  await compareBox.uncheck();

  await page.getByRole('button', { name: 'Сбросить', exact: true }).click();
  await submit(page);
  await visit('пустая форма: стартовая подборка');
  const showAll = page.getByRole('button', { name: /^Показать все/ });
  await showAll.click();
  await showAll.waitFor({ state: 'detached' });
  await page.getByRole('button', { name: 'Подобрать материалы', exact: true }).waitFor();
  await visit('стартовая подборка раскрыта');

  await chooseProfile(page, 'P05');
  await submit(page);
  await visit('P05: уточнение темы');
  await afterPost(page, () => page.getByRole('status').filter({ hasText: 'Уточните тему' }).getByText('Продвижение', { exact: true }).click());
  await visit('P05: выбрана тема');

  await chooseProfile(page, 'P04');
  await submit(page);
  await visit('P04: пробел и стартовая подборка');
  await chooseProfile(page, 'P07');
  await submit(page);
  await visit('P07: узкий запрос');
  await afterPost(page, () => page.getByRole('group', { name: 'Тема', exact: true }).getByText('Продажи', { exact: true }).click());
  await visit('P07: выбраны «Продажи»');

  await chooseProfile(page, 'P01');
  await page.route('**/api/recommend', (route) => route.abort('failed'));
  await page.getByRole('button', { name: 'Подобрать материалы' }).click();
  await page.getByRole('alert').waitFor({ timeout: 5000 });
  await visit('ошибка запроса');
  await page.unroute('**/api/recommend');

  // Ошибка поля: сервер получает задачу длиннее 300 символов и отвечает 422 с подробностями по полю task
  await page.route('**/api/recommend', (route) => route.continue({ postData: { ...route.request().postDataJSON(), task: 'а'.repeat(301) } }));
  await Promise.all([
    page.waitForResponse((r) => new URL(r.url()).pathname === '/api/recommend' && r.status() === 422),
    page.getByRole('button', { name: 'Подобрать материалы' }).click(),
  ]);
  await page.locator('.field__error').waitFor();
  await page.unroute('**/api/recommend');
  await visit('ошибка поля задачи');
}

/**
 * Что в панели «Демо-режим» выходит за область содержимого панели или сама панель — за окно.
 * Пустой список — всё на месте; null — панели нет.
 */
export function demoPanelOverflow(page) {
  return page.evaluate(() => {
    const heading = Array.from(document.querySelectorAll('main h2')).find((h) => h.textContent.trim() === 'Демо-режим');
    const panel = heading?.closest('.panel');
    if (!panel) return null;
    const p = panel.getBoundingClientRect();
    const cs = getComputedStyle(panel);
    const left = p.left + parseFloat(cs.borderLeftWidth) + parseFloat(cs.paddingLeft);
    const right = p.right - parseFloat(cs.borderRightWidth) - parseFloat(cs.paddingRight);
    const px = (x) => Math.round(x);
    const out = [];
    if (p.left < -0.5 || p.right > innerWidth + 0.5) out.push(`панель ${px(p.left)}–${px(p.right)} при окне ${innerWidth}`);
    for (const el of panel.querySelectorAll('*')) {
      const r = el.getBoundingClientRect();
      if (el.closest('.visually-hidden') || el.tagName === 'OPTION' || (r.width === 0 && r.height === 0)) continue;
      if (r.left < left - 0.5 || r.right > right + 0.5) {
        out.push(`${el.tagName.toLowerCase()}.${String(el.className).split(' ')[0]} ${px(r.left)}–${px(r.right)} при ${px(left)}–${px(right)}`);
      }
    }
    return out;
  });
}
