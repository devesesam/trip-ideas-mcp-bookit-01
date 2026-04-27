/**
 * Entry point for the Tripideas chat bundle.
 *
 * Auto-mounts into <div id="tripideas-chat"> on DOMContentLoaded. The host
 * page chooses the rendering mode via attributes on the mount div:
 *
 *   <div id="tripideas-chat"
 *        data-mode="embedded"            // "embedded" (default) | "floating"
 *        data-api-url="https://..."      // optional override of the chat API
 *        data-default-open="true"        // floating-mode only: open on mount
 *   ></div>
 *
 * "embedded" mode (recommended for the dedicated /plan-a-trip page):
 *   ChatPanel fills the mount div. Set the div's height in your page CSS
 *   (e.g., `height: 80vh`) and the panel will fill it.
 *
 * "floating" mode:
 *   Bottom-right launcher button that opens a panel overlay. Use this if
 *   the chat is a secondary feature on a non-dedicated page.
 *
 * API URL resolution order:
 *   1. data-api-url on the mount div                     (per-page override)
 *   2. data-api-url on the <script> tag we were loaded from
 *   3. VITE_API_URL env var (set at build time)
 *   4. http://localhost:8000/chat                        (dev fallback)
 */

import React from "react";
import ReactDOM from "react-dom/client";
import { ChatPanel } from "./ChatPanel";
import { ChatWidget } from "./ChatWidget";
import "./styles.css";


const DEFAULT_DEV_API = "http://localhost:8000/chat";
const MOUNT_ID = "tripideas-chat";


function resolveApiUrl(mountEl: HTMLElement | null): string {
  // 1. Per-page override on the mount div
  const fromMount = mountEl?.getAttribute("data-api-url");
  if (fromMount) return fromMount;

  // 2. <script data-api-url="...">
  if (typeof document !== "undefined") {
    const scripts = document.querySelectorAll<HTMLScriptElement>(
      "script[data-api-url]",
    );
    for (const s of scripts) {
      const url = s.getAttribute("data-api-url");
      if (url) return url;
    }
  }

  // 3. Build-time env var
  const envUrl = (import.meta.env.VITE_API_URL as string | undefined)?.trim();
  if (envUrl) return envUrl;

  // 4. Dev fallback
  return DEFAULT_DEV_API;
}


function resolveMode(mountEl: HTMLElement): "embedded" | "floating" {
  const m = mountEl.getAttribute("data-mode")?.toLowerCase();
  return m === "floating" ? "floating" : "embedded";
}


function mount() {
  const mountEl = document.getElementById(MOUNT_ID);
  if (!mountEl) {
    console.warn(
      `[tripideas-chat] No <div id="${MOUNT_ID}"> on the page; widget not mounted.`,
    );
    return;
  }

  const apiUrl = resolveApiUrl(mountEl);
  const mode = resolveMode(mountEl);
  const defaultOpen = mountEl.getAttribute("data-default-open") === "true";

  const root = ReactDOM.createRoot(mountEl);

  if (mode === "embedded") {
    root.render(
      <React.StrictMode>
        <ChatPanel apiUrl={apiUrl} />
      </React.StrictMode>,
    );
  } else {
    root.render(
      <React.StrictMode>
        <ChatWidget apiUrl={apiUrl} defaultOpen={defaultOpen} />
      </React.StrictMode>,
    );
  }
}


if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
}
