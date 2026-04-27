"""Anthropic tool-use schemas + dispatch for the Tripideas chat orchestrator.

Two responsibilities:
1. `TOOLS` — list of tool schemas in Anthropic's tool-use format (passed to
   the model so it knows what's callable and with what arguments).
2. `dispatch_tool(name, args)` — runs the right Python function from
   `execution.tools` and returns a JSON-serializable result dict the model
   can consume in its next turn.

Schemas mirror the dataclass inputs of the corresponding tools, with optional
fields documented inline so the model picks sensible defaults.
"""

from __future__ import annotations

import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

# Make execution/ importable regardless of CWD
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_EXECUTION_PATH = _PROJECT_ROOT / "execution"
if str(_EXECUTION_PATH) not in sys.path:
    sys.path.insert(0, str(_EXECUTION_PATH))

from sanity_client import SanityClient  # noqa: E402
from tools.build_day_itinerary import (  # noqa: E402
    BuildDayInput, build_day_itinerary,
)
from tools.build_trip_itinerary import (  # noqa: E402
    BuildTripInput, DayAnchor, build_trip_itinerary,
)
from tools.get_place_summary import get_place_summary  # noqa: E402
from tools.refine_itinerary import RefineInput, refine_itinerary  # noqa: E402
from tools.search_accommodation import (  # noqa: E402
    NearFilter as AccomNearFilter,
    SearchAccommodationInput,
    search_accommodation,
)
from tools.search_places import (  # noqa: E402
    NearFilter, SearchPlacesInput, search_places,
)


# =====================================================================
# Tool schemas (Anthropic tool-use format)
# =====================================================================

# Common enums reused across schemas
_THEMES = [
    "coastal", "forest", "alpine", "water", "geological", "protected_area",
    "heritage", "cultural", "wildlife", "family", "remote", "scenic",
    "adventure", "relaxation", "outdoors", "urban", "nature",
]
_PLACE_SUBTYPES = [
    "beach", "walk", "track", "boardwalk", "scenic_drive",
    "lake", "river", "mountain", "glacier", "waterfall",
    "cliff", "sea_cave", "island", "lagoon", "wetland", "forest",
    "national_park", "regional_park", "scenic_reserve", "marine_reserve",
    "lookout", "picnic_spot", "historic_site", "memorial", "museum",
    "art_gallery", "heritage_precinct", "bird_sanctuary", "botanic_garden",
    "cycle_trail",
]
_INTENSITIES = ["none", "easy", "moderate", "demanding"]
_DURATIONS = ["sub_hour", "1_to_2_hours", "half_day", "full_day", "multi_day"]
_PACES = ["relaxed", "balanced", "full"]
_CHANGE_TYPES = [
    "replace_slot", "remove_slot", "add_slot",
    "change_pace", "change_timing", "change_themes",
    "change_intensity", "change_budget", "broad_adjustment",
]
_ACCOMMODATION_TYPES = [
    "Budget/Backpackers",
    "Cabins/Cottages/Units/Houses",
    "Caravan Parks & Camping",
    "Chalets/Villas/Cottages",
    "Lodge",
    "Motel",
    "Studio/Apartments",
]


SEARCH_PLACES_SCHEMA = {
    "name": "search_places",
    "description": (
        "Find places in a NZ region matching optional filters. ALWAYS the first "
        "tool to call when the user mentions a region or wants to explore options. "
        "Returns up to `limit` ranked places with match_reasons and a summary. "
        "Use the `facets` in the response to narrow follow-up questions."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "region": {
                "type": "string",
                "description": "Required. NZ region name (e.g. 'Northland', 'Otago', 'Canterbury'). Resolve aliases first.",
            },
            "subRegion": {
                "type": "string",
                "description": "Optional. Narrow to a specific subRegion (e.g. 'Hibiscus Coast', 'Catlins').",
            },
            "themes": {
                "type": "array",
                "items": {"type": "string", "enum": _THEMES},
                "description": "Optional. Filter places matching these themes (any-match).",
            },
            "place_subtypes": {
                "type": "array",
                "items": {"type": "string", "enum": _PLACE_SUBTYPES},
                "description": "Optional. Filter for specific kinds of place.",
            },
            "physical_intensity_max": {
                "type": "string",
                "enum": _INTENSITIES,
                "description": "Optional. Cap on how strenuous the place is.",
            },
            "duration_bands": {
                "type": "array",
                "items": {"type": "string", "enum": _DURATIONS},
                "description": "Optional. Allowed visit-duration buckets.",
            },
            "dog_friendly_required": {
                "type": "boolean",
                "description": "Optional. If true, exclude places where dogs are not allowed.",
            },
            "near": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lng": {"type": "number"},
                    "radius_km": {"type": "number", "default": 30.0},
                },
                "required": ["lat", "lng"],
                "description": "Optional. Restrict to within radius_km of (lat,lng).",
            },
            "interests_text": {
                "type": "string",
                "description": "Optional free-form niche interest (e.g. 'rock pools', 'glow worms') — substring match against descriptions/attractions.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 30,
                "default": 10,
            },
        },
        "required": ["region"],
    },
}


