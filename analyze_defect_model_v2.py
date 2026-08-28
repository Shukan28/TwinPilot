import pandas as pd
# pyrefly: ignore [missing-import]
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import precision_score, recall_score, confusion_matrix

print("==============================================================")
print("ANALYZING DEFECT MODEL v2 — THRESHOLDS, LEAD TIME & FALSE ALARMS")
print("==============================================================")

# 1. Load data
dataset_dir = r"twinpilot_dataset_extracted\twinpilot_dataset"
sensor_df = pd.read_csv(f"{dataset_dir}\\sensor_timeseries.csv")
events_df = pd.read_csv(f"{dataset_dir}\\events_ground_truth.csv")
stations_df = pd.read_csv(f"{dataset_dir}\\stations_master.csv")
maint_df = pd.read_csv(f"{dataset_dir}\\maintenance_windows.csv")

# 2. Defect targets
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

merged = pd.merge(sensor_df, defect_labels[['run_id', 'station_id', 'peak_minute']],
                  on=['run_id', 'station_id'],
                  how='left')
time_to_peak = merged['peak_minute'] - merged['minute_index']
sensor_df['defect_15min_ahead'] = ((time_to_peak > 0) & (time_to_peak <= 15)).astype(int)

# Structural features
stations_df['station_num'] = pd.to_numeric(
    stations_df['station_id'].str.replace('S', '', regex=False), errors='coerce'
)
stations_df = stations_df.dropna(subset=['station_num'])
stations_df['station_num'] = stations_df['station_num'].astype(int)
sensor_df = pd.merge(sensor_df, stations_df[['station_id', 'station_num']], on='station_id', how='left')

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

features = base_features + [
    'station_num',
    'avg_cycle_time_5m', 'avg_cycle_time_10m',
    'change_cycle_time_5m', 'change_cycle_time_10m',
    'avg_queue_5m', 'avg_queue_10m',
    'queue_growth_5m', 'queue_growth_10m',
    'avg_torque_5m', 'change_torque_5m', 'change_torque_10m',
    'avg_vibration_5m', 'change_vibration_5m', 'change_vibration_10m',
]

train_runs = [f'RUN-{str(i).zfill(3)}' for i in range(1, 16)]
val_runs   = [f'RUN-{str(i).zfill(3)}' for i in range(16, 21)]
test_runs  = [f'RUN-{str(i).zfill(3)}' for i in range(21, 26)]

X_train = sensor_df[sensor_df['run_id'].isin(train_runs)][features]
y_train = sensor_df[sensor_df['run_id'].isin(train_runs)]['defect_15min_ahead']

X_val   = sensor_df[sensor_df['run_id'].isin(val_runs)][features]
y_val   = sensor_df[sensor_df['run_id'].isin(val_runs)]['defect_15min_ahead']

X_test  = sensor_df[sensor_df['run_id'].isin(test_runs)][features]
y_test  = sensor_df[sensor_df['run_id'].isin(test_runs)]['defect_15min_ahead']

# Train Model v2 exactly as before
model = RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=-1, class_weight='balanced')
model.fit(X_train, y_train)

# ==============================================================
# TASK 2: VALIDATION THRESHOLD SEARCH (RUN-016 to RUN-020)
# ==============================================================
print("\n--- TASK 2: VALIDATION SET THRESHOLD SEARCH (RUN-016 to RUN-020) ---")
y_val_proba = model.predict_proba(X_val)[:, 1]
val_thresholds = [0.01, 0.02, 0.03, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50]

print(f"{'Threshold':<10} | {'Precision':<10} | {'Recall':<10} | {'False Pos (FP)':<16} | {'True Pos (TP)':<14}")
print("-" * 72)
val_results = []
for t in val_thresholds:
    preds = (y_val_proba >= t).astype(int)
    p = precision_score(y_val, preds, zero_division=0)
    r = recall_score(y_val, preds, zero_division=0)
    tn, fp, fn, tp = confusion_matrix(y_val, preds).ravel()
    val_results.append({'threshold': t, 'precision': p, 'recall': r, 'fp': fp, 'tp': tp})
    print(f"{t:<10.2f} | {p:<10.4f} | {r:<10.4f} | {fp:<16} | {tp:<14}")

# Based on validation: choose threshold balancing recall and reasonable FP.
# We will inspect and select the optimal threshold.
chosen_t = 0.10  # baseline chosen, let's verify if 0.10 or another is optimal

# ==============================================================
# TASK 3: UNTOUCHED TEST SET EVENT-LEVEL RESULTS (RUN-021 to RUN-025)
# ==============================================================
print(f"\n--- TASK 3: UNTOUCHED TEST SET EVENT-LEVEL RESULTS (Threshold = {chosen_t}) ---")
y_test_proba = model.predict_proba(X_test)[:, 1]
test_df = sensor_df[sensor_df['run_id'].isin(test_runs)].copy()
test_df['proba'] = y_test_proba
test_df['pred'] = (y_test_proba >= chosen_t).astype(int)

test_defects = events_df[(events_df['event_type'] == 'defect_propagation') & (events_df['run_id'].isin(test_runs))]

