import { useId, useState, type ReactNode } from "react";
import type { Fill, Shape, Subject } from "@/lib/compare/subjects";

/** Round tick values that cover [min, max]. */
export function niceTicks(min: number, max: number, want = 5): number[] {
  const span = max - min || 1;
  const raw = span / want;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step)
    out.push(Number(v.toPrecision(12)));
  return out;
}

export const seriesVar = (color: number) => `var(--series-${String(Math.min(color, 2) + 1)})`;

/** A mark's outline for a shape, centred on (x, y) with "radius" r. */
export function shapePath(shape: Shape, x: number, y: number, r: number): string {
  const p = (pts: [number, number][]) =>
    `M${pts.map(([a, b]) => `${String(x + a * r)} ${String(y + b * r)}`).join("L")}Z`;
  switch (shape) {
    case "diamond":
      return p([
        [0, -1.2],
        [1.2, 0],
        [0, 1.2],
        [-1.2, 0],
      ]);
    case "square":
      return p([
        [-0.95, -0.95],
        [0.95, -0.95],
        [0.95, 0.95],
        [-0.95, 0.95],
      ]);
    case "triangle":
      return p([
        [0, -1.2],
        [1.1, 0.9],
        [-1.1, 0.9],
      ]);
    case "hexagon":
      return p([
        [1.1, 0],
        [0.55, 0.95],
        [-0.55, 0.95],
        [-1.1, 0],
        [-0.55, -0.95],
        [0.55, -0.95],
      ]);
    case "circle":
      return `M${String(x - r)} ${String(y)}a${String(r)} ${String(r)} 0 1 0 ${String(2 * r)} 0a${String(r)} ${String(r)} 0 1 0 ${String(-2 * r)} 0Z`;
  }
}

/** The fill that says the precision: FP32 solid, FP16 soft, INT8 hollow. */
export function fillProps(
  fill: Fill,
  color: string,
): { fill: string; fillOpacity?: number; stroke: string; strokeWidth: number } {
  if (fill === "hollow") return { fill: "var(--card)", stroke: color, strokeWidth: 2.5 };
  if (fill === "soft") return { fill: color, fillOpacity: 0.45, stroke: color, strokeWidth: 2 };
  return { fill: color, stroke: "var(--card)", strokeWidth: 2 }; // the ring in the surface colour keeps overlapping marks apart
}

export function Mark({
  subject,
  x,
  y,
  r = 5.5,
}: {
  subject: Subject;
  x: number;
  y: number;
  r?: number;
}) {
  return (
    <path
      d={shapePath(subject.shape, x, y, r)}
      strokeLinejoin="round"
      {...fillProps(subject.fill, seriesVar(subject.color))}
    />
  );
}

/** The legend: colour is the model, shape the format, fill the precision (only the keys that are in use). */
export function Legend({ subjects }: { subjects: Subject[] }) {
  const models = [...new Map(subjects.map((s) => [s.color, s.modelName])).entries()];
  const formats = [...new Map(subjects.map((s) => [s.shape, s.run.format])).entries()];
  const precisions = [...new Map(subjects.map((s) => [s.fill, s.run.precision])).entries()];
  const key = (shape: Shape, fill: Fill, color: string) => (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
      <path d={shapePath(shape, 8, 8, 5)} strokeLinejoin="round" {...fillProps(fill, color)} />
    </svg>
  );
  return (
    <ul className="mb-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-sm" aria-label="Legend">
      {models.map(([c, name]) => (
        <li key={`m${String(c)}`} className="flex items-center gap-1.5">
          {key("circle", "solid", seriesVar(c))}
          {name}
        </li>
      ))}
      {formats.length > 1
        ? formats.map(([shape, name]) => (
            <li key={`f${shape}`} className="flex items-center gap-1.5 text-muted-foreground">
              {key(shape, "solid", "var(--muted-foreground)")}
              {name}
            </li>
          ))
        : null}
      {precisions.length > 1
        ? precisions.map(([fill, name]) => (
            <li key={`p${fill}`} className="flex items-center gap-1.5 text-muted-foreground">
              {key("circle", fill, "var(--muted-foreground)")}
              {name}
            </li>
          ))
        : null}
    </ul>
  );
}

