import { useMemo, useState } from "react";
import { Field, NativeSelect } from "@/components/Field";
import { seriesVar } from "@/components/charts/kit";
import { cannotAdd, threadsText, type Subject, type Suggestion } from "@/lib/compare/subjects";
import { METRIC_BY_KEY } from "@/lib/metrics";
import type { RunInfo } from "@/lib/runs";

const KIND_TITLE: Record<Suggestion["kind"], string> = {
  models: "The same variant on different models",
  variants: "Every variant of one model",
  threads: "A thread sweep of one variant",
  devices: "The same run on different devices",
};

/** Comparisons the data allows, ready to take with one click. */
export function Suggestions({
  items,
  onPick,
}: {
  items: Suggestion[];
  onPick: (ids: number[]) => void;
}) {
  if (items.length === 0)
    return (
      <p className="max-w-prose text-sm text-muted-foreground">
        No ready-made comparison yet: run the same variant on two models, or one variant at several
        thread counts, and it will appear here.
      </p>
    );
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {(Object.keys(KIND_TITLE) as Suggestion["kind"][]).map((kind) => {
        const list = items.filter((x) => x.kind === kind);
        return list.length === 0 ? null : (
          <section key={kind} aria-label={KIND_TITLE[kind]}>
            <h3 className="mb-1 text-sm font-medium">{KIND_TITLE[kind]}</h3>
            <ul className="space-y-1">
              {list.map((x) => (
                <li key={x.id}>
                  <button
                    type="button"
                    className="w-full rounded-md border px-3 py-1.5 text-left text-sm hover:bg-accent/50"
                    onClick={() => {
                      onPick(x.runIds);
                    }}
                  >
                    {x.title}
                    <span className="block text-xs text-muted-foreground">{x.detail}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

const ALL = "all";

/** Every finished run, filterable; tick any of them. Different models, variants, thread counts, datasets and devices can all be mixed. */
export function RunTable({
  runs,
  selected,
  onToggle,
}: {
  runs: RunInfo[];
  selected: Subject[];
  onToggle: (run: RunInfo) => void;
}) {
  const [f, setF] = useState({
    model: ALL,
    format: ALL,
    precision: ALL,
    threads: ALL,
    dataset: ALL,
    device: ALL,
  });
  const options = useMemo(() => {
    const uniq = (get: (r: RunInfo) => string) => [...new Set(runs.map(get))].sort();
    return {
      model: uniq((r) => r.model_name ?? "a removed model"),
      format: uniq((r) => r.format),
      precision: uniq((r) => r.precision),
      threads: uniq(threadsText),
      dataset: uniq((r) => `${r.dataset_name ?? "removed"} v${String(r.dataset_version ?? "?")}`),
      device: uniq((r) => r.device_name ?? "removed"),
    };
  }, [runs]);
  const shown = runs
    .filter(
      (r) =>
        (f.model === ALL || (r.model_name ?? "a removed model") === f.model) &&
        (f.format === ALL || r.format === f.format) &&
        (f.precision === ALL || r.precision === f.precision) &&
        (f.threads === ALL || threadsText(r) === f.threads) &&
        (f.dataset === ALL ||
          `${r.dataset_name ?? "removed"} v${String(r.dataset_version ?? "?")}` === f.dataset) &&
        (f.device === ALL || (r.device_name ?? "removed") === f.device),
    )
    .sort((a, b) => b.id - a.id);
  const map = METRIC_BY_KEY.get("map50_95");
  const time = METRIC_BY_KEY.get("p50");
  const field = (key: keyof typeof f, label: string) => (
    <Field label={label}>
      {(id) => (
        <NativeSelect
          id={id}
          value={f[key]}
          onChange={(e) => {
            setF({ ...f, [key]: e.target.value });
          }}
        >
          <option value={ALL}>All</option>
          {options[key].map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </NativeSelect>
      )}
    </Field>
  );
  return (
    <div>
      <div className="mb-3 grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {field("model", "Model")}
        {field("format", "Format")}
        {field("precision", "Precision")}
        {field("threads", "Threads")}
        {field("dataset", "Dataset")}
        {field("device", "Device")}
      </div>
      <p className="mb-1 text-xs text-muted-foreground" aria-live="polite">
        {String(shown.length)} of {String(runs.length)} finished runs
      </p>
      <div className="max-h-96 overflow-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-background">
            <tr className="border-b text-left text-muted-foreground">
              <th scope="col" className="px-3 py-2 font-medium">
                <span className="sr-only">Add to the comparison</span>
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                Run
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                Model and variant
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                Threads
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                Dataset
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                Device
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                mAP50-95
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                Time
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => {
              const picked = selected.some((s) => s.run.id === r.id);
              const blocked = cannotAdd(selected, r);
              const mapV = map?.value(r);
              const timeV = time?.value(r);
              return (
                <tr key={r.id} className={picked ? "border-b bg-primary/10" : "border-b"}>
                  <td className="px-3 py-1.5">
                    <input
                      type="checkbox"
                      checked={picked}
                      disabled={blocked !== null}
                      title={blocked ?? undefined}
                      onChange={() => {
                        onToggle(r);
                      }}
                      aria-label={`Run ${String(r.id)}: ${r.model_name ?? "a removed model"}, ${r.variant_label}, ${threadsText(r)}`}
                    />
                  </td>
                  <td className="py-1.5 pr-3 tabular-nums">{r.id}</td>
                  <td className="py-1.5 pr-3">
                    <span className="inline-flex items-center gap-1.5">
                      {picked ? (
                        <span
                          aria-hidden
                          className="size-2 rounded-full"
                          style={{
                            background: seriesVar(
                              selected.find((s) => s.run.id === r.id)?.color ?? 0,
                            ),
                          }}
                        />
                      ) : null}
                      {r.model_name ?? "a removed model"}, {r.variant_label}
                    </span>
                  </td>
                  <td className="py-1.5 pr-3">{threadsText(r)}</td>
                  <td className="py-1.5 pr-3">
                    {r.dataset_name ?? "removed"} v{r.dataset_version ?? "?"}
                  </td>
                  <td className="py-1.5 pr-3">{r.device_name ?? "removed"}</td>
                  <td className="py-1.5 pr-3 tabular-nums">
                    {map && mapV !== undefined ? map.format(mapV) : "n/a"}
                  </td>
                  <td className="py-1.5 pr-3 tabular-nums">
                    {time && timeV !== undefined ? time.format(timeV) : "n/a"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
