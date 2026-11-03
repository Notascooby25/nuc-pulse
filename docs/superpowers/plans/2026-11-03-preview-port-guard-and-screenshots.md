# Preview Port Guard and Screenshot Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `scripts/preview.sh` from losing track of a running preview, and add a dev-only screenshot tool that captures the loaded preview at PC and phone sizes.

**Architecture:** `preview.sh` checks the port with bash's `/dev/tcp` before starting, only writes `.preview.pid` once the server is confirmed up, and `down`/`status` recognise a leftover preview by its exact command line. `scripts/screenshot.py` uses Playwright (Chromium, installed inside `.venv`) to wait for the dashboard's data, then saves shots to a folder given on the command line.

**Tech Stack:** bash, Python 3.11, Playwright for Python (dev only), pytest.

**Spec:** Agreed in chat on 2026-11-03 after the 0.2.4 release, when a leftover preview from 0.2.3 was found still serving old code on port 8520 and `up` had overwritten `.preview.pid` with a dead process. The owner approved the five `preview.sh` changes and asked for Playwright in the same pull request.

## Global Constraints

- Version `0.2.5` in `pyproject.toml`; one plain-English `CHANGELOG.md` entry.
- Playwright goes in `pyproject.toml` `[project.optional-dependencies] dev` only, **never** `requirements.txt`, because the NUC's auto-updater installs `requirements.txt`.
- Playwright's browser is installed into `.venv` (`PLAYWRIGHT_BROWSERS_PATH=0`), never the home folder.
- Screenshots are never saved inside the project folder; the output folder is a required argument.
- The default port stays 8520; `NUC_PULSE_PREVIEW_PORT` overrides it (tests only).
- `down` only stops a process whose command line contains this repo's `.venv/bin/uvicorn src.main:app` and `--port <PORT>`.
- CI has no `.venv`; script tests must not need uvicorn.

## Review Focus

1. Port busy with a non-preview process → `up` exits non-zero, leaves `.preview.pid` untouched, and `down` does not kill that process.
2. `.preview.pid` points to a dead process while a real leftover preview runs → `status` reports it and `down` stops it.
3. Start fails (e.g. uvicorn crashes) → `.preview.pid` removed, non-zero exit.
4. The screenshot tool is run while the preview is down → a clear error, no traceback wall.
5. The screenshot output path is inside the repo → refused.

---

### Task 1: `preview.sh` port guard

**Files:** Modify `scripts/preview.sh`; Create `tests/test_preview_script.py`

- [ ] **Step 1: Failing tests** — each test runs the script with `NUC_PULSE_PREVIEW_PORT` set to a free port, with a throwaway Python listener (`socket.bind` + `listen` in the test process) standing in for the "leftover":
  - `test_up_refuses_when_port_busy`: returncode != 0, output contains `already in use`, a pre-existing `.preview.pid` content is unchanged (use a copy of the script in a tmp repo dir so the real pid file is never touched).
  - `test_status_reports_untracked_listener`: output contains `in use` and not `STOPPED`.
  - `test_down_leaves_foreign_process_alone`: listener still accepting after `down`.
- [ ] **Step 2:** Run `PYTHONPATH=. .venv/bin/pytest tests/test_preview_script.py -v` — Expected: FAIL on `test_up_refuses_when_port_busy`.
- [ ] **Step 3:** Implement: `PORT="${NUC_PULSE_PREVIEW_PORT:-8520}"`; `port_in_use()` via `(exec 3<>/dev/tcp/127.0.0.1/$PORT)`; `leftover_pid()` via `pgrep -f` on the exact preview command; `up` writes the PID file only after the process is alive and the port answers (poll up to ~5s), otherwise removes it and exits 1; `down` stops the tracked PID, else a `leftover_pid`; `status` reports tracked / leftover / foreign / stopped.
- [ ] **Step 4:** Run lint and full tests — Expected: all pass. Manually on this PC: `up`, `up` again (says already running), `status`, `down`, `status`.
- [ ] **Step 5: Commit** `fix: preview.sh refuses a busy port and never loses track of a running preview`

### Task 2: Screenshot tool

**Files:** Create `scripts/screenshot.py`; Modify `pyproject.toml` (dev extra), `README.md` (one usage line)

- [ ] **Step 1:** Ask nothing further; install `.venv/bin/pip install playwright` and `PLAYWRIGHT_BROWSERS_PATH=0 .venv/bin/playwright install chromium`.
- [ ] **Step 2:** `scripts/screenshot.py OUT_DIR [--url http://localhost:8520]`: refuse an `OUT_DIR` inside the repo; for viewports desktop 1366×900 and phone 390×844, for scenarios `nominal` and `degraded`, load the page, click the scenario button, wait until `#master-status-text` no longer reads `CHECKING SYSTEMS...`, save full-page PNGs; also save one desktop shot with the What's new dialog open. Connection refused → one-line error, exit 1.
- [ ] **Step 3:** Run it against the preview into the scratchpad and look at every image.
- [ ] **Step 4: Commit** `feat: add dev-only Playwright screenshot tool for the preview`

### Task 3: Release 0.2.5

- [ ] Bump `pyproject.toml` to `0.2.5`, add the changelog entry, run lint and tests, commit `chore: release 0.2.5`, push, open the PR with the change record, run differential-review and a fresh whole-branch review.
