#!/usr/bin/env python3
"""Screenshot the local preview at PC and phone sizes, once its data has loaded.

Dev only. Usage: .venv/bin/python scripts/screenshot.py OUT_DIR [--url http://localhost:8520]
OUT_DIR must be outside the project folder, because previews can hold real-looking data.
"""

import argparse
import os
import sys
from pathlib import Path

# Use the browser installed inside .venv (PLAYWRIGHT_BROWSERS_PATH=0 playwright install chromium)
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

REPO_DIR = Path(__file__).resolve().parent.parent
VIEWPORTS = {"desktop": (1366, 900), "phone": (390, 844)}
# Scenario -> text the status pill shows once that scenario's data is on screen
SCENARIOS = {"nominal": "NOMINAL", "degraded": "ATTENTION"}


def take_screenshots(url: str, out_dir: Path) -> list[Path]:
    saved = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for name, (width, height) in VIEWPORTS.items():
                page = browser.new_page(viewport={"width": width, "height": height})
                page.goto(url)
                # The scenario bar only appears once the first data has loaded (mock mode)
                page.wait_for_selector("#preview-bar", state="visible")
                for scenario, expected in SCENARIOS.items():
                    with page.expect_response(lambda r, s=scenario: f"scenario={s}" in r.url):
                        page.click(f"#btn-{scenario}")
                    page.wait_for_function(
                        "t => document.getElementById('master-status-text').textContent.includes(t)",
                        arg=expected,
                    )
                    path = out_dir / f"{name}-{scenario}.png"
                    page.screenshot(path=str(path), full_page=True)
                    saved.append(path)

                if not page.is_hidden("#release-line"):
                    page.click("#release-line .link-btn")
                    path = out_dir / f"{name}-whats-new.png"
                    page.screenshot(path=str(path))
                    saved.append(path)
                page.close()
        finally:
            browser.close()
    return saved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--url", default="http://localhost:8520")
    args = parser.parse_args()

    out_dir = args.out_dir.resolve()
    if out_dir == REPO_DIR or REPO_DIR in out_dir.parents:
        print(f"Refusing to save screenshots inside the project folder: {out_dir}")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        saved = take_screenshots(args.url, out_dir)
    except PlaywrightError as e:
        first_line = str(e).strip().splitlines()[0]
        print(f"Could not take screenshots of {args.url}: {first_line}")
        print("Is the preview running? Start it with: scripts/preview.sh up")
        return 1

    for path in saved:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
