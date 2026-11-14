// The all-runs table, the failure browser and the dashboard highlights in a real browser, fed fixed data through stand-ins for the API.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { resetIds, run } from "./fixtures/compare-runs.ts";

const PIXEL = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

resetIds();
const MANY = Array.from({ length: 500 }, (_, k) =>
  run({
    model: (k % 3) + 1,
    map: 0.5 + (k % 40) / 100,
    ms: 10 + (k % 50),
    size: 5e6 + k * 1000,
    format: k % 2 ? "OpenVINO" : "ONNX",
    threads: 1 + (k % 4),
  }),
);
const MODELS = [1, 2, 3].map((id) => ({
  id,
  name: ["Old", "New", "Third"][id - 1],
  status: "ready",
  variant_counts: {},
}));

test.use({ colorScheme: "light" });

async function mock(page: Page, runs = MANY) {
  await page.route("**/api/runs", (r) => r.fulfill({ json: runs }));
  await page.route("**/api/models", (r) => r.fulfill({ json: MODELS }));
  await page.route("**/api/experiments", (r) => r.fulfill({ json: [] }));
}

test("the all-runs table draws only the rows in view, so 500 runs scroll smoothly, and sorts, searches and groups", async ({
  page,
}) => {
  await mock(page);
  await page.goto("/results?view=runs");
  await expect(page.getByText("500 of 500 runs")).toBeVisible();
  expect(await page.locator("table tbody tr").count()).toBeLessThan(60); // not 500
  const scroller = page.getByLabel("Table of all runs");
  await scroller.evaluate((el) => {
    el.scrollTop = el.scrollHeight;
  });
  await expect(page.getByRole("link", { name: "1", exact: true })).toBeVisible(); // the oldest run is last in the default order
  await scroller.evaluate((el) => {
    el.scrollTop = 0;
  });

  await page.getByRole("button", { name: "Typical time" }).click();
  await expect(page.getByRole("columnheader", { name: /Typical time/ })).toHaveAttribute(
    "aria-sort",
    "ascending",
  );
  await page.getByRole("button", { name: "Typical time" }).click();
  await expect(page.getByRole("columnheader", { name: /Typical time/ })).toHaveAttribute(
    "aria-sort",
    "descending",
  );

  await page.getByPlaceholder("model, variant, device, run number").fill("third openvino");
  await expect(page.getByText(/of 500 runs/)).not.toHaveText("500 of 500 runs");
  await page.getByPlaceholder("model, variant, device, run number").fill("");
  await page.getByLabel("Group by").selectOption("model");
  await expect(page.getByRole("columnheader", { name: /^New \(\d+\)$/ })).toBeVisible();
});

test("an arrangement can be saved and brought back, runs ticked and compared, and the shown rows taken as CSV", async ({
  page,
}) => {
  await mock(page);
  await page.goto("/results?view=runs");
  await page.getByLabel("Model", { exact: true }).selectOption("Old");
  await page.getByLabel("Group by").selectOption("format");
  await page.getByText(/Saved views/).click();
  await page.getByLabel("Save this arrangement as").fill("Old by format");
  await page.getByRole("button", { name: "Save view" }).click();
  await page.getByRole("button", { name: "Reset" }).click();
  await expect(page.getByText("500 of 500 runs")).toBeVisible();
  await page.getByRole("button", { name: "Old by format", exact: true }).click();
  await expect(page.getByLabel("Model", { exact: true })).toHaveValue("Old");
  await expect(page.getByLabel("Group by")).toHaveValue("format");

  await page
    .getByRole("checkbox", { name: /Select run \d+ for comparing/ })
    .first()
    .check();
  await page
    .getByRole("checkbox", { name: /Select run \d+ for comparing/ })
    .nth(2)
    .check();
  await expect(page.getByRole("link", { name: "Compare 2 selected" })).toHaveAttribute(
    "href",
    /\/compare\?runs=\d+,\d+/,
  );

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "CSV of the shown runs" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("edgebench-runs.csv");
});

