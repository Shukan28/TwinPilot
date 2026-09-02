"""
TwinPilot Plant B (61 Stations) Dataset Generator
=================================================
Generates the complete 61-station Fremont EV Gigafactory dataset:
1. plant_b_stations_master.csv (61 stations, sensor tiers, baseline CT)
2. plant_b_station_dependencies.csv (Full DAG topology with converging sub-assembly lines)
3. plant_b_sensor_timeseries.csv (Multi-run timeseries telemetry across all 61 stations)
4. plant_b_events_ground_truth.csv (Ground truth anomaly & propagation events)
"""

import os
# pyrefly: ignore [missing-import]
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

DATASET_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "twinpilot_dataset_extracted", "plant_b_dataset")
os.makedirs(DATASET_OUT, exist_ok=True)

# ── 1. STATIONS MASTER (61 Stations) ──────────────────────────────────────────
stations = [
    # Stamping (6)
    {"station_id": "ST01", "station_name": "Coil Feed & Blanking", "phase": "Stamping", "sequence_order": 1, "sensor_tier": "rich", "sensors_available": "cycle_time,vibration,torque", "baseline_cycle_time_sec": 35.0, "upstream": ""},
    {"station_id": "ST02", "station_name": "Main Body Press 2500T", "phase": "Stamping", "sequence_order": 2, "sensor_tier": "rich", "sensors_available": "cycle_time,vibration,temperature,torque", "baseline_cycle_time_sec": 38.0, "upstream": "ST01"},
    {"station_id": "ST03", "station_name": "Side Aperture Draw Press", "phase": "Stamping", "sequence_order": 3, "sensor_tier": "rich", "sensors_available": "cycle_time,vibration,torque", "baseline_cycle_time_sec": 40.0, "upstream": "ST02"},
    {"station_id": "ST04", "station_name": "Door Inner Trim & Pierce", "phase": "Stamping", "sequence_order": 4, "sensor_tier": "partial", "sensors_available": "cycle_time,vibration", "baseline_cycle_time_sec": 36.0, "upstream": "ST03"},
    {"station_id": "ST05", "station_name": "Hood & Tailgate Stamping", "phase": "Stamping", "sequence_order": 5, "sensor_tier": "rich", "sensors_available": "cycle_time,vibration,torque", "baseline_cycle_time_sec": 42.0, "upstream": "ST04"},
    {"station_id": "ST06", "station_name": "Stamped Panel Inspection", "phase": "Stamping", "sequence_order": 6, "sensor_tier": "manual", "sensors_available": "", "baseline_cycle_time_sec": 45.0, "upstream": "ST05"},

    # Body-in-White Framing (12)
    {"station_id": "B01", "station_name": "Underbody Front Laser Weld", "phase": "Body Framing", "sequence_order": 7, "sensor_tier": "rich", "sensors_available": "cycle_time,torque,vibration", "baseline_cycle_time_sec": 42.0, "upstream": "ST06"},
    {"station_id": "B02", "station_name": "Battery Tray Framing", "phase": "Body Framing", "sequence_order": 8, "sensor_tier": "rich", "sensors_available": "cycle_time,torque,vibration", "baseline_cycle_time_sec": 44.0, "upstream": "B01"},
    {"station_id": "B03", "station_name": "Floor Pan Spot Weld L1", "phase": "Body Framing", "sequence_order": 9, "sensor_tier": "rich", "sensors_available": "cycle_time,torque,vibration", "baseline_cycle_time_sec": 39.0, "upstream": "B02"},
    {"station_id": "B04", "station_name": "Floor Pan Spot Weld L2", "phase": "Body Framing", "sequence_order": 10, "sensor_tier": "rich", "sensors_available": "cycle_time,torque,vibration", "baseline_cycle_time_sec": 41.0, "upstream": "B03"},
    {"station_id": "B05", "station_name": "Left Aperture Sub-framing", "phase": "Body Framing", "sequence_order": 11, "sensor_tier": "rich", "sensors_available": "cycle_time,torque,vibration", "baseline_cycle_time_sec": 43.0, "upstream": "B04"},
    {"station_id": "B06", "station_name": "Right Aperture Sub-framing", "phase": "Body Framing", "sequence_order": 12, "sensor_tier": "rich", "sensors_available": "cycle_time,torque,vibration", "baseline_cycle_time_sec": 43.0, "upstream": "B05"},
    {"station_id": "B07", "station_name": "Main Robogate Framing", "phase": "Body Framing", "sequence_order": 13, "sensor_tier": "rich", "sensors_available": "cycle_time,torque,vibration,temperature", "baseline_cycle_time_sec": 46.0, "upstream": "B06"},
    {"station_id": "B08", "station_name": "Roof Laser Brazing", "phase": "Body Framing", "sequence_order": 14, "sensor_tier": "rich", "sensors_available": "cycle_time,torque,vibration", "baseline_cycle_time_sec": 38.0, "upstream": "B07"},
    {"station_id": "B09", "station_name": "Door Hang & Hinge Align", "phase": "Body Framing", "sequence_order": 15, "sensor_tier": "partial", "sensors_available": "cycle_time,torque", "baseline_cycle_time_sec": 42.0, "upstream": "B08"},
    {"station_id": "B10", "station_name": "Hood & Liftgate Fitment", "phase": "Body Framing", "sequence_order": 16, "sensor_tier": "partial", "sensors_available": "cycle_time,torque", "baseline_cycle_time_sec": 40.0, "upstream": "B09"},
    {"station_id": "B11", "station_name": "Inline Laser CMM Metrology", "phase": "Body Framing", "sequence_order": 17, "sensor_tier": "rich", "sensors_available": "cycle_time,vibration,temperature", "baseline_cycle_time_sec": 48.0, "upstream": "B10"},
    {"station_id": "B12", "station_name": "BIW Manual Touch-Up", "phase": "Body Framing", "sequence_order": 18, "sensor_tier": "manual", "sensors_available": "", "baseline_cycle_time_sec": 50.0, "upstream": "B11"},

    # Paint Shop (10)
    {"station_id": "P01", "station_name": "Pre-treatment Degrease", "phase": "Paint", "sequence_order": 19, "sensor_tier": "partial", "sensors_available": "cycle_time,temperature", "baseline_cycle_time_sec": 48.0, "upstream": "B12"},
    {"station_id": "P02", "station_name": "E-Coat Dip Tank", "phase": "Paint", "sequence_order": 20, "sensor_tier": "rich", "sensors_available": "cycle_time,temperature,vibration", "baseline_cycle_time_sec": 55.0, "upstream": "P01"},
    {"station_id": "P03", "station_name": "E-Coat Curing Oven", "phase": "Paint", "sequence_order": 21, "sensor_tier": "rich", "sensors_available": "cycle_time,temperature", "baseline_cycle_time_sec": 58.0, "upstream": "P02"},
    {"station_id": "P04", "station_name": "Underbody PVC Sealer", "phase": "Paint", "sequence_order": 22, "sensor_tier": "rich", "sensors_available": "cycle_time,temperature,vibration", "baseline_cycle_time_sec": 44.0, "upstream": "P03"},
    {"station_id": "P05", "station_name": "Primer Coat Robotic Bell", "phase": "Paint", "sequence_order": 23, "sensor_tier": "rich", "sensors_available": "cycle_time,temperature,vibration", "baseline_cycle_time_sec": 42.0, "upstream": "P04"},
    {"station_id": "P06", "station_name": "Primer Flash-off Zone", "phase": "Paint", "sequence_order": 24, "sensor_tier": "partial", "sensors_available": "cycle_time,temperature", "baseline_cycle_time_sec": 40.0, "upstream": "P05"},
    {"station_id": "P07", "station_name": "Base Coat Application", "phase": "Paint", "sequence_order": 25, "sensor_tier": "rich", "sensors_available": "cycle_time,temperature,vibration", "baseline_cycle_time_sec": 45.0, "upstream": "P06"},
    {"station_id": "P08", "station_name": "Clear Coat High Gloss", "phase": "Paint", "sequence_order": 26, "sensor_tier": "rich", "sensors_available": "cycle_time,temperature,vibration", "baseline_cycle_time_sec": 46.0, "upstream": "P07"},
    {"station_id": "P09", "station_name": "Paint Main Bake Oven", "phase": "Paint", "sequence_order": 27, "sensor_tier": "rich", "sensors_available": "cycle_time,temperature", "baseline_cycle_time_sec": 60.0, "upstream": "P08"},
    {"station_id": "P10", "station_name": "Paint Quality & Polish", "phase": "Paint", "sequence_order": 28, "sensor_tier": "manual", "sensors_available": "", "baseline_cycle_time_sec": 52.0, "upstream": "P09"},

    # Battery Pack Integration (8) - Feeder Line converging at Marriage
    {"station_id": "BAT01", "station_name": "Cell Sorting & Impedance", "phase": "Battery Assembly", "sequence_order": 29, "sensor_tier": "rich", "sensors_available": "cycle_time,temperature,vibration", "baseline_cycle_time_sec": 36.0, "upstream": ""},
    {"station_id": "BAT02", "station_name": "Laser Busbar Wire Bonding", "phase": "Battery Assembly", "sequence_order": 30, "sensor_tier": "rich", "sensors_available": "cycle_time,temperature,torque", "baseline_cycle_time_sec": 40.0, "upstream": "BAT01"},
    {"station_id": "BAT03", "station_name": "Thermal Interface Dispense", "phase": "Battery Assembly", "sequence_order": 31, "sensor_tier": "rich", "sensors_available": "cycle_time,temperature,vibration", "baseline_cycle_time_sec": 38.0, "upstream": "BAT02"},
    {"station_id": "BAT04", "station_name": "BMS Harness Installation", "phase": "Battery Assembly", "sequence_order": 32, "sensor_tier": "manual", "sensors_available": "", "baseline_cycle_time_sec": 46.0, "upstream": "BAT03"},
    {"station_id": "BAT05", "station_name": "Module Pack Torquing", "phase": "Battery Assembly", "sequence_order": 33, "sensor_tier": "rich", "sensors_available": "cycle_time,torque,vibration", "baseline_cycle_time_sec": 44.0, "upstream": "BAT04"},
    {"station_id": "BAT06", "station_name": "Coolant Leak Helium Test", "phase": "Battery Assembly", "sequence_order": 34, "sensor_tier": "rich", "sensors_available": "cycle_time,temperature", "baseline_cycle_time_sec": 50.0, "upstream": "BAT05"},
    {"station_id": "BAT07", "station_name": "Top Cover Multi-Torque", "phase": "Battery Assembly", "sequence_order": 35, "sensor_tier": "rich", "sensors_available": "cycle_time,torque,vibration", "baseline_cycle_time_sec": 42.0, "upstream": "BAT06"},
    {"station_id": "BAT08", "station_name": "EOL Hi-Pot & Capacity", "phase": "Battery Assembly", "sequence_order": 36, "sensor_tier": "rich", "sensors_available": "cycle_time,temperature", "baseline_cycle_time_sec": 54.0, "upstream": "BAT07"},

    # Powertrain & Drive Unit (4) - Feeder Line converging at Marriage
    {"station_id": "PT01", "station_name": "Dual-Motor Gearbox Build", "phase": "Powertrain", "sequence_order": 37, "sensor_tier": "rich", "sensors_available": "cycle_time,torque,vibration,temperature", "baseline_cycle_time_sec": 45.0, "upstream": ""},
    {"station_id": "PT02", "station_name": "Drive Unit Spin Dyno", "phase": "Powertrain", "sequence_order": 38, "sensor_tier": "rich", "sensors_available": "cycle_time,torque,vibration,temperature", "baseline_cycle_time_sec": 48.0, "upstream": "PT01"},
    {"station_id": "PT03", "station_name": "Subframe Bushing Press", "phase": "Powertrain", "sequence_order": 39, "sensor_tier": "partial", "sensors_available": "cycle_time,torque", "baseline_cycle_time_sec": 44.0, "upstream": "PT02"},
    {"station_id": "PT04", "station_name": "Fluid Vacuum Fill", "phase": "Powertrain", "sequence_order": 40, "sensor_tier": "rich", "sensors_available": "cycle_time,temperature", "baseline_cycle_time_sec": 40.0, "upstream": "PT03"},

    # General Assembly (GA) (14)
    {"station_id": "GA01", "station_name": "Cockpit Sub-Assembly", "phase": "General Assembly", "sequence_order": 41, "sensor_tier": "partial", "sensors_available": "cycle_time,torque", "baseline_cycle_time_sec": 42.0, "upstream": "P10"},
    {"station_id": "GA02", "station_name": "Dashboard Robotic Decking", "phase": "General Assembly", "sequence_order": 42, "sensor_tier": "rich", "sensors_available": "cycle_time,torque,vibration", "baseline_cycle_time_sec": 44.0, "upstream": "GA01"},
    {"station_id": "GA03", "station_name": "Main Body Wiring Harness", "phase": "General Assembly", "sequence_order": 43, "sensor_tier": "manual", "sensors_available": "", "baseline_cycle_time_sec": 50.0, "upstream": "GA02"},
    {"station_id": "GA04", "station_name": "HVAC Unit & Thermal Ducts", "phase": "General Assembly", "sequence_order": 44, "sensor_tier": "partial", "sensors_available": "cycle_time,torque", "baseline_cycle_time_sec": 42.0, "upstream": "GA03"},
    {"station_id": "GA05", "station_name": "Windshield Urethane & Glass", "phase": "General Assembly", "sequence_order": 45, "sensor_tier": "rich", "sensors_available": "cycle_time,vibration", "baseline_cycle_time_sec": 39.0, "upstream": "GA04"},
    {"station_id": "GA06", "station_name": "Carpet & Acoustic Dampers", "phase": "General Assembly", "sequence_order": 46, "sensor_tier": "manual", "sensors_available": "", "baseline_cycle_time_sec": 45.0, "upstream": "GA05"},
    {"station_id": "GA07", "station_name": "Ergonomic Seat Mounting", "phase": "General Assembly", "sequence_order": 47, "sensor_tier": "manual", "sensors_available": "", "baseline_cycle_time_sec": 44.0, "upstream": "GA06"},
    {"station_id": "GA08", "station_name": "Center Console & Steering", "phase": "General Assembly", "sequence_order": 48, "sensor_tier": "partial", "sensors_available": "cycle_time,torque", "baseline_cycle_time_sec": 41.0, "upstream": "GA07"},
    {"station_id": "GA09", "station_name": "Door Weatherstrip & Clad", "phase": "General Assembly", "sequence_order": 49, "sensor_tier": "manual", "sensors_available": "", "baseline_cycle_time_sec": 46.0, "upstream": "GA08"},
    {"station_id": "GA10", "station_name": "Battery Pack Marriage", "phase": "General Assembly", "sequence_order": 50, "sensor_tier": "rich", "sensors_available": "cycle_time,torque,vibration", "baseline_cycle_time_sec": 48.0, "upstream": "GA09,BAT08"},
    {"station_id": "GA11", "station_name": "Drive Unit Marriage", "phase": "General Assembly", "sequence_order": 51, "sensor_tier": "rich", "sensors_available": "cycle_time,torque,vibration", "baseline_cycle_time_sec": 50.0, "upstream": "GA10,PT04"},
    {"station_id": "GA12", "station_name": "Suspension Strut Bolting", "phase": "General Assembly", "sequence_order": 52, "sensor_tier": "rich", "sensors_available": "cycle_time,torque,vibration", "baseline_cycle_time_sec": 45.0, "upstream": "GA11"},
    {"station_id": "GA13", "station_name": "Robotic Wheel Mounting", "phase": "General Assembly", "sequence_order": 53, "sensor_tier": "rich", "sensors_available": "cycle_time,torque", "baseline_cycle_time_sec": 38.0, "upstream": "GA12"},
    {"station_id": "GA14", "station_name": "Brake Fluid Vacuum Bleed", "phase": "General Assembly", "sequence_order": 54, "sensor_tier": "rich", "sensors_available": "cycle_time,temperature", "baseline_cycle_time_sec": 42.0, "upstream": "GA13"},

    # End of Line (EOL) & ADAS (7)
    {"station_id": "EOL01", "station_name": "ECU Flashing & Wake-Up", "phase": "End of Line", "sequence_order": 55, "sensor_tier": "partial", "sensors_available": "cycle_time,temperature", "baseline_cycle_time_sec": 46.0, "upstream": "GA14"},
    {"station_id": "EOL02", "station_name": "3D Wheel Alignment", "phase": "End of Line", "sequence_order": 56, "sensor_tier": "rich", "sensors_available": "cycle_time,torque,vibration", "baseline_cycle_time_sec": 44.0, "upstream": "EOL01"},
    {"station_id": "EOL03", "station_name": "ADAS Radar/Optical Cal", "phase": "End of Line", "sequence_order": 57, "sensor_tier": "rich", "sensors_available": "cycle_time,temperature", "baseline_cycle_time_sec": 52.0, "upstream": "EOL02"},
    {"station_id": "EOL04", "station_name": "4-Wheel Dyno Roll Test", "phase": "End of Line", "sequence_order": 58, "sensor_tier": "rich", "sensors_available": "cycle_time,torque,vibration,temperature", "baseline_cycle_time_sec": 55.0, "upstream": "EOL03"},
    {"station_id": "EOL05", "station_name": "Monsoon Water Ingress", "phase": "End of Line", "sequence_order": 59, "sensor_tier": "partial", "sensors_available": "cycle_time,temperature", "baseline_cycle_time_sec": 48.0, "upstream": "EOL04"},
    {"station_id": "EOL06", "station_name": "Squeak & Rattle Track", "phase": "End of Line", "sequence_order": 60, "sensor_tier": "rich", "sensors_available": "cycle_time,vibration", "baseline_cycle_time_sec": 45.0, "upstream": "EOL05"},
    {"station_id": "EOL07", "station_name": "Final Customer Buyoff", "phase": "End of Line", "sequence_order": 61, "sensor_tier": "manual", "sensors_available": "", "baseline_cycle_time_sec": 60.0, "upstream": "EOL06"}
]

