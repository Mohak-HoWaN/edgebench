import { useRef, type KeyboardEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { RunExplorer } from "@/components/RunExplorer";
import { useRuns } from "@/lib/runs";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { STATUS_WORDS, useExperiments, type ExperimentInfo } from "@/lib/experiments";
import { bestRun, priorityMetrics, usePriority, type Metric } from "@/lib/metrics";

/** How many of the person's metrics get a column on this page (the experiment page shows all of them). */
const COLUMNS = 3;

const when = (iso: string) => new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });

function progressText(e: ExperimentInfo): string {
  const total = Object.values(e.counts).reduce((a, b) => a + b, 0);
  const done = e.counts.done ?? 0;
  if (e.status === "running") return `${String(done)} of ${String(total)} finished, running`;
  return `${String(done)} of ${String(total)} finished`;
}

function Row({ e, onOpen }: { e: ExperimentInfo; onOpen: () => void }) {
  const order = usePriority((s) => s.order);
  const runs = e.runs ?? [];
  const shown = priorityMetrics(order).slice(0, COLUMNS);
  const best = (metric: Metric) => {
    const run = bestRun(runs, metric, shown);
    const value = run ? metric.value(run) : undefined;
    return run && value !== undefined ? (
      <>
        {metric.format(value)}
        <span className="block text-xs text-muted-foreground">
          {run.model_name}, {run.variant_label}
        </span>
      </>
    ) : (
      <span className="text-muted-foreground">n/a</span>
    );
  };
  return (
    <tr
      className="cursor-pointer border-b align-top hover:bg-accent/40"
      onClick={(ev) => {
        if (!(ev.target as HTMLElement).closest("a")) onOpen();
      }}
    >
      <th scope="row" className="py-3 pr-4 text-left font-normal">
        <Link
          to={`/experiments/${String(e.id)}`}
          data-row-link
          className="font-medium text-primary underline-offset-4 hover:underline"
        >
          {e.name}
        </Link>
        <span className="block text-xs text-muted-foreground">
          {STATUS_WORDS[e.status]}, {progressText(e)}
        </span>
      </th>
      <td className="py-3 pr-4">
        {e.dataset_name ?? "removed"}
        {e.dataset_version ? (
          <span className="block text-xs text-muted-foreground">version {e.dataset_version}</span>
        ) : null}
      </td>
      <td className="py-3 pr-4">
        {e.device_name ?? "removed"}
        <span className="block text-xs text-muted-foreground">{when(e.created_at)}</span>
      </td>
      {shown.map((m) => (
        <td key={m.key} className="py-3 pr-4 tabular-nums">
          {best(m)}
        </td>
      ))}
    </tr>
  );
}

export default function Results() {
  const experiments = useExperiments();
  const [params, setParams] = useSearchParams();
  const tab = params.get("view") === "runs" ? "runs" : "experiments";
  const allRuns = useRuns();
  const navigate = useNavigate();
  const order = usePriority((s) => s.order);
  const body = useRef<HTMLTableSectionElement>(null);
  const shown = priorityMetrics(order).slice(0, COLUMNS);

  // Up and Down move between experiments, Enter opens the one in focus (the link in each row does the rest).
  const onKeyDown = (ev: KeyboardEvent) => {
    if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp") return;
    const links = [...(body.current?.querySelectorAll<HTMLElement>("a[data-row-link]") ?? [])];
    const at = links.indexOf(document.activeElement as HTMLElement);
    const next =
      links[at + (ev.key === "ArrowDown" ? 1 : -1)] ?? (at === -1 ? links[0] : undefined);
    if (next) {
      ev.preventDefault();
      next.focus();
    }
  };

  return (
    <>
      <PageHeader
        title="Results"
        hint="Experiments: one row each; open one to see every model variant compared in it. The Best columns are your first three metrics from Settings, in that order. Keyboard: Up and Down move between experiments, Enter opens the one you are on. All runs: every run in one table to search, sort, group, save as a view, tick and compare, or take as CSV."
      />
      <div role="tablist" aria-label="Results views" className="mb-4 flex gap-1 border-b">
        {(["experiments", "runs"] as const).map((v) => (
          <button
            key={v}
            role="tab"
            type="button"
            aria-selected={tab === v}
            onClick={() => {
              setParams(v === "runs" ? { view: "runs" } : {}, { replace: true });
            }}
            className={`border-b-2 px-3 py-2 text-sm ${tab === v ? "border-primary font-medium" : "border-transparent text-muted-foreground hover:text-foreground"}`}
          >
            {v === "experiments" ? "Experiments" : "All runs"}
          </button>
        ))}
      </div>
      {tab === "runs" ? (
        allRuns.isPending ? (
          <Skeleton aria-busy="true" aria-label="Loading runs" className="h-10 w-full max-w-3xl" />
        ) : allRuns.isError ? (
          <p className="text-sm">The runs could not be loaded: {allRuns.error.message}</p>
        ) : (
          <RunExplorer runs={allRuns.data} />
        )
      ) : null}
      {tab === "runs" ? null : (
        <>
          {experiments.isPending ? (
            <div aria-busy="true" aria-label="Loading experiments">
              <Skeleton className="h-10 w-full max-w-3xl" />
            </div>
          ) : experiments.isError ? (
            <p className="text-sm">
              The experiments could not be loaded: {experiments.error.message}
            </p>
          ) : experiments.data.length === 0 ? (
            <EmptyState
              title="No results yet"
              action={{ label: "Plan an experiment", to: "/experiments/new" }}
            >
              An experiment compares model variants on a dataset and shows up here as one row.
            </EmptyState>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table
                  className="w-full min-w-[52rem] max-w-6xl text-left text-sm"
                  onKeyDown={onKeyDown}
                >
                  <caption className="sr-only">Experiments, newest first</caption>
                  <thead>
                    <tr className="border-b">
                      <th scope="col" className="py-2 pr-4 font-medium">
                        Experiment
                      </th>
                      <th scope="col" className="py-2 pr-4 font-medium">
                        Dataset
                      </th>
                      <th scope="col" className="py-2 pr-4 font-medium">
                        Device and date
                      </th>
                      {shown.map((m) => (
                        <th key={m.key} scope="col" className="py-2 pr-4 font-medium">
                          Best {m.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody ref={body}>
                    {experiments.data.map((e) => (
                      <Row
                        key={e.id}
                        e={e}
                        onOpen={() => {
                          void navigate(`/experiments/${String(e.id)}`);
                        }}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </>
  );
}
