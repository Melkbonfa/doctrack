# Documentação: Geração de Relatório PDF (DocTrack v4.0)

> ⚠️ **HISTÓRICO — não descreve o código atual.** Este documento registra a
> **primeira** das três gerações do relatório PDF, baseada em `html2pdf.js`. Vieram
> depois o caminho WeasyPrint no servidor (`/api/report/pdf`, removido em jul/2026)
> e o atual, montado no navegador com **jsPDF** — veja `gerarRelatorioPDF()` em
> [`static/app.js`](../static/app.js). A função `exportKPIs()` citada abaixo **não
> existe mais**. Mantido porque o layout A4 paisagem e o racional de dimensões
> fixas continuam valendo. **Reescrever para o jsPDF está pendente.**

Este documento contém a lógica exata utilizada para a criação do relatório executivo em modo paisagem (Landscape) no DocTrack. Ele é composto por duas partes principais: a marcação HTML (que monta o layout) e a lógica em JavaScript (que coleta os dados, plota os gráficos via Chart.js e converte a tela em PDF via html2pdf.js).

---

## 1. O Contêiner HTML (dashboard.html)

O bloco abaixo deve ser inserido no final do seu `dashboard.html`. Ele possui dimensões estritas (1123px x 794px) para garantir que o tamanho A4 no modo paisagem seja perfeitamente capturado independentemente da resolução do monitor do usuário.

