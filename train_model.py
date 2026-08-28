import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, roc_auc_score

print("1. Load the data")
dataset_dir = r"twinpilot_dataset_extracted\twinpilot_dataset"
sensor_df = pd.read_csv(f"{dataset_dir}\\sensor_timeseries.csv")
events_df = pd.read_csv(f"{dataset_dir}\\events_ground_truth.csv")

print("2. Create the target: bottleneck_15min_ahead")
bottlenecks = events_df[events_df['event_type'] == 'bottleneck']

# Merge to find when a bottleneck peaks at a specific station for a specific run
merged = pd.merge(sensor_df, bottlenecks[['run_id', 'origin_station_id', 'peak_minute']],
                  left_on=['run_id', 'station_id'],
                  right_on=['run_id', 'origin_station_id'],
                  how='left')

# Calculate time to peak
time_to_peak = merged['peak_minute'] - merged['minute_index']
sensor_df['bottleneck_15min_ahead'] = ((time_to_peak > 0) & (time_to_peak <= 15)).astype(int)

print("3. Handling missing sensors")
base_features = ['cycle_time_sec', 'queue_length', 'vibration_mm_s', 'torque_nm', 'temperature_c']
sensor_df[base_features] = sensor_df[base_features].fillna(-1)

print("4. Feature Engineering: Creating 'Recent History' columns")
# Sort by run, station, and time to correctly calculate rolling history
sensor_df = sensor_df.sort_values(by=['run_id', 'station_id', 'minute_index'])
grouped = sensor_df.groupby(['run_id', 'station_id'])

# Averages over last 5 and 10 minutes
sensor_df['avg_cycle_time_5m'] = grouped['cycle_time_sec'].rolling(window=5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
sensor_df['avg_cycle_time_10m'] = grouped['cycle_time_sec'].rolling(window=10, min_periods=1).mean().reset_index(level=[0,1], drop=True)
sensor_df['avg_queue_5m'] = grouped['queue_length'].rolling(window=5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
sensor_df['avg_queue_10m'] = grouped['queue_length'].rolling(window=10, min_periods=1).mean().reset_index(level=[0,1], drop=True)

# Changes / Growth over last 5 and 10 minutes (Current minus Past)
sensor_df['change_cycle_time_5m'] = sensor_df['cycle_time_sec'] - grouped['cycle_time_sec'].shift(5).fillna(sensor_df['cycle_time_sec'])
sensor_df['change_cycle_time_10m'] = sensor_df['cycle_time_sec'] - grouped['cycle_time_sec'].shift(10).fillna(sensor_df['cycle_time_sec'])
sensor_df['queue_growth_5m'] = sensor_df['queue_length'] - grouped['queue_length'].shift(5).fillna(sensor_df['queue_length'])
sensor_df['queue_growth_10m'] = sensor_df['queue_length'] - grouped['queue_length'].shift(10).fillna(sensor_df['queue_length'])
sensor_df['change_vibration_5m'] = sensor_df['vibration_mm_s'] - grouped['vibration_mm_s'].shift(5).fillna(sensor_df['vibration_mm_s'])
sensor_df['change_torque_5m'] = sensor_df['torque_nm'] - grouped['torque_nm'].shift(5).fillna(sensor_df['torque_nm'])

features = base_features + [
    'avg_cycle_time_5m', 'avg_cycle_time_10m', 'change_cycle_time_5m', 'change_cycle_time_10m',
    'avg_queue_5m', 'avg_queue_10m', 'queue_growth_5m', 'queue_growth_10m',
    'change_vibration_5m', 'change_torque_5m'
]

print("5. Fixed Train / Validation / Test Split")
# We explicitly divide the production runs without peaking at their labels
train_runs = [f'RUN-{str(i).zfill(3)}' for i in range(1, 16)] # 15 runs for training
val_runs = [f'RUN-{str(i).zfill(3)}' for i in range(16, 21)]  # 5 runs for validation
test_runs = [f'RUN-{str(i).zfill(3)}' for i in range(21, 26)] # 5 runs for testing

X_train = sensor_df[sensor_df['run_id'].isin(train_runs)][features]
y_train = sensor_df[sensor_df['run_id'].isin(train_runs)]['bottleneck_15min_ahead']

X_test = sensor_df[sensor_df['run_id'].isin(test_runs)][features]
y_test = sensor_df[sensor_df['run_id'].isin(test_runs)]['bottleneck_15min_ahead']

print(f"Training on {len(X_train)} samples. Testing on {len(X_test)} completely unseen samples.")

print("\n6. Train Model 2 (Temporal Features)")
model = RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1, class_weight='balanced')
model.fit(X_train, y_train)

print("\n7. Evaluate on Test Set")
y_pred = model.predict(X_test)
if len(model.classes_) == 2:
    y_pred_proba = model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, y_pred_proba)
else:
    auc = float('nan')

print("\n===== MODEL 2 RESULTS (History/Temporal) =====")
print(classification_report(y_test, y_pred, zero_division=0))
print(f"ROC AUC Score: {auc:.4f}")
print("==============================================")

print("\nFeature Importances:")
if len(model.classes_) == 2:
    importances = model.feature_importances_
    fi = pd.DataFrame({'Feature': features, 'Importance': importances}).sort_values(by='Importance', ascending=False)
    print(fi.to_string(index=False))
