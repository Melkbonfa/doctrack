/* ═══════════════════════════════════════════════════════════════════════════
   fluxos.js — página /fluxos/: o que está em revisão e os modelos de fluxo.

   Em andamento  todos os fluxos que a pessoa enxerga, do mais parado para o
                 menos parado; a linha leva ao item (documento ou entregável).
   Modelos       (admin/gestor) papéis e etapas de cada tipo de trabalho.

   O servidor decide tudo (fluxos/routes.py, fluxos/core.py); aqui só se desenha.
   Depende de common.js (esc, getToken) e auth.js (DT_AUTH).
   ═══════════════════════════════════════════════════════════════════════════ */
"use strict";

sessionStorage.setItem("dt_module", "fluxos");

function userObj(){
  try{ return JSON.parse(localStorage.getItem("doctrack_user") || "{}") || {}; }
  catch(e){ return {}; }
}
const USER = userObj();
const ROLE = USER.role || "";
const PODE_USAR = ROLE === "admin" || ROLE === "gestor" || ROLE === "tecnico";
const E_GESTAO = ROLE === "admin" || ROLE === "gestor";

const el = id => document.getElementById(id);
let FLUXOS = [], MODELOS = [], PESSOAS = [], EDITANDO = null;

function toast(msg, erro){
  const t = el("toast");
  el("toast-msg").textContent = msg;
  el("toast-dot").style.background = erro ? "var(--red)" : "var(--green)";
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 3200);
}

async function api(url, opts){
  opts = opts || {};
  const h = Object.assign({"Content-Type": "application/json"}, opts.headers || {});
  h["Authorization"] = "Bearer " + getToken();
  let res = await fetch(url, Object.assign({}, opts, {headers: h}));
  if(res.status === 401 && window.DT_AUTH){
    const ok = await window.DT_AUTH.refresh();
    if(ok){
      h["Authorization"] = "Bearer " + getToken();
      res = await fetch(url, Object.assign({}, opts, {headers: h}));
    } else {
      window.DT_AUTH.gotoLogin();
      throw new Error("sessão expirada");
    }
  }
  const corpo = await res.json().catch(() => ({}));
  if(!res.ok){
    const e = new Error(corpo.erro || "Falha na requisição (HTTP " + res.status + ")");
    e.status = res.status;
    throw e;
  }
  return corpo;
}

/* ═══════════ NAVEGAÇÃO ═══════════ */
const TITULOS = {andamento: "Em andamento", modelos: "Modelos"};

function irPara(pag){
  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  el("page-" + pag).classList.add("active");
  document.querySelectorAll(".nav-item[data-page]").forEach(b =>
    b.classList.toggle("active", b.dataset.page === pag));
  el("breadcrumb-current").textContent = TITULOS[pag] || pag;
  if(pag === "modelos") carregarModelos();
}

/* ═══════════ EM ANDAMENTO ═══════════ */
function diasTxt(n){ return n === 0 ? "hoje" : n === 1 ? "1 dia" : n + " dias"; }
function dataBR(iso){ return iso ? iso.split("-").reverse().join("/") : "—"; }
function semAcento(s){ return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }

async function carregarAndamento(){
  try{
    FLUXOS = (await api("/fluxos/api/em-andamento")).fluxos || [];
    renderAndamento();
  }catch(e){ toast(e.message, true); }
}

function renderAndamento(){
  const q = semAcento(el("f-q").value.trim());
  const meus = el("f-meus").checked;
  const linhas = FLUXOS.filter(f => {
    if(meus && !(f.responsavel && f.responsavel.id === USER.id) && !(f.participantes_ids || []).includes(USER.id)) return false;
    if(!q) return true;
    return semAcento([f.titulo, f.modelo_nome, f.etapa_nome, f.responsavel && f.responsavel.nome].join(" ")).includes(q);
  });
  el("n-andamento").textContent = FLUXOS.length || "";
  el("f-total").textContent = linhas.length + " de " + FLUXOS.length;
  el("tb-andamento").innerHTML = linhas.length ? linhas.map(f => `
    <tr class="fx-linha" data-link="${esc(f.link)}" tabindex="0">
      <td><div class="fx-item">${esc(f.titulo)}</div>
          <div class="fx-item-tipo">${f.ref_tipo === "documento" ? "Documento" : "Entregável"}</div></td>
      <td>${esc(f.modelo_nome)}</td>
      <td>${esc(f.etapa_nome)}</td>
      <td>${f.responsavel ? esc(f.responsavel.nome) : "—"}${f.responsavel_inativo
            ? ' <span class="fx-tag atraso">sem responsável ativo</span>' : ""}</td>
      <td class="num ${f.dias_na_etapa >= 7 ? "fx-parado" : ""}">${diasTxt(f.dias_na_etapa)}</td>
      <td class="num">${f.rodada}</td>
      <td class="${f.atrasado ? "fx-atraso" : ""}">${dataBR(f.prazo)}</td>
    </tr>`).join("")
    : `<tr><td colspan="7" class="fx-vazio" style="padding:18px">${FLUXOS.length
        ? "Nada com esse filtro." : "Nenhum fluxo em andamento. Inicie um pela ficha de um documento ou pelo entregável de um projeto."}</td></tr>`;
}

