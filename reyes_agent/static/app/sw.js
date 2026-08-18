/* ZENO service worker.
 *
 * OFFLINE SHELL ONLY -- deliberately.
 *
 * The shell (HTML, manifest, icons) is cached so the app opens instantly and
 * shows a real "you are offline" state instead of the browser's error page.
 *
 * NOTHING from /api/ is EVER cached. Caching an authenticated response would
 * mean a stale device status or, worse, another session reading a cached
 * answer out of the browser store. A wrong "laptop online" is worse than no
 * answer at all, so API requests always go to the network and fail honestly.
 */
const CACHE = "zeno-shell-v3";
const SHELL = ["/app/", "/app/manifest.webmanifest", "/app/icon-192.png",
               "/app/icon-512.png", "/zeno-config.js"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("message", e => {
  if (e.data === "SKIP_WAITING") self.skipWaiting();
});

/* Native Web Push is opt-in and privacy preserving. The gateway sends only
 * a short generic state transition; authenticated detail is fetched after
 * the owner opens the app. A push payload can never choose an external URL.
 */
self.addEventListener("push", e => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch { data = {}; }
  const title = String(data.title || "ZENO").slice(0, 80);
  const body = String(data.body || "ZENO has an update.").slice(0, 160);
  e.waitUntil(self.registration.showNotification(title, {
    body,
    icon: "/app/icon-192.png",
    badge: "/app/icon-192.png",
    tag: "zeno-" + String(data.kind || "update").slice(0, 32),
    renotify: false,
    data: {url: "/app/"},
  }));
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({type: "window", includeUncontrolled: true})
    .then(windows => {
      for (const client of windows) {
        if (new URL(client.url).origin === self.location.origin) return client.focus();
      }
      return self.clients.openWindow("/app/");
    }));
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  // Never cache the API, and never serve it from cache.
  if (url.pathname.startsWith("/api/") || e.request.method !== "GET") return;

  e.respondWith(
    fetch(e.request)
      .then(res => {
        if (res.ok && url.origin === location.origin){
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, copy));
        }
        return res;
      })
      .catch(() => caches.match(e.request).then(hit => hit || caches.match("/app")))
  );
});
