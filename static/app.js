const API='/api';
let allDocs=[],chartInstances={},currentUser={name:'Admin',email:'admin@pde.com',role:'admin',initials:'A'};
let selectedRole='admin',_allUsers=[],_enums={},_lastKpis=null;
let _filterTimer=null;

// ═══ TEMA CLARO/ESCURO ═══
function applyTheme(theme){
  const isLight = theme === 'light';
  document.body.classList.toggle('theme-light', isLight);
  const btn = document.getElementById('theme-toggle');
  if(btn) btn.textContent = isLight ? '☀️' : '🌙';
}
function toggleTheme(){
  const next = document.body.classList.contains('theme-light') ? 'dark' : 'light';
  localStorage.setItem('doctrack_theme', next);
  applyTheme(next);
}
function initTheme(){
  applyTheme(localStorage.getItem('doctrack_theme') || 'dark');
}

const CAT_COLORS={'PRE':'#22d3ee','Manuais':'#06b6d4'};
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
  const chip=e.target.closest('.filter-chip');
  if(chip){ _equipChip = chip.dataset.chip; renderGrid(); return; }
  const btn=e.target.closest('[data-action]');
  if(!btn)return;
  const action=btn.dataset.action;
  const id=btn.dataset.id;
  switch(action){
    case 'edit-user': openEditUser(parseInt(id)); break;
    case 'delete-user': confirmDeleteUser(parseInt(id), btn.dataset.name||''); break;
  }
});

document.body.addEventListener('change',(e)=>{
  if(e.target&&e.target.id==='audit-filter-action'){filterAudit();return}
});

document.body.addEventListener('input',(e)=>{
  if(!e.target)return;
  if(e.target.id==='docs-search'||e.target.id==='audit-search'){
    clearTimeout(_filterTimer);
    const fn=e.target.id==='docs-search'?renderGrid:filterAudit;
    _filterTimer=setTimeout(fn,250);
  }
});

async function initApp(){
  updateUserUI();
  renderSkeletonTable('dash-table',5,5);
  await loadEnums();
  await loadData();

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
    const b = document.getElementById('btn-add-equip');
    if(b) b.style.display='none';
  }
  if(rl==='admin' || rl==='gestor') {
      const btnExp = document.getElementById('btn-export-kpis');
      if(btnExp) btnExp.style.display='block';
  }
}

function exportKPIs() {
    if(!_lastKpis) { showToast('Nenhum dado para exportar', 'error'); return; }
    
    showToast('Gerando PDF de Alta Qualidade (Servidor)...', 'info');
    
    apiFetch('/report/pdf', {
        method: 'POST',
        body: JSON.stringify({ kpis: _lastKpis })
    })
    .then(async res => {
        if(!res.ok) {
            const err = await res.json();
            throw new Error(err.erro || "Falha no servidor");
        }
        return res.blob();
    })
    .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = "DocTrack_Enterprise_KPIs.pdf";
        document.body.appendChild(a);
        a.click();
        a.remove();
        showToast('Relatório Gerado com Sucesso!', 'success');
    })
    .catch(err => {
        console.error("Erro na exportação via servidor: ", err);
        showToast('Erro ao gerar PDF: ' + err.message, 'error');
    });
}

