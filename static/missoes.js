/* Módulo Missões — board kanban nativo (SortableJS + lock otimista por versao) */
/* TOKEN_KEY, token(), esc(), doLogout() e o par de tema vêm de static/common.js. */
function userObj(){ try{ return JSON.parse(localStorage.getItem("doctrack_user")||"{}")||{}; }catch(e){ return {}; } }
const ROLE = (userObj().role)||"";
const MEU_NOME = (userObj().nome)||"";
const podeUsar = ["admin","gestor","tecnico"].includes(ROLE);
sessionStorage.setItem("dt_module", "missoes");

async function api(url, opts={}){
  function hdr(){ return {"Content-Type":"application/json", "Authorization":"Bearer "+token(), ...(opts.headers||{})}; }
  let res = await fetch(url, {...opts, headers:hdr()});
  if(res.status===401){
    if(window.DT_AUTH && await window.DT_AUTH.refresh()){ res = await fetch(url, {...opts, headers:hdr()}); }
    if(res.status===401){ (window.DT_AUTH?window.DT_AUTH.gotoLogin(true):window.location.href="/"); throw new Error("401"); }
  }
  if(res.status===409){ const b=await res.json().catch(()=>({}));
    const e=new Error(b.erro||"conflito"); e.conflito=true; e.body=b; throw e; }
  if(!res.ok){ const b=await res.json().catch(()=>({})); throw new Error(b.erro||("HTTP "+res.status)); }
  return res.json();
}
function toast(msg, erro=false){ const t=document.getElementById("toast");
  t.textContent=msg; t.style.display="block"; t.style.borderColor=erro?"#ef4444":"#22d3ee";
  clearTimeout(t._h); t._h=setTimeout(()=>t.style.display="none",3600); }
function brData(iso){ return iso ? iso.split("-").reverse().join("/") : ""; }

// ── estado ──────────────────────────────────────────────────────────────
let MISSOES=[], BOARD=null;        // BOARD = missão ativa completa (colunas+cartões)
let missaoEditando=null, cartaoEditando=null, colunaDoNovoCartao=null;
let sortables=[], USUARIOS=null, RESP_SEL=[];   // usuários da plataforma + responsáveis do modal
let MODELOS=[], VER_ARQUIVADAS=false, VISAO="board";   // board | meus | alertas
const FILTROS={busca:"", resp:"", etiqueta:"", prioridade:"", atrasados:false,
               meus:false, concluidos:true};

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
  document.getElementById("btn-arquivar-missao").onclick=alternarArquivoMissao;
  document.getElementById("btn-metricas").onclick=()=>abrirMetricas();
  document.getElementById("btn-export").onclick=exportarMissao;
  document.getElementById("btn-modelo").onclick=abrirModalModelo;
  document.getElementById("mo-salvar").onclick=salvarModelo;
  document.getElementById("me-janela").onchange=()=>abrirMetricas();
  document.getElementById("ca-salvar").onclick=salvarCartao;
  document.getElementById("ca-excluir").onclick=excluirCartao;
  document.getElementById("ca-ref-tipo").onchange=()=>carregarRefs();
  document.getElementById("ca-link").onclick=copiarLinkCartao;
  document.getElementById("ca-item-add").onclick=addItemChecklist;
  document.getElementById("ca-com-add").onclick=addComentario;
  document.getElementById("ca-hist-toggle").onclick=alternarHistorico;
  document.getElementById("co-salvar").onclick=salvarColuna;
  document.getElementById("btn-meus-cartoes").onclick=abrirMeusCartoes;
  document.getElementById("btn-alertas").onclick=abrirAlertas;
  document.getElementById("btn-arquivadas").onclick=alternarVerArquivadas;
  document.getElementById("ca-resp-select").onchange=addResponsavel;
  ligarFiltros();
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
    const r=await api("/api/missoes"+(VER_ARQUIVADAS?"?arquivadas=1":""));
    MISSOES=r.missoes||[];
    renderSidebar();
    // deep-link de entrada (?missao=<id>&cartao=<id>) tem prioridade sobre a
    // missão salva na sessão; a URL é limpa depois de consumida
    const params=new URLSearchParams(location.search);
    const deepMissao=parseInt(params.get("missao")||"0");
    const deepCartao=parseInt(params.get("cartao")||"0");
    if(deepMissao||deepCartao) history.replaceState(null,"",location.pathname);
    const salva=deepMissao||parseInt(sessionStorage.getItem("dt_missao")||"0");
    const alvo=MISSOES.find(m=>m.id===salva)||MISSOES[0];
    if(alvo){
      await selecionarMissao(alvo.id);
      if(deepCartao && BOARD && (BOARD.colunas||[]).some(col=>(col.cartoes||[]).some(c=>c.id===deepCartao)))
        abrirModalCartao(deepCartao, null);
    }
    else mostrarVazio();
    atualizarBadges();
  }catch(e){ toast("Erro ao carregar missões: "+e.message, true); }
}

// Badges da sidebar (best-effort, não bloqueiam o board)
function atualizarBadges(){
  api("/api/missoes/meus-cartoes").then(r=>{
    const b=document.getElementById("meus-badge");
    b.textContent=(r.total||0)||"";
    b.classList.toggle("alerta", (r.atrasados||0)>0);
    b.title=(r.atrasados||0)>0 ? `${r.atrasados} com prazo vencido` : "";
  }).catch(()=>{});
  api("/api/missoes/alertas").then(r=>{
    const b=document.getElementById("alertas-badge");
    b.textContent=(r.total||0)||"";
    b.classList.toggle("alerta", (r.criticos||0)>0);
    b.title=(r.criticos||0)>0 ? `${r.criticos} crítico(s)` : "";
  }).catch(()=>{});
}

function renderSidebar(){
  const box=document.getElementById("lista-missoes");
  if(!MISSOES.length){
    box.innerHTML=`<div class="nav-vazio">${VER_ARQUIVADAS?"Nenhuma missão arquivada.":"Nenhuma missão ainda."}</div>`;
    return;
  }
  box.innerHTML=MISSOES.map(m=>{
    // "40" numa missão 38/40 pronta fazia parecer intocada: o badge mostra o que
    // ainda dá trabalho, com o total só no title.
    const abertos=(m.n_abertos!==undefined)?m.n_abertos:(m.n_cartoes||0);
    return `
    <button type="button" class="nav-item ${BOARD&&BOARD.id===m.id?"active":""}" data-id="${m.id}"
            title="${abertos} aberto(s) de ${m.n_cartoes||0}">
      <span class="dot" style="background:${esc(m.accent||"#22d3ee")}"></span>
      <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left">${esc(m.nome)}</span>
      <span class="nav-badge ${abertos?"":"zerado"}">${abertos||"✓"}</span>
    </button>`; }).join("");
  box.querySelectorAll(".nav-item").forEach(b=>{
    b.onclick=()=>selecionarMissao(parseInt(b.dataset.id));
  });
}

