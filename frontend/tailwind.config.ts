import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Brand tokens map to CSS custom properties so the host page (or theme.ts)
        // can override at runtime without a rebuild.
        brand: {
          primary: "rgb(var(--ti-primary) / <alpha-value>)",
          "primary-hover": "rgb(var(--ti-primary-hover) / <alpha-value>)",
          accent: "rgb(var(--ti-accent) / <alpha-value>)",
          surface: "rgb(var(--ti-surface) / <alpha-value>)",
          "surface-alt": "rgb(var(--ti-surface-alt) / <alpha-value>)",
          text: "rgb(var(--ti-text) / <alpha-value>)",
          "text-muted": "rgb(var(--ti-text-muted) / <alpha-value>)",
          border: "rgb(var(--ti-border) / <alpha-value>)",
        },
      },
      fontFamily: {
        sans: ["var(--ti-font-sans)"],
        heading: ["var(--ti-font-heading)"],
      },
      borderRadius: {
        widget: "var(--ti-radius-widget)",
        bubble: "var(--ti-radius-bubble)",
      },
      boxShadow: {
        widget: "0 10px 40px -10px rgb(0 0 0 / 0.25)",
      },
      animation: {
        "fade-in": "fadeIn 200ms ease-out",
        "slide-up": "slideUp 240ms cubic-bezier(0.16, 1, 0.3, 1)",
        "pulse-soft": "pulseSoft 1.5s ease-in-out infinite",
      },
      keyframes: {
        fadeIn: {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        slideUp: {
          from: { opacity: "0", transform: "translateY(12px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        pulseSoft: {
          "0%, 100%": { opacity: "0.6" },
          "50%": { opacity: "1" },
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
