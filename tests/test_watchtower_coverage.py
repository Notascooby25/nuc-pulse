"""Which containers each Watchtower actually looks after (from the 20 Oct sleepwell outage)."""

import json

import httpx
import pytest

from src.app_inspector import inspect_apps_and_containers

SCOPE = "com.centurylinklabs.watchtower.scope"
ENABLE = "com.centurylinklabs.watchtower.enable"
SESSION_OK = 'time="2026-11-02T19:30:45Z" level=info msg="Session done" Failed=0 Scanned=2 Updated=0\n'


def _container(name, *, labels=None, state="running", image="ghcr.io/example/app:latest"):
    return {
        "Id": f"id_{name}",
        "Names": [f"/{name}"],
        "Image": image,
        "State": state,
        "Status": "Up 1 hour" if state == "running" else "Exited (0) 1 hour ago",
        "Ports": [],
        "Labels": labels,
    }


def _watchtower(name="sleep_watchtower", *, labels=None, state="running"):
    return _container(name, labels=labels, state=state, image="containrrr/watchtower:latest")


async def _inspect(containers, *, inspect=None, inspect_status=200, logs_raise=False, inspect_raise=False):
    """inspect maps container name -> Config dict returned by /containers/{id}/json."""
    inspect = inspect or {}

    def docker(request: httpx.Request):
        path = request.url.path
        if path.endswith("/containers/json"):
            return httpx.Response(200, json=containers)
        if path.endswith("/logs"):
            if logs_raise:
                raise httpx.ReadTimeout("logs timed out", request=request)
            return httpx.Response(200, content=SESSION_OK.encode())
        if path.endswith("/json"):
            cid = path.split("/")[-2]
            name = cid.removeprefix("id_")
            if inspect_raise:
                raise httpx.ReadTimeout("inspect timed out", request=request)
            if inspect_status != 200:
                return httpx.Response(inspect_status)
            return httpx.Response(200, json={"Id": cid, "Config": inspect.get(name, {})})
        return httpx.Response(404)

    res = await inspect_apps_and_containers(
        docker_socket="/dummy/socket",
        transport=httpx.MockTransport(docker),
        probe_transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        app_definitions=[],
    )
    return res, {w["name"]: w for w in res["watchtowers"]}


@pytest.mark.asyncio
async def test_scope_from_label():
    label = {SCOPE: "sleep-wellness-tracker"}
    res, wts = await _inspect([
        _watchtower(labels=label),
        _container("sleep_backend", labels=label),
        _container("sleep_frontend_web", labels=label),
    ])
    wt = wts["sleep_watchtower"]
    assert wt["watching"] == ["sleep_backend", "sleep_frontend_web"]
    assert wt["healthy"] is True
    assert wt["running"] is True
    assert wt["scope"] == "sleep-wellness-tracker"
    assert "sleep_watchtower" not in wt["watching"]
    assert res["all_healthy"] is True


@pytest.mark.asyncio
async def test_scope_and_label_enable_from_env():
    env = [
        "WATCHTOWER_SCOPE=audio-scrobbler-app",
        "WATCHTOWER_LABEL_ENABLE=true",
        "WATCHTOWER_NOTIFICATION_URL=https://example.invalid/secret",
    ]
    res, wts = await _inspect(
        [
            _watchtower("scrobbler_wt"),
            _container("backend", labels={SCOPE: "audio-scrobbler-app", ENABLE: "true"}),
            _container("db", labels={SCOPE: "audio-scrobbler-app"}),
        ],
        inspect={"scrobbler_wt": {"Env": env, "Cmd": []}},
    )
    assert wts["scrobbler_wt"]["watching"] == ["backend"]
    assert wts["scrobbler_wt"]["scope"] == "audio-scrobbler-app"
    assert "secret" not in json.dumps(res)


@pytest.mark.asyncio
async def test_scope_and_label_enable_from_command():
    cmd = ["--label-enable", "--cleanup", "--interval", "300", "--scope", "expense_tracker",
           "--http-api-token", "abc123"]
    res, wts = await _inspect(
        [
            _watchtower("expense_wt"),
            _container("expense_web", labels={SCOPE: "expense_tracker", ENABLE: "true"}),
            _container("expense_other", labels={SCOPE: "expense_tracker"}),
        ],
        inspect={"expense_wt": {"Env": [], "Cmd": cmd}},
    )
    wt = wts["expense_wt"]
    assert wt["scope"] == "expense_tracker"
    assert wt["watching"] == ["expense_web"]
    assert "abc123" not in json.dumps(res)