GET_PLACE_SUMMARY_SCHEMA = {
    "name": "get_place_summary",
    "description": (
        "Get full details on one specific place by its Sanity document ID. Use this "
        "when the user asks for more info about a place mentioned in earlier search "
        "results or itineraries."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sanity_doc_id": {
                "type": "string",
                "description": "The _id of the Sanity page (returned by search_places / build_day_itinerary).",
            },
        },
        "required": ["sanity_doc_id"],
    },
}


BUILD_DAY_ITINERARY_SCHEMA = {
    "name": "build_day_itinerary",
    "description": (
        "Compose a single-day itinerary anchored at a base location. Returns "
        "typed slots: place / travel_gap / meal_gap. Use when the user has named "
        "a base + wants a day plan, OR after search_places when they pick a base."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "base_location": {
                "type": "string",
                "description": "Town, suburb, or area to anchor the day (e.g. 'Queenstown', 'Hibiscus Coast').",
            },
            "region": {
                "type": "string",
                "description": "NZ region the base sits in.",
            },
            "pace": {"type": "string", "enum": _PACES, "default": "balanced"},
            "date": {"type": "string", "description": "Optional YYYY-MM-DD."},
            "start_time": {"type": "string", "default": "09:00"},
            "end_time": {"type": "string", "default": "17:00"},
            "themes": {"type": "array", "items": {"type": "string", "enum": _THEMES}},
            "place_subtypes": {"type": "array", "items": {"type": "string", "enum": _PLACE_SUBTYPES}},
            "physical_intensity_max": {"type": "string", "enum": _INTENSITIES},
            "duration_bands": {"type": "array", "items": {"type": "string", "enum": _DURATIONS}},
            "travelling_with": {"type": "string", "enum": ["solo", "couple", "family", "group"]},
            "max_drive_minutes_between_stops": {"type": "integer", "default": 30},
            "candidate_radius_km": {"type": "number", "default": 50.0},
            "include_doc_ids": {
                "type": "array", "items": {"type": "string"},
                "description": "Optional. Pre-curated places (e.g. from prior search_places call) to use as the candidate pool.",
            },
            "exclude_doc_ids": {
                "type": "array", "items": {"type": "string"},
                "description": "Optional. Doc IDs to never propose (e.g. user already rejected).",
            },
            "constraints": {
                "type": "array", "items": {"type": "string"},
                "description": "Optional free-form hints from the user (e.g. 'baby naps at 1pm').",
            },
        },
        "required": ["base_location", "region"],
    },
}


BUILD_TRIP_ITINERARY_SCHEMA = {
    "name": "build_trip_itinerary",
    "description": (
        "Compose a multi-day trip by chaining day plans. Pass one DayAnchor per "
        "day with base_location + region (and optional per-day overrides). "
        "Enforces no-repeat across days. Returns days[], inter-day transitions, "
        "and a trip-level summary."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "day_anchors": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "base_location": {"type": "string"},
                        "region": {"type": "string"},
                        "date": {"type": "string"},
                        "label": {"type": "string", "description": "e.g. 'Day 1 — arrival'"},
                        "pace": {"type": "string", "enum": _PACES},
                        "themes": {"type": "array", "items": {"type": "string", "enum": _THEMES}},
                        "place_subtypes": {"type": "array", "items": {"type": "string", "enum": _PLACE_SUBTYPES}},
                        "physical_intensity_max": {"type": "string", "enum": _INTENSITIES},
                        "notes": {"type": "string"},
                    },
                    "required": ["base_location", "region"],
                },
                "description": "One entry per day. Order matters (chronological).",
            },
            "pace": {"type": "string", "enum": _PACES, "default": "balanced",
                     "description": "Trip-level default; per-anchor pace overrides this."},
            "themes": {"type": "array", "items": {"type": "string", "enum": _THEMES}},
            "place_subtypes": {"type": "array", "items": {"type": "string", "enum": _PLACE_SUBTYPES}},
            "physical_intensity_max": {"type": "string", "enum": _INTENSITIES},
            "travelling_with": {"type": "string", "enum": ["solo", "couple", "family", "group"]},
            "max_drive_minutes_between_stops": {"type": "integer", "default": 30},
            "candidate_radius_km": {"type": "number", "default": 50.0},
            "enforce_no_repeats": {"type": "boolean", "default": True},
        },
        "required": ["day_anchors"],
    },
}


