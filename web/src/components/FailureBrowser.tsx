import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";
import { Boxed, type Box } from "@/components/PictureInspector";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, getJson } from "@/lib/models";
import type { RunInfo } from "@/lib/runs";

interface Issue {
  kind: "missed" | "wrong" | "invented";
  truth?: string;
  answer?: string;
  score?: number;
}

interface Picture {
  index: number;
  original: string;
  severity: number;
  issues: Issue[];
  truth: { name: string; box: number[] }[];
  found: { name: string; box: number[]; score: number }[];
}

interface Failures {
  checked: number;
  with_problems: number;
  totals: { missed: number; wrong: number; invented: number };
  pictures: Picture[];
}

const PAGE = 12;
const REAL = "#0ea5e9";
const FOUND = "#ef4444";

const say = (i: Issue) =>
  i.kind === "missed"
    ? `Missed: ${i.truth ?? ""}`
    : i.kind === "wrong"
      ? `${i.truth ?? ""} named as ${i.answer ?? ""} (${String(Math.round((i.score ?? 0) * 100))}% sure)`
      : `Made up: ${i.answer ?? ""} (${String(Math.round((i.score ?? 0) * 100))}% sure)`;

/**
 * The pictures a run gets wrong, worst first: an object it missed, named wrongly, or made up. The real boxes are dashed blue, what
 * the model found is red. Tick pictures and take them as a folder for the next round of annotation (the pictures, the real labels,
 * the model's answers as starting labels, and a list of what went wrong in each).
 */
export function FailureBrowser({ run }: { run: RunInfo }) {
  const [shown, setShown] = useState(PAGE);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const data = useQuery({
    queryKey: ["failures", run.id],
    queryFn: ({ signal }) =>
      getJson<Failures>(`/api/runs/${String(run.id)}/failures?limit=200`, signal),
    retry: (count, error) => !(error instanceof ApiError) && count < 2,
  });
  if (data.isPending)
    return (
      <Skeleton aria-busy="true" aria-label="Looking for mistakes" className="h-24 max-w-prose" />
    );
  if (data.isError)
    return <p className="max-w-prose text-sm text-muted-foreground">{data.error.message}</p>;
  const { checked, with_problems: bad, totals, pictures } = data.data;
  if (bad === 0)
    return (
      <p className="max-w-prose text-sm">
        None of the {String(checked)} annotated pictures has a missed, wrongly named or made-up
        object at confidence 0.25.
      </p>
    );
  const toggle = (index: number) => {
    const next = new Set(picked);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    setPicked(next);
  };
  const pictureUrl = (index: number) =>
    `/api/datasets/${String(run.dataset_id)}/versions/${String(run.dataset_version)}/images/${String(index)}/file`;
  const boxes = (p: Picture): Box[] => [
    ...p.truth.map((t) => ({
      x1: t.box[0] ?? 0,
      y1: t.box[1] ?? 0,
      x2: t.box[2] ?? 0,
      y2: t.box[3] ?? 0,
      colour: REAL,
      label: `real: ${t.name}`,
      dashed: true,
    })),
    ...p.found.map((f) => ({
      x1: f.box[0] ?? 0,
      y1: f.box[1] ?? 0,
      x2: f.box[2] ?? 0,
      y2: f.box[3] ?? 0,
      colour: FOUND,
      label: `${f.name} ${String(Math.round(f.score * 100))}%`,
    })),
  ];
  const chosen = [...picked].sort((a, b) => a - b);
  return (
    <div>
      <p className="max-w-prose text-sm" aria-live="polite">
        {String(bad)} of {String(checked)} annotated pictures have a problem:{" "}
        {String(totals.missed)} object{totals.missed === 1 ? "" : "s"} missed,{" "}
        {String(totals.wrong)} named wrongly, {String(totals.invented)} made up. The worst come
        first.
      </p>
      <div className="my-3 flex flex-wrap items-center gap-3">
        <Button
          size="xs"
          variant="outline"
          onClick={() => {
            setPicked(new Set(pictures.slice(0, shown).map((p) => p.index)));
          }}
        >
          Select the {String(Math.min(shown, pictures.length))} shown
        </Button>
        <Button
          size="xs"
          variant="outline"
          disabled={picked.size === 0}
          onClick={() => {
            setPicked(new Set());
          }}
        >
          Clear selection
        </Button>
        {chosen.length > 0 ? (
          <a
            className={buttonVariants({ size: "xs" })}
            href={`/api/runs/${String(run.id)}/failures.zip?images=${chosen.join(",")}`}
            download
          >
            <Download aria-hidden />
            Take {String(chosen.length)} picture{chosen.length === 1 ? "" : "s"} as a folder for
            annotation
          </a>
        ) : null}
        <span className="text-xs text-muted-foreground">
          Dashed blue: the real boxes. Red: what the model found.
        </span>
      </div>
      <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-label="Pictures with mistakes">
        {pictures.slice(0, shown).map((p) => (
          <li key={p.index} className="rounded-lg border p-2">
            <Boxed
              src={pictureUrl(p.index)}
              alt={`${p.original} with the real boxes and what the model found`}
              boxes={boxes(p)}
            />
            <label className="mt-2 flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-1"
                checked={picked.has(p.index)}
                onChange={() => {
                  toggle(p.index);
                }}
              />
              <span>
                <span className="font-medium">{p.original}</span>
                <span className="block text-xs text-muted-foreground">
                  {p.issues.map(say).join("; ")}
                </span>
              </span>
            </label>
          </li>
        ))}
      </ul>
      {shown < pictures.length ? (
        <Button
          className="mt-3"
          size="sm"
          variant="outline"
          onClick={() => {
            setShown(shown + PAGE);
          }}
        >
          Show {String(Math.min(PAGE, pictures.length - shown))} more
        </Button>
      ) : null}
    </div>
  );
}
