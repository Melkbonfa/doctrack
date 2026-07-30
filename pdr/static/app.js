/* Dashboard PDR — SPA frontend
   Auth JWT + navegação + gráficos (Chart.js) + CRUD com RBAC + tempo real (Socket.IO) */
"use strict";

// Dados do módulo são servidos sob /pdr; autenticação é a do mestre (raiz).
const API = "/pdr";
const PALETTE = ["#06b6d4", "#22d3ee", "#67e8f9", "#0891b2", "#ec4899", "#22d3ee", "#0891b2", "#67e8f9"];
const STATUS_COLOR = { "Finalizado": "#10b981", "Em progresso": "#22d3ee", "Pendente": "#f59e0b", "Descontinuado": "#64748b" };

const state = {
  token: localStorage.getItem("doctrack_token") || "",
  refresh: localStorage.getItem("doctrack_refresh") || "",
  user: null,
  meta: null,
  produtos: [],
  apres: [],
  page: "dashboard",
  editingApres: null,
  socket: null,
};
const charts = {};

// ── HELPERS ─────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function toast(msg, kind = "ok") {
  const t = $("toast"); $("toast-msg").textContent = msg;
  t.querySelector(".toast-dot").style.background = kind === "err" ? "var(--red)" : kind === "warn" ? "var(--amber)" : "var(--cyan)";
  t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 3000);
}

