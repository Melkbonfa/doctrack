const API='/api';
let allDocs=[],chartInstances={},currentUser={name:'Admin',email:'admin@pde.com',role:'admin',initials:'A'};
let selectedRole='admin',_allUsers=[],_enums={},_lastKpis=null;
let _filterTimer=null;

const CAT_COLORS={'DOCs - Produção (PRE)':'#22d3ee','DOCs - Fabricante':'#a855f7','DOCs - P&D Equipamentos (PDE)':'#ec4899','Manual Usuário':'#e879f9','Instalação':'#f59e0b','QIQOQD':'#10b981','Serviços':'#3b82f6','Usuário':'#c4b5fd'};
const STATUS_PILL={'Elaborar':'pill-elab','Homologado':'pill-ok','Enviado para Homologação':'pill-wip','Treinamento Piloto':'pill-warn','Não':'pill-err','Sim':'pill-ok'};

// ═══ XSS-safe HTML escape ═══
function esc(str){
  if(str==null)return'';
  return String(str)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;')
    .replace(/'/g,'&#39;');
}

// ═══ F2/F9: normalização Unicode (lowercase + sem acentos + trim) ═══
function norm(s){
  if(s==null)return'';
  return String(s).trim().toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g,'');
}

function selectRole(btn,role){document.querySelectorAll('.role-btn').forEach(b=>b.classList.remove('selected'));btn.classList.add('selected');selectedRole=role}
function getToken(){return localStorage.getItem('doctrack_token')||''}
function setToken(t){localStorage.setItem('doctrack_token',t)}
function clearToken(){localStorage.removeItem('doctrack_token');localStorage.removeItem('doctrack_user')}
function authHeader(){return{'Content-Type':'application/json','Authorization':'Bearer '+getToken()}}
async function apiFetch(url,opts={}){try{const res=await fetch(API+url,{headers:authHeader(),...opts});if(res.status===401){doLogout();return null}return res}catch(e){return null}}

