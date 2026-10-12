// Raid rate models.
//
// Raid uniques are not a flat per-kill rate: they depend on points, raid level,
// team size and mode. We turn those into a per-completion probability for every
// item (per KC source, i.e. per mode) using the wiki's formulas. The inputs that
// the game doesn't tell us (typical points, raid level, team size) are explicit
// assumptions the user can change in the UI.

export const DEFAULT_ASSUMPTIONS = {
  cox: { points: 26025, cmPoints: 26025, cmTimedShare: 0.5 },
  tob: { teamSize: 4 },
  toa: {
    normal: { raidLevel: 250, points: 20000 },
    expert: { raidLevel: 350, points: 30000 },
  },
};

export function mergeAssumptions(user) {
  const d = DEFAULT_ASSUMPTIONS;
  const u = user || {};
  return {
    cox: { ...d.cox, ...(u.cox || {}) },
    tob: { ...d.tob, ...(u.tob || {}) },
    toa: {
      normal: { ...d.toa.normal, ...((u.toa || {}).normal || {}) },
      expert: { ...d.toa.expert, ...((u.toa || {}).expert || {}) },
    },
  };
}

const clamp01 = (x) => Math.max(0, Math.min(1, x));

function weightFor(item, src) {
  const w = item.weight;
  if (w == null) return 0;
  return typeof w === 'number' ? w : (w[src] || 0);
}

function totalWeight(act, src) {
  return act.items.reduce((s, it) => s + weightFor(it, src), 0);
}

// Scaled raid level used by the unique-chance formula in Tombs of Amascut.
export function toaScaledLevel(rl) {
  if (rl <= 310) return rl;
  if (rl <= 430) return 310 + (rl - 310) / 3;
  return 350 + (rl - 430) / 6;
}
function toaPetLevel(rl) {
  if (rl <= 400) return rl;
  if (rl <= 550) return 400 + (rl - 400) / 3;
  return 450;
}

// Per-completion unique probability for the whole table, by source (mode).
export function uniqueChance(act, assumptionsIn) {
  const a = mergeAssumptions(assumptionsIn);
  const out = {};
  if (act.raid === 'cox') {
    out.normal = clamp01(Math.min(a.cox.points / 8676, 65.7) / 100);
    out.cm = clamp01(Math.min(a.cox.cmPoints / 8676, 65.7) / 100);
  } else if (act.raid === 'tob') {
    const team = Math.max(1, a.tob.teamSize);
    out.normal = clamp01(1 / 9.1 / team);
    out.hard = clamp01(1 / 7.7 / team);
  } else if (act.raid === 'toa') {
    for (const mode of ['normal', 'expert']) {
      const { raidLevel, points } = a.toa[mode];
      const bracket = Math.max(1000, 10500 - 20 * toaScaledLevel(raidLevel));
      out[mode] = clamp01(Math.min(points / bracket / 100, 0.55));
    }
  }
  return out;
}

// Returns { items, groups } in the same resolved shape the engine uses for
// ordinary bosses: items carry numeric per-source probabilities.
export function resolveRaidItems(act, assumptionsIn) {
  const a = mergeAssumptions(assumptionsIn);
  const srcs = Object.keys(act.sources);
  const u = uniqueChance(act, a);
  const items = [];

  for (const it of act.items) {
    const base = {
      name: it.name,
      aliases: it.alias || [],
      kind: it.kind || 'rng',
      max: it.max,
      milestoneAt: it.at,
    };

    if (it.kind && it.kind !== 'rng') { items.push({ ...base, type: 'free' }); continue; }

    if (it.pity) {
      items.push({ ...base, type: 'pity', pity: it.pity });
      continue;
    }

    const rates = {};
    if (it.weight != null) {
      for (const s of srcs) {
        const W = totalWeight(act, s);
        const w = weightFor(it, s);
        rates[s] = W > 0 && w > 0 ? (u[s] || 0) * (w / W) : 0;
      }
    } else if (it.special) {
      for (const s of srcs) rates[s] = specialRate(act, it.special, s, u, a);
    }
    items.push({ ...base, type: 'plain', rates });
  }
  return { items, groups: {} };
}

function specialRate(act, special, src, u, a) {
  switch (special) {
    case 'olmlet': return (u[src] || 0) / 53;
    case 'cmDust': return src === 'cm' ? a.cox.cmTimedShare / 400 : 0;
    case 'cmKit': return src === 'cm' ? a.cox.cmTimedShare / 75 : 0;
    case 'zik': return src === 'hard' ? 1 / 500 : 1 / 650;
    case 'hmDust': return src === 'hard' ? 1 / 275 : 0;
    case 'hmSangKit': return src === 'hard' ? 1 / 150 : 0;
    case 'hmHolyKit': return src === 'hard' ? 1 / 100 : 0;
    case 'toaPet': {
      const { raidLevel, points } = a.toa[src] || a.toa.normal;
      const bracket = Math.max(50000, 350000 - 700 * toaPetLevel(raidLevel));
      return clamp01(points / bracket / 100);
    }
    default: return 0;
  }
}
