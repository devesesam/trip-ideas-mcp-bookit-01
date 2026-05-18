"""`search_accommodation` — find places to stay in Sanity.

Queries `_type == "accommodation"` documents directly. Sanity already carries
the Bookit-synced fields we need (review counts, star rating, photos via
`bookitMainImageUrl`/`bookitGalleryUrls`, type, coordinates, book-now flag).
No external Bookit API call needed.

What this tool DOES NOT provide (Sprint 5 Bookit-API work):
- Real-time availability for specific dates
- Live numeric pricing (Sanity's `bestPriceAvailable` is a boolean flag, not a price)
- Programmatic booking flow. (We previously emitted a `book_link` to
  tripideas.nz/<slug>, but accommodation pages aren't published as standalone
  URLs on the live site — only places at /place/<slug> are. Probed 2026-05-18:
  every URL variant 404s and no accommodation sitemap exists. Until Douglas
  publishes accommodation pages we return `book_link=None` and surface the
  operator's own website via the `contact.website` field instead.)

Geographic anchoring: accommodation docs aren't tagged with our region/subRegion
taxonomy, so region-based filtering goes through coordinate proximity:
  - region/subRegion → REGION_CENTROIDS or settlement-mean coords → near filter
  - town → exact-match on the `town` field (string substring)
  - near → direct lat/lng/radius_km

All filters optional. Results are scored by review weight + book-now boost +
gold-medal boost - distance penalty.
"""

from __future__ import annotations

import math
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from registry import regions  # noqa: E402
from sanity_client import SanityClient  # noqa: E402


# Hard-coded list of values for accommodationType1 (verified against live Sanity)
ACCOMMODATION_TYPES = [
    "Budget/Backpackers",
    "Cabins/Cottages/Units/Houses",
    "Caravan Parks & Camping",
    "Chalets/Villas/Cottages",
    "Lodge",
    "Motel",
    "Studio/Apartments",
]


# =====================================================================
# Public dataclasses
# =====================================================================


@dataclass
class NearFilter:
    lat: float
    lng: float
    radius_km: float = 30.0


@dataclass
class SearchAccommodationInput:
    # Geographic anchors — at least one is recommended; a totally unfiltered
    # query returns up to `limit` accommodations from the whole NZ pool.
    region: Optional[str] = None
    subRegion: Optional[str] = None
    town: Optional[str] = None
    near: Optional[NearFilter] = None
    # Default radius applied to region/subRegion lookup
    region_radius_km: float = 80.0

    # Type filter — accommodationType1 enum values
    accommodation_types: list[str] = field(default_factory=list)

    # Quality filters
    min_review_rating: Optional[float] = None    # 1-5
    min_review_count: Optional[int] = None       # only meaningful with rating
    star_rating_min: Optional[int] = None        # 1-5; excludes unrated (starRating not set)

    # Booking-flag filters
    bookable_only: bool = False                  # isActive AND bookNowFlag
    hot_deals_only: bool = False                 # isHotDealActive
    gold_medal_only: bool = False                # isGoldMedalToday

    limit: int = 10


@dataclass
class AccommodationResult:
    sanity_doc_id: str
    title: str
    town: Optional[str]
    address: Optional[str]
    coords: Optional[dict]                       # {lat, lng}

    accommodation_type: Optional[str]            # accommodationType1
    accommodation_subtype: Optional[str]         # accommodationType2 (when set)
    star_rating: int                             # 0 = unrated
    review_average: float                        # 0 = unreviewed
    review_count: int

    main_image_url: Optional[str]                # https-prefixed
    gallery_image_urls: list[str]                # https-prefixed; first ~3 from bookitGalleryUrls

    book_now_available: bool
    is_gold_medal: bool                          # isGoldMedalToday
    is_hot_deal: bool                            # isHotDealActive

    point_of_difference: Optional[str]
    cancellation_policy: Optional[str]
    arrival_time: Optional[str]
    departure_time: Optional[str]
    facilities: list[str]

    contact: dict                                # {email?, phone?, website?}
    slug: Optional[str]
    book_link: Optional[str]                     # None for now — accommodation pages aren't published on tripideas.nz; chat should link the operator's own website (contact.website) instead

    distance_km: Optional[float]                 # populated only when near/region filter applied
    score: float
    match_reasons: list[str]


