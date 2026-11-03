let currentScenario = "nominal";

async function fetchStatus() {
  try {
    const url = `/api/status?scenario=${currentScenario}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderDashboard(data);
  } catch (err) {
    console.error("Fetch error:", err);
    document.getElementById("master-status-text").textContent = "API CONNECTION FAILED";
    document.getElementById("master-status-pill").className = "status-pill degraded";
  }
}

function setScenario(scen) {
  currentScenario = scen;
  document.getElementById("btn-nominal").classList.toggle("active", scen === "nominal");
  document.getElementById("btn-degraded").classList.toggle("active", scen === "degraded");
  fetchStatus();
}

function renderDashboard(data) {
  // Show preview bar if in mock mode
  if (data.is_mock) {
    document.getElementById("preview-bar").style.display = "flex";
  }

  // Master Status Pill
  const pill = document.getElementById("master-status-pill");
  const pillText = document.getElementById("master-status-text");
  if (data.overall_healthy) {
    pill.className = "status-pill nominal";
    pillText.textContent = "ALL SYSTEMS NOMINAL";
  } else {
    pill.className = "status-pill degraded";
    pillText.textContent = `${data.attention_count} ATTENTION ITEMS`;
  }

  // Attention box
  const attnBox = document.getElementById("attention-box");
  const attnList = document.getElementById("attention-list");
  const exportBtn = document.getElementById("export-btn");
  if (data.attention_count > 0 && data.attention_items) {
    attnBox.style.display = "block";
    attnList.innerHTML = data.attention_items.map(it => `<li>${escapeHtml(it)}</li>`).join("");
    if (exportBtn) exportBtn.classList.add("has-issues");
  } else {
    attnBox.style.display = "none";
    if (exportBtn) exportBtn.classList.remove("has-issues");
  }

  // System Vitals
  const sys = data.system || {};
  document.getElementById("system-meta").textContent = `${sys.hostname || "nuc"} • ${sys.os_name || "Linux"} • ${sys.uptime_text || ""}`;

  // CPU
  const cpuVal = sys.cpu_percent != null ? `${sys.cpu_percent}%` : "--%";
  document.getElementById("cpu-val").textContent = cpuVal;
  document.getElementById("cpu-bar").style.width = `${Math.min(100, sys.cpu_percent || 0)}%`;
  const load = sys.load_avg ? sys.load_avg.join(", ") : "--";
  document.getElementById("load-val").textContent = `Load avg: ${load}`;

  // RAM
  if (sys.memory) {
    document.getElementById("ram-val").textContent = `${sys.memory.used_gb} GB / ${sys.memory.total_gb} GB`;
    document.getElementById("ram-bar").style.width = `${sys.memory.percent}%`;
    document.getElementById("ram-percent").textContent = `${sys.memory.percent}% used`;
  }

  // Disk
  if (sys.disk) {
    document.getElementById("disk-val").textContent = `${sys.disk.free_gb} GB Free`;
    document.getElementById("disk-bar").style.width = `${sys.disk.percent}%`;
    document.getElementById("disk-percent").textContent = `${sys.disk.total_gb} GB total (${sys.disk.percent}% used)`;
  }

  // Updates & Net
  if (sys.updates) {
    const ub = document.getElementById("updates-badge");
    ub.textContent = sys.updates.summary || "Updates OK";
    ub.className = `badge ${sys.updates.security_updates > 0 ? "danger" : "nominal"}`;
  }
  const rb = document.getElementById("reboot-badge");
  rb.style.display = sys.reboot_required ? "inline-block" : "none";
  rb.className = "badge warning";

  document.getElementById("inet-dot").className = `indicator-dot ${sys.internet_ok ? "online" : ""}`;
  document.getElementById("tailscale-dot").className = `indicator-dot ${sys.tailscale_ok ? "online" : ""}`;

  // Backups
  renderPipelines(data.backups || {});

  // Core Apps
  renderCoreApps((data.apps || {}).core_apps || []);

  // Watchtowers
  renderWatchtowers((data.apps || {}).watchtowers || []);

  // Container Inventory
  renderContainers((data.apps || {}).containers || []);

  document.getElementById("last-updated-text").textContent = new Date().toLocaleTimeString();
}

function renderPipelines(backups) {
  const offsiteContainer = document.getElementById("offsite-pipelines-container");
  const localContainer = document.getElementById("local-pipelines-container");

  // 1. Offsite sync items
  const offsiteItems = [];
  if (backups.offsite) {
    backups.offsite.forEach(item => {
      offsiteItems.push({
        title: item.name,
        healthy: item.healthy,
        status_text: item.status_text,
        badge: "Sync Status",
        log: item.log_tail,
      });
    });
  }

  // 2. Local pipelines
  const localItems = [];
  if (backups.local_pipelines) {
    backups.local_pipelines.forEach(item => {
      localItems.push({
        title: item.display_name || item.name,
        healthy: item.healthy,
        status_text: `${item.status_text} • ${item.version_count} versions stored`,
        badge: `Retained: ${item.version_count}`,
        log: `Latest archive: ${item.latest_file} (${formatBytes(item.latest_size_bytes)})`,
      });
    });
  }

  const renderCardList = (items) => {
    if (!items || items.length === 0) {
      return '<div class="loading-placeholder">None found.</div>';
    }
    return items.map(p => `
      <div class="pipeline-row ${p.healthy ? "healthy" : "unhealthy"}">
        <details>
          <summary class="pipeline-header">
            <div class="pipeline-title-wrap">
              <span class="status-icon">${p.healthy ? "✅" : "❌"}</span>
              <div>
                <div class="pipeline-name">${escapeHtml(p.title)}</div>
                <div class="pipeline-sub">${escapeHtml(p.status_text)}</div>
              </div>
            </div>
            <span class="pipeline-badge">${escapeHtml(p.badge)} ▾</span>
          </summary>
          <div class="pipeline-drawer">
            <div class="log-box">${escapeHtml(p.log || "No log details available.")}</div>
          </div>
        </details>
      </div>
    `).join("");
  };

  offsiteContainer.innerHTML = renderCardList(offsiteItems);
  localContainer.innerHTML = renderCardList(localItems);
}

function renderCoreApps(apps) {
  const container = document.getElementById("apps-container");
  if (!apps || apps.length === 0) {
    container.innerHTML = '<div class="loading-placeholder">No core applications detected.</div>';
    return;
  }

  container.innerHTML = apps.map(app => `
    <div class="app-card ${app.healthy ? "healthy" : "unhealthy"}">
      <div>
        <div class="app-name">${escapeHtml(app.name)}</div>
        <div class="app-sub">${escapeHtml(app.status_text)}</div>
        ${app.container_name ? `<div class="app-sub app-checked">Checked ${escapeHtml(app.container_name)}${app.probe_target ? ` at ${escapeHtml(app.probe_target)}` : ""}</div>` : ""}
        ${(app.notes || []).map(note => `<div class="app-note">${escapeHtml(note)}</div>`).join("")}
      </div>
      <div>
        <span class="status-icon">${app.healthy ? "✅" : "❌"}</span>
      </div>
    </div>
  `).join("");
}

function renderWatchtowers(wts) {
  const container = document.getElementById("watchtowers-container");
  if (!wts || wts.length === 0) {
    container.innerHTML = '<div class="loading-placeholder">No Watchtower instances found.</div>';
    return;
  }

  container.innerHTML = wts.map(wt => `
    <div class="pipeline-row ${wt.healthy ? "healthy" : "unhealthy"}">
      <details>
        <summary class="pipeline-header">
          <div class="pipeline-title-wrap">
            <span class="status-icon">${wt.healthy ? "✅" : "❌"}</span>
            <div>
              <div class="pipeline-name">${escapeHtml(wt.name)}</div>
              <div class="pipeline-sub">Scope: ${escapeHtml(wt.scope)} • ${escapeHtml(wt.status_text)}</div>
              <div class="pipeline-sub">Watching: ${escapeHtml((wt.watching || []).join(", ") || "none")}</div>
            </div>
          </div>
          <span class="pipeline-badge">Logs ▾</span>
        </summary>
        <div class="pipeline-drawer">
          <div class="log-box">${escapeHtml(wt.log_tail || "No recent Watchtower logs.")}</div>
        </div>
      </details>
    </div>
  `).join("");
}

function renderContainers(containers) {
  document.getElementById("container-count").textContent = containers.length;
  const tbody = document.getElementById("containers-tbody");
  tbody.innerHTML = containers.map(c => `
    <tr>
      <td><strong>${escapeHtml(c.name)}</strong></td>
      <td><code>${escapeHtml(c.image)}</code></td>
      <td><span class="status-icon">${c.healthy ? "🟢" : "🔴"}</span> ${escapeHtml(c.status)}</td>
      <td>${c.ports && c.ports.length ? c.ports.join(", ") : "—"}</td>
    </tr>
  `).join("");
}

function escapeHtml(str) {
  if (!str) return "";
  return str.toString()
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

document.getElementById("refresh-btn").addEventListener("click", async () => {
  try {
    await fetch("/api/refresh", { method: "POST" });
    fetchStatus();
  } catch (e) {
    console.error(e);
  }
});

async function openDiagnosticReport() {
  const modal = document.getElementById("report-modal");
  const textarea = document.getElementById("report-textarea");
  const feedback = document.getElementById("copy-feedback");
  if (feedback) feedback.textContent = "";
  textarea.value = "Generating diagnostic report...";
  if (modal && typeof modal.showModal === "function") {
    modal.showModal();
  } else if (modal) {
    modal.setAttribute("open", "");
  }

  try {
    const res = await fetch(`/api/report?scenario=${currentScenario}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    textarea.value = data.markdown || "No report generated.";
  } catch (err) {
    textarea.value = `Failed to load diagnostic report: ${err.message}`;
  }
}

