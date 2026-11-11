import fs from "node:fs";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

test.use({ colorScheme: "light" });

const FIXTURES = path.resolve("e2e", "fixtures");
const read = (name: string) => fs.readFileSync(path.join(FIXTURES, name));

interface Id {
  id: number;
}
interface RunRow extends Id {
  variant_id: number | null;
  params: { threads: number };
  status: string;
}

/** Everything these tests make is removed afterwards: the server's database is shared with the other specs. */
test.afterEach(async ({ request }) => {
  const experiments = (await (await request.get("/api/experiments")).json()) as (Id & {
    status: string;
  })[];
  for (const e of experiments) {
    if (e.status === "running") await request.post(`/api/experiments/${String(e.id)}/cancel`);
    await request.delete(`/api/experiments/${String(e.id)}`);
  }
  for (const list of ["/api/datasets", "/api/devices", "/api/models"]) {
    const rows = (await (await request.get(list)).json()) as Id[];
    for (const row of rows) await request.delete(`${list}/${String(row.id)}`);
  }
});

async function addDataset(request: APIRequestContext) {
  const created = (await (
    await request.post("/api/datasets", { data: { name: "shelf" } })
  ).json()) as Id;
  const blob = (await (
    await request.post(`/api/datasets/${String(created.id)}/blobs`, {
      data: read("shelf.fixture"),
      headers: { "x-path": "shelf.zip" },
    })
  ).json()) as { path: string; sha256: string };
  await request.post(`/api/datasets/${String(created.id)}/commit`, {
    data: { message: "First pictures", add: [{ path: blob.path, sha256: blob.sha256 }] },
  });
  await expect
    .poll(async () => {
      const r = await request.get(`/api/datasets/${String(created.id)}/versions/1`);
      return r.ok() ? ((await r.json()) as { status: string }).status : "missing";
    })
    .toBe("ready");
  return created.id;
}

async function addModel(request: APIRequestContext) {
  const r = await request.post("/api/models", {
    data: read("checkpoint.fixture"),
    headers: { "x-filename": "retail.pt" },
  });
  const { id } = (await r.json()) as Id;
  await expect
    .poll(async () => {
      const m = (await (await request.get(`/api/models/${String(id)}`)).json()) as {
        variants: { state: string }[];
      };
      return (
        m.variants.length === 7 &&
        m.variants.every((v) => !["pending", "converting"].includes(v.state))
      );
    })
    .toBe(true);
  return id;
}

/** A device that reports 8 threads, enrolled the way an agent does. */
async function addDevice(request: APIRequestContext) {
  const created = (await (
    await request.post("/api/devices", { data: { name: "Test PC", expected_kind: "pc" } })
  ).json()) as { device: Id; enroll_token: string };
  const enrolled = (await (
    await request.post("/agent/enroll", {
      data: {
        token: created.enroll_token,
        fingerprint: { cpu: "Test CPU", pi_model: null, logical_cores: 8, physical_cores: 4 },
      },
    })
  ).json()) as { device_token: string };
  return { id: created.device.id, auth: { authorization: `Bearer ${enrolled.device_token}` } };
}

const stage = (p50: number) => ({
  mean: p50,
  std: 0.2,
  min: p50 - 1,
  p50,
  p95: p50 + 2,
  p99: p50 + 3,
  max: p50 + 4,
});

const window = (clock: number | null, temp: number | null, throttled: boolean | null = null) => ({
  samples: 20,
  cpu_mean: 40,
  cpu_max: 70,
  cpu_per_core_mean: [40, 40],
  rss_peak_mb: 210,
  clock_mhz_mean: clock,
  clock_mhz_min: clock,
  temp_c_start: temp,
  temp_c_max: temp,
  throttled,
  gpu_util_mean: null,
  gpu_mem_peak_mb: null,
  gpu_temp_c_max: null,
});

const BOXES = {
  min_confidence: 0.25,
  pictures: Object.fromEntries(
    [0, 1, 2, 3].map((i) => [String(i), [[0.2, 0.2, 0.6, 0.7, 0.91, i % 2]]]),
  ),
};

