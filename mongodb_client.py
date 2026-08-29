"""
TwinPilot MongoDB Atlas Connection Manager
==========================================
Connects the Flask backend to MongoDB Atlas using the MONGODB_URI environment variable from .env.
- Credentials remain strictly on the backend (never exposed to browser or frontend).
- Provides database instance and connection health checks.
- Zero modifications to existing dataset or logic.
"""

import os
import time
import logging
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from pymongo import MongoClient
# pyrefly: ignore [missing-import]
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

logger = logging.getLogger("twinpilot.mongodb")

# Load environment variables from .env file
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(ENV_PATH)

MONGODB_URI = os.getenv("MONGODB_URI")
DEFAULT_DB_NAME = os.getenv("MONGODB_DB_NAME", "twinpilot")

_client = None
_db = None


def get_mongo_client(timeout_ms: int = 6000):
    """
    Returns a singleton MongoClient connected to MongoDB Atlas.
    """
    global _client
    if _client is None:
        if not MONGODB_URI:
            raise ValueError("MONGODB_URI environment variable not found in .env file.")
        _client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=timeout_ms,
            connectTimeoutMS=timeout_ms
        )
    return _client


def get_mongodb_database(db_name: str = DEFAULT_DB_NAME):
    """
    Returns the twinpilot database handle from MongoDB Atlas.
    """
    global _db
    if _db is None:
        client = get_mongo_client()
        _db = client[db_name]
    return _db


def test_mongodb_connection():
    """
    Performs a ping command against MongoDB Atlas and returns detailed connection diagnostics.
    Does NOT modify any collections or datasets.
    """
    start_time = time.time()
    try:
        client = get_mongo_client(timeout_ms=5000)
        # The ping command is cheap and does not require auth on admin for Atlas cluster ping
        ping_result = client.admin.command("ping")
        elapsed_ms = round((time.time() - start_time) * 1000, 2)

        # Get server build information
        build_info = client.admin.command("buildInfo")
        mongo_version = build_info.get("version", "unknown")

        # Check twinpilot db connection
        db = client[DEFAULT_DB_NAME]
        existing_collections = db.list_collection_names()

        return {
            "status": "connected",
            "success": True,
            "database": DEFAULT_DB_NAME,
            "latency_ms": elapsed_ms,
            "server_version": mongo_version,
            "cluster_host": client.nodes,
            "collections_count": len(existing_collections),
            "collections": existing_collections,
            "message": "Successfully connected to MongoDB Atlas (twinpilot database)."
        }
    except ServerSelectionTimeoutError as e:
        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "status": "timeout",
            "success": False,
            "latency_ms": elapsed_ms,
            "error": "Connection timed out connecting to MongoDB Atlas.",
            "details": str(e),
            "tip": "Ensure your current IP address is added to the MongoDB Atlas Network Access whitelist (IP Access List)."
        }
    except ConnectionFailure as e:
        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "status": "failed",
            "success": False,
            "latency_ms": elapsed_ms,
            "error": "Failed to connect to MongoDB Atlas.",
            "details": str(e)
        }
    except Exception as e:
        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "status": "error",
            "success": False,
            "latency_ms": elapsed_ms,
            "error": str(e)
        }


if __name__ == "__main__":
    print("Testing MongoDB Atlas connection...")
    result = test_mongodb_connection()
    import json
    print(json.dumps(result, indent=2, default=str))
