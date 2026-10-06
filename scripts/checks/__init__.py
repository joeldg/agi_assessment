"""Checks added for redesign v2 (definitions v2.0, format-2 reports, page budgets).

check_data.py builds one Ctx and calls each module's check(ctx, ...). The modules never import
check_data (it runs as __main__): the helpers they share with it (check_url, append_only, js) come in
through Ctx. Every rule is a no-op until its input exists: no definitions entry in data/method.json,
no `defs`/`format` on a run, no data/agi_components.json.

    components.py  data/agi_components.json (spec 8.1, 11)
    method.py      definitions in force, methodChange, the boundary run's cells, method.json (8.3, 9.4, 11)
    reports_v2.py  the newest format-2 run, its short report and analysis page, build_report --check (8.2, 9, 11)
    pages.py       visible-word budgets of the built pages (2.2); WARN only, run with --pages
"""
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from html.parser import HTMLParser
from pathlib import Path

sys.dont_write_bytecode = True
_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from alarm_check import parse_date, version_tuple as _version_tuple  # noqa: E402  (one implementation)

COMPONENT_IDS = ["breadth", "quality", "reliability", "reasoning", "horizon", "autonomy", "learning", "generalization"]
SCALE_KEYS = ["far", "partial", "close", "met"]
RATINGS = {"verified fact", "credible report", "expert opinion", "forecast aggregate", "our inference", "speculation"}
HYP_KEYS = ["A", "B", "C", "D", "Dopen"]
ANALYSIS_IDS = ["alarm", "index", "gauges", "tripwires", "escape", "agi", "timeline", "roundup",
                "s1", "s2", "s3", "s4", "s5", "s6", "bottom"]
SHORT_IDS = ["s5", "s6", "timeline", "roundup", "tripwires", "gauges"]
MARK_BEGIN, MARK_END = "<!-- analysis:begin -->", "<!-- analysis:end -->"
WORD = re.compile(r"[A-Za-z0-9][\w'’.,%-]*")


