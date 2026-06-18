"""`railway_schema_probe` — one-off discovery script for the Tripideas Railway DB.

Phase 1 of the bucket-integration workstream. Before designing the
integration we need to know what's actually IN the Railway DB that the
Tripideas website is backed by — what identifies a user, where buckets
live, whether bucket items are sanity_doc_ids or something else.

What this script does:
1. Connects to Railway Postgres via `RAILWAY_DATABASE_URL` from .env
2. Lists non-system schemas + their tables
3. Heuristically flags candidate tables (user / bucket / trip / saved / list)
4. For each candidate: prints columns + a 5-row sample (with long
   text/JSON truncated so the output stays scannable)

Run once, copy the output into `directives/railway_bucket_schema.md` with
notes on what each table means, then this script can be deleted.

Setup:
    pip install psycopg2-binary
    # Add to .env at project root:
    #   RAILWAY_DATABASE_URL=postgresql://user:pass@host:port/dbname

Run:
    python execution/audit/railway_schema_probe.py

The script is read-only — never issues anything but SELECT/SHOW.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Load .env from the project root
try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print(
        "ERROR: psycopg2 not installed. Run:\n"
        "    pip install psycopg2-binary\n"
        "(One-off dependency for this probe — NOT being added to "
        "backend/requirements.txt yet; we'll only promote it if Phase 2 picks "
        "Path B / backend-fetch.)"
    )
    sys.exit(1)


# Tables whose names match these substrings get flagged as candidates worth
# inspecting closely. Case-insensitive substring match.
CANDIDATE_KEYWORDS = [
    "user", "account", "auth", "session",
    "bucket", "saved", "favorite", "favourite", "wishlist",
    "trip", "itiner", "plan", "list",
    "place", "item", "selection",
]

# Schemas we always skip — Postgres system schemas, Railway internals.
SKIP_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast"}

SAMPLE_ROW_COUNT = 5
MAX_CELL_CHARS = 120   # truncate cell values longer than this


def main() -> None:
    db_url = os.environ.get("RAILWAY_DATABASE_URL")
    if not db_url:
        print(
            "ERROR: RAILWAY_DATABASE_URL not set in .env\n\n"
            "Get the Postgres connection string from Railway:\n"
            "  1. https://railway.app/ → the Tripideas project\n"
            "  2. Pick the Postgres service → 'Connect' tab\n"
            "  3. Copy the `DATABASE_URL` value (starts with postgresql://...)\n"
            "  4. Add to .env at project root:\n"
            f"     RAILWAY_DATABASE_URL=postgresql://...\n\n"
            f"     ({_PROJECT_ROOT / '.env'})"
        )
        sys.exit(1)

    print(f"Connecting to Railway DB...")
    print(f"  (host hidden in URL; using credentials from RAILWAY_DATABASE_URL)")
    try:
        conn = psycopg2.connect(db_url, connect_timeout=10)
        conn.set_session(readonly=True, autocommit=True)
    except Exception as e:
        print(f"\nERROR: connection failed — {type(e).__name__}: {e}")
        print(
            "\nCommon causes:\n"
            "  - Wrong DATABASE_URL (host/port/credentials)\n"
            "  - Railway DB IP-allowlist blocking this machine\n"
            "  - Network/firewall issue\n"
        )
        sys.exit(1)
    print("  → connected.\n")

    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Server identity — Postgres version + current DB name
    cur.execute("SELECT version(), current_database();")
    row = cur.fetchone()
    print(f"Server:    {row['version']}")
    print(f"Database:  {row['current_database']}\n")

    # 2. Non-system schemas
    cur.execute("""
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name NOT IN %s AND schema_name NOT LIKE 'pg_%%'
        ORDER BY schema_name;
    """, (tuple(SKIP_SCHEMAS),))
    schemas = [r["schema_name"] for r in cur.fetchall()]
    print(f"User schemas ({len(schemas)}): {schemas}\n")

    # 3. All tables across user schemas
    cur.execute("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema = ANY(%s) AND table_type = 'BASE TABLE'
        ORDER BY table_schema, table_name;
    """, (schemas,))
    all_tables = [(r["table_schema"], r["table_name"]) for r in cur.fetchall()]

    candidates: list[tuple[str, str]] = []
    others: list[tuple[str, str]] = []
    for schema, name in all_tables:
        lower = name.lower()
        if any(kw in lower for kw in CANDIDATE_KEYWORDS):
            candidates.append((schema, name))
        else:
            others.append((schema, name))

    print(f"Total tables: {len(all_tables)}")
    print(f"  Flagged candidates ({len(candidates)}):")
    for s, n in candidates:
        print(f"    {s}.{n}")
    print(f"  Other tables ({len(others)}):")
    for s, n in others:
        print(f"    {s}.{n}")
    print()

    # 4. For each candidate: columns + row count + sample
    for schema, table in candidates:
        _probe_table(cur, schema, table)

    # 5. Quick row-count summary on non-candidates so we can spot anything
    # surprisingly large that the heuristic missed
    print("=" * 72)
    print("Row counts for non-candidate tables (in case the heuristic missed one):")
    print("=" * 72)
    for schema, table in others:
        try:
            cur.execute(f'SELECT count(*) AS n FROM "{schema}"."{table}";')
            n = cur.fetchone()["n"]
            print(f"  {schema}.{table}: {n:,} rows")
        except Exception as e:
            print(f"  {schema}.{table}: count failed — {type(e).__name__}: {e}")

    conn.close()
    print("\nDone. Copy the relevant bits into directives/railway_bucket_schema.md")
    print("with notes on what each table means and which fields hold the bucket.")


def _probe_table(cur, schema: str, table: str) -> None:
    fq = f'"{schema}"."{table}"'
    print("=" * 72)
    print(f"Table: {schema}.{table}")
    print("=" * 72)

    # Columns
    cur.execute("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position;
    """, (schema, table))
    cols = cur.fetchall()
    print(f"  Columns ({len(cols)}):")
    for c in cols:
        default = f"  default={c['column_default']}" if c["column_default"] else ""
        nullable = "NULL" if c["is_nullable"] == "YES" else "NOT NULL"
        print(f"    {c['column_name']:30s}  {c['data_type']:20s}  {nullable}{default}")

    # Row count
    try:
        cur.execute(f"SELECT count(*) AS n FROM {fq};")
        n = cur.fetchone()["n"]
        print(f"  Row count: {n:,}")
    except Exception as e:
        print(f"  Row count failed: {type(e).__name__}: {e}")
        print()
        return

    if n == 0:
        print("  (empty table — no sample to show)\n")
        return

    # Sample
    try:
        cur.execute(f"SELECT * FROM {fq} LIMIT {SAMPLE_ROW_COUNT};")
        rows = cur.fetchall()
        print(f"  Sample ({len(rows)} rows):")
        for i, r in enumerate(rows):
            print(f"    [{i}]")
            for k, v in r.items():
                print(f"      {k:30s}  {_fmt_cell(v)}")
    except Exception as e:
        print(f"  Sample failed: {type(e).__name__}: {e}")
    print()


def _fmt_cell(v: Any) -> str:
    if v is None:
        return "<null>"
    s = repr(v)
    if len(s) > MAX_CELL_CHARS:
        return s[:MAX_CELL_CHARS] + f"... <truncated, total {len(s)} chars>"
    return s


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    main()
