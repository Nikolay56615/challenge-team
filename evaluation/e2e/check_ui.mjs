// Сквозная проверка интерфейса по PLAN.md, 7.1 (E1–E9, E11) в установленном Microsoft Edge.
// Элементы ищутся по ролям и видимым подписям из design/ui-kit.md и PLAN.md, 5.7.
//
// Запуск из корня проекта при работающем сервисе с собранным интерфейсом:
//   node evaluation/e2e/check_ui.mjs <папка playwright-core> [адрес] [папка снимков]
// Пример:
//   node evaluation/e2e/check_ui.mjs <путь-к-node_modules> http://127.0.0.1:8000 evaluation/screens

import { createRequire } from 'node:module';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const [pwDir, base = 'http://127.0.0.1:8000', outDir = 'evaluation/screens'] = process.argv.slice(2);
if (!pwDir) {
  console.error('Укажите папку playwright-core');
  process.exit(2);
}
const require = createRequire(import.meta.url);
const { chromium } = require(resolve(pwDir));
mkdirSync(outDir, { recursive: true });

const results = [];
const check = (id, name, ok, note = '') => {
  results.push({ id, name, ok: Boolean(ok), note });
  console.log(`${ok ? 'PASS' : 'FAIL'} ${id} ${name}${note ? ' — ' + note : ''}`);
};

const browser = await chromium.launch({ channel: 'msedge', headless: true });

async function open(width) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, locale: 'ru-RU' });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text());
  });
  await page.goto(base + '/');
  await page.getByRole('button', { name: 'Подобрать материалы' }).waitFor();
  return { page, context, errors };
}

const shot = (page, name) => page.screenshot({ path: join(outDir, `${name}.png`), fullPage: true });

async function chooseProfile(page, id) {
  const select = page.getByLabel('Тестовый профиль');
  const options = await select.locator('option').evaluateAll((els) => els.map((o) => ({ value: o.value, text: o.textContent })));
  const option = options.find((o) => o.value === id || (o.text || '').startsWith(id));
  await select.selectOption(option.value);
}

