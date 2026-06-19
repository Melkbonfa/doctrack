/* Entregáveis por Projeto — lógica da página */
const TOKEN_KEY = "doctrack_token";
const CATEGORIAS = ["Produto", "Sistema", "Documentação", "Capacitação", "Marketing"];
const TIPOS_PROJETO = ["OEM", "Revenda"];
let _projetos = [], _projAtualId = null, _popEntregavel = null;
let _resumo = null, _projetosAll = [], _charts = {};
let _projChip = "todos";
let _projSort = "padrao", _formProjId = null, _projDetalheAtual = null;
let _pfEntregaveis = [];   // lista editável de entregáveis na criação de projeto
let _modelosTipoAtual = "OEM";   // tipo selecionado na aba Modelos
let _verArquivados = false;      // grade de projetos mostrando arquivados?
let _fichaProj = null;   // projeto selecionado na ficha do Dashboard

function token(){ return localStorage.getItem(TOKEN_KEY) || ""; }

// ═══ TEMA CLARO/ESCURO (mesma chave de Documentos) ═══
function applyTheme(theme){
  const isLight = theme === "light";
  document.body.classList.toggle("theme-light", isLight);
  const btn = document.getElementById("theme-toggle");
  if (btn) btn.textContent = isLight ? "☀️" : "🌙";
}
function toggleTheme(){
  const next = document.body.classList.contains("theme-light") ? "dark" : "light";
  localStorage.setItem("doctrack_theme", next);
  applyTheme(next);
  _rerenderCharts();   // recolore eixos/legenda dos gráficos conforme o tema
}
/* Re-renderiza os gráficos visíveis (cores de eixo dependem do tema). */
function _rerenderCharts(){
  try{
    if (document.getElementById("aba-dash") && document.getElementById("aba-dash").style.display !== "none"){
      const sel = document.getElementById("dash-proj-sel");
      if (sel && sel.value && _fichaProj) renderFichaProjeto(_fichaProj);
      else renderCharts();
    }
    if (document.getElementById("aba-pmo") && document.getElementById("aba-pmo").style.display !== "none"){
      renderPmoDashboard(); renderFinanceiro();
    }
    if (document.getElementById("modal-projeto").classList.contains("open") && _projDetalheAtual)
      renderPmoSection(_projDetalheAtual);
  }catch(e){}
}
// aplica imediatamente para evitar flash ao carregar a página
applyTheme(localStorage.getItem("doctrack_theme") || "dark");

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

/* ── Confirmação interna (substitui confirm() do navegador) ──
   Uso: if (!(await confirmar("Mensagem", {title, okLabel, danger}))) return; */
let _confirmResolver = null;
function confirmar(msg, opts={}){
  return new Promise(resolve => {
    _confirmResolver = resolve;
    document.getElementById("cf-title").textContent = opts.title || "Confirmar";
    document.getElementById("cf-msg").textContent = msg || "Tem certeza?";
    const ok = document.getElementById("cf-ok");
    ok.textContent = opts.okLabel || "Confirmar";
    const danger = opts.danger !== false;   // padrão: ação destrutiva (vermelho)
    ok.classList.toggle("btn-danger", danger);
    ok.classList.toggle("btn-primary", !danger);
    _abrirModal("modal-confirm-ent");
    setTimeout(() => ok.focus(), 60);
  });
}
function _fecharConfirm(val){
  _fecharModal("modal-confirm-ent");
  const r = _confirmResolver; _confirmResolver = null;
  if (r) r(val);
}

/* ── Abas (Dashboard · PMO · Projetos) ── */
function trocarAba(aba){
  ["dash", "pmo", "proj", "modelos"].forEach(t => {
    const sec = document.getElementById("aba-" + t);
    if (sec) sec.style.display = (t === aba) ? "" : "none";
    const b = document.getElementById("tab-btn-" + t);
    if (b){ b.classList.toggle("active", t === aba); b.setAttribute("aria-selected", t === aba); }
  });
  if (aba === "modelos"){ loadModelos().catch(e => toast(e.message, true)); return; }
  if (aba === "dash"){
    Promise.all([loadKpis(), loadProjetosAll()]).then(() => {
      populateDashProjSel();
      const sel = document.getElementById("dash-proj-sel");
      if (sel && sel.value) setDashProj(sel.value);
      else renderCharts();
    }).catch(e => toast(e.message, true));
  } else if (aba === "pmo"){
    loadProjetosAll().then(() => { renderPmoDashboard(); renderFinanceiro(); })
      .catch(e => toast(e.message, true));
  } else {
    if (_projetos.length){ renderProjChips(); renderProjGrid(); }
    else loadProjetos().catch(e => toast(e.message, true));
  }
}

async function loadProjetosAll(){
  const data = await api("/api/projetos?com_entregaveis=1");
  _projetosAll = data.projetos;
}

/* ── Gráficos (Chart.js) — visual idêntico ao app.js do dashboard ── */
/* Cores de eixo sensíveis ao tema (claro/escuro) */
function _chTxt(){ return document.body.classList.contains("theme-light") ? "#475569" : "#94a3ff"; }
function _chTxtStrong(){ return document.body.classList.contains("theme-light") ? "#1e293b" : "#c7d2fe"; }
function _chGrid(){ return document.body.classList.contains("theme-light") ? "rgba(30,41,99,.10)" : "rgba(167,139,250,.06)"; }
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
          x: { ticks: { color: _chTxt(), font: { size: 10, family: "Inter" }, autoSkip: false, maxRotation: 45, minRotation: 0 }, grid: { display: false }, border: { display: false } },
          y: { beginAtZero: true, ticks: { color: _chTxt(), font: { size: 10, family: "Inter" }, precision: 0 }, grid: { color: _chGrid() }, border: { display: false } },
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
          x: { min: 0, max: 100, ticks: { color: _chTxt(), font: { size: 10, family: "Inter" }, callback: (v) => v + "%" }, grid: { color: _chGrid() }, border: { display: false } },
          y: { ticks: { color: _chTxtStrong(), autoSkip: false, font: { size: 11, family: "Inter", weight: "500" } }, grid: { display: false }, border: { display: false } },
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

/* ── Dashboard PMO: saúde do portfólio + quadrante SPI×CPI ── */
const _PMO_COR = { ok:"#10b981", atencao:"#f59e0b", critico:"#ef4444", sem_dados:"#64748b" };
function _piorStatus(a, b){
  const ordem = { critico:0, atencao:1, ok:2, sem_dados:3 };
  const ra = ordem[a] ?? 3, rb = ordem[b] ?? 3;
  return ra <= rb ? a : b;
}

/* Plugin: linhas-guia em SPI=1 e CPI=1 (divisão dos quadrantes). */
const _quadrantePlugin = { id: "quadGuides", beforeDatasetsDraw(chart){
  const { ctx, chartArea: a, scales } = chart;
  if (!a || !scales.x || !scales.y) return;
  const x1 = scales.x.getPixelForValue(1), y1 = scales.y.getPixelForValue(1);
  ctx.save();
  // tinte do quadrante "bom" (canto superior direito: SPI≥1 e CPI≥1)
  ctx.fillStyle = "rgba(16,185,129,.06)";
  ctx.fillRect(x1, a.top, a.right - x1, y1 - a.top);
  ctx.strokeStyle = "rgba(167,139,250,.35)"; ctx.lineWidth = 1; ctx.setLineDash([5,4]);
  ctx.beginPath(); ctx.moveTo(x1, a.top); ctx.lineTo(x1, a.bottom);
  ctx.moveTo(a.left, y1); ctx.lineTo(a.right, y1); ctx.stroke();
  ctx.restore();
}};

function renderPmoDashboard(){
  const host = document.getElementById("pmo-portfolio");
  if (!host) return;
  const projs = _projetosAll || [];
  const comPrazo = projs.filter(p => p.pmo && p.pmo.spi != null);
  const comCusto = projs.filter(p => p.pmo && p.pmo.cpi != null);
  const vazio = document.getElementById("pmo-empty");

  if (!comPrazo.length && !comCusto.length){
    host.style.display = "none";
    if (vazio){
      vazio.style.display = "";
      vazio.innerHTML = `<div class="evm-empty" style="margin-top:18px;padding:32px">
        Ainda não há dados de PMO. Defina <b>cronograma e orçamento</b> nos projetos e faça
        <b>lançamentos mensais</b> (aba Projetos → abrir um projeto → “+ Lançar mês”) para ver
        saúde de prazo/custo, quadrante SPI×CPI e o financeiro aqui.</div>`;
    }
    return;
  }
  host.style.display = "";
  if (vazio) vazio.style.display = "none";

  // 1) Saúde (contagem por status)
  const cont = (lista, chave) => lista.reduce((acc, p) => {
    const s = p.pmo[chave]; acc[s] = (acc[s]||0)+1; return acc;
  }, {});
  const cPrazo = cont(comPrazo, "status_prazo"), cCusto = cont(comCusto, "status_custo");
  const linhaSaude = (titulo, c, total) => `
    <div class="pmo-health-row">
      <span class="pmo-health-cap">${titulo}</span>
      <span class="pmo-pill pmo-ok"><b>${c.ok||0}</b> no alvo</span>
      <span class="pmo-pill pmo-atencao"><b>${c.atencao||0}</b> atenção</span>
      <span class="pmo-pill pmo-critico"><b>${c.critico||0}</b> crítico</span>
      <span class="pmo-health-tot">${total} proj.</span>
    </div>`;
  document.getElementById("pmo-health").innerHTML =
    linhaSaude("Prazo", cPrazo, comPrazo.length) +
    linhaSaude("Custo", cCusto, comCusto.length);

  // 2) Quadrante SPI×CPI (projetos com ambos os índices)
  const pts = projs.filter(p => p.pmo && p.pmo.spi != null && p.pmo.cpi != null);
  const pontos = pts.map(p => ({ x: p.pmo.spi, y: p.pmo.cpi, nome: p.nome }));
  const cores = pts.map(p => _PMO_COR[_piorStatus(p.pmo.status_prazo, p.pmo.status_custo)]);
  const vals = pontos.flatMap(pt => [pt.x, pt.y]).concat([1]);
  const lo = Math.min(0.6, ...vals) - 0.1, hi = Math.max(1.2, ...vals) + 0.1;
  if (pontos.length){
    mkChart("chart-quadrante", {
      type: "scatter",
      data: { datasets: [{ data: pontos, backgroundColor: cores, pointRadius: 7, pointHoverRadius: 9,
        borderColor: "rgba(13,16,32,.6)", borderWidth: 1.5 }] },
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false },
          tooltip: { ...TOOLTIP, callbacks: {
            title: (items) => items[0].raw.nome,
            label: (ctx) => ` SPI ${ctx.raw.x.toFixed(2)} · CPI ${ctx.raw.y.toFixed(2)}` } } },
        scales: {
          x: { min: lo, max: hi, title: { display: true, text: "Prazo (SPI) →", color: _chTxt(), font: { size: 11, family: "Inter" } },
               ticks: { color: _chTxt(), font: { size: 10, family: "Inter" } }, grid: { color: _chGrid() }, border: { display: false } },
          y: { min: lo, max: hi, title: { display: true, text: "Custo (CPI) →", color: _chTxt(), font: { size: 11, family: "Inter" } },
               ticks: { color: _chTxt(), font: { size: 10, family: "Inter" } }, grid: { color: _chGrid() }, border: { display: false } },
        } },
      plugins: [_quadrantePlugin],
    });
  } else {
    const elq = document.getElementById("chart-quadrante");
    if (elq && _charts["chart-quadrante"]){ _charts["chart-quadrante"].destroy(); delete _charts["chart-quadrante"]; }
  }

  // 3) Lista de projetos em risco (status atenção/crítico em prazo ou custo)
  const risco = projs.filter(p => {
    const m = p.pmo || {};
    return ["atencao","critico"].includes(m.status_prazo) || ["atencao","critico"].includes(m.status_custo);
  }).sort((a,b) => {
    const sev = (m) => Math.min(m.spi ?? 9, m.cpi ?? 9);
    return sev(a.pmo) - sev(b.pmo);
  });
  const rl = document.getElementById("pmo-risk-list");
  if (!risco.length){
    rl.innerHTML = `<div class="evm-empty" style="margin:8px 0">Nenhum projeto em risco. 🎯</div>`;
  } else {
    rl.innerHTML = risco.slice(0, 8).map(p => {
      const m = p.pmo;
      const chips = [];
      if (m.spi != null) chips.push(_pmoChip("Prazo", m.spi, m.status_prazo));
      if (m.cpi != null) chips.push(_pmoChip("Custo", m.cpi, m.status_custo));
      return `<div class="pmo-risk-item" onclick="trocarAba('proj');setTimeout(()=>abrirProjModal(${p.id}),120)">
        <span class="pmo-risk-name">${esc(p.nome)}</span>
        <span class="pmo-risk-chips">${chips.join("")}</span>
      </div>`;
    }).join("");
  }
}

