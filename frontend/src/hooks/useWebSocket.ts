import { useEffect, useRef, useState } from "react";

export interface Socket {
  emit: (event: string, data: unknown) => void;
  on: (event: string, callback: (data: never) => void) => void;
  disconnect: () => void;
}

interface SocketIoClient {
  (url?: string, opts?: Record<string, unknown>): Socket;
}

function getIo(): SocketIoClient | null {
  if (typeof window === "undefined") return null;
  const io = (window as unknown as { io?: SocketIoClient }).io;
  return typeof io === "function" ? io : null;
}

/**
 * WebSocket hook for AegisAI Dashboard.
 * Connects to the Socket.IO server and tracks connection status.
 *
 * Socket instance lives in a ref (not render state). Connection status
 * updates only from socket event callbacks — never synchronously in the effect body.
 */
export function useWebSocket() {
  const ioAvailable = getIo() !== null;
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(ioAvailable);
  const socketRef = useRef<Socket | null>(null);

  useEffect(() => {
    const io = getIo();
    if (!io) {
      return;
    }

    const instance = io(import.meta.env.VITE_WS_URL, {
      transports: ["websocket"],
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
    });

    socketRef.current = instance;

    instance.on("connect" as never, (() => {
      setConnected(true);
      setConnecting(false);
      instance.emit("subscribe", { room: "global_feed" });
    }) as never);

    instance.on("disconnect" as never, (() => {
      setConnected(false);
      setConnecting(false);
    }) as never);

    instance.on("connect_error" as never, ((error: unknown) => {
      setConnecting(false);
      console.error("WebSocket connect_error:", error);
    }) as never);

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
