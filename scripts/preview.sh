#!/usr/bin/env bash
set -euo pipefail

# scripts/preview.sh — Local development preview runner with realistic mock data

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PID_FILE="$REPO_DIR/.preview.pid"
PORT=8520

usage() {
    echo "Usage: $0 {up|down|status}"
    exit 1
}

cmd="${1:-}"

case "$cmd" in
    up)
        if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "Preview server is already running (PID: $(cat "$PID_FILE")) on http://localhost:$PORT"
            exit 0
        fi

        echo "Starting NUC Pulse preview server on http://localhost:$PORT..."
        export NUC_PULSE_MOCK=1
        PYTHONPATH="$REPO_DIR" "$REPO_DIR/.venv/bin/uvicorn" src.main:app --host 127.0.0.1 --port "$PORT" > "$REPO_DIR/.preview.log" 2>&1 &
        echo $! > "$PID_FILE"
        sleep 1

        if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "Preview server started successfully!"
            echo "URL: http://localhost:$PORT"
            echo "Logs: $REPO_DIR/.preview.log"
        else
            echo "Failed to start preview server. Check $REPO_DIR/.preview.log"
            exit 1
        fi
        ;;

    down)
        if [ -f "$PID_FILE" ]; then
            PID="$(cat "$PID_FILE")"
            if kill -0 "$PID" 2>/dev/null; then
                echo "Stopping preview server (PID: $PID)..."
                kill "$PID" || true
            fi
            rm -f "$PID_FILE"
            echo "Preview server stopped."
        else
            echo "No preview server is running."
        fi
        ;;

    status)
        if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "Preview server is RUNNING (PID: $(cat "$PID_FILE")) on http://localhost:$PORT"
        else
            echo "Preview server is STOPPED"
        fi
        ;;

    *)
        usage
        ;;
esac
