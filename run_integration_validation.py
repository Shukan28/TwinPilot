"""
TwinPilot: Standalone vs. Integrated Pipeline Verification
==========================================================
Verifies that all 7 core intelligence components produce identical outputs
when executed independently vs. through the integrated pipeline.
"""

import sys
import io
import pandas as pd
# pyrefly: ignore [missing-import]
import numpy as np
from sklearn.ensemble import RandomForestClassifier

# Set standard output encoding to utf-8 safely
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from run_scenario_pipeline import TwinPilotPipeline
from propagation_engine import DefectModelService
from root_cause_engine import RootCauseEngine
from dark_zone_inference import build_vectorized_dark_zone_dataset
from counterfactual_engine import StateDependentCounterfactualEngine

def main():
    print("================================================================================")
    print("TWINPILOT: INTEGRATION VALIDATION AUDIT")
    print("================================================================================\n")

    dataset_dir = r"twinpilot_dataset_extracted\twinpilot_dataset"
    sensor_df = pd.read_csv(f"{dataset_dir}/sensor_timeseries.csv")
    events_df = pd.read_csv(f"{dataset_dir}/events_ground_truth.csv")
    train_runs = [f"RUN-{str(i).zfill(3)}" for i in range(1, 16)]

    # -------------------------------------------------------------
    # 1. INITIALIZE STANDALONE MODULES
    # -------------------------------------------------------------
    print("[1/3] Initializing Standalone Baseline Models...")
    # Standalone Bottleneck Model
    bn_events = events_df[events_df["event_type"] == "bottleneck"]
    bn_merged = pd.merge(
        sensor_df, bn_events[["run_id", "origin_station_id", "peak_minute"]],
        left_on=["run_id", "station_id"],
        right_on=["run_id", "origin_station_id"],
        how="left"
    )
    time_to_peak = bn_merged["peak_minute"] - bn_merged["minute_index"]
    bn_sensor_df = sensor_df.copy()
    bn_sensor_df["bottleneck_15min_ahead"] = ((time_to_peak > 0) & (time_to_peak <= 15)).astype(int)
    
    base_features = ["cycle_time_sec", "queue_length", "vibration_mm_s", "torque_nm", "temperature_c"]
    bn_sensor_df[base_features] = bn_sensor_df[base_features].fillna(-1)
    bn_sensor_df = bn_sensor_df.sort_values(by=["run_id", "station_id", "minute_index"])
    grouped = bn_sensor_df.groupby(["run_id", "station_id"])
    
    bn_sensor_df["avg_cycle_time_5m"] = grouped["cycle_time_sec"].rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
    bn_sensor_df["avg_cycle_time_10m"] = grouped["cycle_time_sec"].rolling(10, min_periods=1).mean().reset_index(level=[0,1], drop=True)
    bn_sensor_df["avg_queue_5m"] = grouped["queue_length"].rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
    bn_sensor_df["avg_queue_10m"] = grouped["queue_length"].rolling(10, min_periods=1).mean().reset_index(level=[0,1], drop=True)
    bn_sensor_df["change_cycle_time_5m"] = bn_sensor_df["cycle_time_sec"] - grouped["cycle_time_sec"].shift(5).fillna(bn_sensor_df["cycle_time_sec"])
    bn_sensor_df["change_cycle_time_10m"] = bn_sensor_df["cycle_time_sec"] - grouped["cycle_time_sec"].shift(10).fillna(bn_sensor_df["cycle_time_sec"])
    bn_sensor_df["queue_growth_5m"] = bn_sensor_df["queue_length"] - grouped["queue_length"].shift(5).fillna(bn_sensor_df["queue_length"])
    bn_sensor_df["queue_growth_10m"] = bn_sensor_df["queue_length"] - grouped["queue_length"].shift(10).fillna(bn_sensor_df["queue_length"])
    bn_sensor_df["change_vibration_5m"] = bn_sensor_df["vibration_mm_s"] - grouped["vibration_mm_s"].shift(5).fillna(bn_sensor_df["vibration_mm_s"])
    bn_sensor_df["change_torque_5m"] = bn_sensor_df["torque_nm"] - grouped["torque_nm"].shift(5).fillna(bn_sensor_df["torque_nm"])

    bn_features = base_features + [
        "avg_cycle_time_5m", "avg_cycle_time_10m", "change_cycle_time_5m", "change_cycle_time_10m",
        "avg_queue_5m", "avg_queue_10m", "queue_growth_5m", "queue_growth_10m",
        "change_vibration_5m", "change_torque_5m"
    ]
    standalone_bn_model = RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1, class_weight="balanced")
    standalone_bn_model.fit(bn_sensor_df[bn_sensor_df["run_id"].isin(train_runs)][bn_features],
                           bn_sensor_df[bn_sensor_df["run_id"].isin(train_runs)]["bottleneck_15min_ahead"])
    bn_sensor_df["bottleneck_prob"] = standalone_bn_model.predict_proba(bn_sensor_df[bn_features])[:, 1]

    # Standalone Defect Model Service
    standalone_defect_service = DefectModelService(dataset_dir)
    standalone_defect_service.initialize_and_train()

    # Standalone Dark Zone Model
    dz_data, manual_stations, _ = build_vectorized_dark_zone_dataset(dataset_dir)
    dz_feature_cols = [c for c in dz_data.columns if c not in ["run_id", "minute_index", "target_station", "is_degrading"]]
    dz_train = dz_data[dz_data["run_id"].isin(train_runs)]
    standalone_dz_model = RandomForestClassifier(n_estimators=150, random_state=42, n_jobs=-1, class_weight="balanced")
    standalone_dz_model.fit(dz_train[dz_feature_cols], dz_train["is_degrading"])
    dz_data["dz_prob"] = standalone_dz_model.predict_proba(dz_data[dz_feature_cols])[:, 1]

    # Standalone Root Cause & Counterfactual Engines
    standalone_rc_engine = RootCauseEngine(dataset_dir)
    standalone_cf_engine = StateDependentCounterfactualEngine(dataset_dir)

    # -------------------------------------------------------------
    # 2. INITIALIZE INTEGRATED PIPELINE
    # -------------------------------------------------------------
    print("[2/3] Initializing Integrated TwinPilot Pipeline...")
    pipeline = TwinPilotPipeline(dataset_dir)
    print("      Initialization Complete.\n")

    # -------------------------------------------------------------
    # 3. VERIFY SCENARIO 1: RUN024-EVT01 (S03 Defect / High Queue)
    # -------------------------------------------------------------
    print("[3/3] Executing Side-by-Side Audit...")
    
    # Standalone S1
    sa_s1_bn = bn_sensor_df[(bn_sensor_df["run_id"] == "RUN-024") & (bn_sensor_df["station_id"] == "S03") & (bn_sensor_df["minute_index"] == 143)]["bottleneck_prob"].iloc[0]
    sa_s1_defect = standalone_defect_service.sensor_df_with_preds[(standalone_defect_service.sensor_df_with_preds["run_id"] == "RUN-024") & (standalone_defect_service.sensor_df_with_preds["station_id"] == "S03") & (standalone_defect_service.sensor_df_with_preds["minute_index"] == 143)]["defect_prob"].iloc[0]
    
    s1_dz_sub = dz_data[(dz_data["run_id"] == "RUN-024") & (dz_data["minute_index"] == 143)]
    sa_s1_dz_max = s1_dz_sub["dz_prob"].max()
    sa_s1_dz_str = "Normal (< 25%)" if sa_s1_dz_max < 0.25 else f"{sa_s1_dz_max*100:.1f}%"
    
    sa_s1_rc = standalone_rc_engine.predict_origin("RUN-024", 139, 148)
    
    s1_risk_map = standalone_defect_service.get_station_risk_at_time("RUN-024", 139, 148 + 5)
    sa_s1_path, _ = standalone_defect_service.predict_propagation_path("S03", s1_risk_map, max_hops=10, min_risk_threshold=0.02)
    sa_s1_vins = standalone_defect_service.identify_at_risk_vins("RUN-024", sa_s1_path, 139, 198)
    sa_s1_cf = standalone_cf_engine.simulate_state_dependent_intervention("RUN-024", "S03", 143)
    sa_s1_rec = sa_s1_cf["recommended_option"]

    # Pipeline S1
    pipe_s1 = pipeline.run_scenario(run_id="RUN-024", minute_index=143, target_station="S03", event_id="RUN024-EVT01")
    pipe_s1_dz_str = "Normal (< 25%)" if pipe_s1["dz_flagged"].empty else f"{pipe_s1['dz_flagged']['dz_prob'].max()*100:.1f}%"

    table_s1 = [
        {"Component": "Bottleneck probability", "Standalone result": f"{sa_s1_bn*100:.1f}%", "Pipeline result": f"{pipe_s1['bottleneck_prob']*100:.1f}%", "Match?": "MATCH" if abs(sa_s1_bn - pipe_s1['bottleneck_prob']) < 1e-4 else "MISMATCH"},
        {"Component": "Defect probability", "Standalone result": f"{sa_s1_defect*100:.1f}%", "Pipeline result": f"{pipe_s1['defect_prob']*100:.1f}%", "Match?": "MATCH" if abs(sa_s1_defect - pipe_s1['defect_prob']) < 1e-4 else "MISMATCH"},
        {"Component": "Dark Zone confidence", "Standalone result": sa_s1_dz_str, "Pipeline result": pipe_s1_dz_str, "Match?": "MATCH" if sa_s1_dz_str == pipe_s1_dz_str else "MISMATCH"},
        {"Component": "Root cause", "Standalone result": sa_s1_rc, "Pipeline result": pipe_s1["root_cause"], "Match?": "MATCH" if sa_s1_rc == pipe_s1["root_cause"] else "MISMATCH"},
        {"Component": "Propagation path", "Standalone result": " -> ".join(sa_s1_path), "Pipeline result": " -> ".join(pipe_s1["propagation_path"]), "Match?": "MATCH" if sa_s1_path == pipe_s1["propagation_path"] else "MISMATCH"},
        {"Component": "At-risk VIN count", "Standalone result": f"{len(sa_s1_vins)} VINs", "Pipeline result": f"{pipe_s1['at_risk_vins_count']} VINs", "Match?": "MATCH" if len(sa_s1_vins) == pipe_s1['at_risk_vins_count'] else "MISMATCH"},
        {"Component": "Recommended option", "Standalone result": sa_s1_rec, "Pipeline result": pipe_s1["recommended_option"], "Match?": "MATCH" if sa_s1_rec == pipe_s1["recommended_option"] else "MISMATCH"},
    ]

    # -------------------------------------------------------------
    # 4. VERIFY SCENARIO 2: RUN025-EVT02 (S16 Machine Failure / Queue)
    # -------------------------------------------------------------
    # Standalone S2
    sa_s2_bn = bn_sensor_df[(bn_sensor_df["run_id"] == "RUN-025") & (bn_sensor_df["station_id"] == "S16") & (bn_sensor_df["minute_index"] == 93)]["bottleneck_prob"].iloc[0]
    sa_s2_defect = standalone_defect_service.sensor_df_with_preds[(standalone_defect_service.sensor_df_with_preds["run_id"] == "RUN-025") & (standalone_defect_service.sensor_df_with_preds["station_id"] == "S16") & (standalone_defect_service.sensor_df_with_preds["minute_index"] == 93)]["defect_prob"].iloc[0]
    
    s2_dz_sub = dz_data[(dz_data["run_id"] == "RUN-025") & (dz_data["minute_index"] == 93)]
    sa_s2_dz_max = s2_dz_sub["dz_prob"].max()
    sa_s2_dz_st = s2_dz_sub.loc[s2_dz_sub["dz_prob"].idxmax()]["target_station"]
    sa_s2_dz_str = f"{sa_s2_dz_st}: {sa_s2_dz_max*100:.1f}%"
    
    sa_s2_rc = standalone_rc_engine.predict_origin("RUN-025", 92, 96)
    
    s2_risk_map = standalone_defect_service.get_station_risk_at_time("RUN-025", 92, 96 + 5)
    sa_s2_path, _ = standalone_defect_service.predict_propagation_path("S16", s2_risk_map, max_hops=10, min_risk_threshold=0.02)
    sa_s2_vins = standalone_defect_service.identify_at_risk_vins("RUN-025", sa_s2_path, 92, 114)
    sa_s2_cf = standalone_cf_engine.simulate_state_dependent_intervention("RUN-025", "S16", 93)
    sa_s2_rec = sa_s2_cf["recommended_option"]

    # Pipeline S2
    pipe_s2 = pipeline.run_scenario(run_id="RUN-025", minute_index=93, target_station="S16", event_id="RUN025-EVT02")
    pipe_s2_dz_st = pipe_s2["dz_flagged"].iloc[0]["target_station"] if not pipe_s2["dz_flagged"].empty else "None"
    pipe_s2_dz_max = pipe_s2["dz_flagged"].iloc[0]["dz_prob"] if not pipe_s2["dz_flagged"].empty else 0.0
    pipe_s2_dz_str = f"{pipe_s2_dz_st}: {pipe_s2_dz_max*100:.1f}%"

    table_s2 = [
        {"Component": "Bottleneck probability", "Standalone result": f"{sa_s2_bn*100:.1f}%", "Pipeline result": f"{pipe_s2['bottleneck_prob']*100:.1f}%", "Match?": "MATCH" if abs(sa_s2_bn - pipe_s2['bottleneck_prob']) < 1e-4 else "MISMATCH"},
        {"Component": "Defect probability", "Standalone result": f"{sa_s2_defect*100:.1f}%", "Pipeline result": f"{pipe_s2['defect_prob']*100:.1f}%", "Match?": "MATCH" if abs(sa_s2_defect - pipe_s2['defect_prob']) < 1e-4 else "MISMATCH"},
        {"Component": "Dark Zone confidence", "Standalone result": sa_s2_dz_str, "Pipeline result": pipe_s2_dz_str, "Match?": "MATCH" if sa_s2_dz_str == pipe_s2_dz_str else "MISMATCH"},
        {"Component": "Root cause", "Standalone result": sa_s2_rc, "Pipeline result": pipe_s2["root_cause"], "Match?": "MATCH" if sa_s2_rc == pipe_s2["root_cause"] else "MISMATCH"},
        {"Component": "Propagation path", "Standalone result": " -> ".join(sa_s2_path), "Pipeline result": " -> ".join(pipe_s2["propagation_path"]), "Match?": "MATCH" if sa_s2_path == pipe_s2["propagation_path"] else "MISMATCH"},
        {"Component": "At-risk VIN count", "Standalone result": f"{len(sa_s2_vins)} VINs", "Pipeline result": f"{pipe_s2['at_risk_vins_count']} VINs", "Match?": "MATCH" if len(sa_s2_vins) == pipe_s2['at_risk_vins_count'] else "MISMATCH"},
        {"Component": "Recommended option", "Standalone result": sa_s2_rec, "Pipeline result": pipe_s2["recommended_option"], "Match?": "MATCH" if sa_s2_rec == pipe_s2["recommended_option"] else "MISMATCH"},
    ]

    print("================================================================================")
    print("SCENARIO 1: RUN024-EVT01 (S03 Defect Propagation / High Queue)")
    print("================================================================================")
    print(pd.DataFrame(table_s1).to_markdown(index=False))

    print("\n" + "=" * 80)
    print("SCENARIO 2: RUN025-EVT02 (S16 Machine Failure / Queue Backlog)")
    print("================================================================================")
    print(pd.DataFrame(table_s2).to_markdown(index=False))

if __name__ == "__main__":
    main()
