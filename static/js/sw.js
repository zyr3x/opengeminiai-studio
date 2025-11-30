// Basic Service Worker to enable PWA installability
self.addEventListener('install', (event) => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(clients.claim());
});

self.addEventListener('fetch', (event) => {
    // Simple pass-through fetch strategy
    // This allows the app to work offline-capable in the future if needed,
    // but primarily satisfies the PWA requirement for a fetch handler.
    event.respondWith(fetch(event.request));
});
