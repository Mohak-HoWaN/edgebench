import { Loader2 } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { useConfirm } from "@/components/ConfirmProvider";
import { EmptyState } from "@/components/EmptyState";
import { Info } from "@/components/Info";
import { Insights } from "@/components/Insights";
import { PageHeader, Section } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useExperiment } from "@/lib/experiments";
import { runInsights } from "@/lib/insights";
import { METRICS, priorityMetrics, usePriority } from "@/lib/metrics";
import {
  STATUS_TEXT,
  useCancelRun,
  useRun,
  useRemoveRun,
  useRunAgain,
  type Accuracy,
  type RunInfo,
  type RunResult,
  type Stage,
} from "@/lib/runs";

const ms = (n: number) => `${n.toFixed(1)} ms`;
const pct = (n: number | undefined) => (n === undefined ? "n/a" : `${(n * 100).toFixed(1)}%`);
const STAGES = ["preprocess", "inference", "postprocess", "total"] as const;
const STAGE_LABEL: Record<(typeof STAGES)[number], string> = {
  preprocess: "Preprocess (resize and pad)",
  inference: "Model",
  postprocess: "Postprocess (decode and NMS)",
  total: "Total per image",
};
const COLUMNS: [keyof Stage, string][] = [
  ["mean", "Mean"],
  ["p50", "Median"],
  ["p95", "95th percentile"],
  ["p99", "99th percentile"],
  ["min", "Fastest"],
  ["max", "Slowest"],
];

