import type { Config } from "tailwindcss";

// Design tokens ported 1:1 from demo/miniapp.html :root custom properties.
// Do not hardcode hex values in components — always reference these tokens.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#F3FBFF",
        surface: "#FFFFFF",
        "surface-2": "#EEF1F9",
        border: {
          DEFAULT: "#D9E0F2",
          2: "#C7D0EC",
        },
        // Ink family follows the client's approved mockup: near-black indigo
        // headings, indigo-gray secondary text (hue ~228 across the board).
        text: {
          DEFAULT: "#121B40",
          2: "#4F5C88",
          3: "#7F8AAB",
        },
        // Vivid royal-indigo from the mockup's labels/icons/prices, one notch
        // desaturated per the client's "синий чуть приглушеннее".
        accent: {
          DEFAULT: "#3050C5",
          2: "#2743A9",
        },
        "on-accent": "#FFFFFF",
        success: "#1E9E6A",
        warning: "#D99021",
        danger: "#C2413C",
        // Brand red from bmusproxy.com buttons (#CD3833) — used for the main
        // purchase CTA only; `danger` stays reserved for error semantics.
        red: {
          DEFAULT: "#CD3833",
          2: "#B9312C",
        },
      },
      borderRadius: {
        sm: "10px",
        DEFAULT: "14px",
        lg: "20px",
        xl: "26px",
      },
      boxShadow: {
        DEFAULT: "0 10px 28px -14px rgba(18,27,64,.18)",
        soft: "0 6px 20px -10px rgba(18,27,64,.12)",
        card: "0 6px 20px -10px rgba(18,27,64,.12)",
        highlight: "0 16px 40px -22px rgba(18,27,64,.14)",
        cta: "0 12px 26px -12px rgba(205,56,51,.5)",
      },
      fontFamily: {
        head: [
          "Manrope",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "sans-serif",
        ],
        body: [
          "Manrope",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "sans-serif",
        ],
        mono: ["Roboto Mono", "ui-monospace", "SF Mono", "Consolas", "monospace"],
      },
      transitionTimingFunction: {
        ease: "cubic-bezier(.16,1,.3,1)",
      },
      backgroundImage: {
        app: `radial-gradient(1100px 700px at 18% -8%, rgba(48,80,197,.06), transparent 60%),
              radial-gradient(900px 600px at 110% 10%, rgba(205,56,51,.04), transparent 55%),
              linear-gradient(160deg, #EDF1FB 0%, #F4F8FF 100%)`,
      },
      keyframes: {
        "m-fade": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "none" },
        },
        pulse2: {
          "0%, 100%": { transform: "scale(.7)", opacity: ".45" },
          "50%": { transform: "scale(1.4)", opacity: "1" },
        },
      },
      animation: {
        "m-fade": "m-fade .2s cubic-bezier(.16,1,.3,1)",
        pulse2: "pulse2 1.9s ease-in-out infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
