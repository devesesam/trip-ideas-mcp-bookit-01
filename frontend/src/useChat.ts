/**
 * Custom React hook talking to the Tripideas chat backend.
 *
 * Why not @ai-sdk/react useChat? Their hook expects a specific Data Stream
 * Protocol format which our FastAPI orchestrator doesn't emit (we use plain
 * named SSE events: text, tool_use, tool_result, usage, done). Rolling our
 * own keeps both ends decoupled and the protocol simple.
 *
 * SSE event format (from backend/orchestrator.py):
 *   event: text              data: {"delta": "..."}
 *   event: tool_use          data: {"id": "...", "name": "..."}
 *   event: tool_args         data: {"id": "...", "name": "...", "args": {...}}
 *   event: tool_result       data: {"id": "...", "name": "...", "ok": bool, "summary": "...", "elapsed_ms": N}
 *   event: tool_result_data  data: {"id": "...", "name": "...", "route_geojson": {...}}    (itinerary tools only)
 *   event: usage             data: {"input_tokens": N, "output_tokens": N, "cost_usd": ..., "loops": N, "elapsed_ms": N}
 *   event: error             data: {"message": "..."}
 *   event: done              data: {"finish_reason": "..."}
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export type ToolCallStatus = "running" | "done" | "error";

export interface ToolCall {
  id: string;
  name: string;
  status: ToolCallStatus;
  /** Arguments the model passed to this tool (populated by the tool_args event,
   *  arrives just before the tool actually runs). Used by the UI to render a
   *  contextual progress label like "Composing your 3-day Northland trip". */
  args?: Record<string, unknown>;
  summary?: string;
  elapsedMs?: number;
  /** GeoJSON FeatureCollection from itinerary tools. Populated by the
   *  `tool_result_data` SSE event for build_day_itinerary, build_trip_itinerary,
   *  and refine_itinerary. Stripped from localStorage to avoid quota issues —
   *  in-memory only. */
  routeGeoJson?: Record<string, unknown>;
}

export interface UsageStats {
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
  loops: number;
  elapsedMs: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls: ToolCall[];
  isStreaming: boolean;
  usage?: UsageStats;
  error?: string;
}

export interface UseChatOptions {
  apiUrl: string;
  storageKey?: string;        // localStorage key for persistence
  onError?: (err: Error) => void;
}

export interface UseChatReturn {
  messages: ChatMessage[];
  input: string;
  setInput: (v: string) => void;
  sendMessage: (text?: string) => Promise<void>;
  reset: () => void;
  isStreaming: boolean;
  totalCostUsd: number;
  /** GeoJSON from the most recent completed itinerary tool call. The map
   *  panel reads this. Walks messages + tool calls in reverse chronological
   *  order and returns the first `routeGeoJson` found. `null` until the
   *  first itinerary tool completes. */
  latestRoute: Record<string, unknown> | null;
  /** Stable id for the latest route — changes only when a new geojson arrives.
   *  Useful as a React `key` to force-remount the map on update. */
  latestRouteId: string | null;
  /** True while an itinerary tool is currently running (build_day_itinerary,
   *  build_trip_itinerary, refine_itinerary). The map panel uses this to show
   *  a loading state. */
  isBuildingItinerary: boolean;
}

const STORAGE_KEY_DEFAULT = "tripideas_chat_history_v1";


function newId(): string {
  // No crypto.randomUUID to keep it light and broadly supported.
  return Math.random().toString(36).slice(2, 11) + Date.now().toString(36);
}


function loadHistory(key: string): ChatMessage[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ChatMessage[];
    // Defensive: clear streaming flags from any persisted in-flight messages
    return parsed.map((m) => ({ ...m, isStreaming: false }));
  } catch {
    return [];
  }
}


function saveHistory(key: string, messages: ChatMessage[]): void {
  if (typeof window === "undefined") return;
  try {
    // Strip routeGeoJson from every tool call before persisting — a single
    // trip can be ~250 KB and localStorage has a 5–10 MB origin quota.
    // After a reload `latestRoute` is null until the next itinerary tool runs.
    const slim = messages.map((m) => ({
      ...m,
      toolCalls: m.toolCalls.map(({ routeGeoJson: _drop, ...rest }) => rest),
    }));
    window.localStorage.setItem(key, JSON.stringify(slim));
  } catch {
    // localStorage might be full or disabled; non-fatal
  }
}


