import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { EmptyState } from "@/components/EmptyState";
import { Field, NativeSelect } from "@/components/Field";
import { PageHeader, Section } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataset, useDatasets } from "@/lib/datasets";
import { cpuLimits, parseCpuList, useDevices } from "@/lib/devices";
import { useStartExperiment } from "@/lib/experiments";
import { useModel, useModels, type ModelInfo } from "@/lib/models";

const BASELINE = "baseline";

function NumberField({
  label,
  help,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  help: string;
  value: number;
  min: number;
  max: number;
  onChange: (n: number) => void;
}) {
  return (
    <Field label={label} help={help}>
      {(id, describedBy) => (
        <Input
          id={id}
          aria-describedby={describedBy}
          type="number"
          inputMode="numeric"
          min={min}
          max={max}
          value={value}
          onChange={(e) => {
            onChange(Number(e.target.value));
          }}
        />
      )}
    </Field>
  );
}

/** The variants of one model that can be run, as checkboxes, with the .pt baseline. */
function ModelChoices({
  model,
  picked,
  onChange,
}: {
  model: ModelInfo;
  picked: string[];
  onChange: (next: string[]) => void;
}) {
  const detail = useModel(model.id);
  const ready = (detail.data?.variants ?? []).filter((v) => v.state === "ready");
  const all = [...ready.map((v) => String(v.id)), BASELINE];
  const toggle = (key: string) => {
    onChange(picked.includes(key) ? picked.filter((k) => k !== key) : [...picked, key]);
  };
  const label = (id: number) => {
    const v = ready.find((x) => x.id === id);
    if (!v) return "";
    const size = model.imgsz && v.imgsz !== model.imgsz ? ` at ${String(v.imgsz)} px` : "";
    const note = v.settings.simplify === false ? ", not simplified" : "";
    return `${v.format} ${v.precision}${size}${note}`;
  };
  return (
    <fieldset className="rounded-lg border p-3">
      <legend className="px-1 text-sm font-medium">{model.name}</legend>
      <div className="mb-2 flex gap-2">
        <Button
          type="button"
          size="xs"
          variant="outline"
          onClick={() => {
            onChange(all);
          }}
        >
          Select all<span className="sr-only"> for {model.name}</span>
        </Button>
        <Button
          type="button"
          size="xs"
          variant="ghost"
          onClick={() => {
            onChange([]);
          }}
        >
          None<span className="sr-only"> for {model.name}</span>
        </Button>
      </div>
      <div className="grid gap-1 sm:grid-cols-2">
        {ready.map((v) => (
          <label key={v.id} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={picked.includes(String(v.id))}
              onChange={() => {
                toggle(String(v.id));
              }}
            />
            {label(v.id)}
          </label>
        ))}
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={picked.includes(BASELINE)}
            onChange={() => {
              toggle(BASELINE);
            }}
          />
          PyTorch (.pt) baseline
        </label>
      </div>
    </fieldset>
  );
}

