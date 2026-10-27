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
          primary: "#0b0e14",
          secondary: "#141b2d",
          tertiary: "#111726",
          elevated: "#0f1524",
        },
        // Border colors
        border: {
          DEFAULT: "#263048",
          secondary: "#33405c",
        },
        // Text colors
        text: {
          primary: "#e8edf5",
          secondary: "#8b96ad",
          tertiary: "#cfe3ff",
          link: "#7db4ff",
        },
        // Accent colors
        accent: {
          blue: "#2563eb",
          green: "#22c55e",
          red: "#ef4444",
          amber: "#f59e0b",
          cyan: "#38bdf8",
          "red-dark": "#7f1d1d",
          "cyan-dark": "#0891b2",
        },
      },
      spacing: {
        // Custom spacing scale
        4.5: "1.125rem",
        18: "4.5rem",
      },
      borderRadius: {
        card: "10px",
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