function closeDiagnosticReport() {
  const modal = document.getElementById("report-modal");
  if (modal && typeof modal.close === "function") {
    modal.close();
  } else if (modal) {
    modal.removeAttribute("open");
  }
}

async function copyDiagnosticReport() {
  const textarea = document.getElementById("report-textarea");
  const feedback = document.getElementById("copy-feedback");
  try {
    await navigator.clipboard.writeText(textarea.value);
    if (feedback) feedback.textContent = "✅ Copied to clipboard! Ready to paste into chat.";
  } catch {
    textarea.select();
    document.execCommand("copy");
    if (feedback) feedback.textContent = "✅ Copied to clipboard!";
  }
}

function downloadDiagnosticReport() {
  const textarea = document.getElementById("report-textarea");
  const blob = new Blob([textarea.value], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `nuc-pulse-diagnostic-${new Date().toISOString().slice(0, 10)}.md`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function formatReleaseDate(iso) {
  const d = new Date(`${iso}T00:00:00Z`);
  if (isNaN(d)) return iso || "";
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

async function loadRelease() {
  try {
    const res = await fetch("/api/release");
    if (!res.ok) return;
    const data = await res.json();
    if (!data.version) return;

    document.getElementById("release-version").textContent = `v${data.version}`;
    document.getElementById("release-title").textContent = `What's new in v${data.version}`;
    document.getElementById("release-date").textContent = data.date ? `Released ${formatReleaseDate(data.date)}` : "";
    document.getElementById("release-changes").innerHTML = (data.changes || [])
      .map(change => `<li>${escapeHtml(change)}</li>`)
      .join("");
    document.getElementById("release-line").hidden = false;
  } catch (e) {
    console.error(e);
  }
}

function openReleaseNotes() {
  const modal = document.getElementById("release-modal");
  if (modal && typeof modal.showModal === "function") {
    modal.showModal();
  } else if (modal) {
    modal.setAttribute("open", "");
  }
}

function closeReleaseNotes() {
  const modal = document.getElementById("release-modal");
  if (modal && typeof modal.close === "function") {
    modal.close();
  } else if (modal) {
    modal.removeAttribute("open");
  }
}

// Initial load and periodic timer
loadRelease();
fetchStatus();
setInterval(fetchStatus, 30000);