```html
<!-- OVERLAY DE CARREGAMENTO & CONTAINER DO RELATÓRIO PDF -->
<div id="pdf-wrapper" style="position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(15,15,40,0.98); z-index: 99999; display: none; overflow: auto; align-items: flex-start; justify-content: flex-start;">
  
  <div style="position: fixed; bottom: 30px; right: 30px; color: #22d3ee; font-size: 16px; font-weight: 600; display: flex; align-items: center; gap: 10px; background: rgba(15,15,40,0.9); padding: 12px 24px; border-radius: 8px; border: 1px solid rgba(34,211,238,0.3); z-index: 100000; box-shadow: 0 4px 15px rgba(0,0,0,0.5);">
    Gerando PDF... Aguarde.
  </div>

  <!-- PÁGINA A4 PAISAGEM EXATA EM PIXELS (1123x794) -->
  <div id="pdf-report-container" style="width: 1123px; min-width: 1123px; height: 794px; background: #0f0f28; color: #f1f5f9; font-family: 'Inter', sans-serif; padding: 30px 40px; box-sizing: border-box; position: relative; overflow: hidden; margin: 0; flex-shrink: 0;">
    
    <!-- Cabeçalho -->
    <div style="display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 2px solid rgba(34,211,238,0.2); padding-bottom: 15px; margin-bottom: 25px;">
      <div>
        <h1 style="color: #f1f5f9; margin: 0; font-size: 28px; letter-spacing: -0.5px;">Relatório Executivo de KPIs</h1>
        <h2 style="color: #22d3ee; margin: 4px 0 0; font-size: 16px; font-weight: 600;">DocTrack Enterprise v4.0</h2>
      </div>
      <div style="text-align: right;">
        <p style="color: #94a3ff; font-size: 12px; margin: 0;">Gerado em: <br><strong id="rep-date" style="color: #c4b5fd; font-family: 'JetBrains Mono', monospace; font-size: 14px;"></strong></p>
      </div>
    </div>

    <!-- Primeira Linha: Cards e Gráficos Redondos -->
    <div style="display: flex; gap: 20px; margin-bottom: 20px; height: 260px;">
      
      <!-- Visão Geral (Cards) -->
      <div style="flex: 1; display: flex; flex-direction: column; justify-content: space-between;">
        <div style="background: rgba(30,30,50,0.6); border: 1px solid rgba(167,139,250,0.3); padding: 16px; border-radius: 10px; display: flex; justify-content: space-between; align-items: center;">
          <span style="color: #94a3ff; font-size: 13px;">Total de Documentos</span>
          <strong style="color: #f1f5f9; font-size: 22px; font-family: 'JetBrains Mono', monospace;" id="rep-total"></strong>
        </div>
        <div style="background: rgba(30,30,50,0.6); border: 1px solid rgba(16,185,129,0.3); padding: 16px; border-radius: 10px; display: flex; justify-content: space-between; align-items: center;">
          <span style="color: #6ee7b7; font-size: 13px;">Finalizados</span>
          <strong style="color: #10b981; font-size: 20px; font-family: 'JetBrains Mono', monospace;" id="rep-fin"></strong>
        </div>
        <div style="background: rgba(30,30,50,0.6); border: 1px solid rgba(34,211,238,0.3); padding: 16px; border-radius: 10px; display: flex; justify-content: space-between; align-items: center;">
          <span style="color: #67e8f9; font-size: 13px;">Em Progresso</span>
          <strong style="color: #22d3ee; font-size: 20px; font-family: 'JetBrains Mono', monospace;" id="rep-prog"></strong>
        </div>
        <div style="background: rgba(30,30,50,0.6); border: 1px solid rgba(148,163,255,0.3); padding: 16px; border-radius: 10px; display: flex; justify-content: space-between; align-items: center;">
          <span style="color: #cbd5ff; font-size: 13px;">Pendentes</span>
          <strong style="color: #94a3ff; font-size: 20px; font-family: 'JetBrains Mono', monospace;" id="rep-pend"></strong>
        </div>
      </div>

      <!-- Gráfico Global -->
      <div style="flex: 1.2; background: rgba(30,30,50,0.4); border: 1px solid rgba(167,139,250,0.15); border-radius: 10px; padding: 15px; display: flex; flex-direction: column;">
        <h3 style="margin: 0 0 10px 0; color: #e879f9; font-size: 13px; text-align: center; text-transform: uppercase; letter-spacing: 1px;">Status Global</h3>
        <div style="flex: 1; position: relative; width: 100%;">
          <canvas id="rep-chart-global"></canvas>
        </div>
      </div>

      <!-- Gráfico Setor -->
      <div style="flex: 1.2; background: rgba(30,30,50,0.4); border: 1px solid rgba(167,139,250,0.15); border-radius: 10px; padding: 15px; display: flex; flex-direction: column;">
        <h3 style="margin: 0 0 10px 0; color: #22d3ee; font-size: 13px; text-align: center; text-transform: uppercase; letter-spacing: 1px;">Distribuição por Setor</h3>
        <div style="flex: 1; position: relative; width: 100%;">
          <canvas id="rep-chart-setor"></canvas>
        </div>
      </div>

    </div>

    <!-- Segunda Linha: Tabela e Gráfico de Barras -->
    <div style="display: flex; gap: 20px; height: 330px;">
      
      <!-- Tabela -->
      <div style="flex: 1; background: rgba(30,30,50,0.4); border: 1px solid rgba(167,139,250,0.15); border-radius: 10px; padding: 15px;">
        <h3 style="color: #a855f7; font-size: 14px; border-bottom: 2px solid rgba(168,85,247,0.3); padding-bottom: 8px; margin-top: 0; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 1px;">Composição por Setor</h3>
        <table style="width: 100%; border-collapse: separate; border-spacing: 0; font-size: 12px; table-layout: fixed;">
          <thead>
            <tr style="background: rgba(168,85,247,0.1);">
              <th style="padding: 10px; border-bottom: 1px solid rgba(168,85,247,0.3); color: #c4b5fd; text-align: left; border-top-left-radius: 8px; width: 40%;">Setor</th>
              <th style="padding: 10px; border-bottom: 1px solid rgba(168,85,247,0.3); color: #c4b5fd; text-align: center; width: 20%;">Docs</th>
              <th style="padding: 10px; border-bottom: 1px solid rgba(168,85,247,0.3); color: #c4b5fd; text-align: center; width: 20%;">% Total</th>
              <th style="padding: 10px; border-bottom: 1px solid rgba(168,85,247,0.3); color: #c4b5fd; text-align: center; border-top-right-radius: 8px; width: 20%;">Conc.</th>
            </tr>
          </thead>
          <tbody id="rep-table-body">
          </tbody>
        </table>
      </div>

      <!-- Gráfico Status -->
      <div style="flex: 1.5; background: rgba(30,30,50,0.4); border: 1px solid rgba(167,139,250,0.15); border-radius: 10px; padding: 15px; display: flex; flex-direction: column;">
        <h3 style="margin: 0 0 10px 0; color: #22d3ee; font-size: 13px; text-align: center; text-transform: uppercase; letter-spacing: 1px;">Detalhamento de Etapas</h3>
        <div style="flex: 1; position: relative; width: 100%;">
          <canvas id="rep-chart-status"></canvas>
        </div>
      </div>

    </div>

  </div>
</div>
```

