// No browser here: the comparison is pure logic, so these tests call it directly. Each interpretation rule has a case that
// triggers it and one that does not.
import { expect, test } from "@playwright/test";
import * as b from "../src/lib/compare/builders.ts";
import * as i from "../src/lib/compare/interpret.ts";
import {
  cannotAdd,
  MAX_MODELS,
  MAX_RUNS,
  notesFor,
  subjectsOf,
  suggestions,
  type Subject,
} from "../src/lib/compare/subjects.ts";
import { specSheet } from "../src/lib/compare/spec.ts";
import { missed as missedBecause, verdict as verdictOf } from "../src/lib/compare/verdict.ts";
import { METRIC_BY_KEY, type Metric } from "../src/lib/metrics.ts";
import type { RunInfo } from "../src/lib/runs.ts";
import { run } from "./fixtures/compare-runs.ts";

const subs = (runs: RunInfo[]): Subject[] =>
  subjectsOf(
    runs,
    runs.map((r) => r.id),
  );
const metric = (key: string): Metric => {
  const m = METRIC_BY_KEY.get(key);
  if (!m) throw new Error(key);
  return m;
};
const flat = (xs: string[]) => xs.join(" ");

test("each model gets a colour, the format a shape, the precision a fill; the limits are explained", () => {
  const runs = [
    run({ model: 1 }),
    run({ model: 2, format: "OpenVINO", precision: "FP16" }),
    run({ model: 3, format: "ncnn", precision: "INT8" }),
    run({ model: 4 }),
  ];
  const s = subs(runs);
  expect(s.map((x) => [x.color, x.shape, x.fill])).toEqual([
    [0, "circle", "solid"],
    [1, "diamond", "soft"],
    [2, "square", "hollow"],
  ]); // the fourth model is not taken
  expect(s[0]?.label).toBe("ONNX FP32 · 1 thread");
  expect(cannotAdd(s, runs[3])).toContain(`Up to ${String(MAX_MODELS)} models`);
  expect(cannotAdd(s, runs[0])).toBeNull();
  const many = Array.from({ length: MAX_RUNS }, () => run());
  expect(cannotAdd(subs(many), run())).toContain(`Up to ${String(MAX_RUNS)} runs`);
});

test("it says what differs between the selected runs, and repeats the tools' warnings", () => {
  expect(notesFor(subs([run(), run()]))).toEqual([]);
  const notes = flat(
    notesFor(
      subs([
        run({ version: 1 }),
        run({ version: 2, device: 2, threads: 4, diagnosis: ["built by an older library"] }),
      ]),
    ),
  );
  expect(notes).toContain("different datasets");
  expect(notes).toContain("different devices");
  expect(notes).toContain("different thread settings");
  expect(notes).toContain("built by an older library");
});

test("suggestions find the same variant across models, variants of a model, thread sweeps and device pairs, newest run each", () => {
  const old = run({ model: 1, ms: 9 });
  const runs = [
    old,
    run({ model: 1, ms: 10 }),
    run({ model: 2, ms: 11 }),
    run({ model: 1, format: "ncnn", ms: 12 }),
    run({ model: 1, threads: 4, ms: 5 }),
    run({ model: 1, device: 2, ms: 40 }),
    run({ model: 2, status: "failed" }),
  ];
  const kinds = suggestions(runs).map((x) => x.kind);
  expect(new Set(kinds)).toEqual(new Set(["models", "variants", "threads", "devices"]));
  const models = suggestions(runs).find((x) => x.kind === "models");
  expect(models?.runIds).not.toContain(old.id); // the older of two runs of the same thing is not offered
  expect(models?.runIds).toHaveLength(2);
  expect(suggestions([run(), run({ model: 2, threads: 2 })])).toEqual([]);
});

