# Chat architecture — design rationale

> **What this is:** The "why" behind how the chat orchestrator + tool-routing works. Future agents (and humans) reading the codebase should consult this before proposing changes to the chat flow.
> **Captured:** 2026-04-27 evening, after first user testing of the running stack. **Updated 2026-04-27 (later evening)** for `search_accommodation` (sixth tool).

---

## Top-line

Tool routing **happens inside Anthropic's Sonnet 4.6 model** via the standard Anthropic tool-use loop. There is **no separate router layer** (no Haiku pre-router, no deterministic Python intent classifier, no semantic vector match). The model sees the system prompt's tool-use guidance + the JSON schemas of all **6 tools** + the conversation, and picks (a) whether to call a tool, (b) which one, (c) what arguments to pass.

The 6 tools, by category:

- **Discovery** — `search_places` (sights/walks/activities), `search_accommodation` (lodging), `get_place_summary` (one-doc detail)
- **Composition** — `build_day_itinerary` (single day), `build_trip_itinerary` (chained multi-day)
- **Mutation** — `refine_itinerary` (adjust existing day plan)

This was a deliberate choice. Read on for why.

---

## How a chat turn flows

```
User types message in browser
       ↓ HTTPS POST /chat with {messages: [...]}
Backend receives request                                    [orchestrator.py: chat()]
       ↓ Build conversation in Anthropic format
Anthropic.messages.stream(model=sonnet, tools=[5 schemas], messages=[...])
       ↓
       ├── Model decides: text reply, or tool_use?
       │
       │   Path A — text reply:
       │       ↓ Stream text deltas back as SSE event: text events
       │       ↓ stop_reason="end_turn" → emit usage + done → stop
       │
       │   Path B — tool_use:
       │       ↓ Emit SSE event: tool_use {id, name} when block starts
       │       ↓ Stream completes; we have the resolved tool args
       │       ↓ Emit SSE event: tool_args {id, name, args}        [for richer UI labels]
       │       ↓ dispatch_tool(name, args)                          [tool_definitions.py]
       │       │       ↓ Imports the right Python tool from execution/tools/
       │       │       ↓ Tool runs (GROQ → Sanity → result dict)
       │       ↓ Emit SSE event: tool_result {id, ok, summary, elapsed_ms}
       │       ↓ Append tool_result to conversation
       │       ↓ Loop back to top: call Sonnet again with updated conversation
       │
       └── Repeat until stop_reason != "tool_use" OR MAX_TOOL_LOOPS hit
```

Code paths:
- **Loop driver:** `backend/orchestrator.py` → `run_chat_loop()`
- **Tool schemas + dispatch:** `backend/tool_definitions.py` → `TOOLS`, `dispatch_tool()`
- **System prompt (the "how to think" instructions for the model):** `backend/system_prompt.py`
- **Tools themselves:** `execution/tools/*.py`

---

## Why no pre-router

Three options were considered and rejected:

### Rejected: Haiku 4.5 pre-router

> First call: Haiku decides "tool needed? which one?" → Second call: Sonnet executes with limited or no tools.

- **Cost:** marginal savings (~$0.005/turn on output tokens)
- **Latency:** **doubles** the per-turn round-trip (~200–500 ms × 2 calls)
- **Quality:** worse on ambiguous turns where the model needs full context to decide (*"what about another option?"* → does it mean refine, or new search?)

Net negative for our use case. Latency is already the user's #1 complaint.

### Rejected: Deterministic Python router

> Regex/keyword rules ("3-day" + region → trip; "day around X" → day) dispatch directly to the right tool without an LLM.

- **Cost:** zero LLM cost on routing
- **Latency:** instant (~1 ms)
- **Quality:** **brittle**. Real user messages don't follow templates ("could you sort us out a few things to do round Queenstown for like a long weekend"). Maintaining the rule set becomes a tax.
- Conversational turns (*"thanks"*, *"hmm let me think"*, *"actually scratch that"*) don't fit any rule and get awkwardly dispatched or dropped.

Rejected for v1. Could be a fast-path for high-volume specific patterns later, but unnecessary now.

### Chosen: Sonnet routes itself

> One Sonnet call. Tools registered. Model picks based on system prompt + schemas + conversation.

- **Cost:** ~$0.06 per multi-day trip turn (most of which is the *response composition*, not the routing decision)
- **Latency:** one round-trip per "decision point" in the conversation. The bottleneck is not the routing — it's the tool execution itself (`build_trip_itinerary` takes ~30 s because it queries Sanity 3+ times for a 3-day trip).
- **Quality:** strong on ambiguity, handles "just chatting" turns gracefully (no tool fires), gracefully handles refinement vs new search distinction.

This stays unless real-usage data shows otherwise.

---

## Latency sources (where the time actually goes)

