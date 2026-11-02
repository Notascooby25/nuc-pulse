# Explicit Container Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Match each core app to its exact container by Docker Compose labels, show a ❌ for missing containers, and show which containers each Watchtower actually looks after, with a ❌ and reason when it looks after none.

**Architecture:** All detection stays in `src/app_inspector.py`. A pass over Docker's container list builds watchtower rows (using `/containers/{id}/json` for allow-listed settings), then a second pass matches core apps by label and adds coverage notes. The UI, report and mock data only display the new fields.

**Tech Stack:** Python 3.11, FastAPI, httpx (Docker socket + `httpx.MockTransport` in tests), pytest-asyncio, vanilla JS.

**Spec:** `docs/superpowers/specs/2026-11-02-explicit-container-matching-design.md`

## Global Constraints

- Version `0.2.2` in `pyproject.toml`; one `CHANGELOG.md` entry, plain English.
- From a Watchtower's environment read only `WATCHTOWER_SCOPE` and `WATCHTOWER_LABEL_ENABLE`; never store, log or return any other env value or the raw command line (it can hold `--http-api-token`, `--notification-url`).
- API response fields are added only; existing fields keep their names and meaning (`container_name`, `port`, `status_text`, `scope`, `healthy`, `log_tail`).
- Probes stay on `127.0.0.1`.
- Public repo: no IPs, hostnames, account IDs or secrets in code, tests, docs or PR text.
- Lint `.venv/bin/ruff check .` and tests `PYTHONPATH=. .venv/bin/pytest -v` must pass after every task.

## Review Focus

1. Watchtower command contains a secret flag value (`--http-api-token abc123`) → that value never appears in any returned field, and is not mistaken for a container name.
2. Docker inspect call for a Watchtower fails or returns 404 → scope falls back to the list-API label; no exception, row still shown.
3. Matching core-app container is stopped while a second (renamed) copy is running → the running one is checked, note "2 containers match".
4. Container `Labels` is `null` in Docker's JSON → treated as empty, no crash.
5. A Watchtower's own container carries its scope label (sleepwell does) → it is never listed as watching itself.

---

### Task 1: Watchtower settings and watched containers

**Files:**
- Modify: `src/app_inspector.py` (watchtower block, lines 178–210; remove `c.get("Command")` scope fallback)
- Modify: `tests/test_false_alarms.py`, `tests/test_app_inspector.py` (fixtures that relied on keyword matching / Command-as-scope)
- Create: `tests/test_watchtower_coverage.py`

**Interfaces:**
- Produces:
  - `_watchtower_settings(list_labels: dict, inspect_json: dict | None) -> dict` returning `{"scope": str | None, "label_enable": bool, "names": list[str]}`.
  - `_watched_containers(settings: dict, self_name: str, containers: list[dict]) -> list[str]` — `containers` are raw Docker list entries; returns sorted container names.
  - New param `inspect_apps_and_containers(..., app_definitions: list[dict] | None = None)`; `None` means `CORE_APP_DEFINITIONS`. Tests that only care about Watchtowers pass `[]`.
  - Each watchtower row gains `"watching": list[str]` and `"running": bool`. `scope` shows the found scope, or `"none (watches all unscoped)"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_watchtower_coverage.py`, using a `_container(name, *, labels=None, state="running")` helper and a Docker mock that answers `/containers/json`, `/containers/{id}/json` and `/logs`:
  - `test_scope_from_label`: sleep watchtower labelled `scope=sleep-wellness-tracker`, plus `sleep_backend`, `sleep_frontend_web` with the same scope label → `wt["watching"] == ["sleep_backend", "sleep_frontend_web"]`, `wt["healthy"] is True`, `"sleep_watchtower" not in wt["watching"]`.
  - `test_scope_and_label_enable_from_env`: inspect `Config.Env = ["WATCHTOWER_SCOPE=audio-scrobbler-app", "WATCHTOWER_LABEL_ENABLE=true", "WATCHTOWER_NOTIFICATION_URL=https://example.invalid/secret"]`; containers `backend` (scope + `enable=true`), `db` (scope only) → `watching == ["backend"]`; `"secret" not in json.dumps(res)`.
  - `test_scope_and_label_enable_from_command`: `Config.Cmd = ["--label-enable", "--cleanup", "--interval", "300", "--scope", "expense_tracker", "--http-api-token", "abc123"]` → scope `expense_tracker`, label-enable on, `"abc123" not in json.dumps(res)`.
  - `test_names_in_command_limit_watching`: `Config.Cmd = ["sleep_backend"]`, no scope, two unscoped app containers → `watching == ["sleep_backend"]`.
  - `test_enable_false_is_excluded` and `test_stopped_containers_are_not_watched`.
  - `test_watching_nothing_is_a_cross_with_reason`: scope label `sleep-wellness-tracker`, apps unlabelled → `healthy is False`, `res["all_healthy"] is False`, `"no running container carries the scope label" in wt["status_text"]` and `"sleep-wellness-tracker" in wt["status_text"]`.
  - `test_no_scope_watches_unscoped_only`: unscoped watchtower, one unscoped and one scoped container → `watching` is the unscoped one, `"no scope set" in status_text`, healthy.
  - `test_inspect_failure_falls_back_to_list_labels` (inspect returns 404) and `test_null_labels_are_handled` (`"Labels": None`).

