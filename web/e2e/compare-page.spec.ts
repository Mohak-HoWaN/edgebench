// The Compare page in a real browser, fed fixed runs through a stand-in for /api/runs and /api/models: the two lists are the page's
// only input, so every chart can be filled and every case set up without running a benchmark.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { resetIds, run } from "./fixtures/compare-runs.ts";

const samples = Array.from({ length: 100 }, (_, k) => 10 + (k % 7) * 0.2);
const rich = {
  samples,
  stages: [1, 6, 2] as [number, number, number],
  curves: true,
  hist: Array.from({ length: 20 }, (_, k) => (k > 8 ? k : 1)),
  sources: { "rpi-cam3-wide": 0.6, mobile: 0.8 },
  size: 10_485_760,
  classes: { chips: 0.9, oreo: 0.5 },
  confusion: {
    labels: ["chips", "oreo", "background"],
    matrix: [
      [8, 1, 1],
      [2, 6, 0],
      [1, 0, 0],
    ],
  },
  series: {
    temp: [50, 52, 55, 58, 60, 61, 62, 63],
    clock: [3000, 3000, 2990, 2980, 2950, 2900, 2900, 2880],
  },
};

resetIds();
const RUNS = [
  run({ ...rich, model: 1, ms: 20, map: 0.7 }), // 1
  run({ ...rich, model: 1, ms: 8, map: 0.7, threads: 4 }), // 2
  run({ ...rich, model: 2, ms: 15, map: 0.8 }), // 3
  run({ ...rich, model: 2, ms: 6, map: 0.8, threads: 4 }), // 4
  run({ ...rich, model: 2, ms: 9, map: 0.6, format: "OpenVINO", precision: "INT8" }), // 5
  run({ ...rich, model: 2, ms: 60, map: 0.8, device: 2 }), // 6: the same run as 3, on the Pi
  run({ ...rich, model: 3, ms: 12, map: 0.75 }), // 7
  run({ ...rich, model: 4, ms: 12, map: 0.75 }), // 8: a fourth model
  run({ ...rich, model: 2, ms: 14, map: 0.79, version: 2 }), // 9: another dataset version
];
const MODELS = [1, 2, 3, 4].map((id) => ({
  id,
  name: ["Old", "New", "Third", "Fourth"][id - 1],
  status: "ready",
  variant_counts: {},
}));

test.use({ colorScheme: "light" });
test.beforeEach(async ({ page }) => {
  await page.route("**/api/runs", (route) => route.fulfill({ json: RUNS }));
  await page.route("**/api/models", (route) => route.fulfill({ json: MODELS }));
});

const TABS: Record<string, string[]> = {
  "Which is the best trade-off?": ["scorecard", "accuracy-speed", "size-accuracy", "size-speed"],
  "Which is faster?": ["speed-up", "latency-distribution", "threads", "devices", "where-time-goes"],
  "Which is more accurate?": ["drift", "per-class", "pr-curve", "f1-curve", "score-distribution"],
  "Where does it go wrong?": ["confusion", "capture-source"],
  "Is the machine coping?": ["temperature", "latency-over-run"],
};

async function open(page: Page, query: string) {
  await page.goto(`/compare${query}`);
  await page.getByRole("heading", { level: 1, name: "Compare" }).waitFor();
}

async function openMore(page: Page) {
  for (const d of await page.locator("[role=tabpanel] details").all())
    await d.locator("summary").click();
}

test("the answer comes first, then the facts side by side, then the charts", async ({ page }) => {
  await open(page, "?runs=1,2,3,4,5,6&ref=3");
  const y = async (name: string) =>
    (await page.getByRole("heading", { name }).first().boundingBox())?.y ?? 0;
  const answer = await y("The answer");
  const side = await y("Side by side");
  const charts = await y("Charts");
  expect(answer).toBeGreaterThan(0);
  expect(side).toBeGreaterThan(answer);
  expect(charts).toBeGreaterThan(side);
  await expect(page.getByText(/is the best pick\./)).toBeVisible();
});

test("limits decide who can win: a run that misses one is left out with the reason", async ({
  page,
}) => {
  await open(page, "?runs=1,3,5&ref=3&minacc=65&maxms=12");
  await page.getByText(/Left out because they miss a limit/).click();
  await expect(page.getByText(/slower than your limit/).first()).toBeVisible();
  await page.getByLabel("At least this accurate").fill("99");
  await expect(page.getByText("None of these runs meets your limits.")).toBeVisible();
  await expect(page).toHaveURL(/minacc=99/);
});

