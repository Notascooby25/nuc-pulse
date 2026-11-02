#!/usr/bin/env bash
set -euo pipefail

# scripts/autoupdate.sh — Automated background updater for NUC Pulse
# Checks origin/main, pulls new commits, updates dependencies if requirements.txt changed,
# and gracefully restarts nuc-pulse.service.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

CHECK_ONLY=0
if [ "${1:-}" = "--check" ]; then
    CHECK_ONLY=1
fi

echo "=== NUC Pulse Auto-Updater ==="
echo "Repository: $REPO_DIR"
echo "Timestamp:  $(date -u '+%Y-%m-%d %H:%M:%S UTC')"

# Verify git repository
if [ ! -d ".git" ]; then
    echo "Error: $REPO_DIR is not a git repository."
    exit 1
fi

# Check for uncommitted work
if [ -n "$(git status --porcelain)" ]; then
    echo "Warning: Uncommitted changes detected in $REPO_DIR; skipping auto-update to avoid conflicts."
    exit 0
fi

# Ensure we are on main
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" != "main" ] && [ $CHECK_ONLY -eq 0 ]; then
    echo "Notice: Repository is on branch '$CURRENT_BRANCH' (not 'main'); skipping auto-update."
    exit 0
fi

# Fetch remote changes with safe timeout/offline handling
echo "Checking remote origin/main..."
if ! git fetch origin main --quiet 2>/dev/null; then
    echo "Notice: git fetch origin main failed (network offline or GitHub unreachable); exiting safely."
    exit 0
fi

LOCAL_HASH="$(git rev-parse HEAD)"
REMOTE_HASH="$(git rev-parse origin/main)"

if [ "$LOCAL_HASH" = "$REMOTE_HASH" ]; then
    echo "NUC Pulse Auto-Updater: Already up-to-date (${LOCAL_HASH:0:7})."
    exit 0
fi

echo "New version available: ${LOCAL_HASH:0:7} -> ${REMOTE_HASH:0:7}"

if [ $CHECK_ONLY -eq 1 ]; then
    echo "Check mode: updates are available."
    exit 0
fi

# Check if requirements.txt changed between commits
REQ_CHANGED="$(git diff --name-only "$LOCAL_HASH" "$REMOTE_HASH" -- requirements.txt 2>/dev/null || true)"

# Pull changes
echo "Pulling latest changes from origin/main..."
git pull origin main --quiet

# Update dependencies if requirements.txt changed
if [ -n "$REQ_CHANGED" ] && [ -x "$REPO_DIR/.venv/bin/pip" ]; then
    echo "requirements.txt updated; reinstalling virtualenv dependencies..."
    "$REPO_DIR/.venv/bin/pip" install -r requirements.txt --quiet
fi

# Gracefully restart systemd user service
if command -v systemctl >/dev/null 2>&1; then
    if systemctl --user is-enabled nuc-pulse.service >/dev/null 2>&1 || systemctl --user is-active nuc-pulse.service >/dev/null 2>&1; then
        echo "Restarting nuc-pulse.service..."
        systemctl --user restart nuc-pulse.service
        echo "nuc-pulse.service successfully restarted at commit ${REMOTE_HASH:0:7}."
    else
        echo "Notice: nuc-pulse.service is not active/enabled; update applied without restarting."
    fi
else
    echo "Notice: systemctl not available; update pulled successfully."
fi

echo "NUC Pulse Auto-Updater: Completed successfully."