async function doLogin(){
  const btn=document.getElementById('login-btn-text'),email=document.getElementById('login-email').value.trim(),senha=document.getElementById('login-pass').value;
  btn.innerHTML='<span class="spinner" style="border-color:rgba(255,255,255,.3);border-top-color:#fff"></span>';
  try{
    const res=await fetch(API+'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,senha})});
    const data=await res.json().catch(()=>({}));
    if(!res.ok){btn.textContent='Entrar no DocTrack';showToast(data.erro||data.error||'Falha no login','error');return}
    setToken(data.access_token);localStorage.setItem('doctrack_user',JSON.stringify(data.usuario));
    const u=data.usuario;currentUser={name:u.nome,email:u.email,role:u.role,initials:u.nome.split(' ').map(w=>w[0]).join('').substring(0,2).toUpperCase()};
    document.getElementById('login-screen').style.display='none';document.getElementById('app').style.display='block';initApp();
  }catch(e){
    btn.textContent='Entrar no DocTrack';
    showToast('Servidor indisponível. Tente novamente.','error');
  }
}
async function doLogout(){
  // B2: revoga o token no servidor antes de descartar localmente
  try{await apiFetch('/auth/logout',{method:'POST'})}catch(e){}
  clearToken();
  document.getElementById('app').style.display='none';
  document.getElementById('login-screen').style.display='flex';
}

const PAGE_LABELS={dashboard:'Dashboard',docs:'Documentos',audit:'Audit Log',users:'Usuários',settings:'Configurações'};
function navigate(page){
  document.querySelectorAll('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.page===page));
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.getElementById('page-'+page).classList.add('active');
  document.getElementById('breadcrumb-current').textContent=PAGE_LABELS[page]||page;
  if(page==='docs')renderDocs();if(page==='audit')renderAudit();if(page==='users')renderUsers();
}
document.querySelectorAll('.nav-item[data-page]').forEach(el=>el.addEventListener('click',()=>navigate(el.dataset.page)));

// ═══ Event delegation for table actions ═══
document.body.addEventListener('click',(e)=>{
  const btn=e.target.closest('[data-action]');
  if(!btn)return;
  const action=btn.dataset.action;
  const id=btn.dataset.id;
  switch(action){
    case 'edit-doc': openEditDoc(parseInt(id)); break;
    case 'delete-doc': delDoc(parseInt(id), btn.dataset.name||''); break;
    case 'edit-user': openEditUser(parseInt(id)); break;
    case 'delete-user': confirmDeleteUser(parseInt(id), btn.dataset.name||''); break;
  }
});

// ═══ Event delegation for etapa selects ═══
document.body.addEventListener('change',(e)=>{
  const sel=e.target.closest('select.etapa-select[data-etapa]');
  if(sel){
    const docId=parseInt(sel.dataset.docId);
    const etapa=sel.dataset.etapa;
    changeEtapa(docId,etapa,sel.value);
    return;
  }
  // Filtros de docs e audit (substitui onchange inline)
  const filterIds=['docs-filter-cat','docs-filter-origem','docs-filter-status-global','docs-filter-tipo','docs-filter-subtipo'];
  if(e.target&&filterIds.includes(e.target.id)){filterDocs();return}
  if(e.target&&e.target.id==='audit-filter-action'){filterAudit();return}
});

// Busca textual com debounce de 250ms (substitui oninput inline)
document.body.addEventListener('input',(e)=>{
  if(!e.target)return;
  if(e.target.id==='docs-search'||e.target.id==='audit-search'){
    clearTimeout(_filterTimer);
    const fn=e.target.id==='docs-search'?filterDocs:filterAudit;
    _filterTimer=setTimeout(fn,250);
  }
});

async function initApp(){
  updateUserUI();
  // Skeleton inicial enquanto carrega
  renderSkeletonTable('dash-table',5,5);
  renderSkeletonTable('docs-tbody',6,11);
  await loadEnums();
  await loadData();
  renderDashboard();renderDocs();renderAudit();renderUsers();
  makeSortable();
  showToast('Bem-vindo ao DocTrack v3.0','success');
  document.getElementById('sync-label').textContent='Conectado · '+new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
  const ls=document.getElementById('last-sync');if(ls)ls.textContent=new Date().toLocaleString('pt-BR',{hour:'2-digit',minute:'2-digit',day:'2-digit',month:'2-digit'});
}

function updateUserUI(){
  const av=currentUser.initials,rl=currentUser.role;
  ['nav-avatar','top-avatar','settings-avatar'].forEach(id=>{const el=document.getElementById(id);if(el)el.textContent=av});
  document.getElementById('nav-name').textContent=currentUser.name;
  document.getElementById('nav-role').textContent=rl.toUpperCase();
  document.getElementById('settings-name').textContent=currentUser.name;
  document.getElementById('settings-email').textContent=currentUser.email;
  const rh={admin:'<span class="role-admin">Admin</span>',gestor:'<span class="role-gestor">Gestor</span>',tecnico:'<span class="role-tecnico">Técnico</span>',leitura:'<span class="role-leitura">Leitura</span>'};
  const rb=document.getElementById('settings-role-badge');if(rb)rb.innerHTML=rh[rl]||'';
  if(rl==='leitura') document.getElementById('btn-add-doc').style.display='none';
}

async function loadEnums(){
  try{const res=await apiFetch('/enums');if(res&&res.ok)_enums=await res.json()}catch(e){}
}
async function loadData(){
  try{
    const res=await apiFetch('/data');
    if(res&&res.ok){
      const data=await res.json();
      allDocs=data.items||[];
      _lastKpis=data.kpis||null;  // R2: front consome KPIs do backend
      return;
    }
  }catch(e){}
  allDocs=[];_lastKpis=null;
}
async function refreshAll(){await loadData();renderDashboard();renderDocs();showToast('Dados atualizados','success');
  document.getElementById('sync-label').textContent='Atualizado · '+new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
}

// ═══ DASHBOARD ═══
function renderDashboard(){
  const total=allDocs.length;
  const cats={},origens={},statuses={},sg={};
  allDocs.forEach(d=>{
    const c=d.categoria||'Sem categoria';cats[c]=(cats[c]||0)+1;
    const o=d.origem||'Sem origem';origens[o]=(origens[o]||0)+1;
    const s=d.status_principal||'Sem status';statuses[s]=(statuses[s]||0)+1;
    const g=d.status_global||'Pendente';sg[g]=(sg[g]||0)+1;
  });
  const withVer=allDocs.filter(d=>d.versao).length;
  const withLocal=allDocs.filter(d=>d.local).length;
  const etapas={elab:0,rev1:0,diag:0,rev2:0};
  allDocs.forEach(d=>{
    if(d.etapa_elaboracao==='Concluído')etapas.elab++;
    if(d.etapa_revisao1==='Concluído')etapas.rev1++;
    if(d.etapa_diagramacao==='Concluído')etapas.diag++;
    if(d.etapa_revisao2==='Concluído')etapas.rev2++;
  });

  document.getElementById('dash-updated').textContent='Última atualização: '+new Date().toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
  document.getElementById('dash-pct-badge').textContent=total+' documentos';

  // KPI rings — paleta cyberpunk: verde / cyan / magenta
  const ringColors=['#10b981','#22d3ee','#a855f7'];
  const ringBgs=['rgba(16,185,129,.15)','rgba(34,211,238,.15)','rgba(168,85,247,.15)'];
  const sgKeys=['Finalizado','Em progresso','Pendente'];
  let kpiHTML='';
  sgKeys.forEach((k,i)=>{
    const v=sg[k]||0,pct=total?Math.round(v/total*100):0;
    kpiHTML+=`<div class="kpi-ring">
      <div class="kpi-ring-canvas" style="width:110px;height:110px"><canvas id="ring${i}" width="110" height="110"></canvas><div class="kpi-ring-val" style="color:${ringColors[i]}">${v}</div></div>
      <div class="kpi-ring-label">${esc(k)}</div>
      <div class="kpi-ring-delta" style="color:${ringColors[i]}">${pct}% do total</div>
    </div>`;
  });
  document.getElementById('kpi-grid').innerHTML=kpiHTML||'<div class="loading-state" style="grid-column:1/-1">Sem dados</div>';

  sgKeys.forEach((k,i)=>{
    const v=sg[k]||0,pct=total?v/total:0;
    if(chartInstances['ring'+i])chartInstances['ring'+i].destroy();
    chartInstances['ring'+i]=new Chart(document.getElementById('ring'+i),{
      type:'doughnut',data:{datasets:[{data:[pct*100,100-pct*100],backgroundColor:[ringColors[i],ringBgs[i]],borderWidth:0,hoverOffset:4}]},
      options:{responsive:false,cutout:'78%',plugins:{legend:{display:false},tooltip:{enabled:false}},animation:{animateRotate:true,duration:1200}}
    });
  });

  const mHTML=`
    <div class="metric-card"><div class="metric-letter" style="background:linear-gradient(135deg,#a855f7,#ec4899)">V</div><div class="metric-info"><div class="metric-value">${withVer}</div><div class="metric-label">Com versão definida</div></div></div>
    <div class="metric-card"><div class="metric-letter" style="background:linear-gradient(135deg,#22d3ee,#3b82f6)">L</div><div class="metric-info"><div class="metric-value">${withLocal}</div><div class="metric-label">Com local de armazenamento</div></div></div>`;
  document.getElementById('metric-row').innerHTML=mHTML;

  const catLabels=Object.keys(cats),catVals=Object.values(cats);
  const dColors=catLabels.map(c=>CAT_COLORS[c]||'#6366f1');
  document.getElementById('donut-total').textContent=total;
  document.getElementById('donut-legend').innerHTML=catLabels.map((c,i)=>{
    const lbl=c.length>22?c.substring(0,22)+'…':c;
    return`<div class="legend-row" title="${esc(c)}"><span class="legend-dot" style="background:${dColors[i]}"></span><span>${esc(lbl)}</span><span class="legend-val">${catVals[i]}</span></div>`;
  }).join('');
  if(chartInstances.donut)chartInstances.donut.destroy();
  chartInstances.donut=new Chart(document.getElementById('cDonut'),{
    type:'doughnut',data:{datasets:[{data:catVals,backgroundColor:dColors,borderWidth:3,borderColor:'#1f2444',hoverOffset:8}]},
    options:{responsive:false,cutout:'72%',plugins:{legend:{display:false},tooltip:{backgroundColor:'#232847',titleColor:'#f1f5f9',bodyColor:'#c7d2fe',borderColor:'rgba(167,139,250,.3)',borderWidth:1,padding:10,cornerRadius:8,callbacks:{label:ctx=>' '+catLabels[ctx.dataIndex]+': '+ctx.raw}}}}
  });

  const etapaNames=['Elaboração','Revisão 1','Diagramação','Revisão 2'];
  const etapaVals=[etapas.elab,etapas.rev1,etapas.diag,etapas.rev2];
  const etapaColors=['#22d3ee','#8b5cf6','#e879f9','#f472b6'];
  document.getElementById('prog-list').innerHTML=etapaNames.map((n,i)=>{
    const pct=total?Math.round(etapaVals[i]/total*100):0;
    return`<div class="prog-row"><span class="prog-label">${n}</span><div class="prog-track"><div class="prog-fill" style="width:${pct}%;background:${etapaColors[i]}"></div></div><span class="prog-pct">${etapaVals[i]} conc.</span></div>`;
  }).join('')+`<div style="margin-top:14px;padding-top:10px;border-top:1px solid var(--border-dim);display:flex;justify-content:space-between"><span style="font-size:10px;color:var(--t3)">Total documentos</span><span style="font-family:var(--font-mono);font-size:14px;font-weight:700;color:var(--cyan)">${total}</span></div>`;

  const origLabels=Object.keys(origens),origVals=Object.values(origens);
  if(chartInstances.bar)chartInstances.bar.destroy();
  // Bar chart com gradiente cyan→azul (igual ref)
  const ctxBar=document.getElementById('chartBar').getContext('2d');
  const gradBar=ctxBar.createLinearGradient(0,0,0,200);
  gradBar.addColorStop(0,'#22d3ee');gradBar.addColorStop(1,'#3b82f6');
  chartInstances.bar=new Chart(ctxBar,{
    type:'bar',data:{labels:origLabels.map(l=>l.length>20?l.substring(0,20)+'…':l),datasets:[{data:origVals,backgroundColor:gradBar,borderRadius:8,borderWidth:0}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{backgroundColor:'#232847',titleColor:'#f1f5f9',bodyColor:'#c7d2fe',borderColor:'rgba(167,139,250,.3)',borderWidth:1,padding:10,cornerRadius:8}},
      scales:{x:{ticks:{color:'#94a3ff',font:{size:10,family:'Inter'}},grid:{display:false},border:{display:false}},
              y:{ticks:{color:'#94a3ff',font:{size:10,family:'Inter'},stepSize:20},grid:{color:'rgba(167,139,250,.06)'},border:{display:false}}}}
  });

  const stLabels=Object.keys(statuses),stVals=Object.values(statuses);
  const stColors=stLabels.map(s=>s==='Elaborar'?'#a855f7':s.includes('Homologado')?'#10b981':s.includes('Enviado')?'#22d3ee':s.includes('Treinamento')?'#f59e0b':s==='Não'?'#f43f5e':s==='Sim'?'#10b981':'#ec4899');
  if(chartInstances.status)chartInstances.status.destroy();
  chartInstances.status=new Chart(document.getElementById('chartStatus'),{
    type:'bar',data:{labels:stLabels.map(l=>l.length>18?l.substring(0,18)+'…':l),datasets:[{data:stVals,backgroundColor:stColors,borderRadius:8,borderWidth:0}]},
    options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{backgroundColor:'#232847',titleColor:'#f1f5f9',bodyColor:'#c7d2fe',borderColor:'rgba(167,139,250,.3)',borderWidth:1,padding:10,cornerRadius:8}},
      scales:{x:{ticks:{color:'#94a3ff',font:{size:10,family:'Inter'}},grid:{color:'rgba(167,139,250,.06)'},border:{display:false}},
              y:{ticks:{color:'#c7d2fe',font:{size:11,family:'Inter',weight:'500'}},grid:{display:false},border:{display:false}}}}
  });

  document.getElementById('dash-table').innerHTML=allDocs.slice(0,10).map(d=>
    `<tr><td class="bold">${esc(d.equipamento)}</td><td style="font-size:11px;color:var(--t2)" title="${esc(d.documento||'')}">${esc((d.documento||'—').substring(0,40))}</td><td><span class="pill pill-elab">${esc((d.tipo_documento||'—').substring(0,20))}</span></td><td>${pillGlobal(d.status_global)}</td><td class="mono">${esc(d.versao||'—')}</td></tr>`
  ).join('')||'<tr><td colspan="5" style="text-align:center;color:var(--t4);padding:32px">Sem dados</td></tr>';
}

