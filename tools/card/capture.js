#!/usr/bin/env node
/**
 * Playwright-based HTML → PNG screenshot.
 * Usage: node capture.js <html-file> <output.png> <width> [height] [fullpage]
 */

const path = require("path");
const fs = require("fs");

async function main() {
  const [htmlPath, outputPath, widthStr, heightStr, fullpageFlag] =
    process.argv.slice(2);

  if (!htmlPath || !outputPath) {
    console.error(
      "Usage: node capture.js <html> <output.png> <width> [height] [fullpage]"
    );
    process.exit(1);
  }

  const width = parseInt(widthStr) || 1080;
  const height = parseInt(heightStr) || 800;
  const fullpage = fullpageFlag === "fullpage";

  let chromium;
  try {
    chromium = require("playwright").chromium;
  } catch {
    console.error("Playwright not found. Run: npm install && npx playwright install chromium");
    process.exit(1);
  }

  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.setViewportSize({ width, height: fullpage ? 800 : height });

  const fileUrl = "file://" + path.resolve(htmlPath);
  await page.goto(fileUrl, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  if (fullpage) {
    const bodyHeight = await page.evaluate(
      () => document.body.scrollHeight
    );
    await page.setViewportSize({ width, height: bodyHeight });
    await page.waitForTimeout(300);
    await page.screenshot({
      path: path.resolve(outputPath),
      type: "png",
      clip: { x: 0, y: 0, width, height: bodyHeight },
    });
  } else {
    await page.screenshot({
      path: path.resolve(outputPath),
      type: "png",
      clip: { x: 0, y: 0, width, height },
    });
  }

  await browser.close();
  console.log("OK: " + path.resolve(outputPath));
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
