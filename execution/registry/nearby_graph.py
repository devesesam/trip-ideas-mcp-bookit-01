"""Editorial nearby-place graph registry.

Builds a place→place association graph from each page's `aiMetadata.nearby_places`
(the "nearby attractions" the article author named in the text), resolves those
free-text names to corpus page IDs, symmetrizes into an undirected adjacency, and
caches to disk — mirroring the registry pattern in `registry/regions.py`.

Resolution is **region-scoped**: a reference is matched against pages in the source
place's own region only (exact, then rapidfuzz token_set_ratio ≥ 80). That kills the
cross-country name collisions (the several "Waipapa"s, "Cathedral Caves", etc.) that a
global match produces. Cross-region and unresolvable ("dangling") references are dropped
from the graph — they're tracked only as a stat. This is the production-grade version of
the resolver prototyped in `audit/nearby_graph_spike.py` (which additionally keeps the
cross-region / dangling cases for its divergence analysis).

Consumed by `tools/get_nearby_places.py`. Read-only — no Sanity writes.

Run as a script to refresh the cache and print stats + sample neighbors:

    python execution/registry/nearby_graph.py
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_PKG_ROOT = Path(__file__).resolve().parent.parent  # .../execution
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from rapidfuzz import fuzz, process  # noqa: E402

from aimetadata.parser import parse  # noqa: E402
from registry.settlements import _haversine_km, _strip_accents  # noqa: E402
from sanity_client import SanityClient  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_PATH = PROJECT_ROOT / ".tmp" / "nearby_graph_cache.json"
CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days

# rapidfuzz token_set_ratio threshold — mirrors find_place_by_name / settlements.
_FUZZY_THRESHOLD = 80

_CORPUS_GROQ = (
    '*[_type == "page" && defined(title)]{'
    '_id, title, "slug": slug.current, coordinates, aiMetadata, '
    '"region": subRegion->region->name, "subRegion": subRegion->name'
    "}"
)

# Rank tiers for neighbor ordering: mutual links first, then this page's own
# outgoing picks, then incoming (named by the other page).
_DIRECTION_RANK = {"both": 0, "out": 1, "in": 2}


def _norm_coords(c) -> Optional[dict]:
    """Normalize a Sanity geopoint to a plain {lat, lng} dict, or None."""
    if not isinstance(c, dict):
        return None
    lat, lng = c.get("lat"), c.get("lng")
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        return {"lat": float(lat), "lng": float(lng)}
    return None


@dataclass
class NearbyGraphRegistry:
    nodes: dict[str, dict]            # id -> {title, slug, coords, region, subRegion}
    adjacency: dict[str, list[dict]]  # id -> [{id, reciprocal, direction, context, distance_text}]
    fetched_at: float
    stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "nodes": self.nodes,
            "adjacency": self.adjacency,
            "fetched_at": self.fetched_at,
            "stats": self.stats,
        }

    def node(self, place_id: str) -> Optional[dict]:
        return self.nodes.get(place_id)

    def neighbors(self, place_id: str, limit: Optional[int] = None) -> list[dict]:
        """Ranked editorial neighbors of `place_id`, enriched from node metadata.

        Order: mutual → outgoing → incoming, ties broken by ascending straight-line km.
        Returns [] for an orphan (no editorial links) or an unknown id.
        """
        entries = self.adjacency.get(place_id, [])
        src = self.nodes.get(place_id) or {}
        src_coords = src.get("coords")
        out: list[dict] = []
        for e in entries:
            meta = self.nodes.get(e["id"]) or {}
            km = None
            mc = meta.get("coords")
            if src_coords and mc:
                km = round(
                    _haversine_km(src_coords["lat"], src_coords["lng"], mc["lat"], mc["lng"]), 2
                )
            out.append({
                "sanity_doc_id": e["id"],
                "title": meta.get("title"),
                "slug": meta.get("slug"),
                "coords": mc,
                "region": meta.get("region"),
                "subRegion": meta.get("subRegion"),
                "reciprocal": e["reciprocal"],
                "direction": e["direction"],
                "context": e.get("context"),
                "distance_text": e.get("distance_text"),
                "straight_line_km": km,
            })
        out.sort(key=lambda n: (
            _DIRECTION_RANK.get(n["direction"], 3),
            n["straight_line_km"] if n["straight_line_km"] is not None else 9e9,
        ))
        return out[:limit] if limit else out


# --- Sanity I/O / build ---

def fetch_from_sanity(client: Optional[SanityClient] = None) -> NearbyGraphRegistry:
    client = client or SanityClient()
    docs = client.query(_CORPUS_GROQ) or []

    # Node metadata for every page, plus region-scoped title indexes for resolution.
    nodes: dict[str, dict] = {}
    parsed: dict[str, dict] = {}                       # id -> {nearby, region}
    reg_index: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    reg_titles: dict[str, list[str]] = defaultdict(list)
    reg_title_ids: dict[str, list[str]] = defaultdict(list)
    # Region + subRegion names (normalized). A "nearby" reference that is just a
    # region/city name (e.g. "Auckland", "Coromandel") is a geographic container,
    # not a place pairing — we drop it so it can't fuzzy-match a page that merely
    # starts with that word ("Auckland" → "Auckland Domain Pukekawa").
    geo_names: set[str] = set()

    for d in docs:
        _id = d["_id"]
        pm = parse(d.get("aiMetadata"))
        region = d.get("region")
        subRegion = d.get("subRegion")
        nodes[_id] = {
            "title": d.get("title") or "",
            "slug": d.get("slug"),
            "coords": _norm_coords(d.get("coordinates")),
            "region": region,
            "subRegion": subRegion,
        }
        parsed[_id] = {"nearby": pm.nearby_places, "region": region}
        if region:
            geo_names.add(_strip_accents(region))
        if subRegion:
            geo_names.add(_strip_accents(subRegion))
        nt = _strip_accents(d.get("title") or "")
        if nt and region:
            reg_index[region][nt].append(_id)
            reg_titles[region].append(nt)
            reg_title_ids[region].append(_id)

    # Region-scoped resolver (in-region only). Cache by (needle, region).
    res_cache: dict[tuple[str, Optional[str]], Optional[str]] = {}

    def resolve(name: str, source_region: Optional[str]) -> Optional[str]:
        needle = _strip_accents(name)
        if not needle or not source_region or source_region not in reg_titles:
            return None
        if needle in geo_names:           # bare region/city reference → not a place pairing
            return None
        key = (needle, source_region)
        if key in res_cache:
            return res_cache[key]
        hit: Optional[str] = None
        ex = reg_index[source_region].get(needle)
        if ex:
            hit = ex[0]
        else:
            m = process.extractOne(
                needle, reg_titles[source_region],
                scorer=fuzz.token_set_ratio, score_cutoff=_FUZZY_THRESHOLD,
            )
            if m:
                hit = reg_title_ids[source_region][m[2]]
        res_cache[key] = hit
        return hit

    # Directed edges with editorial metadata; track dropped references as a stat.
    directed: dict[tuple[str, str], dict] = {}
    n_refs = 0
    n_dropped = 0
    for _id, rec in parsed.items():
        for np in rec["nearby"]:
            name = (np.name or "").strip()
            if not name:
                continue
            n_refs += 1
            tgt = resolve(name, rec["region"])
            if not tgt or tgt == _id:
                n_dropped += 1
                continue
            directed[(_id, tgt)] = {"context": np.context, "distance_text": np.distance_text}

    directed_set = set(directed.keys())

    # Symmetrize: every unordered linked pair appears in both nodes' adjacency, each
    # tagged with its own direction (out/in/both) and the editorial context.
    adjacency: dict[str, list[dict]] = defaultdict(list)
    n_reciprocal_pairs = 0
    for pair in {frozenset(p) for p in directed_set}:
        a, b = tuple(pair)
        ab, ba = (a, b) in directed_set, (b, a) in directed_set
        reciprocal = ab and ba
        if reciprocal:
            n_reciprocal_pairs += 1
        a_ctx = directed.get((a, b)) or directed.get((b, a)) or {}
        b_ctx = directed.get((b, a)) or directed.get((a, b)) or {}
        adjacency[a].append({
            "id": b, "reciprocal": reciprocal,
            "direction": "both" if reciprocal else ("out" if ab else "in"),
            "context": a_ctx.get("context"), "distance_text": a_ctx.get("distance_text"),
        })
        adjacency[b].append({
            "id": a, "reciprocal": reciprocal,
            "direction": "both" if reciprocal else ("out" if ba else "in"),
            "context": b_ctx.get("context"), "distance_text": b_ctx.get("distance_text"),
        })

    stats = {
        "n_nodes": len(nodes),
        "n_linked": len(adjacency),
        "n_orphan": sum(1 for nid in nodes if nid not in adjacency),
        "n_references": n_refs,
        "n_references_dropped": n_dropped,
        "n_directed_edges": len(directed_set),
        "n_reciprocal_pairs": n_reciprocal_pairs,
    }
    return NearbyGraphRegistry(
        nodes=nodes, adjacency=dict(adjacency), fetched_at=time.time(), stats=stats,
    )


def save_cache(registry: NearbyGraphRegistry, path: Path = CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(registry.to_dict(), f, ensure_ascii=False, indent=2)


def load_cache(path: Path = CACHE_PATH) -> Optional[NearbyGraphRegistry]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return NearbyGraphRegistry(
            nodes=data.get("nodes", {}),
            adjacency=data.get("adjacency", {}),
            fetched_at=data.get("fetched_at", 0.0),
            stats=data.get("stats", {}),
        )
    except Exception:
        return None


def get_registry(
    force_refresh: bool = False,
    max_age_seconds: int = CACHE_TTL_SECONDS,
) -> NearbyGraphRegistry:
    """Get the nearby-graph registry, using cache if fresh enough.

    Set `force_refresh=True` to always rebuild from Sanity (and rewrite the cache).
    """
    if not force_refresh:
        cached = load_cache()
        if cached and (time.time() - cached.fetched_at) < max_age_seconds:
            return cached
    fresh = fetch_from_sanity()
    save_cache(fresh)
    return fresh


# --- Module-level convenience: lazy default registry ---

_default_registry: Optional[NearbyGraphRegistry] = None


def _registry() -> NearbyGraphRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = get_registry()
    return _default_registry


def neighbors(place_id: str, limit: Optional[int] = None) -> list[dict]:
    return _registry().neighbors(place_id, limit=limit)


def node(place_id: str) -> Optional[dict]:
    return _registry().node(place_id)


# --- CLI: refresh + stats ---

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    reg = get_registry(force_refresh=True)
    print("Rebuilt nearby-place graph cache:")
    for k, v in reg.stats.items():
        print(f"  {k:24} {v}")
    print(f"  cache -> {CACHE_PATH}")

    def _find_id(substr: str) -> Optional[str]:
        target = _strip_accents(substr)
        # Prefer a linked node so the sample shows real neighbors.
        cands = [nid for nid, m in reg.nodes.items()
                 if target in _strip_accents(m.get("title") or "")]
        for nid in cands:
            if nid in reg.adjacency:
                return nid
        return cands[0] if cands else None

    for name in ("Omaha", "Arataki", "Piha"):
        nid = _find_id(name)
        if not nid:
            print(f"\n{name}: not found")
            continue
        title = reg.nodes[nid]["title"]
        ns = reg.neighbors(nid, limit=8)
        print(f"\n{name} -> {title} ({len(reg.adjacency.get(nid, []))} editorial neighbors):")
        for n in ns:
            rel = "mutual" if n["reciprocal"] else n["direction"]
            km = f"{n['straight_line_km']}km" if n["straight_line_km"] is not None else "?"
            print(f"  - {n['title']}  [{rel}, {km}]")
