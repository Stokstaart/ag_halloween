"""Halloween Projection Control - Hoofdapplicatie (FastAPI)."""
import asyncio
import json
import logging
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Security,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app import __version__
from app.config import (
    AUTH_TOKEN,
    DEBUG,
    HOST,
    MAX_WS_MESSAGE_SIZE,
    MEDIA_DIR,
    PORT,
)
from app.effect_engine import EffectEngine
from app.media_optimizer import MediaOptimizer
from app.scheduler import AutoScareScheduler
from app.ws_manager import ConnectionManager

# Logging configuratie
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("halloween.server")

app = FastAPI(
    title="Halloween Projection Control",
    description="Zelfstandige webapplicatie voor raamprojectie-effecten via beamer.",
    version=__version__,
)

# Template en statische bestanden
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Mounts
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")

# Core services
engine = EffectEngine()
manager = ConnectionManager()
optimizer = MediaOptimizer(engine.media_dir)
active_watchdog_task: Optional[asyncio.Task] = None


def schedule_watchdog(eid: str, duration: float) -> None:
    """Start een waakhond-timer om vastgelopen status te resetten als de beamer onverhoopt uitvalt."""
    global active_watchdog_task
    if active_watchdog_task and not active_watchdog_task.done():
        active_watchdog_task.cancel()

    async def _watchdog():
        try:
            await asyncio.sleep(duration + 2.5)
            if engine.active_effect_id == eid:
                logger.warning("Watchdog: effect %s duur verstreken, forceren automatische reset.", eid)
                engine.stop_effect()
                await manager.broadcast_to_screens({"type": "stop_effect"})
                await manager.broadcast_to_controllers({"type": "effect_stopped", "effect_id": eid})
        except asyncio.CancelledError:
            pass

    active_watchdog_task = asyncio.create_task(_watchdog())


async def _on_autopilot_trigger(trigger_type: str):
    import random
    if trigger_type == "sound":
        sounds = engine.get_sound_effects_list()
        if sounds:
            snd = random.choice(sounds)
            success, reason, payload = engine.trigger_sound_effect(snd["id"])
            if success:
                await manager.broadcast_to_screens({
                    "type": "play_sound",
                    **payload,
                })
                await manager.broadcast_to_controllers({
                    "type": "sound_playing",
                    "sound_id": payload["sound_id"],
                    "is_auto": True,
                })
                return True, snd["name"]
    else:
        success, reason, payload = engine.trigger_random(force=True)
        if success:
            await manager.broadcast_to_screens({
                **payload,
                "display_mode": payload.get("type", "overlay"),
                "type": "play_effect",
            })
            await manager.broadcast_to_controllers({
                "type": "effect_active",
                "effect_id": payload["effect_id"],
                "name": payload["name"],
                "duration": payload["duration"],
                "is_auto": True,
            })
            schedule_watchdog(payload["effect_id"], payload["duration"])
            return True, payload["name"]
    return False, "Geen effect beschikbaar"


async def _on_autopilot_status(status_dict: dict):
    await manager.broadcast_to_controllers({
        "type": "autopilot_update",
        "autopilot": status_dict,
    })


scheduler = AutoScareScheduler(
    trigger_callback=_on_autopilot_trigger,
    broadcast_callback=_on_autopilot_status,
)


# Beveiliging: optionele Bearer / cookie / token auth
bearer_scheme = HTTPBearer(auto_error=False)


def is_authenticated(request: Request, token_param: Optional[str] = None) -> bool:
    """Controleert of een verzoek geauthenticeerd is via cookie, token of header."""
    if not AUTH_TOKEN:
        return True  # Onbeveiligde LAN-modus

    # 1. Cookie check (voor web-sessies)
    if request.cookies.get("auth_token") == AUTH_TOKEN:
        return True

    # 2. Query parameter (?token=...)
    if token_param and token_param == AUTH_TOKEN:
        return True
    req_token = request.query_params.get("token")
    if req_token and req_token == AUTH_TOKEN:
        return True

    # 3. Headers (voor curl of externe API-aanroepen)
    x_token = request.headers.get("X-Auth-Token")
    if x_token and x_token == AUTH_TOKEN:
        return True

    auth_hdr = request.headers.get("Authorization", "")
    if auth_hdr.startswith("Bearer ") and auth_hdr[7:].strip() == AUTH_TOKEN:
        return True

    return False


