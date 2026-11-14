import { Tip, useTip } from "./kit";

export interface HeatRow {
  label: string;
  /** Shown under the label (instances, a total). */
  sub?: string;
  cells: ({ value: number; text: string; note?: string } | undefined)[];
}

/**
 * A grid of cells, darker for more. One hue (the first series colour mixed into the card), so it reads in both themes; the value is
 * written in every cell, so colour is never the only carrier. Missing cells are dashes.
 */
export function Heatmap({
  rows,
  columns,
  aria,
  rowHeader,
}: {
  rows: HeatRow[];
  columns: string[];
  aria: string;
  rowHeader: string;
}) {
  const { tip, on } = useTip();
  const CELL = { w: 92, h: 34 };
  const LEFT = 150;
  const W = LEFT + columns.length * CELL.w + 8;
  const TOP = 62;
  const H = TOP + rows.length * CELL.h;
  return (
    <div className="relative max-w-full overflow-x-auto">
      <svg
        viewBox={`0 0 ${String(W)} ${String(H)}`}
        width={W}
        role="img"
        aria-label={aria}
        className="h-auto max-w-none rounded-lg border bg-card"
        style={{ minWidth: "min(100%, 480px)" }}
      >
        <text x="10" y="24" className="fill-muted-foreground text-[11px]">
          {rowHeader}
        </text>
        {columns.map((c, j) => {
          const [first, ...rest] = c.split(" · ");
          return (
            <g key={c}>
              <text
                x={LEFT + j * CELL.w + CELL.w / 2}
                y="20"
                textAnchor="middle"
                className="fill-foreground text-[11px]"
              >
                {first}
              </text>
              {rest.map((line, k) => (
                <text
                  key={line}
                  x={LEFT + j * CELL.w + CELL.w / 2}
                  y={32 + k * 10}
                  textAnchor="middle"
                  className="fill-muted-foreground text-[9px]"
                >
                  {line}
                </text>
              ))}
            </g>
          );
        })}
        {rows.map((r, i) => (
          <g key={r.label}>
            <text x="10" y={TOP + i * CELL.h + 15} className="fill-foreground text-[12px]">
              {r.label}
            </text>
            {r.sub ? (
              <text x="10" y={TOP + i * CELL.h + 28} className="fill-muted-foreground text-[10px]">
                {r.sub}
              </text>
            ) : null}
            {r.cells.map((c, j) => {
              const x = LEFT + j * CELL.w;
              const y = TOP + i * CELL.h;
              return (
                <g key={j}>
                  <rect
                    x={x + 1}
                    y={y + 1}
                    width={CELL.w - 2}
                    height={CELL.h - 2}
                    rx="3"
                    style={{
                      fill: c
                        ? `color-mix(in oklab, var(--series-1) ${String(Math.round(8 + c.value * 57))}%, var(--card))`
                        : "transparent",
                    }}
                    stroke={c ? "none" : "var(--border)"}
                  />
                  <text
                    x={x + CELL.w / 2}
                    y={y + CELL.h / 2 + 1}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    className="fill-foreground text-[12px] tabular-nums"
                  >
                    {c ? c.text : "—"}
                  </text>
                  {c ? (
                    <rect
                      x={x}
                      y={y}
                      width={CELL.w}
                      height={CELL.h}
                      fill="transparent"
                      tabIndex={0}
                      role="img"
                      aria-label={`${r.label}, ${columns[j] ?? ""}: ${c.text}`}
                      className="outline-none focus-visible:stroke-foreground focus-visible:[stroke-width:2]"
                      {...on((x + CELL.w / 2) / W, y / H, [
                        c.text,
                        `${r.label}, ${columns[j] ?? ""}`,
                        ...(c.note ? [c.note] : []),
                      ])}
                    />
                  ) : null}
                </g>
              );
            })}
          </g>
        ))}
      </svg>
      <Tip tip={tip} />
    </div>
  );
}
