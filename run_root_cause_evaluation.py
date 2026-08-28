"""
Evaluate Root Cause Scoring on Validation and Test Runs
"""
import pandas as pd
# pyrefly: ignore [missing-import]
import numpy as np
from root_cause_engine import RootCauseEngine

def main():
    engine = RootCauseEngine()
    
    events_df = engine.events_df
    vehicles_df = engine.vehicles_df
    
    val_runs = [f"RUN-{str(i).zfill(3)}" for i in range(16, 21)]
    test_runs = [f"RUN-{str(i).zfill(3)}" for i in range(21, 26)]
    
    val_defects = events_df[(events_df["run_id"].isin(val_runs)) & (events_df["event_type"] == "defect_propagation")]
    test_defects = events_df[(events_df["run_id"].isin(test_runs)) & (events_df["event_type"] == "defect_propagation")]
    
    print("================================================================================")
    print("VALIDATION SET RESULTS (RUN-016 TO RUN-020):")
    print("================================================================================")
    val_correct = 0
    for _, ev in val_defects.iterrows():
        pred = engine.predict_origin(ev["run_id"], ev["start_minute"], ev["peak_minute"])
        match = (pred == ev["origin_station_id"])
        if match:
            val_correct += 1
        print(f"{ev['event_id']}: Actual = {ev['origin_station_id']} | Predicted = {pred} | Match: {match}")
    print(f"Validation Origin Accuracy: {val_correct / len(val_defects):.1%} ({val_correct}/{len(val_defects)})\n")
    
    print("================================================================================")
    print("TEST SET RESULTS (RUN-021 TO RUN-025) — ROOT CAUSE SCORING:")
    print("================================================================================")
    
    frozen_tau = 0.02  # frozen propagation stopping threshold
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

        # Predict origin using 3-factor root cause scoring
        pred_origin = engine.predict_origin(run_id, start_min, peak_min)
        is_match = (pred_origin == actual_origin)
        if is_match:
            origin_matches += 1

        # Predict propagation path from predicted origin
        risk_map = engine.service.get_station_risk_at_time(run_id, start_min, peak_min + 5)
        pred_path, path_scores = engine.service.predict_propagation_path(
            origin_station=pred_origin,
            risk_map=risk_map,
            max_hops=10,
            min_risk_threshold=frozen_tau
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
        at_risk_df = engine.service.identify_at_risk_vins(run_id, pred_path, start_min, resolved_min)
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
    print("OVERALL TEST SUMMARY (ROOT-CAUSE 3-FACTOR SCORING):")
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
    main()
