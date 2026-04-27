/**
 * ChatPanel — the embeddable chat UI.
 *
 * Self-contained component with no fixed positioning, no backdrop, no
 * floating launcher. Fills its container. Use this for in-page placement
 * (e.g. /plan-a-trip).
 *
 * For the floating bottom-right popup pattern, use ChatWidget which wraps
 * ChatPanel in a positioned shell.
 *
 * Composition:
 *   <div style={{ height: 600 }}>
 *     <ChatPanel apiUrl="https://..." />
 *   </div>
 */

import { useEffect, useRef } from "react";
import { RotateCcw, Send, Sparkles, X } from "lucide-react";
import { Markdown } from "./Markdown";
import { TRIPIDEAS_THEME, applyTheme } from "./theme";
import { useChat, type ChatMessage, type ToolCall } from "./useChat";


export interface ChatPanelProps {
  apiUrl: string;
  /** Hide the brand header bar (e.g., when the host page has its own page title). */
  hideHeader?: boolean;
  /** Show an X close button in the header (used by ChatWidget's floating mode). */
  showCloseButton?: boolean;
  onClose?: () => void;
  /** Additional class names for the outer container. */
  className?: string;
}


export function ChatPanel({
  apiUrl,
  hideHeader = false,
  showCloseButton = false,
  onClose,
  className = "",
}: ChatPanelProps) {
  const { messages, input, setInput, sendMessage, reset, isStreaming } = useChat({ apiUrl });

  // Apply TripIdeas theme tokens on mount; idempotent across multiple panels
  useEffect(() => {
    applyTheme(TRIPIDEAS_THEME);
  }, []);

  // Auto-scroll the message list as new content arrives
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isStreaming]);

  // Autosize the textarea up to a max height
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage();
    }
  }

  return (
    <div
      className={`flex h-full w-full flex-col overflow-hidden bg-brand-surface text-brand-text font-sans ${className}`}
      style={{ fontFamily: "var(--ti-font-sans)" }}
      role="region"
      aria-label={`${TRIPIDEAS_THEME.brandName} trip planner`}
    >
      {!hideHeader && (
        <header className="flex items-center justify-between border-b border-brand-border bg-brand-surface px-4 py-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-primary text-white">
              <Sparkles className="h-4 w-4" aria-hidden="true" />
            </div>
            <div className="leading-tight">
              <div className="text-sm font-semibold text-brand-text">
                {TRIPIDEAS_THEME.brandName} Trip Planner
              </div>
              <div className="text-[11px] text-brand-text-muted">
                Powered by Tripideas content
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1">
            {messages.length > 0 && (
              <button
                type="button"
                onClick={reset}
                className="rounded p-1.5 text-brand-text-muted hover:bg-brand-surface-alt hover:text-brand-text"
                aria-label="New conversation"
                title="New conversation"
              >
                <RotateCcw className="h-4 w-4" />
              </button>
            )}
            {showCloseButton && onClose && (
              <button
                type="button"
                onClick={onClose}
                className="rounded p-1.5 text-brand-text-muted hover:bg-brand-surface-alt hover:text-brand-text"
                aria-label="Close chat"
              >
                <X className="h-5 w-5" />
              </button>
            )}
          </div>
        </header>
      )}

      <div
        ref={scrollRef}
        className="ti-scroll flex-1 overflow-y-auto px-4 py-4 space-y-4"
      >
        {messages.length === 0 && <Greeting onSuggest={(text) => void sendMessage(text)} />}
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
      </div>

      <div className="border-t border-brand-border bg-brand-surface p-3">
        <div className="flex items-end gap-2 rounded-bubble border border-brand-border bg-brand-surface focus-within:border-brand-primary focus-within:ring-2 focus-within:ring-brand-accent/40 transition-colors">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={TRIPIDEAS_THEME.placeholder}
            rows={1}
            disabled={isStreaming}
            className="flex-1 resize-none bg-transparent px-3 py-2.5 text-sm text-brand-text placeholder:text-brand-text-muted focus:outline-none disabled:opacity-60"
          />
          <button
            type="button"
            onClick={() => void sendMessage()}
            disabled={!input.trim() || isStreaming}
            className="m-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-bubble bg-brand-primary text-white transition-all hover:bg-brand-primary-hover disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Send message"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-1.5 px-1 text-[10px] text-brand-text-muted">
          Enter to send · Shift+Enter for newline
        </div>
      </div>
    </div>
  );
}


// =====================================================================
// Internal pieces — exported here so ChatWidget can reuse the same look
// =====================================================================


