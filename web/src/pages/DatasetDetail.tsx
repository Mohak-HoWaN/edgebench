import { Download, GitCommitVertical, Loader2, RotateCcw, Share2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { useConfirm } from "@/components/ConfirmProvider";
import { AddPictures } from "@/components/DatasetUpload";
import { EmptyState } from "@/components/EmptyState";
import { Field } from "@/components/Field";
import { PageHeader, Section } from "@/components/PageHeader";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useArchiveDataset,
  useChooseCalibration,
  useDataset,
  useDiscardVersion,
  useEditDataset,
  useRestoreVersion,
  useVersionImages,
  type DatasetInfo,
  type PreviewImage,
  type VersionInfo,
} from "@/lib/datasets";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

const PAGE = 24;
const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

/** A picture with its ground-truth boxes drawn over it (boxes are relative, so one SVG fits any picture size). */
function Preview({
  datasetId,
  version,
  image,
  names,
}: {
  datasetId: number;
  version: number;
  image: PreviewImage;
  names: string[];
}) {
  const boxes = image.labels ?? [];
  const classes = [...new Set(boxes.map((b) => names[b[0] ?? 0] ?? "?"))];
  return (
    <figure className="space-y-1">
      <div className="relative overflow-hidden rounded-md border bg-muted">
        <img
          src={`/api/datasets/${String(datasetId)}/versions/${String(version)}/images/${String(image.index)}/file`}
          alt={`${image.original}: ${
            image.labels === null
              ? "no annotations"
              : `${String(boxes.length)} annotated object${boxes.length === 1 ? "" : "s"}`
          }`}
          loading="lazy"
          className="block w-full"
        />
        <svg
          viewBox="0 0 1 1"
          preserveAspectRatio="none"
          aria-hidden
          className="absolute inset-0 size-full"
        >
          {boxes.map((b, i) => {
            const [, cx = 0, cy = 0, w = 0, h = 0] = b;
            return (
              <rect
                key={i}
                x={cx - w / 2}
                y={cy - h / 2}
                width={w}
                height={h}
                fill="none"
                stroke="#22d3ee"
                strokeWidth={2}
                vectorEffect="non-scaling-stroke"
              />
            );
          })}
        </svg>
      </div>
      <figcaption className="truncate text-xs text-muted-foreground" title={image.original}>
        {image.source}
        {classes.length
          ? `: ${classes.slice(0, 3).join(", ")}${classes.length > 3 ? "..." : ""}`
          : ""}
      </figcaption>
    </figure>
  );
}

function Previews({ d, v }: { d: DatasetInfo; v: VersionInfo }) {
  const [limit, setLimit] = useState(PAGE);
  const images = useVersionImages(d.id, v.number, v.status === "ready", limit);
  if (images.isPending) return <Skeleton className="h-40 w-full max-w-3xl" />;
  if (images.isError) return <p className="text-sm">The pictures could not be loaded.</p>;
  return (
    <>
      <ul className="grid max-w-5xl grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {images.data.images.map((image) => (
          <li key={image.index}>
            <Preview
              datasetId={d.id}
              version={v.number}
              image={image}
              names={v.class_names ?? []}
            />
          </li>
        ))}
      </ul>
      {images.data.total > limit ? (
        <Button
          className="mt-4"
          size="sm"
          variant="outline"
          onClick={() => {
            setLimit(limit + PAGE);
          }}
        >
          Show more ({String(images.data.total - limit)} left)
        </Button>
      ) : null}
    </>
  );
}

function ChangeSummary({ v }: { v: VersionInfo }) {
  const c = v.changes;
  if (!c) return <span className="text-muted-foreground">changes not recorded</span>;
  return (
    <span className="tabular-nums">
      <span className="text-ok">+{String(c.added)}</span>{" "}
      <span className="text-destructive">-{String(c.removed)}</span>{" "}
      <span className="text-warn">~{String(c.modified)}</span>
      <span className="sr-only"> files added, removed and changed</span>
    </span>
  );
}

