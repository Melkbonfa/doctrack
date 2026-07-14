/* Módulo Equipamentos — shell + gráficos no mesmo padrão do módulo de Documentos */
const TOKEN_KEY = "doctrack_token";
function token(){ return localStorage.getItem(TOKEN_KEY) || ""; }
function userObj(){ try{ return JSON.parse(localStorage.getItem("doctrack_user")||"{}")||{}; }catch(e){ return {}; } }
const ROLE = (userObj().role)||"";
const podeEditar = ["admin","gestor","tecnico"].includes(ROLE);
const podeGerir  = ["admin","gestor"].includes(ROLE);
sessionStorage.setItem("dt_module", "equip");

function applyTheme(t){ const l=t==="light"; document.body.classList.toggle("theme-light",l);
  const b=document.getElementById("theme-toggle"); if(b) b.textContent=l?"☀️":"🌙"; }
function toggleTheme(){ const n=document.body.classList.contains("theme-light")?"dark":"light";
  localStorage.setItem("doctrack_theme",n); applyTheme(n);
  if(document.getElementById("page-dashboard").classList.contains("active")) renderDashboard(); }
applyTheme(localStorage.getItem("doctrack_theme")||"dark");
function doLogout(){ localStorage.removeItem("doctrack_token"); localStorage.removeItem("doctrack_refresh"); localStorage.removeItem("doctrack_user"); window.location.href="/"; }

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
function esc(s){ const d=document.createElement("div"); d.textContent=s??""; return d.innerHTML; }
function val(id){ const e=document.getElementById(id); return e?e.value:""; }

// gráficos (mesmo visual do Documentos)
let chartInstances = {};
function _darken(hex,f){ const n=parseInt(hex.slice(1),16); let r=(n>>16)&255,g=(n>>8)&255,b=n&255;
  r=Math.round(r*(1-f)); g=Math.round(g*(1-f)); b=Math.round(b*(1-f)); return `rgb(${r},${g},${b})`; }
function donutGrad(ctx,hex){ const g=ctx.createLinearGradient(0,0,0,160); g.addColorStop(0,hex); g.addColorStop(1,_darken(hex,0.5)); return g; }

// ── estado ───────────────────────────────────────────────────────────────
let EQUIP=[], DOCS_BY_EQ={}, TAX={categorias:[],linhas:[]}, selCatId=null;

// ── completude (ICE) ───────────────────────────────────────────────────────
const CAD = ["sku","sku_importacao","nome_tecnico","fabricante","categoria_id","familia_id"];
const REG = ["anvisa","anvisa_registro","anvisa_validade"];
const NDOC = 9;
const CAD_LABEL = {sku:"SKU de Venda",sku_importacao:"SKU de Importação",nome_tecnico:"Nome técnico",
  fabricante:"Fabricante",categoria_id:"Categoria",familia_id:"Família"};
const REG_LABEL = {classificacao_reg:"Classificação (RUO/IVD)",anvisa:"Registro ANVISA",anvisa_registro:"Data de registro",anvisa_validade:"Validade ANVISA"};
function preenchido(e,f){ const v=e[f]; return f.endsWith("_id") ? !!v : !!(v&&String(v).trim()); }
function docFinal(d){ return (d.setor==="PRE"&&d.status==="Homologado")||(d.setor==="Manuais"&&d.status==="Concluído"); }
function docsFinais(eqId){ return (DOCS_BY_EQ[eqId]||[]).filter(docFinal).length; }
// Campos regulatórios exigidos dependem da classificação: RUO (uso em pesquisa)
// não tem registro ANVISA → basta a classificação; IVD/sem classe exige ANVISA.
function regFields(e){
  return e.classificacao_reg==="RUO" ? ["classificacao_reg"]
                                     : ["classificacao_reg","anvisa","anvisa_registro","anvisa_validade"];
}
function scores(e){
  const cad = Math.round(CAD.filter(f=>preenchido(e,f)).length/CAD.length*100);
  const rf  = regFields(e);
  const reg = Math.round(rf.filter(f=>preenchido(e,f)).length/rf.length*100);
  const doc = Math.round(Math.min(NDOC, docsFinais(e.id))/NDOC*100);
  return {cad,reg,doc,ice:Math.round((cad+reg+doc)/3)};
}
const faixa = i=> i>=85?"completo":i>=50?"parcial":"inicial";
const FCOLOR = {completo:"#10b981",parcial:"#f59e0b",inicial:"#f43f5e"};
const FBG = {completo:"rgba(16,185,129,.15)",parcial:"rgba(245,158,11,.15)",inicial:"rgba(244,63,94,.15)"};
const cor = v=> v>=85?"#10b981":v>=50?"#f59e0b":"#f43f5e";
const ehBloqueado = e=> e.bloqueado || e.status==="Obsoleto" || e.status==="Descontinuado";

