/* Módulo Equipamentos — dashboard de completude · lista+ficha · taxonomia */
const TOKEN_KEY = "doctrack_token";
function token(){ return localStorage.getItem(TOKEN_KEY) || ""; }
function userRole(){ try{ return (JSON.parse(localStorage.getItem("doctrack_user")||"{}").role)||""; }catch(e){ return ""; } }
sessionStorage.setItem("dt_module", "equip");

function applyTheme(t){ const l=t==="light"; document.body.classList.toggle("theme-light",l);
  const b=document.getElementById("theme-toggle"); if(b) b.textContent=l?"☀️":"🌙"; }
function toggleTheme(){ const n=document.body.classList.contains("theme-light")?"dark":"light";
  localStorage.setItem("doctrack_theme",n); applyTheme(n); }
applyTheme(localStorage.getItem("doctrack_theme")||"dark");

async function api(url, opts={}){
  const res = await fetch(url, {...opts, headers:{
    "Content-Type":"application/json", "Authorization":"Bearer "+token(), ...(opts.headers||{})}});
  if(res.status===401){ window.location.href="/"; throw new Error("401"); }
  if(!res.ok){ const b=await res.json().catch(()=>({})); throw new Error(b.erro||("HTTP "+res.status)); }
  return res.json();
}
function toast(msg, erro=false){ const t=document.getElementById("toast");
  t.textContent=msg; t.style.display="block"; t.style.borderColor=erro?"#ef4444":"#22d3ee";
  clearTimeout(t._h); t._h=setTimeout(()=>t.style.display="none",3000); }
function esc(s){ const d=document.createElement("div"); d.textContent=s??""; return d.innerHTML; }
function val(id){ const e=document.getElementById(id); return e?e.value:""; }

// ── estado ───────────────────────────────────────────────────────────────
let EQUIP=[], DOCS_BY_EQ={}, TAX={categorias:[],linhas:[]}, selCatId=null;
const ROLE=userRole();
const podeEditar = ["admin","gestor","tecnico"].includes(ROLE);
const podeGerir  = ["admin","gestor"].includes(ROLE);

// ── completude (ICE) ───────────────────────────────────────────────────────
const CAD = ["sku","sku_importacao","nome_tecnico","codigo_interno","fabricante","categoria_id","familia_id","linha_id"];
const REG = ["anvisa","anvisa_registro","anvisa_validade"];
const NDOC = 9;
const CAD_LABEL = {sku:"SKU de Venda",sku_importacao:"SKU de Importação",nome_tecnico:"Nome técnico",
  codigo_interno:"Código interno",fabricante:"Fabricante",categoria_id:"Categoria",familia_id:"Família",linha_id:"Linha"};
const REG_LABEL = {anvisa:"Registro ANVISA",anvisa_registro:"Data de registro",anvisa_validade:"Validade ANVISA"};

function preenchido(e,f){ const v=e[f]; return f.endsWith("_id") ? !!v : !!(v&&String(v).trim()); }
function docFinal(d){ return (d.setor==="PRE"&&d.status==="Homologado")||(d.setor==="Manuais"&&d.status==="Concluído"); }
function docsFinais(eqId){ return (DOCS_BY_EQ[eqId]||[]).filter(docFinal).length; }
function scores(e){
  const cad = Math.round(CAD.filter(f=>preenchido(e,f)).length/CAD.length*100);
  const reg = Math.round(REG.filter(f=>preenchido(e,f)).length/REG.length*100);
  const doc = Math.round(Math.min(NDOC, docsFinais(e.id))/NDOC*100);
  return {cad,reg,doc,ice:Math.round((cad+reg+doc)/3)};
}
const faixa = i=> i>=85?"completo":i>=50?"parcial":"inicial";
const COR = {completo:"var(--green)",parcial:"var(--amber)",inicial:"var(--red)"};
const cor = v=> v>=85?"var(--green)":v>=50?"var(--amber)":"var(--red)";
const ehBloqueado = e=> e.bloqueado || e.status==="Obsoleto" || e.status==="Descontinuado";

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
  if(podeEditar){ const b=document.getElementById("btn-novo-eq"); if(b) b.style.display=""; }
  if(podeGerir){ const b=document.getElementById("btn-import"); if(b) b.style.display=""; }
  preencherSelectsLista();
  renderDashboard(); renderLista(); renderCategorias();
}

