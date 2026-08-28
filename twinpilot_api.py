"""
TwinPilot Local API Server (Data-Driven Unified Factory State Engine)
=====================================================================
Exposes the single unified factory_state for the entire 31-station manufacturing line:
  - 30 Mainline stations (S01–S30) + 1 Feeder (ENG01)
  - 6 Manual Dark Zone stations (S18, S20, S21, S22, S29, S30)
  - Real timeline clock (minutes 0 to 239)
  - Complete 6-phase Twin Evolution Timeline:
      1. Baseline → 2. Emerging Signal → 3. Rising Risk →
      4. Current Prediction (NOW) → 5. Natural Future (Do Nothing) →
      6. A/B/C Counterfactual Intervention Projections
  - In-session decision state machine with instant reset support

Endpoints:
  GET  /api/scenario?run_id=RUN-024&minute=143&station=S03&event_id=RUN024-EVT01
       → returns complete unified factory_state JSON
  POST /api/approve
       → runs outcome learning, updates in-session state and persistent audit log
  POST /api/reset_decision
       → resets active in-session decision state back to pending
  GET  /api/audit_log
       → returns persistent audit history
"""

import sys, io, json, os, traceback
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# pyrefly: ignore [missing-import]
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import pandas as pd
# pyrefly: ignore [missing-import]
import numpy as np

print("[TwinPilot API] Initializing Intelligence Subsystems & Pre-trained Models...")
from run_scenario_pipeline import TwinPilotPipeline
from outcome_learning import record_intervention_outcome

DATASET_DIR = r"twinpilot_dataset_extracted\twinpilot_dataset"
pipeline = TwinPilotPipeline(DATASET_DIR)
sensor_df = pipeline.defect_service.sensor_df_with_preds.copy()
stations_master = pd.read_csv(f"{DATASET_DIR}/stations_master.csv")
print("[TwinPilot API] Ready — Serving on http://localhost:5000\n")

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

_serialized_cache = {}
_session_decisions = {}


def _safe(v):
    import math
    if isinstance(v, (np.integer, int)): return int(v)
    if isinstance(v, (np.floating, float)): return None if math.isnan(float(v)) else float(v)
    if isinstance(v, np.ndarray): return v.tolist()
    if isinstance(v, float) and math.isnan(v): return None
    return v


def _serialize(obj):
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict(orient="records")
    return _safe(obj)


