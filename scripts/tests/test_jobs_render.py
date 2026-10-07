"""Tests for the Jobs section in the Friday wrap-up (scripts/jobs_render.py and build_weekly.py; the Jobs plugin's
spec, 8.2). Stdlib unittest, no network.

fixtures/weekly/wrapup_v2.json is a real format-2 wrap-up input (key numbers and snapshot frozen from the data of
2026-10-09); golden_page_body.html and golden_email.html are what build_weekly rendered for it BEFORE the Jobs section
existed, so "no Jobs file" must still give exactly that. If the wrap-up layout changes on purpose, regenerate them.
"""
import copy
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import build_weekly  # noqa: E402
import jobs_render  # noqa: E402

WEEKLY = HERE / "fixtures" / "weekly"
JOBS = HERE / "fixtures" / "checks" / "base" / "data" / "jobs"


def wrapup():
    return json.loads((WEEKLY / "wrapup_v2.json").read_text(encoding="utf-8"))


def jobs(**over):
    ed = json.loads((JOBS / "2026-10-16.json").read_text(encoding="utf-8"))
    ed.update(over)
    return {"edition": ed, "claims": json.loads((JOBS / "claims.json").read_text(encoding="utf-8"))}


def words(html):
    return len(re.sub(r"<[^>]+>", " ", html).split())


