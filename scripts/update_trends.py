#!/usr/bin/env python3
"""Refresh data/trends.json from primary sources and recompute the projections.

    python3 scripts/update_trends.py

METR task-completion horizons come straight from METR's published data file. For each of
the 50% and 80% horizons we fit log2(minutes) against time on the frontier (state-of-the-art)
models since 2023, excluding points above 16 hours as METR does, and project the fit forward
with a 95% band from the slope's standard error. Hand-curated series (AI share of AI R&D)
live in the same file under "manual" and are left untouched.
"""
import json
import math
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/trends.json"
METR_URL = "https://metr.org/assets/benchmark_results_1_1.yaml"
METR_PAGE = "https://metr.org/time-horizons/"
WORK_WEEK, WORK_MONTH = 40 * 60, 167 * 60   # minutes of human professional time
T_CRIT = 2.0  # ~95% for the sample sizes involved; kept simple and stated on the page


def ordinal(d):
    return date.fromisoformat(d).toordinal()


def fit(points):
    """Least squares of log2(y) on day number. Returns slope/day, intercept, slope SE, n."""
    xs = [ordinal(p["date"]) for p in points]
    ys = [math.log2(p["v"]) for p in points]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    icpt = my - slope * mx
    resid = [y - (icpt + slope * x) for x, y in zip(xs, ys)]
    se = math.sqrt(sum(r * r for r in resid) / (n - 2) / sxx)
    return slope, icpt, se, n, mx


def crossing(slope, icpt, target):
    if slope <= 0:
        return None
    return date.fromordinal(round((math.log2(target) - icpt) / slope)).isoformat()


def project(metric, frontier):
    pts = [{"date": r["date"], "v": r[metric]} for r in frontier
           if r["date"] >= "2023-01-01" and r[metric] and r["p50"] <= 16 * 60]
    slope, icpt, se, n, mx = fit(pts)
    last = max(r["date"] for r in frontier)
    anchor_day = ordinal(last)
    anchor_log = icpt + slope * anchor_day
    lo_s, hi_s = slope - T_CRIT * se, slope + T_CRIT * se

    def band_at(day):
        dt = day - anchor_day
        return {"mid": 2 ** (anchor_log + slope * dt), "lo": 2 ** (anchor_log + lo_s * dt), "hi": 2 ** (anchor_log + hi_s * dt)}

    series = []
    end = date(2031, 1, 1).toordinal()
    for day in range(anchor_day, end + 1, 30):
        b = band_at(day)
        series.append({"date": date.fromordinal(day).isoformat(), **{k: round(v, 2) for k, v in b.items()}})

    def cross(target):
        out = {}
        for name, s in (("mid", slope), ("fast", hi_s), ("slow", lo_s)):
            if s <= 0:
                out[name] = None
                continue
            day = anchor_day + (math.log2(target) - anchor_log) / s
            out[name] = date.fromordinal(round(day)).isoformat() if day > anchor_day else last
        return out

    return {
        "doublingDays": round(1 / slope, 1), "doublingDaysRange": [round(1 / hi_s, 1), round(1 / lo_s, 1) if lo_s > 0 else None],
        "fitPoints": n, "anchor": {"date": last, "value": round(2 ** anchor_log, 2)},
        "projection": series,
        "crossings": {"workWeek": cross(WORK_WEEK), "workMonth": cross(WORK_MONTH)},
    }


def main():
    raw = yaml.safe_load(urllib.request.urlopen(METR_URL, timeout=60).read())
    models = []
    for key, v in raw["results"].items():
        m = v["metrics"]
        models.append({
            "id": key, "date": str(v["release_date"]), "sota": bool(m.get("is_sota")),
            "p50": round(m["p50_horizon_length"]["estimate"], 2),
            "p50lo": round(m["p50_horizon_length"].get("ci_low") or 0, 2),
            "p50hi": round(m["p50_horizon_length"].get("ci_high") or 0, 2),
            "p80": round((m.get("p80_horizon_length") or {}).get("estimate") or 0, 2) or None,
        })
    models.sort(key=lambda r: r["date"])
    frontier = [r for r in models if r["sota"]]
    data = json.loads(OUT.read_text()) if OUT.exists() else {}
    data["updated"] = date.today().isoformat()
    data["metr"] = {
        "source": METR_PAGE, "dataUrl": METR_URL, "unit": "minutes",
        "metrDoublingDays": raw.get("doubling_time_in_days"),
        "thresholds": {"workWeek": WORK_WEEK, "workMonth": WORK_MONTH},
        "models": models,
        "p50": project("p50", frontier), "p80": project("p80", frontier),
        "method": ("Least-squares fit of log2(horizon) against release date on METR's state-of-the-art models since 2023, "
                   "excluding points above 16 hours (METR's own cut-off, where its task suite saturates). The band uses "
                   "±2 standard errors on the slope, anchored at the latest frontier model. This is a projection of a trend, not a prediction."),
    }
    data.setdefault("manual", {})
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    for m in ("p50", "p80"):
        p = data["metr"][m]
        print(f"{m}: doubling {p['doublingDays']}d {p['doublingDaysRange']}, n={p['fitPoints']}, "
              f"work-week {p['crossings']['workWeek']}, work-month {p['crossings']['workMonth']}")


if __name__ == "__main__":
    main()