@pytest.mark.asyncio
async def test_names_in_command_limit_watching():
    _, wts = await _inspect(
        [_watchtower(), _container("sleep_backend"), _container("sleep_frontend_web")],
        inspect={"sleep_watchtower": {"Env": [], "Cmd": ["--interval", "300", "sleep_backend"]}},
    )
    assert wts["sleep_watchtower"]["watching"] == ["sleep_backend"]


@pytest.mark.asyncio
async def test_enable_false_is_excluded():
    label = {SCOPE: "s"}
    _, wts = await _inspect([
        _watchtower(labels=label),
        _container("a", labels=label),
        _container("b", labels={SCOPE: "s", ENABLE: "false"}),
    ])
    assert wts["sleep_watchtower"]["watching"] == ["a"]


@pytest.mark.asyncio
async def test_stopped_containers_are_not_watched():
    label = {SCOPE: "s"}
    _, wts = await _inspect([
        _watchtower(labels=label),
        _container("a", labels=label),
        _container("b", labels=label, state="exited"),
    ])
    assert wts["sleep_watchtower"]["watching"] == ["a"]


@pytest.mark.asyncio
async def test_watching_nothing_is_a_cross_with_reason():
    res, wts = await _inspect([
        _watchtower(labels={SCOPE: "sleep-wellness-tracker"}),
        _container("sleep_backend"),
        _container("sleep_frontend_web"),
    ])
    wt = wts["sleep_watchtower"]
    assert wt["watching"] == []
    assert wt["healthy"] is False
    assert res["all_healthy"] is False
    assert "no running container carries the scope label" in wt["status_text"]
    assert "sleep-wellness-tracker" in wt["status_text"]


@pytest.mark.asyncio
async def test_no_scope_watches_everything():
    _, wts = await _inspect([
        _watchtower(),
        _container("plain"),
        _container("scoped", labels={SCOPE: "other"}),
    ])
    wt = wts["sleep_watchtower"]
    assert wt["watching"] == ["plain", "scoped"]
    assert wt["healthy"] is True
    assert "no scope set" in wt["status_text"]


@pytest.mark.asyncio
async def test_scope_none_watches_unscoped_only():
    _, wts = await _inspect(
        [_watchtower(), _container("plain"), _container("scoped", labels={SCOPE: "other"})],
        inspect={"sleep_watchtower": {"Env": ["WATCHTOWER_SCOPE=none"], "Cmd": []}},
    )
    assert wts["sleep_watchtower"]["watching"] == ["plain"]


@pytest.mark.asyncio
async def test_no_scope_watching_nothing_has_its_own_reason():
    _, wts = await _inspect([_watchtower()])
    wt = wts["sleep_watchtower"]
    assert wt["healthy"] is False
    assert "`none`" not in wt["status_text"]
    assert "no running container for it to update" in wt["status_text"]


@pytest.mark.asyncio
async def test_failed_log_read_still_reads_settings():
    env = {"Env": ["WATCHTOWER_SCOPE=expense_tracker"], "Cmd": []}
    _, wts = await _inspect(
        [_watchtower("expense_wt"), _container("web", labels={SCOPE: "expense_tracker"})],
        inspect={"expense_wt": env},
        logs_raise=True,
    )
    assert wts["expense_wt"]["scope"] == "expense_tracker"
    assert wts["expense_wt"]["watching"] == ["web"]


@pytest.mark.asyncio
async def test_settings_read_raising_falls_back_to_label():
    label = {SCOPE: "s"}
    _, wts = await _inspect([_watchtower(labels=label), _container("a", labels=label)], inspect_raise=True)
    assert wts["sleep_watchtower"]["watching"] == ["a"]
    assert wts["sleep_watchtower"]["healthy"] is True


@pytest.mark.asyncio
async def test_inspect_failure_falls_back_to_list_labels():
    label = {SCOPE: "s"}
    _, wts = await _inspect(
        [_watchtower(labels=label), _container("a", labels=label)], inspect_status=404
    )
    assert wts["sleep_watchtower"]["scope"] == "s"
    assert wts["sleep_watchtower"]["watching"] == ["a"]


@pytest.mark.asyncio
async def test_null_labels_are_handled():
    _, wts = await _inspect([_watchtower(labels=None), _container("a", labels=None)])
    assert wts["sleep_watchtower"]["watching"] == ["a"]
