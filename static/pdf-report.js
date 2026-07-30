/* pdf-report.js — moldura comum dos relatórios PDF (A4 paisagem, tema escuro).
 *
 * O relatório de Documentos (app.js) e o de Projetos (entregaveis.js) nasceram
 * cada um com a sua cópia destes helpers: dois `_renderChartImage`, dois
 * `_centerTextPlugin`, dois `legendRow` — e as cópias já divergiram (a de
 * Projetos reduz a fonte da legenda para caber no cartão, a de Documentos
 * deixa vazar). Os relatórios de Equipamentos usam este arquivo em vez de abrir
 * a terceira cópia; migrar os dois antigos para cá continua pendente.
 *
 * Tudo mora no namespace PDFRep de propósito: carregar este arquivo numa página
 * que ainda tem as cópias locais (dashboard.html, entregaveis.html) não colide
 * com elas.
 *
 * Depende de jsPDF (/static/vendor/jspdf.umd.min.js) e, só para os gráficos,
 * de Chart.js. Sem jsPDF nada aqui é chamado — ver temJsPDF().
 */
window.PDFRep = (function(){

  const CHART_FONT = "'Inter', system-ui, sans-serif";

  // Paleta do papel. O relatório é sempre escuro, inclusive com a tela no tema
  // claro: é o mesmo layout impresso pelos módulos Documentos e Projetos.
  const C = {
    bg:[13,16,32], card:[26,31,58], rowAlt:[20,24,46], border:[42,54,98], track:[35,42,78],
    t1:[241,245,249], t2:[199,210,254], tmut:[148,163,255],
    accent:[34,211,238], cyan:[34,211,238], green:[16,185,129], amber:[245,158,11],
    red:[244,63,94], violet:[167,139,250], slate:[100,116,139], blue:[59,130,246],
  };

  /* jsPDF é carregado só nas páginas que exportam. Quem chama avisa o usuário —
     o resto da tela funciona sem ele. */
  function temJsPDF(){ return !!(window.jspdf && window.jspdf.jsPDF); }

  function rgb(hex){
    const n = parseInt(String(hex).replace('#',''), 16);
    return [(n>>16)&255, (n>>8)&255, n&255];
  }
  function darken(hex, f){
    const [r,g,b] = rgb(hex);
    return `rgb(${Math.round(r*(1-f))},${Math.round(g*(1-f))},${Math.round(b*(1-f))})`;
  }
  /* Mesmo gradiente das roscas da tela: cor cheia no topo, mais escura embaixo. */
  function vgradFull(ctx, h, hex){
    const g = ctx.createLinearGradient(0,0,0,h);
    g.addColorStop(0, hex); g.addColorStop(1, darken(hex, 0.5));
    return g;
  }
  function hgrad(ctx, w, c1, c2){
    const g = ctx.createLinearGradient(0,0,w,0);
    g.addColorStop(0, c1); g.addColorStop(1, c2);
    return g;
  }

  /* Número grande + rótulo no vazio da rosca. */
  function centerTextPlugin(grande, pequeno){
    return { id:'centerText', afterDraw(chart){
      const a = chart.chartArea; if(!a) return;
      const ctx = chart.ctx;
      const cx = (a.left+a.right)/2, cy = (a.top+a.bottom)/2;
      ctx.save(); ctx.textAlign='center'; ctx.textBaseline='middle';
      ctx.fillStyle='#f1f5f9'; ctx.font='bold 60px '+CHART_FONT;
      ctx.fillText(String(grande), cx, cy-6);
      ctx.fillStyle='#94a3ff'; ctx.font='600 22px '+CHART_FONT;
      ctx.fillText(pequeno, cx, cy+32);
      ctx.restore();
    }};
  }

  /* Valor ao final de cada barra horizontal. */
  const barValueHPlugin = { id:'barValuesH', afterDatasetsDraw(chart){
    const ctx = chart.ctx, meta = chart.getDatasetMeta(0);
    chart.data.datasets[0].data.forEach((v,i)=>{
      const el = meta.data[i]; if(!el) return;
      ctx.save(); ctx.fillStyle='#f1f5f9'; ctx.font='bold 26px '+CHART_FONT;
      ctx.textAlign='left'; ctx.textBaseline='middle';
      ctx.fillText(String(v), el.x+10, el.y); ctx.restore();
    });
  }};

  /* Rasteriza um gráfico Chart.js num canvas fora da tela e devolve o PNG.
     O canvas é dimensionado na proporção da caixa que vai receber a imagem no
     PDF — é o que impede o texto do gráfico de esticar. */
  function renderChartImage(build, wpx, hpx){
    return new Promise(resolve=>{
      if(typeof Chart === 'undefined'){ resolve(null); return; }
      const canvas = document.createElement('canvas');
      canvas.width = wpx; canvas.height = hpx;
      canvas.style.position='fixed'; canvas.style.left='-10000px'; canvas.style.top='0';
      document.body.appendChild(canvas);
      const ctx = canvas.getContext('2d');
      const cfg = (typeof build === 'function') ? build(ctx, wpx, hpx) : build;
      cfg.options = cfg.options || {};
      cfg.options.responsive = false;
      cfg.options.animation = false;
      cfg.options.maintainAspectRatio = false;
      let chart;
      try{ chart = new Chart(ctx, cfg); }
      catch(e){ canvas.remove(); resolve(null); return; }
      // Com animation:false o Chart.js já desenhou, mas esperar um quadro deixa
      // o resultado consistente entre navegadores. requestAnimationFrame sozinho
      // não serve: em aba de fundo ele é suspenso e a exportação ficava
      // pendurada para sempre se o usuário trocasse de aba no meio.
      let feito = false;
      const capturar = () => {
        if(feito) return;
        feito = true;
        let url = null;
        try{ url = chart.canvas.toDataURL('image/png'); }catch(e){}
        try{ chart.destroy(); }catch(e){}
        canvas.remove();
        resolve(url);
      };
      requestAnimationFrame(capturar);
      setTimeout(capturar, 60);
    });
  }

  /* A fonte da plataforma tem de estar carregada antes de rasterizar, senão o
     gráfico sai com a fonte de fallback do navegador. */
  async function fontePronta(){
    try{
      await Promise.all([document.fonts.load("700 60px Inter"),
                         document.fonts.load("600 22px Inter")]);
      await document.fonts.ready;
    }catch(e){ /* sem Font Loading API o gráfico sai com o fallback */ }
  }

  function novoDoc(){
    const { jsPDF } = window.jspdf;
    return new jsPDF({orientation:'landscape', unit:'mm', format:'a4'});
  }

  function agora(){
    return new Date().toLocaleString('pt-BR',
      {day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit'});
  }

  /* Nome do arquivo com data, no mesmo formato dos exports do servidor
     (`equipamentos_20260730.csv`). Sem a data, gerar o relatório duas vezes
     sobrescrevia o anterior na pasta de Downloads. */
  function nomeArquivo(base){
    const d = new Date();
    const p = n => String(n).padStart(2, '0');
    return `${base}_${d.getFullYear()}${p(d.getMonth()+1)}${p(d.getDate())}.pdf`;
  }

  /* ── A moldura de um documento ─────────────────────────────────────────────
     Recebe o doc do jsPDF e devolve os desenhos que todo relatório repete:
     fundo, cartão, título de cartão, legenda, barra de progresso, tabela
     paginada e rodapé. */
  function chrome(doc){
    const pageW = doc.internal.pageSize.getWidth();
    const pageH = doc.internal.pageSize.getHeight();
    const margin = 12;
    const larguraUtil = pageW - margin*2;
    const RODAPE = 11;            // faixa reservada ao rodapé

    /* Corta com "…" o que não cabe em maxW. Mede com a fonte corrente, então
       precisa ser chamado depois de setFont/setFontSize. */
    function corta(txt, maxW){
      let v = txt == null ? '' : String(txt);
      if(doc.getTextWidth(v) <= maxW) return v;
      while(v.length > 1 && doc.getTextWidth(v+'…') > maxW) v = v.slice(0,-1);
      return v+'…';
    }

    function paintBg(){
      doc.setFillColor(...C.bg);
      doc.rect(0, 0, pageW, pageH, 'F');
    }
    function card(x, y, w, h){
      doc.setFillColor(...C.card); doc.setDrawColor(...C.border); doc.setLineWidth(0.3);
      doc.roundedRect(x, y, w, h, 2.5, 2.5, 'FD');
    }
    function cardTitle(txt, x, y, w){
      doc.setFont('helvetica','bold'); doc.setFontSize(8.5); doc.setTextColor(...C.accent);
      doc.text(corta(txt.toUpperCase(), w-8), x+w/2, y+6.5, {align:'center'});
    }

    /* Cartão de KPI: rótulo à esquerda, valor à direita, uma linha só. */
    function kpiCard(x, y, w, h, rotulo, valor, cor){
      card(x, y, w, h);
      doc.setFont('helvetica','normal'); doc.setFontSize(8); doc.setTextColor(...C.tmut);
      doc.text(corta(rotulo, w-30), x+5, y+h/2+1);
      doc.setFont('helvetica','bold'); doc.setFontSize(h>=14?16:13); doc.setTextColor(...(cor||C.t1));
      doc.text(String(valor), x+w-5, y+h/2+1.5, {align:'right'});
    }

    /* Legenda vetorial (nítida, ao contrário da legenda rasterizada do gráfico).
       Quebra em linhas para caber em maxW e só então reduz a fonte: com 8
       categorias uma única linha vazava o cartão e invadia os cartões vizinhos.
       Cresce para CIMA a partir de yBase (a última linha fica em yBase) e
       devolve a altura ocupada, para quem chama descontar da caixa da imagem. */
    function legendRow(items, cx, yBase, maxW, maxLinhas){
      const limite = maxLinhas || 2;
      const larguraMax = maxW || larguraUtil;
      let fs = 8.5, itemGap = 8, dotGap = 2.2, r = 1.5;

      const medir = () => {
        doc.setFontSize(fs);
        return items.map(([,rot])=>{
          const texto = corta(rot, larguraMax - r*2 - dotGap);
          return { texto, w: r*2 + dotGap + doc.getTextWidth(texto) };
        });
      };
      const empacotar = (medidas) => {
        const linhas = [];
        let atual = [], largura = 0;
        medidas.forEach((m,i)=>{
          if(atual.length && largura + itemGap + m.w > larguraMax){
            linhas.push({itens:atual, largura}); atual = []; largura = 0;
          }
          largura += (atual.length ? itemGap : 0) + m.w;
          atual.push({cor:items[i][0], texto:m.texto, w:m.w});
        });
        if(atual.length) linhas.push({itens:atual, largura});
        return linhas;
      };

      doc.setFont('helvetica','normal');
      let linhas = empacotar(medir());
      while(linhas.length > limite && fs > 5.5){
        fs -= 0.5;
        itemGap = Math.max(3, itemGap-0.6); dotGap = Math.max(1.4, dotGap-0.15); r = Math.max(1, r-0.08);
        linhas = empacotar(medir());
      }

      const alturaLinha = fs*0.3528 + 1.3;
      const topo = yBase - (linhas.length-1)*alturaLinha;
      doc.setFontSize(fs);
      linhas.forEach((linha,li)=>{
        const y = topo + li*alturaLinha;
        let x = cx - linha.largura/2;
        linha.itens.forEach(item=>{
          doc.setFillColor(...item.cor); doc.circle(x+r, y-1.1, r, 'F');
          doc.setTextColor(...C.t1); doc.text(item.texto, x+r*2+dotGap, y);
          x += item.w + itemGap;
        });
      });
      doc.setFontSize(8.5);
      return (linhas.length-1)*alturaLinha + fs*0.3528 + 1.2;
    }

    /* Barra de progresso — a mesma leitura do .prog-track da tela. */
    function barra(x, y, w, h, pct, cor){
      doc.setFillColor(...C.track);
      doc.roundedRect(x, y, w, h, h/2, h/2, 'F');
      const cheio = Math.max(0, Math.min(100, pct||0))/100 * w;
      if(cheio <= 0.2) return;
      const r = Math.min(h/2, cheio/2);
      doc.setFillColor(...cor);
      doc.roundedRect(x, y, cheio, h, r, r, 'F');
    }

    /* Cabeçalho da primeira página. Devolve o y onde o conteúdo começa.
       Os filtros são empacotados em até duas linhas alinhadas à direita: com
       recorte por faixa, ANVISA e revisão pendente, uma linha só cortava a
       descrição no meio e o leitor não sabia o que estava vendo. */
    function header(opts){
      paintBg();
      doc.setFont('helvetica','bold'); doc.setFontSize(19); doc.setTextColor(...C.t1);
      doc.text(opts.titulo, margin, 18);
      doc.setFont('helvetica','bold'); doc.setFontSize(10); doc.setTextColor(...C.accent);
      doc.text(opts.sub || 'DocTrack Enterprise', margin, 25);

      doc.setFont('helvetica','normal'); doc.setFontSize(8); doc.setTextColor(...C.tmut);
      doc.text('Gerado em '+agora(), pageW-margin, 14, {align:'right'});

      // larguraUtil-80 deixa livre a faixa que o título e o subtítulo ocupam
      const maxW = larguraUtil - 80, SEP = '   ·   ';
      const partes = (opts.filtros && opts.filtros.length) ? opts.filtros.slice() : ['Sem filtros'];
      const linhas = [];
      partes.forEach(parte=>{
        const ultima = linhas.length ? linhas[linhas.length-1] : null;
        const juntas = ultima ? ultima + SEP + parte : parte;
        if(ultima && doc.getTextWidth(juntas) <= maxW) linhas[linhas.length-1] = juntas;
        else if(linhas.length < 2) linhas.push(parte);
        else linhas[1] = linhas[1] + SEP + parte;        // sobra vai para a 2ª e é cortada
      });
      linhas.forEach((linha,i)=>{
        doc.text(corta(linha, maxW), pageW-margin, (linhas.length===1 ? 21 : 19.5+i*5), {align:'right'});
      });

      doc.setDrawColor(...C.accent); doc.setLineWidth(0.5);
      doc.line(margin, 29, pageW-margin, 29);
      return 34;
    }

    /* Página nova com título de seção opcional. Devolve o y de partida. */
    function novaPagina(titulo){
      doc.addPage(); paintBg();
      let y = margin+4;
      if(titulo){
        doc.setFont('helvetica','bold'); doc.setFontSize(14); doc.setTextColor(...C.t1);
        doc.text(titulo, margin, y+4);
        y += 11;
      }
      return y;
    }

    /* Tabela paginada. Repete o cabeçalho (e o título, se vier) a cada quebra.
         cols: [{h, w, align}]
         rows: [[celula, …]] — célula é string ou {v, cor, negrito, align}
       Devolve o y depois da última linha. */
    function tabela(opts){
      const cols = opts.cols || [];
      const rowH = opts.rowH || 7.2, headerH = 9;
      let y = opts.y;

      const cabecalho = () => {
        doc.setFillColor(...C.card); doc.rect(margin, y, larguraUtil, headerH, 'F');
        doc.setFont('helvetica','bold'); doc.setFontSize(7.5); doc.setTextColor(...C.accent);
        let cx = margin;
        cols.forEach(c=>{
          const dir = c.align === 'right';
          doc.text(corta(c.h, c.w-5), dir ? cx+c.w-3 : cx+3, y+6, dir ? {align:'right'} : undefined);
          cx += c.w;
        });
        y += headerH;
      };

      cabecalho();
      (opts.rows || []).forEach((row, i)=>{
        if(y + rowH > pageH - RODAPE){ y = novaPagina(opts.tituloContinuacao); cabecalho(); }
        if(i % 2 === 0){ doc.setFillColor(...C.rowAlt); doc.rect(margin, y, larguraUtil, rowH, 'F'); }
        doc.setDrawColor(...C.border); doc.setLineWidth(0.15);
        doc.line(margin, y+rowH, pageW-margin, y+rowH);
        let cx = margin;
        doc.setFontSize(7.5);
        row.forEach((celula, j)=>{
          const c = cols[j] || {w:20};
          const cel = (celula && typeof celula === 'object') ? celula : {v:celula};
          doc.setFont('helvetica', cel.negrito ? 'bold' : 'normal');
          doc.setTextColor(...(cel.cor || C.tmut));
          const dir = (cel.align || c.align) === 'right';
          const txt = corta(cel.v == null || cel.v === '' ? '—' : cel.v, c.w-5);
          doc.text(txt, dir ? cx+c.w-3 : cx+3, y+4.8, dir ? {align:'right'} : undefined);
          cx += c.w;
        });
        y += rowH;
      });
      return y;
    }

    /* Rodapé em todas as páginas — sempre por último, quando o total é conhecido. */
    function footer(texto){
      const total = doc.internal.getNumberOfPages();
      for(let i=1; i<=total; i++){
        doc.setPage(i);
        doc.setFont('helvetica','normal'); doc.setFontSize(7); doc.setTextColor(...C.tmut);
        doc.text(texto, margin, pageH-5);
        doc.text(`Página ${i} de ${total}`, pageW-margin, pageH-5, {align:'right'});
      }
    }

    return { doc, pageW, pageH, margin, larguraUtil, rodape:RODAPE, C,
             corta, paintBg, card, cardTitle, kpiCard, legendRow, barra,
             header, novaPagina, tabela, footer };
  }

  return { CHART_FONT, C, rgb, darken, vgradFull, hgrad,
           centerTextPlugin, barValueHPlugin, renderChartImage,
           temJsPDF, fontePronta, novoDoc, agora, nomeArquivo, chrome };
})();