REFINE_ITINERARY_SCHEMA = {
    "name": "refine_itinerary",
    "description": (
        "Adjust an existing day_plan based on user feedback. The chat must "
        "interpret the user's utterance into a structured `change_type` first. "
        "Returns updated_plan + diff. Stateless: the caller supplies preserve/reject "
        "doc_ids based on prior conversation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "existing_plan": {
                "type": "object",
                "description": "The DayPlan object returned by build_day_itinerary in a prior turn. Pass through verbatim.",
            },
            "change_type": {
                "type": "string",
                "enum": _CHANGE_TYPES,
                "description": (
                    "Pick one. replace/remove/add_slot need target_slot_index. "
                    "change_* perform a partial rebuild with the new constraint. "
                    "broad_adjustment is the catch-all for messy multi-axis requests."
                ),
            },
            "target_slot_index": {
                "type": "integer",
                "description": "0-based index into existing_plan.slots. Required for replace_/remove_/add_slot.",
            },
            "new_constraints": {
                "type": "object",
                "description": "Sparse overrides; keys map to BuildDayInput fields (pace, themes, physical_intensity_max, etc.).",
            },
            "preserve_doc_ids": {
                "type": "array", "items": {"type": "string"},
                "description": "Doc IDs of place slots the user explicitly liked; protect them from removal where possible.",
            },
            "reject_doc_ids": {
                "type": "array", "items": {"type": "string"},
                "description": "Doc IDs the user said no to; never propose again.",
            },
            "change_request_text": {
                "type": "string",
                "description": "The user's verbatim utterance, for logging.",
            },
        },
        "required": ["existing_plan", "change_type"],
    },
}


SEARCH_ACCOMMODATION_SCHEMA = {
    "name": "search_accommodation",
    "description": (
        "Find Tripideas accommodation listings (places to stay). Use this for "
        "lodging questions — *where to stay*, *find me a holiday park near X*, "
        "*Gold Medal places in Canterbury*, etc. NOT for sights or activities "
        "(use search_places for those). Each result includes a `book_link` to "
        "tripideas.nz/<slug> for the booking flow."
        "\n\n"
        "Important data note: the indexed accommodation pool is heavily "
        "skewed to 'Caravan Parks & Camping' (~94%) — only a handful of "
        "Motels (3), Backpackers (6), and 1 Lodge in the whole country. If a "
        "specific type filter returns 0 results, consider re-running without "
        "the type filter and surfacing what's actually there."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "region": {
                "type": "string",
                "description": "NZ region (e.g. 'Otago', 'Canterbury'). Resolved internally to a coordinate centroid + 80km radius — accommodation docs aren't tagged with our region taxonomy.",
            },
            "subRegion": {
                "type": "string",
                "description": "Optional. SubRegion name; resolved via page-coordinate means.",
            },
            "town": {
                "type": "string",
                "description": "Filter by the `town` field on the doc (e.g. 'Queenstown', 'Picton'). Substring match.",
            },
            "near": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lng": {"type": "number"},
                    "radius_km": {"type": "number", "default": 30.0},
                },
                "required": ["lat", "lng"],
                "description": "Optional explicit lat/lng anchor. Overrides region/subRegion resolution.",
            },
            "region_radius_km": {
                "type": "number",
                "default": 80.0,
                "description": "Radius applied when region/subRegion was resolved to a centroid.",
            },
            "accommodation_types": {
                "type": "array",
                "items": {"type": "string", "enum": _ACCOMMODATION_TYPES},
                "description": "Filter by accommodationType1 enum values (any-match).",
            },
            "min_review_rating": {
                "type": "number",
                "minimum": 1,
                "maximum": 5,
                "description": "e.g. 4.0 — exclude properties below this average review rating.",
            },
            "min_review_count": {
                "type": "integer",
                "minimum": 1,
                "description": "Exclude lightly-reviewed properties (only meaningful with min_review_rating).",
            },
            "star_rating_min": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "description": "Exclude properties below this official star rating. ~41% of docs are unrated; this filter excludes them too.",
            },
            "bookable_only": {
                "type": "boolean",
                "default": False,
                "description": "If true, only show properties where bookNowFlag is true (immediately bookable via Tripideas).",
            },
            "hot_deals_only": {
                "type": "boolean",
                "default": False,
                "description": "If true, only show properties currently marked as a hot deal.",
            },
            "gold_medal_only": {
                "type": "boolean",
                "default": False,
                "description": "If true, only Gold Medal properties (today's flag).",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 30,
                "default": 10,
            },
        },
    },
}


