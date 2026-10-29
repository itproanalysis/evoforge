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
          primary: "#0d1014",
          secondary: "#161b22",
          tertiary: "#11161c",
          elevated: "#131920",
        },
        // Border colors
        border: {
          DEFAULT: "#2a333d",
          secondary: "#3b4755",
        },
        // Text colors
        text: {
          primary: "#edf1f5",
          secondary: "#a0acba",
          tertiary: "#c4cdd7",
          link: "#b8df91",
        },
        // Accent colors
        accent: {
          blue: "#31624f",
          green: "#a9d979",
          red: "#ef4444",
          amber: "#f59e0b",
          cyan: "#9dd9c4",
          "red-dark": "#7f1d1d",
          "cyan-dark": "#356957",
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
