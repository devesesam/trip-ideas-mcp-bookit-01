"""`search_places` — cascade-filter search over Sanity `page` documents.

Pipeline:
  1. **GROQ filter (cheap)**: subRegion->region->name match, optional
     subRegion narrowing, optional tag intersection, optional bounding box
     for `near` queries. Returns candidate pages with aiMetadata payload.
  2. **Python parse (fast)**: feed each aiMetadata through the parser; drop
     parse_error docs (or surface them with reduced data, caller's choice).
  3. **In-memory refinement + scoring**: apply filters that need parsed
     signals (duration_bands, physical_intensity_max, dog_friendly,
     interests_text). Score each surviving doc against the requested
     filter set; rank; emit top-N with `match_reasons`.

The chat orchestrator calls this with whatever subset of filters made sense
for the user utterance. Filters are optional (except `region`); a road-trip
query won't pass `physical_intensity_max`, a quiet-day query will.
"""

from __future__ import annotations

import math
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

# Allow the module to be both run as a script and imported as a package
_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from aimetadata import ParsedAiMetadata, parse  # noqa: E402
from normalize.tag_mapping import TAG_MAPPINGS, for_tag  # noqa: E402
from registry import regions  # noqa: E402
from sanity_client import SanityClient  # noqa: E402


# =====================================================================
# Inverted indices over the tag taxonomy (built once at module load)
# =====================================================================


def _build_theme_to_tags() -> dict[str, list[str]]:
    inv: dict[str, list[str]] = {}
    for tag_name, mapping in TAG_MAPPINGS.items():
        for theme in mapping.themes:
            inv.setdefault(theme, []).append(tag_name)
    return inv


def _build_subtype_to_tags() -> dict[str, list[str]]:
    inv: dict[str, list[str]] = {}
    for tag_name, mapping in TAG_MAPPINGS.items():
        for subtype in mapping.place_subtype_hints:
            inv.setdefault(subtype, []).append(tag_name)
    return inv


THEME_TO_TAGS = _build_theme_to_tags()
SUBTYPE_TO_TAGS = _build_subtype_to_tags()


# =====================================================================
# Public dataclasses (input + output)
# =====================================================================


@dataclass
class NearFilter:
    lat: float
    lng: float
    radius_km: float = 30.0


@dataclass
class SearchPlacesInput:
    region: str                                    # REQUIRED — must match a region (or alias)
    subRegion: Optional[str] = None
    themes: list[str] = field(default_factory=list)        # e.g. ["coastal", "scenic"]
    place_subtypes: list[str] = field(default_factory=list)  # e.g. ["beach", "walk"]
    physical_intensity_max: Optional[str] = None   # easy | moderate | demanding
    duration_bands: list[str] = field(default_factory=list)
    dog_friendly_required: bool = False
    near: Optional[NearFilter] = None
    interests_text: Optional[str] = None           # free-form ("rock pools")
    limit: int = 10
    include_parse_errors: bool = False             # surface truncated docs as thin entries


@dataclass
class SearchPlaceResult:
    sanity_doc_id: str
    title: str
    region: str
    subRegion: Optional[str]
    settlement: Optional[str]
    coords: Optional[dict]
    themes_derived: list[str]
    place_subtype_derived: Optional[str]
    physical_intensity: Optional[str]
    duration_band: Optional[str]
    dog_friendly: str
    summary: str
    score: float
    match_reasons: list[str]
    parse_error: bool = False
    distance_km: Optional[float] = None


@dataclass
class SearchPlacesOutput:
    ok: bool
    query_echo: dict
    count: int
    results: list[SearchPlaceResult]
    facets: dict
    normalization_notes: list[str]
    latency_ms: int
    error_code: Optional[str] = None
    message: Optional[str] = None
    relaxation_suggestions: list[str] = field(default_factory=list)


# =====================================================================
# Public entry point
# =====================================================================


_INTENSITY_RANK = {"none": 0, "easy": 1, "moderate": 2, "demanding": 3}


