/* Módulo Consumíveis — catálogo global + compatibilidade N:N + descritivo.
   Depende de globais definidos em equipamentos.js: api, esc, toast, val, EQUIP,
   openBaseModal, closeModal, podeEditar, podeGerir, vfield, vsection, vfields, vchip. */

let CONS = [], TIPOS_C = [], consLoaded = false;
let consView = "cons", consSelEq = "", consCur = null, cvTab = "geral", consEditId = null;

const FORN_LABEL = {
  exclusivo_loccus: "exclusivo Loccus", pode_fornecer: "pode fornecer",
  nao_fornecido: "não fornecido", nao_informado: "não informado",
};
function fbadge(f){ f = FORN_LABEL[f] ? f : "nao_informado"; return `<span class="forn-b forn-${f}">${FORN_LABEL[f]}</span>`; }
function tipoById(id){ return TIPOS_C.find(t => String(t.id) === String(id)) || null; }

async function loadCons(){
  const [cons, tipos] = await Promise.all([ api("/api/consumiveis"), api("/api/tipos-consumivel") ]);
  CONS = cons || []; TIPOS_C = tipos || []; consLoaded = true;
}

async function renderConsumiveis(){
  if(!consLoaded){ try{ await loadCons(); }catch(e){ toast(e.message || "Erro ao carregar consumíveis", true); return; } }
  if(podeEditar){ const b=document.getElementById("btn-cons-novo"); if(b) b.style.display=""; const bi=document.getElementById("btn-cons-import"); if(bi) bi.style.display=""; }
  const tf=document.getElementById("cons-f-tipo");
  if(tf){ const v=tf.value; tf.innerHTML='<option value="">Tipo: todos</option>'+TIPOS_C.map(t=>`<option>${esc(t.nome)}</option>`).join(""); tf.value=v; }
  const ef=document.getElementById("cons-f-eq");
  if(ef){ const v=ef.value; const eqs=[...EQUIP].sort((a,b)=>(a.nome||"").localeCompare(b.nome||"")); ef.innerHTML=eqs.map(e=>`<option value="${e.id}">${esc(e.nome)}</option>`).join(""); if(v) ef.value=v; }
  renderConsGrid();
}

function consSetView(v){
  consView=v;
  document.getElementById("cseg-cons").classList.toggle("on",v==="cons");
  document.getElementById("cseg-eq").classList.toggle("on",v==="eq");
  document.getElementById("cons-wrap-busca").style.display=v==="cons"?"":"none";
  document.getElementById("cons-f-tipo").style.display=v==="cons"?"":"none";
  document.getElementById("cons-lbl-pend").style.display=v==="cons"?"flex":"none";
  document.getElementById("cons-f-eq").style.display=v==="eq"?"":"none";
  document.getElementById("cons-grid").style.display=v==="cons"?"grid":"none";
  document.getElementById("cons-eqview").style.display=v==="eq"?"block":"none";
  renderConsGrid();
}

