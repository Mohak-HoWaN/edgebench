// The numbers behind each chart, worked out from the selected runs. Pure: no browser, no drawing.
// A chart with nothing to draw gets an empty list and the page says what to select or run to fill it.
import { bestByMetric, compareRuns, headline, type Metric } from "../metrics.ts";
import type { Accuracy, RunInfo } from "../runs.ts";
import { threadsText, type Subject } from "./subjects.ts";

const acc = (r: RunInfo): Accuracy | undefined =>
  r.result?.accuracy?.available ? r.result.accuracy : undefined;
export const timeOf = headline;
export const mapOf = (r: RunInfo): number | undefined => acc(r)?.map50_95;
const dsKey = (r: RunInfo) => `${String(r.dataset_id)}:${String(r.dataset_version)}`;

export interface XY {
  subject: Subject;
  x: number;
  y: number;
  /** On the front: no other point is at least as good on both axes and better on one. */
  front: boolean;
}

/** Which points nobody beats on both axes. ``lowerX`` and ``higherY`` say which direction is good. */
export function frontOf(points: { x: number; y: number }[], higherY: boolean): boolean[] {
  return points.map(
    (p) =>
      !points.some((q) => {
        const yOk = higherY ? q.y >= p.y : q.y <= p.y;
        const yBetter = higherY ? q.y > p.y : q.y < p.y;
        return q.x <= p.x && yOk && (q.x < p.x || yBetter);
      }),
  );
}

function xy(
  subjects: Subject[],
  x: (r: RunInfo) => number | undefined,
  y: (r: RunInfo) => number | undefined,
  higherY: boolean,
): XY[] {
  const raw = subjects.flatMap((subject) => {
    const px = x(subject.run);
    const py = y(subject.run);
    return px === undefined || py === undefined ? [] : [{ subject, x: px, y: py }];
  });
  const front = frontOf(raw, higherY);
  return raw.map((p, i) => ({ ...p, front: front[i] === true }));
}

const megabytes = (r: RunInfo) => (r.size_bytes ? r.size_bytes / 1_048_576 : undefined);
/** 1: accuracy against speed. */
export const accuracySpeed = (s: Subject[]) => xy(s, timeOf, mapOf, true);
/** 16: size against accuracy, and size against speed. */
export const sizeAccuracy = (s: Subject[]) => xy(s, megabytes, mapOf, true);
export const sizeSpeed = (s: Subject[]) => xy(s, megabytes, timeOf, false);

// 2: latency distribution ---------------------------------------------------------------------------------------------

export function quantile(sorted: number[], q: number): number {
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return (sorted[lo] ?? 0) + ((sorted[hi] ?? 0) - (sorted[lo] ?? 0)) * (pos - lo);
}

/** Every timed iteration of the kept repeats, in ms (runs made before repeats were recorded have none). */
export function samplesOf(r: RunInfo): number[] | undefined {
  const speed = r.result?.speed;
  const kept = (speed?.repeats ?? []).filter((x) => x.valid).flatMap((x) => x.total_ms);
  if (kept.length > 0) return kept;
  return speed?.total_ms && speed.total_ms.length > 0 ? speed.total_ms : undefined;
}

export interface Box {
  subject: Subject;
  n: number;
  q1: number;
  median: number;
  q3: number;
  /** The whiskers reach the most extreme value within 1.5 box-heights of the box; beyond is an outlier. */
  low: number;
  high: number;
  outliers: number[];
  p99: number;
}

export function latencyBoxes(subjects: Subject[]): Box[] {
  return subjects.flatMap((subject) => {
    const samples = samplesOf(subject.run);
    if (!samples) return [];
    const s = [...samples].sort((a, b) => a - b);
    const q1 = quantile(s, 0.25);
    const q3 = quantile(s, 0.75);
    const fence = (q3 - q1) * 1.5;
    const inside = s.filter((v) => v >= q1 - fence && v <= q3 + fence);
    return [
      {
        subject,
        n: s.length,
        q1,
        median: quantile(s, 0.5),
        q3,
        low: inside[0] ?? s[0] ?? 0,
        high: inside[inside.length - 1] ?? s[s.length - 1] ?? 0,
        outliers: s.filter((v) => v > q3 + fence || v < q1 - fence),
        p99: quantile(s, 0.99),
      },
    ];
  });
}

// 3: latency over the run ---------------------------------------------------------------------------------------------

export interface Trace {
  subject: Subject;
  points: { x: number; y: number }[];
  /** Iteration numbers at which a new repeat began. */
  starts: number[];
}

