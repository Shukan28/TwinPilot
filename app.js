// ==========================================
// TwinPilot AI Cockpit - Multi-Page Sync Logic
// ==========================================

const defaultState = {
  activeStep: 0,        // 0: Normal, 1: Anomaly, 2: Prediction, -1: Stress
  isPlaying: true,
  selectedScenario: 'C',
  trustScore: 94,
  overallHealth: 98.4,
  throughput: 42.2,
  isStressed: false,
  isStressSolved: false,
  stepProgress: 0,
  auditLogs: [
    "[10:02 AM] System: Running nominal AI forecasting loops.",
    "[Yesterday 14:35] Operator (ID-4890) rejected Option A speed increases. Logged: safety drill override.",
    "[Aug 14 09:15] System Autonomous override: Adjusted Station 5 conveyor limits."
  ],
  chatHistory: [
    { sender: 'bot', text: "Hello, I am TwinPilot AI. Ask me anything about the current state, predicted anomalies, or scenario mitigations." }
  ]
};

let state = { ...defaultState };

// --- Station Nominal Configs ---
const stations = {
  S1: { name: 'Stamping', baseCycle: 42.1 },
  S2: { name: 'Welding', baseCycle: 38.4 },
  S3: { name: 'Underbody', baseCycle: 45.0 },
  S4: { name: 'Painting', baseCycle: 40.2 },
  S5: { name: 'Powertrain', baseCycle: 44.1 },
  S6: { name: 'Doors', baseCycle: 41.3 },
  S7: { name: 'Interior', baseCycle: 43.5 },
  S8: { name: 'Electronics', baseCycle: 36.2 }, // Sensorless
  S9: { name: 'Final Insp.', baseCycle: 48.9 },
};

// --- Web Audio Synth for High-tech UI Sounds ---
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

// --- LocalStorage State Management ---
function saveState() {
  localStorage.setItem('twinpilot_state', JSON.stringify(state));
  updatePageUI();
}

function loadState() {
  const data = localStorage.getItem('twinpilot_state');
  if (data) {
    state = JSON.parse(data);
  } else {
    state = { ...defaultState };
  }
  updatePageUI();
}

// --- Initial Setup ---
document.addEventListener('DOMContentLoaded', () => {
  // Initial load
  loadState();

  // Initialize Lucide Icons
  lucide.createIcons();

  // Sync state between tabs dynamically
  window.addEventListener('storage', (e) => {
    if (e.key === 'twinpilot_state') {
      loadState();
    }
  });

  // Attach generic click sounds
  document.body.addEventListener('click', (e) => {
    const el = e.target.closest('button, .timeline-step, .quick-ask-chip, .nav-item a');
    if (el) {
      const id = el.id || '';
      if (!id.includes('approve') && !id.includes('stress') && !id.includes('reject')) {
        playSound('beep');
      }
    }
  });

  // Wire up play/pause button
  const playPauseBtn = document.getElementById('btn-play-pause');
  if (playPauseBtn) {
    playPauseBtn.addEventListener('click', () => {
      state.isPlaying = !state.isPlaying;
      saveState();
      showToast(state.isPlaying ? 'Simulation resumed.' : 'Simulation paused.', 'info');
    });
  }

  // Wire up replay button
  const replayBtn = document.getElementById('btn-replay');
  if (replayBtn) {
    replayBtn.addEventListener('click', () => {
      playSound('chime');
      showToast('Replaying demo timeline from 10:02 AM', 'info');
      state = {
        ...defaultState,
        auditLogs: [ ...defaultState.auditLogs ],
        chatHistory: [ ...defaultState.chatHistory ]
      };
      saveState();
    });
  }

  // Start cycles jitter
  setInterval(jitterStationCycles, 1000);

  // Start timeline clock tick
  setInterval(runClockTicker, 1000);

  // Start tagline rotators if on index.html
  initTaglineRotator();
});

