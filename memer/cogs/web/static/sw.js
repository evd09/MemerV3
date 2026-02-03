const CACHE_VERSION = 'v3.2.2';
const STATIC_CACHE = `memeboard-static-${CACHE_VERSION}`;
const IMAGE_CACHE = `memeboard-images-${CACHE_VERSION}`;
const DYNAMIC_CACHE = `memeboard-dynamic-${CACHE_VERSION}`;

// Pre-cache critical static assets
const STATIC_ASSETS = [
    '/',
    '/static/js/app.js?v=3.2.2',
    '/manifest.json'
];

// Install: Pre-cache static assets
self.addEventListener('install', (event) => {
    console.log('[SW] Installing service worker v3.2.2');
    self.skipWaiting();
    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then(cache => {
                console.log('[SW] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .catch(err => console.error('[SW] Failed to cache static assets:', err))
    );
});

// Activate: Clean old caches
self.addEventListener('activate', (event) => {
    console.log('[SW] Activating service worker v3.2.2');
    event.waitUntil(
        caches.keys()
            .then(keys => {
                const oldCaches = keys.filter(key =>
                    key.startsWith('memeboard-') &&
                    !key.includes(CACHE_VERSION)
                );
                console.log('[SW] Deleting old caches:', oldCaches);
                return Promise.all(
                    oldCaches.map(key => caches.delete(key))
                );
            })
            .then(() => self.clients.claim())
    );
});

// Fetch: Strategic caching based on resource type
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // Skip non-GET requests
    if (request.method !== 'GET') return;

    // 1. THUMBNAILS: Cache First (aggressive caching for WebP thumbnails)
    if (url.pathname.includes('_thumb.webp')) {
        event.respondWith(cacheFirst(request, IMAGE_CACHE));
        return;
    }

    // 2. IMAGES: Cache First (all images)
    if (url.pathname.match(/\.(png|jpg|jpeg|gif|webp)$/)) {
        event.respondWith(cacheFirst(request, IMAGE_CACHE));
        return;
    }

    // 3. STATIC ASSETS: Cache First (JS, CSS, fonts)
    if (url.pathname.match(/\.(js|css|woff2?|ttf)$/)) {
        event.respondWith(cacheFirst(request, STATIC_CACHE));
        return;
    }

    // 4. API CALLS: Network First (dynamic data)
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(networkFirst(request, DYNAMIC_CACHE));
        return;
    }

    // 5. EVERYTHING ELSE (HTML, etc): Network First
    event.respondWith(networkFirst(request, DYNAMIC_CACHE));
});

// Cache First Strategy: Check cache first, fetch if not found
async function cacheFirst(request, cacheName) {
    try {
        const cached = await caches.match(request);
        if (cached) {
            console.log('[SW] Cache hit:', request.url);
            return cached;
        }

        console.log('[SW] Cache miss, fetching:', request.url);
        const response = await fetch(request);

        if (response.ok) {
            const cache = await caches.open(cacheName);
            cache.put(request, response.clone());
            console.log('[SW] Cached:', request.url);
        }

        return response;
    } catch (error) {
        console.error('[SW] Cache First failed:', error);
        return new Response('Offline - Resource not cached', {
            status: 503,
            statusText: 'Service Unavailable'
        });
    }
}

// Network First Strategy: Try network, fall back to cache
async function networkFirst(request, cacheName) {
    try {
        const response = await fetch(request);

        if (response.ok) {
            const cache = await caches.open(cacheName);
            cache.put(request, response.clone());
        }

        return response;
    } catch (error) {
        console.log('[SW] Network failed, trying cache:', request.url);
        const cached = await caches.match(request);

        if (cached) {
            console.log('[SW] Serving from cache:', request.url);
            return cached;
        }

        console.error('[SW] Network First failed, no cache:', error);
        return new Response('Offline - No cached version', {
            status: 503,
            statusText: 'Service Unavailable'
        });
    }
}