export function Greeting({ onSuggest }: { onSuggest: (text: string) => void }) {
  return (
    <div className="animate-fade-in space-y-3 rounded-bubble border border-brand-border bg-brand-surface-alt p-4 text-sm text-brand-text">
      <Markdown>{TRIPIDEAS_THEME.greeting}</Markdown>
      <div className="flex flex-wrap gap-1.5 pt-1">
        {[
          "3-day Northland coastal trip for couples",
          "Easy walks near Wellington",
          "Road trip Nelson to Christchurch",
        ].map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onSuggest(s)}
            className="rounded-full border border-brand-border bg-brand-surface px-3 py-1 text-[12px] text-brand-text-muted transition-colors hover:border-brand-primary hover:text-brand-text"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}


export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  // Show pulsing dots when assistant is streaming but has no content + no tool
  // calls yet — this is the gap between send and first SSE event.
  const isAwaitingFirstEvent =
    !isUser &&
    message.isStreaming &&
    !message.content &&
    message.toolCalls.length === 0 &&
    !message.error;

  return (
    <div
      className={`flex ${isUser ? "justify-end" : "justify-start"} animate-fade-in`}
    >
      <div
        className={
          isUser
            ? "max-w-[85%] rounded-bubble bg-brand-primary px-3.5 py-2 text-sm text-white"
            : "max-w-[92%] space-y-2 text-sm text-brand-text"
        }
      >
        {isAwaitingFirstEvent && <PulsingDots />}
        {!isUser && message.toolCalls.length > 0 && (
          <div className="space-y-1">
            {message.toolCalls.map((tc) => (
              <ToolIndicator key={tc.id} toolCall={tc} />
            ))}
          </div>
        )}
        {isUser ? (
          <span className="whitespace-pre-wrap">{message.content}</span>
        ) : message.content ? (
          <div className="rounded-bubble bg-brand-surface-alt px-3.5 py-2.5">
            <Markdown>{message.content}</Markdown>
          </div>
        ) : null}
        {message.error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-2 py-1.5 text-[12px] text-red-700">
            ⚠ {message.error}
          </div>
        )}
      </div>
    </div>
  );
}


function PulsingDots() {
  return (
    <div className="inline-flex items-center gap-1.5 rounded-bubble bg-brand-surface-alt px-3.5 py-3">
      <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-brand-text-muted [animation-delay:0ms]" />
      <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-brand-text-muted [animation-delay:150ms]" />
      <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-brand-text-muted [animation-delay:300ms]" />
    </div>
  );
}


export function ToolIndicator({ toolCall }: { toolCall: ToolCall }) {
  const label = describeToolCall(toolCall);
  if (toolCall.status === "running") {
    return (
      <div className="flex items-center gap-2 rounded-md border border-brand-border bg-brand-surface px-2.5 py-1.5 text-[12px] text-brand-text-muted">
        <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-brand-primary" />
        <span>{label}…</span>
      </div>
    );
  }
  if (toolCall.status === "error") {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 px-2.5 py-1.5 text-[12px] text-red-700">
        ⚠ {label} failed{toolCall.summary ? ` — ${toolCall.summary}` : ""}
      </div>
    );
  }
  return (
    <div className="rounded-md border border-brand-border bg-brand-surface px-2.5 py-1.5 text-[12px] text-brand-text-muted">
      ✓ {toolCall.summary ?? label}
      {typeof toolCall.elapsedMs === "number" && (
        <span className="ml-1 text-brand-text-muted/70">
          ({Math.round(toolCall.elapsedMs / 100) / 10}s)
        </span>
      )}
    </div>
  );
}


// =====================================================================
// Tool-call labelling — uses the args we get from the SSE tool_args event
// =====================================================================


function describeToolCall(tc: ToolCall): string {
  const args = tc.args ?? {};
  switch (tc.name) {
    case "search_places": {
      const region = strArg(args.region);
      const themes = arrArg(args.themes);
      const themeBit = themes.length ? ` ${themes.slice(0, 2).join("/")}` : "";
      return region
        ? `Searching${themeBit} places in ${region}`
        : "Searching places";
    }
    case "get_place_summary": {
      return "Fetching place details";
    }
    case "build_day_itinerary": {
      const base = strArg(args.base_location);
      const pace = strArg(args.pace);
      if (base) {
        return `Planning a ${pace || "balanced"} day around ${base}`;
      }
      return "Planning the day";
    }
    case "build_trip_itinerary": {
      const days = arrArg(args.day_anchors).length;
      const region = inferTripRegion(args);
      if (days && region) {
        return `Composing a ${days}-day ${region} trip`;
      }
      if (days) {
        return `Composing a ${days}-day trip`;
      }
      return "Composing the trip";
    }
    case "refine_itinerary": {
      const change = strArg(args.change_type);
      if (change && change !== "broad_adjustment") {
        return `Refining (${change.replace(/_/g, " ")})`;
      }
      return "Refining the plan";
    }
    case "search_accommodation": {
      const town = strArg(args.town);
      const region = strArg(args.region);
      const types = arrArg(args.accommodation_types);
      const goldOnly = args.gold_medal_only === true;
      const where = town || region;
      const typeBit = types.length ? ` ${(types as string[]).slice(0, 2).join("/")}` : "";
      const goldBit = goldOnly ? " Gold Medal" : "";
      if (where) {
        return `Finding${goldBit}${typeBit} accommodation in ${where}`;
      }
      return `Finding${goldBit}${typeBit} accommodation`;
    }
    default:
      return tc.name;
  }
}


function strArg(v: unknown): string | undefined {
  return typeof v === "string" && v.trim() ? v.trim() : undefined;
}


function arrArg(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}


function inferTripRegion(args: Record<string, unknown>): string | undefined {
  // Trip args have day_anchors; the first anchor's region is the natural label
  const anchors = arrArg(args.day_anchors);
  if (!anchors.length) return undefined;
  const first = anchors[0];
  if (first && typeof first === "object" && "region" in first) {
    const r = (first as { region?: unknown }).region;
    if (typeof r === "string") {
      // Show all distinct regions if multiple
      const all = new Set<string>();
      for (const a of anchors) {
        if (a && typeof a === "object" && "region" in a) {
          const reg = (a as { region?: unknown }).region;
          if (typeof reg === "string") all.add(reg);
        }
      }
      return Array.from(all).slice(0, 2).join(" → ");
    }
  }
  return undefined;
}
