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
  server: {
    host: "0.0.0.0",
    port: 3000,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/socket.io": { target: "http://localhost:8000", ws: true, changeOrigin: true },
      "/media": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
