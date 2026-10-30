/* ═══════════════════════════════════════════════════════════════════════════
   cadernos.js — front do módulo Cadernos (cadernos de laboratório).

   Organização como o OneNote: caderno → (grupo) → seção → páginas, com as
   subpáginas recuadas na mesma lista. A página abre em LEITURA; "Editar" pega a
   trava no servidor (uma pessoa por vez) e monta o CKEditor 5. O autosave grava
   2 s depois da última mudança e renova a trava; "Concluir edição" solta a trava
   e o servidor guarda a sessão como versão.

   Imagens: o servidor guarda <img data-arquivo="uuid"> sem src. Aqui o src é
   montado com o token da sessão (`imgSrc`), e ao gravar o servidor tira o token
   de novo — nenhum token vai para o banco.

   Sem bundler e sem framework, como o resto do projeto. Depende de common.js
   (esc, getToken), auth.js (DT_AUTH), Sortable e do build UMD do CKEditor 5.
   ═══════════════════════════════════════════════════════════════════════════ */
"use strict";

sessionStorage.setItem("dt_module", "cadernos");

const el = id => document.getElementById(id);
const PARAMS = new URLSearchParams(location.search);
const AREA = (PARAMS.get("area") || sessionStorage.getItem("dt_area") || "pdr").toLowerCase();

let META = null;          // /api/meta
let CADERNOS = [];        // lista da área
let CAD = null;           // caderno aberto (dict da árvore)
let ARV = null;           // {nos, paginas}
let PAG = null;           // página aberta (completa)
let EDITOR = null;        // instância do CKEditor
let EDITANDO = false;
let VERSAO = 0;           // versão em que o editor está
let SUJO = false;         // há mudança não gravada
let GRAVANDO = null;      // promise da gravação em curso
let T_RENOVA = null, T_ESPIA = null, T_SALVA_META = null;

const RESULTADO_ROTULO = {"": "—", em_andamento: "Em andamento", aprovado: "Aprovado",
                          reprovado: "Reprovado", inconclusivo: "Inconclusivo"};
const ACESSO_ROTULO = {editor: "Toda a área edita", leitor: "A área só lê", nenhum: "Privado (só membros)"};
const PAPEL_ROTULO = {dono: "Dono", editor: "Editor", leitor: "Leitor"};

/* ── utilidades ── */
function userObj(){
  try{ return JSON.parse(localStorage.getItem("doctrack_user") || "{}") || {}; }
  catch(e){ return {}; }
}
function toast(msg, erro){
  const t = el("toast");
  el("toast-msg").textContent = msg;
  el("toast-dot").style.background = erro ? "var(--red, #f43f5e)" : "";
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 3600);
}
function fmtData(iso, comHora){
  if(!iso) return "—";
  const d = new Date(iso);
  if(isNaN(d)) return "—";
  const dia = d.toLocaleDateString("pt-BR");
  return comHora ? dia + " " + d.toLocaleTimeString("pt-BR", {hour: "2-digit", minute: "2-digit"}) : dia;
}
function fmtTam(b){
  if(b == null) return "";
  if(b < 1024) return b + " B";
  if(b < 1048576) return (b / 1024).toFixed(0) + " KB";
  return (b / 1048576).toFixed(1) + " MB";
}
function pode(minimo){
  const peso = {leitor: 1, editor: 2, dono: 3};
  return CAD && (peso[CAD.papel] || 0) >= peso[minimo];
}
function imgSrc(uuid){
  return "/cadernos/api/arquivos/" + uuid + "/conteudo?token=" + encodeURIComponent(getToken());
}
/* HTML guardado → HTML exibível: põe o src (com token) nas imagens e o href nos
   links para arquivos do caderno (anexos no texto). O anexo baixa a versão
   VIGENTE do arquivo (`atual=1`), não a que existia quando o link foi posto. */
function hrefAnexo(uuid){ return imgSrc(uuid) + "&download=1&atual=1"; }
function paraExibir(html){
  return (html || "")
    .replace(/<img\b([^>]*?)\sdata-arquivo="([0-9a-f-]{36})"([^>]*)>/g,
      (m, a, u, b) => '<img' + a + ' src="' + imgSrc(u) + '"' + b + '>')
    .replace(/<a\b([^>]*?)\sdata-arquivo="([0-9a-f-]{36})"([^>]*)>/g,
      (m, a, u, b) => '<a' + a + ' href="' + hrefAnexo(u) + '"' + b + '>');
}

/* ── fetch autenticado (mesmo contrato dos outros módulos) ── */
async function api(url, opts){
  opts = opts || {};
  const corpoForm = opts.body instanceof FormData;
  const h = Object.assign(corpoForm ? {} : {"Content-Type": "application/json"}, opts.headers || {});
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
    const e = new Error(corpo.erro || ("Falha na requisição (HTTP " + res.status + ")"));
    e.corpo = corpo; e.status = res.status;
    throw e;
  }
  return corpo;
}
const json = obj => JSON.stringify(obj);

/* ═══════════ MODAL E MENU ═══════════ */
let _modalSalvar = null;
let _modalAoFechar = null;     // chamado uma vez quando o modal fecha (ou é trocado)
function abrirModal(titulo, sub, corpoHtml, onSalvar, rotuloSalvar){
  _modalAoFechar = null;
  el("modal-titulo").textContent = titulo;
  el("modal-sub").textContent = sub || "";
  el("modal-corpo").innerHTML = corpoHtml;
  const salvar = el("modal-salvar");
  salvar.hidden = !onSalvar;
  salvar.textContent = rotuloSalvar || "Salvar";
  el("modal-cancelar").textContent = onSalvar ? "Cancelar" : "Fechar";
  _modalSalvar = onSalvar;
  el("modal-overlay").classList.add("open");
  const primeiro = el("modal-corpo").querySelector("input,select,textarea");
  if(primeiro) setTimeout(() => primeiro.focus(), 40);
}
function fecharModal(){
  el("modal-overlay").classList.remove("open");
  _modalSalvar = null;
  const f = _modalAoFechar;
  _modalAoFechar = null;
  if(f) f();
}
el("modal-cancelar").addEventListener("click", fecharModal);
el("modal-overlay").addEventListener("click", e => { if(e.target === el("modal-overlay")) fecharModal(); });
el("modal-salvar").addEventListener("click", async () => {
  if(!_modalSalvar) return;
  const b = el("modal-salvar");
  b.disabled = true;
  try{ const r = await _modalSalvar(); if(r !== false) fecharModal(); }
  catch(e){ toast(e.message, true); }
  finally{ b.disabled = false; }
});
document.addEventListener("keydown", e => {
  if(e.key === "Escape"){ fecharModal(); fecharMenu(); }
});

function abrirMenu(ancora, itens){
  const m = el("cd-menu");
  m.innerHTML = itens.filter(Boolean).map((it, i) => it === "-"
    ? '<div class="cd-menu-sep"></div>'
    : '<button type="button" role="menuitem" data-i="' + i + '"' + (it.perigo ? ' class="perigo"' : "") + '>' + esc(it.rotulo) + '</button>').join("");
  const r = ancora.getBoundingClientRect();
  m.hidden = false;
  const larg = m.offsetWidth;
  m.style.left = Math.max(8, Math.min(window.innerWidth - larg - 8, r.right - larg)) + "px";
  m.style.top = (r.bottom + 4 + window.scrollY) + "px";
  m.onclick = ev => {
    const b = ev.target.closest("button[data-i]");
    if(!b) return;
    const it = itens.filter(Boolean)[+b.dataset.i];
    fecharMenu();
    if(it && it.acao) it.acao();
  };
}
function fecharMenu(){ el("cd-menu").hidden = true; }
document.addEventListener("click", e => {
  if(!e.target.closest("#cd-menu") && !e.target.closest("[data-menu]")) fecharMenu();
});

/* ═══════════ CADERNOS ═══════════ */
async function carregarCadernos(){
  const r = await api("/cadernos/api/cadernos?area=" + AREA);
  CADERNOS = r.cadernos;
  renderListaCadernos();
}

function renderListaCadernos(){
  const box = el("cd-lista-cadernos");
  if(!CADERNOS.length){
    box.innerHTML = '<div class="cd-lista-vazia">Nenhum caderno ainda.</div>';
    return;
  }
  box.innerHTML = CADERNOS.map(c =>
    '<button type="button" class="nav-item cd-item-caderno' + (CAD && CAD.uuid === c.uuid ? " active" : "") +
    '" data-uuid="' + c.uuid + '" title="' + esc(c.nome) + '">' +
    '<span class="cd-dot" style="background:' + esc(c.cor || "#a855f7") + '"></span>' +
    '<span class="cd-item-nome">' + esc(c.nome) + '</span>' +
    '<span class="nav-count">' + (c.paginas || 0) + '</span></button>').join("");
  box.querySelectorAll(".cd-item-caderno").forEach(b =>
    b.addEventListener("click", () => abrirCaderno(b.dataset.uuid)));
}

async function abrirCaderno(uuid, paginaUuid){
  if(!(await sairDaEdicao())) return;
  try{
    const r = await api("/cadernos/api/cadernos/" + uuid + "/arvore");
    CAD = r.caderno;
    ARV = {nos: r.nos, paginas: r.paginas};
  } catch(e){ toast(e.message, true); return; }
  localStorage.setItem("cd_ultimo_" + AREA, uuid);
  el("cd-caderno-nome").textContent = CAD.nome;
  el("cd-caderno-cor").style.background = CAD.cor || "#a855f7";
  el("btn-menu-caderno").hidden = false;
  el("cd-arvore-pe").hidden = !pode("editor");
  el("breadcrumb-current").textContent = CAD.nome;
  renderListaCadernos();
  renderArvore();
  const alvo = paginaUuid || (ARV.paginas[0] && ARV.paginas[0].uuid);
  if(alvo && ARV.paginas.some(p => p.uuid === alvo)) abrirPagina(alvo);
  else mostrarVazio();
}

async function recarregarArvore(){
  if(!CAD) return;
  const r = await api("/cadernos/api/cadernos/" + CAD.uuid + "/arvore");
  CAD = r.caderno;
  ARV = {nos: r.nos, paginas: r.paginas};
  renderArvore();
}

async function recarregarTudo(){
  try{
    await carregarCadernos();
    if(CAD) await recarregarArvore();
    if(PAG && !EDITANDO) await abrirPagina(PAG.uuid);
  } catch(e){ toast(e.message, true); }
}

function formCaderno(c){
  c = c || {nome: "", cor: "#a855f7", acesso_area: "editor", modelo: "projeto_pdr", descricao: ""};
  const modelos = c.uuid ? "" :
    '<label class="cd-campo">Modelo<select id="f-modelo">' +
      META.modelos.map(m => '<option value="' + m.id + '"' + (m.id === c.modelo ? " selected" : "") + '>' + esc(m.nome) + '</option>').join("") +
    '</select><small>"Projeto PDR" já cria as seções das fases do projeto (Desenvolvimento, Validações, Estabilidade, Transferência).</small></label>';
  return '<label class="cd-campo">Nome<input id="f-nome" maxlength="200" value="' + esc(c.nome) + '" placeholder="Ex.: Projeto L-037 Kit de detecção CMV"></label>' +
    modelos +
    '<div class="cd-linha"><label class="cd-campo">Cor<input type="color" id="f-cor" value="' + esc(c.cor || "#a855f7") + '"></label>' +
    '<label class="cd-campo" style="flex:1">Quem acessa<select id="f-acesso">' +
      META.acessos_area.map(a => '<option value="' + a + '"' + (a === c.acesso_area ? " selected" : "") + '>' + ACESSO_ROTULO[a] + '</option>').join("") +
    '</select></label></div>' +
    '<label class="cd-campo">Descrição<textarea id="f-desc" rows="2">' + esc(c.descricao || "") + '</textarea></label>';
}

function novoCaderno(){
  abrirModal("Novo caderno", "Você será o dono do caderno.", formCaderno(), async () => {
    const r = await api("/cadernos/api/cadernos", {method: "POST", body: json({
      area: AREA, nome: el("f-nome").value, modelo: el("f-modelo").value,
      cor: el("f-cor").value, acesso_area: el("f-acesso").value, descricao: el("f-desc").value})});
    await carregarCadernos();
    toast("Caderno criado");
    abrirCaderno(r.caderno.uuid);
  }, "Criar");
}

