# NUC Pulse 🖥️

A fast, lightweight, zero-configuration operational dashboard for Intel NUC servers. It provides a **2-second sanity check** confirming whether production apps, Watchtower auto-updaters, and backup pipelines are healthy via clear green ticks (✅) or red crosses (❌).

## Key Features

- **2-Second Sanity Check:** Instant visual confirmation of server and backup health.
- **Dynamic Extensibility:** Auto-detects newly deployed Docker containers, new backup folders, and systemd timers without code modifications.
- **Multi-Root Backup Verification:**
  - Tracks Sleepwell DB, Mood Images, Audio Scrobbler DB, UK Expense Tracker, and Host Config snapshots across `/srv/shared/backups` and `/srv/*/backups`.
  - Verifies non-zero file sizes (`> 0 bytes`) to prevent empty archives from showing false green ticks.
  - Parses `synology_backup_cron.log` and `google_backup_cron.log` for freshness and error status.
- **Watchtower Fleet Tracking:** Reports all running Watchtower instances, their scopes, and inspects recent logs for image pull or GHCR authentication errors.
- **Host Vitals & OS Updates:** Real-time CPU, RAM, Disk usage, pending security updates, and reboot-required flags without blocking the server.
- **Security by Design:** Automatically scrubs credentials, tokens, and healthcheck URLs from logs before rendering.

---

## Local Development & Preview

Test the dashboard locally with realistic mock data:

```bash
# Start local preview server (port 8520)
./scripts/preview.sh up

# Check status
./scripts/preview.sh status

# Stop preview server
./scripts/preview.sh down
```

Open your browser to [http://localhost:8520](http://localhost:8520). In preview mode, use the top bar buttons to toggle between **"All Nominal (Green Ticks)"** and **"Simulate Failure (Red Crosses)"** to see how errors are surfaced.

If `up` says the port is already in use, a leftover preview is probably still running: `./scripts/preview.sh down` stops it.

### Screenshots (optional, this PC only)

Takes PC and phone screenshots of the running preview, in both scenarios and with "What's new" open. It needs the dev-only Playwright tool, whose browser is kept inside `.venv`:

```bash
.venv/bin/pip install -e ".[dev]"
PLAYWRIGHT_BROWSERS_PATH=0 .venv/bin/playwright install chromium

# Save screenshots to a folder outside the project
.venv/bin/python scripts/screenshot.py /path/outside/the/project
```

---

## Production Deployment on the NUC

1. Clone or copy to `/srv/nuc-pulse`:
   ```bash
   cd /srv
   git clone https://github.com/notascooby25/nuc-pulse.git
   cd nuc-pulse
   ```

2. Run the installer:
   ```bash
   chmod +x scripts/*.sh
   ./scripts/install.sh
   ```

3. Access on your local network:
   ```text
   http://<NUC_IP>:8520
   ```
