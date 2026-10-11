"""Tests voor Sound Effects (geluidseffecten en overlappende audio)."""
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.effect_engine import EffectEngine


@pytest.fixture
def temp_sound_dirs(tmp_path):
    media_dir = tmp_path / "media"
    music_dir = media_dir / "effects" / "music"
    music_dir.mkdir(parents=True)
    audio_dir = media_dir / "audio"
    audio_dir.mkdir(parents=True)

    # Maak nep MP3 bestanden
    (music_dir / "thunder_strike.mp3").write_bytes(b"ID3" + b"\x00" * 200)
    (music_dir / "witch_laugh.mp3").write_bytes(b"ID3" + b"\x00" * 300)
    (audio_dir / "wolf_howl.mp3").write_bytes(b"ID3" + b"\x00" * 400)

    config_path = tmp_path / "effects.json"
    return media_dir, config_path


def test_sound_effects_discovery(temp_sound_dirs):
    media_dir, config_path = temp_sound_dirs
    engine = EffectEngine(config_path=config_path, media_dir=media_dir)

    sounds = engine.get_sound_effects_list()
    assert len(sounds) == 3

    sound_ids = [s["id"] for s in sounds]
    assert "sound_thunder_strike" in sound_ids
    assert "sound_witch_laugh" in sound_ids
    assert "sound_wolf_howl" in sound_ids

    # Icoon checks
    thunder = next(s for s in sounds if s["id"] == "sound_thunder_strike")
    assert thunder["icon"] == "⚡"
    laugh = next(s for s in sounds if s["id"] == "sound_witch_laugh")
    assert laugh["icon"] == "😈"
    wolf = next(s for s in sounds if s["id"] == "sound_wolf_howl")
    assert wolf["icon"] == "🐺"


def test_sound_effect_trigger(temp_sound_dirs):
    media_dir, config_path = temp_sound_dirs
    engine = EffectEngine(config_path=config_path, media_dir=media_dir)

    success, msg, payload = engine.trigger_sound_effect("sound_thunder_strike")
    assert success is True
    assert payload["sound_id"] == "sound_thunder_strike"
    assert "thunder_strike.mp3" in payload["filename"]
    assert "/media/" in payload["web_url"]

    # Controleer dat actief video effect NIET beïnvloed is
    assert engine.active_effect_id is None


def test_api_sounds_endpoint(temp_sound_dirs, monkeypatch):
    media_dir, config_path = temp_sound_dirs
    from app import main

    test_engine = EffectEngine(config_path=config_path, media_dir=media_dir)
    monkeypatch.setattr(main, "engine", test_engine)

    client = TestClient(app)
    response = client.get("/api/sounds")
    assert response.status_code == 200
    data = response.json()
    assert "sounds" in data
    assert len(data["sounds"]) == 3