function mostrarVazio(){
  BOARD=null; VISAO="board";
  document.getElementById("board").style.display="none";
  document.getElementById("meus").style.display="none";
  document.getElementById("painel-alertas").style.display="none";
  document.getElementById("filtros").style.display="none";
  document.getElementById("board-vazio").style.display="flex";
  document.getElementById("breadcrumb-current").textContent="—";
  document.getElementById("topbar-missao").style.display="none";
}

async function selecionarMissao(id){
  try{
    const r=await api("/api/missoes/"+id);
    BOARD=r.missao;
    VISAO="board";
    sessionStorage.setItem("dt_missao", String(id));
    renderSidebar();
    renderBoard();
  }catch(e){ toast("Erro ao abrir missão: "+e.message, true); }
}

// ── filtros do board ────────────────────────────────────────────────────
function ligarFiltros(){
  const busca=document.getElementById("f-busca");
  let deb=null;
  busca.oninput=()=>{ clearTimeout(deb); deb=setTimeout(()=>{ FILTROS.busca=busca.value.trim().toLowerCase(); renderBoard(); },180); };
  document.getElementById("f-resp").onchange=e=>{ FILTROS.resp=e.target.value; renderBoard(); };
  document.getElementById("f-etiqueta").onchange=e=>{ FILTROS.etiqueta=e.target.value; renderBoard(); };
  document.getElementById("f-prioridade").onchange=e=>{ FILTROS.prioridade=e.target.value; renderBoard(); };
  [["f-atrasados","atrasados"],["f-meus","meus"],["f-concluidos","concluidos"]].forEach(([id,chave])=>{
    document.getElementById(id).onclick=()=>{ FILTROS[chave]=!FILTROS[chave];
      document.getElementById(id).classList.toggle("on", FILTROS[chave]); renderBoard(); };
  });
  document.getElementById("f-limpar").onclick=()=>{
    Object.assign(FILTROS,{busca:"",resp:"",etiqueta:"",prioridade:"",atrasados:false,meus:false,concluidos:true});
    busca.value=""; ["f-resp","f-etiqueta","f-prioridade"].forEach(i=>document.getElementById(i).value="");
    ["f-atrasados","f-meus"].forEach(i=>document.getElementById(i).classList.remove("on"));
    document.getElementById("f-concluidos").classList.add("on");
    renderBoard();
  };
}

function filtroAtivo(){
  return !!(FILTROS.busca||FILTROS.resp||FILTROS.etiqueta||FILTROS.prioridade||
            FILTROS.atrasados||FILTROS.meus||!FILTROS.concluidos);
}

function passaFiltro(c){
  if(!FILTROS.concluidos && c.concluido) return false;
  if(FILTROS.atrasados && !c.atrasado) return false;
  if(FILTROS.prioridade && (c.prioridade||"media")!==FILTROS.prioridade) return false;
  const resp=(c.responsaveis||"").split(",").map(s=>s.trim()).filter(Boolean);
  if(FILTROS.meus && !resp.includes(MEU_NOME)) return false;
  if(FILTROS.resp && !resp.includes(FILTROS.resp)) return false;
  if(FILTROS.etiqueta){
    const tags=(c.etiquetas||"").split(",").map(s=>s.trim().toLowerCase());
    if(!tags.includes(FILTROS.etiqueta.toLowerCase())) return false;
  }
  if(FILTROS.busca){
    const alvo=[c.titulo,c.etiquetas,c.responsaveis,c.ref_label].join(" ").toLowerCase();
    if(!alvo.includes(FILTROS.busca)) return false;
  }
  return true;
}

// Alimenta os selects de responsável/etiqueta com o que existe no board aberto.
function popularFiltros(){
  const todos=(BOARD.colunas||[]).flatMap(c=>c.cartoes||[]);
  const resps=[...new Set(todos.flatMap(c=>(c.responsaveis||"").split(",").map(s=>s.trim()).filter(Boolean)))].sort();
  const tags=[...new Set(todos.flatMap(c=>(c.etiquetas||"").split(",").map(s=>s.trim()).filter(Boolean)))].sort();
  const selR=document.getElementById("f-resp"), selE=document.getElementById("f-etiqueta");
  selR.innerHTML='<option value="">Todos os responsáveis</option>'+
    resps.map(r=>`<option ${r===FILTROS.resp?"selected":""}>${esc(r)}</option>`).join("");
  selE.innerHTML='<option value="">Todas as etiquetas</option>'+
    tags.map(t=>`<option ${t===FILTROS.etiqueta?"selected":""}>${esc(t)}</option>`).join("");
}

// ── board ───────────────────────────────────────────────────────────────
function renderBoard(){
  if(!BOARD) return mostrarVazio();
  VISAO="board";
  document.getElementById("board-vazio").style.display="none";
  document.getElementById("meus").style.display="none";
  document.getElementById("painel-alertas").style.display="none";
  document.getElementById("filtros").style.display="flex";
  const el=document.getElementById("board");
  el.style.display="flex";
  document.getElementById("breadcrumb-current").textContent=BOARD.nome+(BOARD.arquivado?" (arquivada)":"");
  document.getElementById("topbar-missao").style.display="inline-flex";
  document.getElementById("btn-arquivar-missao").textContent=BOARD.arquivado?"↩":"🗂";
  document.getElementById("btn-arquivar-missao").title=BOARD.arquivado?"Desarquivar":"Arquivar (reversível)";
  document.documentElement.style.setProperty("--accent", BOARD.accent||"#22d3ee");
  popularFiltros();

  let visiveis=0, total=0;
  sortables.forEach(s=>{ try{ s.destroy(); }catch(e){} }); sortables=[];
  el.innerHTML=(BOARD.colunas||[]).map(c=>{
    const cartoes=(c.cartoes||[]);
    const mostrados=cartoes.filter(passaFiltro);
    visiveis+=mostrados.length; total+=cartoes.length;
    const abertos=cartoes.filter(x=>!x.concluido).length;
    const wip=c.limite_wip||0;
    const excedido=wip>0 && abertos>wip;
    return `
    <div class="coluna ${excedido?"wip-excedido":""}" data-id="${c.id}">
      <div class="coluna-head">
        <span class="coluna-cor" style="background:${esc(c.cor||BOARD.accent||"#22d3ee")}"></span>
        <span class="coluna-nome" title="Clique para renomear" data-id="${c.id}">${esc(c.nome)}</span>
        <span class="coluna-count ${excedido?"estourado":""}" title="${wip?`${abertos} aberto(s) · limite de WIP ${wip}`:`${abertos} aberto(s)`}">${
          wip ? `${abertos}/${wip}` : mostrados.length}</span>
        <button class="coluna-x" title="Excluir coluna (os cartões são movidos, não apagados)" data-id="${c.id}">×</button>
      </div>
      <div class="cartoes" data-coluna="${c.id}">
        ${mostrados.map(renderCartao).join("")}
        ${(!mostrados.length&&cartoes.length)?'<div class="coluna-filtrada">nenhum cartão passa no filtro</div>':""}
      </div>
      <button class="add-cartao" data-coluna="${c.id}">＋ Adicionar cartão</button>
    </div>`; }).join("")+
    `<button class="add-coluna" id="btn-add-coluna">＋ Coluna</button>`;

  document.getElementById("f-resumo").textContent =
    filtroAtivo() ? `${visiveis} de ${total} cartões` : `${total} cartões`;

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
        silenciarSocket();
        await api("/api/missoes/reordenar",{method:"POST",body:JSON.stringify({missao_id:BOARD.id, colunas_ids:ids})});
        BOARD.colunas.sort((a,b)=>ids.indexOf(a.id)-ids.indexOf(b.id));
        renderBoard();
      }catch(e){ toast("Erro ao mover coluna: "+e.message, true); await selecionarMissao(BOARD.id); }
    },
  }));
}

