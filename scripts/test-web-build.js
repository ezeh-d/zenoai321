const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const required = [
  "web/index.html", "web/zeno-config.js", "web/_headers",
  "web/app/index.html", "web/app/manifest.webmanifest", "web/app/sw.js",
  "web/app/icon-192.png", "web/app/icon-512.png",
];
for (const name of required) {
  if (!fs.existsSync(path.join(root, name))) throw new Error("missing build output: " + name);
}
const config = fs.readFileSync(path.join(root, "web", "zeno-config.js"), "utf8");
if (/(_TOKEN|_SECRET|_KEY|PASSWORD)\s*[=:]/i.test(config)) {
  throw new Error("secret-shaped value found in public configuration");
}
const app = fs.readFileSync(path.join(root, "web", "app", "index.html"), "utf8");
if (!app.includes("/app/manifest.webmanifest") || !app.includes("/app/sw.js")) {
  throw new Error("PWA manifest or service worker wiring missing");
}
for (const contract of ["MediaRecorder", "echoCancellation:true", "noiseSuppression:true",
                        "/api/owner/voice", "EventSource", "/api/owner/events",
                        "pushManager.subscribe", "/api/owner/push/subscriptions"]) {
  if (!app.includes(contract)) throw new Error("missing Anywhere runtime contract: " + contract);
}
if (app.includes("Internet voice streaming is not implemented")) {
  throw new Error("stale disabled voice implementation remains in owner PWA");
}
const inline = app.match(/<script>\s*([\s\S]*?)<\/script>/);
if (!inline) throw new Error("owner app script missing");
new Function(inline[1]);
const manifest = JSON.parse(fs.readFileSync(
  path.join(root, "web", "app", "manifest.webmanifest"), "utf8"));
if (manifest.display !== "standalone" || !manifest.icons || manifest.icons.length < 2) {
  throw new Error("manifest is not installable");
}
const worker = fs.readFileSync(path.join(root, "web", "app", "sw.js"), "utf8");
if (!worker.includes('addEventListener("push"') ||
    !worker.includes('addEventListener("notificationclick"')) {
  throw new Error("service worker is missing native push handlers");
}
console.log("ZENO Anywhere web build checks passed");
