// Различимость состояний при нарушениях цветового зрения.
//
// Модель. Матрицы Machado, Oliveira и Fernandes (2009) степени 1,0 для протанопии, дейтеранопии и тританопии
// применяются к линейному sRGB (color.mjs). Контраст — формула WCAG 2.2, различие цветов — CIEDE2000.
// Chromium эмулирует те же нарушения через CDP Emulation.setEmulatedVisionDeficiency; скрипт сверяет модель
// с пикселями снимков: расхождение больше ΔE00 2,5 — ошибка, иначе числа модели описывают то, что видно на снимках.
//
// Критерий. Состояния, которые нельзя путать, различаются не только оттенком:
//   1. Роль названа текстом: у баннера ошибки видимая строка «Ошибка» перед заголовком, у уточнения её нет.
//      «Видимая» проверяется дважды. По стилям: строка отображается, итоговая непрозрачность с предками 1,
//      цвет текста без прозрачности, прямоугольник строки внутри баннера и выше заголовка. По пикселям: на снимке
//      баннера при каждой симуляции самый контрастный пиксель в прямоугольнике строки отличается от заливки
//      не меньше чем в 3 раза. Стили ловят opacity и прозрачный цвет, снимок — ещё и обрезку через clip-path.
//   2. Форма: у уточнения полоса слева (левая граница не тоньше 3 px и вдвое толще верхней), у ошибки сплошная
//      рамка одной толщины не тоньше 2 px.
//   3. Светлота: рамки уточнения и ошибки отличаются по контрасту WCAG не меньше чем в 3 раза при обычном зрении
//      и при каждой симуляции. Порог взят из техники WCAG G183: различие 3:1 по светлоте сохраняется без оттенка.
//   4. Признаки, которые несут смысл, при каждой симуляции сохраняют пороги WCAG к соседним цветам: строка «Ошибка»
//      и текст ссылок — 4,5:1, полоса уточнения, рамка ошибки, рамка выбранного чипа и вкладки, рамка поля
//      с ошибкой — 3:1. Ссылки-кнопки окрашены в цвет основного текста и подчёркнуты: линия не тоньше 1 px,
//      её цвет непрозрачен и отличается от фона не меньше чем в 3 раза, сама ссылка не полупрозрачна.
//      Выбранный чип и вкладка отличаются ещё и начертанием. Поверхность уточнения нейтральная: C*ab не больше 3.
// Различие заливок баннеров выводится справочно: при протанопии и дейтеранопии оно около ΔE00 2,5 и опорой
// служить не может. Поэтому различие держат пункты 1–3.
//
// Ограничения. Симуляция дихроматии степени 1,0 — худший случай модели, а не восприятие конкретного человека;
// аномальную трихроматию, яркость экрана и размер элементов она не учитывает. Тританопия у Machado
// моделируется грубее, чем протанопия и дейтеранопия. Вопрос участникам «что означает этот цвет?» скрипт не заменяет.
// По пикселям проверяется только строка «Ошибка»; подчёркивание ссылок — по вычисленным стилям, поэтому его
// перекрытие другим элементом скрипт не заметит. Отрицательные варианты и их результаты — evaluation/track1-contrast.md.
//
// Состояния — walkStates из browser.mjs: 17 на 390 px и 15 на 1120 px. Снимки каждого состояния при каждой
// симуляции сохраняются в <папка результатов>/cvd/<нарушение>/ для ручного просмотра.
//
// Запуск из корня проекта при работающем сервисе с собранным интерфейсом:
//   npm --prefix evaluation/e2e run check:cvd -- [адрес] [папка результатов]
// Переменная CVD_VARIANT_CSS — путь к CSS, который добавляется поверх стилей приложения (с обходом CSP): так
// проверяют вариант палитры до правки кита и отрицательный случай. Без неё проверяется собранный интерфейс как есть.

import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { base, outDir, runBrowserChecks, walkStates, TASK_VIEW } from './browser.mjs';
import { chroma, contrast, deltaE, fmt, parseColor, readTokens, simulate, toHex, VISION, VISION_LABEL } from './color.mjs';
import { LITERALS, PAIRS } from './pairs.mjs';

