// Service worker de Game Manager : rend l'application installable (Chrome, Edge) et garde l'interface en cache.
// Les données (/api/…) ne sont jamais mises en cache : elles viennent toujours du serveur et de la console.
const CACHE = "agm-shell-v1";
const STATIC = /^\/(assets|consoles)\/|\.(png|svg|webp|woff2)$/;

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;

  if (request.mode === "navigate") {
    // Page : toujours la version du serveur ; hors ligne, la dernière connue.
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) caches.open(CACHE).then((c) => c.put("/", response.clone()));
          return response;
        })
        .catch(() => caches.match("/")),
    );
    return;
  }
  if (STATIC.test(url.pathname)) {
    // Fichiers versionnés (/assets/…-hash.js) et images : le cache d'abord.
    event.respondWith(
      caches.match(request).then((hit) => hit || fetch(request).then((response) => {
        if (response.ok) caches.open(CACHE).then((c) => c.put(request, response.clone()));
        return response;
      })),
    );
  }
});
