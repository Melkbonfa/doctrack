const API='/api';
let allDocs=[],chartInstances={},currentUser={name:'Admin',email:'admin@pde.com',role:'admin',initials:'A'};
let selectedRole='admin',_allUsers=[],_enums={},_lastKpis=null;
let _filterTimer=null;
let _currentSetor = 'PRE';

const CAT_COLORS={'PRE':'#22d3ee','Fabricante':'#a855f7','PDE':'#ec4899'};
const STATUS_PILL={'Elaborar':'pill-elab','Homologado':'pill-ok','Enviado para Homologação':'pill-wip','Treinamento Piloto':'pill-warn','Concluído':'pill-ok','Em andamento':'pill-wip'};

function esc(str){
  if(str==null)return'';
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function norm(s){
  if(s==null)return'';
  return String(s).trim().toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g,'');
}

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

document.body.addEventListener('change',(e)=>{
  const sel=e.target.closest('select.etapa-select');
  if(sel){
    const docId=parseInt(sel.dataset.docId);
    changeStatus(docId,sel.value);
    return;
  }
  const filterIds=['docs-filter-status'];
  if(e.target&&filterIds.includes(e.target.id)){filterDocs();return}
  if(e.target&&e.target.id==='audit-filter-action'){filterAudit();return}
});

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
  renderSkeletonTable('dash-table',5,5);
  renderSkeletonTable('docs-tbody',6,8);
  await loadEnums();
  await loadData();
  
  // Setup tabs
  document.querySelectorAll('.docs-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.docs-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _currentSetor = btn.dataset.setor;
      populateFilters();
      filterDocs();
    });
  });

  renderDashboard();renderDocs();renderAudit();renderUsers();
  makeSortable();
  showToast('Bem-vindo ao DocTrack v4.0','success');
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
  
  // Visibility rules
  if(rl==='leitura') {
    document.getElementById('btn-add-doc-pre').style.display='none';
    document.getElementById('btn-add-doc-fab').style.display='none';
    document.getElementById('btn-add-doc-pde').style.display='none';
  }
  if(rl==='admin' || rl==='gestor') {
      const btnExp = document.getElementById('btn-export-kpis');
      if(btnExp) btnExp.style.display='block';
  }
}