// --- Timeline Clocks and Tickers ---
function runClockTicker() {
  if (state.isStressed) {
    jitterStationCycles();
    return;
  }
  
  if (state.isPlaying) {
    state.stepProgress += 1;
    if (state.stepProgress >= 15) { // 15s per step
      state.stepProgress = 0;
      state.activeStep = (state.activeStep + 1) % 3;
      
      // Update state parameters
      if (state.activeStep === 0) {
        state.overallHealth = 98.4;
        state.throughput = 42.2;
      } else if (state.activeStep === 1) {
        state.overallHealth = 89.2;
        state.throughput = 40.5;
        playSound('alert');
      } else if (state.activeStep === 2) {
        state.overallHealth = 78.1;
        state.throughput = 36.4;
        playSound('alert');
      }
      saveState();
    } else {
      // Sync clock readout
      updateClockReadout();
    }
  }
}

function updateClockReadout() {
  const clockEl = document.getElementById('sim-clock');
  if (clockEl) {
    let min = 2 + (state.activeStep * 3);
    let sec = state.stepProgress;
    if (state.activeStep === -1) { // Stress
      min = 9;
      sec = 12;
    }
    const secStr = sec < 10 ? '0' + sec : sec;
    clockEl.innerText = `10:0${min}:${secStr} AM`;
  }
}

// --- Home Tagline Rotator ---
let taglineIndex = 0;
function initTaglineRotator() {
  const taglines = [
    document.getElementById('tagline-0'),
    document.getElementById('tagline-1'),
    document.getElementById('tagline-2'),
    document.getElementById('tagline-3')
  ];
  if (!taglines[0]) return; // Not on index.html

  setInterval(() => {
    taglines[taglineIndex].classList.remove('visible');
    taglineIndex = (taglineIndex + 1) % taglines.length;
    taglines[taglineIndex].classList.add('visible');
  }, 2500);

  // Animate the loop diagram nodes sequentially
  const nodeIds = ['node-data', 'node-twin', 'node-predict', 'node-experiment', 'node-compare', 'node-recommend', 'node-approve', 'node-learn'];
  const labelIds = ['lbl-data', 'lbl-twin', 'lbl-predict', 'lbl-experiment', 'lbl-compare', 'lbl-recommend', 'lbl-approve', 'lbl-learn'];
  let loopIdx = 0;

  setInterval(() => {
    // Remove active from all
    nodeIds.forEach((id, i) => {
      const n = document.getElementById(id);
      const l = document.getElementById(labelIds[i]);
      if (n) n.classList.remove('active');
      if (l) l.classList.remove('active');
    });
    // Add active to current
    const activeNode = document.getElementById(nodeIds[loopIdx]);
    const activeLabel = document.getElementById(labelIds[loopIdx]);
    if (activeNode) activeNode.classList.add('active');
    if (activeLabel) activeLabel.classList.add('active');
    loopIdx = (loopIdx + 1) % nodeIds.length;
  }, 800);
}

// --- Page UI Updates Engine ---
function updatePageUI() {
  updateCommonStats();
  updateTimelineControlUI();
  updateStationsNodeUI();
  updatePredictiveAlertUI();
  updateWhatIfSimulatorUI();
  updateCausalChainUI();
  updateSensorlessInferenceUI();
  updateChatHistoryUI();
  updateTrustScoreUI();
  updateAuditLogUI();
}

// --- Widgets Rendering ---

function updateCommonStats() {
  // Update header overall health
  const healthEl = document.getElementById('factory-overall-health');
  if (healthEl) {
    healthEl.innerText = state.overallHealth.toFixed(1) + "%";
    healthEl.style.color = state.overallHealth > 90 ? "var(--accent-healthy)" : (state.overallHealth > 75 ? "var(--accent-warning)" : "var(--accent-critical)");
  }

  // Update throughput
  const tputEl = document.getElementById('factory-throughput');
  if (tputEl) {
    tputEl.innerText = state.throughput.toFixed(1) + " u/h";
  }

  updateClockReadout();
}

