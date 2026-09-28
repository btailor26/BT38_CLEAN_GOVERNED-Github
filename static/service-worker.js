const CACHE_NAME = 'bt38-scanner-v3';
const urlsToCache = [
  '/mobile/scan',
  '/static/manifest.json',
  '/static/css/mobile-scanner.css',
  '/static/js/mobile-scanner.js',
  '/static/js/mobile-sds-scanner-alignment.js',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
  );
  self.skipWaiting();
});

self.addEventListener('fetch', event => {
  const requestUrl = new URL(event.request.url);
  const isScannerCacheTarget =
    urlsToCache.includes(requestUrl.pathname) ||
    urlsToCache.includes(event.request.url);

  // Scanner offline support owns only its explicit asset allowlist.
  // Dynamic governed pages such as /fbm must always reach the server so the
  // deployed template and persisted DB truth remain the display authority.
  if (!isScannerCacheTarget) {
    return;
  }

  event.respondWith(
    caches.match(event.request)
      .then(response => {
        if (response) {
          return response;
        }
        return fetch(event.request).then(response => {
          if (!response || response.status !== 200) {
            return response;
          }
          const responseToCache = response.clone();
          caches.open(CACHE_NAME)
            .then(cache => {
              cache.put(event.request, responseToCache);
            });
          return response;
        });
      })
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.filter(cacheName => cacheName !== CACHE_NAME)
          .map(cacheName => caches.delete(cacheName))
      );
    })
  );
});