// ═══ EXPORTAÇÃO DE RELATÓRIO (PDF client-side, com filtros) ═══
function _exportConfig(){
  return {
    inicio: (document.getElementById('exp-inicio')||{}).value||'',
    fim:    (document.getElementById('exp-fim')||{}).value||'',
    base:   (document.getElementById('exp-datebase')||{}).value||'data_homologacao',
    status: (document.getElementById('exp-status')||{}).value||'',
  };
}
function _groupGlobalStatus(g){
  const c = equipStatusColor(g);
  return c==='green' ? 'Finalizado' : c==='red' ? 'Pendente' : 'Em progresso';
}
function _parseBR(str){
  if(!str) return null;
  const p = String(str).split(' ')[0].split('/');
  if(p.length!==3) return null;
  return new Date(+p[2], +p[1]-1, +p[0]);
}
function _exportFilteredGroups(){
  const cfg = _exportConfig();
  const startMs = cfg.inicio ? new Date(cfg.inicio+'T00:00:00').getTime() : null;
  const endMs   = cfg.fim ? new Date(cfg.fim+'T23:59:59').getTime() : null;
  return groupByEquip().filter(g=>{
    if(cfg.status && _groupGlobalStatus(g)!==cfg.status) return false;
    if(startMs!==null || endMs!==null){
      const dt = _parseBR(g.pre ? g.pre[cfg.base] : '');
      if(!dt) return false;
      const t = dt.getTime();
      if(startMs!==null && t<startMs) return false;
      if(endMs!==null && t>endMs) return false;
    }
    return true;
  });
}
function updateExportPreview(){
  const el = document.getElementById('exp-preview');
  if(el) el.textContent = `${_exportFilteredGroups().length} equipamento(s) serão incluídos no relatório`;
}
function openExportModal(){
  const ini=document.getElementById('exp-inicio'); if(ini) ini.value='';
  const fim=document.getElementById('exp-fim'); if(fim) fim.value='';
  document.getElementById('exp-datebase').value='data_homologacao';
  document.getElementById('exp-status').value='';
  ['exp-inicio','exp-fim','exp-datebase','exp-status'].forEach(id=>{const e=document.getElementById(id); if(e) e.onchange=updateExportPreview;});
  updateExportPreview();
  openBaseModal('export');
}
function gerarRelatorioPDF(){
  if(!window.jspdf){ showToast('Aguarde o carregamento do gerador de PDF e tente novamente','error'); return; }
  const groups = _exportFilteredGroups();
  if(!groups.length){ showToast('Nenhum equipamento corresponde aos filtros','error'); return; }
  const cfg = _exportConfig();
  const baseLabel = {data_homologacao:'Homologação', data_treinamento:'Treinamento', updated_em:'Últ. atualização'}[cfg.base]||cfg.base;
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({orientation:'landscape', unit:'mm', format:'a4'});
  const pageW = doc.internal.pageSize.getWidth();
  const pageH = doc.internal.pageSize.getHeight();
  const margin = 14;
  let y = margin;

  doc.setFillColor(255,255,255); doc.rect(0,0,pageW,pageH,'F');

  doc.setFont('helvetica','bold'); doc.setFontSize(16); doc.setTextColor(26,25,24);
  doc.text('DocTrack — Relatório de Equipamentos', margin, y+6);
  doc.setFont('helvetica','normal'); doc.setFontSize(9); doc.setTextColor(120,120,120);
  const hoje = new Date().toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
  const filtros = [];
  if(cfg.inicio||cfg.fim) filtros.push(`Período (${baseLabel}): ${cfg.inicio||'…'} a ${cfg.fim||'…'}`);
  if(cfg.status) filtros.push(`Status: ${cfg.status}`);
  if(!filtros.length) filtros.push('Sem filtros (todos os equipamentos)');
  doc.text(`Gerado em ${hoje}  ·  ${filtros.join('  ·  ')}`, margin, y+13);
  y += 22;

  let fin=0, prog=0, pend=0, preHom=0, man100=0;
  groups.forEach(g=>{
    const st=_groupGlobalStatus(g);
    if(st==='Finalizado')fin++; else if(st==='Em progresso')prog++; else pend++;
    if(g.pre && g.pre.status==='Homologado') preHom++;
    if(g.manuais.length>0 && equipManuaisOk(g)===g.manuais.length) man100++;
  });
  const stats = [['Equipamentos',groups.length],['Finalizados',fin],['Em progresso',prog],['Pendentes',pend],['IT/PRE homologados',preHom],['Manuais 100%',man100]];
  const statW = (pageW - margin*2 - 8*5)/6;
  stats.forEach(([label,val],i)=>{
    const sx = margin + i*(statW+8);
    doc.setFillColor(248,248,250); doc.setDrawColor(210,210,215); doc.setLineWidth(0.3);
    doc.roundedRect(sx, y, statW, 16, 2,2,'FD');
    doc.setFont('helvetica','bold'); doc.setFontSize(13); doc.setTextColor(26,25,24);
    doc.text(String(val), sx+statW/2, y+8, {align:'center'});
    doc.setFont('helvetica','normal'); doc.setFontSize(7); doc.setTextColor(120,120,120);
    doc.text(label, sx+statW/2, y+13, {align:'center'});
  });
  y += 24;

  const cols = [
    {h:'Equipamento', k:'equip', w:62},
    {h:'SKU', k:'sku', w:28},
    {h:'Responsável', k:'resp', w:46},
    {h:'IT / PRE', k:'pre', w:42},
    {h:'Manuais', k:'man', w:22},
    {h:'Status', k:'glob', w:30},
    {h:baseLabel, k:'data', w:27},
  ];
  const rowH=7, headerH=8;
  function header(){
    doc.setFillColor(240,239,232); doc.rect(margin,y,pageW-margin*2,headerH,'F');
    doc.setFont('helvetica','bold'); doc.setFontSize(7.5); doc.setTextColor(95,94,90);
    let cx=margin; cols.forEach(c=>{doc.text(c.h, cx+2, y+5.5); cx+=c.w;}); y+=headerH;
  }
  header();
  groups.forEach((g,idx)=>{
    if(y+rowH > pageH-margin){ doc.addPage(); doc.setFillColor(255,255,255); doc.rect(0,0,pageW,pageH,'F'); y=margin; header(); }
    if(idx%2===0){ doc.setFillColor(250,250,252); doc.rect(margin,y,pageW-margin*2,rowH,'F'); }
    doc.setDrawColor(225,225,228); doc.setLineWidth(0.2); doc.line(margin,y,pageW-margin,y);
    const ok=equipManuaisOk(g);
    const row = {
      equip: g.equipamento,
      sku: g.sku||'—',
      resp: (g.pre&&g.pre.responsavel)||'—',
      pre: g.pre? g.pre.status : '—',
      man: g.manuais.length? (ok+'/5') : '—',
      glob: _groupGlobalStatus(g),
      data: g.pre? ((g.pre[cfg.base]||'—').split(' ')[0]||'—') : '—',
    };
    let cx=margin;
    doc.setFont('helvetica','normal'); doc.setFontSize(7.5); doc.setTextColor(26,25,24);
    cols.forEach(c=>{
      let v=String(row[c.k]==null?'':row[c.k]);
      const maxW=c.w-4;
      if(doc.getTextWidth(v)>maxW){ v=v.substring(0, Math.max(1, Math.floor(v.length*maxW/doc.getTextWidth(v))-1))+'…'; }
      doc.text(v, cx+2, y+5); cx+=c.w;
    });
    y+=rowH;
  });
  doc.setDrawColor(225,225,228); doc.line(margin,y,pageW-margin,y);

  const pages=doc.internal.getNumberOfPages();
  for(let i=1;i<=pages;i++){ doc.setPage(i); doc.setFont('helvetica','normal'); doc.setFontSize(7); doc.setTextColor(170,168,162);
    doc.text(`Página ${i} de ${pages}`, pageW-margin, pageH-6, {align:'right'});
    doc.text('DocTrack — relatório gerado automaticamente', margin, pageH-6); }

  doc.save('DocTrack_Relatorio.pdf');
  closeModal('export');
  showToast('Relatório gerado','success');
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

  const ringColors=['#10b981','#22d3ee','#06b6d4'];
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
  const etapaColors=['#06b6d4','#f59e0b','#22d3ee','#10b981'];
  
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
  const stColors=stLabels.map(s=>STATUS_PILL[s] ? (s==='Elaborar'?'#06b6d4':s.includes('Homologado')||s==='Concluído'?'#10b981':'#22d3ee') : '#ec4899');
  
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

function pillCls(c){if(!c)return'pill-elab';if(c.includes('PRE'))return'pill-wip';if(c.includes('Manuais'))return'pill-elab';return'pill-warn'}
function pillSt(s){if(!s)return'<span style="color:var(--t4)">—</span>';const cls=STATUS_PILL[s]||'pill-elab';return`<span class="pill ${cls}">${esc(s)}</span>`}
function pillGlobal(s){
  if(s==='Finalizado')return'<span class="sg-badge sg-finalizado">Finalizado</span>';
  if(s==='Em progresso')return'<span class="sg-badge sg-progresso">Progresso</span>';
  return'<span class="sg-badge sg-pendente">Pendente</span>';
}

function renderLink(url) {
    if(!url || url === '—') return '—';
    const normalizedUrl = url.replace(/\\/g, '/');
    const escapedUrl = esc(normalizedUrl).replace(/'/g, "\\'");
    return `<a href="javascript:void(0)" onclick="abrirPasta('${escapedUrl}')" title="Abrir localização do arquivo" style="color:var(--cyan);text-decoration:none"><svg width="14" height="14" fill="none" viewBox="0 0 24 24"><path d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></a>`;
}

function copiarTexto(texto) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(texto);
  }
  return new Promise((resolve, reject) => {
    try {
      const ta = document.createElement('textarea');
      ta.value = texto;
      ta.style.position = 'fixed';
      ta.style.top = '-9999px';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      if (ok) resolve();
      else reject(new Error('Cópia rejeitada pelo navegador'));
    } catch (e) {
      reject(e);
    }
  });
}

