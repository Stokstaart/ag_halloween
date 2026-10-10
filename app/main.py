"""Halloween Projection Control - Hoofdapplicatie (FastAPI)."""
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import (
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
from fastapi.responses import HTMLResponse, JSONResponse
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

# Beveiliging: optionele Bearer auth
bearer_scheme = HTTPBearer(auto_error=False)


def verify_token(
    request: Request,
    auth_header: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    token_param: Optional[str] = Query(None, alias="token"),
) -> bool:
    """Valideert toegangstoken indien AUTH_TOKEN geconfigureerd is."""
    if not AUTH_TOKEN:
        return True  # Onbeveiligde LAN-modus toegestaan

    # Check header
    if auth_header and auth_header.credentials == AUTH_TOKEN:
        return True

    # Check X-Auth-Token header
    x_token = request.headers.get("X-Auth-Token")
    if x_token and x_token == AUTH_TOKEN:
        return True

    # Check query param (?token=...)
    if token_param and token_param == AUTH_TOKEN:
        return True

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Ongeldig of ontbrekend authenticatietoken.",
        headers={"WWW-Authenticate": "Bearer"},
    )


# Pydantic models voor REST endpoints
class TriggerRequest(BaseModel):
    effect_id: str = Field(..., description="Unieke ID van het af te spelen effect")


class VolumeRequest(BaseModel):
    volume: Optional[float] = Field(None, ge=0.0, le=1.0, description="Volume tussen 0.0 en 1.0")
    muted: Optional[bool] = Field(None, description="Audio dempen of activeren")


class DisableRequest(BaseModel):
    disabled: bool = Field(..., description="Effecten tijdelijk uitschakelen")


class BackgroundRequest(BaseModel):
    file: Optional[str] = Field(None, description="Bestandsnaam of pad van de achtergrondvideo")
    filename: Optional[str] = Field(None, description="Alternatieve bestandsnaam")


# ==========================================
# HTML Views
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def view_index(request: Request, token: Optional[str] = None):
    """Startpagina met snelkoppelingen naar controller en projectiescherm."""
    auth_configured = bool(AUTH_TOKEN)
    token_valid = not auth_configured or (token == AUTH_TOKEN)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "token": token or "",
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
    if AUTH_TOKEN and token != AUTH_TOKEN:
        return HTMLResponse(
            "<h3>Toegang geweigerd: Authenticatietoken vereist op /screen?token=...</h3>",
            status_code=401,
        )
    return templates.TemplateResponse(
        "screen.html",
        {
            "request": request,
            "token": token or "",
            "debug": debug == "1" or DEBUG,
            "background": engine.get_background(),
        },
    )


@app.get("/control", response_class=HTMLResponse)
async def view_control(request: Request, token: Optional[str] = None):
    """Mobiele controller interface voor smartphone."""
    if AUTH_TOKEN and token != AUTH_TOKEN:
        return HTMLResponse(
            "<h3>Toegang geweigerd: Authenticatietoken vereist op /control?token=...</h3>",
            status_code=401,
        )
    return templates.TemplateResponse(
        "control.html",
        {
            "request": request,
            "token": token or "",
            "auth_configured": bool(AUTH_TOKEN),
            "status": engine.get_status(),
            "effects": engine.get_effects_list(),
            "background": engine.get_background(),
        },
    )


# ==========================================
# REST API Endpoints
# ==========================================

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
    }


@app.get("/api/effects")
async def api_effects(authenticated: bool = Depends(verify_token)):
    """Haalt de actuele lijst van effecten en achtergrondconfiguratie op."""
    return {
        "background": engine.get_background(),
        "backgrounds": engine.get_background_list(),
        "effects": engine.get_effects_list(),
    }


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
    """Triggert een effect via REST (handig voor bijv. Home Assistant rest_command)."""
    success, reason, effect_payload = engine.trigger_effect(payload.effect_id)
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

    return {"success": True, "message": "Effect geactiveerd", "effect": effect_payload}


