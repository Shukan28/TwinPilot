"""
Test Unified Factory State API Responses for Scenario 1 vs Scenario 2
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import urllib.request
import json
import pandas as pd

def test_api():
    print("=" * 80)
    print("AUDITING UNIFIED FACTORY STATE BACKEND PAYLOAD")
    print("=" * 80)

    # 1. SCENARIO 1: RUN-024 (Minute 143)
    u1 = "http://localhost:5000/api/scenario?run_id=RUN-024&minute=143&station=S03&event_id=RUN024-EVT01"
    s1 = json.loads(urllib.request.urlopen(u1).read())
    
    print("\n--- SCENARIO 1: RUN024-EVT01 (S03 Defect Propagation) ---")
    print(f"Shift Time:           {s1['sim_clock']} | Health: {s1['overall_metrics']['overall_health_pct']}% | Tput: {s1['overall_metrics']['line_throughput_uph']} u/h")
    print(f"31 Stations Count:    {len(s1['stations'])} stations returned")
    print(f"Target Anomaly:       Station {s1['target_station']['station_id']} ({s1['target_station']['station_name']}) — CT: {s1['target_station']['cycle_time_sec']}s (Base: {s1['target_station']['baseline_cycle_time_sec']}s), Defect: {s1['target_station']['defect_prob_pct']}%, Queue: {s1['target_station']['queue_length']}")
    print(f"Alert Title:          {s1['anomaly_prediction']['alert_title']}")
    print(f"Prediction Factors:   {[(f['name'], f['delta_str']) for f in s1['anomaly_prediction']['prediction_factors']]}")
    print(f"Dark Zones (Manual):  {[(d['station_id'], d['status'], str(d['degradation_prob_pct']) + '%') for d in s1['dark_zones']]}")
    print(f"Root Cause:           {s1['root_cause']['station_id']} ({s1['root_cause']['station_name']})")
    print(f"Propagation Chain:    {' -> '.join(s1['propagation']['path'])}")
    print(f"Quarantined VINs:     {s1['at_risk_vehicles']['total_count']} VINs (Sample: {', '.join(s1['at_risk_vehicles']['sample_vins'][:3])}...)")
    print(f"AI Recommendation:    {s1['recommendation']['option_key']} ({s1['recommendation']['option_name']}) @ {s1['recommendation']['confidence_pct']}% confidence")
    for k, v in s1['interventions'].items():
        print(f"   * {k}: Tput {v['tput_pct']:+.1f}% | Queue {v['queue_change']:+.1f} | Defect {v['defect_risk_change']:+.1f}% | Net ${v['financial_impact']:+.0f} | Rec: {v['is_recommended']}")

    # 2. SCENARIO 2: RUN-025 (Minute 93)
    u2 = "http://localhost:5000/api/scenario?run_id=RUN-025&minute=93&station=S16&event_id=RUN025-EVT02"
    s2 = json.loads(urllib.request.urlopen(u2).read())
    
    print("\n" + "=" * 80)
    print("--- SCENARIO 2: RUN025-EVT02 (S16 Machine Failure / Backlog) ---")
    print(f"Shift Time:           {s2['sim_clock']} | Health: {s2['overall_metrics']['overall_health_pct']}% | Tput: {s2['overall_metrics']['line_throughput_uph']} u/h")
    print(f"31 Stations Count:    {len(s2['stations'])} stations returned")
    print(f"Target Anomaly:       Station {s2['target_station']['station_id']} ({s2['target_station']['station_name']}) — CT: {s2['target_station']['cycle_time_sec']}s (Base: {s2['target_station']['baseline_cycle_time_sec']}s), Defect: {s2['target_station']['defect_prob_pct']}%, Queue: {s2['target_station']['queue_length']}")
    print(f"Alert Title:          {s2['anomaly_prediction']['alert_title']}")
    print(f"Prediction Factors:   {[(f['name'], f['delta_str']) for f in s2['anomaly_prediction']['prediction_factors']]}")
    print(f"Dark Zones (Manual):  {[(d['station_id'], d['status'], str(d['degradation_prob_pct']) + '%') for d in s2['dark_zones']]}")
    print(f"Root Cause:           {s2['root_cause']['station_id']} ({s2['root_cause']['station_name']})")
    print(f"Propagation Chain:    {' -> '.join(s2['propagation']['path'])}")
    print(f"Quarantined VINs:     {s2['at_risk_vehicles']['total_count']} VINs (Sample: {', '.join(s2['at_risk_vehicles']['sample_vins'][:3])}...)")
    print(f"AI Recommendation:    {s2['recommendation']['option_key']} ({s2['recommendation']['option_name']}) @ {s2['recommendation']['confidence_pct']}% confidence")
    for k, v in s2['interventions'].items():
        print(f"   * {k}: Tput {v['tput_pct']:+.1f}% | Queue {v['queue_change']:+.1f} | Defect {v['defect_risk_change']:+.1f}% | Net ${v['financial_impact']:+.0f} | Rec: {v['is_recommended']}")

if __name__ == "__main__":
    test_api()