function exportKPIs() {
    showToast('Gerando PDF...', 'info');
    document.getElementById('rep-date').textContent = new Date().toLocaleString('pt-BR');
    
    if(!_lastKpis) return;
    const total = _lastKpis.total || 0;
    document.getElementById('rep-total').textContent = total;
    document.getElementById('rep-fin').textContent = _lastKpis.global_counts['Finalizado'] || 0;
    document.getElementById('rep-prog').textContent = _lastKpis.global_counts['Em progresso'] || 0;
    document.getElementById('rep-pend').textContent = _lastKpis.global_counts['Pendente'] || 0;

    // Table
    const tb = document.getElementById('rep-table-body');
    const setores = Object.keys(_lastKpis.por_setor);
    tb.innerHTML = setores.map(s => {
        const qtd = _lastKpis.por_setor[s] || 0;
        const pct = total ? Math.round(qtd / total * 100) : 0;
        // Count concluidos per sector
        const concl = _lastKpis.status_counts[s] ? (_lastKpis.status_counts[s]['Concluído'] || _lastKpis.status_counts[s]['Homologado'] || 0) : 0;
        return `<tr>
          <td style="padding: 10px; border-bottom: 1px solid #e5e7eb;">${esc(s)}</td>
          <td style="padding: 10px; border-bottom: 1px solid #e5e7eb; text-align: center;">${qtd}</td>
          <td style="padding: 10px; border-bottom: 1px solid #e5e7eb; text-align: center;">${pct}%</td>
          <td style="padding: 10px; border-bottom: 1px solid #e5e7eb; text-align: center;">${concl}</td>
        </tr>`;
    }).join('');

    // Charts
    if(window._repCharts) window._repCharts.forEach(c => c.destroy());
    window._repCharts = [];

    const gCtx = document.getElementById('rep-chart-global').getContext('2d');
    const sCtx = document.getElementById('rep-chart-setor').getContext('2d');
    const stCtx = document.getElementById('rep-chart-status').getContext('2d');
    
    const ringColors=['#10b981','#22d3ee','#a855f7'];
    const gData = ['Finalizado', 'Em progresso', 'Pendente'].map(k => _lastKpis.global_counts[k] || 0);

    window._repCharts.push(new Chart(gCtx, {
        type: 'doughnut',
        data: { labels: ['Finalizado', 'Em progresso', 'Pendente'], datasets: [{ data: gData, backgroundColor: ringColors }] },
        options: { responsive: true, maintainAspectRatio: false }
    }));

    const catLabels = Object.keys(_lastKpis.por_setor), catVals = Object.values(_lastKpis.por_setor);
    const dColors = catLabels.map(c => CAT_COLORS[c] || '#6366f1');
    window._repCharts.push(new Chart(sCtx, {
        type: 'doughnut',
        data: { labels: catLabels, datasets: [{ data: catVals, backgroundColor: dColors }] },
        options: { responsive: true, maintainAspectRatio: false }
    }));

    const flatStatus = {};
    Object.values(_lastKpis.status_counts).forEach(sc => {
        Object.keys(sc).forEach(k => flatStatus[k] = (flatStatus[k]||0) + sc[k]);
    });
    const stLabels = Object.keys(flatStatus), stVals = Object.values(flatStatus);
    const stColors = stLabels.map(s => STATUS_PILL[s] ? (s === 'Elaborar' ? '#a855f7' : s.includes('Homologado') || s === 'Concluído' ? '#10b981' : '#22d3ee') : '#ec4899');
    
    window._repCharts.push(new Chart(stCtx, {
        type: 'bar',
        data: { labels: stLabels, datasets: [{ data: stVals, backgroundColor: stColors }] },
        options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
    }));

    setTimeout(() => {
        const el = document.getElementById('pdf-report-container');
        html2pdf().set({
            margin: 10,
            filename: 'DocTrack_KPIs.pdf',
            image: { type: 'jpeg', quality: 1 },
            html2canvas: { scale: 2, useCORS: true },
            jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
        }).from(el).save().then(() => showToast('PDF Gerado', 'success'));
    }, 500);
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
      _lastKpis=data.kpis||null;
      return;
    }
  }catch(e){}
  allDocs=[];_lastKpis=null;
}
async function refreshAll(){await loadData();renderDashboard();renderDocs();showToast('Dados atualizados','success');
  document.getElementById('sync-label').textContent='Atualizado · '+new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
}

async function reimportExcel() {
    const ok = await confirmModal('Sincronizar Planilha', 'Isso irá limpar os documentos antigos e carregar todos os dados novamente da planilha excel. Deseja continuar?');
    if(!ok) return;
    try {
        const res = await apiFetch('/reimport', {method: 'POST'});
        if(!res) {
            showToast('Erro de rede ou servidor não responde', 'error');
            return;
        }
        let data = {};
        try { data = await res.json(); } catch(e) { 
            // Se o servidor retornar HTML (ex: 404, 500), tratamos aqui
            data = {erro: `Erro no servidor (Status: ${res.status})`}; 
        }
        
        if(res.ok) {
            showToast(data.mensagem || 'Planilha sincronizada com sucesso!', 'success');
        } else {
            showToast(data.erro || 'Erro ao sincronizar planilha', 'error');
        }
    } catch(e) {
        showToast('Erro de rede', 'error');
    }
}

