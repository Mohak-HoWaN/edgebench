import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { EmptyState } from "@/components/EmptyState";
import { Field, NativeSelect } from "@/components/Field";
import { Info } from "@/components/Info";
import { PageHeader, Section } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataset, useDatasets } from "@/lib/datasets";
import { cpuLimits, parseCpuList, useDevices } from "@/lib/devices";
import {
  usePlan,
  useStartExperiment,
  type NewExperiment as NewExperimentBody,
} from "@/lib/experiments";
import { useModel, useModels, type ModelInfo } from "@/lib/models";

const BASELINE = "baseline";

/** Quick is a first look; Full is what ADR 0004 asks for (three repeats of 200 timed rounds after 20 warm-up rounds). */
const MODES = {
  quick: { warmup: 5, iterations: 50, repeats: 1 },
  full: { warmup: 20, iterations: 200, repeats: 3 },
} as const;
const THREAD_CHOICES = [1, 2, 4, 8];
const SIZE_CHOICES = [320, 416, 512, 640];

/** "about 12 min", "about 40 s": a duration for a person, never false precision. */
export function duration(seconds: number): string {
  if (seconds < 90) return `about ${String(Math.max(5, Math.round(seconds / 5) * 5))} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `about ${String(minutes)} min`;
  const hours = Math.floor(minutes / 60);
  return `about ${String(hours)} h ${String(minutes - hours * 60)} min`;
}

/** Toggle one value of a list of chips. */
function ChipGroup({
  legend,
  help,
  options,
  picked,
  onChange,
  label = (n) => String(n),
}: {
  legend: string;
  help: string;
  options: number[];
  picked: number[];
  onChange: (next: number[]) => void;
  label?: (n: number) => string;
}) {
  return (
    <fieldset className="space-y-1">
      <legend className="flex items-center gap-1.5 text-sm font-medium">
        {legend}
        <Info>{help}</Info>
      </legend>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {options.map((n) => (
          <label key={n} className="flex items-center gap-1.5 text-sm">
            <input
              type="checkbox"
              checked={picked.includes(n)}
              onChange={() => {
                onChange(
                  picked.includes(n)
                    ? picked.filter((x) => x !== n)
                    : [...picked, n].sort((a, b) => a - b),
                );
              }}
            />
            {label(n)}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

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
  const [iterations, setIterations] = useState<number>(MODES.full.iterations);
  const [warmup, setWarmup] = useState<number>(MODES.full.warmup);
  const [repeats, setRepeats] = useState<number>(MODES.full.repeats);
  const [accuracy, setAccuracy] = useState(true);
  const [telemetry, setTelemetry] = useState(true);
  const [sweepThreads, setSweepThreads] = useState<number[]>([]);
  const [sweepSizes, setSweepSizes] = useState<number[]>([]);
  const mode =
    (Object.entries(MODES) as [keyof typeof MODES, (typeof MODES)[keyof typeof MODES]][]).find(
      ([, m]) => m.warmup === warmup && m.iterations === iterations && m.repeats === repeats,
    )?.[0] ?? "custom";

  const readyModels = (models.data ?? []).filter((m) => m.status === "ready" && m.class_names);
  const readyDatasets = (datasets.data ?? []).filter((d) => d.head !== null);
  const enrolled = (devices.data ?? []).filter((d) => d.enrolled);
  const dataset = readyDatasets.find((d) => d.id === (datasetPick ?? readyDatasets[0]?.id));
  const detail = useDataset(dataset?.id ?? 0);
  const versions = (detail.data?.versions ?? []).filter((v) => v.status === "ready");
  const device = enrolled.find((d) => d.id === (devicePick ?? enrolled[0]?.id));
  const limits = cpuLimits(device?.fingerprint ?? null);
  // "0-3; 4-7" is two sets of CPUs to compare; one set pins every run to it
  const sets = pin
    ? cpuText
        .split(";")
        .map((s) => s.trim())
        .filter(Boolean)
        .map((s) => parseCpuList(s, limits.logical))
    : [];
  const parsed = pin
    ? sets.length === 0
      ? parseCpuList("", limits.logical)
      : (sets.find((s) => s.error) ?? sets[0] ?? null)
    : null;
  const cpuSets =
    sets.length > 1 && !sets.some((s) => s.error) ? sets.map((s) => s.cpus ?? []) : [];
  const pinnedCount =
    sets.length === 1
      ? (parsed?.cpus?.length ?? 0)
      : sets.length > 1
        ? Math.min(...sets.map((s) => s.cpus?.length ?? 0))
        : 0;
  const maxThreads = pinnedCount > 0 ? pinnedCount : limits.logical > 0 ? limits.logical : 1024;
  const threadChoices = [
    ...new Set([...THREAD_CHOICES.filter((n) => n <= maxThreads), maxThreads]),
  ].sort((a, b) => a - b);
  const threads = Math.min(Math.max(threadsPick, 1), maxThreads);
  const version = versions.find((v) => v.number === versionPick) ?? versions[0];

  const items = Object.entries(picks).flatMap(([modelId, keys]) =>
    keys.map((k) => ({ model_id: Number(modelId), variant_id: k === BASELINE ? null : Number(k) })),
  );
  const problem =
    items.length === 0
      ? "Pick at least one model variant."
      : pin && parsed?.error
        ? parsed.error
        : null;
  const body: NewExperimentBody | null =
    problem === null && dataset !== undefined && device !== undefined
      ? {
          name: name.trim() || "plan",
          notes: notes.trim(),
          dataset_id: dataset.id,
          dataset_version: version?.number ?? null,
          device_id: device.id,
          params: {
            threads,
            iterations,
            warmup,
            repeats,
            accuracy,
            telemetry,
            conf: 0.001,
            iou: 0.7,
            max_det: 300,
            cpu_list: cpuSets.length === 0 ? (parsed?.cpus ?? null) : null,
          },
          items,
          sweep: { threads: sweepThreads, cpu_sets: cpuSets, imgsz: sweepSizes },
        }
      : null;
  const plan = usePlan(body);
  const canStart =
    problem === null &&
    name.trim() !== "" &&
    dataset !== undefined &&
    device !== undefined &&
    !plan.isError &&
    !start.isPending;

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
          if (body === null) return;
          start.mutate(
            { ...body, name: name.trim() },
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
          <div
            className="mb-4 flex flex-wrap items-center gap-2"
            role="group"
            aria-label="How thorough"
          >
            {(["quick", "full"] as const).map((key) => (
              <Button
                key={key}
                type="button"
                size="sm"
                variant={mode === key ? "default" : "outline"}
                aria-pressed={mode === key}
                onClick={() => {
                  setWarmup(MODES[key].warmup);
                  setIterations(MODES[key].iterations);
                  setRepeats(MODES[key].repeats);
                }}
              >
                {key === "quick" ? "Quick look" : "Full measurement"}
              </Button>
            ))}
            <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
              {mode === "quick"
                ? "5 warm-up and 50 timed rounds, once: fast, but no error bar."
                : mode === "full"
                  ? "20 warm-up and 200 timed rounds, three times."
                  : "Your own numbers."}
              <Info>
                Each repeat has its own warm-up and timed rounds. The speed you see is the average
                of the repeats' medians, with a 95% interval across them; one repeat has no
                interval, and three give a wide one (five or more narrow it).
              </Info>
            </span>
          </div>
          <div className="grid gap-4 sm:grid-cols-4">
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
              help="Untimed rounds before each repeat's timing starts."
              value={warmup}
              min={0}
              max={10000}
              onChange={setWarmup}
            />
            <NumberField
              label="Timed rounds"
              help="Rounds in each repeat that count towards the speed numbers."
              value={iterations}
              min={1}
              max={100000}
              onChange={setIterations}
            />
            <NumberField
              label="Repeats"
              help="How many times the warm-up and timed rounds are repeated. The spread between repeats is what the error bar and the 'is this difference real?' test are made from."
              value={repeats}
              min={1}
              max={100}
              onChange={setRepeats}
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
                help={`Numbers from 0 to ${String(Math.max(limits.logical - 1, 0))}, with ranges: 0-7,16. Separate sets with a semicolon (0-7; 8-15) to compare them, one run per set. On a laptop with fast and slow cores the fast ones are usually the lowest numbers; check yours before trusting a comparison.`}
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
            {pin && sets.length === 1 && parsed?.cpus ? (
              <p className="text-sm text-muted-foreground">
                Using {String(parsed.cpus.length)} CPU{parsed.cpus.length === 1 ? "" : "s"}.
              </p>
            ) : null}
            {pin && sets.length > 1 && cpuSets.length > 0 ? (
              <p className="text-sm text-muted-foreground">
                Comparing {String(cpuSets.length)} sets of CPUs.
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
          <label className="mt-2 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={telemetry}
              onChange={(e) => {
                setTelemetry(e.target.checked);
              }}
            />
            Record CPU, memory, clock and temperature while it runs (a repeat during which the
            machine slowed down is marked and left out)
          </label>
        </Section>

        <Section
          title="Try several settings"
          id="exp-sweep"
          hint="Tick more than one value to run every combination with the variants above. Leave all unticked to use the single settings above. Combinations that cannot run are left out, with the reason, in the plan below."
        >
          <div className="space-y-4">
            <ChipGroup
              legend="Try several thread counts"
              help="Each ticked count becomes its own run for every variant. The largest is this device's own thread count."
              options={threadChoices}
              picked={sweepThreads}
              onChange={setSweepThreads}
              label={(n) => (n === limits.logical ? `${String(n)} (all)` : String(n))}
            />
            <ChipGroup
              legend="Try several input sizes"
              help="A conversion is built for one size. A size with no finished conversion of a variant is left out; add it on the Models page. The PyTorch baseline only runs at the model's own size."
              options={SIZE_CHOICES}
              picked={sweepSizes}
              onChange={setSweepSizes}
              label={(n) => `${String(n)} px`}
            />
          </div>
        </Section>

        <Section
          title="What this will run"
          id="exp-plan"
          hint="Worked out by the server before anything starts. The time is an estimate from earlier runs of the same conversion on this device; where there are none it is a guess."
        >
          {plan.data ? (
            <div className="space-y-2 text-sm">
              <p role="status" data-testid="plan-summary" className="font-medium">
                {String(plan.data.run_count)} run{plan.data.run_count === 1 ? "" : "s"},{" "}
                {duration(plan.data.estimated_seconds)} in total
              </p>
              <p className="text-muted-foreground">
                {String(plan.data.images)} pictures for accuracy, then {String(plan.data.repeats)}{" "}
                timed repeat{plan.data.repeats === 1 ? "" : "s"} of each run, one run after another.
                {plan.data.guessed_runs > 0
                  ? ` For ${String(plan.data.guessed_runs)} of them nothing has been measured on this device yet, so their time is a guess.`
                  : ""}
              </p>
              {plan.data.repeats < 5 ? (
                <p className="text-muted-foreground">
                  {plan.data.repeats === 1
                    ? "One repeat gives no error bar, so a small difference cannot be told from noise."
                    : `${String(plan.data.repeats)} repeats give a wide interval; five or more narrow it.`}
                </p>
              ) : null}
              {plan.data.pruned.length > 0 ? (
                <details data-testid="plan-pruned">
                  <summary className="cursor-pointer">
                    {String(plan.data.pruned.length)} combination
                    {plan.data.pruned.length === 1 ? "" : "s"} left out
                  </summary>
                  <ul className="mt-2 list-disc space-y-1 pl-5">
                    {plan.data.pruned.map((p, i) => (
                      <li key={i}>
                        {p.label}, {String(p.threads)} thread{p.threads === 1 ? "" : "s"}
                        {p.cpu_list ? `, CPUs ${p.cpu_list.join(",")}` : ""}: {p.reason}.
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
              {plan.data.run_count > 1 ? (
                <details>
                  <summary className="cursor-pointer">The runs</summary>
                  <ul className="mt-2 list-disc space-y-1 pl-5">
                    {plan.data.runs.map((r, i) => (
                      <li key={i}>
                        {r.label}, {String(r.threads)} thread{r.threads === 1 ? "" : "s"}
                        {r.cpu_list ? `, CPUs ${r.cpu_list.join(",")}` : ""}
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </div>
          ) : plan.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {plan.error.message}
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">
              {body === null
                ? "Pick at least one model variant to see the plan."
                : "Working it out."}
            </p>
          )}
        </Section>

        <div className="space-y-2 pt-2">
          <p className="text-sm" role="status">
            {problem ??
              (plan.isError ? "Fix the plan above before starting." : null) ??
              `This starts ${String(plan.data?.run_count ?? items.length)} run${(plan.data?.run_count ?? items.length) === 1 ? "" : "s"}, one after another.`}
          </p>
          <Button type="submit" disabled={!canStart}>
            Start experiment
          </Button>
        </div>
      </form>
    </>
  );
}
