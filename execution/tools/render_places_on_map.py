"""`render_places_on_map` — draw arbitrary Tripideas places on the map panel.

Companion to the itinerary tools (build_day / build_trip / refine) which emit
`route_geojson` as a side-effect of composing a plan. This tool exists for the
much lighter case: the user has a set of places (from search_places, from
chatting about them, from a list of suggestions) and asks "show those on the
map" without wanting a full timed itinerary.

The frontend `MapPanel` reads any `route_geojson` event off the SSE stream and
auto-fits the bounds. Emitting a points-only FeatureCollection here is enough
to make markers appear next to the chat.

Design choices:
- Points only. No LineString — this isn't a route, it's a set of pins.
  If the user wants a route, they should ask for an itinerary.
- One batch GROQ query for all requested IDs (not N round-trips).
- Silent partial success: docs that can't be found, or that lack coordinates,
  go into `missing_ids` so the chat can mention them but the map still
  renders what it can.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from sanity_client import SanityClient  # noqa: E402


@dataclass
class RenderPlacesOnMapInput:
    sanity_doc_ids: list[str]                       # REQUIRED — IDs from prior tool results
    title: Optional[str] = None                     # Optional caption for logging/UX


@dataclass
class RenderPlacesOnMapOutput:
    ok: bool
    count: int                                      # places successfully placed on the map
    rendered_titles: list[str] = field(default_factory=list)
    missing_ids: list[dict] = field(default_factory=list)  # [{id, reason}]
    route_geojson: dict = field(default_factory=lambda: {"type": "FeatureCollection", "features": []})
    latency_ms: int = 0
    error_code: Optional[str] = None
    message: Optional[str] = None


def render_places_on_map(
    inp: RenderPlacesOnMapInput,
    client: Optional[SanityClient] = None,
) -> RenderPlacesOnMapOutput:
    started = time.monotonic()
    client = client or SanityClient()

    # Deduplicate while preserving order — caller may pass repeats.
    seen: set[str] = set()
    ids: list[str] = []
    for raw_id in inp.sanity_doc_ids or []:
        if not raw_id or raw_id in seen:
            continue
        seen.add(raw_id)
        ids.append(raw_id)

    if not ids:
        return RenderPlacesOnMapOutput(
            ok=False,
            count=0,
            latency_ms=int((time.monotonic() - started) * 1000),
            error_code="EMPTY_IDS",
            message="`sanity_doc_ids` must contain at least one doc ID.",
        )

    groq = (
        '*[_id in $ids]{'
        '_id, title, "slug": slug.current, coordinates, '
        '"region": subRegion->region->name, '
        '"subRegion": subRegion->name'
        '}'
    )

    try:
        docs = client.query(groq, params={"ids": ids}) or []
    except Exception as e:  # noqa: BLE001
        return RenderPlacesOnMapOutput(
            ok=False,
            count=0,
            latency_ms=int((time.monotonic() - started) * 1000),
            error_code="SANITY_ERROR",
            message=str(e),
        )

    by_id = {d["_id"]: d for d in docs}

    features: list[dict] = []
    rendered_titles: list[str] = []
    missing: list[dict] = []

    for doc_id in ids:
        doc = by_id.get(doc_id)
        if not doc:
            missing.append({"id": doc_id, "reason": "not_found"})
            continue
        coords = doc.get("coordinates") or {}
        lat = coords.get("lat")
        lng = coords.get("lng")
        if lat is None or lng is None:
            missing.append({
                "id": doc_id,
                "reason": "no_coordinates",
                "title": doc.get("title"),
            })
            continue

        title = doc.get("title") or "(untitled)"
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": {
                "role": "place",
                "sanity_doc_id": doc["_id"],
                "title": title,
                "slug": doc.get("slug"),
                "settlement": doc.get("subRegion"),
                "region": doc.get("region"),
            },
        })
        rendered_titles.append(title)

    return RenderPlacesOnMapOutput(
        ok=True,
        count=len(features),
        rendered_titles=rendered_titles,
        missing_ids=missing,
        route_geojson={"type": "FeatureCollection", "features": features},
        latency_ms=int((time.monotonic() - started) * 1000),
    )


__all__ = [
    "render_places_on_map",
    "RenderPlacesOnMapInput",
    "RenderPlacesOnMapOutput",
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

    import json as _json
    from tools.find_place_by_name import FindPlaceByNameInput, find_place_by_name

    client = SanityClient()

    # Pull a handful of real IDs by name so the smoke test runs without
    # hard-coded doc IDs.
    sample_names = ["Mission Bay", "Cornwall Park", "Wynyard Quarter"]
    doc_ids: list[str] = []
    for n in sample_names:
        out = find_place_by_name(FindPlaceByNameInput(name=n, region="Auckland", limit=1), client=client)
        if out.ok and out.results:
            doc_ids.append(out.results[0].sanity_doc_id)

    print(f"Resolved {len(doc_ids)} doc IDs from {sample_names}")
    result = render_places_on_map(RenderPlacesOnMapInput(sanity_doc_ids=doc_ids), client=client)
    print(f"  ok={result.ok}, count={result.count}, missing={len(result.missing_ids)}, "
          f"latency={result.latency_ms}ms")
    print(f"  titles: {result.rendered_titles}")
    if result.missing_ids:
        print(f"  missing: {result.missing_ids}")
    print(f"  features: {len(result.route_geojson['features'])}")
    # Print first feature for visual inspection
    if result.route_geojson["features"]:
        print(_json.dumps(result.route_geojson["features"][0], indent=2))