async function api(path, opts = {}, _retry = false) {
  opts.headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
  if (state.token) opts.headers["Authorization"] = "Bearer " + state.token;
  const r = await fetch(API + path, opts);
  if (r.status === 401 && state.refresh && !_retry) {
    const ok = await tryRefresh();
    if (ok) return api(path, opts, true);
    doLogout(); throw new Error("Sessão expirada");
  }
  let data = null; try { data = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error((data && data.erro) || ("Erro " + r.status));
  return data;
}

async function tryRefresh() {
  try {
    // Autenticação é compartilhada com o mestre (rota na raiz, sem prefixo /pdr).
    const r = await fetch("/api/auth/refresh", { method: "POST", headers: { "Authorization": "Bearer " + state.refresh } });
    if (!r.ok) return false;
    const d = await r.json(); state.token = d.access_token;
    localStorage.setItem("doctrack_token", state.token); return true;
  } catch (e) { return false; }
}

// ── AUTH ────────────────────────────────────────────────────────────────────
// O login é feito na plataforma mestre; aqui apenas reaproveitamos a sessão.
function voltarAoLogin() {
  localStorage.removeItem("doctrack_token");
  localStorage.removeItem("doctrack_refresh");
  localStorage.removeItem("doctrack_user");
  window.location.href = "/";
}

async function doLogout() {
  try { await fetch("/api/auth/logout", { method: "POST", headers: { "Authorization": "Bearer " + state.token } }); } catch (e) {}
  if (state.socket) { state.socket.disconnect(); state.socket = null; }
  voltarAoLogin();
}

async function enterApp() {
  // A sessão vem do mestre (localStorage). Sem token/usuário, volta ao hub/login.
  if (!state.token) return voltarAoLogin();
  if (!state.user) {
    try { state.user = JSON.parse(localStorage.getItem("doctrack_user") || "null"); } catch (e) { state.user = null; }
  }
  if (!state.user) return voltarAoLogin();
  // Sem tela de login própria: a aplicação fica visível assim que há sessão.
  $("app").style.display = "block";
  // Header do usuário
  const u = state.user;
  $("nav-name").textContent = u.nome; $("nav-role").textContent = (u.role || "").toUpperCase();
  $("nav-avatar").textContent = (u.nome || "?")[0].toUpperCase();
  $("top-avatar").textContent = (u.nome || "?")[0].toUpperCase();
  const exp = $("btn-export");
  if (exp) exp.onclick = exportarApresCSV;
  applyRBAC();
  state.meta = await api("/api/meta");
  fillSelects();
  connectSocket();
  await refreshAll();
}

function applyRBAC() {
  const role = state.user.role;
  const isEditor = ["admin", "gestor", "tecnico"].includes(role);
  const isGestor = ["admin", "gestor"].includes(role);
  const isAdmin = role === "admin";
  document.querySelectorAll(".editor-only").forEach((e) => e.style.display = isEditor ? "" : "none");
  document.querySelectorAll(".admin-only").forEach((e) => e.style.display = isAdmin ? "" : "none");
  document.querySelectorAll(".gestor-only").forEach((e) => e.style.display = isGestor ? "" : "none");
  document.querySelectorAll(".nav-gestor").forEach((e) => e.style.display = isGestor ? "" : "none");
}

// ── NAVEGAÇÃO ───────────────────────────────────────────────────────────────
function navigate(page) {
  state.page = page;
  document.querySelectorAll(".nav-item").forEach((n) => n.classList.toggle("active", n.dataset.page === page));
  document.querySelectorAll(".page").forEach((p) => p.classList.remove("active"));
  $("page-" + page).classList.add("active");
  const labels = { dashboard: "Dashboard", produtos: "Produtos", apresentacoes: "Apresentações", audit: "Audit Log", usuarios: "Usuários" };
  $("breadcrumb-current").textContent = labels[page] || page;
  if (page === "audit") loadAudit();
  if (page === "usuarios") loadUsers();
}
document.querySelectorAll(".nav-item").forEach((n) => n.addEventListener("click", () => navigate(n.dataset.page)));

async function refreshAll() {
  try {
    await Promise.all([loadDashboard(), loadProdutos(), loadApres()]);
  } catch (e) { toast(e.message, "err"); }
}

function fillSelects() {
  const linhas = state.meta.linhas || [];
  const opts = '<option value="">Todas as linhas</option>' + linhas.map((l) => `<option>${esc(l)}</option>`).join("");
  $("produtos-linha").innerHTML = opts;
  $("ap-linha").innerHTML = opts;
  $("mp-linha").innerHTML = linhas.map((l) => `<option>${esc(l)}</option>`).join("");
}

// ── DASHBOARD ───────────────────────────────────────────────────────────────
// Escopo do dashboard: todos / um produto / uma apresentação
let dashScope = { produtoId: null, apresId: null };

async function loadDashboard() {
  let d, label;
  if (!dashScope.produtoId && !dashScope.apresId) {
    try { d = await api("/api/dashboard"); } catch (e) { d = computeDash(state.apres); }
    label = "";
  } else if (dashScope.apresId) {
    const list = state.apres.filter((a) => a.id === dashScope.apresId);
    d = computeDash(list);
    label = "Apresentação " + (list[0] ? (list[0].sku || list[0].apresentacao) : "—");
  } else {
    const list = state.apres.filter((a) => a.produto_id === dashScope.produtoId);
    d = computeDash(list);
    label = "Produto: " + (list[0] ? list[0].produto_nome : "—");
  }
  renderDashboardData(d, label);
}

function renderDashboardData(d, label) {
  $("dash-updated").textContent = (label ? label + " · " : "") + "atualizado em " + d.atualizado_em;
  $("dash-badge").textContent = d.avanco_geral + "% concluído";
  $("m-produtos").textContent = d.total_produtos;
  $("m-apres").textContent = d.total_apresentacoes;
  $("m-final").textContent = d.finalizadas;
  $("m-descont").textContent = d.descontinuadas;

  const ativas = d.total_apresentacoes - d.descontinuadas;
  ring("ringAvanco", "val-avanco", d.avanco_geral, "%", 0);
  ring("ringFinal", "val-final", d.total_apresentacoes ? Math.round(d.finalizadas * 100 / d.total_apresentacoes) : 0, "%", 1);
  ring("ringAtivas", "val-ativas", d.total_apresentacoes ? Math.round(ativas * 100 / d.total_apresentacoes) : 0, "%", 2);
  $("delta-final").textContent = d.finalizadas + " de " + d.total_apresentacoes;
  $("delta-ativas").textContent = ativas + " ativas";

  donutLinha(d.por_linha);
  funil(d.funil);
  barH("chFornecedor", d.por_fornecedor.map((x) => x.label), d.por_fornecedor.map((x) => x.value), PALETTE);
  // ANVISA + Protheus combinados
  const reg = (d.por_anvisa || []).map((x) => ({ l: "ANVISA · " + x.label, v: x.value }))
    .concat((d.por_protheus || []).map((x) => ({ l: "Protheus · " + x.label, v: x.value })));
  barH("chAnvisa", reg.map((x) => x.l), reg.map((x) => x.v), reg.map((_, i) => PALETTE[i % PALETTE.length]));

  $("dash-table").innerHTML = (d.ultimas || []).map((a) => `<tr>
    <td class="bold">${esc(a.produto_nome)}</td><td>${esc(a.apresentacao)}</td>
    <td class="mono">${esc(a.sku)}</td><td>${sgBadge(a.status_global)}</td>
    <td>${avancoBar(a.avanco)}</td><td class="mono">${esc(a.updated_em)}</td></tr>`).join("") ||
    '<tr><td colspan="6" style="text-align:center;color:var(--t4)">Sem registros</td></tr>';
}

// Agrega KPIs/gráficos a partir de uma lista de apresentações (mesmo formato de /api/dashboard)
const _OKSET = new Set(["FINALIZADO", "FINALIZADO/LIBERADO", "HOMOLOGADO", "LIBERADO"]);
const _DESCSET = new Set(["DESCONTINUADO", "OBSOLETO"]);
const _TIPOS = ["especificacao", "descritivo", "instrucao_trabalho", "manual"];
const _TIPO_LABEL = { especificacao: "Especificação do Produto", descritivo: "Descritivo", instrucao_trabalho: "Instrução de Trabalho", manual: "Manual" };

function computeDash(list) {
  list = list || [];
  const byLinha = {}, byForn = {}, byAnv = {}, byProt = {}, byStatus = {};
  let docsOk = 0, docsTot = 0, finalizadas = 0, descont = 0;
  const funilM = {}; _TIPOS.forEach((t) => funilM[t] = { ok: 0, pendente: 0, descontinuado: 0 });
  const inc = (o, k) => { k = k || "—"; o[k] = (o[k] || 0) + 1; };
  list.forEach((a) => {
    inc(byLinha, a.linha); inc(byForn, a.fornecedor); inc(byAnv, a.anvisa); inc(byProt, a.cadastro_protheus);
    byStatus[a.status_global] = (byStatus[a.status_global] || 0) + 1;
    if (a.status_global === "Finalizado") finalizadas++;
    if (a.status_global === "Descontinuado") descont++;
    (a.documentos || []).forEach((doc) => {
      const v = (doc.status || doc.fase || "").toUpperCase();
      const fm = funilM[doc.tipo];
      if (_DESCSET.has(v)) { if (fm) fm.descontinuado++; return; }
      docsTot++;
      if (doc.is_ok || _OKSET.has(v)) { docsOk++; if (fm) fm.ok++; }
      else if (fm) fm.pendente++;
    });
  });
  const top = (o, n = 8) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n).map(([label, value]) => ({ label, value }));
  return {
    total_produtos: new Set(list.map((a) => a.produto_nome)).size,
    total_apresentacoes: list.length,
    descontinuadas: descont, finalizadas,
    avanco_geral: docsTot ? Math.round(docsOk * 100 / docsTot) : 0,
    por_linha: top(byLinha), por_fornecedor: top(byForn), por_anvisa: top(byAnv), por_protheus: top(byProt),
    por_status: Object.entries(byStatus).map(([label, value]) => ({ label, value })),
    funil: _TIPOS.map((t) => ({ tipo: _TIPO_LABEL[t], ...funilM[t] })),
    ultimas: [...list].sort((a, b) => (b.updated_em || "").localeCompare(a.updated_em || "")).slice(0, 10),
    atualizado_em: new Date().toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }),
  };
}

