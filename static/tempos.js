/* ═══════════════════════════════════════════════════════════════════════════
   tempos.js — front da página do módulo Tempos.

   O servidor é dono do relógio e da regra (tempos/core.py): esta página só
   desenha e manda comandos. Nenhuma duração é calculada aqui a partir do
   relógio do navegador — o único cálculo local é o tique do cronômetro vivo, e
   ele é ancorado em `servidor_agora` justamente para não depender da máquina.

   O cronômetro em si mora no widget global (tempos-widget.js), presente em todos
   os módulos. Aqui ele aparece de novo porque esta é a tela do assunto, mas quem
   comanda é o mesmo `window.DT_TEMPO`, para não existirem dois estados.

   Sem bundler e sem framework, como o resto do projeto. Depende de common.js
   (esc, getToken, baixarDoServidor) e auth.js (DT_AUTH).
   ═══════════════════════════════════════════════════════════════════════════ */
"use strict";

sessionStorage.setItem("dt_module", "tempos");

function userObj(){
  try{ return JSON.parse(localStorage.getItem("doctrack_user") || "{}") || {}; }
  catch(e){ return {}; }
}
const ROLE = userObj().role || "";
// Mesmo corte do backend (so_membros). O front não decide nada — só evita
// mostrar uma tela inteira de 403 para quem já se sabe que não pode entrar.
const PODE_USAR = ROLE === "admin" || ROLE === "gestor" || ROLE === "tecnico";
const E_GESTAO = ROLE === "admin" || ROLE === "gestor";

let META = null;
let LINHAS = [];
let EDIT = null;

const el = id => document.getElementById(id);
const hhmm = iso => iso ? iso.slice(11, 16) : "—";

function toast(msg){
  const t = el("toast");
  el("toast-msg").textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 3200);
}

/* ── fetch autenticado (mesmo contrato dos outros módulos) ── */
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
    e.corpo = corpo; e.status = res.status;
    throw e;
  }
  return corpo;
}

/* ═══════════ NAVEGAÇÃO ═══════════ */
const TITULOS = {hoje: "Hoje", folha: "Folha", relatorios: "Relatórios"};

function irPara(pag){
  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  const alvo = el("page-" + pag);
  if(alvo) alvo.classList.add("active");
  document.querySelectorAll(".nav-item[data-page]").forEach(b =>
    b.classList.toggle("active", b.dataset.page === pag));
  el("breadcrumb-current").textContent = TITULOS[pag] || pag;
  if(pag === "relatorios") carregarRelatorio();
}

/* ═══════════ CRONÔMETRO (delega ao widget) ═══════════ */

function renderCronometro(){
  const est = window.DT_TEMPO ? window.DT_TEMPO.estado() : null;
  const box = el("tp-cronometro");
  if(!est){ box.innerHTML = ""; return; }

  if(est.em_curso){
    const a = est.em_curso;
    box.innerHTML =
      '<div class="card tp-crono rodando">' +
        '<div class="tp-crono-info">' +
          '<div class="tp-crono-alvo">' + esc(a.rotulo) + '</div>' +
          '<div class="tp-crono-meta">desde ' + hhmm(a.inicio_iso) +
            (a.ref_tipo !== "livre" ? ' · ' + esc(META ? META.ref_tipos_labels[a.ref_tipo] : a.ref_tipo) : '') +
          '</div>' +
        '</div>' +
        '<div class="tp-crono-relogio" id="tp-relogio">' + esc(a.duracao) + '</div>' +
        '<div class="tp-crono-acoes">' +
          '<button class="btn btn-ghost btn-sm" data-crono="pausar">Pausar</button>' +
          '<button class="btn btn-primary btn-sm" data-crono="parar">Parar</button>' +
        '</div>' +
      '</div>';
  } else if(est.retomavel){
    const a = est.retomavel;
    box.innerHTML =
      '<div class="card tp-crono pausado">' +
        '<div class="tp-crono-info">' +
          '<div class="tp-crono-alvo">' + esc(a.rotulo) + '</div>' +
          '<div class="tp-crono-meta">pausado às ' + hhmm(a.fim_iso) + '</div>' +
        '</div>' +
        '<div class="tp-crono-relogio pausado">' + esc(a.duracao) + '</div>' +
        '<div class="tp-crono-acoes">' +
          '<button class="btn btn-primary btn-sm" data-crono="retomar" data-id="' + a.id + '">Retomar</button>' +
          '<button class="btn btn-ghost btn-sm" data-crono="novo">Outra tarefa</button>' +
        '</div>' +
      '</div>';
  } else {
    box.innerHTML =
      '<div class="card tp-crono parado">' +
        '<div class="tp-crono-info">' +
          '<div class="tp-crono-alvo">Nenhum cronômetro em curso</div>' +
          '<div class="tp-crono-meta">Comece por um alvo recente ou escolha outro.</div>' +
        '</div>' +
        '<div class="tp-crono-acoes">' +
          '<button class="btn btn-primary btn-sm" data-crono="novo">Iniciar cronômetro</button>' +
        '</div>' +
      '</div>' + renderRecentes();
  }
}

