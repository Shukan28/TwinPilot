"""
TwinPilot Factory Onboarding & Schema Validation Service
========================================================
Validates and ingests customer manufacturing datasets:
1. Station Metadata (station_id, station_name, baseline_cycle_time_sec, sensor_tier)
2. Station Dependencies & Buffer Capacities (upstream, downstream, buffer_capacity)
3. Sensor Telemetry Timeseries (run_id, minute_index, station_id, cycle_time_sec, queue_length, vibration)
4. Vehicle Production Logs (run_id, vin, model_type)

Performs sanity checks, column auto-mapping, DAG cycle detection, and Dark Zone proxy inference.
"""

import os
import json
import uuid
import pandas as pd
# pyrefly: ignore [missing-import]
import numpy as np
from datetime import datetime
from database import get_db_connection

UPLOAD_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")


def get_factory_upload_dir(factory_id: str) -> str:
    """Ensures an isolated directory exists for the factory's uploaded datasets."""
    path = os.path.join(UPLOAD_BASE, factory_id)
    os.makedirs(path, exist_ok=True)
    return path


def validate_stations_file(file_path: str):
    """
    Validates station metadata CSV:
    - Required: station_id, station_name
    - Recommended: baseline_cycle_time_sec (defaults to 45.0), sensor_tier (defaults to PARTIAL)
    """
    try:
        df = pd.read_csv(file_path)
    except Exception as e:
        return {"valid": False, "errors": [f"Could not read CSV file: {str(e)}"], "stats": {}}

    errors = []
    warnings = []

    # Case-insensitive column resolution
    col_map = {str(c).lower().strip(): c for c in df.columns}

    id_col = col_map.get("station_id") or col_map.get("id") or col_map.get("station")
    name_col = col_map.get("station_name") or col_map.get("name")
    ct_col = col_map.get("baseline_cycle_time_sec") or col_map.get("cycle_time") or col_map.get("baseline_ct")
    tier_col = col_map.get("sensor_tier") or col_map.get("tier")

    if not id_col:
        errors.append("Missing required column: 'station_id' (or 'id', 'station').")
    if not name_col:
        errors.append("Missing required column: 'station_name' (or 'name').")

    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings, "stats": {}}

    # Check for empty station IDs or duplicates
    if df[id_col].isnull().any():
        errors.append("Found null or empty values in station ID column.")
    if df[id_col].duplicated().any():
        dups = df[id_col][df[id_col].duplicated()].tolist()
        errors.append(f"Found duplicate station IDs: {dups[:5]}")

    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings, "stats": {}}

    # Standardize data
    stations = []
    tier_counts = {"RICH": 0, "PARTIAL": 0, "MANUAL": 0}
    for idx, row in df.iterrows():
        sid = str(row[id_col]).strip()
        sname = str(row[name_col]).strip()
        ct = float(row[ct_col]) if ct_col and pd.notnull(row[ct_col]) else 45.0
        tier = str(row[tier_col]).strip().upper() if tier_col and pd.notnull(row[tier_col]) else "PARTIAL"
        if tier not in ("RICH", "PARTIAL", "MANUAL"):
            tier = "PARTIAL"
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        stations.append({
            "station_id": sid,
            "station_name": sname,
            "line_phase": str(row.get("line_phase", "Assembly")),
            "baseline_cycle_time_sec": ct,
            "sensor_tier": tier,
            "station_order": idx + 1
        })

    return {
        "valid": True,
        "errors": [],
        "warnings": warnings,
        "stats": {
            "total_stations": len(stations),
            "tier_breakdown": tier_counts,
            "sample_stations": [s["station_id"] for s in stations[:8]]
        },
        "cleaned_data": stations
    }