// ═══ DASHBOARD ═══
function renderDashboard(){
  if(!_lastKpis) return;
  const total=_lastKpis.total;
  
  document.getElementById('dash-updated').textContent='Última atualização: '+new Date().toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
  document.getElementById('dash-pct-badge').textContent=total+' documentos';

  const ringColors=['#10b981','#22d3ee','#a855f7'];
  const ringBgs=['rgba(16,185,129,.15)','rgba(34,211,238,.15)','rgba(168,85,247,.15)'];
  const sgKeys=['Finalizado','Em progresso','Pendente'];
  let kpiHTML='';
  sgKeys.forEach((k,i)=>{
    const v=_lastKpis.global_counts[k]||0,pct=total?Math.round(v/total*100):0;
    kpiHTML+=`<div class="kpi-ring">
      <div class="kpi-ring-canvas" style="width:110px;height:110px"><canvas id="ring${i}" width="110" height="110"></canvas><div class="kpi-ring-val" style="color:${ringColors[i]}">${v}</div></div>
      <div class="kpi-ring-label">${esc(k)}</div>
      <div class="kpi-ring-delta" style="color:${ringColors[i]}">${pct}% do total</div>
    </div>`;
  });
  document.getElementById('kpi-grid').innerHTML=kpiHTML||'<div class="loading-state" style="grid-column:1/-1">Sem dados</div>';

  sgKeys.forEach((k,i)=>{
    const v=_lastKpis.global_counts[k]||0,pct=total?v/total:0;
    if(chartInstances['ring'+i])chartInstances['ring'+i].destroy();
    chartInstances['ring'+i]=new Chart(document.getElementById('ring'+i),{
      type:'doughnut',data:{datasets:[{data:[pct*100,100-pct*100],backgroundColor:[ringColors[i],ringBgs[i]],borderWidth:0,hoverOffset:4}]},
      options:{responsive:false,cutout:'78%',plugins:{legend:{display:false},tooltip:{enabled:false}},animation:{animateRotate:true,duration:1200}}
    });
  });

  const catLabels=Object.keys(_lastKpis.por_setor),catVals=Object.values(_lastKpis.por_setor);
  const dColors=catLabels.map(c=>CAT_COLORS[c]||'#6366f1');
  document.getElementById('donut-total').textContent=total;
  document.getElementById('donut-legend').innerHTML=catLabels.map((c,i)=>{
    return`<div class="legend-row" title="${esc(c)}"><span class="legend-dot" style="background:${dColors[i]}"></span><span>${esc(c)}</span><span class="legend-val">${catVals[i]}</span></div>`;
  }).join('');
  if(chartInstances.donut)chartInstances.donut.destroy();
  chartInstances.donut=new Chart(document.getElementById('cDonut'),{
    type:'doughnut',data:{datasets:[{data:catVals,backgroundColor:dColors,borderWidth:3,borderColor:'#1f2444',hoverOffset:8}]},
    options:{responsive:false,cutout:'72%',plugins:{legend:{display:false},tooltip:{backgroundColor:'#232847',titleColor:'#f1f5f9',bodyColor:'#c7d2fe',borderColor:'rgba(167,139,250,.3)',borderWidth:1,padding:10,cornerRadius:8,callbacks:{label:ctx=>' '+catLabels[ctx.dataIndex]+': '+ctx.raw}}}}
  });

  // Exemplo de pipeline simples usando os status da PRE
  const etapaNames=_enums.status_map?_enums.status_map['PRE']:[];
  const preStatusCounts = _lastKpis.status_counts['PRE'] || {};
  const preTotal = catLabels.indexOf('PRE') >= 0 ? catVals[catLabels.indexOf('PRE')] : 0;
  const etapaColors=['#a855f7','#f59e0b','#22d3ee','#10b981'];
  
  if(etapaNames.length > 0) {
    document.getElementById('prog-list').innerHTML=etapaNames.map((n,i)=>{
      const val = preStatusCounts[n] || 0;
      const pct=preTotal?Math.round(val/preTotal*100):0;
      return`<div class="prog-row"><span class="prog-label">${esc(n)}</span><div class="prog-track"><div class="prog-fill" style="width:${pct}%;background:${etapaColors[i]||'#fff'}"></div></div><span class="prog-pct">${val}</span></div>`;
    }).join('')+`<div style="margin-top:14px;padding-top:10px;border-top:1px solid var(--border-dim);display:flex;justify-content:space-between"><span style="font-size:10px;color:var(--t3)">Total PRE</span><span style="font-family:var(--font-mono);font-size:14px;font-weight:700;color:var(--cyan)">${preTotal}</span></div>`;
  }

  // Bar chart - Setores
  if(chartInstances.bar)chartInstances.bar.destroy();
  const ctxBar=document.getElementById('chartBar').getContext('2d');
  const gradBar=ctxBar.createLinearGradient(0,0,0,200);
  gradBar.addColorStop(0,'#22d3ee');gradBar.addColorStop(1,'#3b82f6');
  chartInstances.bar=new Chart(ctxBar,{
    type:'bar',data:{labels:catLabels,datasets:[{data:catVals,backgroundColor:gradBar,borderRadius:8,borderWidth:0}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{backgroundColor:'#232847',titleColor:'#f1f5f9',bodyColor:'#c7d2fe',borderColor:'rgba(167,139,250,.3)',borderWidth:1,padding:10,cornerRadius:8}},
      scales:{x:{ticks:{color:'#94a3ff',font:{size:10,family:'Inter'}},grid:{display:false},border:{display:false}},
              y:{ticks:{color:'#94a3ff',font:{size:10,family:'Inter'},stepSize:20},grid:{color:'rgba(167,139,250,.06)'},border:{display:false}}}}
  });

  // Flatten status para chart de status
  const flatStatus = {};
  Object.values(_lastKpis.status_counts).forEach(sc => {
    Object.keys(sc).forEach(k => flatStatus[k] = (flatStatus[k]||0) + sc[k]);
  });
  const stLabels=Object.keys(flatStatus),stVals=Object.values(flatStatus);
  const stColors=stLabels.map(s=>STATUS_PILL[s] ? (s==='Elaborar'?'#a855f7':s.includes('Homologado')||s==='Concluído'?'#10b981':'#22d3ee') : '#ec4899');
  
  if(chartInstances.status)chartInstances.status.destroy();
  chartInstances.status=new Chart(document.getElementById('chartStatus'),{
    type:'bar',data:{labels:stLabels.map(l=>l.length>18?l.substring(0,18)+'…':l),datasets:[{data:stVals,backgroundColor:stColors,borderRadius:8,borderWidth:0}]},
    options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{backgroundColor:'#232847',titleColor:'#f1f5f9',bodyColor:'#c7d2fe',borderColor:'rgba(167,139,250,.3)',borderWidth:1,padding:10,cornerRadius:8}},
      scales:{x:{ticks:{color:'#94a3ff',font:{size:10,family:'Inter'}},grid:{color:'rgba(167,139,250,.06)'},border:{display:false}},
              y:{ticks:{color:'#c7d2fe',font:{size:11,family:'Inter',weight:'500'}},grid:{display:false},border:{display:false}}}}
  });

  document.getElementById('dash-table').innerHTML=allDocs.slice(0,10).map(d=>
    `<tr><td class="bold">${esc(d.equipamento)}</td><td style="font-size:11px;color:var(--t2)" title="${esc(d.documento||'')}">${esc((d.documento||'—').substring(0,40))}</td><td><span class="pill pill-elab">${esc(d.setor)}</span></td><td>${pillGlobal(d.status_global)}</td><td class="mono">${esc(d.sku||'—')}</td></tr>`
  ).join('')||'<tr><td colspan="5" style="text-align:center;color:var(--t4);padding:32px">Sem dados</td></tr>';
}

