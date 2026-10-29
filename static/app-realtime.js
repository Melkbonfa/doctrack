/* ═══════════════════════════════════════════════════════════════════════════
   app-realtime.js — tempo real da tela de Documentos.

   Até aqui este arquivo era um modelo de integração que nunca foi ligado: lia o
   token de uma chave antiga ("jwt"), chamava funções que o app.js não tem e
   redefinia showToast por cima do app.js. Quem estava com Documentos aberto não
   via a mudança feita por outra pessoa sem recarregar a página.

   Agora: um DocTrackSocket (socket-client.js) assinando as salas de setor — é
   por elas que o técnico recebe DOCUMENT_*; gestor e admin já recebem pela sala
   do perfil (event_bus._resolve_rooms) — e cada rajada de eventos vira UMA
   atualização da tela:

     DOCUMENT_UPDATED          traz o documento → vai direto para o cache
     DOCUMENT_STATUS_UPDATED   só traz o id → busca aquele documento
     criar, excluir, responsáveis → recarrega a lista

   A ficha do equipamento aberta NÃO é redesenhada por baixo de quem está
   digitando: quando outra pessoa mexe num documento dela, aparece um aviso com o
   botão "Atualizar a ficha". O painel do fluxo de revisão se atualiza sozinho
   (fluxos-painel.js escuta os eventos FLUXO_*).

   Começa quando o app.js termina de montar a tela (evento `dt:docs-prontos`).
   IIFE com UM global (window.DT_DOCS_RT), pelo motivo de tempos-widget.js.
   Depende de common.js (getToken), socket-client.js e das funções do app.js
   (apiFetch, loadData, _aplicarDocLocal, renderDashboard, renderDocs, loadFluxo,
   openEquipModal, _equipCtx).
   ═══════════════════════════════════════════════════════════════════════════ */
(function(){
  "use strict";

  // Documentos de processo (setor PDE) também mudam pela tela; as três salas
  // cobrem tudo o que esta tela mostra.
  var SALAS = ["setor:PRE", "setor:Manuais", "setor:PDE"];
  var ESPERA_MS = 600;

  var dt = null, timer = null;
  var lote = loteVazio();

  /* `alheios` guarda POR DOCUMENTO quem mudou por outra pessoa: um lote pode
     juntar a minha mudança num documento da ficha com a de outra pessoa em outro
     equipamento, e isso não deve avisar a ficha. */
  function loteVazio(){
    return {docs: {}, buscar: {}, tudo: false, tudoAlheio: false, alheios: {}};
  }

  function meuEmail(){
    try{ return (JSON.parse(localStorage.getItem("doctrack_user") || "{}") || {}).email || ""; }
    catch(e){ return ""; }
  }

  function rotulo(texto){
    var l = document.getElementById("sync-label");
    if(l) l.textContent = texto;
  }

  function iniciar(){
    if(dt || typeof DocTrackSocket === "undefined" || typeof io === "undefined") return;
    if(typeof getToken !== "function" || !getToken()) return;
    try{
      dt = new DocTrackSocket({token: getToken()});
      dt.subscribe(SALAS);
      dt.on("__connect__", function(){ rotulo("Tempo real · conectado"); });
      dt.on("__disconnect__", function(){ rotulo("Tempo real · reconectando…"); });
      dt.on("__auth_error__", renovar);

      dt.on("DOCUMENT_UPDATED", function(e){
        var d = e && e.payload && e.payload.documento;
        if(d && d.id) anotar(e, {doc: d});
        else anotar(e, {tudo: true});
      });
      dt.on("DOCUMENT_STATUS_UPDATED", function(e){
        var id = e && e.payload && e.payload.documento_id;
        anotar(e, id ? {buscar: id} : {tudo: true});
      });
      ["DOCUMENT_CREATED", "DOCUMENT_DELETED", "RESPONSAVEL_ASSIGNED",
       "RESPONSAVEL_REMOVED", "RESPONSAVEL_CHANGED"].forEach(function(t){
        dt.on(t, function(e){ anotar(e, {tudo: true}); });
      });
      dt.connect();
    }catch(e){ dt = null; }        // tempo real é conveniência: a tela funciona sem ele
  }

  /* O access token vence em uma hora; o socket conectado segue vivo, mas uma
     reconexão com o token velho volta com auth_error. Renova e reconecta. */
  function renovar(){
    if(!window.DT_AUTH || !dt) return;
    window.DT_AUTH.refresh().then(function(ok){
      if(!ok || !dt || !dt.socket) return;
      dt.token = getToken();
      dt.socket.auth = {token: dt.token};
      dt.socket.connect();
    });
  }

  function anotar(e, o){
    var alheio = !e || (e.user_email || "") !== meuEmail();
    var id = o.doc ? o.doc.id : o.buscar;
    if(o.doc) lote.docs[o.doc.id] = o.doc;
    if(o.buscar) lote.buscar[o.buscar] = true;
    if(o.tudo){ lote.tudo = true; if(alheio) lote.tudoAlheio = true; }
    if(alheio && id) lote.alheios[id] = true;
    clearTimeout(timer);
    timer = setTimeout(aplicarLote, ESPERA_MS);
  }

  async function aplicarLote(){
    var l = lote;
    lote = loteVazio();
    var alheios = Object.keys(l.alheios).map(Number);
    try{
      if(l.tudo){
        await loadData();
      } else {
        Object.keys(l.docs).forEach(function(id){ _aplicarDocLocal(l.docs[id]); });
        for(var id of Object.keys(l.buscar)){
          if(l.docs[id]) continue;
          var res = await apiFetch("/documentos/" + id);
          if(res && res.ok) _aplicarDocLocal(await res.json());
        }
      }
      renderDashboard();
      renderDocs();
      if(typeof loadFluxo === "function") loadFluxo();
      if(alheios.length || l.tudoAlheio) avisarFicha(alheios, l.tudoAlheio);
    }catch(e){ /* o próximo evento tenta de novo; F5 continua valendo */ }
  }

  /* Ficha aberta e algum documento dela mudou por outra pessoa: avisa em vez de
     redesenhar — redesenhar descartaria o que a pessoa digitou e não salvou. */
  function avisarFicha(ids, tudo){
    var modal = document.getElementById("modal-equip");
    if(!modal || !modal.classList.contains("open") || typeof _equipCtx === "undefined" || !_equipCtx) return;
    var daFicha = (_equipCtx.docs || []).map(function(d){ return d.id; });
    if(!tudo && !ids.some(function(id){ return daFicha.indexOf(id) >= 0; })) return;
    var cab = document.getElementById("equip-header");
    if(!cab || document.getElementById("equip-rt-aviso")) return;
    var aviso = document.createElement("div");
    aviso.id = "equip-rt-aviso";
    aviso.className = "equip-rt-aviso";
    aviso.innerHTML = '<span>Esta ficha foi atualizada por outra pessoa.</span>' +
      '<button type="button" class="btn btn-ghost btn-sm">Atualizar a ficha</button>';
    aviso.querySelector("button").addEventListener("click", function(){
      var key = _equipCtx && _equipCtx.g && _equipCtx.g.key;
      var abaEl = document.querySelector("#equip-tabs .equip-modal-tab.active");
      aviso.remove();
      if(key) openEquipModal(key, {aba: abaEl ? abaEl.dataset.tab : null, manterAberto: true});
    });
    cab.insertAdjacentElement("afterend", aviso);
  }

  window.DT_DOCS_RT = {iniciar: iniciar};
  if(window.__docsProntos) iniciar();
  else window.addEventListener("dt:docs-prontos", iniciar);
})();
