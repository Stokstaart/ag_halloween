"""WebSocket Connection Manager voor realtime projectie en bediening."""
import asyncio
import json
import logging
from typing import Any, Dict, Set
from fastapi import WebSocket

logger = logging.getLogger("halloween.ws_manager")


class ConnectionManager:
    """Houdt actieve WebSockets bij voor projectieschermen en mobiele controllers."""

    def __init__(self):
        self.screen_connections: Set[WebSocket] = set()
        self.controller_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect_screen(self, websocket: WebSocket) -> None:
        """Registreert een projectiescherm."""
        await websocket.accept()
        async with self._lock:
            self.screen_connections.add(websocket)
        logger.info("Projectiescherm verbonden. Totaal schermen: %d", len(self.screen_connections))
        await self.broadcast_connection_stats()

    async def connect_controller(self, websocket: WebSocket) -> None:
        """Registreert een mobiele controller."""
        await websocket.accept()
        async with self._lock:
            self.controller_connections.add(websocket)
        logger.info("Controller verbonden. Totaal controllers: %d", len(self.controller_connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        """Verwijdert een verbroken verbinding."""
        async with self._lock:
            was_screen = websocket in self.screen_connections
            was_ctrl = websocket in self.controller_connections
            self.screen_connections.discard(websocket)
            self.controller_connections.discard(websocket)

        if was_screen:
            logger.info("Projectiescherm verbroken. Resterend: %d", len(self.screen_connections))
            await self.broadcast_connection_stats()
        elif was_ctrl:
            logger.info("Controller verbroken. Resterend: %d", len(self.controller_connections))

    def get_stats(self) -> Dict[str, int]:
        """Geeft het aantal verbonden schermen en controllers terug."""
        return {
            "screen_count": len(self.screen_connections),
            "controller_count": len(self.controller_connections),
        }

    async def send_personal(self, websocket: WebSocket, message: Dict[str, Any]) -> None:
        """Verstuurt een JSON-bericht naar een specifieke WebSocket."""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.debug("Fout bij verzenden naar individuele socket: %s", e)

    async def broadcast_to_screens(self, message: Dict[str, Any]) -> None:
        """Verstuurt een commando naar alle actieve projectieschermen."""
        text = json.dumps(message)
        dead = []
        async with self._lock:
            targets = list(self.screen_connections)

        for ws in targets:
            try:
                await ws.send_text(text)
            except Exception as e:
                logger.warning("Fout bij broadcast naar scherm: %s", e)
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self.screen_connections.discard(ws)
            await self.broadcast_connection_stats()

    async def broadcast_to_controllers(self, message: Dict[str, Any]) -> None:
        """Verstuurt een statusbericht naar alle controllers."""
        text = json.dumps(message)
        dead = []
        async with self._lock:
            targets = list(self.controller_connections)

        for ws in targets:
            try:
                await ws.send_text(text)
            except Exception as e:
                logger.debug("Fout bij broadcast naar controller: %s", e)
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self.controller_connections.discard(ws)

    async def broadcast_all(self, message: Dict[str, Any]) -> None:
        """Verstuurt een bericht naar zowel schermen als controllers."""
        await self.broadcast_to_screens(message)
        await self.broadcast_to_controllers(message)

    async def broadcast_connection_stats(self) -> None:
        """Informeert alle controllers over het actuele aantal verbonden schermen."""
        stats = {
            "type": "connection_stats",
            "screen_count": len(self.screen_connections),
            "controller_count": len(self.controller_connections),
        }
        await self.broadcast_to_controllers(stats)