/** A finished run's result with repeats. ``valid`` marks which repeats the agent kept; ``detections`` is what it found. */
function result(p50s: number[], valid: boolean[], map50 = 0.6, detections: unknown = BOXES) {
  const repeats = p50s.map((p, i) => ({
    index: i,
    valid: valid[i] ?? true,
    invalid_reason: !(valid[i] ?? true)
      ? "the CPU clock averaged 18% below where the run started"
      : null,
    stats: stage(p),
    total_ms: [p],
    telemetry: window(3000, 70),
  }));
  return {
    runtime: { kind: "onnx", threads: 2, versions: { onnxruntime: "1.25.1" } },
    load_ms: 150,
    first_inference_ms: 30,
    speed: {
      warmup: 5,
      iterations: 50,
      pictures_cycled: 4,
      repeats_requested: p50s.length,
      repeats,
      valid_repeats: valid.filter(Boolean).length,
      latency_valid: valid.some(Boolean),
      stages: {
        preprocess: stage(1.5),
        inference: stage(p50s[0] ?? 10),
        postprocess: stage(2),
        total: stage(p50s[0] ?? 10),
      },
    },
    telemetry: {
      enabled: true,
      hz: 5,
      sources: { cpu: "psutil, per logical CPU", clock: "performance counters", throttle: null },
      start_clock_mhz: 3000,
      run: window(3000, null),
    },
    environment: { logical_cores: 8, physical_cores: 4, power_plan: "Balanced", governor: null },
    accuracy: {
      available: true,
      images: 4,
      map50,
      map50_95: map50 / 2,
      precision: 0.7,
      recall: 0.6,
      f1: 0.65,
      confidence_at_best_f1: 0.3,
      per_class: {
        chips: { ap50: map50, ap50_95: map50 / 2, instances: 3, images: 3, predictions: 4 },
      },
    },
    dataset: { hash: "0123456789abcdef0123456789abcdef", images: 4 },
    decode: { conf: 0.001, iou: 0.7, max_det: 300, multi_label: true },
    predictions: detections,
  };
}

/** Answer every waiting job; ``make`` chooses the result for each run. ``only`` stops after that many. */
async function answer(
  request: APIRequestContext,
  auth: Record<string, string>,
  make: (run: RunRow) => unknown,
  only = 99,
) {
  const waiting = ((await (await request.get("/api/runs?limit=500")).json()) as RunRow[]).filter(
    (r) => r.status === "queued",
  ).length;
  for (let done = 0; done < Math.min(only, waiting); done++) {
    const claimed = await request.post("/agent/claim", { headers: auth });
    if (claimed.status() !== 200) return;
    const spec = (await claimed.json()) as { job_id: number; run_id: number };
    const runs = (await (await request.get("/api/runs?limit=500")).json()) as RunRow[];
    const run = runs.find((r) => r.id === spec.run_id);
    if (!run) throw new Error("the run of a claimed job is missing");
    await request.post("/agent/result", {
      headers: auth,
      data: { job_id: spec.job_id, ok: true, result: make(run), log: "bench ok" },
    });
  }
}

async function readyVariants(request: APIRequestContext, model: number) {
  const m = (await (await request.get(`/api/models/${String(model)}`)).json()) as {
    variants: { id: number; state: string }[];
  };
  return m.variants.filter((v) => v.state === "ready");
}

async function startSweep(
  request: APIRequestContext,
  model: number,
  dataset: number,
  device: number,
  extra: Record<string, unknown> = {},
) {
  const [first] = await readyVariants(request, model);
  const r = await request.post("/api/experiments", {
    data: {
      name: "Thread sweep",
      dataset_id: dataset,
      device_id: device,
      params: { threads: 2, warmup: 1, iterations: 5, repeats: 3 },
      items: [
        { model_id: model, variant_id: first.id },
        { model_id: model, variant_id: null },
      ],
      sweep: { threads: [1, 2] },
      ...extra,
    },
  });
  expect(r.status()).toBe(201);
  return (await r.json()) as Id & { runs: Id[] };
}

