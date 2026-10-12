"""Tests voor de AutoScareScheduler (automatische spookmodus)."""
import pytest
from unittest.mock import MagicMock, AsyncMock
from app.scheduler import AutoScareScheduler
from fastapi.testclient import TestClient
from app.main import app


@pytest.mark.asyncio
async def test_scheduler_lifecycle():
    trigger_mock = MagicMock(return_value=(True, "TestScare"))
    broadcast_mock = AsyncMock()

    scheduler = AutoScareScheduler(
        trigger_callback=trigger_mock,
        broadcast_callback=broadcast_mock,
    )

    assert not scheduler.enabled
    status = scheduler.get_status()
    assert status["enabled"] is False
    assert status["min_minutes"] == 1.0
    assert status["max_minutes"] == 6.0
    assert status["mode"] == "both"

    # Configuratie bijwerken
    scheduler.set_config(min_minutes=0.5, max_minutes=1.5, mode="sound")
    assert scheduler.min_minutes == 0.5
    assert scheduler.max_minutes == 1.5
    assert scheduler.mode == "sound"

    # Starten
    scheduler.set_enabled(True)
    assert scheduler.enabled is True
    assert scheduler.next_trigger_at is not None
    assert scheduler.next_trigger_type == "sound"

    # Stoppen
    scheduler.set_enabled(False)
    assert scheduler.enabled is False
    assert scheduler.next_trigger_at is None


def test_api_autopilot_endpoints():
    client = TestClient(app)

    res = client.get("/api/autopilot")
    assert res.status_code == 200
    data = res.json()
    assert "enabled" in data
    assert "mode" in data

    # Update configuratie
    res = client.post("/api/autopilot", json={
        "enabled": False,
        "min_minutes": 1.0,
        "max_minutes": 3.0,
        "mode": "jumpscare"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "jumpscare"
    assert data["min_minutes"] == 1.0
    assert data["max_minutes"] == 3.0
