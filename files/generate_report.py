"""
DocTrack — Gerador de Relatório PDF (Backend)
=============================================
Recebe um JSON com KPIs e devolve um PDF A4 paisagem perfeitamente
calibrado, com gráficos vetoriais (SVG) e zero distorção.

USO:
    POST /api/report/pdf
    Body: { kpis: { total, global_counts, por_setor, status_counts } }

EXECUÇÃO LOCAL:
    python generate_report.py            # gera PDF de exemplo em ./out
    python generate_report.py --serve    # sobe servidor Flask na porta 5000
"""
import os
import sys
import json
from datetime import datetime
from io import BytesIO

# Configuração específica para Windows carregar o GTK3 Runtime (necessário para WeasyPrint)
if sys.platform == "win32":
    gtk_bin = r"C:\Program Files\GTK3-Runtime Win64\bin"
    if os.path.exists(gtk_bin):
        os.environ["PATH"] = gtk_bin + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(gtk_bin)
            except Exception:
                pass

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

import charts

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Cores fixas por setor (override quando aplicável); o resto cai na paleta cíclica
CAT_COLORS = {
    "Financeiro": "#10b981",
    "RH": "#22d3ee",
    "Jurídico": "#a855f7",
    "TI": "#f59e0b",
    "Operações": "#ec4899",
    "Comercial": "#6366f1",
}


def _resolve_setor_colors(setores):
    """Retorna lista de cores na ordem dos setores informados."""
    out = []
    for i, s in enumerate(setores):
        out.append(CAT_COLORS.get(s, charts.SETOR_PALETTE[i % len(charts.SETOR_PALETTE)]))
    return out


def build_context(kpis: dict) -> dict:
    """Transforma o JSON de KPIs no contexto pronto para o template."""
    total = kpis.get("total", 0) or 0
    global_counts = kpis.get("global_counts", {}) or {}
    por_setor = kpis.get("por_setor", {}) or {}
    status_counts = kpis.get("status_counts", {}) or {}

    # ---- gráfico global (doughnut) ----
    g_labels = ["Finalizado", "Em progresso", "Pendente"]
    g_values = [global_counts.get(k, 0) for k in g_labels]
    g_colors = ["#10b981", "#22d3ee", "#94a3ff"]
    chart_global = charts.doughnut_svg(g_labels, g_values, g_colors)

    # ---- gráfico setor (doughnut com legenda) ----
    setores = list(por_setor.keys())
    setor_vals = [por_setor[s] for s in setores]
    setor_colors = _resolve_setor_colors(setores)
    chart_setor = charts.doughnut_with_legend_svg(setores, setor_vals, setor_colors)

    # ---- gráfico status (barras horizontais) ----
    flat_status = {}
    for sc in status_counts.values():
        for k, v in sc.items():
            flat_status[k] = flat_status.get(k, 0) + v
    s_labels = list(flat_status.keys())
    s_vals = list(flat_status.values())
    chart_status = charts.horizontal_bar_svg(s_labels, s_vals)

    # ---- tabela ----
    # limita a 8 linhas (cabe garantido no painel de 88mm de altura);
    # se exceder, agrupa o restante em "Outros"
    rows = []
    items = sorted(por_setor.items(), key=lambda x: x[1], reverse=True)
    LIMIT = 8
    visible, hidden = items[:LIMIT - 1], items[LIMIT - 1:]

    if len(items) <= LIMIT:
        visible, hidden = items, []

    for setor, qtd in visible:
        pct = round(qtd / total * 100) if total else 0
        sc = status_counts.get(setor, {}) or {}
        concl = sc.get("Concluído", 0) or sc.get("Homologado", 0) or sc.get("Finalizado", 0)
        rows.append({"setor": setor, "qtd": qtd, "pct": pct, "concl": concl})

    if hidden:
        h_qtd = sum(v for _, v in hidden)
        h_pct = round(h_qtd / total * 100) if total else 0
        h_concl = 0
        for setor, _ in hidden:
            sc = status_counts.get(setor, {}) or {}
            h_concl += sc.get("Concluído", 0) or sc.get("Homologado", 0) or sc.get("Finalizado", 0)
        rows.append({"setor": f"Outros ({len(hidden)} setores)", "qtd": h_qtd, "pct": h_pct, "concl": h_concl})

    return {
        "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "total": total,
        "finalizado": global_counts.get("Finalizado", 0),
        "em_progresso": global_counts.get("Em progresso", 0),
        "pendente": global_counts.get("Pendente", 0),
        "chart_global": chart_global,
        "chart_setor": chart_setor,
        "chart_status": chart_status,
        "table_rows": rows,
    }


def render_pdf(kpis: dict) -> bytes:
    """Renderiza o PDF final e devolve os bytes."""
    env = Environment(
        loader=FileSystemLoader(BASE_DIR),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("template.html")
    context = build_context(kpis)
    html_str = template.render(**context)

    buf = BytesIO()
    HTML(string=html_str, base_url=BASE_DIR).write_pdf(buf)
    return buf.getvalue()


# ============================================================
# CLI / Servidor Flask
# ============================================================
def _sample_kpis():
    return {
        "total": 487,
        "global_counts": {
            "Finalizado": 312,
            "Em progresso": 128,
            "Pendente": 47,
        },
        "por_setor": {
            "Financeiro": 142,
            "Jurídico": 98,
            "RH": 76,
            "TI": 65,
            "Operações": 54,
            "Comercial": 52,
        },
        "status_counts": {
            "Financeiro": {"Concluído": 95, "Em progresso": 32, "Elaborar": 15},
            "Jurídico": {"Homologado": 60, "Em progresso": 28, "Pendente": 10},
            "RH": {"Concluído": 50, "Em progresso": 20, "Elaborar": 6},
            "TI": {"Concluído": 40, "Em progresso": 18, "Pendente": 7},
            "Operações": {"Concluído": 38, "Em progresso": 12, "Elaborar": 4},
            "Comercial": {"Concluído": 29, "Em progresso": 18, "Pendente": 5},
        },
    }


def _serve():
    from flask import Flask, request, send_file, jsonify

    app = Flask(__name__)

    @app.post("/api/report/pdf")
    def report_pdf():
        try:
            payload = request.get_json(force=True, silent=True) or {}
            kpis = payload.get("kpis") or payload
            pdf_bytes = render_pdf(kpis)
            return send_file(
                BytesIO(pdf_bytes),
                mimetype="application/pdf",
                as_attachment=True,
                download_name="DocTrack_Enterprise_KPIs.pdf",
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.get("/health")
    def health():
        return {"ok": True}

    print(">> DocTrack PDF service rodando em http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)


if __name__ == "__main__":
    if "--serve" in sys.argv:
        _serve()
    else:
        # geração de exemplo
        out_dir = os.path.join(BASE_DIR, "out")
        os.makedirs(out_dir, exist_ok=True)
        pdf_bytes = render_pdf(_sample_kpis())
        out_path = os.path.join(out_dir, "DocTrack_Enterprise_KPIs.pdf")
        with open(out_path, "wb") as f:
            f.write(pdf_bytes)
        print(f"PDF gerado em: {out_path}")
        print(f"Tamanho: {len(pdf_bytes)/1024:.1f} KB")
