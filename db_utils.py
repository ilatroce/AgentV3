from __future__ import annotations
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import traceback
import psycopg2
from psycopg2.extras import Json
from dotenv import load_dotenv

# Import opzionale di numpy
try:
    import numpy as np
except Exception:
    np = None

load_dotenv()

@dataclass
class DBConfig:
    dsn: str

def get_db_config() -> DBConfig:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        # Fallback default or raise
        raise RuntimeError("DATABASE_URL not set.")
    return DBConfig(dsn=dsn)

@contextmanager
def get_connection():
    config = get_db_config()
    conn = psycopg2.connect(config.dsn)
    try:
        yield conn
    finally:
        conn.close()

# =====================
# SCHEMA & INIT
# =====================
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS account_snapshots (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    balance_usd NUMERIC(20, 8) NOT NULL,
    raw_payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS open_positions (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT NOT NULL REFERENCES account_snapshots(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    size NUMERIC(30, 10) NOT NULL,
    entry_price NUMERIC(30, 10),
    mark_price NUMERIC(30, 10),
    pnl_usd NUMERIC(30, 10),
    leverage TEXT,
    raw_payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_contexts (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    system_prompt TEXT
);

CREATE TABLE IF NOT EXISTS indicators_contexts (
    id BIGSERIAL PRIMARY KEY,
    context_id BIGINT NOT NULL REFERENCES ai_contexts(id) ON DELETE CASCADE,
    ticker TEXT,
    ts TIMESTAMPTZ,
    price NUMERIC(20, 8),
    ema20 NUMERIC(20, 8),
    macd NUMERIC(20, 8),
    rsi_7 NUMERIC(20, 8),
    volume_bid NUMERIC(20, 8),
    volume_ask NUMERIC(20, 8),
    open_interest_latest NUMERIC(30, 10),
    funding_rate NUMERIC(20, 8),
    raw JSONB
);

CREATE TABLE IF NOT EXISTS news_contexts (
    id BIGSERIAL PRIMARY KEY,
    context_id BIGINT NOT NULL REFERENCES ai_contexts(id) ON DELETE CASCADE,
    news_text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sentiment_contexts (
    id BIGSERIAL PRIMARY KEY,
    context_id BIGINT NOT NULL REFERENCES ai_contexts(id) ON DELETE CASCADE,
    value INTEGER,
    classification TEXT,
    sentiment_timestamp BIGINT,
    raw JSONB
);

CREATE TABLE IF NOT EXISTS forecasts_contexts (
    id BIGSERIAL PRIMARY KEY,
    context_id BIGINT NOT NULL REFERENCES ai_contexts(id) ON DELETE CASCADE,
    ticker TEXT,
    timeframe TEXT,
    prediction NUMERIC(30, 10),
    forecast_timestamp BIGINT,
    raw JSONB
);

CREATE TABLE IF NOT EXISTS bot_operations (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    context_id BIGINT REFERENCES ai_contexts(id) ON DELETE CASCADE,
    operation TEXT NOT NULL,
    symbol TEXT,
    direction TEXT,
    target_portion_of_balance NUMERIC(10, 4),
    leverage NUMERIC(10, 4),
    raw_payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS errors (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error_type TEXT NOT NULL,
    error_message TEXT,
    traceback TEXT,
    context JSONB,
    source TEXT
);
"""

def init_db() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        conn.commit()

# =====================
# LOGGING FUNCTIONS
# =====================

def _to_plain_number(value: Any) -> Optional[float]:
    if value is None: return None
    if np is not None:
        try:
            if isinstance(value, np.generic): return float(value)
        except: pass
    try: return float(value)
    except: return None

def _normalize_for_json(value: Any) -> Any:
    if isinstance(value, dict): return {k: _normalize_for_json(v) for k, v in value.items()}
    if isinstance(value, list): return [_normalize_for_json(v) for v in value]
    num = _to_plain_number(value)
    if num is not None: return num
    return value

def log_error(exc: BaseException, *, context: Optional[Dict] = None, source: Optional[str] = None):
    error_type = type(exc).__name__
    error_message = str(exc)
    tb_str = traceback.format_exc()
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO errors (error_type, error_message, traceback, context, source) VALUES (%s, %s, %s, %s, %s)",
                    (error_type, error_message, tb_str, Json(context) if context else None, source)
                )
            conn.commit()
    except Exception as e:
        print(f"CRITICAL: Failed to log error to DB: {e}")

def log_bot_operation(operation_payload: Dict[str, Any], *, system_prompt=None, indicators=None, news_text=None, sentiment=None, forecasts=None) -> int:
    operation = operation_payload.get("operation")
    symbol = operation_payload.get("symbol")
    direction = operation_payload.get("direction")
    target_p = operation_payload.get("target_portion_of_balance")
    lev = operation_payload.get("leverage")

    with get_connection() as conn:
        with conn.cursor() as cur:
            # 1. Context
            cur.execute("INSERT INTO ai_contexts (system_prompt) VALUES (%s) RETURNING id", (system_prompt,))
            context_id = cur.fetchone()[0]

            # 2. Log Operation
            cur.execute(
                """
                INSERT INTO bot_operations 
                (context_id, operation, symbol, direction, target_portion_of_balance, leverage, raw_payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (context_id, operation, symbol, direction, target_p, lev, Json(operation_payload))
            )
            op_id = cur.fetchone()[0]
        conn.commit()
    return op_id

# =====================
# DATA FETCHING (DASHBOARD)
# =====================

def get_recent_logs(limit: int = 100) -> List[Dict[str, Any]]:
    """Fetches flattened logs for the dashboard."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    created_at, 
                    operation, 
                    symbol, 
                    direction, 
                    raw_payload->>'reason' as reason
                FROM bot_operations
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]

def get_grid_alerts(limit: int = 50) -> List[Dict[str, Any]]:
    """Fetches Grid Scanner alerts."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    created_at,
                    symbol,
                    raw_payload->>'reason' as reason
                FROM bot_operations 
                WHERE operation = 'GRID_ALERT' 
                ORDER BY created_at DESC 
                LIMIT %s
            """, (limit,))
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
