/* Módulo Missões — board kanban nativo (SortableJS + lock otimista por versao) */
const TOKEN_KEY = "doctrack_token";
function token(){ return localStorage.getItem(TOKEN_KEY) || ""; }
function userObj(){ try{ return JSON.parse(localStorage.getItem("doctrack_user")||"{}")||{}; }catch(e){ return {}; } }
const ROLE = (userObj().role)||"";
const podeUsar = ["admin","gestor","tecnico"].includes(ROLE);
sessionStorage.setItem("dt_module", "missoes");

function applyTheme(t){ const l=t==="light"; document.body.classList.toggle("theme-light",l);
  const b=document.getElementById("theme-toggle"); if(b) b.textContent=l?"☀️":"🌙"; }
function toggleTheme(){ const n=document.body.classList.contains("theme-light")?"dark":"light";
  localStorage.setItem("doctrack_theme",n); applyTheme(n); }
applyTheme(localStorage.getItem("doctrack_theme")||"dark");
function doLogout(){ localStorage.removeItem("doctrack_token"); localStorage.removeItem("doctrack_user"); window.location.href="/"; }

async function api(url, opts={}){
  const res = await fetch(url, {...opts, headers:{
    "Content-Type":"application/json", "Authorization":"Bearer "+token(), ...(opts.headers||{})}});
  if(res.status===401){ window.location.href="/"; throw new Error("401"); }
  if(res.status===409){ const b=await res.json().catch(()=>({}));
    const e=new Error(b.erro||"conflito"); e.conflito=true; e.body=b; throw e; }
  if(!res.ok){ const b=await res.json().catch(()=>({})); throw new Error(b.erro||("HTTP "+res.status)); }
  return res.json();
}
function toast(msg, erro=false){ const t=document.getElementById("toast");
  t.textContent=msg; t.style.display="block"; t.style.borderColor=erro?"#ef4444":"#22d3ee";
  clearTimeout(t._h); t._h=setTimeout(()=>t.style.display="none",3200); }
function esc(s){ const d=document.createElement("div"); d.textContent=s??""; return d.innerHTML; }

// ── estado ──────────────────────────────────────────────────────────────
let MISSOES=[], BOARD=null;        // BOARD = missão ativa completa (colunas+cartões)
let missaoEditando=null, cartaoEditando=null, colunaDoNovoCartao=null;
let sortables=[], USUARIOS=null, RESP_SEL=[];   // usuários da plataforma + responsáveis do modal

// ── boot ────────────────────────────────────────────────────────────────
(function boot(){
  if(!token()){ window.location.href="/"; return; }
  if(!podeUsar){ window.location.href="/hub"; return; }
  document.getElementById("app").style.display="block";   // style.css esconde #app por padrão
  const u=userObj();
  document.getElementById("nav-name").textContent=u.nome||"—";
  document.getElementById("nav-role").textContent=(u.role||"").toUpperCase();
  document.getElementById("nav-avatar").textContent=(u.nome||"?").charAt(0).toUpperCase();
  document.getElementById("btn-nova-missao").onclick=()=>abrirModalMissao();
  document.getElementById("mi-salvar").onclick=salvarMissao;
  document.getElementById("btn-editar-missao").onclick=()=>abrirModalMissao(BOARD);
  document.getElementById("btn-excluir-missao").onclick=excluirMissao;
  document.getElementById("ca-salvar").onclick=salvarCartao;
  document.getElementById("ca-excluir").onclick=excluirCartao;
  document.getElementById("ca-ref-tipo").onchange=carregarRefs;
  document.getElementById("co-salvar").onclick=salvarColuna;
  document.getElementById("btn-meus-cartoes").onclick=abrirMeusCartoes;
  document.getElementById("ca-resp-select").onchange=addResponsavel;
  const tg=document.getElementById("sidebar-toggle");
  if(tg) tg.onclick=()=>{ document.getElementById("sidebar-nav").classList.toggle("open");
    document.getElementById("sidebar-backdrop").classList.toggle("open"); };   // style.css usa .open no backdrop
  const bd=document.getElementById("sidebar-backdrop");
  if(bd) bd.onclick=()=>{ document.getElementById("sidebar-nav").classList.remove("open"); bd.classList.remove("open"); };
  loadAll();
  conectarSocket();
})();

