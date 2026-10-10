# 🎃 Halloween Projection Control

Een zelfstandige, robuuste en sfeervolle webapplicatie om tijdens een Halloweenfeest draadloos en op afstand raamprojecties en enge effecten te activeren op een Android-beamer via een smartphone.

---

## 🌟 Belangrijkste Eigenschappen

- **Twee Gescheiden Interfaces**:
  - `/screen`: Volledig scherm, clean, zwarte achtergrond, doorlopende achtergrondvideo (loop) en effectlaag.
  - `/control`: Sfeervol mobiel bedieningspaneel in haunted house-stijl (zwart met pompoenoranje en bloedrode accenten), ontworpen voor éénhandsbediening.
- **Realtijd Communicatie**: Lage latency via WebSockets met automatische reconnect en verbindingsindicatie.
- **Effectengine**:
  - Twee weergavemodi: `overlay` (zweeft over de achtergrond heen) en `fullscreen` (neemt tijdelijk het hele raam over).
  - Slimme cooldown (voorkomt spammen), maximale tijdsduur per effect en automatische terugkeer naar de achtergrond.
  - Directe noodstop (`Return to Background`).
  - Ondersteuning voor niet-geconfigureerde effecten (ontbrekende mediabestanden worden duidelijk getoond en niet fictief geactiveerd).
- **Lokaal & Homelab-Ready**:
  - Draait 100% lokaal in Docker / Portainer, geen afhankelijkheid van externe cloud of internet.
  - Klaar voor optionele Home Assistant integratie via eenvoudige REST-commando's (zonder verplichte afhankelijkheid).
  - Geoptimaliseerd voor beamerbrowsers op Android TV (inclusief audio-autoplay unlock procedure).

---

## 📁 Projectstructuur

```text
.
├── app/
│   ├── config.py           # Omgevingsvariabelen en padvalidatie
│   ├── effect_engine.py    # Logica voor effecten, cooldowns en mediachecks
│   ├── ws_manager.py       # WebSocket connection management
│   ├── main.py             # FastAPI app, REST routes en WS endpoint
│   ├── templates/
│   │   ├── index.html      # Startpagina en statusoverzicht
│   │   ├── screen.html     # Projectiescherm voor beamer
│   │   └── control.html    # Mobiele controller voor smartphone
│   └── static/
│       ├── css/            # Vormgeving (screen.css & control.css)
│       └── js/             # Client logica (screen.js & control.js)
├── config/
│   └── effects.json        # Effectendefinities en instellingen
├── media/                  # Persistente opslag voor videobestanden
│   ├── background/         # Doorlopende achtergrond (ambient_fog.mp4)
│   ├── effects/            # Effectvideo's (ghost_attack, zombie, etc.)
│   └── audio/              # Optionele losse audiobestanden
├── tests/                  # Geautomatiseerde testsuite (pytest)
├── Dockerfile              # Container image (Python 3.12-slim, non-root)
├── compose.yaml            # Docker Compose configuratie
├── .env.example            # Voorbeeldconfiguratie
└── requirements.txt        # Python dependencies
```

---

## 🚀 Snelle Start met Docker Compose

### 1. Repository clonen of map openen
```bash
cd /home/stokstaart/Desktop/ag_halloween
```

### 2. Omgevingsbestand configureren (optioneel)
```bash
cp .env.example .env
```
Pas indien gewenst `.env` aan:
```env
PORT=8088
AUTH_TOKEN=mijn_geheime_token   # Laat leeg voor onbeveiligde LAN-modus
COOLDOWN_SECONDS=3.0
MAX_EFFECT_DURATION_SECONDS=30.0
```

### 3. Container bouwen en starten
```bash
docker compose up -d --build
```

De applicatie is nu bereikbaar op:
- **Overzicht & Hub:** `http://<SERVER-IP>:8088/`
- **Projectiescherm (Beamer):** `http://<SERVER-IP>:8088/screen`
- **Mobiele Controller (Telefoon):** `http://<SERVER-IP>:8088/control`

---

## 📽️ Installatie & Gebruik op de  (Android TV)

1. **Browser installeren:**
   - Open de **Google Play Store** op de  beamer.
   - Installeer een geschikte browser voor Android TV. Aanbevolen browsers:
     - **TV Bro** (open-source, uitstekende fullscreen en afstandsbediening-navigatie)
     - **JioPages TV** of **BrowseHere**
2. **Navigeer naar het projectiescherm:**
   - Open in de browser: `http://<SERVER-IP>:8088/screen`
3. **Eenmalige Audio Unlock:**
   - Vanwege het autoplay-beleid van moderne webbrowsers mag een pagina niet automatisch audio afspelen totdat de gebruiker minstens één interactie heeft uitgevoerd.
   - Bij het openen verschijnt eenmalig de melding: *"Halloween Projectie Gereed - Druk op OK op je afstandsbediening of klik hier om audio en beeld te activeren."*
   - Druk eenmaal op **OK** (of tik op het scherm). De melding verdwijnt en de beamer blijft de hele avond autonoom draaien zonder verdere bediening.
4. **Volledig scherm (Fullscreen):**
   - Activeer fullscreen in de browser (in TV Bro kan dit via het menu of door op 'F' te drukken).
5. **Debug HUD (optioneel):**
   - Voeg `?debug=1` toe aan de URL of druk op de toets **D** op een aangesloten toetsenbord om realtime statistieken (FPS, WS status, actieve video) te bekijken.

---

## 📱 Gebruik van de Mobiele Controller

Open `http://<SERVER-IP>:8088/control` op je telefoon (verbonden met hetzelfde Wi-Fi netwerk).

