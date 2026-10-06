#!/usr/bin/env python3
"""Headless smoke check of the built site (redesign v2, spec 10.5 and 14). Read-only: it writes nothing into the tree.

    python3 scripts/smoke.py [PAGE[#id] ...] [--widths 375,1280] [--anchors] [--anchors-only] [--root DIR] [--verbose]

Pages. It serves the tree on 127.0.0.1 only while it runs (one short-lived server per page, on a free port) and loads
each page in headless Chrome, inside a same-origin iframe harness that the server answers from memory (it is never
written into the tree, so a run can't leave a dirty file that stops the next daily). After the page settles it fails on:
  - any of the failure strings "Error response", "Couldn't load", "could not be drawn", "Chart unavailable",
    "Unknown status" in the page (scripts left out);
  - no <svg> on a charted page: index, agi, hidden, trends, money, disclosure-lag, agi-claims and a weekly wrap-up
    (the homepage always has its server-rendered Index bar);
  - an uncaught script error or unhandled promise rejection, or a request the server answers with 4xx/5xx (a missing
    asset or data file);
  - with --widths, a document scrollWidth wider than the iframe (a true 375 px phone, not a clamped window);
  - for a page named with #id, no such element after its scripts ran, or the element still shut in a <details>.
Default pages: the 16 standing pages, the latest weekly wrap-up, the latest report, and its analysis page only when the
newest reading has one. Name pages to check only those.

--anchors resolves every link found in reports/*.html, weekly/*.html, feed.xml, docs/welcome-email.md and
data/**/*.json (plus, best effort, every daily and weekly email rendered in memory, so issues older than the feed's
last 30 stay covered) against the static HTML of the local tree. Absolute links on the site's hosts (sitekit.SITE,
build_feed.FEED_GUID_BASE) are mapped to local paths first. A link fails when its file doesn't exist ("no path
retired"), or when its fragment names no id (or <a name>) in the target's server-rendered HTML; and the anchors the
spec promises (REQUIRED_ANCHORS) must be in their pages' server-rendered HTML. The few links in frozen files that never
resolved are listed in KNOWN_BROKEN and print as notes. The generated pages at the root are crawled too, but a broken
link there only warns: it is fixed in its generator, not frozen. --anchors-only skips the browser.
--published-warn (the daily and weekly routines): a broken link that was already in the committed (HEAD) version of
the file it comes from, i.e. published before this run, prints as a "PUBLISHED" line for the owner instead of failing,
so a frozen page nobody may edit can't stop a routine; a link this run added still fails. (A rendered email counts as
published when its link is in the committed data/runs.json or data/weekly/<date>.json it is rendered from.)

Exit status: 0 passed; 1 a check failed (the last line names every failure); 2 the check could not run (no Chrome,
no such root). Chrome: $SMOKE_CHROME, else render_card.CHROME, else the default macOS path.
"""
import argparse
import contextlib
import html
import http.server
import importlib
import io
import json
import os
import re
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlencode, urljoin, urlsplit

sys.dont_write_bytecode = True  # importing the site's modules must not leave __pycache__ behind

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEFAULT_SITE = "https://hiddenagi.com/"
DEFAULT_GUID_BASE = "https://joeldg.github.io/agi_assessment/"

FAIL_STRINGS = ("Error response", "Couldn't load", "could not be drawn", "Chart unavailable", "Unknown status")
STANDING = ("index.html", "agi.html", "hidden.html", "alarm.html", "escape.html", "start-here.html", "changes.html",
            "archive.html", "scorecard.html", "trends.html", "money.html", "disclosure-lag.html", "agi-claims.html",
            "calendar.html", "steelman.html", "about.html")
CHARTED = ("index.html", "agi.html", "hidden.html", "trends.html", "money.html", "disclosure-lag.html",
           "agi-claims.html")
DATED = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WEEKLY_PAGE = re.compile(r"^weekly/\d{4}-\d{2}-\d{2}\.html$")
HARNESS_PATH = "/__smoke__/harness.html"
SETTLE_MS = 2500        # virtual time a page gets after its load event before it is measured
IFRAME_HEIGHT = 900
CHROME_TIMEOUT = 150    # seconds of wall time per page