function menuCaderno(ancora){
  abrirMenu(ancora, [
    {rotulo: "Arquivos do caderno (programas, dados…)", acao: () => modalArquivos("caderno", CAD.uuid, "Arquivos do caderno")},
    pode("editor") && {rotulo: "Exportar para a liderança (zip)…", acao: () => modalExportar(new Set(ARV.paginas.map(p => p.uuid)))},
    {rotulo: "Exportações anteriores", acao: modalHistoricoExportacoes},
    pode("editor") && {rotulo: "Lixeira do caderno", acao: modalLixeira},
    pode("dono") && "-",
    pode("dono") && {rotulo: "Renomear / cor / acesso", acao: editarCaderno},
    pode("dono") && {rotulo: "Membros", acao: modalMembros},
    pode("dono") && "-",
    pode("dono") && {rotulo: "Excluir caderno", perigo: true, acao: excluirCaderno},
    {rotulo: "Seu papel: " + (PAPEL_ROTULO[CAD.papel] || CAD.papel)},
  ]);
}

function editarCaderno(){
  abrirModal("Caderno", "", formCaderno(CAD), async () => {
    await api("/cadernos/api/cadernos/" + CAD.uuid, {method: "PATCH", body: json({
      nome: el("f-nome").value, cor: el("f-cor").value,
      acesso_area: el("f-acesso").value, descricao: el("f-desc").value})});
    await carregarCadernos();
    await abrirCaderno(CAD.uuid, PAG && PAG.uuid);
  });
}

async function excluirCaderno(){
  if(!confirm('Mandar o caderno "' + CAD.nome + '" para a lixeira? Ele some para todos. Só o dono restaura.')) return;
  try{
    await api("/cadernos/api/cadernos/" + CAD.uuid, {method: "DELETE"});
    CAD = null; ARV = null;
    await carregarCadernos();
    el("cd-arvore").innerHTML = "";
    el("cd-caderno-nome").textContent = "Escolha um caderno";
    el("btn-menu-caderno").hidden = true;
    el("cd-arvore-pe").hidden = true;
    mostrarVazio();
    toast("Caderno na lixeira");
  } catch(e){ toast(e.message, true); }
}

async function modalMembros(){
  const r = await api("/cadernos/api/cadernos/" + CAD.uuid);
  const atuais = {};
  (r.caderno.membros || []).forEach(m => atuais[m.user_id] = m.papel);
  const linhas = META.pessoas.map(p =>
    '<tr><td>' + esc(p.nome) + '</td><td><select data-uid="' + p.id + '">' +
    '<option value="">Padrão (' + esc(ACESSO_ROTULO[CAD.acesso_area]) + ')</option>' +
    ["leitor", "editor", "dono"].map(x => '<option value="' + x + '"' + (atuais[p.id] === x ? " selected" : "") + '>' + PAPEL_ROTULO[x] + '</option>').join("") +
    '</select></td></tr>').join("");
  abrirModal("Membros", "Papel explícito vence o acesso padrão da área.",
    '<div class="tbl-wrap cd-tbl-modal"><table class="tbl"><thead><tr><th>Pessoa</th><th>Papel</th></tr></thead><tbody>' + linhas + '</tbody></table></div>',
    async () => {
      const membros = [...el("modal-corpo").querySelectorAll("select[data-uid]")]
        .filter(s => s.value).map(s => ({user_id: +s.dataset.uid, papel: s.value}));
      await api("/cadernos/api/cadernos/" + CAD.uuid + "/membros", {method: "PUT", body: json({membros})});
      toast("Membros atualizados");
    });
}

/* ═══════════ ÁRVORE ═══════════ */
function filhosDe(parentId){
  return ARV.nos.filter(n => (n.parent_id || null) === (parentId || null))
                .sort((a, b) => (a.ordem - b.ordem) || (a.id - b.id));
}
function paginasDaSecao(id){
  return ARV.paginas.filter(p => p.secao_id === id).sort((a, b) => a.ordem - b.ordem);
}

function renderArvore(){
  const box = el("cd-arvore");
  if(!ARV) { box.innerHTML = ""; return; }
  const abertos = JSON.parse(localStorage.getItem("cd_fechados_" + CAD.uuid) || "[]");
  const fechado = new Set(abertos);
  function renderNo(n){
    if(n.tipo === "grupo"){
      const dentro = filhosDe(n.id).map(renderNo).join("");
      return '<div class="cd-grupo' + (fechado.has(n.uuid) ? " fechado" : "") + '" data-uuid="' + n.uuid + '">' +
        '<div class="cd-grupo-cab"><button class="cd-seta" data-toggle="' + n.uuid + '" aria-label="Expandir/recolher">▾</button>' +
        '<span class="cd-grupo-nome">' + esc(n.nome) + '</span>' +
        (pode("editor") ? '<button class="cd-icone" data-menu="no" data-uuid="' + n.uuid + '" aria-label="Opções">⋯</button>' : "") +
        '</div><div class="cd-grupo-corpo">' + (dentro || '<div class="cd-dica">Grupo vazio</div>') + '</div></div>';
    }
    const pags = paginasDaSecao(n.id);
    let escondeAte = 0;
    const itens = pags.map((p, i) => {
      if(escondeAte && p.nivel > escondeAte) return "";
      escondeAte = 0;
      const temFilhas = pags[i + 1] && pags[i + 1].nivel > p.nivel;
      if(temFilhas && p.recolhida) escondeAte = p.nivel;
      const trava = p.editando ? '<span class="cd-trava-mini" title="Em edição por ' + esc(p.editando.por) + '">✎</span>' : "";
      return '<div class="cd-pag-item nivel-' + p.nivel + (PAG && PAG.uuid === p.uuid ? " ativa" : "") +
        '" data-uuid="' + p.uuid + '" tabindex="0">' +
        (temFilhas ? '<button class="cd-seta-pag" data-recolher="' + p.uuid + '">' + (p.recolhida ? "▸" : "▾") + '</button>' : '<span class="cd-seta-pag vazia"></span>') +
        '<span class="cd-pag-nome">' + (p.tipo === "registro_teste" ? '<span class="cd-tag-teste" title="Registro de teste">T</span>' : "") + esc(p.titulo || "Sem título") + '</span>' + trava +
        (pode("editor") ? '<button class="cd-icone" data-menu="pagina" data-uuid="' + p.uuid + '" aria-label="Opções da página">⋯</button>' : "") +
        '</div>';
    }).join("");
    return '<div class="cd-secao' + (fechado.has(n.uuid) ? " fechado" : "") + '" data-uuid="' + n.uuid + '">' +
      '<div class="cd-secao-cab" style="--cor-secao:' + esc(n.cor || CAD.cor || "#a855f7") + '">' +
        '<button class="cd-seta" data-toggle="' + n.uuid + '" aria-label="Expandir/recolher">▾</button>' +
        '<span class="cd-secao-nome">' + esc(n.nome) + '</span><span class="cd-secao-n">' + pags.length + '</span>' +
        (pode("editor") ? '<button class="cd-icone" data-nova-pagina="' + n.uuid + '" title="Nova página">+</button>' +
                          '<button class="cd-icone" data-menu="no" data-uuid="' + n.uuid + '" aria-label="Opções da seção">⋯</button>' : "") +
      '</div><div class="cd-secao-paginas" data-secao="' + n.uuid + '">' + (itens || '<div class="cd-dica">Sem páginas</div>') + '</div></div>';
  }
  const raiz = filhosDe(null);
  box.innerHTML = raiz.length ? raiz.map(renderNo).join("") : '<div class="cd-dica">Caderno sem seções.</div>';
  ligarArvore();
}

function ligarArvore(){
  const box = el("cd-arvore");
  box.querySelectorAll("[data-toggle]").forEach(b => b.addEventListener("click", e => {
    e.stopPropagation();
    const alvo = b.closest(".cd-secao, .cd-grupo");
    alvo.classList.toggle("fechado");
    const fechados = [...box.querySelectorAll(".cd-secao.fechado, .cd-grupo.fechado")].map(x => x.dataset.uuid);
    localStorage.setItem("cd_fechados_" + CAD.uuid, JSON.stringify(fechados));
  }));
  box.querySelectorAll(".cd-pag-item").forEach(it => {
    it.addEventListener("click", e => {
      if(e.target.closest("[data-menu],[data-recolher]")) return;
      abrirPagina(it.dataset.uuid);
    });
    it.addEventListener("keydown", e => {
      if(e.key === "Enter") abrirPagina(it.dataset.uuid);
      if(e.key === "Tab" && pode("editor") && document.activeElement === it){
        e.preventDefault();
        mudarNivel(it.dataset.uuid, e.shiftKey ? -1 : 1);
      }
    });
  });
  box.querySelectorAll("[data-recolher]").forEach(b => b.addEventListener("click", async e => {
    e.stopPropagation();
    const p = ARV.paginas.find(x => x.uuid === b.dataset.recolher);
    p.recolhida = !p.recolhida;
    renderArvore();
    try{ await api("/cadernos/api/paginas/" + p.uuid, {method: "PATCH", body: json({recolhida: p.recolhida})}); }
    catch(err){ toast(err.message, true); }
  }));
  box.querySelectorAll("[data-nova-pagina]").forEach(b => b.addEventListener("click", e => {
    e.stopPropagation(); novaPagina(b.dataset.novaPagina);
  }));
  box.querySelectorAll("[data-menu=no]").forEach(b => b.addEventListener("click", e => {
    e.stopPropagation(); menuNo(b, b.dataset.uuid);
  }));
  box.querySelectorAll("[data-menu=pagina]").forEach(b => b.addEventListener("click", e => {
    e.stopPropagation(); menuPaginaArvore(b, b.dataset.uuid);
  }));
  // Arrastar páginas (inclusive para outra seção). A série vai junto: quem
  // decide isso é o servidor, e a árvore é redesenhada a partir da resposta.
  if(pode("editor") && typeof Sortable !== "undefined"){
    box.querySelectorAll(".cd-secao-paginas").forEach(lista => {
      new Sortable(lista, {
        group: "cd-paginas", animation: 120, draggable: ".cd-pag-item",
        filter: ".cd-icone,.cd-seta-pag", preventOnFilter: false,
        onEnd: async ev => {
          const uuid = ev.item.dataset.uuid;
          const destino = ev.to.dataset.secao;
          const anterior = ev.item.previousElementSibling;
          const apos = anterior && anterior.classList.contains("cd-pag-item") ? anterior.dataset.uuid : null;
          try{
            await api("/cadernos/api/paginas/" + uuid + "/mover", {method: "POST",
              body: json({secao_uuid: destino, apos_uuid: apos})});
          } catch(err){ toast(err.message, true); }
          await recarregarArvore();
        },
      });
    });
  }
}

function menuNo(ancora, uuid){
  const n = ARV.nos.find(x => x.uuid === uuid);
  abrirMenu(ancora, [
    n.tipo === "secao" && {rotulo: "Nova página", acao: () => novaPagina(uuid)},
    n.tipo === "secao" && {rotulo: "Novo registro de teste", acao: () => novaPagina(uuid, {tipo: "registro_teste"})},
    n.tipo === "grupo" && {rotulo: "Nova seção dentro do grupo", acao: () => novoNo("secao", uuid)},
    n.tipo === "secao" && {rotulo: "Arquivos da seção", acao: () => modalArquivos("secao", uuid, "Arquivos da seção " + n.nome)},
    n.tipo === "secao" && pode("editor") && {rotulo: "Exportar seção (zip)…", acao: () => modalExportar(new Set(paginasDaSecao(n.id).map(p => p.uuid)))},
    "-",
    {rotulo: "Renomear", acao: () => renomearNo(n)},
    {rotulo: "Cor", acao: () => corNo(n)},
    {rotulo: "Mover para o topo", acao: () => moverNo(n, null)},
    "-",
    {rotulo: "Excluir " + (n.tipo === "grupo" ? "grupo" : "seção"), perigo: true, acao: () => excluirNo(n)},
  ]);
}