function preencherSelectsLista(){
  const sc=document.getElementById("eq-f-cat");
  sc.innerHTML='<option value="">Categoria: todas</option>'+TAX.categorias.map(c=>`<option value="${c.id}">${esc(c.nome)}</option>`).join("");
  const st=[...new Set(EQUIP.map(e=>e.status).filter(Boolean))];
  document.getElementById("eq-f-status").innerHTML='<option value="">Status: todos</option>'+st.map(s=>`<option>${esc(s)}</option>`).join("");
}

// ── abas ────────────────────────────────────────────────────────────────────
function trocarAba(a){
  ["dash","lista","cat"].forEach(x=>{
    document.getElementById("aba-"+x).style.display = x===a?"":"none";
    document.getElementById("tab-btn-"+x).classList.toggle("active", x===a);
  });
}

// ══ DASHBOARD ══════════════════════════════════════════════════════════════
let dashIncBloq=false, dashCat="", dashStatus="";
function renderDashboard(){
  const fl=document.getElementById("dash-filters");
  fl.innerHTML = `
    <div class="filter-bar" style="margin:0;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <select class="filter-sel" id="dash-cat" onchange="dashCat=this.value;renderDashboard()">
        <option value="">Categoria: todas</option>
        ${TAX.categorias.map(c=>`<option value="${c.id}" ${dashCat==c.id?'selected':''}>${esc(c.nome)}</option>`).join("")}
      </select>
      <label class="muted" style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;margin-left:auto">
        <input type="checkbox" id="dash-bloq" ${dashIncBloq?'checked':''} onchange="dashIncBloq=this.checked;renderDashboard()"> incluir obsoletos/bloqueados
      </label>
    </div>`;
  let list = EQUIP.filter(e=> (dashIncBloq||!ehBloqueado(e)) && (!dashCat||String(e.categoria_id)===String(dashCat)));
  const S = list.map(e=>({e, s:scores(e)}));
  const n = S.length, avg = a=> n?Math.round(a.reduce((x,y)=>x+y,0)/n):0;
  const iceAvg=avg(S.map(o=>o.s.ice)), cadAvg=avg(S.map(o=>o.s.cad)), regAvg=avg(S.map(o=>o.s.reg)), docAvg=avg(S.map(o=>o.s.doc));
  const completos=S.filter(o=>o.s.ice>=85).length;
  const pendReg=S.filter(o=>!o.e.anvisa).length;
  const docInc=S.filter(o=>o.s.doc<100).length;

  document.getElementById("eq-kpis").innerHTML=[
    ["equipamentos no recorte", n, "", "var(--cyan,#22d3ee)"],
    ["ICE médio da frota", iceAvg+"%", n?(completos+" completos (≥85%)"):"", cor(iceAvg)],
    ["sem registro ANVISA", pendReg, "pendência regulatória", "var(--amber)"],
    ["documentação incompleta", docInc, "algum dos 9 tipos não finalizado", "var(--red)"],
  ].map(([l,v,h,c])=>`<div class="kpi-card"><div class="kpi-value" style="color:${c}">${v}</div><div class="kpi-label">${l}</div>${h?`<div class="muted" style="font-size:11px;margin-top:4px">${h}</div>`:""}</div>`).join("");

  // donut por faixa
  const cnt={completo:0,parcial:0,inicial:0}; S.forEach(o=>cnt[faixa(o.s.ice)]++);
  const tot=n||1; let acc=0; const segs=[];
  ["completo","parcial","inicial"].forEach(k=>{ const a=acc/tot*360; acc+=cnt[k]; const b=acc/tot*360; if(cnt[k]) segs.push(`${COR[k]} ${a}deg ${b}deg`); });
  document.getElementById("eq-donut").style.background = n?`conic-gradient(${segs.join(",")})`:"var(--bg-elevated,#222)";
  document.getElementById("eq-donut-avg").textContent=iceAvg+"%";
  document.getElementById("eq-donut-legend").innerHTML=[["Completo ≥85%","completo"],["Parcial 50–84%","parcial"],["Inicial <50%","inicial"]]
    .map(([l,k])=>`<div class="eq-leg-row"><span class="eq-leg-dot" style="background:${COR[k]}"></span>${l}<span class="eq-leg-n">${cnt[k]}</span></div>`).join("");

  document.getElementById("eq-dims").innerHTML=[["Cadastro",cadAvg],["Regulatório",regAvg],["Documental",docAvg]]
    .map(([l,v])=>`<div class="eq-bar"><div class="eq-bar-top"><span>${l}</span><span style="color:${cor(v)};font-weight:700">${v}%</span></div><div class="eq-track"><div class="eq-fill" style="width:${v}%;background:${cor(v)}"></div></div></div>`).join("");
  document.getElementById("eq-dims-note").textContent=`ICE = (Cadastro + Regulatório + Documental) / 3 = ${iceAvg}%`;

  // lacunas
  const gaps={};
  S.forEach(o=>{ CAD.forEach(f=>{ if(!preenchido(o.e,f)) gaps[CAD_LABEL[f]]=(gaps[CAD_LABEL[f]]||0)+1; });
    REG.forEach(f=>{ if(!preenchido(o.e,f)) gaps[REG_LABEL[f]]=(gaps[REG_LABEL[f]]||0)+1; });
    const falt=NDOC-Math.min(NDOC,docsFinais(o.e.id)); if(falt) gaps["Documentos não finalizados"]=(gaps["Documentos não finalizados"]||0)+falt; });
  const top=Object.entries(gaps).sort((a,b)=>b[1]-a[1]).slice(0,6); const mx=top.length?top[0][1]:1;
  document.getElementById("eq-gaps").innerHTML=top.map(([l,c])=>`<div class="eq-bar"><div class="eq-bar-top"><span>${l}</span><span class="muted">${c}</span></div><div class="eq-track"><div class="eq-fill" style="width:${Math.round(c/mx*100)}%;background:var(--purple,#a78bfa)"></div></div></div>`).join("")||'<p class="muted" style="font-size:12px">Sem lacunas no recorte.</p>';

  // worklist
  const rank=[...S].sort((a,b)=>a.s.ice-b.s.ice).slice(0,8);
  const mini=v=>`<div class="eq-mini"><div class="eq-track" style="height:6px"><div class="eq-fill" style="width:${v}%;background:${cor(v)}"></div></div><span>${v}%</span></div>`;
  document.getElementById("eq-worklist").innerHTML=`<table class="eq-wtable"><thead><tr><th>Equipamento</th><th>Cad</th><th>Reg</th><th>Doc</th><th>ICE</th></tr></thead><tbody>`+
    (rank.map(o=>`<tr onclick="abrirFicha(${o.e.id})" style="cursor:pointer"><td><b>${esc(o.e.nome)}</b>${ehBloqueado(o.e)?` <span class="muted" style="font-size:10px">${esc(o.e.status)}</span>`:""}<br><span class="muted" style="font-size:11px">SKU ${esc(o.e.sku||"—")}</span></td><td>${mini(o.s.cad)}</td><td>${mini(o.s.reg)}</td><td>${mini(o.s.doc)}</td><td><span class="eq-badge" style="background:${COR[faixa(o.s.ice)]}22;color:${COR[faixa(o.s.ice)]}">${o.s.ice}%</span></td></tr>`).join("")||'<tr><td colspan="5" class="muted">Sem equipamentos.</td></tr>')+
    `</tbody></table>`;
}

