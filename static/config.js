// ═══════════════════════════════════════════════════════════════════════════
//  CONFIG.JS — Módulo de Configurações (Auditoria + Sistema)
//  Acesso restrito a gestor ou superior. Auditoria cobre sistema e projetos.
// ═══════════════════════════════════════════════════════════════════════════
const API='/api';
let currentUser={name:'Admin',email:'admin@pde.com',role:'admin',initials:'A'};
let _allUsers=[],_filterTimer=null,_codigoAtivacaoAtual='';

// esc, norm, tema e token vêm de static/common.js (carregado antes deste arquivo).

// ═══ AUTH / FETCH ═══
function authHeader(){return{'Content-Type':'application/json','Authorization':'Bearer '+getToken()}}
async function apiFetch(url,opts={}){
  try{
    let res=await fetch(API+url,{headers:authHeader(),...opts});
    if(res.status===401){
      if(window.DT_AUTH&&await window.DT_AUTH.refresh()){
        res=await fetch(API+url,{headers:authHeader(),...opts});
      }
      if(res.status===401){ if(window.DT_AUTH)window.DT_AUTH.gotoLogin(true); else doLogout(); return null; }
    }
    return res;
  }catch(e){return null}
}
async function doLogout(){
  try{await apiFetch('/auth/logout',{method:'POST'})}catch(e){}
  clearToken();
  window.location.href='/';
}

