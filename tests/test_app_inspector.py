import pytest
import httpx
from src.app_inspector import inspect_apps_and_containers

@pytest.mark.asyncio
async def test_inspect_apps_and_containers_with_mock_docker():
    # Mock Docker Engine response for /containers/json
    containers_payload = [
        {
            "Id": "c1",
            "Names": ["/audio_scrobbler_frontend"],
            "Image": "ghcr.io/notascooby25/audio-scrobbler-app-frontend:latest",
            "State": "running",
            "Status": "Up 2 days (healthy)",
            "Ports": [{"PublicPort": 5173, "PrivatePort": 5173, "IP": "0.0.0.0"}],
            "Labels": {"com.centurylinklabs.watchtower.scope": "audio-scrobbler-app"},
        },
        {
            "Id": "c2",
            "Names": ["/uk_expense_tracker_web"],
            "Image": "ghcr.io/notascooby25/uk-expense-tracker-web:latest",
            "State": "running",
            "Status": "Up 2 days",
            "Ports": [{"PublicPort": 8502, "PrivatePort": 8502, "IP": "0.0.0.0"}],
            "Labels": {"com.centurylinklabs.watchtower.scope": "expense_tracker"},
        },
        {
            "Id": "c3",
            "Names": ["/sleep_watchtower"],
            "Image": "containrrr/watchtower:latest",
            "State": "running",
            "Status": "Up 4 days",
            "Ports": [],
            "Labels": {},
            "Command": "sleep_backend sleep_frontend_web",
        },
        {
            "Id": "c4",
            "Names": ["/random_unrecognized_service"],
            "Image": "redis:alpine",
            "State": "running",
            "Status": "Up 1 day",
            "Ports": [{"PublicPort": 6379, "PrivatePort": 6379}],
            "Labels": {},
        },
    ]

    def mock_docker_handler(request: httpx.Request):
        url = str(request.url)
        if "/containers/json" in url:
            return httpx.Response(200, json=containers_payload)
        elif "/containers/c3/logs" in url:
            # Watchtower logs
            return httpx.Response(200, text="time=\"2026-11-02T08:00:00Z\" level=info msg=\"Session done\"\n")
        return httpx.Response(404)

    docker_transport = httpx.MockTransport(mock_docker_handler)

    def mock_probe_handler(request: httpx.Request):
        # Health probes
        return httpx.Response(200, text="OK")

    probe_transport = httpx.MockTransport(mock_probe_handler)

    res = await inspect_apps_and_containers(
        docker_socket="/dummy/socket",
        transport=docker_transport,
        probe_transport=probe_transport,
    )

    assert res["docker_available"] is True
    assert res["all_healthy"] is True

    # Core apps
    core_names = [a["name"] for a in res["core_apps"]]
    assert any("Scrobbler" in n for n in core_names)
    assert any("Expense" in n for n in core_names)

    # Watchtower fleet
    assert len(res["watchtowers"]) == 1
    wt = res["watchtowers"][0]
    assert wt["name"] == "sleep_watchtower"
    assert wt["healthy"] is True
    assert "sleep_backend sleep_frontend_web" in wt["scope"]

    # All containers
    assert len(res["containers"]) == 4
    assert any(c["name"] == "random_unrecognized_service" for c in res["containers"])

@pytest.mark.asyncio
async def test_inspect_apps_watchtower_error_detection():
    containers_payload = [
        {
            "Id": "c_wt_err",
            "Names": ["/watchtower_broken"],
            "Image": "containrrr/watchtower:latest",
            "State": "running",
            "Status": "Up 1 day",
            "Ports": [],
            "Labels": {},
        }
    ]

    def mock_docker_handler(request: httpx.Request):
        if "/containers/json" in str(request.url):
            return httpx.Response(200, json=containers_payload)
        elif "/logs" in str(request.url):
            return httpx.Response(200, text="time=\"2026-11-02T08:00:00Z\" level=error msg=\"Failed to pull image: unauthorized\"\n")
        return httpx.Response(404)

    docker_transport = httpx.MockTransport(mock_docker_handler)

    res = await inspect_apps_and_containers(
        docker_socket="/dummy/socket",
        transport=docker_transport,
        probe_transport=httpx.MockTransport(lambda r: httpx.Response(200)),
    )

    assert res["all_healthy"] is False
    wt = res["watchtowers"][0]
    assert wt["healthy"] is False
    assert "error" in wt["status_text"].lower()
