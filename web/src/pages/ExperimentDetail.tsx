import { Loader2 } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { useConfirm } from "@/components/ConfirmProvider";
import { EmptyState } from "@/components/EmptyState";
import { Info } from "@/components/Info";
import { Insights } from "@/components/Insights";
import { PageHeader, Section } from "@/components/PageHeader";
import { PictureInspector } from "@/components/PictureInspector";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  STATUS_WORDS,
  useCancelExperiment,
  useExperiment,
  useRemoveExperiment,
  type ExperimentInfo,
} from "@/lib/experiments";
import { experimentInsights } from "@/lib/insights";
import { bestByMetric, METRICS, priorityMetrics, rankRuns, usePriority } from "@/lib/metrics";
import { STATUS_TEXT, type RunInfo } from "@/lib/runs";
import { cn } from "@/lib/utils";

/** Which metrics the table shows. The same list as Settings: adding or removing here changes it everywhere. */
function MetricChooser() {
  const order = usePriority((s) => s.order);
  const set = usePriority((s) => s.set);
  return (
    <details className="mb-3 text-sm">
      <summary className="cursor-pointer">
        Metrics shown: {String(order.length)} (choose which)
      </summary>
      <div className="mt-2 grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
        {METRICS.map((m) => (
          <label key={m.key} className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={order.includes(m.key)}
              disabled={order.includes(m.key) && order.length === 1}
              onChange={(ev) => {
                set(ev.target.checked ? [...order, m.key] : order.filter((k) => k !== m.key));
              }}
            />
            {m.label}
          </label>
        ))}
      </div>
    </details>
  );
}

/** How many times a variant had been run before this run, so a repeat can be told apart (0 for the first). */
function repeatNumbers(runs: RunInfo[]): Map<number, number> {
  const seen = new Map<string, number>();
  const out = new Map<number, number>();
  for (const r of [...runs].sort((a, b) => a.id - b.id)) {
    const key = `${String(r.model_id)}|${String(r.variant_id)}`;
    const n = seen.get(key) ?? 0;
    out.set(r.id, n);
    seen.set(key, n + 1);
  }
  return out;
}

