import { create } from "zustand";
import type { Accuracy, RunInfo } from "./runs";

/**
 * A measurement of a run. None of these is "the" way to judge a model: which ones matter depends on what the model is for, so the
 * person chooses them (Settings, or the chooser on an experiment page) and the first one ranks the rows.
 */
export interface Metric {
  key: string;
  label: string;
  short: string;
  group: "accuracy" | "counts" | "speed";
  /** True when a bigger number is better. */
  higher: boolean;
  /** What it tells you, for the "i" next to it. */
  hint: string;
  value: (run: RunInfo) => number | undefined;
  /** A line under the number in a table cell (an interval, a caveat). */
  detail?: (run: RunInfo) => string | undefined;
  format: (n: number) => string;
  /** Two values closer than this are the same result (what the page would show): ties are broken by the next metric. */
  step: number;
}

const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
const ms = (n: number) => `${n.toFixed(1)} ms`;
const count = (n: number) => String(Math.round(n));
const acc = (run: RunInfo): Accuracy | undefined =>
  run.result?.accuracy?.available ? run.result.accuracy : undefined;
const total = (run: RunInfo) => run.result?.speed?.stages.total;
/** The headline median: the mean of the repeats' medians. None when every repeat was throttled (the run is not comparable). */
const headline = (run: RunInfo): number | undefined =>
  run.latency ? (run.latency.valid ? run.latency.p50_ms : undefined) : total(run)?.p50;
/** A speed metric that is missing because the run was throttled, not because it was never measured. */
export const throttled = (run: RunInfo) => run.status === "done" && run.latency?.valid === false;

/** Counts at confidence 0.25 and overlap 0.45, from the confusion matrix (rows: truth, columns: answer, last: nothing). */
export function confusionCounts(
  a: Accuracy | undefined,
): { right: number; wrong: number; missed: number; invented: number } | undefined {
  const m = a?.confusion?.matrix;
  if (!m || m.length < 2) return undefined;
  const n = m.length - 1;
  let right = 0;
  let wrong = 0;
  let missed = 0;
  let invented = 0;
  for (let i = 0; i <= n; i++) {
    for (let j = 0; j <= n; j++) {
      const v = m[i]?.[j] ?? 0;
      if (i < n && j < n) {
        if (i === j) right += v;
        else wrong += v;
      } else if (i < n) missed += v;
      else if (j < n) invented += v;
    }
  }
  return { right, wrong, missed, invented };
}

