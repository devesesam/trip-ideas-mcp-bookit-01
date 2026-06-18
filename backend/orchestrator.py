"""FastAPI orchestrator for the Tripideas chat.

`POST /chat`
  Body: {"messages": [{role, content}], "session_id"?}
  Streams Server-Sent Events:
    event: text         data: {"delta": "..."}    — assistant text chunks
    event: tool_use     data: {"name": "...", "id": "..."}
    event: tool_result  data: {"id": "...", "ok": true|false, "summary": "..."}
    event: usage        data: {"input_tokens": N, "output_tokens": N, "cost_usd": ...}
    event: done         data: {"finish_reason": "..."}

The frontend (using @ai-sdk/react useChat) consumes these events to render
streaming text + tool indicators. Server is stateless — full message history
is sent on each request.

Local dev:
    cd backend && uvicorn orchestrator:create_app --factory --reload --port 8000
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

# Ensure execution/ is on path for tool_definitions imports
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "execution") not in sys.path:
    sys.path.insert(0, str(_ROOT / "execution"))

# Load .env in local-dev mode (Modal injects via secrets)
try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
except ImportError:
    pass

import anthropic  # noqa: E402

from backend.system_prompt import SYSTEM_PROMPT_VERSION, compose_system_prompt  # noqa: E402
from backend.tool_definitions import TOOLS, dispatch_tool  # noqa: E402


# Compose the system prompt ONCE at process start with the live Sanity
# region/sub-region taxonomy injected. This means redeploying picks up new
# sub-regions Douglas adds — no code change required. If Sanity is
# unreachable at startup, fall back to the no-taxonomy prompt so the chat
# still works (the model can call list_subregions on demand).
def _load_system_prompt() -> str:
    try:
        from tools.list_subregions import build_taxonomy_snapshot
        snapshot = build_taxonomy_snapshot()
    except Exception:
        snapshot = ""
    return compose_system_prompt(snapshot)


SYSTEM_PROMPT = _load_system_prompt()


# Pricing (Sonnet 4.6 as of writing) for the cost telemetry.
# Update when switching models.
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
MODEL_PRICING = {
    "claude-sonnet-4-6":   {"input": 3.0,  "output": 15.0},   # $/M tokens
    "claude-haiku-4-5":    {"input": 1.0,  "output": 5.0},
    "claude-opus-4-7":     {"input": 15.0, "output": 75.0},
}
MAX_TOOL_LOOPS = 8                 # safety cap on tool-use iterations per turn
ANTHROPIC_TIMEOUT_S = 120.0        # bumped 2026-05-18 — heavy parallel-tool turns
                                   # (e.g. 17 search_places calls in one loop) were
                                   # hitting the old 60s client timeout intermittently.


# =====================================================================
# Request / response models
# =====================================================================


class ChatMessage(BaseModel):
    role: str               # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    session_id: Optional[str] = None
    model: Optional[str] = None
    # The user's Tripideas bucket — sanity_doc_ids of saved places. When
    # present, the model is told to treat this as the canonical place list
    # and pass these to build_*_itinerary as `include_doc_ids`. See
    # system_prompt.py "THE USER'S BUCKET" section.
    bucket_doc_ids: Optional[list[str]] = None
    bucket_titles: Optional[list[str]] = None       # Optional — for nicer model context
    bucket_collection_name: Optional[str] = None


# Staging seed. Hardcoded while the chat lives on a separate domain (not
# yet embedded in tripideas.nz). When we move to embedded mode, this
# becomes a fallback only — the host page should push the active
# collection ID via the chat embed config / postMessage.
#
# This is Douglas's own "Best Idea" collection — 6 places spread across
# Otago, Auckland and Canterbury — useful exactly because it covers a
# diverse spread the trip-planning tools have to handle gracefully.
DEFAULT_TEST_COLLECTION_ID = "fc_01kb1b26ksexwveksv8se2m9g2"


# =====================================================================
# App factory
# =====================================================================


def create_app() -> FastAPI:
    app = FastAPI(title="Tripideas chat orchestrator", version=SYSTEM_PROMPT_VERSION)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://tripideas.nz",
            "https://www.tripideas.nz",
            "https://*.netlify.app",
            "http://localhost:5173",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
        ],
        allow_origin_regex=r"https://.*\.netlify\.app",
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/")
    def health() -> dict:
        from services import google_maps
        return {
            "ok": True,
            "service": "tripideas-chat",
            "prompt_version": SYSTEM_PROMPT_VERSION,
            "model_default": DEFAULT_MODEL,
            "tools": [t["name"] for t in TOOLS],
            "google_maps_configured": google_maps.is_configured(),
            "default_test_collection_id": DEFAULT_TEST_COLLECTION_ID,
        }

    @app.get("/bucket")
    def bucket(collection_id: Optional[str] = None) -> JSONResponse:
        """Return a hydrated bucket (collection + places + comments) for the
        frontend to render the BucketPanel. Read-only against Railway.

        Hardcoded to the staging-seed collection if no ID is supplied; once
        the chat embeds in tripideas.nz the host page will pass the active
        collection ID via query param.
        """
        from tools.get_user_bucket import get_user_bucket
        cid = collection_id or DEFAULT_TEST_COLLECTION_ID
        out = get_user_bucket(cid)
        if not out.ok:
            return JSONResponse(
                {"ok": False, "error_code": out.error_code, "message": out.message},
                status_code=404 if out.error_code == "COLLECTION_NOT_FOUND" else 400,
            )
        # Dataclass -> dict via asdict so the nested BucketPlace/Collection serialise
        from dataclasses import asdict as _asdict
        return JSONResponse({
            "ok": True,
            "collection": _asdict(out.collection) if out.collection else None,
            "places": [_asdict(p) for p in out.places],
            "missing_ids": out.missing_ids,
            "latency_ms": out.latency_ms,
        })

    @app.post("/chat")
    async def chat(req: ChatRequest) -> StreamingResponse:
        if not req.messages:
            return JSONResponse({"error": "messages cannot be empty"}, status_code=400)
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return JSONResponse(
                {"error": "ANTHROPIC_API_KEY not configured on server"},
                status_code=500,
            )

        model = req.model or DEFAULT_MODEL

        async def event_stream() -> AsyncGenerator[bytes, None]:
            async for chunk in run_chat_loop(
                req.messages,
                model=model,
                bucket_doc_ids=req.bucket_doc_ids,
                bucket_titles=req.bucket_titles,
                bucket_collection_name=req.bucket_collection_name,
            ):
                yield chunk

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",       # disable buffering on proxies
                "Connection": "keep-alive",
            },
        )

    return app


# =====================================================================
# Anthropic tool-use loop with SSE streaming
# =====================================================================


async def run_chat_loop(
    messages: list[ChatMessage],
    model: str,
    bucket_doc_ids: Optional[list[str]] = None,
    bucket_titles: Optional[list[str]] = None,
    bucket_collection_name: Optional[str] = None,
) -> AsyncGenerator[bytes, None]:
    """Run the Anthropic tool-use loop, yielding SSE event bytes as we go.

    Loop:
      1. Send conversation + tools to model (streaming)
      2. As text deltas arrive, emit `text` events
      3. When the model emits a tool_use block, emit `tool_use`, run the tool,
         emit `tool_result`, append the tool result to the conversation
      4. If the stop_reason is tool_use, loop again; else emit `done` and stop

    When `bucket_doc_ids` is supplied, a second `system` block is appended
    naming the bucket so the model knows to plan around those exact places.
    See `_build_bucket_system_block` for the exact text.
    """
    started = time.monotonic()
    client = anthropic.Anthropic(timeout=ANTHROPIC_TIMEOUT_S)

    # System blocks — static prompt first (cacheable), bucket context after.
    # The Anthropic SDK accepts `system` as either a string or a list of blocks.
    system_blocks: list[dict] = [{"type": "text", "text": SYSTEM_PROMPT}]
    if bucket_doc_ids:
        system_blocks.append({
            "type": "text",
            "text": _build_bucket_system_block(
                bucket_doc_ids, bucket_titles, bucket_collection_name,
            ),
        })

    # Build the conversation in Anthropic's format
    convo = [{"role": m.role, "content": m.content} for m in messages]

    total_input_tokens = 0
    total_output_tokens = 0

    for loop_i in range(MAX_TOOL_LOOPS):
        try:
            stream_ctx = client.messages.stream(
                model=model,
                max_tokens=4096,
                system=system_blocks,
                tools=TOOLS,
                messages=convo,
            )
        except Exception as e:
            yield _sse("error", {"message": f"anthropic.messages.stream failed: {e}"})
            return

        # Track tool_use blocks the model emits this turn
        tool_uses: list[dict] = []
        # Accumulate the assistant's content blocks for the convo append
        assistant_content_blocks: list[dict] = []

        with stream_ctx as stream:
            for event in stream:
                etype = event.type

                if etype == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use":
                        # Announce the tool call as soon as we see it begin
                        tool_uses.append({"id": block.id, "name": block.name, "input": {}})
                        yield _sse("tool_use", {"id": block.id, "name": block.name})
                    elif block.type == "server_tool_use":
                        # Anthropic-hosted tool (e.g. web_search). We don't
                        # dispatch — Anthropic runs it server-side and the
                        # result comes back as web_search_tool_result inline.
                        # Emit the same tool_use SSE event so the frontend
                        # shows a "running" indicator.
                        yield _sse("tool_use", {"id": block.id, "name": block.name})

                elif etype == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        yield _sse("text", {"delta": delta.text})
                    # input_json_delta arrives for tool_use blocks; we don't stream it

                elif etype == "message_delta":
                    # usage info arrives in message_delta
                    if hasattr(event, "usage") and event.usage:
                        total_output_tokens += getattr(event.usage, "output_tokens", 0) or 0

                elif etype == "message_stop":
                    pass

            # After streaming finishes, get the final message for tool_use input + usage
            final_message = stream.get_final_message()

        # Capture usage
        if hasattr(final_message, "usage"):
            total_input_tokens += getattr(final_message.usage, "input_tokens", 0) or 0
            # output_tokens already counted via message_delta but final is authoritative
            total_output_tokens = max(
                total_output_tokens,
                getattr(final_message.usage, "output_tokens", 0) or 0,
            )

        # Rebuild the assistant content list with tool_use input filled in.
        # Server-tool blocks (server_tool_use + web_search_tool_result) must
        # be preserved verbatim — they're part of the conversation state and
        # citation continuity depends on them.
        assistant_content_blocks = []
        for block in final_message.content:
            if block.type == "text":
                # Preserve citations if the SDK attached any (web search refs)
                text_block: dict = {"type": "text", "text": block.text}
                cites = getattr(block, "citations", None)
                if cites:
                    text_block["citations"] = [
                        c.model_dump() if hasattr(c, "model_dump") else c
                        for c in cites
                    ]
                assistant_content_blocks.append(text_block)
            elif block.type == "tool_use":
                assistant_content_blocks.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
            elif block.type in ("server_tool_use", "web_search_tool_result"):
                # Pass through as a dict — Anthropic needs the exact shape
                # back if this turn is later referenced (multi-turn citations).
                assistant_content_blocks.append(
                    block.model_dump() if hasattr(block, "model_dump") else dict(block)
                )
        convo.append({"role": "assistant", "content": assistant_content_blocks})

        # `pause_turn` happens when a server tool (web_search) ran but the
        # model has more to say — we loop again with no dispatch, just resume.
        # Custom tools land on `tool_use` (handled below).
        if final_message.stop_reason == "pause_turn":
            continue

        if final_message.stop_reason != "tool_use":
            # Done — emit usage + done
            cost = _calc_cost(model, total_input_tokens, total_output_tokens)
            yield _sse("usage", {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "cost_usd": round(cost, 6),
                "loops": loop_i + 1,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            })
            yield _sse("done", {"finish_reason": final_message.stop_reason})
            return

        # Run all tool_use blocks emitted this turn
        tool_result_blocks = []
        for tu in assistant_content_blocks:
            if tu["type"] != "tool_use":
                continue
            # Emit the resolved tool args so the frontend can render a richer
            # progress label (e.g. "Composing your 3-day Northland trip...")
            yield _sse("tool_args", {
                "id": tu["id"],
                "name": tu["name"],
                "args": tu["input"] or {},
            })
            tool_started = time.monotonic()
            result = dispatch_tool(tu["name"], tu["input"] or {})
            tool_elapsed = int((time.monotonic() - tool_started) * 1000)

            ok = bool(result.get("ok", True))
            summary = _summarize_tool_result(tu["name"], result)
            yield _sse("tool_result", {
                "id": tu["id"],
                "name": tu["name"],
                "ok": ok,
                "summary": summary,
                "elapsed_ms": tool_elapsed,
            })

            # Forward GeoJSON routes to the frontend so the map panel can draw
            # them. Emitted as a separate event AFTER tool_result so the tool
            # completion tick is never delayed by polyline serialization.
            route_geojson = _extract_route_geojson(tu["name"], result)
            if route_geojson:
                yield _sse("tool_result_data", {
                    "id": tu["id"],
                    "name": tu["name"],
                    "route_geojson": route_geojson,
                })

            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": tu["id"],
                "content": json.dumps(result, default=str),
            })

        convo.append({"role": "user", "content": tool_result_blocks})
        # Loop back to let the model see the tool results

    # MAX_TOOL_LOOPS exhausted
    yield _sse("error", {"message": f"Hit MAX_TOOL_LOOPS={MAX_TOOL_LOOPS}; possible loop"})
    yield _sse("done", {"finish_reason": "max_tool_loops"})


# =====================================================================
# Helpers
# =====================================================================


def _build_bucket_system_block(
    doc_ids: list[str],
    titles: Optional[list[str]],
    collection_name: Optional[str],
) -> str:
    """Compose a second `system` block telling the model about the user's bucket.

    Emitted alongside SYSTEM_PROMPT when the request includes bucket_doc_ids
    so the model treats the bucket as the canonical place set for this
    session. The frontend bucket panel + map pins already show the user
    these places visually, so the model does NOT need to call
    `render_places_on_map` to introduce them.
    """
    # Pair IDs with titles where we have them; titles are nicer for the
    # model to reason about than opaque UUIDs.
    if titles and len(titles) == len(doc_ids):
        bucket_list = "\n".join(
            f"  - {t} (sanity_doc_id: {i})" for t, i in zip(titles, doc_ids)
        )
    else:
        bucket_list = "\n".join(f"  - sanity_doc_id: {i}" for i in doc_ids)

    name_clause = f"named “{collection_name}” " if collection_name else ""

    return f"""THE USER'S BUCKET (active this session)

