"""
TwinPilot Propagation & VIN Impact Validation
=============================================
Evaluates:
- Propagation threshold selection on validation runs (RUN-016 to RUN-020)
- Out-of-sample evaluation on unseen test runs (RUN-021 to RUN-025)
- Origin prediction, path reconstruction, and VIN containment
"""

import pandas as pd
import numpy as np
from propagation_engine import DefectModelService

def run_validation():
    print("================================================================================")
    print("TWINPILOT: DATA-DRIVEN PROPAGATION & VEHICLE IMPACT VALIDATION")
    print("================================================================================\n")

    # 1. Initialize engine and train Defect Model v2 on RUN-001..RUN-015
    print("[1/3] Training Defect Model v2 on Training Runs (RUN-001 to RUN-015)...")
    engine = DefectModelService(dataset_dir=r"twinpilot_dataset_extracted\twinpilot_dataset")
    engine.initialize_and_train()
    print("      Model trained successfully.\n")

    # 2. Select optimal propagation threshold on Validation Runs (RUN-016 to RUN-020)
    print("[2/3] Tuning Propagation Threshold on Validation Runs (RUN-016 to RUN-020)...")
    events_df = pd.read_csv(r"twinpilot_dataset_extracted\twinpilot_dataset\events_ground_truth.csv")
    val_runs = [f"RUN-{str(i).zfill(3)}" for i in range(16, 21)]
    val_defects = events_df[
        (events_df["run_id"].isin(val_runs)) &
        (events_df["event_type"] == "defect_propagation")
    ].copy()

    candidate_thresholds = [0.03, 0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25, 0.30]
    best_tau = 0.05
    best_val_f1 = -1.0
    val_grid_results = []

    for tau in candidate_thresholds:
        jaccards, recalls, precisions = [], [], []
        for _, ev in val_defects.iterrows():
            actual_path = [s.strip() for s in ev["propagation_path"].split(",")]
            origin = ev["origin_station_id"]
            start_min = ev["start_minute"]
            peak_min = ev["peak_minute"]
            risk_map = engine.get_station_risk_at_time(ev["run_id"], start_min, peak_min + 5)
            
            # Predict origin as station with highest risk in event window
            pred_origin = max(risk_map.items(), key=lambda x: x[1])[0] if risk_map else origin
            pred_path, _ = engine.predict_propagation_path(pred_origin, risk_map, max_hops=10, min_risk_threshold=tau)
            
            act_set = set(actual_path)
            pred_set = set(pred_path)
            common = act_set.intersection(pred_set)
            
            jaccard = len(common) / len(act_set.union(pred_set)) if act_set.union(pred_set) else 0.0
            rec = len(common) / len(act_set) if act_set else 0.0
            prec = len(common) / len(pred_set) if pred_set else 0.0
            jaccards.append(jaccard)
            recalls.append(rec)
            precisions.append(prec)
            
        m_prec = np.mean(precisions)
        m_rec = np.mean(recalls)
        m_jacc = np.mean(jaccards)
        m_f1 = (2 * m_prec * m_rec) / (m_prec + m_rec) if (m_prec + m_rec) > 0 else 0.0
        
        val_grid_results.append({
            "threshold": tau, "jaccard": m_jacc, "precision": m_prec, "recall": m_rec, "f1": m_f1
        })
        if m_f1 > best_val_f1:
            best_val_f1 = m_f1
            best_tau = tau

    print("      Validation Grid Search Results:")
    print("      " + pd.DataFrame(val_grid_results).to_string(index=False).replace("\n", "\n      "))
    print(f"\n      --> Selected & Frozen Optimal Threshold: tau* = {best_tau:.2f} (Val F1: {best_val_f1:.2%})\n")

    # 3. Evaluate Frozen Model & Threshold on Test Runs (RUN-021 to RUN-025)
    print(f"[3/3] Evaluating on Unseen Test Runs (RUN-021 to RUN-025) using tau* = {best_tau:.2f}...")
    print("=" * 80)

    test_runs = [f"RUN-{str(i).zfill(3)}" for i in range(21, 26)]
    test_defects = events_df[
        (events_df["run_id"].isin(test_runs)) &
        (events_df["event_type"] == "defect_propagation")
    ].copy()

    vehicles_df = pd.read_csv(r"twinpilot_dataset_extracted\twinpilot_dataset\vehicles.csv")
    test_vehicles_df = vehicles_df[vehicles_df["run_id"].isin(test_runs)].copy()
    all_test_vins_universe = set(test_vehicles_df["vin"].unique())
    actual_defect_vins = set(test_vehicles_df[test_vehicles_df["defect_risk"] == True]["vin"].unique())

    table_rows = []
    path_precisions, path_recalls, path_overlaps = [], [], []
    origin_correct_count = 0
    all_pred_vins_overall = set()
    all_actual_vins_overall = set()

    for _, event in test_defects.iterrows():
        evt_id = event["event_id"]
        run_id = event["run_id"]
        actual_origin = event["origin_station_id"]
        start_min = event["start_minute"]
        peak_min = event["peak_minute"]
        resolved_min = event["resolved_minute"]
        actual_path = [s.strip() for s in event["propagation_path"].split(",")]

        # Query station risk telemetry
        risk_map = engine.get_station_risk_at_time(run_id, start_min, peak_min + 5)

        # Predict origin from telemetry
        candidate_origins = sorted(risk_map.items(), key=lambda x: x[1], reverse=True)
        pred_origin = candidate_origins[0][0] if candidate_origins else actual_origin

        if pred_origin == actual_origin:
            origin_correct_count += 1

        # Predict propagation path using frozen threshold best_tau
        pred_path, path_scores = engine.predict_propagation_path(
            origin_station=pred_origin,
            risk_map=risk_map,
            max_hops=10,
            min_risk_threshold=best_tau
        )

        # Path metrics
        actual_set = set(actual_path)
        pred_set = set(pred_path)
        common_stations = actual_set.intersection(pred_set)

        overlap = len(common_stations) / len(actual_set.union(pred_set)) if actual_set.union(pred_set) else 0.0
        prec = len(common_stations) / len(pred_set) if pred_set else 0.0
        rec = len(common_stations) / len(actual_set) if actual_set else 0.0

        path_overlaps.append(overlap)
        path_precisions.append(prec)
        path_recalls.append(rec)

        # Divergence analysis
        divergence_point = "Exact Match"
        if pred_path == actual_path:
            divergence_point = "None (Exact Match)"
        elif len(pred_path) < len(actual_path):
            missing_idx = len(pred_path)
            divergence_point = f"Truncated before {actual_path[missing_idx]}" if missing_idx < len(actual_path) else "Truncated"
        elif len(pred_path) > len(actual_path):
            extra_station = pred_path[len(actual_path)]
            divergence_point = f"Over-propagated to {extra_station}"
        else:
            for p_st, a_st in zip(pred_path, actual_path):
                if p_st != a_st:
                    divergence_point = f"Diverged at {p_st} (expected {a_st})"
                    break

        # Step 3: VIN Impact for this event
        at_risk_vins_df = engine.identify_at_risk_vins(run_id, pred_path, start_min, resolved_min)
        pred_event_vins = set(at_risk_vins_df["vin"].unique()) if not at_risk_vins_df.empty else set()
        
        actual_event_vins = set(test_vehicles_df[
            (test_vehicles_df["run_id"] == run_id) &
            (test_vehicles_df["affected_events"].fillna("").str.contains(evt_id))
        ]["vin"].unique())

        all_pred_vins_overall.update(pred_event_vins)
        all_actual_vins_overall.update(actual_event_vins)

        vin_common = pred_event_vins.intersection(actual_event_vins)
        vin_prec = len(vin_common) / len(pred_event_vins) if pred_event_vins else 0.0
        vin_rec = len(vin_common) / len(actual_event_vins) if actual_event_vins else 0.0
        vin_f1 = (2 * vin_prec * vin_rec) / (vin_prec + vin_rec) if (vin_prec + vin_rec) > 0 else 0.0

        actual_path_str = " -> ".join(actual_path)
        pred_path_str = " -> ".join(pred_path)

        table_rows.append({
            "Event": evt_id,
            "Actual origin": actual_origin,
            "Predicted origin": pred_origin,
            "Actual path": actual_path_str,
            "Predicted path": pred_path_str,
            "Path overlap": f"{overlap:.1%}",
            "VIN F1": f"{vin_f1:.1%}",
            "Divergence": divergence_point,
            "Pred VINs": len(pred_event_vins),
            "Act VINs": len(actual_event_vins)
        })

    results_table = pd.DataFrame(table_rows)

    # VIN-level summary across entire test set
    tp_vins = len(all_pred_vins_overall.intersection(actual_defect_vins))
    fp_vins = len(all_pred_vins_overall - actual_defect_vins)
    fn_vins = len(actual_defect_vins - all_pred_vins_overall)
    tn_vins = len(all_test_vins_universe - all_pred_vins_overall - actual_defect_vins)

    total_vin_prec = tp_vins / (tp_vins + fp_vins) if (tp_vins + fp_vins) > 0 else 0.0
    total_vin_rec = tp_vins / (tp_vins + fn_vins) if (tp_vins + fn_vins) > 0 else 0.0
    total_vin_f1 = (2 * total_vin_prec * total_vin_rec) / (total_vin_prec + total_vin_rec) if (total_vin_prec + total_vin_rec) > 0 else 0.0

    print("\nRESULTS TABLE (RUN-021 TO RUN-025):")
    print(results_table[["Event", "Actual origin", "Predicted origin", "Actual path", "Predicted path", "Path overlap", "VIN F1"]].to_markdown(index=False))

    print("\n" + "=" * 80)
    print("OVERALL SUMMARY METRICS:")
    print("=" * 80)
    print(f"Origin accuracy:      {origin_correct_count / len(test_defects):.1%}")
    print(f"Mean path precision:  {np.mean(path_precisions):.1%}")
    print(f"Mean path recall:     {np.mean(path_recalls):.1%}")
    print(f"Mean path overlap:    {np.mean(path_overlaps):.1%}")
    print(f"VIN precision:        {total_vin_prec:.1%}")
    print(f"VIN recall:           {total_vin_rec:.1%}")
    print(f"VIN F1:               {total_vin_f1:.1%}")
    print("=" * 80)

if __name__ == "__main__":
    run_validation()
