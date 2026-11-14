import type { Subject } from "@/lib/compare/subjects";
import { fillProps, niceTicks, seriesVar, Tip, useTip } from "./kit";

export interface Bar {
  key: string;
  subject: Subject;
  value: number;
  /** Half-width of an interval drawn as a whisker. */
  half?: number;
  /** Tell the reader this bar is the one to look at (outside the band, doubtful). */
  flag?: boolean;
  /** Extra tooltip line. */
  note?: string;
  /** A short name written before the value (a device), when the bars of a group need telling apart. */
  tag?: string;
}

export interface Group {
  label: string;
  bars: Bar[];
}

interface Props {
  groups: Group[];
  yLabel: string;
  fy: (n: number) => string;
  /** Bars grow from here (0, or 1 for a ratio). */
  baseline?: number;
  domain?: [number, number];
  band?: { lo: number; hi: number; label: string };
  refLine?: { y: number; label: string };
  aria: string;
  height?: number;
}

const M = { l: 58, r: 22, t: 22, b: 70 };

/**
 * Columns from one baseline, at most 24 px thick with a 4 px rounded end, a 2 px gap between neighbours, the value at the cap when
 * there are few bars, an optional interval whisker, a reference line and a shaded allowed band. The colour is the model, the
 * outline style the precision (the same keys as the other charts).
 */
