"""Tests for scripts/checks/ and the check_data.py edits (spec 11). Stdlib unittest:

    python3 -m unittest discover -s scripts/tests -p 'test_checks.py'
    python3 scripts/tests/test_checks.py

fixtures/checks/base/ is a valid tree for 2026-10-06: the Oct 5 legacy reading, the method.json v2.0 entry dated
2026-10-05 (go-live the evening before) and the Oct 6 run, which is both the first format-2 report and the first
v2.0 reading, with its short report and analysis page. fixtures/checks/cases/*.json each break one ERROR rule:
`ops` edit the working tree, `head_ops` edit what git's HEAD holds (default: the base as committed), `call`
picks the check (default: the three v2 modules), `render` swaps the real build_report.render for a stub ("crash",
"differs"), and `expect` is part of the error the rule must print. The base pages are real renders by
scripts/build_report.py (WP-E_gen_fixtures.py writes them), so without `render` every case runs the real byte compare.
"""
import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import check_data  # noqa: E402
import checks  # noqa: E402
from checks import components, method, pages, reports_v2  # noqa: E402

FIX = HERE / "fixtures" / "checks"
BASE = FIX / "base"
TODAY = date(2026, 10, 6)


# ---------- harness ----------

def apply_ops(root, ops):
    for op in ops:
        path = root / op["file"]
        if op.get("remove"):
            path.unlink()
            continue
        if "write" in op:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(op["write"], encoding="utf-8")
            continue
        if "replace" in op:
            old, new = op["replace"]
            text = path.read_text(encoding="utf-8")
            assert old in text, "fixture replace target not found in %s: %r" % (op["file"], old[:60])
            path.write_text(text.replace(old, new, 1), encoding="utf-8")
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        keys = op.get("set") or op.get("del") or op.get("append")
        if keys is None and "del" in op:
            keys = op["del"]
        cur = doc
        for k in keys[:-1]:
            cur = cur[k]
        last = keys[-1]
        if "set" in op:
            cur[last] = copy.deepcopy(op["value"])
        elif "del" in op:
            del cur[last]
        else:
            cur[last].append(copy.deepcopy(op["value"]))
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


class FakeGit:
    """Git at HEAD, served from a directory (by default the base tree as committed)."""

    def __init__(self, head_root):
        self.head, self.ok, self.base = Path(head_root), True, "HEAD"

    def show(self, rel):
        try:
            return (self.head / rel).read_text(encoding="utf-8")
        except (OSError, TypeError):
            return None

    def show_json(self, rel):
        text = self.show(rel)
        try:
            return json.loads(text) if text is not None else None
        except ValueError:
            return None

    def lines(self, *args):
        if args[:2] == ("ls-tree", "--name-only"):
            sub = args[-1].rstrip("/")
            return sorted(p.relative_to(self.head).as_posix() for p in (self.head / sub).glob("*") if p.is_file())
        return []


class Tree:
    """A temporary work tree and HEAD tree, both copied from the base, then edited by a case."""

    def __init__(self, case=None):
        case = case or {}
        self.tmp = Path(tempfile.mkdtemp(prefix="checks-"))
        self.work, self.head = self.tmp / "work", self.tmp / "head"
        shutil.copytree(BASE, self.work)
        shutil.copytree(BASE, self.head)
        apply_ops(self.head, case.get("head_ops", []))
        apply_ops(self.work, case.get("ops", []))

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def fake_render(kind, root):
    """A stand-in for build_report.render: "crash" raises, "differs" changes the h1 of the files on disk."""
    def render(d, runs_path=None, body=None):
        if kind == "crash":
            raise RuntimeError("fixture crash")
        short = (root / ("reports/%s.html" % d)).read_text(encoding="utf-8")
        analysis = (root / ("reports/%s-analysis.html" % d)).read_text(encoding="utf-8")
        if kind == "differs":
            short = short.replace("</h1>", " X</h1>", 1)
        return short, analysis
    return render