/* ── Painel Financeiro (R$): orçado × gasto × projeção ── */
function renderFinanceiro(){
  const cardsEl = document.getElementById("fin-cards");
  const rankEl = document.getElementById("fin-ranking");
  if (!cardsEl || !rankEl) return;

  const comBac = (_projetosAll || []).filter(p => (p.orcamento || 0) > 0);
  if (!comBac.length){
    cardsEl.innerHTML = "";
    rankEl.innerHTML = `<div class="evm-empty" style="margin:8px 0">Defina o <b>orçamento</b> dos projetos para acompanhar o financeiro.</div>`;
    return;
  }

  let orcado = 0, gasto = 0, eacTotal = 0;
  comBac.forEach(p => {
    const m = p.pmo || {};
    orcado += p.orcamento;
    gasto  += (m.ac != null ? m.ac : 0);
    eacTotal += (m.eac != null ? m.eac : p.orcamento);   // sem custo lançado → assume no orçamento
  });
  const desvio = eacTotal - orcado;                       // >0 estouro projetado · <0 economia
  const desvioPct = orcado ? desvio / orcado : 0;
  const stDesvio = desvioPct <= 0.02 ? "ok" : desvioPct <= 0.10 ? "atencao" : "critico";
  const pctGasto = orcado ? Math.round(gasto / orcado * 100) : 0;

  cardsEl.innerHTML =
    _evmCard("Orçado total (BAC)", _money(orcado), "sem_dados", `${comBac.length} projeto${comBac.length===1?"":"s"}`) +
    _evmCard("Gasto até agora (AC)", _money(gasto), "sem_dados", `${pctGasto}% do orçado`) +
    _evmCard("Custo projetado (EAC)", _money(eacTotal), stDesvio, "estimativa ao final") +
    _evmCard("Desvio projetado", (desvio >= 0 ? "+" : "−") + _money(Math.abs(desvio)).replace("R$ ", "R$ "),
             desvio <= 0 ? "ok" : stDesvio, (desvio >= 0 ? "estouro" : "economia") + ` · ${Math.abs(Math.round(desvioPct*100))}%`);

  // Ranking de estouro projetado (EAC > BAC)
  const estouros = comBac
    .map(p => ({ p, over: (p.pmo && p.pmo.eac != null ? p.pmo.eac : p.orcamento) - p.orcamento }))
    .filter(x => x.over > 0.5)
    .sort((a, b) => b.over - a.over)
    .slice(0, 8);

  if (!estouros.length){
    rankEl.innerHTML = `<div class="evm-empty" style="margin:8px 0">Nenhum estouro de orçamento projetado. 👍</div>`;
    return;
  }
  rankEl.innerHTML = estouros.map(({ p, over }) => {
    const m = p.pmo || {};
    const cpiChip = (m.cpi != null) ? _pmoChip("CPI", m.cpi, m.status_custo) : "";
    return `<div class="fin-rank-item" onclick="trocarAba('proj');setTimeout(()=>abrirProjModal(${p.id}),120)">
      <span class="fin-rank-name">${esc(p.nome)}</span>
      <span class="fin-rank-meta">${cpiChip}<b class="fin-rank-over">+${_money(over)}</b></span>
    </div>`;
  }).join("");
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

/* ── Ficha do projeto no Dashboard (filtro por projeto) ── */
function populateDashProjSel(){
  const sel = document.getElementById("dash-proj-sel");
  if (!sel) return;
  const atual = sel.value;
  const ordenados = [...(_projetosAll || [])].sort((a, b) => a.nome.localeCompare(b.nome, "pt"));
  sel.innerHTML = `<option value="">Todos os projetos</option>` +
    ordenados.map(p => `<option value="${p.id}">${esc(p.nome)}</option>`).join("");
  sel.value = atual;
}

async function setDashProj(id){
  const portfolio = document.getElementById("dash-portfolio");
  const ficha = document.getElementById("dash-ficha");
  const btn = document.getElementById("btn-export-proj");
  if (!id){
    _fichaProj = null;
    if (portfolio) portfolio.style.display = "";
    if (ficha) ficha.style.display = "none";
    if (btn) btn.style.display = "none";
    renderCharts();
    return;
  }
  try{
    const p = await api("/api/projetos/" + id);
    _fichaProj = p;
    if (portfolio) portfolio.style.display = "none";
    if (ficha) ficha.style.display = "";
    if (btn) btn.style.display = "";
    renderFichaProjeto(p);
  }catch(e){ toast(e.message, true); }
}

/* Rosca de status reutilizável (entregáveis de um projeto). */
function renderStatusDonut(conc, prog, pend, canvasId, centerId, legendId){
  const labels = ["Concluídos", "Em progresso", "Pendentes"];
  const vals = [conc, prog, pend], colors = ["#10b981", "#22d3ee", "#f59e0b"];
  const total = conc + prog + pend;
  const c = document.getElementById(centerId);
  if (c) c.innerHTML = `<div class="donut-center-val">${total}</div><div class="donut-center-lbl">itens</div>`;
  if (legendId) legendHtml(legendId, labels, colors, vals);
  const el = document.getElementById(canvasId);
  if (!el || typeof Chart === "undefined") return;
  const bg = colors.map(col => donutGrad(el.getContext("2d"), col));
  mkChart(canvasId, {
    type: "doughnut",
    data: { labels, datasets: [{ data: vals, backgroundColor: bg, dotColors: colors,
      borderWidth: 0, borderRadius: 8, spacing: 3, hoverOffset: 6 }] },
    options: { responsive: false, cutout: "78%", animation: { duration: 250 },
      plugins: { legend: { display: false },
        tooltip: { enabled: false, external: donutTooltipExternal,
          callbacks: { label: (ctx) => ` ${ctx.label}: ${ctx.parsed}` } } } },
  });
}

function renderFichaProjeto(p){
  const host = document.getElementById("dash-ficha");
  if (!host) return;
  const m = p.pmo || {};
  const flat = (p.categorias || []).flatMap(c => c.entregaveis || []);
  let conc = 0, prog = 0, pend = 0;
  flat.forEach(e => { if (e.status === "concluido") conc++; else if (e.status === "em_progresso") prog++; else if (e.status === "pendente") pend++; });
  const aplic = conc + prog + pend;
  const periodo = periodoProjeto(p);
  const sub = [];
  if (p.sku) sub.push("SKU " + esc(p.sku));
  if (periodo) sub.push("Prazo " + esc(periodo));
  if (m.bac) sub.push("Orçado " + _money(m.bac));

  const kpis = [
    _evmCard("Avanço", p.avanco + "%", "sem_dados", aplic + " entregáveis"),
    _evmCard("Prazo (SPI)", m.spi != null ? m.spi.toFixed(2) : "—", m.status_prazo,
      m.pct_prazo_decorrido != null ? m.pct_prazo_decorrido + "% do prazo" : "sem cronograma"),
    _evmCard("Custo (CPI)", m.cpi != null ? m.cpi.toFixed(2) : "—", m.status_custo,
      m.bac ? "orçado " + _money(m.bac) : "sem orçamento"),
    _evmCard("Custo projetado (EAC)", m.eac != null ? _money(m.eac) : "—", m.status_custo,
      (m.eac != null && m.bac) ? ((m.eac > m.bac ? "+" : "") + _money(m.eac - m.bac) + " vs orçado") : "—"),
    _evmCard("Pendências", String(p.pendentes), p.pendentes > 0 ? "atencao" : "ok", "a concluir"),
  ];

  const curMes = (new Date()).toISOString().slice(0, 7);
  const custos = (p.serie_mensal || []).filter(s => s.custo_acumulado != null);
  const custoTabela = custos.length
    ? `<table class="evm-table"><thead><tr><th>Mês</th><th class="num">Custo acumulado</th></tr></thead><tbody>${custos.map(s => `<tr><td>${_fmtComp(s.competencia)}</td><td class="num">${_money(s.custo_acumulado)}</td></tr>`).join("")}</tbody></table>`
    : `<div class="evm-empty">Nenhum custo lançado. Use a aba Projetos → abrir o projeto → “+ Lançar custo”.</div>`;

  const tarefas = (p.categorias || []).filter(c => (c.entregaveis || []).length).map(c =>
    `<div class="ficha-cat"><div class="ficha-cat-title">${esc(c.categoria)}</div>${c.entregaveis.map(projRowHtml).join("")}</div>`).join("");

  host.innerHTML = `
    <div class="ficha-head">
      <div>
        <div class="ficha-title">${esc(p.nome)} ${moscowBadgeHtml(p.moscow)}</div>
        <div class="ficha-sub">${sub.join(" · ") || "Sem cronograma/orçamento definidos"}</div>
      </div>
      ${pmoChipsHtml(p)}
    </div>
    <div class="evm-cards ficha-kpis">${kpis.join("")}</div>
    <div class="ent-charts ficha-charts">
      <div class="card"><div class="card-title">Curva-S · previsto × realizado</div>
        <div class="evm-curve-wrap" style="height:240px"><canvas id="curva-s-ficha" role="img" aria-label="Curva-S do projeto"></canvas></div></div>
      <div class="card"><div class="card-title">Status dos entregáveis</div>
        <div class="donut-wrap"><div class="donut-canvas-wrap">
          <canvas id="donut-ficha" width="160" height="160" role="img" aria-label="Status dos entregáveis"></canvas>
          <div class="donut-center" id="donut-ficha-center"></div></div>
          <div class="legend-list" id="legend-ficha"></div></div></div>
    </div>
    <div class="card"><div class="card-title">Custos lançados</div>${custoTabela}</div>
    <div class="card">
      <div class="evm-mensal-head"><span class="card-title" style="margin:0">Visão por período</span>
        <span class="periodo-ctrl"><input type="month" id="perf-de" value="${curMes}" onchange="renderPeriodo('perf')"><span class="muted">até</span><input type="month" id="perf-ate" value="${curMes}" onchange="renderPeriodo('perf')"></span>
      </div>
      <div id="periodo-result-f"></div>
    </div>
    <div class="card"><div class="card-title">Entregáveis por categoria</div>${tarefas || '<div class="evm-empty">Sem entregáveis.</div>'}</div>`;

  renderCurvaS(p.serie_mensal || [], "curva-s-ficha");
  renderStatusDonut(conc, prog, pend, "donut-ficha", "donut-ficha-center", "legend-ficha");
  renderPeriodo("perf");
}

/* ── Grade de projetos (mesmo padrão dos equipamentos) ── */
async function loadProjetos(){
  const data = await api("/api/projetos" + (_verArquivados ? "?arquivados=1" : ""));
  _projetos = data.projetos;
  renderProjChips();
  renderProjGrid();
}

function toggleArquivados(){
  _verArquivados = !_verArquivados;
  const btn = document.getElementById("btn-arquivados");
  if (btn){
    btn.textContent = _verArquivados ? "← Voltar aos ativos" : "Ver arquivados";
    btn.classList.toggle("btn-primary", _verArquivados);
    btn.classList.toggle("btn-ghost", !_verArquivados);
    btn.setAttribute("aria-pressed", _verArquivados ? "true" : "false");
  }
  const novo = document.getElementById("btn-novo-proj");
  if (novo && canEditProj()) novo.style.display = _verArquivados ? "none" : "";
  loadProjetos().catch(e => toast(e.message, true));
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

function setProjSort(v){ _projSort = v; renderProjGrid(); }

/* timestamp do lançamento (aceita ISO yyyy-mm-dd, dd/mm/aaaa ou só o ano) */
function _lancTs(s){
  if (!s) return -Infinity;
  let m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (m) return new Date(+m[1], +m[2]-1, +m[3]).getTime();
  m = /^(\d{2})\/(\d{2})\/(\d{4})/.exec(s);
  if (m) return new Date(+m[3], +m[2]-1, +m[1]).getTime();
  m = /(\d{4})/.exec(s);
  if (m) return new Date(+m[1], 0, 1).getTime();
  return -Infinity;
}
/* lançamento ISO -> dd/mm/aaaa; texto livre é mantido como veio */
function fmtLanc(s){
  if (!s) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : s;
}
/* qualquer formato -> ISO yyyy-mm-dd para o <input type=date> (vazio se for texto livre) */
function _toIso(s){
  if (!s) return "";
  let m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (m) return `${m[1]}-${m[2]}-${m[3]}`;
  m = /^(\d{2})\/(\d{2})\/(\d{4})/.exec(s);
  if (m) return `${m[3]}-${m[2]}-${m[1]}`;
  return "";
}

/* Previsto (baseline linear) pelas datas do projeto, espelha o backend. */
function _previstoEm(p, comp){
  const mm = /^(\d{4})-(\d{2})$/.exec(comp || "");
  if (!mm) return null;
  const ini = _toIso(p.data_inicio_prev) || _toIso(p.data_inicio_real);
  const fim = _toIso(p.data_fim_prev);
  if (!ini || !fim) return null;
  const di = new Date(ini + "T00:00:00"), df = new Date(fim + "T00:00:00");
  if (df <= di) return null;
  const ref = new Date(+mm[1], +mm[2], 0);   // último dia do mês da competência
  if (ref <= di) return 0;
  if (ref >= df) return 100;
  return Math.round((ref - di) / (df - di) * 100);
}

function sortProjetos(list){
  const a = [...list], byNome = (x,y) => x.nome.localeCompare(y.nome, "pt");
  switch (_projSort){
    case "nome":        a.sort(byNome); break;
    case "avanco_desc": a.sort((x,y) => y.avanco - x.avanco || byNome(x,y)); break;
    case "avanco_asc":  a.sort((x,y) => x.avanco - y.avanco || byNome(x,y)); break;
    case "pend_desc":   a.sort((x,y) => (y.pendentes||0) - (x.pendentes||0) || byNome(x,y)); break;
    case "lancamento":  a.sort((x,y) => _lancTs(y.lancamento) - _lancTs(x.lancamento) || byNome(x,y)); break;
    default:            a.sort((x,y) => (x.prioridade||999) - (y.prioridade||999) || byNome(x,y));
  }
  return a;
}

function renderProjGrid(){
  const q = (document.getElementById("proj-search").value || "").trim().toLowerCase();
  let lista = _projetos.filter(p => projMatchesChip(p, _projChip));
  if (q){
    lista = lista.filter(p =>
      [p.nome, p.sku].join(" ").toLowerCase().includes(q));
  }
  lista = sortProjetos(lista);
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
        ${_verArquivados ? '<span class="proj-arch-tag">Arquivado</span>' : moscowBadgeHtml(p.moscow)}
      </div>
      <div class="proj-prog">
        <div class="proj-prog-track"><i style="width:${p.avanco}%"></i></div>
        <div class="proj-prog-meta"><span class="pct">${p.avanco}% concluído</span><span>${p.pendentes} pendente${p.pendentes===1?"":"s"}</span></div>
      </div>
      ${pmoChipsHtml(p)}
    </div>`;
  }).join("");
}

/* ── Selos PMO (prazo/custo) ── */
const PMO_CLS = { ok:"pmo-ok", atencao:"pmo-atencao", critico:"pmo-critico", sem_dados:"pmo-neutro" };
function _pmoChip(label, valor, status){
  const cls = PMO_CLS[status] || "pmo-neutro";
  const val = (valor != null) ? ` <b>${valor.toFixed(2)}</b>` : "";
  return `<span class="pmo-chip ${cls}" title="${esc(label)}${val? ' = '+valor.toFixed(2):''}"><span class="pmo-dot"></span>${esc(label)}${val}</span>`;
}
/* Chips compactos para o card: só mostra quando há dado relevante. */
function pmoChipsHtml(p){
  const m = p.pmo || {};
  const chips = [];
  if (m.spi != null) chips.push(_pmoChip("Prazo", m.spi, m.status_prazo));
  else if (m.pct_prazo_decorrido != null) chips.push(`<span class="pmo-chip pmo-neutro"><span class="pmo-dot"></span>Prazo ${m.pct_prazo_decorrido}% decorrido</span>`);
  if (m.cpi != null) chips.push(_pmoChip("Custo", m.cpi, m.status_custo));
  return chips.length ? `<div class="pmo-chips">${chips.join("")}</div>` : "";
}
/* Texto curto do período do projeto (início → fim previstos). */
function periodoProjeto(p){
  const a = fmtLanc(p.data_inicio_real || p.data_inicio_prev), b = fmtLanc(p.data_fim_real || p.data_fim_prev);
  if (a && b) return `${a} → ${b}`;
  return a || b || "";
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
  _projDetalheAtual = p;
  document.getElementById("proj-modal-title").textContent = p.nome;
  const arquivado = p.ativo === false;
  const editBtn = document.getElementById("proj-modal-edit");
  if (editBtn) editBtn.style.display = (canEditProj() && !arquivado) ? "" : "none";
  const addBtn = document.getElementById("proj-modal-add-ent");
  if (addBtn) addBtn.style.display = (canEditProj() && !arquivado) ? "" : "none";
  const restoreBtn = document.getElementById("proj-modal-restore");
  if (restoreBtn) restoreBtn.style.display = (canEditProj() && arquivado) ? "" : "none";
  const partes = [];
  if (p.tipo) partes.push(esc(p.tipo));
  if (p.sku) partes.push("SKU " + esc(p.sku));
  if (p.lancamento) partes.push("Lançamento " + esc(fmtLanc(p.lancamento)));
  const periodo = periodoProjeto(p);
  if (periodo) partes.push("Prazo " + esc(periodo));
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

  renderPmoSection(p);

  const m = document.getElementById("modal-projeto");
  m.setAttribute("aria-hidden", "false");
  m.classList.add("open");
}

/* ── Bloco PMO no modal: indicadores EVM + Curva-S + lançamentos mensais ── */
function _money(v){ const n = Number(v)||0; return "R$ " + n.toLocaleString("pt-BR",{minimumFractionDigits:0, maximumFractionDigits:0}); }
function _fmtComp(c){ const m=/^(\d{4})-(\d{2})$/.exec(c||""); return m ? `${m[2]}/${m[1]}` : (c||""); }

function _evmCard(label, valor, status, hint){
  const cls = PMO_CLS[status] || "pmo-neutro";
  return `<div class="evm-card ${cls}">
    <div class="evm-val">${valor}</div>
    <div class="evm-lbl">${esc(label)}</div>
    ${hint ? `<div class="evm-hint">${esc(hint)}</div>` : ""}
  </div>`;
}

function renderPmoSection(p){
  const host = document.getElementById("proj-pmo");
  if (!host) return;
  const m = p.pmo || {};
  const serie = p.serie_mensal || [];
  const podeEditar = canEditProj();

  // 1) Cartões EVM
  const cards = [];
  cards.push(_evmCard("Prazo (SPI)", m.spi != null ? m.spi.toFixed(2) : "—", m.status_prazo,
    m.pct_prazo_decorrido != null ? `${m.pct_prazo_decorrido}% do prazo` : "sem cronograma"));
  cards.push(_evmCard("Custo (CPI)", m.cpi != null ? m.cpi.toFixed(2) : "—", m.status_custo,
    m.bac ? `Orçado ${_money(m.bac)}` : "sem orçamento"));
  cards.push(_evmCard("Previsto × Real", (m.pct_previsto != null ? m.pct_previsto : "—") + "% / " + (m.pct_realizado != null ? m.pct_realizado : "—") + "%",
    m.status_prazo, m.competencia ? "em " + _fmtComp(m.competencia) : "sem lançamento"));
  cards.push(_evmCard("Custo projetado (EAC)", m.eac != null ? _money(m.eac) : "—", m.status_custo,
    (m.eac != null && m.bac) ? ((m.eac > m.bac ? "+" : "") + _money(m.eac - m.bac) + " vs orçado") : "—"));

  // 2) Cabeçalho da seção de lançamentos
  const btnNovo = podeEditar
    ? `<button class="btn btn-primary btn-sm" onclick="abrirModalMensal()">+ Lançar custo</button>` : "";

  // 3) Tabela de lançamentos
  let tabela;
  if (serie.length){
    const linhas = serie.map(r => {
      const onclk = podeEditar ? ` onclick='abrirModalMensal(${JSON.stringify(r).replace(/'/g,"&#39;")})' style="cursor:pointer"` : "";
      return `<tr${onclk}>
        <td>${_fmtComp(r.competencia)}</td>
        <td class="num">${r.pct_previsto == null ? "—" : r.pct_previsto + "%"}</td>
        <td class="num">${r.pct_realizado == null ? "—" : r.pct_realizado + "%"}</td>
        <td class="num">${r.custo_mes == null ? "—" : _money(r.custo_mes)}</td>
        <td class="num">${r.custo_acumulado == null ? "—" : _money(r.custo_acumulado)}</td>
      </tr>`;
    }).join("");
    tabela = `<table class="evm-table"><thead><tr><th>Mês</th><th class="num">Previsto</th><th class="num">Realizado</th><th class="num">Custo do mês</th><th class="num">Custo acum.</th></tr></thead><tbody>${linhas}</tbody></table>`;
  } else {
    tabela = `<div class="evm-empty">Nenhum lançamento mensal ainda${podeEditar ? " — comece em <b>+ Lançar mês</b>." : "."}</div>`;
  }

  const curMes = (new Date()).toISOString().slice(0,7);
  host.innerHTML = `
    <div class="evm-cards">${cards.join("")}</div>
    <div class="evm-curve-wrap"><canvas id="curva-s" role="img" aria-label="Curva-S: previsto x realizado"></canvas></div>
    <div class="evm-mensal-head"><span class="evm-mensal-title">Acompanhamento mensal (custo)</span>${btnNovo}</div>
    ${tabela}
    <div class="evm-mensal-head"><span class="evm-mensal-title">Visão por período</span>
      <span class="periodo-ctrl">
        <input type="month" id="per-de" value="${curMes}" onchange="renderPeriodo()">
        <span class="muted">até</span>
        <input type="month" id="per-ate" value="${curMes}" onchange="renderPeriodo()">
      </span>
    </div>
    <div id="periodo-result"></div>`;

  renderCurvaS(serie);
  renderPeriodo();
}

