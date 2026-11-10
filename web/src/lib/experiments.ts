import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, getJson, send } from "./models";
import { runsKey, type RunInfo, type RunParams } from "./runs";

export type ExperimentStatus = "running" | "done" | "partly";

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
  runs: RunInfo[] | null;
}

export const experimentsKey = ["experiments"] as const;

export const STATUS_WORDS: Record<ExperimentStatus, string> = {
  running: "Running",
  done: "Finished",
  partly: "Finished, some runs did not complete",
};

export function useExperiments() {
  return useQuery({
    queryKey: experimentsKey,
    queryFn: ({ signal }) => getJson<ExperimentInfo[]>("/api/experiments", signal),
    refetchInterval: (q) => (q.state.data?.some((e) => e.status === "running") ? 4000 : false),
  });
}

export function useExperiment(id: number, enabled = true) {
  return useQuery({
    queryKey: [...experimentsKey, id],
    enabled,
    queryFn: ({ signal }) => getJson<ExperimentInfo>(`/api/experiments/${String(id)}`, signal),
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

export interface NewExperiment {
  name: string;
  notes: string;
  dataset_id: number;
  dataset_version: number | null;
  device_id: number;
  params: RunParams;
  items: { model_id: number; variant_id: number | null }[];
}

export const useStartExperiment = () =>
  useExperimentAction((body: NewExperiment) =>
    send<ExperimentInfo>("POST", "/api/experiments", body),
  );
export const useCancelExperiment = () =>
  useExperimentAction((id: number) =>
    send<ExperimentInfo>("POST", `/api/experiments/${String(id)}/cancel`),
  );
export const useRemoveExperiment = () =>
  useExperimentAction((id: number) => send("DELETE", `/api/experiments/${String(id)}`));
