import os
import re

import httpx

from src.sanitizer import sanitize_text

CORE_APP_DEFINITIONS = [
    {
        "id": "audio_scrobbler",
        "name": "Audio Scrobbler",
        "keywords": ["scrobbler", "audio-scrobbler"],
        "default_port": 5173,
        "health_path": "/health",
    },
    {
        "id": "expense_tracker",
        "name": "UK Expense Tracker",
        "keywords": ["expense_tracker", "uk-expense-tracker"],
        "default_port": 8502,
        "health_path": "/",
    },
    {
        "id": "sleepwell",
        "name": "Sleep Wellness Tracker",
        "keywords": ["sleep", "sleepwell"],
        "default_port": 8510,
        "health_path": "/",
    },
    {
        "id": "jellyfin",
        "name": "Jellyfin Server",
        "keywords": ["jellyfin"],
        "default_port": 8096,
        "health_path": "/health",
    },
    {
        "id": "cloudflared",
        "name": "Cloudflare Tunnel",
        "keywords": ["cloudflared", "nuc-tunnel"],
        "default_port": None,
        "health_path": None,
    },
]


RE_SESSION = re.compile(r"Failed=(\d+)\s+Scanned=(\d+)")

SCOPE_LABEL = "com.centurylinklabs.watchtower.scope"
ENABLE_LABEL = "com.centurylinklabs.watchtower.enable"

# Watchtower flags that take no value; any other flag without "=" takes the next token.
WATCHTOWER_BOOL_FLAGS = {
    "--cleanup", "--label-enable", "--debug", "--trace", "--run-once", "--monitor-only",
    "--rolling-restart", "--include-stopped", "--include-restarting", "--revive-stopped",
    "--no-pull", "--no-restart", "--no-startup-message", "--remove-volumes",
    "--http-api-update", "--http-api-metrics", "--enable-lifecycle-hooks",
    "--label-take-precedence",
}


def _watchtower_settings(list_labels: dict, inspect_json: dict | None) -> dict:
    """Scope, label-enable and named containers. Reads only non-secret settings."""
    config = (inspect_json or {}).get("Config") or {}
    env = {}
    for item in config.get("Env") or []:
        key, _, value = item.partition("=")
        if key in ("WATCHTOWER_SCOPE", "WATCHTOWER_LABEL_ENABLE"):
            env[key] = value

    cmd = config.get("Cmd") or []
    cmd_scope = None
    label_enable_flag = False
    names = []
    i = 0
    while i < len(cmd):
        token = cmd[i]
        if token.startswith("-"):
            flag, has_value, value = token.partition("=")
            if flag == "--label-enable":
                label_enable_flag = True
            elif flag == "--scope":
                if has_value:
                    cmd_scope = value
                elif i + 1 < len(cmd):
                    cmd_scope = cmd[i + 1]
            if not has_value and flag not in WATCHTOWER_BOOL_FLAGS:
                i += 1
        else:
            names.append(token)
        i += 1

    scope = list_labels.get(SCOPE_LABEL) or env.get("WATCHTOWER_SCOPE") or cmd_scope or None
    label_enable = label_enable_flag or env.get("WATCHTOWER_LABEL_ENABLE", "").lower() in ("true", "1")
    return {"scope": scope, "label_enable": label_enable, "names": names}


def _watched_containers(settings: dict, self_name: str, containers: list[dict]) -> list[str]:
    """Names of the running containers this Watchtower would update, sorted."""
    watched = []
    for c in containers:
        raw_names = c.get("Names") or [""]
        name = raw_names[0].lstrip("/")
        labels = c.get("Labels") or {}
        if name == self_name or (c.get("State") or "").lower() != "running":
            continue
        enable = (labels.get(ENABLE_LABEL) or "").lower()
        if enable == "false":
            continue
        if settings["label_enable"] and enable != "true":
            continue
        if (labels.get(SCOPE_LABEL) or None) != settings["scope"]:
            continue
        if settings["names"] and name not in settings["names"]:
            continue
        watched.append(name)
    return sorted(watched)