@dataclass
class SearchAccommodationOutput:
    ok: bool
    query_echo: dict
    count: int
    results: list[AccommodationResult]
    facets: dict
    normalization_notes: list[str]
    latency_ms: int
    error_code: Optional[str] = None
    message: Optional[str] = None


# =====================================================================
# Public entry point
# =====================================================================


def search_accommodation(
    inp: SearchAccommodationInput,
    client: Optional[SanityClient] = None,
) -> SearchAccommodationOutput:
    started = time.monotonic()
    client = client or SanityClient()
    normalization_notes: list[str] = []

    # --- Resolve region/subRegion to a `near` filter when not already set ---
    near = inp.near
    if not near and (inp.region or inp.subRegion):
        coords = _resolve_geo_anchor(inp.region, inp.subRegion, normalization_notes)
        if coords:
            near = NearFilter(lat=coords[0], lng=coords[1], radius_km=inp.region_radius_km)

    # --- Build GROQ filter ---
    clauses = ['_type == "accommodation"', 'isActive == true']
    params: dict[str, Any] = {}

    if inp.bookable_only:
        clauses.append("bookNowFlag == true")
    if inp.hot_deals_only:
        clauses.append("isHotDealActive == true")
    if inp.gold_medal_only:
        clauses.append("isGoldMedalToday == true")

    if inp.accommodation_types:
        clauses.append("accommodationType1 in $types")
        params["types"] = list(inp.accommodation_types)
    if inp.min_review_rating is not None:
        clauses.append("reviewAverageRating >= $min_rating")
        params["min_rating"] = float(inp.min_review_rating)
    if inp.min_review_count is not None:
        clauses.append("reviewCount >= $min_count")
        params["min_count"] = int(inp.min_review_count)
    if inp.star_rating_min is not None:
        clauses.append("starRating >= $min_stars")
        params["min_stars"] = int(inp.star_rating_min)

    if inp.town:
        clauses.append("town match $town_pattern")
        params["town_pattern"] = inp.town

    if near:
        # Bounding-box pre-filter; ~111km per degree latitude
        deg_lat = near.radius_km / 111.0
        deg_lng = near.radius_km / (111.0 * max(0.1, math.cos(math.radians(near.lat))))
        clauses.append("coordinates.lat >= $lat_min && coordinates.lat <= $lat_max")
        clauses.append("coordinates.lng >= $lng_min && coordinates.lng <= $lng_max")
        params["lat_min"] = near.lat - deg_lat
        params["lat_max"] = near.lat + deg_lat
        params["lng_min"] = near.lng - deg_lng
        params["lng_max"] = near.lng + deg_lng

    groq = (
        f"*[{' && '.join(clauses)}]{{"
        "_id, title, town, address, coordinates, slug, "
        "accommodationType1, accommodationType2, starRating, "
        "reviewAverageRating, reviewCount, bookNowFlag, isGoldMedalToday, "
        "isHotDealActive, pointOfDifference, cancellationPolicy, "
        "arrivalTime, departureTime, facilities, "
        "telephone, email, website, "
        "bookitMainImageUrl, bookitGalleryUrls"
        "}"
    )
    candidates = client.query(groq, params=params) or []
    normalization_notes.append(f"GROQ pre-filter returned {len(candidates)} candidate accommodation docs")

    # --- In-memory refine + score ---
    enriched: list[AccommodationResult] = []
    for d in candidates:
        coords = d.get("coordinates") or None
        distance_km: Optional[float] = None

        if near and coords and coords.get("lat") is not None:
            distance_km = _haversine_km(near.lat, near.lng, coords["lat"], coords["lng"])
            if distance_km > near.radius_km:
                continue

        score = 1.0
        match_reasons: list[str] = []

        # Geographic anchor in match_reasons
        if near and distance_km is not None:
            score += max(0.0, 1.0 - (distance_km / near.radius_km)) * 1.0
            match_reasons.append(f"within {distance_km:.1f}km of target")
        if inp.town and d.get("town"):
            match_reasons.append(f"in {d['town']}")

        # Type match
        accom_type = d.get("accommodationType1")
        if inp.accommodation_types and accom_type in inp.accommodation_types:
            match_reasons.append(f"type: {accom_type}")
            score += 0.5

        # Reviews
        rev_avg = float(d.get("reviewAverageRating") or 0)
        rev_count = int(d.get("reviewCount") or 0)
        if rev_count > 0 and rev_avg > 0:
            # Weighted: average × log(count+1), capped
            review_weight = rev_avg * math.log10(rev_count + 1) * 0.5
            score += min(2.0, review_weight)
            if rev_count >= 5:
                match_reasons.append(f"{rev_avg:.1f}/5 from {rev_count} guests")

        # Star rating
        stars = int(d.get("starRating") or 0)
        if stars > 0:
            score += stars * 0.1
            if stars >= 4:
                match_reasons.append(f"{stars}-star rated")

        # Booking flags
        bookable = bool(d.get("bookNowFlag"))
        if bookable:
            score += 0.4
            match_reasons.append("bookable now")
        gold = bool(d.get("isGoldMedalToday"))
        if gold:
            score += 0.5
            match_reasons.append("Gold Medal property")
        hot = bool(d.get("isHotDealActive"))
        if hot:
            score += 0.3
            match_reasons.append("hot deal active")

        # Build the result row
        slug = (d.get("slug") or {}).get("current") if isinstance(d.get("slug"), dict) else None
        main_url = _https(d.get("bookitMainImageUrl"))
        gallery = [_https(u) for u in (d.get("bookitGalleryUrls") or [])[:4] if u]
        gallery = [g for g in gallery if g]

        enriched.append(AccommodationResult(
            sanity_doc_id=d.get("_id", ""),
            title=d.get("title") or "(untitled)",
            town=d.get("town"),
            address=d.get("address"),
            coords=coords,
            accommodation_type=accom_type,
            accommodation_subtype=d.get("accommodationType2"),
            star_rating=stars,
            review_average=rev_avg,
            review_count=rev_count,
            main_image_url=main_url,
            gallery_image_urls=gallery,
            book_now_available=bookable,
            is_gold_medal=gold,
            is_hot_deal=hot,
            point_of_difference=d.get("pointOfDifference"),
            cancellation_policy=d.get("cancellationPolicy"),
            arrival_time=d.get("arrivalTime"),
            departure_time=d.get("departureTime"),
            facilities=list(d.get("facilities") or []),
            contact={
                "email": d.get("email"),
                "phone": d.get("telephone"),
                "website": d.get("website"),
            },
            slug=slug,
            # Intentionally None — see module docstring. tripideas.nz/<slug>
            # 404s for accommodation pages; the chat surfaces contact.website
            # (the operator's own site) as the actionable link instead.
            book_link=None,
            distance_km=distance_km,
            score=score,
            match_reasons=match_reasons,
        ))

    enriched.sort(key=lambda r: -r.score)
    top = enriched[: inp.limit]

    facets = {
        "by_type": dict(Counter(r.accommodation_type for r in enriched if r.accommodation_type).most_common()),
        "by_town": dict(Counter(r.town for r in enriched if r.town).most_common(10)),
        "bookable_count": sum(1 for r in enriched if r.book_now_available),
        "gold_medal_count": sum(1 for r in enriched if r.is_gold_medal),
        "hot_deal_count": sum(1 for r in enriched if r.is_hot_deal),
    }

    out = SearchAccommodationOutput(
        ok=True,
        query_echo=_echo(inp, near),
        count=len(enriched),
        results=top,
        facets=facets,
        normalization_notes=normalization_notes,
        latency_ms=int((time.monotonic() - started) * 1000),
    )

    if not enriched:
        out.error_code = "NO_MATCHES"
        out.message = "No accommodation matched the given filters."

    return out


