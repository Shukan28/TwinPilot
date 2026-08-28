# pyrefly: ignore [missing-import]
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
N_RUNS = 25                 # independent production shifts
SHIFT_MINUTES = 240         # 4-hour shift, 1-min resolution -> 31*240=7440 rows/run
FIRST_SHIFT_DATE = datetime(2026, 8, 1, 6, 0, 0)
LINE_ENTRY_INTERVAL_SEC = 80

stations_df = pd.read_csv("stations_master.csv", dtype=str)
stations_df["baseline_cycle_time_sec"] = stations_df["baseline_cycle_time_sec"].astype(float)
stations_df["sequence_order"] = stations_df["sequence_order"].astype(int)

station_ids = stations_df["station_id"].tolist()
baseline = dict(zip(stations_df.station_id, stations_df.baseline_cycle_time_sec))
sensor_tier = dict(zip(stations_df.station_id, stations_df.sensor_tier))
sensors_avail = dict(zip(stations_df.station_id, stations_df.sensors_available.fillna("")))
phase_of = dict(zip(stations_df.station_id, stations_df.phase))

# trunk = main sequence excluding the parallel ENG01 feeder, ordered by sequence_order
trunk = stations_df[stations_df.station_id != "ENG01"].sort_values("sequence_order").station_id.tolist()
manual_stations = stations_df[stations_df.sensor_tier == "manual"].station_id.tolist()
rich_or_partial = [s for s in station_ids if sensor_tier[s] != "manual"]

def downstream_path(origin, hops):
    """origin + up to `hops` downstream stations along the main trunk."""
    if origin == "ENG01":
        idx = trunk.index("S23")
        path = ["ENG01"] + trunk[idx: idx + hops]
    else:
        idx = trunk.index(origin)
        path = trunk[idx: idx + hops + 1]
    return path

EVENT_TYPES = ["bottleneck", "defect_propagation", "sensorless_drift", "machine_failure"]
EVENT_TYPE_WEIGHTS = [0.35, 0.30, 0.15, 0.20]
SEVERITIES = ["low", "medium", "high", "critical"]
SEVERITY_WEIGHTS = [0.25, 0.35, 0.25, 0.15]

# Defect signal mechanisms — each one shifts different sensors as the primary lead indicator.
# This gives the ML model genuinely different patterns to learn rather than 20 copies of
# "cycle time goes up".
DEFECT_SIGNAL_TYPES = [
    "torque_drift",           # primary: torque drifts up; secondary: vibration mild rise
    "vibration_spike",        # primary: vibration spikes hard; secondary: cycle time mild
    "temperature_shift",      # primary: temperature climbs; secondary: torque mild rise
    "cycle_time_drift",       # primary: cycle time slows; secondary: queue grows
    "component_quality",      # primary: torque + vibration both drift together
]

def event_intensity(minute, start, peak, resolved):
    if minute < start or minute > resolved:
        return 0.0
    if minute <= peak:
        span = max(peak - start, 1)
        return min(1.0, (minute - start) / span)
    span = max(resolved - peak, 1)
    return max(0.0, 1.0 - (minute - peak) / span)

