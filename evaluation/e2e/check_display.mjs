// Автоматическая часть ручного чек-листа доступности (кандидат W19; evaluation/track1-a11y-manual.md):
// режим принудительных цветов — эмуляция высокой контрастности Windows — и увеличение 400 %.
//
// Принудительные цвета: все состояния walkStates на 390 и 1120 px в тёмной и светлой системной палитре,
// снимок каждого состояния в .results/forced-colors/. В каждом состоянии проверяется то, что держит смысл без
// авторских цветов: текст отличается от фона, выбранный чип и вкладка отличаются от невыбранных не только
// начертанием, у уточнения полоса слева, у ошибки строка «Ошибка» и сплошная рамка, ссылки-кнопки подчёркнуты,
// у пометок «Совпало» и бейджей видна граница, кольцо фокуса видно на основной кнопке.
// Увеличение 400 %: окно 1280×1024 при масштабе 400 % равно 320×256 CSS px; все состояния без горизонтальной
// прокрутки, кнопка «Подобрать материалы» достижима.
// Эмуляция Chromium не равна настоящему режиму Windows: системную палитру выбирает браузер, а не тема пользователя.
//
// Запуск из корня проекта при работающем сервисе с собранным интерфейсом:
//   npm --prefix evaluation/e2e run check:display -- [адрес] [папка результатов]

import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { base, outDir, runBrowserChecks, walkStates } from './browser.mjs';

const results = [];
const check = (id, name, ok, note = '') => {
  results.push({ id, name, ok: Boolean(ok), note });
  console.log(`${ok ? 'PASS' : 'FAIL'} ${id} ${name}${note ? ' — ' + note : ''}`);
};

const shotsDir = join(outDir, 'forced-colors');
mkdirSync(shotsDir, { recursive: true });
const slug = (text) => text.toLowerCase().replace(/[^a-zа-яё0-9]+/gi, '-').replace(/^-|-$/g, '');

/** Признаки состояния в режиме принудительных цветов; считаются на странице */
function inspect() {
  const shown = (el) => el.checkVisibility({ visibilityProperty: true, checkVisibilityCSS: true });
  const css = (el) => getComputedStyle(el);
  const px = (value) => parseFloat(value) || 0;
  const body = css(document.body);
  const problems = [];

  // Выбранный чип и вкладка: отличие от невыбранного не только начертанием
  const pairs = [];
  for (const group of document.querySelectorAll('.chip-group')) {
    const labels = Array.from(group.querySelectorAll('.chip')).filter(shown);
    const on = labels.find((l) => l.querySelector('input')?.checked);
    const off = labels.find((l) => !l.querySelector('input')?.checked);
    if (on && off) pairs.push(['чип', on.querySelector('.chip__label'), off.querySelector('.chip__label')]);
  }
  for (const list of document.querySelectorAll('[role="tablist"]')) {
    const on = list.querySelector('[aria-selected="true"]');
    const off = list.querySelector('[aria-selected="false"]');
    if (on && off && shown(on)) pairs.push(['вкладка', on, off]);
  }
  for (const [kind, on, off] of pairs) {
    const a = css(on);
    const b = css(off);
    const differs = a.backgroundColor !== b.backgroundColor || a.color !== b.color || a.borderTopColor !== b.borderTopColor || a.borderTopWidth !== b.borderTopWidth;
    if (!differs) problems.push(`${kind}: выбранный отличается только начертанием`);
  }

  // Баннеры: роль видна формой рамки и строкой «Ошибка»
  for (const banner of Array.from(document.querySelectorAll('.banner')).filter(shown)) {
    const s = css(banner);
    if (banner.classList.contains('banner--info')) {
      if (!(px(s.borderLeftWidth) >= 2 * px(s.borderTopWidth) && px(s.borderLeftWidth) >= 3)) problems.push('уточнение: нет полосы слева');
    } else {
      const kicker = banner.querySelector('.banner__kicker');
      if (!kicker || !shown(kicker) || kicker.textContent.trim() !== 'Ошибка') problems.push('ошибка: нет строки «Ошибка»');
      if (!['Top', 'Right', 'Bottom', 'Left'].every((side) => px(s[`border${side}Width`]) >= 2 && s[`border${side}Style`] === 'solid')) problems.push('ошибка: рамка не сплошная 2 px');
    }
  }

  // Ссылки-кнопки подчёркнуты
  const links = Array.from(document.querySelectorAll('.btn--link')).filter(shown);
  const bare = links.filter((l) => !css(l).textDecorationLine.includes('underline'));
  if (bare.length) problems.push(`ссылок-кнопок без подчёркивания: ${bare.length}`);

  // Граница бейджей и пометок «Совпало»: без фона она держится на рамке
  const boxed = Array.from(document.querySelectorAll('.badge, .match__chip')).filter(shown);
  const borderless = boxed.filter((el) => {
    const s = css(el);
    return !(px(s.borderTopWidth) >= 1 && s.borderTopStyle !== 'none' && s.borderTopColor !== 'rgba(0, 0, 0, 0)' && s.borderTopColor !== s.backgroundColor);
  });
  if (borderless.length) problems.push(`бейджей и пометок без видимой границы: ${borderless.length} из ${boxed.length}`);

  return {
    forced: matchMedia('(forced-colors: active)').matches,
    text: body.color,
    background: body.backgroundColor,
    textDiffers: body.color !== body.backgroundColor,
    pairs: pairs.length,
    banners: document.querySelectorAll('.banner').length,
    links: links.length,
    boxed: boxed.length,
    problems,
  };
}

