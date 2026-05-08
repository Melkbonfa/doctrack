# DocTrack — Geração de Relatório PDF (Backend)

Solução de geração de relatório executivo PDF em **A4 paisagem**, com qualidade
máxima e zero distorção de imagens, gráficos ou texto.

## Por que esta abordagem é melhor que `html2pdf.js`?

| Aspecto | `html2pdf.js` (anterior) | **WeasyPrint + matplotlib (novo)** |
|---|---|---|
| Renderização | Screenshot (raster) | Nativa do PDF (vetorial) |
| Texto | Vira pixel | Texto real, selecionável e pesquisável |
| Gráficos | Canvas raster | SVG vetorial — qualidade infinita |
| Tamanho do PDF | 2–8 MB | **40 KB** |
| Comportamento em telas diferentes | Inconsistente | **Idêntico em qualquer máquina** |
| Risco de cortes | Alto | Zero (calibrado em mm) |
| Múltiplos setores | Estoura layout | Agrupa em "Outros" automaticamente |

## Stack

- **WeasyPrint** — converte HTML/CSS direto em PDF (sem screenshot)
- **matplotlib** — gera gráficos como SVG vetorial
- **Jinja2** — templating do HTML
- **Flask** — endpoint REST opcional

## Instalação

```bash
pip install weasyprint matplotlib flask jinja2
```

No Linux, WeasyPrint precisa de algumas libs do sistema:
```bash
sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0
```

No Windows/Mac, ver: https://doc.courtbouillon.org/weasyprint/stable/first_steps.html

## Estrutura

```
doctrack_pdf/
├── charts.py            # Geradores de gráficos SVG
├── template.html        # Template Jinja2 do relatório (calibrado em mm)
├── generate_report.py   # Orquestrador + CLI + servidor Flask
└── out/                 # PDFs gerados
```

## Uso

### Como CLI (gera PDF de exemplo)
```bash
python generate_report.py
# => out/DocTrack_Enterprise_KPIs.pdf
```

### Como servidor HTTP
```bash
python generate_report.py --serve
# => http://0.0.0.0:5000/api/report/pdf
```

### Como módulo Python
```python
from generate_report import render_pdf

kpis = {
    "total": 487,
    "global_counts": {"Finalizado": 312, "Em progresso": 128, "Pendente": 47},
    "por_setor": {"Financeiro": 142, "Jurídico": 98, "RH": 76, ...},
    "status_counts": {
        "Financeiro": {"Concluído": 95, "Em progresso": 32, "Elaborar": 15},
        ...
    },
}

pdf_bytes = render_pdf(kpis)
with open("relatorio.pdf", "wb") as f:
    f.write(pdf_bytes)
```

## Integração com o frontend existente

No seu `dashboard.html`, substitua a função `exportKPIs()` por:

```javascript
async function exportKPIs() {
    if (!_lastKpis) {
        showToast('Nenhum dado para exportar', 'error');
        return;
    }

    showToast('Gerando PDF...', 'info');

    try {
        const response = await fetch('/api/report/pdf', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ kpis: _lastKpis })
        });

        if (!response.ok) throw new Error('Falha na geração');

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'DocTrack_Enterprise_KPIs.pdf';
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);

        showToast('Relatório gerado!', 'success');
    } catch (err) {
        console.error(err);
        showToast('Falha na geração', 'error');
    }
}
```

## Formato do JSON de KPIs

```json
{
  "kpis": {
    "total": 487,
    "global_counts": {
      "Finalizado": 312,
      "Em progresso": 128,
      "Pendente": 47
    },
    "por_setor": {
      "Financeiro": 142,
      "Jurídico": 98
    },
    "status_counts": {
      "Financeiro": {
        "Concluído": 95,
        "Em progresso": 32,
        "Elaborar": 15
      }
    }
  }
}
```

## Customização

- **Cores por setor**: edite `CAT_COLORS` em `generate_report.py`
- **Cores por status**: edite `STATUS_COLORS` em `charts.py`
- **Limites de itens** (para evitar overflow):
  - Tabela: `LIMIT = 8` em `build_context()`
  - Doughnut com legenda: `max_items=8` em `doughnut_with_legend_svg()`
  - Barras: `max_items=8` em `horizontal_bar_svg()`
- **Layout/tipografia**: editar `template.html` (todos os tamanhos em `mm`/`pt`)

## Garantias do layout

- **Página única**: `page-break-after: avoid` + `overflow: hidden` no container A4
- **Sem distorção**: tudo calibrado em milímetros (não em pixels)
- **Truncamento gracioso**: nomes longos viram `…`, setores extras viram "Outros (N)"
- **Sem dependência de tela**: render é determinístico no servidor
