// Dashboard highlights, computed from the runs with the rule written out ("fastest on this device within 5 points of the best
// accuracy"). Pure (no browser), tested in e2e/explorer.spec.ts.
import { headline } from "./metrics.ts";
import type { RunInfo } from "./runs.ts";

export interface Highlight {
  /** Where: dataset version and device. */
  place: string;
  run: RunInfo;
  ms: number;
  accuracy: number;
  /** The most accurate run in that place, for the comparison. */
  best: RunInfo;
  sentence: string;
  rule: string;
  /** Runs to open in Compare to see why. */
  compare: number[];
}

const label = (r: RunInfo) =>
  `${r.model_name ?? "a removed model"}, ${r.variant_label}, ${String(r.params?.threads ?? "?")} thread${r.params?.threads === 1 ? "" : "s"}`;

/**
 * For each dataset version and device: the fastest run whose accuracy is within ``band`` points of the best accuracy there. Only runs
 * with a measured accuracy and a clean speed count (a throttled run has no speed), and a place needs at least two such runs.
 */
export function highlights(runs: RunInfo[], band: number): Highlight[] {
  const places = new Map<string, RunInfo[]>();
  for (const r of runs) {
    const acc = r.result?.accuracy?.available ? r.result.accuracy.map50_95 : undefined;
    if (
      r.status !== "done" ||
      acc === undefined ||
      headline(r) === undefined ||
      r.model_id === null
    )
      continue;
    const key = `${String(r.dataset_id)}:${String(r.dataset_version)}:${String(r.device_id)}`;
    places.set(key, [...(places.get(key) ?? []), r]);
  }
  const out: Highlight[] = [];
  for (const members of places.values()) {
    if (members.length < 2) continue;
    const acc = (r: RunInfo) => r.result?.accuracy?.map50_95 ?? 0;
    const best = members.reduce((a, r) => (acc(r) > acc(a) ? r : a));
    const within = members.filter((r) => (acc(best) - acc(r)) * 100 <= band);
    const fastest = within.reduce((a, r) =>
      (headline(r) ?? Infinity) < (headline(a) ?? Infinity) ? r : a,
    );
    const place = `${best.dataset_name ?? "a removed dataset"} v${String(best.dataset_version ?? "?")} on ${best.device_name ?? "a removed device"}`;
    const ms = headline(fastest) ?? 0;
    out.push({
      place,
      run: fastest,
      ms,
      accuracy: acc(fastest),
      best,
      sentence: `Fastest on ${place}: ${label(fastest)}, ${ms.toFixed(1)} ms per picture at ${(acc(fastest) * 100).toFixed(1)}% accuracy.`,
      rule: `Among the ${String(members.length)} runs there, the fastest one within ${String(band)} points of the best accuracy (${(acc(best) * 100).toFixed(1)}%, ${label(best)}).`,
      compare: [...new Set([fastest.id, best.id])],
    });
  }
  return out.sort((a, b) => b.run.id - a.run.id).slice(0, 4);
}
