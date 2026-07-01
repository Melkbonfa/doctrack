const API='/api';
let allDocs=[],allEquip={},chartInstances={},currentUser={name:'Admin',email:'admin@pde.com',role:'admin',initials:'A'};
let selectedRole='admin',_allUsers=[],_enums={},_lastKpis=null;
let _filterTimer=null;
let _dashEquip='';   // equipamento selecionado no dashboard ('' = todos)

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
    if(res.status===403&&data.precisa_definir_senha){
      btn.textContent='Entrar no DocTrack';
      showToast('Conta sem senha. Defina sua senha com o código de ativação.','info');
      showPrimeiroAcesso(email);return;
    }
    if(!res.ok){btn.textContent='Entrar no DocTrack';showToast(data.erro||data.error||'Falha no login','error');return}
    setToken(data.access_token);localStorage.setItem('doctrack_user',JSON.stringify(data.usuario));
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
  if(senha.length<6){showToast('A senha deve ter pelo menos 6 caracteres','error');return}
  if(senha!==senha2){showToast('As senhas não conferem','error');return}
  const original=btn.textContent;
  btn.innerHTML='<span class="spinner" style="border-color:rgba(255,255,255,.3);border-top-color:#fff"></span>';
  try{
    const res=await fetch(API+'/auth/primeiro-acesso',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,codigo,senha})});
    const data=await res.json().catch(()=>({}));
    if(!res.ok){btn.textContent=original;showToast(data.erro||'Não foi possível definir a senha','error');return}
    setToken(data.access_token);localStorage.setItem('doctrack_user',JSON.stringify(data.usuario));
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
  makeSortable();
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
    manuais:(document.getElementById('exp-manuais')||{}).value||'',
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
    if(cfg.manuais){
      const cnt=g.manuais.length, ok=equipManuaisOk(g);
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

  let fin=0, prog=0, pend=0, preHom=0, man100=0;
  groups.forEach(g=>{
    const st=_groupGlobalStatus(g);
    if(st==='Finalizado')fin++; else if(st==='Em progresso')prog++; else pend++;
    if(g.pre && g.pre.status==='Homologado') preHom++;
    if(g.manuais.length>0 && equipManuaisOk(g)===g.manuais.length) man100++;
  });
  const preStatuses=['Elaborar','Treinamento Piloto','Enviado para Homologação','Homologado'];
  const preCounts=preStatuses.map(s=>groups.filter(g=>g.pre&&g.pre.status===s).length);
  let manOk=0, manTot=0; groups.forEach(g=>{ manOk+=equipManuaisOk(g); manTot+=g.manuais.length; });
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
    const ok=equipManuaisOk(g);
    const glob=_groupGlobalStatus(g);
    const row = {
      equip: g.equipamento, sku: g.sku||'—', resp: (g.pre&&g.pre.responsavel)||'—',
      pre: g.pre? g.pre.status : '—', man: g.manuais.length? (ok+'/5') : '—',
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
// Identidade dos equipamentos (mapa por nome), fonte única de nome_original/ANVISA/família.
async function loadEquipamentos(){
  allEquip={};
  try{
    const res=await apiFetch('/equipamentos');
    if(res&&res.ok){(await res.json()).forEach(e=>{ allEquip[(e.nome||'').trim()] = e; });}
  }catch(e){}
}
async function refreshAll(){await loadData();renderDashboard();renderDocs();showToast('Dados atualizados','success');
  document.getElementById('sync-label').textContent='Atualizado · '+new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
}

// reimportExcel() foi movido para o módulo de Configurações (static/config.js).

// ═══ DASHBOARD ═══
// Replica compute_kpis() do servidor para recalcular o dashboard por equipamento
// (filtro client-side; estrutura idêntica à de _lastKpis).
function computeKpisJS(docs){
  const setores=Object.keys((_lastKpis&&_lastKpis.por_setor)||{});
  const por_setor={},status_counts={};
  setores.forEach(s=>{por_setor[s]=0;status_counts[s]={};});
  const global_counts={'Pendente':0,'Em progresso':0,'Finalizado':0};
  docs.forEach(d=>{
    const setor=d.setor;
    if(setor in por_setor){por_setor[setor]++;const st=d.status||'Elaborar';status_counts[setor][st]=(status_counts[setor][st]||0)+1;}
    const sg=d.status_global||'Pendente';global_counts[sg]=(global_counts[sg]||0)+1;
  });
  const total=docs.length,fin=global_counts['Finalizado']||0;
  return {total,finalizados:fin,em_progresso:global_counts['Em progresso']||0,pendentes:global_counts['Pendente']||0,
    backlog:total-fin,pct_concluidos:total?Math.round(fin/total*1000)/10:0,por_setor,status_counts,global_counts};
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

function setDashEquip(v){ _dashEquip=v||''; renderDashboard(); }

function renderDashboard(){
  if(!_lastKpis) return;
  populateDashEquip();
  const docsView=_dashEquip ? allDocs.filter(d=>(d.equipamento||'').trim()===_dashEquip) : allDocs;
  const kpis=_dashEquip ? computeKpisJS(docsView) : _lastKpis;
  const total=kpis.total;

  const infoEl=document.getElementById('dash-equip-info');
  if(infoEl) infoEl.textContent=_dashEquip ? (total+' documento(s) deste equipamento') : '';
  document.getElementById('dash-updated').textContent='Última atualização: '+new Date().toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
  document.getElementById('dash-pct-badge').textContent=total+' documentos';

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

// ═══ VISUALIZAR ARQUIVOS DO EQUIPAMENTO ═══
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

async function abrirArquivos(caminho, titulo){
  if(!caminho){ showToast('Este documento não tem caminho de armazenamento definido','error'); return; }
  document.getElementById('arquivos-title').textContent = titulo || 'Documentos';
  document.getElementById('arquivos-sub').textContent = caminho;
  document.getElementById('arquivos-body').innerHTML = '<div class="loading-state"><div class="spinner"></div>Carregando arquivos...</div>';
  openModal('arquivos');
  try{
    const res = await apiFetch('/documentos/arquivos?caminho='+encodeURIComponent(caminho));
    if(!res){ return; }
    const data = await res.json().catch(()=>({}));
    if(!res.ok){
      document.getElementById('arquivos-body').innerHTML =
        `<div style="text-align:center;padding:28px;color:var(--t3);font-size:13px">${esc(data.erro||'Não foi possível listar os arquivos')}</div>`;
      return;
    }
    renderArquivosLista(data.arquivos || []);
  }catch(e){
    document.getElementById('arquivos-body').innerHTML =
      '<div style="text-align:center;padding:28px;color:var(--red);font-size:13px">Erro de rede ao listar arquivos</div>';
  }
}

function renderArquivosLista(arquivos){
  const body = document.getElementById('arquivos-body');
  if(!arquivos.length){
    body.innerHTML = '<div style="text-align:center;padding:28px;color:var(--t3);font-size:13px">Nenhum arquivo encontrado nesta pasta.</div>';
    return;
  }
  const grupos = [['IT','Instrução de Trabalho'],['Checklist','Checklists'],['Outros','Outros arquivos']];
  let html = '';
  for(const [cat, label] of grupos){
    const items = arquivos.filter(a=>a.categoria===cat);
    if(!items.length) continue;
    html += `<div class="section-label-line">${esc(label)}</div>`;
    html += items.map(a=>{
      const ext = (a.ext||'').toLowerCase();
      const cor = _ICON_ARQUIVO[ext] || 'var(--t3)';
      const podeVisualizar = a.inline || ext==='docx';
      const acao = podeVisualizar ? 'Visualizar' : 'Baixar';
      const meta = [a.ext?a.ext.toUpperCase():'', _fmtTamanho(a.tamanho), a.modificado].filter(Boolean).join(' · ');
      const c = encodeURIComponent(a.caminho);
      const nomeEsc = (a.nome||'').replace(/'/g,"\\'");
      return `<div class="arquivo-row" onclick="abrirArquivo('${c}', '${nomeEsc}', '${ext}', ${a.inline?'true':'false'})" title="${esc(acao)}">
        <span class="arquivo-ext" style="background:${cor}">${esc((a.ext||'?').toUpperCase().slice(0,4))}</span>
        <span class="arquivo-info"><span class="arquivo-nome">${esc(a.nome)}</span><span class="arquivo-meta">${esc(meta)}</span></span>
        <span class="arquivo-acao">${esc(acao)}</span>
      </div>`;
    }).join('');
  }
  body.innerHTML = html;
}

function _downloadArquivo(caminhoEnc, nome){
  const a = document.createElement('a');
  a.href = API + '/documentos/arquivo?caminho=' + caminhoEnc + '&token=' + encodeURIComponent(getToken()) + '&download=1';
  a.download = nome || ''; a.style.display = 'none';
  document.body.appendChild(a); a.click(); a.remove();
}

function abrirArquivo(caminhoEnc, nome, ext, inline){
  ext = (ext||'').toLowerCase();
  if(ext === 'docx'){ return visualizarDocx(caminhoEnc, nome); }
  if(inline){
    const url = API + '/documentos/arquivo?caminho=' + caminhoEnc + '&token=' + encodeURIComponent(getToken());
    window.open(url, '_blank');
  }else{
    _downloadArquivo(caminhoEnc, nome);
    showToast('Download iniciado: '+(nome||'arquivo'),'success');
  }
}

// Renderiza um .docx dentro do navegador (client-side, sem sair da rede)
async function visualizarDocx(caminhoEnc, nome){
  const body = document.getElementById('docview-body');
  document.getElementById('docview-title').textContent = nome || 'Documento';
  document.getElementById('docview-download').onclick = ()=>_downloadArquivo(caminhoEnc, nome);
  if(typeof docx === 'undefined' || !docx.renderAsync){
    showToast('Visualizador indisponível — baixando o arquivo','error');
    _downloadArquivo(caminhoEnc, nome);
    return;
  }
  body.innerHTML = '<div class="loading-state"><div class="spinner"></div>Renderizando documento...</div>';
  openModal('docview');
  try{
    const res = await apiFetch('/documentos/arquivo?caminho=' + caminhoEnc);
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

// Agrupa allDocs por nome de equipamento (PRE + Manuais juntos)
function groupByEquip(){
  const groups = {};
  allDocs.forEach(d => {
    const key = (d.equipamento || '—').trim();
    if(!groups[key]){
      groups[key] = { equipamento:key, sku:'', fabricante:'', pre:null, manuais:[],
                      byTipo:{}, docs:[], equip:allEquip[key]||null };
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
  // Complementa identidade a partir da entidade Equipamento
  Object.values(groups).forEach(g=>{
    if(g.equip){ if(!g.sku) g.sku=g.equip.sku||''; if(!g.fabricante) g.fabricante=g.equip.fabricante||''; }
  });
  return Object.values(groups).sort((a,b)=>a.equipamento.localeCompare(b.equipamento));
}

// Documentos de equipamento (PRE + Manuais) do grupo
function _equipDocs(g){ return g.docs.filter(d=>d.setor==='PRE'||d.setor==='Manuais'); }
function _docFinalizado(d){
  return (d.setor==='PRE' && d.status==='Homologado') || (d.setor==='Manuais' && d.status==='Concluído');
}
function equipManuaisOk(g){ return g.manuais.filter(d=>d.status==='Concluído').length; }

// Cor do card = PIOR status entre os documentos do equipamento.
function equipStatusColor(g){
  const docs = _equipDocs(g);
  if(!docs.length) return 'amber';
  if(docs.some(d=>d.status==='Elaborar')) return 'red';   // algum não iniciado
  if(docs.every(_docFinalizado)) return 'green';          // tudo finalizado
  return 'amber';
}

function equipMatchesChip(g, chip){
  const docs = _equipDocs(g);
  const color = equipStatusColor(g);
  const ok = equipManuaisOk(g), cnt = g.manuais.length;
  switch(chip){
    case 'todos': return true;
    case 'pendente': return color==='red';
    case 'progresso': return color==='amber';
    case 'finalizado': return color==='green';
    case 'pre-pendente': return docs.some(d=>d.setor==='PRE' && d.status==='Elaborar');
    case 'manuais-incompletos': return cnt>0 && ok<cnt;
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
    return `<div class="equip-card st-${color}" data-equip="${esc(g.equipamento)}" onclick="openEquipModal('${esc(g.equipamento).replace(/'/g,"\\'")}')">
      <div class="equip-card-name">${esc(g.equipamento)}</div>
      <div class="equip-card-sku">${g.sku?esc(g.sku):'<span class="muted">sem SKU</span>'}</div>
    </div>`;
  }).join('');
}

// ═══ MODAL DE EQUIPAMENTO ═══
let _equipCtx = null; // { equipamento, equip, byTipo:{tipo:doc}, docs:[], sku, fabricante, g }

// Wrapper mantido para o modal de usuário (e quaisquer outros modais simples)
function openModal(id){ openBaseModal(id); }

const _PRE_STATUS = ['Elaborar','Treinamento Piloto','Enviado para Homologação','Homologado'];
const _MAN_STATUS = ['Elaborar','Em andamento','Concluído'];
const _PRE_TIPOS = [
  ['IT','Instrução de Trabalho'],
  ['Checklist','Checklist'],
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
  document.querySelectorAll('#equip-tabs .equip-modal-tab').forEach(b=>b.classList.toggle('active', b.dataset.tab===tab));
  document.querySelectorAll('#equip-panels .equip-tab-panel').forEach(p=>p.classList.toggle('active', p.dataset.panel===tab));
}

function openEquipModal(equipName){
  const g = groupByEquip().find(x=>x.equipamento===equipName) || null;
  const docs = allDocs.filter(d => (d.equipamento||'').trim() === equipName);
  const byTipo = {};
  docs.forEach(d=>{ if(d.tipo_doc && !byTipo[d.tipo_doc]) byTipo[d.tipo_doc]=d; });
  const equip = (g&&g.equip) || allEquip[equipName] || null;
  const sku = (g&&g.sku) || (equip&&equip.sku) || '';
  const fabricante = (g&&g.fabricante) || (equip&&equip.fabricante) || '';
  const equip_id = (equip&&equip.id) || (docs.find(d=>d.equipamento_id)||{}).equipamento_id || null;
  _equipCtx = { equipamento: equipName, equip, equip_id, byTipo, docs, sku, fabricante, g };

  const delBtn = document.getElementById('btn-del-equip');
  if(delBtn) delBtn.style.display = (currentUser.role==='admin'||currentUser.role==='gestor') ? 'inline-flex' : 'none';

  renderEquipHeader();
  renderEquipModal();
  switchEquipTab(_TODOS_TIPOS[0][0]);   // abre na aba "Instrução de Trabalho"
  openBaseModal('equip');
}

// Cabeçalho de identidade do equipamento (fonte: entidade Equipamento)
function renderEquipHeader(){
  const e = _equipCtx.equip || {};
  const color = _equipCtx.g ? equipStatusColor(_equipCtx.g) : 'amber';
  const dot = color==='green'?'var(--green)':color==='red'?'var(--red)':'var(--amber)';
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
      ${_equipCtx.equip_id?`<a class="btn btn-ghost btn-sm" href="/equipamentos" title="Editar a identidade no módulo Equipamentos" style="text-decoration:none">↗ Abrir no módulo Equipamentos</a>`:''}
    </div>
    <div class="equip-id-hint" style="font-size:11px;color:var(--t3);margin-top:6px">A identidade (nome, SKU, fabricante, ANVISA, família…) é editada no módulo <b>Equipamentos</b> e reflete aqui automaticamente.</div>`;
}

// Abas (uma por tipo) + painéis
function renderEquipModal(){
  const tabsEl = document.getElementById('equip-tabs');
  const panelsEl = document.getElementById('equip-panels');
  tabsEl.innerHTML = _TODOS_TIPOS.map(([tipo,label])=>{
    const d = _equipCtx.byTipo[tipo];
    const col = d ? _statusDotColor(d) : 'var(--t4)';
    return `<button type="button" class="equip-modal-tab" data-tab="${tipo}" onclick="switchEquipTab('${tipo}')"><span class="tab-dot" style="background:${col}"></span>${esc(label)}</button>`;
  }).join('');
  panelsEl.innerHTML = _TODOS_TIPOS.map(([tipo])=>
    `<div class="equip-tab-panel" data-panel="${tipo}">${renderTipoPanel(tipo)}</div>`
  ).join('');
}

// Painel de um tipo de documento
function renderTipoPanel(tipo){
  const label = _tipoLabel(tipo);
  const d = _equipCtx.byTipo[tipo];
  const isPre = _isPreTipo(tipo);
  if(!d){
    return `<div style="text-align:center;padding:24px;color:var(--t3)">
      <p style="margin-bottom:12px">Este equipamento ainda não tem o documento "${esc(label)}".</p>
      <button class="btn btn-primary btn-sm" type="button" onclick="createTipo('${tipo}')">Criar ${esc(label)}</button>
    </div>`;
  }
  const statusOpts = (isPre?_PRE_STATUS:_MAN_STATUS)
    .map(s=>`<option value="${esc(s)}" ${d.status===s?'selected':''}>${esc(s)}</option>`).join('');
  const setorTag = `<span class="equip-tag">setor ${isPre?'PRE · 4 etapas':'Manuais · 3 etapas'}</span>`;
  const datasPre = isPre ? `
    <div class="g2">
      <div class="form-group"><label class="form-label">Data Treinamento Piloto</label><input class="form-input" type="date" id="et-treino-${tipo}" value="${_dateToInput(d.data_treinamento)}"></div>
      <div class="form-group"><label class="form-label">Data Envio Homologação</label><input class="form-input" type="date" id="et-homol-${tipo}" value="${_dateToInput(d.data_homologacao)}"></div>
    </div>
    <div class="g2">
      <div class="form-group"><label class="form-label">Obs. Treinamento</label><input class="form-input" id="et-obstr-${tipo}" value="${esc(d.obs_treinamento)}"></div>
      <div class="form-group"><label class="form-label">Obs. Homologação</label><input class="form-input" id="et-obshm-${tipo}" value="${esc(d.obs_homologacao)}"></div>
    </div>` : '';
  return `
    <div class="equip-panel-head"><span class="equip-panel-title">${esc(label)}</span>${setorTag}</div>
    <div class="g2">
      <div class="form-group"><label class="form-label">Código do Doc</label><input class="form-input" id="et-cod-${tipo}" value="${esc(d.codigo_doc)}"></div>
      <div class="form-group"><label class="form-label">Responsável</label><input class="form-input" id="et-resp-${tipo}" value="${esc(d.responsavel)}"></div>
    </div>
    <div class="form-group"><label class="form-label">Status</label><select class="form-input" id="et-st-${tipo}">${statusOpts}</select></div>
    ${datasPre}
    <div class="form-group"><label class="form-label">Armazenamento (Caminho na Rede)</label>
      <div class="armazenamento-row">
        <input class="form-input" id="et-arm-${tipo}" value="${esc(d.armazenamento)}">
        <button type="button" class="btn btn-ghost btn-sm" title="Ver arquivos desta pasta" onclick="abrirArquivos(document.getElementById('et-arm-${tipo}').value, '${esc(label)} — '+(_equipCtx?_equipCtx.equipamento:''))">📄 Ver arquivos</button>
      </div>
    </div>
    <div class="modal-footer" style="margin-top:8px"><button class="btn btn-primary" type="button" onclick="saveTipoDoc('${tipo}')">Salvar alterações</button></div>`;
}

async function deleteEquip(){
  if(!_equipCtx) return;
  if(!(currentUser.role==='admin'||currentUser.role==='gestor')){ showToast('Sem permissão','error'); return; }
  const nome = _equipCtx.equipamento;
  const docs = _equipCtx.docs || [];
  if(!docs.length){ showToast('Nada para excluir','info'); return; }
  const ok = await confirmModal('Excluir equipamento', `Excluir "${nome}" e todos os seus ${docs.length} documento(s)? Esta ação pode ser revertida no banco (soft delete).`);
  if(!ok) return;
  try{
    for(const d of docs){
      const res = await apiFetch(`/documentos/${d.id}`, {method:'DELETE'});
      if(!res || !res.ok){ const e = res ? await res.json().catch(()=>({})) : {}; showToast(e.erro||'Erro ao excluir','error'); return; }
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
  const payload = {
    codigo_doc: val('et-cod-'+tipo),
    responsavel: val('et-resp-'+tipo),
    status: val('et-st-'+tipo),
    armazenamento: val('et-arm-'+tipo),
  };
  if(_isPreTipo(tipo)){
    payload.data_treinamento = val('et-treino-'+tipo);
    payload.data_homologacao = val('et-homol-'+tipo);
    payload.obs_treinamento  = val('et-obstr-'+tipo);
    payload.obs_homologacao  = val('et-obshm-'+tipo);
  }
  try{
    const res = await _patchDoc(d.id, payload);
    if(res && res.ok){ showToast(`${_tipoLabel(tipo)} salvo`,'success'); closeModal('equip'); await refreshAll(); }
    else { const e = await res.json().catch(()=>({})); showToast(e.erro||'Erro ao salvar','error'); }
  }catch(e){ showToast('Erro de rede','error'); }
}

// Cria um tipo de documento ausente para o equipamento aberto
async function createTipo(tipo){
  const isPre = _isPreTipo(tipo);
  const payload = { setor: isPre?'PRE':'Manuais', tipo_doc: tipo,
    equipamento:_equipCtx.equipamento, sku:_equipCtx.sku, fabricante:_equipCtx.fabricante,
    documento:`${_tipoLabel(tipo)} - ${_equipCtx.equipamento}` };
  try{
    const res = await apiFetch('/documentos', {method:'POST', body:JSON.stringify(payload)});
    if(res && res.ok){ showToast(`${_tipoLabel(tipo)} criado`,'success'); await refreshAll(); openEquipModal(_equipCtx.equipamento); }
    else { showToast('Erro ao criar documento','error'); }
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

// ═══ BOOTSTRAP: hub de módulos ═══
// Com token: quem não veio do hub (dt_module!=='docs') é levado ao hub;
// quem veio do hub entra direto no app. Sem token: tela de login normal.
(function bootstrapHub(){
  if(!getToken())return;
  if(sessionStorage.getItem('dt_module')!=='docs'){window.location.href='/hub';return}
  try{
    const u=JSON.parse(localStorage.getItem('doctrack_user')||'{}');
    if(u&&u.nome)currentUser={name:u.nome,email:u.email,role:u.role,initials:u.nome.split(' ').map(w=>w[0]).join('').substring(0,2).toUpperCase()};
  }catch(e){}
  document.getElementById('login-screen').style.display='none';
  document.getElementById('app').style.display='block';
  initApp();
})();
