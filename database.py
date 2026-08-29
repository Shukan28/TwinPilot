"""
TwinPilot Multi-Tenant Relational Database Engine (SQLite)
=========================================================
Provides persistent multi-company, multi-factory relational storage for:
- Companies & User Accounts (Authentication & RBAC)
- Factory Workspaces & Physical Line Configurations
- Custom Telemetry Datasets & Schema Ingestion
- Factory-Specific Model Weights & Baseline Profiles
- Production Runs & Operator Intervention Audit Logs

Pre-seeds the current 31-station automotive assembly plant as the permanent,
unaltered default demo factory.
"""

import os
import sqlite3
import json
import logging
from datetime import datetime

logger = logging.getLogger("twinpilot.database")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "twinpilot.db")
DATASET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "twinpilot_dataset_extracted", "twinpilot_dataset")


def get_db_connection():
    """Returns a SQLite connection with Row factory and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_database():
    """Initializes all database tables and seeds the default demo factory."""
    conn = get_db_connection()
    cur = conn.cursor()

    # 1. Companies Table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS companies (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        industry TEXT DEFAULT 'Automotive / Discrete Manufacturing',
        tier TEXT DEFAULT 'Enterprise',
        created_at TEXT NOT NULL
    )
    """)

    # 2. Users Table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        company_id TEXT NOT NULL,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT DEFAULT 'operator',
        created_at TEXT NOT NULL,
        FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
    )
    """)

    # 3. Factories Table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS factories (
        id TEXT PRIMARY KEY,
        company_id TEXT NOT NULL,
        name TEXT NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        location TEXT DEFAULT 'Global',
        is_demo INTEGER DEFAULT 0,
        status TEXT DEFAULT 'active',
        created_at TEXT NOT NULL,
        FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
    )
    """)

    # 4. Factory Datasets / Uploads Metadata
    cur.execute("""
    CREATE TABLE IF NOT EXISTS factory_datasets (
        id TEXT PRIMARY KEY,
        factory_id TEXT NOT NULL,
        dataset_type TEXT NOT NULL,
        filename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        row_count INTEGER DEFAULT 0,
        validation_status TEXT DEFAULT 'pending',
        validation_report TEXT,
        uploaded_at TEXT NOT NULL,
        FOREIGN KEY (factory_id) REFERENCES factories(id) ON DELETE CASCADE
    )
    """)

    # 5. Factory Stations Table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS factory_stations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        factory_id TEXT NOT NULL,
        station_id TEXT NOT NULL,
        station_name TEXT NOT NULL,
        line_phase TEXT DEFAULT 'Assembly',
        baseline_cycle_time_sec REAL DEFAULT 45.0,
        sensor_tier TEXT DEFAULT 'PARTIAL',
        station_order INTEGER DEFAULT 1,
        created_at TEXT NOT NULL,
        UNIQUE (factory_id, station_id),
        FOREIGN KEY (factory_id) REFERENCES factories(id) ON DELETE CASCADE
    )
    """)

    # 6. Factory Dependencies / Graph Topology Table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS factory_dependencies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        factory_id TEXT NOT NULL,
        upstream_station_id TEXT NOT NULL,
        downstream_station_id TEXT NOT NULL,
        buffer_capacity INTEGER DEFAULT 10,
        transit_time_sec REAL DEFAULT 5.0,
        FOREIGN KEY (factory_id) REFERENCES factories(id) ON DELETE CASCADE
    )
    """)

    # 7. Factory Model Weights & Baseline Cache
    cur.execute("""
    CREATE TABLE IF NOT EXISTS factory_models (
        id TEXT PRIMARY KEY,
        factory_id TEXT NOT NULL,
        model_type TEXT NOT NULL,
        metrics_json TEXT,
        weights_json TEXT,
        trained_at TEXT NOT NULL,
        FOREIGN KEY (factory_id) REFERENCES factories(id) ON DELETE CASCADE
    )
    """)

    # 8. Multi-Tenant User Sessions
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_sessions (
        session_token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        active_factory_id TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (active_factory_id) REFERENCES factories(id) ON DELETE CASCADE
    )
    """)

    conn.commit()
    conn.close()

    # Seed demo company and factory
    seed_default_demo_factory()


def seed_default_demo_factory():
    """
    Seeds the default demo company and factory ('demo-detroit-31')
    using the existing 31-station automotive assembly dataset.
    Never overwrites or replaces any custom data.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    demo_company_id = "comp_demo_apex"
    demo_factory_id = "demo-detroit-31"

    # Check if demo company exists
    cur.execute("SELECT id FROM companies WHERE id = ?", (demo_company_id,))
    if not cur.fetchone():
        now_str = datetime.utcnow().isoformat() + "Z"
        cur.execute("""
        INSERT INTO companies (id, name, industry, tier, created_at)
        VALUES (?, ?, ?, ?, ?)
        """, (demo_company_id, "Apex Mobility Global", "Automotive OEM", "Enterprise", now_str))

        # Demo Admin User
        import hashlib
        demo_pwd_hash = hashlib.pbkdf2_hmac(
            'sha256', 'demo1234'.encode('utf-8'), b'twinpilot_static_salt_2026', 100000
        ).hex()

        cur.execute("""
        INSERT INTO users (id, company_id, name, email, password_hash, role, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("user_demo_lead", demo_company_id, "Chief Plant Operator", "demo@twinpilot.ai", demo_pwd_hash, "admin", now_str))

    # Check if demo factory exists
    cur.execute("SELECT id FROM factories WHERE id = ?", (demo_factory_id,))
    if not cur.fetchone():
        now_str = datetime.utcnow().isoformat() + "Z"
        cur.execute("""
        INSERT INTO factories (id, company_id, name, slug, location, is_demo, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            demo_factory_id,
            demo_company_id,
            "Detroit Assembly Plant #4 (31 Stations — Pre-loaded Demo)",
            "detroit-plant-4",
            "Detroit, MI, USA",
            1,
            "active",
            now_str
        ))

        # Seed stations from stations_master.csv if available
        st_csv = os.path.join(DATASET_DIR, "stations_master.csv")
        if os.path.exists(st_csv):
            import pandas as pd
            df_st = pd.read_csv(st_csv)
            for idx, row in df_st.iterrows():
                cur.execute("""
                INSERT OR IGNORE INTO factory_stations
                (factory_id, station_id, station_name, line_phase, baseline_cycle_time_sec, sensor_tier, station_order, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    demo_factory_id,
                    str(row["station_id"]),
                    str(row["station_name"]),
                    str(row.get("line_phase", "Final Assembly")),
                    float(row.get("baseline_cycle_time_sec", 45.0)),
                    str(row.get("sensor_tier", "PARTIAL")),
                    int(idx + 1),
                    now_str
                ))

        # Seed dependencies from station_dependencies.csv if available
        dep_csv = os.path.join(DATASET_DIR, "station_dependencies.csv")
        if os.path.exists(dep_csv):
            import pandas as pd
            df_dep = pd.read_csv(dep_csv)
            for _, row in df_dep.iterrows():
                cur.execute("""
                INSERT INTO factory_dependencies
                (factory_id, upstream_station_id, downstream_station_id, buffer_capacity, transit_time_sec)
                VALUES (?, ?, ?, ?, ?)
                """, (
                    demo_factory_id,
                    str(row["upstream_station_id"]),
                    str(row["downstream_station_id"]),
                    int(row.get("buffer_capacity", 10)),
                    float(row.get("transit_time_sec", 5.0))
                ))

    conn.commit()
    conn.close()


# Automatically initialize tables on import
init_database()
