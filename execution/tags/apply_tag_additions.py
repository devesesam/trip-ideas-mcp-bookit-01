"""Apply approved tag additions to Sanity Place Pages.

Reads `.tmp/tag_addition_pass/proposals.csv` and applies tag additions where
the `approve` column equals 'y' (case-insensitive).

For each affected article, in a single Sanity patch mutation:
  1. Append new tag _references to `tags[]` (deduped against existing refs).
  2. Append new tag _names to `aiMetadata.tags` (deduped). Skipped if
     `aiMetadata` is missing or unparseable.

Outputs:
  - `.tmp/tag_addition_pass/applied.jsonl` — one line per mutated doc
  - `.tmp/tag_addition_pass/apply_errors.jsonl` — per-doc failures

Run:
    python execution/tags/apply_tag_additions.py --dry-run     # preview only
    python execution/tags/apply_tag_additions.py               # apply for real
"""

from __future__ import annotations

import argparse
import csv
import json
import secrets
import sys
import time
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sanity_client import SanityClient  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


OUT_DIR = Path(__file__).resolve().parent.parent.parent / ".tmp" / "tag_addition_pass"
PROPOSALS_CSV = OUT_DIR / "proposals.csv"
RESOLVED_TAGS_JSON = OUT_DIR / "resolved_tag_ids.json"
APPLIED_JSONL = OUT_DIR / "applied.jsonl"
APPLY_ERRORS_JSONL = OUT_DIR / "apply_errors.jsonl"

# Sanity recommends keeping mutation payloads modest; chunk by article count
BATCH_SIZE = 25