function History({ d, selected }: { d: DatasetInfo; selected: number }) {
  const confirm = useConfirm();
  const restore = useRestoreVersion();
  const discard = useDiscardVersion();
  const [, setParams] = useSearchParams();
  const versions = d.versions ?? [];

  const onRestore = async (v: VersionInfo) => {
    const ok = await confirm({
      title: `Restore version ${String(v.number)}?`,
      body: `A new version is made with exactly the files of version ${String(v.number)}. Nothing is deleted: the versions after it stay in the history.`,
      confirmLabel: "Restore",
    });
    if (!ok) return;
    restore.mutate(
      { id: d.id, version: v.number },
      {
        onSuccess: () => {
          toast.success(`Restoring version ${String(v.number)} as a new version`);
          setParams({});
        },
        onError: (e) => {
          toast.error(e.message);
        },
      },
    );
  };

  return (
    <ol className="max-w-3xl divide-y border-y" aria-label="Versions, newest first">
      {versions.map((v) => (
        <li key={v.id} className={cn("py-3", v.number === selected && "bg-accent/40")}>
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-2">
            <GitCommitVertical aria-hidden className="size-4 self-center text-muted-foreground" />
            <button
              type="button"
              className="font-medium underline-offset-4 hover:underline"
              aria-current={v.number === selected ? "true" : undefined}
              onClick={() => {
                setParams(v.is_head ? {} : { v: String(v.number) });
              }}
            >
              v{v.number}
              <span className="sr-only">: {v.message || "no message"}</span>
            </button>
            <span className="min-w-0 flex-1 truncate text-sm" aria-hidden>
              {v.message || "No message"}
            </span>
            {v.is_head ? <span className="rounded border px-1.5 text-xs">latest</span> : null}
            <span className="text-xs text-muted-foreground">{when(v.created_at)}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 px-2 pl-8 text-sm text-muted-foreground">
            {v.status === "building" ? (
              <span className="flex items-center gap-1.5" role="status">
                <Loader2 aria-hidden className="size-3.5 animate-spin" />
                Building
              </span>
            ) : v.status === "failed" ? (
              <span className="text-destructive" role="alert">
                Failed: {v.error}
              </span>
            ) : (
              <>
                <span className="tabular-nums">{String(v.image_count)} pictures</span>
                <ChangeSummary v={v} />
              </>
            )}
          </div>
          {v.status !== "building" ? (
            <div className="mt-2 flex flex-wrap gap-2 px-2 pl-8">
              {v.status === "ready" ? (
                <>
                  {v.has_files ? (
                    <a
                      href={`/api/datasets/${String(d.id)}/versions/${String(v.number)}/download?kind=files`}
                      download
                      className={buttonVariants({ size: "xs", variant: "outline" })}
                    >
                      <Download aria-hidden />
                      Download
                      <span className="sr-only"> files of version {v.number}</span>
                    </a>
                  ) : null}
                  <a
                    href={`/api/datasets/${String(d.id)}/versions/${String(v.number)}/download?kind=normalised`}
                    download
                    className={buttonVariants({ size: "xs", variant: "outline" })}
                    title="The copy the benchmark agents read: upright, at most 1920 px, labels as relative boxes"
                  >
                    <Download aria-hidden />
                    Normalised
                    <span className="sr-only"> copy of version {v.number}</span>
                  </a>
                  {!v.is_head && v.has_files ? (
                    <Button
                      size="xs"
                      variant="outline"
                      disabled={restore.isPending}
                      onClick={() => {
                        void onRestore(v);
                      }}
                    >
                      <RotateCcw aria-hidden />
                      Restore
                      <span className="sr-only"> version {v.number}</span>
                    </Button>
                  ) : null}
                  <Link
                    to={`/experiments/new?dataset=${String(d.id)}&version=${String(v.number)}`}
                    className={buttonVariants({ size: "xs", variant: "outline" })}
                  >
                    Use in an experiment
                    <span className="sr-only"> (version {v.number})</span>
                  </Link>
                </>
              ) : (
                <Button
                  size="xs"
                  variant="outline"
                  disabled={discard.isPending}
                  onClick={() => {
                    discard.mutate(
                      { id: d.id, version: v.number },
                      {
                        onError: (e) => {
                          toast.error(e.message);
                        },
                      },
                    );
                  }}
                >
                  Discard
                  <span className="sr-only"> failed version {v.number}</span>
                </Button>
              )}
            </div>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

function VersionDetail({ d, v }: { d: DatasetInfo; v: VersionInfo }) {
  const calibrate = useChooseCalibration();
  const stats = v.stats;
  const names = v.class_names ?? [];
  if (v.status !== "ready" || !stats) return null;
  return (
    <>
      {stats.warnings.map((w) => (
        <p key={w} className="mb-2 max-w-prose text-sm text-muted-foreground">
          {w}
        </p>
      ))}
      {v.changes && (v.changes.added || v.changes.removed || v.changes.modified) ? (
        <details className="mb-4 max-w-prose text-sm">
          <summary className="cursor-pointer">
            What changed in v{v.number}: {v.changes.added} added, {v.changes.removed} removed,{" "}
            {v.changes.modified} changed
          </summary>
          <ul className="mt-2 space-y-1 break-all text-muted-foreground">
            {v.changes.added_paths.map((p) => (
              <li key={`a${p}`}>+ {p}</li>
            ))}
            {v.changes.removed_paths.map((p) => (
              <li key={`r${p}`}>- {p}</li>
            ))}
            {v.changes.modified_paths.map((p) => (
              <li key={`m${p}`}>~ {p}</li>
            ))}
            {v.changes.added + v.changes.removed + v.changes.modified >
            v.changes.added_paths.length +
              v.changes.removed_paths.length +
              v.changes.modified_paths.length ? (
              <li>and more</li>
            ) : null}
          </ul>
        </details>
      ) : null}

      <Section
        title="Capture sources"
        hint="Set from a sources.csv, a folder named rpi-cam3-wide or mobile, or the camera model in the picture. Anything else is listed as other."
      >
        <table className="w-full max-w-prose text-left text-sm">
          <caption className="sr-only">Pictures and annotated objects per capture source</caption>
          <thead>
            <tr className="border-b">
              <th scope="col" className="py-2 pr-4 font-medium">
                Source
              </th>
              <th scope="col" className="py-2 pr-4 text-right font-medium">
                Pictures
              </th>
              <th scope="col" className="py-2 pr-4 text-right font-medium">
                Annotated pictures
              </th>
              <th scope="col" className="py-2 text-right font-medium">
                Objects
              </th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(stats.sources)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([source, s]) => (
                <tr key={source} className="border-b tabular-nums">
                  <th scope="row" className="py-2 pr-4 text-left font-normal">
                    {source}
                  </th>
                  <td className="py-2 pr-4 text-right">{s.images}</td>
                  <td className="py-2 pr-4 text-right">{s.labelled}</td>
                  <td className="py-2 text-right">{s.instances}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </Section>

      <Section title={`Classes (${String(names.length)})`}>
        {v.names_generic ? (
          <p className="mb-3 max-w-prose text-sm text-warn">
            The files had no class names, so these are placeholders. Results are matched to a model
            by position, not by name.
          </p>
        ) : null}
        {v.labelled_count === 0 ? (
          <p className="text-sm text-muted-foreground">
            No annotations, so accuracy will show "n/a (no labels)". Speed runs work normally.
          </p>
        ) : (
          <details className="max-w-prose text-sm">
            <summary className="cursor-pointer">
              {String(v.instance_count)} annotated objects across {String(names.length)} classes
            </summary>
            <table className="mt-3 w-full text-left">
              <caption className="sr-only">Annotated objects per class</caption>
              <thead>
                <tr className="border-b">
                  <th scope="col" className="py-1 pr-4 font-medium">
                    Class
                  </th>
                  <th scope="col" className="py-1 text-right font-medium">
                    Objects
                  </th>
                </tr>
              </thead>
              <tbody>
                {names.map((name, i) => (
                  <tr key={i} className="tabular-nums">
                    <th scope="row" className="py-1 pr-4 text-left font-normal">
                      {name}
                    </th>
                    <td className="py-1 text-right">{stats.class_counts[i] ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}
      </Section>

      <Section
        title="Resolution"
        hint="Sizes of the original pictures. Pictures are rotated upright and capped at 1920 px on the long side once, when a version is built."
      >
        <ul className="max-w-prose text-sm">
          {Object.entries(stats.resolution.buckets).map(([bucket, n]) => (
            <li key={bucket} className="flex justify-between border-b py-1 tabular-nums">
              <span>{bucket}</span>
              <span>{n} pictures</span>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-sm">
          Most common original sizes:{" "}
          {stats.resolution.sizes
            .slice(0, 4)
            .map((s) => `${String(s.width)} x ${String(s.height)} (${String(s.count)})`)
            .join(", ")}
        </p>
      </Section>

      <Section
        title="Calibration subset"
        hint="The pictures used to calibrate a quantized model: a seeded sample that mixes capture sources, at least 50 and by default 200. The exact list is recorded."
      >
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button
            size="sm"
            variant="outline"
            disabled={calibrate.isPending}
            onClick={() => {
              calibrate.mutate(
                { id: d.id, version: v.number, count: 200, seed: (v.calibration?.seed ?? -1) + 1 },
                {
                  onError: (e) => {
                    toast.error(e.message);
                  },
                },
              );
            }}
          >
            {v.calibration ? "Choose another sample" : "Choose a sample"}
          </Button>
          <p className="text-sm" role="status">
            {v.calibration
              ? `${String(v.calibration.count)} pictures chosen (seed ${String(v.calibration.seed)}).`
              : v.image_count < 50
                ? "This version has fewer than 50 pictures, so it cannot be used for calibration."
                : "No sample chosen yet."}
          </p>
        </div>
      </Section>

      <Section title={`Pictures in v${String(v.number)}`}>
        <Previews d={d} v={v} />
      </Section>
    </>
  );
}

function Rename({ d, onClose }: { d: DatasetInfo; onClose: () => void }) {
  const edit = useEditDataset();
  const [name, setName] = useState(d.name);
  const [description, setDescription] = useState(d.description);
  return (
    <form
      className="mb-6 grid max-w-prose gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        edit.mutate(
          { id: d.id, name: name.trim(), description: description.trim() },
          {
            onSuccess: onClose,
            onError: (err) => {
              toast.error(err.message);
            },
          },
        );
      }}
    >
      <Field label="Name">
        {(id) => (
          <Input
            id={id}
            required
            value={name}
            maxLength={120}
            onChange={(e) => {
              setName(e.target.value);
            }}
          />
        )}
      </Field>
      <Field label="Description">
        {(id) => (
          <Input
            id={id}
            value={description}
            maxLength={2000}
            onChange={(e) => {
              setDescription(e.target.value);
            }}
          />
        )}
      </Field>
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={!name.trim() || edit.isPending}>
          Save
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

export default function DatasetDetail() {
  const id = Number(useParams().id);
  const dataset = useDataset(id);
  const confirm = useConfirm();
  const navigate = useNavigate();
  const archive = useArchiveDataset();
  const [params, setParams] = useSearchParams();
  const [renaming, setRenaming] = useState(false);

  if (archive.isPending || archive.isSuccess) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Removing the dataset.
      </p>
    );
  }
  if (dataset.isPending) {
    return (
      <div aria-busy="true" aria-label="Loading dataset" className="space-y-3">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full max-w-4xl" />
      </div>
    );
  }
  if (dataset.isError) {
    return (
      <>
        <PageHeader title="Dataset not found" />
        <EmptyState
          title="That dataset is not here"
          action={{ label: "Go to datasets", to: "/datasets" }}
        >
          {dataset.error.message}
        </EmptyState>
      </>
    );
  }

  const d = dataset.data;
  const versions = d.versions ?? [];
  const wanted = Number(params.get("v"));
  const shown = versions.find((v) => v.number === wanted) ?? d.head ?? versions[0];
  const onArchive = async () => {
    const ok = await confirm({
      title: `Remove ${d.name}?`,
      body: "It disappears from your datasets. Runs that already used it keep their results.",
      confirmLabel: "Remove dataset",
      destructive: true,
    });
    if (!ok) return;
    archive.mutate(d.id, {
      onSuccess: () => {
        toast.success(`${d.name} was removed`);
        void navigate("/datasets");
      },
      onError: (e) => {
        toast.error(e.message);
      },
    });
  };

  return (
    <>
      <p className="mb-2 text-sm">
        <Link to="/datasets" className="text-primary underline-offset-4 hover:underline">
          Datasets
        </Link>
      </p>
      <PageHeader title={d.name}>
        {d.description ||
          (d.head
            ? `${String(d.version_count)} version${d.version_count === 1 ? "" : "s"}, latest v${String(d.head.number)} with ${String(d.head.image_count)} pictures`
            : "No pictures yet")}
      </PageHeader>

      <div className="-mt-4 mb-6 flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            setRenaming(!renaming);
          }}
        >
          Edit name and description
        </Button>
        {d.head ? (
          <a
            href={`/api/datasets/${String(d.id)}/export`}
            download
            className={buttonVariants({ size: "sm", variant: "outline" })}
            title="One file with every version and its pictures, to give to someone else or keep as a backup"
          >
            <Share2 aria-hidden />
            Share (all versions)
          </a>
        ) : null}
      </div>
      {renaming ? (
        <Rename
          d={d}
          onClose={() => {
            setRenaming(false);
          }}
        />
      ) : null}

      <Section title="Add or change pictures">
        <details open={versions.length === 0} className="max-w-prose">
          <summary className="cursor-pointer text-sm">
            {versions.length === 0
              ? "Choose the first pictures"
              : "Add pictures, annotations or replace files"}
          </summary>
          <div className="mt-4">
            <AddPictures
              datasetId={d.id}
              onDone={() => {
                setParams({});
              }}
            />
          </div>
        </details>
      </Section>

      <Section title="History">
        {versions.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nothing here yet. Each time you save pictures, a version appears.
          </p>
        ) : (
          <History d={d} selected={shown?.number ?? 0} />
        )}
      </Section>

      {shown ? <VersionDetail d={d} v={shown} /> : null}

      <Section title="Details">
        <dl className="grid max-w-prose grid-cols-[10rem_1fr] gap-y-2 text-sm">
          {shown ? (
            <>
              <dt className="text-muted-foreground">Showing</dt>
              <dd>version {shown.number}</dd>
              <dt className="text-muted-foreground">Size on disk</dt>
              <dd className="tabular-nums">{formatBytes(shown.size_bytes)}</dd>
              <dt className="text-muted-foreground">Read from</dt>
              <dd className="break-all">{shown.source_path ?? "uploaded files"}</dd>
              <dt className="text-muted-foreground">Fingerprint</dt>
              <dd className="tabular-nums" title={shown.dataset_hash ?? undefined}>
                {shown.dataset_hash?.slice(0, 16) ?? "not yet"}
              </dd>
            </>
          ) : null}
          <dt className="text-muted-foreground">Created</dt>
          <dd>{when(d.created_at)}</dd>
        </dl>
        <Button
          className="mt-4"
          size="sm"
          variant="destructive"
          disabled={archive.isPending}
          onClick={() => {
            void onArchive();
          }}
        >
          Remove dataset
        </Button>
      </Section>
    </>
  );
}
