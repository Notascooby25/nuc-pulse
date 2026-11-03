# Accurate DNF Update and Security Advisory Counting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the Fedora OS update detector in NUC Pulse so pending total updates and security updates match Cockpit and the real server state (`dnf check-update`), eliminating false security alarms.

**Architecture:** Replace the advisory bulletin query (`dnf updateinfo list --security --available -q`) and naive line-splitting counter (`_count_dnf_lines`) in `src/system_collector.py` with direct `dnf check-update` calls using cache-only (`-C`). In DNF5 (Fedora 41+), use `--json` for exact structured counts; for plain text, filter out table headers (`Upgrades`, `Name`, etc.) and obsoleting blocks, counting only valid package upgrade rows.

**Tech Stack:** Python 3.11+, FastAPI, DNF5 / DNF4 command line tool, pytest-asyncio.

**Spec:** Bug investigation in chat: on Fedora 44, Cockpit reported 2 bugfix updates (`docker-compose-plugin`, `tailscale`) and 0 security updates. NUC Pulse reported 5 updates (5 security) because `updateinfo list` matched multi-package kernel advisories for older installed kernels, table headers were counted as packages, and `total = max(security, ...)` forced both to 5.

## Global Constraints

- Version `0.2.3` in `pyproject.toml`; one `CHANGELOG.md` entry in plain English.
- Run `dnf check-update` with `-C` (`--cacheonly`) and a fast timeout so background polling every 30 seconds does not hang or hit the network.
- Public repo: no hostnames, IPs, secrets, or account IDs in code, tests, docs, or PR text.
- Lint `.venv/bin/ruff check .` and tests `PYTHONPATH=. .venv/bin/pytest -v` must pass after every task.
- When there are pending non-security updates and 0 security updates, `healthy` must be `True` (no false alarm in attention items).

## Review Focus

1. Zero updates available (`dnf check-update` returns exit code 0 or empty upgrades list) → `total_updates: 0`, `security_updates: 0`, `healthy: True`, summary `"All updates installed"`.
2. Only non-security updates available (e.g. 2 updates, 0 security) → `total_updates: 2`, `security_updates: 0`, `healthy: True`, summary `"2 updates pending (0 security)"`, no attention items.
3. Security updates present (e.g. 3 updates total, 1 security) → `total_updates: 3`, `security_updates: 1`, `healthy: False`, summary `"3 updates pending (1 security)"`, attention item `"1 OS security updates pending"`.
4. Plain-text DNF output containing header lines (`Upgrades`, `Name Type Severity Package Issued`, `Obsoleting Packages`) → headers are never counted as package updates.
5. DNF command fails or is unavailable → gracefully returns 0 updates with `healthy: True` without crashing or throwing unhandled exceptions.

---

### Task 1: Add failing tests for accurate DNF update detection

**Files:**
- Modify: `tests/test_system_collector.py`

**Interfaces:**
- Consumes: `src.system_collector.collect_os_updates(updates_file: str)`
- Produces: Updated test cases in `tests/test_system_collector.py` reproducing the bug (where only non-security updates exist) and testing both JSON and text fallback parsing.

- [ ] **Step 1: Write failing tests in `tests/test_system_collector.py`**
  - Add `test_collect_os_updates_fedora_dnf_json_non_security`: mocks DNF5 `--json` output where 2 updates are available (`docker-compose-plugin` and `tailscale`) and 0 security updates exist. Asserts `total_updates == 2`, `security_updates == 0`, `healthy is True`, and `"2 updates pending (0 security)" in res["summary"]`.
  - Add `test_collect_os_updates_fedora_dnf_text_fallback`: mocks DNF text output with headers (`Upgrades (available for reinstall, available for upgrade)` followed by 2 package lines) and empty security output. Asserts header is ignored, `total_updates == 2`, `security_updates == 0`.
  - Update `test_collect_os_updates_fedora_dnf` to test genuine `check-update` command invocation rather than `updateinfo`.

- [ ] **Step 2: Run tests to verify failure**
  Run: `PYTHONPATH=. .venv/bin/pytest tests/test_system_collector.py -v`
  Expected: FAIL on the new tests because current code still queries `updateinfo` and miscounts headers.

---

### Task 2: Implement robust DNF check-update and JSON/text parsing

**Files:**
- Modify: `src/system_collector.py:121-203`

**Interfaces:**
- Produces:
  - `_parse_dnf_check_update(output: str) -> int` — parses JSON if possible, otherwise filters non-package lines from text output.
  - Updated `_get_os_updates_sync(updates_file: str) -> dict` calling `["dnf", "check-update", "--security", "--json", "-C"]` and `["dnf", "check-update", "--json", "-C"]` (with fallback to non-json if `--json` is unrecognised).

- [ ] **Step 1: Implement `_parse_dnf_check_update` and update `_get_os_updates_sync` in `src/system_collector.py`**
  - Replace `_count_dnf_lines` with `_parse_dnf_check_update`.
  - Use `dnf check-update --security` and `dnf check-update` with `-C`.
  - Set `healthy = security == 0`.
  - Format summary as `"All updates installed"` when `total == 0`, else `f"{total} updates pending ({security} security)"`.

- [ ] **Step 2: Run tests to verify they pass**
  Run: `PYTHONPATH=. .venv/bin/pytest tests/test_system_collector.py -v`
  Expected: PASS

- [ ] **Step 3: Run full test suite and linter**
  Run: `PYTHONPATH=. .venv/bin/pytest -v && .venv/bin/ruff check .`
  Expected: All 64+ tests pass, lint passes.

---

### Task 3: Version bump and documentation update

**Files:**
- Modify: `pyproject.toml` (bump version to `0.2.3`)
- Modify: `CHANGELOG.md` (add release entry for `0.2.3`)

- [ ] **Step 1: Bump version to `0.2.3` in `pyproject.toml`**
- [ ] **Step 2: Add plain-English changelog entry under `## 0.2.3` in `CHANGELOG.md`**
- [ ] **Step 3: Verify tests and lint**
  Run: `PYTHONPATH=. .venv/bin/pytest -v && .venv/bin/ruff check .`