function updateTimelineControlUI() {
  // Sync active step indicators
  document.querySelectorAll('.timeline-step').forEach((el, idx) => {
    el.classList.toggle('active', idx === state.activeStep);
    el.classList.toggle('completed', idx < state.activeStep && state.activeStep !== -1);
  });

  const playPauseBtn = document.getElementById('btn-play-pause');
  if (playPauseBtn) {
    playPauseBtn.innerHTML = state.isPlaying 
      ? `<i data-lucide="pause" style="width:14px;height:14px;"></i>` 
      : `<i data-lucide="play" style="width:14px;height:14px;"></i>`;
    lucide.createIcons();
  }
}

function updateStationsNodeUI() {
  const row = document.getElementById('stations-row');
  if (!row) return; // Not on dashboard/analytics

  // Reset to nominal first
  Object.keys(stations).forEach(key => {
    const el = document.getElementById(`node-${key}`);
    if (!el) return;
    
    if (key === 'S8') el.className = "station-node healthy sensorless";
    else el.className = "station-node healthy";
  });

  if (state.isStressed) {
    document.getElementById('node-S5').className = "station-node critical";
    document.getElementById('node-S6').className = "station-node critical";
    document.getElementById('node-S7').className = "station-node warning";
    document.getElementById('node-S8').className = "station-node warning sensorless";
    document.getElementById('node-S9').className = "station-node warning";
  } else if (state.activeStep === 1) {
    document.getElementById('node-S3').className = "station-node warning";
    document.getElementById('node-S6').className = "station-node warning";
    document.getElementById('node-S8').className = "station-node warning sensorless";
  } else if (state.activeStep === 2) {
    document.getElementById('node-S3').className = "station-node warning";
    document.getElementById('node-S5').className = "station-node warning";
    document.getElementById('node-S6').className = "station-node warning";
    document.getElementById('node-S7').className = "station-node warning";
    document.getElementById('node-S8').className = "station-node warning sensorless";
  }
}

function updatePredictiveAlertUI() {
  const card = document.getElementById('predictive-alert-card');
  if (!card) return;

  if (state.isStressed) {
    card.classList.add('active');
    card.className = "glass-card predictive-alert-card active critical-alert";
    card.querySelector('.alert-header span').innerText = "CRITICAL FAULT CASCADE IN PROGRESS";
    card.querySelector('.alert-message').innerHTML = `Station 5 (Powertrain) drivetrain motor fault detected. Line starvation will halt assembly line in <strong>4 minutes</strong>.`;
    card.querySelector('.alert-detail-value').innerText = "99% Probability";
  } else if (state.activeStep === 2) {
    card.classList.add('active');
    card.className = "glass-card predictive-alert-card active";
    card.querySelector('.alert-header span').innerText = "Bottleneck Predicted in 18 Minutes";
    card.querySelector('.alert-message').innerHTML = `Line simulation indicates Station 7 (Interior) has <strong>78% probability</strong> of buffer starvation/overflow due to upstream torque instability.`;
    card.querySelector('.alert-detail-value').innerText = "68% - 85%";
  } else {
    card.classList.remove('active');
  }
}