- [ ] **Step 2: Run** `PYTHONPATH=. .venv/bin/pytest tests/test_watchtower_coverage.py -v` — expect FAIL (`watching` key missing / unexpected `app_definitions`).

- [ ] **Step 3: Implement** `_watchtower_settings`, `_watched_containers`, the inspect call and the `app_definitions` param.
  - Scope order: list label `com.centurylinklabs.watchtower.scope` → env `WATCHTOWER_SCOPE` → `--scope X` / `--scope=X` in `Config.Cmd` → `None`.
  - Label-enable: env `WATCHTOWER_LABEL_ENABLE` in `("true", "1")` or `--label-enable` in Cmd.
  - Names from Cmd: a token not starting with `-` is a name unless the previous token is a value-taking flag. Treat as boolean (no value) only: `--cleanup --label-enable --debug --trace --run-once --monitor-only --rolling-restart --include-stopped --include-restarting --revive-stopped --no-pull --no-restart --no-startup-message --remove-volumes --http-api-update --http-api-metrics --enable-lifecycle-hooks --label-take-precedence`; any other `--flag` without `=` consumes the next token.
  - Watched: running, not self, `enable != "false"`, scope label equal to scope (or no scope label when scope is `None`), `enable == "true"` when label-enable, and name in `names` when `names` is non-empty.
  - Row status: problems (errors-in-logs, zero watched) → `healthy False`, `status_text` = problems joined with `"; "`. Zero-watched wording: `f"Watching no containers — no running container carries the scope label `{scope}`{' with enable=true' if label_enable else ''}, so nothing will be updated"`. Otherwise `status` plus notes as today, adding `"no scope set: watches all unscoped containers"` when scope is `None`.
  - `_assess_watchtower_logs`: a last session with `Scanned=0` becomes a problem (`"last check scanned 0 containers"`), not a note.

- [ ] **Step 4: Update existing tests** to the new behaviour: in `tests/test_false_alarms.py` give `_watchtower_with_logs` a watched unscoped container and pass `app_definitions=[]`; change `test_watchtower_watching_nothing_is_noted` to `test_watchtower_scanning_nothing_is_a_cross` (`healthy is False`, `"scanned 0" in status_text`). In `tests/test_app_inspector.py` replace the `Command`-as-scope assertion with a `Config.Cmd` names check and pass `app_definitions=[]` where core apps aren't the subject.

- [ ] **Step 5: Run** the full suite and lint — expect all PASS, ruff clean.

- [ ] **Step 6: Commit** `fix: show which containers each Watchtower watches; cross when none`.

### Task 2: Core apps matched by Compose labels, with coverage notes

**Files:**
- Modify: `src/app_inspector.py` (`CORE_APP_DEFINITIONS`, app-matching loop lines 212–246)
- Create: `tests/test_container_matching.py`
- Modify: `tests/test_false_alarms.py::test_scrobbler_is_checked_at_its_health_address`, `tests/test_app_inspector.py::test_inspect_apps_and_containers_with_mock_docker`

