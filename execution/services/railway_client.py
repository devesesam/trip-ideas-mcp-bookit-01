"""Thin wrapper around the Tripideas Railway Postgres DB.

READ-ONLY. The Railway DB is Douglas's client production-grade store
(staging in this v1, production later). Every connection opened by this
client sets `session_readonly=True` so any accidental INSERT/UPDATE/DELETE
raises `psycopg2.errors.ReadOnlySqlTransaction` instead of mutating.

No mutation helpers are defined in this module. Don't add any without
explicit user approval — see `directives/railway_bucket_schema.md`.

Usage:
    from services.railway_client import RailwayClient

    client = RailwayClient()
    rows = client.query(
        'SELECT id, name FROM "FavCollection" WHERE id = %s',
        (collection_id,),
    )

Configured via `RAILWAY_DATABASE_URL` in .env (or Modal secret in prod).
Schema details: `directives/railway_bucket_schema.md`.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Sequence

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class RailwayConfigError(RuntimeError):
    pass


class RailwayQueryError(RuntimeError):
    def __init__(self, sql: str, params: Any, cause: Exception):
        super().__init__(f"Railway query failed: {type(cause).__name__}: {cause}")
        self.sql = sql
        self.params = params
        self.cause = cause


class RailwayClient:
    """Thread-safe lazy-connecting read-only Postgres client.

    One connection is held for the life of the process (Modal containers
    reuse this between requests). On a transient connection error the
    connection is dropped and re-opened on the next call.
    """

    _conn = None
    _lock = threading.Lock()

    def __init__(
        self,
        database_url: str | None = None,
        connect_timeout_s: int = 30,
    ) -> None:
        self.database_url = database_url or os.environ.get("RAILWAY_DATABASE_URL")
        if not self.database_url:
            raise RailwayConfigError(
                "RAILWAY_DATABASE_URL not set. Add to .env locally OR attach "
                "the `railway-secret` Modal secret in production. See "
                "directives/railway_bucket_schema.md."
            )
        self.connect_timeout_s = connect_timeout_s

    def _connect(self):
        conn = psycopg2.connect(
            self.database_url,
            connect_timeout=self.connect_timeout_s,
        )
        # READ-ONLY enforcement — accidental writes will raise rather than mutate.
        conn.set_session(readonly=True, autocommit=True)
        return conn

    def _get_conn(self):
        with self._lock:
            if RailwayClient._conn is None or RailwayClient._conn.closed:
                RailwayClient._conn = self._connect()
            return RailwayClient._conn

    def query(
        self,
        sql: str,
        params: Sequence[Any] | dict | None = None,
    ) -> list[dict]:
        """Run a SELECT and return list of dict-rows. Read-only enforced."""
        try:
            conn = self._get_conn()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(sql, params)
            rows = cur.fetchall()
            cur.close()
            return [dict(r) for r in rows]
        except (psycopg2.InterfaceError, psycopg2.OperationalError) as e:
            # Connection went stale — drop and let the next call reconnect
            with self._lock:
                try:
                    if RailwayClient._conn:
                        RailwayClient._conn.close()
                except Exception:
                    pass
                RailwayClient._conn = None
            raise RailwayQueryError(sql, params, e)
        except Exception as e:  # noqa: BLE001
            raise RailwayQueryError(sql, params, e)


__all__ = ["RailwayClient", "RailwayConfigError", "RailwayQueryError"]
