// The sentences under each chart. One rule is one condition and one sentence; every rule has a test with a case that triggers it and
// one that does not (e2e/compare.spec.ts). Thin data is said to be thin, never read as a result.
import type {
  Box,
  ClassHeat,
  Confusion,
  DevicePair,
  Drift,
  Line,
  Machine,
  ScoreHist,
  Scorecard,
  Speedup,
  Stages,
  ThreadLine,
  Trace,
  XY,
  BySource,
} from "./builders.ts";
import { quantile } from "./builders.ts";

const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
const ms = (n: number) => `${n.toFixed(1)} ms`;
const who = (s: { long: string }) => s.long;
const median = (v: number[]) =>
  quantile(
    [...v].sort((a, b) => a - b),
    0.5,
  );

/** 1 and 16: the front of an accuracy-against-speed (or size) scatter. */
export function front(points: XY[], axes: { x: string; y: string }): string[] {
  if (points.length < 2)
    return [`Select at least two runs that have both ${axes.x} and ${axes.y}.`];
  const out: string[] = [];
  const onFront = points.filter((p) => p.front);
  const models = new Set(onFront.map((p) => p.subject.modelName));
  if (models.size === 1 && new Set(points.map((p) => p.subject.modelName)).size > 1)
    out.push(
      `${[...models][0] ?? ""} has all the best trade-offs: each run of the other model is beaten on both counts by one of its runs.`,
    );
  const dominated = points.filter((p) => !p.front);
  if (dominated.length > 0)
    out.push(
      `Beaten on both counts by another run: ${dominated
        .slice(0, 3)
        .map((p) => who(p.subject))
        .join("; ")}${dominated.length > 3 ? ` and ${String(dominated.length - 3)} more` : ""}.`,
    );
  return out;
}

/** 1 only: accuracy that does not separate the runs. */
export function accuracyFlat(points: XY[]): string[] {
  const ys = points.map((p) => p.y);
  return ys.length > 1 && Math.max(...ys) - Math.min(...ys) < 0.005
    ? ["All runs are within half a point of the same accuracy, so choose by speed."]
    : [];
}

/** 16: a big file saving that costs accuracy. */
export function sizeCost(points: XY[]): string[] {
  const biggest = points.reduce<XY | undefined>((a, p) => (!a || p.x > a.x ? p : a), undefined);
  if (!biggest) return [];
  return points
    .filter((p) => p.x <= biggest.x * 0.7 && biggest.y - p.y >= 0.02)
    .map(
      (p) =>
        `${who(p.subject)} is ${((1 - p.x / biggest.x) * 100).toFixed(0)}% smaller than ${who(biggest.subject)} but ${((biggest.y - p.y) * 100).toFixed(1)} points less accurate.`,
    );
}

/** 2 */
export function spread(boxes: Box[]): string[] {
  const out: string[] = [];
  for (const b of boxes) {
    if (b.p99 > b.median * 2)
      out.push(
        `${who(b.subject)}: the slowest 1 in 100 images takes ${(b.p99 / b.median).toFixed(1)} times the median, so its time is unpredictable.`,
      );
    if (b.outliers.filter((v) => v > b.high).length / b.n >= 0.05)
      out.push(`${who(b.subject)}: more than 1 image in 20 is far slower than the rest.`);
  }
  if (out.length === 0 && boxes.length > 0) {
    const steady = boxes.reduce((a, b) =>
      (b.q3 - b.q1) / b.median < (a.q3 - a.q1) / a.median ? b : a,
    );
    out.push(
      `Steadiest: ${who(steady.subject)} (the middle half of its images lies within ${ms(steady.q3 - steady.q1)}).`,
    );
  }
  return out;
}

/** 3 */
export function warmth(traces: Trace[]): string[] {
  const out: string[] = [];
  for (const t of traces) {
    const y = t.points.map((p) => p.y);
    if (y.length < 20) continue;
    const quarter = Math.floor(y.length / 4);
    const early = median(y.slice(10, 10 + quarter));
    const late = median(y.slice(y.length - quarter));
    const start = median(y.slice(0, 10));
    if (late > early * 1.1)
      out.push(
        `${who(t.subject)} slows by ${((late / early - 1) * 100).toFixed(0)}% towards the end of the run: the machine may be heating up.`,
      );
    else if (start > early * 1.2)
      out.push(
        `${who(t.subject)} starts ${((start / early - 1) * 100).toFixed(0)}% slow: its warm-up may be too short.`,
      );
  }
  return out;
}

