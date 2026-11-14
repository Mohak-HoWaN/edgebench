import { expect, test, type Page } from "@playwright/test";

test.use({ colorScheme: "light" });

const PAGES = [
  { link: "Dashboard", path: "/", heading: "Dashboard", empty: "No experiments yet" },
  { link: "Models", path: "/models", heading: "Models", empty: "No models yet" },
  { link: "Datasets", path: "/datasets", heading: "Datasets", empty: "No datasets yet" },
  { link: "Devices", path: "/devices", heading: "Devices", empty: "No devices yet" },
  {
    link: "New experiment",
    path: "/experiments/new",
    heading: "New experiment",
    empty: "Something is missing before you can run",
  },
  { link: "Results", path: "/results", heading: "Results", empty: "No results yet" },
  {
    link: "Compare",
    path: "/compare",
    heading: "Compare",
    empty: "Nothing to compare yet",
  },
  { link: "Reports", path: "/reports", heading: "Reports", empty: "No reports yet" },
  { link: "Settings", path: "/settings", heading: "Settings", empty: "Appearance" },
];

const html = (page: Page) => page.locator("html");
const mainNav = (page: Page) => page.getByRole("navigation", { name: "Main" });

/** Go to a page and wait until the app has rendered it, so key presses are not sent into a page that is still loading. */
async function open(page: Page, path: string) {
  await page.goto(path);
  await page.getByRole("heading", { level: 1 }).waitFor();
}

test("every page opens from the sidebar and shows its content", async ({ page }) => {
  await open(page, "/");
  for (const p of PAGES) {
    await mainNav(page).getByRole("link", { name: p.link, exact: true }).click();
    await expect(page).toHaveURL(p.path);
    await expect(page.getByRole("heading", { level: 1, name: p.heading })).toBeVisible();
    await expect(page.getByText(p.empty).first()).toBeVisible();
    await expect(page).toHaveTitle(`${p.heading} - EdgeBench`);
  }
});

test("the current page is marked in the sidebar", async ({ page }) => {
  await open(page, "/models");
  await expect(mainNav(page).getByRole("link", { name: "Models", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(mainNav(page).getByRole("link", { name: "Datasets" })).not.toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("the dashboard shows real server details", async ({ page }) => {
  await open(page, "/");
  const server = page.getByRole("region", { name: "Server" });
  await expect(server).toContainText("Working");
  await expect(server).toContainText("0.1.0");
  await expect(server).toContainText("Ready (wal journal)");
  await expect(server).toContainText("Running");
  await expect(server).toContainText("0 waiting, 0 running, 0 failed");
});

test("live updates connect and the sidebar says so", async ({ page }) => {
  await open(page, "/");
  await expect(page.getByRole("status")).toHaveText("Connected");
});

test("a deep link survives a reload, and an unknown address says so", async ({ page }) => {
  await open(page, "/datasets");
  await expect(page.getByRole("heading", { level: 1, name: "Datasets" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Datasets" })).toBeVisible();
  await open(page, "/no/such/page");
  await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
});

test("the theme toggle switches, persists across a reload, and Settings can change it back", async ({
  page,
}) => {
  await open(page, "/");
  await expect(html(page)).not.toHaveClass(/dark/);
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(html(page)).toHaveClass(/dark/);
  await page.reload();
  await expect(html(page)).toHaveClass(/dark/);
  expect(await page.evaluate(() => localStorage.getItem("edgebench.theme"))).toBe("dark");

  await mainNav(page).getByRole("link", { name: "Settings" }).click();
  await page.getByRole("radio", { name: "Light" }).click();
  await expect(html(page)).not.toHaveClass(/dark/);
  await expect(page.getByRole("radio", { name: "Light" })).toBeChecked();
});

test("the theme follows the system while the choice is 'match system'", async ({ page }) => {
  await open(page, "/");
  await expect(html(page)).not.toHaveClass(/dark/);
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(html(page)).toHaveClass(/dark/);
});

test("Ctrl+K opens the palette and Enter goes to the match", async ({ page }) => {
  await open(page, "/");
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.type("datasets");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL("/datasets");
  await expect(page.getByRole("dialog")).toBeHidden();
});

test("'g' then a letter jumps to a page, but not while typing in the palette", async ({ page }) => {
  await open(page, "/");
  await page.keyboard.press("g");
  await page.keyboard.press("m");
  await expect(page).toHaveURL("/models");

  await page.keyboard.press("Control+k");
  await page.keyboard.type("gs");
  await expect(page).toHaveURL("/models");
  await expect(page.getByPlaceholder("Search pages and actions")).toHaveValue("gs");
});

test("the palette changes the theme too", async ({ page }) => {
  await open(page, "/");
  await page.keyboard.press("Control+k");
  await page.keyboard.type("dark");
  await page.keyboard.press("Enter");
  await expect(html(page)).toHaveClass(/dark/);
});

test("when the server cannot be reached the page says so, and recovers on retry", async ({
  page,
}) => {
  await page.route("**/api/health", (route) => route.abort());
  await open(page, "/");
  const banner = page.getByRole("alert");
  await expect(banner).toContainText("cannot reach its server", { timeout: 15_000 });
  await expect(page.getByRole("status")).toHaveText("Server unreachable");

  await page.unroute("**/api/health");
  await banner.getByRole("button", { name: "Retry now" }).click();
  await expect(banner).toBeHidden();
  await expect(page.getByRole("status")).toHaveText("Connected");
});

test("resetting preferences asks first, and cancelling changes nothing", async ({ page }) => {
  await open(page, "/settings");
  await page.getByRole("radio", { name: "Dark" }).click();
  await expect(html(page)).toHaveClass(/dark/);

  await page.getByRole("button", { name: "Reset preferences" }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("Reset interface preferences?");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  await expect(html(page)).toHaveClass(/dark/);

  await page.getByRole("button", { name: "Reset preferences" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Reset preferences" }).click();
  await expect(html(page)).not.toHaveClass(/dark/);
  await expect(page.getByText("Interface preferences reset")).toBeVisible();
  // Reset forgets the choice; it must not write "system" back as if the person had picked it.
  expect(await page.evaluate(() => localStorage.getItem("edgebench.theme"))).toBeNull();
});

test("page shortcuts do nothing behind an open dialog, and Ctrl+K does not open over a confirmation", async ({
  page,
}) => {
  await open(page, "/settings");
  await page.getByRole("button", { name: "Reset preferences" }).click();
  await expect(page.getByRole("alertdialog")).toBeVisible();

  await page.keyboard.press("g");
  await page.keyboard.press("d");
  await expect(page).toHaveURL("/settings");

  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page.getByRole("alertdialog")).toBeVisible();
});

test("a capital letter still counts, as with Caps Lock on", async ({ page }) => {
  await open(page, "/");
  await page.keyboard.press("G");
  await page.keyboard.press("M");
  await expect(page).toHaveURL("/models");
});

test("at tablet width nothing scrolls sideways and the palette still reaches every page", async ({
  page,
}) => {
  await page.setViewportSize({ width: 768, height: 900 });
  for (const p of PAGES) {
    await open(page, p.path);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `${p.path} scrolls sideways`).toBeLessThanOrEqual(0);
  }
  await open(page, "/");
  await page.getByRole("button", { name: "Go to" }).click();
  await page.keyboard.type("results");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL("/results");
});

test("the skip link moves focus to the main content", async ({ page }) => {
  await open(page, "/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
});
