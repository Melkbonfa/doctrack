const API='/api';
let allDocs=[],allEquip={},allEquipById={},chartInstances={},currentUser={name:'Admin',email:'admin@pde.com',role:'admin',initials:'A'};
let selectedRole='admin',_allUsers=[],_enums={},_lastKpis=null;
let _filterTimer=null;
let _dashEquip='';   // equipamento selecionado no dashboard ('' = todos)

// esc, norm, applyTheme/toggleTheme/initTheme e o acesso ao token vêm de
// static/common.js (carregado antes deste arquivo em todos os templates).

const CAT_COLORS={'PRE':'#22d3ee','Manuais':'#06b6d4'};
const STATUS_PILL={'Elaborar':'pill-elab','Homologado':'pill-ok','Enviado para Homologação':'pill-wip','Treinamento Piloto':'pill-warn','Concluído':'pill-ok','Em andamento':'pill-wip'};

// ═══ DONUT: estilo igual ao módulo de Entregáveis (gradiente vertical + tooltip externo) ═══
function _darken(hex, f){
  const n = parseInt(String(hex).replace('#',''), 16);
  const r = Math.round(((n>>16)&255)*f), g = Math.round(((n>>8)&255)*f), b = Math.round((n&255)*f);
  return `rgb(${r},${g},${b})`;
}
function donutGrad(ctx, hex){
  const g = ctx.createLinearGradient(0, 0, 0, 160);
  g.addColorStop(0, hex);
  g.addColorStop(1, _darken(hex, 0.5));
  return g;
}
function donutTooltipExternal(context){
  const { chart, tooltip } = context;
  let el = document.getElementById('app-donut-tip');
  if (!el){
    el = document.createElement('div');
    el.id = 'app-donut-tip';
    el.style.cssText = 'position:fixed;pointer-events:none;z-index:9999;opacity:0;transition:opacity .1s ease;background:#232847;border:1px solid rgba(167,139,250,.3);border-radius:8px;padding:7px 10px;font:500 12px/1.2 Inter,system-ui,sans-serif;color:#f1f5f9;white-space:nowrap;box-shadow:0 8px 24px rgba(0,0,0,.45);display:flex;align-items:center;gap:7px';
    document.body.appendChild(el);
  }
  if (!tooltip || tooltip.opacity === 0){ el.style.opacity = '0'; return; }
  const dp = tooltip.dataPoints && tooltip.dataPoints[0];
  if (!dp){ el.style.opacity = '0'; return; }
  const dot = (dp.dataset.dotColors && dp.dataset.dotColors[dp.dataIndex]) || '#22d3ee';
  const body = (tooltip.body && tooltip.body[0] && tooltip.body[0].lines[0]) ||
               (dp.label + ': ' + dp.formattedValue);
  el.innerHTML = `<span style="width:9px;height:9px;border-radius:50%;background:${dot};flex-shrink:0"></span><span>${esc(body)}</span>`;
  el.style.opacity = '1';
  const rect = chart.canvas.getBoundingClientRect();
  const tw = el.offsetWidth, th = el.offsetHeight;
  let left = rect.left + tooltip.caretX + 14;
  let top = rect.top + tooltip.caretY - th - 8;
  if (left + tw > window.innerWidth - 8) left = window.innerWidth - tw - 8;
  if (top < 8) top = rect.top + tooltip.caretY + 16;
  el.style.left = left + 'px';
  el.style.top = top + 'px';
}

function authHeader(){return{'Content-Type':'application/json','Authorization':'Bearer '+getToken()}}
// 401 → tenta renovar o access token com o refresh e repete a chamada uma vez.
// Só desloga (limpo) se o refresh também venceu/foi revogado.
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

async function doLogin(){
  const btn=document.getElementById('login-btn-text'),email=document.getElementById('login-email').value.trim(),senha=document.getElementById('login-pass').value;
  btn.innerHTML='<span class="spinner" style="border-color:rgba(255,255,255,.3);border-top-color:#fff"></span>';
  try{
    const res=await fetch(API+'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,senha})});
    const data=await res.json().catch(()=>({}));
    if(res.status===403&&data.precisa_definir_senha){
      btn.textContent='Entrar no DocTrack';
      showToast('Conta sem senha. Defina sua senha com o código de ativação.','info');
      showPrimeiroAcesso(email);return;
    }
    if(!res.ok){btn.textContent='Entrar no DocTrack';showToast(data.erro||data.error||'Falha no login','error');return}
    setToken(data.access_token);if(data.refresh_token)localStorage.setItem('doctrack_refresh',data.refresh_token);localStorage.setItem('doctrack_user',JSON.stringify(data.usuario));
    const u=data.usuario;currentUser={name:u.nome,email:u.email,role:u.role,initials:u.nome.split(' ').map(w=>w[0]).join('').substring(0,2).toUpperCase()};
    window.location.href='/hub';
  }catch(e){
    btn.textContent='Entrar no DocTrack';
    showToast('Servidor indisponível. Tente novamente.','error');
  }
}

// ── Primeiro acesso / definir senha ───────────────────────────────────────────
function showPrimeiroAcesso(email){
  document.getElementById('login-screen').style.display='none';
  const scr=document.getElementById('primeiro-acesso-screen');
  scr.style.display='flex';
  if(email){const e=document.getElementById('pa-email');if(e)e.value=email;}
  const f=document.getElementById(email?'pa-codigo':'pa-email');if(f)f.focus();
}
function showLogin(){
  document.getElementById('primeiro-acesso-screen').style.display='none';
  document.getElementById('login-screen').style.display='flex';
  const e=document.getElementById('login-email');if(e)e.focus();
}
async function doPrimeiroAcesso(){
  const btn=document.getElementById('pa-btn-text');
  const email=document.getElementById('pa-email').value.trim();
  const codigo=document.getElementById('pa-codigo').value.trim();
  const senha=document.getElementById('pa-senha').value;
  const senha2=document.getElementById('pa-senha2').value;
  if(senha.length<SENHA_MIN){showToast('A senha deve ter pelo menos '+SENHA_MIN+' caracteres','error');return}
  if(senha!==senha2){showToast('As senhas não conferem','error');return}
  const original=btn.textContent;
  btn.innerHTML='<span class="spinner" style="border-color:rgba(255,255,255,.3);border-top-color:#fff"></span>';
  try{
    const res=await fetch(API+'/auth/primeiro-acesso',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,codigo,senha})});
    const data=await res.json().catch(()=>({}));
    if(!res.ok){btn.textContent=original;showToast(data.erro||'Não foi possível definir a senha','error');return}
    setToken(data.access_token);if(data.refresh_token)localStorage.setItem('doctrack_refresh',data.refresh_token);localStorage.setItem('doctrack_user',JSON.stringify(data.usuario));
    showToast('Senha definida! Entrando...','success');
    window.location.href='/hub';
  }catch(e){
    btn.textContent=original;
    showToast('Servidor indisponível. Tente novamente.','error');
  }
}
// O modal de código de ativação (criação/reset de usuário) vive no módulo de Configurações.
function toggleLoginPass(){
  const inp=document.getElementById('login-pass'),eye=document.getElementById('login-eye');
  if(!inp||!eye)return;
  const mostrar=inp.type==='password';
  inp.type=mostrar?'text':'password';
  eye.classList.toggle('on',mostrar);
  eye.setAttribute('aria-label',mostrar?'Ocultar senha':'Mostrar senha');
  inp.focus();
}
async function doLogout(){
  try{await apiFetch('/auth/logout',{method:'POST'})}catch(e){}
  clearToken();
  document.getElementById('app').style.display='none';
  document.getElementById('login-screen').style.display='flex';
}