// ── Filtros de escopo do dashboard ───────────────────────────────────────────
function populateDashProdutos() {
  const sel = $("dash-produto");
  if (!sel) return;
  const prods = [...state.produtos].sort((a, b) => a.nome.localeCompare(b.nome));
  sel.innerHTML = '<option value="">Todos os produtos</option>' +
    prods.map((p) => `<option value="${p.id}" ${p.id === dashScope.produtoId ? "selected" : ""}>${esc(p.nome)}${p.sigla ? " (" + esc(p.sigla) + ")" : ""}</option>`).join("");
}

function populateDashApres() {
  const sel = $("dash-apres");
  if (!sel) return;
  if (!dashScope.produtoId) { sel.innerHTML = '<option value="">Todas as apresentações</option>'; sel.disabled = true; return; }
  sel.disabled = false;
  const list = state.apres.filter((a) => a.produto_id === dashScope.produtoId)
    .sort((a, b) => (a.apresentacao || a.sku || "").localeCompare(b.apresentacao || b.sku || ""));
  sel.innerHTML = '<option value="">Todas as apresentações</option>' +
    list.map((a) => `<option value="${a.id}" ${a.id === dashScope.apresId ? "selected" : ""}>${esc(a.apresentacao || a.sku)} — ${esc(a.sku)}</option>`).join("");
}

function onDashProduto() {
  const v = $("dash-produto").value;
  dashScope.produtoId = v ? parseInt(v) : null;
  dashScope.apresId = null;
  populateDashApres();
  loadDashboard();
}

function onDashApres() {
  const v = $("dash-apres").value;
  dashScope.apresId = v ? parseInt(v) : null;
  loadDashboard();
}

function clearDashScope() {
  dashScope = { produtoId: null, apresId: null };
  populateDashProdutos(); populateDashApres();
  loadDashboard();
}

// Gradiente vertical por fatia (igual à referência: cor no topo → escurecida embaixo)
function _darken(hex, f) {
  const n = parseInt(String(hex).replace("#", ""), 16);
  return `rgb(${Math.round(((n >> 16) & 255) * f)},${Math.round(((n >> 8) & 255) * f)},${Math.round((n & 255) * f)})`;
}
function donutGrad(ctx, hex) {
  const g = ctx.createLinearGradient(0, 0, 0, 160);
  g.addColorStop(0, hex); g.addColorStop(1, _darken(hex, 0.5));
  return g;
}
// Tooltip externo com bolinha colorida (igual à referência)
function donutTooltipExternal(context) {
  const { chart, tooltip } = context;
  let el = $("app-donut-tip");
  if (!el) {
    el = document.createElement("div"); el.id = "app-donut-tip";
    el.style.cssText = "position:fixed;pointer-events:none;z-index:9999;opacity:0;transition:opacity .1s ease;background:#232847;border:1px solid rgba(6,182,212,.4);border-radius:8px;padding:7px 10px;font:500 12px/1.2 Inter,system-ui,sans-serif;color:#f1f5f9;white-space:nowrap;box-shadow:0 8px 24px rgba(0,0,0,.45);display:flex;align-items:center;gap:7px";
    document.body.appendChild(el);
  }
  if (!tooltip || tooltip.opacity === 0) { el.style.opacity = "0"; return; }
  const dp = tooltip.dataPoints && tooltip.dataPoints[0];
  if (!dp) { el.style.opacity = "0"; return; }
  const dot = (dp.dataset.dotColors && dp.dataset.dotColors[dp.dataIndex]) || "#06b6d4";
  const body = (tooltip.body && tooltip.body[0] && tooltip.body[0].lines[0]) || (dp.label + ": " + dp.formattedValue);
  el.innerHTML = `<span style="width:9px;height:9px;border-radius:50%;background:${dot};flex-shrink:0"></span><span>${esc(body)}</span>`;
  el.style.opacity = "1";
  const rect = chart.canvas.getBoundingClientRect(), tw = el.offsetWidth, th = el.offsetHeight;
  let left = rect.left + tooltip.caretX + 14, top = rect.top + tooltip.caretY - th - 8;
  if (left + tw > window.innerWidth - 8) left = window.innerWidth - tw - 8;
  if (top < 8) top = rect.top + tooltip.caretY + 16;
  el.style.left = left + "px"; el.style.top = top + "px";
}

