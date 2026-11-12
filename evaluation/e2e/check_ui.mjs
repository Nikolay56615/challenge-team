// Сквозная проверка интерфейса по PLAN.md, 7.1 (E1–E9, E11–E13).
// Элементы ищутся по ролям и видимым подписям из design/ui-kit.md и PLAN.md, 5.7.
//
// Запуск из корня проекта при работающем сервисе с собранным интерфейсом:
//   npm --prefix evaluation/e2e run check:ui -- [адрес] [папка результатов]

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterPost, base, chooseProfile, outDir, runBrowserChecks, selectCatalogTopic, submit } from './browser.mjs';

const results = [];
const check = (id, name, ok, note = '') => {
  results.push({ id, name, ok: Boolean(ok), note });
  console.log(`${ok ? 'PASS' : 'FAIL'} ${id} ${name}${note ? ' — ' + note : ''}`);
};

async function open(browser, width, prepare) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, locale: 'ru-RU' });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text());
  });
  if (prepare) await prepare(page);
  await page.goto(base + '/');
  await page.getByRole('button', { name: 'Подобрать материалы' }).waitFor();
  return { page, context, errors };
}

const shot = (page, name) => page.screenshot({ path: join(outDir, `${name}.png`), fullPage: true });

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

const compareColumn = (page, name) =>
  page.locator('.compare__col').filter({ has: page.getByRole('heading', { name, exact: true }) });

async function comparisonTitles(page, width, name) {
  if (width < 800) await page.getByRole('tab', { name, exact: true }).click();
  const column = compareColumn(page, name);
  await column.waitFor();
  return (await cards(page, column)).map((card) => card.title);
}

