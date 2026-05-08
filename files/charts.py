"""
Geração de gráficos SVG (vetoriais) para o relatório DocTrack.
Saída em SVG = qualidade infinita no PDF, sem distorção em qualquer DPI.
"""
import matplotlib
matplotlib.use("Agg")  # backend sem GUI
import matplotlib.pyplot as plt
from io import StringIO

# Paleta dark do DocTrack
BG = "#0f0f28"
PANEL = "#1a1d3a"
TEXT = "#f1f5f9"
MUTED = "#94a3ff"
LILAC = "#c4b5fd"
GRID = "rgba(167,139,250,0.1)"

STATUS_COLORS = {
    "Finalizado": "#10b981",
    "Concluído": "#10b981",
    "Homologado": "#10b981",
    "Em progresso": "#22d3ee",
    "Pendente": "#94a3ff",
    "Elaborar": "#a855f7",
}

# paleta cíclica para setores quando não há cor pré-definida
SETOR_PALETTE = ["#a855f7", "#22d3ee", "#10b981", "#f59e0b", "#ec4899",
                 "#6366f1", "#84cc16", "#f97316", "#06b6d4", "#8b5cf6"]


def _style_axes(ax):
    """Aplica estilo dark consistente nos eixos."""
    ax.set_facecolor("none")
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=9)


def doughnut_svg(labels, values, colors=None, width=2.6, height=2.6):
    """Gráfico de rosca (doughnut) em SVG."""
    if colors is None:
        colors = SETOR_PALETTE[:len(labels)]

    fig, ax = plt.subplots(figsize=(width, height), dpi=100)
    fig.patch.set_alpha(0)

    # filtra zeros para não poluir o gráfico
    filtered = [(l, v, c) for l, v, c in zip(labels, values, colors) if v > 0]
    if not filtered:
        ax.text(0.5, 0.5, "Sem dados", ha="center", va="center",
                color=MUTED, fontsize=10, transform=ax.transAxes)
        ax.axis("off")
    else:
        labels_f, values_f, colors_f = zip(*filtered)
        wedges, _ = ax.pie(
            values_f,
            colors=colors_f,
            startangle=90,
            wedgeprops=dict(width=0.38, edgecolor=PANEL, linewidth=2),
        )
        # total no centro
        total = sum(values_f)
        ax.text(0, 0.05, str(total), ha="center", va="center",
                color=TEXT, fontsize=18, fontweight="bold")
        ax.text(0, -0.18, "Total", ha="center", va="center",
                color=MUTED, fontsize=9)

    ax.axis("equal")
    plt.tight_layout(pad=0.2)

    buf = StringIO()
    plt.savefig(buf, format="svg", transparent=True, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    return buf.getvalue()


def doughnut_with_legend_svg(labels, values, colors=None, width=4.0, height=2.6, max_items=8):
    """Doughnut com legenda lateral (para o gráfico de setores).

    Quando há muitos itens, agrupa os menores em 'Outros' para preservar
    a leitura tanto do gráfico quanto da legenda.
    """
    if colors is None:
        colors = SETOR_PALETTE[:len(labels)]

    fig, ax = plt.subplots(figsize=(width, height), dpi=100)
    fig.patch.set_alpha(0)

    # filtra zeros
    triples = [(l, v, c) for l, v, c in zip(labels, values, colors) if v > 0]

    if not triples:
        ax.text(0.5, 0.5, "Sem dados", ha="center", va="center",
                color=MUTED, fontsize=10, transform=ax.transAxes)
        ax.axis("off")
        plt.tight_layout(pad=0.2)
        buf = StringIO()
        plt.savefig(buf, format="svg", transparent=True, bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)
        return buf.getvalue()

    # agrupa pequenos em "Outros" se passar do limite
    triples.sort(key=lambda x: x[1], reverse=True)
    if len(triples) > max_items:
        head = triples[:max_items - 1]
        tail = triples[max_items - 1:]
        outros_v = sum(v for _, v, _ in tail)
        head.append((f"Outros ({len(tail)})", outros_v, "#6b7299"))
        triples = head

    labels_f = [t[0] for t in triples]
    values_f = [t[1] for t in triples]
    colors_f = [t[2] for t in triples]
    total = sum(values_f)

    wedges, _ = ax.pie(
        values_f,
        colors=colors_f,
        startangle=90,
        wedgeprops=dict(width=0.38, edgecolor=PANEL, linewidth=2),
    )
    ax.text(0, 0.05, str(total), ha="center", va="center",
            color=TEXT, fontsize=16, fontweight="bold")
    ax.text(0, -0.18, "Total", ha="center", va="center",
            color=MUTED, fontsize=8)

    # trunca labels muito longos para a legenda
    def _trim(s, n=22):
        return s if len(s) <= n else s[:n - 1] + "…"

    legend_labels = [f"{_trim(l)}  ·  {v}" for l, v in zip(labels_f, values_f)]

    # 2 colunas quando há muitos itens
    ncol = 2 if len(legend_labels) > 6 else 1
    fontsize = 7 if ncol == 2 else 8

    ax.legend(wedges, legend_labels,
              loc="center left", bbox_to_anchor=(1.05, 0.5),
              frameon=False, labelcolor=LILAC, fontsize=fontsize,
              ncol=ncol, columnspacing=1.0, handletextpad=0.4)
    ax.axis("equal")
    plt.tight_layout(pad=0.2)

    buf = StringIO()
    plt.savefig(buf, format="svg", transparent=True, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    return buf.getvalue()


def horizontal_bar_svg(labels, values, colors=None, width=6.5, height=3.2, max_items=8):
    """Gráfico de barras horizontais para detalhamento de status.

    Limita a max_items barras (top N por valor) para garantir legibilidade.
    """
    if not labels:
        fig, ax = plt.subplots(figsize=(width, height), dpi=100)
        fig.patch.set_alpha(0)
        ax.text(0.5, 0.5, "Sem dados", ha="center", va="center",
                color=MUTED, fontsize=10, transform=ax.transAxes)
        ax.axis("off")
        buf = StringIO()
        plt.savefig(buf, format="svg", transparent=True, bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)
        return buf.getvalue()

    if colors is None:
        colors = [STATUS_COLORS.get(l, "#22d3ee") for l in labels]

    # ordena desc, pega top N
    triples = sorted(zip(labels, values, colors), key=lambda x: x[1], reverse=True)[:max_items]
    # reordena asc para plotar (maior fica em cima)
    triples = sorted(triples, key=lambda x: x[1])
    labels_s = [t[0] for t in triples]
    values_s = [t[1] for t in triples]
    colors_s = [t[2] for t in triples]

    fig, ax = plt.subplots(figsize=(width, height), dpi=100)
    fig.patch.set_alpha(0)
    _style_axes(ax)

    bars = ax.barh(labels_s, values_s, color=colors_s, edgecolor="none", height=0.65)

    # rótulos no fim de cada barra
    max_v = max(values_s) if values_s else 1
    for bar, v in zip(bars, values_s):
        ax.text(bar.get_width() + max_v * 0.02,
                bar.get_y() + bar.get_height() / 2,
                str(v),
                va="center", ha="left",
                color=TEXT, fontsize=9, fontweight="bold")

    ax.set_xlim(0, max_v * 1.18)
    ax.set_xticks([])
    ax.tick_params(axis="y", colors=LILAC, labelsize=9)
    ax.grid(False)

    plt.tight_layout(pad=0.2)
    buf = StringIO()
    plt.savefig(buf, format="svg", transparent=True, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    return buf.getvalue()