def verify_token(
    request: Request,
    auth_header: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    token_param: Optional[str] = Query(None, alias="token"),
) -> bool:
    """Valideert toegangstoken voor REST endpoints indien AUTH_TOKEN geconfigureerd is."""
    if not AUTH_TOKEN:
        return True

    if is_authenticated(request, token_param):
        return True

    if auth_header and auth_header.credentials == AUTH_TOKEN:
        return True

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Ongeldig of ontbrekend authenticatietoken.",
        headers={"WWW-Authenticate": "Bearer"},
    )


# Pydantic models voor REST endpoints
class TriggerRequest(BaseModel):
    effect_id: str = Field(..., description="Unieke ID van het af te spelen effect")
    force: Optional[bool] = Field(False, description="Overschrijf actief effect of cooldown direct")


class VolumeRequest(BaseModel):
    volume: Optional[float] = Field(None, ge=0.0, le=1.0, description="Algemeen of achtergrond volume")
    bg_volume: Optional[float] = Field(None, ge=0.0, le=1.0, description="Enkel achtergrondvideo volume")
    scare_volume: Optional[float] = Field(None, ge=0.0, le=1.0, description="Scares én sound effects volume")
    sound_volume: Optional[float] = Field(None, ge=0.0, le=1.0, description="Sound effects volume compatibiliteit")
    muted: Optional[bool] = Field(None, description="Audio dempen of activeren")


class AutopilotRequest(BaseModel):
    enabled: Optional[bool] = Field(None, description="Autopilot in- of uitschakelen")
    min_minutes: Optional[float] = Field(None, ge=0.1, le=60.0, description="Minimaal interval in minuten")
    max_minutes: Optional[float] = Field(None, ge=0.1, le=120.0, description="Maximaal interval in minuten")
    mode: Optional[str] = Field(None, description="'both', 'jumpscare', of 'sound'")



class DisableRequest(BaseModel):
    disabled: bool = Field(..., description="Effecten tijdelijk uitschakelen")


class BackgroundRequest(BaseModel):
    file: Optional[str] = Field(None, description="Bestandsnaam of pad van de achtergrondvideo")
    filename: Optional[str] = Field(None, description="Alternatieve bestandsnaam")


class SoundRequest(BaseModel):
    sound_id: str = Field(..., description="ID of bestandsnaam van het geluidseffect")


# ==========================================
# HTML Views
# ==========================================

@app.get("/login", response_class=HTMLResponse)
async def view_login(request: Request, next: Optional[str] = "/control", token: Optional[str] = None):
    """Toont het inlogscherm (of stuurt door indien al ingelogd)."""
    if not AUTH_TOKEN or is_authenticated(request, token):
        target = next or "/control"
        return RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "next_url": next or "/control",
            "error": None,
        },
    )


@app.post("/login")
async def handle_login(request: Request):
    """Verwerkt het ingevoerde wachtwoord en zet een beveiligde 30-dagen cookie."""
    next_url = "/control"
    password = ""

    # Ondersteun zowel gewone HTML-form submit als JSON-post zonder externe multipart-libs
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            password = str(body.get("password", "")).strip()
            next_url = str(body.get("next", "/control")).strip() or "/control"
        except Exception:
            pass
    else:
        try:
            raw_body = await request.body()
            form_data = urllib.parse.parse_qs(raw_body.decode("utf-8"))
            password = form_data.get("password", [""])[0].strip()
            next_url = form_data.get("next", ["/control"])[0].strip() or "/control"
        except Exception:
            pass

    if not AUTH_TOKEN or password == AUTH_TOKEN:
        response = RedirectResponse(url=next_url, status_code=status.HTTP_303_SEE_OTHER)
        if AUTH_TOKEN:
            response.set_cookie(
                key="auth_token",
                value=AUTH_TOKEN,
                max_age=30 * 24 * 3600,  # 30 dagen onthouden
                httponly=True,
                samesite="lax",
                secure=False,  # Werkt via zowel HTTP lokaal als HTTPS reverse proxy
            )
        return response

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "next_url": next_url,
            "error": "Onjuist wachtwoord. Probeer het opnieuw.",
        },
        status_code=status.HTTP_401_UNAUTHORIZED,
    )


