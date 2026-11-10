import fs from "node:fs";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

test.use({ colorScheme: "light" });

const FIXTURES = path.resolve("e2e", "fixtures");
const FOLDER = path.join(FIXTURES, "shelf-folder");
const read = (name: string) => fs.readFileSync(path.join(FIXTURES, name));
const zip = (name: string, file: string) => ({
  name,
  mimeType: "application/zip",
  buffer: read(file),
});
const photo = (n: number) =>
  path.join(FOLDER, "images", n < 3 ? "rpi-cam3-wide" : "mobile", `${String(n)}.jpg`);

interface Id {
  id: number;
}

/** Everything these tests make is removed afterwards: the server's database is shared with the other specs. */
test.afterEach(async ({ request }: { request: APIRequestContext }) => {
  const experiments = (await (await request.get("/api/experiments")).json()) as (Id & {
    status: string;
  })[];
  for (const e of experiments) {
    if (e.status === "running") await request.post(`/api/experiments/${String(e.id)}/cancel`);
    await request.delete(`/api/experiments/${String(e.id)}`);
  }
  const runs = (await (await request.get("/api/runs")).json()) as (Id & { status: string })[];
  for (const r of runs) {
    if (r.status === "queued" || r.status === "running")
      await request.post(`/api/runs/${String(r.id)}/cancel`);
    await request.delete(`/api/runs/${String(r.id)}`);
  }
  for (const list of ["/api/datasets", "/api/devices", "/api/models"]) {
    const rows = (await (await request.get(list)).json()) as Id[];
    for (const row of rows) await request.delete(`${list}/${String(row.id)}`);
  }
});

// --- things the app does for the person, done here over the API so a test can start from a known state ------------------

async function waitVersion(
  request: APIRequestContext,
  dataset: number,
  version: number | "head" = "head",
) {
  await expect
    .poll(async () => {
      const r = await request.get(`/api/datasets/${String(dataset)}/versions/${String(version)}`);
      return r.ok() ? ((await r.json()) as { status: string }).status : "missing";
    })
    .toBe("ready");
}