test("front: owned by one model, dominated runs listed, thin data said to be thin", () => {
  const owned = b.accuracySpeed(
    subs([run({ model: 1, ms: 20, map: 0.5 }), run({ model: 2, ms: 10, map: 0.6 })]),
  );
  expect(flat(i.front(owned, { x: "a speed", y: "an accuracy" }))).toContain(
    "New has all the best trade-offs",
  );
  expect(flat(i.front(owned, { x: "a speed", y: "an accuracy" }))).toContain(
    "Beaten on both counts",
  );
  const shared = b.accuracySpeed(
    subs([run({ model: 1, ms: 20, map: 0.7 }), run({ model: 2, ms: 10, map: 0.6 })]),
  );
  expect(flat(i.front(shared, { x: "a", y: "b" }))).not.toContain("has all the best");
  expect(i.front(owned.slice(0, 1), { x: "a speed", y: "an accuracy" })[0]).toContain(
    "at least two",
  );
  expect(
    i.accuracyFlat(b.accuracySpeed(subs([run({ ms: 10, map: 0.5 }), run({ ms: 12, map: 0.502 })]))),
  ).toHaveLength(1);
  expect(i.accuracyFlat(owned)).toHaveLength(0);
});

test("size against accuracy: a big saving that costs accuracy is called out, a free one is not", () => {
  const costly = b.sizeAccuracy(
    subs([run({ size: 10e6, map: 0.9 }), run({ size: 5e6, map: 0.8 })]),
  );
  expect(flat(i.sizeCost(costly))).toContain("smaller");
  expect(
    i.sizeCost(b.sizeAccuracy(subs([run({ size: 10e6, map: 0.9 }), run({ size: 5e6, map: 0.9 })]))),
  ).toEqual([]);
});

test("latency distribution: boxes, whiskers, outliers, and the two red flags", () => {
  const calm = Array.from({ length: 100 }, (_, k) => 10 + (k % 5) * 0.1);
  const bad = [...calm.slice(0, 90), ...Array.from({ length: 10 }, () => 40)];
  const boxes = b.latencyBoxes(subs([run({ samples: calm }), run({ model: 2, samples: bad })]));
  expect(boxes[0]?.outliers).toEqual([]);
  expect(boxes[1]?.outliers.length).toBe(10);
  expect(flat(i.spread(boxes))).toContain("1 in 100");
  expect(flat(i.spread(boxes))).toContain("1 image in 20");
  expect(flat(i.spread([boxes[0]]))).toContain("Steadiest");
  expect(b.latencyBoxes(subs([run()]))).toEqual([]); // no samples recorded for this run
});

test("latency over the run: heat and a slow start are flagged, a flat line is not", () => {
  const flatRun = Array.from({ length: 200 }, () => 10);
  const climbing = Array.from({ length: 200 }, (_, k) => 10 + k * 0.05);
  const slowStart = Array.from({ length: 200 }, (_, k) => (k < 12 ? 30 : 10));
  expect(i.warmth(b.overTime(subs([run({ samples: flatRun })])))).toEqual([]);
  expect(flat(i.warmth(b.overTime(subs([run({ samples: climbing })]))))).toContain("heating up");
  expect(flat(i.warmth(b.overTime(subs([run({ samples: slowStart })]))))).toContain("warm-up");
  expect(b.overTime(subs([run({ samples: [1, 2] })]))).toEqual([]);
});

test("where the time goes: a postprocess that outweighs the model is the bottleneck", () => {
  expect(flat(i.bottleneck(b.stages(subs([run({ stages: [1, 5, 9] })]))))).toContain("bottleneck");
  expect(flat(i.bottleneck(b.stages(subs([run({ stages: [1, 9, 2] })]))))).toContain(
    "largest share",
  );
});

test("speed against threads: a fall after the peak and no gain are called out; one thread count draws no line", () => {
  const rise = b.threadLines(
    subs([run({ threads: 1, ms: 20 }), run({ threads: 4, ms: 8 }), run({ threads: 8, ms: 12 })]),
  );
  expect(flat(i.threading(rise))).toContain("too many threads");
  const plateau = b.threadLines(
    subs([run({ threads: 1, ms: 20 }), run({ threads: 4, ms: 8 }), run({ threads: 8, ms: 7.9 })]),
  );
  expect(flat(i.threading(plateau))).toContain("under 5%");
  expect(
    i.threading(
      b.threadLines(
        subs([run({ threads: 1, ms: 20 }), run({ threads: 4, ms: 8 }), run({ threads: 8, ms: 4 })]),
      ),
    ),
  ).toEqual([]);
  expect(b.threadLines(subs([run({ ms: 10 }), run({ ms: 11 })]))).toEqual([]);
});

