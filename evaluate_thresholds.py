import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import precision_score, recall_score, confusion_matrix
# pyrefly: ignore [missing-import]
import numpy as np

print("Loading data and retraining model...")
dataset_dir = r"twinpilot_dataset_extracted\twinpilot_dataset"
sensor_df = pd.read_csv(f"{dataset_dir}\\sensor_timeseries.csv")
events_df = pd.read_csv(f"{dataset_dir}\\events_ground_truth.csv")

bottlenecks = events_df[events_df['event_type'] == 'bottleneck']
merged = pd.merge(sensor_df, bottlenecks[['run_id', 'origin_station_id', 'peak_minute']],
                  left_on=['run_id', 'station_id'],
                  right_on=['run_id', 'origin_station_id'],
                  how='left')
time_to_peak = merged['peak_minute'] - merged['minute_index']
sensor_df['bottleneck_15min_ahead'] = ((time_to_peak > 0) & (time_to_peak <= 15)).astype(int)

base_features = ['cycle_time_sec', 'queue_length', 'vibration_mm_s', 'torque_nm', 'temperature_c']
sensor_df[base_features] = sensor_df[base_features].fillna(-1)

sensor_df = sensor_df.sort_values(by=['run_id', 'station_id', 'minute_index'])
grouped = sensor_df.groupby(['run_id', 'station_id'])

sensor_df['avg_cycle_time_5m'] = grouped['cycle_time_sec'].rolling(window=5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
sensor_df['avg_cycle_time_10m'] = grouped['cycle_time_sec'].rolling(window=10, min_periods=1).mean().reset_index(level=[0,1], drop=True)
sensor_df['avg_queue_5m'] = grouped['queue_length'].rolling(window=5, min_periods=1).mean().reset_index(level=[0,1], drop=True)
sensor_df['avg_queue_10m'] = grouped['queue_length'].rolling(window=10, min_periods=1).mean().reset_index(level=[0,1], drop=True)
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

train_runs = [f'RUN-{str(i).zfill(3)}' for i in range(1, 16)]
val_runs = [f'RUN-{str(i).zfill(3)}' for i in range(16, 21)]
test_runs = [f'RUN-{str(i).zfill(3)}' for i in range(21, 26)]

# For evaluation, we will combine Val and Test to have more bottlenecks to look at
eval_runs = val_runs + test_runs

X_train = sensor_df[sensor_df['run_id'].isin(train_runs)][features]
y_train = sensor_df[sensor_df['run_id'].isin(train_runs)]['bottleneck_15min_ahead']

eval_mask = sensor_df['run_id'].isin(eval_runs)
X_eval = sensor_df[eval_mask][features]
y_eval = sensor_df[eval_mask]['bottleneck_15min_ahead']

model = RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1, class_weight='balanced')
model.fit(X_train, y_train)

y_pred_proba = model.predict_proba(X_eval)[:, 1]

# 2. Test different alert thresholds
print("\n--- THRESHOLD EVALUATION (Val + Test Sets) ---")
print("Target: 1 if bottleneck peak is within next 15 mins. (Total Positives in Eval: {})".format(y_eval.sum()))
thresholds = [0.1, 0.3, 0.5, 0.7, 0.9]
print(f"{'Threshold':<10} | {'Precision':<10} | {'Recall':<10} | {'False Alarms (FP)':<20} | {'Caught (TP)':<12}")
for t in thresholds:
    preds = (y_pred_proba >= t).astype(int)
    precision = precision_score(y_eval, preds, zero_division=0)
    recall = recall_score(y_eval, preds, zero_division=0)
    tn, fp, fn, tp = confusion_matrix(y_eval, preds).ravel()
    print(f"{t:<10.1f} | {precision:<10.2f} | {recall:<10.2f} | {fp:<20} | {tp:<12}")

# 3. Find Lead Time for each actual bottleneck in the eval set
eval_bottlenecks = events_df[(events_df['event_type'] == 'bottleneck') & (events_df['run_id'].isin(eval_runs))]

print("\n--- LEAD TIME ANALYSIS ---")
# Choosing a balanced threshold based on expected results (we will use 0.1 as a baseline)
chosen_threshold = 0.1
print(f"Using Alert Threshold: {chosen_threshold}")
print(f"{'Bottleneck Event':<20} | {'Actual Peak':<15} | {'First Warning':<15} | {'Lead Time':<10}")
print("-" * 65)

# Build a dataframe to easily query results by run and station
eval_results = sensor_df[eval_mask].copy()
eval_results['probability'] = y_pred_proba

for _, event in eval_bottlenecks.iterrows():
    run_id = event['run_id']
    origin_station = event['origin_station_id']
    peak_minute = event['peak_minute']
    event_id = event['event_id']
    
    # Filter for this event
    event_data = eval_results[(eval_results['run_id'] == run_id) & 
                              (eval_results['station_id'] == origin_station)]
                              
    # Find warnings that occurred BEFORE the peak
    warnings = event_data[(event_data['probability'] >= chosen_threshold) & 
                          (event_data['minute_index'] <= peak_minute)]
                          
    if len(warnings) > 0:
        first_warning_minute = warnings['minute_index'].min()
        lead_time = peak_minute - first_warning_minute
    else:
        first_warning_minute = "Missed"
        lead_time = "N/A"
        
    print(f"{event_id:<20} | {peak_minute:<15} | {first_warning_minute:<15} | {lead_time} min")
