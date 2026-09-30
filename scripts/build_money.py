#!/usr/bin/env python3
"""Build data/money.json (the "Follow the money" data) from data/money_sources.json.

    python3 scripts/build_money.py

money_sources.json holds sourced figures only (every value has a URL): quarterly hyperscaler
capex, Nvidia data-center revenue, lab revenue, prediction-market prices. This script derives:
  - combined Big-4 capex per calendar quarter (only quarters where all four have reported),
  - trailing-twelve-month (TTM) capex and its year-on-year growth,
  - spending vs capability, for context only: capex and the best METR-measured frontier 50% time
    horizon released by each quarter end (a step series of measurements, not a fitted curve), both
    indexed to 100 at the first common quarter (one axis, no dual scales).
"""
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC, OUT, TRENDS = ROOT / "data/money_sources.json", ROOT / "data/money.json", ROOT / "data/trends.json"
BIG4 = ["MSFT", "GOOGL", "AMZN", "META"]
SUITE_CAP = 16 * 60     # METR: measurements above 16 hours are unreliable with its current task suite


def main():
    src = json.loads(SRC.read_text())
    capex = src["capex"]
    by_q = {}
    for co in BIG4:
        for r in capex.get(co, []):
            if r.get("usd_b") is not None:
                by_q.setdefault(r["q"], {})[co] = r
    quarters = sorted(q for q, v in by_q.items() if all(c in v for c in BIG4))
    total = [{"q": q, "end": max(by_q[q][c]["end"] for c in BIG4),
              "usd_b": round(sum(by_q[q][c]["usd_b"] for c in BIG4), 1),
              "by": {c: by_q[q][c]["usd_b"] for c in BIG4}} for q in quarters]
    ttm = None
    if len(total) >= 8:
        last4, prev4 = sum(t["usd_b"] for t in total[-4:]), sum(t["usd_b"] for t in total[-8:-4])
        ttm = {"asOf": total[-1]["q"], "usd_b": round(last4, 1), "prevYear_b": round(prev4, 1),
               "yoyPct": round((last4 / prev4 - 1) * 100, 1)}
    # capability: the best METR-measured frontier (sota) 50% horizon released by each quarter end.
    # Measured points only, so the line can stay flat; quarters after METR's latest measurement are
    # marked stale because releases METR hasn't measured yet are missing from them.
    index, latest = [], None
    if TRENDS.exists() and total:
        models = json.loads(TRENDS.read_text())["metr"]["models"]
        sota = [r for r in models if r.get("sota") and r.get("p50") is not None]
        best = lambda end: max((r for r in sota if r["date"] <= end), key=lambda r: r["p50"], default=None)
        b0 = best(total[0]["end"])
        if b0:
            last_measured = max(r["date"] for r in models)
            c0 = total[0]["usd_b"]
            for t in total:
                b = best(t["end"])
                index.append({"q": t["q"], "end": t["end"], "spend": round(t["usd_b"] / c0 * 100, 1),
                              "capability": round(b["p50"] / b0["p50"] * 100, 1),
                              "capabilityModel": b["id"], "capabilityDate": b["date"],
                              "aboveSuiteRange": b["p50"] > SUITE_CAP, "stale": t["end"] > last_measured})
            top = max(sota, key=lambda r: (r["p50"], r["date"]))
            latest = {"model": top["id"], "date": top["date"], "p50": top["p50"],
                      "aboveSuiteRange": top["p50"] > SUITE_CAP}
    out = {
        "updated": date.today().isoformat(),
        "capexDefinition": src.get("capex_definition"),
        "capexByCompany": {c: capex.get(c, []) for c in BIG4},
        "capexTotal": total, "ttm": ttm, "spendVsCapability": index, "latestMeasured": latest,
        "nvdaDatacenter": src.get("nvda_datacenter", []),
        "labRevenue": src.get("lab_revenue", []),
        "predictionMarkets": src.get("prediction_markets", []),
        "signals": src.get("signals", []),
        "notes": src.get("notes", []),
        "method": ("Context, not a test. Capex is total cash purchases of property and equipment by Microsoft, Alphabet, "
                   "Amazon and Meta (mostly AI data centers; also non-AI spending such as Amazon logistics), summed by "
                   "calendar quarter when all four have reported. The capability line is the best METR-measured frontier "
                   "time horizon released by each quarter end; readings above 16 hours are beyond METR's reliable range, "
                   "and quarters after METR's latest measurement can miss newer models. Models take months to train on "
                   "new capacity, so spending often leads releases. Our actual test for hidden compute is trigger X4."),
    }
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    if ttm:
        print(f"TTM capex {ttm['asOf']}: ${ttm['usd_b']}B ({ttm['yoyPct']:+}% y/y); {len(total)} complete quarters")
    else:
        print(f"{len(total)} complete quarters (need 8 for TTM growth)")


if __name__ == "__main__":
    main()