// ── navegação (sidebar) ─────────────────────────────────────────────────────
function navigate(page){
  document.querySelectorAll(".nav-item").forEach(el=>el.classList.toggle("active", el.dataset.page===page));
  document.querySelectorAll(".page").forEach(p=>p.classList.remove("active"));
  const el=document.getElementById("page-"+page); if(el) el.classList.add("active");
  document.getElementById("breadcrumb-current").textContent={dashboard:"Dashboard",dev:"Desenvolvimento",lista:"Equipamentos",cat:"Categorias",consumiveis:"Consumíveis","tipos-cons":"Tipos de consumível"}[page]||"";
  if(page==="dashboard") renderDashboard();
  if(page==="dev") renderDev();
  if(page==="lista") renderLista();
  if(page==="cat") renderCategorias();
  if(page==="consumiveis" && typeof renderConsumiveis==="function") renderConsumiveis();
  if(page==="tipos-cons" && typeof renderTiposCons==="function") renderTiposCons();
}

// ── carga ──────────────────────────────────────────────────────────────────
async function loadAll(){
  try{
    const [eqs, docs, tax] = await Promise.all([
      api("/api/equipamentos"), api("/api/documentos"), api("/api/equip-taxonomia"),
    ]);
    EQUIP = eqs;
    DOCS_BY_EQ = {};
    (docs||[]).forEach(d=>{ if(d.equipamento_id){ (DOCS_BY_EQ[d.equipamento_id] ||= []).push(d); } });
    TAX = tax || {categorias:[],linhas:[]};
  }catch(e){ toast(e.message||"Erro ao carregar", true); }
  const u=userObj(); const ini=(u.nome||"A").trim()[0]||"A";
  document.getElementById("nav-name").textContent=u.nome||"Usuário";
  document.getElementById("nav-role").textContent=(u.role||"").toUpperCase();
  document.getElementById("nav-avatar").textContent=ini; document.getElementById("top-avatar").textContent=ini;
  if(podeEditar) document.getElementById("btn-novo-eq").style.display="";
  if(podeGerir){ document.getElementById("btn-import").style.display=""; const bp=document.getElementById("btn-import-pareto"); if(bp) bp.style.display=""; }
  preencherSelects();
  renderDashboard(); renderDev(); renderLista(); renderCategorias();
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
      data:{labels:cLabels,datasets:[{data:cVals,backgroundColor:bg,borderWidth:0,borderRadius:8,spacing:3,hoverOffset:6}]},
      options:{responsive:false,cutout:"78%",plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>` ${ctx.label}: ${ctx.parsed}`}}},animation:{animateRotate:true,duration:1000}}}); }

  // prog-list = dimensões
  const dims=[["Cadastro",cadAvg],["Regulatório",regAvg],["Documental",docAvg]];
  const dimC=["#22d3ee","#f59e0b","#10b981"];
  document.getElementById("prog-list").innerHTML=dims.map(([l,v],i)=>`<div class="prog-row"><span class="prog-label">${l}</span><div class="prog-track"><div class="prog-fill" style="width:${v}%;background:${dimC[i]}"></div></div><span class="prog-pct">${v}%</span></div>`).join("")+`<div style="margin-top:14px;padding-top:10px;border-top:1px solid var(--border-dim);display:flex;justify-content:space-between"><span style="font-size:10px;color:var(--t3)">ICE médio</span><span style="font-family:var(--font-mono);font-size:14px;font-weight:700;color:var(--cyan)">${iceAvg}%</span></div>`;

  // bar: equipamentos por categoria
  if(chartInstances.bar) chartInstances.bar.destroy();
  const cb=document.getElementById("chartBar");
  if(cb){ const ctx=cb.getContext("2d"); const grad=ctx.createLinearGradient(0,0,0,200); grad.addColorStop(0,"#22d3ee"); grad.addColorStop(1,"#3b82f6");
    chartInstances.bar=new Chart(ctx,{type:"bar",data:{labels:cLabels,datasets:[{data:cVals,backgroundColor:grad,borderRadius:8,borderWidth:0}]},
      options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
        scales:{x:{ticks:{color:"#94a3ff",font:{size:10,family:"Inter"}},grid:{display:false},border:{display:false}},
                y:{ticks:{color:"#94a3ff",font:{size:10,family:"Inter"}},grid:{color:"rgba(167,139,250,.06)"},border:{display:false}}}}}); }

  // bar horizontal: lacunas mais comuns
  const gaps={}; S.forEach(o=>{ CAD.forEach(f=>{ if(!preenchido(o.e,f)) gaps[CAD_LABEL[f]]=(gaps[CAD_LABEL[f]]||0)+1; });
    regFields(o.e).forEach(f=>{ if(!preenchido(o.e,f)) gaps[REG_LABEL[f]]=(gaps[REG_LABEL[f]]||0)+1; });
    const falt=NDOC-Math.min(NDOC,docsFinais(o.e.id)); if(falt) gaps["Docs não finalizados"]=(gaps["Docs não finalizados"]||0)+falt; });
  const top=Object.entries(gaps).sort((a,b)=>b[1]-a[1]).slice(0,6);
  if(chartInstances.gaps) chartInstances.gaps.destroy();
  const cg=document.getElementById("chartGaps");
  if(cg){ chartInstances.gaps=new Chart(cg,{type:"bar",
      data:{labels:top.map(t=>t[0]),datasets:[{data:top.map(t=>t[1]),backgroundColor:"#a78bfa",borderRadius:8,borderWidth:0}]},
      options:{indexAxis:"y",responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
        scales:{x:{ticks:{color:"#94a3ff",font:{size:10,family:"Inter"}},grid:{color:"rgba(167,139,250,.06)"},border:{display:false}},
                y:{ticks:{color:"#c7d2fe",font:{size:11,family:"Inter"}},grid:{display:false},border:{display:false}}}}}); }

  // tabela worklist
  const rank=[...S].sort((a,b)=>a.s.ice-b.s.ice).slice(0,10);
  const mini=v=>`<span class="mono" style="color:${cor(v)}">${v}%</span>`;
  document.getElementById("dash-table").innerHTML=rank.map(o=>`<tr onclick="openView(${o.e.id})" style="cursor:pointer"><td class="bold">${esc(o.e.nome)}</td><td class="mono">${esc(o.e.sku||"—")}</td><td>${mini(o.s.cad)}</td><td>${mini(o.s.reg)}</td><td>${mini(o.s.doc)}</td><td><span class="sg-badge ${o.s.ice>=85?'sg-finalizado':o.s.ice>=50?'sg-progresso':'sg-pendente'}">${o.s.ice}%</span></td></tr>`).join("")||'<tr><td colspan="6" style="text-align:center;color:var(--t4);padding:32px">Sem dados</td></tr>';
}

