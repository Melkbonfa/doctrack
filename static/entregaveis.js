/* Entregáveis por Projeto — lógica da página */
const TOKEN_KEY = "doctrack_token";
let _projetos = [], _projAtualId = null, _popEntregavel = null;
let _resumo = null, _projetosAll = [], _charts = {};
let _projChip = "todos";

function token(){ return localStorage.getItem(TOKEN_KEY) || ""; }

// Marca o módulo atual (consistência com o hub de módulos)
sessionStorage.setItem("dt_module", "ent");

async function api(url, opts={}){
  const res = await fetch(url, {...opts, headers: {
    "Content-Type": "application/json",
    "Authorization": "Bearer " + token(),
    ...(opts.headers||{})
  }});
  if (res.status === 401){ window.location.href = "/"; throw new Error("401"); }
  if (!res.ok){
    const body = await res.json().catch(()=>({}));
    throw new Error(body.erro || ("HTTP " + res.status));
  }
  return res.json();
}

function toast(msg, erro=false){
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.style.display = "block";
  t.style.borderColor = erro ? "#ef4444" : "#22d3ee";
  clearTimeout(t._h); t._h = setTimeout(()=> t.style.display="none", 3000);
}

function esc(s){ const d=document.createElement("div"); d.textContent=s??""; return d.innerHTML; }

/* ── Abas ── */
function trocarAba(aba){
  const dash = aba === "dash";
  document.getElementById("aba-dash").style.display = dash ? "" : "none";
  document.getElementById("aba-proj").style.display = dash ? "none" : "";
  document.getElementById("tab-btn-dash").classList.toggle("active", dash);
  document.getElementById("tab-btn-proj").classList.toggle("active", !dash);
  document.getElementById("tab-btn-dash").setAttribute("aria-selected", dash);
  document.getElementById("tab-btn-proj").setAttribute("aria-selected", !dash);
  if (dash){
    // atualizar dados do dashboard ao voltar para a aba
    Promise.all([loadKpis(), loadProjetosAll()])
      .then(renderCharts)
      .catch(e => toast(e.message, true));
  } else {
    // garantir que a grade de projetos esteja carregada/atualizada
    if (_projetos.length){ renderProjChips(); renderProjGrid(); }
    else loadProjetos().catch(e => toast(e.message, true));
  }
}

async function loadProjetosAll(){
  const data = await api("/api/projetos");
  _projetosAll = data.projetos;
}

/* ── Gráficos (Chart.js) — visual idêntico ao app.js do dashboard ── */
const CHART_TXT = "#94a3ff", CHART_GRID = "rgba(167,139,250,.06)";
const TOOLTIP = {
  backgroundColor: "#232847", titleColor: "#f1f5f9", bodyColor: "#c7d2fe",
  borderColor: "rgba(167,139,250,.3)", borderWidth: 1, padding: 10, cornerRadius: 8,
};
function legendHtml(elId, labels, colors, vals){
  const el = document.getElementById(elId);
  if (!el) return;
  el.innerHTML = labels.map((l,i) =>
    `<div class="legend-row" title="${esc(l)}"><span class="legend-dot" style="background:${colors[i]}"></span><span>${esc(l)}</span><span class="legend-val">${vals[i]}</span></div>`
  ).join("");
}

function mkChart(id, config){
  if (_charts[id]) { _charts[id].destroy(); delete _charts[id]; }
  const el = document.getElementById(id);
  if (!el || typeof Chart === "undefined") return;
  _charts[id] = new Chart(el.getContext("2d"), config);
}

function _darken(hex, f){
  const n = parseInt(hex.slice(1), 16);
  const r = Math.round(((n>>16)&255)*f), g = Math.round(((n>>8)&255)*f), b = Math.round((n&255)*f);
  return `rgb(${r},${g},${b})`;
}
function donutGrad(ctx, hex){
  const g = ctx.createLinearGradient(0, 0, 0, 160);
  g.addColorStop(0, hex);
  g.addColorStop(1, _darken(hex, 0.5));
  return g;
}

