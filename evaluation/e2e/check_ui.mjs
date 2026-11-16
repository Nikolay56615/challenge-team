// Сквозная проверка интерфейса по docs/plan.md, 7.1 (E1–E9, E11). Проверки WCAG 2.2 по всем состояниям — в check_wcag.mjs.
// Кандидаты D09 — пометки «Совпало», «уровень» только при точном совпадении, длина строки 65ch, кнопка
// на первом экране 390×844; D10 — задержка скелетонов при замедленном ответе, прежнее содержимое до неё на месте.
// evaluation/track1-heuristic-review.md, ИИ-5 — сообщение у предела поля задачи и его снятие при смене значения.
// Тексты сравниваются без неразрывных пробелов типографа.
// Элементы ищутся по ролям и видимым подписям из docs/ui-kit.md и docs/plan.md, 5.7.
//
// Запуск из корня проекта при работающем сервисе с собранным интерфейсом:
//   npm --prefix evaluation/e2e run check:ui -- [адрес] [папка результатов]

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterPost, base, chooseProfile, demoPanelOverflow, outDir, runBrowserChecks, submit, TASK_LABEL, TASK_VIEW } from './browser.mjs';

const results = [];
const check = (id, name, ok, note = '') => {
  results.push({ id, name, ok: Boolean(ok), note });
  console.log(`${ok ? 'PASS' : 'FAIL'} ${id} ${name}${note ? ' — ' + note : ''}`);
};

async function open(browser, width) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, locale: 'ru-RU' });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text());
  });
  await page.goto(base + TASK_VIEW);
  await page.getByRole('button', { name: 'Подобрать материалы' }).waitFor();
  return { page, context, errors };
}

const shot = (page, name) => page.screenshot({ path: join(outDir, `${name}.png`), fullPage: true });

/** Текст карточек без неразрывных пробелов типографа (D09): сравнение идёт с обычными строками */
async function cards(page, scope) {
  const root = scope || page;
  return root.locator('article.card').evaluateAll((els) => {
    const plain = (text) => (text || '').replace(/\u00a0/g, ' ');
    return els.map((el) => ({
      label: el.getAttribute('aria-label'),
      title: plain(el.querySelector('h3')?.textContent).trim(),
      text: plain(el.textContent),
      links: Array.from(el.querySelectorAll('a')).map((a) => ({ text: plain(a.textContent).trim(), href: a.href, rel: a.rel })),
      buttons: Array.from(el.querySelectorAll('button')).map((b) => plain(b.textContent).trim()),
      matched: Array.from(el.querySelectorAll('.match__chip')).map((chip) => plain(chip.textContent).trim()),
    }));
  });
}

const compareColumn = (page, name) =>
  page.locator('.compare__col').filter({ has: page.getByRole('heading', { name, exact: true }) });

async function comparisonCards(page, width, name) {
  if (width < 800) await page.getByRole('tab', { name, exact: true }).click();
  const column = compareColumn(page, name);
  await column.waitFor();
  return cards(page, column);
}

async function comparisonTitles(page, width, name) {
  return (await comparisonCards(page, width, name)).map((card) => card.title);
}

/**
 * D09: ширина текстовых блоков карточки против 65ch их шрифта и наибольшее число знаков в одной строке.
 * Строки считаются по прямоугольникам символов: символы с одной вертикальной позицией — одна строка.
 */
function lineLength(page) {
  return page.evaluate(() => {
    const blocks = Array.from(document.querySelectorAll('article.card .kv__value, article.card .card__benefit'));
    const probe = document.createElement('span');
    // CSSOM, а не атрибут style: CSP приложения запрещает встроенные стили
    Object.assign(probe.style, { position: 'absolute', visibility: 'hidden', width: '65ch' });
    const over = [];
    let limit = 0;
    let widest = 0;
    let chars = 0;
    const range = document.createRange();
    for (const el of blocks) {
      el.append(probe);
      limit = probe.getBoundingClientRect().width;
      probe.remove();
      const width = el.getBoundingClientRect().width;
      widest = Math.max(widest, width);
      if (width > limit + 1) over.push(Math.round(width));
      const text = el.firstChild;
      if (text?.nodeType !== Node.TEXT_NODE) continue;
      const lines = new Map();
      for (let i = 0; i < text.data.length; i++) {
        range.setStart(text, i);
        range.setEnd(text, i + 1);
        const top = Math.round(range.getBoundingClientRect().top);
        lines.set(top, (lines.get(top) || 0) + 1);
      }
      chars = Math.max(chars, ...lines.values());
    }
    const card = document.querySelector('article.card')?.getBoundingClientRect().width || 0;
    return { blocks: blocks.length, over, limit: Math.round(limit), widest: Math.round(widest), chars, card: Math.round(card) };
  });
}

