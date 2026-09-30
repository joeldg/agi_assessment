#!/usr/bin/env python3
"""Refresh data/trends.json from primary sources and recompute the projections.

    python3 scripts/update_trends.py

Needs PyYAML (`python3 -m pip install --user -r requirements.txt`).

METR task-completion horizons come straight from METR's published data file. For each of
the 50% and 80% horizons we fit log2(minutes) against release date on the frontier
(state-of-the-art) models since 2023, excluding points whose own value is above 16 hours
(METR's reliability limit), and project the fit forward. lo/hi is the 95% confidence band of
the fitted line (level and slope uncertainty, Student-t); predLo/predHi is the wider band where
an individual new frontier model should land. The line starts at the fitted value on the latest
frontier release date, not at that model's measurement; crossingsFromMeasured is a sensitivity
that starts from the measurement instead, computed only when it is inside the reliable range.
Hand-curated series (AI share of AI R&D, Remote Labor Index) live in the same file under
"manual" and are left untouched. Nothing is written unless every fetch succeeds.
"""
import http.client
import json
import math
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit(f"PyYAML is missing for {sys.executable}: run `{sys.executable} -m pip install --user -r requirements.txt`. "
             "data/trends.json was not changed.")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/trends.json"
METR_URL = "https://metr.org/assets/benchmark_results_1_1.yaml"
METR_PAGE = "https://metr.org/time-horizons/"
WORK_WEEK, WORK_MONTH = 40 * 60, 167 * 60   # minutes of human professional time
CAP = 16 * 60            # METR: measurements above 16 hours are unreliable with its current task suite
FIT_FROM = "2023-01-01"
PROJECT_TO = date(2031, 1, 1).toordinal()
SEARCH_TO = date(2045, 1, 1).toordinal()   # a curve that has not crossed by then counts as "no crossing" (None)
RETRY_WAITS = (2, 5, 10)                    # seconds between attempts
# Two-sided 95% Student-t critical values, t(0.975, df)
T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262,
        10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110,
        18: 2.101, 19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
        26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042}


def ordinal(d):
    return date.fromisoformat(d).toordinal()


def t_crit(df):
    return T975.get(df) or 1.96 + 2.37 / df + 2.8 / df ** 2


def fit(points):
    """Least squares of log2(y) on day number. Returns slope/day, intercept, residual SD (log2), n, mean day, Sxx."""
    xs = [ordinal(p["date"]) for p in points]
    ys = [math.log2(p["v"]) for p in points]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    icpt = my - slope * mx
    resid = [y - (icpt + slope * x) for x, y in zip(xs, ys)]
    s = math.sqrt(sum(r * r for r in resid) / (n - 2))
    return slope, icpt, s, n, mx, sxx


def first_day(curve, target, start):
    """First day on or after start where curve (log2 minutes) reaches target minutes, or None before SEARCH_TO."""
    goal = math.log2(target)
    for day in range(start, SEARCH_TO + 1):
        if curve(day) >= goal:
            return date.fromordinal(day).isoformat()
    return None


def project(metric, frontier, metr_ci=None):
    """Fit one horizon metric. Returns the trends.json block and the fitted log2 line (a function of day number)."""
    pts = [{"date": r["date"], "v": r[metric]} for r in frontier
           if r["date"] >= FIT_FROM and r[metric] and r[metric] <= CAP]
    if len(pts) < 3:
        sys.exit(f"Only {len(pts)} usable METR points for {metric}; data/trends.json left unchanged.")
    slope, icpt, s, n, mx, sxx = fit(pts)
    t = t_crit(n - 2)
    se_slope = s / math.sqrt(sxx)
    latest = max(frontier, key=lambda r: r["date"])
    last = latest["date"]
    anchor_day = ordinal(last)

    def line(day):
        return icpt + slope * day

    def se_line(day):   # SE of the fitted mean at this date: level plus slope uncertainty
        return s * math.sqrt(1 / n + (day - mx) ** 2 / sxx)

    def se_pred(day):   # SE for one new frontier model at this date
        return s * math.sqrt(1 + 1 / n + (day - mx) ** 2 / sxx)

    def band_at(day):
        f, w, wp = line(day), t * se_line(day), t * se_pred(day)
        return {"mid": 2 ** f, "lo": 2 ** (f - w), "hi": 2 ** (f + w), "predLo": 2 ** (f - wp), "predHi": 2 ** (f + wp)}

    series = []
    for day in range(anchor_day, PROJECT_TO + 1, 30):
        b = band_at(day)
        series.append({"date": date.fromordinal(day).isoformat(), **{k: round(v, 2) for k, v in b.items()}})

    def upper(day):
        return line(day) + t * se_line(day)

    def lower(day):
        return line(day) - t * se_line(day)

    def cross(target):
        return {"mid": first_day(line, target, anchor_day), "fast": first_day(upper, target, anchor_day),
                "slow": first_day(lower, target, anchor_day)}

    measured = latest.get(metric)
    in_range = bool(measured) and measured <= CAP
    from_measured = None
    if in_range and slope > 0:   # never start a scenario from a reading METR calls unreliable
        m_log = math.log2(measured)

        def m_line(day):
            return m_log + slope * (day - anchor_day)
        from_measured = {"workWeek": first_day(m_line, WORK_WEEK, anchor_day),
                         "workMonth": first_day(m_line, WORK_MONTH, anchor_day)}

    lo_s, hi_s = slope - t * se_slope, slope + t * se_slope
    a = band_at(anchor_day)
    block = {
        "doublingDays": round(1 / slope, 1), "doublingDaysRange": [round(1 / hi_s, 1), round(1 / lo_s, 1) if lo_s > 0 else None],
        "fitPoints": n, "tCrit": t, "residSD": round(s, 3),
        "anchor": {"date": last, "model": latest["id"], "value": round(a["mid"], 2), "lo": round(a["lo"], 2), "hi": round(a["hi"], 2),
                   "measured": round(measured, 2) if measured else None, "measuredInRange": in_range},
        "projection": series,
        "crossings": {"workWeek": cross(WORK_WEEK), "workMonth": cross(WORK_MONTH)},
        "crossingsFromMeasured": from_measured,
    }
    if metr_ci:
        block["metrPublishedCI"] = metr_ci
    return block, line