// ══ LISTA ══════════════════════════════════════════════════════════════════
function renderLista(){
  const q=(val("eq-busca")||"").toLowerCase(), cat=val("eq-f-cat"), st=val("eq-f-status"), inc=document.getElementById("eq-f-bloq").checked;
  let list=EQUIP.filter(e=>(inc||!ehBloqueado(e))
    &&(!cat||String(e.categoria_id)===String(cat))&&(!st||e.status===st)
    &&(!q||[e.nome,e.sku,e.nome_tecnico,e.fabricante,e.sku_importacao].filter(Boolean).join(" ").toLowerCase().includes(q)));
  document.getElementById("eq-badge").textContent=list.length+" equip.";
  document.getElementById("eq-grid").innerHTML=list.map(e=>{
    const s=scores(e), col=faixa(s.ice);
    return `<div class="equip-card st-${col==='completo'?'green':col==='parcial'?'amber':'red'}" onclick="abrirFicha(${e.id})">
      <div class="eq-ring" style="background:conic-gradient(${COR[col]} ${s.ice*3.6}deg, var(--bg-elevated,#222) 0)"><span>${s.ice}%</span></div>
      <div class="equip-card-name" style="padding-right:46px">${esc(e.nome)}</div>
      <div class="equip-card-sku">${e.sku?esc(e.sku):'<span class="muted">sem SKU</span>'}</div>
      <div class="eq-card-meta">${e.categoria?`<span class="eq-chip">${esc(e.categoria)}</span>`:""}${ehBloqueado(e)?`<span class="eq-chip bloq">${esc(e.status)}</span>`:""}</div>
    </div>`;
  }).join("")||'<div class="muted" style="grid-column:1/-1;text-align:center;padding:30px">Nenhum equipamento.</div>';
}

