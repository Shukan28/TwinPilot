"""
TwinPilot Data-Driven Propagation & VIN Impact Engine
======================================================
1. Computes station-level defect probabilities using trained Defect Model v2.
2. Traverses factory dependency graph using station risk scores to predict propagation path.
3. Traces affected time window to vehicle arrival times to identify at-risk VINs.
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier

class DefectModelService:
    def __init__(self, dataset_dir=r"twinpilot_dataset_extracted\twinpilot_dataset"):
        self.dataset_dir = dataset_dir
        self.model = None
        self.features = None
        self.stations_df = None
        self.dependencies_df = None
        self.downstream_map = {}
        self.cum_offset_sec = {}
        self.variant_mult = {"Sedan": 1.0, "SUV": 1.05, "EV": 1.12}
        self.sensor_df_with_preds = None

    def initialize_and_train(self, train_runs=None, val_runs=None):
        """Loads data, generates features, builds dependency graph, and trains Defect Model v2."""
        sensor_df = pd.read_csv(f"{self.dataset_dir}/sensor_timeseries.csv")
        events_df = pd.read_csv(f"{self.dataset_dir}/events_ground_truth.csv")
        stations_df = pd.read_csv(f"{self.dataset_dir}/stations_master.csv")
        dependencies_df = pd.read_csv(f"{self.dataset_dir}/station_dependencies.csv")

        self.stations_df = stations_df
        self.dependencies_df = dependencies_df

        # Build downstream lookup map
        self.downstream_map = (
            dependencies_df
            .groupby("from_station")["to_station"]
            .apply(list)
            .to_dict()
        )

        # Build cumulative cycle time offsets for VIN arrival calculation
        main_line_only = stations_df[stations_df["station_id"] != "ENG01"].sort_values("sequence_order")
        running = 0.0
        for _, row in main_line_only.iterrows():
            running += float(row["baseline_cycle_time_sec"])
            self.cum_offset_sec[row["station_id"]] = running

        # Ground truth labels for 15-min ahead defect
        defects = events_df[events_df['event_type'] == 'defect_propagation']
        rows = []
        for _, event in defects.iterrows():
            path_stations = [s.strip() for s in event['propagation_path'].split(',')]
            for station in path_stations:
                rows.append({
                    'run_id': event['run_id'],
                    'station_id': station,
                    'peak_minute': event['peak_minute'],
                    'start_minute': event['start_minute'],
                    'resolved_minute': event['resolved_minute'],
                    'event_id': event['event_id'],
                    'origin_station_id': event['origin_station_id']
                })
        defect_labels = pd.DataFrame(rows)

        merged = pd.merge(
            sensor_df, defect_labels[['run_id', 'station_id', 'peak_minute']],
            on=['run_id', 'station_id'],
            how='left'
        )
        time_to_peak = merged['peak_minute'] - merged['minute_index']
        sensor_df['defect_15min_ahead'] = ((time_to_peak > 0) & (time_to_peak <= 15)).astype(int)

        # Structural features
        stations_df_num = stations_df.copy()
        stations_df_num['station_num'] = pd.to_numeric(
            stations_df_num['station_id'].str.replace('S', '', regex=False), errors='coerce'
        )
        stations_df_num = stations_df_num.dropna(subset=['station_num'])
        stations_df_num['station_num'] = stations_df_num['station_num'].astype(int)
        sensor_df = pd.merge(sensor_df, stations_df_num[['station_id', 'station_num']], on='station_id', how='left')

        # Impute missing sensors
        base_features = ['cycle_time_sec', 'queue_length', 'vibration_mm_s', 'torque_nm', 'temperature_c']
        sensor_df[base_features] = sensor_df[base_features].fillna(-1)

        # Temporal features
        sensor_df = sensor_df.sort_values(by=['run_id', 'station_id', 'minute_index'])
        grouped = sensor_df.groupby(['run_id', 'station_id'])

        sensor_df['avg_cycle_time_5m']  = grouped['cycle_time_sec'].rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
        sensor_df['avg_cycle_time_10m'] = grouped['cycle_time_sec'].rolling(10, min_periods=1).mean().reset_index(level=[0,1], drop=True)
        sensor_df['avg_queue_5m']       = grouped['queue_length'].rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
        sensor_df['avg_queue_10m']      = grouped['queue_length'].rolling(10, min_periods=1).mean().reset_index(level=[0,1], drop=True)
        sensor_df['avg_torque_5m']      = grouped['torque_nm'].rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
        sensor_df['avg_vibration_5m']   = grouped['vibration_mm_s'].rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)

        sensor_df['change_cycle_time_5m']  = sensor_df['cycle_time_sec'] - grouped['cycle_time_sec'].shift(5).fillna(sensor_df['cycle_time_sec'])
        sensor_df['change_cycle_time_10m'] = sensor_df['cycle_time_sec'] - grouped['cycle_time_sec'].shift(10).fillna(sensor_df['cycle_time_sec'])
        sensor_df['queue_growth_5m']       = sensor_df['queue_length']   - grouped['queue_length'].shift(5).fillna(sensor_df['queue_length'])
        sensor_df['queue_growth_10m']      = sensor_df['queue_length']   - grouped['queue_length'].shift(10).fillna(sensor_df['queue_length'])
        sensor_df['change_torque_5m']      = sensor_df['torque_nm']      - grouped['torque_nm'].shift(5).fillna(sensor_df['torque_nm'])
        sensor_df['change_torque_10m']     = sensor_df['torque_nm']      - grouped['torque_nm'].shift(10).fillna(sensor_df['torque_nm'])
        sensor_df['change_vibration_5m']   = sensor_df['vibration_mm_s'] - grouped['vibration_mm_s'].shift(5).fillna(sensor_df['vibration_mm_s'])
        sensor_df['change_vibration_10m']  = sensor_df['vibration_mm_s'] - grouped['vibration_mm_s'].shift(10).fillna(sensor_df['vibration_mm_s'])

        self.features = base_features + [
            'station_num',
            'avg_cycle_time_5m', 'avg_cycle_time_10m',
            'change_cycle_time_5m', 'change_cycle_time_10m',
            'avg_queue_5m', 'avg_queue_10m',
            'queue_growth_5m', 'queue_growth_10m',
            'avg_torque_5m', 'change_torque_5m', 'change_torque_10m',
            'avg_vibration_5m', 'change_vibration_5m', 'change_vibration_10m',
        ]

        if train_runs is None:
            train_runs = [f'RUN-{str(i).zfill(3)}' for i in range(1, 16)]

        X_train = sensor_df[sensor_df['run_id'].isin(train_runs)][self.features]
        y_train = sensor_df[sensor_df['run_id'].isin(train_runs)]['defect_15min_ahead']

        self.model = RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=-1, class_weight='balanced')
        self.model.fit(X_train, y_train)

        # Precompute probabilities for the entire dataset for fast querying
        sensor_df['defect_prob'] = self.model.predict_proba(sensor_df[self.features])[:, 1]
        self.sensor_df_with_preds = sensor_df
        return self

    def get_station_risk_at_time(self, run_id, minute_start, minute_end=None):
        """
        Returns a dictionary mapping station_id -> max predicted defect probability
        over the given minute window for the specified run.
        """
        if minute_end is None:
            minute_end = minute_start

        sub = self.sensor_df_with_preds[
            (self.sensor_df_with_preds['run_id'] == run_id) &
            (self.sensor_df_with_preds['minute_index'] >= minute_start) &
            (self.sensor_df_with_preds['minute_index'] <= minute_end)
        ]
        if sub.empty:
            return {}
        risk_map = sub.groupby('station_id')['defect_prob'].max().to_dict()
        return risk_map

    def predict_propagation_path(self, origin_station, risk_map, max_hops=10, min_risk_threshold=0.10):
        """
        Traverses factory dependency graph starting at origin_station.
        At each hop, checks the model defect probability.
        Propagation continues downstream as long as station risk exceeds min_risk_threshold.
        Returns:
            path: list of station IDs [S_origin, S_1, ..., S_k]
            path_scores: dict mapping station ID -> model risk score
        """
        path = [origin_station]
        path_scores = {origin_station: risk_map.get(origin_station, 0.0)}
        current = origin_station

        for _ in range(max_hops):
            next_stations = self.downstream_map.get(current, [])
            if not next_stations:
                break

            # Check downstream candidates
            best_candidate = None
            best_risk = -1.0

            for candidate in next_stations:
                cand_risk = risk_map.get(candidate, 0.0)
                if cand_risk > best_risk:
                    best_risk = cand_risk
                    best_candidate = candidate

            # If downstream station risk falls below threshold, propagation stops
            if best_candidate is None or best_risk < min_risk_threshold or best_candidate in path:
                break

            path.append(best_candidate)
            path_scores[best_candidate] = best_risk
            current = best_candidate

        return path, path_scores

    def get_vehicle_arrival_minute(self, entry_minute, variant, station_id):
        """Computes vehicle arrival minute at a given station."""
        mult = self.variant_mult.get(variant, 1.0)
        offset_sec = self.cum_offset_sec.get(station_id, 0.0)
        return entry_minute + (offset_sec * mult) / 60.0

    def identify_at_risk_vins(self, run_id, propagation_path, start_minute, resolved_minute):
        """
        Identifies vehicles that pass through the affected propagation stations
        during the active defect window.
        Returns DataFrame of at-risk VINs with estimated arrival times.
        """
        vehicles_df = pd.read_csv(f"{self.dataset_dir}/vehicles.csv")
        run_vehicles = vehicles_df[vehicles_df["run_id"] == run_id].copy()

        at_risk_records = []
        origin_station = propagation_path[0] if propagation_path else None

        for _, v in run_vehicles.iterrows():
            entry_min = float(v["line_entry_minute"])
            variant = v["model_variant"]
            vin = v["vin"]

            # Vehicle arrival at origin station
            arr_origin = self.get_vehicle_arrival_minute(entry_min, variant, origin_station)
            
            # Check if vehicle was at origin during event window
            if start_minute <= arr_origin <= resolved_minute:
                at_risk_records.append({
                    "vin": vin,
                    "model_variant": variant,
                    "line_entry_minute": entry_min,
                    "arrival_at_origin": round(arr_origin, 2),
                    "origin_station": origin_station,
                    "propagation_path": " -> ".join(propagation_path),
                    "ground_truth_defect_risk": v["defect_risk"],
                    "ground_truth_affected_events": str(v["affected_events"])
                })

        return pd.DataFrame(at_risk_records)
