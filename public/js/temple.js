// TempleOSRS response parsing + client.
//
// The browser talks to our own /api/* Pages Functions, which proxy Temple (CORS,
// caching and a proper User-Agent). The parsers are deliberately tolerant about
// response shape and report anything they could not match instead of guessing.

import { norm } from './engine.js';

// Category keys Temple may use differently from ours (carried over from the old app).
export const CLOG_KEY_ALIASES = {
  the_nightmare: ['nightmare'],
  duke_sucellus: ['duke_sucellus'],
  the_whisperer: ['whisperer'],
  the_leviathan: ['leviathan'],
  the_gauntlet: ['gauntlet'],
  hueycoatl: ['the_hueycoatl'],
  royal_titans: ['the_royal_titans'],
  dagannoth_kings: ['dagganoth_kings'],
  the_fight_caves: ['fight_caves'],
  the_inferno: ['inferno'],
  sol_heredit: ['fortis_colosseum', 'colosseum'],
};

export function parseStats(json) {
  const data = (json && (json.data ?? json)) || {};
  const map = new Map();
  for (const [k, v] of Object.entries(data)) {
    const n = typeof v === 'number' ? v : (typeof v === 'string' && v.trim() !== '' && !isNaN(+v) ? +v : null);
    if (n == null) continue;
    map.set(norm(k), n);
  }
  return map;
}

// kill counts per source for one activity: first alias that has a positive KC wins
export function kcForActivity(act, statsMap) {
  const out = {};
  for (const [src, aliases] of Object.entries(act.sources)) {
    let n = 0;
    for (const a of aliases) {
      const v = statsMap.get(norm(a));
      if (v != null && v > 0) { n = Math.floor(v); break; }
    }
    out[src] = n;
  }
  return out;
}

function entryName(e) {
  return e.name ?? e.item_name ?? e.itemName ?? e.item ?? null;
}
function entryCount(e) {
  const v = e.count ?? e.quantity ?? e.qty ?? e.obtained ?? 0;
  return typeof v === 'number' ? v : (+v || 0);
}

// Normalise whatever Temple sent for one category into
// { counts: Map(normName -> count), obtained, total, listComplete }
export function parseClogCategory(json, categoryId) {
  const root = (json && (json.data ?? json)) || {};
  const itemsRoot = root.items ?? root.collection ?? root.categories ?? root;
  const keys = [categoryId, ...(CLOG_KEY_ALIASES[categoryId] || [])];
  let raw;
  for (const k of keys) { if (itemsRoot && itemsRoot[k] !== undefined) { raw = itemsRoot[k]; break; } }
  const missingRoot = root.missing_items ?? root.missing ?? null;
  let missingRaw;
  if (missingRoot) for (const k of keys) { if (missingRoot[k] !== undefined) { missingRaw = missingRoot[k]; break; } }

  if (raw === undefined && missingRaw === undefined) return null;

  const counts = new Map();
  let anyZero = false, hadNames = false;
  const take = (list, forceZero) => {
    const arr = Array.isArray(list) ? list : (list && typeof list === 'object' ? Object.values(list) : []);
    for (const e of arr) {
      if (!e || typeof e !== 'object') continue;
      const name = entryName(e);
      if (!name) continue;
      hadNames = true;
      const c = forceZero ? 0 : entryCount(e);
      if (c === 0) anyZero = true;
      const key = norm(name);
      counts.set(key, Math.max(counts.get(key) || 0, c));
    }
  };

  // a category can also be the legacy {obtained: n, total: n} shape from older responses
  if (raw && !Array.isArray(raw) && typeof raw === 'object' && ('obtained' in raw) && !hadNames) {
    return { counts, obtained: +raw.obtained || 0, total: +raw.total || null, listComplete: false, namesAvailable: false, legacy: true };
  }

  take(raw, false);
  if (missingRaw !== undefined) take(missingRaw, true);

  let obtained = 0;
  for (const c of counts.values()) if (c > 0) obtained++;
  const listComplete = hadNames && (anyZero || missingRaw !== undefined);
  return {
    counts, obtained,
    total: listComplete ? counts.size : null,
    listComplete,
    namesAvailable: hadNames,
  };
}

export function parseEhc(json) {
  const root = (json && (json.data ?? json)) || {};
  const v = root.ehc ?? root.total_ehc ?? null;
  return typeof v === 'number' ? v : (v != null && !isNaN(+v) ? +v : null);
}

// ---- client (browser) ----
export function categoriesParam(dataset) {
  const ids = new Set(Object.keys(dataset.activities));
  for (const id of Object.keys(dataset.activities)) for (const a of CLOG_KEY_ALIASES[id] || []) ids.add(a);
  return [...ids].join(',');
}

async function getJson(url) {
  const res = await fetch(url, { headers: { Accept: 'application/json' } });
  let body = null;
  try { body = await res.json(); } catch { /* ignore */ }
  if (!res.ok) {
    const msg = (body && (body.error || body.message)) || `HTTP ${res.status}`;
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return body;
}

export async function fetchPlayer(name, dataset) {
  const q = encodeURIComponent(name);
  const [stats, clog] = await Promise.all([
    getJson(`/api/stats?player=${q}`),
    getJson(`/api/clog?player=${q}&categories=${encodeURIComponent(categoriesParam(dataset))}`).catch((e) => ({ __error: e.message })),
  ]);
  return { stats, clog };
}

// Build the per-activity input the engine expects from raw API payloads.
export function buildPlayerInputs(dataset, stats, clog) {
  const statsMap = parseStats(stats);
  const perActivity = {};
  const diagnostics = { clogError: clog && clog.__error ? clog.__error : null, noNames: [], noCategory: [] };
  for (const [id, act] of Object.entries(dataset.activities)) {
    const kc = kcForActivity(act, statsMap);
    if (!Object.values(kc).some((n) => n > 0)) continue;
    let cat = null;
    if (clog && !clog.__error) {
      cat = parseClogCategory(clog, id);
      if (!cat) diagnostics.noCategory.push(id);
      else if (!cat.namesAvailable && !cat.legacy) diagnostics.noNames.push(id);
    }
    perActivity[id] = { kc, clog: cat };
  }
  return { perActivity, ehc: clog && !clog.__error ? parseEhc(clog) : null, diagnostics };
}