function renderCartao(c){
  const chips=[];
  (c.etiquetas||"").split(",").map(s=>s.trim()).filter(Boolean).slice(0,2)
    .forEach(e=>chips.push(`<span class="chip etiqueta">${esc(e)}</span>`));
  if(c.prazo)
    chips.push(`<span class="chip prazo ${c.atrasado?"vencido":""}">📅 ${esc(brData(c.prazo))}</span>`);
  if(c.n_itens)
    chips.push(`<span class="chip check ${c.n_itens_feitos===c.n_itens?"ok":""}">☑ ${c.n_itens_feitos}/${c.n_itens}</span>`);
  if(c.n_comentarios) chips.push(`<span class="chip">💬 ${c.n_comentarios}</span>`);
  if(c.recorrencia) chips.push(`<span class="chip recorrente" title="Repete: ${esc(c.recorrencia)}">🔁</span>`);
  // Aging: o cartão esquecido não tinha nenhum sinal visual no board.
  if(!c.concluido && c.dias_parado>=7)
    chips.push(`<span class="chip parado" title="Sem movimentação nesta coluna">⏳ ${c.dias_parado}d</span>`);
  const resp=(c.responsaveis||"").split(",").map(s=>s.trim()).filter(Boolean);
  if(resp.length) chips.push(`<span class="chip resp">👤 ${esc(resp[0])}${resp.length>1?" +"+(resp.length-1):""}</span>`);
  if(c.ref_label){
    // chip clicável: navega para a entidade vinculada (equipamento/documento abrem a ficha via deep-link)
    const url=c.ref_tipo==="equipamento" ? "/equipamentos?ficha="+c.ref_id
             : c.ref_tipo==="projeto" ? "/projetos" : "/?doc="+c.ref_id;
    // documento: chip "vivo" — dot colorido + status atual (fonte: o próprio doc)
    let vivo="";
    if(c.ref_tipo==="documento" && c.ref_status){
      const cor=c.ref_status_global==="Finalizado" ? "var(--green)"
              : c.ref_status_global==="Pendente" ? "var(--red)" : "var(--amber)";
      vivo=` · <span class="ref-dot" style="background:${cor}"></span>${esc(c.ref_status)}`;
    }
    // Vínculo desativado costumava simplesmente sumir do cartão, sem aviso.
    const morto=c.ref_ativo===false;
    chips.push(`<a class="chip ref ${morto?"morto":""}" href="${url}" onclick="event.stopPropagation()"
      title="${morto?"Este "+esc(c.ref_tipo)+" foi desativado":"Abrir "+esc(c.ref_tipo)}">${morto?"⚠":"🔗"} ${esc(c.ref_label)}${vivo}</a>`);
  }
  return `<div class="cartao ${c.concluido?"concluido":""} ${(!c.concluido&&c.atrasado)?"atrasado":""}" data-id="${c.id}" data-versao="${c.versao}">
    <div style="display:flex;gap:8px;align-items:flex-start">
      <span class="pri pri-${esc(c.prioridade||"media")}" style="margin-top:5px" title="Prioridade ${esc(c.prioridade)}"></span>
      <div class="cartao-titulo" style="flex:1">${esc(c.titulo)}</div>
    </div>
    ${chips.length?`<div class="cartao-meta">${chips.join("")}</div>`:""}
  </div>`;
}

// O board recarregava inteiro do servidor a cada arrasto — e de novo pelo eco do
// socket: dois refetches por drag. Agora o estado local é reconciliado com o que
// o DOM já mostra e com o cartão que o servidor devolveu.
async function onDragEnd(ev){
  window._dragTs=Date.now();
  const cartaoId=parseInt(ev.item.dataset.id);
  const versao=parseInt(ev.item.dataset.versao||"0");
  const destinoId=parseInt(ev.to.dataset.coluna);
  const origemId=parseInt(ev.from.dataset.coluna);
  const ids=[...ev.to.querySelectorAll(".cartao")].map(c=>parseInt(c.dataset.id));
  const idsOrigem=[...ev.from.querySelectorAll(".cartao")].map(c=>parseInt(c.dataset.id));
  try{
    silenciarSocket();
    if(destinoId!==origemId){
      const r=await api("/api/missoes/reordenar",{method:"POST",body:JSON.stringify({
        cartao_id:cartaoId, versao, coluna_destino_id:destinoId, ids, ids_origem:idsOrigem})});
      const col=(BOARD.colunas||[]).find(c=>c.id===origemId);
      if(col) col.cartoes=(col.cartoes||[]).filter(x=>x.id!==cartaoId)
        .sort((a,b)=>idsOrigem.indexOf(a.id)-idsOrigem.indexOf(b.id));
      const dst=(BOARD.colunas||[]).find(c=>c.id===destinoId);
      if(dst){ dst.cartoes=(dst.cartoes||[]).filter(x=>x.id!==cartaoId);
        dst.cartoes.push(r.cartao); dst.cartoes.sort((a,b)=>ids.indexOf(a.id)-ids.indexOf(b.id)); }
      renderBoard();
      atualizarBadges();
    }else{
      await api("/api/missoes/reordenar",{method:"POST",body:JSON.stringify({coluna_id:destinoId, ids})});
      const col=(BOARD.colunas||[]).find(c=>c.id===destinoId);
      if(col) col.cartoes.sort((a,b)=>ids.indexOf(a.id)-ids.indexOf(b.id));
      renderBoard();
    }
  }catch(e){
    if(e.conflito) toast("⚠ Outro usuário moveu esse cartão — recarregando", true);
    else toast("Erro ao mover: "+e.message, true);
    await selecionarMissao(BOARD.id);
  }
}

