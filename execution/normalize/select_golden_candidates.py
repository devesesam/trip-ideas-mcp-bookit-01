"""Select candidate "golden docs" for the normalization prompt eval set.

Pulls ~25 candidates from the clean (parseable) page corpus, varied across:
- Region (North Island, South Island, both representative)
- Place type (beach, walk, mountain, lake, urban, heritage, etc. — inferred from tags)
- Physical intensity proxy (presence of demanding-intensity tags)
- aiMetadata length (avoid the 3500+ truncation zone, prefer mid-range richness)

Output: `.tmp/golden_doc_candidates.json` — list of (id, title, region, subRegion, tags, length) for human review/selection.

The final 15 picks become the regression eval set in `execution/normalize/golden_docs/`.

Run:
    python execution/normalize/select_golden_candidates.py
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from sanity_client import SanityClient  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_PATH = PROJECT_ROOT / ".tmp" / "golden_doc_candidates.json"
TARGET_COUNT = 25
RANDOM_SEED = 42


def main() -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    random.seed(RANDOM_SEED)
    client = SanityClient()

    # Pull all clean-zone (length 1500–3499) populated pages with their tags + region.
    # 3500+ is the truncation danger zone; below 1500 is unusual and probably thin.
    print("Fetching clean-zone candidate pages (1500 ≤ aiMetadata length ≤ 3499)...")
    docs = client.query(
        '*[_type == "page" && length(aiMetadata) >= 1500 && length(aiMetadata) <= 3499]{'
        '_id, title, "aiLen": length(aiMetadata), '
        '"tag_names": tags[]->name, '
        '"region": subRegion->region->name, '
        '"subRegion": subRegion->name'
        '}'
    ) or []
    print(f"  {len(docs)} candidates in clean range\n")

    # Bucket by (island_proxy, broad place type proxy) for variety.
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for d in docs:
        region = d.get("region") or "Unknown"
        tags = [t for t in (d.get("tag_names") or []) if t]
        place_type = _broad_place_type(tags)
        buckets[(region, place_type)].append(d)

    print(f"Bucketed into {len(buckets)} (region, broad_type) cells.")

    # Pick at most 1 doc per bucket until we hit TARGET_COUNT.
    picks: list[dict] = []
    keys_shuffled = list(buckets.keys())
    random.shuffle(keys_shuffled)
    for key in keys_shuffled:
        if len(picks) >= TARGET_COUNT:
            break
        bucket = buckets[key]
        random.shuffle(bucket)
        # Prefer mid-length docs (richer content, lower chance of being a thin stub)
        bucket.sort(key=lambda d: -(d.get("aiLen") or 0))
        picks.append(bucket[0])

    # Always include a few canonical references we've already analyzed
    canonical_ids_to_include = [
        "00268b0a-3b30-4d44-80a5-c7d1ec7d7b33",  # Te Hakapureirei Beach
    ]
    for canonical_id in canonical_ids_to_include:
        if not any(p["_id"] == canonical_id for p in picks):
            doc = client.fetch_one(
                "*[_id == $id][0]{_id, title, 'aiLen': length(aiMetadata), "
                "'tag_names': tags[]->name, "
                "'region': subRegion->region->name, "
                "'subRegion': subRegion->name}",
                params={"id": canonical_id},
            )
            if doc:
                picks.append(doc)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(picks, f, ensure_ascii=False, indent=2)

    print(f"\nSelected {len(picks)} candidates → {OUTPUT_PATH}")
    print()
    by_region: dict[str, int] = defaultdict(int)
    by_type: dict[str, int] = defaultdict(int)
    for p in picks:
        by_region[p.get("region") or "Unknown"] += 1
        place_type = _broad_place_type(p.get("tag_names") or [])
        by_type[place_type] += 1

    print("Coverage by region:")
    for k, v in sorted(by_region.items()):
        print(f"  {k:24s} {v}")
    print()
    print("Coverage by broad place type:")
    for k, v in sorted(by_type.items()):
        print(f"  {k:24s} {v}")
    print()
    print("Picks (title — region/subRegion — top tag — length):")
    for p in sorted(picks, key=lambda x: (x.get("region") or "", x.get("title") or "")):
        tags = [t for t in (p.get("tag_names") or []) if t]
        first_tag = tags[0] if tags else "(no tags)"
        sub = p.get("subRegion") or "—"
        region = p.get("region") or "—"
        print(f"  {p.get('title', '')[:45]:45s}  {region}/{sub:24s}  {first_tag:24s}  {p.get('aiLen', 0)}")


def _broad_place_type(tags: list[str]) -> str:
    """Map a tag list to a coarse place-type bucket for diversity sampling."""
    if not tags:
        return "untagged"
    tagset = {t.lower() for t in tags if t}
    # Order matters — first match wins
    rules = [
        ("beach", {"beaches", "coastal walks", "coastal cliffs", "sea caves", "tidal lagoons"}),
        ("alpine", {"alpine routes", "mountains", "glaciers", "high country", "glacial lakes"}),
        ("water", {"lakes", "rivers", "lakeside walk", "wetlands", "waterfalls"}),
        ("forest", {"forests", "forest walks", "rainforest", "kauri forests", "podocarp forests", "beech forests"}),
        ("urban", {"urban walks", "city walks", "art galleries", "museums", "architecture", "botanic gardens"}),
        ("heritage", {"historic sites", "historical sites", "heritage precincts", "memorials", "mining history"}),
        ("track", {"tramps", "great walks", "multi-day walks", "te araroa", "te araroa trail"}),
        ("walk", {"walks", "short walks", "scenic loops", "boardwalks", "hikes"}),
        ("reserve", {"national parks", "regional parks", "scenic reserves", "marine reserves"}),
        ("scenic_drive", {"scenic drive", "scenic drives"}),
        ("lookout", {"lookouts"}),
    ]
    for label, marker_tags in rules:
        if tagset & marker_tags:
            return label
    return "other"


if __name__ == "__main__":
    main()
