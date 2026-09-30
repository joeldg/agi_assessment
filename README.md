# Hidden AGI watch

A daily, calibrated assessment of four hypotheses about advanced AI, published with GitHub Pages at <https://joeldg.github.io/agi_assessment/>:

- **A**: AGI has been achieved but not publicly disclosed.
- **B**: recursive self-improvement (RSI) has been achieved in secret.
- **C**: an AGI-level system is operating autonomously online or in the economy without public knowledge.
- **D**: an AGI-level system is influencing government decisions or world affairs. The dashboard splits this into covert influence (D) and influence through open, acknowledged use (D-open).

A scheduled Claude routine updates the site once a day. Each run searches current news, research and evaluations, reassesses the hypotheses, and adds a news roundup.

## Layout

| Path | What it holds |
| --- | --- |
| `index.html`, `assets/app.js` | The daily dashboard: Hidden AGI Index dial, what moved the needle, tripwires, readings, trend chart, roundup, history. It reads `data/runs.json` in the browser. |
| `assets/charts.js`, `assets/style.css` | The one chart kit and stylesheet for every page. `style.html` is the chart style guide: validated palette, rules and live examples. |
| `data/runs.json` | One entry per daily run: `probs` (A, B, C, D, Dopen → now/y2030/y2035/conf), `agi` (strict AGI exists: now/y2030/y2035/conf), `index`, `indexNote`, `needle`, `tripwires`, summary, changes, `roundup`, timeline, signals, sources, report link. |
| `reports/YYYY-MM-DD.html` | The full daily report: index, needle, probability table, tripwires, timeline, news roundup, Steps 1–6, bottom line. |
| `cards/` | 1200×630 share cards (`YYYY-MM-DD.png`, `latest.png`, `weekly-YYYY-MM-DD.png`), used for link previews and at the top of emails. |
| `start-here.html`, `scorecard.html`, `disclosure-lag.html`, `agi-claims.html`, `calendar.html`, `steelman.html` | Standing sections, rendered in the browser from `data/forecasts.json`, `data/incidents.json`, `data/agi_claims.json`, `data/calendar.json` and `data/steelman.json`. Updated weekly. |
| `trends.html`, `data/trends.json`, `scripts/update_trends.py` | Trend watch: METR time horizons pulled from METR's published data, fitted and projected with a 95% band and threshold-crossing dates, plus hand-curated series (AI share of AI R&D). |
| `alarm.html`, `data/alarm.json` | The fire alarm: four levels (Normal, Watch, Warning, Alarm), published triggers and rules, current status, public history and changelog. `scripts/kit_broadcast.py --alarm` drafts a breaking alert on a level change (always a draft for the owner). |
| `data/gauges.json` | Definitions of the four gauges (capability gap, AI doing AI research, oversight gap, delegation to AI). Daily readings live in `data/runs.json` → `gauges`. |
| `data/external_forecasts.json` | Outside AGI forecasts (Metaculus, markets, AI Futures, lab leaders), plotted as rings on the dashboard forecast chart. |
| `weekly/`, `data/weekly/` | Friday wrap-ups: `data/weekly/YYYY-MM-DD.json` (editorial plus computed key numbers) → `weekly/YYYY-MM-DD.html`. `data/weekly/index.json` lists them. |
| `feed.xml`, `sitemap.xml` | RSS feed and sitemap. Generated; do not hand-edit. |
| `scripts/build_feed.py` | Rebuilds `feed.xml` and `sitemap.xml`, and defines the daily email body. |
| `scripts/render_card.py` | Renders share cards with headless Chrome. |
| `scripts/build_pages.py`, `scripts/sitekit.py` | Generate the standing pages and the style guide from one page shell. Rerun only when their layout or copy changes. |
| `scripts/build_weekly.py` | Builds a wrap-up page and card, and defines the weekly email body. |
| `scripts/kit_broadcast.py` | Pushes the daily issue (`--send-at 10am`) or the weekly wrap-up (`--weekly DATE --send-at 3pm`) to Kit through its API. Needs `KIT_API_KEY` / `KIT_API_SECRET`. Records pushes in `data/kit_broadcasts.json`. |
| `assets/brand/` | Avatar, favicon and share image. |

## Daily update procedure (09:02 Pacific)

1. Read `data/runs.json` and the latest report, then research the news since the last run.
2. Re-check the fire-alarm triggers (`data/alarm.json`), then decide the index, the needle (or a quiet day), the four gauge readings and each tripwire's status. If the alarm level changes, draft a breaking alert with `kit_broadcast.py --alarm`; never send it.
3. Write `reports/<today>.html`, following the previous report's structure.
4. Append the day's entry to `data/runs.json`.
5. Run `python3 scripts/render_card.py`, then `python3 scripts/build_feed.py`.
6. Commit and push to `main`.
7. Run `python3 scripts/kit_broadcast.py --send-at 10am` (via `zsh -ic` so the keys load), then commit `data/kit_broadcasts.json`.

## Weekly wrap-up (Fridays: built about 1pm, emailed at 3pm Pacific)

1. Update `data/forecasts.json` (resolve due forecasts; add new ones; never edit a made forecast), `data/incidents.json`, `data/agi_claims.json`, `data/calendar.json`, `data/external_forecasts.json`; run `python3 scripts/update_trends.py`; add a new entry to `data/steelman.json`.
2. Write `data/weekly/<today>.json` (headline, summary, moves, section notes).
3. Run `python3 scripts/build_weekly.py <today>`, then `python3 scripts/build_feed.py`. Commit and push.
4. Run `python3 scripts/kit_broadcast.py --weekly <today> --send-at 3pm`.

Feed URL: <https://joeldg.github.io/agi_assessment/feed.xml>
Sitemap URL: <https://joeldg.github.io/agi_assessment/sitemap.xml>

Probabilities are subjective estimates. The reports are not investment, policy or security advice.
