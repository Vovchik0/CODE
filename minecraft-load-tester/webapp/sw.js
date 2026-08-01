/*
 * sw.js -- сервис-воркер для установки веб-интерфейса как приложения (PWA).
 *
 * Стратегия:
 *   - запросы к API (/api/...) всегда идут по сети (данные должны быть свежими);
 *   - «оболочка» приложения (страница, иконка, манифест) отдаётся из кеша с
 *     обновлением по сети (stale-while-revalidate), что позволяет открыть
 *     интерфейс даже при временных проблемах с сетью.
 */
"use strict";

var CACHE = "mc-load-tester-v1";
var SHELL = ["./", "./index.html", "./icon.svg", "./manifest.webmanifest"];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) { return cache.addAll(SHELL); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        if (k !== CACHE) return caches.delete(k);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (event) {
  var url = new URL(event.request.url);

  // API -- только сеть, без кеширования.
  if (url.pathname.indexOf("/api/") === 0) {
    return; // пусть обрабатывает браузер по умолчанию (сеть)
  }

  // Оболочка -- отдать из кеша, параллельно обновляя его из сети.
  event.respondWith(
    caches.match(event.request).then(function (cached) {
      var network = fetch(event.request).then(function (resp) {
        if (resp && resp.status === 200 && event.request.method === "GET") {
          var copy = resp.clone();
          caches.open(CACHE).then(function (c) { c.put(event.request, copy); });
        }
        return resp;
      }).catch(function () { return cached; });
      return cached || network;
    })
  );
});
