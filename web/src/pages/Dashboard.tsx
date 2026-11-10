import { EmptyState } from "@/components/EmptyState";
import { PageHeader, Section } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useHealth } from "@/lib/api";
import { formatDuration } from "@/lib/format";

function Row({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{term}</dt>
      <dd className="tabular-nums">{children}</dd>
    </>
  );
}

function ServerSection() {
  const health = useHealth();

  if (health.isPending) {
    return (
      <div aria-busy="true" aria-label="Loading server status" className="space-y-2">
        <Skeleton className="h-4 w-64" />
        <Skeleton className="h-4 w-52" />
        <Skeleton className="h-4 w-60" />
      </div>
    );
  }
  if (health.isError) {
    return (
      <div className="max-w-prose text-sm">
        <p>The server did not answer: {health.error.message}.</p>
        <p className="mt-1 text-muted-foreground">Check that it is running, then try again.</p>
        <Button
          size="sm"
          variant="outline"
          className="mt-3"
          onClick={() => {
            void health.refetch();
          }}
        >
          Try again
        </Button>
      </div>
    );
  }

  const h = health.data;
  const q = h.queue;
  const running = (q.running ?? 0) + (q.claimed ?? 0);
  return (
    <dl className="grid max-w-prose grid-cols-[10rem_1fr] gap-y-2 text-sm">
      <Row term="Status">{h.status === "ok" ? "Working" : "Degraded"}</Row>
      <Row term="Version">{h.version}</Row>
      <Row term="Running for">{formatDuration(h.uptime_seconds)}</Row>
      <Row term="Database">
        {h.db.ok
          ? `Ready (${h.db.journal_mode ?? "unknown"} journal)`
          : `Not available: ${h.db.error ?? "unknown error"}`}
      </Row>
      <Row term="Job worker">{h.worker_running ? "Running" : "Stopped"}</Row>
      <Row term="Jobs">
        {q.queued ?? 0} waiting, {running} running, {q.failed ?? 0} failed
      </Row>
      <Row term="Free disk space">{h.disk_free_gb} GB</Row>
    </dl>
  );
}

export default function Dashboard() {
  return (
    <>
      <PageHeader
        title="Dashboard"
        hint="What has run, what is running, and which devices are connected."
      />
      <Section title="Server">
        <ServerSection />
      </Section>
      <Section title="Recent experiments">
        <EmptyState
          title="No experiments yet"
          action={{ label: "Plan an experiment", to: "/experiments/new" }}
        >
          Finished experiments appear here with their fastest and most accurate variants.
        </EmptyState>
      </Section>
      <Section title="Devices">
        <EmptyState title="No devices connected" action={{ label: "See devices", to: "/devices" }}>
          Each computer or Raspberry Pi you connect shows its status and temperature here.
        </EmptyState>
      </Section>
    </>
  );
}