async function checkTopicNavigation(browser, width) {
  const { page, context } = await open(browser, width);
  try {
    await chooseProfile(page, 'P02');
    const nav = page.getByRole('navigation', { name: 'Разделы' });
    const openCatalog = nav.getByRole('link', { name: 'Каталог', exact: true });
    const openRecommend = nav.getByRole('link', { name: 'Подбор', exact: true });
    const task = page.getByLabel('Что вы хотите сделать?');
    const submitted = [];
    page.on('request', (request) => {
      if (request.method() === 'POST') submitted.push(request);
    });

    const original = await submit(page);
    const originalBody = original.request().postDataJSON();
    const originalCards = (await cards(page)).map((card) => card.title);
    const draft = 'Какую CRM выбрать';
    await task.fill(draft);
    await openCatalog.focus();
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.activeElement?.matches('h1') && document.activeElement.textContent === 'Каталог');
    check('E5', `Каталог открывается с клавиатуры, форма остаётся в «Подборе» (${width})`,
      new URL(page.url()).hash === '#catalog' && (await openCatalog.getAttribute('aria-current')) === 'page' &&
      !(await task.isVisible()) && submitted.length === 1);

    const picker = page.getByLabel('Тема каталога', { exact: true });
    const list = page.getByRole('list', { name: 'Темы каталога' });
    if (width < 800) {
      await picker.focus();
      await page.keyboard.press('Home');
      for (let i = 0; i < 4; i++) await page.keyboard.press('ArrowDown');
      check('E5', `На узком экране выбор темы ждёт подтверждения (${width})`,
        (await picker.inputValue()) === 'marketing' && submitted.length === 1 && !(await list.isVisible()));
      await page.keyboard.press('Tab');
    } else {
      await list.getByRole('button', { name: 'Продвижение', exact: true }).focus();
      check('E5', `На широком экране сразу видны все темы (${width})`,
        (await list.getByRole('button').count()) === 6 && !(await picker.isVisible()));
    }
    const opened = await afterPost(page, () => page.keyboard.press('Enter'));
    const topicBody = opened.request().postDataJSON();
    const topicHeading = page.getByRole('heading', { name: 'Подборка по теме «Продвижение»', exact: true });
    await page.waitForFunction(() => document.activeElement?.textContent === 'Подборка по теме «Продвижение»');
    check('E5', `Тема использует уточнения и историю сеанса (${width})`,
      topicBody.task === '' && topicBody.topic === 'marketing' && topicBody.limit === 5 &&
      topicBody.stage === 'growth' && topicBody.format_pref === 'course' && topicBody.history.length === 3 &&
      (await page.getByText('Показано 5 из 8 материалов', { exact: true }).isVisible()));
    const more = await afterPost(page, () => page.getByRole('button', { name: 'Показать ещё 3' }).click());
    const beforeBack = submitted.length;
    await page.goBack();
    await page.waitForFunction(() => document.activeElement?.textContent === 'Подберём материалы под вашу задачу');
    check('E5', `«Назад» восстанавливает задачу и прежние карточки (${width})`,
      (await task.inputValue()) === draft && submitted.length === beforeBack &&
      JSON.stringify((await cards(page)).map((card) => card.title)) === JSON.stringify(originalCards));
    await page.goForward();
    await page.waitForFunction(() => document.activeElement?.matches('h1') && document.activeElement.textContent === 'Каталог');
    check('E5', `«Вперёд» восстанавливает раскрытый список темы (${width})`,
      submitted.length === beforeBack && (await topicHeading.isVisible()) &&
      (await page.getByText('Показано 8 из 8 материалов', { exact: true }).isVisible()) &&
      more.request().postDataJSON().limit === 10);
    await shot(page, `catalog-${width}`);

    const filters = page.getByRole('group', { name: 'Фильтры выдачи' });
    const format = filters.getByLabel('Формат', { exact: true });
    await format.selectOption('template');
    await afterPost(page, () => filters.getByRole('button', { name: 'Применить фильтры' }).click());
    await openRecommend.click();
    await task.waitFor();
    await openCatalog.click();
    await page.getByRole('heading', { name: 'Каталог', exact: true }).waitFor();
    await format.waitFor();
    check('E5', `Фильтр каталога переживает переходы (${width})`,
      (await format.inputValue()) === 'template' && (await cards(page)).length === 2);

    const studied = await afterPost(page, () => page.getByRole('button', { name: 'Отметить изученным' }).first().click());
    const studiedBody = studied.request().postDataJSON();
    const refreshed = await afterPost(page, () => openRecommend.click());
    const refreshedBody = refreshed.request().postDataJSON();
    check('E11', `Изучение обновляет каталог сразу, а подбор при возврате (${width})`,
      studiedBody.topic === 'marketing' && studiedBody.filters.format === 'template' &&
      studiedBody.history.at(-1)?.event === 'complete' &&
      refreshedBody.task === originalBody.task && refreshedBody.topic === originalBody.topic &&
      refreshedBody.limit === originalBody.limit && JSON.stringify(refreshedBody.history) === JSON.stringify(studiedBody.history) &&
      (await task.inputValue()) === draft);

    await openCatalog.click();
    let failedBody;
    await page.route('**/api/recommend', (route) => {
      failedBody = route.request().postDataJSON();
      return route.abort('failed');
    });
    await selectCatalogTopic(page, width, 'sales', 'Продажи');
    await page.getByRole('alert').waitFor();
    await page.unroute('**/api/recommend');
    const retry = await afterPost(page, () => page.getByRole('button', { name: 'Повторить', exact: true }).click());
    check('E8', `Новая тема сбрасывает фильтры, повтор сохраняет параметры (${width})`,
      JSON.stringify(retry.request().postDataJSON()) === JSON.stringify(failedBody) &&
      failedBody.topic === 'sales' && failedBody.limit === 5 && !failedBody.filters);

    await openRecommend.click();
    const compareToggle = page.getByRole('checkbox', { name: 'Сравнить с подбором по теме' });
    await compareToggle.check();
    await openCatalog.click();
    const compared = await afterPost(page, () => selectCatalogTopic(page, width, 'marketing', 'Продвижение'), '/api/compare');
    const comparison = await compared.json();
    check('E4', `Режим сравнения действует в каталоге (${width})`,
      [comparison.baseline, comparison.personal].every((outcome) => outcome.detected_topics.join() === 'marketing') &&
      (await page.getByRole('heading', { name: 'Сравнение по теме «Продвижение»' }).isVisible()));
    await openRecommend.click();
    await compareToggle.uncheck();

    await page.route('**/api/recommend', async (route) => {
      const response = await route.fetch();
      const data = await response.json();
      if (data.status === 'none' && data.clarification) {
        data.clarification.options.push(
          { value: 'strategy', label: 'Стратегия' },
          { value: 'tech', label: 'Технологии и ИИ' },
          { value: 'marketplaces', label: 'Маркетплейсы' },
        );
      }
      await route.fulfill({ response, json: data });
    });
    await chooseProfile(page, 'P04');
    await submit(page);
    const fallback = page.getByRole('region', { name: /материалов пока нет/ });
    const fallbackPicker = fallback.getByLabel('Тема', { exact: true });
    const requestsBefore = submitted.length;
    await fallbackPicker.selectOption('sales');
    const waited = submitted.length === requestsBefore;
    const chosen = await afterPost(page, () => fallback.getByRole('button', { name: 'Показать материалы темы' }).click());
    const chosenData = await chosen.json();
    check('E7', `В пустой выдаче длинный список тем ждёт подтверждения (${width})`,
      waited && chosen.request().postDataJSON().topic === 'sales' && chosenData.status === 'strong' &&
      (await page.getByRole('heading', { name: 'Подборка по теме «Продажи»' }).isVisible()));

    const direct = await context.newPage();
    await direct.route('**/api/meta', (route) => route.abort('failed'));
    await direct.goto(base + '/#catalog');
    await direct.getByRole('alert').filter({ hasText: 'Не удалось загрузить темы каталога' }).waitFor();
    await direct.unroute('**/api/meta');
    await direct.getByRole('button', { name: 'Повторить', exact: true }).click();
    await (width < 800
      ? direct.getByLabel('Тема каталога', { exact: true })
      : direct.getByRole('list', { name: 'Темы каталога' })).waitFor();
    check('E8', `Прямая ссылка открывает каталог, повтор восстанавливает темы (${width})`,
      (await direct.getByRole('link', { name: 'Каталог' }).getAttribute('aria-current')) === 'page' &&
      (await direct.getByRole('alert').count()) === 0);
  } finally {
    await context.close();
  }
}

