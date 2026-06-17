"""Audit: our tag mappings (`tag_mapping.py` + `tag_definitions.py`) vs Sanity's
live tag list.

The chatbot's tag-related behaviour depends on two hand-curated tables on our
side staying in sync with Sanity:

  - `execution/normalize/tag_mapping.py`     : per-tag mapping into our internal
                                                filter schema (themes, subtypes,
                                                accessibility, seasonality, …).
                                                Consumed by `search_places`.
  - `execution/tags/tag_definitions.py`      : the working definitions + keyword
                                                stems for the underused-tag
                                                suggestion automation.

Both can drift from Sanity over time — tags get renamed (4WD Access → Gravel
Roads), retired, or freshly added. Drift on our side surfaces as silent
chatbot failures (a `tags=["4WD Access"]` filter returning zero against an
already-renamed corpus) and stale editorial automation.

This script is READ-ONLY against Sanity. It performs no writes, no patches,
no mutations. It just reports.

Four buckets:

  ❌ STALE IN OUR CODE      mapping/definition exists in our code but the
                            tag is not present in live Sanity. Likely
                            renamed or retired. Most actionable bucket.
  ⚠️  SANITY TAGS NOT MAPPED   tags exist in Sanity and are in use, but our
                            tag_mapping.py has no entry. Chatbot can't
                            filter by them via the `themes` lever
                            (interest_text fallback still works).
  ✅ CLEAN MAPPINGS         the tag exists in Sanity AND we have a mapping.
  💡 UNUSED IN SANITY       tags that exist in Sanity but appear on zero
                            pages. Candidates for Douglas to prune. Purely
                            informational.

Exit code is non-zero when STALE IN OUR CODE is non-empty (the actionable
chatbot-failure case), so this could wire into CI later.

Run:
    python execution/audit/tag_mapping_parity.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from normalize.tag_mapping import TAG_MAPPINGS  # noqa: E402
from sanity_client import SanityClient  # noqa: E402
from tags.tag_definitions import TAG_DEFINITIONS  # noqa: E402


# Threshold for "low-use" tags worth flagging to Douglas as prune candidates.
# 0 → definitely worth a look; we include >0 in suggestions if very low.
_PRUNE_THRESHOLD_USES = 0


def fetch_sanity_tags(client: SanityClient) -> dict[str, int]:
    """Return {tag_name: page_use_count}, fully read-only."""
    rows = client.query(
        '*[_type == "tag"]{name, '
        '"uses": count(*[_type == "page" && references(^._id)])} '
        '| order(name asc)'
    ) or []
    return {r["name"]: int(r.get("uses") or 0) for r in rows if r.get("name")}


def run_audit() -> int:
    print("=" * 78)
    print("  Tag mappings ↔ Sanity tags parity audit (READ-ONLY)")
    print("=" * 78)

    client = SanityClient()
    sanity_tags = fetch_sanity_tags(client)
    sanity_names = set(sanity_tags.keys())

    mapping_names = set(TAG_MAPPINGS.keys())
    definition_names = {entry["name"] for entry in TAG_DEFINITIONS}
    our_names = mapping_names | definition_names

    # --- Bucket 1: stale in our code (drift bugs) ---
    stale: list[tuple[str, list[str]]] = []  # (tag_name, [where it lives in our code])
    for name in sorted(our_names):
        if name in sanity_names:
            continue
        wheres = []
        if name in mapping_names:
            wheres.append("tag_mapping.py")
        if name in definition_names:
            wheres.append("tag_definitions.py")
        # Find closest live Sanity name as a rename suggestion
        closest = _closest_match(name, sanity_names)
        stale.append((name, wheres, closest))

    # --- Bucket 2: in Sanity, used, but we have no mapping ---
    unmapped: list[tuple[str, int]] = []
    for name in sorted(sanity_names):
        if name in mapping_names:
            continue
        uses = sanity_tags[name]
        if uses > 0:
            unmapped.append((name, uses))

    # --- Bucket 3: clean ---
    clean_mappings = sorted(mapping_names & sanity_names)

    # --- Bucket 4: unused in Sanity (prune candidates) ---
    unused = sorted(
        (name, uses) for name, uses in sanity_tags.items()
        if uses <= _PRUNE_THRESHOLD_USES
    )

    # =================================================================
    # Report
    # =================================================================

    print(f"\nSanity tags fetched: {len(sanity_names)} "
          f"(in use: {sum(1 for u in sanity_tags.values() if u > 0)}, "
          f"unused: {sum(1 for u in sanity_tags.values() if u == 0)})")
    print(f"tag_mapping.py entries : {len(mapping_names)}")
    print(f"tag_definitions.py entries: {len(definition_names)}")

    if stale:
        print(f"\n❌ STALE IN OUR CODE ({len(stale)}) — chatbot filter failures waiting to happen")
        for name, wheres, closest in stale:
            print(f"   {name!r}  in {', '.join(wheres)}")
            print(f"      closest live tag: {closest}")

    if unmapped:
        print(f"\n⚠️  SANITY TAGS NOT MAPPED ({len(unmapped)}) — exists in Sanity, no entry in tag_mapping.py")
        # Sort by usage descending so high-traffic gaps surface first
        unmapped.sort(key=lambda x: -x[1])
        for name, uses in unmapped:
            print(f"   {name!r:40s} used on {uses} pages")

    if unused:
        print(f"\n💡 UNUSED IN SANITY ({len(unused)}) — zero page uses, candidates for Douglas to prune")
        for name, _ in unused:
            print(f"   {name!r}")

    print(f"\n✅ CLEAN MAPPINGS: {len(clean_mappings)} tags present in both Sanity and tag_mapping.py")

    # =================================================================
    # Summary
    # =================================================================

    print()
    print("=" * 78)
    if stale:
        print(f"  RESULT: {len(stale)} stale entry/entries on our side. Update "
              f"tag_mapping.py / tag_definitions.py to match live Sanity.")
        print("=" * 78)
        return 1
    if unmapped:
        print(f"  RESULT: 0 stale entries, but {len(unmapped)} Sanity tag(s) "
              f"have no mapping — chatbot can't filter by them.")
        print("=" * 78)
        return 0
    print(f"  RESULT: clean. Tag mappings are in sync with Sanity.")
    print("=" * 78)
    return 0


def _closest_match(needle: str, haystack: set[str]) -> str:
    """Quick rename suggestion via rapidfuzz."""
    try:
        from rapidfuzz import process
        if not haystack:
            return "(none)"
        m = process.extractOne(needle, list(haystack))
        return f"{m[0]!r} (score {m[1]:.0f})" if m else "(none)"
    except ImportError:
        return "(rapidfuzz not installed)"


if __name__ == "__main__":
    # Windows consoles default to cp1252; force UTF-8 so ↔ / ❌ / ✅ render
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    sys.exit(run_audit())
