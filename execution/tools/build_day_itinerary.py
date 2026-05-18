"""`build_day_itinerary` — assemble one day from a region + base location + filters.

Pipeline:
  1. Resolve `base_location` to coordinates (subRegion mean or page-match).
  2. Build candidate pool — either the explicit `include_doc_ids` from a
     prior `search_places` call, OR run `search_places` internally with the
     same filter menu, anchored to a `near` query around the base.
  3. Greedy fill: pick highest-scoring candidate within drive budget that
     fits remaining day window; insert a `place` slot, an adjacent
     `travel_gap`, and (around noon) a `meal_gap`. Repeat until target
     slot count or time runs out.
  4. Compute feasibility totals + warnings (tide-sensitive without tide
     data, weather-sensitive without forecast, long drives, sparse
     facilities, etc.).
  5. Surface `unfilled_requests` — the honest list of things the tool
     couldn't do (e.g., "no food metadata available — suggest Ōrewa
     cafes generically").

Slot types: `place` | `travel_gap` | `meal_gap` | `buffer`.
"""

from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from aimetadata import parse  # noqa: E402
from registry import regions, settlements  # noqa: E402
from sanity_client import SanityClient  # noqa: E402
from services import google_maps  # noqa: E402
from tools.search_places import (  # noqa: E402
    NearFilter, SearchPlaceResult, SearchPlacesInput, search_places,
)


# =====================================================================
# Constants — tunable defaults
# =====================================================================

PACE_TARGET_SLOTS = {"relaxed": 2, "balanced": 3, "full": 4}
DEFAULT_DRIVE_KMH = 60.0
WINDING_FACTOR = 1.4
LUNCH_TARGET_HOUR = 12
LUNCH_DURATION_MIN = 60
DURATION_MINUTES_BY_BAND = {
    "sub_hour":     45,
    "1_to_2_hours": 90,
    "half_day":     180,
    "full_day":     360,
    "multi_day":    480,
    None:           75,         # default if duration unknown
}


# =====================================================================
# Public dataclasses
# =====================================================================


@dataclass
class BuildDayInput:
    base_location: str                                  # required
    region: str                                         # required (region-strict)
    pace: str = "balanced"                              # relaxed | balanced | full
    date: Optional[str] = None                          # YYYY-MM-DD; for seasonality filter
    start_time: str = "09:00"
    end_time: str = "17:00"

    # Filter menu — all optional, mirrors search_places
    themes: list[str] = field(default_factory=list)
    place_subtypes: list[str] = field(default_factory=list)
    physical_intensity_max: Optional[str] = None
    duration_bands: list[str] = field(default_factory=list)
    travelling_with: Optional[str] = None               # solo | couple | family | group (for soft prefs)
    budget_band: Optional[str] = None                   # currently informational only

    max_drive_minutes_between_stops: int = 30
    candidate_radius_km: float = 50.0                   # how far around base to search

    include_doc_ids: list[str] = field(default_factory=list)
    exclude_doc_ids: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)


@dataclass
class PlaceSlotData:
    sanity_doc_id: str
    title: str
    place_subtype: Optional[str]
    location_settlement: Optional[str]
    coords: Optional[dict]
    themes: list[str]
    physical_intensity: Optional[str]
    summary: str
    source_doc_score: float
    source_match_reasons: list[str]


@dataclass
class TravelGapData:
    from_settlement: Optional[str]
    to_settlement: Optional[str]
    from_coords: Optional[dict]
    to_coords: Optional[dict]
    estimated_km: float
    mode: str = "drive"


@dataclass
class MealGapData:
    meal: str                                           # lunch | dinner
    suggested_settlement: Optional[str]
    content_available: bool                             # always False until food metadata exists
    notes: str


@dataclass
class Slot:
    slot_index: int
    slot_type: str                                      # place | travel_gap | meal_gap | buffer
    start_time: str
    end_time: str
    duration_minutes: int
    place: Optional[PlaceSlotData] = None
    travel: Optional[TravelGapData] = None
    meal: Optional[MealGapData] = None
    notes: list[str] = field(default_factory=list)


@dataclass
class Feasibility:
    total_active_minutes: int
    total_idle_minutes: int
    longest_drive_minutes: int
    warnings: list[str] = field(default_factory=list)