async function loadAll(){
  try{
    const r=await api("/api/missoes");
    MISSOES=r.missoes||[];
    renderSidebar();
    const salva=parseInt(sessionStorage.getItem("dt_missao")||"0");
    const alvo=MISSOES.find(m=>m.id===salva)||MISSOES[0];
    if(alvo) await selecionarMissao(alvo.id);
    else mostrarVazio();
    // badge "Meus cartões" (best-effort, não bloqueia o board)
    api("/api/missoes/meus-cartoes").then(r=>{
      document.getElementById("meus-badge").textContent=(r.cartoes||[]).length||"";
    }).catch(()=>{});
  }catch(e){ toast("Erro ao carregar missões: "+e.message, true); }
}

function renderSidebar(){
  const box=document.getElementById("lista-missoes");
  box.innerHTML=MISSOES.map(m=>`
    <button type="button" class="nav-item ${BOARD&&BOARD.id===m.id?"active":""}" data-id="${m.id}">
      <span class="dot" style="background:${esc(m.accent||"#22d3ee")}"></span>
      <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left">${esc(m.nome)}</span>
      <span style="font-size:10px;color:var(--t4)">${m.n_cartoes||0}</span>
    </button>`).join("");
  box.querySelectorAll(".nav-item").forEach(b=>{
    b.onclick=()=>selecionarMissao(parseInt(b.dataset.id));
  });
}

function mostrarVazio(){
  BOARD=null;
  document.getElementById("board").style.display="none";
  document.getElementById("meus").style.display="none";
  document.getElementById("board-vazio").style.display="flex";
  document.getElementById("breadcrumb-current").textContent="—";
  document.getElementById("btn-editar-missao").style.display="none";
  document.getElementById("btn-excluir-missao").style.display="none";
}

async function selecionarMissao(id){
  try{
    const r=await api("/api/missoes/"+id);
    BOARD=r.missao;
    sessionStorage.setItem("dt_missao", String(id));
    renderSidebar();
    renderBoard();
  }catch(e){ toast("Erro ao abrir missão: "+e.message, true); }
}

