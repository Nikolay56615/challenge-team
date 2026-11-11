// Проверки WCAG 2.2 AA, которых нет в axe, и мелких улучшений интерфейса.
// W05: перенос без горизонтальной прокрутки на 320 px (1.4.10), демо-панель в своих границах, размер целей 24×24 px
// или зазор по исключению 2.5.8, фокус не перекрыт (2.4.11), интервалы текста (1.4.12), ошибка поля с aria-invalid
// и aria-describedby (3.3.1). W14: предзагрузка Onest и font-display: optional без сдвига макета, снижение движения,
// переносы в заголовках при lang="ru", color-scheme: light, печать подборки и сравнения с файлом PDF A4.
// W19 и ИИ-10: после ответа фокус на видимом элементе с кольцом (2.4.7).
// Состояния — те же, что в check_ui.mjs
// и check_a11y.mjs, плюс раскрытые уточнения, вторая вкладка сравнения, раскрытая стартовая подборка и ошибка поля.
// Проход по состояниям — walkStates из browser.mjs, общий с check_cvd.mjs.
// Экран ленты по профилю: перенос, размер целей, фокус при обходе Tab и интервалы текста проверяются
// на семи его состояниях, проход — walkFeedStates из browser.mjs.
//
// Запуск из корня проекта при работающем сервисе с собранным интерфейсом:
//   npm --prefix evaluation/e2e run check:wcag -- [адрес] [папка результатов]

import { join } from 'node:path';
import { readFileSync } from 'node:fs';
import {
  afterPost, base, chooseProfile, demoPanelOverflow, FEED_VIEW, outDir, runBrowserChecks, submit, TASK_LABEL, TASK_VIEW,
  walkFeedStates, walkStates,
} from './browser.mjs';

const results = [];
const check = (id, name, ok, note = '') => {
  results.push({ id, name, ok: Boolean(ok), note });
  console.log(`${ok ? 'PASS' : 'FAIL'} ${id} ${name}${note ? ' — ' + note : ''}`);
};

const WIDTHS = [320, 390, 1120];
// Интервалы текста по WCAG 2.2, 1.4.12: строка 1,5, абзац 2 размера шрифта, буквы 0,12 em, слова 0,16 em
const TEXT_SPACING_CSS = `* { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important; }
p { margin-bottom: 2em !important; }`;
const FONT_FILES = ['onest-cyrillic.woff2', 'onest-latin.woff2'];