function pillCls(c){if(!c)return'pill-elab';if(c.includes('PRE'))return'pill-wip';if(c.includes('Fabricante'))return'pill-elab';return'pill-warn'}
function pillSt(s){if(!s)return'<span style="color:var(--t4)">—</span>';const cls=STATUS_PILL[s]||'pill-elab';return`<span class="pill ${cls}">${esc(s)}</span>`}
function pillGlobal(s){
  if(s==='Finalizado')return'<span class="sg-badge sg-finalizado">Finalizado</span>';
  if(s==='Em progresso')return'<span class="sg-badge sg-progresso">Progresso</span>';
  return'<span class="sg-badge sg-pendente">Pendente</span>';
}

function renderLink(url) {
    if(!url || url === '—') return '—';
    return `<a href="${esc(url)}" target="_blank" title="Abrir localização do arquivo" style="color:var(--cyan);text-decoration:none"><svg width="14" height="14" fill="none" viewBox="0 0 24 24"><path d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></a>`;
}

// ═══ DOCS TABLE ═══
function renderDocs(){
  populateFilters();
  filterDocs();
}

function populateFilters(){
  if(!_enums.status_map) return;
  const statuses = _enums.status_map[_currentSetor] || [];
  const opt=(arr)=>arr.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');
  document.getElementById('docs-filter-status').innerHTML='<option value="">Status: Todos</option>'+opt(statuses);
  
  // Render THEAD based on Setor
  let thHtml = '';
  if(_currentSetor === 'PRE') {
      thHtml = `<tr>
        <th data-sortable="equipamento">Equipamento</th><th data-sortable="sku">SKU</th><th data-sortable="codigo_doc">Código Doc</th>
        <th data-sortable="responsavel">Responsável</th><th data-sortable="status">Status</th>
        <th data-sortable="data_treinamento">Trein. Piloto</th><th data-sortable="data_homologacao">Envio Homol.</th>
        <th>Ações</th>
      </tr>`;
  } else if (_currentSetor === 'Fabricante') {
      thHtml = `<tr>
        <th data-sortable="equipamento">Equipamento</th><th data-sortable="fabricante">Fabricante</th><th data-sortable="sku">SKU</th>
        <th data-sortable="codigo_doc">Código Doc</th><th data-sortable="tipo_doc_label">Documento</th><th data-sortable="status">Status</th>
        <th>Ações</th>
      </tr>`;
  } else if (_currentSetor === 'PDE') {
      thHtml = `<tr>
        <th data-sortable="documento">Documento</th><th data-sortable="codigo_doc">Código Doc</th><th data-sortable="status">Status</th>
        <th>Ações</th>
      </tr>`;
  }
  document.getElementById('docs-thead').innerHTML = thHtml;
  makeSortable();
}