async function abrirPasta(caminho) {
  if(!caminho) return;
  try {
    const res = await apiFetch('/documentos/abrir-pasta', {
      method: 'POST',
      body: JSON.stringify({ caminho })
    });
    const data = await res.json().catch(() => ({}));
    if(!res.ok) {
      showToast(data.erro || 'Não foi possível abrir a pasta', 'error');
      return;
    }
    
    if(data.local === false) {
      const caminhoParaCopiar = data.caminho_aberto;
      try {
        await copiarTexto(caminhoParaCopiar);
        showToast('Caminho de rede copiado! Cole no Windows Explorer.', 'success');
      } catch (clipErr) {
        console.error('Falha ao usar API clipboard, usando fallback...', clipErr);
        window.prompt('Copie o caminho do documento:', caminhoParaCopiar);
      }
    } else {
      showToast(data.mensagem || 'Pasta aberta localmente', 'success');
    }
  } catch(e) {
    showToast('Erro de rede ao tentar abrir a pasta', 'error');
  }
}

// ═══ DOCS — GRADE DE EQUIPAMENTOS ═══
let _equipChip = 'todos';

// Agrupa allDocs por nome de equipamento (PRE + Manuais juntos)
function groupByEquip(){
  const groups = {};
  allDocs.forEach(d => {
    const key = (d.equipamento || '—').trim();
    if(!groups[key]){
      groups[key] = { equipamento: key, sku:'', fabricante:'', pre:null, manuais:[] };
    }
    const g = groups[key];
    if(d.sku && !g.sku) g.sku = d.sku;
    if(d.fabricante && !g.fabricante) g.fabricante = d.fabricante;
    if(d.setor === 'PRE'){ if(!g.pre) g.pre = d; }
    else if(d.setor === 'Manuais'){ g.manuais.push(d); }
  });
  return Object.values(groups).sort((a,b)=>a.equipamento.localeCompare(b.equipamento));
}