// ══ FICHA ══════════════════════════════════════════════════════════════════
let fichaId=null, fichaTab="geral";
function _eqById(id){ return EQUIP.find(e=>e.id===id) || null; }
function famsDe(catId){ const c=TAX.categorias.find(x=>String(x.id)===String(catId)); return c?(c.familias||[]):[]; }

function abrirFicha(id){
  fichaId=id; fichaTab="geral";
  const e = id ? _eqById(id) : {id:null,nome:"",status:"Ativo",categoria_id:null,familia_id:null,linha_id:null};
  const s = id ? scores(e) : {cad:0,reg:0,doc:0,ice:0};
  document.getElementById("eq-ficha-del").style.display = (id&&podeGerir)?"inline-flex":"none";
  document.getElementById("eq-ficha-save").style.display = podeEditar?"inline-flex":"none";
  document.getElementById("eq-ficha-head").innerHTML = `
    <div class="eq-fhead">
      <div><div class="eq-fname"><span class="eq-fdot" style="background:${COR[faixa(s.ice)]}"></span>${esc(e.nome||"Novo equipamento")}</div>
      <div class="eq-fsub">${e.sku?("SKU "+esc(e.sku)+" · "):""}ICE ${s.ice}% · ${esc(e.status||"Ativo")}</div></div>
      <button class="btn btn-ghost btn-sm" onclick="closeModal('eq')" aria-label="Fechar" style="padding:4px 10px">✕</button>
    </div>`;
  const tabs=[["geral","Geral"],["tecnico","Técnico"],["reg","Regulatório"],["docs","Documentos"],["hist","Histórico"]];
  document.getElementById("eq-ficha-tabs").innerHTML=tabs.map(([k,l])=>`<button class="equip-modal-tab ${k===fichaTab?'active':''}" onclick="fichaSwitch('${k}')">${l}</button>`).join("");
  document.getElementById("eq-ficha-panels").innerHTML=tabs.map(([k])=>`<div class="equip-tab-panel ${k===fichaTab?'active':''}" data-panel="${k}">${painelFicha(k,e)}</div>`).join("");
  // popula familia conforme categoria
  onCatChange(true);
  openBaseModal("eq");
}
function fichaSwitch(k){
  fichaTab=k;
  document.querySelectorAll("#eq-ficha-tabs .equip-modal-tab").forEach(b=>
    b.classList.toggle("active", (b.getAttribute("onclick")||"").includes("'"+k+"'")));
  document.querySelectorAll("#eq-ficha-panels .equip-tab-panel").forEach(p=>
    p.classList.toggle("active", p.dataset.panel===k));
}
function fld(label,id,v,ph){ return `<div class="form-group"><label class="form-label">${label}</label><input class="form-input" id="${id}" value="${esc(v||"")}" placeholder="${ph||""}"></div>`; }