// ═══ NAVEGAÇÃO ENTRE SUB-PÁGINAS ═══
const PAGE_LABELS={audit:'Audit Log',users:'Usuários',settings:'Sistema'};
function navigate(page){
  document.querySelectorAll('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.page===page));
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  const pg=document.getElementById('page-'+page);
  if(pg)pg.classList.add('active');
  const bc=document.getElementById('breadcrumb-current');
  if(bc)bc.textContent=PAGE_LABELS[page]||page;
  if(page==='audit')renderAudit();
  if(page==='users')renderUsers();
}
document.querySelectorAll('.nav-item[data-page]').forEach(el=>el.addEventListener('click',()=>navigate(el.dataset.page)));

// ═══ AUDITORIA (sistema + projetos) ═══
// Classifica cada registro por módulo de origem a partir da ação/entidade/campo.
function _auditModule(l){
  const acao=(l.acao||'').toUpperCase();
  const ent=(l.entidade||'');
  const entL=norm(ent);
  const campo=norm(l.campo);
  // Projetos: ações/entidades de projetos, entregáveis, mensais e modelos
  if(/PROJETO|ENTREGAVEL|MENSAL|MODELO/.test(acao)) return 'projetos';
  if(/^projeto[:\s]/i.test(ent) || ent.includes('·') || entL.includes('modelo') || entL.includes('entregavel')) return 'projetos';
  // Sistema: autenticação e administração de usuários
  if(/LOGIN|LOGOUT|PASSWORD|SENHA|RESET|TOKEN|USER|USUARIO|ROLE|PERMISSAO|ATIVACAO|CONVITE/.test(acao)) return 'sistema';
  if(campo==='role' || entL.includes('usuario') || entL.includes('user') || entL.includes('auth')) return 'sistema';
  if(/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(ent.trim())) return 'sistema'; // entidade = e-mail puro (gestão de usuário)
  // Documentos (padrão)
  return 'documentos';
}
// Preenche o filtro de ações com os valores realmente presentes nos registros.
function _syncAuditActions(logs){
  const sel=document.getElementById('audit-filter-action');
  if(!sel)return;
  const atual=sel.value;
  const acoes=[...new Set(logs.map(l=>l.acao).filter(Boolean))].sort();
  sel.innerHTML='<option value="">Todas as ações</option>'+acoes.map(a=>`<option${a===atual?' selected':''}>${esc(a)}</option>`).join('');
  sel.value=atual;
}
const _MOD_BADGE={
  sistema:{label:'Sistema',color:'var(--purple)'},
  documentos:{label:'Documentos',color:'var(--cyan)'},
  projetos:{label:'Projetos',color:'var(--green)'}
};
function _auditDateParams(){
  const di=(document.getElementById('audit-date-inicio')||{}).value||'';
  const df=(document.getElementById('audit-date-fim')||{}).value||'';
  const p=new URLSearchParams();
  if(di)p.set('inicio',di);
  if(df)p.set('fim',df);
  return p;
}
function limparAuditDatas(){
  const a=document.getElementById('audit-date-inicio'),b=document.getElementById('audit-date-fim');
  if(a)a.value='';if(b)b.value='';
  filterAudit();
}
async function renderAudit(){filterAudit()}
async function filterAudit(){
  let logs=[];
  const qs=_auditDateParams().toString();
  try{const res=await apiFetch('/audit'+(qs?('?'+qs):''));if(res&&res.ok)logs=await res.json()}catch(e){}
  _syncAuditActions(logs);
  const q=(document.getElementById('audit-search').value||'').toLowerCase();
  const a=document.getElementById('audit-filter-action').value;
  const mod=(document.getElementById('audit-filter-module')||{}).value||'';
  if(q)logs=logs.filter(l=>(l.usuario||'').toLowerCase().includes(q)||(l.entidade||'').toLowerCase().includes(q)||(l.campo||'').toLowerCase().includes(q));
  if(a)logs=logs.filter(l=>l.acao===a);
  if(mod)logs=logs.filter(l=>_auditModule(l)===mod);
  document.getElementById('audit-list').innerHTML=logs.length?logs.map(l=>{
    let actColor=l.acao==='DELETE'?'var(--red)':l.acao==='CREATE'?'var(--green)':l.acao==='UPDATE'?'var(--cyan)':'var(--purple)';
    const m=_MOD_BADGE[_auditModule(l)];
    return `<div class="audit-item">
      <div class="audit-user">${esc(l.usuario)}</div>
      <div class="audit-action"><span class="audit-mod-badge" style="color:${m.color};border-color:${m.color}">${m.label}</span> <span style="color:${actColor};font-family:var(--font-mono);font-size:10px">[${esc(l.acao)}]</span> <strong>${esc(l.entidade)}</strong>
        ${l.campo&&l.campo!=='—'?`<span style="color:var(--t3);font-size:10px"> (${esc(l.campo)}) </span>`:''}
        ${l.valor_antigo?' <span class="old">'+esc(l.valor_antigo)+'</span> → <span class="new">'+esc(l.valor_novo)+'</span>':l.valor_novo?' '+esc(l.valor_novo):''}
      </div><div class="audit-time">${esc(l.timestamp)}</div>
    </div>`}).join(''):'<div style="text-align:center;padding:28px;color:var(--t4);font-size:12px">Nenhum registro</div>';
}
function exportAudit() {
    const p=_auditDateParams();
    p.set('token', getToken());
    window.open(API + '/export/audit?' + p.toString(), '_blank');
}

// ═══ USUÁRIOS ═══
async function renderUsers(){
  document.getElementById('users-list').innerHTML='<div class="loading-state"><div class="spinner"></div>Carregando...</div>';
  try{const res=await apiFetch('/users');if(!res||!res.ok){document.getElementById('users-list').innerHTML='<div style="color:var(--t3);padding:16px;font-size:12px">Sem permissão.</div>';return}_allUsers=await res.json();renderUserCards(_allUsers)}
  catch(e){_allUsers=[];renderUserCards([])}
}
function renderUserCards(users){
  const rh={admin:'<span class="role-admin">Admin</span>',gestor:'<span class="role-gestor">Gestor</span>',tecnico:'<span class="role-tecnico">Técnico</span>',leitura:'<span class="role-leitura">Leitura</span>'};
  const canEdit=currentUser.role==='admin';
  const showInactive=document.getElementById('users-show-inactive')?.checked;
  const lista=(users||[]).filter(u=>showInactive||u.ativo);
  const inativos=(users||[]).filter(u=>!u.ativo).length;
  document.getElementById('users-list').innerHTML=lista.map(u=>`
    <div class="user-card" style="${!u.ativo?'opacity:.45':''}">
      <div class="uc-avatar">${esc((u.nome||'?').split(' ').map(w=>w[0]).join('').substring(0,2).toUpperCase())}</div>
      <div style="flex:1;min-width:0"><div class="uc-name">${esc(u.nome)}${!u.ativo?' <span style="font-size:10px;color:var(--red)">(inativo)</span>':''}${u.precisa_definir_senha?' <span style="font-size:10px;color:var(--amber,#f59e0b)">(senha pendente)</span>':''}</div><div class="uc-email">${esc(u.email)}</div></div>
      <div>${rh[u.role]||esc(u.role)}${(u.areas||[]).map(a=>` <span class="role-tecnico" title="Acessa a área ${esc(a)}" style="margin-left:4px">${esc(String(a).toUpperCase())}</span>`).join('')}</div>
      <div style="text-align:right;min-width:90px"><div style="font-size:10px;color:var(--t4);font-family:var(--font-mono)">último</div><div style="font-size:11px;color:var(--t3);font-family:var(--font-mono)">${esc(u.ultimo_login||'—')}</div></div>
      ${canEdit?`<div class="uc-actions"><button class="btn btn-ghost btn-sm" type="button" data-action="edit-user" data-id="${u.id}" aria-label="Editar usuário">Editar</button>${u.ativo?`<button class="btn btn-ghost btn-sm" type="button" data-action="reset-user" data-id="${u.id}" data-name="${esc(u.nome)}" data-email="${esc(u.email)}" aria-label="Resetar senha">Resetar senha</button>`:''}${u.ativo&&u.email!==currentUser.email?`<button class="btn btn-ghost btn-sm" type="button" data-action="delete-user" data-id="${u.id}" data-name="${esc(u.nome)}" aria-label="Desativar usuário">Desativar</button>`:''}${u.email!==currentUser.email?`<button class="btn btn-danger btn-sm" type="button" data-action="hard-delete-user" data-id="${u.id}" data-name="${esc(u.nome)}" aria-label="Excluir usuário permanentemente">Excluir</button>`:''}</div>`:''}
    </div>`).join('')||`<div style="color:var(--t4);padding:16px;font-size:12px">Nenhum usuário${!showInactive&&inativos?' ativo. Há '+inativos+' inativo(s) — marque "Mostrar inativos".':'.'}</div>`;
  if(lista.length&&!showInactive&&inativos){
    document.getElementById('users-list').insertAdjacentHTML('beforeend',
      `<div style="color:var(--t4);padding:10px 16px;font-size:11px">${inativos} usuário(s) inativo(s) oculto(s). Marque "Mostrar inativos" para vê-los.</div>`);
  }
}
function openEditUser(id){
  const u=_allUsers.find(x=>x.id===id);if(!u)return;
  document.getElementById('edit-user-id').value=u.id;document.getElementById('edit-user-nome').value=u.nome;
  document.getElementById('edit-user-email').value=u.email;document.getElementById('edit-user-role').value=u.role;
  const cb=document.getElementById('edit-user-ativo');if(cb)cb.checked=u.ativo;
  const uareas=Array.isArray(u.areas)?u.areas:[];
  document.querySelectorAll('.edit-user-area').forEach(el=>{el.checked=uareas.indexOf(el.value)!==-1});
  document.getElementById('edit-user-senha').value='';openBaseModal('edit-user');
}
async function saveEditUser(){
  const id=parseInt(document.getElementById('edit-user-id').value),nome=document.getElementById('edit-user-nome').value.trim(),
    email=document.getElementById('edit-user-email').value.trim(),role=document.getElementById('edit-user-role').value,
    senha=document.getElementById('edit-user-senha').value.trim();
  const cb=document.getElementById('edit-user-ativo');
  const ativo=cb?cb.checked:true;
  const areas=Array.from(document.querySelectorAll('.edit-user-area')).filter(el=>el.checked).map(el=>el.value);
  if(!nome||!email){showToast('Preencha nome e email','error');return}
  const p={nome,email,role,ativo,areas};if(senha)p.senha=senha;
  try{const res=await apiFetch(`/users/${id}`,{method:'PATCH',body:JSON.stringify(p)});const data=await res.json();if(!res.ok){showToast(data.erro||'Erro','error');return}showToast('Atualizado','success');closeModal('edit-user');renderUsers()}catch(e){showToast('Erro','error')}
}
async function confirmDeleteUser(id,nome){
  const ok=await confirmModal('Desativar usuário',`Desativar o usuário "${nome}"? Ele não poderá mais acessar o sistema.`);
  if(!ok)return;
  try{const res=await apiFetch(`/users/${id}`,{method:'DELETE'});if(!res||!res.ok){showToast('Erro','error');return}showToast(nome+' desativado','success');renderUsers()}catch(e){showToast('Erro','error')}
}
async function confirmHardDeleteUser(id,nome){
  const ok=await confirmModal('Excluir permanentemente',`Excluir DEFINITIVAMENTE o usuário "${nome}"? Esta ação não pode ser desfeita. As responsabilidades dele em documentos serão removidas (o histórico de auditoria é preservado).`);
  if(!ok)return;
  try{const res=await apiFetch(`/users/${id}?permanente=true`,{method:'DELETE'});const data=await res.json().catch(()=>({}));if(!res||!res.ok){showToast((data&&data.erro)||'Erro ao excluir','error');return}showToast(nome+' excluído','success');renderUsers()}catch(e){showToast('Erro','error')}
}
async function createUser(){
  const nome=document.getElementById('new-user-nome').value.trim(),email=document.getElementById('new-user-email').value.trim(),
    role=document.getElementById('new-user-role').value,senha=document.getElementById('new-user-senha').value.trim();
  if(!nome||!email){showToast('Preencha nome e e-mail','error');return}
  if(senha&&senha.length<SENHA_MIN){showToast('A senha deve ter pelo menos '+SENHA_MIN+' caracteres','error');return}
  const areas=Array.from(document.querySelectorAll('.new-user-area')).filter(el=>el.checked).map(el=>el.value);
  const body={nome,email,role,areas};if(senha)body.senha=senha;
  try{
    const res=await apiFetch('/users',{method:'POST',body:JSON.stringify(body)});const data=await res.json();
    if(!res.ok){showToast(data.erro||'Erro','error');return}
    showToast('Usuário criado','success');closeModal('add-user');
    ['new-user-nome','new-user-email','new-user-senha'].forEach(id=>{const el=document.getElementById(id);if(el)el.value=''});
    document.querySelectorAll('.new-user-area').forEach(el=>{el.checked=false});
    renderUsers();
    if(data.codigo_ativacao)showCodigoAtivacao(data.codigo_ativacao,email,data.validade_dias);
  }catch(e){showToast('Erro','error')}
}
async function confirmResetUser(id,nome,email){
  const ok=await confirmModal('Resetar senha',`Resetar a senha de "${nome}"? A senha atual deixa de funcionar e será gerado um código de ativação para o usuário definir uma nova senha.`);
  if(!ok)return;
  try{
    const res=await apiFetch(`/users/${id}/reset-senha`,{method:'POST'});const data=await res.json().catch(()=>({}));
    if(!res||!res.ok){showToast((data&&data.erro)||'Erro ao resetar','error');return}
    showToast('Senha resetada','success');renderUsers();
    if(data.codigo_ativacao)showCodigoAtivacao(data.codigo_ativacao,email||nome,data.validade_dias);
  }catch(e){showToast('Erro','error')}
}

// ═══ CÓDIGO DE ATIVAÇÃO ═══
function showCodigoAtivacao(codigo,email,validadeDias){
  _codigoAtivacaoAtual=codigo||'';
  document.getElementById('codigo-ativacao-valor').textContent=codigo||'—';
  document.getElementById('codigo-ativacao-sub').textContent=
    'Repasse este código para '+(email||'o usuário')+'. Ele será mostrado apenas uma vez.';
  document.getElementById('codigo-ativacao-validade').textContent=
    validadeDias?('Validade: '+validadeDias+' dia(s).'):'';
  const b=document.getElementById('codigo-ativacao-copy-btn');if(b)b.textContent='Copiar';
  openModal('codigo-ativacao');
}
function copiarCodigoAtivacao(){
  const b=document.getElementById('codigo-ativacao-copy-btn');
  navigator.clipboard.writeText(_codigoAtivacaoAtual).then(()=>{
    if(b)b.textContent='Copiado ✓';showToast('Código copiado','success');
  }).catch(()=>showToast('Não foi possível copiar','error'));
}

// ═══ HELPERS DE UI ═══
function showToast(msg,type='info'){
  const t=document.getElementById('toast'),d=document.getElementById('toast-dot'),m=document.getElementById('toast-msg');
  if(!t)return;
  d.style.background=type==='success'?'var(--green)':type==='error'?'var(--red)':'var(--cyan)';
  m.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3200);
}
let _previousFocus=null;
function openModal(id){ openBaseModal(id); }
function openBaseModal(id){
  const m=document.getElementById('modal-'+id);
  if(!m)return;
  _previousFocus=document.activeElement;
  m.classList.add('open');
  m.setAttribute('aria-hidden','false');
  const focusable=m.querySelectorAll('input,select,textarea,button,[tabindex]:not([tabindex="-1"])');
  if(focusable.length){focusable[0].focus()}
  else {const inner=m.querySelector('.modal,.confirm-card');if(inner)inner.focus()}
}
function closeModal(id){
  const m=document.getElementById('modal-'+id);
  if(!m)return;
  m.classList.remove('open');
  m.setAttribute('aria-hidden','true');
  if(_previousFocus&&_previousFocus.focus){_previousFocus.focus()}
}
document.querySelectorAll('.modal-overlay').forEach(m=>m.addEventListener('click',e=>{
  if(e.target===m){m.classList.remove('open');m.setAttribute('aria-hidden','true');if(_previousFocus&&_previousFocus.focus)_previousFocus.focus()}
}));