async function renderConsGrid(){
  const badge=document.getElementById("cons-badge");
  if(consView==="cons"){
    const q=(val("cons-busca")||"").toLowerCase(), tf=val("cons-f-tipo"), pd=(document.getElementById("cons-f-pend")||{}).checked;
    const rows=CONS.filter(c=>(!tf||c.tipo===tf)&&(!pd||c.pendente_sku)&&(!q||(c.nome||"").toLowerCase().includes(q)||(c.sku||"").toLowerCase().includes(q)));
    if(badge) badge.textContent=rows.length+" itens";
    document.getElementById("cons-grid").innerHTML=rows.map(c=>`<div class="cons-card ${c.pendente_sku?'pend':''}" onclick="abrirConsView(${c.id})">
      <div class="cons-topline"><span class="eq-chip">${esc(c.tipo||"—")}</span>${c.pendente_sku?'<span class="eq-chip" style="background:rgba(245,158,11,.14);color:#fbbf24">sem SKU</span>':''}</div>
      <div class="cons-card-name">${esc(c.nome)}</div>
      <div class="cons-card-sku">${c.sku?esc(c.sku):'<span class="muted">sem SKU</span>'}</div>
      <div class="cons-card-foot">🔗 ${c.n_equip} equipamento${c.n_equip!==1?'s':''} compatíve${c.n_equip!==1?'is':'l'}</div>
    </div>`).join("")||'<div class="muted" style="grid-column:1/-1;text-align:center;padding:30px">Nenhum consumível.</div>';
  }else{
    const eid=val("cons-f-eq"); const eq=EQUIP.find(e=>String(e.id)===String(eid));
    const box=document.getElementById("cons-eqview");
    if(!eid){ box.innerHTML='<div class="muted" style="padding:20px">Selecione um equipamento.</div>'; if(badge) badge.textContent="—"; return; }
    let list=[]; try{ list=await api("/api/equipamentos/"+eid+"/consumiveis"); }catch(e){ toast(e.message,true); }
    if(badge) badge.textContent=list.length+" consumíveis";
    box.innerHTML=`<div style="padding:4px 2px 12px;margin-bottom:6px;border-bottom:1px solid var(--border-soft)">
        <div style="font-size:16px;font-weight:700;color:var(--t1)">${esc(eq?eq.nome:"")}</div>
        <div style="font-size:12px;color:var(--t3);margin-top:2px">Consumíveis compatíveis (o vínculo lido pelo lado do equipamento)</div></div>`+
      (list.map(v=>`<div class="cons-eqrow" onclick="abrirConsView(${v.consumivel_id})">
        <div><div style="font-size:13px;color:var(--t1)">${esc(v.nome)}</div><div class="cons-card-sku">${esc(v.tipo||"—")}${v.sku?' · '+esc(v.sku):' · sem SKU'}</div></div>
        ${fbadge(v.fornecimento)}</div>`).join("")||'<div class="muted" style="padding:20px">Nenhum consumível vinculado.</div>');
  }
}