// ── board ───────────────────────────────────────────────────────────────
function renderBoard(){
  if(!BOARD) return mostrarVazio();
  document.getElementById("board-vazio").style.display="none";
  document.getElementById("meus").style.display="none";
  const el=document.getElementById("board");
  el.style.display="flex";
  document.getElementById("breadcrumb-current").textContent=BOARD.nome;
  document.getElementById("btn-editar-missao").style.display="";
  document.getElementById("btn-excluir-missao").style.display="";
  document.documentElement.style.setProperty("--accent", BOARD.accent||"#22d3ee");

  sortables.forEach(s=>{ try{ s.destroy(); }catch(e){} }); sortables=[];
  el.innerHTML=(BOARD.colunas||[]).map(c=>`
    <div class="coluna" data-id="${c.id}">
      <div class="coluna-head">
        <span class="coluna-cor" style="background:${esc(c.cor||BOARD.accent||"#22d3ee")}"></span>
        <span class="coluna-nome" title="Clique para renomear" data-id="${c.id}">${esc(c.nome)}</span>
        <span class="coluna-count">${(c.cartoes||[]).length}</span>
        <button class="coluna-x" title="Excluir coluna" data-id="${c.id}">×</button>
      </div>
      <div class="cartoes" data-coluna="${c.id}">
        ${(c.cartoes||[]).map(renderCartao).join("")}
      </div>
      <button class="add-cartao" data-coluna="${c.id}">＋ Adicionar cartão</button>
    </div>`).join("")+
    `<button class="add-coluna" id="btn-add-coluna">＋ Coluna</button>`;

  // interações
  el.querySelectorAll(".coluna-nome").forEach(n=>{ n.onclick=()=>{
    if(Date.now()-(window._dragTs||0)<300) return;   // clique fantasma pós-drag da coluna
    renomearColuna(parseInt(n.dataset.id)); }; });
  el.querySelectorAll(".coluna-x").forEach(b=>{ b.onclick=()=>excluirColuna(parseInt(b.dataset.id)); });
  el.querySelectorAll(".add-cartao").forEach(b=>{ b.onclick=()=>abrirModalCartao(null, parseInt(b.dataset.coluna)); });
  el.querySelectorAll(".cartao").forEach(c=>{ c.onclick=()=>{
    if(Date.now()-(window._dragTs||0)<300) return;   // ignora o clique fantasma pós-drag
    abrirModalCartao(parseInt(c.dataset.id), null); }; });
  document.getElementById("btn-add-coluna").onclick=novaColuna;

  // drag-and-drop de cartões
  el.querySelectorAll(".cartoes").forEach(zone=>{
    sortables.push(new Sortable(zone, {
      group:"cartoes", animation:150, ghostClass:"sortable-ghost", dragClass:"sortable-drag",
      onEnd: onDragEnd,
    }));
  });
  // drag-and-drop das próprias colunas (pega pelo cabeçalho)
  sortables.push(new Sortable(el, {
    animation:150, draggable:".coluna", handle:".coluna-head", ghostClass:"sortable-ghost",
    onEnd: async ()=>{
      window._dragTs=Date.now();
      const ids=[...el.querySelectorAll(".coluna")].map(c=>parseInt(c.dataset.id));
      try{
        await api("/api/missoes/reordenar",{method:"POST",body:JSON.stringify({missao_id:BOARD.id, colunas_ids:ids})});
        await selecionarMissao(BOARD.id);
      }catch(e){ toast("Erro ao mover coluna: "+e.message, true); await selecionarMissao(BOARD.id); }
    },
  }));
}

function renderCartao(c){
  const chips=[];
  (c.etiquetas||"").split(",").map(s=>s.trim()).filter(Boolean).slice(0,3)
    .forEach(e=>chips.push(`<span class="chip etiqueta">${esc(e)}</span>`));
  if(c.prazo){
    const vencido=!c.concluido && c.prazo < new Date().toISOString().slice(0,10);
    chips.push(`<span class="chip prazo ${vencido?"vencido":""}">📅 ${esc(c.prazo.split("-").reverse().join("/"))}</span>`);
  }
  const resp=(c.responsaveis||"").split(",").map(s=>s.trim()).filter(Boolean);
  if(resp.length) chips.push(`<span class="chip resp">👤 ${esc(resp[0])}${resp.length>1?" +"+(resp.length-1):""}</span>`);
  if(c.ref_label){
    // chip clicável: navega para a entidade vinculada (equipamento abre a ficha via deep-link)
    const url=c.ref_tipo==="equipamento" ? "/equipamentos?ficha="+c.ref_id
             : c.ref_tipo==="projeto" ? "/projetos" : "/";
    chips.push(`<a class="chip ref" href="${url}" onclick="event.stopPropagation()" title="Abrir ${esc(c.ref_tipo)}">🔗 ${esc(c.ref_label)}</a>`);
  }
  return `<div class="cartao ${c.concluido?"concluido":""}" data-id="${c.id}" data-versao="${c.versao}">
    <div style="display:flex;gap:8px;align-items:flex-start">
      <span class="pri pri-${esc(c.prioridade||"media")}" style="margin-top:5px" title="Prioridade ${esc(c.prioridade)}"></span>
      <div class="cartao-titulo" style="flex:1">${esc(c.titulo)}</div>
    </div>
    ${chips.length?`<div class="cartao-meta">${chips.join("")}</div>`:""}
  </div>`;
}

