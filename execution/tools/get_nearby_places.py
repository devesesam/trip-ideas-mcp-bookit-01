"""`get_nearby_places` — ranked nearby places for one place, editorial-first.

Answers "what's near X" / place-page "nearby" cards using the editorial nearby-place
graph (`registry/nearby_graph.py`), which is built from the "nearby attractions" the
article authors actually named. This is better than a raw distance search because it
respects road corridors, harbours and travel patterns (e.g. it won't suggest a beach
across the harbour just because it's close as the crow flies).

Falls back to a geometric (distance) search when a place has fewer than `_MIN_NEIGHBORS`
editorial links, so sparse / orphan pages still fill a card. Every neighbor is tagged
`source="editorial"` or `source="geographic"` so the caller can be honest about which is
which.

Does NOT call an LLM. Reads the cached graph + (only on fallback) one search_places pass.
Read-only.
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

from registry import nearby_graph  # noqa: E402
from sanity_client import SanityClient  # noqa: E402
from tools.search_places import (  # noqa: E402
    NearFilter,
    SearchPlacesInput,
    _derive_themes,
    search_places,
)

# Display thresholds mirror the Nearby Places card spec (min 4, max 8).
_MIN_NEIGHBORS = 4
_FALLBACK_RADIUS_KM = 30.0


@dataclass
class GetNearbyPlacesInput:
    sanity_doc_id: str
    limit: int = 8


@dataclass
class GetNearbyPlacesOutput:
    ok: bool
    sanity_doc_id: str = ""
    title: str = ""
    slug: Optional[str] = None
    region: Optional[str] = None
    subRegion: Optional[str] = None
    coords: Optional[dict] = None
    neighbors: list[dict] = field(default_factory=list)
    editorial_count: int = 0
    fallback_count: int = 0
    note: Optional[str] = None
    latency_ms: int = 0
    error_code: Optional[str] = None
    message: Optional[str] = None


def _blank_neighbor(**kw) -> dict:
    base = {
        "sanity_doc_id": None, "title": None, "slug": None, "coords": None,
        "region": None, "subRegion": None, "source": None, "relationship": None,
        "reciprocal": False, "direction": None, "context": None,
        "distance_text": None, "straight_line_km": None, "themes": [],
    }
    base.update(kw)
    return base


def get_nearby_places(
    inp: GetNearbyPlacesInput,
    client: Optional[SanityClient] = None,
) -> GetNearbyPlacesOutput:
    started = time.monotonic()
    client = client or SanityClient()
    reg = nearby_graph.get_registry()

    src = reg.node(inp.sanity_doc_id)
    if src is None:
        # Unknown to the cached graph (e.g. a brand-new page) — fetch the node directly.
        doc = client.fetch_one(
            '*[_id == $id][0]{_id, title, "slug": slug.current, coordinates, '
            '"region": subRegion->region->name, "subRegion": subRegion->name}',
            params={"id": inp.sanity_doc_id},
        )
        if not doc:
            return GetNearbyPlacesOutput(
                ok=False, sanity_doc_id=inp.sanity_doc_id, error_code="DOC_NOT_FOUND",
                message=f"No page with _id={inp.sanity_doc_id!r}",
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        src = {
            "title": doc.get("title") or "", "slug": doc.get("slug"),
            "coords": nearby_graph._norm_coords(doc.get("coordinates")),
            "region": doc.get("region"), "subRegion": doc.get("subRegion"),
        }

    # --- editorial neighbors (already ranked: mutual -> out -> in, nearest first) ---
    neighbors: list[dict] = []
    for n in reg.neighbors(inp.sanity_doc_id, limit=inp.limit):
        neighbors.append(_blank_neighbor(
            sanity_doc_id=n["sanity_doc_id"], title=n["title"], slug=n["slug"],
            coords=n["coords"], region=n["region"], subRegion=n["subRegion"],
            source="editorial",
            relationship="mutual" if n["reciprocal"] else "one_way",
            reciprocal=n["reciprocal"], direction=n["direction"],
            context=n["context"], distance_text=n["distance_text"],
            straight_line_km=n["straight_line_km"],
        ))

    note: Optional[str] = None

    # --- geometric fallback when editorial coverage is thin ---
    if len(neighbors) < _MIN_NEIGHBORS and src.get("coords") and src.get("region"):
        exclude = {inp.sanity_doc_id} | {n["sanity_doc_id"] for n in neighbors}
        sp = search_places(
            SearchPlacesInput(
                region=src["region"],
                near=NearFilter(
                    lat=src["coords"]["lat"], lng=src["coords"]["lng"],
                    radius_km=_FALLBACK_RADIUS_KM,
                ),
                limit=inp.limit + len(exclude) + 5,
            ),
            client=client,
        )
        extra = sorted(
            [r for r in sp.results if r.sanity_doc_id not in exclude],
            key=lambda r: (r.distance_km if r.distance_km is not None else 9e9),
        )
        for r in extra:
            if len(neighbors) >= inp.limit:
                break
            neighbors.append(_blank_neighbor(
                sanity_doc_id=r.sanity_doc_id, title=r.title, slug=r.slug,
                coords=r.coords, region=r.region, subRegion=r.subRegion,
                source="geographic",
                straight_line_km=round(r.distance_km, 2) if r.distance_km is not None else None,
                themes=r.themes_derived,
            ))
        if any(n["source"] == "geographic" for n in neighbors):
            note = ("Few editorial links for this place — topped up with nearby places "
                    "by distance (tagged source='geographic').")

    neighbors = neighbors[: inp.limit]

    # --- attach tag-derived themes to the editorial neighbors (one batched read) ---
    ed_ids = [n["sanity_doc_id"] for n in neighbors if n["source"] == "editorial"]
    if ed_ids:
        docs = client.query(
            '*[_id in $ids]{_id, "tag_names": tags[]->name}', params={"ids": ed_ids}
        ) or []
        theme_map = {
            d["_id"]: _derive_themes([t for t in (d.get("tag_names") or []) if t])
            for d in docs
        }
        for n in neighbors:
            if n["source"] == "editorial":
                n["themes"] = theme_map.get(n["sanity_doc_id"], [])

    return GetNearbyPlacesOutput(
        ok=True,
        sanity_doc_id=inp.sanity_doc_id,
        title=src.get("title") or "",
        slug=src.get("slug"),
        region=src.get("region"),
        subRegion=src.get("subRegion"),
        coords=src.get("coords"),
        neighbors=neighbors,
        editorial_count=sum(1 for n in neighbors if n["source"] == "editorial"),
        fallback_count=sum(1 for n in neighbors if n["source"] == "geographic"),
        note=note,
        latency_ms=int((time.monotonic() - started) * 1000),
    )


# CLI smoke test
if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    test_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not test_id:
        print("usage: python execution/tools/get_nearby_places.py <sanity_doc_id>")
        sys.exit(2)

    out = get_nearby_places(GetNearbyPlacesInput(sanity_doc_id=test_id))
    if not out.ok:
        print(f"ERROR: {out.error_code}: {out.message}")
        sys.exit(1)

    print(f"{out.title}  ({out.region} / {out.subRegion})")
    print(f"editorial={out.editorial_count}  geographic={out.fallback_count}"
          + (f"  — {out.note}" if out.note else ""))
    print()
    for n in out.neighbors:
        rel = n["relationship"] or n["source"]
        km = f"{n['straight_line_km']}km" if n["straight_line_km"] is not None else "?"
        themes = (", ".join(n["themes"][:3])) if n["themes"] else ""
        ctx = f"  «{n['context']}»" if n.get("context") else ""
        print(f"  [{n['source'][:3]}] {n['title']:<38} {rel:<8} {km:>8}  {themes}{ctx}")
    print(f"\nLatency: {out.latency_ms}ms")
