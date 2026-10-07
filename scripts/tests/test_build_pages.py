"""Tests for the shared display rules and build_pages.py's standing pages (spec 3.1, 3.2, 12; review round 1).
Stdlib unittest, no built tree needed:

    python3 -m unittest discover -s scripts/tests -t .
"""
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import build_pages  # noqa: E402
import sitekit  # noqa: E402
from pages import archive, common  # noqa: E402

ALARM = {"groups": [{"level": 1, "triggers": [{"id": "W3"}, {"id": "W4"}]}, {"level": 2, "triggers": [{"id": "X4"}]},
                    {"level": 3, "triggers": [{"id": "Y1"}]}],
         "levels": [{"level": 0, "name": "Normal"}, {"level": 1, "name": "Watch"}, {"level": 2, "name": "Warning"}]}


class SignalWords(unittest.TestCase):
    def test_esc_status_is_the_reordered_view(self):
        # spec 3.2: ESC_STATUS is (icon, word, token); SIGNAL_STATUS is (icon, token, word)
        self.assertEqual(build_pages.ESC_STATUS["watching"], ("◔", "Open", "warn"))
        self.assertEqual(build_pages.ESC_STATUS["tripped"], ("●", "Confirmed", "crit"))
        self.assertEqual(build_pages.ESC_STATUS["quiet"], ("○", "Quiet", "good"))

    def test_confirmed_signal_colour_is_capped_at_its_condition(self):
        self.assertEqual(sitekit.signal_view("tripped", "W3", ALARM), ("●", "warn", "Confirmed · counts toward Watch"))
        self.assertEqual(sitekit.signal_view("tripped", "X4", ALARM), ("●", "crit", "Confirmed"))
        self.assertEqual(sitekit.signal_view("tripped", None, ALARM), ("●", "warn", "Confirmed · no alarm condition"))
        self.assertEqual(sitekit.signal_view("tripped", "W9"), ("●", "warn", "Confirmed · counts toward Watch"))  # letter
        self.assertEqual(sitekit.signal_view("watching", "X4", ALARM), ("◔", "warn", "Open"))
        self.assertEqual(sitekit.signal_view("bogus", "W3")[0], "?")

    def test_signal_board_is_amber_for_watch_conditions(self):
        run = {"date": "2026-10-05", "tripwires": [
            {"id": "a", "signal": "Evaluator access restricted", "status": "tripped", "trigger": "W3", "hyp": "A",
             "note": 'W3 is met (shown amber as "Observed · feeds Watch": a tripwire\'s colour is capped at its '
                     'trigger\'s level).'},
            {"id": "b", "signal": "Unexplained compute", "status": "tripped", "trigger": "X4", "hyp": "A", "note": "x"},
            {"id": "c", "signal": "Training pause", "status": "watching", "hyp": "B", "note": "y"}]}
        old_run, old_load = build_pages.newest_run, build_pages.load_json
        build_pages.newest_run = lambda: run
        build_pages.load_json = lambda rel: ALARM if rel == "data/alarm.json" else old_load(rel)
        try:
            html = build_pages.signals_section()
        finally:
            build_pages.newest_run, build_pages.load_json = old_run, old_load
        w3 = html.split("Evaluator access restricted")[0].rsplit("<summary>", 1)[1]
        self.assertIn('class="ico-warn"', w3)
        self.assertIn("Confirmed · counts toward Watch", w3)
        x4 = html.split("Unexplained compute")[0].rsplit("<summary>", 1)[1]
        self.assertIn('class="ico-crit"', x4)
        self.assertNotIn("Observed · feeds Watch", html)
        self.assertIn("Confirmed · counts toward Watch", html.split("</summary>", 1)[1])


