// Emit the PUBLIC runtime config for the ZENO web surface.
//
// Everything written here ends up in browser JavaScript, so everything here
// is public. That is the whole reason this file exists: it makes the
// public/private split explicit instead of leaving it to whoever edits the
// HTML next.
//
// Reads ZENO_PUBLIC_API_URL from Netlify's environment at BUILD time. A
// server-side secret must never be referenced in this file.

const fs = require("fs");
const path = require("path");

const PUBLIC_KEYS = ["ZENO_PUBLIC_API_URL"];

const forbidden = Object.keys(process.env).filter(
  (k) => /(_TOKEN|_SECRET|_KEY|PASSWORD)$/i.test(k) && PUBLIC_KEYS.includes(k)
);
if (forbidden.length) {
  console.error("Refusing to build: secret-shaped name in the public list:", forbidden);
  process.exit(1);
}

const config = {
  apiBaseUrl: process.env.ZENO_PUBLIC_API_URL || "",
  builtAt: new Date().toISOString(),
};

const out = path.join(__dirname, "..", "web", "zeno-config.js");
fs.writeFileSync(out, "window.ZENO_CONFIG = " + JSON.stringify(config, null, 2) + ";\n");
console.log("wrote", out, "->", config.apiBaseUrl || "(no API URL; page will show OFFLINE)");
