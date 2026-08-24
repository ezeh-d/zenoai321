// Vendor the Pixi browser ESM bundle from node_modules into the static tree,
// so the (bundler-less) ZENO web surface can import it at /static/vendor/.
// Run after `npm install`. The overlay is OFF by default and crash-isolated,
// so ZENO runs fine even if this hasn't been run -- it just has no GPU overlay.
const fs = require("fs");
const path = require("path");
const src = path.join(__dirname, "..", "node_modules", "pixi.js", "dist", "pixi.min.mjs");
const destDir = path.join(__dirname, "..", "reyes_agent", "static", "vendor");
try {
  if (!fs.existsSync(src)) { console.error("pixi.js not installed; run npm install first."); process.exit(0); }
  fs.mkdirSync(destDir, { recursive: true });
  fs.copyFileSync(src, path.join(destDir, "pixi.min.mjs"));
  console.log("Vendored pixi.min.mjs ->", path.relative(process.cwd(), path.join(destDir, "pixi.min.mjs")));
} catch (e) { console.error("vendor-pixi failed:", e.message); process.exit(1); }
