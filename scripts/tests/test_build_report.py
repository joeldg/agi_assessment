"""Tests for the report pipeline (WP-D, spec 9): build_report.py, the v2 email in build_feed.py, render_card.py's
format-2 and weekly boundary rules, kit_broadcast.daily_lists and build_money's no-op write. Stdlib unittest:

    python3 -m unittest discover -s scripts/tests -p 'test_build_report.py'
    python3 scripts/tests/test_build_report.py

Fixtures (regenerate with .claude/work/redesign/build/WP-D_gen_fixtures.py):
  run_v2.json               Oct 4 (legacy, trimmed) + Oct 5 converted to format 2 under defs "1.0"
  run_v2_cutover.json       Oct 5 (legacy, trimmed) + the first v2.0 reading on Oct 6 (method change)
  run_v2_41corrections.json run_v2.json with the 2026-09-30 correction load (41) on the Oct 5 reading
  analysis_body.html        the Oct 5 long-form sections as an analysis body fragment
Nothing here writes into the repo: every render goes to a temporary directory.
"""
import contextlib
import copy
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import build_feed  # noqa: E402
import build_report as br  # noqa: E402
import kit_broadcast  # noqa: E402
import render_card  # noqa: E402
from checks import ANALYSIS_IDS, SHORT_IDS, outline, visible_words  # noqa: E402

FIX = HERE / "fixtures"
BODY = (FIX / "analysis_body.html").read_text()
PROSE_SKIP = ("nav", "footer", "table", ".subscribe", ".share", ".sr-only")
LIVE = ("agi_components.json", "alarm.json", "escape.json", "calendar.json")


def runs(name):
    return json.loads((FIX / f"{name}.json").read_text())


def newest(name):
    return runs(name)[-1]["date"]


def render(name, mutate=None, body=BODY):
    """Render a fixture (optionally changed by mutate(runs)) from a temporary runs file; returns (short, analysis)."""
    rs = runs(name)
    if mutate:
        mutate(rs)
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "runs.json"
        p.write_text(json.dumps(rs, ensure_ascii=False))
        with contextlib.redirect_stderr(io.StringIO()):
            return br.render(rs[-1]["date"], str(p), body)


def cli(argv):
    """Run build_report.main in-process: (exit code, stdout + stderr)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = br.main(argv)
        except SystemExit as x:
            code = x.code
    return code, out.getvalue()


def tree(name):
    """A temporary site tree: the live data files copied from the repo and the fixture as data/runs.json."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "data").mkdir()
    for f in LIVE:
        shutil.copy(REPO / "data" / f, tmp / "data" / f)
    (tmp / "data/runs.json").write_text(json.dumps(runs(name), indent=1, ensure_ascii=False) + "\n")
    (tmp / "body.html").write_text(BODY)
    return tmp


class ShortReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v2 = render("run_v2")
        cls.cut = render("run_v2_cutover")
        cls.c41 = render("run_v2_41corrections")

    def test_two_subscribe_boxes_each(self):
        for short, analysis in (self.v2, self.cut, self.c41):
            self.assertEqual(outline(short).subscribe, 2)
            self.assertEqual(outline(analysis).subscribe, 2)

    def test_head_tags(self):
        for (short, analysis), d in ((self.v2, "2026-10-05"), (self.cut, "2026-10-06")):
            for html, path in ((short, f"reports/{d}.html"), (analysis, f"reports/{d}-analysis.html")):
                o = outline(html)
                self.assertEqual(o.canonical, br.SITE + path)
                self.assertEqual(o.meta["og:url"], br.SITE + path)
                self.assertEqual(o.meta["og:image"], f"{br.SITE}cards/{d}.png")
                self.assertEqual(o.meta["og:type"], "article")

    def test_required_ids(self):
        ids = outline(self.v2[0]).ids
        for i in SHORT_IDS + ["agi", "index", "alarm", "needle", "escape", "bottom"]:
            self.assertEqual(ids.count(i), 1, i)
        o = outline(self.v2[1])
        order = [i for i in o.ids if i in ANALYSIS_IDS]
        self.assertEqual(order, ANALYSIS_IDS)
        self.assertEqual(o.comments.count(br.MARK_BEGIN[4:-3].strip()), 1)
        self.assertEqual(o.comments.count(br.MARK_END[4:-3].strip()), 1)

    def test_prose_budgets(self):
        self.assertLessEqual(visible_words(self.v2[0], PROSE_SKIP), 700)
        self.assertLessEqual(visible_words(self.cut[0], PROSE_SKIP), 700)
        self.assertLessEqual(visible_words(self.c41[0], PROSE_SKIP), 1000)

    def test_correction_box_caps_at_five_and_links_the_rest(self):
        short, analysis = self.c41
        o = outline(short, [".rp-corr"])
        self.assertEqual(o.li[".rp-corr"], 5)
        self.assertIn("36 more corrections →", short)
        self.assertIn('href="2026-10-05-analysis.html#corrections"', short)
        self.assertEqual(outline(analysis, ["#corrections"]).li["#corrections"], 41)
        self.assertNotIn("rp-corr", self.v2[0])  # no box on a day without corrections

    def test_data_is_escaped(self):
        def evil(rs):
            rs[-1]["verdict"] = 'A <script>alert(1)</script> "day"'
            rs[-1]["needle"]["brief"] = "<img src=x onerror=alert(1)>"
            rs[-1]["needle"]["url"] = "javascript:alert(1)"
        with self.assertRaises(br.ReportError):  # a javascript: link is refused outright
            render("run_v2", evil)

        def evil2(rs):
            rs[-1]["verdict"] = 'A <script>alert(1)</script> "day"'
            rs[-1]["needle"]["brief"] = "<img src=x onerror=alert(1)>"
        short, analysis = render("run_v2", evil2)
        self.assertNotIn("<script>alert", short)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", short)
        self.assertNotIn("<img src=x", short)
        self.assertNotIn("<script>alert", analysis)

    def test_two_renders_are_identical(self):
        self.assertEqual(render("run_v2"), self.v2)
        self.assertEqual(render("run_v2_cutover"), self.cut)

    def test_legacy_shape_numbers_and_cells(self):
        rows = outline(self.v2[0], ["#s5"]).rows["#s5"]
        self.assertIn("Change today", rows[0])
        self.assertEqual([r[0] for r in rows[1:]], [label for _, label in br.ROWS])
        self.assertTrue(all(r[4] == "no change" for r in rows[1:]))
        self.assertIn("v1.0 bar", self.v2[0])  # defs 1.0 numbers next to the v2.0 parts are labelled
        self.assertNotIn("Method change today", self.v2[0])

    def test_cutover_reading(self):
        short = self.cut[0]
        self.assertIn("Method change today:", short)
        self.assertIn("parts sum to 2.3; shown as 2.5 on our rounding grid", short)
        self.assertIn('class="ix-round"', short)
        rows = {r[0]: r for r in outline(short, ["#s5"]).rows["#s5"][1:]}
        for label in ("AGI anywhere", "A · Hidden AGI", "C · Covert AGI actor", "D · Covert government influence",
                      "D-open · Open government influence"):
            self.assertEqual(rows[label][4], "method change (definitions v2.0)", label)
        self.assertEqual(rows["B · Hidden self-improvement"][4], "no change")
        self.assertIn("Hidden AGI Index, method change (definitions v2.0)", short)
        self.assertIn("1.7 points are hidden self-improvement", short)

    def test_news_move_on_the_boundary_shows_both(self):
        def news(rs):
            rs[-1]["changes"].append("A rises from 1% to 1.5% now on a lab disclosure (credible report), before the "
                                     "method change.")
        rows = {r[0]: r for r in outline(render("run_v2_cutover", news)[0], ["#s5"]).rows["#s5"][1:]}
        self.assertEqual(rows["A · Hidden AGI"][4], "▲ +0.5 pts news; then method change (definitions v2.0)")
        self.assertEqual(rows["C · Covert AGI actor"][4], "method change (definitions v2.0)")

    def test_degraded_mode_renders_without_optional_fields(self):
        def strip(rs):
            r = rs[-1]
            for k in ("tripwireChanges", "componentLeads", "dates", "furthest"):
                r.pop(k, None)
            r["escape"].pop("newEvidence")
            for k in ("since", "icon", "status", "name"):
                r["alarm"].pop(k)
            for g in r["roundup"]:
                for it in g["items"]:
                    it.pop("rating", None)
        rs = runs("run_v2")
        strip(rs)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "runs.json"
            p.write_text(json.dumps(rs))
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                short, _ = br.render("2026-10-05", str(p), BODY)
        self.assertIn('id="s6"', short)
        self.assertIn("WARN", err.getvalue())
        self.assertIn("dates snapshot is missing", err.getvalue())