export default function NewExperiment() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const models = useModels();
  const datasets = useDatasets();
  const devices = useDevices();
  const start = useStartExperiment();
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [picks, setPicks] = useState<Record<number, string[]>>({});
  const [datasetPick, setDatasetPick] = useState<number | null>(
    Number(params.get("dataset")) || null,
  );
  const [versionPick, setVersionPick] = useState<number | null>(
    Number(params.get("version")) || null,
  );
  const [devicePick, setDevicePick] = useState<number | null>(null);
  const [threadsPick, setThreads] = useState(4);
  const [pin, setPin] = useState(false);
  const [cpuText, setCpuText] = useState("");
  const [iterations, setIterations] = useState(100);
  const [warmup, setWarmup] = useState(10);
  const [accuracy, setAccuracy] = useState(true);

  const readyModels = (models.data ?? []).filter((m) => m.status === "ready" && m.class_names);
  const readyDatasets = (datasets.data ?? []).filter((d) => d.head !== null);
  const enrolled = (devices.data ?? []).filter((d) => d.enrolled);
  const dataset = readyDatasets.find((d) => d.id === (datasetPick ?? readyDatasets[0]?.id));
  const detail = useDataset(dataset?.id ?? 0);
  const versions = (detail.data?.versions ?? []).filter((v) => v.status === "ready");
  const device = enrolled.find((d) => d.id === (devicePick ?? enrolled[0]?.id));
  const limits = cpuLimits(device?.fingerprint ?? null);
  const parsed = pin ? parseCpuList(cpuText, limits.logical) : null;
  const pinnedCount = parsed?.cpus?.length ?? 0;
  const maxThreads = pinnedCount > 0 ? pinnedCount : limits.logical > 0 ? limits.logical : 1024;
  const threads = Math.min(Math.max(threadsPick, 1), maxThreads);
  const version = versions.find((v) => v.number === versionPick) ?? versions[0];

  if (models.isPending || datasets.isPending || devices.isPending) {
    return <Skeleton aria-busy="true" aria-label="Loading" className="h-40 w-full max-w-prose" />;
  }
  const missing = [
    readyModels.length === 0 ? { text: "a model", to: "/models" } : null,
    readyDatasets.length === 0 ? { text: "a dataset", to: "/datasets" } : null,
    enrolled.length === 0 ? { text: "a device with its agent connected", to: "/devices" } : null,
  ].filter((x) => x !== null);
  if (missing.length > 0) {
    return (
      <>
        <PageHeader
          title="New experiment"
          hint="A named set of runs: pick model variants, a dataset and a device, and compare them."
        />
        <EmptyState
          title="Something is missing before you can run"
          action={{ label: `Add ${missing[0]?.text ?? ""}`, to: missing[0]?.to ?? "/models" }}
        >
          You still need {missing.map((m) => m.text).join(", and ")}.
        </EmptyState>
      </>
    );
  }

  const items = Object.entries(picks).flatMap(([modelId, keys]) =>
    keys.map((k) => ({ model_id: Number(modelId), variant_id: k === BASELINE ? null : Number(k) })),
  );
  const problem =
    items.length === 0
      ? "Pick at least one model variant."
      : pin && parsed?.error
        ? parsed.error
        : null;
  const canStart =
    problem === null &&
    name.trim() !== "" &&
    dataset !== undefined &&
    device !== undefined &&
    !start.isPending;

  return (
    <>
      <PageHeader
        title="New experiment"
        hint="A named set of runs. Choose the model variants you want to compare, one dataset version and one device; each variant becomes a run, one after another."
      />
      <form
        className="max-w-prose space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (!canStart) return;
          start.mutate(
            {
              name: name.trim(),
              notes: notes.trim(),
              dataset_id: dataset.id,
              dataset_version: version?.number ?? null,
              device_id: device.id,
              params: {
                threads,
                iterations,
                warmup,
                accuracy,
                conf: 0.001,
                iou: 0.7,
                max_det: 300,
                cpu_list: parsed?.cpus ?? null,
              },
              items,
            },
            {
              onSuccess: (experiment) => {
                void navigate(`/experiments/${String((experiment as { id: number }).id)}`);
              },
              onError: (err) => {
                toast.error(err.message);
              },
            },
          );
        }}
      >
        <Section title="Name it" id="exp-name">
          <div className="space-y-4">
            <Field label="Experiment name" help="This is the row you will look for in Results.">
              {(id, describedBy) => (
                <Input
                  id={id}
                  aria-describedby={describedBy}
                  required
                  maxLength={120}
                  value={name}
                  placeholder="Does FP16 hurt accuracy on the shop shelf?"
                  onChange={(e) => {
                    setName(e.target.value);
                  }}
                />
              )}
            </Field>
            <Field label="Notes (optional)">
              {(id) => (
                <Input
                  id={id}
                  maxLength={4000}
                  value={notes}
                  onChange={(e) => {
                    setNotes(e.target.value);
                  }}
                />
              )}
            </Field>
          </div>
        </Section>

        <Section
          title="Models and variants to compare"
          id="exp-models"
          hint="The PyTorch baseline is the original file, the reference for accuracy. It needs PyTorch and Ultralytics installed on the device."
        >
          <div className="space-y-3">
            {readyModels.map((m) => (
              <ModelChoices
                key={m.id}
                model={m}
                picked={picks[m.id] ?? []}
                onChange={(next) => {
                  setPicks({ ...picks, [m.id]: next });
                }}
              />
            ))}
          </div>
        </Section>

        <Section title="Dataset and device" id="exp-dataset-device">
          <div className="space-y-4">
            <Field label="Dataset">
              {(id) => (
                <NativeSelect
                  id={id}
                  value={dataset?.id ?? ""}
                  onChange={(e) => {
                    setDatasetPick(Number(e.target.value));
                    setVersionPick(null);
                  }}
                >
                  {readyDatasets.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
            <Field
              label="Version"
              help="A run records the exact version, so a dataset that grows later does not change old results."
            >
              {(id, describedBy) => (
                <NativeSelect
                  id={id}
                  aria-describedby={describedBy}
                  value={version?.number ?? ""}
                  onChange={(e) => {
                    setVersionPick(Number(e.target.value));
                  }}
                >
                  {versions.map((v) => (
                    <option key={v.id} value={v.number}>
                      v{v.number}
                      {v.is_head ? " (latest)" : ""}: {v.image_count} pictures
                      {v.labelled_count === 0 ? ", no annotations" : ""}
                      {v.message ? `, ${v.message}` : ""}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
            <Field label="Device">
              {(id) => (
                <NativeSelect
                  id={id}
                  value={device?.id ?? ""}
                  onChange={(e) => {
                    setDevicePick(Number(e.target.value));
                  }}
                >
                  {enrolled.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name} ({d.online ? "online" : "offline"})
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
            {device && !device.online ? (
              <p className="border-l-2 border-warn pl-3 text-sm">
                This device is offline. The runs wait in the queue until its agent is back.
              </p>
            ) : null}
          </div>
        </Section>

        <Section title="Settings" id="exp-settings">
          <p className="mb-4 text-sm text-muted-foreground" data-testid="cpu-summary">
            {limits.logical
              ? `${device?.name ?? "This device"} has ${String(limits.logical)} threads${
                  limits.physical ? ` (${String(limits.physical)} physical cores)` : ""
                }. A run can use at most ${String(maxThreads)}.`
              : `${device?.name ?? "This device"} did not report how many threads it has.`}
          </p>
          <div className="grid gap-4 sm:grid-cols-3">
            <NumberField
              label="Threads"
              help={`Between 1 and ${String(maxThreads)}. More is not always faster.`}
              value={threads}
              min={1}
              max={maxThreads}
              onChange={setThreads}
            />
            <NumberField
              label="Warm-up rounds"
              help="Untimed rounds before timing starts."
              value={warmup}
              min={0}
              max={10000}
              onChange={setWarmup}
            />
            <NumberField
              label="Timed rounds"
              help="Rounds that count towards the speed numbers."
              value={iterations}
              min={1}
              max={100000}
              onChange={setIterations}
            />
          </div>
          <div className="mt-4 space-y-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={pin}
                onChange={(e) => {
                  setPin(e.target.checked);
                }}
              />
              Pin the run to specific CPUs
            </label>
            {pin ? (
              <Field
                label="CPU numbers"
                help={`Numbers from 0 to ${String(Math.max(limits.logical - 1, 0))}, with ranges: 0-7,16. On a laptop with fast and slow cores the fast ones are usually the lowest numbers; check yours before trusting a comparison.`}
              >
                {(id, describedBy) => (
                  <Input
                    id={id}
                    aria-describedby={describedBy}
                    value={cpuText}
                    placeholder="0-7"
                    onChange={(e) => {
                      setCpuText(e.target.value);
                    }}
                  />
                )}
              </Field>
            ) : null}
            {pin && cpuText && parsed?.error ? (
              <p role="alert" className="text-sm text-destructive">
                {parsed.error}
              </p>
            ) : null}
            {pin && parsed?.cpus ? (
              <p className="text-sm text-muted-foreground">
                Using {String(parsed.cpus.length)} CPU{parsed.cpus.length === 1 ? "" : "s"}.
              </p>
            ) : null}
          </div>
          <label className="mt-4 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={accuracy}
              onChange={(e) => {
                setAccuracy(e.target.checked);
              }}
            />
            Measure accuracy (needs annotations; skip it for a faster speed-only run)
          </label>
        </Section>

        <div className="space-y-2 pt-2">
          <p className="text-sm" role="status">
            {problem ??
              `This starts ${String(items.length)} run${items.length === 1 ? "" : "s"}, one after another.`}
          </p>
          <Button type="submit" disabled={!canStart}>
            Start experiment
          </Button>
        </div>
      </form>
    </>
  );
}