function pillCls(c){if(!c)return'pill-elab';if(c.includes('PRE'))return'pill-wip';if(c.includes('Fabricante'))return'pill-elab';return'pill-warn'}
function pillSt(s){if(!s)return'<span style="color:var(--t4)">—</span>';const cls=STATUS_PILL[s]||'pill-elab';return`<span class="pill ${cls}">${esc(s)}</span>`}
function pillGlobal(s){
  if(s==='Finalizado')return'<span class="sg-badge sg-finalizado">Finalizado</span>';
  if(s==='Em progresso')return'<span class="sg-badge sg-progresso">Progresso</span>';
  return'<span class="sg-badge sg-pendente">Pendente</span>';
}

// ═══ DOCS TABLE — F1: filtros centralizados no backend ═══
function renderDocs(){populateFilters();filterDocs()}

function populateFilters(){
  // F8: preservar seleção antes de repopular
  const ids=['docs-filter-cat','docs-filter-origem','docs-filter-status-global','docs-filter-tipo','docs-filter-subtipo'];
  const prev={};
  ids.forEach(id=>{const el=document.getElementById(id);if(el)prev[id]=el.value});

  const cats=[...new Set(allDocs.map(d=>d.categoria).filter(Boolean))].sort();
  const origens=[...new Set(allDocs.map(d=>d.origem).filter(Boolean))].sort();
  // R9: tipos/subtipos vêm de /api/enums quando disponíveis
  const tipos=(_enums.tipos_documento&&_enums.tipos_documento.length)?_enums.tipos_documento:[...new Set(allDocs.map(d=>d.tipo_documento).filter(Boolean))].sort();
  const subtipos=(_enums.subtipos&&_enums.subtipos.length)?_enums.subtipos:[...new Set(allDocs.map(d=>d.subtipo).filter(Boolean))].sort();
  const opt=(arr)=>arr.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');
  document.getElementById('docs-filter-cat').innerHTML='<option value="">Todas categorias</option>'+opt(cats);
  document.getElementById('docs-filter-origem').innerHTML='<option value="">Todas origens</option>'+opt(origens);
  document.getElementById('docs-filter-tipo').innerHTML='<option value="">Todos tipos</option>'+opt(tipos);
  document.getElementById('docs-filter-subtipo').innerHTML='<option value="">Todos subtipos</option>'+opt(subtipos);

  ids.forEach(id=>{const el=document.getElementById(id);if(el&&prev[id]!==undefined)el.value=prev[id]});

  // Atualizar abas
  const tabsContainer = document.getElementById('docs-tabs');
  if(tabsContainer) {
    const currentActive = document.getElementById('docs-filter-origem').value || '';
    let tabsHtml = `<button type="button" class="docs-tab ${currentActive===''?'active':''}" data-origem="">Todos os Departamentos</button>`;
    origens.forEach(o => {
      tabsHtml += `<button type="button" class="docs-tab ${currentActive===o?'active':''}" data-origem="${esc(o)}">${esc(o)}</button>`;
    });
    tabsContainer.innerHTML = tabsHtml;
    tabsContainer.querySelectorAll('.docs-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        tabsContainer.querySelectorAll('.docs-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const origemSel = document.getElementById('docs-filter-origem');
        if(origemSel) origemSel.value = btn.dataset.origem;
        filterDocs();
      });
    });
  }
}

