#!/usr/bin/env node
// Validates public/data/activities.json and compares each activity's computed
// "expected KC to complete the log" with the Temple EKC stored in the dataset.
//
//   node scripts/check-data.mjs            # table of ratios
//   node scripts/check-data.mjs --strict   # exit 1 on structural errors
//
// A big mismatch does not necessarily mean the data is wrong (Temple makes its own
// assumptions about pets, team sizes, modes...) but it is the first place to look.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { resolveItems, pityProbability, parseRate } from '../public/js/engine.js';
import { DEFAULT_ASSUMPTIONS } from '../public/js/raids.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const dataset = JSON.parse(readFileSync(path.join(here, '../public/data/activities.json'), 'utf8'));
const strict = process.argv.includes('--strict');
const errors = [];

function poissonAtLeast(c, lambda) {
  if (c <= 0) return 1;
  let pk = Math.exp(-lambda), cdf = 0;
  for (let k = 0; k < c; k++) { cdf += pk; pk *= lambda / (k + 1); }
  return Math.max(0, 1 - cdf);
}

// P(item obtained by KC t) when all KC is in source `src`
function cdfFor(item, groups, src) {
  if (item.type === 'plain') {
    const p = item.rates[src] || 0;
    return (t) => 1 - Math.pow(1 - p, t);
  }
  if (item.type === 'group') {
    const R = groups[item.group].rates[src] || 0;
    return (t) => poissonAtLeast(item.needs, R * t);
  }
  if (item.type === 'pity') return (t) => pityProbability(item.pity, Math.min(t, 5000));
  return null;
}

function expectedCompletion(act, src, assumptions) {
  const { items, groups } = resolveItems(act, assumptions);
  const cdfs = items.map((it) => cdfFor(it, groups, src)).filter(Boolean);
  const rng = items.filter((it) => it.type !== 'free');
  if (!cdfs.length) return null;
  // skip items that can never drop from this source
  const live = rng.filter((it) => (it.type === 'plain' ? (it.rates[src] || 0) > 0 : it.type === 'group' ? (groups[it.group].rates[src] || 0) > 0 : true));
  const fns = live.map((it) => cdfFor(it, groups, src));
  let sum = 0, t = 0, step = 1;
  while (t < 5e6) {
    let prod = 1;
    for (const f of fns) prod *= f(t);
    const tail = 1 - prod;
    sum += tail * step;
    if (tail < 1e-9) break;
    t += step;
    if (t > 2000) step = Math.max(step, Math.floor(t / 400));
  }
  return sum;
}

const rows = [];
for (const [id, act] of Object.entries(dataset.activities)) {
  if (!act.sources || !Object.keys(act.sources).length) errors.push(`${id}: no sources`);
  if (!act.name) errors.push(`${id}: no name`);
  if (act.approx) { rows.push({ id, conf: act.confidence, model: 'approx' }); continue; }
  const groupIds = new Set(Object.keys(act.groups || {}));
  const names = new Set();
  for (const it of act.items || []) {
    if (!it.name) errors.push(`${id}: item without name`);
    if (names.has(it.name)) errors.push(`${id}: duplicate item "${it.name}"`);
    names.add(it.name);
    try {
      if (it.rate != null) parseRate(it.rate);
      if (it.rates) for (const r of Object.values(it.rates)) parseRate(r);
      if (it.pity) { parseRate(it.pity.start); parseRate(it.pity.end); }
    } catch (e) { errors.push(`${id}/${it.name}: ${e.message}`); }
    if (it.group && !groupIds.has(it.group)) errors.push(`${id}/${it.name}: unknown group ${it.group}`);
    if (it.rates) for (const s of Object.keys(it.rates)) if (!act.sources[s]) errors.push(`${id}/${it.name}: unknown source ${s}`);
    const kind = it.kind || 'rng';
    const hasMeans = it.rate != null || it.rates || it.pity || it.group || it.weight != null || it.special;
    if (kind === 'rng' && !hasMeans) errors.push(`${id}/${it.name}: rng item with no rate`);
  }
  const per = {};
  for (const s of Object.keys(act.sources)) {
    try { per[s] = expectedCompletion(act, s, DEFAULT_ASSUMPTIONS); } catch (e) { errors.push(`${id}: ${e.message}`); }
  }
  const main = Object.values(per).filter((v) => v != null);
  const best = main.length ? Math.min(...main) : null;
  rows.push({
    id, conf: act.confidence, model: 'items',
    computed: best, temple: act.templeEkc,
    ratio: best && act.templeEkc ? best / act.templeEkc : null,
    detail: Object.entries(per).map(([s, v]) => `${s}:${v == null ? '-' : Math.round(v)}`).join(' '),
  });
}

const pad = (s, n) => String(s).padEnd(n);
console.log(pad('activity', 30), pad('conf', 8), pad('computed', 10), pad('temple', 8), pad('ratio', 7), 'per-source');
for (const r of rows) {
  if (r.model === 'approx') { console.log(pad(r.id, 30), pad(r.conf, 8), '(equal-rate model calibrated to Temple EKC)'); continue; }
  console.log(
    pad(r.id, 30), pad(r.conf, 8),
    pad(r.computed ? Math.round(r.computed) : '-', 10),
    pad(r.temple ?? '-', 8),
    pad(r.ratio ? r.ratio.toFixed(2) : '-', 7),
    r.detail,
  );
}
if (errors.length) {
  console.log('\nERRORS');
  for (const e of errors) console.log(' -', e);
  if (strict) process.exit(1);
} else {
  console.log('\nNo structural errors.');
}
