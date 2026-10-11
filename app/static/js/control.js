/**
 * Halloween Mobile Controller - Client Logic
 */

(function () {
  'use strict';

  // State
  let ws = null;
  let reconnectTimer = null;
  let activeEffectTimer = null;
  let cooldownTimer = null;
  let currentVolume = 1.0;
  let isMuted = false;
  let effectsDisabled = false;
  let screensConnected = 0;

  // DOM elementen
  const connectionDot = document.getElementById('connection-dot');
  const connectionText = document.getElementById('connection-text');
  const activeBanner = document.getElementById('active-banner');
  const activeTitle = document.getElementById('active-title');
  const activeRemaining = document.getElementById('active-remaining');
  const progressBarFill = document.getElementById('progress-bar-fill');
  const cooldownBanner = document.getElementById('cooldown-banner');
  const cooldownRemaining = document.getElementById('cooldown-remaining');
  const volumeSlider = document.getElementById('volume-slider');
  const volumeVal = document.getElementById('volume-val');
  const btnMute = document.getElementById('btn-mute');
  const toggleDisabled = document.getElementById('toggle-disabled');
  const btnEmergency = document.getElementById('btn-emergency');
  const toastContainer = document.getElementById('toast-container');
  const bgSelect = document.getElementById('bg-select');
  const btnChangeBg = document.getElementById('btn-change-bg');
  const bgActiveName = document.getElementById('bg-active-name');
  const effectsGrid = document.getElementById('effects-grid');

  let cachedBackgrounds = [];

  // Token uit query params
  const urlParams = new URLSearchParams(window.location.search);
  const token = urlParams.get('token') || '';

  // Haptische feedback op smartphone
  function vibrate(ms = 35) {
    if (navigator.vibrate) {
      try { navigator.vibrate(ms); } catch (e) {}
    }
  }

  // Toon toast bericht
  function showToast(message, isError = false) {
    if (!toastContainer) return;
    const toast = document.createElement('div');
    toast.className = `toast ${isError ? 'error' : ''}`;
    toast.innerHTML = `<span>${isError ? '⚠️' : '🎃'}</span> <span>${message}</span>`;
    toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.transition = 'opacity 0.3s, transform 0.3s';
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      setTimeout(() => toast.remove(), 300);
    }, 3200);
  }

  // WebSocket verbinding opzetten
  function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    let wsUrl = `${protocol}//${window.location.host}/ws?role=control`;
    if (token) {
      wsUrl += `&token=${encodeURIComponent(token)}`;
    }

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.info('Controller verbonden met WebSocket server.');
      updateScreenStatus();
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleMessage(data);
      } catch (e) {
        console.error('Fout bij verwerken WS-bericht:', e);
      }
    };

    ws.onclose = () => {
      console.warn('WS verbinding met server verbroken. Reconnecting...');
      setConnectionStatus(false, 0);
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connectWebSocket, 2000);
    };

    ws.onerror = (err) => {
      console.error('WS fout:', err);
    };
  }

  function setConnectionStatus(connected, screenCount) {
    screensConnected = screenCount;
    if (!connectionDot || !connectionText) return;

    if (!connected || (ws && ws.readyState !== WebSocket.OPEN)) {
      connectionDot.className = 'status-dot disconnected';
      connectionText.textContent = 'Verbinding met server verbroken...';
    } else if (screenCount > 0) {
      connectionDot.className = 'status-dot connected';
      connectionText.textContent = `Beamer verbonden (${screenCount} ${screenCount === 1 ? 'scherm' : 'schermen'})`;
    } else {
      connectionDot.className = 'status-dot disconnected';
      connectionText.textContent = 'Geen beamer verbonden (Wachten op /screen)';
    }
  }

  function updateScreenStatus() {
    setConnectionStatus(ws && ws.readyState === WebSocket.OPEN, screensConnected);
  }

  // Achtergronden dropdown bijwerken
  function renderBackgrounds(backgrounds, currentBg) {
    if (!bgSelect) return;
    if (Array.isArray(backgrounds)) {
      cachedBackgrounds = backgrounds;
      bgSelect.innerHTML = '';
      backgrounds.forEach(bg => {
        const opt = document.createElement('option');
        opt.value = bg.filename || bg.file;
        opt.textContent = bg.name || bg.filename;
        if (bg.is_active || (currentBg && (currentBg.file === bg.file || (currentBg.file && currentBg.file.includes(bg.filename))))) {
          opt.selected = true;
        }
        bgSelect.appendChild(opt);
      });
    }

    if (currentBg && bgActiveName) {
      bgActiveName.textContent = currentBg.name || currentBg.file || 'Achtergrond';
    }
  }

  // Dynamische effectknoppen genereren en bijwerken
  function renderEffects(effects) {
    if (!effects || !Array.isArray(effects)) return;
    const grid = effectsGrid || document.querySelector('.effects-grid');
    const randomBtn = document.querySelector('.btn-effect.btn-random');

    effects.forEach(eff => {
      let btn = document.querySelector(`.btn-effect[data-effect-id="${eff.id}"]`);
      if (!btn && grid) {
        // Maak dynamische knop aan voor nieuw gevonden jumpscare
        btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn-effect';
        btn.dataset.effectId = eff.id;
        btn.title = eff.description || eff.name;

        let iconChar = '🎃';
        const idLower = (eff.id || '').toLowerCase();
        if (eff.icon === 'skull' || idLower.includes('scare') || idLower.includes('jump')) iconChar = '💀';
        else if (eff.icon === 'ghost' || idLower.includes('ghost')) iconChar = '👻';
        else if (eff.icon === 'zombie' || idLower.includes('zombie')) iconChar = '🧟';
        else if (eff.icon === 'eyes' || idLower.includes('eye')) iconChar = '👁️';
        else if (eff.icon === 'scratch' || idLower.includes('scratch') || idLower.includes('claw')) iconChar = '🐾';
        else if (eff.icon === 'spider' || idLower.includes('spider')) iconChar = '🕷️';

        btn.innerHTML = `
          <span class="effect-icon">${iconChar}</span>
          <span class="effect-name">${eff.name}</span>
          <span class="effect-meta">${(eff.type || 'Fullscreen').toUpperCase()} • ${Math.round(eff.duration || 15)}s</span>
        `;

        btn.addEventListener('click', () => handleEffectClick(btn));

        if (randomBtn) {
          grid.insertBefore(btn, randomBtn);
        } else {
          grid.appendChild(btn);
        }
      }

      if (btn) {
        const metaSpan = btn.querySelector('.effect-meta');
        if (metaSpan && eff.duration) {
          metaSpan.textContent = `${(eff.type || 'Fullscreen').toUpperCase()} • ${Math.round(eff.duration)}s`;
        }
        if (eff.configured) {
          btn.classList.remove('unconfigured');
          const badge = btn.querySelector('.unconfigured-badge');
          if (badge) badge.remove();
        } else {
          btn.classList.add('unconfigured');
          if (!btn.querySelector('.unconfigured-badge')) {
            const badge = document.createElement('span');
            badge.className = 'unconfigured-badge';
            badge.textContent = 'GEEN BESTAND';
            btn.appendChild(badge);
          }
        }
      }
    });
  }

  // Berichtafhandeling
  function handleMessage(data) {
    const type = data.type;

    if (type === 'init') {
      screensConnected = data.screen_count || 0;
      updateScreenStatus();
      if (data.backgrounds) {
        renderBackgrounds(data.backgrounds, data.background);
      }
      if (data.effects) {
        renderEffects(data.effects);
      }
      if (data.status) {
        if (data.status.volume !== undefined) setVolumeUI(data.status.volume);
        if (data.status.muted !== undefined) setMuteUI(data.status.muted);
        if (data.status.disabled !== undefined) setDisabledUI(data.status.disabled);
        if (data.status.active_effect_id) {
          startActiveBanner(data.status.active_effect_id, 15);
        }
      }
    } else if (type === 'connection_stats') {
      screensConnected = data.screen_count || 0;
      updateScreenStatus();
    } else if (type === 'background_selected' || type === 'background_update') {
      if (data.backgrounds) {
        renderBackgrounds(data.backgrounds, data.background);
      } else if (data.background) {
        renderBackgrounds(cachedBackgrounds, data.background);
      }
      if (type === 'background_selected' && data.background) {
        showToast(`Achtergrond ingesteld: ${data.background.name || data.background.file}`);
      }
    } else if (type === 'background_ack') {
      if (!data.success) {
        showToast(data.reason || 'Kan achtergrond niet wisselen.', true);
      }
    } else if (type === 'trigger_ack') {
      if (data.success) {
        vibrate(50);
        showToast(`${data.name || data.effect_id} geactiveerd!`);
      } else {
        vibrate([30, 50, 30]);
        showToast(data.reason || 'Kan effect niet starten.', true);
      }
    } else if (type === 'effect_active') {
      startActiveBanner(data.name || data.effect_id, data.duration || 10);
    } else if (type === 'effect_stopped') {
      stopActiveBanner();
    } else if (type === 'playback_error') {
      showToast(`Fout op beamer: ${data.message}`, true);
      stopActiveBanner();
    } else if (type === 'volume_update') {
      if (data.volume !== undefined) setVolumeUI(data.volume);
      if (data.muted !== undefined) setMuteUI(data.muted);
    } else if (type === 'disabled_update') {
      setDisabledUI(data.disabled);
    }
  }

  // Actief bannerbeheer
  function startActiveBanner(title, durationSeconds) {
    if (!activeBanner) return;
    activeTitle.textContent = title;
    activeBanner.classList.add('visible');

    const startTime = Date.now();
    const totalMs = durationSeconds * 1000;

    clearInterval(activeEffectTimer);
    activeEffectTimer = setInterval(() => {
      const elapsed = Date.now() - startTime;
      const remainingSec = Math.max(0, Math.ceil((totalMs - elapsed) / 1000));
      activeRemaining.textContent = `${remainingSec}s`;

      const pct = Math.max(0, Math.min(100, 100 - (elapsed / totalMs * 100)));
      progressBarFill.style.width = `${pct}%`;

      if (elapsed >= totalMs) {
        stopActiveBanner();
      }
    }, 100);
  }

  function stopActiveBanner() {
    clearInterval(activeEffectTimer);
    if (activeBanner) {
      activeBanner.classList.remove('visible');
    }
  }

  // Cooldown beheer
  function startCooldown(seconds) {
    if (!cooldownBanner || !seconds || seconds <= 0) {
      if (cooldownBanner) cooldownBanner.classList.remove('visible');
      return;
    }
    let remaining = seconds;
    cooldownBanner.classList.add('visible');

    clearInterval(cooldownTimer);
    cooldownTimer = setInterval(() => {
      remaining -= 0.2;
      if (remaining <= 0) {
        clearInterval(cooldownTimer);
        cooldownBanner.classList.remove('visible');
      } else {
        cooldownRemaining.textContent = `${remaining.toFixed(1)}s`;
      }
    }, 200);
  }

  // Audio & Toggles UI
  function setVolumeUI(vol) {
    currentVolume = vol;
    if (volumeSlider) volumeSlider.value = Math.round(vol * 100);
    if (volumeVal) volumeVal.textContent = `${Math.round(vol * 100)}%`;
  }

  function setMuteUI(muted) {
    isMuted = muted;
    if (btnMute) {
      btnMute.className = `btn-mute ${muted ? 'is-muted' : ''}`;
      btnMute.textContent = muted ? '🔇' : '🔊';
    }
  }

  function setDisabledUI(disabled) {
    effectsDisabled = disabled;
    if (toggleDisabled) toggleDisabled.checked = disabled;
  }

  // WS commando verzenden met directe HTTP fallback
  function sendCommand(action, payload = {}) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action, ...payload }));
      return;
    }

    console.warn(`WebSocket niet open (status ${ws ? ws.readyState : 'null'}). Fallback naar HTTP voor: ${action}`);

    // HTTP Fallbacks garanderen dat bediening op smartphone ALTIJD direct reageert
    if (action === 'trigger') {
      const triggerUrl = '/api/trigger' + (token ? '?token=' + encodeURIComponent(token) : '');
      fetch(triggerUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ effect_id: payload.effect_id, force: true })
      })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          vibrate(50);
          showToast(`${data.effect?.name || payload.effect_id} geactiveerd!`);
          startActiveBanner(data.effect?.name || payload.effect_id, data.effect?.duration || 10);
        } else {
          showToast(data.detail || 'Kan effect niet starten.', true);
        }
      })
      .catch(() => {
        showToast('Kan server niet bereiken.', true);
      });
    } else if (action === 'stop') {
      const stopUrl = '/api/stop' + (token ? '?token=' + encodeURIComponent(token) : '');
      fetch(stopUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
        .then(() => stopActiveBanner())
        .catch(() => {});
    } else {
      showToast('Niet verbonden met server. Even geduld...', true);
    }
  }

  // Klikafhandeling voor effectknoppen
  let lastClickTime = 0;
  function handleEffectClick(btn) {
    const now = Date.now();
    // Snelle debounce van 250ms tegen per ongeluk dubbeltikken
    if (now - lastClickTime < 250) return;
    lastClickTime = now;

    vibrate(25);
    const isUnconfigured = btn.classList.contains('unconfigured');
    const effectId = btn.dataset.effectId;
    const isRandom = btn.dataset.action === 'random';

    if (isUnconfigured) {
      showToast(`Effect '${btn.querySelector('.effect-name')?.textContent || effectId}' is nog niet geconfigureerd: mediabestand ontbreekt in media/effects/.`, true);
      return;
    }

    if (effectsDisabled) {
      showToast('Effecten zijn momenteel uitgeschakeld via de schakelaar hieronder.', true);
      return;
    }

    if (screensConnected === 0) {
      showToast('Waarschuwing: er is momenteel geen beamer verbonden met /screen.', true);
    }

    if (isRandom) {
      sendCommand('trigger_random', { force: true });
    } else if (effectId) {
      sendCommand('trigger', { effect_id: effectId, force: true });
    }
  }

  // Event Listeners voor Knoppen
  document.querySelectorAll('.btn-effect').forEach(btn => {
    btn.addEventListener('click', () => handleEffectClick(btn));
  });

  // Emergency Stop / Return to Background (Noodstop)
  if (btnEmergency) {
    btnEmergency.addEventListener('click', () => {
      vibrate([60, 40, 60]);
      // 1. Directe UI reset
      stopActiveBanner();

      // 2. Direct via WebSocket verzenden indien open
      sendCommand('stop');

      // 3. Altijd gelijktijdig via HTTP POST /api/stop verzenden
      // Dit garandeert dat de noodstop ONMIDDELLIJK werkt, zelfs als de WebSocket
      // op de smartphone even sliep of aan het herverbinden was!
      const stopUrl = '/api/stop' + (token ? '?token=' + encodeURIComponent(token) : '');
      fetch(stopUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
        .then(res => res.json())
        .then(data => {
          console.info('Noodstop via HTTP bevestigd:', data);
        })
        .catch(err => {
          console.warn('Noodstop HTTP fallback waarschuwing:', err);
        });

      showToast('🛑 Noodstop: Beamer keert direct terug naar achtergrond.');
    });
  }

  // Achtergrond wisselen knop & select
  if (btnChangeBg && bgSelect) {
    btnChangeBg.addEventListener('click', () => {
      const selected = bgSelect.value;
      if (selected) {
        vibrate(30);
        sendCommand('set_background', { file: selected });
      }
    });
  }

  if (bgSelect) {
    bgSelect.addEventListener('change', () => {
      const selected = bgSelect.value;
      if (selected) {
        vibrate(30);
        sendCommand('set_background', { file: selected });
      }
    });
  }

  // Volume slider
  if (volumeSlider) {
    volumeSlider.addEventListener('input', (e) => {
      const vol = parseFloat(e.target.value) / 100;
      setVolumeUI(vol);
      sendCommand('set_volume', { volume: vol });
    });
  }

  // Mute knop
  if (btnMute) {
    btnMute.addEventListener('click', () => {
      vibrate(20);
      sendCommand('toggle_mute');
    });
  }

  // Disabled Toggle
  if (toggleDisabled) {
    toggleDisabled.addEventListener('change', (e) => {
      vibrate(20);
      const disabled = e.target.checked;
      sendCommand('set_disabled', { disabled });
      showToast(disabled ? 'Effecten tijdelijk uitgeschakeld.' : 'Effecten weer ingeschakeld.');
    });
  }

  // Kolommen layout schakelaar (3 of 4 kolommen)
  const btnCol3 = document.getElementById('btn-col-3');
  const btnCol4 = document.getElementById('btn-col-4');

  function setGridColumns(cols) {
    const grid = effectsGrid || document.getElementById('effects-grid');
    if (!grid) return;
    if (cols === 4) {
      grid.classList.add('cols-4');
      grid.classList.remove('cols-3');
      if (btnCol4) btnCol4.classList.add('active');
      if (btnCol3) btnCol3.classList.remove('active');
      try { localStorage.setItem('halloween_grid_cols', '4'); } catch (e) {}
    } else {
      grid.classList.add('cols-3');
      grid.classList.remove('cols-4');
      if (btnCol3) btnCol3.classList.add('active');
      if (btnCol4) btnCol4.classList.remove('active');
      try { localStorage.setItem('halloween_grid_cols', '3'); } catch (e) {}
    }
  }

  if (btnCol3) {
    btnCol3.addEventListener('click', () => {
      vibrate(20);
      setGridColumns(3);
    });
  }
  if (btnCol4) {
    btnCol4.addEventListener('click', () => {
      vibrate(20);
      setGridColumns(4);
    });
  }

  // Laad opgeslagen kolomvoorkeur (standaard 3 kolommen)
  try {
    const savedCols = parseInt(localStorage.getItem('halloween_grid_cols') || '3', 10);
    setGridColumns(savedCols === 4 ? 4 : 3);
  } catch (e) {}

  function syncServerStatus() {
    fetch('/api/status' + (token ? '?token=' + encodeURIComponent(token) : ''))
      .then(res => res.json())
      .then(data => {
        if (!data) return;
        if (data.screens_connected !== undefined) {
          screensConnected = data.screens_connected;
          updateScreenStatus();
        }
        if (data.engine) {
          if (data.engine.active_effect_id) {
            startActiveBanner(data.engine.active_effect_id, 15);
          } else {
            stopActiveBanner();
          }
        }
      })
      .catch(() => {});
  }

  // Zorg voor onmiddellijk herstel van de verbinding en status wanneer het scherm ontwaakt op smartphone
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        connectWebSocket();
      }
      syncServerStatus();
    }
  });
  window.addEventListener('focus', () => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      connectWebSocket();
    }
    syncServerStatus();
  });
  window.addEventListener('online', () => {
    connectWebSocket();
    syncServerStatus();
  });

  // Init
  window.addEventListener('DOMContentLoaded', () => {
    connectWebSocket();

    // Haal initiële achtergronden en effecten direct op
    fetch('/api/effects' + (token ? '?token=' + encodeURIComponent(token) : ''))
      .then(res => res.json())
      .then(data => {
        if (data) {
          if (data.backgrounds) renderBackgrounds(data.backgrounds, data.background);
          if (data.effects) renderEffects(data.effects);
        }
      })
      .catch(() => {});

    // Periodieke controle om nieuwe effecten & achtergronden automatisch te activeren
    setInterval(() => {
      fetch('/api/effects' + (token ? '?token=' + encodeURIComponent(token) : ''))
        .then(res => res.json())
        .then(data => {
          if (data) {
            if (data.backgrounds) renderBackgrounds(data.backgrounds, data.background);
            if (data.effects) renderEffects(data.effects);
          }
        })
        .catch(() => {});
    }, 4000);
  });
})();
