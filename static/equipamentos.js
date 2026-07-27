/* Módulo Equipamentos — shell + gráficos no mesmo padrão do módulo de Documentos */
/* TOKEN_KEY, token(), esc(), doLogout() e o par de tema vêm de static/common.js. */
function userObj(){ try{ return JSON.parse(localStorage.getItem("doctrack_user")||"{}")||{}; }catch(e){ return {}; } }
const ROLE = (userObj().role)||"";
const podeEditar = ["admin","gestor","tecnico"].includes(ROLE);
const podeGerir  = ["admin","gestor"].includes(ROLE);
sessionStorage.setItem("dt_module", "equip");

// Todo gráfico lê a cor do eixo na hora de desenhar (_chTxt/_chGrid), então
// trocar o tema exige repintar a página ativa — não só o dashboard.
window.onThemeChange = function(){
  const ativa = document.querySelector(".page.active");
  if(ativa) renderPagina((ativa.id||"").replace("page-",""));
};

async function api(url, opts={}){
  function hdr(){ return {"Content-Type":"application/json", "Authorization":"Bearer "+token(), ...(opts.headers||{})}; }
  let res = await fetch(url, {...opts, headers:hdr()});
  if(res.status===401){
    if(window.DT_AUTH && await window.DT_AUTH.refresh()){ res = await fetch(url, {...opts, headers:hdr()}); }
    if(res.status===401){ (window.DT_AUTH?window.DT_AUTH.gotoLogin(true):window.location.href="/"); throw new Error("401"); }
  }
  if(!res.ok){ const b=await res.json().catch(()=>({})); throw new Error(b.erro||("HTTP "+res.status)); }
  return res.json();
}
function toast(msg, erro=false){ const t=document.getElementById("toast");
  t.textContent=msg; t.style.display="block"; t.style.borderColor=erro?"#ef4444":"#22d3ee";
  clearTimeout(t._h); t._h=setTimeout(()=>t.style.display="none",3000); }
function val(id){ const e=document.getElementById(id); return e?e.value:""; }

// gráficos (mesmo visual do Documentos)
// Cores dos eixos por tema — os gráficos daqui tinham "#94a3ff" fixo e ficavam
// ilegíveis no tema claro. Mesmos helpers do módulo de Entregáveis.
function _chTxt(){ return document.body.classList.contains("theme-light") ? "#475569" : "#94a3ff"; }
function _chTxtStrong(){ return document.body.classList.contains("theme-light") ? "#1e293b" : "#c7d2fe"; }
function _chGrid(){ return document.body.classList.contains("theme-light") ? "rgba(30,41,99,.10)" : "rgba(167,139,250,.06)"; }
const _chFont={size:10,family:"Inter"};
function _eixoX(extra){ return {ticks:{color:_chTxt(),font:_chFont,...(extra||{})},grid:{color:_chGrid()},border:{display:false}}; }
function _eixoY(extra){ return {ticks:{color:_chTxt(),font:_chFont,...(extra||{})},grid:{color:_chGrid()},border:{display:false}}; }
let chartInstances = {};
function _darken(hex,f){ const n=parseInt(hex.slice(1),16); let r=(n>>16)&255,g=(n>>8)&255,b=n&255;
  r=Math.round(r*(1-f)); g=Math.round(g*(1-f)); b=Math.round(b*(1-f)); return `rgb(${r},${g},${b})`; }
function donutGrad(ctx,hex){ const g=ctx.createLinearGradient(0,0,0,160); g.addColorStop(0,hex); g.addColorStop(1,_darken(hex,0.5)); return g; }

/* Tooltip HTML externo ao canvas — mesmo card usado em Documentos e Entregáveis */
function donutTooltipExternal(context){
  const { chart, tooltip } = context;
  let el = document.getElementById("eq-donut-tip");
  if (!el){
    el = document.createElement("div");
    el.id = "eq-donut-tip";
    el.style.cssText = "position:fixed;pointer-events:none;z-index:9999;opacity:0;transition:opacity .1s ease;background:#232847;border:1px solid rgba(167,139,250,.3);border-radius:8px;padding:7px 10px;font:500 12px/1.2 Inter,system-ui,sans-serif;color:#f1f5f9;white-space:nowrap;box-shadow:0 8px 24px rgba(0,0,0,.45);display:flex;align-items:center;gap:7px";
    document.body.appendChild(el);
  }
  if (!tooltip || tooltip.opacity === 0){ el.style.opacity = "0"; return; }
  const dp = tooltip.dataPoints && tooltip.dataPoints[0];
  if (!dp){ el.style.opacity = "0"; return; }
  const dot = (dp.dataset.dotColors && dp.dataset.dotColors[dp.dataIndex]) || "#22d3ee";
  const body = (tooltip.body && tooltip.body[0] && tooltip.body[0].lines[0]) ||
               (dp.label + ": " + dp.formattedValue);
  el.innerHTML = `<span style="width:9px;height:9px;border-radius:50%;background:${dot};flex-shrink:0"></span><span>${esc(body)}</span>`;
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

// ── estado ───────────────────────────────────────────────────────────────
let EQUIP=[], COMPL={}, TAX={categorias:[]}, selCatId=null, EVOL=[], SAUDE=null;

// ── completude (ICE / IDP) ─────────────────────────────────────────────────
// O cálculo mora no servidor (equipamentos_core.py) e chega pronto por
// /api/equipamentos/completude. Antes o módulo baixava TODOS os documentos do
// sistema só para dividir finalizados por aplicáveis, e a fórmula existia só
// aqui — o export e qualquer relatório teriam de reimplementá-la.
const COMPL_VAZIA = {cad:0,reg:0,doc:0,ice:0,idp:null,rev:{},lacunas:[],
  docs_atrasados:0,atraso_max:0,responsaveis:[],reg_estado:"sem_data",reg_dias:null,
  docs_finais:0,docs_alvo:0,docs_faltando:0};
function compl(id){ return COMPL[id] || COMPL_VAZIA; }
function scores(e){ return compl(e && e.id); }
const LABEL_DOC_FALTANDO = "Docs não finalizados";
const faixa = i=> i>=85?"completo":i>=50?"parcial":"inicial";
const FCOLOR = {completo:"#10b981",parcial:"#f59e0b",inicial:"#f43f5e"};
const FBG = {completo:"rgba(16,185,129,.15)",parcial:"rgba(245,158,11,.15)",inicial:"rgba(244,63,94,.15)"};
const cor = v=> v>=85?"#10b981":v>=50?"#f59e0b":"#f43f5e";
const ehBloqueado = e=> e.bloqueado || e.status==="Obsoleto" || e.status==="Descontinuado";

// ── navegação (sidebar) ─────────────────────────────────────────────────────
const TITULO_PAGINA={dashboard:"Dashboard",dev:"Desenvolvimento",lista:"Equipamentos",
  saude:"Saúde do cadastro",cat:"Categorias",consumiveis:"Consumíveis","tipos-cons":"Tipos de consumível"};
function renderPagina(page){
  if(page==="dashboard") renderDashboard();
  if(page==="dev") renderDev();
  if(page==="lista") renderLista();
  if(page==="saude") renderSaude();
  if(page==="cat") renderCategorias();
  if(page==="consumiveis" && typeof renderConsumiveis==="function") renderConsumiveis();
  if(page==="tipos-cons" && typeof renderTiposCons==="function") renderTiposCons();
}
function navigate(page){
  document.querySelectorAll(".nav-item").forEach(el=>el.classList.toggle("active", el.dataset.page===page));
  document.querySelectorAll(".page").forEach(p=>p.classList.remove("active"));
  const el=document.getElementById("page-"+page); if(el) el.classList.add("active");
  document.getElementById("breadcrumb-current").textContent=TITULO_PAGINA[page]||"";
  renderPagina(page);
}

// ── carga ──────────────────────────────────────────────────────────────────
async function loadAll(){
  try{
    const [eqs, completude, tax] = await Promise.all([
      api("/api/equipamentos"), api("/api/equipamentos/completude"), api("/api/equip-taxonomia"),
    ]);
    EQUIP = eqs;
    COMPL = {};
    ((completude&&completude.itens)||[]).forEach(c=>{ COMPL[c.id]=c; });
    TAX = tax || {categorias:[]};
  }catch(e){ toast(e.message||"Erro ao carregar", true); }
  const u=userObj(); const ini=(u.nome||"A").trim()[0]||"A";
  document.getElementById("nav-name").textContent=u.nome||"Usuário";
  document.getElementById("nav-role").textContent=(u.role||"").toUpperCase();
  document.getElementById("nav-avatar").textContent=ini; document.getElementById("top-avatar").textContent=ini;
  if(podeEditar) document.getElementById("btn-novo-eq").style.display="";
  if(podeGerir){ document.getElementById("btn-import").style.display=""; const bp=document.getElementById("btn-import-pareto"); if(bp) bp.style.display=""; }
  preencherSelects();
  renderDashboard(); renderDev(); renderLista(); renderCategorias();
  carregarEvolucao();   // série temporal: não bloqueia a tela se ainda não houver histórico
}
// A curva de evolução vem de uma tabela própria (equipamento_snapshot) e pode
// estar vazia no primeiro dia — por isso não entra no Promise.all da carga.
async function carregarEvolucao(){
  try{ EVOL=await api("/api/equipamentos/evolucao"); }catch(_){ EVOL=[]; }
  if(document.getElementById("page-dashboard").classList.contains("active")) renderEvolucao();
}
function preencherSelects(){
  const opts='<option value="">Todas as categorias</option>'+TAX.categorias.map(c=>`<option value="${c.id}">${esc(c.nome)}</option>`).join("");
  const dc=document.getElementById("dash-cat"); if(dc){ const v=dc.value; dc.innerHTML=opts; dc.value=v; }
  const vc=document.getElementById("dev-cat"); if(vc){ const v=vc.value; vc.innerHTML=opts; vc.value=v; }
  const fc=document.getElementById("eq-f-cat"); if(fc){ const v=fc.value; fc.innerHTML='<option value="">Categoria: todas</option>'+TAX.categorias.map(c=>`<option value="${c.id}">${esc(c.nome)}</option>`).join(""); fc.value=v; }
  const st=[...new Set(EQUIP.map(e=>e.status).filter(Boolean))];
  const fs=document.getElementById("eq-f-status"); if(fs){ const v=fs.value; fs.innerHTML='<option value="">Status: todos</option>'+st.map(s=>`<option>${esc(s)}</option>`).join(""); fs.value=v; }
}

// ══ DASHBOARD (gráficos no padrão do Documentos) ═══════════════════════════
function renderDashboard(){
  if(typeof Chart==="undefined") return;
  const cat=val("dash-cat"), inc=(document.getElementById("dash-bloq")||{}).checked;
  let list = EQUIP.filter(e=> (inc||!ehBloqueado(e)) && (!cat||String(e.categoria_id)===String(cat)));
  const S = list.map(e=>({e, s:scores(e)}));
  const n = S.length, avg=a=> n?Math.round(a.reduce((x,y)=>x+y,0)/n):0;
  const iceAvg=avg(S.map(o=>o.s.ice)), cadAvg=avg(S.map(o=>o.s.cad)), regAvg=avg(S.map(o=>o.s.reg)), docAvg=avg(S.map(o=>o.s.doc));
  document.getElementById("eq-ice-badge").textContent="ICE médio "+iceAvg+"%";

  // KPI rings por faixa
  const cnt={completo:0,parcial:0,inicial:0}; S.forEach(o=>cnt[faixa(o.s.ice)]++);
  const faixas=[["completo","Completo ≥85%"],["parcial","Parcial 50–84%"],["inicial","Inicial <50%"]];
  document.getElementById("kpi-grid").innerHTML=faixas.map(([k,l],i)=>{
    const v=cnt[k], pct=n?Math.round(v/n*100):0;
    return `<div class="kpi-ring"><div class="kpi-ring-canvas" style="width:110px;height:110px"><canvas id="ring${i}" width="110" height="110"></canvas><div class="kpi-ring-val" style="color:${FCOLOR[k]}">${v}</div></div><div class="kpi-ring-label">${l}</div><div class="kpi-ring-delta" style="color:${FCOLOR[k]}">${pct}% da frota</div></div>`;
  }).join("");
  faixas.forEach(([k],i)=>{ const v=cnt[k], pct=n?v/n:0;
    if(chartInstances["ring"+i]) chartInstances["ring"+i].destroy();
    chartInstances["ring"+i]=new Chart(document.getElementById("ring"+i),{type:"doughnut",
      data:{datasets:[{data:[pct*100,100-pct*100],backgroundColor:[FCOLOR[k],FBG[k]],borderWidth:0,hoverOffset:4}]},
      options:{responsive:false,cutout:"78%",plugins:{legend:{display:false},tooltip:{enabled:false}},animation:{animateRotate:true,duration:900}}}); });

  // donut por categoria
  const porCat={}; S.forEach(o=>{ const c=o.e.categoria||"Sem categoria"; porCat[c]=(porCat[c]||0)+1; });
  const cLabels=Object.keys(porCat), cVals=Object.values(porCat);
  const pal=["#10b981","#22d3ee","#f59e0b","#a78bfa","#06b6d4","#f43f5e","#3b82f6"];
  const dColors=cLabels.map((c,i)=>pal[i%pal.length]);
  document.getElementById("donut-total").textContent=n;
  document.getElementById("donut-legend").innerHTML=cLabels.map((c,i)=>`<div class="legend-row" title="${esc(c)}"><span class="legend-dot" style="background:${dColors[i]}"></span><span>${esc(c)}</span><span class="legend-val">${cVals[i]}</span></div>`).join("")||'<div class="muted">Sem dados</div>';
  if(chartInstances.donut) chartInstances.donut.destroy();
  const elD=document.getElementById("cDonut");
  if(elD && cLabels.length){ const bg=dColors.map(c=>donutGrad(elD.getContext("2d"),c));
    chartInstances.donut=new Chart(elD,{type:"doughnut",
      data:{labels:cLabels,datasets:[{data:cVals,backgroundColor:bg,dotColors:dColors,borderWidth:0,borderRadius:8,spacing:3,hoverOffset:6}]},
      options:{responsive:false,cutout:"78%",plugins:{legend:{display:false},tooltip:{enabled:false,external:donutTooltipExternal,callbacks:{label:ctx=>` ${cLabels[ctx.dataIndex]}: ${ctx.parsed} equipamentos`}}},animation:{animateRotate:true,duration:1000}}}); }

  // prog-list = dimensões
  const dims=[["Cadastro",cadAvg],["Regulatório",regAvg],["Documental",docAvg]];
  const dimC=["#22d3ee","#f59e0b","#10b981"];
  document.getElementById("prog-list").innerHTML=dims.map(([l,v],i)=>`<div class="prog-row"><span class="prog-label">${l}</span><div class="prog-track"><div class="prog-fill" style="width:${v}%;background:${dimC[i]}"></div></div><span class="prog-pct">${v}%</span></div>`).join("")+`<div style="margin-top:14px;padding-top:10px;border-top:1px solid var(--border-dim);display:flex;justify-content:space-between"><span style="font-size:10px;color:var(--t3)">ICE médio</span><span style="font-family:var(--font-mono);font-size:14px;font-weight:700;color:var(--cyan)">${iceAvg}%</span></div>`;

  // bar: equipamentos por categoria
  if(chartInstances.bar) chartInstances.bar.destroy();
  const cb=document.getElementById("chartBar");
  if(cb){ const ctx=cb.getContext("2d"); const grad=ctx.createLinearGradient(0,0,0,200); grad.addColorStop(0,"#22d3ee"); grad.addColorStop(1,"#3b82f6");
    chartInstances.bar=new Chart(ctx,{type:"bar",data:{labels:cLabels,datasets:[{data:cVals,backgroundColor:grad,dotColors:dColors,borderRadius:8,borderWidth:0}]},
      options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{enabled:false,external:donutTooltipExternal,callbacks:{label:ctx=>` ${ctx.label}: ${ctx.parsed.y} equipamentos`}}},
        scales:{x:{ticks:{color:_chTxt(),font:_chFont},grid:{display:false},border:{display:false}},y:_eixoY()}}}); }

  // bar horizontal: lacunas mais comuns (a lista de lacunas vem do servidor)
  const gaps={}; S.forEach(o=>{ (o.s.lacunas||[]).forEach(l=>{ gaps[l]=(gaps[l]||0)+1; });
    if(o.s.docs_faltando) gaps[LABEL_DOC_FALTANDO]=(gaps[LABEL_DOC_FALTANDO]||0)+o.s.docs_faltando; });
  const top=Object.entries(gaps).sort((a,b)=>b[1]-a[1]).slice(0,6);
  if(chartInstances.gaps) chartInstances.gaps.destroy();
  const cg=document.getElementById("chartGaps");
  if(cg){ chartInstances.gaps=new Chart(cg,{type:"bar",
      data:{labels:top.map(t=>t[0]),datasets:[{data:top.map(t=>t[1]),backgroundColor:"#a78bfa",dotColors:top.map(()=>"#a78bfa"),borderRadius:8,borderWidth:0}]},
      options:{indexAxis:"y",responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{enabled:false,external:donutTooltipExternal,callbacks:{label:ctx=>` ${ctx.label}: ${ctx.parsed.x}`}}},
        scales:{x:_eixoX(),y:{ticks:{color:_chTxtStrong(),font:{size:11,family:"Inter"}},grid:{display:false},border:{display:false}}}}}); }

  renderRisco(S);
  renderEvolucao();

  // Worklist: ICE mais baixo primeiro, com o risco que vem dos documentos.
  // Antes a tabela mostrava só completude — um equipamento com ICE 70% e 3
  // documentos vencidos parecia menos urgente que outro com 65% em dia.
  const rank=[...S].sort((a,b)=> (b.s.docs_atrasados-a.s.docs_atrasados) || (a.s.ice-b.s.ice)).slice(0,10);
  const mini=v=>`<span class="mono" style="color:${cor(v)}">${v}%</span>`;
  document.getElementById("dash-table").innerHTML=rank.map(o=>{
    const atr=o.s.docs_atrasados
      ? `<span class="mono" style="color:#f43f5e" title="Pior atraso: ${o.s.atraso_max} dia(s)">${o.s.docs_atrasados}</span>`
      : '<span class="muted">—</span>';
    const resp=o.e.responsavel || (o.s.responsaveis||[])[0] || "";
    return `<tr tabindex="0" role="button" aria-label="Abrir ficha de ${esc(o.e.nome)}" onclick="openView(${o.e.id})" onkeydown="teclaAbre(event,${o.e.id})" style="cursor:pointer"><td class="bold">${esc(o.e.nome)}</td><td class="mono">${esc(o.e.sku||"—")}</td><td>${mini(o.s.cad)}</td><td>${mini(o.s.reg)}</td><td>${mini(o.s.doc)}</td><td><span class="sg-badge ${o.s.ice>=85?'sg-finalizado':o.s.ice>=50?'sg-progresso':'sg-pendente'}">${o.s.ice}%</span></td><td class="num">${atr}</td><td>${resp?esc(resp):'<span class="muted">sem dono</span>'}</td><td class="muted" style="font-size:11px">${esc((o.e.updated_em||"").slice(0,10)||"—")}</td></tr>`;
  }).join("")||'<tr><td colspan="9" style="text-align:center;color:var(--t4);padding:32px">Sem dados</td></tr>';
}

