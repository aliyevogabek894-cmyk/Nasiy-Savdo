// ZARVON Service Worker — Section 14 & 30.5 strict privacy rule:
// Cache ONLY non-sensitive static shell assets. NEVER cache /api/, personal data, passports, or contracts!
const CACHE_NAME = "zarvon-static-v3";
const STATIC_ASSETS = [
  "/static/css/design-system.css",
  "/static/js/app.js",
  "/static/icons/zarvon-icon.svg",
  "/static/icons/product-default.svg"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // Strict exclusion: NEVER cache API calls, private docs, or non-GET requests
  if (
    event.request.method !== "GET" ||
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/private/") ||
    url.pathname.startsWith("/django-admin/")
  ) {
    return;
  }
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(event.request).then((cached) => cached || fetch(event.request))
    );
  }
});