export interface TipState {
  /** Position as a share of the chart's width and height. */
  left: number;
  top: number;
  lines: string[];
}

/** Hover and focus readouts; every value is also in the table view, so a tooltip never gates anything. */
export function useTip() {
  const [tip, setTip] = useState<TipState | null>(null);
  const on = (left: number, top: number, lines: string[]) => ({
    onPointerEnter: () => {
      setTip({ left, top, lines });
    },
    onPointerLeave: () => {
      setTip(null);
    },
    onFocus: () => {
      setTip({ left, top, lines });
    },
    onBlur: () => {
      setTip(null);
    },
  });
  return { tip, setTip, on };
}

export function Tip({ tip }: { tip: TipState | null }) {
  if (!tip) return null;
  const [first, ...rest] = tip.lines;
  return (
    <div
      role="status"
      className="pointer-events-none absolute z-10 max-w-64 -translate-x-1/2 rounded-md border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-md"
      style={{ left: `${String(tip.left * 100)}%`, top: `${String(tip.top * 100 + 3)}%` }}
    >
      <p className="font-semibold tabular-nums">{first}</p>
      {rest.map((l) => (
        <p key={l} className="text-muted-foreground">
          {l}
        </p>
      ))}
    </div>
  );
}

const LINES_SHOWN = 5;

export interface TableData {
  head: string[];
  rows: (string | number)[][];
}

export function DataTable({ table }: { table: TableData }) {
  return (
    <div className="mt-2 max-w-full overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            {table.head.map((h) => (
              <th key={h} scope="col" className="py-1 pr-4 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, i) => (
            <tr key={i} className="border-b">
              {row.map((cell, j) =>
                j === 0 ? (
                  <th key={j} scope="row" className="py-1 pr-4 text-left font-normal">
                    {cell}
                  </th>
                ) : (
                  <td key={j} className="py-1 pr-4 tabular-nums">
                    {cell}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * One chart on the page: the question it answers, how to read it, the chart, what the numbers say (computed, with the red flags),
 * and the same numbers as a table.
 */
export function ChartFrame({
  id,
  title,
  question,
  how,
  lines,
  empty,
  table,
  subjects,
  children,
  controls,
}: {
  id: string;
  title: string;
  question: string;
  how: string;
  lines: string[];
  /** Said instead of the chart when there is nothing to draw: what to select or run. */
  empty?: string;
  table?: TableData;
  subjects?: Subject[];
  children?: ReactNode;
  controls?: ReactNode;
}) {
  const [show, setShow] = useState(false);
  const heading = useId();
  return (
    <section
      id={id}
      aria-labelledby={heading}
      className="scroll-mt-28 border-t py-6 first:border-t-0"
    >
      <h3 id={heading} className="text-base font-semibold">
        {title}
      </h3>
      <p className="mt-1 max-w-prose text-sm">{question}</p>
      <p className="mt-1 max-w-prose text-sm text-muted-foreground">How to read it: {how}</p>
      {empty ? (
        <p className="mt-3 max-w-prose rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">
          {empty}
        </p>
      ) : (
        <>
          {controls ? <div className="mt-3">{controls}</div> : null}
          <figure className="mt-3 max-w-4xl">
            {subjects ? <Legend subjects={subjects} /> : null}
            {children}
          </figure>
          {lines.length > 0 ? (
            <ul
              className="mt-3 max-w-prose list-disc space-y-1 pl-5 text-sm"
              aria-label={`What ${title} shows`}
            >
              {lines.slice(0, LINES_SHOWN).map((l) => (
                <li key={l}>{l}</li>
              ))}
              {lines.length > LINES_SHOWN ? (
                <li>…and {String(lines.length - LINES_SHOWN)} more (the table has every run).</li>
              ) : null}
            </ul>
          ) : null}
          {table ? (
            <>
              <button
                type="button"
                className="mt-2 text-sm text-primary underline-offset-4 hover:underline"
                aria-expanded={show}
                onClick={() => {
                  setShow(!show);
                }}
              >
                {show ? "Hide the table" : "Show as a table"}
              </button>
              {show ? <DataTable table={table} /> : null}
            </>
          ) : null}
        </>
      )}
    </section>
  );
}