test("speed-up: an interval across 1.0 and a slow INT8 are flagged", () => {
  const s = subs([
    run({ ms: 10, ci: 1 }),
    run({ ms: 9.5, ci: 1, precision: "FP16" }),
    run({ ms: 20, ci: 0.1, precision: "INT8" }),
  ]);
  const rows = b.speedups(s, s[0]);
  expect(rows[0]?.ratio).toBe(1);
  expect(flat(i.speedupFlags(rows))).toContain("crosses 1.0");
  expect(flat(i.speedupFlags(rows))).toContain("INT8 and slower");
  const clear = subs([run({ ms: 10, ci: 0.1 }), run({ ms: 5, ci: 0.1 })]);
  expect(i.speedupFlags(b.speedups(clear, clear[0]))).toEqual([]);
  expect(b.speedups(clear, undefined)).toEqual([]);
});

test("drift: a drop beyond the band and a run that found nothing are flagged", () => {
  const s = subs([
    run({ map: 0.8 }),
    run({ map: 0.7 }),
    run({ map: 0, recall: 0 }),
    run({ map: 0.79 }),
  ]);
  const rows = b.drifts(s, s[0], 5);
  expect(rows.map((r) => [r.outside, r.zero])).toEqual([
    [false, false],
    [true, false],
    [true, true],
    [false, false],
  ]);
  expect(flat(i.driftFlags(rows, 5))).toContain("lost 10.0 points");
  expect(flat(i.driftFlags(rows, 5))).toContain("found nothing");
  const above = b.drifts(subs([run({ map: 0.7 }), run({ map: 0.85 })]), undefined, 5);
  expect(above).toEqual([]); // without a reference nothing is measured
  const withRef = subs([run({ map: 0.7 }), run({ map: 0.85 })]);
  expect(flat(i.driftFlags(b.drifts(withRef, withRef[0], 5), 5))).toContain(
    "15.0 points above the reference",
  );
  const fine = b.drifts(subs([run({ map: 0.8 }), run({ map: 0.79 })]), undefined, 5);
  expect(fine).toEqual([]);
  expect(
    flat(
      i.driftFlags(
        b.drifts(
          s.filter((_, k) => k % 3 === 0),
          s[0],
          5,
        ),
        5,
      ),
    ),
  ).toContain("within 5 points");
});

test("per class: a class the average hides, and a class with few examples", () => {
  const s = subs([
    run({ map: 0.7, classes: { chips: 0.9, oreo: 0.5 }, instances: 3 }),
    run({ map: 0.72, classes: { chips: 0.9, oreo: 0.1 }, instances: 3 }),
  ]);
  const heat = b.classHeat(s);
  expect(heat.classes.map((c) => c.name).sort()).toEqual(["chips", "oreo"]);
  expect(flat(i.classFlags(heat))).toContain("the average hides it");
  expect(flat(i.classFlags(heat))).toContain("only 3 labelled examples");
  expect(
    i.classFlags(
      b.classHeat(
        subs([
          run({ map: 0.7, classes: { chips: 0.9 } }),
          run({ map: 0.7, classes: { chips: 0.88 } }),
        ]),
      ),
    ),
  ).toEqual([]);
});

test("confusion: the biggest mistakes in words, and a class that is mostly missed", () => {
  const labels = ["chips", "oreo", "background"];
  const c = b.confusion(
    subs([
      run({
        map: 0.5,
        confusion: {
          labels,
          matrix: [
            [5, 3, 2],
            [0, 10, 0],
            [0, 0, 0],
          ],
        },
      }),
    ])[0],
  );
  expect(c?.top[0]).toEqual({ truth: "chips", answer: "oreo", count: 3 });
  expect(flat(i.confusionFlags(c ?? { labels: [], matrix: [], top: [], missed: [] }))).toContain(
    "chips is taken for oreo 3 times",
  );
  const mostlyMissed = b.confusion(
    subs([
      run({
        map: 0.5,
        confusion: {
          labels,
          matrix: [
            [2, 0, 8],
            [0, 10, 0],
            [0, 0, 0],
          ],
        },
      }),
    ])[0],
  );
  expect(
    flat(i.confusionFlags(mostlyMissed ?? { labels: [], matrix: [], top: [], missed: [] })),
  ).toContain("8 of the 10 chips");
  expect(b.confusion(undefined)).toBeUndefined();
});