/** Функции внутри страницы. Ставятся до скриптов приложения на каждой загрузке, CSP их не касается. */
function installProbes() {
  const short = (text) => (text || '').replace(/\s+/g, ' ').trim().slice(0, 40);
  const describe = (el) => {
    const cls = typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\s+/).join('.') : '';
    return `${el.tagName.toLowerCase()}${cls} «${short(el.textContent || el.getAttribute('aria-label'))}»`;
  };
  const visible = (el) => el.checkVisibility({ visibilityProperty: true, checkVisibilityCSS: true });
  const round = (x) => Math.round(x * 10) / 10;

  window.__wcag = {
    /** 1.4.10: ширина документа не больше окна */
    reflow() {
      const doc = document.documentElement;
      const wide = [];
      if (doc.scrollWidth > innerWidth + 1) {
        for (const el of document.body.querySelectorAll('*')) {
          if (el.closest('.visually-hidden') || !visible(el)) continue;
          const r = el.getBoundingClientRect();
          if (r.right > innerWidth + 1 && el.parentElement?.getBoundingClientRect().right <= innerWidth + 1) wide.push(describe(el));
        }
      }
      return { ok: doc.scrollWidth <= innerWidth + 1, scrollWidth: doc.scrollWidth, wide: wide.slice(0, 4) };
    },

    /** Справочно: сколько пикселей подписи выбранного профиля не помещается в нативный список демо-панели */
    profileLabel() {
      const select = Array.from(document.querySelectorAll('main select')).find((s) => s.labels[0]?.textContent.trim() === 'Тестовый профиль');
      if (!select) return null;
      const cs = getComputedStyle(select);
      const probe = document.createElement('span');
      probe.textContent = select.options[select.selectedIndex]?.text || '';
      Object.assign(probe.style, {
        position: 'absolute',
        visibility: 'hidden',
        whiteSpace: 'pre',
        font: cs.font,
        letterSpacing: cs.letterSpacing,
        wordSpacing: cs.wordSpacing,
      });
      document.body.append(probe);
      const need = probe.getBoundingClientRect().width;
      probe.remove();
      const room = select.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      return { text: probe.textContent, hidden: Math.max(0, Math.round(need - room)) };
    },

    /** 2.5.8: цель не меньше 24×24 или круг диаметром 24 px вокруг её центра не задевает другие цели */
    targets() {
      const selector = 'a[href], button, select, textarea, input:not([type=hidden]), summary, [role="tab"], [tabindex]:not([tabindex="-1"])';
      const list = [];
      const seen = new Set();
      for (const el of document.querySelectorAll(selector)) {
        // Скрытая радиокнопка и флажок принимают нажатие через подпись: цель — label
        const target = el.matches('input') && el.closest('label') ? el.closest('label') : el;
        if (seen.has(target)) continue;
        seen.add(target);
        if (target.closest('.visually-hidden') || !visible(target)) continue;
        const r = target.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const inline = target.matches('a') && getComputedStyle(target).display === 'inline';
        list.push({ el: target, r, inline, cx: r.left + r.width / 2, cy: r.top + r.height / 2 });
      }
      const small = list.filter((t) => !t.inline && (t.r.width < 24 || t.r.height < 24));
      const bad = [];
      for (const s of small) {
        const clash = list.find((o) => {
          if (o === s || o.el.contains(s.el) || s.el.contains(o.el)) return false;
          const dx = Math.max(o.r.left - s.cx, 0, s.cx - o.r.right);
          const dy = Math.max(o.r.top - s.cy, 0, s.cy - o.r.bottom);
          if (Math.hypot(dx, dy) < 12) return true;
          return small.includes(o) && Math.hypot(o.cx - s.cx, o.cy - s.cy) < 24;
        });
        if (clash) bad.push(`${describe(s.el)} ${round(s.r.width)}×${round(s.r.height)} рядом с ${describe(clash.el)}`);
      }
      // Справочно: наименьший зазор между соседними целями
      let gap = Infinity;
      for (let i = 0; i < list.length; i++) {
        for (let j = i + 1; j < list.length; j++) {
          const a = list[i];
          const b = list[j];
          if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
          const dx = Math.max(a.r.left - b.r.right, b.r.left - a.r.right, 0);
          const dy = Math.max(a.r.top - b.r.bottom, b.r.top - a.r.bottom, 0);
          gap = Math.min(gap, Math.max(dx, dy));
        }
      }
      const minW = Math.min(...list.map((t) => t.r.width));
      const minH = Math.min(...list.map((t) => t.r.height));
      return { total: list.length, small: small.length, bad, minW: round(minW), minH: round(minH), gap: round(gap) };
    },

    /** Липкие и фиксированные элементы — источник перекрытия фокуса */
    stuck() {
      return Array.from(document.body.querySelectorAll('*'))
        .filter((el) => ['fixed', 'sticky'].includes(getComputedStyle(el).position))
        .map(describe);
    },

    /** 2.4.11: видна ли хотя бы одна из пяти точек элемента с фокусом */
    focused() {
      const el = document.activeElement;
      if (!el || el === document.body || el === document.documentElement) return null;
      const repeat = this.seen.has(el);
      this.seen.add(el);
      const target = el.matches('input.visually-hidden') && el.closest('label') ? el.closest('label') : el;
      const r = target.getBoundingClientRect();
      // Точки берутся в той части элемента, что попадает в окно: у панели вкладки выше окна нижние точки лежат
      // за его краем, хотя сама панель видна. Элемент целиком вне окна точек не получает
      const left = Math.max(r.left, 0);
      const top = Math.max(r.top, 0);
      const width = Math.min(r.right, innerWidth) - left;
      const height = Math.min(r.bottom, innerHeight) - top;
      let points = 0;
      if (width > 0 && height > 0) {
        for (const [fx, fy] of [[0.5, 0.5], [0.15, 0.15], [0.85, 0.15], [0.15, 0.85], [0.85, 0.85]]) {
          const hit = document.elementFromPoint(left + width * fx, top + height * fy);
          if (hit && target.contains(hit)) points++;
        }
      }
      return { repeat, points, name: describe(target) };
    },
    seen: new Set(),

    /**
     * 2.4.7 и ИИ-10: элемент с фокусом виден, попадает в окно и показывает кольцо. У чипа фокус на скрытой
     * радиокнопке, а видимая цель и кольцо — её подпись.
     */
    focusTarget() {
      const el = document.activeElement;
      if (!el || el === document.body || el === document.documentElement) return { name: 'body', ok: false };
      const chip = el.matches('input.visually-hidden') ? el.closest('label') : null;
      const target = chip ?? el;
      const ring = chip ? el.nextElementSibling ?? chip : el;
      const r = target.getBoundingClientRect();
      const cs = getComputedStyle(ring);
      const hidden = (!chip && !!el.closest('.visually-hidden')) || r.width < 2 || r.height < 2 || !visible(target);
      const inView = r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth;
      const focusVisible = el.matches(':focus-visible');
      const ringOn = cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) >= 2;
      return { name: describe(target), hidden, inView, focusVisible, outline: `${cs.outlineStyle} ${cs.outlineWidth}`, ok: !hidden && inView && focusVisible && ringOn };
    },

    /** 1.4.12: при увеличенных интервалах текст не обрезан, не наложен и не выходит из своей плашки */
    textSpacing() {
      const BOX = '.btn, .chip__label, .badge, .tab, .tabs, .tag, .rank, .card, .panel, .banner, .route, .topbar';
      const range = document.createRange();
      const rects = [];
      const problems = [];
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let id = 0;
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        if (!node.data.trim()) continue;
        const el = node.parentElement;
        if (!el || el.closest('.visually-hidden, select, textarea') || !visible(el)) continue;
        range.selectNodeContents(node);
        const own = Array.from(range.getClientRects()).filter((r) => r.width > 0.5 && r.height > 0.5);
        if (!own.length) continue;
        const box = el.closest(BOX)?.getBoundingClientRect();
        for (const r of own) {
          rects.push({ id, r, el });
          if (r.left < -1 || r.right > innerWidth + 1) problems.push(`за краем окна: ${describe(el)}`);
          else if (box && (r.left < box.left - 1 || r.right > box.right + 1 || r.top < box.top - 1 || r.bottom > box.bottom + 1)) {
            problems.push(`выходит из плашки: ${describe(el)}`);
          }
        }
        id++;
      }
      for (const el of document.body.querySelectorAll('*')) {
        if (el.closest('.visually-hidden') || el.matches('select, textarea, option') || !(el.textContent || '').trim()) continue;
        const cs = getComputedStyle(el);
        const clipX = ['hidden', 'clip'].includes(cs.overflowX) && el.scrollWidth > el.clientWidth + 1;
        const clipY = ['hidden', 'clip'].includes(cs.overflowY) && el.scrollHeight > el.clientHeight + 1;
        if ((clipX || clipY) && visible(el)) problems.push(`обрезано: ${describe(el)} ${el.scrollWidth}×${el.scrollHeight} в ${el.clientWidth}×${el.clientHeight}`);
      }
      for (let i = 0; i < rects.length; i++) {
        for (let j = i + 1; j < rects.length; j++) {
          const a = rects[i];
          const b = rects[j];
          if (a.id === b.id) continue;
          const w = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left);
          const h = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top);
          if (w > 1 && h > 1) problems.push(`наложение: ${describe(a.el)} и ${describe(b.el)}`);
        }
      }
      return { texts: id, problems: [...new Set(problems)] };
    },
  };
}

