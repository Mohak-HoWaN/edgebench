import type { Comparison, Drift } from "./experiments";
import { bestRun, METRIC_BY_KEY, rankRuns, sameResult, throttled, type Metric } from "./metrics";
import type { RunInfo } from "./runs";

/** Which measurement a run is: the same variant at the same thread count and CPUs. A sweep has many of these per variant. */
export const configKey = (r: RunInfo) =>
  `${String(r.model_id)}|${String(r.variant_id)}|${String(r.params?.threads)}|${(r.params?.cpu_list ?? []).join(",")}`;

/** What the server worked out about the runs of an experiment: drift from the baseline and the significance of speed-ups. */
export interface Judgements {
  drift: Record<string, Drift>;
  comparisons: Record<string, Comparison>;
}

/** How a run is named in a sentence: its model and variant. */
export const nameOf = (r: RunInfo) => `${r.model_name ?? "A removed model"}, ${r.variant_label}`;

const signed = (n: number) => `${n >= 0 ? "+" : "-"}${Math.abs(n * 100).toFixed(1)} points`;

/**
 * Plain sentences worked out from an experiment's finished runs: who is fastest, who is most accurate, what is tied, what
 * differs from the PyTorch baseline, what did not finish and how much repeated runs disagree. Nothing here is static help.
 */
