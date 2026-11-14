import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { randomBytes, scryptSync } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

// The server asks for a password as soon as data/owner.json exists, so the test writes that file the way the server's
// `set-password` does (same scrypt cost and format: this also checks Node and Python agree) and removes it afterwards.
const PASSWORD = "correct horse battery";
const ownerFile = () => path.join(process.env.EDGEBENCH_E2E_DIR ?? "", "owner.json");

test.use({ colorScheme: "light" });
test.beforeEach(() => {
  const salt = randomBytes(16);
  const hash = scryptSync(PASSWORD, salt, 64, { N: 2 ** 15, r: 8, p: 1, maxmem: 64 * 1024 * 1024 });
  fs.writeFileSync(
    ownerFile(),
    JSON.stringify({ password: `scrypt$${salt.toString("base64")}$${hash.toString("base64")}` }),
  );
});
test.afterEach(() => {
  fs.rmSync(ownerFile(), { force: true });
});

test("with an owner password the site asks for it, and signing out asks again", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in to EdgeBench" })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.getByLabel("Owner password").fill("not the password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText("That password is not right.");

  await page.getByLabel("Owner password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Dashboard" })).toBeVisible();

  await page.reload(); // the cookie keeps the session
  await expect(page.getByRole("heading", { level: 1, name: "Dashboard" })).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to EdgeBench" })).toBeVisible();
});

test("a session that ended is noticed without a reload", async ({ page, context }) => {
  await page.goto("/");
  await page.getByLabel("Owner password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Dashboard" })).toBeVisible();
  await context.clearCookies(); // as if the session had expired; the next poll of /api/health gets 401
  await expect(page.getByRole("heading", { name: "Sign in to EdgeBench" })).toBeVisible({
    timeout: 15_000,
  });
});