def search_places(
    inp: SearchPlacesInput,
    client: Optional[SanityClient] = None,
) -> SearchPlacesOutput:
    """Run the cascade. See module docstring for the pipeline."""
    started = time.monotonic()
    client = client or SanityClient()
    normalization_notes: list[str] = []

    # --- Resolve region against the live registry (handle aliases) ---
    region_obj = regions._registry().region_by_name(inp.region)
    if not region_obj:
        return SearchPlacesOutput(
            ok=False,
            query_echo=_query_echo(inp, []),
            count=0,
            results=[],
            facets={},
            normalization_notes=normalization_notes,
            latency_ms=int((time.monotonic() - started) * 1000),
            error_code="INVALID_REGION",
            message=f"Region {inp.region!r} not found. Known: {regions.all_region_names()}",
        )
    canonical_region = region_obj.name
    if canonical_region != inp.region:
        normalization_notes.append(f"Region {inp.region!r} resolved to {canonical_region!r}")

    # --- Translate themes/place_subtypes into tag-name OR-set for GROQ ---
    required_any_tag_names = _theme_subtype_tags(inp.themes, inp.place_subtypes)
    if inp.themes or inp.place_subtypes:
        normalization_notes.append(
            f"Filters {{themes={inp.themes}, place_subtypes={inp.place_subtypes}}} "
            f"resolved to {len(required_any_tag_names)} candidate tag(s)"
        )

    # --- Build the GROQ query ---
    candidates = _fetch_candidates(
        client=client,
        region_name=canonical_region,
        subRegion=inp.subRegion,
        any_tag_names=required_any_tag_names,
        near=inp.near,
    )
    normalization_notes.append(f"GROQ pre-filter returned {len(candidates)} candidate docs")

    # --- Parse + refine + score in Python ---
    enriched: list[SearchPlaceResult] = []
    for doc in candidates:
        ai = parse(doc.get("aiMetadata"))
        if ai.parse_error and not inp.include_parse_errors:
            continue

        match_reasons: list[str] = []
        score = 0.0

        # Hard filters that must pass
        if inp.physical_intensity_max:
            ai_int = ai.physical_intensity_hint()
            if ai_int and _intensity_exceeds(ai_int, inp.physical_intensity_max):
                continue
            if ai_int:
                match_reasons.append(f"intensity {ai_int} ≤ {inp.physical_intensity_max}")
                score += 1.0

        if inp.duration_bands:
            db = ai.duration_band()
            if db and db not in inp.duration_bands:
                continue
            if db:
                match_reasons.append(f"duration {db}")
                score += 1.0

        if inp.dog_friendly_required:
            if ai.dog_friendly_kind == "not_allowed":
                continue
            if ai.dog_friendly_kind in ("allowed", "on_leash_only", "seasonal"):
                match_reasons.append(f"dogs: {ai.dog_friendly_kind}")
                score += 0.5

        # Distance filter for `near` queries
        distance_km: Optional[float] = None
        if inp.near and ai.coordinates and doc.get("coordinates"):
            distance_km = _haversine_km(
                inp.near.lat, inp.near.lng,
                doc["coordinates"]["lat"], doc["coordinates"]["lng"],
            )
            if distance_km > inp.near.radius_km:
                continue
            score += max(0.0, 1.0 - (distance_km / inp.near.radius_km)) * 1.0
            match_reasons.append(f"within {distance_km:.1f}km of target")

        # Interests text (substring across description + attractions + local_tips)
        if inp.interests_text:
            interest_blob = " ".join([
                ai.description, " ".join(ai.attractions),
                " ".join(ai.local_tips), " ".join(ai.activities),
            ]).lower()
            term = inp.interests_text.lower().strip()
            if term and term not in interest_blob:
                # Soft filter — drop if interests_text was specific and didn't match
                # but keep if it could be paraphrase. For v1 we drop strictly.
                continue
            if term:
                match_reasons.append(f"matches '{term}'")
                score += 1.5

        # Compute themes_derived from doc's tag list (not aiMetadata)
        tag_names: list[str] = [t for t in (doc.get("tag_names") or []) if t]
        themes_derived = _derive_themes(tag_names)
        place_subtype_derived = _derive_place_subtype(tag_names)

        # Soft scoring boosts: theme overlap, subtype match
        if inp.themes:
            theme_overlap = set(inp.themes) & set(themes_derived)
            if theme_overlap:
                match_reasons.append(f"themes match: {sorted(theme_overlap)}")
                score += 1.0 * len(theme_overlap)
        if inp.place_subtypes:
            if place_subtype_derived in inp.place_subtypes:
                match_reasons.append(f"place_subtype: {place_subtype_derived}")
                score += 1.5

        # Region match always counted (passed GROQ already)
        match_reasons.insert(0, f"region: {canonical_region}")
        score += 0.5

        enriched.append(SearchPlaceResult(
            sanity_doc_id=doc["_id"],
            title=doc.get("title") or "(untitled)",
            region=canonical_region,
            subRegion=doc.get("subRegion_name"),
            settlement=ai.settlement(),
            coords=doc.get("coordinates"),
            themes_derived=themes_derived,
            place_subtype_derived=place_subtype_derived,
            physical_intensity=ai.physical_intensity_hint(),
            duration_band=ai.duration_band(),
            dog_friendly=ai.dog_friendly_kind,
            summary=(ai.description[:280] + "…") if len(ai.description) > 280 else ai.description,
            score=score,
            match_reasons=match_reasons,
            parse_error=ai.parse_error,
            distance_km=distance_km,
        ))

    # --- Rank, slice, build facets ---
    enriched.sort(key=lambda r: -r.score)
    top = enriched[: inp.limit]

    facets = {
        "by_subRegion": dict(Counter(r.subRegion for r in enriched if r.subRegion).most_common()),
        "by_theme": dict(Counter(t for r in enriched for t in r.themes_derived).most_common()),
        "by_place_subtype": dict(Counter(r.place_subtype_derived for r in enriched
                                         if r.place_subtype_derived).most_common()),
    }

    out = SearchPlacesOutput(
        ok=True,
        query_echo=_query_echo(inp, required_any_tag_names),
        count=len(enriched),
        results=top,
        facets=facets,
        normalization_notes=normalization_notes,
        latency_ms=int((time.monotonic() - started) * 1000),
    )

    if not enriched:
        out.error_code = "NO_MATCHES"
        out.message = f"No places matched in {canonical_region} with the given filters."
        out.relaxation_suggestions = _suggest_relaxations(inp)

    return out