export const METRICS: Metric[] = [
  {
    key: "map50_95",
    label: "mAP50-95",
    short: "mAP50-95",
    group: "accuracy",
    higher: true,
    hint: "Accuracy averaged over strict and loose overlap limits. The usual single number for a detector.",
    value: (r) => acc(r)?.map50_95,
    format: pct,
    step: 0.001,
  },
  {
    key: "map50",
    label: "mAP50",
    short: "mAP50",
    group: "accuracy",
    higher: true,
    hint: "Accuracy when a box only has to overlap the real one by half. Forgiving: good for 'does it find things at all'.",
    value: (r) => acc(r)?.map50,
    format: pct,
    step: 0.001,
  },
  {
    key: "f1",
    label: "F1 score",
    short: "F1",
    group: "accuracy",
    higher: true,
    hint: "Balance of precision and recall at the best confidence. Use it when false alarms and misses cost about the same.",
    value: (r) => acc(r)?.f1,
    format: pct,
    step: 0.001,
  },
  {
    key: "precision",
    label: "Precision",
    short: "Precision",
    group: "accuracy",
    higher: true,
    hint: "Of everything it reported, how much was right. Rank by this when a false alarm is expensive (a wrong item on a bill).",
    value: (r) => acc(r)?.precision,
    format: pct,
    step: 0.001,
  },
  {
    key: "recall",
    label: "Recall",
    short: "Recall",
    group: "accuracy",
    higher: true,
    hint: "Of everything really there, how much it found. Rank by this when a miss is expensive (an item left off the bill).",
    value: (r) => acc(r)?.recall,
    format: pct,
    step: 0.001,
  },
  {
    key: "accuracy",
    label: "Detection accuracy",
    short: "Accuracy",
    group: "accuracy",
    higher: true,
    hint: "Correct detections out of all correct, wrong-class, missed and invented ones (confidence 0.25, overlap 0.45). Stricter than precision or recall alone.",
    value: (r) => {
      const c = confusionCounts(acc(r));
      const all = c ? c.right + c.wrong + c.missed + c.invented : 0;
      return c && all > 0 ? c.right / all : undefined;
    },
    format: pct,
    step: 0.001,
  },
  {
    key: "mean_iou",
    label: "Mean IoU",
    short: "IoU",
    group: "accuracy",
    higher: true,
    hint: "How tightly the boxes fit: the average overlap between a detection and the real box it matched. 100% is a perfect fit. Only measured for runs made after this was added.",
    value: (r) => (acc(r)?.mean_iou ? acc(r)?.mean_iou : undefined),
    format: pct,
    step: 0.001,
  },
  {
    key: "missed",
    label: "Missed objects",
    short: "Missed",
    group: "counts",
    higher: false,
    hint: "Real objects the model did not find (confidence 0.25). Fewer is better.",
    value: (r) => confusionCounts(acc(r))?.missed,
    format: count,
    step: 1,
  },
  {
    key: "invented",
    label: "False alarms",
    short: "False alarms",
    group: "counts",
    higher: false,
    hint: "Detections where nothing real was (confidence 0.25). Fewer is better.",
    value: (r) => confusionCounts(acc(r))?.invented,
    format: count,
    step: 1,
  },
  {
    key: "wrong",
    label: "Wrong class",
    short: "Wrong class",
    group: "counts",
    higher: false,
    hint: "Objects found in the right place but named as another class (confidence 0.25). Fewer is better.",
    value: (r) => confusionCounts(acc(r))?.wrong,
    format: count,
    step: 1,
  },
  {
    key: "p50",
    label: "Median time per image",
    short: "Median time",
    group: "speed",
    higher: false,
    hint: "The typical time for one image, start to finish: the mean of each repeat's median, with the 95% interval across repeats under it. Lower is faster. A run whose repeats were all throttled has no value here.",
    value: headline,
    detail: (r) => {
      const l = r.latency;
      if (!l?.valid || l.ci_half_width_ms === null) return undefined;
      return `± ${l.ci_half_width_ms.toFixed(1)} ms (${String(l.valid_repeats)} repeats${l.wide ? ", wide" : ""})`;
    },
    format: ms,
    step: 0.1,
  },
  {
    key: "p95",
    label: "95th percentile time",
    short: "Slow-case time",
    group: "speed",
    higher: false,
    hint: "The time that 95 of 100 images beat. Matters when an occasional slow image is a problem.",
    value: (r) => (r.latency?.valid === false ? undefined : total(r)?.p95),
    format: ms,
    step: 0.1,
  },
  {
    key: "fps",
    label: "Images per second",
    short: "Images/s",
    group: "speed",
    higher: true,
    hint: "How many images it handles each second at the median time. Higher is faster.",
    value: (r) => {
      const p50 = headline(r);
      return p50 ? 1000 / p50 : undefined;
    },
    format: (n) => n.toFixed(1),
    step: 0.1,
  },
  {
    key: "load_ms",
    label: "Model load time",
    short: "Load time",
    group: "speed",
    higher: false,
    hint: "How long the model takes to open before the first image. Matters for a program that starts often.",
    value: (r) => r.result?.load_ms,
    format: ms,
    step: 1,
  },
];
export const METRIC_BY_KEY = new Map(METRICS.map((m) => [m.key, m]));
export const DEFAULT_PRIORITY = ["map50_95", "f1", "p50"];
export const PRIORITY_KEY = "edgebench.metric-priority";