# The harness: loads the page in an iframe of each width in turn, lets it settle, measures it, and leaves the results as
# JSON in #smoke-out for --dump-dom. Served from memory at HARNESS_PATH; same origin as the pages, so it can read them.
HARNESS = """<!doctype html><html><head><meta charset="utf-8"><title>smoke harness</title>
<link rel="icon" href="data:,">
<style>html,body{margin:0;background:#fff}iframe{border:0;display:block}#smoke-out{display:none}</style></head>
<body><pre id="smoke-out"></pre>
<script>
console.log("%(beacon)s");   // proves Chrome's console log reaches smoke.py, so script errors can't go unseen
const FAIL = %(fail)s;
const q = new URLSearchParams(location.search);
const src = q.get("src"), settle = +(q.get("settle") || 2500), H = +(q.get("h") || 900);
const widths = (q.get("w") || "1280").split(",").map(Number);
const sleep = ms => new Promise(r => setTimeout(r, ms));
function describe(el){
  const c = el.className && el.className.baseVal !== undefined ? el.className.baseVal : (el.className || "");
  const cls = String(c).trim() ? "." + String(c).trim().split(/\\s+/).slice(0, 2).join(".") : "";
  return el.tagName.toLowerCase() + (el.id ? "#" + el.id : "") + cls;
}
function clipped(el, win){
  for(let a = el.parentElement; a && a !== win.document.documentElement; a = a.parentElement)
    if(win.getComputedStyle(a).overflowX !== "visible") return true;
  return false;
}
function probe(f, w){
  const d = f.contentDocument, win = f.contentWindow;
  if(!d || !d.documentElement || !d.body) return {w, error: "the page did not load"};
  const de = d.documentElement, W = de.clientWidth;
  const copy = de.cloneNode(true);
  copy.querySelectorAll("script").forEach(s => s.remove());
  const text = copy.outerHTML.replace(/\\u2019/g, "'");
  const over = [];
  for(const el of d.querySelectorAll("body *")){
    const r = el.getBoundingClientRect();
    if(!r.width || r.right <= W + 1) continue;
    if(win.getComputedStyle(el).position === "fixed" || clipped(el, win)) continue;
    over.push(describe(el) + " (right edge " + Math.round(r.right) + ")");
    if(over.length >= 6) break;
  }
  return {w, sw: de.scrollWidth, cw: W, h: de.scrollHeight, title: d.title, url: win.location.pathname,
          fails: FAIL.filter(s => text.includes(s)),
          svgs: [...d.querySelectorAll("svg")].filter(s => !s.closest("nav, footer, .subscribe")).length,
          ready: [...d.querySelectorAll("[data-ready]")].map(e => describe(e) + "=" + e.getAttribute("data-ready")),
          over, target: target(d, win)};
}
function target(d, win){
  // A page loaded with #fragment: is its target there, and not shut inside a closed <details>?
  let id = (win.location.hash || "").slice(1);
  if(!id) return null;
  try { id = decodeURIComponent(id); } catch(e) {}
  const el = d.getElementById(id) || d.getElementsByName(id)[0];
  if(!el) return {id, found: false};
  const shut = el.closest("details:not([open])"), sum = shut && shut.querySelector(":scope > summary");
  return {id, found: true, hidden: !!shut && !(sum && sum.contains(el) && shut !== el)};
}
function load(w){
  return new Promise(resolve => {
    const f = document.createElement("iframe");
    f.style.width = w + "px"; f.style.height = H + "px"; f.title = "page under test";
    f.addEventListener("load", async () => {
      await sleep(settle);
      let r;
      try { r = probe(f, w); } catch(e) { r = {w, error: "the harness could not read the page: " + e}; }
      f.remove();
      resolve(r);
    }, {once: true});
    f.src = src;
    document.body.appendChild(f);
  });
}
(async () => {
  const out = {src, results: [], done: false}, box = document.getElementById("smoke-out");
  for(const w of widths){ out.results.push(await load(w)); box.textContent = JSON.stringify(out); }
  out.done = true;
  box.textContent = JSON.stringify(out);
})();
</script></body></html>
""" % {"fail": json.dumps(list(FAIL_STRINGS)), "beacon": "smoke harness: console log captured"}

BEACON = "smoke harness: console log captured"
CONSOLE = re.compile(r':CONSOLE(?:\(\d+\)|:\d+)?\]\s*"(.*)", source:\s*(\S*)\s*\((\d+)\)')


# ---------------------------------------------------------------------------------------------------------------------
# helpers shared by both parts

def site_modules(root):
    """sitekit.SITE, build_feed.FEED_GUID_BASE and render_card.CHROME from the tree's own scripts, with fallbacks."""
    found = {"SITE": DEFAULT_SITE, "FEED_GUID_BASE": DEFAULT_GUID_BASE, "CHROME": DEFAULT_CHROME}
    scripts = root / "scripts"
    for name, module in (("SITE", "sitekit"), ("FEED_GUID_BASE", "build_feed"), ("CHROME", "render_card")):
        path = scripts / (module + ".py")
        try:
            m = re.search(r'^%s\s*=\s*"([^"]+)"' % name, path.read_text(encoding="utf-8"), re.M)
        except OSError:
            m = None
        if m:
            found[name] = m.group(1)
    return found


