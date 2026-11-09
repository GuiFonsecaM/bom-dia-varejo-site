// Service worker do Bom dia varejo: permite instalar o app e abrir as últimas notícias mesmo sem internet.
const VERSAO = 'bdv-v7';
const BASICOS = ['./', './index.html', './manifest.webmanifest', './icons/icon-192.png', './icons/icon-512.png', './icons/logo-128.png', './icons/favicon-32.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(VERSAO).then(c => c.addAll(BASICOS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(chaves => Promise.all(chaves.filter(k => k !== VERSAO).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // Notícias e a própria página: sempre tenta a rede primeiro (conteúdo novo), usa a cópia se estiver offline
  const ehDado = url.origin === location.origin && (url.pathname.includes('/data/') || req.mode === 'navigate');
  // Fontes do Google e arquivos fixos: usa a cópia e atualiza em segundo plano
  const ehFixo = url.origin === location.origin || url.hostname.endsWith('fonts.googleapis.com') || url.hostname.endsWith('fonts.gstatic.com');
  if (url.pathname.includes('/img/')) return;   // fotos ficam só no cache normal do navegador
  if (!ehDado && !ehFixo) return;

  if (ehDado) {
    e.respondWith(
      fetch(req).then(resp => {
        if (resp.ok) { const copia = resp.clone(); caches.open(VERSAO).then(c => c.put(req, copia)); }
        return resp;
      }).catch(() => caches.match(req, { ignoreSearch: true }).then(r => r || caches.match('./')))
    );
    return;
  }

  e.respondWith(
    caches.match(req).then(cache => {
      const rede = fetch(req).then(resp => {
        if (resp.ok || resp.type === 'opaque') { const copia = resp.clone(); caches.open(VERSAO).then(c => c.put(req, copia)); }
        return resp;
      }).catch(() => cache);
      return cache || rede;
    })
  );
});
