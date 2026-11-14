// The all-runs table: filter, sort, group, the window of rows to draw, and the CSV. Pure (no browser), tested in e2e/explorer.spec.ts.
import { METRIC_BY_KEY, throttled } from "./metrics.ts";
import type { RunInfo } from "./runs.ts";

export type SortKey =
  | "id"
  | "model"
  | "variant"
  | "threads"
  | "dataset"
  | "device"
  | "acc"
  | "f1"
  | "ms"
  | "mb"
  | "status";
export type GroupKey = "none" | "model" | "format" | "precision" | "device" | "dataset";

export interface View {
  search: string;
  model: string;
  format: string;
  precision: string;
  device: string;
  dataset: string;
  status: string;
  sort: { key: SortKey; dir: "asc" | "desc" };
  group: GroupKey;
}

export const ALL = "all";
export const DEFAULT_VIEW: View = {
  search: "",
  model: ALL,
  format: ALL,
  precision: ALL,
  device: ALL,
  dataset: ALL,
  status: "done",
  sort: { key: "id", dir: "desc" },
  group: "none",
};

export interface Row {
  run: RunInfo;
  model: string;
  format: string;
  precision: string;
  variant: string;
  threads: number;
  dataset: string;
  device: string;
  acc: number | undefined;
  f1: number | undefined;
  ms: number | undefined;
  mb: number | undefined;
  /** Finished, but every repeat was throttled: its speed is shown as missing and it is left out of speed rankings. */
  invalid: boolean;
}

export type Item = { kind: "group"; label: string; count: number } | { kind: "row"; row: Row };

const value = (key: string, run: RunInfo) => METRIC_BY_KEY.get(key)?.value(run);

export function rowsOf(runs: RunInfo[]): Row[] {
  return runs.map((run) => ({
    run,
    model: run.model_name ?? "a removed model",
    format: run.format,
    precision: run.precision,
    variant: run.variant_label,
    threads: run.params?.threads ?? 0,
    dataset: `${run.dataset_name ?? "removed"} v${String(run.dataset_version ?? "?")}`,
    device: run.device_name ?? "removed",
    acc: value("map50_95", run),
    f1: value("f1", run),
    ms: value("p50", run),
    mb: run.size_bytes ? run.size_bytes / 1_048_576 : undefined,
    invalid: throttled(run),
  }));
}

export const options = (
  rows: Row[],
  key: "model" | "format" | "precision" | "device" | "dataset" | "status",
) => [...new Set(rows.map((r) => (key === "status" ? r.run.status : r[key])))].sort();

const text = (r: Row) =>
  `${String(r.run.id)} ${r.model} ${r.variant} ${r.dataset} ${r.device} ${r.run.status}`.toLowerCase();

export function filter(rows: Row[], v: View): Row[] {
  const words = v.search.toLowerCase().split(/\s+/).filter(Boolean);
  return rows.filter(
    (r) =>
      (v.model === ALL || r.model === v.model) &&
      (v.format === ALL || r.format === v.format) &&
      (v.precision === ALL || r.precision === v.precision) &&
      (v.device === ALL || r.device === v.device) &&
      (v.dataset === ALL || r.dataset === v.dataset) &&
      (v.status === ALL || r.run.status === v.status) &&
      words.every((w) => text(r).includes(w)),
  );
}

const sortValue = (r: Row, key: SortKey): string | number | undefined =>
  key === "id"
    ? r.run.id
    : key === "status"
      ? r.run.status
      : key === "threads"
        ? r.threads
        : r[key];

/** Sorted by one column; a missing value always goes last, whichever way the column is sorted. */
export function sort(rows: Row[], by: View["sort"]): Row[] {
  return [...rows].sort((a, b) => {
    const x = sortValue(a, by.key);
    const y = sortValue(b, by.key);
    if (x === undefined && y === undefined) return a.run.id - b.run.id;
    if (x === undefined) return 1;
    if (y === undefined) return -1;
    const c =
      typeof x === "number" && typeof y === "number"
        ? x - y
        : String(x).localeCompare(String(y), undefined, { numeric: true });
    return (by.dir === "asc" ? c : -c) || a.run.id - b.run.id;
  });
}

/** The table as a flat list: group headings (with how many rows) and rows, in the order they are drawn. */
export function layout(rows: Row[], v: View): Item[] {
  const sorted = sort(filter(rows, v), v.sort);
  const asRow = (row: Row): Item => ({ kind: "row", row });
  if (v.group === "none") return sorted.map(asRow);
  const groups = new Map<string, Row[]>();
  for (const r of sorted) groups.set(r[v.group], [...(groups.get(r[v.group]) ?? []), r]);
  return [...groups.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .flatMap(([label, members]): Item[] => [
      { kind: "group", label, count: members.length },
      ...members.map(asRow),
    ]);
}

/** Which items to draw for a scrolled list of fixed-height rows, and the space to leave above and below (virtual scrolling). */
export function windowOf(
  total: number,
  scrollTop: number,
  viewport: number,
  rowHeight: number,
  overscan = 6,
) {
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
  const end = Math.min(total, Math.ceil((scrollTop + viewport) / rowHeight) + overscan);
  return { start, end, padTop: start * rowHeight, padBottom: Math.max(0, total - end) * rowHeight };
}

const cell = (v: string | number | undefined) => {
  const s = v === undefined ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

export function toCsv(rows: Row[]): string {
  const head = [
    "run",
    "status",
    "model",
    "format",
    "precision",
    "variant",
    "threads",
    "dataset",
    "device",
    "map50_95",
    "f1",
    "median_ms",
    "size_mb",
    "valid_for_latency",
  ];
  const lines = rows.map((r) =>
    [
      r.run.id,
      r.run.status,
      r.model,
      r.format,
      r.precision,
      r.variant,
      r.threads,
      r.dataset,
      r.device,
      r.acc?.toFixed(4),
      r.f1?.toFixed(4),
      r.ms?.toFixed(2),
      r.mb?.toFixed(2),
      r.invalid ? "no" : "yes",
    ]
      .map(cell)
      .join(","),
  );
  return [head.join(","), ...lines].join("\n") + "\n";
}