function updateWhatIfSimulatorUI() {
  const sect = document.getElementById('simulator-section');
  if (!sect) return;

  const cardA = document.getElementById('scenario-a');
  const cardB = document.getElementById('scenario-b');
  const cardC = document.getElementById('scenario-c');
  const impactText = document.getElementById('scenario-impact-text');
  const approveBtn = document.getElementById('btn-approve');

  // Toggle active styling card
  document.querySelectorAll('.scenario-card').forEach(el => el.classList.remove('active-option'));
  const activeCard = document.getElementById(`scenario-${state.selectedScenario.toLowerCase()}`);
  if (activeCard) activeCard.classList.add('active-option');

  if (state.isStressed) {
    // Stress options
    cardA.querySelector('.scenario-name').innerText = "Emergency Stop";
    cardA.querySelector('.scenario-badge').innerText = "Option A";
    cardA.querySelector('.scenario-impact').innerText = "Halts lines. Safety secure. Massive throughput penalty.";
    
    cardB.querySelector('.scenario-name').innerText = "Bypass via S8";
    cardB.querySelector('.scenario-badge').innerText = "AI Recommended";
    cardB.querySelector('.scenario-impact').innerText = "Reroutes components around S5. Operates at 82% capacity.";
    
    cardC.style.display = "none";

    if (state.isStressSolved) {
      approveBtn.disabled = true;
      approveBtn.innerText = "Bypass Route Active";
      document.getElementById('btn-reject').disabled = true;
      impactText.innerHTML = "Bypass channel active around S5 Powertrain module. Operational capacity stabilized at 82%.";
    } else {
      approveBtn.disabled = false;
      document.getElementById('btn-reject').disabled = false;
      if (state.selectedScenario === 'B') {
        approveBtn.innerText = "Deploy Emergency Plan";
        impactText.innerHTML = "Recommended action: Option B Bypass — prevents catastrophic block, preserves 82% capacity, limits downstream scrap loss.";
      } else {
        approveBtn.innerText = "Execute Line Shut Down";
        impactText.innerHTML = "Emergency option: Manual Shut Down — halts all manufacturing lines, resulting in <strong>~$42,000/hr</strong> in direct losses.";
      }
    }
  } else {
    // Normal/Anomaly options
    cardA.querySelector('.scenario-name').innerText = "Increase Speed";
    cardA.querySelector('.scenario-badge').innerText = "Option A";
    cardA.querySelector('.scenario-impact').innerText = "High risk of scrap buildup. Not recommended.";
    
    cardB.querySelector('.scenario-name').innerText = "Slow Station 5";
    cardB.querySelector('.scenario-badge').innerText = "Option B";
    cardB.querySelector('.scenario-impact').innerText = "Stable, but causes a minor throughput penalty.";

    cardC.style.display = "flex";
    cardC.querySelector('.scenario-name').innerText = "Reroute Workload";
    cardC.querySelector('.scenario-badge').innerText = "AI Recommended";
    cardC.querySelector('.scenario-impact').innerText = "Reroutes parts via Station 8. Prevents defect.";

    if (state.activeStep === 2 && !approveBtn.disabled) {
      approveBtn.disabled = false;
      document.getElementById('btn-reject').disabled = false;
    }

    if (state.selectedScenario === 'A') {
      impactText.innerHTML = `Option A — high cycle speed risks generating <strong>$12,000 in scrap</strong> and increases defect propagation to 84%.`;
      approveBtn.innerText = "Apply Scenario A";
    } else if (state.selectedScenario === 'B') {
      impactText.innerHTML = `Option B — buffering Station 5 prevents defect but slows line throughput, causing <strong>$4,500/hr</strong> capacity loss.`;
      approveBtn.innerText = "Apply Scenario B";
    } else if (state.selectedScenario === 'C') {
      impactText.innerHTML = `Recommended action: Option C — reroutes workload via Station 8, <strong>neutralizes $18,000 in scrap risk</strong>, maintains full throughput.`;
      approveBtn.innerText = "Approve Intervention";
    }
  }
}