function painelFicha(k,e){
  if(k==="geral"){
    const catOpts='<option value="">—</option>'+TAX.categorias.map(c=>`<option value="${c.id}" ${String(e.categoria_id)===String(c.id)?'selected':''}>${esc(c.nome)}</option>`).join("");
    const linOpts='<option value="">—</option>'+TAX.linhas.map(l=>`<option value="${l.id}" ${String(e.linha_id)===String(l.id)?'selected':''}>${esc(l.nome)}</option>`).join("");
    const stOpts=["Ativo","Obsoleto","Descontinuado"].map(s=>`<option ${e.status===s?'selected':''}>${s}</option>`).join("");
    return `<div class="g3">${fld("Código interno","f-codigo_interno",e.codigo_interno)}${fld("SKU de Venda","f-sku",e.sku)}${fld("SKU de Importação","f-sku_importacao",e.sku_importacao)}</div>
      <div class="g2">${fld("Nome comercial","f-nome",e.nome)}${fld("Nome técnico","f-nome_tecnico",e.nome_tecnico)}</div>
      <div class="g3">
        <div class="form-group"><label class="form-label">Categoria</label><select class="form-input" id="f-categoria_id" onchange="onCatChange()">${catOpts}</select></div>
        <div class="form-group"><label class="form-label">Família</label><select class="form-input" id="f-familia_id"></select></div>
        <div class="form-group"><label class="form-label">Linha de produto</label><select class="form-input" id="f-linha_id">${linOpts}</select></div>
      </div>
      <div class="g2">
        <div class="form-group"><label class="form-label">Status</label><select class="form-input" id="f-status">${stOpts}</select></div>
        <div class="form-group"><label class="form-label">Bloqueado</label><label class="muted" style="display:flex;align-items:center;gap:8px;padding-top:9px"><input type="checkbox" id="f-bloqueado" ${e.bloqueado?'checked':''}> equipamento bloqueado</label></div>
      </div>
      <div class="form-group"><label class="form-label">Descrição (descritivo)</label><textarea class="form-input" id="f-descricao" rows="3" placeholder="Aplicação, princípio, diferenciais…">${esc(e.descricao||"")}</textarea></div>
      <div class="form-group"><label class="form-label">Observações (internas)</label><textarea class="form-input" id="f-observacoes" rows="2">${esc(e.observacoes||"")}</textarea></div>`;
  }
  if(k==="tecnico") return `<div class="g2">${fld("Fabricante","f-fabricante",e.fabricante)}${fld("Armazenamento base","f-armazenamento_base",e.armazenamento_base)}</div><p class="muted" style="font-size:12px">Campos técnicos avançados (modelo, tecnologia, aplicação) crescem por fase.</p>`;
  if(k==="reg") return `<div class="form-group">${fld("Registro ANVISA (nº)","f-anvisa",e.anvisa)}</div><div class="g2"><div class="form-group"><label class="form-label">Data de registro</label><input class="form-input" type="date" id="f-anvisa_registro" value="${esc(e.anvisa_registro||"")}"></div><div class="form-group"><label class="form-label">Validade</label><input class="form-input" type="date" id="f-anvisa_validade" value="${esc(e.anvisa_validade||"")}"></div></div><p class="muted" style="font-size:12px">Classe de risco, situação e alertas de vencimento entram na Fase 3.</p>`;
  if(k==="docs"){
    if(!e.id) return '<p class="muted">Salve o equipamento para vincular documentos.</p>';
    const docs=DOCS_BY_EQ[e.id]||[];
    if(!docs.length) return '<p class="muted">Nenhum documento vinculado ainda. Crie-os no módulo de Documentos.</p>';
    const stc=s=>(s==="Homologado"||s==="Concluído")?"var(--green)":s==="Elaborar"?"var(--red)":"var(--amber)";
    return `<div class="eq-doclist">${docs.map(d=>`<div class="eq-docrow"><span class="eq-docdot" style="background:${stc(d.status)}"></span>${esc(d.tipo_doc_label||d.tipo_doc||d.documento)}<span class="muted" style="margin-left:auto;font-size:11px">${esc(d.status)}</span></div>`).join("")}</div><p class="muted" style="font-size:11px;margin-top:8px">${docsFinais(e.id)}/${NDOC} finalizados.</p>`;
  }
  return '<p class="muted">Auditoria de alterações deste equipamento — integra com o log na Fase 3.</p>';
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
    codigo_interno:val("f-codigo_interno"), sku:val("f-sku"), sku_importacao:val("f-sku_importacao"),
    nome_tecnico:val("f-nome_tecnico"), descricao:val("f-descricao"), observacoes:val("f-observacoes"),
    status:val("f-status"), bloqueado:document.getElementById("f-bloqueado").checked,
    fabricante:val("f-fabricante"), armazenamento_base:val("f-armazenamento_base"),
    anvisa:val("f-anvisa"), anvisa_registro:val("f-anvisa_registro"), anvisa_validade:val("f-anvisa_validade"),
    categoria_id:val("f-categoria_id")||null, familia_id:val("f-familia_id")||null, linha_id:val("f-linha_id")||null };
  try{
    if(fichaId) await api("/api/equipamentos/"+fichaId,{method:"PATCH",body:JSON.stringify(payload)});
    else await api("/api/equipamentos",{method:"POST",body:JSON.stringify(payload)});
    toast("Equipamento salvo"); closeModal("eq"); await loadAll();
  }catch(e){ toast(e.message,true); }
}
async function excluirEquip(){
  if(!fichaId) return;
  if(!confirm("Excluir este equipamento? (pode ser revertido no banco)")) return;
  try{ await api("/api/equipamentos/"+fichaId,{method:"DELETE"}); toast("Equipamento excluído");
    closeModal("eq"); await loadAll(); }
  catch(e){ toast(e.message,true); }
}

