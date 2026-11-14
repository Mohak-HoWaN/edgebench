// No browser: the all-runs table's logic is pure, so it is tested by calling it.
import { expect, test } from "@playwright/test";
import {
  ALL,
  DEFAULT_VIEW,
  layout,
  options,
  rowsOf,
  sort,
  toCsv,
  windowOf,
  type View,
} from "../src/lib/explorer.ts";
import { highlights } from "../src/lib/highlights.ts";
import { resetIds, run } from "./fixtures/compare-runs.ts";

resetIds();
const RUNS = [
  run({ model: 1, map: 0.7, ms: 20, size: 10e6 }), // 1
  run({ model: 2, map: 0.9, ms: 10, size: 5e6, format: "OpenVINO", precision: "FP16" }), // 2
  run({ model: 2, map: 0.8, ms: null, size: 5e6, threads: 4 }), // 3: no clean speed
  run({ model: 1, status: "failed" }), // 4
  run({ model: 3, map: 0.6, ms: 30, device: 2 }), // 5
];
const rows = rowsOf(RUNS);
const view = (change: Partial<View>): View => ({ ...DEFAULT_VIEW, status: ALL, ...change });
const ids = (v: View) => layout(rows, v).flatMap((i) => (i.kind === "row" ? [i.row.run.id] : []));

test("rows carry what the table shows, and a run without a clean speed is marked", () => {
  const r2 = rows[1];
  expect(r2.format).toBe("OpenVINO");
  expect(r2.acc).toBe(0.9);
  expect(r2.ms).toBe(10);
  expect(rows[2]?.ms).toBeUndefined();
});

test("filters combine, text search matches every word, and the default view shows finished runs only", () => {
  expect(ids(view({ model: "New" })).sort()).toEqual([2, 3]);
  expect(ids(view({ model: "New", format: "ONNX" }))).toEqual([3]);
  expect(ids(view({ search: "openvino new" }))).toEqual([2]);
  expect(ids(view({ search: "nothing like this" }))).toEqual([]);
  expect(ids({ ...DEFAULT_VIEW, sort: { key: "id", dir: "asc" } })).toEqual([1, 2, 3, 5]); // the failed run is hidden by default
  expect(ids(view({ status: "failed" }))).toEqual([4]);
  expect(options(rows, "model")).toEqual(["New", "Old", "Third"]);
});

test("sorting puts a missing value last whichever way, and ties keep run order", () => {
  expect(sort(rows, { key: "ms", dir: "asc" }).map((r) => r.run.id)).toEqual([2, 1, 5, 3, 4]);
  expect(sort(rows, { key: "ms", dir: "desc" }).map((r) => r.run.id)).toEqual([5, 1, 2, 3, 4]);
  expect(
    sort(rows, { key: "acc", dir: "desc" })
      .map((r) => r.run.id)
      .slice(0, 3),
  ).toEqual([2, 3, 1]);
  expect(
    sort(rows, { key: "model", dir: "asc" })
      .map((r) => r.run.model_name)
      .slice(0, 2),
  ).toEqual(["New", "New"]);
});

test("grouping adds a heading with the count before each group, in name order", () => {
  const items = layout(rows, view({ group: "model", sort: { key: "id", dir: "asc" } }));
  expect(items.filter((i) => i.kind === "group")).toEqual([
    { kind: "group", label: "New", count: 2 },
    { kind: "group", label: "Old", count: 2 },
    { kind: "group", label: "Third", count: 1 },
  ]);
  expect(items).toHaveLength(5 + 3);
  expect(items[0]).toEqual({ kind: "group", label: "New", count: 2 });
});

test("only the rows in view are drawn, with space left for the rest (500 rows, a 480 px window)", () => {
  expect(windowOf(500, 0, 480, 40)).toEqual({ start: 0, end: 18, padTop: 0, padBottom: 482 * 40 });
  const w = windowOf(500, 4000, 480, 40);
  expect(w.start).toBe(94);
  expect(w.end).toBe(118);
  expect(w.padTop + (w.end - w.start) * 40 + w.padBottom).toBe(500 * 40); // the scroll height never changes
  expect(windowOf(500, 999_999, 480, 40).end).toBe(500);
  expect(windowOf(0, 0, 480, 40)).toEqual({ start: 0, end: 0, padTop: 0, padBottom: 0 });
});

test("the CSV has a header, one line per row, quotes where a value needs them, and says which speeds are not clean", () => {
  const csv = toCsv(rows.slice(0, 3)).trimEnd().split("\n");
  expect(csv[0]).toContain("run,status,model");
  expect(csv).toHaveLength(4);
  expect(csv[2]).toContain("OpenVINO FP16");
  const odd = toCsv([{ ...rows[0], model: 'A "quoted", model' }]);
  expect(odd).toContain('"A ""quoted"", model"');
});

test("the dashboard highlight is the fastest run within the allowed points of the best accuracy, with its rule", () => {
  resetIds();
  const set = [
    run({ model: 1, map: 0.9, ms: 40 }),
    run({ model: 2, map: 0.88, ms: 20 }), // within 5 points of 0.9 and faster
    run({ model: 3, map: 0.7, ms: 5 }), // fastest, but 20 points less accurate
    run({ model: 1, map: 0.95, ms: 50, device: 2 }), // another device: a place of its own, with one run only
  ];
  const [h] = highlights(set, 5);
  expect(h.run.model_id).toBe(2);
  expect(h.sentence).toContain("Fastest on shelf v1 on PC");
  expect(h.rule).toContain("within 5 points of the best accuracy (90.0%");
  expect(h.compare).toEqual([2, 1]);
  expect(highlights(set, 25)[0]?.run.model_id).toBe(3); // a looser limit lets the fast, weaker run win
  expect(highlights(set.slice(3), 5)).toEqual([]); // one run is nothing to pick between
});
