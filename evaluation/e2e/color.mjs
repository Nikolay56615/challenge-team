// Цветовая математика для check_contrast.mjs и check_cvd.mjs (docs/ui-kit.md, 2.1 и 6; кандидаты D03 и D18).
// Токены читаются из tokens.css. Контраст — формула WCAG 2.2. Различие цветов — CIEDE2000 в CIELAB.
// Симуляция нарушений цветового зрения — матрицы Machado, Oliveira и Fernandes (2009) для степени 1,0,
// применяются к линейному sRGB, как в эмуляции Chromium (CDP Emulation.setEmulatedVisionDeficiency).

import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Рабочая папка: app/frontend; репозиторий комплекта: frontend в корне
const TOKEN_PATHS = ['../../app/frontend/src/styles/tokens.css', '../../frontend/src/styles/tokens.css'];

/**
 * Цветовые токены из tokens.css: имя без префикса color- → #rrggbb в нижнем регистре.
 * Токен не в виде #rgb или #rrggbb попадает в unparsed: контраст для rgb(), hsl(), var() и альфа-канала не считается.
 * Переменная TOKENS_CSS задаёт другой файл: так проверяют вариант палитры и отрицательный случай.
 */
export function readTokens() {
  const override = process.env.TOKENS_CSS;
  const candidates = override ? [new URL(`file:///${override.replace(/\\/g, '/').replace(/^\/+/, '')}`)] : TOKEN_PATHS.map((path) => new URL(path, import.meta.url));
  const url = candidates.find((candidate) => existsSync(candidate));
  if (!url) throw new Error('Не найден tokens.css: ' + candidates.map((candidate) => fileURLToPath(candidate)).join(', '));
  const tokens = {};
  const unparsed = [];
  for (const [, name, raw] of readFileSync(url, 'utf8').matchAll(/--color-([a-z0-9-]+)\s*:\s*([^;]+);/gi)) {
    const value = raw.trim().toLowerCase();
    if (/^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/.test(value)) tokens[name] = expand(value);
    else unparsed.push(`--color-${name}: ${raw.trim()}`);
  }
  return { path: fileURLToPath(url), tokens, unparsed };
}

function expand(hex) {
  const h = hex.slice(1);
  return h.length === 3 ? '#' + [...h].map((x) => x + x).join('') : hex;
}

/** #rrggbb или rgb(r, g, b) из getComputedStyle → [r, g, b] в 0–255; прозрачный или неизвестный цвет → null */
export function parseColor(value) {
  if (!value) return null;
  const text = value.trim().toLowerCase();
  if (text.startsWith('#')) {
    const h = expand(text).slice(1);
    return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  }
  const m = text.match(/^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/);
  if (!m) return null;
  if (m[4] !== undefined && parseFloat(m[4]) === 0) return null;
  return [m[1], m[2], m[3]].map(Number);
}

export function toHex(rgb) {
  return '#' + rgb.map((c) => Math.round(c).toString(16).padStart(2, '0')).join('');
}

const toLinear = (c) => {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
};
const toGamma = (v) => 255 * (v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055);

// Machado G. M., Oliveira M. M., Fernandes L. A. F. A Physiologically-based Model for Simulation of Color Vision
// Deficiency. IEEE TVCG 15(6), 2009. Матрицы для степени 1,0 (дихроматия), линейный RGB.
export const MATRICES = {
  protanopia: [
    [0.152286, 1.052583, -0.204868],
    [0.114503, 0.786281, 0.099216],
    [-0.003882, -0.048116, 1.051998],
  ],
  deuteranopia: [
    [0.367322, 0.860646, -0.227968],
    [0.280085, 0.672501, 0.047413],
    [-0.01182, 0.04294, 0.968881],
  ],
  tritanopia: [
    [1.255528, -0.076749, -0.178779],
    [-0.078411, 0.930809, 0.147602],
    [0.004733, 0.691367, 0.3039],
  ],
};
export const VISION = ['none', 'protanopia', 'deuteranopia', 'tritanopia'];
export const VISION_LABEL = { none: 'обычное', protanopia: 'протанопия', deuteranopia: 'дейтеранопия', tritanopia: 'тританопия' };

/** Цвет [r, g, b] 0–255 глазами человека с дихроматией type; none — без изменений */
export function simulate(rgb, type = 'none') {
  if (type === 'none') return rgb;
  const lin = rgb.map(toLinear);
  return MATRICES[type].map((row) => toGamma(Math.min(1, Math.max(0, row[0] * lin[0] + row[1] * lin[1] + row[2] * lin[2]))));
}

