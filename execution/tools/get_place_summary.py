"""`get_place_summary` — return everything we know about a single place.

Used when the chat needs detail on a specific result (e.g., user picks one
from search_places results and wants to know more before adding it to a day).

Output is a flat dict of:
- Core fields (title, slug, coords, region/subRegion)
- Derived signals (place_subtype, themes, physical_intensity, duration_band)
- The full parsed aiMetadata view (description, attractions, activities,
  amenities, accessibility notes, local_tips, ideal_for, nearby_places, etc.)

Does NOT call an LLM. Reads one Sanity doc, parses aiMetadata, returns.
"""

from __future__ import annotations

import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from aimetadata import parse  # noqa: E402
from sanity_client import SanityClient  # noqa: E402
from tools.search_places import _derive_place_subtype, _derive_themes  # noqa: E402


@dataclass
class GetPlaceSummaryOutput:
    ok: bool
    sanity_doc_id: str = ""
    title: str = ""
    slug: Optional[str] = None
    region: Optional[str] = None
    subRegion: Optional[str] = None
    settlement: Optional[str] = None
    coords: Optional[dict] = None

    place_subtype: Optional[str] = None
    themes: list[str] = field(default_factory=list)
    physical_intensity: Optional[str] = None
    duration_band: Optional[str] = None
    dog_friendly_kind: str = "unknown"

    description: str = ""
    attractions: list[str] = field(default_factory=list)
    activities: list[str] = field(default_factory=list)
    amenities: list[str] = field(default_factory=list)
    accessibility_notes: list[str] = field(default_factory=list)
    transportation: list[str] = field(default_factory=list)
    local_tips: list[str] = field(default_factory=list)
    ideal_for: list[str] = field(default_factory=list)
    nearby_places: list[dict] = field(default_factory=list)
    track_trail: Optional[dict] = None
    best_time_to_visit: list[str] = field(default_factory=list)
    water_safety_notes: list[str] = field(default_factory=list)
    historical_significance: list[str] = field(default_factory=list)

    tag_names: list[str] = field(default_factory=list)
    parse_error: bool = False
    parse_error_message: Optional[str] = None
    latency_ms: int = 0
    error_code: Optional[str] = None
    message: Optional[str] = None


def get_place_summary(
    sanity_doc_id: str,
    client: Optional[SanityClient] = None,
) -> GetPlaceSummaryOutput:
    started = time.monotonic()
    client = client or SanityClient()

    doc = client.fetch_one(
        '*[_id == $id][0]{'
        '_id, title, "slug": slug.current, coordinates, aiMetadata, '
        '"tag_names": tags[]->name, '
        '"region_name": subRegion->region->name, '
        '"subRegion_name": subRegion->name'
        '}',
        params={"id": sanity_doc_id},
    )
    if not doc:
        return GetPlaceSummaryOutput(
            ok=False,
            sanity_doc_id=sanity_doc_id,
            error_code="DOC_NOT_FOUND",
            message=f"No page with _id={sanity_doc_id!r}",
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    ai = parse(doc.get("aiMetadata"))
    tag_names = [t for t in (doc.get("tag_names") or []) if t]

    return GetPlaceSummaryOutput(
        ok=True,
        sanity_doc_id=doc["_id"],
        title=doc.get("title") or "",
        slug=doc.get("slug"),
        region=doc.get("region_name"),
        subRegion=doc.get("subRegion_name"),
        settlement=ai.settlement(),
        coords=doc.get("coordinates"),

        place_subtype=_derive_place_subtype(tag_names),
        themes=_derive_themes(tag_names),
        physical_intensity=ai.physical_intensity_hint(),
        duration_band=ai.duration_band(),
        dog_friendly_kind=ai.dog_friendly_kind,

        description=ai.description,
        attractions=ai.attractions,
        activities=ai.activities,
        amenities=ai.amenities,
        accessibility_notes=ai.accessibility_notes,
        transportation=ai.transportation,
        local_tips=ai.local_tips,
        ideal_for=ai.ideal_for,
        nearby_places=[asdict(np) for np in ai.nearby_places],
        track_trail=asdict(ai.track_trail) if ai.track_trail else None,
        best_time_to_visit=ai.best_time_to_visit,
        water_safety_notes=ai.water_safety_notes,
        historical_significance=ai.historical_significance,

        tag_names=tag_names,
        parse_error=ai.parse_error,
        parse_error_message=ai.parse_error_message,
        latency_ms=int((time.monotonic() - started) * 1000),
    )


# CLI smoke test
if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    import json

    test_id = sys.argv[1] if len(sys.argv) > 1 else "00268b0a-3b30-4d44-80a5-c7d1ec7d7b33"  # Te Hakapureirei
    out = get_place_summary(test_id)

    if not out.ok:
        print(f"ERROR: {out.error_code}: {out.message}")
        sys.exit(1)

    print(f"Title:     {out.title}")
    print(f"Slug:      {out.slug}")
    print(f"Region:    {out.region} / {out.subRegion} / {out.settlement}")
    print(f"Coords:    {out.coords}")
    print(f"Subtype:   {out.place_subtype}, intensity={out.physical_intensity}, "
          f"duration={out.duration_band}, dog={out.dog_friendly_kind}")
    print(f"Themes:    {out.themes}")
    print(f"Tags:      {out.tag_names}")
    print()
    print(f"Description: {out.description[:200]}{'...' if len(out.description) > 200 else ''}")
    print()
    print(f"Attractions ({len(out.attractions)}): {out.attractions[:3]}{'...' if len(out.attractions) > 3 else ''}")
    print(f"Activities ({len(out.activities)}):  {out.activities[:3]}{'...' if len(out.activities) > 3 else ''}")
    print(f"Amenities ({len(out.amenities)}):    {out.amenities[:3]}{'...' if len(out.amenities) > 3 else ''}")
    print(f"Local tips ({len(out.local_tips)}):  {out.local_tips[:2]}{'...' if len(out.local_tips) > 2 else ''}")
    print(f"Nearby places ({len(out.nearby_places)}): {[p['name'] for p in out.nearby_places[:5]]}")
    if out.track_trail:
        print(f"Track:     {out.track_trail.get('name')!r} ({out.track_trail.get('primary_type')}, "
              f"{out.track_trail.get('difficulty')}, {out.track_trail.get('duration_text')})")
    print(f"Latency:   {out.latency_ms}ms")