async function filterDocs(){
  const q=document.getElementById('docs-search').value.trim();
  const st=document.getElementById('docs-filter-status').value;

  renderSkeletonTable('docs-tbody',6,8);

  let data=allDocs.filter(d => d.setor === _currentSetor);
  if(st) data = data.filter(d => d.status === st);
  if(q) {
      data = data.filter(d => {
          const blob = [d.equipamento, d.documento, d.sku, d.codigo_doc, d.responsavel, d.fabricante, d.tipo_doc_label].join(' ').toLowerCase();
          return blob.includes(q.toLowerCase());
      });
  }

  data=applySort(data);

  document.getElementById('docs-badge').textContent=data.length+' docs';
  const canEdit=currentUser.role!=='leitura';
  
  let tbHtml = '';
  if(_currentSetor === 'PRE') {
      tbHtml = data.map(d=>`<tr>
        <td class="bold">${esc(d.equipamento)}</td><td class="mono">${esc(d.sku)}</td><td class="mono">${esc(d.codigo_doc)}</td>
        <td>${esc(d.responsavel)}</td>
        <td id="td-${d.id}-status">${renderStatusSelect(d.id, d.status, canEdit)}</td>
        <td>${esc(d.data_treinamento)}</td><td>${esc(d.data_homologacao)}</td>
        <td>
          <div class="row-actions">
            ${renderLink(d.armazenamento)}
            ${canEdit?`<button class="btn-edit" type="button" data-action="edit-doc" data-id="${d.id}" aria-label="Editar">Editar</button><button class="btn-del" type="button" data-action="delete-doc" data-id="${d.id}" aria-label="Excluir">×</button>`:''}
          </div>
        </td>
      </tr>`).join('');
  } else if (_currentSetor === 'Fabricante') {
      tbHtml = data.map(d=>`<tr>
        <td class="bold">${esc(d.equipamento)}</td><td>${esc(d.fabricante)}</td><td class="mono">${esc(d.sku)}</td>
        <td class="mono">${esc(d.codigo_doc)}</td><td>${esc(d.tipo_doc_label)}</td>
        <td id="td-${d.id}-status">${renderStatusSelect(d.id, d.status, canEdit)}</td>
        <td>
          <div class="row-actions">
            ${renderLink(d.armazenamento)}
            ${canEdit?`<button class="btn-edit" type="button" data-action="edit-doc" data-id="${d.id}" aria-label="Editar">Editar</button><button class="btn-del" type="button" data-action="delete-doc" data-id="${d.id}" aria-label="Excluir">×</button>`:''}
          </div>
        </td>
      </tr>`).join('');
  } else if (_currentSetor === 'PDE') {
      tbHtml = data.map(d=>`<tr>
        <td class="bold">${esc(d.documento)}</td><td class="mono">${esc(d.codigo_doc)}</td>
        <td id="td-${d.id}-status">${renderStatusSelect(d.id, d.status, canEdit)}</td>
        <td>
          <div class="row-actions">
            ${renderLink(d.armazenamento)}
            ${canEdit?`<button class="btn-edit" type="button" data-action="edit-doc" data-id="${d.id}" aria-label="Editar">Editar</button><button class="btn-del" type="button" data-action="delete-doc" data-id="${d.id}" aria-label="Excluir">×</button>`:''}
          </div>
        </td>
      </tr>`).join('');
  }
  
  document.getElementById('docs-tbody').innerHTML = tbHtml || `<tr><td colspan="8" style="text-align:center;color:var(--t4);padding:32px">Nenhum resultado</td></tr>`;
}