/* ═══════════ MODELOS ═══════════ */
async function carregarModelos(){
  try{
    const [m, p] = await Promise.all([
      api("/fluxos/api/modelos" + (el("f-arquivados").checked ? "?todos=1" : "")),
      PESSOAS.length ? Promise.resolve({pessoas: PESSOAS}) : api("/fluxos/api/pessoas")]);
    MODELOS = m.modelos || [];
    PESSOAS = p.pessoas || [];
    renderModelos();
  }catch(e){ toast(e.message, true); }
}

function nomePessoa(id){
  const p = PESSOAS.find(x => x.id === id);
  return p ? p.nome : "";
}

function renderModelos(){
  el("fx-modelos").innerHTML = MODELOS.length ? MODELOS.map(m => {
    const papeis = {};
    m.papeis.forEach(p => papeis[p.chave] = p);
    return `<div class="card fx-modelo-card ${m.ativo ? "" : "arquivado"}">
      <div class="fx-modelo-topo">
        <div><div class="card-title" style="margin:0">${esc(m.nome)}${m.ativo ? "" : ' <span class="fx-tag">arquivado</span>'}</div>
          ${m.descricao ? `<div class="fx-sub">${esc(m.descricao)}</div>` : ""}</div>
        <div class="fx-botoes">
          <button class="btn btn-ghost btn-sm" data-modelo="editar" data-id="${m.id}">Editar</button>
          <button class="btn btn-ghost btn-sm" data-modelo="${m.ativo ? "arquivar" : "reativar"}" data-id="${m.id}">${m.ativo ? "Arquivar" : "Reativar"}</button>
        </div>
      </div>
      <ol class="fx-etapas">${m.etapas.map(e => `<li class="futura" style="opacity:1">
        <span class="fx-etapa-nome">${esc(e.nome)}${e.tipo === "revisao" ? ' <span class="fx-tag">revisão</span>' : ""}</span>
        <span class="fx-etapa-quem">${esc((papeis[e.papel] || {}).nome || e.papel)}${
          papeis[e.papel] && papeis[e.papel].padrao_user_id ? " · " + esc(nomePessoa(papeis[e.papel].padrao_user_id)) : ""}</span>
        ${e.tipo === "revisao" ? `<span class="fx-etapa-quem">devolve para ${esc((m.etapas.find(x => x.chave === e.devolve_para) || {}).nome || "")}</span>` : ""}
      </li>`).join("")}</ol>
      <div class="fx-sub">${m.n_fluxos || 0} fluxo(s) já usaram este modelo.</div>
    </div>`;
  }).join("") : '<div class="fx-vazio">Nenhum modelo cadastrado.</div>';
}

/* ── editor ── cada linha tem um _k interno; a chave do servidor sai dele na hora
   de salvar, e é por ele que a etapa aponta para o papel e para onde devolve. */
let _seqK = 0;
const novoK = () => "k" + (++_seqK);

function slug(t){
  return (t || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase()
    .replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);
}

