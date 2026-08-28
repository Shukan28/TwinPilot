"""
TwinPilot: Outcome & Learning Demo
====================================
Runs the two validated test scenarios through the full integrated pipeline,
then feeds the approved intervention into the Outcome & Learning module.

For each scenario prints:
  - TwinPilot Decision Report
  - Outcome & Learning Report (predicted vs. actual, accuracy, verdict)
  - Running intervention ledger across all logged events
"""

import pandas as pd
from run_scenario_pipeline import TwinPilotPipeline
from outcome_learning import record_intervention_outcome, print_outcome_report

DATASET_DIR = r"twinpilot_dataset_extracted\twinpilot_dataset"

def print_ledger(log_path="intervention_audit_log.json"):
    """Print a compact summary table of all logged interventions."""
    import json, os
    if not os.path.exists(log_path):
        return
    with open(log_path) as f:
        records = json.load(f)
    if not records:
        return

    print("=" * 80)
    print("TWINPILOT INTERVENTION LEDGER  (all logged outcomes)")
    print("=" * 80)
    rows = []
    for r in records:
        pred = r["twinpilot_prediction"]
        obs  = r.get("observed_outcome", {})
        acc  = r.get("accuracy", {})
        rows.append({
            "Event":            r["event_id"],
            "Station":          r["before_state"]["station_id"],
            "Intervention":     pred["recommended_option"],
            "Pred Tput":        f"{pred['tput_pct']:+.1f}%",
            "Obs Tput":         f"{obs.get('observed_tput_pct', float('nan')):+.1f}%" if obs.get("observed_tput_pct") is not None else "N/A",
            "Overall Acc":      f"{acc.get('overall_accuracy_pct', 0):.1f}%" if acc.get("overall_accuracy_pct") is not None else "N/A",
            "Successful":       "YES" if acc.get("is_successful") else "NO",
            "Dir Correct":      "YES" if acc.get("is_directionally_correct") else "NO",
        })
    df = pd.DataFrame(rows)
    print(df.to_markdown(index=False))
    print()


def main():
    # Delete old log to start fresh each demo run
    import os
    if os.path.exists("intervention_audit_log.json"):
        os.remove("intervention_audit_log.json")

    print("[Initializing TwinPilot End-to-End Pipeline...]\n")
    pipeline = TwinPilotPipeline(DATASET_DIR)

    # Load raw sensor data for post-intervention telemetry reads
    sensor_df = pipeline.defect_service.sensor_df_with_preds.copy()

    # ---------------------------------------------------------------
    # Scenario 1: RUN024-EVT01 — S03 High Queue + High Defect Risk
    # ---------------------------------------------------------------
    print("\n" + "#" * 80)
    print("# SCENARIO 1: RUN024-EVT01 (S03 — Cycle-Time Drift / High Queue + High Defect)")
    print("#" * 80)
    r1 = pipeline.run_scenario(
        run_id="RUN-024",
        minute_index=143,
        target_station="S03",
        event_id="RUN024-EVT01",
    )

    # Print decision report
    opts = r1["options"]
    rec  = r1["recommended_option"]
    print("\n--- TwinPilot Decision ---")
    print(f"  Anomaly:        S03 | CT {r1['ct']:.1f}s | Queue {r1['queue']:.0f} | Defect {r1['defect_prob']*100:.1f}%")
    print(f"  Root Cause:     {r1['root_cause']}  |  Path: {' -> '.join(r1['propagation_path'])}")
    print(f"  At-Risk VINs:   {r1['at_risk_vins_count']}")
    print(f"  Recommended:    {rec} ({opts[rec]['name']}) @ {r1['confidence']}% confidence")
    for k, v in opts.items():
        tag = " <-- AI RECOMMENDED" if k == rec else ""
        print(f"    {k}: Tput {v['tput_pct']:+.1f}%  Queue {v['queue_change']:+.1f}  Defect {v['defect_risk_change']:+.1f}%  Net ${v['financial_impact']:+.0f}{tag}")

    # Operator approves
    rec1 = record_intervention_outcome(r1, operator_action="approve", sensor_df=sensor_df, observation_window=20)
    print_outcome_report(rec1)

    # ---------------------------------------------------------------
    # Scenario 2: RUN025-EVT02 — S16 Machine Failure / High Queue
    # ---------------------------------------------------------------
    print("\n" + "#" * 80)
    print("# SCENARIO 2: RUN025-EVT02 (S16 — Machine Failure / Queue Backlog)")
    print("#" * 80)
    r2 = pipeline.run_scenario(
        run_id="RUN-025",
        minute_index=93,
        target_station="S16",
        event_id="RUN025-EVT02",
    )

    opts2 = r2["options"]
    rec2  = r2["recommended_option"]
    print("\n--- TwinPilot Decision ---")
    print(f"  Anomaly:        S16 | CT {r2['ct']:.1f}s | Queue {r2['queue']:.0f} | Defect {r2['defect_prob']*100:.1f}%")
    dz_str = ", ".join([f"{row['target_station']} ({row['dz_prob']*100:.1f}%)" for _, row in r2["dz_flagged"].iterrows()]) if not r2["dz_flagged"].empty else "None"
    print(f"  Dark Zone:      {dz_str}")
    print(f"  Root Cause:     {r2['root_cause']}  |  Path: {' -> '.join(r2['propagation_path'])}")
    print(f"  At-Risk VINs:   {r2['at_risk_vins_count']}")
    print(f"  Recommended:    {rec2} ({opts2[rec2]['name']}) @ {r2['confidence']}% confidence")
    for k, v in opts2.items():
        tag = " <-- AI RECOMMENDED" if k == rec2 else ""
        print(f"    {k}: Tput {v['tput_pct']:+.1f}%  Queue {v['queue_change']:+.1f}  Defect {v['defect_risk_change']:+.1f}%  Net ${v['financial_impact']:+.0f}{tag}")

    # Operator approves
    rec2_out = record_intervention_outcome(r2, operator_action="approve", sensor_df=sensor_df, observation_window=20)
    print_outcome_report(rec2_out)

    # ---------------------------------------------------------------
    # Intervention Ledger
    # ---------------------------------------------------------------
    print_ledger()


if __name__ == "__main__":
    main()
