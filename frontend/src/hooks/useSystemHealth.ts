import { useEffect } from "react";
import {
  startSystemHealthPolling,
  useSystemHealthStore,
} from "@/stores/systemHealthStore";

/**
 * Shared system health hook.
 * Starts one poller on first subscriber; exposes service-level status + refresh.
 */
export function useSystemHealth() {
  const health = useSystemHealthStore();

  useEffect(() => {
    startSystemHealthPolling();
  }, []);

  return health;
}
