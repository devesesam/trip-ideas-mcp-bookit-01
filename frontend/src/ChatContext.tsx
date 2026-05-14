/**
 * Provides a single `useChat` instance to a subtree.
 *
 * Both embedded and floating modes wrap their UI in `<ChatProvider>` (see
 * `main.tsx`). This lets `ChatPanel` and `MapPanel` siblings share one
 * conversation + one SSE stream + one source of truth for `latestRoute` —
 * without prop drilling or duplicate `useChat()` calls (which would set up
 * conflicting localStorage writers).
 *
 * Consumers call `useChatContext()`. Throws if used outside a provider so
 * mistakes surface immediately instead of falling back to silent duplication.
 */

import React, { createContext, useContext } from "react";
import { useChat, UseChatReturn } from "./useChat";

const ChatContext = createContext<UseChatReturn | null>(null);

export interface ChatProviderProps {
  apiUrl: string;
  children: React.ReactNode;
}

export function ChatProvider({ apiUrl, children }: ChatProviderProps) {
  const chat = useChat({ apiUrl });
  return <ChatContext.Provider value={chat}>{children}</ChatContext.Provider>;
}

export function useChatContext(): UseChatReturn {
  const ctx = useContext(ChatContext);
  if (!ctx) {
    throw new Error(
      "useChatContext must be used inside <ChatProvider>. Check that main.tsx wraps your component tree.",
    );
  }
  return ctx;
}
