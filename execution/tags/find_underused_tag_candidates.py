"""Find Place Pages that should be tagged with one of the 15 underused tags.

Pipeline:
  1. Pull all `page` docs from Sanity (paginated), including aiMetadata + current tags.
  2. For each doc, parse aiMetadata, build a searchable text blob.
  3. Regex pre-filter: which of the 15 tag positive_keyword lists hit?
  4. For docs with ≥1 hit, ask Claude Haiku 4.5 which (0–2) of the matched tags
     genuinely apply, with justification + confidence.
  5. Write proposals.jsonl + proposals.csv + skipped.jsonl in .tmp/tag_addition_pass/.

Resumable: on startup, reads proposals.jsonl + skipped.jsonl + errors.jsonl
and skips _ids already processed.

Run:
    python execution/tags/find_underused_tag_candidates.py [--limit N] [--concurrency 8]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

# Allow imports from execution/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sanity_client import SanityClient  # noqa: E402
from aimetadata.parser import parse as parse_aimetadata, ParsedAiMetadata  # noqa: E402

# Local module
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tag_definitions import TAG_DEFINITIONS  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


# =====================================================================
# Config
# =====================================================================

OUT_DIR = Path(__file__).resolve().parent.parent.parent / ".tmp" / "tag_addition_pass"
PROPOSALS_JSONL = OUT_DIR / "proposals.jsonl"
SKIPPED_JSONL = OUT_DIR / "skipped.jsonl"
ERRORS_JSONL = OUT_DIR / "errors.jsonl"
PROPOSALS_CSV = OUT_DIR / "proposals.csv"

MODEL = "claude-haiku-4-5"
PRICING = {"input_per_M": 1.0, "output_per_M": 5.0}   # USD per million tokens

PAGE_BATCH = 200   # paginated fetch size for Sanity


# =====================================================================
# Pre-compile regexes per tag for fast pre-filtering
# =====================================================================

def _compile_keyword_patterns() -> dict[str, list[re.Pattern]]:
    out: dict[str, list[re.Pattern]] = {}
    for tag in TAG_DEFINITIONS:
        out[tag["name"]] = [
            re.compile(kw, flags=re.IGNORECASE) for kw in tag["positive_keywords"]
        ]
    return out


KEYWORD_PATTERNS = _compile_keyword_patterns()


def matched_candidate_tags(text: str) -> list[str]:
    """Return tag names whose positive-keyword list matched the text."""
    hits: list[str] = []
    for tag_name, patterns in KEYWORD_PATTERNS.items():
        if any(p.search(text) for p in patterns):
            hits.append(tag_name)
    return hits


# =====================================================================
# Build a flat searchable text blob from a page + parsed aiMetadata
# =====================================================================

def build_text_blob(page: dict, parsed: ParsedAiMetadata | None) -> str:
    """Concatenate the fields useful for tag matching into one searchable string."""
    parts: list[str] = []

    # Root-level page fields (some places store title + description on the doc, not in aiMetadata)
    parts.append(str(page.get("title") or ""))
    parts.append(str(page.get("subtitle") or ""))
    parts.append(str(page.get("excerpt") or ""))

    if parsed and not parsed.parse_error:
        parts.append(parsed.title)
        parts.append(parsed.description)
        parts.extend(parsed.keywords)
        parts.extend(parsed.attractions)
        parts.extend(parsed.activities)
        parts.extend(parsed.historical_significance)
        parts.extend(parsed.ideal_for)
        parts.extend(parsed.local_tips)
        parts.extend(parsed.best_time_to_visit)
        parts.extend(parsed.accessibility_notes)
        parts.extend(parsed.transportation)
        parts.extend(parsed.amenities)
        parts.extend(parsed.water_safety_notes)
        parts.extend(parsed.inline_tags)
        if parsed.track_trail:
            parts.append(parsed.track_trail.description or "")
            parts.append(parsed.track_trail.duration_text or "")
            parts.append(parsed.track_trail.primary_type or "")

    return "\n".join(p for p in parts if p)


# =====================================================================
# Build the Claude prompt for a single article
# =====================================================================

def build_prompt(
    page: dict, parsed: ParsedAiMetadata | None, candidate_tag_names: list[str]
) -> str:
    """Return the user-message text for the Claude classification call."""
    # Pull a clean view of the article
    title = (parsed.title if parsed and parsed.title else page.get("title")) or "(no title)"
    description = (parsed.description if parsed and parsed.description else page.get("excerpt")) or ""

    keywords = parsed.keywords if parsed and not parsed.parse_error else []
    activities = parsed.activities if parsed and not parsed.parse_error else []
    attractions = parsed.attractions if parsed and not parsed.parse_error else []
    historical = parsed.historical_significance if parsed and not parsed.parse_error else []
    ideal_for = parsed.ideal_for if parsed and not parsed.parse_error else []
    local_tips = parsed.local_tips if parsed and not parsed.parse_error else []
    best_time = parsed.best_time_to_visit if parsed and not parsed.parse_error else []
    accessibility = parsed.accessibility_notes if parsed and not parsed.parse_error else []
    transportation = parsed.transportation if parsed and not parsed.parse_error else []
    water_safety = parsed.water_safety_notes if parsed and not parsed.parse_error else []
    track_descr = ""
    if parsed and parsed.track_trail:
        track_descr = parsed.track_trail.description or ""

    primary_loc = parsed.primary_location() if parsed and not parsed.parse_error else None
    location_str = ""
    if primary_loc:
        location_str = ", ".join(
            x for x in (
                primary_loc.suburb_place,
                primary_loc.subregion2,
                primary_loc.subregion,
                primary_loc.region,
            ) if x
        )

    # Build the candidate tag definitions block (only matched candidates)
    candidate_block_lines: list[str] = []
    for name in candidate_tag_names:
        td = next((t for t in TAG_DEFINITIONS if t["name"] == name), None)
        if not td:
            continue
        candidate_block_lines.append(f"  - Name: {td['name']}")
        candidate_block_lines.append(f"    Definition: {td['definition']}")
        if td["negative_signals"]:
            candidate_block_lines.append(
                f"    Do NOT apply when: {'; '.join(td['negative_signals'])}"
            )
    candidate_block = "\n".join(candidate_block_lines)

    def fmt_list(items: list[str], cap: int = 12) -> str:
        return " | ".join(items[:cap]) if items else "(none)"

    prompt = f"""You are reviewing a New Zealand travel article and deciding which (if any) of a small list of candidate tags genuinely apply.

