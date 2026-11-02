# Explicit container matching and Watchtower coverage — design

Date: 2026-11-02. Target version: 0.2.2.

## Why

On 2 Nov the dashboard showed Sleep Wellness Tracker as ❌ "HTTP 401 Error" while the app was fine. Each core app is found by a loose keyword (`"sleep"`), and the first matching container in Docker's list wins. Docker lists the newest containers first, so after Watchtower recreated sleepwell, `sleep_backend` (port 8000, needs login, answers 401) was picked instead of `sleep_frontend_web`. Audio Scrobbler and the expense tracker only work today because of the order Docker happens to list them in. If an app's container disappears altogether, its row silently vanishes.

Separately, from 20 Oct to 2 Nov sleepwell's Watchtower watched zero containers (scope tag on Watchtower but not on the app containers), so releases #21–#24 never deployed. The dashboard, had it existed, would have shown a green tick with a small grey "(watching no containers)" note. The owner wants a 2-second glance to catch this.

## Goals

1. Each core app is matched to exactly the right container, every time, regardless of Docker's list order or container renames.
2. A missing container is a visible ❌, never a silently missing row.
3. Each app and Watchtower row shows what was actually checked, so a wrong match is obvious.
4. A Watchtower looking after zero containers is a ❌ **with a note explaining why** (owner's decision).
5. The owner's own three apps flag when their checked container isn't covered by any Watchtower.

## Non-goals

- Checking whether each app runs the newest image from GitHub.
- Changing any of the other apps' repos or compose files.
- A new amber/warning state. The dashboard stays tick or cross, with notes.

## Anti-goals

- Configuration living only on the NUC (git-ignored file etc.). That kind of drift caused the sleepwell outage; the app list lives in this repo.
- Reading, storing, logging or displaying any Watchtower environment variable other than the scope. Those environments can hold notification URLs and tokens.
- New false alarms. Jellyfin and Cloudflare are not auto-updated by design and must not show "not auto-updated".

## How containers are matched (decided)

Use the labels Docker Compose puts on every container it starts: `com.docker.compose.project` and `com.docker.compose.service`. These survive recreation and renames. Cloudflare was started without Compose and has no labels, so it is matched by exact container name.

Live labels as reported from the NUC on 2 Nov:

| App | Match | Probe | Expect Watchtower coverage |
|---|---|---|---|
| Audio Scrobbler | project `audio-scrobbler-app`, service `backend` | port 8010, `/health` | yes |
| UK Expense Tracker | project `uk-expense-tracker`, service `expense-tracker-web` | port 8502, `/` | yes |
| Sleep Wellness Tracker | project `sleep-wellness-tracker`, service `frontend_web` | port 8510, `/` | yes |
| Jellyfin Server | project `jellyfin`, service `jellyfin` | port 8096, `/health` | no |
| Cloudflare Tunnel | container name `cloudflared` | none (running check only) | no |

The port and path are fixed in the definition (not taken from the container's published ports), so the probe target never depends on port ordering. All probes stay on `127.0.0.1`.

Note: `e24ad8b74e3c_uk_expense_tracker` is service `expense-tracker` (port 8501), a different service from the web app, so it is not a duplicate. Its odd name is Docker's rename after a clashing recreate and is out of scope.

## Core app rows

- **Found and probe OK:** ✅, status as today, plus the checked container's name and the address probed (e.g. `sleep_frontend_web · :8510/`).
- **Not found:** ❌ with "Container not found (expected sleep-wellness-tracker / frontend_web)". Counts towards overall health.
- **More than one container matches:** use the running one; if several are running, use the first and add the note "N containers match". (Builder's choice how to break ties, but it must be deterministic and noted.)
- **Not covered by a Watchtower** (only for apps marked "expect coverage"): note "not auto-updated: no Watchtower is watching <container>". The tick colour is decided by the probe; this is a note, not a cross. *My call — keeps the cross for "the app is broken", while the Watchtower row below carries the cross for "updates are broken".*

## Watchtower rows

- **Finding its scope**, in this order: the container's `com.centurylinklabs.watchtower.scope` label; else the `WATCHTOWER_SCOPE` value from the container's environment (from Docker's inspect endpoint — read just that one variable and throw away the rest); else a `--scope <name>` argument in its command; else no scope. The scrobbler and expense Watchtowers have no scope label on the NUC, so the fallbacks are needed.
- **Settings read from the environment** are a fixed allow-list of non-secret Watchtower settings: `WATCHTOWER_SCOPE` and `WATCHTOWER_LABEL_ENABLE`. Every other variable is discarded unread. *My call — `LABEL_ENABLE` is a true/false flag, not a secret, and is needed to count correctly.*
- **Watched containers:** every other **running** container whose scope label equals the Watchtower's scope, then narrowed as Watchtower itself would:
  - if the command lists container names (e.g. `sleep_backend sleep_frontend_web`), only those names;
  - if label-enable is on (env `WATCHTOWER_LABEL_ENABLE=true` **or** a `--label-enable` command flag), only containers labelled `com.centurylinklabs.watchtower.enable=true`;
  - containers labelled `com.centurylinklabs.watchtower.enable=false` are always excluded.
  Shown in the row, e.g. "watching sleep_backend, sleep_frontend_web". *My call — stopped containers don't count because Watchtower skips them by default.*
- **Zero watched containers:** ❌ with the note "watching no containers — no container carries the scope label `<scope>`, so nothing will be updated". The existing log-based `Scanned=0` signal becomes a ❌ with a note too.
- **No scope at all:** keep ✅ with the note "no scope set: watches all unscoped containers". It counts as watching only running containers that carry **no** scope label (current Watchtower behaviour), so it never hides a missing scope match for the owner's apps. *My call.*
- **Coverage for core apps (goal 5):** an app is covered only if a **running** Watchtower's watched list includes its checked container. A stopped Watchtower is already ❌ and covers nothing. *My call.*
- Existing log checks (errors, failed sessions, warnings as notes) are unchanged.

Watchtower settings on the NUC as reported on 2 Nov (mock data should mirror these):

| Watchtower | Scope from | Label-enable |
|---|---|---|
| `sleep_watchtower` | label `sleep-wellness-tracker` | no (its log shows `Scanned=2` with no `enable` labels on its apps) |
| `watchtower_expense_tracker` | env and `--scope expense_tracker` | yes (`--label-enable` flag) |
| `audio-scrobbler-app-watchtower-1` | env `audio-scrobbler-app` | yes (env) |

`enable=true` is set on `uk_expense_tracker_web`, `e24ad8b74e3c_uk_expense_tracker`, and the scrobbler `backend`, `worker` and `frontend` containers. No sleepwell container has an `enable` label.

**Expected live result on day one:** all three Watchtowers ✅ — sleep watching 2, expense watching 2, scrobbler watching 3 — and all five core apps ✅ with no "not auto-updated" note. Any ❌ on first live check means the code is wrong, not the NUC.

## Where it shows up

- The dashboard UI (`static/app.js`) shows the new note text and the checked container/address. Visual change, so it gets the mock preview and owner review.
- The diagnostic report (`src/report_builder.py`) includes the same reasons.
- The mock scenarios (`src/mock_data.py`) are updated to match the real NUC layout, and gain one scenario with a Watchtower watching nothing and one with a missing app container.
- API response fields are added, not renamed or removed. *My call.*

## Tests required

- The sleepwell case: `sleep_backend` listed before `sleep_frontend_web` → the frontend is probed at 8510.
- The list order is shuffled for every app → same matches.
- The app container is missing → ❌ "not found", and the row is still present.
- Watchtower scope found from the label, from `WATCHTOWER_SCOPE` and from `--scope`; the other env values never appear in the output.
- Watchtower with zero matching containers → ❌ with a reason note.
- Owner app not covered → note; Jellyfin/Cloudflare never get that note.

## Left to the builder

Code structure, field names, exact wording of notes (plain English, short), how the UI lays out the extra line.
