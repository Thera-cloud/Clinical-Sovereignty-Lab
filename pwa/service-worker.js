/* ── Sovereign Sanctuary PWA Service Worker ── */

var CACHE_NAME = 'ss-v1';
var SHELL_FILES = [
  '/',
  '/index.html',
  '/css/app.css',
  '/js/app.js',
  '/js/auth.js',
  '/js/chat.js',
  '/js/storyboard.js',
  '/js/intake.js',
  '/js/vault.js',
  '/manifest.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png'
];

/* ── Install: cache shell ── */
self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      return cache.addAll(SHELL_FILES);
    }).then(function () { return self.skipWaiting(); })
  );
});

/* ── Activate: purge old caches ── */
self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (names) {
      return Promise.all(
        names.filter(function (n) { return n !== CACHE_NAME; })
             .map(function (n) { return caches.delete(n); })
      );
    }).then(function () { return self.clients.claim(); })
  );
});

/* ── Fetch strategy ── */
self.addEventListener('fetch', function (e) {
  var url = new URL(e.request.url);

  /* WebSocket — pass through */
  if (e.request.url.indexOf('/ws') !== -1) return;

  /* API calls — network only, no caching */
  if (url.pathname.indexOf('/api/') !== -1) {
    e.respondWith(fetch(e.request));
    return;
  }

  /* R2 images — cache first, then network */
  if (url.hostname.indexOf('r2.dev') !== -1 || url.pathname.indexOf('/sse/') !== -1) {
    e.respondWith(
      caches.open(CACHE_NAME).then(function (cache) {
        return cache.match(e.request).then(function (cached) {
          if (cached) return cached;
          return fetch(e.request).then(function (resp) {
            if (resp.ok) cache.put(e.request, resp.clone());
            return resp;
          });
        });
      })
    );
    return;
  }

  /* Shell — cache first, update in background */
  e.respondWith(
    caches.match(e.request).then(function (cached) {
      var fetchPromise = fetch(e.request).then(function (resp) {
        if (resp.ok) {
          caches.open(CACHE_NAME).then(function (cache) {
            cache.put(e.request, resp.clone());
          });
        }
        return resp;
      }).catch(function () { return cached; });

      return cached || fetchPromise;
    })
  );
});

/* ── Push notifications (future) ── */
self.addEventListener('push', function (e) {
  var data = {};
  try { data = e.data.json(); } catch (err) { data = { title: 'Little Nate', body: e.data.text() }; }
  e.waitUntil(
    self.registration.showNotification(data.title || 'Sovereign Sanctuary', {
      body: data.body || '',
      icon: '/icons/icon-192.png',
      badge: '/icons/icon-192.png',
      data: data
    })
  );
});

self.addEventListener('notificationclick', function (e) {
  e.notification.close();
  var url = (e.notification.data || {}).url || '/';
  e.waitUntil(clients.openWindow(url));
});
