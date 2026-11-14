import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, getJson, send } from "./models";

export type RunStatus =
  "queued" | "running" | "done" | "failed" | "unavailable" | "cancelled" | "lost";

export interface RunParams {
  threads: number;
  warmup: number;
  iterations: number;
  accuracy: boolean;
  conf: number;
  iou: number;
  max_det: number;
  max_images?: number | null;
  /** Logical CPU numbers the benchmark was pinned to. */
  cpu_list?: number[] | null;
  /** Timed repeats, each with its own warm-up (ADR 0004). Absent on runs made before repeats existed. */
  repeats?: number;
  telemetry?: boolean;
}

export interface Stage {
  mean: number;
  std: number;
  min: number;
  p50: number;
  p95: number;
  p99: number;
  max: number;
}

/** What the machine did during one window of time: a repeat, or the whole run. `null` means not available, never zero. */
export interface TelemetryWindow {
  samples: number;
  cpu_mean: number | null;
  cpu_max: number | null;
  cpu_per_core_mean: number[] | null;
  rss_peak_mb: number | null;
  clock_mhz_mean: number | null;
  clock_mhz_min: number | null;
  temp_c_start: number | null;
  temp_c_max: number | null;
  throttled: boolean | null;
  gpu_util_mean: number | null;
  gpu_mem_peak_mb: number | null;
  gpu_temp_c_max: number | null;
}

export interface Repeat {
  index: number;
  stats: Stage;
  total_ms: number[];
  valid: boolean;
  invalid_reason: string | null;
  telemetry?: TelemetryWindow;
}

/** The headline latency: mean of the repeats' medians, with a 95% interval over the repeats (ADR 0004). */
export interface Latency {
  p50_ms: number;
  ci_half_width_ms: number | null;
  n: number;
  /** Fewer than five repeats: the interval is too wide to lean on. */
  wide: boolean;
  repeats: number;
  valid_repeats: number;
  /** False when every repeat was throttled: the run is shown, but its latency is not to be compared. */
  valid: boolean;
  fps: number | null;
}

export interface Accuracy {
  available: boolean;
  note?: string;
  images?: number;
  class_mapping?: string;
  unmapped_classes?: string[];
  map50?: number;
  map50_95?: number;
  precision?: number;
  recall?: number;
  f1?: number;
  mean_iou?: number;
  confidence_at_best_f1?: number;
  per_class?: Record<
    string,
    { ap50: number; ap50_95: number; instances: number; images: number; predictions: number }
  >;
  confusion?: { labels: string[]; matrix: number[][] };
}

export interface RunResult {
  runtime?: {
    kind: string;
    threads: number;
    cpus?: number[] | null;
    versions: Record<string, string>;
  };
  load_ms?: number;
  first_inference_ms?: number;
  speed?: {
    warmup: number;
    iterations: number;
    pictures_cycled: number;
    stages: Record<"preprocess" | "inference" | "postprocess" | "total", Stage>;
    repeats_requested?: number;
    repeats?: Repeat[];
    valid_repeats?: number;
    latency_valid?: boolean;
  };
  telemetry?: {
    enabled: boolean;
    hz?: number;
    /** What each reading is on this machine; null where it is not available here. */
    sources?: Record<string, string | null>;
    start_clock_mhz?: number | null;
    run?: TelemetryWindow;
  };
  environment?: {
    logical_cores: number | null;
    physical_cores: number | null;
    power_plan: string | null;
    governor: string | null;
  };
  accuracy?: Accuracy;
  dataset?: { hash: string; images: number };
  decode?: { conf: number; iou: number; max_det: number; multi_label: boolean };
  log?: string;
}

export interface RunInfo {
  id: number;
  experiment_id: number | null;
  status: RunStatus;
  model_id: number | null;
  model_name: string | null;
  variant_id: number | null;
  variant_label: string;
  runtime: string;
  dataset_id: number | null;
  dataset_name: string | null;
  dataset_version: number | null;
  device_id: number | null;
  device_name: string | null;
  device_kind: string | null;
  params: RunParams | null;
  progress: number | null;
  message: string | null;
  result: RunResult | null;
  latency: Latency | null;
  /** Recorded facts that point at the tool, not the model, when a result looks wrong. */
  diagnosis: string[];
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export const runsKey = ["runs"] as const;

export const STATUS_TEXT: Record<RunStatus, string> = {
  queued: "Waiting for the device",
  running: "Running",
  done: "Finished",
  failed: "Failed",
  unavailable: "Not available on this device",
  cancelled: "Cancelled",
  lost: "Lost: the device stopped answering",
};

const live = (r: RunInfo) => r.status === "queued" || r.status === "running";

export function useRuns() {
  return useQuery({
    queryKey: runsKey,
    queryFn: ({ signal }) => getJson<RunInfo[]>("/api/runs", signal),
    refetchInterval: (q) => (q.state.data?.some(live) ? 4000 : false),
  });
}

export function useRun(id: number) {
  return useQuery({
    queryKey: [...runsKey, id],
    queryFn: ({ signal }) => getJson<RunInfo>(`/api/runs/${String(id)}`, signal),
    refetchInterval: (q) => (q.state.data && live(q.state.data) ? 3000 : false),
    retry: (count, error) => !(error instanceof ApiError) && count < 2,
  });
}

function useRunAction<A>(run: (arg: A) => Promise<RunInfo>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: runsKey });
      await queryClient.invalidateQueries({ queryKey: ["experiments"] }); // a run is a row inside an experiment
    },
  });
}

export const useCancelRun = () =>
  useRunAction((id: number) => send<RunInfo>("POST", `/api/runs/${String(id)}/cancel`));
export const useRunAgain = () =>
  useRunAction((id: number) => send<RunInfo>("POST", `/api/runs/${String(id)}/again`));
export const useRemoveRun = () =>
  useRunAction((id: number) => send<RunInfo>("DELETE", `/api/runs/${String(id)}`));
