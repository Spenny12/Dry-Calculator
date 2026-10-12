// Spoon engine (model v11)
//
// For every activity we build a probabilistic model of how loot arrives, then ask:
// "out of players with this exact KC, what share would have a haul worth less than
// this player's?". That share is the luck percentile (50 = on rate, 99 = spooned).
//
//  * Every drop has its own per-kill rate (and per-mode rates for raids, or per-boss
//    rates for things like Callisto/Artio), so a 1/5000 pet and a 1/128 ring are
//    never treated as interchangeable "slots".
//  * Haul value: each drop is worth its expected wait in KC (1/rate). Getting a 1/5000
//    item early counts for far more than a common one, but ties and duplicates are
//    handled exactly.
//  * Guaranteed items, KC-milestone capes and crafted/derived items are removed from
//    the maths (they carry no luck), and shown separately.
//  * Dup-protected sets and "N qualifying rolls" items (Araxxor halberd, DT2 vestiges,
//    Hydra pieces, Moons sets) are progressive groups: one stream of events that
//    unlocks items in order.
//  * Items whose rate climbs until the first drop (blood quartz, ToA jewels, Vorkath's
//    head) use their real per-kill hazard schedule.

import { resolveRaidItems, mergeAssumptions } from './raids.js';

export const MODEL_VERSION = 'v12';
export const DEFAULT_SIMS = 20000;

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------
export function norm(s) {
  return String(s == null ? '' : s)
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '');
}

// "1/512", "2x1/1024" (2 rolls), "3/1088", or a plain probability -> per-kill probability
export function parseRate(r) {
  if (typeof r === 'number') return r;
  const m = String(r).trim().match(/^(?:(\d+(?:\.\d+)?)\s*[x×*]\s*)?(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)$/i);
  if (!m) throw new Error(`Cannot parse rate "${r}"`);
  const rolls = m[1] ? parseFloat(m[1]) : 1;
  const p = parseFloat(m[2]) / parseFloat(m[3]);
  return 1 - Math.pow(1 - p, rolls);
}