/* Tooltip HTML externo ao canvas (não corta nem bloqueia a rosca) */
function donutTooltipExternal(context){
  const { chart, tooltip } = context;
  let el = document.getElementById("ent-donut-tip");
  if (!el){
    el = document.createElement("div");
    el.id = "ent-donut-tip";
    el.style.cssText = "position:fixed;pointer-events:none;z-index:9999;opacity:0;transition:opacity .1s ease;background:#232847;border:1px solid rgba(167,139,250,.3);border-radius:8px;padding:7px 10px;font:500 12px/1.2 Inter,system-ui,sans-serif;color:#f1f5f9;white-space:nowrap;box-shadow:0 8px 24px rgba(0,0,0,.45);display:flex;align-items:center;gap:7px";
    document.body.appendChild(el);
  }
  if (!tooltip || tooltip.opacity === 0){ el.style.opacity = "0"; return; }
  const dp = tooltip.dataPoints && tooltip.dataPoints[0];
  if (!dp){ el.style.opacity = "0"; return; }
  const dot = (dp.dataset.dotColors && dp.dataset.dotColors[dp.dataIndex]) || "#22d3ee";
  const body = (tooltip.body && tooltip.body[0] && tooltip.body[0].lines[0]) ||
               (dp.label + ": " + dp.formattedValue);
  el.innerHTML = `<span style="width:9px;height:9px;border-radius:50%;background:${dot};flex-shrink:0"></span><span>${body}</span>`;
  el.style.opacity = "1";
  const rect = chart.canvas.getBoundingClientRect();
  const tw = el.offsetWidth, th = el.offsetHeight;
  let left = rect.left + tooltip.caretX + 14;
  let top = rect.top + tooltip.caretY - th - 8;
  if (left + tw > window.innerWidth - 8) left = window.innerWidth - tw - 8;
  if (top < 8) top = rect.top + tooltip.caretY + 16;
  el.style.left = left + "px";
  el.style.top = top + "px";
}

