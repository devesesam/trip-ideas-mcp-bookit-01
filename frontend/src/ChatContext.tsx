/**
 * Provides a single `useChat` instance — plus the user's bucket — to a subtree.
 *
 * Both embedded and floating modes wrap their UI in `<ChatProvider>` (see
 * `main.tsx`). This lets `ChatPanel`, `MapPanel`, and `BucketPanel` siblings
 * share one conversation, one bucket fetch, and one source of truth for
 * `latestRoute` — without prop drilling or duplicate `useChat()` calls
 * (which would set up conflicting localStorage writers).
 *
 * Bucket lifecycle:
 *   - On mount, fetches `GET <apiBase>/bucket` (apiUrl with /chat → /bucket).
 *   - Exposes `bucket`, `bucketLoading`, `bucketError` for the panel + map.
 *   - Passes the bucket's sanity_doc_ids + titles into useChat as
 *     `bucketDocIds` / `bucketTitles` so every /chat request includes them.
 *
 * Bucket fetch failures are non-fatal — the chat still works for users
 * without a bucket. Errors are surfaced via `bucketError` for the panel
 * to display.
 *
 * Consumers call `useChatContext()`. Throws if used outside a provider so
 * mistakes surface immediately instead of falling back to silent duplication.
 */

import React, { createContext, useContext, useEffect, useState } from "react";
import { useChat, UseChatReturn } from "./useChat";


// =====================================================================
// Bucket types — matched to backend's GetUserBucketOutput dataclass
// =====================================================================

export interface BucketPlace {
  sanity_doc_id: string;
  title: string;
  slug?: string | null;
  region?: string | null;
  subRegion?: string | null;
  coords?: { lat?: number; lng?: number } | null;
  favourited_at?: string | null;
  comments?: string[];
}

export interface BucketCollection {
  id: string;
  name: string;
  owner_email?: string | null;
  owner_user_id?: string | null;
}

export interface Bucket {
  collection: BucketCollection;
  places: BucketPlace[];
  missing_ids?: string[];
}


// =====================================================================
// Context shape — useChat returns + bucket state
// =====================================================================

export interface ChatContextValue extends UseChatReturn {
  bucket: Bucket | null;
  bucketLoading: boolean;
  bucketError: string | null;
}


const ChatContext = createContext<ChatContextValue | null>(null);


export interface ChatProviderProps {
  apiUrl: string;
  children: React.ReactNode;
}


/** Derive the bucket endpoint from the configured /chat endpoint. */
function deriveBucketUrl(apiUrl: string): string {
  // Typical apiUrl: "https://devesesam--tripideas-chat-web.modal.run/chat"
  if (/\/chat\/?$/.test(apiUrl)) {
    return apiUrl.replace(/\/chat\/?$/, "/bucket");
  }
  // Fallback: assume the API base is apiUrl and bucket is a sibling path
  return apiUrl.replace(/\/?$/, "") + "/bucket";
}


export function ChatProvider({ apiUrl, children }: ChatProviderProps) {
  const [bucket, setBucket] = useState<Bucket | null>(null);
  const [bucketLoading, setBucketLoading] = useState(true);
  const [bucketError, setBucketError] = useState<string | null>(null);

  // Fetch the bucket once on mount. The backend hardcodes Douglas's
  // "Best Idea" collection during staging; once the chat embeds on
  // tripideas.nz the host page will pass a collection_id query param.
  useEffect(() => {
    let cancelled = false;
    const url = deriveBucketUrl(apiUrl);
    setBucketLoading(true);
    setBucketError(null);
    fetch(url)
      .then(async (r) => {
        if (!r.ok) {
          throw new Error(`Bucket fetch ${r.status} ${r.statusText}`);
        }
        return (await r.json()) as {
          ok: boolean;
          collection?: BucketCollection;
          places?: BucketPlace[];
          missing_ids?: string[];
          error_code?: string;
          message?: string;
        };
      })
      .then((data) => {
        if (cancelled) return;
        if (!data.ok || !data.collection) {
          setBucket(null);
          setBucketError(
            data.message ?? `Bucket not available (${data.error_code ?? "unknown"})`,
          );
          return;
        }
        setBucket({
          collection: data.collection,
          places: data.places ?? [],
          missing_ids: data.missing_ids,
        });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        setBucketError(msg);
        setBucket(null);
      })
      .finally(() => {
        if (!cancelled) setBucketLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [apiUrl]);

  // Hand the bucket ids + titles to useChat so they ride on every /chat request
  const bucketDocIds = bucket?.places.map((p) => p.sanity_doc_id) ?? undefined;
  const bucketTitles = bucket?.places.map((p) => p.title) ?? undefined;
  const bucketCollectionName = bucket?.collection.name;

  const chat = useChat({
    apiUrl,
    bucketDocIds,
    bucketTitles,
    bucketCollectionName,
  });

  const value: ChatContextValue = {
    ...chat,
    bucket,
    bucketLoading,
    bucketError,
  };

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}


export function useChatContext(): ChatContextValue {
  const ctx = useContext(ChatContext);
  if (!ctx) {
    throw new Error(
      "useChatContext must be used inside <ChatProvider>. Check that main.tsx wraps your component tree.",
    );
  }
  return ctx;
}
