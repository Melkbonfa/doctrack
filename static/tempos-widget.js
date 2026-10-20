/* ═══════════════════════════════════════════════════════════════════════════
   tempos-widget.js — cronômetro global do DocTrack.

   Carregado em TODOS os módulos (base.html + entregaveis.html), para que marcar
   tempo custe um clique de onde a pessoa já está. Um timer a três cliques de
   distância ninguém usa, e dado que ninguém registra não vale nada — é esta a
   razão de o widget existir em vez de o cronômetro morar só na página /tempos/.

   IIFE de propósito, com UM único global (window.DT_TEMPO). Na página /tempos/
   este arquivo carrega junto de tempos.js, e dois `const` de topo com o mesmo
   nome são SyntaxError que mata os dois scripts e deixa o #app escondido — o
   mesmo modo de falha do commit f7b65e7, com outra causa e igualmente invisível
   no DOM. Nada aqui vaza para o escopo global.

   Depende de common.js (getToken, esc) e, quando existir, de auth.js (DT_AUTH).
   ═══════════════════════════════════════════════════════════════════════════ */
(function(){
  "use strict";

  // Sem common.js não há como autenticar: alguma página fora do padrão.
  if(typeof getToken !== "function") return;
  // Sem sessão o DOM não é criado. Esta guarda é o que faz o widget conviver com
  // a rota de página pública (o #login-screen do dashboard.html fica FORA do
  // #app, no mesmo plano fixo que este widget) — sem ela, o cronômetro
  // apareceria flutuando sobre a tela de login.
  if(!getToken()) return;
  // `leitura` recebe 403 e não adianta perguntar de novo a cada página.
  if(sessionStorage.getItem("dt_tempo_sem_acesso") === "1") return;
  // Nem a primeira vez: todo 403 de perfil vira ACESSO_NEGADO na trilha, e
  // este seria o mais comum de todos, provocado pela própria tela em cada aba
  // aberta pelo perfil leitura. O 403 abaixo continua como rede de segurança.
  try{
    if((JSON.parse(localStorage.getItem("doctrack_user") || "{}") || {}).role === "leitura") return;
  }catch(e){}

  var PING = "dt_tempo_ping";
  var estado = {em_curso: null, retomavel: null};
  var offsetMs = 0;      // relógio do navegador - relógio do servidor
  var caixa = null, tick = null, silenciado = false;

  /* ── fetch ───────────────────────────────────────────────────────────────
     Divergência DELIBERADA de custos.js: lá, refresh falho chama
     DT_AUTH.gotoLogin(), o que é correto para uma página cujo conteúdo inteiro é
     aquela API. Num widget isso ejetaria a pessoa de Equipamentos porque uma
     requisição do MARCADOR DE TEMPO falhou. Aqui tenta o refresh uma vez e, se
     não der, o widget se cala. Não "alinhar com custos.js". */
  function req(url, metodo, corpo){
    var h = {"Content-Type": "application/json", "Authorization": "Bearer " + getToken()};
    var opt = {method: metodo || "GET", headers: h};
    if(corpo) opt.body = JSON.stringify(corpo);

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
      if(res.status === 403){          // perfil sem acesso ao módulo
        sessionStorage.setItem("dt_tempo_sem_acesso", "1");
        silenciar();
        return null;
      }
      return res.json().catch(function(){ return {}; }).then(function(corpo){
        if(!res.ok){
          var e = new Error(corpo.erro || "Falha (HTTP " + res.status + ")");
          e.corpo = corpo; e.status = res.status;
          throw e;
        }
        return corpo;
      });
    });
  }

  function silenciar(){
    silenciado = true;
    if(tick){ clearInterval(tick); tick = null; }
    if(caixa && caixa.parentNode){ caixa.parentNode.removeChild(caixa); caixa = null; }
  }

  /* ── relógio ancorado no servidor ─────────────────────────────────────────
     O dado já estaria certo sem isto (o servidor carimba início e fim), mas o
     usuário veria "-3h 12m" num navegador adiantado e abriria um chamado. */
  function agora(){ return new Date(Date.now() - offsetMs); }

  function decorrido(iso){
    var s = Math.max(0, Math.floor((agora() - new Date(iso)) / 1000));
    return Math.floor(s / 3600) + ":" +
           String(Math.floor((s % 3600) / 60)).padStart(2, "0") + ":" +
           String(s % 60).padStart(2, "0");
  }

  /* ── DOM ──────────────────────────────────────────────────────────────── */
  function garantirCaixa(){
    if(caixa) return caixa;
    caixa = document.createElement("div");
    caixa.id = "dt-tempo";
    caixa.setAttribute("aria-live", "polite");
    document.body.appendChild(caixa);
    caixa.addEventListener("click", aoClicar);
    return caixa;
  }

  function render(){
    if(silenciado) return;
    // Na própria página de Tempos o cronômetro já é desenhado em tamanho grande
    // por tempos.js; dois relógios na tela seriam dois estados aparentes.
    if(sessionStorage.getItem("dt_module") === "tempos"){
      if(caixa){ caixa.innerHTML = ""; caixa.classList.remove("visivel"); }
      return;
    }

    var c = garantirCaixa();
    if(estado.em_curso){
      var a = estado.em_curso;
      c.className = "visivel rodando";
      c.innerHTML =
        '<span class="dt-t-ponto"></span>' +
        '<span class="dt-t-rel" id="dt-t-rel">' + decorrido(a.inicio_iso) + '</span>' +
        '<span class="dt-t-alvo" title="' + esc(a.rotulo) + '">' + esc(a.rotulo) + '</span>' +
        '<button class="dt-t-btn" data-acao="pausar" title="Pausar">❙❙</button>' +
        '<button class="dt-t-btn parar" data-acao="parar" title="Parar">■</button>';
    } else if(estado.retomavel){
      var r = estado.retomavel;
      c.className = "visivel pausado";
      c.innerHTML =
        '<span class="dt-t-ponto"></span>' +
        '<span class="dt-t-rel">' + esc(r.duracao) + '</span>' +
        '<span class="dt-t-alvo" title="' + esc(r.rotulo) + '">' + esc(r.rotulo) + '</span>' +
        '<button class="dt-t-btn" data-acao="retomar" data-id="' + r.id + '" title="Retomar">▶</button>';
    } else {
      c.className = "visivel parado";
      c.innerHTML =
        '<a class="dt-t-link" href="/tempos/" title="Apontar tempo">' +
          '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">' +
            '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2" stroke-linecap="round"/></svg>' +
          '<span>Apontar tempo</span>' +
        '</a>';
    }
    ajustarTique();
  }

  function ajustarTique(){
    if(tick){ clearInterval(tick); tick = null; }
    if(!estado.em_curso) return;
    tick = setInterval(function(){
      var alvo = document.getElementById("dt-t-rel");
      if(alvo) alvo.textContent = decorrido(estado.em_curso.inicio_iso);
    }, 1000);
  }

  /* ── estado ───────────────────────────────────────────────────────────── */
  function aplicar(d){
    if(!d) return;
    estado.em_curso = d.em_curso || null;
    estado.retomavel = d.retomavel || null;
    if(d.servidor_agora) offsetMs = Date.now() - new Date(d.servidor_agora).getTime();
    render();
    window.dispatchEvent(new CustomEvent("dt-tempo-mudou", {detail: estado}));
  }

  function recarregar(){
    if(silenciado) return Promise.resolve(estado);
    return req("/tempos/api/atual").then(function(d){ aplicar(d); return estado; })
      .catch(function(){ return estado; });   // rede caiu: o widget não é a página
  }

  // Sincronia entre abas SEM socket.io: custo zero no servidor e funciona até no
  // config.html, que não carrega socket.io. Emitir cada start/stop pelo
  // event_bus geraria ~60 mil linhas de audit_logs por ano só de ruído de UI.
  function avisarAbas(){
    try{ localStorage.setItem(PING, String(Date.now())); }catch(e){}
  }

  function comandar(promessa){
    return promessa.then(function(d){
      return recarregar().then(function(){ avisarAbas(); return d; });
    });
  }

  /* ── ações ────────────────────────────────────────────────────────────── */
  function iniciar(alvo){
    alvo = alvo || {};
    return comandar(req("/tempos/api/iniciar", "POST", {
      ref_tipo: alvo.ref_tipo || "livre",
      ref_id: alvo.ref_id || null,
      titulo: alvo.titulo || "",
      projeto_id: alvo.projeto_id || null
    }));
  }
  function pausar(){ return comandar(req("/tempos/api/atual/pausar", "POST")); }
  function parar(){ return comandar(req("/tempos/api/atual/parar", "POST")); }
  function retomar(id){ return comandar(req("/tempos/api/" + id + "/retomar", "POST")); }

  function aoClicar(ev){
    var b = ev.target.closest("[data-acao]");
    if(!b) return;
    ev.preventDefault();
    b.disabled = true;                       // trava o clique duplo aqui também
    var acao = b.dataset.acao;
    var p = acao === "pausar" ? pausar()
          : acao === "parar" ? parar()
          : acao === "retomar" ? retomar(Number(b.dataset.id))
          : Promise.resolve();
    p.catch(function(e){ if(window.console) console.warn("[tempos]", e.message); })
     .then(function(){ b.disabled = false; });
  }

  /* ── ciclo de vida ────────────────────────────────────────────────────── */

  // Outra aba mexeu no cronômetro.
  window.addEventListener("storage", function(ev){
    if(ev.key === PING) recarregar();
  });

  // O notebook pode ter dormido: reancorar o relógio em vez de confiar no tique
  // acumulado. Só re-busca quando ficou escondido tempo suficiente para importar.
  var escondidoEm = 0;
  document.addEventListener("visibilitychange", function(){
    if(document.hidden){ escondidoEm = Date.now(); return; }
    if(Date.now() - escondidoEm > 60000) recarregar();
    else render();
  });

  window.DT_TEMPO = {
    estado: function(){ return estado; },
    estaRodando: function(){ return !!estado.em_curso; },
    recarregar: recarregar,
    iniciar: iniciar, pausar: pausar, parar: parar, retomar: retomar
  };

  // Adiado para depois do primeiro paint do módulo hospedeiro: o widget é
  // acessório e não pode competir com a carga da página que a pessoa abriu.
  function comecar(){ setTimeout(recarregar, 0); }
  if(document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", comecar);
  else comecar();
})();