export function overTime(subjects: Subject[], window = 9, maxPoints = 200): Trace[] {
  return subjects.flatMap((subject) => {
    const speed = subject.run.result?.speed;
    const repeats = speed?.repeats;
    const all =
      repeats && repeats.length > 0
        ? repeats.map((r) => r.total_ms)
        : speed?.total_ms
          ? [speed.total_ms]
          : [];
    const flat = all.flat();
    if (flat.length < window) return [];
    let at = 0;
    const starts = all.map((part) => {
      const begin = at;
      at += part.length;
      return begin;
    });
    const smooth = flat.map((_, i) => {
      const part = flat.slice(Math.max(0, i - window + 1), i + 1).sort((a, b) => a - b);
      return quantile(part, 0.5);
    });
    const stride = Math.max(1, Math.ceil(smooth.length / maxPoints));
    return [
      {
        subject,
        points: smooth.flatMap((y, i) => (i % stride === 0 ? [{ x: i + 1, y }] : [])),
        starts,
      },
    ];
  });
}

// 4: where the time goes ----------------------------------------------------------------------------------------------

export interface Stages {
  subject: Subject;
  pre: number;
  model: number;
  post: number;
}

export function stages(subjects: Subject[]): Stages[] {
  return subjects.flatMap((subject) => {
    const s = subject.run.result?.speed?.stages;
    return s
      ? [{ subject, pre: s.preprocess.mean, model: s.inference.mean, post: s.postprocess.mean }]
      : [];
  });
}

// 5: speed against threads --------------------------------------------------------------------------------------------

export interface ThreadLine {
  subject: Subject;
  label: string;
  points: { x: number; y: number; run: RunInfo }[];
}

/** One line per model and variant (on the same dataset and device) that was run at two or more thread counts. */
export function threadLines(subjects: Subject[]): ThreadLine[] {
  const groups = new Map<string, Subject[]>();
  for (const s of subjects) {
    const key = `${String(s.run.model_id)}|${s.run.variant_label}|${dsKey(s.run)}|${String(s.run.device_id)}`;
    groups.set(key, [...(groups.get(key) ?? []), s]);
  }
  return [...groups.values()].flatMap((members) => {
    const byThreads = new Map<number, Subject>();
    for (const m of members) {
      const t = m.run.params?.threads;
      if (t !== undefined && timeOf(m.run) !== undefined) byThreads.set(t, m);
    }
    if (byThreads.size < 2) return [];
    const points = [...byThreads.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([x, m]) => ({ x, y: timeOf(m.run) ?? 0, run: m.run }));
    const first = members[0];
    if (!first) return [];
    return [{ subject: first, label: `${first.modelName}, ${first.run.variant_label}`, points }];
  });
}

// 6: speed-up over the reference ----------------------------------------------------------------------------------------

export interface Speedup {
  subject: Subject;
  ratio: number;
  /** Half-width of the 95% interval on the ratio, when both runs have an interval. */
  half: number | undefined;
  crossesOne: boolean;
}

export function speedups(subjects: Subject[], ref: Subject | undefined): Speedup[] {
  const refT = ref ? timeOf(ref.run) : undefined;
  if (!ref || refT === undefined) return [];
  return subjects.flatMap((subject) => {
    const t = timeOf(subject.run);
    if (t === undefined) return [];
    const ratio = refT / t;
    const a = subject.run.latency?.ci_half_width_ms;
    const b = ref.run.latency?.ci_half_width_ms;
    const half =
      a != null && b != null && subject !== ref
        ? ratio * Math.sqrt((a / t) ** 2 + (b / refT) ** 2)
        : undefined;
    return [
      { subject, ratio, half, crossesOne: half !== undefined && Math.abs(ratio - 1) <= half },
    ];
  });
}

// 7: accuracy drift -----------------------------------------------------------------------------------------------------

export interface Drift {
  subject: Subject;
  /** Percentage points of mAP50-95 against the reference. */
  points: number;
  /** Fell by more than the allowed band. */
  outside: boolean;
  /** Found nothing: the failure the INT8 spike had. */
  zero: boolean;
}

export function drifts(subjects: Subject[], ref: Subject | undefined, band: number): Drift[] {
  const base = ref ? mapOf(ref.run) : undefined;
  if (!ref || base === undefined) return [];
  return subjects.flatMap((subject) => {
    const v = mapOf(subject.run);
    if (v === undefined) return [];
    const points = (v - base) * 100;
    return [
      { subject, points, outside: points < -band, zero: v === 0 || acc(subject.run)?.recall === 0 },
    ];
  });
}