function equipManuaisOk(g){ return g.manuais.filter(d=>d.status==='Concluído').length; }

function equipStatusColor(g){
  const ok = equipManuaisOk(g), cnt = g.manuais.length;
  const preElaborar = g.pre && g.pre.status === 'Elaborar';
  const preHomolog  = g.pre && g.pre.status === 'Homologado';
  if(preElaborar || (cnt>0 && ok===0)) return 'red';
  if(preHomolog && cnt>0 && ok===cnt) return 'green';
  return 'amber';
}

function equipMatchesChip(g, chip){
  const ok = equipManuaisOk(g), cnt = g.manuais.length;
  const anyElaborar = (g.pre && g.pre.status==='Elaborar') || g.manuais.some(d=>d.status==='Elaborar');
  const anyProgresso = (g.pre && ['Treinamento Piloto','Enviado para Homologação'].includes(g.pre.status)) || g.manuais.some(d=>d.status==='Em andamento');
  const finalizado = (g.pre && g.pre.status==='Homologado') && cnt>0 && ok===cnt;
  switch(chip){
    case 'todos': return true;
    case 'pendente': return anyElaborar;
    case 'progresso': return anyProgresso && !anyElaborar;
    case 'finalizado': return finalizado;
    case 'pre-pendente': return g.pre && g.pre.status==='Elaborar';
    case 'manuais-incompletos': return ok < (cnt || 5);
    default: return true;
  }
}