/** 4 */
export function bottleneck(rows: Stages[]): string[] {
  const out = rows
    .filter((r) => r.post > r.model)
    .map(
      (r) =>
        `${who(r.subject)}: postprocess (${ms(r.post)}) takes longer than the model (${ms(r.model)}), so a faster format will not help; the decode and NMS are the bottleneck.`,
    );
  if (out.length === 0 && rows.length > 0) {
    const r = rows[0];
    if (r)
      out.push(
        `The model itself is the largest share of every run's time (${who(r.subject)}: ${((r.model / (r.pre + r.model + r.post)) * 100).toFixed(0)}%).`,
      );
  }
  return out;
}

/** 5 */
export function threading(lines: ThreadLine[]): string[] {
  const out: string[] = [];
  for (const l of lines) {
    const best = l.points.reduce((a, p) => (p.y < a.y ? p : a));
    const last = l.points[l.points.length - 1];
    if (last && best.x !== last.x && last.y > best.y * 1.05)
      out.push(
        `${l.label} is fastest at ${String(best.x)} threads and slower beyond that: too many threads for this CPU.`,
      );
    else {
      const second = l.points[l.points.length - 2];
      if (last && second && second.y / last.y < 1.05)
        out.push(
          `${l.label}: going from ${String(second.x)} to ${String(last.x)} threads buys under 5%.`,
        );
    }
  }
  return out;
}

/** 6 */
export function speedupFlags(rows: Speedup[]): string[] {
  const out: string[] = [];
  for (const r of rows) {
    if (r.crossesOne)
      out.push(
        `${who(r.subject)}: the interval around ${r.ratio.toFixed(2)}x crosses 1.0, so it is not provably faster or slower than the reference.`,
      );
    if (r.subject.run.precision === "INT8" && r.ratio < 1)
      out.push(`${who(r.subject)} is INT8 and slower than the reference (${r.ratio.toFixed(2)}x).`);
  }
  return out;
}

/** 7 */
export function driftFlags(rows: Drift[], band: number): string[] {
  const out: string[] = [];
  for (const r of rows) {
    if (r.zero)
      out.push(
        `${who(r.subject)} found nothing at all: its conversion or quantization probably broke it.`,
      );
    else if (r.outside)
      out.push(
        `${who(r.subject)} lost ${(-r.points).toFixed(1)} points, more than the ${String(band)} allowed.`,
      );
    else if (r.points > band)
      out.push(
        `${who(r.subject)} is ${r.points.toFixed(1)} points above the reference: not a conversion effect, so it is a different model or the reference is not the strongest.`,
      );
  }
  if (out.length === 0 && rows.length > 1)
    out.push(`Every run is within ${String(band)} points of the reference.`);
  return out;
}

/** 8 */
export function classFlags(h: ClassHeat): string[] {
  const out: string[] = [];
  const overall = h.subjects
    .map((s) => s.run.result?.accuracy?.map50_95)
    .filter((v): v is number => v !== undefined);
  const flat = overall.length > 1 && Math.max(...overall) - Math.min(...overall) < 0.05;
  for (const c of h.classes) {
    const v = c.cells.filter((x): x is number => x !== undefined);
    if (flat && v.length > 1 && Math.max(...v) - Math.min(...v) >= 0.15)
      out.push(
        `${c.name} falls from ${pct(Math.max(...v))} to ${pct(Math.min(...v))} across these runs while their averages are close: the average hides it.`,
      );
    if (c.instances < 5)
      out.push(
        `${c.name} has only ${String(c.instances)} labelled examples, so its numbers are shaky.`,
      );
  }
  return out;
}

/** 9 */
export function confusionFlags(c: Confusion): string[] {
  const out = c.top
    .slice(0, 2)
    .map(
      (t) =>
        `${t.truth} is taken for ${t.answer} ${String(t.count)} time${t.count === 1 ? "" : "s"}.`,
    );
  for (const m of c.missed)
    if (m.total > 0 && m.missed / m.total >= 0.3)
      out.push(
        `${String(m.missed)} of the ${String(m.total)} ${m.name} objects were not found at all.`,
      );
  return out;
}