async function open(browser, width, { path = TASK_VIEW, bypassCSP = false } = {}) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, locale: 'ru-RU', bypassCSP });
  await context.addInitScript(installProbes);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => {
    if (m.type() === 'error' || m.type() === 'warning') errors.push(m.text());
  });
  await page.goto(base + path);
  return { page, context, errors };
}

const probe = (page, name, arg) => page.evaluate(([n, a]) => window.__wcag[n](a), [name, arg]);
const settle = (page) => page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));

/** 1.4.10: страница в текущем состоянии не прокручивается по горизонтали */
async function reflowCheck(page, state, width) {
  const reflow = await probe(page, 'reflow');
  check('W05', `Без горизонтальной прокрутки: ${state} (${width})`, reflow.ok,
    reflow.ok ? '' : `ширина документа ${reflow.scrollWidth}; ${reflow.wide.join('; ')}`);
}

/** 2.5.8: цели нажатия в текущем состоянии */
async function targetsCheck(page, state, width) {
  const targets = await probe(page, 'targets');
  check('W05', `Цели 24×24 px или зазор по 2.5.8: ${state} (${width})`, targets.bad.length === 0,
    `целей ${targets.total}, наименьшие ширина и высота ${targets.minW} и ${targets.minH} px, меньше 24 px — ${targets.small}, наименьший зазор ${targets.gap} px` +
      (targets.bad.length ? '; ' + targets.bad.slice(0, 3).join('; ') : ''));
}

/** 2.4.11: при обходе клавишей Tab ни один элемент с фокусом не перекрыт */
async function focusNotObscured(page, state, width) {
  await page.evaluate(() => {
    window.__wcag.seen = new Set();
    window.scrollTo(0, 0);
  });
  // Щелчок по верхней строке снимает фокус и переносит точку начала обхода Tab в начало страницы
  await page.mouse.click(2, 2);
  const hidden = [];
  let count = 0;
  let outside = 0;
  for (let i = 0; i < 250; i++) {
    await page.keyboard.press('Tab');
    const info = await probe(page, 'focused');
    // Фокус ушёл из документа: следующий Tab вернёт его в начало, второй выход подряд — конец обхода
    if (!info) {
      if (++outside > 1) break;
      continue;
    }
    outside = 0;
    if (info.repeat) break;
    count++;
    if (info.points === 0) hidden.push(info.name);
  }
  const stuck = await probe(page, 'stuck');
  check('W05', `Фокус не перекрыт при обходе Tab: ${state} (${width})`, count > 0 && hidden.length === 0 && stuck.length === 0,
    `элементов ${count}, скрытых ${hidden.length}, липких и фиксированных ${stuck.length}` +
      (hidden.length || stuck.length ? '; ' + [...hidden, ...stuck].slice(0, 3).join('; ') : ''));
}