test("the side-by-side table hides what is the same, marks the best, and keeps the run names in view", async ({
  page,
}) => {
  await open(page, "?runs=1,3&ref=3");
  const table = page.getByRole("table").first();
  await expect(table.getByRole("rowheader", { name: /Accuracy score/ })).toBeVisible();
  await expect(table.getByRole("rowheader", { name: "Machine", exact: true })).toHaveCount(0); // the same machine for both: hidden
  await expect(table.getByText("best").first()).toBeVisible();
  await page.getByLabel("Only show differences").uncheck();
  await expect(table.getByRole("rowheader", { name: "Machine", exact: true })).toBeVisible();
  await expect(table.locator("thead")).toHaveCSS("position", "sticky");
});

test("the charts are grouped by the question they answer, and every chart is drawn when its data exists", async ({
  page,
}) => {
  await open(page, "?runs=1,2,3,4,5,6&ref=3");
  for (const [label, ids] of Object.entries(TABS)) {
    await page.getByRole("tab", { name: label }).click();
    await openMore(page);
    for (const id of ids) {
      const section = page.locator(`section#${id}`);
      await expect(section, `${label}: ${id}`).toBeVisible();
      await expect(
        section.getByText(
          /Select at least|did not record|None of the selected|Run them again|to see this/,
        ),
        id,
      ).toHaveCount(0);
      await expect(section.locator("svg[role=img], table").first(), id).toBeVisible();
    }
  }
});

test("the tabs work from the keyboard and the choice is kept in the address", async ({ page }) => {
  await open(page, "?runs=1,3");
  await page.getByRole("tab", { name: "Which is the best trade-off?" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Which is faster?" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page).toHaveURL(/tab=speed/);
});

test("the sentences say what the numbers show", async ({ page }) => {
  await open(page, "?runs=1,2,3,4,5,6&ref=3");
  await page.getByRole("tab", { name: "Which is faster?" }).click();
  await openMore(page);
  await expect(page.locator("section#devices")).toContainText("slower than");
  await page.getByRole("tab", { name: "Which is more accurate?" }).click();
  await expect(page.locator("section#drift")).toContainText("lost 20.0 points"); // the INT8 run, against the reference
  await expect(page.locator("section#per-class")).toContainText("labelled examples");
});

test("a mark can be read by focus, and a chart can be shown as a table", async ({ page }) => {
  await open(page, "?runs=1,3&ref=1");
  const mark = page.locator("section#accuracy-speed svg [role=img]").first();
  await mark.focus();
  await expect(page.locator("section#accuracy-speed").getByRole("status")).toContainText("ms");
  await page
    .locator("section#accuracy-speed")
    .getByRole("button", { name: "Show as a table" })
    .click();
  await expect(page.locator("section#accuracy-speed table")).toContainText("Old");
});

test("anything can be mixed: the page says what then differs, and the comparison lives in the address", async ({
  page,
}) => {
  await open(page, "?runs=3,6,9");
  const notes = page.getByRole("list", { name: "What differs between these runs" });
  await expect(notes).toContainText("different datasets");
  await expect(notes).toContainText("different devices");
  await page
    .getByRole("button", { name: /Remove .*New, ONNX FP32, 1 thread/ })
    .first()
    .click();
  await expect(page).toHaveURL(/runs=6%2C9|runs=6,9/);
  await page
    .getByLabel(/Reference.*New/)
    .last()
    .check();
  await expect(page).toHaveURL(/ref=\d+/);
});

test("a fourth model is refused with the reason, and a ready-made comparison fills the page", async ({
  page,
}) => {
  await open(page, "?runs=1,3,7");
  await page.getByText("Choose runs yourself").click();
  const fourth = page.getByRole("checkbox", { name: /Run 8: Fourth/ });
  await expect(fourth).toBeDisabled();
  await expect(fourth).toHaveAttribute("title", /Up to 3 models/);
  await page.getByRole("button", { name: "Clear all" }).click();
  await expect(page.getByText("Nothing is selected")).toBeVisible();
  await page.getByRole("button", { name: /ONNX FP32, 1 thread: Old against/ }).click();
  await expect(page.getByRole("columnheader", { name: /Reference/ })).toHaveCount(3);
});

test("no accessibility violations in either theme, on each tab with its extra charts open", async ({
  page,
}) => {
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await open(page, "?runs=1,2,3,4,5,6&ref=3&tab=tradeoffs");
    for (const label of Object.keys(TABS)) {
      await page.getByRole("tab", { name: label }).click();
      await openMore(page);
      await page.locator("[role=tabpanel] svg").first().waitFor();
      const results = await new AxeBuilder({ page }).analyze();
      expect(
        results.violations.map(
          (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`,
        ),
        `${scheme}, ${label}`,
      ).toEqual([]);
    }
  }
});
