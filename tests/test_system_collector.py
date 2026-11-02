
import pytest

from src.system_collector import collect_fast_vitals, collect_os_updates


@pytest.mark.asyncio
async def test_collect_fast_vitals(tmp_path):
    reboot_flag = tmp_path / "reboot-required"
    reboot_flag.write_text("*** System restart required ***")

    vitals = await collect_fast_vitals(disk_path=str(tmp_path), reboot_flag_path=str(reboot_flag))

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
    assert res["healthy"] is False  # Pending security updates flag a warning
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
