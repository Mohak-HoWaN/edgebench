import fs from "node:fs";
import path from "node:path";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

test.use({ colorScheme: "light" });

const FIXTURES = path.resolve("e2e", "fixtures");
const GOOD = path.join(FIXTURES, "checkpoint.fixture");
const EVIL = path.join(FIXTURES, "evil.fixture");

/** A fixture presented to the page as a .pt file with the given name. */
const payload = (file: string, name: string) => ({
  name,
  mimeType: "application/octet-stream",
  buffer: fs.readFileSync(file),
});

// The e2e server's stand-in converter fails ncnn FP16, lacks a package for ncnn FP32, and gives OpenVINO FP16 an output that
// differs from PyTorch, and TorchScript FP32 converts but its check against PyTorch crashes; everything else converts cleanly. See playwright.config.ts.
const SETTLED = "5 of 7 converted, 1 failed, 1 not available";

/** Models live in the server's database, which the whole run shares: leave none behind for the other specs. */
test.afterEach(async ({ request }: { request: APIRequestContext }) => {
  const models = (await (await request.get("/api/models")).json()) as { id: number }[];
  for (const m of models) await request.delete(`/api/models/${String(m.id)}`);
});

async function upload(
  page: Page,
  file: string | { name: string; mimeType: string; buffer: Buffer },
) {
  await page.goto("/models");
  await page.getByRole("heading", { level: 1, name: "Models" }).waitFor();
  await page.getByLabel("Choose a PyTorch model file (.pt)").setInputFiles(file);
}

/** Upload the good fixture under a .pt name and wait for the matrix to finish. */
async function uploadAndSettle(page: Page, name = "retail.pt") {
  await upload(page, payload(GOOD, name));
  await expect(page).toHaveURL(/\/models\/\d+$/);
  await expect(page.getByText("2 not converted.")).toBeVisible({ timeout: 30_000 });
}

const cell = (page: Page, format: string, precision: string) =>
  page
    .getByRole("row", { name: new RegExp(`^${format}`) })
    .getByRole("cell")
    .nth(precision === "FP32" ? 0 : 1);

test("the Models page invites an upload and lists nothing yet", async ({ page }) => {
  await page.goto("/models");
  await expect(page.getByText("No models yet")).toBeVisible();
  await expect(page.getByRole("button", { name: "Choose a .pt file" })).toBeEnabled();
});

test("an uploaded model is read, then every cell of the grid reaches a final state", async ({
  page,
}) => {
  await uploadAndSettle(page);
  await expect(page.getByRole("heading", { level: 1, name: "retail" })).toBeVisible();
  await expect(
    page.getByText("detect, 640 px input, 2.6 M parameters, 6.5 GFLOPs, 3 classes"),
  ).toBeVisible();

  await expect(cell(page, "ONNX", "FP32")).toContainText("Ready");
  await expect(cell(page, "ONNX", "FP16")).toContainText("Ready");
  await expect(cell(page, "TorchScript", "FP32")).toContainText(
    "Ready, but could not be checked against PyTorch",
  );
  await expect(cell(page, "TorchScript", "FP32")).toContainText("RuntimeError: the check crashed");
  await expect(cell(page, "OpenVINO", "FP32")).toContainText("Ready");
  await expect(cell(page, "ncnn", "FP16")).toContainText("Failed");
  await expect(cell(page, "ncnn", "FP16")).toContainText("RuntimeError: boom");
  await expect(cell(page, "ncnn", "FP32")).toContainText("Not available");
  await expect(cell(page, "ncnn", "FP32")).toContainText("not installed");
  await expect(cell(page, "OpenVINO", "FP16")).toContainText("Ready, but differs from PyTorch");
  await expect(cell(page, "OpenVINO", "FP16")).toContainText("Largest difference from PyTorch 90%");

  // TorchScript has no FP16 build: a dash, announced as such
  await expect(cell(page, "TorchScript", "FP16")).toContainText("Not offered for TorchScript");
});

test("one failing cell never stops the others, and the list says where the model stands", async ({
  page,
}) => {
  await uploadAndSettle(page);
  await page.getByRole("link", { name: "Models", exact: true }).first().click();
  await expect(page.getByRole("link", { name: /retail/ })).toContainText(SETTLED);
  await expect(page.getByRole("link", { name: /retail/ })).toContainText(
    "detect, 3 classes, 2.6 M parameters",
  );
});

