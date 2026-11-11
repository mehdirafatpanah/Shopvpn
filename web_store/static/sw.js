const CACHE = "shopvpn-shell-v8";
const SHELL = ["/", "/assets/app.css", "/assets/app.js", "/assets/hero-scene.js", "/assets/hero-scene.css", "/assets/cinema.js", "/assets/cinema.css", "/assets/scene-extra.js", "/assets/i18n.js", "/assets/boot.js", "/assets/og-image.png"];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE && k.startsWith("shopvpn-shell-")).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", event => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  event.respondWith(fetch(req).then(res => {
    if (res.ok && (url.pathname.startsWith("/assets/") || url.pathname === "/" || url.pathname === "/en/")) {
      const copy = res.clone();
      caches.open(CACHE).then(cache => cache.put(req, copy));
    }
    return res;
  }).catch(() => caches.match(req).then(cached => cached || caches.match("/"))));
});
