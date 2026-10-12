import { STATUS_BANDS } from './engine.js';
import { fetchPlayer } from './temple.js';

const $ = (s) => document.querySelector(s);
const LS = 'dry-calc-v2';
let dataset = null;
const players = new Map(); // name -> {results, summary, ehc, diagnostics} | {error}
let active = null;

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = (n, d = 1) => (n == null || Number.isNaN(n) ? '–' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d }));

function load() {
  try { const s = JSON.parse(localStorage.getItem(LS) || '{}'); if (s.players) $('#players').value = s.players; if (s.approx) $('#approx').checked = true; } catch { /* ignore */ }
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
    w.onerror = (e) => { w.terminate(); reject(new Error(e.message || 'Worker failed')); };
    w.postMessage(payload);
  });
}

async function run() {
  save();
  const names = [...new Set($('#players').value.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean))].slice(0, 12);
  if (!names.length) { $('#status').textContent = 'Enter at least one player.'; return; }
  $('#run').disabled = true;
  players.clear();
  for (const [i, name] of names.entries()) {
    $('#status').textContent = `Analysing ${name} (${i + 1}/${names.length})…`;
    try {
      const { stats, clog } = await fetchPlayer(name, dataset);
      const out = await analyse({ id: name, dataset, stats, clog, assumptions: assumptions(), includeApprox: $('#approx').checked, sims: 20000 });
      players.set(name, out);
    } catch (e) {
      players.set(name, { error: e.message });
    }
  }
  $('#status').textContent = '';
  $('#run').disabled = false;
  active = names[0];
  render();
}

function render() {
  const ok = [...players].filter(([, v]) => !v.error).sort((a, b) => a[1].summary.score - b[1].summary.score);
  const bad = [...players].filter(([, v]) => v.error);
  $('#leaderboard').hidden = false;
  $('#lb tbody').innerHTML = ok.map(([n, v], i) => {
    const b = statusLabel(v.summary.percentile);
    return `<tr><td>${i + 1}</td><td><a href="#" data-p="${esc(n)}">${esc(n)}</a></td><td><strong>${fmt(v.summary.score)}</strong></td><td>${b} ${fmt(v.summary.percentile, 0)}%</td><td>${v.summary.used}</td><td>${v.summary.spooned}</td><td>${v.summary.dry}</td><td>${fmt(v.ehc, 0)}</td></tr>`;
  }).join('') + bad.map(([n, v]) => `<tr><td></td><td>${esc(n)}</td><td colspan="6" class="err">${esc(v.error)}</td></tr>`).join('');
  $('#detail').hidden = !ok.length;
  $('#tabs').innerHTML = ok.map(([n]) => `<button class="${n === active ? 'on' : ''}" data-p="${esc(n)}">${esc(n)}</button>`).join('');
  renderDetail();
}

function statusLabel(pct) {
  for (const b of STATUS_BANDS) if (pct >= b.min) return `${b.emoji} ${b.label}`;
  return '';
}

function renderDetail() {
  const v = players.get(active);
  if (!v || v.error) { $('#detail-body').innerHTML = ''; return; }
  const f = $('#filter').value;
  const rows = v.results.filter((r) => f === 'all' || r.type === f).sort((a, b) => (a.luck ? a.luck.percentile : 50) - (b.luck ? b.luck.percentile : 50) * 1);
  let html = '';
  const d = v.diagnostics || {};
  if (d.clogError) html += `<p class="warn">Collection log unavailable (${esc(d.clogError)}). Showing expected drops only.</p>`;
  html += '<div class="table-wrap"><table><thead><tr><th>Activity</th><th>KC</th><th>Log</th><th>Expected</th><th>Percentile</th><th>Status</th></tr></thead><tbody>';
  for (const r of rows) {
    const kc = Object.entries(r.kc).filter(([, n]) => n > 0).map(([s, n]) => (Object.keys(r.kc).length > 1 ? `${esc(s)} ${fmt(n, 0)}` : fmt(n, 0))).join(' · ');
    const slots = r.slots ? `${r.slots.obtained}${r.slots.total ? '/' + r.slots.total : ''}` : '–';
    const exp = r.expectedSlots != null ? fmt(r.expectedSlots) : '–';
    const p = r.luck ? r.luck.percentile : null;
    html += `<tr><td><details><summary>${esc(r.name)} ${r.confidence !== 'high' ? `<span class="tag">${esc(r.confidence)}</span>` : ''}</summary>${breakdown(r)}</details></td><td>${kc}</td><td>${slots}</td><td>${exp}</td>`
      + `<td>${p == null ? '–' : `<div class="bar"><i style="left:calc(${p}% - 1px)"></i></div>${fmt(p, 1)}`}</td><td>${r.luck ? esc(statusLabel(p)) : '–'}</td></tr>`;
  }
  html += '</tbody></table></div>';
  $('#detail-body').innerHTML = html;
}

function breakdown(r) {
  let h = '';
  if (r.note) h += `<p class="muted">${esc(r.note)}</p>`;
  for (const w of r.warnings) h += `<p class="warn">${esc(w)}</p>`;
  if (r.items.length) {
    h += '<table class="sub-table"><tr><th>Item</th><th>Rate/kill</th><th>Expected</th><th>Have</th><th>P(≥ have)</th></tr>';
    for (const i of r.items) h += `<tr><td>${esc(i.name)}</td><td>1/${fmt(1 / (i.perKc || 1e-9), 0)}</td><td>${fmt(i.expected, 2)}</td><td>${i.observed ?? '–'}</td><td>${i.pAtLeast == null ? '–' : fmt(i.pAtLeast * 100, 1) + '%'}</td></tr>`;
    h += '</table>';
  }
  if (r.free.length) h += `<p class="muted">Not counted as luck: ${r.free.map((x) => esc(x.name) + (x.at ? ` (${x.at} KC)` : '')).join(', ')}</p>`;
  if (r.wiki) h += `<p><a href="${esc(r.wiki)}" target="_blank" rel="noopener">Wiki</a></p>`;
  return h;
}

document.addEventListener('click', (e) => {
  const a = e.target.closest('[data-p]');
  if (a) { e.preventDefault(); active = a.dataset.p; render(); }
});
$('#run').addEventListener('click', run);
$('#filter').addEventListener('change', renderDetail);
$('#players').addEventListener('input', save);

load();
fetch('data/activities.json').then((r) => r.json()).then((d) => { dataset = d; }).catch(() => { $('#status').textContent = 'Failed to load activity data.'; $('#run').disabled = true; });