class Copy(unittest.TestCase):
    def test_background_date_is_never_first_reported(self):
        self.assertEqual(sitekit.story_date({"date": "Oct 2 (background)"}), "Oct 2 (earlier event)")
        self.assertEqual(sitekit.story_date({"date": "Oct 1 (background; first in our 2 Oct reading)"}),
                         "Oct 1 (earlier event)")
        self.assertEqual(sitekit.story_date({"date": "Oct 5", "background": True}), "Oct 5 (earlier event)")
        self.assertEqual(sitekit.story_date({"date": "Oct 5 (Quartz, citing the WSJ)",
                                             "short": "Quartz, citing the WSJ: the force has 120 days."}), "Oct 5")
        self.assertEqual(sitekit.story_date({"date": "Oct 7 (effective)", "text": "AWS raises prices"}),
                         "Oct 7 (effective)")

    def test_retired_words_are_mapped_for_display(self):
        s = sitekit.display_words("WATCHING (the current status) holds. TRIPPED requires two outlets. Status is "
                                  "watching rather than quiet. B (secret RSI short of strict AGI).")
        self.assertNotRegex(s, r"WATCHING|TRIPPED|secret RSI|strict AGI|Status is watching")
        self.assertIn("OPEN (the current status)", s)

    def test_index_cell_is_method_change_on_the_boundary(self):
        run = {"defs": "2.0", "index": 2.5, "methodChange": {"from": "1.0", "to": "2.0"},
               "changes": ["The Remote Labor Index (RLI) top score rose from 20.8% to 22.4%."]}
        prev = {"defs": "1.0", "index": 2.5}
        self.assertEqual(common.delta_text(run, prev, "index"), sitekit.METHOD_CHANGE)

    def test_quiet_headline_never_says_nothing_moved_on_a_method_change_day(self):
        run = {"date": "2026-10-06", "methodChange": {"from": "1.0", "to": "2.0"}, "report": "reports/2026-10-06.html",
               "format": 2, "needle": {"quiet": True, "headline": "Quiet day: nothing moved.", "subject": "x"},
               "alarm": {"level": 1, "met": []}}
        html = common.card_alarm({"alarm": {}, "escape": {}}, run, "", {"card": "alarm", "q": "q3"})
        self.assertNotIn("nothing moved", html)
        self.assertIn("no news moved our numbers", html)


def _moved(row):
    """The HTML inside an archive row's "What moved" cell."""
    return row.split('data-label="What moved">', 1)[1].split("</td>", 1)[0]


class ArchiveAndTracker(unittest.TestCase):
    """Review round 2: R2-01 (archive quiet days), R2-02 (X4 wording), VR2-01 (measurement tables)."""
    RUNS = [
        {"date": "2026-09-29", "label": "Chat baseline", "comparable": False, "index": 3, "agi": {"now": 1.5}},
        {"date": "2026-10-04", "report": "reports/2026-10-04.html", "index": 2.5, "agi": {"now": 1.5},
         "alarm": {"level": 1, "met": []},
         "needle": {"quiet": True, "subject": "OpenAI reports model reached an internal host",
                    "headline": "Quiet day: nothing moved."}},
        {"date": "2026-10-05", "report": "reports/2026-10-05.html", "index": 2.5, "agi": {"now": 1.5},
         "alarm": {"level": 1, "met": []},
         "needle": {"quiet": False, "hypothesis": "A", "from": 1, "to": 1.5,
                    "subject": "OpenAI reportedly pulls a model over deception"}},
    ]
    ALARM = {"levels": [{"level": 1, "name": "Watch"}]}

    def test_quiet_day_never_lists_its_story_as_what_moved(self):
        rows = archive.rows(self.RUNS, self.ALARM)
        quiet = _moved(next(r for r in rows if "Oct 4, 2026" in r))
        self.assertTrue(quiet.startswith("Quiet day"), quiet)
        self.assertIn('<span class="small muted">· top story: OpenAI reports model reached an internal host</span>',
                      quiet)
        # a day on which news did move a number keeps its subject as the move
        self.assertEqual(_moved(next(r for r in rows if "Oct 5, 2026" in r)),
                         "OpenAI reportedly pulls a model over deception")
        # the baseline (no needle) keeps its label
        self.assertEqual(_moved(next(r for r in rows if "Sep 29, 2026" in r)), "Chat baseline")

    def test_every_quiet_run_in_the_data_reads_quiet_day(self):
        runs = common.load_json("data/runs.json")
        rows = archive.rows(runs, common.load_json("data/alarm.json"))
        quiet = [r for r in common.published(runs) if (r.get("needle") or {}).get("quiet") is True]
        self.assertTrue(quiet)
        for r in quiet:
            row = next(x for x in rows if f'data-label="Date">{common.day(r["date"])}<' in x)
            self.assertTrue(_moved(row).startswith("Quiet day"), r["date"])

    def test_x4_is_never_described_as_twice_the_largest_known(self):
        money = build_pages.money_body() + build_pages.RED_FLAGS
        self.assertNotIn("largest known", money)
        self.assertIn("2x Epoch AI's trend", money)
        self.assertIn("within 12 months", money)
        self.assertNotIn("within 6 months", money)

    def test_measurement_tables_format_dates_and_label_cells(self):
        self.assertEqual(common.as_of("2026-09-17 (last leaderboard update; read Oct 5)"),
                         "Sep 17, 2026 (last leaderboard update; read Oct 5)")
        self.assertEqual(common.as_of("2026-08-03 and 2026-02-27 (Sierra evaluation dates)"),
                         "Aug 3, 2026 and Feb 27, 2026 (Sierra evaluation dates)")
        self.assertEqual(common.as_of("Feb 16-Mar 16, 2026 assessment window"), "Feb 16-Mar 16, 2026 assessment window")
        c = {"id": "quality", "name": "Quality", "headline": {}, "current": [
            {"metric": "GDPval wins or ties", "value": "83.0%", "system": "Claude Fable 5", "asOf": "2026-04-23",
             "rating": "verified fact", "url": "https://example.org/x"}]}
        html = common.static_component(c)
        self.assertIn('<table class="am-meas">', html)
        self.assertIn('<td data-label="As of"><span class="am-day">Apr 23, 2026</span></td>', html)
        self.assertEqual(common.as_of_html("2026-09-17 (re-read Oct 5)"),
                         '<span class="am-day">Sep 17, 2026</span> (re-read Oct 5)')
        self.assertEqual(common.as_of_html(None), "–")
        self.assertNotIn(">2026-04-23<", html)