export function experimentInsights(
  runs: RunInfo[],
  metrics: Metric[],
  judged: Judgements = { drift: {}, comparisons: {} },
): string[] {
  const out: string[] = [];
  const done = runs.filter((r) => r.status === "done");
  const waiting = runs.filter((r) => r.status === "queued" || r.status === "running").length;
  if (waiting > 0)
    out.push(
      `${String(waiting)} of ${String(runs.length)} runs are still waiting or running; this changes as they finish.`,
    );
  if (done.length === 0) return [...out, "No run has finished yet."];

  const p50 = METRIC_BY_KEY.get("p50");
  const accuracy =
    metrics.find((m) => m.group === "accuracy" && m.key !== "mean_iou") ??
    METRIC_BY_KEY.get("map50_95");
  const fastest = p50 ? bestRun(done, p50) : undefined;
  const fastestMs = fastest && p50 ? p50.value(fastest) : undefined;
  if (fastest && fastestMs !== undefined) {
    out.push(
      `Fastest: ${nameOf(fastest)}, ${fastestMs.toFixed(1)} ms per image (about ${(1000 / fastestMs).toFixed(0)} images per second).`,
    );
  }

  const withAccuracy = accuracy ? done.filter((r) => accuracy.value(r) !== undefined) : [];
  if (accuracy && withAccuracy.length > 0) {
    const best = bestRun(withAccuracy, accuracy, metrics); // ties go to the next metric, as in the table
    const bestValue = best ? accuracy.value(best) : undefined;
    if (best && bestValue !== undefined) {
      out.push(
        `Most accurate by ${accuracy.label}: ${nameOf(best)}, ${accuracy.format(bestValue)}.`,
      );
      const sameAccuracy = withAccuracy.filter((r) => sameResult(accuracy, r, best));
      if (sameAccuracy.length > 1) {
        const quickest = p50 ? bestRun(sameAccuracy, p50) : undefined;
        out.push(
          `${String(sameAccuracy.length)} runs give the same ${accuracy.label} (${accuracy.format(bestValue)}), so accuracy cannot tell them apart${
            quickest ? `: speed decides, and ${nameOf(quickest)} is fastest of them` : ""
          }.`,
        );
      }
    }
  }

  // against the PyTorch baseline, if it was part of the experiment
  const baseline = done.find((r) => r.variant_id === null);
  if (baseline && p50) {
    const baseMs = p50.value(baseline);
    const others = done.filter((r) => r !== baseline);
    const quick = others.length > 0 ? bestRun(others, p50) : undefined;
    const quickMs = quick ? p50.value(quick) : undefined;
    if (quick && quickMs !== undefined && baseMs !== undefined && quickMs < baseMs) {
      const diff = (accuracy?.value(quick) ?? 0) - (accuracy?.value(baseline) ?? 0);
      const delta =
        accuracy?.value(quick) !== undefined && accuracy.value(baseline) !== undefined
          ? Math.abs(diff) < 0.0005
            ? `, with the same ${accuracy.label}`
            : `, with ${signed(diff)} of ${accuracy.label} compared with it`
          : "";
      out.push(
        `${nameOf(quick)} is ${(baseMs / quickMs).toFixed(1)}x faster than the PyTorch baseline${delta}.`,
      );
      const c = judged.comparisons[String(quick.id)];
      if (c?.significant === false)
        out.push(
          `That speed-up is within the noise (p = ${c.p?.toFixed(2) ?? "?"}): the repeats overlap too much to call it real. More repeats would settle it.`,
        );
      else if (c?.significant === null && c.note)
        out.push(`No significance test for it: ${c.note}.`);
    }
    if (accuracy?.value(baseline) !== undefined) {
      const base = accuracy.value(baseline) ?? 0;
      const moved = others
        .filter((r) => accuracy.value(r) !== undefined)
        .map((r) => ({ r, d: (accuracy.value(r) ?? 0) - base }))
        .sort((a, b) => Math.abs(b.d) - Math.abs(a.d))[0];
      if (moved && Math.abs(moved.d) >= 0.0005) {
        out.push(
          `The variant furthest from the baseline in ${accuracy.label} is ${nameOf(moved.r)}: ${signed(moved.d)}.`,
        );
      } else if (others.length > 0) {
        out.push(
          `No variant differs from the PyTorch baseline by more than 0.1 point of ${accuracy.label}.`,
        );
      }
    }
  }

  // accuracy check against the baseline, and runs the machine throttled
  for (const r of done) {
    const d = judged.drift[String(r.id)];
    if (d && !d.verdict.passed)
      out.push(
        `${nameOf(r)} fails the accuracy check against the PyTorch baseline: ${d.verdict.reasons.join("; ")}. Its speed does not make up for that.`,
      );
  }
  const hot = done.filter(throttled);
  if (hot.length > 0)
    out.push(
      `${String(hot.length)} run${hot.length === 1 ? " was" : "s were"} throttled (${hot
        .slice(0, 3)
        .map(nameOf)
        .join(
          "; ",
        )}): the machine slowed down while it ran, so ${hot.length === 1 ? "its" : "their"} speed is left out of the ranking. Run again once it has cooled.`,
    );

  // repeats of the same measurement (same variant, threads and CPUs; a sweep over threads is not a repeat)
  const groups = new Map<string, RunInfo[]>();
  for (const r of done) groups.set(configKey(r), [...(groups.get(configKey(r)) ?? []), r]);
  for (const group of groups.values()) {
    const times = group.map((r) => p50?.value(r)).filter((v): v is number => v !== undefined);
    const [head] = group;
    if (head && group.length > 1 && times.length > 1) {
      const lo = Math.min(...times);
      const hi = Math.max(...times);
      out.push(
        `${nameOf(head)} was run ${String(group.length)} times: median time from ${lo.toFixed(1)} to ${hi.toFixed(1)} ms (${(((hi - lo) / lo) * 100).toFixed(0)}% apart). Differences smaller than that are noise.`,
      );
    }
  }
  const withInterval = done.filter((r) => (r.latency?.n ?? 1) >= 2).length;
  if (!Array.from(groups.values()).some((g) => g.length > 1) && done.length > 1) {
    out.push(
      withInterval === 0
        ? "Each variant was run once. Run one again before trusting a small difference."
        : withInterval === done.length
          ? "Each run has several timed repeats, so its speed carries an interval; a difference smaller than the interval is noise."
          : "Some runs have a single repeat and so no error bar. Use more repeats before trusting a small difference.",
    );
  }

  const problems = runs.filter((r) =>
    ["failed", "unavailable", "cancelled", "lost"].includes(r.status),
  );
  if (problems.length > 0) {
    out.push(
      `${String(problems.length)} run${problems.length === 1 ? "" : "s"} did not finish: ${problems
        .slice(0, 3)
        .map((r) => `${nameOf(r)} (${r.status})`)
        .join("; ")}${problems.length > 3 ? "; and more" : ""}.`,
    );
  }
  return out;
}

