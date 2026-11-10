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
