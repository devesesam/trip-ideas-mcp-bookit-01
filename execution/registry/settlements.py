"""Lightweight settlement / base-location coordinate resolution.

No parallel registry — uses live Sanity data.

Resolution order for a given `name`:
  1. Match against a subRegion name → coordinates of the page with the most
     neighbours within 15 km (the *densest cluster* anchor). This handles
     dispersed sub-regions like Hauraki Gulf Islands, Catlins, Fiordland —
     where the geographic mean lands between clusters but a single
     page-as-anchor gives a useful base.
  2. Match against the suburb_place / subregion2 string inside aiMetadata
     `location` of any page → that page's root `coordinates`.
  3. Fallback: None (caller decides — error, ask user, or guess).

Caches a tiny in-memory result per (name, region) pair for the session.
"""

from __future__ import annotations

import math
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from sanity_client import SanityClient  # noqa: E402
from registry import regions  # noqa: E402


# Neighbour radius used to find the densest cluster within a sub-region.
# 15 km is wide enough to cover a town and its near-surrounds (so all pages
# anchored on a single settlement cluster together) but narrow enough to
# separate distinct settlements in dispersed sub-regions like the Catlins
# (Owaka vs Papatowai ~20 km apart) or Hauraki Gulf (Waiheke vs Rangitoto).
_CLUSTER_NEIGHBOUR_KM = 15.0
# Tie-break radius — when two pages have the same primary neighbour count,
# whichever has more very-close neighbours wins. Picks the "centre of mass"
# within the largest cluster.
_CLUSTER_TIEBREAK_KM = 5.0
# Below this page count, clustering is meaningless — fall back to mean.
_CLUSTER_MIN_PAGES = 3


def _strip_accents(s: str) -> str:
    """Normalise a string for diacritic-tolerant comparison.

    GROQ's `match` is diacritic-sensitive, and Claude regularly strips macrons
    from Te Reo place names when constructing tool args (e.g. passing
    "Purakaunui Falls" when the page title is "Pūrākaunui Falls"). To resolve
    correctly regardless, we normalise both sides via NFKD decomposition and
    drop combining marks, then casefold.
    """
    nfkd = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).casefold().strip()


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class ResolvedLocation:
    name: str
    lat: float
    lng: float
    method: str             # "subregion_densest_cluster" | "subregion_mean" | "page_match" | "explicit"
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
        result = _resolve_subregion_anchor(client, sub.id, sub.name)

    # --- Else try page-level title match (diacritic-tolerant) ---
    # We can't rely on GROQ `match` for this because it's diacritic-sensitive
    # — "Purakaunui" won't match "Pūrākaunui" at the query layer. Instead:
    # when a region is provided, fetch all that region's pages and filter
    # title strings in Python after _strip_accents-normalising both sides.
    # When no region: fall back to the GROQ title match (broader pool risk).
    if not result:
        candidates: list[dict] = []
        if region:
            region_obj = regions._registry().region_by_name(region)
            if region_obj:
                candidates = client.query(
                    '*[_type == "page" && defined(coordinates) '
                    '&& subRegion->region->name == $region]'
                    '{_id, title, coordinates}',
                    {"region": region_obj.name},
                ) or []
        if not candidates:
            # No region — narrow GROQ to title hits only (won't catch
            # diacritic mismatches but body-mention is worse).
            candidates = client.query(
                '*[_type == "page" && defined(coordinates) '
                '&& title match $name_pattern][0...50]'
                '{_id, title, coordinates}',
                {"name_pattern": f"*{name}*"},
            ) or []

        if candidates:
            needle = _strip_accents(name)
            # Rank: exact title (normalised) > title-substring (normalised).
            # Body-mention path is dead — we only ever check titles now.
            exact = [c for c in candidates
                     if _strip_accents(c.get("title") or "") == needle]
            title_sub = [c for c in candidates
                         if needle and needle in _strip_accents(c.get("title") or "")]
            best = None
            confidence = 0.0
            if exact:
                best = exact[0]
                confidence = 0.7
            elif title_sub:
                best = title_sub[0]
                confidence = 0.55

            if best:
                coords = best.get("coordinates") or {}
                if coords.get("lat") is not None:
                    result = ResolvedLocation(
                        name=best.get("title", name),
                        lat=float(coords["lat"]),
                        lng=float(coords["lng"]),
                        method="page_match",
                        confidence=confidence,
                    )

    # --- Last resort: region centroid via the largest sub-region ---
    # If the name didn't match any subRegion or page title, but the caller
    # gave us a region, return the densest-cluster anchor of the most-
    # populated sub-region within it. Better than failing — the LLM may have
    # passed a colloquialism like "Wellington CBD" that's not a tag anywhere.
    if not result and region:
        region_obj = regions._registry().region_by_name(region)
        if region_obj:
            subs = client.query(
                '*[_type == "subRegion" && region->name == $region]{ _id, name, '
                '"count": count(*[_type == "page" && subRegion._ref == ^._id]) }'
                ' | order(count desc)',
                {"region": region_obj.name},
            ) or []
            for sub in subs:
                if sub.get("count", 0) < 1:
                    continue
                anchor = _resolve_subregion_anchor(client, sub["_id"], sub["name"])
                if anchor:
                    result = ResolvedLocation(
                        name=anchor.name,
                        lat=anchor.lat,
                        lng=anchor.lng,
                        method="region_fallback",
                        confidence=0.4,
                    )
                    break

    _cache[key] = result
    return result


