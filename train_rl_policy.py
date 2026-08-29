"""
TwinPilot: Reinforcement Learning Policy Training Script
=========================================================
Trains the Contextual Bandit / Q-Learning Policy using all 25 manufacturing production runs
and ground-truth event anomalies from the dataset.

Evaluates:
  1. Policy action distribution across state regimes (High Risk, High Queue, Mixed)
  2. Convergence of learned weights theta_a
  3. Cumulative reward trajectory and policy value improvement
  4. Sensitivity to operator approvals (+Reward) vs operator rejections (-Penalty)
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import os
import math
import json
# pyrefly: ignore [missing-import]
import numpy as np
import pandas as pd
from reinforcement_learning_policy import ContextualBanditRLPolicy, ACTIONS, ACTION_NAMES

DATASET_DIR = r"twinpilot_dataset_extracted\twinpilot_dataset"


def train_reinforcement_learning_agent(num_episodes=3000, dataset_dir=DATASET_DIR):
    print("=" * 80)
    print("TWINPILOT: TRAINING REINFORCEMENT LEARNING INTERVENTION POLICY")
    print("=" * 80)

    # 1. Load Dataset
    stations_df = pd.read_csv(f"{dataset_dir}/stations_master.csv")
    events_df = pd.read_csv(f"{dataset_dir}/events_ground_truth.csv")
    sensor_df = pd.read_csv(f"{dataset_dir}/sensor_timeseries.csv")
    print(f"Loaded {len(stations_df)} stations, {len(events_df)} ground-truth events, {len(sensor_df):,} sensor records.")

    base_ct_map = dict(zip(stations_df["station_id"], stations_df["baseline_cycle_time_sec"]))
    tier_map = dict(zip(stations_df["station_id"], stations_df["sensor_tier"]))

    # 2. Instantiate RL Agent
    rl_agent = ContextualBanditRLPolicy(
        state_dim=6,
        num_actions=3,
        alpha=0.8,
        l2_reg=0.5,
        model_path="rl_policy_weights.json"
    )

    # 3. Generate Training Dataset from Real Manufacturing Telemetry
    training_states = []
    
    # A. Anomaly event states from events_ground_truth
    for _, evt in events_df.iterrows():
        rid = evt["run_id"]
        sid = evt["origin_station_id"]
        start_m = int(evt["start_minute"])
        peak_m = int(evt["peak_minute"])

        # Sample across pre-peak to peak minutes
        for m in range(max(0, start_m - 5), min(240, peak_m + 5), 2):
            sub = sensor_df[(sensor_df["run_id"] == rid) & (sensor_df["station_id"] == sid) & (sensor_df["minute_index"] == m)]
            if sub.empty:
                continue
            row = sub.iloc[0]
            ct = float(row.get("cycle_time_sec", 45.0) or 45.0)
            q = float(row.get("queue_length", 0.0) or 0.0)
            vib = float(row.get("tool_vibration_mm_s", 0.80) or 0.80)
            d_risk = float(row.get("defect_prob", 0.0) or 0.0)
            bn_risk = float(row.get("bottleneck_prob", 0.0) or 0.0)
            
            # Extract state vector
            s = rl_agent.extract_state_vector(
                cycle_time=ct,
                baseline_ct=base_ct_map.get(sid, 45.0),
                queue=q,
                defect_prob=d_risk,
                bottleneck_prob=bn_risk,
                vibration=vib,
                tier=tier_map.get(sid, "RICH")
            )
            training_states.append(s)

    # B. Add nominal and boundary states across all runs
    for rid in sensor_df["run_id"].unique()[:10]:
        for sid in ["S01", "S03", "S08", "S14", "S16", "S21", "S28", "ENG01"]:
            for m in [30, 60, 90, 120, 150, 180]:
                sub = sensor_df[(sensor_df["run_id"] == rid) & (sensor_df["station_id"] == sid) & (sensor_df["minute_index"] == m)]
                if sub.empty:
                    continue
                row = sub.iloc[0]
                ct = float(row.get("cycle_time_sec", 45.0) or 45.0)
                q = float(row.get("queue_length", 0.0) or 0.0)
                vib = float(row.get("tool_vibration_mm_s", 0.80) or 0.80)
                d_risk = float(row.get("defect_prob", 0.0) or 0.0)
                bn_risk = float(row.get("bottleneck_prob", 0.0) or 0.0)
                s = rl_agent.extract_state_vector(
                    cycle_time=ct,
                    baseline_ct=base_ct_map.get(sid, 45.0),
                    queue=q,
                    defect_prob=d_risk,
                    bottleneck_prob=bn_risk,
                    vibration=vib,
                    tier=tier_map.get(sid, "RICH")
                )
                training_states.append(s)

    print(f"Extracted {len(training_states)} distinct manufacturing state vectors for RL training.")

    # 4. Training Loop with Exploration & Environmental Dynamics
    np.random.seed(42)
    cumulative_rewards = []
    action_history = []
    
    print("\nTraining Reinforcement Learning Policy across episodes...")
    for ep in range(num_episodes):
        # Sample a random state from empirical distribution
        state = training_states[np.random.randint(len(training_states))]
        ct_drift, q_norm, d_risk, bn_risk, vib_norm, tier_enc = state

        # Epsilon-greedy / UCB exploration
        epsilon = max(0.05, 0.50 * (1.0 - ep / num_episodes))
        pred = rl_agent.predict(state)
        
        if np.random.rand() < epsilon:
            chosen_action_idx = np.random.randint(3)
        else:
            chosen_action_idx = pred["best_action_idx"]
            
        chosen_action = ACTIONS[chosen_action_idx]

        # Environmental Counterfactual Simulator dynamics
        # Option A: Speed Override (favored when queue is high, punished when defect is high)
        # Option B: Buffer Throttle (favored when defect is high, punished when queue is high)
        # Option C: Workload Rebalance (compromise, optimal when both queue and defect risk are present)
        
        if chosen_action == "Option A":
            pct_tput = +12.0 + 8.0 * q_norm
            q_delta = -max(1.0, 2.5 * q_norm)
            d_delta = +(d_risk * 15.0 + 5.0 * vib_norm)
            fin_impact = (pct_tput * 140.0) - (d_risk * 600.0 * 20.0)
            # Operator decision probability: High queue + Low defect = Optimal for Option A
            approval_prob = 0.96 if (d_risk < 0.12 and q_norm >= 0.25) else (0.35 if d_risk < 0.15 else 0.08)
        elif chosen_action == "Option B":
            pct_tput = -(8.0 + 6.0 * d_risk)
            q_delta = +(1.5 + 2.0 * d_risk)
            d_delta = -min(25.0, d_risk * 75.0)
            fin_impact = (abs(d_delta) / 100.0 * 600.0 * 20.0) - (abs(pct_tput) * 160.0)
            # High defect + Low queue = Optimal for Option B
            approval_prob = 0.95 if (d_risk >= 0.25 and q_norm < 0.35) else 0.15
        else: # Option C
            pct_tput = +7.5
            q_delta = -max(1.0, 1.8 * q_norm)
            d_delta = -min(15.0, d_risk * 35.0)
            fin_impact = (pct_tput * 140.0) + (abs(d_delta) / 100.0 * 600.0 * 20.0) - 250.0
            # Both queue and defect elevated = Optimal for Option C
            approval_prob = 0.96 if (d_risk >= 0.15 and q_norm >= 0.25) or (d_risk >= 0.10 and bn_risk >= 0.2) else (0.15 if d_risk < 0.12 else 0.40)

        # Simulate Human-in-the-Loop decision
        operator_action = "approve" if (np.random.rand() < approval_prob) else "reject"

        # Compute RL reward
        predicted_impact = {
            "tput_pct": pct_tput,
            "queue_change": q_delta,
            "defect_risk_change": d_delta,
            "financial_impact": fin_impact
        }
        reward = rl_agent.compute_reward(
            state_vector=state,
            action_name=chosen_action,
            operator_action=operator_action,
            observed_outcome=None,
            predicted_impact=predicted_impact
        )

        # Update RL Model online
        rl_agent.update(state, chosen_action, reward)
        cumulative_rewards.append(reward)
        action_history.append(chosen_action)

        if (ep + 1) % 600 == 0:
            avg_rew = np.mean(cumulative_rewards[-600:])
            print(f"  Episode {ep+1:4d}/{num_episodes} | Mean Reward: {avg_rew:+7.2f} | Epsilon: {epsilon:.3f} | Actions (A/B/C): {rl_agent.action_counts}")

    # 5. Save Model
    rl_agent.save("rl_policy_weights.json")
    print(f"\nTrained weights successfully saved to rl_policy_weights.json.")

    # 6. Evaluation on Benchmark Regimes
    print("\n" + "=" * 80)
    print("REINFORCEMENT LEARNING POLICY EVALUATION BENCHMARK")
    print("=" * 80)

    test_cases = [
        ("High Queue + Low Defect (Bottleneck Jitter)", [0.4, 1.2, 0.02, 0.8, 0.2, 1.0]),
        ("Low Queue + Critical Defect Spike", [0.2, 0.1, 0.45, 0.05, 1.8, 1.0]),
        ("RUN-024 S03 Defect Surge (Mixed Queue + Defect Risk)", [0.25, 0.67, 0.355, 0.0, 0.40, 1.0]),
        ("RUN-025 S16 Mechanical Delay + Dark Zone S21", [0.35, 0.53, 0.06, 0.42, 0.85, 0.5]),
        ("Nominal Baseline Operational State", [0.0, 0.0, 0.0, 0.0, 0.02, 1.0])
    ]

    for title, s_vec in test_cases:
        eval_pred = rl_agent.predict(s_vec, temperature=0.5)
        print(f"\nScenario: {title}")
        print(f"  State Vector:          {s_vec}")
        print(f"  Q-Values:              {eval_pred['q_values']}")
        print(f"  Policy Probabilities:  {eval_pred['policy_distribution']}")
        print(f"  Recommended Action:    {eval_pred['recommended_action']} ({ACTION_NAMES[eval_pred['recommended_action']]})")
        print(f"  Model Confidence:      {eval_pred['confidence_pct']}%")

    print("\n" + "=" * 80)
    print("RL TRAINING & EVALUATION COMPLETED SUCCESSFULLY")
    print("=" * 80)


if __name__ == "__main__":
    train_reinforcement_learning_agent()
