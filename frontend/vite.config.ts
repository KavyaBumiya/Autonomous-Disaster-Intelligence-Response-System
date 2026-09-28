import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

/**
 * The console is deployed independently of the API, so production builds talk to
 * the backend over CORS using absolute `VITE_API_BASE_URL` / `VITE_SOCKET_URL`
 * values.
 *
 * In local development it is more convenient to keep the frontend on its own
 * origin and let Vite forward both the REST prefix and the Socket.IO handshake
 * to the backend. Leave `VITE_API_BASE_URL` empty to use this proxy; set it to
 * an absolute origin to bypass the proxy entirely.
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const target = env.VITE_DEV_PROXY_TARGET || "http://localhost:8000";
  const useDevProxy = (env.VITE_USE_DEV_PROXY || "").trim().toLowerCase() === "true";

  return {
    plugins: [react()],
    server: {
      port: 5173,
      // No strictPort: Vite may fall back to 5174+ when 5173 is busy. That is
      // safe because the API accepts any loopback origin in development, so an
      // auto-incremented port does not break the Socket.IO handshake.
      proxy: useDevProxy ? {
        "/api": { target, changeOrigin: true },
        // Socket.IO long-polling handshake and upgrade. The browser's Origin is
        // this dev server's origin, which the API validates in development.
        "/socket.io": { target, changeOrigin: true, ws: true },
      } : undefined,
    },
  };
});
