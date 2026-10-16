import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["selector", '[data-theme="dark"]'],
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-inter)", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "Liberation Mono", "monospace"],
      },
      colors: {
        bg: "hsl(var(--bg) / <alpha-value>)",
        surface: {
          DEFAULT: "hsl(var(--surface) / <alpha-value>)",
          2: "hsl(var(--surface-2) / <alpha-value>)",
          3: "hsl(var(--surface-3) / <alpha-value>)",
        },
        border: {
          DEFAULT: "hsl(var(--border) / <alpha-value>)",
          strong: "hsl(var(--border-strong) / <alpha-value>)",
        },
        fg: {
          DEFAULT: "hsl(var(--fg) / <alpha-value>)",
          muted: "hsl(var(--fg-muted) / <alpha-value>)",
          subtle: "hsl(var(--fg-subtle) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "hsl(var(--accent) / <alpha-value>)",
          fg: "hsl(var(--accent-fg) / <alpha-value>)",
          2: "hsl(var(--accent-2) / <alpha-value>)",
        },
        success: "hsl(var(--success) / <alpha-value>)",
        warning: "hsl(var(--warning) / <alpha-value>)",
        danger: "hsl(var(--danger) / <alpha-value>)",
        info: "hsl(var(--info) / <alpha-value>)",
        ring: "hsl(var(--ring) / <alpha-value>)",
      },
      borderRadius: {
        sm: "6px",
        DEFAULT: "8px",
        md: "8px",
        lg: "12px",
        xl: "16px",
        "2xl": "20px",
      },
      boxShadow: {
        soft: "0 1px 2px 0 rgb(0 0 0 / 0.06), 0 4px 16px -4px rgb(0 0 0 / 0.08)",
        pop: "0 8px 32px -8px rgb(0 0 0 / 0.35), 0 1px 0 0 rgb(255 255 255 / 0.04) inset",
        glow: "0 0 0 1px hsl(var(--accent) / 0.35), 0 8px 24px -8px hsl(var(--accent) / 0.45)",
      },
      keyframes: {
        shimmer: { "0%": { backgroundPosition: "-200% 0" }, "100%": { backgroundPosition: "200% 0" } },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "slide-up": { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        "slide-in-right": { from: { transform: "translateX(100%)" }, to: { transform: "translateX(0)" } },
        "slide-in-left": { from: { transform: "translateX(-100%)" }, to: { transform: "translateX(0)" } },
        "zoom-in": { from: { opacity: "0", transform: "scale(0.97)" }, to: { opacity: "1", transform: "scale(1)" } },
      },
      animation: {
        shimmer: "shimmer 1.6s linear infinite",
        "fade-in": "fade-in 160ms ease-out",
        "slide-up": "slide-up 220ms cubic-bezier(0.2, 0.8, 0.2, 1)",
        "slide-in-right": "slide-in-right 240ms cubic-bezier(0.2, 0.8, 0.2, 1)",
        "slide-in-left": "slide-in-left 240ms cubic-bezier(0.2, 0.8, 0.2, 1)",
        "zoom-in": "zoom-in 180ms cubic-bezier(0.2, 0.8, 0.2, 1)",
      },
    },
  },
  plugins: [],
};

export default config;
