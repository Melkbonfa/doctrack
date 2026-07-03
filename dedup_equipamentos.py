"""
dedup_equipamentos.py — mescla equipamentos DUPLICADOS pela chave de venda (SKU).

Contexto: a importação da planilha mestra criou cópias do mesmo equipamento porque
o SKU diferia só no zero à esquerda ("1.000404" vs "01.000404") — a junção por SKU
falhou. Este script reconcilia: para cada SKU normalizado com mais de uma entidade
ATIVA, mantém UMA canônica, migra os documentos, preenche campos vazios da canônica
com dados das cópias e desativa (soft-delete) as cópias.

Regras:
- SKU normalizado = só dígitos, sem zeros à esquerda (01.000404 -> 1000404).
- Canônica = menor id do grupo (é a original, nome comercial correto e docs reais).
- SKU da canônica é padronizado para o formato "NN.NNNNNN" (zero à esquerda).
- Documentos: por tipo, mantém o "melhor" (status mais avançado / com conteúdo),
  migra para a canônica e desativa os demais.
- Campos vazios da canônica são preenchidos a partir das cópias (nome_tecnico,
  sku_importacao, nome_original, anvisa*, fabricante, categoria/família, etc.).
- NÃO mescla equipamentos com SKUs diferentes (produtos distintos).

Uso:
  python dedup_equipamentos.py            # dry-run (só relata)
  python dedup_equipamentos.py --apply    # aplica de verdade
"""
import sys
import re
from datetime import datetime

from servidor import app, db
from models import Equipamento, Documento, TIPOS_DOC_TODOS

APPLY = "--apply" in sys.argv

# Campos preenchidos na canônica a partir das cópias, quando a canônica estiver vazia.
FILL_FIELDS = [
    "nome_original", "nome_tecnico", "descricao", "sku_importacao",
    "classificacao_reg", "anvisa", "anvisa_registro", "anvisa_validade",
    "fabricante", "codigo_fabricante", "armazenamento_base",
    "categoria_id", "familia_id",
]


# Só o formato oficial "NN.NNNNNN" (ex.: 01.000404 / 1.000404) é elegível para
# mesclagem automática. SKUs não-padrão (LCV-10X10, 496158, "MINI-15K (220V)"…)
# retornam None e NÃO são agrupados — evita falso-positivo por dígitos avulsos.
_SKU_RE = re.compile(r"^\s*0*(\d+)\.(\d+)\s*$")

def norm_sku(sku):
    m = _SKU_RE.match(sku or "")
    if not m:
        return None
    return f"{m.group(1)}.{m.group(2)}"   # sem zeros à esquerda, ex.: '1.000404'


def pad_sku(sku):
    """Padroniza para 'NN.NNNNNN' (zero à esquerda na parte antes do ponto)."""
    s = (sku or "").strip()
    if "." in s:
        a, b = s.split(".", 1)
        return f"{a.zfill(2)}.{b}"
    return s


def doc_rank(d):
    """Quão 'rico' é o documento (para escolher qual manter por tipo)."""
    st = (d.status or "").strip()
    if st in ("Homologado", "Concluído"):
        r = 3
    elif st in ("Treinamento Piloto", "Enviado para Homologação", "Em andamento"):
        r = 2
    elif (d.codigo_doc or d.responsavel or d.armazenamento):
        r = 1
    else:
        r = 0
    # desempate: id menor (mais antigo) primeiro -> usar -id para max()
    return (r, -d.id)


def main():
    with app.app_context():
        equips = Equipamento.query.filter(Equipamento.ativo == True).all()
        grupos = {}
        for e in equips:
            k = norm_sku(e.sku)
            if k:
                grupos.setdefault(k, []).append(e)
        dups = {k: v for k, v in grupos.items() if len(v) > 1}

        print(f"\n{'APLICANDO' if APPLY else 'DRY-RUN'} — {len(dups)} grupo(s) de SKU duplicado\n" + "="*70)
        total_removidos = total_docs_migrados = total_docs_removidos = total_campos = 0

        for k, membros in sorted(dups.items()):
            membros.sort(key=lambda e: e.id)
            canon = membros[0]
            copias = membros[1:]
            print(f"\nSKU {k}: manter [{canon.id}] '{canon.nome}' (sku={canon.sku})")
            for c in copias:
                print(f"          remover [{c.id}] '{c.nome}' (sku={c.sku})")

            # 1) padroniza SKU da canônica
            novo_sku = pad_sku(canon.sku) or pad_sku(next((c.sku for c in copias if c.sku), ""))
            if novo_sku and novo_sku != canon.sku:
                print(f"          SKU '{canon.sku}' -> '{novo_sku}'")
                if APPLY:
                    canon.sku = novo_sku

            # 2) preenche campos vazios da canônica a partir das cópias
            for f in FILL_FIELDS:
                atual = getattr(canon, f)
                if atual in (None, "", 0):
                    for c in copias:
                        v = getattr(c, f)
                        if v not in (None, "", 0):
                            print(f"          campo {f}: (vazio) <- [{c.id}] '{v}'")
                            total_campos += 1
                            if APPLY:
                                setattr(canon, f, v)
                            break

            # 3) mescla documentos por tipo (mantém o melhor, migra p/ canônica)
            ids_grupo = [m.id for m in membros]
            docs = Documento.query.filter(
                Documento.ativo == True,
                Documento.equipamento_id.in_(ids_grupo)).all()
            por_tipo = {}
            for d in docs:
                por_tipo.setdefault(d.tipo_doc, []).append(d)
            for tipo, lst in por_tipo.items():
                melhor = max(lst, key=doc_rank)
                for d in lst:
                    if d is melhor:
                        if d.equipamento_id != canon.id:
                            total_docs_migrados += 1
                            if APPLY:
                                d.equipamento_id = canon.id
                                d.equipamento = canon.nome
                    else:
                        total_docs_removidos += 1
                        if APPLY:
                            d.ativo = False
                            d.deleted_at = datetime.now()

            # 4) desativa as cópias
            for c in copias:
                total_removidos += 1
                if APPLY:
                    c.ativo = False
                    c.updated_em = datetime.now()

        if APPLY:
            db.session.commit()

        print("\n" + "="*70)
        print(f"Resumo: {total_removidos} equipamentos {'desativados' if APPLY else 'a desativar'}; "
              f"{total_docs_removidos} docs {'removidos' if APPLY else 'a remover'}; "
              f"{total_docs_migrados} docs {'migrados' if APPLY else 'a migrar'}; "
              f"{total_campos} campos {'preenchidos' if APPLY else 'a preencher'}.")
        if not APPLY:
            print("\n>> DRY-RUN. Nada foi alterado. Rode com --apply para aplicar.")


if __name__ == "__main__":
    main()
