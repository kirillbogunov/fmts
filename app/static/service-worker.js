const CACHE = 'fmts-v060-enterprise-servicedesk';
const STATIC = ['/static/app.css','/static/icon-192.png','/static/icon-512.png','/static/manifest.webmanifest'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(STATIC)));
  self.skipWaiting();
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;
  // Do not cache business/API pages containing live or sensitive data.
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(caches.match(req).then(hit => hit || fetch(req).then(resp => {
      const copy = resp.clone(); caches.open(CACHE).then(c => c.put(req, copy)); return resp;
    })));
  }
});

self.addEventListener('push', event => {
  let data={title:'FMTS',body:'Новое уведомление',link:'/notifications'};
  try { if(event.data) data={...data,...event.data.json()}; } catch(e) {}
  event.waitUntil(self.registration.showNotification(data.title,{body:data.body,icon:'/static/icon-192.png',badge:'/static/icon-192.png',data:{link:data.link||'/notifications'}}));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const link=(event.notification.data&&event.notification.data.link)||'/notifications';
  event.waitUntil(clients.matchAll({type:'window',includeUncontrolled:true}).then(list=>{for(const c of list){if('focus' in c){c.navigate(link);return c.focus();}} if(clients.openWindow)return clients.openWindow(link);}));
});