function renderChips(groups){
  const chips = [
    {id:'todos', label:'Todos'},
    {id:'pendente', label:'Pendente'},
    {id:'progresso', label:'Em progresso'},
    {id:'finalizado', label:'Finalizado'},
    {id:'pre-pendente', label:'IT/PRE pendente'},
    {id:'manuais-incompletos', label:'Manuais incompletos'},
  ];
  document.getElementById('equip-chips').innerHTML = chips.map(c => {
    const n = groups.filter(g => equipMatchesChip(g, c.id)).length;
    const active = _equipChip === c.id ? ' active' : '';
    return `<button type="button" class="filter-chip${active}" data-chip="${c.id}">${esc(c.label)}<span class="chip-count">${n}</span></button>`;
  }).join('');
}

function renderDocs(){ renderGrid(); }

function renderGrid(){
  const groups = groupByEquip();
  renderChips(groups);

  const q = (document.getElementById('docs-search').value || '').trim().toLowerCase();
  let filtered = groups.filter(g => equipMatchesChip(g, _equipChip));
  if(q){
    filtered = filtered.filter(g =>
      [g.equipamento, g.sku, g.fabricante].join(' ').toLowerCase().includes(q)
    );
  }

  document.getElementById('docs-badge').textContent = filtered.length + ' equip.';

  const grid = document.getElementById('equip-grid');
  if(!filtered.length){
    grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;color:var(--t4);padding:32px">Nenhum equipamento encontrado</div>';
    return;
  }
  grid.innerHTML = filtered.map(g => {
    const color = equipStatusColor(g);
    return `<div class="equip-card st-${color}" data-equip="${esc(g.equipamento)}" onclick="openEquipModal('${esc(g.equipamento).replace(/'/g,"\\'")}')">
      <div class="equip-card-name">${esc(g.equipamento)}</div>
      <div class="equip-card-sku">${g.sku?esc(g.sku):'<span class="muted">sem SKU</span>'}</div>
    </div>`;
  }).join('');
}

// ═══ MODAL DE EQUIPAMENTO ═══
let _equipCtx = null; // { equipamento, pre, manuais: {tipo: doc} }

// Wrapper mantido para o modal de usuário (e quaisquer outros modais simples)
function openModal(id){ openBaseModal(id); }

const _PRE_STATUS = ['Elaborar','Treinamento Piloto','Enviado para Homologação','Homologado'];
const _MAN_STATUS = ['Elaborar','Em andamento','Concluído'];
const _MAN_TIPOS = [
  ['Manual_ES','Manual ES'],
  ['Manual_Usuario','Manual do Usuário'],
  ['QIQOQD','QI/QO/QD'],
  ['Manual_Servico','Manual de Serviço'],
  ['Spare_Parts','Spare Parts'],
];

function _dateToInput(br){ // "dd/mm/yyyy" -> "yyyy-mm-dd"
  if(!br) return '';
  const p = br.split('/');
  return p.length===3 ? `${p[2]}-${p[1]}-${p[0]}` : '';
}

