import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export type VariantState =
  "pending" | "converting" | "ready" | "failed" | "unavailable" | "cancelled";
export type ModelStatus = "inspecting" | "ready" | "converter_missing" | "rejected";

export interface Verify {
  ok: boolean;
  max_abs_diff?: number;
  relative?: number;
  tolerance?: number;
  /** Set when the comparison with PyTorch could not be made (its output had another shape, or the check crashed). */
  error?: string;
}

export interface Variant {
  id: number;
  op: string;
  format: string;
  precision: string;
  /** The input size this conversion was built for. */
  imgsz: number;
  /** Settings that change the output (the ONNX export's `simplify`). */
  settings: Record<string, unknown>;
  state: VariantState;
  mismatch: boolean;
  cached: boolean;
  size_bytes: number | null;
  seconds: number | null;
  verify: Verify | null;
  error: string | null;
  has_log: boolean;
  updated_at: string;
}

export interface ModelInfo {
  id: number;
  name: string;
  filename: string;
  size_bytes: number;
  status: ModelStatus;
  error: string | null;
  task: string | null;
  imgsz: number | null;
  parameters: number | null;
  gflops: number | null;
  class_names: string[] | null;
  sha256: string | null;
  created_at: string;
  variant_counts: Partial<Record<VariantState, number>>;
  variants: Variant[] | null;
}

export interface ConverterInfo {
  available: boolean;
  message: string | null;
  python: string | null;
  versions: Record<string, string>;
  missing: string[];
}

/** An error whose message is already fit to show to a person (the server writes them that way). */
export class ApiError extends Error {}

export async function failure(res: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    detail = ((await res.json()) as { detail?: unknown }).detail;
  } catch {
    detail = undefined;
  }
  return new ApiError(
    typeof detail === "string"
      ? detail
      : `The server answered ${String(res.status)} ${res.statusText}`,
  );
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(path, { signal });
  if (!res.ok) throw await failure(res);
  return (await res.json()) as T;
}

export async function send<T>(
  method: "POST" | "DELETE" | "PATCH",
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(
    path,
    body === undefined
      ? { method }
      : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
  );
  if (!res.ok) throw await failure(res);
  return (res.status === 204 ? undefined : await res.json()) as T;
}

/** Upload with progress (fetch cannot report upload progress). Resolves with the model and whether it already existed. */
export function uploadModel(
  file: File,
  onProgress: (fraction: number) => void,
): Promise<{ model: ModelInfo; existing: boolean }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/models");
    xhr.setRequestHeader("X-Filename", encodeURIComponent(file.name));
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onerror = () => {
      reject(new ApiError("Could not reach the server. Check that it is running and try again."));
    };
    xhr.onload = () => {
      let body: unknown;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = undefined;
      }
      if (xhr.status === 200 || xhr.status === 201) {
        resolve({ model: body as ModelInfo, existing: xhr.status === 200 });
        return;
      }
      const detail = (body as { detail?: unknown } | undefined)?.detail;
      reject(
        new ApiError(
          typeof detail === "string" ? detail : `The server answered ${String(xhr.status)}`,
        ),
      );
    };
    xhr.send(file);
  });
}

const active = (m: ModelInfo) =>
  m.status === "inspecting" ||
  (m.variant_counts.converting ?? 0) + (m.variant_counts.pending ?? 0) > 0;

/** One line that says where a model stands. */
export function progressText(m: ModelInfo): string {
  if (m.status === "inspecting") return "Reading the model";
  if (m.status === "rejected") return "Could not be read";
  if (m.status === "converter_missing") return "Waiting for the converter";
  const c = m.variant_counts;
  const total = Object.values(c).reduce((a, b) => a + b, 0);
  const parts = [`${String(c.ready ?? 0)} of ${String(total)} converted`];
  if (c.failed) parts.push(`${String(c.failed)} failed`);
  if (c.unavailable) parts.push(`${String(c.unavailable)} not available`);
  return parts.join(", ");
}

export const modelsKey = ["models"] as const;

export function useModels() {
  return useQuery({
    queryKey: modelsKey,
    queryFn: ({ signal }) => getJson<ModelInfo[]>("/api/models", signal),
    // Live events refresh this; polling is only a safety net while something is in progress.
    refetchInterval: (q) => (q.state.data?.some(active) ? 4000 : false),
  });
}

export function useModel(id: number, enabled = true) {
  return useQuery({
    queryKey: [...modelsKey, id],
    enabled,
    queryFn: ({ signal }) => getJson<ModelInfo>(`/api/models/${String(id)}`, signal),
    refetchInterval: (q) => (q.state.data && active(q.state.data) ? 4000 : false),
    retry: (count, error) => !(error instanceof ApiError) && count < 2,
  });
}

export function useConverter() {
  return useQuery({
    queryKey: ["converter"],
    queryFn: ({ signal }) => getJson<ConverterInfo>("/api/converter", signal),
    staleTime: 60_000,
  });
}

export function useVariantLog(id: number | null, polling: boolean) {
  return useQuery({
    queryKey: ["variant-log", id],
    enabled: id !== null,
    queryFn: async ({ signal }) => {
      const res = await fetch(`/api/variants/${String(id)}/log`, { signal });
      if (!res.ok) throw await failure(res);
      return res.text();
    },
    refetchInterval: polling ? 1500 : false,
  });
}

/** A mutation that refreshes every model view when it finishes. */
function useModelAction<A>(run: (arg: A) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: () => queryClient.invalidateQueries({ queryKey: modelsKey }),
  });
}

export const useConvertMissing = () =>
  useModelAction((id: number) => send("POST", `/api/models/${String(id)}/convert`));
export const useReread = () =>
  useModelAction((id: number) => send("POST", `/api/models/${String(id)}/inspect`));
export const useArchive = () =>
  useModelAction((id: number) => send("DELETE", `/api/models/${String(id)}`));
export const useRetry = () =>
  useModelAction((id: number) => send("POST", `/api/variants/${String(id)}/retry`));
export const useCancel = () =>
  useModelAction((id: number) => send("POST", `/api/variants/${String(id)}/cancel`));

export const useAddVariant = () =>
  useModelAction((a: { id: number; op: string; imgsz: number; simplify: boolean }) =>
    send<ModelInfo>("POST", `/api/models/${String(a.id)}/variants`, {
      op: a.op,
      imgsz: a.imgsz,
      simplify: a.simplify,
    }),
  );