For a multi-day trip request like *"3-day coastal Northland trip"* (~30 s end-to-end):

| Phase | Time | Notes |
|---|---|---|
| Anthropic `messages.stream` 1st call (decide tool) | ~2-3 s | Sonnet first-token latency + decision streaming |
| `build_trip_itinerary` dispatch | ~25-28 s | **Bottleneck.** Internally loops `build_day_itinerary` per day; each day calls `search_places` against Sanity (~2 s) + Python parse + greedy fill (~500 ms). Sequential. |
| Anthropic `messages.stream` 2nd call (compose response) | ~3-5 s | Streams the formatted itinerary text |
| **Total** | **~30 s** | |

For a simple turn like *"easy walks near Wellington"* (~5 s end-to-end):

| Phase | Time | Notes |
|---|---|---|
| Anthropic 1st call | ~2 s | |
| `search_places` dispatch | ~2 s | Single Sanity round-trip |
| Anthropic 2nd call | ~1-2 s | Short response |

### Where we'd optimize first

1. **Parallelize `build_trip_itinerary`'s per-day searches** — currently sequential, could run all `build_day_itinerary` calls concurrently with `asyncio.gather`. Cuts ~30 s → ~10-12 s on 3-day trips. Stretch goal in Sprint 4.5.
2. **Session-level Sanity cache** — most multi-turn chats stay in one region. Cache `aiMetadata` for that region's pages between turns (5-min TTL). Cuts repeated queries to near-zero.
3. **Stream tool result summaries earlier** — currently the tool runs to completion then we emit `tool_result`. Could emit per-day progress events as `build_trip_itinerary` finishes each day. Doesn't reduce total time but improves perceived progress.

None of these touch tool routing.

---

## What the system prompt does

`backend/system_prompt.py` (`SYSTEM_PROMPT_VERSION` = `0.2.0` as of 2026-04-27) carries:

1. **NZ regions cheat-sheet** — model resolves user aliases ("BoP", "Bay of Islands", "Hawke's Bay") to the canonical Sanity region names before calling tools.
2. **Tool-use patterns** — guidance on which tool to pick for which intent shape (search vs single day vs trip vs refine vs detail).
3. **Conversational style** — be concise, use match_reasons verbatim, don't invent missing data, offer one next step.
4. **Pre-tool acknowledgement (added v0.2.0)** — for slow tools (`build_trip_itinerary`, `build_day_itinerary`, `refine_itinerary`), emit a 1-sentence "give me a moment" text BEFORE the tool_use block, so the user sees streaming text within ~1-2 s instead of staring at a spinner for 30 s. The model usually follows this reliably.

If you change the system prompt, bump `SYSTEM_PROMPT_VERSION` (semver) so future debugging can correlate.

---

## SSE event protocol (backend → frontend)

Custom format, defined in `backend/orchestrator.py`. The frontend's custom `useChat` hook (`frontend/src/useChat.ts`) consumes it. We don't use Vercel AI SDK's data-stream protocol because:
- Their format is opinionated (and changes between versions)
- Our needs are simple — text deltas + tool lifecycle + usage
- Owning both ends of a custom SSE format is ~100 lines and trivial to evolve

| event | data | when |
|---|---|---|
| `text` | `{delta: str}` | Each text token from the model |
| `tool_use` | `{id, name}` | Model emits a tool_use block (args still streaming) |
| `tool_args` | `{id, name, args}` | Args resolved, just before dispatch |
| `tool_result` | `{id, name, ok, summary, elapsed_ms}` | After dispatch returns |
| `usage` | `{input_tokens, output_tokens, cost_usd, loops, elapsed_ms}` | Final per-request totals |
| `error` | `{message}` | Anything that shouldn't happen |
| `done` | `{finish_reason}` | Stream complete |

---

## When to revisit this design

Trigger to add a router or change the architecture:
- **Cost per session > $0.50 sustained** at low traffic — output tokens dominate; consider Haiku for response composition while keeping Sonnet for tool routing
- **First-token latency > 3 s consistently** — switch model or add a smaller "ack" call
- **Tool selection accuracy < 90%** observed across user conversations — add a deterministic fast-path for the common patterns

None of these are met today. Status quo wins.

---

## Per-tool reference

Each tool has its own contract doc under `directives/tool_contracts/`. As of 2026-04-27 only `search_accommodation.md` is fully written; the other five tools are documented inline in their `__main__` smoke tests + the build plan + this file. As tools evolve or get extended, write a tool-contract doc per the `search_accommodation.md` template:

- What it does + when to call it (vs alternatives)
- Input schema + output shape
- Data caveats / quirks
- Sample tool calls with verified results
- How to extend (adding filters, scoring rules)
- Future improvements