function novoNo(tipo, parentUuid){
  const rot = tipo === "grupo" ? "Novo grupo de seções" : "Nova seção";
  abrirModal(rot, "", '<label class="cd-campo">Nome<input id="f-nome" maxlength="200"></label>' +
    (tipo === "secao" ? '<label class="cd-campo">"+ Página" cria<select id="f-tipo"><option value="nota">Nota</option><option value="registro_teste">Registro de teste</option></select></label>' : ""),
    async () => {
      await api("/cadernos/api/cadernos/" + CAD.uuid + "/nos", {method: "POST", body: json({
        tipo, nome: el("f-nome").value, parent_uuid: parentUuid || null,
        tipo_pagina_padrao: el("f-tipo") ? el("f-tipo").value : "nota"})});
      await recarregarArvore();
    }, "Criar");
}
function renomearNo(n){
  abrirModal("Renomear", "", '<label class="cd-campo">Nome<input id="f-nome" maxlength="200" value="' + esc(n.nome) + '"></label>', async () => {
    await api("/cadernos/api/nos/" + n.uuid, {method: "PATCH", body: json({nome: el("f-nome").value})});
    await recarregarArvore();
  });
}
function corNo(n){
  abrirModal("Cor da seção", "", '<label class="cd-campo">Cor<input type="color" id="f-cor" value="' + esc(n.cor || CAD.cor || "#a855f7") + '"></label>', async () => {
    await api("/cadernos/api/nos/" + n.uuid, {method: "PATCH", body: json({cor: el("f-cor").value})});
    await recarregarArvore();
  });
}
async function moverNo(n, parentUuid){
  try{
    await api("/cadernos/api/nos/" + n.uuid + "/mover", {method: "POST", body: json({parent_uuid: parentUuid, apos_uuid: null})});
    await recarregarArvore();
  } catch(e){ toast(e.message, true); }
}
async function excluirNo(n){
  if(!confirm('Mandar "' + n.nome + '" (e tudo dentro) para a lixeira?')) return;
  try{
    await api("/cadernos/api/nos/" + n.uuid, {method: "DELETE"});
    if(PAG && !ARV.paginas.some(p => p.uuid === PAG.uuid)) mostrarVazio();
    await recarregarArvore();
    if(PAG && !ARV.paginas.some(p => p.uuid === PAG.uuid)) mostrarVazio();
    toast("Na lixeira — restaure pelo 🗑");
  } catch(e){ toast(e.message, true); }
}

function menuPaginaArvore(ancora, uuid){
  const p = ARV.paginas.find(x => x.uuid === uuid);
  const secao = ARV.nos.find(n => n.id === p.secao_id);
  abrirMenu(ancora, [
    {rotulo: "Nova página abaixo", acao: () => novaPagina(secao.uuid, {apos_uuid: uuid})},
    {rotulo: "Nova subpágina", acao: () => novaPagina(secao.uuid, {subpagina_de: uuid})},
    "-",
    {rotulo: "Rebaixar (vira subpágina)", acao: () => mudarNivel(uuid, 1)},
    {rotulo: "Promover", acao: () => mudarNivel(uuid, -1)},
    {rotulo: "Mover para outra seção…", acao: () => moverPaginaPara(p)},
    "-",
    {rotulo: "Excluir página", perigo: true, acao: () => excluirPagina(p)},
  ]);
}

async function novaPagina(secaoUuid, extra){
  if(!(await sairDaEdicao())) return;
  try{
    const r = await api("/cadernos/api/secoes/" + secaoUuid + "/paginas", {method: "POST", body: json(extra || {})});
    await recarregarArvore();
    await abrirPagina(r.pagina.uuid);
    editar();           // página nova já abre em edição
  } catch(e){ toast(e.message, true); }
}
async function mudarNivel(uuid, delta){
  try{
    await api("/cadernos/api/paginas/" + uuid + "/nivel", {method: "POST", body: json({delta})});
    await recarregarArvore();
  } catch(e){ toast(e.message, true); }
}
function moverPaginaPara(p){
  const secoes = ARV.nos.filter(n => n.tipo === "secao");
  abrirModal("Mover página", "As subpáginas vão junto.", '<label class="cd-campo">Seção de destino<select id="f-secao">' +
    secoes.map(s => '<option value="' + s.uuid + '"' + (s.id === p.secao_id ? " selected" : "") + '>' + esc(s.nome) + '</option>').join("") +
    '</select></label>', async () => {
      await api("/cadernos/api/paginas/" + p.uuid + "/mover", {method: "POST", body: json({secao_uuid: el("f-secao").value, apos_uuid: null})});
      await recarregarArvore();
    }, "Mover");
}
async function excluirPagina(p){
  if(!confirm('Mandar a página "' + p.titulo + '" para a lixeira?')) return;
  try{
    await api("/cadernos/api/paginas/" + p.uuid, {method: "DELETE"});
    if(PAG && PAG.uuid === p.uuid){ await sairDaEdicao(true); mostrarVazio(); }
    await recarregarArvore();
    toast("Página na lixeira — restaure pelo 🗑");
  } catch(e){ toast(e.message, true); }
}

/* ═══════════ PÁGINA (leitura) ═══════════ */
function mostrarVazio(){
  PAG = null;
  el("cd-pag").hidden = true;
  el("cd-vazio").hidden = false;
  pararEspia();
  if(CAD) history.replaceState(null, "", "#c=" + CAD.uuid);
}

async function abrirPagina(uuid){
  if(PAG && PAG.uuid !== uuid && !(await sairDaEdicao())) return;
  let r;
  try{ r = await api("/cadernos/api/paginas/" + uuid); }
  catch(e){ toast(e.message, true); return; }
  PAG = r.pagina;
  VERSAO = PAG.versao;
  history.replaceState(null, "", "#c=" + CAD.uuid + "&p=" + PAG.uuid);
  el("cd-vazio").hidden = true;
  el("cd-pag").hidden = false;
  document.querySelectorAll(".cd-pag-item").forEach(x => x.classList.toggle("ativa", x.dataset.uuid === uuid));
  renderPagina();
  carregarArquivosPagina();
  iniciarEspia();
}

function renderPagina(){
  const p = PAG;
  el("cd-pag-caminho").textContent = (p.secao ? p.secao.nome : "") ;
  el("cd-titulo").textContent = p.titulo || "Sem título";
  el("cd-titulo").hidden = EDITANDO;
  el("cd-titulo-input").hidden = !EDITANDO;
  el("cd-meta").innerHTML =
    '<span title="Data da página">📅 ' + fmtData(p.data_pagina, true) + '</span>' +
    (p.origem_autores ? '<span title="Autores registrados no OneNote">Autores no OneNote: ' + esc(p.origem_autores) + '</span>'
                      : '<span>Criada por ' + esc(p.criado_por || "—") + '</span>') +
    (p.atualizado_por ? '<span>Editada por ' + esc(p.atualizado_por) + ' em ' + fmtData(p.atualizado_em, true) + '</span>'
                      : '<span>Modificada' + (p.origem_autores ? ' no OneNote' : '') + ' em ' + fmtData(p.atualizado_em, true) + '</span>') +
    '<span class="cd-versao">v' + p.versao + '</span>';
  renderFicha();
  if(!EDITANDO) el("cd-leitura").innerHTML = paraExibir(p.html) || '<p class="cd-dica">Página vazia. Clique em <b>Editar</b> para escrever.</p>';
  el("cd-leitura").hidden = EDITANDO;
  el("cd-editor-host").hidden = !EDITANDO;
  el("btn-editar").hidden = EDITANDO || !pode("editor");
  // Exportar é de editor (R-50): o servidor recusa o leitor, a tela nem oferece.
  el("btn-exportar").hidden = !pode("editor");
  el("btn-concluir").hidden = !EDITANDO;
  renderTrava();
}

function renderTrava(){
  const t = PAG && PAG.editando;
  const box = el("cd-trava");
  const meu = META && t && t.por_id === META.eu.id;
  if(!t || meu || EDITANDO){ box.hidden = true; el("btn-editar").disabled = false; return; }
  box.hidden = false;
  box.innerHTML = '✎ <b>' + esc(t.por) + '</b> está editando esta página. Ela atualiza aqui sozinha quando a pessoa gravar.' +
    (pode("dono") ? ' <button class="btn btn-ghost btn-sm" id="btn-tomar">Tomar a edição</button>' : "");
  el("btn-editar").disabled = true;
  const b = el("btn-tomar");
  if(b) b.addEventListener("click", tomarEdicao);
}

/* Enquanto a página está aberta em leitura, consulta a cada 20 s se alguém a
   gravou ou pegou a trava. Barato (só metadados) e sem socket nesta fase. */
function iniciarEspia(){
  pararEspia();
  T_ESPIA = setInterval(async () => {
    if(!PAG || EDITANDO || document.hidden) return;
    try{
      const r = await api("/cadernos/api/paginas/" + PAG.uuid + "?leve=1");
      const mudouTrava = JSON.stringify(r.pagina.editando) !== JSON.stringify(PAG.editando);
      if(r.pagina.versao !== PAG.versao) await abrirPagina(PAG.uuid);
      else if(mudouTrava){ PAG.editando = r.pagina.editando; renderTrava(); }
    } catch(e){ /* silencioso: a próxima tentativa resolve */ }
  }, 20000);
}
function pararEspia(){ if(T_ESPIA){ clearInterval(T_ESPIA); T_ESPIA = null; } }

/* ═══════════ FICHA DO REGISTRO DE TESTE ═══════════ */
function nomePessoa(id){
  const p = (META.pessoas || []).find(x => x.id === id);
  return p ? p.nome : (id ? "#" + id : "—");
}
function renderFicha(){
  const box = el("cd-ficha");
  if(!PAG || PAG.tipo !== "registro_teste"){ box.hidden = true; box.innerHTML = ""; return; }
  box.hidden = false;
  const f = PAG.ficha || {};
  if(!EDITANDO){
    const res = f.resultado || "";
    box.innerHTML = '<div class="cd-ficha-titulo">Registro de teste</div><div class="cd-ficha-grade">' +
      campoLeitura("Projeto", f.projeto) + campoLeitura("Número do teste", f.numero) +
      campoLeitura("Responsável pelo teste", f.resp_teste_id ? nomePessoa(f.resp_teste_id) : (f.resp_teste_nome || "—")) +
      campoLeitura("Responsável pela execução", f.resp_execucao_id ? nomePessoa(f.resp_execucao_id) : (f.resp_execucao_nome || "—")) +
      campoLeitura("Início", f.inicio ? fmtData(f.inicio + "T12:00") : "—") +
      campoLeitura("Término", f.termino ? fmtData(f.termino + "T12:00") : "—") +
      '<div class="cd-ficha-campo"><span>Resultado</span><b class="cd-res cd-res-' + (res || "nenhum") + '">' + RESULTADO_ROTULO[res] + '</b></div>' +
      '</div>';
    return;
  }
  const opcPessoa = (sel, nome) => '<option value="">' + (nome ? esc(nome) + " (do OneNote)" : "—") + '</option>' + META.pessoas.map(p =>
    '<option value="' + p.id + '"' + (p.id === sel ? " selected" : "") + '>' + esc(p.nome) + '</option>').join("");
  box.innerHTML = '<div class="cd-ficha-titulo">Registro de teste</div><div class="cd-ficha-grade">' +
    '<label class="cd-ficha-campo"><span>Projeto</span><input data-f="projeto" maxlength="80" value="' + esc(f.projeto || "") + '"></label>' +
    '<label class="cd-ficha-campo"><span>Número do teste</span><input data-f="numero" maxlength="40" value="' + esc(f.numero || "") + '"></label>' +
    '<label class="cd-ficha-campo"><span>Responsável pelo teste</span><select data-f="resp_teste_id">' + opcPessoa(f.resp_teste_id, f.resp_teste_nome) + '</select><input type="hidden" data-f="resp_teste_nome" value="' + esc(f.resp_teste_nome || "") + '"></label>' +
    '<label class="cd-ficha-campo"><span>Responsável pela execução</span><select data-f="resp_execucao_id">' + opcPessoa(f.resp_execucao_id, f.resp_execucao_nome) + '</select><input type="hidden" data-f="resp_execucao_nome" value="' + esc(f.resp_execucao_nome || "") + '"></label>' +
    '<label class="cd-ficha-campo"><span>Início</span><input type="date" data-f="inicio" value="' + esc(f.inicio || "") + '"></label>' +
    '<label class="cd-ficha-campo"><span>Término</span><input type="date" data-f="termino" value="' + esc(f.termino || "") + '"></label>' +
    '<label class="cd-ficha-campo"><span>Resultado</span><select data-f="resultado">' +
      META.resultados.map(r => '<option value="' + r + '"' + (r === (f.resultado || "") ? " selected" : "") + '>' + RESULTADO_ROTULO[r] + '</option>').join("") +
    '</select></label></div>';
  box.querySelectorAll("[data-f]").forEach(c => c.addEventListener("change", () => marcarSujo()));
  box.querySelectorAll("input[data-f]").forEach(c => c.addEventListener("input", () => marcarSujo()));
}
function campoLeitura(rot, v){
  return '<div class="cd-ficha-campo"><span>' + esc(rot) + '</span><b>' + esc(v || "—") + '</b></div>';
}
function lerFicha(){
  const f = {};
  el("cd-ficha").querySelectorAll("[data-f]").forEach(c => {
    let v = c.value;
    if(c.dataset.f.endsWith("_id")) v = v ? +v : null;
    f[c.dataset.f] = v;
  });
  return f;
}