// ── ficha (leitura + abas) ────────────────────────────────────────────────────
function cvPanel(k,c){
  if(k==="geral") return `<div class="vw-body">${vsection("Identificação e cadastro", vfields([
      vfield("Fabricante",c.fabricante),
      vfield("SKU de venda",c.sku),
      vfield("SKU de importação",c.sku_importacao),
      vfield("Tipo",c.tipo),
      vfield("Situação",c.pendente_sku?"Pendente de cadastro (sem SKU)":"Cadastrado"),
      vfield("Descrição",c.descricao,true),
  ]))}</div>`;
  if(k==="espec"){
    const t=tipoById(c.tipo_id); const campos=(t&&t.campos)||[]; const at=c.atributos||{};
    const modelo=campos.map(cp=>{ let v=at[cp.chave]; if(cp.tipo_dado==="bool") v=(v===true||v==="true"||v==="sim")?"Sim":(v===false||v==="false"||v==="não"||v==="nao")?"Não":v;
      const un=cp.unidade&&v?(" "+cp.unidade):""; return vfield(cp.rotulo,(v!==undefined&&v!==null&&v!=="")?(v+un):"", cp.rotulo.length>16); });
    const chaves=new Set(campos.map(cp=>cp.chave));
    const extras=Object.keys(at).filter(k2=>k2!=="descritivo"&&!chaves.has(k2)&&at[k2]!==""&&at[k2]!=null).map(k2=>vfield(k2,at[k2]));
    let html=`<div class="vw-body">`;
    html+=modelo.length?vsection("Especificações do tipo", vfields(modelo)):`<div class="vw-sec"><div class="vw-empty">Este tipo ainda não tem campos definidos (configure em Tipos de consumível).</div></div>`;
    if(extras.length) html+=vsection("Outros campos (extras deste item)", vfields(extras));
    return html+`</div>`;
  }
  if(k==="descritivo"){
    const d=(c.atributos&&c.atributos.descritivo)||{};
    const id=d.identificacao||{}, ds=d.descricao||{}, tc=d.tecnicas||{}, em=d.embalagem||{};
    let html=`<div class="vw-body">`;
    html+=vsection("Identificação", vfields([
      vfield("Código",id.codigo),
      vfield("Área",id.area),
      vfield("SKU Protheus",c.sku),
      vfield("Fornecedor",c.fabricante),
      vfield("Origem",id.origem),
      vfield("Criticidade",id.criticidade),
    ]));
    html+=vsection("Descrição do produto", vfields([
      vfield("Nome comercial",ds.nome_comercial),
      vfield("Categoria",ds.categoria),
      vfield("Aplicação",ds.aplicacao,true),
      vfield("Descrição",c.descricao,true),
    ]));
    html+=vsection("Características técnicas", vfields([
      vfield("Material",tc.material),
      vfield("Dimensões",tc.dimensoes),
      vfield("Esterilidade",tc.esterilidade),
      vfield("Desempenho",tc.desempenho,true),
      vfield("Compatibilidade",tc.compatibilidade,true),
    ]));
    html+=vsection("Embalagem", vfields([
      vfield("Tipo primária",em.tipo_primaria),
      vfield("Tipo secundária",em.tipo_secundaria),
      vfield("Quantidade",em.quantidade),
    ]));
    return html+`</div>`;
  }
  // compatibilidade
  const eqs=(c.equipamentos||[]).slice().sort((a,b)=>(a.equipamento_nome||"").localeCompare(b.equipamento_nome||""));
  const jaTem=new Set(eqs.map(v=>v.equipamento_id));
  const disp=[...EQUIP].filter(e=>!jaTem.has(e.id)).sort((a,b)=>(a.nome||"").localeCompare(b.nome||""));
  const rows=eqs.map(v=>`<tr><td>${esc(v.equipamento_nome)}</td><td>${
      podeEditar?`<select class="filter-sel" style="padding:5px 8px;font-size:12px" onchange="mudarForn(${v.vinculo_id},this.value)">${
        Object.keys(FORN_LABEL).map(f=>`<option value="${f}" ${v.fornecimento===f?'selected':''}>${FORN_LABEL[f]}</option>`).join("")}</select>`:fbadge(v.fornecimento)
    }</td>${podeEditar?`<td style="width:34px"><button class="eq-tdel" title="Remover" onclick="removerVinculo(${v.vinculo_id})">🗑</button></td>`:""}</tr>`).join("");
  const add=podeEditar?`<div class="cons-linkadd">
      <select class="filter-sel" id="cons-add-eq" style="flex:1;min-width:180px">${disp.map(e=>`<option value="${e.id}">${esc(e.nome)}</option>`).join("")||'<option value="">— todos já vinculados —</option>'}</select>
      <select class="filter-sel" id="cons-add-forn">${Object.keys(FORN_LABEL).map(f=>`<option value="${f}" ${f==='pode_fornecer'?'selected':''}>${FORN_LABEL[f]}</option>`).join("")}</select>
      <button class="btn btn-primary btn-sm" onclick="vincularCons()">+ vincular</button></div>`:"";
  return `<div class="vw-body">${vsection("Compatível com",
    `<table class="vw-itbl"><thead><tr><th>Equipamento</th><th style="width:180px">Fornecimento</th>${podeEditar?"<th></th>":""}</tr></thead><tbody>${rows||'<tr><td colspan="3" class="vw-empty">Nenhum equipamento vinculado.</td></tr>'}</tbody></table>${add}`, eqs.length)}</div>`;
}

async function abrirConsView(id, keepTab){
  let c; try{ c=await api("/api/consumiveis/"+id); }catch(e){ toast(e.message,true); return; }
  consCur=c; if(!keepTab) cvTab="geral";
  const chips=[]; if(c.tipo) chips.push(vchip(c.tipo,"cat")); if(c.sku) chips.push(vchip("SKU "+c.sku,"mono"));
  chips.push(c.pendente_sku?vchip("pendente de cadastro","warn"):vchip("cadastrado","ok"));
  document.getElementById("consview-hero").innerHTML=`<div class="vw-hero"><div class="vw-hero-main"><div class="vw-name">${esc(c.nome)}</div><div class="vw-chips">${chips.join("")}</div></div></div>`;
  const tabs=[["geral","Geral"],["descritivo","Descritivo técnico"],["espec","Especificações"],["compat","Compatibilidade ("+(c.equipamentos||[]).length+")"]];
  document.getElementById("consview-tabs").innerHTML=tabs.map(([k,l])=>`<button class="equip-modal-tab ${k===cvTab?'active':''}" onclick="switchCvTab('${k}')">${esc(l)}</button>`).join("");
  document.getElementById("consview-panels").innerHTML=cvPanel(cvTab,c);
  const eb=document.getElementById("consview-edit"); if(eb) eb.style.display=podeEditar?"inline-flex":"none";
  openBaseModal("consview");
}
function switchCvTab(k){ cvTab=k; const c=consCur;
  document.querySelectorAll("#consview-tabs .equip-modal-tab").forEach(b=>b.classList.toggle("active",(b.getAttribute("onclick")||"").includes("'"+k+"'")));
  document.getElementById("consview-panels").innerHTML=cvPanel(k,c);
}