function updateCausalChainUI() {
  // Works on analytics.html — look for a causal node to confirm we're on the right page
  const sect = document.getElementById('cnode-1');
  if (!sect) return;

  const node1 = document.getElementById('cnode-1');
  const node2 = document.getElementById('cnode-2');
  const node3 = document.getElementById('cnode-3');
  const node4 = document.getElementById('cnode-4');
  const arrow1 = document.getElementById('carrow-1');
  const arrow2 = document.getElementById('carrow-2');
  const arrow3 = document.getElementById('carrow-3');

  const riskLabel = document.getElementById('risk-vehicle-label');

  // Reset nominal
  node1.className = "causal-node";
  node2.className = "causal-node";
  node3.className = "causal-node";
  node4.className = "causal-node";
  arrow1.className = "causal-arrow";
  arrow2.className = "causal-arrow";
  arrow3.className = "causal-arrow";

  document.querySelectorAll('.vehicle-icon-card').forEach(el => el.className = "vehicle-icon-card");

  if (state.overallHealth > 95) {
    document.getElementById('prop-risk').innerText = "Low Risk (<1%)";
    document.getElementById('prop-risk').className = "prop-stat-val";
    document.getElementById('prop-cause').innerText = "None detected";
    document.getElementById('prop-reduction').innerText = "None required";
    riskLabel.innerText = "All vehicles secured";
    riskLabel.style.color = "var(--accent-healthy)";
    document.querySelectorAll('.vehicle-icon-card').forEach(el => el.className = "vehicle-icon-card healthy-car");
  } else if (state.activeStep === 1) {
    node1.className = "causal-node critical";
    node2.className = "causal-node critical";
    arrow1.className = "causal-arrow glowing";
    document.getElementById('prop-risk').innerText = "38% Risk";
    document.getElementById('prop-risk').className = "prop-stat-val highlight";
    document.getElementById('prop-cause').innerText = "S3 Cycle Spike";
    document.getElementById('prop-reduction').innerText = "Evaluating";
    
    document.getElementById('vehicle-2').className = "vehicle-icon-card at-risk";
    riskLabel.innerText = "VIN-2090 Flagged";
    riskLabel.style.color = "var(--accent-warning)";
  } else if (state.activeStep === 2) {
    node1.className = "causal-node critical";
    node2.className = "causal-node critical";
    node3.className = "causal-node critical";
    node4.className = "causal-node critical";
    arrow1.className = "causal-arrow glowing";
    arrow2.className = "causal-arrow glowing";
    arrow3.className = "causal-arrow glowing";
    
    document.getElementById('prop-risk').innerText = "61% Prob. to S9";
    document.getElementById('prop-risk').className = "prop-stat-val highlight";
    document.getElementById('prop-cause').innerText = "S3 Spike & S5 Drift";
    document.getElementById('prop-reduction').innerText = "94% Risk Mitigation";

    document.getElementById('vehicle-2').className = "vehicle-icon-card at-risk";
    document.getElementById('vehicle-3').className = "vehicle-icon-card at-risk";
    riskLabel.innerText = "VIN-2090 & VIN-2091 Flagged";
    riskLabel.style.color = "var(--accent-critical)";
  }
}

function updateSensorlessInferenceUI() {
  const badge = document.getElementById('inferred-s8-badge');
  if (!badge) return;

  const confidence = document.getElementById('sensorless-confidence');

  if (state.overallHealth > 95) {
    badge.className = "proxy-node sensorless-center";
    badge.innerText = state.selectedScenario === 'C' && state.activeStep === 0 ? "Nominal (Rerouted)" : "S8 Inferred Status";
    badge.style.borderColor = "var(--accent-healthy)";
    confidence.innerText = "Station 8 Confidence: 91%";
    confidence.style.color = "var(--accent-healthy)";
  } else if (state.activeStep === 1 || state.activeStep === 2 || state.isStressed) {
    badge.className = "proxy-node sensorless-center warning";
    badge.innerText = "S8 Degrading Cycle";
    badge.style.borderColor = "var(--accent-warning)";
    confidence.innerText = state.isStressed ? "Confidence: 61% (Bypass Mode)" : "Confidence: 74% (Disturbed)";
    confidence.style.color = "var(--accent-warning)";
  }
}

function updateChatHistoryUI() {
  const box = document.getElementById('chat-history-box');
  if (!box) return;

  box.innerHTML = "";
  state.chatHistory.forEach(msg => {
    const el = document.createElement('div');
    el.className = `chat-message ${msg.sender}`;
    el.innerText = msg.text;
    box.appendChild(el);
  });
  box.scrollTop = box.scrollHeight;
}

function updateTrustScoreUI() {
  const pctEl = document.getElementById('trust-score-pct');
  if (!pctEl) return;

  pctEl.innerText = state.trustScore + "%";

  const fillCircle = document.getElementById('trust-fill-circle');
  if (fillCircle) {
    const r = parseFloat(fillCircle.getAttribute('r'));
    const circumference = 2 * Math.PI * r;
    fillCircle.style.strokeDasharray = circumference;
    const offset = circumference - (state.trustScore / 100) * circumference;
    fillCircle.style.strokeDashoffset = offset;
    
    if (state.trustScore >= 95) {
      fillCircle.style.stroke = "var(--accent-healthy)";
    } else if (state.trustScore >= 90) {
      fillCircle.style.stroke = "var(--accent-warning)";
    } else {
      fillCircle.style.stroke = "var(--accent-critical)";
    }
  }
}