async function filterDocs(){
  // F1: backend é única fonte para filtros
  const params=new URLSearchParams();
  const q=document.getElementById('docs-search').value.trim();
  const cat=document.getElementById('docs-filter-cat').value;
  const orig=document.getElementById('docs-filter-origem').value;
  const sg=document.getElementById('docs-filter-status-global').value;
  const tip=document.getElementById('docs-filter-tipo').value;
  const sub=document.getElementById('docs-filter-subtipo').value;
  if(q) params.set('q',q);
  if(cat) params.set('categoria',cat);
  if(orig) params.set('origem',orig);
  if(sg) params.set('status_global',sg);
  if(tip) params.set('tipo_documento',tip);
  if(sub) params.set('subtipo',sub);

  // Skeleton enquanto carrega (U16)
  renderSkeletonTable('docs-tbody',6,11);

  let data=[];
  try{
    const res=await apiFetch('/documentos?'+params.toString());
    if(res&&res.ok) data=await res.json();
  }catch(e){data=[]}

  data=applySort(data); // U18

  document.getElementById('docs-badge').textContent=data.length+' de '+allDocs.length;
  const canEdit=currentUser.role!=='leitura';
  document.getElementById('docs-tbody').innerHTML=data.map(d=>`<tr>
    <td class="bold" data-label="Equipamento">${esc(d.equipamento)}</td>
    <td data-label="Documento" style="font-size:11px;color:var(--t2);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(d.documento||'')}">${esc(d.documento||'—')}</td>
    <td data-label="Tipo"><span class="pill ${pillCls(d.categoria)}">${esc((d.tipo_documento||'—').substring(0,15))}</span></td>
    <td data-label="Subtipo" class="mono" style="font-size:9px">${esc(d.subtipo||'—')}</td>
    <td data-label="Elaboração" class="etapa-cell" id="td-${d.id}-etapa_elaboracao">${renderEtapaSelect(d.id,'etapa_elaboracao',d.etapa_elaboracao,canEdit)}</td>
    <td data-label="Revisão 1" class="etapa-cell" id="td-${d.id}-etapa_revisao1">${renderEtapaSelect(d.id,'etapa_revisao1',d.etapa_revisao1,canEdit)}</td>
    <td data-label="Diagramação" class="etapa-cell" id="td-${d.id}-etapa_diagramacao">${renderEtapaSelect(d.id,'etapa_diagramacao',d.etapa_diagramacao,canEdit)}</td>
    <td data-label="Revisão 2" class="etapa-cell" id="td-${d.id}-etapa_revisao2">${renderEtapaSelect(d.id,'etapa_revisao2',d.etapa_revisao2,canEdit)}</td>
    <td data-label="Status" id="td-${d.id}-global">${pillGlobal(d.status_global)}</td>
    <td data-label="Versão" class="mono">${esc(d.versao||'—')}</td>
    <td data-label="Ações">${canEdit?`<div class="row-actions"><button class="btn-edit" type="button" data-action="edit-doc" data-id="${d.id}" aria-label="Editar documento ${esc(d.equipamento)}">Editar</button><button class="btn-del" type="button" data-action="delete-doc" data-id="${d.id}" data-name="${esc(d.equipamento)}" aria-label="Excluir documento ${esc(d.equipamento)}">×</button></div>`:'—'}</td>
  </tr>`).join('')||'<tr><td colspan="11" style="text-align:center;color:var(--t4);padding:32px">Nenhum resultado</td></tr>';
}

