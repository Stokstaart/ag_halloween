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
  let currentBgVolume = 0.8;
  let currentScareVolume = 1.0;
  let isMuted = false;
  let effectsDisabled = false;
  let screensConnected = 0;
  const activeSoundIds = new Set();
  let autopilotCountdownTimer = null;
  let autopilotRemainingSeconds = 0;
  let autopilotNextType = '';

  // DOM elementen
  const connectionDot = document.getElementById('connection-dot');
  const connectionText = document.getElementById('connection-text');
  const activeBanner = document.getElementById('active-banner');
  const activeTitle = document.getElementById('active-title');
  const activeRemaining = document.getElementById('active-remaining');
  const progressBarFill = document.getElementById('progress-bar-fill');
  const cooldownBanner = document.getElementById('cooldown-banner');
  const cooldownRemaining = document.getElementById('cooldown-remaining');
  const bgVolumeSlider = document.getElementById('bg-volume-slider') || document.getElementById('volume-slider');
  const bgVolumeVal = document.getElementById('bg-volume-val') || document.getElementById('volume-val');
  const scareVolumeSlider = document.getElementById('scare-volume-slider') || document.getElementById('sound-volume-slider');
  const scareVolumeVal = document.getElementById('scare-volume-val') || document.getElementById('sound-volume-val');
  const btnMute = document.getElementById('btn-mute');
  const toggleDisabled = document.getElementById('toggle-disabled');
  const btnEmergency = document.getElementById('btn-emergency');
  const toastContainer = document.getElementById('toast-container');
  const bgSelect = document.getElementById('bg-select');
  const btnChangeBg = document.getElementById('btn-change-bg');
  const bgActiveName = document.getElementById('bg-active-name');
  const effectsGrid = document.getElementById('effects-grid');
  const soundsGrid = document.getElementById('sounds-grid');

  // Autopilot DOM
  const toggleAutopilot = document.getElementById('toggle-autopilot');
  const autopilotDetails = document.getElementById('autopilot-details');
  const autopilotStatusBanner = document.getElementById('autopilot-status-banner');
  const autopilotStatusText = document.getElementById('autopilot-status-text');
  const autopilotStatusIcon = document.getElementById('autopilot-status-icon');
  const autopilotMode = document.getElementById('autopilot-mode');
  const autopilotIntervalPreset = document.getElementById('autopilot-interval-preset');

  // Video Optimizer DOM
  const btnOptimizeMedia = document.getElementById('btn-optimize-media');
  const btnOptText = document.getElementById('btn-opt-text');
  const btnOptIcon = document.getElementById('btn-opt-icon');
  const optHealthBadge = document.getElementById('opt-health-badge');
  const optProgressBox = document.getElementById('opt-progress-box');
  const optProgressLabel = document.getElementById('opt-progress-label');
  const optProgressBarFill = document.getElementById('opt-progress-bar-fill');

  let cachedBackgrounds = [];
  let cachedSounds = [];


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

    // Alleen effecten tonen waarvoor daadwerkelijk een mediabestand op schijf staat
    const configuredEffects = effects.filter(eff => eff.configured && eff.file_exists);
    const configuredIds = new Set(configuredEffects.map(eff => eff.id));

    // Verwijder knoppen die geen bestand (meer) hebben op schijf
    document.querySelectorAll('.btn-effect[data-effect-id]').forEach(btn => {
      const id = btn.dataset.effectId;
      if (!configuredIds.has(id)) {
        btn.remove();
      }
    });

    configuredEffects.forEach(eff => {
      let btn = document.querySelector(`.btn-effect[data-effect-id="${eff.id}"]`);
      if (!btn && grid) {
        // Maak knop aan voor gevonden jumpscare/effect
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
      }
    });
  }

  // Geluidseffecten knoppen genereren en bijwerken
  function renderSounds(sounds) {
    if (!soundsGrid) return;
    if (!sounds || !Array.isArray(sounds) || sounds.length === 0) {
      if (soundsGrid.children.length === 0 || soundsGrid.querySelector('.btn-sound') === null) {
        soundsGrid.innerHTML = `
          <div class="no-sounds-hint" id="no-sounds-hint">
            <span>ℹ️ Geen MP3's gevonden.</span><br>
            Plaats <code>.mp3</code> bestanden in <code>media/audio/</code>.
          </div>
        `;
      }
      return;
    }

    cachedSounds = sounds;
    const noSoundsHint = document.getElementById('no-sounds-hint');
    if (noSoundsHint) noSoundsHint.remove();

    sounds.forEach(snd => {
      let btn = soundsGrid.querySelector(`.btn-sound[data-sound-id="${snd.id}"]`);
      if (!btn) {
        btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn-sound';
        btn.dataset.soundId = snd.id;
        btn.title = snd.filename || snd.name;
        btn.innerHTML = `
          <span class="sound-icon">${snd.icon || '🔊'}</span>
          <span class="sound-name">${snd.name}</span>
        `;
        btn.addEventListener('click', () => handleSoundClick(btn));
        soundsGrid.appendChild(btn);
      } else {
        const nameSpan = btn.querySelector('.sound-name');
        if (nameSpan) nameSpan.textContent = snd.name;
      }
    });
  }

  let lastSoundClickTime = 0;
  function handleSoundClick(btn) {
    const now = Date.now();
    if (now - lastSoundClickTime < 250) return;
    lastSoundClickTime = now;

    const soundId = btn.dataset.soundId;
    if (!soundId) return;

    if (effectsDisabled) {
      showToast('Effecten zijn momenteel uitgeschakeld.', true);
      return;
    }

    // Als dit specifieke geluid momenteel al actief is: STOP HET EFFECT!
    if (activeSoundIds.has(soundId)) {
      vibrate([40, 30]);
      btn.classList.remove('is-active', 'playing');
      activeSoundIds.delete(soundId);
      sendCommand('stop_sound', { sound_id: soundId });
      showToast(`Geluid gestopt`);
      return;
    }

    // Anders: Start het geluidseffect en highlight de knop
    vibrate(30);
    btn.classList.add('is-active', 'playing');
    activeSoundIds.add(soundId);

    sendCommand('play_sound', { sound_id: soundId });
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
      if (data.sounds) {
        renderSounds(data.sounds);
      }
      if (data.status) {
        if (data.status.bg_volume !== undefined) setBgVolumeUI(data.status.bg_volume);
        else if (data.status.volume !== undefined) setBgVolumeUI(data.status.volume);

        if (data.status.scare_volume !== undefined) setScareVolumeUI(data.status.scare_volume);
        else if (data.status.sound_volume !== undefined) setScareVolumeUI(data.status.sound_volume);

        if (data.status.muted !== undefined) setMuteUI(data.status.muted);
        if (data.status.disabled !== undefined) setDisabledUI(data.status.disabled);
        if (data.status.active_effect_id) {
          startActiveBanner(data.status.active_effect_id, 15);
        }
      }
      if (data.autopilot) {
        setAutopilotUI(data.autopilot);
      }
      if (data.media_health) {
        setMediaHealthUI(data.media_health);
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
    } else if (type === 'sound_ack') {
      if (data.success) {
        vibrate(40);
        showToast(`🔊 Geluid: ${data.name || data.sound_id}`);
      } else {
        const btn = soundsGrid ? soundsGrid.querySelector(`.btn-sound[data-sound-id="${data.sound_id}"]`) : null;
        if (btn) btn.classList.remove('is-active', 'playing');
        activeSoundIds.delete(data.sound_id);
        showToast(data.reason || 'Kan geluid niet starten.', true);
      }
    } else if (type === 'sound_triggered') {
      activeSoundIds.add(data.sound_id);
      const btn = soundsGrid ? soundsGrid.querySelector(`.btn-sound[data-sound-id="${data.sound_id}"]`) : null;
      if (btn) {
        btn.classList.add('is-active', 'playing');
      }
    } else if (type === 'sound_stopped') {
      activeSoundIds.delete(data.sound_id);
      const btn = soundsGrid ? soundsGrid.querySelector(`.btn-sound[data-sound-id="${data.sound_id}"]`) : null;
      if (btn) {
        btn.classList.remove('is-active', 'playing');
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
      if (data.bg_volume !== undefined) setBgVolumeUI(data.bg_volume);
      else if (data.volume !== undefined) setBgVolumeUI(data.volume);

      if (data.scare_volume !== undefined) setScareVolumeUI(data.scare_volume);
      else if (data.sound_volume !== undefined) setScareVolumeUI(data.sound_volume);

      if (data.muted !== undefined) setMuteUI(data.muted);
    } else if (type === 'autopilot_update') {
      if (data.autopilot) {
        setAutopilotUI(data.autopilot);
      }
    } else if (type === 'media_optimize_progress') {
      handleOptimizeProgress(data.optimize_status);
    } else if (type === 'media_optimize_done') {
      handleOptimizeDone(data.result, data.media_health);
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

  // Audio UI
  function setBgVolumeUI(vol) {
    currentBgVolume = vol;
    if (bgVolumeSlider) bgVolumeSlider.value = Math.round(vol * 100);
    if (bgVolumeVal) bgVolumeVal.textContent = `${Math.round(vol * 100)}%`;
  }

  function setScareVolumeUI(vol) {
    currentScareVolume = vol;
    if (scareVolumeSlider) scareVolumeSlider.value = Math.round(vol * 100);
    if (scareVolumeVal) scareVolumeVal.textContent = `${Math.round(vol * 100)}%`;
  }

  // Backward compatibility alias
  function setVolumeUI(vol) {
    setBgVolumeUI(vol);
  }
  function setSoundVolumeUI(vol) {
    setScareVolumeUI(vol);
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

  // Autopilot UI
  function updateAutopilotCountdownText() {
    if (!autopilotStatusText || !autopilotStatusIcon) return;
    if (!toggleAutopilot || !toggleAutopilot.checked) {
      autopilotStatusIcon.textContent = '💤';
      autopilotStatusText.textContent = 'Autopilot staat uit';
      if (autopilotStatusBanner) autopilotStatusBanner.classList.remove('active-firing');
      return;
    }

    if (autopilotRemainingSeconds <= 0) {
      autopilotStatusIcon.textContent = '⚡';
      autopilotStatusText.textContent = 'Scare wordt afgevuurd...';
      if (autopilotStatusBanner) autopilotStatusBanner.classList.add('active-firing');
    } else {
      if (autopilotStatusBanner) autopilotStatusBanner.classList.remove('active-firing');
      autopilotStatusIcon.textContent = '⏳';
      const typeLabel = autopilotNextType === 'sound' ? 'Geluid' : autopilotNextType === 'jumpscare' ? 'Jumpscare' : 'Willekeurig';
      const timeStr = autopilotRemainingSeconds >= 60 ? `${(autopilotRemainingSeconds / 60).toFixed(1)} min` : `${autopilotRemainingSeconds}s`;
      autopilotStatusText.textContent = `Volgende scare over ca. ${timeStr} (${typeLabel})`;
    }
  }

  function setAutopilotUI(ap) {
    if (!ap) return;
    if (toggleAutopilot) toggleAutopilot.checked = !!ap.enabled;
    if (autopilotDetails) {
      if (ap.enabled) autopilotDetails.classList.remove('is-disabled');
      else autopilotDetails.classList.add('is-disabled');
    }
    if (autopilotMode && ap.mode) autopilotMode.value = ap.mode;

    clearInterval(autopilotCountdownTimer);
    autopilotRemainingSeconds = ap.next_trigger_in || 0;
    autopilotNextType = ap.next_trigger_type || 'jumpscare';

    updateAutopilotCountdownText();

    if (ap.enabled && autopilotRemainingSeconds > 0) {
      autopilotCountdownTimer = setInterval(() => {
        autopilotRemainingSeconds--;
        updateAutopilotCountdownText();
        if (autopilotRemainingSeconds <= 0) {
          clearInterval(autopilotCountdownTimer);
        }
      }, 1000);
    }
  }

  // Media Health UI
  function setMediaHealthUI(report) {
    if (!report || !optHealthBadge) return;
    if (report.needs_optimization > 0) {
      optHealthBadge.className = 'opt-badge badge-warn';
      optHealthBadge.textContent = `⚠️ ${report.needs_optimization} te optimaliseren`;
    } else {
      optHealthBadge.className = 'opt-badge badge-ok';
      optHealthBadge.textContent = '✅ Alles optimaal';
    }

    if (btnOptimizeMedia) {
      if (report.is_optimizing) {
        btnOptimizeMedia.disabled = true;
        if (btnOptText) btnOptText.textContent = 'Optimalisatie loopt...';
        if (btnOptIcon) btnOptIcon.textContent = '⏳';
      } else {
        btnOptimizeMedia.disabled = false;
        if (btnOptText) btnOptText.textContent = 'Optimaliseer Media Nu';
        if (btnOptIcon) btnOptIcon.textContent = '⚡';
      }
    }
  }

  function handleOptimizeProgress(status) {
    if (!status) return;
    if (optProgressBox) optProgressBox.style.display = 'block';
    if (btnOptimizeMedia) btnOptimizeMedia.disabled = true;
    if (btnOptText) btnOptText.textContent = 'Optimaliseren...';
    if (btnOptIcon) btnOptIcon.textContent = '⏳';

    if (optProgressLabel) {
      optProgressLabel.textContent = `${status.current_file || ''}: ${status.step || 'Verwerken...'}`;
    }
    if (optProgressBarFill) {
      const pct = status.total > 0 ? Math.round((status.processed / status.total) * 100) : 50;
      optProgressBarFill.style.width = `${pct}%`;
    }
  }

  function handleOptimizeDone(result, health) {
    if (btnOptimizeMedia) btnOptimizeMedia.disabled = false;
    if (btnOptText) btnOptText.textContent = 'Optimaliseer Media Nu';
    if (btnOptIcon) btnOptIcon.textContent = '⚡';

    if (optProgressLabel) optProgressLabel.textContent = 'Voltooid! Alle media is nu geoptimaliseerd.';
    if (optProgressBarFill) optProgressBarFill.style.width = '100%';

    setTimeout(() => {
      if (optProgressBox) optProgressBox.style.display = 'none';
    }, 4000);

    if (health) setMediaHealthUI(health);
    showToast('⚡ Media optimalisatie voltooid! Video\'s starten vloeiend en audio is gebalanceerd.');
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
    } else if (action === 'play_sound') {
      const soundUrl = '/api/sound' + (token ? '?token=' + encodeURIComponent(token) : '');
      fetch(soundUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sound_id: payload.sound_id })
      })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          vibrate(40);
          showToast(`🔊 Geluid: ${data.sound?.name || payload.sound_id}`);
        } else {
          showToast(data.detail || 'Kan geluid niet starten.', true);
        }
      })
      .catch(() => {
        showToast('Kan server niet bereiken.', true);
      });
    } else if (action === 'stop_sound') {
      const stopSoundUrl = '/api/sound/stop' + (token ? '?token=' + encodeURIComponent(token) : '');
      fetch(stopSoundUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sound_id: payload.sound_id })
      }).catch(() => {});
    } else if (action === 'set_bg_volume' || action === 'set_volume') {
      const volUrl = '/api/volume' + (token ? '?token=' + encodeURIComponent(token) : '');
      fetch(volUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bg_volume: payload.bg_volume !== undefined ? payload.bg_volume : payload.volume })
      }).catch(() => {});
    } else if (action === 'set_scare_volume' || action === 'set_sound_volume') {
      const volUrl = '/api/volume' + (token ? '?token=' + encodeURIComponent(token) : '');
      fetch(volUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scare_volume: payload.scare_volume !== undefined ? payload.scare_volume : payload.volume })
      }).catch(() => {});
    } else if (action === 'toggle_autopilot') {
      const apUrl = '/api/autopilot' + (token ? '?token=' + encodeURIComponent(token) : '');
      fetch(apUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: payload.enabled })
      }).catch(() => {});
    } else if (action === 'set_autopilot_config') {
      const apUrl = '/api/autopilot' + (token ? '?token=' + encodeURIComponent(token) : '');
      fetch(apUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }).catch(() => {});
    } else if (action === 'optimize_media') {
      const optUrl = '/api/media/optimize' + (token ? '?token=' + encodeURIComponent(token) : '');
      fetch(optUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      }).catch(() => {});
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

  // Event Listeners voor statisch gerenderde Geluidseffectknoppen
  document.querySelectorAll('.btn-sound').forEach(btn => {
    btn.addEventListener('click', () => handleSoundClick(btn));
  });

  // Event delegation op soundsGrid voor dynamische soundknoppen
  if (soundsGrid) {
    soundsGrid.addEventListener('click', (e) => {
      const btn = e.target.closest('.btn-sound');
      if (btn) {
        handleSoundClick(btn);
      }
    });
  }

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

  // Achtergrond Video Volume slider
  if (bgVolumeSlider) {
    bgVolumeSlider.addEventListener('input', (e) => {
      const vol = parseFloat(e.target.value) / 100;
      setBgVolumeUI(vol);
      sendCommand('set_bg_volume', { bg_volume: vol, volume: vol });
    });
  }

  // Scares & Sound Effects Volume slider
  if (scareVolumeSlider) {
    scareVolumeSlider.addEventListener('input', (e) => {
      const vol = parseFloat(e.target.value) / 100;
      setScareVolumeUI(vol);
      sendCommand('set_scare_volume', { scare_volume: vol, sound_volume: vol });
    });
  }

  // Mute knop
  if (btnMute) {
    btnMute.addEventListener('click', () => {
      vibrate(20);
      sendCommand('toggle_mute');
    });
  }

  // Autopilot Schakelaar & Instellingen
  if (toggleAutopilot) {
    toggleAutopilot.addEventListener('change', (e) => {
      vibrate(25);
      const enabled = e.target.checked;
      sendCommand('toggle_autopilot', { enabled });
      showToast(enabled ? '⏱️ Autopilot ingeschakeld' : 'Autopilot uitgeschakeld');
    });
  }

  if (autopilotMode) {
    autopilotMode.addEventListener('change', (e) => {
      vibrate(20);
      const mode = e.target.value;
      sendCommand('set_autopilot_config', { mode });
      showToast(`Autopilot modus: ${mode === 'both' ? 'Beide' : mode === 'jumpscare' ? 'Alleen Jumpscares' : 'Alleen Geluiden'}`);
    });
  }

  if (autopilotIntervalPreset) {
    autopilotIntervalPreset.addEventListener('change', (e) => {
      vibrate(20);
      const val = e.target.value;
      let minMin = 1.0;
      let maxMin = 6.0;
      if (val === '1-3') { minMin = 1.0; maxMin = 3.0; }
      else if (val === '3-8') { minMin = 3.0; maxMin = 8.0; }
      else if (val === '0.5-1.5') { minMin = 0.5; maxMin = 1.5; }
      else { minMin = 1.0; maxMin = 6.0; }

      sendCommand('set_autopilot_config', { min_minutes: minMin, max_minutes: maxMin });
      showToast(`Interval ingesteld op ${minMin} - ${maxMin} min.`);
    });
  }

  // Video Optimalisatie Knop
  if (btnOptimizeMedia) {
    btnOptimizeMedia.addEventListener('click', () => {
      vibrate(35);
      if (optProgressBox) optProgressBox.style.display = 'block';
      if (optProgressLabel) optProgressLabel.textContent = 'Optimalisatie starten...';
      sendCommand('optimize_media');
      showToast('⚡ Video optimalisatie gestart op de achtergrond...');
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

  // Kolommen layout schakelaar (3 of 4 kolommen) voor Video Effecten & Geluidseffecten
  const btnCol3 = document.getElementById('btn-col-3');
  const btnCol4 = document.getElementById('btn-col-4');
  const btnSoundCol3 = document.getElementById('btn-sound-col-3');
  const btnSoundCol4 = document.getElementById('btn-sound-col-4');

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

  function setSoundGridColumns(cols) {
    const sGrid = soundsGrid || document.getElementById('sounds-grid');
    if (!sGrid) return;
    if (cols === 4) {
      sGrid.classList.add('cols-4');
      sGrid.classList.remove('cols-3');
      if (btnSoundCol4) btnSoundCol4.classList.add('active');
      if (btnSoundCol3) btnSoundCol3.classList.remove('active');
      try { localStorage.setItem('halloween_sound_grid_cols', '4'); } catch (e) {}
    } else {
      sGrid.classList.add('cols-3');
      sGrid.classList.remove('cols-4');
      if (btnSoundCol3) btnSoundCol3.classList.add('active');
      if (btnSoundCol4) btnSoundCol4.classList.remove('active');
      try { localStorage.setItem('halloween_sound_grid_cols', '3'); } catch (e) {}
    }
  }

  if (btnCol3) {
    btnCol3.addEventListener('click', () => {
      vibrate(20);
      setGridColumns(3);
      if (!localStorage.getItem('halloween_sound_grid_cols')) {
        setSoundGridColumns(3);
      }
    });
  }
  if (btnCol4) {
    btnCol4.addEventListener('click', () => {
      vibrate(20);
      setGridColumns(4);
      if (!localStorage.getItem('halloween_sound_grid_cols')) {
        setSoundGridColumns(4);
      }
    });
  }

  if (btnSoundCol3) {
    btnSoundCol3.addEventListener('click', () => {
      vibrate(20);
      setSoundGridColumns(3);
    });
  }
  if (btnSoundCol4) {
    btnSoundCol4.addEventListener('click', () => {
      vibrate(20);
      setSoundGridColumns(4);
    });
  }

  // Laad opgeslagen kolomvoorkeuren (standaard 3 kolommen)
  try {
    const savedCols = parseInt(localStorage.getItem('halloween_grid_cols') || '3', 10);
    setGridColumns(savedCols === 4 ? 4 : 3);
  } catch (e) {}

  try {
    const savedSoundCols = parseInt(localStorage.getItem('halloween_sound_grid_cols') || localStorage.getItem('halloween_grid_cols') || '3', 10);
    setSoundGridColumns(savedSoundCols === 4 ? 4 : 3);
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
          if (data.engine.bg_volume !== undefined) setBgVolumeUI(data.engine.bg_volume);
          else if (data.engine.volume !== undefined) setBgVolumeUI(data.engine.volume);

          if (data.engine.scare_volume !== undefined) setScareVolumeUI(data.engine.scare_volume);
          else if (data.engine.sound_volume !== undefined) setScareVolumeUI(data.engine.sound_volume);

          if (data.engine.muted !== undefined) setMuteUI(data.engine.muted);
          if (data.engine.active_effect_id) {
            startActiveBanner(data.engine.active_effect_id, 15);
          } else {
            stopActiveBanner();
          }
        }
        if (data.autopilot) {
          setAutopilotUI(data.autopilot);
        }
        if (data.media_health) {
          setMediaHealthUI(data.media_health);
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

    // Haal status, achtergronden, effecten en geluiden direct op
    syncServerStatus();

    fetch('/api/effects' + (token ? '?token=' + encodeURIComponent(token) : ''))
      .then(res => res.json())
      .then(data => {
        if (data) {
          if (data.backgrounds) renderBackgrounds(data.backgrounds, data.background);
          if (data.effects) renderEffects(data.effects);
          if (data.sounds) renderSounds(data.sounds);
        }
      })
      .catch(() => {});

    // Periodieke controle om nieuwe effecten, achtergronden & geluiden automatisch te activeren
    setInterval(() => {
      fetch('/api/effects' + (token ? '?token=' + encodeURIComponent(token) : ''))
        .then(res => res.json())
        .then(data => {
          if (data) {
            if (data.backgrounds) renderBackgrounds(data.backgrounds, data.background);
            if (data.effects) renderEffects(data.effects);
            if (data.sounds) renderSounds(data.sounds);
          }
        })
        .catch(() => {});
    }, 4000);
  });
})();