def make_random_event(rng, run_idx, evt_idx, force_defect=False):
    if force_defect:
        etype = "defect_propagation"
    else:
        etype = rng.choice(EVENT_TYPES, p=EVENT_TYPE_WEIGHTS)
    severity = rng.choice(SEVERITIES, p=SEVERITY_WEIGHTS)

    if etype == "sensorless_drift":
        origin = rng.choice(manual_stations)
    elif etype == "defect_propagation":
        # Spread origin stations across the whole line — not just one cluster.
        # Use full trunk so defects can start anywhere with room for propagation.
        candidates = [s for s in trunk if trunk.index(s) <= len(trunk) - 4]
        origin = rng.choice(candidates)
    else:
        origin = rng.choice(rich_or_partial if etype != "bottleneck" else station_ids)

    if etype == "bottleneck":
        ramp = int(rng.integers(15, 41)); hold = int(rng.integers(5, 16)); decay = int(rng.integers(10, 21))
        hops = int(rng.integers(2, 5))
        detect_frac = rng.uniform(0.35, 0.55)
        signal_type = None
    elif etype == "defect_propagation":
        # Varied timing: some defects are fast and sharp, others slow and creeping
        ramp = int(rng.integers(4, 20)); hold = int(rng.integers(2, 12)); decay = int(rng.integers(15, 45))
        # Varied propagation length: some defects spread far, others are contained
        hops = int(rng.integers(2, 8))
        detect_frac = rng.uniform(0.45, 0.85)
        signal_type = str(rng.choice(DEFECT_SIGNAL_TYPES))
    elif etype == "sensorless_drift":
        ramp = int(rng.integers(10, 26)); hold = int(rng.integers(4, 12)); decay = int(rng.integers(10, 21))
        hops = int(rng.integers(2, 4))
        detect_frac = rng.uniform(0.55, 0.8)
        signal_type = None
    else:  # machine_failure
        ramp = int(rng.integers(1, 5)); hold = int(rng.integers(2, 7)); decay = int(rng.integers(5, 13))
        hops = int(rng.integers(1, 4))
        detect_frac = rng.uniform(0.15, 0.35)
        signal_type = None

    latest_start = SHIFT_MINUTES - (ramp + hold + decay) - 5
    if latest_start < 20:
        latest_start = 20
    start = int(rng.integers(20, max(21, latest_start)))
    peak = start + ramp
    resolved = min(SHIFT_MINUTES - 1, peak + hold + decay)
    detectable = start + max(1, int(round((peak - start) * detect_frac)))

    path = downstream_path(origin, hops)

    root_cause = f"Simulated {etype.replace('_',' ')} originating at {origin}."
    if signal_type:
        root_cause += f" Signal pattern: {signal_type}."

    return {
        "event_id": f"RUN{run_idx:03d}-EVT{evt_idx:02d}",
        "run_id": f"RUN-{run_idx:03d}",
        "event_type": etype,
        "origin_station_id": origin,
        "start_minute": start,
        "detectable_minute": detectable,
        "peak_minute": peak,
        "resolved_minute": resolved,
        "propagation_path": ",".join(path),
        "root_cause": root_cause,
        "severity": severity,
        "defect_signal_type": signal_type if signal_type else "",
    }

def maybe_maintenance(rng, run_idx):
    if rng.random() > 0.20:
        return None
    sid = rng.choice([s for s in rich_or_partial])
    dur = int(rng.integers(10, 21))
    latest_start = SHIFT_MINUTES - dur - 5
    start = int(rng.integers(20, max(21, latest_start)))
    return {
        "run_id": f"RUN-{run_idx:03d}",
        "station_id": sid,
        "window_start_minute": start,
        "window_end_minute": start + dur,
        "type": "scheduled",
        "notes": "Planned retrofit/maintenance window.",
    }

# ---------------------------------------------------------------------------
# GENERATE ALL RUNS
# ---------------------------------------------------------------------------
all_events = []
all_maint = []
all_timeseries = []
all_manual_checks = []
all_vehicles = []
run_summaries = []

vin_counter = 2026000

# Pre-assign which runs will have a forced defect event so we get 22 defect events total.
# These are spread deliberately: roughly one defect every 1-2 runs, skipping a handful
# of runs to keep clean negative-control shifts.
# Runs 1-25, we force defects on ~22 of them but leave 3 completely clean.
FORCED_DEFECT_RUNS = set(range(1, 26)) - {4, 12, 19}  # 22 runs get a guaranteed defect

