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
| `index.html`, `assets/` | The dashboard. It is static and reads `data/runs.json` in the browser. |
| `data/runs.json` | One entry per daily run: probabilities, confidence, summary, changes, news roundup (grouped by topic), timeline notes, signals, key sources, report link. |
| `reports/YYYY-MM-DD.html` | The full report for each day, with a news roundup, Steps 1–6 and a bottom line, with every claim cited. |

## Daily update procedure

1. Read `data/runs.json` and the latest report to see the previous reading.
2. Research the news since the last run.
3. Write `reports/<today>.html`, copying the structure of the previous report.
4. Append the day's entry to `data/runs.json`, keeping the same schema. The `probs` keys are `A`, `B`, `C`, `D` and `Dopen`, each with `now`, `y2030` and `y2035` in percent plus `conf`.
5. Commit and push to `main`. Pages deploys from the root of `main`.

Probabilities are subjective estimates. The reports are not investment, policy or security advice.