function renderRecentes(){
  if(!META || !META.recentes.length) return "";
  return '<div class="tp-recentes">' +
    META.recentes.map(r =>
      '<button class="tp-chip" data-recente=\'' + esc(JSON.stringify(r)) + '\'>' +
        '<span class="tp-chip-tipo">' + esc(META.ref_tipos_labels[r.ref_tipo] || "") + '</span>' +
        esc(r.rotulo) +
      '</button>').join("") +
    '</div>';
}

/* ═══════════ TABELAS ═══════════ */

function chipAlvo(a){
  const tipo = META ? (META.ref_tipos_labels[a.ref_tipo] || a.ref_tipo) : a.ref_tipo;
  return '<span class="tp-alvo' + (a.ref_ativo ? '' : ' inativo') + '">' + esc(a.rotulo) +
         (a.ref_ativo ? '' : ' <span class="tp-inativo-tag">inativo</span>') + '</span>' +
         '<span class="tp-tipo">' + esc(tipo) + '</span>';
}

function selo(a){
  // O corte automático fica VISÍVEL: o sistema não adivinha uma duração e
  // esconde o palpite — sinaliza e deixa o dono corrigir.
  if(a.encerrado_por === "guarda")
    return '<span class="pill pill-warn" title="Cronômetro esquecido, cortado no limite. Confira o horário.">cortado</span>';
  if(a.em_curso) return '<span class="pill pill-wip">em curso</span>';
  if(a.origem === "manual") return '<span class="pill pill-elab">manual</span>';
  return "";
}

function linhaAcoes(a){
  return '<div class="row-actions">' +
    '<button class="ra-btn" data-editar="' + a.id + '" title="Editar">✎</button>' +
    '<button class="ra-btn ra-danger" data-excluir="' + a.id + '" title="Excluir">✕</button>' +
    '</div>';
}

function renderHoje(linhas){
  const hoje = new Date().toISOString().slice(0, 10);
  const doDia = linhas.filter(a => a.dia_iso === hoje);
  el("n-hoje").textContent = doDia.length || "";

  const total = doDia.reduce((s, a) => s + a.duracao_s, 0);
  const alvos = new Set(doDia.map(a => a.ref_tipo + ":" + (a.ref_id || a.titulo))).size;
  el("tp-kpis").innerHTML =
    kpi("Hoje", fmtDur(total)) +
    kpi("Lançamentos", String(doDia.length)) +
    kpi("Alvos distintos", String(alvos));

  el("tb-hoje").innerHTML = doDia.length ? doDia.map(a =>
    '<tr' + (a.em_curso ? ' class="tp-rodando"' : '') + '>' +
      '<td>' + hhmm(a.inicio_iso) + '</td>' +
      '<td>' + (a.em_curso ? '—' : hhmm(a.fim_iso)) + '</td>' +
      '<td class="tp-dur">' + esc(a.duracao) + ' ' + selo(a) + '</td>' +
      '<td>' + chipAlvo(a) + '</td>' +
      '<td>' + esc(META ? (META.ref_tipos_labels[a.ref_tipo] || "") : "") + '</td>' +
      '<td class="tp-nota">' + esc(a.nota || "") + '</td>' +
      '<td>' + linhaAcoes(a) + '</td>' +
    '</tr>').join("")
    : '<tr><td colspan="7" class="tp-vazio">Nada apontado hoje ainda.</td></tr>';
}