# =====================================================================
# Helpers
# =====================================================================


def _query_echo(inp: SearchPlacesInput, tag_names: list[str]) -> dict:
    return {
        "region": inp.region,
        "subRegion": inp.subRegion,
        "themes": inp.themes,
        "place_subtypes": inp.place_subtypes,
        "physical_intensity_max": inp.physical_intensity_max,
        "duration_bands": inp.duration_bands,
        "dog_friendly_required": inp.dog_friendly_required,
        "near": asdict(inp.near) if inp.near else None,
        "interests_text": inp.interests_text,
        "limit": inp.limit,
        "tag_filter_resolved": tag_names,
    }


def _theme_subtype_tags(themes: list[str], place_subtypes: list[str]) -> list[str]:
    """Translate requested themes + place_subtypes into a deduplicated list of
    tag names that, when present on a page, indicate a match."""
    out: set[str] = set()
    for t in themes:
        out.update(THEME_TO_TAGS.get(t, []))
    for s in place_subtypes:
        out.update(SUBTYPE_TO_TAGS.get(s, []))
    return sorted(out)


def _fetch_candidates(
    client: SanityClient,
    region_name: str,
    subRegion: Optional[str],
    any_tag_names: list[str],
    near: Optional[NearFilter],
) -> list[dict]:
    """Build and execute the GROQ filter. Returns docs with aiMetadata payload."""
    clauses = [
        '_type == "page"',
        "length(aiMetadata) > 10",
        "subRegion->region->name == $region",
    ]
    params: dict[str, Any] = {"region": region_name}

    if subRegion:
        clauses.append("subRegion->name == $subRegion")
        params["subRegion"] = subRegion

    if any_tag_names:
        clauses.append("count(tags[]->name[@ in $tag_names]) > 0")
        params["tag_names"] = any_tag_names

    if near:
        # Bounding-box pre-filter; ~111 km per degree lat
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
        '_id, title, coordinates, aiMetadata, '
        '"tag_names": tags[]->name, '
        '"subRegion_name": subRegion->name'
        "}"
    )
    return client.query(groq, params=params) or []