const SIMULATED = VISION.filter((type) => type !== 'none');
const WIDTHS = [390, 1120];
const TEXT = 4.5;
const UI = 3;
const ROLE = 3;
const NEUTRAL_CHROMA = 3;
const STRIPE_MIN = 3;
const FRAME_MIN = 2;
const EMULATION_TOLERANCE = 2.5;
// Пиксели строки «Ошибка» на снимке: самый контрастный к заливке. Сглаживание краёв букв понижает контраст,
// поэтому порог — 3:1, а не 4,5:1: он говорит, что строка нарисована, а не что её удобно читать (это пункт 4)
const INK_MIN = 3;

const STATE_SLUG = {
  'начальный экран': 'initial',
  'уточнения раскрыты': 'refinements',
  'P01: выдача и маршрут': 'p01',
  'P02: платные карточки и пометки': 'p02',
  'сравнение P02: персональный подбор': 'compare-p02',
  'сравнение P02: подбор по теме': 'compare-p02-baseline',
  'сравнение без темы: персональный подбор': 'compare-crm',
  'сравнение без темы: подбор по теме': 'compare-crm-baseline',
  'пустая форма: стартовая подборка': 'cold',
  'стартовая подборка раскрыта': 'cold-expanded',
  'P05: уточнение темы': 'p05',
  'P05: выбрана тема': 'p05-topic',
  'P04: пробел и стартовая подборка': 'p04',
  'P07: узкий запрос': 'p07',
  'P07: выбраны «Продажи»': 'p07-sales',
  'ошибка запроса': 'error',
  'ошибка поля задачи': 'field-error',
};

const results = [];
const check = (id, name, ok, note = '') => {
  results.push({ id, name, ok: Boolean(ok), note });
  console.log(`${ok ? 'PASS' : 'FAIL'} ${id} ${name}${note ? ' — ' + note : ''}`);
};

/** Наименьший контраст пары при обычном зрении и всех симуляциях; прозрачный или неизвестный цвет — 0 */
const worst = (a, b) => {
  const [x, y] = [parseColor(a), parseColor(b)];
  return x && y ? Math.min(...VISION.map((type) => contrast(x, y, type))) : 0;
};
/** Контраст пары по каждому виду зрения: «6,04 / 8,06 / 4,67 / 4,94» */
const byVision = (a, b, f = contrast) => VISION.map((type) => fmt(f(parseColor(a), parseColor(b), type), f === contrast ? 2 : 1)).join(' / ');
const hex = (value) => {
  const rgb = parseColor(value);
  return rgb ? toHex(rgb) : `прозрачный (${value})`;
};

// ---------- 1. Пары токенов ----------
const { tokens, path: tokensPath } = readTokens();
const tokenColor = (name) => tokens[name] ?? LITERALS[name];
console.log(`Пары токенов: контраст WCAG — ${VISION.map((t) => VISION_LABEL[t]).join(' / ')}`);
const table = [];
for (const { kind, fg, bg, min, where, d03 } of PAIRS) {
  const a = tokenColor(fg);
  const b = tokenColor(bg);
  if (!a || !b) {
    check('D18', `${fg} / ${bg}: оба токена есть в tokens.css`, false);
    continue;
  }
  const ratios = Object.fromEntries(VISION.map((type) => [type, Number(contrast(a, b, type).toFixed(2))]));
  const deltas = Object.fromEntries(VISION.map((type) => [type, Number(deltaE(a, b, type).toFixed(1))]));
  const below = min === null ? [] : VISION.filter((type) => ratios[type] < min);
  table.push({ kind, fg, bg, min, where, d03, contrast: ratios, deltaE00: deltas, below });
  const values = VISION.map((type) => fmt(ratios[type])).join(' / ');
  const tail = `${min === null ? 'без порога' : `порог ${fmt(min)}`}; ΔE00 ${VISION.map((type) => fmt(deltas[type], 1)).join(' / ')} — ${where}`;
  if (d03 && min !== null) check('D03', `${fg} / ${bg} при симуляции`, below.length === 0, `${values}; ${tail}`);
  else console.log(`${min === null ? 'INFO' : below.length ? 'WARN' : 'INFO'} ${fg} / ${bg}: ${values}; ${tail}${below.length ? `; ниже порога: ${below.map((t) => VISION_LABEL[t]).join(', ')}` : ''}`);
}

