import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Clock,
  Download,
  Loader2,
  MinusCircle,
  XCircle,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { LogDialog } from "@/components/LogDialog";
import { Button, buttonVariants } from "@/components/ui/button";
import { formatBytes } from "@/lib/format";
import { useCancel, useRetry, type ModelInfo, type Variant, type VariantState } from "@/lib/models";
import { cn } from "@/lib/utils";

const FORMATS = ["ONNX", "TorchScript", "OpenVINO", "ncnn"];
const PRECISIONS = ["FP32", "FP16"];

const STATE: Record<VariantState, { label: string; icon: ReactNode; tone: string }> = {
  pending: { label: "Waiting", icon: <Clock aria-hidden />, tone: "text-muted-foreground" },
  converting: {
    label: "Converting",
    icon: <Loader2 aria-hidden className="animate-spin" />,
    tone: "text-foreground",
  },
  ready: { label: "Ready", icon: <CheckCircle2 aria-hidden />, tone: "text-ok" },
  failed: { label: "Failed", icon: <XCircle aria-hidden />, tone: "text-destructive" },
  unavailable: { label: "Not available", icon: <Ban aria-hidden />, tone: "text-warn" },
  cancelled: {
    label: "Cancelled",
    icon: <MinusCircle aria-hidden />,
    tone: "text-muted-foreground",
  },
};

const percent = (x: number) => `${(x * 100).toPrecision(2)}%`;

