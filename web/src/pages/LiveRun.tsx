import { Link } from "react-router-dom";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader, Section } from "@/components/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { STATUS_TEXT, useRuns, type RunInfo } from "@/lib/runs";

function Active({ r }: { r: RunInfo }) {
  const percent = r.progress === null ? null : Math.round(r.progress * 100);
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <Link
          to={`/results/${String(r.id)}`}
          className="font-medium text-primary underline-offset-4 hover:underline"
        >
          Run {r.id}: {r.model_name ?? "removed model"}, {r.variant_label}
        </Link>
        {r.experiment_id !== null ? (
          <Link
            to={`/experiments/${String(r.experiment_id)}`}
            className="text-xs text-muted-foreground underline-offset-4 hover:underline"
          >
            its experiment
          </Link>
        ) : null}
      </div>
      <p className="text-sm text-muted-foreground">
        on {r.device_name ?? "a removed device"} with {r.dataset_name ?? "a removed dataset"}
        {r.dataset_version ? ` v${String(r.dataset_version)}` : ""}
      </p>
      {r.status === "running" ? (
        <div className="mt-1">
          <progress
            className="h-2 w-full max-w-md"
            value={r.progress ?? 0}
            max={1}
            aria-label={`Progress of run ${String(r.id)}`}
          />
          <p className="text-xs text-muted-foreground">
            Running{percent === null ? "" : `, ${String(percent)}%`}
            {r.message ? ` (${r.message})` : ""}
          </p>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">{STATUS_TEXT[r.status]}</p>
      )}
    </li>
  );
}

export default function LiveRun() {
  const runs = useRuns();
  const all = runs.data ?? [];
  const active = all
    .filter((r) => r.status === "running" || r.status === "queued")
    .sort((a, b) => (a.status === b.status ? a.id - b.id : a.status === "running" ? -1 : 1));
  const recent = all.filter((r) => r.status !== "running" && r.status !== "queued").slice(0, 5);

  return (
    <>
      <PageHeader
        title="Live run"
        hint="Every run that is running or waiting, on every device, with its progress. A run you start again shows up here at once."
      />
      {runs.isPending ? (
        <Skeleton aria-busy="true" aria-label="Loading runs" className="h-24 max-w-prose" />
      ) : runs.isError ? (
        <p className="text-sm">The runs could not be loaded: {runs.error.message}</p>
      ) : active.length === 0 ? (
        <EmptyState
          title="No run in progress"
          action={{ label: "Plan an experiment", to: "/experiments/new" }}
        >
          Nothing is running or waiting. Start an experiment, or run one again from its results.
        </EmptyState>
      ) : (
        <Section title={`Running and waiting (${String(active.length)})`} id="active">
          <ul
            className="max-w-prose divide-y border-y"
            aria-label="Runs that are running or waiting"
          >
            {active.map((r) => (
              <Active key={r.id} r={r} />
            ))}
          </ul>
        </Section>
      )}
      {recent.length > 0 ? (
        <Section title="Finished lately" id="recent">
          <ul className="max-w-prose divide-y border-y text-sm">
            {recent.map((r) => (
              <li key={r.id} className="flex flex-wrap justify-between gap-2 py-2">
                <Link
                  to={`/results/${String(r.id)}`}
                  className="text-primary underline-offset-4 hover:underline"
                >
                  Run {r.id}: {r.model_name ?? "removed model"}, {r.variant_label}
                </Link>
                <span className="text-muted-foreground">{STATUS_TEXT[r.status]}</span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
    </>
  );
}