export function BarsChart({
  groups,
  yLabel,
  fy,
  baseline = 0,
  domain,
  band,
  refLine,
  aria,
  height = 320,
}: Props) {
  const { tip, on } = useTip();
  const bars = groups.flatMap((g) => g.bars);
  if (bars.length === 0) return null;
  const SLOT = bars.some((b) => b.tag) ? 76 : 30;
  const GROUP_MIN = 100; // a group's name needs this much room under it, however few bars it has
  const wide = (n: number) => Math.max(n * SLOT, GROUP_MIN);
  const W = Math.max(
    640,
    M.l + M.r + groups.length * 12 + groups.reduce((sum, g) => sum + wide(g.bars.length), 0) + 12,
  );
  const H = height;
  const vals = [
    ...bars.flatMap((b) => [b.value - (b.half ?? 0), b.value + (b.half ?? 0)]),
    baseline,
    ...(band ? [band.lo, band.hi] : []),
    ...(refLine ? [refLine.y] : []),
  ];
  const [lo, hi] = domain ?? [Math.min(...vals), Math.max(...vals)];
  const span = hi - lo || 1;
  const y0 = lo - (domain ? 0 : span * 0.05);
  const y1 = hi + (domain ? 0 : span * 0.1);
  const sy = (v: number) => H - M.b - ((v - y0) / (y1 - y0)) * (H - M.t - M.b);
  const layout = groups.reduce<{ start: number; end: number }[]>((acc, g) => {
    const start = (acc[acc.length - 1]?.end ?? M.l) + 12;
    return [...acc, { start, end: start + wide(g.bars.length) }];
  }, []);
  const labelled = bars.length <= 10;
  return (
    <div className="relative max-w-full overflow-x-auto">
      <svg
        viewBox={`0 0 ${String(W)} ${String(H)}`}
        width={W}
        role="img"
        aria-label={aria}
        className="h-auto max-w-none rounded-lg border bg-card"
        style={{ minWidth: "100%" }}
      >
        {niceTicks(y0, y1).map((v) => (
          <g key={String(v)}>
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
        <text
          transform={`translate(14 ${String((M.t + H - M.b) / 2)}) rotate(-90)`}
          textAnchor="middle"
          className="fill-muted-foreground text-[12px]"
        >
          {yLabel}
        </text>
        {band ? (
          <g>
            <rect
              x={M.l}
              y={sy(band.hi)}
              width={W - M.l - M.r}
              height={Math.max(0, sy(band.lo) - sy(band.hi))}
              fill="var(--muted-foreground)"
              opacity="0.12"
            />
            <text
              x={W - M.r - 4}
              y={sy(band.hi) + 12}
              textAnchor="end"
              className="fill-muted-foreground text-[11px]"
            >
              {band.label}
            </text>
          </g>
        ) : null}
        <line
          x1={M.l}
          x2={W - M.r}
          y1={sy(baseline)}
          y2={sy(baseline)}
          stroke="var(--muted-foreground)"
          strokeWidth="1"
        />
        {refLine ? (
          <g>
            <line
              x1={M.l}
              x2={W - M.r}
              y1={sy(refLine.y)}
              y2={sy(refLine.y)}
              stroke="var(--muted-foreground)"
              strokeWidth="1"
              strokeDasharray="4 3"
            />
            <text
              x={W - M.r - 4}
              y={sy(refLine.y) - 4}
              textAnchor="end"
              className="fill-muted-foreground text-[11px]"
            >
              {refLine.label}
            </text>
          </g>
        ) : null}
        {groups.map((g, gi) => {
          const place = layout[gi] ?? { start: M.l, end: M.l };
          const cols = g.bars.map((b, bi) => {
            const cx =
              place.start + (wide(g.bars.length) - g.bars.length * SLOT) / 2 + bi * SLOT + SLOT / 2;

            const top = sy(Math.max(b.value, baseline));
            const bottom = sy(Math.min(b.value, baseline));
            const color = seriesVar(b.subject.color);
            const f = fillProps(b.subject.fill, color);
            const r = Math.min(4, (bottom - top) / 2);
            const grows = b.value >= baseline;
            return (
              <g key={b.key}>
                <path
                  d={
                    grows
                      ? `M${String(cx - 12)} ${String(bottom)}V${String(top + r)}a${String(r)} ${String(r)} 0 0 1 ${String(r)} ${String(-r)}H${String(cx + 12 - r)}a${String(r)} ${String(r)} 0 0 1 ${String(r)} ${String(r)}V${String(bottom)}Z`
                      : `M${String(cx - 12)} ${String(top)}V${String(bottom - r)}a${String(r)} ${String(r)} 0 0 0 ${String(r)} ${String(r)}H${String(cx + 12 - r)}a${String(r)} ${String(r)} 0 0 0 ${String(r)} ${String(-r)}V${String(top)}Z`
                  }
                  fill={f.fill}
                  fillOpacity={f.fillOpacity}
                  stroke={b.subject.fill === "solid" ? "none" : color}
                  strokeWidth={b.subject.fill === "solid" ? 0 : 2}
                />
                {b.half !== undefined ? (
                  <g stroke="var(--foreground)" strokeWidth="1.5">
                    <line x1={cx} x2={cx} y1={sy(b.value - b.half)} y2={sy(b.value + b.half)} />
                    <line
                      x1={cx - 4}
                      x2={cx + 4}
                      y1={sy(b.value - b.half)}
                      y2={sy(b.value - b.half)}
                    />
                    <line
                      x1={cx - 4}
                      x2={cx + 4}
                      y1={sy(b.value + b.half)}
                      y2={sy(b.value + b.half)}
                    />
                  </g>
                ) : null}
                {labelled ? (
                  <text
                    x={cx}
                    y={
                      (grows ? top : bottom) +
                      (grows
                        ? -(b.half !== undefined ? sy(b.value) - sy(b.value + b.half) + 4 : 5)
                        : 13)
                    }
                    textAnchor="middle"
                    className={`text-[11px] ${b.flag ? "fill-warn font-semibold" : "fill-foreground"}`}
                  >
                    {b.tag ? `${b.tag} ` : ""}
                    {fy(b.value)}
                  </text>
                ) : null}
                <rect
                  x={cx - SLOT / 2}
                  y={M.t}
                  width={SLOT}
                  height={H - M.t - M.b}
                  fill="transparent"
                  tabIndex={0}
                  role="img"
                  aria-label={`${b.subject.long}: ${fy(b.value)}${b.half !== undefined ? `, plus or minus ${fy(b.half)}` : ""}${b.flag ? ", flagged" : ""}`}
                  className="outline-none focus-visible:stroke-foreground focus-visible:[stroke-width:2]"
                  {...on(cx / W, sy(b.value) / H, [
                    fy(b.value) + (b.half !== undefined ? ` ± ${fy(b.half)}` : ""),
                    b.subject.long,
                    ...(b.note ? [b.note] : []),
                  ])}
                />
              </g>
            );
          });
          const mid = (place.start + place.end) / 2;
          const [first, ...rest] = g.label.split(" · ");
          return (
            <g key={g.label}>
              {cols}
              <text
                x={mid}
                y={H - M.b + 16}
                textAnchor="middle"
                className="fill-foreground text-[11px]"
              >
                {first}
              </text>
              {rest.map((line, i) => (
                <text
                  key={line}
                  x={mid}
                  y={H - M.b + 29 + i * 12}
                  textAnchor="middle"
                  className="fill-muted-foreground text-[10px]"
                >
                  {line}
                </text>
              ))}
            </g>
          );
        })}
      </svg>
      <Tip tip={tip} />
    </div>
  );
}