def run_checks(tree, call="modules", render=None, today=TODAY):
    """Runs one check over the tree; returns (errors + frozen, warnings)."""
    f = check_data.Findings()
    check_data.ROOT_DIR = tree.work
    data = check_data.load_all(tree.work, f)
    runs = data.get("data/runs.json")
    git = FakeGit(tree.head)
    latest = max(i for i, r in enumerate(runs) if r.get("report")) if isinstance(runs, list) else None
    newest = max(r["date"] for r in runs) if isinstance(runs, list) else None
    if call == "check_probs":
        for i, r in enumerate(runs):
            check_data.check_probs(f, "runs[%d]" % i, r, newest)
    elif call == "immutability":
        check_data.check_immutability(f, git, data, runs, newest)
    elif call == "urls":
        check_data.check_data_urls(f, data, runs, newest)
    else:
        ctx = checks.Ctx(f=f, root=tree.work, data=data, git=git, today=today, check_url=check_data.check_url,
                         append_only=check_data.append_only, js=check_data.js, scan_page=check_data.scan_page)
        method.check(ctx, runs, latest)
        components.check(ctx, runs)
        reports_v2.check(ctx, runs, latest, render=fake_render(render, tree.work) if render else None)
    return f.errors + f.frozen, f.warnings


# ---------- tests ----------