@app.post("/api/stop")
async def api_stop(authenticated: bool = Depends(verify_token)):
    """Stopt direct het actieve effect en keert terug naar de achtergrond."""
    result = engine.stop_effect()
    await manager.broadcast_to_screens({"type": "stop_effect"})
    await manager.broadcast_to_controllers({"type": "effect_stopped"})
    return {"success": True, "message": "Teruggekeerd naar achtergrond", **result}


@app.post("/api/volume")
async def api_volume(payload: VolumeRequest, authenticated: bool = Depends(verify_token)):
    """Past volume of dempstatus aan."""
    if payload.volume is not None:
        engine.set_volume(payload.volume)
    if payload.muted is not None:
        engine.set_muted(payload.muted)

    status_update = {
        "type": "volume_update",
        "volume": engine.volume,
        "muted": engine.muted,
    }
    await manager.broadcast_all(status_update)
    return {"success": True, "volume": engine.volume, "muted": engine.muted}


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
    # Check optioneel token via query params
    query_token = websocket.query_params.get("token", "")
    if AUTH_TOKEN and query_token != AUTH_TOKEN:
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
            "volume": engine.volume,
            "muted": engine.muted,
        })
    else:
        await manager.connect_controller(websocket)
        await manager.send_personal(websocket, {
            "type": "init",
            "status": engine.get_status(),
            "effects": engine.get_effects_list(),
            "background": engine.get_background(),
            "backgrounds": engine.get_background_list(),
            "screen_count": len(manager.screen_connections),
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

                elif action == "screen_ping":
                    await manager.send_personal(websocket, {"type": "screen_pong"})

            # --- Commando's vanaf de mobiele controller ---
            else:
                if action == "trigger":
                    effect_id = data.get("effect_id")
                    logger.info("Trigger commando ontvangen van controller voor: %s", effect_id)
                    success, reason, effect_payload = engine.trigger_effect(effect_id)
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
                        # Watchdog om vastlopen van state te voorkomen
                        async def _watchdog(eid: str, delay: float):
                            await asyncio.sleep(delay)
                            if engine.active_effect_id == eid:
                                logger.warning("Watchdog: effect %s duur verstreken, forceren reset.", eid)
                                engine.stop_effect()
                                await manager.broadcast_to_screens({"type": "stop_effect"})
                                await manager.broadcast_to_controllers({"type": "effect_stopped", "effect_id": eid})
                        asyncio.create_task(_watchdog(effect_payload["effect_id"], effect_payload["duration"] + 3.5))
                    else:
                        logger.warning("Trigger voor %s geweigerd: %s", effect_id, reason)
                        await manager.send_personal(websocket, {
                            "type": "trigger_ack",
                            "success": False,
                            "effect_id": effect_id,
                            "reason": reason,
                        })

                elif action == "trigger_random":
                    success, reason, effect_payload = engine.trigger_random()
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
                        import asyncio
                        async def _watchdog_random(eid: str, delay: float):
                            await asyncio.sleep(delay)
                            if engine.active_effect_id == eid:
                                logger.warning("Watchdog (random): effect %s duur verstreken, forceren reset.", eid)
                                engine.stop_effect()
                                await manager.broadcast_to_screens({"type": "stop_effect"})
                                await manager.broadcast_to_controllers({"type": "effect_stopped", "effect_id": eid})
                        asyncio.create_task(_watchdog_random(effect_payload["effect_id"], effect_payload["duration"] + 3.5))
                    else:
                        await manager.send_personal(websocket, {
                            "type": "trigger_ack",
                            "success": False,
                            "reason": reason,
                        })

                elif action in ("stop", "return_to_background"):
                    result = engine.stop_effect()
                    await manager.broadcast_to_screens({"type": "stop_effect"})
                    await manager.broadcast_to_controllers({"type": "effect_stopped"})

                elif action == "set_volume":
                    vol = data.get("volume", 1.0)
                    engine.set_volume(vol)
                    await manager.broadcast_all({
                        "type": "volume_update",
                        "volume": engine.volume,
                        "muted": engine.muted,
                    })

                elif action == "toggle_mute":
                    muted = engine.toggle_muted()
                    await manager.broadcast_all({
                        "type": "volume_update",
                        "volume": engine.volume,
                        "muted": engine.muted,
                    })

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
