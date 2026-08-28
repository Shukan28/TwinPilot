"""
TwinPilot: Root-Cause Scoring Engine (Magnitude + Onset Timing + Directionality)
"""

import pandas as pd
# pyrefly: ignore [missing-import]
import numpy as np
from propagation_engine import DefectModelService

class RootCauseEngine:
    def __init__(self, dataset_dir=r"twinpilot_dataset_extracted\twinpilot_dataset"):
        self.dataset_dir = dataset_dir
        self.service = DefectModelService(dataset_dir)
        self.service.initialize_and_train()
        
        self.dependencies_df = pd.read_csv(f"{dataset_dir}/station_dependencies.csv")
        self.stations_df = pd.read_csv(f"{dataset_dir}/stations_master.csv")
        self.events_df = pd.read_csv(f"{dataset_dir}/events_ground_truth.csv")
        self.vehicles_df = pd.read_csv(f"{dataset_dir}/vehicles.csv")
        
        self.downstream_map = self.dependencies_df.groupby("from_station")["to_station"].apply(list).to_dict()
        self.upstream_map = self.dependencies_df.groupby("to_station")["from_station"].apply(list).to_dict()

    def get_all_downstream(self, st):
        """Returns all reachable downstream stations along the dependency graph."""
        visited = []
        curr = [st]
        while curr:
            nxt = []
            for s in curr:
                for d in self.downstream_map.get(s, []):
                    if d not in visited and d != st:
                        visited.append(d)
                        nxt.append(d)
            curr = nxt
        return visited

    def get_all_upstream(self, st):
        """Returns all reachable upstream stations."""
        visited = []
        curr = [st]
        while curr:
            nxt = []
            for s in curr:
                for u in self.upstream_map.get(s, []):
                    if u not in visited and u != st:
                        visited.append(u)
                        nxt.append(u)
            curr = nxt
        return visited

    def score_candidate_origins(self, run_id, start_min, peak_min, onset_threshold=0.03):
        """
        Scores each candidate station using:
        1. Risk Magnitude: Peak and sustained anomaly evidence at the candidate station.
        2. Risk Onset Timing: Minute when the station began its anomalous ascent.
        3. Directionality: Whether candidate is upstream of other high-risk stations it explains,
           penalized if an upstream station showed high risk earlier.
        """
        sub = self.service.sensor_df_with_preds[
            (self.service.sensor_df_with_preds["run_id"] == run_id) &
            (self.service.sensor_df_with_preds["minute_index"] >= max(0, start_min - 5)) &
            (self.service.sensor_df_with_preds["minute_index"] <= peak_min + 5)
        ].copy()

        if sub.empty:
            return {}

        st_stats = {}
        window_duration = max(1, (peak_min + 5) - max(0, start_min - 5))

        for sid, grp in sub.groupby("station_id"):
            max_prob = grp["defect_prob"].max()
            top3_mean = grp["defect_prob"].nlargest(3).mean()
            
            # Find earliest minute crossing onset_threshold
            cross = grp[grp["defect_prob"] >= onset_threshold]
            if not cross.empty:
                onset_min = cross["minute_index"].min()
            else:
                onset_min = peak_min + 10

            st_stats[sid] = {
                "max_prob": max_prob,
                "top3_mean": top3_mean,
                "onset_min": onset_min
            }

        candidate_scores = {}
        for sid, stats in st_stats.items():
            if stats["max_prob"] < onset_threshold:
                continue

            # 1. Magnitude Evidence
            mag_score = stats["top3_mean"]

            # 2. Onset Timing Score (earlier onset receives higher score, range [0, 1])
            onset_score = max(0.0, (peak_min + 5 - stats["onset_min"]) / window_duration)

            # 3. Directionality / Topology Influence
            downstream_nodes = self.get_all_downstream(sid)
            upstream_nodes = self.get_all_upstream(sid)

            # Downstream influence: risk mass in downstream stations that rose at or after sid
            downstream_influence = 0.0
            for d in downstream_nodes:
                if d in st_stats and st_stats[d]["max_prob"] >= onset_threshold:
                    if st_stats[d]["onset_min"] >= stats["onset_min"] - 2:
                        downstream_influence += st_stats[d]["max_prob"]

            # Upstream penalty: high risk in upstream stations that rose before sid
            upstream_penalty = 0.0
            for u in upstream_nodes:
                if u in st_stats and st_stats[u]["max_prob"] >= 0.08:
                    if st_stats[u]["onset_min"] < stats["onset_min"]:
                        upstream_penalty += st_stats[u]["max_prob"]

            # Combined 3-Factor Root Cause Score
            score = mag_score * (1.0 + 1.2 * downstream_influence) * (1.0 + 0.8 * onset_score) / (1.0 + 2.5 * upstream_penalty)
            candidate_scores[sid] = {
                "total_score": score,
                "magnitude": mag_score,
                "onset_score": onset_score,
                "downstream_influence": downstream_influence,
                "upstream_penalty": upstream_penalty
            }

        return candidate_scores

    def predict_origin(self, run_id, start_min, peak_min):
        scores = self.score_candidate_origins(run_id, start_min, peak_min)
        if not scores:
            return "S01"
        sorted_candidates = sorted(scores.items(), key=lambda x: x[1]["total_score"], reverse=True)
        return sorted_candidates[0][0]