function AccuracyBlock({ a, run }: { a: Accuracy; run: RunInfo }) {
  const order = usePriority((s) => s.order);
  if (!a.available) {
    return <p className="text-sm text-muted-foreground">Accuracy: {a.note ?? "n/a"}.</p>;
  }
  const classes = Object.entries(a.per_class ?? {}).sort((x, y) => y[1].ap50_95 - x[1].ap50_95);
  // every metric the tool knows, in the person's order first, with what it means on hover
  const shown = [
    ...priorityMetrics(order),
    ...METRICS.filter((m) => !order.includes(m.key)),
  ].filter((m) => m.group !== "speed" && m.value(run) !== undefined);
  return (
    <>
      <dl className="grid max-w-2xl grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
        {shown.map((m) => (
          <div key={m.key}>
            <dt className="flex items-center gap-1 text-xs text-muted-foreground">
              {m.short}
              <Info>{`${m.label}: ${m.hint} ${m.higher ? "Higher is better." : "Lower is better."}`}</Info>
            </dt>
            <dd className="text-xl font-semibold tabular-nums">{m.format(m.value(run) ?? 0)}</dd>
          </div>
        ))}
      </dl>
      {classes.length ? (
        <details className="mt-4 max-w-prose text-sm">
          <summary className="cursor-pointer">
            Accuracy per class ({String(classes.length)})
          </summary>
          <table className="mt-3 w-full text-left">
            <caption className="sr-only">Average precision per class</caption>
            <thead>
              <tr className="border-b">
                <th scope="col" className="py-1 pr-4 font-medium">
                  Class
                </th>
                <th scope="col" className="py-1 pr-4 text-right font-medium">
                  Objects
                </th>
                <th scope="col" className="py-1 pr-4 text-right font-medium">
                  AP50
                </th>
                <th scope="col" className="py-1 text-right font-medium">
                  AP50-95
                </th>
              </tr>
            </thead>
            <tbody>
              {classes.map(([name, c]) => (
                <tr key={name} className="tabular-nums">
                  <th scope="row" className="py-1 pr-4 text-left font-normal">
                    {name}
                  </th>
                  <td className="py-1 pr-4 text-right">{c.instances}</td>
                  <td className="py-1 pr-4 text-right">{pct(c.ap50)}</td>
                  <td className="py-1 text-right">{pct(c.ap50_95)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ) : null}
    </>
  );
}

const NOT_AVAILABLE = "not available on this machine";
const num = (n: number | null | undefined, unit: string, digits = 0) =>
  n === null || n === undefined ? NOT_AVAILABLE : `${n.toFixed(digits)}${unit}`;

/** The repeats of a run: each one's median, whether it counts, and what the machine did during it. */
function Repeats({ r }: { r: RunInfo }) {
  const speed = r.result?.speed;
  const repeats = speed?.repeats;
  const l = r.latency;
  if (!repeats?.length || !l) return null;
  return (
    <div className="mb-6 max-w-3xl">
      <p className="text-sm" data-testid="headline-latency">
        <span className="text-2xl font-semibold tabular-nums">{l.p50_ms.toFixed(1)} ms</span>
        {l.ci_half_width_ms !== null ? (
          <span className="tabular-nums"> ± {l.ci_half_width_ms.toFixed(1)} ms</span>
        ) : null}{" "}
        <span className="text-muted-foreground">
          median time per image, the mean of {String(l.n)} repeat{l.n === 1 ? "" : "s"}
          {l.ci_half_width_ms !== null ? " with a 95% interval across them" : ""}
        </span>
      </p>
      {l.wide ? (
        <p className="mt-1 text-sm text-warn">
          {l.n < 2
            ? "One repeat gives no interval, so this number has no error bar. Use more repeats."
            : `${String(l.n)} repeats give a wide interval. Five or more narrow it.`}
        </p>
      ) : null}
      {!l.valid ? (
        <p role="alert" className="mt-1 border-l-2 border-warn pl-3 text-sm">
          Invalid for latency: the machine slowed down during every repeat, so this speed is not to
          be compared. Run it again once the machine has cooled.
        </p>
      ) : null}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[34rem] text-left text-sm">
          <caption className="sr-only">Each repeat of the timed rounds</caption>
          <thead>
            <tr className="border-b">
              <th scope="col" className="py-2 pr-3 font-medium">
                Repeat
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Median
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                95th percentile
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                CPU
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Clock
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Temperature
              </th>
              <th scope="col" className="py-2 font-medium">
                Counts?
              </th>
            </tr>
          </thead>
          <tbody>
            {repeats.map((rep) => (
              <tr key={rep.index} className="border-b align-top tabular-nums">
                <th scope="row" className="py-2 pr-3 text-left font-normal">
                  {rep.index + 1}
                </th>
                <td className="py-2 pr-3 text-right">{ms(rep.stats.p50)}</td>
                <td className="py-2 pr-3 text-right">{ms(rep.stats.p95)}</td>
                <td className="py-2 pr-3 text-right">{num(rep.telemetry?.cpu_mean, "%")}</td>
                <td className="py-2 pr-3 text-right">
                  {num(rep.telemetry?.clock_mhz_mean, " MHz")}
                </td>
                <td className="py-2 pr-3 text-right">{num(rep.telemetry?.temp_c_max, " °C")}</td>
                <td className="py-2 text-xs">
                  {rep.valid ? "Yes" : `No: ${rep.invalid_reason ?? "throttled"}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** What the machine did while the run went, from the sampler that ran beside it. Anything it could not read says so. */
function Machine({ res }: { res: RunResult }) {
  const t = res.telemetry;
  const env = res.environment;
  if (!t && !env) return null;
  const run = t?.run;
  const sources = t?.sources ?? {};
  const rows: [string, string, string | null | undefined][] = [
    [
      "CPU use",
      `${num(run?.cpu_mean, "%")} on average, ${num(run?.cpu_max, "%")} at most`,
      sources.cpu,
    ],
    ["Memory", `${num(run?.rss_peak_mb, " MB")} at the peak (the benchmark process)`, sources.ram],
    [
      "CPU clock",
      `${num(run?.clock_mhz_mean, " MHz")} on average; the run started at ${num(t?.start_clock_mhz, " MHz")}`,
      sources.clock,
    ],
    ["Temperature", `${num(run?.temp_c_max, " °C")} at the highest`, sources.temperature],
    [
      "Throttling",
      run?.throttled === null || run?.throttled === undefined
        ? "no throttle flag on this machine; a clock that drops more than 10% still marks a repeat invalid"
        : run.throttled
          ? "the machine reported throttling"
          : "none reported",
      sources.throttle,
    ],
    [
      "GPU",
      run?.gpu_util_mean == null ? NOT_AVAILABLE : `${run.gpu_util_mean.toFixed(0)}% busy`,
      sources.gpu,
    ],
  ];
  return (
    <Section
      title="Machine during the run"
      id="machine"
      hint="Sampled five times a second by a separate process, so reading the sensors never slows the benchmark. A reading the machine cannot give is 'not available', never a zero."
    >
      {t?.enabled === false ? (
        <p className="text-sm text-muted-foreground">Telemetry was switched off for this run.</p>
      ) : null}
      <dl className="grid max-w-3xl grid-cols-[9rem_1fr] gap-y-2 text-sm">
        {t?.enabled === false
          ? null
          : rows.map(([name, value, source]) => (
              <div key={name} className="contents">
                <dt className="text-muted-foreground">{name}</dt>
                <dd>
                  {value}
                  {source ? (
                    <span className="block text-xs text-muted-foreground">{source}</span>
                  ) : null}
                </dd>
              </div>
            ))}
        {env ? (
          <>
            <dt className="text-muted-foreground">Power plan</dt>
            <dd>{env.power_plan ?? env.governor ?? NOT_AVAILABLE}</dd>
            <dt className="text-muted-foreground">Cores</dt>
            <dd className="tabular-nums">
              {env.logical_cores ?? "?"} logical, {env.physical_cores ?? "?"} physical
            </dd>
          </>
        ) : null}
      </dl>
    </Section>
  );
}

function Outcome({ r, siblings }: { r: RunInfo; siblings: RunInfo[] }) {
  const res = r.result;
  const order = usePriority((s) => s.order);
  if (!res?.speed) return null;
  const repeats = res.speed.repeats?.length ?? 1;
  const facts = [
    `Measured over ${String(res.speed.iterations)} timed rounds after ${String(res.speed.warmup)} warm-up rounds${
      repeats > 1 ? `, repeated ${String(repeats)} times` : ""
    }, cycling ${String(res.speed.pictures_cycled)} pictures.`,
    res.load_ms === undefined ? "" : `The model took ${ms(res.load_ms)} to load.`,
  ].filter(Boolean);
  return (
    <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_19rem]">
      <div>
        <Section
          title="Accuracy"
          hint="Measured on the annotated pictures of the dataset version. Precision, recall and F1 are read at the confidence that gives the best F1, as Ultralytics reports them; the counts and accuracy use confidence 0.25."
        >
          {res.accuracy ? (
            <AccuracyBlock a={res.accuracy} run={r} />
          ) : (
            <p className="text-sm">n/a</p>
          )}
        </Section>
        <Section
          title="Speed per image"
          hint="Time for one image, start to finish, split into preparing the picture, running the model and decoding the answer. The first call is slow and is left out. The table is pooled over the repeats that counted; repeats that were throttled are listed above it and left out."
        >
          <Repeats r={r} />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[34rem] max-w-3xl text-left text-sm">
              <caption className="sr-only">Time per image for each stage, in milliseconds</caption>
              <thead>
                <tr className="border-b">
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Stage
                  </th>
                  {COLUMNS.map(([, label]) => (
                    <th key={label} scope="col" className="py-2 pr-3 text-right font-medium">
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {STAGES.map((stage) => (
                  <tr key={stage} className="border-b tabular-nums">
                    <th scope="row" className="py-2 pr-4 text-left font-normal">
                      {STAGE_LABEL[stage]}
                    </th>
                    {COLUMNS.map(([key, label]) => (
                      <td key={label} className="py-2 pr-3 text-right">
                        {ms(res.speed?.stages[stage][key] ?? 0)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      </div>
      <Insights items={[...facts, ...runInsights(r, siblings, priorityMetrics(order))]} />
    </div>
  );
}

export default function RunDetail() {
  const id = Number(useParams().id);
  const run = useRun(id);
  const experiment = useExperiment(run.data?.experiment_id ?? 0, run.data?.experiment_id != null);
  const cancel = useCancelRun();
  const again = useRunAgain();
  const remove = useRemoveRun();
  const confirm = useConfirm();
  const navigate = useNavigate();

  if (run.isPending)
    return <Skeleton aria-busy="true" aria-label="Loading run" className="h-40 max-w-3xl" />;
  if (run.isError) {
    return (
      <>
        <PageHeader title="Run not found" />
        <EmptyState
          title="That run is not here"
          action={{ label: "Go to results", to: "/results" }}
        >
          {run.error.message}
        </EmptyState>
      </>
    );
  }
  const r = run.data;
  const active = r.status === "queued" || r.status === "running";
  const settings = r.params;

  return (
    <>
      <p className="mb-2 text-sm">
        <Link to="/results" className="text-primary underline-offset-4 hover:underline">
          Results
        </Link>
        {r.experiment_id !== null ? (
          <>
            {" / "}
            <Link
              to={`/experiments/${String(r.experiment_id)}`}
              className="text-primary underline-offset-4 hover:underline"
            >
              {experiment.data?.name ?? "Experiment"}
            </Link>
          </>
        ) : null}
      </p>
      <PageHeader title={`Run ${String(r.id)}`}>
        {r.model_name ?? "A removed model"}, {r.variant_label}, on{" "}
        {r.dataset_name ?? "a removed dataset"}
        {r.dataset_version ? ` (version ${String(r.dataset_version)})` : ""} with{" "}
        {r.device_name ?? "a removed device"}.
      </PageHeader>

      <p role="status" className="mb-4 flex items-center gap-2 text-sm font-medium">
        {active ? <Loader2 aria-hidden className="size-4 animate-spin" /> : null}
        {STATUS_TEXT[r.status]}
        {r.status === "running" && r.progress !== null
          ? `, ${String(Math.round(r.progress * 100))}%${r.message ? ` (${r.message})` : ""}`
          : ""}
      </p>
      {r.status === "running" && r.progress !== null ? (
        <progress
          className="mb-4 h-2 w-full max-w-prose"
          value={r.progress}
          max={1}
          aria-label="Run progress"
        />
      ) : null}
      {r.error ? (
        <p role="alert" className="mb-4 max-w-prose border-l-2 border-destructive pl-4 text-sm">
          {r.error}
        </p>
      ) : null}

      <div className="mb-6 flex flex-wrap gap-2">
        {active ? (
          <Button
            size="sm"
            variant="outline"
            disabled={cancel.isPending}
            onClick={() => {
              cancel.mutate(r.id, {
                onError: (e) => {
                  toast.error(e.message);
                },
              });
            }}
          >
            Cancel run
          </Button>
        ) : (
          <Button
            size="sm"
            variant="outline"
            disabled={again.isPending}
            onClick={() => {
              again.mutate(r.id, {
                onSuccess: (next) => {
                  toast.success(`Run ${String(next.id)} was queued`, {
                    action: {
                      label: "Watch live",
                      onClick: () => {
                        void navigate("/live");
                      },
                    },
                  });
                  void navigate(`/results/${String(next.id)}`);
                },
                onError: (e) => {
                  toast.error(e.message);
                },
              });
            }}
          >
            Run again
          </Button>
        )}
        {active ? null : (
          <Button
            size="sm"
            variant="destructive"
            disabled={remove.isPending}
            onClick={() => {
              void confirm({
                title: `Remove run ${String(r.id)}?`,
                body: "It disappears from the results. This cannot be undone.",
                confirmLabel: "Remove run",
                destructive: true,
              }).then((ok) => {
                if (!ok) return;
                remove.mutate(r.id, {
                  onSuccess: () => {
                    toast.success(`Run ${String(r.id)} was removed`);
                    void navigate(
                      r.experiment_id !== null
                        ? `/experiments/${String(r.experiment_id)}`
                        : "/results",
                    );
                  },
                  onError: (e) => {
                    toast.error(e.message);
                  },
                });
              });
            }}
          >
            Remove run
          </Button>
        )}
        <a
          className="inline-flex h-7 items-center rounded-lg border px-2.5 text-xs font-medium hover:bg-accent"
          href={`/api/runs/${String(r.id)}`}
          target="_blank"
          rel="noreferrer"
        >
          Raw data (JSON)
        </a>
      </div>

      <Outcome r={r} siblings={experiment.data?.runs ?? []} />
      {r.result ? <Machine res={r.result} /> : null}

      <Section title="Settings and environment">
        <dl className="grid max-w-prose grid-cols-[11rem_1fr] gap-y-2 text-sm">
          <dt className="text-muted-foreground">Runtime</dt>
          <dd>{r.result?.runtime?.kind ?? r.runtime}</dd>
          {settings ? (
            <>
              <dt className="text-muted-foreground">Threads</dt>
              <dd className="tabular-nums">
                {settings.threads}
                {r.result?.runtime?.cpus?.length
                  ? `, pinned to CPUs ${r.result.runtime.cpus.join(", ")}`
                  : settings.cpu_list?.length
                    ? `, asked to pin to CPUs ${settings.cpu_list.join(", ")}`
                    : ""}
              </dd>
              <dt className="text-muted-foreground">Detection settings</dt>
              <dd className="tabular-nums">
                confidence {settings.conf}, overlap limit {settings.iou}, up to {settings.max_det}{" "}
                per image
              </dd>
            </>
          ) : null}
          {r.result?.runtime?.versions ? (
            <>
              <dt className="text-muted-foreground">Packages</dt>
              <dd className="break-words">
                {Object.entries(r.result.runtime.versions)
                  .map(([k, v]) => `${k} ${v}`)
                  .join(", ")}
              </dd>
            </>
          ) : null}
          {r.result?.dataset ? (
            <>
              <dt className="text-muted-foreground">Dataset fingerprint</dt>
              <dd className="tabular-nums">{r.result.dataset.hash.slice(0, 16)}</dd>
            </>
          ) : null}
        </dl>
      </Section>

      {r.result?.log ? (
        <Section title="Log">
          <pre
            tabIndex={0}
            aria-label="Benchmark log"
            className="max-h-64 max-w-3xl overflow-auto rounded-md bg-muted p-3 text-xs"
          >
            {r.result.log}
          </pre>
        </Section>
      ) : null}
    </>
  );
}
