"""
Cleanly remove Gujarat EV Body Plant from SQLite & MongoDB Atlas.
Leave ONLY Detroit Assembly Plant #4 (31 Stations — Pre-loaded Demo).
"""

import sys
import io
import sqlite3

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from database import get_db_connection

def remove_gujarat():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT id, name FROM factories WHERE lower(name) LIKE '%gujarat%' OR id = 'fact_a0c21e63b97d'")
    rows = cur.fetchall()

    for r in rows:
        fid = r["id"]
        fname = r["name"]
        print(f"Deleting factory: [{fid}] {fname}...")
        cur.execute("DELETE FROM factory_stations WHERE factory_id = ?", (fid,))
        cur.execute("DELETE FROM factory_dependencies WHERE factory_id = ?", (fid,))
        cur.execute("DELETE FROM factory_models WHERE factory_id = ?", (fid,))
        cur.execute("DELETE FROM factory_datasets WHERE factory_id = ?", (fid,))
        cur.execute("DELETE FROM factories WHERE id = ?", (fid,))
        print(f"  ✓ Deleted from SQLite.")

    # Reset all active factory sessions to demo-detroit-31
    cur.execute("UPDATE user_sessions SET active_factory_id = 'demo-detroit-31'")
    conn.commit()

    # Verify remaining factories
    cur.execute("SELECT id, name, is_demo, status FROM factories")
    remaining = [dict(r) for r in cur.fetchall()]
    print("\nRemaining Factories in SQLite:")
    for rem in remaining:
        print(f"  🏭 [{rem['id']}] {rem['name']} (Demo: {rem['is_demo']})")

    conn.close()

    # Mirror to MongoDB Atlas
    try:
        import mongodb_client
        mdb = mongodb_client.get_mongodb_database()
        mdb.factories.delete_many({"name": {"$regex": "gujarat", "$options": "i"}})
        mdb.factories.delete_many({"_id": "fact_a0c21e63b97d"})
        mdb.factory_stations.delete_many({"factory_id": "fact_a0c21e63b97d"})
        mdb.factory_dependencies.delete_many({"factory_id": "fact_a0c21e63b97d"})
        mdb.factory_models.delete_many({"factory_id": "fact_a0c21e63b97d"})
        mdb.user_sessions.update_many({}, {"$set": {"active_factory_id": "demo-detroit-31"}})
        print("✓ Mirrored deletion and session reset to MongoDB Atlas.")
    except Exception as mex:
        print("[MongoDB Atlas Notice]:", mex)

if __name__ == "__main__":
    remove_gujarat()
