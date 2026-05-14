"""Resolve the 15 underused tags Douglas flagged to their Sanity tag doc IDs.

Checks each name against `*[_type=='tag']`, and also surfaces fuzzy near-matches
(case + diacritic insensitive) so we catch spelling variants like
`Māori History` vs `Maori History`.

For every requested tag, prints:
  - exact match doc(s) with _id and current place-page count
  - near-match doc(s) (different spelling) with the same info

Writes a JSON map of {tag_name -> {_id, places_count}} to
`.tmp/tag_addition_pass/resolved_tag_ids.json` for downstream scripts.

Run:
    python execution/tags/resolve_tag_ids.py
"""

from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

# Allow `from sanity_client import ...` when run from execution/tags/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sanity_client import SanityClient

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


REQUESTED_TAGS = [
    "4WD Access",
    "Beech Forests",
    "Biosecurity Access",
    "Boat Access",
    "Caves",
    "City Parks",
    "Freedom Camping",
    "Glaciers",
    "Historical Trails",
    "Māori History",
    "Night Walks",
    "Restoration Sites",
    "Seasonal Access",
    "Surfing",
    "Town Parks",
]


def fold(s: str) -> str:
    """Lowercase + strip diacritics for fuzzy comparison."""
    if not isinstance(s, str):
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    ).lower().strip()


def main() -> None:
    client = SanityClient()
    print(
        f"Connected to project={client.project_id} dataset={client.dataset} "
        f"api={client.api_version}"
    )

    all_tags = client.query(
        "*[_type == 'tag']{_id, name, 'slug': slug.current, "
        "'places_count': count(*[_type == 'page' && references(^._id)])}"
    ) or []
    print(f"\nLoaded {len(all_tags)} tag docs from Sanity")

    by_folded: dict[str, list[dict]] = {}
    for tag in all_tags:
        by_folded.setdefault(fold(tag.get("name") or ""), []).append(tag)

    resolved: dict[str, dict] = {}
    missing: list[str] = []
    ambiguous: list[tuple[str, list[dict]]] = []

    print("\n=== Resolution per requested tag ===")
    for requested in REQUESTED_TAGS:
        folded = fold(requested)
        candidates = by_folded.get(folded, [])

        exact_matches = [t for t in candidates if (t.get("name") or "") == requested]
        near_matches = [t for t in candidates if (t.get("name") or "") != requested]

        print(f"\n{requested!r}")
        if exact_matches:
            for m in exact_matches:
                print(
                    f"  EXACT: _id={m['_id']!r}  name={m['name']!r}  "
                    f"slug={m.get('slug')!r}  places={m['places_count']}"
                )
        for m in near_matches:
            print(
                f"  NEAR : _id={m['_id']!r}  name={m['name']!r}  "
                f"slug={m.get('slug')!r}  places={m['places_count']}"
            )

        if exact_matches:
            primary = exact_matches[0]
            resolved[requested] = {
                "_id": primary["_id"],
                "name": primary["name"],
                "slug": primary.get("slug"),
                "places_count": primary["places_count"],
                "near_matches": [
                    {
                        "_id": m["_id"],
                        "name": m["name"],
                        "slug": m.get("slug"),
                        "places_count": m["places_count"],
                    }
                    for m in near_matches
                ],
            }
            if len(exact_matches) > 1:
                ambiguous.append((requested, exact_matches))
        elif len(near_matches) == 1:
            print(f"  -> Adopting near-match as resolution (no exact found)")
            primary = near_matches[0]
            resolved[requested] = {
                "_id": primary["_id"],
                "name": primary["name"],
                "slug": primary.get("slug"),
                "places_count": primary["places_count"],
                "near_matches": [],
                "note": "resolved via near-match (diacritic/case variant)",
            }
        elif len(near_matches) > 1:
            print(f"  -> AMBIGUOUS: multiple near-matches and no exact")
            ambiguous.append((requested, near_matches))
        else:
            print(f"  -> MISSING from Sanity tag taxonomy")
            missing.append(requested)

    # Also surface tags Douglas might consider near-duplicates by name
    # (e.g., Heritage Trails vs Historical Trails)
    print("\n=== Related-name scan (manual review) ===")
    related_pairs = [
        ("Historical Trails", "Heritage Trails"),
        ("Caves", "Sea Caves"),
        ("Town Parks", "City Parks"),
        ("Town Parks", "Regional Parks"),
        ("Surfing", "Beaches"),
    ]
    for a, b in related_pairs:
        a_match = [t for t in all_tags if (t.get("name") or "").lower() == a.lower()]
        b_match = [t for t in all_tags if (t.get("name") or "").lower() == b.lower()]
        if a_match and b_match:
            print(
                f"  {a!r} (places={a_match[0]['places_count']}) "
                f"<-> {b!r} (places={b_match[0]['places_count']})"
            )

    print("\n=== Summary ===")
    print(f"  Resolved: {len(resolved)} / {len(REQUESTED_TAGS)}")
    print(f"  Missing : {missing}")
    print(f"  Ambiguous: {[r[0] for r in ambiguous]}")

    out_dir = Path(__file__).resolve().parent.parent.parent / ".tmp" / "tag_addition_pass"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "resolved_tag_ids.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "resolved": resolved,
                "missing": missing,
                "ambiguous": [
                    {"requested": r, "candidates": cands} for r, cands in ambiguous
                ],
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