class FixRound1(unittest.TestCase):
    """Review round 1 (2026-10-05): ED5, R1-03, R1-06/ED7, R1-07, R1-10, R1-11, R1-17/M3, M2, V3, V4."""

    def test_quiet_day_never_says_what_moved_the_needle(self):
        short = render("run_v2_cutover")[0]
        self.assertTrue(runs("run_v2_cutover")[-1]["needle"]["quiet"])
        self.assertNotIn("What moved the needle", short)
        self.assertIn('<p class="kicker">Quiet day</p>', short)

    def test_w_linked_confirmed_signal_is_amber_and_capped(self):
        def change(rs):
            rs[-1]["tripwireChanges"] = [{"id": "outsider-incidents", "from": "watching", "to": "tripped", "why": "x"},
                                         {"id": "evaluator-access", "from": "watching", "to": "tripped", "why": "y"}]
            for tw in rs[-1]["tripwires"]:
                if tw["id"] == "evaluator-access":
                    tw["trigger"] = "X1"   # an X-linked signal stays red
        short = render("run_v2", change)[0]
        sig = short.split('id="tripwires"', 1)[1].split("</section>", 1)[0]
        self.assertIn('ico-warn" aria-hidden="true">●</span> ', sig)
        self.assertIn("→ Confirmed · counts toward Watch.", sig)
        self.assertIn('ico-crit" aria-hidden="true">●</span> ', sig)
        email = build_feed.issue_html_v2(*self.email_args(change))
        self.assertIn("Confirmed · counts toward Watch", email)

    def email_args(self, mutate):
        rs = runs("run_v2")
        mutate(rs)
        return rs[-1], build_feed.prev_published(rs, len(rs) - 1), []

    def test_background_items_read_earlier_event_everywhere(self):
        def bg(rs):
            for g in rs[-1]["roundup"]:
                for it in g["items"]:
                    if it.get("top"):
                        it["date"] = "Oct 2 (background)"
                        return
        short = render("run_v2", bg)[0]
        self.assertIn('<span class="rdate">Oct 2 (earlier event)</span>', short)
        self.assertNotIn("first reported", short)
        rs = runs("run_v2")
        bg(rs)
        email = build_feed.issue_html_v2(rs[-1], build_feed.prev_published(rs, len(rs) - 1), [])
        self.assertIn("Oct 2 (earlier event)", email)
        self.assertNotIn("(background)", email)

    def test_floor_chip_links_its_one_home(self):
        self.assertIn('<a href="../disclosure-lag.html#floor"><abbr class="chip"', render("run_v2")[0])

    def test_five_long_corrections_never_exit_2(self):
        long = " ".join(["word"] * 95)
        def corr(rs):
            rs[-1]["corrections"] = [{"date": "2026-10-05", "page": "reports/2026-10-01.html", "item": "x",
                                      "was": long, "now": long, "url": "https://example.org/x"}] * 5
            rs[-1]["verdict"] = " ".join(["verdict"] * 30)
            rs[-1]["needle"]["brief"] = " ".join(["brief"] * 100)
        short = render("run_v2", corr)[0]   # no ReportError: the box counts toward the 700-word budget only
        self.assertGreater(visible_words(short, PROSE_SKIP), 1000)
        self.assertLessEqual(visible_words(short, PROSE_SKIP + (".rp-corr",)), 1000)

    def test_rendered_files_are_world_readable(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            code, out = cli(["--date", newest("run_v2"), "--runs", str(FIX / "run_v2.json"), "--body",
                             str(FIX / "analysis_body.html"), "--out", str(tmp)])
            self.assertEqual(code, 0, out)
            for f in (tmp / "reports").glob("*.html"):
                self.assertEqual(f.stat().st_mode & 0o777, 0o644, f.name)
        finally:
            shutil.rmtree(tmp)

    def test_another_index_is_never_index_news(self):
        def rli(rs):
            rs[-1]["changes"].append("The Remote Labor Index (RLI) top score rose from 20.8% to 22.4% (GPT-6 Astra); no AGI "
                                     "part changes status.")
            rs[-1]["changes"].append("Method change (definitions v2.0): the Hidden AGI Index stays at 2.5% (about 2.3 "
                                     "before rounding, down from about 2.5).")
        short = render("run_v2_cutover", rli)[0]
        self.assertIn("Hidden AGI Index, method change (definitions v2.0)</p>", short)
        self.assertNotIn("news; then method change (definitions v2.0)</p>", short.split('id="index"', 1)[1][:3000])
        sys.path.insert(0, str(SCRIPTS))
        from pages import common
        rs = runs("run_v2_cutover")
        rli(rs)
        prev = build_feed.prev_published(rs, len(rs) - 1)
        self.assertEqual(common.delta_text(rs[-1], prev, "index"), "method change (definitions v2.0)")
        self.assertEqual(br.change_cell(rs[-1], prev, "index"), "method change (definitions v2.0)")

    def test_relative_link_to_a_missing_page_exits_2(self):
        body = BODY.replace('href="../trends.html"', 'href="trends.html"', 1)
        self.assertNotEqual(body, BODY)
        with self.assertRaises(br.ReportError) as cm:
            render("run_v2", body=body)
        self.assertEqual(cm.exception.code, 2)
        self.assertIn('href "trends.html" points at reports/trends.html, which does not exist', str(cm.exception))

    def test_probability_table_reads_as_cards_on_phones(self):
        short = render("run_v2_cutover")[0]
        self.assertIn('<table class="rp-prob">', short)
        self.assertIn('data-label="Change today">method change (definitions v2.0)</td>', short)

    def test_full_analysis_is_first_in_the_page_nav(self):
        short = render("run_v2")[0]
        nav = short.split('<nav class="top rp-top"', 1)[1].split("</nav>", 1)[0]
        self.assertTrue(nav.split("<a ", 2)[1].startswith('href="2026-10-05-analysis.html">Full analysis'), nav[:200])


class BadInput(unittest.TestCase):
    def assertExit2(self, mutate, needle):
        with self.assertRaises(br.ReportError) as cm:
            render("run_v2", mutate)
        self.assertEqual(cm.exception.code, 2)
        self.assertIn(needle, str(cm.exception))

    def test_string_in_tripwire_changes(self):
        self.assertExit2(lambda rs: rs[-1].__setitem__("tripwireChanges", ["W3 tripped"]),
                         "tripwireChanges[0]: expected an object with id, from, to, why; got a string")

    def test_escape_changes_shape(self):
        self.assertExit2(lambda rs: rs[-1]["escape"].__setitem__("changes", [{"key": "money"}]), "escape.changes[0]")

    def test_index_parts_off_the_grid(self):
        self.assertExit2(lambda rs: rs[-1]["indexParts"][1].__setitem__("v", 0.4), "indexParts: the parts sum to")

    def test_unknown_component(self):
        self.assertExit2(lambda rs: rs[-1]["components"].__setitem__("embodiment", {}), "unknown component id")

    def test_missing_needle_rating(self):
        self.assertExit2(lambda rs: rs[-1]["needle"].pop("rating"), "needle.rating")

    def test_legacy_run_is_refused(self):
        self.assertExit2(lambda rs: rs[-1].pop("format"), "not 2")


class Fragment(unittest.TestCase):
    def body_with(self, extra, where="bottom"):
        return BODY.replace(f'<h2 id="{where}">', extra + f'<h2 id="{where}">', 1)

    def test_refused_constructs_exit_2(self):
        for bad, needle in [("<script>x()</script>", "<script>"), ("<style>p{}</style>", "<style>"),
                            ('<iframe src="https://e.com"></iframe>', "<iframe>"), ("<form></form>", "<form>"),
                            ('<input value="1">', "<input>"), ("<nav>x</nav>", "<nav>"),
                            ('<p onclick="x()">x</p>', "event-handler"), ('<div class="subscribe">x</div>', "subscribe"),
                            ('<a href="javascript:alert(1)">x</a>', "http(s) or relative"),
                            ('<a href="data:text/html,x">x</a>', "http(s) or relative"),
                            ('<link rel="stylesheet" href="x.css">', "<link>"), ('<meta charset="x">', "<meta>")]:
            with self.subTest(bad=bad):
                with self.assertRaises(br.ReportError) as cm:
                    br.clean_body(self.body_with(bad))
                self.assertEqual(cm.exception.code, 2)
                self.assertIn(needle, str(cm.exception))
                self.assertRegex(str(cm.exception), r"line \d+")

    def test_unknown_tag_and_attribute_are_stripped_with_a_warning(self):
        clean, warns = br.clean_body(self.body_with('<marquee style="x">Moving <img src="a.png"> text</marquee>'))
        self.assertIn("Moving  text", clean)
        self.assertNotIn("marquee", clean)
        self.assertNotIn("<img", clean)
        self.assertTrue(any("<marquee> stripped" in w for w in warns), warns)
        self.assertTrue(any("<img> stripped" in w for w in warns), warns)

    def test_required_ids(self):
        with self.assertRaises(br.ReportError) as cm:
            br.clean_body(BODY.replace('id="agi"', 'id="agi-x"'))
        self.assertIn('id "agi" is missing', str(cm.exception))
        with self.assertRaises(br.ReportError) as cm:
            br.clean_body(BODY + '<p id="s3">again</p>')
        self.assertIn('"s3" appears 2 times', str(cm.exception))
        swapped = BODY.replace('id="timeline"', 'id="TMP"').replace('id="roundup"', 'id="timeline"').replace(
            'id="TMP"', 'id="roundup"')
        with self.assertRaises(br.ReportError) as cm:
            br.clean_body(swapped)
        self.assertIn("out of order", str(cm.exception))

    def test_markers_and_shell_ids_cannot_be_smuggled_in(self):
        clean, warns = br.clean_body(self.body_with('<!-- analysis:end --><p id="corrections">x</p>'))
        self.assertNotIn("analysis:end", clean)
        self.assertNotIn('id="corrections"', clean)

    def test_cleaning_is_idempotent(self):
        clean, _ = br.clean_body(BODY)
        again, warns = br.clean_body(clean)
        self.assertEqual(again, clean)
        self.assertEqual(warns, [])


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tree("run_v2_cutover")
        self.runs = str(self.tmp / "data/runs.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_render_check_and_frozen_after_live_edits(self):
        code, out = cli(["--date", "2026-10-06", "--runs", self.runs, "--body", str(self.tmp / "body.html")])
        self.assertEqual(code, 0, out)
        short = self.tmp / "reports/2026-10-06.html"
        self.assertTrue(short.is_file() and (self.tmp / "reports/2026-10-06-analysis.html").is_file())
        self.assertEqual(cli(["--date", "2026-10-06", "--runs", self.runs, "--check"])[0], 0)
        # a Friday rewrites the live files the report once copied from: the report still matches its render (B1)
        comp = json.loads((self.tmp / "data/agi_components.json").read_text())
        comp["components"][0]["status"] = "partial"
        comp["components"][0]["glance"] = "Changed on Friday."
        (self.tmp / "data/agi_components.json").write_text(json.dumps(comp))
        al = json.loads((self.tmp / "data/alarm.json").read_text())
        al["current"]["since"] = "2026-10-09"
        (self.tmp / "data/alarm.json").write_text(json.dumps(al))
        es = json.loads((self.tmp / "data/escape.json").read_text())
        es["indicators"][0]["status"] = "tripped"
        (self.tmp / "data/escape.json").write_text(json.dumps(es))
        cal = json.loads((self.tmp / "data/calendar.json").read_text())
        cal["events"].insert(0, {"date": "2026-10-07", "title": "A new event"})
        (self.tmp / "data/calendar.json").write_text(json.dumps(cal))
        code, out = cli(["--date", "2026-10-06", "--runs", self.runs, "--check"])
        self.assertEqual(code, 0, out)
        # a same-day re-render without --body reuses the body and is idempotent
        before = short.read_text()
        self.assertEqual(cli(["--date", "2026-10-06", "--runs", self.runs])[0], 0)
        self.assertEqual(short.read_text(), before)
        # a one-byte edit is caught
        short.write_text(before.replace("Probabilities", "Probabilitie5", 1))
        code, out = cli(["--date", "2026-10-06", "--runs", self.runs, "--check"])
        self.assertEqual(code, 1)
        self.assertIn("differs from its render", out)
        # an edit to the analysis shell is caught; an edit inside the body is not the shell's business
        an = self.tmp / "reports/2026-10-06-analysis.html"
        short.write_text(before)
        html = an.read_text()
        an.write_text(html.replace("No new evidence on any part today.", "Edited body."))
        self.assertEqual(cli(["--date", "2026-10-06", "--runs", self.runs, "--check"])[0], 0)
        an.write_text(html.replace("Analysis for", "Analysis  for"))
        self.assertEqual(cli(["--date", "2026-10-06", "--runs", self.runs, "--check"])[0], 1)

    def test_check_data_in_process_render(self):
        """check_data calls render(date, runs_path) with no body: it reuses the body on disk."""
        cli(["--date", "2026-10-06", "--runs", self.runs, "--body", str(self.tmp / "body.html")])
        with contextlib.redirect_stderr(io.StringIO()):
            short, analysis = br.render("2026-10-06", self.runs)
        self.assertEqual(short, (self.tmp / "reports/2026-10-06.html").read_text())
        self.assertEqual(analysis, (self.tmp / "reports/2026-10-06-analysis.html").read_text())

    def test_no_body(self):
        code, out = cli(["--date", "2026-10-06", "--runs", self.runs])
        self.assertEqual(code, 2)
        self.assertIn("no analysis body", out)

    def test_past_date_is_refused(self):
        code, out = cli(["--date", "2026-10-05", "--runs", self.runs, "--body", str(self.tmp / "body.html")])
        self.assertEqual(code, 3)
        self.assertIn("past reports are frozen", out)
        self.assertFalse((self.tmp / "reports/2026-10-05.html").exists())

    def test_out_renders_elsewhere(self):
        out = self.tmp / "rehearsal"
        code, msg = cli(["--date", "2026-10-06", "--runs", self.runs, "--body", str(self.tmp / "body.html"),
                         "--out", str(out)])
        self.assertEqual(code, 0, msg)
        self.assertTrue((out / "reports/2026-10-06.html").is_file())
        self.assertFalse((self.tmp / "reports").exists())
        self.assertEqual(cli(["--date", "2026-10-06", "--runs", self.runs, "--out", str(out), "--check"])[0], 0)

    def test_snapshot_writes_only_the_snapshot_fields(self):
        rs = json.loads((self.tmp / "data/runs.json").read_text())
        before = copy.deepcopy(rs)
        for k in ("components", "furthest", "dates"):
            rs[-1].pop(k)
        for k in ("since", "icon", "status", "name"):
            rs[-1]["alarm"].pop(k)
        (self.tmp / "data/runs.json").write_text(json.dumps(rs, indent=1, ensure_ascii=False) + "\n")
        code, out = cli(["--snapshot", "2026-10-06", "--runs", self.runs])
        self.assertEqual(code, 0, out)
        after = json.loads((self.tmp / "data/runs.json").read_text())
        self.assertEqual(after[0], before[0])  # the earlier entry is untouched
        r = after[-1]
        self.assertEqual(sorted(r["components"]), sorted(br.COMPONENT_IDS))
        self.assertEqual(set(r["components"]["horizon"]), {"status", "short", "glance", "basisShort"})
        self.assertEqual(r["furthest"]["id"], "horizon")
        self.assertEqual(len(r["dates"]), 3)
        self.assertTrue(all(d["date"] > "2026-10-06" and br.words(d["short"]) <= 14 for d in r["dates"]))
        self.assertEqual((r["alarm"]["icon"], r["alarm"]["status"], r["alarm"]["name"]), ("◐", "warn", "Watch"))
        self.assertEqual(r["alarm"]["level"], 1)
        rest = {k: v for k, v in r.items() if k not in ("components", "furthest", "dates", "alarm")}
        self.assertEqual(rest, {k: v for k, v in before[-1].items() if k not in ("components", "furthest", "dates", "alarm")})


class Email(unittest.TestCase):
    def issue(self, name, mutate=None):
        rs = runs(name)
        if mutate:
            mutate(rs)
        return build_feed.issue_html(rs[-1], build_feed.prev_published(rs, len(rs) - 1), [])

    def test_v2_email_order_and_links(self):
        html = self.issue("run_v2_cutover")
        order = ["Method change today", "Fire alarm: Level 1, Watch", "Is AGI here?", "Hidden AGI Index: 2.5%",
                 "AI labs testify under oath", "Method change (definitions v2.0): AGI anywhere 1.5→0.9%; A 1→0.5%; "
                 "C 0.5→0.3%; D 0.25→0.1%; D-open 0.3→0.2%; B unchanged, it needs no AGI.",
                 "No signal changed today · 2 confirmed (count toward Watch)", "Escape watch: 0 of 8",
                 "AGI parts", "Top stories", "Dates to watch", "Bottom line"]
        pos = [html.find(s) for s in order]
        self.assertTrue(all(p >= 0 for p in pos), dict(zip(order, pos)))
        self.assertEqual(pos, sorted(pos))
        self.assertNotIn("parts sum to", html)   # the arithmetic stays on the report's card 2 and the analysis
        self.assertIn("method change (definitions v2.0), unchanged after rounding", html)
        self.assertIn("Higher than AGI anywhere (0.9%) because 1.7 points are hidden self-improvement (B), which needs no AGI.", html)
        self.assertNotIn("Change today", html)   # no displayed number moved on evidence: four columns
        self.assertIn("met: W3, evaluator access restricted by a lab or government (past 90 days); W4, median disclosure lag", html)
        self.assertIn("new evidence on 4 of 8 indicators", html)
        self.assertNotIn("(compute, identity, coordination, leakage)", html)
        self.assertIn("Disclosure lag, incident to public", html)
        self.assertIn("Quiet day · the day&#x27;s story", html)
        self.assertIn("No evidence moved today; numbers that need an AGI-level system were re-derived", html)   # the verdict
        self.assertLess(html.find("No evidence moved today;"), html.find("Method change today"))
        self.assertEqual(html.count("anthropic-openai-google-meta-execs-testify-nyc-council-ai-hearing"), 1)  # needle box only
        self.assertNotIn("Is AGI here, today?", html)
        an = br.SITE + "reports/2026-10-06-analysis.html"
        for frag in ("#timeline", "#roundup", "#s5", "#s6"):
            self.assertIn(an + frag, html)
        self.assertIn("method change (definitions v2.0)", html)
        self.assertNotIn("strict AGI", html)

    def test_v2_email_is_a_function_of_the_run(self):
        self.assertEqual(self.issue("run_v2"), self.issue("run_v2"))
        self.assertIn("Not in public:", self.issue("run_v2"))

    def test_v2_email_steady_day_and_a_move(self):
        html = self.issue("run_v2")   # a steady day: nothing moved, four columns, one line says so
        self.assertNotIn("Change today", html)
        self.assertIn("No number moved today.", html)
        self.assertNotIn("unchanged after rounding", html)

        def move(rs):
            rs[-1]["probs"]["B"]["now"] = 2.5
        html = self.issue("run_v2", move)   # a move brings the column back, with the arrow cell
        self.assertIn("Change today", html)
        self.assertIn("▲ +0.5 pts", html)
        self.assertIn("What changed and why:", html)

        def move_horizon(rs):
            rs[-1]["probs"]["A"]["y2030"] = 30
        html = self.issue("run_v2", move_horizon)   # only a horizon number moved (M2): four columns, the line names it
        self.assertNotIn("Change today", html)
        self.assertNotIn("No number moved today.", html)
        self.assertIn("No today number moved; by end-2030 / end-2035 changed: A by end-2030 25→30%.", html)

    def test_condition_short_matches_alarm_json(self):
        from sitekit import CONDITION_SHORT, condition_name
        a = json.loads((REPO / "data/alarm.json").read_text())
        for g in a.get("groups") or []:
            for t in g.get("triggers") or []:
                if t.get("short"):   # criteria 1.1 carries no short names; 1.2 does
                    self.assertEqual(CONDITION_SHORT.get(t["id"]), t["short"], t["id"])
        self.assertEqual(condition_name("W3"), "W3, evaluator access restricted by a lab or government (past 90 days)")
        self.assertEqual(condition_name("X3"), "X3, AI-driven self-improvement: over 10% autonomous AI R&D, or 3x+ speed-up")
        self.assertEqual(condition_name("Z9"), "Z9")

    def test_daily_subject_and_preview(self):
        rs = runs("run_v2_cutover")
        run, prev = rs[-1], build_feed.prev_published(rs, len(rs) - 1)
        self.assertEqual(kit_broadcast.daily_subject(run, prev), "AI labs testify under oath at NYC Council · quiet day")
        # the preview is the verdict first; the state follows when the 140-character line has room for it
        self.assertEqual(kit_broadcast.daily_preview(run),
                         "No evidence moved today; numbers that need an AGI-level system were re-derived under definitions v2.0.")
        short = dict(run, verdict="A quiet day: no number moved on evidence.")
        self.assertEqual(kit_broadcast.daily_preview(short),
                         "A quiet day: no number moved on evidence. Index 2.5% · fire alarm Level 1, Watch.")
        moved = dict(run, index=3, defs="1.0", needle=dict(run["needle"], quiet=False))   # a non-boundary run
        self.assertEqual(kit_broadcast.daily_subject(moved, prev), "AI labs testify under oath at NYC Council · Index 2.5→3%")
        # on the method boundary a re-derived Index that rounds differently is a method change, never a move (M1)
        boundary = dict(run, index=2.0)
        self.assertEqual(kit_broadcast.daily_subject(boundary, prev), "AI labs testify under oath at NYC Council · quiet day")
        bare = dict(run, alarm={"level": 1, "met": ["W3"]})   # no snapshot name: still a line, never a crash
        self.assertTrue(kit_broadcast.daily_preview(bare).endswith("Index 2.5% · fire alarm Level 1."))
        legacy = rs[0]
        self.assertTrue(kit_broadcast.daily_subject(legacy).startswith("Index 2.5% · Quiet day: "))
        self.assertEqual(kit_broadcast.daily_preview(legacy), kit_broadcast.preview(legacy["needle"]["detail"]))

    def test_next_dates_keeps_the_alarm_clock(self):
        evs = [{"date": "2026-10-14", "kind": "industry"}, {"date": "2026-10-31", "kind": "forecast"},
               {"date": "2026-10-31", "kind": "forecast"}, {"date": "2026-11-07", "kind": "alarm"},
               {"date": "2026-11-16", "kind": "policy"}]
        self.assertEqual([x["date"] for x in br.next_dates(evs)], ["2026-10-14", "2026-10-31", "2026-11-07"])
        self.assertEqual([x["date"] for x in br.next_dates(evs[3:])], ["2026-11-07", "2026-11-16"])
        self.assertEqual([x["date"] for x in br.next_dates(evs[:3])], ["2026-10-14", "2026-10-31", "2026-10-31"])
        self.assertEqual(br.next_dates([]), [])

    def test_v2_email_caps_corrections(self):
        html = self.issue("run_v2_41corrections")
        self.assertIn("36 more corrections →", html)
        self.assertIn(br.SITE + "reports/2026-10-05-analysis.html#corrections", html)

    def test_legacy_runs_take_the_legacy_path(self):
        html = self.issue("run_legacy")   # the last two legacy runs, frozen: live runs.json is format 2 from 2026-10-07
        self.assertIn("Read the full report", html)  # the unchanged legacy closing
        self.assertNotIn("Is AGI here, today?", html)


class CardsAndSender(unittest.TestCase):
    def test_daily_card_v2(self):
        rs = runs("run_v2_cutover")
        rows, foot, note = render_card.v2_card_parts(rs[-1], build_feed.prev_published(rs, 1))
        self.assertEqual([d for _, _, d in rows], ["method change", "no change", "method change", "method change"])
        self.assertIn("AGI parts: 0 of 8 met", note)
        self.assertIn("Method change", note)
        rs = runs("run_v2")
        rows, _, note = render_card.v2_card_parts(rs[-1], build_feed.prev_published(rs, 1))
        self.assertEqual([d for _, _, d in rows], ["no change"] * 4)
        self.assertNotIn("Method change", note)

    def test_weekly_boundary(self):
        k = {"weekAgo": {"A": 1}, "defs": "2.0", "defsWeekAgo": "1.0"}
        self.assertTrue(render_card.weekly_boundary(k))
        self.assertFalse(render_card.weekly_boundary(dict(k, methodBoundary=False)))
        self.assertFalse(render_card.weekly_boundary(dict(k, firstReading=True)))
        legacy = json.loads((REPO / "data/weekly/2026-10-02.json").read_text())["keyNumbers"]
        self.assertFalse(render_card.weekly_boundary(legacy))

    def test_kit_lists_include_the_analysis_page(self):
        run = runs("run_v2_cutover")[-1]
        live, files = kit_broadcast.daily_lists(run, run["date"])
        self.assertIn("reports/2026-10-06-analysis.html", files)
        self.assertIn(br.SITE + "reports/2026-10-06-analysis.html", live)
        legacy = runs("run_v2_cutover")[0]
        live, files = kit_broadcast.daily_lists(legacy, legacy["date"])
        self.assertFalse(any("analysis" in x for x in live + files))


class Money(unittest.TestCase):
    def test_writes_only_when_a_figure_changes(self):
        import build_money
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "money.json"
            saved = build_money.OUT
            build_money.OUT = out
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    build_money.main()
                    doc = json.loads(out.read_text())
                    doc["updated"] = "2000-01-01"
                    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
                    before = out.read_text()
                    build_money.main()  # only the date would change: no write
                    self.assertEqual(out.read_text(), before)
                    doc["ttm"] = None  # a figure differs: rewritten
                    out.write_text(json.dumps(doc))
                    build_money.main()
                    self.assertNotEqual(json.loads(out.read_text())["ttm"], None)
            finally:
                build_money.OUT = saved


if __name__ == "__main__":
    unittest.main()
