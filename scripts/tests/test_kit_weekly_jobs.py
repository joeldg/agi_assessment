"""The weekly send's live check covers the Jobs page when the wrap-up carries Jobs (the 2026-10-06 review's Minor 1,
re-graded: the email links "Full tracker" to jobs.html, so it must be published before the email goes out)."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import kit_broadcast  # noqa: E402


class LiveFiles(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="kit-weekly-"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_without_jobs_the_lists_are_unchanged(self):
        live, files = kit_broadcast.weekly_live_files("2026-10-09", self.root)
        self.assertEqual(live, [kit_broadcast.SITE + "weekly/2026-10-09.html"])
        self.assertEqual(files, ["weekly/2026-10-09.html", "data/weekly/2026-10-09.json"])

    def test_with_jobs_the_page_and_data_must_be_live(self):
        (self.root / "data/jobs").mkdir(parents=True)
        (self.root / "data/jobs/2026-10-09.json").write_text("{}")
        live, files = kit_broadcast.weekly_live_files("2026-10-09", self.root)
        self.assertIn(kit_broadcast.SITE + "jobs.html", live)
        for f in ("jobs.html", "data/jobs/2026-10-09.json", "data/jobs/claims.json"):
            self.assertIn(f, files)


if __name__ == "__main__":
    unittest.main()
