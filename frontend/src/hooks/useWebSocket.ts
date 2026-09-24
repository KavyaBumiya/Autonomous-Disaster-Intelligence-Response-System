import { useEffect, useRef, useState } from "react";
import { io, type Socket } from "socket.io-client";

/**
 * WebSocket hook for AegisAI Dashboard.
 * Connects to the backend Socket.IO server (proxied via Vite/nginx) and tracks connection status.
 *
 * Socket instance lives in a ref (not render state). Connection status
 * updates only from socket event callbacks — never synchronously in the effect body.
 */
export function useWebSocket() {
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(true);
  const socketRef = useRef<Socket | null>(null);

  useEffect(() => {
    const instance = io(import.meta.env.VITE_WS_URL || "/", {
      transports: ["websocket", "polling"],
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
    });

    socketRef.current = instance;

    instance.on("connect", () => {
      setConnected(true);
      setConnecting(false);
      instance.emit("subscribe", { room: "global_feed" });
    });

    instance.on("disconnect", () => {
      setConnected(false);
      setConnecting(false);
    });

    instance.on("connect_error", (error: unknown) => {
      setConnecting(false);
      console.error("WebSocket connect_error:", error);
    });

    return () => {
      instance.disconnect();
      socketRef.current = null;
      setConnected(false);
      setConnecting(false);
    };
  }, []);

  return {
    connected,
    connecting,
    /** Access only from event handlers / effects — not during render. */
    getSocket: () => socketRef.current,
  };
}