/** Sentences about one run, with where it stands in its experiment. */
export function runInsights(run: RunInfo, siblings: RunInfo[], metrics: Metric[]): string[] {
  const out: string[] = [];
  const res = run.result;
  const stages = res?.speed?.stages;
  if (!res || !stages) return out;
  const total = stages.total;
  out.push(
    `About ${(1000 / total.p50).toFixed(0)} images per second at the median time of ${total.p50.toFixed(1)} ms.`,
  );
  const parts = ["preprocess", "inference", "postprocess"] as const;
  const sum = parts.reduce((s, k) => s + stages[k].mean, 0);
  if (sum > 0) {
    const share = (k: (typeof parts)[number]) => Math.round((stages[k].mean / sum) * 100);
    out.push(
      `Time per image: ${String(share("inference"))}% in the model, ${String(share("preprocess"))}% preparing the picture, ${String(share("postprocess"))}% decoding the answer.`,
    );
    if (stages.postprocess.mean > stages.inference.mean)
      out.push(
        "Decoding takes longer than the model itself, so a faster format would not help much here.",
      );
  }
  const spread = total.p95 / total.p50;
  out.push(
    spread > 1.5
      ? `Uneven: the slowest 1 in 20 images take ${total.p95.toFixed(1)} ms or more, ${spread.toFixed(1)}x the median.`
      : `Steady: the slowest 1 in 20 images take ${total.p95.toFixed(1)} ms, within ${((spread - 1) * 100).toFixed(0)}% of the median.`,
  );
  if (res.first_inference_ms !== undefined && res.first_inference_ms > total.p50 * 1.3) {
    out.push(
      `The first image took ${res.first_inference_ms.toFixed(1)} ms, ${(res.first_inference_ms / total.p50).toFixed(1)}x a typical one; that start-up cost is left out of the figures above.`,
    );
  }
  const a = res.accuracy;
  if (a?.available && a.recall !== undefined && a.precision !== undefined) {
    out.push(
      `Finds ${(a.recall * 100).toFixed(0)}% of the objects, and ${(a.precision * 100).toFixed(0)}% of what it reports is right (at confidence ${a.confidence_at_best_f1?.toFixed(2) ?? "?"}).`,
    );
    const classes = Object.entries(a.per_class ?? {}).sort((x, y) => x[1].ap50_95 - y[1].ap50_95);
    const weakest = classes[0];
    const strongest = classes[classes.length - 1];
    if (weakest && strongest && classes.length > 1) {
      const few =
        weakest[1].instances < 5
          ? ` (only ${String(weakest[1].instances)} examples, so be careful)`
          : "";
      out.push(
        `Weakest class: ${weakest[0]}, ${(weakest[1].ap50_95 * 100).toFixed(1)}% mAP50-95${few}. Strongest: ${strongest[0]}, ${(strongest[1].ap50_95 * 100).toFixed(1)}%.`,
      );
    }
  }
  const first = metrics[0];
  if (first && siblings.length > 1 && first.value(run) !== undefined) {
    const ranked = rankRuns(
      siblings.filter((r) => r.status === "done"),
      metrics,
    );
    const place = ranked.findIndex((r) => r.id === run.id) + 1;
    if (place > 0)
      out.push(
        `Ranks ${String(place)} of ${String(ranked.length)} in this experiment by ${first.label}, then by your next priorities.`,
      );
  }
  return out;
}
