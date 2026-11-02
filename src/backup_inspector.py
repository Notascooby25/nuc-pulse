import asyncio
import re
import time
from collections import defaultdict
from pathlib import Path

from src.sanitizer import sanitize_text

# Cadence mappings (hours) and grace thresholds
DEFAULT_THRESHOLDS = {
    "sleepdb": 14.0,              # runs 12h
    "mood_images": 14.0,          # runs 6h
    "scrobbler": 14.0,            # runs 6h
    "garmin_tokens": 14.0,        # runs 12h
    "expense_tracker_data": 26.0, # runs daily (24h)
    "host_config": 26.0,          # runs daily (24h)
    "synology": 14.0,             # runs 6h
    "google": 14.0,               # runs 6h
}

ARCHIVE_EXTENSIONS = {".dump", ".gz", ".tar"}


def _format_age(hours: float) -> str:
    if hours < 1.0:
        mins = max(1, int(hours * 60))
        return f"{mins}m ago"
    elif hours < 24.0:
        h = int(hours)
        m = int((hours - h) * 60)
        return f"{h}h {m}m ago"
    else:
        d = int(hours / 24)
        h = int(hours % 24)
        return f"{d}d {h}h ago"


def _extract_category(filename: str) -> str:
    # Remove extensions
    stem = filename
    for ext in [".sql.gz", ".tar.gz", ".dump", ".gz", ".tar"]:
        if stem.endswith(ext):
            stem = stem[: -len(ext)]
            break

    # Strip timestamps like _20261102T060000Z or -20261102T060000Z or _20260920T181417
    cleaned = re.sub(r"[-_]\d{8}[T_]?\d{0,6}Z?.*$", "", stem)
    return cleaned or "other"


def _scan_backup_files(srv_path: Path) -> dict:
    categories = defaultdict(list)
    # Search /srv/shared/backups (and its subdirectories)
    shared_backups = srv_path / "shared" / "backups"
    search_dirs = []
    if shared_backups.is_dir():
        search_dirs.append(shared_backups)
        for child in shared_backups.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                search_dirs.append(child)

    # Search /srv/*/backups
    if srv_path.is_dir():
        for app_dir in srv_path.iterdir():
            if app_dir.is_dir() and app_dir.name != "shared":
                b_dir = app_dir / "backups"
                if b_dir.is_dir():
                    search_dirs.append(b_dir)

    for d in search_dirs:
        try:
            for item in d.iterdir():
                if item.is_file():
                    # Check if archive
                    if any(item.name.endswith(ext) for ext in ARCHIVE_EXTENSIONS):
                        try:
                            stat = item.stat()
                            cat = _extract_category(item.name)
                            categories[cat].append({
                                "name": item.name,
                                "path": str(item),
                                "size_bytes": stat.st_size,
                                "mtime": stat.st_mtime,
                            })
                        except OSError:
                            continue
        except OSError:
            continue

    return categories


def _parse_sync_log(log_path: Path, current_time: float, threshold_hours: float) -> dict:
    if not log_path.is_file():
        return {
            "healthy": False,
            "status_text": "Log file not found",
            "last_run": None,
            "age_hours": None,
            "log_tail": "",
        }

    try:
        stat = log_path.stat()
        mtime = stat.st_mtime
        age_hours = (current_time - mtime) / 3600.0

        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        tail_lines = lines[-15:] if len(lines) >= 15 else lines
        raw_tail = "".join(tail_lines)
        clean_tail = sanitize_text(raw_tail)

        # Check for errors in the tail, ignoring clean phrases like "0 errors"
        tail_upper = raw_tail.upper()
        # Remove harmless phrases
        tail_upper_scrubbed = re.sub(r"0\s+ERRORS?", "", tail_upper)
        has_error = any(
            err in tail_upper_scrubbed
            for err in ["ERROR", "FAILED", "FATAL", "STALE"]
        )

        is_stale = age_hours > threshold_hours

        healthy = (not has_error) and (not is_stale)
        if is_stale:
            status_text = f"Stale (last run {_format_age(age_hours)})"
        elif has_error:
            status_text = "Errors reported in latest run"
        else:
            status_text = f"Completed ({_format_age(age_hours)})"

        return {
            "healthy": healthy,
            "status_text": status_text,
            "last_run": mtime,
            "age_hours": round(age_hours, 1),
            "log_tail": clean_tail,
        }
    except Exception as e:
        return {
            "healthy": False,
            "status_text": f"Error parsing log: {e}",
            "last_run": None,
            "age_hours": None,
            "log_tail": "",
        }


def _inspect_backups_sync(srv_root: str, current_time: float) -> dict:
    srv_path = Path(srv_root)
    categories = _scan_backup_files(srv_path)

    local_pipelines = []
    all_healthy = True

    for cat_name, file_list in categories.items():
        # Sort newest first
        file_list.sort(key=lambda x: x["mtime"], reverse=True)
        latest = file_list[0]
        age_hours = (current_time - latest["mtime"]) / 3600.0
        threshold = DEFAULT_THRESHOLDS.get(cat_name, 26.0)

        # Check conditions
        is_empty = latest["size_bytes"] == 0
        is_stale = age_hours > threshold

        healthy = (not is_empty) and (not is_stale)
        if not healthy:
            all_healthy = False

        if is_empty:
            status_text = "Latest archive is empty (0 bytes)"
        elif is_stale:
            status_text = f"Stale archive ({_format_age(age_hours)})"
        else:
            status_text = f"Fresh ({_format_age(age_hours)})"

        local_pipelines.append({
            "name": cat_name,
            "healthy": healthy,
            "status_text": status_text,
            "version_count": len(file_list),
            "latest_file": latest["name"],
            "latest_size_bytes": latest["size_bytes"],
            "last_run": latest["mtime"],
            "age_hours": round(age_hours, 1),
            "threshold_hours": threshold,
        })

    # Sort pipelines deterministically
    local_pipelines.sort(key=lambda x: x["name"])

    # Offsite Logs
    shared_backups = srv_path / "shared" / "backups"
    syno_info = _parse_sync_log(
        shared_backups / "synology_backup_cron.log",
        current_time,
        DEFAULT_THRESHOLDS["synology"],
    )
    syno_info["name"] = "Synology NAS Mirror"

    google_info = _parse_sync_log(
        shared_backups / "google_backup_cron.log",
        current_time,
        DEFAULT_THRESHOLDS["google"],
    )
    google_info["name"] = "Google Drive Sync"

    offsite = [syno_info, google_info]
    for o in offsite:
        if not o["healthy"]:
            all_healthy = False

    return {
        "all_healthy": all_healthy,
        "local_pipelines": local_pipelines,
        "offsite": offsite,
        "timers": [],
    }


async def inspect_backups(srv_root: str = "/srv", now: float | None = None) -> dict:
    """Non-blocking inspection of all backup archives, directories, and offsite logs."""
    current_time = time.time() if now is None else now
    return await asyncio.to_thread(_inspect_backups_sync, srv_root, current_time)