export function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function hashString(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

function gauss(rng) {
  const u1 = Math.max(rng(), 1e-12), u2 = rng();
  return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}

// Binomial sampler prepared once per (n, p): inversion when n*p is small, normal otherwise.
export function makeBinomial(n, p) {
  n = Math.max(0, Math.floor(n));
  if (n === 0 || p <= 0) return { zero: true };
  if (p >= 1) return { all: n };
  const pq = Math.min(p, 1 - p);
  if (n * pq < 30) {
    return { n, p, r: p / (1 - p), p0: Math.exp(n * Math.log1p(-p)) };
  }
  return { n, normal: true, mean: n * p, sd: Math.sqrt(n * p * (1 - p)) };
}

export function drawBinomial(b, rng) {
  if (b.zero) return 0;
  if (b.all !== undefined) return b.all;
  if (b.normal) {
    const x = Math.round(b.mean + b.sd * gauss(rng));
    return x < 0 ? 0 : x > b.n ? b.n : x;
  }
  const u = rng();
  let pk = b.p0, s = pk, k = 0;
  while (u > s && k < b.n) {
    pk *= ((b.n - k) / (k + 1)) * b.r;
    k++;
    s += pk;
    if (pk < 1e-300) break;
  }
  return k;
}

// Standard normal quantile (Acklam) and CDF
export function normInv(p) {
  if (p <= 0) return -Infinity;
  if (p >= 1) return Infinity;
  const a = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2, 1.38357751867269e2, -3.066479806614716e1, 2.506628277459239];
  const b = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2, 6.680131188771972e1, -1.328068155288572e1];
  const c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416];
  const plow = 0.02425;
  let q, r;
  if (p < plow) {
    q = Math.sqrt(-2 * Math.log(p));
    return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  if (p > 1 - plow) {
    q = Math.sqrt(-2 * Math.log(1 - p));
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  q = p - 0.5; r = q * q;
  return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q /
    (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
}

export function normCdf(x) {
  // Zelen & Severo, abs error < 1e-7
  const t = 1 / (1 + 0.2316419 * Math.abs(x));
  const d = 0.3989422804014327 * Math.exp(-x * x / 2);
  const p = d * t * (0.31938153 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
  return x >= 0 ? 1 - p : p;
}

// P(Poisson(lambda) >= c)
export function poissonAtLeast(c, lambda) {
  if (c <= 0) return 1;
  if (lambda <= 0) return 0;
  let pk = Math.exp(-lambda), cdf = 0;
  for (let k = 0; k < c; k++) {
    cdf += pk;
    pk *= lambda / (k + 1);
    if (pk === 0 && k > lambda) break;
  }
  return Math.max(0, 1 - cdf);
}

// ---------------------------------------------------------------------------
// pity items: per-kill hazard rises linearly from `start` (kill 1) to `end` (kill atKc)
// ---------------------------------------------------------------------------
function pityParams(p) {
  return {
    start: parseRate(p.start), end: parseRate(p.end),
    atKc: p.atKc || 0, guaranteeAt: p.guaranteeAt || 0,
  };
}

function hazard(pp, k) {
  if (pp.guaranteeAt && k >= pp.guaranteeAt) return 1;
  if (!pp.atKc || pp.atKc <= 1) return pp.end;
  if (k >= pp.atKc) return pp.end;
  return pp.start + (pp.end - pp.start) * (k - 1) / (pp.atKc - 1);
}

// P(first drop has happened within n kills)
export function pityProbability(p, n) {
  const pp = pityParams(p);
  let S = 1;
  for (let k = 1; k <= n; k++) {
    S *= 1 - hazard(pp, k);
    if (S < 1e-15) return 1;
  }
  return 1 - S;
}

// expected kills until the first drop
export function pityMeanWait(p) {
  const pp = pityParams(p);
  let S = 1, sum = 1; // k = 0 term
  for (let k = 1; k < 400000; k++) {
    S *= 1 - hazard(pp, k);
    sum += S;
    if (S < 1e-12) break;
  }
  return sum;
}

// ---------------------------------------------------------------------------
// resolving the dataset entry into numeric items
// ---------------------------------------------------------------------------
export function resolveItems(act, assumptions) {
  if (act.raid) return resolveRaidItems(act, assumptions);

  const srcKeys = Object.keys(act.sources);
  const groups = {};
  for (const [id, g] of Object.entries(act.groups || {})) {
    const rates = {};
    if (g.rates) for (const [s, r] of Object.entries(g.rates)) rates[s] = parseRate(r);
    else for (const s of srcKeys) rates[s] = parseRate(g.rate);
    groups[id] = { rates };
  }

  const items = (act.items || []).map((it) => {
    const base = { name: it.name, aliases: it.alias || [], kind: it.kind || 'rng', max: it.max, milestoneAt: it.at, sharedWith: it.sharedWith };
    if (base.kind !== 'rng') return { ...base, type: 'free' };
    if (it.group) return { ...base, type: 'group', group: it.group, needs: it.needs || 1 };
    if (it.pity) return { ...base, type: 'pity', pity: it.pity };
    const rates = {};
    if (it.rates) for (const [s, r] of Object.entries(it.rates)) rates[s] = parseRate(r);
    else if (it.rate != null) for (const s of srcKeys) rates[s] = parseRate(it.rate);
    else return { ...base, type: 'free' };
    return { ...base, type: 'plain', rates };
  });
  return { items, groups };
}

// ---------------------------------------------------------------------------
// matching dataset items against what Temple returned for the category
// ---------------------------------------------------------------------------
function lookupObserved(item, clog) {
  const keys = [norm(item.name), ...item.aliases.map(norm)].filter(Boolean);
  for (const k of keys) if (clog.counts.has(k)) return { found: true, count: clog.counts.get(k) };
  const cands = [];
  for (const key of clog.counts.keys()) {
    if (key.length < 6) continue;
    for (const k of keys) {
      if (k.length >= 6 && (key.includes(k) || k.includes(key))) { cands.push(key); break; }
    }
  }
  if (cands.length === 1) return { found: true, count: clog.counts.get(cands[0]) };
  return { found: false, count: 0 };
}

// ---------------------------------------------------------------------------
// status buckets from luck percentile (0-100)
// ---------------------------------------------------------------------------
export const STATUS_BANDS = [
  { min: 97.5, key: 'spooned', label: 'Spooned' },
  { min: 85, key: 'lucky', label: 'Lucky' },
  { min: 15, key: 'on-rate', label: 'On rate' },
  { min: 2.5, key: 'dry', label: 'Dry' },
  { min: -1, key: 'very-dry', label: 'Very dry' },
];

export function statusFor(percentile) {
  for (const b of STATUS_BANDS) if (percentile >= b.min) return b;
  return STATUS_BANDS[STATUS_BANDS.length - 1];
}

// ---------------------------------------------------------------------------
// the main analysis
// ---------------------------------------------------------------------------
function harmonic(m) { let h = 0; for (let i = 1; i <= m; i++) h += 1 / i; return h; }

function percentileFromSims(sims, vObs) {
  let below = 0, equal = 0;
  for (let i = 0; i < sims.length; i++) {
    const v = sims[i];
    if (v < vObs) below++;
    else if (v === vObs) equal++;
  }
  return (below + 0.5 * equal) / sims.length;
}

// z-scores of the simulated null distribution (mid-rank), used to calibrate the
// overall score: discrete activities have a null variance below 1.
function nullZStats(sims) {
  const sorted = Float64Array.from(sims).sort();
  const N = sorted.length;
  let sum = 0, sum2 = 0, i = 0;
  while (i < N) {
    let j = i + 1;
    while (j < N && sorted[j] === sorted[i]) j++;
    const u = (i + (j - i) / 2) / N;
    const z = normInv(Math.min(Math.max(u, 0.5 / N), 1 - 0.5 / N));
    sum += z * (j - i); sum2 += z * z * (j - i);
    i = j;
  }
  const mean = sum / N;
  return { mean, sd: Math.sqrt(Math.max(sum2 / N - mean * mean, 0)) };
}

export function analyzeActivity(act, ctx) {
  const kc = ctx.kc || {};
  const srcKeys = Object.keys(act.sources);
  const nBy = {};
  let total = 0;
  for (const s of srcKeys) { nBy[s] = Math.max(0, Math.floor(kc[s] || 0)); total += nBy[s]; }
  if (total <= 0) return null;

  const N = ctx.sims || DEFAULT_SIMS;
  const rawClog = ctx.clog || null;
  // A collection log without item names (legacy {obtained,total}) cannot drive the per-item model.
  const clog = rawClog && (act.approx || rawClog.namesAvailable !== false) ? rawClog : null;
  const base = {
    id: ctx.id, name: act.name, type: act.type, confidence: act.confidence,
    kc: nBy, kcTotal: total, note: act.note || '', wiki: act.wiki || '',
    slots: rawClog ? { obtained: rawClog.obtained, total: rawClog.total } : null,
    warnings: [], items: [], free: [], luck: null, expectedSlots: null,
  };
  const seed = hashString(`${MODEL_VERSION}|${ctx.id}|${srcKeys.map((s) => nBy[s]).join(',')}|${N}`);

  // ---------------- approximate (equal-rate) model ----------------
  if (act.approx) {
    const m = Math.max(1, act.approx.slots - (act.approx.free || 0));
    const p = Math.min(0.5, harmonic(m) / act.templeEkc);
    const q = 1 - Math.pow(1 - p, total);
    base.expectedSlots = (act.approx.free || 0) + m * q;
    base.model = 'approx';
    if (!clog) return base;
    const kObs = Math.min(m, Math.max(0, clog.obtained - (act.approx.free || 0)));
    const rng = mulberry32(seed);
    const bin = makeBinomial(m, q);
    const sims = new Float64Array(N);
    for (let i = 0; i < N; i++) sims[i] = drawBinomial(bin, rng);
    const u = percentileFromSims(sims, kObs);
    const zs = nullZStats(sims);
    base.luck = finishLuck(u, zs, N);
    base.rngObserved = kObs; base.rngSlots = m;
    return base;
  }

  // ---------------- per-item model ----------------
  const { items, groups } = resolveItems(act, ctx.assumptions);
  base.model = 'items';
  if (rawClog && !clog) base.warnings.push('Temple returned no item names for this category, so luck could not be scored.');
  const plain = [], groupMap = new Map(), pities = [];
  let vObs = 0;
  let expectedDistinct = 0;

  const observedFor = (item) => {
    if (!clog) return { found: true, count: 0, known: false };
    const r = lookupObserved(item, clog);
    return { ...r, known: true };
  };

  for (const item of items) {
    if (item.type === 'free') {
      let count = 0, found = true;
      if (clog) { const r = lookupObserved(item, clog); count = r.count; found = r.found; }
      let expectedHave = 1;
      if (item.kind === 'milestone') expectedHave = item.milestoneAt && total >= item.milestoneAt ? 1 : 0;
      // shared items also drop elsewhere: never scored, and neutral in the expected-vs-have comparison
      if (item.kind === 'shared') expectedHave = count > 0 ? 1 : 0;
      base.free.push({ name: item.name, kind: item.kind, count, found, expected: expectedHave, at: item.milestoneAt || null, sharedWith: item.sharedWith || null });
      if (found || !clog) expectedDistinct += expectedHave;
      continue;
    }

    const obs = observedFor(item);
    if (clog && !obs.found && clog.listComplete) {
      base.warnings.push(`"${item.name}" is in the model but Temple did not list it for this category; it was left out of the luck score.`);
      continue;
    }
    const count = obs.count;
    const cap = item.max || 0;
    const capped = cap ? Math.min(count, cap) : count;

    if (item.type === 'plain') {
      const srcs = [];
      let lambda = 0, logNone = 0;
      for (const s of srcKeys) {
        const p = item.rates[s] || 0;
        if (p > 0 && nBy[s] > 0) {
          srcs.push(makeBinomial(nBy[s], p));
          lambda += nBy[s] * p;
          logNone += nBy[s] * Math.log1p(-p);
        }
      }
      if (lambda <= 0) {
        if (count > 0) base.warnings.push(`"${item.name}" was obtained but the model expects none from the KC found; check kill counts.`);
        continue;
      }
      const p1 = 1 - Math.exp(logNone);
      const w = Math.max(1, Math.round(10 * Math.sqrt(total / lambda)));
      plain.push({ srcs, cap, w });
      vObs += capped * w;
      expectedDistinct += p1;
      base.items.push({
        name: item.name, kind: 'plain', perKc: lambda / total, expected: lambda,
        observed: count, pHave: p1, pAtLeast: cap ? (count >= 1 ? p1 : 1) : poissonAtLeast(count, lambda),
        max: cap || null, weight: w / 10,
      });
    } else if (item.type === 'group') {
      let g = groupMap.get(item.group);
      if (!g) {
        const gdef = groups[item.group];
        const srcs = [];
        let lambda = 0;
        for (const s of srcKeys) {
          const R = (gdef.rates[s] || 0);
          if (R > 0 && nBy[s] > 0) { srcs.push(makeBinomial(nBy[s], R)); lambda += nBy[s] * R; }
        }
        g = { srcs, lambda, items: [] };
        groupMap.set(item.group, g);
      }
      if (g.lambda <= 0) continue;
      const w = Math.max(1, Math.round(10 * Math.sqrt(item.needs * total / g.lambda)));
      g.items.push({ needs: item.needs, w });
      if (count > 0) vObs += w;
      const p1 = poissonAtLeast(item.needs, g.lambda);
      expectedDistinct += p1;
      base.items.push({
        name: item.name, kind: 'group', perKc: g.lambda / total, expected: g.lambda / item.needs,
        observed: count, pHave: p1, pAtLeast: count > 0 ? p1 : 1, max: 1, weight: w / 10, needs: item.needs,
      });
    } else if (item.type === 'pity') {
      const p1 = pityProbability(item.pity, total);
      const wait = pityMeanWait(item.pity);
      const w = Math.max(1, Math.round(10 * Math.sqrt(wait)));
      pities.push({ p: p1, w });
      if (count > 0) vObs += w;
      expectedDistinct += p1;
      base.items.push({
        name: item.name, kind: 'pity', perKc: 1 / wait, expected: p1,
        observed: count, pHave: p1, pAtLeast: count > 0 ? p1 : 1, max: 1, weight: w / 10,
      });
    }
  }

  base.expectedSlots = expectedDistinct;
  const groupList = [...groupMap.values()].filter((g) => g.items.length);
  const hasRandom = plain.length || groupList.length || pities.length;
  if (!hasRandom) { base.model = 'no-rng'; return base; }
  if (!clog) return base;

  const rng = mulberry32(seed);
  const sims = new Float64Array(N);
  for (let i = 0; i < N; i++) {
    let v = 0;
    for (let a = 0; a < plain.length; a++) {
      const c = plain[a];
      let k = 0;
      for (let b = 0; b < c.srcs.length; b++) k += drawBinomial(c.srcs[b], rng);
      if (c.cap && k > c.cap) k = c.cap;
      v += k * c.w;
    }
    for (let a = 0; a < groupList.length; a++) {
      const g = groupList[a];
      let e = 0;
      for (let b = 0; b < g.srcs.length; b++) e += drawBinomial(g.srcs[b], rng);
      for (let b = 0; b < g.items.length; b++) if (e >= g.items[b].needs) v += g.items[b].w;
    }
    for (let a = 0; a < pities.length; a++) if (rng() < pities[a].p) v += pities[a].w;
    sims[i] = v;
  }

  const u = percentileFromSims(sims, vObs);
  const zs = nullZStats(sims);
  base.luck = finishLuck(u, zs, N);
  base.haul = { observed: vObs / 10, median: medianOf(sims) / 10 };
  return base;
}

function medianOf(arr) {
  const s = Float64Array.from(arr).sort();
  return s[Math.floor(s.length / 2)];
}

function finishLuck(u, zs, N) {
  const uc = Math.min(Math.max(u, 0.5 / N), 1 - 0.5 / N);
  const z = normInv(uc);
  const percentile = u * 100;
  return { percentile, z, zMean: zs.mean, zSd: zs.sd, status: statusFor(percentile) };
}

// ---------------------------------------------------------------------------
// overall score across activities
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Overall score (0-100, higher = more spooned)
//
// Each activity gives a standardised luck value s (null mean 0, sd 1, clipped to
// +-3). The account's luck index L is the information-weighted mean of s, so it
// does not grow with the number of activities the way a summed z-score does.
//
// Real accounts are not a random sample from the model: players stop farming a
// boss once they have what they came for, so final hauls lean lucky, and some
// rates/KC are imperfect. BASELINE is the average L seen on the first four real
// test accounts (rough, ~0.8) and TAU the account-to-account spread around it.
// Both are calibration constants, not statistics; re-fit them with more data.
// ---------------------------------------------------------------------------
export const SCORE_BASELINE = 0.8;
export const SCORE_TAU = 0.4;
const CONF_WEIGHT = { high: 1, partial: 0.8, approx: 0.5 };

export function summarize(results, opts = {}) {
  const includeApprox = !!opts.includeApprox;
  let wSum = 0, wsSum = 0, w2Sum = 0, used = 0;
  const bands = { spooned: 0, lucky: 0, 'on-rate': 0, dry: 0, 'very-dry': 0 };
  for (const r of results) {
    if (!r || !r.luck) continue;
    bands[r.luck.status.key]++;
    if (r.confidence === 'approx' && !includeApprox) continue;
    const sd = Math.max(r.luck.zSd, 0.3);
    const s = Math.max(-3, Math.min(3, (r.luck.z - r.luck.zMean) / sd));
    const w = (CONF_WEIGHT[r.confidence] ?? 1) * Math.min(1, sd);
    wSum += w; wsSum += w * s; w2Sum += w * w;
    used++;
  }
  const index = wSum > 0 ? wsSum / wSum : 0;
  const se = wSum > 0 ? Math.sqrt(w2Sum) / wSum : 1;
  const spread = Math.sqrt(se * se + SCORE_TAU * SCORE_TAU);
  const score = Math.round(normCdf((index - SCORE_BASELINE) / spread) * 1000) / 10;
  return { score, index, se, used, bands, spooned: bands.spooned + bands.lucky, dry: bands.dry + bands['very-dry'] };
}

export function analyzeAll(dataset, perActivity, opts = {}) {
  const results = [];
  for (const [id, act] of Object.entries(dataset.activities)) {
    const pa = perActivity[id];
    if (!pa) continue;
    const r = analyzeActivity(act, { id, kc: pa.kc, clog: pa.clog, assumptions: opts.assumptions, sims: opts.sims });
    if (r) results.push(r);
  }
  return results;
}
