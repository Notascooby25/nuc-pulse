"""Checks that healthy things aren't shown as red crosses (from the 2 November report)."""

import os
import struct
import time

import httpx
import pytest

from src.app_inspector import inspect_apps_and_containers
from src.backup_inspector import inspect_backups

SESSION_OK = (
    'time="2026-11-02T11:31:27Z" level=info msg="Session done" '
    "Failed=0 Scanned=3 Updated=0 notify=no\n"
)
SESSION_FAILED = (
    'time="2026-11-02T11:31:27Z" level=info msg="Session done" '
    "Failed=1 Scanned=3 Updated=0 notify=no\n"
)
SESSION_NOTHING_WATCHED = (
    'time="2026-11-02T11:36:24Z" level=info msg="Session done" '
    "Failed=0 Scanned=0 Updated=0 notify=no\n"
)
HEAD_WARNING = (
    'time="2026-11-02T11:21:25Z" level=warning msg="Could not do a head request for '
    '\\"ghcr.io/example/app:latest\\", falling back to regular pull." container=/app\n'
)
SHUTDOWN_WAIT = (
    'time="2026-11-02T11:10:28Z" level=info msg="Waiting for running update to be finished..."\n'
)


def _framed(text: str) -> bytes:
    """Docker's log format for containers without a terminal: an 8-byte header per line."""
    out = b""
    for line in text.splitlines(keepends=True):
        data = line.encode()
        out += struct.pack(">BxxxL", 2, len(data)) + data
    return out


WATCHTOWER = {
    "Id": "wt1",
    "Names": ["/some_watchtower"],
    "Image": "containrrr/watchtower:latest",
    "State": "running",
    "Status": "Up 1 hour",
    "Ports": [],
    "Labels": {},
}

WATCHED_APP = {
    "Id": "app1",
    "Names": ["/some_app"],
    "Image": "ghcr.io/example/app:latest",
    "State": "running",
    "Status": "Up 1 hour",
    "Ports": [],
    "Labels": {},
}


async def _watchtower_with_logs(body):
    def docker(request: httpx.Request):
        if "/containers/json" in str(request.url):
            return httpx.Response(200, json=[WATCHTOWER, WATCHED_APP])
        if "/logs" in str(request.url):
            return httpx.Response(200, content=body)
        return httpx.Response(404)

    res = await inspect_apps_and_containers(
        docker_socket="/dummy/socket",
        transport=httpx.MockTransport(docker),
        probe_transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        app_definitions=[],
    )
    return res, res["watchtowers"][0]


@pytest.mark.asyncio
async def test_normal_watchtower_sessions_are_healthy():
    res, wt = await _watchtower_with_logs(_framed(SHUTDOWN_WAIT + SESSION_OK * 5))
    assert wt["healthy"] is True
    assert res["all_healthy"] is True
    assert "error" not in wt["status_text"].lower()


@pytest.mark.asyncio
async def test_watchtower_warnings_are_a_note_not_a_cross():
    _, wt = await _watchtower_with_logs(_framed((HEAD_WARNING + SESSION_OK) * 3))
    assert wt["healthy"] is True
    assert "warning" in wt["status_text"].lower()


@pytest.mark.asyncio
async def test_failed_watchtower_session_is_a_cross():
    res, wt = await _watchtower_with_logs(_framed(SESSION_OK + SESSION_FAILED))
    assert wt["healthy"] is False
    assert res["all_healthy"] is False
    assert "error" in wt["status_text"].lower()


@pytest.mark.asyncio
async def test_watchtower_scanning_nothing_is_a_cross():
    res, wt = await _watchtower_with_logs(_framed(SESSION_NOTHING_WATCHED * 3))
    assert wt["healthy"] is False
    assert res["all_healthy"] is False
    assert "scanned 0" in wt["status_text"].lower()


@pytest.mark.asyncio
async def test_docker_log_headers_are_removed():
    _, wt = await _watchtower_with_logs(_framed(SESSION_OK * 2))
    assert wt["log_tail"].startswith('time="')
    assert "\x00" not in wt["log_tail"]
    assert "\x02" not in wt["log_tail"]