/* Tarefas iniciadas / concluídas dentro do intervalo escolhido (client-side). */
function renderPeriodo(prefix){
  prefix = prefix || "per";
  const proj = prefix === "perf" ? _fichaProj : _projDetalheAtual;
  const host = document.getElementById(prefix === "perf" ? "periodo-result-f" : "periodo-result");
  if (!host || !proj) return;
  const de = (document.getElementById(prefix+"-de")||{}).value || "";
  const ate = (document.getElementById(prefix+"-ate")||{}).value || "";
  const flat = (proj.categorias || []).flatMap(c => c.entregaveis || []);
  const ym = (iso) => { const m = /^(\d{4})-(\d{2})/.exec(iso||""); return m ? m[1]+"-"+m[2] : null; };
  const inRange = (iso) => { const k = ym(iso); return k && (!de || k >= de) && (!ate || k <= ate); };
  const concl = flat.filter(e => inRange(e.data_conclusao));
  const inic  = flat.filter(e => inRange(e.data_inicio) && e.status !== "concluido");

  const lista = (arr, campo) => arr.length
    ? arr.map(e => `<div class="per-item"><span>${esc(e.tipo)}</span><span class="per-data">${fmtLanc(e[campo])}</span></div>`).join("")
    : `<div class="per-vazio">—</div>`;

  host.innerHTML = `
    <div class="periodo-cols">
      <div class="periodo-col">
        <div class="periodo-col-head"><b>${concl.length}</b> concluída${concl.length===1?"":"s"}</div>
        ${lista(concl, "data_conclusao")}
      </div>
      <div class="periodo-col">
        <div class="periodo-col-head"><b>${inic.length}</b> em andamento (iniciada${inic.length===1?"":"s"})</div>
        ${lista(inic, "data_inicio")}
      </div>
    </div>`;
}

