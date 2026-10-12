import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseRate, mulberry32, normInv, normCdf, norm, analyzeActivity } from '../public/js/engine.js';
import { parseClogCategory, parseStats } from '../public/js/temple.js';

const dataset = JSON.parse(readFileSync(new URL('../public/data/activities.json', import.meta.url)));

test('parseRate grammar', () => {
  assert.equal(parseRate('1/512'), 1 / 512);
  assert.ok(Math.abs(parseRate('2x1/1024') - (1 - (1 - 1 / 1024) ** 2)) < 1e-12);
  assert.equal(parseRate(0.25), 0.25);
});

test('normInv/normCdf are inverse', () => {
  for (const p of [0.001, 0.05, 0.5, 0.9, 0.999]) assert.ok(Math.abs(normCdf(normInv(p)) - p) < 1e-6);
});

// Independent kill-by-kill simulation of plain items.
function simulatePlayer(act, kc, rng) {
  const counts = new Map();
  for (const it of act.items) {
    const p = parseRate(it.rate);
    let n = 0;
    for (let k = 0; k < kc; k++) if (rng() < p) n++;
    counts.set(norm(it.name), n);
  }
  const arr = [...counts].map(([name, count]) => ({ name, count }));
  return { counts, obtained: arr.filter((a) => a.count > 0).length, total: arr.length, listComplete: true, namesAvailable: true };
}

test('percentiles are roughly uniform for simulated Zulrah players', () => {
  const act = dataset.activities.zulrah;
  const rng = mulberry32(12345);
  const n = 300, kc = 1500;
  const us = [];
  for (let i = 0; i < n; i++) {
    const clog = simulatePlayer(act, kc, rng);
    const r = analyzeActivity(act, { id: 'zulrah', kc: { main: kc }, clog, sims: 4000 });
    us.push(r.luck.percentile / 100);
  }
  const mean = us.reduce((a, b) => a + b, 0) / n;
  assert.ok(Math.abs(mean - 0.5) < 0.06, `mean percentile ${mean}`);
  const lo = us.filter((u) => u < 0.1).length / n;
  const hi = us.filter((u) => u > 0.9).length / n;
  assert.ok(lo > 0.04 && lo < 0.17, `lower tail ${lo}`);
  assert.ok(hi > 0.04 && hi < 0.17, `upper tail ${hi}`);
});

test('zero-drop player is flagged dry, full-log player lucky', () => {
  const act = dataset.activities.zulrah;
  const mk = (c) => ({ counts: new Map(act.items.map((i) => [norm(i.name), c])), obtained: c ? act.items.length : 0, total: act.items.length, listComplete: true, namesAvailable: true });
  const dry = analyzeActivity(act, { id: 'zulrah', kc: { main: 6000 }, clog: mk(0), sims: 4000 });
  const lucky = analyzeActivity(act, { id: 'zulrah', kc: { main: 300 }, clog: mk(1), sims: 4000 });
  assert.ok(dry.luck.percentile < 5);
  assert.ok(lucky.luck.percentile > 95);
});

test('legacy clog without names does not crash or score items', () => {
  const act = dataset.activities.zulrah;
  const r = analyzeActivity(act, { id: 'zulrah', kc: { main: 500 }, clog: { obtained: 3, total: 8, listComplete: false, namesAvailable: false, legacy: true, counts: new Map() } });
  assert.equal(r.luck, null);
  assert.ok(r.warnings.length);
});

test('every item-model activity runs without error', () => {
  for (const [id, act] of Object.entries(dataset.activities)) {
    const kc = Object.fromEntries(Object.keys(act.sources).map((s) => [s, 800]));
    const r = analyzeActivity(act, { id, kc, clog: null, sims: 500 });
    assert.ok(r && r.kcTotal > 0, id);
  }
});

test('temple parsers', () => {
  const m = parseStats({ data: { Zulrah: 120, 'Vet\'ion': '30', junk: 'x' } });
  assert.equal(m.get('zulrah'), 120);
  assert.equal(m.get('vetion'), 30);
  const c = parseClogCategory({ data: { items: { zulrah: [{ name: 'Tanzanite fang', count: 2 }] }, missing_items: { zulrah: [{ name: 'Magic fang' }] } } }, 'zulrah');
  assert.equal(c.obtained, 1);
  assert.equal(c.listComplete, true);
  assert.equal(c.counts.get('magicfang'), 0);
});
