import { useEffect, useState, useRef } from "react";

export interface Socket {
  emit: (event: string, data: any) => void;
  on: (event: string, callback: (data: any) => void) => void;
  disconnect: () => void;
  connecting: boolean;
}

export interface WebSocketState {
  socket: Socket | null;
  connected: boolean;
  connecting: boolean;
}

/**
 * WebSocket hook for AegisAI Dashboard.
 * Connects to the Socket.IO server and handles all Phase 1 event types.
 */
export function useWebSocket() {
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const socketRef = useRef<any>(null);

  useEffect(() => {
    // Don't run on server side
    if (typeof window === "undefined") {
      return;
    }

    setConnecting(true);

    const socket: any = (window as any).io(import.meta.env.VITE_WS_URL, {
      transports: ["websocket"],
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
    });

    socketRef.current = socket;

    socket.on("connect", () => {
      setConnected(true);
      setConnecting(false);
      socket.emit("subscribe", { room: "global_feed" });
    });

    socket.on("disconnect", () => {
      setConnected(false);
      setConnecting(false);
    });

    socket.on("connect_error", (error: string) => {
      setConnecting(false);
      console.error("WebSocket connect error:", error);
    });

    // Handle all Phase 1 event types
    const handleEvent = (event: string, data: any) => {
      // Could be handled by parent component via state updates
      // or just logged for now
      // console.log(`${event}:`, data);
    };

    socket.on("new_report", (data: any) => {
      handleEvent("new_report", data);
    });

    socket.on("trust_score_updated", (data: any) => {
      handleEvent("trust_score_updated", data);
    });

    socket.on("incident_priority_updated", (data: any) => {
      handleEvent("incident_priority_updated", data);
    });

    socket.on("new_incident", (data: any) => {
      handleEvent("new_incident", data);
    });

    socket.on("prediction_updated", (data: any) => {
      handleEvent("prediction_updated", data);
    });

    socket.on("resource_assigned", (data: any) => {
      handleEvent("resource_assigned", data);
    });

    socket.on("route_changed", (data: any) => {
      handleEvent("route_changed", data);
    });

    socket.on("command_interaction", (data: any) => {
      handleEvent("command_interaction", data);
    });

    return () => {
      socket.disconnect();
      socketRef.current = null;
    };
  }, []);

  return {
    connected,
    connecting,
    socket: socketRef.current,
  };
}