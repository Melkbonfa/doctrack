"""
equipamentos_importer.py — Importa a planilha mestra de equipamentos.

Chave de junção: **SKU de Venda** (≠ nome). Casa com `equipamentos.sku`:
- existe → atualiza sku_importacao, nome_tecnico, bloqueado, observações (não toca no `nome`).
- não existe → cria registro novo (sem documentos).

Idempotente. Suporta dry-run (prévia) antes de aplicar.

Colunas esperadas: SKU de Importação · SKU de Venda · Equipamento · Bloqueio · Observações.
"""

import os
import io
import re
import unicodedata
import pandas as pd

from models import db, Equipamento


def _norm(s):
    """Normaliza para casamento de nome: sem acento, só alfanumérico minúsculo."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())

# Caminho padrão da planilha mestra (configurável por env).
DEFAULT_MASTER = os.environ.get(
    "DOCTRACK_EQUIP_MASTER",
    r"P:\Engenharia\Projetos\1. Produtos\Equipamentos Cadastrados.xlsx",
)

_STATUS_PREFIX = {
    "OBSOLETO": "Obsoleto", "OBSOLETA": "Obsoleto",
    "DESCONTINUADO": "Descontinuado", "DESCONTINUADA": "Descontinuado",
}


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


def derivar_nome(nome_master):
    """'Nome - Descrição breve' (ordem às vezes invertida) → (nome, descricao, nome_tecnico, status).

    O nome do produto é o trecho mais curto; o restante vira a descrição.
    Prefixos OBSOLETO/DESCONTINUADO viram status (e saem do nome).
    """
    s = (nome_master or "").strip()
    status = "Ativo"
    partes = [p.strip() for p in s.split(" - ") if p.strip()]
    limpas = []
    for p in partes:
        up = p.upper()
        if up in _STATUS_PREFIX:
            status = _STATUS_PREFIX[up]
        else:
            limpas.append(p)
    if not limpas:
        limpas = [s] if s else [""]
    if len(limpas) == 1:
        nome, desc = limpas[0], ""
    else:
        idx = min(range(len(limpas)), key=lambda i: len(limpas[i].split()))
        nome = limpas[idx]
        desc = " - ".join(limpas[:idx] + limpas[idx + 1:])
    nome_tecnico = " - ".join(limpas)
    return nome, desc, nome_tecnico, status


def _carregar_df(path=None, file_bytes=None):
    if file_bytes is not None:
        return pd.read_excel(io.BytesIO(file_bytes), header=0)
    return pd.read_excel(path or DEFAULT_MASTER, header=0)


# Normalização de SKU de Venda: fonte única em utils.norm_sku (compartilhada com
# o módulo de consumíveis) — antes havia três cópias idênticas deste regex.
from utils import norm_sku as _norm_sku


def importar_equipamentos(path=None, file_bytes=None, dryrun=True):
    """Importa/atualiza equipamentos a partir da planilha. Devolve um relatório.

    dryrun=True calcula a prévia sem gravar; dryrun=False aplica e comita.
    """
    df = _carregar_df(path, file_bytes)
    c_venda = _col(df, "SKU", "VENDA")
    c_imp   = _col(df, "SKU", "IMPORTA")
    c_eq    = _col(df, "EQUIPAMENTO")
    c_bloq  = _col(df, "BLOQUEIO")
    c_obs   = _col(df, "OBSERVA")
    if not c_venda or not c_eq:
        return {"erro": "Planilha sem as colunas 'SKU de Venda' e/ou 'Equipamento'."}

    criar, atualizar, inconsistencias = [], [], []
    vistos = set()

    # Fallback de reconciliação: equipamentos existentes SEM SKU, por nome normalizado.
    # Evita criar duplicata quando o equipamento já existe (vindo dos documentos) sem SKU.
    sem_sku = {}
    for e in Equipamento.query.filter(
        Equipamento.ativo == True,
        db.or_(Equipamento.sku == None, Equipamento.sku == ""),
    ).all():
        sem_sku.setdefault(_norm(e.nome), e)

    # Casamento por SKU NORMALIZADO (ignora zero à esquerda) — evita duplicar quando
    # o SKU só difere no formato ('01.000404' vs '1.000404').
    por_sku_norm = {}
    for e in Equipamento.query.filter(Equipamento.ativo == True).all():
        k = _norm_sku(e.sku)
        if k:
            por_sku_norm.setdefault(k, e)

    for i, row in df.iterrows():
        nome_master = _s(row.get(c_eq))
        sku_venda   = _s(row.get(c_venda))
        if not nome_master and not sku_venda:
            continue  # linha vazia
        if not sku_venda:
            inconsistencias.append({"linha": int(i) + 2, "motivo": "Sem SKU de Venda", "equipamento": nome_master})
            continue
        if sku_venda in vistos:
            inconsistencias.append({"linha": int(i) + 2, "motivo": "SKU de Venda duplicado na planilha", "equipamento": nome_master})
            continue
        vistos.add(sku_venda)

        sku_imp = _s(row.get(c_imp)) if c_imp else ""
        obs     = _s(row.get(c_obs)) if c_obs else ""
        bloq    = (_s(row.get(c_bloq)).upper() == "SIM") if c_bloq else False
        nome, desc, nome_tec, status = derivar_nome(nome_master)

        # 1) casa por SKU normalizado (pega variações de zero à esquerda)
        eq = por_sku_norm.get(_norm_sku(sku_venda)) or Equipamento.query.filter_by(sku=sku_venda).first()
        por_nome = False
        if not eq:
            cand = sem_sku.get(_norm(nome))               # casa por nome (existente sem SKU)
            if cand and not cand.sku:
                eq, por_nome = cand, True
                sem_sku.pop(_norm(nome), None)
        if eq:
            atualizar.append({"sku": sku_venda, "nome": eq.nome, "nome_tecnico": nome_tec,
                              "bloqueado": bloq, "por": "nome" if por_nome else "sku"})
            if not dryrun:
                if por_nome and not eq.sku:               # backfill do SKU no existente
                    eq.sku = sku_venda
                eq.sku_importacao = sku_imp or eq.sku_importacao
                eq.nome_tecnico = nome_tec
                if obs:
                    eq.observacoes = obs
                if not eq.descricao:
                    eq.descricao = desc
                eq.bloqueado = bloq                       # planilha é fonte de verdade
                if status != "Ativo":                      # não rebaixa status manual
                    eq.status = status
        else:
            criar.append({"sku": sku_venda, "nome": nome, "nome_tecnico": nome_tec,
                          "status": status, "bloqueado": bloq})
            if not dryrun:
                db.session.add(Equipamento(
                    nome=nome, nome_tecnico=nome_tec, descricao=desc,
                    sku=sku_venda, sku_importacao=sku_imp,
                    bloqueado=bloq, status=status, observacoes=obs,
                ))

    if not dryrun:
        db.session.commit()

    return {
        "aplicado": not dryrun,
        "total_linhas": len(df),
        "a_criar": len(criar), "a_atualizar": len(atualizar), "inconsistencias_n": len(inconsistencias),
        "criar": criar, "atualizar": atualizar, "inconsistencias": inconsistencias,
    }