// ---------- 2. Признаки состояний на экране ----------
/** Вычисленные стили баннеров, ссылок-кнопок, чипов, вкладок и поля с ошибкой в текущем состоянии */
function collectCues() {
  const visible = (el) => el.checkVisibility({ visibilityProperty: true, checkVisibilityCSS: true });
  const opaque = (c) => c && c !== 'transparent' && !/^rgba\(.*,\s*0\)$/.test(c);
  const behind = (el) => {
    for (let p = el.parentElement; p; p = p.parentElement) {
      const c = getComputedStyle(p).backgroundColor;
      if (opaque(c)) return c;
    }
    return 'rgb(255, 255, 255)';
  };
  const own = (el) => (opaque(getComputedStyle(el).backgroundColor) ? getComputedStyle(el).backgroundColor : behind(el));
  const side = (cs, s) => ({ color: cs[`border${s}Color`], width: parseFloat(cs[`border${s}Width`]) });
  /** Альфа-канал вычисленного цвета: rgb() — 1, rgba(…, a) — a */
  const alphaOf = (c) => {
    if (!c || c === 'transparent') return 0;
    const m = c.match(/^rgba\(.*[,/]\s*([\d.]+)\)$/);
    return m ? Number(m[1]) : 1;
  };
  /** Итоговая непрозрачность: произведение opacity элемента и всех предков */
  const opacityOf = (el) => {
    let value = 1;
    for (let p = el; p; p = p.parentElement) value *= Number(getComputedStyle(p).opacity);
    return value;
  };

  const banners = Array.from(document.querySelectorAll('.banner')).filter(visible).map((el, index) => {
    const cs = getComputedStyle(el);
    const kicker = el.querySelector('.banner__kicker');
    const title = el.querySelector('.banner__title');
    const ks = kicker ? getComputedStyle(kicker) : null;
    const br = el.getBoundingClientRect();
    const kr = kicker?.getBoundingClientRect();
    const tr = title?.getBoundingClientRect();
    return {
      index,
      tone: el.classList.contains('banner--error') ? 'error' : el.classList.contains('banner--info') ? 'info' : 'other',
      role: el.getAttribute('role'),
      fill: cs.backgroundColor,
      page: behind(el),
      textColor: cs.color,
      top: side(cs, 'Top'),
      right: side(cs, 'Right'),
      bottom: side(cs, 'Bottom'),
      left: side(cs, 'Left'),
      text: el.innerText,
      kicker: kicker
        ? {
            text: kicker.textContent.trim(),
            displayed:
              kicker.checkVisibility({ visibilityProperty: true, checkVisibilityCSS: true, opacityProperty: true }) &&
              kr.width > 0 &&
              kr.height > 0 &&
              !kicker.closest('.visually-hidden'),
            opacity: Number(opacityOf(kicker).toFixed(3)),
            colorAlpha: alphaOf(ks.color),
            inside: kr.left >= br.left - 0.5 && kr.right <= br.right + 0.5 && kr.top >= br.top - 0.5 && kr.bottom <= br.bottom + 0.5,
            above: Boolean(tr) && kr.bottom <= tr.top + 0.5,
            first: el.firstElementChild === kicker,
            beforeTitle: Boolean(title) && Boolean(kicker.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING),
            // Прямоугольник строки относительно рамки баннера: по нему берутся пиксели снимка
            box: { x: kr.left - br.left, y: kr.top - br.top, w: kr.width, h: kr.height },
            size: parseFloat(ks.fontSize),
            weight: Number(ks.fontWeight),
            color: ks.color,
          }
        : null,
    };
  });
  const links = Array.from(document.querySelectorAll('.btn--link')).filter(visible).map((el) => {
    const cs = getComputedStyle(el);
    return {
      text: el.textContent.trim(),
      color: cs.color,
      line: cs.textDecorationLine,
      lineColor: cs.textDecorationColor,
      lineAlpha: alphaOf(cs.textDecorationColor),
      thickness: cs.textDecorationThickness,
      opacity: Number(opacityOf(el).toFixed(3)),
      disabled: el.disabled || el.getAttribute('aria-disabled') === 'true',
      bg: own(el),
    };
  });
  const chips = Array.from(document.querySelectorAll('.chip-group'))
    .filter(visible)
    .map((group) =>
      Array.from(group.querySelectorAll('.chip')).map((chip) => {
        const label = chip.querySelector('.chip__label');
        const cs = getComputedStyle(label);
        return { checked: chip.querySelector('input').checked, border: cs.borderTopColor, weight: Number(cs.fontWeight), around: behind(label) };
      }),
    )
    .filter((group) => group.some((chip) => chip.checked));
  const tabs = Array.from(document.querySelectorAll('[role="tablist"]'))
    .filter(visible)
    .map((list) => ({
      track: getComputedStyle(list).backgroundColor,
      tabs: Array.from(list.querySelectorAll('[role="tab"]')).map((tab) => {
        const cs = getComputedStyle(tab);
        return { selected: tab.getAttribute('aria-selected') === 'true', border: cs.borderTopColor, weight: Number(cs.fontWeight) };
      }),
    }));
  const invalid = Array.from(document.querySelectorAll('[aria-invalid="true"]'))
    .filter(visible)
    .map((el) => ({ border: getComputedStyle(el).borderTopColor, around: behind(el) }));
  const normal = Array.from(document.querySelectorAll('select')).filter(visible)[0];
  return { banners, links, chips, tabs, invalid, normalBorder: normal ? getComputedStyle(normal).borderTopColor : null, body: getComputedStyle(document.body).color };
}