function read(): string[] {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(PRIORITY_KEY) ?? "null");
    if (Array.isArray(raw)) {
      const keys = raw.filter((k): k is string => typeof k === "string" && METRIC_BY_KEY.has(k));
      if (keys.length > 0) return [...new Set(keys)];
    }
  } catch {
    /* unreadable or blocked storage: use the default */
  }
  return DEFAULT_PRIORITY;
}

interface PriorityState {
  /** Metric keys, most important first. The first ranks the rows; all are shown, in this order. */
  order: string[];
  set: (order: string[]) => void;
  reset: () => void;
}

export const usePriority = create<PriorityState>((set) => ({
  order: read(),
  set: (order) => {
    try {
      localStorage.setItem(PRIORITY_KEY, JSON.stringify(order));
    } catch {
      /* not persisted; still applies for this session */
    }
    set({ order });
  },
  reset: () => {
    try {
      localStorage.removeItem(PRIORITY_KEY);
    } catch {
      /* nothing was saved to remove */
    }
    set({ order: DEFAULT_PRIORITY });
  },
}));

export function priorityMetrics(order: string[]): Metric[] {
  return order.map((k) => METRIC_BY_KEY.get(k)).filter((m): m is Metric => m !== undefined);
}

/** A value reduced to the resolution the page shows, so that 52.04% and 52.01% count as the same result. */
function stepped(metric: Metric, run: RunInfo): number | undefined {
  const v = metric.value(run);
  return v === undefined ? undefined : Math.round(v / metric.step);
}

/** Order two runs by the metrics in turn: the first metric decides, and only a tie moves on to the next. */
export function compareRuns(a: RunInfo, b: RunInfo, metrics: Metric[]): number {
  for (const m of metrics) {
    const x = stepped(m, a);
    const y = stepped(m, b);
    if (x === y) continue;
    if (x === undefined) return 1;
    if (y === undefined) return -1;
    return m.higher ? y - x : x - y;
  }
  return a.id - b.id;
}

/** Runs best first. Ties on the first metric are settled by the second, and so on down the person's priorities. */
export function rankRuns(runs: RunInfo[], metrics: Metric[]): RunInfo[] {
  return [...runs].sort((a, b) => compareRuns(a, b, metrics));
}

/**
 * Which run to mark "best" in each column. The best value wins its column; if several runs share it (to the precision shown),
 * the one that comes first by the person's whole priority order gets the mark, so a column where every run is the same still
 * points at the run that wins on the other metrics. No marks at all when the runs cannot be told apart by any metric.
 */
export function bestByMetric(runs: RunInfo[], metrics: Metric[]): Map<string, number> {
  const out = new Map<string, number>();
  if (runs.length < 2) return out;
  const indistinguishable = metrics.every(
    (m) => new Set(runs.map((r) => stepped(m, r))).size === 1,
  );
  if (indistinguishable) return out;
  for (const m of metrics) {
    const values = runs
      .map((r) => ({ r, v: stepped(m, r) }))
      .filter((x): x is { r: RunInfo; v: number } => x.v !== undefined);
    if (values.length === 0) continue;
    const top = values.reduce(
      (best, x) => (m.higher ? Math.max(best, x.v) : Math.min(best, x.v)),
      values[0]?.v ?? 0,
    );
    const tied = values.filter((x) => x.v === top).map((x) => x.r);
    const winner = rankRuns(tied, metrics)[0];
    if (winner) out.set(m.key, winner.id);
  }
  return out;
}

/** The run that is best by one metric alone, or undefined if none has a value. */
export function bestRun(
  runs: RunInfo[],
  metric: Metric,
  tieBreakers: Metric[] = [],
): RunInfo | undefined {
  return rankRuns(
    runs.filter((r) => metric.value(r) !== undefined),
    [metric, ...tieBreakers.filter((m) => m.key !== metric.key)],
  )[0];
}

/** Two runs with the same value for a metric, to the precision the page shows. */
export function sameResult(metric: Metric, a: RunInfo, b: RunInfo): boolean {
  const x = stepped(metric, a);
  return x !== undefined && x === stepped(metric, b);
}
