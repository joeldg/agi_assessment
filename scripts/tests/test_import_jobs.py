"""Tests for scripts/import_jobs.py (the Jobs plugin's spec, 8.1). Stdlib unittest; temp git repos, no network."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import import_jobs  # noqa: E402

FIX = HERE / "fixtures" / "checks" / "base" / "data" / "jobs"
FRIDAY = "2026-10-09"


def edition(date, **over):
    doc = json.loads((FIX / "2026-10-16.json").read_text(encoding="utf-8"))
    doc.pop("edition", None)
    doc.pop("source", None)
    doc["date"] = date
    doc.update(over)
    return doc


def git(root, *args):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True,
                   capture_output=True)


class Env:
    """A plugin repo (git) with claims.json and the given editions, and a newsletter root with a corrections log."""

    def __init__(self, editions=(), uncommitted=()):
        self.tmp = Path(tempfile.mkdtemp(prefix="jobs-import-"))
        self.plugin, self.news = self.tmp / "post_agi_work", self.tmp / "news"
        (self.plugin / "editions").mkdir(parents=True)
        (self.news / "data").mkdir(parents=True)
        shutil.copy(FIX / "claims.json", self.plugin / "claims.json")
        for d, doc in editions:
            (self.plugin / f"editions/{d}.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        git(self.plugin, "init", "-q")
        git(self.plugin, "add", "-A")
        git(self.plugin, "commit", "-qm", "editions")
        for d, doc in uncommitted:
            (self.plugin / f"editions/{d}.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        (self.news / "data/corrections.json").write_text(json.dumps(
            {"note": "n", "fields": "f", "corrections": [{"date": "2026-10-02", "page": "x.html", "item": "i", "was": "w",
                                                         "now": "n", "url": "https://example.org/c", "emailed": "2026-10-04"}]},
            indent=1) + "\n", encoding="utf-8")

    def run(self, friday=FRIDAY, plugin=True):
        return import_jobs.import_edition(self.news, self.plugin if plugin else None, friday)

    def read(self, rel):
        return json.loads((self.news / rel).read_text(encoding="utf-8"))

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class Import(unittest.TestCase):
    def test_no_plugin_exits_3(self):
        env = Env([("2026-10-08", edition("2026-10-08"))])
        try:
            code, line = env.run(plugin=False)
            self.assertEqual(code, 3)
            self.assertFalse((env.news / "data/jobs").exists())
        finally:
            env.close()

    def test_no_edition_in_window_exits_3(self):
        env = Env([("2026-10-01", edition("2026-10-01"))])
        try:
            self.assertEqual(env.run()[0], 3)
        finally:
            env.close()

    def test_imports_the_newest_edition_in_the_window(self):
        env = Env([("2026-10-01", edition("2026-10-01")), ("2026-10-08", edition("2026-10-08")),
                   ("2026-10-09", edition("2026-10-09", headline="Friday rerun"))])
        try:
            code, line = env.run()
            self.assertEqual(code, 0, line)
            doc = env.read(f"data/jobs/{FRIDAY}.json")
            self.assertEqual((doc["date"], doc["edition"], doc["headline"]), ("2026-10-09", "2026-10-09", "Friday rerun"))
            self.assertTrue(doc["source"].startswith("post_agi_work@"))
            self.assertEqual(env.read("data/jobs/claims.json")["version"], "1.0")
        finally:
            env.close()

    def test_reads_head_only(self):
        # A half-written Thursday run must be invisible: only committed editions count (plugin spec 8.1).
        env = Env([("2026-10-08", edition("2026-10-08"))], uncommitted=[("2026-10-09", edition("2026-10-09", headline="WIP"))])
        try:
            self.assertEqual(env.run()[0], 0)
            self.assertEqual(env.read(f"data/jobs/{FRIDAY}.json")["date"], "2026-10-08")
        finally:
            env.close()

    def test_invalid_edition_exits_2_and_writes_nothing(self):
        bad = edition("2026-10-08")
        bad["evidence"][0]["rating"] = "fact"
        env = Env([("2026-10-08", bad)])
        try:
            code, line = env.run()
            self.assertEqual(code, 2)
            self.assertIn("rating", line)
            self.assertFalse((env.news / "data/jobs").exists())
        finally:
            env.close()

    def test_denylisted_link_is_refused(self):
        bad = edition("2026-10-08")
        bad["evidence"][0]["url"] = "https://aiweekly.co/x"
        env = Env([("2026-10-08", bad)])
        try:
            code, line = env.run()
            self.assertEqual(code, 2)
            self.assertIn("aiweekly.co", line)
        finally:
            env.close()

    def test_corrections_appended_once(self):
        corr = [{"date": "2026-10-08", "page": "jobs.html", "item": "J3 payroll figure", "was": "19%", "now": "17%",
                 "url": "https://example.org/fix"}]
        env = Env([("2026-10-08", edition("2026-10-08", corrections=corr))])
        try:
            env.run()
            env.run()
            got = [c for c in env.read("data/corrections.json")["corrections"] if c.get("section") == "jobs"]
            self.assertEqual(len(got), 1)
            self.assertEqual((got[0]["item"], got[0]["emailed"], got[0]["page"]), ("J3 payroll figure", None, "jobs.html"))
        finally:
            env.close()

    def test_rerun_is_idempotent(self):
        env = Env([("2026-10-08", edition("2026-10-08"))])
        try:
            env.run()
            first = {p: (env.news / p).read_bytes() for p in ("data/jobs/2026-10-09.json", "data/jobs/claims.json", "data/corrections.json")}
            env.run()
            self.assertEqual(first, {p: (env.news / p).read_bytes() for p in first})
        finally:
            env.close()

    def test_find_plugin_order(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            news, sib = tmp / "agi_assessment", tmp / "post_agi_work"
            news.mkdir()
            self.assertIsNone(import_jobs.find_plugin(None, news))
            sib.mkdir()
            shutil.copy(FIX / "claims.json", sib / "claims.json")
            git(sib, "init", "-q")
            git(sib, "add", "-A")
            git(sib, "commit", "-qm", "c")
            self.assertEqual(import_jobs.find_plugin(None, news).resolve(), sib.resolve())
            other = tmp / "elsewhere"
            other.mkdir()
            old = os.environ.get("JOBS_PLUGIN")
            os.environ["JOBS_PLUGIN"] = str(other)
            try:
                self.assertIsNone(import_jobs.find_plugin(None, news))   # set, but no committed claims.json there
            finally:
                os.environ.pop("JOBS_PLUGIN") if old is None else os.environ.__setitem__("JOBS_PLUGIN", old)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_main_exit_code(self):
        env = Env([("2026-10-08", edition("2026-10-08"))])
        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = import_jobs.main(["--date", FRIDAY, "--plugin", str(env.plugin), "--root", str(env.news)])
            self.assertEqual(code, 0)
            self.assertIn("imported", out.getvalue())
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
