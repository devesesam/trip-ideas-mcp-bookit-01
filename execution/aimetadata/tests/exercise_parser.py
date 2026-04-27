"""Exercise the aiMetadata parser against real Sanity docs.

Pulls the 26 golden-candidate doc IDs (from `.tmp/golden_doc_candidates.json`)
plus a few known-truncated docs from the audit, parses each, and prints a
compact summary. Useful as a smoke test when the parser changes.

This is a sanity-check script, not a unit test (those go in `test_parser.py`).

Run from project root:
    python execution/aimetadata/tests/exercise_parser.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make sibling packages importable
_PKG_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from aimetadata import parse  # noqa: E402
from sanity_client import SanityClient  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CANDIDATES_PATH = PROJECT_ROOT / ".tmp" / "golden_doc_candidates.json"

# A few known-truncated IDs (from .tmp/truncated_aimetadata_docs.csv)
KNOWN_TRUNCATED_IDS: list[str] = []  # populated lazily from the CSV


def main() -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    client = SanityClient()

    # Load candidate IDs
    if not CANDIDATES_PATH.exists():
        print(f"No candidate file at {CANDIDATES_PATH}. Run select_golden_candidates.py first.")
        sys.exit(1)
    candidates = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    candidate_ids = [c["_id"] for c in candidates]

    # Add 3 known-truncated docs to test the parse_error path
    truncated_csv = PROJECT_ROOT / ".tmp" / "truncated_aimetadata_docs.csv"
    if truncated_csv.exists():
        import csv
        with truncated_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if i >= 3:
                    break
                KNOWN_TRUNCATED_IDS.append(row["_id"])

    all_ids = candidate_ids + KNOWN_TRUNCATED_IDS
    print(f"Exercising parser against {len(candidate_ids)} clean candidates "
          f"+ {len(KNOWN_TRUNCATED_IDS)} known-truncated docs\n")

    docs = client.query(
        "*[_id in $ids]{_id, title, aiMetadata}", params={"ids": all_ids}
    ) or []

    parse_ok = 0
    parse_fail = 0
    duration_band_hits = 0
    intensity_hits = 0
    settlement_hits = 0
    nearby_places_hits = 0
    track_trail_hits = 0

    print(f"{'TITLE':<45} {'parse':<7} {'subtype':<8} {'duration':<14} "
          f"{'intensity':<10} {'dog':<14} {'nearby':<7} {'settle'}")
    print("-" * 130)

    for doc in docs:
        ai_str = doc.get("aiMetadata") or ""
        parsed = parse(ai_str)

        if parsed.parse_error:
            parse_fail += 1
            print(f"{doc.get('title', '')[:45]:<45} ❌ ERROR  parse_error: {parsed.parse_error_message[:60] if parsed.parse_error_message else ''}")
            continue

        parse_ok += 1
        if parsed.duration_band():
            duration_band_hits += 1
        if parsed.physical_intensity_hint():
            intensity_hits += 1
        if parsed.settlement():
            settlement_hits += 1
        if parsed.nearby_places:
            nearby_places_hits += 1
        if parsed.track_trail:
            track_trail_hits += 1

        print(
            f"{doc.get('title', '')[:45]:<45} "
            f"✓       "
            f"{(parsed.track_trail.primary_type if parsed.track_trail else '-') or '-':<8} "
            f"{parsed.duration_band() or '-':<14} "
            f"{parsed.physical_intensity_hint() or '-':<10} "
            f"{parsed.dog_friendly_kind:<14} "
            f"{len(parsed.nearby_places):<7} "
            f"{parsed.settlement() or '-'}"
        )

    print()
    print(f"Parse rate: {parse_ok}/{parse_ok + parse_fail} ok, {parse_fail} errors (expected ~3)")
    print(f"Derived signals (across {parse_ok} parseable):")
    print(f"  duration_band:           {duration_band_hits}/{parse_ok}")
    print(f"  physical_intensity_hint: {intensity_hits}/{parse_ok}")
    print(f"  settlement():            {settlement_hits}/{parse_ok}")
    print(f"  nearby_places present:   {nearby_places_hits}/{parse_ok}")
    print(f"  track_trail present:     {track_trail_hits}/{parse_ok}")


if __name__ == "__main__":
    main()