def format_sim_clock(minute_index):
    # Base shift start: 08:00 AM
    total_minutes = 8 * 60 + int(minute_index)
    hours = (total_minutes // 60) % 24
    mins = total_minutes % 60
    am_pm = "AM" if hours < 12 else "PM"
    display_hour = hours if hours <= 12 else hours - 12
    if display_hour == 0: display_hour = 12
    return f"{display_hour:02d}:{mins:02d}:00 {am_pm}"


def get_approval_state(run_id, minute, event_id):
    """Return in-session operator decision state (resets cleanly on demand)."""
    key = f"{run_id}_{event_id or ''}"
    if key in _session_decisions:
        return _session_decisions[key]
    key_run = f"{run_id}_"
    if key_run in _session_decisions:
        return _session_decisions[key_run]
    return {"status": "pending", "record": None}


def build_factory_state(run_id, minute, station=None, event_id=None):
    # 1. Telemetry snapshot for all 31 stations at this exact minute
    snap = pipeline.defect_service.sensor_df_with_preds[
        (pipeline.defect_service.sensor_df_with_preds["run_id"] == run_id) &
        (pipeline.defect_service.sensor_df_with_preds["minute_index"] == minute)
    ].copy()

    bn_snap = pipeline.bn_sensor_df[
        (pipeline.bn_sensor_df["run_id"] == run_id) &
        (pipeline.bn_sensor_df["minute_index"] == minute)
    ].copy()

    merged_snap = pd.merge(snap, bn_snap[["station_id", "bottleneck_prob"]], on="station_id", how="left")
    snap_dict = {row["station_id"]: row for _, row in merged_snap.iterrows()}

    # Auto-detect target station if not supplied
    if not station:
        if not merged_snap.empty:
            top_defect = merged_snap.sort_values(by="defect_prob", ascending=False).iloc[0]
            if float(top_defect.get("defect_prob", 0)) >= 0.15:
                station = top_defect["station_id"]
            else:
                top_ct = merged_snap.sort_values(by="cycle_time_sec", ascending=False).iloc[0]
                station = top_ct["station_id"]
        else:
            station = "S03" if run_id == "RUN-024" else "S16"

    cache_key = f"{run_id}_{minute}_{station}_{event_id}"
    if cache_key in _serialized_cache:
        cached = dict(_serialized_cache[cache_key])
        cached["approval_state"] = get_approval_state(run_id, minute, event_id)
        return cached

    # Run core pipeline
    result = pipeline.run_scenario(
        run_id=run_id,
        minute_index=minute,
        target_station=station,
        event_id=event_id,
    )

    path_set = set(result["propagation_path"] or [])
    path_scores = {k: round(float(v)*100, 1) for k, v in result["path_scores"].items()}

    # 2. Build 31-Station Data Strip (30 Mainline + 1 Feeder)
    stations_list = []
    station_name_map = {}
    for _, st_row in stations_master.sort_values(by="sequence_order").iterrows():
        sid = st_row["station_id"]
        sname = st_row["station_name"]
        station_name_map[sid] = sname
        phase = st_row["phase"]
        tier = st_row["sensor_tier"]  # "rich", "partial", "manual"
        base_ct = float(st_row["baseline_cycle_time_sec"])
        is_feeder = (sid == "ENG01")
        is_manual = (tier.lower() == "manual")
        
        live_data = snap_dict.get(sid, None)
        if live_data is not None:
            curr_ct = float(live_data.get("cycle_time_sec", base_ct) or base_ct)
            curr_q = int(live_data.get("queue_length", 0) or 0)
            d_prob = round(float(live_data.get("defect_prob", 0.0) or 0.0) * 100, 1)
            bn_prob = round(float(live_data.get("bottleneck_prob", 0.0) or 0.0) * 100, 1)
            vib = float(live_data.get("vibration_mm_s", 0.0) or 0.0)
            torq = float(live_data.get("torque_nm", 0.0) or 0.0)
            temp = float(live_data.get("temperature_c", 0.0) or 0.0)
        else:
            curr_ct = base_ct
            curr_q = 0
            d_prob = 0.0
            bn_prob = 0.0
            vib = 0.0
            torq = 0.0
            temp = 0.0

        if sid == station:
            status = "critical"
        elif sid in path_set or d_prob >= 15.0 or bn_prob >= 20.0 or curr_q >= 6:
            status = "warning"
        elif is_manual:
            status = "manual"
        else:
            status = "healthy"

        stations_list.append({
            "station_id": sid,
            "station_name": sname,
            "phase": phase,
            "sequence_order": int(st_row["sequence_order"]),
            "is_feeder": is_feeder,
            "sensor_tier": "FEEDER (RICH)" if is_feeder else tier.upper(),
            "sensors_available": str(st_row.get("sensors_available", "") or "none"),
            "baseline_cycle_time_sec": round(base_ct, 1),
            "cycle_time_sec": round(curr_ct, 1),
            "queue_length": curr_q,
            "vibration_mm_s": round(vib, 2),
            "torque_nm": round(torq, 1),
            "temperature_c": round(temp, 1),
            "defect_prob_pct": d_prob,
            "bottleneck_prob_pct": bn_prob,
            "is_manual": is_manual,
            "status": status,
            "path_score_pct": path_scores.get(sid, 0.0)
        })

    # 3. Dynamic Dark Zone Assessment (All 6 Manual Stations)
    manual_stations = stations_master[stations_master["sensor_tier"] == "manual"]
    dark_zones = []
    
    dz_snap = pipeline.dz_dataset[
        (pipeline.dz_dataset["run_id"] == run_id) &
        (pipeline.dz_dataset["minute_index"] == minute)
    ]
    dz_prob_map = {}
    if not dz_snap.empty:
        preds = pipeline.dz_model.predict_proba(dz_snap[pipeline.dz_feature_cols])[:, 1]
        for target_st, prob in zip(dz_snap["target_station"], preds):
            dz_prob_map[target_st] = round(float(prob) * 100, 1)

    for _, mst in manual_stations.iterrows():
        sid = mst["station_id"]
        sname = mst["station_name"]
        deg_prob = dz_prob_map.get(sid, 1.5)
        is_deg = deg_prob >= 25.0
        
        dark_zones.append({
            "station_id": sid,
            "station_name": sname,
            "phase": mst["phase"],
            "sensor_tier": "MANUAL",
            "is_degrading": is_deg,
            "degradation_prob_pct": deg_prob,
            "status": "degrading" if is_deg else "nominal",
            "basis": "Upstream cycle timing jitter + downstream buffer queues."
        })

    # 4. Target Station & Risk State Gating
    target_info = next((s for s in stations_list if s["station_id"] == station), stations_list[0])
    ct_drift_pct = round(((target_info["cycle_time_sec"] - target_info["baseline_cycle_time_sec"]) / target_info["baseline_cycle_time_sec"]) * 100, 1)

    d_prob = target_info["defect_prob_pct"]
    bn_prob = target_info["bottleneck_prob_pct"]
    
    # State-Dependent Anomaly Gating:
    # An anomaly alert is only elevated when supported by actual signal deviation
    is_anomaly_active = (d_prob >= 15.0 or bn_prob >= 15.0 or abs(ct_drift_pct) >= 10.0 or target_info["queue_length"] >= 4)

    if d_prob >= 20.0 and bn_prob < 15.0:
        primary_risk_type = "defect_surge"
        alert_title = f"Defect Surge Alert — Station {station} ({target_info['station_name']})"
        alert_msg = f"Station {station} exhibits high tool drift with <strong>{d_prob}% defect propagation probability</strong>. <em>No significant bottleneck precursor detected (Bottleneck Risk: {bn_prob}%).</em>"
        est_downtime = 35
        conf_band = f"{d_prob}% - {min(100.0, d_prob + 16.5):.1f}%"
    elif bn_prob >= 20.0 and d_prob < 15.0:
        primary_risk_type = "bottleneck_congestion"
        alert_title = f"Bottleneck & Buffer Congestion — Station {station} ({target_info['station_name']})"
        alert_msg = f"Station {station} cycle time is {target_info['cycle_time_sec']}s (baseline {target_info['baseline_cycle_time_sec']}s) with queue {target_info['queue_length']}. <strong>Bottleneck precursor risk: {bn_prob}%</strong>. Defect risk is nominal ({d_prob}%)."
        est_downtime = 45
        conf_band = f"{bn_prob}% - {min(100.0, bn_prob + 15.0):.1f}%"
    elif d_prob >= 20.0 and bn_prob >= 20.0:
        primary_risk_type = "compound_anomaly"
        alert_title = f"Compound Defect & Bottleneck Anomaly — Station {station} ({target_info['station_name']})"
        alert_msg = f"Station {station} experiencing both tool drift ({d_prob}% defect risk) and buffer congestion ({bn_prob}% bottleneck risk) at {target_info['cycle_time_sec']}s cycle time."
        est_downtime = 50
        conf_band = f"{max(d_prob, bn_prob)}% - {min(100.0, max(d_prob, bn_prob) + 15.0):.1f}%"
    elif is_anomaly_active:
        primary_risk_type = "mechanical_delay"
        alert_title = f"Mechanical Delay & Buffer Backlog — Station {station} ({target_info['station_name']})"
        alert_msg = f"Station {station} cycle time rose to <strong>{target_info['cycle_time_sec']}s</strong> (baseline {target_info['baseline_cycle_time_sec']}s) with <strong>{target_info['queue_length']} queued units</strong>. <em>No significant bottleneck precursor or defect surge detected ({d_prob}% defect risk). Speed override / rebalance recommended.</em>"
        est_downtime = 25
        conf_band = "50.0% - 68.0%"
    else:
        primary_risk_type = "nominal"
        alert_title = f"All 31 Stations Nominal — Continuous Monitoring Active"
        alert_msg = f"Line pacing is within nominal baseline tolerance. All 30 mainline stations and ENG01 feeder operating normally. Counterfactual simulator standing by in monitoring mode."
        est_downtime = 0
        conf_band = "0.0% - 5.0%"

    prediction_factors = [
        {
            "name": "Cycle Time Drift",
            "delta_str": f"{'↑' if ct_drift_pct >= 0 else '↓'} {abs(ct_drift_pct)}%",
            "type": "warning" if abs(ct_drift_pct) > 10 else "normal",
            "raw_val": f"{target_info['cycle_time_sec']}s (base: {target_info['baseline_cycle_time_sec']}s)"
        },
        {
            "name": "Queue Backlog",
            "delta_str": f"↑ {target_info['queue_length']} units",
            "type": "warning" if target_info["queue_length"] >= 4 else "normal",
            "raw_val": f"{target_info['queue_length']} vehicles"
        },
        {
            "name": "Tool Vibration / Stress",
            "delta_str": f"↑ {target_info['vibration_mm_s']:.2f} mm/s",
            "type": "critical" if target_info["vibration_mm_s"] >= 2.5 else "normal",
            "raw_val": f"{target_info['vibration_mm_s']:.2f} mm/s"
        },
        {
            "name": "Dominant Model Signal",
            "delta_str": f"{max(d_prob, bn_prob):.1f}% ({primary_risk_type.replace('_', ' ').title()})",
            "type": "critical" if max(d_prob, bn_prob) >= 25 else ("warning" if max(d_prob, bn_prob) >= 10 else "normal"),
            "raw_val": f"{max(d_prob, bn_prob):.1f}%"
        }
    ]

    # 5. Propagation Causal Chain Detail
    prop_path_objs = []
    for sid in result["propagation_path"]:
        st_meta = next((s for s in stations_list if s["station_id"] == sid), None)
        s_name = st_meta["station_name"] if st_meta else sid
        r_score = path_scores.get(sid, 0.0)
        prop_path_objs.append({
            "station_id": sid,
            "station_name": s_name,
            "risk_pct": r_score,
            "role": "Origin" if sid == result["propagation_path"][0] else ("Terminal" if sid == result["propagation_path"][-1] else "Transfer")
        })

    # 6. Interventions Detail
    opts = result["options"]
    rec_opt = result["recommended_option"]
    interventions_payload = {}
    for opt_k, opt_v in opts.items():
        is_rec = (opt_k == rec_opt)
        if opt_k == "Option A":
            summary = "Rapid speed override clears buffer backlog immediately, but adds defect strain."
        elif opt_k == "Option B":
            summary = "Upstream throttle drastically suppresses defects, but sacrifices overall throughput."
        else:
            summary = "Dynamic workload reroute balances line pacing and avoids defect propagation."
        
        interventions_payload[opt_k] = {
            "name": opt_v["name"],
            "tput_pct": round(float(opt_v["tput_pct"]), 1),
            "queue_change": round(float(opt_v["queue_change"]), 1),
            "defect_risk_change": round(float(opt_v["defect_risk_change"]), 1),
            "financial_impact": round(float(opt_v["financial_impact"]), 0),
            "utility": round(float(opt_v["utility"]), 2),
            "is_recommended": is_rec,
            "impact_summary": summary
        }

    # 7. Line Health & Output
    avg_ct = np.mean([s["cycle_time_sec"] for s in stations_list if s["cycle_time_sec"] > 0])
    uph_actual = round(3600.0 / avg_ct, 1) if avg_ct > 0 else 75.0
    health_score = max(50.0, round(100.0 - (d_prob * 0.4 + target_info["queue_length"] * 2.0), 1))

    rc_id = result["root_cause"]
    rc_name = station_name_map.get(rc_id, rc_id)

    # 8. Complete 6-Phase Twin Evolution Timeline
    #   1. Baseline → 2. Emerging Signal → 3. Rising Risk →
    #   4. Current Prediction (NOW) → 5. Natural Future (Do Nothing) →
    #   6. A/B/C Counterfactual Intervention Projections
    ref_min = 143 if run_id == "RUN-024" else 93
    m_base = max(0, ref_min - 20)
    m_emerge = max(0, ref_min - 10)
    m_rising = max(0, ref_min - 4)
    m_now = ref_min
    m_future = min(239, ref_min + 15)

    base_snap = pipeline.defect_service.sensor_df_with_preds[
        (pipeline.defect_service.sensor_df_with_preds["run_id"] == run_id) &
        (pipeline.defect_service.sensor_df_with_preds["minute_index"] == m_base) &
        (pipeline.defect_service.sensor_df_with_preds["station_id"] == station)
    ]
    base_ct = round(float(base_snap.iloc[0]["cycle_time_sec"]), 1) if not base_snap.empty else target_info["baseline_cycle_time_sec"]
    base_q = int(base_snap.iloc[0]["queue_length"]) if not base_snap.empty else 0

    emerge_snap = pipeline.defect_service.sensor_df_with_preds[
        (pipeline.defect_service.sensor_df_with_preds["run_id"] == run_id) &
        (pipeline.defect_service.sensor_df_with_preds["minute_index"] == m_emerge) &
        (pipeline.defect_service.sensor_df_with_preds["station_id"] == station)
    ]
    emerge_ct = round(float(emerge_snap.iloc[0]["cycle_time_sec"]), 1) if not emerge_snap.empty else base_ct
    emerge_q = int(emerge_snap.iloc[0]["queue_length"]) if not emerge_snap.empty else 2
    emerge_vib = round(float(emerge_snap.iloc[0].get("vibration_mm_s", 0.8) or 0.8), 2) if not emerge_snap.empty else 0.8
    emerge_drift = round(((emerge_ct - target_info["baseline_cycle_time_sec"]) / target_info["baseline_cycle_time_sec"]) * 100, 1)

    rising_snap = pipeline.defect_service.sensor_df_with_preds[
        (pipeline.defect_service.sensor_df_with_preds["run_id"] == run_id) &
        (pipeline.defect_service.sensor_df_with_preds["minute_index"] == m_rising) &
        (pipeline.defect_service.sensor_df_with_preds["station_id"] == station)
    ]
    rising_ct = round(float(rising_snap.iloc[0]["cycle_time_sec"]), 1) if not rising_snap.empty else target_info["cycle_time_sec"]
    rising_q = int(rising_snap.iloc[0]["queue_length"]) if not rising_snap.empty else target_info["queue_length"]
    rising_d = round(float(rising_snap.iloc[0].get("defect_prob", 0.0) or 0.0) * 100, 1) if not rising_snap.empty else d_prob

    now_snap = pipeline.defect_service.sensor_df_with_preds[
        (pipeline.defect_service.sensor_df_with_preds["run_id"] == run_id) &
        (pipeline.defect_service.sensor_df_with_preds["minute_index"] == m_now) &
        (pipeline.defect_service.sensor_df_with_preds["station_id"] == station)
    ]
    now_ct = round(float(now_snap.iloc[0]["cycle_time_sec"]), 1) if not now_snap.empty else target_info["cycle_time_sec"]
    now_q = int(now_snap.iloc[0]["queue_length"]) if not now_snap.empty else target_info["queue_length"]
    now_d = round(float(now_snap.iloc[0].get("defect_prob", 0.0) or 0.0) * 100, 1) if not now_snap.empty else d_prob

    twin_timeline = [
        {
            "step_id": 0,
            "phase_name": "1. Baseline",
            "stage_title": "Historical Baseline",
            "category_badge": "OBSERVED TELEMETRY",
            "category_type": "observed",
            "minute": m_base,
            "sim_clock": format_sim_clock(m_base),
            "status": "Nominal Pacing",
            "telemetry_highlight": f"CT: {base_ct}s | Queue: {base_q} | Defect Risk: 0.0%",
            "summary": f"Station {station} observed within baseline tolerance ({base_ct}s cycle time, buffer queue {base_q}). Line operating smoothly."
        },
        {
            "step_id": 1,
            "phase_name": "2. Emerging Signal",
            "stage_title": "Emerging Micro-Variance",
            "category_badge": "OBSERVED TELEMETRY",
            "category_type": "observed",
            "minute": m_emerge,
            "sim_clock": format_sim_clock(m_emerge),
            "status": "Early Variance",
            "telemetry_highlight": f"Vibration: {emerge_vib} mm/s | CT Drift: {emerge_drift:+0.1f}% | Queue: {emerge_q}",
            "summary": f"Earliest upstream telemetry variance detected. Cycle times beginning subtle drift ({emerge_drift:+0.1f}%) while line remains operational."
        },
        {
            "step_id": 2,
            "phase_name": "3. Rising Risk",
            "stage_title": "Risk Precursor Triggered",
            "category_badge": "OBSERVED TELEMETRY + TRIGGER",
            "category_type": "observed",
            "minute": m_rising,
            "sim_clock": format_sim_clock(m_rising),
            "status": "Threshold Breached",
            "telemetry_highlight": f"Model Trigger: {rising_d:.1f}% Risk | CT: {rising_ct}s | Queue: {rising_q}",
            "summary": f"Predictive model threshold breached (Risk: {rising_d:.1f}%). Graph traversal identifies downstream propagation path through active stations."
        },
        {
            "step_id": 3,
            "phase_name": "4. Current Prediction (NOW)",
            "stage_title": "Active State & Prediction",
            "category_badge": "LIVE PREDICTION",
            "category_type": "prediction",
            "minute": m_now,
            "sim_clock": format_sim_clock(m_now),
            "status": "Active Monitored State",
            "telemetry_highlight": f"CT: {now_ct}s | Risk: {max(now_d, bn_prob):.1f}% | Quarantined VINs: {result['at_risk_vins_count']}",
            "summary": f"Station {station} ({target_info['station_name']}) at {now_ct}s CT, queue {now_q}. Likely Root-Cause Candidate: Station {rc_id} ({rc_name})."
        },
        {
            "step_id": 4,
            "phase_name": "5. Natural Future (Do Nothing)",
            "stage_title": "Unmitigated Line Progression",
            "category_badge": "NATURAL PROJECTION (DO NOTHING)",
            "category_type": "natural_future",
            "minute": m_future,
            "sim_clock": format_sim_clock(m_future),
            "status": "Severe Disruption Projected",
            "telemetry_highlight": f"Projected Tput: -18.5% | Queue Buildup: +{target_info['queue_length'] + 6} units | Scrap Loss: -$3,200+",
            "summary": f"If no action is taken, buffer backlog surges by +{target_info['queue_length'] + 6} vehicles, cascading line starvation into downstream Final Assembly and inflicting quality defect penalties."
        },
        {
            "step_id": 5,
            "phase_name": "6. A/B/C Counterfactual Interventions",
            "stage_title": "Intervention Optimization",
            "category_badge": "INTERVENTION PROJECTION",
            "category_type": "intervention_projection",
            "minute": m_future,
            "sim_clock": format_sim_clock(m_future),
            "status": f"AI Recommended: {rec_opt}",
            "telemetry_highlight": f"Recommended: {rec_opt} | Projected Tput: {opts[rec_opt]['tput_pct']:+.1f}% | Net Value: +${opts[rec_opt]['financial_impact']:+.0f}",
            "summary": f"Constraint-aware simulator recommends {rec_opt} ({opts[rec_opt]['name']}), delivering {opts[rec_opt]['tput_pct']:+.1f}% throughput gain and clearing queue by {abs(opts[rec_opt]['queue_change']):.1f} units."
        }
    ]

    # Recommendation Rationale
    if is_anomaly_active:
        rec_rationale = f"Recommended: {rec_opt} ({opts[rec_opt]['name']}), because it delivers {opts[rec_opt]['tput_pct']:+.1f}% throughput gain, drains queue by {abs(opts[rec_opt]['queue_change']):.1f} units with net economic benefit of ${opts[rec_opt]['financial_impact']:+.0f}."
    else:
        rec_rationale = "System Nominal — All stations within tolerance. Counterfactual simulator standing by."

    factory_state = {
        "run_id": run_id,
        "minute": minute,
        "sim_clock": format_sim_clock(minute),
        "event_id": event_id or f"{run_id}-M{minute}",
        "is_anomaly_active": is_anomaly_active,
        "target_station": target_info,
        "overall_metrics": {
            "overall_health_pct": health_score,
            "line_throughput_uph": uph_actual,
            "sim_clock": format_sim_clock(minute),
            "total_stations": len(stations_list),
            "total_at_risk_vins": int(result["at_risk_vins_count"]) if is_anomaly_active else 0
        },
        "anomaly_prediction": {
            "is_anomaly_active": is_anomaly_active,
            "primary_risk_type": primary_risk_type,
            "alert_title": alert_title,
            "alert_message": alert_msg,
            "defect_prob_pct": d_prob,
            "bottleneck_prob_pct": bn_prob,
            "computed_prob_str": f"{max(d_prob, bn_prob):.1f}%",
            "eta_minutes": 15 if is_anomaly_active else 0,
            "confidence_band": conf_band,
            "est_downtime_mins": est_downtime,
            "prediction_factors": prediction_factors
        },
        "stations": stations_list,
        "dark_zones": dark_zones,
        "root_cause": {
            "candidate_id": rc_id,
            "candidate_name": rc_name,
            "label": f"Likely Root-Cause Candidate: Station {rc_id} ({rc_name})",
            "station_id": rc_id,
            "station_name": rc_name,
            "evidence": f"Inferred via 3-Factor Root Cause scoring: earliest signal divergence (Min {max(0, minute-10)}), high signal magnitude, and upstream graph reachability."
        },
        "propagation": {
            "origin_station": result["propagation_path"][0] if result["propagation_path"] else station,
            "path": result["propagation_path"] if is_anomaly_active else [station],
            "path_stations": prop_path_objs if is_anomaly_active else [],
            "path_scores": path_scores if is_anomaly_active else {},
            "earliest_cause": f"Likely Root-Cause Candidate: Station {rc_id} ({rc_name})" if is_anomaly_active else "Nominal Line Pacing",
            "predicted_defect": f"Tool Defect & Structural Strain ({d_prob}% Risk)" if is_anomaly_active else "Nominal (Zero Detected Defect)",
            "recommended_action": f"{rec_opt} — {opts[rec_opt]['name']} ({opts[rec_opt]['tput_pct']:+.1f}% Tput, {opts[rec_opt]['defect_risk_change']:+.1f}% Defect)" if is_anomaly_active else "Standby Mode"
        },
        "at_risk_vehicles": {
            "total_count": int(result["at_risk_vins_count"]) if is_anomaly_active else 0,
            "sample_vins": result["sample_vins"] if is_anomaly_active else [],
            "quarantine_location": f"Buffer line prior to Station {result['propagation_path'][-1] if result['propagation_path'] else station}" if is_anomaly_active else "Line Nominal"
        },
        "interventions": interventions_payload,
        "recommendation": {
            "option_key": rec_opt,
            "option_name": opts[rec_opt]["name"],
            "confidence_pct": float(result["confidence"]),
            "rationale": rec_rationale
        },
        "twin_timeline": twin_timeline,
        "timeline_steps": twin_timeline[:3],
        "approval_state": get_approval_state(run_id, minute, event_id)
    }

    serialized = _serialize(factory_state)
    _serialized_cache[cache_key] = serialized
    return serialized


@app.route("/")
def index():
    return send_from_directory(".", "dashboard.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(".", path)


@app.route("/api/scenario")
def api_scenario():
    run_id   = request.args.get("run_id",   "RUN-024")
    minute   = int(request.args.get("minute",  "143"))
    station  = request.args.get("station",  None)
    event_id = request.args.get("event_id", None)

    try:
        factory_state = build_factory_state(run_id, minute, station=station, event_id=event_id)
        return jsonify(factory_state)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/approve", methods=["POST"])
def api_approve():
    body = request.get_json(force=True)
    run_id = body.get("run_id", "RUN-024")
    minute = int(body.get("minute", 143))
    station = body.get("station", "S03")
    event_id = body.get("event_id", None)
    operator_action = body.get("operator_action", "approve")

    try:
        result = pipeline.run_scenario(
            run_id=run_id,
            minute_index=minute,
            target_station=station,
            event_id=event_id,
        )
        record = record_intervention_outcome(
            result,
            operator_action=operator_action,
            sensor_df=sensor_df,
            observation_window=20,
        )
        serialized_rec = _serialize(record)
        
        # Save to in-session decisions
        key = f"{run_id}_{event_id or ''}"
        _session_decisions[key] = {
            "status": operator_action,
            "record": serialized_rec
        }
        
        return jsonify(serialized_rec)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/reset_decision", methods=["POST"])
def api_reset_decision():
    body = request.get_json(force=True) if request.data else {}
    run_id = body.get("run_id", None)
    event_id = body.get("event_id", None)
    if run_id and event_id:
        _session_decisions.pop(f"{run_id}_{event_id}", None)
    elif run_id:
        to_del = [k for k in _session_decisions if k.startswith(run_id)]
        for k in to_del: _session_decisions.pop(k, None)
    else:
        _session_decisions.clear()
    return jsonify({"status": "pending", "message": "In-session decision state reset to pending."})


@app.route("/api/audit_log")
def api_audit_log():
    log_path = "intervention_audit_log.json"
    if not os.path.exists(log_path):
        return jsonify([])
    with open(log_path) as f:
        return jsonify(json.load(f))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
