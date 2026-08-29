/**
 * TwinPilot AI Cockpit — UI Interaction & Sound Engine
 * ====================================================
 * Handles client-side audio feedback, interactive chat Q&A, and toast notifications.
 * State rendering is fully owned by twinpilot_bridge.js from backend factory_state.
 */

// --- Web Audio Synth for High-Tech Factory UI Sounds ---
let audioCtx = null;
function playSound(type) {
  try {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioCtx.state === 'suspended') {
      audioCtx.resume();
    }
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    const now = audioCtx.currentTime;

    if (type === 'beep') {
      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, now);
      gain.gain.setValueAtTime(0.04, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.1);
      osc.start(now); osc.stop(now + 0.1);
    } else if (type === 'alert') {
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(330, now);
      osc.frequency.linearRampToValueAtTime(440, now + 0.15);
      osc.frequency.linearRampToValueAtTime(330, now + 0.3);
      gain.gain.setValueAtTime(0.03, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.3);
      osc.start(now); osc.stop(now + 0.3);
    } else if (type === 'critical') {
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(220, now);
      osc.frequency.linearRampToValueAtTime(293, now + 0.2);
      gain.gain.setValueAtTime(0.06, now);
      gain.gain.setValueAtTime(0.06, now + 0.15);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.4);
      osc.start(now); osc.stop(now + 0.4);
    } else if (type === 'chime') {
      osc.type = 'sine';
      osc.frequency.setValueAtTime(523.25, now);
      osc.frequency.setValueAtTime(659.25, now + 0.08);
      osc.frequency.setValueAtTime(783.99, now + 0.16);
      osc.frequency.setValueAtTime(1046.50, now + 0.24);
      gain.gain.setValueAtTime(0.05, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.5);
      osc.start(now); osc.stop(now + 0.5);
    }
  } catch (e) {
    console.warn("Audio Context blocked:", e);
  }
}

// --- Toast Notification Helper ---
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.style.cssText = `
    background: ${type === 'success' ? 'rgba(5,150,105,0.2)' : (type === 'critical' ? 'rgba(220,38,38,0.2)' : 'rgba(37,99,235,0.2)')};
    border: 1px solid ${type === 'success' ? 'rgba(5,150,105,0.5)' : (type === 'critical' ? 'rgba(220,38,38,0.5)' : 'rgba(37,99,235,0.5)')};
    backdrop-filter: blur(8px);
    border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;
    font-size: 12px; color: var(--text-primary); box-shadow: 0 4px 15px rgba(0,0,0,0.2);
  `;
  toast.innerText = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 6000);
}

// --- Interactive Chat with Causal AI ---
function sendChat() {
  const input = document.getElementById('chat-user-input');
  if (!input || !input.value.trim()) return;
  const question = input.value.trim();
  input.value = '';

  appendChatMessage('user', question);
  playSound('beep');

  setTimeout(() => {
    generateTwinAnswer(question);
  }, 400);
}

function handleChatEnter(event) {
  if (event.key === 'Enter') {
    sendChat();
  }
}

function askPredefined(question) {
  appendChatMessage('user', question);
  playSound('beep');
  setTimeout(() => {
    generateTwinAnswer(question);
  }, 400);
}

function appendChatMessage(sender, text) {
  const box = document.getElementById('chat-history-box');
  if (!box) return;
  const msg = document.createElement('div');
  msg.className = `chat-message ${sender}`;
  msg.style.cssText = sender === 'user'
    ? 'align-self: flex-end; background: var(--accent-info-bg); border: 1px solid rgba(37,99,235,0.3); padding: 8px 12px; border-radius: 10px 10px 0 10px; margin-bottom: 8px; max-width: 85%; font-size: 12px;'
    : 'align-self: flex-start; background: rgba(0,0,0,0.05); border: 1px solid var(--border-color); padding: 8px 12px; border-radius: 10px 10px 10px 0; margin-bottom: 8px; max-width: 85%; font-size: 12px;';
  msg.innerHTML = text;
  box.appendChild(msg);
  box.scrollTop = box.scrollHeight;
}

