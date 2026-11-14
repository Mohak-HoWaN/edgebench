import type { Box, Stages } from "@/lib/compare/builders";
import { niceTicks, seriesVar, Tip, useTip } from "./kit";

const M = { l: 58, r: 22, t: 22, b: 70 };
const SLOT = 100; // wide enough for the three lines of a run's name

const ms = (n: number) => `${n.toFixed(1)} ms`;

function Frame({
  width,
  height,
  aria,
  ticks,
  y,
  yLabel,
  children,
}: {
  width: number;
  height: number;
  aria: string;
  ticks: number[];
  y: (v: number) => number;
  yLabel: string;
  children: React.ReactNode;
}) {
  return (
    <svg
      viewBox={`0 0 ${String(width)} ${String(height)}`}
      width={width}
      role="img"
      aria-label={aria}
      className="h-auto max-w-none rounded-lg border bg-card"
      style={{ minWidth: "100%" }}
    >
      {ticks.map((v) => (
        <g key={String(v)}>
          <line
            x1={M.l}
            x2={width - M.r}
            y1={y(v)}
            y2={y(v)}
            stroke="var(--border)"
            strokeWidth="1"
          />
          <text
            x={M.l - 8}
            y={y(v)}
            textAnchor="end"
            dominantBaseline="middle"
            className="fill-muted-foreground text-[11px]"
          >
            {String(v)}
          </text>
        </g>
      ))}
      <text
        transform={`translate(14 ${String((M.t + height - M.b) / 2)}) rotate(-90)`}
        textAnchor="middle"
        className="fill-muted-foreground text-[12px]"
      >
        {yLabel}
      </text>
      {children}
    </svg>
  );
}

function Label({ x, y, text }: { x: number; y: number; text: string }) {
  const [first, ...rest] = text.split(" · ");
  return (
    <>
      <text x={x} y={y + 16} textAnchor="middle" className="fill-foreground text-[11px]">
        {first}
      </text>
      {rest.map((line, i) => (
        <text
          key={line}
          x={x}
          y={y + 29 + i * 12}
          textAnchor="middle"
          className="fill-muted-foreground text-[10px]"
        >
          {line}
        </text>
      ))}
    </>
  );
}

/** Box plot of each run's time per image: the box is the middle half, the whiskers the rest, dots the outliers. */
export function BoxChart({ boxes, aria }: { boxes: Box[]; aria: string }) {
  const { tip, on } = useTip();
  if (boxes.length === 0) return null;
  const W = Math.max(640, M.l + M.r + boxes.length * SLOT + 20);
  const H = 320;
  const top = Math.max(...boxes.map((b) => Math.max(b.high, ...b.outliers.slice(-12)))) * 1.08;
  const y = (v: number) => H - M.b - (v / top) * (H - M.t - M.b);
  return (
    <div className="relative max-w-full overflow-x-auto">
      <Frame
        width={W}
        height={H}
        aria={aria}
        ticks={niceTicks(0, top)}
        y={y}
        yLabel="Time per image (ms)"
      >
        {boxes.map((b, i) => {
          const cx = M.l + 20 + i * SLOT + SLOT / 2;
          const color = seriesVar(b.subject.color);
          return (
            <g key={b.subject.run.id}>
              <line x1={cx} x2={cx} y1={y(b.low)} y2={y(b.high)} stroke={color} strokeWidth="2" />
              <rect
                x={cx - 12}
                y={y(b.q3)}
                width="24"
                height={Math.max(2, y(b.q1) - y(b.q3))}
                rx="4"
                fill={color}
                fillOpacity={b.subject.fill === "hollow" ? 0 : 0.35}
                stroke={color}
                strokeWidth="2"
              />
              <line
                x1={cx - 12}
                x2={cx + 12}
                y1={y(b.median)}
                y2={y(b.median)}
                stroke="var(--foreground)"
                strokeWidth="2"
              />
              {b.outliers.slice(-12).map((v, k) => (
                <circle
                  key={k}
                  cx={cx}
                  cy={y(v)}
                  r="3"
                  fill={color}
                  stroke="var(--card)"
                  strokeWidth="1.5"
                />
              ))}
              <Label x={cx} y={H - M.b} text={b.subject.cat} />
              <rect
                x={cx - SLOT / 2}
                y={M.t}
                width={SLOT}
                height={H - M.t - M.b}
                fill="transparent"
                tabIndex={0}
                role="img"
                aria-label={`${b.subject.long}: median ${ms(b.median)}, middle half ${ms(b.q1)} to ${ms(b.q3)}, ${String(b.n)} images`}
                className="outline-none focus-visible:stroke-foreground focus-visible:[stroke-width:2]"
                {...on(cx / W, y(b.median) / H, [
                  `median ${ms(b.median)}`,
                  b.subject.long,
                  `middle half ${ms(b.q1)} to ${ms(b.q3)}; slowest 1 in 100 ${ms(b.p99)}; ${String(b.n)} timings`,
                ])}
              />
            </g>
          );
        })}
      </Frame>
      <Tip tip={tip} />
    </div>
  );
}

