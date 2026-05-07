import os

with open('templates/dashboard.html', 'r', encoding='utf-8') as f:
    content = f.read()

import re

# We will use regex to replace everything between <!-- CONTAINER DO RELATÓRIO PDF (Oculto) --> and </div> that contains the pdf container

start_marker = "  <!-- CONTAINER DO RELATÓRIO PDF (Oculto) -->"
end_marker = "  </div>\n\n<script src=\"https://cdn.socket.io"

new_html = """  <!-- OVERLAY DE CARREGAMENTO & CONTAINER DO RELATÓRIO PDF -->
  <div id="pdf-wrapper" style="position: fixed; inset: 0; background: rgba(15,15,40,0.9); backdrop-filter: blur(8px); display: none; align-items: flex-start; justify-content: center; z-index: 99999; overflow-y: auto;">
    
    <div style="position: fixed; top: 20px; color: #22d3ee; font-size: 16px; font-weight: 600; display: flex; align-items: center; gap: 10px; background: rgba(15,15,40,0.8); padding: 10px 20px; border-radius: 8px; border: 1px solid rgba(34,211,238,0.3); z-index: 100000; box-shadow: 0 4px 15px rgba(0,0,0,0.5);">
      <span style="display:inline-block; width: 20px; height: 20px; border: 3px solid rgba(34,211,238,0.3); border-top-color: #22d3ee; border-radius: 50%; animation: repSpin 1s linear infinite;"></span>
      <style>@keyframes repSpin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }</style>
      Gerando PDF de Alta Qualidade...
    </div>

    <!-- PÁGINA A4 -->
    <div id="pdf-report-container" style="width: 210mm; min-height: 297mm; background: #0f0f28; color: #f1f5f9; font-family: 'Inter', sans-serif; padding: 20mm; box-sizing: border-box; position: relative; margin: 80px auto 40px auto; box-shadow: 0 20px 60px rgba(34,211,238,0.15);">
      
      <!-- Cabeçalho Cyberpunk -->
      <div style="text-align: center; border-bottom: 2px solid rgba(34,211,238,0.2); padding-bottom: 20px; margin-bottom: 30px;">
        <h1 style="color: #f1f5f9; margin: 0; font-size: 28px; letter-spacing: -0.5px;">Relatório Executivo de KPIs</h1>
        <h2 style="color: #22d3ee; margin: 5px 0 0; font-size: 18px; font-weight: 600;">DocTrack Enterprise v4.0</h2>
        <p style="text-align: right; color: #94a3ff; font-size: 12px; margin-top: 10px;">Gerado em: <span id="rep-date" style="color: #c4b5fd; font-family: 'JetBrains Mono', monospace;"></span></p>
      </div>

      <!-- Resumo Global e Gráfico de Progresso -->
      <div style="display: flex; gap: 30px; margin-bottom: 40px;">
        
        <!-- Cards de KPI -->
        <div style="flex: 1; display: flex; flex-direction: column; gap: 16px;">
          <h3 style="margin: 0; color: #e879f9; font-size: 14px; text-transform: uppercase; letter-spacing: 1px;">Visão Geral</h3>
          
          <div style="background: rgba(30,30,50,0.6); border: 1px solid rgba(167,139,250,0.3); padding: 18px; border-radius: 12px; display: flex; justify-content: space-between; align-items: center;">
            <span style="color: #94a3ff; font-size: 13px;">Total de Documentos</span>
            <strong style="color: #f1f5f9; font-size: 22px; font-family: 'JetBrains Mono', monospace;" id="rep-total"></strong>
          </div>
          
          <div style="background: rgba(30,30,50,0.6); border: 1px solid rgba(16,185,129,0.3); padding: 18px; border-radius: 12px; display: flex; justify-content: space-between; align-items: center;">
            <span style="color: #6ee7b7; font-size: 13px;">Finalizados</span>
            <strong style="color: #10b981; font-size: 20px; font-family: 'JetBrains Mono', monospace;" id="rep-fin"></strong>
          </div>
          
          <div style="background: rgba(30,30,50,0.6); border: 1px solid rgba(34,211,238,0.3); padding: 18px; border-radius: 12px; display: flex; justify-content: space-between; align-items: center;">
            <span style="color: #67e8f9; font-size: 13px;">Em Progresso</span>
            <strong style="color: #22d3ee; font-size: 20px; font-family: 'JetBrains Mono', monospace;" id="rep-prog"></strong>
          </div>

          <div style="background: rgba(30,30,50,0.6); border: 1px solid rgba(148,163,255,0.3); padding: 18px; border-radius: 12px; display: flex; justify-content: space-between; align-items: center;">
            <span style="color: #cbd5ff; font-size: 13px;">Pendentes</span>
            <strong style="color: #94a3ff; font-size: 20px; font-family: 'JetBrains Mono', monospace;" id="rep-pend"></strong>
          </div>
        </div>

        <!-- Gráfico Global -->
        <div style="flex: 2; background: rgba(30,30,50,0.4); border: 1px solid rgba(167,139,250,0.15); border-radius: 12px; padding: 20px;">
          <h3 style="margin: 0 0 20px 0; color: #e879f9; font-size: 14px; text-align: center; text-transform: uppercase; letter-spacing: 1px;">Progresso (Status Global)</h3>
          <div style="height: 250px; position: relative;">
            <canvas id="rep-chart-global"></canvas>
          </div>
        </div>
      </div>

      <!-- Gráficos de Setor e Detalhamento -->
      <div style="display: flex; gap: 30px; margin-bottom: 40px;">
        <div style="flex: 1; background: rgba(30,30,50,0.4); border: 1px solid rgba(167,139,250,0.15); border-radius: 12px; padding: 20px;">
          <h3 style="margin: 0 0 20px 0; color: #22d3ee; font-size: 14px; text-align: center; text-transform: uppercase; letter-spacing: 1px;">Distribuição por Setor</h3>
          <div style="height: 250px; position: relative;">
            <canvas id="rep-chart-setor"></canvas>
          </div>
        </div>
        <div style="flex: 2; background: rgba(30,30,50,0.4); border: 1px solid rgba(167,139,250,0.15); border-radius: 12px; padding: 20px;">
          <h3 style="margin: 0 0 20px 0; color: #22d3ee; font-size: 14px; text-align: center; text-transform: uppercase; letter-spacing: 1px;">Detalhamento de Status</h3>
          <div style="height: 250px; position: relative;">
            <canvas id="rep-chart-status"></canvas>
          </div>
        </div>
      </div>

      <!-- Tabela -->
      <div>
        <h3 style="color: #a855f7; font-size: 16px; border-bottom: 2px solid rgba(168,85,247,0.3); padding-bottom: 10px; text-transform: uppercase; letter-spacing: 1px;">Composição por Setor</h3>
        <table style="width: 100%; border-collapse: separate; border-spacing: 0; margin-top: 15px; font-size: 13px;">
          <thead>
            <tr style="background: rgba(168,85,247,0.1);">
              <th style="padding: 12px; border-bottom: 1px solid rgba(168,85,247,0.3); color: #c4b5fd; text-align: left; border-top-left-radius: 8px;">Setor</th>
              <th style="padding: 12px; border-bottom: 1px solid rgba(168,85,247,0.3); color: #c4b5fd; text-align: center;">Documentos</th>
              <th style="padding: 12px; border-bottom: 1px solid rgba(168,85,247,0.3); color: #c4b5fd; text-align: center;">% do Total</th>
              <th style="padding: 12px; border-bottom: 1px solid rgba(168,85,247,0.3); color: #c4b5fd; text-align: center; border-top-right-radius: 8px;">Concluídos</th>
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

print("Replacement done!")