// ── missão (modal) ──────────────────────────────────────────────────────
async function abrirModalMissao(m){
  missaoEditando=m||null;
  document.getElementById("modal-missao-titulo").textContent=m?"Editar missão":"Nova missão";
  document.getElementById("mi-nome").value=m?m.nome:"";
  document.getElementById("mi-descricao").value=m?(m.descricao||""):"";
  document.getElementById("mi-accent").value=(m&&m.accent)||"#22d3ee";
  // O modelo só faz sentido ao criar (a missão já tem colunas)
  document.getElementById("mi-modelo-wrap").style.display=m?"none":"";
  if(!m) await carregarModelos();
  document.getElementById("modal-missao").style.display="flex";
  document.getElementById("mi-nome").focus();
}
function fecharModal(id){ document.getElementById(id).style.display="none"; }

async function carregarModelos(){
  try{
    MODELOS=(await api("/api/missoes/modelos")).modelos||[];
  }catch(e){ MODELOS=[]; }
  document.getElementById("mi-modelo").innerHTML=
    '<option value="">— colunas padrão (A fazer / Fazendo / Concluído) —</option>'+
    MODELOS.map(m=>`<option value="${m.id}">${esc(m.nome)} · ${m.n_colunas} coluna(s), ${m.n_cartoes} cartão(ões)</option>`).join("");
}

async function salvarMissao(){
  const nome=document.getElementById("mi-nome").value.trim();
  if(!nome) return toast("Informe o nome da missão", true);
  const body={nome, descricao:document.getElementById("mi-descricao").value.trim(),
              accent:document.getElementById("mi-accent").value};
  const modelo=document.getElementById("mi-modelo").value;
  if(!missaoEditando && modelo) body.modelo_id=parseInt(modelo);
  try{
    silenciarSocket();
    if(missaoEditando){
      await api("/api/missoes/"+missaoEditando.id,{method:"PATCH",body:JSON.stringify(body)});
      toast("Missão atualizada");
      fecharModal("modal-missao");
      const r=await api("/api/missoes"+(VER_ARQUIVADAS?"?arquivadas=1":"")); MISSOES=r.missoes||[];
      await selecionarMissao(missaoEditando.id);
    }else{
      const r=await api("/api/missoes",{method:"POST",body:JSON.stringify(body)});
      toast("Missão criada");
      fecharModal("modal-missao");
      const l=await api("/api/missoes"+(VER_ARQUIVADAS?"?arquivadas=1":"")); MISSOES=l.missoes||[];
      await selecionarMissao(r.missao.id);
    }
  }catch(e){ toast("Erro: "+e.message, true); }
}

async function alternarArquivoMissao(){
  if(!BOARD) return;
  const arquivar=!BOARD.arquivado;
  if(arquivar && !confirm(`Arquivar a missão "${BOARD.nome}"? Ela sai da lista mas nada é apagado — dá para desarquivar depois.`)) return;
  try{
    silenciarSocket();
    await api("/api/missoes/"+BOARD.id,{method:"PATCH",body:JSON.stringify({arquivado:arquivar})});
    toast(arquivar?"Missão arquivada":"Missão desarquivada");
    sessionStorage.removeItem("dt_missao");
    await loadAll();
  }catch(e){ toast("Erro: "+e.message, true); }
}

async function excluirMissao(){
  if(!BOARD) return;
  if(ROLE!=="admin")
    return toast("Exclusão definitiva é do administrador — use 🗂 para arquivar", true);
  const nome=prompt(`Isto APAGA a missão "${BOARD.nome}", todos os cartões e todo o histórico dela.\n`+
                    `Não há como desfazer (para só tirar da lista, use 🗂 Arquivar).\n\n`+
                    `Digite o nome da missão para confirmar:`);
  if(nome===null) return;
  if(nome.trim()!==BOARD.nome) return toast("Nome não confere — nada foi excluído", true);
  try{
    silenciarSocket();
    await api("/api/missoes/"+BOARD.id+"?definitivo=1",{method:"DELETE"});
    toast("Missão excluída definitivamente");
    sessionStorage.removeItem("dt_missao");
    await loadAll();
  }catch(e){ toast("Erro: "+e.message, true); }
}

