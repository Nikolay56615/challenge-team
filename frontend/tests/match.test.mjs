// Пометки «Совпало» из contributions. Вклады взяты из ответов синтетического
// каталога для P01, P02, P05 и P11: ответ /api/compare снимка бэкенда после волны A.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { EXPERIENCE_LEVEL, MATCH_LABELS, MATCH_MAX, matchLabels } from '../src/match.ts';

test('P01, M01: тема, стадия, уровень, сфера; усилие не показывается', () => {
  assert.deepEqual(
    matchLabels({ topic: 3, stage: 2, level: 2, industry: 1, effort: 0.5 }, { level: 'intro', experience: 'none' }),
    ['тема', 'стадия', 'уровень', 'сфера'],
  );
});

test('P02, M02: не больше четырёх пометок по убыванию вклада, при равенстве — порядок признаков', () => {
  assert.deepEqual(matchLabels({ format: 1.5, level: 2, stage: 2, signal: 2, topic: 3 }), ['тема', 'суть задачи', 'стадия', 'уровень']);
  assert.deepEqual(matchLabels({ topic: 3, stage: 2, level: 2 }, { max: 2 }), ['тема', 'стадия']);
  assert.equal(MATCH_MAX, 4);
});

test('смежный уровень — не совпадение: причина говорит «на шаг глубже» или «проще», пометки «уровень» нет', () => {
  // P01, M03: опыт «нет» — вводный уровень, шаблон практического уровня на шаг глубже, вклад уровня 1,0
  assert.deepEqual(
    matchLabels({ topic: 3, stage: 2, level: 1, effort: 0.5 }, { level: 'practical', experience: 'none' }),
    ['тема', 'стадия'],
  );
  // P02, M03: опыт «большой» — продвинутый уровень, материал на шаг проще
  assert.deepEqual(matchLabels({ topic: 3, level: 1 }, { level: 'practical', experience: 'experienced' }), ['тема']);
  // Точное совпадение при том же опыте остаётся
  assert.deepEqual(matchLabels({ topic: 3, level: 2 }, { level: 'advanced', experience: 'experienced' }), ['тема', 'уровень']);
  assert.deepEqual(EXPERIENCE_LEVEL, { none: 'intro', some: 'practical', experienced: 'advanced' });
});

test('без опыта в запросе вклад уровня даёт только подсказка из текста при точном совпадении: пометка есть', () => {
  assert.deepEqual(matchLabels({ topic: 3, level: 1 }, { level: 'intro', experience: null }), ['тема', 'уровень']);
  assert.deepEqual(matchLabels({ topic: 3, level: 1 }, { level: 'intro' }), ['тема', 'уровень']);
});

test('отрицательные и нулевые вклады, неизвестные признаки и прототип объекта пометок не дают', () => {
  assert.deepEqual(matchLabels({ topic: 3, stage: 2, viewed: -1.5 }), ['тема', 'стадия']);
  assert.deepEqual(matchLabels({ completed: -4, popularity: 1, effort: 0.5, constructor: 1, toString: 2 }), []);
  assert.deepEqual(matchLabels({ topic: 0, stage: Number.NaN }), []);
  assert.deepEqual(matchLabels({}), []);
  assert.deepEqual(matchLabels(null), []);
});

test('P11, подбор по истории: продолжение и начатый материал — одна пометка', () => {
  assert.deepEqual(matchLabels({ continuation: 1.5, history_topic: 1 }), ['продолжение', 'тема истории']);
  assert.deepEqual(matchLabels({ history_topic: 1, co_enrollment: 0.9 }), ['тема истории', 'похожие курсы']);
  assert.deepEqual(matchLabels({ in_progress: 2, continuation: 1.5, topic: 3 }), ['тема', 'продолжение']);
});

test('подписи короткие и без чисел', () => {
  for (const label of Object.values(MATCH_LABELS)) {
    assert.ok(label.length <= 16 && !/\d/.test(label), label);
  }
});
