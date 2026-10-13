import { STATUS_BANDS } from './engine.js';
import { fetchPlayer } from './temple.js';

const $ = (s) => document.querySelector(s);
const LS = 'dry-calc-v3';
let dataset = null;
const players = new Map();
let active = null;
let filter = 'all';
let sortBy = 'luck';

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = (n, d = 1) => (n == null || Number.isNaN(n) ? '–' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d }));
const bandFor = (pct) => STATUS_BANDS.find((b) => pct >= b.min) || STATUS_BANDS[STATUS_BANDS.length - 1];
const toneClass = (pct) => `tone-${bandFor(pct).key}`;

function load() {
  try {
    const s = JSON.parse(localStorage.getItem(LS) || '{}');
    if (s.players) $('#players').value = s.players;
    if (s.approx) $('#approx').checked = true;
  } catch { /* storage unavailable */ }
}
function save() {
  try { localStorage.setItem(LS, JSON.stringify({ players: $('#players').value, approx: $('#approx').checked })); } catch { /* ignore */ }
}

function assumptions() {
  const n = (id) => +$(id).value;
  return {
    cox: { points: n('#cox-points'), cmPoints: n('#cox-cm') },
    tob: { teamSize: n('#tob-team') },
    toa: { normal: { raidLevel: n('#toa-n-rl'), points: n('#toa-n-pts') }, expert: { raidLevel: n('#toa-e-rl'), points: n('#toa-e-pts') } },
  };
}

function analyse(payload) {
  return new Promise((resolve, reject) => {
    const w = new Worker(new URL('./worker.js', import.meta.url), { type: 'module' });
    w.onmessage = (e) => { w.terminate(); e.data.ok ? resolve(e.data) : reject(new Error(e.data.error)); };
    w.onerror = (e) => { w.terminate(); reject(new Error(e.message || 'Calculation failed')); };
    w.postMessage(payload);
  });
}

function setStatus(msg, tone) { const el = $('#status'); el.textContent = msg; el.dataset.tone = tone || ''; }

async function run(ev) {
  ev?.preventDefault();
  save();
  const names = [...new Set($('#players').value.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean))].slice(0, 12);
  if (!names.length) { setStatus('Enter at least one username.', 'error'); return; }
  if (!dataset) { setStatus('Drop data is still loading. Try again in a moment.', 'error'); return; }
  $('#run').disabled = true;
  players.clear();
  for (const [i, name] of names.entries()) {
    setStatus(`Scoring ${name} (${i + 1} of ${names.length})…`);
    try {
      const { stats, clog } = await fetchPlayer(name, dataset);
      players.set(name, await analyse({ id: name, dataset, stats, clog, assumptions: assumptions(), includeApprox: $('#approx').checked, sims: 20000 }));
    } catch (e) {
      players.set(name, { error: friendly(e.message) });
    }
  }
  setStatus('');
  $('#run').disabled = false;
  active = [...players].filter(([, v]) => !v.error).sort((a, b) => (b[1].summary.score ?? -1) - (a[1].summary.score ?? -1))[0]?.[0] || null;
  render();
  $('#board').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function friendly(msg) {
  if (/not found/i.test(msg)) return 'Not found on TempleOSRS. Check the spelling, or visit templeosrs.com to add and update the player.';
  return msg;
}

function strip(results, big) {
  const scored = results.filter((r) => r.luck);
  const dots = scored.map((r, i) => {
    const p = r.luck.percentile;
    const top = 50 + ((i % 5) - 2) * (big ? 9 : 7) - 8;
    return `<span class="strip__dot ${toneClass(p)}" style="left:${p}%;top:${top}%" title="${esc(r.name)}: ${fmt(p, 0)}th percentile"></span>`;
  }).join('');
  return `<div class="strip ${big ? 'strip--lg' : ''}" role="img" aria-label="Each dot is one activity, placed from dry on the left to spooned on the right"><span class="strip__mid"></span><span class="strip__axis"></span>${dots}<span class="strip__ends"><span>Dry</span><span>Spooned</span></span></div>`;
}

function render() {
  const ok = [...players].filter(([, v]) => !v.error).sort((a, b) => (b[1].summary.score ?? -1) - (a[1].summary.score ?? -1));
  const bad = [...players].filter(([, v]) => v.error);
  $('#board').hidden = false;
  $('#ladder').innerHTML = ok.map(([n, v], i) => `
    <li><button class="ladder__row" data-p="${esc(n)}" ${n === active ? 'aria-current="true"' : ''}>
      <span class="ladder__rank">${i + 1}</span>
      <span class="ladder__name">${esc(n)}<span class="ladder__meta">${v.summary.used ? `${v.summary.used} activities` : noData(v)}${v.ehc ? ` · ${fmt(v.ehc, 0)} EHC` : ''}</span></span>
      ${strip(v.results)}
      <span class="score"><span class="score__n">${fmt(v.summary.score, 0)}</span><span class="score__l">spoon score</span></span>
    </button></li>`).join('');
  $('#failed').innerHTML = bad.map(([n, v]) => `<li><b>${esc(n)}</b>: ${esc(v.error)}</li>`).join('');
  renderPlayer();
}

function noData(v) {
  if (v.diagnostics?.clogError) return 'Collection log unavailable';
  return v.results.length ? 'No collection log synced to Temple' : 'No tracked boss kills';
}

