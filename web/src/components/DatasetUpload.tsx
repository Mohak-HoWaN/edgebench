import { useQueryClient } from "@tanstack/react-query";
import { FolderUp, ImagePlus, X } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Field } from "@/components/Field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  collectDropped,
  commitFiles,
  datasetsKey,
  describePick,
  pathsFromFiles,
  useCreateDataset,
  type Picked,
} from "@/lib/datasets";
import { useModels } from "@/lib/models";
import { cn } from "@/lib/utils";

const ACCEPT = "image/*,.txt,.json,.ndjson,.jsonl,.xml,.yaml,.yml,.csv,.names,.zip";

/** Merge new picks into the old ones; a later pick of the same path replaces the earlier one. */
const merge = (old: Picked[], extra: Picked[]): Picked[] => [
  ...old.filter((o) => !extra.some((e) => e.path === o.path)),
  ...extra,
];

/**
 * Choose photos, a whole folder, or drop either on the box. Annotations are optional: label files that sit among the photos are
 * picked up (YOLO .txt with a data.yaml, COCO .json, Pascal VOC .xml); photos alone give a dataset for speed runs.
 */
export function FilePicker({
  picked,
  onChange,
  disabled,
}: {
  picked: Picked[];
  onChange: (next: Picked[]) => void;
  disabled?: boolean;
}) {
  const photos = useRef<HTMLInputElement>(null);
  const folder = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const info = describePick(picked);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (disabled) return;
    void collectDropped(e.dataTransfer.items).then((dropped) => {
      onChange(merge(picked, dropped));
    });
  };

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => {
          setDragging(false);
        }}
        onDrop={onDrop}
        className={cn(
          "flex flex-col items-start gap-3 rounded-lg border border-dashed p-5 transition-colors",
          dragging ? "border-primary bg-accent" : "border-input",
        )}
      >
        <p className="text-sm">
          Drop photos or a whole folder here, or choose them. Photos are enough; annotation files
          among them are picked up automatically.
        </p>
        <input
          ref={photos}
          type="file"
          multiple
          accept={ACCEPT}
          className="sr-only"
          aria-label="Choose photos or files"
          tabIndex={-1}
          onChange={(e) => {
            onChange(
              merge(
                picked,
                pathsFromFiles([...(e.target.files ?? [])]).map((p) => ({
                  ...p,
                  path: p.file.name,
                })),
              ),
            );
            e.target.value = "";
          }}
        />
        <input
          ref={folder}
          type="file"
          multiple
          className="sr-only"
          aria-label="Choose a folder of photos"
          tabIndex={-1}
          {...({ webkitdirectory: "" } as object)}
          onChange={(e) => {
            onChange(merge(picked, pathsFromFiles([...(e.target.files ?? [])])));
            e.target.value = "";
          }}
        />
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            disabled={disabled}
            onClick={() => {
              photos.current?.click();
            }}
          >
            <ImagePlus aria-hidden />
            Choose photos
          </Button>
          <Button
            variant="outline"
            disabled={disabled}
            onClick={() => {
              folder.current?.click();
            }}
          >
            <FolderUp aria-hidden />
            Choose a folder
          </Button>
        </div>
      </div>

      {picked.length > 0 ? (
        <div className="max-w-prose text-sm" role="status">
          <p className="flex flex-wrap items-center gap-x-3">
            <span>
              {String(picked.length)} file{picked.length === 1 ? "" : "s"} chosen:{" "}
              {String(info.pictures)} picture{info.pictures === 1 ? "" : "s"}
              {info.labels > 0
                ? `, ${String(info.labels)} annotation file${info.labels === 1 ? "" : "s"}`
                : ""}
              {info.zips > 0 ? `, ${String(info.zips)} zip` : ""}
              {info.ndjson > 0 ? `, ${String(info.ndjson)} NDJSON file` : ""}.
            </span>
            <Button
              size="xs"
              variant="ghost"
              disabled={disabled}
              onClick={() => {
                onChange([]);
              }}
            >
              <X aria-hidden />
              Clear
            </Button>
          </p>
          {info.pictures > 0 && !info.annotated && info.zips === 0 ? (
            <p className="mt-1 text-muted-foreground">
              No annotations among them. That is fine: this dataset will measure speed only.
              Accuracy needs YOLO .txt files (with a data.yaml), a COCO .json file or Pascal VOC
              .xml files; you can add them in a later version.
            </p>
          ) : null}
          {info.ndjson > 0 ? (
            <p className="mt-1 text-muted-foreground">
              An NDJSON file lists the pictures and their boxes. Pictures you chose along with it
              are matched by file name; any others are fetched from the addresses in the file
              (public addresses only).
            </p>
          ) : null}
          {info.annotated && !info.names && info.ndjson === 0 ? (
            <p className="mt-1 text-muted-foreground">
              No data.yaml or class list found. Class names will be placeholders unless you take
              them from a model below.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** Which model's class names to use when the files carry none. */
function useClassNameSource() {
  const models = useModels();
  const named = (models.data ?? []).filter((m) => m.class_names !== null);
  const [modelId, setModelId] = useState<number | null>(null);
  return { named, modelId, setModelId };
}

function ClassNameChoice({ named, modelId, setModelId }: ReturnType<typeof useClassNameSource>) {
  if (named.length === 0) return null;
  return (
    <Field
      label="Class names from a model (optional)"
      help="Only used when the files have no data.yaml or class list. The labels' class numbers must follow that model's order."
    >
      {(id, describedBy) => (
        <select
          id={id}
          aria-describedby={describedBy}
          className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm dark:bg-input/30"
          value={modelId ?? ""}
          onChange={(e) => {
            setModelId(e.target.value ? Number(e.target.value) : null);
          }}
        >
          <option value="">None</option>
          {named.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      )}
    </Field>
  );
}

function Progress({ done, total, label }: { done: number; total: number; label: string }) {
  return (
    <div>
      <progress className="h-2 w-full max-w-prose" value={done} max={total} aria-label={label} />
      <p className="mt-1 text-xs text-muted-foreground" role="status">
        {done < total
          ? `Uploading ${String(done)} of ${String(total)} files`
          : "Building the new version"}
      </p>
    </div>
  );
}

/** Add pictures (or change them) in an existing dataset: this becomes the next version. */
export function AddPictures({
  datasetId,
  onDone,
}: {
  datasetId: number;
  onDone: (version: number) => void;
}) {
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState<Picked[]>([]);
  const [message, setMessage] = useState("");
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const names = useClassNameSource();

  async function commit() {
    setError(null);
    setProgress({ done: 0, total: picked.length });
    try {
      const version = await commitFiles(
        datasetId,
        picked,
        message.trim(),
        (done, total) => {
          setProgress({ done, total });
        },
        names.modelId,
      );
      setPicked([]);
      setMessage("");
      await queryClient.invalidateQueries({ queryKey: datasetsKey });
      onDone(version.number);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The upload failed.");
    } finally {
      setProgress(null);
    }
  }

  return (
    <div className="max-w-prose space-y-4">
      <FilePicker picked={picked} onChange={setPicked} disabled={progress !== null} />
      <ClassNameChoice {...names} />
      <Field
        label="Describe this change"
        help="Like a commit message. Optional; it shows in the history."
      >
        {(id, describedBy) => (
          <Input
            id={id}
            aria-describedby={describedBy}
            value={message}
            maxLength={300}
            placeholder="Add the Tuesday evening photos"
            onChange={(e) => {
              setMessage(e.target.value);
            }}
          />
        )}
      </Field>
      <Button disabled={picked.length === 0 || progress !== null} onClick={() => void commit()}>
        Save as a new version
      </Button>
      {progress ? <Progress {...progress} label="Upload progress" /> : null}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** Make a dataset and its first version in one go. */
export function NewDataset() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const create = useCreateDataset();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [picked, setPicked] = useState<Picked[]>([]);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const names = useClassNameSource();

  async function submit() {
    setError(null);
    setProgress({ done: 0, total: picked.length });
    let created: { id: number } | null = null;
    try {
      created = await create.mutateAsync({
        name: name.trim(),
        description: description.trim(),
      });
      await commitFiles(
        created.id,
        picked,
        "First pictures",
        (done, total) => {
          setProgress({ done, total });
        },
        names.modelId,
      );
      await queryClient.invalidateQueries({ queryKey: datasetsKey });
      void navigate(`/datasets/${String(created.id)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The upload failed.");
      // the dataset exists but is empty; its page lets you try again without making another
      if (created) void navigate(`/datasets/${String(created.id)}`);
    } finally {
      setProgress(null);
    }
  }

  return (
    <form
      className="max-w-prose space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Dataset name">
          {(id) => (
            <Input
              id={id}
              required
              maxLength={120}
              value={name}
              placeholder="Shop shelf, evening light"
              onChange={(e) => {
                setName(e.target.value);
              }}
            />
          )}
        </Field>
        <Field label="Description (optional)">
          {(id) => (
            <Input
              id={id}
              maxLength={2000}
              value={description}
              onChange={(e) => {
                setDescription(e.target.value);
              }}
            />
          )}
        </Field>
      </div>
      <FilePicker picked={picked} onChange={setPicked} disabled={progress !== null} />
      <ClassNameChoice {...names} />
      <Button type="submit" disabled={!name.trim() || picked.length === 0 || progress !== null}>
        Create dataset
      </Button>
      {progress ? <Progress {...progress} label="Upload progress" /> : null}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </form>
  );
}