/** Относительная яркость WCAG 2.2 */
export function luminance(rgb) {
  const [r, g, b] = rgb.map(toLinear);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Контраст WCAG 2.2: (L1 + 0,05) / (L2 + 0,05). Принимает #hex или [r, g, b] */
export function contrast(a, b, type = 'none') {
  const [x, y] = [a, b].map((c) => simulate(Array.isArray(c) ? c : parseColor(c), type));
  const [hi, lo] = [luminance(x), luminance(y)].sort((p, q) => q - p);
  return (hi + 0.05) / (lo + 0.05);
}

/** CIELAB D65 из sRGB */
export function lab(rgb) {
  const [r, g, b] = rgb.map(toLinear);
  const x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047;
  const y = 0.2126729 * r + 0.7151522 * g + 0.072175 * b;
  const z = (0.0193339 * r + 0.119192 * g + 0.9503041 * b) / 1.08883;
  const f = (t) => (t > 216 / 24389 ? Math.cbrt(t) : (24389 / 27 * t + 16) / 116);
  const [fx, fy, fz] = [f(x), f(y), f(z)];
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}

/** Насыщенность C*ab: у нейтрального серого около 0 */
export function chroma(rgb) {
  const [, a, b] = lab(rgb);
  return Math.hypot(a, b);
}

/** Различие цветов CIEDE2000 после симуляции type. Принимает #hex или [r, g, b] */
export function deltaE(a, b, type = 'none') {
  const [x, y] = [a, b].map((c) => lab(simulate(Array.isArray(c) ? c : parseColor(c), type)));
  return deltaE2000(x, y);
}

/** CIEDE2000 для двух цветов CIELAB (Sharma, Wu, Dalal, 2005) */
export function deltaE2000([l1, a1, b1], [l2, a2, b2]) {
  const rad = Math.PI / 180;
  const c1 = Math.hypot(a1, b1);
  const c2 = Math.hypot(a2, b2);
  const cBar7 = ((c1 + c2) / 2) ** 7;
  const g = 0.5 * (1 - Math.sqrt(cBar7 / (cBar7 + 25 ** 7)));
  const a1p = (1 + g) * a1;
  const a2p = (1 + g) * a2;
  const c1p = Math.hypot(a1p, b1);
  const c2p = Math.hypot(a2p, b2);
  const hue = (bb, ap) => (bb === 0 && ap === 0 ? 0 : ((Math.atan2(bb, ap) / rad) % 360 + 360) % 360);
  const h1p = hue(b1, a1p);
  const h2p = hue(b2, a2p);
  const dLp = l2 - l1;
  const dCp = c2p - c1p;
  let dhp = 0;
  if (c1p * c2p !== 0) {
    dhp = h2p - h1p;
    if (dhp > 180) dhp -= 360;
    else if (dhp < -180) dhp += 360;
  }
  const dHp = 2 * Math.sqrt(c1p * c2p) * Math.sin((dhp * rad) / 2);
  const lBar = (l1 + l2) / 2;
  const cBarP = (c1p + c2p) / 2;
  let hBar = h1p + h2p;
  if (c1p * c2p !== 0) {
    if (Math.abs(h1p - h2p) <= 180) hBar = (h1p + h2p) / 2;
    else hBar = h1p + h2p < 360 ? (h1p + h2p + 360) / 2 : (h1p + h2p - 360) / 2;
  }
  const t =
    1 - 0.17 * Math.cos((hBar - 30) * rad) + 0.24 * Math.cos(2 * hBar * rad) + 0.32 * Math.cos((3 * hBar + 6) * rad) - 0.2 * Math.cos((4 * hBar - 63) * rad);
  const dTheta = 30 * Math.exp(-(((hBar - 275) / 25) ** 2));
  const rc = 2 * Math.sqrt(cBarP ** 7 / (cBarP ** 7 + 25 ** 7));
  const sl = 1 + (0.015 * (lBar - 50) ** 2) / Math.sqrt(20 + (lBar - 50) ** 2);
  const sc = 1 + 0.045 * cBarP;
  const sh = 1 + 0.015 * cBarP * t;
  const rt = -Math.sin(2 * dTheta * rad) * rc;
  return Math.sqrt((dLp / sl) ** 2 + (dCp / sc) ** 2 + (dHp / sh) ** 2 + rt * (dCp / sc) * (dHp / sh));
}

/** Число с запятой: 6,04 */
export const fmt = (x, digits = 2) => x.toFixed(digits).replace('.', ',');
