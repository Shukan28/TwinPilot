"""
TwinPilot: State-Dependent Counterfactual Intervention Engine
============================================================
Dynamically simulates the 3 UI interventions based on current factory state:
- Option A: Speed Override / Move Operator (Favored when Queue is High & Defect Risk is Low)
- Option B: Buffer / Throttle Upstream (Favored when Defect Risk is High / Critical)
- Option C: Workload Rebalance / Reroute (Favored when both Queue and Defect are elevated)
"""

import pandas as pd
import numpy as np
from propagation_engine import DefectModelService
from reinforcement_learning_policy import ContextualBanditRLPolicy, ACTIONS, ACTION_NAMES

class StateDependentCounterfactualEngine:
    def __init__(self, dataset_dir=r"twinpilot_dataset_extracted\twinpilot_dataset", rl_weights_path="rl_policy_weights.json"):
        self.dataset_dir = dataset_dir
        self.service = DefectModelService(dataset_dir)
        self.service.initialize_and_train()
        self.stations_df = pd.read_csv(f"{dataset_dir}/stations_master.csv")
        self.events_df = pd.read_csv(f"{dataset_dir}/events_ground_truth.csv")
        self.baseline_ct = dict(zip(self.stations_df["station_id"], self.stations_df["baseline_cycle_time_sec"]))
        self.tier_map = dict(zip(self.stations_df["station_id"], self.stations_df["sensor_tier"]))
        
        # Connect Trained Reinforcement Learning Policy Model
        self.rl_policy = ContextualBanditRLPolicy(model_path=rl_weights_path)

    def simulate_state_dependent_intervention(self, run_id, station_id, minute_index):
        """
        Simulates the 3 interventions conditioned on the exact state (CT, Queue, Defect Risk, Anomaly Type).
        Evaluates Q-values and action policy distributions via the trained Reinforcement Learning Agent.
        """
        sub = self.service.sensor_df_with_preds[
            (self.service.sensor_df_with_preds["run_id"] == run_id) &
            (self.service.sensor_df_with_preds["station_id"] == station_id) &
            (self.service.sensor_df_with_preds["minute_index"] == minute_index)
        ]
        
        if sub.empty:
            sub = self.service.sensor_df_with_preds[
                (self.service.sensor_df_with_preds["run_id"] == run_id) &
                (self.service.sensor_df_with_preds["station_id"] == station_id)
            ]
            if sub.empty:
                return None
            row = sub.iloc[0]
        else:
            row = sub.iloc[0]

        curr_ct = float(row["cycle_time_sec"]) if row["cycle_time_sec"] > 0 else self.baseline_ct.get(station_id, 45.0)
        curr_queue = float(row["queue_length"]) if row["queue_length"] >= 0 else 2.0
        curr_risk = float(row["defect_prob"])
        curr_bn = float(row.get("bottleneck_prob", 0.0) or 0.0)
        curr_vib = float(row.get("tool_vibration_mm_s", 0.80) or 0.80)
        base_ct = self.baseline_ct.get(station_id, 45.0)
        base_uph = 3600.0 / curr_ct if curr_ct > 0 else 80.0
        
        # State characterization
        slowdown_ratio = curr_ct / base_ct
        queue_severity = max(0.0, (curr_queue - 2.0) / 4.0)  # normalized queue stress
        risk_severity = curr_risk                           # 0 to 1

        # -------------------------------------------------------------
        # OPTION A: Speed Override / Move Operator
        # Dynamics: High throughput gain & strong queue clearance.
        # However, speed exacerbates existing mechanical faults:
        # If defect risk is already high, Option A creates heavy scrap.
        # -------------------------------------------------------------
        speedup_factor = min(0.25, 0.12 + 0.04 * queue_severity)
        ct_a = curr_ct * (1.0 - speedup_factor)
        uph_a = 3600.0 / ct_a
        pct_tput_a = ((uph_a - base_uph) / base_uph) * 100.0
        queue_delta_a = -min(curr_queue, max(1.5, 0.65 * curr_queue))
        risk_delta_a = + (0.03 + 0.40 * curr_risk + 0.08 * max(0.0, slowdown_ratio - 1.0))
        post_risk_a = min(1.0, curr_risk + risk_delta_a)
        tput_value_a = pct_tput_a * 140.0
        scrap_cost_a = post_risk_a * 550.0 * 20.0
        net_financial_a = tput_value_a - scrap_cost_a

        # -------------------------------------------------------------
        # OPTION B: Buffer / Throttle Upstream Station
        # Dynamics: Drastically reduces defect risk & tool stress.
        # However, it penalizes throughput and adds queue buffer upstream.
        # Best when defect risk is severe and scrap cost would be catastrophic.
        # -------------------------------------------------------------
        slow_factor = min(0.30, 0.12 + 0.10 * risk_severity)
        ct_b = curr_ct * (1.0 + slow_factor)
        uph_b = 3600.0 / ct_b
        pct_tput_b = ((uph_b - base_uph) / base_uph) * 100.0
        queue_delta_b = +max(1.0, 1.2 + 0.3 * curr_queue)
        risk_delta_b = -min(curr_risk * 0.75, 0.30)
        post_risk_b = max(0.01, curr_risk + risk_delta_b)
        tput_loss_b = abs(pct_tput_b) * 160.0
        scrap_saved_b = abs(risk_delta_b) * 550.0 * 20.0
        net_financial_b = scrap_saved_b - tput_loss_b

        # -------------------------------------------------------------
        # OPTION C: Workload Rebalance / Dynamic Reroute
        # Dynamics: Moderate throughput gain, moderate queue relief, moderate defect relief.
        # Incurs fixed rerouting/setup overhead ($250).
        # Best when both queue and defect risk are present (compromise).
        # -------------------------------------------------------------
        ct_c = curr_ct * 0.93
        uph_c = 3600.0 / ct_c
        pct_tput_c = ((uph_c - base_uph) / base_uph) * 100.0
        queue_delta_c = -min(curr_queue, max(1.0, 0.40 * curr_queue))
        risk_delta_c = -min(curr_risk * 0.35, 0.08)
        post_risk_c = max(0.01, curr_risk + risk_delta_c)
        reroute_overhead = 250.0
        tput_value_c = pct_tput_c * 140.0
        scrap_saved_c = abs(risk_delta_c) * 550.0 * 20.0
        net_financial_c = tput_value_c + scrap_saved_c - reroute_overhead

        # -------------------------------------------------------------
        # Reinforcement Learning Contextual Bandit Evaluation
        # -------------------------------------------------------------
        state_vec = ContextualBanditRLPolicy.extract_state_vector(
            cycle_time=curr_ct,
            baseline_ct=base_ct,
            queue=curr_queue,
            defect_prob=curr_risk,
            bottleneck_prob=curr_bn,
            vibration=curr_vib,
            tier=self.tier_map.get(station_id, "RICH")
        )
        rl_pred = self.rl_policy.predict(state_vec, temperature=0.6)

        options = {
            "Option A": {
                "name": "Speed Override / Move Operator",
                "tput_pct": round(pct_tput_a, 1),
                "queue_change": round(queue_delta_a, 1),
                "defect_risk_change": round(risk_delta_a * 100.0, 1),
                "financial_impact": round(net_financial_a, 0),
                "q_value": rl_pred["q_values"]["Option A"],
                "policy_prob_pct": rl_pred["policy_distribution"]["Option A"]
            },
            "Option B": {
                "name": "Buffer / Throttle Upstream",
                "tput_pct": round(pct_tput_b, 1),
                "queue_change": round(queue_delta_b, 1),
                "defect_risk_change": round(risk_delta_b * 100.0, 1),
                "financial_impact": round(net_financial_b, 0),
                "q_value": rl_pred["q_values"]["Option B"],
                "policy_prob_pct": rl_pred["policy_distribution"]["Option B"]
            },
            "Option C": {
                "name": "Workload Rebalance / Reroute",
                "tput_pct": round(pct_tput_c, 1),
                "queue_change": round(queue_delta_c, 1),
                "defect_risk_change": round(risk_delta_c * 100.0, 1),
                "financial_impact": round(net_financial_c, 0),
                "q_value": rl_pred["q_values"]["Option C"],
                "policy_prob_pct": rl_pred["policy_distribution"]["Option C"]
            }
        }

        best_opt = rl_pred["recommended_action"]
        conf = rl_pred["confidence_pct"]

        # State descriptor
        if curr_risk >= 0.25 and curr_queue <= 3.0:
            state_desc = f"High Defect Risk ({curr_risk*100:.0f}%), Low Queue ({curr_queue:.0f})"
        elif curr_queue >= 5.0 and curr_risk <= 0.10:
            state_desc = f"High Queue ({curr_queue:.0f}), Low Defect Risk ({curr_risk*100:.0f}%)"
        elif curr_queue >= 4.0 and curr_risk >= 0.15:
            state_desc = f"High Queue ({curr_queue:.0f}) + High Defect ({curr_risk*100:.0f}%)"
        else:
            state_desc = f"Queue = {curr_queue:.0f} | Risk = {curr_risk*100:.1f}% | CT = {curr_ct:.1f}s"

        return {
            "run_id": run_id,
            "station_id": station_id,
            "minute_index": minute_index,
            "current_ct": round(curr_ct, 2),
            "current_queue": round(curr_queue, 1),
            "current_defect_prob": round(curr_risk, 3),
            "state_desc": state_desc,
            "state_vector": [round(float(x), 3) for x in state_vec],
            "options": options,
            "recommended_option": best_opt,
            "confidence": round(conf, 1),
            "rl_q_values": rl_pred["q_values"],
            "rl_policy_distribution": rl_pred["policy_distribution"]
        }

    def evaluate_operator_lifecycle(self, simulation_result, operator_action="approve", observed_outcome=None):
        """
        Simulates the human approval step and executes an online Reinforcement Learning policy update:
        AI recommends -> operator approves/rejects -> RL agent receives reward/penalty -> model learns online.
        """
        rec_opt = simulation_result["recommended_option"]
        opt_details = simulation_result["options"][rec_opt]
        state_vec = simulation_result.get("state_vector") or ContextualBanditRLPolicy.extract_state_vector(
            cycle_time=simulation_result.get("current_ct", 46.0),
            baseline_ct=46.0,
            queue=simulation_result.get("current_queue", 2.0),
            defect_prob=simulation_result.get("current_defect_prob", 0.1),
            bottleneck_prob=0.0,
            vibration=1.0,
            tier="RICH"
        )

        is_approved = (operator_action.lower() == "approve")

        if is_approved:
            outcome_status = "Executed"
            realized_tput_gain = opt_details["tput_pct"]
            realized_defect_reduction = abs(opt_details["defect_risk_change"])
            realized_savings = opt_details["financial_impact"]
            notes = f"Operator approved {rec_opt} ({opt_details['name']}). Line stabilized."
        else:
            outcome_status = "Rejected (Manual Override)"
            realized_tput_gain = -8.0
            realized_defect_reduction = 0.0
            realized_savings = -500.0
            notes = f"Operator rejected {rec_opt}. Default manual override executed without counterfactual optimization."

        # Compute RL reward & update weights online
        reward = self.rl_policy.compute_reward(
            state_vector=state_vec,
            action_name=rec_opt,
            operator_action=operator_action,
            observed_outcome=observed_outcome,
            predicted_impact=opt_details
        )
        update_stats = self.rl_policy.update(state_vec, rec_opt, reward)

        return {
            "operator_action": operator_action.capitalize(),
            "outcome_status": outcome_status,
            "realized_tput_gain_pct": realized_tput_gain,
            "realized_defect_reduction_pct": realized_defect_reduction,
            "realized_financial_impact": realized_savings,
            "rl_reward_applied": reward,
            "rl_update_stats": update_stats,
            "audit_log": notes
        }