def newest_run(root):
    """The newest reading in data/runs.json (the last entry with the greatest date), or None."""
    try:
        runs = json.loads((root / "data/runs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    runs = [r for r in runs if isinstance(r, dict) and isinstance(r.get("date"), str)] if isinstance(runs, list) else []
    best = None
    for r in runs:
        if r.get("report") and (best is None or r["date"] >= best["date"]):
            best = r
    return best


def default_pages(root):
    """(pages, notes): the standing pages, the latest wrap-up, the latest report and its analysis page if any."""
    pages, notes = list(STANDING), []
    weekly = sorted(p.name for p in (root / "weekly").glob("*.html") if DATED.match(p.stem))
    if weekly:
        pages.append("weekly/" + weekly[-1])
    else:
        notes.append("no weekly wrap-up page found under weekly/")
    run = newest_run(root)
    if run:
        pages.append(run["report"])
        if run.get("analysis"):
            pages.append(run["analysis"])
    else:
        reports = sorted(p.name for p in (root / "reports").glob("*.html") if DATED.match(p.stem))
        if reports:
            pages.append("reports/" + reports[-1])
            notes.append("data/runs.json unreadable: took the latest report by file name")
        else:
            notes.append("no report found under reports/")
    return pages, notes


def charted(page):
    page = page.split("#", 1)[0]
    return page in CHARTED or bool(WEEKLY_PAGE.match(page))


# ---------------------------------------------------------------------------------------------------------------------
# part 1: pages in headless Chrome

def handler_class(root, misses):
    class Handler(http.server.SimpleHTTPRequestHandler):
        """Serves the tree read-only, answers the harness from memory and records every 4xx/5xx it sends."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def do_GET(self):
            if urlsplit(self.path).path == HARNESS_PATH:
                body = HARNESS.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_request(self, code="-", size="-"):
            try:
                status = int(getattr(code, "value", code))
            except (TypeError, ValueError):
                return
            if status >= 400:
                misses.append("%s (%d)" % (urlsplit(self.path).path, status))

        def log_message(self, format, *args):  # noqa: A002 (the base class's name)
            pass

    return Handler


def chrome_page(page, widths, opts):
    """Load one page at each width; returns {"page", "results", "console", "misses", "error"}."""
    misses = []
    out = {"page": page, "results": [], "console": [], "misses": misses, "error": None}
    try:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_class(opts.root, misses))
    except OSError as e:
        out["error"] = "could not start the local server on 127.0.0.1: %s" % e
        return out
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        query = urlencode({"src": "/" + page, "w": ",".join(str(w) for w in widths),
                           "settle": opts.settle, "h": IFRAME_HEIGHT})
        url = "http://127.0.0.1:%d%s?%s" % (srv.server_port, HARNESS_PATH, query)
        budget = len(widths) * (opts.settle + 5000) + 5000
        cmd = [opts.chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
               "--no-default-browser-check", "--mute-audio", "--enable-logging=stderr", "--v=0",
               "--window-size=%d,%d" % (max(widths) + 40, IFRAME_HEIGHT + 40),
               "--virtual-time-budget=%d" % budget, "--dump-dom", url]
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=opts.timeout)
        except subprocess.TimeoutExpired:
            out["error"] = "headless Chrome timed out after %d s" % opts.timeout
            return out
        except OSError as e:
            out["error"] = "headless Chrome could not start: %s" % e
            return out
        stdout = p.stdout.decode("utf-8", "replace")
        stderr = p.stderr.decode("utf-8", "replace")
        for line in stderr.splitlines():
            m = CONSOLE.search(line)
            if m:
                src = re.sub(r"^https?://127\.0\.0\.1:\d+/", "", m.group(2))
                out["console"].append((m.group(1), "%s:%s" % (src, m.group(3))))
        m = re.search(r'<pre id="smoke-out">(.*?)</pre>', stdout, re.S)
        if not m or not m.group(1).strip():
            tail = (stderr.strip().splitlines() or [""])[-1][:200]
            out["error"] = "the harness returned no result (Chrome exit %d) %s" % (p.returncode, tail)
            return out
        try:
            got = json.loads(html.unescape(m.group(1)))
            out["results"] = got["results"]
        except (ValueError, KeyError, TypeError) as e:
            out["error"] = "the harness result could not be read: %s" % e
            return out
        if not got.get("done"):
            out["error"] = ("the page did not finish loading within Chrome's virtual-time budget (%d of %d width(s) "
                            "measured)" % (len(out["results"]), len(widths)))
        return out
    finally:
        srv.shutdown()
        srv.server_close()


def judge_width(page, r, widths_enforced):
    """(problems, notes) for one page at one width."""
    w, problems, notes = r.get("w"), [], []
    if r.get("error"):
        return ["%s px: %s" % (w, r["error"])], notes
    if r.get("fails"):
        problems.append("%s px: shows %s" % (w, ", ".join('"%s"' % s for s in r["fails"])))
    if charted(page) and not r.get("svgs"):
        problems.append("%s px: no chart drawn (no <svg>)" % w)
    t = r.get("target")
    if t and not t.get("found"):
        problems.append('%s px: no element with id "%s" after the page ran' % (w, t["id"]))
    elif t and t.get("hidden"):
        problems.append('%s px: #%s is inside a closed <details> after load (it should open from the hash)'
                        % (w, t["id"]))
    if widths_enforced and r.get("sw", 0) > w:
        over = "; wider than the page: " + ", ".join(r["over"]) if r.get("over") else ""
        problems.append("%s px: scrollWidth %s is wider than %s px%s" % (w, r.get("sw"), w, over))
    elif r.get("over"):
        notes.append("%s px: past the right edge, though the page still fits: %s" % (w, ", ".join(r["over"][:3])))
    return problems, notes


def judge_page(res, widths_enforced):
    """(problems, notes) for one page's harness result."""
    problems, notes = ([res["error"]] if res["error"] else []), []
    for r in res["results"]:
        p, n = judge_width(res["page"], r, widths_enforced)
        problems += p
        notes += n
    for msg, where in res["console"]:
        if msg == BEACON:
            continue
        if msg.startswith("Uncaught"):
            problems.append("script error: %s (%s)" % (msg[:240], where))
        elif "Failed to load resource" not in msg:   # 404s are reported from the server's own log, below
            notes.append("console: %s (%s)" % (msg[:200], where))
    for miss in sorted(set(res["misses"])):
        problems.append("the page requested a missing file: %s" % miss)
    return problems, notes


def summary_cell(r, widths_enforced):
    if r.get("error"):
        return "%s px error" % r.get("w")
    sw = " sw %s" % r.get("sw") if widths_enforced else ""
    return "%s px%s svg %s" % (r.get("w"), sw, r.get("svgs"))


def check_pages(pages, opts):
    """Runs the browser part; returns the list of failure labels."""
    widths = opts.widths or [1280]
    print("pages: %d page(s) at %s px in headless Chrome, served from %s on 127.0.0.1 only while this runs"
          % (len(pages), ", ".join(str(w) for w in widths), opts.root))
    with ThreadPoolExecutor(max_workers=max(1, opts.jobs)) as ex:
        results = list(ex.map(lambda pg: chrome_page(pg, widths, opts), pages))
    deaf = [res["page"] for res in results if not res["error"] and all(m != BEACON for m, _ in res["console"])]
    if deaf:
        print("note: Chrome's console log was not captured for %d page(s), so script errors were not checked there "
              "(a Chrome logging change?): %s" % (len(deaf), ", ".join(deaf)))
    failed = []
    width = max(len(p) for p in pages) + 2
    for res in results:
        problems, notes = judge_page(res, bool(opts.widths))
        print_page(res, problems, notes, opts, width)
        if problems:
            failed.append(res["page"])
    return failed


def print_page(res, problems, notes, opts, width):
    cells = " · ".join(summary_cell(r, bool(opts.widths)) for r in res["results"])
    print("  %s%s%s" % (res["page"].ljust(width), cells or "-", "  PROBLEM" if problems else "  ok"))
    for line in problems:
        print("      PROBLEM: " + line)
    if not opts.verbose:
        if notes:
            print("      (%d note(s); --verbose shows them)" % len(notes))
        return
    for line in notes:
        print("      note: " + line)
    for r in res["results"]:
        if r.get("ready"):
            print("      ready: %s px %s" % (r["w"], ", ".join(r["ready"])))


# ---------------------------------------------------------------------------------------------------------------------
# part 2: the anchor crawl

class LinkScan(HTMLParser):
    """Ids (and <a name>s) a page defines, and the links it carries, with line numbers."""
    META_LINKS = ("og:url", "og:image", "twitter:image")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.links = set(), []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "a" and a.get("name"):
            self.ids.add(a["name"])
        line = self.getpos()[0]
        for k in ("href", "src"):
            v = a.get(k, "").strip()
            if v:
                self.links.append((v, line))
        prop = (a.get("property") or a.get("name") or "").lower()
        if tag == "meta" and prop in self.META_LINKS and a.get("content"):
            self.links.append((a["content"].strip(), line))


def scan_html(text):
    s = LinkScan()
    s.feed(text)
    s.close()
    return s


URL_KEY = re.compile(r"(?:^|[a-z_])(?:url|href|link)s?$", re.I)   # check_data.walk_urls's rule
# A data string that is a whole site path: a page ("index.html", "reports/2026-10-05.html#s5"), or a file one folder
# down or more ("cards/2026-10-05.png", "data/trends.json"). Bare names such as "Node.js" are not paths.
LOCAL_SHAPE = re.compile(r"^(?:\.{1,2}/)*(?:[\w%.-]+\.(?:html?|xml)"
                         r"|[\w%.-]+(?:/[\w%.-]+)+\.(?:html?|xml|json|png|jpe?g|svg|gif|webp|css|js|pdf|txt|ico))"
                         r"(?:[?#]\S*)?$", re.I)
ATTR_LINK = re.compile(r"""\b(?:href|src)\s*=\s*(["'])(.*?)\1""", re.I | re.S)

# Anchors the spec promises (2.3, 5, 7.4, 12) in the server-rendered HTML, whether or not a crawled file links them.
REQUIRED_ANCHORS = {
    "index.html": "tripwires alarm gauges escape roundup",
    "alarm.html": "W1 W2 W3 W4 W5 W6 X1 X2 X3 X4 X5 X6 Y1 Y2 Y3 rules proof case-file changelog "
                  "level-1 level-2 level-3 signals",
    "escape.html": "weights selfrep compute money identity supplychain coordination leakage",
    "start-here.html": "method gauges hidden pieces names alarm sending changes hypotheses agi-bar index honesty",
    "about.html": "corrections sending",
    "agi.html": "definition tracker agi-map numbers excludes v1 others breadth quality reliability reasoning horizon "
                "autonomy learning generalization",
    "hidden.html": "index hypotheses odds over-time gauges",
    "changes.html": "method criteria corrections",
    "disclosure-lag.html": "floor",
}

# Links in frozen files that never resolved, so they are not a path we retired. Listed by (file, exact href); each is
# printed as a note, never a failure. Anything else that fails to resolve fails the check.
KNOWN_BROKEN = {
    ("reports/2026-10-01.html", "disclosure-lag.html"):
        "the frozen 2026-10-01 report's gauge 'evidence' link was written without '../'; it has been a 404 since then",
    ("reports/2026-10-01.html", "money.html"):
        "the frozen 2026-10-01 report's gauge 'evidence' link was written without '../'; it has been a 404 since then",
}


class Crawl:
    def __init__(self, root, site, guid_base):
        self.root = root.resolve()
        self.site = site if site.endswith("/") else site + "/"
        s = urlsplit(self.site)
        host = (s.hostname or "").lower()
        self.site_hosts = {host, host[4:] if host.startswith("www.") else "www." + host}
        self.site_prefix = s.path or "/"
        g = urlsplit(guid_base)
        self.guid_host, self.guid_prefix = (g.hostname or "").lower(), g.path or "/"
        if not self.guid_prefix.endswith("/"):
            self.guid_prefix += "/"
        host_re = "|".join(re.escape(h) for h in sorted(self.site_hosts | {self.guid_host}) if h)
        self.abs_in_text = re.compile(r"https?://(?:%s)(?:/[^\s\"'<>()\[\]]*)?" % host_re, re.I)
        self.links = []      # (where, raw url, base path, soft): soft links only warn
        self.notes = []
        self._ids = {}

    # -- sources ------------------------------------------------------------------------------------------------------
    def add(self, where, url, base="", soft=False):
        self.links.append((where, url, base, soft))

    def add_html(self, label, text, base, soft=False):
        for url, line in scan_html(text).links:
            self.add("%s:%d" % (label, line), url, base, soft)

    def add_html_files(self, files, soft=False):
        for path in files:
            rel = path.relative_to(self.root).as_posix()
            try:
                self.add_html(rel, path.read_text(encoding="utf-8"), rel, soft)
            except (OSError, UnicodeDecodeError) as e:
                self.add(rel, "!unreadable: %s" % e, soft=soft)
        return len(files)

    def add_pages(self):
        """Every report (analysis pages included) and every wrap-up page, frozen or new."""
        return self.add_html_files(sorted(self.root.glob("reports/*.html")) + sorted(self.root.glob("weekly/*.html")))

    def add_site_pages(self):
        """The generated pages at the root: their own links are fixable in the generator, so they only warn."""
        return self.add_html_files(sorted(self.root.glob("*.html")), soft=True)

    def add_feed(self):
        path = self.root / "feed.xml"
        if not path.exists():
            self.notes.append("feed.xml is missing; nothing crawled from it")
            return 0
        try:
            tree = ET.parse(str(path))
        except (ET.ParseError, OSError) as e:
            self.add("feed.xml", "!unparseable: %s" % e)
            return 1
        channel = tree.getroot().find("channel")
        if channel is None:
            self.add("feed.xml", "!unparseable: no <channel>")
            return 1
        blocks = [("feed.xml channel", [el for el in channel if el.tag.split("}")[-1] != "item"])]
        for item in channel.findall("item"):
            blocks.append(("feed.xml item %s" % (item.findtext("link") or item.findtext("title") or "?").strip(),
                           list(item)))
        for label, elements in blocks:
            for el in (el for top in elements for el in top.iter()):
                self.add_feed_element(label, el)
        return 1

    def add_feed_element(self, label, el):
        tag = el.tag.split("}")[-1]
        where = "%s <%s>" % (label, tag)
        # <guid> is the report's URL on the old host (FEED_GUID_BASE) even when isPermaLink is false
        if tag in ("link", "url", "guid", "comments") and (el.text or "").strip():
            self.add(where, el.text.strip())
        if el.get("href"):
            self.add(where, el.get("href"))
        if tag in ("description", "encoded") and el.text and "<" in el.text:
            for url, line in scan_html(el.text).links:
                self.add("%s line %d" % (where, line), url)

    def add_markdown(self, rel):
        path = self.root / rel
        if not path.exists():
            self.notes.append("%s is missing; nothing crawled from it" % rel)
            return 0
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            seen = set()
            for m in re.finditer(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)", line):
                seen.add(m.group(1))
            for m in re.finditer(r"https?://[^\s<>()\[\]\"'`]+", line):
                seen.add(m.group(0).rstrip(".,;:!?*_"))
            for url in sorted(seen):
                self.add("%s:%d" % (rel, i), url)
        return 1

    def add_data(self):
        files = sorted(p for p in self.root.glob("data/**/*.json") if p.is_file())
        for path in files:
            rel = path.relative_to(self.root).as_posix()
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                self.add(rel, "!unparseable: %s" % e)
                continue
            if isinstance(doc, dict) and "fields" in doc:   # a schema block describes fields in prose
                doc = {k: v for k, v in doc.items() if k != "fields"}
            self._walk(doc, rel, Path(rel).stem)
        return len(files)

    def _walk(self, obj, rel, where, key=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                self._walk(v, rel, "%s.%s" % (where, k), str(k))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                self._walk(v, rel, "%s[%d]" % (where, i), key)
        elif isinstance(obj, str):
            self.add_data_string(obj.strip(), "%s: %s" % (rel, where), key)

    def add_data_string(self, s, label, key):
        """A whole-string link (a URL key, a site path, an absolute link to the site), or the links inside prose."""
        whole = URL_KEY.search(key) or LOCAL_SHAPE.match(s) or self.abs_in_text.fullmatch(s)
        if s and whole and not re.search(r"\s", s):
            self.add(label, s)
            return
        if "<" in s:
            for m in ATTR_LINK.finditer(s):
                self.add(label, html.unescape(m.group(2)))
        for m in self.abs_in_text.finditer(s):
            self.add(label, m.group(0).rstrip(".,;:!?"))

    def add_rendered_emails(self):
        """Best effort: every daily email (build_feed.issue_html) and weekly email (build_weekly.weekly_email_html),
        rendered in memory, so links in issues older than the feed's 30 items stay covered."""
        scripts = self.root / "scripts"
        if not (scripts / "build_feed.py").exists() or not (scripts / "build_weekly.py").exists():
            self.notes.append("emails not rendered in memory: %s has no build_feed.py or build_weekly.py" % scripts)
            return 0
        added, chatter = 0, io.StringIO()
        sys.path.insert(0, str(scripts))
        try:
            with contextlib.redirect_stdout(chatter), contextlib.redirect_stderr(chatter):
                try:
                    build_feed = self._module("build_feed", scripts)
                    runs = json.loads((self.root / "data/runs.json").read_text(encoding="utf-8"))
                    log = build_feed.corrections_log()
                    for i in build_feed.feed_items(runs):
                        run = runs[i]
                        pages = (run["report"], run.get("analysis") if run.get("format") == 2 else None)
                        later = [c for c in log if c.get("page") and c.get("page") in pages]
                        body = build_feed.issue_html(run, build_feed.prev_published(runs, i), later)
                        self.add_html("daily email %s (rendered)" % run["date"], body, "")
                        added += 1
                except Exception as e:   # noqa: BLE001 (best effort: feed.xml is the source of record)
                    self.notes.append("daily emails not rendered in memory (%s: %s); feed.xml still crawled"
                                      % (type(e).__name__, e))
                try:
                    build_weekly = self._module("build_weekly", scripts)
                    for path in sorted(self.root.glob("data/weekly/*.json")):
                        if not DATED.match(path.stem):
                            continue
                        w = json.loads(path.read_text(encoding="utf-8"))
                        self.add_html("weekly email %s (rendered)" % path.stem, build_weekly.weekly_email_html(w), "")
                        added += 1
                except Exception as e:   # noqa: BLE001
                    self.notes.append("weekly emails not rendered in memory (%s: %s)" % (type(e).__name__, e))
        finally:
            sys.path.remove(str(scripts))
        for line in chatter.getvalue().splitlines()[:3]:
            self.notes.append("while rendering emails: " + line.strip())
        return added

    @staticmethod
    def _module(name, scripts):
        """Import a site script from this tree's scripts/ (never another tree's copy)."""
        module = importlib.import_module(name)
        if Path(module.__file__).resolve().parent != scripts.resolve():
            raise ImportError("%s came from %s, not %s" % (name, module.__file__, scripts))
        return module

    # -- resolution ---------------------------------------------------------------------------------------------------
    @staticmethod
    def web_link(url):
        """The link, stripped, when it is relative or http(s); None for mailto:, javascript:, data: and the like."""
        u = url.strip()
        if not u or re.match(r"^(?:mailto|tel|javascript|data|blob|about|sms):", u, re.I):
            return None
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", u) and not re.match(r"^https?:", u, re.I):
            return None
        return u

    def resolve(self, url, base):
        """(local path, fragment) for a link to this site; None for an external or non-web link."""
        u = self.web_link(url)
        if u is None:
            return None
        full = urljoin(self.site + base, u)
        parts = urlsplit(full)
        host = (parts.hostname or "").lower()
        path = parts.path or "/"
        if host in self.site_hosts and path.startswith(self.site_prefix):
            local = path[len(self.site_prefix):]
        elif host == self.guid_host and (path + "/").startswith(self.guid_prefix):
            local = path[len(self.guid_prefix):] if path.startswith(self.guid_prefix) else ""
        else:
            return None
        return unquote(local), parts.fragment

    def target(self, local):
        """The file a local path serves (index.html for a folder; GitHub Pages' extensionless .html), or None."""
        p = (self.root / local).resolve() if local else self.root
        if self.root not in p.parents and p != self.root:
            return None
        if p.is_dir():
            p = p / "index.html"
        elif not p.exists() and not p.suffix and p.with_name(p.name + ".html").exists():
            p = p.with_name(p.name + ".html")
        return p

    def ids(self, path):
        if path not in self._ids:
            try:
                self._ids[path] = scan_html(path.read_text(encoding="utf-8")).ids
            except (OSError, UnicodeDecodeError):
                self._ids[path] = set()
        return self._ids[path]

    # -- "published before this run" (--published-warn) ----------------------------------------------------------------
    def _git_ok(self):
        if not hasattr(self, "_git"):
            try:
                top = subprocess.run(["git", "-C", str(self.root), "rev-parse", "--show-toplevel"], capture_output=True,
                                     text=True, timeout=20).stdout.strip()
                self._git = bool(top) and Path(top).resolve() == self.root
            except (OSError, subprocess.SubprocessError):
                self._git = False
            self._head = {}
        return self._git

    def head_text(self, rel):
        """The committed (HEAD) text of a file in this tree, '' when it isn't committed or git can't say."""
        if not self._git_ok():
            return ""
        if rel not in self._head:
            try:
                r = subprocess.run(["git", "-C", str(self.root), "show", "HEAD:" + rel], capture_output=True, timeout=20)
                self._head[rel] = r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""
            except (OSError, subprocess.SubprocessError):
                self._head[rel] = ""
        return self._head[rel]

    @staticmethod
    def source_file(where):
        """The committed file a link was read from (a rendered email: the data file it is rendered from)."""
        m = re.match(r"^(daily|weekly) email (\d{4}-\d{2}-\d{2}) \(rendered\)", where)
        if m:
            return "data/runs.json" if m.group(1) == "daily" else "data/weekly/%s.json" % m.group(2)
        if where.startswith("feed.xml"):
            return "feed.xml"
        return re.split(r":(?:\s|\d)", where, maxsplit=1)[0] if re.match(r"^[\w./-]+\.(?:html|json|md|xml)\b", where) else None

    def published(self, where, url):
        """True when this link was already in the committed version of its source file: published before this run."""
        rel = self.source_file(where)
        if not rel:
            return False
        head = self.head_text(rel)
        u = url.strip()
        return bool(head) and (u in head or html.escape(u, quote=True) in head or json.dumps(u)[1:-1] in head)

    def check(self):
        """({problem: [where, ...]} for the inbound sources, the same for the site pages (warnings), counts)."""
        broken, soft_broken, local_links, with_frag = {}, {}, 0, 0
        self.published_links = {}
        for where, url, base, soft in self.links:
            if url.startswith("!"):
                problem, local, frag = "%s can't be read: %s" % (where, url[1:].split(": ", 1)[-1]), None, ""
            else:
                problem, local, frag = self.check_link(where, url, base)
            local_links += bool(local)
            with_frag += bool(local and frag and not frag.startswith(":~:"))
            if problem:
                (soft_broken if soft else broken).setdefault(problem, []).append(where)
                if not soft and not url.startswith("!"):
                    self.published_links.setdefault(problem, []).append(self.published(where, url))
        return broken, soft_broken, local_links, with_frag

    def check_link(self, where, url, base):
        """(problem or None, the local path or None when the link is not to this site, fragment)."""
        r = self.resolve(url, base)
        if r is None:
            return None, None, ""
        local, frag = r
        path, shown = self.target(local), local or "/"
        if path is None:
            return "%s points outside the site" % url, shown, frag
        if not path.exists():
            known = KNOWN_BROKEN.get((where.split(":", 1)[0], url.strip()))
            if known:
                self.notes.append("known, not a failure: %s \u2192 %s (%s)" % (where, url.strip(), known))
                return None, shown, frag
            return "%s: no such file (%s)" % (shown, url), shown, frag
        name = unquote(frag)
        if not frag or frag.startswith(":~:") or path.suffix.lower() not in (".html", ".htm") or name == "top":
            return None, shown, frag
        if name not in self.ids(path):
            rel = path.relative_to(self.root).as_posix()
            return '%s#%s: no id "%s" in the static HTML of %s' % (shown, frag, name, rel), shown, frag
        return None, shown, frag


def print_problems(label, problems):
    for problem in sorted(problems):
        wheres = problems[problem]
        more = " and %d more" % (len(wheres) - 3) if len(wheres) > 3 else ""
        print("  %s: %s  [from %s%s]" % (label, problem, "; ".join(wheres[:3]), more))


def check_anchors(opts, names):
    crawl = Crawl(opts.root, names["SITE"], names["FEED_GUID_BASE"])
    n = crawl.add_pages() + crawl.add_feed() + crawl.add_markdown("docs/welcome-email.md") + crawl.add_data()
    emails = crawl.add_rendered_emails()
    site = crawl.add_site_pages()
    broken, soft, local_links, with_frag = crawl.check()   # check() adds the known-broken notes: print notes after it
    print("anchors: %d link(s) to this site from %d inbound file(s), %d email(s) rendered in memory and %d site "
          "page(s); %d with a fragment; %s and %s mapped to %s"
          % (local_links, n, emails, site, with_frag, names["SITE"], names["FEED_GUID_BASE"], opts.root))
    for note in crawl.notes:
        print("  note: " + note)
    promised = 0
    for page, ids in sorted(REQUIRED_ANCHORS.items()):
        path = opts.root / page
        if not path.exists():   # the page check names a missing page; the crawl names links to it
            print("  note: %s is not built here, so its promised anchors were not checked" % page)
            continue
        have = crawl.ids(path)
        for name in ids.split():
            promised += 1
            if name not in have:
                broken.setdefault("%s#%s: an anchor the spec promises is missing from the static HTML" % (page, name),
                                  []).append("spec 2.3")
    published = {}
    if opts.published_warn:
        for problem in list(broken):
            flags = crawl.published_links.get(problem) or []
            if flags and all(flags) and len(flags) == len(broken[problem]):
                published[problem] = broken.pop(problem)
    print_problems("PROBLEM", broken)
    print_problems("PUBLISHED (in a page or entry published before this run; tell the owner)", published)
    print_problems("WARN (a site page's own link; fix its generator)", soft)
    if not broken and published:
        print("  no broken link from this run; %d problem(s) above were already published before it (PUBLISHED: for "
              "the owner, not a failure); all %d anchors the spec promises are there" % (len(published), promised))
        return []
    if not broken:
        print("  every inbound link resolves: each target exists and each fragment is in its target's "
              "server-rendered HTML" + ("" if soft else "; so does every link on the site pages")
              + "; all %d anchors the spec promises are there" % promised)
        return []
    return ["%d anchor problem(s)" % len(broken)]


# ---------------------------------------------------------------------------------------------------------------------

def parse_widths(text):
    try:
        widths = [int(x) for x in text.split(",") if x.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError("--widths takes whole numbers, e.g. 375,1280")
    if not widths or any(w < 200 or w > 4000 for w in widths):
        raise argparse.ArgumentTypeError("--widths takes widths from 200 to 4000 px, e.g. 375,1280")
    return widths


def run_pages(pages, opts):
    """The browser part: failure labels, or None when Chrome is missing."""
    if not Path(opts.chrome).exists():
        print("smoke: Chrome not found at %s (set $SMOKE_CHROME)" % opts.chrome, file=sys.stderr)
        return None
    missing = [p for p in pages if not (opts.root / p.split("#", 1)[0]).is_file()]
    for p in missing:
        print("  %s  PROBLEM: no such file" % p)
    present = [p for p in pages if p not in missing]
    return missing + (check_pages(present, opts) if present else [])


def parse_args(argv):
    ap = argparse.ArgumentParser(description="Headless smoke check of the built site (read-only; see the docstring).")
    ap.add_argument("pages", nargs="*", help="pages to check, relative to the root (default: the standard set)")
    ap.add_argument("--widths", type=parse_widths, help="comma-separated iframe widths; fail when a page is wider")
    ap.add_argument("--anchors", action="store_true", help="also resolve every inbound link and fragment")
    ap.add_argument("--anchors-only", action="store_true", help="only the anchor crawl (no browser)")
    ap.add_argument("--published-warn", action="store_true",
                    help="a broken link already in the committed version of its source prints as PUBLISHED, not a failure")
    ap.add_argument("--root", default=str(ROOT), help="the tree to check (default: this script's repo)")
    ap.add_argument("--chrome", help="the Chrome binary (default: $SMOKE_CHROME or render_card.CHROME)")
    ap.add_argument("--jobs", type=int, default=4, help="pages loaded in parallel (default 4)")
    ap.add_argument("--settle", type=int, default=SETTLE_MS,
                    help="virtual ms a page gets after load (default %d)" % SETTLE_MS)
    ap.add_argument("--timeout", type=int, default=CHROME_TIMEOUT,
                    help="wall-clock seconds per page (default %d)" % CHROME_TIMEOUT)
    ap.add_argument("--list", action="store_true", help="print the default page list and exit")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="print notes: console lines, overflow that still fits, ready flags")
    return ap.parse_args(argv)


def main(argv=None):
    opts = parse_args(argv)
    opts.root = Path(opts.root).resolve()
    if not (opts.root / "index.html").exists():
        print("smoke: %s has no index.html; nothing to check" % opts.root, file=sys.stderr)
        return 2
    names = site_modules(opts.root)
    opts.chrome = opts.chrome or os.environ.get("SMOKE_CHROME") or names["CHROME"]

    pages, notes = default_pages(opts.root)
    if opts.pages:
        pages = [p.lstrip("/") for p in opts.pages]
    if opts.list:
        print("\n".join(pages))
        return 0
    for note in notes:
        print("note: " + note)

    failed = []
    if not opts.anchors_only:
        failed = run_pages(pages, opts)
        if failed is None:
            return 2
    if opts.anchors or opts.anchors_only:
        failed += check_anchors(opts, names)
    if failed:
        sys.stdout.flush()   # keep the verdict last when stdout and stderr share a pipe
        print("SMOKE CHECK FAILED: " + ", ".join(failed), file=sys.stderr)
        return 1
    at = " at %s px" % ",".join(map(str, opts.widths)) if opts.widths else ""
    parts = [] if opts.anchors_only else ["%d page(s)%s" % (len(pages), at)]
    if opts.anchors or opts.anchors_only:
        parts.append("anchors")
    print("smoke check passed: " + "; ".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
