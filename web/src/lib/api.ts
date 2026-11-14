import { useQuery } from "@tanstack/react-query";
import { SIGNED_OUT } from "@/lib/models";

/** Shape of GET /api/health (server/edgebench/api.py). */
export interface Health {
  status: "ok" | "degraded";
  version: string;
  uptime_seconds: number;
  db: { ok: boolean; journal_mode: string | null; error: string | null };
  queue: Record<string, number>;
  worker_running: boolean;
  disk_free_gb: number;
}

export async function getHealth(signal?: AbortSignal): Promise<Health> {
  const res = await fetch("/api/health", { signal });
  if (res.status === 401) window.dispatchEvent(new Event(SIGNED_OUT));
  if (!res.ok) throw new Error(`The server answered ${String(res.status)}`);
  return (await res.json()) as Health;
}

export const healthKey = ["health"] as const;

export function useHealth() {
  return useQuery({
    queryKey: healthKey,
    queryFn: ({ signal }) => getHealth(signal),
    refetchInterval: 5000,
    retry: 1,
  });
}