function renderPlayer() {
  const v = players.get(active);
  $('#player').hidden = !v || !!v.error;
  if (!v || v.error) return;
  const s = v.summary;
  const d = v.diagnostics || {};
  $('#player-head').innerHTML = `
    <div><h2 class="player__name">${esc(active)}</h2>
    <p class="player__facts"><b>${s.spooned}</b> spooned or lucky · <b>${s.bands['on-rate']}</b> on rate · <b>${s.dry}</b> dry or very dry</p></div>
    <div class="score"><span class="score__n">${fmt(s.score, 0)}</span><span class="score__l">spoon score</span></div>
    <div class="player__strip">${strip(v.results, true)}</div>
    ${d.clogError ? `<div class="notice player__strip">Collection log unavailable (${esc(d.clogError)}). Showing expected drops only.</div>` : ''}`;
  const rows = v.results.filter((r) => filter === 'all' || r.type === filter);
  const key = (r) => (r.luck ? r.luck.percentile : 50);
  rows.sort((a, b) => (sortBy === 'luck' ? key(b) - key(a) : sortBy === 'dry' ? key(a) - key(b) : b.kcTotal - a.kcTotal));
  $('#rows').innerHTML = `<div class="rows__head"><span>Activity</span><span class="num">Kills</span><span class="num">Log</span><span class="num">Expected</span><span>Luck percentile</span><span>Verdict</span></div>`
    + (rows.length ? rows.map(row).join('') : '<p class="empty">No activities with kills in this category.</p>');
}

function row(r) {
  const kc = fmt(r.kcTotal, 0);
  const slots = r.slots ? `${r.slots.obtained}${r.slots.total ? '/' + r.slots.total : ''}` : '–';
  const p = r.luck ? r.luck.percentile : null;
  const tag = r.confidence === 'partial' ? '<span class="tag">partial</span>' : r.confidence === 'approx' ? '<span class="tag">rough</span>' : '';
  const meter = p == null ? '<span class="muted">Not scored</span>'
    : `<div class="meter ${toneClass(p)}"><span class="meter__zone"></span><span class="meter__mark" style="left:${p}%"></span></div><div class="meter__val">${fmt(p, 1)}</div>`;
  const verdict = p == null ? '<span class="muted">–</span>' : `<span class="pill ${toneClass(p)}"><span class="pill__dot"></span>${bandFor(p).label}</span>`;
  return `<details class="act"><summary><div class="act__main">
    <span class="act__name">${esc(r.name)} ${tag}</span>
    <span class="num act__kc">${kc}</span><span class="num act__log">${slots}</span><span class="num act__exp">${r.expectedSlots != null ? fmt(r.expectedSlots) : '–'}</span>
    <span class="meter-cell">${meter}</span><span>${verdict}</span></div></summary>${breakdown(r)}</details>`;
}

function breakdown(r) {
  let h = '<div class="act__body">';
  if (Object.keys(r.kc).length > 1) h += `<p class="muted">Kills by source: ${Object.entries(r.kc).filter(([, n]) => n > 0).map(([s, n]) => `${esc(s)} ${fmt(n, 0)}`).join(', ')}</p>`;
  if (r.note) h += `<p class="muted">${esc(r.note)}</p>`;
  for (const w of r.warnings) h += `<p class="warn">${esc(w)}</p>`;
  if (r.items.length) {
    h += '<table><thead><tr><th>Item</th><th class="n">Rate</th><th class="n">Expected</th><th class="n">Have</th><th class="n">Chance of having this many</th></tr></thead><tbody>';
    for (const i of r.items) h += `<tr><td>${esc(i.name)}</td><td class="n">1/${fmt(1 / (i.perKc || 1e-9), 0)}</td><td class="n">${fmt(i.expected, 2)}</td><td class="n">${i.observed ?? '–'}</td><td class="n">${i.pAtLeast == null ? '–' : fmt(i.pAtLeast * 100, 1) + '%'}</td></tr>`;
    h += '</tbody></table>';
  }
  const shared = r.free.filter((x) => x.kind === 'shared');
  const other = r.free.filter((x) => x.kind !== 'shared');
  if (shared.length) h += `<p class="muted">Also drop elsewhere, so not scored: ${shared.map((x) => `${esc(x.name)}${x.count ? ` (have ${fmt(x.count, 0)})` : ''}${x.sharedWith ? ` – ${esc(x.sharedWith)}` : ''}`).join('; ')}.</p>`;
  if (other.length) h += `<p class="muted">Not counted as luck: ${other.map((x) => esc(x.name) + (x.at ? ` (${x.at} kills)` : '')).join(', ')}.</p>`;
  if (r.wiki) h += `<p><a href="${esc(r.wiki)}" target="_blank" rel="noopener">Drop table on the wiki</a></p>`;
  return h + '</div>';
}

document.addEventListener('click', (e) => {
  const a = e.target.closest('[data-p]');
  if (a) { active = a.dataset.p; render(); $('#player').scrollIntoView({ behavior: 'smooth', block: 'start' }); }
});
function seg(id, attr, apply) {
  $(id).addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    apply(b.dataset[attr]);
    for (const x of $(id).querySelectorAll('button')) x.setAttribute('aria-pressed', String(x === b));
    renderPlayer();
  });
}
seg('#filter', 'f', (v) => { filter = v; });
seg('#sort', 's', (v) => { sortBy = v; });
$('#form').addEventListener('submit', run);
$('#players').addEventListener('input', save);
$('#approx').addEventListener('change', save);
$('#toggle-assume').addEventListener('click', (e) => {
  const open = $('#assume').hidden;
  $('#assume').hidden = !open;
  e.currentTarget.setAttribute('aria-expanded', String(open));
});

load();
fetch('data/activities.json').then((r) => r.json()).then((d) => { dataset = d; }).catch(() => setStatus('Could not load drop data. Refresh the page to try again.', 'error'));