/* ═══════════ EDIÇÃO ═══════════ */
const PALETA_CELULA = [
  // As cores de célula mais usadas no L-037 (inventário de 2026-10-05), da
  // paleta do Office: o conteúdo importado continua editável com as mesmas cores.
  ["#F2F2F2", "Cinza 5%"], ["#D8D8D8", "Cinza 15%"], ["#BFBFBF", "Cinza 25%"],
  ["#B8CCE4", "Azul claro"], ["#D9E2F3", "Azul 10%"], ["#DAE8F8", "Azul gelo"],
  ["#9BBB59", "Verde oliva"], ["#C3D69B", "Verde claro"], ["#B2A2C7", "Lilás"],
  ["#CCC1D9", "Lilás claro"], ["#FBD5B5", "Laranja claro"], ["#FAC090", "Laranja"],
  ["#FFFF99", "Amarelo claro"], ["#FF9999", "Vermelho claro"], ["#FFFFFF", "Branco"],
].map(([color, label]) => ({color, label}));

function configEditor(){
  const C = window.CKEDITOR;
  class Upload {
    constructor(loader){ this.loader = loader; }
    upload(){
      return this.loader.file.then(file => {
        const fd = new FormData();
        fd.append("upload", file);
        return api("/cadernos/api/paginas/" + PAG.uuid + "/imagens", {method: "POST", body: fd})
          .then(r => ({default: imgSrc(r.uuid)}));
      });
    }
    abort(){}
  }
  function UploadPlugin(editor){
    editor.plugins.get("FileRepository").createUploadAdapter = loader => new Upload(loader);
  }
  /* Anexo dentro da nota, como o "Inserir › Arquivo" do OneNote: o arquivo vai
     para os arquivos da PÁGINA (o mesmo painel 📎) e o texto ganha um link para
     ele onde estava o cursor. Arrastar um arquivo qualquer para o texto faz o
     mesmo; imagem arrastada continua virando imagem. */
  function AnexoPlugin(editor){
    editor.ui.componentFactory.add("anexarArquivo", locale => {
      const b = new C.ButtonView(locale);
      b.set({label: "Anexar arquivo (qualquer extensão)", icon: ICONE_CLIPE, tooltip: true});
      b.on("execute", () => escolherArquivos({escopo: "pagina", ref: PAG.uuid,
        aoEnviar: a => inserirAnexo(editor, a), aoTerminar: carregarArquivosPagina}));
      return b;
    });
    editor.editing.view.document.on("clipboardInput", (evt, data) => {
      const dt = data.dataTransfer;
      const arquivos = Array.from((dt && dt.files) || []);
      if(!arquivos.length || dt.getData("text/html")) return;
      const imagens = arquivos.filter(f => /^image\/(png|jpe?g|gif|webp)$/.test(f.type));
      const outros = arquivos.filter(f => !imagens.includes(f));
      if(!outros.length) return;                 // só imagens: o ImageUpload cuida
      evt.stop();
      if(data.targetRanges && data.targetRanges.length){
        const alvo = editor.editing.mapper.toModelRange(data.targetRanges[0]);
        editor.model.change(w => w.setSelection(alvo));
      }
      if(imagens.length) editor.execute("uploadImage", {file: imagens});
      enviarArquivos(outros, {escopo: "pagina", ref: PAG.uuid,
        aoEnviar: a => inserirAnexo(editor, a), aoTerminar: carregarArquivosPagina});
    }, {priority: "high"});
  }
  return {
    licenseKey: "GPL",
    language: "pt-br",
    translations: window.CKEDITOR_TRANSLATIONS,
    plugins: [
      C.Essentials, C.Paragraph, C.Heading, C.Bold, C.Italic, C.Underline, C.Strikethrough,
      C.Subscript, C.Superscript, C.Code, C.FontColor, C.FontBackgroundColor, C.FontSize,
      C.Highlight, C.Alignment, C.Indent, C.IndentBlock, C.List, C.ListProperties, C.TodoList,
      C.Table, C.TableToolbar, C.TableProperties, C.TableCellProperties, C.TableColumnResize,
      C.TableCaption, C.Image, C.ImageToolbar, C.ImageCaption, C.ImageStyle, C.ImageResize,
      C.ImageUpload, C.ImageBlock, C.ImageInline, C.Link, C.AutoLink, C.PasteFromOffice,
      C.FindAndReplace, C.SpecialCharacters, C.SpecialCharactersEssentials, C.CodeBlock,
      C.BlockQuote, C.HorizontalLine, C.RemoveFormat, C.Autosave, C.WordCount,
    ],
    extraPlugins: [UploadPlugin, AnexoPlugin],
    toolbar: {
      items: ["undo", "redo", "|", "heading", "|", "fontSize", "fontColor", "fontBackgroundColor", "highlight", "|",
              "bold", "italic", "underline", "strikethrough", "subscript", "superscript", "removeFormat", "|",
              "alignment", "bulletedList", "numberedList", "todoList", "outdent", "indent", "|",
              "insertTable", "uploadImage", "anexarArquivo", "link", "blockQuote", "codeBlock", "horizontalLine", "specialCharacters", "|",
              "findAndReplace"],
      shouldNotGroupWhenFull: false,
    },
    heading: {options: [
      {model: "paragraph", title: "Parágrafo", class: "ck-heading_paragraph"},
      {model: "heading2", view: "h2", title: "Título 1", class: "ck-heading_heading2"},
      {model: "heading3", view: "h3", title: "Título 2", class: "ck-heading_heading3"},
      {model: "heading4", view: "h4", title: "Título 3", class: "ck-heading_heading4"},
    ]},
    fontSize: {options: ["tiny", "small", "default", "big", "huge"]},
    highlight: {options: [
      // As seis cores de realce do OneNote, as mesmas encontradas no L-037.
      {model: "yellowMarker", class: "marker-yellow", title: "Amarelo", color: "#ffff00", type: "marker"},
      {model: "limeMarker", class: "marker-lime", title: "Verde-limão", color: "#00ff00", type: "marker"},
      {model: "fuchsiaMarker", class: "marker-fuchsia", title: "Magenta", color: "#ff00ff", type: "marker"},
      {model: "redMarker", class: "marker-red", title: "Vermelho", color: "#ff5c5c", type: "marker"},
      {model: "aquaMarker", class: "marker-aqua", title: "Ciano", color: "#00ffff", type: "marker"},
      {model: "silverMarker", class: "marker-silver", title: "Cinza", color: "#c0c0c0", type: "marker"},
    ]},
    table: {
      contentToolbar: ["tableColumn", "tableRow", "mergeTableCells", "tableProperties", "tableCellProperties", "toggleTableCaption"],
      tableCellProperties: {backgroundColors: PALETA_CELULA, borderColors: PALETA_CELULA},
      tableProperties: {backgroundColors: PALETA_CELULA, borderColors: PALETA_CELULA},
    },
    image: {
      toolbar: ["imageTextAlternative", "toggleImageCaption", "|", "imageStyle:inline", "imageStyle:block",
                "imageStyle:side", "|", "resizeImage"],
      upload: {types: ["png", "jpeg", "gif", "webp"]},
    },
    list: {properties: {styles: true, startIndex: true, reversed: false}},
    link: {addTargetToExternalLinks: true, defaultProtocol: "https://"},
    placeholder: "Escreva aqui. Cole tabelas do Excel e imagens direto.",
    autosave: {waitingTime: 2000, save: () => salvar()},
    wordCount: {onUpdate: s => { el("cd-contagem").textContent = s.words + " palavras · " + s.characters + " caracteres"; }},
  };
}

const ICONE_CLIPE = '<svg viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg"><path fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" d="M13.5 6.5 7.4 12.6a1.6 1.6 0 0 0 2.3 2.3l6.4-6.4a3.2 3.2 0 0 0-4.5-4.5L5.2 10.4a4.8 4.8 0 0 0 6.8 6.8l5.1-5.1"/></svg>';

/* Põe no texto, onde está o cursor, o link para um arquivo do caderno. O
   servidor guarda <a data-arquivo="uuid">nome</a>: sem URL e sem token. */
function inserirAnexo(editor, a){
  if(!editor || editor.state === "destroyed") return;
  editor.model.change(w => {
    const sel = editor.model.document.selection;
    editor.model.insertContent(w.createText(a.nome, {linkHref: hrefAnexo(a.uuid)}), sel);
    const pos = editor.model.document.selection.getFirstPosition();
    w.insertText(" ", pos);
    w.setSelection(w.createPositionAt(pos.parent, pos.offset + 1));
  });
  editor.editing.view.focus();
}

async function editar(){
  if(!PAG || EDITANDO) return;
  if(!window.CKEDITOR){ toast("O editor não carregou (static/vendor/ckeditor5).", true); return; }
  let r;
  try{ r = await api("/cadernos/api/paginas/" + PAG.uuid + "/edicao", {method: "POST"}); }
  catch(e){
    if(e.status === 423 && e.corpo && e.corpo.editando){ PAG.editando = e.corpo.editando; renderTrava(); }
    toast(e.message, true);
    return;
  }
  PAG = r.pagina;
  VERSAO = PAG.versao;
  EDITANDO = true;
  SUJO = false;
  pararEspia();
  renderPagina();
  el("cd-titulo-input").value = PAG.titulo || "";
  el("cd-titulo-input").oninput = () => marcarSujo();
  try{
    EDITOR = await window.CKEDITOR.ClassicEditor.create(el("cd-editor"), configEditor());
    EDITOR.setData(paraExibir(PAG.html));
    EDITOR.model.document.on("change:data", () => { SUJO = true; status("Alterações não salvas…"); });
    EDITOR.editing.view.focus();
  } catch(e){
    console.error(e);
    toast("Falha ao abrir o editor: " + e.message, true);
    await sairDaEdicao(true);
    return;
  }
  status("Editando — salva sozinho");
  T_RENOVA = setInterval(renovar, 30000);
  carregarArquivosPagina();      // o painel passa a oferecer "Inserir no texto"
}

/* Mudança no título ou na ficha (fora do CKEditor): agenda a gravação. */
function marcarSujo(){
  SUJO = true;
  status("Alterações não salvas…");
  clearTimeout(T_SALVA_META);
  T_SALVA_META = setTimeout(() => salvar(), 2000);
}

async function salvar(){
  if(!EDITANDO || !EDITOR) return;
  if(GRAVANDO){ await GRAVANDO.catch(() => {}); }
  if(!SUJO) return;
  const corpo = {versao_base: VERSAO, titulo: el("cd-titulo-input").value, html: EDITOR.getData()};
  if(PAG.tipo === "registro_teste") corpo.ficha = lerFicha();
  SUJO = false;
  status("Salvando…");
  GRAVANDO = api("/cadernos/api/paginas/" + PAG.uuid, {method: "PUT", body: json(corpo)})
    .then(r => {
      VERSAO = r.versao;
      PAG.versao = r.versao;
      PAG.titulo = corpo.titulo;
      if(corpo.ficha) PAG.ficha = corpo.ficha;
      status("Salvo às " + new Date().toLocaleTimeString("pt-BR", {hour: "2-digit", minute: "2-digit", second: "2-digit"}));
      const item = ARV && ARV.paginas.find(x => x.uuid === PAG.uuid);
      if(item && item.titulo !== corpo.titulo){ item.titulo = corpo.titulo; renderArvore(); }
    })
    .catch(async e => {
      SUJO = true;
      status("Não salvo", true);
      toast(e.message, true);
      if(e.status === 409 || e.status === 423){ await sairDaEdicao(true); await abrirPagina(PAG.uuid); }
      throw e;
    })
    .finally(() => { GRAVANDO = null; });
  return GRAVANDO;
}

async function renovar(){
  if(!EDITANDO || !PAG) return;
  try{ await api("/cadernos/api/paginas/" + PAG.uuid + "/edicao", {method: "PUT"}); }
  catch(e){
    toast("A trava de edição foi perdida: " + e.message, true);
    await sairDaEdicao(true);
    if(PAG) await abrirPagina(PAG.uuid);
  }
}

