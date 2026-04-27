"""NZ regions / subRegions registry.

Pulls live region/subRegion graph from Sanity, caches to disk, and exposes
lookup helpers for the rest of the planning pipeline.

The `subRegion` doc in Sanity has a `region` reference; this module resolves
those into a flat lookup so callers can answer:

- Which region does this subRegion belong to?
- Which subRegions are in this region?
- Which island is this region on?
- What's the canonical name of this region (handling diacritic variants)?

Run as a script to refresh the cache and print the registry:

    python execution/registry/regions.py
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

# Make sibling `sanity_client` importable when run directly or imported as package
_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from sanity_client import SanityClient  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_PATH = PROJECT_ROOT / ".tmp" / "regions_cache.json"
CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days


# Static region name → island. NZ has North, South, Stewart Island, and a few
# offshore island groups. Keep both macron and non-macron variants of names
# observed in Sanity. Update as new regions are observed.
REGION_ISLAND: dict[str, str] = {
    # North Island
    "Northland": "North",
    "Auckland": "North",
    "Coromandel": "North",
    "Waikato": "North",
    "Bay of Plenty": "North",
    "East Cape": "North",
    "Gisborne": "North",
    "Hawke Bay": "North",          # Sanity uses this form
    "Hawke's Bay": "North",
    "Hawkes Bay": "North",
    "Taranaki": "North",
    "Manawatū-Whanganui": "North",
    "Manawatu-Whanganui": "North",
    "Wairarapa": "North",
    "Wellington": "North",
    # South Island
    "Tasman": "South",
    "Nelson": "South",
    "Nelson Tasman": "South",      # Sanity uses combined form
    "Golden Bay": "South",
    "Marlborough": "South",
    "West Coast": "South",
    "Canterbury": "South",
    "Otago": "South",
    "Southland": "South",
    "Fiordland": "South",
    # Stewart Island — note: in Sanity this is a subRegion of Southland,
    # not a top-level region. Use `island_for_subRegion` to catch it.
    "Stewart Island": "Stewart",
    "Rakiura": "Stewart",
    # Offshore
    "Chatham Islands": "Offshore",
}

# subRegions that override their parent region's island assignment.
# Stewart Island ("Rakiura") sits under Southland in Sanity but is its own island.
SUBREGION_ISLAND_OVERRIDE: dict[str, str] = {
    "Rakiura": "Stewart",
    "Stewart Island": "Stewart",
}


@dataclass
class Region:
    id: str
    name: str
    slug: str
    maori: Optional[str] = None
    island: str = "Unknown"


@dataclass
class SubRegion:
    id: str
    name: str
    slug: str
    region_id: str = ""
    region_name: str = ""


@dataclass
class RegionsRegistry:
    regions: list[Region] = field(default_factory=list)
    subRegions: list[SubRegion] = field(default_factory=list)
    fetched_at: float = 0.0

    # --- Lookups by id / name ---

    def region_by_id(self, region_id: str) -> Optional[Region]:
        return next((r for r in self.regions if r.id == region_id), None)

    def region_by_name(self, name: str) -> Optional[Region]:
        target = _normalize(name)
        return next((r for r in self.regions if _normalize(r.name) == target), None)

    def subRegion_by_id(self, sub_id: str) -> Optional[SubRegion]:
        return next((s for s in self.subRegions if s.id == sub_id), None)

    def subRegion_by_name(self, name: str) -> Optional[SubRegion]:
        target = _normalize(name)
        return next((s for s in self.subRegions if _normalize(s.name) == target), None)

    # --- Graph traversals ---

    def subRegions_for_region(self, region_name: str) -> list[SubRegion]:
        target = _normalize(region_name)
        return [s for s in self.subRegions if _normalize(s.region_name) == target]

    def region_for_subRegion(self, subRegion_name: str) -> Optional[Region]:
        sub = self.subRegion_by_name(subRegion_name)
        if not sub:
            return None
        return self.region_by_id(sub.region_id)

    def island_for_region(self, region_name: str) -> str:
        # Try direct lookup first
        if region_name in REGION_ISLAND:
            return REGION_ISLAND[region_name]
        # Then case-insensitive
        target = _normalize(region_name)
        for k, v in REGION_ISLAND.items():
            if _normalize(k) == target:
                return v
        # Finally check if Sanity returned an island value already
        r = self.region_by_name(region_name)
        return r.island if (r and r.island and r.island != "Unknown") else "Unknown"

    def island_for_subRegion(self, subRegion_name: str) -> str:
        """Resolve island via subRegion. Handles Rakiura/Stewart correctly
        even though it sits under Southland in Sanity's hierarchy."""
        # Override list takes precedence
        target = _normalize(subRegion_name)
        for k, v in SUBREGION_ISLAND_OVERRIDE.items():
            if _normalize(k) == target:
                return v
        # Fall through to parent region's island
        parent = self.region_for_subRegion(subRegion_name)
        if parent:
            return self.island_for_region(parent.name)
        return "Unknown"

    def data_quality_warnings(self) -> list[str]:
        """Surface data issues observed in the live registry."""
        warnings: list[str] = []
        # Orphan subRegions (no region reference resolved)
        orphans = [s.name for s in self.subRegions if not s.region_name]
        if orphans:
            warnings.append(f"{len(orphans)} subRegion(s) with no region reference: {orphans}")
        # Whitespace issues
        whitespace_subs = [
            s.name for s in self.subRegions if s.name != s.name.strip()
        ]
        if whitespace_subs:
            warnings.append(f"subRegion(s) with leading/trailing whitespace: {whitespace_subs}")
        # Regions without island mapping
        unmapped_regions = [
            r.name for r in self.regions if r.island == "Unknown"
        ]
        if unmapped_regions:
            warnings.append(f"region(s) with no island mapping: {unmapped_regions}")
        return warnings

    # --- Convenience listings ---

    def all_region_names(self) -> list[str]:
        return sorted([r.name for r in self.regions])

    def all_subRegion_names(self) -> list[str]:
        return sorted([s.name for s in self.subRegions])

    def to_dict(self) -> dict:
        return {
            "regions": [asdict(r) for r in self.regions],
            "subRegions": [asdict(s) for s in self.subRegions],
            "fetched_at": self.fetched_at,
        }