**Interfaces:**
- Consumes: watchtower rows with `"watching"` and `"healthy"` from Task 1.
- Produces: `CORE_APP_DEFINITIONS` entries `{"id", "name", "match": {"project": str, "service": str} | {"container_name": str}, "port": int | None, "health_path": str | None, "expect_watchtower": bool}`; `_find_app_container(match: dict, containers: list[dict]) -> tuple[dict | None, int]` (chosen raw container, number matching). Each core-app row gains `"probe_target": str | None` (e.g. `":8510/"`) and `"notes": list[str]`.

Definitions (copy exactly):

| id | name | match | port | health_path | expect_watchtower |
|---|---|---|---|---|---|
| audio_scrobbler | Audio Scrobbler | project `audio-scrobbler-app`, service `backend` | 8010 | `/health` | True |
| expense_tracker | UK Expense Tracker | project `uk-expense-tracker`, service `expense-tracker-web` | 8502 | `/` | True |
| sleepwell | Sleep Wellness Tracker | project `sleep-wellness-tracker`, service `frontend_web` | 8510 | `/` | True |
| jellyfin | Jellyfin Server | project `jellyfin`, service `jellyfin` | 8096 | `/health` | False |
| cloudflared | Cloudflare Tunnel | container_name `cloudflared` | None | None | False |

- [ ] **Step 1: Write the failing tests** in `tests/test_container_matching.py`, with a fixture `NUC_CONTAINERS` mirroring the real layout (names, project/service/scope/enable labels as in the spec, `sleep_backend` listed **before** `sleep_frontend_web`, plus the three Watchtowers with their real settings via inspect) and a probe mock recording `request.url.port` and path:
  - `test_sleepwell_probes_frontend_not_backend`: probe for sleepwell hit `(8510, "/")`; app healthy; `container_name == "sleep_frontend_web"`. Probe mock returns 401 for port 8000, so a wrong match fails.
  - `test_order_does_not_change_matches`: run with `NUC_CONTAINERS` and `reversed(NUC_CONTAINERS)` → identical `{id: container_name}` maps.
  - `test_missing_container_is_a_cross_not_a_gap`: drop `sleep_frontend_web` → sleepwell row present, `healthy False`, `status_text == "Container not found (expected sleep-wellness-tracker / frontend_web)"`.
  - `test_running_copy_preferred_and_noted`: add a stopped `sleep_frontend_web_old` with the same labels → running one chosen, `"2 containers match" in notes`.
  - `test_uncovered_owner_app_gets_note`: strip scope labels from sleepwell containers → sleepwell row still `healthy True`, notes contain `"not auto-updated: no Watchtower is watching sleep_frontend_web"`.
  - `test_jellyfin_and_cloudflared_never_get_coverage_note`.
  - `test_real_layout_is_all_green`: full `NUC_CONTAINERS` → `res["all_healthy"] is True`, every core app healthy with no notes, watchers `{"sleep_watchtower": 2, "watchtower_expense_tracker": 2, "audio-scrobbler-app-watchtower-1": 3}` by `len(watching)`.

- [ ] **Step 2: Run** `PYTHONPATH=. .venv/bin/pytest tests/test_container_matching.py -v` — expect FAIL.