/** Строка состояния без неразрывных пробелов типографа */
const statusText = async (page) => ((await page.locator('p.status-line').textContent()) || '').replace(/\u00a0/g, ' ');

/** Опыт из формы и уровень материала при точном совпадении (docs/plan.md, 3.2) */
const LEVEL_OF = { none: 'intro', some: 'practical', experienced: 'advanced' };

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
    const p01 = await submit(page);
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
    check('E2', `P01: у карточек есть следующий шаг и действие (${width})`, list.every((c) => c.text.includes('Следующий шаг') && (c.links.length || c.buttons.length)));
    check('E2', `P01: маршрут на первую неделю (${width})`, (await page.getByText('Маршрут на первую неделю').count()) > 0);
    check('E2', `Карточки озвучиваются как «Позиция N» (${width})`, list.every((c, i) => c.label === `Позиция ${i + 1}`));
    // D09: пометки «Совпало» из contributions — у M01 тема, стадия, уровень и сфера, без усилия и без чисел
    check('D09', `P01: у M01 пометки «Совпало»: тема, стадия, уровень, сфера (${width})`,
      JSON.stringify(list[0].matched) === JSON.stringify(['тема', 'стадия', 'уровень', 'сфера']) &&
        list.every((c) => c.matched.length >= 1 && c.matched.length <= 4 && c.matched.every((m) => !/\d/.test(m))),
      list.map((c) => c.matched.join(' · ')).join(' / '));
    // D09: вклад уровня дают и точное совпадение, и смежный уровень (docs/plan.md, 3.2). «уровень» в «Совпало» — только
    // при точном: у смежного причина говорит «на шаг глубже» или «проще». В тройке P01 смежный — шаблон M03
    const p01Items = (await p01.json()).items;
    const target = LEVEL_OF[p01.request().postDataJSON().experience];
    const levelRows = p01Items
      .map((item, index) => ({ id: item.material_id, exact: item.level === target, level: item.contributions.level ?? 0, chip: list[index]?.matched.includes('уровень') }))
      .filter((row) => row.level > 0);
    check('D09', `P01: «уровень» только при точном совпадении уровня, у смежного M03 пометки нет (${width})`,
      levelRows.some((row) => row.id === 'M03' && !row.exact) && levelRows.every((row) => row.chip === row.exact),
      levelRows.map((row) => `${row.id} ${row.exact ? 'точный' : 'смежный'}: ${row.chip ? 'есть' : 'нет'}`).join(', '));
    const chips = await page.evaluate(() => {
      const lists = Array.from(document.querySelectorAll('article.card ul.match__list'));
      const named = lists.filter((ul) => document.getElementById(ul.getAttribute('aria-labelledby') || '')?.textContent === 'Совпало');
      const items = Array.from(document.querySelectorAll('.match__chip'));
      return {
        lists: lists.length,
        named: named.length,
        focusable: items.filter((li) => li.tabIndex >= 0 || li.querySelector('a, button, input')).length,
        maxHeight: Math.max(...items.map((li) => li.getBoundingClientRect().height)),
      };
    });
    check('D09', `Пометки — статичный список с подписью «Совпало», не цели нажатия (${width})`,
      chips.lists === list.length && chips.named === chips.lists && chips.focusable === 0 && chips.maxHeight < 44,
      `списков ${chips.lists} из ${list.length}, с подписью ${chips.named}, фокусируемых пометок ${chips.focusable}, высота до ${Math.round(chips.maxHeight)} px`);
    if (width >= 800) {
      const measure = await lineLength(page);
      check('D09', 'Текстовые блоки карточки не шире 65ch на 1120 px', measure.blocks > 0 && measure.over.length === 0,
        `блоков ${measure.blocks}, 65ch = ${measure.limit} px, самый широкий блок ${measure.widest} px, в строке до ${measure.chars} знаков` +
          (measure.over.length ? `, шире: ${measure.over.join(', ')}` : ''));
    }
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
    check('E3', `P02: у M05 нет перехода и есть примечание (${width})`, m05 && m05.links.length === 0 && m05.text.includes('Ссылка на платформу не передана'));
    check('E3', `P02: пометки истории видны (${width})`, list.some((c) => c.text.includes('Вы уже открывали')));
    const external = list.flatMap((c) => c.links);
    check('E3', `Внешние ссылки с rel noopener noreferrer (${width})`, external.every((l) => l.rel.includes('noopener') && l.rel.includes('noreferrer')));
    await shot(page, `p02${tag}`);

    // E4: сравнение
    await page.getByRole('checkbox', { name: 'Сравнить с подбором по теме' }).check();
    await submit(page, '/api/compare');
    if (width >= 800) {
      const both = (await page.getByRole('heading', { name: /Подбор по теме/ }).count()) > 0 && (await page.getByRole('heading', { name: /Персональный подбор/ }).count()) > 0;
      // Вкладки сравнения есть только на узком экране; вкладки входа стоят вне main и сюда не входят
      check('E4', 'Сравнение: две колонки на широком экране', both && (await page.locator('main').getByRole('tablist').count()) === 0);
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
    const baselineCardsP02 = await comparisonCards(page, width, 'Подбор по теме');
    const personalCardsP02 = await comparisonCards(page, width, 'Персональный подбор');
    const baselineP02 = baselineCardsP02.map((c) => c.title);
    const personalP02 = personalCardsP02.map((c) => c.title);
    // D09: подбор по теме ничего из профиля не учитывает — пометок «Совпало» у него нет
    check('D09', `Сравнение P02: «Совпало» только у персонального подбора (${width})`,
      baselineCardsP02.every((c) => c.matched.length === 0) && personalCardsP02.every((c) => c.matched.length > 0),
      `подбор по теме: ${baselineCardsP02.map((c) => c.matched.length).join(', ')}; персональный: ${personalCardsP02.map((c) => c.matched.join(' · ')).join(' / ')}`);
    await shot(page, `compare-p02${tag}`);
    const demoOverflow = await demoPanelOverflow(page);
    check('E4', `Демо-панель не выходит за край панели и окна (${width})`, demoOverflow?.length === 0, (demoOverflow ?? ['панель не найдена']).slice(0, 3).join('; '));
    await chooseProfile(page, 'P01');
    await submit(page, '/api/compare');
    const baselineP01 = await comparisonTitles(page, width, 'Подбор по теме');
    const personalP01 = await comparisonTitles(page, width, 'Персональный подбор');
    check('E4', `Сравнение P01 и P02: подбор по теме совпадает (${width})`, baselineP01.length === 5 && JSON.stringify(baselineP01) === JSON.stringify(baselineP02));
    check('E4', `Сравнение P01 и P02: персональные подборки различаются (${width})`,
      personalP01[0] === T.M01 && personalP02[0] === T.M02 &&
      JSON.stringify(personalP01) === JSON.stringify(singleP01) && JSON.stringify(personalP02) === JSON.stringify(singleP02));

    // E4: задача без темы. Подбор по теме показывает своё сообщение и стартовую подборку, позиции не сравниваются
    await page.getByRole('button', { name: 'Сбросить' }).click();
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
    const compareStatus = ((await page.locator('p.status-line').textContent()) || '').replace(/\u00a0/g, ' ');
    check('E4', `Без темы: строка состояния не называет изменённые позиции (${width})`, compareStatus === 'Сравнение готово. Подбор по теме не нашёл материалов по запросу.' && (await page.getByText('Изменились позиции').count()) === 0, compareStatus);
    check('E4', `Без темы: нет горизонтальной прокрутки (${width})`, !(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
    await shot(page, `compare-no-topic${tag}`);

    // Пустая задача и история профиля (P11): подбор по теме — стартовая подборка, персональный — подбор по истории.
    // Строка состояния не говорит «не нашёл материалов по запросу»: запроса нет
    await chooseProfile(page, 'P11');
    await submit(page, '/api/compare');
    const historyStatus = await statusText(page);
    const historyCards = await comparisonCards(page, width, 'Персональный подбор');
    check('E4', `P11 без задачи: строка состояния называет стартовую подборку и подбор по истории (${width})`,
      historyStatus === 'Сравнение готово. Без задачи подбор по теме показывает стартовую подборку, персональный — подбор по истории.' &&
        (await page.getByText('Изменились позиции').count()) === 0,
      historyStatus);
    check('D09', `P11: пометки «Совпало» подбора по истории (${width})`,
      historyCards.length > 0 && historyCards.every((c) => c.matched.length > 0 && c.matched.every((m) => ['продолжение', 'тема истории', 'похожие курсы'].includes(m))),
      historyCards.map((c) => c.matched.join(' · ')).join(' / '));
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

    check('E1', `Нет ошибок страницы в сценарии (${width})`, errors.filter((e) => !e.includes('net::ERR_FAILED') && !e.includes('Failed to fetch') && !e.includes('Failed to load resource')).length === 0, errors.join(' | ').slice(0, 300));
    await context.close();
  }

  // E5: все вводные материалы уже изучены, но тема остаётся доступной.
  {
    const { page, context } = await open(browser, 390);
    const appRoot = new URL('../../app/', import.meta.url);
    const repoRoot = new URL('../../', import.meta.url);
    const catalogPath = 'backend/data/catalog.synthetic.json';
    const workspaceCatalog = new URL(catalogPath, appRoot);
    const catalogUrl = existsSync(workspaceCatalog) ? workspaceCatalog : new URL(catalogPath, repoRoot);
    const catalog = JSON.parse(readFileSync(catalogUrl, 'utf8'));
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

  // D09: главное действие на первом экране телефона 390×844 без прокрутки
  {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: 'ru-RU' });
    const page = await context.newPage();
    await page.goto(base + TASK_VIEW);
    const button = page.getByRole('button', { name: 'Подобрать материалы', exact: true });
    await button.waitFor();
    const box = await button.boundingBox();
    const scrollY = await page.evaluate(() => window.scrollY);
    check('D09', 'Кнопка «Подобрать материалы» видна без прокрутки на 390×844', box && scrollY === 0 && box.y >= 0 && box.y + box.height <= 844,
      box ? `кнопка ${Math.round(box.y)}–${Math.round(box.y + box.height)} px при высоте окна 844, прокрутка ${scrollY}` : 'кнопка не найдена');
    await shot(page, 'first-screen-390x844');
    await context.close();
  }

  // D09: на 1440 px колонка выдачи достигает 760 px, и предел 65ch ограничивает строку причины
  {
    const { page, context } = await open(browser, 1440);
    await chooseProfile(page, 'P01');
    await submit(page);
    const measure = await lineLength(page);
    check('D09', 'Текстовые блоки карточки упираются в 65ch на 1440 px', measure.blocks > 0 && measure.over.length === 0 && measure.card - 40 > measure.limit && measure.widest >= measure.limit - 1,
      `блоков ${measure.blocks}, 65ch = ${measure.limit} px, карточка ${measure.card} px, самый широкий блок ${measure.widest} px, в строке до ${measure.chars} знаков`);
    await shot(page, 'p01-1440');
    await context.close();
  }

  // D10: строка состояния сразу, скелетоны — только если ответ дольше 400 мс. До скелетонов прежнее
  // содержимое остаётся на месте, неактивное (inert), и колонка не схлопывается
  {
    const { page, context } = await open(browser, 1120);
    await chooseProfile(page, 'P01');
    /** Журнал страницы при каждой мутации: высота колонки, карточки, вводная панель, скелетоны, обёртки Stale */
    const watch = () => page.evaluate(() => {
      const log = (window.__hold = []);
      const snap = () => {
        const stale = Array.from(document.querySelectorAll('.stale'));
        log.push({
          height: Math.round(document.querySelector('.layout__content').getBoundingClientRect().height),
          cards: document.querySelectorAll('article.card').length,
          intro: Boolean(document.querySelector('.intro__examples')),
          skeletons: document.querySelectorAll('.skeleton').length,
          stale: stale.length,
          inert: stale.every((el) => el.inert),
        });
      };
      snap();
      new MutationObserver(snap).observe(document.body, { childList: true, subtree: true, characterData: true });
    });
    const held = () => page.evaluate(() => window.__hold);
    await watch();
    // Отметки времени ставит страница: щелчок, первая строка «Подбираем…», первый скелетон и их число
    await page.evaluate(() => {
      const log = (window.__d10 = { click: null, status: null, skeleton: null, count: 0 });
      document.addEventListener('click', () => {
        Object.assign(log, { click: performance.now(), status: null, skeleton: null, count: 0 });
      }, true);
      new MutationObserver(() => {
        if (log.click === null) return;
        const now = performance.now() - log.click;
        if (log.status === null && (document.querySelector('p.status-line')?.textContent || '').startsWith('Подбираем')) log.status = now;
        const count = document.querySelectorAll('.skeleton').length;
        if (count > 0 && log.skeleton === null) log.skeleton = now;
        log.count = Math.max(log.count, count);
      }).observe(document.body, { childList: true, subtree: true, characterData: true });
    });
    const button = page.getByRole('button', { name: 'Подобрать материалы', exact: true });
    const started = Date.now();
    await submit(page);
    const fastMs = Date.now() - started;
    const fast = await page.evaluate(() => ({ ...window.__d10 }));
    check('D10', 'Быстрый ответ: строка состояния сразу, скелетоны не появились',
      fast.status !== null && fast.status < 100 && fast.skeleton === null && fast.count === 0,
      `ответ за ${fastMs} мс, строка через ${Math.round(fast.status ?? -1)} мс, скелетонов ${fast.count}`);
    const introLog = await held();
    check('D10', 'Быстрый ответ с начального экрана: вводная панель остаётся неактивной до карточек, колонка не пустеет',
      introLog.every((e) => e.intro || e.cards > 0) && introLog.some((e) => e.stale > 0 && e.intro) && introLog.every((e) => e.inert && e.skeletons === 0),
      `мутаций ${introLog.length}, с обёрткой Stale ${introLog.filter((e) => e.stale).length}, без панели и карточек ${introLog.filter((e) => !e.intro && !e.cards).length}`);

    // Повтор из выдачи с ответом за 250 мс: карточки на месте, высота колонки не падает
    const before = await page.evaluate(() => Math.round(document.querySelector('.layout__content').getBoundingClientRect().height));
    await page.route('**/api/recommend', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 250));
      await route.continue();
    });
    await watch();
    await afterPost(page, () => page.locator('article.card').first().getByRole('button', { name: 'Отметить изученным' }).click());
    await page.unroute('**/api/recommend');
    const repeatLog = await held();
    const lowest = Math.min(...repeatLog.map((e) => e.height));
    check('D10', 'Ответ за 250 мс на «Отметить изученным»: прежние карточки на месте и неактивны, колонка не схлопывается',
      repeatLog.every((e) => e.cards >= 5 && e.skeletons === 0 && e.inert) && repeatLog.some((e) => e.stale > 0) && lowest >= before - 1,
      `высота до запроса ${before} px, наименьшая ${lowest} px, наименьшее число карточек ${Math.min(...repeatLog.map((e) => e.cards))}`);
    // Замедленный ответ: сеть держит запрос 1500 мс
    await page.route('**/api/recommend', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      await route.continue();
    });
    const task = page.getByLabel(TASK_LABEL);
    const response = afterPost(page, async () => {
      await button.click();
      const early = await page.locator('.task-submit').evaluate((el) => ({
        busy: el.dataset.busy,
        blocked: el.getAttribute('aria-disabled'),
        text: el.textContent,
        fieldDisabled: document.querySelector('textarea')?.disabled,
      }));
      check('D10', 'До скелетонов форма сохраняет обычный вид, повторная отправка заблокирована',
        early.busy === 'false' && early.blocked === 'true' && early.text === 'Подобрать материалы' && early.fieldDisabled === false,
        JSON.stringify(early));
      const busy = page.getByRole('button', { name: 'Подбираем…', exact: true });
      await busy.waitFor();
      check('D10', 'После задержки поля блокируются вместе с появлением скелетонов',
        await task.isDisabled() && (await page.locator('.skeleton').count()) === 3);
    });
    await response;
    const slow = await page.evaluate(() => ({ ...window.__d10 }));
    await page.unroute('**/api/recommend');
    check('D10', 'Медленный ответ: строка состояния сразу, три скелетона через 300–600 мс',
      slow.status !== null && slow.status < 100 && slow.skeleton !== null && slow.skeleton >= 300 && slow.skeleton <= 600 && slow.count === 3,
      `строка через ${Math.round(slow.status ?? -1)} мс, скелетоны через ${Math.round(slow.skeleton ?? -1)} мс, скелетонов ${slow.count}`);
    check('D10', 'После ответа скелетонов нет, карточки на месте', (await page.locator('.skeleton').count()) === 0 && (await cards(page)).length === 5);
    await context.close();
  }

  // ИИ-5: поле задачи у предела сообщает о нём, а не обрезает вставку молча
  {
    const context = await browser.newContext({ viewport: { width: 390, height: 900 }, locale: 'ru-RU' });
    await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: new URL(base).origin });
    const page = await context.newPage();
    await page.goto(base + TASK_VIEW);
    const field = page.getByLabel('Что вы хотите сделать?');
    await field.waitFor();
    const state = () => field.evaluate((el) => {
      const ids = (el.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
      const hint = ids.map((id) => document.getElementById(id)).find((d) => d?.classList.contains('field__hint'));
      const live = el.closest('.field')?.querySelector('[role="status"]');
      const plain = (text) => (text || '').replace(/\u00a0/g, ' ').trim();
      return { length: el.value.length, hint: plain(hint?.textContent), live: plain(live?.textContent), invalid: el.getAttribute('aria-invalid') };
    });
    await field.fill('а'.repeat(290));
    await page.evaluate(() => navigator.clipboard.writeText('б'.repeat(30)));
    await field.press('End');
    await field.press('Control+V');
    const pasted = await state();
    const cutText = 'Вставка длиннее на 20 символов, её конец не поместился. Поле вмещает 300 символов.';
    check('ИИ-5', 'Вставка сверх предела: подсказка и живая область называют, сколько не поместилось',
      pasted.length === 300 && pasted.hint === cutText && pasted.live === cutText && pasted.invalid === null, JSON.stringify(pasted));
    await field.press('Backspace');
    const below = await state();
    check('ИИ-5', 'Ниже предела: снова счётчик, сообщение снято', below.length === 299 && below.hint === '299 из 300 символов' && below.live === '', JSON.stringify(below));
    await field.press('Space');
    const typed = await state();
    check('ИИ-5', 'Набор до предела: «Это предел. Поле вмещает 300 символов.»',
      typed.length === 300 && typed.hint === 'Это предел. Поле вмещает 300 символов.' && typed.live === typed.hint, JSON.stringify(typed));
    await field.press('Space');
    const over = await state();
    check('ИИ-5', 'Сверх предела при наборе поле не растёт, сообщение остаётся',
      over.length === 300 && over.hint === 'Это предел. Поле вмещает 300 символов.' && over.live === over.hint, JSON.stringify(over));

    // Сообщение о вставке относится к значению, которое она дала: «Сбросить» и выбор профиля его снимают
    const defaultHint = 'До 300 символов. Можно своими словами, без терминов';
    await field.fill('а'.repeat(290));
    await field.press('End');
    await field.press('Control+V');
    const again = await state();
    await page.getByRole('button', { name: 'Сбросить' }).click();
    const reset = await state();
    check('ИИ-5', '«Сбросить» после обрезанной вставки: подсказка по умолчанию, живая область пуста',
      again.hint === cutText && reset.length === 0 && reset.hint === defaultHint && reset.live === '', JSON.stringify({ again: again.hint, reset }));
    await field.fill('а'.repeat(290));
    await field.press('End');
    await field.press('Control+V');
    await chooseProfile(page, 'P01');
    const profile = await state();
    check('ИИ-5', 'Выбор профиля после обрезанной вставки: счётчик задачи профиля, сообщения нет',
      profile.length > 0 && profile.length < 300 && profile.hint === `${profile.length} из 300 символов` && profile.live === '', JSON.stringify(profile));
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

  // E9: 320 px (WCAG 2.2, 1.4.10) с самой длинной подписью профиля. Полный проход на 320 px — в check_wcag.mjs
  {
    const { page, context } = await open(browser, 320);
    await chooseProfile(page, 'P01');
    const demoOverflow = await demoPanelOverflow(page);
    check('E9', 'Демо-панель с профилем P01 не выходит за край на 320 px', demoOverflow?.length === 0, (demoOverflow ?? ['панель не найдена']).slice(0, 3).join('; '));
    await submit(page);
    check('E9', 'Нет горизонтальной прокрутки на 320 px', !(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
    await shot(page, 'p01-320');
    await context.close();
  }

  // Первый визит: готовые задачи и возврат к выбору, опциональная стадия и стартовая подборка.
  {
    const { page, context } = await open(browser, 390);
    const button = (name) => page.getByRole('button', { name });
    const heading = (name) => page.getByRole('heading', { name, exact: true });
    const focused = (target) => target.evaluate((element) => element === document.activeElement);
    const readRequest = (action) => Promise.all([
      page.waitForRequest((request) => request.method() === 'POST' && request.url().endsWith('/api/recommend')),
      afterPost(page, action),
    ]).then(([request]) => request.postDataJSON());

    await button('Выбрать готовую задачу').press('Enter');
    const choice = heading('Что хотите сделать?');
    const focusedFirst = await focused(choice);
    const images = await page.locator('.intro__example img').evaluateAll(async (items) => {
      await Promise.all(items.map((image) => image.decode()));
      return items.length === 3 && items.every((image) => image.naturalWidth > 0);
    });
    await button(/Запустить первую рекламу/).press('Enter');
    const stage = heading('На каком этапе ваш бизнес?');
    const focusedSecond = await focused(stage);
    await button('Назад').press('Enter');
    check('Первый визит', 'Фото открываются, фокус переходит между шагами и возвращается', images &&
      focusedFirst && focusedSecond && await focused(choice));

    await button(/Как делегировать задачи/).click();
    await button('Сбросить').click();
    check('Первый визит', 'Сброс возвращает список задач', await choice.isVisible());

    await button(/Какой налоговый режим выбрать/).click();
    const selected = await readRequest(() => button('Недавно начал бизнес').click());
    check('Первый визит', 'Готовая задача и выбранная стадия попали в запрос', selected.stage === 'start' &&
      selected.task === 'Какой налоговый режим выбрать' && (await cards(page)).length > 0);

    await button('Сбросить').click();
    await button(/Запустить первую рекламу/).click();
    const skipped = await readRequest(() => button('Пропустить уточнение').click());
    check('Первый визит', 'Уточнение можно пропустить', skipped.stage === null &&
      skipped.task === 'Запустить первую рекламу' && (await cards(page)).length > 0);

    await button('Сбросить').click();
    const starter = await readRequest(() => button('Показать материалы для начала').click());
    check('Первый визит', 'Подборку можно открыть без задачи', starter.task === '' &&
      starter.stage === null && (await cards(page)).length > 0);
    await chooseProfile(page, 'P02');
    await submit(page);
    const cover = page.locator('.card__cover').first();
    await cover.scrollIntoViewIfNeeded();
    await cover.evaluate((image) => image.decode());
    const hasBenefit = await cover.locator('xpath=ancestor::article').locator('.card__benefit').isVisible();
    check('Первый визит', 'Карточка курса показывает тематическое фото и краткое описание', hasBenefit);
    await context.close();
  }
});

const failed = results.filter((r) => !r.ok);
console.log(`\nИтого: ${results.length - failed.length} из ${results.length} проверок пройдено`);
process.exit(failed.length ? 1 : 0);