function renderEtapaSelect(docId,etapa,val,canEdit){
  const v=val||'Pendente';
  const cls=v==='Concluído'?'s-concluido':v==='Em andamento'?'s-andamento':'s-pendente';
  if(!canEdit) return `<span class="pill" style="font-size:9px">${esc(v)}</span>`;
  return `<select class="etapa-select ${cls}" data-doc-id="${docId}" data-etapa="${esc(etapa)}" aria-label="Status da etapa ${esc(etapa)}">
    <option value="Pendente" ${v==='Pendente'?'selected':''}>Pendente</option>
    <option value="Em andamento" ${v==='Em andamento'?'selected':''}>Em andamento</option>
    <option value="Concluído" ${v==='Concluído'?'selected':''}>Concluído</option>
  </select>`;
}

async function changeEtapa(docId,etapa,novoStatus){
  const td=document.getElementById(`td-${docId}-${etapa}`);
  const sel=td.querySelector('select');
  td.classList.add('loading');
  const localDoc=allDocs.find(d=>d.id===docId);
  const expectedVersion=localDoc?(localDoc.version||0):null;
  try{
    const res=await apiFetch(`/documento/${docId}/status`,{method:'PUT',body:JSON.stringify({etapa,status:novoStatus,version:expectedVersion})});
    const data=await res.json();
    if(res.status===409){
      // B8: optimistic lock — alguém atualizou antes
      showToast('Documento foi alterado por outro usuário. Recarregando…','error');
      if(data.documento&&localDoc){Object.assign(localDoc,data.documento)}
      td.innerHTML=renderEtapaSelect(docId,etapa,data.documento?data.documento[etapa]:novoStatus,true);
      document.getElementById(`td-${docId}-global`).innerHTML=pillGlobal(data.documento?data.documento.status_global:'Pendente');
      td.classList.remove('loading');return;
    }
    if(!res.ok){showToast(data.erro||'Erro de fluxo','error');td.innerHTML=renderEtapaSelect(docId,etapa,data.status_etapa_anterior||'Pendente',true);td.classList.remove('loading');return}
    showToast(`Status atualizado`,'success');
    if(localDoc){
      localDoc[etapa]=novoStatus;
      localDoc.status_global=data.documento.status_global;
      localDoc.version=data.documento.version;
      document.getElementById(`td-${docId}-global`).innerHTML=pillGlobal(localDoc.status_global);
    }
    sel.className='etapa-select '+(novoStatus==='Concluído'?'s-concluido':novoStatus==='Em andamento'?'s-andamento':'s-pendente');
    td.insertAdjacentHTML('beforeend','<div class="cell-feedback">✨</div>');
    setTimeout(()=>{const f=td.querySelector('.cell-feedback');if(f)f.remove()},1000);
  }catch(e){showToast('Erro','error')}
  td.classList.remove('loading');
}

