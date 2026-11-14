import { ArrowDown, ArrowUp, Download } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Field, NativeSelect } from "@/components/Field";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ALL,
  DEFAULT_VIEW,
  layout,
  options,
  rowsOf,
  toCsv,
  windowOf,
  type GroupKey,
  type SortKey,
  type View,
} from "@/lib/explorer";
import { MAX_RUNS } from "@/lib/compare/subjects";
import { METRIC_BY_KEY } from "@/lib/metrics";
import type { RunInfo } from "@/lib/runs";
import { useViews } from "@/lib/views";

const ROW = 40;
const VIEWPORT = 480;

const COLUMNS: { key: SortKey; label: string; hint?: string; right?: boolean }[] = [
  { key: "id", label: "Run" },
  { key: "model", label: "Model" },
  { key: "variant", label: "Variant" },
  { key: "threads", label: "Threads", right: true },
  { key: "dataset", label: "Dataset" },
  { key: "device", label: "Device" },
  { key: "acc", label: "Accuracy score", right: true },
  { key: "f1", label: "Balance score", right: true },
  { key: "ms", label: "Typical time", right: true },
  { key: "mb", label: "Size", right: true },
  { key: "status", label: "Status" },
];

/**
 * Every run in one table: search, filter, sort by any column, group, save the arrangement under a name, tick runs to compare
 * them, take the shown rows as CSV. Only the rows in view are drawn (rows have a fixed height), so a few hundred runs scroll
 * smoothly. A run whose every repeat was throttled shows "not clean" for its speed and is left out of speed rankings.
 */