async function onDragEnd(ev){
  window._dragTs=Date.now();
  const cartaoId=parseInt(ev.item.dataset.id);
  const versao=parseInt(ev.item.dataset.versao||"0");
  const destinoId=parseInt(ev.to.dataset.coluna);
  const origemId=parseInt(ev.from.dataset.coluna);
  const ids=[...ev.to.querySelectorAll(".cartao")].map(c=>parseInt(c.dataset.id));
  try{
    if(destinoId!==origemId){
      const idsOrigem=[...ev.from.querySelectorAll(".cartao")].map(c=>parseInt(c.dataset.id));
      await api("/api/missoes/reordenar",{method:"POST",body:JSON.stringify({
        cartao_id:cartaoId, versao, coluna_destino_id:destinoId, ids, ids_origem:idsOrigem})});
    }else{
      await api("/api/missoes/reordenar",{method:"POST",body:JSON.stringify({coluna_id:destinoId, ids})});
    }
    await selecionarMissao(BOARD.id);   // estado real do servidor (contadores/versões)
  }catch(e){
    if(e.conflito) toast("⚠ Outro usuário moveu esse cartão — recarregando", true);
    else toast("Erro ao mover: "+e.message, true);
    await selecionarMissao(BOARD.id);
  }
}

// ── missão (modal) ──────────────────────────────────────────────────────
function abrirModalMissao(m){
  missaoEditando=m||null;
  document.getElementById("modal-missao-titulo").textContent=m?"Editar missão":"Nova missão";
  document.getElementById("mi-nome").value=m?m.nome:"";
  document.getElementById("mi-descricao").value=m?(m.descricao||""):"";
  document.getElementById("mi-accent").value=(m&&m.accent)||"#22d3ee";
  document.getElementById("modal-missao").style.display="flex";
}
function fecharModal(id){ document.getElementById(id).style.display="none"; }

async function salvarMissao(){
  const nome=document.getElementById("mi-nome").value.trim();
  if(!nome) return toast("Informe o nome da missão", true);
  const body={nome, descricao:document.getElementById("mi-descricao").value.trim(),
              accent:document.getElementById("mi-accent").value};
  try{
    if(missaoEditando){
      await api("/api/missoes/"+missaoEditando.id,{method:"PATCH",body:JSON.stringify(body)});
      toast("Missão atualizada");
      fecharModal("modal-missao");
      const r=await api("/api/missoes"); MISSOES=r.missoes||[];
      await selecionarMissao(missaoEditando.id);
    }else{
      const r=await api("/api/missoes",{method:"POST",body:JSON.stringify(body)});
      toast("Missão criada");
      fecharModal("modal-missao");
      const l=await api("/api/missoes"); MISSOES=l.missoes||[];
      await selecionarMissao(r.missao.id);
    }
  }catch(e){ toast("Erro: "+e.message, true); }
}

async function excluirMissao(){
  if(!BOARD) return;
  if(!confirm(`Excluir a missão "${BOARD.nome}" com todas as colunas e cartões?`)) return;
  try{
    await api("/api/missoes/"+BOARD.id,{method:"DELETE"});
    toast("Missão excluída");
    sessionStorage.removeItem("dt_missao");
    await loadAll();
  }catch(e){ toast("Erro: "+e.message, true); }
}

