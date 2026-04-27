"""Audit aiMetadata quality across the page corpus.

Reports:
- Parse-error rate
- Length distribution (overall + failures)
- Truncation pattern (do failures cluster at specific lengths?)
- Top-level field presence (% of parseable docs that include each key)
- Value-type stability per field (string vs array vs null inconsistency)
- Sample failures with their tail contents (to diagnose truncation)

Run:
    python execution/audit/aimetadata_quality.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sanity_client import SanityClient

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


CHUNK = 200


def main() -> None:
    client = SanityClient()

    print("=== Pulling page IDs with populated aiMetadata ===")
    ids = client.query(
        '*[_type == "page" && length(aiMetadata) > 10]._id'
    ) or []
    print(f"  {len(ids)} pages\n")

    parse_ok = 0
    parse_fail = 0
    field_keys_per_doc: list[set[str]] = []
    field_value_types: dict[str, Counter[str]] = defaultdict(Counter)
    length_buckets_all: Counter[int] = Counter()
    length_buckets_failed: Counter[int] = Counter()
    failures: list[dict] = []

    for start in range(0, len(ids), CHUNK):
        batch_ids = ids[start : start + CHUNK]
        docs = client.query(
            "*[_id in $ids]{_id, title, 'aiLen': length(aiMetadata), aiMetadata}",
            params={"ids": batch_ids},
        ) or []
        for d in docs:
            ai_str = d.get("aiMetadata") or ""
            ai_len = d.get("aiLen") or len(ai_str)
            bucket = (ai_len // 500) * 500
            length_buckets_all[bucket] += 1

            try:
                parsed = json.loads(ai_str)
                parse_ok += 1
                if isinstance(parsed, dict):
                    field_keys_per_doc.append(set(parsed.keys()))
                    for k, v in parsed.items():
                        if v is None:
                            type_name = "None"
                        elif isinstance(v, list):
                            type_name = "list[empty]" if not v else f"list[{type(v[0]).__name__}]"
                        else:
                            type_name = type(v).__name__
                        field_value_types[k][type_name] += 1
            except json.JSONDecodeError as e:
                parse_fail += 1
                length_buckets_failed[bucket] += 1
                failures.append({
                    "id": d.get("_id"),
                    "title": d.get("title"),
                    "length": ai_len,
                    "error": str(e)[:120],
                    "tail": (ai_str[-150:] if ai_str else "").replace("\n", "\\n"),
                })

        print(f"  processed {min(start + CHUNK, len(ids))}/{len(ids)}")

    total = parse_ok + parse_fail
    pct_ok = 100 * parse_ok / total if total else 0

    print()
    print("=== Parse rate ===")
    print(f"  Parseable: {parse_ok} / {total} ({pct_ok:.1f}%)")
    print(f"  Failed:    {parse_fail} ({100 - pct_ok:.1f}%)")

    print()
    print("=== Length distribution (all populated docs) ===")
    for bucket in sorted(length_buckets_all.keys()):
        bar = "#" * min(60, length_buckets_all[bucket] // 10)
        print(f"  {bucket:5d}–{bucket + 499:5d}: {length_buckets_all[bucket]:5d}  {bar}")

    print()
    print("=== Length distribution (FAILURES only) ===")
    if length_buckets_failed:
        for bucket in sorted(length_buckets_failed.keys()):
            print(f"  {bucket:5d}–{bucket + 499:5d}: {length_buckets_failed[bucket]} failed")
    else:
        print("  (no failures)")

    print()
    print("=== Sample failures (last 150 chars to spot truncation) ===")
    for f in failures[:10]:
        print(f"  {f['title']!r} (id={f['id'][:8]}…, length={f['length']})")
        print(f"    error: {f['error']}")
        print(f"    tail:  ...{f['tail'][-150:]!r}")

    print()
    print(f"=== Field presence across {parse_ok} parseable docs ===")
    all_keys: Counter[str] = Counter()
    for ks in field_keys_per_doc:
        for k in ks:
            all_keys[k] += 1
    for k, c in sorted(all_keys.items(), key=lambda x: -x[1]):
        pct = 100 * c / parse_ok if parse_ok else 0
        bar = "#" * int(pct / 2)
        print(f"  {k:30s} {c:5d} ({pct:5.1f}%)  {bar}")

    print()
    print("=== Value-type stability per field ===")
    for k in sorted(field_value_types.keys()):
        types = field_value_types[k]
        if len(types) == 1:
            t, c = next(iter(types.items()))
            print(f"  {k:30s} stable: {t} ({c})")
        else:
            sorted_types = sorted(types.items(), key=lambda x: -x[1])
            print(f"  {k:30s} MIXED: {sorted_types}")


if __name__ == "__main__":
    main()