function abrirEditor(m){
  const papeis = (m ? m.papeis : [{chave: "", nome: "Autor(a)"}, {chave: "", nome: "Revisor(a)"}])
    .map(p => ({_k: novoK(), chave: p.chave, nome: p.nome, padrao_user_id: p.padrao_user_id || null}));
  const porChave = {};
  papeis.forEach(p => { if(p.chave) porChave[p.chave] = p._k; });
  const etapas = (m ? m.etapas : [{nome: "Elaboração", tipo: "execucao"}, {nome: "Revisão", tipo: "revisao"}])
    .map((e, i) => ({_k: novoK(), chave: e.chave || "", nome: e.nome, tipo: e.tipo || "execucao",
                     papel: m ? porChave[e.papel] : papeis[Math.min(i, papeis.length - 1)]._k,
                     devolve_para: e.devolve_para || ""}));
  const etapaPorChave = {};
  etapas.forEach(e => { if(e.chave) etapaPorChave[e.chave] = e._k; });
  etapas.forEach(e => { e.devolve_para = etapaPorChave[e.devolve_para] || ""; });
  EDITANDO = {id: m ? m.id : null, nome: m ? m.nome : "", descricao: m ? m.descricao : "", papeis, etapas};
  el("modal-titulo").textContent = m ? "Editar modelo" : "Novo modelo de fluxo";
  el("modal-sub").textContent = m
    ? "Vale para os próximos fluxos. Os que já estão andando guardam a própria cópia."
    : "Papéis são quem faz; etapas são a ordem do trabalho. Uma revisão pode devolver para uma etapa anterior.";
  renderEditor();
  el("modal-overlay").classList.add("open");
  el("modal-salvar").onclick = salvarModelo;
}

function fecharModal(){ el("modal-overlay").classList.remove("open"); EDITANDO = null; }

function lerEditor(){
  if(!EDITANDO) return;
  const c = el("modal-corpo");
  EDITANDO.nome = c.querySelector("#ed-nome").value;
  EDITANDO.descricao = c.querySelector("#ed-desc").value;
  c.querySelectorAll("[data-papel-k]").forEach(row => {
    const p = EDITANDO.papeis.find(x => x._k === row.dataset.papelK);
    p.nome = row.querySelector(".ed-p-nome").value;
    const v = row.querySelector(".ed-p-padrao").value;
    p.padrao_user_id = v ? Number(v) : null;
  });
  c.querySelectorAll("[data-etapa-k]").forEach(row => {
    const e = EDITANDO.etapas.find(x => x._k === row.dataset.etapaK);
    e.nome = row.querySelector(".ed-e-nome").value;
    e.papel = row.querySelector(".ed-e-papel").value;
    e.tipo = row.querySelector(".ed-e-tipo").value;
    const dv = row.querySelector(".ed-e-devolve");
    e.devolve_para = dv ? dv.value : "";
  });
}

function renderEditor(){
  const E = EDITANDO;
  const optPessoas = sel => '<option value="">— ninguém fixo —</option>' + PESSOAS.map(p =>
    `<option value="${p.id}" ${p.id === sel ? "selected" : ""}>${esc(p.nome)}</option>`).join("");
  el("modal-corpo").innerHTML = `
    <div class="fx-ed">
      <label class="fx-campo"><span>Nome</span><input class="form-input" id="ed-nome" maxlength="80" value="${esc(E.nome)}"></label>
      <label class="fx-campo"><span>Descrição</span><input class="form-input" id="ed-desc" value="${esc(E.descricao)}"></label>

      <div class="fx-ed-sec">Papéis</div>
      ${E.papeis.map(p => `<div class="fx-ed-linha" data-papel-k="${p._k}">
        <input class="form-input ed-p-nome" placeholder="Ex.: Diagramador(a)" value="${esc(p.nome)}">
        <select class="form-input ed-p-padrao" title="Pessoa que já vem escolhida ao iniciar">${optPessoas(p.padrao_user_id)}</select>
        <button type="button" class="btn btn-ghost btn-sm" data-ed="rm-papel" data-k="${p._k}" title="Remover papel">✕</button>
      </div>`).join("")}
      <button type="button" class="btn btn-ghost btn-sm" data-ed="add-papel">+ Papel</button>

      <div class="fx-ed-sec">Etapas, na ordem</div>
      ${E.etapas.map((e, i) => `<div class="fx-ed-linha" data-etapa-k="${e._k}">
        <span class="fx-ed-num">${i + 1}</span>
        <input class="form-input ed-e-nome" placeholder="Ex.: Diagramação" value="${esc(e.nome)}">
        <select class="form-input ed-e-papel" title="Quem faz">${E.papeis.map(p =>
          `<option value="${p._k}" ${p._k === e.papel ? "selected" : ""}>${esc(p.nome || "(sem nome)")}</option>`).join("")}</select>
        <select class="form-input ed-e-tipo" title="Execução: envia para a próxima. Revisão: aprova ou devolve.">
          <option value="execucao" ${e.tipo === "execucao" ? "selected" : ""}>Execução</option>
          <option value="revisao" ${e.tipo === "revisao" ? "selected" : ""} ${i === 0 ? "disabled" : ""}>Revisão</option>
        </select>
        ${e.tipo === "revisao" ? `<select class="form-input ed-e-devolve" title="Para onde a revisão devolve">${
          E.etapas.slice(0, i).map((x, j) => `<option value="${x._k}" ${(e.devolve_para ? x._k === e.devolve_para : j === i - 1) ? "selected" : ""}>devolve p/ ${esc(x.nome || "(etapa " + (j + 1) + ")")}</option>`).join("")}</select>` : ""}
        <span class="fx-ed-mover">
          <button type="button" class="btn btn-ghost btn-sm" data-ed="sobe" data-k="${e._k}" ${i === 0 ? "disabled" : ""} title="Subir">↑</button>
          <button type="button" class="btn btn-ghost btn-sm" data-ed="desce" data-k="${e._k}" ${i === E.etapas.length - 1 ? "disabled" : ""} title="Descer">↓</button>
          <button type="button" class="btn btn-ghost btn-sm" data-ed="rm-etapa" data-k="${e._k}" title="Remover etapa">✕</button>
        </span>
      </div>`).join("")}
      <button type="button" class="btn btn-ghost btn-sm" data-ed="add-etapa">+ Etapa</button>
    </div>`;
}

