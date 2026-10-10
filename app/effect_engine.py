"""Effectengine voor Halloween raamprojectie."""
import json
import logging
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import (
    ALLOWED_MEDIA_EXTENSIONS,
    CONFIG_FILE,
    COOLDOWN_SECONDS,
    MAX_EFFECT_DURATION_SECONDS,
    MEDIA_DIR,
)

logger = logging.getLogger("halloween.effect_engine")


class EffectEngine:
    """Beheert effectconfiguraties, mediabestanden en runtime-status."""

    def __init__(self, config_path: Path = CONFIG_FILE, media_dir: Path = MEDIA_DIR):
        self.config_path = config_path
        self.media_dir = media_dir

        self.background_config: Dict[str, Any] = {}
        self.effects: Dict[str, Dict[str, Any]] = {}

        # Runtime status
        self.active_effect_id: Optional[str] = None
        self.active_effect_started_at: Optional[float] = None
        self.last_effect_ended_at: float = 0.0
        self.disabled: bool = False
        self.volume: float = 1.0  # 0.0 - 1.0
        self.muted: bool = False

        self.load_configuration()

    def _is_safe_path(self, relative_path: str) -> Optional[Path]:
        """Controleert of een bestandspad binnen de toegestane mediadirectory valt."""
        if not relative_path:
            return None
        try:
            # Verwijder voorloop-slash of prefix 'media/' indien aanwezig
            clean_rel = relative_path.strip().lstrip("/")
            if clean_rel.startswith("media/"):
                clean_rel = clean_rel[len("media/"):]

            target_path = (self.media_dir / clean_rel).resolve()
            # Moet binnen media_dir liggen (geen path traversal)
            if not str(target_path).startswith(str(self.media_dir)):
                logger.warning("Onveilig pad gedetecteerd: %s", relative_path)
                return None

            # Extensie controleren
            if target_path.suffix.lower() not in ALLOWED_MEDIA_EXTENSIONS:
                logger.warning("Niet-toegestane media-extensie: %s", target_path.suffix)
                return None

            return target_path
        except Exception as e:
            logger.error("Fout bij padvalidatie voor %s: %s", relative_path, e)
            return None

    def _check_file_exists(self, relative_path: str) -> Tuple[bool, Optional[str]]:
        """Controleert of het bestand fysiek bestaat en geeft de web-URL terug."""
        resolved = self._is_safe_path(relative_path)
        if not resolved:
            return False, None
        exists = resolved.is_file() and resolved.stat().st_size > 0
        if exists:
            # Relatief pad t.o.v. media_dir voor web serving via /media/...
            rel_to_media = resolved.relative_to(self.media_dir).as_posix()
            web_url = f"/media/{rel_to_media}"
            return True, web_url
        return False, None

    def load_configuration(self) -> None:
        """Laadt of herlaadt effects.json."""
        if not self.config_path.is_file():
            logger.warning("Configuratiebestand %s niet gevonden, fallback actief.", self.config_path)
            self.background_config = {
                "file": "media/background/ambient_fog.mp4",
                "description": "Standaard achtergrond",
                "loop": True,
                "muted": True,
            }
            self.effects = {}
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.background_config = data.get("background", {})
            self.effects = {
                item["id"]: item for item in data.get("effects", []) if "id" in item
            }
            logger.info("Configuratie geladen: %d effecten gevonden.", len(self.effects))
        except Exception as e:
            logger.error("Fout bij laden van %s: %s", self.config_path, e)
            self.effects = {}

    def get_background(self) -> Dict[str, Any]:
        """Geeft de actuele achtergrondconfiguratie inclusief bestandsstatus."""
        file_path = self.background_config.get("file", "")
        exists, web_url = self._check_file_exists(file_path)
        return {
            "file": file_path,
            "web_url": web_url,
            "file_exists": exists,
            "description": self.background_config.get("description", ""),
            "loop": self.background_config.get("loop", True),
            "muted": self.background_config.get("muted", True),
        }

    def get_effects_list(self) -> List[Dict[str, Any]]:
        """Geeft alle effecten terug met hun configuratiestatus."""
        result = []
        for effect_id, item in self.effects.items():
            file_path = item.get("file", "")
            exists, web_url = self._check_file_exists(file_path)
            duration = min(float(item.get("duration", 10.0)), MAX_EFFECT_DURATION_SECONDS)
            result.append({
                "id": effect_id,
                "name": item.get("name", effect_id),
                "file": file_path,
                "web_url": web_url,
                "file_exists": exists,
                "configured": exists,  # Alleen geconfigureerd als het bestand daadwerkelijk bestaat
                "type": item.get("type", "overlay"),  # overlay | fullscreen
                "has_audio": bool(item.get("has_audio", True)),
                "duration": duration,
                "auto_return": bool(item.get("auto_return", True)),
                "description": item.get("description", ""),
                "icon": item.get("icon", "ghost"),
            })
        return result

    def get_effect(self, effect_id: str) -> Optional[Dict[str, Any]]:
        """Haalt een specifiek effect op met actuele status."""
        item = self.effects.get(effect_id)
        if not item:
            return None
        file_path = item.get("file", "")
        exists, web_url = self._check_file_exists(file_path)
        duration = min(float(item.get("duration", 10.0)), MAX_EFFECT_DURATION_SECONDS)
        return {
            "id": effect_id,
            "name": item.get("name", effect_id),
            "file": file_path,
            "web_url": web_url,
            "file_exists": exists,
            "configured": exists,
            "type": item.get("type", "overlay"),
            "has_audio": bool(item.get("has_audio", True)),
            "duration": duration,
            "auto_return": bool(item.get("auto_return", True)),
            "description": item.get("description", ""),
            "icon": item.get("icon", "ghost"),
        }

    def get_cooldown_remaining(self) -> float:
        """Berekent de resterende cooldowntijd in seconden."""
        now = time.time()
        elapsed = now - self.last_effect_ended_at
        remaining = max(0.0, COOLDOWN_SECONDS - elapsed)
        return round(remaining, 1)

    def can_trigger(self) -> Tuple[bool, str, float]:
        """Controleert of een nieuw effect mag worden gestart."""
        if self.disabled:
            return False, "Effecten zijn tijdelijk uitgeschakeld.", 0.0

        if self.active_effect_id is not None:
            # Controleer of effect niet over de maximale duur heen is gelopen
            now = time.time()
            if self.active_effect_started_at and (now - self.active_effect_started_at) > (MAX_EFFECT_DURATION_SECONDS + 2):
                logger.warning("Actief effect %s overschreed maximale duur, forceren reset.", self.active_effect_id)
                self.stop_effect()
            else:
                return False, f"Er speelt al een effect ({self.active_effect_id}).", 0.0

        remaining = self.get_cooldown_remaining()
        if remaining > 0:
            return False, f"Cooldown actief. Wacht nog {remaining}s.", remaining

        return True, "Gereed", 0.0

    def trigger_effect(self, effect_id: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Start een effect indien gevalideerd."""
        can, reason, remaining = self.can_trigger()
        if not can:
            return False, reason, None

        effect = self.get_effect(effect_id)
        if not effect:
            return False, f"Onbekend effect-ID: '{effect_id}'.", None

        if not effect["configured"] or not effect["file_exists"]:
            return False, f"Effect '{effect['name']}' is niet geconfigureerd: mediabestand ontbreekt op de server.", None

        # Start effect
        now = time.time()
        self.active_effect_id = effect_id
        self.active_effect_started_at = now

        payload = {
            "effect_id": effect["id"],
            "name": effect["name"],
            "web_url": effect["web_url"],
            "type": effect["type"],
            "has_audio": effect["has_audio"],
            "duration": effect["duration"],
            "auto_return": effect["auto_return"],
            "started_at": now,
            "volume": self.volume if not self.muted else 0.0,
            "muted": self.muted,
        }
        return True, "Effect gestart", payload

    def trigger_random(self) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Kiest en start een willekeurig geconfigureerd effect."""
        configured_effects = [e for e in self.get_effects_list() if e["configured"]]
        if not configured_effects:
            return False, "Geen enkel geconfigureerd effect met bestaand mediabestand gevonden.", None

        chosen = random.choice(configured_effects)
        return self.trigger_effect(chosen["id"])

    def stop_effect(self) -> Dict[str, Any]:
        """Stopt direct het actieve effect en keert terug naar de achtergrond."""
        stopped_id = self.active_effect_id
        self.active_effect_id = None
        self.active_effect_started_at = None
        self.last_effect_ended_at = time.time()
        logger.info("Effect gestopt: %s. Cooldown gestart.", stopped_id)
        return {
            "stopped_effect_id": stopped_id,
            "cooldown": COOLDOWN_SECONDS,
        }

    def set_volume(self, volume: float) -> float:
        """Stelt het audiovolume in tussen 0.0 en 1.0."""
        self.volume = max(0.0, min(1.0, float(volume)))
        return self.volume

    def set_muted(self, muted: bool) -> bool:
        """Dempt of herstelt audio."""
        self.muted = bool(muted)
        return self.muted

    def toggle_muted(self) -> bool:
        """Wisselt de dempstatus om."""
        self.muted = not self.muted
        return self.muted

    def set_disabled(self, disabled: bool) -> bool:
        """Schakelt de effectengine tijdelijk in of uit."""
        self.disabled = bool(disabled)
        if self.disabled and self.active_effect_id:
            self.stop_effect()
        return self.disabled

    def get_status(self) -> Dict[str, Any]:
        """Geeft de actuele status van de effectengine."""
        can, reason, remaining = self.can_trigger()
        return {
            "active_effect_id": self.active_effect_id,
            "active_effect_started_at": self.active_effect_started_at,
            "disabled": self.disabled,
            "volume": self.volume,
            "muted": self.muted,
            "cooldown_remaining": self.get_cooldown_remaining(),
            "can_trigger": can,
            "reason": reason,
        }
