"""End-to-end demo of the *deterministic* portion of the planning_attributes
pipeline. Takes a Sanity page, applies registry + tag_mapping rules, and emits
a partial `planning_attributes` object. Whatever this script can't fill in is
what the LLM normalization prompt will have to derive from `aiMetadata` text.

Useful as a sanity check that the foundation pieces compose correctly, and as
a baseline to compare LLM output against.

Run:
    python execution/normalize/demo_deterministic_prepass.py
    python execution/normalize/demo_deterministic_prepass.py <sanity_doc_id>
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from sanity_client import SanityClient  # noqa: E402
from registry import regions  # noqa: E402
from normalize.tag_mapping import for_tag  # noqa: E402


SAMPLE_IDS = [
    "00268b0a-3b30-4d44-80a5-c7d1ec7d7b33",  # Te Hakapureirei Beach (Otago)
]


def deterministic_prepass(doc: dict) -> dict:
    """Build a partial planning_attributes from registry + tag_mapping signals.

    Returns a dict shaped like planning_attributes but with `null` for fields
    the deterministic pass can't decide (those are LLM territory).
    """
    place_subtype_votes: Counter[str] = Counter()
    themes: set[str] = set()
    suitability: dict[str, bool] = {}
    intensity_candidates: list[str] = []
    accessibility: dict[str, Any] = {}
    seasonality_hints: list[str] = []
    time_of_day: list[str] = []
    is_meta = False
    is_location_only = False
    activity_tags: list[str] = []
    accommodation_tags: list[str] = []

    tag_names: list[str] = [t for t in (doc.get("tag_names") or []) if t]
    for tag_name in tag_names:
        m = for_tag(tag_name)
        if m is None:
            # Unknown tag — should never happen if validate_against_live passes
            continue
        for s in m.place_subtype_hints:
            place_subtype_votes[s] += 1
        themes.update(m.themes)
        for k, v in m.suitability:
            suitability[k] = v
        if m.intensity_hint:
            intensity_candidates.append(m.intensity_hint)
        for k, v in m.accessibility:
            accessibility[k] = v
        if m.seasonality_hint:
            seasonality_hints.append(m.seasonality_hint)
        if m.time_of_day_hint:
            time_of_day.append(m.time_of_day_hint)
        if m.is_meta_tag:
            is_meta = True
        if m.is_location_tag:
            is_location_only = True
        if m.is_activity_tag:
            activity_tags.append(tag_name)
        if m.is_accommodation_tag:
            accommodation_tags.append(tag_name)

    # Place subtype: highest vote wins; ties broken by first-seen order
    place_subtype = place_subtype_votes.most_common(1)[0][0] if place_subtype_votes else None

    # Physical intensity: take the most demanding hit
    intensity_rank = {"none": 0, "easy": 1, "moderate": 2, "demanding": 3}
    physical_intensity: Optional[str] = None
    if intensity_candidates:
        physical_intensity = max(intensity_candidates, key=lambda x: intensity_rank.get(x, 0))

    # Seasonality: prefer most-restrictive
    seasonality: Optional[str] = None
    if seasonality_hints:
        season_rank = {"all_year": 0, "summer_best": 1, "winter_best": 1,
                       "tide_sensitive": 2, "weather_sensitive": 3}
        seasonality = max(seasonality_hints, key=lambda x: season_rank.get(x, 0))

    # Region/subRegion via Sanity refs
    sub_name = doc.get("subRegion")
    region_name = doc.get("region") or (regions.region_for_subRegion(sub_name) if sub_name else None)
    island = regions.island_for_subRegion(sub_name) if sub_name else (
        regions.island_for_region(region_name) if region_name else "Unknown"
    )

    coords = doc.get("coordinates") or {}
    lat = coords.get("lat")
    lng = coords.get("lng")

    return {
        "schema_version": "1.0",
        "content_kind": "place",
        "place_subtype": place_subtype,
        "place_subtype_alternatives": [s for s, _ in place_subtype_votes.most_common()][1:],
        "location_normalized": {
            "country": "NZ",
            "island": island,
            "region": region_name,
            "subRegion": sub_name,  # Sanity term; rename to district downstream if preferred
            "settlement": None,                                     # LLM to extract from aiMetadata
            "coords_present": lat is not None and lng is not None,
        },
        "themes": sorted(themes),
        "suitability": suitability,
        "physical_intensity": physical_intensity,
        "physical_intensity_source": "tag" if physical_intensity else None,
        "duration_band": None,                                       # LLM territory (parses track_trail_details)
        "budget_band": "free",                                       # default for editorial place content; LLM can override
        "seasonality": seasonality,
        "accessibility": accessibility,
        "time_of_day_hints": time_of_day,
        "activity_tags": activity_tags,
        "accommodation_tags": accommodation_tags,                    # non-empty → likely wrong content_kind
        "is_meta_classified": is_meta,
        "is_location_tag_only": is_location_only,
        "confidence": {
            # Deterministic pass has high confidence in what tags say but nothing else.
            "themes": 0.9 if themes else 0.0,
            "place_subtype": 0.9 if place_subtype else 0.0,
            "location": 0.95 if region_name else 0.3,
            "duration_band": 0.0,
            "intensity": 0.7 if physical_intensity else 0.0,
            "overall": 0.6 if (place_subtype and themes and region_name) else 0.3,
        },
        "deterministic_input": {
            "tag_names": tag_names,
            "raw_intensity_candidates": intensity_candidates,
            "raw_seasonality_hints": seasonality_hints,
        },
    }


def run_demo(client: SanityClient, doc_id: str) -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    doc = client.fetch_one(
        '*[_id == $id][0]{'
        '_id, title, coordinates, '
        '"tag_names": tags[]->name, '
        '"region": subRegion->region->name, '
        '"subRegion": subRegion->name, '
        'aiMetadata'
        '}',
        params={"id": doc_id},
    )
    if not doc:
        print(f"Doc {doc_id} not found.")
        return

    title = doc.get("title", "(untitled)")
    print(f"=== {title} ===")
    print(f"  region:    {doc.get('region')!r}")
    print(f"  subRegion: {doc.get('subRegion')!r}")
    print(f"  coords:    {doc.get('coordinates')}")
    print(f"  tag_names: {doc.get('tag_names')}")

    prepass = deterministic_prepass(doc)
    print()
    print("Deterministic pre-pass output:")
    print(json.dumps(prepass, ensure_ascii=False, indent=2))

    print()
    print("What LLM still needs to fill in (per planning_attributes schema):")
    pending = []
    if prepass["place_subtype"] is None:
        pending.append("place_subtype")
    if prepass["duration_band"] is None:
        pending.append("duration_band (parse track_trail_details.duration_text)")
    if not prepass["accessibility"]:
        pending.append("accessibility flags (parking, wheelchair, dog_friendly nuance)")
    pending.extend([
        "settlement (parse from aiMetadata.location)",
        "confidence.inference_notes (the LLM's audit trail)",
        "Any per-doc semantic refinement of themes / suitability",
    ])
    for p in pending:
        print(f"  - {p}")


if __name__ == "__main__":
    client = SanityClient()
    doc_ids = sys.argv[1:] or SAMPLE_IDS
    for doc_id in doc_ids:
        run_demo(client, doc_id)
        print()
