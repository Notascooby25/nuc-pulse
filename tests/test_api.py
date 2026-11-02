import pytest
import httpx
from src.main import app

@pytest.mark.asyncio
async def test_api_status_mock_mode_nominal():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Default mock mode or scenario nominal
        resp = await client.get("/api/status?scenario=nominal")
        assert resp.status_code == 200
        data = resp.json()
        assert "overall_healthy" in data
        assert data["overall_healthy"] is True
        assert data["attention_count"] == 0
        assert "system" in data
        assert "backups" in data
        assert "apps" in data

@pytest.mark.asyncio
async def test_api_status_mock_mode_degraded():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/status?scenario=degraded")
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_healthy"] is False
        assert data["attention_count"] > 0
        assert len(data["attention_items"]) > 0

@pytest.mark.asyncio
async def test_api_refresh_endpoint():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("refreshed") is True