export function useChat({
  apiUrl,
  storageKey = STORAGE_KEY_DEFAULT,
  onError,
}: UseChatOptions): UseChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>(() => loadHistory(storageKey));
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Persist on every change
  useEffect(() => {
    saveHistory(storageKey, messages);
  }, [messages, storageKey]);

  const totalCostUsd = useMemo(
    () => messages.reduce((s, m) => s + (m.usage?.costUsd ?? 0), 0),
    [messages],
  );

  // Walk messages newest → oldest, then their tool calls newest → oldest,
  // and return the first routeGeoJson found. The id is the originating
  // tool_use id, stable across renders until a new geojson arrives.
  const { latestRoute, latestRouteId } = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      for (let j = m.toolCalls.length - 1; j >= 0; j--) {
        const tc = m.toolCalls[j];
        if (tc.routeGeoJson) {
          return { latestRoute: tc.routeGeoJson, latestRouteId: tc.id };
        }
      }
    }
    return { latestRoute: null, latestRouteId: null };
  }, [messages]);

  const isBuildingItinerary = useMemo(() => {
    if (!isStreaming) return false;
    const last = messages[messages.length - 1];
    if (!last) return false;
    return last.toolCalls.some(
      (tc) =>
        tc.status === "running" &&
        (tc.name === "build_day_itinerary" ||
          tc.name === "build_trip_itinerary" ||
          tc.name === "refine_itinerary"),
    );
  }, [isStreaming, messages]);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setMessages([]);
    setIsStreaming(false);
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(storageKey);
    }
  }, [storageKey]);

  const sendMessage = useCallback(
    async (textArg?: string) => {
      const text = (textArg ?? input).trim();
      if (!text || isStreaming) return;

      const userMsg: ChatMessage = {
        id: newId(),
        role: "user",
        content: text,
        toolCalls: [],
        isStreaming: false,
      };
      const assistantMsg: ChatMessage = {
        id: newId(),
        role: "assistant",
        content: "",
        toolCalls: [],
        isStreaming: true,
      };
      const assistantId = assistantMsg.id;

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setInput("");
      setIsStreaming(true);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        // Build the messages payload (don't send the empty assistant placeholder)
        const payload = {
          messages: [...messages, userMsg].map((m) => ({
            role: m.role,
            content: m.content,
          })),
        };

        const response = await fetch(apiUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          throw new Error(`Backend ${response.status} ${response.statusText}`);
        }

        await consumeSSE(response.body, (event, data) => {
          setMessages((prev) =>
            prev.map((m) => {
              if (m.id !== assistantId) return m;
              return applyEventToMessage(m, event, data);
            }),
          );
        });
      } catch (err) {
        const e = err instanceof Error ? err : new Error(String(err));
        if (e.name === "AbortError") {
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, isStreaming: false } : m)),
          );
        } else {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, isStreaming: false, error: e.message }
                : m,
            ),
          );
          onError?.(e);
        }
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
        // Mark as not streaming in case the SSE done event was never received
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, isStreaming: false } : m)),
        );
      }
    },
    [apiUrl, input, isStreaming, messages, onError],
  );

  return {
    messages,
    input,
    setInput,
    sendMessage,
    reset,
    isStreaming,
    totalCostUsd,
    latestRoute,
    latestRouteId,
    isBuildingItinerary,
  };
}


// =====================================================================
// SSE consumption + event → message reducer
// =====================================================================

async function consumeSSE(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: string, data: Record<string, unknown>) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Parse SSE: events are separated by \n\n, fields by \n.
    let sepIdx: number;
    while ((sepIdx = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, sepIdx);
      buffer = buffer.slice(sepIdx + 2);

      let eventName = "message";
      const dataLines: string[] = [];
      for (const line of rawEvent.split("\n")) {
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trimStart());
        }
      }
      if (!dataLines.length) continue;

      try {
        const data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
        onEvent(eventName, data);
      } catch {
        // ignore malformed events; keep streaming
      }
    }
  }
}


function applyEventToMessage(
  msg: ChatMessage,
  event: string,
  data: Record<string, unknown>,
): ChatMessage {
  switch (event) {
    case "text": {
      const delta = String(data.delta ?? "");
      return { ...msg, content: msg.content + delta };
    }
    case "tool_use": {
      const id = String(data.id ?? newId());
      const name = String(data.name ?? "?");
      // Avoid duplicates if backend re-emits
      if (msg.toolCalls.some((c) => c.id === id)) return msg;
      return {
        ...msg,
        toolCalls: [
          ...msg.toolCalls,
          { id, name, status: "running" },
        ],
      };
    }
    case "tool_args": {
      // Backend emits this just before dispatching the tool. We attach the
      // resolved args so the UI can render a richer progress label.
      const id = String(data.id ?? "");
      const args = (data.args && typeof data.args === "object")
        ? (data.args as Record<string, unknown>)
        : undefined;
      return {
        ...msg,
        toolCalls: msg.toolCalls.map((c) =>
          c.id === id ? { ...c, args } : c,
        ),
      };
    }
    case "tool_result": {
      const id = String(data.id ?? "");
      const ok = Boolean(data.ok ?? true);
      const summary = data.summary ? String(data.summary) : undefined;
      const elapsedMs = typeof data.elapsed_ms === "number" ? data.elapsed_ms : undefined;
      return {
        ...msg,
        toolCalls: msg.toolCalls.map((c) =>
          c.id === id
            ? { ...c, status: ok ? "done" : "error", summary, elapsedMs }
            : c,
        ),
      };
    }
    case "tool_result_data": {
      // Emitted by the backend after tool_result for itinerary tools, carrying
      // the route_geojson FeatureCollection. Attaches to the matching tool call.
      const id = String(data.id ?? "");
      const geojson = data.route_geojson;
      if (!geojson || typeof geojson !== "object") return msg;
      return {
        ...msg,
        toolCalls: msg.toolCalls.map((c) =>
          c.id === id
            ? { ...c, routeGeoJson: geojson as Record<string, unknown> }
            : c,
        ),
      };
    }
    case "usage": {
      return {
        ...msg,
        usage: {
          inputTokens: Number(data.input_tokens ?? 0),
          outputTokens: Number(data.output_tokens ?? 0),
          costUsd: Number(data.cost_usd ?? 0),
          loops: Number(data.loops ?? 0),
          elapsedMs: Number(data.elapsed_ms ?? 0),
        },
      };
    }
    case "error": {
      return { ...msg, error: String(data.message ?? "unknown error"), isStreaming: false };
    }
    case "done": {
      return { ...msg, isStreaming: false };
    }
    default:
      return msg;
  }
}