for run_idx in range(1, N_RUNS + 1):
    rng = np.random.default_rng(1000 + run_idx)
    run_id = f"RUN-{run_idx:03d}"
    shift_start = FIRST_SHIFT_DATE + timedelta(days=run_idx - 1)

    # --- events for this run ---
    # Base random events (0-3 additional, skewed toward 1)
    n_extra = min(3, rng.poisson(1.0))
    events = []
    evt_idx = 1

    # Guarantee a defect event on forced runs as event #1
    if run_idx in FORCED_DEFECT_RUNS:
        events.append(make_random_event(rng, run_idx, evt_idx, force_defect=True))
        evt_idx += 1

    # Add additional random events of any type
    for _ in range(n_extra):
        events.append(make_random_event(rng, run_idx, evt_idx))
        evt_idx += 1

    all_events.extend(events)

    maint = maybe_maintenance(rng, run_idx)
    if maint:
        all_maint.append(maint)

    # station -> list of (event_dict, hop_distance)
    station_events = {sid: [] for sid in station_ids}
    for ev in events:
        path = ev["propagation_path"].split(",")
        for hop, sid in enumerate(path):
            station_events[sid].append((ev, hop))

    # --- per-station timeseries for this run ---
    station_noise_params = {}
    for sid in station_ids:
        station_noise_params[sid] = {
            "torque_base": rng.uniform(35, 65),
            "vib_base": rng.uniform(0.8, 2.2),
            "temp_base": rng.uniform(55, 85) if phase_of[sid] == "Paint" else rng.uniform(38, 62),
        }

    for sid in station_ids:
        base_ct = baseline[sid]
        avail = set(sensors_avail[sid].split(",")) if sensors_avail[sid] else set()
        ct_noise_sd = base_ct * 0.03
        p = station_noise_params[sid]
        is_maint_station = maint is not None and maint["station_id"] == sid

        for m in range(SHIFT_MINUTES):
            ts = shift_start + timedelta(minutes=m)

            total_intensity = 0.0
            max_hop = 0
            active_ids = []
            dominant_event = None
            for ev, hop in station_events[sid]:
                lag = hop * 3
                inten = event_intensity(m - lag, ev["start_minute"], ev["peak_minute"], ev["resolved_minute"])
                damp = 1.0 if hop == 0 else max(0.15, 0.6 - 0.12 * hop)
                eff = inten * damp
                if eff > total_intensity:
                    total_intensity = eff
                    max_hop = hop
                    dominant_event = ev
                if inten > 0.05:
                    active_ids.append(ev["event_id"])

            in_maint_window = is_maint_station and maint["window_start_minute"] <= m <= maint["window_end_minute"]

            if in_maint_window:
                ct = torque = vib = temp = queue = None
                status = "maintenance"
            else:
                # Determine signal-type multipliers based on the dominant defect signal pattern.
                # Each defect mechanism has a unique sensor fingerprint so the ML model
                # learns varied patterns rather than one generic "intensity goes up" pattern.
                sig = dominant_event.get("defect_signal_type", "") if dominant_event and dominant_event["event_type"] == "defect_propagation" else ""
                I = total_intensity  # shorthand

                if sig == "torque_drift":
                    ct_scale   = 1.0 + 0.10 * I          # mild cycle time drift
                    torq_scale = 1.0 + 0.55 * I          # STRONG torque rise
                    vib_scale  = 1.0 + 0.20 * I          # mild vibration
                    temp_scale = 1.0 + 0.05 * I          # almost no temperature change
                    queue_base = 2.0 + I * 4
                elif sig == "vibration_spike":
                    ct_scale   = 1.0 + 0.15 * I
                    torq_scale = 1.0 + 0.10 * I          # mild torque
                    vib_scale  = 1.0 + 0.80 * I          # STRONG vibration spike
                    temp_scale = 1.0 + 0.04 * I
                    queue_base = 1.5 + I * 3
                elif sig == "temperature_shift":
                    ct_scale   = 1.0 + 0.10 * I
                    torq_scale = 1.0 + 0.25 * I          # moderate torque
                    vib_scale  = 1.0 + 0.10 * I
                    temp_scale = 1.0 + 0.45 * I          # STRONG temperature climb
                    queue_base = 1.5 + I * 3
                elif sig == "cycle_time_drift":
                    ct_scale   = 1.0 + 0.60 * I          # STRONG cycle time slow-down
                    torq_scale = 1.0 + 0.10 * I
                    vib_scale  = 1.0 + 0.10 * I
                    temp_scale = 1.0 + 0.03 * I
                    queue_base = 2.5 + I * 9             # queue grows heavily
                elif sig == "component_quality":
                    ct_scale   = 1.0 + 0.20 * I
                    torq_scale = 1.0 + 0.45 * I          # STRONG torque + vibration together
                    vib_scale  = 1.0 + 0.45 * I
                    temp_scale = 1.0 + 0.12 * I
                    queue_base = 1.5 + I * 4
                else:
                    # Default (bottleneck, machine_failure, sensorless_drift, or no signal type)
                    ct_scale   = 1.0 + (0.5 if max_hop == 0 else 0.25) * I
                    torq_scale = 1.0 + 0.30 * I
                    vib_scale  = 1.0 + 0.40 * I
                    temp_scale = 1.0 + 0.08 * I
                    queue_base = 1.5 + I * 8

                ct = max(5.0, rng.normal(base_ct * ct_scale, ct_noise_sd))
                torque = vib = temp = None
                if "torque" in avail:
                    torque = round(max(0.0, rng.normal(p["torque_base"] * torq_scale, p["torque_base"] * 0.04)), 2)
                if "vibration" in avail:
                    vib = round(max(0.0, rng.normal(p["vib_base"] * vib_scale, p["vib_base"] * 0.05)), 3)
                if "temperature" in avail:
                    temp = round(max(0.0, rng.normal(p["temp_base"] * temp_scale, p["temp_base"] * 0.02)), 2)
                queue = max(0, round(rng.poisson(queue_base) + rng.normal(0, 0.6)))
                ct = round(ct, 2)
                status = "critical" if total_intensity > 0.66 else ("warning" if total_intensity > 0.25 else "normal")

            all_timeseries.append({
                "run_id": run_id,
                "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "minute_index": m,
                "station_id": sid,
                "cycle_time_sec": ct,
                "torque_nm": torque,
                "vibration_mm_s": vib,
                "temperature_c": temp,
                "queue_length": queue,
                "status_flag": status,
                "active_event_ids": ";".join(sorted(set(active_ids))) if active_ids else "",
            })

    # --- manual checks for this run ---
    operators = [f"OP-{i:03d}" for i in range(1, 13)]
    for sid in manual_stations:
        m = 20
        while m < SHIFT_MINUTES:
            ts = shift_start + timedelta(minutes=m)
            result, notes = "Pass", "Routine check, within spec."
            for ev, hop in station_events[sid]:
                if hop >= 1 or (hop == 0 and ev["event_type"] == "sensorless_drift"):
                    if abs(ev["peak_minute"] - m) <= 12 and ev["event_type"] in ("defect_propagation", "sensorless_drift"):
                        result = "Fail" if ev["event_type"] == "defect_propagation" else "Flagged"
                        notes = f"Anomaly consistent with {ev['event_id']} (origin {ev['origin_station_id']})."
            all_manual_checks.append({
                "run_id": run_id, "station_id": sid, "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "minute_index": m, "operator_id": rng.choice(operators), "result": result, "notes": notes,
            })
            m += 20

    # --- vehicles for this run ---
    main_line_only = stations_df[stations_df.station_id != "ENG01"].sort_values("sequence_order")
    cum_offset_sec = {}
    running = 0.0
    for _, row in main_line_only.iterrows():
        running += row["baseline_cycle_time_sec"]
        cum_offset_sec[row["station_id"]] = running

    n_vehicles = int((SHIFT_MINUTES * 60) / LINE_ENTRY_INTERVAL_SEC)
    variants = rng.choice(["Sedan", "SUV", "EV"], size=n_vehicles, p=[0.5, 0.35, 0.15])

    for i in range(n_vehicles):
        entry_sec = max(0.0, i * LINE_ENTRY_INTERVAL_SEC + rng.normal(0, 5))
        entry_time = shift_start + timedelta(seconds=entry_sec)
        entry_minute = entry_sec / 60.0
        vin = f"VIN-{vin_counter}"; vin_counter += 1
        variant = variants[i]
        variant_mult = {"Sedan": 1.0, "SUV": 1.05, "EV": 1.12}[variant]

        def arrival_minute(sid):
            return entry_minute + (cum_offset_sec.get(sid, 0.0) * variant_mult) / 60.0

        flags = {"bottleneck_impacted": False, "defect_risk": False,
                 "sensorless_drift_flagged": False, "machine_failure_impacted": False}
        affected = []
        for ev in events:
            origin = ev["origin_station_id"]
            arr = arrival_minute(origin) if origin != "ENG01" else arrival_minute("S23")
            if ev["start_minute"] <= arr <= ev["resolved_minute"]:
                key = {"bottleneck": "bottleneck_impacted", "defect_propagation": "defect_risk",
                       "sensorless_drift": "sensorless_drift_flagged",
                       "machine_failure": "machine_failure_impacted"}[ev["event_type"]]
                flags[key] = True
                affected.append(ev["event_id"])

        flagged_for_inspection = flags["defect_risk"] or flags["sensorless_drift_flagged"] or flags["machine_failure_impacted"]

        all_vehicles.append({
            "run_id": run_id, "vin": vin, "model_variant": variant,
            "line_entry_time": entry_time.strftime("%Y-%m-%d %H:%M:%S"),
            "line_entry_minute": round(entry_minute, 2),
            **flags,
            "flagged_for_inspection": flagged_for_inspection,
            "affected_events": ";".join(affected),
        })

    run_summaries.append({
        "run_id": run_id,
        "shift_start": shift_start.strftime("%Y-%m-%d %H:%M:%S"),
        "n_events": len(events),
        "event_types_present": ";".join(sorted(set(e["event_type"] for e in events))) if events else "",
        "had_scheduled_maintenance": maint is not None,
        "n_vehicles": n_vehicles,
    })

# ---------------------------------------------------------------------------
# WRITE OUTPUTS
# ---------------------------------------------------------------------------
pd.DataFrame(run_summaries).to_csv("production_runs.csv", index=False)
pd.DataFrame(all_events).to_csv("events_ground_truth.csv", index=False)
pd.DataFrame(all_maint).to_csv("maintenance_windows.csv", index=False)
pd.DataFrame(all_timeseries).to_csv("sensor_timeseries.csv", index=False)
pd.DataFrame(all_manual_checks).to_csv("manual_checks.csv", index=False)
pd.DataFrame(all_vehicles).to_csv("vehicles.csv", index=False)

print("Runs:", N_RUNS)
print("Timeseries rows:", len(all_timeseries))
print("Events:", len(all_events))
print("Maintenance windows:", len(all_maint))
print("Manual checks:", len(all_manual_checks))
print("Vehicles:", len(all_vehicles))
