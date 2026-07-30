/* equipamentos-pdf.js — Exportar PDF do Dashboard e da aba Desenvolvimento.
 *
 * Mesmo relatório A4 paisagem escuro dos módulos Documentos e Projetos: a
 * moldura (cartões, legendas, tabela paginada, rodapé) vem de pdf-report.js e
 * os gráficos são os mesmos da tela, rasterizados pelo Chart.js.
 *
 * Cada relatório tem o SEU modal de filtros, com os recortes que fazem sentido
 * para ele: o do Dashboard pergunta faixa de ICE e situação da ANVISA, o do IDP
 * pergunta classe ABC e em qual das 6 revisões há pendência. Perguntar no
 * momento da exportação é o ponto: a tela oferece um filtro por vez ("classe A"
 * ou "todas"), e um relatório costuma querer "A e B", "só o que tem registro
 * vencido", "só o que está pendente em IT".
 *
 * Os grupos abrem semeados com o que está selecionado na tela, mas daqui em
 * diante é o modal que manda — o PDF não olha mais os selects da página, para
 * não haver dois filtros somados sem o usuário perceber.
 */

/* jsPDF vem de /static/vendor e é o único ponto que pode faltar. */
function _pdfIndisponivel(){
  if(typeof PDFRep !== "undefined" && PDFRep.temJsPDF()) return false;
  toast("Gerador de PDF não carregou. Recarregue a página.", true);
  return true;
}
const _PDF_PALETA_CAT = ["#10b981","#22d3ee","#f59e0b","#a78bfa","#06b6d4","#f43f5e","#3b82f6"];
/* Contagem por chave → [[rótulo, valor]] em ordem decrescente, com a cauda
   agrupada em "Outras" para a legenda não virar um muro de texto. */
function _pdfTopN(cont, n, rotuloResto){
  const pares = Object.entries(cont).sort((a,b)=>b[1]-a[1]);
  if(pares.length <= n) return pares;
  const resto = pares.slice(n).reduce((t,p)=>t+p[1], 0);
  return pares.slice(0, n).concat([[rotuloResto, resto]]);
}

/* ══ FILTROS DE EXPORTAÇÃO ════════════════════════════════════════════════
   Cada grupo é uma grade de caixas com um `data-exp` em comum. A regra é
   literal em todos: vale o que está marcado. Desmarcar o grupo inteiro dá zero
   resultado e a prévia diz isso — é mais honesto que tratar "nada marcado" como
   "tudo", que esconderia o erro até o PDF sair com a frota inteira.
   A única exceção é declarada na tela: "revisão pendente em" vazio não
   restringe, porque ali o grupo acrescenta uma condição em vez de definir o
   escopo. */

const EXP_FAIXAS = [["completo","Completo 85%+"], ["parcial","Parcial 50-84%"], ["inicial","Inicial <50%"]];
const EXP_ANVISA = [["vencido","Vencida"], ["vencendo","Vence em até 90 dias"],
                    ["ok","Vigente"], ["sem_data","Sem data"]];
const EXP_ANVISA_COR = {vencido:"#f43f5e", vencendo:"#f59e0b", ok:"#10b981", sem_data:"#94a3b8"};
const EXP_CLASSES = [["A","Classe A"], ["B","Classe B"], ["C","Classe C"], ["","Sem classe"]];
const EXP_CLASSE_COR = {A:"#10b981", B:"#f59e0b", C:"#64748b", "":"#a78bfa"};

function _expChk(grupo, valor, rotulo, marcado, cor){
  const ponto = cor ? `<span class="exp-dot" style="background:${cor}"></span>` : "";
  return `<label class="exp-chk"><input type="checkbox" data-exp="${grupo}" value="${esc(valor)}"${marcado?" checked":""}>`
       + `${ponto}<span>${esc(rotulo)}</span></label>`;
}
function _expMarcados(grupo){
  return [...document.querySelectorAll(`[data-exp="${grupo}"]:checked`)].map(el=>el.value);
}
function _expTotal(grupo){
  return document.querySelectorAll(`[data-exp="${grupo}"]`).length;
}
/* Rótulos legíveis do que ficou marcado — alimenta o cabeçalho do PDF. */
function _expRotulos(grupo, pares){
  const marcados = _expMarcados(grupo);
  const mapa = new Map(pares);
  return marcados.map(v => mapa.has(v) ? mapa.get(v) : v);
}
function expToggleGrupo(grupo){
  const caixas = [...document.querySelectorAll(`[data-exp="${grupo}"]`)];
  const ligar = caixas.some(c=>!c.checked);
  caixas.forEach(c=>{ c.checked = ligar; });
  expAtualizarPrevia();
}
/* Grade de categorias: a taxonomia + "Sem categoria", que existe na frota e não
   está em TAX. Semeia com a categoria selecionada na tela, se houver uma. */
function _expGradeCats(grupo, selecionada){
  const itens = (TAX.categorias||[]).map(c=>[String(c.id), c.nome]);
  itens.push(["", "Sem categoria"]);
  return itens.map(([v,rot],i)=>
    _expChk(grupo, v, rot, !selecionada || String(selecionada)===v,
            _PDF_PALETA_CAT[i%_PDF_PALETA_CAT.length])).join("");
}
function _expParesCats(grupo){
  return [...document.querySelectorAll(`[data-exp="${grupo}"]`)]
    .map(el=>[el.value, el.parentElement.querySelector("span:last-child").textContent]);
}

