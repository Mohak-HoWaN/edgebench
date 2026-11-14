// Runs built to look like what the server returns, with only the parts a chart needs. Used by the comparison tests.
import type { RunInfo } from "../../src/lib/runs.ts";

export interface O {
  model?: number;
  format?: string;
  precision?: string;
  threads?: number;
  device?: number;
  version?: number;
  ms?: number | null;
  ci?: number;
  map?: number;
  recall?: number;
  instances?: number;
  size?: number;
  classes?: Record<string, number>;
  samples?: number[];
  stages?: [number, number, number];
  curves?: boolean;
  hist?: number[];
  sources?: Record<string, number>;
  series?: { temp: (number | null)[]; clock: (number | null)[]; throttled?: boolean[] };
  confusion?: { labels: string[]; matrix: number[][] };
  diagnosis?: string[];
  status?: string;
}

let next = 1;
export const resetIds = () => {
  next = 1;
};
export const NAMES: Record<number, string> = { 1: "Old", 2: "New", 3: "Third", 4: "Fourth" };
export function run(o: O = {}): RunInfo {
  const format = o.format ?? "ONNX";
  const precision = o.precision ?? "FP32";
  const per: Record<string, unknown> = {};
  for (const [n, ap] of Object.entries(o.classes ?? { chips: o.map ?? 0.5 }))
    per[n] = { ap50: ap, ap50_95: ap, instances: o.instances ?? 30, images: 5, predictions: 9 };
  const curve = (f: (k: number) => number) => Array.from({ length: 51 }, (_, k) => f(k / 50));
  return {
    id: next++,
    status: o.status ?? "done",
    model_id: o.model ?? 1,
    model_name: NAMES[o.model ?? 1],
    format,
    precision,
    variant_label: `${format} ${precision}`,
    size_bytes: o.size ?? null,
    imgsz: 640,
    dataset_id: 1,
    dataset_name: "shelf",
    dataset_version: o.version ?? 1,
    device_id: o.device ?? 1,
    device_name: o.device === 2 ? "Pi" : "PC",
    params: { threads: o.threads ?? 1 },
    diagnosis: o.diagnosis ?? [],
    latency:
      o.ms === undefined || o.ms === null
        ? null
        : {
            p50_ms: o.ms,
            ci_half_width_ms: o.ci ?? 1,
            n: 3,
            wide: false,
            repeats: 3,
            valid_repeats: 3,
            valid: true,
            fps: null,
          },
    result: {
      // a run without timings has no speed block at all, as one made without a speed pass
      speed:
        o.ms == null && !o.samples && !o.stages
          ? undefined
          : {
              stages: {
                preprocess: { mean: o.stages?.[0] ?? 1 },
                inference: { mean: o.stages?.[1] ?? 5 },
                postprocess: { mean: o.stages?.[2] ?? 1 },
                total: { mean: 0, p50: o.ms ?? 0 },
              },
              total_ms: o.samples,
              repeats: o.samples ? [{ index: 0, valid: true, total_ms: o.samples }] : undefined,
            },
      accuracy: {
        available: o.map !== undefined,
        map50_95: o.map,
        recall: o.recall ?? 0.9,
        per_class: per,
        confusion: o.confusion,
        score_hist: o.hist,
        by_source:
          o.sources &&
          Object.fromEntries(
            Object.entries(o.sources).map(([k, v]) => [
              k,
              { images: 4, instances: 8, map50: v, map50_95: v, precision: v, recall: v },
            ]),
          ),
        curves: o.curves
          ? {
              conf: curve((x) => x),
              all: {
                precision: curve((x) => 0.5 + x / 2),
                recall: curve((x) => 1 - x),
                f1: curve((x) => 1 - Math.abs(x - 0.5)),
              },
              per_class: {
                chips: {
                  precision: curve(() => 0.9),
                  recall: curve((x) => 1 - x),
                  f1: curve(() => 0.8),
                },
              },
            }
          : undefined,
      },
      telemetry: o.series
        ? {
            enabled: true,
            series: {
              t: o.series.temp.map((_, k) => k),
              temp_c: o.series.temp,
              clock_mhz: o.series.clock,
              cpu: o.series.temp.map(() => 10),
              throttled: o.series.throttled ?? o.series.temp.map(() => false),
              repeats: [{ start: 0, end: o.series.temp.length, valid: true }],
            },
          }
        : undefined,
    },
  } as unknown as RunInfo;
}