@dataclass
class DayPlan:
    date: Optional[str]
    base_location: str
    base_coords: dict
    region: str
    start_time: str
    end_time: str
    pace: str
    slots: list[Slot]
    # GeoJSON FeatureCollection for the day's route — Point features for each
    # place + a LineString feature for the road-following polyline (when
    # Google Maps was reachable). Empty FeatureCollection if no places fit.
    route_geojson: dict = field(default_factory=lambda: {"type": "FeatureCollection", "features": []})


@dataclass
class BuildDayOutput:
    ok: bool
    query_echo: dict
    day_plan: Optional[DayPlan]
    assumptions: list[str]
    feasibility: Optional[Feasibility]
    unfilled_requests: list[str]
    candidate_pool_size: int
    latency_ms: int
    error_code: Optional[str] = None
    message: Optional[str] = None


# =====================================================================
# Public entry point
# =====================================================================


def build_day_itinerary(
    inp: BuildDayInput,
    client: Optional[SanityClient] = None,
) -> BuildDayOutput:
    started = time.monotonic()
    client = client or SanityClient()

    # 1) Resolve base location → coords
    base = settlements.resolve(inp.base_location, region=inp.region, client=client)
    if not base:
        return BuildDayOutput(
            ok=False,
            query_echo=_echo(inp),
            day_plan=None,
            assumptions=[],
            feasibility=None,
            unfilled_requests=[],
            candidate_pool_size=0,
            latency_ms=int((time.monotonic() - started) * 1000),
            error_code="UNRESOLVABLE_BASE_LOCATION",
            message=f"Could not resolve base_location {inp.base_location!r} in region {inp.region!r}.",
        )
    base_coords = {"lat": base.lat, "lng": base.lng}

    # 2) Build candidate pool
    if inp.include_doc_ids:
        candidates = _hydrate_pool_from_ids(client, inp.include_doc_ids)
    else:
        sp_in = SearchPlacesInput(
            region=inp.region,
            themes=inp.themes,
            place_subtypes=inp.place_subtypes,
            physical_intensity_max=inp.physical_intensity_max,
            duration_bands=inp.duration_bands,
            near=NearFilter(lat=base.lat, lng=base.lng, radius_km=inp.candidate_radius_km),
            limit=30,
        )
        sp_out = search_places(sp_in, client=client)
        if not sp_out.ok:
            return BuildDayOutput(
                ok=False,
                query_echo=_echo(inp),
                day_plan=None,
                assumptions=[],
                feasibility=None,
                unfilled_requests=[],
                candidate_pool_size=0,
                latency_ms=int((time.monotonic() - started) * 1000),
                error_code=sp_out.error_code or "NO_CANDIDATES",
                message=sp_out.message or "search_places returned no candidates",
            )
        candidates = sp_out.results

    # Filter excludes
    if inp.exclude_doc_ids:
        candidates = [c for c in candidates if c.sanity_doc_id not in inp.exclude_doc_ids]

    # 3) Greedy fill
    start_min = _hhmm_to_min(inp.start_time)
    end_min = _hhmm_to_min(inp.end_time)
    target_slots = PACE_TARGET_SLOTS.get(inp.pace, 3)

    slots: list[Slot] = []
    current_coords = base_coords
    current_settlement = base.name
    current_time = start_min
    used_ids: set[str] = set(inp.exclude_doc_ids)
    meal_inserted = False
    place_subtypes_used: list[str] = []
    longest_drive = 0
    place_count = 0

    while place_count < target_slots and current_time < end_min - 30:
        # Insert meal gap if we're approaching noon and haven't yet
        if not meal_inserted and current_time >= LUNCH_TARGET_HOUR * 60:
            meal_settlement = current_settlement or base.name
            slots.append(_make_meal_gap_slot(
                slot_index=len(slots),
                start_min=current_time,
                meal="lunch",
                suggested_settlement=meal_settlement,
            ))
            current_time += LUNCH_DURATION_MIN
            meal_inserted = True
            continue

        choice = _pick_best_candidate(
            candidates=candidates,
            current_coords=current_coords,
            current_time_min=current_time,
            end_time_min=end_min,
            used_ids=used_ids,
            place_subtypes_used=place_subtypes_used,
            max_drive_min=inp.max_drive_minutes_between_stops,
            meal_inserted=meal_inserted,
            is_first_pick=(place_count == 0),
        )
        if not choice:
            break
        cand, drive_min, visit_min = choice

        # Travel gap (only if ≥ 5 minutes drive)
        if drive_min >= 5:
            slots.append(_make_travel_gap_slot(
                slot_index=len(slots),
                start_min=current_time,
                duration_min=drive_min,
                from_settlement=current_settlement,
                to_settlement=cand.settlement,
                from_coords=current_coords,
                to_coords=cand.coords,
            ))
            current_time += drive_min
            longest_drive = max(longest_drive, drive_min)

        # Place slot
        slots.append(_make_place_slot(
            slot_index=len(slots),
            start_min=current_time,
            duration_min=visit_min,
            cand=cand,
        ))
        current_time += visit_min
        used_ids.add(cand.sanity_doc_id)
        if cand.place_subtype_derived:
            place_subtypes_used.append(cand.place_subtype_derived)
        current_coords = cand.coords or current_coords
        current_settlement = cand.settlement or current_settlement
        place_count += 1

    # If we never inserted lunch (e.g., pace=full and timing skipped past noon)
    if not meal_inserted and end_min - current_time >= LUNCH_DURATION_MIN:
        slots.append(_make_meal_gap_slot(
            slot_index=len(slots),
            start_min=current_time,
            meal="lunch",
            suggested_settlement=current_settlement or base.name,
        ))
        current_time += LUNCH_DURATION_MIN
        meal_inserted = True

    # 4) Feasibility
    total_active = sum(s.duration_minutes for s in slots if s.slot_type == "place")
    total_idle = sum(s.duration_minutes for s in slots
                     if s.slot_type in ("travel_gap", "meal_gap", "buffer"))
    feas = Feasibility(
        total_active_minutes=total_active,
        total_idle_minutes=total_idle,
        longest_drive_minutes=int(longest_drive),
    )

    # Warnings — tide/weather/no-content
    for slot in slots:
        if slot.slot_type == "place" and slot.place:
            # The aiMetadata-derived themes can flag tide_sensitive places via parser later
            # For now, flag long drives only.
            pass
    if longest_drive > 60:
        feas.warnings.append(
            f"Longest drive is {int(longest_drive)} min — consider relaxing pace or narrowing radius."
        )
    if place_count < target_slots:
        feas.warnings.append(
            f"Only {place_count} of {target_slots} target slots filled "
            f"(candidates exhausted within {inp.max_drive_minutes_between_stops}-min drive budget)."
        )

    # 5) Assumptions + unfilled requests
    assumptions = [
        "Self-drive assumed",
        "Drive times estimated from haversine × 1.4 / 60 km/h (no live routing)",
        f"Lunch placed at ~{LUNCH_TARGET_HOUR:02d}:00 (adjustable)" if meal_inserted else "No lunch slot included",
    ]
    if inp.date:
        assumptions.append(f"Date: {inp.date}")

    unfilled: list[str] = []
    if meal_inserted:
        unfilled.append(
            "Lunch recommendation: no food/restaurant metadata indexed yet — chat should suggest "
            f"cafes generically near the suggested settlement."
        )
    if not inp.include_doc_ids and len(candidates) < 5:
        unfilled.append(
            f"Thin candidate pool ({len(candidates)} places within {inp.candidate_radius_km}km). "
            "Consider broadening radius or removing filters."
        )

    plan = DayPlan(
        date=inp.date,
        base_location=base.name,
        base_coords=base_coords,
        region=inp.region,
        start_time=inp.start_time,
        end_time=inp.end_time,
        pace=inp.pace,
        slots=slots,
        route_geojson=_build_route_geojson(base_coords, slots),
    )
    return BuildDayOutput(
        ok=True,
        query_echo=_echo(inp),
        day_plan=plan,
        assumptions=assumptions,
        feasibility=feas,
        unfilled_requests=unfilled,
        candidate_pool_size=len(candidates),
        latency_ms=int((time.monotonic() - started) * 1000),
    )


