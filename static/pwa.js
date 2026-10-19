/* ═══════════════════════════════════════════════════════════════════════════
   pwa.js — Registra o service worker e oferece a instalação na tela inicial.

   Carregado em todas as páginas do app (base.html e os quatro templates de
   <head> próprio). NÃO é carregado em travado.html: aquela página é a tela do
   kill switch e é deliberadamente autossuficiente, sem JS de aplicação.

   O convite de instalação só aparece em tela estreita. Num desktop o "app
   instalado" é uma janela sem barra de endereço — não resolve problema nenhum
   e o banner só atrapalha quem já está no navegador.
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  var CHAVE_DISPENSA = "dt_pwa_dispensado";   // epoch ms de quando foi dispensado
  var DIAS_SILENCIO = 30;                      // não insiste antes disso
  var LARGURA_MOBILE = 820;

  // ── SERVICE WORKER ─────────────────────────────────────────────────────────
  // A versão vai na query para casar com o cache versionado do worker (ver o
  // cabeçalho de sw.js). O <script> que nos carrega já traz o mesmo ?v= dos
  // outros estáticos, então lemos dali em vez de o servidor injetar de novo.
  function versaoDosEstaticos() {
    try {
      var meu = document.currentScript ||
                document.querySelector('script[src*="pwa.js"]');
      if (meu) {
        var v = new URL(meu.src, location.href).searchParams.get("v");
        if (v) return v;
      }
    } catch (e) { /* cai no padrão */ }
    return "dev";
  }
  var VERSAO = versaoDosEstaticos();

  if ("serviceWorker" in navigator) {
    // No load, e não na hora: registrar cedo disputa banda com o JS e o CSS de
    // que a primeira pintura depende — justo no 4G, que é o caso que isto veio
    // atender.
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js?v=" + encodeURIComponent(VERSAO), {
        scope: "/"
      }).catch(function () {
        // Sem worker o app funciona igual, só sem cache e sem página offline.
        // Também é o caminho normal em HTTP puro: o navegador exige contexto
        // seguro, então na LAN sem TLS o registro falha — e tudo bem.
      });
    });
  }

  // ── CONVITE DE INSTALAÇÃO ──────────────────────────────────────────────────
  var promptAdiado = null;

  function estaInstalado() {
    return window.matchMedia("(display-mode: standalone)").matches ||
           window.navigator.standalone === true;   // iOS
  }

  function silenciadoAinda() {
    try {
      var t = parseInt(localStorage.getItem(CHAVE_DISPENSA) || "0", 10);
      return t > 0 && (Date.now() - t) < DIAS_SILENCIO * 86400000;
    } catch (e) { return false; }
  }

  // Tirar o banner é sempre por aqui: a classe no <body> é o que faz o
  // cronômetro global subir para não ficar atrás dele (ver mobile.css), e
  // removê-la em um só lugar evita o pill ficar deslocado para sempre.
  function removerBanner(banner) {
    if (banner && banner.parentNode) banner.parentNode.removeChild(banner);
    document.body.classList.remove("pwa-banner-visivel");
  }

  function dispensar(banner) {
    try { localStorage.setItem(CHAVE_DISPENSA, String(Date.now())); } catch (e) {}
    removerBanner(banner);
  }

  function montarBanner(texto, rotuloAcao, aoAceitar) {
    var el = document.createElement("div");
    el.className = "pwa-banner";
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-label", "Instalar o DocTrack");

    var msg = document.createElement("p");
    msg.className = "pwa-banner-msg";
    msg.textContent = texto;

    var acoes = document.createElement("div");
    acoes.className = "pwa-banner-acoes";

    var agora = document.createElement("button");
    agora.type = "button";
    agora.className = "pwa-banner-btn pwa-banner-btn-ok";
    agora.textContent = rotuloAcao;

    var depois = document.createElement("button");
    depois.type = "button";
    depois.className = "pwa-banner-btn";
    depois.textContent = "Agora não";

    depois.addEventListener("click", function () { dispensar(el); });
    agora.addEventListener("click", function () { aoAceitar(el); });

    acoes.appendChild(depois);
    acoes.appendChild(agora);
    el.appendChild(msg);
    el.appendChild(acoes);
    document.body.appendChild(el);
    document.body.classList.add("pwa-banner-visivel");
    return el;
  }

  function podeConvidar() {
    return !estaInstalado() &&
           !silenciadoAinda() &&
           window.innerWidth <= LARGURA_MOBILE;
  }

  // Android/Chrome: o navegador avisa que a instalação é possível e nos entrega
  // o gatilho. Guardamos e chamamos no clique — chamar aqui seria ignorado.
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    promptAdiado = e;
    if (!podeConvidar()) return;
    montarBanner(
      "Instale o DocTrack na tela inicial para abrir direto, em tela cheia.",
      "Instalar",
      function (banner) {
        removerBanner(banner);
        promptAdiado.prompt();
        promptAdiado.userChoice.then(function (escolha) {
          // Recusou: silencia pelo mesmo período do "Agora não". Insistir a
          // cada carregamento de página é como se perde o usuário de vez.
          if (escolha && escolha.outcome !== "accepted") {
            try { localStorage.setItem(CHAVE_DISPENSA, String(Date.now())); } catch (e2) {}
          }
          promptAdiado = null;
        });
      }
    );
  });

  window.addEventListener("appinstalled", function () {
    try { localStorage.removeItem(CHAVE_DISPENSA); } catch (e) {}
    removerBanner(document.querySelector(".pwa-banner"));
  });

  // iOS/Safari: não existe beforeinstallprompt nem API de instalação — só o
  // caminho manual pelo menu Compartilhar. Sem esta dica o usuário de iPhone
  // simplesmente não descobre que dá para instalar.
  function ehIOSSafari() {
    var ua = navigator.userAgent;
    var ios = /iPad|iPhone|iPod/.test(ua) ||
              // iPadOS 13+ se apresenta como Mac; o toque é o que o denuncia.
              (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    // CriOS/FxiOS/EdgiOS são Chrome/Firefox/Edge no iOS, e nenhum deles instala.
    return ios && /Safari/.test(ua) && !/CriOS|FxiOS|EdgiOS/.test(ua);
  }

  window.addEventListener("load", function () {
    if (!ehIOSSafari() || !podeConvidar()) return;
    montarBanner(
      "Para instalar: toque em Compartilhar e depois em “Adicionar à Tela de Início”.",
      "Entendi",
      function (banner) { dispensar(banner); }
    );
  });
})();
