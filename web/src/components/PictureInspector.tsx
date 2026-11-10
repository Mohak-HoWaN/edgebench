import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Info } from "@/components/Info";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataset, useVersionImages } from "@/lib/datasets";
import type { ExperimentInfo } from "@/lib/experiments";
import { getJson } from "@/lib/models";
import { cn } from "@/lib/utils";

const PAGE = 18;
const COLOURS = [
  "#ef4444",
  "#f59e0b",
  "#10b981",
  "#3b82f6",
  "#a855f7",
  "#ec4899",
  "#14b8a6",
  "#eab308",
];

interface Box {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  colour: string;
  label: string;
  dashed?: boolean;
}

/** A picture with boxes over it, positioned by percentage so they follow however the picture is scaled. */
function Boxed({ src, alt, boxes }: { src: string; alt: string; boxes: Box[] }) {
  return (
    <div className="relative overflow-hidden rounded-md border bg-muted">
      <img src={src} alt={alt} loading="lazy" className="block w-full" />
      {boxes.map((b, i) => (
        <div
          key={i}
          aria-hidden
          className={cn("absolute border-2", b.dashed && "border-dashed")}
          style={{
            left: `${String(b.x1 * 100)}%`,
            top: `${String(b.y1 * 100)}%`,
            width: `${String((b.x2 - b.x1) * 100)}%`,
            height: `${String((b.y2 - b.y1) * 100)}%`,
            borderColor: b.colour,
          }}
        >
          <span
            className="absolute -top-px left-0 max-w-full -translate-y-full truncate px-1 text-[10px] leading-4 text-white"
            style={{ background: b.colour }}
          >
            {b.label}
          </span>
        </div>
      ))}
    </div>
  );
}

interface Inspection {
  image: number;
  runs: {
    run_id: number;
    model_name: string | null;
    variant_label: string;
    status: string;
    class_names: string[];
    detections: number[][] | null;
  }[];
}

/**
 * The pictures of the experiment's dataset version, on the right of the page: choose one and see, side by side, the real boxes and
 * what each run found in it. This is where "which model is better" becomes visible.
 */