/* Fecha a edição (grava o que falta e solta a trava). `forcar` = sem gravar,
   usado quando o servidor já recusou. Devolve false se a pessoa desistiu. */
async function sairDaEdicao(forcar){
  if(!EDITANDO) return true;
  clearInterval(T_RENOVA); T_RENOVA = null;
  clearTimeout(T_SALVA_META);
  if(!forcar){
    try{ SUJO = SUJO || false; await salvar(); }
    catch(e){
      if(!confirm("Não foi possível salvar as últimas alterações. Sair mesmo assim e perdê-las?")){
        T_RENOVA = setInterval(renovar, 30000);
        return false;
      }
    }
    try{ await api("/cadernos/api/paginas/" + PAG.uuid + "/edicao", {method: "DELETE"}); } catch(e){}
  }
  EDITANDO = false;
  SUJO = false;
  if(EDITOR){ try{ await EDITOR.destroy(); } catch(e){} EDITOR = null; }
  el("cd-editor").innerHTML = "";
  status("");
  return true;
}

async function concluir(){
  const uuid = PAG.uuid;
  if(await sairDaEdicao()){
    await abrirPagina(uuid);
    await recarregarArvore();
    toast("Edição concluída — versão guardada");
  }
}

async function tomarEdicao(){
  if(!confirm("Tomar a edição desta página? O que a outra pessoa já salvou fica guardado como versão; ela perde a trava.")) return;
  try{
    await api("/cadernos/api/paginas/" + PAG.uuid + "/edicao/tomar", {method: "POST"});
    PAG.editando = null;
    await editarComTravaJaPega();
  } catch(e){ toast(e.message, true); }
}
async function editarComTravaJaPega(){
  // A trava já é nossa: o POST de edição só renova e devolve a página fresca.
  await editar();
}

function status(txt, erro){
  const s = el("cd-status");
  s.textContent = txt || "";
  s.classList.toggle("erro", !!erro);
}

window.addEventListener("beforeunload", e => {
  if(EDITANDO && (SUJO || GRAVANDO)){ e.preventDefault(); e.returnValue = ""; }
});

/* ═══════════ VERSÕES ═══════════ */
async function modalVersoes(){
  let r;
  try{ r = await api("/cadernos/api/paginas/" + PAG.uuid + "/versoes"); }
  catch(e){ toast(e.message, true); return; }
  const motivo = {sessao: "Sessão de edição", antes_excluir: "Antes de excluir",
                  antes_restaurar: "Antes de restaurar", importacao: "Importada do OneNote", reimportacao: "Reimportação"};
  const linhas = r.versoes.map(v =>
    '<tr><td>v' + v.versao + (v.versao === r.atual ? ' <span class="cd-pill">atual</span>' : "") + '</td><td>' + fmtData(v.criado_em, true) +
    '</td><td>' + esc(v.autor || "—") + '</td><td>' + esc(motivo[v.motivo] || v.motivo) + '</td>' +
    '<td><button class="btn btn-ghost btn-sm" data-ver="' + v.versao + '">Ver</button></td></tr>').join("");
  abrirModal("Versões da página", "Uma versão por sessão de edição, mais as de segurança.",
    r.versoes.length
      ? '<div class="tbl-wrap cd-tbl-modal"><table class="tbl"><thead><tr><th>Versão</th><th>Quando</th><th>Quem</th><th>Motivo</th><th></th></tr></thead><tbody>' + linhas + '</tbody></table></div><div id="cd-versao-previa"></div>'
      : '<div class="cd-dica">Ainda não há versões guardadas.</div>');
  el("modal-corpo").querySelectorAll("[data-ver]").forEach(b => b.addEventListener("click", () => verVersao(+b.dataset.ver, r.atual)));
}
async function verVersao(n, atual){
  const r = await api("/cadernos/api/paginas/" + PAG.uuid + "/versoes/" + n);
  const box = el("cd-versao-previa");
  box.innerHTML = '<div class="cd-versao-cab"><b>v' + n + ' — ' + esc(r.versao.titulo) + '</b>' +
    (pode("editor") && n !== atual && !EDITANDO ? ' <button class="btn btn-primary btn-sm" id="btn-restaurar-v">Restaurar esta versão</button>' : "") +
    '</div><div class="cd-versao-corpo ck-content">' + paraExibir(r.versao.html) + '</div>';
  const b = el("btn-restaurar-v");
  if(b) b.addEventListener("click", async () => {
    if(!confirm("Restaurar a v" + n + "? O estado atual fica guardado como versão.")) return;
    try{
      await api("/cadernos/api/paginas/" + PAG.uuid + "/versoes/" + n + "/restaurar", {method: "POST"});
      fecharModal();
      await abrirPagina(PAG.uuid);
      await recarregarArvore();
      toast("Versão restaurada");
    } catch(e){ toast(e.message, true); }
  });
}

/* ═══════════ ARQUIVOS ═══════════ */
let _uploadAlvo = null;     // {escopo, ref, pasta, aoTerminar}

function tabelaArquivos(itens, escopo, ref){
  if(!itens.length) return '<div class="cd-dica">Nenhum arquivo. Arraste para cá ou use “Enviar arquivos”.</div>';
  return '<div class="tbl-wrap"><table class="tbl cd-tbl-arq"><thead><tr><th>Arquivo</th><th>Pasta</th><th>Tamanho</th><th>Versão</th><th>Enviado</th><th title="Entra no zip da exportação">Exporta</th><th></th></tr></thead><tbody>' +
    itens.map(a => '<tr data-uuid="' + a.uuid + '">' +
      '<td><a href="#" data-baixar="' + a.uuid + '" data-nome="' + esc(a.nome) + '">' + esc(a.nome) + '</a>' +
        (a.no_texto ? ' <span class="cd-tag" title="Há um link para este arquivo no texto da página">no texto</span>' : "") +
        (a.descricao ? '<div class="cd-dica">' + esc(a.descricao) + '</div>' : "") + '</td>' +
      '<td>' + esc(a.pasta || "—") + '</td><td>' + fmtTam(a.tamanho) + '</td>' +
      '<td>v' + a.versao + (a.versoes > 1 ? ' <a href="#" data-historico="' + a.uuid + '">(' + a.versoes + ')</a>' : "") + '</td>' +
      '<td>' + esc(a.enviado_por_nome || "") + '<div class="cd-dica">' + fmtData(a.enviado_em, true) + '</div></td>' +
      '<td><input type="checkbox" data-exporta="' + a.uuid + '"' + (a.incluir_exportacao ? " checked" : "") + (pode("editor") ? "" : " disabled") + '></td>' +
      '<td class="cd-arq-acoes">' + (pode("editor") ? '<button class="cd-icone" data-menu="arquivo" data-uuid="' + a.uuid + '">⋯</button>' : "") + '</td></tr>').join("") +
    '</tbody></table></div>';
}

function ligarTabelaArquivos(box, itens, recarregar){
  box.querySelectorAll("[data-baixar]").forEach(a => a.addEventListener("click", e => {
    e.preventDefault();
    const it = itens.find(x => x.uuid === a.dataset.baixar);
    const inline = /\.(pdf|png|jpe?g|gif|webp)$/i.test(it.nome);
    window.open(imgSrc(it.uuid) + (inline ? "" : "&download=1"), "_blank");
  }));
  box.querySelectorAll("[data-historico]").forEach(a => a.addEventListener("click", e => {
    e.preventDefault(); historicoArquivo(a.dataset.historico);
  }));
  box.querySelectorAll("[data-exporta]").forEach(c => c.addEventListener("change", async () => {
    try{ await api("/cadernos/api/arquivos/" + c.dataset.exporta, {method: "PATCH", body: json({incluir_exportacao: c.checked})}); }
    catch(e){ toast(e.message, true); c.checked = !c.checked; }
  }));
  box.querySelectorAll("[data-menu=arquivo]").forEach(b => b.addEventListener("click", e => {
    e.stopPropagation();
    const it = itens.find(x => x.uuid === b.dataset.uuid);
    abrirMenu(b, [
      EDITANDO && EDITOR && {rotulo: "Inserir no texto (onde está o cursor)", acao: () => { inserirAnexo(EDITOR, it); fecharModal(); }},
      {rotulo: "Enviar nova versão", acao: () => novaVersaoArquivo(it, recarregar)},
      {rotulo: "Pasta e descrição", acao: () => editarArquivo(it, recarregar)},
      {rotulo: "Baixar", acao: () => window.open(imgSrc(it.uuid) + "&download=1", "_blank")},
      "-",
      {rotulo: "Excluir (todas as versões)", perigo: true, acao: async () => {
        if(!confirm('Mandar "' + it.nome + '" para a lixeira?')) return;
        try{ await api("/cadernos/api/arquivos/" + it.uuid, {method: "DELETE"}); recarregar(); toast("Arquivo na lixeira"); }
        catch(err){ toast(err.message, true); }
      }},
    ]);
  }));
}

function aceitarArraste(zona, alvo){
  zona.addEventListener("dragover", e => { if(pode("editor") && e.dataTransfer.types.includes("Files")){ e.preventDefault(); zona.classList.add("arrastando"); } });
  zona.addEventListener("dragleave", () => zona.classList.remove("arrastando"));
  zona.addEventListener("drop", e => {
    zona.classList.remove("arrastando");
    if(!pode("editor") || !e.dataTransfer.files.length) return;
    e.preventDefault();
    enviarArquivos(e.dataTransfer.files, alvo());
  });
}

async function carregarArquivosPagina(){
  const box = el("cd-arquivos-pagina");
  if(!PAG){ box.innerHTML = ""; return; }
  let r;
  try{ r = await api("/cadernos/api/arquivos?caderno=" + CAD.uuid + "&escopo=pagina&ref=" + PAG.uuid); }
  catch(e){ box.innerHTML = '<div class="cd-dica">' + esc(e.message) + '</div>'; return; }
  box.innerHTML = '<div class="cd-arq-cab"><b>📎 Arquivos da página</b> <span class="cd-dica">qualquer extensão · ' +
      (EDITANDO ? 'para pôr um arquivo no meio do texto, use 📎 na barra do editor ou arraste o arquivo para o texto'
                : 'para pôr um arquivo no meio do texto, clique em Editar e use 📎 na barra do editor') + '</span>' +
    (pode("editor") ? '<button class="btn btn-ghost btn-sm" id="btn-enviar-pag">Enviar arquivos</button>' : "") + '</div>' +
    tabelaArquivos(r.arquivos, "pagina", PAG.uuid);
  ligarTabelaArquivos(box, r.arquivos, carregarArquivosPagina);
  const b = el("btn-enviar-pag");
  if(b) b.addEventListener("click", () => escolherArquivos({escopo: "pagina", ref: PAG.uuid, aoTerminar: carregarArquivosPagina}));
}
aceitarArraste(el("cd-arquivos-pagina"), () => ({escopo: "pagina", ref: PAG.uuid, aoTerminar: carregarArquivosPagina}));

async function modalArquivos(escopo, ref, titulo){
  const recarregar = async () => {
    const r = await api("/cadernos/api/arquivos?caderno=" + CAD.uuid + "&escopo=" + escopo + "&ref=" + ref);
    const corpo = el("cd-modal-arq");
    if(!corpo) return;
    corpo.innerHTML = tabelaArquivos(r.arquivos, escopo, ref);
    ligarTabelaArquivos(corpo, r.arquivos, recarregar);
  };
  abrirModal(titulo, "Programas e arquivos de qualquer extensão. Marque “Exporta” para entrar no zip da exportação.",
    (pode("editor") ? '<div class="cd-linha"><input id="f-pasta" placeholder="Pasta (opcional), ex.: Programas" maxlength="120" style="flex:1"><button class="btn btn-primary btn-sm" id="btn-enviar-modal">Enviar arquivos</button></div>' : "") +
    '<div id="cd-modal-arq" class="cd-modal-arq"><div class="cd-dica">Carregando…</div></div>');
  const b = el("btn-enviar-modal");
  if(b) b.addEventListener("click", () => escolherArquivos({escopo, ref, pasta: el("f-pasta").value, aoTerminar: recarregar}));
  aceitarArraste(el("cd-modal-arq"), () => ({escopo, ref, pasta: el("f-pasta") ? el("f-pasta").value : "", aoTerminar: recarregar}));
  await recarregar();
}

function escolherArquivos(alvo){
  _uploadAlvo = alvo;
  const inp = el("cd-input-arquivo");
  inp.value = "";
  inp.click();
}
el("cd-input-arquivo").addEventListener("change", e => {
  if(e.target.files.length && _uploadAlvo) enviarArquivos(e.target.files, _uploadAlvo);
});