def fetch(url, what):
    """GET url, retrying on network errors, timeouts and HTTP 429/5xx; exit cleanly (writing nothing) when it gives up."""
    reason = "unknown error"
    for wait in RETRY_WAITS + (None,):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            reason = f"HTTP {e.code}"
            if e.code != 429 and e.code < 500:
                break
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            reason = str(getattr(e, "reason", "") or e) or type(e).__name__
        if wait is None:
            break
        print(f"{what}: {reason}; retrying in {wait}s", file=sys.stderr)
        time.sleep(wait)
    sys.exit(f"{what} unreachable ({reason}); data/trends.json left unchanged.")


def main():
    try:
        raw = yaml.safe_load(fetch(METR_URL, "METR data"))
        results = raw["results"]
    except (yaml.YAMLError, KeyError, TypeError) as e:
        detail = " ".join(str(e).split())[:200]
        sys.exit(f"METR data could not be parsed ({type(e).__name__}: {detail}); data/trends.json left unchanged.")
    models = []
    for key, v in results.items():
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
    pub = ((raw.get("doubling_time_in_days") or {}).get("from_2023_on") or {})
    metr_ci = [round(pub["ci_low"], 1), round(pub["ci_high"], 1)] if pub.get("ci_low") and pub.get("ci_high") else None
    p50, line50 = project("p50", frontier, metr_ci)
    p80, line80 = project("p80", frontier)
    # Residuals against each fit, in log2 units (log2 of measured / fitted), for frontier models in the fit window.
    for r in frontier:
        if r["date"] < FIT_FROM:
            continue
        day = ordinal(r["date"])
        r["resid"] = round(math.log2(r["p50"]) - line50(day), 3)
        if r["p80"]:
            r["resid80"] = round(math.log2(r["p80"]) - line80(day), 3)
        if r["p50"] > CAP:
            r["excluded"] = True      # above 16 hours: not used in the 50% fit
        if r["p80"] and r["p80"] > CAP:
            r["excluded80"] = True    # not used in the 80% fit
    today = date.today()
    trend_now = 2 ** line50(today.toordinal())
    data = json.loads(OUT.read_text()) if OUT.exists() else {}
    data["updated"] = today.isoformat()
    data["metr"] = {
        "source": METR_PAGE, "dataUrl": METR_URL, "unit": "minutes",
        "metrDoublingDays": raw.get("doubling_time_in_days"),
        "thresholds": {"workWeek": WORK_WEEK, "workMonth": WORK_MONTH},
        "models": models,
        "p50": p50, "p80": p80,
        # Trigger X2 input: can a model 4x above the 50% trend be told apart on METR's suite today?
        "x2": {"date": today.isoformat(), "metric": "p50", "trendNow": round(trend_now, 1), "fourX": round(4 * trend_now, 1),
               "suiteLimit": CAP, "observable": 4 * trend_now <= CAP},
        "method": ("Least-squares fit of log2(horizon) on release date (METR frontier models since 2023, excluding points above "
                   "16 hours, METR's reliability limit). Shaded band = 95% confidence band of the trend line (Student-t); "
                   "lighter band = where an individual new frontier model should land. The line starts at the fitted value on "
                   "the latest frontier release date, not at that model's measurement."),
    }
    data.setdefault("manual", {})
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    for m in ("p50", "p80"):
        p = data["metr"][m]
        c, an = p["crossings"], p["anchor"]
        print(f"{m}: doubling {p['doublingDays']}d {p['doublingDaysRange']}"
              + (f" (METR published CI {p['metrPublishedCI']})" if p.get("metrPublishedCI") else "")
              + f", n={p['fitPoints']}, t={p['tCrit']}, residual SD {p['residSD']} log2")
        print(f"  anchor {an['date']} ({an['model']}): fitted {an['value']} min [{an['lo']}–{an['hi']}], measured {an['measured']}")
        for k in ("workWeek", "workMonth"):
            print(f"  {k}: {c[k]['mid']} (range {c[k]['fast']} – {c[k]['slow']})")
        print(f"  from measured: {p['crossingsFromMeasured']}")
    x2 = data["metr"]["x2"]
    print(f"x2 ({x2['date']}): 50% trend {x2['trendNow']} min, 4x = {x2['fourX']} min, observable on METR's suite: {x2['observable']}")


if __name__ == "__main__":
    main()