df_stations = pd.DataFrame(stations)
df_stations["baseline_throughput_uph"] = (3600.0 / df_stations["baseline_cycle_time_sec"]).round(1)
stations_csv_path = os.path.join(DATASET_OUT, "plant_b_stations_master.csv")
df_stations.to_csv(stations_csv_path, index=False)
print(f"[Plant B Dataset] Created stations master: {len(df_stations)} stations -> {stations_csv_path}")

# ── 2. STATION DEPENDENCIES (DAG Topology) ───────────────────────────────────
deps = []
for s in stations:
    sid = s["station_id"]
    up = s["upstream"]
    if up:
        for u in up.split(","):
            u = u.strip()
            if u:
                deps.append({
                    "upstream_station_id": u,
                    "downstream_station_id": sid,
                    "buffer_capacity": 12 if "BAT" in sid or "PT" in sid else 10,
                    "transit_time_sec": 6.0
                })

df_deps = pd.DataFrame(deps)
deps_csv_path = os.path.join(DATASET_OUT, "plant_b_station_dependencies.csv")
df_deps.to_csv(deps_csv_path, index=False)
print(f"[Plant B Dataset] Created DAG dependencies: {len(df_deps)} links -> {deps_csv_path}")

# ── 3. SENSOR TIMESERIES & GROUND TRUTH EVENTS ───────────────────────────────
np.random.seed(42)
N_RUNS = 20
SHIFT_MINUTES = 240

