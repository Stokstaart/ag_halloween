"""Tests voor de EffectEngine."""
import json
import time
from pathlib import Path
import pytest
from app.effect_engine import EffectEngine


@pytest.fixture
def temp_env(tmp_path):
    """Creëert een tijdelijke testomgeving met configuratie en dummy media."""
    media_dir = tmp_path / "media"
    config_dir = tmp_path / "config"
    (media_dir / "background").mkdir(parents=True)
    (media_dir / "effects").mkdir(parents=True)
    (media_dir / "audio").mkdir(parents=True)
    config_dir.mkdir(parents=True)

    # Maak dummy videobestanden
    bg_file = media_dir / "background" / "ambient_fog.mp4"
    bg_file.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"1" * 100)

    ghost_file = media_dir / "effects" / "ghost_attack.mp4"
    ghost_file.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"2" * 100)

    # Configbestand
    config_file = config_dir / "effects.json"
    config_data = {
        "version": "1.0",
        "background": {
            "file": "media/background/ambient_fog.mp4",
            "loop": True,
            "muted": True
        },
        "effects": [
            {
                "id": "ghost_attack",
                "name": "Ghost Attack",
                "file": "media/effects/ghost_attack.mp4",
                "type": "overlay",
                "has_audio": True,
                "duration": 5.0,
                "auto_return": True
            },
            {
                "id": "missing_zombie",
                "name": "Zombie",
                "file": "media/effects/zombie_not_found.mp4",
                "type": "fullscreen",
                "has_audio": True,
                "duration": 5.0,
                "auto_return": True
            }
        ]
    }
    config_file.write_text(json.dumps(config_data), encoding="utf-8")

    engine = EffectEngine(config_path=config_file, media_dir=media_dir)
    return engine, media_dir, config_file


def test_path_traversal_prevention(temp_env):
    """Zorg dat directory traversal pogingen worden geblokkeerd."""
    engine, media_dir, _ = temp_env
    assert engine._is_safe_path("../../../etc/passwd") is None
    assert engine._is_safe_path("/etc/shadow") is None
    assert engine._is_safe_path("media/../../../secret.txt") is None
    assert engine._is_safe_path("effects/bad_script.sh") is None  # Niet-toegestane extensie


def test_configuration_loading_and_file_existence(temp_env):
    """Controleer of effecten correct gemarkeerd worden als geconfigureerd of niet."""
    engine, _, _ = temp_env
    effects = engine.get_effects_list()
    assert len(effects) == 2

    ghost = next(e for e in effects if e["id"] == "ghost_attack")
    assert ghost["configured"] is True
    assert ghost["file_exists"] is True
    assert ghost["web_url"] == "/media/effects/ghost_attack.mp4"

    zombie = next(e for e in effects if e["id"] == "missing_zombie")
    assert zombie["configured"] is False
    assert zombie["file_exists"] is False
    assert zombie["web_url"] is None


def test_trigger_and_cooldown(temp_env):
    """Test start van effect en cooldown validatie."""
    engine, _, _ = temp_env

    # 1. Start geconfigureerd effect
    success, reason, payload = engine.trigger_effect("ghost_attack")
    assert success is True
    assert payload["effect_id"] == "ghost_attack"

    # 2. Poging om direct een nieuw effect te starten terwijl er een actief is
    success2, reason2, _ = engine.trigger_effect("ghost_attack")
    assert success2 is False
    assert "Er speelt al een effect" in reason2

    # 3. Stop effect
    engine.stop_effect()
    assert engine.active_effect_id is None

    # 4. Direct proberen te starten tijdens cooldown
    success3, reason3, _ = engine.trigger_effect("ghost_attack")
    assert success3 is False
    assert "Cooldown actief" in reason3


def test_trigger_unconfigured_rejected(temp_env):
    """Test dat niet-geconfigureerde effecten direct geweigerd worden."""
    engine, _, _ = temp_env
    success, reason, _ = engine.trigger_effect("missing_zombie")
    assert success is False
    assert "niet geconfigureerd" in reason


def test_disable_toggle(temp_env):
    """Test het tijdelijk uitschakelen van effecten."""
    engine, _, _ = temp_env
    engine.set_disabled(True)
    assert engine.disabled is True

    success, reason, _ = engine.trigger_effect("ghost_attack")
    assert success is False
    assert "uitgeschakeld" in reason