function renderFolha(linhas, total){
  el("f-total").textContent = linhas.length + " lançamento(s) · " + total;
  el("tb-folha").innerHTML = linhas.length ? linhas.map(a =>
    '<tr>' +
      '<td>' + esc(a.inicio.slice(0, 10)) + '</td>' +
      '<td>' + esc(a.usuario_nome) + '</td>' +
      '<td>' + hhmm(a.inicio_iso) + '</td>' +
      '<td>' + (a.em_curso ? '—' : hhmm(a.fim_iso)) + '</td>' +
      '<td class="tp-dur">' + esc(a.duracao) + ' ' + selo(a) + '</td>' +
      '<td>' + chipAlvo(a) + '</td>' +
      '<td>' + esc(META ? (META.ref_tipos_labels[a.ref_tipo] || "") : "") + '</td>' +
      '<td class="tp-nota">' + esc(a.nota || "") +
        (a.editado ? ' <span class="tp-editado" title="Corrigido por ' + esc(a.editado_por) +
                     ' em ' + esc(a.editado_em) + '">editado</span>' : '') + '</td>' +
      '<td>' + linhaAcoes(a) + '</td>' +
    '</tr>').join("")
    : '<tr><td colspan="9" class="tp-vazio">Nenhum apontamento no período.</td></tr>';
}

function kpi(rotulo, valor){
  return '<div class="metric"><div class="metric-label">' + esc(rotulo) + '</div>' +
         '<div class="metric-value">' + esc(valor) + '</div></div>';
}

function fmtDur(s){
  s = Math.max(0, Math.floor(s || 0));
  return Math.floor(s / 3600) + "h " + String(Math.floor((s % 3600) / 60)).padStart(2, "0") + "m";
}

/* ═══════════ RELATÓRIO ═══════════ */

async function carregarRelatorio(){
  const por = el("r-por").value;
  try{
    const d = await api("/tempos/api/resumo?por=" + por + "&" + filtros());
    const max = Math.max.apply(null, d.grupos.map(g => g.duracao_s).concat([1]));
    el("tp-relatorio").innerHTML =
      '<div class="card"><div class="card-title">Total do período: ' + esc(d.total) +
      ' <span class="tp-sub">(' + d.linhas + ' lançamentos)</span></div>' +
      (d.grupos.length ? '<div class="tp-barras">' + d.grupos.map(g =>
        '<div class="tp-barra-linha">' +
          '<div class="tp-barra-rot" title="' + esc(g.rotulo) + '">' + esc(g.rotulo) + '</div>' +
          '<div class="tp-barra-trilho"><div class="tp-barra" style="width:' +
            (g.duracao_s / max * 100).toFixed(1) + '%"></div></div>' +
          '<div class="tp-barra-val">' + esc(g.duracao) + '</div>' +
        '</div>').join("") + '</div>'
        : '<div class="tp-vazio">Nada no período.</div>') +
      '</div>';
  }catch(e){ toast(e.message); }
}

/* ═══════════ MODAL ═══════════ */

