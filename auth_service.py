"""
TwinPilot Authentication & Multi-Tenant Access Service
=====================================================
Handles:
- Secure password hashing and verification
- Company & Factory registration
- User login, session tokens, and RBAC
- Multi-factory switching per user session
"""

import os
import uuid
import hashlib
import secrets
from datetime import datetime, timedelta
from database import get_db_connection

SALT = b"twinpilot_security_salt_2026_enterprise"


def hash_password(password: str) -> str:
    """Derives a secure hex hash from password and salt."""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), SALT, 100000).hex()


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time password hash comparison."""
    test_hash = hash_password(password)
    return secrets.compare_digest(test_hash, hashed)


def register_company_and_user(company_name: str, industry: str, user_name: str, email: str, password: str, factory_name: str = "", location: str = "Global"):
    """
    Registers a new company, administrative user, and initial factory workspace.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    # Check if user already exists
    cur.execute("SELECT id FROM users WHERE lower(email) = lower(?)", (email,))
    if cur.fetchone():
        conn.close()
        return {"success": False, "error": f"An account with email '{email}' already exists."}

    now_str = datetime.utcnow().isoformat() + "Z"
    company_id = f"comp_{uuid.uuid4().hex[:12]}"
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    factory_id = f"fact_{uuid.uuid4().hex[:12]}"

    slug = factory_name.lower().replace(" ", "-").replace("/", "-") if factory_name else f"plant-{uuid.uuid4().hex[:6]}"

    try:
        # 1. Create Company
        cur.execute("""
        INSERT INTO companies (id, name, industry, tier, created_at)
        VALUES (?, ?, ?, ?, ?)
        """, (company_id, company_name.strip(), industry.strip() or "Manufacturing", "Enterprise", now_str))

        # 2. Create User
        cur.execute("""
        INSERT INTO users (id, company_id, name, email, password_hash, role, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, company_id, user_name.strip(), email.strip().lower(), hash_password(password), "admin", now_str))

        # 3. Create Initial Factory Workspace
        fname = factory_name.strip() if factory_name else f"{company_name.strip()} Primary Facility"
        cur.execute("""
        INSERT INTO factories (id, company_id, name, slug, location, is_demo, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (factory_id, company_id, fname, slug, location.strip() or "Global", 0, "pending_onboarding", now_str))

        # 4. Create Session
        token = secrets.token_hex(24)
        expires_at = (datetime.utcnow() + timedelta(days=30)).isoformat() + "Z"
        cur.execute("""
        INSERT INTO user_sessions (session_token, user_id, active_factory_id, expires_at)
        VALUES (?, ?, ?, ?)
        """, (token, user_id, factory_id, expires_at))

        conn.commit()

        # Mirror directly to MongoDB Atlas
        try:
            import mongodb_client
            mdb = mongodb_client.get_mongodb_database()
            mdb.companies.update_one({"_id": company_id}, {"$set": {
                "name": company_name.strip(),
                "industry": industry.strip() or "Manufacturing",
                "tier": "Enterprise",
                "created_at": now_str
            }}, upsert=True)
            mdb.users.update_one({"_id": user_id}, {"$set": {
                "company_id": company_id,
                "name": user_name.strip(),
                "email": email.strip().lower(),
                "role": "admin",
                "created_at": now_str
            }}, upsert=True)
            mdb.factories.update_one({"_id": factory_id}, {"$set": {
                "company_id": company_id,
                "name": fname,
                "slug": slug,
                "location": location.strip() or "Global",
                "is_demo": False,
                "status": "pending_onboarding",
                "created_at": now_str
            }}, upsert=True)
        except Exception as mex:
            print("[MongoDB Atlas Registration Sync Warning]:", mex)

        return {
            "success": True,
            "session_token": token,
            "user": {
                "id": user_id,
                "name": user_name.strip(),
                "email": email.strip().lower(),
                "role": "admin",
                "company_id": company_id,
                "company_name": company_name.strip(),
                "active_factory": {
                    "id": factory_id,
                    "name": fname,
                    "is_demo": False,
                    "status": "pending_onboarding"
                }
            }
        }
    except Exception as e:
        conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def authenticate_user(email: str, password: str):
    """
    Authenticates user credentials and returns an active session token.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    SELECT u.id, u.company_id, u.name, u.email, u.password_hash, u.role, c.name as company_name
    FROM users u
    JOIN companies c ON u.company_id = c.id
    WHERE lower(u.email) = lower(?)
    """, (email.strip(),))
    user_row = cur.fetchone()

    if not user_row:
        # Fallback to check MongoDB Atlas directly
        try:
            import mongodb_client
            mdb = mongodb_client.get_mongodb_database()
            mongo_user = mdb.users.find_one({"email": email.strip().lower()})
            if mongo_user and verify_password(password, mongo_user.get("password_hash", "")):
                company_doc = mdb.companies.find_one({"_id": mongo_user["company_id"]})
                comp_name = company_doc.get("name", "Enterprise OEM") if company_doc else "Enterprise OEM"
                
                # Restore user and company into SQLite
                cur.execute("INSERT OR REPLACE INTO companies (id, name, industry, tier, created_at) VALUES (?, ?, ?, ?, ?)",
                            (mongo_user["company_id"], comp_name, company_doc.get("industry", "Manufacturing") if company_doc else "Manufacturing", "Enterprise", mongo_user.get("created_at", "")))
                cur.execute("INSERT OR REPLACE INTO users (id, company_id, name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (mongo_user["_id"], mongo_user["company_id"], mongo_user["name"], mongo_user["email"], mongo_user["password_hash"], mongo_user.get("role", "admin"), mongo_user.get("created_at", "")))
                
                fact_doc = mdb.factories.find_one({"company_id": mongo_user["company_id"]})
                if fact_doc:
                    cur.execute("INSERT OR REPLACE INTO factories (id, company_id, name, slug, location, is_demo, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (fact_doc["_id"], mongo_user["company_id"], fact_doc["name"], fact_doc.get("slug", ""), fact_doc.get("location", "Global"), 0, fact_doc.get("status", "active"), fact_doc.get("created_at", "")))
                
                conn.commit()

                cur.execute("""
                SELECT u.id, u.company_id, u.name, u.email, u.password_hash, u.role, c.name as company_name
                FROM users u
                JOIN companies c ON u.company_id = c.id
                WHERE lower(u.email) = lower(?)
                """, (email.strip(),))
                user_row = cur.fetchone()
        except Exception as mex:
            print("[MongoDB Auth Check Warning]:", mex)

    if not user_row:
        conn.close()
        return {"success": False, "error": "Invalid email or password."}

    if not verify_password(password, user_row["password_hash"]):
        conn.close()
        return {"success": False, "error": "Invalid email or password."}

    # Find the user's active or primary factory
    cur.execute("""
    SELECT id, name, is_demo, status
    FROM factories
    WHERE company_id = ?
    ORDER BY is_demo ASC, created_at DESC
    LIMIT 1
    """, (user_row["company_id"],))
    fact_row = cur.fetchone()
    active_factory_id = fact_row["id"] if fact_row else "demo-detroit-31"

    token = secrets.token_hex(24)
    expires_at = (datetime.utcnow() + timedelta(days=30)).isoformat() + "Z"
    cur.execute("""
    INSERT INTO user_sessions (session_token, user_id, active_factory_id, expires_at)
    VALUES (?, ?, ?, ?)
    """, (token, user_row["id"], active_factory_id, expires_at))

    conn.commit()
    conn.close()

    # Mirror session to MongoDB Atlas
    try:
        import mongodb_client
        mdb = mongodb_client.get_mongodb_database()
        mdb.user_sessions.update_one({"_id": token}, {"$set": {
            "user_id": user_row["id"],
            "active_factory_id": active_factory_id,
            "expires_at": expires_at
        }}, upsert=True)
    except Exception as mex:
        pass

    return {
        "success": True,
        "session_token": token,
        "user": {
            "id": user_row["id"],
            "name": user_row["name"],
            "email": user_row["email"],
            "role": user_row["role"],
            "company_id": user_row["company_id"],
            "company_name": user_row["company_name"],
            "active_factory": {
                "id": fact_row["id"] if fact_row else "demo-detroit-31",
                "name": fact_row["name"] if fact_row else "Detroit Assembly Plant #4 (Demo)",
                "is_demo": bool(fact_row["is_demo"]) if fact_row else True,
                "status": fact_row["status"] if fact_row else "active"
            }
        }
    }


def get_session_user(session_token: str):
    """
    Validates a session token and retrieves current user, company, and factory.
    If session_token is None or invalid, falls back gracefully to default Demo Operator.
    """
    if not session_token:
        return get_default_demo_user()

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    SELECT s.session_token, s.active_factory_id, u.id as user_id, u.name as user_name, u.email, u.role,
           c.id as company_id, c.name as company_name,
           f.id as factory_id, f.name as factory_name, f.is_demo, f.status as factory_status
    FROM user_sessions s
    JOIN users u ON s.user_id = u.id
    JOIN companies c ON u.company_id = c.id
    LEFT JOIN factories f ON s.active_factory_id = f.id
    WHERE s.session_token = ?
    """, (session_token,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return get_default_demo_user()

    return {
        "is_authenticated": True,
        "user_id": row["user_id"],
        "user_name": row["user_name"],
        "email": row["email"],
        "role": row["role"],
        "company_id": row["company_id"],
        "company_name": row["company_name"],
        "active_factory": {
            "id": row["factory_id"] or "demo-detroit-31",
            "name": row["factory_name"] or "Detroit Assembly Plant #4 (Demo)",
            "is_demo": bool(row["is_demo"]) if row["is_demo"] is not None else True,
            "status": row["factory_status"] or "active"
        }
    }


def get_default_demo_user():
    """Returns the default pre-loaded Demo Operator representation."""
    return {
        "is_authenticated": False,
        "user_id": "user_demo_lead",
        "user_name": "Demo Plant Operator",
        "email": "demo@twinpilot.ai",
        "role": "admin",
        "company_id": "comp_demo_apex",
        "company_name": "Apex Mobility Global (Demo)",
        "active_factory": {
            "id": "demo-detroit-31",
            "name": "Detroit Assembly Plant #4 (31 Stations — Pre-loaded Demo)",
            "is_demo": True,
            "status": "active"
        }
    }


def list_company_factories(company_id: str):
    """
    Lists all factories belonging to a company, plus the universal demo factory.
    Enforces strict multi-tenant isolation: demo accounts only see is_demo=1 plants.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    if company_id == "comp_demo_apex":
        cur.execute("""
        SELECT id, name, slug, location, is_demo, status, created_at,
               (SELECT COUNT(*) FROM factory_stations WHERE factory_id = factories.id) as station_count
        FROM factories
        WHERE is_demo = 1
        ORDER BY is_demo DESC, created_at DESC
        """)
    else:
        cur.execute("""
        SELECT id, name, slug, location, is_demo, status, created_at,
               (SELECT COUNT(*) FROM factory_stations WHERE factory_id = factories.id) as station_count
        FROM factories
        WHERE (company_id = ? AND is_demo = 0) OR is_demo = 1
        ORDER BY is_demo DESC, created_at DESC
        """, (company_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def switch_active_factory(session_token: str, factory_id: str):
    """Switches the active factory for an ongoing user session."""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT id, name, is_demo, status FROM factories WHERE id = ?", (factory_id,))
    fact = cur.fetchone()
    if not fact:
        conn.close()
        return {"success": False, "error": "Factory not found."}

    if session_token:
        cur.execute("UPDATE user_sessions SET active_factory_id = ? WHERE session_token = ?", (factory_id, session_token))
        conn.commit()

    conn.close()
    return {
        "success": True,
        "active_factory": {
            "id": fact["id"],
            "name": fact["name"],
            "is_demo": bool(fact["is_demo"]),
            "status": fact["status"]
        }
    }


def create_factory_for_company(company_id: str, factory_name: str, location: str = "Global"):
    """Creates a new factory workspace within an existing company account."""
    conn = get_db_connection()
    cur = conn.cursor()

    factory_id = f"fact_{uuid.uuid4().hex[:12]}"
    slug = factory_name.lower().replace(" ", "-").replace("/", "-")
    now_str = datetime.utcnow().isoformat() + "Z"

    cur.execute("""
    INSERT INTO factories (id, company_id, name, slug, location, is_demo, status, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (factory_id, company_id, factory_name.strip(), slug, location.strip(), 0, "pending_onboarding", now_str))

    conn.commit()
    conn.close()

    # Mirror to MongoDB Atlas
    try:
        import mongodb_client
        mdb = mongodb_client.get_mongodb_database()
        mdb.factories.update_one({"_id": factory_id}, {"$set": {
            "company_id": company_id,
            "name": factory_name.strip(),
            "slug": slug,
            "location": location.strip(),
            "is_demo": False,
            "status": "pending_onboarding",
            "created_at": now_str
        }}, upsert=True)
    except Exception as mex:
        print("[MongoDB Atlas Factory Sync Warning]:", mex)

    return {
        "success": True,
        "factory": {
            "id": factory_id,
            "name": factory_name.strip(),
            "slug": slug,
            "location": location.strip(),
            "is_demo": False,
            "status": "pending_onboarding"
        }
    }
