# Issues and fixes — running log

> **What this is:** Chronological log of issues encountered, the fix or workaround applied, and any caveats future agents should know about. Append-only — do not delete entries when issues are resolved; mark them resolved in place. The point is to keep a paper trail so future sessions don't re-discover the same surprises.

---

## 2026-04-27 — Initial build

### Sanity GROQ: `defined(aiMetadata)` returns false for populated string fields

**Symptom:** Counting populated docs returned 3 instead of the actual ~1300.
**Cause:** Unknown Sanity quirk. Reproducible across all `perspective` values (`raw`, `published`, `drafts`).
**Fix:** Use `length(aiMetadata) > 0` instead of `defined(aiMetadata)` whenever filtering for populated string-encoded fields.
**Status:** Worked around. Captured in [`corpus_audit_2026-04-27.md`](corpus_audit_2026-04-27.md) under "GROQ gotchas".

---

### `aiMetadata` JSON truncation — 206/1315 docs unparseable

**Symptom:** Roughly 16% of pages with populated `aiMetadata` fail `json.loads()`. All failures cluster in the 3500–4499 char range.
**Cause:** Upstream metadata-generator pipeline likely had a `max_tokens` cap around 1000 tokens (~4000 chars JSON), causing mid-string truncation.
**Fix (parser-level):** [`execution/aimetadata/parser.py`](../execution/aimetadata/parser.py) catches `JSONDecodeError` and returns `parse_error=True` so callers can surface "thin data" or skip gracefully.
**Pending:** User (Douglas) is investigating. The list of 206 broken doc IDs is in [`.tmp/truncated_aimetadata_docs.csv`](../.tmp/truncated_aimetadata_docs.csv).
**Status:** Worked around. v1 ships against the 1110 clean docs.

---

### `aiMetadata` value-type chaos within stable keys

**Symptom:** Same field key like `amenities` is `string` in one doc, `list[str]` in another, `null` in a third. Same for 11 of the 19 fields.
**Cause:** Upstream LLM non-determinism. The keys are stable but the model freely chose value types.
**Fix:** [`execution/aimetadata/parser.py`](../execution/aimetadata/parser.py) provides robust accessors (`as_list`, `as_str`, `as_dict`) that normalize whatever shape arrives. Tools downstream see consistent types.
**Status:** Resolved.

---

### Tag taxonomy duplicates and prompt-vs-live drift

**Symptom:** Some tags exist in both forms across the live taxonomy: `Historic Sites` AND `Historical Sites`, `Heritage Trails` AND `Historical Trails`, `Scenic Drive` AND `Scenic Drives`, `Te Araroa` AND `Te Araroa Trail`. Plus the Sanity tag list has tags not in either prompt (`Glaciers`, `Surfing`, `Waterfalls`, `Parks`, `City Walks`, `Top 5`).
**Cause:** Editorial drift. The two automation prompts (primary + secondary) were starting points; the Sanity tag collection is what's actually been used.
**Fix:** [`execution/normalize/tag_mapping.py`](../execution/normalize/tag_mapping.py) treats the obvious dup pairs as synonyms (both map to the same theme/subtype). Includes all 102 live tags.
**Pending:** Confirm with Douglas whether the dups are intentional or should be merged in Sanity.
**Status:** Worked around at the mapping layer.

---

### Geographic hallucinations in aiMetadata