const TINT = { pre: 0.35, model: 1, post: 0.65 } as const;

/** Where one image's time goes: preprocess, the model, postprocess, stacked, with a 2 px gap between the parts. */
export function StageChart({ rows, aria }: { rows: Stages[]; aria: string }) {
  const { tip, on } = useTip();
  if (rows.length === 0) return null;
  const W = Math.max(640, M.l + M.r + rows.length * SLOT + 20);
  const H = 320;
  const top = Math.max(...rows.map((r) => r.pre + r.model + r.post)) * 1.1;
  const y = (v: number) => H - M.b - (v / top) * (H - M.t - M.b);
  return (
    <div className="relative max-w-full overflow-x-auto">
      <ul className="mb-2 flex gap-4 text-sm text-muted-foreground" aria-label="Parts">
        {(["pre", "model", "post"] as const).map((k) => (
          <li key={k} className="flex items-center gap-1.5">
            <svg width="14" height="14" aria-hidden>
              <rect
                width="14"
                height="14"
                rx="3"
                fill="var(--muted-foreground)"
                fillOpacity={TINT[k]}
              />
            </svg>
            {k === "pre" ? "Preprocess" : k === "model" ? "The model" : "Postprocess"}
          </li>
        ))}
      </ul>
      <Frame
        width={W}
        height={H}
        aria={aria}
        ticks={niceTicks(0, top)}
        y={y}
        yLabel="Mean time per image (ms)"
      >
        {rows.map((r, i) => {
          const cx = M.l + 20 + i * SLOT + SLOT / 2;
          const color = seriesVar(r.subject.color);
          let from = 0;
          const parts = (
            [
              ["pre", r.pre],
              ["model", r.model],
              ["post", r.post],
            ] as const
          ).map(([k, v]) => {
            const y1 = y(from + v);
            const y0 = y(from);
            from += v;
            return (
              <rect
                key={k}
                x={cx - 12}
                y={y1}
                width="24"
                height={Math.max(0, y0 - y1 - 2)}
                fill={color}
                fillOpacity={TINT[k]}
              />
            );
          });
          return (
            <g key={r.subject.run.id}>
              {parts}
              <Label x={cx} y={H - M.b} text={r.subject.cat} />
              <rect
                x={cx - SLOT / 2}
                y={M.t}
                width={SLOT}
                height={H - M.t - M.b}
                fill="transparent"
                tabIndex={0}
                role="img"
                aria-label={`${r.subject.long}: preprocess ${ms(r.pre)}, model ${ms(r.model)}, postprocess ${ms(r.post)}`}
                className="outline-none focus-visible:stroke-foreground focus-visible:[stroke-width:2]"
                {...on(cx / W, y(r.pre + r.model + r.post) / H, [
                  `${ms(r.pre + r.model + r.post)} in total`,
                  r.subject.long,
                  `preprocess ${ms(r.pre)}, model ${ms(r.model)}, postprocess ${ms(r.post)}`,
                ])}
              />
            </g>
          );
        })}
      </Frame>
      <Tip tip={tip} />
    </div>
  );
}