def test_api_sound_trigger_endpoint(temp_sound_dirs, monkeypatch):
    media_dir, config_path = temp_sound_dirs
    from app import main

    test_engine = EffectEngine(config_path=config_path, media_dir=media_dir)
    monkeypatch.setattr(main, "engine", test_engine)

    client = TestClient(app)
    response = client.post("/api/sound", json={"sound_id": "sound_wolf_howl"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["sound"]["sound_id"] == "sound_wolf_howl"


def test_websocket_sound_trigger(temp_sound_dirs, monkeypatch):
    media_dir, config_path = temp_sound_dirs
    from app import main

    test_engine = EffectEngine(config_path=config_path, media_dir=media_dir)
    monkeypatch.setattr(main, "engine", test_engine)

    client = TestClient(app)
    with client.websocket_connect("/ws?role=screen") as screen_ws:
        init_screen = screen_ws.receive_json()
        assert init_screen["type"] == "init"

        with client.websocket_connect("/ws?role=control") as ctrl_ws:
            init_ctrl = ctrl_ws.receive_json()
            assert init_ctrl["type"] == "init"
            assert "sounds" in init_ctrl
            assert len(init_ctrl["sounds"]) == 3

            # Controller stuurt play_sound
            ctrl_ws.send_json({"action": "play_sound", "sound_id": "sound_witch_laugh"})

            # Controller krijgt sound_ack
            ack = ctrl_ws.receive_json()
            assert ack["type"] == "sound_ack"
            assert ack["success"] is True

            # Scherm ontvangt play_sound
            screen_msg = screen_ws.receive_json()
            assert screen_msg["type"] == "play_sound"
            assert screen_msg["sound_id"] == "sound_witch_laugh"
            assert "web_url" in screen_msg


def test_api_sound_stop_endpoint(temp_sound_dirs, monkeypatch):
    media_dir, config_path = temp_sound_dirs
    from app import main

    test_engine = EffectEngine(config_path=config_path, media_dir=media_dir)
    monkeypatch.setattr(main, "engine", test_engine)

    client = TestClient(app)
    response = client.post("/api/sound/stop", json={"sound_id": "sound_wolf_howl"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["sound_id"] == "sound_wolf_howl"


def test_sound_volume_control(temp_sound_dirs, monkeypatch):
    media_dir, config_path = temp_sound_dirs
    from app import main

    test_engine = EffectEngine(config_path=config_path, media_dir=media_dir)
    monkeypatch.setattr(main, "engine", test_engine)

    assert test_engine.sound_volume == 1.0
    test_engine.set_sound_volume(0.42)
    assert test_engine.sound_volume == 0.42

    client = TestClient(app)
    # Test setting sound volume via /api/volume
    res = client.post("/api/volume", json={"sound_volume": 0.75})
    assert res.status_code == 200
    assert test_engine.sound_volume == 0.75
    assert res.json()["sound_volume"] == 0.75


def test_websocket_sound_stop_and_ended(temp_sound_dirs, monkeypatch):
    media_dir, config_path = temp_sound_dirs
    from app import main

    test_engine = EffectEngine(config_path=config_path, media_dir=media_dir)
    monkeypatch.setattr(main, "engine", test_engine)

    client = TestClient(app)
    with client.websocket_connect("/ws?role=screen") as screen_ws:
        _ = screen_ws.receive_json()

        with client.websocket_connect("/ws?role=control") as ctrl_ws:
            _ = ctrl_ws.receive_json()

            # Controller stuurt stop_sound
            ctrl_ws.send_json({"action": "stop_sound", "sound_id": "sound_witch_laugh"})

            # Controller ontvangt sound_stopped
            ctrl_msg = ctrl_ws.receive_json()
            assert ctrl_msg["type"] == "sound_stopped"
            assert ctrl_msg["sound_id"] == "sound_witch_laugh"

            # Scherm ontvangt stop_sound
            screen_msg = screen_ws.receive_json()
            assert screen_msg["type"] == "stop_sound"
            assert screen_msg["sound_id"] == "sound_witch_laugh"

            # Scherm stuurt sound_ended (bijv. als audio natuurlijk afloopt)
            screen_ws.send_json({"action": "sound_ended", "sound_id": "sound_thunder_strike"})

            # Controller ontvangt sound_stopped
            ctrl_msg2 = ctrl_ws.receive_json()
            assert ctrl_msg2["type"] == "sound_stopped"
            assert ctrl_msg2["sound_id"] == "sound_thunder_strike"

            # Controller stuurt set_sound_volume
            ctrl_ws.send_json({"action": "set_sound_volume", "sound_volume": 0.35})
            screen_vol_msg = screen_ws.receive_json()
            assert screen_vol_msg["type"] == "volume_update"
            assert screen_vol_msg["sound_volume"] == 0.35
            ctrl_vol_msg = ctrl_ws.receive_json()
            assert ctrl_vol_msg["type"] == "volume_update"
            assert ctrl_vol_msg["sound_volume"] == 0.35

