"""
Test and Tune Earliest Origin Scoring
"""
import pandas as pd
import numpy as np
from propagation_engine import DefectModelService

def evaluate_earliest_origin():
    engine = DefectModelService(dataset_dir=r"twinpilot_dataset_extracted\twinpilot_dataset")
    engine.initialize_and_train()
    
    events_df = pd.read_csv(r"twinpilot_dataset_extracted\twinpilot_dataset\events_ground_truth.csv")
    stations_df = pd.read_csv(r"twinpilot_dataset_extracted\twinpilot_dataset\stations_master.csv")
    vehicles_df = pd.read_csv(r"twinpilot_dataset_extracted\twinpilot_dataset\vehicles.csv")

    val_runs = [f"RUN-{str(i).zfill(3)}" for i in range(16, 21)]
    test_runs = [f"RUN-{str(i).zfill(3)}" for i in range(21, 26)]
    
    val_defects = events_df[(events_df["run_id"].isin(val_runs)) & (events_df["event_type"] == "defect_propagation")]
    test_defects = events_df[(events_df["run_id"].isin(test_runs)) & (events_df["event_type"] == "defect_propagation")]

    # Function to get earliest origin
    # An earliest origin is defined by:
    # 1. Filter stations in the run that cross an anomaly threshold tau_alert in the event detection window [start_min, peak_min + 5].
    # 2. Sort candidate stations by the minute they first cross tau_alert (earliest detection time).
    # 3. If there is a tie for earliest minute, pick the candidate with highest initial slope / risk or upstream position.
    
    print("=================================================================")
    print("EARLIEST ORIGIN TUNING ON VALIDATION SET (RUN-016 TO RUN-020)")
    print("=================================================================")
    
    candidate_alert_thresholds = [0.05, 0.08, 0.10, 0.12, 0.15, 0.20]
    best_alert_tau = 0.10
    best_val_origin_acc = -1.0
    
    for alert_tau in candidate_alert_thresholds:
        correct = 0
        for _, ev in val_defects.iterrows():
            run_id = ev["run_id"]
            start_min = ev["start_minute"]
            peak_min = ev["peak_minute"]
            true_origin = ev["origin_station_id"]
            
            sub = engine.sensor_df_with_preds[
                (engine.sensor_df_with_preds["run_id"] == run_id) &
                (engine.sensor_df_with_preds["minute_index"] >= start_min) &
                (engine.sensor_df_with_preds["minute_index"] <= peak_min + 5)
            ].copy()
            
            # Find stations crossing alert_tau
            anom = sub[sub["defect_prob"] >= alert_tau]
            if not anom.empty:
                # Group by station to find earliest alert minute and early integrated risk
                earliest_mins = anom.groupby("station_id")["minute_index"].min().to_dict()
                min_minute = min(earliest_mins.values())
                # Stations that flagged within 2 minutes of the very first alert
                lead_stations = [s for s, m in earliest_mins.items() if m <= min_minute + 2]
                
                # Rank by earliest time, then by maximum early risk
                lead_sub = anom[anom["station_id"].isin(lead_stations)]
                pred_origin = lead_sub.groupby("station_id")["defect_prob"].max().idxmax()
            else:
                pred_origin = sub.groupby("station_id")["defect_prob"].max().idxmax()
                
            if pred_origin == true_origin:
                correct += 1
                
        acc = correct / len(val_defects)
        print(f"Alert Threshold: {alert_tau:.2f} -> Validation Origin Accuracy: {acc:.1%} ({correct}/{len(val_defects)})")
        if acc > best_val_origin_acc:
            best_val_origin_acc = acc
            best_alert_tau = alert_tau
            
    print(f"\n--> Selected Earliest Alert Threshold: tau_alert = {best_alert_tau:.2f} (Val Origin Acc: {best_val_origin_acc:.1%})\n")
    
    # Evaluate on Test Runs (RUN-021 to RUN-025)
    print("=================================================================")
    print("EVALUATING EARLIEST ORIGIN ON UNTOUCHED TEST SET (RUN-021 TO RUN-025)")
    print("=================================================================")
    
    stopping_tau = 0.02  # frozen from previous step
    test_vehicles_df = vehicles_df[vehicles_df["run_id"].isin(test_runs)].copy()
    actual_defect_vins_universe = set(test_vehicles_df[test_vehicles_df["defect_risk"] == True]["vin"].unique())
    all_test_vins_universe = set(test_vehicles_df["vin"].unique())

    test_rows = []
    origin_matches = 0
    all_pred_vins = set()
    jaccards, precisions, recalls = [], [], []

    for _, ev in test_defects.iterrows():
        evt_id = ev["event_id"]
        run_id = ev["run_id"]
        start_min = ev["start_minute"]
        peak_min = ev["peak_minute"]
        resolved_min = ev["resolved_minute"]
        actual_origin = ev["origin_station_id"]
        actual_path = [s.strip() for s in ev["propagation_path"].split(",")]

        sub = engine.sensor_df_with_preds[
            (engine.sensor_df_with_preds["run_id"] == run_id) &
            (engine.sensor_df_with_preds["minute_index"] >= start_min) &
            (engine.sensor_df_with_preds["minute_index"] <= peak_min + 5)
        ].copy()

        # Earliest-origin scoring
        anom = sub[sub["defect_prob"] >= best_alert_tau]
        if not anom.empty:
            earliest_mins = anom.groupby("station_id")["minute_index"].min().to_dict()
            min_minute = min(earliest_mins.values())
            lead_stations = [s for s, m in earliest_mins.items() if m <= min_minute + 2]
            lead_sub = anom[anom["station_id"].isin(lead_stations)]
            pred_origin = lead_sub.groupby("station_id")["defect_prob"].max().idxmax()
        else:
            pred_origin = sub.groupby("station_id")["defect_prob"].max().idxmax()

        is_match = (pred_origin == actual_origin)
        if is_match:
            origin_matches += 1

        # Predict propagation path starting from predicted earliest origin
        risk_map = engine.get_station_risk_at_time(run_id, start_min, peak_min + 5)
        pred_path, path_scores = engine.predict_propagation_path(
            origin_station=pred_origin,
            risk_map=risk_map,
            max_hops=10,
            min_risk_threshold=stopping_tau
        )

        act_set = set(actual_path)
        pred_set = set(pred_path)
        common = act_set.intersection(pred_set)

        jacc = len(common) / len(act_set.union(pred_set)) if act_set.union(pred_set) else 0.0
        prec = len(common) / len(pred_set) if pred_set else 0.0
        rec = len(common) / len(act_set) if act_set else 0.0

        jaccards.append(jacc)
        precisions.append(prec)
        recalls.append(rec)

        # VIN evaluation from predicted path
        at_risk_df = engine.identify_at_risk_vins(run_id, pred_path, start_min, resolved_min)
        pred_vins_ev = set(at_risk_df["vin"].unique()) if not at_risk_df.empty else set()
        
        act_vins_ev = set(test_vehicles_df[
            (test_vehicles_df["run_id"] == run_id) &
            (test_vehicles_df["affected_events"].fillna("").str.contains(evt_id))
        ]["vin"].unique())

        all_pred_vins.update(pred_vins_ev)

        vin_common = pred_vins_ev.intersection(act_vins_ev)
        v_prec = len(vin_common) / len(pred_vins_ev) if pred_vins_ev else 0.0
        v_rec = len(vin_common) / len(act_vins_ev) if act_vins_ev else 0.0
        v_f1 = (2 * v_prec * v_rec) / (v_prec + v_rec) if (v_prec + v_rec) > 0 else 0.0

        test_rows.append({
            "Event": evt_id,
            "Actual origin": actual_origin,
            "Predicted origin": pred_origin,
            "Actual path": " -> ".join(actual_path),
            "Predicted path": " -> ".join(pred_path),
            "Path overlap": f"{jacc:.1%}",
            "VIN F1": f"{v_f1:.1%}"
        })

    test_results_df = pd.DataFrame(test_rows)
    print("\nRESULTS TABLE (RUN-021 TO RUN-025):")
    print(test_results_df.to_markdown(index=False))

    tp_v = len(all_pred_vins.intersection(actual_defect_vins_universe))
    fp_v = len(all_pred_vins - actual_defect_vins_universe)
    fn_v = len(actual_defect_vins_universe - all_pred_vins)
    tot_vin_prec = tp_v / (tp_v + fp_v) if (tp_v + fp_v) > 0 else 0.0
    tot_vin_rec = tp_v / (tp_v + fn_v) if (tp_v + fn_v) > 0 else 0.0
    tot_vin_f1 = (2 * tot_vin_prec * tot_vin_rec) / (tot_vin_prec + tot_vin_rec) if (tot_vin_prec + tot_vin_rec) > 0 else 0.0

    print("\n" + "=" * 80)
    print("OVERALL SUMMARY METRICS (EARLIEST-ORIGIN SCORING):")
    print("=" * 80)
    print(f"Origin accuracy:      {origin_matches / len(test_defects):.1%} ({origin_matches}/{len(test_defects)})")
    print(f"Mean path precision:  {np.mean(precisions):.1%}")
    print(f"Mean path recall:     {np.mean(recalls):.1%}")
    print(f"Mean path overlap:    {np.mean(jaccards):.1%}")
    print(f"VIN precision:        {tot_vin_prec:.1%}")
    print(f"VIN recall:           {tot_vin_rec:.1%}")
    print(f"VIN F1:               {tot_vin_f1:.1%}")
    print("=" * 80)

if __name__ == "__main__":
    evaluate_earliest_origin()