function abrirExportDash(){
  document.getElementById("exp-dash-cats").innerHTML =
    _expGradeCats("dash-cat", val("dash-cat"));
  document.getElementById("exp-dash-faixas").innerHTML =
    EXP_FAIXAS.map(([v,r])=>_expChk("dash-faixa", v, r, true, FCOLOR[v])).join("");
  document.getElementById("exp-dash-anvisa").innerHTML =
    EXP_ANVISA.map(([v,r])=>_expChk("dash-anvisa", v, r, true, EXP_ANVISA_COR[v])).join("");
  document.getElementById("exp-dash-atrasados").checked = false;
  document.getElementById("exp-dash-semdono").checked = false;
  document.getElementById("exp-dash-bloq").checked = !!(document.getElementById("dash-bloq")||{}).checked;
  document.getElementById("exp-dash-ordem").value = "criticos";
  _expLigarEventos("modal-export-dash");
  openBaseModal("export-dash");     // a prévia só conta com o modal visível
  expAtualizarPrevia();
}

function abrirExportDev(){
  const classeTela = val("dev-classe");        // "" | A | B | C | "-" (sem classe)
  document.getElementById("exp-dev-classes").innerHTML =
    EXP_CLASSES.map(([v,r])=>{
      const marcado = !classeTela || (classeTela==="-" ? v==="" : classeTela===v);
      return _expChk("dev-classe", v, r, marcado, EXP_CLASSE_COR[v]);
    }).join("");
  document.getElementById("exp-dev-cats").innerHTML =
    _expGradeCats("dev-cat", val("dev-cat"));
  document.getElementById("exp-dev-faixas").innerHTML =
    EXP_FAIXAS.map(([v,r])=>_expChk("dev-faixa", v, r, true, FCOLOR[v])).join("")
    + _expChk("dev-faixa", "sem", "Sem avaliação", true, "#94a3b8");
  document.getElementById("exp-dev-itens").innerHTML =
    DEV_ITENS.map(it=>_expChk("dev-item", it, DEV_ITEM_LABEL[it], false)).join("");
  document.getElementById("exp-dev-bloq").checked = !!(document.getElementById("dev-bloq")||{}).checked;
  document.getElementById("exp-dev-ordem").value = "pareto";
  _expLigarEventos("modal-export-dev");
  openBaseModal("export-dev");      // a prévia só conta com o modal visível
  expAtualizarPrevia();
}

/* Um listener por modal, no container: as caixas são recriadas a cada abertura,
   então ligar em cada uma vazaria listeners. */
function _expLigarEventos(idModal){
  const m = document.getElementById(idModal);
  if(!m || m._expLigado) return;
  m.addEventListener("change", expAtualizarPrevia);
  m._expLigado = true;
}

function expAtualizarPrevia(){
  const par = [["exp-dash-preview", _expDashLista, "exp-dash-gerar"],
               ["exp-dev-preview",  _expDevLista,  "exp-dev-gerar"]];
  par.forEach(([idPrev, lista, idBtn])=>{
    const el = document.getElementById(idPrev);
    if(!el || !el.offsetParent) return;          // modal fechado: não recalcula
    let n = 0;
    try{ n = lista().length; }catch(e){ n = 0; }
    el.textContent = n
      ? `${n} equipamento(s) no relatório`
      : "Nenhum equipamento corresponde a esta combinação de filtros";
    el.classList.toggle("vazio", !n);
    const btn = document.getElementById(idBtn);
    if(btn) btn.disabled = !n;
  });
}

/* ── Dashboard: escopo + recortes ── */
const _EXP_ORD_DASH = {
  criticos:  (a,b)=>(b.s.docs_atrasados-a.s.docs_atrasados) || (a.s.ice-b.s.ice),
  ice:       (a,b)=>a.s.ice-b.s.ice || (a.e.nome||"").localeCompare(b.e.nome||""),
  "ice-desc":(a,b)=>b.s.ice-a.s.ice || (a.e.nome||"").localeCompare(b.e.nome||""),
  nome:      (a,b)=>(a.e.nome||"").localeCompare(b.e.nome||""),
};
function _expDashCfg(){
  return {
    cats:    _expMarcados("dash-cat"),
    faixas:  _expMarcados("dash-faixa"),
    anvisa:  _expMarcados("dash-anvisa"),
    atrasados: !!(document.getElementById("exp-dash-atrasados")||{}).checked,
    semDono:   !!(document.getElementById("exp-dash-semdono")||{}).checked,
    bloq:      !!(document.getElementById("exp-dash-bloq")||{}).checked,
    ordem:   val("exp-dash-ordem") || "criticos",
  };
}
function _expDashLista(){
  const cfg = _expDashCfg();
  const S = EQUIP
    .filter(e => cfg.bloq || !ehBloqueado(e))
    .filter(e => cfg.cats.includes(String(e.categoria_id || "")))
    .map(e => ({e, s:scores(e)}))
    .filter(o => cfg.faixas.includes(faixa(o.s.ice)))
    .filter(o => cfg.anvisa.includes(o.s.reg_estado))
    .filter(o => !cfg.atrasados || o.s.docs_atrasados > 0)
    .filter(o => !cfg.semDono ||
                 (!(o.e.responsavel||"").trim() && !(o.s.responsaveis||[]).length));
  return S.sort(_EXP_ORD_DASH[cfg.ordem] || _EXP_ORD_DASH.criticos);
}