function renderCharts(){
  if (typeof Chart === "undefined") return;
  const base = {
    responsive: true, maintainAspectRatio: false,
    animation: { duration: 250 },
  };

  /* 1. Donut status */
  if (_resumo){
    const r = _resumo;
    const total = (r.concluidos||0) + (r.em_progresso||0) + (r.pendentes||0);
    const c = document.getElementById("donut-status-center");
    if (c) c.innerHTML = `<div class="donut-center-val">${total}</div><div class="donut-center-lbl">itens</div>`;
    const stLabels = ["Concluídos", "Em progresso", "Pendentes"];
    const stVals = [r.concluidos||0, r.em_progresso||0, r.pendentes||0];
    const stColors = ["#10b981", "#22d3ee", "#f59e0b"];
    legendHtml("legend-status", stLabels, stColors, stVals);
    const elS = document.getElementById("chart-status");
    const stBg = elS ? stColors.map(c => donutGrad(elS.getContext("2d"), c)) : stColors;
    mkChart("chart-status", {
      type: "doughnut",
      data: {
        labels: stLabels,
        datasets: [{
          data: stVals,
          backgroundColor: stBg,
          dotColors: stColors,
          borderWidth: 0, borderRadius: 8, spacing: 3, hoverOffset: 6,
        }],
      },
      options: { ...base, responsive: false, cutout: "78%",
        plugins: { legend: { display: false },
          tooltip: { enabled: false, external: donutTooltipExternal,
            callbacks: { label: (ctx) => ` ${ctx.label}: ${ctx.parsed} entregáveis` } } } },
    });

    /* 3. Carga por responsável */
    const carga = Object.entries(r.por_responsavel||{}).map(([grupo, itens]) => {
      const abertos = (itens||[]).filter(i => i.status === "pendente" || i.status === "em_progresso").length;
      return [grupo, abertos];
    }).filter(([,n]) => n > 0).sort((a,b) => b[1] - a[1]);
    const elCarga = document.getElementById("chart-carga");
    let gradCarga = "#22d3ee";
    if (elCarga){
      const ctxC = elCarga.getContext("2d");
      gradCarga = ctxC.createLinearGradient(0, 0, 0, 240);
      gradCarga.addColorStop(0, "#22d3ee"); gradCarga.addColorStop(1, "#3b82f6");
    }
    mkChart("chart-carga", {
      type: "bar",
      data: {
        labels: carga.map(c2 => c2[0]),
        datasets: [{ data: carga.map(c2 => c2[1]), backgroundColor: gradCarga, borderRadius: 8, borderWidth: 0 }],
      },
      options: { ...base,
        plugins: { legend: { display: false },
          tooltip: { enabled: false, external: donutTooltipExternal,
            callbacks: { label: (ctx) => ` ${ctx.label}: ${ctx.parsed.y} itens em aberto` } } },
        scales: {
          x: { ticks: { color: CHART_TXT, font: { size: 10, family: "Inter" }, autoSkip: false, maxRotation: 45, minRotation: 0 }, grid: { display: false }, border: { display: false } },
          y: { beginAtZero: true, ticks: { color: CHART_TXT, font: { size: 10, family: "Inter" }, precision: 0 }, grid: { color: CHART_GRID }, border: { display: false } },
        } },
    });
  }

  /* 2. Avanço por projeto (top 15) */
  if (_projetosAll.length){
    const ordenados = [..._projetosAll].sort((a,b) => b.avanco - a.avanco);
    const top = ordenados.slice(0, 15);
    const titulo = document.getElementById("title-avanco");
    if (titulo) titulo.textContent = ordenados.length > 15
      ? "Avanço por projeto (top 15)" : "Avanço por projeto";
    const elAvanco = document.getElementById("chart-avanco");
    let gradAvanco = "#22d3ee";
    if (elAvanco){
      const ctxAv = elAvanco.getContext("2d");
      gradAvanco = ctxAv.createLinearGradient(0, 0, 400, 0);
      gradAvanco.addColorStop(0, "#22d3ee"); gradAvanco.addColorStop(1, "#3b82f6");
    }
    mkChart("chart-avanco", {
      type: "bar",
      data: {
        labels: top.map(p => p.nome),
        datasets: [{ data: top.map(p => p.avanco), backgroundColor: gradAvanco, borderRadius: 8, borderWidth: 0 }],
      },
      options: { ...base, indexAxis: "y",
        plugins: { legend: { display: false },
          tooltip: { enabled: false, external: donutTooltipExternal,
            callbacks: { label: (ctx) => ` ${ctx.label}: ${ctx.parsed.x}% concluído` } } },
        scales: {
          x: { min: 0, max: 100, ticks: { color: CHART_TXT, font: { size: 10, family: "Inter" }, callback: (v) => v + "%" }, grid: { color: CHART_GRID }, border: { display: false } },
          y: { ticks: { color: "#c7d2fe", autoSkip: false, font: { size: 11, family: "Inter", weight: "500" } }, grid: { display: false }, border: { display: false } },
        } },
    });

    /* 4. MoSCoW */
    const ordem = ["Must", "Should", "Could", "Won't", "Sem prioridade"];
    const cores = { "Must": "#ef4444", "Should": "#f59e0b", "Could": "#3b82f6", "Won't": "#64748b", "Sem prioridade": "#94a3b8" };
    const moscowLabel = (m) => { const v = normMoscow(m); return v === "Wont" ? "Won't" : (v || "Sem prioridade"); };
    const cont = {};
    _projetosAll.forEach(p => { const k = moscowLabel(p.moscow); cont[k] = (cont[k]||0) + 1; });
    const labels = ordem.filter(m => cont[m]);
    const mColors = labels.map(m => cores[m] || "#94a3b8");
    const mVals = labels.map(m => cont[m]);
    legendHtml("legend-moscow", labels, mColors, mVals);
    const cm = document.getElementById("donut-moscow-center");
    if (cm) cm.innerHTML = `<div class="donut-center-val">${_projetosAll.length}</div><div class="donut-center-lbl">projetos</div>`;
    const elM = document.getElementById("chart-moscow");
    const mBg = elM ? mColors.map(c => donutGrad(elM.getContext("2d"), c)) : mColors;
    mkChart("chart-moscow", {
      type: "doughnut",
      data: {
        labels,
        datasets: [{
          data: mVals,
          backgroundColor: mBg,
          dotColors: mColors,
          borderWidth: 0, borderRadius: 8, spacing: 3, hoverOffset: 6,
        }],
      },
      options: { ...base, responsive: false, cutout: "78%",
        plugins: { legend: { display: false },
          tooltip: { enabled: false, external: donutTooltipExternal,
            callbacks: { label: (ctx) => ` ${ctx.label}: ${ctx.parsed} projeto${ctx.parsed === 1 ? "" : "s"}` } } } },
    });
  }
}