test("the plan counts a sweep's runs, estimates the time and says what it left out and why", async ({
  page,
  request,
}) => {
  await addModel(request);
  await addDataset(request);
  await addDevice(request);
  await page.goto("/experiments/new");
  await page.getByLabel("Experiment name").fill("Which thread count?");
  await page.getByRole("button", { name: "Select all for retail" }).click();
  await expect(page.getByTestId("plan-summary")).toContainText("6 runs");

  const threads = page.getByRole("group", { name: /Try several thread counts/ });
  await threads.getByLabel("1", { exact: true }).check();
  await threads.getByLabel("2", { exact: true }).check();
  await threads.getByLabel("4", { exact: true }).check();
  await expect(page.getByTestId("plan-summary")).toContainText("18 runs");
  await expect(page.getByTestId("plan-summary")).toContainText(/about \d+ (s|min)/);
  await expect(page.getByText("For 18 of them nothing has been measured")).toBeVisible();

  // a size with no conversion is left out with the reason; the model's own size still runs
  const sizes = page.getByRole("group", { name: /Try several input sizes/ });
  await sizes.getByLabel("640 px").check();
  await sizes.getByLabel("416 px").check();
  await expect(page.getByTestId("plan-summary")).toContainText("18 runs");
  await page.getByTestId("plan-pruned").locator("summary").click();
  await expect(page.getByTestId("plan-pruned")).toContainText(
    "there is no finished conversion at 416 px",
  );
  await expect(page.getByTestId("plan-pruned")).toContainText("own input size"); // the .pt only runs at its own size
  await expect(page.getByText("This starts 18 runs, one after another.")).toBeVisible();
});

test("a sweep where nothing can run says so and cannot be started", async ({ page, request }) => {
  await addModel(request);
  await addDataset(request);
  await addDevice(request);
  await page.goto("/experiments/new");
  await page.getByLabel("Experiment name").fill("Impossible");
  await page.getByRole("button", { name: "Select all for retail" }).click();
  await page
    .getByRole("group", { name: /Try several input sizes/ })
    .getByLabel("320 px")
    .check();
  await expect(page.getByRole("alert")).toContainText("Every combination was left out");
  await expect(page.getByRole("button", { name: "Start experiment" })).toBeDisabled();
});

