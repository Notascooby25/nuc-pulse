import asyncio
import os
import re
import shutil
import socket

import psutil

RE_UPDATES = re.compile(r"(\d+)\s+updates?\s+can\s+be\s+applied", re.IGNORECASE)
RE_SECURITY = re.compile(r"(\d+)\s+of\s+these\s+updates?\s+are\s+.*security", re.IGNORECASE)


def _get_fast_vitals_sync(disk_path: str, reboot_flag_path: str) -> dict:
    # 1. CPU
    cpu_percent = psutil.cpu_percent(interval=None)
    try:
        load_avg = [round(x, 2) for x in os.getloadavg()]
    except (AttributeError, OSError):
        load_avg = [0.0, 0.0, 0.0]

    # 2. Memory
    mem = psutil.virtual_memory()
    memory_info = {
        "used_gb": round(mem.used / (1024**3), 2),
        "total_gb": round(mem.total / (1024**3), 2),
        "percent": mem.percent,
        "healthy": mem.percent < 90.0,
    }

    # 3. Disk
    try:
        usage = shutil.disk_usage(disk_path)
        disk_total_gb = round(usage.total / (1024**3), 2)
        disk_used_gb = round(usage.used / (1024**3), 2)
        disk_free_gb = round(usage.free / (1024**3), 2)
        disk_percent = round((usage.used / usage.total) * 100, 1) if usage.total > 0 else 0.0
    except OSError:
        disk_total_gb, disk_used_gb, disk_free_gb, disk_percent = 0.0, 0.0, 0.0, 0.0

    disk_info = {
        "total_gb": disk_total_gb,
        "used_gb": disk_used_gb,
        "free_gb": disk_free_gb,
        "percent": disk_percent,
        "healthy": disk_percent < 90.0,
    }

    # 4. Reboot flag
    reboot_required = os.path.exists(reboot_flag_path)

    # 5. Internet check (1.1.1.1:53)
    internet_ok = False
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=1.0):
            internet_ok = True
    except OSError:
        internet_ok = False

    # 7. Tailscale check (check socket or interface)
    tailscale_ok = False
    try:
        addrs = psutil.net_if_addrs()
        if "tailscale0" in addrs:
            tailscale_ok = True
    except Exception:
        tailscale_ok = False

    return {
        "cpu_percent": cpu_percent,
        "load_avg": load_avg,
        "memory": memory_info,
        "disk": disk_info,
        "reboot_required": reboot_required,
        "internet_ok": internet_ok,
        "tailscale_ok": tailscale_ok,
    }


async def collect_fast_vitals(
    disk_path: str = "/", reboot_flag_path: str = "/var/run/reboot-required"
) -> dict:
    """Non-blocking collect of CPU, RAM, Disk, Uptime, Network, and Reboot flag."""
    return await asyncio.to_thread(_get_fast_vitals_sync, disk_path, reboot_flag_path)


def _get_os_updates_sync(updates_file: str) -> dict:
    if os.path.exists(updates_file):
        try:
            with open(updates_file, "r", encoding="utf-8") as f:
                content = f.read()
            m_up = RE_UPDATES.search(content)
            m_sec = RE_SECURITY.search(content)
            total = int(m_up.group(1)) if m_up else 0
            security = int(m_sec.group(1)) if m_sec else 0
            healthy = security == 0
            summary = (
                "All updates installed"
                if total == 0
                else f"{total} updates pending ({security} security)"
            )
            return {
                "total_updates": total,
                "security_updates": security,
                "healthy": healthy,
                "summary": summary,
            }
        except Exception as e:
            return {
                "total_updates": 0,
                "security_updates": 0,
                "healthy": True,
                "summary": f"Could not read updates: {e}",
            }

    # Fallback when running on Fedora/test environment or updates-available is absent
    return {
        "total_updates": 0,
        "security_updates": 0,
        "healthy": True,
        "summary": "OS up to date or update-notifier not installed",
    }


async def collect_os_updates(
    updates_file: str = "/var/lib/update-notifier/updates-available",
) -> dict:
    """Non-blocking collector for OS pending packages and security updates."""
    return await asyncio.to_thread(_get_os_updates_sync, updates_file)
