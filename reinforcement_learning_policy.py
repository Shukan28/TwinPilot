"""
TwinPilot: Reinforcement Learning Policy Engine for Human-in-the-Loop Manufacturing Interventions
==================================================================================================
Implements a Contextual Bandit / Q-Learning Policy that learns optimal intervention selection
from operator feedback (Approvals = Positive Reward, Rejections = Penalty) and observed post-intervention
telemetry outcomes (Throughput Delta, Queue Reduction, Scrap Reduction, Net Financial Gain).

Mathematical Formulation:
-------------------------
State Space s in R^6:
  s_1: Normalized Cycle Time Drift = clamp((CT - Baseline_CT) / Baseline_CT, -0.5, 1.5)
  s_2: Normalized Buffer Queue Severity = clamp(Queue / 15.0, 0.0, 2.0)
  s_3: Defect Propagation Risk Probability = [0.0, 1.0]
  s_4: Bottleneck Accumulation Probability = [0.0, 1.0]
  s_5: Normalized Tool Vibration Deviation = clamp((Vibration - 0.75) / 2.0, 0.0, 3.0)
  s_6: Sensor Tier Encoding = [Rich=1.0, Partial=0.5, Manual=0.0]

Action Space A in {0, 1, 2}:
  0: Option A (Speed Override / Move Operator) - High throughput, high queue clearance, risk of scrap if defect risk high
  1: Option B (Buffer / Throttle Upstream)     - High defect suppression, throughput reduction, queue accumulation
  2: Option C (Workload Rebalance / Reroute)   - Balanced throughput & defect mitigation, fixed rerouting overhead

Reward Function R(s, a, operator_action, observed_telemetry):
  - Operator APPROVES (a = a_rec):
      R = +100.0 (Base Approval Reward)
        + 0.5 * Net_Financial_Impact ($)
        + 20.0 * Delta_Throughput (%)
        - 500.0 * Delta_Defect_Risk (%)
        + 30.0 * Queue_Reduction_Count
  - Operator REJECTS (a = a_rec rejected):
      R = -250.0 (Policy Penalty for rejected recommendation)
        - 0.5 * Unmitigated_Scrap_Loss ($)
        - 150.0 * (Defect_Risk_Severity)
"""

import os
import json
# pyrefly: ignore [missing-import]
import numpy as np
import pandas as pd


ACTIONS = ["Option A", "Option B", "Option C"]
ACTION_NAMES = {
    "Option A": "Speed Override / Move Operator",
    "Option B": "Buffer / Throttle Upstream",
    "Option C": "Workload Rebalance / Reroute"
}