/** 1.4.12: при увеличенных интервалах текст не обрезан, не наложен и страница не шире окна */
async function textSpacingCheck(page, state, width, extra = '') {
  await settle(page);
  const spacing = await probe(page, 'textSpacing');
  const reflow = await probe(page, 'reflow');
  check('W05', `Интервалы текста 1.4.12: нет обрезки и наложений: ${state} (${width})`,
    spacing.problems.length === 0 && reflow.ok,
    [`текстов ${spacing.texts}${extra}`, ...spacing.problems.slice(0, 3), reflow.ok ? '' : `ширина документа ${reflow.scrollWidth}`].filter(Boolean).join('; '));
}

// Chromium на Linux предупреждает об этой директиве. В заголовке она нужна браузерам с поддержкой Web Bluetooth.
const consoleNoise = (text) => text.includes('net::ERR_FAILED') || text.includes('Failed to load resource') || text.includes('Failed to fetch')
  || text === "Error with Permissions-Policy header: Unrecognized feature: 'bluetooth'.";

/** Состояние ошибки поля: связи для вспомогательных технологий и фокус */
async function fieldErrorChecks(page, width) {
  const field = page.getByLabel(TASK_LABEL);
  const info = await field.evaluate((el) => {
    const ids = (el.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
    const described = ids.map((id) => document.getElementById(id)).filter(Boolean);
    const error = described.find((d) => d.classList.contains('field__error'));
    return {
      invalid: el.getAttribute('aria-invalid'),
      ids,
      errorText: error ? error.textContent.trim() : null,
      errorVisible: error ? error.checkVisibility() : false,
      focused: document.activeElement === el,
      allExist: described.length === ids.length,
    };
  });
  check('W05', `Ошибка поля: aria-invalid="true", aria-describedby ведёт к видимому тексту ошибки (${width})`,
    info.invalid === 'true' && info.allExist && info.errorVisible && info.errorText === 'Запрос длиннее 300 символов',
    `aria-describedby="${info.ids.join(' ')}", текст «${info.errorText}»`);
  check('W05', `Ошибка поля: фокус на поле задачи (${width})`, info.focused);
  await field.press('End');
  await field.press('Backspace');
  const cleared = await field.evaluate((el) => ({
    invalid: el.getAttribute('aria-invalid'),
    errors: document.querySelectorAll('.field__error').length,
    describedBy: el.getAttribute('aria-describedby') || '',
  }));
  check('W05', `Ошибка поля: правка задачи снимает aria-invalid и текст ошибки (${width})`,
    cleared.invalid === null && cleared.errors === 0 && !cleared.describedBy.includes('error'), JSON.stringify(cleared));
}

await runBrowserChecks('wcag-results.json', results, async (browser) => {
  // ---------- W05: перенос, демо-панель, размер целей по всем состояниям ----------
  for (const width of WIDTHS) {
    const { page, context, errors } = await open(browser, width);
    await walkStates(page, width, async (state) => {
      await reflowCheck(page, state, width);
      const demo = await demoPanelOverflow(page);
      const label = await probe(page, 'profileLabel');
      const clipped = label?.hidden ? `подпись «${label.text}» в списке обрезана многоточием, не поместилось ${label.hidden} px` : '';
      check('W05', `Демо-панель не выходит за край панели и окна: ${state} (${width})`, demo !== null && demo.length === 0,
        [demo === null ? 'панель не найдена' : demo.slice(0, 3).join('; '), clipped].filter(Boolean).join('; '));
      await targetsCheck(page, state, width);
      if (state === 'ошибка поля задачи') await fieldErrorChecks(page, width);
    });
    const pageErrors = errors.filter((e) => !consoleNoise(e));
    check('W05', `Нет ошибок и предупреждений консоли в проходе (${width})`, pageErrors.length === 0, pageErrors.join(' | ').slice(0, 300));
    await context.close();

    // Экран ленты по профилю: те же критерии по его состояниям
    const feed = await open(browser, width, { path: FEED_VIEW });
    await walkFeedStates(feed.page, width, async (state) => {
      await reflowCheck(feed.page, state, width);
      await targetsCheck(feed.page, state, width);
    });
    const feedErrors = feed.errors.filter((e) => !consoleNoise(e));
    check('W05', `Нет ошибок и предупреждений консоли в проходе ленты (${width})`, feedErrors.length === 0, feedErrors.join(' | ').slice(0, 300));
    await feed.context.close();

    const kit = await open(browser, width, { path: '/kit.html' });
    await kit.page.getByRole('heading', { name: 'UI-кит трека 1 · витрина' }).waitFor();
    const kitReflow = await probe(kit.page, 'reflow');
    check('W05', `Витрина kit.html без горизонтальной прокрутки страницы (${width})`, kitReflow.ok,
      kitReflow.ok ? '' : `ширина документа ${kitReflow.scrollWidth}; ${kitReflow.wide.join('; ')}`);
    const kitTargets = await probe(kit.page, 'targets');
    check('W05', `Витрина kit.html: цели 24×24 px или зазор по 2.5.8 (${width})`, kitTargets.bad.length === 0,
      `целей ${kitTargets.total}, наименьшие ширина и высота ${kitTargets.minW} и ${kitTargets.minH} px` + (kitTargets.bad.length ? '; ' + kitTargets.bad.slice(0, 3).join('; ') : ''));
    await kit.context.close();
  }

  // ---------- W05: фокус не перекрыт, 2.4.11 ----------
  for (const width of [320, 1120]) {
    const { page, context } = await open(browser, width);
    await walkStates(page, width, (state) => focusNotObscured(page, state, width));
    await context.close();

    const feed = await open(browser, width, { path: FEED_VIEW });
    await walkFeedStates(feed.page, width, (state) => focusNotObscured(feed.page, state, width));
    await feed.context.close();
  }

  // ---------- ИИ-10, 2.4.7: после ответа фокус на видимом элементе с кольцом ----------
  // Действия выполняются клавиатурой: так браузер показывает кольцо :focus-visible и после переноса фокуса скриптом
  for (const width of [390, 1120]) {
    const { page, context } = await open(browser, width);
    const byKeyboard = async (locator) => {
      await locator.focus();
      // Shift+Tab и Tab возвращают фокус на тот же элемент, но уже с клавиатуры
      await page.keyboard.press('Shift+Tab');
      await page.keyboard.press('Tab');
    };
    const formButton = page.getByRole('button', { name: 'Подобрать материалы', exact: true });
    const focusCheck = async (what, expected) => {
      await settle(page);
      const info = await probe(page, 'focusTarget');
      const matches = expected.test(info.name);
      check('W19', `ИИ-10: ${what} — фокус на видимом элементе с кольцом (${width})`, info.ok && matches,
        `${info.name}; скрыт ${info.hidden}, в окне ${info.inView}, :focus-visible ${info.focusVisible}, outline ${info.outline}`);
    };

    await chooseProfile(page, 'P01');
    await byKeyboard(formButton);
    await afterPost(page, () => page.keyboard.press('Enter'));
    await focusCheck('отправка формы, ответ strong', /^article\.card «/);

    const mark = page.locator('article.card').first().getByRole('button', { name: 'Отметить изученным' });
    await byKeyboard(mark);
    await afterPost(page, () => page.keyboard.press('Enter'));
    await focusCheck('«Отметить изученным»', /^article\.card «/);

    await chooseProfile(page, 'P05');
    await byKeyboard(formButton);
    await afterPost(page, () => page.keyboard.press('Enter'));
    await focusCheck('отправка формы, ответ weak', /^article\.card «/);
    // Фокус на карточке под баннером: вопрос уточнения не уходит за верхний край окна (docs/ui-kit.md, 4.1)
    const question = await page.evaluate(() => {
      const title = document.querySelector('.banner__title')?.getBoundingClientRect();
      const card = document.activeElement?.getBoundingClientRect();
      return { title: title ? Math.round(title.top) : null, card: card ? Math.round(card.top) : null, height: innerHeight };
    });
    check('W19', `ИИ-10: ответ weak — вопрос уточнения и карточка с фокусом оба в окне (${width})`,
      question.title !== null && question.title >= 0 && question.card !== null && question.card < question.height,
      `верх вопроса ${question.title} px, верх карточки ${question.card} px, высота окна ${question.height} px`);
    await byKeyboard(page.getByRole('button', { name: 'Оставить как есть' }));
    await page.keyboard.press('Enter');
    await focusCheck('«Оставить как есть»', /^article\.card «/);

    await byKeyboard(formButton);
    await afterPost(page, () => page.keyboard.press('Enter'));
    const topic = page.getByRole('status').filter({ hasText: 'Уточните тему' }).getByRole('radio', { name: 'Продвижение' });
    await topic.focus();
    // Стрелки в группе с activation="manual" только переносят фокус: вправо и обратно, затем Enter выбирает
    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('ArrowLeft');
    await afterPost(page, () => page.keyboard.press('Enter'));
    await focusCheck('тема из баннера уточнения', /^article\.card «/);

    await chooseProfile(page, 'P04');
    await byKeyboard(formButton);
    await afterPost(page, () => page.keyboard.press('Enter'));
    await focusCheck('пустая выдача', /^h2\.h2 «/);

    await chooseProfile(page, 'P02');
    await page.getByRole('checkbox', { name: 'Сравнить с подбором по теме' }).check();
    await byKeyboard(formButton);
    await afterPost(page, () => page.keyboard.press('Enter'), '/api/compare');
    await focusCheck('сравнение', /^h2\.h2 «Сравнение/);
    await page.getByRole('checkbox', { name: 'Сравнить с подбором по теме' }).uncheck();

    await page.route('**/api/recommend', (route) => route.abort('failed'));
    await byKeyboard(formButton);
    await page.keyboard.press('Enter');
    await page.getByRole('alert').waitFor({ timeout: 5000 });
    await focusCheck('ошибка запроса', /^button\.btn.* «Повторить»/);
    await page.unroute('**/api/recommend');
    await context.close();
  }

  // ---------- W05: интервалы текста, 1.4.12 ----------
  for (const width of [320, 1120]) {
    // Вставка стилей требует обхода CSP: приложение запрещает встроенные стили
    const { page, context } = await open(browser, width, { bypassCSP: true });
    await page.addStyleTag({ content: TEXT_SPACING_CSS });
    await walkStates(page, width, async (state) => {
      const label = await probe(page, 'profileLabel');
      await textSpacingCheck(page, state, width,
        label?.hidden ? `; подпись в нативном списке обрезана многоточием, не поместилось ${label.hidden} px` : '');
      if (state === 'P01: выдача и маршрут') await page.screenshot({ path: join(outDir, `text-spacing-p01-${width}.png`), fullPage: true });
    });
    await context.close();

    const feed = await open(browser, width, { path: FEED_VIEW, bypassCSP: true });
    await feed.page.addStyleTag({ content: TEXT_SPACING_CSS });
    await walkFeedStates(feed.page, width, (state) => textSpacingCheck(feed.page, state, width));
    await feed.context.close();
  }

  // ---------- W14: шрифт ----------
  for (const path of [TASK_VIEW, '/kit.html']) {
    const { page, context, errors } = await open(browser, 390, { path });
    await page.locator('h1').first().waitFor();
    const fonts = await page.evaluate(async (files) => {
      await document.fonts.ready;
      await new Promise((resolve) => setTimeout(resolve, 300));
      const preloads = Array.from(document.querySelectorAll('link[rel="preload"][as="font"]')).map((link) => ({
        file: link.getAttribute('href').split('/').pop(),
        type: link.getAttribute('type'),
        crossOrigin: link.crossOrigin,
      }));
      const fetched = performance.getEntriesByType('resource').filter((e) => e.name.includes('/fonts/'));
      const counts = Object.fromEntries(files.map((f) => [f, fetched.filter((e) => e.name.endsWith(f)).length]));
      const displays = [];
      for (const sheet of document.styleSheets) {
        for (const rule of sheet.cssRules) if (rule instanceof CSSFontFaceRule) displays.push(rule.style.getPropertyValue('font-display'));
      }
      let cls = 0;
      await new Promise((resolve) => {
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) if (!entry.hadRecentInput) cls += entry.value;
        }).observe({ type: 'layout-shift', buffered: true });
        setTimeout(resolve, 200);
      });
      return {
        preloads,
        counts,
        displays,
        cls,
        used: document.fonts.check('16px Onest', 'Подбор Onest'),
        family: getComputedStyle(document.body).fontFamily,
      };
    }, FONT_FILES);
    const preloadOk = FONT_FILES.every((file) => fonts.preloads.some((p) => p.file === file && p.type === 'font/woff2' && p.crossOrigin === 'anonymous'));
    check('W14', `Предзагрузка Onest: кириллица и латиница, as=font, crossorigin (${path})`, preloadOk && fonts.preloads.length === 2, JSON.stringify(fonts.preloads));
    check('W14', `Каждое предзагруженное подмножество скачано один раз (${path})`, FONT_FILES.every((f) => fonts.counts[f] === 1), JSON.stringify(fonts.counts));
    check('W14', `font-display: optional у всех начертаний Onest (${path})`, fonts.displays.length === 4 && fonts.displays.every((d) => d === 'optional'), fonts.displays.join(', '));
    check('W14', `Onest применён к тексту страницы (${path})`, fonts.used && fonts.family.startsWith('Onest'), fonts.family);
    check('W14', `Сдвиг макета при первой загрузке CLS ≤ 0,1 (${path})`, fonts.cls <= 0.1, `CLS ${fonts.cls.toFixed(4)}`);
    // Браузер предупреждает о неиспользованной предзагрузке через несколько секунд после загрузки
    await page.waitForTimeout(3500);
    const preloadWarnings = errors.filter((e) => e.includes('preload'));
    check('W14', `Нет предупреждений о неиспользованной предзагрузке (${path})`, preloadWarnings.length === 0, preloadWarnings.join(' | ').slice(0, 200));
    // Без встроенных стилей и скриптов страница работает под CSP сервиса; React style — это CSSOM, CSP его не ограничивает
    const csp = await page.evaluate(() => fetch(location.href).then((r) => r.headers.get('content-security-policy') || ''));
    const violations = errors.filter((e) => e.includes('Content Security Policy'));
    check('W14', `Нет нарушений CSP (${path})`, violations.length === 0, `style-src: ${(csp.match(/style-src [^;]*/) || ['нет'])[0]}` + (violations.length ? '; ' + violations.join(' | ').slice(0, 200) : ''));
    await context.close();
  }

  // ---------- W14: движение, переносы, цветовая схема ----------
  {
    const { page, context } = await open(browser, 390);
    await chooseProfile(page, 'P01');
    await submit(page);
    const durations = () => page.evaluate(() => {
      let max = 0;
      let moving = 0;
      for (const el of document.querySelectorAll('*')) {
        const cs = getComputedStyle(el);
        const values = [...cs.transitionDuration.split(','), ...cs.animationDuration.split(',')].map((v) => parseFloat(v) * (v.trim().endsWith('ms') ? 0.001 : 1));
        const longest = Math.max(...values);
        if (longest > 0) moving++;
        max = Math.max(max, longest);
      }
      return { max, moving };
    });
    const normal = await durations();
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const reduced = await durations();
    check('W14', 'prefers-reduced-motion: переходы и анимации не длиннее 0,01 мс', normal.max > 0.1 && reduced.max <= 0.00001 + 1e-9,
      `без настройки — до ${normal.max} с у ${normal.moving} элементов; с настройкой — до ${reduced.max * 1000} мс`);

    const headings = await page.evaluate(() => ({
      lang: document.documentElement.lang,
      values: Array.from(document.querySelectorAll('h1, h2, h3, .h1, .h2, .h3')).map((h) => getComputedStyle(h).hyphens),
    }));
    check('W14', 'Переносы: lang="ru" и hyphens: auto у всех заголовков', headings.lang === 'ru' && headings.values.length > 0 && headings.values.every((v) => v === 'auto'),
      `lang="${headings.lang}", заголовков ${headings.values.length}, значения ${[...new Set(headings.values)].join(', ')}`);

    // Дождаться смены схемы и завершения CSS-переходов. После подбора кнопка формы меняет вариант.
    const colors = () => page.evaluate(async () => {
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      const elements = Array.from(document.querySelectorAll('html, body, textarea, select, input[type=checkbox], .btn, .card, .panel'));
      await Promise.allSettled(elements.flatMap((el) => el.getAnimations()
        .filter((animation) => animation instanceof CSSTransition)
        .map((transition) => transition.finished)));
      return elements.map((el) => {
        const cs = getComputedStyle(el);
        return `${cs.colorScheme}|${cs.backgroundColor}|${cs.color}|${cs.borderTopColor}`;
      });
    });
    await page.emulateMedia({ colorScheme: 'light' });
    const light = await colors();
    await page.emulateMedia({ colorScheme: 'dark' });
    const dark = await colors();
    await page.emulateMedia({ colorScheme: 'light' });
    const meta = await page.evaluate(() => document.querySelector('meta[name="color-scheme"]')?.content);
    check('W14', 'color-scheme: light — в тёмном режиме системы поля и панели те же', light[0].startsWith('light|') && meta === 'light' && JSON.stringify(light) === JSON.stringify(dark),
      `элементов ${light.length}, meta «${meta}»`);
    await context.close();
  }

  // ---------- W14: печать ----------
  for (const width of [390, 1120]) {
    const { page, context } = await open(browser, width);
    await chooseProfile(page, 'P01');
    await submit(page);
    const screenCards = await page.locator('article.card').count();
    await page.emulateMedia({ media: 'print' });
    const printed = () => page.evaluate(() => {
      const shown = (el) => el.checkVisibility();
      const demo = Array.from(document.querySelectorAll('main h2')).find((h) => h.textContent.trim() === 'Демо-режим')?.closest('.panel');
      const controls = Array.from(document.querySelectorAll('button, select, textarea, input, fieldset')).filter(shown).map((el) => el.tagName.toLowerCase());
      const cards = Array.from(document.querySelectorAll('article.card')).filter(shown);
      const content = document.querySelector('.layout__content').getBoundingClientRect();
      return {
        demoHidden: !demo || !shown(demo),
        controls,
        cards: cards.length,
        breakInside: [...new Set(cards.map((c) => getComputedStyle(c).breakInside))],
        titles: cards.every((c) => (c.querySelector('h3')?.textContent || '').trim().length > 0),
        contentWidth: Math.round(content.width),
        overflow: document.documentElement.scrollWidth > innerWidth + 1,
        panels: Array.from(document.querySelectorAll('[role="tabpanel"]')).filter(shown).length,
        tablist: Array.from(document.querySelectorAll('[role="tablist"]')).filter(shown).length,
      };
    });
    const p01 = await printed();
    check('W14', `Печать: демо-панель и элементы управления скрыты (${width})`, p01.demoHidden && p01.controls.length === 0, p01.controls.join(', '));
    check('W14', `Печать: все карточки видны, не разрываются, колонка во всю ширину (${width})`,
      p01.cards === screenCards && p01.titles && p01.breakInside.join() === 'avoid' && !p01.overflow && p01.contentWidth > width * 0.8,
      `карточек ${p01.cards} из ${screenCards}, break-inside ${p01.breakInside.join()}, ширина колонки ${p01.contentWidth} px`);
    await page.screenshot({ path: join(outDir, `print-p01-${width}.png`), fullPage: true });
    await page.emulateMedia({ media: 'screen' });

    // Сравнение P02: обе колонки рядом, у каждой заголовок; вкладок, формы, демо-панели и скелетонов нет.
    // Узкий экран печатает разметку вкладок. Лист A4 шире окна телефона: перед печатью окно расширяется до
    // печатной области листа, 718 px, но не до 800 px, где разметка сменилась бы на две колонки без вкладок
    await chooseProfile(page, 'P02');
    await page.getByRole('checkbox', { name: 'Сравнить с подбором по теме' }).check();
    await submit(page, '/api/compare');
    const tabsOnScreen = await page.getByRole('tablist').count();
    if (width < 800) await page.setViewportSize({ width: 718, height: 900 });
    await page.emulateMedia({ media: 'print' });
    const compare = await printed();
    const layout = await page.evaluate(() => {
      const shown = (el) => el.checkVisibility();
      const cols = Array.from(document.querySelectorAll('.compare__col')).filter(shown);
      const rects = cols.map((c) => c.getBoundingClientRect());
      const heads = cols.map((c) => c.querySelector(':scope > .h3'));
      return {
        cols: cols.length,
        heads: heads.map((h) => (h?.textContent || '').trim()),
        headsShown: heads.every((h) => h && shown(h) && h.getBoundingClientRect().height > 0),
        sideBySide: rects.length === 2 && Math.abs(rects[0].top - rects[1].top) < 2 && rects[1].left >= rects[0].right,
        widths: rects.map((r) => Math.round(r.width)),
        skeletons: Array.from(document.querySelectorAll('.skeleton')).filter(shown).length,
      };
    });
    check('W14', `Печать сравнения: колонки рядом с заголовками, без вкладок, формы, демо-панели и скелетонов (${width})`,
      compare.demoHidden && compare.controls.length === 0 && compare.tablist === 0 && compare.cards === 10 && !compare.overflow &&
        layout.cols === 2 && layout.headsShown && layout.heads.join(' | ') === 'Подбор по теме | Персональный подбор' &&
        layout.sideBySide && layout.skeletons === 0,
      `вкладок на экране ${tabsOnScreen}, при печати ${compare.tablist}; колонок ${layout.cols} шириной ${layout.widths.join(' и ')} px, рядом ${layout.sideBySide}; ` +
        `заголовки «${layout.heads.join('», «')}»; карточек ${compare.cards}; элементов управления ${compare.controls.length}`);
    await page.screenshot({ path: join(outDir, `print-compare-${width}.png`), fullPage: true });
    // Файл PDF из того же состояния: лист A4 с полями 12 мм, как при печати из браузера
    const pdfPath = join(outDir, `print-compare-${width}.pdf`);
    await page.pdf({ path: pdfPath, format: 'A4', printBackground: true, margin: { top: '12mm', right: '12mm', bottom: '12mm', left: '12mm' } });
    const pdfPages = (readFileSync(pdfPath, 'latin1').match(/\/Type\s*\/Page(?![s\w])/g) || []).length;
    check('W14', `Печать сравнения в PDF A4: от 1 до 6 страниц (${width})`, pdfPages >= 1 && pdfPages <= 6, `страниц ${pdfPages}, файл ${pdfPath.split(/[\\/]/).pop()}`);
    await context.close();
  }

  // ---------- W14: снимки 320 px для просмотра ----------
  {
    const { page, context } = await open(browser, 320);
    const shots = new Map([
      ['P01: выдача и маршрут', 'p01'],
      ['сравнение P02: персональный подбор', 'compare-p02'],
      ['P07: узкий запрос', 'p07'],
      ['ошибка поля задачи', 'field-error'],
    ]);
    await walkStates(page, 320, async (state) => {
      const name = shots.get(state);
      if (name) await page.screenshot({ path: join(outDir, `${name}-320.png`), fullPage: true });
    });
    await context.close();
  }
});

const failed = results.filter((r) => !r.ok);
console.log(`\nИтого: ${results.length - failed.length} из ${results.length} проверок пройдено`);
process.exit(failed.length ? 1 : 0);