function aoEditar(acao, k){
  lerEditor();
  const E = EDITANDO;
  if(acao === "add-papel") E.papeis.push({_k: novoK(), chave: "", nome: "", padrao_user_id: null});
  else if(acao === "rm-papel"){
    if(E.papeis.length === 1){ toast("O modelo precisa de pelo menos um papel", true); return; }
    E.papeis = E.papeis.filter(p => p._k !== k);
    E.etapas.forEach(e => { if(e.papel === k) e.papel = E.papeis[0]._k; });
  }
  else if(acao === "add-etapa") E.etapas.push({_k: novoK(), chave: "", nome: "", tipo: "execucao",
                                               papel: E.papeis[0]._k, devolve_para: ""});
  else if(acao === "rm-etapa"){
    E.etapas = E.etapas.filter(e => e._k !== k);
    E.etapas.forEach(e => { if(e.devolve_para === k) e.devolve_para = ""; });
  }
  else if(acao === "sobe" || acao === "desce"){
    const i = E.etapas.findIndex(e => e._k === k), j = acao === "sobe" ? i - 1 : i + 1;
    [E.etapas[i], E.etapas[j]] = [E.etapas[j], E.etapas[i]];
  }
  // A primeira etapa não pode ser revisão, e a revisão só devolve para trás.
  E.etapas.forEach((e, i) => {
    if(i === 0) e.tipo = "execucao";
    const antes = E.etapas.slice(0, i).map(x => x._k);
    if(e.devolve_para && !antes.includes(e.devolve_para)) e.devolve_para = "";
  });
  renderEditor();
}

async function salvarModelo(){
  lerEditor();
  const E = EDITANDO;
  const usadas = new Set();
  const chaveDe = (atual, nome) => {
    let c = atual || slug(nome) || "item", base = c, n = 2;
    while(usadas.has(c)) c = base + "_" + (n++);
    usadas.add(c);
    return c;
  };
  const papelChave = {};
  const papeis = E.papeis.map(p => {
    const chave = chaveDe(p.chave, p.nome);
    papelChave[p._k] = chave;
    return {chave, nome: p.nome.trim(), padrao_user_id: p.padrao_user_id};
  });
  usadas.clear();
  const etapaChave = {};
  E.etapas.forEach(e => { etapaChave[e._k] = chaveDe(e.chave, e.nome); });
  const etapas = E.etapas.map(e => ({
    chave: etapaChave[e._k], nome: e.nome.trim(), papel: papelChave[e.papel], tipo: e.tipo,
    devolve_para: e.tipo === "revisao" ? (etapaChave[e.devolve_para] || "") : ""}));
  const corpo = {nome: E.nome.trim(), descricao: E.descricao.trim(), papeis, etapas};
  const b = el("modal-salvar");
  b.disabled = true;
  try{
    if(E.id) await api("/fluxos/api/modelos/" + E.id, {method: "PUT", body: JSON.stringify(corpo)});
    else await api("/fluxos/api/modelos", {method: "POST", body: JSON.stringify(corpo)});
    toast("Modelo salvo");
    fecharModal();
    carregarModelos();
  }catch(e){ toast(e.message, true); }
  finally{ b.disabled = false; }
}

