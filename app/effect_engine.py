"""Effectengine voor Halloween raamprojectie."""
import json
import logging
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

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

    def __init__(self, config_path: Path = CONFIG_FILE, media_dir: Path = MEDIA_DIR, cooldown_seconds: Optional[float] = None):
        self.config_path = config_path
        self.media_dir = media_dir
        self.cooldown_seconds = float(cooldown_seconds) if cooldown_seconds is not None else COOLDOWN_SECONDS

        self.background_config: Dict[str, Any] = {}
        self.effects: Dict[str, Dict[str, Any]] = {}

        # Runtime status
        self.active_background_file: Optional[str] = None
        self.active_effect_id: Optional[str] = None
        self.active_effect_started_at: Optional[float] = None
        self.last_effect_ended_at: float = 0.0
        self.disabled: bool = False
        self.volume: float = 1.0  # 0.0 - 1.0 (video volume)
        self.sound_volume: float = 1.0  # 0.0 - 1.0 (losse sound effects volume)
        self.muted: bool = False
        self._duration_cache: Dict[str, Tuple[float, float]] = {}

        self.load_configuration()


    def _get_media_duration(self, file_path: Union[str, Path]) -> Optional[float]:
        """Leest de exacte duur van een videobestand (MP4/WebM) in seconden via box header parsing."""
        if isinstance(file_path, Path):
            p = file_path
        else:
            resolved = self._is_safe_path(str(file_path))
            p = resolved if resolved else (self.media_dir / str(file_path).lstrip("/"))

        if not p or not p.is_file():
            return None

        try:
            mtime = p.stat().st_mtime
            key = str(p)
            if key in self._duration_cache:
                cached_mtime, cached_dur = self._duration_cache[key]
                if cached_mtime == mtime:
                    return cached_dur

            dur = None
            if p.suffix.lower() in (".mp4", ".m4v", ".mov"):
                import struct
                file_size = p.stat().st_size
                with open(p, "rb") as f:
                    while f.tell() < file_size:
                        header = f.read(8)
                        if len(header) < 8:
                            break
                        size, atom_type = struct.unpack(">I4s", header)
                        if size == 1:
                            size_bytes = f.read(8)
                            if len(size_bytes) < 8:
                                break
                            size = struct.unpack(">Q", size_bytes)[0] - 8
                        elif size == 0:
                            size = file_size - f.tell() + 8

                        if atom_type == b"moov":
                            moov_bytes = f.read(max(0, size - 8))
                            idx = moov_bytes.find(b"mvhd")
                            if idx != -1:
                                mvhd_data = moov_bytes[idx + 4 :]
                                if len(mvhd_data) >= 20:
                                    version = mvhd_data[0]
                                    if version == 1 and len(mvhd_data) >= 32:
                                        timescale, duration = struct.unpack(">IQ", mvhd_data[20:32])
                                    else:
                                        timescale, duration = struct.unpack(">II", mvhd_data[12:20])
                                    if timescale > 0:
                                        dur = round(duration / timescale, 2)
                            break
                        else:
                            f.seek(max(0, size - 8), 1)

            if dur is not None:
                self._duration_cache[key] = (mtime, dur)
                return dur

        except Exception as e:
            logger.debug("Fout bij uitlezen duur van %s: %s", p, e)

        return None

    def _calculate_effect_duration(self, file_path: Union[str, Path], fallback: float = 15.0) -> float:
        """Berekent de effectieve effectduur met een kleine overlap (ongeveer 0.7s) voor een vloeiende overgang."""
        raw = self._get_media_duration(file_path)
        if raw and raw > 1.5:
            overlap_duration = max(2.0, round(raw - 0.7, 1))
            return min(overlap_duration, MAX_EFFECT_DURATION_SECONDS)
        return min(fallback, MAX_EFFECT_DURATION_SECONDS)

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
            from urllib.parse import quote
            web_url = f"/media/{quote(rel_to_media, safe='/')}"
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
        self.load_configuration()

        # 1. Handmatig geselecteerde achtergrond
        if self.active_background_file:
            exists, web_url = self._check_file_exists(self.active_background_file)
            if exists:
                name = Path(self.active_background_file).stem.replace("_", " ").replace("-", " ")
                return {
                    "file": self.active_background_file,
                    "name": name,
                    "web_url": web_url,
                    "file_exists": True,
                    "description": name,
                    "loop": True,
                    "muted": False,
                }

        # 2. Geconfigureerd achtergrondbestand uit effects.json
        file_path = self.background_config.get("file", "")
        exists, web_url = self._check_file_exists(file_path)

        # 3. Automatische fallback: eerste geldig videobestand in media/background/
        if not exists:
            bg_dir = self.media_dir / "background"
            if bg_dir.is_dir():
                candidates = [
                    f for f in sorted(bg_dir.iterdir())
                    if f.is_file() and f.suffix.lower() in ALLOWED_MEDIA_EXTENSIONS and f.stat().st_size > 0
                ]
                if candidates:
                    chosen = candidates[0]
                    file_path = f"media/background/{chosen.name}"
                    exists, web_url = self._check_file_exists(file_path)
                    logger.info("Achtergrond automatisch gedetecteerd: %s", file_path)

        name = Path(file_path).stem.replace("_", " ").replace("-", " ") if file_path else "Geen achtergrond"
        return {
            "file": file_path,
            "name": name,
            "web_url": web_url,
            "file_exists": exists,
            "description": self.background_config.get("description", name),
            "loop": self.background_config.get("loop", True),
            "muted": self.background_config.get("muted", False),
        }

    def get_background_list(self) -> List[Dict[str, Any]]:
        """Scant media/background/ en media/effects/ naar alle beschikbare achtergrondvideo's."""
        self.load_configuration()
        bg_dir = self.media_dir / "background"
        effects_dir = self.media_dir / "effects"
        current_bg = self.get_background()
        current_file = current_bg.get("file", "")

        results = []
        seen_filenames = set()

        def _add_candidates(directory: Path, folder_prefix: str, filter_prefix: bool = False):
            if not directory.is_dir():
                return
            for f in sorted(directory.iterdir()):
                if (f.is_file() and 
                    f.suffix.lower() in ALLOWED_MEDIA_EXTENSIONS and 
                    f.stat().st_size > 0 and
                    not f.name.endswith(".dwsupload") and
                    not f.name.endswith(".part") and
                    not f.name.endswith(".tmp")):
                    if filter_prefix and not (f.stem.lower().startswith("achtergrond") or f.stem.lower().startswith("background")):
                        continue
                    if f.name.lower() in seen_filenames:
                        continue
                    seen_filenames.add(f.name.lower())
                    rel_path = f"{folder_prefix}/{f.name}"
                    _, web_url = self._check_file_exists(rel_path)
                    name = f.stem.replace("_", " ").replace("-", " ")
                    results.append({
                        "id": f.stem,
                        "filename": f.name,
                        "name": name,
                        "file": rel_path,
                        "web_url": web_url,
                        "is_active": (rel_path == current_file or f.name in current_file),
                    })

        _add_candidates(bg_dir, "media/background", filter_prefix=False)
        _add_candidates(effects_dir, "media/effects", filter_prefix=True)
        return results

    def set_background(self, target: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Wisselt de actieve achtergrondvideo."""
        if not target:
            return False, "Geen bestand opgegeven.", None

        bg_dir = self.media_dir / "background"
        effects_dir = self.media_dir / "effects"
        clean_name = Path(target).name

        target_file = bg_dir / clean_name
        rel_path = f"media/background/{clean_name}"

        if not target_file.is_file() or target_file.stat().st_size == 0:
            target_file = effects_dir / clean_name
            rel_path = f"media/effects/{clean_name}"

        if not target_file.is_file() or target_file.stat().st_size == 0:
            return False, f"Achtergrondbestand '{clean_name}' niet gevonden.", None

        self.active_background_file = rel_path
        logger.info("Achtergrond handmatig gewijzigd naar: %s", rel_path)
        return True, f"Achtergrond gewijzigd naar '{clean_name}'", self.get_background()

    def _resolve_effect_file(self, item: Dict[str, Any]) -> Tuple[str, bool, Optional[str]]:
        """Zoekt het mediabestand voor een effect, inclusief automatische trefwoord-matching."""
        file_path = item.get("file", "")
        exists, web_url = self._check_file_exists(file_path)
        if exists:
            return file_path, True, web_url

        effects_dir = self.media_dir / "effects"
        if effects_dir.is_dir():
            effect_id = item.get("id", "").lower()
            keywords = [effect_id, effect_id.replace("_", " ")]
            if effect_id == "ghost_attack": keywords.extend(["ghost", "spook", "geest"])
            elif effect_id == "zombie": keywords.extend(["zombie", "undead"])
            elif effect_id == "creepy_eyes": keywords.extend(["eyes", "ogen", "creepy"])
            elif effect_id == "jumpscare": keywords.extend(["jump", "scare1", "jumpscare"])
            elif effect_id == "window_scratcher": keywords.extend(["scratch", "kras", "claw", "klauw"])

            candidates = [
                f for f in sorted(effects_dir.iterdir())
                if f.is_file() and f.suffix.lower() in ALLOWED_MEDIA_EXTENSIONS and f.stat().st_size > 0
                and not f.name.endswith(".dwsupload")
                and not f.name.endswith(".part")
                and not f.name.endswith(".tmp")
                and not f.stem.lower().startswith("achtergrond")
                and not f.stem.lower().startswith("background")
            ]
            for candidate in candidates:
                c_name = candidate.stem.lower()
                if any(kw in c_name for kw in keywords):
                    rel = f"media/effects/{candidate.name}"
                    c_exists, c_url = self._check_file_exists(rel)
                    if c_exists:
                        return rel, True, c_url

            # Als er slechts één effectbestand in media/effects/ staat en dit is jumpscare:
            if effect_id == "jumpscare" and len(candidates) == 1:
                rel = f"media/effects/{candidates[0].name}"
                c_exists, c_url = self._check_file_exists(rel)
                if c_exists:
                    return rel, True, c_url

        return file_path, False, None

    def _get_dynamic_effects(self) -> List[Dict[str, Any]]:
        """Detecteert extra effect-bestanden in media/effects/ die niet onder de standaardknoppen vallen."""
        effects_dir = self.media_dir / "effects"
        if not effects_dir.is_dir():
            return []

        import re
        claimed_filenames = set()
        for item in self.effects.values():
            fp, exists, _ = self._resolve_effect_file(item)
            if exists:
                claimed_filenames.add(Path(fp).name.lower())

        dynamic_list = []
        for f in sorted(effects_dir.iterdir()):
            if (f.is_file() and 
                f.suffix.lower() in ALLOWED_MEDIA_EXTENSIONS and 
                f.stat().st_size > 0 and 
                not f.name.endswith(".dwsupload") and 
                not f.name.endswith(".part") and
                not f.name.endswith(".tmp") and
                not f.stem.lower().startswith("achtergrond") and
                not f.stem.lower().startswith("background")):

                if f.name.lower() in claimed_filenames:
                    continue

                stem = f.stem
                effect_id = re.sub(r'[^a-zA-Z0-9_]', '_', stem).lower()
                if effect_id in self.effects:
                    effect_id = f"custom_{effect_id}"

                rel_path = f"media/effects/{f.name}"
                _, web_url = self._check_file_exists(rel_path)

                name_lower = stem.lower()
                if any(k in name_lower for k in ["scare", "jump", "schrik", "skull"]):
                    icon = "skull"
                elif any(k in name_lower for k in ["ghost", "spook", "geest"]):
                    icon = "ghost"
                elif any(k in name_lower for k in ["eye", "oog", "ogen"]):
                    icon = "eyes"
                elif any(k in name_lower for k in ["zombie", "dead"]):
                    icon = "zombie"
                elif any(k in name_lower for k in ["spider", "spin"]):
                    icon = "spider"
                elif any(k in name_lower for k in ["scratch", "kras", "claw"]):
                    icon = "scratch"
                else:
                    icon = "pumpkin"

                display_name = stem.replace("_", " ").replace("-", " ").title()
                duration = self._calculate_effect_duration(f, fallback=15.0)
                raw_duration = self._get_media_duration(f)
                dynamic_list.append({
                    "id": effect_id,
                    "name": display_name,
                    "file": rel_path,
                    "web_url": web_url,
                    "file_exists": True,
                    "configured": True,
                    "type": "fullscreen",
                    "has_audio": True,
                    "duration": duration,
                    "raw_duration": raw_duration,
                    "auto_return": True,
                    "description": f"Ontdekt effect ({f.name})",
                    "icon": icon,
                    "is_custom": True,
                })

        return dynamic_list

    def get_effects_list(self) -> List[Dict[str, Any]]:
        """Geeft alle effecten terug met hun configuratiestatus, inclusief dynamische effecten."""
        self.load_configuration()
        result = []
        for effect_id, item in self.effects.items():
            file_path, exists, web_url = self._resolve_effect_file(item)
            if exists:
                duration = self._calculate_effect_duration(file_path, fallback=float(item.get("duration", 10.0)))
                raw_duration = self._get_media_duration(file_path)
            else:
                duration = min(float(item.get("duration", 10.0)), MAX_EFFECT_DURATION_SECONDS)
                raw_duration = None
            result.append({
                "id": effect_id,
                "name": item.get("name", effect_id),
                "file": file_path,
                "web_url": web_url,
                "file_exists": exists,
                "configured": exists,
                "type": item.get("type", "overlay"),
                "has_audio": bool(item.get("has_audio", True)),
                "duration": duration,
                "raw_duration": raw_duration,
                "auto_return": bool(item.get("auto_return", True)),
                "description": item.get("description", ""),
                "icon": item.get("icon", "ghost"),
                "is_custom": False,
            })

        # Voeg dynamische effecten toe
        dynamic_effects = self._get_dynamic_effects()
        result.extend(dynamic_effects)
        return result

    def get_effect(self, effect_id: str) -> Optional[Dict[str, Any]]:
        """Haalt een specifiek effect op met actuele status."""
        self.load_configuration()
        item = self.effects.get(effect_id)
        if item:
            file_path, exists, web_url = self._resolve_effect_file(item)
            if exists:
                duration = self._calculate_effect_duration(file_path, fallback=float(item.get("duration", 10.0)))
                raw_duration = self._get_media_duration(file_path)
            else:
                duration = min(float(item.get("duration", 10.0)), MAX_EFFECT_DURATION_SECONDS)
                raw_duration = None
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
                "raw_duration": raw_duration,
                "auto_return": bool(item.get("auto_return", True)),
                "description": item.get("description", ""),
                "icon": item.get("icon", "ghost"),
                "is_custom": False,
            }

        # Zoek in dynamische effecten
        for dyn in self._get_dynamic_effects():
            if dyn["id"] == effect_id:
                return dyn

        return None

    def get_cooldown_remaining(self) -> float:
        """Berekent de resterende cooldowntijd in seconden."""
        if self.cooldown_seconds <= 0:
            return 0.0
        now = time.time()
        elapsed = now - self.last_effect_ended_at
        remaining = max(0.0, self.cooldown_seconds - elapsed)
        return round(remaining, 1)

    def can_trigger(self, force: bool = False) -> Tuple[bool, str, float]:
        """Controleert of een nieuw effect mag worden gestart."""
        if self.disabled:
            return False, "Effecten zijn tijdelijk uitgeschakeld.", 0.0

        if force:
            return True, "Gereed", 0.0

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

    def trigger_effect(self, effect_id: str, force: bool = False) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Start een effect indien gevalideerd."""
        if self.disabled:
            return False, "Effecten zijn tijdelijk uitgeschakeld.", None

        if not force:
            can, reason, remaining = self.can_trigger(force=False)
            if not can:
                return False, reason, None
        else:
            # Bij geforceerde/handmatige bediening vanaf de controller:
            # als er al een effect speelt, schakel direct naadloos over naar het nieuwe effect!
            if self.active_effect_id is not None:
                logger.info("Handmatige controller trigger: vorig effect %s direct overschrijven met %s", self.active_effect_id, effect_id)
                self.stop_effect()

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

    def trigger_random(self, force: bool = False) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Kiest en start een willekeurig geconfigureerd effect."""
        configured_effects = [e for e in self.get_effects_list() if e["configured"]]
        if not configured_effects:
            return False, "Geen enkel geconfigureerd effect met bestaand mediabestand gevonden.", None

        chosen = random.choice(configured_effects)
        return self.trigger_effect(chosen["id"], force=force)

    def get_sound_effects_list(self) -> List[Dict[str, Any]]:
        """Scant mediadirectories naar losse geluidseffecten (.mp3, .wav, .ogg, .aac)."""
        AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".aac", ".flac", ".m4a"}
        search_dirs = [
            (self.media_dir / "effects" / "music", "media/effects/music"),
            (self.media_dir / "music", "media/music"),
            (self.media_dir / "audio", "media/audio"),
            (self.media_dir / "effects", "media/effects"),
        ]

        results: List[Dict[str, Any]] = []
        seen_filenames = set()

        import re
        for folder_path, rel_prefix in search_dirs:
            if not folder_path.is_dir():
                continue

            for f in sorted(folder_path.iterdir()):
                if (f.is_file() and 
                    f.suffix.lower() in AUDIO_EXTENSIONS and 
                    f.stat().st_size > 0 and
                    not f.name.endswith(".dwsupload") and
                    not f.name.endswith(".part") and
                    not f.name.endswith(".tmp")):

                    lower_name = f.name.lower()
                    if lower_name in seen_filenames:
                        continue
                    seen_filenames.add(lower_name)

                    stem = f.stem
                    sound_id = f"sound_{re.sub(r'[^a-zA-Z0-9_]', '_', stem).lower()}"
                    rel_path = f"{rel_prefix}/{f.name}"
                    _, web_url = self._check_file_exists(rel_path)

                    # Bepaal passend icoon op basis van bestandsnaam
                    stem_lower = stem.lower()
                    if any(k in stem_lower for k in ["scream", "schreeuw"]):
                        icon = "😱"
                    elif any(k in stem_lower for k in ["thunder", "donder", "lightning", "bliksem"]):
                        icon = "⚡"
                    elif any(k in stem_lower for k in ["howl", "wolf"]):
                        icon = "🐺"
                    elif any(k in stem_lower for k in ["laugh", "lach"]):
                        icon = "😈"
                    elif any(k in stem_lower for k in ["bell", "klok", "chime"]):
                        icon = "🔔"
                    elif any(k in stem_lower for k in ["music", "theme", "muziek", "song"]):
                        icon = "🎵"
                    elif any(k in stem_lower for k in ["whisper", "fluister", "wind"]):
                        icon = "💨"
                    elif any(k in stem_lower for k in ["creak", "kraak", "door", "deur"]):
                        icon = "🚪"
                    elif any(k in stem_lower for k in ["chains", "ketting"]):
                        icon = "⛓️"
                    else:
                        icon = "🔊"

                    display_name = stem.replace("_", " ").replace("-", " ").title()

                    results.append({
                        "id": sound_id,
                        "name": display_name,
                        "filename": f.name,
                        "file": rel_path,
                        "web_url": web_url,
                        "icon": icon,
                        "file_exists": True,
                        "configured": True,
                    })

        return results

    def get_sound_effect(self, sound_id: str) -> Optional[Dict[str, Any]]:
        """Haalt een specifiek geluidseffect op."""
        clean_id = sound_id.lower().strip()
        for snd in self.get_sound_effects_list():
            if snd["id"].lower() == clean_id or snd["filename"].lower() == clean_id:
                return snd
        return None

    def trigger_sound_effect(self, sound_id: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Triggert een los geluidseffect zonder het actieve video-effect te onderbreken."""
        if self.disabled:
            return False, "Effecten zijn momenteel uitgeschakeld.", None

        sound = self.get_sound_effect(sound_id)
        if not sound:
            return False, f"Geluidseffect '{sound_id}' niet gevonden.", None

        payload = {
            "sound_id": sound["id"],
            "name": sound["name"],
            "filename": sound["filename"],
            "web_url": sound["web_url"],
            "volume": self.sound_volume if not self.muted else 0.0,
            "sound_volume": self.sound_volume,
            "muted": self.muted,
        }
        return True, "Geluidseffect gestart", payload

    def stop_effect(self) -> Dict[str, Any]:
        """Stopt direct het actieve effect en keert terug naar de achtergrond."""
        stopped_id = self.active_effect_id
        self.active_effect_id = None
        self.active_effect_started_at = None
        self.last_effect_ended_at = time.time()
        logger.info("Effect gestopt: %s.", stopped_id)
        return {
            "stopped_effect_id": stopped_id,
            "cooldown": self.cooldown_seconds,
        }

    def set_volume(self, volume: float) -> float:
        """Stelt het video audiovolume in tussen 0.0 en 1.0."""
        self.volume = max(0.0, min(1.0, float(volume)))
        return self.volume

    def set_sound_volume(self, volume: float) -> float:
        """Stelt het sound effects volume in tussen 0.0 en 1.0."""
        self.sound_volume = max(0.0, min(1.0, float(volume)))
        return self.sound_volume

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
            "sound_volume": self.sound_volume,
            "muted": self.muted,
            "cooldown_remaining": self.get_cooldown_remaining(),
            "can_trigger": can,
            "reason": reason,
        }