function abrirModal(titulo, sub, corpo, aoSalvar){
  el("modal-titulo").textContent = titulo;
  el("modal-sub").textContent = sub || "";
  el("modal-corpo").innerHTML = corpo;
  el("modal-overlay").classList.add("open");
  el("modal-salvar").onclick = aoSalvar;
}
function fecharModal(){
  el("modal-overlay").classList.remove("open");
  EDIT = null;
}

function campo(rot, html){
  return '<label class="tp-campo"><span>' + esc(rot) + '</span>' + html + '</label>';
}

function formApontamento(a){
  const tipos = META.ref_tipos.map(t =>
    '<option value="' + t + '"' + (a && a.ref_tipo === t ? ' selected' : '') + '>' +
    esc(META.ref_tipos_labels[t]) + '</option>').join("");
  const dia = a ? a.inicio_iso.slice(0, 10) : new Date().toISOString().slice(0, 10);
  return campo("Tipo de alvo", '<select id="m-tipo" class="filter-sel">' + tipos + '</select>') +
    '<div id="m-alvo-box"></div>' +
    campo("Título", '<input id="m-titulo" class="search-input" value="' +
          esc(a ? a.titulo : "") + '" placeholder="O que foi feito">') +
    '<div class="g2">' +
      campo("Data", '<input type="date" id="m-dia" class="filter-sel" value="' + dia + '">') +
      campo("Início", '<input type="time" id="m-ini" class="filter-sel" value="' +
            (a ? hhmm(a.inicio_iso) : "09:00") + '">') +
    '</div>' +
    campo("Fim", '<input type="time" id="m-fim" class="filter-sel" value="' +
          (a && a.fim_iso ? hhmm(a.fim_iso) : "10:00") + '">') +
    campo("Nota", '<textarea id="m-nota" class="search-input" rows="2">' +
          esc(a ? a.nota : "") + '</textarea>');
}

async function trocarTipoAlvo(){
  const tipo = el("m-tipo").value;
  const box = el("m-alvo-box");
  if(tipo === "livre"){ box.innerHTML = ""; return; }
  box.innerHTML = campo("Alvo", '<select id="m-alvo" class="filter-sel"><option>carregando…</option></select>');
  try{
    const d = await api("/tempos/api/alvos?tipo=" + tipo);
    el("m-alvo").innerHTML = d.alvos.length
      ? d.alvos.map(x => '<option value="' + x.id + '">' + esc(x.rotulo) +
                         (x.extra ? " — " + esc(x.extra) : "") + '</option>').join("")
      : '<option value="">nenhum disponível</option>';
    if(EDIT && EDIT.ref_tipo === tipo && EDIT.ref_id) el("m-alvo").value = EDIT.ref_id;
  }catch(e){ toast(e.message); }
}

function corpoDoForm(){
  const tipo = el("m-tipo").value;
  const alvo = el("m-alvo");
  const dia = el("m-dia").value;
  return {
    ref_tipo: tipo,
    ref_id: (tipo !== "livre" && alvo && alvo.value) ? Number(alvo.value) : null,
    titulo: el("m-titulo").value.trim(),
    nota: el("m-nota").value.trim(),
    inicio: dia + "T" + el("m-ini").value,
    fim: dia + "T" + el("m-fim").value,
  };
}

function novoManual(){
  EDIT = null;
  abrirModal("Lançar tempo", "Registro retroativo — o servidor confere sobreposição.",
             formApontamento(null), salvarManual);
  el("m-tipo").addEventListener("change", trocarTipoAlvo);
  trocarTipoAlvo();
}

async function salvarManual(){
  try{
    await api("/tempos/api/apontamentos", {method: "POST", body: JSON.stringify(corpoDoForm())});
    fecharModal();
    toast("Tempo lançado.");
    carregarTudo();
  }catch(e){
    // O 409 traz QUAL linha conflita — dizer só "conflita" não ajudaria ninguém.
    toast(e.message);
  }
}

