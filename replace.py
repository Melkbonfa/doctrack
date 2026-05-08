import os

with open('templates/dashboard.html', 'r', encoding='utf-8') as f:
    content = f.read()

start_marker = "  <!-- OVERLAY DE CARREGAMENTO & CONTAINER DO RELATÓRIO PDF -->"
end_marker = "  </div>\n\n<script src=\"https://cdn.socket.io"

new_html = """  <!-- OVERLAY DE CARREGAMENTO & CONTAINER DO RELATÓRIO PDF -->
  <div id="pdf-wrapper" style="position: fixed; inset: 0; background: rgba(15,15,40,0.95); backdrop-filter: blur(8px); display: none; align-items: flex-start; justify-content: center; z-index: 99999; overflow: auto; padding: 40px 0;">
    
    <div style="position: fixed; top: 20px; left: 50%; transform: translateX(-50%); color: #22d3ee; font-size: 16px; font-weight: 600; display: flex; align-items: center; gap: 10px; background: rgba(15,15,40,0.9); padding: 10px 20px; border-radius: 8px; border: 1px solid rgba(34,211,238,0.3); z-index: 100000; box-shadow: 0 4px 15px rgba(0,0,0,0.5);">
      <span style="display:inline-block; width: 20px; height: 20px; border: 3px solid rgba(34,211,238,0.3); border-top-color: #22d3ee; border-radius: 50%; animation: repSpin 1s linear infinite;"></span>
      <style>@keyframes repSpin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }</style>
      Gerando PDF de Alta Qualidade...
    </div>

    <!-- PÁGINA A4 EXATA EM PIXELS (794x1123) -->
    <div id="pdf-report-container" style="width: 794px; height: 1123px; background: #0f0f28; color: #f1f5f9; font-family: 'Inter', sans-serif; padding: 40px; box-sizing: border-box; position: relative; margin: 0; flex-shrink: 0; overflow: hidden;">
      
      <!-- Cabeçalho Cyberpunk -->
      <div style="text-align: center; border-bottom: 2px solid rgba(34,211,238,0.2); padding-bottom: 15px; margin-bottom: 25px;">
        <h1 style="color: #f1f5f9; margin: 0; font-size: 26px; letter-spacing: -0.5px;">Relatório Executivo de KPIs</h1>
        <h2 style="color: #22d3ee; margin: 4px 0 0; font-size: 16px; font-weight: 600;">DocTrack Enterprise v4.0</h2>
        <p style="text-align: right; color: #94a3ff; font-size: 11px; margin-top: 5px;">Gerado em: <span id="rep-date" style="color: #c4b5fd; font-family: 'JetBrains Mono', monospace;"></span></p>
      </div>

      <!-- Resumo Global e Gráfico de Progresso -->
      <div style="display: flex; gap: 20px; margin-bottom: 25px;">
        
        <!-- Cards de KPI -->
        <div style="flex: 1; display: flex; flex-direction: column; gap: 12px;">
          <h3 style="margin: 0; color: #e879f9; font-size: 13px; text-transform: uppercase; letter-spacing: 1px;">Visão Geral</h3>
          
          <div style="background: rgba(30,30,50,0.6); border: 1px solid rgba(167,139,250,0.3); padding: 15px; border-radius: 10px; display: flex; justify-content: space-between; align-items: center;">
            <span style="color: #94a3ff; font-size: 12px;">Total de Documentos</span>
            <strong style="color: #f1f5f9; font-size: 20px; font-family: 'JetBrains Mono', monospace;" id="rep-total"></strong>
          </div>
          
          <div style="background: rgba(30,30,50,0.6); border: 1px solid rgba(16,185,129,0.3); padding: 15px; border-radius: 10px; display: flex; justify-content: space-between; align-items: center;">
            <span style="color: #6ee7b7; font-size: 12px;">Finalizados</span>
            <strong style="color: #10b981; font-size: 18px; font-family: 'JetBrains Mono', monospace;" id="rep-fin"></strong>
          </div>
          
          <div style="background: rgba(30,30,50,0.6); border: 1px solid rgba(34,211,238,0.3); padding: 15px; border-radius: 10px; display: flex; justify-content: space-between; align-items: center;">
            <span style="color: #67e8f9; font-size: 12px;">Em Progresso</span>
            <strong style="color: #22d3ee; font-size: 18px; font-family: 'JetBrains Mono', monospace;" id="rep-prog"></strong>
          </div>

          <div style="background: rgba(30,30,50,0.6); border: 1px solid rgba(148,163,255,0.3); padding: 15px; border-radius: 10px; display: flex; justify-content: space-between; align-items: center;">
            <span style="color: #cbd5ff; font-size: 12px;">Pendentes</span>
            <strong style="color: #94a3ff; font-size: 18px; font-family: 'JetBrains Mono', monospace;" id="rep-pend"></strong>
          </div>
        </div>

        <!-- Gráfico Global -->
        <div style="flex: 2; background: rgba(30,30,50,0.4); border: 1px solid rgba(167,139,250,0.15); border-radius: 10px; padding: 15px;">
          <h3 style="margin: 0 0 10px 0; color: #e879f9; font-size: 13px; text-align: center; text-transform: uppercase; letter-spacing: 1px;">Progresso (Status Global)</h3>
          <div style="height: 230px; position: relative; width: 100%;">
            <canvas id="rep-chart-global"></canvas>
          </div>
        </div>
      </div>

      <!-- Gráficos de Setor e Detalhamento -->
      <div style="display: flex; gap: 20px; margin-bottom: 25px;">
        <div style="flex: 1; background: rgba(30,30,50,0.4); border: 1px solid rgba(167,139,250,0.15); border-radius: 10px; padding: 15px;">
          <h3 style="margin: 0 0 10px 0; color: #22d3ee; font-size: 13px; text-align: center; text-transform: uppercase; letter-spacing: 1px;">Distribuição por Setor</h3>
          <div style="height: 220px; position: relative; width: 100%;">
            <canvas id="rep-chart-setor"></canvas>
          </div>
        </div>
        <div style="flex: 2; background: rgba(30,30,50,0.4); border: 1px solid rgba(167,139,250,0.15); border-radius: 10px; padding: 15px;">
          <h3 style="margin: 0 0 10px 0; color: #22d3ee; font-size: 13px; text-align: center; text-transform: uppercase; letter-spacing: 1px;">Detalhamento de Status</h3>
          <div style="height: 220px; position: relative; width: 100%;">
            <canvas id="rep-chart-status"></canvas>
          </div>
        </div>
      </div>

      <!-- Tabela -->
      <div>
        <h3 style="color: #a855f7; font-size: 14px; border-bottom: 2px solid rgba(168,85,247,0.3); padding-bottom: 8px; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 1px;">Composição por Setor</h3>
        <table style="width: 100%; border-collapse: separate; border-spacing: 0; font-size: 12px; table-layout: fixed;">
          <thead>
            <tr style="background: rgba(168,85,247,0.1);">
              <th style="padding: 10px; border-bottom: 1px solid rgba(168,85,247,0.3); color: #c4b5fd; text-align: left; border-top-left-radius: 8px; width: 40%;">Setor</th>
              <th style="padding: 10px; border-bottom: 1px solid rgba(168,85,247,0.3); color: #c4b5fd; text-align: center; width: 20%;">Documentos</th>
              <th style="padding: 10px; border-bottom: 1px solid rgba(168,85,247,0.3); color: #c4b5fd; text-align: center; width: 20%;">% do Total</th>
              <th style="padding: 10px; border-bottom: 1px solid rgba(168,85,247,0.3); color: #c4b5fd; text-align: center; border-top-right-radius: 8px; width: 20%;">Concluídos</th>
            </tr>
          </thead>
          <tbody id="rep-table-body">
          </tbody>
        </table>
      </div>
      
    </div>
  </div>\n\n<script src="https://cdn.socket.io"""

content = content[:content.find(start_marker)] + new_html + content[content.find(end_marker) + len(end_marker):]

with open('templates/dashboard.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("done html")