TOOLS = [
    SEARCH_PLACES_SCHEMA,
    GET_PLACE_SUMMARY_SCHEMA,
    BUILD_DAY_ITINERARY_SCHEMA,
    BUILD_TRIP_ITINERARY_SCHEMA,
    REFINE_ITINERARY_SCHEMA,
    SEARCH_ACCOMMODATION_SCHEMA,
]


# =====================================================================
# Dispatch — model picks a tool, we run it
# =====================================================================


def dispatch_tool(name: str, args: dict, client: SanityClient | None = None) -> dict:
    """Run the named tool with the given args. Returns a JSON-serializable dict.

    Errors (unknown tool, bad args) are returned in the result rather than raised
    so the model can recover gracefully.
    """
    client = client or SanityClient()

    try:
        if name == "search_places":
            inp = _make_search_places_input(args)
            out = search_places(inp, client=client)
        elif name == "get_place_summary":
            out = get_place_summary(args["sanity_doc_id"], client=client)
        elif name == "build_day_itinerary":
            inp = _make_build_day_input(args)
            out = build_day_itinerary(inp, client=client)
        elif name == "build_trip_itinerary":
            inp = _make_build_trip_input(args)
            out = build_trip_itinerary(inp, client=client)
        elif name == "refine_itinerary":
            inp = _make_refine_input(args)
            out = refine_itinerary(inp, client=client)
        elif name == "search_accommodation":
            inp = _make_search_accommodation_input(args)
            out = search_accommodation(inp, client=client)
        else:
            return {"ok": False, "error_code": "UNKNOWN_TOOL",
                    "message": f"No tool named {name!r}"}
    except Exception as e:
        return {"ok": False, "error_code": "TOOL_EXCEPTION",
                "message": f"{type(e).__name__}: {e}"}

    return _to_jsonable(out)


# =====================================================================
# Argument unpackers
# =====================================================================


def _make_search_places_input(args: dict) -> SearchPlacesInput:
    near = None
    if args.get("near"):
        near = NearFilter(
            lat=float(args["near"]["lat"]),
            lng=float(args["near"]["lng"]),
            radius_km=float(args["near"].get("radius_km", 30.0)),
        )
    return SearchPlacesInput(
        region=args["region"],
        subRegion=args.get("subRegion"),
        themes=args.get("themes", []) or [],
        place_subtypes=args.get("place_subtypes", []) or [],
        physical_intensity_max=args.get("physical_intensity_max"),
        duration_bands=args.get("duration_bands", []) or [],
        dog_friendly_required=bool(args.get("dog_friendly_required", False)),
        near=near,
        interests_text=args.get("interests_text"),
        limit=int(args.get("limit", 10)),
    )


def _make_build_day_input(args: dict) -> BuildDayInput:
    return BuildDayInput(
        base_location=args["base_location"],
        region=args["region"],
        pace=args.get("pace", "balanced"),
        date=args.get("date"),
        start_time=args.get("start_time", "09:00"),
        end_time=args.get("end_time", "17:00"),
        themes=args.get("themes", []) or [],
        place_subtypes=args.get("place_subtypes", []) or [],
        physical_intensity_max=args.get("physical_intensity_max"),
        duration_bands=args.get("duration_bands", []) or [],
        travelling_with=args.get("travelling_with"),
        budget_band=args.get("budget_band"),
        max_drive_minutes_between_stops=int(args.get("max_drive_minutes_between_stops", 30)),
        candidate_radius_km=float(args.get("candidate_radius_km", 50.0)),
        include_doc_ids=args.get("include_doc_ids", []) or [],
        exclude_doc_ids=args.get("exclude_doc_ids", []) or [],
        constraints=args.get("constraints", []) or [],
    )