const PAGE_LABELS={dashboard:'Dashboard',docs:'Documentos'};
function navigate(page){
  document.querySelectorAll('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.page===page));
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  const pg=document.getElementById('page-'+page);
  if(pg)pg.classList.add('active');
  document.getElementById('breadcrumb-current').textContent=PAGE_LABELS[page]||page;
  if(page==='docs')renderDocs();
}
document.querySelectorAll('.nav-item[data-page]').forEach(el=>el.addEventListener('click',()=>navigate(el.dataset.page)));

document.body.addEventListener('click',(e)=>{
  const chip=e.target.closest('.filter-chip');
  if(chip){ _equipChip = chip.dataset.chip; renderGrid(); return; }
});

document.body.addEventListener('input',(e)=>{
  if(!e.target)return;
  if(e.target.id==='docs-search'){
    clearTimeout(_filterTimer);
    _filterTimer=setTimeout(renderGrid,250);
  }
});

async function initApp(){
  updateUserUI();
  renderSkeletonTable('dash-table',5,5);
  await loadEnums();
  await loadData();

  renderDashboard();renderDocs();
  // Fluxo carrega em paralelo, sem bloquear a pintura do dashboard: são duas
  // chamadas a mais e o painel se preenche sozinho quando chegarem.
  loadFluxo();
  makeSortable();

  // deep-link vindo do board de missões: /?doc=<id> abre a ficha na aba certa
  const _dq = new URLSearchParams(location.search);
  const _docDeep = parseInt(_dq.get('doc')||'0');
  if(_docDeep){
    history.replaceState(null, '', location.pathname);
    const d = allDocs.find(x=>x.id===_docDeep);
    // Documento de processo não tem ficha de equipamento: leva para a tabela dele
    if(d && !_SETORES_EQUIP.includes(d.setor)){
      navigate('docs');
      const card=document.getElementById('proc-card');
      if(card) card.scrollIntoView({behavior:'smooth', block:'center'});
    }
    else if(d){
      const key = d.equipamento_id ? ('id:'+d.equipamento_id) : ('nome:'+(d.equipamento||'—').trim());
      openEquipModal(key);
      if(d.tipo_doc==='Manual_ES'){ _manLang='ES'; setManLang('ES'); switchEquipTab('Manual_Usuario'); }
      else if(d.tipo_doc==='Manual_Usuario'){ switchEquipTab('Manual_Usuario'); }
      else if(_isChkTipo(d.tipo_doc)){ setChkSel(d.tipo_doc); switchEquipTab('Checklist_Conferencia'); }
      else if(d.tipo_doc){ switchEquipTab(d.tipo_doc); }
    }
  }

  showToast('Bem-vindo ao DocTrack v4.0','success');
  document.getElementById('sync-label').textContent='Conectado · '+new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
  const ls=document.getElementById('last-sync');if(ls)ls.textContent=new Date().toLocaleString('pt-BR',{hour:'2-digit',minute:'2-digit',day:'2-digit',month:'2-digit'});
}

function updateUserUI(){
  const av=currentUser.initials,rl=currentUser.role;
  ['nav-avatar','top-avatar'].forEach(id=>{const el=document.getElementById(id);if(el)el.textContent=av});
  const nn=document.getElementById('nav-name');if(nn)nn.textContent=currentUser.name;
  const nr=document.getElementById('nav-role');if(nr)nr.textContent=rl.toUpperCase();

  // Visibility rules
  if(rl==='leitura') {
    const b = document.getElementById('btn-add-equip');
    if(b) b.style.display='none';
  }
  if(rl==='admin' || rl==='gestor') {
      const btnExp = document.getElementById('btn-export-kpis');
      if(btnExp) btnExp.style.display='block';
      // Diagnóstico lê o filesystem da rede: mesma restrição da rota (admin/gestor)
      const btnDiag = document.getElementById('btn-diag');
      if(btnDiag) btnDiag.style.display='inline-flex';
  }
}

// CSV bruto dos documentos — o PDF de KPIs responde "como estamos"; o CSV
// permite qualquer recorte fora do sistema (Excel/BI). Respeita a busca da tela.
async function exportarDocumentosCSV(){
  const q = (document.getElementById('docs-search')||{}).value || '';
  try{
    const res = await apiFetch('/documentos/export' + (q.trim()?('?q='+encodeURIComponent(q.trim())):''));
    if(!res || !res.ok){ showToast('Erro ao exportar','error'); return; }
    await salvarResposta(res, 'documentos.csv');   // nome datado vem do servidor
    showToast('CSV gerado','success');
  }catch(e){ showToast('Erro de rede','error'); }
}

// ═══ DIAGNÓSTICO DE ARQUIVOS (admin/gestor) ═══
// Confronta o cadastro com as duas fontes de arquivo — a pasta de rede e a cópia
// hospedada na plataforma. "Homologado" no sistema não prova que existe arquivo.
const _DIAG_MAX_LINHAS = 200;

// Um apontamento reúne todos os documentos que sofrem da MESMA causa (o mesmo
// caminho que sumiu, o mesmo blob perdido). A tabela mostra o primeiro e resume
// o resto: listar 40 linhas iguais esconderia os outros problemas.
const _DIAG_PILL = {error:'pill-err', warning:'pill-warn', info:'pill-wip'};

function _diagAfetados(docs){
  const lista = docs||[];
  if(!lista.length) return '—';
  const primeiro = esc(`${lista[0].equipamento||'—'} · ${lista[0].tipo_doc_label||'—'}`);
  return lista.length===1 ? primeiro : `${primeiro} <span style="color:var(--t3)">+${lista.length-1}</span>`;
}

async function abrirDiagnostico(){
  const modal = document.getElementById('diag-body');
  if(!modal) return;
  modal.innerHTML = '<div class="loading-state">Verificando pastas e arquivos…</div>';
  openBaseModal('diag');
  try{
    const res = await apiFetch('/documentos/diagnostico');
    if(!res || !res.ok){
      const e = res ? await res.json().catch(()=>({})) : {};
      modal.innerHTML = `<div class="loading-state">${esc(e.erro||'Diagnóstico indisponível')}</div>`;
      return;
    }
    const rel = await res.json();
    const s = rel.stats||{};
    const cards = [
      ['Verificados',        s.documentos||0,            ''],
      ['Sem apontamento',    s.ok||0,                    'ok'],
      ['Pasta não encontrada', s.pastas_ausentes||0,     'err'],
      ['Pasta vazia',        s.pastas_vazias||0,         'warn'],
      ['Arquivo sumido',     s.arquivos_sumidos||0,      'err'],
    ].map(([l,v,c])=>`<div class="diag-stat ${c}"><span class="diag-stat-val">${v}</span><span class="diag-stat-lbl">${esc(l)}</span></div>`).join('');

    // Com o share fora do ar, TODO caminho responde "não existe". Nesse caso o
    // servidor descarta a checagem de rede em vez de reportar centenas de falsos
    // positivos — e a tela precisa dizer que a metade de rede não foi avaliada.
    const aviso = rel.rede_indisponivel
      ? `<div class="diag-aviso">⚠ Pastas de rede não verificadas — o servidor de arquivos não respondeu${
          rel.orcamento_estourado ? ' dentro do tempo limite' : ''}. Os apontamentos abaixo cobrem só os arquivos hospedados na plataforma.</div>`
      : '';

    const issues = rel.issues||[];
    const linhas = issues.slice(0,_DIAG_MAX_LINHAS).map(i=>
      `<tr><td><span class="pill ${_DIAG_PILL[i.severidade]||'pill-wip'}">${esc(i.titulo||i.tipo)}</span></td>
       <td>${_diagAfetados(i.documentos)}</td>
       <td style="font-size:11px;color:var(--t3)">${esc(i.detalhe||'')}</td>
       <td style="font-size:11px;color:var(--t3)">${esc(i.caminho||'—')}</td></tr>`).join('');
    const corte = issues.length>_DIAG_MAX_LINHAS
      ? `<div class="diag-aviso">Mostrando ${_DIAG_MAX_LINHAS} de ${issues.length} apontamentos — resolva os mais graves e rode de novo.</div>`
      : '';

    modal.innerHTML = `<div class="diag-stats">${cards}</div>` + aviso + (linhas
      ? `<div class="tbl-wrap"><table><thead><tr><th>Problema</th><th>Documentos</th><th>Detalhe</th><th>Caminho</th></tr></thead><tbody>${linhas}</tbody></table></div>${corte}`
      : '<div class="loading-state">Nenhuma inconsistência encontrada.</div>');
  }catch(e){ modal.innerHTML = '<div class="loading-state">Erro de rede</div>'; }
}

// ═══ EXPORTAÇÃO DE RELATÓRIO (PDF client-side, com filtros) ═══
function _exportConfig(){
  return {
    inicio: (document.getElementById('exp-inicio')||{}).value||'',
    fim:    (document.getElementById('exp-fim')||{}).value||'',
    base:   (document.getElementById('exp-datebase')||{}).value||'data_homologacao',
    status: (document.getElementById('exp-status')||{}).value||'',
    manuais:(document.getElementById('exp-manuais')||{}).value||'',
  };
}
// Equipamento sem nenhum documento aplicável (tudo em N/A) não é pendente nem
// finalizado: fica de fora das três faixas, como o idp() que devolve null.
function _groupGlobalStatus(g){
  const c = equipStatusColor(g);
  return c==='green' ? 'Finalizado' : c==='red' ? 'Pendente'
       : c==='neutro' ? 'Sem escopo' : 'Em progresso';
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
    if(cfg.manuais){
      const cnt=equipManuaisAplicaveis(g), ok=equipManuaisOk(g);
      if(cfg.manuais==='completos' && !(cnt>0 && ok===cnt)) return false;
      if(cfg.manuais==='incompletos' && !(cnt>0 && ok<cnt)) return false;
      if(cfg.manuais==='sem' && cnt>0) return false;
    }
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
  const man=document.getElementById('exp-manuais'); if(man) man.value='';
  ['exp-inicio','exp-fim','exp-datebase','exp-status','exp-manuais'].forEach(id=>{const e=document.getElementById(id); if(e) e.onchange=updateExportPreview;});
  updateExportPreview();
  openBaseModal('export');
}
// build pode ser um objeto de config ou uma função(ctx,w,h)=>config (para gradientes/plugins)
function _renderChartImage(build, wpx, hpx){
  return new Promise(resolve=>{
    if(typeof Chart==='undefined'){ resolve(null); return; }
    const canvas=document.createElement('canvas');
    canvas.width=wpx; canvas.height=hpx;
    canvas.style.position='fixed'; canvas.style.left='-10000px'; canvas.style.top='0';
    document.body.appendChild(canvas);
    const ctx=canvas.getContext('2d');
    const cfg = (typeof build==='function') ? build(ctx, wpx, hpx) : build;
    cfg.options=cfg.options||{};
    cfg.options.responsive=false; cfg.options.animation=false; cfg.options.maintainAspectRatio=false;
    let chart;
    try{ chart=new Chart(ctx, cfg); }catch(e){ canvas.remove(); resolve(null); return; }
    requestAnimationFrame(()=>{
      let url=null;
      try{ url=chart.canvas.toDataURL('image/png'); }catch(e){}
      try{ chart.destroy(); }catch(e){}
      canvas.remove();
      resolve(url);
    });
  });
}
const _CHART_FONT = "'Inter', system-ui, sans-serif";
function _vgrad(ctx, h, c1, c2){ const g=ctx.createLinearGradient(0,0,0,h); g.addColorStop(0,c1); g.addColorStop(1,c2); return g; }
function _hgrad(ctx, w, c1, c2){ const g=ctx.createLinearGradient(0,0,w,0); g.addColorStop(0,c1); g.addColorStop(1,c2); return g; }
function _centerTextPlugin(big, small){
  return { id:'centerText', afterDraw(chart){
    const a=chart.chartArea; if(!a) return; const ctx=chart.ctx;
    const cx=(a.left+a.right)/2, cy=(a.top+a.bottom)/2;
    ctx.save(); ctx.textAlign='center'; ctx.textBaseline='middle';
    ctx.fillStyle='#f1f5f9'; ctx.font='bold 60px '+_CHART_FONT; ctx.fillText(String(big), cx, cy-6);
    ctx.fillStyle='#94a3ff'; ctx.font='600 22px '+_CHART_FONT; ctx.fillText(small, cx, cy+32);
    ctx.restore();
  }};
}
// valores ao final de barras horizontais (texto claro)
const _barValueHPlugin = { id:'barValuesH', afterDatasetsDraw(chart){
  const ctx=chart.ctx; const meta=chart.getDatasetMeta(0);
  chart.data.datasets[0].data.forEach((v,i)=>{ const el=meta.data[i]; if(!el) return;
    ctx.save(); ctx.fillStyle='#f1f5f9'; ctx.font='bold 26px '+_CHART_FONT; ctx.textAlign='left'; ctx.textBaseline='middle';
    ctx.fillText(String(v), el.x+10, el.y); ctx.restore();
  });
}};

// Insere imagem preservando a proporção (sem achatar), centralizada na caixa.
// imgRatio = largura/altura da imagem renderizada.
function _addImgContain(doc, img, x, y, boxW, boxH, imgRatio){
  if(!img) return;
  let w = boxW, h = boxW/imgRatio;
  if(h > boxH){ h = boxH; w = boxH*imgRatio; }
  doc.addImage(img, 'PNG', x + (boxW-w)/2, y + (boxH-h)/2, w, h);
}

async function gerarRelatorioPDF(){
  if(!window.jspdf){ showToast('Aguarde o carregamento do gerador de PDF e tente novamente','error'); return; }
  const groups = _exportFilteredGroups();
  if(!groups.length){ showToast('Nenhum equipamento corresponde aos filtros','error'); return; }
  showToast('Gerando relatório...','info');
  const cfg = _exportConfig();
  const baseLabel = {data_homologacao:'Homologação', data_treinamento:'Treinamento', updated_em:'Últ. atualização'}[cfg.base]||cfg.base;

  // Equipamentos sem escopo (todos os documentos em N/A) ficam fora das faixas:
  // não são pendência nem conclusão, só não têm o que medir.
  let fin=0, prog=0, pend=0, preHom=0, man100=0;
  groups.forEach(g=>{
    const st=_groupGlobalStatus(g);
    if(st==='Sem escopo') return;
    if(st==='Finalizado')fin++; else if(st==='Em progresso')prog++; else pend++;
    if(g.pre && g.pre.status==='Homologado') preHom++;
    const cnt=equipManuaisAplicaveis(g);
    if(cnt>0 && equipManuaisOk(g)===cnt) man100++;
  });
  const preStatuses=['Elaborar','Treinamento Piloto','Enviado para Homologação','Homologado'];
  const preCounts=preStatuses.map(s=>groups.filter(g=>g.pre&&g.pre.status===s).length);
  let manOk=0, manTot=0; groups.forEach(g=>{ manOk+=equipManuaisOk(g); manTot+=equipManuaisAplicaveis(g); });
  const manPend = Math.max(0, manTot-manOk);
  const manPct = manTot? Math.round(manOk/manTot*100) : 0;

  // Gráficos (Chart.js → PNG transparente, para os cartões escuros)
  const LEG = {color:'#cbd5ff', font:{size:24, family:_CHART_FONT}, padding:18, boxWidth:16, usePointStyle:true, pointStyle:'circle'};
  const donutImg = await _renderChartImage((ctx)=>({
    type:'doughnut',
    data:{labels:['Finalizado','Em progresso','Pendente'],
      datasets:[{data:[fin,prog,pend], backgroundColor:['#34d399','#fbbf24','#fb7185'], borderColor:'#1a1f3a', borderWidth:5}]},
    options:{cutout:'66%', layout:{padding:14}, plugins:{legend:{display:false}}},
    plugins:[_centerTextPlugin(groups.length, 'equipamentos')]
  }), 760, 760);
  const manuaisImg = await _renderChartImage((ctx)=>({
    type:'doughnut',
    data:{labels:['Concluídos','Pendentes'],
      datasets:[{data:[manOk, manPend], backgroundColor:['#22d3ee','#3a4170'], borderColor:'#1a1f3a', borderWidth:5}]},
    options:{cutout:'66%', layout:{padding:14}, plugins:{legend:{display:false}}},
    plugins:[_centerTextPlugin(manPct+'%', manOk+' de '+manTot)]
  }), 760, 760);
  const barImg = await _renderChartImage((ctx)=>({
    type:'bar',
    data:{labels:['Elaborar','Trein. Piloto','Envio Homol.','Homologado'],
      datasets:[{data:preCounts, borderRadius:8, maxBarThickness:48,
        backgroundColor:[_hgrad(ctx,1300,'#818cf8','#a78bfa'), _hgrad(ctx,1300,'#fbbf24','#fcd34d'), _hgrad(ctx,1300,'#22d3ee','#67e8f9'), _hgrad(ctx,1300,'#34d399','#6ee7b7')]}]},
    options:{indexAxis:'y', layout:{padding:{right:54, left:6, top:4, bottom:4}}, plugins:{legend:{display:false}},
      scales:{x:{beginAtZero:true, ticks:{display:false}, grid:{color:'rgba(148,163,255,.14)'}, border:{display:false}},
              y:{ticks:{color:'#cbd5ff', font:{size:27, family:_CHART_FONT}}, grid:{display:false}, border:{display:false}}}},
    plugins:[_barValueHPlugin]
  }), 1320, 700);

  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({orientation:'landscape', unit:'mm', format:'a4'});
  const pageW = doc.internal.pageSize.getWidth();
  const pageH = doc.internal.pageSize.getHeight();
  const margin = 12;
  const C = { bg:[13,16,32], card:[26,31,58], rowAlt:[20,24,46], border:[42,54,98],
    t1:[241,245,249], tmut:[148,163,255], accent:[34,211,238],
    green:[52,211,153], amber:[251,191,36], red:[251,113,133], cyan:[34,211,238] };
  const globColor = {Finalizado:C.green, 'Em progresso':C.amber, Pendente:C.red};
  function paintBg(){ doc.setFillColor(...C.bg); doc.rect(0,0,pageW,pageH,'F'); }
  function card(x,yy,w,h){ doc.setFillColor(...C.card); doc.setDrawColor(...C.border); doc.setLineWidth(0.3); doc.roundedRect(x,yy,w,h,2.5,2.5,'FD'); }
  function cardTitle(txt,x,yy,w){ doc.setFont('helvetica','bold'); doc.setFontSize(8.5); doc.setTextColor(...C.accent); doc.text(txt.toUpperCase(), x+w/2, yy+6.5, {align:'center'}); }
  // legenda nativa (vetorial, nítida): linha de itens [cor, rótulo] centralizada em cx
  function legendRow(items, cx, yy){
    doc.setFont('helvetica','normal'); doc.setFontSize(8.5);
    const r=1.5, dotGap=2.2, itemGap=8;
    const widths = items.map(([c,l])=> r*2 + dotGap + doc.getTextWidth(l));
    const total = widths.reduce((a,b)=>a+b,0) + itemGap*(items.length-1);
    let x = cx - total/2;
    items.forEach(([col,lab],i)=>{
      doc.setFillColor(...col); doc.circle(x+r, yy-1.1, r, 'F');
      doc.setTextColor(...C.t1); doc.text(lab, x+r*2+dotGap, yy);
      x += widths[i] + itemGap;
    });
  }

  const hoje = new Date().toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
  const filtros = [];
  if(cfg.inicio||cfg.fim) filtros.push(`Período (${baseLabel}): ${cfg.inicio||'…'} a ${cfg.fim||'…'}`);
  if(cfg.status) filtros.push(`Status: ${cfg.status}`);
  if(cfg.manuais) filtros.push(`Manuais: ${({completos:'Completos (5/5)', incompletos:'Incompletos (<5)', sem:'Sem manuais'})[cfg.manuais]||cfg.manuais}`);
  if(!filtros.length) filtros.push('Sem filtros');

  paintBg();
  // ── Cabeçalho
  doc.setFont('helvetica','bold'); doc.setFontSize(19); doc.setTextColor(...C.t1);
  doc.text('Relatório Executivo de KPIs', margin, 18);
  doc.setFont('helvetica','bold'); doc.setFontSize(10); doc.setTextColor(...C.accent);
  doc.text('DocTrack Enterprise v4.0', margin, 25);
  doc.setFont('helvetica','normal'); doc.setFontSize(8); doc.setTextColor(...C.tmut);
  doc.text('Gerado em '+hoje, pageW-margin, 16, {align:'right'});
  doc.text(filtros.join('   ·   '), pageW-margin, 22, {align:'right'});
  doc.setDrawColor(...C.accent); doc.setLineWidth(0.5); doc.line(margin, 29, pageW-margin, 29);

  let y = 34;
  // ── Linha A: KPIs + 2 donuts
  const rowAh = 74, gap = 4, colW = 58;
  const kpis = [['Equipamentos', groups.length, C.t1],['Finalizados', fin, C.green],['Em progresso', prog, C.amber],['Pendentes', pend, C.red]];
  const kh = (rowAh - gap*3)/4;
  kpis.forEach(([lab,val,col],i)=>{
    const cy = y + i*(kh+gap);
    card(margin, cy, colW, kh);
    doc.setFont('helvetica','normal'); doc.setFontSize(8); doc.setTextColor(...C.tmut);
    doc.text(lab, margin+5, cy+kh/2+1);
    doc.setFont('helvetica','bold'); doc.setFontSize(16); doc.setTextColor(...col);
    doc.text(String(val), margin+colW-5, cy+kh/2+1.5, {align:'right'});
  });
  const donW = (pageW - margin*2 - colW - gap*2)/2;
  const d1x = margin+colW+gap, d2x = d1x+donW+gap;
  const donImgH = rowAh - 9 - 9; // deixa ~9mm no rodapé para a legenda nativa
  card(d1x, y, donW, rowAh); cardTitle('Status global', d1x, y, donW);
  _addImgContain(doc, donutImg, d1x+6, y+9, donW-12, donImgH, 1);
  legendRow([['Finalizado',C.green],['Em progresso',C.amber],['Pendente',C.red]].map(([l,c])=>[c,l]), d1x+donW/2, y+rowAh-4);
  card(d2x, y, donW, rowAh); cardTitle('Manuais (conclusão)', d2x, y, donW);
  _addImgContain(doc, manuaisImg, d2x+6, y+9, donW-12, donImgH, 1);
  legendRow([['Concluídos',C.cyan],['Pendentes',[58,65,112]]].map(([l,c])=>[c,l]), d2x+donW/2, y+rowAh-4);

  y += rowAh + gap;
  // ── Linha B: composição (tabela) + IT/PRE por etapa (barras)
  const rowBh = pageH - y - 11;
  const tblW = 118, barsW = pageW - margin*2 - tblW - gap;
  card(margin, y, tblW, rowBh); cardTitle('Composição por status', margin, y, tblW);
  let ty = y+16;
  doc.setFont('helvetica','bold'); doc.setFontSize(7.5); doc.setTextColor(...C.tmut);
  doc.text('STATUS', margin+11, ty); doc.text('EQUIP.', margin+tblW-38, ty, {align:'right'}); doc.text('%', margin+tblW-9, ty, {align:'right'});
  ty += 2.5; doc.setDrawColor(...C.border); doc.setLineWidth(0.3); doc.line(margin+6, ty, margin+tblW-6, ty); ty += 8;
  [['Finalizado', fin, C.green],['Em progresso', prog, C.amber],['Pendente', pend, C.red]].forEach(([lab,val,col])=>{
    doc.setFillColor(...col); doc.circle(margin+9, ty-1.4, 1.7, 'F');
    doc.setFont('helvetica','normal'); doc.setFontSize(10); doc.setTextColor(...C.t1); doc.text(lab, margin+14, ty);
    doc.setFont('helvetica','bold'); doc.text(String(val), margin+tblW-38, ty, {align:'right'});
    doc.setFont('helvetica','normal'); doc.setTextColor(...C.tmut); doc.text((groups.length?Math.round(val/groups.length*100):0)+'%', margin+tblW-9, ty, {align:'right'});
    ty += 11;
  });
  // resumo manuais dentro do mesmo cartão
  ty += 2; doc.setDrawColor(...C.border); doc.line(margin+6, ty-4, margin+tblW-6, ty-4);
  doc.setFont('helvetica','normal'); doc.setFontSize(9); doc.setTextColor(...C.tmut);
  doc.text('Manuais concluídos', margin+9, ty);
  doc.setFont('helvetica','bold'); doc.setTextColor(...C.cyan); doc.text(`${manOk} / ${manTot}  (${manPct}%)`, margin+tblW-9, ty, {align:'right'});
  ty += 11;
  doc.setFont('helvetica','normal'); doc.setFontSize(9); doc.setTextColor(...C.tmut);
  doc.text('IT/PRE homologados', margin+9, ty);
  doc.setFont('helvetica','bold'); doc.setTextColor(...C.green); doc.text(String(preHom), margin+tblW-9, ty, {align:'right'});

  const bx = margin+tblW+gap;
  card(bx, y, barsW, rowBh); cardTitle('IT/PRE por etapa', bx, y, barsW);
  if(barImg) doc.addImage(barImg, 'PNG', bx+4, y+10, barsW-8, rowBh-14);

  // ── Página 2: detalhamento por equipamento (escuro)
  doc.addPage(); paintBg(); y = margin+4;
  doc.setFont('helvetica','bold'); doc.setFontSize(14); doc.setTextColor(...C.t1);
  doc.text('Detalhamento por equipamento', margin, y+4); y += 11;

  const cols = [
    {h:'Equipamento', k:'equip', w:62},
    {h:'SKU', k:'sku', w:28},
    {h:'Responsável', k:'resp', w:46},
    {h:'IT / PRE', k:'pre', w:42},
    {h:'Manuais', k:'man', w:22},
    {h:'Status', k:'glob', w:30},
    {h:baseLabel, k:'data', w:27},
  ];
  const rowH=7.2, headerH=9;
  function thead(){
    doc.setFillColor(...C.card); doc.rect(margin,y,pageW-margin*2,headerH,'F');
    doc.setFont('helvetica','bold'); doc.setFontSize(7.5); doc.setTextColor(...C.accent);
    let cx=margin; cols.forEach(c=>{doc.text(c.h, cx+3, y+6); cx+=c.w;}); y+=headerH;
  }
  thead();
  groups.forEach((g,idx)=>{
    if(y+rowH > pageH-11){ doc.addPage(); paintBg(); y=margin+4; thead(); }
    if(idx%2===0){ doc.setFillColor(...C.rowAlt); doc.rect(margin,y,pageW-margin*2,rowH,'F'); }
    doc.setDrawColor(...C.border); doc.setLineWidth(0.15); doc.line(margin,y+rowH,pageW-margin,y+rowH);
    const ok=equipManuaisOk(g), manTot=equipManuaisAplicaveis(g);
    const glob=_groupGlobalStatus(g);
    const row = {
      equip: g.equipamento, sku: g.sku||'—', resp: (g.pre&&g.pre.responsavel)||'—',
      pre: g.pre? g.pre.status : '—', man: manTot? (ok+'/'+manTot) : '—',
      glob: glob, data: g.pre? ((g.pre[cfg.base]||'—').split(' ')[0]||'—') : '—',
    };
    let cx=margin;
    doc.setFontSize(7.5);
    cols.forEach(c=>{
      let v=String(row[c.k]==null?'':row[c.k]);
      const maxW=c.w-4;
      if(doc.getTextWidth(v)>maxW){ v=v.substring(0, Math.max(1, Math.floor(v.length*maxW/doc.getTextWidth(v))-1))+'…'; }
      if(c.k==='glob'){ doc.setFont('helvetica','bold'); doc.setTextColor(...(globColor[glob]||C.t1)); }
      else { doc.setFont('helvetica', c.k==='equip'?'bold':'normal'); doc.setTextColor(...(c.k==='equip'?C.t1:C.tmut)); }
      doc.text(v, cx+3, y+4.8); cx+=c.w;
    });
    y+=rowH;
  });

  // ── Rodapés
  const pages=doc.internal.getNumberOfPages();
  for(let i=1;i<=pages;i++){ doc.setPage(i); doc.setFont('helvetica','normal'); doc.setFontSize(7); doc.setTextColor(...C.tmut);
    doc.text('DocTrack Enterprise — Relatório confidencial', margin, pageH-5);
    doc.text(`Página ${i} de ${pages}`, pageW-margin, pageH-5, {align:'right'}); }

  doc.save('DocTrack_Relatorio.pdf');
  closeModal('export');
  showToast('Relatório gerado','success');
}

async function loadEnums(){
  try{const res=await apiFetch('/enums');if(res&&res.ok)_enums=await res.json()}catch(e){}
}
async function loadData(){
  await loadEquipamentos();
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
// Identidade dos equipamentos (mapas por nome e por id), fonte única de
// nome_original/ANVISA/família. O mapa por id é a chave da sincronização.
async function loadEquipamentos(){
  allEquip={}; allEquipById={};
  try{
    const res=await apiFetch('/equipamentos');
    if(res&&res.ok){(await res.json()).forEach(e=>{
      allEquip[(e.nome||'').trim()] = e;
      allEquipById[e.id] = e;
    });}
  }catch(e){}
}
async function refreshAll(){await loadData();renderDashboard();renderDocs();loadFluxo();showToast('Dados atualizados','success');
  document.getElementById('sync-label').textContent='Atualizado · '+new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
}

// A sincronização por planilha (reimportExcel) não existe mais: a rota
// /api/reimport dropava as tabelas de documentos antes de reinserir a planilha.
// O seed por Excel ficou restrito a `servidor.py --init` em banco vazio.

// ═══ DASHBOARD ═══
// Replica compute_kpis() do servidor para recalcular o dashboard por equipamento
// (filtro client-side; estrutura idêntica à de _lastKpis).
// Os DOIS filtros do servidor precisam existir aqui, senão o mesmo equipamento
// mostra números diferentes conforme o filtro do dashboard estiver ligado:
//   1) N/A fora da conta;  2) só setores de equipamento (processo não entra).
function computeKpisJS(docs){
  const setores=Object.keys((_lastKpis&&_lastKpis.por_setor)||{});
  const por_setor={},status_counts={};
  setores.forEach(s=>{por_setor[s]=0;status_counts[s]={};});
  const global_counts={'Pendente':0,'Em progresso':0,'Finalizado':0};
  const aplicaveis=docs.filter(d=>d.aplicavel!==false);
  const processos=aplicaveis.filter(d=>!(d.setor in por_setor)).length;
  const view=aplicaveis.filter(d=>d.setor in por_setor);
  let atrasados=0;
  view.forEach(d=>{
    const setor=d.setor;
    por_setor[setor]++;
    const st=d.status||'Elaborar';status_counts[setor][st]=(status_counts[setor][st]||0)+1;
    const sg=d.status_global||'Pendente';global_counts[sg]=(global_counts[sg]||0)+1;
    if(d.atrasado) atrasados++;
  });
  const total=view.length,fin=global_counts['Finalizado']||0;
  return {total,finalizados:fin,em_progresso:global_counts['Em progresso']||0,pendentes:global_counts['Pendente']||0,
    backlog:total-fin,atrasados,processos,
    pct_concluidos:total?Math.round(fin/total*1000)/10:0,por_setor,status_counts,global_counts};
}

// Popula o seletor de equipamento do dashboard a partir de allDocs.
function populateDashEquip(){
  const sel=document.getElementById('dash-equip-sel');
  if(!sel) return;
  const nomes=[...new Set(allDocs.map(d=>(d.equipamento||'').trim()).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
  if(_dashEquip && !nomes.includes(_dashEquip)) _dashEquip='';
  sel.innerHTML='<option value="">Todos os equipamentos</option>'+
    nomes.map(n=>`<option value="${esc(n)}" ${n===_dashEquip?'selected':''}>${esc(n)}</option>`).join('');
  sel.value=_dashEquip;
}

function setDashEquip(v){ _dashEquip=v||''; renderDashboard(); renderFluxo(); }

// ═══ FLUXO DE TRABALHO ═══
// Leituras de GET /api/documentos/metricas e /alertas. A trilha do documento
// (documento_historico) já era gravada a cada troca de status desde sempre e só
// alimentava a lista da ficha — nenhum número do dashboard vinha dela.
let _fluxo=null, _fluxoAlertas=null;

const SEV_COR={critico:'#ef4444',atencao:'#f59e0b',info:'#22d3ee'};
const SEV_LBL={critico:'Crítico',atencao:'Atenção',info:'Info'};

// Não existe modal de um documento isolado: a ficha é do equipamento (as 12
// abas de tipo moram lá). Um clique no alerta abre a ficha do equipamento dele.
function abrirDoFluxo(equipId, equipNome){
  const key = equipId ? ('id:'+equipId) : ('nome:'+(equipNome||''));
  navigate('docs');
  openEquipModal(key);
}

async function loadFluxo(){
  const qs = _dashEquip && allEquip[_dashEquip] ? `?equipamento_id=${allEquip[_dashEquip].id}` : '';
  try{
    const [m,a] = await Promise.all([
      apiFetch('/documentos/metricas'+qs),
      apiFetch('/documentos/alertas'),
    ]);
    _fluxo = m ? await m.json() : null;
    _fluxoAlertas = a ? await a.json() : null;
  }catch(e){ _fluxo=null; _fluxoAlertas=null; }
  renderFluxo();
}

function renderFluxo(){
  const set=(id,html)=>{const el=document.getElementById(id); if(el) el.innerHTML=html;};
  if(!_fluxo){
    set('flx-cards','<div class="loading-state" style="grid-column:1/-1">Sem dados de fluxo</div>');
    return;
  }
  const t=_fluxo.totais, ct=_fluxo.cycle_time;
  const jan=document.getElementById('flx-janela');
  if(jan) jan.textContent=`últimos ${_fluxo.janela_dias} dias`;

  // Quatro números que não existiam em tela nenhuma antes.
  // Throughput e ciclo só contam documentos com data de conclusão REAL (uma
  // transição registrada na trilha). Os concluídos antes da instrumentação não
  // têm essa data, e o rodapé do card diz isso em vez de fingir cobertura total.
  const semData=_fluxo.throughput.sem_data||0;
  const cards=[
    {v:t.wip, l:'Em andamento (WIP)', c:'#22d3ee',
     t:'Documentos efetivamente em curso — nem no início, nem prontos'},
    {v:_fluxo.throughput.concluidos, l:`Concluídos em ${_fluxo.janela_dias}d`, c:'#10b981',
     t:'Throughput: quantos saíram no período, medidos pela trilha'},
    {v:ct.p85!=null?ct.p85+'d':'—', l:'Ciclo p85', c:'#a78bfa',
     t:ct.amostra?`85% concluíram em até este prazo (${ct.amostra} medição(ões))`
                 :'Sem medição ainda — depende de conclusões registradas pela trilha'},
    {v:t.atrasados, l:'Atrasados', c:'#ef4444',
     t:'Prazo vencido e ainda não finalizado'},
  ];
  set('flx-cards', cards.map(c=>`
    <div class="metric-card" title="${esc(c.t)}">
      <div class="metric-info">
        <div class="metric-value" style="color:${c.c}">${esc(String(c.v))}</div>
        <div class="metric-label">${esc(c.l)}</div>
      </div>
    </div>`).join(''));

  // Tempo médio parado em cada status: onde o fluxo trava.
  const maxDias=Math.max(1,..._fluxo.por_status.map(s=>s.dias_medios||0));
  set('flx-status', _fluxo.por_status.map(s=>{
    const pct=Math.round((s.dias_medios||0)/maxDias*100);
    return `<div class="prog-row" title="${s.amostras} medição(ões) na trilha">
      <span class="prog-label">${esc(s.status)}</span>
      <div class="prog-track"><div class="prog-fill" style="width:${pct}%;background:#a78bfa"></div></div>
      <span class="prog-pct">${s.dias_medios}d</span></div>`;
  }).join('')+`<div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border-dim);display:flex;justify-content:space-between;font-size:11px;color:var(--t3)">
      <span>Tempo médio no status</span>
      <span>avanço ponderado <b style="color:var(--cyan)">${_fluxo.avanco.ponderado}%</b></span></div>`
    +(semData?`<div style="margin-top:8px;font-size:10px;color:var(--t3);line-height:1.5">
        ⓘ ${semData} documento(s) já concluído(s) antes da instrumentação não têm
        data de conclusão registrada — entram no avanço, mas ficam fora do
        throughput e do tempo de ciclo.</div>`:''));

  // Aging: quem está esquecido. Ordenado pelo backend.
  set('flx-aging', _fluxo.aging.length ? _fluxo.aging.map(a=>`
    <div class="prog-row" style="cursor:pointer" onclick="abrirDoFluxo(${a.equipamento_id||'null'},'${esc(a.equipamento).replace(/'/g,"\\'")}')"
         title="${esc(a.equipamento)} · ${esc(a.status)}">
      <span class="prog-label" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(a.documento)}</span>
      <span class="prog-pct" style="color:${a.dias>=180?'#ef4444':a.dias>=60?'#f59e0b':'var(--t2)'}">${a.dias}d</span>
    </div>`).join('') : '<div class="loading-state">Nada parado</div>');

  // Carga por pessoa — só possível depois do N:N de responsáveis.
  const maxCarga=Math.max(1,..._fluxo.por_responsavel.map(r=>r.abertos));
  set('flx-carga', _fluxo.por_responsavel.length ? _fluxo.por_responsavel.slice(0,8).map(r=>`
    <div class="prog-row" title="${r.peso} de peso · ${r.parados} parado(s) há 30d+">
      <span class="prog-label" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(r.nome)}</span>
      <div class="prog-track"><div class="prog-fill" style="width:${Math.round(r.abertos/maxCarga*100)}%;background:${r.atrasados?'#f59e0b':'#22d3ee'}"></div></div>
      <span class="prog-pct">${r.abertos}${r.atrasados?` <span style="color:#ef4444">(${r.atrasados})</span>`:''}</span>
    </div>`).join('') : '<div class="loading-state">Sem atribuições</div>');

  renderFluxoAlertas();
}

function renderFluxoAlertas(){
  const el=document.getElementById('flx-alertas');
  const cnt=document.getElementById('flx-alertas-total');
  if(!el) return;
  if(!_fluxoAlertas){ el.innerHTML='<div class="loading-state">—</div>'; return; }
  if(cnt) cnt.textContent=_fluxoAlertas.total
    ? `${_fluxoAlertas.total} item(ns) · ${_fluxoAlertas.criticos} crítico(s)`
    : 'nada pendente';
  if(!_fluxoAlertas.alertas.length){
    el.innerHTML='<div class="loading-state">Nenhum alerta — tudo em ordem</div>';
    return;
  }
  // Já vem ordenado por severidade do backend (mesmo formato de projetos/missões).
  el.innerHTML=_fluxoAlertas.alertas.slice(0,40).map(a=>`
    <div style="display:flex;gap:10px;align-items:flex-start;padding:9px 0;border-bottom:1px solid var(--border-dim);cursor:pointer"
         onclick="abrirDoFluxo(${a.equipamento_id||'null'},'${esc(a.equipamento).replace(/'/g,"\\'")}')">
      <span style="width:7px;height:7px;border-radius:50%;background:${SEV_COR[a.severidade]||'#22d3ee'};margin-top:6px;flex-shrink:0"
            title="${esc(SEV_LBL[a.severidade]||a.severidade)}"></span>
      <div style="flex:1;min-width:0">
        <div style="font-size:12px;font-weight:600;color:var(--t1)">${esc(a.titulo)}</div>
        <div style="font-size:11px;color:var(--t3);margin-top:2px">${esc(a.detalhe)}</div>
        <div style="font-size:10px;color:var(--t3);margin-top:3px;font-family:var(--font-mono)">${esc(a.equipamento)} · ${esc(a.documento)}</div>
      </div>
    </div>`).join('');
}

function renderDashboard(){
  if(!_lastKpis) return;
  populateDashEquip();
  const docsView=_dashEquip ? allDocs.filter(d=>(d.equipamento||'').trim()===_dashEquip) : allDocs;
  const kpis=_dashEquip ? computeKpisJS(docsView) : _lastKpis;
  const total=kpis.total;

  const infoEl=document.getElementById('dash-equip-info');
  if(infoEl) infoEl.textContent=_dashEquip ? (total+' documento(s) deste equipamento') : '';
  document.getElementById('dash-updated').textContent='Última atualização: '+new Date().toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
  // `total` conta só documentos de equipamento aplicáveis — é o mesmo número que
  // o donut soma. Processo (POPs/ITs da área) e atrasados aparecem à parte.
  document.getElementById('dash-pct-badge').textContent=total+' documentos';
  const extraEl=document.getElementById('dash-extra');
  if(extraEl){
    const partes=[];
    if(kpis.atrasados) partes.push(`<span class="dash-flag late" title="Prazo vencido e ainda não finalizado">⏰ ${kpis.atrasados} atrasado${kpis.atrasados>1?'s':''}</span>`);
    if(kpis.processos) partes.push(`<span class="dash-flag" title="POPs e ITs da área — fora da completude dos equipamentos">📄 ${kpis.processos} de processo</span>`);
    extraEl.innerHTML=partes.join('');
  }

  const ringColors=['#10b981','#22d3ee','#06b6d4'];
  const ringBgs=['rgba(16,185,129,.15)','rgba(34,211,238,.15)','rgba(168,85,247,.15)'];
  const sgKeys=['Finalizado','Em progresso','Pendente'];
  let kpiHTML='';
  sgKeys.forEach((k,i)=>{
    const v=kpis.global_counts[k]||0,pct=total?Math.round(v/total*100):0;
    kpiHTML+=`<div class="kpi-ring">
      <div class="kpi-ring-canvas" style="width:110px;height:110px"><canvas id="ring${i}" width="110" height="110"></canvas><div class="kpi-ring-val" style="color:${ringColors[i]}">${v}</div></div>
      <div class="kpi-ring-label">${esc(k)}</div>
      <div class="kpi-ring-delta" style="color:${ringColors[i]}">${pct}% do total</div>
    </div>`;
  });
  document.getElementById('kpi-grid').innerHTML=kpiHTML||'<div class="loading-state" style="grid-column:1/-1">Sem dados</div>';

  sgKeys.forEach((k,i)=>{
    const v=kpis.global_counts[k]||0,pct=total?v/total:0;
    if(chartInstances['ring'+i])chartInstances['ring'+i].destroy();
    chartInstances['ring'+i]=new Chart(document.getElementById('ring'+i),{
      type:'doughnut',data:{datasets:[{data:[pct*100,100-pct*100],backgroundColor:[ringColors[i],ringBgs[i]],borderWidth:0,hoverOffset:4}]},
      options:{responsive:false,cutout:'78%',plugins:{legend:{display:false},tooltip:{enabled:false}},animation:{animateRotate:true,duration:1200}}
    });
  });

  const catLabels=Object.keys(kpis.por_setor),catVals=Object.values(kpis.por_setor);
  // mesma paleta do donut de status dos entregáveis (verde, ciano, âmbar)
  const donutPalette=['#10b981','#22d3ee','#f59e0b','#a78bfa','#06b6d4'];
  const dColors=catLabels.map((c,i)=>donutPalette[i % donutPalette.length]);
  document.getElementById('donut-total').textContent=total;
  document.getElementById('donut-legend').innerHTML=catLabels.map((c,i)=>{
    return`<div class="legend-row" title="${esc(c)}"><span class="legend-dot" style="background:${dColors[i]}"></span><span>${esc(c)}</span><span class="legend-val">${catVals[i]}</span></div>`;
  }).join('');
  if(chartInstances.donut)chartInstances.donut.destroy();
  const elDonut=document.getElementById('cDonut');
  const donutBg=elDonut?dColors.map(c=>donutGrad(elDonut.getContext('2d'),c)):dColors;
  chartInstances.donut=new Chart(elDonut,{
    type:'doughnut',
    data:{labels:catLabels,datasets:[{data:catVals,backgroundColor:donutBg,dotColors:dColors,borderWidth:0,borderRadius:8,spacing:3,hoverOffset:6}]},
    options:{responsive:false,cutout:'78%',plugins:{legend:{display:false},tooltip:{enabled:false,external:donutTooltipExternal,callbacks:{label:ctx=>` ${catLabels[ctx.dataIndex]}: ${ctx.parsed} docs`}}},animation:{animateRotate:true,duration:1200}}
  });

  // Exemplo de pipeline simples usando os status da PRE
  const etapaNames=_enums.status_map?_enums.status_map['PRE']:[];
  const preStatusCounts = kpis.status_counts['PRE'] || {};
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
    type:'bar',data:{labels:catLabels,datasets:[{data:catVals,backgroundColor:gradBar,dotColors:dColors,borderRadius:8,borderWidth:0}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{enabled:false,external:donutTooltipExternal,callbacks:{label:ctx=>` ${ctx.label}: ${ctx.parsed.y} docs`}}},
      scales:{x:{ticks:{color:'#94a3ff',font:{size:10,family:'Inter'}},grid:{display:false},border:{display:false}},
              y:{ticks:{color:'#94a3ff',font:{size:10,family:'Inter'},stepSize:20},grid:{color:'rgba(167,139,250,.06)'},border:{display:false}}}}
  });

  // Flatten status para chart de status
  const flatStatus = {};
  Object.values(kpis.status_counts).forEach(sc => {
    Object.keys(sc).forEach(k => flatStatus[k] = (flatStatus[k]||0) + sc[k]);
  });
  const stLabels=Object.keys(flatStatus),stVals=Object.values(flatStatus);
  const stColors=stLabels.map(s=>STATUS_PILL[s] ? (s==='Elaborar'?'#06b6d4':s.includes('Homologado')||s==='Concluído'?'#10b981':'#22d3ee') : '#ec4899');
  
  if(chartInstances.status)chartInstances.status.destroy();
  chartInstances.status=new Chart(document.getElementById('chartStatus'),{
    type:'bar',data:{labels:stLabels.map(l=>l.length>18?l.substring(0,18)+'…':l),datasets:[{data:stVals,backgroundColor:stColors,dotColors:stColors,borderRadius:8,borderWidth:0}]},
    options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{enabled:false,external:donutTooltipExternal,callbacks:{label:ctx=>` ${ctx.label}: ${ctx.parsed.x} docs`}}},
      scales:{x:{ticks:{color:'#94a3ff',font:{size:10,family:'Inter'}},grid:{color:'rgba(167,139,250,.06)'},border:{display:false}},
              y:{ticks:{color:'#c7d2fe',font:{size:11,family:'Inter',weight:'500'}},grid:{display:false},border:{display:false}}}}
  });

  document.getElementById('dash-table').innerHTML=docsView.slice(0,10).map(d=>
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

// ═══ AUXILIARES DE ARQUIVO ═══
// Compartilhados pela lista de arquivos hospedados na plataforma
// (renderArquivoPlataforma).
function _fmtTamanho(b){
  if(!b) return '';
  if(b < 1024) return b+' B';
  if(b < 1048576) return (b/1024).toFixed(0)+' KB';
  return (b/1048576).toFixed(1)+' MB';
}

const _ICON_ARQUIVO = {
  pdf:'#ef4444', docx:'#2563eb', doc:'#2563eb', xlsx:'#16a34a', xls:'#16a34a',
  zip:'#a855f7', rar:'#a855f7', png:'#0891b2', jpg:'#0891b2', jpeg:'#0891b2'
};

// Garante que todo o conteúdo (tabelas/imagens) caiba dentro dos limites da folha A4
function _ajustarDocxNaPagina(body){
  const secs = body.querySelectorAll('.docx-wrapper > section.docx');
  secs.forEach(sec=>{
    const cs = getComputedStyle(sec);
    const avail = sec.clientWidth - (parseFloat(cs.paddingLeft)||0) - (parseFloat(cs.paddingRight)||0);
    // tabelas mais largas que a área útil → layout fixo para redistribuir as colunas
    sec.querySelectorAll('table').forEach(t=>{
      if(t.offsetWidth > avail + 1){
        t.style.tableLayout = 'fixed';
        t.style.width = '100%';
      }
    });
    // imagens largas → limita à largura da página
    sec.querySelectorAll('img').forEach(im=>{
      if(im.offsetWidth > avail){ im.style.maxWidth = '100%'; im.style.height = 'auto'; }
    });
    // rede de segurança: se ainda sobrar algo estourando, encolhe a página inteira para caber
    if(sec.scrollWidth > sec.clientWidth + 1){
      sec.style.zoom = (sec.clientWidth / sec.scrollWidth).toFixed(4);
    }
  });
}

// ═══ DOCS — GRADE DE EQUIPAMENTOS ═══
let _equipChip = 'todos';

// Agrupa allDocs por EQUIPAMENTO (entidade). A chave é o equipamento_id — assim
// dois produtos distintos com o mesmo nome viram cards separados e ficam alinhados
// com o módulo Equipamentos. Documentos sem vínculo (ex.: PDE) caem por nome.
// Documentos de PROCESSO da área (setor PDE): POPs e ITs do próprio P&D, que não
// pertencem a equipamento nenhum. Ficam fora do grid — antes viravam um card
// fantasma escrito "nenhum documento aplicável", que não abria nada de útil.
const _SETORES_EQUIP = ['PRE','Manuais'];
function _docsProcesso(){ return allDocs.filter(d => d.setor && !_SETORES_EQUIP.includes(d.setor)); }

function groupByEquip(){
  const groups = {};
  allDocs.filter(d => _SETORES_EQUIP.includes(d.setor)).forEach(d => {
    const key = d.equipamento_id ? ('id:'+d.equipamento_id) : ('nome:'+(d.equipamento || '—').trim());
    if(!groups[key]){
      const eq = d.equipamento_id ? (allEquipById[d.equipamento_id]||null) : (allEquip[(d.equipamento||'').trim()]||null);
      groups[key] = { key, id:d.equipamento_id||null,
                      equipamento:(eq&&eq.nome)||(d.equipamento||'—').trim(),
                      sku:'', fabricante:'', pre:null, manuais:[],
                      byTipo:{}, docs:[], equip:eq };
    }
    const g = groups[key];
    g.docs.push(d);
    if(d.tipo_doc && !g.byTipo[d.tipo_doc]) g.byTipo[d.tipo_doc] = d;
    if(d.sku && !g.sku) g.sku = d.sku;
    if(d.fabricante && !g.fabricante) g.fabricante = d.fabricante;
    // IT é o documento PRE primário (usado nos KPIs de PRE)
    if(d.setor === 'PRE'){ if(!g.pre || d.tipo_doc==='IT') g.pre = d; }
    else if(d.setor === 'Manuais'){ g.manuais.push(d); }
  });
  // Identidade vem da entidade Equipamento (fonte única) — sobrepõe valores que
  // possam estar defasados nas colunas dos documentos (nome/SKU/fabricante).
  Object.values(groups).forEach(g=>{
    if(g.equip){
      g.sku = g.equip.sku || g.sku;
      g.fabricante = g.equip.fabricante || g.fabricante;
      g.equipamento = g.equip.nome || g.equipamento;
    }
  });
  return Object.values(groups).sort((a,b)=>a.equipamento.localeCompare(b.equipamento));
}

// Documentos de equipamento (PRE + Manuais) do grupo. `_equipDocs` devolve só os
// APLICÁVEIS: documentos em N/A ("não se aplica a este equipamento") estão fora da
// completude — não pintam o card, não entram nos chips, não contam nos KPIs.
function _equipDocs(g){ return g.docs.filter(d=>(d.setor==='PRE'||d.setor==='Manuais') && d.aplicavel!==false); }
function _equipDocsNA(g){ return g.docs.filter(d=>d.aplicavel===false); }
function _docFinalizado(d){
  return (d.setor==='PRE' && d.status==='Homologado') || (d.setor==='Manuais' && d.status==='Concluído');
}
function equipManuaisOk(g){ return g.manuais.filter(d=>d.aplicavel!==false && d.status==='Concluído').length; }
function equipManuaisAplicaveis(g){ return g.manuais.filter(d=>d.aplicavel!==false).length; }

// Cor do card = PIOR status entre os documentos APLICÁVEIS do equipamento.
// Equipamento sem nenhum aplicável (tudo N/A) fica neutro — como o idp() que
// devolve null quando todos os itens são N/A.
function equipStatusColor(g){
  const docs = _equipDocs(g);
  if(!docs.length) return 'neutro';
  if(docs.some(d=>d.status==='Elaborar')) return 'red';   // algum não iniciado
  if(docs.every(_docFinalizado)) return 'green';          // tudo finalizado
  return 'amber';
}

// Completude do equipamento: finalizados / aplicáveis (+ quantos estão em N/A)
function equipCompletude(g){
  const docs = _equipDocs(g);
  return { ok: docs.filter(_docFinalizado).length, total: docs.length, na: _equipDocsNA(g).length };
}

function equipAtrasados(g){ return _equipDocs(g).filter(d=>d.atrasado).length; }

function equipMatchesChip(g, chip){
  const docs = _equipDocs(g);
  const color = equipStatusColor(g);
  const ok = equipManuaisOk(g), cnt = equipManuaisAplicaveis(g);
  switch(chip){
    case 'todos': return true;
    case 'pendente': return color==='red';
    case 'progresso': return color==='amber';
    case 'finalizado': return color==='green';
    case 'pre-pendente': return docs.some(d=>d.setor==='PRE' && d.status==='Elaborar');
    case 'manuais-incompletos': return cnt>0 && ok<cnt;
    case 'atrasados': return docs.some(d=>d.atrasado);
    default: return true;
  }
}

// Recorte por TIPO de documento: responde "quais equipamentos ainda não têm o
// Manual de Serviço?" — a pergunta que os chips de status agregado não alcançam.
// '' = sem recorte. O modo diz o que procurar dentro do tipo escolhido.
let _tipoFiltro = '', _tipoModo = 'pendente';
function setTipoFiltro(v){ _tipoFiltro = v||''; renderGrid(); }
function setTipoModo(v){ _tipoModo = v||'pendente'; renderGrid(); }

function equipMatchesTipo(g){
  if(!_tipoFiltro) return true;
  const d = g.byTipo[_tipoFiltro];
  switch(_tipoModo){
    case 'na':          return !!d && d.aplicavel===false;
    case 'finalizado':  return !!d && d.aplicavel!==false && _docFinalizado(d);
    case 'ausente':     return !d || d.aplicavel===false;
    default:            return !!d && d.aplicavel!==false && !_docFinalizado(d);  // pendente
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
    {id:'atrasados', label:'Com atraso'},
  ];
  document.getElementById('equip-chips').innerHTML = chips.map(c => {
    const n = groups.filter(g => equipMatchesChip(g, c.id)).length;
    const active = _equipChip === c.id ? ' active' : '';
    return `<button type="button" class="filter-chip${active}" data-chip="${c.id}">${esc(c.label)}<span class="chip-count">${n}</span></button>`;
  }).join('');

  const sel = document.getElementById('tipo-filtro');
  if(sel && !sel.dataset.ready){
    sel.innerHTML = '<option value="">Qualquer tipo de documento</option>' +
      _TODOS_TIPOS.map(([t,l])=>`<option value="${t}">${esc(l)}</option>`).join('');
    sel.dataset.ready = '1';
  }
  if(sel) sel.value = _tipoFiltro;
  const modo = document.getElementById('tipo-modo');
  if(modo){ modo.style.display = _tipoFiltro ? '' : 'none'; modo.value = _tipoModo; }
}

function renderDocs(){ renderGrid(); renderProcessos(); }

function renderGrid(){
  const groups = groupByEquip();
  renderChips(groups);

  const q = (document.getElementById('docs-search').value || '').trim().toLowerCase();
  let filtered = groups.filter(g => equipMatchesChip(g, _equipChip) && equipMatchesTipo(g));
  if(q){
    filtered = filtered.filter(g =>
      [g.equipamento, g.sku, g.fabricante,
       g.equip&&g.equip.nome_original, g.equip&&g.equip.anvisa, g.equip&&g.equip.familia]
        .filter(Boolean).join(' ').toLowerCase().includes(q)
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
    const c = equipCompletude(g);
    const atr = equipAtrasados(g);
    const resumo = c.total
      ? `${c.ok}/${c.total} concluídos${c.na?` · ${c.na} N/A`:''}`
      : 'nenhum documento aplicável';
    const flag = atr ? `<span class="equip-card-late" title="${atr} documento(s) com prazo vencido">⏰ ${atr}</span>` : '';
    const key = esc(g.key).replace(/'/g,"\\'");
    // Card é um botão de verdade: <div onclick> não recebia foco nem Enter/Espaço.
    return `<div class="equip-card st-${color}" data-equip="${esc(g.key)}" role="button" tabindex="0"
      aria-label="${esc(g.equipamento)} — ${esc(resumo)}"
      onclick="openEquipModal('${key}')"
      onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openEquipModal('${key}')}">
      <div class="equip-card-name">${esc(g.equipamento)}${flag}</div>
      <div class="equip-card-sku">${g.sku?esc(g.sku):'<span class="muted">sem SKU</span>'}</div>
      <div class="equip-card-compl">${esc(resumo)}</div>
    </div>`;
  }).join('');
}

// ═══ DOCUMENTOS DE PROCESSO (POPs/ITs da área) ═══
// Não têm equipamento nem os 12 tipos canônicos: uma tabela enxuta com troca de
// status inline resolve. Antes eram invisíveis na prática (card fantasma) e
// ineditáveis (STATUS_MAP não tinha o setor).
function renderProcessos(){
  const wrap = document.getElementById('proc-card');
  if(!wrap) return;
  const docs = _docsProcesso();
  if(!docs.length){ wrap.style.display='none'; return; }
  wrap.style.display='';
  const podeEditar = currentUser.role!=='leitura';
  const fluxo = (_enums.status_map && _enums.status_map['PDE']) || _MAN_STATUS;
  document.getElementById('proc-badge').textContent = docs.length + ' documento(s)';
  document.getElementById('proc-tbody').innerHTML = docs.map(d=>{
    const opts = fluxo.map(s=>`<option value="${esc(s)}" ${s===d.status?'selected':''}>${esc(s)}</option>`).join('');
    const sel = podeEditar
      ? `<select class="filter-sel proc-status" data-id="${d.id}" data-ver="${d.version}" onchange="salvarStatusProcesso(this)">${opts}</select>`
      : pillSt(d.status);
    return `<tr>
      <td class="mono">${esc(d.codigo_doc||'—')}</td>
      <td class="bold">${esc(d.documento||'—')}</td>
      <td>${sel}</td>
      <td>${pillGlobal(d.status_global)}</td>
      <td style="font-size:11px;color:var(--t3)">${esc(d.updated_em||'')}</td>
    </tr>`;
  }).join('');
}

async function salvarStatusProcesso(el){
  const id = el.dataset.id, novo = el.value, version = Number(el.dataset.ver);
  el.disabled = true;
  try{
    const res = await apiFetch(`/documento/${id}/status`, {method:'PUT', body:JSON.stringify({status:novo, version})});
    if(res && res.ok){
      const doc = (await res.json()).documento;
      const i = allDocs.findIndex(d=>d.id===doc.id);
      if(i>=0) allDocs[i] = doc;
      showToast('Status atualizado','success');
      renderProcessos();
    } else {
      const e = res ? await res.json().catch(()=>({})) : {};
      showToast(e.erro||'Erro ao salvar','error');
      renderProcessos();          // devolve o select ao valor real
    }
  }catch(e){ showToast('Erro de rede','error'); renderProcessos(); }
  finally{ el.disabled = false; }
}

// ═══ MODAL DE EQUIPAMENTO ═══
let _equipCtx = null; // { equipamento, equip, byTipo:{tipo:doc}, docs:[], sku, fabricante, g }

// Wrapper mantido para o modal de usuário (e quaisquer outros modais simples)
function openModal(id){ openBaseModal(id); }

const _PRE_STATUS = ['Elaborar','Treinamento Piloto','Enviado para Homologação','Homologado'];
const _MAN_STATUS = ['Elaborar','Em andamento','Concluído'];
const _PRE_TIPOS = [
  ['IT','Instrução de Trabalho'],
  ['Checklist_Conferencia','Checklist de Conferência'],
  ['Checklist_BurnIn','Checklist de Burn-In'],
  ['Checklist_Limpeza_Embalagem','Checklist de Limpeza e Embalagem'],
  ['Checklist_Produto','Checklist de Produto'],
];
const _MAN_TIPOS = [
  ['Manual_Usuario','Manual do Usuário PT'],
  ['Manual_ES','Manual do Usuário ES'],
  ['Manual_Servico','Manual de Serviço'],
  ['Spare_Parts','Spare Parts'],
  ['Dossie','Dossiê'],
  ['Guia_Instalacao','Guia de Instalação'],
  ['QIQOQD','QI/QO/QD'],
];
const _TODOS_TIPOS = [..._PRE_TIPOS, ..._MAN_TIPOS];
// Opcionais: os 12 documentos já existem no banco, mas estes nascem em N/A
// (aplicavel=false). A aba só aparece quando o tipo é ligado na aba Escopo.
const _TIPOS_OPCIONAIS = ['Spare_Parts','Dossie','QIQOQD'];
// Os 4 checklists dividem UMA aba ("Checklists") com seletor interno,
// como os manuais PT/ES. Rótulos curtos para o seletor.
const _CHK_TIPOS = [
  ['Checklist_Conferencia','Conferência'],
  ['Checklist_BurnIn','Burn-In'],
  ['Checklist_Limpeza_Embalagem','Limpeza e Embalagem'],
  ['Checklist_Produto','Produto'],
];
function _isChkTipo(t){ return _CHK_TIPOS.some(x=>x[0]===t); }
function _isPreTipo(t){ return _PRE_TIPOS.some(x=>x[0]===t); }
function _tipoLabel(t){ const x=_TODOS_TIPOS.find(y=>y[0]===t); return x?x[1]:t; }
function _statusDotColor(d){
  return _docFinalizado(d) ? 'var(--green)' : (d.status==='Elaborar' ? 'var(--red)' : 'var(--amber)');
}

function _dateToInput(br){ // "dd/mm/yyyy" -> "yyyy-mm-dd"
  if(!br) return '';
  const p = br.split('/');
  return p.length===3 ? `${p[2]}-${p[1]}-${p[0]}` : '';
}

function switchEquipTab(tab){
  const btns = Array.from(document.querySelectorAll('#equip-tabs .equip-modal-tab'));
  // A aba pedida pode não existir: o tipo pode estar em N/A (fora do escopo do
  // equipamento) — vale para a aba padrão do openEquipModal e para o deep-link
  // /?doc=<id>. Cai na primeira aba visível e, se todas estiverem em N/A, no Escopo.
  if(btns.length && !btns.some(b=>b.dataset.tab===tab)){
    const primeira = btns.find(b=>b.dataset.tab!=='__escopo');
    tab = primeira ? primeira.dataset.tab : '__escopo';
  }
  btns.forEach(b=>b.classList.toggle('active', b.dataset.tab===tab));
  document.querySelectorAll('#equip-panels .equip-tab-panel').forEach(p=>p.classList.toggle('active', p.dataset.panel===tab));
  refreshHistSections();   // trilha é carregada sob demanda, só da aba visível
}

function openEquipModal(key, opts){
  // `key` é a chave do grupo ('id:<n>' ou 'nome:<nome>'). Retrocompat: se vier um
  // nome puro (chamadas antigas), tenta casar por nome.
  // opts.manterAberto → re-hidrata o modal já aberto (após salvar) sem reabri-lo,
  // preservando a aba ativa (opts.aba). O card fecha só quando o usuário pedir.
  opts = opts || {};
  const groups = groupByEquip();
  const g = groups.find(x=>x.key===key) || groups.find(x=>x.equipamento===key) || null;
  const docs = g ? g.docs.slice() : [];
  const byTipo = {};
  docs.forEach(d=>{ if(d.tipo_doc && !byTipo[d.tipo_doc]) byTipo[d.tipo_doc]=d; });
  const equip = (g&&g.equip) || null;
  const sku = (g&&g.sku) || (equip&&equip.sku) || '';
  const fabricante = (g&&g.fabricante) || (equip&&equip.fabricante) || '';
  const equip_id = (g&&g.id) || (equip&&equip.id) || null;
  _equipCtx = { equipamento: (g&&g.equipamento)||'', equip, equip_id, byTipo, docs, sku, fabricante, g,
                // pastas (grupos) do equipamento: vêm no próprio to_dict dele,
                // então o seletor do modal não custa uma ida extra ao servidor
                pastas: (equip && equip.pastas) || [],
                cartoesPorDoc: undefined };   // undefined=carregando, null=indisponível (403/erro)
  _escopoPendente = null;   // nenhum N/A a meio caminho no modal recém-aberto

  const delBtn = document.getElementById('btn-del-equip');
  if(delBtn) delBtn.style.display = (currentUser.role==='admin'||currentUser.role==='gestor') ? 'inline-flex' : 'none';

  renderEquipHeader();
  renderEquipModal();
  // abre na aba "Instrução de Trabalho"; se a IT estiver em N/A, o switchEquipTab
  // cai na primeira aba visível (ou no Escopo, se tudo estiver em N/A). Ao re-hidratar
  // após salvar, preserva a aba que o usuário estava vendo.
  switchEquipTab(opts.aba || _TODOS_TIPOS[0][0]);
  if(!opts.manterAberto) openBaseModal('equip');
  _loadCartoesVinculados();   // a trilha vem do switchEquipTab (só a aba ativa)
  carregarResponsaveis();
}

// Datalist do campo "Responsável": o campo era texto livre e estava preenchido
// em 2 de 522 documentos. Uma chamada por sessão.
let _responsaveisCarregados = false;
async function carregarResponsaveis(){
  if(_responsaveisCarregados) return;
  const dl = document.getElementById('lista-responsaveis');
  if(!dl) return;
  try{
    const res = await apiFetch('/documentos/responsaveis');
    if(!res || !res.ok) return;
    const users = await res.json();
    dl.innerHTML = users.map(u=>`<option value="${esc(u.nome)}">${esc(u.email)}</option>`).join('');
    _responsaveisCarregados = true;
  }catch(e){}
}

// Busca (1 chamada, em lote) os cartões de missão vinculados aos documentos do
// equipamento aberto. Role `leitura` recebe 403 → a seção some sem erro.
async function _loadCartoesVinculados(){
  const ctx = _equipCtx;
  const ids = (ctx.docs||[]).map(d=>d.id).filter(Boolean);
  if(!ids.length){ ctx.cartoesPorDoc = {}; refreshMissoesSections(); return; }
  try{
    const res = await apiFetch('/missoes/cartoes-vinculados?tipo=documento&ids='+ids.join(','));
    if(_equipCtx!==ctx) return;          // modal foi reaberto com outro equipamento
    if(!res || !res.ok){ ctx.cartoesPorDoc = null; }
    else{
      const j = await res.json();
      const map = {};
      (j.cartoes||[]).forEach(c=>{ (map[c.ref_id] = map[c.ref_id]||[]).push(c); });
      ctx.cartoesPorDoc = map;
    }
  }catch(e){ ctx.cartoesPorDoc = null; }
  refreshMissoesSections();
}

// Cabeçalho de identidade do equipamento (fonte: entidade Equipamento)
function renderEquipHeader(){
  const e = _equipCtx.equip || {};
  const color = _equipCtx.g ? equipStatusColor(_equipCtx.g) : 'amber';
  const dot = color==='green'?'var(--green)':color==='red'?'var(--red)':color==='neutro'?'var(--t4)':'var(--amber)';
  const reg = (e.anvisa_registro||e.anvisa_validade)
    ? `Registro ${e.anvisa_registro||'—'} · val. ${e.anvisa_validade||'—'}` : '';
  const badges = [
    _equipCtx.sku ? 'SKU '+_equipCtx.sku : '',
    e.anvisa ? 'ANVISA '+e.anvisa : '',
    reg,
    _equipCtx.fabricante ? 'Fabricante '+_equipCtx.fabricante : '',
    e.familia ? 'Família '+e.familia : '',
  ].filter(Boolean).map(t=>`<span class="equip-id-badge">${esc(t)}</span>`).join('');
  // Identidade é somente-leitura aqui: a fonte única é o módulo Equipamentos.
  document.getElementById('equip-header').innerHTML = `
    <div class="equip-id-name"><span class="equip-id-dot" style="background:${dot}" title="Pior status entre os documentos"></span>${esc(_equipCtx.equipamento)}</div>
    ${e.nome_original?`<div class="equip-id-orig"><span>nome original:</span> ${esc(e.nome_original)}</div>`:''}
    <div class="equip-id-badges">
      ${badges}
      ${_equipCtx.equip_id?`<a class="btn btn-ghost btn-sm" href="/equipamentos?equip=${_equipCtx.equip_id}" title="Abrir o card deste equipamento no módulo Equipamentos" style="text-decoration:none">↗ Abrir no módulo Equipamentos</a>`:''}
    </div>
    <div class="equip-id-hint" style="font-size:11px;color:var(--t3);margin-top:6px">A identidade (nome, SKU, fabricante, ANVISA, família…) é editada no módulo <b>Equipamentos</b> e reflete aqui automaticamente.</div>`;
}

// Um tipo está no escopo quando o documento existe e está marcado como aplicável.
function _aplicavel(tipo){ const d=_equipCtx.byTipo[tipo]; return !!d && d.aplicavel!==false; }

// Abas visíveis: só os tipos APLICÁVEIS. IT, Checklists (os 4 numa aba só), Manual
// do Usuário (PT/ES numa aba só), Manual de Serviço, Guia de Instalação e os
// opcionais que estiverem ligados. A aba Escopo (sempre última) liga/desliga tudo.
// Ids das abas agregadas: o primeiro tipo do grupo.
function _visibleTabs(){
  const grupos = [
    ['IT','Instrução de Trabalho', ['IT']],
    ['Checklist_Conferencia','Checklists', _CHK_TIPOS.map(x=>x[0])],
    ['Manual_Usuario','Manual do Usuário', ['Manual_Usuario','Manual_ES']],
    ['Manual_Servico','Manual de Serviço', ['Manual_Servico']],
    ['Guia_Instalacao','Guia de Instalação', ['Guia_Instalacao']],
  ];
  const tabs = grupos
    .filter(([,,tipos]) => tipos.some(_aplicavel))   // aba some se todo o grupo é N/A
    .map(([id,label]) => [id,label]);
  _TIPOS_OPCIONAIS.forEach(t=>{ if(_aplicavel(t)) tabs.push([t,_tipoLabel(t)]); });
  return tabs;
}
function _tabDotColor(tipo){
  // abas agregadas (checklists / manuais PT+ES): pior status do grupo, só aplicáveis
  const grupo = (tipo==='Checklist_Conferencia') ? _CHK_TIPOS.map(x=>x[0])
              : (tipo==='Manual_Usuario') ? ['Manual_Usuario','Manual_ES']
              : [tipo];
  const docs = grupo.filter(_aplicavel).map(t=>_equipCtx.byTipo[t]);
  if(!docs.length) return 'var(--t4)';
  if(docs.some(d=>d.status==='Elaborar')) return 'var(--red)';
  if(docs.every(_docFinalizado)) return 'var(--green)';
  return 'var(--amber)';
}

// Abas + painéis
function renderEquipModal(){
  const tabsEl = document.getElementById('equip-tabs');
  const panelsEl = document.getElementById('equip-panels');
  const tabs = _visibleTabs();
  tabsEl.innerHTML = tabs.map(([tipo,label])=>
    `<button type="button" class="equip-modal-tab" data-tab="${tipo}" onclick="switchEquipTab('${tipo}')"><span class="tab-dot" style="background:${_tabDotColor(tipo)}"></span>${esc(label)}</button>`
  ).join('') +
    `<button type="button" class="equip-modal-tab tab-add" data-tab="__escopo" onclick="switchEquipTab('__escopo')" title="Escolher quais documentos se aplicam a este equipamento">⚙ Escopo</button>`;
  panelsEl.innerHTML = tabs.map(([tipo])=>
    `<div class="equip-tab-panel" data-panel="${tipo}">${
      tipo==='Checklist_Conferencia'?renderChecklistPanel()
      : tipo==='Manual_Usuario'?renderManualPanel()
      : renderTipoPanel(tipo)}</div>`
  ).join('') +
    `<div class="equip-tab-panel" data-panel="__escopo">${renderEscopoPanel()}</div>`;
}

// Painel da aba Checklists: seletor entre os 4 checklists sobre o mesmo painel
let _chkSel = 'Checklist_Conferencia';
function renderChecklistPanel(){
  const disp = _CHK_TIPOS.filter(([t])=>_aplicavel(t));   // os em N/A somem do seletor
  if(!disp.some(([t])=>t===_chkSel)) _chkSel = disp.length ? disp[0][0] : 'Checklist_Conferencia';
  const btn=(t,txt)=>`<button type="button" class="btn btn-sm ${_chkSel===t?'btn-primary':'btn-ghost'}" onclick="setChkSel('${t}')">${txt}</button>`;
  return `<div class="man-lang-toggle">${disp.map(([t,l])=>btn(t,l)).join('')}</div>` + renderTipoPanel(_chkSel);
}
function setChkSel(t){
  _chkSel = t;
  const p = document.querySelector('#equip-panels [data-panel="Checklist_Conferencia"]');
  if(p){ p.innerHTML = renderChecklistPanel(); refreshMissoesSections(); refreshHistSections(); }
}

// Painel da aba de manuais do usuário: toggle PT/ES sobre o mesmo painel
let _manLang = 'PT';
function renderManualPanel(){
  const temPT = _aplicavel('Manual_Usuario'), temES = _aplicavel('Manual_ES');
  if(_manLang==='ES' && !temES) _manLang='PT';       // idioma em N/A → cai no outro
  if(_manLang==='PT' && !temPT) _manLang='ES';
  const tipo = _manLang==='ES' ? 'Manual_ES' : 'Manual_Usuario';
  const btn = (l,txt)=>`<button type="button" class="btn btn-sm ${_manLang===l?'btn-primary':'btn-ghost'}" onclick="setManLang('${l}')">${txt}</button>`;
  const toggles = `${temPT?btn('PT','Português'):''}${temES?btn('ES','Español'):''}`;
  return `<div class="man-lang-toggle">${toggles}</div>` + renderTipoPanel(tipo);
}
function setManLang(l){
  _manLang = l;
  const p = document.querySelector('#equip-panels [data-panel="Manual_Usuario"]');
  if(p){ p.innerHTML = renderManualPanel(); refreshMissoesSections(); refreshHistSections(); }
}

// Painel "Escopo": liga/desliga cada um dos 12 tipos para este equipamento.
// Desligado = N/A: o documento continua existindo (status, código e histórico
// intactos), mas sai da conta de completude. Só admin/gestor edita.
function _podeEditarEscopo(){ return currentUser.role==='admin' || currentUser.role==='gestor'; }

// Tipo aguardando o motivo (o usuário desmarcou e ainda não confirmou). O N/A só
// é gravado no "Confirmar" — desistir aqui devolve o checkbox ao lugar.
let _escopoPendente = null;

function renderEscopoPanel(){
  const c = _equipCtx.g ? equipCompletude(_equipCtx.g) : {ok:0,total:0,na:0};
  const editavel = _podeEditarEscopo();
  const linha = ([tipo,label])=>{
    const d = _equipCtx.byTipo[tipo];
    if(!d) return '';                              // documento ainda não existe (equip. legado)
    const pend = (_escopoPendente === tipo);
    const apl = pend ? false : d.aplicavel!==false;
    const dot = apl ? _statusDotColor(d) : 'var(--t4)';
    const status = apl ? esc(d.status) : 'Não se aplica';
    const rotulo = d.motivo_na_label || d.motivo_na;
    const motivo = (!apl && !pend && rotulo) ? `<div class="escopo-motivo">${esc(rotulo)}</div>` : '';
    // Ao desmarcar, a linha pede o motivo (OBRIGATÓRIO, lista fechada) e só grava
    // no Confirmar. Texto livre só quando o motivo é "Outro" — motivo em lista
    // fechada é analisável; texto livre não é, e antes ninguém preenchia.
    const motivos = _enums.motivos_na || {};
    const opts = ['<option value="">Selecione o motivo…</option>'].concat(
      Object.keys(motivos).map(k=>`<option value="${esc(k)}" ${k===d.motivo_na_codigo?'selected':''}>${esc(motivos[k])}</option>`)
    ).join('');
    const livre = (_enums.motivo_na_livre || 'outro');
    const formMotivo = pend ? `
      <div class="escopo-na-form">
        <select class="form-input" id="escopo-motivo-cod-${tipo}" onchange="_toggleMotivoLivre('${tipo}')">${opts}</select>
        <input class="form-input" id="escopo-motivo-${tipo}" maxlength="300"
               style="display:${d.motivo_na_codigo===livre?'':'none'}"
               placeholder="Descreva o motivo" value="${esc(d.motivo_na||'')}">
        <button type="button" class="btn btn-primary btn-sm" onclick="confirmarNA('${tipo}')">Confirmar N/A</button>
        <button type="button" class="btn btn-ghost btn-sm" onclick="cancelarNA()">Cancelar</button>
      </div>` : '';
    return `<div class="escopo-row${apl?'':' off'}">
      <label class="escopo-toggle">
        <input type="checkbox" ${apl?'checked':''} ${editavel?'':'disabled'}
               onchange="toggleEscopo('${tipo}', this.checked)">
        <span class="escopo-dot" style="background:${dot}"></span>
        <span class="escopo-label">${esc(label)}</span>
      </label>
      <span class="escopo-status">${status}</span>
      ${motivo}
      ${formMotivo}
    </div>`;
  };
  const bloco = (titulo, tipos)=>`
    <div class="doc-sec">
      <div class="doc-sec-title">${titulo}</div>
      ${tipos.map(linha).join('')}
    </div>`;
  const resumo = c.total
    ? `${c.ok} de ${c.total} aplicáveis concluídos${c.na?` · ${c.na} N/A`:''}`
    : 'Nenhum documento aplicável a este equipamento';
  const aviso = editavel ? '' :
    '<p class="muted" style="font-size:12px">Só admin e gestor podem alterar o escopo — mexer nele muda a completude de todo mundo.</p>';
  return `
    <div class="equip-panel-head">
      <span class="equip-panel-title">Escopo de documentos</span>
      <span class="equip-tag">${esc(resumo)}</span>
    </div>
    <p class="muted" style="font-size:12px;margin-bottom:8px">Desmarque o que não se aplica a este equipamento. O documento continua salvo (status, código, arquivos) — só sai da conta de completude.</p>
    ${aviso}
    ${bloco('PRE', _PRE_TIPOS)}
    ${bloco('Manuais', _MAN_TIPOS)}`;
}

// Stepper de etapas: um botão por status do pipeline; clique só grava no
// Salvar (o input hidden et-st-<tipo> mantém o saveTipoDoc intocado).
function renderStepper(tipo, sel){
  const fluxo = _isPreTipo(tipo)?_PRE_STATUS:_MAN_STATUS;
  const idx = fluxo.indexOf(sel);
  return `<div class="doc-stepper" id="et-stepper-${tipo}">`+fluxo.map((s,i)=>{
    const st = i<idx?'done':i===idx?'current':'pending';
    return `<button type="button" class="doc-step ${st}" onclick="selStep('${tipo}',${i})" title="Marcar etapa: ${esc(s)}">
      <span class="doc-step-dot">${i<idx?'✓':i+1}</span><span class="doc-step-label">${esc(s)}</span>
    </button>`;
  }).join('<span class="doc-step-line"></span>')+`</div>`;
}
function selStep(tipo, i){
  const fluxo = _isPreTipo(tipo)?_PRE_STATUS:_MAN_STATUS;
  const hid = document.getElementById('et-st-'+tipo);
  if(hid) hid.value = fluxo[i];
  const wrap = document.getElementById('et-stepper-'+tipo);
  if(wrap){ const tmp=document.createElement('div'); tmp.innerHTML=renderStepper(tipo, fluxo[i]); wrap.replaceWith(tmp.firstElementChild); }
}

// Seção "Missões vinculadas" do painel (populada async pelo fetch batch)
function renderMissoesDoc(tipo){
  const d = _equipCtx.byTipo[tipo];
  const map = _equipCtx.cartoesPorDoc;
  if(!d || map===null) return '';                     // 403/erro → seção some
  if(map===undefined) return '<span style="color:var(--t4);font-size:12px">Carregando…</span>';
  const cartoes = map[d.id]||[];
  const chips = cartoes.length
    ? cartoes.map(c=>{
        const late = c.atrasado ? ' ⏰' : '';
        const tit = c.prazo ? `Prazo ${c.prazo.split('-').reverse().join('/')}` : 'Abrir no board de missões';
        return `<a class="doc-missao-chip ${c.concluido?'done':''} ${c.atrasado?'late':''}" href="/missoes?missao=${c.missao_id}&cartao=${c.id}" title="${esc(tit)}">🎯 ${esc(c.missao_nome)} · ${esc(c.coluna_nome)}${c.concluido?' ✓':late}</a>`;
      }).join('')
    : '<span style="color:var(--t4);font-size:12px">Nenhum cartão de missão vinculado a este documento.</span>';
  // O vínculo só nascia de dentro do board: daqui dava para ver os cartões, mas
  // não para abrir um.
  return chips +
    `<button type="button" class="doc-missao-novo" onclick="abrirNovoCartaoMissao('${tipo}')">＋ criar cartão</button>` +
    `<div class="doc-missao-form" id="dmf-${tipo}" style="display:none"></div>`;
}

// Missões ativas, em cache (só nomes; usado pelo seletor do formulário acima)
let _missoesLista = null;
async function _carregarMissoesLista(){
  if(_missoesLista) return _missoesLista;
  try{
    const res = await apiFetch('/missoes');
    if(!res || !res.ok){ _missoesLista = []; return _missoesLista; }
    _missoesLista = ((await res.json()).missoes)||[];
  }catch(e){ _missoesLista = []; }
  return _missoesLista;
}

async function abrirNovoCartaoMissao(tipo){
  const box = document.getElementById('dmf-'+tipo);
  const d = _equipCtx.byTipo[tipo];
  if(!box || !d) return;
  if(box.style.display !== 'none'){ box.style.display='none'; return; }
  const missoes = await _carregarMissoesLista();
  if(!missoes.length){ showToast('Nenhuma missão ativa — crie uma no módulo Missões','error'); return; }
  const titulo = `${_tipoLabel(tipo)} — ${_equipCtx.equipamento||''}`.trim();
  box.style.display = 'flex';
  box.innerHTML = `
    <input class="form-input" id="dmf-t-${tipo}" maxlength="200" placeholder="Título do cartão" value="${esc(titulo)}">
    <select class="form-input" id="dmf-m-${tipo}">${missoes.map(m=>`<option value="${m.id}">${esc(m.nome)}</option>`).join('')}</select>
    <input class="form-input" type="date" id="dmf-p-${tipo}" value="${esc(d.prazo||'')}" title="Prazo do cartão">
    <button type="button" class="btn btn-primary btn-sm" onclick="criarCartaoMissao('${tipo}')">Criar</button>
    <button type="button" class="btn btn-ghost btn-sm" onclick="document.getElementById('dmf-${tipo}').style.display='none'">Cancelar</button>`;
  const inp = document.getElementById('dmf-t-'+tipo);
  if(inp) inp.focus();
}

async function criarCartaoMissao(tipo){
  const d = _equipCtx.byTipo[tipo];
  if(!d) return;
  const titulo = (document.getElementById('dmf-t-'+tipo).value||'').trim();
  if(!titulo){ showToast('Informe o título do cartão','error'); return; }
  const body = {
    missao_id: parseInt(document.getElementById('dmf-m-'+tipo).value||'0'),
    titulo,
    prazo: document.getElementById('dmf-p-'+tipo).value||'',
    ref_tipo: 'documento', ref_id: d.id,
  };
  try{
    const res = await apiFetch('/missoes/cartao-rapido', {method:'POST', body: JSON.stringify(body)});
    if(!res || !res.ok){
      const b = res ? await res.json().catch(()=>({})) : {};
      throw new Error(b.erro||'não foi possível criar');
    }
    const j = await res.json();
    showToast(`Cartão criado em ${j.missao_nome} · ${j.coluna_nome}`,'success');
    const box = document.getElementById('dmf-'+tipo);
    if(box) box.style.display='none';
    await _loadCartoesVinculados();
  }catch(e){ showToast('Erro ao criar cartão: '+e.message,'error'); }
}
function refreshMissoesSections(){
  document.querySelectorAll('[data-missoes-tipo]').forEach(el=>{
    const tipo = el.dataset.missoesTipo;
    const html = renderMissoesDoc(tipo);
    const sec = el.closest('.doc-sec');
    if(sec) sec.style.display = (html==='' ? 'none' : '');
    el.innerHTML = html;
  });
}

// Painel de um tipo de documento — 4 seções: identificação / progresso /
// arquivos / missões vinculadas
function renderTipoPanel(tipo){
  const label = _tipoLabel(tipo);
  const d = _equipCtx.byTipo[tipo];
  const isPre = _isPreTipo(tipo);
  // Com os 12 tipos criados junto com o equipamento, este ramo só sobra para
  // equipamentos legados ainda não sincronizados — não há mais o que criar aqui.
  if(!d){
    return `<div style="text-align:center;padding:24px;color:var(--t3)">
      <p>Este equipamento ainda não tem o documento "${esc(label)}". Ele será criado na próxima sincronização; use a aba <b>Escopo</b> para definir o que se aplica.</p>
    </div>`;
  }
  const setorTag = `<span class="equip-tag">setor ${isPre?'PRE · 4 etapas':'Manuais · 3 etapas'}</span>`;
  // Prazo (data ALVO). As datas abaixo são as REALIZADAS — sem prazo, nada podia
  // estar atrasado.
  const atrasoTag = d.atrasado
    ? `<span class="equip-tag late">⏰ atrasado ${Math.abs(d.dias_para_prazo)} dia(s)</span>`
    : (d.dias_para_prazo!==null && d.dias_para_prazo!==undefined && d.dias_para_prazo<=7 && d.aplicavel!==false
        ? `<span class="equip-tag warn">vence em ${d.dias_para_prazo} dia(s)</span>` : '');
  const datasPre = isPre ? `
    <div class="g2" style="margin-top:12px">
      <div class="form-group"><label class="form-label">Data Treinamento Piloto</label><input class="form-input" type="date" id="et-treino-${tipo}" value="${_dateToInput(d.data_treinamento)}"></div>
      <div class="form-group"><label class="form-label">Data Envio Homologação</label><input class="form-input" type="date" id="et-homol-${tipo}" value="${_dateToInput(d.data_homologacao)}"></div>
    </div>
    <div class="g2">
      <div class="form-group"><label class="form-label">Obs. Treinamento</label><input class="form-input" id="et-obstr-${tipo}" value="${esc(d.obs_treinamento)}"></div>
      <div class="form-group"><label class="form-label">Obs. Homologação</label><input class="form-input" id="et-obshm-${tipo}" value="${esc(d.obs_homologacao)}"></div>
    </div>` : '';
  return `
    <div class="equip-panel-head"><span class="equip-panel-title">${esc(label)}</span>${setorTag}${atrasoTag}</div>

    <div class="doc-sec">
      <div class="doc-sec-title">Identificação</div>
      <div class="g2">
        <div class="form-group"><label class="form-label">Código do Doc</label><input class="form-input" id="et-cod-${tipo}" value="${esc(d.codigo_doc)}"></div>
        <div class="form-group"><label class="form-label">Responsável</label>
          <input class="form-input" id="et-resp-${tipo}" list="lista-responsaveis" value="${esc(d.responsavel)}" placeholder="Escolha ou digite">
        </div>
      </div>
    </div>

    <div class="doc-sec">
      <div class="doc-sec-title">Progresso</div>
      <input type="hidden" id="et-st-${tipo}" value="${esc(d.status)}">
      ${renderStepper(tipo, d.status)}
      <div class="g2" style="margin-top:12px">
        <div class="form-group"><label class="form-label">Prazo (data alvo)</label><input class="form-input" type="date" id="et-prazo-${tipo}" value="${esc(d.prazo||'')}"></div>
        <div class="form-group"><label class="form-label">Histórico</label>
          <div class="doc-hist" data-hist-tipo="${tipo}" id="et-hist-${tipo}"><span style="color:var(--t4);font-size:12px">Carregando…</span></div>
        </div>
      </div>
      ${datasPre}
    </div>

    <div class="doc-sec">
      <div class="doc-sec-title">Arquivos</div>
      <div id="et-arqplat-${tipo}">${renderArquivoPlataforma(d, tipo)}</div>
    </div>

    <div class="doc-sec">
      <div class="doc-sec-title">Missões vinculadas</div>
      <div class="doc-missoes" data-missoes-tipo="${tipo}">${renderMissoesDoc(tipo)}</div>
    </div>

    <div class="modal-footer" style="margin-top:8px"><button class="btn btn-primary" type="button" onclick="saveTipoDoc('${tipo}')">Salvar alterações</button></div>`;
}

// ── Arquivos hospedados na plataforma ────────────────────────────────────────
// São CÓPIAS de conveniência: o mestre continua no servidor da engenharia e a
// Qualidade mantém o sistema dela. Um documento comporta vários arquivos ao
// mesmo tempo (manual PT e ES, IT e checklist). Adicionar/remover é de
// admin+gestor; ler e baixar é de qualquer um — quem entra no DocTrack já
// acessa as pastas de rede, então travar o download não protegeria nada.
function _podeGerenciarArquivo(){
  return currentUser.role==='admin' || currentUser.role==='gestor';
}

function renderArquivoPlataforma(d, tipo){
  const lista = (d && d.arquivos) || [];
  const pode = _podeGerenciarArquivo();
  const btnAdd = pode
    ? `<button type="button" class="arq-btn arq-btn-add" onclick="enviarArquivoDoc('${tipo}')">
         <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14"/><path d="M5 12h14"/></svg>
         Adicionar arquivo</button>`
    : '';
  if(!lista.length){
    return `<div class="arq-plat-vazio">
      <span>Nenhum arquivo enviado para a plataforma.</span>
      ${btnAdd}
    </div>`;
  }
  const linhas = lista.map(a=>{
    const cor = _ICON_ARQUIVO[a.ext] || 'var(--t3)';
    // Autor e data ficam SEMPRE visíveis: não há sincronização com o mestre,
    // então é isso que impede alguém ler uma cópia velha sem perceber.
    const meta = [_fmtTamanho(a.tamanho), a.enviado_por, a.enviado_em]
                   .filter(Boolean).join(' · ');
    const nomeEsc = (a.nome||'').replace(/'/g,"\\'");
    const acoes = [
      a.pode_visualizar
        ? `<button type="button" class="arq-btn" title="Visualizar na plataforma" onclick="visualizarArquivoDoc(${a.id}, '${nomeEsc}', '${a.ext}')">
             <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>
             Visualizar</button>`
        : '',
      `<button type="button" class="arq-btn" title="Baixar o arquivo" onclick="baixarArquivoDoc(${a.id})">
         <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M4 19h16"/></svg>
         Baixar</button>`,
      pode
        ? `<button type="button" class="arq-btn danger" title="Remover esta cópia da plataforma" onclick="removerArquivoDoc(${a.id}, '${tipo}')">
             <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/></svg>
             Remover</button>`
        : ''
    ].filter(Boolean).join('');
    return `<div class="arquivo-row arq-plat">
      <span class="arquivo-ext" style="background:${cor}">${esc((a.ext||'?').toUpperCase().slice(0,4))}</span>
      <span class="arquivo-info">
        <span class="arquivo-nome">${esc(a.nome)}</span>
        <span class="arquivo-meta">${esc(meta)}${a.observacao?' · '+esc(a.observacao):''}</span>
      </span>
      <span class="arq-plat-acoes">${acoes}</span>
    </div>`;
  }).join('');
  return linhas + (btnAdd ? `<div class="arq-plat-footer">${btnAdd}</div>` : '');
}

// Repinta só a faixa do arquivo — repintar o painel inteiro descartaria o que o
// usuário já digitou nos outros campos e ainda não salvou.
function _repintarArqPlat(tipo, doc){
  const el = document.getElementById('et-arqplat-'+tipo);
  if(el) el.innerHTML = renderArquivoPlataforma(doc, tipo);
}

function enviarArquivoDoc(tipo){
  const d = _equipCtx && _equipCtx.byTipo[tipo];
  if(!d) return;
  const inp = document.createElement('input');
  inp.type = 'file';
  inp.accept = '.pdf,.docx,.doc,.xlsx,.xls,.pptx,.png,.jpg,.jpeg';
  inp.onchange = async ()=>{
    const f = inp.files && inp.files[0];
    if(!f) return;
    const el = document.getElementById('et-arqplat-'+tipo);
    if(el) el.innerHTML = '<div class="loading-state"><div class="spinner"></div>Enviando…</div>';
    const fd = new FormData();
    fd.append('arquivo', f);
    try{
      // Sem Content-Type manual: o navegador precisa definir o boundary do
      // multipart, e authHeader() forçaria application/json.
      const res = await apiFetch(`/documentos/${d.id}/arquivos`, {
        method:'POST', body: fd,
        headers:{'Authorization':'Bearer '+getToken()}
      });
      if(!res){ _repintarArqPlat(tipo, d); return; }
      const data = await res.json().catch(()=>({}));
      if(!res.ok){
        showToast(data.erro||'Erro ao enviar o arquivo','error');
        _repintarArqPlat(tipo, d);
        return;
      }
      _aplicarDocLocal(data.documento);
      _equipCtx.byTipo[tipo] = data.documento;
      _repintarArqPlat(tipo, data.documento);
      renderDashboard(); renderDocs();
      showToast('Arquivo enviado','success');
    }catch(e){
      showToast('Erro de rede ao enviar','error');
      _repintarArqPlat(tipo, d);
    }
  };
  inp.click();
}

// Visualiza dentro da plataforma: PDF/imagem em iframe (visualizador nativo do
// navegador) e .docx renderizado client-side. O token vai na querystring porque
// JWT_TOKEN_LOCATION inclui "query_string" — o iframe não manda cabeçalho.
async function visualizarArquivoDoc(arqId, nome, ext){
  const body = document.getElementById('docview-body');
  const rota = `/documentos/arquivos/${arqId}/conteudo`;
  document.getElementById('docview-title').textContent = nome || 'Documento';
  document.getElementById('docview-download').onclick = ()=>baixarArquivoDoc(arqId);
  openModal('docview');
  ext = (ext||'').toLowerCase();

  if(ext !== 'docx'){
    body.innerHTML = `<iframe class="docview-frame" title="${esc(nome||'Documento')}"
      src="${API}${rota}?token=${encodeURIComponent(getToken())}"></iframe>`;
    return;
  }
  if(typeof docx === 'undefined' || !docx.renderAsync){
    closeModal('docview');
    showToast('Visualizador indisponível — baixando o arquivo','error');
    baixarArquivoDoc(arqId);
    return;
  }
  body.innerHTML = '<div class="loading-state"><div class="spinner"></div>Renderizando documento...</div>';
  try{
    const res = await apiFetch(rota);
    if(!res || !res.ok){
      body.innerHTML = '<div class="docview-erro">Não foi possível carregar o documento.</div>';
      return;
    }
    const blob = await res.blob();
    body.innerHTML = '';
    await docx.renderAsync(blob, body, null, {
      className:'docx', inWrapper:true, useBase64URL:true,
      breakPages:true, ignoreLastRenderedPageBreak:true, experimental:true
    });
    _ajustarDocxNaPagina(body);
  }catch(e){
    body.innerHTML = '<div class="docview-erro">Não foi possível renderizar este documento.<br><span style="color:var(--t3);font-size:12px">Use o botão “Baixar” acima para abrir no Word.</span></div>';
  }
}

function baixarArquivoDoc(arqId){
  const a = document.createElement('a');
  a.href = API + `/documentos/arquivos/${arqId}/conteudo?download=1&token=`
           + encodeURIComponent(getToken());
  a.style.display = 'none';
  document.body.appendChild(a); a.click(); a.remove();
}

async function removerArquivoDoc(arqId, tipo){
  const ok = await confirmModal('Remover arquivo',
    'Remover esta cópia da plataforma? O arquivo no servidor da engenharia não é afetado.');
  if(!ok) return;
  try{
    const res = await apiFetch(`/documentos/arquivos/${arqId}`, {method:'DELETE'});
    if(!res){ return; }
    const data = await res.json().catch(()=>({}));
    if(!res.ok){ showToast(data.erro||'Erro ao remover','error'); return; }
    if(data.documento){
      _aplicarDocLocal(data.documento);
      _equipCtx.byTipo[tipo] = data.documento;
      _repintarArqPlat(tipo, data.documento);
      renderDashboard(); renderDocs();
    }
    showToast('Arquivo removido','success');
  }catch(e){ showToast('Erro de rede','error'); }
}

// Histórico do documento aberto (aging + últimas transições). Carregado sob
// demanda: o payload do dashboard não carrega trilha.
async function carregarHistorico(tipo){
  const el = document.getElementById('et-hist-'+tipo);
  const d = _equipCtx && _equipCtx.byTipo[tipo];
  if(!el || !d) return;
  try{
    const res = await apiFetch(`/documentos/${d.id}/historico`);
    if(!res || !res.ok){ el.innerHTML='<span style="color:var(--t4);font-size:12px">Indisponível</span>'; return; }
    const j = await res.json();
    const dias = j.dias_no_status;
    const aging = (dias===null||dias===undefined) ? ''
      : `<div class="doc-hist-aging">Neste status há <b>${dias}</b> dia(s) · desde ${esc(j.desde)}</div>`;
    const linhas = (j.historico||[]).slice(0,5).map(h=>{
      const txt = h.evento==='escopo'
        ? (h.aplicavel ? 'voltou ao escopo' : 'marcado N/A'+(h.motivo?` (${esc(h.motivo)})`:''))
        : (h.status_antigo ? `${esc(h.status_antigo)} → ${esc(h.status_novo)}` : `criado em ${esc(h.status_novo)}`);
      return `<div class="doc-hist-row"><span class="doc-hist-when">${esc(h.em)}</span> ${txt} <span class="doc-hist-who">${esc(h.por||'')}</span></div>`;
    }).join('');
    el.innerHTML = aging + (linhas || '<span style="color:var(--t4);font-size:12px">Sem movimentações.</span>');
  }catch(e){ el.innerHTML='<span style="color:var(--t4);font-size:12px">Indisponível</span>'; }
}

// Carrega o histórico só do painel ATIVO: os 12 painéis são renderizados juntos,
// mas buscar a trilha de todos abriria 7 requisições por abertura do modal.
function refreshHistSections(){
  const ativo = document.querySelector('#equip-panels .equip-tab-panel.active');
  (ativo ? ativo.querySelectorAll('[data-hist-tipo]') : []).forEach(
    el => carregarHistorico(el.dataset.histTipo));
}

async function deleteEquip(){
  if(!_equipCtx) return;
  if(!(currentUser.role==='admin'||currentUser.role==='gestor')){ showToast('Sem permissão','error'); return; }
  const nome = _equipCtx.equipamento;
  const eid = _equipCtx.equip_id;
  const docs = _equipCtx.docs || [];
  if(!eid && !docs.length){ showToast('Nada para excluir','info'); return; }
  const ok = await confirmModal('Excluir equipamento', `Excluir "${nome}" e todos os seus documentos? Remove o equipamento dos dois módulos (Equipamentos e Documentos). Pode ser revertido no banco (soft delete).`);
  if(!ok) return;
  try{
    if(eid){
      // Exclui a entidade Equipamento — o backend remove os documentos em cascata
      // e evita que o backfill recrie os 9 tipos no próximo boot.
      const res = await apiFetch(`/equipamentos/${eid}`, {method:'DELETE'});
      if(!res || !res.ok){ const e = res ? await res.json().catch(()=>({})) : {}; showToast(e.erro||'Erro ao excluir','error'); return; }
    } else {
      for(const d of docs){
        const res = await apiFetch(`/documentos/${d.id}`, {method:'DELETE'});
        if(!res || !res.ok){ const e = res ? await res.json().catch(()=>({})) : {}; showToast(e.erro||'Erro ao excluir','error'); return; }
      }
    }
    showToast('Equipamento excluído','success'); closeModal('equip'); await refreshAll();
  }catch(e){ showToast('Erro de rede','error'); }
}

async function _patchDoc(id, payload){
  const res = await apiFetch(`/documentos/${id}`, {method:'PATCH', body:JSON.stringify(payload)});
  return res;
}

// Salva um documento de um tipo específico
async function saveTipoDoc(tipo){
  const d = _equipCtx.byTipo[tipo];
  if(!d) return;
  const val = id => { const el=document.getElementById(id); return el?el.value:undefined; };
  // Sem `armazenamento` e sem `pasta_id`: a pasta de rede saiu desta aba e o
  // endereço do documento é resolvido pelo backend (exceção > pasta do grupo >
  // equipamento). Ler campos que o painel não renderiza mais só devolvia
  // `undefined` — chave que o JSON.stringify descarta —, mas era código morto
  // apontando para uma seção inexistente.
  const payload = {
    codigo_doc: val('et-cod-'+tipo),
    responsavel: val('et-resp-'+tipo),
    status: val('et-st-'+tipo),
    prazo: val('et-prazo-'+tipo),
  };
  if(_isPreTipo(tipo)){
    payload.data_treinamento = val('et-treino-'+tipo);
    payload.data_homologacao = val('et-homol-'+tipo);
    payload.obs_treinamento  = val('et-obstr-'+tipo);
    payload.obs_homologacao  = val('et-obshm-'+tipo);
  }
  try{
    const res = await _patchDoc(d.id, payload);
    if(res && res.ok){
      showToast(`${_tipoLabel(tipo)} salvo`,'success');
      // O PATCH já devolve o documento atualizado: aplica no cache local em vez
      // de recarregar /api/data + /api/equipamentos inteiros a cada campo salvo.
      const doc = (await res.json()).documento;
      _aplicarDocLocal(doc);
      const key = _equipCtx.g && _equipCtx.g.key;
      const abaEl = document.querySelector('#equip-tabs .equip-modal-tab.active');
      const aba = abaEl ? abaEl.dataset.tab : null;
      renderDashboard(); renderDocs();
      if(key) openEquipModal(key, { aba, manterAberto:true });
    }
    else { const e = await res.json().catch(()=>({})); showToast(e.erro||'Erro ao salvar','error'); }
  }catch(e){ showToast('Erro de rede','error'); }
}

// Substitui um documento no cache local e propaga o caminho base do equipamento
// para os irmãos (o backend pode tê-lo promovido neste PATCH).
function _aplicarDocLocal(doc){
  if(!doc) return;
  const i = allDocs.findIndex(x=>x.id===doc.id);
  if(i>=0) allDocs[i] = doc; else allDocs.push(doc);
  if(doc.equipamento_id){
    allDocs.forEach(x=>{
      if(x.equipamento_id===doc.equipamento_id && x.armazenamento_base!==doc.armazenamento_base){
        x.armazenamento_base = doc.armazenamento_base;
        if(!(x.armazenamento||'').trim()) x.armazenamento_efetivo = doc.armazenamento_base;
      }
    });
    const eq = allEquipById[doc.equipamento_id];
    if(eq) eq.armazenamento_base = doc.armazenamento_base;
  }
}

// Liga/desliga um tipo no escopo do equipamento aberto.
//   marcar   → grava direto (voltar ao escopo não pede justificativa)
//   desmarcar→ abre o campo de motivo na linha; só grava no "Confirmar N/A"
function toggleEscopo(tipo, aplicavel){
  if(!_equipCtx.byTipo[tipo]) return;
  if(!aplicavel){ _escopoPendente = tipo; _repintarEscopo(); return; }
  _escopoPendente = null;
  _gravarEscopo(tipo, true, '');
}

function cancelarNA(){ _escopoPendente = null; _repintarEscopo(); }

// O campo de texto só aparece para o motivo "Outro"
function _toggleMotivoLivre(tipo){
  const cod = document.getElementById('escopo-motivo-cod-'+tipo);
  const txt = document.getElementById('escopo-motivo-'+tipo);
  if(cod && txt) txt.style.display = (cod.value === (_enums.motivo_na_livre||'outro')) ? '' : 'none';
}

function confirmarNA(tipo){
  const codEl = document.getElementById('escopo-motivo-cod-'+tipo);
  const el = document.getElementById('escopo-motivo-'+tipo);
  const codigo = codEl ? codEl.value : '';
  const motivo = el ? el.value.trim() : '';
  // Validação no cliente só para dar retorno imediato — quem decide é a API.
  if(!codigo){ showToast('Escolha o motivo do N/A','error'); return; }
  if(codigo === (_enums.motivo_na_livre||'outro') && !motivo){
    showToast('Descreva o motivo','error'); return;
  }
  _escopoPendente = null;
  _gravarEscopo(tipo, false, motivo, codigo);
}

// Repinta só o painel do escopo (sem reabrir o modal, para não perder o foco)
function _repintarEscopo(){
  const p = document.querySelector('#equip-panels [data-panel="__escopo"]');
  if(p) p.innerHTML = renderEscopoPanel();
}

async function _gravarEscopo(tipo, aplicavel, motivo, codigo){
  const d = _equipCtx.byTipo[tipo];
  const reopenKey = (_equipCtx.g && _equipCtx.g.key) || _equipCtx.equipamento;
  try{
    const res = await apiFetch(`/documentos/${d.id}/aplicabilidade`,
      {method:'PUT', body:JSON.stringify({aplicavel, motivo_na: motivo, motivo_na_codigo: codigo||''})});
    if(res && res.ok){
      showToast(`${_tipoLabel(tipo)} ${aplicavel?'incluído no escopo':'marcado como N/A'}`,'success');
      _aplicarDocLocal((await res.json()).documento);
      renderDashboard(); renderDocs();
      openEquipModal(reopenKey, {manterAberto:true});   // recarrega o contexto
      switchEquipTab('__escopo');
    } else {
      const e = res ? await res.json().catch(()=>({})) : {};
      showToast(e.erro||'Erro ao atualizar o escopo','error');
      _repintarEscopo();             // desfaz o checkbox otimista
    }
  }catch(e){
    showToast('Erro de rede','error');
    _repintarEscopo();
  }
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
    const res = await apiFetch('/documentos', {method:'POST', body:JSON.stringify({setor:'PRE', equipamento:nome, sku})});
    if(res && res.ok){ showToast('Equipamento criado','success'); closeModal('new-equip'); await refreshAll(); }
    else { showToast('Erro ao criar equipamento','error'); }
  }catch(e){ showToast('Erro de rede','error'); }
}

// ═══ AUDIT & USERS ═══
// Movidos para o módulo de Configurações (static/config.js) — acessível pelo hub (gestor+).

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
// Clique no fundo do overlay NÃO fecha o card: a ficha do equipamento e os
// formulários têm edições em andamento e um clique fora acidental descartava tudo.
// O fechamento é sempre explícito — botão "Fechar"/"Cancelar" (ou ESC).

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

// ═══ BOOTSTRAP: hub de módulos ═══
// Com token: quem não veio do hub (dt_module!=='docs') é levado ao hub;
// quem veio do hub entra direto no app. Sem token: tela de login normal.
(async function bootstrapHub(){
  // Sem token nem refresh: mostra a tela de login (com aviso se a sessão expirou).
  if(!getToken()&&!(window.DT_AUTH&&window.DT_AUTH.getRefresh())){
    if(window.DT_AUTH&&window.DT_AUTH.consumeExpiredFlag()){
      showToast('Sua sessão expirou. Faça login novamente.','info');
    }
    return;
  }
  // deep-link /?doc=<id> (chip do board de missões) entra direto no módulo
  if(new URLSearchParams(location.search).get('doc')){
    sessionStorage.setItem('dt_module','docs');
    sessionStorage.setItem('dt_area','pde');
  }
  if(sessionStorage.getItem('dt_module')!=='docs'){window.location.href='/hub';return}
  // Access token vencido? Renova em silêncio antes de montar o app; se o refresh
  // também venceu, cai numa tela de login limpa com aviso (sem app pela metade).
  if(window.DT_AUTH&&window.DT_AUTH.isExpired()){
    const ok=await window.DT_AUTH.refresh();
    if(!ok){ window.DT_AUTH.gotoLogin(true); return; }
  }
  try{
    const u=JSON.parse(localStorage.getItem('doctrack_user')||'{}');
    if(u&&u.nome)currentUser={name:u.nome,email:u.email,role:u.role,initials:u.nome.split(' ').map(w=>w[0]).join('').substring(0,2).toUpperCase()};
  }catch(e){}
  document.getElementById('login-screen').style.display='none';
  document.getElementById('app').style.display='block';
  initApp();
})();
