# TwinPilot Defect Prediction Model v2 — Complete Summary

This document details all changes made, the dataset overhaul, the training process, evaluation metrics, and conclusions for **Defect Prediction Model v2**.

---

## 1. Context & Motivation

In **Defect Model v1**, the model achieved an ROC-AUC of **0.4980** (equivalent to random guessing) because the original dataset contained only **3 defect events** across 25 production shifts. When split strictly across runs:
- Train set (Runs 1–15) had only **1 defect event** (originating at S23).
- Test set (Runs 21–25) had **1 defect event** (originating at S11).

The model could not generalize from a single station pattern to an unseen station.

---

## 2. Dataset v2 Overhaul (`generate_multirun_dataset.py`)

We modified the dataset generation engine to create a rich, realistic, and varied defect landscape while preserving strict negative controls (clean shifts):

### Key Dataset Changes:
1. **Event Count Scaled Up:** Increased `defect_propagation` events from **3 → 25** across 25 shifts.
2. **Varied Origin Stations:** Spread origins across **16 unique assembly stations** (S01, S03, S05, S07, S08, S11, S13, S14, S15, S16, S17, S18, S19, S21, S22, S26).
3. **5 Distinct Signal Mechanisms:** Defects no longer just slow down cycle times; they have unique multi-sensor fingerprints:
   - `torque_drift` (3 events): Early torque rise precedes defect.
   - `vibration_spike` (4 events): Vibration spikes sharply before propagation.
   - `temperature_shift` (5 events): Thermal climb with secondary torque changes.
   - `cycle_time_drift` (5 events): Station slowdown and queue buildup.
   - `component_quality` (8 events): Dual torque + vibration deviations.
4. **Preserved Clean Shifts:** Runs 4, 12, and 19 were preserved as defect-free negative controls.
5. **Preserved Co-occurring Events:** Bottlenecks (6), machine failures (5), and sensorless drift events (4) remained active.

### Split Breakdown in Dataset v2:
- **Train (RUN-001 to RUN-015):** 14 defect events (1,245 positive minutes across danger zones)
- **Validation (RUN-016 to RUN-020):** 5 defect events (405 positive minutes)
- **Test (RUN-021 to RUN-025):** 6 defect events (420 positive minutes)

---

## 3. Model Training Methodology (`defect_model.py`)

1. **No-Leakage Rule Enforced:** `status_flag`, `active_event_ids`, and ground truth columns were strictly excluded from feature inputs.
2. **Structural Context Added:** Station sequence number (`station_num`, e.g., S23 → 23) was included as a factory layout property.
3. **Missing Sensors Handled:** Sensorless/partial stations filled with `-1` (representing physical absence, not missing data).
4. **Temporal Feature Pipeline (21 features):**
   - Instantaneous values: cycle time, torque, vibration, temperature, queue.
   - Rolling averages (5m & 10m): cycle time, queue, torque, vibration.
   - Rate-of-change deltas (5m & 10m): cycle time, queue, torque, vibration.
5. **Classifier:** `RandomForestClassifier(n_estimators=200, class_weight='balanced', random_state=42)`.

---

## 4. Evaluation Results on Unseen Test Runs (RUN-021 to RUN-025)

### Performance Comparison:

| Metric | Defect Model v1 (3 events) | **Defect Model v2 (25 events)** |
| :--- | :--- | :--- |
| **ROC-AUC Score** | 0.4980 *(Random)* | **0.6291 *(Learning Real Signal)*** |
| **Accuracy** | 1.00 *(Trivial baseline)* | **0.95** |
| **Precision** (threshold 0.10) | 0.00 | **0.03** |
| **Recall** (threshold 0.10) | 0.00 | **0.09** |
| **F1-Score** | 0.00 | **0.04** |
| **Event Detection Rate** | 0 / 1 (0%) | **6 / 6 (100%)** |

### Confusion Matrix (Test Set, Threshold = 0.10):

```text
                  Predicted Normal (0)    Predicted Defect (1)
Actual Normal (0)             35,369                   1,411  (False Alarms)
Actual Defect (1)                381                      39  (True Positives)
```
- **True Negatives (TN):** 35,369
- **False Positives (FP):** 1,411
- **False Negatives (FN):** 381
- **True Positives (TP):** 39

---

## 5. Early Detection & Lead Time Breakdown

Every single defect event in the unseen test shifts was caught before peak propagation:

| Test Event | Origin Station | Peak Minute | 1st Alert Minute | Lead Time | Result |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **RUN021-EVT01** | S05 | Min 49 | Min 48 | **1 min** | ✅ Detected |
| **RUN021-EVT02** | S16 | Min 198 | Min 61 | **137 min** | ✅ Early Warning |
| **RUN022-EVT01** | S16 | Min 169 | Min 100 | **69 min** | ✅ Early Warning |
| **RUN023-EVT01** | S18 | Min 47 | Min 20 | **27 min** | ✅ Early Warning |
| **RUN024-EVT01** | S03 | Min 148 | Min 142 | **6 min** | ✅ Detected |
| **RUN025-EVT01** | S14 | Min 170 | Min 78 | **92 min** | ✅ Early Warning |

---

## 6. What the Model Prioritizes (Feature Importances)

Because defects now exhibit diverse signal types, importance is distributed across all telemetry channels rather than dominated by a single metric:

| Rank | Feature | Importance | Physical Meaning |
| :--- | :--- | :--- | :--- |
| 1 | `avg_cycle_time_10m` | **10.1%** | Sustained drift in station processing time |
| 2 | `station_num` | **9.3%** | Line layout position (upstream vs downstream) |
| 3 | `avg_cycle_time_5m` | **8.3%** | Short-term cycle time drift |
| 4 | `avg_vibration_5m` | **6.8%** | Mechanical chatter / fixture looseness |
| 5 | `change_cycle_time_10m` | **6.8%** | Rate of station degradation |
| 6 | `avg_queue_10m` | **6.5%** | Upstream accumulation |
| 7 | `cycle_time_sec` | **6.1%** | Instantaneous cycle time |
| 8 | `change_cycle_time_5m` | **5.8%** | Immediate cycle time slowdown |
| 9 | `temperature_c` | **5.7%** | Tool / process thermal drift |
| 10 | `avg_torque_5m` | **5.4%** | Fastener tightening anomalies |

---

## 7. Summary of Artifacts & Files

| File | Status | Description |
| :--- | :--- | :--- |
| [`twinpilot_dataset_v2.zip`](file:///c:/Users/Shuka/OneDrive/Desktop/TwinPilot/twinpilot_dataset_v2.zip) | Created | Complete 25-shift dataset with 25 multi-modal defect events |
| [`defect_model.py`](file:///c:/Users/Shuka/OneDrive/Desktop/TwinPilot/defect_model.py) | Updated | Retrained Defect Model v2 script with confusion matrix & threshold evaluation |
| [`TwinPilot_Defect_Model_v2.md`](file:///c:/Users/Shuka/OneDrive/Desktop/TwinPilot/TwinPilot_Defect_Model_v2.md) | Created | This complete experiment documentation |
