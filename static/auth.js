/* ═══════════════════════════════════════════════════════════════════════════
   auth.js — Sessão compartilhada entre todos os módulos (fonte única).

   O access token vive 1h; o refresh token, 7 dias (config no servidor). Este
   helper renova o access token silenciosamente usando o refresh, para que o
   usuário não seja chutado ao login a cada hora. Só volta ao login quando o
   refresh também vence (>7 dias) ou é revogado — e aí de forma limpa, com aviso.

   Deve ser carregado ANTES dos scripts de cada módulo. Exposto em window.DT_AUTH.
   ═══════════════════════════════════════════════════════════════════════════ */
(function(){
  "use strict";
  var ACCESS_KEY  = "doctrack_token";
  var REFRESH_KEY = "doctrack_refresh";
  var USER_KEY    = "doctrack_user";
  var EXPIRED_FLAG = "dt_session_expired";
  var _inflight = null;   // refresh em andamento (evita corrida com vários 401 juntos)

  function getAccess(){  return localStorage.getItem(ACCESS_KEY)  || ""; }
  function getRefresh(){ return localStorage.getItem(REFRESH_KEY) || ""; }

  function setTokens(access, refresh){
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

  window.DT_AUTH = {
    getAccess: getAccess, getRefresh: getRefresh,
    setTokens: setTokens, setAccess: setAccess, clear: clear,
    expOf: expOf, isExpired: isExpired,
    refresh: refresh, ensureFresh: ensureFresh,
    gotoLogin: gotoLogin, consumeExpiredFlag: consumeExpiredFlag
  };
})();
