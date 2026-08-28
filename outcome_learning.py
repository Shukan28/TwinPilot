"""
TwinPilot: Outcome & Learning Module
=====================================
For every approved intervention, records:
  1. Factory state before intervention
  2. TwinPilot prediction (expected throughput, queue, defect risk)
  3. Chosen intervention + human decision
  4. Observed outcome  (read from actual post-intervention telemetry)
  5. Prediction error  (predicted vs. observed)
  6. Success verdict   (was the recommendation beneficial?)
  7. Feedback entry    (appended to persistent audit log JSON)

Does NOT retrain any model or change any threshold.
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import json
import os
import math
from datetime import datetime, timezone
import pandas as pd
# pyrefly: ignore [missing-import]
import numpy as np


AUDIT_LOG_PATH = "intervention_audit_log.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_audit_log():
    if os.path.exists(AUDIT_LOG_PATH):
        with open(AUDIT_LOG_PATH, "r") as f:
            return json.load(f)
    return []


def _save_audit_log(records):
    with open(AUDIT_LOG_PATH, "w") as f:
        json.dump(records, f, indent=2, default=str)


def _uph_from_ct(cycle_time_sec: float) -> float:
    """Units-per-hour from cycle time in seconds."""
    if cycle_time_sec <= 0:
        return 0.0
    return 3600.0 / cycle_time_sec


# ---------------------------------------------------------------------------
# Core: read actual post-intervention telemetry
# ---------------------------------------------------------------------------

def read_observed_outcome(
    sensor_df: pd.DataFrame,
    run_id: str,
    station_id: str,
    intervention_minute: int,
    observation_window: int = 20,
) -> dict:
    """
    Reads the actual factory state ~observation_window minutes after the
    intervention minute and computes observed changes vs. the pre-intervention
    baseline at the same station.

    Returns a dict with observed_tput_pct, observed_queue_change,
    observed_defect_risk_change (NaN if the station has no defect_prob column),
    and the raw pre/post row snapshots.
    """
    station_mask = sensor_df["station_id"] == station_id
    run_mask = sensor_df["run_id"] == run_id

    pre_rows = sensor_df[run_mask & station_mask &
                         (sensor_df["minute_index"] == intervention_minute)]
    post_rows = sensor_df[run_mask & station_mask &
                          (sensor_df["minute_index"] == intervention_minute + observation_window)]

    # Fall back to nearest available minute if exact row missing
    if pre_rows.empty:
        candidates = sensor_df[run_mask & station_mask &
                                (sensor_df["minute_index"] <= intervention_minute)]
        pre_rows = candidates.tail(1)
    if post_rows.empty:
        candidates = sensor_df[run_mask & station_mask &
                                (sensor_df["minute_index"] >= intervention_minute + observation_window)]
        post_rows = candidates.head(1)

    if pre_rows.empty or post_rows.empty:
        return {"error": "telemetry unavailable"}

    pre = pre_rows.iloc[0]
    post = post_rows.iloc[0]

    pre_ct = float(pre.get("cycle_time_sec", 0) or 0)
    post_ct = float(post.get("cycle_time_sec", 0) or 0)
    pre_uph = _uph_from_ct(pre_ct)
    post_uph = _uph_from_ct(post_ct)
    tput_pct = ((post_uph - pre_uph) / pre_uph * 100) if pre_uph > 0 else float("nan")

    pre_q = float(pre.get("queue_length", 0) or 0)
    post_q = float(post.get("queue_length", 0) or 0)
    queue_change = post_q - pre_q

    defect_change = float("nan")
    if "defect_prob" in sensor_df.columns:
        pre_d = float(pre.get("defect_prob", float("nan")) or float("nan"))
        post_d = float(post.get("defect_prob", float("nan")) or float("nan"))
        if not (math.isnan(pre_d) or math.isnan(post_d)):
            defect_change = (post_d - pre_d) * 100.0  # in percentage points

    return {
        "pre_ct": round(pre_ct, 2),
        "post_ct": round(post_ct, 2),
        "pre_queue": round(pre_q, 1),
        "post_queue": round(post_q, 1),
        "pre_minute": int(pre.get("minute_index", intervention_minute)),
        "post_minute": int(post.get("minute_index", intervention_minute + observation_window)),
        "observed_tput_pct": round(tput_pct, 2) if not math.isnan(tput_pct) else None,
        "observed_queue_change": round(queue_change, 1),
        "observed_defect_risk_change": round(defect_change, 2) if not math.isnan(defect_change) else None,
    }


# ---------------------------------------------------------------------------
# Core: compute prediction error & success verdict
# ---------------------------------------------------------------------------

def compute_prediction_accuracy(predicted: dict, observed: dict) -> dict:
    """
    Given the predicted and observed outcome dicts, returns:
      - tput_accuracy_pct  (0–100; None if observed is nan)
      - queue_accuracy_pct
      - defect_accuracy_pct
      - overall_accuracy_pct  (mean of available dimensions)
      - is_directionally_correct  (did predicted & observed move in the same direction?)
      - is_successful             (outcome better than doing nothing, i.e. net positive)
      - success_reason
    """
    results = {}

    def _accuracy(pred, obs):
        """Accuracy as 100% minus relative error, clamped to [0, 100]."""
        if pred is None or obs is None:
            return None
        if abs(pred) < 0.01 and abs(obs) < 0.01:
            return 100.0
        denom = max(abs(pred), abs(obs), 0.01)
        return max(0.0, 100.0 - abs(pred - obs) / denom * 100.0)

    tput_acc = _accuracy(predicted.get("tput_pct"), observed.get("observed_tput_pct"))
    queue_acc = _accuracy(predicted.get("queue_change"), observed.get("observed_queue_change"))
    defect_acc = _accuracy(predicted.get("defect_risk_change"), observed.get("observed_defect_risk_change"))

    results["tput_accuracy_pct"] = round(tput_acc, 1) if tput_acc is not None else None
    results["queue_accuracy_pct"] = round(queue_acc, 1) if queue_acc is not None else None
    results["defect_accuracy_pct"] = round(defect_acc, 1) if defect_acc is not None else None

    available = [v for v in [tput_acc, queue_acc, defect_acc] if v is not None]
    results["overall_accuracy_pct"] = round(float(np.mean(available)), 1) if available else None

    # Directional correctness
    pred_tput = predicted.get("tput_pct") or 0
    obs_tput = observed.get("observed_tput_pct") or 0
    pred_q = predicted.get("queue_change") or 0
    obs_q = observed.get("observed_queue_change") or 0

    def _same_dir(a, b):
        return (a >= 0 and b >= 0) or (a <= 0 and b <= 0)

    dir_checks = [_same_dir(pred_tput, obs_tput), _same_dir(pred_q, obs_q)]
    results["is_directionally_correct"] = all(dir_checks)

    # Success: net beneficial = throughput improved OR queue reduced OR defect risk reduced
    obs_defect = observed.get("observed_defect_risk_change")
    beneficial = (
        (obs_tput is not None and obs_tput > 0) or
        (obs_q < 0) or
        (obs_defect is not None and obs_defect < 0)
    )
    results["is_successful"] = beneficial

    if results["is_successful"] and results["is_directionally_correct"]:
        results["feedback"] = "Recommendation validated — prediction and outcome aligned."
    elif results["is_successful"] and not results["is_directionally_correct"]:
        results["feedback"] = "Outcome successful but direction mis-predicted — model underestimated scale."
    elif not results["is_successful"] and results["is_directionally_correct"]:
        results["feedback"] = "Direction correct but outcome not net-positive — external factors dampened effect."
    else:
        results["feedback"] = "Recommendation not validated — outcome diverged from prediction."

    return results


# ---------------------------------------------------------------------------
# Public API: record_intervention_outcome
# ---------------------------------------------------------------------------

def record_intervention_outcome(
    pipeline_result: dict,
    operator_action: str,
    sensor_df: pd.DataFrame,
    observation_window: int = 20,
) -> dict:
    """
    Main entry point.  Given a pipeline result dict (from TwinPilotPipeline.run_scenario)
    and the operator's decision, reads actual post-intervention telemetry, computes
    prediction accuracy, and appends a structured record to the audit log.

    Returns the full outcome record.
    """
    run_id = pipeline_result["run_id"]
    minute_index = pipeline_result["minute_index"]
    station = pipeline_result["station"]
    event_id = pipeline_result.get("event_id", "unknown")
    chosen_opt = pipeline_result["recommended_option"]
    opts = pipeline_result["options"]
    predicted = opts[chosen_opt]

    # --- Before state ---
    before_state = {
        "station_id": station,
        "cycle_time_sec": pipeline_result["ct"],
        "queue_length": pipeline_result["queue"],
        "defect_prob": pipeline_result["defect_prob"],
        "bottleneck_prob": pipeline_result["bottleneck_prob"],
        "root_cause_station": pipeline_result["root_cause"],
        "propagation_path": pipeline_result["propagation_path"],
        "at_risk_vins": pipeline_result["at_risk_vins_count"],
    }

    # --- Prediction ---
    prediction = {
        "recommended_option": chosen_opt,
        "option_name": predicted["name"],
        "tput_pct": predicted["tput_pct"],
        "queue_change": predicted["queue_change"],
        "defect_risk_change": predicted["defect_risk_change"],
        "financial_impact": predicted["financial_impact"],
        "confidence_pct": pipeline_result["confidence"],
    }

    # --- Human decision ---
    human_decision = {
        "operator_action": operator_action,
        "accepted_recommendation": operator_action.lower() == "approve",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # --- Observed outcome ---
    observed = read_observed_outcome(sensor_df, run_id, station, minute_index, observation_window)

    # --- Accuracy & verdict ---
    accuracy = {}
    if "error" not in observed:
        accuracy = compute_prediction_accuracy(prediction, observed)
    else:
        accuracy = {"error": "Cannot compute accuracy — post-intervention telemetry unavailable."}

    # --- Assemble full record ---
    record = {
        "event_id": event_id,
        "run_id": run_id,
        "minute_index": minute_index,
        "observation_window_min": observation_window,
        "before_state": before_state,
        "twinpilot_prediction": prediction,
        "human_decision": human_decision,
        "observed_outcome": observed,
        "accuracy": accuracy,
    }

    # --- Append to persistent audit log ---
    log = _load_audit_log()
    log.append(record)
    _save_audit_log(log)

    return record


# ---------------------------------------------------------------------------
# Pretty printer
# ---------------------------------------------------------------------------

def print_outcome_report(record: dict):
    """Prints a human-readable TwinPilot Outcome Report for a single record."""
    pred = record["twinpilot_prediction"]
    obs = record["observed_outcome"]
    acc = record["accuracy"]
    hd = record["human_decision"]
    bs = record["before_state"]
    ow = record["observation_window_min"]

    success_marker = "SUCCESS" if acc.get("is_successful") else "NOT VALIDATED"
    validated_marker = "Recommendation validated" if acc.get("is_directionally_correct") else "Direction mis-predicted"

    print("=" * 80)
    print("TWINPILOT OUTCOME & LEARNING REPORT")
    print(f"Event: {record['event_id']}  |  Run: {record['run_id']}  |  Minute: {record['minute_index']}")
    print("=" * 80)

    print("\n[1. FACTORY STATE BEFORE INTERVENTION]")
    print(f"  Station:           {bs['station_id']}  |  CT: {bs['cycle_time_sec']}s  |  Queue: {bs['queue_length']}")
    print(f"  Defect Prob:       {bs['defect_prob']*100:.1f}%  |  Bottleneck Prob: {bs['bottleneck_prob']*100:.1f}%")
    print(f"  Root Cause:        {bs['root_cause_station']}  |  Path: {' -> '.join(bs['propagation_path'])}")
    print(f"  At-Risk VINs:      {bs['at_risk_vins']}")

    print("\n[2. TWINPILOT PREDICTION]")
    print(f"  Recommended:       {pred['recommended_option']} — {pred['option_name']}")
    print(f"  Predicted Impact:  Throughput {pred['tput_pct']:+.1f}%  |  Queue {pred['queue_change']:+.1f}  |  Defect Risk {pred['defect_risk_change']:+.1f}%")
    print(f"  Net Fin. Impact:   ${pred['financial_impact']:+.0f}")
    print(f"  Confidence:        {pred['confidence_pct']}%")

    print("\n[3. HUMAN DECISION]")
    decision_word = "APPROVED" if hd["accepted_recommendation"] else "REJECTED"
    print(f"  Operator Action:   {decision_word} — {hd['operator_action']}")
    print(f"  Timestamp:         {hd['timestamp']}")

    print(f"\n[4. OBSERVED OUTCOME  (+{ow} min after intervention)]")
    if "error" in obs:
        print(f"  ERROR: {obs['error']}")
    else:
        obs_tput = obs.get("observed_tput_pct")
        obs_q = obs.get("observed_queue_change")
        obs_d = obs.get("observed_defect_risk_change")
        print(f"  Actual CT:         {obs['pre_ct']}s  ->  {obs['post_ct']}s")
        print(f"  Actual Queue:      {obs['pre_queue']}  ->  {obs['post_queue']}")
        print(f"  Observed Tput:     {f'{obs_tput:+.1f}%' if obs_tput is not None else 'N/A'}")
        obs_q_str = f"{obs_q:+.1f}" if obs_q is not None else "N/A"
        print(f"  Observed Queue Ch: {obs_q_str}")
        obs_d_str = f"{obs_d:+.1f}%" if obs_d is not None else "N/A"
        print(f"  Observed Defect Ch:{obs_d_str}")

    print("\n[5. PREDICTION ACCURACY & FEEDBACK]")
    if "error" in acc:
        print(f"  ERROR: {acc['error']}")
    else:
        def _acc_str(v):
            return f"{v:.1f}%" if v is not None else "N/A"

        print(f"  Throughput Accuracy: {_acc_str(acc.get('tput_accuracy_pct'))}  "
              f"|  Predicted {pred['tput_pct']:+.1f}%  vs  Observed {obs.get('observed_tput_pct', 0):+.1f}%")
        print(f"  Queue Accuracy:      {_acc_str(acc.get('queue_accuracy_pct'))}  "
              f"|  Predicted {pred['queue_change']:+.1f}  vs  Observed {obs.get('observed_queue_change', 0):+.1f}")
        print(f"  Defect Accuracy:     {_acc_str(acc.get('defect_accuracy_pct'))}")
        print(f"  Overall Accuracy:    {_acc_str(acc.get('overall_accuracy_pct'))}")
        print(f"  Direction Correct:   {'Yes' if acc.get('is_directionally_correct') else 'No'}")
        print(f"  Outcome Verdict:     {success_marker}")
        print(f"  Feedback:            {acc.get('feedback', '')}")
    print("=" * 80 + "\n")
