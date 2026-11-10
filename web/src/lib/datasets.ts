import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, getJson, send } from "./models";

export type VersionStatus = "building" | "ready" | "failed";

export interface SourceStats {
  images: number;
  labelled: number;
  instances: number;
  class_counts: number[];
}

export interface DatasetStats {
  class_counts: number[];
  sources: Record<string, SourceStats>;
  resolution: {
    buckets: Record<string, number>;
    sizes: { width: number; height: number; count: number }[];
  };
  warnings: string[];
}

export interface Changes {
  added: number;
  removed: number;
  modified: number;
  added_paths: string[];
  removed_paths: string[];
  modified_paths: string[];
}

export interface Calibration {
  seed: number;
  count: number;
  files?: string[];
}

export interface VersionInfo {
  id: number;
  number: number;
  message: string;
  created_at: string;
  status: VersionStatus;
  error: string | null;
  is_head: boolean;
  /** False for a version made before versions existed: its original files were not kept. */
  has_files: boolean;
  format: string | null;
  image_count: number;
  labelled_count: number;
  instance_count: number;
  class_names: string[] | null;
  names_generic: boolean;
  dataset_hash: string | null;
  size_bytes: number;
  stats: DatasetStats | null;
  calibration: Calibration | null;
  changes: Changes | null;
  source_path: string | null;
}

export interface DatasetInfo {
  id: number;
  name: string;
  description: string;
  created_at: string;
  version_count: number;
  building: boolean;
  head: VersionInfo | null;
  versions: VersionInfo[] | null;
}

export interface PreviewImage {
  index: number;
  original: string;
  width: number;
  height: number;
  source: string;
  labels: number[][] | null;
}

export const datasetsKey = ["datasets"] as const;

export function useDatasets() {
  return useQuery({
    queryKey: datasetsKey,
    queryFn: ({ signal }) => getJson<DatasetInfo[]>("/api/datasets", signal),
    refetchInterval: (q) => (q.state.data?.some((d) => d.building) ? 3000 : false),
  });
}

export function useDataset(id: number) {
  return useQuery({
    queryKey: [...datasetsKey, id],
    queryFn: ({ signal }) => getJson<DatasetInfo>(`/api/datasets/${String(id)}`, signal),
    refetchInterval: (q) => (q.state.data?.building ? 2000 : false),
    retry: (count, error) => !(error instanceof ApiError) && count < 2,
  });
}

export function useVersionImages(
  id: number,
  version: number | "head",
  enabled: boolean,
  limit: number,
) {
  return useQuery({
    queryKey: [...datasetsKey, id, "images", version, limit],
    enabled,
    queryFn: ({ signal }) =>
      getJson<{ total: number; images: PreviewImage[] }>(
        `/api/datasets/${String(id)}/versions/${String(version)}/images?offset=0&limit=${String(limit)}`,
        signal,
      ),
  });
}

export function useDatasetAction<A, R = unknown>(run: (arg: A) => Promise<R>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: () => queryClient.invalidateQueries({ queryKey: datasetsKey }),
  });
}

export const useCreateDataset = () =>
  useDatasetAction((a: { name: string; description: string }) =>
    send<DatasetInfo>("POST", "/api/datasets", a),
  );
export const useEditDataset = () =>
  useDatasetAction((a: { id: number; name?: string; description?: string }) =>
    send<DatasetInfo>("PATCH", `/api/datasets/${String(a.id)}`, {
      name: a.name,
      description: a.description,
    }),
  );
export const useArchiveDataset = () =>
  useDatasetAction((id: number) => send("DELETE", `/api/datasets/${String(id)}`));
export const useRestoreVersion = () =>
  useDatasetAction((a: { id: number; version: number }) =>
    send<VersionInfo>(
      "POST",
      `/api/datasets/${String(a.id)}/versions/${String(a.version)}/restore`,
    ),
  );
export const useDiscardVersion = () =>
  useDatasetAction((a: { id: number; version: number }) =>
    send("DELETE", `/api/datasets/${String(a.id)}/versions/${String(a.version)}`),
  );
export const useChooseCalibration = () =>
  useDatasetAction((a: { id: number; version: number; count: number; seed: number }) =>
    send<VersionInfo>(
      "POST",
      `/api/datasets/${String(a.id)}/versions/${String(a.version)}/calibration`,
      { count: a.count, seed: a.seed },
    ),
  );
export const useImportFolder = () =>
  useDatasetAction((a: { path: string; name: string; datasetId: number | null; message: string }) =>
    send<DatasetInfo>("POST", "/api/datasets/from-folder", {
      path: a.path,
      name: a.name || null,
      dataset_id: a.datasetId,
      message: a.message,
    }),
  );

/** One file to add: where it goes inside the dataset, and the file. */
export interface Picked {
  path: string;
  file: File;
}