@app.get("/logout")
async def handle_logout():
    """Logt de gebruiker uit en verwijdert de auth cookie."""
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key="auth_token")
    return response


@app.get("/", response_class=HTMLResponse)
async def view_index(request: Request, token: Optional[str] = None):
    """Startpagina met snelkoppelingen naar controller en projectiescherm."""
    auth_configured = bool(AUTH_TOKEN)
    token_valid = is_authenticated(request, token)

    if auth_configured and not token_valid:
        return RedirectResponse(url="/login?next=/", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "token": token or request.cookies.get("auth_token", ""),
            "auth_configured": auth_configured,
            "token_valid": token_valid,
            "screen_count": len(manager.screen_connections),
            "effects": engine.get_effects_list(),
            "background": engine.get_background(),
        },
    )


@app.get("/screen", response_class=HTMLResponse)
async def view_screen(request: Request, token: Optional[str] = None, debug: Optional[str] = None):
    """Projectiescherm interface voor weergave op de beamer."""
    if AUTH_TOKEN and not is_authenticated(request, token):
        return RedirectResponse(url="/login?next=/screen", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        "screen.html",
        {
            "request": request,
            "token": token or request.cookies.get("auth_token", ""),
            "debug": debug == "1" or DEBUG,
            "background": engine.get_background(),
        },
    )


@app.get("/control", response_class=HTMLResponse)
async def view_control(request: Request, token: Optional[str] = None):
    """Mobiele controller interface voor smartphone."""
    if AUTH_TOKEN and not is_authenticated(request, token):
        return RedirectResponse(url="/login?next=/control", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        "control.html",
        {
            "request": request,
            "token": token or request.cookies.get("auth_token", ""),
            "auth_configured": bool(AUTH_TOKEN),
            "status": engine.get_status(),
            "effects": engine.get_effects_list(only_configured=True),
            "sounds": engine.get_sound_effects_list(),
            "background": engine.get_background(),
            "autopilot": scheduler.get_status(),
            "media_health": optimizer.get_health_report(),
        },
    )



# ==========================================
# REST API Endpoints
# ==========================================

@app.get("/health")
@app.get("/api/health")
async def health_check():
    """Lichtgewicht health check endpoint voor Docker en container orchestrators."""
    return {"status": "ok"}


@app.get("/api/status")
async def api_status(authenticated: bool = Depends(verify_token)):
    """Geeft de actuele status van de server, verbindingen en effectengine."""
    stats = manager.get_stats()
    engine_status = engine.get_status()
    bg = engine.get_background()
    return {
        "status": "online",
        "version": __version__,
        "auth_configured": bool(AUTH_TOKEN),
        "screens_connected": stats["screen_count"],
        "controllers_connected": stats["controller_count"],
        "background_ready": bg["file_exists"],
        "engine": engine_status,
        "autopilot": scheduler.get_status(),
        "media_health": optimizer.get_health_report(),
    }


@app.get("/api/effects")
async def api_effects(configured_only: bool = False, authenticated: bool = Depends(verify_token)):
    """Haalt de actuele lijst van effecten, geluidseffecten en achtergrondconfiguratie op."""
    return {
        "background": engine.get_background(),
        "backgrounds": engine.get_background_list(),
        "effects": engine.get_effects_list(only_configured=configured_only),
        "sounds": engine.get_sound_effects_list(),
    }


@app.get("/api/sounds")
async def api_sounds(authenticated: bool = Depends(verify_token)):
    """Haalt alle beschikbare geluidseffecten (.mp3, .wav, etc.) op."""
    return {
        "sounds": engine.get_sound_effects_list(),
    }