# =====================================================================
# Helpers
# =====================================================================


def _echo(inp: BuildDayInput) -> dict:
    return {
        "base_location": inp.base_location,
        "region": inp.region,
        "pace": inp.pace,
        "date": inp.date,
        "start_time": inp.start_time,
        "end_time": inp.end_time,
        "themes": inp.themes,
        "place_subtypes": inp.place_subtypes,
        "physical_intensity_max": inp.physical_intensity_max,
        "duration_bands": inp.duration_bands,
        "max_drive_minutes_between_stops": inp.max_drive_minutes_between_stops,
        "candidate_radius_km": inp.candidate_radius_km,
        "include_doc_ids": inp.include_doc_ids,
        "exclude_doc_ids": inp.exclude_doc_ids,
        "constraints": inp.constraints,
    }


def _hhmm_to_min(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _min_to_hhmm(m: int) -> str:
    h, mm = divmod(int(round(m)), 60)
    return f"{h:02d}:{mm:02d}"


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _drive_minutes(from_coords: dict, to_coords: dict) -> float:
    """Minutes between two coords. Always haversine × 1.4 / 60 km/h.

    NOTE: We deliberately don't call Google Maps here even though we have the
    key. Greedy fill calls this 30+ times per day (once per candidate in
    `_pick_best_candidate`). At ~$0.005 per Directions call that'd add ~$0.15
    per day plan just for picking, with no real quality gain — the greedy
    algorithm just needs a "close enough" relative ranking. Google Maps gets
    invoked exactly ONCE per day in `_build_route_geojson` (and once per
    inter-day transition in build_trip_itinerary) for the visual polyline.
    """
    km = _haversine_km(from_coords["lat"], from_coords["lng"],
                       to_coords["lat"], to_coords["lng"]) * WINDING_FACTOR
    return (km / DEFAULT_DRIVE_KMH) * 60.0


def _build_route_geojson(base_coords: dict, slots: list[Slot]) -> dict:
    """Build a GeoJSON FeatureCollection for the day's route.

    Cost model: makes AT MOST ONE Google Maps Directions call for the whole
    day (origin = destination = base, waypoints = ordered place stops). Falls
    back to straight-line LineStrings if Google isn't configured or the call
    fails.

    Output features:
    - Point for the base (role="base")
    - Point per place slot (role="place")
    - Single LineString for the full route polyline (role="drive_route") —
      either Google's road-following overview, or a straight-line through
      the stops as fallback. Frontend renders this as one continuous path.

    GeoJSON coordinate order: [lng, lat]. Easy to flip; Google returns
    (lat, lng) so we flip on the way out.
    """
    features: list[dict] = []

    if base_coords and base_coords.get("lat") is not None:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [base_coords["lng"], base_coords["lat"]]},
            "properties": {"role": "base", "label": "Start / End"},
        })

    place_slots = [s for s in slots if s.slot_type == "place" and s.place and s.place.coords]

    for s in place_slots:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [s.place.coords["lng"], s.place.coords["lat"]],
            },
            "properties": {
                "role": "place",
                "slot_index": s.slot_index,
                "title": s.place.title,
                "subtype": s.place.place_subtype,
                "settlement": s.place.location_settlement,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "themes": s.place.themes,
            },
        })

    # Single LineString covering the whole loop (base → places → base)
    line_coords = _route_polyline(base_coords, [s.place.coords for s in place_slots])
    if line_coords:
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": line_coords},
            "properties": {
                "role": "drive_route",
                "stop_count": len(place_slots),
                "polyline_source": "google_directions" if google_maps.is_configured() else "straight_line",
            },
        })

    return {"type": "FeatureCollection", "features": features}