**Symptom:** Te Hakapureirei Beach (North Otago) has `dog_friendly: "No dogs allowed at all times on Matapōuri Reserve including Te Hakapureirei Beach area"` — but Matapōuri Reserve is in Northland, ~500km away.
**Cause:** Upstream LLM conflated two unrelated NZ places named with similar Māori words.
**Fix:** Documented as a known data-quality issue. A `hallucination_check.py` audit was deferred to Sprint 1+ but not yet built.
**Pending:** Run a corpus-wide geographic-consistency check (cross-reference place names mentioned in `dog_friendly`/`historical_significance`/`nearby_places` against the doc's `coordinates` to flag mismatches > 200km).
**Status:** Open. Doesn't block v1.

---

### Modal token format gotcha

**Symptom:** User shared just the token ID (`ak-...`) — Modal CLI requires the full pair (ID + secret).
**Cause:** Modal token API design — IDs and secrets are paired credentials.
**Fix:** Use `modal token new` (browser OAuth flow) which writes both to `~/.modal.toml` cleanly. Never share secrets via chat.
**Status:** Resolved. Captured in memory for future sessions.

---

### Modal CLI on Windows — charmap encoding crash

**Symptom:** First `modal deploy` attempt failed with `'charmap' codec can't encode characters in position 3-42`. Modal's progress-bar Unicode characters can't be printed in cp1252.
**Cause:** Default Windows console encoding is cp1252; Modal's CLI prints Unicode (✓, →, etc).
**Fix:** Prefix Modal commands with `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`:
```bash
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 modal deploy backend/modal_app.py
```
**Status:** Resolved. Add to README + memory for future sessions.

---

### MessageBubble bug — empty pre-stream rendering

**Symptom:** User typed in chat, hit send, then saw nothing for 5–7 seconds before the response appeared all at once.
**Cause:** Empty assistant `MessageBubble` was added immediately so SSE events have a target. But `messages[last].role !== "user"` so the parent-level `ThinkingIndicator` never fired. And the empty bubble had no visible content (no text, no tool calls yet).
**Fix:** Added `isAwaitingFirstEvent` check inside `MessageBubble`: when assistant is streaming + no content + no tool calls, render `PulsingDots` inline. Removed the parent-level `ThinkingIndicator`.
**Files:** [`frontend/src/ChatPanel.tsx`](../frontend/src/ChatPanel.tsx)
**Status:** Resolved 2026-04-27 evening.

---

### Netlify config — wrong `publish` path

**Symptom:** N/A — caught before deploy.
**Cause:** `netlify.toml` had `base = "frontend/"` AND `publish = "frontend/dist/"`. With `base` set, paths resolve relative to it — so the original `publish` would have looked for `frontend/frontend/dist/`.
**Fix:** Changed `publish` to `"dist/"` (relative to `base = "frontend/"`).
**Files:** [`../netlify.toml`](../netlify.toml)
**Status:** Resolved.

---

### Accommodation: no numeric pricing in Sanity

**Symptom:** Tried to filter by `max_price_per_night` against `bestPriceAvailable` — got 0 results everywhere.
**Cause:** `bestPriceAvailable` is a `bool` flag, not a price number. Probably "show the 'best price available' badge?". All 10 sampled docs had `False`.
**Fix:** Dropped `max_price_per_night` from `search_accommodation`'s input schema. Surface `book_link` to `tripideas.nz/<slug>` instead so users see live pricing on Tripideas's existing flow. Real pricing requires Bookit API (Sprint 5).
**Files:** [`execution/tools/search_accommodation.py`](../execution/tools/search_accommodation.py)
**Status:** Documented in [`tool_contracts/search_accommodation.md`](tool_contracts/search_accommodation.md) and [`accommodation_audit_2026-04-27.md`](accommodation_audit_2026-04-27.md).

---

### Accommodation: no region/subRegion taxonomy

**Symptom:** No way to do `subRegion->region->name == "Otago"`-style filter on accommodation (works for pages).
**Cause:** Accommodation docs only have `town` (string, 195/220 populated) and `coordinates` (219/220). They don't reference our region/subRegion graph.
**Fix:** Added `REGION_CENTROIDS` to [`execution/registry/regions.py`](../execution/registry/regions.py) (hardcoded coords for each NZ region, picked at the most touristically-central point). `search_accommodation` resolves a `region` argument to a centroid and applies an 80km radius filter.
**Status:** Resolved. Approximate but works for v1.

---

### Accommodation pool is heavily caravan-park-skewed

**Symptom:** "Find me a Lodge in Otago" → 0 results. "Find me a Motel in Picton" → 0 results.
**Cause:** Real data — 207 of 220 accommodation docs (94%) are `accommodationType1 == "Caravan Parks & Camping"`. Only 1 Lodge in NZ (Tuatapere, Southland), 3 Motels, 6 Backpackers.
**Fix:** Updated `backend/system_prompt.py` (v0.3.0) to instruct the chat: *"if a specific type filter returns 0 results, consider re-running without the type filter and surfacing what's actually there with a brief honest note."* Verified in live testing — the chat acknowledged "the Tripideas-listed properties in the Queenstown area are currently holiday parks" rather than just saying "no results found".
**Status:** Worked around at the prompt level. Long-term fix is for Douglas to onboard more property types to Bookit.

---

## 2026-05-05 — Sprint 4.7: Google Maps integration

### Greedy day-fill scoring shouldn't call Google Maps

**Symptom (caught in design before shipping):** First draft put `google_maps.directions()` inside `_drive_minutes` — the function the greedy day-fill calls when scoring every candidate against every chosen stop. For a balanced day with ~5 picks against a candidate pool of 30, that's ~150 Google calls per day plan. At ~$0.005/call that's ~$0.75 per day plan, ~$3 per 4-day trip — chat cost dwarfed by routing.
**Cause:** Confusing two needs: a "close enough" relative ranking signal (cheap, deterministic, never user-visible) vs an accurate user-facing drive estimate + visual polyline.
**Fix:** Reverted `_drive_minutes` to haversine × 1.4 / 60 km/h. Google Maps is invoked exactly **once per day** in `_build_route_geojson` (origin/destination = base, all places as waypoints) for the visual + accurate total. Same model in `build_trip_itinerary`: once per inter-day transition. So a 4-day trip = 4 day-Google-calls + 3 inter-day calls = 7 total, ~$0.035.
**Files:** [`execution/tools/build_day_itinerary.py`](../execution/tools/build_day_itinerary.py) (`_drive_minutes`, `_build_route_geojson`), [`execution/tools/build_trip_itinerary.py`](../execution/tools/build_trip_itinerary.py) (`_compute_transition`, `_build_trip_geojson`), [`execution/services/google_maps.py`](../execution/services/google_maps.py).
**Status:** Resolved before deploy. Cost model documented inline near `_drive_minutes`.

---

### `google-maps-secret` was never actually created in Modal

**Symptom:** First `modal deploy` after Sprint 4.7 wiring failed with `Secret 'google-maps-secret' not found in environment 'main'`. A previous session's summary claimed the secret existed — `modal secret list` showed otherwise.
**Cause:** Trust drift. Conversation summaries are not source of truth; only `modal secret list` is.
**Fix:** Created the secret via `modal secret create google-maps-secret GOOGLE_MAPS_API_KEY=…` from the value already in `.env`.
**Lesson encoded into:** [`directives/deployment.md`](deployment.md) — explicit secrets table + "always verify with `modal secret list`" guidance.
**Status:** Resolved.

---

### Modal warm container served stale code after redeploy

**Symptom:** Pushed a code change (bumped `SYSTEM_PROMPT_VERSION` from 0.3.0 to 0.4.0, added `google_maps_configured` to the health response). `modal deploy` succeeded multiple times. The live `/` endpoint kept returning the old `prompt_version` and missing the new field. Repeated deploys (3.2s, "Created mounts") didn't fix it. Cleared `__pycache__` — no change.
**Cause:** With `min_containers=0` and a warm container still alive, `modal deploy` doesn't always force-evict it; new requests get routed to the old container which has the old code in memory. (Modal usually does evict, but this time it didn't — possibly because containers fall under a "warm pool" briefly post-deploy.)
**Fix:** `modal app stop <app_id>` (find via `modal app list`), then `modal deploy`. The next request cold-starts a fresh container with the new code. Confirmed: `prompt_version` flipped to 0.4.0 immediately after the stop+redeploy.
**Lesson encoded into:** [`directives/deployment.md`](deployment.md) — under "Common gotchas", with the diagnostic recipe.
**Status:** Resolved. Going forward: bump `SYSTEM_PROMPT_VERSION` (or some visible field) on every meaningful change so `curl /` immediately tells you whether the redeploy took effect.

---

### Modal workspace ambiguity (`devesesam` vs `rvnu`)

**Symptom:** `modal deploy` from a fresh shell hit `Secret 'tripideas-secrets' not found in environment 'main'`. Cause: `modal profile current` was set to `rvnu`, a different workspace on the same machine. The secrets live in `devesesam`.
**Fix:** `modal profile activate devesesam` before any `modal` command for this project.
**Lesson encoded into:** [`directives/deployment.md`](deployment.md) (workspace = `devesesam`, deploy command listed verbatim) plus a memory entry so this doesn't get re-discovered every session.
**Status:** Resolved. Always run `modal profile current` before deploying — must read `devesesam`.

---

## How to use this log

When you encounter a new issue:
1. Append a new dated section at the end of this file
2. Write the symptom, cause, fix, files touched, and current status
3. If the issue is resolved later, update the Status line in place — don't delete the entry
4. If the issue resurfaces or partially regresses, add a follow-up note below

When you start a session and see something weird:
1. Search this file (Ctrl+F) for the symptom you're seeing
2. If it's documented, follow the fix
3. If not, debug from scratch — and add a new entry once you've worked it out
