"""
TwinPilot Multi-Tenant Factory Pipeline Router
=============================================
Dispatches Digital Twin state queries to:
1. Default Demo Factory ('demo-detroit-31'): Existing 31-station automotive pipeline (completely preserved).
2. Custom Onboarded Factories: Dynamic SQLite-backed topology, custom stations, and dynamic telemetry.
"""

import os
import json
import sqlite3
import pandas as pd
# pyrefly: ignore [missing-import]
import numpy as np
from database import get_db_connection

DEFAULT_DEMO_FACTORY_ID = "demo-detroit-31"


def get_factory_metadata(factory_id: str):
    """Fetches factory record and station count from SQLite."""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    SELECT f.*, c.name as company_name
    FROM factories f
    JOIN companies c ON f.company_id = c.id
    WHERE f.id = ?
    """, (factory_id,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return None

    cur.execute("SELECT COUNT(*) FROM factory_stations WHERE factory_id = ?", (factory_id,))
    st_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM factory_dependencies WHERE factory_id = ?", (factory_id,))
    dep_count = cur.fetchone()[0]

    conn.close()

    res = dict(row)
    res["station_count"] = st_count
    res["dependency_count"] = dep_count
    res["is_demo"] = bool(row["is_demo"])
    return res


def get_factory_stations_list(factory_id: str):
    """Returns list of stations for a given factory from database."""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    SELECT station_id, station_name, line_phase, baseline_cycle_time_sec, sensor_tier, station_order
    FROM factory_stations
    WHERE factory_id = ?
    ORDER BY station_order ASC
    """, (factory_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def build_custom_factory_state(factory_id: str, minute: int = 100, target_station: str = None, step_id: int = 0):
    """
    Builds dynamic Digital Twin state for a custom onboarded factory using its database stations.
    """
    fact = get_factory_metadata(factory_id)
    if not fact:
        return None

    stations_list = get_factory_stations_list(factory_id)
    if not stations_list:
        return None

    if not target_station:
        if factory_id == "factory-fremont-61":
            target_sid = "BAT05"
        else:
            target_sid = stations_list[min(len(stations_list) - 1, 2)]["station_id"]
    else:
        target_sid = target_station

    target_info = next((s for s in stations_list if s["station_id"] == target_sid), stations_list[0])

    # Fetch DAG dependencies for realistic propagation path
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT upstream_station_id, downstream_station_id FROM factory_dependencies WHERE factory_id = ?", (factory_id,))
    dep_rows = cur.fetchall()
    conn.close()

    adj_downstream = {}
    for r in dep_rows:
        u, d = r["upstream_station_id"], r["downstream_station_id"]
        adj_downstream.setdefault(u, []).append(d)

    # Breadth/depth traverse downstream from target_sid up to 6 stations
    path_stations = [target_sid]
    curr = target_sid
    visited = {target_sid}
    while len(path_stations) < 6:
        next_nodes = [n for n in adj_downstream.get(curr, []) if n not in visited]
        if not next_nodes:
            break
        curr = next_nodes[0]
        path_stations.append(curr)
        visited.add(curr)

    # Fallback if topology is linear or disconnected
    if len(path_stations) < 3:
        st_ids = [s["station_id"] for s in stations_list]
        if target_sid in st_ids:
            idx = st_ids.index(target_sid)
            path_stations = st_ids[idx:min(len(st_ids), idx + 6)]
        else:
            path_stations = st_ids[:min(len(st_ids), 6)]

    # Dynamic status per station based on step_id
    station_telemetry_list = []
    dark_zones = []
    
    for idx, s in enumerate(stations_list):
        sid = s["station_id"]
        base_ct = float(s["baseline_cycle_time_sec"])
        tier = s["sensor_tier"]

        is_target = (sid == target_sid)
        if is_target and step_id >= 2:
            ct_val = round(base_ct + (8.5 if step_id >= 3 else 3.2), 1)
            q_val = (4 if step_id == 2 else (9 if step_id in (3, 4) else 1))
            vib_val = round(0.85 + (0.95 if step_id >= 3 else 0.40), 2)
            d_prob = (0.28 if step_id >= 3 else 0.08)
            status_str = "critical" if step_id in (3, 4) else "warning"
        else:
            ct_val = base_ct
            q_val = 0
            vib_val = 0.80
            d_prob = 0.015
            status_str = "nominal"

        st_obj = {
            "station_id": sid,
            "station_name": s["station_name"],
            "line_phase": s.get("line_phase", "Assembly"),
            "cycle_time_sec": ct_val,
            "baseline_cycle_time_sec": base_ct,
            "queue_length": q_val,
            "vibration": vib_val,
            "temperature": 42.0,
            "defect_risk_pct": round(d_prob * 100.0, 1),
            "defect_prob_pct": round(d_prob * 100.0, 1),
            "bottleneck_prob_pct": 2.0 if not is_target else (42.0 if step_id >= 3 else 12.0),
            "status": status_str,
            "sensor_tier": tier
        }
        station_telemetry_list.append(st_obj)

        if tier.upper() == "MANUAL":
            dark_zones.append({
                "station_id": sid,
                "station_name": s["station_name"],
                "is_degrading": (is_target and step_id >= 2),
                "degradation_prob_pct": round(d_prob * 100.0, 1) if (is_target and step_id >= 2) else 1.5,
                "proxy_confidence": 88.5
            })

    # Interventions
    options = {
        "Option A": {
            "name": "Speed Override / Move Operator",
            "tput_pct": 14.5,
            "queue_change": -3.0,
            "defect_risk_change": +3.5,
            "financial_impact": 1200.0,
            "is_recommended": (step_id >= 2),
            "impact_summary": "Rapid speed override balances queue buildup."
        },
        "Option B": {
            "name": "Buffer / Throttle Upstream",
            "tput_pct": -9.0,
            "queue_change": +2.0,
            "defect_risk_change": -12.0,
            "financial_impact": -650.0,
            "is_recommended": False,
            "impact_summary": "Throttles upstream pacing to suppress defects."
        },
        "Option C": {
            "name": "Workload Rebalance / Reroute",
            "tput_pct": 7.5,
            "queue_change": -2.0,
            "defect_risk_change": -4.0,
            "financial_impact": 850.0,
            "is_recommended": False,
            "impact_summary": "Dynamic workload rebalance across manual lines."
        }
    }

    rec_key = "Option A"
    
    # Target station object
    target_obj = {
        "station_id": target_sid,
        "station_name": target_info["station_name"],
        "line_phase": target_info.get("line_phase", "Assembly"),
        "sensor_tier": target_info["sensor_tier"],
        "baseline_cycle_time_sec": float(target_info.get("baseline_cycle_time_sec", 45.0)),
        "cycle_time_sec": round(float(target_info.get("baseline_cycle_time_sec", 45.0)) + (8.5 if step_id >= 3 else (3.2 if step_id == 2 else 0.0)), 1),
        "queue_length": (9 if step_id >= 3 else (4 if step_id == 2 else 0)),
        "defect_prob_pct": (35.0 if step_id >= 3 else (10.0 if step_id == 2 else 1.5)),
        "bottleneck_prob_pct": (42.0 if step_id >= 3 else (12.0 if step_id == 2 else 2.0))
    }

    # Overall metrics
    health = 99.2 if step_id == 5 else (98.4 if step_id < 2 else (91.2 if step_id == 2 else 78.5))
    uph = 83.2 if step_id < 2 else (76.4 if step_id in (3, 4) else 82.8)
    overall_metrics = {
        "overall_health_pct": health,
        "line_throughput_uph": uph,
        "stations_monitored": len(stations_list),
        "active_anomalies_count": 1 if step_id >= 2 else 0,
        "sim_clock": f"10:{minute:02d}:00 AM" if minute < 60 else f"{10 + minute//60}:{minute%60:02d}:00 AM",
        "minute_index": minute
    }

    # Anomaly prediction
    anomaly_prediction = {
        "primary_risk_type": "defect" if step_id >= 2 else "nominal",
        "station_id": target_sid,
        "station_name": target_info["station_name"],
        "alert_title": f"Stage {step_id+1}/6: {'Predictive Variance Detected' if step_id >= 2 else 'Line Operating Within Nominal Baseline'}",
        "alert_message": f"Station {target_sid} ({target_info['station_name']}) {'exhibits cycle time micro-drift and buffer queue buildup.' if step_id >= 2 else 'operating with zero active queue accumulation.'}",
        "confidence_band": "94.2% (High Confidence)" if step_id >= 2 else "99.8% (Nominal)",
        "est_downtime_mins": 18 if step_id in (3, 4) else (6 if step_id == 2 else 0),
        "defect_prob_pct": 35.5 if step_id >= 3 else (12.0 if step_id == 2 else 1.5),
        "bottleneck_prob_pct": 42.0 if step_id >= 3 else (15.0 if step_id == 2 else 2.0),
        "prediction_factors": [
            {
                "name": f"Station {target_sid} Cycle Time Drift",
                "delta_str": f"+{8.5 if step_id >= 3 else 3.2}s" if step_id >= 2 else "Nominal",
                "type": "critical" if step_id >= 3 else ("warning" if step_id == 2 else "normal"),
                "raw_val": f"{target_info.get('baseline_cycle_time_sec', 45.0)}s baseline"
            },
            {
                "name": "Buffer Queue Backlog",
                "delta_str": f"{9 if step_id >= 3 else 4} units" if step_id >= 2 else "0 units",
                "type": "critical" if step_id >= 3 else ("warning" if step_id == 2 else "normal"),
                "raw_val": "Nominal: 0"
            },
            {
                "name": f"Dark Zone Sensorless Inference ({len(dark_zones)} unmonitored stations)",
                "delta_str": f"{len(dark_zones)} Proxies Calibrated",
                "type": "normal",
                "raw_val": "Isolation Forest Active"
            }
        ]
    }

    # Propagation
    propagation = {
        "path": path_stations,
        "path_stations": path_stations,
        "earliest_cause": f"Station {target_sid} ({target_info['station_name']})",
        "predicted_defect": f"Cycle Time Jitter & Queue Backlog ({35.5 if step_id >= 3 else 1.5}%)",
        "recommended_action": f"{rec_key} — {options[rec_key]['name']} (+{options[rec_key]['tput_pct']}% Tput)",
        "propagation_path": [
            {
                "station_id": sid,
                "station_name": next((s["station_name"] for s in stations_list if s["station_id"] == sid), sid),
                "risk_pct": 35.0 if sid == target_sid else 15.0,
                "role": "Origin" if sid == target_sid else "Transfer"
            }
            for sid in path_stations
        ]
    }

    # 6-step twin timeline
    twin_timeline = [
        {
            "step_id": 0,
            "phase_name": "1. Baseline",
            "stage_title": "Nominal Baseline",
            "category_badge": "OBSERVED TELEMETRY",
            "category_type": "observed",
            "minute": 10,
            "sim_clock": "10:10:00 AM",
            "status": "Nominal Pacing Active",
            "telemetry_highlight": f"All {len(stations_list)} Stations Nominal | Zero Active Queue",
            "summary": f"{fact['name']} operating at steady-state. Zero active queue accumulation."
        },
        {
            "step_id": 1,
            "phase_name": "2. Emerging Signal",
            "stage_title": "Emerging Jitter Signal",
            "category_badge": "OBSERVED TELEMETRY",
            "category_type": "observed",
            "minute": 15,
            "sim_clock": "10:15:00 AM",
            "status": "Emerging Micro-Jitter",
            "telemetry_highlight": f"Station {target_sid} variance: +3.2s | Vibration: 1.1 mm/s",
            "summary": f"Subtle pacing irregularity detected at Station {target_sid}."
        },
        {
            "step_id": 2,
            "phase_name": "3. Rising Risk",
            "stage_title": "Threshold Breached",
            "category_badge": "LIVE PREDICTION",
            "category_type": "live_prediction",
            "minute": 20,
            "sim_clock": "10:20:00 AM",
            "status": "Precursor Breached",
            "telemetry_highlight": f"Station {target_sid} queue accumulation: 4 vehicles | Defect Risk: 12%",
            "summary": f"Station {target_sid} threshold breach. Recommended {rec_key} primed."
        },
        {
            "step_id": 3,
            "phase_name": "4. Live Prediction",
            "stage_title": "Defect Surge Predicted",
            "category_badge": "LIVE PREDICTION",
            "category_type": "live_prediction",
            "minute": 25,
            "sim_clock": "10:25:00 AM",
            "status": "Bottleneck Critical",
            "telemetry_highlight": f"Station {target_sid} cycle time: +8.5s | Backlog: 9 vehicles | Defect Risk: 35.5%",
            "summary": f"Critical bottleneck at Station {target_sid} threatening downstream starvation."
        },
        {
            "step_id": 4,
            "phase_name": "5. Dynamic Future",
            "stage_title": "Mitigated / Counterfactual Outcome",
            "category_badge": "INTERVENTION EXECUTED",
            "category_type": "intervention_projection",
            "minute": 35,
            "sim_clock": "10:35:00 AM",
            "status": "Line Stabilized",
            "telemetry_highlight": f"Throughput gain: +{options[rec_key]['tput_pct']}% | Queue reduced: {options[rec_key]['queue_change']} units",
            "summary": f"Executing {rec_key} successfully relieves congestion at {fact['name']}."
        },
        {
            "step_id": 5,
            "phase_name": "6. Nominal Restored",
            "stage_title": "Full Nominal State Restored",
            "category_badge": "NOMINAL RESTORED",
            "category_type": "intervention_projection",
            "minute": 45,
            "sim_clock": "10:45:00 AM",
            "status": "Full Steady State",
            "telemetry_highlight": f"All {len(stations_list)} Stations Nominal | Cycle Time: 45.0s | Defect Risk: 0.0%",
            "summary": f"All {len(stations_list)} stations in {fact['name']} restored to full production capacity."
        }
    ]

    return {
        "factory_id": factory_id,
        "factory_name": fact["name"],
        "is_custom_factory": True,
        "minute": minute,
        "sim_clock": overall_metrics["sim_clock"],
        "target_station": target_obj,
        "step_id": step_id,
        "stations": station_telemetry_list,
        "dark_zones": dark_zones,
        "interventions": options,
        "overall_metrics": overall_metrics,
        "anomaly_prediction": anomaly_prediction,
        "propagation": propagation,
        "timeline_steps": twin_timeline,
        "approval_state": {
            "status": "pending",
            "record": None
        },
        "recommendation": {
            "option_key": rec_key,
            "rationale": f"Adaptive pipeline recommendation for {fact['name']} at station {target_sid}."
        },
        "at_risk_vehicles": {
            "total_count": 8 if step_id in (3, 4) else 0,
            "sample_vins": [f"VIN-{fact['slug'][:3].upper()}-{1000+i}" for i in range(5)],
            "quarantine_label": f"8 vehicles staged at {fact['name']} quality gate" if step_id in (3, 4) else "All vehicles cleared for release"
        }
    }
