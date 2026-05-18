# `web_search` — tool contract

**Status:** Live as of Sprint 5.1 (2026-05-18). `prompt_version: 0.7.0`+.

---

## What it does

Anthropic's built-in web search — sends a query to Brave-class search, returns ranked snippets + URLs + extracted citation text directly to the model. It's a **server tool**: Anthropic runs it server-side and feeds the result back in the same API call. We don't dispatch it, don't call any external API, and don't manage a search-provider key.

## When to call it

Strictly gated by HARD_RULE #11 (see [`backend/system_prompt.py`](../../backend/system_prompt.py)):

✓ **Call when both are true:**
1. You've already searched Tripideas (`search_places`, `find_place_by_name`, `search_accommodation`) and got zero or insufficient results.
2. The user's question genuinely needs **current information** — opening hours, schedules, prices, weather, road closures, recent news, etc.

❌ **Do NOT call for:**
- General travel descriptions (training-data is fine — surface the operator URL via EXTERNAL_REFERENCES instead)
- Things clearly in Tripideas you forgot to query
- Padding answers ("let me check the web") when conversational is all the user wanted

Examples:
- ✓ *"What time does Te Papa open today?"* — current info, schedule
- ✓ *"Ferry times from Auckland to Waiheke today"* — current info, schedule
- ✓ *"Is the Routeburn Track open right now?"* — current info, conditions
- ❌ *"Tell me about Hobbiton"* — training data covers this; surface hobbitontours.com
- ❌ *"Best restaurants in Wellington"* — Tripideas doesn't index restaurants; suggest Google Maps generically (HARD_RULE #2 says still call Tripideas tools first to confirm zero, but don't web_search for subjective recommendations)

## How it's integrated

| Layer | Where | What |
|---|---|---|
| Tool declaration | [`backend/tool_definitions.py`](../../backend/tool_definitions.py) `WEB_SEARCH_SCHEMA` | `{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}` |
| Orchestrator handling | [`backend/orchestrator.py`](../../backend/orchestrator.py) | Recognises `server_tool_use` and `web_search_tool_result` content blocks, preserves them in `convo`, loops on `pause_turn` stop_reason |
| Prompt gating | [`backend/system_prompt.py`](../../backend/system_prompt.py) HARD_RULE #11 | When to fire / when not to |

**Key difference from custom tools:** the model emits `server_tool_use` (note the prefix on the tool id: `srvtoolu_...` instead of `toolu_...`). The orchestrator never calls `dispatch_tool` for it — it just acknowledges the block and lets Anthropic do the work.

## Cost + quotas

| Field | Value |
|---|---|
| Per-search cost | **$0.01** ($10 per 1,000 searches) |
| Billing | Same Anthropic API key as everything else (no separate billing surface) |
| Max uses per chat turn | **3** (configured in `WEB_SEARCH_SCHEMA`) — capped to keep per-turn cost ≤ $0.03 |
| Citations | Free — `citations[]` arrays don't count toward token usage |
| Latency | ~1–3 seconds added to whichever model turn triggers the search |

## Org-admin requirement

**Web Search must be enabled in the Anthropic Console** under `/settings/privacy` for the API key referenced by `ANTHROPIC_API_KEY`. Currently enabled for the workspace owning the project's API key. If it ever gets disabled, `web_search_tool_result` blocks come back with `error.type` set to one of:
- `too_many_requests` — workspace rate-limited
- `invalid_input` — malformed query
- `max_uses_exceeded` — hit the 3-per-turn cap
- `query_too_long` — query exceeded length limit
- `unavailable` — service down or not enabled

These don't raise Python exceptions — they're content blocks. The model usually handles them gracefully ("I couldn't reach search this time — here's what I know from general info").

## Citation handling

Web search results come back with structured citations:
- `url` — link to source
- `title` — page title
- `cited_text` — up to 150 chars of the actual sentence quoted
- `encrypted_index` — opaque token Anthropic needs to verify the citation in future turns

The orchestrator preserves all citation fields when rebuilding the assistant message (see `text_block["citations"]` in `orchestrator.py`). The model embeds inline citations naturally in its text output — we don't transform them.

## Verified behaviour (2026-05-18)

| Prompt | Expected | Actual |
|---|---|---|
| "Current ferry times from Auckland to Waiheke" | `web_search` fires; cites Fullers360 / Island Direct / Auckland Transport | ✓ |
| "Coastal walks in Northland" | `search_places` only, no web_search | ✓ |
| "Tell me about Wellington Botanic Gardens" | `find_place_by_name` + `get_place_summary` only, no web_search | ✓ (Tripideas content is sufficient) |

## How to verify it's working

Curl the live `/chat` endpoint with a current-info prompt, then look for events in the SSE stream:

```bash
curl -s -N -X POST https://devesesam--tripideas-chat-web.modal.run/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"What time does Te Anau visitor centre open today?"}]}' \
  --max-time 60 | grep -E 'event:|web_search'
```

You should see at least one `event: tool_use` with `name: web_search` and id prefix `srvtoolu_`.

## Future improvements (not blocking)

- **Upgrade to `web_search_20260209`** when the SDK adds typed support — better token efficiency and supports allowed/blocked domains. Currently on `web_search_20250305` because that's what `anthropic` 0.75.0 has typed support for.
- **Domain allow-list** — once we're on the newer tool version, we could restrict searches to a curated set (NZTA, DOC, MetService, operator sites). Trades flexibility for trust.
- **Citation rendering in the frontend** — the chatbot's text already cites inline; we could lift the structured citation list into a separate UI element ("Sources: …") if Douglas wants stronger source visibility.
- **Per-region geo hint** — `user_location` parameter (city/region/country) is supported by the newer tool version; would bias results toward NZ-relevant sources. Worth doing once we upgrade.

## See also

- [`directives/chat_architecture.md`](../chat_architecture.md) — broader chat orchestration including web_search routing
- [`directives/deployment.md`](../deployment.md) — Anthropic Console org-admin setup
- [`directives/issues_and_fixes_log.md`](../issues_and_fixes_log.md) — 2026-05-18 entry for the integration
