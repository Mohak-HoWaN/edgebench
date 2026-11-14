import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// A model made by a newer Ultralytics than the converter has must be stopped and explained, and a conversion built by an older
// converter must say so. The stand-in converter reads "TRAINED_WITH=x" from inside a model file and its own claimed version from
// a file this test rewrites (see playwright.config.ts), so both situations can be made here.

test.use({ colorScheme: "light" });

const GOOD = fs.readFileSync(path.resolve("e2e", "fixtures", "checkpoint.fixture"));
const versionFile = () => path.join(process.env.EDGEBENCH_E2E_DIR ?? "", "ultralytics.txt");
const made = (version: string) => Buffer.concat([GOOD, Buffer.from(`TRAINED_WITH=${version}`)]);

async function uploadViaApi(request: APIRequestContext, name: string, data: Buffer) {
  const r = await request.post("/api/models", {
    data,
    headers: { "x-filename": name, "content-type": "application/octet-stream" },
  });
  expect(r.status()).toBe(201);
  return ((await r.json()) as { id: number }).id;
}

async function status(request: APIRequestContext, id: number) {
  return (await (await request.get(`/api/models/${String(id)}`)).json()) as {
    status: string;
    error: string | null;
    variants: { state: string; stale: string | null; built_with: Record<string, string> | null }[];
  };
}

async function settle(request: APIRequestContext) {
  fs.rmSync(versionFile(), { force: true });
  await request.post("/api/converter/refresh");
}

test.afterEach(async ({ request }) => {
  const models = (await (await request.get("/api/models")).json()) as { id: number }[];
  for (const m of models) await request.delete(`/api/models/${String(m.id)}`);
  await settle(request); // later specs must see the converter as it was
});

test("a model the converter is too old for is stopped with a plain explanation, then converts after an upgrade", async ({
  page,
  request,
}) => {
  fs.writeFileSync(versionFile(), "8.3.248"); // the converter claims an old Ultralytics
  await request.post("/api/converter/refresh");
  const id = await uploadViaApi(request, "yolo26.pt", made("8.4.208"));
  await expect
    .poll(async () => (await status(request, id)).status, { timeout: 30_000 })
    .toBe("incompatible");
  expect((await status(request, id)).variants).toEqual([]);

  await page.goto(`/models/${String(id)}`);
  const alert = page.getByRole("alert").filter({ hasText: "cannot read this model yet" });
  await expect(alert).toContainText("Nothing is wrong with your model");
  await expect(alert).toContainText("8.4.208");
  await expect(alert).toContainText("8.3.248");
  await expect(page.getByText(/^Trained with Ultralytics 8.4.208/)).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  // a run on it is refused with the same words
  const refused = await request.post("/api/runs", {
    data: { model_id: id, dataset_id: 1, device_id: 1 },
  });
  expect(refused.status()).toBe(422);

  fs.writeFileSync(versionFile(), "8.4.212"); // the owner upgraded the converter
  await page.getByRole("button", { name: "Check again" }).click();
  await expect(page.getByRole("heading", { name: "Conversions" })).toBeVisible({ timeout: 30_000 });
  await expect(alert).toHaveCount(0);
});

test("conversions built before a converter change say so, cannot be run, and can be rebuilt", async ({
  page,
  request,
}) => {
  const id = await uploadViaApi(request, "old-build.pt", GOOD); // built while the converter claims version 0
  await expect
    .poll(
      async () => (await status(request, id)).variants.filter((v) => v.state === "ready").length,
      { timeout: 40_000 },
    )
    .toBeGreaterThan(0);
  expect((await status(request, id)).variants.every((v) => v.stale === null)).toBe(true);

  fs.writeFileSync(versionFile(), "8.4.212");
  await page.goto("/settings");
  await page.getByRole("button", { name: "Check the converter again" }).click();
  await expect(page.getByText(/ultralytics 8\.4\.212/)).toBeVisible();

  await page.goto(`/models/${String(id)}`);
  await expect(
    page.getByText(/Built by an older converter: .*ultralytics 0 \(now 8\.4\.212\)/).first(),
  ).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: /^Rebuild ONNX FP32$/ }).click();
  await expect
    .poll(
      async () =>
        (await status(request, id)).variants.some((v) => v.built_with?.ultralytics === "8.4.212"),
      {
        timeout: 40_000,
      },
    )
    .toBe(true);
});
