"""
Diagnostic: Compare Standalone Subsystem Outputs vs. Pipeline Outputs
"""
import pandas as pd
# pyrefly: ignore [missing-import]
import numpy as np

def run_diagnostic():
    dataset_dir = r"twinpilot_dataset_extracted\twinpilot_dataset"
    sensor_df = pd.read_csv(f"{dataset_dir}/sensor_timeseries.csv")
    events_df = pd.read_csv(f"{dataset_dir}/events_ground_truth.csv")
    stations_df = pd.read_csv(f"{dataset_dir}/stations_master.csv")
    vehicles_df = pd.read_csv(f"{dataset_dir}/vehicles.csv")

    # 1. STANDALONE BOTTLENECK MODEL (train_model.py)
    print("--- 1. Standalone Bottleneck Model ---")
    from sklearn.ensemble import RandomForestClassifier
    
    bn_events = events_df[events_df['event_type'] == 'bottleneck']
    bn_merged = pd.merge(sensor_df, bn_events[['run_id', 'origin_station_id', 'peak_minute']],
                         left_on=['run_id', 'station_id'],
                         right_on=['run_id', 'origin_station_id'],
                         how='left')
    time_to_peak = bn_merged['peak_minute'] - bn_merged['minute_index']
    bn_sensor_df = sensor_df.copy()
    bn_sensor_df['bottleneck_15min_ahead'] = ((time_to_peak > 0) & (time_to_peak <= 15)).astype(int)
    
    base_features = ['cycle_time_sec', 'queue_length', 'vibration_mm_s', 'torque_nm', 'temperature_c']
    bn_sensor_df[base_features] = bn_sensor_df[base_features].fillna(-1)
    bn_sensor_df = bn_sensor_df.sort_values(by=['run_id', 'station_id', 'minute_index'])
    grouped = bn_sensor_df.groupby(['run_id', 'station_id'])
    
    bn_sensor_df['avg_cycle_time_5m'] = grouped['cycle_time_sec'].rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
    bn_sensor_df['avg_cycle_time_10m'] = grouped['cycle_time_sec'].rolling(10, min_periods=1).mean().reset_index(level=[0,1], drop=True)
    bn_sensor_df['avg_queue_5m'] = grouped['queue_length'].rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
    bn_sensor_df['avg_queue_10m'] = grouped['queue_length'].rolling(10, min_periods=1).mean().reset_index(level=[0,1], drop=True)
    bn_sensor_df['change_cycle_time_5m'] = bn_sensor_df['cycle_time_sec'] - grouped['cycle_time_sec'].shift(5).fillna(bn_sensor_df['cycle_time_sec'])
    bn_sensor_df['change_cycle_time_10m'] = bn_sensor_df['cycle_time_sec'] - grouped['cycle_time_sec'].shift(10).fillna(bn_sensor_df['cycle_time_sec'])
    bn_sensor_df['queue_growth_5m'] = bn_sensor_df['queue_length'] - grouped['queue_length'].shift(5).fillna(bn_sensor_df['queue_length'])
    bn_sensor_df['queue_growth_10m'] = bn_sensor_df['queue_length'] - grouped['queue_length'].shift(10).fillna(bn_sensor_df['queue_length'])
    bn_sensor_df['change_vibration_5m'] = bn_sensor_df['vibration_mm_s'] - grouped['vibration_mm_s'].shift(5).fillna(bn_sensor_df['vibration_mm_s'])
    bn_sensor_df['change_torque_5m'] = bn_sensor_df['torque_nm'] - grouped['torque_nm'].shift(5).fillna(bn_sensor_df['torque_nm'])

    bn_features = base_features + [
        'avg_cycle_time_5m', 'avg_cycle_time_10m', 'change_cycle_time_5m', 'change_cycle_time_10m',
        'avg_queue_5m', 'avg_queue_10m', 'queue_growth_5m', 'queue_growth_10m',
        'change_vibration_5m', 'change_torque_5m'
    ]
    train_runs = [f'RUN-{str(i).zfill(3)}' for i in range(1, 16)]
    bn_model = RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1, class_weight='balanced')
    bn_model.fit(bn_sensor_df[bn_sensor_df['run_id'].isin(train_runs)][bn_features],
                 bn_sensor_df[bn_sensor_df['run_id'].isin(train_runs)]['bottleneck_15min_ahead'])
    
    bn_sensor_df['bottleneck_prob'] = bn_model.predict_proba(bn_sensor_df[bn_features])[:, 1]
    
    # Check probabilities
    s1_bn = bn_sensor_df[(bn_sensor_df['run_id'] == 'RUN-024') & (bn_sensor_df['station_id'] == 'S03') & (bn_sensor_df['minute_index'] == 143)]['bottleneck_prob'].iloc[0]
    s2_bn = bn_sensor_df[(bn_sensor_df['run_id'] == 'RUN-025') & (bn_sensor_df['station_id'] == 'S16') & (bn_sensor_df['minute_index'] == 93)]['bottleneck_prob'].iloc[0]
    print(f"Standalone Bottleneck Prob -> RUN-024 @ S03 (Min 143): {s1_bn*100:.1f}%")
    print(f"Standalone Bottleneck Prob -> RUN-025 @ S16 (Min 93): {s2_bn*100:.1f}%")

    # 2. STANDALONE DEFECT MODEL v2 (analyze_defect_model_v2.py / propagation_engine.py)
    print("\n--- 2. Standalone Defect Model v2 ---")
    from propagation_engine import DefectModelService
    engine = DefectModelService(dataset_dir)
    engine.initialize_and_train()
    
    s1_defect = engine.sensor_df_with_preds[(engine.sensor_df_with_preds['run_id'] == 'RUN-024') & (engine.sensor_df_with_preds['station_id'] == 'S03') & (engine.sensor_df_with_preds['minute_index'] == 143)]['defect_prob'].iloc[0]
    s2_defect = engine.sensor_df_with_preds[(engine.sensor_df_with_preds['run_id'] == 'RUN-025') & (engine.sensor_df_with_preds['station_id'] == 'S16') & (engine.sensor_df_with_preds['minute_index'] == 93)]['defect_prob'].iloc[0]
    print(f"Standalone Defect Prob -> RUN-024 @ S03 (Min 143): {s1_defect*100:.1f}%")
    print(f"Standalone Defect Prob -> RUN-025 @ S16 (Min 93): {s2_defect*100:.1f}%")

    # 3. STANDALONE DARK ZONE MODEL (dark_zone_inference.py)
    print("\n--- 3. Standalone Dark Zone Model ---")
    from dark_zone_inference import build_vectorized_dark_zone_dataset
    dz_data, manual_stations, _ = build_vectorized_dark_zone_dataset(dataset_dir)
    dz_feature_cols = [c for c in dz_data.columns if c not in ["run_id", "minute_index", "target_station", "is_degrading"]]
    dz_train = dz_data[dz_data["run_id"].isin(train_runs)]
    dz_model = RandomForestClassifier(n_estimators=150, random_state=42, n_jobs=-1, class_weight="balanced")
    dz_model.fit(dz_train[dz_feature_cols], dz_train["is_degrading"])
    dz_data["dz_prob"] = dz_model.predict_proba(dz_data[dz_feature_cols])[:, 1]
    
    s1_dz = dz_data[(dz_data['run_id'] == 'RUN-024') & (dz_data['minute_index'] == 143)]
    s2_dz = dz_data[(dz_data['run_id'] == 'RUN-025') & (dz_data['minute_index'] == 93)]
    print(f"Standalone Dark Zone Max Prob -> RUN-024 (Min 143): {s1_dz['dz_prob'].max()*100:.1f}%")
    print(f"Standalone Dark Zone Max Prob -> RUN-025 (Min 93): {s2_dz['dz_prob'].max()*100:.1f}% (Station {s2_dz.loc[s2_dz['dz_prob'].idxmax()]['target_station']})")

    # 4. STANDALONE ROOT CAUSE & PROPAGATION
    print("\n--- 4. Standalone Root Cause & Propagation ---")
    from root_cause_engine import RootCauseEngine
    rc_engine = RootCauseEngine(dataset_dir)
    s1_rc = rc_engine.predict_origin('RUN-024', 139, 148)
    s2_rc = rc_engine.predict_origin('RUN-025', 92, 96)
    print(f"Standalone Root Cause -> RUN-024 (EVT01): {s1_rc}")
    print(f"Standalone Root Cause -> RUN-025 (EVT02): {s2_rc}")

    # Propagation from origin station with tau=0.02
    risk_map_1 = engine.get_station_risk_at_time('RUN-024', 139, 148 + 5)
    pred_path_1, _ = engine.predict_propagation_path('S03', risk_map_1, max_hops=10, min_risk_threshold=0.02)
    print(f"Standalone Propagation Path -> RUN-024 from S03: {' -> '.join(pred_path_1)}")

    risk_map_2 = engine.get_station_risk_at_time('RUN-025', 92, 96 + 5)
    pred_path_2, _ = engine.predict_propagation_path('S16', risk_map_2, max_hops=10, min_risk_threshold=0.02)
    print(f"Standalone Propagation Path -> RUN-025 from S16: {' -> '.join(pred_path_2)}")

    # 5. STANDALONE VINs
    vins_1 = engine.identify_at_risk_vins('RUN-024', pred_path_1, 139, 198)
    vins_2 = engine.identify_at_risk_vins('RUN-025', pred_path_2, 92, 114)
    print(f"\nStandalone At-Risk VINs Count -> RUN-024: {len(vins_1)}")
    print(f"Standalone At-Risk VINs Count -> RUN-025: {len(vins_2)}")

    # 6. STANDALONE COUNTERFACTUAL
    print("\n--- 6. Standalone Counterfactual ---")
    from counterfactual_engine import StateDependentCounterfactualEngine
    cf_engine = StateDependentCounterfactualEngine(dataset_dir)
    cf_1 = cf_engine.simulate_state_dependent_intervention('RUN-024', 'S03', 143)
    cf_2 = cf_engine.simulate_state_dependent_intervention('RUN-025', 'S16', 93)
    print(f"Standalone Counterfactual Rec -> RUN-024 @ S03 (Min 143): {cf_1['recommended_option']}")
    print(f"Standalone Counterfactual Rec -> RUN-025 @ S16 (Min 93): {cf_2['recommended_option']}")

if __name__ == "__main__":
    run_diagnostic()