function switchEquipTab(tab){
  document.querySelectorAll('.equip-modal-tab').forEach(b=>b.classList.toggle('active', b.dataset.tab===tab));
  document.getElementById('equip-panel-pre').classList.toggle('active', tab==='pre');
  document.getElementById('equip-panel-manuais').classList.toggle('active', tab==='manuais');
}

function openEquipModal(equipName){
  const docs = allDocs.filter(d => (d.equipamento||'').trim() === equipName);
  const pre = docs.find(d => d.setor==='PRE') || null;
  const manuais = {};
  docs.filter(d=>d.setor==='Manuais').forEach(d=>{ manuais[d.tipo_doc] = d; });
  const fabricante = (docs.find(d=>d.fabricante)||{}).fabricante || '';
  const sku = (docs.find(d=>d.sku)||{}).sku || '';
  _equipCtx = { equipamento: equipName, pre, manuais, fabricante, sku };

  document.getElementById('equip-modal-title').textContent = equipName;
  document.getElementById('equip-modal-sub').textContent = (sku?('SKU '+sku):'') + (fabricante?(' · '+fabricante):'');

  // Botão de excluir equipamento: somente admin/gestor
  const delBtn = document.getElementById('btn-del-equip');
  if(delBtn) delBtn.style.display = (currentUser.role==='admin'||currentUser.role==='gestor') ? 'inline-flex' : 'none';

  renderEquipPrePanel();
  renderEquipManuaisPanel();
  switchEquipTab('pre');
  openBaseModal('equip');
}

async function deleteEquip(){
  if(!_equipCtx) return;
  if(!(currentUser.role==='admin'||currentUser.role==='gestor')){ showToast('Sem permissão','error'); return; }
  const nome = _equipCtx.equipamento;
  const docs = [];
  if(_equipCtx.pre) docs.push(_equipCtx.pre);
  Object.values(_equipCtx.manuais).forEach(d=>docs.push(d));
  if(!docs.length){ showToast('Nada para excluir','info'); return; }
  const ok = await confirmModal('Excluir equipamento', `Excluir "${nome}" e todos os seus ${docs.length} documento(s) (IT/PRE e Manuais)? Esta ação pode ser revertida no banco (soft delete).`);
  if(!ok) return;
  try{
    for(const d of docs){
      const res = await apiFetch(`/documentos/${d.id}`, {method:'DELETE'});
      if(!res || !res.ok){ const e = res ? await res.json().catch(()=>({})) : {}; showToast(e.erro||'Erro ao excluir','error'); return; }
    }
    showToast('Equipamento excluído','success'); closeModal('equip'); await refreshAll();
  }catch(e){ showToast('Erro de rede','error'); }
}

function renderEquipPrePanel(){
  const p = _equipCtx.pre;
  const panel = document.getElementById('equip-panel-pre');
  if(!p){
    panel.innerHTML = `<div style="text-align:center;padding:24px;color:var(--t3)">
      <p style="margin-bottom:12px">Este equipamento ainda não tem documento IT/PRE.</p>
      <button class="btn btn-primary btn-sm" onclick="createPreDoc()">Criar documento IT/PRE</button>
    </div>`;
    return;
  }
  const statusOpts = _PRE_STATUS.map(s=>`<option value="${esc(s)}" ${p.status===s?'selected':''}>${esc(s)}</option>`).join('');
  panel.innerHTML = `
    <div class="g2">
      <div class="form-group"><label class="form-label">Equipamento</label><input class="form-input" id="ep-equipamento" value="${esc(p.equipamento)}"></div>
      <div class="form-group"><label class="form-label">SKU</label><input class="form-input" id="ep-sku" value="${esc(p.sku)}"></div>
    </div>
    <div class="g2">
      <div class="form-group"><label class="form-label">Código do Doc</label><input class="form-input" id="ep-codigo" value="${esc(p.codigo_doc)}"></div>
      <div class="form-group"><label class="form-label">Responsável</label><input class="form-input" id="ep-responsavel" value="${esc(p.responsavel)}"></div>
    </div>
    <div class="form-group"><label class="form-label">Status</label><select class="form-input" id="ep-status">${statusOpts}</select></div>
    <div class="g2">
      <div class="form-group"><label class="form-label">Data Treinamento Piloto</label><input class="form-input" type="date" id="ep-data_treinamento" value="${_dateToInput(p.data_treinamento)}"></div>
      <div class="form-group"><label class="form-label">Data Envio Homologação</label><input class="form-input" type="date" id="ep-data_homologacao" value="${_dateToInput(p.data_homologacao)}"></div>
    </div>
    <div class="g2">
      <div class="form-group"><label class="form-label">Obs. Treinamento</label><input class="form-input" id="ep-obs_treinamento" value="${esc(p.obs_treinamento)}"></div>
      <div class="form-group"><label class="form-label">Obs. Homologação</label><input class="form-input" id="ep-obs_homologacao" value="${esc(p.obs_homologacao)}"></div>
    </div>
    <div class="form-group"><label class="form-label">Armazenamento (Caminho na Rede)</label><input class="form-input" id="ep-armazenamento" value="${esc(p.armazenamento)}"></div>
    <div class="modal-footer" style="margin-top:8px"><button class="btn btn-primary" onclick="saveEquipPre()">Salvar alterações</button></div>
  `;
}

