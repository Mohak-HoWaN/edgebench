import fs from "node:fs";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const PATHS = [
  "/",
  "/models",
  "/datasets",
  "/devices",
  "/experiments/new",
  "/results",
  "/reports",
  "/settings",
  "/no/such/page",
];

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];

async function violations(page: Page) {
  const { violations: found } = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  return found.map(
    (v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`,
  );
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme });

    for (const path of PATHS) {
      test(`${path} has no accessibility violations`, async ({ page }) => {
        await page.goto(path);
        await page.getByRole("heading", { level: 1 }).waitFor();
        await expect(page.getByRole("status")).toHaveText("Connected");
        expect(await violations(page)).toEqual([]);
      });
    }

    test("the command palette has no accessibility violations", async ({ page }) => {
      await page.goto("/");
      await page.getByRole("heading", { level: 1 }).waitFor();
      await page.keyboard.press("Control+k");
      await page.getByRole("dialog").waitFor();
      expect(await violations(page)).toEqual([]);
    });

    test("the confirm dialog has no accessibility violations", async ({ page }) => {
      await page.goto("/settings");
      await page.getByRole("button", { name: "Reset preferences" }).click();
      await page.getByRole("alertdialog").waitFor();
      expect(await violations(page)).toEqual([]);
    });

    test("the Models page with a model in it, its detail page and its log dialog have no accessibility violations", async ({
      page,
      request,
    }) => {
      const buffer = fs.readFileSync(path.resolve("e2e", "fixtures", "checkpoint.fixture"));
      const created = await request.post("/api/models", {
        data: buffer,
        headers: { "x-filename": "retail.pt" },
      });
      const { id } = (await created.json()) as { id: number };
      try {
        await expect
          .poll(
            async () => {
              const m = (await (await request.get(`/api/models/${String(id)}`)).json()) as {
                variants: { state: string }[];
              };
              return (
                m.variants.length === 7 &&
                m.variants.every((v) => ["ready", "failed", "unavailable"].includes(v.state))
              );
            },
            { timeout: 30_000 },
          )
          .toBe(true);

        await page.goto("/models");
        await page.getByRole("link", { name: /retail/ }).waitFor();
        expect(await violations(page)).toEqual([]);

        await page.goto(`/models/${String(id)}`);
        await expect(page.getByText("2 not converted.")).toBeVisible();
        expect(await violations(page)).toEqual([]);

        await page.getByRole("button", { name: /Log for ncnn FP16/ }).click();
        await page.getByRole("dialog").waitFor();
        expect(await violations(page)).toEqual([]);
      } finally {
        await request.delete(`/api/models/${String(id)}`);
      }
    });
  });
}