function getStatusClass(v) {
    if(!v) return 's-elaborar';
    const lower = v.toLowerCase();
    if(lower.includes('homologado') || lower === 'concluído') return 's-concluido';
    if(lower.includes('homologação')) return 's-homologacao';
    if(lower.includes('piloto') || lower === 'em andamento') return 's-treinamento';
    return 's-elaborar';
}

function renderStatusSelect(docId, val, canEdit) {
    const v=val||'Elaborar';
    const cls = getStatusClass(v);
    
    // Fallback pra exibição sem dropdown
    if(!canEdit) {
        let pCls = 'pill-elab';
        if (cls === 's-concluido') pCls = 'pill-ok';
        else if (cls === 's-homologacao') pCls = 'pill-wip';
        else if (cls === 's-treinamento') pCls = 'pill-warn';
        return `<span class="pill ${pCls}" style="font-size:9px">${esc(v)}</span>`;
    }
    
    const options = _enums.status_map[_currentSetor].map(opt => `<option value="${esc(opt)}" ${v===opt?'selected':''}>${esc(opt)}</option>`).join('');
    
    return `<select class="etapa-select ${cls}" data-doc-id="${docId}" aria-label="Status">
      ${options}
    </select>`;
}

async function changeStatus(docId, novoStatus){
  const td=document.getElementById(`td-${docId}-status`);
  const sel=td.querySelector('select');
  td.classList.add('loading');
  const localDoc=allDocs.find(d=>d.id===docId);
  const expectedVersion=localDoc?(localDoc.version||0):null;
  try{
    const res=await apiFetch(`/documento/${docId}/status`,{method:'PUT',body:JSON.stringify({status:novoStatus,version:expectedVersion})});
    const data=await res.json();
    if(res.status===409){
      showToast('Documento foi alterado por outro usuário. Recarregando…','error');
      if(data.documento&&localDoc){Object.assign(localDoc,data.documento)}
      td.innerHTML=renderStatusSelect(docId,data.documento?data.documento.status:novoStatus,true);
      td.classList.remove('loading');return;
    }
    if(!res.ok){showToast(data.erro||'Erro','error');td.innerHTML=renderStatusSelect(docId,localDoc.status,true);td.classList.remove('loading');return}
    showToast(`Status atualizado`,'success');
    if(localDoc){
      localDoc.status=novoStatus;
      localDoc.status_global=data.documento.status_global;
      localDoc.version=data.documento.version;
    }
    const cls = getStatusClass(novoStatus);
    sel.className='etapa-select '+cls;
    td.insertAdjacentHTML('beforeend','<div class="cell-feedback">✨</div>');
    setTimeout(()=>{const f=td.querySelector('.cell-feedback');if(f)f.remove()},1000);
  }catch(e){showToast('Erro','error')}
  td.classList.remove('loading');
}

