/**
 * Halloween Projection Screen - Client Engine
 * Geoptimaliseerd voor beamerbrowsers (Android TV).
 */

(function () {
  'use strict';

  // DOM elementen
  const bgVideo1 = document.getElementById('bg-video-1') || document.getElementById('bg-video');
  const bgVideo2 = document.getElementById('bg-video-2');
  let activeBgVideo = bgVideo1;
  let standbyBgVideo = bgVideo2;
  const effectVideo = document.getElementById('effect-video');
  const blackoutOverlay = document.getElementById('blackout-overlay');
  const unlockOverlay = document.getElementById('unlock-overlay');
  const noMediaNotice = document.getElementById('no-media-notice');
  const debugHud = document.getElementById('debug-hud');

  // Vaste audio spelers voor Sound Effects
  const sfxAudioPool = [
    document.getElementById('sfx-audio-1'),
    document.getElementById('sfx-audio-2'),
    document.getElementById('sfx-audio-3'),
    document.getElementById('sfx-audio-4'),
  ].filter(Boolean);
  let nextSfxPoolIndex = 0;


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
  let currentOverlapHandler = null;
  const activeSoundEffects = new Set();
  let lastPlayedSound = 'Geen';

  // Toggle debug HUD
  function updateDebugHud() {
    if (!debugHud) return;
    if (debugMode) {
      debugHud.classList.add('visible');
      debugHud.innerHTML = `
        <strong>🎃 SCREEN DEBUG HUD</strong><br>
        WS Status: ${ws && ws.readyState === WebSocket.OPEN ? '<span style="color:#81c784">VERBONDEN</span>' : '<span style="color:#e57373">VERBROKEN</span>'}<br>
        Actief Effect: ${currentActiveEffect ? currentActiveEffect.effect_id : 'Geen (Achtergrond)'}<br>
        Laatste Geluid: <span style="color:#ce93d8">${lastPlayedSound}</span><br>
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
    } else if (e.key === 'Escape' || e.key === 's' || e.key === 'S') {
      returnToBackground(true);
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
    if (activeBgVideo && activeBgVideo.src) {
      activeBgVideo.muted = isMuted;
      activeBgVideo.volume = isMuted ? 0 : currentVolume;
      if (activeBgVideo.paused) {
        activeBgVideo.play().catch(err => {
          console.warn('Achtergrondvideo autoplay waarschuwing na unlock:', err);
        });
      }
    }

    if (standbyBgVideo && standbyBgVideo.src) {
      standbyBgVideo.muted = isMuted;
      standbyBgVideo.volume = isMuted ? 0 : currentVolume;
    }

    // Probeer effectvideo kort gereed te maken voor audio
    if (effectVideo) {
      effectVideo.volume = isMuted ? 0 : currentVolume;
      effectVideo.muted = isMuted;
    }

    // Unmute en initialiseer alle sound effect audiospelers
    sfxAudioPool.forEach(player => {
      try {
        player.muted = isMuted;
        player.volume = isMuted ? 0 : currentVolume;
      } catch (e) {}
    });

    updateDebugHud();
  }


  if (unlockOverlay) {
    unlockOverlay.addEventListener('click', unlockMedia);
  }
  document.addEventListener('click', unlockMedia);
  document.addEventListener('touchstart', unlockMedia);

  // Achtergrondvideo instellen en naadloos wisselen
  function setupBackground(bg) {
    backgroundConfig = bg;
    if (bg && bg.file_exists && bg.web_url) {
      if (noMediaNotice) noMediaNotice.style.display = 'none';
      if (bgPollingTimer) {
        clearInterval(bgPollingTimer);
        bgPollingTimer = null;
      }

      // Voorkom onnodig herladen als dezelfde video al speelt
      if (activeBgVideo && activeBgVideo.src && activeBgVideo.src.includes(bg.web_url) && !activeBgVideo.paused) {
        return;
      }

      // Als er een standby-speler is en activeBgVideo speelt al: naadloze crossfade
      if (standbyBgVideo && activeBgVideo && activeBgVideo.src) {
        console.info('Naadloze achtergrond crossfade naar:', bg.web_url);
        standbyBgVideo.src = bg.web_url;
        standbyBgVideo.loop = bg.loop !== false;
        standbyBgVideo.muted = isMuted;
        standbyBgVideo.volume = isMuted ? 0 : currentVolume;
        standbyBgVideo.load();

        standbyBgVideo.play().then(() => {
          standbyBgVideo.classList.add('visible');
          standbyBgVideo.classList.add('active-top');

          setTimeout(() => {
            activeBgVideo.classList.remove('visible');
            activeBgVideo.classList.remove('active-top');
            try { activeBgVideo.pause(); } catch (e) {}

            // Verwissel active en standby spelers
            const temp = activeBgVideo;
            activeBgVideo = standbyBgVideo;
            standbyBgVideo = temp;

            if (unlockOverlay && isMediaUnlocked) {
              unlockOverlay.classList.add('hidden');
            }
          }, 850);
        }).catch(err => {
          console.warn('Standby video play mislukt, fallback naar gedempt:', err);
          standbyBgVideo.muted = true;
          standbyBgVideo.play().catch(() => {});
        });
        return;
      }

      // Eerste start
      if (activeBgVideo) {
        activeBgVideo.src = bg.web_url;
        activeBgVideo.loop = bg.loop !== false;
        activeBgVideo.muted = isMuted;
        activeBgVideo.volume = isMuted ? 0 : currentVolume;
        activeBgVideo.load();

        activeBgVideo.play().then(() => {
          activeBgVideo.classList.add('visible');
          if (unlockOverlay && isMediaUnlocked) {
            unlockOverlay.classList.add('hidden');
          }
        }).catch(err => {
          console.warn('Browser autoplay beleid blokkeert audio start:', err);
          if (!isMediaUnlocked && unlockOverlay) {
            unlockOverlay.classList.remove('hidden');
          }
          // Start gedempt afspelen zodat er tenminste beeld is totdat gebruiker klikt
          activeBgVideo.muted = true;
          activeBgVideo.play().then(() => {
            activeBgVideo.classList.add('visible');
          }).catch(() => {});
        });
      }
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

  // Effect afspelen met gegarandeerd vloeiende overgang zonder zwarte flits
  function playEffect(effect) {
    console.info('Start effect op projectiescherm:', effect);
    currentActiveEffect = effect;

    if (unlockOverlay) {
      unlockOverlay.classList.add('hidden');
    }

    if (effectTimeoutTimer) {
      clearTimeout(effectTimeoutTimer);
      effectTimeoutTimer = null;
    }

    // Reset weergavemodus
    effectVideo.pause();
    effectVideo.className = 'video-layer';

    const mode = effect.display_mode || effect.type;
    if (mode === 'fullscreen') {
      effectVideo.classList.add('mode-fullscreen');
    } else {
      effectVideo.classList.add('mode-overlay');
    }

    // Audio-instellingen
    effectVideo.volume = isMuted ? 0 : (effect.has_audio ? currentVolume : 0);
    effectVideo.muted = isMuted || !effect.has_audio;

    // Pas de achtergrond verbergen zodra het effectframe DAADWERKELIJK rendert (elimineert de zwarte hapering!)
    let frameRendered = false;
    const onFrameReady = () => {
      if (frameRendered) return;
      frameRendered = true;
      effectVideo.removeEventListener('playing', onFrameReady);
      effectVideo.removeEventListener('timeupdate', onFrameReady);

      effectVideo.classList.add('visible');
      if (mode === 'fullscreen' && activeBgVideo) {
        activeBgVideo.style.opacity = '0';
        activeBgVideo.muted = true;
      }
      updateDebugHud();
    };

    effectVideo.addEventListener('playing', onFrameReady);
    effectVideo.addEventListener('timeupdate', onFrameReady);

    // Laad bron
    effectVideo.src = effect.web_url;
    effectVideo.load();

    effectVideo.play().then(() => {
      setTimeout(onFrameReady, 50);
    }).catch(err => {
      console.warn('Fout bij afspelen van effectvideo:', err);
      if (err.name === 'NotAllowedError') {
        effectVideo.muted = true;
        effectVideo.play().then(onFrameReady).catch(err2 => {
          console.error('Ook gedempt afspelen mislukt:', err2);
          notifyEffectError(effect.effect_id, 'Kan effectvideo niet afspelen: ' + err2.message);
          returnToBackground();
        });
        return;
      }
      notifyEffectError(effect.effect_id, 'Kan effectvideo niet afspelen: ' + err.message);
      returnToBackground();
    });

    // Luister naar video-afspeeltijd voor naadloze overlap-terugkeer
    if (currentOverlapHandler) {
      effectVideo.removeEventListener('timeupdate', currentOverlapHandler);
      currentOverlapHandler = null;
    }

    let overlapTriggered = false;
    currentOverlapHandler = () => {
      if (overlapTriggered) return;
      if (!currentActiveEffect || currentActiveEffect.effect_id !== effect.effect_id) {
        if (currentOverlapHandler) {
          effectVideo.removeEventListener('timeupdate', currentOverlapHandler);
          currentOverlapHandler = null;
        }
        return;
      }
      const dur = effectVideo.duration;
      const cur = effectVideo.currentTime;
      // Start de vloeiende overgang ~0.75s vóór het einde van de video voor de gewenste overlap
      if (dur > 1.2 && cur >= (dur - 0.75)) {
        overlapTriggered = true;
        console.info(`Overlap punt bereikt (${Math.round(cur * 10) / 10}s / ${Math.round(dur * 10) / 10}s), start vloeiende overgang naar achtergrond.`);
        if (currentOverlapHandler) {
          effectVideo.removeEventListener('timeupdate', currentOverlapHandler);
          currentOverlapHandler = null;
        }
        returnToBackground();
      }
    };
    effectVideo.addEventListener('timeupdate', currentOverlapHandler);

    // Fallback veiligheidstimer (mocht timeupdate haperen of video vastlopen)
    const durationMs = (effect.duration || 15) * 1000;
    effectTimeoutTimer = setTimeout(() => {
      console.info('Effectduur verstreken (fallback timer):', effect.effect_id);
      returnToBackground();
    }, durationMs + 2000);

    updateDebugHud();
  }

  // Terugkeren naar de achtergrond (zowel bij natuurlijk einde als noodstop)
  function returnToBackground(isEmergency = false) {
    if (effectTimeoutTimer) {
      clearTimeout(effectTimeoutTimer);
      effectTimeoutTimer = null;
    }

    if (currentOverlapHandler) {
      effectVideo.removeEventListener('timeupdate', currentOverlapHandler);
      currentOverlapHandler = null;
    }

    const finishedId = currentActiveEffect ? currentActiveEffect.effect_id : null;
    currentActiveEffect = null;

    if (isEmergency) {
      console.info('NOODSTOP UITGEVOERD: Direct effectvideo pauzeren en achtergrond herstellen.');
      // 1. Direct jumpscare video pauzeren, dempen en zichtbaarheid wegnemen
      try {
        effectVideo.pause();
        effectVideo.muted = true;
        effectVideo.removeAttribute('src');
        effectVideo.load();
      } catch (e) {}
      effectVideo.className = 'video-layer';

      // 1b. Stop ook alle actieve overlappende geluidseffecten
      activeSoundEffects.forEach(snd => {
        try {
          snd.pause();
          snd.currentTime = 0;
        } catch (e) {}
      });
      activeSoundEffects.clear();

      // 2. Direct achtergrond herstellen
      if (activeBgVideo) {
        activeBgVideo.style.opacity = '1';
        activeBgVideo.muted = isMuted;
        activeBgVideo.volume = isMuted ? 0 : currentVolume;
        if (activeBgVideo.src) {
          activeBgVideo.play().catch(() => {});
        }
      }
    } else {
      // Vloeiende fade-out effectvideo
      if (activeBgVideo) {
        activeBgVideo.style.opacity = '1';
        activeBgVideo.muted = isMuted;
        activeBgVideo.volume = isMuted ? 0 : currentVolume;
        if (activeBgVideo.paused && activeBgVideo.src) {
          activeBgVideo.play().catch(() => {});
        }
      }

      effectVideo.classList.remove('visible');

      setTimeout(() => {
        try {
          effectVideo.pause();
          effectVideo.removeAttribute('src');
          effectVideo.load();
        } catch (e) {}
      }, 350);
    }

    // 1. WebSocket melding indien verbonden
    if (ws && ws.readyState === WebSocket.OPEN && finishedId) {
      ws.send(JSON.stringify({
        action: 'effect_ended',
        effect_id: finishedId
      }));
    }

    // 2. HTTP Fallback (garandeert dat server status ALTIJD gereset wordt, zelfs bij haperende WS)
    if (finishedId) {
      const endUrl = '/api/effect-ended' + (token ? '?token=' + encodeURIComponent(token) : '');
      fetch(endUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ effect_id: finishedId })
      }).catch(err => {
        console.debug('HTTP effect-ended melding fallback:', err);
      });
    }

    updateDebugHud();
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

  [bgVideo1, bgVideo2].forEach((v) => {
    if (v) {
      v.addEventListener('ended', () => {
        console.info('Achtergrondvideo heeft einde bereikt; automatische repeat/loop herstarten.');
        v.currentTime = 0;
        v.play().catch(err => console.warn('Herstart achtergrondloop waarschuwing:', err));
      });
      v.addEventListener('error', (e) => {
        console.error('Fout bij laden van achtergrondvideo:', v.error, e);
        if (noMediaNotice) {
          noMediaNotice.innerHTML = '<h2>Achtergrondvideo Fout</h2><p>Controleer of het MP4-bestand geldig is en de H.264 codec gebruikt.</p>';
          noMediaNotice.style.display = 'block';
        }
      });
    }
  });

  // WebSocket verbinding
  let isConnecting = false;
  function connectWebSocket() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    let wsUrl = `${protocol}//${window.location.host}/ws?role=screen`;
    if (token) {
      wsUrl += `&token=${encodeURIComponent(token)}`;
    }

    console.info('Verbinden met WebSocket:', wsUrl);
    try {
      ws = new WebSocket(wsUrl);
    } catch (err) {
      console.error('Fout bij initialiseren WebSocket:', err);
      scheduleReconnect();
      return;
    }

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
    } else if (type === 'play_sound') {
      console.info('play_sound signaal ontvangen:', data);
      playSoundEffect(data);
    } else if (type === 'play_effect' || type === 'fullscreen' || type === 'overlay' || data.web_url) {
      console.info('play_effect signaal ontvangen:', data);
      playEffect(data);
    } else if (type === 'stop_effect' || type === 'effect_stopped') {
      console.info('Noodstop / stop_effect commando ontvangen.');
      returnToBackground(true);
    } else if (type === 'volume_update') {
      currentVolume = data.volume !== undefined ? data.volume : currentVolume;
      isMuted = !!data.muted;
      if (activeBgVideo) {
        activeBgVideo.volume = isMuted ? 0 : currentVolume;
        activeBgVideo.muted = isMuted;
      }
      if (standbyBgVideo) {
        standbyBgVideo.volume = isMuted ? 0 : currentVolume;
        standbyBgVideo.muted = isMuted;
      }
      if (effectVideo) {
        effectVideo.volume = isMuted ? 0 : currentVolume;
        effectVideo.muted = isMuted;
      }
      // Werk volume bij voor alle actieve geluidseffecten
      activeSoundEffects.forEach(snd => {
        try {
          snd.volume = isMuted ? 0 : currentVolume;
          snd.muted = isMuted;
        } catch (e) {}
      });
      updateDebugHud();
    }
  }

  // Speelt een geluidseffect overlappend af via de sfx audio pool (met dynamische fallback)
  function playSoundEffect(soundData) {
    if (!soundData || !soundData.web_url) {
      console.warn('playSoundEffect aangeroepen zonder web_url:', soundData);
      return;
    }

    if (unlockOverlay) {
      unlockOverlay.classList.add('hidden');
    }

    const soundUrl = soundData.web_url;
    const targetVolume = isMuted ? 0 : (soundData.volume !== undefined ? soundData.volume : currentVolume);

    // 1. Kies een audiospeler uit de vaste pool in de DOM (heeft reeds autoplay-rechten)
    let player = null;
    if (sfxAudioPool.length > 0) {
      player = sfxAudioPool[nextSfxPoolIndex % sfxAudioPool.length];
      nextSfxPoolIndex++;
    } else {
      player = new Audio();
    }

    try {
      player.pause();
      player.src = soundUrl;
      player.volume = targetVolume;
      player.muted = isMuted;
      player.currentTime = 0;
      player.load();

      activeSoundEffects.add(player);

      const cleanup = () => {
        activeSoundEffects.delete(player);
        player.removeEventListener('ended', cleanup);
        player.removeEventListener('error', onError);
      };

      const onError = (e) => {
        const errDetails = player.error ? `Code ${player.error.code}: ${player.error.message}` : 'Onbekende audiofout';
        console.error('Audiofout bij afspelen van sound effect:', soundData.name, errDetails, e);
        cleanup();
      };

      player.addEventListener('ended', cleanup);
      player.addEventListener('error', onError);

      lastPlayedSound = soundData.name || soundData.filename || 'Sound';
      updateDebugHud();

      const playPromise = player.play();
      if (playPromise !== undefined) {
        playPromise.then(() => {
          console.info('Sound effect speelt succesvol af:', soundData.name);
          updateDebugHud();
        }).catch(err => {
          console.warn('Autoplay waarschuwing bij sound effect play():', err.name, err.message);
          lastPlayedSound = `${soundData.name} (Geblokkeerd door browser)`;
          updateDebugHud();
          cleanup();
        });
      }

    } catch (e) {
      console.error('Fout bij afspelen sound effect:', e);
    }
  }



  // Heartbeat ping om verbinding levend te houden
  setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: 'screen_ping' }));
    }
    updateDebugHud();
  }, 15000);

  // Liveness watchdog: controleer elke 3 seconden of de verbinding hersteld moet worden
  setInterval(() => {
    if (!ws || ws.readyState === WebSocket.CLOSED) {
      connectWebSocket();
    }
  }, 3000);

  window.addEventListener('online', () => connectWebSocket());
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) connectWebSocket();
  });

  // Initialisatie bij pagina load
  window.addEventListener('DOMContentLoaded', () => {
    connectWebSocket();
    updateDebugHud();
  });
})();