@pytest.mark.asyncio
async def test_plain_logs_from_a_terminal_container_still_read():
    _, wt = await _watchtower_with_logs(SESSION_OK.encode())
    assert wt["log_tail"] == SESSION_OK
    assert wt["healthy"] is True


@pytest.mark.asyncio
async def test_scrobbler_is_checked_at_its_health_address():
    backend = {
        "Id": "s1",
        "Names": ["/audio-scrobbler-app-backend-1"],
        "Image": "ghcr.io/example/audio-scrobbler-app-backend:latest",
        "State": "running",
        "Status": "Up 27 minutes (healthy)",
        "Ports": [{"PublicPort": 8010, "PrivatePort": 8000}],
        "Labels": {
            "com.docker.compose.project": "audio-scrobbler-app",
            "com.docker.compose.service": "backend",
        },
    }
    asked = []

    def docker(request: httpx.Request):
        if "/containers/json" in str(request.url):
            return httpx.Response(200, json=[backend])
        return httpx.Response(404)

    def probe(request: httpx.Request):
        asked.append((request.url.port, request.url.path))
        return httpx.Response(200 if request.url.path == "/health" else 404)

    res = await inspect_apps_and_containers(
        docker_socket="/dummy/socket",
        transport=httpx.MockTransport(docker),
        probe_transport=httpx.MockTransport(probe),
    )
    app = next(a for a in res["core_apps"] if "Scrobbler" in a["name"])
    assert (8010, "/health") in asked
    assert app["healthy"] is True


def _backup(folder, name, *, age_days, size=b"data"):
    path = folder / name
    path.write_bytes(size)
    stamp = time.time() - age_days * 86400
    os.utime(path, (stamp, stamp))


@pytest.mark.asyncio
async def test_one_off_backups_are_not_marked_stale(tmp_path):
    folder = tmp_path / "srv" / "app" / "backups"
    folder.mkdir(parents=True)
    _backup(folder, "manual-20260915-201039.sql.gz", age_days=48)
    _backup(folder, "pre_deploy_20260429_202400pgdata.tar.gz", age_days=187)
    _backup(folder, "pre_restore_20260429_195159.dump", age_days=187)

    res = await inspect_backups(srv_root=str(tmp_path / "srv"), now=time.time())
    pipes = {p["name"]: p for p in res["local_pipelines"]}
    for name in ("manual", "pre_deploy", "pre_restore"):
        assert pipes[name]["healthy"] is True, pipes[name]
        assert "one-off" in pipes[name]["status_text"].lower()


@pytest.mark.asyncio
async def test_empty_one_off_backup_is_still_a_cross(tmp_path):
    folder = tmp_path / "srv" / "app" / "backups"
    folder.mkdir(parents=True)
    _backup(folder, "manual-20261101-101010.sql.gz", age_days=1, size=b"")

    res = await inspect_backups(srv_root=str(tmp_path / "srv"), now=time.time())
    pipe = next(p for p in res["local_pipelines"] if p["name"] == "manual")
    assert pipe["healthy"] is False
    assert "empty" in pipe["status_text"].lower()


@pytest.mark.asyncio
async def test_new_scheduled_backups_are_still_checked_daily(tmp_path):
    folder = tmp_path / "srv" / "app" / "backups"
    folder.mkdir(parents=True)
    _backup(folder, "newjob_20261101T000000Z.dump", age_days=2)

    res = await inspect_backups(srv_root=str(tmp_path / "srv"), now=time.time())
    pipe = next(p for p in res["local_pipelines"] if p["name"] == "newjob")
    assert pipe["healthy"] is False
    assert "stale" in pipe["status_text"].lower()


def test_report_describes_one_off_backups_without_a_threshold():
    from src.mock_data import get_mock_scenario
    from src.report_builder import build_diagnostic_markdown

    state = get_mock_scenario("degraded")
    state["backups"]["local_pipelines"].append({
        "name": "manual", "healthy": False, "status_text": "Latest archive is empty (0 bytes)",
        "version_count": 1, "latest_file": "manual-20261101-101010.sql.gz",
        "latest_size_bytes": 0, "last_run": 0, "age_hours": 1.0, "threshold_hours": None,
    })
    md = build_diagnostic_markdown(state)
    assert "Noneh" not in md
    assert "one-off" in md
