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

from backend.system_prompt import SYSTEM_PROMPT, SYSTEM_PROMPT_VERSION  # noqa: E402
from backend.tool_definitions import TOOLS, dispatch_tool  # noqa: E402


# Pricing (Sonnet 4.6 as of writing) for the cost telemetry.
# Update when switching models.
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
MODEL_PRICING = {
    "claude-sonnet-4-6":   {"input": 3.0,  "output": 15.0},   # $/M tokens
    "claude-haiku-4-5":    {"input": 1.0,  "output": 5.0},
    "claude-opus-4-7":     {"input": 15.0, "output": 75.0},
}
MAX_TOOL_LOOPS = 8                 # safety cap on tool-use iterations per turn
ANTHROPIC_TIMEOUT_S = 60.0


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
        }

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
            async for chunk in run_chat_loop(req.messages, model=model):
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
) -> AsyncGenerator[bytes, None]:
    """Run the Anthropic tool-use loop, yielding SSE event bytes as we go.

    Loop:
      1. Send conversation + tools to model (streaming)
      2. As text deltas arrive, emit `text` events
      3. When the model emits a tool_use block, emit `tool_use`, run the tool,
         emit `tool_result`, append the tool result to the conversation
      4. If the stop_reason is tool_use, loop again; else emit `done` and stop
    """
    started = time.monotonic()
    client = anthropic.Anthropic(timeout=ANTHROPIC_TIMEOUT_S)

    # Build the conversation in Anthropic's format
    convo = [{"role": m.role, "content": m.content} for m in messages]

    total_input_tokens = 0
    total_output_tokens = 0

    for loop_i in range(MAX_TOOL_LOOPS):
        try:
            stream_ctx = client.messages.stream(
                model=model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
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

        # Rebuild the assistant content list with tool_use input filled in
        assistant_content_blocks = []
        for block in final_message.content:
            if block.type == "text":
                assistant_content_blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content_blocks.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
        convo.append({"role": "assistant", "content": assistant_content_blocks})

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


def _sse(event: str, data: dict) -> bytes:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["claude-sonnet-4-6"])
    return (input_tokens / 1_000_000) * pricing["input"] + (output_tokens / 1_000_000) * pricing["output"]


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
    return f"{name} → ok"


__all__ = ["create_app", "run_chat_loop", "ChatMessage", "ChatRequest"]
