// Rasterise the figures. Medium does not accept SVG uploads, so every figure
// ships as a PNG at 2x for the reader who zooms.
//
//   node docs/article/figures/render.mjs [scale]
//
// Needs @resvg/resvg-js, which is a build-time tool rather than a project
// dependency: install it wherever is convenient and point NODE_PATH here.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const scale = Number(process.argv[2] ?? 2);

// ESM ignores NODE_PATH, so allow an explicit location for the rasteriser.
const { Resvg } = await (async () => {
  try {
    return await import("@resvg/resvg-js");
  } catch (err) {
    const dir = process.env.RESVG_MODULES;
    if (!dir) throw err;
    return await import(pathToFileURL(path.join(dir, "@resvg/resvg-js/index.js")).href);
  }
})();

const files = fs
  .readdirSync(here)
  .filter((f) => f.endsWith(".svg"))
  .sort();

if (files.length === 0) {
  console.error("no .svg files - run the fig*.py generators first");
  process.exit(1);
}

for (const file of files) {
  const svg = fs.readFileSync(path.join(here, file), "utf8");
  const resvg = new Resvg(svg, {
    fitTo: { mode: "zoom", value: scale },
    font: {
      fontDirs: ["C:\\Windows\\Fonts", "/usr/share/fonts", "/Library/Fonts"],
      loadSystemFonts: true,
      defaultFontFamily: "Segoe UI",
    },
  });
  const png = resvg.render().asPng();
  const out = path.join(here, file.replace(/\.svg$/, ".png"));
  fs.writeFileSync(out, png);
  const { width, height } = resvg.render();
  console.log(`  ${file} -> ${path.basename(out)}  ${width}x${height}  ${(png.length / 1024).toFixed(0)} KB`);
}
