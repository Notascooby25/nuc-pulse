# AI Agent Instructions

## Set-up answers
- **What it is and who uses it:** NUC Pulse is a lightweight system, Watchtower, and backup sanity dashboard for the owner's Intel NUC server, providing a 2-second visual status check (green ticks / red crosses).
- **GitHub:** Public (`nuc-pulse`). **Backup:** GitHub remote + local NUC deployment.
- **Real data held, and where:** Zero personal or secret data held. The application only inspects local system vitals and status.
- **How it goes live, and the master copy:** Master copy is on GitHub; goes live on the NUC through the auto-updater (`scripts/autoupdate.sh`, a systemd timer every 15 minutes), which fast-forwards to `origin/main` and restarts the service. Merging a pull request on GitHub is going live.
- **Preview:** Local preview script `scripts/preview.sh` with realistic mock scenarios (`NUC_PULSE_MOCK=1`).
- **Process:** full (`safe-change` process: feature branch, automated tests, preview verification, explicit user go-ahead before merging).
- **Version and changelog:** version in `pyproject.toml`; every release adds one entry to `CHANGELOG.md`.

## How to work here
Follow the shared `safe-change` skill for every change. For a public repo, never commit IPs, hostnames, account IDs, secrets or known weaknesses.
Every change reaches `main` through a pull request on GitHub, with the change record filled in; never merge into `main` on this PC.
- **Frontend / Visual changes:** Always start the local mock preview (`scripts/preview.sh up`) and explicitly prompt the owner to review `http://localhost:8520` locally before asking for the go-ahead to merge and go live.

## Commands
- Lint: `.venv/bin/ruff check .`
- Test: `PYTHONPATH=. .venv/bin/pytest -v`
- Preview: `scripts/preview.sh up` (mock data, this PC only); `scripts/preview.sh down` to stop.

## Must never be edited
- Live secrets or non-redacted credentials.
