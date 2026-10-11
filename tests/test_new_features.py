import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from app.effect_engine import EffectEngine
from app.scheduler import AutoScareScheduler
from app.media_optimizer import MediaOptimizer
from fastapi.testclient import TestClient
from app.main import app


def test_split_volume_controls():
    engine = EffectEngine()
    # Default initial values
    assert engine.bg_volume == 0.8
    assert engine.scare_volume == 1.0

    # Test setting bg volume only
    engine.set_bg_volume(0.4)
    assert engine.bg_volume == 0.4
    assert engine.scare_volume == 1.0
    # Backward compatibility property
    assert engine.volume == 0.4

    # Test setting scare volume only
    engine.set_scare_volume(0.7)
    assert engine.bg_volume == 0.4
    assert engine.scare_volume == 0.7
    # Backward compatibility property
    assert engine.sound_volume == 0.7

    # Clamping
    engine.set_bg_volume(1.5)
    assert engine.bg_volume == 1.0
    engine.set_scare_volume(-0.5)
    assert engine.scare_volume == 0.0


def test_api_split_volume_endpoint():
    client = TestClient(app)

    # Set background volume only
    res = client.post("/api/volume", json={"bg_volume": 0.65})
    assert res.status_code == 200
    data = res.json()
    assert data["bg_volume"] == 0.65
    assert data["success"] is True

    # Set scare volume only
    res = client.post("/api/volume", json={"scare_volume": 0.85})
    assert res.status_code == 200
    data = res.json()
    assert data["scare_volume"] == 0.85
    assert data["bg_volume"] == 0.65


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

    # Configure
    scheduler.set_config(min_minutes=0.5, max_minutes=1.5, mode="sound")
    assert scheduler.min_minutes == 0.5
    assert scheduler.max_minutes == 1.5
    assert scheduler.mode == "sound"

    # Start
    scheduler.set_enabled(True)
    assert scheduler.enabled is True
    assert scheduler.next_trigger_at is not None
    assert scheduler.next_trigger_type == "sound"

    # Stop
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

    # Update configuration
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


def test_media_optimizer_health():
    client = TestClient(app)
    res = client.get("/api/media/health")
    assert res.status_code == 200
    data = res.json()
    assert "total_videos" in data
    assert "optimal_count" in data
    assert "needs_optimization" in data
    assert isinstance(data["files"], list)
