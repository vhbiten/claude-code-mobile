'use strict';
// Service worker do painel: só cuida das notificações (Web Push). Não intercepta nenhum
// pedido, então a página continua sempre buscando tudo direto do PC.

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (ev) => ev.waitUntil(self.clients.claim()));

self.addEventListener('push', (ev) => {
  let d = {};
  try { d = ev.data ? ev.data.json() : {}; } catch { d = { texto: ev.data ? ev.data.text() : '' }; }
  const tarefas = [self.registration.showNotification(d.titulo || 'Claude', {
    body: d.texto || '', tag: d.tag || 'painel', renotify: true,
    icon: '/icone-180.png', badge: '/icone-180.png', data: { url: d.url || '/' },
  })];
  // bolinha no ícone da Tela de Início até abrir o painel
  if (self.navigator.setAppBadge) tarefas.push(self.navigator.setAppBadge(1).catch(() => {}));
  ev.waitUntil(Promise.all(tarefas));
});

self.addEventListener('notificationclick', (ev) => {
  ev.notification.close();
  const url = (ev.notification.data && ev.notification.data.url) || '/';
  ev.waitUntil((async () => {
    const janelas = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const aberta = janelas.find((c) => new URL(c.url).origin === self.location.origin);
    if (aberta && url.startsWith('/')) return aberta.focus();
    return self.clients.openWindow(url);
  })());
});