const RING_COLORS = ["#06b6d4", "#22d3ee", "#67e8f9"];
const RING_BGS = ["rgba(6,182,212,.16)", "rgba(34,211,238,.16)", "rgba(103,232,249,.16)"];

function ring(canvasId, valId, pct, suffix, idx) {
  const color = RING_COLORS[idx] || RING_COLORS[0];
  const valEl = $(valId);
  valEl.textContent = pct + (suffix || ""); valEl.style.color = color;
  const ctx = $(canvasId);
  if (charts[canvasId]) charts[canvasId].destroy();
  charts[canvasId] = new Chart(ctx, {
    type: "doughnut",
    data: { datasets: [{ data: [pct, 100 - pct], backgroundColor: [color, RING_BGS[idx] || RING_BGS[0]], borderWidth: 0, hoverOffset: 4 }] },
    options: { responsive: false, cutout: "78%", plugins: { legend: { display: false }, tooltip: { enabled: false } }, animation: { animateRotate: true, duration: 1200 } },
  });
}

function donutLinha(data) {
  $("donut-total").textContent = data.reduce((s, x) => s + x.value, 0);
  const colors = data.map((_, i) => PALETTE[i % PALETTE.length]);
  const ctx = $("chLinha");
  if (charts.chLinha) charts.chLinha.destroy();
  const grad = colors.map((c) => donutGrad(ctx.getContext("2d"), c));
  charts.chLinha = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: data.map((x) => x.label),
      datasets: [{ data: data.map((x) => x.value), backgroundColor: grad, dotColors: colors, borderWidth: 0, borderRadius: 8, spacing: 3, hoverOffset: 6 }],
    },
    options: {
      responsive: false, cutout: "78%",
      plugins: { legend: { display: false }, tooltip: { enabled: false, external: donutTooltipExternal, callbacks: { label: (c) => ` ${data[c.dataIndex].label}: ${c.parsed} SKUs` } } },
      animation: { animateRotate: true, duration: 1200 },
    },
  });
  $("legend-linha").innerHTML = data.map((x, i) => `<div class="legend-row" title="${esc(x.label)}"><span class="legend-dot" style="background:${colors[i]}"></span><span>${esc(x.label)}</span><span class="legend-val">${x.value}</span></div>`).join("");
}

function funil(data) {
  const max = Math.max(1, ...data.map((x) => x.ok + x.pendente));
  $("funil-list").innerHTML = data.map((x) => {
    const tot = x.ok + x.pendente;
    const pct = tot ? Math.round(x.ok * 100 / tot) : 0;
    return `<div class="prog-row"><span class="prog-label">${esc(x.tipo)}</span>
      <div class="prog-track"><div class="prog-fill" style="width:${tot ? Math.round(tot * 100 / max) : 0}%;background:var(--grad-cyan-brand)"></div></div>
      <span class="prog-pct">${x.ok}/${tot} (${pct}%)</span></div>`;
  }).join("");
}

// Gradiente horizontal por barra (base escura → ponta vibrante), no estilo da rosca
function barGradH(ctx, hex) {
  const g = ctx.createLinearGradient(0, 0, 320, 0);
  g.addColorStop(0, _darken(hex, 0.55)); g.addColorStop(1, hex);
  return g;
}

function barH(canvasId, labels, values, colors) {
  const ctx = $(canvasId);
  if (charts[canvasId]) charts[canvasId].destroy();
  const c2 = ctx.getContext("2d");
  const grads = colors.map((c) => barGradH(c2, c));
  charts[canvasId] = new Chart(ctx, {
    type: "bar",
    data: { labels, datasets: [{ data: values, backgroundColor: grads, dotColors: colors, borderRadius: 8, borderWidth: 0, barThickness: 16, maxBarThickness: 22 }] },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { enabled: false, external: donutTooltipExternal, callbacks: { label: (c) => ` ${c.label}: ${c.parsed.x}` } },
      },
      scales: {
        x: { grid: { color: "rgba(6,182,212,.07)" }, border: { display: false }, ticks: { color: "#94a3ff", font: { size: 10, family: "Inter" } } },
        y: { grid: { display: false }, border: { display: false }, ticks: { color: "#c7d2fe", font: { size: 10, family: "Inter" } } },
      },
    },
  });
}