/** Почему строка «Ошибка» не считается видимой по стилям; пустой список — видима */
function kickerProblems(k) {
  if (!k) return ['строки роли нет'];
  const out = [];
  if (k.text !== 'Ошибка') out.push(`текст «${k.text}»`);
  if (k.opacity < 0.99) out.push(`непрозрачность ${fmt(k.opacity)}`);
  // У неотображаемой строки прямоугольник может быть нулевым: проверки положения ничего не добавят
  if (!k.displayed) return [...out, 'не отображается'];
  if (k.colorAlpha < 1) out.push(`альфа цвета текста ${fmt(k.colorAlpha)}`);
  if (!k.inside) out.push('выходит за баннер');
  if (!k.above) out.push('не выше заголовка');
  if (!k.first || !k.beforeTitle) out.push('в разметке не первая');
  return out;
}

/** Проверки признаков в одном состоянии. Стили от эмуляции не зависят, симуляция считается моделью для всех видов зрения */
function stateChecks(state, width, cues) {
  const problems = [];
  const notes = [];
  const need = (ok, text) => {
    if (!ok) problems.push(text);
  };

  for (const b of cues.banners) {
    if (b.tone === 'error') {
      const k = b.kicker;
      need(b.role === 'alert', `ошибка: role="${b.role}"`);
      const hidden = kickerProblems(k);
      need(hidden.length === 0, `ошибка: строка «Ошибка» перед заголовком не видна: ${hidden.join(', ')}`);
      need(k && k.size >= 12 && k.weight >= 600, `ошибка: строка роли ${k?.size} px, начертание ${k?.weight}`);
      const sides = [b.top, b.right, b.bottom, b.left];
      need(sides.every((s) => s.width >= FRAME_MIN && s.width === b.top.width && s.color === b.top.color), `ошибка: рамка не сплошная ${sides.map((s) => `${s.width}px ${hex(s.color)}`).join(', ')}`);
      const kick = k ? worst(k.color, b.fill) : 0;
      const frameFill = worst(b.top.color, b.fill);
      const framePage = worst(b.top.color, b.page);
      need(kick >= TEXT, `ошибка: строка «Ошибка» к заливке ${fmt(kick)}`);
      need(frameFill >= UI && framePage >= UI, `ошибка: рамка к заливке ${fmt(frameFill)}, к странице ${fmt(framePage)}`);
      notes.push(`ошибка: строка «Ошибка» ${k?.size} px ${k?.weight}, рамка ${b.top.width} px; минимум при симуляциях: строка ${fmt(kick)}, рамка/заливка ${fmt(frameFill)}, рамка/страница ${fmt(framePage)}`);
    } else if (b.tone === 'info') {
      need(b.role === 'status', `уточнение: role="${b.role}"`);
      need(!/ошибка/i.test(b.text), 'уточнение: в тексте есть «Ошибка»');
      const c = chroma(parseColor(b.fill));
      need(c <= NEUTRAL_CHROMA, `уточнение: поверхность ${hex(b.fill)} не нейтральная, C*ab ${fmt(c, 1)}`);
      need(b.left.width >= STRIPE_MIN && b.left.width >= 2 * b.top.width, `уточнение: полоса ${b.left.width} px при рамке ${b.top.width} px`);
      const text = worst(b.textColor, b.fill);
      const stripeFill = worst(b.left.color, b.fill);
      const stripePage = worst(b.left.color, b.page);
      need(text >= TEXT, `уточнение: текст к заливке ${fmt(text)}`);
      need(stripeFill >= UI && stripePage >= UI, `уточнение: полоса к заливке ${fmt(stripeFill)}, к странице ${fmt(stripePage)}`);
      notes.push(`уточнение: поверхность ${hex(b.fill)} C*ab ${fmt(c, 1)}, полоса ${b.left.width} px; минимум: текст ${fmt(text)}, полоса/заливка ${fmt(stripeFill)}, полоса/страница ${fmt(stripePage)}`);
    } else {
      problems.push('баннер без варианта info или error');
    }
  }

  /** Контраст линии подчёркивания к фону; прозрачная или полупрозрачная линия — 0 */
  const underline = (link) => (link.lineAlpha === 1 ? worst(link.lineColor, link.bg) : 0);
  for (const link of cues.links) {
    const ratio = worst(link.color, link.bg);
    const line = underline(link);
    need(link.line.includes('underline'), `ссылка «${link.text}» без подчёркивания`);
    need(line >= UI, `ссылка «${link.text}»: подчёркивание ${link.lineAlpha === 1 ? `${hex(link.lineColor)} к фону ${fmt(line)}` : `прозрачное, альфа ${fmt(link.lineAlpha)}`}`);
    need(!(parseFloat(link.thickness) < 1), `ссылка «${link.text}»: подчёркивание ${link.thickness}`);
    need(link.disabled || link.opacity >= 0.99, `ссылка «${link.text}»: непрозрачность ${fmt(link.opacity)}`);
    need(link.color === cues.body, `ссылка «${link.text}» ${hex(link.color)}, текст ${hex(cues.body)}`);
    need(ratio >= TEXT, `ссылка «${link.text}» к фону ${fmt(ratio)}`);
  }
  if (cues.links.length) {
    const names = [...new Set(cues.links.map((l) => `«${l.text}»`))].join(', ');
    notes.push(
      `ссылки ${cues.links.length} (${names}): цвет текста, минимум ${fmt(Math.min(...cues.links.map((l) => worst(l.color, l.bg))))}; ` +
        `подчёркивание ${[...new Set(cues.links.map((l) => l.thickness))].join(', ')}, к фону не меньше ${fmt(Math.min(...cues.links.map(underline)))}`,
    );
  }

  const chipRatios = [];
  for (const group of cues.chips) {
    const on = group.filter((chip) => chip.checked);
    const off = group.filter((chip) => !chip.checked);
    const ratio = Math.min(...on.map((chip) => worst(chip.border, chip.around)));
    chipRatios.push(ratio);
    need(on.every((chip) => chip.weight >= 600) && off.every((chip) => chip.weight < on[0].weight), `чипы: начертание ${on.map((c) => c.weight)} против ${off.map((c) => c.weight)}`);
    need(ratio >= UI, `выбранный чип: рамка к фону ${fmt(ratio)}`);
  }
  if (chipRatios.length) notes.push(`выбранные чипы в ${chipRatios.length} группах: начертание 600, рамка/фон не меньше ${fmt(Math.min(...chipRatios))}`);

  for (const list of cues.tabs) {
    const on = list.tabs.filter((tab) => tab.selected);
    const off = list.tabs.filter((tab) => !tab.selected);
    const ratio = Math.min(...on.map((tab) => worst(tab.border, list.track)));
    need(on.length === 1 && off.every((tab) => tab.weight < on[0].weight), 'вкладки: выбранная не отличается начертанием');
    need(ratio >= UI, `выбранная вкладка: рамка к треку ${fmt(ratio)}`);
    notes.push(`выбранная вкладка: рамка/трек ${fmt(ratio)}`);
  }

  for (const field of cues.invalid) {
    const ratio = worst(field.border, field.around);
    need(ratio >= UI, `поле с ошибкой: рамка к фону ${fmt(ratio)}`);
    const vsNormal = cues.normalBorder ? byVision(field.border, cues.normalBorder) : 'нет';
    notes.push(`поле с ошибкой: рамка/фон ${fmt(ratio)}; против обычной рамки ${vsNormal} (справочно)`);
  }

  check('D18', `${state} (${width})`, problems.length === 0, problems.length ? problems.join('; ') : notes.join('; ') || 'признаков цвета в состоянии нет');
}