@app.post("/api/sound")
async def api_play_sound(payload: SoundRequest, authenticated: bool = Depends(verify_token)):
    """Speelt een los geluidseffect af op de beamer(s) overlappend met de video."""
    success, reason, sound_payload = engine.trigger_sound_effect(payload.sound_id)
    if not success:
        raise HTTPException(status_code=400, detail=reason)

    # Broadcast naar alle beamer schermen om overlappend af te spelen
    await manager.broadcast_to_screens({
        "type": "play_sound",
        **sound_payload,
    })

    # Broadcast naar controllers ter notificatie
    await manager.broadcast_to_controllers({
        "type": "sound_triggered",
        **sound_payload,
    })

    return {"success": True, "message": "Geluidseffect gestart", "sound": sound_payload}


@app.post("/api/sound/stop")
async def api_stop_sound(payload: SoundRequest, authenticated: bool = Depends(verify_token)):
    """Stopt een specifiek geluidseffect op de beamer(s)."""
    sound_id = payload.sound_id
    # Broadcast stop instructie naar alle beamers
    await manager.broadcast_to_screens({
        "type": "stop_sound",
        "sound_id": sound_id,
    })

    # Broadcast naar controllers
    await manager.broadcast_to_controllers({
        "type": "sound_stopped",
        "sound_id": sound_id,
    })

    return {"success": True, "message": "Geluidseffect gestopt", "sound_id": sound_id}




@app.get("/api/backgrounds")
async def api_backgrounds(authenticated: bool = Depends(verify_token)):
    """Haalt alle beschikbare achtergrondvideo's op."""
    return {
        "current": engine.get_background(),
        "backgrounds": engine.get_background_list(),
    }


@app.post("/api/background")
async def api_set_background(payload: BackgroundRequest, authenticated: bool = Depends(verify_token)):
    """Wisselt de actieve achtergrondvideo."""
    target = payload.file or payload.filename
    if not target:
        raise HTTPException(status_code=400, detail="Geen bestandsnaam opgegeven.")

    success, msg, bg = engine.set_background(target)
    if not success:
        raise HTTPException(status_code=400, detail=msg)

    # Broadcast naar alle schermen
    await manager.broadcast_to_screens({
        "type": "background_update",
        "background": bg,
    })

    # Broadcast naar controllers
    await manager.broadcast_to_controllers({
        "type": "background_selected",
        "background": bg,
        "backgrounds": engine.get_background_list(),
    })

    return {"success": True, "message": msg, "background": bg}


@app.post("/api/trigger")
async def api_trigger(payload: TriggerRequest, authenticated: bool = Depends(verify_token)):
    """Triggert een effect via REST."""
    success, reason, effect_payload = engine.trigger_effect(payload.effect_id, force=bool(payload.force))
    if not success:
        raise HTTPException(status_code=400, detail=reason)

    # Broadcast naar alle schermen
    await manager.broadcast_to_screens({
        **effect_payload,
        "display_mode": effect_payload.get("type", "overlay"),
        "type": "play_effect",
    })

    # Update controllers
    await manager.broadcast_to_controllers({
        "type": "effect_active",
        "effect_id": effect_payload["effect_id"],
        "name": effect_payload["name"],
        "duration": effect_payload["duration"],
    })

    # Start waakhond
    schedule_watchdog(effect_payload["effect_id"], effect_payload["duration"])

    return {"success": True, "message": "Effect geactiveerd", "effect": effect_payload}


@app.post("/api/stop")
async def api_stop(authenticated: bool = Depends(verify_token)):
    """Stopt direct het actieve effect en keert terug naar de achtergrond."""
    global active_watchdog_task
    if active_watchdog_task and not active_watchdog_task.done():
        active_watchdog_task.cancel()

    result = engine.stop_effect()
    await manager.broadcast_to_screens({"type": "stop_effect"})
    await manager.broadcast_to_controllers({"type": "effect_stopped"})
    return {"success": True, "message": "Teruggekeerd naar achtergrond", **result}


