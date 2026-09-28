// Service Worker for Cron System PWA
// Scope: /pwa/
const CACHE_NAME = 'cron-pwa-v1';

// Precache list as specified: ['./', './index.html', './manifest.webmanifest']
const PRECACHE_URLS = [
  './',
  './index.html',
  './manifest.webmanifest'
];

// Install Event: open cache and precache core shell assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

// Activate Event: clear old caches and claim clients immediately
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch Event
self.addEventListener('fetch', (event) => {
  // Only handle GET requests for caching
  if (event.request.method !== 'GET') {
    return;
  }

  const url = new URL(event.request.url);

  // Network-first strategy for /api/* and /admin/*
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/admin/') || url.pathname === '/api' || url.pathname === '/admin') {
    event.respondWith(
      fetch(event.request)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const responseClone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseClone));
          }
          return networkResponse;
        })
        .catch(async () => {
          // If offline, check if we have cached response
          const cachedResponse = await caches.match(event.request);
          if (cachedResponse) {
            return cachedResponse;
          }
          // Fallback response for offline API calls
          return new Response(JSON.stringify({ error: 'Network unavailable (offline)', offline: true }), {
            status: 503,
            statusText: 'Service Unavailable',
            headers: { 'Content-Type': 'application/json' }
          });
        })
    );
    return;
  }

  // Cache-first strategy for shell and assets with offline fallback to index.html
  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }

      // Not in cache: fetch from network
      return fetch(event.request)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const responseClone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseClone));
          }
          return networkResponse;
        })
        .catch(async () => {
          // Offline fallback for navigation / document requests to index.html
          if (event.request.mode === 'navigate' ||
              event.request.destination === 'document' ||
              (event.request.headers.get('accept') && event.request.headers.get('accept').includes('text/html'))) {
            const fallback = await caches.match('./index.html') ||
                             await caches.match('./') ||
                             await caches.match('/pwa/index.html') ||
                             await caches.match('/pwa/');
            if (fallback) {
              return fallback;
            }
          }

          // Last resort fallback
          return new Response('Offline - cron system shell unavailable', {
            status: 503,
            statusText: 'Service Unavailable',
            headers: { 'Content-Type': 'text/plain' }
          });
        });
    })
  );
});
