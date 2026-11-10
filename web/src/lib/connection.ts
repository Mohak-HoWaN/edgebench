import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { toast } from "sonner";
import { create } from "zustand";
import { healthKey } from "./api";
import { datasetsKey } from "./datasets";
import { devicesKey } from "./devices";
import { experimentsKey } from "./experiments";
import { modelsKey } from "./models";
import { runsKey } from "./runs";

export type LiveStatus = "connecting" | "live" | "offline";

export const useLiveStatus = create<{ status: LiveStatus }>(() => ({ status: "connecting" }));

const MAX_BACKOFF_MS = 15_000;

/**
 * Keeps one WebSocket to /ws/events open for the lifetime of the shell and reconnects with backoff.
 *
 * All state lives inside the effect run, never in refs shared between runs: React runs effects twice in development, and a
 * shared "cancelled" flag would let the second run leave an orphan socket behind.
 */
export function useLiveEvents(): void {
  const queryClient = useQueryClient();
  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;
    let timer: number | undefined;
    let attempt = 0;
    let wasLive = false;

    const connect = () => {
      if (cancelled) return;
      useLiveStatus.setState({ status: "connecting" });
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${scheme}://${window.location.host}/ws/events`);
      socket = ws;
      ws.onopen = () => {
        if (cancelled) {
          ws.close();
          return;
        }
        if (attempt > 0 && wasLive) toast.success("Live updates are back");
        attempt = 0;
        wasLive = true;
        useLiveStatus.setState({ status: "live" });
      };
      ws.onmessage = (message: MessageEvent<string>) => {
        const type = (JSON.parse(message.data) as { type?: string }).type ?? "";
        // A job changed state: the queue counts on the dashboard are stale.
        if (type.startsWith("job.") || type === "queue.recovered") {
          void queryClient.invalidateQueries({ queryKey: healthKey });
        }
        // A model or one cell of its conversion matrix changed: refresh the list, the detail page and the logs.
        if (type === "model.updated" || type === "variant.updated") {
          void queryClient.invalidateQueries({ queryKey: modelsKey });
          void queryClient.invalidateQueries({ queryKey: ["variant-log"] });
        }
        if (type === "dataset.updated")
          void queryClient.invalidateQueries({ queryKey: datasetsKey });
        if (type === "device.updated") void queryClient.invalidateQueries({ queryKey: devicesKey });
        // A run changed, or an agent reported progress, or a job was recovered as lost: refresh the run views.
        if (type === "run.updated" || type === "job.progress" || type === "queue.recovered") {
          void queryClient.invalidateQueries({ queryKey: runsKey });
          void queryClient.invalidateQueries({ queryKey: experimentsKey });
          void queryClient.invalidateQueries({ queryKey: devicesKey });
        }
      };
      ws.onclose = () => {
        if (cancelled) return;
        if (wasLive && attempt === 0) toast.warning("Live updates lost. Reconnecting.");
        useLiveStatus.setState({ status: "offline" });
        attempt += 1;
        timer = window.setTimeout(connect, Math.min(1000 * 2 ** attempt, MAX_BACKOFF_MS));
      };
    };

    connect();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      socket?.close();
    };
  }, [queryClient]);
}
