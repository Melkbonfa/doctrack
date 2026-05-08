import os

# --- 1. Modify servidor.py ---
with open('servidor.py', 'r', encoding='utf-8') as f:
    server_content = f.read()

route_code = """
# ── API — PDF REPORT ─────────────────────────────────────────────────────────
@app.route("/api/report/pdf", methods=["POST"])
@jwt_required()
@require_role("admin", "gestor", "tecnico")
def api_report_pdf():
    try:
        import sys
        files_dir = os.path.join(BASE_DIR, "files")
        if files_dir not in sys.path:
            sys.path.append(files_dir)
        import generate_report
        
        payload = request.get_json(force=True, silent=True) or {}
        kpis = payload.get("kpis") or payload
        pdf_bytes = generate_report.render_pdf(kpis)
        
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="DocTrack_Enterprise_KPIs.pdf",
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"erro": f"Erro na geração do PDF: {e}"}), 500

# ── API — METRICS / ENUMS / AUDIT / EXPORT ───────────────────────────────────
"""

if "def api_report_pdf():" not in server_content:
    server_content = server_content.replace("# ── API — METRICS / ENUMS / AUDIT / EXPORT ───────────────────────────────────", route_code)
    with open('servidor.py', 'w', encoding='utf-8') as f:
        f.write(server_content)
    print("Modified servidor.py")
else:
    print("servidor.py already contains PDF route")

# --- 2. Modify static/app.js ---
with open('static/app.js', 'r', encoding='utf-8') as f:
    app_js = f.read()

import re

# find function exportKPIs() { ... }
# Note: we need to replace the entire body of exportKPIs.
start_idx = app_js.find("function exportKPIs() {")
if start_idx != -1:
    end_idx = app_js.find("}\n\nasync function loadEnums", start_idx)
    if end_idx != -1:
        new_export = """function exportKPIs() {
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
}"""
        app_js = app_js[:start_idx] + new_export + app_js[end_idx:]
        with open('static/app.js', 'w', encoding='utf-8') as f:
            f.write(app_js)
        print("Modified static/app.js")
    else:
        print("Could not find end of exportKPIs")
else:
    print("Could not find exportKPIs")