// ── colunas (modal) ─────────────────────────────────────────────────────
let colunaEditando=null;
function novaColuna(){ abrirModalColuna(null); }
function renomearColuna(id){ abrirModalColuna((BOARD.colunas||[]).find(c=>c.id===id)||null); }
function abrirModalColuna(c){
  colunaEditando=c||null;
  document.getElementById("modal-coluna-titulo").textContent=c?"Editar coluna":"Nova coluna";
  document.getElementById("co-nome").value=c?c.nome:"";
  document.getElementById("co-categoria").value=c?(c.categoria||""):"";
  document.getElementById("modal-coluna").style.display="flex";
  document.getElementById("co-nome").focus();
}
async function salvarColuna(){
  const nome=document.getElementById("co-nome").value.trim();
  if(!nome) return toast("Informe o nome da coluna", true);
  const body={nome, categoria:document.getElementById("co-categoria").value};
  try{
    if(colunaEditando)
      await api("/api/missoes/colunas/"+colunaEditando.id,{method:"PATCH",body:JSON.stringify(body)});
    else
      await api(`/api/missoes/${BOARD.id}/colunas`,{method:"POST",body:JSON.stringify(body)});
    fecharModal("modal-coluna");
    await selecionarMissao(BOARD.id);
  }catch(e){ toast("Erro: "+e.message, true); }
}
async function excluirColuna(id){
  const col=(BOARD.colunas||[]).find(c=>c.id===id);
  const n=(col&&col.cartoes)?col.cartoes.length:0;
  if(!confirm(`Excluir a coluna "${col?col.nome:""}"${n?` e seus ${n} cartão(ões)`:""}?`)) return;
  try{
    await api("/api/missoes/colunas/"+id,{method:"DELETE"});
    await selecionarMissao(BOARD.id);
  }catch(e){ toast("Erro: "+e.message, true); }
}

// ── cartões (modal) ─────────────────────────────────────────────────────
async function abrirModalCartao(cartaoId, colunaId){
  cartaoEditando=null; colunaDoNovoCartao=colunaId||null;
  const del=document.getElementById("ca-excluir");
  if(cartaoId){
    try{
      const r=await api("/api/missoes/cartoes/"+cartaoId);   // versão + descrição frescas
      cartaoEditando=r.cartao;
    }catch(e){ return toast("Erro ao abrir cartão: "+e.message, true); }
  }
  const c=cartaoEditando||{};
  document.getElementById("modal-cartao-titulo").textContent=cartaoId?"Editar cartão":"Novo cartão";
  document.getElementById("ca-titulo").value=c.titulo||"";
  document.getElementById("ca-descricao").value=c.descricao||"";
  document.getElementById("ca-prazo").value=c.prazo||"";
  document.getElementById("ca-prioridade").value=c.prioridade||"media";
  RESP_SEL=(c.responsaveis||"").split(",").map(s=>s.trim()).filter(Boolean);
  await carregarUsuarios(); renderRespChips();
  document.getElementById("ca-etiquetas").value=c.etiquetas||"";
  document.getElementById("ca-concluido").checked=!!c.concluido;
  document.getElementById("ca-ref-tipo").value=c.ref_tipo||"";
  del.style.display=cartaoId?"":"none";
  await carregarRefs(c.ref_id);
  document.getElementById("modal-cartao").style.display="flex";
  document.getElementById("ca-titulo").focus();
}

async function carregarRefs(selecionadoId){
  const tipo=document.getElementById("ca-ref-tipo").value;
  const sel=document.getElementById("ca-ref-id");
  if(!tipo){ sel.innerHTML='<option value="">—</option>'; sel.disabled=true; return; }
  sel.disabled=false; sel.innerHTML='<option value="">Carregando…</option>';
  try{
    const r=await api(`/api/missoes/refs?tipo=${tipo}`);
    const idSel=(typeof selecionadoId==="number")?selecionadoId:null;
    sel.innerHTML='<option value="">— escolha —</option>'+(r.itens||[]).map(i=>
      `<option value="${i.id}" ${i.id===idSel?"selected":""}>${esc(i.label)}</option>`).join("");
    // se o vínculo atual não veio no top-20, injeta a opção para não perdê-lo
    if(idSel && ![...sel.options].some(o=>parseInt(o.value)===idSel)){
      const c=cartaoEditando||{};
      sel.insertAdjacentHTML("beforeend", `<option value="${idSel}" selected>${esc(c.ref_label||("#"+idSel))}</option>`);
    }
  }catch(e){ sel.innerHTML='<option value="">erro ao buscar</option>'; }
}