def _route_polyline(base_coords: dict, place_coords: list[dict]) -> list[list[float]]:
    """Get the full day's route polyline as [[lng,lat], ...] (GeoJSON order).

    Single call to Google Maps with the day's stops as waypoints; returns the
    overview polyline. Falls back to straight lines through the points when
    Google isn't available.
    """
    if not base_coords or base_coords.get("lat") is None:
        return []
    valid_places = [p for p in place_coords if p and p.get("lat") is not None]
    if not valid_places:
        return []

    # Try Google first
    if google_maps.is_configured():
        result = google_maps.directions(
            origin=(base_coords["lat"], base_coords["lng"]),
            destination=(base_coords["lat"], base_coords["lng"]),
            waypoints=[(p["lat"], p["lng"]) for p in valid_places],
        )
        if result and result.overview_polyline_points:
            return [[lng, lat] for (lat, lng) in result.overview_polyline_points]

    # Fallback: straight-line chain through all the stops
    chain = [base_coords] + valid_places + [base_coords]
    return [[c["lng"], c["lat"]] for c in chain]


def _pick_best_candidate(
    candidates: list[SearchPlaceResult],
    current_coords: dict,
    current_time_min: int,
    end_time_min: int,
    used_ids: set[str],
    place_subtypes_used: list[str],
    max_drive_min: int,
    meal_inserted: bool,
    is_first_pick: bool = False,
) -> Optional[tuple[SearchPlaceResult, float, int]]:
    """Return (candidate, drive_minutes, visit_minutes) of the best feasible pick, or None.

    `is_first_pick` triples the drive-time penalty so the day starts near the
    user's stated base. Without this, a high-scoring place far from base can
    win the first slot — e.g. asking for a "coastal day around Wellington CBD"
    used to land on Mākara Beach (12 km west, ~25 min drive) because its score
    edge outweighed a small 0.05/min penalty. Subsequent slots keep the normal
    penalty so road-trip days can still range widely once anchored.
    """
    best: Optional[tuple[SearchPlaceResult, float, int]] = None
    best_score = -math.inf
    drive_penalty_per_min = 0.15 if is_first_pick else 0.05

    for c in candidates:
        if c.sanity_doc_id in used_ids:
            continue
        if not c.coords:
            continue
        drive_min = _drive_minutes(current_coords, c.coords)
        if drive_min > max_drive_min:
            continue

        visit_min = DURATION_MINUTES_BY_BAND.get(c.duration_band, 75)
        # Allow the visit to fit within the day window
        if current_time_min + drive_min + visit_min > end_time_min - 15:
            continue

        # Score: search_places score minus drive penalty, plus diversity bonus
        score = c.score - (drive_min * drive_penalty_per_min)
        if c.place_subtype_derived and c.place_subtype_derived in place_subtypes_used:
            score -= 0.7
        if score > best_score:
            best_score = score
            best = (c, drive_min, visit_min)

    return best