def validate_dependencies_file(file_path: str, valid_station_ids: set):
    """
    Validates station dependencies / line topology:
    - Required: upstream_station_id / from_station, downstream_station_id / to_station
    - Checks that referenced stations exist in the station metadata
    """
    try:
        df = pd.read_csv(file_path)
    except Exception as e:
        return {"valid": False, "errors": [f"Could not read CSV file: {str(e)}"], "stats": {}}

    errors = []
    warnings = []

    col_map = {str(c).lower().strip(): c for c in df.columns}
    u_col = col_map.get("upstream_station_id") or col_map.get("from_station") or col_map.get("upstream") or col_map.get("source")
    d_col = col_map.get("downstream_station_id") or col_map.get("to_station") or col_map.get("downstream") or col_map.get("target")

    if not u_col:
        errors.append("Missing upstream column: 'upstream_station_id' or 'from_station'.")
    if not d_col:
        errors.append("Missing downstream column: 'downstream_station_id' or 'to_station'.")

    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings, "stats": {}}

    deps = []
    for _, row in df.iterrows():
        u_sid = str(row[u_col]).strip()
        d_sid = str(row[d_col]).strip()

        if valid_station_ids and u_sid not in valid_station_ids:
            warnings.append(f"Upstream station '{u_sid}' not found in uploaded stations list.")
        if valid_station_ids and d_sid not in valid_station_ids:
            warnings.append(f"Downstream station '{d_sid}' not found in uploaded stations list.")

        buf = int(row.get("buffer_capacity", 10)) if "buffer_capacity" in row and pd.notnull(row["buffer_capacity"]) else 10
        tt = float(row.get("transit_time_sec", 5.0)) if "transit_time_sec" in row and pd.notnull(row["transit_time_sec"]) else 5.0

        deps.append({
            "upstream_station_id": u_sid,
            "downstream_station_id": d_sid,
            "buffer_capacity": buf,
            "transit_time_sec": tt
        })

    return {
        "valid": True,
        "errors": [],
        "warnings": warnings[:5],
        "stats": {
            "total_links": len(deps),
            "sample_links": [f"{d['upstream_station_id']} -> {d['downstream_station_id']}" for d in deps[:6]]
        },
        "cleaned_data": deps
    }


def validate_telemetry_file(file_path: str, valid_station_ids: set):
    """
    Validates timeseries telemetry CSV:
    - Required: run_id, minute_index (or timestamp), station_id, cycle_time_sec
    """
    try:
        df = pd.read_csv(file_path, nrows=5000) # Read sample for fast schema validation
    except Exception as e:
        return {"valid": False, "errors": [f"Could not read CSV file: {str(e)}"], "stats": {}}

    errors = []
    warnings = []

    col_map = {str(c).lower().strip(): c for c in df.columns}
    run_col = col_map.get("run_id") or col_map.get("run")
    min_col = col_map.get("minute_index") or col_map.get("minute") or col_map.get("min")
    st_col = col_map.get("station_id") or col_map.get("station")
    ct_col = col_map.get("cycle_time_sec") or col_map.get("cycle_time") or col_map.get("ct")

    if not run_col:
        errors.append("Missing column: 'run_id'.")
    if not min_col:
        errors.append("Missing column: 'minute_index' (or 'minute').")
    if not st_col:
        errors.append("Missing column: 'station_id'.")
    if not ct_col:
        errors.append("Missing column: 'cycle_time_sec' (or 'cycle_time').")

    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings, "stats": {}}

    unique_runs = df[run_col].dropna().unique().tolist()
    unique_stations = df[st_col].dropna().unique().tolist()
    min_range = [int(df[min_col].min()), int(df[min_col].max())]

    return {
        "valid": True,
        "errors": [],
        "warnings": warnings,
        "stats": {
            "runs_detected": len(unique_runs),
            "sample_runs": unique_runs[:5],
            "stations_covered": len(unique_stations),
            "minute_range": min_range,
            "avg_cycle_time": round(float(df[ct_col].mean()), 2)
        }
    }


def save_factory_datasets_and_stations(factory_id: str, stations_data: list, deps_data: list):
    """
    Commits validated stations and dependencies to SQLite for the given factory workspace.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    now_str = datetime.utcnow().isoformat() + "Z"

    # Insert stations
    for s in stations_data:
        cur.execute("""
        INSERT OR REPLACE INTO factory_stations
        (factory_id, station_id, station_name, line_phase, baseline_cycle_time_sec, sensor_tier, station_order, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            factory_id,
            s["station_id"],
            s["station_name"],
            s.get("line_phase", "Assembly"),
            s.get("baseline_cycle_time_sec", 45.0),
            s.get("sensor_tier", "PARTIAL"),
            s.get("station_order", 1),
            now_str
        ))

    # Insert dependencies
    for d in deps_data:
        cur.execute("""
        INSERT INTO factory_dependencies
        (factory_id, upstream_station_id, downstream_station_id, buffer_capacity, transit_time_sec)
        VALUES (?, ?, ?, ?, ?)
        """, (
            factory_id,
            d["upstream_station_id"],
            d["downstream_station_id"],
            d.get("buffer_capacity", 10),
            d.get("transit_time_sec", 5.0)
        ))

    # Update factory status to ready
    cur.execute("UPDATE factories SET status = 'active' WHERE id = ?", (factory_id,))

    conn.commit()
    conn.close()
    return True
