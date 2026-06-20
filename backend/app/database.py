import os
import logging
import threading
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection pool — keeps warm connections alive so Neon doesn't cold-start
# on every request.  min=1 keeps one connection alive at all times.
# ---------------------------------------------------------------------------
_pool: psycopg2.pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()

# Timeouts (seconds)
_CONNECT_TIMEOUT = 15   # max time to establish a connection
_POOL_MIN = 1
_POOL_MAX = 10


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set. Add it to .env")
    return database_url


def _build_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """Create and return a new connection pool."""
    url = get_database_url()
    return psycopg2.pool.ThreadedConnectionPool(
        _POOL_MIN,
        _POOL_MAX,
        url,
        cursor_factory=RealDictCursor,
        connect_timeout=_CONNECT_TIMEOUT,
    )


def get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """Return the global pool, initialising it lazily on first call."""
    global _pool
    if _pool is None or _pool.closed:
        with _pool_lock:
            if _pool is None or _pool.closed:
                logger.info("Initialising database connection pool…")
                _pool = _build_pool()
                logger.info("Connection pool ready.")
    return _pool


@contextmanager
def get_connection():
    """
    Yield a psycopg2 connection from the pool.
    The connection is returned to the pool on exit.
    On any pool error (e.g. Neon sleep), fall back to a direct connection.
    """
    pool = get_pool()
    conn = None
    from_pool = False
    try:
        conn = pool.getconn()
        from_pool = True
        # Reset autocommit off — callers use explicit conn.commit()
        conn.autocommit = False
        yield conn
    except psycopg2.pool.PoolError:
        # Pool exhausted or closed — open a direct connection as fallback
        logger.warning("Pool unavailable, falling back to direct connection.")
        conn = psycopg2.connect(
            get_database_url(),
            cursor_factory=RealDictCursor,
            connect_timeout=_CONNECT_TIMEOUT,
        )
        from_pool = False
        yield conn
    finally:
        if conn is not None:
            if from_pool:
                try:
                    pool.putconn(conn)
                except Exception:
                    pass
            else:
                try:
                    conn.close()
                except Exception:
                    pass


def warmup() -> None:
    """
    Send a trivial query to keep the Neon instance awake.
    Call this once at startup so the first real request is fast.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        logger.info("Database warmup ping successful.")
    except Exception as exc:
        logger.warning("Database warmup ping failed (non-fatal): %s", exc)


def init_db() -> None:
    schema_path = Path(__file__).resolve().parent / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(schema_sql)
        conn.commit()


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