async function enviarArquivos(lista, alvo){
  const limite = (META.limite_arquivo_mb || 500) * 1048576;
  let ok = 0;
  for(const f of lista){
    if(f.size > limite){ toast(f.name + ": maior que " + META.limite_arquivo_mb + " MB", true); continue; }
    const fd = new FormData();
    fd.append("caderno", CAD.uuid);
    fd.append("escopo", alvo.escopo);
    fd.append("ref", alvo.ref);
    fd.append("pasta", alvo.pasta || "");
    fd.append("arquivo", f, f.name);
    status("Enviando " + f.name + " (" + fmtTam(f.size) + ")…");
    try{
      const r = await api("/cadernos/api/arquivos", {method: "POST", body: fd});
      ok++;
      if(alvo.aoEnviar) alvo.aoEnviar(r.arquivo);
    }
    catch(err){ toast(f.name + ": " + err.message, true); }
  }
  status(EDITANDO ? "Editando — salva sozinho" : "");
  if(ok) toast(ok + " arquivo(s) enviado(s)");
  if(alvo.aoTerminar) alvo.aoTerminar();
}

function novaVersaoArquivo(it, recarregar){
  const inp = el("cd-input-versao");
  inp.value = "";
  inp.onchange = async () => {
    if(!inp.files.length) return;
    const fd = new FormData();
    fd.append("arquivo", inp.files[0], inp.files[0].name);
    try{
      await api("/cadernos/api/arquivos/" + it.uuid + "/versao", {method: "POST", body: fd});
      toast("Nova versão enviada — a anterior continua no histórico");
      recarregar();
    } catch(e){ toast(e.message, true); }
  };
  inp.click();
}

function editarArquivo(it, recarregar){
  abrirModal("Arquivo", it.nome,
    '<label class="cd-campo">Pasta<input id="f-apasta" maxlength="120" value="' + esc(it.pasta || "") + '"></label>' +
    '<label class="cd-campo">Descrição<textarea id="f-adesc" rows="3">' + esc(it.descricao || "") + '</textarea></label>',
    async () => {
      await api("/cadernos/api/arquivos/" + it.uuid, {method: "PATCH", body: json({pasta: el("f-apasta").value, descricao: el("f-adesc").value})});
      recarregar();
    });
}

async function historicoArquivo(uuid){
  const r = await api("/cadernos/api/arquivos/" + uuid + "/versoes");
  abrirModal("Versões do arquivo", "A versão anterior continua baixável.",
    '<div class="tbl-wrap cd-tbl-modal"><table class="tbl"><thead><tr><th>Versão</th><th>Arquivo</th><th>Tamanho</th><th>Enviado</th></tr></thead><tbody>' +
    r.versoes.map(v => '<tr><td>v' + v.versao + (v.ativo ? ' <span class="cd-pill">atual</span>' : "") + '</td><td><a href="' + imgSrc(v.uuid) + '&download=1" target="_blank">' + esc(v.nome) + '</a></td><td>' + fmtTam(v.tamanho) + '</td><td>' + esc(v.enviado_por_nome || "") + ' · ' + fmtData(v.enviado_em, true) + '</td></tr>').join("") +
    '</tbody></table></div>');
}

/* ═══════════ LIXEIRA ═══════════ */
/* ═══════════ EXPORTAÇÃO (zip para a liderança) ═══════════
   1. escolher as páginas → 2. revisar os arquivos (o servidor diz o que vem
   marcado) → 3. gerar: o servidor monta o zip em segundo plano e o front acompanha
   o progresso; no fim o download começa sozinho. */
function secoesEmOrdem(){
  const saida = [];
  (function descer(pid){
    filhosDe(pid).forEach(n => { if(n.tipo === "secao") saida.push(n); else descer(n.id); });
  })(null);
  return saida;
}

function modalExportar(marcadas){
  const secoes = secoesEmOrdem().filter(s => paginasDaSecao(s.id).length);
  if(!secoes.length){ toast("O caderno não tem páginas para exportar", true); return; }
  const lista = secoes.map(s => {
    const pags = paginasDaSecao(s.id);
    return '<div class="cd-exp-secao"><label class="cd-exp-cab"><input type="checkbox" data-exp-secao="' + s.id + '"> <b>' + esc(s.nome) + '</b> <span class="cd-dica">' + pags.length + '</span></label>' +
      pags.map(p => '<label class="cd-exp-pag" style="padding-left:' + (22 + (p.nivel - 1) * 18) + 'px"><input type="checkbox" data-exp-pag="' + p.uuid + '" data-secao="' + s.id + '"' + (marcadas.has(p.uuid) ? " checked" : "") + '> ' +
        (p.tipo === "registro_teste" ? '<span class="cd-tag-teste" title="Registro de teste">T</span>' : "") + esc(p.titulo || "Sem título") + '</label>').join("") + '</div>';
  }).join("");
  abrirModal("Exportar para a liderança", "Passo 1 de 2 · Escolha as páginas. O zip leva o relatório em Word, as imagens no tamanho original, os arquivos que você confirmar no passo 2 e um LEIA-ME com a conferência de cada arquivo.",
    '<div class="cd-exp-topo"><label><input type="checkbox" id="exp-todas"> Todas as páginas</label><span class="cd-dica" id="exp-cont"></span>' +
    '<a href="#" id="exp-historico">Exportações anteriores</a></div><div class="cd-exp-lista">' + lista + '</div>',
    async () => {
      const uuids = [...document.querySelectorAll("[data-exp-pag]:checked")].map(c => c.dataset.expPag);
      if(!uuids.length){ toast("Marque ao menos uma página", true); return false; }
      await revisarExportacao(uuids);
      return false;
    }, "Revisar arquivos →");
  const atualizar = () => {
    const todas = [...document.querySelectorAll("[data-exp-pag]")];
    const n = todas.filter(c => c.checked).length;
    el("exp-cont").textContent = n + " de " + todas.length + " página(s)";
    el("exp-todas").checked = n === todas.length;
    el("exp-todas").indeterminate = n > 0 && n < todas.length;
    document.querySelectorAll("[data-exp-secao]").forEach(cs => {
      const dela = todas.filter(c => c.dataset.secao === cs.dataset.expSecao);
      const k = dela.filter(c => c.checked).length;
      cs.checked = k === dela.length;
      cs.indeterminate = k > 0 && k < dela.length;
    });
  };
  document.querySelectorAll("[data-exp-pag]").forEach(c => c.addEventListener("change", atualizar));
  document.querySelectorAll("[data-exp-secao]").forEach(cs => cs.addEventListener("change", () => {
    document.querySelectorAll('[data-exp-pag][data-secao="' + cs.dataset.expSecao + '"]').forEach(c => c.checked = cs.checked);
    atualizar();
  }));
  el("exp-todas").addEventListener("change", e => {
    document.querySelectorAll("[data-exp-pag]").forEach(c => c.checked = e.target.checked);
    atualizar();
  });
  el("exp-historico").addEventListener("click", e => { e.preventDefault(); modalHistoricoExportacoes(); });
  atualizar();
}

async function revisarExportacao(uuids){
  const r = await api("/cadernos/api/cadernos/" + CAD.uuid + "/exportacao/previa", {method: "POST", body: json({paginas: uuids})});
  const linhas = r.arquivos.map(a => '<tr><td><input type="checkbox" data-exp-arq="' + a.uuid + '" data-tam="' + a.tamanho + '"' + (a.marcado ? " checked" : "") + '></td>' +
    '<td>' + esc(a.nome) + (a.no_texto ? ' <span class="cd-tag" title="Citado no texto de uma página exportada">no texto</span>' : "") +
    '<div class="cd-dica" title="Caminho dentro do zip">' + esc(a.destino) + '</div></td>' +
    '<td>' + esc(a.origem_rotulo) + '<div class="cd-dica">' + esc(a.local) + '</div></td><td>' + fmtTam(a.tamanho) + '</td></tr>').join("");
  abrirModal("Exportar para a liderança", "Passo 2 de 2 · " + r.escopo + ". Confira os arquivos: vêm marcados os que têm “Exporta” ligado e os citados no texto das páginas.",
    '<div class="cd-exp-resumo"><span><b>' + r.paginas.length + '</b> página(s)</span><span><b>' + r.imagens + '</b> imagem(ns) · ' + fmtTam(r.tamanho_imagens) + '</span>' +
      '<span>Arquivos marcados: <b id="exp-n-arq">0</b> · <b id="exp-tam-arq">0 B</b></span><a href="#" id="exp-voltar">← Voltar às páginas</a></div>' +
    (r.arquivos.length
      ? '<div class="tbl-wrap cd-tbl-modal"><table class="tbl cd-tbl-arq"><thead><tr><th><input type="checkbox" id="exp-arq-todos" title="Marcar todos"></th><th>Arquivo</th><th>De onde</th><th>Tamanho</th></tr></thead><tbody>' + linhas + '</tbody></table></div>'
      : '<div class="cd-dica">Nenhum arquivo anexado a estas páginas, às suas seções ou ao caderno. O zip leva o relatório e as imagens.</div>'),
    async () => {
      const arquivos = [...document.querySelectorAll("[data-exp-arq]:checked")].map(c => c.dataset.expArq);
      const t = await api("/cadernos/api/cadernos/" + CAD.uuid + "/exportacoes", {method: "POST", body: json({paginas: uuids, arquivos})});
      acompanharExportacao(t.tarefa);
      return false;
    }, "Gerar zip");
  const soma = () => {
    const marc = [...document.querySelectorAll("[data-exp-arq]:checked")];
    el("exp-n-arq").textContent = marc.length;
    el("exp-tam-arq").textContent = fmtTam(marc.reduce((s, c) => s + (+c.dataset.tam || 0), 0));
  };
  document.querySelectorAll("[data-exp-arq]").forEach(c => c.addEventListener("change", soma));
  const todos = el("exp-arq-todos");
  if(todos) todos.addEventListener("change", e => { document.querySelectorAll("[data-exp-arq]").forEach(c => c.checked = e.target.checked); soma(); });
  el("exp-voltar").addEventListener("click", e => { e.preventDefault(); modalExportar(new Set(uuids)); });
  soma();
}

function acompanharExportacao(tarefa){
  abrirModal("Gerando o pacote…", "Pode fechar esta janela: o download começa sozinho quando o zip ficar pronto.",
    '<div class="cd-progresso"><div class="cd-progresso-barra" id="exp-barra"></div></div><div class="cd-dica" id="exp-etapa"></div>');
  const mostrar = t => barraDeProgresso(t, "exp-barra", "exp-etapa");
  const terminar = t => {
    if(t.estado === "erro"){
      toast("A exportação falhou: " + t.erro, true);
      if(el("exp-etapa")) el("exp-etapa").textContent = "Falhou: " + t.erro;
      return;
    }
    const e = t.resultado.exportacao;
    baixarExportacao(e.uuid);
    toast("Pacote pronto: " + e.nome_zip);
    if(el("exp-barra")){
      el("exp-barra").style.width = "100%";
      el("modal-titulo").textContent = "Pacote pronto";
      el("modal-sub").textContent = "";
      el("exp-etapa").innerHTML = '<b>' + esc(e.nome_zip) + '</b> · ' + fmtTam(e.tamanho) + ' · ' + e.paginas + ' página(s), ' + e.arquivos + ' arquivo(s) conferidos no LEIA-ME.<br>' +
        'O download começou. Se não começou, <a href="#" id="exp-baixar">clique aqui</a>. O zip fica disponível por um dia em <a href="#" id="exp-hist">Exportações anteriores</a>.';
      el("exp-baixar").addEventListener("click", ev => { ev.preventDefault(); baixarExportacao(e.uuid); });
      el("exp-hist").addEventListener("click", ev => { ev.preventDefault(); modalHistoricoExportacoes(); });
    }
  };
  seguirTarefa(tarefa, mostrar, terminar);
}

/* Consulta o progresso de uma tarefa do servidor (exportação, importação) até
   ela terminar. */
function seguirTarefa(tarefa, aoAtualizar, aoTerminar){
  aoAtualizar(tarefa);
  if(tarefa.estado !== "rodando"){ aoTerminar(tarefa); return; }
  const passo = async () => {
    let t;
    try{ t = (await api("/cadernos/api/tarefas/" + tarefa.id)).tarefa; }
    catch(e){ toast(e.message, true); return; }
    aoAtualizar(t);
    if(t.estado === "rodando") setTimeout(passo, 1200);
    else aoTerminar(t);
  };
  setTimeout(passo, 800);
}

