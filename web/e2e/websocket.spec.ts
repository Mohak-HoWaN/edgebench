import { expect, test, type Page } from "@playwright/test";

interface Tracked {
  __sockets: WebSocket[];
}

/** Record every WebSocket the page opens so the test can count how many are still open. */
async function trackSockets(page: Page) {
  await page.addInitScript(() => {
    const Native = window.WebSocket;
    const all: WebSocket[] = [];
    Object.assign(window, { __sockets: all });
    window.WebSocket = class extends Native {
      constructor(...args: ConstructorParameters<typeof WebSocket>) {
        super(...args);
        all.push(this);
      }
    };
  });
}

const openSockets = (page: Page) =>
  page.evaluate(
    () =>
      // Only the app's own socket: in development Vite also keeps a hot-reload socket open on the page.
      (window as unknown as Tracked).__sockets.filter(
        (s) => s.url.endsWith("/ws/events") && s.readyState <= WebSocket.OPEN,
      ).length,
  );

// Run once against the built app and once with E2E_DEV=1: React's development double-effect once left an orphan
// socket per page visit in a sister project, which used up the server's connection limit.
test("exactly one live-update socket stays open through many page changes and reloads", async ({
  page,
}) => {
  await trackSockets(page);
  await page.goto("/");
  await expect(page.getByRole("status")).toHaveText("Connected");

  const links = ["Models", "Datasets", "Devices", "Results", "Settings", "Dashboard"];
  for (let round = 0; round < 3; round++) {
    for (const name of links) {
      await page
        .getByRole("navigation", { name: "Main" })
        .getByRole("link", { name, exact: true })
        .click();
      await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
    }
  }
  await expect(page.getByRole("status")).toHaveText("Connected");
  expect(await openSockets(page)).toBe(1);

  await page.reload();
  await expect(page.getByRole("status")).toHaveText("Connected");
  expect(await openSockets(page)).toBe(1);
});

test("the live-update socket reconnects after the server closes it", async ({ page }) => {
  await trackSockets(page);
  await page.goto("/");
  await expect(page.getByRole("status")).toHaveText("Connected");
  await page.evaluate(() => {
    for (const s of (window as unknown as Tracked).__sockets) s.close();
  });
  await expect(page.getByRole("status")).toHaveText("Connected", { timeout: 15_000 });
  expect(await openSockets(page)).toBe(1);
});
