// Лента по профилю: вход-развилка, состав оценки, сравнение карточек, клиент по коду,
// два клиента рядом, лента из 50 карточек, «что если», вид клиента, новый клиент, доступность по axe-core
// и отсутствие горизонтальной прокрутки.
//
// Запуск из корня проекта при работающем сервисе с собранным интерфейсом и демо-режимом:
//   npm --prefix evaluation/e2e run check:feed -- [адрес] [папка результатов]

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { base, outDir, runBrowserChecks } from './browser.mjs';
import { contrast, deltaE, fmt, parseColor, VISION, VISION_LABEL } from './color.mjs';

const axeSource = readFileSync(new URL(import.meta.resolve('axe-core/axe.min.js')), 'utf8');
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
// Цвета источников полосы оценки: наименьшее различие пары по CIEDE2000 при обычном зрении и при симуляции
// протанопии, дейтеранопии и тританопии. Порог записан до первого прогона.
const SERIES = ['history', 'content', 'links', 'own', 'neutral'];
const SERIES_MIN = 8;
const rows = [];
let failed = 0;

function check(id, title, ok, detail = '') {
  rows.push({ id, title, ok, detail });
  if (!ok) failed += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${id} ${title}${detail ? ` — ${detail}` : ''}`);
}

const number = (text) => Number(text.replace('−', '-').replace(',', '.').replace(/[^0-9.+-]/g, ''));

async function open(browser, width, path = '/') {
  const context = await browser.newContext({ viewport: { width, height: 900 }, locale: 'ru-RU', bypassCSP: true });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text());
  });
  await page.goto(base + path);
  return { page, context, errors };
}

/** Лента загружена: карточки есть, список не помечен занятым */
async function settled(page) {
  await page.locator('.feed-list article.card').first().waitFor();
  await page.waitForFunction(() => document.querySelector('.feed-list')?.getAttribute('aria-busy') === 'false');
}

async function axe(page, state, width) {
  // Цвета замеряются после переходов, иначе axe видит промежуточные цвета
  await page.evaluate(() => Promise.all(document.getAnimations().map((animation) => animation.finished.catch(() => null))));
  await page.addScriptTag({ content: axeSource });
  const result = await page.evaluate((tags) => window.axe.run(document, { runOnly: { type: 'tag', values: tags } }), TAGS);
  const violations = result.violations.map((v) => `${v.id} (${v.impact}, ${v.nodes.length})`);
  check('F9', `axe-core без нарушений: ${state} (${width})`, violations.length === 0, violations.join('; '));
}

/** Названия карточек; неразрывные пробелы типографа приведены к обычным, чтобы строки сравнивались */
const plain = (text) => text.replace(/\s+/g, ' ');
const titles = async (page) => (await page.locator('.feed-list article.card h3').allInnerTexts()).map(plain);

/** Снимок окна на 1120 px: файлы feed-*.png в папке результатов, для README и презентации */
async function shot(page, width, name) {
  if (width !== 1120) return;
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: join(outDir, `feed-${name}-1120.png`) });
}

/** Цвета источников различимы попарно; у полосы есть текстовая подпись, потому что два цвета светлее порога 3:1 */
async function seriesColors(page) {
  const colors = await page.evaluate((names) => {
    const style = getComputedStyle(document.querySelector('.feed'));
    return names.map((name) => style.getPropertyValue(`--series-${name}`).trim());
  }, SERIES);
  const parsed = colors.map(parseColor);
  let weakest = { value: Infinity };
  for (let i = 0; i < SERIES.length; i++) {
    for (let j = i + 1; j < SERIES.length; j++) {
      for (const type of VISION) {
        const value = parsed[i] && parsed[j] ? deltaE(parsed[i], parsed[j], type) : 0;
        if (value < weakest.value) weakest = { value, pair: `${SERIES[i]} / ${SERIES[j]}`, type };
      }
    }
  }
  check('F21', `Цвета источников полосы различимы попарно при обычном зрении и трёх симуляциях: ΔE00 не меньше ${SERIES_MIN}`,
    weakest.value >= SERIES_MIN, `наименьшее ${fmt(weakest.value, 1)}: ${weakest.pair}, ${VISION_LABEL[weakest.type]}`);
  const surface = parseColor('#ffffff');
  const pale = SERIES.filter((_, i) => parsed[i] && contrast(parsed[i], surface) < 3);
  const labels = await page.locator('.feed-list .score-bar').evaluateAll((bars) => bars.map((bar) => bar.getAttribute('aria-label') || ''));
  check('F21', 'Смысл полосы продублирован текстом: у каждой полосы подпись с оценкой и вкладами',
    labels.length > 0 && labels.every((label) => /^Оценка \d+,\d{2}: /.test(label)), `полос ${labels.length}; светлее 3:1 к поверхности: ${pale.join(', ') || 'нет'}`);
}

await runBrowserChecks('feed-results.json', rows, async (browser) => {
  // 320 px — ширина критерия 1.4.10 WCAG 2.2
  for (const width of [1120, 390, 320]) {
    const { page, context, errors } = await open(browser, width);
    await settled(page);
    if (width === 1120) await seriesColors(page);

    await shot(page, width, 'history');
    const tabs = await page.getByRole('tab').allInnerTexts();
    const selected = await page.getByRole('tab', { selected: true }).innerText();
    check('F1', `Вход — развилка, первой открыта лента клиента с историей (${width})`,
      tabs.length === 3 && selected.replace(/\s+/g, ' ') === 'Клиент с историей', tabs.join(' | '));

    const cards = page.locator('.feed-list article.card');
    const count = await cards.count();
    const scores = (await page.locator('.score__value').allInnerTexts()).map(number);
    check('F2', `Карточки идут по убыванию оценки (${width})`,
      count > 1 && scores.every((value, i) => i === 0 || value <= scores[i - 1]), `${count} карточек, первая ${scores[0]}`);
    const taskReasons = (await page.locator('.feed-card__reason').allInnerTexts()).filter((t) => t.includes('совпадает с задачей'));
    check('F3', `Без задачи нет причины «совпадает с задачей» (${width})`, taskReasons.length === 0);

    await cards.nth(1).getByRole('button', { name: 'Как посчитано' }).click();
    const values = (await cards.nth(1).locator('.feed-parts__value').allInnerTexts()).map(number);
    const sum = Math.round(values.reduce((a, b) => a + b, 0) * 100) / 100;
    check('F4', `Оценка второй карточки равна сумме вкладов (${width})`, values.length > 0 && sum === scores[1], `${sum} и ${scores[1]}`);
    const evidence = await cards.nth(1).locator('.feed-parts__evidence').allInnerTexts();
    check('F5', `У каждого вклада есть свидетельство (${width})`, evidence.every((text) => text.trim().length > 0));
    // Две карточки рядом: строка «Оценка» таблицы сравнения — оценки обеих карточек и их разница
    const cells = async (table) => (await table.locator('tfoot td').allInnerTexts()).map(number);
    const inCard = await cells(cards.nth(1).locator('.compare-table'));
    check('F6', `В расчёте карточка стоит рядом с первой: оценки и разница сходятся (${width})`,
      inCard[0] === scores[1] && inCard[1] === scores[0] && Math.abs(inCard[2] - (scores[1] - scores[0])) < 0.005, inCard.join(' / '));
    const top = page.locator('.layout__content > .compare-table');
    const topCells = await cells(top);
    const deltas = (await top.locator('tbody td:last-child').allInnerTexts()).map(number);
    const deltaSum = Math.round(deltas.reduce((a, b) => a + b, 0) * 100) / 100;
    check('F6', `Первая и последняя карточки рядом: разницы по источникам дают разницу оценок (${width})`,
      topCells[0] === scores[0] && Math.abs(deltaSum - topCells[2]) < 0.005, `${deltaSum} и ${topCells[2]}`);
    // Паспорт модели: качество на журнале по трём группам, у каждой три метода рядом
    await page.locator('summary', { hasText: 'Паспорт модели' }).click();
    const passport = page.locator('.passport-table');
    const methods = await passport.first().locator('tbody th').allInnerTexts();
    const shares = await passport.locator('tbody td').allInnerTexts();
    check('F16', `Паспорт модели показывает три группы и три метода с долями (${width})`,
      (await passport.count()) === 3 && methods.join('|') === 'Лента|Только совместные записи|Популярность' && shares.length === 18 && shares.every((text) => /^\d+\s%$/.test(text)),
      shares.join(' '));
    // Ячейки таблиц переносят слово только при увеличенных интервалах текста; в обычном виде слово цело.
    // Признак разрыва: строк в ячейке больше, чем слов. Подписи источников в первой колонке сюда не входят
    const torn = await page.evaluate(() => {
      const range = document.createRange();
      const found = [];
      for (const cell of document.querySelectorAll('.compare-table thead th, .compare-table tfoot th, .compare-table td, .passport-table thead th')) {
        const text = cell.textContent.trim();
        if (!text || !cell.checkVisibility()) continue;
        range.selectNodeContents(cell);
        const lines = new Set(Array.from(range.getClientRects()).filter((r) => r.width > 0.5).map((r) => Math.round(r.top)));
        if (lines.size > text.split(/\s+/).length) found.push(text);
      }
      return [...new Set(found)];
    });
    check('F22', `Заголовки и числа таблиц не разорваны посреди слова (${width})`, torn.length === 0, torn.join(', '));
    await axe(page, 'лента клиента с историей, расчёт карточки и паспорт модели', width);
    if (width === 1120) await cards.nth(1).screenshot({ path: join(outDir, 'feed-card-details-1120.png') });
    if (width === 1120) await page.locator('details.disclosure', { hasText: 'Паспорт модели' }).screenshot({ path: join(outDir, 'feed-passport-1120.png') });

    const reflow = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
    check('F8', `Страница без горизонтальной прокрутки (${width})`, reflow);

    // Клиент по коду: неизвестный код называет ошибку и ленту не трогает, известный открывает клиента
    const firstClient = await page.getByLabel('Клиент', { exact: true }).inputValue();
    const codeField = page.getByLabel('Код клиента');
    await codeField.fill('U9999');
    await page.getByRole('button', { name: 'Найти' }).click();
    const codeError = (await page.locator('#feed-code-error').innerText()).replace(/\s+/g, ' ');
    check('F13', `Неизвестный код назван в ошибке, клиент прежний (${width})`,
      codeError === 'Клиента с кодом «U9999» нет в журнале' && (await page.getByLabel('Клиент', { exact: true }).inputValue()) === firstClient, codeError);
    if (width === 1120) await page.locator('.layout__aside .panel').first().screenshot({ path: join(outDir, 'feed-code-error-1120.png') });
    // Карточка материала без журнала записей: причина говорит о содержании, а не о выборе слушателей
    const byContent = page.locator('.feed-list article.card', { hasText: 'Похоже на материалы из истории' }).first();
    if (width === 1120) await byContent.screenshot({ path: join(outDir, 'feed-content-card-1120.png') });
    const ownTitles = await titles(page);
    await codeField.fill('u0008');
    await codeField.press('Enter');
    await page.waitForFunction(() => document.querySelector('#feed-client')?.value === 'U0008');
    await settled(page);
    const history = await page.locator('.feed-history li').count();
    check('F13', `Код без учёта регистра открывает клиента, его историю и ленту (${width})`,
      (await titles(page)).join('|') !== ownTitles.join('|') && history > 1 && (await codeField.inputValue()) === '', `${history} событий истории`);
    const sharedText = (await page.locator('.banner--info').innerText()).replace(/\s+/g, ' ');
    check('F15', `После смены клиента названо число общих карточек двух лент (${width})`,
      new RegExp(`Общих карточек с лентой клиента ${firstClient}: \\d+ из 20\\.`).test(sharedText), sharedText);
    await page.getByRole('button', { name: /^Показать первые/ }).click();
    await page.waitForFunction(() => document.querySelectorAll('.feed-list article.card').length === 50);
    await settled(page);
    const fullScores = (await page.locator('.score__value').allInnerTexts()).map(number);
    check('F14', `Лента из 50 карточек идёт по убыванию оценки (${width})`,
      fullScores.length === 50 && fullScores.every((value, i) => i === 0 || value <= fullScores[i - 1]), `${fullScores[0]} … ${fullScores[49]}`);
    await page.getByLabel('Клиент', { exact: true }).selectOption(firstClient);
    await settled(page);

    // Два клиента рядом: общие карточки числом, доли источников полосами, первые десять карточек по местам
    await page.locator('#feed-compare').selectOption('U0008');
    const compare = page.locator('.client-compare');
    await compare.waitFor();
    const marked = await compare.locator('tbody tr td:nth-child(2) .client-compare__shared').count();
    check('F18', `Два клиента рядом: две полосы источников и десять мест (${width})`,
      marked > 0 && (await compare.locator('.score-bar').count()) === 2 && (await compare.locator('tbody tr').count()) === 10,
      `Помечено в первой колонке: ${marked}`);
    await axe(page, 'два клиента рядом', width);
    if (width === 1120) await compare.screenshot({ path: join(outDir, 'feed-compare-clients-1120.png') });
    await page.locator('#feed-compare').selectOption('');
    await compare.waitFor({ state: 'detached' });

    // «Что если»: убрать событие истории и вернуть его
    const beforeTitles = await titles(page);
    await page.locator('.feed-history input[type=checkbox]').first().uncheck();
    await settled(page);
    const afterTitles = await titles(page);
    const banner = await page.locator('.banner--info').innerText();
    check('F7', `Без события истории лента меняется, изменение названо (${width})`,
      afterTitles.join('|') !== beforeTitles.join('|') && /Новых карточек: \d+\. Ушло: \d+\. Сменили место: \d+\./.test(banner), banner.replace(/\s+/g, ' '));
    await page.getByRole('button', { name: 'Вернуть исходную историю' }).click();
    await settled(page);
    check('F7', `Исходная история возвращает прежнюю ленту (${width})`, (await titles(page)).join('|') === beforeTitles.join('|'));

    // «Что если» в другую сторону: отметить карточку пройденной
    const target = (await titles(page))[1];
    await cards.nth(1).getByRole('button', { name: 'Как посчитано' }).click();
    await cards.nth(1).getByRole('button', { name: 'Отметить пройденным' }).click();
    await settled(page);
    const withAdded = await titles(page);
    await shot(page, width, 'what-if');
    const historyText = plain(await page.locator('.feed-history').innerText());
    check('F7', `Пройденная карточка уходит из ленты в историю (${width})`,
      !withAdded.includes(target) && historyText.includes(target), target);

    // Вид клиента: те же карточки без оценки, расчёта и панелей
    await page.getByRole('checkbox', { name: /Вид клиента/ }).check();
    await settled(page);
    const ownReason = plain(await page.locator('.feed-card__reason').first().innerText());
    check('F19', `Вид клиента: карточки без оценки, расчёта и панелей (${width})`,
      (await page.locator('.score').count()) === 0 && (await page.getByRole('button', { name: 'Как посчитано' }).count()) === 0
        && (await page.locator('.feed-history, .compare-table, .feed-legend').count()) === 0 && ownReason.length > 0 && !ownReason.includes('клиента'), ownReason);
    // Сколько карточек целиком входит в первый экран телефона высотой 844 px
    const onScreen = await page.evaluate(() =>
      [...document.querySelectorAll('.feed-list article.card')].filter((card) => card.getBoundingClientRect().bottom <= 844).length);
    if (width === 390) check('F20', 'Вид клиента на 390 px: в первый экран входит не меньше трёх карточек', onScreen >= 3, `карточек: ${onScreen}`);
    check('F19', `В виде клиента вкладки путей скрыты, флажок возврата виден (${width})`,
      (await page.getByRole('tab').count()) === 0 && (await page.getByRole('checkbox', { name: /Вид клиента/ }).isVisible()));
    await axe(page, 'вид клиента', width);
    await page.evaluate(() => window.scrollTo(0, 0));
    if (width !== 320) await page.screenshot({ path: join(outDir, `feed-client-view-${width}.png`) });
    await page.getByRole('checkbox', { name: /Вид клиента/ }).uncheck();
    await settled(page);

    // Новый клиент: лента без истории и один необязательный вопрос
    await page.getByRole('tab', { name: 'Новый клиент' }).click();
    await settled(page);
    const status = await page.locator('.status-line').innerText();
    const selects = await page.locator('main select').count();
    check('F10', `Новый клиент сразу видит ленту и два необязательных вопроса (${width})`,
      status.startsWith('Порядок задают популярные материалы.') && selects === 2 && (await page.locator('.field__optional').count()) === 2, status);
    const coldTop = (await titles(page))[0];
    await page.getByLabel('Стадия бизнеса').selectOption({ index: 1 });
    await settled(page);
    const staged = await page.locator('.feed-card__reason').first().innerText();
    check('F10', `Ответ о стадии меняет ленту и причину первой карточки (${width})`, /стади/i.test(staged), `${coldTop} → ${staged}`);
    const stagedTitles = await titles(page);
    await page.getByLabel('Сфера бизнеса').selectOption('horeca');
    await settled(page);
    const industryBanner = (await page.locator('.banner--info').innerText()).replace(/\s+/g, ' ');
    check('F17', `Ответ о сфере бизнеса меняет ленту, изменение названо (${width})`,
      (await titles(page)).join('|') !== stagedTitles.join('|') && /Сменили место: \d+\./.test(industryBanner), industryBanner);
    await axe(page, 'лента нового клиента', width);
    await shot(page, width, 'new-client');

    await page.getByRole('button', { name: 'Есть конкретная задача? Подобрать по задаче' }).click();
    await page.getByRole('button', { name: 'Подобрать материалы' }).waitFor();
    check('F11', `Подбор по задаче открывается как дополнительный путь (${width})`,
      (await page.getByRole('tab', { selected: true }).innerText()).replace(/\s+/g, ' ') === 'Подбор по задаче');

    check('F12', `Нет ошибок в консоли и нарушений CSP (${width})`, errors.length === 0, errors.join(' | '));
    await context.close();
  }
  console.log(`\nИтого: ${rows.length - failed} из ${rows.length} проверок пройдено`);
});

process.exit(failed ? 1 : 0);