class BaseTree(unittest.TestCase):
    def test_base_has_no_errors(self):
        for call in ("modules", "check_probs", "immutability", "urls"):
            t = Tree()
            try:
                errs, warns = run_checks(t, call)
            finally:
                t.close()
            self.assertEqual(errs, [], call)
            self.assertFalse([w for w in warns if "build_report" in w], call)

    def test_base_pages_are_real_renders(self):
        """The fixture pages are exactly what build_report.render writes for the fixture run (WP-D, spec 9.3)."""
        import build_report
        t = Tree()
        try:
            got = build_report.render("2026-10-06", str(t.work / "data/runs.json"))
            self.assertEqual(got[0], (t.work / "reports/2026-10-06.html").read_text(encoding="utf-8"))
            self.assertEqual(got[1], (t.work / "reports/2026-10-06-analysis.html").read_text(encoding="utf-8"))
        finally:
            t.close()

    def test_real_render_inside_window_has_no_errors(self):
        """The morning of 2026-10-06, before the commit: the run and both pages are new, the real render matches."""
        t = Tree({"head_ops": [{"file": "data/runs.json", "del": [-1]},
                               {"file": "reports/2026-10-06.html", "remove": True},
                               {"file": "reports/2026-10-06-analysis.html", "remove": True}]})
        try:
            self.assertTrue(reports_v2.in_window(
                checks.Ctx(f=check_data.Findings(), root=t.work, data={}, git=FakeGit(t.head), today=TODAY,
                           check_url=None, append_only=None, js=check_data.js),
                json.loads((t.work / "data/runs.json").read_text(encoding="utf-8"))[-1],
                ["reports/2026-10-06.html", "reports/2026-10-06-analysis.html"]))
            errs, warns = run_checks(t)
        finally:
            t.close()
        self.assertEqual(errs, [])
        self.assertFalse([w for w in warns if "build_report" in w], warns)

    def test_real_render_with_corrections_has_no_errors(self):
        """Seven corrections, rendered by build_report: the box shows 5 and links the rest, #corrections lists 7,
        and every check agrees with the real markup (the contract in requests_WP-E.md)."""
        import build_report
        corr = [{"date": "2026-10-0%d" % (1 + j % 5), "page": "reports/2026-10-05.html", "was": "x%d" % j,
                 "now": "y%d" % j} for j in range(7)]
        t = Tree({"ops": [{"file": "data/runs.json", "set": [-1, "corrections"], "value": corr}],
                  "head_ops": [{"file": "data/runs.json", "del": [-1]}]})
        try:
            short, analysis = build_report.render("2026-10-06", str(t.work / "data/runs.json"))
            (t.work / "reports/2026-10-06.html").write_text(short, encoding="utf-8")
            (t.work / "reports/2026-10-06-analysis.html").write_text(analysis, encoding="utf-8")
            o = checks.outline(short, [".rp-corr"])
            self.assertEqual(o.li[".rp-corr"], 5)
            self.assertEqual(checks.outline(analysis, ["#corrections"]).li["#corrections"], 7)
            errs, warns = run_checks(t)
        finally:
            t.close()
        self.assertEqual(errs, [])
        self.assertFalse([w for w in warns if "build_report" in w], warns)

    def test_real_render_ignores_live_files_after_the_morning(self):
        """B1: Friday edits to agi_components, escape and calendar never change the committed report's render."""
        t = Tree({"ops": [{"file": "data/agi_components.json", "set": ["components", 1, "glance"], "value": "Changed."},
                          {"file": "data/escape.json", "append": ["indicators"], "value": {"key": "new"}},
                          {"file": "data/calendar.json", "write": "[]\n"}]})
        try:
            errs, warns = run_checks(t, today=date(2026, 10, 9))
        finally:
            t.close()
        self.assertEqual(errs, [])
        self.assertFalse([w for w in warns if "build_report" in w], warns)
        self.assertTrue(any("snapshot differs" in w for w in warns), warns)

    def test_real_render_failure_outside_window_is_a_warning(self):
        """A committed run that build_report can no longer render (here: its body ids were edited in HEAD too)."""
        edit = {"file": "reports/2026-10-06-analysis.html", "replace": ['<section id="s6">', '<section id="sx">']}
        t = Tree({"ops": [edit], "head_ops": [edit]})
        try:
            errs, warns = run_checks(t)
        finally:
            t.close()
        self.assertFalse([e for e in errs if "build_report" in e], errs)
        self.assertTrue(any(w.startswith("build_report: ReportError: analysis body") for w in warns), warns)

    def test_missing_build_report_is_reported(self):
        """load_render names a missing module instead of skipping the compare."""
        saved = sys.modules.pop("build_report", None)
        sys.modules["build_report"] = None  # makes `import build_report` raise ImportError(name="build_report")
        try:
            render, why = reports_v2.load_render()
        finally:
            del sys.modules["build_report"]
            if saved is not None:
                sys.modules["build_report"] = saved
        self.assertIsNone(render)
        self.assertIn("scripts/build_report.py is missing", why)

    def test_go_live_evening_has_no_errors(self):
        """Tonight: the method entry is in, the newest run is still the legacy Oct 5 reading."""
        t = Tree({"ops": [{"file": "data/runs.json", "del": [-1]},
                          {"file": "reports/2026-10-06.html", "remove": True},
                          {"file": "reports/2026-10-06-analysis.html", "remove": True}]})
        try:
            errs, _ = run_checks(t, today=date(2026, 10, 5))
        finally:
            t.close()
        self.assertEqual(errs, [])

    def test_before_go_live_is_a_no_op(self):
        """No definitions entry, no agi_components.json, legacy runs only: every new rule is silent."""
        t = Tree({"ops": [{"file": "data/runs.json", "del": [-1]},
                          {"file": "data/method.json", "del": ["changelog", -1]},
                          {"file": "data/method.json", "set": ["version"], "value": "1.2"},
                          {"file": "data/agi_components.json", "remove": True}],
                  "head_ops": [{"file": "data/method.json", "del": ["changelog", -1]},
                               {"file": "data/method.json", "set": ["version"], "value": "1.2"}]})
        try:
            errs, warns = run_checks(t, today=date(2026, 10, 5))
        finally:
            t.close()
        self.assertEqual(errs, [])
        self.assertEqual(warns, [])

    def test_same_day_rerun_keeps_method_change(self):
        """A rerun replaces the Oct 6 entry; it must still carry methodChange (M2)."""
        t = Tree({"head_ops": [{"file": "data/runs.json", "del": [-1, "methodChange"]}],
                  "ops": [{"file": "data/runs.json", "del": [-1, "methodChange"]}]})
        try:
            errs, _ = run_checks(t)
        finally:
            t.close()
        self.assertTrue(any("needs methodChange" in e for e in errs), errs)

    def test_render_differs_outside_window_is_a_warning(self):
        """A committed report that no longer matches its render: WARN, never ERROR (a Friday weekly)."""
        t = Tree()
        try:
            errs, warns = run_checks(t, render="differs")
        finally:
            t.close()
        self.assertEqual(errs, [])
        self.assertTrue(any("differs from build_report's render" in w for w in warns), warns)

    def test_friday_status_change_after_morning_run(self):
        """The weekly changes a status (with its history row) after the morning's format-2 run: a WARN only."""
        t = Tree({"ops": [{"file": "data/agi_components.json", "set": ["components", 1, "status"], "value": "partial"},
                          {"file": "data/agi_components.json", "set": ["components", 1, "statusBasis"],
                           "value": "Partial: RLI 25% reaches the Partial mark."},
                          {"file": "data/agi_components.json", "set": ["components", 1, "headline", "value"],
                           "value": 26},
                          {"file": "data/agi_components.json", "append": ["history"],
                           "value": {"date": "2026-10-09", "id": "quality", "from": "far", "to": "partial",
                                     "why": "x"}}]})
        try:
            errs, warns = run_checks(t, today=date(2026, 10, 9))
        finally:
            t.close()
        self.assertEqual(errs, [])
        self.assertTrue(any("snapshot differs" in w for w in warns), warns)