The user is opening the chat with a Tripideas bucket {name_clause}already loaded.
A "bucket" is a list of places they curated on Tripideas.nz before starting
this conversation. The bucket panel to the left of the chat shows them as
cards; the map already has them as pins. You do NOT need to call
`render_places_on_map` to introduce them — that's already done visually.

Bucket contents ({len(doc_ids)} places):
{bucket_list}

How to plan around a bucket:

1. **Never call `search_places` to discover places.** The user has already
   chosen. Searching would just surface alternatives they didn't ask for.

2. **Use `build_trip_itinerary`** (multi-day) or `build_day_itinerary`
   (single day) with **`include_doc_ids` set to the bucket sanity_doc_ids
   above**. This forces the planner to use exactly those places.

3. **Counter-prompt for context FIRST** (HARD_RULE #11). Bucket-aware
   planning still needs to know: travelling-with (solo/couple/family/group),
   pace (relaxed/balanced/full), and the *purpose* at each place type
   (e.g. "beaches for picnic or surfing?"). Ask ONE short question covering
   the highest-leverage missing axis before calling the planner.

4. **Day-anchor strategy.** The bucket spans multiple regions; you'll need
   to pick sensible day anchors (e.g. cluster by region/subRegion). Pass
   one `DayAnchor` per day in `build_trip_itinerary` based on the cluster
   centroids — but always include the same `include_doc_ids` list across
   the call so the no-repeat dedupe across days works on the bucket pool.

5. **Don't silently drop bucket places.** If geography or pace means a
   place can't fit, surface that explicitly ("Ahuriri Valley is a long
   detour from the others — happy to do a side-trip, or leave it for a
   separate visit?") rather than just omitting it from the plan.

6. **Refining**. When the user adjusts the plan, the bucket remains the
   canonical pool — pass it as `include_doc_ids` to `refine_itinerary`'s
   downstream `build_*` calls. Suggesting NEW places outside the bucket is
   fine only if the user explicitly asks ("anything I'm missing in
   Otago?").

This is the most common real-world entry path — users browse Tripideas,
curate their bucket, then come here to sequence it. Treat the curation as
already done."""


def _sse(event: str, data: dict) -> bytes:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["claude-sonnet-4-6"])
    return (input_tokens / 1_000_000) * pricing["input"] + (output_tokens / 1_000_000) * pricing["output"]


_GEOJSON_TOOLS = {
    "build_day_itinerary",
    "build_trip_itinerary",
    "refine_itinerary",
    "render_places_on_map",
}


def _extract_route_geojson(name: str, result: dict) -> Optional[dict]:
    """Pull the route_geojson FeatureCollection out of a tool result.

    Path varies by tool — DayPlan owns the field for day/refine, BuildTripOutput
    owns it directly for trips, render_places_on_map owns it directly too:
    - build_day_itinerary:    result["day_plan"]["route_geojson"]
    - refine_itinerary:       result["updated_plan"]["route_geojson"]
    - build_trip_itinerary:   result["route_geojson"]   (trip-wide aggregation)
    - render_places_on_map:   result["route_geojson"]   (points-only)

    Returns None for any tool that doesn't produce a route or whose result
    didn't include one (e.g. errors, empty plans).
    """
    if name not in _GEOJSON_TOOLS:
        return None
    if name == "build_day_itinerary":
        plan = result.get("day_plan") or {}
        fc = plan.get("route_geojson") if isinstance(plan, dict) else None
    elif name == "refine_itinerary":
        plan = result.get("updated_plan") or {}
        fc = plan.get("route_geojson") if isinstance(plan, dict) else None
    else:  # build_trip_itinerary, render_places_on_map
        fc = result.get("route_geojson")
    if not isinstance(fc, dict) or not fc.get("features"):
        return None
    return fc


def _summarize_tool_result(name: str, result: dict) -> str:
    """Compact one-line summary of what a tool returned, for the SSE event."""
    if not result.get("ok", True):
        return f"{name} → error: {result.get('error_code', 'unknown')}: {result.get('message', '')[:80]}"
    if name == "search_places":
        return f"search_places → {result.get('count', 0)} matches"
    if name == "search_accommodation":
        facets = result.get("facets") or {}
        bookable = facets.get("bookable_count", 0)
        return f"search_accommodation → {result.get('count', 0)} matches, {bookable} bookable now"
    if name == "get_place_summary":
        return f"get_place_summary → {result.get('title', '?')!r}"
    if name == "build_day_itinerary":
        plan = result.get("day_plan") or {}
        slots = plan.get("slots", []) if isinstance(plan, dict) else []
        place_count = sum(1 for s in slots if s.get("slot_type") == "place")
        return f"build_day_itinerary → {place_count} places at {plan.get('base_location', '?')}"
    if name == "build_trip_itinerary":
        days = result.get("days", [])
        summary = result.get("summary") or {}
        return f"build_trip_itinerary → {len(days)} days, {summary.get('total_places', 0)} places total"
    if name == "refine_itinerary":
        diff = result.get("diff") or {}
        return f"refine_itinerary ({result.get('regeneration_mode_used', '?')}) → {diff.get('summary', 'updated')}"
    if name == "find_place_by_name":
        return f"find_place_by_name → {result.get('count', 0)} matches"
    if name == "list_subregions":
        subs = result.get("subRegions") or []
        return f"list_subregions({result.get('region', '?')}) → {len(subs)} sub-regions, {result.get('total_places', 0)} places"
    if name == "render_places_on_map":
        missing = len(result.get("missing_ids") or [])
        suffix = f", {missing} unmappable" if missing else ""
        return f"render_places_on_map → {result.get('count', 0)} pins{suffix}"
    return f"{name} → ok"


__all__ = ["create_app", "run_chat_loop", "ChatMessage", "ChatRequest"]