function Cell({ variant, onLog }: { variant: Variant; onLog: () => void }) {
  const retry = useRetry();
  const cancel = useCancel();
  const s = STATE[variant.state];
  const act = (run: typeof retry) => {
    run.mutate(variant.id, {
      onError: (e) => {
        toast.error(e.message);
      },
    });
  };
  const check = variant.verify;
  return (
    <div className="space-y-1 text-sm">
      <p className={cn("flex items-center gap-1.5 font-medium [&_svg]:size-4", s.tone)}>
        {s.icon}
        {variant.mismatch
          ? check?.error
            ? "Ready, but could not be checked against PyTorch"
            : "Ready, but differs from PyTorch"
          : s.label}
      </p>
      {variant.state === "ready" ? (
        <>
          <p className="tabular-nums text-muted-foreground">
            {formatBytes(variant.size_bytes ?? 0)}
            {variant.cached
              ? ", reused"
              : variant.seconds !== null
                ? `, ${variant.seconds.toFixed(1)} s`
                : ""}
          </p>
          {check?.error ? (
            <p className="flex items-start gap-1 text-xs text-warn [&_svg]:mt-0.5 [&_svg]:size-3.5 [&_svg]:shrink-0">
              <AlertTriangle aria-hidden />
              {check.error}
            </p>
          ) : variant.precision === "INT8" ? (
            <p
              className="text-xs text-muted-foreground"
              title="INT8 changes the numbers by design. Whether it still finds the objects is what the accuracy check in an experiment with the PyTorch baseline tells you."
            >
              Accuracy: check it in an experiment
            </p>
          ) : check?.relative !== undefined &&
            check.tolerance !== undefined &&
            check.tolerance !== null ? (
            // A pass is one quiet phrase (the numbers are on hover); only a cell that does not match gets the figures.
            variant.mismatch ? (
              <p className="flex items-center gap-1 text-xs tabular-nums text-warn [&_svg]:size-3.5">
                <AlertTriangle aria-hidden />
                Largest difference from PyTorch {percent(check.relative)}, limit{" "}
                {percent(check.tolerance)}
              </p>
            ) : (
              <p
                className="text-xs text-muted-foreground"
                title={`Largest difference from PyTorch ${percent(check.relative)}, limit ${percent(check.tolerance)}`}
              >
                Matches PyTorch
              </p>
            )
          ) : null}
        </>
      ) : null}
      {variant.error && variant.state !== "ready" ? (
        <p className="line-clamp-3 text-xs text-muted-foreground" title={variant.error}>
          {variant.error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-1 pt-0.5">
        {variant.state === "ready" ? (
          <a
            href={`/api/variants/${String(variant.id)}/download`}
            download
            className={buttonVariants({ size: "xs", variant: "outline" })}
          >
            <Download aria-hidden />
            Download
            <span className="sr-only">
              {" "}
              {variant.format} {variant.precision}
            </span>
          </a>
        ) : null}
        {["failed", "unavailable", "cancelled"].includes(variant.state) ? (
          <Button
            size="xs"
            variant="outline"
            disabled={retry.isPending}
            onClick={() => {
              act(retry);
            }}
          >
            Retry
            <span className="sr-only">
              {" "}
              {variant.format} {variant.precision}
            </span>
          </Button>
        ) : null}
        {["pending", "converting"].includes(variant.state) ? (
          <Button
            size="xs"
            variant="outline"
            disabled={cancel.isPending}
            onClick={() => {
              act(cancel);
            }}
          >
            Cancel
            <span className="sr-only">
              {" "}
              {variant.format} {variant.precision}
            </span>
          </Button>
        ) : null}
        {variant.has_log ? (
          <Button size="xs" variant="ghost" onClick={onLog}>
            Log
            <span className="sr-only">
              {" "}
              for {variant.format} {variant.precision}
            </span>
          </Button>
        ) : null}
      </div>
    </div>
  );
}

/** The cells that share an input size and export settings form one grid; a custom size or setting gets its own. */
function groupKey(v: Variant): string {
  return `${String(v.imgsz)}|${v.settings.simplify === false ? "plain" : "default"}`;
}

interface CalibrationInfo {
  count: number;
  version: number;
  seed: number;
  dataset_id: number;
}

/** INT8 conversions, one row each: they differ by the pictures they were calibrated on, so they do not fit the grid. */
function Int8Table({ cells, onLog }: { cells: Variant[]; onLog: (id: number) => void }) {
  return (
    <table className="mb-6 w-full max-w-4xl border-collapse text-left">
      <caption className="pb-2 text-left text-sm font-medium">INT8 conversions</caption>
      <thead>
        <tr className="border-b text-sm">
          <th scope="col" className="w-36 py-2 pr-4 font-medium">
            Format
          </th>
          <th scope="col" className="py-2 pr-4 font-medium">
            Calibrated on
          </th>
          <th scope="col" className="py-2 pr-4 font-medium">
            Status
          </th>
        </tr>
      </thead>
      <tbody>
        {cells.map((v) => {
          const c = v.settings.calibration as CalibrationInfo | undefined;
          return (
            <tr key={v.id} className="border-b align-top">
              <th scope="row" className="py-3 pr-4 text-sm font-medium">
                {v.format} {v.precision}
                <span className="block text-xs font-normal text-muted-foreground">
                  {String(v.imgsz)} px
                </span>
              </th>
              <td className="py-3 pr-4 text-sm">
                {c ? (
                  <>
                    {String(c.count)} pictures, dataset{" "}
                    <Link
                      to={`/datasets/${String(c.dataset_id)}?v=${String(c.version)}`}
                      className="text-primary underline-offset-4 hover:underline"
                    >
                      #{String(c.dataset_id)} version {String(c.version)}
                    </Link>
                    <span className="block text-xs text-muted-foreground">
                      seed {String(c.seed)}
                    </span>
                  </>
                ) : (
                  <span className="text-muted-foreground">not recorded</span>
                )}
              </td>
              <td className="py-3 pr-4">
                <Cell
                  variant={v}
                  onLog={() => {
                    onLog(v.id);
                  }}
                />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** One grid per input size (and export setting): a row per format, a column per precision. A missing combination shows a dash. */
export function ModelMatrix({ model }: { model: ModelInfo }) {
  const [logId, setLogId] = useState<number | null>(null);
  const all = model.variants ?? [];
  const int8 = all.filter((v) => v.precision === "INT8");
  const variants = all.filter((v) => v.precision !== "INT8");
  const logFor = all.find((v) => v.id === logId) ?? null; // looked up each render, so "live" follows the cell
  const groups = new Map<string, Variant[]>();
  for (const v of variants) groups.set(groupKey(v), [...(groups.get(groupKey(v)) ?? []), v]);
  const ordered = [...groups.entries()].sort(([a], [b]) => {
    const own = (k: string) => (k === `${String(model.imgsz ?? 0)}|default` ? 0 : 1);
    return own(a) - own(b) || a.localeCompare(b);
  });
  return (
    <>
      {int8.length > 0 ? <Int8Table cells={int8} onLog={setLogId} /> : null}
      {ordered.map(([key, cells]) => {
        const first = cells[0];
        const heading = first
          ? `${String(first.imgsz)} px input${first.settings.simplify === false ? ", ONNX not simplified" : ""}${
              key === `${String(model.imgsz ?? 0)}|default` ? " (the model's own size)" : ""
            }`
          : "";
        const formats = FORMATS.filter((f) => cells.some((v) => v.format === f));
        return (
          <table key={key} className="mb-6 w-full max-w-4xl border-collapse text-left">
            <caption className="pb-2 text-left text-sm font-medium">
              <span className="sr-only">Conversion status of {model.name} at </span>
              {heading}
            </caption>
            <thead>
              <tr className="border-b text-sm">
                <th scope="col" className="w-36 py-2 pr-4 font-medium">
                  Format
                </th>
                {PRECISIONS.map((p) => (
                  <th key={p} scope="col" className="py-2 pr-4 font-medium">
                    {p}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {formats.map((format) => (
                <tr key={format} className="border-b align-top">
                  <th scope="row" className="py-3 pr-4 text-sm font-medium">
                    {format}
                  </th>
                  {PRECISIONS.map((precision) => {
                    const v = cells.find((x) => x.format === format && x.precision === precision);
                    return (
                      <td key={precision} className="py-3 pr-4">
                        {v ? (
                          <Cell
                            variant={v}
                            onLog={() => {
                              setLogId(v.id);
                            }}
                          />
                        ) : (
                          <span className="text-sm text-muted-foreground">
                            <span aria-hidden>-</span>
                            <span className="sr-only">Not offered for {format}</span>
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        );
      })}
      <LogDialog
        variantId={logFor?.id ?? null}
        title={logFor ? `${logFor.format} ${logFor.precision}` : ""}
        live={logFor?.state === "converting"}
        onClose={() => {
          setLogId(null);
        }}
      />
    </>
  );
}
