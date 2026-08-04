const CACHE_NAME = "ibw-admin-static-v4";

const STATIC_FILES = [
  "/static/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_FILES);
    })
  );

  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((cacheName) => cacheName !== CACHE_NAME)
          .map((cacheName) => caches.delete(cacheName))
      );
    })
  );

  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== "GET") {
    return;
  }

  if (url.origin !== self.location.origin) {
    return;
  }

  /*
    Login, dashboard, applications, documents, receipts
    aur private admin data kabhi cache nahi hoga.
  */
  const privatePaths = [
    "/login",
    "/logout",
    "/admin",
    "/dashboard",
    "/applications",
    "/application",
    "/documents",
    "/document",
    "/uploads",
    "/files",
    "/media"
  ];

  const isPrivatePath = privatePaths.some((path) =>
    url.pathname.startsWith(path)
  );

  if (isPrivatePath) {
    event.respondWith(
      fetch(request, {
        cache: "no-store",
        credentials: "include"
      })
    );
    return;
  }

  /*
    Sirf static PWA files cache hongi.
  */
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(request).then((cachedResponse) => {
        const networkFetch = fetch(request).then((networkResponse) => {
          if (
            networkResponse &&
            networkResponse.status === 200 &&
            networkResponse.type === "basic"
          ) {
            const responseCopy = networkResponse.clone();

            caches.open(CACHE_NAME).then((cache) => {
              cache.put(request, responseCopy);
            });
          }

          return networkResponse;
        });

        return cachedResponse || networkFetch;
      })
    );
    return;
  }

  /*
    Baaki pages hamesha network se load honge,
    taaki purani blank screen ya stale login page na aaye.
  */
  event.respondWith(
    fetch(request, {
      cache: "no-store",
      credentials: "include"
    })
  );
});