// ── PRODUTOS ────────────────────────────────────────────────────────────────
async function loadProdutos() {
  state.produtos = await api("/api/produtos");
  // popular filtro de siglas
  const siglas = [...new Set(state.produtos.map((p) => p.sigla).filter(Boolean))].sort();
  const cur = $("produtos-sigla").value;
  $("produtos-sigla").innerHTML = '<option value="">Todas as siglas</option>' +
    siglas.map((s) => `<option ${s === cur ? "selected" : ""}>${esc(s)}</option>`).join("");
  populateDashProdutos();
  renderProdutos();
}

function renderProdutos() {
  const busca = ($("produtos-search").value || "").toLowerCase();
  const linha = $("produtos-linha").value;
  const sigla = $("produtos-sigla").value;
  const list = state.produtos.filter((p) =>
    (!linha || p.linha === linha) &&
    (!sigla || p.sigla === sigla) &&
    (!busca || (p.nome + " " + (p.sigla || "")).toLowerCase().includes(busca)));
  $("produtos-count").textContent = list.length + " produtos";
  $("produtos-grid").innerHTML = list.map((p) => {
    const st = p.avanco >= 80 ? "st-green" : p.avanco >= 40 ? "st-amber" : "st-red";
    return `<div class="equip-card ${st}" onclick="openProduto(${p.id})">
      <div class="equip-card-name">${esc(p.nome)}</div>
      <div class="equip-card-sku">${esc(p.sigla || "—")} · ${p.total_apresentacoes} apres.</div>
      ${avancoBar(p.avanco)}
      <div style="font-size:10px;color:var(--t4)">${esc(p.linha)}</div>
      <button class="btn-edit gestor-only" style="margin-top:8px" onclick="event.stopPropagation();openNewApres(${p.id})">+ Apresentação</button>
    </div>`;
  }).join("") || '<div class="loading-state">Nenhum produto</div>';
  applyRBAC();
}

async function openProduto(id) {
  navigate("apresentacoes");
  const p = state.produtos.find((x) => x.id === id);
  if (p) { $("ap-search").value = p.nome; renderApres(); }
}

// ── APRESENTAÇÕES ───────────────────────────────────────────────────────────
async function loadApres() {
  state.apres = await api("/api/apresentacoes");
  // popular filtros de fornecedor/anvisa
  const forns = [...new Set(state.apres.map((a) => a.fornecedor).filter(Boolean))].sort();
  const anvs = [...new Set(state.apres.map((a) => a.anvisa).filter(Boolean))].sort();
  $("ap-fornecedor").innerHTML = '<option value="">Todos fornecedores</option>' + forns.map((f) => `<option>${esc(f)}</option>`).join("");
  $("ap-anvisa").innerHTML = '<option value="">Toda ANVISA</option>' + anvs.map((a) => `<option>${esc(a)}</option>`).join("");
  renderApres();
}

// CSV com o mesmo recorte da aba. Antes era um <a href> com o token na query —
// o que ignorava os filtros e ainda gravava o JWT no log de acesso do servidor.
async function exportarApresCSV() {
  const p = new URLSearchParams();
  const busca = ($("ap-search").value || "").trim();
  if (busca) p.set("busca", busca);
  [["ap-linha", "linha"], ["ap-fornecedor", "fornecedor"],
   ["ap-anvisa", "anvisa"], ["ap-status", "status"]].forEach(([id, chave]) => {
    const v = $(id).value; if (v) p.set(chave, v);
  });
  const qs = p.toString();
  try {
    const r = await fetch(API + "/api/export/apresentacoes.csv" + (qs ? "?" + qs : ""),
                          { headers: { "Authorization": "Bearer " + state.token } });
    if (!r.ok) throw new Error("Erro " + r.status);
    const cd = r.headers.get("Content-Disposition") || "";
    const m = /filename="?([^";\n]+)"?/i.exec(cd);
    const href = URL.createObjectURL(await r.blob());
    const a = document.createElement("a");
    a.href = href; a.download = m ? m[1].trim() : "apresentacoes_pdr.csv";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
  } catch (e) { toast("Falha ao exportar: " + e.message, "err"); }
}

function renderApres() {
  const busca = ($("ap-search").value || "").toLowerCase();
  const fl = $("ap-linha").value, ff = $("ap-fornecedor").value, fa = $("ap-anvisa").value, fs = $("ap-status").value;
  const list = state.apres.filter((a) => {
    if (fl && a.linha !== fl) return false;
    if (ff && a.fornecedor !== ff) return false;
    if (fa && a.anvisa !== fa) return false;
    if (fs && a.status_global !== fs) return false;
    if (busca && !(`${a.produto_nome} ${a.sku} ${a.apresentacao} ${a.modelo} ${a.fornecedor} ${a.descricao}`.toLowerCase().includes(busca))) return false;
    return true;
  });
  $("ap-count").textContent = list.length + " apresentações";
  const canEdit = ["admin", "gestor", "tecnico"].includes(state.user.role);
  $("ap-tbody").innerHTML = list.slice(0, 600).map((a) => `<tr>
    <td class="bold">${esc(a.produto_nome)}</td>
    <td>${esc(a.apresentacao || a.descricao || "—")}</td>
    <td class="mono">${esc(a.sku)}</td>
    <td class="mono">${esc(a.modelo)}</td>
    <td>${esc(a.cadastro_protheus)}</td>
    <td>${esc(a.anvisa)}</td>
    <td>${esc(a.fornecedor)}</td>
    <td>${sgBadge(a.status_global)}</td>
    <td>${avancoBar(a.avanco)}</td>
    <td class="row-actions"><button class="btn-edit" onclick="openApresModal(${a.id})">${canEdit ? "Editar" : "Ver"}</button></td>
  </tr>`).join("") || '<tr><td colspan="10" style="text-align:center;color:var(--t4)">Nenhuma apresentação</td></tr>';
}

