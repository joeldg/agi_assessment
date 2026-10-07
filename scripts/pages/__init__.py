"""Page modules for the generated hubs of redesign v2 (definitions v2.0), plus the shared server-side pieces.

    common.py    the pieces several builders share (spec 6.9): the answer line, the eight-part strip, the Index
                 bar, the three answer cards, the numbers diagram and naming key, the static tracker. Used by
                 build_pages.py, build_report.py (short report) and build_weekly.py (new wrap-ups).
    home.py      index.html     "Today": three answer cards, top stories, coming up, explore
    agi.py       agi.html       "Is AGI here?": the definition and the eight-part tracker
    hidden.py    hidden.html    "Could it be hidden?": the Index, A-D, our odds, readings over time, gauges
    changes.py   changes.html   "Changes and corrections": method log, alarm criteria log, corrections
    archive.py   archive.html   "Every reading": one row per reading
    jobs.py      jobs.html      "Jobs watch": the Jobs plugin's tracker (only when data/jobs/ exists)

Each page module exports PAGE = dict(title, description, body, scripts_code, head_extra). `body` (and, where
it depends on data, `description`) is a callable that reads the live data files when build_pages.py builds the
site; `scripts_code` is the page's module script (build_pages wraps it with its PREAMBLE, so `K`, `j`, `link`
and `fd` are in scope). Import a module as `pages.home` with scripts/ on sys.path.
"""

# published path -> module name, for build_pages.py (WP-C1) to register: PAGES[path] = import_module(...).PAGE
MODULES = {
    "index.html": "home",
    "agi.html": "agi",
    "hidden.html": "hidden",
    "changes.html": "changes",
    "archive.html": "archive",
    "jobs.html": "jobs",
}


def all_pages():
    """{published path: PAGE} for every module here, imported on demand."""
    from importlib import import_module
    return {path: import_module(f"{__name__}.{mod}").PAGE for path, mod in MODULES.items()}