// ══ DESENVOLVIMENTO (IDP — 6 revisões + Pareto) ════════════════════════════
// 3 itens são marcados à mão (rev_*); 3 derivam do status dos documentos.
const DEV_ITENS = ["cadastro","estrutura","it","checklists","manual_usuario","descritivo"];
const DEV_ITEM_LABEL = {cadastro:"Cadastro",estrutura:"Estrutura",it:"IT",checklists:"Checklists",manual_usuario:"Manual usuário",descritivo:"Descritivo"};
const DEV_ITEM_CAMPO = {cadastro:"rev_cadastro",estrutura:"rev_estrutura",descritivo:"rev_descritivo"};  // só os manuais
const EST_COR = {"Revisado":"#10b981","Em revisão":"#f59e0b","Pendente":"#f43f5e","N/A":"#64748b"};
const EST_BG  = {"Revisado":"rgba(16,185,129,.15)","Em revisão":"rgba(245,158,11,.15)","Pendente":"rgba(244,63,94,.15)","N/A":"rgba(100,116,139,.15)"};
const EST_TODOS = ["Pendente","Em revisão","Revisado","N/A"];
// status do doc → estado de revisão (PRE: Elaborar→…→Homologado; Manuais: Elaborar→Em andamento→Concluído)
function _estPRE(st){ return st==="Homologado"?"Revisado":(!st||st==="Elaborar")?"Pendente":"Em revisão"; }
function _estManuais(st){ return st==="Concluído"?"Revisado":(!st||st==="Elaborar")?"Pendente":"Em revisão"; }
function _docsDoTipo(eqId,tipos){ return (DOCS_BY_EQ[eqId]||[]).filter(d=>tipos.includes(d.tipo_doc)); }
// estado de cada um dos 6 itens de revisão
function revState(e,item){
  if(item==="cadastro")   return e.rev_cadastro||"Pendente";
  if(item==="estrutura")  return e.rev_estrutura||"Pendente";
  if(item==="descritivo") return e.rev_descritivo||"Pendente";
  if(item==="it"){ const d=_docsDoTipo(e.id,["IT"])[0]; return _estPRE(d&&d.status); }
  if(item==="manual_usuario"){ const d=_docsDoTipo(e.id,["Manual_Usuario"])[0]; return _estManuais(d&&d.status); }
  if(item==="checklists"){
    const ds=_docsDoTipo(e.id,["Checklist_Conferencia","Checklist_BurnIn","Checklist_Limpeza_Embalagem","Checklist_Produto"]);
    if(!ds.length) return "Pendente";
    const est=ds.map(d=>_estPRE(d.status));
    if(est.every(x=>x==="Revisado")) return "Revisado";
    if(est.every(x=>x==="Pendente")) return "Pendente";
    return "Em revisão";
  }
  return "Pendente";
}
// IDP = Revisados / (6 − nº de N/A) × 100. null quando todos os itens são N/A.
function idp(e){ let rev=0, apl=0;
  DEV_ITENS.forEach(it=>{ const s=revState(e,it); if(s==="N/A") return; apl++; if(s==="Revisado") rev++; });
  return apl ? Math.round(rev/apl*100) : null;
}
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
  try{ await api("/api/equipamentos/"+id,{method:"PATCH",body:JSON.stringify({[campo]:valor})});
    const e=_eqById(id); if(e) e[campo]=valor; renderDev();
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
      {label:"Completo",data:porClasse.map(p=>p.completo),backgroundColor:FCOLOR.completo,borderRadius:6,stack:"s"},
      {label:"Parcial", data:porClasse.map(p=>p.parcial), backgroundColor:FCOLOR.parcial, borderRadius:6,stack:"s"},
      {label:"Inicial", data:porClasse.map(p=>p.inicial), backgroundColor:FCOLOR.inicial, borderRadius:6,stack:"s"}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:"bottom",labels:{color:"#94a3ff",font:{size:10,family:"Inter"},boxWidth:10}}},
      scales:{x:{stacked:true,ticks:{color:"#94a3ff",font:{size:11,family:"Inter"}},grid:{display:false},border:{display:false}},
              y:{stacked:true,ticks:{color:"#94a3ff",font:{size:10,family:"Inter"},precision:0},grid:{color:"rgba(167,139,250,.06)"},border:{display:false}}}}}); }

  // barra horizontal: revisões mais pendentes (por item, na frota filtrada)
  const pend=DEV_ITENS.map(it=>[DEV_ITEM_LABEL[it], S.filter(o=>{const s=revState(o.e,it); return s!=="Revisado"&&s!=="N/A";}).length]).sort((a,b)=>b[1]-a[1]);
  if(chartInstances.devItens) chartInstances.devItens.destroy();
  const ci=document.getElementById("devChartItens");
  if(ci){ chartInstances.devItens=new Chart(ci,{type:"bar",
    data:{labels:pend.map(p=>p[0]),datasets:[{data:pend.map(p=>p[1]),backgroundColor:"#a78bfa",borderRadius:8}]},
    options:{indexAxis:"y",responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
      scales:{x:{ticks:{color:"#94a3ff",font:{size:10,family:"Inter"},precision:0},grid:{color:"rgba(167,139,250,.06)"},border:{display:false}},
              y:{ticks:{color:"#c7d2fe",font:{size:11,family:"Inter"}},grid:{display:false},border:{display:false}}}}}); }

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
function renderLista(){
  const q=(val("eq-busca")||"").toLowerCase(), cat=val("eq-f-cat"), st=val("eq-f-status"), inc=(document.getElementById("eq-f-bloq")||{}).checked;
  let list=EQUIP.filter(e=>(inc||!ehBloqueado(e))
    &&(!cat||String(e.categoria_id)===String(cat))&&(!st||e.status===st)
    &&(!q||[e.nome,e.sku,e.nome_tecnico,e.fabricante,e.sku_importacao].filter(Boolean).join(" ").toLowerCase().includes(q)));
  document.getElementById("eq-badge").textContent=list.length+" equip.";
  document.getElementById("eq-grid").innerHTML=list.map(e=>{
    const s=scores(e), f=faixa(s.ice);
    return `<div class="equip-card st-${f==='completo'?'green':f==='parcial'?'amber':'red'}" onclick="openView(${e.id})">
      <div class="eq-ring" style="background:conic-gradient(${FCOLOR[f]} ${s.ice*3.6}deg, var(--bg-elevated) 0)"><span>${s.ice}%</span></div>
      <div class="equip-card-name" style="padding-right:46px">${esc(e.nome)}</div>
      <div class="equip-card-sku">${e.sku?esc(e.sku):'<span class="muted">sem SKU</span>'}</div>
      <div class="eq-card-meta">${e.categoria?`<span class="eq-chip">${esc(e.categoria)}</span>`:""}${ehBloqueado(e)?`<span class="eq-chip bloq">${esc(e.status)}</span>`:""}</div>
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
      <div class="g2">
        <div class="form-group"><label class="form-label">Status</label><select class="form-input" id="f-status">${stOpts}</select></div>
        <div class="form-group"><label class="form-label">Bloqueado</label><label class="muted" style="display:flex;align-items:center;gap:8px;padding-top:9px"><input type="checkbox" id="f-bloqueado" ${e.bloqueado?'checked':''}> equipamento bloqueado</label></div>
      </div>
      <div class="form-group"><label class="form-label">Descrição (descritivo)</label><textarea class="form-input" id="f-descricao" rows="3" placeholder="Aplicação, princípio, diferenciais…">${esc(e.descricao||"")}</textarea></div>
      <div class="form-group"><label class="form-label">Observações (internas)</label><textarea class="form-input" id="f-observacoes" rows="2">${esc(e.observacoes||"")}</textarea></div>`;
  }
  if(k==="tecnico") return `<div class="g2">${fld("Fabricante","f-fabricante",e.fabricante)}${fld("Código do fabricante","f-codigo_fabricante",e.codigo_fabricante)}</div>
      <div class="g2">${fld("Nome original","f-nome_original",e.nome_original)}${fld("Armazenamento base","f-armazenamento_base",e.armazenamento_base)}</div>
      <p class="muted" style="font-size:12px">Campos técnicos avançados (modelo, tecnologia, aplicação) crescem por fase.</p>`;
  if(k==="reg"){
    const clOpts=["","RUO","IVD"].map(v=>`<option value="${v}" ${e.classificacao_reg===v?'selected':''}>${v||"— não definido —"}</option>`).join("");
    return `<div class="g2">
        <div class="form-group"><label class="form-label">Classificação regulatória</label><select class="form-input" id="f-classificacao_reg" onchange="fichaRegToggle()">${clOpts}</select></div>
        ${fld("Registro ANVISA (nº)","f-anvisa",e.anvisa)}
      </div>
      <div class="g2"><div class="form-group"><label class="form-label">Data de registro</label><input class="form-input" type="date" id="f-anvisa_registro" value="${esc(e.anvisa_registro||"")}"></div><div class="form-group"><label class="form-label">Validade</label><input class="form-input" type="date" id="f-anvisa_validade" value="${esc(e.anvisa_validade||"")}"></div></div>
      <p class="muted" style="font-size:12px" id="reg-hint">RUO (uso em pesquisa) não exige registro ANVISA. Classe de risco e alertas de vencimento entram na Fase 3.</p>`;
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
  return '<p class="muted">Auditoria de alterações deste equipamento — integra com o log na Fase 3.</p>';
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
async function salvarFicha(){
  const nome=val("f-nome").trim();
  if(!nome){ toast("Informe o nome comercial", true); return; }
  const payload={ nome,
    sku:val("f-sku"), sku_importacao:val("f-sku_importacao"),
    nome_tecnico:val("f-nome_tecnico"), nome_original:val("f-nome_original"),
    descricao:val("f-descricao"), observacoes:val("f-observacoes"),
    status:val("f-status"), bloqueado:document.getElementById("f-bloqueado").checked,
    fabricante:val("f-fabricante"), codigo_fabricante:val("f-codigo_fabricante"),
    armazenamento_base:val("f-armazenamento_base"), classificacao_reg:val("f-classificacao_reg"),
    anvisa:val("f-anvisa"), anvisa_registro:val("f-anvisa_registro"), anvisa_validade:val("f-anvisa_validade"),
    rev_cadastro:val("f-rev_cadastro"), rev_estrutura:val("f-rev_estrutura"), rev_descritivo:val("f-rev_descritivo"),
    categoria_id:val("f-categoria_id")||null, familia_id:val("f-familia_id")||null };
  try{
    if(fichaId) await api("/api/equipamentos/"+fichaId,{method:"PATCH",body:JSON.stringify(payload)});
    else await api("/api/equipamentos",{method:"POST",body:JSON.stringify(payload)});
    toast("Equipamento salvo"); closeModal("eq");
    const volta=fichaFromView&&fichaId; fichaFromView=false;
    await loadAll();
    if(volta) openView(fichaId);
  }catch(e){ toast(e.message,true); }
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
        vfield("Descrição",e.descricao,true),
      ]))}
    ${vsection("Técnico", vfields([
        vfield("Fabricante",e.fabricante),
        vfield("Código do fabricante",e.codigo_fabricante),
        vfield("Armazenamento base",e.armazenamento_base,true),
      ]))}
    ${vsection("Regulatório", vfields([
        vfield("Classificação",e.classificacao_reg),
        vfield("Registro ANVISA",e.anvisa),
        vfield("Data de registro",e.anvisa_registro),
        vfield("Validade",e.anvisa_validade),
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
  add("Classificação",e.classificacao_reg); add("Registro ANVISA",e.anvisa);
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
async function exportarCSV(){
  try{ const res=await fetch("/api/equipamentos/export",{headers:{"Authorization":"Bearer "+token()}});
    const blob=await res.blob(); const a=document.createElement("a"); a.href=URL.createObjectURL(blob); a.download="equipamentos.csv"; a.click(); }
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

if(!token()){ window.location.href="/"; }
else { document.getElementById("app").style.display="block";
  Promise.resolve(loadAll()).then(()=>{   // deep-link: /equipamentos?ficha=<id> abre a ficha (ex.: chip do Missões)
    const f=parseInt(new URLSearchParams(location.search).get("ficha")||"");
    if(f && _eqById(f)){ navigate("lista"); abrirFicha(f); }
  });
}
