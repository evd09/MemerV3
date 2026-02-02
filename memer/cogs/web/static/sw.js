const CACHE_NAME = 'memeboard-v3-cache-v1';
const ASSETS_TO_CACHE = [
    '/',
    '/manifest.json'
];

self.addEventListener('install', (event) => {
    self.skipWaiting();
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            // return cache.addAll(ASSETS_TO_CACHE); // Optional: Precache core assets
        })
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
    // Simple pass-through for now, or offline fallback if needed.
    // For a dynamic app, we usually want network first.
    if (event.request.method !== 'GET') return;

    event.respondWith(
        fetch(event.request)
            .catch(() => {
                return caches.match(event.request);
            })
    );
});
