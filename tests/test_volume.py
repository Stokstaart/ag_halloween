"""Tests voor gescheiden volumeregeling (achtergrond vs scare volume)."""
import pytest
from app.effect_engine import EffectEngine
from fastapi.testclient import TestClient
from app.main import app


def test_split_volume_controls():
    engine = EffectEngine()
    # Standaard initiële waarden
    assert engine.bg_volume == 0.8
    assert engine.scare_volume == 1.0

    # Alleen achtergrond volume aanpassen
    engine.set_bg_volume(0.4)
    assert engine.bg_volume == 0.4
    assert engine.scare_volume == 1.0
    # Backward compatibility property
    assert engine.volume == 0.4

    # Alleen scare volume aanpassen
    engine.set_scare_volume(0.7)
    assert engine.bg_volume == 0.4
    assert engine.scare_volume == 0.7
    # Backward compatibility property
    assert engine.sound_volume == 0.7

    # Clamping grenzen (0.0 tot 1.0)
    engine.set_bg_volume(1.5)
    assert engine.bg_volume == 1.0
    engine.set_scare_volume(-0.5)
    assert engine.scare_volume == 0.0


def test_api_split_volume_endpoint():
    client = TestClient(app)

    # Achtergrond volume instellen
    res = client.post("/api/volume", json={"bg_volume": 0.65})
    assert res.status_code == 200
    data = res.json()
    assert data["bg_volume"] == 0.65
    assert data["success"] is True

    # Scare volume instellen
    res = client.post("/api/volume", json={"scare_volume": 0.85})
    assert res.status_code == 200
    data = res.json()
    assert data["scare_volume"] == 0.85
    assert data["bg_volume"] == 0.65