/* ── IDP: escopo + pendência por revisão ── */
const _EXP_ORD_DEV = {
  pareto: (a,b)=>_prioridade(a.e, b.e),
  idp:    (a,b)=>((a.idp==null?101:a.idp) - (b.idp==null?101:b.idp))
                 || (a.e.nome||"").localeCompare(b.e.nome||""),
  saidas: (a,b)=>(b.e.qtd_saidas||0)-(a.e.qtd_saidas||0),
  nome:   (a,b)=>(a.e.nome||"").localeCompare(b.e.nome||""),
};
function _expDevCfg(){
  return {
    classes: _expMarcados("dev-classe"),
    cats:    _expMarcados("dev-cat"),
    faixas:  _expMarcados("dev-faixa"),
    itens:   _expMarcados("dev-item"),
    bloq:    !!(document.getElementById("exp-dev-bloq")||{}).checked,
    ordem:   val("exp-dev-ordem") || "pareto",
  };
}
function _expDevLista(){
  const cfg = _expDevCfg();
  const S = EQUIP
    .filter(e => cfg.bloq || !ehBloqueado(e))
    .filter(e => cfg.classes.includes(e.pareto_classe || ""))
    .filter(e => cfg.cats.includes(String(e.categoria_id || "")))
    .map(e => ({e, idp:idp(e)}))
    .filter(o => cfg.faixas.includes(o.idp==null ? "sem" : faixa(o.idp)))
    // grupo vazio não restringe: é condição extra, não escopo (dito na tela)
    .filter(o => !cfg.itens.length || cfg.itens.some(it=>{
      const st = revState(o.e, it);
      return st === "Pendente" || st === "Em revisão";
    }));
  return S.sort(_EXP_ORD_DEV[cfg.ordem] || _EXP_ORD_DEV.pareto);
}

/* Resumo dos filtros para o cabeçalho do PDF. Grupo inteiro marcado não vira
   linha — dizer "todas as 8 categorias" só gasta a régua do cabeçalho. */
function _expResumoGrupo(rotulo, grupo, pares, nomeTudo){
  const marcados = _expMarcados(grupo);
  const total = _expTotal(grupo);
  if(marcados.length === total) return nomeTudo || "";
  const nomes = _expRotulos(grupo, pares);
  const prefixo = rotulo ? rotulo+": " : "";       // classes já se descrevem sozinhas
  return prefixo + (nomes.length <= 3 ? nomes.join(", ") : `${nomes.length} de ${total}`);
}

