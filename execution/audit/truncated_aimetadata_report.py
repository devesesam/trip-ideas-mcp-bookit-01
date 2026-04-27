"""Generate a CSV report of pages with truncated/unparseable aiMetadata.

Produces `.tmp/truncated_aimetadata_docs.csv` with one row per broken doc:
  _id, title, region, subRegion, length, parse_error, tail_100

Intended use: send to Douglas so he can re-run the upstream metadata generator
(with a higher max_tokens cap) on these specific pages, or decide they're skip-
worthy for v1.

Run:
    python execution/audit/truncated_aimetadata_report.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from sanity_client import SanityClient  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_PATH = PROJECT_ROOT / ".tmp" / "truncated_aimetadata_docs.csv"
CHUNK = 200


def main() -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    client = SanityClient()
    print("Fetching all populated aiMetadata page IDs...")
    ids = client.query(
        '*[_type == "page" && length(aiMetadata) > 10]._id'
    ) or []
    print(f"  {len(ids)} populated pages\n")

    failures: list[dict] = []
    for start in range(0, len(ids), CHUNK):
        batch_ids = ids[start : start + CHUNK]
        docs = client.query(
            "*[_id in $ids]{"
            "_id, title, _updatedAt, "
            '"region": subRegion->region->name, '
            '"subRegion": subRegion->name, '
            '"aiLen": length(aiMetadata), aiMetadata'
            "}",
            params={"ids": batch_ids},
        ) or []
        for d in docs:
            ai_str = d.get("aiMetadata") or ""
            ai_len = d.get("aiLen") or len(ai_str)
            try:
                json.loads(ai_str)
            except json.JSONDecodeError as e:
                failures.append({
                    "_id": d.get("_id", ""),
                    "title": d.get("title", "") or "",
                    "region": d.get("region", "") or "",
                    "subRegion": d.get("subRegion", "") or "",
                    "_updatedAt": d.get("_updatedAt", "") or "",
                    "length": ai_len,
                    "parse_error": str(e)[:200],
                    "tail_100": (ai_str[-100:] if ai_str else "").replace("\n", "\\n"),
                })
        print(f"  scanned {min(start + CHUNK, len(ids))}/{len(ids)}")

    print(f"\nFound {len(failures)} truncated/unparseable docs.")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["_id", "title", "region", "subRegion", "_updatedAt",
                  "length", "parse_error", "tail_100"]
    with OUTPUT_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in sorted(failures, key=lambda x: (-x["length"], x["title"])):
            writer.writerow(row)

    print(f"Wrote {OUTPUT_PATH}")
    print(f"\nFirst 10 entries (sorted by length desc):")
    for row in sorted(failures, key=lambda x: -x["length"])[:10]:
        print(f"  {row['title']!r:50s} (region={row['region']!r}, len={row['length']})")


if __name__ == "__main__":
    main()