def load_tag_id_map() -> dict[str, str]:
    """Return {tag_name: tag_doc_id} for the 15 tags from resolved_tag_ids.json."""
    if not RESOLVED_TAGS_JSON.exists():
        raise FileNotFoundError(
            f"{RESOLVED_TAGS_JSON} not found. Run resolve_tag_ids.py first."
        )
    with open(RESOLVED_TAGS_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {name: info["_id"] for name, info in data["resolved"].items()}


def load_approved_proposals() -> dict[str, list[str]]:
    """Read proposals.csv and aggregate approved (article_id -> [tag_name]).

    Approval rule: rows where `approve` column == 'y' (any case, with whitespace
    stripped). Empty `proposed_tag` rows are ignored.
    """
    if not PROPOSALS_CSV.exists():
        raise FileNotFoundError(f"{PROPOSALS_CSV} not found.")

    approved: dict[str, list[str]] = {}
    with open(PROPOSALS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get("approve") or "").strip().lower() != "y":
                continue
            article_id = (row.get("_id") or "").strip()
            tag_name = (row.get("proposed_tag") or "").strip()
            if not article_id or not tag_name:
                continue
            approved.setdefault(article_id, [])
            if tag_name not in approved[article_id]:
                approved[article_id].append(tag_name)
    return approved


def fetch_current_state(client: SanityClient, article_ids: list[str]) -> dict[str, dict]:
    """Fetch current tags[] (with _key) and aiMetadata for the given article IDs."""
    out: dict[str, dict] = {}
    # Chunk to keep GROQ filter sane
    for i in range(0, len(article_ids), 50):
        chunk = article_ids[i:i + 50]
        groq = (
            "*[_id in $ids]{_id, title, 'tag_refs': tags[]{_key, _ref, _type}, aiMetadata}"
        )
        docs = client.query(groq, params={"ids": chunk}) or []
        for d in docs:
            out[d["_id"]] = d
    return out


def build_patch_for_article(
    article_id: str,
    article_state: dict,
    tag_names_to_add: list[str],
    tag_name_to_id: dict[str, str],
) -> tuple[dict | None, dict]:
    """Construct a Sanity patch mutation for one article.

    Returns (mutation, log_entry).
      mutation: None if there's nothing to do (already has all tags).
      log_entry: per-article record of what changed (for applied.jsonl)
    """
    log: dict = {
        "_id": article_id,
        "title": article_state.get("title"),
        "requested_tag_names": tag_names_to_add,
        "added_tag_names": [],
        "added_tag_ids": [],
        "aimetadata_updated": False,
        "skipped_reason": None,
    }

    existing_refs = article_state.get("tag_refs") or []
    existing_ref_ids = {r.get("_ref") for r in existing_refs if r.get("_ref")}

    # Build new tag refs (skip already-present)
    new_refs: list[dict] = []
    added_names: list[str] = []
    for tag_name in tag_names_to_add:
        tag_id = tag_name_to_id.get(tag_name)
        if not tag_id:
            log.setdefault("missing_tag_ids", []).append(tag_name)
            continue
        if tag_id in existing_ref_ids:
            continue
        new_refs.append({
            "_type": "reference",
            "_ref": tag_id,
            "_key": secrets.token_hex(6),
        })
        added_names.append(tag_name)

    # Build new aiMetadata if present + parseable
    new_aimetadata_str: str | None = None
    raw_md = article_state.get("aiMetadata")
    if raw_md and added_names:
        try:
            md = json.loads(raw_md)
            if isinstance(md, dict):
                existing_md_tags = md.get("tags") or []
                if not isinstance(existing_md_tags, list):
                    existing_md_tags = []
                changed = False
                for name in added_names:
                    if name not in existing_md_tags:
                        existing_md_tags.append(name)
                        changed = True
                if changed:
                    md["tags"] = existing_md_tags
                    new_aimetadata_str = json.dumps(md, ensure_ascii=False)
        except json.JSONDecodeError:
            # Truncated/broken — log and skip aiMetadata update for this doc
            log["aimetadata_skip_reason"] = "json_parse_error"

    if not new_refs and not new_aimetadata_str:
        log["skipped_reason"] = "no_changes"
        return None, log

    # Construct the patch.
    # We set `tags` to the full new array (existing refs + new refs). Using
    # `set` rather than `insert` is bulletproof for both empty and non-empty
    # arrays, with no edge cases. Existing refs keep their _key values.
    new_full_tags = [
        {
            "_type": "reference",
            "_ref": r["_ref"],
            "_key": r.get("_key") or secrets.token_hex(6),
        }
        for r in existing_refs
        if r.get("_ref")
    ] + new_refs

    set_payload: dict = {"tags": new_full_tags}
    if new_aimetadata_str is not None:
        set_payload["aiMetadata"] = new_aimetadata_str
        log["aimetadata_updated"] = True

    mutation = {
        "patch": {
            "id": article_id,
            "set": set_payload,
        }
    }

    log["added_tag_names"] = added_names
    log["added_tag_ids"] = [
        tag_name_to_id[n] for n in added_names if n in tag_name_to_id
    ]
    return mutation, log


def chunks(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def run(dry_run: bool, limit: int | None) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag_id_map = load_tag_id_map()
    approved = load_approved_proposals()
    if limit:
        approved = dict(list(approved.items())[:limit])

    if not approved:
        print("No approved proposals found. Mark rows with `approve=y` in proposals.csv first.")
        return

    print(f"Loaded {len(approved)} approved articles ({sum(len(v) for v in approved.values())} tag additions).")

    client = SanityClient()
    print(f"Connected to project={client.project_id} dataset={client.dataset} api={client.api_version}")
    print(f"Mode: {'DRY-RUN (no writes)' if dry_run else 'LIVE (writes will occur)'}")

    article_ids = list(approved.keys())
    print(f"Fetching current state for {len(article_ids)} articles...")
    state = fetch_current_state(client, article_ids)
    missing = [aid for aid in article_ids if aid not in state]
    if missing:
        print(f"  WARNING: {len(missing)} approved article IDs not found in Sanity: {missing[:5]}")

    # Build mutations + logs
    mutations: list[dict] = []
    logs: list[dict] = []
    for article_id in article_ids:
        if article_id not in state:
            logs.append({
                "_id": article_id,
                "skipped_reason": "article_not_found",
                "requested_tag_names": approved[article_id],
            })
            continue
        mutation, log = build_patch_for_article(
            article_id, state[article_id], approved[article_id], tag_id_map
        )
        if mutation is not None:
            mutations.append(mutation)
        logs.append(log)

    print(f"Built {len(mutations)} mutations.")
    if dry_run:
        # Print first 3 mutations for eyeball check
        print("\nFirst 3 mutation payloads:")
        for m in mutations[:3]:
            print(json.dumps(m, indent=2, ensure_ascii=False)[:1200])
            print("---")
        # Also write logs (with applied=false) so the user can review intent
        with open(APPLIED_JSONL.with_suffix(".dryrun.jsonl"), "w", encoding="utf-8") as f:
            for log in logs:
                log["dry_run"] = True
                f.write(json.dumps(log, ensure_ascii=False) + "\n")
        print(f"\nDry-run log written to {APPLIED_JSONL.with_suffix('.dryrun.jsonl')}")
        return

    # LIVE apply, in chunks
    print(f"\nApplying in chunks of {BATCH_SIZE}...")
    applied_f = open(APPLIED_JSONL, "a", encoding="utf-8")
    errors_f = open(APPLY_ERRORS_JSONL, "a", encoding="utf-8")

    # Map log entries by article ID so we can mark which succeeded per chunk
    log_by_id = {log["_id"]: log for log in logs if "_id" in log}

    total_chunks = (len(mutations) + BATCH_SIZE - 1) // BATCH_SIZE
    start = time.time()
    for chunk_idx, chunk in enumerate(chunks(mutations, BATCH_SIZE), start=1):
        chunk_ids = [m["patch"]["id"] for m in chunk]
        try:
            resp = client.mutate(chunk)
            for aid in chunk_ids:
                log = log_by_id.get(aid, {"_id": aid})
                log["applied"] = True
                log["applied_at"] = time.time()
                applied_f.write(json.dumps(log, ensure_ascii=False) + "\n")
            applied_f.flush()
            print(f"  Chunk {chunk_idx}/{total_chunks} OK ({len(chunk_ids)} docs)")
        except Exception as e:
            for aid in chunk_ids:
                log = log_by_id.get(aid, {"_id": aid})
                log["applied"] = False
                log["error"] = f"{type(e).__name__}: {str(e)[:300]}"
                errors_f.write(json.dumps(log, ensure_ascii=False) + "\n")
            errors_f.flush()
            print(f"  Chunk {chunk_idx}/{total_chunks} FAILED: {e}")

    applied_f.close()
    errors_f.close()
    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Build mutations and print preview, but do NOT write to Sanity")
    parser.add_argument("--limit", type=int,
                        help="Apply at most N articles (useful for first-batch sanity check)")
    args = parser.parse_args()
    run(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