export function PictureInspector({ e }: { e: ExperimentInfo }) {
  const [limit, setLimit] = useState(PAGE);
  const [picked, setPicked] = useState<number | null>(null);
  const [minConf, setMinConf] = useState(0.25);
  const datasetId = e.dataset_id ?? 0;
  const version = e.dataset_version ?? 0;
  const enabled = e.dataset_id !== null && e.dataset_version !== null;
  const images = useVersionImages(datasetId, version, enabled, limit);
  const dataset = useDataset(datasetId);
  const names = dataset.data?.versions?.find((v) => v.number === version)?.class_names ?? [];
  const runKey = (e.runs ?? []).map((r) => `${String(r.id)}${r.status}`).join();
  const inspection = useQuery({
    queryKey: ["inspect", e.id, picked, runKey],
    enabled: picked !== null,
    queryFn: ({ signal }) =>
      getJson<Inspection>(
        `/api/experiments/${String(e.id)}/inspect?image=${String(picked ?? 0)}`,
        signal,
      ),
  });
  const selected = images.data?.images.find((i) => i.index === picked);
  const src = (index: number) =>
    `/api/datasets/${String(datasetId)}/versions/${String(version)}/images/${String(index)}/file`;

  if (!enabled)
    return (
      <p className="text-sm text-muted-foreground">The dataset of this experiment was removed.</p>
    );
  return (
    <div className="space-y-6">
      <div>
        <p className="mb-2 flex items-center gap-2 text-sm font-medium">
          Pictures of {e.dataset_name} v{e.dataset_version}
          <Info>
            Choose a picture to see what each run found in it, next to the real boxes. Only
            detections above a confidence of 25% are kept for this.
          </Info>
        </p>
        {images.isPending ? (
          <Skeleton className="h-32 w-full" />
        ) : images.isError ? (
          <p className="text-sm">The pictures could not be loaded.</p>
        ) : (
          <>
            <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4 xl:grid-cols-6">
              {images.data.images.map((image) => (
                <li key={image.index}>
                  <button
                    type="button"
                    aria-pressed={picked === image.index}
                    aria-label={`Inspect picture ${String(image.index + 1)}: ${image.original}`}
                    onClick={() => {
                      setPicked(image.index);
                    }}
                    className={cn(
                      "block w-full overflow-hidden rounded-md border outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                      picked === image.index && "ring-2 ring-primary",
                    )}
                  >
                    <img
                      src={src(image.index)}
                      alt=""
                      loading="lazy"
                      className="block aspect-square w-full object-cover"
                    />
                  </button>
                </li>
              ))}
            </ul>
            {images.data.total > limit ? (
              <Button
                className="mt-3"
                size="sm"
                variant="outline"
                onClick={() => {
                  setLimit(limit + PAGE);
                }}
              >
                Show more pictures ({String(images.data.total - limit)} left)
              </Button>
            ) : null}
          </>
        )}
      </div>

      {picked !== null && selected ? (
        <div aria-live="polite">
          <div className="mb-3 flex flex-wrap items-center gap-x-6 gap-y-2">
            <p className="text-sm font-medium">
              Picture {picked + 1}:{" "}
              <span className="font-normal text-muted-foreground">{selected.original}</span>
            </p>
            <label className="flex items-center gap-2 text-sm">
              Show detections above
              <input
                type="range"
                min={0.25}
                max={0.95}
                step={0.05}
                value={minConf}
                aria-label="Confidence cut-off for the detections shown"
                onChange={(ev) => {
                  setMinConf(Number(ev.target.value));
                }}
              />
              <span className="w-10 tabular-nums">{Math.round(minConf * 100)}%</span>
            </label>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <figure className="space-y-1">
              <Boxed
                src={src(picked)}
                alt={`Picture ${String(picked + 1)} with its real boxes`}
                boxes={(selected.labels ?? []).map((l) => {
                  const [c = 0, cx = 0, cy = 0, w = 0, h = 0] = l;
                  return {
                    x1: cx - w / 2,
                    y1: cy - h / 2,
                    x2: cx + w / 2,
                    y2: cy + h / 2,
                    colour: "#22d3ee",
                    dashed: true,
                    label: names[c] ?? `class ${String(c)}`,
                  };
                })}
              />
              <figcaption className="text-xs">
                <span className="font-medium">Real boxes</span>
                <span className="block text-muted-foreground">
                  {selected.labels === null
                    ? "This picture has no annotations."
                    : `${String(selected.labels.length)} object${selected.labels.length === 1 ? "" : "s"}${
                        selected.labels.length
                          ? `: ${[...new Set(selected.labels.map((l) => names[l[0] ?? 0] ?? "?"))].join(", ")}`
                          : ""
                      }`}
                </span>
              </figcaption>
            </figure>
            {inspection.isPending ? (
              <Skeleton className="h-40 w-full" />
            ) : inspection.isError ? (
              <p className="text-sm">What the runs found could not be loaded.</p>
            ) : (
              inspection.data.runs.map((run) => {
                const found = (run.detections ?? []).filter((d) => (d[4] ?? 0) >= minConf);
                return (
                  <figure key={run.run_id} className="space-y-1">
                    <Boxed
                      src={src(picked)}
                      alt={`Picture ${String(picked + 1)} with what ${run.model_name ?? "the model"}, ${run.variant_label} found`}
                      boxes={found.map((d) => {
                        const [x1 = 0, y1 = 0, x2 = 0, y2 = 0, score = 0, c = 0] = d;
                        return {
                          x1,
                          y1,
                          x2,
                          y2,
                          colour: COLOURS[c % COLOURS.length] ?? "#ef4444",
                          label: `${run.class_names[c] ?? `class ${String(c)}`} ${String(Math.round(score * 100))}%`,
                        };
                      })}
                    />
                    <figcaption className="text-xs">
                      <span className="font-medium">
                        {run.model_name}, {run.variant_label}
                      </span>
                      <span className="block text-muted-foreground">
                        {run.detections === null
                          ? run.status === "done"
                            ? "This run did not keep its detections (it was made before pictures could be inspected)."
                            : "Waiting for this run to finish."
                          : found.length === 0
                            ? `Nothing found above ${String(Math.round(minConf * 100))}%.`
                            : `${String(found.length)} found: ${found
                                .slice(0, 5)
                                .map(
                                  (d) =>
                                    `${run.class_names[d[5] ?? 0] ?? "?"} ${String(Math.round((d[4] ?? 0) * 100))}%`,
                                )
                                .join(", ")}${found.length > 5 ? ", ..." : ""}`}
                      </span>
                    </figcaption>
                  </figure>
                );
              })
            )}
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          Choose a picture above to compare what each run found in it.
        </p>
      )}
    </div>
  );
}
