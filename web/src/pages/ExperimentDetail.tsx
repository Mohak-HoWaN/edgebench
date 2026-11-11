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
  useResumeExperiment,
  type Comparison,
  type Drift,
  type ExperimentInfo,
} from "@/lib/experiments";
import { configKey, experimentInsights } from "@/lib/insights";
import {
  bestByMetric,
  METRICS,
  priorityMetrics,
  rankRuns,
  throttled,
  usePriority,
} from "@/lib/metrics";
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

/** How many times a measurement (variant, threads, CPUs) had been run before this run (0 for the first). A sweep is not a repeat. */
function repeatNumbers(runs: RunInfo[]): Map<number, number> {
  const seen = new Map<string, number>();
  const out = new Map<number, number>();
  for (const r of [...runs].sort((a, b) => a.id - b.id)) {
    const key = configKey(r);
    const n = seen.get(key) ?? 0;
    out.set(r.id, n);
    seen.set(key, n + 1);
  }
  return out;
}

/** The settings that differ between runs, so a sweep's rows can be told apart. */
function settingsNote(r: RunInfo): string {
  const p = r.params;
  if (!p) return "";
  const cpus = p.cpu_list?.length ? `, CPUs ${p.cpu_list.join(",")}` : "";
  return `${String(p.threads)} thread${p.threads === 1 ? "" : "s"}${cpus}`;
}

/** Speed against the PyTorch baseline at the same settings, and whether the accuracy check passed. */
function AgainstBaseline({ c, d }: { c?: Comparison; d?: Drift }) {
  return (
    <div className="space-y-1 text-xs">
      {c?.speedup ? (
        <p>
          {c.speedup >= 1
            ? `${c.speedup.toFixed(2)}x faster`
            : `${(1 / c.speedup).toFixed(2)}x slower`}
          {c.significant === true ? (
            <span className="text-muted-foreground"> (a real difference)</span>
          ) : c.significant === false ? (
            <span className="text-warn"> (not significant: could be noise)</span>
          ) : (
            <span className="text-muted-foreground"> (no test: {c.note ?? "too few repeats"})</span>
          )}
        </p>
      ) : null}
      {d ? (
        <>
          <p className={d.verdict.passed ? "text-ok" : "font-medium text-destructive"}>
            {d.verdict.passed ? "Passes the accuracy check" : "Fails the accuracy check"}
          </p>
          <p className="text-muted-foreground">
            {d.mean_box_iou !== undefined && d.mean_box_iou !== null
              ? `boxes agree ${(d.mean_box_iou * 100).toFixed(0)}%`
              : "boxes: not compared"}
            {d.map50_delta !== null
              ? `; mAP50 ${d.map50_delta >= 0 ? "+" : "-"}${Math.abs(d.map50_delta * 100).toFixed(1)} points`
              : ""}
          </p>
          {d.verdict.reasons.map((reason) => (
            <p key={reason} className="text-destructive">
              {reason}
            </p>
          ))}
        </>
      ) : null}
    </div>
  );
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
  const showSettings = new Set(runs.map((r) => settingsNote(r))).size > 1;
  const showAgainst = Object.keys(e.drift).length > 0 || Object.keys(e.comparisons).length > 0;

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
                {showAgainst ? (
                  <th scope="col" className="py-2 pr-3 font-medium">
                    <span className="inline-flex items-center gap-1">
                      Against the .pt
                      <Info>
                        Speed compared with the PyTorch baseline run at the same settings, using a
                        Welch test on the repeats (a speed-up that could be noise says so). The
                        accuracy check compares the boxes and the mAP with the baseline's, using the
                        limits in Settings.
                      </Info>
                    </span>
                  </th>
                ) : null}
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
                      {showSettings ? (
                        <span className="block text-xs text-muted-foreground">
                          {settingsNote(r)}
                        </span>
                      ) : null}
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
                            <span
                              className={cn(
                                "text-muted-foreground",
                                m.group === "speed" && throttled(r) && "text-warn",
                              )}
                            >
                              {r.status !== "done"
                                ? ""
                                : m.group === "speed" && throttled(r)
                                  ? "throttled"
                                  : "n/a"}
                            </span>
                          ) : (
                            <>
                              {m.format(v)}
                              {m.detail?.(r) ? (
                                <span className="block text-xs font-normal text-muted-foreground">
                                  {m.detail(r)}
                                </span>
                              ) : null}
                              {isBest ? (
                                <span className="block text-xs font-normal text-ok">best</span>
                              ) : null}
                            </>
                          )}
                        </td>
                      );
                    })}
                    {showAgainst ? (
                      <td className="py-2 pr-3">
                        <AgainstBaseline
                          c={e.comparisons[String(r.id)]}
                          d={e.drift[String(r.id)]}
                        />
                      </td>
                    ) : null}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      <Insights
        items={experimentInsights(runs, metrics, { drift: e.drift, comparisons: e.comparisons })}
      />
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
            {p.warmup} warm-up and {p.iterations} timed, in {p.repeats ?? 1} repeat
            {(p.repeats ?? 1) === 1 ? "" : "s"}
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
  const resume = useResumeExperiment();
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
        {e.resumable ? (
          <Button
            size="sm"
            variant="outline"
            disabled={resume.isPending}
            onClick={() => {
              resume.mutate(e.id, {
                onSuccess: () => {
                  toast.success("The runs that were not finished are queued again");
                },
                onError: (err) => {
                  toast.error(err.message);
                },
              });
            }}
          >
            Resume: make what is missing
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
