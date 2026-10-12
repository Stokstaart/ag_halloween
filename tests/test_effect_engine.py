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

    # Alleen geconfigureerde effecten opvragen (zoals voor controller)
    configured_only = engine.get_effects_list(only_configured=True)
    assert len(configured_only) == 1
    assert configured_only[0]["id"] == "ghost_attack"


def test_trigger_and_cooldown(temp_env):
    """Test start van effect en cooldown validatie."""
    engine, _, _ = temp_env

    # 1. Start geconfigureerd effect
    success, reason, payload = engine.trigger_effect("ghost_attack")
    assert success is True
    assert payload["effect_id"] == "ghost_attack"

    # 2. Poging om direct een nieuw effect te starten terwijl er een actief is (zonder force)
    success2, reason2, _ = engine.trigger_effect("ghost_attack", force=False)
    assert success2 is False
    assert "Er speelt al een effect" in reason2

    # 3. Stop effect
    engine.stop_effect()
    assert engine.active_effect_id is None

    # 4. Met default zero-cooldown (timeout gedropt) kan operator direct weer klikken!
    success3, reason3, _ = engine.trigger_effect("ghost_attack")
    assert success3 is True

    # 5. Indien expliciet een cooldown geconfigureerd is (bv. 3.0s) wordt deze nageleefd bij force=False
    engine.cooldown_seconds = 3.0
    engine.stop_effect()
    assert engine.get_cooldown_remaining() > 0
    success4, reason4, _ = engine.trigger_effect("ghost_attack", force=False)
    assert success4 is False
    assert "Cooldown actief" in reason4


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


def test_dynamic_effects_discovery(temp_env):
    """Test dat ongeconfigureerde videobestanden in media/effects/ dynamisch ontdekt worden."""
    engine, media_dir, _ = temp_env
    effects_dir = media_dir / "effects"
    
    # Maak nieuw videobestand aan dat niet in effects.json staat
    extra_video = effects_dir / "scare_clown.mp4"
    extra_video.write_bytes(b"\x00" * 1024)

    effects = engine.get_effects_list()
    clown = next((e for e in effects if e["id"] == "scare_clown"), None)
    assert clown is not None
    assert clown["is_custom"] is True
    assert clown["configured"] is True
    assert clown["file_exists"] is True
    assert clown["icon"] == "skull"
    assert "Scare Clown" in clown["name"]


def test_background_switching(temp_env):
    """Test dat achtergronden gewisseld kunnen worden."""
    engine, media_dir, _ = temp_env
    bg_dir = media_dir / "background"

    bg2 = bg_dir / "fog_loop.mp4"
    bg2.write_bytes(b"\x00" * 1024)

    bg_list = engine.get_background_list()
    assert len(bg_list) >= 2

    success, msg, bg = engine.set_background("fog_loop.mp4")
    assert success is True
    assert "fog_loop.mp4" in bg["file"]


def test_effect_duration_reading():
    """Test dat de engine de werkelijke videoduur afleest van echte effect-bestanden."""
    engine = EffectEngine()
    effects = engine.get_effects_list()
    
    # ghost_attack.mp4 is 9.0s -> met 0.7s overlap circa 8.3s
    ghost = next((e for e in effects if e["id"] == "ghost_attack"), None)
    if ghost and ghost["file_exists"]:
        assert ghost["duration"] > 7.0 and ghost["duration"] < 9.0
        assert ghost["raw_duration"] is not None
        assert abs(ghost["raw_duration"] - 9.0) < 0.5


def test_force_trigger_overrides_active_effect_and_cooldown(temp_env):
    """Test dat force=True een actief effect direct vervangt en cooldown omzeilt."""
    engine, _, _ = temp_env

    # 1. Start effect
    s1, _, p1 = engine.trigger_effect("ghost_attack")
    assert s1 is True
    assert engine.active_effect_id == "ghost_attack"

    # 2. Zonder force wordt een volgend effect geweigerd
    s2, r2, _ = engine.trigger_effect("ghost_attack", force=False)
    assert s2 is False
    assert "Er speelt al een effect" in r2

    # 3. Met force=True wordt het effect direct naadloos overschreven!
    s3, r3, p3 = engine.trigger_effect("ghost_attack", force=True)
    assert s3 is True
    assert engine.active_effect_id == "ghost_attack"

    # 4. Stop effect met actieve cooldown
    engine.cooldown_seconds = 3.0
    engine.stop_effect()
    assert engine.get_cooldown_remaining() > 0

    # 5. Tijdens cooldown: zonder force geweigerd, met force direct toegestaan!
    s4, r4, _ = engine.trigger_effect("ghost_attack", force=False)
    assert s4 is False
    assert "Cooldown actief" in r4

    s5, r5, p5 = engine.trigger_effect("ghost_attack", force=True)
    assert s5 is True
    assert engine.active_effect_id == "ghost_attack"


def test_background_in_effects_folder(temp_env):
    """Test dat een achtergrondbestand in de effects folder niet als jumpscare wordt gezien."""
    engine, media_dir, _ = temp_env
    eff_dir = media_dir / "effects"
    bg_eff = eff_dir / "achtergrond_zombies_test.mp4"
    bg_eff.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"z" * 100)

    # Mag NIET als zombie jumpscare gematcht worden
    effects = engine.get_effects_list()
    zombie = next(e for e in effects if e["id"] == "missing_zombie")
    assert zombie["configured"] is False
    assert zombie["file_exists"] is False

    # Moet WEL beschikbaar zijn in get_background_list()
    bg_list = engine.get_background_list()
    assert any("achtergrond_zombies_test.mp4" in b["filename"] for b in bg_list)


def test_exact_filename_matching_and_scare1_naming(temp_env):
    """Test dat bestandsnamen exact gematcht worden en scare1 niet gekaapt wordt door een template."""
    engine, media_dir, _ = temp_env
    eff_dir = media_dir / "effects"
    
    # Maak scare1.mp4 aan
    scare1 = eff_dir / "scare1.mp4"
    scare1.write_bytes(b"\x00" * 1024)

    effects = engine.get_effects_list()
    # zombie/jumpscare template mag scare1.mp4 NIET kapen
    zombie = next((e for e in effects if e["id"] == "missing_zombie"), None)
    assert zombie["file_exists"] is False

    # scare1 moet als dynamisch effect met naam 'Scare 1' ontdekt worden
    scare_effect = next((e for e in effects if e["id"] == "scare1"), None)
    assert scare_effect is not None
    assert scare_effect["name"] == "Scare 1"
    assert scare_effect["file_exists"] is True



