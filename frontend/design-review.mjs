// Design-review harness: sweeps every screen x viewport x theme, saves
// screenshots to design-review/, and audits each combination for WCAG
// color-contrast violations (axe-core) and horizontal overflow.
//
// Run:  npm run design-review   (dev server must be up on :5173)

import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { mkdirSync } from "node:fs";

const BASE = process.env.BASE_URL ?? "http://localhost:5173";
const SCREENS = ["welcome", "live", "call", "practice", "settings"];
const VIEWPORTS = [
  { name: "phone", width: 390, height: 844 },
  { name: "desktop", width: 1440, height: 900 },
];
const THEMES = ["light", "dark"];
const OUT = new URL("./design-review/", import.meta.url).pathname;

mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const findings = [];

for (const vp of VIEWPORTS) {
  const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
  const page = await context.newPage();
  for (const screen of SCREENS) {
    for (const theme of THEMES) {
      const id = `${screen}-${vp.name}-${theme}`;
      await page.goto(`${BASE}/#${screen}`, { waitUntil: "networkidle" });
      await page.evaluate(
        (isDark) => document.documentElement.classList.toggle("dark", isDark),
        theme === "dark",
      );
      await page.waitForTimeout(250);
      await page.screenshot({ path: `${OUT}${id}.png`, fullPage: true });

      // Horizontal overflow: the most common responsive bug
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      if (overflow > 1) findings.push({ id, type: "overflow", detail: `${overflow}px wider than viewport` });

      // WCAG color-contrast audit (serious/critical only)
      const axe = await new AxeBuilder({ page }).withRules(["color-contrast"]).analyze();
      for (const v of axe.violations) {
        for (const node of v.nodes.slice(0, 8)) {
          findings.push({
            id,
            type: "contrast",
            detail: node.any[0]?.message ?? v.help,
            target: node.target.join(" "),
            snippet: node.html.slice(0, 120),
          });
        }
      }
    }
  }
  await context.close();
}

await browser.close();

console.log(`\n${findings.length} findings\n`);
for (const f of findings) {
  console.log(`[${f.id}] ${f.type}: ${f.detail}`);
  if (f.snippet) console.log(`    ${f.target}\n    ${f.snippet}`);
}
