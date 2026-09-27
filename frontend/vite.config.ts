/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": join(__dirname, "src"),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
  server: {
    host: "0.0.0.0",
    port: 3001, // 3000 often taken by Grafana / other local services
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/socket.io": { target: "http://localhost:8000", ws: true, changeOrigin: true },
      "/media": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes("node_modules")) {
            if (id.includes("cesium")) return "cesium";
            if (
              id.includes("react-router") ||
              id.includes("@remix-run") ||
              id.includes("react-router-dom")
            ) {
              return "router";
            }
            if (
              id.includes("@tanstack") ||
              id.includes("use-sync-external-store")
            ) {
              return "query";
            }
            if (id.includes("axios")) return "axios";
            if (id.includes("socket.io-client") || id.includes("engine.io-client") || id.includes("ws")) {
              return "socket";
            }
            if (id.includes("sonner") || id.includes("zustand")) return "ui";
            if (
              id.includes("/react/") ||
              id.includes("/react-dom/") ||
              id.includes("/scheduler/")
            ) {
              return "react";
            }
          }
          return undefined;
        },
      },
    },
    // mapbox-gl is ~1.3 MB minified and loads only with the map components.
    // It cannot be split further usefully; suppress the size warning for that chunk.
    chunkSizeWarningLimit: 1400,
  },
});