events = []
timeseries_rows = []

for run_idx in range(1, N_RUNS + 1):
    run_id = f"RUN-PB-{run_idx:03d}"
    
    # 2 Anomaly events per run: 1 bottleneck and 1 defect propagation
    evt1_peak = int(np.random.randint(60, 110))
    evt1_origin = "BAT05" if run_idx % 2 == 0 else "B07"
    evt1_type = "defect_propagation"
    events.append({
        "run_id": run_id,
        "event_id": f"{run_id.replace('-', '')}-EVT01",
        "event_type": evt1_type,
        "origin_station_id": evt1_origin,
        "peak_minute": evt1_peak,
        "start_minute": max(0, evt1_peak - 20),
        "resolved_minute": min(239, evt1_peak + 25),
        "severity": "high",
        "propagation_path": f"{evt1_origin},BAT06,BAT07,BAT08,GA10" if "BAT" in evt1_origin else f"{evt1_origin},B08,B09,B10,B11"
    })

    evt2_peak = int(np.random.randint(140, 200))
    evt2_origin = "GA10" if run_idx % 2 == 0 else "ST02"
    evt2_type = "bottleneck"
    events.append({
        "run_id": run_id,
        "event_id": f"{run_id.replace('-', '')}-EVT02",
        "event_type": evt2_type,
        "origin_station_id": evt2_origin,
        "peak_minute": evt2_peak,
        "start_minute": max(0, evt2_peak - 22),
        "resolved_minute": min(239, evt2_peak + 20),
        "severity": "critical",
        "propagation_path": f"{evt2_origin},GA11,GA12,GA13" if "GA" in evt2_origin else f"{evt2_origin},ST03,ST04,ST05"
    })

    # Telemetry generation across 61 stations
    for minute in range(SHIFT_MINUTES):
        for s in stations:
            sid = s["station_id"]
            base_ct = s["baseline_cycle_time_sec"]
            tier = s["sensor_tier"]

            # Calculate anomaly injection intensity
            intensity1 = 0.0
            if evt1_origin == sid and (evt1_peak - 20 <= minute <= evt1_peak + 25):
                dist = abs(minute - evt1_peak)
                intensity1 = max(0.0, 1.0 - dist / 22.0)

            intensity2 = 0.0
            if evt2_origin == sid and (evt2_peak - 22 <= minute <= evt2_peak + 20):
                dist = abs(minute - evt2_peak)
                intensity2 = max(0.0, 1.0 - dist / 22.0)

            ct = base_ct + np.random.normal(0, 0.6)
            q = max(0, int(np.random.poisson(1.2)))
            vib = 0.75 + np.random.normal(0, 0.05)
            torq = 145.0 + np.random.normal(0, 2.5)
            temp = 42.0 + np.random.normal(0, 0.8)

            if intensity1 > 0:
                ct += 8.5 * intensity1
                vib += 1.8 * intensity1
                torq += 35.0 * intensity1
                temp += 12.0 * intensity1
                q += int(round(6 * intensity1))

            if intensity2 > 0:
                ct += 14.0 * intensity2
                q += int(round(9 * intensity2))
                vib += 0.4 * intensity2

            # Null out unmeasured sensors for partial/manual tiers
            if tier == "manual":
                vib = np.nan
                torq = np.nan
                temp = np.nan
                q = 0 if intensity1 == 0 and intensity2 == 0 else max(1, q)
            elif tier == "partial":
                if "vibration" not in s["sensors_available"]: vib = np.nan
                if "torque" not in s["sensors_available"]: torq = np.nan
                if "temperature" not in s["sensors_available"]: temp = np.nan

            timeseries_rows.append({
                "run_id": run_id,
                "minute_index": minute,
                "station_id": sid,
                "cycle_time_sec": round(float(ct), 2),
                "queue_length": int(q),
                "vibration_mm_s": round(float(vib), 3) if pd.notnull(vib) else np.nan,
                "torque_nm": round(float(torq), 2) if pd.notnull(torq) else np.nan,
                "temperature_c": round(float(temp), 2) if pd.notnull(temp) else np.nan
            })

df_events = pd.DataFrame(events)
events_csv_path = os.path.join(DATASET_OUT, "plant_b_events_ground_truth.csv")
df_events.to_csv(events_csv_path, index=False)
print(f"[Plant B Dataset] Created events ground truth: {len(df_events)} events -> {events_csv_path}")

df_ts = pd.DataFrame(timeseries_rows)
ts_csv_path = os.path.join(DATASET_OUT, "plant_b_sensor_timeseries.csv")
df_ts.to_csv(ts_csv_path, index=False)
print(f"[Plant B Dataset] Created timeseries telemetry: {len(df_ts):,} rows -> {ts_csv_path}")

# Also copy/symlink to root directory for easy single-file references
for fname in ["plant_b_stations_master.csv", "plant_b_station_dependencies.csv", "plant_b_sensor_timeseries.csv", "plant_b_events_ground_truth.csv"]:
    src = os.path.join(DATASET_OUT, fname)
    dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), fname)
    with open(src, "rb") as sf, open(dst, "wb") as df:
        df.write(sf.read())

print("[Plant B Dataset Generation Complete] All 61 stations ready for full onboarding and training.")