---

## 2. A Função JavaScript (app.js)

Esta função é a responsável por dar vida ao template acima. Note as configurações de `windowWidth` e `windowHeight` injetadas no método do `html2pdf()`. Isto inibe qualquer variação gerada pelo navegador ou tela do usuário.

```javascript
function exportKPIs() {
    if(!_lastKpis) { showToast('Nenhum dado para exportar', 'error'); return; }
    
    // Mostra o container na tela para o html2canvas renderizar os dados visíveis
    const wrapper = document.getElementById('pdf-wrapper');
    wrapper.style.display = 'flex';
    document.getElementById('rep-date').textContent = new Date().toLocaleString('pt-BR');
    
    const total = _lastKpis.total || 0;
    document.getElementById('rep-total').textContent = total;
    document.getElementById('rep-fin').textContent = _lastKpis.global_counts['Finalizado'] || 0;
    document.getElementById('rep-prog').textContent = _lastKpis.global_counts['Em progresso'] || 0;
    document.getElementById('rep-pend').textContent = _lastKpis.global_counts['Pendente'] || 0;

    // Popula a Tabela Dinamicamente
    const tb = document.getElementById('rep-table-body');
    const setores = Object.keys(_lastKpis.por_setor);
    tb.innerHTML = setores.map(s => {
        const qtd = _lastKpis.por_setor[s] || 0;
        const pct = total ? Math.round(qtd / total * 100) : 0;
        const concl = _lastKpis.status_counts[s] ? (_lastKpis.status_counts[s]['Concluído'] || _lastKpis.status_counts[s]['Homologado'] || 0) : 0;
        return `<tr>
          <td style="padding: 12px; border-bottom: 1px solid rgba(168,85,247,0.3); color: #f1f5f9;">${esc(s)}</td>
          <td style="padding: 12px; border-bottom: 1px solid rgba(168,85,247,0.3); text-align: center; color: #f1f5f9;">${qtd}</td>
          <td style="padding: 12px; border-bottom: 1px solid rgba(168,85,247,0.3); text-align: center; color: #f1f5f9;">${pct}%</td>
          <td style="padding: 12px; border-bottom: 1px solid rgba(168,85,247,0.3); text-align: center; color: #10b981; font-weight: 600;">${concl}</td>
        </tr>`;
    }).join('');

    // Pausa técnica (50ms) para garantir atualização do DOM antes de injetar canvas
    setTimeout(() => {
        // Limpa instâncias anteriores para evitar vazamento de memória e sobreposições
        if(window._repCharts) window._repCharts.forEach(c => c.destroy());
        window._repCharts = [];

        // Gráfico 1: Global
        const gCtx = document.getElementById('rep-chart-global').getContext('2d');
        const ringColors=['#10b981','#22d3ee','#a855f7'];
        const gData = ['Finalizado', 'Em progresso', 'Pendente'].map(k => _lastKpis.global_counts[k] || 0);

        window._repCharts.push(new Chart(gCtx, {
            type: 'doughnut',
            data: { labels: ['Finalizado', 'Em progresso', 'Pendente'], datasets: [{ data: gData, backgroundColor: ringColors, borderColor: '#1a1d3a' }] },
            options: { responsive: true, maintainAspectRatio: false, animation: false, color: '#c4b5fd' }
        }));

        // Gráfico 2: Setor
        const sCtx = document.getElementById('rep-chart-setor').getContext('2d');
        const catLabels = Object.keys(_lastKpis.por_setor), catVals = Object.values(_lastKpis.por_setor);
        const dColors = catLabels.map(c => CAT_COLORS[c] || '#6366f1');
        
        window._repCharts.push(new Chart(sCtx, {
            type: 'doughnut',
            data: { labels: catLabels, datasets: [{ data: catVals, backgroundColor: dColors, borderColor: '#1a1d3a' }] },
            options: { responsive: true, maintainAspectRatio: false, animation: false, color: '#c4b5fd' }
        }));

        // Gráfico 3: Detalhamento de Status (Barras)
        const stCtx = document.getElementById('rep-chart-status').getContext('2d');
        const flatStatus = {};
        Object.values(_lastKpis.status_counts).forEach(sc => {
            Object.keys(sc).forEach(k => flatStatus[k] = (flatStatus[k]||0) + sc[k]);
        });
        const stLabels = Object.keys(flatStatus), stVals = Object.values(flatStatus);
        const stColors = stLabels.map(s => STATUS_PILL[s] ? (s === 'Elaborar' ? '#a855f7' : s.includes('Homologado') || s === 'Concluído' ? '#10b981' : '#22d3ee') : '#ec4899');
        
        window._repCharts.push(new Chart(stCtx, {
            type: 'bar',
            data: { labels: stLabels, datasets: [{ data: stVals, backgroundColor: stColors, borderRadius: 4 }] },
            options: { 
                indexAxis: 'y', responsive: true, maintainAspectRatio: false, animation: false, 
                plugins: { legend: { display: false } },
                scales: { 
                    x: { ticks: { color: '#94a3ff' }, grid: { color: 'rgba(167,139,250,0.1)' } },
                    y: { ticks: { color: '#94a3ff' }, grid: { display: false } }
                }
            }
        }));

        // Damos 600ms para os gráficos Chart.js finalizarem totalmente a renderização visual
        setTimeout(() => {
            const el = document.getElementById('pdf-report-container');
            
            // O Motor do PDF
            html2pdf().set({
                margin: 0,
                filename: 'DocTrack_Enterprise_KPIs.pdf',
                image: { type: 'jpeg', quality: 1 },
                html2canvas: { 
                    scale: 2,               // Qualidade (A4 em dobro)
                    useCORS: true, 
                    backgroundColor: '#0f0f28', 
                    // Âncoras vitais para evitar cortes e PDFs em branco
                    windowWidth: 1123, 
                    windowHeight: 794, 
                    width: 1123, 
                    height: 794, 
                    x: 0, 
                    y: 0, 
                    scrollX: 0, 
                    scrollY: 0 
                },
                jsPDF: { unit: 'px', format: [1123, 794], orientation: 'landscape' } // Formato Paisagem exato
            }).from(el).save().then(() => {
                // Ao final, esconde a tela de carregamento novamente
                wrapper.style.display = 'none';
                showToast('Relatório Gerado com Sucesso!', 'success');
            }).catch(err => {
                console.error("Erro fatal ao gerar o PDF: ", err);
                wrapper.style.display = 'none';
                showToast('Falha na Geração', 'error');
            });
        }, 600);
    }, 50);
}
```

---

### Dicas de Depuração Rápida (Debug)
Se você estiver corrigindo por conta própria e o PDF continuar falhando, as principais variáveis de teste são:
1. Comentar a linha final `wrapper.style.display = 'none';`. Isso permitirá inspecionar se a tabela/dados foram gerados com sucesso no DOM.
2. Garantir que a importação do script `html2pdf.bundle.min.js` e do `Chart.js` não estão sendo carregados de forma assíncrona conflitante.
3. Se a captura ficar sempre transparente/branca, alterar `html2canvas: { scrollX: window.scrollX, scrollY: window.scrollY }` em ambientes onde o scroll de tela pode estar afetando a captura.