async function addDataset(request: APIRequestContext, name = "shelf") {
  const created = (await (await request.post("/api/datasets", { data: { name } })).json()) as Id;
  const blob = (await (
    await request.post(`/api/datasets/${String(created.id)}/blobs`, {
      data: read("shelf.fixture"),
      headers: { "x-path": "shelf.zip" },
    })
  ).json()) as { path: string; sha256: string };
  await request.post(`/api/datasets/${String(created.id)}/commit`, {
    data: { message: "First pictures", add: [{ path: blob.path, sha256: blob.sha256 }] },
  });
  await waitVersion(request, created.id, 1);
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

/** Enrol a device the way an agent does (it reports 8 threads on 4 cores) and return what a test needs to act as that agent. */
async function addDevice(request: APIRequestContext, kind: "pc" | "pi" = "pc") {
  const created = (await (
    await request.post("/api/devices", { data: { name: "Test PC", expected_kind: kind } })
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
const PREDICTIONS = {
  min_confidence: 0.25,
  pictures: Object.fromEntries(
    [0, 1, 2, 3, 4, 5].map((i) => [
      String(i),
      [
        [0.2, 0.2, 0.6, 0.7, 0.91, i % 2],
        [0.1, 0.1, 0.2, 0.2, 0.4, 0],
      ],
    ]),
  ),
};
const resultFor = (map5095: number, p50: number, unmapped: string[] = []) => ({
  runtime: { kind: "onnx", threads: 4, versions: { onnxruntime: "1.25.1" } },
  load_ms: 150,
  first_inference_ms: 30,
  speed: {
    warmup: 5,
    iterations: 50,
    pictures_cycled: 6,
    stages: {
      preprocess: stage(1.5),
      inference: stage(p50 - 3),
      postprocess: stage(2),
      total: stage(p50),
    },
  },
  accuracy: {
    available: true,
    images: 6,
    class_mapping: "by name",
    unmapped_classes: unmapped,
    map50: map5095 + 0.1,
    map50_95: map5095,
    precision: 0.7,
    recall: 0.6,
    f1: 0.65,
    confidence_at_best_f1: 0.3,
    per_class: {
      chips: { ap50: 0.9, ap50_95: 0.7, instances: 3, images: 3, predictions: 4 },
      biscuit: { ap50: 0.4, ap50_95: 0.3, instances: 3, images: 3, predictions: 5 },
    },
  },
  dataset: { hash: "0123456789abcdef0123456789abcdef", images: 6 },
  decode: { conf: 0.001, iou: 0.7, max_det: 300, multi_label: true },
  predictions: PREDICTIONS,
});

/** Claim the next waiting job as the device's agent would, report some progress, and return its job id. */
async function takeJob(request: APIRequestContext, auth: Record<string, string>) {
  const claimed = await request.post("/agent/claim", { headers: auth });
  expect(claimed.status()).toBe(200);
  const { job_id: jobId } = (await claimed.json()) as { job_id: number };
  await request.post("/agent/heartbeat", {
    headers: auth,
    data: { job_id: jobId, fraction: 0.4, message: "Running" },
  });
  return jobId;
}

async function report(
  request: APIRequestContext,
  auth: Record<string, string>,
  jobId: number,
  result = resultFor(0.5076, 13.5),
) {
  await request.post("/agent/result", {
    headers: auth,
    data: { job_id: jobId, ok: true, result, log: "bench ok" },
  });
}

/** Finish ``count`` waiting jobs with different results: accuracy and speed that disagree about which variant is best. */
async function finishJobs(
  request: APIRequestContext,
  auth: Record<string, string>,
  count: number,
  maps = [0.4, 0.55, 0.5, 0.3, 0.52, 0.45],
  times = [10, 20, 8, 30, 9, 12],
) {
  for (let i = 0; i < count; i++) {
    const job = await takeJob(request, auth);
    await report(request, auth, job, resultFor(maps[i % 6] ?? 0.4, times[i % 6] ?? 10));
  }
}

async function startExperiment(
  request: APIRequestContext,
  deviceId: number,
  datasetId: number,
  name = "Does FP16 hurt?",
  all = true,
) {
  const models = (await (await request.get("/api/models")).json()) as Id[];
  const detail = (await (await request.get(`/api/models/${String(models[0]?.id)}`)).json()) as {
    id: number;
    variants: { id: number; state: string }[];
  };
  const ready = detail.variants.filter((v) => v.state === "ready");
  const items: { model_id: number; variant_id: number | null }[] = (
    all ? ready : ready.slice(0, 2)
  ).map((v) => ({
    model_id: detail.id,
    variant_id: v.id,
  }));
  if (all) items.push({ model_id: detail.id, variant_id: null });
  const r = await request.post("/api/experiments", {
    data: {
      name,
      dataset_id: datasetId,
      device_id: deviceId,
      params: { threads: 2, warmup: 1, iterations: 5 },
      items,
    },
  });
  return (await r.json()) as Id & { runs: Id[] };
}

async function violations(page: Page) {
  const { violations: found } = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"])
    .analyze();
  return found.map(
    (v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`,
  );
}

// --- datasets: photos, folders, zips, versions -----------------------------------------------------------------------

test("loose photos with no annotations make a dataset that measures speed only", async ({
  page,
}) => {
  await page.goto("/datasets");
  await page.getByLabel("Dataset name").fill("Loose photos");
  await page.getByLabel("Choose photos or files").setInputFiles([photo(3), photo(4)]);
  await expect(page.getByText("2 files chosen: 2 pictures.")).toBeVisible();
  await expect(page.getByText("No annotations among them. That is fine")).toBeVisible();
  await page.getByRole("button", { name: "Create dataset" }).click();

  await expect(page).toHaveURL(/\/datasets\/\d+$/);
  await expect(page.getByRole("heading", { level: 1, name: "Loose photos" })).toBeVisible();
  const history = page.getByRole("list", { name: "Versions, newest first" });
  await expect(history.getByRole("listitem")).toHaveCount(1);
  await expect(history).toContainText("First pictures");
  await expect(history).toContainText("2 pictures", { timeout: 15_000 });
  await expect(page.getByText("No annotations, so accuracy will show")).toBeVisible();
});

test("a whole folder with labels is read, its sources, classes and boxed pictures are shown", async ({
  page,
}) => {
  await page.goto("/datasets");
  await page.getByLabel("Dataset name").fill("Shelf folder");
  await page.getByLabel("Choose a folder of photos").setInputFiles(FOLDER);
  await expect(page.getByText(/13 files chosen: 6 pictures, 6 annotation files/)).toBeVisible();
  await page.getByRole("button", { name: "Create dataset" }).click();

  await expect(page).toHaveURL(/\/datasets\/\d+$/);
  const sources = page.getByRole("table", {
    name: "Pictures and annotated objects per capture source",
  });
  await expect(sources.getByRole("row", { name: /rpi-cam3-wide 3 3 3/ })).toBeVisible({
    timeout: 15_000,
  });
  await expect(sources.getByRole("row", { name: /mobile 3 3 3/ })).toBeVisible();
  await expect(page.getByText("6 annotated objects across 2 classes")).toBeVisible();
  await expect(page.getByText("This version has fewer than 50 pictures")).toBeVisible();
  await expect(page.getByRole("img", { name: /annotated object/ })).toHaveCount(6);
  await expect(page.locator("main svg rect")).toHaveCount(6); // one ground-truth box per picture
});

test("a zip is still accepted, and a zip with no pictures fails with the reason and can be discarded", async ({
  page,
}) => {
  await page.goto("/datasets");
  await page.getByLabel("Dataset name").fill("From a zip");
  await page.getByLabel("Choose photos or files").setInputFiles(zip("shelf.zip", "shelf.fixture"));
  await page.getByRole("button", { name: "Create dataset" }).click();
  await expect(page.getByText("6 annotated objects across 2 classes")).toBeVisible({
    timeout: 15_000,
  });

  await page.goto("/datasets");
  await page.getByLabel("Dataset name").fill("Only notes");
  await page.getByLabel("Choose photos or files").setInputFiles(zip("notes.zip", "notes.fixture"));
  await page.getByRole("button", { name: "Create dataset" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "No images were found" })).toBeVisible({
    timeout: 15_000,
  });
  await page.getByRole("button", { name: "Discard failed version 1" }).click();
  await expect(page.getByText("Nothing here yet.")).toBeVisible();
});

test("a folder path that does not exist is refused", async ({ page }) => {
  await page.goto("/datasets");
  await page.getByLabel("Read a folder that is on this computer").fill("C:\\no\\such\\folder");
  await page.getByRole("button", { name: "Read folder" }).click();
  await expect(page.getByRole("alert")).toContainText("full path of a folder that exists");
});

test("each save is a version: add pictures, see the change, restore an old version, download and share", async ({
  page,
  request,
}) => {
  const id = await addDataset(request);
  await page.goto(`/datasets/${String(id)}`);
  await expect(page.getByRole("list", { name: "Versions, newest first" })).toContainText(
    "First pictures",
  );

  await page.getByText("Add pictures, annotations or replace files").click();
  await page
    .getByLabel("Choose photos or files")
    .setInputFiles(path.join(FIXTURES, "shelf-folder", "images", "mobile", "3.jpg"));
  await expect(page.getByText("1 file chosen: 1 picture.")).toBeVisible();
  // the same picture again under another name is a change; a retaken one would be too
  await page.getByLabel("Describe this change").fill("A spare shot");
  await page.getByRole("button", { name: "Save as a new version" }).click();

  const history = page.getByRole("list", { name: "Versions, newest first" });
  await expect(history.getByRole("listitem")).toHaveCount(2, { timeout: 15_000 });
  await expect(history.getByRole("listitem").first()).toContainText("A spare shot");
  await expect(history.getByRole("listitem").first()).toContainText("7 pictures");
  await expect(history.getByRole("listitem").first()).toContainText("latest");

  // the files of any version can be downloaded; the whole dataset can be shared
  await expect(page.getByRole("link", { name: "Download files of version 1" })).toHaveAttribute(
    "href",
    `/api/datasets/${String(id)}/versions/1/download?kind=files`,
  );
  await expect(page.getByRole("link", { name: "Share (all versions)" })).toHaveAttribute(
    "href",
    `/api/datasets/${String(id)}/export`,
  );
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Normalised copy of version 2" }).click();
  expect((await download).suggestedFilename()).toBe("shelf-v2-normalised.zip");

  // restoring makes version 3 with the pictures of version 1; nothing is lost
  await page.getByRole("button", { name: "Restore version 1" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Restore" }).click();
  await expect(history.getByRole("listitem")).toHaveCount(3, { timeout: 15_000 });
  await expect(history.getByRole("listitem").first()).toContainText("Restore version 1");
  await expect(history.getByRole("listitem").first()).toContainText("6 pictures");
  await expect(history.getByRole("listitem").nth(1)).toContainText("A spare shot"); // still there
});

test("an NDJSON file with its pictures becomes a dataset", async ({ page }) => {
  const ndjson = [
    { type: "dataset", task: "detect", class_names: { "0": "chips", "1": "biscuit" } },
    {
      type: "image",
      file: "0.jpg",
      split: "train",
      annotations: { boxes: [[0, 0.5, 0.5, 0.4, 0.5]] },
    },
    {
      type: "image",
      file: "3.jpg",
      split: "val",
      annotations: { boxes: [[1, 0.5, 0.5, 0.4, 0.5]] },
    },
  ]
    .map((line) => JSON.stringify(line))
    .join("\n");
  const file = (name: string, buffer: Buffer, mimeType: string) => ({ name, mimeType, buffer });
  await page.goto("/datasets");
  await page.getByLabel("Dataset name").fill("From NDJSON");
  await page
    .getByLabel("Choose photos or files")
    .setInputFiles([
      file("shelf.ndjson", Buffer.from(ndjson), "application/x-ndjson"),
      file("0.jpg", fs.readFileSync(photo(0)), "image/jpeg"),
      file("3.jpg", fs.readFileSync(photo(3)), "image/jpeg"),
    ]);
  await expect(page.getByText("3 files chosen: 2 pictures, 1 NDJSON file.")).toBeVisible();
  await expect(page.getByText("An NDJSON file lists the pictures and their boxes.")).toBeVisible();
  await page.getByRole("button", { name: "Create dataset" }).click();
  await expect(page.getByText("2 annotated objects across 2 classes")).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByRole("img", { name: /annotated object/ })).toHaveCount(2);
});

test("a shared dataset is imported with its history", async ({ page, request }) => {
  const id = await addDataset(request, "Shared shelf");
  const bundle = await request.get(`/api/datasets/${String(id)}/export`);
  expect(bundle.status()).toBe(200);
  await page.goto("/datasets");
  await page.getByLabel("Choose a shared dataset file").setInputFiles({
    name: "Shared_shelf.ebdataset.zip",
    mimeType: "application/zip",
    buffer: await bundle.body(),
  });
  await expect(page).toHaveURL(/\/datasets\/\d+$/);
  await expect(page).not.toHaveURL(new RegExp(`/datasets/${String(id)}$`));
  await expect(page.getByRole("list", { name: "Versions, newest first" })).toContainText(
    "First pictures",
    { timeout: 15_000 },
  );
  await expect(page.getByText("6 annotated objects across 2 classes")).toBeVisible();
});

test("removing a dataset asks first, then takes it off the list", async ({ page, request }) => {
  const id = await addDataset(request);
  await page.goto(`/datasets/${String(id)}`);
  await page.getByRole("button", { name: "Remove dataset" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Remove dataset" }).click();
  await expect(page).toHaveURL(/\/datasets$/);
  await expect(page.getByText("No datasets yet")).toBeVisible();
});

// --- devices ----------------------------------------------------------------------------------------------------------

test("a device is added, shows the command to connect it, and goes online when its agent enrols", async ({
  page,
  request,
}) => {
  await page.goto("/devices");
  await page.getByRole("button", { name: "Get a connection command" }).click();
  const command = page.locator("pre");
  // the address is whatever the page was opened on: the API itself, or Vite in front of it in development
  await expect(command).toHaveText(
    /^python -m edgebench_agent --server http:\/\/127\.0\.0\.1:\d+ --token eb-enroll-\S+$/,
  );
  await expect(page.getByText("Waiting for its agent to connect")).toBeVisible();

  const token = (await command.innerText()).split("--token ")[1]?.trim() ?? "";
  const r = await request.post("/agent/enroll", {
    data: {
      token,
      fingerprint: { cpu: "Test CPU", pi_model: null, logical_cores: 8, os: "Test OS" },
    },
  });
  expect(r.status()).toBe(200);
  await expect(page.getByText("Online", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Test CPU")).toBeVisible();
  expect((await request.post("/agent/enroll", { data: { token, fingerprint: {} } })).status()).toBe(
    401,
  ); // works once
});

test("a machine that is not what you said it is gets a plain warning", async ({
  page,
  request,
}) => {
  await page.goto("/devices");
  await page.getByLabel("Type").selectOption("pi");
  await page.getByRole("button", { name: "Get a connection command" }).click();
  const token = ((await page.locator("pre").innerText()).split("--token ")[1] ?? "").trim();
  await request.post("/agent/enroll", {
    data: { token, fingerprint: { cpu: "Desktop", pi_model: null } },
  });
  await expect(
    page.getByText("You set this up as a Raspberry Pi, but the machine reports itself as a PC"),
  ).toBeVisible({
    timeout: 15_000,
  });
});

test("a device can be removed, and its agent is cut off", async ({ page, request }) => {
  const { auth } = await addDevice(request);
  await page.goto("/devices");
  await page.getByRole("button", { name: "Remove Test PC" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Remove device" }).click();
  await expect(page.getByText("No devices yet")).toBeVisible();
  expect((await request.post("/agent/claim", { headers: auth })).status()).toBe(401);
});

// --- the experiment form: limits that follow the device ---------------------------------------------------------------

test("the experiment form says what is missing before anything exists", async ({ page }) => {
  await page.goto("/experiments/new");
  await expect(page.getByText("Something is missing before you can run")).toBeVisible();
  await expect(page.getByRole("link", { name: "Add a model" })).toBeVisible();
});

test("threads cannot go beyond what the device has, and pinning to CPUs narrows them further", async ({
  page,
  request,
}) => {
  await addModel(request);
  await addDataset(request);
  await addDevice(request);
  await page.goto("/experiments/new");
  await page.getByRole("heading", { level: 1, name: "New experiment" }).waitFor();

  await expect(page.getByTestId("cpu-summary")).toContainText(
    "Test PC has 8 threads (4 physical cores). A run can use at most 8.",
  );
  const threads = page.getByLabel("Threads");
  await expect(threads).toHaveAttribute("max", "8");
  await threads.fill("10000");
  await expect(threads).toHaveValue("8"); // not a number the machine does not have

  await page.getByLabel("Pin the run to specific CPUs").check();
  await page.getByLabel("CPU numbers").fill("0-9");
  await expect(page.getByRole("alert")).toContainText(
    "CPU 8 does not exist: this device has CPUs 0 to 7",
  );
  await expect(page.getByRole("button", { name: "Start experiment" })).toBeDisabled();
  await page.getByLabel("CPU numbers").fill("0-3");
  await expect(page.getByText("Using 4 CPUs.")).toBeVisible();
  await expect(page.getByTestId("cpu-summary")).toContainText("A run can use at most 4.");
  await expect(threads).toHaveAttribute("max", "4");
  await expect(threads).toHaveValue("4"); // clamped to the pinned CPUs
});

// --- an experiment: one row, many runs ---------------------------------------------------------------------------------

test("an experiment compares many variants, is followed live, and is one row in Results ranked by your priority", async ({
  page,
  request,
}) => {
  await addModel(request);
  const dataset = await addDataset(request);
  const { auth } = await addDevice(request);

  await page.goto("/experiments/new");
  await page.getByLabel("Experiment name").fill("Does FP16 hurt on the shelf?");
  await page.getByRole("button", { name: "Select all for retail" }).click();
  await expect(page.getByText("This starts 6 runs, one after another.")).toBeVisible(); // 5 conversions that are ready + the .pt
  await page.getByLabel("Timed rounds", { exact: true }).fill("50");
  await page.getByRole("button", { name: "Start experiment" }).click();

  await expect(page).toHaveURL(/\/experiments\/\d+$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "Does FP16 hurt on the shelf?" }),
  ).toBeVisible();
  await expect(page.getByText("Running: 0 of 6 runs finished")).toBeVisible();

  await finishJobs(request, auth, 6);
  await expect(page.getByText("Finished: 6 of 6 runs finished")).toBeVisible({ timeout: 20_000 });
  const table = page.getByRole("table", {
    name: /Runs of this experiment, best first by mAP50-95/,
  });
  const rows = table.getByRole("row");
  await expect(rows.nth(1)).toContainText("55.0%"); // the best mAP50-95 is first
  await expect(rows.nth(1)).toContainText("best");
  await expect(rows.nth(2)).toContainText("52.0%");
  await expect(page.getByText("Does FP16 hurt on the shelf?").first()).toBeVisible();

  // Results: the whole experiment is a single row
  await page.getByRole("link", { name: "Results", exact: true }).first().click();
  const results = page.getByRole("table", { name: "Experiments, newest first" });
  await expect(results.getByRole("row")).toHaveCount(2); // header + one experiment
  await expect(results.getByRole("row", { name: /Does FP16 hurt on the shelf\?/ })).toContainText(
    "6 of 6 finished",
  );
  await expect(results.getByRole("row", { name: /Does FP16 hurt on the shelf\?/ })).toContainText(
    "55.0%",
  );
  expect(dataset).toBeGreaterThan(0);
});

test("Results are ranked by what you chose in Settings, and the choice is kept", async ({
  page,
  request,
}) => {
  await addModel(request);
  const dataset = await addDataset(request);
  const { auth, id: device } = await addDevice(request);
  const e = await startExperiment(request, device, dataset);
  await finishJobs(request, auth, 6);

  await page.goto("/settings");
  const list = page.getByRole("list", { name: "Your result priorities, most important first" });
  await expect(list.getByRole("listitem").first()).toContainText("mAP50-95");
  await page.getByRole("button", { name: "Move Median time per image up" }).click();
  await page.getByRole("button", { name: "Move Median time per image up" }).click();
  await expect(list.getByRole("listitem").first()).toContainText("Median time per image");
  await page.getByRole("button", { name: "Remove F1 score" }).click();
  await page.getByLabel("Add a metric").selectOption("recall");
  await expect(list.getByRole("listitem")).toHaveCount(3);

  await page.goto(`/experiments/${String(e.id)}`);
  await expect(page.getByText("Finished: 6 of 6 runs finished")).toBeVisible({ timeout: 20_000 });
  const table = page.getByRole("table", { name: /best first by Median time per image/ });
  await expect(table.getByRole("row").nth(1)).toContainText("8.0 ms"); // the fastest is first now
  await expect(table.getByRole("columnheader", { name: /Recall/ })).toBeVisible();
  await expect(table.getByRole("columnheader", { name: /F1/ })).toHaveCount(0);

  await page.reload(); // kept in this browser
  await expect(
    page.getByRole("table", { name: /best first by Median time per image/ }),
  ).toBeVisible();
  await page.goto("/settings");
  await page.getByRole("button", { name: "Use the defaults" }).click();
  await expect(list.getByRole("listitem").first()).toContainText("mAP50-95");
});

test("Results can be walked with the keyboard and the history buttons go back and forward", async ({
  page,
  request,
}) => {
  await addModel(request);
  const dataset = await addDataset(request);
  const { id: device } = await addDevice(request);
  const first = await startExperiment(request, device, dataset, "First experiment", false);
  const second = await startExperiment(request, device, dataset, "Second experiment", false);

  await page.goto("/results");
  await page.getByRole("table", { name: "Experiments, newest first" }).waitFor();
  const links = page.locator("a[data-row-link]");
  await links.first().focus();
  await expect(links.first()).toContainText("Second experiment"); // newest first
  await page.keyboard.press("ArrowDown");
  await expect(links.nth(1)).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(links.first()).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/experiments/${String(second.id)}$`));

  const back = page.getByRole("button", { name: "Back", exact: true });
  const forward = page.getByRole("button", { name: "Forward", exact: true });
  await expect(forward).toBeDisabled();
  await back.click();
  await expect(page).toHaveURL(/\/results$/);
  await expect(forward).toBeEnabled();
  await forward.click();
  await expect(page).toHaveURL(new RegExp(`/experiments/${String(second.id)}$`));
  await back.click();
  await page.getByRole("link", { name: "First experiment" }).click(); // a new page cuts off what was ahead
  await expect(page).toHaveURL(new RegExp(`/experiments/${String(first.id)}$`));
  await expect(forward).toBeDisabled();
});

test("the back button is off on the first page you opened", async ({ page }) => {
  await page.goto("/models");
  await page.getByRole("heading", { level: 1, name: "Models" }).waitFor();
  await expect(page.getByRole("button", { name: "Back", exact: true })).toBeDisabled();
  await page.getByRole("link", { name: "Datasets", exact: true }).first().click();
  await expect(page.getByRole("button", { name: "Back", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await expect(page).toHaveURL(/\/models$/);
});

test("an experiment can be cancelled, a run opened from it and removed, and the experiment removed", async ({
  page,
  request,
}) => {
  await addModel(request);
  const dataset = await addDataset(request);
  const { auth, id: device } = await addDevice(request);
  const e = await startExperiment(request, device, dataset, "Quick check", false);

  await page.goto(`/experiments/${String(e.id)}`);
  const job = await takeJob(request, auth); // one run is running, one waits
  await page.getByRole("button", { name: "Cancel what is left" }).click();
  await report(request, auth, job);
  await expect(page.getByText("Finished, some runs did not complete")).toBeVisible({
    timeout: 20_000,
  });

  await page
    .getByRole("table", { name: /Runs of this experiment/ })
    .getByRole("link")
    .first()
    .click();
  await expect(page).toHaveURL(/\/results\/\d+$/);
  await expect(page.getByRole("link", { name: "Quick check" })).toBeVisible(); // the breadcrumb back to its experiment
  await expect(page.getByText("Finished").first()).toBeVisible();
  await page.getByRole("button", { name: "Remove run" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Remove run" }).click();
  await expect(page).toHaveURL(new RegExp(`/experiments/${String(e.id)}$`));

  await page.getByRole("button", { name: "Delete experiment" }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("Do you really want to delete Quick check?");
  const confirm = dialog.getByRole("button", { name: "Delete experiment" });
  await expect(confirm).toBeDisabled(); // nothing typed yet
  await dialog.getByLabel(/To confirm, type/).fill("delete quick check");
  await expect(confirm).toBeDisabled(); // not exactly the phrase (case matters)
  await dialog.getByLabel(/To confirm, type/).fill("delete Quick check");
  await expect(confirm).toBeEnabled();
  await confirm.click();
  await expect(page).toHaveURL(/\/results$/);
  await expect(page.getByText("No results yet")).toBeVisible();
});

test("a run that failed on the device shows why", async ({ page, request }) => {
  await addModel(request);
  const dataset = await addDataset(request);
  const { auth, id: device } = await addDevice(request);
  const e = await startExperiment(request, device, dataset, "Missing runtime", false);
  const claimed = (await (await request.post("/agent/claim", { headers: auth })).json()) as {
    job_id: number;
    run_id: number;
  };
  await request.post("/agent/result", {
    headers: auth,
    data: {
      job_id: claimed.job_id,
      ok: false,
      kind: "unavailable",
      error: "ncnn is not installed on this device",
    },
  });
  await page.goto(`/results/${String(claimed.run_id)}`);
  await expect(
    page.getByRole("status").filter({ hasText: "Not available on this device" }),
  ).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("ncnn is not installed on this device");
  expect(e.id).toBeGreaterThan(0);
});

test("things that do not exist say so", async ({ page }) => {
  for (const [url, text] of [
    ["/results/99999", "That run is not here"],
    ["/experiments/99999", "That experiment is not here"],
    ["/datasets/99999", "That dataset is not here"],
  ] as const) {
    await page.goto(url);
    await expect(page.getByText(text)).toBeVisible();
  }
});

// --- models: a conversion of your own ----------------------------------------------------------------------------------

test("a conversion at another input size is added from the model page and gets its own grid", async ({
  page,
  request,
}) => {
  const model = await addModel(request);
  await page.goto(`/models/${String(model)}`);
  await page.getByLabel("Format and precision").selectOption("openvino_fp16");
  await page.getByLabel("Input size (pixels)").fill("320");
  await page.getByRole("button", { name: "Add this conversion" }).click();
  const grid = page.getByRole("table", { name: /320 px input/ });
  await expect(grid).toBeVisible({ timeout: 15_000 });
  await expect(grid.getByRole("row", { name: /OpenVINO/ })).toContainText("Ready", {
    timeout: 30_000,
  });
  await expect(
    page.getByRole("table", { name: /640 px input \(the model's own size\)/ }),
  ).toBeVisible();
  await page.getByLabel("Input size (pixels)").fill("330");
  await expect(page.getByRole("button", { name: "Add this conversion" })).toBeDisabled(); // not a multiple of 32
});

// --- the review of 2026-11-10 (second round) ----------------------------------------------------------------------------

test("the sidebar lists the parts of the page you are on and jumps to them", async ({ page }) => {
  await page.goto("/models");
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: "Add a model" })).toBeVisible();
  await nav.getByRole("link", { name: "Your models" }).click();
  await expect(page).toHaveURL(/\/models#your-models$/);
  await nav.getByRole("link", { name: "Datasets", exact: true }).click();
  await expect(nav.getByRole("link", { name: "Create a dataset" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Your datasets" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Add a model" })).toHaveCount(0); // only the page you are on
  await nav.getByRole("link", { name: "Devices", exact: true }).click();
  await expect(nav.getByRole("link", { name: "Add a device" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Your devices" })).toBeVisible();
});

test("help lives behind an i that explains on hover, instead of taking room on the page", async ({
  page,
}) => {
  await page.goto("/models");
  await expect(page.getByText("Upload a PyTorch model and EdgeBench converts")).toHaveCount(0); // not printed on the page
  const hint = page.getByRole("button", { name: /Upload a PyTorch model and EdgeBench converts/ });
  await hint.hover();
  await expect(
    page.getByText("Upload a PyTorch model and EdgeBench converts it to every format"),
  ).toBeVisible();
});

test("an experiment shows insights worked out from its results, and the metrics can be chosen on the page", async ({
  page,
  request,
}) => {
  await addModel(request);
  const dataset = await addDataset(request);
  const { auth, id: device } = await addDevice(request);
  const e = await startExperiment(request, device, dataset, "Insight check", false);
  await finishJobs(request, auth, 2, [0.5, 0.5], [20, 8]);

  await page.goto(`/experiments/${String(e.id)}`);
  const insights = page.getByRole("complementary", { name: "Insights" });
  await expect(insights).toContainText("Fastest:", { timeout: 20_000 });
  await expect(insights).toContainText("8.0 ms per image (about 125 images per second)");
  await expect(insights).toContainText(
    "2 runs give the same mAP50-95 (50.0%), so accuracy cannot tell them apart",
  );
  await expect(insights).toContainText("Each variant was run once");

  await page.getByText(/Metrics shown: 3/).click();
  await page.getByRole("checkbox", { name: "Precision" }).check();
  await page.getByRole("checkbox", { name: "Mean IoU" }).check();
  const table = page.getByRole("table", { name: /Runs of this experiment/ });
  await expect(table.getByRole("columnheader", { name: /Precision/ })).toBeVisible();
  await expect(table.getByRole("columnheader", { name: /IoU/ })).toBeVisible();
});

test("when runs tie on a metric the next priority decides, so the best run is marked on the tied columns too", async ({
  page,
  request,
}) => {
  await addModel(request);
  const dataset = await addDataset(request);
  const { auth, id: device } = await addDevice(request);
  const e = await startExperiment(request, device, dataset, "Ties", false);
  await finishJobs(request, auth, 2, [0.5, 0.5], [20, 8]); // identical accuracy, different speed

  await page.goto(`/experiments/${String(e.id)}`);
  const rows = page.getByRole("table", { name: /Runs of this experiment/ }).getByRole("row");
  await expect(rows.nth(1)).toContainText("8.0 ms", { timeout: 20_000 }); // the faster one leads
  await expect(rows.nth(1).getByText("best", { exact: true })).toHaveCount(3); // mAP50-95, F1 and median time
  await expect(rows.nth(2).getByText("best", { exact: true })).toHaveCount(0);
});

test("a run that is made again shows live, is tinted and numbered in its experiment, and no line about classes left out", async ({
  page,
  request,
}) => {
  await addModel(request);
  const dataset = await addDataset(request);
  const { auth, id: device } = await addDevice(request);
  const e = await startExperiment(request, device, dataset, "Repeat check", false);
  const job = await takeJob(request, auth);
  await report(request, auth, job, resultFor(0.5, 12, ["eno_lime", "oreo_chocolate"]));
  await finishJobs(request, auth, 1);

  const first = e.runs[0]?.id ?? 0;
  await page.goto(`/results/${String(first)}`);
  await expect(page.getByText("Left out because the model has no such class")).toHaveCount(0);
  await expect(page.getByRole("complementary", { name: "Insights" })).toContainText(
    "images per second",
    { timeout: 15_000 },
  );
  await page.getByRole("button", { name: "Run again" }).click();
  await expect(page.getByText(/Run \d+ was queued/)).toBeVisible();
  await expect(
    page.getByRole("status").filter({ hasText: "Waiting for the device" }),
  ).toBeVisible();

  // it is on the Live run page while it waits
  await page.goto("/live");
  await expect(page.getByRole("list", { name: "Runs that are running or waiting" })).toContainText(
    "retail",
  );
  await expect(page.getByText("Running and waiting (1)")).toBeVisible();

  const jobAgain = await takeJob(request, auth);
  await report(request, auth, jobAgain, resultFor(0.5, 9));
  await page.goto(`/experiments/${String(e.id)}`);
  const again = page.getByRole("row").filter({ hasText: "run again #2" });
  await expect(again).toHaveCount(1, { timeout: 20_000 });
  await expect(again).toHaveClass(/bg-primary/); // tinted, so it is easy to find among the rows
  await expect(page.getByRole("complementary", { name: "Insights" })).toContainText(
    "was run 2 times",
  );
});

test("a picture can be chosen and what each run found in it is shown next to the real boxes", async ({
  page,
  request,
}) => {
  await addModel(request);
  const dataset = await addDataset(request);
  const { auth, id: device } = await addDevice(request);
  const e = await startExperiment(request, device, dataset, "Inspect check", false);
  await finishJobs(request, auth, 2);

  await page.goto(`/experiments/${String(e.id)}`);
  await expect(
    page.getByText("Choose a picture above to compare what each run found in it."),
  ).toBeVisible();
  await page.getByRole("button", { name: /^Inspect picture 1:/ }).click();
  await expect(page.getByText("Real boxes")).toBeVisible();
  await expect(page.getByText(/^1 object: /)).toBeVisible();
  await expect(page.getByText(/^2 found: chips 91%, chips 40%/).first()).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByRole("img", { name: /with what retail, .* found/ })).toHaveCount(2); // one panel per run
  await page.getByLabel("Confidence cut-off for the detections shown").fill("0.95");
  await expect(page.getByText("Nothing found above 95%.").first()).toBeVisible();
});

// --- accessibility ------------------------------------------------------------------------------------------------------

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme });

    test("datasets, experiments, results, settings and the model page have no accessibility violations", async ({
      page,
      request,
    }) => {
      const model = await addModel(request);
      const dataset = await addDataset(request);
      const { auth, id: device } = await addDevice(request);
      const e = await startExperiment(request, device, dataset, "Accessibility check", false);
      await finishJobs(request, auth, 2);

      const checked: Record<string, string[]> = {};
      const visit = async (url: string, waitFor: string) => {
        await page.goto(url);
        await page.getByText(waitFor).first().waitFor();
        await expect(page.getByRole("status").filter({ hasText: "Connected" })).toBeVisible();
        checked[url] = await violations(page);
      };

      await visit("/datasets", "Your datasets");
      await visit(`/datasets/${String(dataset)}`, "Capture sources");
      await visit("/devices", "Test PC");
      await visit("/experiments/new", "Models and variants to compare");
      await visit(`/experiments/${String(e.id)}`, "Parameters and pictures");
      await visit("/results", "Accessibility check");
      await visit("/settings", "Metrics you judge by");
      await visit(`/models/${String(model)}`, "Add a conversion of your own");

      expect(checked).toEqual(Object.fromEntries(Object.keys(checked).map((k) => [k, []])));
    });
  });
}