function renderCurvaS(serie, canvasId="curva-s"){
  const el = document.getElementById(canvasId);
  if (!el || typeof Chart === "undefined") return;
  if (_charts[canvasId]){ _charts[canvasId].destroy(); delete _charts[canvasId]; }
  if (!serie.length){
    const ctx = el.getContext("2d");
    ctx.clearRect(0,0,el.width,el.height);
    return;
  }
  const labels = serie.map(r => _fmtComp(r.competencia));
  const prev = serie.map(r => r.pct_previsto);
  const real = serie.map(r => r.pct_realizado);
  _charts[canvasId] = new Chart(el.getContext("2d"), {
    type: "line",
    data: { labels, datasets: [
      { label: "Previsto", data: prev, borderColor: "#22d3ee", backgroundColor: "rgba(34,211,238,.08)",
        borderDash: [6,4], borderWidth: 2, pointRadius: 3, pointBackgroundColor: "#22d3ee", tension: .25, fill: false },
      { label: "Realizado", data: real, borderColor: "#10b981", backgroundColor: "rgba(16,185,129,.12)",
        borderWidth: 2.5, pointRadius: 3, pointBackgroundColor: "#10b981", tension: .25, fill: true },
    ]},
    options: { responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: true, position: "top", align: "end",
        labels: { color: _chTxtStrong(), font: { size: 11, family: "Inter" }, boxWidth: 12, boxHeight: 12, usePointStyle: true } },
        tooltip: { ...TOOLTIP, callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${ctx.parsed.y}%` } } },
      scales: {
        x: { ticks: { color: _chTxt(), font: { size: 10, family: "Inter" } }, grid: { display: false }, border: { display: false } },
        y: { min: 0, max: 100, ticks: { color: _chTxt(), font: { size: 10, family: "Inter" }, callback: (v) => v + "%" }, grid: { color: _chGrid() }, border: { display: false } },
      } },
  });
}

function projRowHtml(e){
  let badgeCls = "sg-pendente", statusLabel = "Pendente", extra = "";
  if (e.status === "concluido"){ badgeCls = "sg-finalizado"; statusLabel = "Concluído"; }
  else if (e.status === "em_progresso"){ badgeCls = "sg-progresso"; statusLabel = (e.percentual ?? 0) + "%"; }
  else if (e.status === "na"){ badgeCls = "sg-pendente"; statusLabel = "N/A"; extra = ' style="color:var(--t4)"'; }
  const delBtn = canEditProj()
    ? `<button type="button" class="ent-row-del" title="Excluir entregável" aria-label="Excluir entregável" onclick='event.stopPropagation();excluirEntregavel(${e.id}, ${JSON.stringify(e.tipo)})'>✕</button>`
    : "";
  return `<div class="ent-row" onclick='abrirPop(${JSON.stringify(e).replace(/'/g,"&#39;")})'>
    <span>${esc(e.tipo)}</span>
    <span class="quem">${esc(e.responsaveis||"—")} <span class="sg-badge ${badgeCls}"${extra}>${statusLabel}</span>${delBtn}</span>
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
  _projDetalheAtual = null;
}

/* ── Criar / Editar / Arquivar projeto ── */
function _abrirModal(id){ const m = document.getElementById(id); m.classList.add("open"); m.setAttribute("aria-hidden", "false"); }
function _fecharModal(id){ const m = document.getElementById(id); m.classList.remove("open"); m.setAttribute("aria-hidden", "true"); }

function _fmtMoeda(v){
  const n = Number(v) || 0;
  return n ? n.toLocaleString("pt-BR", {minimumFractionDigits: 2, maximumFractionDigits: 2}) : "";
}

/* "15.000,50" | "15000.50" | "15000" → Number (formato pt-BR ou simples). */
function _parseMoeda(s){
  if (s == null) return 0;
  let t = String(s).trim().replace(/[R$\s]/g, "");
  if (!t) return 0;
  if (t.includes(",")) t = t.replace(/\./g, "").replace(",", ".");  // pt-BR
  const n = parseFloat(t);
  return isNaN(n) ? 0 : n;
}

function _preencherForm(p){
  document.getElementById("pf-nome").value = p ? (p.nome || "") : "";
  document.getElementById("pf-tipo").value = p ? (p.tipo || "") : "";
  document.getElementById("pf-sku").value = p ? (p.sku || "") : "";
  document.getElementById("pf-lancamento").value = p ? _toIso(p.lancamento) : "";
  document.getElementById("pf-moscow").value = p ? (normMoscow(p.moscow) || "") : "";
  document.getElementById("pf-desc").value = p ? (p.descricao || "") : "";
  document.getElementById("pf-inicio-prev").value = p ? _toIso(p.data_inicio_prev) : "";
  document.getElementById("pf-fim-prev").value    = p ? _toIso(p.data_fim_prev) : "";
  document.getElementById("pf-inicio-real").value = p ? _toIso(p.data_inicio_real) : "";
  document.getElementById("pf-fim-real").value    = p ? _toIso(p.data_fim_real) : "";
  document.getElementById("pf-orcamento").value   = p ? _fmtMoeda(p.orcamento) : "";
}

/* Preenche um <select> com as categorias de entregável. */
function _fillCatSelect(id, sel){
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = CATEGORIAS.map(c => `<option value="${c}" ${c===sel?"selected":""}>${c}</option>`).join("");
}

/* ── Editor de entregáveis na criação de projeto ── */
function pfRenderEntList(){
  const host = document.getElementById("pf-ent-list");
  const cnt = document.getElementById("pf-ent-count");
  if (cnt) cnt.textContent = _pfEntregaveis.length + (_pfEntregaveis.length === 1 ? " item" : " itens");
  if (!host) return;
  if (!_pfEntregaveis.length){
    host.innerHTML = `<div class="per-vazio" style="padding:8px 0">Nenhum entregável — adicione abaixo ou escolha um tipo.</div>`;
    return;
  }
  host.innerHTML = _pfEntregaveis.map((e, i) =>
    `<div class="pf-ent-row">
      <span class="pf-ent-cat">${esc(e.categoria)}</span>
      <span class="pf-ent-nome">${esc(e.tipo)}</span>
      <button type="button" class="pf-ent-del" title="Remover" aria-label="Remover entregável" onclick="pfRemoveEntregavel(${i})">✕</button>
    </div>`).join("");
}

function pfAddEntregavel(){
  const nome = document.getElementById("pf-ent-nome").value.trim();
  const cat = document.getElementById("pf-ent-cat").value || "Produto";
  if (!nome){ toast("Informe o nome do entregável", true); return; }
  _pfEntregaveis.push({ tipo: nome, categoria: cat, responsaveis: "" });
  document.getElementById("pf-ent-nome").value = "";
  pfRenderEntList();
}

function pfRemoveEntregavel(i){
  _pfEntregaveis.splice(i, 1);
  pfRenderEntList();
}

/* Ao escolher o tipo na criação: carrega a lista-padrão do modelo (substitui a atual). */
async function onTipoProjetoChange(){
  if (_formProjId) return;   // edição não recarrega template
  const tipo = document.getElementById("pf-tipo").value;
  const hint = document.getElementById("pf-ent-hint");
  if (!tipo){
    _pfEntregaveis = [];
    if (hint) hint.textContent = "Escolha o tipo para carregar a lista-padrão. Você pode remover ou adicionar itens antes de criar.";
    pfRenderEntList();
    return;
  }
  try{
    const data = await api("/api/modelos?tipo=" + encodeURIComponent(tipo));
    const itens = (data.modelos && data.modelos[tipo]) || [];
    _pfEntregaveis = itens.map(m => ({ tipo: m.tipo, categoria: m.categoria, responsaveis: m.responsavel_padrao || "" }));
    if (hint) hint.textContent = `Lista-padrão de ${tipo} carregada. Remova ou adicione itens antes de criar.`;
    pfRenderEntList();
  }catch(err){ toast(err.message, true); }
}

function abrirFormProjeto(){
  _formProjId = null;
  document.getElementById("pf-title").textContent = "Novo projeto";
  _preencherForm(null);
  document.getElementById("pf-arquivar").style.display = "none";
  // Editor de entregáveis: só na criação
  _pfEntregaveis = [];
  _fillCatSelect("pf-ent-cat", "Produto");
  document.getElementById("pf-tipo").disabled = false;
  document.getElementById("pf-ent-wrap").style.display = "";
  pfRenderEntList();
  _abrirModal("modal-proj-form");
  setTimeout(() => document.getElementById("pf-nome").focus(), 60);
}

function editarProjetoAtual(){
  const p = _projDetalheAtual;
  if (!p) return;
  _formProjId = p.id;
  document.getElementById("pf-title").textContent = "Editar projeto";
  _preencherForm(p);
  document.getElementById("pf-arquivar").style.display = "";
  // Na edição não mexemos na lista de entregáveis (isso é feito no detalhe)
  document.getElementById("pf-tipo").disabled = false;
  document.getElementById("pf-ent-wrap").style.display = "none";
  _abrirModal("modal-proj-form");
}

function fecharFormProjeto(){ _fecharModal("modal-proj-form"); _formProjId = null; }

async function _recarregarTudo(){
  await Promise.all([
    loadProjetos().catch(()=>{}),
    loadKpis().catch(()=>{}),
    loadProjetosAll().catch(()=>{}),
  ]);
  renderCharts();
}

async function salvarFormProjeto(){
  const nome = document.getElementById("pf-nome").value.trim();
  if (!nome){ toast("Informe o nome do projeto", true); return; }
  const payload = {
    nome,
    tipo: document.getElementById("pf-tipo").value,               // "" | OEM | Revenda
    sku: document.getElementById("pf-sku").value.trim(),
    lancamento: document.getElementById("pf-lancamento").value,   // ISO yyyy-mm-dd ou ""
    moscow: document.getElementById("pf-moscow").value,           // "" | Must | Should | Could | Wont
    descricao: document.getElementById("pf-desc").value.trim(),
    data_inicio_prev: document.getElementById("pf-inicio-prev").value,
    data_fim_prev:    document.getElementById("pf-fim-prev").value,
    data_inicio_real: document.getElementById("pf-inicio-real").value,
    data_fim_real:    document.getElementById("pf-fim-real").value,
    orcamento:        document.getElementById("pf-orcamento").value,   // backend aceita "1.234,56"
  };
  try{
    if (_formProjId){
      await api("/api/projetos/" + _formProjId, { method: "PUT", body: JSON.stringify(payload) });
      toast("Projeto atualizado");
    } else {
      payload.entregaveis = _pfEntregaveis;   // lista já editada no modal
      await api("/api/projetos", { method: "POST", body: JSON.stringify(payload) });
      toast("Projeto criado");
    }
    fecharFormProjeto();
    fecharProjModal();
    await _recarregarTudo();
  }catch(err){ toast(err.message, true); }
}

async function arquivarProjetoAtual(){
  if (!_formProjId) return;
  if (!(await confirmar("Arquivar este projeto? Ele sai das listas, mas pode ser restaurado depois em “Ver arquivados”.",
        {title:"Arquivar projeto", okLabel:"Arquivar"}))) return;
  try{
    await api("/api/projetos/" + _formProjId, { method: "DELETE" });
    toast("Projeto arquivado");
    fecharFormProjeto();
    fecharProjModal();
    await _recarregarTudo();
  }catch(err){ toast(err.message, true); }
}