function updateAuditLogUI() {
  const container = document.getElementById('override-log');
  if (!container) return;

  container.innerHTML = `<span class="override-log-title">Historical Log Records</span>`;
  state.auditLogs.forEach((log) => {
    const entry = document.createElement('div');
    entry.className = "override-log-entry";
    if (log.includes("rejected") || log.includes("override")) {
      entry.className = "override-log-entry rejected";
    }
    if (log.includes("Emergency") || log.includes("FAULT")) {
      entry.className = "override-log-entry critical";
    }
    entry.innerText = log;
    container.appendChild(entry);
  });
  container.scrollTop = container.scrollHeight;
}

// --- Cycle Times Jitter ---
function jitterStationCycles() {
  Object.keys(stations).forEach(key => {
    const st = stations[key];
    const elVal = document.getElementById(`cycle-${key}`);
    if (!elVal) return;

    let base = st.baseCycle;
    
    if (state.isStressed) {
      if (key === 'S5') {
        elVal.innerText = "FAULT / HALT";
        elVal.style.color = "var(--accent-critical)";
        return;
      } else if (key === 'S6' || key === 'S7') {
        base += 15.4;
      } else if (key === 'S8') {
        base -= 4.2;
      }
    } else if (state.activeStep === 1) {
      if (key === 'S3') base = 54.2;
      if (key === 'S6') base = 49.8;
      if (key === 'S8') base = 41.5;
    } else if (state.activeStep === 2) {
      if (key === 'S3') base = 52.8;
      if (key === 'S5') base = 48.9;
      if (key === 'S6') base = 49.2;
      if (key === 'S7') base = 51.5;
      if (key === 'S8') base = 43.1;
    }

    let jitter = (Math.random() * 0.8) - 0.4;
    let computedVal = (base + jitter).toFixed(1);

    elVal.innerText = computedVal + "s";
    elVal.style.color = "var(--text-primary)";
  });
}

// --- Interactive Controller actions ---

function setTimelineStep(stepIndex) {
  state.activeStep = stepIndex;
  state.stepProgress = 0;
  state.isStressed = false;
  state.isStressSolved = false;

  // Restore Option C default view
  resetWhatIfSimulator();

  if (stepIndex === 0) {
    state.overallHealth = 98.4;
    state.throughput = 42.2;
  } else if (stepIndex === 1) {
    state.overallHealth = 89.2;
    state.throughput = 40.5;
    playSound('alert');
  } else if (stepIndex === 2) {
    state.overallHealth = 78.1;
    state.throughput = 36.4;
    playSound('alert');
  }

  saveState();
}

function selectScenario(option) {
  if (state.isStressSolved) return;
  state.selectedScenario = option;
  saveState();
}

function resetWhatIfSimulator() {
  state.selectedScenario = 'C';
}

// --- Approve / Reject Handlers ---

function approveRecommendation() {
  playSound('chime');

  // Pause simulation
  state.isPlaying = false;
  
  const nowStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  if (state.isStressed) {
    // Stress bypass approval
    state.isStressed = false;
    state.isStressSolved = true;
    state.overallHealth = 92.4;
    state.throughput = 34.6;
    state.auditLogs.push(`[${nowStr}] Emergency: Bypass activated. Maintenance dispatched to S5 Powertrain.`);
    state.trustScore = Math.min(state.trustScore + 2, 100);
    showToast("Emergency Bypass Action B-2 Deployed!", "healthy");
    saveState();
    return;
  }

  // Anomaly recommendation approval
  state.overallHealth = 99.1;
  state.throughput = 42.4;
  state.trustScore = Math.min(state.trustScore + 4, 100);
  state.auditLogs.push(`[${nowStr}] Operator approved Option ${state.selectedScenario}. Cycle buffers restored.`);
  
  // Clear chatbot history logs for a clean new sequence
  showToast(`Intervention ${state.selectedScenario} Applied Successfully!`, "healthy");
  
  // Update timeline state to resolved
  saveState();
}