- [ ] **Step 3: Implement** the definitions, `_find_app_container`, and the second pass.
  - Matching on raw list entries' `Labels` (`com.docker.compose.project` / `com.docker.compose.service`) or exact name. Tie-break: running before not running, then by name ascending; count > 1 adds note `f"{count} containers match"`.
  - Not found → row with `healthy False`, `container_name None`, `port` from the definition, `probe_target None`.
  - Found with port and path → probe `127.0.0.1:{port}{path}`; status as today. Found without port → running check only.
  - Coverage: for `expect_watchtower` apps, covered when any watchtower row with `running True` has the container name in `watching` (its `healthy` doesn't matter); a stopped Watchtower covers nothing. Note copy: `f"not auto-updated: no Watchtower is watching {name}"`. Notes never change `healthy`.

- [ ] **Step 4: Update existing tests**: scrobbler test gets compose labels `audio-scrobbler-app`/`backend`, asserts the probe went to port 8010 `/health`; the big fixture in `tests/test_app_inspector.py` gets compose labels for the apps it asserts on.

- [ ] **Step 5: Run** full suite and lint — expect PASS.

- [ ] **Step 6: Commit** `fix: match core apps by compose labels; cross for missing containers (sleepwell 401)`.

### Task 3: Show it — UI, report, mock data, version

**Files:**
- Modify: `static/app.js` (`renderCoreApps`, `renderWatchtowers`), `static/style.css` (only if a new line needs a class; reuse `.app-sub` / `.pipeline-sub`)
- Modify: `src/report_builder.py` (section 4)
- Modify: `src/mock_data.py` (apps block)
- Modify: `pyproject.toml`, `CHANGELOG.md`
- Test: `tests/test_report_builder.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `probe_target`, `notes` (core apps) and `watching` (watchtowers) from Tasks 1–2.

- [ ] **Step 1: Write the failing tests**:
  - `tests/test_report_builder.py::test_report_shows_watchtower_reason_and_watching`: degraded mock → report contains `"sleep_watchtower"`, `"no running container carries the scope label"`.
  - `tests/test_report_builder.py::test_report_lists_app_notes`: degraded mock → report contains `"Container not found"` (Jellyfin) and `"not auto-updated"` (sleepwell).
  - `tests/test_api.py::test_mock_nominal_mirrors_real_layout`: nominal mock → every core app has `probe_target` key and `notes == []`; sleepwell `container_name == "sleep_frontend_web"`; each watchtower has a non-empty `watching`.

- [ ] **Step 2: Run** those tests — expect FAIL.

- [ ] **Step 3: Implement.**
  - Mock nominal: real container names, ports and Watchtower scopes/watching lists from the spec; scrobbler `container_name "audio-scrobbler-app-backend-1"`, port 8010. Mock degraded: keep the expense HTTP 500; `sleep_watchtower` ❌ with the zero-watched reason and `watching []`; sleepwell note "not auto-updated…"; Jellyfin ❌ "Container not found (expected jellyfin / jellyfin)"; add matching `attention_items`.
  - Report: core-app lines append `probe_target` when set; a "Notes" bullet for any core app with notes (healthy or not); watchtower block adds `- **Watching:** a, b` or `none`.
  - UI: app card gets a second `.app-sub` line `container_name · probe_target` (or the not-found text), and each note as its own `.app-sub` line; watchtower sub-line shows `Scope: … • Watching: a, b • status_text`. All via `escapeHtml`.
  - `pyproject.toml` → `0.2.2`; `CHANGELOG.md` `## 0.2.2 - 2026-11-02` with: apps found by their Compose app/role so Sleep Wellness no longer shows a false 401; a missing container shows a cross instead of vanishing; Watchtowers show what they look after and a cross with a reason when nothing; scrobbler and expense tracker checks no longer depend on Docker's list order.

- [ ] **Step 4: Run** full suite and lint — expect PASS.

- [ ] **Step 5: Preview.** `scripts/preview.sh up`, open `http://localhost:8520`, check Nominal (all green, sub-lines show the real container names) and Simulate Failure (sleep_watchtower ❌ with reason, Jellyfin ❌ not found, sleepwell note); take screenshots for the owner. Leave the preview running for the owner's review.

- [ ] **Step 6: Commit** `feat: show checked container, notes and Watchtower coverage; 0.2.2`.

### Task 4: Review and hand-off

- [ ] **Step 1:** Run the differential-review skill on `main..fix/explicit-container-matching`; fix findings on the branch; report by severity.
- [ ] **Step 2:** Run verification-before-completion: full test + lint output shown to the owner.
- [ ] **Step 3:** Push the branch and open a PR using `.github/pull_request_template.md` (every heading filled; Go-ahead: "Waiting for the owner"). Do not merge — merging is going live.
- [ ] **Step 4:** After the owner merges and the auto-updater has run, live check: Sleep Wellness ✅ at `sleep_frontend_web · :8510/`, three Watchtowers ✅ watching 2 / 2 / 3. Any ❌ here is a code bug (per spec).
