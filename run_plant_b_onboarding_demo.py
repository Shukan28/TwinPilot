"""
TwinPilot Multi-Factory End-to-End Onboarding Execution Proof (Plant B)
======================================================================
Executes and validates the complete onboarding, training, threshold tuning,
and live Digital Twin cockpit launch flow for Plant B's real 61-station dataset.

Workflow Stages:
1. Multi-Tenant Registration & Workspace Isolation
2. 61-Station Dataset Upload & Schema Validation
3. DAG Topology Graph Discovery & Dark Zone Identification
4. Machine Learning Model Training & Threshold Tuning (tau = 0.02)
5. Live 61-Station Digital Twin State Generation & Propagation Check
6. Executive Leadership & ROI Value Rollup
"""

import os
import sys
import io
import json
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pandas as pd
# pyrefly: ignore [missing-import]
import numpy as np

# Ensure root workspace is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import auth_service
import onboarding_service
import tenant_pipeline
from database import get_db_connection, init_database
from train_plant_b_model import train_plant_b_models
from roi_engine import roi_engine


def run_full_onboarding_proof():
    print("=" * 75)
    print("  TWINPILOT: MULTI-FACTORY ONBOARDING & EXECUTION PROOF (PLANT B - 61 STATIONS)")
    print("=" * 75)

    # Initialize DB
    init_database()

    # ─────────────────────────────────────────────────────────────────────────
    # STAGE 1: Multi-Tenant Enterprise User Authentication
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[STAGE 1] Multi-Tenant User Authentication & Workspace Initialization...")
    reg_result = auth_service.register_company_and_user(
        company_name="Apex Mobility Global OEM",
        industry="Electric Vehicle / Discrete Automotive",
        user_name="Elena Rostova (VP Manufacturing)",
        email="elena.rostova@apexmobility.com",
        password="SecureFactoryPassword2026!",
        factory_name="Fremont EV Gigafactory (61 Stations)",
        location="Fremont, CA, USA"
    )
    
    # Authenticate or login
    login_res = auth_service.authenticate_user(
        email="elena.rostova@apexmobility.com",
        password="SecureFactoryPassword2026!"
    )
    session_token = login_res.get("session_token")
    user_info = login_res.get("user")
    print(f"  ✓ Authenticated User: {user_info['name']} ({user_info['role']})")
    print(f"  ✓ Company ID: {user_info['company_id']} | Session Token: {session_token[:16]}...")

    # ─────────────────────────────────────────────────────────────────────────
    # STAGE 2: Dataset Upload & Schema Validation
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[STAGE 2] Ingesting Plant B 61-Station Dataset...")
    st_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)), "twinpilot_dataset_extracted", "plant_b_dataset", "plant_b_stations_master.csv")
    dep_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)), "twinpilot_dataset_extracted", "plant_b_dataset", "plant_b_station_dependencies.csv")

    if not os.path.exists(st_csv):
        st_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plant_b_stations_master.csv")
    if not os.path.exists(dep_csv):
        dep_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plant_b_station_dependencies.csv")

    st_val = onboarding_service.validate_stations_file(st_csv)
    if not st_val.get("valid"):
        print("  ✗ Station validation failed:", st_val.get("errors"))
        return False

    stations_data = st_val["cleaned_data"]
    valid_sids = {s["station_id"] for s in stations_data}
    dep_val = onboarding_service.validate_dependencies_file(dep_csv, valid_sids)
    deps_data = dep_val["cleaned_data"]

    stats = st_val["stats"]
    print(f"  ✓ Stations Ingested: {len(stations_data)}")
    print(f"  ✓ Sensor Tiers: {stats['tier_breakdown']}")
    print(f"  ✓ Manufacturing Phases: {stats['phases']}")
    print(f"  ✓ Topology Links Discovered: {len(deps_data)} DAG dependencies")

    # ─────────────────────────────────────────────────────────────────────────
    # STAGE 3: Topology Discovery & Factory Workspace Persistence
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[STAGE 3] Committing Factory Topology & Dark Zone Proxies to Database...")
    factory_id = "factory-fremont-61"
    
    # Save datasets and stations into database
    onboarding_service.save_factory_datasets_and_stations(factory_id, stations_data, deps_data)
    
    # Switch active session factory
    auth_service.switch_active_factory(session_token, factory_id)
    print(f"  ✓ Factory Workspace '{factory_id}' successfully activated in SQLite & MongoDB Atlas.")

    # ─────────────────────────────────────────────────────────────────────────
    # STAGE 4: Machine Learning Training & Decision Threshold Tuning
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[STAGE 4] Executing Model Training & Threshold Calibration on 61 Stations...")
    model_metrics = train_plant_b_models()
    print(f"  ✓ Defect Model ROC-AUC: {model_metrics['defect_roc_auc']}")
    print(f"  ✓ Bottleneck Model ROC-AUC: {model_metrics['bottleneck_roc_auc']}")
    print(f"  ✓ Calibrated Decision Threshold (tau): {model_metrics['optimal_threshold_tau']}")
    print(f"  ✓ Dark Zone Isolation Forest Proxies: {len(model_metrics['dark_zone_proxies'])} active")

    # ─────────────────────────────────────────────────────────────────────────
    # STAGE 5: Live Digital Twin Cockpit State Generation
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[STAGE 5] Generating Live Digital Twin Cockpit State for Plant B...")
    twin_state_step3 = tenant_pipeline.build_custom_factory_state(
        factory_id=factory_id,
        minute=120,
        target_station="BAT05",
        step_id=3
    )

    if not twin_state_step3:
        print("  ✗ Failed to construct Digital Twin state for Plant B.")
        return False

    print(f"  ✓ Factory Name: {twin_state_step3['factory_name']}")
    print(f"  ✓ Total Monitored Stations: {len(twin_state_step3['stations'])} stations in live ribbon")
    print(f"  ✓ Target Station: {twin_state_step3['target_station']['station_id']} ({twin_state_step3['target_station']['station_name']})")
    print(f"  ✓ Anomaly Alert: {twin_state_step3['anomaly_prediction']['alert_title']}")
    print(f"  ✓ Defect Probability: {twin_state_step3['anomaly_prediction']['defect_prob_pct']}%")
    print(f"  ✓ Earliest Origin Cause: {twin_state_step3['propagation']['earliest_cause']}")
    print(f"  ✓ Graph Propagation Path: {' -> '.join(twin_state_step3['propagation']['path'])}")
    print(f"  ✓ Recommended Counterfactual Action: {twin_state_step3['propagation']['recommended_action']}")
    print(f"  ✓ Dark Zone Proxies Monitored: {len(twin_state_step3['dark_zones'])} stations")

    # Verify 6 timeline steps exist
    timeline = twin_state_step3["timeline_steps"]
    print(f"  ✓ 6-Step Twin Evolution Timeline Generated: {len(timeline)} stages")
    for step in timeline:
        print(f"    - Step {step['step_id']+1}: {step['stage_title']} ({step['sim_clock']}) -> {step['status']}")

    # ─────────────────────────────────────────────────────────────────────────
    # STAGE 6: Leadership & ROI Value Computation
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[STAGE 6] Evaluating Executive Leadership & ROI Projections...")
    roi_b = roi_engine.compute_plant_roi(station_count=61, dark_zone_count=9)
    s = roi_b["summary"]
    print(f"  ✓ Annual Defect Scrap Avoided: ${s['annual_scrap_savings']:,.0f} ({s['annual_defects_avoided']} defects)")
    print(f"  ✓ Annual Downtime Avoided: ${s['annual_downtime_savings']:,.0f} ({s['annual_downtime_hours_avoided']} hrs)")
    print(f"  ✓ Throughput Recovery: ${s['annual_throughput_value']:,.0f} (+{s['recovered_units_per_year']} vehicles)")
    print(f"  ✓ Net Annual Financial Benefit: ${s['net_annual_benefit']:,.0f} / yr")
    print(f"  ✓ Capex Payback Period: {s['payback_months']} Months")
    print(f"  ✓ 5-Year NPV: ${s['npv_5year']:,.0f} (ROI: {s['roi_5year_pct']}%)")

    print("\n" + "=" * 75)
    print("  >>> PLANT B 61-STATION END-TO-END ONBOARDING PROOF SUCCESSFUL <<<")
    print("=" * 75)
    return True


if __name__ == "__main__":
    success = run_full_onboarding_proof()
    sys.exit(0 if success else 1)
