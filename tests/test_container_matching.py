"""Core apps are matched by their Compose app and role, not by Docker's list order (2 Nov sleepwell 401)."""

import httpx
import pytest

from src.app_inspector import inspect_apps_and_containers

SCOPE = "com.centurylinklabs.watchtower.scope"
ENABLE = "com.centurylinklabs.watchtower.enable"
SESSION_OK = 'time="2026-11-02T19:30:45Z" level=info msg="Session done" Failed=0 Scanned=2 Updated=0\n'


def _c(name, project=None, service=None, *, scope=None, enable=None, state="running",
       image="ghcr.io/example/app:latest"):
    labels = {}
    if project:
        labels["com.docker.compose.project"] = project
        labels["com.docker.compose.service"] = service
    if scope:
        labels[SCOPE] = scope
    if enable:
        labels[ENABLE] = enable
    return {
        "Id": f"id_{name}",
        "Names": [f"/{name}"],
        "Image": image,
        "State": state,
        "Status": "Up 47 minutes" if state == "running" else "Exited (0) 1 hour ago",
        "Ports": [],
        "Labels": labels,
    }


WT_IMAGE = "containrrr/watchtower:latest"
SLEEP, EXPENSE, SCROB = "sleep-wellness-tracker", "uk-expense-tracker", "audio-scrobbler-app"

# The NUC as reported on 2 Nov, with sleep_backend listed before sleep_frontend_web.
NUC_CONTAINERS = [
    _c("sleep_backend", SLEEP, "backend", scope=SLEEP),
    _c("sleep_frontend_web", SLEEP, "frontend_web", scope=SLEEP),
    _c("sleep_watchtower", SLEEP, "watchtower", scope=SLEEP, image=WT_IMAGE),
    _c("uk_expense_tracker_web", EXPENSE, "expense-tracker-web", scope="expense_tracker", enable="true"),
    _c("e24ad8b74e3c_uk_expense_tracker", EXPENSE, "expense-tracker", scope="expense_tracker", enable="true"),
    _c("audio-scrobbler-app-backend-1", SCROB, "backend", scope=SCROB, enable="true"),
    _c("audio-scrobbler-app-worker-1", SCROB, "worker", scope=SCROB, enable="true"),
    _c("audio-scrobbler-app-frontend-1", SCROB, "frontend", scope=SCROB, enable="true"),
    _c("audio-scrobbler-app-db-1", SCROB, "db"),
    _c("audio-scrobbler-app-watchtower-1", SCROB, "watchtower", image=WT_IMAGE),
    _c("cloudflared", image="cloudflare/cloudflared:latest"),
    _c("watchtower_expense_tracker", EXPENSE, "watchtower", image=WT_IMAGE),
    _c("jellyfin", "jellyfin", "jellyfin"),
    _c("sleep_db", SLEEP, "db"),
]

NUC_INSPECT = {
    "watchtower_expense_tracker": {
        "Env": ["WATCHTOWER_SCOPE=expense_tracker"],
        "Cmd": ["--label-enable", "--cleanup", "--interval", "300", "--scope", "expense_tracker"],
    },
    "audio-scrobbler-app-watchtower-1": {
        "Env": ["WATCHTOWER_SCOPE=audio-scrobbler-app", "WATCHTOWER_LABEL_ENABLE=true"],
        "Cmd": [],
    },
}


async def _inspect(containers):
    probed = []

    def docker(request: httpx.Request):
        path = request.url.path
        if path.endswith("/containers/json"):
            return httpx.Response(200, json=list(containers))
        if path.endswith("/logs"):
            return httpx.Response(200, content=SESSION_OK.encode())
        if path.endswith("/json"):
            name = path.split("/")[-2].removeprefix("id_")
            return httpx.Response(200, json={"Config": NUC_INSPECT.get(name, {"Env": [], "Cmd": []})})
        return httpx.Response(404)

    def probe(request: httpx.Request):
        probed.append((request.url.port, request.url.path))
        # The sleepwell backend needs a login, so a wrong match shows up as a 401.
        return httpx.Response(401 if request.url.port == 8000 else 200)

    res = await inspect_apps_and_containers(
        docker_socket="/dummy/socket",
        transport=httpx.MockTransport(docker),
        probe_transport=httpx.MockTransport(probe),
    )
    return res, {a["id"]: a for a in res["core_apps"]}, probed


