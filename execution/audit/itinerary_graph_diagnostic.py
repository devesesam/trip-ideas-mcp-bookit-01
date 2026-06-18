"""itinerary_graph_diagnostic — is Phase 2 (graph-driven itineraries) worth building?

The day builder picks stops by geometry (`haversine × 1.4`). This asks: does it
ALREADY pick editorially-coherent stops, or would routing selection through the
nearby-place graph change the day? If today's days are already coherent, Phase 2 is
low value. If not, Phase 2 earns its keep — and this gives a baseline to measure it.

Method (read-only; the Google Directions polyline call is stubbed out, so $0):
  - GEOMETRY day  = build_day_itinerary(base) as it runs today (radius pool).
  - GRAPH day     = SAME builder, but candidate pool = the base's editorial
                    neighbors fed via include_doc_ids (so the graph selects, the
                    greedy fill still sequences + times with haversine).
  Then compare:
    * coherence   = % of a day's stops that are editorial neighbors of the base.
    * overlap     = Jaccard(geometry stops, graph stops) — how much the graph
                    would change the day.
    * close-unlinked = geometry stops near the base that the graph does NOT link
                    (the across-water / "close but you'd not combine them" risk).

Run: python execution/audit/itinerary_graph_diagnostic.py [sample_per_region]
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from registry import nearby_graph  # noqa: E402
from registry.settlements import _haversine_km  # noqa: E402
from sanity_client import SanityClient  # noqa: E402
from tools import build_day_itinerary as bdi  # noqa: E402
from tools.build_day_itinerary import BuildDayInput, build_day_itinerary  # noqa: E402
from tools.find_place_by_name import FindPlaceByNameInput, find_place_by_name  # noqa: E402

# Stub the paid Google Directions polyline — we only need stop SELECTION, not the
# route line. Forces the straight-line fallback inside _build_route_geojson.
bdi.google_maps.is_configured = lambda: False

_GRAPH_POOL_LIMIT = 12      # how many editorial neighbors to seed the graph day with
_CLOSE_KM = 8.0             # "near the base" threshold for the close-unlinked flag


def _stops(out) -> list[dict]:
    if not out or not out.ok or not out.day_plan:
        return []
    return [
        {"id": s.place.sanity_doc_id, "title": s.place.title, "coords": s.place.coords}
        for s in out.day_plan.slots
        if s.slot_type == "place" and s.place
    ]


def _neighbor_ids(reg, pid: str) -> set:
    return {e["id"] for e in reg.adjacency.get(pid, [])}


def _real(stops, base_id) -> list[dict]:
    """Drop the base itself — it's the anchor, not a 'pick', and a place is never
    its own editorial neighbor, so counting it would understate coherence."""
    return [s for s in stops if s["id"] != base_id]


def _safe_build(inp: BuildDayInput, client) -> Optional[object]:
    try:
        return build_day_itinerary(inp, client=client)
    except Exception:
        return None


def _build_geometry(base_title, region, subRegion, client):
    return _safe_build(BuildDayInput(
        base_location=base_title, region=region, subRegion=subRegion,
    ), client)


def _build_graph(base_id, base_title, region, subRegion, reg, client):
    nbr = [n["sanity_doc_id"] for n in reg.neighbors(base_id, limit=_GRAPH_POOL_LIMIT)]
    if not nbr:
        return None
    return _safe_build(BuildDayInput(
        base_location=base_title, region=region, subRegion=subRegion,
        include_doc_ids=[base_id] + nbr,
    ), client)


def _coherence(stops, base_id, reg) -> Optional[float]:
    if not stops:
        return None
    nbr = _neighbor_ids(reg, base_id)
    return sum(1 for s in stops if s["id"] in nbr) / len(stops)


def _overlap(a_stops, b_stops) -> Optional[float]:
    a = {s["id"] for s in a_stops}
    b = {s["id"] for s in b_stops}
    if not a and not b:
        return None
    return len(a & b) / len(a | b) if (a | b) else None


def _close_unlinked(stops, base_id, reg) -> list[tuple]:
    nbr = _neighbor_ids(reg, base_id)
    bc = (reg.nodes.get(base_id) or {}).get("coords")
    out = []
    for s in stops:
        if s["id"] in nbr or not bc or not s["coords"]:
            continue
        km = _haversine_km(bc["lat"], bc["lng"], s["coords"]["lat"], s["coords"]["lng"])
        if km <= _CLOSE_KM:
            out.append((s["title"], round(km, 1)))
    return out


def _sample_bases(reg, per_region: int, min_neighbors: int = 4) -> list[tuple]:
    by_region = defaultdict(list)
    for nid, m in reg.nodes.items():
        if m.get("region") and m.get("subRegion") and m.get("coords"):
            deg = len(reg.adjacency.get(nid, []))
            if deg >= min_neighbors:
                by_region[m["region"]].append((nid, m, deg))
    picks = []
    for region, lst in sorted(by_region.items()):
        lst.sort(key=lambda x: -x[2])          # most-connected hubs first (deterministic)
        picks.extend(lst[:per_region])
    return picks


def run_aggregate(reg, client, per_region: int) -> None:
    bases = _sample_bases(reg, per_region)
    print(f"\n=== AGGREGATE: {len(bases)} bases (top-{per_region} connected per region) ===")
    print(f"{'Region':<18} {'Base':<26} {'geoN':>4} {'coher':>6} {'grphN':>5} "
          f"{'overlap':>7} {'close-unlinked':>14}")
    cohers, overlaps, changed, total_unlinked = [], [], 0, 0
    for nid, m, deg in bases:
        title, region, sub = m["title"], m["region"], m["subRegion"]
        geo = _build_geometry(title, region, sub, client)
        grp = _build_graph(nid, title, region, sub, reg, client)
        gs, hs = _real(_stops(geo), nid), _real(_stops(grp), nid)
        coher = _coherence(gs, nid, reg)
        ov = _overlap(gs, hs)
        unlinked = _close_unlinked(gs, nid, reg)
        if coher is not None:
            cohers.append(coher)
        if ov is not None:
            overlaps.append(ov)
            if ov < 0.5:
                changed += 1
        total_unlinked += len(unlinked)
        print(f"{region:<18} {title[:25]:<26} {len(gs):>4} "
              f"{(f'{coher:.0%}' if coher is not None else '-'):>6} {len(hs):>5} "
              f"{(f'{ov:.0%}' if ov is not None else '-'):>7} "
              f"{(', '.join(t for t, _ in unlinked[:2]) or '-'):>14}")
    mc = sum(cohers) / len(cohers) if cohers else 0
    mo = sum(overlaps) / len(overlaps) if overlaps else 0
    print(f"\n  mean geometry-day coherence (stops that ARE editorial neighbors of base): {mc:.0%}")
    print(f"  mean overlap (geometry vs graph day):                                     {mo:.0%}")
    print(f"  bases where graph would materially change the day (overlap < 50%):        "
          f"{changed}/{len(overlaps)}")
    print(f"  total close-but-unlinked geometry stops (across-water risk):              {total_unlinked}")


def run_prototype(reg, client, names: list[str]) -> None:
    print("\n=== PROTOTYPE: geometry day vs graph day ===")
    for name in names:
        res = find_place_by_name(FindPlaceByNameInput(name=name, limit=1), client=client)
        hit = res.results[0] if getattr(res, "results", None) else None
        if not hit:
            print(f"\n--- {name}: no page match ---")
            continue
        bid, region, sub = hit.sanity_doc_id, hit.region, hit.subRegion
        title = hit.title
        in_graph = bid in reg.nodes and bid in reg.adjacency
        print(f"\n--- {name} -> {title}  ({region} / {sub})  "
              f"[{'graph node, ' + str(len(reg.adjacency.get(bid, []))) + ' neighbors' if in_graph else 'NOT a graph node / orphan'}] ---")
        geo = _build_geometry(title, region, sub, client)
        grp = _build_graph(bid, title, region, sub, reg, client) if in_graph else None
        nbr = _neighbor_ids(reg, bid)
        bc = (reg.nodes.get(bid) or {}).get("coords")

        def _render(label, out):
            stops = _stops(out)
            print(f"  {label} ({len(stops)} stops):")
            if not stops:
                print("    (none)")
                return
            for s in stops:
                if s["id"] == bid:
                    tag = "(base/anchor)"
                else:
                    tag = "editorial-neighbor" if s["id"] in nbr else "NOT-a-neighbor"
                km = ""
                if bc and s["coords"]:
                    km = f"{_haversine_km(bc['lat'], bc['lng'], s['coords']['lat'], s['coords']['lng']):.1f}km"
                print(f"    - {s['title']:<34} [{tag:<18}] {km:>8}")

        _render("GEOMETRY", geo)
        if in_graph:
            _render("GRAPH   ", grp)
        else:
            print("  GRAPH   : skipped — base is not a place node (the 'base is a town' wrinkle)")


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    per_region = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    client = SanityClient()
    reg = nearby_graph.get_registry()

    run_prototype(reg, client, ["Piha", "Queenstown", "Curio Bay"])
    run_aggregate(reg, client, per_region)
