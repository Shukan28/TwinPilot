"""
TwinPilot: Dark Zone / Sensorless Station Inference Engine (Vectorized)
======================================================================
Infers degradation state of uninstrumented (manual) stations strictly
from observable upstream and downstream neighboring telemetry.
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, precision_score, recall_score, f1_score, confusion_matrix

def build_vectorized_dark_zone_dataset(dataset_dir=r"twinpilot_dataset_extracted\twinpilot_dataset"):
    sensor_df = pd.read_csv(f"{dataset_dir}/sensor_timeseries.csv")
    events_df = pd.read_csv(f"{dataset_dir}/events_ground_truth.csv")
    stations_df = pd.read_csv(f"{dataset_dir}/stations_master.csv")
    dependencies_df = pd.read_csv(f"{dataset_dir}/station_dependencies.csv")

    manual_stations = stations_df[stations_df["sensor_tier"] == "manual"]["station_id"].tolist()
    
    # Map upstream and downstream neighbors
    downstream_map = dependencies_df.groupby("from_station")["to_station"].apply(list).to_dict()
    upstream_map = dependencies_df.groupby("to_station")["from_station"].apply(list).to_dict()

    # Pre-calculate rolling features on all sensor timeseries
    base_cols = ["cycle_time_sec", "queue_length", "vibration_mm_s", "torque_nm", "temperature_c"]
    sensor_df[base_cols] = sensor_df[base_cols].fillna(-1)
    sensor_df = sensor_df.sort_values(by=["run_id", "station_id", "minute_index"])
    grouped = sensor_df.groupby(["run_id", "station_id"])

    sensor_df["avg_ct_5m"] = grouped["cycle_time_sec"].rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
    sensor_df["avg_ct_10m"] = grouped["cycle_time_sec"].rolling(10, min_periods=1).mean().reset_index(level=[0,1], drop=True)
    sensor_df["delta_ct_5m"] = sensor_df["cycle_time_sec"] - grouped["cycle_time_sec"].shift(5).fillna(sensor_df["cycle_time_sec"])
    sensor_df["delta_ct_10m"] = sensor_df["cycle_time_sec"] - grouped["cycle_time_sec"].shift(10).fillna(sensor_df["cycle_time_sec"])
    sensor_df["avg_queue_5m"] = grouped["queue_length"].rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
    sensor_df["avg_queue_10m"] = grouped["queue_length"].rolling(10, min_periods=1).mean().reset_index(level=[0,1], drop=True)
    sensor_df["queue_growth_5m"] = sensor_df["queue_length"] - grouped["queue_length"].shift(5).fillna(sensor_df["queue_length"])
    sensor_df["queue_growth_10m"] = sensor_df["queue_length"] - grouped["queue_length"].shift(10).fillna(sensor_df["queue_length"])
    sensor_df["avg_torque_5m"] = grouped["torque_nm"].rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
    sensor_df["avg_vib_5m"] = grouped["vibration_mm_s"].rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
    sensor_df["avg_temp_5m"] = grouped["temperature_c"].rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)

    # Base telemetry lookup dataframe keyed by (run_id, station_id, minute_index)
    lookup_cols = [
        "run_id", "station_id", "minute_index", "cycle_time_sec", "queue_length",
        "avg_ct_5m", "avg_ct_10m", "delta_ct_5m", "delta_ct_10m",
        "avg_queue_5m", "avg_queue_10m", "queue_growth_5m", "queue_growth_10m",
        "avg_torque_5m", "avg_vib_5m", "avg_temp_5m"
    ]
    lookup_df = sensor_df[lookup_cols].copy()

    # Ground truth labels
    event_rows = []
    for _, ev in events_df.iterrows():
        path_stations = [s.strip() for s in str(ev["propagation_path"]).split(",")]
        for st in path_stations:
            if st in manual_stations:
                event_rows.append({
                    "run_id": ev["run_id"],
                    "station_id": st,
                    "event_id": ev["event_id"],
                    "start_minute": ev["start_minute"],
                    "peak_minute": ev["peak_minute"],
                    "resolved_minute": ev["resolved_minute"],
                    "event_type": ev["event_type"]
                })
    degrade_events = pd.DataFrame(event_rows)

    all_station_dfs = []
    runs = sensor_df["run_id"].unique()
    minutes = np.arange(240)
    grid_index = pd.MultiIndex.from_product([runs, minutes], names=["run_id", "minute_index"]).to_frame().reset_index(drop=True)

    for m_st in manual_stations:
        st_df = grid_index.copy()
        st_df["target_station"] = m_st
        st_df["station_num"] = int(m_st.replace("S", ""))

        up1 = upstream_map.get(m_st, [None])[0]
        up2 = upstream_map.get(up1, [None])[0] if up1 else None
        down1 = downstream_map.get(m_st, [None])[0]
        down2 = downstream_map.get(down1, [None])[0] if down1 else None

        # Merge Upstream 1
        if up1:
            u1_df = lookup_df[lookup_df["station_id"] == up1].drop(columns=["station_id"])
            u1_df.columns = ["run_id", "minute_index"] + [f"up1_{c}" for c in u1_df.columns if c not in ["run_id", "minute_index"]]
            st_df = pd.merge(st_df, u1_df, on=["run_id", "minute_index"], how="left")
        else:
            for c in lookup_cols:
                if c not in ["run_id", "station_id", "minute_index"]:
                    st_df[f"up1_{c}"] = -1

        # Merge Upstream 2
        if up2:
            u2_df = lookup_df[lookup_df["station_id"] == up2][["run_id", "minute_index", "cycle_time_sec", "queue_length", "avg_ct_5m", "queue_growth_5m"]]
            u2_df.columns = ["run_id", "minute_index", "up2_ct", "up2_queue", "up2_avg_ct_5m", "up2_queue_growth_5m"]
            st_df = pd.merge(st_df, u2_df, on=["run_id", "minute_index"], how="left")
        else:
            for c in ["up2_ct", "up2_queue", "up2_avg_ct_5m", "up2_queue_growth_5m"]:
                st_df[c] = -1

        # Merge Downstream 1
        if down1:
            d1_df = lookup_df[lookup_df["station_id"] == down1].drop(columns=["station_id"])
            d1_df.columns = ["run_id", "minute_index"] + [f"down1_{c}" for c in d1_df.columns if c not in ["run_id", "minute_index"]]
            st_df = pd.merge(st_df, d1_df, on=["run_id", "minute_index"], how="left")
        else:
            for c in lookup_cols:
                if c not in ["run_id", "station_id", "minute_index"]:
                    st_df[f"down1_{c}"] = -1

        # Merge Downstream 2
        if down2:
            d2_df = lookup_df[lookup_df["station_id"] == down2][["run_id", "minute_index", "cycle_time_sec", "queue_length", "avg_ct_5m", "queue_growth_5m"]]
            d2_df.columns = ["run_id", "minute_index", "down2_ct", "down2_queue", "down2_avg_ct_5m", "down2_queue_growth_5m"]
            st_df = pd.merge(st_df, d2_df, on=["run_id", "minute_index"], how="left")
        else:
            for c in ["down2_ct", "down2_queue", "down2_avg_ct_5m", "down2_queue_growth_5m"]:
                st_df[c] = -1

        # Calculate neighbor differentials
        st_df["queue_diff_up_down"] = st_df["up1_queue_length"].fillna(0) - st_df["down1_queue_length"].fillna(0)
        st_df["ct_diff_up_down"] = st_df["up1_cycle_time_sec"].fillna(0) - st_df["down1_cycle_time_sec"].fillna(0)

        # Labeling
        st_df["is_degrading"] = 0
        if not degrade_events.empty:
            st_events = degrade_events[degrade_events["station_id"] == m_st]
            for _, ev in st_events.iterrows():
                mask = (
                    (st_df["run_id"] == ev["run_id"]) &
                    (st_df["minute_index"] >= ev["start_minute"]) &
                    (st_df["minute_index"] <= ev["resolved_minute"])
                )
                st_df.loc[mask, "is_degrading"] = 1

        all_station_dfs.append(st_df)

    dataset_df = pd.concat(all_station_dfs, ignore_index=True)
    dataset_df = dataset_df.fillna(-1)
    return dataset_df, manual_stations, events_df

def run_dark_zone_experiment():
    print("================================================================================")
    print("TWINPILOT: DARK ZONE / SENSORLESS INFERENCE EXPERIMENT")
    print("================================================================================\n")

    print("[1/4] Building Vectorized Neighbor Telemetry Pipeline...")
    dataset_df, manual_stations, events_df = build_vectorized_dark_zone_dataset()
    print(f"      Dark zone manual stations evaluated: {manual_stations}")
    print(f"      Total telemetry samples generated: {len(dataset_df):,} rows\n")

    feature_cols = [c for c in dataset_df.columns if c not in ["run_id", "minute_index", "target_station", "is_degrading"]]

    train_runs = [f"RUN-{str(i).zfill(3)}" for i in range(1, 16)]
    val_runs   = [f"RUN-{str(i).zfill(3)}" for i in range(16, 21)]
    test_runs  = [f"RUN-{str(i).zfill(3)}" for i in range(21, 26)]

    train_df = dataset_df[dataset_df["run_id"].isin(train_runs)]
    val_df   = dataset_df[dataset_df["run_id"].isin(val_runs)]
    test_df  = dataset_df[dataset_df["run_id"].isin(test_runs)].copy()

    X_train, y_train = train_df[feature_cols], train_df["is_degrading"]
    X_val, y_val     = val_df[feature_cols], val_df["is_degrading"]
    X_test, y_test   = test_df[feature_cols], test_df["is_degrading"]

    print("[2/4] Training Dark Zone Inference Classifier on RUN-001..RUN-015...")
    model = RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=-1, class_weight="balanced")
    model.fit(X_train, y_train)
    print("      Model trained successfully.\n")

    # Tune threshold on validation set
    print("[3/4] Tuning Inference Threshold on Validation Set (RUN-016..RUN-020)...")
    val_probs = model.predict_proba(X_val)[:, 1]
    val_auc = roc_auc_score(y_val, val_probs)
    
    candidate_thresholds = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60]
    best_tau = 0.30
    best_f1 = -1.0
    for tau in candidate_thresholds:
        preds = (val_probs >= tau).astype(int)
        f1 = f1_score(y_val, preds, zero_division=0)
        prec = precision_score(y_val, preds, zero_division=0)
        rec = recall_score(y_val, preds, zero_division=0)
        if f1 > best_f1:
            best_f1 = f1
            best_tau = tau
        print(f"      Threshold {tau:.2f} -> Precision: {prec:.1%}, Recall: {rec:.1%}, F1: {f1:.1%}")
    print(f"\n      --> Selected Frozen Inference Threshold: tau* = {best_tau:.2f} (Val AUC: {val_auc:.4f}, Val F1: {best_f1:.1%})\n")

    # Evaluate on Test Runs (RUN-021..RUN-025)
    print("[4/4] Evaluating Dark Zone Inference on Unseen Test Runs (RUN-021..RUN-025)...")
    print("=" * 80)
    test_probs = model.predict_proba(X_test)[:, 1]
    test_preds = (test_probs >= best_tau).astype(int)
    test_df["inferred_prob"] = test_probs
    test_df["inferred_degrading"] = test_preds

    test_auc = roc_auc_score(y_test, test_probs)
    test_prec = precision_score(y_test, test_preds, zero_division=0)
    test_rec = recall_score(y_test, test_preds, zero_division=0)
    test_f1 = f1_score(y_test, test_preds, zero_division=0)
    cm = confusion_matrix(y_test, test_preds)

    print(f"TEST SET PERFORMANCE METRICS (DARK ZONE INFERENCE):")
    print(f"  ROC-AUC:               {test_auc:.4f}")
    print(f"  Accuracy:              {(test_preds == y_test).mean():.1%}")
    print(f"  Precision:             {test_prec:.1%}")
    print(f"  Recall:                {test_rec:.1%}")
    print(f"  F1-Score:              {test_f1:.1%}")
    print(f"\nConfusion Matrix (Minute-level Dark Zone Inference):")
    print(f"  TN: {cm[0,0]:5d} | FP: {cm[0,1]:5d}")
    print(f"  FN: {cm[1,0]:5d} | TP: {cm[1,1]:5d}")

    # Top feature importances
    importances = pd.Series(model.feature_importances_, index=feature_cols).sort_values(ascending=False)
    print("\nTop 8 Neighbor Telemetry Features Used for Dark Zone Inference:")
    for feat, imp in importances.head(8).items():
        print(f"  - {feat:25s}: {imp:.1%}")

    # Event-level Breakdown on Test Runs
    print("\n" + "=" * 80)
    print("DARK ZONE EVENT INFERENCE BREAKDOWN ON UNSEEN TEST SHIFTS:")
    print("=" * 80)

    test_events = events_df[events_df["run_id"].isin(test_runs)].copy()
    for _, ev in test_events.iterrows():
        path_stations = [s.strip() for s in str(ev["propagation_path"]).split(",")]
        affected_manual = [s for s in path_stations if s in manual_stations]
        if not affected_manual:
            continue

        run_id = ev["run_id"]
        evt_id = ev["event_id"]
        start_m = ev["start_minute"]
        peak_m = ev["peak_minute"]
        resolved_m = ev["resolved_minute"]
        etype = ev["event_type"]

        print(f"\n[EVENT {evt_id}] ({run_id} | Type: {etype} | Peak: Min {peak_m})")
        print(f"  Dark Zone Stations on Propagation Path: {', '.join(affected_manual)}")

        for m_st in affected_manual:
            sub = test_df[
                (test_df["run_id"] == run_id) &
                (test_df["target_station"] == m_st) &
                (test_df["minute_index"] >= start_m - 5) &
                (test_df["minute_index"] <= resolved_m + 5)
            ]
            if sub.empty:
                continue

            max_prob = sub["inferred_prob"].max()
            first_alert = sub[sub["inferred_prob"] >= best_tau]
            if not first_alert.empty:
                first_alert_m = first_alert["minute_index"].min()
                lead_time = peak_m - first_alert_m
                state_str = "Degrading"
                conf_str = f"{max_prob * 100:.1f}%"
                detected_str = f"Detected {lead_time} minutes before peak degradation (at Min {first_alert_m})"
            else:
                state_str = "Sub-threshold"
                conf_str = f"{max_prob * 100:.1f}%"
                detected_str = "Sub-threshold (Peak probability below cutoff)"

            print(f"  > Station {m_st} — NO DIRECT SENSOR")
            print(f"    Inferred state: {state_str}")
            print(f"    Confidence:     {conf_str}")
            print(f"    Lead Time:      {detected_str}")

if __name__ == "__main__":
    run_dark_zone_experiment()
