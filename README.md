# Dry Calculator

Compares an OSRS player's collection log with the drops they should have by now, using
[TempleOSRS](https://templeosrs.com) data. Static site + two Cloudflare Pages Functions.

## What changed from the Streamlit version
- **Per-item rates** (per kill source / mode) instead of slot-count power curves.
- **Guaranteed drops, commons and KC capes** are listed but never scored as luck.
- **Rarity-weighted haul**: a rare item counts for more than a common one.
- **Monte Carlo null distribution** (20,000 seeded sims, in a Web Worker) gives a mid-p percentile.
- **Groups** for shared pools: Hydra pieces, Araxxor, Abyssal Sire, Vestiges, Moons sets; **pity timers** for blood quartz, Vorkath's head, ToA thread/jewels.
- **Raids** (`public/js/raids.js`): CoX, ToB, ToA unique chances from points / team size / raid level, adjustable in the UI. Shrouds are milestones.
- **Overall score** is a 0–100 *spoon score* (higher = luckier, ~50 typical): the information-weighted mean of per-activity standardised luck, placed on a scale by two calibration constants (`SCORE_BASELINE`, `SCORE_TAU` in `engine.js`, fitted on four real accounts). It no longer grows with the number of activities. The old summed z-score piled almost everyone near the top. The scale differs from the old app.
- **Rarity weights** use the square root of the expected wait, so one pet no longer dominates an activity's haul.
- Fixed a data typo (`dagganoth_kings`).

## Layout
- `public/` – site (`index.html`, `js/engine.js`, `raids.js`, `temple.js`, `worker.js`, `app.js`, `data/activities.json`)
- `functions/api/stats.js`, `clog.js` – Temple proxies (name validation, UA, edge cache 30 min)
- `scripts/check-data.mjs` – validates the dataset and compares computed expected-completion KC to Temple's EKC
- `test/` – calibration (simulated players), parser and function tests

## Develop / deploy
```
npm install
npm test
npm run dev                      # wrangler pages dev on :8788
npx wrangler pages deploy public --project-name dry-calculator
```
Or connect the repo in the Cloudflare dashboard: build command empty, output directory `public`.

## Data confidence and caveats
- Rates were collected 2026-10-12 from wiki pages through lossy fetches. Each activity has `confidence`: `high`, `partial` (some rates from memory), `approx` (equal-rate model calibrated to Temple EKC; excluded from the overall score by default).
- `npm run check-data` shows computed vs Temple EKC. Temple makes its own assumptions, so a mismatch is a prompt to re-check, not proof of an error. Currently notable: Chaos Fanatic, Skotizo, Royal Titans, King Black Dragon, Vardorvis, Zalcano, Fight Caves, Inferno, and raids (mode/team assumptions).
- The Temple collection-log response shape could not be tested against the live API from the build environment. The parser is tolerant and reports unmatched items; if names are missing, luck is not scored for that category.
- Newer bosses (e.g. Doom of Mokhaiotl) are not yet in the dataset. Add them to `activities.json` and run `check-data`.
