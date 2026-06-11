import os

JS_CODE = """
/* ── GERAÇÃO DE RELATÓRIO PDF (Client-side) ── */
function _exportConfigEnt(){
  return {
    lancamento: (document.getElementById('exp-lancamento')||{}).value||'',
    moscow: (document.getElementById('exp-moscow')||{}).value||'',
    status: (document.getElementById('exp-status')||{}).value||'',
  };
}
function _exportFilteredProjects(){
  const cfg = _exportConfigEnt();
  const q = cfg.lancamento.trim().toLowerCase();
  return _projetosAll.filter(p => {
    if (q && !(p.lancamento||'').toLowerCase().includes(q)) return false;
    if (cfg.moscow) {
      const v = normMoscow(p.moscow);
      const k = v === "Wont" ? "Wont" : (v || "Sem prioridade");
      if (k !== cfg.moscow) return false;
    }
    if (cfg.status === 'Finalizado' && p.avanco < 100) return false;
    if (cfg.status === 'Pendente' && p.avanco === 100) return false;
    return true;
  });
}
function updateExportPreviewEnt(){
  const el = document.getElementById('exp-preview');
  if(el) el.textContent = `${_exportFilteredProjects().length} projeto(s) serão incluídos no relatório`;
}
function openExportModal(){
  const el1=document.getElementById('exp-lancamento'); if(el1) el1.value='';
  const el2=document.getElementById('exp-moscow'); if(el2) el2.value='';
  const el3=document.getElementById('exp-status'); if(el3) el3.value='';
  ['exp-lancamento','exp-moscow','exp-status'].forEach(id=>{
    const e=document.getElementById(id); if(e) e.addEventListener('input', updateExportPreviewEnt);
  });
  updateExportPreviewEnt();
  const m = document.getElementById('modal-export-ent');
  m.classList.add('open');
  m.setAttribute('aria-hidden', 'false');
}
function fecharModalExport(){
  const m = document.getElementById('modal-export-ent');
  m.classList.remove('open');
  m.setAttribute('aria-hidden', 'true');
}

const _CHART_FONT = "'Inter', system-ui, sans-serif";
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
const _barValueHPlugin = { id:'barValuesH', afterDatasetsDraw(chart){
  const ctx=chart.ctx; const meta=chart.getDatasetMeta(0);
  chart.data.datasets[0].data.forEach((v,i)=>{ const el=meta.data[i]; if(!el) return;
    ctx.save(); ctx.fillStyle='#f1f5f9'; ctx.font='bold 26px '+_CHART_FONT; ctx.textAlign='left'; ctx.textBaseline='middle';
    ctx.fillText(String(v)+'%', el.x+10, el.y); ctx.restore();
  });
}};
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
function _addImgContain(doc, img, x, y, boxW, boxH, imgRatio){
  if(!img) return;
  let w = boxW, h = boxW/imgRatio;
  if(h > boxH){ h = boxH; w = boxH*imgRatio; }
  doc.addImage(img, 'PNG', x + (boxW-w)/2, y + (boxH-h)/2, w, h);
}

async function gerarRelatorioPDF(){
  if(!window.jspdf){ toast('Aguarde o carregamento do gerador de PDF e tente novamente', true); return; }
  const projects = _exportFilteredProjects();
  if(!projects.length){ toast('Nenhum projeto corresponde aos filtros', true); return; }
  toast('Gerando relatório...');
  const cfg = _exportConfigEnt();

  let conc=0, prog=0, pend=0;
  projects.forEach(p=>{
    if(p.avanco === 100) conc++;
    else if(p.avanco > 0) prog++;
    else pend++;
  });
  const avg = projects.length ? Math.round(projects.reduce((a,b)=>a+b.avanco,0)/projects.length) : 0;
  
  const top = [...projects].sort((a,b)=>b.avanco - a.avanco).slice(0,10);
  const moscowCont = {};
  projects.forEach(p=>{
      const m = normMoscow(p.moscow);
      const k = m==="Wont"?"Wont":(m||"Sem prioridade");
      moscowCont[k]=(moscowCont[k]||0)+1;
  });

  const donutImg = await _renderChartImage((ctx)=>({
    type:'doughnut',
    data:{labels:['Concluídos','Em progresso','Pendentes'],
      datasets:[{data:[conc,prog,pend], backgroundColor:['#34d399','#22d3ee','#fbbf24'], borderColor:'#1a1f3a', borderWidth:5}]},
    options:{cutout:'66%', layout:{padding:14}, plugins:{legend:{display:false}}},
    plugins:[_centerTextPlugin(projects.length, 'projetos')]
  }), 760, 760);

  const moscowColors = {"Must":"#ef4444", "Should":"#f59e0b", "Could":"#3b82f6", "Wont":"#64748b", "Sem prioridade":"#94a3b8"};
  const mLabels = Object.keys(moscowCont);
  const mVals = mLabels.map(l=>moscowCont[l]);
  const mBg = mLabels.map(l=>moscowColors[l]);

  const moscowImg = await _renderChartImage((ctx)=>({
    type:'doughnut',
    data:{labels:mLabels.map(x=>x==='Wont'?"Won't":x),
      datasets:[{data:mVals, backgroundColor:mBg, borderColor:'#1a1f3a', borderWidth:5}]},
    options:{cutout:'66%', layout:{padding:14}, plugins:{legend:{display:false}}},
    plugins:[_centerTextPlugin(projects.length, 'projetos')]
  }), 760, 760);

  const barImg = await _renderChartImage((ctx)=>({
    type:'bar',
    data:{labels:top.map(p=>p.nome),
      datasets:[{data:top.map(p=>p.avanco), borderRadius:8, maxBarThickness:48, backgroundColor:_hgrad(ctx,1300,'#22d3ee','#3b82f6')}]},
    options:{indexAxis:'y', layout:{padding:{right:80, left:6, top:4, bottom:4}}, plugins:{legend:{display:false}},
      scales:{x:{min:0, max:100, ticks:{display:false}, grid:{color:'rgba(148,163,255,.14)'}, border:{display:false}},
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
  
  function paintBg(){ doc.setFillColor(...C.bg); doc.rect(0,0,pageW,pageH,'F'); }
  function card(x,yy,w,h){ doc.setFillColor(...C.card); doc.setDrawColor(...C.border); doc.setLineWidth(0.3); doc.roundedRect(x,yy,w,h,2.5,2.5,'FD'); }
  function cardTitle(txt,x,yy,w){ doc.setFont('helvetica','bold'); doc.setFontSize(8.5); doc.setTextColor(...C.accent); doc.text(txt.toUpperCase(), x+w/2, yy+6.5, {align:'center'}); }
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
  if(cfg.lancamento) filtros.push(`Lançamento: ${cfg.lancamento}`);
  if(cfg.moscow) filtros.push(`MoSCoW: ${cfg.moscow==="Wont"?"Won't":cfg.moscow}`);
  if(cfg.status) filtros.push(`Status: ${cfg.status}`);
  if(!filtros.length) filtros.push('Todos os projetos');

  paintBg();
  doc.setFont('helvetica','bold'); doc.setFontSize(19); doc.setTextColor(...C.t1);
  doc.text('Relatório Executivo — Projetos & Entregáveis', margin, 18);
  doc.setFont('helvetica','bold'); doc.setFontSize(10); doc.setTextColor(...C.accent);
  doc.text('DocTrack Enterprise v4.0', margin, 25);
  doc.setFont('helvetica','normal'); doc.setFontSize(8); doc.setTextColor(...C.tmut);
  doc.text('Gerado em '+hoje, pageW-margin, 16, {align:'right'});
  doc.text(filtros.join('   ·   '), pageW-margin, 22, {align:'right'});
  doc.setDrawColor(...C.accent); doc.setLineWidth(0.5); doc.line(margin, 29, pageW-margin, 29);

  let y = 34;
  const rowAh = 74, gap = 4, colW = 58;
  const kpis = [['Projetos Filtrados', projects.length, C.t1],['Concluídos', conc, C.green],['Em progresso', prog, C.cyan],['Avanço Médio', avg+'%', C.accent]];
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
  const donImgH = rowAh - 18; 
  card(d1x, y, donW, rowAh); cardTitle('Status dos Projetos', d1x, y, donW);
  _addImgContain(doc, donutImg, d1x+6, y+9, donW-12, donImgH, 1);
  legendRow([['Concluídos',C.green],['Em progresso',C.cyan],['Pendentes',C.amber]].map(([l,c])=>[c,l]), d1x+donW/2, y+rowAh-4);
  
  card(d2x, y, donW, rowAh); cardTitle('Prioridade MoSCoW', d2x, y, donW);
  _addImgContain(doc, moscowImg, d2x+6, y+9, donW-12, donImgH, 1);
  const legMoscow = mLabels.map(l=> {
      const c = l==="Must"?C.red:l==="Should"?C.amber:l==="Could"?[59,130,246]:l==="Wont"?[100,116,139]:[148,163,184];
      return [c, l==="Wont"?"Won't":l];
  });
  legendRow(legMoscow, d2x+donW/2, y+rowAh-4);

  y += rowAh + gap;
  const rowBh = pageH - y - 11;
  card(margin, y, pageW-margin*2, rowBh); cardTitle('Avanço por Projeto (Top 10)', margin, y, pageW-margin*2);
  if(barImg) doc.addImage(barImg, 'PNG', margin+4, y+10, pageW-margin*2-8, rowBh-14);

  // Página 2: Detalhamento
  doc.addPage(); paintBg(); y = margin+4;
  doc.setFont('helvetica','bold'); doc.setFontSize(14); doc.setTextColor(...C.t1);
  doc.text('Detalhamento dos Projetos', margin, y+4); y += 11;

  const cols = [
    {h:'Projeto', k:'nome', w:100},
    {h:'MoSCoW', k:'moscow', w:26},
    {h:'Pendências', k:'pendentes', w:30},
    {h:'Lançamento', k:'lancamento', w:40},
    {h:'Avanço', k:'avanco', w:30},
  ];
  const rowH=7.2, headerH=9;
  function thead(){
    doc.setFillColor(...C.card); doc.rect(margin,y,pageW-margin*2,headerH,'F');
    doc.setFont('helvetica','bold'); doc.setFontSize(7.5); doc.setTextColor(...C.accent);
    let cx=margin; cols.forEach(c=>{doc.text(c.h, cx+3, y+6); cx+=c.w;}); y+=headerH;
  }
  thead();
  projects.forEach((p,idx)=>{
    if(y+rowH > pageH-11){ doc.addPage(); paintBg(); y=margin+4; thead(); }
    if(idx%2===0){ doc.setFillColor(...C.rowAlt); doc.rect(margin,y,pageW-margin*2,rowH,'F'); }
    doc.setDrawColor(...C.border); doc.setLineWidth(0.15); doc.line(margin,y+rowH,pageW-margin,y+rowH);
    
    let cx=margin;
    doc.setFontSize(7.5);
    cols.forEach(c=>{
      let v = String(p[c.k] || (c.k==='avanco'?'0':'—'));
      if(c.k === 'avanco') v += '%';
      if(c.k === 'moscow') { v = normMoscow(v); if(v==="Wont") v="Won't"; }
      const maxW = c.w-4;
      if(doc.getTextWidth(v)>maxW){ v=v.substring(0, Math.max(1, Math.floor(v.length*maxW/doc.getTextWidth(v))-1))+'…'; }
      if(c.k==='nome'){ doc.setFont('helvetica','bold'); doc.setTextColor(...C.t1); }
      else { doc.setFont('helvetica', 'normal'); doc.setTextColor(...C.tmut); }
      doc.text(v, cx+3, y+4.8); cx+=c.w;
    });
    y+=rowH;
  });

  const pages=doc.internal.getNumberOfPages();
  for(let i=1;i<=pages;i++){ doc.setPage(i); doc.setFont('helvetica','normal'); doc.setFontSize(7); doc.setTextColor(...C.tmut);
    doc.text('DocTrack Enterprise — Relatório de Projetos', margin, pageH-5);
    doc.text(`Página ${i} de ${pages}`, pageW-margin, pageH-5, {align:'right'}); }

  doc.save('DocTrack_Projetos.pdf');
  fecharModalExport();
  toast('Relatório gerado');
}

"""

with open(r'c:\Melk\dashboard_IT\static\entregaveis.js', 'a', encoding='utf-8') as f:
    f.write("\n" + JS_CODE)
print("Updated entregaveis.js")