def _normalize(s: str) -> str:
    """Case- and whitespace-insensitive comparison key. Diacritics preserved
    (Sanity stores both 'Maori' and 'Māori' variants; treat as distinct here)."""
    return (s or "").strip().casefold()


# --- Sanity I/O ---

def fetch_from_sanity(client: Optional[SanityClient] = None) -> RegionsRegistry:
    client = client or SanityClient()
    region_docs = client.query(
        '*[_type == "region"]{_id, name, "slug": slug.current, maori}'
    ) or []
    subregion_docs = client.query(
        '*[_type == "subRegion"]{'
        '_id, name, "slug": slug.current, '
        '"region_id": region->_id, "region_name": region->name'
        '}'
    ) or []

    regions = [
        Region(
            id=d.get("_id", ""),
            name=d.get("name", ""),
            slug=d.get("slug") or "",
            maori=d.get("maori"),
            island=REGION_ISLAND.get(d.get("name", ""), "Unknown"),
        )
        for d in region_docs
    ]
    subRegions = [
        SubRegion(
            id=d.get("_id", ""),
            name=d.get("name", ""),
            slug=d.get("slug") or "",
            region_id=d.get("region_id") or "",
            region_name=d.get("region_name") or "",
        )
        for d in subregion_docs
    ]
    return RegionsRegistry(regions=regions, subRegions=subRegions, fetched_at=time.time())


def save_cache(registry: RegionsRegistry, path: Path = CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(registry.to_dict(), f, ensure_ascii=False, indent=2)


def load_cache(path: Path = CACHE_PATH) -> Optional[RegionsRegistry]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        regions = [Region(**r) for r in data.get("regions", [])]
        subRegions = [SubRegion(**s) for s in data.get("subRegions", [])]
        return RegionsRegistry(
            regions=regions,
            subRegions=subRegions,
            fetched_at=data.get("fetched_at", 0.0),
        )
    except Exception:
        return None


def get_registry(
    force_refresh: bool = False,
    max_age_seconds: int = CACHE_TTL_SECONDS,
) -> RegionsRegistry:
    """Get the regions registry, using cache if fresh enough.

    Set `force_refresh=True` to always pull from Sanity (and rewrite the cache).
    """
    if not force_refresh:
        cached = load_cache()
        if cached and (time.time() - cached.fetched_at) < max_age_seconds:
            return cached
    fresh = fetch_from_sanity()
    save_cache(fresh)
    return fresh


# --- Module-level convenience: lazy default registry ---

_default_registry: Optional[RegionsRegistry] = None


def _registry() -> RegionsRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = get_registry()
    return _default_registry


def all_region_names() -> list[str]:
    return _registry().all_region_names()


def region_for_subRegion(subRegion_name: str) -> Optional[str]:
    r = _registry().region_for_subRegion(subRegion_name)
    return r.name if r else None


def island_for_region(region_name: str) -> str:
    return _registry().island_for_region(region_name)


def island_for_subRegion(subRegion_name: str) -> str:
    return _registry().island_for_subRegion(subRegion_name)


def subRegions_for_region(region_name: str) -> list[str]:
    return [s.name for s in _registry().subRegions_for_region(region_name)]


# --- CLI entry ---

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    reg = get_registry(force_refresh=True)
    print(f"Cached to {CACHE_PATH}")
    print()
    print(f"{len(reg.regions)} regions:")
    for r in sorted(reg.regions, key=lambda x: x.name):
        # Re-derive island from current REGION_ISLAND (cache may be stale)
        island = REGION_ISLAND.get(r.name, "Unknown")
        suffix = " ⚠ unmapped to island" if island == "Unknown" else ""
        print(f"  {r.name:24s}  maori={(r.maori or '-'):24s}  island={island}{suffix}")

    print()
    warnings = reg.data_quality_warnings()
    if warnings:
        print("Data quality warnings:")
        for w in warnings:
            print(f"  ⚠ {w}")
    else:
        print("Data quality: clean")

    print()
    print(f"{len(reg.subRegions)} subRegions, grouped by region:")
    by_region: dict[str, list[str]] = {}
    for s in reg.subRegions:
        by_region.setdefault(s.region_name or "(no region link)", []).append(s.name)
    for region_name in sorted(by_region.keys()):
        print(f"  {region_name}:")
        for name in sorted(by_region[region_name]):
            print(f"    - {name}")
