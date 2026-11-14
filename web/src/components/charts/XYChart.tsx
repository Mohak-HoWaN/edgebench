import type { Subject } from "@/lib/compare/subjects";
import { Mark, niceTicks, seriesVar, Tip, useTip } from "./kit";

export interface XYSeries {
  id: string;
  subject: Subject;
  label: string;
  points: { x: number; y: number }[];
  /** Draw the points joined by a 2 px line (otherwise only marks). */
  line?: boolean;
  /** Draw a mark at every point (scatter, a few thread counts); lines with many points mark only `peak`. */
  markers?: boolean;
  peak?: number;
  /** A direct label beside the first point. */
  tag?: boolean;
}

interface Props {
  series: XYSeries[];
  xLabel: string;
  yLabel: string;
  fx: (n: number) => string;
  fy: (n: number) => string;
  /** The same numbers with their units, for the hover and focus readout (the axes stay uncluttered). */
  tipX?: (n: number) => string;
  tipY?: (n: number) => string;
  xDomain?: [number, number];
  yDomain?: [number, number];
  /** The front: drawn as a neutral line through these points. */
  front?: { x: number; y: number }[];
  vlines?: { x: number; label?: string }[];
  hlines?: { y: number; label: string }[];
  /** Shaded bands along x (repeats that were left out). */
  bands?: { from: number; to: number }[];
  /** Where your limits are met: right edge (at most this x) and bottom edge (at least this y). */
  zone?: { xMax?: number; yMin?: number; label: string };
  aria: string;
  height?: number;
}

const W = 640;
const M = { l: 58, r: 22, t: 28, b: 48 };

/**
 * Scatter and line charts in plain SVG. Marks with a hit area bigger than the mark (and keyboard focus) give the readout; lines with
 * many points use the nearest-x readout instead. Left and bottom axes carry round ticks; the grid is a hairline.
 */
