/**
 * AEGIS-AI — Route store (Phase 15)
 * Shares the latest computed route (from RouteIntelligence) with the
 * OperationalMap's additive route layer.
 */
import { create } from "zustand";
import type { RoutesResult } from "@/services/api";

interface RouteStore {
  route: RoutesResult | null;
  setRoute: (route: RoutesResult | null) => void;
}

export const useRouteStore = create<RouteStore>((set) => ({
  route: null,
  setRoute: (route) => set({ route }),
}));
