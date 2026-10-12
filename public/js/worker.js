import { analyzeAll, summarize } from './engine.js';
import { buildPlayerInputs } from './temple.js';

self.onmessage = (ev) => {
  const { id, dataset, stats, clog, assumptions, includeApprox, sims } = ev.data;
  try {
    const { perActivity, ehc, diagnostics } = buildPlayerInputs(dataset, stats, clog);
    const results = analyzeAll(dataset, perActivity, { assumptions, sims });
    const summary = summarize(results, { includeApprox });
    self.postMessage({ id, ok: true, results, summary, ehc, diagnostics });
  } catch (e) {
    self.postMessage({ id, ok: false, error: String(e && e.message || e) });
  }
};
