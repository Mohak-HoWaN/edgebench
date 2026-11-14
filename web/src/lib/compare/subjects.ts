// What is being compared: runs, each with a stable identity on the charts. Pure (no browser), so e2e/compare.spec.ts calls it directly.
import type { RunInfo } from "../runs.ts";

export const MAX_RUNS = 12;
/** Colour tells the models apart, and only three colours pass the colour-blind check against each other (dataviz). */
export const MAX_MODELS = 3;

export type Shape = "circle" | "diamond" | "square" | "triangle" | "hexagon";
export type Fill = "solid" | "soft" | "hollow";

export interface Subject {
  run: RunInfo;
  /** 0 to 2: which model colour (series-1 to series-3), in the order the models were first picked. */
  color: number;
  /** The format: ONNX is a circle, OpenVINO a diamond, ncnn a square, TorchScript a triangle, the .pt a hexagon. */
  shape: Shape;
  /** The precision: FP32 solid, FP16 soft, INT8 hollow. */
  fill: Fill;
  modelName: string;
  /** "ONNX FP32 · 1 thread" */
  label: string;
  /** "v_0.0.1.3_, ONNX FP32, 1 thread" */
  long: string;
  /** "v_0.0.1.3_ · ONNX FP32 · 1 thread": a chart category, one line per part. */
  cat: string;
}

const SHAPE: Record<string, Shape> = {
  ONNX: "circle",
  OpenVINO: "diamond",
  ncnn: "square",
  TorchScript: "triangle",
  PyTorch: "hexagon",
};
const FILL: Record<string, Fill> = { FP32: "solid", FP16: "soft", INT8: "hollow" };

export function threadsText(r: RunInfo): string {
  const threads = r.params?.threads;
  const cpus = r.params?.cpu_list;
  const t =
    threads === undefined
      ? "unknown threads"
      : `${String(threads)} thread${threads === 1 ? "" : "s"}`;
  return cpus?.length ? `${t}, CPUs ${cpus.join(",")}` : t;
}

export function subjectsOf(runs: RunInfo[], ids: number[]): Subject[] {
  const byId = new Map(runs.map((r) => [r.id, r]));
  const colours = new Map<number, number>();
  const out: Subject[] = [];
  for (const id of ids) {
    const run = byId.get(id);
    if (!run) continue;
    if (run.model_id === null || out.some((s) => s.run.id === id)) continue;
    if (!colours.has(run.model_id)) {
      if (colours.size >= MAX_MODELS) continue;
      colours.set(run.model_id, colours.size);
    }
    const modelName = run.model_name ?? "a removed model";
    out.push({
      run,
      color: colours.get(run.model_id) ?? 0,
      shape: SHAPE[run.format] ?? "circle",
      fill: FILL[run.precision] ?? "solid",
      modelName,
      label: `${run.variant_label} · ${threadsText(run)}`,
      long: `${modelName}, ${run.variant_label}, ${threadsText(run)}`,
      cat: `${modelName} · ${run.variant_label} · ${threadsText(run)}`,
    });
  }
  return out;
}

/** Why a run cannot be added to what is selected, or null when it can (or is already in, which removes it). */
export function cannotAdd(selected: Subject[], run: RunInfo): string | null {
  if (selected.some((s) => s.run.id === run.id)) return null;
  if (selected.length >= MAX_RUNS) return `Up to ${String(MAX_RUNS)} runs at once.`;
  const models = new Set(selected.map((s) => s.run.model_id));
  if (!models.has(run.model_id) && models.size >= MAX_MODELS)
    return `Up to ${String(MAX_MODELS)} models at once: the colour is what tells them apart.`;
  return null;
}

const dataset = (r: RunInfo) =>
  `${r.dataset_name ?? "a removed dataset"} v${String(r.dataset_version ?? "?")}`;

/** What differs between the selected runs besides what you chose to compare: it limits what the numbers can say. */
export function notesFor(subjects: Subject[]): string[] {
  const out: string[] = [];
  const runs = subjects.map((s) => s.run);
  const datasets = [...new Set(runs.map(dataset))];
  if (datasets.length > 1)
    out.push(
      `These runs used different datasets (${datasets.join(", ")}): their accuracy numbers do not measure the same thing.`,
    );
  const devices = [...new Set(runs.map((r) => r.device_name ?? "a removed device"))];
  if (devices.length > 1)
    out.push(
      `These runs were made on different devices (${devices.join(", ")}): compare their speed only between runs on the same device, or on the device chart.`,
    );
  const settings = [...new Set(runs.map(threadsText))];
  if (settings.length > 1)
    out.push(
      `The runs used different thread settings (${settings.join("; ")}): a speed difference may come from the setting, not the variant.`,
    );
  for (const s of subjects)
    for (const d of s.run.diagnosis) out.push(`Run ${String(s.run.id)} (${s.long}): ${d}`);
  return out;
}