@pytest.mark.asyncio
async def test_sleepwell_probes_frontend_not_backend():
    _, apps, probed = await _inspect(NUC_CONTAINERS)
    assert (8510, "/") in probed
    assert 8000 not in [port for port, _ in probed]
    assert apps["sleepwell"]["healthy"] is True
    assert apps["sleepwell"]["container_name"] == "sleep_frontend_web"
    assert apps["sleepwell"]["probe_target"] == ":8510/"
    assert apps["audio_scrobbler"]["container_name"] == "audio-scrobbler-app-backend-1"
    assert (8010, "/health") in probed


@pytest.mark.asyncio
async def test_order_does_not_change_matches():
    _, forward, _ = await _inspect(NUC_CONTAINERS)
    _, backward, _ = await _inspect(list(reversed(NUC_CONTAINERS)))
    assert {k: a["container_name"] for k, a in forward.items()} == {
        k: a["container_name"] for k, a in backward.items()
    }


@pytest.mark.asyncio
async def test_missing_container_is_a_cross_not_a_gap():
    containers = [c for c in NUC_CONTAINERS if c["Names"][0] != "/sleep_frontend_web"]
    res, apps, _ = await _inspect(containers)
    assert apps["sleepwell"]["healthy"] is False
    assert apps["sleepwell"]["status_text"] == (
        "Container not found (expected sleep-wellness-tracker / frontend_web)"
    )
    assert res["all_healthy"] is False


@pytest.mark.asyncio
async def test_running_copy_preferred_and_noted():
    old = _c("sleep_frontend_web_old", SLEEP, "frontend_web", scope=SLEEP, state="exited")
    _, apps, _ = await _inspect([old] + NUC_CONTAINERS)
    assert apps["sleepwell"]["container_name"] == "sleep_frontend_web"
    assert "2 containers match" in apps["sleepwell"]["notes"]


@pytest.mark.asyncio
async def test_uncovered_owner_app_gets_note():
    containers = [
        _c("sleep_backend", SLEEP, "backend"),
        _c("sleep_frontend_web", SLEEP, "frontend_web"),
    ] + [c for c in NUC_CONTAINERS if not c["Names"][0].startswith(("/sleep_backend", "/sleep_frontend"))]
    _, apps, _ = await _inspect(containers)
    assert apps["sleepwell"]["healthy"] is True
    assert "not auto-updated: no Watchtower is watching sleep_frontend_web" in apps["sleepwell"]["notes"]


@pytest.mark.asyncio
async def test_stopped_watchtower_covers_nothing():
    containers = [
        _c("sleep_watchtower", SLEEP, "watchtower", scope=SLEEP, image=WT_IMAGE, state="exited")
        if c["Names"][0] == "/sleep_watchtower" else c
        for c in NUC_CONTAINERS
    ]
    _, apps, _ = await _inspect(containers)
    assert any("not auto-updated" in n for n in apps["sleepwell"]["notes"])


@pytest.mark.asyncio
async def test_jellyfin_and_cloudflared_never_get_coverage_note():
    _, apps, _ = await _inspect(NUC_CONTAINERS)
    assert apps["jellyfin"]["notes"] == []
    assert apps["cloudflared"]["notes"] == []
    assert apps["cloudflared"]["probe_target"] is None


@pytest.mark.asyncio
async def test_real_layout_is_all_green():
    res, apps, _ = await _inspect(NUC_CONTAINERS)
    assert res["all_healthy"] is True
    assert all(a["healthy"] and a["notes"] == [] for a in apps.values())
    assert {w["name"]: len(w["watching"]) for w in res["watchtowers"]} == {
        "sleep_watchtower": 2,
        "watchtower_expense_tracker": 2,
        "audio-scrobbler-app-watchtower-1": 3,
    }