// ══ CATEGORIAS (taxonomia) ═════════════════════════════════════════════════
function renderCategorias(){
  const cl=document.getElementById("cat-list");
  cl.innerHTML=TAX.categorias.map(c=>`<div class="eq-trow ${c.id===selCatId?'sel':''}" onclick="selCat(${c.id})">
    <input class="eq-tname" value="${esc(c.nome)}" onclick="event.stopPropagation()" onchange="renCategoria(${c.id},this.value)">
    <span class="eq-tct">${c.uso||0}</span>
    ${podeEditar?`<button class="eq-tdel" title="Excluir" onclick="event.stopPropagation();delCategoria(${c.id})">🗑</button>`:""}
  </div>`).join("")||'<p class="muted" style="font-size:12px">Nenhuma categoria.</p>';
  document.getElementById("lin-list").innerHTML=TAX.linhas.map(l=>`<div class="eq-trow">
    <input class="eq-tname" value="${esc(l.nome)}" onchange="renLinha(${l.id},this.value)">
    <span class="eq-tct">${l.uso||0}</span>
    ${podeEditar?`<button class="eq-tdel" onclick="delLinha(${l.id})">🗑</button>`:""}
  </div>`).join("")||'<p class="muted" style="font-size:12px">Nenhuma linha.</p>';
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
    <p class="muted" style="font-size:11px;margin-top:12px">O vínculo de cada equipamento a uma categoria/família é feito na ficha (aba Equipamentos).</p>`;
}
async function addCategoria(){ const nome=val("cat-new").trim(); if(!nome) return;
  try{ await api("/api/categorias-equipamento",{method:"POST",body:JSON.stringify({nome})}); document.getElementById("cat-new").value=""; await reloadTax(); }catch(e){ toast(e.message,true); } }
async function renCategoria(id,nome){ if(!nome.trim())return; try{ await api("/api/categorias-equipamento/"+id,{method:"PATCH",body:JSON.stringify({nome})}); await reloadTax(); }catch(e){ toast(e.message,true); } }
async function delCategoria(id){ const c=TAX.categorias.find(x=>x.id===id); if(c&&c.uso&&!confirm(`"${c.nome}" está em uso por ${c.uso} equipamento(s). Excluir e desvincular?`))return;
  try{ await api("/api/categorias-equipamento/"+id,{method:"DELETE"}); if(selCatId===id)selCatId=null; await reloadTax(); }catch(e){ toast(e.message,true); } }
async function addFamilia(cid){ const nome=val("fam-new").trim(); if(!nome) return;
  try{ await api("/api/familias-equipamento",{method:"POST",body:JSON.stringify({nome,categoria_id:cid})}); await reloadTax(); }catch(e){ toast(e.message,true); } }
async function delFamilia(id){ try{ await api("/api/familias-equipamento/"+id,{method:"DELETE"}); await reloadTax(); }catch(e){ toast(e.message,true); } }
async function addLinha(){ const nome=val("lin-new").trim(); if(!nome) return;
  try{ await api("/api/linhas-produto",{method:"POST",body:JSON.stringify({nome})}); document.getElementById("lin-new").value=""; await reloadTax(); }catch(e){ toast(e.message,true); } }
async function renLinha(id,nome){ if(!nome.trim())return; try{ await api("/api/linhas-produto/"+id,{method:"PATCH",body:JSON.stringify({nome})}); await reloadTax(); }catch(e){ toast(e.message,true); } }
async function delLinha(id){ try{ await api("/api/linhas-produto/"+id,{method:"DELETE"}); await reloadTax(); }catch(e){ toast(e.message,true); } }
async function reloadTax(){ try{ TAX=await api("/api/equip-taxonomia"); preencherSelectsLista(); renderCategorias(); renderLista(); renderDashboard(); }catch(e){} }

// ══ IMPORTAÇÃO ═════════════════════════════════════════════════════════════
function abrirImport(){ document.getElementById("import-preview").innerHTML="—";
  document.getElementById("btn-aplicar").style.display="none"; document.getElementById("import-file").value="";
  openBaseModal("import"); }
async function rodarImport(dryrun){
  const f=document.getElementById("import-file").files[0];
  const fd=new FormData(); if(f) fd.append("arquivo",f);
  const url="/api/equipamentos/import?dryrun="+(dryrun?"1":"0");
  document.getElementById("import-preview").innerHTML="Processando…";
  try{
    const res=await fetch(url,{method:"POST",headers:{"Authorization":"Bearer "+token()},body:fd});
    const rel=await res.json();
    if(!res.ok){ document.getElementById("import-preview").innerHTML=`<span style="color:var(--red)">${esc(rel.erro||"Falha")}</span>`; return; }
    const incList=(rel.inconsistencias||[]).slice(0,8).map(x=>`linha ${x.linha}: ${esc(x.motivo)}${x.equipamento?(" — "+esc(x.equipamento)):""}`).join("<br>");
    document.getElementById("import-preview").innerHTML=`
      <b>${rel.aplicado?"Importação aplicada":"Prévia"}</b> — ${rel.total_linhas} linhas<br>
      A criar: <b>${rel.a_criar}</b> · A atualizar: <b>${rel.a_atualizar}</b> · Inconsistências: <b>${rel.inconsistencias_n}</b>
      ${incList?`<div class="muted" style="font-size:11px;margin-top:8px">${incList}</div>`:""}`;
    document.getElementById("btn-aplicar").style.display = (dryrun && !rel.erro) ? "inline-flex" : "none";
    if(!dryrun){ toast(`Importado: ${rel.a_criar} criados, ${rel.a_atualizar} atualizados`); await loadAll(); setTimeout(()=>closeModal("import"),1200); }
  }catch(e){ document.getElementById("import-preview").innerHTML=`<span style="color:var(--red)">${esc(e.message)}</span>`; }
}
async function exportarCSV(){
  try{ const res=await fetch("/api/equipamentos/export",{headers:{"Authorization":"Bearer "+token()}});
    const blob=await res.blob(); const a=document.createElement("a"); a.href=URL.createObjectURL(blob); a.download="equipamentos.csv"; a.click(); }
  catch(e){ toast("Erro ao exportar",true); }
}

// ── modais ───────────────────────────────────────────────────────────────────
function openBaseModal(id){ const m=document.getElementById("modal-"+id); if(m){ m.classList.add("open"); m.setAttribute("aria-hidden","false"); } }
function closeModal(id){ const m=document.getElementById("modal-"+id); if(m){ m.classList.remove("open"); m.setAttribute("aria-hidden","true"); } }
document.querySelectorAll(".modal-overlay").forEach(m=>m.addEventListener("click",e=>{ if(e.target===m) closeModal(m.id.replace("modal-","")); }));
document.addEventListener("keydown",e=>{ if(e.key==="Escape") document.querySelectorAll(".modal-overlay.open").forEach(m=>closeModal(m.id.replace("modal-",""))); });

if(!token()){ window.location.href="/"; } else { loadAll(); }