# =====================================================================
# Helpers
# =====================================================================


def _echo(inp: SearchAccommodationInput, resolved_near: Optional[NearFilter]) -> dict:
    return {
        "region": inp.region,
        "subRegion": inp.subRegion,
        "town": inp.town,
        "near": asdict(resolved_near) if resolved_near else None,
        "accommodation_types": inp.accommodation_types,
        "min_review_rating": inp.min_review_rating,
        "min_review_count": inp.min_review_count,
        "star_rating_min": inp.star_rating_min,
        "bookable_only": inp.bookable_only,
        "hot_deals_only": inp.hot_deals_only,
        "gold_medal_only": inp.gold_medal_only,
        "limit": inp.limit,
    }


def _resolve_geo_anchor(
    region: Optional[str],
    subRegion: Optional[str],
    notes: list[str],
) -> Optional[tuple[float, float]]:
    """Resolve region or subRegion → (lat, lng) for use as a near filter.

    Tries subRegion first (more specific), falls back to region centroid.
    """
    if subRegion:
        # Settlement registry knows page-coord means per subRegion
        from registry import settlements
        try:
            resolved = settlements.resolve(subRegion, region=region)
        except Exception:
            resolved = None
        if resolved:
            notes.append(f"subRegion {subRegion!r} resolved to ({resolved.lat:.3f}, {resolved.lng:.3f}) via {resolved.method}")
            return (resolved.lat, resolved.lng)
        notes.append(f"subRegion {subRegion!r} did not resolve; falling back to region centroid")

    if region:
        centroid = regions.region_centroid(region)
        if centroid:
            notes.append(f"region {region!r} resolved to centroid ({centroid[0]:.3f}, {centroid[1]:.3f})")
            return centroid
        notes.append(f"region {region!r} has no centroid mapped")
    return None


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _https(url: Any) -> Optional[str]:
    """Normalize protocol-relative URLs (//images.bookeasy.com.au/...) to https://."""
    if not isinstance(url, str) or not url:
        return None
    if url.startswith("//"):
        return "https:" + url
    return url


