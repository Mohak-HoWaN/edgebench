import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { limitsQuery, useDriftLimits } from "./drift";
import { ApiError, getJson, send } from "./models";
import { runsKey, type RunInfo, type RunParams } from "./runs";

export type ExperimentStatus = "running" | "done" | "partly";

/** A converted run against the PyTorch baseline at the same settings: the speed-up, and Welch's test on the repeats. */
export interface Comparison {
  vs_run_id: number;
  speedup: number | null;
  p: number | null;
  t: number | null;
  /** null: no test could be made (fewer than two valid repeats on a side, or a side was throttled). */
  significant: boolean | null;
  note?: string;
}

/** How far a converted run drifted from the PyTorch baseline, and whether that passes the person's limits. */
export interface Drift {
  baseline_run_id: number;
  agreement_available: boolean;
  map50_delta: number | null;
  map50_95_delta: number | null;
  per_class_ap50_delta: Record<string, number> | null;
  baseline_detections?: number;
  variant_detections?: number;
  matched?: number;
  missed?: number;
  class_flips?: number;
  /** How well the variant's boxes agree with the baseline's, 0 to 1; 0 for a model that finds nothing. */
  mean_box_iou?: number | null;
  verdict: { passed: boolean; reasons: string[] };
}

export interface ExperimentInfo {
  id: number;
  name: string;
  notes: string;
  created_at: string;
  dataset_id: number | null;
  dataset_name: string | null;
  dataset_version: number | null;
  device_id: number | null;
  device_name: string | null;
  params: RunParams | null;
  status: ExperimentStatus;
  counts: Record<string, number>;
  models: string[];
  /** Some runs were cancelled or lost and the experiment remembers what it was asked to run. */
  resumable: boolean;
  comparisons: Record<string, Comparison>;
  drift: Record<string, Drift>;
  runs: RunInfo[] | null;
}

export const experimentsKey = ["experiments"] as const;

export const STATUS_WORDS: Record<ExperimentStatus, string> = {
  running: "Running",
  done: "Finished",
  partly: "Finished, some runs did not complete",
};

/** The limits in force, as the query string the server needs; part of the cache key so changing them refetches. */
function useLimitsQuery() {
  const maxMapDropPoints = useDriftLimits((s) => s.maxMapDropPoints);
  const minAgreement = useDriftLimits((s) => s.minAgreement);
  return limitsQuery({ maxMapDropPoints, minAgreement });
}

export function useExperiments() {
  const limits = useLimitsQuery();
  return useQuery({
    queryKey: [...experimentsKey, "list", limits],
    queryFn: ({ signal }) => getJson<ExperimentInfo[]>(`/api/experiments?${limits}`, signal),
    refetchInterval: (q) => (q.state.data?.some((e) => e.status === "running") ? 4000 : false),
  });
}

export function useExperiment(id: number, enabled = true) {
  const limits = useLimitsQuery();
  return useQuery({
    queryKey: [...experimentsKey, id, limits],
    enabled,
    queryFn: ({ signal }) =>
      getJson<ExperimentInfo>(`/api/experiments/${String(id)}?${limits}`, signal),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 3000 : false),
    retry: (count, error) => !(error instanceof ApiError) && count < 2,
  });
}

function useExperimentAction<A, R>(run: (arg: A) => Promise<R>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: experimentsKey });
      await queryClient.invalidateQueries({ queryKey: runsKey });
    },
  });
}

/** Axes to vary. An empty axis means "as the base settings say"; the runs are every combination of the axes. */
export interface Sweep {
  threads: number[];
  cpu_sets: number[][];
  imgsz: number[];
}

export interface NewExperiment {
  name: string;
  notes: string;
  dataset_id: number;
  dataset_version: number | null;
  device_id: number;
  params: RunParams;
  items: { model_id: number; variant_id: number | null }[];
  sweep: Sweep;
}

export interface PlanInfo {
  runs: {
    label: string;
    threads: number;
    cpu_list: number[] | null;
    imgsz: number;
    estimated_seconds: number;
    /** Nothing on this device has been measured for this conversion, so its time is a guess. */
    guessed: boolean;
  }[];
  pruned: {
    label: string;
    threads: number;
    cpu_list: number[] | null;
    imgsz: number;
    reason: string;
  }[];
  run_count: number;
  estimated_seconds: number;
  guessed_runs: number;
  images: number;
  repeats: number;
}

/** What the experiment would run and how long it should take, worked out by the server without starting anything. */
export function usePlan(body: NewExperiment | null) {
  return useQuery({
    queryKey: [...experimentsKey, "plan", JSON.stringify(body)],
    enabled: body !== null,
    queryFn: () => send<PlanInfo>("POST", "/api/experiments/plan", body),
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 10_000,
  });
}

export const useStartExperiment = () =>
  useExperimentAction((body: NewExperiment) =>
    send<ExperimentInfo>("POST", "/api/experiments", body),
  );
export const useCancelExperiment = () =>
  useExperimentAction((id: number) =>
    send<ExperimentInfo>("POST", `/api/experiments/${String(id)}/cancel`),
  );
export const useResumeExperiment = () =>
  useExperimentAction((id: number) =>
    send<ExperimentInfo>("POST", `/api/experiments/${String(id)}/resume`),
  );
export const useRemoveExperiment = () =>
  useExperimentAction((id: number) => send("DELETE", `/api/experiments/${String(id)}`));
