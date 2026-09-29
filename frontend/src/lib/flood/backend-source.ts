import { io, type Socket } from "socket.io-client";
import type { FloodReading } from "./types";
import { API_BASE, SOCKET_BASE } from "../config";

export class BackendDataSource {
  private socket: Socket | null = null;
  private handler: ((reading: FloodReading) => void) | null = null;

  subscribe(handler: (reading: FloodReading) => void): () => void {
    this.handler = handler;
    const target = SOCKET_BASE || API_BASE || undefined;
    this.socket = io(target, {
      path: "/socket.io",
      transports: ["websocket", "polling"],
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionAttempts: 10,
      timeout: 8000,
    });

    this.socket.on("flood_reading", (data: FloodReading) => {
      this.handler?.(data);
    });

    return () => {
      this.socket?.disconnect();
      this.socket = null;
      this.handler = null;
    };
  }

  disconnect(): void {
    this.socket?.disconnect();
    this.socket = null;
  }
}
