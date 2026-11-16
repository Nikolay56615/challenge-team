// Расчёты экрана ленты (src/feed.ts; docs/plan.md, раздел 13): состав оценки и сравнение карточек.
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  FAMILY_OF,
  changeSentence,
  compareRows,
  feedChange,
  formatDelta,
  formatScore,
  segments,
  shareSegments,
  sharedCards,
} from '../src/feed.ts';

const part = (source, label, value) => ({ source, label, value, evidence: null });
const item = (rank, id, parts) => ({
  rank,
  material_id: id,
  parts,
  score: Math.round(parts.reduce((sum, p) => sum + p.value, 0) * 100) / 100,
});

const first = item(1, 'A', [
  part('links', 'Совет редакции', 1.5),
  part('content', 'Похожее содержание', 0.49),
  part('popularity', 'Популярность', 0.28),
]);
const second = item(2, 'B', [
  part('history', 'Выбор слушателей', 1.2),
  part('content', 'Похожее содержание', 0.19),
  part('seen', 'Уже открывали', -1.5),
  part('task', 'Ваша задача', 3),
  part('profile', 'Ваша анкета', 2),
]);

test('числа пишутся с запятой и типографским минусом', () => {
  assert.equal(formatScore(2.27), '2,27');
  assert.equal(formatScore(-1.5), '−1,50');
  assert.equal(formatDelta(1.5), '+1,50');
  assert.equal(formatDelta(-0.1), '−0,10');
});

test('две карточки рядом: разницы по источникам в сумме дают разницу оценок', () => {
  const rows = compareRows(first, second);
  const sum = Math.round(rows.reduce((total, row) => total + row.delta, 0) * 100) / 100;
  assert.equal(sum, Math.round((first.score - second.score) * 100) / 100);
  assert.deepEqual(rows.map((row) => row.source).sort(), ['content', 'history', 'links', 'popularity', 'profile', 'seen', 'task']);
  const links = rows.find((row) => row.source === 'links');
  assert.deepEqual([links.a, links.b, links.delta], [1.5, 0, 1.5]);
  assert.ok(Math.abs(rows[0].delta) >= Math.abs(rows.at(-1).delta));
  assert.ok(compareRows(first, first).every((row) => row.delta === 0));
});

test('полоса складывает положительные вклады по группам, отрицательный в неё не входит', () => {
  const bar = segments(second);
  assert.deepEqual(bar.map((segment) => segment.family), ['history', 'content', 'own']);
  assert.equal(bar.find((segment) => segment.family === 'own')?.value, 5);
  assert.equal(FAMILY_OF.seen, null);
});

test('два клиента рядом: общие карточки на глубине и доли источников по группам', () => {
  const own = [item(1, 'A', []), item(2, 'B', []), item(3, 'C', [])];
  const other = [item(1, 'C', []), item(2, 'A', []), item(3, 'D', [])];
  assert.equal(sharedCards(own, other, 2), 1); // в первых двух у обоих только A
  assert.equal(sharedCards(own, other, 3), 2);
  const bar = shareSegments([
    { source: 'history', share: 0.5 },
    { source: 'task', share: 0.2 },
    { source: 'profile', share: 0.1 },
    { source: 'popularity', share: 0.2 },
    { source: 'seen', share: 0 },
  ]);
  assert.deepEqual(bar.map((segment) => segment.family), ['history', 'own', 'popularity']);
  assert.ok(Math.abs(bar[1].value - 0.3) < 1e-9);
});

test('пересчёт ленты: новые, ушедшие и сменившие место карточки', () => {
  const before = new Map([['A', 1], ['B', 2], ['C', 3]]);
  const change = feedChange(before, [item(1, 'B', []), item(2, 'A', []), item(3, 'D', [])]);
  assert.deepEqual([change.arrived, change.left, change.moved], [1, 1, 2]);
  assert.equal(change.shift.get('B'), 1);
  assert.equal(change.shift.get('A'), -1);
  assert.equal(change.shift.get('D'), null);
  assert.equal(changeSentence(change), 'Новых карточек: 1. Ушло: 1. Сменили место: 2.');
  assert.equal(changeSentence(feedChange(before, [item(1, 'A', []), item(2, 'B', []), item(3, 'C', [])])), 'Лента не изменилась.');
});
