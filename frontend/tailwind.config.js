/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Semantic status palette — color carries meaning, not decoration.
        ink: { 900: "#0E1116", 800: "#141922", 700: "#1A2029", 600: "#212936" },
        line: "#2A3340",
        fg: { DEFAULT: "#E6EAF0", muted: "#8A94A6", faint: "#5B6675" },
        healthy: "#3FB950",
        degrading: "#D29922",
        down: "#F85149",
        recovering: "#58A6FF",
        rescued: "#2DD4BF",
      },
      fontFamily: {
        sans: ["'IBM Plex Sans'", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
