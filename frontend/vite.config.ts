import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dashboard talks to the backend at :8000. In dev we proxy /api, /ws and
// /ingest so the frontend can use same-origin paths.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/ingest": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
