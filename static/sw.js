/* ═══════════════════════════════════════════════════════════════════════════
   sw.js — Service worker do DocTrack (PWA).

   SERVIDO EM /sw.js, nunca em /static/sw.js. O escopo de um service worker é o
   diretório de onde ele foi baixado: publicado sob /static/ ele só controlaria
   /static/*, e nenhuma página do app. A rota que o serve está em servidor.py.

   O que ele faz, e principalmente o que ele NÃO faz:

   * NÃO cacheia /api/*. Em nenhuma hipótese. Dado de negócio servido do cache é
     dado velho apresentado como atual — num sistema sob validação ANVISA
     (ver docs/referencias/) isso é defeito, não otimização. É também o que
     mantém a trava de emergência honesta: com o sistema travado toda API
     responde 423, e um cache no caminho esconderia exatamente o que a trava
     existe para fazer aparecer.

   * NÃO usa o cache como reserva para resposta de ERRO do servidor. Só para
     falha de REDE (fetch rejeitado). A diferença é o kill switch: 423 é uma
     resposta legítima, e ela tem que chegar na tela.

   * Cacheia /static/* de forma agressiva, porque essas URLs já carregam ?v=
     (ver _static_version() em servidor.py): quando o arquivo muda, a URL muda.
     É daqui que vem o ganho no 4G — o app pesa alguns MB de JS e CSS que, sem
     isto, desceriam de novo a cada abertura.

   Estratégia por tipo de requisição:
     navegação (HTML) → rede primeiro, página offline se a rede falhar
     /static/*        → cache primeiro, rede se não tiver
     resto (/api/*)   → rede, direto, sem passar por aqui
   ═══════════════════════════════════════════════════════════════════════════ */
"use strict";

// A versão vem da querystring com que a página registrou o worker (?v=<asset_v>).
// Cada deploy que muda um .js/.css muda o token, o que muda o nome do cache e
// o byte-a-byte deste arquivo — os dois gatilhos que o navegador usa para
// instalar um worker novo. Sem isto, um deploy poderia ficar invisível.
const VERSAO = new URL(self.location.href).searchParams.get("v") || "dev";
const CACHE_ESTATICO = "doctrack-estatico-" + VERSAO;
const CACHE_CASCA = "doctrack-casca-" + VERSAO;

// Única coisa pré-cacheada na instalação. É deliberadamente uma página só:
// pré-cachear o app inteiro obrigaria a manter aqui uma lista de arquivos que
// desatualiza silenciosamente. O resto entra no cache conforme for usado.
const PAGINA_OFFLINE = "/static/offline.html";

self.addEventListener("install", (evento) => {
  evento.waitUntil(
    caches.open(CACHE_CASCA)
      .then((c) => c.add(new Request(PAGINA_OFFLINE, { cache: "reload" })))
      // Falhar aqui derrubaria a instalação inteira e deixaria o app sem
      // worker nenhum. Sem página offline o app ainda funciona online.
      .catch(() => {})
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    caches.keys()
      .then((nomes) => Promise.all(
        nomes
          .filter((n) => n.startsWith("doctrack-") &&
                         n !== CACHE_ESTATICO && n !== CACHE_CASCA)
          .map((n) => caches.delete(n))
      ))
      .then(() => self.clients.claim())
  );
});

// Apaga o que estiver guardado. Chamado quando o servidor responde 423 (trava)
// e no logout: as duas situações em que deixar a casca do app no disco do
// aparelho não ajuda ninguém.
function limparTudo() {
  return caches.keys().then((nomes) => Promise.all(
    nomes.filter((n) => n.startsWith("doctrack-")).map((n) => caches.delete(n))
  ));
}

self.addEventListener("message", (evento) => {
  if (evento.data === "limpar-cache") evento.waitUntil(limparTudo());
});

function ehEstatico(url) {
  return url.origin === self.location.origin &&
         url.pathname.startsWith("/static/") &&
         // A própria página offline é da casca, não do cache de estáticos.
         url.pathname !== PAGINA_OFFLINE;
}

self.addEventListener("fetch", (evento) => {
  const req = evento.request;

  // Só GET. POST/PUT/DELETE mudam estado no servidor e não têm o que fazer aqui.
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Outra origem (nada hoje, mas se um dia houver) passa direto.
  if (url.origin !== self.location.origin) return;

  // API nunca passa pelo cache — nem para ler, nem para gravar. Ver o cabeçalho.
  if (url.pathname.startsWith("/api/")) return;

  // O próprio worker e o manifesto: sempre da rede, senão uma versão velha do
  // manifesto poderia fixar um start_url que não existe mais.
  if (url.pathname === "/sw.js" || url.pathname.endsWith(".webmanifest")) return;

  if (ehEstatico(url)) {
    // Cache primeiro: a URL já é versionada, então o que está no cache é, por
    // construção, a versão certa daquele arquivo.
    evento.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        // Só guarda resposta boa e completa. `res.ok` exclui 404/423/500, e o
        // status 206 (parcial) não pode ir para o cache — o navegador rejeita.
        if (res.ok && res.status === 200) {
          const copia = res.clone();
          caches.open(CACHE_ESTATICO).then((c) => c.put(req, copia)).catch(() => {});
        }
        return res;
      }))
    );
    return;
  }

  // Navegação (o usuário abrindo/recarregando uma página).
  if (req.mode === "navigate") {
    evento.respondWith(
      fetch(req)
        .then((res) => {
          // 423 = sistema travado. Limpa o que houver guardado e deixa a
          // resposta seguir intacta até a tela: é o kill switch funcionando.
          if (res.status === 423) {
            limparTudo().catch(() => {});
          }
          return res;
        })
        // Repare no `.catch`: só cai aqui quando o fetch REJEITA, isto é,
        // quando não houve rede. Resposta de erro do servidor não passa por
        // aqui — ela já voltou no `.then` acima e vai para a tela como veio.
        .catch(() => caches.match(PAGINA_OFFLINE)
          .then((hit) => hit || new Response(
            "<h1>DocTrack</h1><p>Sem conexão.</p>",
            { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } }
          )))
    );
  }
});
