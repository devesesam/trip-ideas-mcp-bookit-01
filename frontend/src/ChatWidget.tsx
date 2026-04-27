/**
 * ChatWidget — floating bottom-right launcher that opens the ChatPanel
 * in a fixed-position shell (full-screen on mobile).
 *
 * Use this for embedding on pages where the chat is a *secondary* feature
 * (e.g., a help button on every page). For the primary "/plan-a-trip"-style
 * chat experience, use <ChatPanel> directly so it sits inline with the page.
 *
 * Composition:
 *   <ChatWidget apiUrl="https://..." />
 */

import { useState } from "react";
import { MessageCircle } from "lucide-react";
import { ChatPanel } from "./ChatPanel";
import { TRIPIDEAS_THEME } from "./theme";


interface Props {
  apiUrl: string;
  /** Start opened on mount. Useful for the demo page. */
  defaultOpen?: boolean;
}


export function ChatWidget({ apiUrl, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="font-sans" style={{ fontFamily: "var(--ti-font-sans)" }}>
      {!open && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="fixed bottom-6 right-6 z-[9998] flex items-center gap-2 rounded-full bg-brand-primary px-5 py-3 text-white shadow-widget transition-all hover:bg-brand-primary-hover hover:scale-105 focus:outline-none focus:ring-4 focus:ring-brand-accent/40"
          aria-label={`Open ${TRIPIDEAS_THEME.brandName} chat`}
        >
          <MessageCircle className="h-5 w-5" aria-hidden="true" />
          <span className="text-sm font-medium">Plan a trip</span>
        </button>
      )}

      {open && (
        <div
          className="fixed inset-0 z-[9999] flex items-end justify-end p-0 sm:p-6 animate-fade-in"
          role="dialog"
          aria-label={`${TRIPIDEAS_THEME.brandName} trip planner`}
        >
          {/* Backdrop on mobile only */}
          <div
            className="absolute inset-0 bg-black/40 sm:hidden"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />

          <div className="relative h-full w-full max-h-[100dvh] overflow-hidden border border-brand-border bg-brand-surface shadow-widget animate-slide-up sm:h-[640px] sm:max-h-[85vh] sm:w-[420px] sm:rounded-widget">
            <ChatPanel
              apiUrl={apiUrl}
              showCloseButton
              onClose={() => setOpen(false)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
