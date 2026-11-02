#!/usr/bin/env bash
set -euo pipefail

# scripts/install.sh — Installs and enables NUC Pulse as a systemd user service on the NUC

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="nuc-pulse.service"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

echo "=== Installing NUC Pulse on $(hostname) ==="
echo "Repository directory: $REPO_DIR"

# 1. Ensure Python venv
if [ ! -d "$REPO_DIR/.venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$REPO_DIR/.venv"
fi

echo "Installing dependencies..."
"$REPO_DIR/.venv/bin/pip" install -q -r "$REPO_DIR/requirements.txt"

# 2. Enable lingering for current user so systemd user services run at boot without active login
if command -v loginctl >/dev/null 2>&1; then
    echo "Enabling user lingering..."
    loginctl enable-linger "$USER" || true
fi

# 3. Install unit file with exact repository path substituted
mkdir -p "$SYSTEMD_USER_DIR"
sed "s|__REPO_DIR__|$REPO_DIR|g" "$REPO_DIR/scripts/$SERVICE_NAME" > "$SYSTEMD_USER_DIR/$SERVICE_NAME"

# 4. Reload, reset any previous failed state, and restart
systemctl --user daemon-reload
systemctl --user reset-failed "$SERVICE_NAME" 2>/dev/null || true
systemctl --user enable "$SERVICE_NAME"
systemctl --user restart "$SERVICE_NAME"

echo ""
echo "=== NUC Pulse installed and running! ==="
echo "Check status: systemctl --user status $SERVICE_NAME"
echo "View logs:    journalctl --user -u $SERVICE_NAME -f"
echo "Dashboard:    http://localhost:8520"
