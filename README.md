# 🎃 Halloween Projection Control

Een zelfstandige, robuuste en sfeervolle webapplicatie om tijdens Halloween draadloos en realtime raamprojecties, jumpscares en overlappende geluidseffecten aan te sturen op een Android TV-beamer via een mobiele smartphone-controller.

---

## 🌟 Belangrijkste Eigenschappen

- **Twee Gescheiden Interfaces**:
  - `/screen`: Volledig scherm, randloos, pure zwarte achtergrond (`#000000`), dual-layer videoplayer voor doorlopende achtergrondloops, naadloze overgangen en overlappende audio.
  - `/control`: Sfeervol donker bedieningspaneel in haunted house-stijl (zwart, pompoenoranje en bloedrood), geoptimaliseerd voor éénhandsbediening op smartphone met haptische vibratiefeedback.
- **Geen Kunstmatige Tijdslimieten of Wachttijden**:
  - **0 Seconden Cooldown**: Geen verplichte wachttijd tussen scares. Je drukt op de knop wanneer het jou uitkomt.
  - **Volledige Speelduur**: Scares worden niet kunstmatig afgekapt op een vaste limiet. De engine leest automatisch de werkelijke videoduur uit de MP4 metadata (`mvhd` atom) en speelt de video vloeiend uit.
  - **Directe Override**: Het aantikken van een nieuwe scare breekt het vorige effect direct af en start het nieuwe effect onmiddellijk (`force: true`).
- **Naadloze Dual-Layer Videoplayer (Zero Black Screen)**:
  - Twee parallelle achtergrondspelers met vloeiende CSS crossfades.
  - Bij een jumpscare blijft de achtergrond zichtbaar totdat het eerste frame van het schrikeffect daadwerkelijk decodeert en afspeelt.
  - Vloeiende overgang terug naar de achtergrond ca. 0.7s vóór het einde van het effect.
  - **Live Wisselen van Achtergrond**: Schakel op de controller direct tussen verschillende achtergrondloops in `media/background/`.
- **🔊 Overlappende Geluidseffecten (.mp3)**:
  - Speel losse geluidseffecten (screams, heksengelach, wolvengehuil, onweer) af via een speciale audio-pool.
  - **Polyfoon & Overlappend**: Het afspelen van een geluidseffect dempt of stopt de lopende achtergrondvideo of jumpscarevideo **niet**.
  - **Visuele Highlight & Toggle-to-Stop**: Spelende geluidseffecten lichten op de controller herkenbaar paars pulserend op. Een tweede klik op de pulserende knop stopt dat specifieke geluidseffect onmiddellijk.
  - **Automatische Synchronisatie**: Zodra een geluidseffect is afgelopen, dooft de knop automatisch op alle aangesloten telefoons.
- **🎚️ Gescheiden Volumeregeling**:
  - Twee onafhankelijke volumeschuifbalken op de mobiele controller:
    1. **Videovolume**: Voor de achtergrondvideo en video-jumpscares.
    2. **🎵 Geluidseffecten Volume (.mp3)**: Specifiek voor de losse audio-effecten.
- **📱 Flexibele Grid-indeling (3 of 4 Kolommen)**:
  - Schakel bovenaan het paneel direct tussen een 3-koloms of 4-koloms raster voor effectknoppen, zodat je op elk smartphonescherm alle knoppen overzichtelijk bij de hand hebt. De voorkeur wordt onthouden in `localStorage`.
- **🔍 Volledig Dynamische Mediabestandsdetectie**:
  - Plaats simpelweg een nieuw videobestand (`.mp4`, `.webm`) in `media/effects/` of `media/background/`, of een audiobestand (`.mp3`, `.wav`) in `media/effects/music/`.
  - Bestanden worden direct automatisch herkend en voorzien van een passende naam en Halloween-icoon, zonder handmatige configuratie van JSON-bestanden!
- **🛑 Betrouwbare Noodstop & Herverbinding**:
  - Directe noodstopknop (`Return to Background`) met dubbele WebSocket + HTTP REST fallback (`POST /api/stop`), die zowel actieve video's als spelende geluidseffecten per direct afbreekt.
  - Automatische WebSocket liveness-watchdog en wake-lock herstel bij ontwaken van je smartphone.
- **🏠 Homelab & Docker-Ready**:
  - Draait 100% lokaal in Docker / Portainer, geen cloudverbinding vereist.
  - Klaar voor Home Assistant automatiseringen via eenvoudige REST-commando's (bijv. gekoppeld aan een Zigbee deurbel of bewegingsmelder).

---

## 📁 Projectstructuur

