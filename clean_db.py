import sqlite3

conn = sqlite3.connect('twinpilot.db')
cur = conn.cursor()

# 1. Delete all non-demo factories and their cascading child records
cur.execute("DELETE FROM factory_stations WHERE factory_id != 'demo-detroit-31'")
cur.execute("DELETE FROM factory_dependencies WHERE factory_id != 'demo-detroit-31'")
cur.execute("DELETE FROM factory_models WHERE factory_id != 'demo-detroit-31'")
cur.execute("DELETE FROM factory_datasets WHERE factory_id != 'demo-detroit-31'")
cur.execute("DELETE FROM user_sessions WHERE active_factory_id != 'demo-detroit-31'")
cur.execute("DELETE FROM factories WHERE id != 'demo-detroit-31'")

# 2. Delete test companies and users created during test runs, leaving only demo
cur.execute("DELETE FROM users WHERE id != 'user_demo_lead'")
cur.execute("DELETE FROM companies WHERE id != 'comp_demo_apex'")

conn.commit()

# Verify state
factories = cur.execute("SELECT id, name, is_demo, (SELECT count(1) FROM factory_stations WHERE factory_id=factories.id) as st_count FROM factories").fetchall()
print("Remaining Factories in DB:", factories)

comps = cur.execute("SELECT id, name FROM companies").fetchall()
print("Remaining Companies:", comps)

users = cur.execute("SELECT id, email, name FROM users").fetchall()
print("Remaining Users:", users)

conn.close()
