"""
TwinPilot: State-Dependent Counterfactual Evaluation on Unseen Test Shifts (RUN-021 to RUN-025)
"""

import pandas as pd
# pyrefly: ignore [missing-import]
import numpy as np
from counterfactual_engine import StateDependentCounterfactualEngine

def main():
    engine = StateDependentCounterfactualEngine()
    events_df = engine.events_df
    
    test_runs = [f"RUN-{str(i).zfill(3)}" for i in range(21, 26)]
    test_events = events_df[events_df["run_id"].isin(test_runs)].copy()

    rows = []
    for idx, ev in test_events.iterrows():
        evt_id = ev["event_id"]
        run_id = ev["run_id"]
        origin = ev["origin_station_id"]
        etype = ev["event_type"]
        detectable_m = ev["detectable_minute"]
        
        sim = engine.simulate_state_dependent_intervention(run_id, origin, detectable_m)
        if not sim:
            continue
            
        opts = sim["options"]
        rec = sim["recommended_option"]
        
        a_out = f"Tput {opts['Option A']['tput_pct']:+0.1f}%, Q {opts['Option A']['queue_change']:+0.1f}, Risk {opts['Option A']['defect_risk_change']:+0.1f}%"
        b_out = f"Tput {opts['Option B']['tput_pct']:+0.1f}%, Q {opts['Option B']['queue_change']:+0.1f}, Risk {opts['Option B']['defect_risk_change']:+0.1f}%"
        c_out = f"Tput {opts['Option C']['tput_pct']:+0.1f}%, Q {opts['Option C']['queue_change']:+0.1f}, Risk {opts['Option C']['defect_risk_change']:+0.1f}%"
        
        rows.append({
            "Event": evt_id,
            "Current state": f"{origin} ({etype}): {sim['state_desc']}",
            "Best option": rec,
            "A outcome": a_out,
            "B outcome": b_out,
            "C outcome": c_out
        })
        
    df = pd.DataFrame(rows)
    print("================================================================================")
    print("STATE-DEPENDENT COUNTERFACTUAL INTERVENTION TABLE (RUN-021 TO RUN-025):")
    print("================================================================================")
    print(df.to_markdown(index=False))

if __name__ == "__main__":
    main()