def _make_build_trip_input(args: dict) -> BuildTripInput:
    anchors = [
        DayAnchor(
            base_location=a["base_location"],
            region=a["region"],
            date=a.get("date"),
            label=a.get("label"),
            pace=a.get("pace"),
            themes=a.get("themes"),
            place_subtypes=a.get("place_subtypes"),
            physical_intensity_max=a.get("physical_intensity_max"),
            notes=a.get("notes"),
        )
        for a in args.get("day_anchors", [])
    ]
    return BuildTripInput(
        day_anchors=anchors,
        pace=args.get("pace", "balanced"),
        themes=args.get("themes", []) or [],
        place_subtypes=args.get("place_subtypes", []) or [],
        physical_intensity_max=args.get("physical_intensity_max"),
        travelling_with=args.get("travelling_with"),
        max_drive_minutes_between_stops=int(args.get("max_drive_minutes_between_stops", 30)),
        candidate_radius_km=float(args.get("candidate_radius_km", 50.0)),
        enforce_no_repeats=bool(args.get("enforce_no_repeats", True)),
    )


def _make_refine_input(args: dict) -> RefineInput:
    # The model passes existing_plan as a dict; reconstruct the DayPlan dataclass
    from tools.build_day_itinerary import (
        DayPlan, MealGapData, PlaceSlotData, Slot, TravelGapData,
    )

    raw_plan = args["existing_plan"]
    slots: list[Slot] = []
    for s in raw_plan.get("slots", []):
        place = None
        travel = None
        meal = None
        if s.get("place"):
            place = PlaceSlotData(**s["place"])
        if s.get("travel"):
            travel = TravelGapData(**s["travel"])
        if s.get("meal"):
            meal = MealGapData(**s["meal"])
        slots.append(Slot(
            slot_index=s["slot_index"],
            slot_type=s["slot_type"],
            start_time=s["start_time"],
            end_time=s["end_time"],
            duration_minutes=s["duration_minutes"],
            place=place, travel=travel, meal=meal,
            notes=s.get("notes", []) or [],
        ))
    plan = DayPlan(
        date=raw_plan.get("date"),
        base_location=raw_plan["base_location"],
        base_coords=raw_plan["base_coords"],
        region=raw_plan["region"],
        start_time=raw_plan["start_time"],
        end_time=raw_plan["end_time"],
        pace=raw_plan["pace"],
        slots=slots,
    )
    return RefineInput(
        existing_plan=plan,
        change_type=args["change_type"],
        target_slot_index=args.get("target_slot_index"),
        new_constraints=args.get("new_constraints", {}) or {},
        preserve_doc_ids=args.get("preserve_doc_ids", []) or [],
        reject_doc_ids=args.get("reject_doc_ids", []) or [],
        change_request_text=args.get("change_request_text"),
    )


def _make_search_accommodation_input(args: dict) -> SearchAccommodationInput:
    near = None
    if args.get("near"):
        near = AccomNearFilter(
            lat=float(args["near"]["lat"]),
            lng=float(args["near"]["lng"]),
            radius_km=float(args["near"].get("radius_km", 30.0)),
        )
    return SearchAccommodationInput(
        region=args.get("region"),
        subRegion=args.get("subRegion"),
        town=args.get("town"),
        near=near,
        region_radius_km=float(args.get("region_radius_km", 80.0)),
        accommodation_types=args.get("accommodation_types", []) or [],
        min_review_rating=(
            float(args["min_review_rating"]) if args.get("min_review_rating") is not None else None
        ),
        min_review_count=(
            int(args["min_review_count"]) if args.get("min_review_count") is not None else None
        ),
        star_rating_min=(
            int(args["star_rating_min"]) if args.get("star_rating_min") is not None else None
        ),
        bookable_only=bool(args.get("bookable_only", False)),
        hot_deals_only=bool(args.get("hot_deals_only", False)),
        gold_medal_only=bool(args.get("gold_medal_only", False)),
        limit=int(args.get("limit", 10)),
    )


# =====================================================================
# Result serialization (recursive dataclass → dict)
# =====================================================================


def _to_jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if is_dataclass(obj) and not isinstance(obj, type):
        return _to_jsonable(asdict(obj))
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_jsonable(v) for v in obj]
    # Fallback for unexpected types — string-ify
    return str(obj)


__all__ = ["TOOLS", "dispatch_tool"]
