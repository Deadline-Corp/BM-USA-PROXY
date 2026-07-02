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
        "surface-2": "#EDF3F8",
        border: {
          DEFAULT: "#D8E6F0",
          2: "#C4D9E9",
        },
        text: {
          DEFAULT: "#14324A",
          2: "#4E6B81",
          3: "#7C95A8",
        },
        accent: {
          DEFAULT: "#195079",
          2: "#124063",
        },
        "on-accent": "#FFFFFF",
        success: "#1E9E6A",
        warning: "#D99021",
        danger: "#C2413C",
      },
      borderRadius: {
        sm: "8px",
        DEFAULT: "12px",
        lg: "16px",
        xl: "22px",
      },
      boxShadow: {
        DEFAULT: "0 8px 24px -12px rgba(20,50,74,.18)",
        soft: "0 4px 16px -8px rgba(20,50,74,.12)",
        card: "0 4px 16px -8px rgba(20,50,74,.14)",
        highlight: "0 16px 40px -22px rgba(20,50,74,.14)",
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
        mono: ["Roboto Mono", "ui-monospace", "SF Mono", "Consolas", "monospace"],
      },
      transitionTimingFunction: {
        ease: "cubic-bezier(.16,1,.3,1)",
      },
      backgroundImage: {
        app: `radial-gradient(1100px 700px at 18% -8%, rgba(25,80,121,.06), transparent 60%),
              radial-gradient(900px 600px at 110% 10%, rgba(194,65,60,.04), transparent 55%),
              linear-gradient(160deg, #EAF4FB 0%, #F3FBFF 100%)`,
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