// Abrir por Enter/Espaço — cards e linhas eram <div>/<tr> com onclick, sem foco
// nem acesso por teclado, apesar do resto da página ter skip-link e aria-label.
function teclaAbre(ev,id){
  if(ev.key==="Enter"||ev.key===" "){ ev.preventDefault(); openView(id); }
}

// ── risco documental e regulatório (dados que já vinham e não eram usados) ──
function renderRisco(S){
  const el=document.getElementById("risco-list"); if(!el) return;
  const atrasados=S.filter(o=>o.s.docs_atrasados>0).sort((a,b)=>b.s.atraso_max-a.s.atraso_max);
  const docsAtrasados=atrasados.reduce((t,o)=>t+o.s.docs_atrasados,0);
  const vencidos=S.filter(o=>o.s.reg_estado==="vencido");
  const vencendo=S.filter(o=>o.s.reg_estado==="vencendo");
  const semDono=S.filter(o=>!(o.e.responsavel||"").trim() && !(o.s.responsaveis||[]).length);
  const linhas=[
    ["Equipamentos com documento atrasado", atrasados.length, "#f43f5e",
      docsAtrasados?`${docsAtrasados} documento(s), pior atraso ${atrasados[0].s.atraso_max} dia(s)`:""],
    ["Registro ANVISA vencido", vencidos.length, "#f43f5e",
      vencidos.length?vencidos.slice(0,3).map(o=>o.e.nome).join(", "):""],
    ["Registro vence em até 90 dias", vencendo.length, "#f59e0b",
      vencendo.length?vencendo.slice(0,3).map(o=>o.e.nome).join(", "):""],
    ["Sem responsável definido", semDono.length, "#94a3b8", ""],
  ];
  el.innerHTML=linhas.map(([l,v,c,sub])=>
    `<div class="prog-row" style="align-items:flex-start"><span class="prog-label" style="flex:1">${l}${sub?`<div class="muted" style="font-size:10px;margin-top:2px">${esc(sub)}</div>`:""}</span><span class="mono" style="font-weight:700;color:${v?c:'var(--t4)'}">${v}</span></div>`
  ).join("");
}

// ── evolução do ICE médio (série temporal do equipamento_snapshot) ──────────
function renderEvolucao(){
  const cv=document.getElementById("chartEvol"); if(!cv||typeof Chart==="undefined") return;
  const hint=document.getElementById("evol-hint");
  if(chartInstances.evol){ chartInstances.evol.destroy(); chartInstances.evol=null; }
  if(!EVOL.length){
    if(hint) hint.textContent="A série começa a partir da primeira foto diária — volte amanhã para ver a curva.";
    return;
  }
  const pts=EVOL.slice(-60);
  const delta=pts.length>1?pts[pts.length-1].ice-pts[0].ice:0;
  if(hint) hint.textContent=pts.length>1
    ? `${pts.length} medições · ${delta>=0?"+":""}${delta} ponto(s) desde ${pts[0].data}`
    : "Primeira medição registrada. A curva aparece a partir da segunda.";
  const ctx=cv.getContext("2d");
  const grad=ctx.createLinearGradient(0,0,0,200);
  grad.addColorStop(0,"rgba(34,211,238,.35)"); grad.addColorStop(1,"rgba(34,211,238,0)");
  chartInstances.evol=new Chart(ctx,{type:"line",
    data:{labels:pts.map(p=>p.data.slice(5)),datasets:[
      {label:"ICE",data:pts.map(p=>p.ice),borderColor:"#22d3ee",backgroundColor:grad,fill:true,tension:.35,pointRadius:pts.length>20?0:3,borderWidth:2,dotColors:pts.map(()=>"#22d3ee")},
      {label:"IDP",data:pts.map(p=>p.idp),borderColor:"#a78bfa",fill:false,tension:.35,pointRadius:0,borderWidth:2,borderDash:[4,4],dotColors:pts.map(()=>"#a78bfa")}]},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},
      plugins:{legend:{position:"bottom",labels:{color:_chTxt(),font:_chFont,boxWidth:10}},
        tooltip:{enabled:false,external:donutTooltipExternal,callbacks:{label:ctx=>` ${ctx.dataset.label}: ${ctx.parsed.y==null?"—":ctx.parsed.y+"%"}`}}},
      scales:{x:{ticks:{color:_chTxt(),font:_chFont,maxTicksLimit:8},grid:{display:false},border:{display:false}},
              y:_eixoY({precision:0,callback:v=>v+"%"})}}});
}

