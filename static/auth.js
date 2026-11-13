/* ═══════════════════════════════════════════════════════════════════════════
   auth.js — Sessão compartilhada entre todos os módulos (fonte única).

   O access token vive 1h; o refresh token, 7 dias (config no servidor). Este
   helper renova o access token silenciosamente usando o refresh, para que o
   usuário não seja chutado ao login a cada hora. Só volta ao login quando o
   refresh também vence (>7 dias) ou é revogado — e aí de forma limpa, com aviso.

   Sessão parada é encerrada: sem mouse, teclado ou toque por `inatividade_min`
   minutos (vem de /api/version; 0 desliga), o helper revoga os tokens no
   servidor e volta ao login. A última atividade fica no localStorage, então
   vale para todas as abas juntas — e para a aba reaberta no dia seguinte.

   Deve ser carregado ANTES dos scripts de cada módulo. Exposto em window.DT_AUTH.
   ═══════════════════════════════════════════════════════════════════════════ */
(function(){
  "use strict";
  var ACCESS_KEY  = "doctrack_token";
  var REFRESH_KEY = "doctrack_refresh";
  var USER_KEY    = "doctrack_user";
  var EXPIRED_FLAG = "dt_session_expired";
  var IDLE_FLAG    = "dt_session_idle";
  var ATIVIDADE_KEY = "doctrack_atividade";   // epoch ms da última ação da pessoa
  var LIMITE_KEY    = "doctrack_inatividade_min";
  var _inflight = null;   // refresh em andamento (evita corrida com vários 401 juntos)

  function getAccess(){  return localStorage.getItem(ACCESS_KEY)  || ""; }
  function getRefresh(){ return localStorage.getItem(REFRESH_KEY) || ""; }

  function setTokens(access, refresh){
    marcarAtividade(true);
    if(access)  localStorage.setItem(ACCESS_KEY,  access);
    if(refresh) localStorage.setItem(REFRESH_KEY, refresh);
  }
  function setAccess(access){ if(access) localStorage.setItem(ACCESS_KEY, access); }

  function clear(){
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(USER_KEY);
  }

  // Lê o claim exp (epoch em segundos) de um JWT, sem validar assinatura. null se falhar.
  function expOf(tok){
    try{
      var part = tok.split(".")[1];
      part = part.replace(/-/g, "+").replace(/_/g, "/");
      var pad = part.length % 4; if(pad) part += "====".slice(pad);
      var payload = JSON.parse(decodeURIComponent(escape(atob(part))));
      return (typeof payload.exp === "number") ? payload.exp : null;
    }catch(e){ return null; }
  }

  // true se o token está ausente ou expira dentro de `skewSec` segundos (folga p/ latência).
  function isExpired(tok, skewSec){
    tok = tok || getAccess();
    if(!tok) return true;
    var exp = expOf(tok);
    if(exp == null) return false;              // sem exp legível: deixa o servidor julgar
    return (Date.now() / 1000) >= (exp - (skewSec == null ? 30 : skewSec));
  }

  // Renova o access token via /api/auth/refresh. Retorna Promise<bool>.
  // Chamadas concorrentes compartilham a MESMA requisição.
  function refresh(){
    if(_inflight) return _inflight;
    var rt = getRefresh();
    if(!rt) return Promise.resolve(false);
    _inflight = fetch("/api/auth/refresh", {
      method: "POST",
      headers: { "Authorization": "Bearer " + rt }
    }).then(function(res){
      if(!res.ok) return false;
      return res.json().then(function(d){
        if(d && d.access_token){ setAccess(d.access_token); return true; }
        return false;
      });
    }).catch(function(){ return false; })
      .then(function(ok){ _inflight = null; return ok; });
    return _inflight;
  }

  // Garante um access token válido antes de usar a página (chamado no boot).
  // Retorna Promise<bool>: true = sessão pronta; false = precisa logar.
  function ensureFresh(){
    if(!getAccess() && !getRefresh()) return Promise.resolve(false);
    if(!isExpired()) return Promise.resolve(true);
    return refresh();
  }

  // Volta ao login de forma limpa. Com expired=true, sinaliza o aviso na tela de login.
  function gotoLogin(expired){
    clear();
    if(expired){ try{ sessionStorage.setItem(EXPIRED_FLAG, "1"); }catch(e){} }
    if(location.pathname !== "/") window.location.href = "/";
    else window.location.reload();
  }

  // Consome (lê e apaga) a flag de sessão expirada — usado pela tela de login.
  function consumeExpiredFlag(){
    try{
      var v = sessionStorage.getItem(EXPIRED_FLAG);
      if(v){ sessionStorage.removeItem(EXPIRED_FLAG); return true; }
    }catch(e){}
    return false;
  }

  // ── Encerrar a sessão no servidor ──────────────────────────────────────────
  // Revoga o access E o refresh token, e grava a saída na trilha de auditoria.
  // Não navega: quem chama decide para onde ir. Retorna Promise (nunca rejeita).
  function encerrar(motivo){
    var at = getAccess();
    if(!at) return Promise.resolve();
    return fetch("/api/auth/logout", {
      method: "POST",
      headers: { "Authorization": "Bearer " + at, "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: getRefresh(), motivo: motivo || "" })
    }).catch(function(){});
  }

  // ── Inatividade ────────────────────────────────────────────────────────────
  var _ultimaGravacao = 0, _semSessao = true, _saindo = false;

  function limiteMs(){
    var min = parseInt(localStorage.getItem(LIMITE_KEY) || "30", 10);
    return (isNaN(min) || min <= 0) ? 0 : min * 60000;
  }
  // Grava no máximo a cada 5 s: mousemove dispara centenas de vezes por segundo.
  function marcarAtividade(forcar){
    var agora = Date.now();
    if(!forcar && agora - _ultimaGravacao < 5000) return;
    _ultimaGravacao = agora;
    try{ localStorage.setItem(ATIVIDADE_KEY, String(agora)); }catch(e){}
  }
  function conferirInatividade(){
    if(_saindo) return;
    if(!getAccess() && !getRefresh()){ _semSessao = true; return; }
    // Acabou de entrar nesta aba: a marca antiga é da sessão anterior.
    if(_semSessao){ _semSessao = false; marcarAtividade(true); return; }
    var limite = limiteMs();
    if(!limite) return;
    var ultima = parseInt(localStorage.getItem(ATIVIDADE_KEY) || "0", 10);
    if(!ultima){ marcarAtividade(true); return; }
    if(Date.now() - ultima < limite) return;
    _saindo = true;
    encerrar("inatividade").then(function(){
      clear();
      try{ sessionStorage.setItem(IDLE_FLAG, "1"); }catch(e){}
      if(location.pathname !== "/") window.location.href = "/";
      else window.location.reload();
    });
  }
  function consumeIdleFlag(){
    try{
      var v = sessionStorage.getItem(IDLE_FLAG);
      if(v){ sessionStorage.removeItem(IDLE_FLAG); return true; }
    }catch(e){}
    return false;
  }

  ["mousedown", "keydown", "touchstart", "wheel", "mousemove"].forEach(function(ev){
    window.addEventListener(ev, function(){ marcarAtividade(false); }, { passive: true, capture: true });
  });
  // Aba que já abre com sessão: confere na hora (é o caso da aba esquecida e
  // reaberta), sem passar pelo ramo de "acabou de entrar".
  if(getAccess() || getRefresh()){ _semSessao = false; conferirInatividade(); }
  setInterval(conferirInatividade, 20000);
  document.addEventListener("visibilitychange", function(){
    if(!document.hidden) conferirInatividade();
  });
  // O limite é configuração do servidor; guardado para valer já no próximo boot.
  fetch("/api/version").then(function(r){ return r.ok ? r.json() : null; }).then(function(d){
    if(d && typeof d.inatividade_min === "number"){
      try{ localStorage.setItem(LIMITE_KEY, String(d.inatividade_min)); }catch(e){}
    }
  }).catch(function(){});

  window.DT_AUTH = {
    encerrar: encerrar, consumeIdleFlag: consumeIdleFlag, marcarAtividade: marcarAtividade,
    getAccess: getAccess, getRefresh: getRefresh,
    setTokens: setTokens, setAccess: setAccess, clear: clear,
    expOf: expOf, isExpired: isExpired,
    refresh: refresh, ensureFresh: ensureFresh,
    gotoLogin: gotoLogin, consumeExpiredFlag: consumeExpiredFlag
  };
})();
