# AI Agent Instructions

## Set-up answers
- **What it is and who uses it:** NUC Pulse is a lightweight system, Watchtower, and backup sanity dashboard for the owner's Intel NUC server, providing a 2-second visual status check (green ticks / red crosses).
- **GitHub:** Public (`nuc-pulse`). **Backup:** GitHub remote + local NUC deployment.
- **Real data held, and where:** Zero personal or secret data held. The application only inspects local system vitals and status.
- **How it goes live, and the master copy:** Master copy is on GitHub; goes live on the NUC under `/srv/nuc-pulse` via git pull or Watchtower.
- **Preview:** Local preview script `scripts/preview.sh` with realistic mock scenarios (`NUC_PULSE_MOCK=1`).
- **Process:** full (`safe-change` process: feature branch, automated tests, preview verification, explicit user go-ahead before merging).

## How to work here
Follow the shared `safe-change` skill for every change. For a public repo, never commit IPs, hostnames, account IDs, secrets or known weaknesses.

## Commands
- Lint: `.venv/bin/ruff check .`
- Test: `.venv/bin/pytest -v`
- Run local: `.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8520`

## Must never be edited
- Live secrets or non-redacted credentials.
