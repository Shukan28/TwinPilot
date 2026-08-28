/**
 * TwinPilot Live API Bridge & Universal Data-Driven Digital Twin Engine
 * ====================================================================
 * Connects the HTML/JS frontend to the Python backend (127.0.0.1:5000).
 * 
 * Flow:
 *  1. DETECTION: Live sensor telemetry with real drift vs stations_master baseline.
 *  2. PREDICTION: Multi-model intelligence (Defect RF, Bottleneck Precursor,
 *     Dark Zone proxy inference, 3-Factor Root Cause localization, Graph Propagation).
 *  3. HUMAN INTERVENTION: Constraint-aware counterfactual simulator with Approve/Reject.
 *  4. SOLUTION & OUTCOME: Real post-intervention validation (+20m window) and audit logging.
 *  5. TWIN TIMELINE: Compact milestone navigator with single expandable detail panel.
 */

const TwinPilotAPI = (() => {
  const BASE = (typeof window !== "undefined" && window.location.port === "5000")
    ? "/api"
    : "http://127.0.0.1:5000/api";

  const SCENARIOS = {
    "RUN024-EVT01": { run_id: "RUN-024", defaultMinute: 143, station: "S03", event_id: "RUN024-EVT01", title: "RUN-024 (S03 Defect Surge — Option C recommended)" },
    "RUN025-EVT02": { run_id: "RUN-025", defaultMinute: 93,  station: "S16", event_id: "RUN025-EVT02", title: "RUN-025 (S16 Delay & S21 Dark Zone — Option A recommended)" },
  };

  const clock = {
    runId: "RUN-024",
    minute: 143,
    station: "S03",
    event_id: "RUN024-EVT01"
  };

  let latestState = null;
  let selectedOptionKey = null;
  let decisionState = "pending"; // "pending" | "executing" | "approved" | "rejected"
  let decisionRecord = null;
  let selectedTimelineStepIdx = 3; // default: Step 3 (Current Prediction NOW)

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

  // ── Clean Master Top Bar (Scenario Selector & System Status Only) ──────────
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
      <div style="display:flex; align-items:center; gap:12px;">
        <div style="display:flex; align-items:center; gap:8px;">
          <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#10b981; animation:blink 1.5s infinite;"></span>
          <span style="color:#818cf8; font-weight:800; letter-spacing:0.05em; text-transform:uppercase;">Twin Scenario:</span>
        </div>
        <select id="tp-scenario-select" style="background:#0f172a; color:#f8fafc; border:1px solid rgba(99,102,241,0.5);
          border-radius:6px; padding:5px 12px; font-size:12px; font-weight:600; cursor:pointer; outline:none;">
          <option value="RUN024-EVT01">RUN-024 (S03 Defect Surge — Option C recommended)</option>
          <option value="RUN025-EVT02">RUN-025 (S16 Delay & S21 Dark Zone — Option A recommended)</option>
        </select>
      </div>

      <!-- Line Structure & Intelligence Pipeline Badge -->
      <div style="display:flex; align-items:center; gap:12px;">
        <span style="font-size:11px; color:#94a3b8;">Topology: <strong style="color:#f8fafc;">30 Mainline (S01–S30) + 1 Feeder (ENG01)</strong></span>
        <span style="background:rgba(16,185,129,0.15); color:#10b981; border:1px solid rgba(16,185,129,0.3); padding:3px 8px; border-radius:4px; font-size:10.5px; font-weight:700;">● ML Intelligence Live</span>
      </div>
    `;

    const sel = document.getElementById("tp-scenario-select");
    if (sel) {
      sel.value = clock.event_id || "RUN024-EVT01";
      sel.addEventListener("change", (e) => {
        switchScenario(e.target.value);
      });
    }
  }

  function setMinute(m) {
    clock.minute = m;
    fetchAndRenderState();
  }

  function switchScenario(scenarioKey) {
    const cfg = SCENARIOS[scenarioKey];
    if (!cfg) return;

    clock.runId = cfg.run_id;
    clock.minute = cfg.defaultMinute;
    clock.station = cfg.station;
    clock.event_id = cfg.event_id;
    selectedOptionKey = null;
    decisionState = "pending";
    decisionRecord = null;
    selectedTimelineStepIdx = 3;

    // Reset session decision state on backend for smooth switching
    fetch(`${BASE}/reset_decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: clock.runId, event_id: clock.event_id })
    }).catch(() => {});

    fetchAndRenderState();
  }

  async function reset() {
    const cfg = SCENARIOS[clock.event_id] || SCENARIOS["RUN024-EVT01"];
    clock.runId = cfg.run_id;
    clock.minute = cfg.defaultMinute;
    clock.station = cfg.station;
    clock.event_id = cfg.event_id;
    selectedOptionKey = null;
    decisionState = "pending";
    decisionRecord = null;
    selectedTimelineStepIdx = 3;

    // Clear backend in-session decision state
    try {
      await fetch(`${BASE}/reset_decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: clock.runId, event_id: clock.event_id })
      });
    } catch (e) {}

    const container = document.getElementById("toast-container");
    if (container) container.innerHTML = "";

    await fetchAndRenderState();
    showToast(`Simulation reset to Baseline state (1. Baseline @ ${latestState ? latestState.sim_clock : '10:03 AM'}).`, "info");
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

  // ── Auto-Tour Playback across Milestones ──────────────────────────────────
  let isPlayingTimeline = false;
  let timelinePlayTimer = null;

  function togglePlayTimeline() {
    if (isPlayingTimeline) {
      stopPlayTimeline();
    } else {
      startPlayTimeline();
    }
  }

  function updateTimelinePlayButton(isPlaying) {
    const txt = document.getElementById("btn-play-timeline-text");
    const btn = document.getElementById("btn-play-timeline");
    if (txt) txt.textContent = isPlaying ? "Pause Tour" : "Auto-Tour";
    if (btn) {
      btn.style.background = isPlaying ? "rgba(220,38,38,0.15)" : "rgba(99,102,241,0.12)";
      btn.style.borderColor = isPlaying ? "rgba(220,38,38,0.4)" : "rgba(99,102,241,0.3)";
      btn.style.color = isPlaying ? "var(--accent-critical)" : "#818cf8";
    }
  }

  function startPlayTimeline() {
    isPlayingTimeline = true;
    updateTimelinePlayButton(true);
    if (timelinePlayTimer) clearInterval(timelinePlayTimer);
    
    timelinePlayTimer = setInterval(() => {
      selectedTimelineStepIdx = (selectedTimelineStepIdx + 1) % 6;
      if (latestState && latestState.twin_timeline && latestState.twin_timeline[selectedTimelineStepIdx]) {
        clock.minute = latestState.twin_timeline[selectedTimelineStepIdx].minute;
        fetchAndRenderState();
      }
    }, 3000);
  }

  function stopPlayTimeline() {
    isPlayingTimeline = false;
    updateTimelinePlayButton(false);
    if (timelinePlayTimer) {
      clearInterval(timelinePlayTimer);
      timelinePlayTimer = null;
    }
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
      const isTarget = (st.station_id === targetStationId && latestState && latestState.is_anomaly_active);
      const isPath = pathSet.has(st.station_id) && latestState && latestState.is_anomaly_active;
      const isManual = st.is_manual;
      const isFeeder = (st.station_id === "ENG01");
      
      let badgeClass = "healthy";
      let tierTag = isFeeder ? "FEEDER (RICH)" : st.sensor_tier;
      let tagBg = "rgba(5,150,105,0.15)";
      let tagColor = "var(--accent-healthy)";

      if (isTarget) {
        badgeClass = "critical";
        tagBg = "rgba(220,38,38,0.2)";
        tagColor = "var(--accent-critical)";
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

      const node = document.createElement("div");
      node.className = `station-node ${badgeClass}`;
      node.id = `node-${st.station_id}`;
      node.style.cssText = `
        flex: 0 0 ${isFeeder ? "125px" : "110px"};
        min-width: ${isFeeder ? "125px" : "110px"};
        background: ${isTarget ? "var(--accent-critical-bg)" : (isPath ? "var(--accent-warning-bg)" : (isFeeder ? "rgba(139,92,246,0.06)" : "#ffffff"))};
        border: ${isManual ? "1.5px dashed rgba(37,99,235,0.4)" : `1px solid ${isTarget ? "var(--accent-critical)" : (isPath ? "var(--accent-warning)" : (isFeeder ? "rgba(139,92,246,0.4)" : "var(--border-color)"))}`};
        border-radius: 10px;
        padding: 8px 6px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 4px;
        text-align: center;
        box-shadow: ${isTarget ? "0 0 12px rgba(220,38,38,0.2)" : (isFeeder ? "0 0 8px rgba(139,92,246,0.15)" : "var(--shadow-sm)")};
        transition: transform .2s ease;
      `;

      node.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; width:100%;">
          <span style="font-size:11px; font-weight:800; color:${isFeeder ? "#8b5cf6" : "var(--text-primary)"}; font-family:var(--font-display);">${st.station_id}</span>
          <span style="font-size:8.5px; font-weight:700; padding:1px 4px; border-radius:4px; background:${tagBg}; color:${tagColor}; text-transform:uppercase;">${tierTag}</span>
        </div>
        <div style="font-size:10px; font-weight:600; color:var(--text-secondary); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; width:100%;" title="${st.station_name}">${st.station_name}</div>
        <div style="font-size:13px; font-weight:800; font-family:var(--font-display); color:${isTarget ? "var(--accent-critical)" : (isFeeder ? "#8b5cf6" : "var(--text-primary)")};">${st.cycle_time_sec}s</div>
        <div style="display:flex; justify-content:space-between; width:100%; font-size:9px; color:var(--text-muted); border-top:1px solid rgba(0,0,0,0.05); padding-top:3px;">
          <span>Q: <strong style="color:var(--text-primary);">${st.queue_length}</strong></span>
          <span>Risk: <strong style="color:${colorForProb(st.defect_prob_pct)};">${st.defect_prob_pct}%</strong></span>
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

    const shortNames = [
      "1. Baseline",
      "2. Emerging",
      "3. Rising Risk",
      "4. Now (Pred)",
      "5. Natural Future",
      "6. Interventions"
    ];

    // Render 6 compact milestone buttons in clean 3x2 grid
    timelineSteps.forEach((step, idx) => {
      const isSelected = (idx === selectedTimelineStepIdx);
      const tagStyle = tagStyles[step.category_badge] || tagStyles["OBSERVED TELEMETRY"];

      const btn = document.createElement("button");
      btn.className = `milestone-node-btn ${isSelected ? "active" : ""}`;
      btn.title = `Click to jump to ${step.phase_name} (${step.sim_clock})`;

      btn.innerHTML = `
        <span class="milestone-node-title">
          ${shortNames[idx]}
        </span>
        <span class="milestone-node-time">
          ${step.sim_clock.split(" ")[0]} ${step.sim_clock.split(" ")[1] || ""}
        </span>
      `;

      btn.onclick = () => {
        stopPlayTimeline();
        selectedTimelineStepIdx = idx;
        clock.minute = step.minute;
        fetchAndRenderState();
        showToast(`Jumped simulation to ${step.phase_name} (${step.sim_clock})`, "info");
      };

      stepperTrack.appendChild(btn);
    });

    // Render single expandable detail panel
    const cur = timelineSteps[selectedTimelineStepIdx] || timelineSteps[3];
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
            ${cur.category_badge}
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

    if (!latestState || !latestState.is_anomaly_active) {
      actionsBox.innerHTML = `
        <div style="display:flex; align-items:center; gap:8px; color:var(--text-secondary); font-size:12px; padding:6px 0;">
          <i data-lucide="shield-check" style="width:16px;height:16px;color:var(--accent-healthy);"></i>
          <span>Line Operating Nominally — Counterfactual engine standing by in passive monitoring mode.</span>
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
      const success = acc.is_successful;
      const obsTput = obs.observed_tput_pct != null ? `${obs.observed_tput_pct >= 0 ? "+" : ""}${obs.observed_tput_pct}%` : "N/A";
      const obsQ = obs.observed_queue_change != null ? `${obs.observed_queue_change >= 0 ? "+" : ""}${obs.observed_queue_change}` : "N/A";

      actionsBox.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:8px; width:100%;">
          <div style="padding:10px 14px; background:${success ? "rgba(5,150,105,0.15)" : "rgba(245,158,11,0.15)"}; border:1px solid ${success ? "rgba(5,150,105,0.4)" : "rgba(245,158,11,0.4)"}; border-radius:8px; font-size:12px;">
            <div style="font-weight:800; color:${success ? "var(--accent-healthy)" : "var(--accent-warning)"}; margin-bottom:4px;">
              ${success ? "✓ INTERVENTION APPROVED & VALIDATED" : "⚠ INTERVENTION APPROVED (Divergence Logged)"}
            </div>
            <div>Observed Tput: <strong>${obsTput}</strong> | Observed Queue: <strong>${obsQ}</strong></div>
            <div style="font-size:10.5px; color:var(--text-secondary); margin-top:2px;">${acc.feedback || "Audit record active"}</div>
          </div>
          <button onclick="TwinPilotAPI.resetDecisionState()" style="background:transparent; border:1px dashed var(--border-color); color:var(--text-secondary); padding:6px 12px; border-radius:6px; font-size:11px; cursor:pointer; align-self:flex-start;">
            ↺ Reset Decision State
          </button>
        </div>
      `;
    } else if (decisionState === "rejected") {
      actionsBox.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:8px; width:100%;">
          <div style="padding:10px 14px; background:rgba(220,38,38,0.12); border:1px solid rgba(220,38,38,0.4); border-radius:8px; font-size:12px;">
            <div style="font-weight:800; color:var(--accent-critical); margin-bottom:2px;">❌ OPERATOR OVERRIDE REJECTED</div>
            <div>Automated intervention bypassed. Plant manager manual pacing active.</div>
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
    const isAnomaly = state.is_anomaly_active;

    // 1. Header Telemetry
    setText("sim-clock", state.sim_clock || metrics.sim_clock);
    setText("factory-overall-health", `${metrics.overall_health_pct}%`);
    setStyle("factory-overall-health", "color", metrics.overall_health_pct >= 90 ? "var(--accent-healthy)" : "var(--accent-warning)");
    setText("factory-throughput", `${metrics.line_throughput_uph} u/h`);

    // 2. 31-Station Factory Strip
    render31StationsStrip(state.stations, target.station_id, pathSet);

    // 3. Predictive Alert Card (State-Dependent Gating)
    const alertCard = document.getElementById("predictive-alert-card");
    if (alertCard) {
      alertCard.className = `glass-card predictive-alert-card active ${isAnomaly ? "" : "nominal-alert"}`;
    }
    setText("alert-title-text", anomaly.alert_title);
    setHTML("alert-msg-text", anomaly.alert_message);
    setText("alert-confidence-band", anomaly.confidence_band);
    setText("alert-est-downtime", isAnomaly ? `${anomaly.est_downtime_mins} mins` : "0 mins (Nominal)");

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
        const isRec = (optKey === recKey && isAnomaly);
        card.classList.toggle("active-option", optKey === selectedOptionKey && isAnomaly);
        card.style.opacity = isAnomaly ? "1.0" : "0.75";
        
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
          impactEl.textContent = isAnomaly
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
    setText("sim-clock", state.sim_clock || metrics.sim_clock);
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
    const atRisk = state.at_risk_vehicles;

    if (vlabel) {
      vlabel.textContent = state.is_anomaly_active
        ? `${atRisk.total_count} vehicles quarantined at ${atRisk.quarantine_location}`
        : "0 vehicles quarantined — line operating nominally";
    }

    if (vrow) {
      vrow.innerHTML = "";
      if (atRisk.sample_vins && atRisk.sample_vins.length > 0) {
        atRisk.sample_vins.forEach((vin, i) => {
          const card = document.createElement("div");
          card.className = "vehicle-icon-card at-risk";
          card.id = `vehicle-${i + 1}`;
          card.innerHTML = `
            <i data-lucide="car" style="width:18px;height:18px;"></i>
            <span>${vin}</span>
          `;
          vrow.appendChild(card);
        });

        if (atRisk.total_count > atRisk.sample_vins.length) {
          const moreCard = document.createElement("div");
          moreCard.className = "vehicle-icon-card";
          moreCard.style.opacity = "0.7";
          moreCard.innerHTML = `
            <i data-lucide="more-horizontal" style="width:18px;height:18px;"></i>
            <span>+${atRisk.total_count - atRisk.sample_vins.length} more</span>
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
  }

  // ── Load Persistent Audit Logs ─────────────────────────────────────────────
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

  // ── Fetch & Load State from API ───────────────────────────────────────────
  async function fetchAndRenderState() {
    const url = `${BASE}/scenario?run_id=${clock.runId}&minute=${clock.minute}&station=${clock.station}&event_id=${clock.event_id || ""}`;
    try {
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const state = await resp.json();
      latestState = state;
      window.latestFactoryState = state;

      // Sync approval state from backend
      if (state.approval_state && state.approval_state.status !== "pending") {
        decisionState = state.approval_state.status;
        decisionRecord = state.approval_state.record;
      }

      const path = window.location.pathname;
      if (path.includes("analytics")) {
        renderDiagnostics(state);
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
      const activeCard = document.getElementById(`scenario-${optKeyShort.toLowerCase()}`);
      if (activeCard) activeCard.classList.add("active-option");
    }
  }

  // ── State Machine Approve / Reject Handlers ───────────────────────────────
  async function approve() {
    if (!latestState) return;
    decisionState = "executing";
    renderApprovalControls(latestState.recommendation.option_key, latestState.interventions[latestState.recommendation.option_key]);
    playSound('chime');

    const body = {
      run_id: clock.runId,
      minute: clock.minute,
      station: clock.station,
      event_id: clock.event_id,
      operator_action: "approve"
    };

    try {
      const resp = await fetch(`${BASE}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const record = await resp.json();
      decisionRecord = record;
      decisionState = "approved";
      renderApprovalControls(latestState.recommendation.option_key, latestState.interventions[latestState.recommendation.option_key]);
      showToast("Intervention approved and executed.", "success");
      loadRecentAuditLogs();
    } catch (err) {
      console.error("[TwinPilot Universal Bridge] approve failed:", err);
      decisionState = "pending";
    }
  }

  async function reject() {
    if (!latestState) return;
    decisionState = "executing";
    renderApprovalControls(latestState.recommendation.option_key, latestState.interventions[latestState.recommendation.option_key]);
    playSound('alert');

    const body = {
      run_id: clock.runId,
      minute: clock.minute,
      station: clock.station,
      event_id: clock.event_id,
      operator_action: "reject"
    };

    try {
      const resp = await fetch(`${BASE}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const record = await resp.json();
      decisionRecord = record;
      decisionState = "rejected";
      renderApprovalControls(latestState.recommendation.option_key, latestState.interventions[latestState.recommendation.option_key]);
      showToast("Intervention override rejected.", "critical");
      loadRecentAuditLogs();
    } catch (err) {
      console.error("[TwinPilot Universal Bridge] reject failed:", err);
      decisionState = "pending";
    }
  }

  // ── Initialization ────────────────────────────────────────────────────────
  function init() {
    injectSimulationBar();
    fetchAndRenderState();
  }

  return {
    init,
    clock,
    setMinute,
    switchScenario,
    reset,
    togglePlayTimeline,
    approve,
    reject,
    resetDecisionState,
    selectScenarioCard,
    SCENARIOS
  };
})();

// Global action delegates
function approveRecommendation() {
  TwinPilotAPI.approve();
}
function rejectRecommendation() {
  TwinPilotAPI.reject();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", TwinPilotAPI.init);
} else {
  TwinPilotAPI.init();
}
