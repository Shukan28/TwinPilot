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

    target_sid = target_station if target_station else stations_list[min(len(stations_list) - 1, 2)]["station_id"]
    target_info = next((s for s in stations_list if s["station_id"] == target_sid), stations_list[0])

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
    return {
        "factory_id": factory_id,
        "factory_name": fact["name"],
        "is_custom_factory": True,
        "minute": minute,
        "target_station": target_sid,
        "step_id": step_id,
        "stations": station_telemetry_list,
        "dark_zones": dark_zones,
        "interventions": options,
        "recommendation": {
            "option_key": rec_key,
            "rationale": f"Adaptive pipeline recommendation for {fact['name']} at station {target_sid}."
        },
        "propagation": {
            "earliest_cause": f"Station {target_sid} ({target_info['station_name']})",
            "predicted_defect": f"Cycle Time Jitter & Queue Backlog ({station_telemetry_list[0]['defect_risk_pct']}%)",
            "recommended_action": f"{rec_key} — {options[rec_key]['name']} (+{options[rec_key]['tput_pct']}% Tput)",
            "path_stations": [s["station_id"] for s in stations_list[:min(len(stations_list), 6)]]
        },
        "at_risk_vehicles": {
            "total_count": 8 if step_id in (3, 4) else 0,
            "sample_vins": [f"VIN-{fact['slug'][:3].upper()}-{1000+i}" for i in range(5)],
            "quarantine_label": f"8 vehicles staged at {fact['name']} quality gate" if step_id in (3, 4) else "All vehicles cleared for release"
        }
    }