function barraDeProgresso(t, idBarra, idEtapa){
  const pct = t.total ? Math.round(100 * t.feito / t.total) : 5;
  if(el(idBarra)) el(idBarra).style.width = Math.max(5, Math.min(100, pct)) + "%";
  if(el(idEtapa)) el(idEtapa).textContent = t.etapa || "";
}

/* ═══════════ IMPORTAÇÃO DO ONENOTE ═══════════
   O OneNote só se deixa ler na máquina de quem o tem aberto. Por isso: 1. a
   pessoa baixa o assistente (um .cmd) e roda lá; 2. o assistente acha o caderno
   baixado do SharePoint, extrai e MANDA o .zip para cá sozinho, com um ticket de
   uso único, enquanto esta janela mostra a etapa; 3. a janela abre o resumo, e
   ao confirmar o servidor grava em segundo plano. Enviar o .zip à mão continua
   valendo, para quando a rede ou o antivírus barrarem o envio do assistente.

   O ticket fica no sessionStorage: fechar a janela ou recarregar a página não
   perde o caderno que o assistente está mandando. */
let IMP = null;          // {id}: o ticket desta importação, até o pacote chegar
let IMP_VOLTA = 0;       // cada acompanhamento tem um número; o antigo para sozinho

function modalImportar(){
  abrirModal("Importar do OneNote", "Traz um caderno inteiro: seções, páginas, imagens, tabelas com as cores, anexos e os arquivos originais do OneNote.",
    '<ol class="cd-passos">' +
      '<li><b>Baixe o caderno do SharePoint.</b> Na pasta do caderno, use <i>Baixar</i>: vem um .zip na pasta Downloads. ' +
        '<span class="cd-dica">Aberto direto do SharePoint, o OneNote não entrega todas as imagens.</span></li>' +
      '<li><b>Rode o assistente</b> no computador que tem o OneNote.' +
        '<div class="cd-imp-acao"><button type="button" class="btn btn-primary btn-sm" id="imp-assistente">Baixar o assistente</button></div>' +
        'Dois cliques no arquivo baixado. Ele acha o caderno do passo 1 (é só apertar Enter), extrai e manda para cá sozinho. ' +
        '<span class="cd-dica">Se o Windows avisar que protegeu o computador, use “Mais informações › Executar assim mesmo”.</span>' +
        '<div class="cd-imp-status" id="imp-status" hidden><div class="cd-imp-etapa" id="imp-status-txt"></div>' +
          '<div class="cd-dica" id="imp-status-dica" hidden></div>' +
          '<div class="cd-progresso" id="imp-status-prog" hidden><div class="cd-progresso-barra" id="imp-status-barra"></div></div></div></li>' +
      '<li><b>Confira e confirme.</b> O resumo aparece aqui assim que o caderno chegar.</li>' +
    '</ol>' +
    '<details class="cd-imp-manual" id="imp-manual"><summary>Prefere enviar o .zip à mão?</summary>' +
      '<label class="cd-imp-zona" id="imp-zona"><input type="file" id="imp-arquivo" accept=".zip" hidden>' +
      '<span id="imp-zona-txt">Clique para escolher ou arraste o .zip que o assistente deixou na Área de Trabalho</span></label>' +
      '<div class="cd-progresso" id="imp-prog" hidden><div class="cd-progresso-barra" id="imp-barra"></div></div>' +
      '<div class="cd-dica" id="imp-etapa"></div>' +
    '</details>');
  el("imp-assistente").addEventListener("click", baixarAssistente);
  el("imp-arquivo").addEventListener("change", e => { if(e.target.files[0]) enviarPacote(e.target.files[0]); });
  const zona = el("imp-zona");
  zona.addEventListener("dragover", e => { e.preventDefault(); zona.classList.add("arrastando"); });
  zona.addEventListener("dragleave", () => zona.classList.remove("arrastando"));
  zona.addEventListener("drop", e => {
    e.preventDefault();
    zona.classList.remove("arrastando");
    if(e.dataTransfer.files[0]) enviarPacote(e.dataTransfer.files[0]);
  });
  _modalAoFechar = () => IMP_VOLTA++;
  if(!IMP){
    const salvo = sessionStorage.getItem("cd_imp_ticket");
    if(salvo) IMP = {id: salvo};
  }
  if(IMP){
    el("imp-assistente").textContent = "Baixar o assistente de novo";
    acompanharAssistente();
  }
}

function esquecerTicket(){
  IMP = null;
  sessionStorage.removeItem("cd_imp_ticket");
}

async function baixarAssistente(){
  if(!IMP){
    try{
      const r = await api("/cadernos/api/importacoes/tickets", {method: "POST", body: json({area: AREA})});
      IMP = {id: r.id};
      sessionStorage.setItem("cd_imp_ticket", r.id);
    } catch(e){ toast(e.message, true); return; }
  }
  // Navegação direta: é um download, a página fica onde está.
  window.location.href = "/cadernos/api/onenote/assistente?ticket=" + IMP.id + "&token=" + encodeURIComponent(getToken());
  el("imp-assistente").textContent = "Baixar o assistente de novo";
  acompanharAssistente();
}

/* Consulta o ticket a cada 1,5 s enquanto a janela está aberta. Quando o
   pacote chega, a própria janela vira a conferência. */
function acompanharAssistente(){
  const volta = ++IMP_VOLTA;
  const vale = () => volta === IMP_VOLTA && IMP && el("imp-status");
  const passo = async () => {
    if(!vale()) return;
    let r = null;
    try{ r = await api("/cadernos/api/importacoes/tickets/" + IMP.id); }
    catch(e){
      if(!vale()) return;
      if(e.status === 404){
        esquecerTicket();
        mostrarAssistente({estado: "erro", erro: e.message, expirou: true});
        el("imp-assistente").textContent = "Baixar o assistente";
        return;
      }
      // Falha de rede: tenta de novo na próxima volta.
    }
    if(!vale()) return;
    if(r && r.estado === "recebido" && r.pacote){
      esquecerTicket();
      confirmarImportacao(r.pacote);
      return;
    }
    if(r) mostrarAssistente(r);
    setTimeout(passo, 1500);
  };
  passo();
}

function frase(s){ s = (s || "").trim(); return /[.!?…]$/.test(s) ? s : s + "."; }

function mostrarAssistente(r){
  const box = el("imp-status");
  if(!box) return;
  box.hidden = false;
  const erro = r.estado === "erro";
  box.classList.toggle("erro", erro);
  let txt, dica = "";
  if(erro){
    txt = frase(r.erro || "O assistente parou");
    if(!r.expirou){
      dica = "O mesmo arquivo baixado serve para tentar de novo. Ou envie o .zip à mão, abaixo.";
      el("imp-manual").open = true;
    }
  }
  else if(r.estado === "aguardando") txt = "Esperando o assistente. Abra o arquivo baixado (dois cliques).";
  else if(r.estado === "recebendo") txt = "O caderno chegou. Conferindo o pacote…";
  else txt = r.etapa || "O assistente está trabalhando…";
  el("imp-status-txt").textContent = txt;
  el("imp-status-dica").textContent = dica;
  el("imp-status-dica").hidden = !dica;
  const barra = !erro && r.total > 0;
  el("imp-status-prog").hidden = !barra;
  if(barra) barraDeProgresso({feito: r.feito, total: r.total}, "imp-status-barra", null);
}

/* Envio com XMLHttpRequest: o fetch não informa o progresso do upload, e o
   pacote de um caderno passa fácil de 100 MB. */
function enviarComProgresso(url, fd, aoProgredir){
  return new Promise((ok, falha) => {
    const x = new XMLHttpRequest();
    x.open("POST", url);
    x.setRequestHeader("Authorization", "Bearer " + getToken());
    x.upload.onprogress = e => { if(e.lengthComputable) aoProgredir(e.loaded, e.total); };
    x.onload = () => {
      let corpo = {};
      try{ corpo = JSON.parse(x.responseText || "{}"); } catch(e){}
      if(x.status >= 200 && x.status < 300) ok(corpo);
      else falha(new Error(corpo.erro || (x.status === 413 ? "Arquivo grande demais para o servidor" : "Falha no envio (HTTP " + x.status + ")")));
    };
    x.onerror = () => falha(new Error("Falha de rede no envio"));
    x.send(fd);
  });
}

async function enviarPacote(arquivo){
  if(!/\.zip$/i.test(arquivo.name)){ toast("Envie o .zip gerado pelo assistente", true); return; }
  el("imp-prog").hidden = false;
  el("imp-zona-txt").textContent = arquivo.name + " (" + fmtTam(arquivo.size) + ")";
  const fd = new FormData();
  fd.append("area", AREA);
  fd.append("pacote", arquivo, arquivo.name);
  let r;
  try{
    r = await enviarComProgresso("/cadernos/api/importacoes", fd, (feito, total) =>
      barraDeProgresso({feito, total, etapa: "Enviando… " + fmtTam(feito) + " de " + fmtTam(total)}, "imp-barra", "imp-etapa"));
  } catch(e){
    el("imp-etapa").textContent = e.message;
    toast(e.message, true);
    return;
  }
  esquecerTicket();             // foi à mão: o assistente desta rodada não serve mais
  confirmarImportacao(r);
}

function confirmarImportacao(r){
  const s = r.resumo, ex = r.existente;
  const avisos = (s.avisos || []);
  let corpo = '<div class="cd-imp-resumo"><div class="cd-imp-nome">' + esc(s.caderno) + '</div>' +
    '<div class="cd-dica">Extraído em ' + fmtData(s.extraido_em, true) + (s.maquina ? ' no computador ' + esc(s.maquina) : "") + '</div>' +
    '<div class="cd-imp-numeros">' +
      ['secoes|seções', 'paginas|páginas', 'imagens|imagens', 'anexos|anexos', 'originais|arquivos originais', 'paginas_com_tinta|com desenho à mão']
        .map(x => { const [k, rot] = x.split("|"); return '<span><b>' + (s[k] || 0) + '</b> ' + rot + '</span>'; }).join("") +
    '</div></div>';
  if(s.aberto_do_sharepoint)
    corpo += '<div class="cd-aviso">⚠ O caderno foi extraído aberto direto do SharePoint: pode faltar imagem. O recomendado é extrair de uma cópia baixada (passo 1).</div>';
  if(avisos.length)
    corpo += '<details class="cd-imp-avisos"><summary>' + avisos.length + ' aviso(s) da extração</summary><ul>' + avisos.slice(0, 50).map(a => '<li>' + esc(a) + '</li>').join("") + '</ul></details>';
  let pode = true;
  if(ex){
    pode = ex.pode_atualizar;
    corpo += '<div class="cd-aviso">Este caderno já foi importado: <b>' + esc(ex.nome) + '</b>. ' +
      (pode ? 'Importar de novo atualiza as páginas que ninguém editou no DocTrack e acrescenta as novas; as editadas ficam como estão.'
            : 'Só um editor desse caderno pode importá-lo de novo.') + '</div>';
  } else {
    corpo += '<label class="cd-campo">Nome no DocTrack<input id="imp-nome" maxlength="200" value="' + esc(s.caderno) + '"></label>' +
      '<div class="cd-dica">Você será o dono. A área inteira poderá editar (dá para mudar depois em ⋯ › Renomear / cor / acesso).</div>';
  }
  let iniciou = false;
  abrirModal("Importar do OneNote", "Confira antes de gravar.", corpo, pode ? async () => {
    const nome = el("imp-nome") ? el("imp-nome").value.trim() : "";
    const t = await api("/cadernos/api/importacoes/" + r.id + "/iniciar", {method: "POST", body: json({nome})});
    iniciou = true;
    acompanharImportacao(t.tarefa);
    return false;
  } : null, ex ? "Atualizar o caderno" : "Importar");
  _modalAoFechar = () => { if(!iniciou) api("/cadernos/api/importacoes/" + r.id, {method: "DELETE"}).catch(() => {}); };
}