await runBrowserChecks('display-results.json', results, async (browser) => {
  // ---------- принудительные цвета ----------
  for (const scheme of ['dark', 'light']) {
    for (const width of [390, 1120]) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, locale: 'ru-RU', forcedColors: 'active', colorScheme: scheme });
      const page = await context.newPage();
      await page.goto(base + '/');
      let index = 0;
      let failed = 0;
      const notes = [];
      // Снимок с fullPage и смена размера окна в Chromium сбрасывают эмуляцию принудительных цветов. Поэтому эмуляция
      // ставится заново в каждом состоянии, а страница снимается целиком так: окно вытягивается на высоту документа,
      // эмуляция включается снова, снимается окно, затем высота возвращается
      const emulate = () => page.emulateMedia({ forcedColors: 'active', colorScheme: scheme });
      const shoot = async (path) => {
        const height = await page.evaluate(() => document.documentElement.scrollHeight);
        await page.setViewportSize({ width, height });
        await emulate();
        await page.screenshot({ path });
        await page.setViewportSize({ width, height: 900 });
        await emulate();
      };
      await walkStates(page, width, async (state) => {
        index += 1;
        await emulate();
        const info = await page.evaluate(inspect);
        await shoot(join(shotsDir, `${scheme}-${width}-${String(index).padStart(2, '0')}-${slug(state)}.png`));
        // Фон страницы не авторский #fffafa: цвета действительно заменены системными, а не только совпал медиазапрос
        const ok = info.forced && info.background !== 'rgb(255, 250, 250)' && info.textDiffers && info.problems.length === 0;
        if (!ok) failed += 1;
        check('W19', `Принудительные цвета, ${scheme === 'dark' ? 'тёмная' : 'светлая'} палитра: ${state} (${width})`, ok,
          `текст ${info.text} на ${info.background}; пар выбора ${info.pairs}, баннеров ${info.banners}, ссылок-кнопок ${info.links}, бейджей и пометок ${info.boxed}` +
            (info.problems.length ? '; ' + info.problems.join('; ') : ''));
      });
      // Кольцо фокуса основной кнопки: в этом режиме outline получает системный цвет
      await emulate();
      const button = page.getByRole('button', { name: 'Подобрать материалы', exact: true });
      await button.focus();
      await page.keyboard.press('Shift+Tab');
      await page.keyboard.press('Tab');
      const ring = await button.evaluate((el) => {
        const s = getComputedStyle(el);
        return { visible: el.matches(':focus-visible'), style: s.outlineStyle, width: s.outlineWidth, color: s.outlineColor, background: getComputedStyle(document.body).backgroundColor };
      });
      check('W19', `Принудительные цвета, ${scheme === 'dark' ? 'тёмная' : 'светлая'} палитра: кольцо фокуса видно (${width})`,
        ring.visible && ring.style !== 'none' && parseFloat(ring.width) >= 2 && ring.color !== ring.background, JSON.stringify(ring));
      notes.push(`${index} состояний, с замечаниями ${failed}`);
      console.log(`  ${scheme} ${width}: ${notes.join('; ')}; снимки в ${shotsDir}`);
      await context.close();
    }
  }

  // ---------- увеличение 400 % ----------
  // 1280×1024 при 400 % — 320×256 CSS px. Высота окна меньше формы: проверяется и то, что кнопка достижима прокруткой
  {
    const context = await browser.newContext({ viewport: { width: 320, height: 256 }, locale: 'ru-RU' });
    const page = await context.newPage();
    await page.goto(base + '/');
    let states = 0;
    const wide = [];
    await walkStates(page, 320, async (state) => {
      states += 1;
      const doc = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: innerWidth }));
      if (doc.scroll > doc.inner + 1) wide.push(`${state}: ${doc.scroll} px`);
      if (states === 1) await page.screenshot({ path: join(outDir, 'zoom-400-initial.png'), fullPage: true });
    });
    check('W19', 'Увеличение 400 % (окно 320×256): ни одно состояние не прокручивается по горизонтали', states >= 15 && wide.length === 0,
      `состояний ${states}` + (wide.length ? `; шире окна: ${wide.slice(0, 3).join('; ')}` : ''));
    const button = page.getByRole('button', { name: 'Подобрать материалы', exact: true });
    await button.scrollIntoViewIfNeeded();
    const box = await button.boundingBox();
    check('W19', 'Увеличение 400 %: кнопка «Подобрать материалы» достижима прокруткой и целиком в окне', box && box.y >= 0 && box.y + box.height <= 256,
      box ? `кнопка ${Math.round(box.y)}–${Math.round(box.y + box.height)} px в окне высотой 256` : 'нет кнопки');
    await context.close();
  }
});

const failed = results.filter((r) => !r.ok);
console.log(`\nИтого: ${results.length - failed.length} из ${results.length} проверок пройдено`);
process.exit(failed.length ? 1 : 0);
