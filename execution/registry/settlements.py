"""Lightweight settlement / base-location coordinate resolution.

No parallel registry — uses live Sanity data.

Resolution order for a given `name`:
  1. Match against a subRegion name → mean lat/lng of pages whose `subRegion`
     points at it.
  2. Match against the suburb_place / subregion2 string inside aiMetadata
     `location` of any page → that page's root `coordinates`.
  3. Fallback: None (caller decides — error, ask user, or guess).

Caches a tiny in-memory result per (name, region) pair for the session.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from sanity_client import SanityClient  # noqa: E402
from registry import regions  # noqa: E402


@dataclass(frozen=True)
class ResolvedLocation:
    name: str
    lat: float
    lng: float
    method: str             # "subregion_mean" | "page_match" | "explicit"
    confidence: float


_cache: dict[tuple[str, str], Optional[ResolvedLocation]] = {}


def resolve(
    name: str,
    region: Optional[str] = None,
    client: Optional[SanityClient] = None,
) -> Optional[ResolvedLocation]:
    """Resolve a base-location name to coordinates. Returns None if unresolvable."""
    key = ((name or "").strip().casefold(), (region or "").strip().casefold())
    if key in _cache:
        return _cache[key]

    client = client or SanityClient()
    result: Optional[ResolvedLocation] = None

    # --- Try subRegion match first ---
    sub = regions._registry().subRegion_by_name(name)
    if sub:
        coords = client.fetch_one(
            "{"
            f'"avg_lat": math::avg(*[_type == "page" && subRegion._ref == "{sub.id}"'
            ' && defined(coordinates.lat)].coordinates.lat),'
            f'"avg_lng": math::avg(*[_type == "page" && subRegion._ref == "{sub.id}"'
            ' && defined(coordinates.lng)].coordinates.lng),'
            f'"count": count(*[_type == "page" && subRegion._ref == "{sub.id}"'
            ' && defined(coordinates.lat)])'
            "}"
        )
        if coords and coords.get("avg_lat") is not None and coords.get("count", 0) > 0:
            result = ResolvedLocation(
                name=sub.name,
                lat=float(coords["avg_lat"]),
                lng=float(coords["avg_lng"]),
                method="subregion_mean",
                confidence=0.85 if coords["count"] >= 5 else 0.65,
            )

    # --- Else try page-level match (settlement mentioned in aiMetadata) ---
    if not result:
        clauses = ['_type == "page"', "defined(coordinates)"]
        params: dict = {}
        if region:
            region_obj = regions._registry().region_by_name(region)
            if region_obj:
                clauses.append("subRegion->region->name == $region")
                params["region"] = region_obj.name
        # Substring match on title or aiMetadata text. aiMetadata is a string
        # so substring search inside it is `match` (works on words).
        clauses.append('(title match $name_pattern || aiMetadata match $name_pattern)')
        params["name_pattern"] = f"*{name}*"
        groq = (
            f"*[{' && '.join(clauses)}][0...10]"
            "{_id, title, coordinates}"
        )
        candidates = client.query(groq, params=params) or []
        if candidates:
            # Take coords of best title match, else first
            best = next(
                (c for c in candidates if c.get("title", "").lower() == name.lower()),
                candidates[0],
            )
            coords = best.get("coordinates") or {}
            if coords.get("lat") is not None:
                result = ResolvedLocation(
                    name=best.get("title", name),
                    lat=float(coords["lat"]),
                    lng=float(coords["lng"]),
                    method="page_match",
                    confidence=0.7 if best.get("title", "").lower() == name.lower() else 0.5,
                )

    _cache[key] = result
    return result


# CLI smoke test
if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    samples = [
        ("Queenstown", "Otago"),
        ("Wellington", "Wellington"),
        ("Hibiscus Coast", "Auckland"),         # subregion2-level — likely no direct subRegion match
        ("North Otago", "Otago"),               # exact subRegion name
        ("Bridge Point", "Otago"),              # tiny settlement — mentioned in aiMetadata
        ("Nelson", "Nelson Tasman"),
    ]
    for name, region in samples:
        r = resolve(name, region)
        if r:
            print(f"  {name!r:24s} (region={region}) → {r.lat:.4f},{r.lng:.4f} "
                  f"via {r.method} confidence={r.confidence}")
        else:
            print(f"  {name!r:24s} (region={region}) → unresolved")
