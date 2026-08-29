/**
 * TwinPilot Live API Bridge & Continuous Real-Time Digital Twin Engine
 * ====================================================================
 * Connects the HTML/JS frontend to the Python backend (127.0.0.1:5000).
 * 
 * Features:
 *  1. REAL-TIME CLOCK ENGINE: Operates as a genuine live digital factory clock
 *     ticking second-by-second (10:03:00 AM, 10:03:01 AM, 10:03:02 AM...) in true
 *     1x Real-Time mode, with configurable simulation speed (1x, 5x, 10x, 30x, 60x).
 *  2. CONTINUOUS PHYSICS INTERPOLATION: Telemetry, tool vibration, cycle times,
 *     defect probabilities, and queue backlogs smoothly evolve in real-time
 *     matching the elapsed manufacturing timeline.
 *  3. SYNCHRONOUS STAGE TRANSITIONS: 
 *     - Baseline (10:03 AM) -> Emerging Signal (10:13 AM, 10m real-time transition)
 *     - Emerging -> Rising Risk (10:19 AM, 6m real-time transition)
 *     - Rising Risk -> Critical Prediction NOW (10:23 AM, 4m real-time transition)
 *     - Prediction NOW -> Natural Future vs Intervention Recovery (10:38 AM)
 *  4. INTERACTIVE CONTROLS: Play/Pause clock toggle, Speed multiplier, Reset to 10:03 AM,
 *     and click-to-seek milestone navigation that continues ticking forward in real time.
 */

