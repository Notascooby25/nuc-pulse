import tomllib
from pathlib import Path

import httpx
import pytest

import src.main
from src.changelog import latest_release
from src.main import CHANGELOG_PATH, app

SAMPLE = """# Changelog

Intro text, not a change.

## 1.2.0 - 2026-01-05
- First change with <b>tag</b> & `code`.
- Second change that wraps
  onto a second line.

## 1.1.0 - 2026-01-01
- Older change.
"""


def _pyproject_version():
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject.open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def test_latest_release_reads_newest_entry(tmp_path):
    p = tmp_path / "CHANGELOG.md"
    p.write_text(SAMPLE)
    assert latest_release(p) == {
        "version": "1.2.0",
        "date": "2026-01-05",
        "changes": [
            "First change with <b>tag</b> & `code`.",
            "Second change that wraps onto a second line.",
        ],
    }


def test_latest_release_missing_file_returns_none(tmp_path):
    assert latest_release(tmp_path / "nope.md") is None


def test_latest_release_no_version_heading_returns_none(tmp_path):
    p = tmp_path / "CHANGELOG.md"
    p.write_text("# Changelog\n\nNothing yet.\n")
    assert latest_release(p) is None


def test_real_changelog_matches_pyproject_version():
    release = latest_release(CHANGELOG_PATH)
    assert release is not None
    assert release["version"] == _pyproject_version()
    assert release["changes"]


@pytest.mark.asyncio
async def test_api_release_returns_latest():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/release")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == _pyproject_version()
        assert data["changes"]


@pytest.mark.asyncio
async def test_api_release_missing_changelog(monkeypatch, tmp_path):
    monkeypatch.setattr(src.main, "CHANGELOG_PATH", tmp_path / "missing.md")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/release")
        assert resp.status_code == 200
        assert resp.json() == {"version": None, "date": None, "changes": []}