export function XYChart({
  series,
  xLabel,
  yLabel,
  fx,
  fy,
  tipX = fx,
  tipY = fy,
  xDomain,
  yDomain,
  front,
  vlines,
  hlines,
  bands,
  zone,
  aria,
  height = 330,
}: Props) {
  const { tip, setTip, on } = useTip();
  const H = height;
  const all = series.flatMap((s) => s.points);
  if (all.length === 0) return null;
  const xs = [...all.map((p) => p.x), ...(zone?.xMax === undefined ? [] : [zone.xMax])];
  const ys = [...all.map((p) => p.y), ...(zone?.yMin === undefined ? [] : [zone.yMin])];
  const pad = (lo: number, hi: number, f: number) => (hi - lo || Math.abs(hi) || 1) * f;
  const [x0, x1] = xDomain ?? [
    Math.min(...xs) - pad(Math.min(...xs), Math.max(...xs), 0.1),
    Math.max(...xs) + pad(Math.min(...xs), Math.max(...xs), 0.1),
  ];
  const [y0, y1] = yDomain ?? [
    Math.min(...ys) - pad(Math.min(...ys), Math.max(...ys), 0.15),
    Math.max(...ys) + pad(Math.min(...ys), Math.max(...ys), 0.15),
  ];
  const sx = (v: number) => M.l + ((v - x0) / (x1 - x0 || 1)) * (W - M.l - M.r);
  const sy = (v: number) => H - M.b - ((v - y0) / (y1 - y0 || 1)) * (H - M.t - M.b);
  const path = (pts: { x: number; y: number }[]) =>
    pts.map((p, i) => `${i === 0 ? "M" : "L"}${String(sx(p.x))} ${String(sy(p.y))}`).join("");
  const scatter = series.every((s) => s.markers);
  const xsAll = [...new Set(xs)].sort((a, b) => a - b);

  // nearest-x readout for line charts
  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const vx = x0 + ((e.clientX - box.left) / box.width) * (x1 - x0); // the rect covers exactly the plot area
    const nearest = xsAll.reduce(
      (a, b) => (Math.abs(b - vx) < Math.abs(a - vx) ? b : a),
      xsAll[0] ?? 0,
    );
    const lines = [
      tipX(nearest),
      ...series.flatMap((s) => {
        const p = s.points.reduce(
          (a, b) => (Math.abs(b.x - nearest) < Math.abs(a.x - nearest) ? b : a),
          s.points[0] ?? { x: 0, y: 0 },
        );
        return [`${s.label}: ${tipY(p.y)}`];
      }),
    ];
    setTip({ left: sx(nearest) / W, top: 0.12, lines });
  };

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${String(W)} ${String(H)}`}
        role="img"
        aria-label={aria}
        className="h-auto w-full rounded-lg border bg-card"
      >
        {niceTicks(y0, y1).map((v) => (
          <g key={`y${String(v)}`}>
            <line
              x1={M.l}
              x2={W - M.r}
              y1={sy(v)}
              y2={sy(v)}
              stroke="var(--border)"
              strokeWidth="1"
            />
            <text
              x={M.l - 8}
              y={sy(v)}
              textAnchor="end"
              dominantBaseline="middle"
              className="fill-muted-foreground text-[11px]"
            >
              {fy(v)}
            </text>
          </g>
        ))}
        {niceTicks(x0, x1).map((v) => (
          <text
            key={`x${String(v)}`}
            x={sx(v)}
            y={H - M.b + 16}
            textAnchor="middle"
            className="fill-muted-foreground text-[11px]"
          >
            {fx(v)}
          </text>
        ))}
        <text
          x={(M.l + W - M.r) / 2}
          y={H - 8}
          textAnchor="middle"
          className="fill-muted-foreground text-[12px]"
        >
          {xLabel}
        </text>
        <text
          transform={`translate(14 ${String((M.t + H - M.b) / 2)}) rotate(-90)`}
          textAnchor="middle"
          className="fill-muted-foreground text-[12px]"
        >
          {yLabel}
        </text>
        {zone && (zone.xMax !== undefined || zone.yMin !== undefined) ? (
          <g>
            <rect
              x={M.l}
              y={M.t}
              width={Math.max(0, (zone.xMax === undefined ? W - M.r : sx(zone.xMax)) - M.l)}
              height={Math.max(0, (zone.yMin === undefined ? H - M.b : sy(zone.yMin)) - M.t)}
              fill="var(--series-3)"
              opacity="0.12"
            />
            <text x={M.l + 6} y={M.t + 14} className="fill-muted-foreground text-[11px]">
              {zone.label}
            </text>
          </g>
        ) : null}
        {(bands ?? []).map((b, i) => (
          <rect
            key={i}
            x={sx(b.from)}
            y={M.t}
            width={Math.max(0, sx(b.to) - sx(b.from))}
            height={H - M.t - M.b}
            fill="var(--muted-foreground)"
            opacity="0.1"
          />
        ))}
        {(hlines ?? []).map((h) => (
          <g key={h.label}>
            <line
              x1={M.l}
              x2={W - M.r}
              y1={sy(h.y)}
              y2={sy(h.y)}
              stroke="var(--muted-foreground)"
              strokeWidth="1"
              strokeDasharray="4 3"
            />
            <text
              x={W - M.r - 4}
              y={sy(h.y) - 4}
              textAnchor="end"
              className="fill-muted-foreground text-[11px]"
            >
              {h.label}
            </text>
          </g>
        ))}
        {(vlines ?? []).map((v) => (
          <g key={v.x}>
            <line
              x1={sx(v.x)}
              x2={sx(v.x)}
              y1={M.t}
              y2={H - M.b}
              stroke="var(--muted-foreground)"
              strokeWidth="1"
              strokeDasharray="4 3"
            />
            {v.label ? (
              <text x={sx(v.x) + 4} y={M.t + 10} className="fill-muted-foreground text-[11px]">
                {v.label}
              </text>
            ) : null}
          </g>
        ))}
        {front && front.length > 1 ? (
          <path
            d={path(front)}
            fill="none"
            stroke="var(--muted-foreground)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {series.map((s) => (
          <g key={s.id}>
            {s.line ? (
              <path
                d={path(s.points)}
                fill="none"
                stroke={seriesVar(s.subject.color)}
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeDasharray={s.subject.fill === "hollow" ? "6 3" : undefined}
              />
            ) : null}
            {s.points.map((p, i) =>
              s.markers || i === s.peak ? (
                <Mark
                  key={i}
                  subject={s.subject}
                  x={sx(p.x)}
                  y={sy(p.y)}
                  r={s.markers ? 5.5 : 6.5}
                />
              ) : null,
            )}
            {s.tag && s.points[0] ? (
              <text
                x={sx(s.points[0].x) + 9}
                y={sy(s.points[0].y) - 9}
                className="fill-foreground text-[11px]"
              >
                {s.label}
              </text>
            ) : null}
            {s.markers
              ? s.points.map((p, i) => (
                  <circle
                    key={`h${String(i)}`}
                    cx={sx(p.x)}
                    cy={sy(p.y)}
                    r="14"
                    fill="transparent"
                    tabIndex={0}
                    role="img"
                    aria-label={`${s.label}: ${tipX(p.x)}, ${tipY(p.y)}`}
                    className="outline-none focus-visible:stroke-foreground focus-visible:[stroke-width:2]"
                    {...on(sx(p.x) / W, sy(p.y) / H, [`${tipX(p.x)}, ${tipY(p.y)}`, s.label])}
                  />
                ))
              : null}
          </g>
        ))}
        {!scatter ? (
          <rect
            x={M.l}
            y={M.t}
            width={W - M.l - M.r}
            height={H - M.t - M.b}
            fill="transparent"
            onPointerMove={onMove}
            onPointerLeave={() => {
              setTip(null);
            }}
          />
        ) : null}
      </svg>
      <Tip tip={tip} />
    </div>
  );
}