| Tool | Contract doc | Status |
|---|---|---|
| `search_places` | (inline in tool file) | Verified working — tag-intersection bug fixed Sprint 4.9 |
| `get_place_summary` | (inline in tool file) | Verified working |
| `build_day_itinerary` | (inline in tool file) | Verified working — first-pick proximity bias + densest-cluster base Sprint 5.0 |
| `build_trip_itinerary` | (inline in tool file) | Verified working |
| `refine_itinerary` | (inline in tool file) | Verified working |
| `search_accommodation` | [`tool_contracts/search_accommodation.md`](tool_contracts/search_accommodation.md) | Verified working — `book_link` is null until accommodation pages are published (see contract) |
| `find_place_by_name` | (inline in tool file) | Sprint 4.9 — locate page by title/slug with `has_aimetadata` flag |
| `list_subregions` | (inline in tool file) | Sprint 4.9 — live sub-region taxonomy; also injected into the system prompt at startup |
| `web_search` | [`tool_contracts/web_search.md`](tool_contracts/web_search.md) | Sprint 5.1 — Anthropic server tool, gated by HARD_RULE #11 |

---

## Google Maps integration (Sprint 4.7, 2026-05-05)

**Why:** Two needs the haversine fudge couldn't satisfy:
1. Honest drive estimates surfaced to the user (`135 km, ~2h 5m` matters when planning tight days).
2. A road-following polyline so the frontend can render the day's actual route, not a straight line through the bush.

**Wrapper:** [`execution/services/google_maps.py`](../execution/services/google_maps.py) — `is_configured()`, `geocode()` (LRU-cached), `directions()`, `decode_polyline()`. Defensive: every function returns `None` on missing key / API error / non-OK status. Caller falls back to haversine; nothing crashes.

**Where it's called (cost-controlled):**

| Location | Calls per invocation | Why limited |
|---|---|---|
| `build_day_itinerary` `_build_route_geojson` | **1** per day plan | Origin/destination = base, all places as waypoints — one call returns the whole day's polyline + accurate total drive time |
| `build_trip_itinerary` `_compute_transition` | **1** per inter-day transition | N-1 calls for an N-day trip |
| `build_day_itinerary` `_drive_minutes` | **0** | Reverted to haversine. Greedy fill scores ~150 candidate-vs-stop pairs per day; Google calls there would cost ~$0.75/day with no quality win for a relative ranking signal |

Cost model: 4-day trip = 4 day-routes + 3 transitions = ~7 Google calls = ~$0.035. Acceptable.