print(f"{'Event':<15} | {'Origin':<8} | {'Peak':<8} | {'First Alert':<12} | {'Lead Time':<10} | {'Caught?'}")
print("-" * 70)
for _, ev in test_defects.iterrows():
    r_id = ev['run_id']
    origin = ev['origin_station_id']
    peak = ev['peak_minute']
    eid = ev['event_id']
    
    # Check origin station alerts prior to or at peak
    origin_rows = test_df[(test_df['run_id'] == r_id) & (test_df['station_id'] == origin)]
    alerts = origin_rows[(origin_rows['pred'] == 1) & (origin_rows['minute_index'] <= peak)]
    
    if len(alerts) > 0:
        first_alert = alerts['minute_index'].min()
        lead_time = peak - first_alert
        caught = "Yes"
    else:
        # Check along entire propagation path
        path_stations = [s.strip() for s in ev['propagation_path'].split(',')]
        path_rows = test_df[(test_df['run_id'] == r_id) & (test_df['station_id'].isin(path_stations))]
        path_alerts = path_rows[(path_rows['pred'] == 1) & (path_rows['minute_index'] <= peak)]
        if len(path_alerts) > 0:
            first_alert = path_alerts['minute_index'].min()
            lead_time = peak - first_alert
            caught = f"Yes (at {path_alerts.loc[path_alerts['minute_index'] == first_alert, 'station_id'].iloc[0]})"
        else:
            first_alert = "N/A"
            lead_time = "N/A"
            caught = "No"
            
    print(f"{eid:<15} | {origin:<8} | {peak:<8} | {str(first_alert):<12} | {str(lead_time):<10} | {caught}")

# ==============================================================
# TASK 4: FALSE ALARM BREAKDOWN (TEST SET)
# ==============================================================
print(f"\n--- TASK 4: FALSE ALARM BREAKDOWN (TEST SET AT THRESHOLD {chosen_t}) ---")
# False positive rows: y_true == 0, y_pred == 1
fp_rows = test_df[(test_df['defect_15min_ahead'] == 0) & (test_df['pred'] == 1)].copy()
total_fp = len(fp_rows)
print(f"Total False Positive Rows in Test Set: {total_fp}")

# Categorization rules:
# 1. Maintenance: during scheduled maintenance window or status_flag == 'maintenance'
# 2. During another real non-defect event: active_event_ids has bottleneck, machine_failure, sensorless_drift
# 3. Near a defect event:
#    - Station is on propagation path of a defect event in that run, but minute is outside the strict 15-min target
#    - Or within ±30 mins of a defect event window (start_minute - 30 to resolved_minute + 30)
# 4. Completely normal operation: none of the above

categories = {
    'During Maintenance': 0,
    'During Other Real Event (Bottleneck/Failure/Drift)': 0,
    'Near Defect Event (Outside 15m target or on downstream path)': 0,
    'Completely Normal Operation': 0
}

# Get all test events
test_all_events = events_df[events_df['run_id'].isin(test_runs)]

for _, row in fp_rows.iterrows():
    run_id = row['run_id']
    sid = row['station_id']
    minute = row['minute_index']
    active_ids = str(row['active_event_ids']) if pd.notna(row['active_event_ids']) else ""
    status = row['status_flag']
    
    # 1. Check Maintenance
    is_maint = (status == 'maintenance')
    if not is_maint:
        maint_match = maint_df[(maint_df['run_id'] == run_id) & (maint_df['station_id'] == sid) & 
                               (maint_df['window_start_minute'] <= minute) & (minute <= maint_df['window_end_minute'])]
        is_maint = len(maint_match) > 0
        
    if is_maint:
        categories['During Maintenance'] += 1
        continue
        
    # 2. Check Other Real Events (non-defect)
    # Check if active_event_ids contains bottleneck, machine_failure, or sensorless_drift
    other_ev_active = False
    if active_ids:
        for eid in active_ids.split(';'):
            ev_match = test_all_events[test_all_events['event_id'] == eid]
            if len(ev_match) > 0 and ev_match['event_type'].iloc[0] != 'defect_propagation':
                other_ev_active = True
                break
    if not other_ev_active:
        # Also check ground truth event windows for this run/station
        other_events = test_all_events[(test_all_events['run_id'] == run_id) & (test_all_events['event_type'] != 'defect_propagation')]
        for _, oev in other_events.iterrows():
            path_stns = [s.strip() for s in oev['propagation_path'].split(',')]
            if sid in path_stns and (oev['start_minute'] <= minute <= oev['resolved_minute']):
                other_ev_active = True
                break
                
    if other_ev_active:
        categories['During Other Real Event (Bottleneck/Failure/Drift)'] += 1
        continue
        
    # 3. Check Near Defect Event
    near_defect = False
    defect_events = test_all_events[(test_all_events['run_id'] == run_id) & (test_all_events['event_type'] == 'defect_propagation')]
    for _, dev in defect_events.iterrows():
        path_stns = [s.strip() for s in dev['propagation_path'].split(',')]
        if sid in path_stns:
            # Extended window: 30 mins before start up to resolved minute
            if (dev['start_minute'] - 30 <= minute <= dev['resolved_minute'] + 10):
                near_defect = True
                break
        else:
            # Nearby station during active defect window
            if (dev['start_minute'] <= minute <= dev['resolved_minute']):
                near_defect = True
                break
                
    if near_defect:
        categories['Near Defect Event (Outside 15m target or on downstream path)'] += 1
        continue
        
    # 4. Completely Normal Operation
    categories['Completely Normal Operation'] += 1

print(f"{'Category':<60} | {'Count':<8} | {'Percentage'}")
print("-" * 80)
for cat, count in categories.items():
    pct = (count / total_fp) * 100
    print(f"{cat:<60} | {count:<8} | {pct:<6.2f}%")