// ══ DESENVOLVIMENTO (IDP — 6 revisões + Pareto) ════════════════════════════
// 3 itens são marcados à mão (rev_*); 3 derivam do status dos documentos.
const DEV_ITENS = ["cadastro","estrutura","it","checklists","manual_usuario","descritivo"];
const DEV_ITEM_LABEL = {cadastro:"Cadastro",estrutura:"Estrutura",it:"IT",checklists:"Checklists",manual_usuario:"Manual usuário",descritivo:"Descritivo"};
const DEV_ITEM_CAMPO = {cadastro:"rev_cadastro",estrutura:"rev_estrutura",descritivo:"rev_descritivo"};  // só os manuais
const EST_COR = {"Revisado":"#10b981","Em revisão":"#f59e0b","Pendente":"#f43f5e","N/A":"#64748b"};
const EST_BG  = {"Revisado":"rgba(16,185,129,.15)","Em revisão":"rgba(245,158,11,.15)","Pendente":"rgba(244,63,94,.15)","N/A":"rgba(100,116,139,.15)"};
const EST_TODOS = ["Pendente","Em revisão","Revisado","N/A"];
// Os 6 estados e o IDP são calculados no servidor (mesma regra do export e do
// snapshot); aqui só lemos o que veio em /api/equipamentos/completude.
function revState(e,item){ return (compl(e&&e.id).rev||{})[item] || "Pendente"; }
function idp(e){ return compl(e&&e.id).idp; }
const _CLASSE_ORD={"A":0,"B":1,"C":2,"":3};
function _prioridade(a,b){
  const ca=_CLASSE_ORD[a.pareto_classe||""]??3, cb=_CLASSE_ORD[b.pareto_classe||""]??3;
  if(ca!==cb) return ca-cb;
  const qa=a.qtd_saidas||0, qb=b.qtd_saidas||0;
  if(qa!==qb) return qb-qa;                                   // mais vendidos primeiro
  const ia=idp(a), ib=idp(b);
  return (ia==null?101:ia)-(ib==null?101:ib);                 // menos completos primeiro
}
async function setRev(id,campo,valor){
  try{ const r=await api("/api/equipamentos/"+id,{method:"PATCH",body:JSON.stringify({[campo]:valor})});
    const e=_eqById(id); if(e) e[campo]=valor;
    // O PATCH devolve a completude recalculada: sem isso o IDP da linha só
    // acertaria no próximo loadAll.
    if(r&&r.equipamento&&r.equipamento.completude) COMPL[id]=r.equipamento.completude;
    renderDev();
  }catch(err){ toast(err.message||"Erro ao gravar",true); }
}
function _chipAuto(estado){
  return `<span class="rev-chip" title="Derivado do status do documento" style="color:${EST_COR[estado]};background:${EST_BG[estado]}">${estado}</span>`;
}
function _chipManual(id,campo,estado){
  if(!podeEditar) return `<span class="rev-chip" style="color:${EST_COR[estado]};background:${EST_BG[estado]}">${estado}</span>`;
  const opts=EST_TODOS.map(s=>`<option${s===estado?" selected":""}>${s}</option>`).join("");
  return `<select class="rev-sel" style="color:${EST_COR[estado]};background:${EST_BG[estado]}" onchange="setRev(${id},'${campo}',this.value)" aria-label="${DEV_ITEM_LABEL[campo==='rev_cadastro'?'cadastro':campo==='rev_estrutura'?'estrutura':'descritivo']}">${opts}</select>`;
}
function _idpBadge(v){ if(v==null) return '<span class="sg-badge">—</span>';
  return `<span class="sg-badge ${v>=85?'sg-finalizado':v>=50?'sg-progresso':'sg-pendente'}">${v}%</span>`; }
function renderDev(){
  if(typeof Chart==="undefined") return;
  const cls=val("dev-classe"), cat=val("dev-cat"), inc=(document.getElementById("dev-bloq")||{}).checked;
  let list=EQUIP.filter(e=> (inc||!ehBloqueado(e)) && (!cat||String(e.categoria_id)===String(cat)));
  if(cls) list=list.filter(e=> cls==="-" ? !(e.pareto_classe||"") : (e.pareto_classe||"")===cls );
  const S=list.map(e=>({e, idp:idp(e)})).sort((a,b)=>_prioridade(a.e,b.e));
  const comIdp=S.filter(o=>o.idp!=null);
  const media=comIdp.length?Math.round(comIdp.reduce((x,o)=>x+o.idp,0)/comIdp.length):0;
  document.getElementById("dev-idp-badge").textContent="IDP médio "+media+"%";

  // KPIs (rings por faixa + Classe A pendente)
  const cnt={completo:0,parcial:0,inicial:0}; comIdp.forEach(o=>cnt[faixa(o.idp)]++);
  const classeApend=S.filter(o=>(o.e.pareto_classe||"")==="A" && o.idp!=null && o.idp<85).length;
  const kpis=[["completo","Completo ≥85%",cnt.completo,comIdp.length],
              ["parcial","Parcial 50–84%",cnt.parcial,comIdp.length],
              ["inicial","Inicial <50%",cnt.inicial,comIdp.length]];
  let kh=kpis.map(([k,l,v,tot],i)=>{ const pct=tot?Math.round(v/tot*100):0;
    return `<div class="kpi-ring"><div class="kpi-ring-canvas" style="width:110px;height:110px"><canvas id="dring${i}" width="110" height="110"></canvas><div class="kpi-ring-val" style="color:${FCOLOR[k]}">${v}</div></div><div class="kpi-ring-label">${l}</div><div class="kpi-ring-delta" style="color:${FCOLOR[k]}">${pct}% dos avaliados</div></div>`;
  }).join("");
  kh+=`<div class="kpi-ring"><div class="kpi-ring-canvas" style="width:110px;height:110px;display:flex;align-items:center;justify-content:center"><div class="kpi-ring-val" style="position:static;color:${classeApend?'#f43f5e':'#10b981'};font-size:34px">${classeApend}</div></div><div class="kpi-ring-label">Classe A incompletos</div><div class="kpi-ring-delta muted">prioridade máxima</div></div>`;
  document.getElementById("dev-kpi-grid").innerHTML=kh;
  kpis.forEach(([k,l,v,tot],i)=>{ const pct=tot?v/tot:0;
    if(chartInstances["dring"+i]) chartInstances["dring"+i].destroy();
    chartInstances["dring"+i]=new Chart(document.getElementById("dring"+i),{type:"doughnut",
      data:{datasets:[{data:[pct*100,100-pct*100],backgroundColor:[FCOLOR[k],FBG[k]],borderWidth:0}]},
      options:{responsive:false,cutout:"78%",plugins:{legend:{display:false},tooltip:{enabled:false}},animation:{animateRotate:true,duration:800}}}); });

  // barra empilhada: faixa de IDP por classe ABC
  const classesLbl=["A","B","C","Sem classe"];
  const porClasse=classesLbl.map(c=>{ const key=c==="Sem classe"?"":c;
    const grp=comIdp.filter(o=>(o.e.pareto_classe||"")===key);
    return {completo:grp.filter(o=>o.idp>=85).length,parcial:grp.filter(o=>o.idp>=50&&o.idp<85).length,inicial:grp.filter(o=>o.idp<50).length}; });
  if(chartInstances.devClasse) chartInstances.devClasse.destroy();
  const cc=document.getElementById("devChartClasse");
  if(cc){ chartInstances.devClasse=new Chart(cc,{type:"bar",
    data:{labels:classesLbl,datasets:[
      {label:"Completo",data:porClasse.map(p=>p.completo),backgroundColor:FCOLOR.completo,dotColors:classesLbl.map(()=>FCOLOR.completo),borderRadius:6,stack:"s"},
      {label:"Parcial", data:porClasse.map(p=>p.parcial), backgroundColor:FCOLOR.parcial, dotColors:classesLbl.map(()=>FCOLOR.parcial), borderRadius:6,stack:"s"},
      {label:"Inicial", data:porClasse.map(p=>p.inicial), backgroundColor:FCOLOR.inicial, dotColors:classesLbl.map(()=>FCOLOR.inicial), borderRadius:6,stack:"s"}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:"bottom",labels:{color:_chTxt(),font:_chFont,boxWidth:10}},tooltip:{enabled:false,external:donutTooltipExternal,callbacks:{label:ctx=>` ${ctx.dataset.label}: ${ctx.parsed.y}`}}},
      scales:{x:{stacked:true,ticks:{color:_chTxt(),font:{size:11,family:"Inter"}},grid:{display:false},border:{display:false}},
              y:{stacked:true,...(_eixoY({precision:0}))}}}}); }

  // barra horizontal: revisões mais pendentes (por item, na frota filtrada)
  const pend=DEV_ITENS.map(it=>[DEV_ITEM_LABEL[it], S.filter(o=>{const s=revState(o.e,it); return s!=="Revisado"&&s!=="N/A";}).length]).sort((a,b)=>b[1]-a[1]);
  if(chartInstances.devItens) chartInstances.devItens.destroy();
  const ci=document.getElementById("devChartItens");
  if(ci){ chartInstances.devItens=new Chart(ci,{type:"bar",
    data:{labels:pend.map(p=>p[0]),datasets:[{data:pend.map(p=>p[1]),backgroundColor:"#a78bfa",dotColors:pend.map(()=>"#a78bfa"),borderRadius:8}]},
    options:{indexAxis:"y",responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{enabled:false,external:donutTooltipExternal,callbacks:{label:ctx=>` ${ctx.label}: ${ctx.parsed.x} pendentes`}}},
      scales:{x:_eixoX({precision:0}),
              y:{ticks:{color:_chTxtStrong(),font:{size:11,family:"Inter"}},grid:{display:false},border:{display:false}}}}}); }

  // matriz priorizada
  const classeBadge=c=> c?`<span class="abc-badge abc-${c}">${c}</span>`:'<span class="muted">—</span>';
  document.getElementById("dev-table").innerHTML=S.map(o=>{ const e=o.e;
    const cel=it=> DEV_ITEM_CAMPO[it] ? _chipManual(e.id,DEV_ITEM_CAMPO[it],revState(e,it)) : _chipAuto(revState(e,it));
    return `<tr><td class="bold">${esc(e.nome)}${e.sku?`<div class="muted mono" style="font-size:10px">${esc(e.sku)}</div>`:""}</td>`+
      `<td>${classeBadge(e.pareto_classe||"")}</td><td class="num mono">${e.qtd_saidas||"—"}</td>`+
      `<td>${cel("cadastro")}</td><td>${cel("estrutura")}</td><td>${cel("it")}</td><td>${cel("checklists")}</td><td>${cel("manual_usuario")}</td><td>${cel("descritivo")}</td>`+
      `<td>${_idpBadge(o.idp)}</td></tr>`;
  }).join("")||'<tr><td colspan="10" style="text-align:center;color:var(--t4);padding:32px">Sem equipamentos no filtro</td></tr>';
}
// import Pareto (Qtd de saídas + Classe ABC)
function abrirImportPareto(){ document.getElementById("pareto-preview").innerHTML="—";
  document.getElementById("btn-pareto-aplicar").style.display="none"; document.getElementById("pareto-file").value=""; openBaseModal("pareto"); }