class FailingFixtures(unittest.TestCase):
    """One failing fixture per new ERROR rule."""

    def test_cases(self):
        cases = sorted((FIX / "cases").glob("*.json"))
        self.assertGreaterEqual(len(cases), 60)
        for path in cases:
            case = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(case=path.stem, rule=case["rule"]):
                t = Tree(case)
                try:
                    errs, warns = run_checks(t, case.get("call", "modules"), case.get("render"))
                finally:
                    t.close()
                self.assertTrue(any(case["expect"] in e for e in errs),
                                "%s: expected an ERROR containing %r\nerrors: %s\nwarnings: %s" % (
                                    path.stem, case["expect"], "\n  ".join(errs), "\n  ".join(warns[:5])))


class Helpers(unittest.TestCase):
    def test_defs_in_force(self):
        m = {"changelog": [{"version": "1.0", "date": "2026-09-29"},
                           {"version": "2.0", "date": "2026-10-05", "definitions": "2.0"}]}
        self.assertEqual(checks.defs_in_force(m, "2026-10-05"), "1.0")  # the entry day's own morning run
        self.assertEqual(checks.defs_in_force(m, "2026-10-06"), "2.0")
        m["changelog"].append({"version": "2.1", "date": "2026-10-05", "definitions": "1.0"})  # same-day withdrawal
        self.assertEqual(checks.defs_in_force(m, "2026-10-06"), "1.0")
        self.assertEqual(checks.defs_in_force({}, "2026-10-06"), "1.0")
        self.assertEqual(checks._defs_in_force(m, "2026-10-06"), checks.defs_in_force(m, "2026-10-06"))

    def test_round_grid(self):
        for v, want in ((2.27, 2.5), (2.3, 2.5), (2.2, 2.0), (0.855, 0.9), (0.536, 0.5), (0.25 * 0.6, 0.2),
                        (44.5, 45), (34.65, 35), (0.05, 0.1), (10.2, 10), (1.0, 1.0)):
            self.assertEqual(checks.round_grid(v), want, v)
            self.assertEqual(checks._round_grid(v), want, v)

    def test_news_moved(self):
        run = {"changes": ["Method change (definitions v2.0): A goes from 1% to 0.5% now.",
                           "A new METR result moved the gap gauge from 3 to 4 months.",
                           "AI R&D share rose from 26% to 28%.",
                           "C goes from 0.5% to 1% on the leaked memo."]}
        self.assertFalse(method.news_moved(run, "A"))
        self.assertFalse(method.news_moved(run, "D"))
        self.assertTrue(method.news_moved(run, "C"))
        self.assertTrue(method.method_named(run, "A"))

    def test_visible_words(self):
        html = ('<html><head><title>t w o</title><script>var a = 1;</script></head><body><nav>one two</nav>'
                '<p>alpha beta <span class="sr-only">hidden words</span></p>'
                '<details><summary>open me</summary><p>closed body text</p></details>'
                '<details open><summary>s</summary><p>open body</p></details>'
                '<div class="subscribe">sub box</div><table><tr><td>cell</td></tr></table><br>'
                '<footer>foot</footer></body></html>')
        self.assertEqual(checks.visible_words(html, ("nav", "footer", ".subscribe", ".sr-only", "table")), 7)

    def test_outline_rows_and_li(self):
        o = checks.outline('<section id="s5"><table><tr><th>A</th><th>Change today</th></tr>'
                           '<tr><td>B · x</td><td>no change</td></tr></table></section>'
                           '<aside class="callout rp-corr"><ul><li>1</li><li>2</li></ul></aside>',
                           ["#s5", ".rp-corr"])
        self.assertEqual(o.rows["#s5"], [["A", "Change today"], ["B · x", "no change"]])
        self.assertEqual(o.li[".rp-corr"], 2)