Het paneel bevat minimaal de 8 vereiste functies:
1. **Ghost Attack** (👻) - Overlay: spookachtige verschijning over de mist.
2. **Zombie** (🧟) - Fullscreen: zombie slaat tegen het raam.
3. **Creepy Eyes** (👁️) - Overlay: gloeiende ogen in het donker.
4. **Jumpscare** (💀) - Fullscreen: plotselinge angstaanjagende schrikscène.
5. **Window Scratcher** (🐾) - Overlay: krassende klauwen over het raam.
6. **Random Scare** (🎲) - Kiest direct een willekeurig beschikbaar effect.
7. **Return to Background (Noodstop)** (🛑) - Stopt elk actief effect en keert direct terug naar de achtergrond.
8. **Mute / Unmute & Volumeregelaar** (🔊 / 🔇) - Regelt het audiovolume van de projectie op afstand.

> **Let op:** Knoppen waarvoor nog geen videobestand in `media/effects/` staat, worden automatisch aangeduid met een badge `GEEN BESTAND` en gedimd weergegeven. Wanneer je hierop tikt, geeft de app direct een duidelijke melding en wordt er geen onecht effect gestart.

---

## 🎬 Mediabestanden Toevoegen

Plaats je eigen MP4-bestanden in de volgende mappen:

- **Achtergrond:**
  `media/background/ambient_fog.mp4`
- **Effecten:**
  `media/effects/ghost_attack.mp4`
  `media/effects/zombie.mp4`
  `media/effects/creepy_eyes.mp4`
  `media/effects/jumpscare.mp4`
  `media/effects/window_scratcher.mp4`

### Aanbevolen Media Specificaties:
- **Container:** `.mp4`
- **Videocodec:** H.264 (AVC) - High Profile (optimaal compatibel met Android TV hardware-decoding).
- **Audiocodec:** AAC (Stereo, 44.1 of 48 kHz).
- **Resolutie:** 1920x1080 (Full HD) of 1280x720 (HD).
- **Framerate:** 24, 25 of 30 fps.
- **Transparantie / Overlays:** Voor overlapeffecten kun je MP4 video's met een zwarte achtergrond gebruiken (de app toont deze direct over de loop).

---

## 🔒 Beveiliging

1. **Vertrouwd Thuisnetwerk (Standaard):**
   - Als `AUTH_TOKEN` leeg wordt gelaten, werkt de app direct binnen je eigen LAN.
   - De controller toont dan een duidelijke waarschuwing: `⚠️ LAN Open` om te voorkomen dat er een vals gevoel van veiligheid ontstaat.
2. **Beveiligde Modus:**
   - Stel in `.env` een token in: `AUTH_TOKEN=mijnGeheimeToken123`.
   - Open de controller via: `http://<SERVER-IP>:8088/control?token=mijnGeheimeToken123`.
   - Open het scherm via: `http://<SERVER-IP>:8088/screen?token=mijnGeheimeToken123`.
   - *Let op:* Tokens in querystrings kunnen zichtbaar zijn in browsergeschiedenis en webserverlogs. Voor ultieme beveiliging bij externe toegang wordt een reverse proxy (zoals Nginx Proxy Manager, Traefik of Cloudflare Tunnel) met HTTPS aanbevolen. Stel de app **niet** ongeauthenticeerd publiek bloot aan het internet.
3. **Path Traversal Bescherming:**
   - De backend valideert strikt alle bestandspaden; willekeurige bestandspaden of `..` worden categorisch geweigerd. Alleen toegestane media-extensies binnen de `media/` directory worden ingelezen.

---

## 🏠 Optionele Home Assistant Integratie

De applicatie functioneert volledig zelfstandig, maar kan eenvoudig worden aangestuurd vanuit Home Assistant (bijvoorbeeld via een Zigbee bewegingsmelder, deurbel of tijdschakelaar).

Er worden bewust **geen** Home Assistant tokens in de frontend opgeslagen. De communicatie verloopt via Home Assistant's ingebouwde `rest_command`.

### Voorbeeld `configuration.yaml` in Home Assistant:

```yaml
rest_command:
  halloween_trigger_ghost:
    url: "http://<IP-VAN-HALLOWEEN-SERVER>:8088/api/trigger"
    method: "POST"
    headers:
      Content-Type: "application/json"
      # Indien AUTH_TOKEN is ingesteld:
      # Authorization: "Bearer JOUW_TOKEN"
    payload: '{"effect_id": "ghost_attack"}'

  halloween_trigger_jumpscare:
    url: "http://<IP-VAN-HALLOWEEN-SERVER>:8088/api/trigger"
    method: "POST"
    headers:
      Content-Type: "application/json"
    payload: '{"effect_id": "jumpscare"}'

  halloween_stop_effect:
    url: "http://<IP-VAN-HALLOWEEN-SERVER>:8088/api/stop"
    method: "POST"
```

### Voorbeeld Home Assistant Automatisering:

```yaml
alias: "Halloween Raam - Jumpscare bij Deurbel"
description: "Start direct jumpscare op het raam zodra er wordt aangebeld"
trigger:
  - platform: state
    entity_id: binary_sensor.smart_doorbell
    to: "on"
action:
  - service: rest_command.halloween_trigger_jumpscare
mode: single
```

---

## 🧪 Lokale Tests Uitvoeren

De testsuite dekt de REST API, de EffectEngine en WebSocket interacties:

```bash
# Virtuele omgeving activeren
source .venv/bin/activate

# Tests draaien
pytest -v
```

---

## 📄 Portainer Stack Template

Voor beheer via Portainer:
1. Ga in Portainer naar **Stacks** &rarr; **Add stack**.
2. Kies **Web editor** en plak de inhoud van `compose.yaml`.
3. Voeg eventueel environment variabelen toe (`PORT=8088`, etc.).
4. Klik op **Deploy the stack**.