async function vincularCons(){
  const eid=val("cons-add-eq"); if(!eid) return; const forn=val("cons-add-forn");
  try{ await api("/api/consumiveis/"+consCur.id+"/equipamentos",{method:"POST",body:JSON.stringify({equipamento_id:parseInt(eid),fornecimento:forn})});
    toast("Equipamento vinculado"); await refreshConsAfter(consCur.id,"compat"); }
  catch(e){ toast(e.message,true); }
}
async function mudarForn(vid,forn){ try{ await api("/api/consumivel-equipamento/"+vid,{method:"PATCH",body:JSON.stringify({fornecimento:forn})}); toast("Fornecimento atualizado"); }catch(e){ toast(e.message,true); } }
async function removerVinculo(vid){ if(!confirm("Remover este vínculo?")) return;
  try{ await api("/api/consumivel-equipamento/"+vid,{method:"DELETE"}); toast("Vínculo removido"); await refreshConsAfter(consCur.id,"compat"); }catch(e){ toast(e.message,true); } }
async function refreshConsAfter(id,tab){ cvTab=tab||cvTab; await loadCons(); await abrirConsView(id,true); }

function consViewEdit(){ const id=consCur&&consCur.id; closeModal("consview"); if(id) abrirConsEdit(id); }

// ── novo / editar ─────────────────────────────────────────────────────────────
function preencherTipoSelect(sel,val2){ sel.innerHTML='<option value="">—</option>'+TIPOS_C.map(t=>`<option value="${t.id}" ${String(val2)===String(t.id)?'selected':''}>${esc(t.nome)}</option>`).join(""); }
// campos do descritivo que moram no JSON (fornecedor→fabricante, sku_protheus→sku e descrição→descricao reusam colunas)
const DESCR_MAP={ identificacao:["codigo","area","origem","criticidade"], descricao:["nome_comercial","categoria","aplicacao"],
  tecnicas:["material","dimensoes","esterilidade","desempenho","compatibilidade"], embalagem:["tipo_primaria","tipo_secundaria","quantidade"] };
function _preencherDescritivo(d){ d=d||{};
  Object.keys(DESCR_MAP).forEach(sec=>{ const src=d[sec]||{}; DESCR_MAP[sec].forEach(k=>{ const el=document.getElementById("ced-"+k); if(el) el.value=src[k]!=null?src[k]:""; }); }); }
function _coletarDescritivo(){ const o={};
  Object.keys(DESCR_MAP).forEach(sec=>{ o[sec]={}; DESCR_MAP[sec].forEach(k=>{ const el=document.getElementById("ced-"+k); o[sec][k]=el?el.value.trim():""; }); }); return o; }
function abrirConsNovo(){ consEditId=null; document.getElementById("consedit-title").textContent="Novo consumível";
  ["nome","sku","sku_importacao","fabricante","descricao"].forEach(f=>{ const el=document.getElementById("ce-"+f); if(el) el.value=""; });
  _preencherDescritivo({});
  preencherTipoSelect(document.getElementById("ce-tipo_id"),""); consEditCamposDoTipo({}); openBaseModal("consedit"); }