// Метка порядка байтов в начале файла сломала бы первый селектор
const variantCss = process.env.CVD_VARIANT_CSS ? readFileSync(process.env.CVD_VARIANT_CSS, 'utf8').replace(/^\uFEFF/, '') : null;
if (variantCss) console.log(`Вариант стилей поверх приложения: ${process.env.CVD_VARIANT_CSS}`);

/** Страница приложения; вариант стилей, если задан, добавляется после загрузки и действует во всех состояниях */
async function openApp(browser, width) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, locale: 'ru-RU', bypassCSP: Boolean(variantCss) });
  const page = await context.newPage();
  await page.goto(base + TASK_VIEW);
  if (variantCss) await page.addStyleTag({ content: variantCss });
  return { context, page };
}

/** Указатель уходит в угол окна, переходы цвета завершаются: стиль и снимок — без случайного наведения */
async function rest(page) {
  await page.mouse.move(0, 0);
  await page.evaluate(() => Promise.all(document.getAnimations().map((a) => a.finished.catch(() => {}))));
}

const cvdDir = join(outDir, 'cvd');
const seen = {};
const samples = [];
const detail = [];

await runBrowserChecks('cvd-results.json', results, async (browser) => {
  rmSync(cvdDir, { recursive: true, force: true });
  const decoder = await browser.newPage();

  /** Цвета пикселей PNG в точках [x, y]: декодирует отдельная пустая страница без эмуляции */
  const pixels = (png, points) =>
    decoder.evaluate(
      async ({ b64, points: list }) => {
        const img = new Image();
        img.src = 'data:image/png;base64,' + b64;
        await img.decode();
        const canvas = document.createElement('canvas');
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;
        const ctx = canvas.getContext('2d', { willReadFrequently: true });
        ctx.drawImage(img, 0, 0);
        return list.map(([x, y]) => Array.from(ctx.getImageData(Math.round(x), Math.round(y), 1, 1).data.slice(0, 3)));
      },
      { b64: png.toString('base64'), points },
    );

  /** Самый тёмный и самый светлый пиксель PNG в прямоугольнике { x, y, w, h }; пустой прямоугольник — [] */
  const extremes = (png, rect) =>
    decoder.evaluate(
      async ({ b64, rect: r }) => {
        const img = new Image();
        img.src = 'data:image/png;base64,' + b64;
        await img.decode();
        const x = Math.max(0, Math.floor(r.x));
        const y = Math.max(0, Math.floor(r.y));
        const w = Math.min(img.naturalWidth, Math.ceil(r.x + r.w)) - x;
        const h = Math.min(img.naturalHeight, Math.ceil(r.y + r.h)) - y;
        if (w <= 0 || h <= 0) return [];
        const canvas = document.createElement('canvas');
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;
        const ctx = canvas.getContext('2d', { willReadFrequently: true });
        ctx.drawImage(img, 0, 0);
        const data = ctx.getImageData(x, y, w, h).data;
        const lin = (c) => (c / 255 <= 0.04045 ? c / 255 / 12.92 : ((c / 255 + 0.055) / 1.055) ** 2.4);
        let dark = null;
        let light = null;
        for (let i = 0; i < data.length; i += 4) {
          const rgb = [data[i], data[i + 1], data[i + 2]];
          const l = 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2]);
          if (!dark || l < dark.l) dark = { l, rgb };
          if (!light || l > light.l) light = { l, rgb };
        }
        return [dark.rgb, light.rgb];
      },
      { b64: png.toString('base64'), rect },
    );

  /**
   * Снимок баннера под эмуляцией: заливка в поле над текстом и полоса или рамка слева на середине высоты.
   * У ошибки ещё и прямоугольник строки «Ошибка»: самый контрастный к заливке пиксель показывает, что строка нарисована
   */
  async function sampleBanner(page, banner, type, width, state) {
    const box = page.locator('.banner').filter({ visible: true }).nth(banner.index);
    const png = await box.screenshot();
    const size = await box.evaluate((el) => ({ w: el.offsetWidth, h: el.offsetHeight }));
    const fillPoint = [size.w - 30, banner.top.width + 6];
    const edgePoint = [Math.floor(banner.left.width / 2), Math.floor(size.h / 2)];
    const [fill, edge] = await pixels(png, [fillPoint, edgePoint]);
    const model = { fill: simulate(parseColor(banner.fill), type), edge: simulate(parseColor(banner.left.color), type) };
    let kicker;
    if (banner.tone === 'error') {
      const ink = banner.kicker?.box ? await extremes(png, banner.kicker.box) : [];
      const best = ink.map((rgb) => ({ rgb, ratio: contrast(rgb, fill) })).sort((p, q) => q.ratio - p.ratio)[0];
      kicker = best ? { pixel: toHex(best.rgb), contrast: Number(best.ratio.toFixed(2)) } : { pixel: null, contrast: 0 };
    }
    samples.push({
      width,
      type,
      state,
      tone: banner.tone,
      fill: { screen: toHex(fill), model: toHex(model.fill), deltaE00: Number(deltaE(fill, model.fill).toFixed(2)) },
      edge: { screen: toHex(edge), model: toHex(model.edge), deltaE00: Number(deltaE(edge, model.edge).toFixed(2)) },
      ...(kicker ? { kicker } : {}),
    });
  }

  for (const width of WIDTHS) {
    for (const type of SIMULATED) {
      const { context, page } = await openApp(browser, width);
      const cdp = await context.newCDPSession(page);
      await cdp.send('Emulation.setEmulatedVisionDeficiency', { type });
      const dir = join(cvdDir, type);
      mkdirSync(dir, { recursive: true });
      let index = 0;
      await walkStates(page, width, async (state) => {
        index++;
        const slug = STATE_SLUG[state] ?? `state-${index}`;
        await rest(page);
        await page.screenshot({ path: join(dir, `${width}-${String(index).padStart(2, '0')}-${slug}.png`), fullPage: true });
        const cues = await page.evaluate(collectCues);
        if (type === SIMULATED[0]) {
          stateChecks(state, width, cues);
          detail.push({ width, state, cues });
          for (const banner of cues.banners) (seen[`${width}-${banner.tone}`] ??= banner);
        }
        for (const banner of cues.banners) {
          if (state === 'P05: уточнение темы' || state === 'ошибка запроса') await sampleBanner(page, banner, type, width, state);
        }
      });
      console.log(`снимков ${index}: ${VISION_LABEL[type]}, ${width} px`);
      await context.close();
    }

    // Уточнение против ошибки на одной ширине
    const info = seen[`${width}-info`];
    const error = seen[`${width}-error`];
    if (!info || !error) {
      check('D03', `Уточнение и ошибка найдены на экране (${width})`, false, `уточнение ${Boolean(info)}, ошибка ${Boolean(error)}`);
      continue;
    }
    // Строка видна по стилям и нарисована на снимках при каждой симуляции
    const hidden = kickerProblems(error.kicker);
    const ink = samples.filter((s) => s.width === width && s.tone === 'error').map((s) => ({ type: s.type, ...s.kicker }));
    const inkMin = ink.length === SIMULATED.length ? Math.min(...ink.map((s) => s.contrast)) : 0;
    check('D03', `Роль названа текстом: строка «Ошибка» видна только у ошибки (${width})`,
      hidden.length === 0 && inkMin >= INK_MIN && !/ошибка/i.test(info.text),
      `ошибка: ${hidden.length ? `строка не видна по стилям: ${hidden.join(', ')}` : `«${error.kicker.text}» над заголовком, непрозрачность 1`}; ` +
        `пиксели строки к заливке на снимках: ${ink.length ? ink.map((s) => `${VISION_LABEL[s.type]} ${s.pixel ? fmt(s.contrast) : 'строки нет'}`).join(', ') : 'снимков нет'}, порог ${fmt(INK_MIN, 0)}; ` +
        `уточнение: ${info.kicker ? `«${info.kicker.text}»` : 'строки роли нет'}`);
    const infoBar = info.left.width >= STRIPE_MIN && info.left.width >= 2 * info.top.width;
    const errorFrame = [error.top, error.right, error.bottom, error.left].every((s) => s.width === error.top.width && s.width >= FRAME_MIN);
    check('D03', `Форма: полоса слева у уточнения, сплошная рамка у ошибки (${width})`, infoBar && errorFrame,
      `уточнение ${info.top.width}/${info.right.width}/${info.bottom.width}/${info.left.width} px, ошибка ${error.top.width}/${error.right.width}/${error.bottom.width}/${error.left.width} px`);
    const frames = worst(info.top.color, error.top.color);
    check('D03', `Светлота: рамки уточнения и ошибки различаются не меньше чем в ${fmt(ROLE, 0)} раза при каждой симуляции (${width})`, frames >= ROLE,
      `${hex(info.top.color)} против ${hex(error.top.color)}: ${byVision(info.top.color, error.top.color)}`);
    console.log(`INFO заливки ${hex(info.fill)} / ${hex(error.fill)}: контраст ${byVision(info.fill, error.fill)}; ΔE00 ${byVision(info.fill, error.fill, deltaE)} (${width})`);
    console.log(`INFO полоса и рамка ${hex(info.left.color)} / ${hex(error.left.color)}: контраст ${byVision(info.left.color, error.left.color)}; ΔE00 ${byVision(info.left.color, error.left.color, deltaE)} (${width})`);

    // Модель против эмуляции Chromium
    for (const type of SIMULATED) {
      const rows = samples.filter((s) => s.width === width && s.type === type);
      const max = Math.max(...rows.flatMap((s) => [s.fill.deltaE00, s.edge.deltaE00]));
      check('D18', `Модель совпадает с эмуляцией Chromium: ${VISION_LABEL[type]} (${width})`, rows.length >= 2 && max <= EMULATION_TOLERANCE,
        `${rows.map((s) => `${s.tone}: заливка ${s.fill.screen} против ${s.fill.model}, ${s.tone === 'info' ? 'полоса' : 'рамка'} ${s.edge.screen} против ${s.edge.model}`).join('; ')}; наибольшее ΔE00 ${fmt(max)}`);
    }
  }

  // Наведение и фокус ссылки-кнопки: состояние меняет не только цвет
  {
    const { context, page } = await openApp(browser, 1120);
    const reset = page.getByRole('button', { name: 'Сбросить' });
    await reset.waitFor();
    const style = () => reset.evaluate((el) => {
      const cs = getComputedStyle(el);
      return { color: cs.color, line: cs.textDecorationLine, thickness: cs.textDecorationThickness, outline: `${cs.outlineStyle} ${cs.outlineWidth} ${cs.outlineColor}`, focused: document.activeElement === el };
    });
    await rest(page);
    const calm = await style();
    await reset.hover();
    await page.evaluate(() => Promise.all(document.getAnimations().map((a) => a.finished.catch(() => {}))));
    const hover = await style();
    await rest(page);
    for (let i = 0; i < 40 && !(await style()).focused; i++) await page.keyboard.press('Tab');
    const focus = await style();
    check('D03', 'Ссылка-кнопка «Сбросить»: наведение утолщает подчёркивание, фокус с клавиатуры даёт кольцо',
      calm.line.includes('underline') && hover.line.includes('underline') && parseFloat(hover.thickness) > parseFloat(calm.thickness) && focus.focused && focus.outline.startsWith('solid 2px'),
      `покой ${hex(calm.color)} ${calm.thickness}; наведение ${hex(hover.color)} ${hover.thickness}; фокус: ${focus.outline}`);
    await context.close();
  }
  await decoder.close();
});

writeFileSync(join(outDir, 'cvd-detail.json'), JSON.stringify({ tokens: tokensPath, table, samples, states: detail }, null, 2), 'utf8');
const failed = results.filter((r) => !r.ok);
const warned = table.filter((row) => !row.d03 && row.below.length);
console.log(`\nИтого: проверок ${results.length}, провалено ${failed.length}; справочных пар ниже порога при симуляции ${warned.length}; снимки — ${cvdDir}`);
process.exit(failed.length ? 1 : 0);
