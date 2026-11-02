import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.app_inspector import inspect_apps_and_containers
from src.backup_inspector import inspect_backups
from src.mock_data import get_mock_scenario
from src.report_builder import build_diagnostic_markdown
from src.system_collector import collect_fast_vitals, collect_os_updates

CACHED_STATE = {}
MOCK_MODE = os.environ.get("NUC_PULSE_MOCK", "0") in ["1", "true", "yes"]
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


async def update_cached_state():
    """Poll live system data into CACHED_STATE."""
    global CACHED_STATE
    try:
        vitals = await collect_fast_vitals()
        updates = await collect_os_updates()
        vitals["updates"] = updates

        backups = await inspect_backups()
        apps = await inspect_apps_and_containers()

        # Compute overall status
        attention_items = []
        if not vitals["disk"]["healthy"]:
            attention_items.append(f"Disk storage critically low ({vitals['disk']['percent']}% used)")
        if not updates["healthy"]:
            attention_items.append(f"{updates['security_updates']} OS security updates pending")
        if vitals["reboot_required"]:
            attention_items.append("Server reboot required")
        if not backups["all_healthy"]:
            attention_items.append("One or more backup pipelines or sync jobs failed/stale")
        if not apps["all_healthy"]:
            attention_items.append("One or more containers or core apps unhealthy")

        overall_healthy = len(attention_items) == 0

        CACHED_STATE = {
            "timestamp": asyncio.get_event_loop().time(),
            "is_mock": False,
            "overall_healthy": overall_healthy,
            "attention_count": len(attention_items),
            "attention_items": attention_items,
            "system": vitals,
            "backups": backups,
            "apps": apps,
        }
    except Exception as e:
        CACHED_STATE = {
            "overall_healthy": False,
            "attention_count": 1,
            "attention_items": [f"Collector error: {e}"],
            "error": str(e),
        }


async def background_poll_loop():
    """Background polling worker running every 30 seconds."""
    while True:
        await update_cached_state()
        await asyncio.sleep(30.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize state
    if not MOCK_MODE:
        await update_cached_state()
        task = asyncio.create_task(background_poll_loop())
    yield
    if not MOCK_MODE and 'task' in locals():
        task.cancel()


app = FastAPI(title="NUC Pulse", lifespan=lifespan)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    index_file = STATIC_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return JSONResponse({"status": "running", "dashboard": "NUC Pulse API"})


@app.get("/api/status")
async def get_status(scenario: str = Query(default="nominal")):
    """Instant status snapshot."""
    if MOCK_MODE or not CACHED_STATE:
        return get_mock_scenario(scenario)
    return CACHED_STATE


@app.get("/api/report")
async def get_diagnostic_report(scenario: str = Query(default="nominal")):
    """Generate a ready-to-paste, sanitized Markdown diagnostic report."""
    state = get_mock_scenario(scenario) if (MOCK_MODE or not CACHED_STATE) else CACHED_STATE
    return {
        "overall_healthy": state.get("overall_healthy", False),
        "attention_count": state.get("attention_count", 0),
        "markdown": build_diagnostic_markdown(state),
    }


@app.post("/api/refresh")
async def force_refresh():
    """Force an immediate re-poll."""
    if not MOCK_MODE:
        await update_cached_state()
    return {"refreshed": True, "mock": MOCK_MODE}