async function arquivar(id, ativo){
  try{
    if(ativo) await api("/fluxos/api/modelos/" + id, {method: "PUT", body: JSON.stringify({ativo: true})});
    else await api("/fluxos/api/modelos/" + id, {method: "DELETE"});
    carregarModelos();
  }catch(e){ toast(e.message, true); }
}

/* ═══════════ EVENTOS ═══════════ */
document.addEventListener("click", ev => {
  const nav = ev.target.closest(".nav-item[data-page]");
  if(nav){ irPara(nav.dataset.page); return; }

  const linha = ev.target.closest("tr.fx-linha");
  if(linha){ window.location.href = linha.dataset.link; return; }

  const mod = ev.target.closest("[data-modelo]");
  if(mod){
    const id = Number(mod.dataset.id);
    if(mod.dataset.modelo === "editar") abrirEditor(MODELOS.find(m => m.id === id));
    else arquivar(id, mod.dataset.modelo === "reativar");
    return;
  }
  const ed = ev.target.closest("[data-ed]");
  if(ed){ aoEditar(ed.dataset.ed, ed.dataset.k); return; }

  if(ev.target.id === "btn-novo-modelo"){ abrirEditor(null); return; }
  if(ev.target.id === "modal-cancelar" || ev.target.id === "modal-overlay") fecharModal();
});
document.addEventListener("change", ev => {
  // Trocar o tipo de uma etapa muda o que a linha mostra (o "devolve para").
  if(ev.target.classList.contains("ed-e-tipo")){ lerEditor(); aoEditar("nada"); }
  if(ev.target.id === "f-arquivados") carregarModelos();
  if(ev.target.id === "f-meus") renderAndamento();
});
document.addEventListener("input", ev => { if(ev.target.id === "f-q") renderAndamento(); });
document.addEventListener("keydown", ev => {
  if(ev.key === "Escape" && el("modal-overlay").classList.contains("open")) fecharModal();
  if(ev.key === "Enter" && ev.target.matches("tr.fx-linha")) window.location.href = ev.target.dataset.link;
});

/* Tempo real: a lista "Em andamento" acompanha os fluxos sem F5. O socket também
   repassa os eventos ao sino (socket-client.js → dt:evento). */
function tempoReal(){
  if(typeof DocTrackSocket === "undefined" || typeof io === "undefined") return;
  try{
    const dt = new DocTrackSocket({token: getToken()});
    let t = null;
    const agenda = () => { clearTimeout(t); t = setTimeout(carregarAndamento, 500); };
    ["FLUXO_INICIADO", "FLUXO_MOVIDO", "FLUXO_CONCLUIDO", "FLUXO_CANCELADO"].forEach(ev => dt.on(ev, agenda));
    dt.on("__connect__", () => { const l = el("sync-label"); if(l) l.textContent = "Tempo real · conectado"; });
    dt.on("__disconnect__", () => { const l = el("sync-label"); if(l) l.textContent = "Tempo real · reconectando…"; });
    dt.connect();
  }catch(e){ /* a página funciona sem tempo real */ }
}

function carregarTudo(){
  carregarAndamento();
  if(el("page-modelos").classList.contains("active")) carregarModelos();
}

function boot(){
  if(!getToken()){ window.location.href = "/"; return; }
  if(!PODE_USAR){ window.location.href = "/hub"; return; }
  document.getElementById("app").style.display = "block";
  const nome = USER.nome || "—";
  el("nav-name").textContent = nome;
  el("nav-role").textContent = ROLE.toUpperCase();
  el("nav-avatar").textContent = nome.charAt(0).toUpperCase();
  const topo = el("top-avatar");
  if(topo) topo.textContent = nome.charAt(0).toUpperCase();
  if(E_GESTAO){ el("nav-modelos").hidden = false; }
  else { el("btn-novo-modelo").hidden = true; }
  if(typeof initTheme === "function") initTheme();
  carregarTudo();
  tempoReal();
}

if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
