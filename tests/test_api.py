"""Tests voor de REST API endpoints."""
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app, engine
import app.config as config


@pytest.fixture(autouse=True)
def reset_engine_state():
    """Reset engine state voor elke test."""
    engine.stop_effect()
    engine.last_effect_ended_at = 0.0
    engine.set_disabled(False)
    engine.set_volume(1.0)
    engine.set_muted(False)


@pytest.mark.asyncio
async def test_api_status():
    """Test /api/status endpoint."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "online"
        assert "screens_connected" in data
        assert "controllers_connected" in data
        assert "engine" in data


@pytest.mark.asyncio
async def test_api_effects():
    """Test /api/effects endpoint."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/effects")
        assert resp.status_code == 200
        data = resp.json()
        assert "effects" in data
        assert "background" in data
        assert len(data["effects"]) >= 5


@pytest.mark.asyncio
async def test_api_trigger_unknown_effect():
    """Test dat een onbekend effect-ID een 400 bad request geeft."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/trigger", json={"effect_id": "non_existent_monster"})
        assert resp.status_code == 400
        assert "Onbekend effect-ID" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_api_trigger_unconfigured_effect():
    """Test dat een effect zonder mediabestand geweigerd wordt."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # zombie heeft geen bestand op schijf
        resp = await client.post("/api/trigger", json={"effect_id": "zombie"})
        assert resp.status_code == 400
        assert "niet geconfigureerd" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_api_stop():
    """Test /api/stop endpoint."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/stop")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


@pytest.mark.asyncio
async def test_api_volume():
    """Test /api/volume aanpassingen."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/volume", json={"volume": 0.5, "muted": True})
        assert resp.status_code == 200
        data = resp.json()
        assert data["volume"] == 0.5
        assert data["muted"] is True


@pytest.mark.asyncio
async def test_api_disable():
    """Test /api/disable endpoint."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/disable", json={"disabled": True})
        assert resp.status_code == 200
        assert resp.json()["disabled"] is True