async function generateTwinAnswer(q) {
  const box = document.getElementById('chat-history-box');
  let thinkingMsg = null;
  if (box) {
    thinkingMsg = document.createElement('div');
    thinkingMsg.className = 'chat-message bot';
    thinkingMsg.style.cssText = 'align-self: flex-start; background: rgba(0,0,0,0.05); border: 1px dashed var(--border-color); padding: 8px 12px; border-radius: 10px 10px 10px 0; margin-bottom: 8px; max-width: 85%; font-size: 12px; color: var(--text-secondary); font-style: italic;';
    thinkingMsg.innerHTML = '<span style="display:inline-block; animation: pulse 1.2s infinite;">⚡</span> Analyzing factory telemetry & causal model...';
    box.appendChild(thinkingMsg);
    box.scrollTop = box.scrollHeight;
  }

  const state = window.latestFactoryState;
  const cfg = window.activeCfg || {};

  try {
    const payload = {
      question: q,
      run_id: cfg.run_id || (state ? state.current_run_id : "RUN-024"),
      minute: cfg.minute || (state ? state.current_minute_index : 143),
      station: cfg.station || (state && state.target_station ? state.target_station.station_id : "S03"),
      event_id: cfg.event_id || "RUN024-EVT01",
      step_id: typeof selectedTimelineStepIdx !== "undefined" ? selectedTimelineStepIdx : (state ? state.current_step_id : 3)
    };

    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (thinkingMsg && thinkingMsg.parentNode) {
      thinkingMsg.parentNode.removeChild(thinkingMsg);
    }

    if (res.ok) {
      const data = await res.json();
      appendChatMessage('bot', data.reply || "No response received from TwinPilot AI.");
      playSound('beep');
    } else {
      throw new Error(`API error ${res.status}`);
    }
  } catch (err) {
    if (thinkingMsg && thinkingMsg.parentNode) {
      thinkingMsg.parentNode.removeChild(thinkingMsg);
    }
    // Fallback response if offline
    appendChatMessage('bot', fallbackLocalAnswer(q, state));
    playSound('beep');
  }
}

function fallbackLocalAnswer(q, state) {
  const qLower = q.toLowerCase();
  if (qLower.includes("how many station") || qLower.includes("total station")) {
    return "The TwinPilot platform monitors a total of <strong>31 production stations</strong> (30 mainline S01-S30 + 1 dedicated feeder ENG01) across Body Construction, Paint, and Final Assembly.";
  }
  if (qLower.includes("feature") || qLower.includes("what can we do")) {
    return "TwinPilot provides real-time digital twin streaming, early anomaly precursor forecasting, 3-factor root cause localization, defect propagation traversal, Dark Zone sensorless inference, vehicle quarantine tracking, counterfactual what-if simulation (Options A/B/C), and reinforcement learning governance.";
  }
  if (state && state.target_station) {
    const target = state.target_station;
    return `Station <strong>${target.station_id} (${target.station_name})</strong> cycle time: <strong>${target.cycle_time_sec}s</strong>. Queue: <strong>${target.queue_length}</strong> vehicles. Defect risk: <strong>${target.defect_prob_pct}%</strong>.`;
  }
  return "TwinPilot AI is actively monitoring 31 stations across Body, Paint, and Final Assembly.";
}

// --- DOM Initializer ---
document.addEventListener('DOMContentLoaded', () => {
  if (typeof lucide !== 'undefined') lucide.createIcons();

  // Attach generic click sounds
  document.body.addEventListener('click', (e) => {
    const el = e.target.closest('button, .quick-ask-chip, .nav-item a');
    if (el && !el.id.includes('approve') && !el.id.includes('reject')) {
      playSound('beep');
    }
  });

  // Wire play/pause button
  const playPauseBtn = document.getElementById('btn-play-pause');
  if (playPauseBtn) {
    playPauseBtn.addEventListener('click', () => {
      showToast('Live digital twin streaming.', 'info');
    });
  }

  // Wire replay button
  const replayBtn = document.getElementById('btn-replay');
  if (replayBtn) {
    replayBtn.addEventListener('click', () => {
      playSound('chime');
      showToast('Replaying scenario telemetry from baseline minute.', 'info');
      if (typeof TwinPilotAPI !== 'undefined' && window.activeCfg) {
        TwinPilotAPI.loadScenario(window.activeCfg);
      }
    });
  }
});
