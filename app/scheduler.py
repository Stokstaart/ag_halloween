"""Autopilot Scheduler voor getimede willekeurige scares en geluidseffecten.

Draait server-side in de achtergrond:
- Interval instelbaar (standaard tussen 1 en 6 minuten).
- Keuze tussen: beide (willekeurig), alleen video jumpscares, of alleen geluidseffecten.
- Houdt rekening met al actieve scares (wacht netjes tot een actief effect voorbij is).
- Blijft continu betrouwbaar lopen, ook als de smartphone van de operator vergrendeld is.
"""
import asyncio
import logging
import random
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("halloween.scheduler")


class AutoScareScheduler:
    def __init__(
        self,
        trigger_callback: Callable[[str], Any],
        broadcast_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        self.trigger_callback = trigger_callback
        self.broadcast_callback = broadcast_callback
        self.enabled = False
        self.min_minutes = 1.0
        self.max_minutes = 6.0
        self.mode = "both"  # "both", "jumpscare", "sound"

        self.next_trigger_at: Optional[float] = None
        self.next_trigger_type: Optional[str] = None
        self.last_triggered_name: Optional[str] = None
        self.last_triggered_at: Optional[float] = None

        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    def get_status(self) -> Dict[str, Any]:
        """Geeft de actuele status van de autopilot scheduler."""
        remaining = 0
        if self.enabled and self.next_trigger_at:
            remaining = max(0, int(self.next_trigger_at - time.time()))

        return {
            "enabled": self.enabled,
            "min_minutes": self.min_minutes,
            "max_minutes": self.max_minutes,
            "mode": self.mode,
            "next_trigger_in": remaining,
            "next_trigger_type": self.next_trigger_type,
            "last_triggered_name": self.last_triggered_name,
            "last_triggered_at": self.last_triggered_at,
        }

    def set_config(
        self,
        min_minutes: Optional[float] = None,
        max_minutes: Optional[float] = None,
        mode: Optional[str] = None,
    ):
        """Past de autopilot instellingen aan."""
        if min_minutes is not None:
            self.min_minutes = max(0.2, float(min_minutes))
        if max_minutes is not None:
            self.max_minutes = max(self.min_minutes, float(max_minutes))
        if mode in ("both", "jumpscare", "sound"):
            self.mode = mode

        if self.enabled:
            self._schedule_next()

    def set_enabled(self, enabled: bool):
        """Schakelt de autopilot aan of uit."""
        if self.enabled == enabled:
            return

        self.enabled = enabled
        if self.enabled:
            self._stop_event.clear()
            self._schedule_next()
            self._task = asyncio.create_task(self._run_loop())
            logger.info("Auto-scare autopilot ingeschakeld (interval %.1f - %.1f min, mode: %s).", self.min_minutes, self.max_minutes, self.mode)
        else:
            self._stop_event.set()
            if self._task and not self._task.done():
                self._task.cancel()
            self._task = None
            self.next_trigger_at = None
            self.next_trigger_type = None
            logger.info("Auto-scare autopilot uitgeschakeld.")

    def _schedule_next(self):
        """Berekent het volgende willekeurige triggermoment."""
        min_sec = int(self.min_minutes * 60)
        max_sec = int(self.max_minutes * 60)
        delay = random.randint(min_sec, max(min_sec, max_sec))

        self.next_trigger_at = time.time() + delay

        if self.mode == "both":
            self.next_trigger_type = random.choice(["jumpscare", "sound"])
        elif self.mode == "sound":
            self.next_trigger_type = "sound"
        else:
            self.next_trigger_type = "jumpscare"

        logger.info("Volgende auto-scare (%s) gepland over %d seconden.", self.next_trigger_type, delay)

    async def _run_loop(self):
        """Achtergrondloop die aftelt en scares activeert."""
        try:
            last_broadcast = 0.0
            while self.enabled and not self._stop_event.is_set():
                now = time.time()

                # Periodiek status broadcasten naar controller (elke 5 sec)
                if self.broadcast_callback and (now - last_broadcast >= 5.0):
                    last_broadcast = now
                    try:
                        await self.broadcast_callback(self.get_status())
                    except Exception as e:
                        logger.debug("Fout bij broadcast autopilot status: %s", e)

                if self.next_trigger_at and now >= self.next_trigger_at:
                    trig_type = self.next_trigger_type or "jumpscare"
                    logger.info("Autopilot vuurt nu een auto-scare af: %s", trig_type)

                    try:
                        res = self.trigger_callback(trig_type)
                        if asyncio.iscoroutine(res):
                            res = await res
                        success, name = res
                        if success:
                            self.last_triggered_name = name
                            self.last_triggered_at = now
                    except Exception as ex:
                        logger.error("Fout tijdens uitvoeren van auto-scare: %s", ex)

                    # Plan direct de volgende scare
                    self._schedule_next()
                    if self.broadcast_callback:
                        try:
                            await self.broadcast_callback(self.get_status())
                        except Exception:
                            pass

                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("Onverwachte fout in autopilot loop: %s", e)