async function restaurarProjetoAtual(){
  if (!_projAtualId) return;
  if (!(await confirmar("Restaurar este projeto? Ele volta a aparecer nas listas de projetos ativos.",
        {title:"Restaurar projeto", okLabel:"Restaurar", danger:false}))) return;
  try{
    await api("/api/projetos/" + _projAtualId + "/restaurar", { method: "POST" });
    toast("Projeto restaurado");
    fecharProjModal();
    await loadProjetos();      // recarrega a visão atual (arquivados)
    _recarregarTudo().catch(()=>{});
  }catch(err){ toast(err.message, true); }
}

/* ── Entregáveis do projeto: adicionar / excluir (no detalhe) ── */
function abrirFormEntregavel(){
  if (!_projAtualId) return;
  // categoria padrão = aba ativa no detalhe, se houver
  const tabAtiva = document.querySelector("#proj-modal-tabs .equip-modal-tab.active");
  const catAtual = (tabAtiva && tabAtiva.textContent.trim()) || "Produto";
  _fillCatSelect("ef-cat", CATEGORIAS.includes(catAtual) ? catAtual : "Produto");
  document.getElementById("ef-nome").value = "";
  document.getElementById("ef-resp").value = "";
  _abrirModal("modal-ent-form");
  setTimeout(() => document.getElementById("ef-nome").focus(), 60);
}

function fecharFormEntregavel(){ _fecharModal("modal-ent-form"); }

async function salvarFormEntregavel(){
  if (!_projAtualId) return;
  const nome = document.getElementById("ef-nome").value.trim();
  if (!nome){ toast("Informe o nome do entregável", true); return; }
  const payload = {
    tipo: nome,
    categoria: document.getElementById("ef-cat").value || "Produto",
    responsaveis: document.getElementById("ef-resp").value.trim(),
  };
  try{
    await api("/api/projetos/" + _projAtualId + "/entregaveis", { method: "POST", body: JSON.stringify(payload) });
    toast("Entregável adicionado");
    fecharFormEntregavel();
    await abrirProjModal(_projAtualId);   // recarrega o detalhe
    _recarregarTudo().catch(()=>{});
  }catch(err){ toast(err.message, true); }
}

async function excluirEntregavel(eid, nome){
  if (!(await confirmar(`Excluir o entregável "${nome}"? Esta ação não pode ser desfeita.`,
        {title:"Excluir entregável", okLabel:"Excluir"}))) return;
  try{
    await api("/api/entregaveis/" + eid, { method: "DELETE" });
    toast("Entregável excluído");
    if (_projAtualId) await abrirProjModal(_projAtualId);
    _recarregarTudo().catch(()=>{});
  }catch(err){ toast(err.message, true); }
}

/* ── Aba Modelos: templates de entregáveis por tipo (OEM/Revenda) ── */
let _modelosCache = {};

async function loadModelos(){
  const data = await api("/api/modelos");
  _modelosCache = data.modelos || {};
  renderModelosToggle(data.tipos || TIPOS_PROJETO);
  renderModelos();
}

function renderModelosToggle(tipos){
  const host = document.getElementById("modelos-tipo-toggle");
  if (!host) return;
  host.innerHTML = tipos.map(t =>
    `<button type="button" class="modelos-tipo-btn${t===_modelosTipoAtual?" active":""}" onclick="setModelosTipo('${t}')">${esc(t)}</button>`
  ).join("");
}

function setModelosTipo(t){
  _modelosTipoAtual = t;
  document.querySelectorAll("#modelos-tipo-toggle .modelos-tipo-btn")
    .forEach(b => b.classList.toggle("active", b.textContent.trim() === t));
  renderModelos();
}

function renderModelos(){
  const host = document.getElementById("modelos-body");
  if (!host) return;
  const itens = _modelosCache[_modelosTipoAtual] || [];
  const pode = canEditProj();
  // agrupa por categoria
  const grupos = {};
  itens.forEach(m => (grupos[m.categoria] = grupos[m.categoria] || []).push(m));
  const cats = CATEGORIAS.filter(c => grupos[c]).concat(
    Object.keys(grupos).filter(c => !CATEGORIAS.includes(c)));
  let html = "";
  cats.forEach(c => {
    html += `<div class="modelos-cat"><div class="modelos-cat-head">${esc(c)}</div>`;
    html += grupos[c].map(m =>
      `<div class="modelos-row">
        <span class="modelos-nome">${esc(m.tipo)}</span>
        <span class="modelos-resp">${esc(m.responsavel_padrao || "—")}</span>
        ${pode ? `<span class="modelos-acts">
          <button type="button" class="lnk" onclick="modeloEditar(${m.id})">Editar</button>
          <button type="button" class="lnk lnk-danger" onclick="modeloExcluir(${m.id})">Excluir</button>
        </span>` : ""}
      </div>`).join("");
    html += `</div>`;
  });
  if (!itens.length) html = `<div class="per-vazio" style="padding:16px 0">Nenhum item neste modelo ainda.</div>`;
  if (pode){
    const opts = CATEGORIAS.map(c => `<option value="${c}">${c}</option>`).join("");
    html += `<div class="modelos-add">
      <select class="form-input" id="mod-add-cat" aria-label="Categoria">${opts}</select>
      <input class="form-input" id="mod-add-nome" placeholder="Nome do entregável" aria-label="Nome do entregável"
             onkeydown="if(event.key==='Enter'){event.preventDefault();modeloAdicionar();}">
      <input class="form-input" id="mod-add-resp" placeholder="Responsável padrão (opcional)" aria-label="Responsável padrão">
      <button type="button" class="btn btn-primary btn-sm" onclick="modeloAdicionar()">+ Adicionar</button>
    </div>`;
  }
  host.innerHTML = html;
}

async function modeloAdicionar(){
  const nome = document.getElementById("mod-add-nome").value.trim();
  if (!nome){ toast("Informe o nome do entregável", true); return; }
  const payload = {
    tipo_projeto: _modelosTipoAtual,
    categoria: document.getElementById("mod-add-cat").value || "Produto",
    tipo: nome,
    responsavel_padrao: document.getElementById("mod-add-resp").value.trim(),
  };
  try{
    await api("/api/modelos", { method: "POST", body: JSON.stringify(payload) });
    toast("Item adicionado ao modelo");
    await loadModelos();
  }catch(err){ toast(err.message, true); }
}

let _modeloEditId = null;

function modeloEditar(mid){
  const itens = _modelosCache[_modelosTipoAtual] || [];
  const m = itens.find(x => x.id === mid);
  if (!m) return;
  _modeloEditId = mid;
  _fillCatSelect("mdf-cat", m.categoria);
  document.getElementById("mdf-nome").value = m.tipo || "";
  document.getElementById("mdf-resp").value = m.responsavel_padrao || "";
  document.getElementById("mdf-sub").textContent = `Modelo ${_modelosTipoAtual} · projetos já criados não são afetados`;
  _abrirModal("modal-modelo-form");
  setTimeout(() => document.getElementById("mdf-nome").focus(), 60);
}

function fecharModeloForm(){ _fecharModal("modal-modelo-form"); _modeloEditId = null; }

async function salvarModeloForm(){
  if (!_modeloEditId) return;
  const nome = document.getElementById("mdf-nome").value.trim();
  if (!nome){ toast("Informe o nome do entregável", true); return; }
  const payload = {
    tipo: nome,
    categoria: document.getElementById("mdf-cat").value || "Produto",
    responsavel_padrao: document.getElementById("mdf-resp").value.trim(),
  };
  try{
    await api("/api/modelos/" + _modeloEditId, { method: "PUT", body: JSON.stringify(payload) });
    toast("Modelo atualizado");
    fecharModeloForm();
    await loadModelos();
  }catch(err){ toast(err.message, true); }
}

async function modeloExcluir(mid){
  const itens = _modelosCache[_modelosTipoAtual] || [];
  const m = itens.find(x => x.id === mid);
  const nome = m ? m.tipo : "este item";
  if (!(await confirmar(`Remover "${nome}" do modelo ${_modelosTipoAtual}? Projetos já criados não são afetados.`,
        {title:"Remover item do modelo", okLabel:"Remover"}))) return;
  try{
    await api("/api/modelos/" + mid, { method: "DELETE" });
    toast("Item removido do modelo");
    await loadModelos();
  }catch(err){ toast(err.message, true); }
}

/* ── Lançamento mensal (PMO) ── */
let _mensalEditComp = null;

function _proximaCompetencia(serie){
  if (serie && serie.length){
    const m = /^(\d{4})-(\d{2})$/.exec(serie[serie.length-1].competencia);
    if (m){ let y=+m[1], mo=+m[2]+1; if(mo>12){mo=1;y++;} return `${y}-${String(mo).padStart(2,"0")}`; }
  }
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}`;
}

function _atualizaPrevInfo(){
  const el = document.getElementById("mf-prev-info");
  if (!el || !_projDetalheAtual) return;
  const comp = document.getElementById("mf-competencia").value;
  const prev = _previstoEm(_projDetalheAtual, comp);
  const serie = _projDetalheAtual.serie_mensal || [];
  const ponto = serie.find(s => s.competencia === comp);
  const real = ponto ? ponto.pct_realizado : null;
  if (prev == null && real == null){
    el.innerHTML = `<span class="mf-prev-warn">Defina <b>início e término previstos</b> do projeto para a baseline automática.</span>`;
    return;
  }
  const partes = [];
  if (prev != null) partes.push(`Previsto pelas datas: <b>${prev}%</b>`);
  if (real != null) partes.push(`Realizado pelas tarefas: <b>${real}%</b>`);
  el.innerHTML = partes.join(" · ") + ` <span class="muted">(automáticos)</span>`;
}

function abrirModalMensal(r){
  if (!_projAtualId) return;
  _mensalEditComp = r ? r.competencia : null;
  document.getElementById("mf-title").textContent = r ? "Editar custo do mês" : "Lançar custo do mês";
  const serie = (_projDetalheAtual && _projDetalheAtual.serie_mensal) || [];
  // ao criar, sugere o mês corrente (ou o próximo sem custo)
  const semCusto = serie.filter(s => s.custo_acumulado == null);
  document.getElementById("mf-competencia").value =
    r ? r.competencia : (semCusto.length ? semCusto[semCusto.length-1].competencia : _proximaCompetencia(serie));
  const temReg = r && (r.custo_mes != null);
  document.getElementById("mf-custo").value = temReg ? _fmtMoeda(r.custo_mes) : "";
  document.getElementById("mf-excluir").style.display = temReg ? "" : "none";
  _atualizaPrevInfo();
  _atualizaAcumInfo();
  _abrirModal("modal-mensal");
  setTimeout(() => document.getElementById("mf-custo").focus(), 60);
}

/* Mostra ao vivo o custo acumulado resultante (até o mês escolhido) ao digitar. */
function _atualizaAcumInfo(){
  const el = document.getElementById("mf-acum-info");
  if (!el || !_projDetalheAtual) return;
  const comp = document.getElementById("mf-competencia").value;
  const valor = _parseMoeda(document.getElementById("mf-custo").value);
  const serie = _projDetalheAtual.serie_mensal || [];
  // soma os meses anteriores (mantém o lançado) + o valor digitado neste mês
  let acum = 0;
  for (const s of serie){
    if (s.competencia > comp) break;
    acum += (s.competencia === comp ? (valor || 0) : (s.custo_mes || 0));
  }
  if (!valor && !acum){ el.innerHTML = ""; return; }
  el.innerHTML = `Acumulado até ${_fmtComp(comp)}: <b>${_money(acum)}</b> <span class="muted">(automático)</span>`;
}

function fecharModalMensal(){ _fecharModal("modal-mensal"); _mensalEditComp = null; }

async function salvarMensal(){
  if (!_projAtualId) return;
  const comp = document.getElementById("mf-competencia").value;
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(comp)){ toast("Informe a competência (mês)", true); return; }
  const payload = {
    competencia: comp,
    custo_mes: document.getElementById("mf-custo").value,   // incremental; backend aceita "15.000,00"
    // previsto (datas) e realizado (tarefas) são automáticos no backend
  };
  try{
    await api("/api/projetos/" + _projAtualId + "/mensal", { method: "PUT", body: JSON.stringify(payload) });
    toast("Lançamento salvo");
    fecharModalMensal();
    await abrirProjModal(_projAtualId);   // recarrega detalhe (série/curva/indicadores)
    await _recarregarTudo();              // atualiza grade/KPIs
  }catch(err){ toast(err.message, true); }
}

async function excluirMensal(){
  if (!_projAtualId || !_mensalEditComp) return;
  if (!(await confirmar("Excluir o lançamento de " + _fmtComp(_mensalEditComp) + "?",
        {title:"Excluir lançamento", okLabel:"Excluir"}))) return;
  try{
    await api("/api/projetos/" + _projAtualId + "/mensal/" + _mensalEditComp, { method: "DELETE" });
    toast("Lançamento excluído");
    fecharModalMensal();
    await abrirProjModal(_projAtualId);
    await _recarregarTudo();
  }catch(err){ toast(err.message, true); }
}

/* ── Popover de edição ── */
function abrirPop(e){
  _popEntregavel = e;
  document.getElementById("pop-titulo").textContent = e.tipo;
  document.getElementById("pop-status").value = e.status;
  document.getElementById("pop-pct").value = e.percentual ?? 0;
  document.getElementById("pop-pct-val").textContent = (e.percentual ?? 0) + "%";
  document.getElementById("pop-resp").value = e.responsaveis || "";
  document.getElementById("pop-inicio").value = _toIso(e.data_inicio);
  document.getElementById("pop-conclusao").value = _toIso(e.data_conclusao);
  popStatusChange();
  document.getElementById("edit-pop").style.display = "flex";
}
function _hojeIso(){ const d=new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`; }
function popStatusChange(){
  const st = document.getElementById("pop-status").value;
  document.getElementById("pop-pct-wrap").style.display = st === "em_progresso" ? "block" : "none";
  // datas relevantes quando a tarefa está em andamento ou concluída
  const mostraDatas = st === "em_progresso" || st === "concluido";
  document.getElementById("pop-datas").style.display = mostraDatas ? "block" : "none";
  const ini = document.getElementById("pop-inicio"), con = document.getElementById("pop-conclusao");
  if (st === "concluido" && !con.value) con.value = _hojeIso();   // conclusão = hoje por padrão
  if (st !== "concluido") con.value = "";                         // conclusão só faz sentido se concluído
  if (mostraDatas && !ini.value)                                  // início = conclusão (se concluído) ou hoje
    ini.value = (st === "concluido" && con.value) ? con.value : _hojeIso();
}
function fecharPop(){ document.getElementById("edit-pop").style.display = "none"; _popEntregavel = null; }

