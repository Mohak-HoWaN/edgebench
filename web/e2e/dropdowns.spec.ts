import { expect, test, type Page } from "@playwright/test";

/**
 * A dropdown's list is drawn by the browser from the select's own colours, so a translucent background there turned into grey
 * text on a grey list. These tests read the colours the browser will use (select and options) and check that they are solid
 * and readable, in both themes, on every page that has a dropdown without needing data.
 */

interface Painted {
  selectText: number[];
  selectBackground: number[];
  optionText: number[];
  optionBackground: number[];
}

async function painted(page: Page, label: string): Promise<Painted> {
  return page.getByLabel(label).evaluate((el) => {
    const select = el as HTMLSelectElement;
    // whatever notation the browser reports (rgb, color-mix, oklab), the canvas turns it into the pixel that is actually painted
    const rgba = (css: string): number[] => {
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 1;
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      if (!ctx) return [0, 0, 0, 0];
      ctx.clearRect(0, 0, 1, 1);
      ctx.fillStyle = css;
      ctx.fillRect(0, 0, 1, 1);
      return [...ctx.getImageData(0, 0, 1, 1).data];
    };
    const option = select.options.item(0);
    if (!option) throw new Error("the select has no options");
    const s = getComputedStyle(select);
    const o = getComputedStyle(option);
    return {
      selectText: rgba(s.color),
      selectBackground: rgba(s.backgroundColor),
      optionText: rgba(o.color),
      optionBackground: rgba(o.backgroundColor),
    };
  });
}

const channel = (v: number) => {
  const c = v / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};
const luminance = (c: number[]) =>
  0.2126 * channel(c[0] ?? 0) + 0.7152 * channel(c[1] ?? 0) + 0.0722 * channel(c[2] ?? 0);
const contrast = (a: number[], b: number[]) =>
  (Math.max(luminance(a), luminance(b)) + 0.05) / (Math.min(luminance(a), luminance(b)) + 0.05);

const DROPDOWNS = [
  { path: "/settings", label: "Add a metric" },
  { path: "/devices", label: "Type" },
];

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme });

    for (const { path, label } of DROPDOWNS) {
      test(`the "${label}" dropdown on ${path} is solid and readable`, async ({ page }) => {
        await page.goto(path);
        await page.getByRole("heading", { level: 1 }).waitFor();
        const c = await painted(page, label);
        expect(c.selectBackground[3], "the control's background is opaque").toBe(255);
        expect(c.optionBackground[3], "the list's background is opaque").toBe(255);
        expect(
          contrast(c.selectText, c.selectBackground),
          "text in the control",
        ).toBeGreaterThanOrEqual(4.5);
        expect(
          contrast(c.optionText, c.optionBackground),
          "text in the list",
        ).toBeGreaterThanOrEqual(4.5);
        expect(c.optionBackground.slice(0, 3), "the list matches the control").toEqual(
          c.selectBackground.slice(0, 3),
        );
      });
    }
  });
}