function abrirConsEdit(id){ const c=CONS.find(x=>x.id===id)||consCur; if(!c) return; consEditId=id;
  document.getElementById("consedit-title").textContent="Editar consumível";
  document.getElementById("ce-nome").value=c.nome||""; document.getElementById("ce-sku").value=c.sku||"";
  document.getElementById("ce-sku_importacao").value=c.sku_importacao||""; document.getElementById("ce-fabricante").value=c.fabricante||"";
  document.getElementById("ce-descricao").value=c.descricao||"";
  _preencherDescritivo((c.atributos||{}).descritivo);
  preencherTipoSelect(document.getElementById("ce-tipo_id"),c.tipo_id); consEditCamposDoTipo(c.atributos||{}); openBaseModal("consedit"); }
function consEditCamposDoTipo(atributos){
  const t=tipoById(val("ce-tipo_id")); const box=document.getElementById("ce-campos"); const at=atributos||_coletarAttrAtuais();
  if(!t||!(t.campos||[]).length){ box.innerHTML=""; return; }
  box.innerHTML=`<div class="form-label" style="margin-bottom:8px">Campos do tipo — ${esc(t.nome)}</div><div class="g2">`+
    t.campos.map(cp=>{ const v=at[cp.chave]; const un=cp.unidade?` (${cp.unidade})`:"";
      if(cp.tipo_dado==="bool") return `<div class="form-group" style="margin:0"><label class="form-label">${esc(cp.rotulo)}</label><label class="muted" style="display:flex;align-items:center;gap:8px;padding-top:9px"><input type="checkbox" id="ce-attr-${cp.chave}" ${(v===true||v==="true"||v==="sim")?'checked':''}> sim</label></div>`;
      return `<div class="form-group" style="margin:0"><label class="form-label">${esc(cp.rotulo)}${un}</label><input class="form-input" id="ce-attr-${cp.chave}" value="${esc(v!=null?v:"")}"></div>`;
    }).join("")+`</div>`;
}
function _coletarAttrAtuais(){ const t=tipoById(val("ce-tipo_id")); const o={}; if(!t) return o;
  (t.campos||[]).forEach(cp=>{ const el=document.getElementById("ce-attr-"+cp.chave); if(!el) return; o[cp.chave]=cp.tipo_dado==="bool"?el.checked:el.value.trim(); }); return o; }
async function salvarConsumivel(){
  const nome=val("ce-nome").trim(); if(!nome){ toast("Informe o nome",true); return; }
  const base=(consEditId?((CONS.find(x=>x.id===consEditId)||consCur||{}).atributos||{}):{});
  const atributos=Object.assign({},base,_coletarAttrAtuais()); atributos.descritivo=_coletarDescritivo();
  const payload={ nome, sku:val("ce-sku").trim(), sku_importacao:val("ce-sku_importacao").trim(),
    fabricante:val("ce-fabricante").trim(), descricao:val("ce-descricao").trim(),
    tipo_id:val("ce-tipo_id")||null, atributos };
  try{
    if(consEditId) await api("/api/consumiveis/"+consEditId,{method:"PATCH",body:JSON.stringify(payload)});
    else await api("/api/consumiveis",{method:"POST",body:JSON.stringify(payload)});
    toast("Consumível salvo"); closeModal("consedit"); await loadCons(); renderConsGrid();
    if(consEditId) abrirConsView(consEditId,true);
  }catch(e){ toast(e.message,true); }
}
async function excluirConsumivel(){ if(!consCur) return; if(!confirm("Excluir este consumível?")) return;
  try{ await api("/api/consumiveis/"+consCur.id,{method:"DELETE"}); toast("Consumível excluído"); closeModal("consview"); await loadCons(); renderConsGrid(); }catch(e){ toast(e.message,true); } }

// ── descritivo (export/import) ────────────────────────────────────────────────
async function baixarJSON(url, filename){
  const res=await fetch(url,{headers:{"Authorization":"Bearer "+token()}});
  if(!res.ok){ toast("Falha ao exportar",true); return; }
  const data=await res.json(); const blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"});
  const a=document.createElement("a"); a.href=URL.createObjectURL(blob); a.download=filename; a.click();
}
function exportarDescritivo(){ if(!consCur) return; const nome=(consCur.sku||consCur.nome||"consumivel").replace(/[^\w.-]+/g,"_"); baixarJSON("/api/consumiveis/"+consCur.id+"/descritivo","descritivo_"+nome+".json"); }
function abrirConsImport(){ document.getElementById("consimport-json").value=""; document.getElementById("consimport-preview").textContent="—"; document.getElementById("btn-consimport-aplicar").style.display="none";
  const fi=document.getElementById("consimport-docx"); if(fi) fi.value=""; const fn=document.getElementById("consimport-docx-nome"); if(fn){ fn.textContent="Nenhum arquivo selecionado."; fn.style.color=""; }
  openBaseModal("consimport"); }
