"""
TwinPilot Multi-Tenant Database & Platform Verification Test
"""
import urllib.request
import json
import os
import sqlite3

print("=== 1. CHECK SQLITE DATABASE TABLES ===")
conn = sqlite3.connect("twinpilot.db")
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("Database Tables:", tables)
for required in ["companies", "users", "factories", "factory_stations", "factory_dependencies", "user_sessions"]:
    assert required in tables, f"Missing table: {required}"

print("\n=== 2. VERIFY DEFAULT DEMO FACTORY PRESERVATION ===")
cur = conn.cursor()
cur.execute("SELECT id, name, is_demo, (SELECT count(1) FROM factory_stations WHERE factory_id=factories.id) as st_count FROM factories WHERE is_demo = 1")
demo_fact = cur.fetchone()
print("Demo Factory in DB:", demo_fact)
assert demo_fact[0] == "demo-detroit-31" and demo_fact[3] == 31
conn.close()

print("\n=== 3. TEST AUTHENTICATION & REGISTRATION API ===")
reg_payload = json.dumps({
    "company_name": "Audi Brussels AG",
    "industry": "Premium EV Manufacturing",
    "user_name": "Marc Van Damme",
    "email": f"marc.vandamme.{os.getpid()}@audi.be",
    "password": "AudiPassword2026!",
    "factory_name": "Brussels e-tron Line 1",
    "location": "Brussels, Belgium"
}).encode("utf-8")

req = urllib.request.Request("http://localhost:5000/api/auth/register", data=reg_payload, headers={"Content-Type": "application/json"})
reg_res = json.loads(urllib.request.urlopen(req).read())
print("Registration Response:", reg_res["success"], "| User:", reg_res["user"]["name"])
token = reg_res["session_token"]

print("\n=== 4. TEST AUTH SESSION LOOKUP ===")
req_me = urllib.request.Request("http://localhost:5000/api/auth/me", headers={"X-Session-Token": token})
me = json.loads(urllib.request.urlopen(req_me).read())
print("Authenticated User:", me["user_name"], "| Company:", me["company_name"])
assert me["is_authenticated"] is True

print("\n=== 5. TEST FACTORY LISTING ===")
req_f = urllib.request.Request("http://localhost:5000/api/factories", headers={"X-Session-Token": token})
factories = json.loads(urllib.request.urlopen(req_f).read())["factories"]
print(f"User has {len(factories)} accessible factories:")
for f in factories:
    print(f" - {f['name']} (Stations: {f.get('station_count', 0)}, Demo: {bool(f['is_demo'])})")

print("\n=== 6. VERIFY DEMO FACTORY SCENARIOS REMAIN 100% FUNCTIONAL ===")
demo_s24 = json.loads(urllib.request.urlopen("http://localhost:5000/api/scenario?run_id=RUN-024&minute=143&station=S03&event_id=RUN024-EVT01&step_id=3").read())
print("RUN-024 Stations Count:", len(demo_s24["stations"]), "| Rec:", demo_s24["recommendation"]["option_key"])
assert len(demo_s24["stations"]) == 31 and demo_s24["recommendation"]["option_key"] == "Option C"

demo_s25 = json.loads(urllib.request.urlopen("http://localhost:5000/api/scenario?run_id=RUN-025&minute=93&station=S16&event_id=RUN025-EVT02&step_id=3").read())
print("RUN-025 Stations Count:", len(demo_s25["stations"]), "| Rec:", demo_s25["recommendation"]["option_key"])
assert len(demo_s25["stations"]) == 31 and demo_s25["recommendation"]["option_key"] == "Option A"

print("\n>>> ALL MULTI-TENANT DATABASE & FACTORY TESTS PASSED WITH 100% INTEGRITY! <<<")