/* ── KPIs ── */
async function loadKpis(){
  const r = await api("/api/entregaveis/resumo");
  _resumo = r;

  const concluidos = r.concluidos || 0, em = r.em_progresso || 0, pend = r.pendentes || 0;
  const total = concluidos + em + pend;

  const ringColors = ["#10b981", "#22d3ee", "#06b6d4"];
  const ringBgs = ["rgba(16,185,129,.15)", "rgba(34,211,238,.15)", "rgba(168,85,247,.15)"];
  const rings = [
    ["Concluídos", concluidos],
    ["Em progresso", em],
    ["Pendentes", pend],
  ];

  document.getElementById("ent-rings").innerHTML = rings.map(([k, v], i) => {
    const pct = total ? Math.round(v / total * 100) : 0;
    return `<div class="kpi-ring">
      <div class="kpi-ring-canvas" style="width:110px;height:110px"><canvas id="ent-ring${i}" width="110" height="110"></canvas><div class="kpi-ring-val" style="color:${ringColors[i]}">${v}</div></div>
      <div class="kpi-ring-label">${esc(k)}</div>
      <div class="kpi-ring-delta" style="color:${ringColors[i]}">${pct}% do total</div>
    </div>`;
  }).join("");

  rings.forEach(([k, v], i) => {
    const pct = total ? v / total : 0;
    mkChart("ent-ring" + i, {
      type: "doughnut",
      data: { datasets: [{ data: [pct * 100, 100 - pct * 100], backgroundColor: [ringColors[i], ringBgs[i]], borderWidth: 0, hoverOffset: 4 }] },
      options: { responsive: false, cutout: "78%", plugins: { legend: { display: false }, tooltip: { enabled: false } }, animation: { animateRotate: true, duration: 1200 } },
    });
  });

  document.getElementById("ent-metrics").innerHTML =
    `<div class="metric-card"><div><div class="metric-value">${r.projetos}</div><div class="metric-label">Projetos ativos</div></div></div>` +
    `<div class="metric-card"><div><div class="metric-value">${r.avanco_medio}%</div><div class="metric-label">Avanço médio</div></div></div>`;
}

/* ── Grade de projetos (mesmo padrão dos equipamentos) ── */
async function loadProjetos(){
  const data = await api("/api/projetos");
  _projetos = data.projetos;
  renderProjChips();
  renderProjGrid();
}

function projMatchesChip(p, chip){
  switch(chip){
    case "todos":     return true;
    case "pendentes": return p.avanco < 35;
    case "andamento": return p.avanco >= 35 && p.avanco < 70;
    case "avancados": return p.avanco >= 70;
    case "must":      return p.moscow === "Must";
    case "compend":   return (p.pendentes || 0) > 0;
    default:          return true;
  }
}

function renderProjChips(){
  const chips = [
    {id:"todos",     label:"Todos"},
    {id:"pendentes", label:"Pendentes"},
    {id:"andamento", label:"Em andamento"},
    {id:"avancados", label:"Avançados"},
    {id:"must",      label:"Must"},
    {id:"compend",   label:"Com pendências"},
  ];
  document.getElementById("proj-chips").innerHTML = chips.map(c => {
    const n = _projetos.filter(p => projMatchesChip(p, c.id)).length;
    const active = _projChip === c.id ? " active" : "";
    return `<button type="button" class="filter-chip${active}" data-chip="${c.id}" onclick="setProjChip('${c.id}')">${esc(c.label)}<span class="chip-count">${n}</span></button>`;
  }).join("");
}

function setProjChip(id){
  _projChip = id;
  renderProjChips();
  renderProjGrid();
}