function acompanharImportacao(tarefa){
  abrirModal("Importando…", "Pode fechar esta janela: a importação continua no servidor e o caderno aparece na lista quando terminar.",
    '<div class="cd-progresso"><div class="cd-progresso-barra" id="imp-barra"></div></div><div class="cd-dica" id="imp-etapa"></div>');
  seguirTarefa(tarefa, t => barraDeProgresso(t, "imp-barra", "imp-etapa"), async t => {
    if(t.estado === "erro"){
      toast("A importação falhou: " + t.erro, true);
      if(el("imp-etapa")) el("imp-etapa").textContent = "Falhou: " + t.erro;
      return;
    }
    const rel = t.resultado.relatorio, c = rel.contagens;
    await carregarCadernos();
    toast("Caderno importado: " + rel.caderno.nome);
    if(!el("imp-barra")) return;
    const autores = Object.entries(rel.autores || {});
    el("modal-titulo").textContent = "Caderno importado";
    el("modal-sub").textContent = rel.caderno.nome;
    el("modal-corpo").innerHTML = '<div class="cd-imp-numeros">' +
        '<span><b>' + rel.criadas + '</b> páginas novas</span>' +
        (rel.atualizadas ? '<span><b>' + rel.atualizadas + '</b> atualizadas</span>' : "") +
        (rel.puladas_editadas_no_doctrack.length ? '<span><b>' + rel.puladas_editadas_no_doctrack.length + '</b> puladas (editadas no DocTrack)</span>' : "") +
        '<span><b>' + (c.imagens || 0) + '</b> imagens</span><span><b>' + (c.tabelas || 0) + '</b> tabelas</span>' +
        '<span><b>' + (c.registros_de_teste || 0) + '</b> registros de teste</span>' +
        '<span><b>' + (c.anexos_importados || 0) + '</b> anexos' + (c.anexos_faltando ? ' (' + c.anexos_faltando + ' faltando)' : "") + '</span>' +
        '<span><b>' + (c.originais_onenote || 0) + '</b> arquivos originais</span></div>' +
      (autores.length ? '<div class="cd-imp-autores"><b>Autores do OneNote</b><ul>' + autores.map(([n, u]) =>
        '<li>' + esc(n) + ' → ' + (u ? esc(u) : '<span class="cd-dica">sem usuário no DocTrack (fica como texto)</span>') + '</li>').join("") + '</ul></div>' : "") +
      (rel.avisos.length ? '<details class="cd-imp-avisos"><summary>' + rel.avisos.length + ' aviso(s)</summary><ul>' +
        rel.avisos.slice(0, 80).map(a => '<li>' + esc(a) + '</li>').join("") + '</ul></details>' : "") +
      '<div style="margin-top:12px"><button class="btn btn-primary btn-sm" id="imp-abrir">Abrir o caderno</button></div>';
    el("imp-abrir").addEventListener("click", async () => { fecharModal(); await abrirCaderno(rel.caderno.uuid); });
  });
}

function baixarExportacao(uuid){
  // Navegação direta: o arquivo pode ter centenas de MB e não deve passar pela memória da página.
  window.location.href = "/cadernos/api/exportacoes/" + uuid + "/zip?token=" + encodeURIComponent(getToken());
}

async function modalHistoricoExportacoes(){
  const r = await api("/cadernos/api/cadernos/" + CAD.uuid + "/exportacoes");
  const linhas = r.exportacoes.map(e => '<tr><td>' + fmtData(e.criado_em, true) + '</td><td>' + esc(e.criado_por_nome || "—") + '</td>' +
    '<td>' + esc(e.escopo) + '<div class="cd-dica">' + e.paginas + ' página(s) · ' + e.arquivos + ' arquivo(s)</div></td><td>' + fmtTam(e.tamanho) + '</td>' +
    '<td>' + (!pode("editor") ? '' : e.disponivel ? '<a href="#" data-baixar-exp="' + e.uuid + '">Baixar</a>' : '<span class="cd-dica" title="O zip fica disponível por um dia; o registro do que foi enviado continua aqui">expirado</span>') + '</td></tr>').join("");
  abrirModal("Exportações anteriores", "O que já saiu deste caderno, por quem e quando. O registro guarda a versão de cada página e o SHA-256 de cada arquivo.",
    r.exportacoes.length
      ? '<div class="tbl-wrap cd-tbl-modal"><table class="tbl"><thead><tr><th>Quando</th><th>Por</th><th>Escopo</th><th>Tamanho</th><th></th></tr></thead><tbody>' + linhas + '</tbody></table></div>'
      : '<div class="cd-dica">Nenhuma exportação ainda.</div>');
  document.querySelectorAll("[data-baixar-exp]").forEach(a => a.addEventListener("click", e => { e.preventDefault(); baixarExportacao(a.dataset.baixarExp); }));
}

async function modalLixeira(){
  let r;
  try{ r = await api("/cadernos/api/lixeira?caderno=" + CAD.uuid); }
  catch(e){ toast(e.message, true); return; }
  const tipo = {pagina: "Página", secao: "Seção", grupo: "Grupo", arquivo: "Arquivo"};
  abrirModal("Lixeira do caderno", "Itens ficam " + r.dias + " dias e depois são apagados de vez.",
    r.itens.length
      ? '<div class="tbl-wrap cd-tbl-modal"><table class="tbl"><thead><tr><th>Item</th><th>Tipo</th><th>Excluído</th><th>Apagado em</th><th></th></tr></thead><tbody>' +
        r.itens.map(it => '<tr><td>' + esc(it.nome) + '</td><td>' + tipo[it.tipo] + '</td><td>' + esc(it.por) + ' · ' + fmtData(it.excluido_em, true) +
          '</td><td>' + fmtData(it.expira_em) + '</td><td><button class="btn btn-ghost btn-sm" data-rest="' + it.tipo + ':' + it.uuid + '">Restaurar</button></td></tr>').join("") +
        '</tbody></table></div>'
      : '<div class="cd-dica">A lixeira está vazia.</div>');
  el("modal-corpo").querySelectorAll("[data-rest]").forEach(b => b.addEventListener("click", async () => {
    const [t, u] = b.dataset.rest.split(":");
    const rota = t === "pagina" ? "paginas" : t === "arquivo" ? "arquivos" : "nos";
    try{
      await api("/cadernos/api/" + rota + "/" + u + "/restaurar", {method: "POST"});
      b.closest("tr").remove();
      await recarregarArvore();
      if(PAG) carregarArquivosPagina();
      toast("Restaurado");
    } catch(e){ toast(e.message, true); }
  }));
}

/* ═══════════ BUSCA ═══════════ */
let T_BUSCA = null;
el("cd-busca").addEventListener("input", () => {
  clearTimeout(T_BUSCA);
  T_BUSCA = setTimeout(buscar, 300);
});
el("cd-busca").addEventListener("focus", () => { if(el("cd-busca-res").innerHTML) el("cd-busca-res").hidden = false; });
document.addEventListener("click", e => { if(!e.target.closest(".cd-busca")) el("cd-busca-res").hidden = true; });

async function buscar(){
  const q = el("cd-busca").value.trim();
  const box = el("cd-busca-res");
  if(q.length < 2){ box.hidden = true; box.innerHTML = ""; return; }
  try{
    const r = await api("/cadernos/api/busca?area=" + AREA + "&q=" + encodeURIComponent(q));
    box.innerHTML = r.resultados.length
      ? r.resultados.map(x => '<button type="button" class="cd-busca-item" data-c="' + x.caderno.uuid + '" data-p="' + x.uuid + '">' +
          '<b>' + esc(x.titulo) + '</b><span>' + esc(x.caderno.nome) + ' › ' + esc(x.secao) + '</span><small>' + esc(x.trecho) + '</small></button>').join("")
      : '<div class="cd-dica" style="padding:10px">Nada encontrado.</div>';
    box.hidden = false;
    box.querySelectorAll(".cd-busca-item").forEach(b => b.addEventListener("click", async () => {
      box.hidden = true;
      if(!CAD || CAD.uuid !== b.dataset.c) await abrirCaderno(b.dataset.c, b.dataset.p);
      else await abrirPagina(b.dataset.p);
    }));
  } catch(e){ toast(e.message, true); }
}

/* ═══════════ BOTÕES ═══════════ */
el("btn-novo-caderno").addEventListener("click", novoCaderno);
el("btn-importar-onenote").addEventListener("click", modalImportar);
el("btn-menu-caderno").setAttribute("data-menu", "caderno");
el("btn-menu-caderno").addEventListener("click", e => { e.stopPropagation(); menuCaderno(e.currentTarget); });
el("btn-nova-secao").addEventListener("click", () => novoNo("secao"));
el("btn-novo-grupo").addEventListener("click", () => novoNo("grupo"));
el("btn-lixeira").addEventListener("click", modalLixeira);
el("btn-editar").addEventListener("click", editar);
el("btn-concluir").addEventListener("click", concluir);
el("btn-versoes").addEventListener("click", modalVersoes);
el("btn-exportar").addEventListener("click", () => modalExportar(new Set([PAG.uuid])));
el("btn-link").addEventListener("click", async () => {
  const url = location.origin + "/cadernos/?area=" + AREA + "#c=" + CAD.uuid + "&p=" + PAG.uuid;
  try{ await navigator.clipboard.writeText(url); toast("Link copiado"); }
  catch(e){ prompt("Copie o link:", url); }
});
el("btn-menu-pagina").setAttribute("data-menu", "pagina-topo");
el("btn-menu-pagina").addEventListener("click", e => {
  e.stopPropagation();
  const p = ARV.paginas.find(x => x.uuid === PAG.uuid);
  const secao = ARV.nos.find(n => n.id === p.secao_id);
  abrirMenu(e.currentTarget, [
    {rotulo: "Data da página…", acao: editarDataPagina},
    pode("editor") && {rotulo: "Nova subpágina", acao: () => novaPagina(secao.uuid, {subpagina_de: PAG.uuid})},
    pode("editor") && {rotulo: "Mover para outra seção…", acao: () => moverPaginaPara(p)},
    pode("editor") && {rotulo: "Exportar esta página (zip)…", acao: () => modalExportar(new Set([PAG.uuid]))},
    {rotulo: "Imprimir / PDF", acao: () => window.print()},
    pode("editor") && "-",
    pode("editor") && {rotulo: "Excluir página", perigo: true, acao: () => excluirPagina(p)},
  ]);
});

function editarDataPagina(){
  if(!pode("editor")) return;
  const v = PAG.data_pagina ? PAG.data_pagina.slice(0, 16) : "";
  abrirModal("Data da página", "A data e hora que aparecem sob o título — no caderno de bancada, é o registro.",
    '<label class="cd-campo">Data e hora<input type="datetime-local" id="f-data" value="' + esc(v) + '"></label>', async () => {
      await api("/cadernos/api/paginas/" + PAG.uuid, {method: "PATCH", body: json({data_pagina: el("f-data").value})});
      if(!EDITANDO) await abrirPagina(PAG.uuid);
    });
}

/* ═══════════ BOOT ═══════════
   style.css esconde #app por padrão e cada módulo o revela depois de conferir a
   sessão — sem isto a página carrega inteira e fica invisível (commit f7b65e7). */
async function boot(){
  if(!token()){ window.location.href = "/"; return; }
  try{ META = await api("/cadernos/api/meta?area=" + AREA); }
  catch(e){
    if(e.status === 403){ window.location.href = "/hub"; return; }
    document.getElementById("app").style.display = "block";
    toast(e.message, true);
    return;
  }
  document.getElementById("app").style.display = "block";
  sessionStorage.setItem("dt_area", AREA);

  const u = userObj();
  const nome = META.eu.nome || u.nome || "—";
  el("nav-name").textContent = nome;
  el("nav-role").textContent = (META.eu.role || "").toUpperCase();
  el("nav-avatar").textContent = nome.charAt(0).toUpperCase();
  if(el("top-avatar")) el("top-avatar").textContent = nome.charAt(0).toUpperCase();
  el("cd-brand").textContent = "CADERNOS · " + META.area.nome.toUpperCase();
  el("cd-bc-area").textContent = "Cadernos · " + META.area.nome;
  el("cd-voltar-area").href = AREA === "pdr" ? "/pdr/" : "/hub/" + AREA;
  el("cd-voltar-rotulo").textContent = AREA === "pdr" ? "Voltar ao PDR" : "Voltar à área";
  el("btn-novo-caderno").hidden = !META.pode_criar;
  el("btn-importar-onenote").hidden = !META.pode_criar;
  if(typeof initTheme === "function") initTheme();

  await carregarCadernos();
  const h = new URLSearchParams(location.hash.slice(1));
  const alvo = h.get("c") || localStorage.getItem("cd_ultimo_" + AREA);
  if(alvo && CADERNOS.some(c => c.uuid === alvo)) await abrirCaderno(alvo, h.get("p"));
  else if(CADERNOS.length) await abrirCaderno(CADERNOS[0].uuid);
}

if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