async function salvarCartao(){
  const titulo=document.getElementById("ca-titulo").value.trim();
  if(!titulo) return toast("Informe o título", true);
  const refTipo=document.getElementById("ca-ref-tipo").value;
  const refId=document.getElementById("ca-ref-id").value;
  const body={
    titulo,
    descricao:document.getElementById("ca-descricao").value.trim(),
    prazo:document.getElementById("ca-prazo").value,
    prioridade:document.getElementById("ca-prioridade").value,
    responsaveis:RESP_SEL.join(", "),
    etiquetas:document.getElementById("ca-etiquetas").value.trim(),
    concluido:document.getElementById("ca-concluido").checked,
    ref_tipo:(refTipo&&refId)?refTipo:"", ref_id:(refTipo&&refId)?parseInt(refId):null,
  };
  try{
    if(cartaoEditando){
      body.versao=cartaoEditando.versao;   // lock otimista → 409 se outro editou
      await api("/api/missoes/cartoes/"+cartaoEditando.id,{method:"PATCH",body:JSON.stringify(body)});
      toast("Cartão salvo");
    }else{
      await api(`/api/missoes/colunas/${colunaDoNovoCartao}/cartoes`,{method:"POST",body:JSON.stringify(body)});
      toast("Cartão criado");
    }
    fecharModal("modal-cartao");
    await selecionarMissao(BOARD.id);
  }catch(e){
    if(e.conflito){ toast("⚠ Conflito: outro usuário editou este cartão — recarregado", true);
      fecharModal("modal-cartao"); await selecionarMissao(BOARD.id); }
    else toast("Erro: "+e.message, true);
  }
}

async function excluirCartao(){
  if(!cartaoEditando) return;
  if(!confirm(`Excluir o cartão "${cartaoEditando.titulo}"?`)) return;
  try{
    await api("/api/missoes/cartoes/"+cartaoEditando.id,{method:"DELETE"});
    toast("Cartão excluído");
    fecharModal("modal-cartao");
    await selecionarMissao(BOARD.id);
  }catch(e){ toast("Erro: "+e.message, true); }
}

// ── responsáveis (usuários da plataforma) ───────────────────────────────
async function carregarUsuarios(){
  if(USUARIOS) return;
  try{ USUARIOS=(await api("/api/missoes/usuarios")).usuarios||[]; }
  catch(e){ USUARIOS=[]; }
}
function renderRespChips(){
  const sel=document.getElementById("ca-resp-select");
  sel.innerHTML='<option value="">＋ adicionar responsável…</option>'+
    (USUARIOS||[]).filter(u=>!RESP_SEL.includes(u)).map(u=>`<option>${esc(u)}</option>`).join("");
  document.getElementById("ca-resp-chips").innerHTML=RESP_SEL.map(n=>
    `<span class="chip resp">👤 ${esc(n)} <b class="chip-x" data-nome="${esc(n)}">×</b></span>`).join("");
  document.querySelectorAll("#ca-resp-chips .chip-x").forEach(x=>{
    x.onclick=()=>{ RESP_SEL=RESP_SEL.filter(n=>n!==x.dataset.nome); renderRespChips(); };
  });
}
function addResponsavel(){
  const v=document.getElementById("ca-resp-select").value;
  if(v && !RESP_SEL.includes(v)){ RESP_SEL.push(v); renderRespChips(); }
}