class Ctx:
    """What a check needs: findings, the repo root, parsed data, git at the base, today, and the shared helpers."""

    def __init__(self, *, f, root, data, git, today, check_url, append_only, js, scan_page=None):
        self.f, self.root, self.data, self.git, self.today = f, Path(root), data, git, today
        self.check_url, self.append_only, self.js, self.scan_page = check_url, append_only, js, scan_page

    def read(self, rel):
        try:
            return (self.root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None


# ---------- small shared helpers ----------

def words(s):
    """Word count, the same rule as the prototype's word counter (final_shots/words.html)."""
    return len(WORD.findall(s or "")) if isinstance(s, str) else 0


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def iso(s):
    """A date from YYYY-MM-DD; only the first 10 characters are read, so "2026-09-17 (entry date …)" works."""
    return parse_date(s[:10]) if isinstance(s, str) else None


def version_tuple(v):
    """(2, 0) from "2.0"; None when there is no number in it."""
    return _version_tuple(v) or None


def _defs_in_force(method, d):
    """Definitions in force for a run dated d: the `definitions` of the last changelog entry (list order)
    that has one and is dated before d; "1.0" if none (spec 8.3)."""
    v = "1.0"
    log = method.get("changelog") if isinstance(method, dict) else None
    for e in log if isinstance(log, list) else []:
        if isinstance(e, dict) and e.get("definitions") and isinstance(e.get("date"), str) and e["date"] < str(d):
            v = str(e["definitions"])
    return v


def _round_grid(v):
    """Our grid: 0.1 steps below 1, 0.5 from 1 to 10, whole points above; half up, decimal arithmetic."""
    d = Decimal(str(v))
    step = Decimal("0.1") if d < 1 else Decimal("0.5") if d <= 10 else Decimal("1")
    return float((d / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step)


try:  # one implementation (sitekit, WP-F); the local copies only stand in until it lands
    from sitekit import defs_in_force  # noqa: F401
except ImportError:
    defs_in_force = _defs_in_force
try:
    from sitekit import round_grid  # noqa: F401
except ImportError:
    round_grid = _round_grid


def _run_defs(run):
    d = run.get("defs") if isinstance(run, dict) else None
    return str(d) if d else "1.0"


try:
    from sitekit import run_defs  # noqa: F401
except ImportError:
    run_defs = _run_defs


def prev_published(runs, i):
    """The published run that runs[i] is compared with: the latest earlier entry dated before it that has a
    report, isn't marked comparable false, and isn't an earlier copy of the same report. None for the first."""
    me = runs[i]
    for j in range(i - 1, -1, -1):
        r = runs[j]
        if (isinstance(r, dict) and r.get("report") and r.get("comparable") is not False
                and r["report"] != me.get("report") and str(r.get("date")) < str(me.get("date"))):
            return r
    return None


def definitions_entries(method):
    log = method.get("changelog") if isinstance(method, dict) else None
    return [e for e in (log if isinstance(log, list) else []) if isinstance(e, dict) and e.get("definitions")]


# ---------- HTML ----------

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
INLINE = {"a", "abbr", "b", "bdi", "bdo", "cite", "code", "data", "dfn", "em", "i", "kbd", "label", "mark", "q", "s",
          "samp", "small", "span", "strong", "sub", "sup", "time", "u", "var"}


class PageText(HTMLParser):
    """Visible words, roughly as a browser's innerText counts them: no head, script, style, noscript,
    template or [hidden]; never inside a closed <details> except its <summary>. `skip` names more regions
    to leave out: tag names ("nav", "footer", "table"), ".class" and "#id"."""

    ALWAYS = {"head", "script", "style", "noscript", "template", "title"}

    def __init__(self, skip=()):
        super().__init__(convert_charrefs=True)
        self.skip = set(skip)
        self.regions = []  # [tag, depth, kind ("skip" | "details"), in_summary]
        self.parts = []

    def _match(self, tag, a):
        if tag in self.ALWAYS or tag in self.skip or "hidden" in a:
            return True
        if a.get("id") and "#" + a["id"] in self.skip:
            return True
        return any("." + c in self.skip for c in (a.get("class") or "").split())

    def handle_starttag(self, tag, attrs):
        if tag not in INLINE:
            self.parts.append(" ")  # a block boundary separates words, as innerText's line breaks do
        if tag in VOID:
            return
        a = {k: (v if v is not None else "") for k, v in attrs}
        for r in self.regions:
            if r[0] == tag:
                r[1] += 1
        if self.regions and self.regions[-1][2] == "details" and tag == "summary" and self.regions[-1][1] == 1:
            self.regions[-1][3] = True
        if self._match(tag, a):
            self.regions.append([tag, 1, "skip", False])
        elif tag == "details" and "open" not in a:
            self.regions.append([tag, 1, "details", False])

    def handle_endtag(self, tag):
        if tag not in INLINE:
            self.parts.append(" ")
        if self.regions and self.regions[-1][2] == "details" and tag == "summary" and self.regions[-1][1] == 1:
            self.regions[-1][3] = False
        for r in self.regions:
            if r[0] == tag:
                r[1] -= 1
        while self.regions and self.regions[-1][1] <= 0:
            self.regions.pop()

    def handle_data(self, data):
        if all(r[2] == "details" and r[3] for r in self.regions):
            self.parts.append(data)

    def text(self):
        return " ".join("".join(self.parts).split())


def visible_words(html, skip=()):
    p = PageText(skip)
    p.feed(html or "")
    p.close()
    return words(p.text())


class Outline(HTMLParser):
    """ids in document order, subscribe boxes, head tags, comments, and the text and <li> count of chosen regions."""

    def __init__(self, regions=()):
        super().__init__(convert_charrefs=True)
        self.ids, self.subscribe, self.meta, self.canonical, self.comments = [], 0, {}, None, []
        self.want = set(regions)  # "#id" or ".class"
        self.open = []  # [key, tag, depth]
        self.li = {}
        self.rows = {}  # region key -> list of rows (list of cell texts)
        self._cell = None

    def handle_starttag(self, tag, attrs):
        a = {k: (v if v is not None else "") for k, v in attrs}
        cls = a.get("class", "").split()
        if a.get("id"):
            self.ids.append(a["id"])
        if "subscribe" in cls:
            self.subscribe += 1
        if tag == "meta" and (a.get("property") or a.get("name")):
            self.meta[a.get("property") or a.get("name")] = a.get("content")
        if tag == "link" and "canonical" in a.get("rel", "").lower().split():
            self.canonical = a.get("href")
        if tag in VOID:
            return
        for o in self.open:
            if o[1] == tag:
                o[2] += 1
            if tag == "li":
                self.li[o[0]] = self.li.get(o[0], 0) + 1
            if tag == "tr":
                self.rows.setdefault(o[0], []).append([])
            if tag in ("td", "th"):
                self._cell = []
        keys = (["#" + a["id"]] if a.get("id") else []) + ["." + c for c in cls]
        for k in keys:
            if k in self.want:
                self.open.append([k, tag, 1])
                self.li.setdefault(k, 0)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            text = " ".join("".join(self._cell).split())
            for o in self.open:
                if self.rows.get(o[0]):
                    self.rows[o[0]][-1].append(text)
            self._cell = None
        for o in self.open:
            if o[1] == tag:
                o[2] -= 1
        self.open = [o for o in self.open if o[2] > 0]

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_comment(self, data):
        self.comments.append(data.strip())


def outline(html, regions=()):
    o = Outline(regions)
    o.feed(html or "")
    o.close()
    return o