test("the dashboard says which run is the fastest that is still accurate enough, and shows its rule", async ({
  page,
}) => {
  resetIds();
  const set = [
    run({ model: 1, map: 0.9, ms: 40 }),
    run({ model: 2, map: 0.88, ms: 20 }),
    run({ model: 3, map: 0.7, ms: 5 }),
  ];
  await mock(page, set);
  await page.goto("/");
  const list = page.getByRole("list", { name: "Highlights" });
  await expect(list).toContainText("Fastest on shelf v1 on PC: New, ONNX FP32, 1 thread");
  await expect(list).toContainText("within 5 points of the best accuracy");
  await expect(list.getByRole("link", { name: "Compare them" })).toHaveAttribute(
    "href",
    /\/compare\?runs=/,
  );
});

test("the pages have no accessibility violations in either theme", async ({ page }) => {
  await mock(page);
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto("/results?view=runs");
    await page.getByText("500 of 500 runs").waitFor();
    const v = (await new AxeBuilder({ page }).analyze()).violations;
    expect(
      v.map((x) => `${x.id}: ${x.nodes.map((n) => n.target.join(" ")).join(" | ")}`),
      scheme,
    ).toEqual([]);
  }
});

test("the failure browser lists the worst pictures, lets some be picked and offers them as a folder", async ({
  page,
}) => {
  resetIds();
  const one = run({ model: 1, map: 0.7, ms: 20 });
  const stage = { mean: 1, std: 0.1, min: 1, p50: 1, p95: 1, p99: 1, max: 1 };
  const full = {
    ...one,
    dataset_id: 1,
    dataset_version: 1,
    experiment_id: null,
    result: {
      ...one.result,
      load_ms: 5,
      speed: {
        warmup: 1,
        iterations: 5,
        pictures_cycled: 5,
        stages: { preprocess: stage, inference: stage, postprocess: stage, total: stage },
      },
    },
  };
  await page.route("**/api/runs/1", (r) => r.fulfill({ json: full }));
  await page.route("**/api/runs/1/failures?*", (r) =>
    r.fulfill({
      json: {
        checked: 8,
        with_problems: 2,
        totals: { missed: 1, wrong: 1, invented: 0 },
        pictures: [
          {
            index: 3,
            original: "shelf 4.jpg",
            severity: 3,
            issues: [{ kind: "wrong", truth: "chips", answer: "oreo", score: 0.8 }],
            truth: [{ name: "chips", box: [0.1, 0.1, 0.4, 0.4] }],
            found: [{ name: "oreo", box: [0.1, 0.1, 0.4, 0.4], score: 0.8 }],
          },
          {
            index: 5,
            original: "shelf 6.jpg",
            severity: 2,
            issues: [{ kind: "missed", truth: "kitkat" }],
            truth: [{ name: "kitkat", box: [0.5, 0.5, 0.9, 0.9] }],
            found: [],
          },
        ],
      },
    }),
  );
  await page.route("**/api/datasets/1/versions/1/images/*/file", (r) =>
    r.fulfill({ body: PIXEL, contentType: "image/png" }),
  );
  await page.goto("/results/1");
  const section = page.locator("section#failures");
  await expect(section).toContainText("2 of 8 annotated pictures have a problem");
  await expect(section.getByRole("listitem")).toHaveCount(2);
  await expect(section).toContainText("chips named as oreo (80% sure)");
  await expect(section).toContainText("Missed: kitkat");
  await section.getByRole("checkbox", { name: /shelf 4\.jpg/ }).check();
  await expect(section.getByRole("link", { name: /Take 1 picture as a folder/ })).toHaveAttribute(
    "href",
    "/api/runs/1/failures.zip?images=3",
  );
  await section.getByRole("button", { name: /Select the 2 shown/ }).click();
  await expect(section.getByRole("link", { name: /Take 2 pictures/ })).toHaveAttribute(
    "href",
    /images=3,5/,
  );
});