// Confirm modal (substitui confirm() nativo)
let _confirmResolve=null,_confirmReject=null;
function confirmModal(title,message){
  return new Promise((resolve)=>{
    const m=document.getElementById('confirm-modal');
    document.getElementById('confirm-title').textContent=title;
    document.getElementById('confirm-msg').textContent=message;
    _previousFocus=document.activeElement;
    m.classList.add('open');
    setTimeout(()=>document.getElementById('confirm-cancel').focus(),10);
    _confirmResolve=()=>{m.classList.remove('open');if(_previousFocus&&_previousFocus.focus)_previousFocus.focus();resolve(true)};
    _confirmReject=()=>{m.classList.remove('open');if(_previousFocus&&_previousFocus.focus)_previousFocus.focus();resolve(false)};
  });
}
document.getElementById('confirm-ok')?.addEventListener('click',()=>_confirmResolve&&_confirmResolve());
document.getElementById('confirm-cancel')?.addEventListener('click',()=>_confirmReject&&_confirmReject());
document.getElementById('confirm-modal')?.addEventListener('click',(e)=>{if(e.target.id==='confirm-modal')_confirmReject&&_confirmReject()});

// Trap de teclado nos modais
document.addEventListener('keydown',(e)=>{
  const openOverlay=document.querySelector('.modal-overlay.open, .confirm-modal.open');
  if(e.key==='Escape'){
    if(openOverlay){
      if(openOverlay.classList.contains('confirm-modal')){_confirmReject&&_confirmReject()}
      else{openOverlay.classList.remove('open');openOverlay.setAttribute('aria-hidden','true');if(_previousFocus&&_previousFocus.focus)_previousFocus.focus()}
    }
    return;
  }
  if(e.key==='Tab'&&openOverlay){
    const focusable=openOverlay.querySelectorAll('input:not([disabled]),select:not([disabled]),textarea:not([disabled]),button:not([disabled]),a[href],[tabindex]:not([tabindex="-1"])');
    if(focusable.length===0)return;
    const first=focusable[0],last=focusable[focusable.length-1];
    if(e.shiftKey&&document.activeElement===first){last.focus();e.preventDefault()}
    else if(!e.shiftKey&&document.activeElement===last){first.focus();e.preventDefault()}
  }
});

