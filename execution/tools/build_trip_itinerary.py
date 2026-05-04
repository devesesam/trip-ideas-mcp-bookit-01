"""`build_trip_itinerary` — chain N day plans into a multi-day trip.

The chat orchestrator hands us a list of day anchors (one per day, each
with a base_location + region + optional per-day overrides). We build each
day via `build_day_itinerary`, accumulating used place IDs to prevent
repeats across days, then compute inter-day transitions and a trip-level
summary.

This is a thin coordinator — it doesn't re-implement day planning. All
the day-level intelligence stays in `build_day_itinerary`.

Pattern in the brief:
- *"Plan a relaxed South Island itinerary for 7 days"* → orchestrator
  picks 7 anchors, calls this tool with those anchors + relaxed pace.
- *"4-day road trip Nelson to Christchurch"* → orchestrator picks 4
  anchors along the route (Nelson, Picton, Kaikoura, Christchurch) and
  calls this tool.
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

from sanity_client import SanityClient  # noqa: E402
from services import google_maps  # noqa: E402
from tools.build_day_itinerary import (  # noqa: E402
    BuildDayInput, DayPlan, Slot, build_day_itinerary,
    DEFAULT_DRIVE_KMH, WINDING_FACTOR,
)


# =====================================================================
# Public dataclasses
# =====================================================================


@dataclass
class DayAnchor:
    """One day's worth of input. Per-day fields override trip-level defaults
    when set; None falls back to the trip-level value."""
    base_location: str
    region: str
    date: Optional[str] = None
    label: Optional[str] = None                          # e.g. "Day 1 — arrival"
    pace: Optional[str] = None
    themes: Optional[list[str]] = None
    place_subtypes: Optional[list[str]] = None
    physical_intensity_max: Optional[str] = None
    duration_bands: Optional[list[str]] = None
    max_drive_minutes_between_stops: Optional[int] = None
    candidate_radius_km: Optional[float] = None
    notes: Optional[str] = None                          # free-form context for the day


@dataclass
class BuildTripInput:
    day_anchors: list[DayAnchor]                         # required, at least 1

    # Trip-level defaults
    pace: str = "balanced"
    themes: list[str] = field(default_factory=list)
    place_subtypes: list[str] = field(default_factory=list)
    physical_intensity_max: Optional[str] = None
    duration_bands: list[str] = field(default_factory=list)
    travelling_with: Optional[str] = None
    budget_band: Optional[str] = None
    max_drive_minutes_between_stops: int = 30
    candidate_radius_km: float = 50.0

    # Cross-day variety
    enforce_no_repeats: bool = True

    # Session state from chat orchestrator
    preserve_doc_ids: list[str] = field(default_factory=list)
    reject_doc_ids: list[str] = field(default_factory=list)


@dataclass
class TripDay:
    day_index: int
    date: Optional[str]
    label: Optional[str]
    base_location: str
    region: str
    day_plan: Optional[DayPlan]
    feasibility: Optional[Any]
    candidate_pool_size: int
    unfilled_requests: list[str]
    error_code: Optional[str] = None
    message: Optional[str] = None


@dataclass
class InterDayTransition:
    from_day_index: int
    to_day_index: int
    from_settlement: Optional[str]
    to_settlement: Optional[str]
    from_coords: Optional[dict]
    to_coords: Optional[dict]
    estimated_km: float
    estimated_drive_minutes: int
    drive_source: str = "haversine"
    """How the drive estimate was computed: "google_directions" or "haversine"."""
    polyline_points: list[list[float]] = field(default_factory=list)
    """Decoded road-following polyline as [[lng,lat], ...] (GeoJSON order).
    Empty when Google Maps wasn't reachable. Powers the inter-day
    LineString in the trip-wide GeoJSON."""


@dataclass
class TripSummary:
    total_days: int
    total_places: int
    total_active_minutes: int
    total_within_day_drive_minutes: int
    total_inter_day_drive_minutes: int
    themes_covered: list[str]
    place_subtypes_covered: list[str]
    settlements_visited: list[str]
    highlight_titles: list[str]                          # top-scored places across all days
    days_with_warnings: int


@dataclass
class BuildTripOutput:
    ok: bool
    query_echo: dict
    days: list[TripDay]
    transitions: list[InterDayTransition]
    summary: Optional[TripSummary]
    unresolved_constraints: list[str]
    latency_ms: int
    route_geojson: dict = field(default_factory=lambda: {"type": "FeatureCollection", "features": []})
    """Trip-wide GeoJSON FeatureCollection. Combines per-day Point/LineString
    features (each tagged with day_index) plus inter-day transition
    LineStrings. The frontend can render this as one map of the whole trip."""
    error_code: Optional[str] = None
    message: Optional[str] = None


# =====================================================================
# Public entry point
# =====================================================================


def build_trip_itinerary(
    inp: BuildTripInput,
    client: Optional[SanityClient] = None,
) -> BuildTripOutput:
    started = time.monotonic()
    client = client or SanityClient()

    if not inp.day_anchors:
        return _error(inp, started, "NO_DAY_ANCHORS",
                      "build_trip_itinerary requires at least one day_anchor")

    used_doc_ids: set[str] = set(inp.reject_doc_ids)
    days: list[TripDay] = []
    unresolved_aggregate: list[str] = []

    # --- Build each day ---
    for i, anchor in enumerate(inp.day_anchors):
        # Compose per-day input from trip-level + per-day overrides
        day_in = BuildDayInput(
            base_location=anchor.base_location,
            region=anchor.region,
            date=anchor.date,
            pace=anchor.pace or inp.pace,
            themes=anchor.themes if anchor.themes is not None else inp.themes,
            place_subtypes=(anchor.place_subtypes
                            if anchor.place_subtypes is not None
                            else inp.place_subtypes),
            physical_intensity_max=(anchor.physical_intensity_max
                                    if anchor.physical_intensity_max is not None
                                    else inp.physical_intensity_max),
            duration_bands=(anchor.duration_bands
                            if anchor.duration_bands is not None
                            else inp.duration_bands),
            travelling_with=inp.travelling_with,
            budget_band=inp.budget_band,
            max_drive_minutes_between_stops=(anchor.max_drive_minutes_between_stops
                                             or inp.max_drive_minutes_between_stops),
            candidate_radius_km=(anchor.candidate_radius_km
                                 or inp.candidate_radius_km),
            include_doc_ids=list(inp.preserve_doc_ids),
            exclude_doc_ids=(list(used_doc_ids) if inp.enforce_no_repeats
                             else list(inp.reject_doc_ids)),
            constraints=[anchor.notes] if anchor.notes else [],
        )

        day_out = build_day_itinerary(day_in, client=client)

        if not day_out.ok:
            days.append(TripDay(
                day_index=i, date=anchor.date, label=anchor.label,
                base_location=anchor.base_location, region=anchor.region,
                day_plan=None, feasibility=None, candidate_pool_size=0,
                unfilled_requests=[], error_code=day_out.error_code,
                message=day_out.message,
            ))
            unresolved_aggregate.append(
                f"Day {i + 1} ({anchor.base_location}): {day_out.error_code} — {day_out.message}"
            )
            continue

        days.append(TripDay(
            day_index=i,
            date=anchor.date,
            label=anchor.label,
            base_location=anchor.base_location,
            region=anchor.region,
            day_plan=day_out.day_plan,
            feasibility=day_out.feasibility,
            candidate_pool_size=day_out.candidate_pool_size,
            unfilled_requests=day_out.unfilled_requests,
        ))

        # Track place IDs used so subsequent days don't repeat
        if inp.enforce_no_repeats and day_out.day_plan:
            for slot in day_out.day_plan.slots:
                if slot.slot_type == "place" and slot.place:
                    used_doc_ids.add(slot.place.sanity_doc_id)

    # --- Inter-day transitions (Google Maps when configured, haversine fallback) ---
    transitions: list[InterDayTransition] = []
    for a, b in zip(days, days[1:]):
        if not a.day_plan or not b.day_plan:
            continue
        a_end = _last_place_coords(a.day_plan)
        b_start = _first_place_coords(b.day_plan) or b.day_plan.base_coords
        if a_end and b_start:
            transitions.append(_compute_transition(a, b, a_end, b_start))

    # --- Trip summary + trip-wide route GeoJSON ---
    summary = _summarize(days, transitions)
    trip_route_geojson = _build_trip_geojson(days, transitions)

    return BuildTripOutput(
        ok=True,
        query_echo=_echo(inp),
        days=days,
        transitions=transitions,
        summary=summary,
        unresolved_constraints=unresolved_aggregate,
        latency_ms=int((time.monotonic() - started) * 1000),
        route_geojson=trip_route_geojson,
    )


# =====================================================================
# Helpers
# =====================================================================


def _echo(inp: BuildTripInput) -> dict:
    return {
        "anchors": [{"base_location": a.base_location, "region": a.region,
                     "date": a.date, "label": a.label, "pace_override": a.pace,
                     "themes_override": a.themes}
                    for a in inp.day_anchors],
        "trip_defaults": {
            "pace": inp.pace, "themes": inp.themes,
            "place_subtypes": inp.place_subtypes,
            "physical_intensity_max": inp.physical_intensity_max,
            "max_drive_minutes_between_stops": inp.max_drive_minutes_between_stops,
        },
        "enforce_no_repeats": inp.enforce_no_repeats,
        "preserve_doc_ids": inp.preserve_doc_ids,
        "reject_doc_ids": inp.reject_doc_ids,
    }


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _last_place_coords(plan: DayPlan) -> Optional[dict]:
    for s in reversed(plan.slots):
        if s.slot_type == "place" and s.place and s.place.coords:
            return s.place.coords
    return plan.base_coords


def _first_place_coords(plan: DayPlan) -> Optional[dict]:
    for s in plan.slots:
        if s.slot_type == "place" and s.place and s.place.coords:
            return s.place.coords
    return None


def _last_place_settlement(plan: DayPlan) -> Optional[str]:
    for s in reversed(plan.slots):
        if s.slot_type == "place" and s.place:
            return s.place.location_settlement or plan.base_location
    return plan.base_location


def _first_place_settlement(plan: DayPlan) -> Optional[str]:
    for s in plan.slots:
        if s.slot_type == "place" and s.place:
            return s.place.location_settlement
    return None


def _compute_transition(
    a: TripDay, b: TripDay, a_end: dict, b_start: dict,
) -> InterDayTransition:
    """Compute the transition between two consecutive days.

    Tries Google Maps Directions for an accurate drive time + road-following
    polyline; falls back to haversine × WINDING_FACTOR / DEFAULT_DRIVE_KMH on
    any failure (key missing, API error, non-OK status).

    The polyline is stored as [[lng, lat], ...] (GeoJSON coordinate order)
    so the trip-wide FeatureCollection can drop it straight into a
    LineString geometry without further transformation.
    """
    from_settlement = _last_place_settlement(a.day_plan) if a.day_plan else None
    to_settlement = _first_place_settlement(b.day_plan) if b.day_plan else None
    if not to_settlement and b.day_plan:
        to_settlement = b.day_plan.base_location

    drive_source = "haversine"
    polyline_points: list[list[float]] = []
    estimated_km: float
    estimated_drive_minutes: int

    result = google_maps.directions(
        origin=(a_end["lat"], a_end["lng"]),
        destination=(b_start["lat"], b_start["lng"]),
    )
    if result is not None:
        drive_source = "google_directions"
        estimated_km = round(result.total_distance_km, 1)
        estimated_drive_minutes = result.total_duration_min
        polyline_points = [[lng, lat] for lat, lng in result.overview_polyline_points]
    else:
        km = _haversine_km(a_end["lat"], a_end["lng"], b_start["lat"], b_start["lng"])
        estimated_km = round(km * WINDING_FACTOR, 1)
        estimated_drive_minutes = int(round(estimated_km / DEFAULT_DRIVE_KMH * 60))

    return InterDayTransition(
        from_day_index=a.day_index,
        to_day_index=b.day_index,
        from_settlement=from_settlement,
        to_settlement=to_settlement,
        from_coords=a_end,
        to_coords=b_start,
        estimated_km=estimated_km,
        estimated_drive_minutes=estimated_drive_minutes,
        drive_source=drive_source,
        polyline_points=polyline_points,
    )


def _build_trip_geojson(
    days: list[TripDay], transitions: list[InterDayTransition],
) -> dict:
    """Aggregate per-day route features + inter-day transition LineStrings
    into a single FeatureCollection.

    Each day's existing features get their `properties.day_index` stamped
    so the frontend can colour-code by day. Inter-day transitions become
    LineString features with `role="inter_day_drive"`.

    Coordinate order is [lng, lat] throughout (GeoJSON convention, matches
    what `_build_route_geojson` produces in build_day_itinerary).
    """
    features: list[dict] = []

    for d in days:
        if not d.day_plan:
            continue
        day_fc = d.day_plan.route_geojson or {}
        for feat in day_fc.get("features", []):
            tagged = {
                **feat,
                "properties": {
                    **(feat.get("properties") or {}),
                    "day_index": d.day_index,
                },
            }
            features.append(tagged)

    for t in transitions:
        if t.polyline_points:
            line_coords = t.polyline_points
        elif t.from_coords and t.to_coords:
            line_coords = [
                [t.from_coords["lng"], t.from_coords["lat"]],
                [t.to_coords["lng"], t.to_coords["lat"]],
            ]
        else:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": line_coords},
            "properties": {
                "role": "inter_day_drive",
                "from_day_index": t.from_day_index,
                "to_day_index": t.to_day_index,
                "from_settlement": t.from_settlement,
                "to_settlement": t.to_settlement,
                "estimated_km": t.estimated_km,
                "estimated_drive_minutes": t.estimated_drive_minutes,
                "polyline_source": t.drive_source,
            },
        })

    return {"type": "FeatureCollection", "features": features}


def _summarize(days: list[TripDay], transitions: list[InterDayTransition]) -> TripSummary:
    total_places = 0
    total_active = 0
    total_within_drive = 0
    themes_counter: Counter[str] = Counter()
    subtypes_counter: Counter[str] = Counter()
    settlements: list[str] = []
    highlights: list[tuple[float, str]] = []
    days_with_warnings = 0

    for d in days:
        if not d.day_plan:
            continue
        for s in d.day_plan.slots:
            if s.slot_type == "place" and s.place:
                total_places += 1
                total_active += s.duration_minutes
                themes_counter.update(s.place.themes)
                if s.place.place_subtype:
                    subtypes_counter[s.place.place_subtype] += 1
                if s.place.location_settlement:
                    settlements.append(s.place.location_settlement)
                highlights.append((s.place.source_doc_score, s.place.title))
            elif s.slot_type == "travel_gap":
                total_within_drive += s.duration_minutes
        if d.feasibility and d.feasibility.warnings:
            days_with_warnings += 1

    total_inter_drive = sum(t.estimated_drive_minutes for t in transitions)

    # Dedupe settlements while preserving order of first appearance
    seen: set[str] = set()
    unique_settlements: list[str] = []
    for s in settlements:
        if s not in seen:
            seen.add(s)
            unique_settlements.append(s)

    highlights.sort(reverse=True)
    highlight_titles = [t for _, t in highlights[:5]]

    return TripSummary(
        total_days=len(days),
        total_places=total_places,
        total_active_minutes=total_active,
        total_within_day_drive_minutes=total_within_drive,
        total_inter_day_drive_minutes=total_inter_drive,
        themes_covered=[t for t, _ in themes_counter.most_common()],
        place_subtypes_covered=[s for s, _ in subtypes_counter.most_common()],
        settlements_visited=unique_settlements,
        highlight_titles=highlight_titles,
        days_with_warnings=days_with_warnings,
    )


def _error(inp: BuildTripInput, started: float, code: str, msg: str) -> BuildTripOutput:
    return BuildTripOutput(
        ok=False, query_echo=_echo(inp), days=[], transitions=[],
        summary=None, unresolved_constraints=[],
        latency_ms=int((time.monotonic() - started) * 1000),
        error_code=code, message=msg,
    )


# =====================================================================
# CLI smoke test — exercises both convergence patterns
# =====================================================================


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    client = SanityClient()

    # ---------- TRIP 1: 4-day road trip Nelson → Christchurch ----------
    print("=" * 78)
    print("  TRIP 1 — 4-day road trip Nelson → Christchurch")
    print("=" * 78)
    trip1 = build_trip_itinerary(BuildTripInput(
        day_anchors=[
            DayAnchor(base_location="Nelson", region="Nelson Tasman",
                      label="Day 1 — arrival", pace="relaxed"),
            DayAnchor(base_location="Picton", region="Marlborough",
                      label="Day 2 — Marlborough Sounds", themes=["coastal"]),
            DayAnchor(base_location="Kaikoura", region="Canterbury",
                      label="Day 3 — coastal wildlife", themes=["coastal", "wildlife"]),
            DayAnchor(base_location="Christchurch", region="Canterbury",
                      label="Day 4 — city + heritage",
                      themes=["urban", "heritage"], pace="balanced"),
        ],
        pace="balanced",
        candidate_radius_km=40,
    ), client=client)

    print(f"\nLatency: {trip1.latency_ms}ms\n")
    if not trip1.ok:
        print(f"ERROR: {trip1.error_code}: {trip1.message}")
    else:
        for d in trip1.days:
            print(f"--- {d.label or f'Day {d.day_index + 1}'} — {d.base_location} ({d.region}) ---")
            if d.error_code:
                print(f"   ERROR: {d.error_code}: {d.message}")
                continue
            for s in (d.day_plan.slots if d.day_plan else []):
                if s.slot_type == "place" and s.place:
                    print(f"   [{s.start_time}] {s.place.title:40s} ({s.place.location_settlement or '—'}) "
                          f"themes={s.place.themes[:3]}")
                elif s.slot_type == "travel_gap" and s.travel:
                    print(f"   [{s.start_time}] travel  → {s.travel.to_settlement or '—'} "
                          f"({s.travel.estimated_km}km)")
                elif s.slot_type == "meal_gap" and s.meal:
                    print(f"   [{s.start_time}] lunch ({s.meal.suggested_settlement or '—'})")
        print()
        if trip1.transitions:
            print("Inter-day transitions:")
            for t in trip1.transitions:
                print(f"   Day {t.from_day_index + 1} → Day {t.to_day_index + 1}: "
                      f"{t.from_settlement} → {t.to_settlement} "
                      f"({t.estimated_km}km, ~{t.estimated_drive_minutes}min)")
        print()
        s = trip1.summary
        print(f"Trip summary:")
        print(f"   Days: {s.total_days}, Places: {s.total_places}")
        print(f"   Active: {s.total_active_minutes // 60}h {s.total_active_minutes % 60}m")
        print(f"   Drive (within days): {s.total_within_day_drive_minutes}min")
        print(f"   Drive (between days): {s.total_inter_day_drive_minutes}min")
        print(f"   Themes covered: {s.themes_covered[:8]}")
        print(f"   Settlements: {s.settlements_visited[:10]}")
        print(f"   Highlights: {s.highlight_titles}")

    # ---------- TRIP 2: 3-day Otago, mixed themes per day ----------
    print()
    print("=" * 78)
    print("  TRIP 2 — 3-day Otago: alpine + lakes + city")
    print("=" * 78)
    trip2 = build_trip_itinerary(BuildTripInput(
        day_anchors=[
            DayAnchor(base_location="Queenstown", region="Otago",
                      label="Day 1 — alpine", themes=["alpine", "scenic"]),
            DayAnchor(base_location="Wanaka", region="Otago",
                      label="Day 2 — lakes", themes=["water", "scenic"]),
            DayAnchor(base_location="Dunedin", region="Otago",
                      label="Day 3 — city + heritage", themes=["urban", "heritage"]),
        ],
        pace="balanced",
        candidate_radius_km=40,
    ), client=client)

    print(f"\nLatency: {trip2.latency_ms}ms\n")
    if not trip2.ok:
        print(f"ERROR: {trip2.error_code}: {trip2.message}")
    else:
        for d in trip2.days:
            print(f"--- {d.label or f'Day {d.day_index + 1}'} — {d.base_location} ---")
            if d.error_code:
                print(f"   ERROR: {d.error_code}: {d.message}")
                continue
            for s in (d.day_plan.slots if d.day_plan else []):
                if s.slot_type == "place" and s.place:
                    print(f"   [{s.start_time}] {s.place.title:40s} themes={s.place.themes[:3]}")
                elif s.slot_type == "meal_gap" and s.meal:
                    print(f"   [{s.start_time}] lunch")
        print()
        s = trip2.summary
        print(f"Trip summary:")
        print(f"   {s.total_days} days, {s.total_places} places, themes={s.themes_covered[:6]}")
        print(f"   Repeats prevented: enforce_no_repeats=True, "
              f"used_ids would have grown across days.")