/** Upload one file as the raw request body (fetch cannot report byte progress, so progress is counted in files). */
async function uploadOne(
  datasetId: number,
  item: Picked,
): Promise<{ path: string; sha256: string }> {
  const res = await fetch(`/api/datasets/${String(datasetId)}/blobs`, {
    method: "POST",
    headers: { "X-Path": encodeURIComponent(item.path) },
    body: item.file,
  });
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail;
    } catch {
      detail = undefined;
    }
    throw new ApiError(
      typeof detail === "string"
        ? detail
        : `${item.path}: the server answered ${String(res.status)}`,
    );
  }
  return (await res.json()) as { path: string; sha256: string };
}

/**
 * Upload every picked file (three at a time), then commit them as the next version. Nothing changes in the dataset until the
 * commit, so a failed upload leaves it as it was.
 */
export async function commitFiles(
  datasetId: number,
  picked: Picked[],
  message: string,
  onProgress: (done: number, total: number) => void,
  modelId: number | null = null,
): Promise<VersionInfo> {
  const uploaded: { path: string; sha256: string }[] = new Array<{ path: string; sha256: string }>(
    picked.length,
  );
  let next = 0;
  let done = 0;
  const worker = async () => {
    while (next < picked.length) {
      const index = next++;
      const item = picked[index];
      if (!item) continue;
      uploaded[index] = await uploadOne(datasetId, item);
      onProgress(++done, picked.length);
    }
  };
  await Promise.all([worker(), worker(), worker()]);
  return send<VersionInfo>("POST", `/api/datasets/${String(datasetId)}/commit`, {
    message,
    add: uploaded,
    model_id: modelId,
  });
}

export async function importBundle(file: File, name: string): Promise<DatasetInfo> {
  const query = name ? `?name=${encodeURIComponent(name)}` : "";
  const res = await fetch(`/api/datasets/import-bundle${query}`, {
    method: "POST",
    headers: { "X-Filename": encodeURIComponent(file.name) },
    body: file,
  });
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail;
    } catch {
      detail = undefined;
    }
    throw new ApiError(
      typeof detail === "string" ? detail : `The server answered ${String(res.status)}`,
    );
  }
  return (await res.json()) as DatasetInfo;
}

const IMAGE = /\.(jpe?g|png|bmp|webp)$/i;

/** What a pick contains, in words a person can check before uploading. */
export function describePick(picked: Picked[]): {
  pictures: number;
  labels: number;
  zips: number;
  ndjson: number;
  annotated: boolean;
  names: boolean;
} {
  const count = (re: RegExp) => picked.filter((p) => re.test(p.path)).length;
  const labels =
    picked.filter(
      (p) =>
        /\.(txt|xml)$/i.test(p.path) && !/(^|\/)(classes|labels|obj)\.(txt|names)$/i.test(p.path),
    ).length + picked.filter((p) => /\.json$/i.test(p.path)).length;
  return {
    pictures: count(IMAGE),
    labels,
    zips: count(/\.zip$/i),
    ndjson: count(/\.(ndjson|jsonl)$/i),
    annotated: labels > 0 || count(/\.(ndjson|jsonl)$/i) > 0,
    names: picked.some((p) =>
      /(^|\/)(data|dataset)\.ya?ml$|(^|\/)(classes|obj)\.(txt|names)$/i.test(p.path),
    ),
  };
}

/** Paths from a folder pick carry the folder's own name first; drop it when every file shares it. */
export function pathsFromFiles(files: File[]): Picked[] {
  const rel = files.map((f) => ({ file: f, path: f.webkitRelativePath || f.name }));
  const firsts = new Set(rel.map((r) => r.path.split("/")[0]));
  const strip = firsts.size === 1 && rel.every((r) => r.path.includes("/"));
  return rel.map((r) => ({
    file: r.file,
    path: strip ? r.path.split("/").slice(1).join("/") : r.path,
  }));
}

type Entry = FileSystemEntry & { file?: (ok: (f: File) => void, no: (e: unknown) => void) => void };

/** Everything dropped on the page: files, and folders walked recursively. */
export async function collectDropped(items: DataTransferItemList): Promise<Picked[]> {
  const out: Picked[] = [];
  const walk = async (entry: Entry, prefix: string): Promise<void> => {
    if (entry.isFile) {
      const file = await new Promise<File>((ok, no) => {
        entry.file?.(ok, no);
      });
      out.push({ file, path: prefix + entry.name });
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      for (;;) {
        const batch = await new Promise<FileSystemEntry[]>((ok, no) => {
          reader.readEntries(ok, no);
        });
        if (batch.length === 0) break;
        for (const child of batch) await walk(child, `${prefix}${entry.name}/`);
      }
    }
  };
  const entries = [...items]
    .map((i) => i.webkitGetAsEntry())
    .filter((e): e is FileSystemEntry => e !== null);
  for (const entry of entries) await walk(entry, "");
  const roots = new Set(entries.filter((e) => e.isDirectory).map((e) => e.name));
  // a single dropped folder: its own name is not part of the dataset's paths
  if (entries.length === 1 && roots.size === 1) {
    const root = `${[...roots][0] ?? ""}/`;
    return out.map((p) => ({
      ...p,
      path: p.path.startsWith(root) ? p.path.slice(root.length) : p.path,
    }));
  }
  return out;
}
