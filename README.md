# Hidden AGI watch

A daily, sourced assessment (aiming for calibration; the track record is on the [scorecard](https://joeldg.github.io/agi_assessment/scorecard.html)) of four hypotheses about advanced AI, published with GitHub Pages at <https://joeldg.github.io/agi_assessment/>:

- **A**: AGI has been achieved but not publicly disclosed.
- **B**: recursive self-improvement (RSI) has been achieved in secret.
- **C**: an AGI-level system is operating autonomously online or in the economy without public knowledge.
- **D**: an AGI-level system is influencing government decisions or world affairs. The dashboard splits this into covert influence (D) and influence through open, acknowledged use (D-open).

These are short labels. The exact definitions (v1.0), the strict AGI bar, the 30-day window for "undisclosed" and what "by 2030" means are on [Start here](https://joeldg.github.io/agi_assessment/start-here.html). Changes to them are dated in `data/method.json`.

A custom AI agent updates the site once a day. Each run searches current news, research and evaluations, reassesses the hypotheses, and adds a news roundup. It publishes automatically; the owner sets the definitions and alarm thresholds and approves every fire-alarm alert.

## Setup

Python 3.9 or newer (the scheduled tasks use the system `python3`). The scripts use only the standard library, except `scripts/update_trends.py`, which needs PyYAML:

```sh
python3 -m pip install --user -r requirements.txt
```

`scripts/render_card.py` needs Google Chrome in /Applications. `scripts/update_sec.py` sends a contact address in its User-Agent, as the SEC requires, taken from `$SEC_CONTACT_EMAIL` or `git config user.email`; it is never written to disk. `scripts/kit_broadcast.py` needs `KIT_API_KEY` or `KIT_API_SECRET` in the environment.

## Layout

| Path | What it holds |
| --- | --- |
| `index.html`, `assets/app.js` | The daily dashboard: fire-alarm level, Hidden AGI Index dial, what moved the needle, the five gauges, tripwires, readings, forecast chart, roundup, history. It reads `data/runs.json` in the browser. |
| `assets/charts.js`, `assets/style.css` | The one chart kit and stylesheet for every page. `style.html` is the chart style guide: validated palette, rules and live examples. |
| `data/runs.json` | One entry per daily reading (fields below). |
| `reports/YYYY-MM-DD.html` | The full daily report: fire-alarm block, index, needle, probability table, five gauges, tripwires, timeline, news roundup, Steps 1–6, bottom line. Each copies the previous report's site shell (head, site nav, alarm banner, footer). A report's path is its feed GUID, so it never changes. |
| `cards/` | 1200×630 share cards (`YYYY-MM-DD.png`, `latest.png`, `weekly-YYYY-MM-DD.png`), used for link previews and in emails. |
| `start-here.html`, `scorecard.html`, `disclosure-lag.html`, `agi-claims.html`, `calendar.html`, `steelman.html` | Standing sections, rendered in the browser from `data/forecasts.json`, `data/incidents.json`, `data/agi_claims.json`, `data/calendar.json` and `data/steelman.json`. Updated weekly. |
| `about.html` | Who runs the site and how it's made, contact (GitHub Issues), the corrections log and how to cite. |
| `trends.html`, `data/trends.json`, `scripts/update_trends.py` | Trend watch: METR time horizons pulled from METR's published data, fitted and projected with a prediction band and threshold-crossing dates, plus hand-curated series (AI share of AI R&D). |
| `alarm.html`, `data/alarm.json` | The fire alarm: four levels (Normal, Watch, Warning, Alarm), published triggers and rules, current status, public history and changelog. The page is static HTML, rebuilt from `data/alarm.json` by `scripts/build_pages.py` on every daily run. |
| `money.html`, `data/money_sources.json`, `data/money.json`, `scripts/update_sec.py`, `scripts/build_money.py` | Follow the money. Quarterly capex for Microsoft, Alphabet, Amazon and Meta is pulled from SEC XBRL filings by `update_sec.py`: it is total capex (all property and equipment, mostly data centers), not an AI-only figure, and is never hand-edited. Nvidia data-center revenue, lab revenue and prediction-market prices are hand-curated with a URL per figure. `build_money.py` derives trailing-12-month totals and a side-by-side view of spending and measured capability, which is context only, not a test for hidden capability (that is alarm trigger X4). |
| `data/gauges.json` | Definitions of the five gauges (capability gap, AI doing AI research, oversight gap, money trail, delegation to AI), each tagged measured, estimated or assessed. Daily readings live in `data/runs.json` → `gauges`. |
| `data/external_forecasts.json` | Outside AGI forecasts (Metaculus, markets, AI Futures, lab leaders), plotted as rings on the dashboard forecast chart where they are comparable. |
| `data/corrections.json` | The public corrections log. Rendered on the About page and carried into the next daily email. |
| `data/method.json` | The method changelog: dated changes to definitions and methods, with reasons. |
| `weekly/`, `data/weekly/` | Friday wrap-ups: `data/weekly/YYYY-MM-DD.json` (editorial, computed key numbers and a frozen chart snapshot) → `weekly/YYYY-MM-DD.html`. `data/weekly/index.json` lists them. |
| `feed.xml`, `sitemap.xml` | RSS feed and sitemap, for feed readers and Search Console. Generated; do not hand-edit. |
| `scripts/build_feed.py` | Rebuilds `feed.xml` and `sitemap.xml`, and defines the daily email body. |
| `scripts/render_card.py` | Renders share cards with headless Chrome. |
| `scripts/build_pages.py`, `scripts/sitekit.py` | Generate the standing pages, the static alarm page, the About page and the style guide from one page shell. |
| `scripts/build_weekly.py` | Builds a wrap-up page and card, and defines the weekly email body. |
| `scripts/check_data.py` | Read-only validator run before every publish: every data file parses, readings are coherent, the latest report has its subscribe boxes, social tags and card, URLs aren't on the aggregator denylist, and frozen data (past readings, made forecasts, append-only logs, past reports) hasn't been edited. |
| `scripts/alarm_check.py` | Read-only fire-alarm arithmetic: the rule level from the met flags, the 30-day hold-down, date crossings, W4's 180-day median and due reviews. The agent still judges the evidence. |
| `scripts/kit_broadcast.py` | Pushes the daily issue (`--date DATE --send-at 10am`), the weekly wrap-up (`--weekly DATE --send-at 3pm`) or a fire-alarm alert (`--alarm`, always a draft) to Kit through its API. It never sends late, checks the site is live before scheduling, holds the issue as a draft on a day the alarm level changes, and records pushes in `data/kit_broadcasts.json` so nothing goes out twice. |
| `requirements.txt` | The one third-party dependency (PyYAML). |
| `assets/brand/` | Avatar, favicon and share image. |

## Data fields

- **`data/runs.json`**, one entry per reading:
  - `date`, `label`, `report`, and `comparable` (false for the quick chat baseline, which is kept for the record but never used for change figures) with a `note`.
  - `probs`: A, B, C, D, Dopen → `now` / `y2030` / `y2035` / `conf`. `agi` (strict AGI exists, public or hidden) has the same fields. The horizons are cumulative: `y2030` means true at any point before 1 Jan 2031.
  - `index` and `indexNote`: the Hidden AGI Index, the probability that at least one of A–D is true now.
  - `needle`: `quiet`, `hypothesis`, `from`, `to`, `subject` (the email subject hook: at most 50 characters, plain words, no hypothesis letters), `headline`, `detail`, `url`.
  - `gauges`: `gap`, `rd`, `oversight`, `money`, `delegation` → `value`, `display`, `note`, `url`, optional `range`.
  - `alarm`: that day's `level` and `met` triggers.
  - `tripwires`: `id`, `hyp`, `signal`, `status` (quiet, watching or tripped), `since`, `note`, `url`, and `trigger`, the alarm trigger it feeds where there is one.
  - `roundup`: `[{topic, items: [{date, text, url, top}]}]`, where `top: true` marks the items the email shows, plus `roundupWindow`.
  - `corrections`: `[{date, page, was, now, url}]`, the corrections from `data/corrections.json` that this day's email carries. `date` is when the correction was made; the email dates the original claim from `page`.
  - `summary`, `changes`, `timeline`, `signals`, `sources`.
- **`data/forecasts.json`**: `id`, `question`, `p`, `made`, `deadline`, `resolution`, `context`, `url`; `market` with `marketAsOf`, `marketSource` and `marketUrl`; optional `tests` (the gauges or alarm triggers a forecast is a proxy for, e.g. `["W2", "gap"]`); `corrections` (`[{date, text, url}]`); `original_context` and `original_url`, the reasoning and source as made, kept when a correction rewrites `context` (the scorecard shows both); `outcome` (true, false, or `"void"` with `voidReason` for a withdrawn forecast) and `resolved`.
- **`data/incidents.json`**: `occurred` (with `occurredApprox`, and the window in `occurredFrom` / `occurredTo` when a date is approximate), `detected` and `detectedBy` (who noticed first), `disclosed`, `foundBy` (who first made it public), `lab`, `note`, `url`, `press`. The file's note gives the inclusion rule.
- **`data/external_forecasts.json`**: `who`, `what`, `date`, `p`, `asOf`, `definition`, `rating`, `url`, plus `bar` (announcement, narrower, stricter, different or own-definition) and `gap`, a line on how it differs from our strict bar.
- **`data/corrections.json`**: `corrections: [{date, page, item, was, now, url, emailed}]`. `emailed` is null until a daily email carries the correction.
- **`data/alarm.json`**: `version`, `published`, `levels`, `evidenceStandard`, `rules`, `groups` (each trigger has `id`, `trigger`, `threshold`, `why`, `met`, `since`, `evidence`, `url`, and optionally `press` (corroborating coverage), `borderline`, `observable`, `watchFrom`), `current`, `history` (`date`, `from`, `to`, `cause`, `triggers`, `cleared`, `note`, `reviewDue`, `review`) and `changelog`.

## Policies

- **Frozen once published.** Past readings, past reports, made forecasts (`p`, `question`, `resolution`, `made`, `deadline`) and the append-only logs (incidents, steelman, corrections, alarm history and changelog) are never edited. `scripts/check_data.py` enforces this against git.
- **Corrections are public.** A wrong claim gets a dated entry in `data/corrections.json`, a dated "Correction" note on the affected report and a correction box in the next daily email. A wrong forecast premise gets a dated entry in that forecast's `corrections`; it is still scored as made.
- **Evidence ratings.** "Verified fact" means a primary source, or two independent credible outlets that were actually opened. Leaked documents, single anonymously sourced reports and "reportedly" items are "credible report". Our own inferences carry no fact tag, and secondhand sources are marked "via".
- **Market prices** come only from the Kalshi and Polymarket public APIs, with the date and bid/ask, never from press coverage.
- **Definitions and alarm criteria** are the owner's call. They change only with a dated, versioned changelog entry, and never while an alarm-level change is being considered.
- **Publishing.** Each run stops if the working tree has uncommitted changes in the files it reads or writes, commits only the paths it names (never `git add -A` or a force-push), and pushes only after `scripts/check_data.py` passes.

## Daily update procedure (runs about 09:00 Pacific; the email goes at 10am)

1. Fetch, and stop if the working tree has uncommitted changes in the files the run reads or writes.
2. Read `data/runs.json` and the latest report, open corrections and reported issues, then research the news since the last run.
3. Run `python3 scripts/alarm_check.py` and re-check the fire-alarm triggers (`data/alarm.json`). Then decide the index, the needle (or a quiet day), the five gauge readings and each tripwire's status. If the alarm level changes, draft a breaking alert with `kit_broadcast.py --alarm`; never send it.
4. Write `reports/<today>.html`, copying the previous report's structure and shell.
5. Add the day's entry to `data/runs.json` (a rerun replaces the same day's entry).
6. Run `python3 scripts/render_card.py --date <today>`, `python3 scripts/build_pages.py`, `python3 scripts/build_feed.py` and `python3 scripts/check_data.py`.
7. Commit the named paths and push to `main`.
8. Run `python3 scripts/kit_broadcast.py --date <today> --send-at 10am` (via `zsh -ic` so the keys load), then commit `data/kit_broadcasts.json`. Drafts, holds and failures are flagged to the owner.

## Weekly wrap-up (Fridays: built about 1pm, emailed at 3pm Pacific)

1. Work out the wrap-up date (the most recent Friday), and stop on a duplicate. A Saturday catch-up is left as a draft; a later one is skipped. Wait for the Friday daily reading if it's still running. Then the same clean-tree check as the daily.
2. Update `data/forecasts.json` (resolve due forecasts; add new ones, at least one a proxy for a gauge or alarm trigger; never edit a made forecast), `data/incidents.json`, `data/agi_claims.json`, `data/calendar.json`, `data/external_forecasts.json`; run `python3 scripts/update_trends.py`; run `python3 scripts/update_sec.py`, add the other money figures to `data/money_sources.json`, then run `python3 scripts/build_money.py`; add a new entry to `data/steelman.json`.
3. Write `data/weekly/<date>.json` (headline, subject, summary, moves, section notes, and any gauge updates for the next daily). The wrap-up never edits a published daily reading or report.
4. Run `python3 scripts/build_weekly.py <date>`, `python3 scripts/build_pages.py`, `python3 scripts/build_feed.py`, `python3 scripts/check_data.py` and a headless smoke check. Commit the named paths and push.
5. Run `python3 scripts/kit_broadcast.py --weekly <date> --send-at 3pm`.

Feed URL: <https://joeldg.github.io/agi_assessment/feed.xml>
Sitemap URL: <https://joeldg.github.io/agi_assessment/sitemap.xml>

Probabilities are subjective estimates. The reports are not investment, policy or security advice.
