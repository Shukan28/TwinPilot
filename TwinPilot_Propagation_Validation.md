# TwinPilot: Data-Driven Propagation & Vehicle Impact Validation

This report documents the design, execution, and validation results for **Steps 1, 2, and 3** of TwinPilot's defect propagation and vehicle tracking pipeline.

---

## 1. Executive Summary

| Phase | Key Question | Method / Implementation | Result on Unseen Test Runs |
| :--- | :--- | :--- | :--- |
| **Step 1: Data-Driven Propagation** | How do we determine where a defect travels? | Evaluates Defect Model v2 probability $P(\text{defect} \mid s)$ dynamically at each station and traverses directed factory graph (`station_dependencies.csv`). | Replaced distance decay heuristic with genuine ML evidence + factory topology. |
| **Step 2: Path Validation** | Can TwinPilot reconstruct the defect chain without being given the answer? | Evaluates predicted path vs. ground-truth propagation path across all 6 test events in `RUN-021` to `RUN-025`. | **71.4% Station Recovery Rate** (20/28 stations), **67.38% Mean Jaccard Similarity**. |
| **Step 3: VIN Impact Tracking** | Which specific vehicles were exposed? | Computes line-entry offsets and arrival minutes at affected stations during active defect windows. | **100.0% Precision & 100.0% Recall** (219 / 219 defect-exposed VINs quarantined, 0 false alarms, 0 escapes). |

---

## 2. Step 1: Data-Driven Propagation Architecture

Instead of applying a static rule where "risk decreases with distance", TwinPilot queries the trained Random Forest classifier (`Defect Model v2`) for station telemetry risk scores at event detection time:

$$\text{Next Station } S_{k+1} \in \text{Downstream}(S_k) \quad \text{included if } P(\text{Defect} \mid S_{k+1}) \ge \tau$$

### Example Risk Breakdown
When a defect triggers at **S16**, the engine evaluates downstream nodes:
- `S16`: **0.10** *(Origin)*
- `S17`: **0.28** *(Elevated vibration / cycle drift)*
- `S18`: **0.27** *(Elevated queue / torque deviation)*
- `S19`: **0.04** *(Below threshold $\tau=0.10 \implies$ Propagation terminates)*

**Predicted Propagation Path:** `S16 -> S17 -> S18`

---

## 3. Step 2: Validation Against Test Shift Ground Truth

Evaluated on all defect events in unseen shifts (**RUN-021 through RUN-025**):

| Event ID | Run | Origin | Defect Signal Type | Predicted Path (with ML Risk Scores) | Ground Truth Path | Station Overlap | Divergence Analysis |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **RUN021-EVT01** | RUN-021 | **S05** | `component_quality` | `S05(0.20) -> S06(0.36)` | `S05 -> S06 -> S07 -> S08 -> S09 -> S10 -> S11` | 2 / 7 (28.6%) | Truncated before S07 |
| **RUN021-EVT02** | RUN-021 | **S16** | `torque_drift` | `S16(0.10) -> S17(0.28) -> S18(0.27)` | `S16 -> S17 -> S18` | 3 / 3 (100.0%) | **Exact Match** |
| **RUN022-EVT01** | RUN-022 | **S16** | `temperature_shift` | `S16(0.07) -> S17(0.12) -> S18(0.14) -> S19(0.23) -> S20(0.32) -> S21(0.11) -> S22(0.22)` | `S16 -> S17 -> S18 -> S19 -> S20 -> S21` | 6 / 6 (100.0%) | Over-propagated to S22 |
| **RUN023-EVT01** | RUN-023 | **S18** | `component_quality` | `S18(0.56) -> S19(0.23) -> S20(0.23) -> S21(0.32) -> S22(0.22)` | `S18 -> S19 -> S20` | 3 / 3 (100.0%) | Over-propagated to S21 |
| **RUN024-EVT01** | RUN-024 | **S03** | `cycle_time_drift` | `S03(0.36) -> S04(0.30) -> S05(0.10) -> S06(0.10)` | `S03 -> S04 -> S05 -> S06 -> S07` | 4 / 5 (80.0%) | Truncated before S07 |
| **RUN025-EVT01** | RUN-025 | **S14** | `cycle_time_drift` | `S14(0.24) -> S15(0.37)` | `S14 -> S15 -> S16 -> S17` | 2 / 4 (50.0%) | Truncated before S16 |

### Overall Path Reconstruction Metrics:
- **Total True Path Stations:** 28
- **Correctly Reconstructed Stations:** 20 (**71.4%**)
- **Mean Jaccard Similarity:** **67.38%**

---

## 4. Step 3: Vehicle / VIN Impact Tracking & Validation

Using cumulative line cycle timing and model variant multipliers (Sedan 1.0x, SUV 1.05x, EV 1.12x), TwinPilot calculates the exact arrival window of each VIN at the affected stations during the active defect window $[\hat{t}_{\text{start}}, \hat{t}_{\text{resolved}}]$.

### Test Set VIN Confusion Matrix (900 Total Test Vehicles):

```text
                           Actual Normal VINs    Actual Defect VINs
Predicted Cleared (0)             681                    0  (False Negatives)
Predicted At-Risk (1)               0                  219  (True Positives)
```

- **True Positives (TP):** 219 *(Correctly quarantined)*
- **False Positives (FP):** 0 *(Zero unnecessary rework)*
- **False Negatives (FN):** 0 *(Zero defect escapes to customer)*
- **True Negatives (TN):** 681 *(Cleared vehicles)*

### Performance Scores:
- **Accuracy:** **100.00%**
- **Precision:** **100.00%**
- **Recall (Containment):** **100.00%**
- **F1-Score:** **100.00%**

---

## 5. Artifacts & Code Modules

- [`propagation_engine.py`](file:///c:/Users/Shuka/OneDrive/Desktop/TwinPilot/propagation_engine.py): Core module with `DefectModelService`, graph traversal, risk scoring, and VIN timing resolution.
- [`validate_propagation_and_vins.py`](file:///c:/Users/Shuka/OneDrive/Desktop/TwinPilot/validate_propagation_and_vins.py): Automated test script computing path accuracy, divergence analysis, and VIN confusion matrix.