function openApresModal(id) {
  const a = state.apres.find((x) => x.id === id);
  if (!a) return;
  state.editingApres = JSON.parse(JSON.stringify(a));
  const canEdit = ["admin", "gestor", "tecnico"].includes(state.user.role);
  const ro = canEdit ? "" : "disabled";
  $("ma-title").textContent = canEdit ? "Editar Apresentação" : "Apresentação";
  $("ma-sub").textContent = `${a.produto_nome} · ${a.sku}`;
  const meta = state.meta;
  const sel = (id_, val, opts) => `<select class="form-input" id="${id_}" ${ro}>${["", ...opts].map((o) => `<option ${o === val ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
  const inp = (id_, val) => `<input class="form-input" id="${id_}" value="${esc(val)}" ${ro}>`;
  const docRow = (d) => `<div class="manual-row">
      <div class="manual-row-head"><span class="manual-row-name">${esc(d.tipo_label)}</span>${sgDot(d)}</div>
      <div style="display:grid;grid-template-columns:1.4fr .8fr ${d.tipo === "instrucao_trabalho" ? "1fr" : ""};gap:8px">
        ${sel("doc-status-" + d.id, d.status, meta.status_doc)}
        ${inp("doc-versao-" + d.id, d.versao)}
        ${d.tipo === "instrucao_trabalho" ? inp("doc-cod-" + d.id, d.codificacao) : ""}
      </div></div>`;
  $("ma-body").innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
      <div class="form-group"><label class="form-label">Apresentação</label>${inp("ma-apresentacao", a.apresentacao)}</div>
      <div class="form-group"><label class="form-label">Modelo</label>${inp("ma-modelo", a.modelo)}</div>
      <div class="form-group"><label class="form-label">SKU</label>${inp("ma-sku", a.sku)}</div>
      <div class="form-group"><label class="form-label">Fornecedor</label>${inp("ma-fornecedor", a.fornecedor)}</div>
      <div class="form-group"><label class="form-label">Cadastro Protheus</label>${sel("ma-cadastro_protheus", a.cadastro_protheus, meta.status_protheus)}</div>
      <div class="form-group"><label class="form-label">ANVISA</label>${sel("ma-anvisa", a.anvisa, meta.status_anvisa)}</div>
      <div class="form-group"><label class="form-label">Nº ANVISA</label>${inp("ma-numero_anvisa", a.numero_anvisa)}</div>
      <div class="form-group"><label class="form-label">Etiqueta</label>${inp("ma-etiqueta", a.etiqueta)}</div>
    </div>
    <div class="section-label-line">Documentação</div>
    ${a.documentos.map(docRow).join("")}
    <div class="form-group" style="margin-top:12px"><label class="form-label">Observações</label>${inp("ma-observacoes", a.observacoes)}</div>`;
  openModal("modal-apres-overlay");
}

async function saveApres() {
  const a = state.editingApres;
  const body = { version: a.version, documentos: [] };
  ["apresentacao", "modelo", "sku", "fornecedor", "cadastro_protheus", "anvisa", "numero_anvisa", "etiqueta", "observacoes"].forEach((f) => {
    const el = $("ma-" + f); if (el) body[f] = el.value;
  });
  a.documentos.forEach((d) => {
    const doc = { id: d.id };
    doc.status = $("doc-status-" + d.id).value;
    doc.versao = $("doc-versao-" + d.id).value;
    if (d.tipo === "instrucao_trabalho") doc.codificacao = $("doc-cod-" + d.id).value;
    body.documentos.push(doc);
  });
  try {
    await api("/api/apresentacoes/" + a.id, { method: "PATCH", body: JSON.stringify(body) });
    closeModal("modal-apres-overlay"); toast("Apresentação atualizada");
    await Promise.all([loadApres(), loadDashboard()]);
  } catch (e) {
    if (e.message.includes("alterada por outro")) { toast("Registro alterado por outro usuário. Recarregando…", "warn"); await loadApres(); closeModal("modal-apres-overlay"); }
    else toast(e.message, "err");
  }
}

// ── NOVA APRESENTAÇÃO ───────────────────────────────────────────────────────
function openNewApres(produtoId) {
  const meta = state.meta;
  const prods = [...state.produtos].sort((a, b) => a.nome.localeCompare(b.nome));
  const prodOpts = prods.map((p) => `<option value="${p.id}" ${p.id === produtoId ? "selected" : ""}>${esc(p.nome)}${p.sigla ? " (" + esc(p.sigla) + ")" : ""}</option>`).join("");
  const sel = (id_, opts) => `<select class="form-input" id="${id_}">${["", ...opts].map((o) => `<option>${esc(o)}</option>`).join("")}</select>`;
  $("mna-body").innerHTML = `
    <div class="form-group"><label class="form-label">Produto</label><select class="form-input" id="mna-produto">${prodOpts}</select></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
      <div class="form-group"><label class="form-label">Apresentação</label><input class="form-input" id="mna-apresentacao" placeholder="ex.: PU08-W"></div>
      <div class="form-group"><label class="form-label">Modelo</label><input class="form-input" id="mna-modelo"></div>
      <div class="form-group"><label class="form-label">SKU</label><input class="form-input" id="mna-sku" placeholder="ex.: 01.000000"></div>
      <div class="form-group"><label class="form-label">Fornecedor</label><input class="form-input" id="mna-fornecedor"></div>
      <div class="form-group"><label class="form-label">Cadastro Protheus</label>${sel("mna-cadastro_protheus", meta.status_protheus)}</div>
      <div class="form-group"><label class="form-label">ANVISA</label>${sel("mna-anvisa", meta.status_anvisa)}</div>
      <div class="form-group"><label class="form-label">Nº ANVISA</label><input class="form-input" id="mna-numero_anvisa"></div>
      <div class="form-group"><label class="form-label">Descrição</label><input class="form-input" id="mna-descricao"></div>
    </div>
    <div class="form-group"><label class="form-label">Observações</label><input class="form-input" id="mna-observacoes"></div>
    <div style="font-size:11px;color:var(--t4)">Os 4 documentos (especificação, descritivo, IT, manual) são criados em branco e podem ser preenchidos na edição.</div>`;
  const p = prods.find((x) => x.id === produtoId);
  $("mna-sub").textContent = p ? `Produto: ${p.nome}` : "Selecione o produto e preencha os dados";
  openModal("modal-newapres-overlay");
}

async function saveNewApres() {
  const produto_id = parseInt($("mna-produto").value);
  if (!produto_id) { toast("Selecione um produto", "err"); return; }
  const body = { produto_id };
  ["apresentacao", "modelo", "sku", "fornecedor", "cadastro_protheus", "anvisa", "numero_anvisa", "descricao", "observacoes"].forEach((f) => {
    const el = $("mna-" + f); if (el) body[f] = el.value;
  });
  if (!body.sku && !body.apresentacao) { toast("Informe ao menos SKU ou apresentação", "warn"); return; }
  try {
    const r = await api("/api/apresentacoes", { method: "POST", body: JSON.stringify(body) });
    closeModal("modal-newapres-overlay"); toast("Apresentação criada");
    await Promise.all([loadApres(), loadProdutos(), loadDashboard()]);
    // abre direto para edição da documentação, se desejado
    if (r && r.apresentacao && r.apresentacao.id) { navigate("apresentacoes"); }
  } catch (e) { toast(e.message, "err"); }
}

// ── PRODUTO MODAL ───────────────────────────────────────────────────────────
function openProdutoModal() {
  $("mp-nome").value = ""; $("mp-sigla").value = ""; $("mp-obs").value = "";
  openModal("modal-produto-overlay");
}
async function saveProduto() {
  try {
    await api("/api/produtos", { method: "POST", body: JSON.stringify({ nome: $("mp-nome").value, sigla: $("mp-sigla").value, linha: $("mp-linha").value, observacoes: $("mp-obs").value }) });
    closeModal("modal-produto-overlay"); toast("Produto criado"); await loadProdutos();
  } catch (e) { toast(e.message, "err"); }
}

// ── AUDIT ───────────────────────────────────────────────────────────────────
let auditCache = [];
async function loadAudit() { auditCache = await api("/api/audit?limit=400"); renderAudit(); }
function renderAudit() {
  const busca = ($("audit-search").value || "").toLowerCase();
  const fa = $("audit-filter").value;
  const list = auditCache.filter((l) => (!fa || l.acao === fa) &&
    (!busca || `${l.usuario} ${l.entidade} ${l.campo} ${l.valor_novo}`.toLowerCase().includes(busca)));
  $("audit-list").innerHTML = list.map((l) => `<div class="audit-item">
    <div class="audit-user">${esc(l.usuario)}<div style="color:var(--t4);font-size:10px">${esc(l.acao)}</div></div>
    <div class="audit-action">${esc(l.entidade)}${l.campo !== "—" ? " · " + esc(l.campo) : ""}
      ${l.valor_antigo ? `<span class="old">${esc(l.valor_antigo)}</span> → ` : ""}${l.valor_novo ? `<span class="new">${esc(l.valor_novo)}</span>` : ""}</div>
    <div class="audit-time">${esc(l.timestamp)}</div></div>`).join("") ||
    '<div class="loading-state">Sem registros</div>';
}

// ── USUÁRIOS ────────────────────────────────────────────────────────────────
let usersCache = [];
async function loadUsers() {
  try { usersCache = await api("/api/users"); } catch (e) { $("users-list").innerHTML = '<div class="loading-state">Sem permissão</div>'; return; }
  $("users-list").innerHTML = usersCache.map((u) => `<div class="user-card">
    <div class="uc-avatar">${esc((u.nome || "?")[0].toUpperCase())}</div>
    <div style="flex:1"><div class="uc-name">${esc(u.nome)} <span class="role-${u.role}">${esc(u.role)}</span></div>
      <div class="uc-email">${esc(u.email)} · último acesso ${esc(u.ultimo_login)}</div></div>
    <div class="uc-actions admin-only"><button class="btn-edit" onclick='openUserModal(${JSON.stringify(u)})'>Editar</button></div>
  </div>`).join("");
  applyRBAC();
}
let editingUserId = null;
function openUserModal(u) {
  editingUserId = u && u.id ? u.id : null;
  $("mu-title").textContent = editingUserId ? "Editar Usuário" : "Novo Usuário";
  $("mu-nome").value = u ? u.nome : ""; $("mu-email").value = u ? u.email : "";
  $("mu-senha").value = ""; $("mu-role").value = u ? u.role : "leitura";
  $("mu-pass-hint").textContent = editingUserId ? "(deixe em branco p/ manter)" : "";
  openModal("modal-user-overlay");
}
async function saveUser() {
  const body = { nome: $("mu-nome").value, email: $("mu-email").value, role: $("mu-role").value };
  const senha = $("mu-senha").value; if (senha) body.senha = senha;
  try {
    if (editingUserId) await api("/api/users/" + editingUserId, { method: "PATCH", body: JSON.stringify(body) });
    else await api("/api/users", { method: "POST", body: JSON.stringify(body) });
    closeModal("modal-user-overlay"); toast("Usuário salvo"); await loadUsers();
  } catch (e) { toast(e.message, "err"); }
}

// ── BADGES / UI ─────────────────────────────────────────────────────────────
function sgBadge(s) {
  const cls = { "Finalizado": "sg-finalizado", "Em progresso": "sg-progresso", "Pendente": "sg-pendente", "Descontinuado": "sg-pendente" }[s] || "sg-pendente";
  return `<span class="sg-badge ${cls}">${esc(s)}</span>`;
}
function sgDot(d) {
  const ok = d.is_ok; return `<span class="pill ${ok ? "pill-ok" : "pill-warn"}">${esc(d.status || d.fase || "—")}</span>`;
}
function avancoBar(pct) {
  const col = pct >= 80 ? "var(--green)" : pct >= 40 ? "var(--amber)" : "var(--red)";
  return `<div style="display:flex;align-items:center;gap:7px"><div class="prog-track" style="width:70px"><div class="prog-fill" style="width:${pct}%;background:${col}"></div></div><span style="font-size:11px;color:var(--t3)">${pct}%</span></div>`;
}

// ── MODAIS ──────────────────────────────────────────────────────────────────
function openModal(id) { $(id).classList.add("open"); }
function closeModal(id) { $(id).classList.remove("open"); }
document.querySelectorAll(".modal-overlay").forEach((o) => o.addEventListener("click", (e) => { if (e.target === o) closeModal(o.id); }));

// ── TEMA ────────────────────────────────────────────────────────────────────
function toggleTheme() {
  document.body.classList.toggle("theme-light");
  const light = document.body.classList.contains("theme-light");
  $("theme-toggle").textContent = light ? "☀️" : "🌙";
  localStorage.setItem("doctrack_theme", light ? "light" : "dark");
}
if (localStorage.getItem("doctrack_theme") === "light") { document.body.classList.add("theme-light"); }

// ── SOCKET.IO ───────────────────────────────────────────────────────────────
function connectSocket() {
  if (state.socket) return;
  try {
    state.socket = io({ auth: { token: state.token }, transports: ["websocket", "polling"] });
    state.socket.on("connect", () => { $("sync-dot").style.background = "var(--green)"; $("sync-label").textContent = "Conectado"; });
    state.socket.on("disconnect", () => { $("sync-dot").style.background = "var(--amber)"; $("sync-label").textContent = "Reconectando…"; });
    const onChange = (ev) => {
      if (state.page === "dashboard") loadDashboard();
      if (state.page === "apresentacoes" || state.page === "produtos") { loadApres(); loadProdutos(); }
      if (ev && ev.user_email && ev.user_email !== state.user.email) toast("Atualização de " + ev.user_email, "warn");
    };
    ["APRESENTACAO_UPDATED", "APRESENTACAO_CREATED", "PRODUTO_CREATED", "PRODUTO_UPDATED", "REIMPORT"].forEach((e) => state.socket.on(e, onChange));
  } catch (e) { console.warn("socket", e); }
}

// ── BOOT ────────────────────────────────────────────────────────────────────
if (!state.token) { voltarAoLogin(); }
else { enterApp().catch((e) => { console.warn('PDR: sessão inválida, voltando ao login.', e); voltarAoLogin(); }); }
