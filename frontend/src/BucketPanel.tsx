/**
 * BucketPanel — the user's saved Tripideas places, on the left of the chat.
 *
 * A "bucket" is a Tripideas FavCollection — a named list of places the user
 * curated in the Tripideas trip-planning tool before opening this chat. The
 * backend's `GET /bucket` endpoint reads it from Railway (Postgres) and
 * resolves each placeId to its Sanity page metadata (title, subRegion,
 * coords, comments). This panel renders that as scannable cards.
 *
 * Reads `bucket` from useChatContext (see ChatContext.tsx). The map panel
 * reads the same context for pin rendering, so the bucket → display fetch
 * happens exactly once per session.
 *
 * Three render states:
 *   - loading: skeleton placeholders
 *   - error:   surfaced via context
 *   - loaded:  collection header + scrollable place-card list
 *
 * For now (staging-only) the backend hardcodes Douglas's "Best Idea"
 * collection. When the chat embeds in tripideas.nz, the host page will
 * pass a collection_id query param.
 */

import { MapPin, Bookmark } from "lucide-react";
import { useChatContext } from "./ChatContext";


export interface BucketPanelProps {
  className?: string;
}


export function BucketPanel({ className = "" }: BucketPanelProps) {
  const { bucket, bucketLoading, bucketError } = useChatContext();

  return (
    <aside
      className={`flex h-full w-full flex-col overflow-hidden bg-brand-surface-alt text-brand-text ${className}`}
      role="region"
      aria-label="Your saved places"
    >
      <Header
        collectionName={bucket?.collection?.name}
        placeCount={bucket?.places?.length}
      />

      <div className="flex-1 overflow-y-auto">
        {bucketLoading && <LoadingState />}
        {!bucketLoading && bucketError && <ErrorState message={bucketError} />}
        {!bucketLoading && !bucketError && bucket && bucket.places.length === 0 && (
          <EmptyState />
        )}
        {!bucketLoading && !bucketError && bucket && bucket.places.length > 0 && (
          <ul className="flex flex-col gap-2 p-3">
            {bucket.places.map((p) => (
              <PlaceCard key={p.sanity_doc_id} place={p} />
            ))}
          </ul>
        )}
      </div>

      <Footer />
    </aside>
  );
}


function Header({
  collectionName,
  placeCount,
}: {
  collectionName?: string;
  placeCount?: number;
}) {
  return (
    <header className="flex items-center gap-2 border-b border-brand-border bg-brand-surface px-4 py-3">
      <Bookmark className="h-4 w-4 text-brand-primary" aria-hidden="true" />
      <div className="flex-1 min-w-0">
        <div className="truncate text-sm font-semibold text-brand-text">
          {collectionName ? `“${collectionName}”` : "Your bucket"}
        </div>
        <div className="text-[11px] text-brand-text-muted">
          {placeCount != null
            ? `${placeCount} ${placeCount === 1 ? "place" : "places"} from your Tripideas trip tool`
            : "from your Tripideas trip tool"}
        </div>
      </div>
    </header>
  );
}


function PlaceCard({
  place,
}: {
  place: {
    sanity_doc_id: string;
    title: string;
    slug?: string | null;
    region?: string | null;
    subRegion?: string | null;
    comments?: string[];
  };
}) {
  const sub = [place.subRegion, place.region && place.region !== place.subRegion ? place.region : null]
    .filter(Boolean)
    .join(" · ");
  return (
    <li className="rounded-bubble border border-brand-border bg-brand-surface px-3 py-2.5 transition-colors hover:border-brand-primary/60">
      <div className="text-sm font-semibold text-brand-text">{place.title}</div>
      {sub && (
        <div className="mt-0.5 flex items-center gap-1 text-[11px] text-brand-text-muted">
          <MapPin className="h-3 w-3" aria-hidden="true" />
          {sub}
        </div>
      )}
      {place.comments && place.comments.length > 0 && (
        <div className="mt-1.5 space-y-1">
          {place.comments.map((c, i) => (
            <div
              key={i}
              className="rounded border-l-2 border-brand-accent bg-brand-surface-alt px-2 py-1 text-[11px] italic text-brand-text-muted"
            >
              “{c}”
            </div>
          ))}
        </div>
      )}
    </li>
  );
}


function LoadingState() {
  return (
    <div className="p-3 space-y-2" aria-label="Loading bucket">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="rounded-bubble border border-brand-border bg-brand-surface px-3 py-2.5 animate-pulse"
        >
          <div className="h-3 w-3/4 rounded bg-brand-border" />
          <div className="mt-2 h-2 w-1/2 rounded bg-brand-border" />
        </div>
      ))}
      <p className="px-1 pt-1 text-[11px] text-brand-text-muted">
        Loading your saved places from Tripideas…
      </p>
    </div>
  );
}


function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center p-6 text-center">
      <Bookmark className="mb-2 h-6 w-6 text-brand-text-muted" aria-hidden="true" />
      <p className="text-sm font-medium text-brand-text">No saved places yet</p>
      <p className="mt-1 text-xs text-brand-text-muted">
        Add places to your Tripideas trip tool, then open the chat to plan around them.
      </p>
    </div>
  );
}


function ErrorState({ message }: { message: string }) {
  return (
    <div className="m-3 rounded-bubble border border-brand-border bg-brand-surface px-3 py-3 text-xs text-brand-text-muted">
      <div className="font-medium text-brand-text">Couldn't load your bucket</div>
      <div className="mt-1">{message}</div>
    </div>
  );
}


function Footer() {
  return (
    <div className="border-t border-brand-border bg-brand-surface px-3 py-2 text-[10px] text-brand-text-muted">
      Staging preview — the chat will plan around this list.
    </div>
  );
}