export interface Suggestion {
  id: string;
  kind: "models" | "variants" | "threads" | "devices";
  title: string;
  detail: string;
  runIds: number[];
}

const where = (r: RunInfo) => `${dataset(r)} on ${r.device_name ?? "a removed device"}`;

/**
 * Comparisons the data allows, so nobody has to hunt for runs that go together: the same variant across models, every variant
 * of one model, a thread sweep, the same run on several devices. Each takes the newest run of each member.
 */
export function suggestions(runs: RunInfo[]): Suggestion[] {
  const done = runs.filter((r) => r.status === "done" && r.model_id !== null);
  const place = (r: RunInfo) =>
    `${String(r.dataset_id)}:${String(r.dataset_version)}:${String(r.device_id)}`;
  const names = (rs: RunInfo[]) => rs.map((r) => r.model_name ?? "a removed model");
  const modelName = (r: RunInfo) => r.model_name ?? "model";
  const firstModels = (rs: RunInfo[]) => {
    const seen = new Set<number | null>();
    return rs.filter(
      (r) => seen.has(r.model_id) || (seen.size < MAX_MODELS && (seen.add(r.model_id), true)),
    );
  };
  const make = (
    kind: Suggestion["kind"],
    groupKey: (r: RunInfo) => string,
    member: (r: RunInfo) => string,
    title: (first: RunInfo, members: RunInfo[]) => string,
    detail: (r: RunInfo) => string,
    limit: (members: RunInfo[]) => RunInfo[],
  ): Suggestion[] => {
    const groups = new Map<string, Map<string, RunInfo>>();
    for (const r of done) {
      const g = groups.get(groupKey(r)) ?? new Map<string, RunInfo>();
      const have = g.get(member(r));
      if (!have || r.id > have.id) g.set(member(r), r);
      groups.set(groupKey(r), g);
    }
    return [...groups.entries()]
      .flatMap(([key, g]) => {
        const members = limit([...g.values()].sort((a, b) => a.id - b.id));
        const [first] = members;
        return first && members.length >= 2
          ? [
              {
                id: `${kind}:${key}`,
                kind,
                title: title(first, members),
                detail: detail(first),
                runIds: members.slice(0, MAX_RUNS).map((r) => r.id),
              },
            ]
          : [];
      })
      .sort(
        (a, b) =>
          b.runIds.length - a.runIds.length || Math.max(...b.runIds) - Math.max(...a.runIds),
      )
      .slice(0, 5);
  };
  return [
    ...make(
      "models",
      (r) => `${r.variant_label}|${threadsText(r)}|${place(r)}`,
      (r) => String(r.model_id),
      (f, m) => `${f.variant_label}, ${threadsText(f)}: ${names(m).join(" against ")}`,
      where,
      firstModels,
    ),
    ...make(
      "variants",
      (r) => `${String(r.model_id)}|${threadsText(r)}|${place(r)}`,
      (r) => r.variant_label,
      (f, m) => `${modelName(f)}: ${String(m.length)} variants at ${threadsText(f)}`,
      where,
      (rs) => rs,
    ),
    ...make(
      "threads",
      (r) => `${String(r.model_id)}|${r.variant_label}|${place(r)}`,
      threadsText,
      (f, m) => `${modelName(f)}, ${f.variant_label}: ${m.map(threadsText).join(" / ")}`,
      where,
      (rs) => rs,
    ),
    ...make(
      "devices",
      (r) =>
        `${String(r.model_id)}|${r.variant_label}|${threadsText(r)}|${String(r.dataset_id)}:${String(r.dataset_version)}`,
      (r) => String(r.device_id),
      (f, m) =>
        `${modelName(f)}, ${f.variant_label}: ${m.map((r) => r.device_name ?? "a removed device").join(" against ")}`,
      dataset,
      (rs) => rs,
    ),
  ];
}
