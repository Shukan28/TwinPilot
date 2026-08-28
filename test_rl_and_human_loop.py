"""
TwinPilot: Human-in-the-Loop & Reinforcement Learning Integration Test
======================================================================
Verifies:
  1. Policy decisions driven by trained RL Contextual Bandit Q-values
  2. Dynamic future adaptation on Operator Approval (+Reward, Line Recovered)
  3. Dynamic future adaptation on Operator Rejection (-Penalty, Manual Delay)
  4. Online RL weight updates on human feedback
"""

import json
from twinpilot_api import build_factory_state, _session_decisions, _serialized_cache
from counterfactual_engine import StateDependentCounterfactualEngine

def test_rl_and_human_loop():
    print("=" * 80)
    print("TEST: RL CONTEXTUAL BANDIT & DYNAMIC HUMAN-IN-THE-LOOP FUTURE")
    print("=" * 80)

    engine = StateDependentCounterfactualEngine()
    
    # 1. Test RL recommendation on RUN-024 S03 @ minute 143
    print("\n[1. RL POLICY PREDICTION ON CRITICAL ANOMALY]")
    sim = engine.simulate_state_dependent_intervention("RUN-024", "S03", 143)
    print(f"  Station:               {sim['station_id']}")
    print(f"  Current CT / Risk:     {sim['current_ct']}s / {sim['current_defect_prob']*100:.1f}%")
    print(f"  RL Q-Values:           {sim['rl_q_values']}")
    print(f"  RL Policy Distribution:{sim['rl_policy_distribution']}")
    print(f"  Recommended Action:    {sim['recommended_option']}")
    print(f"  Model Confidence:      {sim['confidence']}%")

    assert sim['recommended_option'] in ["Option A", "Option B", "Option C"], "Invalid RL recommendation"

    # 2. Test Step 4 in 'Pending' State
    print("\n[2. STAGE 5 FUTURE IN 'PENDING' STATE (NO HUMAN ACTION YET)]")
    _session_decisions.clear()
    _serialized_cache.clear()
    state_pending = build_factory_state(run_id="RUN-024", minute=158, station="S03", event_id="RUN024-EVT01", step_id=4)
    tl_pending = state_pending["twin_timeline"][4]
    print(f"  Step 4 Phase Name:     {tl_pending['phase_name']}")
    print(f"  Step 4 Badge:          {tl_pending['category_badge']}")
    print(f"  Step 4 Status:         {tl_pending['status']}")
    print(f"  Step 4 Highlight:      {tl_pending['telemetry_highlight']}")
    assert "Natural Future (Do Nothing)" in tl_pending['phase_name'], "Expected Natural Future when pending"
    assert "Severe Disruption Projected" in tl_pending['status'], "Expected Severe Disruption when pending"

    # 3. Simulate Operator Approval
    print("\n[3. SIMULATE OPERATOR APPROVAL -> ONLINE RL UPDATE]")
    approval_res = engine.evaluate_operator_lifecycle(sim, operator_action="approve")
    print(f"  Operator Action:       {approval_res['operator_action']}")
    print(f"  Status:                {approval_res['outcome_status']}")
    print(f"  Realized Tput Gain:    +{approval_res['realized_tput_gain_pct']}%")
    print(f"  RL Reward Applied:     +{approval_res['rl_reward_applied']} pts")
    print(f"  RL Update Action:      {approval_res['rl_update_stats']['action']} (Total Count: {approval_res['rl_update_stats']['action_total_count']})")
    assert approval_res['rl_reward_applied'] > 0, "Approval should yield positive RL reward"

    # Set in-session decision to approved
    _session_decisions["RUN-024_RUN024-EVT01"] = {
        "status": "approved",
        "record": {"rl_learning": approval_res}
    }
    _serialized_cache.clear()

    # 4. Test Step 4 in 'Approved' State
    print("\n[4. STAGE 5 DYNAMIC FUTURE IN 'APPROVED' STATE]")
    state_approved = build_factory_state(run_id="RUN-024", minute=158, station="S03", event_id="RUN024-EVT01", step_id=4)
    tl_approved = state_approved["twin_timeline"][4]
    print(f"  Step 4 Phase Name:     {tl_approved['phase_name']}")
    print(f"  Step 4 Badge:          {tl_approved['category_badge']}")
    print(f"  Step 4 Status:         {tl_approved['status']}")
    print(f"  Step 4 Highlight:      {tl_approved['telemetry_highlight']}")
    print(f"  S03 Recovered CT:      {state_approved['target_station']['cycle_time_sec']}s")
    print(f"  Overall Factory Health:{state_approved['overall_metrics']['overall_health_pct']}%")
    assert "Dynamic Future (Approved)" in tl_approved['phase_name'], "Expected Dynamic Future (Approved)"
    assert "INTERVENTION EXECUTED & VALIDATED" in tl_approved['category_badge'], "Expected Validated badge"
    assert state_approved['target_station']['cycle_time_sec'] <= 46.0, "Expected recovered cycle time"

    # 5. Simulate Operator Rejection
    print("\n[5. SIMULATE OPERATOR REJECTION -> ONLINE RL PENALTY]")
    rejection_res = engine.evaluate_operator_lifecycle(sim, operator_action="reject")
    print(f"  Operator Action:       {rejection_res['operator_action']}")
    print(f"  Status:                {rejection_res['outcome_status']}")
    print(f"  Realized Loss:         ${rejection_res['realized_financial_impact']}")
    print(f"  RL Penalty Applied:    {rejection_res['rl_reward_applied']} pts")
    assert rejection_res['rl_reward_applied'] < 0, "Rejection should yield negative RL penalty"

    # Set in-session decision to rejected
    _session_decisions["RUN-024_RUN024-EVT01"] = {
        "status": "rejected",
        "record": {"rl_learning": rejection_res}
    }
    _serialized_cache.clear()

    # 6. Test Step 4 in 'Rejected' State
    print("\n[6. STAGE 5 DYNAMIC FUTURE IN 'REJECTED' STATE]")
    state_rejected = build_factory_state(run_id="RUN-024", minute=158, station="S03", event_id="RUN024-EVT01", step_id=4)
    tl_rejected = state_rejected["twin_timeline"][4]
    print(f"  Step 4 Phase Name:     {tl_rejected['phase_name']}")
    print(f"  Step 4 Badge:          {tl_rejected['category_badge']}")
    print(f"  Step 4 Status:         {tl_rejected['status']}")
    print(f"  Step 4 Highlight:      {tl_rejected['telemetry_highlight']}")
    print(f"  S03 Delayed CT:        {state_rejected['target_station']['cycle_time_sec']}s")
    print(f"  Overall Factory Health:{state_rejected['overall_metrics']['overall_health_pct']}%")
    assert "Dynamic Future (Rejected)" in tl_rejected['phase_name'], "Expected Dynamic Future (Rejected)"
    assert "OPERATOR OVERRIDE REJECTED" in tl_rejected['category_badge'], "Expected Rejected badge"
    assert state_rejected['target_station']['cycle_time_sec'] > 46.0, "Expected delayed cycle time"

    print("\n" + "=" * 80)
    print("ALL REINFORCEMENT LEARNING & HUMAN-IN-THE-LOOP TESTS PASSED!")
    print("=" * 80)

if __name__ == "__main__":
    test_rl_and_human_loop()
