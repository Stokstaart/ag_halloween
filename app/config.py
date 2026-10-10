"""Configuratiebeheer voor Halloween Projection Control."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Laad .env bestand indien aanwezig
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Netwerk- en serverinstellingen
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8088"))
DEBUG = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")

# Beveiliging: optioneel authenticatietoken
# Indien leeg: onbeveiligde LAN-modus (duidelijk weergegeven in de UI)
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "").strip()

# Timing en effectparameters
COOLDOWN_SECONDS = float(os.getenv("COOLDOWN_SECONDS", "0.0"))
MAX_EFFECT_DURATION_SECONDS = float(os.getenv("MAX_EFFECT_DURATION_SECONDS", "300.0"))

# Paden
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", str(BASE_DIR / "media"))).resolve()
CONFIG_DIR = Path(os.getenv("CONFIG_DIR", str(BASE_DIR / "config"))).resolve()
CONFIG_FILE = CONFIG_DIR / "effects.json"

# Toegestane media-extensies
ALLOWED_MEDIA_EXTENSIONS = {
    ".mp4", ".webm", ".m4v", ".mp3", ".wav", ".aac", ".ogg"
}

# WebSocket instellingen
MAX_WS_MESSAGE_SIZE = 64 * 1024  # 64 KB
WS_PING_INTERVAL = 20.0          # Seconden
WS_PING_TIMEOUT = 10.0           # Seconden