# =====================================================================
# Sub-region → anchor coordinates via densest cluster
# =====================================================================


def _resolve_subregion_anchor(
    client: SanityClient,
    sub_id: str,
    sub_name: str,
) -> Optional[ResolvedLocation]:
    """Pick a sensible anchor point for a sub-region.

    For dispersed sub-regions (Hauraki Gulf Islands, Catlins, Fiordland,
    Marlborough Sounds) the geographic mean of all page coordinates falls
    between clusters and lands somewhere useless (e.g. the middle of the
    ocean). Instead we find the page with the most neighbours within
    ~15 km, and use that page's coordinates as the anchor.

    For compact sub-regions (Wellington City, Dunedin) every page is a
    neighbour of every other, so the choice is essentially "page closest
    to the centre of mass" — same as the mean would give.

    Falls back to math::avg for sub-regions with fewer than _CLUSTER_MIN_PAGES
    where clustering is meaningless.
    """
    # Fetch every page in the sub-region with valid coordinates — one round trip.
    pages = client.query(
        '*[_type == "page" && subRegion._ref == $sub_id'
        ' && defined(coordinates.lat) && defined(coordinates.lng)]'
        '{ _id, title, "lat": coordinates.lat, "lng": coordinates.lng }',
        {"sub_id": sub_id},
    ) or []

    if not pages:
        return None

    if len(pages) < _CLUSTER_MIN_PAGES:
        # Not enough points to cluster — average is fine.
        avg_lat = sum(float(p["lat"]) for p in pages) / len(pages)
        avg_lng = sum(float(p["lng"]) for p in pages) / len(pages)
        return ResolvedLocation(
            name=sub_name, lat=avg_lat, lng=avg_lng,
            method="subregion_mean",
            confidence=0.5,
        )

    # Count neighbours within the cluster radius for each page.
    # O(n^2) over typically ≤ 200 points — a few ms.
    coords = [(float(p["lat"]), float(p["lng"])) for p in pages]
    best_idx = 0
    best_main = -1
    best_tie = -1
    for i, (lat_i, lng_i) in enumerate(coords):
        main = 0
        tie = 0
        for j, (lat_j, lng_j) in enumerate(coords):
            if i == j:
                continue
            d = _haversine_km(lat_i, lng_i, lat_j, lng_j)
            if d <= _CLUSTER_NEIGHBOUR_KM:
                main += 1
                if d <= _CLUSTER_TIEBREAK_KM:
                    tie += 1
        if main > best_main or (main == best_main and tie > best_tie):
            best_main = main
            best_tie = tie
            best_idx = i

    anchor = pages[best_idx]
    # Confidence scales with the size of the picked cluster.
    cluster_size = best_main + 1  # +1 for the anchor itself
    if cluster_size >= 8:
        confidence = 0.90
    elif cluster_size >= 4:
        confidence = 0.80
    else:
        confidence = 0.65

    return ResolvedLocation(
        name=sub_name,
        lat=float(anchor["lat"]),
        lng=float(anchor["lng"]),
        method="subregion_densest_cluster",
        confidence=confidence,
    )


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