function renderProjGrid(){
  const q = (document.getElementById("proj-search").value || "").trim().toLowerCase();
  let lista = _projetos.filter(p => projMatchesChip(p, _projChip));
  if (q){
    lista = lista.filter(p =>
      [p.nome, p.sku].join(" ").toLowerCase().includes(q));
  }
  const badge = document.getElementById("proj-badge");
  if (badge) badge.textContent = lista.length + " proj.";
  const grid = document.getElementById("proj-grid");
  if (!lista.length){
    grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;color:var(--t4);padding:32px">Nenhum projeto encontrado</div>';
    return;
  }
  grid.innerHTML = lista.map(p => {
    const cor = p.avanco >= 70 ? "green" : p.avanco >= 35 ? "amber" : "red";
    return `<div class="equip-card proj-card st-${cor}" onclick="abrirProjModal(${p.id})">
      <div class="proj-card-head">
        <span class="proj-card-name">${esc(p.nome)}</span>
        ${moscowBadgeHtml(p.moscow)}
      </div>
      <div class="proj-prog">
        <div class="proj-prog-track"><i style="width:${p.avanco}%"></i></div>
        <div class="proj-prog-meta"><span class="pct">${p.avanco}% concluído</span><span>${p.pendentes} pendente${p.pendentes===1?"":"s"}</span></div>
      </div>
    </div>`;
  }).join("");
}

function normMoscow(m){ const s=(m||"").toLowerCase().replace(/[^a-z]/g,""); return s==="must"?"Must":s==="should"?"Should":s==="could"?"Could":(s==="wont"?"Wont":""); }
function moscowBadgeHtml(m){ const v=normMoscow(m); if(!v) return ""; const lab=v==="Wont"?"WON'T":v.toUpperCase(); return `<span class="moscow-badge mq-${v.toLowerCase()}">${lab}</span>`; }
function userRole(){ try{ return (JSON.parse(localStorage.getItem("doctrack_user")||"{}").role)||""; }catch(e){ return ""; } }
function canEditProj(){ return ["admin","gestor"].includes(userRole()); }

async function salvarMoscow(valor){
  if (!_projAtualId) return;
  try{
    const r = await api("/api/projetos/" + _projAtualId, { method:"PUT", body: JSON.stringify({ moscow: valor }) });
    const novo = r.projeto;
    const idx = _projetos.findIndex(x => x.id === _projAtualId);
    if (idx >= 0 && novo) _projetos[idx] = Object.assign({}, _projetos[idx], novo);
    renderProjGrid();
    toast("Prioridade atualizada");
  }catch(err){ toast(err.message, true); }
}

/* ── Modal de projeto (abas por categoria) ── */
async function abrirProjModal(id){
  _projAtualId = id;
  const p = await api("/api/projetos/" + id);
  document.getElementById("proj-modal-title").textContent = p.nome;
  const partes = [];
  if (p.sku) partes.push("SKU " + esc(p.sku));
  if (p.lancamento) partes.push("Lançamento " + esc(p.lancamento));
  partes.push("Avanço " + p.avanco + "%");
  let moscowHtml;
  if (canEditProj()){
    const v = normMoscow(p.moscow);
    const opts = [["","—"],["Must","Must"],["Should","Should"],["Could","Could"],["Wont","Won't"]]
      .map(([val,lab]) => `<option value="${val}" ${v===val?"selected":""}>${lab}</option>`).join("");
    moscowHtml = `<span class="proj-moscow-edit">Prioridade <select id="proj-moscow-sel" onchange="salvarMoscow(this.value)">${opts}</select></span>`;
  } else {
    moscowHtml = p.moscow ? `MoSCoW ${esc(p.moscow)}` : "";
  }
  const sub = partes.join(" · ") + (moscowHtml ? " · " + moscowHtml : "");
  document.getElementById("proj-modal-sub").innerHTML = sub;

  const cats = (p.categorias || []).filter(c => (c.entregaveis || []).length);
  document.getElementById("proj-modal-tabs").innerHTML = cats.map((c, i) =>
    `<button type="button" class="equip-modal-tab${i===0?" active":""}" data-tab="cat${i}" onclick="switchProjTab('cat${i}')">${esc(c.categoria)}</button>`
  ).join("");
  document.getElementById("proj-modal-panels").innerHTML = cats.map((c, i) =>
    `<div class="equip-tab-panel${i===0?" active":""}" id="proj-panel-cat${i}">${c.entregaveis.map(projRowHtml).join("")}</div>`
  ).join("");

  const m = document.getElementById("modal-projeto");
  m.setAttribute("aria-hidden", "false");
  m.classList.add("open");
}