function renderEquipManuaisPanel(){
  const panel = document.getElementById('equip-panel-manuais');
  const hasManuais = Object.keys(_equipCtx.manuais).length > 0;
  if(!hasManuais){
    panel.innerHTML = `<div style="text-align:center;padding:24px;color:var(--t3)">
      <p style="margin-bottom:12px">Este equipamento ainda não tem documentos de Manuais.</p>
      <button class="btn btn-primary btn-sm" onclick="createManuais()">Criar manuais para este equipamento</button>
    </div>`;
    return;
  }
  const rows = _MAN_TIPOS.map(([tipo, label]) => {
    const d = _equipCtx.manuais[tipo];
    if(!d) return '';
    const statusOpts = _MAN_STATUS.map(s=>`<option value="${esc(s)}" ${d.status===s?'selected':''}>${esc(s)}</option>`).join('');
    return `<div class="manual-row">
      <div class="manual-row-head"><span class="manual-row-name">${esc(label)}</span></div>
      <div class="form-group" style="margin-bottom:0"><label class="form-label">Status</label><select class="form-input" id="em-st-${tipo}">${statusOpts}</select></div>
    </div>`;
  }).join('');
  panel.innerHTML = `
    <div class="section-label-line">Dados do fabricante (compartilhados)</div>
    <div class="g2">
      <div class="form-group"><label class="form-label">Fabricante</label><input class="form-input" id="em-fabricante" value="${esc(_equipCtx.fabricante)}"></div>
      <div class="form-group"><label class="form-label">Armazenamento base</label><input class="form-input" id="em-armazenamento" value="${esc((Object.values(_equipCtx.manuais)[0]||{}).armazenamento||'')}"></div>
    </div>
    <div class="section-label-line">Documentos por tipo</div>
    ${rows}
    <div class="modal-footer" style="margin-top:8px"><button class="btn btn-primary" onclick="saveEquipManuais()">Salvar alterações</button></div>
  `;
}

async function _patchDoc(id, payload){
  const res = await apiFetch(`/documentos/${id}`, {method:'PATCH', body:JSON.stringify(payload)});
  return res;
}

async function saveEquipPre(){
  const p = _equipCtx.pre;
  if(!p) return;
  const payload = {
    equipamento: document.getElementById('ep-equipamento').value,
    sku: document.getElementById('ep-sku').value,
    codigo_doc: document.getElementById('ep-codigo').value,
    responsavel: document.getElementById('ep-responsavel').value,
    status: document.getElementById('ep-status').value,
    data_treinamento: document.getElementById('ep-data_treinamento').value,
    data_homologacao: document.getElementById('ep-data_homologacao').value,
    obs_treinamento: document.getElementById('ep-obs_treinamento').value,
    obs_homologacao: document.getElementById('ep-obs_homologacao').value,
    armazenamento: document.getElementById('ep-armazenamento').value,
  };
  try{
    const res = await _patchDoc(p.id, payload);
    if(res && res.ok){ showToast('IT/PRE salvo','success'); closeModal('equip'); await refreshAll(); }
    else { const e = await res.json().catch(()=>({})); showToast(e.erro||'Erro ao salvar','error'); }
  }catch(e){ showToast('Erro de rede','error'); }
}

