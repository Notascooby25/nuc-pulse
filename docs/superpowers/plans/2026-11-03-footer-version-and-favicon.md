# Footer Version, What's New and Favicon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the running version in the dashboard footer with a "What's new" link that opens the latest changelog entry, and use the header's 🖥️ as the browser-tab icon.

**Architecture:** A small parser in `src/changelog.py` reads the newest `## <version> - <date>` entry from `CHANGELOG.md`. A new `GET /api/release` endpoint returns it. The footer fetches it once on page load and fills a version line and a `<dialog>` styled like the existing report modal. The favicon is an inline SVG data URI wrapping the 🖥️ emoji.

**Tech Stack:** Python 3.11, FastAPI, vanilla JS, pytest-asyncio. No new dependencies.

**Spec:** Agreed in chat on 2026-11-03: footer shows the version number and a "What's new" link; clicking it shows that version's full changelog entry in a pop-up like Export Issues; favicon is the header's 🖥️; version and notes come from `CHANGELOG.md` so they update with each release; if the changelog can't be read the line is hidden.

## Global Constraints

- Version `0.2.4` in `pyproject.toml`; one plain-English `CHANGELOG.md` entry for 0.2.4.
- No new dependencies (`tomllib` is in the standard library).
- Changelog text is shown with `escapeHtml` / `textContent`, never as raw HTML.
- Public repo: no hostnames, IPs, secrets or account IDs.
- Lint `.venv/bin/ruff check .` and tests `PYTHONPATH=. .venv/bin/pytest -v` pass after every task.
- Use the Impeccable skill for the footer and pop-up styling.

## Review Focus

1. `CHANGELOG.md` missing or unreadable on the server → `/api/release` returns `{"version": null, "date": null, "changes": []}` with status 200; the footer version line stays hidden; the rest of the dashboard works.
2. The intro paragraph above the first `##` heading → never treated as a change.
3. A bullet that wraps onto an indented second line → joined into one change, not dropped or split.
4. Changelog text containing `<`, `&` or backticks → shown literally in the pop-up.
5. `pyproject.toml` version and the newest changelog heading disagree → a test fails, so the footer can't show a stale version.

---

### Task 1: Changelog parser and `/api/release` endpoint

**Files:**
- Create: `src/changelog.py`
- Modify: `src/main.py` (add `CHANGELOG_PATH` constant and the endpoint)
- Test: `tests/test_changelog.py`

**Interfaces:**
- Produces: `latest_release(path: Path) -> dict | None` returning `{"version": str, "date": str, "changes": list[str]}`, or `None` when the file is missing/unreadable or has no `## <version> - <date>` heading.
- Produces: `src.main.CHANGELOG_PATH: Path` (repo root `CHANGELOG.md`), and `GET /api/release` returning `latest_release(CHANGELOG_PATH)` or `{"version": None, "date": None, "changes": []}`.

- [ ] **Step 1: Write the failing tests in `tests/test_changelog.py`**

```python
SAMPLE = """# Changelog

Intro text, not a change.

## 1.2.0 - 2026-01-05
- First change with <b>tag</b> & `code`.
- Second change that wraps
  onto a second line.

## 1.1.0 - 2026-01-01
- Older change.
"""

def test_latest_release_reads_newest_entry(tmp_path):
    p = tmp_path / "CHANGELOG.md"; p.write_text(SAMPLE)
    assert latest_release(p) == {
        "version": "1.2.0", "date": "2026-01-05",
        "changes": ["First change with <b>tag</b> & `code`.",
                    "Second change that wraps onto a second line."],
    }

def test_latest_release_missing_file_returns_none(tmp_path):
    assert latest_release(tmp_path / "nope.md") is None

def test_latest_release_no_version_heading_returns_none(tmp_path):
    p = tmp_path / "CHANGELOG.md"; p.write_text("# Changelog\n\nNothing yet.\n")
    assert latest_release(p) is None

def test_real_changelog_matches_pyproject_version():
    # tomllib.load(pyproject.toml)["project"]["version"] == latest_release(CHANGELOG_PATH)["version"]
    ...

async def test_api_release_returns_latest(): # GET /api/release → 200, version == pyproject version, changes non-empty
async def test_api_release_missing_changelog(monkeypatch, tmp_path):
    # monkeypatch src.main.CHANGELOG_PATH to tmp_path / "missing.md"
    # → 200, {"version": None, "date": None, "changes": []}
```