def _make_place_slot(slot_index: int, start_min: int, duration_min: int,
                     cand: SearchPlaceResult) -> Slot:
    return Slot(
        slot_index=slot_index,
        slot_type="place",
        start_time=_min_to_hhmm(start_min),
        end_time=_min_to_hhmm(start_min + duration_min),
        duration_minutes=duration_min,
        place=PlaceSlotData(
            sanity_doc_id=cand.sanity_doc_id,
            title=cand.title,
            place_subtype=cand.place_subtype_derived,
            location_settlement=cand.settlement,
            coords=cand.coords,
            themes=cand.themes_derived,
            physical_intensity=cand.physical_intensity,
            summary=cand.summary,
            source_doc_score=cand.score,
            source_match_reasons=cand.match_reasons,
        ),
    )


def _make_travel_gap_slot(slot_index: int, start_min: int, duration_min: float,
                          from_settlement: Optional[str], to_settlement: Optional[str],
                          from_coords: Optional[dict], to_coords: Optional[dict]) -> Slot:
    km: float = 0.0
    if from_coords and to_coords:
        km = _haversine_km(from_coords["lat"], from_coords["lng"],
                           to_coords["lat"], to_coords["lng"])
    return Slot(
        slot_index=slot_index,
        slot_type="travel_gap",
        start_time=_min_to_hhmm(start_min),
        end_time=_min_to_hhmm(start_min + duration_min),
        duration_minutes=int(round(duration_min)),
        travel=TravelGapData(
            from_settlement=from_settlement,
            to_settlement=to_settlement,
            from_coords=from_coords,
            to_coords=to_coords,
            estimated_km=round(km, 1),
        ),
    )


def _make_meal_gap_slot(slot_index: int, start_min: int, meal: str,
                        suggested_settlement: Optional[str]) -> Slot:
    return Slot(
        slot_index=slot_index,
        slot_type="meal_gap",
        start_time=_min_to_hhmm(start_min),
        end_time=_min_to_hhmm(start_min + LUNCH_DURATION_MIN),
        duration_minutes=LUNCH_DURATION_MIN,
        meal=MealGapData(
            meal=meal,
            suggested_settlement=suggested_settlement,
            content_available=False,
            notes=(f"Food/restaurant content not yet indexed — chat should suggest "
                   f"cafes generically near {suggested_settlement!r}.") if suggested_settlement
                  else "Food content not yet indexed.",
        ),
    )


