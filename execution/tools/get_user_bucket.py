"""`get_user_bucket` — resolve a Tripideas FavCollection to a ready-to-use bucket.

Stitches together the two data sources behind a user's bucket:

  Railway Postgres                    Sanity CMS
  ----------------                    ----------
  FavCollection                       page._id (== placeId)
       |                                  |
  FavCollectionItem ──────────────▶  title, slug, coordinates,
       |                              subRegion->name
  Favourite (.placeId)
       |
  CollectionItemComment (optional)

A single call returns everything the chat embed needs to render the
bucket panel, draw map pins, and seed `build_trip_itinerary`'s
`include_doc_ids`.

READ-ONLY against Railway (enforced by RailwayClient). Sanity also queried
read-only.

CLI usage:
    python execution/tools/get_user_bucket.py fc_01kb1b26ksexwveksv8se2m9g2

Schema reference: `directives/railway_bucket_schema.md`.
"""

from __future__ import annotations

import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from sanity_client import SanityClient  # noqa: E402
from services.railway_client import RailwayClient  # noqa: E402


@dataclass
class BucketPlace:
    sanity_doc_id: str
    title: str
    slug: Optional[str]
    region: Optional[str]
    subRegion: Optional[str]
    coords: Optional[dict]                       # {lat, lng}
    favourited_at: Optional[str]                 # ISO timestamp from Favourite.createdAt
    comments: list[str] = field(default_factory=list)  # CollectionItemComment.text values


@dataclass
class BucketCollection:
    id: str
    name: str
    owner_email: Optional[str]
    owner_user_id: Optional[str]


@dataclass
class GetUserBucketOutput:
    ok: bool
    collection: Optional[BucketCollection] = None
    places: list[BucketPlace] = field(default_factory=list)
    missing_ids: list[str] = field(default_factory=list)
    latency_ms: int = 0
    error_code: Optional[str] = None
    message: Optional[str] = None


def get_user_bucket(
    collection_id: str,
    railway: Optional[RailwayClient] = None,
    sanity: Optional[SanityClient] = None,
) -> GetUserBucketOutput:
    started = time.monotonic()
    railway = railway or RailwayClient()
    sanity = sanity or SanityClient()

    if not collection_id or not collection_id.startswith("fc_"):
        return GetUserBucketOutput(
            ok=False,
            latency_ms=int((time.monotonic() - started) * 1000),
            error_code="BAD_COLLECTION_ID",
            message=f"collection_id must look like 'fc_...' — got {collection_id!r}",
        )

    # --- Collection envelope ---
    coll_rows = railway.query(
        '''
        SELECT
            c.id              AS id,
            c.name            AS name,
            u.email           AS owner_email,
            u.id              AS owner_user_id
        FROM "FavCollection" c
        LEFT JOIN "User" u ON u.id = c."userId"
        WHERE c.id = %s
        LIMIT 1;
        ''',
        (collection_id,),
    )
    if not coll_rows:
        return GetUserBucketOutput(
            ok=False,
            latency_ms=int((time.monotonic() - started) * 1000),
            error_code="COLLECTION_NOT_FOUND",
            message=f"No FavCollection with id={collection_id!r}",
        )
    coll = BucketCollection(
        id=coll_rows[0]["id"],
        name=coll_rows[0]["name"],
        owner_email=coll_rows[0].get("owner_email"),
        owner_user_id=coll_rows[0].get("owner_user_id"),
    )

    # --- Place rows (favourites in this collection, ordered by when favourited) ---
    fav_rows = railway.query(
        '''
        SELECT
            i.id              AS collection_item_id,
            f.id              AS favourite_id,
            f."placeId"       AS sanity_doc_id,
            f."createdAt"     AS favourited_at
        FROM "FavCollectionItem" i
        JOIN "Favourite" f ON f.id = i."favouriteId"
        WHERE i."collectionId" = %s
        ORDER BY f."createdAt" ASC;
        ''',
        (collection_id,),
    )
    if not fav_rows:
        return GetUserBucketOutput(
            ok=True,
            collection=coll,
            places=[],
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    sanity_ids = [r["sanity_doc_id"] for r in fav_rows]

    # --- Per-item comments (rare, but useful when present) ---
    item_ids = [r["collection_item_id"] for r in fav_rows]
    comment_rows = railway.query(
        '''
        SELECT "collectionItemId" AS item_id, text
        FROM "CollectionItemComment"
        WHERE "collectionItemId" = ANY(%s)
        ORDER BY "createdAt" ASC;
        ''',
        (item_ids,),
    )
    comments_by_item: dict[str, list[str]] = {}
    for cr in comment_rows:
        comments_by_item.setdefault(cr["item_id"], []).append(cr["text"])

    # --- Sanity enrichment in one batch query ---
    sanity_docs = sanity.query(
        '*[_id in $ids]{'
        '_id, title, "slug": slug.current, coordinates, '
        '"region": subRegion->region->name, '
        '"subRegion": subRegion->name'
        '}',
        params={"ids": sanity_ids},
    ) or []
    by_id = {d["_id"]: d for d in sanity_docs}

    places: list[BucketPlace] = []
    missing: list[str] = []
    for r in fav_rows:
        sid = r["sanity_doc_id"]
        doc = by_id.get(sid)
        if not doc:
            missing.append(sid)
            continue
        favourited_at = r.get("favourited_at")
        places.append(BucketPlace(
            sanity_doc_id=sid,
            title=doc.get("title") or "(untitled)",
            slug=doc.get("slug"),
            region=doc.get("region"),
            subRegion=doc.get("subRegion"),
            coords=doc.get("coordinates"),
            favourited_at=favourited_at.isoformat() if favourited_at else None,
            comments=comments_by_item.get(r["collection_item_id"], []),
        ))

    return GetUserBucketOutput(
        ok=True,
        collection=coll,
        places=places,
        missing_ids=missing,
        latency_ms=int((time.monotonic() - started) * 1000),
    )


__all__ = [
    "get_user_bucket",
    "GetUserBucketOutput",
    "BucketCollection",
    "BucketPlace",
]


# =====================================================================
# CLI smoke test
# =====================================================================


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    cid = sys.argv[1] if len(sys.argv) > 1 else "fc_01kb1b26ksexwveksv8se2m9g2"
    out = get_user_bucket(cid)
    if not out.ok:
        print(f"ERROR: {out.error_code}: {out.message}")
        sys.exit(1)
    print(f"Collection: '{out.collection.name}' (id={out.collection.id})")
    print(f"  owner: {out.collection.owner_email}")
    print(f"  places: {len(out.places)}  missing: {len(out.missing_ids)}")
    print(f"  latency: {out.latency_ms}ms")
    print()
    for p in out.places:
        line = f"  - {p.title}"
        if p.subRegion:
            line += f"  ({p.subRegion}"
            if p.region and p.region != p.subRegion:
                line += f", {p.region}"
            line += ")"
        print(line)
        if p.comments:
            for c in p.comments:
                print(f"      \"{c}\"")
    if out.missing_ids:
        print(f"\n  missing sanity IDs (in Railway but not in Sanity): {out.missing_ids}")