async function delDoc(id,nome){
  const ok=await confirmModal('Excluir documento',`Tem certeza que deseja excluir o documento de "${nome}"? Essa ação pode ser revertida no banco (soft delete).`);
  if(!ok)return;
  try{const res=await apiFetch(`/documentos/${id}`,{method:'DELETE'});if(!res||!res.ok)return;showToast('Excluído','success');await refreshAll()}catch(e){}
}

function openEditDoc(id){
  const d=allDocs.find(x=>x.id===id);if(!d)return;
  document.getElementById('edit-doc-id').value=d.id;
  document.getElementById('edit-doc-equip').value=d.equipamento;
  document.getElementById('edit-doc-nome').value=d.documento;
  document.getElementById('edit-doc-tipo').value=d.tipo_documento;
  document.getElementById('edit-doc-subtipo').value=d.subtipo;
  document.getElementById('edit-doc-cat').value=d.categoria;
  document.getElementById('edit-doc-origem').value=d.origem;
  document.getElementById('edit-doc-versao').value=d.versao;
  document.getElementById('edit-doc-local').value=d.local;
  openModal('edit-doc');
}
async function saveEditDoc(){
  const id=document.getElementById('edit-doc-id').value;
  const payload={
    equipamento:document.getElementById('edit-doc-equip').value,
    documento:document.getElementById('edit-doc-nome').value,
    tipo_documento:document.getElementById('edit-doc-tipo').value,
    subtipo:document.getElementById('edit-doc-subtipo').value,
    categoria:document.getElementById('edit-doc-cat').value,
    origem:document.getElementById('edit-doc-origem').value,
    versao:document.getElementById('edit-doc-versao').value,
    local:document.getElementById('edit-doc-local').value
  };
  try{const res=await apiFetch(`/documentos/${id}`,{method:'PATCH',body:JSON.stringify(payload)});if(res&&res.ok){showToast('Salvo','success');closeModal('edit-doc');await refreshAll()}}catch(e){}
}
async function createDoc(){
  const payload={
    equipamento:document.getElementById('new-doc-equip').value,
    documento:document.getElementById('new-doc-nome').value,
    tipo_documento:document.getElementById('new-doc-tipo').value,
    subtipo:document.getElementById('new-doc-subtipo').value,
    categoria:document.getElementById('new-doc-cat').value,
    origem:document.getElementById('new-doc-origem').value,
    versao:document.getElementById('new-doc-versao').value,
    local:document.getElementById('new-doc-local').value
  };
  if(!payload.equipamento){showToast('Equipamento é obrigatório','error');return}
  try{
    const res=await apiFetch(`/documentos`,{method:'POST',body:JSON.stringify(payload)});
    if(res&&res.ok){
      showToast('Criado','success');
      closeModal('add-doc');
      ['new-doc-equip', 'new-doc-nome', 'new-doc-tipo', 'new-doc-subtipo', 'new-doc-cat', 'new-doc-origem', 'new-doc-versao', 'new-doc-local'].forEach(id => {
        document.getElementById(id).value = '';
      });
      window.selectedTab = payload.origem ? payload.origem : 'Todas as Origens';
      await refreshAll();
    } else {
      const errData = await res.json().catch(() => ({}));
      showToast(errData.erro || errData.message || 'Erro ao criar documento', 'error');
      console.error("Create doc error:", errData);
    }
  }catch(e){
    console.error(e);
    showToast('Erro de rede ou servidor', 'error');
  }
}