@app.post("/api/effect-ended")
async def api_effect_ended(request: Request, authenticated: bool = Depends(verify_token)):
    """Meldt voltooiing van effect via HTTP fallback vanaf het beamer scherm."""
    global active_watchdog_task
    if active_watchdog_task and not active_watchdog_task.done():
        active_watchdog_task.cancel()

    finished_id = engine.active_effect_id
    try:
        body = await request.json()
        if isinstance(body, dict) and body.get("effect_id"):
            finished_id = body.get("effect_id")
    except Exception:
        pass

    logger.info("Projectiescherm meldt voltooiing via HTTP fallback: %s", finished_id)
    result = engine.stop_effect()
    await manager.broadcast_to_controllers({"type": "effect_stopped", "effect_id": finished_id})
    return {"success": True, "message": "Effect beëindigd", **result}


@app.post("/api/volume")
async def api_volume(payload: VolumeRequest, authenticated: bool = Depends(verify_token)):
    """Past achtergrondvideo volume, scares & sound volume of dempstatus aan."""
    if payload.bg_volume is not None:
        engine.set_bg_volume(payload.bg_volume)
    elif payload.volume is not None:
        engine.set_bg_volume(payload.volume)

    if payload.scare_volume is not None:
        engine.set_scare_volume(payload.scare_volume)
    elif payload.sound_volume is not None:
        engine.set_scare_volume(payload.sound_volume)

    if payload.muted is not None:
        engine.set_muted(payload.muted)

    status_update = {
        "type": "volume_update",
        "volume": engine.bg_volume,
        "bg_volume": engine.bg_volume,
        "scare_volume": engine.scare_volume,
        "sound_volume": engine.scare_volume,
        "muted": engine.muted,
    }
    await manager.broadcast_all(status_update)
    return {
        "success": True,
        "volume": engine.bg_volume,
        "bg_volume": engine.bg_volume,
        "scare_volume": engine.scare_volume,
        "sound_volume": engine.scare_volume,
        "muted": engine.muted,
    }


@app.get("/api/media/health")
async def api_media_health(authenticated: bool = Depends(verify_token)):
    """Haalt de gezondheidsstatus op van alle videobestanden (codecs en FastStart)."""
    return optimizer.get_health_report()


@app.post("/api/media/optimize")
async def api_media_optimize(background_tasks: BackgroundTasks, authenticated: bool = Depends(verify_token)):
    """Start automatische optimalisatie (FastStart en H.264 conversie) in de achtergrond."""
    if optimizer.is_running:
        return {"success": False, "message": "Optimalisatie is al bezig."}

    async def _progress_cb(status_dict: dict):
        await manager.broadcast_to_controllers({
            "type": "media_optimize_progress",
            "optimize_status": status_dict,
        })

    async def _run_opt():
        res = await optimizer.optimize_all(progress_callback=_progress_cb)
        await manager.broadcast_to_controllers({
            "type": "media_optimize_done",
            "result": res,
            "media_health": optimizer.get_health_report(),
        })

    background_tasks.add_task(_run_opt)
    return {"success": True, "message": "Optimalisatietaak gestart op de achtergrond."}


@app.get("/api/autopilot")
async def api_get_autopilot(authenticated: bool = Depends(verify_token)):
    """Geeft de actuele status en timer van de autopilot scheduler."""
    return scheduler.get_status()


@app.post("/api/autopilot")
async def api_set_autopilot(payload: AutopilotRequest, authenticated: bool = Depends(verify_token)):
    """Stelt de autopilot in of schakelt deze in/uit."""
    if payload.min_minutes is not None or payload.max_minutes is not None or payload.mode is not None:
        scheduler.set_config(
            min_minutes=payload.min_minutes,
            max_minutes=payload.max_minutes,
            mode=payload.mode,
        )
    if payload.enabled is not None:
        scheduler.set_enabled(payload.enabled)

    status_data = scheduler.get_status()
    await manager.broadcast_to_controllers({
        "type": "autopilot_update",
        "autopilot": status_data,
    })
    return status_data



