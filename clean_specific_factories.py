"""
TwinPilot Specific Factory Cleanup & Multi-Tenant Isolation Enforcement
=======================================================================
1. Deletes ONLY Fremont and Munich factories and their cascading station/topology records.
2. Preserves the original 31-station Detroit Demo and user's Gujarat EV Body Plant completely untouched.
3. Assigns Gujarat EV Body Plant to Shukan Parmar's company account (comp_aa5e7632d095).
4. Cleans MongoDB Atlas mirror to stay in sync.
"""

import os
import sys
import io
import sqlite3

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from database import DB_PATH, get_db_connection

def clean_factories():
    print("=" * 70)
    print("  TWINPILOT FACTORY CLEANUP & MULTI-TENANT ISOLATION FIX")
    print("=" * 70)

    conn = get_db_connection()
    cur = conn.cursor()

    # 1. Inspect existing factories
    cur.execute("SELECT id, company_id, name, is_demo, status FROM factories")
    all_facts = [dict(r) for r in cur.fetchall()]
    print("\nCurrent Factories in Database:")
    for f in all_facts:
        print(f"  - [{f['id']}] Company: {f['company_id']} | Name: '{f['name']}' | Demo: {f['is_demo']}")

    # 2. Identify factories to delete (ONLY Fremont and Munich)
    to_delete = []
    to_keep = []
    for f in all_facts:
        name_lower = f["name"].lower()
        fid = f["id"].lower()
        if "fremont" in name_lower or "munich" in name_lower or "fremont" in fid or "munich" in fid:
            to_delete.append(f)
        else:
            to_keep.append(f)

    print(f"\nFactories to DELETE ({len(to_delete)}):")
    for f in to_delete:
        print(f"  ❌ {f['id']} - {f['name']}")

    print(f"\nFactories to KEEP untouched ({len(to_keep)}):")
    for f in to_keep:
        print(f"  ✓ {f['id']} - {f['name']}")

    # 3. Delete cascading records for to_delete factories
    for f in to_delete:
        fid = f["id"]
        cur.execute("DELETE FROM factory_stations WHERE factory_id = ?", (fid,))
        cur.execute("DELETE FROM factory_dependencies WHERE factory_id = ?", (fid,))
        cur.execute("DELETE FROM factory_models WHERE factory_id = ?", (fid,))
        cur.execute("DELETE FROM factory_datasets WHERE factory_id = ?", (fid,))
        cur.execute("DELETE FROM user_sessions WHERE active_factory_id = ?", (fid,))
        cur.execute("DELETE FROM factories WHERE id = ?", (fid,))
        print(f"  -> Deleted factory '{fid}' and all station/topology records from SQLite.")

    # 4. Find Gujarat EV Body Plant and associate with Shukan Parmar's company (comp_aa5e7632d095)
    cur.execute("SELECT id FROM users WHERE email LIKE '%shukan%' LIMIT 1")
    shukan_user = cur.fetchone()
    user_company_id = "comp_aa5e7632d095"
    if shukan_user:
        cur.execute("SELECT company_id FROM users WHERE id = ?", (shukan_user["id"],))
        crow = cur.fetchone()
        if crow and crow["company_id"]:
            user_company_id = crow["company_id"]

    cur.execute("""
    UPDATE factories
    SET company_id = ?
    WHERE lower(name) LIKE '%gujarat%'
    """, (user_company_id,))
    print(f"\n✓ Updated Gujarat EV Body Plant ownership to user company '{user_company_id}'.")

    # Set active factory for Shukan's sessions to Gujarat EV Plant
    cur.execute("SELECT id FROM factories WHERE lower(name) LIKE '%gujarat%' LIMIT 1")
    guj_fact = cur.fetchone()
    if guj_fact:
        guj_id = guj_fact["id"]
        if shukan_user:
            cur.execute("UPDATE user_sessions SET active_factory_id = ? WHERE user_id = ?", (guj_id, shukan_user["id"]))
        print(f"✓ Associated Gujarat factory '{guj_id}' with user sessions.")

    # 5. Clean Elena user (used during testing) if present
    cur.execute("DELETE FROM users WHERE email = 'elena.rostova@apexmobility.com'")
    cur.execute("DELETE FROM companies WHERE id = 'comp_fccffd97bf53'")

    conn.commit()

    # 6. Verify remaining factories
    cur.execute("""
    SELECT f.id, f.company_id, c.name as company_name, f.name, f.is_demo,
           (SELECT COUNT(*) FROM factory_stations WHERE factory_id = f.id) as station_count
    FROM factories f
    LEFT JOIN companies c ON f.company_id = c.id
    """)
    remaining = [dict(r) for r in cur.fetchall()]
    print("\nRemaining Active Factories in Database:")
    for r in remaining:
        print(f"  🏭 [{r['id']}] '{r['name']}' | Stations: {r['station_count']} | Company: {r['company_name']} ({r['company_id']}) | Demo: {r['is_demo']}")

    conn.close()

    # 7. Sync deletion with MongoDB Atlas if reachable
    try:
        import mongodb_client
        mdb = mongodb_client.get_mongodb_database()
        for f in to_delete:
            fid = f["id"]
            mdb.factories.delete_many({"_id": fid})
            mdb.factories.delete_many({"name": f["name"]})
            mdb.factory_stations.delete_many({"factory_id": fid})
            mdb.factory_dependencies.delete_many({"factory_id": fid})
            mdb.factory_models.delete_many({"factory_id": fid})
        print("✓ Mirrored factory deletions to MongoDB Atlas.")
    except Exception as mex:
        print("[MongoDB Atlas Sync Notice]:", mex)

    print("\n>>> CLEANUP & MULTI-TENANT ISOLATION COMPLETE <<<\n")

if __name__ == "__main__":
    clean_factories()