class ContextualBanditRLPolicy:
    """
    Linear-UCB & Softmax Contextual Bandit Policy with Ridge Regression & Online RL Updates.
    Learns state-dependent Q-values Q(s, a) = w_a^T s + b_a for manufacturing interventions.
    """
    def __init__(self, state_dim=6, num_actions=3, alpha=1.0, l2_reg=1.0, model_path="rl_policy_weights.json"):
        self.state_dim = state_dim
        self.num_actions = num_actions
        self.alpha = alpha       # UCB exploration parameter
        self.l2_reg = l2_reg     # Ridge regularization parameter
        self.model_path = model_path

        # Sufficient statistics for Ridge Regression per action
        # A_a = X_a^T X_a + l2_reg * I (d x d)
        # b_a = X_a^T r_a (d x 1)
        self.A = [np.eye(self.state_dim) * self.l2_reg for _ in range(self.num_actions)]
        self.A_inv = [np.linalg.inv(self.A[a]) for a in range(self.num_actions)]
        self.b = [np.zeros(self.state_dim) for _ in range(self.num_actions)]
        self.bias = np.zeros(self.num_actions)
        self.action_counts = np.zeros(self.num_actions, dtype=int)
        self.total_rewards = np.zeros(self.num_actions, dtype=float)
        self.experience_replay = []

        if os.path.exists(self.model_path):
            self.load(self.model_path)

    @staticmethod
    def extract_state_vector(cycle_time, baseline_ct, queue, defect_prob, bottleneck_prob, vibration, tier="RICH"):
        """Extracts normalized 6-dimensional continuous state vector."""
        ct_drift = max(-0.5, min(1.5, (cycle_time - baseline_ct) / (baseline_ct if baseline_ct > 0 else 45.0)))
        q_norm = max(0.0, min(2.0, queue / 15.0))
        d_risk = max(0.0, min(1.0, defect_prob))
        bn_risk = max(0.0, min(1.0, bottleneck_prob))
        vib_norm = max(0.0, min(3.0, (vibration - 0.75) / 2.0))
        
        tier_str = str(tier).upper()
        if "MANUAL" in tier_str:
            tier_enc = 0.0
        elif "PARTIAL" in tier_str:
            tier_enc = 0.5
        else:
            tier_enc = 1.0
            
        return np.array([ct_drift, q_norm, d_risk, bn_risk, vib_norm, tier_enc], dtype=float)

    def get_action_weights(self):
        """Returns the learned weight vector for each action: theta_a = A_a^{-1} b_a."""
        weights = []
        for a in range(self.num_actions):
            w = self.A_inv[a].dot(self.b[a])
            weights.append(w)
        return weights

    def predict(self, state_vector, temperature=1.0):
        """
        Evaluates state vector and returns predicted Q-values, UCB scores,
        policy action distribution, recommended action, and confidence.
        """
        s = np.array(state_vector, dtype=float).flatten()
        weights = self.get_action_weights()
        
        q_values = np.zeros(self.num_actions)
        ucb_scores = np.zeros(self.num_actions)
        conf_intervals = np.zeros(self.num_actions)

        for a in range(self.num_actions):
            theta_a = weights[a]
            # Expected reward Q(s, a)
            q_val = float(np.dot(theta_a, s)) + self.bias[a]
            # UCB exploration uncertainty
            var = float(np.dot(s, np.dot(self.A_inv[a], s)).item())
            std = np.sqrt(max(0.0, var))
            ucb = q_val + self.alpha * std

            q_values[a] = q_val
            ucb_scores[a] = ucb
            conf_intervals[a] = std

        # Softmax action probabilities from Q-values
        scaled_q = (q_values - np.mean(q_values)) / (np.std(q_values) + 1e-4) / max(0.1, temperature)
        exp_q = np.exp(np.clip(scaled_q, -20.0, 20.0))
        policy_probs = exp_q / np.sum(exp_q)

        best_action_idx = int(np.argmax(q_values))
        recommended_action = ACTIONS[best_action_idx]
        confidence = float(policy_probs[best_action_idx]) * 100.0

        return {
            "recommended_action": recommended_action,
            "best_action_idx": best_action_idx,
            "q_values": {ACTIONS[i]: round(float(q_values[i]), 2) for i in range(self.num_actions)},
            "policy_distribution": {ACTIONS[i]: round(float(policy_probs[i]) * 100.0, 1) for i in range(self.num_actions)},
            "confidence_pct": round(confidence, 1),
            "state_vector": [round(float(x), 3) for x in s],
            "action_counts": [int(x) for x in self.action_counts]
        }

    def compute_reward(self, state_vector, action_name, operator_action="approve", observed_outcome=None, predicted_impact=None):
        """
        Computes formal reinforcement learning scalar reward R(s, a).
        """
        s = np.array(state_vector, dtype=float)
        d_risk = s[2]
        q_norm = s[1]
        
        is_approved = (operator_action.lower() == "approve")

        if not is_approved:
            # Rejection penalty
            base_penalty = -250.0
            unmitigated_scrap = d_risk * 600.0 * 15.0
            rejection_reward = base_penalty - unmitigated_scrap
            return round(float(rejection_reward), 2)

        # Approval reward
        base_reward = +150.0
        
        if predicted_impact:
            tput_pct = float(predicted_impact.get("tput_pct", 5.0))
            q_delta = float(predicted_impact.get("queue_change", -2.0))
            d_delta = float(predicted_impact.get("defect_risk_change", -10.0))
            fin_impact = float(predicted_impact.get("financial_impact", 1000.0))
        else:
            tput_pct = 7.5
            q_delta = -2.0
            d_delta = -15.0
            fin_impact = 1684.0

        r = (
            base_reward
            + 0.10 * fin_impact
            + 15.0 * tput_pct
            - 25.0 * q_delta                 # Negative queue change is desirable
            - 300.0 * (d_delta / 100.0)      # Negative defect delta is desirable
        )

        return round(float(r), 2)

    def update(self, state_vector, action_name, reward):
        """
        Performs exact online Sherman-Morrison rank-1 Ridge update for contextual bandit:
        A_a <- A_a + s s^T
        b_a <- b_a + r s
        A_inv_a <- A_inv_a - (A_inv_a s s^T A_inv_a) / (1 + s^T A_inv_a s)
        """
        a = ACTIONS.index(action_name) if isinstance(action_name, str) else int(action_name)
        s = np.array(state_vector, dtype=float).reshape(-1, 1) # (d, 1)
        r = float(reward)

        # Sherman-Morrison update of A_inv
        A_inv = self.A_inv[a]
        denom = 1.0 + float(s.T.dot(A_inv).dot(s).item())
        num = A_inv.dot(s).dot(s.T).dot(A_inv)
        self.A_inv[a] = A_inv - (num / denom)

        # Update matrix A and vector b
        self.A[a] += s.dot(s.T)
        self.b[a] += r * s.flatten()
        self.bias[a] += 0.05 * (r - self.bias[a]) # Running bias update

        self.action_counts[a] += 1
        self.total_rewards[a] += r

        # Store in experience replay buffer
        self.experience_replay.append({
            "state": [round(float(x), 4) for x in s.flatten()],
            "action": ACTIONS[a],
            "reward": round(r, 2)
        })

        if len(self.experience_replay) > 500:
            self.experience_replay = self.experience_replay[-500:]

        self.save(self.model_path)
        return {
            "action": ACTIONS[a],
            "reward": r,
            "action_total_count": int(self.action_counts[a]),
            "action_mean_reward": round(float(self.total_rewards[a] / max(1, self.action_counts[a])), 2)
        }

    def save(self, filepath=None):
        """Persists trained policy weights and statistics to JSON."""
        path = filepath or self.model_path
        data = {
            "state_dim": self.state_dim,
            "num_actions": self.num_actions,
            "alpha": self.alpha,
            "l2_reg": self.l2_reg,
            "b": [b.tolist() for b in self.b],
            "A_inv": [inv.tolist() for inv in self.A_inv],
            "bias": self.bias.tolist(),
            "action_counts": self.action_counts.tolist(),
            "total_rewards": self.total_rewards.tolist(),
            "learned_weights": [w.tolist() for w in self.get_action_weights()]
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def load(self, filepath=None):
        """Loads trained policy weights and statistics from JSON."""
        path = filepath or self.model_path
        if not os.path.exists(path):
            return False
        with open(path, "r") as f:
            data = json.load(f)
        self.state_dim = data.get("state_dim", self.state_dim)
        self.num_actions = data.get("num_actions", self.num_actions)
        self.alpha = data.get("alpha", self.alpha)
        self.l2_reg = data.get("l2_reg", self.l2_reg)
        self.b = [np.array(b, dtype=float) for b in data["b"]]
        self.A_inv = [np.array(inv, dtype=float) for inv in data["A_inv"]]
        self.bias = np.array(data.get("bias", [0.0]*self.num_actions), dtype=float)
        self.action_counts = np.array(data.get("action_counts", [0]*self.num_actions), dtype=int)
        self.total_rewards = np.array(data.get("total_rewards", [0.0]*self.num_actions), dtype=float)
        return True