// ══ DASHBOARD ══════════════════════════════════════════════════════════════
async function exportarDashboardPDF(){
  if(_pdfIndisponivel()) return;
  const S = _expDashLista();
  if(!S.length){ toast("Nenhum equipamento corresponde aos filtros", true); return; }
  closeModal("export-dash");
  toast("Gerando relatório…");
  await PDFRep.fontePronta();

  const n = S.length, media = a => n ? Math.round(a.reduce((x,y)=>x+y,0)/n) : 0;
  const iceAvg = media(S.map(o=>o.s.ice)), cadAvg = media(S.map(o=>o.s.cad)),
        regAvg = media(S.map(o=>o.s.reg)), docAvg = media(S.map(o=>o.s.doc));
  const cnt = {completo:0, parcial:0, inicial:0};
  S.forEach(o => cnt[faixa(o.s.ice)]++);

  // categorias — mesma paleta do donut da tela, agrupando a cauda
  const porCat = {};
  S.forEach(o=>{ const c = o.e.categoria || "Sem categoria"; porCat[c] = (porCat[c]||0)+1; });
  const cats = _pdfTopN(porCat, 6, "Outras categorias");
  const catCores = cats.map((c,i)=>_PDF_PALETA_CAT[i%_PDF_PALETA_CAT.length]);

  // lacunas — a lista vem do servidor, igual ao gráfico da tela
  const gaps = {};
  S.forEach(o=>{
    (o.s.lacunas||[]).forEach(l=>{ gaps[l] = (gaps[l]||0)+1; });
    if(o.s.docs_faltando) gaps[LABEL_DOC_FALTANDO] = (gaps[LABEL_DOC_FALTANDO]||0)+o.s.docs_faltando;
  });
  const topGaps = Object.entries(gaps).sort((a,b)=>b[1]-a[1]).slice(0,6);
  const pts = (EVOL||[]).slice(-60);

  const F = PDFRep.CHART_FONT;
  const donutCat = await PDFRep.renderChartImage((ctx,w,h)=>({
    type:"doughnut",
    data:{labels:cats.map(c=>c[0]), datasets:[{data:cats.map(c=>c[1]),
      backgroundColor:catCores.map(c=>PDFRep.vgradFull(ctx,h,c)),
      borderWidth:0, borderRadius:14, spacing:6}]},
    options:{cutout:"78%", layout:{padding:14}, plugins:{legend:{display:false}}},
    plugins:[PDFRep.centerTextPlugin(n, n===1?"equipamento":"equipamentos")]
  }), 760, 760);

  const donutFaixa = await PDFRep.renderChartImage((ctx,w,h)=>({
    type:"doughnut",
    data:{labels:["Completo","Parcial","Inicial"], datasets:[{data:[cnt.completo,cnt.parcial,cnt.inicial],
      backgroundColor:[FCOLOR.completo,FCOLOR.parcial,FCOLOR.inicial].map(c=>PDFRep.vgradFull(ctx,h,c)),
      borderWidth:0, borderRadius:14, spacing:6}]},
    options:{cutout:"78%", layout:{padding:14}, plugins:{legend:{display:false}}},
    plugins:[PDFRep.centerTextPlugin(iceAvg+"%", "ICE médio")]
  }), 760, 760);

  const lacunasImg = topGaps.length ? await PDFRep.renderChartImage((ctx)=>({
    type:"bar",
    data:{labels:topGaps.map(g=>g[0]), datasets:[{data:topGaps.map(g=>g[1]),
      borderRadius:10, borderWidth:0, maxBarThickness:34,
      backgroundColor:PDFRep.hgrad(ctx,1600,"#a78bfa","#22d3ee")}]},
    options:{indexAxis:"y", layout:{padding:{right:70, left:8, top:8, bottom:8}},
      plugins:{legend:{display:false}},
      scales:{x:{beginAtZero:true, ticks:{display:false}, grid:{color:"rgba(167,139,250,.14)"}, border:{display:false}},
              y:{ticks:{color:"#f1f5f9", font:{size:20, family:F}}, grid:{display:false}, border:{display:false}}}},
    plugins:[PDFRep.barValueHPlugin]
  }), 1600, 354) : null;

  const evolImg = pts.length > 1 ? await PDFRep.renderChartImage((ctx)=>({
    type:"line",
    data:{labels:pts.map(p=>p.data.slice(5)), datasets:[
      {label:"ICE", data:pts.map(p=>p.ice), borderColor:"#22d3ee", backgroundColor:"rgba(34,211,238,.20)",
        fill:true, tension:.35, pointRadius:pts.length>20?0:4, borderWidth:3.5},
      {label:"IDP", data:pts.map(p=>p.idp), borderColor:"#a78bfa", fill:false,
        tension:.35, pointRadius:0, borderWidth:3, borderDash:[7,5]}]},
    options:{layout:{padding:{top:4, right:14, bottom:4, left:4}},
      plugins:{legend:{display:true, position:"top", align:"end",
        labels:{color:"#c7d2fe", font:{size:18, family:F}, boxWidth:16, usePointStyle:true, padding:12}}},
      scales:{x:{ticks:{color:"#94a3ff", font:{size:15, family:F}, maxTicksLimit:8}, grid:{display:false}, border:{display:false}},
              y:{min:0, max:100, ticks:{color:"#94a3ff", font:{size:15, family:F}, stepSize:25, callback:v=>v+"%"},
                 grid:{color:"rgba(167,139,250,.14)"}, border:{display:false}}}}
  }), 1500, 272) : null;

  const doc = PDFRep.novoDoc();
  const ch = PDFRep.chrome(doc);
  const C = ch.C, margin = ch.margin;

  const cfg = _expDashCfg();
  let y = ch.header({
    titulo: "Relatório Executivo — Equipamentos",
    sub: "Completude ICE · DocTrack Enterprise",
    filtros: [
      _expResumoGrupo("Categorias", "dash-cat", _expParesCats("dash-cat"), "Todas as categorias"),
      _expResumoGrupo("Faixa de ICE", "dash-faixa", EXP_FAIXAS, ""),
      _expResumoGrupo("ANVISA", "dash-anvisa", EXP_ANVISA, ""),
      cfg.atrasados ? "Só com documento atrasado" : "",
      cfg.semDono ? "Só sem responsável" : "",
      cfg.bloq ? "Inclui obsoletos/bloqueados" : "Só equipamentos ativos",
    ].filter(Boolean),
  });

  // ── Linha A: KPIs + duas roscas
  const gap = 4, colW = 58, rowAh = 74;
  const kpis = [
    ["Equipamentos", n, C.t1],
    ["Completo 85%+", cnt.completo, PDFRep.rgb(FCOLOR.completo)],
    ["Parcial 50-84%", cnt.parcial, PDFRep.rgb(FCOLOR.parcial)],
    ["Inicial <50%", cnt.inicial, PDFRep.rgb(FCOLOR.inicial)],
    ["ICE médio", iceAvg+"%", C.accent],
  ];
  const kh = (rowAh - gap*(kpis.length-1))/kpis.length;
  kpis.forEach(([rot,valor,cor],i)=> ch.kpiCard(margin, y+i*(kh+gap), colW, kh, rot, valor, cor));

  const donW = (ch.larguraUtil - colW - gap*2)/2;
  const d1x = margin+colW+gap, d2x = d1x+donW+gap;
  ch.card(d1x, y, donW, rowAh); ch.cardTitle("Distribuição por categoria", d1x, y, donW);
  const legCat = ch.legendRow(cats.map((c,i)=>[PDFRep.rgb(catCores[i]), `${c[0]} (${c[1]})`]),
                              d1x+donW/2, y+rowAh-4, donW-10);

  ch.card(d2x, y, donW, rowAh); ch.cardTitle("Faixas de completude", d2x, y, donW);
  const legFaixa = ch.legendRow([[PDFRep.rgb(FCOLOR.completo), "Completo"],
                                 [PDFRep.rgb(FCOLOR.parcial),  "Parcial"],
                                 [PDFRep.rgb(FCOLOR.inicial),  "Inicial"]],
                                d2x+donW/2, y+rowAh-4, donW-10);
  // As roscas entram depois dos cartões (o retângulo do cartão é opaco) e
  // quadradas, porque o PNG é 1:1. A altura desconta o título e a legenda —
  // que pode ter duas linhas quando há muitas categorias.
  const donutBox = (leg) => rowAh - 9 - leg - 5;
  if(donutCat){ const s = donutBox(legCat);
    doc.addImage(donutCat, "PNG", d1x+(donW-s)/2, y+9, s, s); }
  if(donutFaixa){ const s = donutBox(legFaixa);
    doc.addImage(donutFaixa, "PNG", d2x+(donW-s)/2, y+9, s, s); }

  // ── Linha B: dimensões (vetorial) + lacunas (gráfico)
  y += rowAh + gap;
  const rowBh = 42, meia = (ch.larguraUtil-gap)/2;
  ch.card(margin, y, meia, rowBh); ch.cardTitle("Completude média por dimensão", margin, y, meia);
  const dims = [["Cadastro", cadAvg, C.cyan], ["Regulatório", regAvg, C.amber], ["Documental", docAvg, C.green]];
  const trackX = margin+42, trackW = meia-42-26;
  dims.forEach(([rot,v,cor],i)=>{
    const by = y+17+i*9;
    doc.setFont("helvetica","normal"); doc.setFontSize(8.5); doc.setTextColor(...C.t1);
    doc.text(rot, margin+6, by);
    ch.barra(trackX, by-2.6, trackW, 3.4, v, cor);
    doc.setFont("helvetica","bold"); doc.setFontSize(9); doc.setTextColor(...cor);
    doc.text(v+"%", margin+meia-6, by, {align:"right"});
  });

  const b2x = margin+meia+gap;
  ch.card(b2x, y, meia, rowBh); ch.cardTitle("Lacunas mais comuns", b2x, y, meia);
  if(lacunasImg) doc.addImage(lacunasImg, "PNG", b2x+4, y+10, meia-8, rowBh-14);
  else {
    doc.setFont("helvetica","normal"); doc.setFontSize(9); doc.setTextColor(...C.tmut);
    doc.text("Nenhuma lacuna de cadastro registrada.", b2x+meia/2, y+rowBh/2+3, {align:"center"});
  }

  // ── Linha C: evolução + risco
  y += rowBh + gap;
  const rowCh = ch.pageH - ch.rodape - y;
  const evolW = 157, riscoW = ch.larguraUtil - evolW - gap;
  ch.card(margin, y, evolW, rowCh); ch.cardTitle("Evolução do ICE e do IDP médios", margin, y, evolW);
  if(evolImg) doc.addImage(evolImg, "PNG", margin+4, y+10, evolW-8, rowCh-14);
  else {
    doc.setFont("helvetica","normal"); doc.setFontSize(9); doc.setTextColor(...C.tmut);
    doc.text("A série começa na primeira foto diária — ainda sem histórico para a curva.",
             margin+evolW/2, y+rowCh/2+3, {align:"center"});
  }

  const cx2 = margin+evolW+gap;
  ch.card(cx2, y, riscoW, rowCh); ch.cardTitle("Risco documental e regulatório", cx2, y, riscoW);
  riscoLinhas(S).forEach(([rot,v,cor,sub],i)=>{
    const by = y+14+i*8.2;
    doc.setFont("helvetica","normal"); doc.setFontSize(8.5); doc.setTextColor(...C.t1);
    doc.text(ch.corta(rot, riscoW-26), cx2+6, by);
    doc.setFont("helvetica","bold"); doc.setFontSize(9.5);
    doc.setTextColor(...(v ? PDFRep.rgb(cor) : C.tmut));
    doc.text(String(v), cx2+riscoW-6, by, {align:"right"});
    if(sub){
      doc.setFont("helvetica","normal"); doc.setFontSize(6.2); doc.setTextColor(...C.tmut);
      doc.text(ch.corta(sub, riscoW-24), cx2+6, by+3.2);
    }
  });

  // ── Página 2+: worklist completa (a tela mostra só o topo 10).
  // S já vem na ordem escolhida no modal — não reordenar aqui.
  const ORDEM_LEGENDA = {criticos:"mais críticos primeiro", ice:"menor ICE primeiro",
                         "ice-desc":"maior ICE primeiro", nome:"em ordem alfabética"};
  const titulo2 = "Completude por equipamento — " + (ORDEM_LEGENDA[cfg.ordem] || "");
  const cols = [
    {h:"Equipamento", w:62}, {h:"SKU", w:24}, {h:"Categoria", w:32},
    {h:"Cad.", w:18, align:"right"}, {h:"Reg.", w:20, align:"right"},
    {h:"Doc.", w:22, align:"right"}, {h:"ICE", w:16, align:"right"},
    {h:"Atras.", w:18, align:"right"}, {h:"ANVISA", w:26}, {h:"Responsável", w:35},
  ];
  const pct = v => ({v:v+"%", cor:PDFRep.rgb(FCOLOR[faixa(v)]), align:"right"});
  ch.tabela({
    y: ch.novaPagina(titulo2), cols, tituloContinuacao: titulo2,
    rows: S.map(o=>{
      const s = o.s, e = o.e;
      const resp = (e.responsavel||"").trim() || (s.responsaveis||[])[0] || "";
      return [
        {v:e.nome, cor:C.t1, negrito:true},
        e.sku, e.categoria,
        pct(s.cad), pct(s.reg), pct(s.doc),
        {v:s.ice+"%", cor:PDFRep.rgb(FCOLOR[faixa(s.ice)]), negrito:true, align:"right"},
        s.docs_atrasados ? {v:String(s.docs_atrasados), cor:C.red, negrito:true, align:"right"}
                         : {v:"—", align:"right"},
        _pdfRegCelula(s),
        resp ? {v:resp} : {v:"sem dono", cor:C.slate},
      ];
    }),
  });

  ch.footer("DocTrack Enterprise — Relatório de Equipamentos (ICE)");
  doc.save("DocTrack_Equipamentos_Dashboard.pdf");
  toast("Relatório gerado");
}

