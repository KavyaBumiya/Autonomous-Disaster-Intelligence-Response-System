/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      colors: {
        ink: "#07111f",
        panel: "#0c1727",
        line: "#203047",
        cyan: "#39d9ff",
        amber: "#ffbd5a",
        danger: "#ff5c69",
        success: "#35d39a",
      },
      boxShadow: {
        glow: "0 0 28px rgba(57,217,255,.12)",
      },
    },
  },
  plugins: [],
};