// ═══ AUDIT ═══
async function renderAudit(){filterAudit()}
async function filterAudit(){
  let logs=[];
  try{const res=await apiFetch('/audit');if(res&&res.ok)logs=await res.json()}catch(e){}
  const q=(document.getElementById('audit-search').value||'').toLowerCase();
  const a=document.getElementById('audit-filter-action').value;
  if(q)logs=logs.filter(l=>(l.usuario||'').toLowerCase().includes(q)||(l.entidade||'').toLowerCase().includes(q)||(l.campo||'').toLowerCase().includes(q));
  if(a)logs=logs.filter(l=>l.acao===a);
  document.getElementById('audit-list').innerHTML=logs.length?logs.map(l=>{
    let actColor=l.acao==='DELETE'?'var(--red)':l.acao==='CREATE'?'var(--green)':l.acao==='UPDATE'?'var(--cyan)':'var(--purple)';
    return `<div class="audit-item">
      <div class="audit-user">${esc(l.usuario)}</div>
      <div class="audit-action"><span style="color:${actColor};font-family:var(--font-mono);font-size:10px">[${esc(l.acao)}]</span> <strong>${esc(l.entidade)}</strong>
        ${l.campo&&l.campo!=='—'?`<span style="color:var(--t3);font-size:10px"> (${esc(l.campo)}) </span>`:''}
        ${l.valor_antigo?' <span class="old">'+esc(l.valor_antigo)+'</span> → <span class="new">'+esc(l.valor_novo)+'</span>':l.valor_novo?' '+esc(l.valor_novo):''}
      </div><div class="audit-time">${esc(l.timestamp)}</div>
    </div>`}).join(''):'<div style="text-align:center;padding:28px;color:var(--t4);font-size:12px">Nenhum registro</div>';
}

// ═══ USERS ═══
async function renderUsers(){
  document.getElementById('users-list').innerHTML='<div class="loading-state"><div class="spinner"></div>Carregando...</div>';
  try{const res=await apiFetch('/users');if(!res||!res.ok){document.getElementById('users-list').innerHTML='<div style="color:var(--t3);padding:16px;font-size:12px">Sem permissão.</div>';return}_allUsers=await res.json();renderUserCards(_allUsers)}
  catch(e){_allUsers=[];renderUserCards([])}
}
function renderUserCards(users){
  const rh={admin:'<span class="role-admin">Admin</span>',gestor:'<span class="role-gestor">Gestor</span>',tecnico:'<span class="role-tecnico">Técnico</span>',leitura:'<span class="role-leitura">Leitura</span>'};
  const canEdit=currentUser.role==='admin';
  document.getElementById('users-list').innerHTML=users.map(u=>`
    <div class="user-card" style="${!u.ativo?'opacity:.45':''}">
      <div class="uc-avatar">${esc((u.nome||'?').split(' ').map(w=>w[0]).join('').substring(0,2).toUpperCase())}</div>
      <div style="flex:1;min-width:0"><div class="uc-name">${esc(u.nome)}${!u.ativo?' <span style="font-size:10px;color:var(--red)">(inativo)</span>':''}</div><div class="uc-email">${esc(u.email)}</div></div>
      <div>${rh[u.role]||esc(u.role)}</div>
      <div style="text-align:right;min-width:90px"><div style="font-size:10px;color:var(--t4);font-family:var(--font-mono)">último</div><div style="font-size:11px;color:var(--t3);font-family:var(--font-mono)">${esc(u.ultimo_login||'—')}</div></div>
      ${canEdit?`<div class="uc-actions"><button class="btn btn-ghost btn-sm" type="button" data-action="edit-user" data-id="${u.id}" aria-label="Editar usuário">Editar</button>${u.ativo&&u.email!==currentUser.email?`<button class="btn btn-danger btn-sm" type="button" data-action="delete-user" data-id="${u.id}" data-name="${esc(u.nome)}" aria-label="Desativar usuário">×</button>`:''}</div>`:''}
    </div>`).join('')||'<div style="color:var(--t4);padding:16px;font-size:12px">Nenhum usuário.</div>';
}
function openEditUser(id){
  const u=_allUsers.find(x=>x.id===id);if(!u)return;
  document.getElementById('edit-user-id').value=u.id;document.getElementById('edit-user-nome').value=u.nome;
  document.getElementById('edit-user-email').value=u.email;document.getElementById('edit-user-role').value=u.role;
  document.getElementById('edit-user-senha').value='';openModal('edit-user');
}
async function saveEditUser(){
  const id=parseInt(document.getElementById('edit-user-id').value),nome=document.getElementById('edit-user-nome').value.trim(),
    email=document.getElementById('edit-user-email').value.trim(),role=document.getElementById('edit-user-role').value,
    senha=document.getElementById('edit-user-senha').value.trim();
  if(!nome||!email){showToast('Preencha nome e email','error');return}
  const p={nome,email,role};if(senha)p.senha=senha;
  try{const res=await apiFetch(`/users/${id}`,{method:'PATCH',body:JSON.stringify(p)});const data=await res.json();if(!res.ok){showToast(data.erro||'Erro','error');return}showToast('Atualizado','success');closeModal('edit-user');renderUsers()}catch(e){showToast('Erro','error')}
}
async function confirmDeleteUser(id,nome){
  const ok=await confirmModal('Desativar usuário',`Desativar o usuário "${nome}"? Ele não poderá mais acessar o sistema.`);
  if(!ok)return;
  try{const res=await apiFetch(`/users/${id}`,{method:'DELETE'});if(!res||!res.ok){showToast('Erro','error');return}showToast(nome+' desativado','success');renderUsers()}catch(e){showToast('Erro','error')}
}
async function createUser(){
  const nome=document.getElementById('new-user-nome').value.trim(),email=document.getElementById('new-user-email').value.trim(),
    role=document.getElementById('new-user-role').value,senha=document.getElementById('new-user-senha').value.trim();
  if(!nome||!email||!senha){showToast('Preencha tudo','error');return}
  try{const res=await apiFetch('/users',{method:'POST',body:JSON.stringify({nome,email,role,senha})});const data=await res.json();if(!res.ok){showToast(data.erro||'Erro','error');return}showToast('Criado','success');closeModal('add-user');['new-user-nome','new-user-email','new-user-senha'].forEach(id=>{const el=document.getElementById(id);if(el)el.value=''});renderUsers()}catch(e){showToast('Erro','error')}
}