test("curves: precision-recall and F1 lines per run or per class, only for runs that recorded them", () => {
  const s = subs([run({ map: 0.5, curves: true }), run({ map: 0.5 })]);
  expect(b.prLines(s, null)).toHaveLength(1);
  expect(b.prLines(s, "chips")[0]?.points).toHaveLength(51);
  expect(b.classesWithCurves(s)).toEqual(["chips"]);
  const f = b.f1Lines(s, null);
  expect(f[0]?.points[f[0].peak ?? 0]?.x).toBeCloseTo(0.5);
  expect(flat(i.peaks(f))).toContain("far from the 0.25");
  expect(i.peaks(f, 0.5)).toEqual([]);
  const smooth = b.prLines(s, null);
  expect(i.steepness(smooth)).toEqual([]); // recall moves 2 points per step here
  const cliff: b.Line = {
    subject: smooth[0]?.subject,
    points: [
      { x: 1, y: 0.9 },
      { x: 0.6, y: 0.95 },
    ],
  };
  expect(flat(i.steepness([cliff]))).toContain(
    "change the share of real objects found by 40.0% or more",
  );
});

test("scores: a distribution shifted to the left of the reference is flagged", () => {
  const high = Array.from({ length: 20 }, (_, k) => (k >= 16 ? 10 : 0));
  const low = Array.from({ length: 20 }, (_, k) => (k >= 8 && k < 12 ? 10 : 0));
  const rows = b.scoreHists(subs([run({ map: 0.5, hist: high }), run({ map: 0.5, hist: low })]));
  expect(flat(i.scoreShift(rows, rows[0]?.subject, rows[0]?.mean))).toContain("sit");
  expect(i.scoreShift(rows.slice(0, 1), rows[0]?.subject, rows[0]?.mean)).toEqual([]);
});

test("temperature and clock: throttling readings and heat with a falling clock are flagged", () => {
  const temp = [50, 51, 52, 53, 60, 61, 62, 63];
  const hot = b.machine(
    subs([
      run({
        series: {
          temp,
          clock: [3000, 3000, 3000, 3000, 2500, 2500, 2500, 2500],
          throttled: temp.map((_, k) => k > 5),
        },
      }),
    ]),
  );
  expect(flat(i.heat(hot))).toContain("throttling during the run");
  expect(flat(i.heat(hot))).toContain("which is throttling");
  const cool = b.machine(
    subs([
      run({
        series: { temp: [50, 50, 50, 50, 50, 50], clock: [3000, 3000, 3000, 3000, 3000, 3000] },
      }),
    ]),
  );
  expect(i.heat(cool)).toEqual([]);
  expect(b.machine(subs([run()]))).toEqual([]);
});

test("devices: how much slower, and whether the best choice differs between devices", () => {
  const pairs = b.devicePairs(subs([run({ ms: 10 }), run({ ms: 40, device: 2 })]));
  expect(pairs[0]?.ratio).toBe(4);
  expect(flat(i.devices(pairs))).toContain("Pi is 4.0x slower than PC");
  const split = b.devicePairs(
    subs([
      run({ ms: 10 }),
      run({ ms: 40, device: 2 }),
      run({ format: "ncnn", ms: 12 }),
      run({ format: "ncnn", ms: 30, device: 2 }),
    ]),
  );
  expect(flat(i.devices(split))).toContain("not the same on every device");
  expect(flat(i.devices(pairs))).not.toContain("not the same");
  expect(b.devicePairs(subs([run({ ms: 10 })]))).toEqual([]);
});

test("capture source: a big gap between sources is flagged", () => {
  const gap = b.bySource(subs([run({ map: 0.5, sources: { "rpi-cam3-wide": 0.5, mobile: 0.9 } })]));
  expect(flat(i.sources(gap))).toContain("may not be the data you deploy on");
  expect(i.sources(b.bySource(subs([run({ map: 0.5, sources: { a: 0.8, b: 0.85 } })])))).toEqual(
    [],
  );
});