class PageBudgets(unittest.TestCase):
    def test_agi_page_budgets_the_tracker_separately(self):
        words = " ".join("w%d" % i for i in range(1600))   # over the static view's 1,500-word budget
        html = '<main><p>Outside the tracker.</p><div id="agi-map"><p>%s</p></div></main><footer>x</footer>' % words
        t = Tree({"ops": [{"file": "agi.html", "write": html}]})
        try:
            f = check_data.Findings()
            check_data.ROOT_DIR = t.work
            data = check_data.load_all(t.work, f)
            ctx = checks.Ctx(f=f, root=t.work, data=data, git=FakeGit(t.head), today=TODAY,
                             check_url=check_data.check_url, append_only=check_data.append_only, js=check_data.js)
            lines = pages.check(ctx, data.get("data/runs.json"))
        finally:
            t.close()
        self.assertEqual(f.errors, [])
        self.assertTrue(any(re.search(r"agi\.html\s+3 words", x) for x in lines), lines)
        self.assertTrue(any("agi.html #agi-map" in x and "1600" in x and "OVER" in x for x in lines), lines)
        self.assertTrue(any("agi.html #agi-map" in w for w in f.warnings), f.warnings)


class Worktree(unittest.TestCase):
    """check_data.py on the repository itself: exit 0; --pages never fails."""

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / "check_data.py"), *args], cwd=str(REPO),
                              capture_output=True, text=True, timeout=300)

    def test_check_data_exits_0(self):
        p = self.run_cli()
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])

    def test_pages_only_warns(self):
        p = self.run_cli("--pages")
        self.assertEqual(p.returncode, 0, p.stdout[-2000:] + p.stderr[-2000:])
        self.assertNotIn("ERROR", p.stdout)
        self.assertIn("PAGES  index.html", p.stdout)


class StaleOrMissingWarnings(unittest.TestCase):
    def test_component_staleness_warns(self):
        t = Tree()
        try:
            errs, warns = run_checks(t, today=date(2026, 11, 1))
        finally:
            t.close()
        self.assertEqual(errs, [])
        self.assertTrue(any("agi_components.lastReviewed=2026-10-05 is more than 10 days old" in w for w in warns),
                        warns)
        self.assertTrue(any("is more than 14 days old" in w for w in warns), warns)

    def test_headline_at_bar_warns(self):
        t = Tree({"ops": [{"file": "data/agi_components.json", "set": ["components", 0, "headline", "value"],
                           "value": 85},
                          {"file": "data/agi_components.json", "set": ["components", 0, "statusBasis"],
                           "value": "Far: the GDPval half is unmeasured, so this does not count."}]})
        try:
            errs, warns = run_checks(t)
        finally:
            t.close()
        self.assertEqual(errs, [])
        self.assertTrue(any("headline at the bar; other parts pending" in w for w in warns), warns)


if __name__ == "__main__":
    unittest.main()