// ── meus cartões (visão cross-missão) ───────────────────────────────────
async function abrirMeusCartoes(){
  try{
    const r=await api("/api/missoes/meus-cartoes");
    BOARD=null;
    document.getElementById("board").style.display="none";
    document.getElementById("board-vazio").style.display="none";
    document.getElementById("btn-editar-missao").style.display="none";
    document.getElementById("btn-excluir-missao").style.display="none";
    document.getElementById("breadcrumb-current").textContent="Meus cartões";
    renderSidebar();
    const el=document.getElementById("meus");
    el.style.display="block";
    const cartoes=r.cartoes||[];
    document.getElementById("meus-badge").textContent=cartoes.length||"";
    if(!cartoes.length){
      el.innerHTML=`<div class="board-vazio-inner" style="margin:60px auto;text-align:center">
        <div style="font-size:34px">🎉</div><h2>Nada atribuído a você</h2>
        <p>Cartões em que você é responsável aparecem aqui.</p></div>`;
      return;
    }
    // agrupa por missão
    const grupos={};
    cartoes.forEach(c=>{ (grupos[c.missao_id]=grupos[c.missao_id]||{nome:c.missao_nome,itens:[]}).itens.push(c); });
    el.innerHTML=Object.entries(grupos).map(([mid,g])=>`
      <div class="meus-grupo">
        <div class="meus-missao" data-mid="${mid}">🎯 ${esc(g.nome)}</div>
        ${g.itens.map(c=>`
          <div class="meus-item" data-mid="${c.missao_id}" data-cid="${c.id}">
            <span class="pri pri-${esc(c.prioridade||"media")}"></span>
            <span class="meus-titulo">${esc(c.titulo)}</span>
            <span class="chip">${esc(c.coluna_nome)}</span>
            ${c.prazo?`<span class="chip prazo ${(!c.concluido&&c.prazo<new Date().toISOString().slice(0,10))?"vencido":""}">📅 ${esc(c.prazo.split("-").reverse().join("/"))}</span>`:""}
          </div>`).join("")}
      </div>`).join("");
    el.querySelectorAll(".meus-missao").forEach(t=>{ t.onclick=()=>selecionarMissao(parseInt(t.dataset.mid)); });
    el.querySelectorAll(".meus-item").forEach(i=>{ i.onclick=async()=>{
      await selecionarMissao(parseInt(i.dataset.mid));
      abrirModalCartao(parseInt(i.dataset.cid), null); }; });
  }catch(e){ toast("Erro ao carregar meus cartões: "+e.message, true); }
}

// ── tempo real (best-effort; o estado real é sempre o servidor) ──────────
function conectarSocket(){
  if(typeof io==="undefined") return;
  try{
    const s=io({auth:{token:token()}, transports:["websocket","polling"]});
    const label=document.getElementById("sync-label");
    s.on("connect",()=>{ if(label) label.textContent="Conectado"; });
    s.on("disconnect",()=>{ if(label) label.textContent="Offline"; });
    const refresh=(ev)=>{
      const p=(ev&&ev.payload)||{};
      if(!BOARD) { loadAll(); return; }
      // evento da missão aberta → recarrega o board; de outra → só a sidebar
      if(p.missao_id===BOARD.id || (p.missao&&p.missao.id===BOARD.id) || p.missao_id===undefined){
        selecionarMissao(BOARD.id);
      }else{
        api("/api/missoes").then(r=>{ MISSOES=r.missoes||[]; renderSidebar(); }).catch(()=>{});
      }
    };
    ["MISSAO_CREATED","MISSAO_UPDATED","MISSAO_DELETED",
     "MISSAO_COLUNA_CREATED","MISSAO_COLUNA_UPDATED","MISSAO_COLUNA_DELETED",
     "MISSAO_COLUNA_REORDENADA","MISSAO_COLUNAS_REORDENADAS",
     "MISSAO_CARTAO_CREATED","MISSAO_CARTAO_UPDATED","MISSAO_CARTAO_DELETED",
     "MISSAO_CARTAO_MOVIDO"].forEach(ev=>s.on(ev, refresh));
  }catch(e){ /* tempo real é opcional */ }
}
