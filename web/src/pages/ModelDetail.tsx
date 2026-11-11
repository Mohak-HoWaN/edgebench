import { Download, Loader2 } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { useConfirm } from "@/components/ConfirmProvider";
import { AddInt8 } from "@/components/AddInt8";
import { AddVariant } from "@/components/AddVariant";
import { ConverterBanner } from "@/components/ConverterBanner";
import { EmptyState } from "@/components/EmptyState";
import { ModelMatrix } from "@/components/ModelMatrix";
import { PageHeader, Section } from "@/components/PageHeader";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatBytes, formatCount } from "@/lib/format";
import { useArchive, useConvertMissing, useModel, useReread } from "@/lib/models";

export default function ModelDetail() {
  const id = Number(useParams().id);
  const model = useModel(id);
  const confirm = useConfirm();
  const navigate = useNavigate();
  const archive = useArchive();
  const convertMissing = useConvertMissing();
  const reread = useReread();

  // Once removal starts the model is gone from the server: refetching it would answer 404 and flash an error before we leave.
  if (archive.isPending || archive.isSuccess) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Removing the model.
      </p>
    );
  }
  if (model.isPending) {
    return (
      <div aria-busy="true" aria-label="Loading model" className="space-y-3">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full max-w-4xl" />
      </div>
    );
  }
  if (model.isError) {
    return (
      <>
        <PageHeader title="Model not found" />
        <EmptyState
          title="That model is not here"
          action={{ label: "Go to models", to: "/models" }}
        >
          {model.error.message}
        </EmptyState>
      </>
    );
  }

  const m = model.data;
  const variants = m.variants ?? [];
  const notReady = variants.filter((v) => v.state !== "ready").length;
  const busy = variants.some((v) => v.state === "pending" || v.state === "converting");
  const facts = [
    m.task,
    m.imgsz ? `${String(m.imgsz)} px input` : null,
    m.parameters ? `${formatCount(m.parameters)} parameters` : null,
    m.gflops ? `${String(m.gflops)} GFLOPs` : null,
    m.class_names ? `${String(m.class_names.length)} classes` : null,
  ].filter(Boolean);

  const onArchive = async () => {
    const ok = await confirm({
      title: `Remove ${m.name}?`,
      body: "It disappears from your models and its waiting conversions are stopped. The files stay on disk, so uploading the same file again brings its finished conversions straight back.",
      confirmLabel: "Remove model",
      destructive: true,
    });
    if (!ok) return;
    archive.mutate(m.id, {
      onSuccess: () => {
        toast.success(`${m.name} was removed`);
        void navigate("/models");
      },
      onError: (e) => {
        toast.error(e.message);
      },
    });
  };

  return (
    <>
      <p className="mb-2 text-sm">
        <Link to="/models" className="text-primary underline-offset-4 hover:underline">
          Models
        </Link>
      </p>
      <PageHeader title={m.name}>{facts.join(", ") || m.filename}</PageHeader>

      {m.status === "inspecting" ? (
        <p role="status" className="mb-6 flex items-center gap-2 text-sm">
          <Loader2 aria-hidden className="size-4 animate-spin" />
          Reading the model. Its conversions start as soon as that is done.
        </p>
      ) : null}
      {m.status === "rejected" ? (
        <p role="alert" className="mb-6 max-w-prose border-l-2 border-destructive pl-4 text-sm">
          {m.error}
        </p>
      ) : null}
      {m.status === "converter_missing" ? (
        <div className="mb-6">
          <ConverterBanner />
          <Button
            variant="outline"
            size="sm"
            disabled={reread.isPending}
            onClick={() => {
              reread.mutate(m.id, {
                onError: (e) => {
                  toast.error(e.message);
                },
              });
            }}
          >
            Read the model again
          </Button>
        </div>
      ) : null}

      {m.status === "ready" ? (
        <Section
          title="Conversions"
          hint="These are the same model in different formats and precisions, not separate models. Each can be downloaded: ONNX and TorchScript as one file, OpenVINO and ncnn as a zip because they are several files that belong together."
        >
          <ModelMatrix model={m} />
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button
              size="sm"
              variant="outline"
              disabled={notReady === 0 || busy || convertMissing.isPending}
              onClick={() => {
                convertMissing.mutate(m.id, {
                  onError: (e) => {
                    toast.error(e.message);
                  },
                });
              }}
            >
              Convert what is missing
            </Button>
            {notReady < variants.length ? (
              <a
                href={`/api/models/${String(m.id)}/download`}
                download
                className={buttonVariants({ size: "sm", variant: "outline" })}
              >
                <Download aria-hidden />
                Download all converted (zip)
              </a>
            ) : null}
            <p className="text-sm text-muted-foreground">
              {busy
                ? "Conversions are running."
                : notReady === 0
                  ? "Every variant is converted."
                  : `${String(notReady)} not converted.`}
            </p>
          </div>
        </Section>
      ) : null}

      {m.status === "ready" ? (
        <Section title="Add a conversion of your own">
          <AddVariant model={m} />
        </Section>
      ) : null}

      {m.status === "ready" ? (
        <Section
          title="Add an INT8 conversion"
          id="int8"
          hint="INT8 stores the model in whole numbers: smaller and often much faster on a CPU, but it can lose accuracy or, done wrongly, stop finding anything. It is never made by 'convert what is missing'. It learns from real pictures of a dataset, and an experiment with the PyTorch baseline tells you whether it is still good."
        >
          <AddInt8 model={m} />
        </Section>
      ) : null}

      {m.class_names ? (
        <Section
          title={`Classes (${String(m.class_names.length)})`}
          hint="The order is the model's own. Results from different models are matched by name, never by position."
        >
          <details className="max-w-prose text-sm">
            <summary className="cursor-pointer">
              {m.class_names.slice(0, 8).join(", ")}
              {m.class_names.length > 8 ? `, and ${String(m.class_names.length - 8)} more` : ""}
            </summary>
            <ol start={0} className="mt-3 columns-2 gap-8 text-muted-foreground sm:columns-3">
              {m.class_names.map((name, index) => (
                <li key={index} className="tabular-nums">
                  {index} {name}
                </li>
              ))}
            </ol>
          </details>
        </Section>
      ) : null}

      <Section title="File">
        <dl className="grid max-w-prose grid-cols-[10rem_1fr] gap-y-2 text-sm">
          <dt className="text-muted-foreground">Name</dt>
          <dd>{m.filename}</dd>
          <dt className="text-muted-foreground">Size</dt>
          <dd className="tabular-nums">{formatBytes(m.size_bytes)}</dd>
          <dt className="text-muted-foreground">Fingerprint</dt>
          <dd className="tabular-nums" title={m.sha256 ?? undefined}>
            {m.sha256?.slice(0, 16)}
          </dd>
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
          Remove model
        </Button>
      </Section>
    </>
  );
}