// ═══ SIDEBAR (mobile) ═══
const _sidebarToggle=document.getElementById('sidebar-toggle');
const _sidebarBackdrop=document.getElementById('sidebar-backdrop');
const _sidebar=document.getElementById('sidebar-nav');
function toggleSidebar(force){
  if(!_sidebar)return;
  const willOpen=force!==undefined?force:!_sidebar.classList.contains('open');
  _sidebar.classList.toggle('open',willOpen);
  if(_sidebarBackdrop)_sidebarBackdrop.classList.toggle('open',willOpen);
  if(_sidebarToggle)_sidebarToggle.setAttribute('aria-expanded',String(willOpen));
}
_sidebarToggle?.addEventListener('click',()=>toggleSidebar());
_sidebarBackdrop?.addEventListener('click',()=>toggleSidebar(false));
document.querySelectorAll('.nav-item[data-page]').forEach(el=>el.addEventListener('click',()=>{if(window.innerWidth<=900)toggleSidebar(false)}));

// ═══ DELEGAÇÃO DE EVENTOS (ações de usuário, filtros) ═══
document.body.addEventListener('click',(e)=>{
  const btn=e.target.closest('[data-action]');
  if(!btn)return;
  const action=btn.dataset.action, id=btn.dataset.id;
  switch(action){
    case 'edit-user': openEditUser(parseInt(id)); break;
    case 'delete-user': confirmDeleteUser(parseInt(id), btn.dataset.name||''); break;
    case 'hard-delete-user': confirmHardDeleteUser(parseInt(id), btn.dataset.name||''); break;
    case 'reset-user': confirmResetUser(parseInt(id), btn.dataset.name||'', btn.dataset.email||''); break;
  }
});
document.body.addEventListener('change',(e)=>{
  if(e.target&&(e.target.id==='audit-filter-action'||e.target.id==='audit-filter-module')){filterAudit();return}
});
document.body.addEventListener('input',(e)=>{
  if(e.target&&e.target.id==='audit-search'){
    clearTimeout(_filterTimer);
    _filterTimer=setTimeout(filterAudit,250);
  }
});

