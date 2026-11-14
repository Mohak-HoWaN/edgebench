// The answer at the top of the Compare page, in plain words: which run to pick, given the limits you set and the priorities you
// ranked. Pure (no browser), tested in e2e/compare.spec.ts.
import { compareRuns, type Metric } from "../metrics.ts";
import type { RunInfo } from "../runs.ts";
import { mapOf, timeOf } from "./builders.ts";
import type { Subject } from "./subjects.ts";

/** What a run must meet to be considered. A missing limit means no limit. Accuracy is the 0 to 1 mAP50-95. */
export interface Limits {
  minAccuracy?: number;
  maxMs?: number;
  maxMb?: number;
}

export interface Verdict {
  winner: Subject | undefined;
  /** Runs that meet every limit, best first. */
  passes: Subject[];
  failed: { subject: Subject; reasons: string[] }[];
  headline: string;
  /** How the winner compares with each other run that meets the limits. */
  against: string[];
  notes: string[];
}

const megabytes = (r: RunInfo) => (r.size_bytes ? r.size_bytes / 1_048_576 : undefined);
const pct = (n: number) => `${(n * 100).toFixed(1)}%`;

/** Why a run misses the limits (empty when it meets them). A limit that cannot be checked counts as missed, and says so. */
export function missed(run: RunInfo, limits: Limits): string[] {
  const out: string[] = [];
  const acc = mapOf(run);
  const ms = timeOf(run);
  const mb = megabytes(run);
  if (limits.minAccuracy !== undefined) {
    if (acc === undefined) out.push("its accuracy was not measured");
    else if (acc < limits.minAccuracy)
      out.push(`less accurate than your limit (${pct(acc)}, you want ${pct(limits.minAccuracy)})`);
  }
  if (limits.maxMs !== undefined) {
    if (ms === undefined) out.push("its speed was not measured cleanly");
    else if (ms > limits.maxMs)
      out.push(
        `slower than your limit (${ms.toFixed(1)} ms, you allow ${limits.maxMs.toFixed(1)})`,
      );
  }
  if (limits.maxMb !== undefined) {
    if (mb === undefined) out.push("its file size is not known");
    else if (mb > limits.maxMb)
      out.push(
        `bigger than your limit (${mb.toFixed(1)} MB, you allow ${limits.maxMb.toFixed(1)})`,
      );
  }
  return out;
}

/** The winner against one other run, as three short comparisons: accuracy, speed, size. */
export function against(win: Subject, other: Subject): string {
  const parts: string[] = [];
  const a = mapOf(win.run);
  const b = mapOf(other.run);
  if (a !== undefined && b !== undefined) {
    const d = (a - b) * 100;
    parts.push(
      Math.abs(d) < 0.5
        ? "as accurate"
        : `${Math.abs(d).toFixed(1)} points ${d > 0 ? "more" : "less"} accurate`,
    );
  }
  const x = timeOf(win.run);
  const y = timeOf(other.run);
  if (x !== undefined && y !== undefined) {
    const lw = win.run.latency;
    const lo = other.run.latency;
    const proven =
      lw?.ci_half_width_ms != null &&
      lo?.ci_half_width_ms != null &&
      Math.abs(x - y) > lw.ci_half_width_ms + lo.ci_half_width_ms;
    const ratio = y / x;
    parts.push(
      !proven || Math.abs(ratio - 1) < 0.05
        ? "about the same speed"
        : ratio > 1
          ? `${ratio.toFixed(1)}x faster`
          : `${(1 / ratio).toFixed(1)}x slower`,
    );
  }
  const s = megabytes(win.run);
  const t = megabytes(other.run);
  if (s !== undefined && t !== undefined)
    parts.push(
      Math.abs(s / t - 1) < 0.03
        ? "the same size"
        : `${Math.abs((1 - s / t) * 100).toFixed(0)}% ${s < t ? "smaller" : "bigger"}`,
    );
  return `${other.long}: ${parts.join(", ") || "nothing to compare"}`;
}

export function verdict(subjects: Subject[], limits: Limits, metrics: Metric[]): Verdict {
  const checked = subjects.map((subject) => ({ subject, reasons: missed(subject.run, limits) }));
  const passes = checked
    .filter((c) => c.reasons.length === 0)
    .map((c) => c.subject)
    .sort((p, q) => compareRuns(p.run, q.run, metrics));
  const failed = checked.filter((c) => c.reasons.length > 0);
  const winner = passes[0];
  const notes: string[] = [];
  if (winner && passes.length > 1 && metrics.length >= 2) {
    const swapped = [metrics[1], metrics[0], ...metrics.slice(2)].flatMap((m) => (m ? [m] : []));
    const other = [...passes].sort((p, q) => compareRuns(p.run, q.run, swapped))[0];
    if (other && other.run.id !== winner.run.id)
      notes.push(
        "If you put your first two priorities the other way round, another run would win. The pick depends on what matters most to you.",
      );
  }
  const objects = Object.values(winner?.run.result?.accuracy?.per_class ?? {}).reduce(
    (sum, c) => sum + c.instances,
    0,
  );
  if (winner && objects > 0 && objects < 50)
    notes.push(
      `The accuracy numbers rest on only ${String(objects)} labelled objects, so small gaps could be chance.`,
    );
  return {
    winner,
    passes,
    failed,
    headline: winner
      ? `${winner.long} is the best pick.`
      : subjects.length === 0
        ? "Choose some runs to compare."
        : "None of these runs meets your limits.",
    against: winner ? passes.slice(1, 4).map((o) => against(winner, o)) : [],
    notes,
  };
}
