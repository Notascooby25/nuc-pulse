import os
import time
import pytest
from src.backup_inspector import inspect_backups

@pytest.mark.asyncio
async def test_inspect_backups_multi_root_nominal(tmp_path):
    srv_dir = tmp_path / "srv"
    shared_backups = srv_dir / "shared" / "backups"
    mood_dir = shared_backups / "mood-images"
    host_config_dir = shared_backups / "host-config"
    scrobbler_backups = srv_dir / "audio-scrobbler-app" / "backups"

    for d in [shared_backups, mood_dir, host_config_dir, scrobbler_backups]:
        d.mkdir(parents=True, exist_ok=True)

    now = time.time()

    # Sleepwell DB
    f1 = shared_backups / "sleepdb_20261102T060000Z.dump"
    f1.write_bytes(b"dummy dump content")
    os.utime(f1, (now - 3600, now - 3600))  # 1 hour ago

    # Mood images
    f2 = mood_dir / "mood_images_20261102T060000Z.tar.gz"
    f2.write_bytes(b"dummy tar")
    os.utime(f2, (now - 7200, now - 7200))  # 2 hours ago

    # Expense Tracker
    f3 = shared_backups / "expense_tracker_data_20261102T030000Z.tar.gz"
    f3.write_bytes(b"dummy expense")
    os.utime(f3, (now - 14400, now - 14400))  # 4 hours ago

    # Scrobbler DB
    f4 = scrobbler_backups / "scrobbler-20261102T060000Z.dump"
    f4.write_bytes(b"dummy scrobbler")
    os.utime(f4, (now - 3600, now - 3600))  # 1 hour ago

    # Synology Cron Log
    syno_log = shared_backups / "synology_backup_cron.log"
    syno_log.write_text("[2026-11-02T06:30:00Z] push_srv_to_synology: Completed with 0 errors\n")
    os.utime(syno_log, (now - 3600, now - 3600))

    # Google Cron Log
    google_log = shared_backups / "google_backup_cron.log"
    google_log.write_text("[2026-11-02T04:10:00Z] sync_backups_to_google: OK: newest archives verified\n")
    os.utime(google_log, (now - 7200, now - 7200))

    res = await inspect_backups(srv_root=str(srv_dir), now=now)

    assert res["all_healthy"] is True
    assert len(res["offsite"]) == 2
    assert any(x["name"] == "Synology NAS Mirror" and x["healthy"] for x in res["offsite"])
    assert any(x["name"] == "Google Drive Sync" and x["healthy"] for x in res["offsite"])
    
    # Check pipelines
    pipeline_names = [p["name"] for p in res["local_pipelines"]]
    assert "sleepdb" in pipeline_names
    assert "mood_images" in pipeline_names
    assert "expense_tracker_data" in pipeline_names
    assert "scrobbler" in pipeline_names

@pytest.mark.asyncio
async def test_inspect_backups_catches_zero_byte_archive(tmp_path):
    srv_dir = tmp_path / "srv"
    shared_backups = srv_dir / "shared" / "backups"
    shared_backups.mkdir(parents=True, exist_ok=True)

    now = time.time()
    # 0 byte file
    f_empty = shared_backups / "sleepdb_20261102T060000Z.dump"
    f_empty.write_bytes(b"")
    os.utime(f_empty, (now - 1800, now - 1800))

    res = await inspect_backups(srv_root=str(srv_dir), now=now)
    sleep_pipe = next((p for p in res["local_pipelines"] if p["name"] == "sleepdb"), None)
    assert sleep_pipe is not None
    assert sleep_pipe["healthy"] is False
    assert "empty" in sleep_pipe["status_text"].lower()

@pytest.mark.asyncio
async def test_inspect_backups_catches_stale_archive(tmp_path):
    srv_dir = tmp_path / "srv"
    shared_backups = srv_dir / "shared" / "backups"
    shared_backups.mkdir(parents=True, exist_ok=True)

    now = time.time()
    # 20 hours old (threshold is 14h for 12h rotation)
    f_stale = shared_backups / "sleepdb_20261101T000000Z.dump"
    f_stale.write_bytes(b"valid content")
    os.utime(f_stale, (now - 20 * 3600, now - 20 * 3600))

    res = await inspect_backups(srv_root=str(srv_dir), now=now)
    sleep_pipe = next((p for p in res["local_pipelines"] if p["name"] == "sleepdb"), None)
    assert sleep_pipe is not None
    assert sleep_pipe["healthy"] is False
    assert "stale" in sleep_pipe["status_text"].lower()