export function RunExplorer({ runs }: { runs: RunInfo[] }) {
  const [view, setView] = useState<View>(DEFAULT_VIEW);
  const [typed, setTyped] = useState("");
  const [top, setTop] = useState(0);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [name, setName] = useState("");
  const { views, save, remove } = useViews();
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setView((v) => (v.search === typed ? v : { ...v, search: typed }));
    }, 250); // the table filters when typing pauses, not on every key
    return () => {
      window.clearTimeout(t);
    };
  }, [typed]);

  const rows = useMemo(() => rowsOf(runs), [runs]);
  const items = useMemo(() => layout(rows, view), [rows, view]);
  const win = windowOf(items.length, top, VIEWPORT, ROW);
  const shownRows = items.flatMap((i) => (i.kind === "row" ? [i.row] : []));
  const set = (change: Partial<View>) => {
    setView({ ...view, ...change });
    scroller.current?.scrollTo({ top: 0 });
    setTop(0);
  };
  const sortBy = (key: SortKey) => {
    set({ sort: { key, dir: view.sort.key === key && view.sort.dir === "asc" ? "desc" : "asc" } });
  };
  const toggle = (id: number) => {
    const next = new Set(picked);
    if (next.has(id)) next.delete(id);
    else if (next.size < MAX_RUNS) next.add(id);
    setPicked(next);
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([toCsv(shownRows)], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "edgebench-runs.csv";
    a.click();
    URL.revokeObjectURL(url);
  };
  const filterField = (
    key: "model" | "format" | "precision" | "device" | "dataset" | "status",
    label: string,
  ) => (
    <Field label={label}>
      {(id) => (
        <NativeSelect
          id={id}
          value={view[key]}
          onChange={(e) => {
            set({ [key]: e.target.value });
          }}
        >
          <option value={ALL}>All</option>
          {options(rows, key).map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </NativeSelect>
      )}
    </Field>
  );
  const fmt = (n: number | undefined, key: string, unit = "") => {
    const m = METRIC_BY_KEY.get(key);
    return n === undefined ? "n/a" : m ? m.format(n) : `${n.toFixed(1)}${unit}`;
  };

  return (
    <div>
      <div className="mb-3 grid gap-3 sm:grid-cols-3 lg:grid-cols-7">
        <Field label="Search" className="sm:col-span-3 lg:col-span-2">
          {(id) => (
            <Input
              id={id}
              value={typed}
              placeholder="model, variant, device, run number"
              onChange={(e) => {
                setTyped(e.target.value);
              }}
            />
          )}
        </Field>
        {filterField("model", "Model")}
        {filterField("format", "Format")}
        {filterField("precision", "Precision")}
        {filterField("device", "Device")}
        {filterField("status", "Status")}
        {filterField("dataset", "Dataset")}
        <Field label="Group by">
          {(id) => (
            <NativeSelect
              id={id}
              value={view.group}
              onChange={(e) => {
                set({ group: e.target.value as GroupKey });
              }}
            >
              <option value="none">Nothing</option>
              <option value="model">Model</option>
              <option value="format">Format</option>
              <option value="precision">Precision</option>
              <option value="device">Device</option>
              <option value="dataset">Dataset</option>
            </NativeSelect>
          )}
        </Field>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
        <span aria-live="polite">
          {String(shownRows.length)} of {String(rows.length)} runs
        </span>
        <Button
          size="xs"
          variant="outline"
          onClick={() => {
            setView(DEFAULT_VIEW);
            setTyped("");
          }}
        >
          Reset
        </Button>
        <Button size="xs" variant="outline" onClick={download} disabled={shownRows.length === 0}>
          <Download aria-hidden />
          CSV of the shown runs
        </Button>
        {picked.size > 0 ? (
          <Link
            className={buttonVariants({ size: "xs" })}
            to={`/compare?runs=${[...picked].join(",")}`}
          >
            Compare {String(picked.size)} selected
          </Link>
        ) : null}
        {picked.size > 0 ? (
          <Button
            size="xs"
            variant="ghost"
            onClick={() => {
              setPicked(new Set());
            }}
          >
            Clear selection
          </Button>
        ) : null}
      </div>

      <details className="mb-3">
        <summary className="cursor-pointer text-sm font-medium">
          Saved views ({String(views.length)})
        </summary>
        <div className="mt-2 flex flex-wrap items-end gap-3">
          <Field label="Save this arrangement as">
            {(id) => (
              <Input
                id={id}
                className="w-56"
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                }}
              />
            )}
          </Field>
          <Button
            size="sm"
            variant="outline"
            disabled={name.trim() === ""}
            onClick={() => {
              save(name.trim(), view);
              setName("");
            }}
          >
            Save view
          </Button>
        </div>
        {views.length > 0 ? (
          <ul className="mt-2 flex flex-wrap gap-2" aria-label="Saved views">
            {views.map((v) => (
              <li
                key={v.name}
                className="flex items-center gap-1 rounded-md border px-2 py-1 text-sm"
              >
                <button
                  type="button"
                  className="text-primary underline underline-offset-4"
                  onClick={() => {
                    setView(v.view);
                    setTyped(v.view.search);
                  }}
                >
                  {v.name}
                </button>
                <button
                  type="button"
                  className="text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    remove(v.name);
                  }}
                >
                  <span aria-hidden>×</span>
                  <span className="sr-only">Delete the view {v.name}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </details>

      <div
        ref={scroller}
        className="overflow-auto rounded-lg border"
        style={{ maxHeight: VIEWPORT }}
        onScroll={(e) => {
          setTop(e.currentTarget.scrollTop);
        }}
        tabIndex={0}
        aria-label="Table of all runs"
      >
        <table className="w-full min-w-[60rem] text-sm" style={{ tableLayout: "auto" }}>
          <thead className="sticky top-0 z-10 bg-background">
            <tr className="border-b text-left">
              <th scope="col" className="w-10 px-3 py-2">
                <span className="sr-only">Select for comparing</span>
              </th>
              {COLUMNS.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  className={`py-2 pr-3 font-medium ${c.right ? "text-right" : ""}`}
                  aria-sort={
                    view.sort.key === c.key
                      ? view.sort.dir === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 hover:underline"
                    onClick={() => {
                      sortBy(c.key);
                    }}
                  >
                    {c.label}
                    {view.sort.key === c.key ? (
                      view.sort.dir === "asc" ? (
                        <ArrowUp aria-hidden className="size-3.5" />
                      ) : (
                        <ArrowDown aria-hidden className="size-3.5" />
                      )
                    ) : null}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {win.padTop > 0 ? (
              <tr aria-hidden style={{ height: win.padTop }}>
                <td colSpan={COLUMNS.length + 1} />
              </tr>
            ) : null}
            {items.slice(win.start, win.end).map((item, k) =>
              item.kind === "group" ? (
                <tr key={`g${item.label}${String(k)}`} style={{ height: ROW }} className="bg-muted">
                  <th
                    scope="colgroup"
                    colSpan={COLUMNS.length + 1}
                    className="px-3 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                  >
                    {item.label} ({String(item.count)})
                  </th>
                </tr>
              ) : (
                <tr
                  key={item.row.run.id}
                  style={{ height: ROW }}
                  className={picked.has(item.row.run.id) ? "border-b bg-primary/10" : "border-b"}
                >
                  <td className="px-3">
                    <input
                      type="checkbox"
                      checked={picked.has(item.row.run.id)}
                      disabled={!picked.has(item.row.run.id) && picked.size >= MAX_RUNS}
                      onChange={() => {
                        toggle(item.row.run.id);
                      }}
                      aria-label={`Select run ${String(item.row.run.id)} for comparing`}
                    />
                  </td>
                  <td className="pr-3 tabular-nums">
                    <Link
                      to={`/results/${String(item.row.run.id)}`}
                      className="text-primary underline-offset-4 hover:underline"
                    >
                      {item.row.run.id}
                    </Link>
                  </td>
                  <td className="pr-3">{item.row.model}</td>
                  <td className="pr-3">{item.row.variant}</td>
                  <td className="pr-3 text-right tabular-nums">{item.row.threads || "n/a"}</td>
                  <td className="pr-3">{item.row.dataset}</td>
                  <td className="pr-3">{item.row.device}</td>
                  <td className="pr-3 text-right tabular-nums">{fmt(item.row.acc, "map50_95")}</td>
                  <td className="pr-3 text-right tabular-nums">{fmt(item.row.f1, "f1")}</td>
                  <td className="pr-3 text-right tabular-nums">
                    {item.row.invalid ? "not clean" : fmt(item.row.ms, "p50")}
                  </td>
                  <td className="pr-3 text-right tabular-nums">
                    {item.row.mb === undefined ? "n/a" : `${item.row.mb.toFixed(1)} MB`}
                  </td>
                  <td className="pr-3">{item.row.run.status}</td>
                </tr>
              ),
            )}
            {win.padBottom > 0 ? (
              <tr aria-hidden style={{ height: win.padBottom }}>
                <td colSpan={COLUMNS.length + 1} />
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
