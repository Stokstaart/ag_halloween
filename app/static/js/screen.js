/**
 * Halloween Projection Screen - Client Engine
 * Geoptimaliseerd voor beamerbrowsers (Android TV).
 */

(function () {
  'use strict';

  // DOM elementen
  const bgVideo = document.getElementById('bg-video');
  const effectVideo = document.getElementById('effect-video');
  const blackoutOverlay = document.getElementById('blackout-overlay');
  const unlockOverlay = document.getElementById('unlock-overlay');
  const noMediaNotice = document.getElementById('no-media-notice');
  const debugHud = document.getElementById('debug-hud');

  // Parameters uit URL
  const urlParams = new URLSearchParams(window.location.search);
  const token = urlParams.get('token') || '';
  let debugMode = urlParams.get('debug') === '1';

  // State
  let ws = null;
  let reconnectAttempts = 0;
  let maxReconnectDelay = 10000;
  let currentActiveEffect = null;
  let effectTimeoutTimer = null;
  let isMediaUnlocked = false;
  let currentVolume = 1.0;
  let isMuted = false;
  let backgroundConfig = null;

  // Toggle debug HUD
  function updateDebugHud() {
    if (!debugHud) return;
    if (debugMode) {
      debugHud.classList.add('visible');
      debugHud.innerHTML = `
        <strong>🎃 SCREEN DEBUG HUD</strong><br>
        WS Status: ${ws && ws.readyState === WebSocket.OPEN ? '<span style="color:#81c784">VERBONDEN</span>' : '<span style="color:#e57373">VERBROKEN</span>'}<br>
        Actief Effect: ${currentActiveEffect ? currentActiveEffect.effect_id : 'Geen (Achtergrond)'}<br>
        Volume: ${Math.round(currentVolume * 100)}% (Muted: ${isMuted})<br>
        Media Unlocked: ${isMediaUnlocked}<br>
        Scherm: ${window.innerWidth}x${window.innerHeight}px<br>
        Reconnect pogingen: ${reconnectAttempts}
      `;
    } else {
      debugHud.classList.remove('visible');
    }
  }

  // Toetsenbordsnelkoppelingen (bv. 'D' voor debug toggle, 'F' voor fullscreen)
  window.addEventListener('keydown', (e) => {
    if (e.key === 'd' || e.key === 'D') {
      debugMode = !debugMode;
      updateDebugHud();
    } else if (e.key === 'f' || e.key === 'F') {
      toggleFullscreen();
    }
    // Druk op een willekeurige toets om media te unlocken op Android TV
    if (!isMediaUnlocked) {
      unlockMedia();
    }
  });

  // Cursor verbergen na inactiviteit
  let mouseTimer = null;
  window.addEventListener('mousemove', () => {
    document.body.classList.add('show-cursor');
    clearTimeout(mouseTimer);
    mouseTimer = setTimeout(() => {
      document.body.classList.remove('show-cursor');
    }, 2500);
  });

  function toggleFullscreen() {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  }

  // Media Autoplay Unlock Procedure
  function unlockMedia() {
    isMediaUnlocked = true;
    if (unlockOverlay) {
      unlockOverlay.classList.add('hidden');
    }

    // Start achtergrondvideo indien beschikbaar
    if (bgVideo && bgVideo.src) {
      bgVideo.muted = isMuted || (backgroundConfig ? backgroundConfig.muted === true : false);
      bgVideo.volume = isMuted ? 0 : currentVolume;
      bgVideo.play().catch(err => {
        console.warn('Achtergrondvideo autoplay waarschuwing na unlock:', err);
      });
    }

    // Probeer effectvideo kort gereed te maken voor audio
    if (effectVideo) {
      effectVideo.volume = isMuted ? 0 : currentVolume;
      effectVideo.muted = isMuted;
    }

    updateDebugHud();
  }

  if (unlockOverlay) {
    unlockOverlay.addEventListener('click', unlockMedia);
  }
  document.addEventListener('click', unlockMedia);
  document.addEventListener('touchstart', unlockMedia);

  // Achtergrondvideo instellen en starten
  function setupBackground(bg) {
    backgroundConfig = bg;
    if (bg && bg.file_exists && bg.web_url) {
      if (noMediaNotice) noMediaNotice.style.display = 'none';
      if (bgPollingTimer) {
        clearInterval(bgPollingTimer);
        bgPollingTimer = null;
      }
      // Voorkom onnodig herladen als dezelfde video al speelt
      if (bgVideo.src && bgVideo.src.includes(bg.web_url) && !bgVideo.paused) {
        return;
      }
      bgVideo.src = bg.web_url;
      bgVideo.loop = bg.loop !== false;
      bgVideo.muted = isMuted || (bg.muted === true);
      bgVideo.load();

      bgVideo.play().then(() => {
        bgVideo.classList.add('visible');
        if (unlockOverlay && isMediaUnlocked) {
          unlockOverlay.classList.add('hidden');
        }
      }).catch(err => {
        console.warn('Browser autoplay beleid blokkeert automatische start:', err);
        if (!isMediaUnlocked && unlockOverlay) {
          unlockOverlay.classList.remove('hidden');
        }
      });
    } else {
      console.warn('Geen achtergrondvideo aanwezig in media/background/. Start periodieke check...');
      if (noMediaNotice) noMediaNotice.style.display = 'block';
      startBackgroundPolling();
    }
  }

  let bgPollingTimer = null;
  function startBackgroundPolling() {
    if (bgPollingTimer) return;
    bgPollingTimer = setInterval(() => {
      fetch('/api/effects' + (token ? '?token=' + encodeURIComponent(token) : ''))
        .then(res => res.json())
        .then(data => {
          if (data && data.background && data.background.file_exists) {
            console.info('Nieuwe achtergrondvideo ontdekt via polling:', data.background.file);
            setupBackground(data.background);
          }
        })
        .catch(() => {});
    }, 4000);
  }

  // Effect afspelen
  function playEffect(effect) {
    console.info('Start effect op projectiescherm:', effect);
    currentActiveEffect = effect;

    // Verberg altijd direct het unlock overlay scherm
    if (unlockOverlay) {
      unlockOverlay.classList.add('hidden');
    }

    // Annuleer lopende timers
    if (effectTimeoutTimer) {
      clearTimeout(effectTimeoutTimer);
      effectTimeoutTimer = null;
    }

    // Reset effect video
    effectVideo.pause();
    effectVideo.className = 'video-layer';

    if (effect.type === 'fullscreen') {
      effectVideo.classList.add('mode-fullscreen');
      // Verberg achtergrondvideo tijdelijk visueel en audio-matig voor maximaal jumpscare impact
      bgVideo.style.opacity = '0';
      bgVideo.muted = true;
    } else {
      effectVideo.classList.add('mode-overlay');
    }

    // Audio-instellingen
    effectVideo.volume = isMuted ? 0 : (effect.has_audio ? currentVolume : 0);
    effectVideo.muted = isMuted || !effect.has_audio;

    // Laad bron
    effectVideo.src = effect.web_url;
    effectVideo.load();

    effectVideo.play().then(() => {
      effectVideo.classList.add('visible');
      updateDebugHud();
    }).catch(err => {
      console.warn('Fout bij afspelen van effectvideo:', err);
      // Als de browser autoplay met geluid blokkeert, speel dan af met dempen als fallback
      if (err.name === 'NotAllowedError') {
        console.warn('Browser autoplay beleid blokkeert audio. Speelt gedempt af als fallback...');
        effectVideo.muted = true;
        effectVideo.play().then(() => {
          effectVideo.classList.add('visible');
          updateDebugHud();
        }).catch(err2 => {
          console.error('Ook gedempt afspelen mislukt:', err2);
          notifyEffectError(effect.effect_id, 'Kan effectvideo niet afspelen: ' + err2.message);
          returnToBackground();
        });
        return;
      }
      notifyEffectError(effect.effect_id, 'Kan effectvideo niet afspelen: ' + err.message);
      returnToBackground();
      return;
    });

    // Veiligheidstimer op basis van effectduur
    const durationMs = (effect.duration || 10) * 1000;
    effectTimeoutTimer = setTimeout(() => {
      console.info('Effectduur verstreken (fallback timer):', effect.effect_id);
      returnToBackground();
    }, durationMs + 500);

    updateDebugHud();
  }

  // Terugkeren naar de achtergrond
  function returnToBackground() {
    if (effectTimeoutTimer) {
      clearTimeout(effectTimeoutTimer);
      effectTimeoutTimer = null;
    }

    // Herstel achtergrondweergave
    bgVideo.style.opacity = '1';
    bgVideo.muted = isMuted || (backgroundConfig ? backgroundConfig.muted === true : false);
    if (bgVideo.paused && bgVideo.src) {
      bgVideo.play().catch(() => {});
    }

    if (currentActiveEffect) {
      const finishedId = currentActiveEffect.effect_id;
      currentActiveEffect = null;

      // Fade-out effect
      effectVideo.classList.remove('visible');

      setTimeout(() => {
        try {
          effectVideo.pause();
          effectVideo.removeAttribute('src');
          effectVideo.load();
        } catch (e) {}

        // Meld voltooiing aan backend
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            action: 'effect_ended',
            effect_id: finishedId
          }));
        }
        updateDebugHud();
      }, 350);
    }
  }

  function notifyEffectError(effectId, message) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        action: 'effect_error',
        effect_id: effectId,
        message: message
      }));
    }
  }

  // Luister naar video events
  effectVideo.addEventListener('ended', () => {
    console.info('Effectvideo natuurlijk afgelopen.');
    returnToBackground();
  });

  effectVideo.addEventListener('error', (e) => {
    const errorDetails = effectVideo.error ? `Code ${effectVideo.error.code}: ${effectVideo.error.message}` : 'Onbekende mediafout';
    console.error('Mediafout opgetreden in effectvideo:', errorDetails, e);
    if (currentActiveEffect) {
      notifyEffectError(currentActiveEffect.effect_id, errorDetails);
      returnToBackground();
    }
  });

  bgVideo.addEventListener('error', (e) => {
    console.error('Fout bij laden van achtergrondvideo:', bgVideo.error, e);
    if (noMediaNotice) {
      noMediaNotice.innerHTML = '<h2>Achtergrondvideo Fout</h2><p>Controleer of het MP4-bestand geldig is en de H.264 codec gebruikt.</p>';
      noMediaNotice.style.display = 'block';
    }
  });

  // WebSocket verbinding
  function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    let wsUrl = `${protocol}//${window.location.host}/ws?role=screen`;
    if (token) {
      wsUrl += `&token=${encodeURIComponent(token)}`;
    }

    console.info('Verbinden met WebSocket:', wsUrl);
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.info('WebSocket succesvol verbonden met Halloween server.');
      reconnectAttempts = 0;
      updateDebugHud();
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleServerMessage(data);
      } catch (err) {
        console.error('Fout bij verwerken van WS bericht:', err);
      }
    };

    ws.onclose = () => {
      console.warn('WebSocket verbinding verbroken. Opnieuw proberen...');
      updateDebugHud();
      scheduleReconnect();
    };

    ws.onerror = (err) => {
      console.error('WebSocket fout:', err);
    };
  }

  function scheduleReconnect() {
    reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(1.5, reconnectAttempts), maxReconnectDelay);
    console.info(`Volgende reconnect poging over ${Math.round(delay / 1000)}s...`);
    setTimeout(connectWebSocket, delay);
  }

  function handleServerMessage(data) {
    const type = data.type;

    if (type === 'init' || type === 'background_update') {
      if (data.volume !== undefined) currentVolume = data.volume;
      if (data.muted !== undefined) isMuted = !!data.muted;
      setupBackground(data.background);
    } else if (type === 'play_effect') {
      playEffect(data);
    } else if (type === 'stop_effect') {
      console.info('Noodstop / stop_effect commando ontvangen.');
      returnToBackground();
    } else if (type === 'volume_update') {
      currentVolume = data.volume !== undefined ? data.volume : currentVolume;
      isMuted = !!data.muted;
      if (bgVideo) {
        bgVideo.volume = isMuted ? 0 : currentVolume;
        bgVideo.muted = isMuted || (backgroundConfig ? backgroundConfig.muted === true : false);
      }
      if (effectVideo) {
        effectVideo.volume = isMuted ? 0 : currentVolume;
        effectVideo.muted = isMuted;
      }
      updateDebugHud();
    }
  }

  // Heartbeat ping om verbinding levend te houden
  setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: 'screen_ping' }));
    }
    updateDebugHud();
  }, 15000);

  // Initialisatie bij pagina load
  window.addEventListener('DOMContentLoaded', () => {
    connectWebSocket();
    updateDebugHud();
  });
})();
