import os
from psycopg2.extras import RealDictCursor
import psycopg2
from typing import Optional,List,Dict, Any
from datetime import datetime

DATABASE_URL = (
    "postgresql://neondb_owner:npg_AEQ8r5tXDhdg@"
    "ep-cool-bread-a8pe8h2p-pooler.eastus2.azure.neon.tech/"
    "neondb?sslmode=require&channel_binding=require"
)

SQLITE_PATH = os.environ.get("SQLITE_PATH", "local.db")


MODE = os.environ.get("BACKEND_MODE", "sqlite").lower()


# -----------------------------------------
# Connections
# -----------------------------------------

def _pg_conn():
    return psycopg2.connect(DATABASE_URL)

def _sqlite_conn():
    # row_factory lets us read by column name if we want later
    conn = sqlite3.connect(SQLITE_PATH)
    return conn

