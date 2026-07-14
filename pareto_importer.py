"""
pareto_importer.py — Importa a aba de análise Pareto 80-20 para os equipamentos.

Traz para cada equipamento a **Qtd de saídas** e a **Classe ABC** (priorização
comercial), casando pela **SKU de Venda** com `equipamentos.sku`.

Chave de junção: SKU de Venda NORMALIZADO (`utils.norm_sku`) — ignora zero à
esquerda, para '01.000404' e '1.000404' casarem. A planilha é lida com
`dtype=str` de propósito: se deixarmos o pandas inferir, a coluna de SKU vira
float e perde zeros à direita ('01.000200' → 1.0002), quebrando o casamento.

Snapshot: em modo aplicar, equipamentos ativos que tinham classe/qtd mas não
aparecem nesta planilha são zerados (saíram do ranking). Idempotente; dry-run.
"""

import io
import pandas as pd

from models import db, Equipamento
from utils import norm_sku

# Cabeçalho da aba Pareto está na 11ª linha da planilha (índice 10).
_HEADER_ROW = 10
_SHEET_HINT = "pareto"


def _col(df, *keys):
    """Acha a coluna cujo nome (maiúsculo) contém todos os termos `keys`."""
    for c in df.columns:
        cu = str(c).upper()
        if all(k in cu for k in keys):
            return c
    return None


def _s(v):
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in ("nan", "none", "-", "—") else s


def _int(v):
    s = _s(v)
    if not s:
        return 0
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return 0


def _achar_aba(path=None, file_bytes=None):
    """Escolhe a aba do Pareto (a que contém 'pareto' no nome; senão a 1ª)."""
    src = io.BytesIO(file_bytes) if file_bytes is not None else path
    xls = pd.ExcelFile(src)
    for nome in xls.sheet_names:
        if _SHEET_HINT in str(nome).lower():
            return xls, nome
    return xls, xls.sheet_names[0]


def importar_pareto(path=None, file_bytes=None, dryrun=True):
    """Atualiza qtd_saidas/pareto_classe dos equipamentos a partir da aba Pareto.

    dryrun=True calcula a prévia sem gravar; dryrun=False aplica e comita.
    """
    xls, aba = _achar_aba(path, file_bytes)
    df = pd.read_excel(xls, sheet_name=aba, header=_HEADER_ROW, dtype=str)

    c_sku    = _col(df, "SKU", "VENDA")
    c_qtd    = _col(df, "QTD") or _col(df, "SAID")
    c_classe = _col(df, "CLASSE")
    if not c_sku or not c_classe:
        return {"erro": "Planilha sem as colunas 'SKU Venda' e/ou 'Classe ABC'."}

    # Equipamentos ativos indexados por SKU normalizado.
    por_sku_norm = {}
    for e in Equipamento.query.filter(Equipamento.ativo == True).all():
        k = norm_sku(e.sku)
        if k:
            por_sku_norm.setdefault(k, e)

    atualizar, sem_match, inconsistencias = [], [], []
    casados = set()  # SKUs normalizados de equipamentos tocados nesta planilha
    vistos = set()

    for i, row in df.iterrows():
        sku = _s(row.get(c_sku))
        if not sku:
            continue  # linha de total/rodapé sem SKU
        key = norm_sku(sku)
        if not key:
            inconsistencias.append({"linha": int(i) + _HEADER_ROW + 2, "sku": sku,
                                    "motivo": "SKU de Venda fora do padrão NN.NNNNNN"})
            continue
        if key in vistos:
            inconsistencias.append({"linha": int(i) + _HEADER_ROW + 2, "sku": sku,
                                    "motivo": "SKU de Venda duplicado na planilha"})
            continue
        vistos.add(key)

        qtd = _int(row.get(c_qtd)) if c_qtd else 0
        classe = _s(row.get(c_classe)).upper()[:1]
        if classe not in ("A", "B", "C"):
            classe = ""

        eq = por_sku_norm.get(key)
        if not eq:
            sem_match.append({"sku": sku, "qtd_saidas": qtd, "classe": classe})
            continue

        casados.add(key)
        atualizar.append({"sku": sku, "nome": eq.nome, "classe": classe, "qtd_saidas": qtd})
        if not dryrun:
            eq.pareto_classe = classe
            eq.qtd_saidas = qtd

    # Snapshot: quem tinha classe/qtd e saiu do ranking é zerado.
    limpos = []
    for k, eq in por_sku_norm.items():
        if k in casados:
            continue
        if (eq.pareto_classe or "") or (eq.qtd_saidas or 0):
            limpos.append({"sku": eq.sku, "nome": eq.nome})
            if not dryrun:
                eq.pareto_classe = ""
                eq.qtd_saidas = 0

    if not dryrun:
        db.session.commit()

    return {
        "aplicado": not dryrun,
        "aba": aba,
        "total_linhas": len(df),
        "a_atualizar": len(atualizar),
        "sem_match_n": len(sem_match),
        "limpos_n": len(limpos),
        "inconsistencias_n": len(inconsistencias),
        "atualizar": atualizar,
        "sem_match": sem_match,
        "limpos": limpos,
        "inconsistencias": inconsistencias,
    }
