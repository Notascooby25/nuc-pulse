import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import time

import psutil

RE_UPDATES = re.compile(r"(\d+)\s+updates?\s+can\s+be\s+applied", re.IGNORECASE)
RE_SECURITY = re.compile(r"(\d+)\s+of\s+these\s+updates?\s+are\s+.*security", re.IGNORECASE)


def _read_os_name(os_release_path: str = "/etc/os-release") -> str:
    if os.path.exists(os_release_path):
        try:
            with open(os_release_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        return line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
    return "Linux"


def _format_uptime(boot_time: float, now: float | None = None) -> str:
    current = time.time() if now is None else now
    elapsed = max(0, int(current - boot_time))
    days = elapsed // 86400
    hours = (elapsed % 86400) // 3600
    mins = (elapsed % 3600) // 60
    if days > 0:
        return f"up {days} days, {hours} hours"
    if hours > 0:
        return f"up {hours} hours, {mins} mins"
    return f"up {mins} mins"


def _get_fast_vitals_sync(disk_path: str, reboot_flag_path: str) -> dict:
    # 0. Hostname, OS name & Uptime
    hostname = socket.gethostname()
    os_name = _read_os_name()
    uptime_text = _format_uptime(psutil.boot_time())

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

    # 4. Reboot flag (Ubuntu/Debian /var/run/reboot-required or Fedora needs-restarting)
    reboot_required = os.path.exists(reboot_flag_path)

    # 5. Internet check (1.1.1.1:53)
    internet_ok = False
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=1.0):
            internet_ok = True
    except OSError:
        internet_ok = False

    # 6. Tailscale check (check interface)
    tailscale_ok = False
    try:
        addrs = psutil.net_if_addrs()
        if "tailscale0" in addrs:
            tailscale_ok = True
    except Exception:
        tailscale_ok = False

    return {
        "hostname": hostname,
        "os_name": os_name,
        "uptime_text": uptime_text,
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


def _parse_dnf_check_update(output: str) -> int:
    """Parse DNF check-update output, supporting both DNF5 JSON and DNF4/5 plain text."""
    trimmed = output.strip()
    if not trimmed:
        return 0

    # Try JSON parsing first (supported natively by DNF5 on Fedora 41+)
    if trimmed.startswith("{") and trimmed.endswith("}"):
        try:
            data = json.loads(trimmed)
            if isinstance(data, dict):
                upgrades = data.get("upgrades")
                if isinstance(upgrades, list):
                    return len(upgrades)
                return 0
        except json.JSONDecodeError:
            pass

    # Fall back to plain text parsing (DNF4 or non-JSON output)
    count = 0
    in_obsoleting = False
    for raw_line in output.splitlines():
        if raw_line.startswith((" ", "\t")):
            continue
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("Obsoleting Packages"):
            in_obsoleting = True
            continue
        if in_obsoleting:
            continue
        if line.startswith((
            "Last metadata",
            "Updating and loading",
            "Repositories loaded",
            "Security:",
            "Upgrades",
            "Name ",
            "Loaded plugins",
        )):
            continue
        parts = line.split()
        if len(parts) >= 3 and "." in parts[0]:
            count += 1
    return count


def _run_dnf_check_update(security_only: bool = False, timeout: float = 8.0) -> int:
    """Run dnf check-update using local cache (-C), trying --json first then plain text."""
    base_flags = ["-C"]
    if security_only:
        base_flags.append("--security")

    # Attempt 1: with --json (DNF5 native)
    try:
        proc = subprocess.run(
            ["dnf", "check-update", *base_flags, "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode in (0, 100):
            return _parse_dnf_check_update(proc.stdout)
    except Exception:
        pass

    # Attempt 2: plain text (DNF4 fallback)
    try:
        proc = subprocess.run(
            ["dnf", "check-update", *base_flags, "-q"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode in (0, 100):
            return _parse_dnf_check_update(proc.stdout)
    except Exception:
        pass

    return 0


def _get_os_updates_sync(updates_file: str) -> dict:
    # 1. Ubuntu / Debian update-notifier file
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

    # 2. Fedora / RHEL dnf check-update (using local cache -C)
    if shutil.which("dnf"):
        try:
            security = _run_dnf_check_update(security_only=True)
            total = max(security, _run_dnf_check_update(security_only=False))
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
        except Exception:
            pass

    return {
        "total_updates": 0,
        "security_updates": 0,
        "healthy": True,
        "summary": "All updates installed",
    }


async def collect_os_updates(
    updates_file: str = "/var/lib/update-notifier/updates-available",
) -> dict:
    """Non-blocking collector for OS pending packages and security updates."""
    return await asyncio.to_thread(_get_os_updates_sync, updates_file)
