import type { Config } from "tailwindcss";

// Design tokens ported 1:1 from demo/admin.html :root custom properties.
// See design-spec.md for the full rationale. Do not hardcode hex values in
// components — always reference these tokens so the admin panel and the
// miniapp stay visually consistent (same backend, same brand).
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#F3FBFF",
        surface: "#FFFFFF",
        "surface-2": "#EDF3F8",
        border: {
          DEFAULT: "#D8E6F0",
          2: "#C7DAEA",
        },
        text: {
          DEFAULT: "#14324A",
          2: "#4E6B81",
          3: "#7C95A8",
        },
        accent: {
          DEFAULT: "#195079",
          2: "#124063",
          soft: "rgba(25,80,121,.09)",
          line: "rgba(25,80,121,.28)",
        },
        "on-accent": "#FFFFFF",
        success: {
          DEFAULT: "#1E9E6A",
          soft: "rgba(30,158,106,.10)",
          line: "rgba(30,158,106,.24)",
        },
        warning: {
          DEFAULT: "#D99021",
          soft: "rgba(217,144,33,.10)",
          line: "rgba(217,144,33,.28)",
          text: "#9a6200",
        },
        danger: {
          DEFAULT: "#C2413C",
          soft: "rgba(194,65,60,.10)",
          line: "rgba(194,65,60,.28)",
        },
      },
      borderRadius: {
        sm: "8px",
        DEFAULT: "12px",
        lg: "16px",
        xl: "22px",
      },
      boxShadow: {
        DEFAULT: "0 8px 24px -12px rgba(20,50,74,.18)",
        lg: "0 16px 40px -16px rgba(20,50,74,.22)",
        menu: "0 16px 40px -12px rgba(20,50,74,.14)",
      },
      fontFamily: {
        head: [
          "Jost",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "sans-serif",
        ],
        body: [
          "Roboto",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "sans-serif",
        ],
        mono: [
          "Roboto Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Cascadia Code",
          "Menlo",
          "monospace",
        ],
      },
      transitionTimingFunction: {
        brand: "cubic-bezier(.16,1,.3,1)",
      },
      spacing: {
        sidebar: "264px",
        topbar: "64px",
      },
      maxWidth: {
        screen: "1320px",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "none" },
        },
        "pulse-node": {
          "0%": { transform: "scale(1)", opacity: ".5" },
          "70%": { transform: "scale(2.8)", opacity: "0" },
          "100%": { transform: "scale(2.8)", opacity: "0" },
        },
        "pulse-live": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: ".4" },
        },
      },
      animation: {
        "fade-in": "fade-in 200ms cubic-bezier(.16,1,.3,1)",
        "pulse-node": "pulse-node 3s cubic-bezier(.16,1,.3,1) infinite",
        "pulse-live": "pulse-live 2.4s cubic-bezier(.16,1,.3,1) infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