async function delDoc(id,nome){
  const ok=await confirmModal('Excluir documento',`Tem certeza que deseja excluir o documento? Essa ação pode ser revertida no banco (soft delete).`);
  if(!ok)return;
  try{const res=await apiFetch(`/documentos/${id}`,{method:'DELETE'});if(!res||!res.ok)return;showToast('Excluído','success');await refreshAll()}catch(e){}
}

function configureDocModal(setor) {
    document.getElementById('doc-setor').value = setor;
    document.getElementById('modal-doc-sub').textContent = `Setor: ${setor}`;
    
    // reset visibilities
    document.getElementById('row-datas-pre').style.display = 'none';
    document.getElementById('row-obs-pre').style.display = 'none';
    document.getElementById('row-resp-fab').style.display = 'none';
    document.getElementById('fg-sku').style.display = 'none';
    document.getElementById('fg-equipamento').style.display = 'none';
    document.getElementById('fg-responsavel').style.display = 'none';
    document.getElementById('fg-fabricante').style.display = 'none';
    document.getElementById('fg-tipo_doc').style.display = 'none';
    
    if(setor === 'PRE') {
        document.getElementById('row-datas-pre').style.display = 'flex';
        document.getElementById('row-obs-pre').style.display = 'flex';
        document.getElementById('fg-sku').style.display = 'block';
        document.getElementById('fg-equipamento').style.display = 'block';
        document.getElementById('row-resp-fab').style.display = 'flex';
        document.getElementById('fg-responsavel').style.display = 'block';
    } else if(setor === 'Fabricante') {
        document.getElementById('fg-sku').style.display = 'block';
        document.getElementById('fg-equipamento').style.display = 'block';
        document.getElementById('row-resp-fab').style.display = 'flex';
        document.getElementById('fg-fabricante').style.display = 'block';
        document.getElementById('fg-tipo_doc').style.display = 'block';
        
        const selTipo = document.getElementById('doc-tipo_doc');
        selTipo.innerHTML = _enums.tipos_doc_fabricante.map(t => `<option value="${t}">${_enums.tipos_doc_labels[t]}</option>`).join('');
    } else if(setor === 'PDE') {
        // Just Document, Codigo, and Armazenamento
    }
}

function openModal(id) {
    if(id.startsWith('add-doc-')) {
        const setorMap = {'add-doc-pre': 'PRE', 'add-doc-fab': 'Fabricante', 'add-doc-pde': 'PDE'};
        configureDocModal(setorMap[id]);
        document.getElementById('doc-id').value = '';
        ['doc-equipamento', 'doc-documento', 'doc-sku', 'doc-codigo', 'doc-responsavel', 'doc-fabricante', 'doc-data_treinamento', 'doc-data_homologacao', 'doc-obs_treinamento', 'doc-obs_homologacao', 'doc-armazenamento'].forEach(f => {
            const el = document.getElementById(f);
            if(el) el.value = '';
        });
        openBaseModal('doc');
        return;
    }
    openBaseModal(id);
}

function openEditDoc(id){
  const d=allDocs.find(x=>x.id===id);if(!d)return;
  configureDocModal(d.setor);
  
  document.getElementById('doc-id').value=d.id;
  document.getElementById('doc-equipamento').value=d.equipamento;
  document.getElementById('doc-documento').value=d.documento;
  document.getElementById('doc-sku').value=d.sku;
  document.getElementById('doc-codigo').value=d.codigo_doc;
  document.getElementById('doc-responsavel').value=d.responsavel;
  document.getElementById('doc-fabricante').value=d.fabricante;
  document.getElementById('doc-tipo_doc').value=d.tipo_doc;
  
  // input date formats
  if(d.data_treinamento) {
      const parts = d.data_treinamento.split('/');
      if(parts.length===3) document.getElementById('doc-data_treinamento').value = `${parts[2]}-${parts[1]}-${parts[0]}`;
  }
  if(d.data_homologacao) {
      const parts = d.data_homologacao.split('/');
      if(parts.length===3) document.getElementById('doc-data_homologacao').value = `${parts[2]}-${parts[1]}-${parts[0]}`;
  }
  
  document.getElementById('doc-obs_treinamento').value=d.obs_treinamento;
  document.getElementById('doc-obs_homologacao').value=d.obs_homologacao;
  document.getElementById('doc-armazenamento').value=d.armazenamento;
  
  openBaseModal('doc');
}

