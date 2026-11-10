import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { NewDataset } from "@/components/DatasetUpload";
import { Info } from "@/components/Info";
import { EmptyState } from "@/components/EmptyState";
import { Field } from "@/components/Field";
import { PageHeader, Section } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  datasetsKey,
  importBundle,
  useDatasets,
  useImportFolder,
  type DatasetInfo,
} from "@/lib/datasets";
import { formatBytes } from "@/lib/format";

function summary(d: DatasetInfo): string {
  if (!d.head) return d.building ? "Building the first version" : "Empty: no pictures yet";
  const h = d.head;
  const labels =
    h.labelled_count === 0
      ? "no annotations (speed only)"
      : `${String(h.instance_count)} annotated objects`;
  const versions = `${String(d.version_count)} version${d.version_count === 1 ? "" : "s"}`;
  return `${versions}, latest v${String(h.number)}: ${String(h.image_count)} pictures, ${labels}, ${formatBytes(h.size_bytes)}`;
}

/** The two other ways in: a folder on this computer, and a dataset someone shared. */
function OtherWays() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const importFolder = useImportFolder();
  const bundle = useRef<HTMLInputElement>(null);
  const [path, setPath] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function onBundle(file: File) {
    setError(null);
    try {
      const dataset = await importBundle(file, "");
      await queryClient.invalidateQueries({ queryKey: datasetsKey });
      void navigate(`/datasets/${String(dataset.id)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The import failed.");
    } finally {
      if (bundle.current) bundle.current.value = "";
    }
  }

  return (
    <div className="max-w-prose space-y-6">
      <div className="space-y-2">
        <Field
          label="Read a folder that is on this computer"
          help="The full path, for example D:\Photos\shelf. Good for thousands of photos: nothing is uploaded through the browser."
        >
          {(id, describedBy) => (
            <Input
              id={id}
              aria-describedby={describedBy}
              value={path}
              placeholder="D:\Photos\shelf"
              onChange={(e) => {
                setPath(e.target.value);
              }}
            />
          )}
        </Field>
        <Button
          variant="outline"
          disabled={!path.trim() || importFolder.isPending}
          onClick={() => {
            setError(null);
            importFolder.mutate(
              { path, name: "", datasetId: null, message: "" },
              {
                onSuccess: (dataset) => {
                  void navigate(`/datasets/${String(dataset.id)}`);
                },
                onError: (e) => {
                  setError(e.message);
                  toast.error(e.message);
                },
              },
            );
          }}
        >
          Read folder
        </Button>
      </div>
      <div className="space-y-2">
        <p className="flex items-center gap-1.5 text-sm font-medium">
          Import a dataset someone shared with you
          <Info>
            A file made by Share on another dataset's page. It brings every version with it.
          </Info>
        </p>
        <input
          ref={bundle}
          type="file"
          accept=".zip"
          className="sr-only"
          aria-label="Choose a shared dataset file"
          tabIndex={-1}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void onBundle(file);
          }}
        />
        <Button
          variant="outline"
          onClick={() => {
            bundle.current?.click();
          }}
        >
          Choose a shared dataset file
        </Button>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export default function Datasets() {
  const datasets = useDatasets();
  return (
    <>
      <PageHeader
        title="Datasets"
        hint="Collections of pictures, each with a history: every change is a version you can go back to, download or share."
      />
      <Section title="Create a dataset" id="create-dataset">
        <NewDataset />
      </Section>
      <Section title="Your datasets" id="your-datasets">
        {datasets.isPending ? (
          <div aria-busy="true" aria-label="Loading datasets" className="space-y-2">
            <Skeleton className="h-10 w-full max-w-prose" />
            <Skeleton className="h-10 w-full max-w-prose" />
          </div>
        ) : datasets.isError ? (
          <p className="text-sm">
            The list of datasets could not be loaded: {datasets.error.message}
          </p>
        ) : datasets.data.length === 0 ? (
          <EmptyState title="No datasets yet">
            Create one below from photos or a folder. Photos alone are enough to measure speed.
          </EmptyState>
        ) : (
          <ul className="max-w-prose divide-y border-y">
            {datasets.data.map((d) => (
              <li key={d.id}>
                <Link to={`/datasets/${String(d.id)}`} className="block py-3 hover:bg-accent/50">
                  <span className="font-medium">{d.name}</span>
                  <span className="block text-sm text-muted-foreground">{summary(d)}</span>
                  {d.description ? (
                    <span className="block text-xs text-muted-foreground">{d.description}</span>
                  ) : null}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Other ways to bring pictures in" id="other-ways">
        <OtherWays />
      </Section>
    </>
  );
}