ARTICLE
Title: {title}
Location: {location_str or "(not specified)"}
Description: {description}
Keywords: {fmt_list(keywords)}
Activities: {fmt_list(activities)}
Attractions: {fmt_list(attractions)}
Historical significance: {fmt_list(historical)}
Ideal for: {fmt_list(ideal_for)}
Best time to visit: {fmt_list(best_time)}
Accessibility notes: {fmt_list(accessibility)}
Transportation: {fmt_list(transportation)}
Water safety notes: {fmt_list(water_safety)}
Local tips: {fmt_list(local_tips)}
Track / trail description: {track_descr or "(none)"}

CANDIDATE TAGS (the only options — pre-filter keyword hits)
{candidate_block}

RULES
- Be strict. The tag must MEANINGFULLY feature in the article, not just be mentioned in passing.
- Return at most 2 tags (the strongest fits). Returning 0 is fine and common.
- Use the "Do NOT apply when" guidance above to reject false positives.
- Confidence: "high" = unambiguous, multiple evidence fields; "medium" = clear fit but evidence is thin; "low" = plausible but stretchy.

Return a single JSON object, no prose or backticks:

{{"applicable_tags": [{{"tag_name": "...", "justification": "<one sentence quoting or paraphrasing article evidence>", "confidence": "high|medium|low"}}]}}
"""
    return prompt


# =====================================================================
# Anthropic call
# =====================================================================

# Lazy import so the script can be run for stats without anthropic installed
def _get_anthropic_client():
    import anthropic
    return anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


async def classify_article(
    client: Any,
    page: dict,
    parsed: ParsedAiMetadata | None,
    candidate_tag_names: list[str],
    semaphore: asyncio.Semaphore,
    counter: dict,
) -> dict:
    """Call Claude with retry-on-429. Returns a result dict; on terminal error
    after retries, sets 'error' field."""
    prompt = build_prompt(page, parsed, candidate_tag_names)

    # Retry on 429 (rate limit) with exponential backoff. The Haiku tier is
    # 50 req/min for our org, so even with concurrency=4 we expect occasional
    # bursts that push past the limit.
    import anthropic as _anthropic_mod
    backoffs = [1.5, 4.0, 10.0, 25.0, 60.0]   # seconds

    response = None
    last_error: Exception | None = None
    async with semaphore:
        for attempt, wait_before in enumerate([0.0] + backoffs):
            if wait_before:
                await asyncio.sleep(wait_before)
            try:
                response = await client.messages.create(
                    model=MODEL,
                    max_tokens=600,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                )
                break
            except _anthropic_mod.RateLimitError as e:
                last_error = e
                continue
            except _anthropic_mod.APIStatusError as e:
                # Retry on 5xx; bail on 4xx other than 429
                if 500 <= e.status_code < 600:
                    last_error = e
                    continue
                return {"error": f"{type(e).__name__}: {e}",
                        "prompt_chars": len(prompt)}
            except Exception as e:
                last_error = e
                # Other exceptions (network) — one short retry then bail
                if attempt >= 1:
                    return {"error": f"{type(e).__name__}: {e}",
                            "prompt_chars": len(prompt)}
                continue

    if response is None:
        return {
            "error": f"giveup_after_retries: {type(last_error).__name__}: {last_error}",
            "prompt_chars": len(prompt),
        }

    # Tally tokens
    usage = response.usage
    counter["input_tokens"] += usage.input_tokens
    counter["output_tokens"] += usage.output_tokens

    # Parse JSON response
    text = response.content[0].text if response.content else ""
    parsed_resp = _parse_json_response(text)
    if parsed_resp is None:
        return {
            "error": "json_parse_failed",
            "raw_text": text[:500],
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        }

    # Validate each returned tag is in the candidate list
    applicable = parsed_resp.get("applicable_tags", [])
    validated: list[dict] = []
    for entry in applicable[:2]:
        if not isinstance(entry, dict):
            continue
        name = entry.get("tag_name")
        if name in candidate_tag_names:
            validated.append({
                "tag_name": name,
                "justification": str(entry.get("justification", ""))[:300],
                "confidence": entry.get("confidence", "medium"),
            })

    return {
        "applicable_tags": validated,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
    }


def _parse_json_response(text: str) -> dict | None:
    """Strip optional code fences, then json.loads."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        # try to find the first {...} block
        m = re.search(r"\{.*\}", t, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        return None


# =====================================================================
# Sanity corpus fetch (paginated)
# =====================================================================

def fetch_corpus(client: SanityClient) -> list[dict]:
    """Pull all `page` docs with the fields we need. Paginated to stay safe."""
    print(f"Fetching all `page` docs from Sanity (batch size {PAGE_BATCH})...")
    total = client.query("count(*[_type == 'page'])")
    print(f"  Total page docs: {total}")

    results: list[dict] = []
    start = 0
    while True:
        groq = (
            "*[_type == 'page'] | order(_id asc) "
            f"[{start}...{start + PAGE_BATCH}]"
            "{_id, title, subtitle, excerpt, 'slug': slug.current, "
            "'current_tags': tags[]->{_id, name}, aiMetadata}"
        )
        batch = client.query(groq) or []
        if not batch:
            break
        results.extend(batch)
        print(f"  Fetched {len(results)} / {total}")
        if len(batch) < PAGE_BATCH:
            break
        start += PAGE_BATCH
    return results


# =====================================================================
# Resumability — read existing output files to skip already-processed IDs
# =====================================================================

def already_processed_ids() -> set[str]:
    out: set[str] = set()
    for path in (PROPOSALS_JSONL, SKIPPED_JSONL, ERRORS_JSONL):
        if not path.exists():
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if "_id" in row:
                        out.add(row["_id"])
                except json.JSONDecodeError:
                    continue
    return out


# =====================================================================
# Main pipeline
# =====================================================================

async def run(limit: int | None, concurrency: int) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sanity = SanityClient()
    pages = fetch_corpus(sanity)

    already = already_processed_ids()
    if already:
        print(f"Resuming: skipping {len(already)} already-processed _ids")

    # Filter out resumed + apply --limit
    to_process = [p for p in pages if p["_id"] not in already]
    if limit:
        to_process = to_process[:limit]

    print(f"Will process {len(to_process)} pages")
    if not to_process:
        print("Nothing to do.")
        return

    # Open output files in append mode
    proposals_f = open(PROPOSALS_JSONL, "a", encoding="utf-8")
    skipped_f = open(SKIPPED_JSONL, "a", encoding="utf-8")
    errors_f = open(ERRORS_JSONL, "a", encoding="utf-8")

    anthropic_client = _get_anthropic_client()
    semaphore = asyncio.Semaphore(concurrency)
    counter = {"input_tokens": 0, "output_tokens": 0}

    async def process_one(page: dict) -> None:
        parsed = parse_aimetadata(page.get("aiMetadata") or "")
        blob = build_text_blob(page, parsed)
        candidate_hits = matched_candidate_tags(blob)
        current_tag_names = sorted({t["name"] for t in (page.get("current_tags") or []) if t})

        base_row = {
            "_id": page["_id"],
            "title": page.get("title") or (parsed.title if parsed else ""),
            "slug": page.get("slug"),
            "current_tags": current_tag_names,
            "aimetadata_parse_error": parsed.parse_error if parsed else False,
        }

        if not candidate_hits:
            base_row["reason"] = "no_keyword_match"
            skipped_f.write(json.dumps(base_row, ensure_ascii=False) + "\n")
            skipped_f.flush()
            return

        result = await classify_article(
            anthropic_client, page, parsed, candidate_hits, semaphore, counter
        )

        if "error" in result:
            base_row["candidate_hits"] = candidate_hits
            base_row["error"] = result["error"]
            errors_f.write(json.dumps(base_row, ensure_ascii=False) + "\n")
            errors_f.flush()
            return

        base_row["candidate_hits"] = candidate_hits
        base_row["applicable_tags"] = result["applicable_tags"]
        base_row["input_tokens"] = result.get("input_tokens", 0)
        base_row["output_tokens"] = result.get("output_tokens", 0)
        proposals_f.write(json.dumps(base_row, ensure_ascii=False) + "\n")
        proposals_f.flush()

    # Progress reporter
    completed = 0
    total_to_do = len(to_process)
    start_time = time.time()

    async def report_progress():
        nonlocal completed
        while completed < total_to_do:
            await asyncio.sleep(30)
            elapsed = time.time() - start_time
            rate = completed / elapsed if elapsed > 0 else 0
            cost = (
                counter["input_tokens"] * PRICING["input_per_M"] / 1_000_000
                + counter["output_tokens"] * PRICING["output_per_M"] / 1_000_000
            )
            print(
                f"  Progress: {completed}/{total_to_do} "
                f"({100*completed/total_to_do:.1f}%) "
                f"{rate:.1f}/sec  cost ~${cost:.3f}"
            )

    progress_task = asyncio.create_task(report_progress())

    async def wrapped(page: dict) -> None:
        nonlocal completed
        try:
            await process_one(page)
        finally:
            completed += 1

    try:
        await asyncio.gather(*(wrapped(p) for p in to_process))
    finally:
        progress_task.cancel()
        proposals_f.close()
        skipped_f.close()
        errors_f.close()

    # Final stats
    elapsed = time.time() - start_time
    cost = (
        counter["input_tokens"] * PRICING["input_per_M"] / 1_000_000
        + counter["output_tokens"] * PRICING["output_per_M"] / 1_000_000
    )
    print(f"\nDONE in {elapsed:.1f}s")
    print(f"  Input tokens : {counter['input_tokens']:,}")
    print(f"  Output tokens: {counter['output_tokens']:,}")
    print(f"  Estimated cost: ${cost:.3f}")

    # Rebuild flat CSV from proposals.jsonl
    rebuild_csv()


def rebuild_csv() -> None:
    """Render proposals.jsonl as a flat CSV — one row per (article, proposed tag)."""
    if not PROPOSALS_JSONL.exists():
        print("No proposals.jsonl to flatten")
        return

    rows: list[dict] = []
    with open(PROPOSALS_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            applicable = doc.get("applicable_tags") or []
            if not applicable:
                # Still write a row for "evaluated but no tag suggested"
                rows.append({
                    "_id": doc["_id"],
                    "title": doc.get("title") or "",
                    "slug": doc.get("slug") or "",
                    "current_tag_count": len(doc.get("current_tags", [])),
                    "current_tags": "; ".join(doc.get("current_tags") or []),
                    "candidate_hits": "; ".join(doc.get("candidate_hits") or []),
                    "proposed_tag": "",
                    "justification": "",
                    "confidence": "",
                    "approve": "",
                })
                continue
            for tag in applicable:
                rows.append({
                    "_id": doc["_id"],
                    "title": doc.get("title") or "",
                    "slug": doc.get("slug") or "",
                    "current_tag_count": len(doc.get("current_tags", [])),
                    "current_tags": "; ".join(doc.get("current_tags") or []),
                    "candidate_hits": "; ".join(doc.get("candidate_hits") or []),
                    "proposed_tag": tag.get("tag_name") or "",
                    "justification": tag.get("justification") or "",
                    "confidence": tag.get("confidence") or "",
                    "approve": "",   # human fills in: y / n
                })

    # Write CSV
    with open(PROPOSALS_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "_id", "title", "slug", "current_tag_count", "current_tags",
                "candidate_hits", "proposed_tag", "justification", "confidence",
                "approve",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {PROPOSALS_CSV} ({len(rows)} rows)")

    # Print per-tag counts
    from collections import Counter
    tag_counts = Counter(r["proposed_tag"] for r in rows if r["proposed_tag"])
    print("\nPer-tag proposal counts:")
    for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1]):
        print(f"  {tag:25s} {count}")
    if not tag_counts:
        print("  (no proposals)")


# =====================================================================
# CLI
# =====================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="Process at most N pages (for testing)")
    parser.add_argument("--concurrency", type=int, default=8,
                        help="Max concurrent Anthropic calls (default 8)")
    parser.add_argument("--rebuild-csv", action="store_true",
                        help="Skip processing; just rebuild the CSV from proposals.jsonl")
    args = parser.parse_args()

    if args.rebuild_csv:
        rebuild_csv()
        return

    asyncio.run(run(limit=args.limit, concurrency=args.concurrency))


if __name__ == "__main__":
    main()
