// The spec sheet: one row per fact, one column per run, grouped, with the best of each row marked and the rows where every run is the
// same flagged so the page can hide them. Pure (no browser), tested in e2e/compare.spec.ts.
import { METRIC_BY_KEY, throttled } from "../metrics.ts";
import type { RunInfo } from "../runs.ts";
import { threadsText, type Subject } from "./subjects.ts";

export type Group = "Accuracy" | "Speed" | "Size and set-up" | "The machine";

export interface SpecRow {
  key: string;
  group: Group;
  /** Plain words; the technical name is `tech`, shown on hover. */
  label: string;
  tech?: string;
  hint?: string;
  cells: { text: string; value?: number }[];
  /** Columns that are best in this row (none when every value is the same, or the row has no better or worse). */
  best: number[];
  /** Every run has the same value, as shown. */
  same: boolean;
}

/** Plain-words name for a metric, with the technical one kept for hover. */
const PLAIN: Record<string, { label: string; group: Group }> = {
  map50_95: { label: "Accuracy score", group: "Accuracy" },
  map50: { label: "Accuracy score (easy overlap)", group: "Accuracy" },
  f1: { label: "Balance of misses and false alarms", group: "Accuracy" },
  recall: { label: "Share of real objects found", group: "Accuracy" },
  precision: { label: "Share of detections that were right", group: "Accuracy" },
  accuracy: { label: "Overall correct", group: "Accuracy" },
  mean_iou: { label: "How tightly the boxes fit", group: "Accuracy" },
  missed: { label: "Objects missed", group: "Accuracy" },
  invented: { label: "False alarms", group: "Accuracy" },
  wrong: { label: "Found but named wrongly", group: "Accuracy" },
  p50: { label: "Typical time per picture", group: "Speed" },
  p95: { label: "Time in the slow cases", group: "Speed" },
  fps: { label: "Pictures per second", group: "Speed" },
  load_ms: { label: "Time to open the model", group: "Speed" },
};

const mb = (r: RunInfo) => (r.size_bytes ? r.size_bytes / 1_048_576 : undefined);

interface Plain {
  key: string;
  group: Group;
  label: string;
  tech?: string;
  hint?: string;
  text: (r: RunInfo) => string;
  value?: (r: RunInfo) => number | undefined;
  higher?: boolean;
  step?: number;
}

const FACTS: Plain[] = [
  {
    key: "size",
    group: "Size and set-up",
    label: "File size",
    text: (r) => (mb(r) === undefined ? "n/a" : `${(mb(r) ?? 0).toFixed(1)} MB`),
    value: mb,
    higher: false,
    step: 0.1,
  },
  {
    key: "imgsz",
    group: "Size and set-up",
    label: "Picture size it works at",
    text: (r) => (r.imgsz ? `${String(r.imgsz)} px` : "n/a"),
  },
  {
    key: "format",
    group: "Size and set-up",
    label: "Format and precision",
    text: (r) => `${r.format} ${r.precision}`,
  },
  { key: "threads", group: "Size and set-up", label: "Threads", text: threadsText },
  {
    key: "dataset",
    group: "Size and set-up",
    label: "Pictures it was tested on",
    text: (r) => `${r.dataset_name ?? "removed"} v${String(r.dataset_version ?? "?")}`,
  },
  {
    key: "device",
    group: "Size and set-up",
    label: "Machine",
    text: (r) => r.device_name ?? "removed",
  },
  {
    key: "hottest",
    group: "The machine",
    label: "Hottest reading",
    tech: "°C",
    text: (r) => {
      const t = r.result?.telemetry?.run?.temp_c_max;
      return t == null ? "n/a" : `${t.toFixed(0)} °C`;
    },
    value: (r) => r.result?.telemetry?.run?.temp_c_max ?? undefined,
    higher: false,
    step: 1,
  },
  {
    key: "throttled",
    group: "The machine",
    label: "Slowed itself down?",
    text: (r) =>
      r.result?.telemetry?.run?.throttled == null
        ? "n/a"
        : r.result.telemetry.run.throttled
          ? "Yes"
          : "No",
  },
];

const ORDER: Group[] = ["Accuracy", "Speed", "Size and set-up", "The machine"];

export function specSheet(subjects: Subject[]): SpecRow[] {
  const rows: SpecRow[] = [];
  const fromMetric = (key: string): SpecRow | undefined => {
    const m = METRIC_BY_KEY.get(key);
    const plain = PLAIN[key];
    if (!m || !plain) return undefined;
    const values = subjects.map((s) => m.value(s.run));
    return finish(
      {
        key,
        group: plain.group,
        label: plain.label,
        tech: m.label,
        hint: m.hint,
        cells: subjects.map((s, i) => {
          const v = values[i];
          return v === undefined
            ? {
                text: throttled(s.run) && plain.group === "Speed" ? "not clean (throttled)" : "n/a",
              }
            : { text: m.format(v), value: v };
        }),
      },
      values,
      m.higher,
      m.step,
    );
  };
  for (const key of Object.keys(PLAIN)) {
    const row = fromMetric(key);
    if (row) rows.push(row);
  }
  for (const f of FACTS) {
    const values = subjects.map((s) => f.value?.(s.run));
    rows.push(
      finish(
        {
          key: f.key,
          group: f.group,
          label: f.label,
          tech: f.tech,
          cells: subjects.map((s, i) => ({ text: f.text(s.run), value: values[i] })),
        },
        values,
        f.higher,
        f.step,
      ),
    );
  }
  return rows.sort((a, b) => ORDER.indexOf(a.group) - ORDER.indexOf(b.group));
}

function finish(
  row: Omit<SpecRow, "best" | "same">,
  values: (number | undefined)[],
  higher: boolean | undefined,
  step = 0.001,
): SpecRow {
  const same = row.cells.every((c) => c.text === row.cells[0]?.text);
  const known = values.flatMap((v, i) => (v === undefined ? [] : [{ i, v: Math.round(v / step) }]));
  if (higher === undefined || same || known.length < 2) return { ...row, best: [], same };
  const top = known.reduce(
    (a, b) => (higher ? Math.max(a, b.v) : Math.min(a, b.v)),
    known[0]?.v ?? 0,
  );
  const best = known.filter((k) => k.v === top).map((k) => k.i);
  return { ...row, best: best.length === known.length ? [] : best, same };
}