- [ ] **Step 2: Run** `PYTHONPATH=. .venv/bin/pytest tests/test_changelog.py -v` — Expected: FAIL (`ModuleNotFoundError: src.changelog`).

- [ ] **Step 3: Implement `latest_release` in `src/changelog.py`** — scan lines; the first line matching `^## (\S+) - (\S+)` starts the entry; `- ` lines start a change; indented non-blank lines append to the previous change with one space; stop at the next `## `. Catch `OSError` → `None`.

- [ ] **Step 4: Add `CHANGELOG_PATH` and `GET /api/release` to `src/main.py`** (reads the file on each request; it's tiny and changes only on deploy).

- [ ] **Step 5: Run** `.venv/bin/ruff check .` and `PYTHONPATH=. .venv/bin/pytest -v` — Expected: all pass.

- [ ] **Step 6: Commit** `feat: add changelog parser and /api/release endpoint`

### Task 2: Footer version line, What's new pop-up and favicon

**Files:**
- Modify: `static/index.html` (favicon `<link>`, footer line, `release-modal` dialog)
- Modify: `static/app.js` (`loadRelease()`, `openReleaseNotes()`, `closeReleaseNotes()`)
- Modify: `static/style.css` (footer version line, link-style button, release list)

**Interfaces:**
- Consumes: `GET /api/release` from Task 1.

- [ ] **Step 1: Favicon** — in `<head>`: `<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🖥️</text></svg>">`.

- [ ] **Step 2: Footer markup** — below the existing auto-refresh line add `<div id="release-line" class="release-line" hidden>` containing `<span id="release-version"></span> · <button type="button" class="link-btn" onclick="openReleaseNotes()">What's new</button>`. Add `<dialog id="release-modal" class="report-modal release-modal">` with a header (`What's new in v…`, date sub-line, `✕ Close` button like the report modal) and `<ul id="release-changes">`.

- [ ] **Step 3: JS** — `loadRelease()` runs once at start-up: fetch `/api/release`; if `version` is null or the fetch fails, leave `#release-line` hidden; otherwise set `v<version>`, fill the dialog title/date and one `<li>` per change via `escapeHtml`, then un-hide. `openReleaseNotes()` / `closeReleaseNotes()` call `showModal()` / `close()`.

- [ ] **Step 4: CSS** — `.link-btn` looks like an underlined text link in the footer colour with a visible focus ring; `.release-line` sits under the refresh line; release list readable at phone width (no horizontal scroll). Use the Impeccable skill to check this.

- [ ] **Step 5: Run** `scripts/preview.sh up`; open `http://localhost:8520`: tab shows 🖥️, footer shows `v0.2.3 · What's new`, pop-up lists 0.2.3's points and closes with ✕ and Esc. Check at phone width. Lint and tests pass.

- [ ] **Step 6: Commit** `feat: show version and What's new in footer; add 🖥️ favicon`

### Task 3: Release 0.2.4

**Files:**
- Modify: `pyproject.toml` (`version = "0.2.4"`), `CHANGELOG.md` (new 0.2.4 entry at the top)

- [ ] **Step 1:** Bump version and add the 0.2.4 entry, e.g. "The footer shows the running version, with a What's new link listing that version's changes." and "The browser tab shows the 🖥️ computer icon."
- [ ] **Step 2: Run** lint and full tests — `test_real_changelog_matches_pyproject_version` must pass.
- [ ] **Step 3: Commit** `chore: release 0.2.4`, push, open the pull request with the change record filled in, then run differential-review on the whole branch.