def _decode_docker_logs(raw: bytes) -> str:
    """Strip the 8-byte header Docker puts before each line for containers without a terminal."""
    if len(raw) < 8 or raw[0] not in (0, 1, 2) or raw[1:4] != b"\x00\x00\x00":
        return raw.decode("utf-8", errors="replace")
    out = bytearray()
    pos = 0
    while pos + 8 <= len(raw):
        size = int.from_bytes(raw[pos + 4 : pos + 8], "big")
        out += raw[pos + 8 : pos + 8 + size]
        pos += 8 + size
    return out.decode("utf-8", errors="replace")


def _assess_watchtower_logs(log_text: str) -> tuple[bool, list[str]]:
    """Return (has_error, notes) from Watchtower's log lines."""
    lower = log_text.lower()
    has_error = "level=error" in lower or "level=fatal" in lower
    sessions = RE_SESSION.findall(log_text)
    if any(int(failed) > 0 for failed, _ in sessions):
        has_error = True
    notes = []
    if "level=warning" in lower:
        notes.append("warnings in logs")
    return has_error, notes


def _last_scan_was_empty(log_text: str) -> bool:
    sessions = RE_SESSION.findall(log_text)
    return bool(sessions) and int(sessions[-1][1]) == 0


async def _probe_health(
    client: httpx.AsyncClient, host: str, port: int, path: str
) -> tuple[bool, str]:
    url = f"http://{host}:{port}{path}"
    try:
        resp = await client.get(url, timeout=3.0)
        if resp.status_code < 400:
            return True, f"HTTP {resp.status_code} OK"
        return False, f"HTTP {resp.status_code} Error"
    except Exception as e:
        return False, f"Offline ({type(e).__name__})"