async function alternarVerArquivadas(){
  VER_ARQUIVADAS=!VER_ARQUIVADAS;
  document.getElementById("lbl-arquivadas").textContent=VER_ARQUIVADAS?"Ver ativas":"Ver arquivadas";
  document.getElementById("btn-arquivadas").classList.toggle("active", VER_ARQUIVADAS);
  sessionStorage.removeItem("dt_missao");
  BOARD=null;
  await loadAll();
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
  document.getElementById("co-wip").value=c?(c.limite_wip||0):0;
  document.getElementById("co-cor").value=(c&&c.cor)||BOARD.accent||"#22d3ee";
  document.getElementById("modal-coluna").style.display="flex";
  document.getElementById("co-nome").focus();
}
async function salvarColuna(){
  const nome=document.getElementById("co-nome").value.trim();
  if(!nome) return toast("Informe o nome da coluna", true);
  const body={nome, categoria:document.getElementById("co-categoria").value,
              limite_wip:parseInt(document.getElementById("co-wip").value||"0"),
              cor:document.getElementById("co-cor").value};
  try{
    silenciarSocket();
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
  const outras=(BOARD.colunas||[]).filter(c=>c.id!==id);
  if(n && !outras.length)
    return toast("É a única coluna da missão — mova ou exclua os cartões antes", true);
  // Os cartões migram em vez de serem destruídos junto com a coluna.
  let destino=null;
  if(n){
    const opcoes=outras.map((c,i)=>`${i+1}) ${c.nome}`).join("\n");
    const escolha=prompt(`A coluna "${col?col.nome:""}" tem ${n} cartão(ões).\n`+
      `Eles serão MOVIDOS (não apagados). Para qual coluna?\n\n${opcoes}\n\n`+
      `Digite o número (vazio = a coluna anterior):`);
    if(escolha===null) return;
    const idx=parseInt(escolha||"0");
    if(idx>=1 && idx<=outras.length) destino=outras[idx-1].id;
  }else if(!confirm(`Excluir a coluna "${col?col.nome:""}"?`)) return;
  try{
    silenciarSocket();
    const r=await api("/api/missoes/colunas/"+id+(destino?`?destino_id=${destino}`:""),{method:"DELETE"});
    if(r.cartoes_movidos) toast(`Coluna excluída · ${r.cartoes_movidos} cartão(ões) movido(s)`);
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
  document.getElementById("ca-inicio").value=c.data_inicio||"";
  document.getElementById("ca-prazo").value=c.prazo||"";
  document.getElementById("ca-prioridade").value=c.prioridade||"media";
  document.getElementById("ca-peso").value=(c.peso!==undefined&&c.peso!==null)?c.peso:1;
  document.getElementById("ca-recorrencia").value=c.recorrencia||"";
  RESP_SEL=(c.responsaveis||"").split(",").map(s=>s.trim()).filter(Boolean);
  await carregarUsuarios(); renderRespChips();
  carregarEtiquetas();
  document.getElementById("ca-etiquetas").value=c.etiquetas||"";
  document.getElementById("ca-concluido").checked=!!c.concluido;
  document.getElementById("ca-ref-tipo").value=c.ref_tipo||"";
  // "Mover para" — no celular arrastar entre colunas de 84vw é sofrível
  const colAtual=c.coluna_id||colunaDoNovoCartao;
  document.getElementById("ca-coluna").innerHTML=(BOARD.colunas||[]).map(col=>
    `<option value="${col.id}" ${col.id===colAtual?"selected":""}>${esc(col.nome)}</option>`).join("");
  del.style.display=cartaoId?"":"none";
  document.getElementById("ca-link").style.display=cartaoId?"":"none";
  document.getElementById("ca-extra").style.display=cartaoId?"":"none";
  if(cartaoId){ renderChecklist(); renderComentarios();
    document.getElementById("ca-historico").style.display="none";
    document.getElementById("ca-hist-toggle").textContent="▸ Histórico do cartão"; }
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
    data_inicio:document.getElementById("ca-inicio").value,
    prazo:document.getElementById("ca-prazo").value,
    prioridade:document.getElementById("ca-prioridade").value,
    peso:parseFloat(document.getElementById("ca-peso").value||"1"),
    recorrencia:document.getElementById("ca-recorrencia").value,
    responsaveis:RESP_SEL.join(", "),
    etiquetas:document.getElementById("ca-etiquetas").value.trim(),
    concluido:document.getElementById("ca-concluido").checked,
    ref_tipo:(refTipo&&refId)?refTipo:"", ref_id:(refTipo&&refId)?parseInt(refId):null,
  };
  const colunaEscolhida=parseInt(document.getElementById("ca-coluna").value||"0");
  try{
    silenciarSocket();
    if(cartaoEditando){
      body.versao=cartaoEditando.versao;   // lock otimista → 409 se outro editou
      const r=await api("/api/missoes/cartoes/"+cartaoEditando.id,{method:"PATCH",body:JSON.stringify(body)});
      if(colunaEscolhida && colunaEscolhida!==cartaoEditando.coluna_id)
        await moverCartaoPara(cartaoEditando.id, r.cartao.versao, colunaEscolhida);
      toast(r.recorrencia
        ? `Cartão salvo · próxima ocorrência agendada para ${brData(r.recorrencia.prazo)}`
        : "Cartão salvo");
    }else{
      await api(`/api/missoes/colunas/${colunaEscolhida||colunaDoNovoCartao}/cartoes`,{method:"POST",body:JSON.stringify(body)});
      toast("Cartão criado");
    }
    fecharModal("modal-cartao");
    await selecionarMissao(BOARD.id);
    atualizarBadges();
  }catch(e){
    if(e.conflito){ toast("⚠ Conflito: outro usuário editou este cartão — recarregado", true);
      fecharModal("modal-cartao"); await selecionarMissao(BOARD.id); }
    else toast("Erro: "+e.message, true);
  }
}

async function moverCartaoPara(cartaoId, versao, destinoId){
  const dst=(BOARD.colunas||[]).find(c=>c.id===destinoId);
  const ids=[...((dst&&dst.cartoes)||[]).map(c=>c.id).filter(i=>i!==cartaoId), cartaoId];
  await api("/api/missoes/reordenar",{method:"POST",body:JSON.stringify({
    cartao_id:cartaoId, versao, coluna_destino_id:destinoId, ids})});
}

async function excluirCartao(){
  if(!cartaoEditando) return;
  if(!confirm(`Excluir o cartão "${cartaoEditando.titulo}"? O histórico dele vai junto.`)) return;
  try{
    silenciarSocket();
    await api("/api/missoes/cartoes/"+cartaoEditando.id,{method:"DELETE"});
    toast("Cartão excluído");
    fecharModal("modal-cartao");
    await selecionarMissao(BOARD.id);
    atualizarBadges();
  }catch(e){ toast("Erro: "+e.message, true); }
}

function copiarLinkCartao(){
  if(!cartaoEditando) return;
  const url=`${location.origin}/missoes?missao=${cartaoEditando.missao_id}&cartao=${cartaoEditando.id}`;
  (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject())
    .then(()=>toast("Link copiado"))
    .catch(()=>prompt("Copie o link do cartão:", url));
}

// ── checklist ───────────────────────────────────────────────────────────
function renderChecklist(){
  const itens=(cartaoEditando&&cartaoEditando.itens)||[];
  const feitos=itens.filter(i=>i.feito).length;
  document.getElementById("ca-itens-resumo").textContent=itens.length?`${feitos}/${itens.length}`:"";
  const box=document.getElementById("ca-itens");
  box.innerHTML=itens.length ? itens.map(i=>`
    <div class="ca-item ${i.feito?"feito":""}">
      <input type="checkbox" data-id="${i.id}" ${i.feito?"checked":""}>
      <span>${esc(i.texto)}</span>
      <button type="button" class="ca-item-x" data-id="${i.id}" title="Remover">×</button>
    </div>`).join("") : '<div class="ca-vazio">Nenhum item ainda.</div>';
  box.querySelectorAll('input[type=checkbox]').forEach(cb=>{
    cb.onchange=()=>patchItem(parseInt(cb.dataset.id), {feito:cb.checked});
  });
  box.querySelectorAll(".ca-item-x").forEach(b=>{
    b.onclick=()=>patchItem(parseInt(b.dataset.id), null);
  });
}
async function patchItem(id, body){
  try{
    silenciarSocket();
    if(body===null) await api("/api/missoes/itens/"+id,{method:"DELETE"});
    else await api("/api/missoes/itens/"+id,{method:"PATCH",body:JSON.stringify(body)});
    const r=await api("/api/missoes/cartoes/"+cartaoEditando.id);
    cartaoEditando=r.cartao; renderChecklist();
  }catch(e){ toast("Erro: "+e.message, true); }
}
async function addItemChecklist(){
  const inp=document.getElementById("ca-item-novo");
  const texto=inp.value.trim();
  if(!texto || !cartaoEditando) return;
  try{
    silenciarSocket();
    await api(`/api/missoes/cartoes/${cartaoEditando.id}/itens`,{method:"POST",body:JSON.stringify({texto})});
    inp.value="";
    const r=await api("/api/missoes/cartoes/"+cartaoEditando.id);
    cartaoEditando=r.cartao; renderChecklist(); inp.focus();
  }catch(e){ toast("Erro: "+e.message, true); }
}

// ── comentários ─────────────────────────────────────────────────────────
function renderComentarios(){
  const cs=(cartaoEditando&&cartaoEditando.comentarios)||[];
  document.getElementById("ca-com-resumo").textContent=cs.length||"";
  const box=document.getElementById("ca-comentarios");
  box.innerHTML=cs.length ? cs.slice().reverse().map(c=>`
    <div class="ca-com">
      <div class="ca-com-head"><b>${esc(c.por)}</b><span>${esc(c.em)}</span>
        <button type="button" class="ca-item-x" data-id="${c.id}" title="Apagar">×</button></div>
      <div class="ca-com-texto">${esc(c.texto)}</div>
    </div>`).join("") : '<div class="ca-vazio">Sem comentários. É aqui que fica registrado por que o cartão travou.</div>';
  box.querySelectorAll(".ca-item-x").forEach(b=>{
    b.onclick=async()=>{
      if(!confirm("Apagar este comentário?")) return;
      try{ silenciarSocket();
        await api("/api/missoes/comentarios/"+b.dataset.id,{method:"DELETE"});
        const r=await api("/api/missoes/cartoes/"+cartaoEditando.id);
        cartaoEditando=r.cartao; renderComentarios();
      }catch(e){ toast("Erro: "+e.message, true); }
    };
  });
}
async function addComentario(){
  const ta=document.getElementById("ca-com-novo");
  const texto=ta.value.trim();
  if(!texto || !cartaoEditando) return;
  try{
    silenciarSocket();
    await api(`/api/missoes/cartoes/${cartaoEditando.id}/comentarios`,{method:"POST",body:JSON.stringify({texto})});
    ta.value="";
    const r=await api("/api/missoes/cartoes/"+cartaoEditando.id);
    cartaoEditando=r.cartao; renderComentarios();
  }catch(e){ toast("Erro: "+e.message, true); }
}

// ── histórico do cartão ─────────────────────────────────────────────────
const ROTULO_EVENTO={criado:"criado", movido:"movido", concluido:"concluído",
                     reaberto:"reaberto", campo:"alterado"};
async function alternarHistorico(){
  const box=document.getElementById("ca-historico");
  const btn=document.getElementById("ca-hist-toggle");
  if(box.style.display!=="none"){ box.style.display="none"; btn.textContent="▸ Histórico do cartão"; return; }
  box.style.display="block"; btn.textContent="▾ Histórico do cartão";
  box.innerHTML='<div class="ca-vazio">Carregando…</div>';
  try{
    const r=await api(`/api/missoes/cartoes/${cartaoEditando.id}/historico`);
    const hs=r.historico||[];
    box.innerHTML=hs.length ? hs.map(h=>{
      let detalhe="";
      if(h.evento==="movido") detalhe=`${esc(h.coluna_origem||"—")} → <b>${esc(h.coluna_destino||"—")}</b>`;
      else if(h.evento==="campo") detalhe=`<b>${esc(h.campo)}</b>: ${esc(h.valor_antigo||"vazio")} → ${esc(h.valor_novo||"vazio")}`;
      else detalhe=esc(h.valor_novo||"");
      const marca=h.origem&&h.origem!=="manual" ? `<span class="ca-hist-origem">${esc(h.origem)}</span>` : "";
      return `<div class="ca-hist-linha"><span class="ca-hist-quando">${esc(h.em)}</span>
        <span class="ca-hist-ev ev-${esc(h.evento)}">${esc(ROTULO_EVENTO[h.evento]||h.evento)}</span>
        <span class="ca-hist-det">${detalhe}</span>${marca}
        <span class="ca-hist-por">${esc(h.por)}</span></div>`;
    }).join("") : '<div class="ca-vazio">Sem registros.</div>';
  }catch(e){ box.innerHTML=`<div class="ca-vazio">Erro: ${esc(e.message)}</div>`; }
}

// ── responsáveis e etiquetas (vocabulário) ──────────────────────────────
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
// Sugere o que já existe: campo livre fazia "urgência"/"urgencia"/"Urgente"
// virarem três etiquetas diferentes e nenhum filtro fechar.
let ETIQUETAS=null;
function carregarEtiquetas(){
  if(ETIQUETAS){ pintarEtiquetas(); return; }
  api("/api/missoes/etiquetas").then(r=>{ ETIQUETAS=r.etiquetas||[]; pintarEtiquetas(); }).catch(()=>{ETIQUETAS=[];});
}
function pintarEtiquetas(){
  document.getElementById("lista-etiquetas").innerHTML=
    (ETIQUETAS||[]).map(e=>`<option value="${esc(e.nome)}">${e.n} cartão(ões)</option>`).join("");
}

// ── meus cartões (visão cross-missão) ───────────────────────────────────
function prepararPainel(titulo){
  BOARD=null;
  document.getElementById("board").style.display="none";
  document.getElementById("board-vazio").style.display="none";
  document.getElementById("filtros").style.display="none";
  document.getElementById("topbar-missao").style.display="none";
  document.getElementById("breadcrumb-current").textContent=titulo;
  renderSidebar();
}

async function abrirMeusCartoes(){
  try{
    const r=await api("/api/missoes/meus-cartoes");
    VISAO="meus";
    prepararPainel("Meus cartões");
    document.getElementById("painel-alertas").style.display="none";
    const el=document.getElementById("meus");
    el.style.display="block";
    const cartoes=r.cartoes||[];
    if(!cartoes.length){
      el.innerHTML=`<div class="board-vazio-inner" style="margin:60px auto;text-align:center">
        <div style="font-size:34px">🎉</div><h2>Nada atribuído a você</h2>
        <p>Cartões em que você é responsável aparecem aqui.</p></div>`;
      return;
    }
    const grupos={};
    cartoes.forEach(c=>{ (grupos[c.missao_id]=grupos[c.missao_id]||{nome:c.missao_nome,itens:[]}).itens.push(c); });
    el.innerHTML=`<div class="painel-topo">${cartoes.length} cartão(ões) abertos · ${r.atrasados||0} com prazo vencido</div>`+
      Object.entries(grupos).map(([mid,g])=>`
      <div class="meus-grupo">
        <div class="meus-missao" data-mid="${mid}">🎯 ${esc(g.nome)}</div>
        ${g.itens.map(c=>`
          <div class="meus-item ${c.atrasado?"atrasado":""}" data-mid="${c.missao_id}" data-cid="${c.id}">
            <span class="pri pri-${esc(c.prioridade||"media")}"></span>
            <span class="meus-titulo">${esc(c.titulo)}</span>
            ${c.n_itens?`<span class="chip check">☑ ${c.n_itens_feitos}/${c.n_itens}</span>`:""}
            <span class="chip">${esc(c.coluna_nome)}</span>
            ${c.prazo?`<span class="chip prazo ${c.atrasado?"vencido":""}">📅 ${esc(brData(c.prazo))}</span>`:""}
          </div>`).join("")}
      </div>`).join("");
    el.querySelectorAll(".meus-missao").forEach(t=>{ t.onclick=()=>selecionarMissao(parseInt(t.dataset.mid)); });
    el.querySelectorAll(".meus-item").forEach(i=>{ i.onclick=async()=>{
      await selecionarMissao(parseInt(i.dataset.mid));
      abrirModalCartao(parseInt(i.dataset.cid), null); }; });
  }catch(e){ toast("Erro ao carregar meus cartões: "+e.message, true); }
}

// ── alertas (o que precisa de atenção hoje) ─────────────────────────────
async function abrirAlertas(){
  try{
    const r=await api("/api/missoes/alertas");
    VISAO="alertas";
    prepararPainel("Alertas");
    document.getElementById("meus").style.display="none";
    const el=document.getElementById("painel-alertas");
    el.style.display="block";
    const itens=r.alertas||[];
    if(!itens.length){
      el.innerHTML=`<div class="board-vazio-inner" style="margin:60px auto;text-align:center">
        <div style="font-size:34px">✅</div><h2>Nada pedindo atenção</h2>
        <p>Sem prazos vencidos, cartões parados ou vínculos quebrados.</p></div>`;
      return;
    }
    el.innerHTML=`<div class="painel-topo">${itens.length} alerta(s) · ${r.criticos||0} crítico(s)</div>`+
      itens.map(a=>`
        <div class="alerta-item sev-${esc(a.severidade)}" ${a.cartao_id?`data-mid="${a.missao_id}" data-cid="${a.cartao_id}"`:`data-mid="${a.missao_id}"`}>
          <span class="alerta-sev">${a.severidade==="critico"?"🔴":"🟡"}</span>
          <div class="alerta-corpo">
            <div class="alerta-titulo">${esc(a.titulo)}${a.cartao?` — ${esc(a.cartao)}`:""}</div>
            <div class="alerta-detalhe">${esc(a.detalhe)}</div>
          </div>
          <div class="alerta-ctx">${esc(a.missao)}${a.coluna?` · ${esc(a.coluna)}`:""}</div>
        </div>`).join("");
    el.querySelectorAll(".alerta-item").forEach(i=>{ i.onclick=async()=>{
      await selecionarMissao(parseInt(i.dataset.mid));
      if(i.dataset.cid) abrirModalCartao(parseInt(i.dataset.cid), null); }; });
  }catch(e){ toast("Erro ao carregar alertas: "+e.message, true); }
}

// ── métricas ────────────────────────────────────────────────────────────
function tile(rotulo, valor, extra=""){
  return `<div class="me-tile"><div class="me-valor">${valor}</div>
    <div class="me-rotulo">${esc(rotulo)}</div>${extra?`<div class="me-extra">${extra}</div>`:""}</div>`;
}
async function abrirMetricas(){
  if(!BOARD) return;
  const dias=document.getElementById("me-janela").value||"30";
  document.getElementById("modal-metricas-titulo").textContent="Métricas · "+BOARD.nome;
  document.getElementById("modal-metricas").style.display="flex";
  const corpo=document.getElementById("me-corpo");
  corpo.innerHTML='<div class="ca-vazio">Calculando…</div>';
  try{
    const m=await api(`/api/missoes/${BOARD.id}/metricas?dias=${dias}`);
    const t=m.totais, ct=m.cycle_time;
    const maxCol=Math.max(1, ...m.por_coluna.map(c=>c.total));
    const maxSem=Math.max(1, ...m.throughput.por_semana.map(s=>s.n));
    const maxResp=Math.max(1, ...m.por_responsavel.map(r=>r.abertos));
    corpo.innerHTML=`
      <div class="me-grid">
        ${tile("abertos", t.abertos, `de ${t.total} cartões`)}
        ${tile("atrasados", t.atrasados, t.atrasados?"prazo vencido":"em dia")}
        ${tile("em progresso (WIP)", t.wip, "colunas 'em andamento'")}
        ${tile("avanço ponderado", m.avanco.ponderado+"%", `por cartão: ${m.avanco.por_cartao}%`)}
        ${tile("concluídos", m.throughput.concluidos, `nos últimos ${m.janela_dias} dias`)}
        ${tile("cycle time p85", ct.p85!==null?ct.p85+"d":"—",
               ct.amostra?`média ${ct.media}d · p50 ${ct.p50}d · ${ct.amostra} amostra(s)`:"sem conclusões na janela")}
      </div>
      ${(t.sem_responsavel||t.sem_prazo)?`<div class="me-nota">⚠ ${t.sem_responsavel} cartão(ões) sem responsável · ${t.sem_prazo} sem prazo</div>`:""}

      <div class="me-sec">Fluxo por coluna <i>(quanto tempo o cartão fica parado em cada etapa — é aqui que aparece o gargalo)</i></div>
      <table class="me-tab"><thead><tr><th>Coluna</th><th>Cartões</th><th>Abertos</th><th>WIP</th><th>Dias médios</th></tr></thead><tbody>
        ${m.por_coluna.map(c=>`<tr class="${c.excedido?"estourado":""}">
          <td>${esc(c.nome)}${c.categoria?` <span class="me-tag">${esc(c.categoria)}</span>`:""}</td>
          <td><span class="me-bar" style="width:${Math.round(100*c.total/maxCol)}%"></span>${c.total}</td>
          <td>${c.abertos}</td>
          <td>${c.limite_wip?`${c.abertos}/${c.limite_wip}${c.excedido?" ⚠":""}`:"—"}</td>
          <td>${c.dias_medios}d ${c.amostras?`<i class="me-amostra">(${c.amostras})</i>`:""}</td></tr>`).join("")}
      </tbody></table>

      <div class="me-sec">Throughput por semana</div>
      ${m.throughput.por_semana.length ? `<div class="me-spark">${m.throughput.por_semana.map(s=>
        `<div class="me-spark-col" title="${esc(s.semana)}: ${s.n} concluído(s)">
           <div class="me-spark-bar" style="height:${Math.round(100*s.n/maxSem)}%"></div>
           <span>${esc(s.semana.split("-S")[1]||"")}</span></div>`).join("")}</div>`
        : '<div class="ca-vazio">Nenhum cartão concluído na janela.</div>'}

      <div class="me-sec">Carga por responsável</div>
      ${m.por_responsavel.length ? `<table class="me-tab"><thead><tr><th>Responsável</th><th>Abertos</th><th>Atrasados</th><th>Peso</th></tr></thead><tbody>
        ${m.por_responsavel.map(r=>`<tr>
          <td>${esc(r.nome)}</td>
          <td><span class="me-bar" style="width:${Math.round(100*r.abertos/maxResp)}%"></span>${r.abertos}</td>
          <td class="${r.atrasados?"vermelho":""}">${r.atrasados||"—"}</td>
          <td>${r.peso}</td></tr>`).join("")}
      </tbody></table>` : '<div class="ca-vazio">Nenhum cartão aberto.</div>'}

      <div class="me-sec">Cartões parados há mais tempo</div>
      ${m.aging.length ? `<table class="me-tab"><thead><tr><th>Cartão</th><th>Coluna</th><th>Responsáveis</th><th>Parado</th></tr></thead><tbody>
        ${m.aging.map(a=>`<tr class="me-click" data-cid="${a.cartao_id}">
          <td>${esc(a.titulo)}</td><td>${esc(a.coluna)}</td>
          <td>${esc(a.responsaveis||"—")}</td>
          <td class="${a.dias>=14?"vermelho":""}">${a.dias}d</td></tr>`).join("")}
      </tbody></table>` : '<div class="ca-vazio">Nenhum cartão aberto.</div>'}

      <div class="me-sec">Abertos por prioridade</div>
      <div class="me-pri">${Object.entries(m.por_prioridade).map(([p,n])=>
        `<span class="chip"><span class="pri pri-${esc(p)}"></span> ${esc(p)}: <b>${n}</b></span>`).join("")}</div>
    `;
    corpo.querySelectorAll(".me-click").forEach(tr=>{
      tr.onclick=()=>{ fecharModal("modal-metricas"); abrirModalCartao(parseInt(tr.dataset.cid), null); };
    });
  }catch(e){ corpo.innerHTML=`<div class="ca-vazio">Erro: ${esc(e.message)}</div>`; }
}

async function exportarMissao(){
  if(!BOARD) return;
  toast("Gerando planilha…");
  try{
    const res=await fetch(`/api/missoes/${BOARD.id}/export`, {headers:{Authorization:"Bearer "+token()}});
    if(!res.ok) throw new Error("HTTP "+res.status);
    const blob=await res.blob();
    const a=document.createElement("a");
    a.href=URL.createObjectURL(blob);
    a.download=`Missao_${BOARD.nome.replace(/[^\w-]+/g,"_")}.xlsx`;
    a.click();
    setTimeout(()=>URL.revokeObjectURL(a.href), 4000);
  }catch(e){ toast("Erro ao exportar: "+e.message, true); }
}

// ── modelos de missão ───────────────────────────────────────────────────
function abrirModalModelo(){
  if(!BOARD) return;
  document.getElementById("mo-nome").value=BOARD.nome;
  document.getElementById("mo-descricao").value=BOARD.descricao||"";
  document.getElementById("mo-cartoes").checked=true;
  document.getElementById("mo-lista").innerHTML=(BOARD.colunas||[]).map(c=>{
    const abertos=(c.cartoes||[]).filter(x=>!x.concluido).length;
    return `<div class="mo-linha"><b>${esc(c.nome)}</b>
      <span>${c.categoria||"sem categoria"}${c.limite_wip?` · WIP ${c.limite_wip}`:""} · ${abertos} cartão(ões) abertos</span></div>`;
  }).join("");
  document.getElementById("modal-modelo").style.display="flex";
  document.getElementById("mo-nome").focus();
}
async function salvarModelo(){
  const nome=document.getElementById("mo-nome").value.trim();
  if(!nome) return toast("Informe o nome do modelo", true);
  try{
    await api("/api/missoes/modelos",{method:"POST",body:JSON.stringify({
      missao_id:BOARD.id, nome, descricao:document.getElementById("mo-descricao").value.trim(),
      com_cartoes:document.getElementById("mo-cartoes").checked})});
    toast("Modelo salvo — já aparece ao criar uma missão nova");
    MODELOS=[];
    fecharModal("modal-modelo");
  }catch(e){ toast("Erro: "+e.message, true); }
}

// ── tempo real (best-effort; o estado real é sempre o servidor) ──────────
// O eco da própria ação já vinha aplicado na resposta HTTP; sem esta janela,
// cada mutação disparava um recarregamento redundante do board inteiro.
let _mudoAte=0;
function silenciarSocket(ms=1200){ _mudoAte=Date.now()+ms; }

function conectarSocket(){
  if(typeof io==="undefined") return;
  try{
    const s=io({auth:{token:token()}, transports:["websocket","polling"]});
    const label=document.getElementById("sync-label");
    s.on("connect",()=>{ if(label) label.textContent="Conectado"; });
    s.on("disconnect",()=>{ if(label) label.textContent="Offline"; });
    // N usuários ativos geravam N refetches do board por ação; a janela agrupa
    // a rajada de eventos numa recarga só.
    let pendente=null, precisaBoard=false;
    const agendar=()=>{
      if(pendente) return;
      pendente=setTimeout(async()=>{
        pendente=null;
        try{
          const r=await api("/api/missoes"+(VER_ARQUIVADAS?"?arquivadas=1":""));
          MISSOES=r.missoes||[];
          if(precisaBoard && BOARD && VISAO==="board") await selecionarMissao(BOARD.id);
          else renderSidebar();
          precisaBoard=false;
          atualizarBadges();
        }catch(e){ /* silencioso: o próximo evento tenta de novo */ }
      }, 450);
    };
    const refresh=(ev)=>{
      if(Date.now()<_mudoAte) return;            // eco da própria ação
      if(document.getElementById("modal-cartao").style.display==="flex") return;
      const p=(ev&&ev.payload)||{};
      if(!BOARD){ precisaBoard=false; agendar(); return; }
      if(p.missao_id===BOARD.id || (p.missao&&p.missao.id===BOARD.id)) precisaBoard=true;
      agendar();
    };
    ["MISSAO_CREATED","MISSAO_UPDATED","MISSAO_DELETED","MISSAO_ARQUIVADA",
     "MISSAO_COLUNA_CREATED","MISSAO_COLUNA_UPDATED","MISSAO_COLUNA_DELETED",
     "MISSAO_COLUNA_REORDENADA","MISSAO_COLUNAS_REORDENADAS",
     "MISSAO_CARTAO_CREATED","MISSAO_CARTAO_UPDATED","MISSAO_CARTAO_DELETED",
     "MISSAO_CARTAO_MOVIDO","MISSAO_CARTAO_COMENTADO"].forEach(ev=>s.on(ev, refresh));
  }catch(e){ /* tempo real é opcional */ }
}
