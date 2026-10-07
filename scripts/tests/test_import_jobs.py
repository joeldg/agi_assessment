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

    def __init__(self, editions=(), uncommitted=(), claims=None):
        self.tmp = Path(tempfile.mkdtemp(prefix="jobs-import-"))
        self.plugin, self.news = self.tmp / "post_agi_work", self.tmp / "news"
        (self.plugin / "editions").mkdir(parents=True)
        (self.news / "data").mkdir(parents=True)
        if claims is None:
            shutil.copy(FIX / "claims.json", self.plugin / "claims.json")
        else:
            (self.plugin / "claims.json").write_text(json.dumps(claims, indent=1) + "\n", encoding="utf-8")
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


def _set(path, value):
    def f(doc):
        cur = doc
        for k in path[:-1]:
            cur = cur[k]
        cur[path[-1]] = value
    return f


def _append(path, value):
    def f(doc):
        cur = doc
        for k in path:
            cur = cur[k]
        cur.append(value)
    return f


# Editions the plugin's own checker would pass (it coerces with str()) but that would crash the wrap-up build or
# corrupt the corrections log (the 2026-10-06 review's Important 1), or that check_data rejects later (Important 2).
HOSTILE_EDITIONS = {
    "dek is null": _set(["dek"], None),
    "move why is null": _set(["moves", 0, "why"], None),
    "move has no id": lambda d: d["moves"][0].pop("id"),
    "move is not an object": _set(["moves"], ["J3"]),
    "evidence text is a number": _set(["evidence", 0, "text"], 5),
    "evidence via is a number": _set(["evidence", 0, "via"], 7),
    "evidence url is empty": _set(["evidence", 0, "url"], ""),
    "evidence entry is null": _append(["evidence"], None),
    "strip pending is a string": _set(["strip", 4, "pending"], "established"),
    "strip entry is null": _set(["strip", 0], None),
    "pendingOwner entry is not an object": _set(["pendingOwner"], ["J4"]),
    "pendingOwner entry has no id": _set(["pendingOwner"], [{"from": "supported", "to": "established", "why": "w", "evidence": []}]),
    "releases entry is not an object": _set(["releases"], ["x"]),
    "nullCase text is a number": _set(["nullCase", "text"], 3),
    "correction is not an object": _set(["corrections"], ["oops"]),
    "correction was is null": _set(["corrections"], [{"date": "2026-10-08", "page": "jobs.html", "item": "x", "was": None,
                                                      "now": "n", "url": "https://example.org/c"}]),
    "evidence text is a data: string": _set(["evidence", 0, "text"], "Data: the series rose"),
}


class Hostile(unittest.TestCase):
    def test_every_hostile_edition_is_refused_and_nothing_is_written(self):
        for name, mutate in HOSTILE_EDITIONS.items():
            with self.subTest(name):
                doc = edition("2026-10-08")
                mutate(doc)
                env = Env([("2026-10-08", doc)])
                try:
                    before = (env.news / "data/corrections.json").read_bytes()
                    code, line = env.run()
                    self.assertEqual(code, 2, line)
                    self.assertFalse((env.news / "data/jobs").exists(), line)
                    self.assertEqual((env.news / "data/corrections.json").read_bytes(), before)
                finally:
                    env.close()

    def test_hostile_claims_are_refused(self):
        base = json.loads((FIX / "claims.json").read_text(encoding="utf-8"))
        cases = {
            "history row is not an object": lambda c: c["claims"][3]["history"].append("x"),
            "marks is a list": lambda c: c["claims"][5].__setitem__("marks", ["a"]),
            "indicator url is javascript:": lambda c: c["claims"][1]["indicators"][0].__setitem__("url", "javascript:alert(1)"),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                claims = json.loads(json.dumps(base))
                mutate(claims)
                env = Env([("2026-10-08", edition("2026-10-08"))], claims=claims)
                try:
                    code, line = env.run()
                    self.assertEqual(code, 2, line)
                    self.assertFalse((env.news / "data/jobs").exists())
                finally:
                    env.close()

    def test_validators_never_raise(self):
        from checks.jobs import validate_claims, validate_edition
        for junk in ([], "x", {"strip": 5, "evidence": "x", "moves": {"a": 1}}, {"claims": [None, 3]}):
            self.assertTrue(validate_edition(junk, "data/jobs/2026-10-09.json"))
            self.assertTrue(validate_claims(junk))


if __name__ == "__main__":
    unittest.main()
