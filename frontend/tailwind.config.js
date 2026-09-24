/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: "#38d9c4", dark: "#0d9488", danger: "#ff6b6b", warn: "#f3b562" },
        ink: "#e8edf5",
        muted: "#8ea0b8",
        line: "rgba(151, 171, 199, 0.15)",
        panel: "rgba(15, 27, 44, 0.88)",
        "panel-strong": "#102238",
        cyan: { DEFAULT: "#38d9c4" },
        amber: { DEFAULT: "#f3b562" },
        danger: { DEFAULT: "#ff6b6b" },
        surface: { DEFAULT: "#07101c", card: "#102238", border: "#1d3148" },
      },
      fontFamily: { sans: ["Space Grotesk", "system-ui", "sans-serif"], mono: ["DM Mono", "monospace"] },
      borderRadius: { sm: "8px", md: "10px", lg: "12px", xl: "14px" },
      spacing: { 1: "4px", 2: "8px", 3: "12px", 4: "16px", 5: "20px", 6: "24px", 8: "32px", 10: "40px", 12: "48px", 16: "64px" },
      screens: { xl: "1200px", "2xl": "1400px" },
      maxWidth: { shell: "none" },
      gridTemplateColumns: { "kpi": "repeat(4, minmax(0, 1fr))", "dash": "repeat(12, minmax(0, 1fr))" },
    },
  },
  plugins: [],
};
