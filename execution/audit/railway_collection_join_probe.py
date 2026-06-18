"""`railway_collection_join_probe` — confirm the bucket join shape.

After railway_schema_probe.py revealed the table structure, this script
joins FavCollection -> FavCollectionItem -> Favourite -> User and dumps
a couple of real collections end-to-end so we can be sure we know what
"a user's bucket" looks like when we read it from chat-side.

READ-ONLY (SELECT only).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

import psycopg2
from psycopg2.extras import RealDictCursor


def main() -> None:
    url = os.environ.get("RAILWAY_DATABASE_URL")
    if not url:
        print("RAILWAY_DATABASE_URL missing — run railway_api_discover.py first")
        sys.exit(1)
    conn = psycopg2.connect(url, connect_timeout=10)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Show FavCollection schema (probe missed it — wasn't in candidates list)
    cur.execute("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'FavCollection'
        ORDER BY ordinal_position;
    """)
    print("FavCollection columns:")
    for r in cur.fetchall():
        print(f"  {r['column_name']:25s}  {r['data_type']}  {r['is_nullable']}")
    print()

    # All collections with owner + item count
    cur.execute('''
        SELECT
            c.id              AS collection_id,
            c.name            AS collection_name,
            u.email           AS owner_email,
            u.id              AS owner_user_id,
            c."createdAt"     AS created_at,
            COUNT(i.id)       AS item_count
        FROM "FavCollection" c
        LEFT JOIN "User" u ON u.id = c."userId"
        LEFT JOIN "FavCollectionItem" i ON i."collectionId" = c.id
        GROUP BY c.id, c.name, u.email, u.id, c."createdAt"
        ORDER BY c."createdAt" DESC;
    ''')
    collections = cur.fetchall()
    print(f"All FavCollections ({len(collections)}):")
    for c in collections:
        print(
            f"  {c['collection_id']}  '{c['collection_name']}'  "
            f"by {c['owner_email']} — {c['item_count']} items"
        )
    print()

    # Pick the biggest collection and join out the full place list
    if not collections:
        return
    biggest = max(collections, key=lambda r: r["item_count"])
    print(f"Drilling into biggest collection: '{biggest['collection_name']}' "
          f"({biggest['item_count']} items, owner {biggest['owner_email']})")
    cur.execute('''
        SELECT
            i.id              AS collection_item_id,
            f.id              AS favourite_id,
            f."placeId"       AS sanity_doc_id,
            f."userId"        AS favourite_owner,
            f."createdAt"     AS favourited_at
        FROM "FavCollectionItem" i
        JOIN "Favourite" f ON f.id = i."favouriteId"
        WHERE i."collectionId" = %s
        ORDER BY f."createdAt" ASC;
    ''', (biggest["collection_id"],))
    items = cur.fetchall()
    print(f"  → {len(items)} items:")
    for it in items:
        print(f"    placeId={it['sanity_doc_id']}  fav={it['favourite_id']}  "
              f"item={it['collection_item_id']}")

    # Also: how many of those placeIds are real Sanity docs we can resolve?
    sanity_ids = [it["sanity_doc_id"] for it in items]
    print(f"\nFirst 5 sanity_doc_ids: {sanity_ids[:5]}")
    print("(Use these to verify against Sanity in a follow-up step.)")

    conn.close()


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    main()
