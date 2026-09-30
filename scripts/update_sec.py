#!/usr/bin/env python3
"""Pull quarterly capex for Microsoft, Alphabet, Amazon and Meta straight from SEC XBRL filings
into data/money_sources.json ("capex"), then rebuild data/money.json.

    python3 scripts/update_sec.py

The SEC requires a contact email in the User-Agent. It's read at run time from $SEC_CONTACT_EMAIL,
or else from `git config user.email`. It's never written to disk or committed.

Cash-flow figures in 10-Q filings are year-to-date, so each quarter is the YTD value at the
quarter end minus the YTD value at the previous quarter end in the same fiscal year.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/money_sources.json"
COMPANIES = {  # ticker: (CIK, us-gaap tag for cash purchases of property and equipment)
    "MSFT": ("0000789019", "PaymentsToAcquirePropertyPlantAndEquipment"),
    "GOOGL": ("0001652044", "PaymentsToAcquirePropertyPlantAndEquipment"),
    "AMZN": ("0001018724", "PaymentsToAcquireProductiveAssets"),
    "META": ("0001326801", "PaymentsToAcquirePropertyPlantAndEquipment"),
}
FIRST = "2023-01-01"


def contact():
    email = os.environ.get("SEC_CONTACT_EMAIL")
    if not email:
        try:
            email = subprocess.run(["git", "-C", str(ROOT), "config", "user.email"], capture_output=True, text=True).stdout.strip()
        except OSError:
            email = ""
    if not email:
        sys.exit("Set SEC_CONTACT_EMAIL (the SEC requires a contact email in the User-Agent).")
    return f"HiddenAGIwatch research {email}"


def fetch(cik, tag, ua):
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["units"]["USD"]


def cal_quarter(end):
    d = date.fromisoformat(end)
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def quarterly(facts, cik):
    """Turn filed facts into discrete quarters. Returns [{q, end, usd_b, url}] from FIRST on.

    Uses a reported 3-month figure when one exists; otherwise differences year-to-date values
    within a fiscal year. Fiscal years come from the 10-K annual figures, which keeps
    trailing-twelve-month figures (Amazon files these too) from being mistaken for YTD ones."""
    dur = lambda f: (date.fromisoformat(f["end"]) - date.fromisoformat(f["start"])).days
    ytd = {}
    for f in facts:
        if f.get("form") in ("10-Q", "10-K") and f.get("start"):
            ytd[(f["start"], f["end"])] = f  # later filings overwrite earlier ones (restated values win)
    fy_starts = set()
    for f in ytd.values():
        if f["form"] == "10-K" and 350 <= dur(f) <= 380:
            fy_starts.add(f["start"])
            fy_starts.add(date.fromordinal(date.fromisoformat(f["end"]).toordinal() + 1).isoformat())
    out = []
    for e in sorted({e for (_, e) in ytd}):
        if e < FIRST:
            continue
        three = [f for (s_, ee), f in ytd.items() if ee == e and 80 <= dur(f) <= 100]
        if three:
            cur, val = three[0], three[0]["val"]
        else:
            fs = [s_ for s_ in fy_starts if s_ <= e and (date.fromisoformat(e) - date.fromisoformat(s_)).days < 370]
            if not fs:
                continue
            s_ = max(fs)
            cur = ytd.get((s_, e))
            if not cur:
                continue
            prev_ends = [pe for (ps, pe) in ytd if ps == s_ and pe < e]
            if not prev_ends:
                continue  # no earlier YTD value to subtract: skip rather than guess
            val = cur["val"] - ytd[(s_, max(prev_ends))]["val"]
        acc = cur["accn"].replace("-", "")
        out.append({"q": cal_quarter(e), "end": e, "usd_b": round(val / 1e9, 2),
                    "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/", "form": cur["form"]})
    return out


def main():
    ua = contact()
    src = json.loads(SRC.read_text()) if SRC.exists() else {}
    capex = {}
    for tk, (cik, tag) in COMPANIES.items():
        capex[tk] = quarterly(fetch(cik, tag, ua), cik)
        print(f"{tk}: {len(capex[tk])} quarters, latest {capex[tk][-1]['q']} = ${capex[tk][-1]['usd_b']}B")
        time.sleep(0.3)  # stay well under the SEC's 10 requests/second limit
    src["capex"] = capex
    src["capex_definition"] = ("Cash purchases of property and equipment from each company's SEC filings (XBRL: "
                               "PaymentsToAcquirePropertyPlantAndEquipment; for Amazon, PaymentsToAcquireProductiveAssets), "
                               "converted from year-to-date to quarterly values. Excludes finance leases.")
    src["capex_source"] = "SEC EDGAR XBRL company facts, pulled " + date.today().isoformat()
    SRC.write_text(json.dumps(src, indent=1, ensure_ascii=False) + "\n")
    subprocess.run([sys.executable, str(ROOT / "scripts/build_money.py")], check=True)


if __name__ == "__main__":
    main()
