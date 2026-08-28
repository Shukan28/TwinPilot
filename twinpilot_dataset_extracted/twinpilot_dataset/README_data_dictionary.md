# TwinPilot — Simulated Production Dataset (Round 2)

A simplified but internally consistent simulation of a mixed-model vehicle assembly line: **31 stations** across Body Construction, Paint, and Final Assembly, run across **25 independent production shifts** (one simulated day each), with uneven sensor coverage and randomized scenario mixes per shift. Built to match the Round 2 brief's reference parameters (30–50 stations, mixed sensor coverage, mixed-model production, limited maintenance windows) — and, per your request, to give a model genuine variety to learn from rather than one shift copy-pasted many times.

**186,000 telemetry rows** (25 runs × 31 stations × 240 minutes), **19 distinct ground-truth events** spread unevenly across shifts, **9 completely clean baseline shifts** (zero anomalies — your negative controls), and **4,500 VINs** across the full run.

Every file is keyed by `run_id` (`RUN-001`…`RUN-025`) in addition to its own keys — always filter/group by `run_id` before doing any time-series work, since minute_index and timestamps repeat across runs (each run is its own independent 4-hour shift, not a continuation of the previous one).

## Files

### `production_runs.csv` — index of all 25 shifts
One row per run: `run_id`, `shift_start`, `n_events`, `event_types_present`, `had_scheduled_maintenance`, `n_vehicles`. Start here to see what's in each shift before diving into the detail files. 9 of the 25 runs have `n_events == 0` — pure normal-operation baselines, useful so your model learns what "nothing wrong" looks like, not just anomalies.

### `stations_master.csv` / `station_dependencies.csv` — shared line structure (unchanged across all runs)
| column | meaning |
|---|---|
| station_id | e.g. `S07`; `ENG01` is a parallel feeder line (engine/transmission sub-assembly) that merges into `S23` |
| sensor_tier | `rich` (cycle_time+torque+vibration[+temp]), `partial` (cycle_time + one other signal), `manual` (no digital sensors — cycle_time is still timestamped via line tracking, but no torque/vibration/temperature) |
| upstream_station_id | direct upstream dependency(ies) — `S23` has two (`S22,ENG01`), the one real merge point in the graph |

**18 rich / 7 partial / 6 manual.** Notably, **S29 Final Inspection and S30 Road Test are themselves manual-only** — the last line of defense has no sensors, which is exactly why upstream prediction matters. This structure is identical across all 25 runs.

### `sensor_timeseries.csv` — 186,000 rows (25 runs × 31 stations × 240 min)
| column | meaning |
|---|---|
| run_id, timestamp, minute_index, station_id | keys — **always scope by run_id first** |
| cycle_time_sec, torque_nm, vibration_mm_s, temperature_c | `null` wherever that station/signal isn't instrumented for that tier — this is the sparse-sensor reality, don't backfill it |
| queue_length | simple proxy for units waiting at the station |
| status_flag | `normal` / `warning` / `critical` / `maintenance` — **ground truth**, derived from that run's scripted events. Use it to score precision/recall; don't feed it into your model as an input feature. |
| active_event_ids | which `events_ground_truth` row(s) are live at that station/minute/run, if any |

### `events_ground_truth.csv` — 19 events across the 25 runs, the answer key
Each event has its own randomized `event_type` (`bottleneck`, `defect_propagation`, `sensorless_drift`, `machine_failure`), origin station, severity, and timing (`start_minute` → `detectable_minute` → `peak_minute` → `resolved_minute`), plus a `propagation_path` (comma list of downstream stations affected, in order) you can use to validate a model's predicted causal chain against ground truth. Some runs have multiple concurrent events (see `RUN-017`, which has 4) to test how well a model separates overlapping anomalies.

Event types, in brief:
- **bottleneck** — gradual cycle-time/torque drift at the origin, rippling downstream
- **defect_propagation** — a quality issue that isn't caught until much later downstream (sometimes only at a manual station), the "dozens of vehicles undetected" scenario from the original brief
- **sensorless_drift** — degradation *originating at a manual-tier station* (no direct sensor), only inferable from neighboring stations' drift — this is the dataset for your Dark Zone / Sensorless Inference feature
- **machine_failure** — a sudden, short, high-severity spike — good input for a Stress-Test Simulator feature

### `maintenance_windows.csv` — 3 scheduled windows across the 25 runs
Only ~20% of shifts have one, matching the brief's "production can only be paused... during a small number of scheduled maintenance windows." Useful as a negative/control case so a model doesn't misclassify planned downtime as an anomaly.

### `manual_checks.csv` — 1,650 periodic logs (25 runs × 6 manual stations × ~11 checks/shift)
`result` is `Pass` by default; entries near a `defect_propagation` or `sensorless_drift` event's peak are marked `Fail`/`Flagged` with a note referencing the event — these are the moments a human eventually caught what the twin should have predicted earlier.

### `vehicles.csv` — 4,500 VINs (180 per run × 25 runs, mixed model: 50% Sedan / 35% SUV / 15% EV)
Each VIN has a `run_id`, `line_entry_time`, and boolean flags (`bottleneck_impacted`, `defect_risk`, `sensorless_drift_flagged`, `machine_failure_impacted`, `flagged_for_inspection`) showing which vehicles were on the line during that run's active event windows — the ground truth for an "at-risk VINs" feature. `affected_events` names the specific event_id(s) involved.

## Suggested modeling approach (ties back to the Round 2 prompt's "Solutioning Areas")
- **Train/validate split by run_id**, not by random row — holding out entire shifts (e.g. train on RUN-001–020, validate on RUN-021–025) tests generalization to new production days far better than a random row split would, since rows within a run are highly correlated.
- **Sensor-poor stations**: predict/impute manual-tier state from upstream cycle_time + downstream queue_length trends at neighboring rich stations — `sensorless_drift` events are the labeled ground truth for this.
- **Predictive lead time**: for `bottleneck` events, check whether a model flags "warning" meaningfully before `peak_minute` — compare against the labeled `detectable_minute` to quantify claimed lead time.
- **False-alarm control**: the 3 scheduled-maintenance runs and 9 zero-event runs are your negative controls — a good model should stay quiet on all of them.
- **Root-cause tracing**: each event's `propagation_path` is the causal chain your Defect Propagation Map feature should reconstruct from the timeseries alone, without being told the path in advance.

## Notes / assumptions
- This is a simplified simulation, not a physics-accurate one — cycle time, torque, vibration, and temperature are generated from a shared "event intensity" curve per station rather than independently modeled physical processes.
- Queue length is a lightweight proxy (Poisson baseline + event intensity), not true queueing-theory simulation.
- `generate_multirun_dataset.py` is the authoritative generation script — rerun it with a different `N_RUNS` to scale row count further, or edit the event-type weights/probabilities to shift the scenario mix. Each run uses a seeded RNG (`1000 + run_idx`) so results are reproducible.
- The earlier single-shift scripts (`generate_dataset.py`, `generate_timeseries.py`, `generate_manual_checks.py`, `generate_vehicles.py`) are kept for reference/history but are superseded by `generate_multirun_dataset.py` for anything going forward.

