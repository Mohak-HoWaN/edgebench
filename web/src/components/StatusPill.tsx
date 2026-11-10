import { useHealth } from "@/lib/api";
import { useLiveStatus } from "@/lib/connection";
import { cn } from "@/lib/utils";

type Tone = "ok" | "warn" | "bad";

const DOT: Record<Tone, string> = { ok: "bg-ok", warn: "bg-warn", bad: "bg-destructive" };

/** Connection state in words plus a dot, so it never relies on colour alone. */
export function useConnectionState(): { tone: Tone; label: string } {
  const health = useHealth();
  const live = useLiveStatus((s) => s.status);
  if (health.isError) return { tone: "bad", label: "Server unreachable" };
  if (health.isPending) return { tone: "warn", label: "Connecting" };
  if (health.data.status === "degraded") return { tone: "warn", label: "Server degraded" };
  if (live !== "live") return { tone: "warn", label: "Reconnecting live updates" };
  return { tone: "ok", label: "Connected" };
}

export function StatusPill({ className }: { className?: string }) {
  const { tone, label } = useConnectionState();
  return (
    <p
      className={cn("flex items-center gap-2 text-xs text-muted-foreground", className)}
      role="status"
    >
      <span aria-hidden className={cn("size-2 rounded-full", DOT[tone])} />
      {label}
    </p>
  );
}
