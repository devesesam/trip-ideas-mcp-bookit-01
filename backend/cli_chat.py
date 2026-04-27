"""Local CLI chat — talk to the Tripideas orchestrator from your terminal.

Doesn't need Modal or Netlify. Runs the full Anthropic tool-use loop in-process,
hitting live Sanity for tool calls. Useful for testing the system prompt + tool
contracts before deploying anywhere.

Setup (one-off):
    pip install -r backend/requirements.txt
    # then add ANTHROPIC_API_KEY=sk-ant-... to .env at repo root

Run:
    python backend/cli_chat.py

Commands inside the chat:
    /reset          — clear conversation and start over
    /usage          — print accumulated token + cost so far
    /quit           — exit
    /verbose        — toggle verbose tool result printing
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

# Path setup so backend.* and execution.* import correctly
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
except ImportError:
    pass

from backend.orchestrator import ChatMessage, run_chat_loop, DEFAULT_MODEL  # noqa: E402


VERBOSE = False


# --- Pretty terminal output ---------------------------------------------------

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    USER = "\033[36m"           # cyan
    ASSISTANT = "\033[92m"      # bright green
    TOOL = "\033[33m"           # yellow
    ERROR = "\033[91m"          # red
    META = "\033[90m"           # grey


def _color(text: str, color: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{color}{text}{C.RESET}"


def _print_assistant_inline(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _print_meta(text: str) -> None:
    print(_color(text, C.META))


def _print_tool_use(name: str) -> None:
    print(_color(f"\n  ⚙ {name}…", C.TOOL), end="", flush=True)


def _print_tool_result(name: str, ok: bool, summary: str, elapsed_ms: int) -> None:
    color = C.TOOL if ok else C.ERROR
    print(_color(f" ({elapsed_ms}ms) — {summary}", color))


def _print_usage(usage: dict) -> None:
    print()
    _print_meta(
        f"  [tokens in={usage.get('input_tokens', 0)} out={usage.get('output_tokens', 0)} "
        f"cost=${usage.get('cost_usd', 0):.4f} loops={usage.get('loops', 0)} "
        f"elapsed={usage.get('elapsed_ms', 0)}ms]"
    )


# --- Main loop ----------------------------------------------------------------


async def chat_turn(messages: list[ChatMessage], model: str) -> tuple[str, dict]:
    """Run one turn: model + tool-use loop. Returns (assistant_text, usage_dict)."""
    assistant_text_parts: list[str] = []
    usage: dict = {}
    print()
    print(_color("Tripideas:", C.ASSISTANT), end=" ", flush=True)

    async for chunk in run_chat_loop(messages, model=model):
        # chunk is bytes of the form b"event: <name>\ndata: <json>\n\n"
        text = chunk.decode("utf-8", errors="replace")
        for line in text.splitlines():
            if line.startswith("event: "):
                current_event = line[7:].strip()
            elif line.startswith("data: "):
                try:
                    payload = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if current_event == "text":
                    delta = payload.get("delta", "")
                    assistant_text_parts.append(delta)
                    _print_assistant_inline(delta)
                elif current_event == "tool_use":
                    _print_tool_use(payload.get("name", "?"))
                elif current_event == "tool_result":
                    _print_tool_result(
                        payload.get("name", "?"),
                        payload.get("ok", True),
                        payload.get("summary", ""),
                        payload.get("elapsed_ms", 0),
                    )
                    if VERBOSE:
                        _print_meta(f"    {json.dumps(payload, ensure_ascii=False)[:300]}")
                elif current_event == "usage":
                    usage = payload
                elif current_event == "error":
                    print(_color(f"\n  ⚠ {payload.get('message', '')}", C.ERROR))
                elif current_event == "done":
                    pass

    print()
    if usage:
        _print_usage(usage)
    return "".join(assistant_text_parts), usage


def main() -> None:
    global VERBOSE

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(_color(
            "ERROR: ANTHROPIC_API_KEY not set. Add it to .env at repo root, then re-run.",
            C.ERROR,
        ))
        print(_color(
            "  Example .env line: ANTHROPIC_API_KEY=sk-ant-api03-...",
            C.META,
        ))
        sys.exit(1)

    model = os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)

    print(_color(
        f"Tripideas chat (CLI) — model: {model}, prompt v0.1.0\n"
        f"Commands: /reset, /usage, /verbose, /quit\n",
        C.META,
    ))

    history: list[ChatMessage] = []
    total_cost = 0.0
    total_in = 0
    total_out = 0

    while True:
        try:
            user_input = input(_color("You: ", C.USER)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input == "/quit":
            break
        if user_input == "/reset":
            history = []
            print(_color("  (history cleared)", C.META))
            continue
        if user_input == "/verbose":
            VERBOSE = not VERBOSE
            print(_color(f"  (verbose = {VERBOSE})", C.META))
            continue
        if user_input == "/usage":
            print(_color(
                f"  Session: in={total_in} out={total_out} cost=${total_cost:.4f}",
                C.META,
            ))
            continue

        history.append(ChatMessage(role="user", content=user_input))

        try:
            assistant_text, usage = asyncio.run(chat_turn(history, model=model))
        except KeyboardInterrupt:
            print(_color("\n  (interrupted)", C.META))
            continue
        except Exception as e:
            print(_color(f"\n  ERROR: {type(e).__name__}: {e}", C.ERROR))
            history.pop()        # don't keep the failed turn
            continue

        if assistant_text.strip():
            history.append(ChatMessage(role="assistant", content=assistant_text))

        total_cost += usage.get("cost_usd", 0)
        total_in += usage.get("input_tokens", 0)
        total_out += usage.get("output_tokens", 0)


if __name__ == "__main__":
    main()