test("quick and full set the rounds and repeats, and a custom number is called custom", async ({
  page,
  request,
}) => {
  await addModel(request);
  await addDataset(request);
  await addDevice(request);
  await page.goto("/experiments/new");
  await expect(page.getByRole("button", { name: "Full measurement" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByLabel("Repeats", { exact: true })).toHaveValue("3");
  await page.getByRole("button", { name: "Quick look" }).click();
  await expect(page.getByLabel("Warm-up rounds", { exact: true })).toHaveValue("5");
  await expect(page.getByLabel("Timed rounds", { exact: true })).toHaveValue("50");
  await expect(page.getByLabel("Repeats", { exact: true })).toHaveValue("1");
  await page.getByLabel("Repeats", { exact: true }).fill("5");
  await expect(page.getByText("Your own numbers.")).toBeVisible();
});

test("repeats show an interval, a speed-up that could be noise says so, and a bad INT8-like model fails the check", async ({
  page,
  request,
}) => {
  const model = await addModel(request);
  const dataset = await addDataset(request);
  const { id: device, auth } = await addDevice(request);
  const [variant] = await readyVariants(request, model);
  const e = await startSweep(request, model, dataset, device, { sweep: {} });
  // the converted variant finds nothing (the zero-detection model); the baseline finds the objects
  await answer(request, auth, (run) =>
    run.variant_id === variant.id
      ? result([9.0, 11.0, 13.0], [true, true, true], 0.0, { min_confidence: 0.25, pictures: {} })
      : result([10.0, 12.0, 14.0], [true, true, true], 0.6),
  );
  await page.goto(`/experiments/${String(e.id)}`);
  const table = page.getByRole("table", { name: /Runs of this experiment/ });
  await expect(table).toContainText("± 5.0 ms (3 repeats, wide)");
  await expect(table).toContainText("not significant: could be noise"); // one ms apart with this spread
  await expect(table).toContainText("Fails the accuracy check");
  await expect(table).toContainText("it finds nothing, where the baseline found objects");
  await expect(page.getByLabel("Insights", { exact: false }).first()).toBeVisible();
  await expect(
    page.getByText(/fails the accuracy check against the PyTorch baseline/),
  ).toBeVisible();
  await expect(page.getByText(/within the noise/)).toBeVisible();
});

test("the accuracy limits in Settings decide pass or fail, are kept, and reset", async ({
  page,
  request,
}) => {
  const model = await addModel(request);
  const dataset = await addDataset(request);
  const { id: device, auth } = await addDevice(request);
  const [variant] = await readyVariants(request, model);
  const e = await startSweep(request, model, dataset, device, { sweep: {} });
  // the variant's box is shifted a little and its mAP is 3 points lower
  const shifted = {
    min_confidence: 0.25,
    pictures: Object.fromEntries(
      [0, 1, 2, 3].map((i) => [String(i), [[0.24, 0.2, 0.64, 0.7, 0.9, i % 2]]]),
    ),
  };
  await answer(request, auth, (run) =>
    run.variant_id === variant.id
      ? result([9.0, 9.1, 8.9], [true, true, true], 0.57, shifted)
      : result([12.0, 12.1, 11.9], [true, true, true], 0.6),
  );
  await page.goto(`/experiments/${String(e.id)}`);
  const table = page.getByRole("table", { name: /Runs of this experiment/ });
  await expect(table).toContainText("Passes the accuracy check"); // the defaults: 5 points, agreement 0.80

  await page.goto("/settings");
  await page.getByLabel("Largest mAP drop (points)").fill("1");
  await page.getByLabel("Lowest box agreement").fill("0.95");
  await page.goto(`/experiments/${String(e.id)}`);
  await expect(table).toContainText("Fails the accuracy check");
  await expect(table).toContainText("mAP@50 fell by 3.0 points, more than 1.0");

  await page.reload(); // kept in this browser
  await expect(table).toContainText("Fails the accuracy check");
  await page.goto("/settings");
  await expect(page.getByLabel("Largest mAP drop (points)")).toHaveValue("1");
  await page.getByRole("button", { name: "Reset preferences" }).click();
  await page.getByRole("button", { name: "Reset preferences" }).last().click();
  await expect(page.getByLabel("Largest mAP drop (points)")).toHaveValue("5");
});

test("a throttled run is marked, left out of the speed ranking and explained on its page", async ({
  page,
  request,
}) => {
  const model = await addModel(request);
  const dataset = await addDataset(request);
  const { id: device, auth } = await addDevice(request);
  const [variant] = await readyVariants(request, model);
  const e = await startSweep(request, model, dataset, device, { sweep: {} });
  await answer(request, auth, (run) =>
    run.variant_id === variant.id
      ? result([30.0, 31.0, 32.0], [false, false, false], 0.6) // every repeat was slowed down
      : result([20.0, 21.0, 19.0], [true, true, true], 0.6),
  );
  await page.goto(`/experiments/${String(e.id)}`);
  const table = page.getByRole("table", { name: /Runs of this experiment/ });
  await expect(table.getByRole("row", { name: /ONNX FP32/ })).toContainText("throttled");
  await expect(page.getByText(/1 run was throttled/)).toBeVisible();

  const runs = (await (
    await request.get(`/api/runs?experiment_id=${String(e.id)}`)
  ).json()) as RunRow[];
  const hot = runs.find((r) => r.variant_id === variant.id);
  await page.goto(`/results/${String(hot?.id)}`);
  await expect(page.getByRole("alert").filter({ hasText: "Invalid for latency" })).toBeVisible();
  await expect(
    page.getByRole("cell", { name: /No: the CPU clock averaged 18% below/ }).first(),
  ).toBeVisible();
});

test("a run page shows each repeat and the machine, and says 'not available' instead of showing a zero", async ({
  page,
  request,
}) => {
  const model = await addModel(request);
  const dataset = await addDataset(request);
  const { id: device, auth } = await addDevice(request);
  const e = await startSweep(request, model, dataset, device, { sweep: {} });
  await answer(request, auth, () => result([10.0, 12.0, 14.0], [true, true, true]));
  const runs = (await (
    await request.get(`/api/runs?experiment_id=${String(e.id)}`)
  ).json()) as RunRow[];
  await page.goto(`/results/${String(runs[0]?.id)}`);
  await expect(page.getByTestId("headline-latency")).toContainText("12.0 ms");
  await expect(page.getByTestId("headline-latency")).toContainText("± 5.0 ms");
  await expect(page.getByText("3 repeats give a wide interval")).toBeVisible();
  await expect(
    page.getByRole("table", { name: "Each repeat of the timed rounds" }).getByRole("row"),
  ).toHaveCount(4);
  const machine = page.getByRole("heading", { name: "Machine during the run" });
  await expect(machine).toBeVisible();
  await expect(page.getByText("no throttle flag on this machine")).toBeVisible();
  await expect(page.getByText("Balanced")).toBeVisible();
  await expect(page.getByText("not available on this machine").first()).toBeVisible(); // the temperature, never 0
});

test("a cancelled sweep keeps what finished and resume makes only what is missing", async ({
  page,
  request,
}) => {
  const model = await addModel(request);
  const dataset = await addDataset(request);
  const { id: device, auth } = await addDevice(request);
  const e = await startSweep(request, model, dataset, device, { sweep: { threads: [1, 2, 4] } });
  expect(e.runs).toHaveLength(6);
  await answer(request, auth, () => result([10.0, 10.0, 10.0], [true, true, true]), 2);
  await page.goto(`/experiments/${String(e.id)}`);
  await page.getByRole("button", { name: "Cancel what is left" }).click();
  await expect(
    page.getByText("Finished, some runs did not complete: 6 of 6 runs finished"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Resume: make what is missing" }).click();
  await expect(page.getByText("Running: 2 of 6 runs finished")).toBeVisible(); // the two that finished were not repeated
  await expect(page.getByRole("button", { name: "Resume: make what is missing" })).toHaveCount(0);
});

test("INT8 is refused with the reason when the dataset has too few pictures", async ({
  page,
  request,
}) => {
  const model = await addModel(request);
  await addDataset(request); // the fixture has a handful of pictures
  await page.goto(`/models/${String(model)}`);
  await expect(page.getByRole("heading", { name: "Add an INT8 conversion" })).toBeVisible();
  await expect(page.getByText(/INT8 calibration needs at least 50/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Add this INT8 conversion" })).toBeDisabled();
  // and the server refuses the same request made directly
  const datasets = (await (await request.get("/api/datasets")).json()) as Id[];
  const r = await request.post(`/api/models/${String(model)}/int8`, {
    data: { op: "openvino_int8", dataset_id: datasets[0]?.id },
  });
  expect(r.status()).toBe(422);
  expect(((await r.json()) as { detail: string }).detail).toContain("at least 50");
});

async function violations(page: Page) {
  const { violations: found } = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"])
    .analyze();
  return found.map(
    (v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`,
  );
}

for (const scheme of ["light", "dark"] as const) {
  test(`the new pages have no accessibility violations in the ${scheme} theme`, async ({
    page,
    request,
  }) => {
    await page.emulateMedia({ colorScheme: scheme });
    const model = await addModel(request);
    const dataset = await addDataset(request);
    const { id: device, auth } = await addDevice(request);
    const [variant] = await readyVariants(request, model);
    const e = await startSweep(request, model, dataset, device, { sweep: {} });
    await answer(request, auth, (run) =>
      run.variant_id === variant.id
        ? result([30.0, 31.0, 32.0], [false, false, true], 0.2, {
            min_confidence: 0.25,
            pictures: {},
          })
        : result([20.0, 21.0, 19.0], [true, true, true], 0.6),
    );
    const runs = (await (
      await request.get(`/api/runs?experiment_id=${String(e.id)}`)
    ).json()) as RunRow[];
    const pages = [
      `/experiments/${String(e.id)}`,
      `/results/${String(runs[0]?.id)}`,
      `/models/${String(model)}`,
      "/experiments/new",
      "/settings",
    ];
    for (const url of pages) {
      await page.goto(url);
      await page.getByRole("heading", { level: 1 }).waitFor();
      if (url === "/experiments/new") {
        await page.getByRole("button", { name: "Select all for retail" }).click();
        await page
          .getByRole("group", { name: /Try several thread counts/ })
          .getByLabel("2", { exact: true })
          .check();
        await expect(page.getByTestId("plan-summary")).toBeVisible();
      }
      expect(await violations(page), url).toEqual([]);
    }
  });
}

test("Results shows your first three metrics as columns, in your order, and keeps them across a reload", async ({
  page,
  request,
}) => {
  const model = await addModel(request);
  const dataset = await addDataset(request);
  const { id: device, auth } = await addDevice(request);
  await startSweep(request, model, dataset, device, { sweep: {} });
  await answer(request, auth, () => result([10.0, 10.0, 10.0], [true, true, true]));

  const headers = page
    .getByRole("table", { name: "Experiments, newest first" })
    .getByRole("columnheader");
  await page.goto("/results");
  // the defaults: mAP50-95, F1 score, median time
  await expect(headers).toHaveText([
    "Experiment",
    "Dataset",
    "Device and date",
    "Best mAP50-95",
    "Best F1 score",
    "Best Median time per image",
  ]);

  await page.goto("/settings");
  await page.getByRole("button", { name: "Remove F1 score" }).click();
  await page.getByLabel("Add a metric").selectOption("recall");
  await page.getByLabel("Add a metric").selectOption("precision");
  await page.getByRole("button", { name: "Move Recall up" }).click();
  // now: mAP50-95, Recall, Median time, Precision: only the first three get a column
  await page.goto("/results");
  await expect(headers).toHaveText([
    "Experiment",
    "Dataset",
    "Device and date",
    "Best mAP50-95",
    "Best Recall",
    "Best Median time per image",
  ]);
  await page.reload();
  await expect(headers.nth(5)).toHaveText("Best Median time per image");
  await expect(page.getByRole("row", { name: /Thread sweep/ }).getByRole("cell")).toHaveCount(5); // dataset, device and the three metrics; the name is the row header
});

test("the picture inspector names each run's threads, and a box label wraps and stays inside the picture", async ({
  page,
  request,
}) => {
  const model = await addModel(request);
  const dataset = await addDataset(request);
  const { id: device, auth } = await addDevice(request);
  const e = await startSweep(request, model, dataset, device, { sweep: { threads: [1, 2] } });
  // a box in the top-right corner: its label used to be cut off by the picture's edge
  const corner = { min_confidence: 0.25, pictures: { "0": [[0.7, 0.0, 0.99, 0.4, 0.9, 0]] } };
  await answer(request, auth, () => result([10.0, 10.0, 10.0], [true, true, true], 0.6, corner));
  await page.goto(`/experiments/${String(e.id)}`);
  await page.getByRole("button", { name: /Inspect picture 1:/ }).click();

  const caption = page.locator("figcaption");
  await expect(caption.filter({ hasText: /ONNX FP32, 1 thread/ }).first()).toBeVisible();
  await expect(caption.filter({ hasText: /ONNX FP32, 2 threads/ }).first()).toBeVisible();
  await expect(caption.filter({ hasText: /baseline, 1 thread/ })).toHaveCount(1);
  await expect(page.getByText(/^Run \d+$/).first()).toBeVisible(); // two runs of one variant are still told apart

  const label = page
    .locator("figure")
    .filter({ has: page.locator("figcaption", { hasText: /ONNX FP32, 1 thread/ }) })
    .locator("div[aria-hidden] span")
    .first();
  await expect(label).toBeVisible();
  expect(await label.evaluate((el) => getComputedStyle(el).whiteSpace)).toBe("normal");
  expect(await label.evaluate((el) => getComputedStyle(el).textOverflow)).not.toBe("ellipsis");
  const picture = await label
    .locator("xpath=ancestor::div[contains(@class,'overflow-hidden')][1]")
    .boundingBox();
  const text = await label.boundingBox();
  if (!picture || !text) throw new Error("the picture or its label has no box on screen");
  expect(text.x).toBeGreaterThanOrEqual(picture.x - 1);
  expect(text.x + text.width).toBeLessThanOrEqual(picture.x + picture.width + 1);
  expect(text.y).toBeGreaterThanOrEqual(picture.y - 1); // inside the box, not above the picture
});