def _hydrate_pool_from_ids(client: SanityClient, ids: list[str]) -> list[SearchPlaceResult]:
    """Fetch a fixed set of pages by ID and adapt them to SearchPlaceResult shape."""
    docs = client.query(
        "*[_id in $ids]{_id, title, coordinates, aiMetadata, "
        '"tag_names": tags[]->name, "subRegion_name": subRegion->name, '
        '"region_name": subRegion->region->name}',
        params={"ids": ids},
    ) or []

    from tools.search_places import _derive_themes, _derive_place_subtype

    out: list[SearchPlaceResult] = []
    for d in docs:
        ai = parse(d.get("aiMetadata"))
        if ai.parse_error:
            continue
        tag_names = [t for t in (d.get("tag_names") or []) if t]
        out.append(SearchPlaceResult(
            sanity_doc_id=d["_id"],
            title=d.get("title") or "(untitled)",
            region=d.get("region_name") or "",
            subRegion=d.get("subRegion_name"),
            settlement=ai.settlement(),
            coords=d.get("coordinates"),
            themes_derived=_derive_themes(tag_names),
            place_subtype_derived=_derive_place_subtype(tag_names),
            physical_intensity=ai.physical_intensity_hint(),
            duration_band=ai.duration_band(),
            dog_friendly=ai.dog_friendly_kind,
            summary=(ai.description[:280] + "…") if len(ai.description) > 280 else ai.description,
            score=1.0,            # neutral; caller selected these explicitly
            match_reasons=["explicit include via include_doc_ids"],
        ))
    return out


# =====================================================================
# CLI smoke test
# =====================================================================


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    queries: list[BuildDayInput] = [
        BuildDayInput(
            base_location="Queenstown",
            region="Otago",
            pace="balanced",
            themes=["scenic"],
            candidate_radius_km=40,
        ),
        BuildDayInput(
            base_location="Wellington",
            region="Wellington",
            pace="relaxed",
            themes=["coastal", "heritage"],
            max_drive_minutes_between_stops=45,
            candidate_radius_km=60,
        ),
        BuildDayInput(
            base_location="Hibiscus Coast",
            region="Auckland",
            pace="full",
            themes=["coastal", "family"],
            place_subtypes=["beach", "walk"],
            candidate_radius_km=30,
        ),
    ]

    for q in queries:
        print(f"\n=== build_day_itinerary base={q.base_location!r}, region={q.region!r}, "
              f"pace={q.pace!r}, themes={q.themes} ===")
        out = build_day_itinerary(q)
        if not out.ok:
            print(f"  ERROR: {out.error_code}: {out.message}")
            continue
        plan = out.day_plan
        print(f"  Base: {plan.base_location} ({plan.base_coords['lat']:.3f}, {plan.base_coords['lng']:.3f})")
        print(f"  Pool: {out.candidate_pool_size} candidates, latency={out.latency_ms}ms")
        for s in plan.slots:
            if s.slot_type == "place" and s.place:
                tags_summary = "/".join(s.place.themes[:3])
                print(f"  [{s.start_time}-{s.end_time}] PLACE      {s.place.title:40s} "
                      f"({s.place.location_settlement or '—'}) themes={tags_summary}")
            elif s.slot_type == "travel_gap" and s.travel:
                print(f"  [{s.start_time}-{s.end_time}] travel     {s.travel.from_settlement or '—'} → "
                      f"{s.travel.to_settlement or '—'}  ({s.travel.estimated_km}km)")
            elif s.slot_type == "meal_gap" and s.meal:
                print(f"  [{s.start_time}-{s.end_time}] {s.meal.meal:8s}    suggest: {s.meal.suggested_settlement or '—'}")
        print(f"  Feasibility: active={out.feasibility.total_active_minutes}min, "
              f"idle={out.feasibility.total_idle_minutes}min, "
              f"longest_drive={out.feasibility.longest_drive_minutes}min")
        if out.feasibility.warnings:
            for w in out.feasibility.warnings:
                print(f"    ⚠ {w}")
        if out.unfilled_requests:
            print("  Unfilled:")
            for u in out.unfilled_requests:
                print(f"    · {u}")