test("a failed conversion's log can be read", async ({ page }) => {
  await uploadAndSettle(page);
  await cell(page, "ncnn", "FP16").getByRole("button", { name: /Log/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("ncnn FP16");
  await expect(dialog.getByLabel("Converter log")).toContainText("RuntimeError: boom");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

test("a converted model can be downloaded, one file or a zip, and only when it is ready", async ({
  page,
}) => {
  await uploadAndSettle(page);
  const onnx = page.waitForEvent("download");
  await cell(page, "ONNX", "FP32")
    .getByRole("link", { name: /Download/ })
    .click();
  expect((await onnx).suggestedFilename()).toBe("retail-onnx_fp32.onnx");

  const zip = page.waitForEvent("download");
  await cell(page, "OpenVINO", "FP32")
    .getByRole("link", { name: /Download/ })
    .click();
  expect((await zip).suggestedFilename()).toBe("retail-openvino_fp32.zip");

  const all = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download all converted (zip)" }).click();
  expect((await all).suggestedFilename()).toBe("retail-variants.zip");

  await expect(cell(page, "ncnn", "FP16").getByRole("link", { name: /Download/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /not separate models/ })).toBeVisible();
});

test("a failed cell can be retried from the grid", async ({ page }) => {
  await uploadAndSettle(page);
  const retried = page.waitForResponse(
    (r) => /\/api\/variants\/\d+\/retry$/.test(r.url()) && r.request().method() === "POST",
  );
  await cell(page, "ncnn", "FP16").getByRole("button", { name: /Retry/ }).click();
  expect((await retried).status()).toBe(200);
  await expect(cell(page, "ncnn", "FP16")).toContainText("Failed", { timeout: 30_000 }); // the stand-in fails it again
});

test("the same file uploaded again opens the model that is already there", async ({ page }) => {
  await uploadAndSettle(page);
  const first = page.url();
  await upload(page, payload(GOOD, "retail.pt"));
  await expect(page).toHaveURL(first);
  await expect(page.getByText("That exact file was uploaded before")).toBeVisible();
});

test("a file that would run code when opened is refused, with the reason", async ({ page }) => {
  await upload(page, payload(EVIL, "trojan.pt"));
  await expect(page.getByRole("alert")).toContainText("refers to code a model never needs");
  await expect(page.getByRole("alert")).toContainText("nt.system");
  await expect(page).toHaveURL("/models");
  await expect(page.getByText("No models yet")).toBeVisible();
});

test("a renamed text file and a wrong file type are refused in plain words", async ({ page }) => {
  await upload(page, {
    name: "notes.pt",
    mimeType: "text/plain",
    buffer: Buffer.from("just some words"),
  });
  await expect(page.getByRole("alert")).toContainText("not a PyTorch checkpoint");
  await page.getByLabel("Choose a PyTorch model file (.pt)").setInputFiles({
    name: "model.onnx",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("x"),
  });
  await expect(page.getByRole("alert")).toContainText("Only PyTorch checkpoints (.pt files)");
});

test("removing a model asks first, then takes it off the list", async ({ page }) => {
  await uploadAndSettle(page);
  await page.getByRole("button", { name: "Remove model" }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("Remove retail?");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "retail" })).toBeVisible();

  await page.getByRole("button", { name: "Remove model" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Remove model" }).click();
  await expect(page).toHaveURL("/models");
  await expect(page.getByText("retail was removed")).toBeVisible();
  await expect(page.getByText("No models yet")).toBeVisible();
});

test("an address for a model that does not exist says so", async ({ page }) => {
  await page.goto("/models/99999");
  await expect(page.getByRole("heading", { level: 1, name: "Model not found" })).toBeVisible();
  await expect(page.getByText("There is no such model.")).toBeVisible();
});

test("when the converter is not set up, the page explains it", async ({ page }) => {
  await page.route("**/api/converter", (route) =>
    route.fulfill({
      json: {
        available: false,
        message: "No converter environment is set up.",
        python: null,
        versions: {},
        missing: [],
      },
    }),
  );
  await page.goto("/models");
  await expect(page.getByRole("alert")).toContainText(
    "The converter is not set up on this computer.",
  );
  await expect(page.getByRole("alert")).toContainText("converter/README.md");
});