function projRowHtml(e){
  let badgeCls = "sg-pendente", statusLabel = "Pendente", extra = "";
  if (e.status === "concluido"){ badgeCls = "sg-finalizado"; statusLabel = "Concluído"; }
  else if (e.status === "em_progresso"){ badgeCls = "sg-progresso"; statusLabel = (e.percentual ?? 0) + "%"; }
  else if (e.status === "na"){ badgeCls = "sg-pendente"; statusLabel = "N/A"; extra = ' style="color:var(--t4)"'; }
  return `<div class="ent-row" onclick='abrirPop(${JSON.stringify(e).replace(/'/g,"&#39;")})'>
    <span>${esc(e.tipo)}</span>
    <span class="quem">${esc(e.responsaveis||"—")} <span class="sg-badge ${badgeCls}"${extra}>${statusLabel}</span></span>
  </div>`;
}

function switchProjTab(tab){
  document.querySelectorAll("#proj-modal-tabs .equip-modal-tab")
    .forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll("#proj-modal-panels .equip-tab-panel")
    .forEach(panel => panel.classList.toggle("active", panel.id === "proj-panel-" + tab));
}

function fecharProjModal(){
  const m = document.getElementById("modal-projeto");
  m.classList.remove("open");
  m.setAttribute("aria-hidden", "true");
  _projAtualId = null;
}

/* ── Popover de edição ── */
function abrirPop(e){
  _popEntregavel = e;
  document.getElementById("pop-titulo").textContent = e.tipo;
  document.getElementById("pop-status").value = e.status;
  document.getElementById("pop-pct").value = e.percentual ?? 0;
  document.getElementById("pop-pct-val").textContent = (e.percentual ?? 0) + "%";
  document.getElementById("pop-resp").value = e.responsaveis || "";
  popStatusChange();
  document.getElementById("edit-pop").style.display = "flex";
}
function popStatusChange(){
  const st = document.getElementById("pop-status").value;
  document.getElementById("pop-pct-wrap").style.display =
    st === "em_progresso" ? "block" : "none";
}
function fecharPop(){ document.getElementById("edit-pop").style.display = "none"; _popEntregavel = null; }

async function salvarPop(){
  if (!_popEntregavel) return;
  const payload = {
    status: document.getElementById("pop-status").value,
    responsaveis: document.getElementById("pop-resp").value.trim(),
  };
  if (payload.status === "em_progresso")
    payload.percentual = parseInt(document.getElementById("pop-pct").value, 10);
  try{
    const r = await api("/api/entregaveis/" + _popEntregavel.id, {
      method: "PUT", body: JSON.stringify(payload)});
    toast("Entregável atualizado");
    fecharPop();
    // Recarrega a grade (novo avanço / pendências) e o modal aberto.
    const modalAberto = document.getElementById("modal-projeto").classList.contains("open");
    const idAtual = _projAtualId;
    await loadProjetos().catch(()=>{});
    if (modalAberto && idAtual) abrirProjModal(idAtual).catch(()=>{});
  }catch(err){ toast(err.message, true); }
}

/* ── Export ── */
async function exportarExcel(){
  try{
    const res = await fetch("/api/entregaveis/export", {
      headers: {"Authorization": "Bearer " + token()}});
    if (!res.ok) throw new Error("Falha no export (HTTP " + res.status + ")");
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "Entregaveis.xlsx";
    a.click();
    URL.revokeObjectURL(a.href);
  }catch(err){ toast(err.message, true); }
}

/* ── Fechar modal: clique no overlay + tecla ESC (app.js não está nesta página) ── */
document.getElementById("modal-projeto").addEventListener("click", (e) => {
  if (e.target === e.currentTarget) fecharProjModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (document.getElementById("modal-projeto").classList.contains("open")) fecharProjModal();
  else if (document.getElementById("edit-pop").style.display !== "none") fecharPop();
});

/* ── Init ── */
(async function init(){
  if (!token()){ window.location.href = "/"; return; }
  try{
    await Promise.all([loadKpis(), loadProjetos(), loadProjetosAll()]);
    renderCharts();
  }catch(e){ toast(e.message, true); }
})();