test("scorecard: ordered by the priorities, best marked, and flagged when swapping the first two priorities changes the winner", () => {
  const map = metric("map50_95");
  const time = metric("p50");
  const s = subs([run({ map: 0.5, ms: 10 }), run({ model: 2, map: 0.6, ms: 20 })]);
  const card = b.scorecard(s, [map, time]);
  expect(card.winner?.run.model_id).toBe(2);
  expect(card.sensitive).toBe(true);
  expect(flat(i.scoreSentence(card, ["mAP50-95", "median time"]))).toContain(
    "depends on what you value most",
  );
  expect(card.rows.map((r) => r.cells.filter((c) => c.best).length)).toEqual([1, 1]);
  const stable = b.scorecard(
    subs([run({ map: 0.5, ms: 20 }), run({ model: 2, map: 0.6, ms: 10 })]),
    [map, time],
  );
  expect(stable.sensitive).toBe(false);
  expect(i.scoreSentence(stable, ["mAP50-95"]).join(" ")).not.toContain("depends on");
});

test("the verdict picks the best run that meets your limits and says why the others lost", () => {
  const map = metric("map50_95");
  const time = metric("p50");
  const s = subs([
    run({ map: 0.9, ms: 40, ci: 1, size: 10e6 }),
    run({ model: 2, map: 0.9, ms: 20, ci: 1, size: 10e6 }),
    run({ model: 3, map: 0.6, ms: 5, ci: 1, size: 3e6 }),
  ]);
  const v = verdictOf(s, { minAccuracy: 0.8 }, [map, time]);
  expect(v.winner?.run.model_id).toBe(2);
  expect(v.headline).toContain("is the best pick");
  expect(v.failed.map((f) => f.subject.run.model_id)).toEqual([3]);
  expect(flat(v.failed[0]?.reasons ?? [])).toContain("less accurate than your limit");
  expect(v.against[0]).toMatch(/as accurate, 2\.0x faster, the same size/);
  expect(verdictOf(s, { minAccuracy: 0.99 }, [map, time]).headline).toBe(
    "None of these runs meets your limits.",
  );
  expect(verdictOf(s, { maxMs: 10 }, [map, time]).winner?.run.model_id).toBe(3);
  expect(verdictOf([], {}, [map, time]).headline).toContain("Choose some runs");
});

test("a limit that cannot be checked counts as missed, and a thin or sensitive pick is said to be", () => {
  const map = metric("map50_95");
  const time = metric("p50");
  const s = subs([
    run({ map: 0.9, ms: null, instances: 3 }),
    run({ model: 2, map: 0.8, ms: 20, instances: 3 }),
  ]);
  expect(flat(missedBecause(s[0]?.run, { maxMs: 50 }))).toContain("speed was not measured");
  const v = verdictOf(s, {}, [map, time]);
  expect(flat(v.notes)).toContain("only 3 labelled objects");
  const flip = verdictOf(
    subs([run({ map: 0.9, ms: 40 }), run({ model: 2, map: 0.8, ms: 10 })]),
    {},
    [map, time],
  );
  expect(flat(flip.notes)).toContain("the other way round");
  const calm = verdictOf(
    subs([run({ map: 0.9, ms: 10 }), run({ model: 2, map: 0.8, ms: 40 })]),
    {},
    [map, time],
  );
  expect(flat(calm.notes)).not.toContain("the other way round");
});

test("the spec sheet groups the facts, marks the best of each row, and flags rows where nothing differs", () => {
  const s = subs([
    run({ map: 0.9, ms: 40, size: 10e6, instances: 30 }),
    run({ model: 2, map: 0.8, ms: 20, size: 10e6, instances: 30 }),
  ]);
  const rows = specSheet(s);
  const row = (key: string) => rows.find((r) => r.key === key);
  expect(row("map50_95")?.label).toBe("Accuracy score");
  expect(row("map50_95")?.tech).toBe("mAP50-95");
  expect(row("map50_95")?.best).toEqual([0]);
  expect(row("p50")?.best).toEqual([1]);
  expect(row("size")?.same).toBe(true);
  expect(row("size")?.best).toEqual([]);
  expect(row("device")?.same).toBe(true);
  expect(row("map50_95")?.same).toBe(false);
  expect(rows.map((r) => r.group)).toEqual(
    [...rows.map((r) => r.group)].sort(
      (a, b) =>
        ["Accuracy", "Speed", "Size and set-up", "The machine"].indexOf(a) -
        ["Accuracy", "Speed", "Size and set-up", "The machine"].indexOf(b),
    ),
  );
  const throttledRun = specSheet(subs([run({ map: 0.9 }), run({ model: 2, map: 0.8, ms: 20 })]));
  expect(throttledRun.find((r) => r.key === "p50")?.cells[0]?.text).toBe("n/a");
});