async function submit(page, endpoint = /\/api\/(recommend|compare)$/) {
  const response = page.waitForResponse((r) => endpoint.test(new URL(r.url()).pathname) && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Подобрать материалы' }).click();
  await response;
  await page.getByRole('button', { name: 'Подобрать материалы' }).waitFor({ state: 'visible' });
  await page.waitForTimeout(150);
}

async function cards(page, scope) {
  const root = scope || page;
  return root.locator('article.card').evaluateAll((els) =>
    els.map((el) => ({
      label: el.getAttribute('aria-label'),
      title: (el.querySelector('h3')?.textContent || '').trim(),
      text: el.textContent || '',
      links: Array.from(el.querySelectorAll('a')).map((a) => ({ text: (a.textContent || '').trim(), href: a.href, rel: a.rel })),
      buttons: Array.from(el.querySelectorAll('button')).map((b) => (b.textContent || '').trim()),
    })),
  );
}

const T = {
  M01: 'Чек-лист: первые шаги в продвижении',
  M02: 'Курс «Системный маркетинг для растущего бизнеса»',
  M03: 'Шаблон: контент-план на месяц',
  M04: 'Статья: как выбрать аудиторию и первый рекламный канал',
  M05: 'Вебинар: таргетированная реклама с бюджетом до 10 тысяч',
  M07: 'Видео: пять ошибок в продвижении малого бизнеса',
  S02: 'Шаблон: скрипт разговора с клиентом',
  S03: 'Курс «Отдел продаж с нуля»',
};

// E1: чистый запуск — интерфейс и API доступны
{
  const health = await fetch(base + '/api/health').then((r) => r.status).catch(() => 0);
  const { page, context, errors } = await open(1120);
  check('E1', 'Интерфейс открывается, /api/health отвечает', health === 200 && (await page.locator('h1').count()) === 1, `health ${health}`);
  await shot(page, 'initial-1120');
  check('E1', 'Нет ошибок в консоли при загрузке', errors.length === 0, errors.join(' | '));
  await context.close();
}

for (const width of [1120, 390]) {
  const { page, context, errors } = await open(width);
  const tag = `-${width}`;

  // E2: P01
  await chooseProfile(page, 'P01');
  await submit(page);
  let list = await cards(page);
  const top3 = list.slice(0, 3).map((c) => c.title);
  check('E2', `P01: тройка M01, M07, M04 (${width})`, JSON.stringify(top3) === JSON.stringify([T.M01, T.M07, T.M04]), top3.join(' / '));
  const reasonsOk = list.slice(0, 3).every((c) =>
    c.text.includes('стадии') &&
    !c.text.includes('Уровень «') && !c.text.includes('уровня «') &&
    !c.text.includes('Формат «') && !c.text.includes('Займёт около'));
  check('E2', `P01: причины со стадией, без повтора бейджей (${width})`, reasonsOk);
  check('E2', `P01: у M01 названа сфера (${width})`, list[0].text.includes('кафе и рестораны'));
  check('E2', `P01: у карточек есть следующий шаг и действие (${width})`, list.every((c) => c.text.includes('Следующий шаг') && (c.links.length || c.buttons.length)));
  check('E2', `P01: маршрут на первую неделю (${width})`, (await page.getByText('Маршрут на первую неделю').count()) > 0);
  check('E2', `Карточки озвучиваются как «Позиция N» (${width})`, list.every((c, i) => c.label === `Позиция ${i + 1}`));
  await shot(page, `p01${tag}`);

  // E11: «Отметить изученным» на первой карточке
  const taskBefore = await page.getByLabel('Что вы хотите сделать?').inputValue();
  await Promise.all([
    page.waitForResponse((r) => r.url().includes('/api/recommend')),
    page.locator('article.card').first().getByRole('button', { name: 'Отметить изученным' }).click(),
  ]);
  await page.waitForTimeout(200);
  list = await cards(page);
  check('E11', `Изученная карточка уходит вниз, продолжение поднимается (${width})`, list[0].title === T.M04 && !list.slice(0, 5).some((c) => c.title === T.M01), list.map((c) => c.title.slice(0, 20)).join(' / '));
  check('E11', `Форма не очищена (${width})`, (await page.getByLabel('Что вы хотите сделать?').inputValue()) === taskBefore);
  await shot(page, `p01-studied${tag}`);

  // E3: P02
  await chooseProfile(page, 'P02');
  await submit(page);
  list = await cards(page);
  const m02 = list[0];
  check('E3', `P02: первым курс M02 с пользой и переходом (${width})`, m02.title === T.M02 && m02.text.includes('Воронка') && m02.links.some((l) => l.text.includes('Открыть страницу курса')));
  const m05 = list.find((c) => c.title === T.M05);
  check('E3', `P02: у M05 нет перехода и есть примечание (${width})`, m05 && m05.links.length === 0 && m05.text.includes('Ссылка на платформу не передана'));
  check('E3', `P02: пометки истории видны (${width})`, list.some((c) => c.text.includes('Вы уже открывали')));
  const external = list.flatMap((c) => c.links);
  check('E3', `Внешние ссылки с rel noopener noreferrer (${width})`, external.every((l) => l.rel.includes('noopener') && l.rel.includes('noreferrer')));
  await shot(page, `p02${tag}`);

  // E4: сравнение
  await page.getByRole('checkbox', { name: 'Сравнить с подбором по теме' }).check();
  await submit(page, /\/api\/compare$/);
  const compareP02 = await page.content();
  if (width >= 800) {
    const both = (await page.getByRole('heading', { name: /Подбор по теме/ }).count()) > 0 && (await page.getByRole('heading', { name: /Персональный подбор/ }).count()) > 0;
    check('E4', 'Сравнение: две колонки на широком экране', both && (await page.getByRole('tablist').count()) === 0);
  } else {
    const tablist = page.getByRole('tablist', { name: 'Метод подбора' });
    const hasTabs = (await tablist.count()) === 1;
    let switched = false;
    if (hasTabs) {
      const selectedBefore = await tablist.getByRole('tab', { selected: true }).textContent();
      await tablist.getByRole('tab', { selected: true }).focus();
      await page.keyboard.press('ArrowLeft');
      const selectedAfter = await tablist.getByRole('tab', { selected: true }).textContent();
      switched = selectedBefore !== selectedAfter;
    }
    check('E4', 'Сравнение: вкладки на узком экране переключаются стрелками', hasTabs && switched);
  }
  await shot(page, `compare-p02${tag}`);
  await chooseProfile(page, 'P01');
  await submit(page, /\/api\/compare$/);
  check('E4', `Сравнение P01 и P02 отличается в персональной колонке (${width})`, (await page.content()) !== compareP02);

  // E4: задача без темы. Подбор по теме показывает своё сообщение и стартовую подборку, позиции не сравниваются
  await page.getByRole('button', { name: 'Сбросить' }).click();
  await page.getByLabel('Что вы хотите сделать?').fill('Какую CRM выбрать');
  await page.getByRole('checkbox', { name: 'Сравнить с подбором по теме' }).check();
  await submit(page, /\/api\/compare$/);
  const column = (name) => page.locator('.compare__col').filter({ has: page.getByRole('heading', { name, exact: true }) });
  // На узком экране сначала открыта вкладка персонального подбора
  const personalCol = column('Персональный подбор');
  const personalTitles = (await personalCol.isVisible()) ? (await cards(page, personalCol)).map((c) => c.title) : [];
  check('E4', `Без темы: персональный подбор показывает S02 и S03 (${width})`, JSON.stringify([...personalTitles].sort()) === JSON.stringify([T.S02, T.S03].sort()), personalTitles.join(' / '));
  if (width < 800) await page.getByRole('tablist', { name: 'Метод подбора' }).getByRole('tab', { name: 'Подбор по теме' }).click();
  const baselineCol = column('Подбор по теме');
  const baselineNote = baselineCol.getByText('Подбор по теме не нашёл тему в запросе «Какую CRM выбрать».', { exact: true });
  const starterGroup = baselineCol.getByRole('group', { name: 'Стартовая подборка' });
  const starterCards = (await starterGroup.count()) === 1 ? await cards(page, starterGroup) : [];
  check('E4', `Без темы: подбор по теме показывает своё сообщение и стартовую подборку (${width})`, (await baselineNote.isVisible()) && (await starterGroup.isVisible()) && starterCards.length === 5 && (await baselineCol.getByText('порядок одинаков').count()) === 0, `карточек ${starterCards.length}`);
  const compareStatus = (await page.locator('p.status-line').textContent()) || '';
  check('E4', `Без темы: строка состояния не называет изменённые позиции (${width})`, compareStatus === 'Сравнение готово. Подбор по теме не нашёл материалов по запросу.' && (await page.getByText('Изменились позиции').count()) === 0, compareStatus);
  check('E4', `Без темы: нет горизонтальной прокрутки (${width})`, !(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
  await shot(page, `compare-no-topic${tag}`);
  await page.getByRole('checkbox', { name: 'Сравнить с подбором по теме' }).uncheck();

  // E5: пустая форма
  await page.getByRole('button', { name: 'Сбросить' }).click();
  check('E5', `«Сбросить» очищает задачу (${width})`, (await page.getByLabel('Что вы хотите сделать?').inputValue()) === '');
  await submit(page);
  const coldHeading = await page.getByRole('heading', { name: 'С чего хотите начать?' }).count();
  list = await cards(page);
  check('E5', `Пустая форма: вопрос о цели и стартовая подборка (${width})`, coldHeading > 0 && list.length >= 3);
  await shot(page, `cold${tag}`);

  // E6: P05 и выбор темы в баннере
  await chooseProfile(page, 'P05');
  await submit(page);
  const banner = page.getByRole('status').filter({ hasText: 'Уточните тему' });
  check('E6', `P05: уточнение темы (${width})`, (await banner.count()) > 0);
  await shot(page, `p05${tag}`);
  await Promise.all([
    page.waitForResponse((r) => r.url().includes('/api/recommend')),
    page.getByRole('radio', { name: 'Продвижение' }).first().check({ force: true }),
  ]);
  await page.waitForTimeout(200);
  list = await cards(page);
  const marketingOnly = list.every((c) => !c.title.includes('продаж') && !c.title.includes('скрипт'));
  check('E6', `После выбора «Продвижение» выдача по одной теме, форма сохранена (${width})`, marketingOnly && (await page.getByLabel('Что вы хотите сделать?').inputValue()) === 'Хочу больше клиентов');

  // E7: P04
  await chooseProfile(page, 'P04');
  await submit(page);
  const gap = await page.getByRole('heading', { name: /материалов пока нет/ }).count();
  check('E7', `P04: сообщение о пробеле, темы и стартовая подборка (${width})`, gap > 0 && (await page.getByRole('radio').count()) >= 3 && (await cards(page)).length >= 3);
  await shot(page, `p04${tag}`);

  // E8: сбой API и повтор без повторного ввода
  await chooseProfile(page, 'P01');
  await page.route('**/api/recommend', (route) => route.abort('failed'));
  await page.getByRole('button', { name: 'Подобрать материалы' }).click();
  const alert = page.getByRole('alert');
  await alert.waitFor({ timeout: 5000 }).catch(() => {});
  check('E8', `Сбой: баннер ошибки с ролью alert (${width})`, (await alert.count()) > 0 && (await alert.textContent()).includes('Не удалось получить подборку'));
  await shot(page, `error${tag}`);
  await page.unroute('**/api/recommend');
  await Promise.all([page.waitForResponse((r) => r.url().includes('/api/recommend')), page.getByRole('button', { name: 'Повторить' }).click()]);
  await page.waitForTimeout(200);
  list = await cards(page);
  check('E8', `«Повторить» возвращает выдачу без повторного ввода (${width})`, list.length === 5 && list[0].title === T.M01);

  check('E1', `Нет ошибок страницы в сценарии (${width})`, errors.filter((e) => !e.includes('net::ERR_FAILED') && !e.includes('Failed to fetch') && !e.includes('Failed to load resource')).length === 0, errors.join(' | ').slice(0, 300));
  await context.close();
}

// E9: узкий экран и клавиатура
{
  const { page, context } = await open(390);
  const field = page.getByLabel('Что вы хотите сделать?');
  let reached = false;
  for (let i = 0; i < 6 && !reached; i++) {
    await page.keyboard.press('Tab');
    reached = await field.evaluate((el) => el === document.activeElement);
  }
  await page.keyboard.type('Запустить первую рекламу');
  // Уточнения свёрнуты: Tab до summary, Enter раскрывает группы
  await page.keyboard.press('Tab');
  const onSummary = await page.evaluate(() => document.activeElement?.tagName === 'SUMMARY');
  if (onSummary) await page.keyboard.press('Enter');
  // Стадия с клавиатуры: Tab до радиогруппы, стрелка выбирает, пробел снимает выбор
  let onRadio = false;
  for (let i = 0; i < 6 && !onRadio; i++) {
    await page.keyboard.press('Tab');
    onRadio = await page.evaluate(() => document.activeElement?.getAttribute('type') === 'radio');
  }
  await page.keyboard.press('ArrowRight');
  const selected = await page.evaluate(() => document.activeElement?.checked === true);
  await page.keyboard.press('Space');
  const cleared = await page.evaluate(() => document.activeElement?.checked === false);
  check('E9', 'Чип выбирается стрелкой и снимается пробелом', onRadio && selected && cleared);
  const ring = await page.evaluate(() => {
    const el = document.activeElement;
    const target = el?.matches('input[type=radio]') ? el.nextElementSibling : el;
    const s = getComputedStyle(target);
    return { style: s.outlineStyle, width: s.outlineWidth, color: s.outlineColor };
  });
  check('E9', 'Фокус виден: кольцо 2 px', ring.style !== 'none' && ring.width === '2px', JSON.stringify(ring));
  let onSubmit = false;
  for (let i = 0; i < 20 && !onSubmit; i++) {
    await page.keyboard.press('Tab');
    onSubmit = await page.evaluate(() => (document.activeElement?.textContent || '').trim() === 'Подобрать материалы');
  }
  const response = page.waitForResponse((r) => r.url().includes('/api/recommend'));
  await page.keyboard.press('Enter');
  await response;
  await page.waitForTimeout(200);
  const found = await cards(page);
  check('E9', 'Сценарий проходится с клавиатуры на 390 px', onSubmit && found.length > 0, `карточек ${found.length}`);
  const small = await page.evaluate(() =>
    Array.from(document.querySelectorAll('button, a, select, textarea, .chip__label, summary'))
      .filter((el) => el.offsetParent !== null)
      .map((el) => ({ h: el.getBoundingClientRect().height, t: (el.textContent || el.tagName).trim().slice(0, 30) }))
      .filter((x) => x.h < 39.5),
  );
  check('E9', 'Цели нажатия не ниже 40 px', small.length === 0, JSON.stringify(small.slice(0, 5)));
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  check('E9', 'Нет горизонтальной прокрутки на 390 px', !overflow);
  await shot(page, 'keyboard-390');
  await context.close();
}

await browser.close();
writeFileSync(join(outDir, 'results.json'), JSON.stringify(results, null, 2), 'utf8');
const failed = results.filter((r) => !r.ok);
console.log(`\nИтого: ${results.length - failed.length} из ${results.length} проверок пройдено`);
process.exit(failed.length ? 1 : 0);