async function editar(id){
  try{
    EDIT = await api("/tempos/api/apontamentos/" + id);
    abrirModal("Editar apontamento",
               EDIT.em_curso ? "Em curso: só o início é editável (use Parar para encerrar)." : "",
               formApontamento(EDIT), salvarEdicao);
    el("m-tipo").value = EDIT.ref_tipo;
    el("m-tipo").addEventListener("change", trocarTipoAlvo);
    if(EDIT.em_curso) el("m-fim").closest(".tp-campo").style.display = "none";
    trocarTipoAlvo();
  }catch(e){ toast(e.message); }
}

async function salvarEdicao(){
  const corpo = corpoDoForm();
  if(EDIT.em_curso) delete corpo.fim;
  const id = EDIT.id;
  try{
    await api("/tempos/api/apontamentos/" + id, {method: "PUT", body: JSON.stringify(corpo)});
    fecharModal();
    toast("Apontamento atualizado.");
    carregarTudo();
  }catch(e){ toast(e.message); }
}

async function excluir(id){
  if(!confirm("Excluir este apontamento? A ação não pode ser desfeita.")) return;
  try{
    await api("/tempos/api/apontamentos/" + id, {method: "DELETE"});
    toast("Apontamento excluído.");
    carregarTudo();
  }catch(e){ toast(e.message); }
}

function iniciarNovo(){
  EDIT = null;
  abrirModal("Iniciar cronômetro", "O servidor carimba o horário de início.",
    campo("Tipo de alvo", '<select id="m-tipo" class="filter-sel">' +
      META.ref_tipos.map(t => '<option value="' + t + '">' +
        esc(META.ref_tipos_labels[t]) + '</option>').join("") + '</select>') +
    '<div id="m-alvo-box"></div>' +
    campo("Título", '<input id="m-titulo" class="search-input" placeholder="O que você vai fazer">'),
    async () => {
      const tipo = el("m-tipo").value, alvo = el("m-alvo");
      try{
        await window.DT_TEMPO.iniciar({
          ref_tipo: tipo,
          ref_id: (tipo !== "livre" && alvo && alvo.value) ? Number(alvo.value) : null,
          titulo: el("m-titulo").value.trim(),
        });
        fecharModal();
        carregarTudo();
      }catch(e){ toast(e.message); }
    });
  el("m-tipo").addEventListener("change", trocarTipoAlvo);
  trocarTipoAlvo();
}

/* ═══════════ CARGA ═══════════ */

function filtros(){
  const p = new URLSearchParams();
  if(el("f-de").value) p.set("de", el("f-de").value);
  if(el("f-ate").value) p.set("ate", el("f-ate").value);
  if(el("f-tipo").value) p.set("ref_tipo", el("f-tipo").value);
  if(el("f-q").value.trim()) p.set("q", el("f-q").value.trim());
  const pessoa = el("f-pessoa");
  if(E_GESTAO && pessoa && pessoa.value) p.set("user_id", pessoa.value);
  return p.toString();
}

async function carregarMeta(){
  META = await api("/tempos/api/meta");
  el("f-tipo").innerHTML = '<option value="">Todos os alvos</option>' +
    META.ref_tipos.map(t => '<option value="' + t + '">' +
      esc(META.ref_tipos_labels[t]) + '</option>').join("");
  if(META.gestao){
    const s = el("f-pessoa");
    s.style.display = "";
    s.innerHTML = '<option value="">Todo mundo</option>' +
      META.pessoas.map(p => '<option value="' + p.id + '">' + esc(p.nome) + '</option>').join("");
  }
}

async function carregarTudo(){
  try{
    if(!META) await carregarMeta();
    if(window.DT_TEMPO) await window.DT_TEMPO.recarregar();
    renderCronometro();

    const d = await api("/tempos/api/apontamentos?" + filtros());
    LINHAS = d.apontamentos;
    renderHoje(LINHAS);
    renderFolha(LINHAS, d.total);
    if(el("page-relatorios").classList.contains("active")) carregarRelatorio();
  }catch(e){ toast(e.message); }
}