async function saveEquipManuais(){
  const fabricante = document.getElementById('em-fabricante').value;
  const armazenamento = document.getElementById('em-armazenamento').value;
  const tipos = Object.keys(_equipCtx.manuais);
  try{
    for(const tipo of tipos){
      const d = _equipCtx.manuais[tipo];
      const payload = {
        fabricante,
        armazenamento,
        status: document.getElementById('em-st-'+tipo).value,
      };
      const res = await _patchDoc(d.id, payload);
      if(!res || !res.ok){ const e = res ? await res.json().catch(()=>({})) : {}; showToast(e.erro||'Erro ao salvar manuais','error'); return; }
    }
    showToast('Manuais salvos','success'); closeModal('equip'); await refreshAll();
  }catch(e){ showToast('Erro de rede','error'); }
}

// Cria o documento IT/PRE para o equipamento aberto
async function createPreDoc(){
  const payload = { setor:'PRE', equipamento:_equipCtx.equipamento, documento:`IT/Checklist - ${_equipCtx.equipamento}`, sku:_equipCtx.sku };
  try{
    const res = await apiFetch('/documentos', {method:'POST', body:JSON.stringify(payload)});
    if(res && res.ok){ showToast('IT/PRE criado','success'); closeModal('equip'); await refreshAll(); }
    else { showToast('Erro ao criar IT/PRE','error'); }
  }catch(e){ showToast('Erro de rede','error'); }
}

// Cria os 5 manuais para o equipamento aberto (backend gera os 5 a partir de um POST Manuais)
async function createManuais(){
  const payload = { setor:'Manuais', equipamento:_equipCtx.equipamento, documento:`Manual ES - ${_equipCtx.equipamento}`, tipo_doc:'Manual_ES', sku:_equipCtx.sku, fabricante:_equipCtx.fabricante };
  try{
    const res = await apiFetch('/documentos', {method:'POST', body:JSON.stringify(payload)});
    if(res && res.ok){ showToast('Manuais criados','success'); closeModal('equip'); await refreshAll(); }
    else { showToast('Erro ao criar manuais','error'); }
  }catch(e){ showToast('Erro de rede','error'); }
}

function openNewEquip(){
  document.getElementById('new-equip-nome').value = '';
  document.getElementById('new-equip-sku').value = '';
  openBaseModal('new-equip');
}

async function submitNewEquip(){
  const nome = document.getElementById('new-equip-nome').value.trim();
  const sku = document.getElementById('new-equip-sku').value.trim();
  if(!nome){ showToast('Informe o nome do equipamento','error'); return; }
  try{
    const res = await apiFetch('/documentos', {method:'POST', body:JSON.stringify({setor:'PRE', equipamento:nome, sku, documento:`IT/Checklist - ${nome}`})});
    if(res && res.ok){ showToast('Equipamento criado','success'); closeModal('new-equip'); await refreshAll(); }
    else { showToast('Erro ao criar equipamento','error'); }
  }catch(e){ showToast('Erro de rede','error'); }
}

// ═══ AUDIT ═══
async function renderAudit(){filterAudit()}
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
async function filterAudit(){
  let logs=[];
  const qs=_auditDateParams().toString();
  try{const res=await apiFetch('/audit'+(qs?('?'+qs):''));if(res&&res.ok)logs=await res.json()}catch(e){}
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
    const p=_auditDateParams();
    p.set('token', getToken());
    window.open(API + '/export/audit?' + p.toString(), '_blank');
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
      renderGrid();
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

// Aplica o tema salvo assim que o script carrega (vale para tela de login também)
initTheme();