async function rodarImportPareto(dryrun){
  const f=document.getElementById("pareto-file").files[0];
  if(!f){ document.getElementById("pareto-preview").innerHTML='<span style="color:#f43f5e">Selecione o arquivo do Pareto.</span>'; return; }
  const fd=new FormData(); fd.append("arquivo",f);
  document.getElementById("pareto-preview").innerHTML="Processando…";
  try{
    const res=await fetch("/api/equipamentos/import-pareto?dryrun="+(dryrun?"1":"0"),{method:"POST",headers:{"Authorization":"Bearer "+token()},body:fd});
    const rel=await res.json();
    if(!res.ok){ document.getElementById("pareto-preview").innerHTML=`<span style="color:#f43f5e">${esc(rel.erro||"Falha")}</span>`; return; }
    const sm=(rel.sem_match||[]).slice(0,6).map(x=>`${esc(x.sku)} (${esc(x.classe||"—")})`).join(", ");
    document.getElementById("pareto-preview").innerHTML=`<b>${rel.aplicado?"Importação aplicada":"Prévia"}</b> — aba "${esc(rel.aba)}", ${rel.total_linhas} linhas<br>A atualizar: <b>${rel.a_atualizar}</b> · Sem equipamento: <b>${rel.sem_match_n}</b> · Zerados: <b>${rel.limpos_n}</b>${sm?`<div class="muted" style="font-size:11px;margin-top:8px">Sem match: ${sm}${rel.sem_match_n>6?"…":""}</div>`:""}`;
    document.getElementById("btn-pareto-aplicar").style.display=(dryrun)?"inline-flex":"none";
    if(!dryrun){ toast(`Pareto: ${rel.a_atualizar} atualizados`); await loadAll(); navigate("dev"); setTimeout(()=>closeModal("pareto"),1200); }
  }catch(e){ document.getElementById("pareto-preview").innerHTML=`<span style="color:#f43f5e">${esc(e.message)}</span>`; }
}

// ══ LISTA ══════════════════════════════════════════════════════════════════
// A busca refiltrava e repintava a frota inteira a cada tecla. Com o debounce o
// trabalho acontece uma vez por pausa de digitação.
let _buscaTimer=null;
function buscaLista(){ clearTimeout(_buscaTimer); _buscaTimer=setTimeout(renderLista,180); }

const _CLASSE_ORD_LISTA={"A":0,"B":1,"C":2,"":3};
const ORDENADORES={
  nome:      (a,b)=>(a.e.nome||"").localeCompare(b.e.nome||""),
  ice:       (a,b)=>a.s.ice-b.s.ice || (a.e.nome||"").localeCompare(b.e.nome||""),
  "ice-desc":(a,b)=>b.s.ice-a.s.ice || (a.e.nome||"").localeCompare(b.e.nome||""),
  atraso:    (a,b)=>b.s.docs_atrasados-a.s.docs_atrasados || b.s.atraso_max-a.s.atraso_max || a.s.ice-b.s.ice,
  classe:    (a,b)=>(_CLASSE_ORD_LISTA[a.e.pareto_classe||""]??3)-(_CLASSE_ORD_LISTA[b.e.pareto_classe||""]??3)
                    || (b.e.qtd_saidas||0)-(a.e.qtd_saidas||0),
  atualizado:(a,b)=>(a.e.updated_iso||"").localeCompare(b.e.updated_iso||""),
};

function renderLista(){
  const q=(val("eq-busca")||"").toLowerCase(), cat=val("eq-f-cat"),
        st=val("eq-f-status"), inc=(document.getElementById("eq-f-bloq")||{}).checked;
  let list=EQUIP.filter(e=>(inc||!ehBloqueado(e))
    &&(!cat||String(e.categoria_id)===String(cat))
    &&(!st||e.status===st)
    &&(!q||[e.nome,e.sku,e.nome_tecnico,e.fabricante,e.sku_importacao,e.responsavel]
        .filter(Boolean).join(" ").toLowerCase().includes(q)));
  const S=list.map(e=>({e,s:scores(e)}));
  S.sort(ORDENADORES[val("eq-ordem")||"nome"]||ORDENADORES.nome);
  const atrasados=S.filter(o=>o.s.docs_atrasados>0).length;
  document.getElementById("eq-badge").textContent=list.length+" equip."+(atrasados?` · ${atrasados} com atraso`:"");
  document.getElementById("eq-grid").innerHTML=S.map(({e,s})=>{
    const f=faixa(s.ice);
    const risco=[];
    if(s.docs_atrasados) risco.push(`<span class="eq-chip risco" title="Pior atraso: ${s.atraso_max} dia(s)">${s.docs_atrasados} atrasado${s.docs_atrasados>1?"s":""}</span>`);
    if(s.reg_estado==="vencido") risco.push('<span class="eq-chip risco">ANVISA vencida</span>');
    else if(s.reg_estado==="vencendo") risco.push(`<span class="eq-chip alerta">Vence em ${s.reg_dias}d</span>`);
    return `<div class="equip-card st-${f==='completo'?'green':f==='parcial'?'amber':'red'}" tabindex="0" role="button" aria-label="Abrir ficha de ${esc(e.nome)} — ICE ${s.ice}%" onclick="openView(${e.id})" onkeydown="teclaAbre(event,${e.id})">
      <div class="eq-ring" style="background:conic-gradient(${FCOLOR[f]} ${s.ice*3.6}deg, var(--bg-elevated) 0)"><span>${s.ice}%</span></div>
      <div class="equip-card-name" style="padding-right:46px">${esc(e.nome)}</div>
      <div class="equip-card-sku">${e.sku?esc(e.sku):'<span class="muted">sem SKU</span>'}</div>
      <div class="eq-card-meta">${e.categoria?`<span class="eq-chip">${esc(e.categoria)}</span>`:""}${ehBloqueado(e)?`<span class="eq-chip bloq">${esc(e.status)}</span>`:""}${risco.join("")}</div>
    </div>`;
  }).join("")||'<div class="muted" style="grid-column:1/-1;text-align:center;padding:30px">Nenhum equipamento.</div>';
}

// ══ FICHA ══════════════════════════════════════════════════════════════════
let fichaId=null, fichaTab="geral", FICHA_ITENS={consumivel:[],acessorio:[]}, FICHA_CONS=[], fichaFromView=false;
function _eqById(id){ return EQUIP.find(e=>e.id===id) || null; }
function famsDe(catId){ const c=TAX.categorias.find(x=>String(x.id)===String(catId)); return c?(c.familias||[]):[]; }