// 8: accuracy per class -------------------------------------------------------------------------------------------------

export interface ClassHeat {
  classes: { name: string; instances: number; cells: (number | undefined)[] }[];
  subjects: Subject[];
}

export function classHeat(subjects: Subject[]): ClassHeat {
  const names = new Map<string, number>();
  for (const s of subjects)
    for (const [name, c] of Object.entries(acc(s.run)?.per_class ?? {}))
      names.set(name, Math.max(names.get(name) ?? 0, c.instances));
  const classes = [...names.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([name, instances]) => ({
      name,
      instances,
      cells: subjects.map((s) => acc(s.run)?.per_class?.[name]?.ap50_95),
    }));
  return { classes, subjects };
}

// 9: confusion ----------------------------------------------------------------------------------------------------------

export interface Confusion {
  labels: string[];
  matrix: number[][];
  /** The biggest mistakes, in words ("oreo was taken for center_fruit 3 times"). */
  top: { truth: string; answer: string; count: number }[];
  /** Real objects of each class that were not found. */
  missed: { name: string; missed: number; total: number }[];
}

export function confusion(subject: Subject | undefined): Confusion | undefined {
  const c = subject ? acc(subject.run)?.confusion : undefined;
  if (!c || c.matrix.length < 2) return undefined;
  const n = c.labels.length - 1;
  const top: Confusion["top"] = [];
  const missed: Confusion["missed"] = [];
  for (let i = 0; i <= n; i++) {
    for (let j = 0; j <= n; j++) {
      const count = c.matrix[i]?.[j] ?? 0;
      if (i !== j && count > 0 && i < n && j < n)
        top.push({ truth: c.labels[i] ?? "", answer: c.labels[j] ?? "", count });
    }
    if (i < n) {
      const row = c.matrix[i] ?? [];
      missed.push({
        name: c.labels[i] ?? "",
        missed: row[n] ?? 0,
        total: row.reduce((a, b) => a + b, 0),
      });
    }
  }
  return {
    labels: c.labels,
    matrix: c.matrix,
    top: top.sort((a, b) => b.count - a.count).slice(0, 5),
    missed,
  };
}

// 10 to 12: curves and scores -------------------------------------------------------------------------------------------

export interface Line {
  subject: Subject;
  points: { x: number; y: number }[];
  /** Index of the best point (F1 curve). */
  peak?: number;
}

export const classesWithCurves = (subjects: Subject[]): string[] => [
  ...new Set(subjects.flatMap((s) => Object.keys(acc(s.run)?.curves?.per_class ?? {}))),
];

function curve(s: Subject, cls: string | null) {
  const c = acc(s.run)?.curves;
  const part = c ? (cls === null ? c.all : c.per_class[cls]) : undefined;
  return c && part ? { conf: c.conf, ...part } : undefined;
}

/** 10: precision against recall, one line per run, for all classes (their mean) or one class. */
export function prLines(subjects: Subject[], cls: string | null): Line[] {
  return subjects.flatMap((subject) => {
    const c = curve(subject, cls);
    return c ? [{ subject, points: c.recall.map((x, i) => ({ x, y: c.precision[i] ?? 0 })) }] : [];
  });
}

/** 11: F1 against the confidence cut-off. */
export function f1Lines(subjects: Subject[], cls: string | null): Line[] {
  return subjects.flatMap((subject) => {
    const c = curve(subject, cls);
    if (!c) return [];
    const points = c.conf.map((x, i) => ({ x, y: c.f1[i] ?? 0 }));
    const peak = points.reduce((best, p, i) => (p.y > (points[best]?.y ?? -1) ? i : best), 0);
    return [{ subject, points, peak }];
  });
}

export interface ScoreHist {
  subject: Subject;
  /** Share of this run's detections in each of 20 bins from 0 to 1. */
  share: number[];
  mean: number;
}

export function scoreHists(subjects: Subject[]): ScoreHist[] {
  return subjects.flatMap((subject) => {
    const h = acc(subject.run)?.score_hist;
    const total = h?.reduce((a, b) => a + b, 0) ?? 0;
    if (!h || total === 0) return [];
    return [
      {
        subject,
        share: h.map((n) => n / total),
        mean: h.reduce((sum, n, i) => sum + n * ((i + 0.5) / h.length), 0) / total,
      },
    ];
  });
}

// 13: temperature and clock ---------------------------------------------------------------------------------------------

export interface Machine {
  subject: Subject;
  t: number[];
  temp: (number | null)[];
  clock: (number | null)[];
  /** Seconds at which the machine said it was throttling. */
  throttledAt: number[];
  repeats: { start: number; end: number; valid: boolean }[];
}