```text
.
├── app/
│   ├── config.py           # Omgevingsvariabelen, padvalidatie en defaults
│   ├── effect_engine.py    # Effectengine, MP4 metadataparser, dynamische schijfscan & volume
│   ├── ws_manager.py       # WebSocket connection manager voor beamer en controllers
│   ├── main.py             # FastAPI app, REST routes en realtime WebSocket communicatie
│   ├── templates/
│   │   ├── index.html      # Startpagina en statusdashboard
│   │   ├── screen.html     # Projectiescherm voor beamer (dual-video + audio pool)
│   │   └── control.html    # Mobiele controller (grid, sliders, achtergrondkeuze)
│   └── static/
│       ├── css/            # Vormgeving (screen.css & control.css)
│       └── js/             # Client logica (screen.js & control.js)
├── config/
│   └── effects.json        # Basisconfiguratie en eventuele statische overrides
├── media/                  # Persistente opslag voor mediabestanden
│   ├── background/         # Achtergrondvideo's (bijv. Halloween Window Projection 2024.mp4)
│   ├── effects/            # Jumpscare en schrikvideo's (scare1.mp4, window_scratcher.mp4, etc.)
│   └── effects/music/      # Geluidseffecten (losse .mp3 bestanden zoals wolf howl, screams)
├── tests/                  # Geautomatiseerde testsuite (pytest, 34 tests)
├── Dockerfile              # Container image (Python 3.12-slim, non-root appuser)
├── compose.yaml            # Docker Compose stack met volume mounts
├── .env.example            # Voorbeeldconfiguratie
└── requirements.txt        # Python dependencies
```

---

## 🚀 Snelle Start met Docker Compose

### 1. Repository clonen of openen
```bash
git clone https://github.com/Stokstaart/ag_halloween.git
cd ag_halloween
```

### 2. Omgevingsbestand configureren (optioneel)
```bash
cp .env.example .env
```
Standaardwaarden in `.env`:
```env
PORT=8088
AUTH_TOKEN=                     # Laat leeg voor lokaal open LAN-gebruik
COOLDOWN_SECONDS=0.0            # 0.0 = direct vuren zonder wachttijd
MAX_EFFECT_DURATION_SECONDS=300.0  # Ruime veiligheidslimiet (5 min)
```

### 3. Container bouwen en starten
```bash
docker compose up -d --build
```

De applicatie is nu direct bereikbaar via:
- **Overzicht & Hub:** `http://<SERVER-IP>:8088/`
- **Projectiescherm (Beamer):** `http://<SERVER-IP>:8088/screen`
- **Mobiele Controller (Smartphone):** `http://<SERVER-IP>:8088/control`

---

## 📽️ Installatie & Gebruik op de Beamer (Android TV)

1. **Browser installeren:**
   - Installeer een Android TV-geschikte browser via de Google Play Store op de beamer. Aanbevolen:
     - **TV Bro** (open-source, uitstekende ondersteuning voor volledig scherm en afstandsbedieningen)
     - **BrowseHere** of **JioPages TV**
2. **Navigeer naar het scherm:**
   - Open de URL: `http://<SERVER-IP>:8088/screen`
3. **Eenmalige Audio Autoplay Unlock:**
   - Browsers blokkeren automatische audio tot de eerste interactie.
   - Bij het openen toont het scherm eenmalig een melding: *"Halloween Projectie Gereed - Druk op OK op je afstandsbediening of klik hier om audio en beeld te activeren."*
   - Druk op **OK** op de afstandsbediening. De beamer draait daarna de hele avond autonoom met geluid.
4. **Volledig scherm:**
   - Schakel fullscreen in via het browsermenu (in TV Bro bijv. via menu of toets 'F').
5. **Debug HUD (optioneel):**
   - Druk op toets **D** (of open met `?debug=1`) voor realtime weergave van FPS, actieve spelers en netwerkstatus.
6. **Sneltoets Noodstop:**
   - Druk op **Escape** of **S** op een aangesloten toetsenbord/afstandsbediening om direct terug te keren naar de achtergrond.

---

## 📱 Gebruik van de Mobiele Controller (`/control`)

Open `http://<SERVER-IP>:8088/control` op je telefoon op hetzelfde netwerk.

### Onderdelen van het bedieningspaneel:
1. **Verbindingsstatus & Noodstop**:
   - Statusindicator (`🟢 Beamer verbonden` / `🔴 Geen beamer verbonden`).
   - Grote rode **🛑 Noodstop (Return to Background)** knop die per direct video's en geluiden afbreekt.
2. **🎬 Achtergrond Selectie**:
   - Dropdown met alle gedetecteerde video's in `media/background/`.
   - Druk op **Wissel** om naadloos met een crossfade over te schakelen naar een andere achtergrondloop.
