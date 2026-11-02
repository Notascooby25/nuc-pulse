import os
import re

import httpx

from src.sanitizer import sanitize_text

# Each app is matched by the labels Docker Compose puts on its containers (app + role),
# which survive recreation and renames. Cloudflare isn't run by Compose, so it's matched by name.
CORE_APP_DEFINITIONS = [
    {
        "id": "audio_scrobbler",
        "name": "Audio Scrobbler",
        "match": {"project": "audio-scrobbler-app", "service": "backend"},
        "port": 8010,
        "health_path": "/health",
        "expect_watchtower": True,
    },
    {
        "id": "expense_tracker",
        "name": "UK Expense Tracker",
        "match": {"project": "uk-expense-tracker", "service": "expense-tracker-web"},
        "port": 8502,
        "health_path": "/",
        "expect_watchtower": True,
    },
    {
        "id": "sleepwell",
        "name": "Sleep Wellness Tracker",
        "match": {"project": "sleep-wellness-tracker", "service": "frontend_web"},
        "port": 8510,
        "health_path": "/",
        "expect_watchtower": True,
    },
    {
        "id": "jellyfin",
        "name": "Jellyfin Server",
        "match": {"project": "jellyfin", "service": "jellyfin"},
        "port": 8096,
        "health_path": "/health",
        "expect_watchtower": False,
    },
    {
        "id": "cloudflared",
        "name": "Cloudflare Tunnel",
        "match": {"container_name": "cloudflared"},
        "port": None,
        "health_path": None,
        "expect_watchtower": False,
    },
]


def _describe_match(match: dict) -> str:
    if "container_name" in match:
        return f"container {match['container_name']}"
    return f"{match['project']} / {match['service']}"


def _find_app_container(match: dict, containers: list[dict]) -> tuple[dict | None, int]:
    """The container for an app (running ones first, then by name) and how many matched."""
    found = []
    for c in containers:
        name = (c.get("Names") or [""])[0].lstrip("/")
        labels = c.get("Labels") or {}
        if "container_name" in match:
            ok = name == match["container_name"]
        else:
            ok = (
                labels.get("com.docker.compose.project") == match["project"]
                and labels.get("com.docker.compose.service") == match["service"]
            )
        if ok:
            found.append((((c.get("State") or "").lower() != "running"), name, c))
    if not found:
        return None, 0
    found.sort(key=lambda item: item[:2])
    return found[0][2], len(found)


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
        covered = {name for w in watchtowers if w["running"] for name in w["watching"]}
        for app_def in app_definitions:
            raw, match_count = _find_app_container(app_def["match"], containers)
            port, path = app_def["port"], app_def["health_path"]
            notes = []

            if raw is None:
                all_healthy = False
                core_apps.append({
                    "id": app_def["id"],
                    "name": app_def["name"],
                    "healthy": False,
                    "status_text": f"Container not found (expected {_describe_match(app_def['match'])})",
                    "port": port,
                    "container_name": None,
                    "probe_target": None,
                    "notes": notes,
                })
                continue

            raw_name = (raw.get("Names") or [""])[0].lstrip("/")
            matched_c = next(p for p in parsed_containers if p["name"] == raw_name)
            if match_count > 1:
                notes.append(f"{match_count} containers match")
            if app_def["expect_watchtower"] and matched_c["name"] not in covered:
                notes.append(f"not auto-updated: no Watchtower is watching {matched_c['name']}")

            probe_target = None
            if port and path:
                probe_target = f":{port}{path}"
                probe_ok, probe_text = await _probe_health(probe_client, "127.0.0.1", port, path)
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
                "port": port,
                "container_name": matched_c["name"],
                "probe_target": probe_target,
                "notes": notes,
            })

    return {
        "docker_available": True,
        "all_healthy": all_healthy,
        "core_apps": core_apps,
        "watchtowers": watchtowers,
        "containers": parsed_containers,
    }
