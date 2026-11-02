from datetime import datetime, timezone

from src.sanitizer import sanitize_diagnostic_report


def _format_bytes(size_bytes: int | None) -> str:
    if not size_bytes:
        return "0 B"
    val = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if val < 1024.0:
            return f"{val:.1f} {unit}"
        val /= 1024.0
    return f"{val:.1f} PB"


def build_diagnostic_markdown(state: dict) -> str:
    """Build a ready-to-paste, sanitized Markdown diagnostic report from the current dashboard snapshot."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    overall_healthy = state.get("overall_healthy", False)
    attention_count = state.get("attention_count", 0)
    attention_items = state.get("attention_items", []) or []
    sys_info = state.get("system", {}) or {}
    backups = state.get("backups", {}) or {}
    apps = state.get("apps", {}) or {}

    status_label = "✅ ALL SYSTEMS NOMINAL" if overall_healthy else f"❌ {attention_count} ATTENTION ITEMS"

    lines = [
        "# NUC Pulse Diagnostic Report",
        f"- **Generated:** {now_iso}",
        f"- **Overall Status:** {status_label}",
        f"- **OS:** {sys_info.get('os_name', 'Unknown')} ({sys_info.get('uptime_text', 'uptime unknown')})",
        "",
    ]

    # 1. Attention Summary
    lines.append("## 1. Attention Summary")
    if attention_items:
        for item in attention_items:
            lines.append(f"- ❌ {item}")
    else:
        lines.append("- ✅ No active alerts or attention items.")
    lines.append("")

    # 2. System Vitals & OS Updates
    mem = sys_info.get("memory", {}) or {}
    disk = sys_info.get("disk", {}) or {}
    updates = sys_info.get("updates", {}) or {}
    load_avg = sys_info.get("load_avg", []) or []
    load_str = ", ".join(str(x) for x in load_avg) if load_avg else "n/a"

    lines.extend([
        "## 2. System Vitals & OS Health",
        f"- **CPU:** {sys_info.get('cpu_percent', 0)}% (Load avg: {load_str})",
        f"- **Memory:** {mem.get('used_gb', 0)} GB / {mem.get('total_gb', 0)} GB ({mem.get('percent', 0)}%)",
        f"- **Disk (/):** {disk.get('free_gb', 0)} GB free of {disk.get('total_gb', 0)} GB ({disk.get('percent', 0)}% used)",
        f"- **OS Updates:** {updates.get('summary', 'Unknown')} (Security updates: {updates.get('security_updates', 0)})",
        f"- **Reboot Required:** {'Yes ⚠️' if sys_info.get('reboot_required') else 'No'}",
        f"- **Connectivity:** Internet={'OK' if sys_info.get('internet_ok') else 'FAIL'}, Tailscale={'OK' if sys_info.get('tailscale_ok') else 'OFFLINE'}",
        "",
    ])

    # 3. Backup Pipelines & Offsite Sync
    lines.append("## 3. Backup Pipelines & Offsite Sync Issues")
    offsite_list = backups.get("offsite", []) or []
    local_list = backups.get("local_pipelines", []) or []

    unhealthy_offsite = [o for o in offsite_list if not o.get("healthy", False)]
    healthy_offsite = [o.get("name", "unknown") for o in offsite_list if o.get("healthy", False)]
    unhealthy_local = [p for p in local_list if not p.get("healthy", False)]
    healthy_local = [p.get("display_name") or p.get("name", "unknown") for p in local_list if p.get("healthy", False)]

    if not unhealthy_offsite and not unhealthy_local:
        lines.append("- ✅ No failing or stale backups detected.")
    else:
        for o in unhealthy_offsite:
            lines.append(f"### ❌ Offsite: {o.get('name', 'Unknown')}")
            lines.append(f"- **Status:** {o.get('status_text', 'Unknown')}")
            lines.append(f"- **Age (hours):** {o.get('age_hours', 'n/a')}")
            log_tail = (o.get("log_tail") or "").strip()
            if log_tail:
                lines.append("```text")
                lines.append(log_tail)
                lines.append("```")
        for p in unhealthy_local:
            title = p.get("display_name") or p.get("name", "Unknown")
            lines.append(f"### ❌ Local Pipeline: {title}")
            lines.append(f"- **Status:** {p.get('status_text', 'Unknown')}")
            lines.append(
                f"- **Latest File:** `{p.get('latest_file', 'none')}` "
                f"({_format_bytes(p.get('latest_size_bytes'))}, {p.get('version_count', 0)} versions retained)"
            )
            lines.append(
                f"- **Age:** {p.get('age_hours', 'n/a')}h (Threshold: {p.get('threshold_hours', 'n/a')}h)"
            )

    if healthy_offsite or healthy_local:
        lines.append(
            f"- *Healthy backups:* Offsite ({', '.join(healthy_offsite) or 'none'}) | "
            f"Local ({', '.join(healthy_local) or 'none'})"
        )
    lines.append("")

    # 4. Applications, Watchtowers & Containers
    lines.append("## 4. Applications, Watchtowers & Containers Issues")
    if not apps.get("docker_available", True):
        lines.append(f"- ❌ **Docker Engine Unavailable:** {apps.get('error', 'Unknown error')}")
    else:
        core_apps = apps.get("core_apps", []) or []
        watchtowers = apps.get("watchtowers", []) or []
        containers = apps.get("containers", []) or []

        bad_core = [a for a in core_apps if not a.get("healthy", False)]
        bad_wt = [w for w in watchtowers if not w.get("healthy", False)]
        bad_containers = [c for c in containers if not c.get("healthy", False)]

        if not bad_core and not bad_wt and not bad_containers:
            lines.append("- ✅ No unhealthy applications or containers detected.")
        else:
            for a in bad_core:
                lines.append(
                    f"- ❌ **Core App `{a.get('name')}`** (container `{a.get('container_name')}`, "
                    f"port `{a.get('port')}`): {a.get('status_text')}"
                )
            for w in bad_wt:
                lines.append(
                    f"### ❌ Watchtower: `{w.get('name')}` (scope: `{w.get('scope')}`)"
                )
                lines.append(f"- **Status:** {w.get('status_text')}")
                wt_log = (w.get("log_tail") or "").strip()
                if wt_log:
                    lines.append("```text")
                    lines.append(wt_log)
                    lines.append("```")
            for c in bad_containers:
                lines.append(
                    f"- ❌ **Container `{c.get('name')}`** (`{c.get('image', '')}`): "
                    f"state=`{c.get('state')}`, status=`{c.get('status', '')}`"
                )

        healthy_c_count = sum(1 for c in containers if c.get("healthy", False))
        lines.append(f"- *Container fleet summary:* {healthy_c_count}/{len(containers)} containers healthy.")

    raw_markdown = "\n".join(lines) + "\n"
    return sanitize_diagnostic_report(raw_markdown)