// ═══ UI DO USUÁRIO LOGADO ═══
function updateUserUI(){
  const av=currentUser.initials,rl=currentUser.role;
  ['nav-avatar','settings-avatar'].forEach(id=>{const el=document.getElementById(id);if(el)el.textContent=av});
  const nn=document.getElementById('nav-name');if(nn)nn.textContent=currentUser.name;
  const nr=document.getElementById('nav-role');if(nr)nr.textContent=rl.toUpperCase();
  const sn=document.getElementById('settings-name');if(sn)sn.textContent=currentUser.name;
  const se=document.getElementById('settings-email');if(se)se.textContent=currentUser.email;
  const rh={admin:'<span class="role-admin">Admin</span>',gestor:'<span class="role-gestor">Gestor</span>',tecnico:'<span class="role-tecnico">Técnico</span>',leitura:'<span class="role-leitura">Leitura</span>'};
  const rb=document.getElementById('settings-role-badge');if(rb)rb.innerHTML=rh[rl]||'';
  // Criação/edição de usuários é exclusiva de admin; gestor tem acesso somente-leitura.
  if(rl!=='admin'){
    const ba=document.getElementById('btn-add-user');
    if(ba)ba.style.display='none';
  }
}

// ═══ BOOTSTRAP: exige token e nível gestor+ ═══
initTheme();
(function bootstrapConfig(){
  const token=getToken();
  if(!token){ window.location.href='/'; return; }
  let u={};
  try{ u=JSON.parse(localStorage.getItem('doctrack_user')||'{}')||{}; }catch(e){}
  if(!(u.role==='admin'||u.role==='gestor')){ window.location.href='/hub'; return; }
  currentUser={name:u.nome,email:u.email,role:u.role,initials:(u.nome||'?').split(' ').map(w=>w[0]).join('').substring(0,2).toUpperCase()};
  const appEl=document.getElementById('app');if(appEl)appEl.style.display='block';
  updateUserUI();
  navigate('audit');
  renderUsers();
  carregarStatusSistema();
})();

