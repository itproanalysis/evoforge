import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Background colors
        background: {
          primary: "rgb(var(--surface-base) / <alpha-value>)",
          secondary: "rgb(var(--surface-panel) / <alpha-value>)",
          tertiary: "rgb(var(--surface-muted) / <alpha-value>)",
          elevated: "rgb(var(--surface-raised) / <alpha-value>)",
        },
        // Border colors
        border: {
          DEFAULT: "rgb(var(--line) / <alpha-value>)",
          secondary: "rgb(var(--line-strong) / <alpha-value>)",
        },
        // Text colors
        text: {
          primary: "rgb(var(--ink) / <alpha-value>)",
          secondary: "rgb(var(--ink-muted) / <alpha-value>)",
          tertiary: "rgb(var(--ink-soft) / <alpha-value>)",
          link: "rgb(var(--accent-action) / <alpha-value>)",
        },
        // Accent colors
        accent: {
          blue: "rgb(var(--accent-action) / <alpha-value>)",
          green: "rgb(var(--accent-success) / <alpha-value>)",
          red: "rgb(var(--accent-error) / <alpha-value>)",
          amber: "rgb(var(--accent-warning) / <alpha-value>)",
          cyan: "rgb(var(--accent-info) / <alpha-value>)",
          "red-dark": "rgb(var(--accent-error-deep) / <alpha-value>)",
          "cyan-dark": "rgb(var(--accent-info-deep) / <alpha-value>)",
        },
      },
      spacing: {
        // Custom spacing scale
        4.5: "1.125rem",
        18: "4.5rem",
      },
      borderRadius: {
        card: "16px",
        badge: "20px",
      },
      fontSize: {
        xs: ["0.75rem", { lineHeight: "1rem" }],
        sm: ["0.8125rem", { lineHeight: "1.25rem" }],
        base: ["0.875rem", { lineHeight: "1.5rem" }],
        lg: ["1rem", { lineHeight: "1.5rem" }],
        xl: ["1.125rem", { lineHeight: "1.75rem" }],
        "2xl": ["1.375rem", { lineHeight: "2rem" }],
      },
      fontWeight: {
        normal: "400",
        medium: "500",
        semibold: "600",
        bold: "700",
        extrabold: "800",
      },
    },
  },
  plugins: [],
};

export default config;
