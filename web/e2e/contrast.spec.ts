import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

/** WCAG 2.x contrast ratio between two #rrggbb colours. */
function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function ratio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

const css = readFileSync("src/index.css", "utf8");

function tokens(selector: string): Record<string, string> {
  const block = new RegExp(`${selector.replace(".", "\\.")}\\s*\\{([^}]*)\\}`).exec(css)?.[1] ?? "";
  return Object.fromEntries(
    [...block.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})/g)].map((m) => [m[1], m[2]]),
  );
}

// Text pairs need 4.5:1 (WCAG AA). Boundaries of controls need 3:1 (WCAG 1.4.11).
const TEXT: [string, string][] = [
  ["foreground", "background"],
  ["card-foreground", "card"],
  ["popover-foreground", "popover"],
  ["muted-foreground", "background"],
  ["muted-foreground", "card"],
  ["muted-foreground", "muted"],
  ["muted-foreground", "sidebar"],
  ["primary-foreground", "primary"],
  ["primary", "background"],
  ["primary", "card"],
  ["secondary-foreground", "secondary"],
  ["accent-foreground", "accent"],
  ["sidebar-foreground", "sidebar"],
  ["sidebar-accent-foreground", "sidebar-accent"],
  ["sidebar-primary-foreground", "sidebar-primary"],
  ["destructive-foreground", "destructive"],
  ["destructive", "background"],
  ["destructive", "card"],
  ["ok", "background"],
  ["warn", "background"],
];
const BOUNDARY: [string, string][] = [
  ["input", "background"],
  ["input", "card"],
  ["ring", "background"],
  ["series-1", "card"], // chart marks (dataviz: 3:1 against the surface)
  ["series-2", "card"],
];

for (const [name, selector] of [
  ["light", ":root"],
  ["dark", ".dark"],
] as const) {
  test.describe(`${name} theme colours`, () => {
    const t = tokens(selector);
    for (const [fg, bg] of TEXT) {
      test(`${fg} on ${bg} is at least 4.5:1`, () => {
        expect(t[fg], `--${fg} missing`).toBeDefined();
        expect(t[bg], `--${bg} missing`).toBeDefined();
        expect(ratio(t[fg] ?? "", t[bg] ?? "")).toBeGreaterThanOrEqual(4.5);
      });
    }
    for (const [fg, bg] of BOUNDARY) {
      test(`${fg} against ${bg} is at least 3:1`, () => {
        expect(ratio(t[fg] ?? "", t[bg] ?? "")).toBeGreaterThanOrEqual(3);
      });
    }
  });
}
