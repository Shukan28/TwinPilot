import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, roc_auc_score, precision_score, recall_score, confusion_matrix
# pyrefly: ignore [missing-import]
import numpy as np

print("=" * 60)
print("TWINPILOT DEFECT PREDICTION MODEL v1")
print("=" * 60)

# ------------------------------------------------
# 1. LOAD DATA
# ------------------------------------------------
print("\n[1] Loading data...")
dataset_dir = r"twinpilot_dataset_extracted\twinpilot_dataset"
sensor_df = pd.read_csv(f"{dataset_dir}\\sensor_timeseries.csv")
events_df = pd.read_csv(f"{dataset_dir}\\events_ground_truth.csv")
stations_df = pd.read_csv(f"{dataset_dir}\\stations_master.csv")

print(f"    Sensor rows: {len(sensor_df):,}")
print(f"    Total events: {len(events_df)}")

# Identify defect events
defects = events_df[events_df['event_type'] == 'defect_propagation']
print(f"    Defect propagation events: {len(defects)}")
print(f"    Defect runs: {defects['run_id'].tolist()}")

# ------------------------------------------------
# 2. CREATE THE DEFECT TARGET
# No cheating: the model will NOT see event_type, active_event_ids or status_flag.
# We label a row as 1 only if:
#   - it is the origin station of the defect
#   - the defect peak is within the next 15 minutes
# This is the same approach we used for bottleneck prediction.
# ------------------------------------------------
print("\n[2] Creating target: defect_15min_ahead...")
# We label a row as 1 if:
#   - The station is ON the propagation path of a defect event
#   - The defect peak is within the next 15 minutes from this row's timestamp
# This is correct and not leakage: a defect at S23 genuinely affects S24-S26.
# We are labeling the DANGER ZONE, not telling the model the event name.
rows = []
for _, event in defects.iterrows():
    path_stations = [s.strip() for s in event['propagation_path'].split(',')]
    for station in path_stations:
        rows.append({
            'run_id': event['run_id'],
            'station_id': station,
            'peak_minute': event['peak_minute']
        })
defect_labels = pd.DataFrame(rows)

merged = pd.merge(sensor_df, defect_labels,
                  on=['run_id', 'station_id'],
                  how='left')
time_to_peak = merged['peak_minute'] - merged['minute_index']
sensor_df['defect_15min_ahead'] = ((time_to_peak > 0) & (time_to_peak <= 15)).astype(int)
print(f"    Target distribution:\n{sensor_df['defect_15min_ahead'].value_counts().to_string()}")

# ------------------------------------------------
# 3. ADD STATION STRUCTURAL INFORMATION
# "Known operational context" (not ground truth leakage)
# Station position (numeric) and whether it has a sensor are
# structural properties of the factory the twin is allowed to know.
# ------------------------------------------------
print("\n[3] Adding station metadata (structural context)...")
# Extract station sequence number (e.g. S23 → 23). Non-S rows (like ENG01) are dropped.
stations_df['station_num'] = pd.to_numeric(
    stations_df['station_id'].str.replace('S', '', regex=False), errors='coerce'
)
stations_df = stations_df.dropna(subset=['station_num'])
stations_df['station_num'] = stations_df['station_num'].astype(int)

# Check what columns are available
sensor_df = pd.merge(sensor_df, stations_df[['station_id', 'station_num']],
                     on='station_id', how='left')

# ------------------------------------------------
# 4. HANDLE MISSING SENSORS (same fix as bottleneck model)
# Stations without sensors get -1 (structural fact, not leakage)
# ------------------------------------------------
print("\n[4] Handling missing sensors (fill with -1)...")
base_features = ['cycle_time_sec', 'queue_length', 'vibration_mm_s', 'torque_nm', 'temperature_c']
sensor_df[base_features] = sensor_df[base_features].fillna(-1)

# ------------------------------------------------
# 5. FEATURE ENGINEERING: RECENT HISTORY
# Same temporal approach that made the bottleneck model succeed.
# ------------------------------------------------
print("\n[5] Engineering temporal features (recent history)...")
sensor_df = sensor_df.sort_values(by=['run_id', 'station_id', 'minute_index'])
grouped = sensor_df.groupby(['run_id', 'station_id'])

# Rolling averages
sensor_df['avg_cycle_time_5m']  = grouped['cycle_time_sec'].rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
sensor_df['avg_cycle_time_10m'] = grouped['cycle_time_sec'].rolling(10, min_periods=1).mean().reset_index(level=[0,1], drop=True)
sensor_df['avg_queue_5m']       = grouped['queue_length'].rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
sensor_df['avg_queue_10m']      = grouped['queue_length'].rolling(10, min_periods=1).mean().reset_index(level=[0,1], drop=True)
sensor_df['avg_torque_5m']      = grouped['torque_nm'].rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
sensor_df['avg_vibration_5m']   = grouped['vibration_mm_s'].rolling(5, min_periods=1).mean().reset_index(level=[0,1], drop=True)

# Rate of change (current vs N minutes ago)
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

# ------------------------------------------------
# 6. FIXED TRAIN / VALIDATION / TEST SPLIT BY RUN
# ------------------------------------------------
print("\n[6] Splitting by production run...")
train_runs = [f'RUN-{str(i).zfill(3)}' for i in range(1, 16)]
val_runs   = [f'RUN-{str(i).zfill(3)}' for i in range(16, 21)]
test_runs  = [f'RUN-{str(i).zfill(3)}' for i in range(21, 26)]