def _derive_themes(tag_names: list[str]) -> list[str]:
    out: set[str] = set()
    for t in tag_names:
        m = for_tag(t)
        if m:
            out.update(m.themes)
    return sorted(out)


def _derive_place_subtype(tag_names: list[str]) -> Optional[str]:
    """Vote across tags for a single place_subtype. Highest count wins."""
    votes: Counter[str] = Counter()
    for t in tag_names:
        m = for_tag(t)
        if m:
            for s in m.place_subtype_hints:
                votes[s] += 1
    return votes.most_common(1)[0][0] if votes else None


def _intensity_exceeds(actual: str, max_allowed: str) -> bool:
    return _INTENSITY_RANK.get(actual, 0) > _INTENSITY_RANK.get(max_allowed, 3)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points in km."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _suggest_relaxations(inp: SearchPlacesInput) -> list[str]:
    """Produce simple text suggestions for narrowing filters when no results match."""
    suggestions: list[str] = []
    if inp.subRegion:
        suggestions.append(f"Drop subRegion filter (broaden from {inp.subRegion!r} to all of {inp.region!r})")
    if inp.themes:
        suggestions.append(f"Drop one or more themes: {inp.themes}")
    if inp.physical_intensity_max and inp.physical_intensity_max != "demanding":
        suggestions.append(f"Raise physical_intensity_max to 'demanding'")
    if inp.dog_friendly_required:
        suggestions.append("Drop dog_friendly_required (currently True)")
    if inp.near:
        suggestions.append(f"Increase near.radius_km from {inp.near.radius_km}")
    if not suggestions:
        suggestions.append("Try a different region or remove all filters except region.")
    return suggestions


# =====================================================================
# CLI smoke test
# =====================================================================


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    # Three exercise queries representing different shapes:
    # 1. Outdoor: coastal walks in Northland
    # 2. Vague: anything in Otago
    # 3. Specific: places "near Queenstown" within 30 km
    queries = [
        SearchPlacesInput(region="Northland", themes=["coastal"], place_subtypes=["beach", "walk"], limit=5),
        SearchPlacesInput(region="Otago", limit=5),
        SearchPlacesInput(region="Otago", near=NearFilter(lat=-45.0312, lng=168.6626, radius_km=30), limit=5),
    ]

    for q in queries:
        print(f"\n=== Query: region={q.region!r}, themes={q.themes}, subtypes={q.place_subtypes}, "
              f"near={q.near}, limit={q.limit} ===")
        out = search_places(q)
        print(f"  ok={out.ok}, count={out.count}, latency={out.latency_ms}ms")
        if out.error_code:
            print(f"  error: {out.error_code}: {out.message}")
        for note in out.normalization_notes:
            print(f"  · {note}")
        for r in out.results:
            print(f"  [{r.score:5.2f}]  {r.title:40s} sub={r.subRegion!r:24s} "
                  f"subtype={r.place_subtype_derived!r:18s} themes={r.themes_derived[:3]}"
                  f"{' dist=' + format(r.distance_km, '.1f') + 'km' if r.distance_km else ''}")
            print(f"           reasons: {r.match_reasons}")
        if out.facets.get("by_subRegion"):
            print(f"  facets.by_subRegion: {dict(list(out.facets['by_subRegion'].items())[:5])}")