async function abrirFicha(id, fromView){
  fichaId=id; fichaTab="geral"; FICHA_ITENS={consumivel:[],acessorio:[]}; FICHA_CONS=[];
  fichaFromView=!!(fromView&&id);
  const e = id ? _eqById(id) : {id:null,nome:"",status:"Ativo",categoria_id:null,familia_id:null};
  const s = id ? scores(e) : {cad:0,reg:0,doc:0,ice:0};
  if(id){ try{ const det=await api("/api/equipamentos/"+id);
      FICHA_ITENS={consumivel:det.consumiveis||[], acessorio:det.acessorios||[]};
      FICHA_CONS=det.consumiveis_vinc||[]; }catch(_){}
    // catálogo de consumíveis p/ o seletor da aba Consumíveis (só escolher existentes)
    if(typeof consLoaded!=='undefined' && !consLoaded){ try{ await loadCons(); }catch(_){ } }
  }
  document.getElementById("eq-ficha-del").style.display = (id&&podeGerir)?"inline-flex":"none";
  document.getElementById("eq-ficha-save").style.display = podeEditar?"inline-flex":"none";
  document.getElementById("eq-ficha-head").innerHTML = `
    <div class="eq-fhead">
      <div><div class="eq-fname"><span class="eq-fdot" style="background:${FCOLOR[faixa(s.ice)]}"></span>${esc(e.nome||"Novo equipamento")}</div>
      <div class="eq-fsub">${e.sku?("SKU "+esc(e.sku)+" · "):""}ICE ${s.ice}% · ${esc(e.status||"Ativo")}</div></div>
      <button class="btn btn-ghost btn-sm" onclick="fecharFicha()" aria-label="Fechar" style="padding:4px 10px">✕</button>
    </div>`;
  const tabs=[["geral","Geral"],["tecnico","Técnico"],["reg","Regulatório"],["dev","Desenvolvimento"],["consumivel","Consumíveis"],["acessorio","Acessórios"],["hist","Histórico"]];
  document.getElementById("eq-ficha-tabs").innerHTML=tabs.map(([k,l])=>`<button class="equip-modal-tab ${k===fichaTab?'active':''}" onclick="fichaSwitch('${k}')">${l}</button>`).join("");
  document.getElementById("eq-ficha-panels").innerHTML=tabs.map(([k])=>`<div class="equip-tab-panel ${k===fichaTab?'active':''}" data-panel="${k}">${painelFicha(k,e)}</div>`).join("");
  onCatChange(true);
  fichaRegToggle();
  openBaseModal("eq");
}
function fichaSwitch(k){
  fichaTab=k;
  document.querySelectorAll("#eq-ficha-tabs .equip-modal-tab").forEach(b=>b.classList.toggle("active",(b.getAttribute("onclick")||"").includes("'"+k+"'")));
  document.querySelectorAll("#eq-ficha-panels .equip-tab-panel").forEach(p=>p.classList.toggle("active",p.dataset.panel===k));
  if(k==="hist" && fichaId) carregarHistorico(fichaId);
}
function fld(label,id,v,ph){ return `<div class="form-group"><label class="form-label">${label}</label><input class="form-input" id="${id}" value="${esc(v||"")}" placeholder="${ph||""}"></div>`; }
function painelFicha(k,e){
  if(k==="geral"){
    const catOpts='<option value="">—</option>'+TAX.categorias.map(c=>`<option value="${c.id}" ${String(e.categoria_id)===String(c.id)?'selected':''}>${esc(c.nome)}</option>`).join("");
    const stOpts=["Ativo","Obsoleto","Descontinuado"].map(s=>`<option ${e.status===s?'selected':''}>${s}</option>`).join("");
    return `<div class="g2">${fld("SKU de Venda","f-sku",e.sku)}${fld("SKU de Importação","f-sku_importacao",e.sku_importacao)}</div>
      <div class="g2">${fld("Nome comercial","f-nome",e.nome)}${fld("Nome técnico","f-nome_tecnico",e.nome_tecnico)}</div>
      <div class="g2">
        <div class="form-group"><label class="form-label">Categoria</label><select class="form-input" id="f-categoria_id" onchange="onCatChange()">${catOpts}</select></div>
        <div class="form-group"><label class="form-label">Família</label><select class="form-input" id="f-familia_id"></select></div>
      </div>
      ${fld("Responsável pelo cadastro","f-responsavel",e.responsavel,"quem cobra as pendências")}
      <div class="g2">
        <div class="form-group"><label class="form-label">Status</label><select class="form-input" id="f-status">${stOpts}</select></div>
        <div class="form-group"><label class="form-label">Bloqueado</label><label class="muted" style="display:flex;align-items:center;gap:8px;padding-top:9px"><input type="checkbox" id="f-bloqueado" ${e.bloqueado?'checked':''}> equipamento bloqueado</label></div>
      </div>
      <div class="form-group"><label class="form-label">Descrição (descritivo)</label><textarea class="form-input" id="f-descricao" rows="3" placeholder="Aplicação, princípio, diferenciais…">${esc(e.descricao||"")}</textarea></div>
      <div class="form-group"><label class="form-label">Observações (internas)</label><textarea class="form-input" id="f-observacoes" rows="2">${esc(e.observacoes||"")}</textarea></div>`;
  }
  if(k==="tecnico") return `<div class="g2">${fld("Fabricante","f-fabricante",e.fabricante)}${fld("Código do fabricante","f-codigo_fabricante",e.codigo_fabricante)}</div>
      ${fld("Nome original","f-nome_original",e.nome_original)}
      <div class="form-group"><label class="form-label">Armazenamento base</label><input class="form-input" id="f-armazenamento_base" value="${esc(e.armazenamento_base||"")}"></div>`;
  if(k==="reg"){
    const clOpts=["","RUO","IVD"].map(v=>`<option value="${v}" ${e.classificacao_reg===v?'selected':''}>${v||"— não definido —"}</option>`).join("");
    return `<div class="g2">
        <div class="form-group"><label class="form-label">Classificação regulatória</label><select class="form-input" id="f-classificacao_reg" onchange="fichaRegToggle()">${clOpts}</select></div>
        ${fld("Registro ANVISA (nº)","f-anvisa",e.anvisa)}
      </div>
      <div class="g2"><div class="form-group"><label class="form-label">Data de registro</label><input class="form-input" type="date" id="f-anvisa_registro" value="${esc(e.anvisa_registro||"")}"></div><div class="form-group"><label class="form-label">Validade</label><input class="form-input" type="date" id="f-anvisa_validade" value="${esc(e.anvisa_validade||"")}"></div></div>
      <div class="g2">
        <div class="form-group"><label class="form-label">Classe de risco</label><select class="form-input" id="f-classe_risco">${
          ["","I","II","III","IV"].map(v=>`<option value="${v}" ${e.classe_risco===v?'selected':''}>${v||"— não definida —"}</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Situação do registro</label><select class="form-input" id="f-situacao_regulatoria">${
          ["","Vigente","Em renovação","Cancelado","Não aplicável"].map(v=>`<option value="${v}" ${e.situacao_regulatoria===v?'selected':''}>${v||"— não definida —"}</option>`).join("")}</select></div>
      </div>
      <p class="muted" style="font-size:12px" id="reg-hint">RUO (uso em pesquisa) não exige registro ANVISA.</p>
      <p class="muted" style="font-size:11px">Validade vencida deixa de contar como campo preenchido no ICE regulatório. Classe de risco e situação são coletadas, mas ainda ficam fora do índice.</p>`;
  }
  if(k==="dev"){
    const selRev=(campo,label)=>{ const cur=e[campo]||"Pendente";
      const opts=EST_TODOS.map(s=>`<option${s===cur?" selected":""}>${s}</option>`).join("");
      return `<div class="form-group"><label class="form-label">${label}</label><select class="form-input" id="f-${campo}">${opts}</select></div>`; };
    const auto=(item,label)=>{ const st=e.id?revState(e,item):"Pendente";
      return `<div class="form-group"><label class="form-label">${label}</label><div style="padding-top:6px">${_chipAuto(st)}</div></div>`; };
    const v=e.id?idp(e):null;
    return `<div class="g2">${selRev("rev_cadastro","Revisão de cadastro")}${selRev("rev_estrutura","Revisão de estrutura")}</div>
      <div class="g2">${selRev("rev_descritivo","Revisão de descritivo técnico")}<div class="form-group"><label class="form-label">IDP atual</label><div style="padding-top:6px">${_idpBadge(v)}</div></div></div>
      <div class="g2" style="grid-template-columns:1fr 1fr 1fr">${auto("it","Revisão de IT")}${auto("checklists","Revisão de checklists")}${auto("manual_usuario","Revisão de manual de usuário")}</div>
      <p class="muted" style="font-size:12px">IT, Checklists e Manual derivam do status dos documentos (edite no módulo Documentos). O IDP recalcula ao salvar.</p>`;
  }
  if(k==="consumivel") return painelConsVinc(e);
  if(k==="acessorio") return painelItens(k,e);
  return painelHistorico(e);
}

// ── Histórico da ficha (trilha de-para + evolução do ICE) ───────────────────
const HIST_LABEL={nome:"Nome comercial",nome_tecnico:"Nome técnico",nome_original:"Nome original",
  descricao:"Descrição",sku:"SKU de Venda",sku_importacao:"SKU de Importação",
  classificacao_reg:"Classificação regulatória",anvisa:"Registro ANVISA",anvisa_registro:"Data de registro",
  anvisa_validade:"Validade ANVISA",fabricante:"Fabricante",codigo_fabricante:"Código do fabricante",
  status:"Status",observacoes:"Observações",armazenamento_base:"Armazenamento base",responsavel:"Responsável",
  bloqueado:"Bloqueado",categoria_id:"Categoria",familia_id:"Família",
  rev_cadastro:"Revisão de cadastro",rev_estrutura:"Revisão de estrutura",rev_descritivo:"Revisão de descritivo",
  ativo:"Ativo"};
const HIST_EVENTO={create:"criação",update:"alteração",delete:"exclusão",import:"importação"};
// O conteúdo é carregado só quando a aba é aberta (fichaSwitch): o painel fica
// display:none até lá, e o Chart.js desenharia num canvas de tamanho zero.
function painelHistorico(e){
  if(!e||!e.id) return '<p class="muted">Salve o equipamento primeiro para ver o histórico.</p>';
  return `<div id="hist-evol" style="height:150px;position:relative;margin-bottom:14px"><canvas id="chartHistEvol" role="img" aria-label="Evolução do ICE deste equipamento"></canvas></div>
    <div id="hist-body"><p class="muted">Carregando histórico…</p></div>`;
}
async function carregarHistorico(id){
  let linhas=[], evol=null;
  try{ [linhas,evol]=await Promise.all([
        api("/api/equipamentos/"+id+"/historico"),
        api("/api/equipamentos/"+id+"/evolucao").catch(()=>null)]); }
  catch(err){ const b=document.getElementById("hist-body");
    if(b) b.innerHTML=`<p class="muted">Não foi possível carregar o histórico: ${esc(err.message||"erro")}</p>`;
    return; }
  const body=document.getElementById("hist-body"); if(!body) return;
  const fmt=v=>v===""||v==null?'<span class="muted">—</span>':esc(String(v).length>60?String(v).slice(0,60)+"…":v);
  body.innerHTML=linhas.length
    ? `<table class="vw-itbl"><thead><tr><th style="width:130px">Quando</th><th>Campo</th><th>De</th><th>Para</th><th style="width:150px">Por</th></tr></thead><tbody>${
        linhas.map(l=>`<tr><td class="muted" style="font-size:11px">${esc(l.em)}</td>`+
          `<td>${esc(HIST_LABEL[l.campo]||l.campo||HIST_EVENTO[l.evento]||"—")}</td>`+
          `<td>${fmt(l.valor_antigo)}</td><td>${fmt(l.valor_novo)}</td>`+
          `<td class="muted" style="font-size:11px">${esc(l.por||"—")}</td></tr>`).join("")}</tbody></table>`
    : '<p class="muted">Nenhuma alteração registrada ainda.</p>';
  desenharHistEvol(evol);
}
function desenharHistEvol(evol){
  const cv=document.getElementById("chartHistEvol"), box=document.getElementById("hist-evol");
  if(!cv||typeof Chart==="undefined") return;
  const pts=((evol&&evol.snapshots)||[]).slice(-60);
  if(chartInstances.histEvol){ chartInstances.histEvol.destroy(); chartInstances.histEvol=null; }
  if(pts.length<2){ if(box) box.innerHTML='<p class="muted" style="font-size:12px">A curva de ICE deste equipamento aparece a partir da segunda foto diária.</p>'; return; }
  chartInstances.histEvol=new Chart(cv.getContext("2d"),{type:"line",
    data:{labels:pts.map(p=>p.data.slice(5)),datasets:[
      {label:"ICE",data:pts.map(p=>p.ice),borderColor:"#22d3ee",fill:false,tension:.35,pointRadius:0,borderWidth:2,dotColors:pts.map(()=>"#22d3ee")},
      {label:"IDP",data:pts.map(p=>p.idp),borderColor:"#a78bfa",fill:false,tension:.35,pointRadius:0,borderWidth:2,borderDash:[4,4],dotColors:pts.map(()=>"#a78bfa")}]},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},
      plugins:{legend:{position:"bottom",labels:{color:_chTxt(),font:_chFont,boxWidth:10}},
        tooltip:{enabled:false,external:donutTooltipExternal,callbacks:{label:ctx=>` ${ctx.dataset.label}: ${ctx.parsed.y==null?"—":ctx.parsed.y+"%"}`}}},
      scales:{x:{ticks:{color:_chTxt(),font:_chFont,maxTicksLimit:6},grid:{display:false},border:{display:false}},
              y:_eixoY({precision:0,callback:v=>v+"%"})}}});
}
// ── itens (consumíveis / acessórios) na ficha ────────────────────────────────
function painelItens(tipo,e){
  const label=tipo==="consumivel"?"consumível":"acessório";
  if(!e.id) return `<p class="muted">Salve o equipamento primeiro para cadastrar ${label}s.</p>`;
  return `<div class="eq-itens">
    <div class="eq-item-row eq-item-head"><span>Item</span><span>SKU de Venda</span><span>SKU de Importação</span><span></span></div>
    <div id="itens-body-${tipo}">${itensBody(tipo)}</div>
    ${podeEditar?`<div class="eq-item-row eq-item-add">
      <input class="form-input" id="ni-${tipo}-nome" placeholder="Nome do ${label}…">
      <input class="form-input" id="ni-${tipo}-sku" placeholder="SKU venda">
      <input class="form-input" id="ni-${tipo}-imp" placeholder="SKU import.">
      <button class="btn btn-primary btn-sm" onclick="addItem('${tipo}')">+</button>
    </div>`:""}
  </div>`;
}
function itensBody(tipo){
  const list=FICHA_ITENS[tipo]||[], label=tipo==="consumivel"?"consumível":"acessório";
  return list.map(it=>itemRow(tipo,it)).join("")||`<p class="muted" style="font-size:12px;padding:8px 2px">Nenhum ${label} cadastrado.</p>`;
}
function itemRow(tipo,it){
  const ro=podeEditar?"":"disabled";
  return `<div class="eq-item-row" data-id="${it.id}">
    <input class="form-input" value="${esc(it.nome)}" ${ro} onchange="patchItem(${it.id},'nome',this.value)">
    <input class="form-input" value="${esc(it.sku)}" ${ro} onchange="patchItem(${it.id},'sku',this.value)">
    <input class="form-input" value="${esc(it.sku_importacao)}" ${ro} onchange="patchItem(${it.id},'sku_importacao',this.value)">
    ${podeEditar?`<button class="eq-tdel" title="Excluir" onclick="delItem('${tipo}',${it.id})">🗑</button>`:"<span></span>"}
  </div>`;
}
function refreshItens(tipo){
  const body=document.getElementById("itens-body-"+tipo); if(body) body.innerHTML=itensBody(tipo);
  ["nome","sku","imp"].forEach(s=>{ const el=document.getElementById("ni-"+tipo+"-"+s); if(el) el.value=""; });
}
async function addItem(tipo){
  const nome=val("ni-"+tipo+"-nome").trim();
  if(!nome){ toast("Informe o nome do item",true); return; }
  try{ const it=await api("/api/equipamentos/"+fichaId+"/itens",{method:"POST",
        body:JSON.stringify({tipo,nome,sku:val("ni-"+tipo+"-sku"),sku_importacao:val("ni-"+tipo+"-imp")})});
    (FICHA_ITENS[tipo]||=[]).push(it); refreshItens(tipo); toast("Item adicionado"); }
  catch(e){ toast(e.message,true); }
}
async function patchItem(id,campo,valor){
  try{ await api("/api/equip-itens/"+id,{method:"PATCH",body:JSON.stringify({[campo]:valor})});
    for(const t of ["consumivel","acessorio"]){ const it=(FICHA_ITENS[t]||[]).find(x=>x.id===id); if(it) it[campo]=(valor||"").trim(); }
  }catch(e){ toast(e.message,true); }
}
async function delItem(tipo,id){
  if(!confirm("Excluir este item?")) return;
  try{ await api("/api/equip-itens/"+id,{method:"DELETE"});
    FICHA_ITENS[tipo]=(FICHA_ITENS[tipo]||[]).filter(x=>x.id!==id); refreshItens(tipo); toast("Item excluído"); }
  catch(e){ toast(e.message,true); }
}
// ── consumíveis do catálogo vinculados a este equipamento (N:N) ───────────────
// Espelha a aba "Compatibilidade" do consumível: aqui vinculamos consumíveis já
// cadastrados (não cria catálogo). Reusa CONS/FORN_LABEL/fbadge de consumiveis.js.
function _fornLabels(){ return (typeof FORN_LABEL!=='undefined')?FORN_LABEL:{nao_informado:"não informado"}; }
function painelConsVinc(e){
  if(!e||!e.id) return `<p class="muted">Salve o equipamento primeiro para vincular consumíveis.</p>`;
  const FL=_fornLabels();
  const links=(FICHA_CONS||[]).slice().sort((a,b)=>(a.nome||"").localeCompare(b.nome||""));
  const jaTem=new Set(links.map(v=>v.consumivel_id));
  const cat=(typeof CONS!=='undefined'?CONS:[]);
  const disp=cat.filter(c=>!jaTem.has(c.id)).sort((a,b)=>(a.nome||"").localeCompare(b.nome||""));
  const rows=links.map(v=>`<tr>
      <td>${esc(v.nome)}<div class="cons-card-sku">${esc(v.tipo||"—")}${v.sku?' · '+esc(v.sku):' · sem SKU'}</div></td>
      <td>${podeEditar?`<select class="filter-sel" style="padding:5px 8px;font-size:12px" onchange="mudarFornEquipCons(${v.vinculo_id},this.value)">${
          Object.keys(FL).map(f=>`<option value="${f}" ${v.fornecimento===f?'selected':''}>${FL[f]}</option>`).join("")}</select>`
        :(typeof fbadge==='function'?fbadge(v.fornecimento):esc(FL[v.fornecimento]||v.fornecimento||"—"))}</td>
      ${podeEditar?`<td style="width:34px"><button class="eq-tdel" title="Remover" onclick="removerConsDoEquip(${v.vinculo_id})">🗑</button></td>`:""}
    </tr>`).join("");
  const add=podeEditar?`<div class="cons-linkadd" style="margin-top:10px">
      <select class="filter-sel" id="eqc-add-cons" style="flex:1;min-width:200px">${
        disp.map(c=>`<option value="${c.id}">${esc(c.nome)}${c.sku?' — '+esc(c.sku):''}</option>`).join("")||'<option value="">— todos já vinculados —</option>'}</select>
      <select class="filter-sel" id="eqc-add-forn">${Object.keys(FL).map(f=>`<option value="${f}" ${f==='pode_fornecer'?'selected':''}>${FL[f]}</option>`).join("")}</select>
      <button class="btn btn-primary btn-sm" onclick="vincularConsAoEquip()">+ vincular</button></div>
      <p class="muted" style="font-size:11px;margin-top:8px">Só lista consumíveis já cadastrados na aba Consumíveis. O vínculo é o mesmo dos dois lados.</p>`:"";
  return `<div class="eq-itens">
    <table class="vw-itbl"><thead><tr><th>Consumível</th><th style="width:180px">Fornecimento</th>${podeEditar?"<th></th>":""}</tr></thead>
    <tbody>${rows||`<tr><td colspan="3" class="vw-empty">Nenhum consumível vinculado.</td></tr>`}</tbody></table>
    ${add}</div>`;
}
async function refreshFichaCons(){
  try{ FICHA_CONS=await api("/api/equipamentos/"+fichaId+"/consumiveis"); }catch(_){ FICHA_CONS=[]; }
  const panel=document.querySelector('#eq-ficha-panels .equip-tab-panel[data-panel="consumivel"]');
  if(panel) panel.innerHTML=painelConsVinc({id:fichaId});
}
async function vincularConsAoEquip(){
  const cid=val("eqc-add-cons"); if(!cid){ toast("Nenhum consumível disponível para vincular",true); return; }
  const forn=val("eqc-add-forn");
  try{ await api("/api/consumiveis/"+cid+"/equipamentos",{method:"POST",body:JSON.stringify({equipamento_id:fichaId,fornecimento:forn})});
    toast("Consumível vinculado"); await refreshFichaCons(); }
  catch(e){ toast(e.message,true); }
}
async function mudarFornEquipCons(vid,forn){
  try{ await api("/api/consumivel-equipamento/"+vid,{method:"PATCH",body:JSON.stringify({fornecimento:forn})}); toast("Fornecimento atualizado"); }
  catch(e){ toast(e.message,true); }
}
async function removerConsDoEquip(vid){
  if(!confirm("Remover este consumível do equipamento?")) return;
  try{ await api("/api/consumivel-equipamento/"+vid,{method:"DELETE"}); toast("Vínculo removido"); await refreshFichaCons(); }
  catch(e){ toast(e.message,true); }
}
function fichaRegToggle(){
  const ruo=val("f-classificacao_reg")==="RUO";
  ["f-anvisa","f-anvisa_registro","f-anvisa_validade"].forEach(id=>{ const el=document.getElementById(id);
    if(el){ el.disabled=ruo; el.style.opacity=ruo?.5:1; } });
  const hint=document.getElementById("reg-hint");
  if(hint) hint.textContent=ruo
    ? "RUO (uso em pesquisa): sem registro ANVISA — campos de ANVISA desabilitados."
    : "IVD/registrado: preencha o registro ANVISA. Classe de risco e alertas de vencimento entram na Fase 3.";
}

function onCatChange(keepFam){
  const sel=document.getElementById("f-categoria_id"); if(!sel) return;
  const fams=famsDe(sel.value);
  const e = fichaId?_eqById(fichaId):null;
  const cur = keepFam && e ? e.familia_id : null;
  document.getElementById("f-familia_id").innerHTML='<option value="">—</option>'+fams.map(f=>`<option value="${f.id}" ${String(cur)===String(f.id)?'selected':''}>${esc(f.nome)}</option>`).join("");
}
async function salvarFicha(forcarSku){
  const nome=val("f-nome").trim();
  if(!nome){ toast("Informe o nome comercial", true); return; }
  const payload={ nome,
    sku:val("f-sku"), sku_importacao:val("f-sku_importacao"),
    nome_tecnico:val("f-nome_tecnico"), nome_original:val("f-nome_original"),
    responsavel:val("f-responsavel"),
    classe_risco:val("f-classe_risco"), situacao_regulatoria:val("f-situacao_regulatoria"),
    descricao:val("f-descricao"), observacoes:val("f-observacoes"),
    status:val("f-status"), bloqueado:document.getElementById("f-bloqueado").checked,
    fabricante:val("f-fabricante"), codigo_fabricante:val("f-codigo_fabricante"),
    armazenamento_base:val("f-armazenamento_base"), classificacao_reg:val("f-classificacao_reg"),
    anvisa:val("f-anvisa"), anvisa_registro:val("f-anvisa_registro"), anvisa_validade:val("f-anvisa_validade"),
    rev_cadastro:val("f-rev_cadastro"), rev_estrutura:val("f-rev_estrutura"), rev_descritivo:val("f-rev_descritivo"),
    categoria_id:val("f-categoria_id")||null, familia_id:val("f-familia_id")||null };
  if(forcarSku) payload.ignorar_sku_duplicado=true;
  try{
    if(fichaId) await api("/api/equipamentos/"+fichaId,{method:"PATCH",body:JSON.stringify(payload)});
    else await api("/api/equipamentos",{method:"POST",body:JSON.stringify(payload)});
    toast("Equipamento salvo"); closeModal("eq");
    const volta=fichaFromView&&fichaId; fichaFromView=false;
    await loadAll();
    if(volta) openView(fichaId);
  }catch(e){
    // O servidor recusa SKU repetido (409) porque o SKU é a chave de junção do
    // importador mestre e do Pareto. Duplicar é possível, mas só de propósito.
    if(!forcarSku && /já está em/i.test(e.message||"")
       && confirm(e.message+"\n\nSalvar mesmo assim?")) return salvarFicha(true);
    toast(e.message,true);
  }
}
async function excluirEquip(){
  if(!fichaId) return;
  if(!confirm("Excluir este equipamento? (pode ser revertido no banco)")) return;
  try{ await api("/api/equipamentos/"+fichaId,{method:"DELETE"}); toast("Equipamento excluído");
    fichaFromView=false; closeModal("eq"); await loadAll(); }
  catch(e){ toast(e.message,true); }
}

// ══ FICHA (somente leitura, fácil de ler/copiar) ════════════════════════════
let viewEq=null;
async function openView(id){
  let e=_eqById(id);
  try{ e=await api("/api/equipamentos/"+id); }catch(_){ if(!e){ toast("Erro ao abrir a ficha",true); return; } }
  viewEq=e;
  // O GET individual já traz a completude recalculada; mantém o cache alinhado
  // para a lista e o dashboard não mostrarem um ICE diferente do da ficha.
  if(e.completude) COMPL[id]=e.completude;
  const s=scores(e), f=faixa(s.ice);
  document.getElementById("eqview-body").innerHTML=renderView(e,s,f);
  document.getElementById("eqview-edit").style.display=podeEditar?"inline-flex":"none";
  openBaseModal("eqview");
}
function viewEdit(){ const id=viewEq&&viewEq.id; closeModal("eqview"); if(id) abrirFicha(id,true); }
function fecharFicha(){
  const volta=fichaFromView&&fichaId; fichaFromView=false;
  closeModal("eq");
  if(volta) openView(fichaId);
}
function vfield(label,v,wide){
  const has=v&&String(v).trim();
  return `<div class="vw-field${wide?' wide':''}"><span class="vw-flabel">${label}</span><span class="vw-fval${has?'':' empty'}">${has?esc(v):"—"}</span></div>`;
}
function vsection(title,inner,count){
  return `<div class="vw-sec"><div class="vw-sec-title">${title}${count!=null?`<span class="vw-sec-count">${count}</span>`:""}</div>${inner}</div>`;
}
function vfields(items){ return `<div class="vw-fields">${items.join("")}</div>`; }
function vitens(list,label){
  if(!list||!list.length) return `<div class="vw-empty">Nenhum ${label} cadastrado.</div>`;
  return `<table class="vw-itbl"><thead><tr><th>Item</th><th>SKU de Venda</th><th>SKU de Importação</th></tr></thead><tbody>${list.map(it=>`<tr><td>${esc(it.nome)}</td><td class="mono">${it.sku?esc(it.sku):'—'}</td><td class="mono">${it.sku_importacao?esc(it.sku_importacao):'—'}</td></tr>`).join("")}</tbody></table>`;
}
function vitensCons(list){
  if(!list||!list.length) return `<div class="vw-empty">Nenhum consumível vinculado.</div>`;
  const FL=_fornLabels();
  return `<table class="vw-itbl"><thead><tr><th>Consumível</th><th>SKU</th><th>Fornecimento</th></tr></thead><tbody>${
    list.map(v=>`<tr><td>${esc(v.nome)}</td><td class="mono">${v.sku?esc(v.sku):'—'}</td><td>${esc(FL[v.fornecimento]||v.fornecimento||'—')}</td></tr>`).join("")}</tbody></table>`;
}
function vchip(txt,cls){ return `<span class="vw-chip${cls?" "+cls:""}">${esc(txt)}</span>`; }
function renderView(e,s,f){
  const chips=[];
  if(e.sku) chips.push(vchip("SKU "+e.sku,"mono"));
  if(e.categoria) chips.push(vchip(e.categoria,"cat"));
  if(e.familia) chips.push(vchip(e.familia,"cat"));
  if(e.classificacao_reg) chips.push(vchip(e.classificacao_reg,"cls"));
  const stCls=e.status==="Ativo"?"ok":"warn";
  chips.push(vchip(e.status||"Ativo",stCls));
  if(ehBloqueado(e)) chips.push(vchip("Bloqueado","bloq"));
  // Risco que já vinha no payload dos documentos e nunca aparecia na ficha.
  if(s.docs_atrasados) chips.push(vchip(`${s.docs_atrasados} documento(s) atrasado(s)`,"bloq"));
  if(s.reg_estado==="vencido") chips.push(vchip("Registro ANVISA vencido","bloq"));
  else if(s.reg_estado==="vencendo") chips.push(vchip(`Registro vence em ${s.reg_dias} dia(s)`,"warn"));
  return `
  <div class="vw-hero">
    <div class="eq-ring vw-ring" style="background:conic-gradient(${FCOLOR[f]} ${s.ice*3.6}deg, var(--bg-elevated) 0)"><span>${s.ice}%</span></div>
    <div class="vw-hero-main">
      <div class="vw-name">${esc(e.nome||"—")}</div>
      <div class="vw-chips">${chips.join("")}</div>
    </div>
  </div>
  <div class="vw-body">
    ${vsection("Identificação", vfields([
        vfield("Nome comercial",e.nome),
        vfield("SKU de Venda",e.sku),
        vfield("SKU de Importação",e.sku_importacao),
        vfield("Nome técnico",e.nome_tecnico,true),
        vfield("Nome original",e.nome_original,true),
        vfield("Categoria",e.categoria),
        vfield("Família",e.familia),
        vfield("Responsável",e.responsavel),
        vfield("Descrição",e.descricao,true),
      ]))}
    ${vsection("Técnico", vfields([
        vfield("Fabricante",e.fabricante),
        vfield("Código do fabricante",e.codigo_fabricante),
        vfield("Armazenamento base",e.armazenamento_base,true),
      ]))}
    ${vsection("Regulatório", vfields([
        vfield("Classificação",e.classificacao_reg),
        vfield("Classe de risco",e.classe_risco),
        vfield("Situação do registro",e.situacao_regulatoria),
        vfield("Registro ANVISA",e.anvisa),
        vfield("Data de registro",e.anvisa_registro),
        vfield("Validade",e.anvisa_validade + (s.reg_estado==="vencido"?" (vencida)":s.reg_estado==="vencendo"?` (vence em ${s.reg_dias}d)`:"")),
      ]))}
    ${vsection("Situação", vfields([
        vfield("ICE",`${s.ice}% (cadastro ${s.cad}% · regulatório ${s.reg}% · documental ${s.doc}%)`,true),
        vfield("IDP",s.idp==null?"—":s.idp+"%"),
        vfield("Documentos finalizados",`${s.docs_finais} de ${s.docs_alvo}`),
        vfield("Documentos atrasados",s.docs_atrasados?`${s.docs_atrasados} (pior atraso: ${s.atraso_max} dia(s))`:"nenhum"),
        vfield("Responsáveis nos documentos",(s.responsaveis||[]).join(", ")),
        vfield("Última atualização",e.updated_em),
      ]))}
    <div class="vw-two">
      ${vsection("Consumíveis", vitensCons(e.consumiveis_vinc), (e.consumiveis_vinc||[]).length)}
      ${vsection("Acessórios", vitens(e.acessorios,"acessório"), (e.acessorios||[]).length)}
    </div>
    ${e.observacoes&&e.observacoes.trim()?vsection("Observações internas", `<div class="vw-obs">${esc(e.observacoes)}</div>`):""}
  </div>`;
}
function copiarFicha(){
  const e=viewEq; if(!e) return;
  const L=[e.nome||""]; const add=(k,v)=>{ if(v&&String(v).trim()) L.push(k+": "+v); };
  add("Nome técnico",e.nome_tecnico); add("Nome original",e.nome_original);
  add("SKU de Venda",e.sku); add("SKU de Importação",e.sku_importacao);
  add("Categoria",e.categoria); add("Família",e.familia);
  add("Fabricante",e.fabricante); add("Código do fabricante",e.codigo_fabricante);
  add("Armazenamento base",e.armazenamento_base);
  add("Classificação",e.classificacao_reg); add("Classe de risco",e.classe_risco);
  add("Situação do registro",e.situacao_regulatoria); add("Registro ANVISA",e.anvisa);
  add("Data de registro",e.anvisa_registro); add("Validade",e.anvisa_validade);
  add("Descrição",e.descricao); add("Observações",e.observacoes);
  const bloco=(arr,t)=>{ if(arr&&arr.length){ L.push(""); L.push(t+":"); arr.forEach(it=>L.push("  - "+it.nome+(it.sku?(" | Venda: "+it.sku):"")+(it.sku_importacao?(" | Import.: "+it.sku_importacao):""))); } };
  const FL=_fornLabels();
  if(e.consumiveis_vinc&&e.consumiveis_vinc.length){ L.push(""); L.push("Consumíveis:"); e.consumiveis_vinc.forEach(v=>L.push("  - "+v.nome+(v.sku?(" | SKU: "+v.sku):"")+" | "+(FL[v.fornecimento]||v.fornecimento||""))); }
  bloco(e.acessorios,"Acessórios");
  const txt=L.join("\n");
  if(navigator.clipboard&&navigator.clipboard.writeText){ navigator.clipboard.writeText(txt).then(()=>toast("Ficha copiada")).catch(()=>toast("Falha ao copiar",true)); }
  else { const ta=document.createElement("textarea"); ta.value=txt; document.body.appendChild(ta); ta.select(); try{ document.execCommand("copy"); toast("Ficha copiada"); }catch(_){ toast("Falha ao copiar",true); } document.body.removeChild(ta); }
}

// ══ CATEGORIAS ═════════════════════════════════════════════════════════════
function renderCategorias(){
  const cl=document.getElementById("cat-list");
  cl.innerHTML=TAX.categorias.map(c=>`<div class="eq-trow ${c.id===selCatId?'sel':''}" onclick="selCat(${c.id})">
    <input class="eq-tname" value="${esc(c.nome)}" onclick="event.stopPropagation()" onchange="renCategoria(${c.id},this.value)">
    <span class="eq-tct">${c.uso||0}</span>${podeEditar?`<button class="eq-tdel" onclick="event.stopPropagation();delCategoria(${c.id})">🗑</button>`:""}</div>`).join("")||'<p class="muted" style="font-size:12px">Nenhuma categoria.</p>';
  renderCatDetail();
}
function selCat(id){ selCatId=id; renderCategorias(); }
function renderCatDetail(){
  const c=TAX.categorias.find(x=>x.id===selCatId);
  const d=document.getElementById("cat-detail");
  if(!c){ d.innerHTML='<p class="muted">Selecione uma categoria para ver/editar as famílias.</p>'; return; }
  d.innerHTML=`<div class="card-title">Famílias de “${esc(c.nome)}”</div>
    <div class="eq-chips">${(c.familias||[]).map(f=>`<span class="eq-fchip">${esc(f.nome)} <span class="muted">(${f.uso||0})</span>${podeEditar?`<button onclick="delFamilia(${f.id})">×</button>`:""}</span>`).join("")||'<span class="muted" style="font-size:12px">Sem famílias.</span>'}</div>
    ${podeEditar?`<div class="eq-addline" style="max-width:300px"><input class="form-input" id="fam-new" placeholder="Nova família…"><button class="btn btn-ghost btn-sm" onclick="addFamilia(${c.id})">+ família</button></div>`:""}
    <p class="muted" style="font-size:11px;margin-top:12px">O vínculo de cada equipamento a uma categoria/família é feito na ficha (Todos os equipamentos).</p>`;
}
async function addCategoria(){ const nome=val("cat-new").trim(); if(!nome) return;
  try{ await api("/api/categorias-equipamento",{method:"POST",body:JSON.stringify({nome})}); document.getElementById("cat-new").value=""; await reloadTax(); }catch(e){ toast(e.message,true); } }
async function renCategoria(id,nome){ if(!nome.trim())return; try{ await api("/api/categorias-equipamento/"+id,{method:"PATCH",body:JSON.stringify({nome})}); await reloadTax(); }catch(e){ toast(e.message,true); } }
async function delCategoria(id){ const c=TAX.categorias.find(x=>x.id===id); if(c&&c.uso&&!confirm(`"${c.nome}" está em uso por ${c.uso} equipamento(s). Excluir e desvincular?`))return;
  try{ await api("/api/categorias-equipamento/"+id,{method:"DELETE"}); if(selCatId===id)selCatId=null; await reloadTax(); }catch(e){ toast(e.message,true); } }
async function addFamilia(cid){ const nome=val("fam-new").trim(); if(!nome) return;
  try{ await api("/api/familias-equipamento",{method:"POST",body:JSON.stringify({nome,categoria_id:cid})}); await reloadTax(); }catch(e){ toast(e.message,true); } }
async function delFamilia(id){ try{ await api("/api/familias-equipamento/"+id,{method:"DELETE"}); await reloadTax(); }catch(e){ toast(e.message,true); } }
async function reloadTax(){ try{ TAX=await api("/api/equip-taxonomia"); preencherSelects(); renderCategorias(); renderLista(); renderDashboard(); }catch(e){} }

// ══ SAÚDE DO CADASTRO ══════════════════════════════════════════════════════
// Duplicidade de SKU, texto corrompido e órfãos só apareciam rodando script
// (scripts/dedup_equipamentos.py, reconciliar_orfaos.py) — nada na aplicação.
const SAUDE_BLOCOS=[
  ["sku_duplicado","SKU de Venda duplicado","Quebra o casamento por SKU do importador mestre e do Pareto: a planilha atualiza um só dos dois.","grupo"],
  ["nome_duplicado","Nome duplicado","Provável cadastro repetido — confira antes de excluir.","grupo"],
  ["texto_corrompido","Texto corrompido (encoding)","Caracteres quebrados vindos de importações antigas; some da busca e sai errado no CSV.","lista"],
  ["registro_vencido","Registro ANVISA vencido","Não conta mais como campo preenchido no ICE regulatório.","validade"],
  ["registro_vencendo","Registro vencendo em até 90 dias","Ainda conta no ICE, mas precisa de renovação.","validade"],
  ["sem_documentos","Sem nenhum documento vinculado","A dimensão documental do ICE cai no denominador padrão de 12 tipos.","lista"],
  ["sem_sku","Sem SKU de Venda","Nenhum importador consegue alcançá-lo.","lista"],
  ["docs_orfaos","Documentos sem equipamento","Documento ativo que não entra na completude de ninguém.","docs"],
];
async function renderSaude(forcar){
  const badge=document.getElementById("saude-badge");
  if(!SAUDE||forcar){
    if(badge) badge.textContent="analisando…";
    try{ SAUDE=await api("/api/equipamentos/saude"); }
    catch(e){ document.getElementById("saude-blocos").innerHTML=`<div class="card"><p class="muted">Falha ao analisar: ${esc(e.message||"erro")}</p></div>`; return; }
  }
  const conta=b=>(SAUDE[b[0]]||[]).length;
  const total=SAUDE_BLOCOS.reduce((t,b)=>t+conta(b),0);
  if(badge) badge.textContent=total?`${total} ponto(s) de atenção`:"cadastro sem apontamentos";
  const criticos=conta(SAUDE_BLOCOS[0])+conta(SAUDE_BLOCOS[3]);
  document.getElementById("saude-kpis").innerHTML=[
    ["Equipamentos ativos",SAUDE.total,"#22d3ee"],
    ["Pontos de atenção",total,total?"#f59e0b":"#10b981"],
    ["Críticos (SKU/ANVISA)",criticos,criticos?"#f43f5e":"#10b981"],
  ].map(([l,v,c])=>`<div class="kpi-ring"><div class="kpi-ring-canvas" style="width:110px;height:110px;display:flex;align-items:center;justify-content:center"><div class="kpi-ring-val" style="position:static;color:${c};font-size:34px">${v}</div></div><div class="kpi-ring-label">${l}</div></div>`).join("");

  document.getElementById("saude-blocos").innerHTML=SAUDE_BLOCOS.map(([chave,titulo,porque,tipo])=>{
    const itens=SAUDE[chave]||[];
    if(!itens.length) return "";
    let corpo="";
    if(tipo==="grupo"){
      corpo=itens.map(g=>`<div class="prog-row" style="align-items:flex-start"><span class="prog-label" style="flex:1"><span class="mono">${esc(g.chave)}</span><div style="margin-top:4px;display:flex;gap:6px;flex-wrap:wrap">${
        g.itens.map(i=>`<button class="eq-chip" style="cursor:pointer;border:0" onclick="openView(${i.id})">${esc(i.nome)}</button>`).join("")}</div></span><span class="mono" style="color:#f43f5e;font-weight:700">${g.itens.length}</span></div>`).join("");
    }else if(tipo==="validade"){
      corpo=`<div style="display:flex;gap:6px;flex-wrap:wrap">${itens.map(i=>`<button class="eq-chip" style="cursor:pointer;border:0" onclick="openView(${i.id})" title="Validade ${esc(i.validade||"—")}">${esc(i.nome)} · ${i.dias<0?`${-i.dias}d vencida`:`${i.dias}d`}</button>`).join("")}</div>`;
    }else if(tipo==="docs"){
      corpo=`<table class="vw-itbl"><thead><tr><th>Documento</th><th>Equipamento (texto)</th><th>SKU</th></tr></thead><tbody>${
        itens.map(d=>`<tr><td>${esc(d.documento||"—")}</td><td>${esc(d.equipamento||"—")}</td><td class="mono">${esc(d.sku||"—")}</td></tr>`).join("")}</tbody></table>`;
    }else{
      corpo=`<div style="display:flex;gap:6px;flex-wrap:wrap">${itens.map(i=>`<button class="eq-chip" style="cursor:pointer;border:0" onclick="openView(${i.id})">${esc(i.nome)}</button>`).join("")}</div>`;
    }
    return `<div class="card mb"><div class="card-title">${titulo} <span class="filter-count" style="margin-left:8px">${itens.length}</span></div>
      <p class="muted" style="font-size:11px;margin:-4px 0 10px">${porque}</p>${corpo}</div>`;
  }).join("")||'<div class="card"><p class="muted">Nenhum apontamento: SKUs únicos, sem texto corrompido, sem órfãos e sem registro vencido.</p></div>';
  if(podeGerir) renderImportacoes();
}

// Histórico de importações: o relatório completo de cada execução aplicada
// (antes só sobrava uma linha resumida no audit).
const ORIGEM_LABEL={mestra:"Planilha mestra",pareto:"Pareto ABC"};
async function renderImportacoes(){
  let linhas=[];
  try{ linhas=await api("/api/equipamentos/importacoes?limit=15"); }catch(_){ return; }
  const box=document.getElementById("saude-blocos"); if(!box) return;
  const corpo=linhas.length
    ? `<table class="vw-itbl"><thead><tr><th>Quando</th><th>Origem</th><th>Por</th><th class="num">Criados</th><th class="num">Atualizados</th><th class="num">Sem match</th><th class="num">Inconsistências</th></tr></thead><tbody>${
        linhas.map(l=>`<tr><td class="muted" style="font-size:11px">${esc(l.em)}</td><td>${esc(ORIGEM_LABEL[l.origem]||l.origem)}</td><td class="muted" style="font-size:11px">${esc(l.por||"—")}</td><td class="num mono">${l.criados}</td><td class="num mono">${l.atualizados}</td><td class="num mono" style="color:${l.sem_match?"#f59e0b":"inherit"}">${l.sem_match}</td><td class="num mono" style="color:${l.inconsistencias?"#f43f5e":"inherit"}">${l.inconsistencias}</td></tr>`).join("")}</tbody></table>`
    : '<p class="muted">Nenhuma importação aplicada ainda.</p>';
  box.insertAdjacentHTML("beforeend",
    `<div class="card mb"><div class="card-title">Importações aplicadas</div>
     <p class="muted" style="font-size:11px;margin:-4px 0 10px">Cada execução guarda o relatório completo — dá para rever quais SKUs não casaram depois de aplicar.</p>${corpo}</div>`);
}

// ══ IMPORTAÇÃO / EXPORT ════════════════════════════════════════════════════
function abrirImport(){ document.getElementById("import-preview").innerHTML="—";
  document.getElementById("btn-aplicar").style.display="none"; document.getElementById("import-file").value=""; openBaseModal("import"); }
async function rodarImport(dryrun){
  const f=document.getElementById("import-file").files[0];
  const fd=new FormData(); if(f) fd.append("arquivo",f);
  document.getElementById("import-preview").innerHTML="Processando…";
  try{
    const res=await fetch("/api/equipamentos/import?dryrun="+(dryrun?"1":"0"),{method:"POST",headers:{"Authorization":"Bearer "+token()},body:fd});
    const rel=await res.json();
    if(!res.ok){ document.getElementById("import-preview").innerHTML=`<span style="color:#f43f5e">${esc(rel.erro||"Falha")}</span>`; return; }
    const inc=(rel.inconsistencias||[]).slice(0,8).map(x=>`linha ${x.linha}: ${esc(x.motivo)}${x.equipamento?(" — "+esc(x.equipamento)):""}`).join("<br>");
    document.getElementById("import-preview").innerHTML=`<b>${rel.aplicado?"Importação aplicada":"Prévia"}</b> — ${rel.total_linhas} linhas<br>A criar: <b>${rel.a_criar}</b> · A atualizar: <b>${rel.a_atualizar}</b> · Inconsistências: <b>${rel.inconsistencias_n}</b>${inc?`<div class="muted" style="font-size:11px;margin-top:8px">${inc}</div>`:""}`;
    document.getElementById("btn-aplicar").style.display=(dryrun)?"inline-flex":"none";
    if(!dryrun){ toast(`Importado: ${rel.a_criar} criados, ${rel.a_atualizar} atualizados`); await loadAll(); setTimeout(()=>closeModal("import"),1200); }
  }catch(e){ document.getElementById("import-preview").innerHTML=`<span style="color:#f43f5e">${esc(e.message)}</span>`; }
}
// Export segue os filtros da tela (o CSV ignorava tudo e devolvia 12 colunas
// fixas, sem ICE/IDP, classe ABC, saídas, descrição nem observações).
async function exportarCSV(){
  const p=new URLSearchParams();
  const q=val("eq-busca").trim(); if(q) p.set("q",q);
  const cat=val("eq-f-cat"); if(cat) p.set("categoria_id",cat);
  const st=val("eq-f-status"); if(st) p.set("status",st);
  if(!(document.getElementById("eq-f-bloq")||{}).checked) p.set("incluir_bloqueados","0");
  const ordem=val("eq-ordem"); if(ordem) p.set("ordem",ordem);
  try{ const res=await fetch("/api/equipamentos/export?"+p.toString(),{headers:{"Authorization":"Bearer "+token()}});
    if(!res.ok) throw new Error("HTTP "+res.status);
    const blob=await res.blob(); const a=document.createElement("a"); a.href=URL.createObjectURL(blob); a.download="equipamentos.csv"; a.click();
    toast("CSV exportado com os filtros da tela"); }
  catch(e){ toast("Erro ao exportar",true); }
}

// ── modais + nav wiring ──────────────────────────────────────────────────────
function openBaseModal(id){ const m=document.getElementById("modal-"+id); if(m){ m.classList.add("open"); m.setAttribute("aria-hidden","false"); } }
function closeModal(id){ const m=document.getElementById("modal-"+id); if(m){ m.classList.remove("open"); m.setAttribute("aria-hidden","true"); } }
// modais que NÃO fecham ao clicar fora (evita perder edições sem querer)
const MODAIS_SEM_FECHAR_FORA=new Set(["modal-eq","modal-consview","modal-consedit","modal-consimport"]);
document.querySelectorAll(".modal-overlay").forEach(m=>m.addEventListener("click",e=>{ if(e.target!==m) return; if(MODAIS_SEM_FECHAR_FORA.has(m.id)) return; closeModal(m.id.replace("modal-","")); }));
document.addEventListener("keydown",e=>{ if(e.key==="Escape") document.querySelectorAll(".modal-overlay.open").forEach(m=>{ if(m.id==="modal-eq") fecharFicha(); else closeModal(m.id.replace("modal-","")); }); });
document.querySelectorAll(".nav-item[data-page]").forEach(el=>el.addEventListener("click",()=>navigate(el.dataset.page)));
const _st=document.getElementById("sidebar-toggle"), _sb=document.getElementById("sidebar-backdrop"), _sn=document.getElementById("sidebar-nav");
function toggleSidebar(f){ const open=f!==undefined?f:!_sn.classList.contains("open"); _sn.classList.toggle("open",open); _sb.classList.toggle("open",open); }
_st&&_st.addEventListener("click",()=>toggleSidebar()); _sb&&_sb.addEventListener("click",()=>toggleSidebar(false));

// ── tempo real ──────────────────────────────────────────────────────────────
// A dimensão documental é 1/3 do ICE: homologar um documento no módulo
// Documentos deixava o índice daqui velho até alguém dar F5. app-realtime.js
// não serve (é acoplado à tabela de documentos e ao token 'jwt'), então
// assinamos os eventos direto e só recarregamos a completude.
let _dtSock=null, _refreshTimer=null;
const EVENTOS_QUE_MEXEM_NO_ICE=["DOCUMENT_CREATED","DOCUMENT_UPDATED","DOCUMENT_DELETED",
  "DOCUMENT_STATUS_UPDATED","ETAPA_COMPLETED"];
function agendarRefresh(){
  clearTimeout(_refreshTimer);
  _refreshTimer=setTimeout(async()=>{
    try{
      const c=await api("/api/equipamentos/completude");
      COMPL={}; ((c&&c.itens)||[]).forEach(x=>{ COMPL[x.id]=x; });
      const ativa=document.querySelector(".page.active");
      if(ativa) renderPagina((ativa.id||"").replace("page-",""));
    }catch(_){}
  },1200);   // agrupa rajadas (mudar 12 documentos dispara 12 eventos)
}
function iniciarRealtime(){
  if(typeof DocTrackSocket==="undefined"||!token()) return;
  try{
    _dtSock=new DocTrackSocket({token:token()});
    EVENTOS_QUE_MEXEM_NO_ICE.forEach(ev=>_dtSock.on(ev,agendarRefresh));
    _dtSock.on("__connect__",()=>{ const l=document.getElementById("sync-label"); if(l) l.textContent="Conectado"; });
    _dtSock.on("__disconnect__",()=>{ const l=document.getElementById("sync-label"); if(l) l.textContent="Offline"; });
    _dtSock.connect();
  }catch(_){}
}

if(!token()){ window.location.href="/"; }
else { document.getElementById("app").style.display="block";
  Promise.resolve(loadAll()).then(()=>{   // deep-link: /equipamentos?ficha=<id> abre a ficha (ex.: chip do Missões)
    const f=parseInt(new URLSearchParams(location.search).get("ficha")||"");
    if(f && _eqById(f)){ navigate("lista"); abrirFicha(f); }
    iniciarRealtime();
  });
}
