#!/usr/bin/env bash
set -euo pipefail

# scripts/preview.sh — Local development preview runner with realistic mock data

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PID_FILE="$REPO_DIR/.preview.pid"
PORT="${NUC_PULSE_PREVIEW_PORT:-8520}"
UVICORN="$REPO_DIR/.venv/bin/uvicorn"

usage() {
    echo "Usage: $0 {up|down|status}"
    exit 1
}

# True if something is listening on the preview port
port_in_use() {
    (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null
}

# True if the PID is this folder's preview server (exact command match, not just a live PID)
is_preview_pid() {
    local cmd
    cmd="$(tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null)" || return 1
    [[ "$cmd" == *" $UVICORN src.main:app --host 127.0.0.1 --port $PORT " ]]
}

# PID recorded by `up`, if it is still this preview (a reused PID after a reboot doesn't count)
tracked_pid() {
    local pid
    [ -f "$PID_FILE" ] || return 0
    pid="$(cat "$PID_FILE")"
    if is_preview_pid "$pid"; then
        echo "$pid"
    fi
}

# A preview from this folder that the PID file has lost track of
leftover_pid() {
    local pid
    for pid in $(pgrep -f -- "src.main:app" || true); do
        if is_preview_pid "$pid"; then
            echo "$pid"
            return 0
        fi
    done
}

cmd="${1:-}"

case "$cmd" in
    up)
        PID="$(tracked_pid)"
        if [ -n "$PID" ]; then
            echo "Preview server is already running (PID: $PID) on http://localhost:$PORT"
            exit 0
        fi
        if port_in_use; then
            echo "Port $PORT is already in use, probably a leftover preview. Run '$0 down' first, then try again."
            exit 1
        fi

        echo "Starting NUC Pulse preview server on http://localhost:$PORT..."
        export NUC_PULSE_MOCK=1
        PYTHONPATH="$REPO_DIR" "$UVICORN" src.main:app --host 127.0.0.1 --port "$PORT" > "$REPO_DIR/.preview.log" 2>&1 &
        PID=$!

        # Only record the PID once the server is alive and answering
        for _ in $(seq 1 40); do
            if ! kill -0 "$PID" 2>/dev/null; then
                break
            fi
            if port_in_use; then
                echo "$PID" > "$PID_FILE"
                echo "Preview server started successfully!"
                echo "URL: http://localhost:$PORT"
                echo "Logs: $REPO_DIR/.preview.log"
                exit 0
            fi
            sleep 0.25
        done

        kill "$PID" 2>/dev/null || true
        rm -f "$PID_FILE"
        echo "Failed to start preview server. Check $REPO_DIR/.preview.log"
        exit 1
        ;;

    down)
        PID="$(tracked_pid)"
        [ -n "$PID" ] || PID="$(leftover_pid)"
        rm -f "$PID_FILE"
        if [ -n "$PID" ]; then
            echo "Stopping preview server (PID: $PID)..."
            kill "$PID" || true
            for _ in $(seq 1 20); do
                kill -0 "$PID" 2>/dev/null || break
                sleep 0.25
            done
            if kill -0 "$PID" 2>/dev/null; then
                echo "Preview server (PID: $PID) did not stop within 5 seconds."
                exit 1
            fi
            echo "Preview server stopped."
        elif port_in_use; then
            echo "No preview server is running, but port $PORT is in use by another program. Left it alone."
        else
            echo "No preview server is running."
        fi
        ;;

    status)
        PID="$(tracked_pid)"
        LEFTOVER="$(leftover_pid)"
        if [ -n "$PID" ]; then
            echo "Preview server is RUNNING (PID: $PID) on http://localhost:$PORT"
        elif [ -n "$LEFTOVER" ]; then
            echo "A leftover preview server is in use on port $PORT (PID: $LEFTOVER) but not tracked. Run '$0 down' to stop it."
        elif port_in_use; then
            echo "Preview server is not running, but port $PORT is in use by another program."
        else
            echo "Preview server is STOPPED"
        fi
        ;;

    *)
        usage
        ;;
esac
