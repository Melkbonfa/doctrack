/* ═══════════════════════════════════════════════════════════════════════════
   notificacoes-widget.js — o sino, presente em todas as telas.

   Carregado FORA de blocos Jinja em base.html, entregaveis.html, hub.html e
   subhub.html (mesma razão do cronômetro: os filhos sobrescrevem {% block
   scripts %} sem super()). O DOM é criado aqui e vive fora do #app.

   Duas listas no painel:
     Com você agora  fluxos cuja etapa atual é sua (/fluxos/api/comigo) — o estado
                     vivo, que não some só porque o aviso foi lido
     Avisos          a caixa de entrada (/api/notificacoes)

   Sem socket, de propósito: o aviso pessoal não passa pelo barramento (lido e
   não lido são estado da tabela — ver notificacoes/models.py). A contagem é
   consultada ao abrir a página, a cada 30 s, quando a aba volta ao foco e quando
   alguém dispara `dt:notificacoes-atualizar` (o painel do fluxo, depois de uma
   ação). Com aviso novo, o título da aba ganha "(n)" — é o que chama a atenção
   de quem está noutra aba, já que a rede interna em http não permite a
   Notification API do navegador.

   IIFE com UM global (window.DT_SINO), pelo motivo registrado em
   tempos-widget.js. Depende de common.js (getToken, esc) e de auth.js (DT_AUTH)
   quando existir.
   ═══════════════════════════════════════════════════════════════════════════ */
