/**
 * Tripideas brand tokens.
 *
 * These are PLACEHOLDERS until we capture the real Tripideas brand from
 * tripideas.nz. Once Douglas (or you, with dev tools) provides:
 *   - primary brand color
 *   - accent color
 *   - body / heading font families
 *   - logo URL
 * — swap them into this file. Tailwind classes that reference `brand.*`
 * pick up the change with no other edits required.
 *
 * Color format: space-separated RGB triples (e.g. "8 145 178" for #0891b2)
 * because Tailwind's `<alpha-value>` shorthand needs them that way.
 */

export interface BrandTheme {
  primary: string;          // RGB triple, e.g. "8 145 178"
  primaryHover: string;
  accent: string;
  surface: string;          // background of the chat panel
  surfaceAlt: string;       // alt background (e.g. assistant bubble)
  text: string;
  textMuted: string;
  border: string;

  fontSans: string;         // CSS font stack
  fontHeading: string;

  radiusWidget: string;     // e.g. "0.75rem"
  radiusBubble: string;

  logoUrl?: string;
  brandName: string;
  greeting: string;         // first message shown to the user
  placeholder: string;      // input placeholder text
}

/**
 * TripIdeas theme — editorial-minimal, photo-driven, black/white with a
 * sky-blue accent. Captured 2026-04-27 from tripideas.nz screenshots +
 * Tailwind CSS dump (`--tw-ring-color: rgb(175 222 255 / 0.5)` and
 * `border: 0 solid #cdcdcd`). Refine in one follow-up pass after first eyeball.
 */
export const TRIPIDEAS_THEME: BrandTheme = {
  // Black is the primary brand color — used for buttons, headings, send button
  primary: "0 0 0",                // #000000
  primaryHover: "38 38 38",        // #262626 — soft hover for black
  // Sky-blue accent (homepage map widget background, focus ring)
  accent: "175 222 255",           // #afdeff
  // Surfaces
  surface: "255 255 255",          // white
  surfaceAlt: "250 250 250",       // #fafafa — barely-tinted alt for assistant bubbles
  text: "0 0 0",                   // #000000
  textMuted: "115 115 115",        // #737373 — Marlborough subtitle on Blenheim page
  border: "205 205 205",           // #cdcdcd — TripIdeas Tailwind border default

  fontSans: '"Inter", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  fontHeading: '"Inter", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif',

  radiusWidget: "0.5rem",          // tighter than the placeholder; matches editorial feel
  radiusBubble: "0.625rem",

  brandName: "Trip Ideas",
  greeting:
    "Kia ora! I can help plan your New Zealand trip. Tell me what you're after — *a 3-day coastal Northland trip for couples*, *easy walks near Wellington*, or *a road trip from Nelson to Christchurch*.",
  placeholder: "Where are you off to next?",
};

/**
 * Apply theme tokens to CSS custom properties on the document root.
 * Called once on widget mount; idempotent.
 */
export function applyTheme(theme: BrandTheme = TRIPIDEAS_THEME): void {
  const root = document.documentElement;
  root.style.setProperty("--ti-primary", theme.primary);
  root.style.setProperty("--ti-primary-hover", theme.primaryHover);
  root.style.setProperty("--ti-accent", theme.accent);
  root.style.setProperty("--ti-surface", theme.surface);
  root.style.setProperty("--ti-surface-alt", theme.surfaceAlt);
  root.style.setProperty("--ti-text", theme.text);
  root.style.setProperty("--ti-text-muted", theme.textMuted);
  root.style.setProperty("--ti-border", theme.border);
  root.style.setProperty("--ti-font-sans", theme.fontSans);
  root.style.setProperty("--ti-font-heading", theme.fontHeading);
  root.style.setProperty("--ti-radius-widget", theme.radiusWidget);
  root.style.setProperty("--ti-radius-bubble", theme.radiusBubble);
}
