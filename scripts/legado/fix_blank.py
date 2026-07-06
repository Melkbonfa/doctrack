import os

# --- Fix HTML ---
with open('templates/dashboard.html', 'r', encoding='utf-8') as f:
    content = f.read()

start_marker = "  <!-- OVERLAY DE CARREGAMENTO & CONTAINER DO RELATÓRIO PDF -->"
end_marker = "  </div>\n\n<script src=\"https://cdn.socket.io"

new_html = """  <!-- OVERLAY DE CARREGAMENTO & CONTAINER DO RELATÓRIO PDF -->
  <div id="pdf-wrapper" style="position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(15,15,40,0.98); z-index: 99999; display: none; overflow: auto; align-items: flex-start; justify-content: flex-start;">
    
    <div style="position: fixed; bottom: 30px; right: 30px; color: #22d3ee; font-size: 16px; font-weight: 600; display: flex; align-items: center; gap: 10px; background: rgba(15,15,40,0.9); padding: 12px 24px; border-radius: 8px; border: 1px solid rgba(34,211,238,0.3); z-index: 100000; box-shadow: 0 4px 15px rgba(0,0,0,0.5);">
      <span style="display:inline-block; width: 20px; height: 20px; border: 3px solid rgba(34,211,238,0.3); border-top-color: #22d3ee; border-radius: 50%; animation: repSpin 1s linear infinite;"></span>
      <style>@keyframes repSpin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }</style>
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
        
        <!-- Visão Geral -->
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
  </div>\n\n<script src="https://cdn.socket.io"""

content = content[:content.find(start_marker)] + new_html + content[content.find(end_marker) + len(end_marker):]

with open('templates/dashboard.html', 'w', encoding='utf-8') as f:
    f.write(content)


# --- Fix JS ---
with open('static/app.js', 'r', encoding='utf-8') as f:
    js_content = f.read()

import re
old_html2canvas_block = re.search(r"html2pdf\(\)\.set\(\{.*?\}\)\.from\(el\)", js_content, re.DOTALL)
if old_html2canvas_block:
    # Use windowWidth/windowHeight/width/height and scale 2 to prevent memory limits
    new_html2canvas = """html2pdf().set({
                margin: 0,
                filename: 'DocTrack_Enterprise_KPIs.pdf',
                image: { type: 'jpeg', quality: 1 },
                html2canvas: { scale: 2, useCORS: true, backgroundColor: '#0f0f28', windowWidth: 1123, windowHeight: 794, width: 1123, height: 794, x: 0, y: 0, scrollX: 0, scrollY: 0 },
                jsPDF: { unit: 'px', format: [1123, 794], orientation: 'landscape' }
            }).from(el)"""
    js_content = js_content[:old_html2canvas_block.start()] + new_html2canvas + js_content[old_html2canvas_block.end():]

    with open('static/app.js', 'w', encoding='utf-8') as f:
        f.write(js_content)
    print("Done HTML and JS")
else:
    print("Could not find JS block to replace")
