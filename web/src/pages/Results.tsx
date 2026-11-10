import { useRef, type KeyboardEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { STATUS_WORDS, useExperiments, type ExperimentInfo } from "@/lib/experiments";
import { bestRun, METRIC_BY_KEY, usePriority } from "@/lib/metrics";

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
  const main = METRIC_BY_KEY.get(order[0] ?? "");
  const second = METRIC_BY_KEY.get(order[1] ?? "");
  const best = (metric: typeof main) => {
    const run = metric ? bestRun(runs, metric) : undefined;
    const value = run && metric ? metric.value(run) : undefined;
    return run && metric && value !== undefined ? (
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
      <td className="py-3 pr-4 tabular-nums">{best(main)}</td>
      <td className="py-3 tabular-nums">{second ? best(second) : null}</td>
    </tr>
  );
}

export default function Results() {
  const experiments = useExperiments();
  const navigate = useNavigate();
  const order = usePriority((s) => s.order);
  const body = useRef<HTMLTableSectionElement>(null);
  const mainLabel = METRIC_BY_KEY.get(order[0] ?? "")?.label ?? "Best";
  const secondLabel = METRIC_BY_KEY.get(order[1] ?? "")?.label;

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
        hint="One row per experiment; open one to see every model variant compared in it. The two Best columns follow your metrics in Settings. Keyboard: Up and Down move between experiments, Enter opens the one you are on."
      />
      {experiments.isPending ? (
        <div aria-busy="true" aria-label="Loading experiments">
          <Skeleton className="h-10 w-full max-w-3xl" />
        </div>
      ) : experiments.isError ? (
        <p className="text-sm">The experiments could not be loaded: {experiments.error.message}</p>
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
              className="w-full min-w-[44rem] max-w-5xl text-left text-sm"
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
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Best {mainLabel}
                  </th>
                  <th scope="col" className="py-2 font-medium">
                    {secondLabel ? `Best ${secondLabel}` : ""}
                  </th>
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
  );
}