function rejectRecommendation() {
  playSound('critical');
  
  const nowStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  state.auditLogs.push(`[${nowStr}] Operator rejected Option ${state.selectedScenario}. Running manual line speed override.`);
  state.trustScore = Math.max(state.trustScore - 2, 80);
  
  showToast("AI recommendation overridden by operator.", "warning");
  saveState();
}

// --- Ask the Twin chat handlers ---
const cannedAnswers = {
  "why is station 7 slowing down?": "Station 3's cycle time spiked by 4.2s. This created downstream torque variances in Powertrain Station 5, leading to door gap anomalies on Station 6. S7 is now starving for doors chassis blocks.",
  "what is the root cause of the anomaly?": "Telemetry diagnostics isolate the primary cause to an assembly rail misalignment at S3 Underbody. This forced a +4.2s cycle compensation which cascaded downstream.",
  "how does option c prevent the defect?": "Option C activates an alternate buffer path through sensorless Electronics Station 8. This absorbs S5 cycle fluctuations and recalibrates torque parameters dynamically, reducing scrap risk by 94%."
};

function askPredefined(question) {
  const input = document.getElementById('chat-user-input');
  if (input) {
    input.value = question;
    sendChat();
  }
}

function handleChatEnter(e) {
  if (e.key === 'Enter') {
    sendChat();
  }
}

function sendChat() {
  const input = document.getElementById('chat-user-input');
  if (!input) return;
  const question = input.value.trim();
  if (!question) return;

  // Add user message
  state.chatHistory.push({ sender: 'user', text: question });
  input.value = "";
  playSound('beep');
  saveState();

  // Answer response typing simulation
  setTimeout(() => {
    const cleanQ = question.toLowerCase().replace(/[?,.]/g, "");
    let answer = "Analyzing telemetry context. S8 inference shows standard cycle variance. Causal drift originates from S3 underbody calibration. Recommend Option C to prevent defect propagation.";
    
    Object.keys(cannedAnswers).forEach(key => {
      if (cleanQ.includes(key.substring(0, 15)) || key.split(' ').some(word => word.length > 4 && cleanQ.includes(word))) {
        answer = cannedAnswers[key];
      }
    });

    state.chatHistory.push({ sender: 'bot', text: answer });
    playSound('beep');
    saveState();
  }, 1000);
}

// --- Stress Test Cascade Trigger ---
function triggerStressTest() {
  playSound('critical');
  showToast("CRITICAL CASCADE INITIATED: S5 failure simulated!", "critical");

  state.isStressed = true;
  state.isStressSolved = false;
  state.isPlaying = false;
  state.activeStep = -1;
  state.selectedScenario = 'B'; // Default recommend Option B bypass

  state.overallHealth = 44.5;
  state.throughput = 18.2;

  const nowStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  state.auditLogs.push(`[${nowStr}] Emergency: Critical motor fault at Station 5 (Powertrain). Cascading blocks predicted.`);

  saveState();
}

// btn-replay is now handled in DOMContentLoaded above

// --- Toast notification helper ---
function showToast(message, type = "healthy") {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  let toastClass = 'toast';
  if (type === 'warning') toastClass += ' warning-toast';
  else if (type === 'critical') toastClass += ' critical-toast';
  else if (type === 'info') toastClass += ' info-toast';
  toast.className = toastClass;
  
  let icon = "info";
  if (type === "healthy") icon = "check-circle";
  if (type === "warning") icon = "alert-triangle";
  if (type === "critical") icon = "alert-circle";
  
  toast.innerHTML = `
    <i data-lucide="${icon}" style="width:16px;height:16px;flex-shrink:0;"></i>
    <span>${message}</span>
  `;
  container.appendChild(toast);
  lucide.createIcons();
  
  setTimeout(() => {
    toast.remove();
  }, 4000);
}