function RunsTable({ e }: { e: ExperimentInfo }) {
  const order = usePriority((s) => s.order);
  const metrics = priorityMetrics(order);
  const runs = e.runs ?? [];
  const done = runs.filter((r) => r.status === "done");
  const ranked = [
    ...rankRuns(done, metrics),
    ...runs.filter((r) => r.status !== "done").sort((a, b) => a.id - b.id),
  ];
  const best = bestByMetric(done, metrics);
  const repeats = repeatNumbers(runs);
  const first = metrics[0];

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_19rem]">
      <div>
        <MetricChooser />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[34rem] text-left text-sm">
            <caption className="sr-only">
              Runs of this experiment, best first by {first?.label ?? "run number"}
            </caption>
            <thead>
              <tr className="border-b">
                <th scope="col" className="py-2 pr-3 font-medium">
                  Model and variant
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  State
                </th>
                {metrics.map((m, i) => (
                  <th key={m.key} scope="col" className="py-2 pr-3 text-right font-medium">
                    <span className="inline-flex items-center justify-end gap-1">
                      {m.short}
                      <Info>{`${m.label}: ${m.hint} ${m.higher ? "Higher is better." : "Lower is better."}`}</Info>
                    </span>
                    {i === 0 ? (
                      <span className="block text-xs font-normal text-muted-foreground">
                        ranked by
                      </span>
                    ) : null}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ranked.map((r) => {
                const again = repeats.get(r.id) ?? 0;
                return (
                  <tr key={r.id} className={cn("border-b align-top", again > 0 && "bg-primary/10")}>
                    <th scope="row" className="py-2 pr-3 text-left font-normal">
                      <Link
                        to={`/results/${String(r.id)}`}
                        className="font-medium text-primary underline-offset-4 hover:underline"
                      >
                        {r.model_name ?? "removed model"}
                      </Link>
                      <span className="block text-xs text-muted-foreground">{r.variant_label}</span>
                      {again > 0 ? (
                        <span className="mt-0.5 inline-block rounded border border-primary/40 px-1.5 text-xs text-primary">
                          run again #{again + 1}
                        </span>
                      ) : null}
                    </th>
                    <td className="py-2 pr-3 text-xs">
                      {r.status === "running" && r.progress !== null
                        ? `Running, ${String(Math.round(r.progress * 100))}%`
                        : STATUS_TEXT[r.status]}
                    </td>
                    {metrics.map((m) => {
                      const v = r.status === "done" ? m.value(r) : undefined;
                      const isBest = v !== undefined && best.get(m.key) === r.id;
                      return (
                        <td
                          key={m.key}
                          className={cn(
                            "py-2 pr-3 text-right tabular-nums",
                            isBest && "font-semibold",
                          )}
                        >
                          {v === undefined ? (
                            <span className="text-muted-foreground">
                              {r.status === "done" ? "n/a" : ""}
                            </span>
                          ) : (
                            <>
                              {m.format(v)}
                              {isBest ? (
                                <span className="block text-xs font-normal text-ok">best</span>
                              ) : null}
                            </>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      <Insights items={experimentInsights(runs, metrics)} />
    </div>
  );
}

function Parameters({ e }: { e: ExperimentInfo }) {
  const p = e.params;
  return (
    <dl className="grid grid-cols-[7rem_1fr] content-start gap-y-2 text-sm">
      <dt className="text-muted-foreground">Dataset</dt>
      <dd>
        {e.dataset_id ? (
          <Link
            to={`/datasets/${String(e.dataset_id)}?v=${String(e.dataset_version ?? "")}`}
            className="text-primary underline-offset-4 hover:underline"
          >
            {e.dataset_name}, version {e.dataset_version}
          </Link>
        ) : (
          "removed"
        )}
      </dd>
      <dt className="text-muted-foreground">Device</dt>
      <dd>{e.device_name ?? "removed"}</dd>
      {p ? (
        <>
          <dt className="text-muted-foreground">Threads</dt>
          <dd className="tabular-nums">
            {p.threads}
            {p.cpu_list?.length ? `, pinned to CPUs ${p.cpu_list.join(", ")}` : ""}
          </dd>
          <dt className="text-muted-foreground">Rounds</dt>
          <dd className="tabular-nums">
            {p.warmup} warm-up, {p.iterations} timed
          </dd>
          <dt className="text-muted-foreground">Detection</dt>
          <dd className="tabular-nums">
            confidence {p.conf}, overlap {p.iou}, up to {p.max_det} per image
          </dd>
        </>
      ) : null}
    </dl>
  );
}

export default function ExperimentDetail() {
  const id = Number(useParams().id);
  const experiment = useExperiment(id);
  const cancel = useCancelExperiment();
  const remove = useRemoveExperiment();
  const confirm = useConfirm();
  const navigate = useNavigate();

  if (remove.isPending || remove.isSuccess) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Removing the experiment.
      </p>
    );
  }
  if (experiment.isPending) {
    return <Skeleton aria-busy="true" aria-label="Loading experiment" className="h-40 max-w-3xl" />;
  }
  if (experiment.isError) {
    return (
      <>
        <PageHeader title="Experiment not found" />
        <EmptyState
          title="That experiment is not here"
          action={{ label: "Go to results", to: "/results" }}
        >
          {experiment.error.message}
        </EmptyState>
      </>
    );
  }
  const e = experiment.data;
  const total = Object.values(e.counts).reduce((a, b) => a + b, 0);
  const finished = total - (e.counts.queued ?? 0) - (e.counts.running ?? 0);

  return (
    <>
      <p className="mb-2 text-sm">
        <Link to="/results" className="text-primary underline-offset-4 hover:underline">
          Results
        </Link>
      </p>
      <PageHeader
        title={e.name}
        hint="A named set of runs: model variants compared on one dataset version and one device."
      >
        {e.notes || undefined}
      </PageHeader>

      <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2">
        <p role="status" className="flex items-center gap-2 text-sm font-medium">
          {e.status === "running" ? <Loader2 aria-hidden className="size-4 animate-spin" /> : null}
          {STATUS_WORDS[e.status]}: {String(finished)} of {String(total)} runs finished
        </p>
        {e.status === "running" ? (
          <Link to="/live" className="text-sm text-primary underline-offset-4 hover:underline">
            Watch live
          </Link>
        ) : null}
      </div>
      {e.status === "running" ? (
        <progress
          className="mb-4 h-2 w-full max-w-prose"
          value={finished}
          max={total}
          aria-label="Experiment progress"
        />
      ) : null}

      <div className="mb-6 flex flex-wrap gap-2">
        {e.status === "running" ? (
          <Button
            size="sm"
            variant="outline"
            disabled={cancel.isPending}
            onClick={() => {
              cancel.mutate(e.id, {
                onError: (err) => {
                  toast.error(err.message);
                },
              });
            }}
          >
            Cancel what is left
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="destructive"
          onClick={() => {
            void confirm({
              title: `Do you really want to delete ${e.name}?`,
              body: `The experiment and all ${String(total)} of its runs disappear from the results. This cannot be undone.${
                e.status === "running" ? " Runs that are still waiting or running are stopped." : ""
              }`,
              confirmLabel: "Delete experiment",
              destructive: true,
              typeToConfirm: `delete ${e.name}`,
            }).then((ok) => {
              if (!ok) return;
              remove.mutate(e.id, {
                onSuccess: () => {
                  toast.success(`${e.name} was deleted`);
                  void navigate("/results");
                },
                onError: (err) => {
                  toast.error(err.message);
                },
              });
            });
          }}
        >
          Delete experiment
        </Button>
      </div>

      <Section
        title="Runs"
        id="runs"
        hint="Rows are ranked by the first metric; if two runs are equal on it, the next metric you chose decides, and so on. 'best' marks the leader of each column, using the same order to settle ties. A tinted row is a run made again."
      >
        <RunsTable e={e} />
      </Section>

      <Section title="Parameters and pictures" id="pictures">
        <div className="grid gap-8 lg:grid-cols-[17rem_minmax(0,1fr)]">
          <Parameters e={e} />
          <PictureInspector e={e} />
        </div>
      </Section>
    </>
  );
}
