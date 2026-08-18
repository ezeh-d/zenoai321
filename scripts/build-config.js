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

const rawApi = (process.env.ZENO_PUBLIC_API_URL || "").replace(/\/$/, "");
if (rawApi && !/^https:\/\//i.test(rawApi) &&
    !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(rawApi)) {
  console.error("Refusing to build: ZENO_PUBLIC_API_URL must use HTTPS outside localhost.");
  process.exit(1);
}

const config = {
  apiBaseUrl: rawApi,
  builtAt: new Date().toISOString(),
};

const root = path.join(__dirname, "..");
const web = path.join(root, "web");
const app = path.join(web, "app");
fs.mkdirSync(app, {recursive: true});

// Local FastAPI and Netlify serve the same audited owner UI.  Copying at
// build time prevents two mobile ZENO implementations drifting apart.
fs.copyFileSync(path.join(root, "reyes_agent", "static", "app.html"),
                path.join(app, "index.html"));
for (const name of ["manifest.webmanifest", "sw.js", "icon-192.png", "icon-512.png"]) {
  fs.copyFileSync(path.join(root, "reyes_agent", "static", "app", name),
                  path.join(app, name));
}

const out = path.join(web, "zeno-config.js");
fs.writeFileSync(out, "window.ZENO_CONFIG = " + JSON.stringify(config, null, 2) + ";\n");
let connect = "'self'";
if (rawApi) connect += " " + new URL(rawApi).origin;
const headers = `/*
  X-Frame-Options: DENY
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()
  Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src ${connect}; frame-ancestors 'none'; base-uri 'self'; form-action 'none'

/app/*
  Cache-Control: no-cache
  Permissions-Policy: camera=(), microphone=(self), geolocation=(), payment=(), usb=()

/zeno-config.js
  Cache-Control: no-store
`;
fs.writeFileSync(path.join(web, "_headers"), headers);
console.log("wrote", out, "->", config.apiBaseUrl || "(no API URL; page will show OFFLINE)");