**GeoJSON contract:** Both itinerary tools now return a `route_geojson` field — a [GeoJSON FeatureCollection](https://datatracker.ietf.org/doc/html/rfc7946) with [lng, lat] coordinate order throughout. Features:

| `properties.role` | Geometry | Source |
|---|---|---|
| `base` | Point | Day's base coordinates |
| `place` | Point | Each chosen place's coords; properties carry title, themes, settlement, start/end times |
| `drive_route` | LineString | Per-day road polyline; `properties.polyline_source` is `google_directions` or `straight_line` (fallback) |
| `inter_day_drive` | LineString | Inter-day road polyline (trip tool only); `properties.polyline_source` and the from/to day_index + settlements |

The trip-level `route_geojson` is the union of every day's per-day features (each tagged with `day_index`) plus the inter-day `LineString`s. Frontend can render this as one map.

**Health diagnostic:** `GET /` on the deployed orchestrator now reports `google_maps_configured: true|false` so a fresh `curl` confirms the key is plumbed through the secret, no chat call needed.

**Secrets:** `google-maps-secret` in the `devesesam` Modal workspace (one key: `GOOGLE_MAPS_API_KEY`). See [`directives/deployment.md`](deployment.md).

---

## URL conventions on tripideas.nz (Sprint 5.1, 2026-05-18)

Probed against the live sitemap + HEAD requests:

| Content type | Canonical URL | Notes |
|---|---|---|
| Place page | `https://www.tripideas.nz/place/<slug>` | The bare `tripideas.nz/<slug>` works via legacy redirect but isn't canonical |
| Post (blog) | `https://www.tripideas.nz/post/<slug>` | Sitemap-confirmed; not currently surfaced by our tools |
| Region overview | `https://www.tripideas.nz/region/<slug>` | Sitemap-confirmed |
| Tag overview | `https://www.tripideas.nz/tag/<slug>` | Sitemap-confirmed |
| **Accommodation** | **No public URL.** Every variant 404s. | Sanity has the data; frontend doesn't publish individual accommodation pages |

**Implications for the chat:**
- Place links must use the `/place/` prefix (HARD_RULE #1).
- Accommodation `book_link` is hardcoded to `None` in [`search_accommodation.py`](../execution/tools/search_accommodation.py). The chat surfaces `contact.website` (operator's own site) as the actionable link instead.
- If Douglas later publishes accommodation pages, the single fix is to set `book_link=f"https://www.tripideas.nz/<correct-prefix>/{slug}"` in [`search_accommodation.py:305`](../execution/tools/search_accommodation.py) — no system prompt change needed because the chat already routes lodging questions through `search_accommodation`.

To re-probe if the routing changes: fetch any accommodation slug from Sanity, HEAD-request a few candidate prefixes, see which returns 200. The Sprint 5.1 issue log has the script.

---

## Web search integration (Sprint 5.1, 2026-05-18)

**Why:** The chatbot was citing external URLs (`hobbitontours.com`, etc.) from training data — looked like web search but wasn't. Added Anthropic's built-in `web_search_20250305` server tool as a gated fallback for genuinely-current information.

**How it's different from our other tools:** It's a **server tool** — Anthropic runs the search; we don't dispatch. The orchestrator handles two new content-block types when rebuilding the assistant message for conversation continuity:
- `server_tool_use` — model decided to search (emit `tool_use` SSE event for UI indicator)
- `web_search_tool_result` — search results returned inline (preserve verbatim in `convo`)

The orchestrator also handles `pause_turn` stop_reason — when a server tool ran but the model has more to say, loop again without dispatching.

**Cost + quotas:**
- $10 per 1,000 searches ($0.01 each), billed via the same Anthropic API key
- `max_uses=3` per chat turn caps per-turn cost at $0.03
- Citations don't count toward token usage

**Gating** (HARD_RULE #11 in [`backend/system_prompt.py`](../backend/system_prompt.py)):
- ONLY fire when Tripideas tools already returned zero AND the user needs current info (opening hours, schedules, prices, news)
- Don't use for general descriptions or padding
- Always cite the URLs Anthropic returns

**Verified smoke results (2026-05-18):**
- *"Current ferry times to Waiheke"* → fires web_search, cites Fullers360 + Island Direct + Auckland Transport ✓
- *"Coastal walks in Northland"* → fires `search_places` only, no `web_search` ✓

**Org-admin requirement:** Web Search must be enabled in the Anthropic Console under `/settings/privacy` for the workspace's API key. Currently enabled for `devesesam`. If web_search ever stops working, check this first — failures come back as `web_search_tool_result` blocks with error codes (`too_many_requests`, `invalid_input`, `max_uses_exceeded`, `query_too_long`, `unavailable`), not as exceptions.

---

## System prompt structure (HARD_RULES at 11 rules, Sprint 5.1)

The system prompt has grown to ~18 KB after the live taxonomy snapshot is injected. Structure:

1. Tool list (9 tools)
2. **HARD_RULES** (11 numbered, do-not-violate rules) — see below
3. NZ regions reference (cheat sheet)
4. Live sub-region taxonomy (injected from Sanity at startup)
5. Tool-use guidance (when to call which tool)
6. **ITINERARY_FORMAT** (canonical 4-column table)
7. **EXTERNAL_REFERENCES** (Douglas's curated default-resource list)
8. Conversational style
9. Pre-tool acknowledgement (latency UX)
10. Prompt version stamp

The 11 HARD_RULES (one-line summaries):

| # | Rule | Sprint added |
|---|---|---|
| 1 | Never emit a tripideas.nz URL unless the slug came from a tool result; places use `/place/<slug>`, accommodation has no public URL | 4.9 (extended 5.1) |
| 2 | Always search before composing — including for queries you think tools won't cover | 4.9 (tightened 5.0+5.3) |
| 3 | Use the right filter lever — `themes` / `place_subtypes` / `tags` are distinct | 4.9 |
| 4 | Multi-zone requests use `subRegions=[...]` in one call, not fan-out | 4.9 |
| 5 | Find-by-name → look up the ID → then summarise (use `find_place_by_name` first) | 4.9 |
| 6 | Use `list_subregions(region)` when unsure of the live taxonomy | 4.9 |
| 7 | Quote place titles verbatim — macrons, apostrophes, capitalisation preserved | 5.0 |
| 8 | Verify named places via `find_place_by_name` before mentioning them | 5.0 (tightened 5.2) |
| 9 | Pick `candidate_radius_km` from the user's stated scope (15 km walkable → 80+ road trip) | 5.0 |
| 10 | Translate colloquial location names ("Wellington CBD") to canonical sub-region tags | 5.2 |
| 11 | `web_search` is the LAST-resort fallback — gated to "Tripideas tools returned zero AND needs live info" | 5.1 |

Each rule lives in [`backend/system_prompt.py`](../backend/system_prompt.py) `HARD_RULES`. When adding rules: keep the format consistent (numbered, ❌/✓ examples where the rule is ambiguous), and bump `SYSTEM_PROMPT_VERSION`.
