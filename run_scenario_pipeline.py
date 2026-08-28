"""
TwinPilot: End-to-End Scenario Runner & Decision Pipeline (Aligned)
===================================================================
Integrated intelligence pipeline aligned with validated standalone subsystems:
- Bottleneck Model v1 (train_model.py)
- Defect Model v2 (defect_model.py / propagation_engine.py)
- Dark Zone Sensorless Inference (dark_zone_inference.py)
- 3-Factor Root Cause Engine (root_cause_engine.py)
- Dependency Graph Propagation with tau=0.02 (tune_and_validate_propagation.py)
- VIN Arrival Tracing (propagation_engine.py)
- State-Dependent Counterfactuals (counterfactual_engine.py)
"""

import pandas as pd
# pyrefly: ignore [missing-import]
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from root_cause_engine import RootCauseEngine
from counterfactual_engine import StateDependentCounterfactualEngine
from dark_zone_inference import build_vectorized_dark_zone_dataset

class TwinPilotPipeline:
    def __init__(self, dataset_dir=r"twinpilot_dataset_extracted\twinpilot_dataset"):
        self.dataset_dir = dataset_dir
        
        # 1. Root Cause & Propagation Engine (with trained Defect Model v2)
        self.rc_engine = RootCauseEngine(dataset_dir)
        self.defect_service = self.rc_engine.service
        
        # 2. State-Dependent Counterfactual Engine
        self.cf_engine = StateDependentCounterfactualEngine(dataset_dir)
        
        # 3. Train Bottleneck Model v1 on RUN-001..RUN-015
        self._train_bottleneck_model()
        
        # 4. Train Dark Zone Inference Model on RUN-001..RUN-015
        self._train_dark_zone_model()
        
        self.stations_df = self.defect_service.stations_df
        self.dependencies_df = self.defect_service.dependencies_df
        self.vehicles_df = pd.read_csv(f"{dataset_dir}/vehicles.csv")
        self.events_df = pd.read_csv(f"{dataset_dir}/events_ground_truth.csv")

    def _train_bottleneck_model(self):
        sensor_df = pd.read_csv(f"{self.dataset_dir}/sensor_timeseries.csv")
        events_df = pd.read_csv(f"{self.dataset_dir}/events_ground_truth.csv")
        
        bottlenecks = events_df[events_df['event_type'] == 'bottleneck']
        merged = pd.merge(
            sensor_df, bottlenecks[['run_id', 'origin_station_id', 'peak_minute']],
            left_on=['run_id', 'station_id'],
            right_on=['run_id', 'origin_station_id'],
            how='left'
        )
        time_to_peak = merged['peak_minute'] - merged['minute_index']
        sensor_df['bottleneck_15min_ahead'] = ((time_to_peak > 0) & (time_to_peak <= 15)).astype(int)
        
        base_features = ['cycle_time_sec', 'queue_length', 'vibration_mm_s', 'torque_nm', 'temperature_c']
        sensor_df[base_features] = sensor_df[base_features].fillna(-1)
        sensor_df = sensor_df.sort_values(by=['run_id', 'station_id', 'minute_index'])
        grouped = sensor_df.groupby(['run_id', 'station_id'])
        
        sensor_df['avg_cycle_time_5m'] = grouped['cycle_time_sec'].rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
        sensor_df['avg_cycle_time_10m'] = grouped['cycle_time_sec'].rolling(10, min_periods=1).mean().reset_index(level=[0,1], drop=True)
        sensor_df['avg_queue_5m'] = grouped['queue_length'].rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
        sensor_df['avg_queue_10m'] = grouped['queue_length'].rolling(10, min_periods=1).mean().reset_index(level=[0,1], drop=True)
        sensor_df['change_cycle_time_5m'] = sensor_df['cycle_time_sec'] - grouped['cycle_time_sec'].shift(5).fillna(sensor_df['cycle_time_sec'])
        sensor_df['change_cycle_time_10m'] = sensor_df['cycle_time_sec'] - grouped['cycle_time_sec'].shift(10).fillna(sensor_df['cycle_time_sec'])
        sensor_df['queue_growth_5m'] = sensor_df['queue_length'] - grouped['queue_length'].shift(5).fillna(sensor_df['queue_length'])
        sensor_df['queue_growth_10m'] = sensor_df['queue_length'] - grouped['queue_length'].shift(10).fillna(sensor_df['queue_length'])
        sensor_df['change_vibration_5m'] = sensor_df['vibration_mm_s'] - grouped['vibration_mm_s'].shift(5).fillna(sensor_df['vibration_mm_s'])
        sensor_df['change_torque_5m'] = sensor_df['torque_nm'] - grouped['torque_nm'].shift(5).fillna(sensor_df['torque_nm'])

        self.bn_features = base_features + [
            'avg_cycle_time_5m', 'avg_cycle_time_10m', 'change_cycle_time_5m', 'change_cycle_time_10m',
            'avg_queue_5m', 'avg_queue_10m', 'queue_growth_5m', 'queue_growth_10m',
            'change_vibration_5m', 'change_torque_5m'
        ]
        
        train_runs = [f'RUN-{str(i).zfill(3)}' for i in range(1, 16)]
        X_train = sensor_df[sensor_df['run_id'].isin(train_runs)][self.bn_features]
        y_train = sensor_df[sensor_df['run_id'].isin(train_runs)]['bottleneck_15min_ahead']
        
        self.bn_model = RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1, class_weight='balanced')
        self.bn_model.fit(X_train, y_train)
        
        sensor_df['bottleneck_prob'] = self.bn_model.predict_proba(sensor_df[self.bn_features])[:, 1]
        self.bn_sensor_df = sensor_df

    def _train_dark_zone_model(self):
        dz_data, self.manual_stations, _ = build_vectorized_dark_zone_dataset(self.dataset_dir)
        self.dz_feature_cols = [c for c in dz_data.columns if c not in ["run_id", "minute_index", "target_station", "is_degrading"]]
        train_runs = [f"RUN-{str(i).zfill(3)}" for i in range(1, 16)]
        train_df = dz_data[dz_data["run_id"].isin(train_runs)]
        
        self.dz_model = RandomForestClassifier(n_estimators=150, random_state=42, n_jobs=-1, class_weight="balanced")
        self.dz_model.fit(train_df[self.dz_feature_cols], train_df["is_degrading"])
        self.dz_dataset = dz_data

    def run_scenario(self, run_id, minute_index, target_station=None, event_id=None):
        """
        Executes the entire TwinPilot decision loop for a given run and minute.
        """
        # Look up ground truth event details if provided
        ev_meta = None
        if event_id:
            match_ev = self.events_df[self.events_df["event_id"] == event_id]
            if not match_ev.empty:
                ev_meta = match_ev.iloc[0]

        start_m = ev_meta["start_minute"] if ev_meta is not None else max(0, minute_index - 15)
        peak_m = ev_meta["peak_minute"] if ev_meta is not None else minute_index + 10
        resolved_m = ev_meta["resolved_minute"] if ev_meta is not None else minute_index + 40
        eval_station = target_station or (ev_meta["origin_station_id"] if ev_meta is not None else "S01")

        # 1. Telemetry Ingestion
        sensor_snap = self.defect_service.sensor_df_with_preds[
            (self.defect_service.sensor_df_with_preds["run_id"] == run_id) &
            (self.defect_service.sensor_df_with_preds["minute_index"] == minute_index)
        ].copy()

        bn_snap = self.bn_sensor_df[
            (self.bn_sensor_df["run_id"] == run_id) &
            (self.bn_sensor_df["minute_index"] == minute_index)
        ].copy()

        sensor_snap = pd.merge(sensor_snap, bn_snap[["station_id", "bottleneck_prob"]], on="station_id", how="left")
        origin_row = sensor_snap[sensor_snap["station_id"] == eval_station].iloc[0]

        # 2. Dark Zone Status
        dz_snap = self.dz_dataset[
            (self.dz_dataset["run_id"] == run_id) &
            (self.dz_dataset["minute_index"] == minute_index)
        ].copy()
        dz_preds = self.dz_model.predict_proba(dz_snap[self.dz_feature_cols])[:, 1]
        dz_snap["dz_prob"] = dz_preds
        flagged_dz = dz_snap[dz_snap["dz_prob"] >= 0.25]

        # 3. Root Cause Localization
        pred_origin = self.rc_engine.predict_origin(run_id, start_m, peak_m)

        # 4. Propagation Path Traversal (Frozen tau = 0.02)
        risk_map = self.defect_service.get_station_risk_at_time(run_id, start_m, peak_m + 5)
        pred_path, path_scores = self.defect_service.predict_propagation_path(
            origin_station=eval_station,
            risk_map=risk_map,
            max_hops=10,
            min_risk_threshold=0.02
        )

        # 5. At-Risk VIN Identification
        at_risk_vins_df = self.defect_service.identify_at_risk_vins(
            run_id, pred_path, start_m, resolved_m
        )
        at_risk_count = len(at_risk_vins_df)
        sample_vins = at_risk_vins_df["vin"].head(5).tolist() if at_risk_count > 0 else []

        # 6. Counterfactual Simulation
        sim_result = self.cf_engine.simulate_state_dependent_intervention(run_id, eval_station, minute_index)
        opts = sim_result["options"]
        rec_opt = sim_result["recommended_option"]
        conf = sim_result["confidence"]

        operator_log = self.cf_engine.evaluate_operator_lifecycle(
            {"recommended_option": rec_opt, "options": opts}, operator_action="approve"
        )

        return {
            "run_id": run_id,
            "minute_index": minute_index,
            "event_id": event_id,
            "station": eval_station,
            "ct": origin_row["cycle_time_sec"],
            "queue": origin_row["queue_length"],
            "bottleneck_prob": origin_row["bottleneck_prob"],
            "defect_prob": origin_row["defect_prob"],
            "dz_flagged": flagged_dz,
            "root_cause": pred_origin,
            "propagation_path": pred_path,
            "path_scores": path_scores,
            "at_risk_vins_count": at_risk_count,
            "sample_vins": sample_vins,
            "options": opts,
            "recommended_option": rec_opt,
            "confidence": conf,
            "operator_log": operator_log
        }