// ═══ HELPERS ═══
function showToast(msg,type='info'){
  const t=document.getElementById('toast'),d=document.getElementById('toast-dot'),m=document.getElementById('toast-msg');
  d.style.background=type==='success'?'var(--green)':type==='error'?'var(--red)':'var(--cyan)';
  m.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3200);
}
// ═══ Modal accessibility (U1: foco-trap, ESC, ARIA) ═══
let _previousFocus=null;
function openModal(id){
  const m=document.getElementById('modal-'+id);
  if(!m)return;
  _previousFocus=document.activeElement;
  m.classList.add('open');
  m.setAttribute('aria-hidden','false');
  // foco no primeiro input focável
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

// ESC fecha + foco-trap (Tab cycle dentro do modal aberto)
document.addEventListener('keydown',(e)=>{
  const openOverlay=document.querySelector('.modal-overlay.open, .confirm-modal.open');
  if(e.key==='Escape'){
    if(openOverlay){
      if(openOverlay.classList.contains('confirm-modal')){_confirmReject()}
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

// ═══ U8: confirm() customizado (Promise) ═══
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

// ═══ U6: Sidebar responsiva ═══
const _sidebarToggle=document.getElementById('sidebar-toggle');
const _sidebarBackdrop=document.getElementById('sidebar-backdrop');
const _sidebar=document.getElementById('sidebar-nav');
function toggleSidebar(force){
  if(!_sidebar)return;
  const willOpen=force!==undefined?force:!_sidebar.classList.contains('open');
  _sidebar.classList.toggle('open',willOpen);
  _sidebarBackdrop.classList.toggle('open',willOpen);
  _sidebarToggle.setAttribute('aria-expanded',String(willOpen));
}
_sidebarToggle?.addEventListener('click',()=>toggleSidebar());
_sidebarBackdrop?.addEventListener('click',()=>toggleSidebar(false));
// Fechar ao navegar (mobile)
document.querySelectorAll('.nav-item[data-page]').forEach(el=>el.addEventListener('click',()=>{if(window.innerWidth<=900)toggleSidebar(false)}));

// ═══ U18: sort de tabela (clica no th.sortable) ═══
let _sortState={col:null,dir:1};
function makeSortable(){
  document.querySelectorAll('#docs-tbody').forEach(()=>{});
  const ths=document.querySelectorAll('table thead th');
  ths.forEach((th,idx)=>{
    if(!th.dataset.sortable)return;
    th.classList.add('sortable');
    th.setAttribute('role','button');
    th.setAttribute('tabindex','0');
    th.setAttribute('aria-label','Ordenar por '+th.textContent.trim());
    const handler=()=>{
      const key=th.dataset.sortable;
      _sortState.dir=(_sortState.col===key)?-_sortState.dir:1;
      _sortState.col=key;
      ths.forEach(t=>t.classList.remove('sort-asc','sort-desc'));
      th.classList.add(_sortState.dir>0?'sort-asc':'sort-desc');
      filterDocs();
    };
    th.onclick=handler;
    th.onkeydown=(e)=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();handler()}};
  });
}

// Aplica sort à lista localmente (front-side, depois do fetch)
function applySort(arr){
  if(!_sortState.col)return arr;
  const key=_sortState.col, dir=_sortState.dir;
  return [...arr].sort((a,b)=>{
    const va=(a[key]??'').toString().toLowerCase();
    const vb=(b[key]??'').toString().toLowerCase();
    return va<vb?-dir:va>vb?dir:0;
  });
}

// ═══ U16: skeleton loader ═══
function renderSkeletonTable(tbodyId,rows=5,cols=5){
  const tb=document.getElementById(tbodyId);if(!tb)return;
  tb.innerHTML=Array(rows).fill(0).map(()=>
    `<tr class="skeleton-row">${Array(cols).fill(0).map(()=>'<td><span class="skeleton"></span></td>').join('')}</tr>`
  ).join('');
}