async function saveDoc(){
  const id=document.getElementById('doc-id').value;
  const payload={
    setor: document.getElementById('doc-setor').value,
    equipamento:document.getElementById('doc-equipamento').value,
    documento:document.getElementById('doc-documento').value,
    sku:document.getElementById('doc-sku').value,
    codigo_doc:document.getElementById('doc-codigo').value,
    responsavel:document.getElementById('doc-responsavel').value,
    fabricante:document.getElementById('doc-fabricante').value,
    tipo_doc:document.getElementById('doc-tipo_doc').value,
    data_treinamento:document.getElementById('doc-data_treinamento').value,
    data_homologacao:document.getElementById('doc-data_homologacao').value,
    obs_treinamento:document.getElementById('doc-obs_treinamento').value,
    obs_homologacao:document.getElementById('doc-obs_homologacao').value,
    armazenamento:document.getElementById('doc-armazenamento').value
  };
  
  if(payload.setor !== 'PDE' && !payload.equipamento){showToast('Equipamento é obrigatório','error');return}
  if(!payload.documento){showToast('Documento é obrigatório','error');return}

  try{
    const method = id ? 'PATCH' : 'POST';
    const url = id ? `/documentos/${id}` : `/documentos`;
    const res=await apiFetch(url,{method:method,body:JSON.stringify(payload)});
    if(res&&res.ok){
      showToast('Salvo','success');
      closeModal('doc');
      _currentSetor = payload.setor;
      document.querySelectorAll('.docs-tab').forEach(b => {
          b.classList.remove('active');
          if(b.dataset.setor === payload.setor) b.classList.add('active');
      });
      await refreshAll();
    } else {
        const errData = await res.json().catch(() => ({}));
        showToast(errData.erro || errData.message || 'Erro ao salvar documento', 'error');
    }
  }catch(e){showToast('Erro de rede ou servidor', 'error')}
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

function exportAudit() {
    window.location.href = API + '/export/audit?token=' + getToken();
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
  const cb=document.getElementById('edit-user-ativo');if(cb)cb.checked=u.ativo;
  document.getElementById('edit-user-senha').value='';openBaseModal('edit-user');
}
async function saveEditUser(){
  const id=parseInt(document.getElementById('edit-user-id').value),nome=document.getElementById('edit-user-nome').value.trim(),
    email=document.getElementById('edit-user-email').value.trim(),role=document.getElementById('edit-user-role').value,
    senha=document.getElementById('edit-user-senha').value.trim();
  const cb=document.getElementById('edit-user-ativo');
  const ativo=cb?cb.checked:true;
  if(!nome||!email){showToast('Preencha nome e email','error');return}
  const p={nome,email,role,ativo};if(senha)p.senha=senha;
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
let _previousFocus=null;
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
document.querySelectorAll('.nav-item[data-page]').forEach(el=>el.addEventListener('click',()=>{if(window.innerWidth<=900)toggleSidebar(false)}));

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

function applySort(arr){
  if(!_sortState.col)return arr;
  const key=_sortState.col, dir=_sortState.dir;
  return [...arr].sort((a,b)=>{
    const va=(a[key]??'').toString().toLowerCase();
    const vb=(b[key]??'').toString().toLowerCase();
    return va<vb?-dir:va>vb?dir:0;
  });
}

function renderSkeletonTable(tbodyId,rows=5,cols=5){
  const tb=document.getElementById(tbodyId);if(!tb)return;
  tb.innerHTML=Array(rows).fill(0).map(()=>
    `<tr class="skeleton-row">${Array(cols).fill(0).map(()=>'<td><span class="skeleton"></span></td>').join('')}</tr>`
  ).join('');
}