/** 10: one sentence for all the runs (with thin data nearly every run jumps, and ten identical sentences help nobody). */
export function steepness(lines: Line[]): string[] {
  const jumps = lines
    .map((l) => ({
      l,
      jump: Math.max(0, ...l.points.slice(1).map((p, k) => Math.abs(p.x - (l.points[k]?.x ?? 0)))),
    }))
    .filter((j) => j.jump >= 0.1);
  const worst = jumps.reduce<(typeof jumps)[number] | undefined>(
    (a, j) => (!a || j.jump > a.jump ? j : a),
    undefined,
  );
  if (!worst) return [];
  const who2 =
    jumps.length === lines.length
      ? "Every run"
      : `${String(jumps.length)} of ${String(lines.length)} runs`;
  return [
    `${who2} change the share of real objects found by ${pct(worst.jump)} or more between two neighbouring cut-offs (most for ${who(worst.l.subject)}), so a small change in the cut-off changes a lot.`,
  ];
}

/** 11 */
export function peaks(lines: Line[], used = 0.25): string[] {
  return lines.flatMap((l) => {
    const p = l.peak === undefined ? undefined : l.points[l.peak];
    return p && Math.abs(p.x - used) > 0.2
      ? [
          `${who(l.subject)}: the best balance of misses and false alarms (F1) is at a cut-off of ${p.x.toFixed(2)}, far from the ${String(used)} the counts use.`,
        ]
      : [];
  });
}

/** 12 */
export function scoreShift(
  rows: ScoreHist[],
  ref: { long: string } | undefined,
  refMean: number | undefined,
): string[] {
  if (!ref || refMean === undefined) return [];
  return rows.flatMap((r) =>
    refMean - r.mean > 0.1
      ? [
          `${who(r.subject)}: its scores sit ${((refMean - r.mean) * 100).toFixed(0)} points lower than ${who(ref)}'s, so a fixed cut-off would drop real items.`,
        ]
      : [],
  );
}

/** 13 */
export function heat(rows: Machine[]): string[] {
  const out: string[] = [];
  for (const m of rows) {
    if (m.throttledAt.length > 0)
      out.push(
        `${who(m.subject)}: the machine said it was throttling during the run (${String(m.throttledAt.length)} readings); the run is flagged, not hidden.`,
      );
    const temps = m.temp.filter((v): v is number => v !== null);
    const clocks = m.clock.filter((v): v is number => v !== null);
    if (temps.length > 4 && clocks.length > 4) {
      const q = Math.max(1, Math.floor(temps.length / 4));
      const hotter = median(temps.slice(-q)) - median(temps.slice(0, q));
      const slower = 1 - median(clocks.slice(-q)) / median(clocks.slice(0, q));
      if (hotter >= 8 && slower >= 0.05)
        out.push(
          `${who(m.subject)}: it got ${hotter.toFixed(0)} degrees hotter while the clock fell ${(slower * 100).toFixed(0)}%, which is throttling.`,
        );
    }
  }
  return out;
}

/** 14 */
export function devices(pairs: DevicePair[]): string[] {
  const out = pairs.map(
    (p) =>
      `${p.title}: ${p.devices[p.devices.length - 1]?.device ?? ""} is ${p.ratio.toFixed(1)}x slower than ${p.devices[0]?.device ?? ""}.`,
  );
  const fastest = new Map<string, { title: string; ms: number }>();
  for (const p of pairs)
    for (const d of p.devices) {
      const have = fastest.get(d.device);
      if (!have || d.ms < have.ms) fastest.set(d.device, { title: p.title, ms: d.ms });
    }
  if (new Set([...fastest.values()].map((v) => v.title)).size > 1)
    out.push("The fastest choice is not the same on every device.");
  return out;
}

/** 15 */
export function sources(s: BySource): string[] {
  return s.subjects.flatMap((subject, i) => {
    const v = s.sources.flatMap((x) =>
      x.cells[i] ? [{ name: x.name, map: (x.cells[i] as { map: number }).map }] : [],
    );
    if (v.length < 2) return [];
    const hi = v.reduce((a, b) => (b.map > a.map ? b : a));
    const lo = v.reduce((a, b) => (b.map < a.map ? b : a));
    return hi.map - lo.map >= 0.1
      ? [
          `${who(subject)}: ${pct(hi.map)} on ${hi.name} but ${pct(lo.map)} on ${lo.name}. The data you train on may not be the data you deploy on.`,
        ]
      : [];
  });
}

/** 17 */
export function scoreSentence(c: Scorecard, names: string[]): string[] {
  if (!c.winner) return [];
  const out = [`First by your priorities (${names.join(", then ")}): ${who(c.winner)}.`];
  if (c.sensitive)
    out.push(
      "The winner changes if your first two priorities swap places, so this choice depends on what you value most.",
    );
  return out;
}