3. **💀 Jumpscares & Effecten**:
   - Raster met alle geconfigureerde en dynamisch gedetecteerde videoscares (Ghost Attack, Jumpscare, Window Scratcher, Scare 4, Scare 5, etc.).
   - **3 / 4 Kolommen Toggle**: Schakel tussen 3 of 4 knoppen per rij.
   - **Geen cooldown**: Druk op elk gewenst moment op een effect; een actief effect wordt direct vervangen door het nieuw gekozen effect.
   - **Voortgangsbalk**: Toont realtime de resterende seconden op basis van de werkelijke lengte van de video.
4. **🔊 Geluidseffecten (Overlap)**:
   - Knoppen voor losse `.mp3` effecten (Screams, Wolf Howl, Sirens, etc.).
   - **Paarse puls**: Knop pulseert zolang het geluid speelt.
   - **Stop toggle**: Klik nogmaals op een pulserende knop om uitsluitend dat geluidseffect direct te stoppen.
5. **🎚️ Onafhankelijke Volumeregeling**:
   - **Bovenste slider**: Videovolume (achtergrond + jumpscares) + Mute toggle.
   - **Onderste slider (paars)**: Geluidseffecten Volume (.mp3).

---

## 🎬 Mediabestanden Toevoegen

Plaats je eigen bestanden in de bijbehorende mappen (hot-reload, geen herstart nodig):

- **Achtergronden (`media/background/`):**
  - Bijv. `ambient_fog.mp4`, `Halloween Window Projection 2024.mp4`, `Achtergrond1.mp4`.
  - Video's loopen automatisch en zijn direct selecteerbaar in het dropdown-menu.
- **Jumpscares & Scares (`media/effects/`):**
  - Bijv. `scare1.mp4`, `scare4.mp4`, `window_scratcher.mp4`.
  - Worden automatisch herkend en getoond als effectknoppen.
- **Geluidseffecten (`media/effects/music/` of `media/audio/`):**
  - Bijv. `Wolf howl.mp3`, `SCREAM - Horror sound.mp3`, `thunder.mp3`.
  - Verschijnen automatisch als geluidseffectknoppen in de paarse sectie.

### Aanbevolen Codecs:
- **Video:** H.264 (AVC) met AAC audio en FastStart (`+faststart` moov atom).
- **Audio:** MP3 of AAC (Stereo, 44.1 of 48 kHz).
- *Tip:* Bestanden met moderne codecs zoals AV1 kunnen door Android TV decoders haperen; converteer ze eenvoudig naar H.264 via `ffmpeg -i input.mp4 -c:v libx264 -preset fast -crf 22 -c:a aac -movflags +faststart output.mp4`.

---

## 🔒 Beveiliging

1. **Lokaal Netwerk (Standaard):**
   - Met lege `AUTH_TOKEN` is het systeem direct bruikbaar op je thuisnetwerk. De controller toont een subtiele `⚠️ LAN Open` badge.
2. **Beveiligde Token Modus:**
   - Vul in `.env` een token in: `AUTH_TOKEN=mijnGeheimeToken123`.
   - Open de interfaces via `http://<SERVER-IP>:8088/control?token=mijnGeheimeToken123` en `http://<SERVER-IP>:8088/screen?token=mijnGeheimeToken123`.
3. **Path Traversal Bescherming:**
   - De backend valideert alle bestandspaden strikt; ongeldige bestandspaden en `..` worden categorisch geblokkeerd.

---

## 🏠 Optionele Home Assistant Integratie

Aansturing via Home Assistant verloopt eenvoudig via standaard REST-commando's:

### `configuration.yaml` in Home Assistant:
```yaml
rest_command:
  halloween_trigger_jumpscare:
    url: "http://<IP-SERVER>:8088/api/trigger"
    method: "POST"
    headers:
      Content-Type: "application/json"
    payload: '{"effect_id": "jumpscare", "force": true}'

  halloween_trigger_sound:
    url: "http://<IP-SERVER>:8088/api/sound"
    method: "POST"
    headers:
      Content-Type: "application/json"
    payload: '{"sound_id": "sound_wolf_howl"}'

  halloween_stop:
    url: "http://<IP-SERVER>:8088/api/stop"
    method: "POST"
```

---

## 🧪 Geautomatiseerde Tests

De testsuite valideert de REST API, EffectEngine, audio playback, cooldown overrides en WebSocket broadcasts:

```bash
# Virtuele omgeving activeren
source .venv/bin/activate

# 34 tests uitvoeren
pytest -v
```

---

## 📄 Portainer Stack Template

1. Ga in Portainer naar **Stacks** → **Add stack**.
2. Plak de inhoud van `compose.yaml`.
3. Klik op **Deploy the stack**.
