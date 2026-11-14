import { Link } from "react-router-dom";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader, Section } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useHealth } from "@/lib/api";
import { useDriftLimits } from "@/lib/drift";
import { formatDuration } from "@/lib/format";
import { highlights } from "@/lib/highlights";
import { useRuns } from "@/lib/runs";

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

function Highlights() {
  const runs = useRuns();
  const band = useDriftLimits((s) => s.maxMapDropPoints);
  const found = highlights(runs.data ?? [], band);
  if (found.length === 0)
    return (
      <EmptyState
        title="Nothing to highlight yet"
        action={{ label: "Plan an experiment", to: "/experiments/new" }}
      >
        Once two or more runs have finished on the same dataset version and device, the fastest one
        that is still accurate enough is shown here, with the rule it was picked by.
      </EmptyState>
    );
  return (
    <ul className="max-w-prose space-y-4" aria-label="Highlights">
      {found.map((h) => (
        <li key={h.place}>
          <p className="text-sm font-medium">{h.sentence}</p>
          <p className="text-xs text-muted-foreground">
            {h.rule}{" "}
            <Link
              to={`/compare?runs=${h.compare.join(",")}&ref=${String(h.best.id)}`}
              className="text-primary underline underline-offset-4"
            >
              Compare them
            </Link>
          </p>
        </li>
      ))}
    </ul>
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
      <Section
        title="Highlights"
        hint="Computed from your runs, with the rule shown. The allowed accuracy drop is the one in Settings."
      >
        <Highlights />
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