if __name__ == "__main__":
    unittest.main()


class JobsPage(unittest.TestCase):
    """jobs.html, "Jobs watch" (the Jobs plugin's spec, 8.3)."""

    def setUp(self):
        import shutil
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="jobs-page-"))
        src = Path(__file__).resolve().parent / "fixtures" / "checks" / "base" / "data" / "jobs"
        shutil.copytree(src, self.tmp / "data" / "jobs")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def render(self, root=None):
        from pages import jobs
        return jobs.render(root or self.tmp)

    def test_jobs_page_is_registered(self):
        import pages
        self.assertEqual(pages.MODULES.get("jobs.html"), "jobs")

    def test_jobs_page_skipped_without_data(self):
        import tempfile
        self.assertIsNone(self.render(Path(tempfile.mkdtemp())))

    def test_jobs_page_has_every_claim_anchor(self):
        html = self.render()
        for i in range(13):
            self.assertIn(f'id="J{i}"', html)

    def test_jobs_crumb_is_today(self):
        crumb = sitekit.crumb_for("jobs.html")
        self.assertIn("Today", crumb)
        self.assertIn("Jobs watch", crumb)

    def test_jobs_intro_says_it_never_feeds_the_index(self):
        self.assertIn("never feeds the Hidden AGI Index", self.render())

    def test_archive_links_wrapups(self):
        self.assertIn('href="weekly/2026-10-16.html"', self.render())

    def test_status_board_uses_current_statuses(self):
        html = self.render()
        self.assertIn("st-emerging", html)          # J3 in the fixture claims
        self.assertIn("Established under review", html)   # J4's pending proposal

    def test_text_is_escaped(self):
        import json
        p = self.tmp / "data" / "jobs" / "claims.json"
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["claims"][0]["wording"] = "<b>bold</b> & co"
        p.write_text(json.dumps(doc), encoding="utf-8")
        html = self.render()
        self.assertIn("&lt;b&gt;bold&lt;/b&gt; &amp; co", html)

    def test_indicator_link_is_never_a_script_url(self):
        import json
        p = self.tmp / "data" / "jobs" / "claims.json"
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["claims"][1]["indicators"][0]["url"] = "javascript:alert(1)"
        p.write_text(json.dumps(doc), encoding="utf-8")
        self.assertNotIn("javascript:", self.render())

    def test_names_row_appears_only_with_jobs_claims(self):
        import json
        claims = json.loads((self.tmp / "data" / "jobs" / "claims.json").read_text(encoding="utf-8"))
        row = common.jobs_names_row(claims)
        self.assertEqual(row[0], '<a href="jobs.html">Jobs claims</a>')
        self.assertIn("Contradicted", row[1])
        self.assertIn("1 emerging", row[2])
        self.assertIsNone(common.jobs_names_row(None))