# =====================================================================
# CLI smoke test
# =====================================================================


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    queries = [
        SearchAccommodationInput(
            town="Queenstown", min_review_rating=4.0, limit=5,
        ),
        SearchAccommodationInput(
            region="Otago", accommodation_types=["Lodge"], limit=5,
        ),
        SearchAccommodationInput(
            town="Picton", accommodation_types=["Motel", "Lodge"], limit=5,
        ),
        SearchAccommodationInput(
            region="Canterbury", gold_medal_only=True, limit=5,
        ),
    ]

    for q in queries:
        print(f"\n=== Query: town={q.town!r}, region={q.region!r}, types={q.accommodation_types}, "
              f"min_rating={q.min_review_rating}, gold_only={q.gold_medal_only}, limit={q.limit} ===")
        out = search_accommodation(q)
        print(f"  ok={out.ok}, count={out.count}, latency={out.latency_ms}ms")
        for note in out.normalization_notes:
            print(f"  · {note}")
        if out.error_code:
            print(f"  error: {out.error_code}: {out.message}")
        for r in out.results:
            tag = "🏆" if r.is_gold_medal else ("✓" if r.book_now_available else " ")
            review_str = (
                f"{r.review_average:.1f}/5 ({r.review_count})"
                if r.review_count > 0 else "no reviews"
            )
            stars = f"{r.star_rating}★" if r.star_rating > 0 else "—"
            dist = f" {r.distance_km:.1f}km" if r.distance_km else ""
            print(f"  {tag} [{r.score:5.2f}] {r.title:50s} {stars:4s} {review_str:18s}"
                  f" {r.accommodation_type or '?':30s} {r.town or '?'}{dist}")
            print(f"           reasons: {r.match_reasons}")
        if out.facets.get("by_type"):
            print(f"  facets.by_type: {out.facets['by_type']}")