async function checkResultFilters(browser, width) {
  const { page, context } = await open(browser, width);
  try {
    await chooseProfile(page, 'P05');
    await submit(page);
    const filters = page.getByRole('group', { name: 'Фильтры выдачи' });
    const format = filters.getByLabel('Формат', { exact: true });
    const access = filters.getByLabel('Доступ', { exact: true });
    const apply = filters.getByRole('button', { name: 'Применить фильтры' });
    const reset = filters.getByRole('button', { name: 'Сбросить фильтры' });
    await access.focus();
    await page.keyboard.press('Home');
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Tab');
    const onApply = await apply.evaluate((element) => element === document.activeElement);
    const applied = await afterPost(page, () => page.keyboard.press('Enter'));
    const appliedBody = applied.request().postDataJSON();
    const appliedData = await applied.json();
    await page.waitForFunction(() => document.activeElement?.textContent === 'Показано 5 из 8 материалов');
    check('E12', `Клавиатура применяет доступ, счётчик и фокус обновляются (${width})`,
      onApply && appliedBody.filters.access === 'open' && appliedData.total_candidates === 8 &&
      appliedData.items.every((item) => item.access === 'open'));

    const more = await afterPost(page, () => page.getByRole('button', { name: 'Показать ещё 3' }).click());
    const complete = page.locator('article.card').first().getByRole('button', { name: 'Отметить изученным' });
    const studied = await afterPost(page, () => complete.click());
    const studiedBody = studied.request().postDataJSON();
    check('E12', `Раскрытие и отметка сохраняют фильтр (${width})`,
      more.request().postDataJSON().filters.access === 'open' && (await more.json()).items.length === 8 &&
      studiedBody.filters.access === 'open' && studiedBody.history.at(-1)?.event === 'complete' &&
      (await page.getByRole('heading', { name: 'Показано 8 из 8 материалов' }).isVisible()));

    await format.selectOption('template');
    let failedBody;
    await page.route('**/api/recommend', (route) => {
      failedBody = route.request().postDataJSON();
      return route.abort('failed');
    });
    await apply.click();
    await page.getByRole('alert').waitFor();
    await page.unroute('**/api/recommend');
    const retried = await afterPost(page, () => page.getByRole('button', { name: 'Повторить' }).click());
    const topic = page.getByRole('group', { name: 'Тема', exact: true });
    const clarified = await afterPost(page, () => topic.getByText('Продажи', { exact: true }).click());
    check('E12', `Повтор и уточнение сохраняют оба фильтра (${width})`,
      JSON.stringify(retried.request().postDataJSON()) === JSON.stringify(failedBody) &&
      clarified.request().postDataJSON().filters.format === 'template' &&
      clarified.request().postDataJSON().filters.access === 'open' &&
      clarified.request().postDataJSON().topic === 'sales');

    await access.selectOption('paid');
    await afterPost(page, () => apply.click());
    const empty = page.getByRole('paragraph').filter({ hasText: /^По выбранным фильтрам материалов нет$/ });
    check('E12', `Пустая выдача показывает сообщение и сброс (${width})`,
      await empty.isVisible() && await reset.isEnabled() && (await cards(page)).length === 0 &&
      (await page.getByText('Стартовая подборка', { exact: true }).count()) === 0);
    await shot(page, `filters-empty-${width}`);
    await reset.focus();
    const cleared = await afterPost(page, () => page.keyboard.press('Enter'));
    await page.waitForFunction(() => document.activeElement?.textContent === 'Подборка по теме «Продажи»');
    check('E12', `Сброс с клавиатуры восстанавливает выдачу и фокус (${width})`,
      cleared.request().postDataJSON().filters === null && (await cleared.json()).total_candidates === 4);

    await chooseProfile(page, 'P02');
    await page.getByRole('checkbox', { name: 'Сравнить с подбором по теме' }).check();
    await submit(page, '/api/compare');
    await format.selectOption('course');
    const compared = await afterPost(page, () => apply.click(), '/api/compare');
    const comparison = await compared.json();
    for (const name of ['Подбор по теме', 'Персональный подбор']) {
      check('E12', `В сравнении видны только курсы метода «${name}» (${width})`,
        (await comparisonTitles(page, width, name)).length === 2);
    }
    check('E12', `Формат применяется к обоим методам (${width})`,
      await filters.count() === 1 && [comparison.baseline, comparison.personal].every((method) =>
        method.total_candidates === 2 && method.items.every((item) => item.format === 'course')));
  } finally {
    await context.close();
  }
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

await runBrowserChecks('results.json', results, async (browser) => {
  // E1: чистый запуск — интерфейс и API доступны
  {
    const health = await fetch(base + '/api/health').then((r) => r.status).catch(() => 0);
    const { page, context, errors } = await open(browser, 1120);
    await page.getByText('Тестовый каталог', { exact: true }).waitFor();
    check('E1', 'Интерфейс открывается, /api/health отвечает', health === 200 && (await page.locator('h1').count()) === 1, `health ${health}`);
    await shot(page, 'initial-1120');
    check('E1', 'Нет ошибок в консоли при загрузке', errors.length === 0, errors.join(' | '));
    await context.close();
  }

  for (const width of [1120, 390]) {
    const { page, context, errors } = await open(browser, width);
    const tag = `-${width}`;

    // E2: P01
    await chooseProfile(page, 'P01');
    await submit(page);
    let list = await cards(page);
    const singleP01 = list.map((c) => c.title);
    const top3 = singleP01.slice(0, 3);
    check('E2', `P01: тройка M01, M07, M04 (${width})`, JSON.stringify(top3) === JSON.stringify([T.M01, T.M07, T.M04]), top3.join(' / '));
    const reasonsOk = list.slice(0, 3).every((c) =>
      c.text.includes('стадии') &&
      !c.text.includes('Уровень «') && !c.text.includes('уровня «') &&
      !c.text.includes('Формат «') && !c.text.includes('Займёт около'));
    check('E2', `P01: причины со стадией, без повтора бейджей (${width})`, reasonsOk);
    check('E2', `P01: у M01 названа сфера (${width})`, list[0].text.includes('кафе и рестораны'));
    check('E2', `P01: карточки показывают доступные действия (${width})`,
      list.every((c) => c.links.length ? c.text.includes('Следующий шаг') : c.buttons.includes('Скопировать название')));
    check('E2', `P01: маршрут на первую неделю (${width})`, (await page.getByText('Маршрут на первую неделю').count()) > 0);
    check('E2', `Карточки озвучиваются как «Позиция N» (${width})`, list.every((c, i) => c.label === `Позиция ${i + 1}`));
    await shot(page, `p01${tag}`);

    // E11: «Отметить изученным» на первой карточке
    const taskBefore = await page.getByLabel('Что вы хотите сделать?').inputValue();
    await afterPost(page, () => page.locator('article.card').first().getByRole('button', { name: 'Отметить изученным' }).click());
    list = await cards(page);
    check('E11', `Изученная карточка уходит вниз, продолжение поднимается (${width})`, list[0].title === T.M04 && !list.slice(0, 5).some((c) => c.title === T.M01), list.map((c) => c.title.slice(0, 20)).join(' / '));
    check('E11', `Форма не очищена (${width})`, (await page.getByLabel('Что вы хотите сделать?').inputValue()) === taskBefore);
    await shot(page, `p01-studied${tag}`);

    // E3: P02
    await chooseProfile(page, 'P02');
    await submit(page);
    list = await cards(page);
    const singleP02 = list.map((c) => c.title);
    const m02 = list[0];
    check('E3', `P02: первым курс M02 с пользой и переходом (${width})`, m02.title === T.M02 && m02.text.includes('Воронка') && m02.links.some((l) => l.text.includes('Открыть страницу курса')));
    const m05 = list.find((c) => c.title === T.M05);
    check('E3', `P02: у M05 есть копирование и примечание вместо перехода (${width})`,
      m05 && m05.links.length === 0 && m05.buttons.includes('Скопировать название') &&
      m05.text.includes('Ссылка на платформу не передана') && !m05.text.includes('Следующий шаг') &&
      (await page.getByText('У материалов в этой подборке нет ссылок на платформу.', { exact: true }).count()) === 0);
    check('E3', `P02: пометки истории видны (${width})`, list.some((c) => c.text.includes('Вы уже открывали')));
    const external = list.flatMap((c) => c.links);
    check('E3', `Внешние ссылки с rel noopener noreferrer (${width})`, external.every((l) => l.rel.includes('noopener') && l.rel.includes('noreferrer')));
    await shot(page, `p02${tag}`);

    // E4: сравнение
    await page.getByRole('checkbox', { name: 'Сравнить с подбором по теме' }).check();
    await submit(page, '/api/compare');
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
    const baselineP02 = await comparisonTitles(page, width, 'Подбор по теме');
    const personalP02 = await comparisonTitles(page, width, 'Персональный подбор');
    await shot(page, `compare-p02${tag}`);
    await chooseProfile(page, 'P01');
    await submit(page, '/api/compare');
    const baselineP01 = await comparisonTitles(page, width, 'Подбор по теме');
    const personalP01 = await comparisonTitles(page, width, 'Персональный подбор');
    check('E4', `Сравнение P01 и P02: подбор по теме совпадает (${width})`, baselineP01.length === 5 && JSON.stringify(baselineP01) === JSON.stringify(baselineP02));
    check('E4', `Сравнение P01 и P02: персональные подборки различаются (${width})`,
      personalP01[0] === T.M01 && personalP02[0] === T.M02 &&
      JSON.stringify(personalP01) === JSON.stringify(singleP01) && JSON.stringify(personalP02) === JSON.stringify(singleP02));

    // E4: задача без темы. Подбор по теме показывает своё сообщение и стартовую подборку, позиции не сравниваются
    await page.getByRole('button', { name: 'Сбросить', exact: true }).click();
    await page.getByLabel('Что вы хотите сделать?').fill('Какую CRM выбрать');
    await page.getByRole('checkbox', { name: 'Сравнить с подбором по теме' }).check();
    await submit(page, '/api/compare');
    // На узком экране сначала открыта вкладка персонального подбора
    const personalCol = compareColumn(page, 'Персональный подбор');
    const personalTitles = (await personalCol.isVisible()) ? (await cards(page, personalCol)).map((c) => c.title) : [];
    check('E4', `Без темы: персональный подбор показывает S02 и S03 (${width})`, JSON.stringify([...personalTitles].sort()) === JSON.stringify([T.S02, T.S03].sort()), personalTitles.join(' / '));
    if (width < 800) await page.getByRole('tablist', { name: 'Метод подбора' }).getByRole('tab', { name: 'Подбор по теме' }).click();
    const baselineCol = compareColumn(page, 'Подбор по теме');
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
    await page.getByRole('button', { name: 'Сбросить', exact: true }).click();
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
    await afterPost(page, () => banner.getByText('Продвижение', { exact: true }).click());
    list = await cards(page);
    const marketingOnly = list.length > 0 && list.every((c) => !c.title.includes('продаж') && !c.title.includes('скрипт'));
    check('E6', `После выбора «Продвижение» выдача по одной теме, форма сохранена (${width})`, marketingOnly && (await page.getByLabel('Что вы хотите сделать?').inputValue()) === 'Хочу больше клиентов');

    // E7: P04
    await chooseProfile(page, 'P04');
    await submit(page);
    const gap = await page.getByRole('heading', { name: /материалов пока нет/ }).count();
    check('E7', `P04: сообщение о пробеле, темы и стартовая подборка (${width})`, gap > 0 && (await page.getByRole('radio').count()) >= 3 && (await cards(page)).length >= 3);
    await shot(page, `p04${tag}`);
    const starterList = page.getByRole('region', { name: 'Стартовая подборка' });
    const beforeExpand = await starterList.getByText('Показано 3 из 5 материалов', { exact: true }).isVisible();
    await starterList.getByRole('button', { name: 'Показать все 5' }).click();
    await starterList.getByText('Показано 5 из 5 материалов', { exact: true }).waitFor();
    check('E7', `P04: счётчик стартовой подборки обновляется при раскрытии (${width})`,
      beforeExpand && (await cards(page, starterList)).length === 5);

    // E7: P07 — узкий запрос, переход от стартовой подборки к выбранной теме.
    await chooseProfile(page, 'P07');
    const narrowTask = await page.getByLabel('Что вы хотите сделать?').inputValue();
    const narrow = await submit(page);
    const narrowHeading = page.getByRole('heading', { name: 'По этому запросу подходящих материалов не нашлось' });
    const starterRegion = page.getByRole('region', { name: 'Стартовая подборка' });
    const starter = await cards(page, starterRegion);
    check('E7', `P07: после сообщения показана только стартовая подборка (${width})`,
      (await narrow.json()).status === 'none' && (await narrowHeading.isVisible()) &&
      starter.length > 0 && starter.length === (await cards(page)).length);
    await shot(page, `p07${tag}`);
    const narrowTopics = page.getByRole('group', { name: 'Тема', exact: true });
    const narrowed = await afterPost(page, () => narrowTopics.getByText('Продажи', { exact: true }).click());
    const narrowedBody = await narrowed.json();
    check('E7', `P07: выбор «Продажи» возвращает подборку по теме (${width})`,
      narrowed.request().postDataJSON().topic === 'sales' && narrowedBody.status === 'strong' &&
      narrowedBody.items.length > 0 && narrowedBody.items.every((item) => item.topics.includes('sales')) &&
      (await cards(page)).length === narrowedBody.items.length && !(await starterRegion.isVisible()) &&
      (await page.getByLabel('Что вы хотите сделать?').inputValue()) === narrowTask);

    // E8: сбой API и повтор без повторного ввода
    await chooseProfile(page, 'P01');
    await page.route('**/api/recommend', (route) => route.abort('failed'));
    await page.getByRole('button', { name: 'Подобрать материалы' }).click();
    const alert = page.getByRole('alert');
    await alert.waitFor({ timeout: 5000 }).catch(() => {});
    check('E8', `Сбой: баннер ошибки с ролью alert (${width})`, (await alert.count()) > 0 && (await alert.textContent()).includes('Не удалось получить подборку'));
    await shot(page, `error${tag}`);
    await page.unroute('**/api/recommend');
    const retry = await afterPost(page, () => page.getByRole('button', { name: 'Повторить' }).click());
    list = await cards(page);
    check('E8', `«Повторить» возвращает выдачу без повторного ввода (${width})`, list.length === 5 && list[0].title === T.M01 && retry.request().postDataJSON().task === taskBefore);

    // E13: повторный запрос не размонтирует выдачу и не сбрасывает прокрутку
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await page.route('**/api/recommend', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 400));
      await route.continue();
    });
    const refresh = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/recommend' && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Отметить изученным' }).last().click();
    await page.waitForTimeout(150);
    const during = await page.evaluate(() => ({
      cards: document.querySelectorAll('.card').length,
      busy: document.querySelectorAll('.card[aria-busy="true"]').length,
      skeletons: document.querySelectorAll('.skeleton').length,
      scrollY: Math.round(window.scrollY),
    }));
    await refresh;
    await page.waitForTimeout(100);
    const after = await page.evaluate(() => ({ cards: document.querySelectorAll('.card').length, scrollY: Math.round(window.scrollY) }));
    check('E13', `Повторный запрос сохраняет карточки и прокрутку (${width})`,
      during.cards === 5 && during.busy === 5 && during.skeletons === 0 && during.scrollY > 0 &&
      after.cards === 5 && Math.abs(after.scrollY - during.scrollY) <= 100, JSON.stringify({ during, after }));

    // E13: до скелетона экран не пустеет, скелетон ждёт 200 мс и повторяет габариты карточки
    const slow = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/recommend' && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Подобрать материалы', exact: true }).click();
    await page.waitForTimeout(100);
    const early = await page.evaluate(() => ({
      cards: document.querySelectorAll('.card').length,
      skeletons: document.querySelectorAll('.skeleton').length,
      fieldDisabled: document.querySelector('textarea')?.disabled,
      buttonText: document.querySelector('.actions .btn--primary')?.textContent?.trim(),
    }));
    await page.waitForTimeout(200);
    const skeleton = await page.evaluate(() => ({
      cards: document.querySelectorAll('.card').length,
      count: document.querySelectorAll('.skeleton').length,
      height: Math.round(document.querySelector('.skeleton')?.getBoundingClientRect().height ?? 0),
      fieldDisabled: document.querySelector('textarea')?.disabled,
      buttonText: document.querySelector('.actions .btn--primary')?.textContent?.trim(),
    }));
    await slow;
    await page.unroute('**/api/recommend');
    await page.getByRole('button', { name: 'Подобрать материалы', exact: true }).waitFor();
    const late = await page.evaluate(() => ({
      fieldDisabled: document.querySelector('textarea')?.disabled,
      buttonText: document.querySelector('.actions .btn--primary')?.textContent?.trim(),
    }));
    check('E13', `До скелетона остаётся прежняя выдача и активная форма, затем загрузка по габаритам карточки (${width})`,
      early.cards === 5 && early.skeletons === 0 && early.fieldDisabled === false &&
      early.buttonText === 'Подобрать материалы' && skeleton.cards === 0 &&
      skeleton.count === 5 && skeleton.height === (width === 390 ? 461 : 297) &&
      skeleton.fieldDisabled === true && skeleton.buttonText === 'Подбираем…' &&
      late.fieldDisabled === false && late.buttonText === 'Подобрать материалы',
      JSON.stringify({ early, skeleton, late }));

    check('E1', `Нет ошибок страницы в сценарии (${width})`, errors.filter((e) => !e.includes('net::ERR_FAILED') && !e.includes('Failed to fetch') && !e.includes('Failed to load resource')).length === 0, errors.join(' | ').slice(0, 300));
    await context.close();
  }

  for (const width of [390, 1120]) {
    let withCourse = false;
    const courseUrl = 'https://kurs.alfabank.ru/courses/test-course/';
    const { page, context } = await open(browser, width, async (page) => {
      await page.route('**/api/meta', async (route) => {
        const response = await route.fetch();
        const meta = await response.json();
        const source = width === 390 ? 'sqlite' : 'file';
        await route.fulfill({ response, json: { ...meta, catalog: { source, available: 1086 } } });
      });
      await page.route('**/api/recommend', async (route) => {
        const response = await route.fetch();
        const result = await response.json();
        const items = result.items.map((item, index) => ({
          ...item, url: null, link_allowed: false,
          topic_labels: index === 0 ? ['Налоги и законы', 'Продажи', 'Продвижение'] : item.topic_labels,
          ...(withCourse && index === 0 ? {
            format: 'course', format_label: 'Курс', access: 'paid', access_label: 'Платно', is_paid: true,
            duration_minutes: 60, lesson_count: 22, has_certificate: true, url: courseUrl, link_allowed: true,
            short_benefit: 'Прежняя краткая польза',
            course_details: {
              description: 'Практика планирования бюджета',
              audiences: ['Владельцам магазинов'],
              outcomes: ['Составить бюджет'],
            },
          } : {}),
        }));
        await route.fulfill({ response, json: { ...result, status: 'strong', clarification: null, items } });
      });
      await page.addInitScript(() => {
        Object.defineProperty(navigator, 'clipboard', {
          value: {
            writeText: async (title) => {
              if (window.failClipboard) throw new Error('Clipboard denied');
              window.copiedTitle = title;
            },
          },
        });
      });
    });
    await page.getByText(/Локальный каталог · 1\s086 доступных материалов/).waitFor();
    await page.getByLabel('Что вы хотите сделать?').fill('Хочу больше клиентов');
    await submit(page);
    const items = page.locator('article.card');
    const first = items.first();
    check('E2', `Сводка и одно пояснение для выдачи без ссылок (${width})`,
      (await page.getByRole('heading', { name: 'Показано 5 из 12 материалов' }).isVisible()) &&
      (await page.getByText('У материалов в этой подборке нет ссылок на платформу.', { exact: true }).count()) === 1 &&
      (await page.getByText('Ссылка на платформу не передана', { exact: true }).count()) === 0 &&
      (await page.getByText('Следующий шаг', { exact: true }).count()) === 0);
    check('E2', `Карточка показывает первые две темы в порядке API (${width})`,
      JSON.stringify(await first.locator('.badge--topic').allTextContents()) === JSON.stringify(['Налоги и законы', 'Продажи']));

    const copy = first.getByRole('button', { name: 'Скопировать название' });
    await copy.focus();
    await page.keyboard.press('Enter');
    await first.getByRole('status').getByText('Название скопировано').waitFor();
    const title = await first.getByRole('heading').textContent();
    check('E9', `Копирование с клавиатуры сохраняет фокус (${width})`,
      await copy.evaluate((button, title) => button === document.activeElement && window.copiedTitle === title, title));
    await page.evaluate(() => { window.failClipboard = true; });
    await page.keyboard.press('Enter');
    const manualCopy = first.getByRole('status').getByText('Выделите название материала и скопируйте его вручную.');
    await manualCopy.waitFor();
    check('E9', `При отказе буфера обмена видна ручная инструкция (${width})`, await manualCopy.isVisible());

    await afterPost(page, () => page.getByRole('button', { name: 'Показать ещё 5' }).click());
    await page.waitForFunction(() => document.activeElement === document.querySelectorAll('article.card')[5]);
    check('E9', `Раскрытие обновляет счётчик и переносит фокус к первой новой карточке (${width})`,
      (await page.getByRole('heading', { name: 'Показано 10 из 12 материалов' }).isVisible()) &&
      (await page.getByText('Уточните задачу, чтобы сузить подборку.', { exact: true }).isVisible()) &&
      (await items.count()) === 10);

    withCourse = true;
    await context.route(courseUrl, (route) => route.fulfill({
      contentType: 'text/html; charset=utf-8', body: '<title>Тестовая страница курса</title>',
    }));
    await submit(page);
    const link = first.getByRole('link', { name: 'Открыть страницу курса' });
    const disclosure = first.locator('summary').filter({ hasText: 'Подробнее о курсе' });
    const outcome = first.getByText('Составить бюджет', { exact: true });
    check('E9', `Описание видно сразу, а подробности свёрнуты (${width})`,
      await first.getByText('Практика планирования бюджета.', { exact: true }).isVisible() &&
      (await first.getByText('Прежняя краткая польза.', { exact: true }).count()) === 0 &&
      !(await outcome.isVisible()) && await link.isVisible());
    await disclosure.focus();
    await page.keyboard.press('Enter');
    await outcome.waitFor();
    check('E9', `Enter раскрывает сведения о курсе и сохраняет фокус (${width})`,
      await first.getByText('Владельцам магазинов', { exact: true }).isVisible() &&
      await disclosure.evaluate((el) => document.activeElement === el) && await link.isVisible());
    await page.keyboard.press('Space');
    await outcome.waitFor({ state: 'hidden' });
    check('E9', `Пробел сворачивает подробности, переход остаётся видимым (${width})`,
      await disclosure.evaluate((el) => document.activeElement === el) && await link.isVisible());
    check('E9', `Курс показывает длительность, число уроков и сертификат (${width})`,
      await first.getByText('60 мин', { exact: true }).isVisible() &&
      await first.getByText('22 урока', { exact: true }).isVisible() &&
      await first.getByText('Сертификат', { exact: true }).isVisible());
    check('E9', `В смешанной выдаче карточка без ссылки предлагает копирование (${width})`,
      await items.nth(1).getByRole('button', { name: 'Скопировать название' }).isVisible() &&
      await items.nth(1).getByText('Ссылка на платформу не передана').isVisible() &&
      await first.getByText('Следующий шаг', { exact: true }).isVisible() &&
      (await page.getByText('У материалов в этой подборке нет ссылок на платформу.').count()) === 0);
    await link.focus();
    const [tab] = await Promise.all([context.waitForEvent('page'), page.keyboard.press('Enter')]);
    await tab.waitForURL(courseUrl);
    await tab.waitForLoadState();
    const titleOfTab = await tab.title();
    check('E9', `Enter открывает ссылку курса в новой вкладке (${width})`,
      titleOfTab === 'Тестовая страница курса' && (await link.getAttribute('rel'))?.includes('noopener'),
      titleOfTab);
    await tab.close();
    await context.close();
  }

  for (const width of [390, 1120]) await checkTopicNavigation(browser, width);
  for (const width of [390, 1120]) await checkResultFilters(browser, width);

  // E5: все вводные материалы уже изучены, но тема остаётся доступной.
  {
    const { page, context } = await open(browser, 390);
    const catalog = JSON.parse(readFileSync(new URL('../../backend/data/catalog.synthetic.json', import.meta.url), 'utf8'));
    const history = catalog.materials.map(({ id }, index) => ({ material_id: id, event: 'complete', seq: index + 1 }));
    await page.route('**/api/recommend', (route) => {
      const body = route.request().postDataJSON();
      return route.continue({ postData: { ...body, history } });
    });
    const cold = await submit(page);
    const topicGroup = page.getByRole('group', { name: 'Тема', exact: true });
    check('E5', 'Без вводных карточек остаётся выбор темы', (await cold.json()).status === 'cold' &&
      (await topicGroup.isVisible()) && (await cards(page)).length === 0 &&
      (await page.getByRole('heading', { name: 'Стартовая подборка' }).count()) === 0);
    const chosen = await afterPost(page, () => topicGroup.getByText('Продвижение', { exact: true }).click());
    check('E5', 'Выбор темы возвращает карточки', (await chosen.json()).status === 'strong' &&
      chosen.request().postDataJSON().topic === 'marketing' && (await cards(page)).length > 0);
    await context.close();
  }

  // E9: узкий экран и клавиатура
  {
    const { page, context } = await open(browser, 390);
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
    await afterPost(page, () => page.keyboard.press('Enter'));
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
});

const failed = results.filter((r) => !r.ok);
console.log(`\nИтого: ${results.length - failed.length} из ${results.length} проверок пройдено`);
process.exit(failed.length ? 1 : 0);