@app.post("/api/disable")
async def api_disable(payload: DisableRequest, authenticated: bool = Depends(verify_token)):
    """Schakelt effecten tijdelijk uit of weer in."""
    engine.set_disabled(payload.disabled)
    await manager.broadcast_to_controllers({
        "type": "disabled_update",
        "disabled": engine.disabled,
    })
    return {"success": True, "disabled": engine.disabled}


# ==========================================
# WebSocket Endpoint
# ==========================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Realtime communicatie tussen controller, server en beamer."""
    # Check optioneel token via query params of cookie
    query_token = websocket.query_params.get("token", "")
    cookie_token = websocket.cookies.get("auth_token", "")
    client_token = query_token or cookie_token
    if AUTH_TOKEN and client_token != AUTH_TOKEN:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("WebSocket verbinding geweigerd: ongeldig token.")
        return

    role = websocket.query_params.get("role", "control").lower()

    if role == "screen":
        await manager.connect_screen(websocket)
        # Stuur initiële configuratie naar beamer
        bg = engine.get_background()
        await manager.send_personal(websocket, {
            "type": "init",
            "background": bg,
            "volume": engine.bg_volume,
            "bg_volume": engine.bg_volume,
            "scare_volume": engine.scare_volume,
            "sound_volume": engine.scare_volume,
            "muted": engine.muted,
        })
    else:
        await manager.connect_controller(websocket)
        await manager.send_personal(websocket, {
            "type": "init",
            "status": engine.get_status(),
            "effects": engine.get_effects_list(only_configured=True),
            "sounds": engine.get_sound_effects_list(),
            "background": engine.get_background(),
            "backgrounds": engine.get_background_list(),
            "screen_count": len(manager.screen_connections),
            "autopilot": scheduler.get_status(),
            "media_health": optimizer.get_health_report(),
        })


    try:
        while True:
            raw_data = await websocket.receive_text()

            # Beveiliging: limiet op berichtgrootte
            if len(raw_data) > MAX_WS_MESSAGE_SIZE:
                logger.warning("WebSocket bericht overschrijdt maximale grootte (%d bytes)", len(raw_data))
                await manager.send_personal(websocket, {
                    "type": "error",
                    "message": "Bericht overschrijdt maximale toegestane grootte.",
                })
                continue

            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                await manager.send_personal(websocket, {"type": "error", "message": "Ongeldig JSON-formaat."})
                continue

            action = data.get("action") or data.get("type")

            # --- Signalen vanaf het projectiescherm ---
            if role == "screen":
                if action == "effect_ended":
                    effect_id = data.get("effect_id")
                    logger.info("Projectiescherm meldt voltooiing van effect: %s", effect_id)
                    engine.stop_effect()
                    await manager.broadcast_to_controllers({"type": "effect_stopped", "effect_id": effect_id})

                elif action == "effect_error":
                    effect_id = data.get("effect_id")
                    err_msg = data.get("message", "Fout bij afspelen van video op scherm")
                    logger.error("Afspeelfout op scherm voor effect %s: %s", effect_id, err_msg)
                    engine.stop_effect()
                    await manager.broadcast_to_controllers({
                        "type": "playback_error",
                        "effect_id": effect_id,
                        "message": err_msg,
                    })

                elif action == "sound_ended":
                    sound_id = data.get("sound_id")
                    logger.info("Projectiescherm meldt voltooiing van geluidseffect: %s", sound_id)
                    await manager.broadcast_to_controllers({"type": "sound_stopped", "sound_id": sound_id})

                elif action == "screen_ping":
                    await manager.send_personal(websocket, {"type": "screen_pong"})


            # --- Commando's vanaf de mobiele controller ---
            else:
                if action == "trigger":
                    effect_id = data.get("effect_id")
                    force = data.get("force", True)
                    logger.info("Trigger commando ontvangen van controller voor: %s (force=%s)", effect_id, force)
                    success, reason, effect_payload = engine.trigger_effect(effect_id, force=force)
                    if success:
                        logger.info("Effect %s gevalideerd, broadcasting naar beamers...", effect_id)
                        # Bevestiging aan controller
                        await manager.send_personal(websocket, {
                            "type": "trigger_ack",
                            "success": True,
                            "effect_id": effect_id,
                            "name": effect_payload["name"],
                        })
                        # Commando naar alle beamers
                        await manager.broadcast_to_screens({
                            **effect_payload,
                            "display_mode": effect_payload.get("type", "overlay"),
                            "type": "play_effect",
                        })
                        # Status naar alle controllers
                        await manager.broadcast_to_controllers({
                            "type": "effect_active",
                            "effect_id": effect_payload["effect_id"],
                            "name": effect_payload["name"],
                            "duration": effect_payload["duration"],
                        })
                        # Waakhond starten
                        schedule_watchdog(effect_payload["effect_id"], effect_payload["duration"])
                    else:
                        logger.warning("Trigger voor %s geweigerd: %s", effect_id, reason)
                        await manager.send_personal(websocket, {
                            "type": "trigger_ack",
                            "success": False,
                            "effect_id": effect_id,
                            "reason": reason,
                        })

                elif action == "trigger_random":
                    force = data.get("force", True)
                    success, reason, effect_payload = engine.trigger_random(force=force)
                    if success:
                        await manager.send_personal(websocket, {
                            "type": "trigger_ack",
                            "success": True,
                            "effect_id": effect_payload["effect_id"],
                            "name": effect_payload["name"],
                            "is_random": True,
                        })
                        await manager.broadcast_to_screens({
                            **effect_payload,
                            "display_mode": effect_payload.get("type", "overlay"),
                            "type": "play_effect",
                        })
                        await manager.broadcast_to_controllers({
                            "type": "effect_active",
                            "effect_id": effect_payload["effect_id"],
                            "name": effect_payload["name"],
                            "duration": effect_payload["duration"],
                        })
                        # Waakhond starten
                        schedule_watchdog(effect_payload["effect_id"], effect_payload["duration"])
                    else:
                        await manager.send_personal(websocket, {
                            "type": "trigger_ack",
                            "success": False,
                            "reason": reason,
                        })

                elif action in ("play_sound", "trigger_sound"):
                    sound_id = data.get("sound_id")
                    logger.info("Geluidseffect commando ontvangen: %s", sound_id)
                    success, reason, sound_payload = engine.trigger_sound_effect(sound_id)
                    if success:
                        await manager.send_personal(websocket, {
                            "type": "sound_ack",
                            "success": True,
                            "sound_id": sound_payload["sound_id"],
                            "name": sound_payload["name"],
                        })
                        await manager.broadcast_to_screens({
                            "type": "play_sound",
                            **sound_payload,
                        })
                        await manager.broadcast_to_controllers({
                            "type": "sound_triggered",
                            **sound_payload,
                        })
                    else:
                        logger.warning("Geluidseffect geweigerd: %s", reason)
                        await manager.send_personal(websocket, {
                            "type": "sound_ack",
                            "success": False,
                            "sound_id": sound_id,
                            "reason": reason,
                        })

                elif action in ("stop_sound", "sound_stop"):
                    sound_id = data.get("sound_id")
                    logger.info("Controller vraagt stoppen van geluidseffect: %s", sound_id)
                    await manager.broadcast_to_screens({
                        "type": "stop_sound",
                        "sound_id": sound_id,
                    })
                    await manager.broadcast_to_controllers({
                        "type": "sound_stopped",
                        "sound_id": sound_id,
                    })

                elif action in ("stop", "return_to_background"):

                    result = engine.stop_effect()
                    await manager.broadcast_to_screens({"type": "stop_effect"})
                    await manager.broadcast_to_controllers({"type": "effect_stopped"})

                elif action == "set_bg_volume":
                    vol = data.get("volume") if data.get("volume") is not None else data.get("bg_volume", 0.8)
                    engine.set_bg_volume(vol)
                    await manager.broadcast_all({
                        "type": "volume_update",
                        "volume": engine.bg_volume,
                        "bg_volume": engine.bg_volume,
                        "scare_volume": engine.scare_volume,
                        "sound_volume": engine.scare_volume,
                        "muted": engine.muted,
                    })

                elif action == "set_scare_volume":
                    vol = data.get("volume") if data.get("volume") is not None else data.get("scare_volume", 1.0)
                    engine.set_scare_volume(vol)
                    await manager.broadcast_all({
                        "type": "volume_update",
                        "volume": engine.bg_volume,
                        "bg_volume": engine.bg_volume,
                        "scare_volume": engine.scare_volume,
                        "sound_volume": engine.scare_volume,
                        "muted": engine.muted,
                    })

                elif action == "set_volume":
                    vol = data.get("volume", 0.8)
                    engine.set_bg_volume(vol)
                    await manager.broadcast_all({
                        "type": "volume_update",
                        "volume": engine.bg_volume,
                        "bg_volume": engine.bg_volume,
                        "scare_volume": engine.scare_volume,
                        "sound_volume": engine.scare_volume,
                        "muted": engine.muted,
                    })

                elif action == "set_sound_volume":
                    vol = data.get("volume") if data.get("volume") is not None else data.get("sound_volume", 1.0)
                    engine.set_scare_volume(vol)
                    await manager.broadcast_all({
                        "type": "volume_update",
                        "volume": engine.bg_volume,
                        "bg_volume": engine.bg_volume,
                        "scare_volume": engine.scare_volume,
                        "sound_volume": engine.scare_volume,
                        "muted": engine.muted,
                    })

                elif action == "toggle_mute":
                    muted = engine.toggle_muted()
                    await manager.broadcast_all({
                        "type": "volume_update",
                        "volume": engine.bg_volume,
                        "bg_volume": engine.bg_volume,
                        "scare_volume": engine.scare_volume,
                        "sound_volume": engine.scare_volume,
                        "muted": engine.muted,
                    })

                elif action == "toggle_autopilot":
                    target_state = data.get("enabled")
                    if target_state is None:
                        target_state = not scheduler.enabled
                    scheduler.set_enabled(bool(target_state))
                    await manager.broadcast_to_controllers({
                        "type": "autopilot_update",
                        "autopilot": scheduler.get_status(),
                    })

                elif action == "set_autopilot_config":
                    scheduler.set_config(
                        min_minutes=data.get("min_minutes"),
                        max_minutes=data.get("max_minutes"),
                        mode=data.get("mode"),
                    )
                    await manager.broadcast_to_controllers({
                        "type": "autopilot_update",
                        "autopilot": scheduler.get_status(),
                    })

                elif action == "optimize_media":
                    async def _run_ws_opt():
                        async def _prog_cb(status_dict):
                            await manager.broadcast_to_controllers({
                                "type": "media_optimize_progress",
                                "optimize_status": status_dict,
                            })
                        res = await optimizer.optimize_all(progress_callback=_prog_cb)
                        await manager.broadcast_to_controllers({
                            "type": "media_optimize_done",
                            "result": res,
                            "media_health": optimizer.get_health_report(),
                        })
                    asyncio.create_task(_run_ws_opt())


                elif action == "set_disabled":
                    val = bool(data.get("disabled", False))
                    engine.set_disabled(val)
                    await manager.broadcast_to_controllers({
                        "type": "disabled_update",
                        "disabled": engine.disabled,
                    })

                elif action in ("set_background", "change_background"):
                    target = data.get("file") or data.get("filename") or data.get("background")
                    if target:
                        success, reason, bg = engine.set_background(target)
                        if success:
                            await manager.broadcast_to_screens({
                                "type": "background_update",
                                "background": bg,
                            })
                            await manager.broadcast_to_controllers({
                                "type": "background_selected",
                                "background": bg,
                                "backgrounds": engine.get_background_list(),
                            })
                            await manager.send_personal(websocket, {
                                "type": "background_ack",
                                "success": True,
                                "message": reason,
                                "background": bg,
                            })
                        else:
                            await manager.send_personal(websocket, {
                                "type": "background_ack",
                                "success": False,
                                "reason": reason,
                            })

                elif action == "ping":
                    await manager.send_personal(websocket, {"type": "pong"})

    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error("Onverwachte WebSocket fout: %s", e)
        await manager.disconnect(websocket)
