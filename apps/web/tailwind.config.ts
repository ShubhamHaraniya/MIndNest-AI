import type { Config } from "tailwindcss";

// Colours come from CSS variables in globals.css (a light and a dark set), so the whole app
// shares one set of design tokens and a theme change needs no per-component work.
// Tailwind's "/60" opacity modifiers need a colour it can rewrite. The tokens are CSS variables, so
// the alpha is mixed in by the browser instead: bg-danger/60 is the danger colour at 60%.
const token = (name: string) => `color-mix(in srgb, var(${name}) calc(<alpha-value> * 100%), transparent)`;

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: token("--bg"),
        surface: { DEFAULT: token("--surface"), 2: token("--surface-2"), 3: token("--surface-3") },
        ink: token("--text"),
        muted: token("--text-muted"),
        faint: token("--text-faint"),
        border: { DEFAULT: token("--border"), strong: token("--border-strong") },
        primary: {
          DEFAULT: token("--primary"),
          hover: token("--primary-hover"),
          soft: token("--primary-soft"),
        },
        brand: token("--brand"),
        "on-primary": token("--on-primary"),
        accent: { DEFAULT: token("--accent"), soft: token("--accent-soft") },
        success: { DEFAULT: token("--success"), soft: token("--success-soft") },
        warning: { DEFAULT: token("--warning"), soft: token("--warning-soft") },
        danger: { DEFAULT: token("--danger"), soft: token("--danger-soft") },
        info: { DEFAULT: token("--info"), soft: token("--info-soft") },
      },
      // Soft and friendly: controls 8-10px, cards 14px. Legacy rounded-* classes map onto this scale.
      borderRadius: {
        none: "0",
        sm: "6px",
        DEFAULT: "8px",
        md: "8px",
        lg: "10px",
        xl: "12px",
        "2xl": "16px",
        "3xl": "20px",
        card: "var(--radius-card)",
        control: "var(--radius-control)",
      },
      boxShadow: {
        card: "var(--shadow-card)",
        pop: "var(--shadow-pop)",
        glow: "var(--shadow-glow)",
      },
      keyframes: {
        shimmer: { "100%": { transform: "translateX(100%)" } },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "slide-up": { from: { opacity: "0", transform: "translateY(10px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        "pop-in": { from: { opacity: "0", transform: "scale(0.96) translateY(-4px)" }, to: { opacity: "1", transform: "scale(1) translateY(0)" } },
        "toast-in": { from: { opacity: "0", transform: "translateY(12px) scale(0.97)" }, to: { opacity: "1", transform: "translateY(0) scale(1)" } },
        float: { "0%,100%": { transform: "translateY(0)" }, "50%": { transform: "translateY(-8px)" } },
        "glow-pulse": { "0%,100%": { opacity: "0.55" }, "50%": { opacity: "1" } },
      },
      animation: {
        "fade-in": "fade-in 0.3s ease-out both",
        "slide-up": "slide-up 0.45s cubic-bezier(0.22, 1, 0.36, 1) both",
        "pop-in": "pop-in 0.18s cubic-bezier(0.22, 1, 0.36, 1) both",
        "toast-in": "toast-in 0.3s cubic-bezier(0.22, 1, 0.36, 1) both",
        float: "float 6s ease-in-out infinite",
        "glow-pulse": "glow-pulse 3.2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