async function salvarPop(){
  if (!_popEntregavel) return;
  const projIdDaTarefa = _popEntregavel.projeto_id;
  const payload = {
    status: document.getElementById("pop-status").value,
    responsaveis: document.getElementById("pop-resp").value.trim(),
    data_inicio: document.getElementById("pop-inicio").value,
    data_conclusao: document.getElementById("pop-conclusao").value,
  };
  if (payload.status === "em_progresso")
    payload.percentual = parseInt(document.getElementById("pop-pct").value, 10);
  try{
    await api("/api/entregaveis/" + _popEntregavel.id, {
      method: "PUT", body: JSON.stringify(payload)});
    toast("Entregável atualizado");
    fecharPop();
    // Recarrega a grade (novo avanço / pendências) e o modal aberto.
    const modalAberto = document.getElementById("modal-projeto").classList.contains("open");
    const idAtual = _projAtualId;
    await loadProjetos().catch(()=>{});
    if (modalAberto && idAtual) abrirProjModal(idAtual).catch(()=>{});
    // Se a ficha do Dashboard estiver mostrando este projeto, atualiza-a.
    if (_fichaProj && _fichaProj.id === projIdDaTarefa) setDashProj(_fichaProj.id).catch(()=>{});
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
document.getElementById("modal-proj-form").addEventListener("click", (e) => {
  if (e.target === e.currentTarget) fecharFormProjeto();
});
document.getElementById("modal-mensal").addEventListener("click", (e) => {
  if (e.target === e.currentTarget) fecharModalMensal();
});
document.getElementById("modal-ent-form").addEventListener("click", (e) => {
  if (e.target === e.currentTarget) fecharFormEntregavel();
});
document.getElementById("modal-modelo-form").addEventListener("click", (e) => {
  if (e.target === e.currentTarget) fecharModeloForm();
});
document.getElementById("cf-ok").addEventListener("click", () => _fecharConfirm(true));
document.getElementById("cf-cancel").addEventListener("click", () => _fecharConfirm(false));
document.getElementById("modal-confirm-ent").addEventListener("click", (e) => {
  if (e.target === e.currentTarget) _fecharConfirm(false);
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (document.getElementById("modal-confirm-ent").classList.contains("open")){ _fecharConfirm(false); return; }
  if (document.getElementById("modal-modelo-form").classList.contains("open")) fecharModeloForm();
  else if (document.getElementById("modal-ent-form").classList.contains("open")) fecharFormEntregavel();
  else if (document.getElementById("modal-mensal").classList.contains("open")) fecharModalMensal();
  else if (document.getElementById("modal-proj-form").classList.contains("open")) fecharFormProjeto();
  else if (document.getElementById("modal-projeto").classList.contains("open")) fecharProjModal();
  else if (document.getElementById("edit-pop").style.display !== "none") fecharPop();
});

/* ── Init ── */
(async function init(){
  if (!token()){ window.location.href = "/"; return; }
  // Acesso ao módulo: somente gestor ou acima (gestor/admin)
  if (!["admin", "gestor"].includes(userRole())){ window.location.href = "/hub"; return; }
  const nb = document.getElementById("btn-novo-proj");
  if (nb) nb.style.display = canEditProj() ? "" : "none";
  try{
    await Promise.all([loadKpis(), loadProjetos(), loadProjetosAll()]);
    populateDashProjSel();
    renderCharts();
  }catch(e){ toast(e.message, true); }
})();


/* ── GERAÇÃO DE RELATÓRIO PDF (Client-side) ── */
function _parseBRDate(str) {
  if(!str) return 0;
  const parts = str.split(' ');
  if(parts.length < 1) return 0;
  const d = parts[0].split('/');
  if(d.length !== 3) return 0;
  return new Date(d[2], parseInt(d[1])-1, d[0]).getTime();
}
function _exportConfigEnt(){
  return {
    periodo: (document.getElementById('exp-periodo')||{}).value||'',
    moscow: (document.getElementById('exp-moscow')||{}).value||'',
    status: (document.getElementById('exp-status')||{}).value||'',
  };
}
function _exportFilteredProjects(){
  const cfg = _exportConfigEnt();
  return _projetosAll.filter(p => {
    if (cfg.periodo) {
      const days = parseInt(cfg.periodo);
      const cutoff = Date.now() - (days * 24 * 60 * 60 * 1000);
      const hasRecent = (p.entregaveis || []).some(e => {
        if(e.status === 'na') return false;
        return _parseBRDate(e.atualizado_em) >= cutoff;
      });
      if(!hasRecent) return false;
    }
    if (cfg.moscow) {
      const v = normMoscow(p.moscow);
      const k = v === "Wont" ? "Wont" : (v || "Sem prioridade");
      if (k !== cfg.moscow) return false;
    }
    if (cfg.status === 'Finalizado' && p.avanco < 100) return false;
    if (cfg.status === 'Pendente' && p.avanco === 100) return false;
    return true;
  });
}
function updateExportPreviewEnt(){
  const el = document.getElementById('exp-preview');
  if(el) el.textContent = `${_exportFilteredProjects().length} projeto(s) serão incluídos no relatório`;
}
function openExportModal(){
  const el1=document.getElementById('exp-periodo'); if(el1) el1.value='';
  const el2=document.getElementById('exp-moscow'); if(el2) el2.value='';
  const el3=document.getElementById('exp-status'); if(el3) el3.value='';
  ['exp-periodo','exp-moscow','exp-status'].forEach(id=>{
    const e=document.getElementById(id); if(e) e.addEventListener('input', updateExportPreviewEnt);
    if(e) e.addEventListener('change', updateExportPreviewEnt);
  });
  updateExportPreviewEnt();
  const m = document.getElementById('modal-export-ent');
  m.classList.add('open');
  m.setAttribute('aria-hidden', 'false');
}
function fecharModalExport(){
  const m = document.getElementById('modal-export-ent');
  m.classList.remove('open');
  m.setAttribute('aria-hidden', 'true');
}

const _CHART_FONT = "'Inter', system-ui, sans-serif";
function _hgrad(ctx, w, c1, c2){ const g=ctx.createLinearGradient(0,0,w,0); g.addColorStop(0,c1); g.addColorStop(1,c2); return g; }
/* mesmo gradiente das roscas internas: cor cheia no topo -> mais escura embaixo */
function _vgradFull(ctx, h, hex){ const g=ctx.createLinearGradient(0,0,0,h); g.addColorStop(0,hex); g.addColorStop(1,_darken(hex,0.5)); return g; }
function _centerTextPlugin(big, small){
  return { id:'centerText', afterDraw(chart){
    const a=chart.chartArea; if(!a) return; const ctx=chart.ctx;
    const cx=(a.left+a.right)/2, cy=(a.top+a.bottom)/2;
    ctx.save(); ctx.textAlign='center'; ctx.textBaseline='middle';
    ctx.fillStyle='#f1f5f9'; ctx.font='bold 60px '+_CHART_FONT; ctx.fillText(String(big), cx, cy-6);
    ctx.fillStyle='#94a3ff'; ctx.font='600 22px '+_CHART_FONT; ctx.fillText(small, cx, cy+32);
    ctx.restore();
  }};
}
const _barValueHPlugin = { id:'barValuesH', afterDatasetsDraw(chart){
  const ctx=chart.ctx; const meta=chart.getDatasetMeta(0);
  chart.data.datasets[0].data.forEach((v,i)=>{ const el=meta.data[i]; if(!el) return;
    ctx.save(); ctx.fillStyle='#f1f5f9'; ctx.font='bold 26px '+_CHART_FONT; ctx.textAlign='left'; ctx.textBaseline='middle';
    ctx.fillText(String(v)+'%', el.x+10, el.y); ctx.restore();
  });
}};
function _renderChartImage(build, wpx, hpx){
  return new Promise(resolve=>{
    if(typeof Chart==='undefined'){ resolve(null); return; }
    const canvas=document.createElement('canvas');
    canvas.width=wpx; canvas.height=hpx;
    canvas.style.position='fixed'; canvas.style.left='-10000px'; canvas.style.top='0';
    document.body.appendChild(canvas);
    const ctx=canvas.getContext('2d');
    const cfg = (typeof build==='function') ? build(ctx, wpx, hpx) : build;
    cfg.options=cfg.options||{};
    cfg.options.responsive=false; cfg.options.animation=false; cfg.options.maintainAspectRatio=false;
    let chart;
    try{ chart=new Chart(ctx, cfg); }catch(e){ canvas.remove(); resolve(null); return; }
    requestAnimationFrame(()=>{
      let url=null;
      try{ url=chart.canvas.toDataURL('image/png'); }catch(e){}
      try{ chart.destroy(); }catch(e){}
      canvas.remove();
      resolve(url);
    });
  });
}
function _addImgContain(doc, img, x, y, boxW, boxH, imgRatio){
  if(!img) return;
  let w = boxW, h = boxW/imgRatio;
  if(h > boxH){ h = boxH; w = boxH*imgRatio; }
  doc.addImage(img, 'PNG', x + (boxW-w)/2, y + (boxH-h)/2, w, h);
}

async function gerarRelatorioPDF(){
  if(!window.jspdf){ toast('Aguarde o carregamento do gerador de PDF e tente novamente', true); return; }
  const projects = _exportFilteredProjects();
  if(!projects.length){ toast('Nenhum projeto corresponde aos filtros', true); return; }
  toast('Gerando relatório...');
  const cfg = _exportConfigEnt();

  // garante a fonte Inter carregada antes de rasterizar os gráficos (mesma fonte da plataforma)
  try{ await Promise.all([document.fonts.load("700 60px Inter"), document.fonts.load("600 24px Inter")]); await document.fonts.ready; }catch(e){}

  let conc=0, prog=0, pend=0;
  projects.forEach(p=>{
    if(p.avanco === 100) conc++;
    else if(p.avanco > 0) prog++;
    else pend++;
  });
  const avg = projects.length ? Math.round(projects.reduce((a,b)=>a+b.avanco,0)/projects.length) : 0;

  const top = [...projects].sort((a,b)=>b.avanco - a.avanco).slice(0,10);
  const moscowCont = {};
  projects.forEach(p=>{
      const m = normMoscow(p.moscow);
      const k = m==="Wont"?"Wont":(m||"Sem prioridade");
      moscowCont[k]=(moscowCont[k]||0)+1;
  });

  // Rosca de status — idêntica à do dashboard: cutout 78%, gradiente vertical, cantos arredondados + espaçamento
  const stHex = ['#10b981','#22d3ee','#f59e0b'];
  const donutImg = await _renderChartImage((ctx,w,h)=>({
    type:'doughnut',
    data:{labels:['Concluídos','Em progresso','Pendentes'],
      datasets:[{data:[conc,prog,pend], backgroundColor:stHex.map(c=>_vgradFull(ctx,h,c)),
        borderWidth:0, borderRadius:14, spacing:6}]},
    options:{cutout:'78%', layout:{padding:14}, plugins:{legend:{display:false}}},
    plugins:[_centerTextPlugin(projects.length, 'projetos')]
  }), 760, 760);

  const moscowColors = {"Must":"#ef4444", "Should":"#f59e0b", "Could":"#3b82f6", "Wont":"#64748b", "Sem prioridade":"#94a3b8"};
  const mLabels = Object.keys(moscowCont);
  const mVals = mLabels.map(l=>moscowCont[l]);
  const mBg = mLabels.map(l=>moscowColors[l]);

  const moscowImg = await _renderChartImage((ctx,w,h)=>({
    type:'doughnut',
    data:{labels:mLabels.map(x=>x==='Wont'?"Won't":x),
      datasets:[{data:mVals, backgroundColor:mBg.map(c=>_vgradFull(ctx,h,c)),
        borderWidth:0, borderRadius:14, spacing:6}]},
    options:{cutout:'78%', layout:{padding:14}, plugins:{legend:{display:false}}},
    plugins:[_centerTextPlugin(projects.length, 'projetos')]
  }), 760, 760);

  // Barras horizontais — mesmo padrão interno: gradiente ciano→azul, cantos arredondados, eixo % e grade discreta.
  // Canvas renderizado já na proporção da caixa larga/baixa do PDF para o texto não esticar/borrar.
  const barImg = await _renderChartImage((ctx)=>({
    type:'bar',
    data:{labels:top.map(p=>p.nome),
      datasets:[{data:top.map(p=>p.avanco), borderRadius:10, borderWidth:0, maxBarThickness:26, backgroundColor:_hgrad(ctx,1600,'#22d3ee','#3b82f6')}]},
    options:{indexAxis:'y', layout:{padding:{right:20, left:8, top:8, bottom:8}}, plugins:{legend:{display:false}},
      scales:{x:{min:0, max:100, ticks:{color:'#c7d2fe', font:{size:15, family:_CHART_FONT}, callback:(v)=>v+'%'}, grid:{color:'rgba(167,139,250,.12)'}, border:{display:false}},
              y:{ticks:{color:'#f1f5f9', font:{size:17, family:_CHART_FONT, weight:'600'}}, grid:{display:false}, border:{display:false}}}}
  }), 1600, 440);

  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({orientation:'landscape', unit:'mm', format:'a4'});
  const pageW = doc.internal.pageSize.getWidth();
  const pageH = doc.internal.pageSize.getHeight();
  const margin = 12;
  const C = { bg:[13,16,32], card:[26,31,58], rowAlt:[20,24,46], border:[42,54,98],
    t1:[241,245,249], tmut:[148,163,255], accent:[34,211,238],
    green:[16,185,129], amber:[245,158,11], red:[239,68,68], cyan:[34,211,238] };
  
  function paintBg(){ doc.setFillColor(...C.bg); doc.rect(0,0,pageW,pageH,'F'); }
  function card(x,yy,w,h){ doc.setFillColor(...C.card); doc.setDrawColor(...C.border); doc.setLineWidth(0.3); doc.roundedRect(x,yy,w,h,2.5,2.5,'FD'); }
  function cardTitle(txt,x,yy,w){ doc.setFont('helvetica','bold'); doc.setFontSize(8.5); doc.setTextColor(...C.accent); doc.text(txt.toUpperCase(), x+w/2, yy+6.5, {align:'center'}); }
  function legendRow(items, cx, yy, maxW){
    // auto-ajusta fonte/espaçamentos para caber dentro de maxW (não vaza o card)
    let fs=8.5, itemGap=8, dotGap=2.2, r=1.5;
    const measure = () => {
      doc.setFontSize(fs);
      const widths = items.map(([c,l])=> r*2 + dotGap + doc.getTextWidth(l));
      return { widths, total: widths.reduce((a,b)=>a+b,0) + itemGap*(items.length-1) };
    };
    let m = measure();
    if (maxW && m.total > maxW){
      const scale = Math.max(0.55, maxW / m.total);
      fs *= scale; itemGap = Math.max(2.5, itemGap*scale); dotGap *= scale; r *= scale;
      m = measure();
      if (m.total > maxW){ itemGap = 2.2; m = measure(); }   // último recurso
    }
    doc.setFont('helvetica','normal'); doc.setFontSize(fs);
    let x = cx - m.total/2;
    items.forEach(([col,lab],i)=>{
      doc.setFillColor(...col); doc.circle(x+r, yy-1.1, r, 'F');
      doc.setTextColor(...C.t1); doc.text(lab, x+r*2+dotGap, yy);
      x += m.widths[i] + itemGap;
    });
    doc.setFontSize(8.5);
  }

  const hoje = new Date().toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
  const filtros = [];
  if(cfg.periodo) filtros.push(`Avanço em: Últimos ${cfg.periodo} dias`);
  if(cfg.moscow) filtros.push(`MoSCoW: ${cfg.moscow==="Wont"?"Won't":cfg.moscow}`);
  if(cfg.status) filtros.push(`Status: ${cfg.status}`);
  if(!filtros.length) filtros.push('Todos os projetos');

  paintBg();
  doc.setFont('helvetica','bold'); doc.setFontSize(19); doc.setTextColor(...C.t1);
  doc.text('Relatório Executivo — Projetos & Entregáveis', margin, 18);
  doc.setFont('helvetica','bold'); doc.setFontSize(10); doc.setTextColor(...C.accent);
  doc.text('DocTrack Enterprise v4.0', margin, 25);
  doc.setFont('helvetica','normal'); doc.setFontSize(8); doc.setTextColor(...C.tmut);
  doc.text('Gerado em '+hoje, pageW-margin, 16, {align:'right'});
  doc.text(filtros.join('   ·   '), pageW-margin, 22, {align:'right'});
  doc.setDrawColor(...C.accent); doc.setLineWidth(0.5); doc.line(margin, 29, pageW-margin, 29);

  let y = 34;
  const rowAh = 74, gap = 4, colW = 58;
  const kpis = [['Projetos Filtrados', projects.length, C.t1],['Concluídos', conc, C.green],['Em progresso', prog, C.cyan],['Avanço Médio', avg+'%', C.accent]];
  const kh = (rowAh - gap*3)/4;
  kpis.forEach(([lab,val,col],i)=>{
    const cy = y + i*(kh+gap);
    card(margin, cy, colW, kh);
    doc.setFont('helvetica','normal'); doc.setFontSize(8); doc.setTextColor(...C.tmut);
    doc.text(lab, margin+5, cy+kh/2+1);
    doc.setFont('helvetica','bold'); doc.setFontSize(16); doc.setTextColor(...col);
    doc.text(String(val), margin+colW-5, cy+kh/2+1.5, {align:'right'});
  });

  const donW = (pageW - margin*2 - colW - gap*2)/2;
  const d1x = margin+colW+gap, d2x = d1x+donW+gap;
  const donImgH = rowAh - 18; 
  card(d1x, y, donW, rowAh); cardTitle('Status dos Projetos', d1x, y, donW);
  _addImgContain(doc, donutImg, d1x+6, y+9, donW-12, donImgH, 1);
  legendRow([['Concluídos',C.green],['Em progresso',C.cyan],['Pendentes',C.amber]].map(([l,c])=>[c,l]), d1x+donW/2, y+rowAh-4, donW-10);
  
  card(d2x, y, donW, rowAh); cardTitle('Prioridade MoSCoW', d2x, y, donW);
  _addImgContain(doc, moscowImg, d2x+6, y+9, donW-12, donImgH, 1);
  const legMoscow = mLabels.map(l=> {
      const c = l==="Must"?C.red:l==="Should"?C.amber:l==="Could"?[59,130,246]:l==="Wont"?[100,116,139]:[148,163,184];
      return [c, l==="Wont"?"Won't":l];
  });
  legendRow(legMoscow, d2x+donW/2, y+rowAh-4, donW-10);

  y += rowAh + gap;
  const rowBh = pageH - y - 11;
  card(margin, y, pageW-margin*2, rowBh); cardTitle('Avanço por Projeto (Top 10)', margin, y, pageW-margin*2);
  if(barImg) doc.addImage(barImg, 'PNG', margin+4, y+10, pageW-margin*2-8, rowBh-14);

  // Página 2: Detalhamento
  doc.addPage(); paintBg(); y = margin+4;
  doc.setFont('helvetica','bold'); doc.setFontSize(14); doc.setTextColor(...C.t1);
  doc.text('Detalhamento dos Projetos', margin, y+4); y += 11;

  const cols = [
    {h:'Projeto', k:'nome', w:80},
    {h:'MoSCoW', k:'moscow', w:24},
    {h:'Pend.', k:'pendentes', w:20},
    {h:'Lançamento', k:'lancamento', w:34},
    {h:'Avanço', k:'avanco', w:24},
    {h:'SPI (prazo)', k:'spi', w:32},
    {h:'CPI (custo)', k:'cpi', w:32},
  ];
  const _pmoPdfCor = (st) => st==='ok'?C.green : st==='atencao'?C.amber : st==='critico'?C.red : C.tmut;
  const rowH=7.2, headerH=9;
  function thead(){
    doc.setFillColor(...C.card); doc.rect(margin,y,pageW-margin*2,headerH,'F');
    doc.setFont('helvetica','bold'); doc.setFontSize(7.5); doc.setTextColor(...C.accent);
    let cx=margin; cols.forEach(c=>{doc.text(c.h, cx+3, y+6); cx+=c.w;}); y+=headerH;
  }
  thead();
  projects.forEach((p,idx)=>{
    if(y+rowH > pageH-11){ doc.addPage(); paintBg(); y=margin+4; thead(); }
    if(idx%2===0){ doc.setFillColor(...C.rowAlt); doc.rect(margin,y,pageW-margin*2,rowH,'F'); }
    doc.setDrawColor(...C.border); doc.setLineWidth(0.15); doc.line(margin,y+rowH,pageW-margin,y+rowH);
    
    let cx=margin;
    doc.setFontSize(7.5);
    const m = p.pmo || {};
    cols.forEach(c=>{
      let v = String(p[c.k] || (c.k==='avanco'?'0':'—'));
      let corCel = null;
      if(c.k === 'avanco') v += '%';
      if(c.k === 'moscow') { v = normMoscow(v) || '—'; if(v==="Wont") v="Won't"; }
      if(c.k === 'lancamento') v = fmtLanc(p.lancamento) || '—';
      if(c.k === 'spi') { v = m.spi != null ? m.spi.toFixed(2) : '—'; if(m.spi != null) corCel = _pmoPdfCor(m.status_prazo); }
      if(c.k === 'cpi') { v = m.cpi != null ? m.cpi.toFixed(2) : '—'; if(m.cpi != null) corCel = _pmoPdfCor(m.status_custo); }
      const maxW = c.w-4;
      if(doc.getTextWidth(v)>maxW){ v=v.substring(0, Math.max(1, Math.floor(v.length*maxW/doc.getTextWidth(v))-1))+'…'; }
      if(c.k==='nome'){ doc.setFont('helvetica','bold'); doc.setTextColor(...C.t1); }
      else if(corCel){ doc.setFont('helvetica','bold'); doc.setTextColor(...corCel); }
      else { doc.setFont('helvetica', 'normal'); doc.setTextColor(...C.tmut); }
      doc.text(v, cx+3, y+4.8); cx+=c.w;
    });
    y+=rowH;
  });

  const pages=doc.internal.getNumberOfPages();
  for(let i=1;i<=pages;i++){ doc.setPage(i); doc.setFont('helvetica','normal'); doc.setFontSize(7); doc.setTextColor(...C.tmut);
    doc.text('DocTrack Enterprise — Relatório de Projetos', margin, pageH-5);
    doc.text(`Página ${i} de ${pages}`, pageW-margin, pageH-5, {align:'right'}); }

  doc.save('DocTrack_Projetos.pdf');
  fecharModalExport();
  toast('Relatório gerado');
}

/* ── PDF da ficha de UM projeto (filtro do Dashboard) ── */
async function exportarProjetoPDF(){
  if(!window.jspdf){ toast('Aguarde o gerador de PDF carregar', true); return; }
  const p = _fichaProj;
  if(!p){ toast('Selecione um projeto', true); return; }
  toast('Gerando ficha...');
  try{ await Promise.all([document.fonts.load("700 60px Inter"), document.fonts.load("600 22px Inter")]); await document.fonts.ready; }catch(e){}

  const m = p.pmo || {};
  const flat = (p.categorias||[]).flatMap(c=>c.entregaveis||[]);
  let conc=0, prog=0, pend=0;
  flat.forEach(e=>{ if(e.status==='concluido')conc++; else if(e.status==='em_progresso')prog++; else if(e.status==='pendente')pend++; });

  const serie = p.serie_mensal||[];
  const labels = serie.map(s=>_fmtComp(s.competencia));
  const prev = serie.map(s=>s.pct_previsto), real = serie.map(s=>s.pct_realizado);

  const curvaImg = serie.length ? await _renderChartImage((ctx)=>({
    type:'line',
    data:{labels, datasets:[
      {label:'Previsto', data:prev, borderColor:'#22d3ee', borderDash:[7,5], borderWidth:3, pointRadius:3, pointBackgroundColor:'#22d3ee', tension:.25, fill:false},
      {label:'Realizado', data:real, borderColor:'#10b981', backgroundColor:'rgba(16,185,129,.16)', borderWidth:3.5, pointRadius:3, pointBackgroundColor:'#10b981', tension:.25, fill:true},
    ]},
    options:{layout:{padding:10}, plugins:{legend:{display:true, position:'top', align:'end', labels:{color:'#c7d2fe', font:{size:17, family:_CHART_FONT}, boxWidth:16, usePointStyle:true, padding:14}}},
      scales:{x:{ticks:{color:'#94a3ff', font:{size:14, family:_CHART_FONT}}, grid:{display:false}, border:{display:false}},
              y:{min:0, max:100, ticks:{color:'#94a3ff', font:{size:14, family:_CHART_FONT}, callback:v=>v+'%'}, grid:{color:'rgba(167,139,250,.12)'}, border:{display:false}}}}
  }), 1300, 560) : null;

  const donutImg = (conc+prog+pend) ? await _renderChartImage((ctx,w,h)=>({
    type:'doughnut',
    data:{labels:['Concluídos','Em progresso','Pendentes'],
      datasets:[{data:[conc,prog,pend], backgroundColor:['#10b981','#22d3ee','#f59e0b'].map(c=>_vgradFull(ctx,h,c)), borderWidth:0, borderRadius:14, spacing:6}]},
    options:{cutout:'70%', layout:{padding:14}, plugins:{legend:{display:false}}},
    plugins:[_centerTextPlugin(p.avanco+'%','avanço')]
  }), 660, 660) : null;

  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({orientation:'landscape', unit:'mm', format:'a4'});
  const pageW = doc.internal.pageSize.getWidth(), pageH = doc.internal.pageSize.getHeight(), margin = 12;
  const C = { bg:[13,16,32], card:[26,31,58], rowAlt:[20,24,46], border:[42,54,98], t1:[241,245,249],
    tmut:[148,163,255], accent:[34,211,238], green:[16,185,129], amber:[245,158,11], red:[239,68,68] };
  const corStatus = (s)=> s==='ok'?C.green : s==='atencao'?C.amber : s==='critico'?C.red : C.tmut;
  const paintBg=()=>{ doc.setFillColor(...C.bg); doc.rect(0,0,pageW,pageH,'F'); };
  const card=(x,y,w,h)=>{ doc.setFillColor(...C.card); doc.setDrawColor(...C.border); doc.setLineWidth(0.3); doc.roundedRect(x,y,w,h,2.5,2.5,'FD'); };
  const cardTitle=(t,x,y,w)=>{ doc.setFont('helvetica','bold'); doc.setFontSize(8.5); doc.setTextColor(...C.accent); doc.text(t.toUpperCase(), x+w/2, y+6.5, {align:'center'}); };

  paintBg();
  const hoje = new Date().toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
  doc.setFont('helvetica','bold'); doc.setFontSize(18); doc.setTextColor(...C.t1);
  doc.text(p.nome, margin, 17);
  doc.setFont('helvetica','bold'); doc.setFontSize(9); doc.setTextColor(...C.accent);
  doc.text('Ficha do Projeto · DocTrack Enterprise', margin, 23);
  doc.setFont('helvetica','normal'); doc.setFontSize(8); doc.setTextColor(...C.tmut);
  const periodo = periodoProjeto(p);
  doc.text('Gerado em '+hoje, pageW-margin, 14, {align:'right'});
  const subDir = [periodo?('Prazo '+periodo):null, m.bac?('Orçado '+_money(m.bac)):null].filter(Boolean).join('   ·   ');
  if(subDir) doc.text(subDir, pageW-margin, 20, {align:'right'});
  doc.setDrawColor(...C.accent); doc.setLineWidth(0.5); doc.line(margin, 27, pageW-margin, 27);

  const kpis = [
    ['Avanço', p.avanco+'%', C.accent],
    ['Prazo (SPI)', m.spi!=null?m.spi.toFixed(2):'—', corStatus(m.status_prazo)],
    ['Custo (CPI)', m.cpi!=null?m.cpi.toFixed(2):'—', corStatus(m.status_custo)],
    ['Custo proj. (EAC)', m.eac!=null?_money(m.eac):'—', corStatus(m.status_custo)],
    ['Pendências', String(p.pendentes), p.pendentes>0?C.amber:C.green],
  ];
  let y = 32; const gap=4, kw=(pageW-margin*2-gap*4)/5, kh=24;
  kpis.forEach(([lab,val,col],i)=>{
    const x = margin + i*(kw+gap);
    card(x,y,kw,kh);
    doc.setFont('helvetica','normal'); doc.setFontSize(7.5); doc.setTextColor(...C.tmut);
    doc.text(lab, x+5, y+9);
    doc.setFont('helvetica','bold'); doc.setFontSize(15); doc.setTextColor(...col);
    doc.text(String(val), x+5, y+19);
  });

  y += kh + gap;
  const rowH = pageH - y - 11;
  const curvaW = (pageW-margin*2)*0.62, donutW = pageW-margin*2-curvaW-gap;
  card(margin, y, curvaW, rowH); cardTitle('Curva-S · previsto x realizado', margin, y, curvaW);
  if(curvaImg) doc.addImage(curvaImg, 'PNG', margin+4, y+10, curvaW-8, rowH-14);
  else { doc.setFont('helvetica','normal'); doc.setFontSize(9); doc.setTextColor(...C.tmut); doc.text('Sem dados de cronograma.', margin+curvaW/2, y+rowH/2, {align:'center'}); }

  const dx = margin+curvaW+gap;
  card(dx, y, donutW, rowH); cardTitle('Status dos entregáveis', dx, y, donutW);
  if(donutImg) _addImgContain(doc, donutImg, dx+6, y+11, donutW-12, rowH-32, 1);
  const leg = [['Concluídos',C.green,conc],['Em progresso',C.accent,prog],['Pendentes',C.amber,pend]];
  let ly = y+rowH-20;
  leg.forEach(([lab,col,n])=>{
    doc.setFillColor(...col); doc.circle(dx+10, ly-1, 1.6, 'F');
    doc.setFont('helvetica','normal'); doc.setFontSize(8.5); doc.setTextColor(...C.t1);
    doc.text(`${lab}: ${n}`, dx+15, ly); ly += 5.5;
  });

  // Página 2: entregáveis
  doc.addPage(); paintBg(); y = margin+4;
  doc.setFont('helvetica','bold'); doc.setFontSize(14); doc.setTextColor(...C.t1);
  doc.text('Entregáveis — '+p.nome, margin, y+4); y += 11;
  const cols = [
    {h:'Categoria', w:38}, {h:'Entregável', w:80}, {h:'Responsáveis', w:62},
    {h:'Status', w:28}, {h:'Início', w:24}, {h:'Conclusão', w:24},
  ];
  const rowAh=7.2, headerH=9;
  const stLabel = (e)=> e.status==='concluido'?'Concluído' : e.status==='em_progresso'?((e.percentual??0)+'%') : e.status==='na'?'N/A':'Pendente';
  const thead=()=>{ doc.setFillColor(...C.card); doc.rect(margin,y,pageW-margin*2,headerH,'F');
    doc.setFont('helvetica','bold'); doc.setFontSize(7.5); doc.setTextColor(...C.accent);
    let cx=margin; cols.forEach(c=>{doc.text(c.h, cx+3, y+6); cx+=c.w;}); y+=headerH; };
  thead();
  const linhas = (p.categorias||[]).flatMap(c => (c.entregaveis||[]).map(e=>({cat:c.categoria, e})));
  linhas.forEach((row,idx)=>{
    if(y+rowAh > pageH-11){ doc.addPage(); paintBg(); y=margin+4; thead(); }
    if(idx%2===0){ doc.setFillColor(...C.rowAlt); doc.rect(margin,y,pageW-margin*2,rowAh,'F'); }
    doc.setDrawColor(...C.border); doc.setLineWidth(0.15); doc.line(margin,y+rowAh,pageW-margin,y+rowAh);
    const e=row.e;
    const vals = [row.cat, (e.tipo||'').trim(), (e.responsaveis||'—'), stLabel(e), fmtLanc(e.data_inicio)||'—', fmtLanc(e.data_conclusao)||'—'];
    let cx=margin; doc.setFontSize(7.5);
    cols.forEach((c,i)=>{
      let v=String(vals[i]); const maxW=c.w-4;
      if(doc.getTextWidth(v)>maxW){ v=v.substring(0, Math.max(1, Math.floor(v.length*maxW/doc.getTextWidth(v))-1))+'…'; }
      if(i===3){ doc.setFont('helvetica','bold'); doc.setTextColor(...(e.status==='concluido'?C.green:e.status==='em_progresso'?C.accent:e.status==='na'?C.tmut:C.amber)); }
      else if(i===1){ doc.setFont('helvetica','bold'); doc.setTextColor(...C.t1); }
      else { doc.setFont('helvetica','normal'); doc.setTextColor(...C.tmut); }
      doc.text(v, cx+3, y+4.8); cx+=c.w;
    });
    y+=rowAh;
  });

  const pages=doc.internal.getNumberOfPages();
  for(let i=1;i<=pages;i++){ doc.setPage(i); doc.setFont('helvetica','normal'); doc.setFontSize(7); doc.setTextColor(...C.tmut);
    doc.text('DocTrack Enterprise — Ficha de Projeto', margin, pageH-5);
    doc.text(`Página ${i} de ${pages}`, pageW-margin, pageH-5, {align:'right'}); }

  doc.save('Projeto_'+(p.nome||'projeto').replace(/[^a-z0-9]+/gi,'_').slice(0,40)+'.pdf');
  toast('Ficha gerada');
}

