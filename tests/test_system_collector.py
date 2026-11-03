import subprocess
from unittest.mock import patch

import pytest

from src.system_collector import collect_fast_vitals, collect_os_updates


@pytest.mark.asyncio
async def test_collect_fast_vitals(tmp_path):
    reboot_flag = tmp_path / "reboot-required"
    reboot_flag.write_text("*** System restart required ***")

    vitals = await collect_fast_vitals(disk_path=str(tmp_path), reboot_flag_path=str(reboot_flag))

    assert "hostname" in vitals
    assert len(vitals["hostname"]) > 0
    assert "os_name" in vitals
    assert len(vitals["os_name"]) > 0
    assert "uptime_text" in vitals
    assert vitals["uptime_text"].startswith("up ")
    assert "cpu_percent" in vitals
    assert "load_avg" in vitals
    assert "memory" in vitals
    assert vitals["memory"]["total_gb"] > 0
    assert "disk" in vitals
    assert vitals["disk"]["total_gb"] > 0
    assert vitals["reboot_required"] is True
    assert vitals["internet_ok"] in [True, False]
    assert vitals["tailscale_ok"] in [True, False]


@pytest.mark.asyncio
async def test_collect_os_updates_ubuntu_style(tmp_path):
    update_file = tmp_path / "updates-available"
    update_file.write_text("14 updates can be applied immediately.\n4 of these updates are standard security updates.\n")

    res = await collect_os_updates(updates_file=str(update_file))
    assert res["total_updates"] == 14
    assert res["security_updates"] == 4
    assert res["healthy"] is False
    assert "4 security" in res["summary"]


@pytest.mark.asyncio
async def test_collect_os_updates_all_clean(tmp_path):
    update_file = tmp_path / "updates-available"
    update_file.write_text("0 updates can be applied immediately.\n0 of these updates are standard security updates.\n")

    res = await collect_os_updates(updates_file=str(update_file))
    assert res["total_updates"] == 0
    assert res["security_updates"] == 0
    assert res["healthy"] is True
    assert "All updates installed" in res["summary"]


@pytest.mark.asyncio
async def test_collect_os_updates_fedora_dnf(tmp_path):
    missing_file = tmp_path / "no-such-file"
    fake_sec_json = (
        '{"upgrades": ['
        '{"name": "kernel", "arch": "x86_64", "evr": "6.11.5-300.fc44", "repository": "updates"}'
        ']}'
    )
    fake_all_json = (
        '{"upgrades": ['
        '{"name": "kernel", "arch": "x86_64", "evr": "6.11.5-300.fc44", "repository": "updates"},'
        '{"name": "vim-minimal", "arch": "x86_64", "evr": "9.1.0-1.fc44", "repository": "updates"}'
        ']}'
    )

    def fake_run(cmd, **kwargs):
        assert "-C" in cmd or "--cacheonly" in cmd
        assert "check-update" in cmd
        if "--security" in cmd:
            return subprocess.CompletedProcess(cmd, 100, stdout=fake_sec_json, stderr="")
        return subprocess.CompletedProcess(cmd, 100, stdout=fake_all_json, stderr="")

    with patch("shutil.which", return_value="/usr/bin/dnf"), patch("subprocess.run", side_effect=fake_run):
        res = await collect_os_updates(updates_file=str(missing_file))
        assert res["security_updates"] == 1
        assert res["total_updates"] == 2
        assert res["healthy"] is False
        assert "1 security" in res["summary"]


@pytest.mark.asyncio
async def test_collect_os_updates_fedora_dnf_json_non_security(tmp_path):
    missing_file = tmp_path / "no-such-file"
    all_json = (
        '{"upgrades": ['
        '{"name": "docker-compose-plugin", "arch": "x86_64", "evr": "5.7.0-1.fc44", "repository": "docker-ce-stable"},'
        '{"name": "tailscale", "arch": "x86_64", "evr": "1.104.5-1", "repository": "tailscale"}'
        ']}'
    )
    sec_json = '{}'

    def fake_run(cmd, **kwargs):
        assert "-C" in cmd or "--cacheonly" in cmd
        assert "check-update" in cmd
        if "--security" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=sec_json, stderr="")
        return subprocess.CompletedProcess(cmd, 100, stdout=all_json, stderr="")

    with patch("shutil.which", return_value="/usr/bin/dnf"), patch("subprocess.run", side_effect=fake_run):
        res = await collect_os_updates(updates_file=str(missing_file))
        assert res["total_updates"] == 2
        assert res["security_updates"] == 0
        assert res["healthy"] is True
        assert res["summary"] == "2 updates pending (0 security)"


@pytest.mark.asyncio
async def test_collect_os_updates_fedora_dnf_text_fallback_ignores_headers(tmp_path):
    missing_file = tmp_path / "no-such-file"
    all_text = (
        "Upgrades (available for reinstall, available for upgrade)\n"
        "docker-compose-plugin.x86_64  5.7.0-1.fc44  docker-ce-stable\n"
        "tailscale.x86_64  1.104.5-1  tailscale\n"
    )
    sec_text = ""

    def fake_run(cmd, **kwargs):
        assert "-C" in cmd or "--cacheonly" in cmd
        assert "check-update" in cmd
        if "--security" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=sec_text, stderr="")
        return subprocess.CompletedProcess(cmd, 100, stdout=all_text, stderr="")

    with patch("shutil.which", return_value="/usr/bin/dnf"), patch("subprocess.run", side_effect=fake_run):
        res = await collect_os_updates(updates_file=str(missing_file))
        assert res["total_updates"] == 2
        assert res["security_updates"] == 0
        assert res["healthy"] is True
        assert res["summary"] == "2 updates pending (0 security)"


def test_service_template_substitutes_repo_dir(tmp_path):
    from pathlib import Path
    service_tpl = Path(__file__).resolve().parent.parent / "scripts" / "nuc-pulse.service"
    content = service_tpl.read_text()
    assert "__REPO_DIR__" in content
    rendered = content.replace("__REPO_DIR__", "/srv/nuc-pulse")
    assert "WorkingDirectory=/srv/nuc-pulse" in rendered
    assert "ExecStart=/srv/nuc-pulse/.venv/bin/uvicorn" in rendered