/* ═══════════ EVENTOS ═══════════ */

document.addEventListener("click", async ev => {
  const nav = ev.target.closest(".nav-item[data-page]");
  if(nav){ irPara(nav.dataset.page); return; }

  const crono = ev.target.closest("[data-crono]");
  if(crono){
    const acao = crono.dataset.crono;
    try{
      if(acao === "pausar") await window.DT_TEMPO.pausar();
      else if(acao === "parar") await window.DT_TEMPO.parar();
      else if(acao === "retomar") await window.DT_TEMPO.retomar(Number(crono.dataset.id));
      else if(acao === "novo"){ iniciarNovo(); return; }
      carregarTudo();
    }catch(e){ toast(e.message); }
    return;
  }

  const chip = ev.target.closest("[data-recente]");
  if(chip){
    try{
      await window.DT_TEMPO.iniciar(JSON.parse(chip.dataset.recente));
      carregarTudo();
    }catch(e){ toast(e.message); }
    return;
  }

  const ed = ev.target.closest("[data-editar]");
  if(ed){ editar(Number(ed.dataset.editar)); return; }

  const ex = ev.target.closest("[data-excluir]");
  if(ex){ excluir(Number(ex.dataset.excluir)); return; }

  if(ev.target.id === "btn-manual"){ novoManual(); return; }
  if(ev.target.id === "modal-cancelar" || ev.target.id === "modal-overlay"){ fecharModal(); return; }
  if(ev.target.id === "btn-csv"){
    baixarDoServidor("/tempos/api/export/apontamentos.csv?" + filtros()); return;
  }
  if(ev.target.id === "btn-xlsx"){
    baixarDoServidor("/tempos/api/export/tempos.xlsx?" + filtros()); return;
  }
});

document.addEventListener("keydown", ev => {
  if(ev.key === "Escape" && el("modal-overlay").classList.contains("open")) fecharModal();
});

let _tf = null;
["f-de", "f-ate", "f-tipo", "f-q", "f-pessoa"].forEach(id => {
  const e = el(id);
  if(e) e.addEventListener("input", () => {
    clearTimeout(_tf);
    _tf = setTimeout(carregarTudo, 280);
  });
});
el("r-por").addEventListener("change", carregarRelatorio);

// O widget avisa quando o cronômetro muda (inclusive vindo de outra aba), para a
// página não guardar um segundo estado que possa divergir dele.
window.addEventListener("dt-tempo-mudou", () => { renderCronometro(); });

/* ═══════════ BOOT ═══════════
   style.css esconde #app por padrão e cada módulo o revela depois de conferir a
   sessão — é o que impede a tela piscar antes de saber se há usuário. Sem esta
   função a página carrega inteira e fica invisível (foi o bug do commit f7b65e7). */
function boot(){
  if(!token()){ window.location.href = "/"; return; }
  if(!PODE_USAR){ window.location.href = "/hub/pde"; return; }

  document.getElementById("app").style.display = "block";

  const u = userObj();
  const nome = u.nome || "—";
  el("nav-name").textContent = nome;
  el("nav-role").textContent = (u.role || "").toUpperCase();
  el("nav-avatar").textContent = nome.charAt(0).toUpperCase();
  const topo = el("top-avatar");
  if(topo) topo.textContent = nome.charAt(0).toUpperCase();

  // Padrão da folha: a semana corrente.
  const hoje = new Date();
  const seg = new Date(hoje);
  seg.setDate(hoje.getDate() - ((hoje.getDay() + 6) % 7));
  el("f-de").value = seg.toISOString().slice(0, 10);
  el("f-ate").value = hoje.toISOString().slice(0, 10);

  if(typeof initTheme === "function") initTheme();
  carregarTudo();
}

if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