/* Situação do registro ANVISA na tabela — os quatro estados que o servidor
   devolve em reg_estado. */
function _pdfRegCelula(s){
  const C = PDFRep.C;
  if(s.reg_estado === "vencido")  return {v:"Vencida", cor:C.red, negrito:true};
  if(s.reg_estado === "vencendo") return {v:(s.reg_dias!=null?`Vence em ${s.reg_dias}d`:"Vencendo"), cor:C.amber, negrito:true};
  if(s.reg_estado === "ok")       return {v:"Vigente", cor:C.green};
  return {v:"Sem data", cor:C.slate};
}

// ══ DESENVOLVIMENTO (IDP) ══════════════════════════════════════════════════
async function exportarDevPDF(){
  if(_pdfIndisponivel()) return;
  const S = _expDevLista();
  if(!S.length){ toast("Nenhum equipamento corresponde aos filtros", true); return; }
  closeModal("export-dev");
  toast("Gerando relatório…");
  await PDFRep.fontePronta();

  const comIdp = S.filter(o=>o.idp != null);
  const media = comIdp.length ? Math.round(comIdp.reduce((x,o)=>x+o.idp,0)/comIdp.length) : 0;
  const cnt = {completo:0, parcial:0, inicial:0};
  comIdp.forEach(o=>cnt[faixa(o.idp)]++);
  const classeApend = S.filter(o=>(o.e.pareto_classe||"")==="A" && o.idp!=null && o.idp<85).length;

  // Situação item a item: as 6 revisões × os 4 estados possíveis
  const porItem = DEV_ITENS.map(it=>{
    const c = {"Revisado":0, "Em revisão":0, "Pendente":0, "N/A":0};
    S.forEach(o=>{ const st = revState(o.e, it); if(c[st] !== undefined) c[st]++; });
    const avaliados = S.length - c["N/A"];
    return {item:it, rotulo:DEV_ITEM_LABEL[it], c,
            pendentes:c["Pendente"]+c["Em revisão"],
            pctRev: avaliados ? Math.round(c["Revisado"]/avaliados*100) : 0};
  });
  const pendTotal = porItem.reduce((t,i)=>t+i.pendentes, 0);

  const classesLbl = ["A","B","C","Sem classe"];
  // A, B e C repetem as cores dos selos .abc-* da tela. "Sem classe" recebe o
  // violeta do módulo: no cinza do selo C ficavam indistinguíveis na rosca.
  const classeCor = {"A":"#10b981", "B":"#f59e0b", "C":"#64748b", "Sem classe":"#a78bfa"};
  const porClasse = classesLbl.map(c=>{
    const chave = c==="Sem classe" ? "" : c;
    const grp = comIdp.filter(o=>(o.e.pareto_classe||"")===chave);
    return {total:S.filter(o=>(o.e.pareto_classe||"")===chave).length,
            completo:grp.filter(o=>o.idp>=85).length,
            parcial: grp.filter(o=>o.idp>=50 && o.idp<85).length,
            inicial: grp.filter(o=>o.idp<50).length};
  });

  const F = PDFRep.CHART_FONT;
  const donutIdp = await PDFRep.renderChartImage((ctx,w,h)=>({
    type:"doughnut",
    data:{labels:["Completo","Parcial","Inicial"], datasets:[{data:[cnt.completo,cnt.parcial,cnt.inicial],
      backgroundColor:[FCOLOR.completo,FCOLOR.parcial,FCOLOR.inicial].map(c=>PDFRep.vgradFull(ctx,h,c)),
      borderWidth:0, borderRadius:14, spacing:6}]},
    options:{cutout:"78%", layout:{padding:14}, plugins:{legend:{display:false}}},
    plugins:[PDFRep.centerTextPlugin(media+"%", "IDP médio")]
  }), 760, 760);

  const donutClasse = await PDFRep.renderChartImage((ctx,w,h)=>({
    type:"doughnut",
    data:{labels:classesLbl, datasets:[{data:porClasse.map(p=>p.total),
      backgroundColor:classesLbl.map(c=>PDFRep.vgradFull(ctx,h,classeCor[c])),
      borderWidth:0, borderRadius:14, spacing:6}]},
    options:{cutout:"78%", layout:{padding:14}, plugins:{legend:{display:false}}},
    plugins:[PDFRep.centerTextPlugin(S.length, "no Pareto")]
  }), 760, 760);

  // As fontes são grandes porque o canvas de 1600px é reduzido a ~127mm no
  // papel: com os 16px do gráfico da tela os rótulos saíam em ~4pt, ilegíveis.
  const classeImg = await PDFRep.renderChartImage((ctx)=>({
    type:"bar",
    data:{labels:classesLbl, datasets:[
      {label:"Completo", data:porClasse.map(p=>p.completo), backgroundColor:FCOLOR.completo, borderRadius:6, stack:"s", maxBarThickness:120},
      {label:"Parcial",  data:porClasse.map(p=>p.parcial),  backgroundColor:FCOLOR.parcial,  borderRadius:6, stack:"s", maxBarThickness:120},
      {label:"Inicial",  data:porClasse.map(p=>p.inicial),  backgroundColor:FCOLOR.inicial,  borderRadius:6, stack:"s", maxBarThickness:120}]},
    options:{layout:{padding:{top:8, right:14, bottom:2, left:6}}, plugins:{legend:{display:false}},
      scales:{x:{stacked:true, ticks:{color:"#f1f5f9", font:{size:26, family:F}}, grid:{display:false}, border:{display:false}},
              y:{stacked:true, ticks:{color:"#c7d2fe", font:{size:24, family:F}, precision:0, maxTicksLimit:5},
                 grid:{color:"rgba(167,139,250,.16)"}, border:{display:false}}}}
  }), 1600, 340);

  const pendOrd = [...porItem].sort((a,b)=>b.pendentes-a.pendentes);
  const itensImg = await PDFRep.renderChartImage((ctx)=>({
    type:"bar",
    data:{labels:pendOrd.map(i=>i.rotulo), datasets:[{data:pendOrd.map(i=>i.pendentes),
      borderRadius:10, borderWidth:0, maxBarThickness:34,
      backgroundColor:PDFRep.hgrad(ctx,1600,"#a78bfa","#f43f5e")}]},
    options:{indexAxis:"y", layout:{padding:{right:70, left:8, top:8, bottom:8}},
      plugins:{legend:{display:false}},
      scales:{x:{beginAtZero:true, ticks:{display:false}, grid:{color:"rgba(167,139,250,.14)"}, border:{display:false}},
              y:{ticks:{color:"#f1f5f9", font:{size:20, family:F}}, grid:{display:false}, border:{display:false}}}},
    plugins:[PDFRep.barValueHPlugin]
  }), 1600, 354);

  const doc = PDFRep.novoDoc();
  const ch = PDFRep.chrome(doc);
  const C = ch.C, margin = ch.margin;

  const cfgDev = _expDevCfg();
  let y = ch.header({
    titulo: "Índice de Desenvolvimento de Produto",
    sub: "6 revisões por equipamento · prioridade Pareto/ABC",
    filtros: [
      // os rótulos já dizem "Classe A"/"Sem classe": prefixar daria "Classe: Classe A"
      _expResumoGrupo("", "dev-classe", EXP_CLASSES, "Todas as classes"),
      _expResumoGrupo("Categorias", "dev-cat", _expParesCats("dev-cat"), "Todas as categorias"),
      _expResumoGrupo("Faixa de IDP", "dev-faixa",
                      EXP_FAIXAS.concat([["sem","Sem avaliação"]]), ""),
      cfgDev.itens.length
        ? "Pendência em: " + cfgDev.itens.map(it=>DEV_ITEM_LABEL[it]).join(", ") : "",
      cfgDev.bloq ? "Inclui obsoletos/bloqueados" : "Só equipamentos ativos",
    ].filter(Boolean),
  });

  // ── Linha A: KPIs + duas roscas
  const gap = 4, colW = 58, rowAh = 74;
  const kpis = [
    ["Equipamentos", S.length, C.t1],
    ["Avaliados", comIdp.length, C.accent],
    ["IDP médio", media+"%", C.accent],
    ["Classe A incompletos", classeApend, classeApend ? PDFRep.rgb(FCOLOR.inicial) : PDFRep.rgb(FCOLOR.completo)],
    ["Revisões pendentes", pendTotal, pendTotal ? C.amber : PDFRep.rgb(FCOLOR.completo)],
  ];
  const kh = (rowAh - gap*(kpis.length-1))/kpis.length;
  kpis.forEach(([rot,valor,cor],i)=> ch.kpiCard(margin, y+i*(kh+gap), colW, kh, rot, valor, cor));

  const donW = (ch.larguraUtil - colW - gap*2)/2;
  const d1x = margin+colW+gap, d2x = d1x+donW+gap;
  ch.card(d1x, y, donW, rowAh); ch.cardTitle("Faixas de IDP (avaliados)", d1x, y, donW);
  const legIdp = ch.legendRow([[PDFRep.rgb(FCOLOR.completo), "Completo"],
                               [PDFRep.rgb(FCOLOR.parcial),  "Parcial"],
                               [PDFRep.rgb(FCOLOR.inicial),  "Inicial"]],
                              d1x+donW/2, y+rowAh-4, donW-10);
  ch.card(d2x, y, donW, rowAh); ch.cardTitle("Distribuição por classe ABC", d2x, y, donW);
  const legClasse = ch.legendRow(classesLbl.map(c=>[PDFRep.rgb(classeCor[c]), c]),
                                 d2x+donW/2, y+rowAh-4, donW-10);
  const donutBox = (leg) => rowAh - 9 - leg - 5;
  if(donutIdp){ const s = donutBox(legIdp);
    doc.addImage(donutIdp, "PNG", d1x+(donW-s)/2, y+9, s, s); }
  if(donutClasse){ const s = donutBox(legClasse);
    doc.addImage(donutClasse, "PNG", d2x+(donW-s)/2, y+9, s, s); }

  // ── Linha B: completude por classe + revisões mais pendentes
  y += rowAh + gap;
  const rowBh = 42, meia = (ch.larguraUtil-gap)/2;
  ch.card(margin, y, meia, rowBh); ch.cardTitle("Completude por classe ABC", margin, y, meia);
  const legClasseBar = ch.legendRow([[PDFRep.rgb(FCOLOR.completo), "Completo"],
                                     [PDFRep.rgb(FCOLOR.parcial),  "Parcial"],
                                     [PDFRep.rgb(FCOLOR.inicial),  "Inicial"]],
                                    margin+meia/2, y+rowBh-3.5, meia-10);
  // -3 extra: sem folga, os rótulos A/B/C do eixo encostavam na legenda.
  if(classeImg) doc.addImage(classeImg, "PNG", margin+4, y+10, meia-8, rowBh-14-legClasseBar);

  const b2x = margin+meia+gap;
  ch.card(b2x, y, meia, rowBh); ch.cardTitle("Revisões mais pendentes", b2x, y, meia);
  if(itensImg) doc.addImage(itensImg, "PNG", b2x+4, y+10, meia-8, rowBh-14);

  // ── Linha C: as 6 revisões, estado a estado (vetorial)
  y += rowBh + gap;
  const rowCh = ch.pageH - ch.rodape - y;
  ch.card(margin, y, ch.larguraUtil, rowCh);
  ch.cardTitle("Situação das 6 revisões", margin, y, ch.larguraUtil);
  const X = {rot:margin+6, rev:102, emrev:136, pend:168, na:194, barra:206, pct:margin+ch.larguraUtil-6};
  const larguraBarra = X.pct - 14 - X.barra;
  doc.setFont("helvetica","bold"); doc.setFontSize(7); doc.setTextColor(...C.accent);
  doc.text("REVISÃO", X.rot, y+13);
  doc.text("REVISADO", X.rev, y+13, {align:"right"});
  doc.text("EM REVISÃO", X.emrev, y+13, {align:"right"});
  doc.text("PENDENTE", X.pend, y+13, {align:"right"});
  doc.text("N/A", X.na, y+13, {align:"right"});
  doc.text("% REVISADO", X.pct, y+13, {align:"right"});
  porItem.forEach((it,i)=>{
    const by = y+18.7+i*3.9;
    doc.setFont("helvetica","bold"); doc.setFontSize(7.5); doc.setTextColor(...C.t1);
    doc.text(it.rotulo, X.rot, by);
    doc.setFont("helvetica","normal");
    const num = (v, x, cor) => { doc.setTextColor(...cor); doc.text(String(v), x, by, {align:"right"}); };
    num(it.c["Revisado"],   X.rev,   PDFRep.rgb(EST_COR["Revisado"]));
    num(it.c["Em revisão"], X.emrev, PDFRep.rgb(EST_COR["Em revisão"]));
    num(it.c["Pendente"],   X.pend,  PDFRep.rgb(EST_COR["Pendente"]));
    num(it.c["N/A"],        X.na,    C.slate);
    ch.barra(X.barra, by-2.3, larguraBarra, 2.8, it.pctRev, PDFRep.rgb(FCOLOR[faixa(it.pctRev)]));
    doc.setFont("helvetica","bold"); doc.setTextColor(...PDFRep.rgb(FCOLOR[faixa(it.pctRev)]));
    doc.text(it.pctRev+"%", X.pct, by, {align:"right"});
  });

  // ── Página 2+: a matriz, na ordem escolhida no modal
  const ORDEM_LEGENDA = {pareto:"prioridade por Pareto", idp:"menor IDP primeiro",
                         saidas:"mais saídas primeiro", nome:"em ordem alfabética"};
  const titulo2 = "Matriz de revisões — " + (ORDEM_LEGENDA[cfgDev.ordem] || "");
  const cols = [
    {h:"Equipamento", w:61}, {h:"SKU", w:24}, {h:"Classe", w:16},
    {h:"Saídas", w:18, align:"right"},
    {h:"Cadastro", w:23}, {h:"Estrutura", w:23}, {h:"IT", w:23},
    {h:"Checklists", w:23}, {h:"Manual", w:23}, {h:"Descritivo", w:23},
    {h:"IDP", w:16, align:"right"},
  ];
  const celEstado = (e, item) => {
    const st = revState(e, item);
    return {v:st, cor:PDFRep.rgb(EST_COR[st]||"#64748b"), negrito:st!=="N/A"};
  };
  ch.tabela({
    y: ch.novaPagina(titulo2), cols, tituloContinuacao: titulo2,
    rows: S.map(o=>{
      const e = o.e, classe = e.pareto_classe||"";
      return [
        {v:e.nome, cor:C.t1, negrito:true},
        e.sku,
        classe ? {v:classe, cor:PDFRep.rgb(classeCor[classe]||"#94a3b8"), negrito:true} : {v:"—"},
        {v:e.qtd_saidas || "—", align:"right"},
        ...DEV_ITENS.map(it=>celEstado(e, it)),
        o.idp==null ? {v:"—", align:"right"}
                    : {v:o.idp+"%", cor:PDFRep.rgb(FCOLOR[faixa(o.idp)]), negrito:true, align:"right"},
      ];
    }),
  });

  ch.footer("DocTrack Enterprise — Relatório de Desenvolvimento (IDP)");
  doc.save("DocTrack_Equipamentos_IDP.pdf");
  toast("Relatório gerado");
}