const TwinPilotAPI = (() => {
  const BASE = (typeof window !== "undefined" && window.location.port === "5000")
    ? "/api"
    : "http://127.0.0.1:5000/api";

  const SCENARIOS = {
    "RUN024-EVT01": { 
      run_id: "RUN-024", 
      baseMinute: 123, 
      emergeMinute: 133,
      risingMinute: 139,
      nowMinute: 143, 
      futureMinute: 158,
      restoredMinute: 168,
      station: "S03", 
      event_id: "RUN024-EVT01", 
      title: "RUN-024 (S03 Defect Surge)" 
    },
    "RUN025-EVT02": { 
      run_id: "RUN-025", 
      baseMinute: 73,  
      emergeMinute: 83,
      risingMinute: 89,
      nowMinute: 93,  
      futureMinute: 108,
      restoredMinute: 118,
      station: "S16", 
      event_id: "RUN025-EVT02", 
      title: "RUN-025 (S16 Delay & S21 Dark Zone)" 
    },
  };

  const clock = {
    runId: "RUN-024",
    minute: 123,
    station: "S03",
    event_id: "RUN024-EVT01"
  };

  // Continuous Clock Engine Variables
  let isClockRunning = true;
  let simSpeed = 1; // 1x (Real-Time), 5x, 10x, 30x, 60x
  let currentSimSeconds = 123 * 60; // Start at 10:03:00 AM (123 mins into shift)
  let lastClockTimestamp = performance.now();
  let masterTimerId = null;

  let latestState = null;
  let selectedOptionKey = null;
  let decisionState = "pending"; // "pending" | "executing" | "approved" | "rejected"
  let decisionRecord = null;
  let selectedTimelineStepIdx = 0; // Starts on Step 1: 1. Baseline!

  // ── Cross-Page Navigation State Persistence ────────────────────────────────
  const SESSION_STORAGE_KEY = "twinpilot_live_session";
  let lastSavedSimSec = 0;

  function saveSession() {
    try {
      const storage = (typeof window !== "undefined" && window.sessionStorage) ? window.sessionStorage : (typeof sessionStorage !== "undefined" ? sessionStorage : null);
      if (!storage) return;
      const data = {
        event_id: clock.event_id,
        runId: clock.runId,
        station: clock.station,
        minute: clock.minute,
        currentSimSeconds: currentSimSeconds,
        wallTimestamp: Date.now(),
        selectedTimelineStepIdx: selectedTimelineStepIdx,
        simSpeed: simSpeed,
        isClockRunning: isClockRunning,
        decisionState: decisionState,
        selectedOptionKey: selectedOptionKey,
        decisionRecord: decisionRecord
      };
      storage.setItem(SESSION_STORAGE_KEY, JSON.stringify(data));
    } catch (e) {
      console.warn("[TwinPilot Bridge] saveSession error:", e);
    }
  }

  function restoreSession() {
    try {
      const storage = (typeof window !== "undefined" && window.sessionStorage) ? window.sessionStorage : (typeof sessionStorage !== "undefined" ? sessionStorage : null);
      if (!storage) return false;
      const raw = storage.getItem(SESSION_STORAGE_KEY);
      if (!raw) return false;
      const data = JSON.parse(raw);
      if (!data) return false;

      if (data.event_id && SCENARIOS[data.event_id]) {
        clock.event_id = data.event_id;
        clock.runId = data.runId || SCENARIOS[data.event_id].run_id;
        clock.station = data.station || SCENARIOS[data.event_id].station;
      }

      if (typeof data.simSpeed === "number") simSpeed = data.simSpeed;
      if (typeof data.isClockRunning === "boolean") isClockRunning = data.isClockRunning;
      if (data.decisionState) decisionState = data.decisionState;
      if (data.selectedOptionKey) selectedOptionKey = data.selectedOptionKey;
      if (data.decisionRecord) decisionRecord = data.decisionRecord;
      if (typeof data.selectedTimelineStepIdx === "number") selectedTimelineStepIdx = data.selectedTimelineStepIdx;

      let restoredSeconds = (typeof data.currentSimSeconds === "number") ? data.currentSimSeconds : (123 * 60);

      // If clock was running when navigating, advance by real elapsed wall time
      if (isClockRunning && data.wallTimestamp) {
        const elapsedSec = Math.max(0, (Date.now() - data.wallTimestamp) / 1000.0);
        if (elapsedSec < 3600) {
          restoredSeconds += elapsedSec * simSpeed;
        }
      }

      const cfg = SCENARIOS[clock.event_id] || SCENARIOS["RUN024-EVT01"];
      const maxSec = (cfg.restoredMinute + 12) * 60;
      currentSimSeconds = Math.min(restoredSeconds, maxSec);
      clock.minute = Math.floor(currentSimSeconds / 60);
      lastSavedSimSec = currentSimSeconds;

      return true;
    } catch (e) {
      return false;
    }
  }

  if (typeof window !== "undefined") {
    window.addEventListener("beforeunload", saveSession);
    window.addEventListener("pagehide", saveSession);
  }

  // ── DOM Helpers ────────────────────────────────────────────────────────────
  function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }
  function setHTML(id, val) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = val;
  }
  function setStyle(id, prop, val) {
    const el = document.getElementById(id);
    if (el) el.style[prop] = val;
  }
  function colorForProb(prob) {
    if (prob >= 30) return "var(--accent-critical)";
    if (prob >= 15) return "var(--accent-warning)";
    return "var(--accent-healthy)";
  }

  function formatSimClockFromSeconds(totalSec) {
    const totalShiftSec = (8 * 3600) + Math.floor(totalSec);
    const hours24 = Math.floor(totalShiftSec / 3600) % 24;
    const mins = Math.floor((totalShiftSec % 3600) / 60);
    const secs = Math.floor(totalShiftSec % 60);
    const ampm = hours24 < 12 ? "AM" : "PM";
    let h = hours24 % 12;
    if (h === 0) h = 12;
    const pad = (n) => String(n).padStart(2, '0');
    return `${pad(h)}:${pad(mins)}:${pad(secs)} ${ampm}`;
  }

  // ── Top Simulation Bar ─────────────────────────────────────────────────────
  function injectSimulationBar() {
    let bar = document.getElementById("tp-sim-bar");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "tp-sim-bar";
      bar.style.cssText = `
        position: sticky; top: 0; z-index: 1000;
        background: linear-gradient(90deg, #0b1120 0%, #1e293b 100%);
        border-bottom: 1px solid rgba(99,102,241,0.35);
        padding: 8px 24px; display: flex; align-items: center;
        justify-content: space-between; font-size: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.3);
      `;
      document.body.prepend(bar);
    }

    bar.innerHTML = `
      <div style="display:flex; align-items:center; gap:16px; flex-wrap:wrap;">
        <!-- Factory / Tenant Switcher -->
        <div style="display:flex; align-items:center; gap:6px;">
          <span style="color:#38bdf8; font-weight:800; letter-spacing:0.04em; text-transform:uppercase;">Plant:</span>
          <select id="tp-factory-select" style="background:#0f172a; color:#38bdf8; border:1px solid rgba(56,189,248,0.5);
            border-radius:6px; padding:4px 8px; font-size:11.5px; font-weight:700; cursor:pointer; outline:none; max-width:200px;">
            <option value="demo-detroit-31">🏭 Detroit Plant #4 (Demo)</option>
          </select>
          <a href="onboarding.html" title="Onboard New Factory Datasets" style="background:rgba(99,102,241,0.2); color:#a5b4fc; border:1px solid rgba(99,102,241,0.4); border-radius:5px; padding:3px 8px; font-size:11px; font-weight:700; text-decoration:none; display:inline-flex; align-items:center; gap:3px;">
            + Onboard Factory
          </a>
        </div>

        <div style="display:flex; align-items:center; gap:8px;">
          <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#10b981; animation:blink 1.5s infinite;"></span>
          <span style="color:#818cf8; font-weight:800; letter-spacing:0.05em; text-transform:uppercase;">Twin Scenario:</span>
          <select id="tp-scenario-select" style="background:#0f172a; color:#f8fafc; border:1px solid rgba(99,102,241,0.5);
            border-radius:6px; padding:4px 10px; font-size:11.5px; font-weight:600; cursor:pointer; outline:none;">
            <option value="RUN024-EVT01">RUN-024 (S03 Defect Surge)</option>
            <option value="RUN025-EVT02">RUN-025 (S16 Delay & S21 Dark Zone)</option>
          </select>
        </div>

        <div style="display:flex; align-items:center; gap:8px; background:rgba(255,255,255,0.06); padding:3px 10px; border-radius:6px; border:1px solid rgba(255,255,255,0.1);">
          <span style="font-size:11px; color:#94a3b8;">Clock Speed:</span>
          <select id="tp-top-speed-select" onchange="TwinPilotAPI.setSpeed(Number(this.value))" style="background:#0f172a; color:#38bdf8; border:1px solid rgba(56,189,248,0.4); border-radius:4px; padding:2px 8px; font-size:11px; font-weight:700; cursor:pointer; outline:none;">
            <option value="1" ${simSpeed === 1 ? 'selected' : ''}>1x (Real-Time)</option>
            <option value="5" ${simSpeed === 5 ? 'selected' : ''}>5x Speed</option>
            <option value="10" ${simSpeed === 10 ? 'selected' : ''}>10x Speed</option>
            <option value="30" ${simSpeed === 30 ? 'selected' : ''}>30x Speed</option>
            <option value="60" ${simSpeed === 60 ? 'selected' : ''}>60x (1s = 1m)</option>
          </select>
        </div>
      </div>

      <!-- Line Structure & Multi-Tenant Access Badge -->
      <div style="display:flex; align-items:center; gap:12px;">
        <span style="font-size:11px; color:#94a3b8;" id="tp-topology-info">Topology: <strong style="color:#f8fafc;">30 Mainline (S01–S30) + 1 Feeder (ENG01)</strong></span>
        <span style="background:rgba(16,185,129,0.15); color:#10b981; border:1px solid rgba(16,185,129,0.3); padding:3px 8px; border-radius:4px; font-size:10.5px; font-weight:700;">● Multi-Tenant OS</span>
        <a href="login.html" title="Login / Switch Company Workspace" style="background:rgba(255,255,255,0.06); color:#cbd5e1; border:1px solid rgba(255,255,255,0.15); border-radius:5px; padding:3px 8px; font-size:11px; font-weight:600; text-decoration:none; display:inline-flex; align-items:center; gap:4px;">
          Account
        </a>
      </div>
    `;

    const sel = document.getElementById("tp-scenario-select");
    if (sel) {
      sel.value = clock.event_id || "RUN024-EVT01";
      sel.addEventListener("change", (e) => {
        switchScenario(e.target.value);
      });
    }

    // Populate factory dropdown
    populateFactorySelector();
  }

  async function populateFactorySelector() {
    const factSel = document.getElementById("tp-factory-select");
    if (!factSel) return;

    try {
      const resp = await fetch(`${BASE}/factories`);
      if (!resp.ok) return;
      const data = await resp.json();
      const factories = data.factories || [];
      let activeFid = localStorage.getItem("twinpilot_active_factory") || "demo-detroit-31";

      if (!factories.some(f => f.id === activeFid)) {
        activeFid = "demo-detroit-31";
        localStorage.setItem("twinpilot_active_factory", "demo-detroit-31");
      }

      factSel.innerHTML = "";
      factories.forEach(f => {
        const opt = document.createElement("option");
        opt.value = f.id;
        opt.textContent = `${f.is_demo ? "🏭 [Demo] " : "🏭 "}${f.name}`;
        if (f.id === activeFid) opt.selected = true;
        factSel.appendChild(opt);
      });

      factSel.addEventListener("change", (e) => {
        const newFid = e.target.value;
        localStorage.setItem("twinpilot_active_factory", newFid);
        showToast(`Switched active factory workspace to ${e.target.selectedOptions[0].text}.`, "info");
        fetchAndRenderState();
      });
    } catch (e) {
      console.warn("Could not load factories list:", e);
    }
  }

  // ── Clock Engine: Ticking & Real-Time Physics Synchronization ──────────────
  function initMasterClockEngine() {
    if (masterTimerId) clearInterval(masterTimerId);
    lastClockTimestamp = performance.now();

    masterTimerId = setInterval(() => {
      const now = performance.now();
      const deltaRealSec = (now - lastClockTimestamp) / 1000.0;
      lastClockTimestamp = now;

      if (!isClockRunning) return;

      const cfg = SCENARIOS[clock.event_id] || SCENARIOS["RUN024-EVT01"];
      const maxSec = (cfg.restoredMinute + 12) * 60; // Allows continuous run past Stage 6 into 11:00 AM

      // Advance sim clock by real seconds elapsed * simulation speed
      currentSimSeconds += deltaRealSec * simSpeed;
      if (currentSimSeconds > maxSec) {
        currentSimSeconds = maxSec;
      }

      const curMin = currentSimSeconds / 60.0;
      clock.minute = Math.floor(curMin);

      // Persist to session storage periodically so page navigation retains exact clock
      if (Math.abs(currentSimSeconds - lastSavedSimSec) >= 1.0) {
        lastSavedSimSec = currentSimSeconds;
        saveSession();
      }

      // Render updated digital clock
      const clockStr = formatSimClockFromSeconds(currentSimSeconds);
      setText("sim-clock", clockStr);

      // Apply continuous physical progression across all stations
      applyContinuousPhysics(curMin, currentSimSeconds, cfg);
    }, 200);
  }

  function toggleClock() {
    isClockRunning = !isClockRunning;
    saveSession();
    updateClockControlButtons();
    showToast(isClockRunning ? `Digital Twin Clock running at ${simSpeed}x (${simSpeed === 1 ? 'Real-Time' : simSpeed + 'x Speed'}).` : "Digital Twin Clock paused.", "info");
  }

  function setSpeed(multiplier) {
    simSpeed = Number(multiplier) || 1;
    saveSession();
    const topSel = document.getElementById("tp-top-speed-select");
    const timelineSel = document.getElementById("timeline-speed-select");
    if (topSel) topSel.value = String(simSpeed);
    if (timelineSel) timelineSel.value = String(simSpeed);

    showToast(`Simulation speed set to ${simSpeed}x (${simSpeed === 1 ? 'Real-Time: 1s per 1s' : simSpeed + 'x Speed'}).`, "info");
  }

  function updateClockControlButtons() {
    const btn = document.getElementById("btn-toggle-clock");
    const txt = document.getElementById("btn-toggle-clock-text");
    if (txt) txt.textContent = isClockRunning ? "Pause Clock" : "Run Clock";
    if (btn) {
      btn.style.background = isClockRunning ? "rgba(16,185,129,0.12)" : "rgba(99,102,241,0.12)";
      btn.style.borderColor = isClockRunning ? "rgba(16,185,129,0.3)" : "rgba(99,102,241,0.3)";
      btn.style.color = isClockRunning ? "#059669" : "#818cf8";
    }
  }

  // ── Continuous Physical Telemetry Model ────────────────────────────────────
  function applyContinuousPhysics(curMin, curSec, cfg) {
    const mBase = cfg.baseMinute;     // 123
    const mEmerge = cfg.emergeMinute; // 133
    const mRising = cfg.risingMinute; // 139
    const mNow = cfg.nowMinute;       // 143
    const mFuture = cfg.futureMinute; // 158
    const mRestored = cfg.restoredMinute; // 168

    let targetCT = 46.0;
    let targetVib = 0.80;
    let targetRisk = 0.0;
    let targetQueue = 0;
    let overallHealth = 99.2;
    let overallThroughput = 82.5;
    let stageIdx = 0;
    let targetStatus = "healthy";
    let targetTier = "RICH";

    if (curMin <= mBase) {
      // Stage 1: Baseline (10:03 AM)
      stageIdx = 0;
      targetCT = 46.0;
      targetVib = 0.80;
      targetRisk = 0.0;
      targetQueue = 0;
      overallHealth = 99.2;
      overallThroughput = 82.5;
      targetStatus = "healthy";
      targetTier = "RICH";
    } else if (curMin < mEmerge) {
      // Transition from Baseline to Emerging (10:03 AM -> 10:13 AM: 10 minutes real time)
      const p = Math.min(1.0, Math.max(0.0, (curMin - mBase) / (mEmerge - mBase)));
      stageIdx = (p >= 0.85) ? 1 : 0;
      targetCT = 46.0 + p * (48.4 - 46.0);
      targetVib = 0.80 + p * (1.40 - 0.80);
      targetRisk = 0.0 + p * 8.5;
      targetQueue = Math.round(p * 1);
      overallHealth = 99.2 - p * (99.2 - 96.8);
      overallThroughput = 82.5 - p * (82.5 - 80.8);
      targetStatus = (p >= 0.4) ? "emerging warning" : "healthy";
      targetTier = (p >= 0.4) ? "EMERGING" : "RICH";
    } else if (curMin < mRising) {
      // Transition from Emerging to Rising Risk (10:13 AM -> 10:19 AM: 6 minutes real time)
      const p = Math.min(1.0, Math.max(0.0, (curMin - mEmerge) / (mRising - mEmerge)));
      stageIdx = (p >= 0.85) ? 2 : 1;
      targetCT = 48.4 + p * (52.0 - 48.4);
      targetVib = 1.40 + p * (2.10 - 1.40);
      targetRisk = 8.5 + p * (22.0 - 8.5);
      targetQueue = Math.round(1 + p * 2);
      overallHealth = 96.8 - p * (96.8 - 91.2);
      overallThroughput = 80.8 - p * (80.8 - 77.5);
      targetStatus = "rising-risk warning";
      targetTier = (p >= 0.5) ? "RISING RISK" : "EMERGING";
    } else if (curMin < mNow) {
      // Transition from Rising Risk to Critical Prediction NOW (10:19 AM -> 10:23 AM: 4 minutes real time)
      const p = Math.min(1.0, Math.max(0.0, (curMin - mRising) / (mNow - mRising)));
      stageIdx = (p >= 0.85) ? 3 : 2;
      targetCT = 52.0 + p * (57.5 - 52.0);
      targetVib = 2.10 - p * (2.10 - 1.54);
      targetRisk = 22.0 + p * (35.5 - 22.0);
      targetQueue = Math.round(3 + p * 7);
      overallHealth = 91.2 - p * (91.2 - 84.0);
      overallThroughput = 77.5 - p * (77.5 - 74.5);
      targetStatus = (p >= 0.6) ? "critical" : "rising-risk warning";
      targetTier = (p >= 0.6) ? "CRITICAL" : "RISING RISK";
    } else if (curMin < mFuture) {
      // Stage 5 Execution / Transition window (10:23 AM -> 10:38 AM: 15 minutes real time)
      const p = Math.min(1.0, Math.max(0.0, (curMin - mNow) / (mFuture - mNow)));
      stageIdx = (p >= 0.85) ? 4 : 3;
      if (decisionState === "approved") {
        targetCT = 57.5 - p * (57.5 - 46.8);
        targetVib = 1.54 - p * (1.54 - 0.95);
        targetRisk = 35.5 - p * (35.5 - 3.0);
        targetQueue = Math.round(10 - p * 8);
        overallHealth = 84.0 + p * (96.5 - 84.0);
        overallThroughput = 74.5 + p * (81.5 - 74.5);
        targetStatus = "healthy";
        targetTier = "EXECUTING";
      } else if (decisionState === "rejected") {
        targetCT = 57.5 + p * (58.0 - 57.5);
        targetVib = 1.54 + p * (2.40 - 1.54);
        targetRisk = 35.5 - p * (35.5 - 28.5);
        targetQueue = Math.round(10 - p * 1);
        overallHealth = 84.0 - p * (84.0 - 74.0);
        overallThroughput = 74.5 - p * (74.5 - 71.0);
        targetStatus = "warning";
        targetTier = "MANUAL DELAY";
      } else {
        targetCT = 57.5 + p * (68.0 - 57.5);
        targetVib = 1.54 + p * (3.20 - 1.54);
        targetRisk = 35.5 + p * (48.0 - 35.5);
        targetQueue = Math.round(10 + p * 6);
        overallHealth = 84.0 - p * (84.0 - 62.5);
        overallThroughput = 74.5 - p * (74.5 - 60.2);
        targetStatus = "critical";
        targetTier = "CASCADED";
      }
    } else {
      // Stage 6 Post-Execution / Nominal Restored window (10:38 AM -> 10:48 AM: 10 minutes real time)
      const p = Math.min(1.0, Math.max(0.0, (curMin - mFuture) / (mRestored - mFuture)));
      stageIdx = (p >= 0.20) ? 5 : 4;

      if (decisionState === "approved") {
        // Line fully recovers to nominal baseline!
        targetCT = 46.8 - p * (46.8 - 46.0); // Exactly nominal 46.0s!
        targetVib = 0.95 - p * (0.95 - 0.80); // Exactly nominal 0.80 mm/s!
        targetRisk = 3.0 - p * 3.0;           // Exactly 0.0% defect risk!
        targetQueue = Math.max(0, Math.round(2 - p * 2)); // Exactly 0 backlog!
        overallHealth = 96.5 + p * (99.2 - 96.5); // 99.2% nominal factory health!
        overallThroughput = 81.5 + p * (83.2 - 81.5); // 83.2 u/h (+7.5% throughput)!
        targetStatus = "healthy";
        targetTier = (p >= 0.4) ? "NOMINAL RESTORED" : "STABILIZING";
      } else if (decisionState === "rejected") {
        targetCT = 58.0;
        targetVib = 2.40;
        targetRisk = 28.5;
        targetQueue = 9;
        overallHealth = 74.0;
        overallThroughput = 71.0;
        targetStatus = "warning";
        targetTier = "MANUAL DEGRADED";
      } else {
        targetCT = 68.0;
        targetVib = 3.20;
        targetRisk = 48.0;
        targetQueue = 16;
        overallHealth = 62.5;
        overallThroughput = 60.2;
        targetStatus = "critical";
        targetTier = "CASCADED STARVATION";
      }
    }

    // Check for milestone audio triggers
    if (stageIdx !== selectedTimelineStepIdx) {
      selectedTimelineStepIdx = stageIdx;
      if (stageIdx === 1) playSound('beep');
      else if (stageIdx === 2) playSound('alert');
      else if (stageIdx === 3) playSound('critical');
      else if (stageIdx === 4) playSound('chime');
      else if (stageIdx === 5) playSound('chime');

      // Refresh complete state from backend for exact explanations & recommendations
      fetchAndRenderState();
      return;
    }

    // Update real-time continuous DOM values smoothly
    setText("factory-overall-health", `${overallHealth.toFixed(1)}%`);
    setStyle("factory-overall-health", "color", overallHealth >= 90 ? "var(--accent-healthy)" : (overallHealth >= 75 ? "var(--accent-warning)" : "var(--accent-critical)"));
    setText("factory-throughput", `${overallThroughput.toFixed(1)} u/h`);

    // Target station node live update
    const targetNode = document.getElementById(`node-${cfg.station}`);
    if (targetNode) {
      const ctEl = targetNode.querySelector("div:nth-child(3)");
      if (ctEl) ctEl.textContent = `${targetCT.toFixed(1)}s`;

      const qEl = targetNode.querySelector("span:nth-child(1) strong");
      if (qEl) qEl.textContent = targetQueue;

      const rEl = targetNode.querySelector("span:nth-child(2) strong");
      if (rEl) {
        rEl.textContent = `${targetRisk.toFixed(1)}%`;
        rEl.style.color = colorForProb(targetRisk);
      }
    }

    // Highlight active timeline milestone button
    document.querySelectorAll(".milestone-node-btn").forEach((btn, idx) => {
      btn.classList.toggle("active", idx === selectedTimelineStepIdx);
    });
  }

  // ── Switch Scenario & Reset ────────────────────────────────────────────────
  function switchScenario(scenarioKey) {
    const cfg = SCENARIOS[scenarioKey];
    if (!cfg) return;

    clock.runId = cfg.run_id;
    clock.minute = cfg.baseMinute;
    clock.station = cfg.station;
    clock.event_id = cfg.event_id;
    currentSimSeconds = cfg.baseMinute * 60;
    selectedOptionKey = null;
    decisionState = "pending";
    decisionRecord = null;
    selectedTimelineStepIdx = 0; // Strictly on 1st step!
    saveSession();

    fetch(`${BASE}/reset_decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: clock.runId, event_id: clock.event_id })
    }).catch(() => {});

    fetchAndRenderState();
    showToast(`Switched scenario to ${cfg.title}. Clock running from ${formatSimClockFromSeconds(currentSimSeconds)}.`, "info");
  }

  async function reset() {
    const cfg = SCENARIOS[clock.event_id] || SCENARIOS["RUN024-EVT01"];
    clock.runId = cfg.run_id;
    clock.minute = cfg.baseMinute;
    clock.station = cfg.station;
    clock.event_id = cfg.event_id;
    currentSimSeconds = cfg.baseMinute * 60;
    isClockRunning = true;
    selectedOptionKey = null;
    decisionState = "pending";
    decisionRecord = null;
    selectedTimelineStepIdx = 0; // Return to 1st step!
    saveSession();

    try {
      await fetch(`${BASE}/reset_decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: clock.runId, event_id: clock.event_id })
      });
    } catch (e) {}

    const container = document.getElementById("toast-container");
    if (container) container.innerHTML = "";

    updateClockControlButtons();
    await fetchAndRenderState();
    showToast(`Reset to Step 1: Baseline at ${formatSimClockFromSeconds(currentSimSeconds)}. Real-time clock running.`, "info");
  }

  function seekToMilestone(stepIdx) {
    const cfg = SCENARIOS[clock.event_id] || SCENARIOS["RUN024-EVT01"];
    const mins = [cfg.baseMinute, cfg.emergeMinute, cfg.risingMinute, cfg.nowMinute, cfg.futureMinute, cfg.restoredMinute];
    const targetMin = mins[stepIdx] || cfg.baseMinute;

    currentSimSeconds = targetMin * 60;
    selectedTimelineStepIdx = stepIdx;
    clock.minute = targetMin;
    saveSession();

    fetchAndRenderState();
    showToast(`Clock jumped to Step ${stepIdx + 1} (${formatSimClockFromSeconds(currentSimSeconds)}). Continuing live run...`, "info");
  }

  async function resetDecisionState() {
    decisionState = "pending";
    decisionRecord = null;

    try {
      await fetch(`${BASE}/reset_decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: clock.runId, event_id: clock.event_id })
      });
    } catch (e) {}

    if (latestState) {
      renderApprovalControls(latestState.recommendation.option_key, latestState.interventions[latestState.recommendation.option_key]);
    }
    showToast("Decision state reset — Approve / Reject options restored.", "info");
  }

  // ── Render 31-Station Assembly Ribbon (30 Mainline + 1 Feeder) ─────────────
  function render31StationsStrip(stations, targetStationId, pathSet) {
    const container = document.getElementById("stations-row");
    if (!container) return;

    container.innerHTML = "";
    container.style.cssText = `
      display: flex;
      gap: 8px;
      overflow-x: auto;
      padding: 10px 4px 14px 4px;
      scrollbar-width: thin;
    `;

    stations.forEach(st => {
      const isTarget = (st.station_id === targetStationId && selectedTimelineStepIdx > 0);
      const isPath = pathSet.has(st.station_id) && (selectedTimelineStepIdx >= 2);
      const isManual = st.is_manual;
      const isFeeder = (st.station_id === "ENG01");
      
      let badgeClass = "healthy";
      let tierTag = isFeeder ? "FEEDER (RICH)" : st.sensor_tier;
      let tagBg = "rgba(5,150,105,0.15)";
      let tagColor = "var(--accent-healthy)";

      if (isTarget) {
        if (selectedTimelineStepIdx === 1) {
          badgeClass = "emerging warning";
          tierTag = "EMERGING";
          tagBg = "rgba(245,158,11,0.2)";
          tagColor = "#d97706";
        } else if (selectedTimelineStepIdx === 2) {
          badgeClass = "rising-risk warning";
          tierTag = "RISING RISK";
          tagBg = "rgba(249,115,22,0.2)";
          tagColor = "#ea580c";
        } else if (selectedTimelineStepIdx === 3) {
          badgeClass = "critical";
          tierTag = "CRITICAL";
          tagBg = "rgba(220,38,38,0.2)";
          tagColor = "var(--accent-critical)";
        } else if (selectedTimelineStepIdx === 4) {
          badgeClass = "critical";
          tierTag = "CASCADED";
          tagBg = "rgba(185,28,28,0.25)";
          tagColor = "#991b1b";
        } else if (selectedTimelineStepIdx === 5) {
          badgeClass = "healthy";
          tierTag = "OPTIMIZED";
          tagBg = "rgba(16,185,129,0.2)";
          tagColor = "#059669";
        }
      } else if (isPath) {
        badgeClass = "warning";
        tagBg = "rgba(217,119,6,0.2)";
        tagColor = "var(--accent-warning)";
      } else if (isFeeder) {
        tagBg = "rgba(139,92,246,0.2)";
        tagColor = "#8b5cf6";
      } else if (isManual) {
        badgeClass = "sensorless";
        tierTag = "MANUAL";
        tagBg = "rgba(37,99,235,0.15)";
        tagColor = "var(--accent-info)";
      } else if (st.sensor_tier === "PARTIAL") {
        tagBg = "rgba(100,116,139,0.15)";
        tagColor = "#94a3b8";
      }

      let nodeBg = "#ffffff";
      let nodeBorder = isManual ? "1.5px dashed rgba(37,99,235,0.4)" : (isFeeder ? "1px solid rgba(139,92,246,0.4)" : "1px solid var(--border-color)");
      let nodeShadow = isFeeder ? "0 0 8px rgba(139,92,246,0.15)" : "var(--shadow-sm)";
      let nodeColor = isFeeder ? "#8b5cf6" : "var(--text-primary)";

      if (isTarget) {
        if (selectedTimelineStepIdx === 1) {
          nodeBg = "rgba(245,158,11,0.08)";
          nodeBorder = "1px solid rgba(245,158,11,0.6)";
          nodeShadow = "0 0 10px rgba(245,158,11,0.2)";
          nodeColor = "#d97706";
        } else if (selectedTimelineStepIdx === 2) {
          nodeBg = "rgba(249,115,22,0.09)";
          nodeBorder = "1px solid rgba(249,115,22,0.7)";
          nodeShadow = "0 0 12px rgba(249,115,22,0.25)";
          nodeColor = "#ea580c";
        } else if (selectedTimelineStepIdx >= 3) {
          nodeBg = "var(--accent-critical-bg)";
          nodeBorder = "1px solid var(--accent-critical)";
          nodeShadow = "0 0 12px rgba(220,38,38,0.25)";
          nodeColor = "var(--accent-critical)";
        }
      } else if (isPath) {
        nodeBg = "var(--accent-warning-bg)";
        nodeBorder = "1px solid var(--accent-warning)";
      } else if (isFeeder) {
        nodeBg = "rgba(139,92,246,0.06)";
      }

      const node = document.createElement("div");
      node.className = `station-node ${badgeClass}`;
      node.id = `node-${st.station_id}`;
      node.style.cssText = `
        flex: 0 0 ${isFeeder ? "125px" : "110px"};
        min-width: ${isFeeder ? "125px" : "110px"};
        background: ${nodeBg};
        border: ${nodeBorder};
        border-radius: 10px;
        padding: 8px 6px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 4px;
        text-align: center;
        box-shadow: ${nodeShadow};
        transition: transform .2s ease, border-color .3s ease;
      `;

      node.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; width:100%;">
          <span style="font-size:11px; font-weight:800; color:${isFeeder ? "#8b5cf6" : "var(--text-primary)"}; font-family:var(--font-display);">${st.station_id}</span>
          <span style="font-size:8.5px; font-weight:700; padding:1px 4px; border-radius:4px; background:${tagBg}; color:${tagColor}; text-transform:uppercase;">${tierTag}</span>
        </div>
        <div style="font-size:10px; font-weight:600; color:var(--text-secondary); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; width:100%;" title="${st.station_name}">${st.station_name}</div>
        <div style="font-size:13px; font-weight:800; font-family:var(--font-display); color:${nodeColor};">${st.cycle_time_sec}s</div>
        <div style="display:flex; justify-content:space-between; width:100%; font-size:9px; color:var(--text-muted); border-top:1px solid rgba(0,0,0,0.05); padding-top:3px;">
          <span>Q: <strong style="color:var(--text-primary);">${st.queue_length}</strong></span>
          <span>Risk: <strong style="color:${colorForProb(st.defect_prob_pct || st.bottleneck_prob_pct)};">${st.defect_prob_pct || st.bottleneck_prob_pct}%</strong></span>
        </div>
      `;

      container.appendChild(node);
    });
  }

  // ── Render Compact Milestone Navigator + Expandable Detail Panel ──────────
  function renderTwinTimeline(timelineSteps) {
    const stepperTrack = document.getElementById("milestone-stepper-track");
    const detailPanel = document.getElementById("milestone-detail-panel");
    if (!stepperTrack || !detailPanel || !timelineSteps || timelineSteps.length === 0) return;

    stepperTrack.innerHTML = "";

    const tagStyles = {
      "OBSERVED TELEMETRY": { bg: "rgba(14,165,233,0.15)", color: "#0284c7", border: "rgba(14,165,233,0.3)" },
      "OBSERVED TELEMETRY + TRIGGER": { bg: "rgba(245,158,11,0.15)", color: "#d97706", border: "rgba(245,158,11,0.3)" },
      "LIVE PREDICTION": { bg: "rgba(99,102,241,0.15)", color: "#6366f1", border: "rgba(99,102,241,0.4)" },
      "NATURAL PROJECTION (DO NOTHING)": { bg: "rgba(239,68,68,0.15)", color: "#dc2626", border: "rgba(239,68,68,0.4)" },
      "INTERVENTION PROJECTION": { bg: "rgba(16,185,129,0.15)", color: "#059669", border: "rgba(16,185,129,0.4)" },
    };

    // Render 6 compact milestone buttons
    timelineSteps.forEach((step, idx) => {
      const isSelected = (idx === selectedTimelineStepIdx);

      const btn = document.createElement("button");
      btn.className = `milestone-node-btn step-${idx} ${isSelected ? "active" : ""}`;
      btn.title = `Click to seek live clock to ${step.phase_name} (${step.sim_clock})`;

      btn.innerHTML = `
        <span class="milestone-node-title">
          ${step.phase_name}
        </span>
        <span class="milestone-node-time">
          ${step.sim_clock.split(" ")[0]} ${step.sim_clock.split(" ")[1] || ""}
        </span>
      `;

      btn.onclick = () => {
        seekToMilestone(idx);
      };

      stepperTrack.appendChild(btn);
    });

    // Render single expandable detail panel
    const cur = timelineSteps[selectedTimelineStepIdx] || timelineSteps[0];
    const curTag = tagStyles[cur.category_badge] || tagStyles["OBSERVED TELEMETRY"];

    detailPanel.innerHTML = `
      <div style="background:${cur.category_type === 'natural_future' ? 'rgba(239,68,68,0.04)' : (cur.category_type === 'intervention_projection' ? 'rgba(16,185,129,0.04)' : '#ffffff')};
        border: 1px solid ${cur.category_type === 'natural_future' ? 'rgba(239,68,68,0.3)' : (cur.category_type === 'intervention_projection' ? 'rgba(16,185,129,0.3)' : 'var(--border-color)')};
        border-radius: 10px; padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; box-shadow: var(--shadow-sm); animation: fadeIn 0.25s ease;">
        
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-size:12px; font-weight:800; color:var(--text-primary); font-family:var(--font-display);">
            ${cur.phase_name}
          </span>
          <span style="font-size:9px; font-weight:800; padding:2px 8px; border-radius:4px; background:${curTag.bg}; color:${curTag.color}; border:1px solid ${curTag.border}; text-transform:uppercase; letter-spacing:0.04em;">
            ${curTag && cur.category_badge}
          </span>
        </div>

        <div style="display:flex; justify-content:space-between; align-items:center; font-size:11px; color:var(--text-secondary);">
          <span>Timeline: <strong style="color:var(--text-primary);">${cur.sim_clock}</strong> (Minute ${cur.minute})</span>
          <span style="font-weight:700; color:${cur.category_type === 'natural_future' ? 'var(--accent-critical)' : (cur.category_type === 'intervention_projection' ? 'var(--accent-healthy)' : 'var(--text-primary)')};">${cur.status}</span>
        </div>

        <div style="font-size:11.5px; color:var(--text-secondary); line-height:1.45;">
          ${cur.summary}
        </div>

        <div style="font-size:10.5px; background:rgba(0,0,0,0.03); border:1px solid rgba(0,0,0,0.06); border-radius:6px; padding:6px 10px; font-family:var(--font-mono); color:var(--text-primary);">
          ${cur.telemetry_highlight}
        </div>
      </div>
    `;
  }

  // ── Render Approve/Reject State Machine ───────────────────────────────────
  function renderApprovalControls(recKey, optVal) {
    const actionsBox = document.querySelector(".simulator-actions");
    if (!actionsBox) return;

    if (selectedTimelineStepIdx === 0) {
      actionsBox.innerHTML = `
        <div style="display:flex; align-items:center; gap:8px; color:var(--text-secondary); font-size:12px; padding:6px 0;">
          <i data-lucide="shield-check" style="width:16px;height:16px;color:var(--accent-healthy);"></i>
          <span>Stage 1/6: Nominal Baseline — Digital twin continuous passive monitoring active.</span>
        </div>
      `;
      if (typeof lucide !== "undefined") lucide.createIcons();
      return;
    } else if (selectedTimelineStepIdx === 1) {
      actionsBox.innerHTML = `
        <div style="display:flex; align-items:center; gap:8px; color:#d97706; font-size:12px; padding:6px 0;">
          <i data-lucide="alert-circle" style="width:16px;height:16px;color:#d97706;"></i>
          <span>Stage 2/6: Emerging Variance — Monitoring micro-drift and preparing mitigation plans.</span>
        </div>
      `;
      if (typeof lucide !== "undefined") lucide.createIcons();
      return;
    } else if (selectedTimelineStepIdx === 2) {
      actionsBox.innerHTML = `
        <div style="display:flex; align-items:center; gap:8px; color:#ea580c; font-size:12px; padding:6px 0;">
          <i data-lucide="zap" style="width:16px;height:16px;color:#ea580c;"></i>
          <span>Stage 3/6: Precursor Breached — Recommendation ${recKey} primed for line execution.</span>
        </div>
      `;
      if (typeof lucide !== "undefined") lucide.createIcons();
      return;
    }

    if (decisionState === "pending") {
      actionsBox.innerHTML = `
        <button class="action-btn" id="btn-approve" onclick="TwinPilotAPI.approve()" style="background:var(--accent-healthy); color:#fff; border:none; padding:10px 18px; border-radius:8px; font-weight:700; font-size:13px; cursor:pointer; display:flex; align-items:center; gap:6px;">
          <i data-lucide="check" style="width:16px;height:16px;"></i>
          Approve ${recKey}
        </button>
        <button class="action-btn reject-btn" id="btn-reject" onclick="TwinPilotAPI.reject()" style="background:rgba(220,38,38,0.1); color:var(--accent-critical); border:1px solid rgba(220,38,38,0.3); padding:10px 16px; border-radius:8px; font-weight:700; font-size:13px; cursor:pointer;">
          Reject Override
        </button>
      `;
    } else if (decisionState === "executing") {
      actionsBox.innerHTML = `
        <div style="padding:10px 16px; background:rgba(99,102,241,0.15); border:1px solid rgba(99,102,241,0.4); border-radius:8px; color:#818cf8; font-weight:700; font-size:12px; display:flex; align-items:center; gap:8px;">
          <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#818cf8; animation:blink 1s infinite;"></span>
          Executing Intervention: ${recKey} (${optVal.name})...
        </div>
      `;
    } else if (decisionState === "approved") {
      const acc = decisionRecord?.accuracy || {};
      const obs = decisionRecord?.observed_outcome || {};
      const rlData = decisionRecord?.rl_learning || {};
      const success = acc.is_successful;
      const obsTput = obs.observed_tput_pct != null ? `${obs.observed_tput_pct >= 0 ? "+" : ""}${obs.observed_tput_pct}%` : "+7.5%";
      const obsQ = obs.observed_queue_change != null ? `${obs.observed_queue_change >= 0 ? "+" : ""}${obs.observed_queue_change}` : "-9 units";
      const rlRew = rlData.rl_reward_applied != null ? `${rlData.rl_reward_applied >= 0 ? "+" : ""}${rlData.rl_reward_applied} pts` : "+320.5 pts";

      const isStage6 = (selectedTimelineStepIdx === 5);
      actionsBox.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:8px; width:100%;">
          <div style="padding:10px 14px; background:rgba(5,150,105,0.15); border:1px solid rgba(5,150,105,0.4); border-radius:8px; font-size:12px;">
            <div style="font-weight:800; color:var(--accent-healthy); margin-bottom:4px;">
              ${isStage6 ? "✓ STAGE 6/6: FULL NOMINAL STATE RESTORED" : (success ? "✓ INTERVENTION APPROVED & VALIDATED" : "⚠ INTERVENTION APPROVED (Divergence Logged)")}
            </div>
            <div>${isStage6 ? "Line Telemetry: <strong>Nominal 46.0s Cycle Time</strong> | Backlog: <strong>0 Units</strong> | Defect Risk: <strong>0.0%</strong>" : `Observed Tput: <strong>${obsTput}</strong> | Observed Queue: <strong>${obsQ}</strong>`}</div>
            <div style="margin-top:3px; color:#10b981; font-weight:700;">RL Agent Reward: <strong>${rlRew}</strong> (Policy Updated Online)</div>
            <div style="font-size:10.5px; color:var(--text-secondary); margin-top:2px;">${isStage6 ? "All 31 stations running within 100% nominal baseline tolerances." : (acc.feedback || "Audit record active")}</div>
          </div>
          <button onclick="TwinPilotAPI.resetDecisionState()" style="background:transparent; border:1px dashed var(--border-color); color:var(--text-secondary); padding:6px 12px; border-radius:6px; font-size:11px; cursor:pointer; align-self:flex-start;">
            ↺ Reset Decision State
          </button>
        </div>
      `;
    } else if (decisionState === "rejected") {
      const rlData = decisionRecord?.rl_learning || {};
      const rlRew = rlData.rl_reward_applied != null ? `${rlData.rl_reward_applied} pts` : "-250.0 pts";

      actionsBox.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:8px; width:100%;">
          <div style="padding:10px 14px; background:rgba(220,38,38,0.12); border:1px solid rgba(220,38,38,0.4); border-radius:8px; font-size:12px;">
            <div style="font-weight:800; color:var(--accent-critical); margin-bottom:2px;">❌ OPERATOR OVERRIDE REJECTED</div>
            <div>Automated intervention bypassed. Plant manager manual pacing active.</div>
            <div style="margin-top:3px; color:#ef4444; font-weight:700;">RL Agent Penalty: <strong>${rlRew}</strong> (Policy Updated Online)</div>
          </div>
          <button onclick="TwinPilotAPI.resetDecisionState()" style="background:transparent; border:1px dashed var(--border-color); color:var(--text-secondary); padding:6px 12px; border-radius:6px; font-size:11px; cursor:pointer; align-self:flex-start;">
            ↺ Reset Decision State
          </button>
        </div>
      `;
    }

    if (typeof lucide !== "undefined") lucide.createIcons();
  }

  // ── Render Cockpit (dashboard.html) ───────────────────────────────────────
  function renderCockpit(state) {
    const target = state.target_station;
    const metrics = state.overall_metrics;
    const anomaly = state.anomaly_prediction;
    const pathSet = new Set(state.propagation.path || []);

    // 1. Header Telemetry
    setText("sim-clock", formatSimClockFromSeconds(currentSimSeconds));
    setText("factory-overall-health", `${metrics.overall_health_pct}%`);
    setStyle("factory-overall-health", "color", metrics.overall_health_pct >= 90 ? "var(--accent-healthy)" : (metrics.overall_health_pct >= 75 ? "var(--accent-warning)" : "var(--accent-critical)"));
    setText("factory-throughput", `${metrics.line_throughput_uph} u/h`);

    // 2. 31-Station Factory Strip
    render31StationsStrip(state.stations, target.station_id, pathSet);

    // 3. Predictive Alert Card (Stage-Dependent Styling & Icons)
    const alertCard = document.getElementById("predictive-alert-card");
    const stageNames = ["baseline", "emerging", "rising", "prediction", "future", "interventions"];
    const stageClass = `stage-${selectedTimelineStepIdx}-${stageNames[selectedTimelineStepIdx] || 'baseline'}`;

    if (alertCard) {
      alertCard.className = `glass-card predictive-alert-card active ${stageClass}`;
      
      const headerIcon = alertCard.querySelector(".alert-header i");
      if (headerIcon) {
        const iconNames = ["shield-check", "alert-circle", "zap", "alert-triangle", "alert-octagon", "check-circle-2"];
        headerIcon.setAttribute("data-lucide", iconNames[selectedTimelineStepIdx] || "shield-check");
      }
    }

    setText("alert-title-text", anomaly.alert_title);
    setHTML("alert-msg-text", anomaly.alert_message);
    setText("alert-confidence-band", anomaly.confidence_band);
    setText("alert-est-downtime", anomaly.est_downtime_mins > 0 ? `${anomaly.est_downtime_mins} mins` : "0 mins (Nominal)");

    // Prediction Factors list
    const factorsBox = document.getElementById("pred-factors");
    if (factorsBox && anomaly.prediction_factors) {
      let factorsHTML = `<div style="margin-bottom:6px; font-weight:700; color:var(--text-primary);">Observed Telemetry & Model Factors:</div>`;
      anomaly.prediction_factors.slice(0, 3).forEach(f => {
        const color = f.type === "critical" ? "var(--accent-critical)" : (f.type === "warning" ? "var(--accent-warning)" : "var(--text-primary)");
        factorsHTML += `<div style="display:flex; justify-content:space-between; margin-bottom:3px;">
          <span>${f.name} <span style="font-size:9px; color:var(--text-muted);">(${f.raw_val})</span></span>
          <span style="color:${color}; font-weight:700;">${f.delta_str}</span>
        </div>`;
      });
      const topFactor = anomaly.prediction_factors[anomaly.prediction_factors.length - 1];
      factorsHTML += `<div style="margin-top:6px; padding-top:6px; border-top:1px solid rgba(255,255,255,0.1); display:flex; justify-content:space-between; font-weight:700;">
        <span>${topFactor.name}</span>
        <span style="color:${colorForProb(anomaly.defect_prob_pct || anomaly.bottleneck_prob_pct)}; font-size:13px;">${topFactor.delta_str}</span>
      </div>`;
      factorsBox.innerHTML = factorsHTML;
    }

    // 4. Counterfactual What-If Simulator (State-Driven)
    const opts = state.interventions;
    const recKey = state.recommendation.option_key;
    selectedOptionKey = selectedOptionKey || recKey;

    const optMap = { "Option A": "a", "Option B": "b", "Option C": "c" };

    Object.entries(opts).forEach(([optKey, optVal]) => {
      const k = optMap[optKey];
      if (!k) return;

      setText(`val-${k}-tput`, `${optVal.tput_pct >= 0 ? "+" : ""}${optVal.tput_pct}%`);
      setText(`val-${k}-queue`, `${optVal.queue_change >= 0 ? "+" : ""}${optVal.queue_change}`);

      const defEl = document.getElementById(`val-${k}-defect`);
      if (defEl) defEl.textContent = `${optVal.defect_risk_change >= 0 ? "+" : ""}${optVal.defect_risk_change}%`;

      const barTput = document.getElementById(`bar-${k}-tput`);
      if (barTput) {
        const w = Math.min(100, Math.abs(optVal.tput_pct) * 3);
        barTput.style.width = `${Math.max(15, w)}%`;
        barTput.className = `bar-fill ${optVal.tput_pct >= 0 ? "positive" : "negative"}`;
      }
      const barQueue = document.getElementById(`bar-${k}-queue`);
      if (barQueue) {
        const w = Math.min(100, Math.abs(optVal.queue_change) * 10);
        barQueue.style.width = `${Math.max(15, w)}%`;
        barQueue.className = `bar-fill ${optVal.queue_change <= 0 ? "positive" : "negative"}`;
      }

      const card = document.getElementById(`scenario-${k}`);
      if (card) {
        const isRec = (optKey === recKey && selectedTimelineStepIdx >= 2);
        card.classList.toggle("active-option", optKey === selectedOptionKey && selectedTimelineStepIdx >= 2);
        card.style.opacity = selectedTimelineStepIdx >= 2 ? "1.0" : "0.75";
        
        const badge = card.querySelector(".scenario-badge");
        if (badge) {
          badge.textContent = isRec ? "AI Recommended" : `Option ${k.toUpperCase()}`;
          badge.style.color = isRec ? "var(--accent-healthy)" : "";
        }
        const nameEl = card.querySelector(".scenario-name");
        if (nameEl) nameEl.textContent = optVal.name;
        
        const impactEl = card.querySelector(".scenario-impact");
        if (impactEl) {
          const net = optVal.financial_impact;
          impactEl.textContent = (selectedTimelineStepIdx >= 2)
            ? `${optVal.impact_summary} (Net: ${net >= 0 ? "+" : ""}$${net.toFixed(0)})`
            : `Passive projection: Net value ${net >= 0 ? "+" : ""}$${net.toFixed(0)}`;
        }
      }
    });

    setText("scenario-impact-text", state.recommendation.rationale);

    // 5. Render Approval State Machine
    renderApprovalControls(recKey, opts[recKey]);

    // 6. Render Compact Milestone Navigator + Single Detail Panel
    renderTwinTimeline(state.twin_timeline);

    // 7. Ask the Twin Chips
    const chips = document.querySelectorAll(".chat-quick-asks .quick-ask-chip");
    if (chips.length >= 3) {
      chips[0].textContent = `Why is Station ${target.station_id} deviating?`;
      chips[0].setAttribute("onclick", `askPredefined('Why is Station ${target.station_id} slowing down?')`);
      chips[1].textContent = `What is the likely root cause (${state.root_cause.candidate_id || state.root_cause.station_id})?`;
      chips[1].setAttribute("onclick", `askPredefined('What is the likely root cause of the anomaly at ${target.station_id}?')`);
      chips[2].textContent = `How does ${recKey} stabilize the line?`;
      chips[2].setAttribute("onclick", `askPredefined('How does ${recKey} help?')`);
    }

    // 8. Load persistent audit logs
    loadRecentAuditLogs();
  }

  // ── Render Diagnostics (analytics.html) ───────────────────────────────────
  function renderDiagnostics(state) {
    const target = state.target_station;
    const metrics = state.overall_metrics;
    const prop = state.propagation;
    const pathSet = new Set(prop.path || []);

    // 1. Header Telemetry
    setText("sim-clock", formatSimClockFromSeconds(currentSimSeconds));
    setText("factory-overall-health", `${metrics.overall_health_pct}%`);
    setText("factory-throughput", `${metrics.line_throughput_uph} u/h`);

    // 2. 31-Station Factory Strip
    render31StationsStrip(state.stations, target.station_id, pathSet);

    // 3. Causal Chain Row
    const chainRow = document.querySelector(".causal-chain-row");
    if (chainRow && prop.path_stations) {
      chainRow.innerHTML = "";
      if (prop.path_stations.length === 0) {
        chainRow.innerHTML = `<div style="color:var(--text-secondary); font-size:12px; padding:10px;">Line operating within normal baseline. Zero active propagation paths.</div>`;
      } else {
        prop.path_stations.forEach((stObj, idx) => {
          const node = document.createElement("div");
          node.className = `causal-node ${stObj.station_id === prop.path[0] ? "active" : ""}`;
          node.id = `cnode-${idx + 1}`;
          node.innerHTML = `
            <span class="causal-node-title">${stObj.station_id}</span>
            <span class="causal-node-value" style="color:${colorForProb(stObj.risk_pct)}; font-weight:700;">${stObj.risk_pct}% risk</span>
            <span style="font-size:9px; color:var(--text-muted);">${stObj.station_name}</span>
          `;
          chainRow.appendChild(node);

          if (idx < prop.path_stations.length - 1) {
            const arr = document.createElement("div");
            arr.className = "causal-arrow";
            arr.textContent = "→";
            chainRow.appendChild(arr);
          }
        });
      }
    }

    // 4. Stat chips
    setText("prop-cause", prop.earliest_cause);
    setText("prop-risk", prop.predicted_defect);
    setText("prop-reduction", prop.recommended_action);

    // 5. Quarantined At-Risk Vehicles Cohort
    const vrow = document.querySelector(".vehicle-row");
    const vlabel = document.getElementById("risk-vehicle-label");
    const atRisk = state.at_risk_vehicles || {};
    const vins = atRisk.vins_cohort || state.propagation.quarantined_vins || [];
    const totalCount = atRisk.total_count || 0;
    const isAnomalyActive = (selectedTimelineStepIdx >= 2) && (state.is_anomaly_active !== false);

    if (vlabel) {
      if (atRisk.quarantine_label) {
        vlabel.textContent = atRisk.quarantine_label;
      } else if (isAnomalyActive && totalCount > 0) {
        vlabel.textContent = `${totalCount} vehicles quarantined at ${atRisk.quarantine_location || 'Buffer line prior to Station S07'}`;
      } else {
        vlabel.textContent = "Quarantine cohort calculated from physical line timings";
      }
    }

    if (vrow) {
      vrow.innerHTML = "";
      if (selectedTimelineStepIdx === 0) {
        // Stage 1: Nominal baseline (Picture 1)
        vrow.innerHTML = `<div style="color:var(--text-secondary); font-size:12px; padding:4px 0; display:flex; align-items:center; gap:6px;">
          <i data-lucide="shield-check" style="width:16px;height:16px;color:var(--accent-healthy);"></i>
          All produced VINs verified defect-free in active window (0 vehicles quarantined).
        </div>`;
      } else if (selectedTimelineStepIdx === 5 && decisionState === "approved") {
        // Stage 6: Nominal Restored after Approval
        // Quarantined vehicles inspected and cleared before final release!
        vrow.innerHTML = "";
        const clearedSample = (atRisk.sample_vins || ["VIN-2030243", "VIN-2030244", "VIN-2030245", "VIN-2030246", "VIN-2030247"]).slice(0, 5);
        clearedSample.forEach((vinCode, i) => {
          const card = document.createElement("div");
          card.className = "vehicle-icon-card healthy-car";
          card.id = `vehicle-${i + 1}`;
          card.title = `VIN: ${vinCode} — Physical inspection complete. Quality gate passed for final release.`;
          card.innerHTML = `
            <i data-lucide="check-circle" style="width:18px;height:18px;color:var(--accent-healthy);"></i>
            <span>${vinCode}</span>
          `;
          vrow.appendChild(card);
        });
        const rem = (totalCount || 44) - clearedSample.length;
        if (rem > 0) {
          const moreCard = document.createElement("div");
          moreCard.className = "vehicle-icon-card";
          moreCard.style.opacity = "0.85";
          moreCard.title = `${rem} additional vehicles inspected & cleared`;
          moreCard.innerHTML = `
            <i data-lucide="check" style="width:18px;height:18px;color:var(--accent-healthy);"></i>
            <span>+${rem} cleared</span>
          `;
          vrow.appendChild(moreCard);
        }
      } else if (vins && vins.length > 0 && isAnomalyActive) {
        // Picture 2: Anomaly Active / Rising
        // Render each vehicle with car symbol:
        // Only vehicles that went through the stations under risk are flagged as at-risk!
        vins.slice(0, 5).forEach((v, i) => {
          const vinCode = typeof v === "string" ? v : v.vin;
          const isAtRisk = (typeof v === "object" && v.status) ? (v.status === "at-risk" || v.status === "warning") : true;
          const card = document.createElement("div");
          card.className = `vehicle-icon-card ${isAtRisk ? "at-risk" : "healthy-car"}`;
          card.id = `vehicle-${i + 1}`;
          card.title = (typeof v === "object" && v.exposure_reason) ? v.exposure_reason : `VIN: ${vinCode} — Traversed at-risk station. Held for inspection before final release.`;
          card.innerHTML = `
            <i data-lucide="car" style="width:18px;height:18px;"></i>
            <span>${vinCode}</span>
          `;
          vrow.appendChild(card);
        });

        // More card (e.g. +39 more) with horizontal more dots (Picture 2)
        const remainingCount = totalCount - 5;
        if (remainingCount > 0) {
          const moreCard = document.createElement("div");
          moreCard.className = "vehicle-icon-card";
          moreCard.style.opacity = "0.75";
          moreCard.title = `${remainingCount} additional vehicles queued at buffer quality gate`;
          moreCard.innerHTML = `
            <i data-lucide="more-horizontal" style="width:18px;height:18px;"></i>
            <span>+${remainingCount} more</span>
          `;
          vrow.appendChild(moreCard);
        }
      } else {
        vrow.innerHTML = `<div style="color:var(--text-secondary); font-size:12px; padding:4px 0;">All produced VINs verified defect-free in active window.</div>`;
      }
    }

    // 6. Dynamic Dark Zone Matrix (6 Manual Stations)
    const dzList = state.dark_zones || [];
    const degradingDz = dzList.find(d => d.is_degrading);
    const dzHeader = document.getElementById("dz-card-title");
    const dzCenterBadge = document.getElementById("inferred-dz-badge");
    const dzConf = document.getElementById("sensorless-confidence");
    const dzDesc = document.getElementById("sensorless-desc-text");
    const dzMatrix = document.getElementById("dz-stations-matrix");

    if (degradingDz) {
      if (dzHeader) {
        dzHeader.innerHTML = `<i data-lucide="eye-off" style="width:16px;height:16px;color:var(--accent-critical);"></i> Dark Zone Anomaly: Station ${degradingDz.station_id} (${degradingDz.station_name})`;
      }
      if (dzCenterBadge) {
        dzCenterBadge.textContent = `${degradingDz.station_id} Degrading (${degradingDz.degradation_prob_pct}%)`;
        dzCenterBadge.style.background = "var(--accent-critical-bg)";
        dzCenterBadge.style.borderColor = "var(--accent-critical)";
        dzCenterBadge.style.color = "var(--accent-critical)";
      }
      if (dzConf) {
        dzConf.textContent = `Inferred Degradation Probability: ${degradingDz.degradation_prob_pct}%`;
        dzConf.style.color = "var(--accent-critical)";
      }
      if (dzDesc) {
        dzDesc.innerHTML = `Station <strong>${degradingDz.station_id} (${degradingDz.station_name})</strong> is a manual assembly station with NO sensors. Reconstructed from upstream cycle trends & downstream buffer queues: <strong>Degradation detected with ${degradingDz.degradation_prob_pct}% probability.</strong>`;
      }
    } else {
      if (dzHeader) {
        dzHeader.innerHTML = `<i data-lucide="eye-off" style="width:16px;height:16px;color:var(--accent-info);"></i> Dark Zone Sensorless Inference (6 Manual Stations)`;
      }
      if (dzCenterBadge) {
        dzCenterBadge.textContent = "6 Manual Stations Monitored";
        dzCenterBadge.style.background = "var(--accent-healthy-bg)";
        dzCenterBadge.style.borderColor = "var(--accent-healthy)";
        dzCenterBadge.style.color = "var(--accent-healthy)";
      }
      if (dzConf) {
        dzConf.textContent = "All 6 Sensorless Stations Operating Nominally";
        dzConf.style.color = "var(--accent-healthy)";
      }
      if (dzDesc) {
        dzDesc.innerHTML = `Monitoring manual assembly stations <strong>S18, S20, S21, S22, S29, S30</strong> via proxy telemetry. Zero degradation detected across manual zones.`;
      }
    }

    if (dzMatrix) {
      dzMatrix.innerHTML = "";
      dzList.forEach(m => {
        const isDeg = m.is_degrading;
        const box = document.createElement("div");
        box.style.cssText = `
          background: ${isDeg ? "var(--accent-critical-bg)" : "rgba(0,0,0,0.03)"};
          border: 1px solid ${isDeg ? "var(--accent-critical)" : "var(--border-color)"};
          border-radius: 6px; padding: 6px 8px; font-size: 11px;
        `;
        box.innerHTML = `
          <div style="display:flex; justify-content:space-between; font-weight:700;">
            <span>${m.station_id}</span>
            <span style="color:${isDeg ? "var(--accent-critical)" : "var(--accent-healthy)"};">${isDeg ? "DEGRADING" : "NOMINAL"}</span>
          </div>
          <div style="font-size:9.5px; color:var(--text-muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${m.station_name}</div>
          <div style="font-size:10px; margin-top:2px; font-weight:600; color:${isDeg ? "var(--accent-critical)" : "var(--text-secondary)"};">Risk: ${m.degradation_prob_pct}%</div>
        `;
        dzMatrix.appendChild(box);
      });
    }

    if (typeof lucide !== "undefined") lucide.createIcons();
  }

  // ── Approval Decision Handlers ─────────────────────────────────────────────
  async function approve() {
    if (!latestState) return;
    const recKey = latestState.recommendation.option_key;
    const optVal = latestState.interventions[recKey];

    decisionState = "executing";
    renderApprovalControls(recKey, optVal);
    playSound('beep');

    try {
      const resp = await fetch(`${BASE}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: clock.runId,
          minute: clock.minute,
          station: clock.station,
          event_id: clock.event_id,
          option_key: recKey,
          rationale: latestState.recommendation.rationale
        })
      });

      const auditRecord = await resp.json();
      decisionState = "approved";
      decisionRecord = auditRecord;
      saveSession();

      await fetchAndRenderState();
      loadRecentAuditLogs();
      playSound('chime');
      showToast(`Intervention ${recKey} approved! Post-intervention telemetry stabilized. RL model rewarded (+320.5 pts).`, "success");
    } catch (err) {
      console.error("Approve failed:", err);
      decisionState = "pending";
      renderApprovalControls(recKey, optVal);
      showToast("Could not record approval on server.", "error");
    }
  }

  async function reject() {
    if (!latestState) return;
    const recKey = latestState.recommendation.option_key;
    const optVal = latestState.interventions[recKey];

    decisionState = "executing";
    renderApprovalControls(recKey, optVal);
    playSound('alert');

    try {
      const resp = await fetch(`${BASE}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: clock.runId,
          minute: clock.minute,
          station: clock.station,
          event_id: clock.event_id,
          option_key: recKey,
          rationale: "Operator rejected automated intervention"
        })
      });

      const auditRecord = await resp.json();
      decisionState = "rejected";
      decisionRecord = auditRecord;
      saveSession();

      await fetchAndRenderState();
      loadRecentAuditLogs();
      showToast("Automated intervention rejected. Line operating under manual control. RL policy penalized (-250.0 pts).", "warning");
    } catch (err) {
      console.error("Reject failed:", err);
      decisionState = "rejected";
      renderApprovalControls(recKey, optVal);
      showToast("Automated intervention rejected.", "warning");
    }
  }

  async function loadRecentAuditLogs() {
    const logBox = document.getElementById("override-log");
    if (!logBox) return;

    try {
      const resp = await fetch(`${BASE}/audit_log`);
      if (!resp.ok) return;
      const logs = await resp.json();
      if (!logs || logs.length === 0) return;

      logBox.innerHTML = "";
      logs.slice(-5).reverse().forEach(entry => {
        const pred = entry.twinpilot_prediction || {};
        const acc = entry.accuracy || {};
        const success = acc.is_successful;
        const div = document.createElement("div");
        div.className = `override-log-entry ${success ? "" : "rejected"}`;
        div.style.marginBottom = "4px";
        div.innerHTML = `<strong>[${entry.event_id || entry.run_id}]</strong> ${pred.recommended_option} — ${success ? "Validated" : "Logged"}. Acc: ${acc.overall_accuracy_pct ? acc.overall_accuracy_pct.toFixed(1) + "%" : "N/A"}`;
        logBox.appendChild(div);
      });
    } catch (e) {
      console.warn("Could not load audit log:", e);
    }
  }

  // ── Render Responsible AI & Trust Center (responsible-ai.html) ─────────────
  function renderResponsibleAI(state) {
    const metrics = state.overall_metrics || {};

    // 1. Header Telemetry & Clock
    setText("sim-clock", formatSimClockFromSeconds(currentSimSeconds));
    if (metrics.overall_health_pct != null) {
      setText("factory-overall-health", `${metrics.overall_health_pct}%`);
      setStyle("factory-overall-health", "color", metrics.overall_health_pct >= 90 ? "var(--accent-healthy)" : (metrics.overall_health_pct >= 75 ? "var(--accent-warning)" : "var(--accent-critical)"));
    }

    // 2. Dynamic Trust Score Calibration
    let trustVal = 94;
    if (decisionState === "approved") {
      trustVal = 98;
    } else if (decisionState === "rejected") {
      trustVal = 88;
    } else if (selectedTimelineStepIdx >= 3) {
      trustVal = 91;
    }

    setText("trust-score-pct", `${trustVal}%`);
    const circle = document.getElementById("trust-fill-circle");
    if (circle) {
      const circ = 2 * Math.PI * 54; // ~339.29
      const offset = circ - (circ * (trustVal / 100));
      circle.style.strokeDashoffset = offset;
    }

    // 3. Load & Render Live Audit Logs
    loadRecentAuditLogs();
  }

  // ── Fetch & Load State from API ───────────────────────────────────────────
  async function fetchAndRenderState() {
    const activeFid = localStorage.getItem("twinpilot_active_factory") || "demo-detroit-31";
    let url = `${BASE}/scenario?run_id=${clock.runId}&minute=${clock.minute}&station=${clock.station}&event_id=${clock.event_id || ""}&step_id=${selectedTimelineStepIdx}`;
    if (activeFid && activeFid !== "demo-detroit-31") {
      url += `&factory_id=${activeFid}`;
    }

    try {
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const state = await resp.json();
      latestState = state;
      window.latestFactoryState = state;

      // Update topology info badge in bar if custom factory
      const topInfo = document.getElementById("tp-topology-info");
      if (topInfo && state.is_custom_factory) {
        topInfo.innerHTML = `Topology: <strong style="color:#38bdf8;">${state.factory_name} (${state.stations.length} Stations)</strong>`;
      } else if (topInfo) {
        topInfo.innerHTML = `Topology: <strong style="color:#f8fafc;">30 Mainline (S01–S30) + 1 Feeder (ENG01)</strong>`;
      }

      // Sync approval state from backend
      if (state.approval_state && state.approval_state.status !== "pending") {
        decisionState = state.approval_state.status;
        decisionRecord = state.approval_state.record;
      }

      const path = window.location.pathname;
      if (path.includes("analytics")) {
        renderDiagnostics(state);
      } else if (path.includes("responsible-ai")) {
        renderResponsibleAI(state);
      } else {
        renderCockpit(state);
      }

      if (typeof lucide !== "undefined") lucide.createIcons();
    } catch (err) {
      console.error("[TwinPilot Universal Bridge] fetchAndRenderState failed:", err);
    }
  }

  function selectScenarioCard(optKeyShort) {
    const keyMap = { "A": "Option A", "B": "Option B", "C": "Option C" };
    selectedOptionKey = keyMap[optKeyShort] || "Option A";
    if (latestState) {
      const opt = latestState.interventions[selectedOptionKey];
      if (opt) {
        setText("scenario-impact-text", `${selectedOptionKey} (${opt.name}): ${opt.impact_summary} Projected Throughput: ${opt.tput_pct >= 0 ? "+" : ""}${opt.tput_pct}%, Queue Change: ${opt.queue_change}, Net Economic Value: $${opt.financial_impact >= 0 ? "+" : ""}${opt.financial_impact.toFixed(0)}.`);
      }
      document.querySelectorAll(".scenario-card").forEach(card => card.classList.remove("active-option"));
      const activeEl = document.getElementById(`scenario-${optKeyShort.toLowerCase()}`);
      if (activeEl) activeEl.classList.add("active-option");
    }
  }

  // ── Init on page load ──────────────────────────────────────────────────────
  function init() {
    restoreSession();
    injectSimulationBar();
    initMasterClockEngine();
    updateClockControlButtons();
    fetchAndRenderState();
  }

  if (typeof window !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  }

  return {
    init,
    reset,
    resetDecisionState,
    setSpeed,
    toggleClock,
    seekToMilestone,
    approve,
    reject,
    switchScenario,
    selectScenarioCard,
    getLatestState: () => latestState
  };
})();
