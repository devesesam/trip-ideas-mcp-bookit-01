# Directive: Tag Addition Pass (Underused Tags → Place Pages)

> **Originating request (2026-05-11):** Douglas reviewed the tag taxonomy and found 15 tags with zero Place Pages associated. Asked us to AI-search relevant articles and add the tags. SOP below covers this pass and any similar future pass where a small set of underused tags needs application across the corpus.

## Goal

Apply 0, 1, or 2 of a target tag set to every Place Page in Sanity, where each tag genuinely features in the article. Update both writes:
1. Root-level `tags[]` array of references to `tag` documents
2. `aiMetadata.tags` JSON-encoded string field (keeps the two in sync for the chat tool's query path)

Ignore prior per-article tag caps — if a tag fits, add it.

## Inputs

- **Target tag list** — names provided by Douglas (e.g., the 15 from 2026-05-11)
- **Sanity corpus** — `*[_type == 'page']` (~1,500 docs)
- **Tag definitions + keyword stems** — in `execution/tags/tag_definitions.py`

## Pipeline

### 1. Resolve target tag IDs

```bash
python execution/tags/resolve_tag_ids.py
```

Reads `REQUESTED_TAGS` from the script. Confirms each tag exists in Sanity, surfaces near-spelling-matches (`Māori History` vs `Maori History`), and writes resolved IDs + place counts to `.tmp/tag_addition_pass/resolved_tag_ids.json`.

**Gate:** if any tags are missing, ambiguous, or have suspicious near-duplicates competing for the same concept (e.g., `Historical Trails` vs `Heritage Trails` 167 pages), confirm with the user before proceeding.

### 2. Draft per-tag definitions + keyword stems

Edit `execution/tags/tag_definitions.py`. Each tag needs:
- `name` — exact Sanity tag name
- `definition` — one-line working definition the LLM follows (calibrated to NZ-travel corpus)
- `positive_keywords` — broad regex stems; pre-filter passes if any match. Cast wide here — Claude does the final judgment.
- `negative_signals` — phrases that should make Claude reject (e.g., `Boat Access` should not apply for "boat ramp" alone)

### 3. Run the candidate finder (resumable, async)

```bash
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python execution/tags/find_underused_tag_candidates.py [--limit N] [--concurrency 2]
```

Behavior:
- Paginated Sanity fetch of all `page` docs (~1,500 in ~10s)
- Per-article regex pre-filter to identify candidate tags (cheap; skips ~50–60% of corpus)
- For surviving articles, one Claude Haiku 4.5 call per article evaluating only the candidate tags
- Resumable: skips _ids already in `proposals.jsonl`, `skipped.jsonl`, or `errors.jsonl`

**Rate-limit note (learned 2026-05-11):** Haiku 4.5 tier 1 is **50 req/min per org**. Concurrency=8 blasts past this; concurrency=2 stays under. Script has retry-on-429 with exponential backoff (1.5s → 4s → 10s → 25s → 60s) so transient hits recover. If errors persist, clear `errors.jsonl` and re-run to re-attempt.

Output files (in `.tmp/tag_addition_pass/`):
- `proposals.jsonl` — one line per article that got Claude judgment
- `proposals.csv` — flat view, one row per (article, proposed tag) with `approve` column for human review
- `skipped.jsonl` — articles with no keyword hits (pre-filter rejected)
- `errors.jsonl` — articles where Claude call failed terminally

Run cost estimate: ~$0.001 per article = ~$1.50 for the full corpus. Runtime at concurrency=2: ~20 min.

### 4. Spot-check + human review

Spot-check 20 random rows from `proposals.csv` against the actual articles. Confirm Claude's justifications hold up. Check per-tag counts (printed at end of run) for sanity (e.g., Glaciers should be ~10–15, not 200).

Then:
- Hand `proposals.csv` to user (or Douglas)
- They mark `approve=y` on rows they accept (anything else = reject)
- Save the edited file back at the same path

### 5. Apply approved proposals to Sanity

**Pre-check:** Sanity token must have Editor (write) scope. Test with a no-op dry run first:

```bash
python execution/tags/apply_tag_additions.py --dry-run --limit 5
```

This prints sample patch payloads for eyeball check. No writes.

Then live apply:

```bash
python execution/tags/apply_tag_additions.py
```

Each affected article gets one atomic Sanity patch that:
- `set`s the full new `tags[]` array (existing refs + new refs, deduped by `_ref`). Each item has a generated `_key`. We use full `set` rather than `insert` because it's bulletproof for both empty and non-empty starting arrays.
- `set`s `aiMetadata` to the re-encoded JSON string with new tag names appended to `aiMetadata.tags` (deduped). Skipped per-doc if `aiMetadata` is missing or unparseable (truncated docs — ~14% of corpus per the 2026-04-27 audit).

Outputs:
- `applied.jsonl` — one line per successfully-mutated doc
- `apply_errors.jsonl` — per-doc failures (e.g., transient 5xx)

Chunk size: 25 mutations per Sanity API call.

### 6. Verify

Re-fetch ~10 random mutated docs and confirm:
- `tags[]` contains the new reference (`_ref` to correct tag doc)
- `aiMetadata` still parses as JSON
- `aiMetadata.tags` includes the new tag names
- No other fields changed

Run `python execution/tags/resolve_tag_ids.py` again to confirm the previously-zero tags now show non-zero `places_count`.

## Critical files

- `execution/tags/tag_definitions.py` — tag definitions + keyword stems
- `execution/tags/resolve_tag_ids.py` — confirms tags exist in Sanity
- `execution/tags/find_underused_tag_candidates.py` — corpus pull + classification
- `execution/tags/apply_tag_additions.py` — bulk Sanity patcher
- `execution/sanity_client.py` — `SanityClient.mutate()` POSTs to `/data/mutate/{dataset}`
- `execution/aimetadata/parser.py` — used to extract clean fields for the LLM prompt

## Notes for future passes

- If the next tag set is larger (e.g., 30+ tags), consider splitting into themed batches so the LLM prompt stays focused. The current per-article prompt sends only pre-filter-matched candidates, so 30+ candidates per article would dilute attention.
- If a tag is genuinely ambiguous (e.g., `Town Parks` vs `City Parks` depends on settlement size), bake that distinction into the per-tag `definition` rather than expecting Claude to guess. The 2026-05-11 pass used "Town: pop <50k, City: pop ≥50k" with named exemplar cities.
- If running on a project with a higher Anthropic rate-limit tier, raise `--concurrency` accordingly. The retry-with-backoff logic gates aggression automatically; no need to micro-tune.