export function machine(subjects: Subject[]): Machine[] {
  return subjects.flatMap((subject) => {
    const s = subject.run.result?.telemetry?.series;
    if (!s || s.t.length < 2) return [];
    return [
      {
        subject,
        t: s.t,
        temp: s.temp_c,
        clock: s.clock_mhz,
        throttledAt: s.t.filter((_, i) => s.throttled[i] === true),
        repeats: s.repeats,
      },
    ];
  });
}

// 14: device comparison -------------------------------------------------------------------------------------------------

export interface DevicePair {
  title: string;
  /** One entry per device, slowest last. */
  devices: { subject: Subject; device: string; ms: number }[];
  /** How many times slower the slowest is than the fastest. */
  ratio: number;
}

export function devicePairs(subjects: Subject[]): DevicePair[] {
  const groups = new Map<string, Subject[]>();
  for (const s of subjects) {
    const key = `${String(s.run.model_id)}|${s.run.variant_label}|${threadsText(s.run)}|${dsKey(s.run)}`;
    groups.set(key, [...(groups.get(key) ?? []), s]);
  }
  return [...groups.values()].flatMap((members) => {
    const byDevice = new Map<number | null, Subject>();
    for (const m of members) if (timeOf(m.run) !== undefined) byDevice.set(m.run.device_id, m);
    if (byDevice.size < 2) return [];
    const devices = [...byDevice.values()]
      .map((subject) => ({
        subject,
        device: subject.run.device_name ?? "a removed device",
        ms: timeOf(subject.run) ?? 0,
      }))
      .sort((a, b) => a.ms - b.ms);
    const first = members[0];
    if (!first) return [];
    return [
      {
        title: `${first.modelName}, ${first.run.variant_label}, ${threadsText(first.run)}`,
        devices,
        ratio: (devices[devices.length - 1]?.ms ?? 1) / (devices[0]?.ms ?? 1),
      },
    ];
  });
}

// 15: accuracy by capture source ----------------------------------------------------------------------------------------

export interface BySource {
  sources: { name: string; cells: ({ map: number; images: number } | undefined)[] }[];
  subjects: Subject[];
}

export function bySource(subjects: Subject[]): BySource {
  const names = [
    ...new Set(subjects.flatMap((s) => Object.keys(acc(s.run)?.by_source ?? {}))),
  ].sort();
  return {
    subjects,
    sources: names.map((name) => ({
      name,
      cells: subjects.map((s) => {
        const v = acc(s.run)?.by_source?.[name];
        return v ? { map: v.map50_95, images: v.images } : undefined;
      }),
    })),
  };
}

// 17: scorecard ---------------------------------------------------------------------------------------------------------

export interface Scorecard {
  rows: {
    subject: Subject;
    cells: {
      metric: Metric;
      value: number | undefined;
      best: boolean;
      share: number | undefined;
    }[];
  }[];
  /** The winner would be another run if the first two priorities swapped. */
  sensitive: boolean;
  winner: Subject | undefined;
}

export function scorecard(subjects: Subject[], metrics: Metric[]): Scorecard {
  const order = (ms: Metric[]) => [...subjects].sort((a, b) => compareRuns(a.run, b.run, ms));
  const ranked = order(metrics);
  const best = bestByMetric(
    subjects.map((s) => s.run),
    metrics,
  );
  const swapped =
    metrics.length >= 2
      ? [metrics[1] ?? metrics[0], metrics[0], ...metrics.slice(2)].flatMap((m) => (m ? [m] : []))
      : metrics;
  const extent = new Map(
    metrics.map((m) => {
      const v = subjects.map((s) => m.value(s.run)).filter((x): x is number => x !== undefined);
      return [m.key, { lo: Math.min(...v), hi: Math.max(...v) }] as const;
    }),
  );
  return {
    winner: ranked[0],
    sensitive: subjects.length > 1 && order(swapped)[0]?.run.id !== ranked[0]?.run.id,
    rows: ranked.map((subject) => ({
      subject,
      cells: metrics.map((metric) => {
        const value = metric.value(subject.run);
        const e = extent.get(metric.key);
        // The bar is the value against the best in its column (the best fills it), so a small gap looks small.
        const share =
          value === undefined || !e
            ? undefined
            : metric.higher
              ? e.hi > 0
                ? value / e.hi
                : 1
              : value > 0
                ? e.lo / value
                : 1;
        return { metric, value, best: best.get(metric.key) === subject.run.id, share };
      }),
    })),
  };
}