// ═══ ABA SISTEMA: infra real, não texto fixo ═══
// O card "Conexão" dizia "Flask local · porta 5000" e "SQLite · doctrack.db"
// escritos no HTML — errado em produção (waitress + PostgreSQL) e impossível de
// perceber olhando a tela. GET /api/status responde com o que está de fato no ar.
async function carregarStatusSistema(){
  const def = (id, texto) => { const el=document.getElementById(id); if(el) el.textContent=texto; };
  try{
    // apiFetch devolve a Response (convenção deste módulo), não o JSON.
    const res = await apiFetch('/status');
    if(!res || !res.ok) throw new Error('status indisponível');
    const s = await res.json();
    def('cfg-servidor', `${s.db_engine === 'SQLite' ? 'Flask local' : 'waitress'} · ${window.location.host}`);
    def('cfg-banco', `${s.db_engine} · ${s.db_nome} · ${s.documentos} documentos · ${s.usuarios} usuários`);
    def('cfg-versao', `DocTrack v${s.versao}`);
    def('cfg-agendador', s.agendador
      ? 'Agendador interno ativo — foto diária automática'
      : 'Agendador interno desligado (tarefa externa ou manual)');
  }catch(e){
    def('cfg-servidor', 'Não foi possível ler o estado do servidor');
    def('cfg-banco', '—');
    def('cfg-agendador', '—');
  }
}

// Dispara a foto do dia sem esperar o agendador nem reiniciar o serviço.
async function rodarTarefasDiarias(){
  const btn = document.getElementById('cfg-btn-snapshot');
  if(btn){ btn.disabled = true; btn.textContent = 'Gravando…'; }
  try{
    const res = await apiFetch('/admin/tarefas-diarias', {method:'POST'});
    if(!res || !res.ok){
      // Exclusiva de admin: gestor vê a tela mas não dispara.
      const corpo = res ? await res.json().catch(()=>({})) : {};
      throw new Error(corpo.erro || 'Não foi possível gravar as fotos do dia');
    }
    showToast('Fotos do dia gravadas (equipamentos, missões e projetos)');
    carregarStatusSistema();
  }catch(e){
    showToast(e.message || 'Não foi possível gravar as fotos do dia', 'error');
  }finally{
    if(btn){ btn.disabled = false; btn.textContent = 'Gravar agora'; }
  }
}
