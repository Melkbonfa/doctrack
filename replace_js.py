import os
import re

with open('static/app.js', 'r', encoding='utf-8') as f:
    content = f.read()

start_marker = "function exportKPIs() {"
end_marker = "}\n\nasync function loadEnums(){"

new_func = """function exportKPIs() {
    if(!_lastKpis) { showToast('Nenhum dado para exportar', 'error'); return; }
    
    // Exibe a tela de carregamento e container real
    const wrapper = document.getElementById('pdf-wrapper');
    wrapper.style.display = 'flex';
    document.getElementById('rep-date').textContent = new Date().toLocaleString('pt-BR');
    
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
        const concl = _lastKpis.status_counts[s] ? (_lastKpis.status_counts[s]['Concluído'] || _lastKpis.status_counts[s]['Homologado'] || 0) : 0;
        return `<tr>
          <td style="padding: 12px; border-bottom: 1px solid rgba(168,85,247,0.3); color: #f1f5f9;">${esc(s)}</td>
          <td style="padding: 12px; border-bottom: 1px solid rgba(168,85,247,0.3); text-align: center; color: #f1f5f9;">${qtd}</td>
          <td style="padding: 12px; border-bottom: 1px solid rgba(168,85,247,0.3); text-align: center; color: #f1f5f9;">${pct}%</td>
          <td style="padding: 12px; border-bottom: 1px solid rgba(168,85,247,0.3); text-align: center; color: #10b981; font-weight: 600;">${concl}</td>
        </tr>`;
    }).join('');

    // Da um pequeno tempo para o CSS aplicar o flex no wrapper
    setTimeout(() => {
        if(window._repCharts) window._repCharts.forEach(c => c.destroy());
        window._repCharts = [];

        const gCtx = document.getElementById('rep-chart-global').getContext('2d');
        const sCtx = document.getElementById('rep-chart-setor').getContext('2d');
        const stCtx = document.getElementById('rep-chart-status').getContext('2d');
        
        const ringColors=['#10b981','#22d3ee','#a855f7'];
        const gData = ['Finalizado', 'Em progresso', 'Pendente'].map(k => _lastKpis.global_counts[k] || 0);

        window._repCharts.push(new Chart(gCtx, {
            type: 'doughnut',
            data: { labels: ['Finalizado', 'Em progresso', 'Pendente'], datasets: [{ data: gData, backgroundColor: ringColors, borderColor: '#1a1d3a' }] },
            options: { responsive: true, maintainAspectRatio: false, animation: false, color: '#c4b5fd' }
        }));

        const catLabels = Object.keys(_lastKpis.por_setor), catVals = Object.values(_lastKpis.por_setor);
        const dColors = catLabels.map(c => CAT_COLORS[c] || '#6366f1');
        window._repCharts.push(new Chart(sCtx, {
            type: 'doughnut',
            data: { labels: catLabels, datasets: [{ data: catVals, backgroundColor: dColors, borderColor: '#1a1d3a' }] },
            options: { responsive: true, maintainAspectRatio: false, animation: false, color: '#c4b5fd' }
        }));

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

        setTimeout(() => {
            const el = document.getElementById('pdf-report-container');
            html2pdf().set({
                margin: 0,
                filename: 'DocTrack_Enterprise_KPIs.pdf',
                image: { type: 'jpeg', quality: 1 },
                html2canvas: { scale: 2, useCORS: true, backgroundColor: '#0f0f28' },
                jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
            }).from(el).save().then(() => {
                wrapper.style.display = 'none';
                showToast('Relatório de Alta Qualidade Gerado', 'success');
            });
        }, 600);
    }, 50);
"""

# Extract exactly the function exportKPIs
content = content[:content.find(start_marker)] + new_func + content[content.find(end_marker):]

with open('static/app.js', 'w', encoding='utf-8') as f:
    f.write(content)

print("Replacement app.js done!")