X_train = sensor_df[sensor_df['run_id'].isin(train_runs)][features]
y_train = sensor_df[sensor_df['run_id'].isin(train_runs)]['defect_15min_ahead']

X_val   = sensor_df[sensor_df['run_id'].isin(val_runs)][features]
y_val   = sensor_df[sensor_df['run_id'].isin(val_runs)]['defect_15min_ahead']

X_test  = sensor_df[sensor_df['run_id'].isin(test_runs)][features]
y_test  = sensor_df[sensor_df['run_id'].isin(test_runs)]['defect_15min_ahead']

print(f"    Train: {len(X_train):,} rows | Positives: {y_train.sum()}")
print(f"    Val:   {len(X_val):,} rows | Positives: {y_val.sum()}")
print(f"    Test:  {len(X_test):,} rows | Positives: {y_test.sum()}")

# ------------------------------------------------
# 7. TRAIN THE DEFECT MODEL
# ------------------------------------------------
print("\n[7] Training Defect Prediction Model v1...")
model = RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=-1, class_weight='balanced')
model.fit(X_train, y_train)
print("    Training complete.")

# ------------------------------------------------
# 8. EVALUATE ON VALIDATION SET (threshold search)
# ------------------------------------------------
print("\n[8] Evaluating on Validation Set (Threshold Analysis)...")
y_val_proba = model.predict_proba(X_val)[:, 1]
print(f"    Total defect positives in Val: {y_val.sum()}")
print(f"\n    {'Threshold':<10} | {'Precision':<10} | {'Recall':<10} | {'False Alarms (FP)':<20} | {'Caught (TP)':<12}")
thresholds = [0.05, 0.10, 0.20, 0.30, 0.50]
for t in thresholds:
    preds = (y_val_proba >= t).astype(int)
    precision = precision_score(y_val, preds, zero_division=0)
    recall = recall_score(y_val, preds, zero_division=0)
    if len(np.unique(preds)) == 1 and preds[0] == 0:
        fp, tp = 0, 0
    else:
        tn, fp, fn, tp = confusion_matrix(y_val, preds).ravel()
    print(f"    {t:<10.2f} | {precision:<10.2f} | {recall:<10.2f} | {fp:<20} | {tp:<12}")

# ------------------------------------------------
# 9. EVALUATE ON COMPLETELY UNSEEN TEST SET
# ------------------------------------------------
print("\n[9] Final Evaluation on Unseen Test Runs (RUN-021 to RUN-025)...")
y_test_proba = model.predict_proba(X_test)[:, 1]
y_test_pred = (y_test_proba >= 0.10).astype(int)

if y_test.nunique() > 1:
    auc = roc_auc_score(y_test, y_test_proba)
else:
    auc = float('nan')

print(f"\n    {'='*52}")
print(f"    DEFECT MODEL v2 — TEST SET RESULTS (threshold=0.10)")
print(f"    {'='*52}")
print(classification_report(y_test, y_test_pred, zero_division=0))
print(f"    ROC AUC Score: {auc:.4f}")
print(f"\n    Confusion Matrix (rows=actual, cols=predicted):")
cm = confusion_matrix(y_test, y_test_pred)
print(f"                  Pred 0    Pred 1")
print(f"    Actual 0  {cm[0][0]:>8}  {cm[0][1]:>8}")
print(f"    Actual 1  {cm[1][0]:>8}  {cm[1][1]:>8}")
print(f"    (TN={cm[0][0]}, FP={cm[0][1]}, FN={cm[1][0]}, TP={cm[1][1]})")

# ------------------------------------------------
# 10. LEAD TIME ANALYSIS ON TEST SET
# ------------------------------------------------
print("\n[10] Lead Time Analysis on Test Set...")
chosen_threshold = 0.10
test_defects = events_df[(events_df['event_type'] == 'defect_propagation') & 
                          (events_df['run_id'].isin(test_runs))]

test_eval = sensor_df[sensor_df['run_id'].isin(test_runs)].copy()
test_eval['probability'] = y_test_proba

print(f"\n    {'Defect Event':<20} | {'Origin':<8} | {'Peak':<8} | {'1st Warning':<14} | {'Lead Time'}")
print(f"    {'-'*65}")
for _, event in test_defects.iterrows():
    run_id = event['run_id']
    origin = event['origin_station_id']
    peak   = event['peak_minute']
    eid    = event['event_id']
    
    event_rows = test_eval[(test_eval['run_id'] == run_id) &
                            (test_eval['station_id'] == origin)]
    warnings = event_rows[(event_rows['probability'] >= chosen_threshold) &
                           (event_rows['minute_index'] <= peak)]
    
    if len(warnings) > 0:
        first = warnings['minute_index'].min()
        lead  = peak - first
        print(f"    {eid:<20} | {origin:<8} | {peak:<8} | {first:<14} | {lead} min")
    else:
        print(f"    {eid:<20} | {origin:<8} | {peak:<8} | {'Missed':<14} | N/A")

# ------------------------------------------------
# 11. FEATURE IMPORTANCES
# ------------------------------------------------
print("\n[11] What the model thinks matters (Feature Importances):")
fi = pd.DataFrame({'Feature': features, 'Importance': model.feature_importances_})
fi = fi.sort_values(by='Importance', ascending=False)
print(fi.head(10).to_string(index=False))