(function(){
  "use strict";

  if(typeof getToken !== "function") return;
  if(!getToken()) return;
  if(sessionStorage.getItem("dt_sino_sem_acesso") === "1") return;
  try{
    if((JSON.parse(localStorage.getItem("doctrack_user") || "{}") || {}).role === "leitura") return;
  }catch(e){}

  var INTERVALO_MS = 30000;
  var botao = null, painel = null, timer = null, silenciado = false;
  var naoLidas = 0, tituloBase = document.title;

  /* Divergência deliberada de custos.js no 401: um widget não pode ejetar a
     pessoa da página por causa de uma requisição dele (ver tempos-widget.js). */
  function req(url, metodo){
    var h = {"Authorization": "Bearer " + getToken()};
    var opt = {method: metodo || "GET", headers: h};
    return fetch(url, opt).then(function(res){
      if(res.status === 401 && window.DT_AUTH){
        return window.DT_AUTH.refresh().then(function(ok){
          if(!ok){ silenciar(); return null; }
          h["Authorization"] = "Bearer " + getToken();
          return fetch(url, opt);
        });
      }
      return res;
    }).then(function(res){
      if(!res) return null;
      if(res.status === 403){
        sessionStorage.setItem("dt_sino_sem_acesso", "1");
        silenciar();
        return null;
      }
      if(!res.ok) return null;
      return res.json().catch(function(){ return null; });
    }).catch(function(){ return null; });   // rede caiu: o sino não é a página
  }

  function silenciar(){
    silenciado = true;
    if(timer){ clearInterval(timer); timer = null; }
    [botao, painel].forEach(function(n){ if(n && n.parentNode) n.parentNode.removeChild(n); });
    botao = painel = null;
  }

  /* ── DOM ──────────────────────────────────────────────────────────────── */
  var ICONE =
    '<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/>' +
    '<path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg>';

  function montar(){
    botao = document.createElement("button");
    botao.type = "button";
    botao.id = "dt-sino";
    botao.setAttribute("aria-haspopup", "dialog");
    botao.setAttribute("aria-expanded", "false");
    botao.innerHTML = ICONE + '<span class="dt-sino-badge" hidden></span>';
    botao.addEventListener("click", function(ev){ ev.stopPropagation(); alternar(); });
    document.body.appendChild(botao);

    painel = document.createElement("div");
    painel.id = "dt-sino-painel";
    painel.setAttribute("role", "dialog");
    painel.setAttribute("aria-label", "Notificações");
    painel.hidden = true;
    painel.addEventListener("click", aoClicarPainel);
    document.body.appendChild(painel);

    document.addEventListener("click", function(ev){
      if(painel && !painel.hidden && !painel.contains(ev.target)) fechar();
    });
    document.addEventListener("keydown", function(ev){
      if(ev.key === "Escape" && painel && !painel.hidden){ fechar(); botao.focus(); }
    });
    rotular();
  }

  function rotular(){
    if(!botao) return;
    var b = botao.querySelector(".dt-sino-badge");
    b.hidden = !naoLidas;
    b.textContent = naoLidas > 99 ? "99+" : String(naoLidas);
    botao.classList.toggle("tem", naoLidas > 0);
    botao.title = naoLidas ? naoLidas + " aviso(s) não lido(s)" : "Notificações";
    botao.setAttribute("aria-label", botao.title);
    document.title = (naoLidas ? "(" + naoLidas + ") " : "") + tituloBase;
  }

  /* ── contagem ─────────────────────────────────────────────────────────── */
  function contar(){
    if(silenciado) return Promise.resolve();
    return req("/api/notificacoes/contagem").then(function(d){
      if(!d) return;
      var antes = naoLidas;
      naoLidas = d.nao_lidas || 0;
      rotular();
      if(naoLidas > antes && botao){
        botao.classList.remove("chegou");
        void botao.offsetWidth;             // reinicia a animação
        botao.classList.add("chegou");
      }
      if(painel && !painel.hidden && naoLidas !== antes) carregarPainel();
    });
  }

  /* ── painel ───────────────────────────────────────────────────────────── */
  function alternar(){ if(painel.hidden) abrir(); else fechar(); }

  function abrir(){
    painel.hidden = false;
    botao.setAttribute("aria-expanded", "true");
    painel.innerHTML = '<div class="dt-sino-vazio">Carregando…</div>';
    carregarPainel();
  }

  function fechar(){
    if(!painel) return;
    painel.hidden = true;
    botao.setAttribute("aria-expanded", "false");
  }

  function carregarPainel(){
    Promise.all([req("/fluxos/api/comigo"), req("/api/notificacoes?limite=30")])
      .then(function(r){ desenhar((r[0] || {}).fluxos || [], (r[1] || {}).notificacoes || []); });
  }

  function dias(n){
    return n === 0 ? "hoje" : n === 1 ? "há 1 dia" : "há " + n + " dias";
  }

  function desenhar(comigo, avisos){
    var h = '<div class="dt-sino-topo"><b>Notificações</b>' +
      (naoLidas ? '<button type="button" class="dt-sino-link" data-acao="todas">Marcar todas como lidas</button>' : '') +
      '</div>';

    h += '<div class="dt-sino-secao">Com você agora</div>';
    if(!comigo.length){
      h += '<div class="dt-sino-vazio">Nada esperando por você.</div>';
    } else {
      h += comigo.map(function(f){
        return '<a class="dt-sino-item vez" href="' + esc(f.link) + '">' +
          '<span class="dt-sino-tit">' + esc(f.etapa_nome) + ' · ' + esc(f.titulo) + '</span>' +
          '<span class="dt-sino-sub">' + esc(f.modelo_nome) +
            (f.rodada > 1 ? ' · rodada ' + f.rodada : '') + ' · ' + dias(f.dias_na_etapa) +
            (f.atrasado ? ' · <span class="dt-sino-atraso">prazo vencido</span>' : '') +
          '</span></a>';
      }).join("");
    }

    h += '<div class="dt-sino-secao">Avisos</div>';
    if(!avisos.length){
      h += '<div class="dt-sino-vazio">Nenhum aviso.</div>';
    } else {
      h += avisos.map(function(n){
        return '<a class="dt-sino-item ' + (n.lida ? 'lida' : 'nova') + ' ' + esc(n.tipo) +
          '" href="' + esc(n.link || "#") + '" data-id="' + n.id + '">' +
          '<span class="dt-sino-tit">' + esc(n.titulo) + '</span>' +
          (n.texto ? '<span class="dt-sino-sub">' + esc(n.texto) + '</span>' : '') +
          '<span class="dt-sino-quando">' + esc(n.criada_em) + '</span></a>';
      }).join("");
    }
    h += '<a class="dt-sino-rodape" href="/fluxos/">Ver todos os fluxos em andamento</a>';
    painel.innerHTML = h;
  }

  function aoClicarPainel(ev){
    ev.stopPropagation();
    var todas = ev.target.closest("[data-acao=todas]");
    if(todas){
      todas.disabled = true;
      req("/api/notificacoes/lidas", "POST").then(function(){ naoLidas = 0; rotular(); carregarPainel(); });
      return;
    }
    var item = ev.target.closest("a.dt-sino-item.nova");
    if(!item) return;
    // Marca como lida antes de sair da página; sem esperar a resposta a
    // navegação cortaria o POST no meio. keepalive cobre o pior caso.
    ev.preventDefault();
    var destino = item.getAttribute("href");
    fetch("/api/notificacoes/" + item.dataset.id + "/lida", {
      method: "POST", keepalive: true,
      headers: {"Authorization": "Bearer " + getToken()}
    }).catch(function(){}).then(function(){ irPara(destino); });
  }

  /* Mesma página com outro ?doc= não recarrega sozinha em todas as telas: força. */
  function irPara(destino){
    if(!destino || destino === "#"){ contar(); carregarPainel(); return; }
    var alvo = new URL(destino, location.href);
    if(alvo.pathname === location.pathname && alvo.search === location.search) location.reload();
    else location.href = alvo.href;
  }

  /* ── ciclo de vida ────────────────────────────────────────────────────── */
  window.addEventListener("dt:notificacoes-atualizar", function(){ contar(); });
  // Fluxo andou (evento repassado pelo socket da página, quando ela tem um):
  // reconta na hora em vez de esperar os 30 s, e redesenha o painel aberto.
  // O aviso em si continua vindo da API — o evento só diz que vale perguntar.
  var tFluxo = null;
  window.addEventListener("dt:evento", function(ev){
    var t = ((ev && ev.detail) || {}).event_type || "";
    if(!/^FLUXO_/.test(t)) return;
    clearTimeout(tFluxo);
    tFluxo = setTimeout(function(){
      contar().then(function(){ if(painel && !painel.hidden) carregarPainel(); });
    }, 800);
  });
  document.addEventListener("visibilitychange", function(){ if(!document.hidden) contar(); });

  window.DT_SINO = {atualizar: contar};

  function comecar(){
    // O título final da página pode ser escrito pelo boot do módulo.
    tituloBase = document.title.replace(/^\(\d+\+?\) /, "");
    montar();
    contar();
    timer = setInterval(function(){ if(!document.hidden) contar(); }, INTERVALO_MS);
  }
  if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", comecar);
  else setTimeout(comecar, 0);
})();