async function lerConsDocx(input){
  const file=input.files&&input.files[0]; if(!file) return;
  const fn=document.getElementById("consimport-docx-nome"); fn.textContent="Lendo "+file.name+"…"; fn.style.color="";
  const fd=new FormData(); fd.append("arquivo",file);
  try{
    const res=await fetch("/api/consumiveis/descritivo/import-docx",{method:"POST",headers:{"Authorization":"Bearer "+token()},body:fd});
    const data=await res.json();
    if(!res.ok){ fn.textContent=data.erro||"Falha ao ler o .docx"; fn.style.color="#f43f5e"; return; }
    document.getElementById("consimport-json").value=JSON.stringify(data.item,null,2);
    fn.textContent="✓ "+file.name+" — confira a prévia abaixo."; fn.style.color="#34d399";
    rodarConsImport(true);   // já dispara a prévia
  }catch(e){ fn.textContent=e.message||"Erro ao ler o arquivo"; fn.style.color="#f43f5e"; }
}
async function rodarConsImport(dryrun){
  const raw=val("consimport-json").trim(); const prev=document.getElementById("consimport-preview");
  if(!raw){ prev.innerHTML='<span style="color:#f43f5e">Escolha um arquivo .docx primeiro.</span>'; return; }
  let parsed; try{ parsed=JSON.parse(raw); }catch(e){ prev.innerHTML='<span style="color:#f43f5e">JSON inválido: '+esc(e.message)+'</span>'; return; }
  try{
    const rel=await api("/api/consumiveis/descritivo/import",{method:"POST",body:JSON.stringify({descritivo:parsed,dryrun})});
    const det=(rel.itens||[]).slice(0,8).map(r=>{ const ex=r.extras&&r.extras.length?` · extras: ${r.extras.join(", ")}`:""; const ne=r.equip_nao_encontrado?` · equip. não encontrado: ${r.equip_nao_encontrado.join(", ")}`:""; return `${r.acao}: ${esc(r.nome||r.sku||"?")}${ex}${ne}`; }).join("<br>");
    prev.innerHTML=`<b>${rel.aplicado?"Importado":"Prévia"}</b> — ${rel.total} item(ns) · criar: <b>${rel.a_criar}</b> · atualizar: <b>${rel.a_atualizar}</b>${det?`<div class="muted" style="font-size:11px;margin-top:8px">${det}</div>`:""}`;
    document.getElementById("btn-consimport-aplicar").style.display=dryrun?"inline-flex":"none";
    if(!dryrun){ toast(`Descritivo aplicado (${rel.a_criar} criados, ${rel.a_atualizar} atualizados)`); await loadCons(); renderConsGrid(); setTimeout(()=>closeModal("consimport"),1200); }
  }catch(e){ prev.innerHTML='<span style="color:#f43f5e">'+esc(e.message)+'</span>'; }
}
async function exportarConsCSV(){
  try{ const res=await fetch("/api/consumiveis/export",{headers:{"Authorization":"Bearer "+token()}});
    const blob=await res.blob(); const a=document.createElement("a"); a.href=URL.createObjectURL(blob); a.download="consumiveis.csv"; a.click(); }
  catch(e){ toast("Erro ao exportar",true); }
}
function copiarConsFicha(){ const c=consCur; if(!c) return; const L=[c.nome||""]; const add=(k,v)=>{ if(v&&String(v).trim()) L.push(k+": "+v); };
  add("Tipo",c.tipo); add("SKU de venda",c.sku); add("SKU de importação",c.sku_importacao); add("Fabricante",c.fabricante); add("Descrição",c.descricao);
  const at=c.atributos||{}; Object.keys(at).forEach(k=>{ if(k!=="descritivo") add(k,at[k]); });   // descritivo é objeto → formatado à parte
  const d=at.descritivo;
  if(d&&typeof d==="object"){
    const sec=(titulo,obj,labels)=>{ const rows=Object.keys(labels).map(k=>(obj&&obj[k]&&String(obj[k]).trim())?("  "+labels[k]+": "+obj[k]):null).filter(Boolean); if(rows.length){ L.push(""); L.push(titulo+":"); rows.forEach(r=>L.push(r)); } };
    L.push(""); L.push("── Descritivo técnico ──");
    sec("Identificação",Object.assign({},d.identificacao,{sku_protheus:c.sku,fornecedor:c.fabricante}),{codigo:"Código",area:"Área",sku_protheus:"SKU Protheus",fornecedor:"Fornecedor",origem:"Origem",criticidade:"Criticidade"});
    sec("Descrição do produto",Object.assign({},d.descricao,{descricao:c.descricao}),{nome_comercial:"Nome comercial",categoria:"Categoria",aplicacao:"Aplicação",descricao:"Descrição"});
    sec("Características técnicas",d.tecnicas,{material:"Material",dimensoes:"Dimensões",esterilidade:"Esterilidade",desempenho:"Desempenho",compatibilidade:"Compatibilidade"});
    sec("Embalagem",d.embalagem,{tipo_primaria:"Tipo primária",tipo_secundaria:"Tipo secundária",quantidade:"Quantidade"});
  }
  if((c.equipamentos||[]).length){ L.push(""); L.push("Compatível com:"); c.equipamentos.forEach(v=>L.push("  - "+v.equipamento_nome+" ("+(FORN_LABEL[v.fornecimento]||v.fornecimento)+")")); }
  const txt=L.join("\n");
  if(navigator.clipboard&&navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(()=>toast("Ficha copiada")).catch(()=>toast("Falha ao copiar",true));
  else { const ta=document.createElement("textarea"); ta.value=txt; document.body.appendChild(ta); ta.select(); try{ document.execCommand("copy"); toast("Ficha copiada"); }catch(_){ toast("Falha ao copiar",true); } document.body.removeChild(ta); }
}

// ── tipos de consumível (config) ──────────────────────────────────────────────
async function renderTiposCons(){
  if(!consLoaded){ try{ await loadCons(); }catch(e){ toast(e.message,true); return; } }
  else { try{ TIPOS_C=await api("/api/tipos-consumivel"); }catch(e){} }
  if(podeEditar){ const a=document.getElementById("tipos-cons-add"); if(a) a.style.display="flex"; }
  document.getElementById("tipos-cons-list").innerHTML=TIPOS_C.map(t=>{
    const chips=(t.campos||[]).map(cp=>`<span class="eq-chip">${esc(cp.rotulo)}${cp.unidade?` (${esc(cp.unidade)})`:""}</span>`).join(" ")||'<span class="muted" style="font-size:12px">sem campos definidos</span>';
    return `<div class="tipo-cons-row">
      <div class="tipo-cons-name">${esc(t.nome)} <span class="eq-tct">${t.uso||0} consumíveis</span>
        <button class="btn btn-ghost btn-sm" style="margin-left:auto;padding:4px 10px" onclick="exportarModeloTipo(${t.id})">⬇ Modelo em branco</button></div>
      <div class="eq-chips" style="margin-top:8px">${chips}</div>
    </div>`;
  }).join("")||'<div class="muted" style="padding:20px">Nenhum tipo cadastrado.</div>';
}
async function addTipoCons(){ const nome=val("tipo-cons-new").trim(); if(!nome){ toast("Informe o nome",true); return; }
  try{ await api("/api/tipos-consumivel",{method:"POST",body:JSON.stringify({nome,campos:[]})}); document.getElementById("tipo-cons-new").value=""; TIPOS_C=await api("/api/tipos-consumivel"); renderTiposCons(); toast("Tipo criado"); }catch(e){ toast(e.message,true); } }
function exportarModeloTipo(tid){ baixarJSON("/api/tipos-consumivel/"+tid+"/descritivo-modelo","modelo_descritivo.json"); }