async def inspect_apps_and_containers(
    docker_socket: str = "/var/run/docker.sock",
    transport: httpx.AsyncBaseTransport | None = None,
    probe_transport: httpx.AsyncBaseTransport | None = None,
    app_definitions: list[dict] | None = None,
) -> dict:
    """Inspect Docker containers, evaluate Core Apps, Watchtowers, and extra services."""
    if app_definitions is None:
        app_definitions = CORE_APP_DEFINITIONS
    client_kwargs = {}
    if transport is not None:
        client_kwargs["transport"] = transport
    elif os.path.exists(docker_socket):
        client_kwargs["transport"] = httpx.AsyncHTTPTransport(uds=docker_socket)
    else:
        # Docker not available or socket missing
        return {
            "docker_available": False,
            "all_healthy": True,
            "core_apps": [],
            "watchtowers": [],
            "containers": [],
            "error": "Docker socket not available",
        }

    containers = []
    try:
        async with httpx.AsyncClient(base_url="http://docker", **client_kwargs) as client:
            resp = await client.get("/containers/json?all=1", timeout=5.0)
            if resp.status_code == 200:
                containers = resp.json()
            else:
                return {
                    "docker_available": False,
                    "all_healthy": False,
                    "core_apps": [],
                    "watchtowers": [],
                    "containers": [],
                    "error": f"Docker API returned status {resp.status_code}",
                }
    except Exception as e:
        return {
            "docker_available": False,
            "all_healthy": False,
            "core_apps": [],
            "watchtowers": [],
            "containers": [],
            "error": f"Docker connection failed: {e}",
        }

    probe_kwargs = {"transport": probe_transport} if probe_transport else {}
    all_healthy = True

    # 1. Parse all containers
    parsed_containers = []
    watchtowers = []
    core_apps = []

    async with httpx.AsyncClient(**probe_kwargs) as probe_client:
        for c in containers:
            c_id = c.get("Id", "")[:12]
            raw_names = c.get("Names", [""])
            clean_name = raw_names[0].lstrip("/") if raw_names else "unknown"
            image = c.get("Image", "")
            state = c.get("State", "").lower()
            status = c.get("Status", "")
            labels = c.get("Labels", {}) or {}
            ports = c.get("Ports", []) or []

            # Determine public ports
            public_ports = [
                p["PublicPort"] for p in ports if isinstance(p, dict) and "PublicPort" in p
            ]

            is_running = state == "running"
            is_healthy = is_running and ("unhealthy" not in status.lower())
            if not is_healthy:
                all_healthy = False

            container_entry = {
                "id": c_id,
                "name": clean_name,
                "image": image,
                "state": state,
                "status": status,
                "healthy": is_healthy,
                "ports": public_ports,
            }
            parsed_containers.append(container_entry)

            # Check if Watchtower
            if "watchtower" in image.lower() or "watchtower" in clean_name.lower():
                # Check recent logs and settings
                wt_log_tail = ""
                has_wt_error = False
                wt_notes = []
                inspect_json = None
                try:
                    async with httpx.AsyncClient(base_url="http://docker", **client_kwargs) as docker_client:
                        log_resp = await docker_client.get(
                            f"/containers/{c.get('Id')}/logs?stdout=1&stderr=1&tail=20",
                            timeout=3.0,
                        )
                        if log_resp.status_code == 200:
                            wt_log_tail = sanitize_text(_decode_docker_logs(log_resp.content))
                            has_wt_error, wt_notes = _assess_watchtower_logs(wt_log_tail)
                        inspect_resp = await docker_client.get(f"/containers/{c.get('Id')}/json", timeout=3.0)
                        if inspect_resp.status_code == 200:
                            inspect_json = inspect_resp.json()
                except Exception:
                    pass

                settings = _watchtower_settings(labels, inspect_json)
                watching = _watched_containers(settings, clean_name, containers)
                scope = settings["scope"]

                problems = []
                if has_wt_error:
                    problems.append("Errors reported in logs")
                if not watching:
                    problems.append(
                        "Watching no containers — no running container carries the scope label "
                        f"`{scope or 'none'}`{' with enable=true' if settings['label_enable'] else ''}"
                        ", so nothing will be updated"
                    )
                elif _last_scan_was_empty(wt_log_tail):
                    problems.append("Last check scanned 0 containers, so nothing will be updated")
                if scope is None:
                    wt_notes.append("no scope set: watches all unscoped containers")

                wt_healthy = is_running and not problems
                if not wt_healthy:
                    all_healthy = False

                watchtowers.append({
                    "id": c_id,
                    "name": clean_name,
                    "healthy": wt_healthy,
                    "running": is_running,
                    "scope": scope or "none (watches all unscoped)",
                    "watching": watching,
                    "status_text": "; ".join(problems)
                    if problems
                    else status + (f" ({', '.join(wt_notes)})" if wt_notes else ""),
                    "log_tail": wt_log_tail,
                })

        # Match Core Apps
        for app_def in app_definitions:
            # Find matching container
            matched_c = None
            for c in parsed_containers:
                for kw in app_def["keywords"]:
                    if kw in c["name"].lower() or kw in c["image"].lower():
                        matched_c = c
                        break
                if matched_c:
                    break

            if matched_c:
                target_port = matched_c["ports"][0] if matched_c["ports"] else app_def["default_port"]
                if target_port and app_def["health_path"]:
                    probe_ok, probe_text = await _probe_health(
                        probe_client, "127.0.0.1", target_port, app_def["health_path"]
                    )
                    healthy = matched_c["healthy"] and probe_ok
                    status_text = probe_text if probe_ok else f"{matched_c['status']} - {probe_text}"
                else:
                    healthy = matched_c["healthy"]
                    status_text = matched_c["status"]

                if not healthy:
                    all_healthy = False

                core_apps.append({
                    "id": app_def["id"],
                    "name": app_def["name"],
                    "healthy": healthy,
                    "status_text": status_text,
                    "port": target_port,
                    "container_name": matched_c["name"],
                })

    return {
        "docker_available": True,
        "all_healthy": all_healthy,
        "core_apps": core_apps,
        "watchtowers": watchtowers,
        "containers": parsed_containers,
    }