class Rendered(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jobs-weekly-"))
        (self.tmp / "data").mkdir()
        shutil.copy(WEEKLY / "gauges.json", self.tmp / "data" / "gauges.json")
        self.root, build_weekly.ROOT = build_weekly.ROOT, self.tmp

    def tearDown(self):
        build_weekly.ROOT = self.root
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_absent_changes_nothing(self):
        self.assertEqual(build_weekly.page_body(wrapup(), jobs=None), (WEEKLY / "golden_page_body.html").read_text(encoding="utf-8"))
        self.assertEqual(build_weekly.weekly_email_html_v2(wrapup(), jobs=None), (WEEKLY / "golden_email.html").read_text(encoding="utf-8"))

    def test_no_jobs_file_on_disk_changes_nothing(self):
        # The default looks in data/jobs/<date>.json under ROOT, which this temp root does not have.
        self.assertEqual(build_weekly.page_body(wrapup()), (WEEKLY / "golden_page_body.html").read_text(encoding="utf-8"))

    def test_section_is_last(self):
        page = build_weekly.page_body(wrapup(), jobs=jobs())
        i_jobs, i_escape = page.index('<section id="jobs"'), page.index('<section id="escape"')
        i_note = page.index("The charts and the AGI parts on this page are frozen")
        self.assertLess(i_escape, i_jobs)
        self.assertLess(i_jobs, i_note)

    def test_email_block_sits_before_the_closing_links_and_nothing_else_changes(self):
        golden = (WEEKLY / "golden_email.html").read_text(encoding="utf-8")
        got = build_weekly.weekly_email_html_v2(wrapup(), jobs=jobs())
        block = jobs_render.email_html(jobs()["edition"], jobs()["claims"])
        self.assertIn(block, got)
        self.assertEqual(got.replace(block, "", 1), golden)
        self.assertLess(got.index(block), got.index("See the full wrap-up with graphs"))

    def test_baseline_says_starting_statuses(self):
        j = jobs(baseline=True, moves=[])
        for s in j["edition"]["strip"]:
            s["prev"] = None
        self.assertIn("Starting statuses", jobs_render.section_html(j["edition"], j["claims"]))
        self.assertIn("Starting statuses", jobs_render.email_html(j["edition"], j["claims"]))

    def test_no_moves_line(self):
        j = jobs(moves=[])
        self.assertIn("No claim moved this week", jobs_render.section_html(j["edition"], j["claims"]))
        em = jobs_render.email_html(j["edition"], j["claims"])
        self.assertIn("No claim moved this week", em)
        self.assertLessEqual(em.count("<li"), 3)

    def test_moves_are_shown_with_arrows_and_reasons(self):
        j = jobs()
        html = jobs_render.section_html(j["edition"], j["claims"])
        self.assertIn("No clear sign → Emerging", html)
        self.assertIn("Payroll research shows the gap.", html)

    def test_pending_shows_under_review(self):
        j = jobs()
        html = jobs_render.section_html(j["edition"], j["claims"])
        self.assertIn("Established under review", html)
        self.assertNotIn('st-established"', html)   # J4 is shown at its status, Supported, never as Established

    def test_text_is_escaped(self):
        j = jobs()
        j["edition"]["evidence"][0]["text"] = "<script>alert(1)</script> & co"
        j["edition"]["evidence"][0]["top"] = True
        html = jobs_render.section_html(j["edition"], j["claims"])
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; co", html)
        self.assertNotIn("<script>alert", html)

    def test_email_block_under_200_words(self):
        j = jobs()
        self.assertLessEqual(words(jobs_render.email_html(j["edition"], j["claims"])), jobs_render.EMAIL_WORDS)

    def test_links_point_at_the_tracker(self):
        j = jobs()
        self.assertIn('href="../jobs.html"', jobs_render.section_html(j["edition"], j["claims"]))
        self.assertIn("https://hiddenagi.com/jobs.html", jobs_render.email_html(j["edition"], j["claims"]))

    def test_load_jobs_reads_both_files(self):
        (self.tmp / "data" / "jobs").mkdir()
        shutil.copy(JOBS / "2026-10-16.json", self.tmp / "data" / "jobs" / "2026-10-09.json")
        shutil.copy(JOBS / "claims.json", self.tmp / "data" / "jobs" / "claims.json")
        got = build_weekly.load_jobs("2026-10-09")
        self.assertEqual(sorted(got), ["claims", "edition"])
        self.assertIsNone(build_weekly.load_jobs("2026-10-02"))


class Sentences(unittest.TestCase):
    # The 2026-10-06 review's Important 3: real items from the 2026-10-06 edition that a split on ". " garbled.
    def test_first_sentence_keeps_abbreviations(self):
        cases = {
            "The share of U.S. workers using AI rose to 40%. The rest did not.": "The share of U.S. workers using AI rose to 40%.",
            "Challenger, Gray & Christmas counted 120,136 announced U.S. job cuts citing AI. That is 21%.":
                "Challenger, Gray & Christmas counted 120,136 announced U.S. job cuts citing AI.",
            "In Mobley v. Workday, the court certified a collective action. It is procedural.":
                "In Mobley v. Workday, the court certified a collective action.",
            "In X.AI LLC v. Musk the judge ruled for the defendant. Next.": "In X.AI LLC v. Musk the judge ruled for the defendant.",
            "St. Louis Fed researchers found a 0.47 correlation. Correlation is not causation.":
                "St. Louis Fed researchers found a 0.47 correlation.",
            "J. Smith of the Fed said so. More.": "J. Smith of the Fed said so.",
            "No full stop at all": "No full stop at all.",
        }
        for text, want in cases.items():
            with self.subTest(text):
                self.assertEqual(jobs_render.first_sentence(text), want)

    def test_a_very_long_first_sentence_is_cut_at_a_word(self):
        got = jobs_render.first_sentence(" ".join(["word"] * 80) + ".")
        self.assertTrue(got.endswith("…"))
        self.assertLessEqual(len(got.split()), jobs_render.SENTENCE_WORDS + 1)


class EmailSafety(unittest.TestCase):
    def test_email_text_is_escaped(self):
        j = jobs()
        j["edition"]["evidence"][0]["text"] = "<script>alert(1)</script> & co. Second."
        j["edition"]["evidence"][0]["top"] = True
        j["edition"]["moves"][0]["why"] = "<b>bold</b> reason."
        em = jobs_render.email_html(j["edition"], j["claims"])
        self.assertNotIn("<script>alert", em)
        self.assertNotIn("<b>bold</b>", em)
        self.assertIn("&lt;script&gt;", em)


class ConfirmedSince(unittest.TestCase):
    # The review's Minor 3, re-graded: the owner confirmed J4 after the edition was frozen; readers must not be told
    # it is still under review when the imported claims say it is Established.
    def confirmed(self):
        j = jobs()
        j4 = j["claims"]["claims"][4]
        j4["history"].append({"date": "2026-10-16", "from": "supported", "to": "established", "why": "Owner agreed.",
                              "evidence": [], "by": "owner"})
        j4["status"], j4["pending"] = "established", None
        return j

    def test_page_says_confirmed_not_under_review(self):
        j = self.confirmed()
        html = jobs_render.section_html(j["edition"], j["claims"])
        self.assertNotIn("Established under review", html)
        self.assertIn("Established, since confirmed by the owner", html)

    def test_email_says_confirmed(self):
        j = self.confirmed()
        em = jobs_render.email_html(j["edition"], j["claims"])
        self.assertNotIn("under review", em)
        self.assertIn("since confirmed by the owner", em)

    def test_baseline_email_status_line_agrees(self):
        j = self.confirmed()
        j["edition"]["baseline"] = True
        j["edition"]["moves"] = []
        em = jobs_render.email_html(j["edition"], j["claims"])
        self.assertNotIn("(Established proposed)", em)
        self.assertIn("since confirmed by the owner", em)
        self.assertEqual(em.count("since confirmed by the owner"), 1)

    def test_rejected_since_says_so(self):
        j = jobs()
        j4 = j["claims"]["claims"][4]
        j4["history"].append({"date": "2026-10-16", "from": "supported", "to": "supported", "why": "Rejected.",
                              "evidence": [], "by": "owner", "note": "rejected: established"})
        j4["pending"] = None
        html = jobs_render.section_html(j["edition"], j["claims"])
        self.assertNotIn("under review", html)
        self.assertIn("since rejected by the owner", html)


if __name__ == "__main__":
    unittest.main()
