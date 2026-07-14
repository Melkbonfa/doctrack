"""
reconciliar_orfaos.py — reconcilia documentos ATIVOS presos a equipamentos INATIVOS.

Contexto: as exclusões de equipamento feitas em 01–02/07/2026 ocorreram antes de a
rota DELETE passar a desativar (soft-delete) os documentos junto. Resultado: 18
equipamentos ficaram inativos — logo, invisíveis no módulo Equipamentos — enquanto
seus documentos continuaram ativos e visíveis no módulo Documentos. Daí a
divergência entre os dois módulos.

A maioria desses equipamentos era cópia criada pelo bug do zero à esquerda no SKU
("1.000207" vs "01.000207"). O gêmeo canônico segue ativo, mas com os 9 documentos
VAZIOS que o backfill auto-criou — enquanto o conteúdo real (status, código,
responsável, armazenamento) ficou nos documentos do órfão. Por isso a mesclagem
escolhe o documento mais RICO de cada tipo; não se pode simplesmente descartar o
lado órfão.

Regras (por par órfão → canônico):
- Para cada tipo_doc, mantém o documento de maior doc_rank (status mais avançado /
  com conteúdo), migra-o para o canônico e desativa os demais.
- Antes de desativar o perdedor, o vencedor ABSORVE os campos que estiverem vazios
  nele (codigo_doc, responsavel, armazenamento, datas…). Sem isso perderíamos, por
  exemplo, o codigo_doc que só o perdedor tinha — os dois lados estão parcialmente
  preenchidos, cada um com uma parte da informação.
- Campos vazios do canônico são preenchidos a partir do órfão.
- Sem gêmeo + documentos com conteúdo real  -> REATIVA o equipamento.
- Sem gêmeo + documentos todos vazios       -> desativa os documentos (completa o cascade).

Uso:
  python scripts/reconciliar_orfaos.py            # dry-run (só relata)
  python scripts/reconciliar_orfaos.py --apply    # aplica de verdade
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from servidor import app, db
from models import Equipamento, Documento

APPLY = "--apply" in sys.argv

# Órfão (inativo, com docs ativos) -> canônico ATIVO que deve absorver os documentos.
# Casados por SKU normalizado; 22 e 31 casados por nome (o SKU do órfão está truncado).
PARES = {
    2: 94, 3: 61, 4: 105, 5: 137, 6: 73, 16: 7, 18: 44, 20: 77,
    21: 169, 22: 136, 24: 139, 25: 131, 26: 133, 28: 155, 29: 116, 31: 8,
}

# Órfãos sem gêmeo: os documentos são reais, então o equipamento volta a existir.
REATIVAR = [27]

# Órfãos sem gêmeo cujos documentos estão todos vazios: exclusão legítima, o
# cascade é que não rodou. Desativa os documentos.
LIMPAR = [39]

# Campos do canônico preenchidos a partir do órfão quando estiverem vazios.
FILL_FIELDS = [
    "nome_original", "nome_tecnico", "descricao", "sku_importacao",
    "classificacao_reg", "anvisa", "anvisa_registro", "anvisa_validade",
    "fabricante", "codigo_fabricante", "armazenamento_base",
    "categoria_id", "familia_id",
]

# Campos do documento vencedor preenchidos a partir do perdedor, quando vazios.
# 'status' fica de fora: o vencedor já foi escolhido por ter o status mais avançado.
# 'sku' também fica de fora: quem manda no SKU é o equipamento (ver SKU propagado
# no final), não o documento — senão herdaríamos a grafia legada sem zero à esquerda.
DOC_FILL_FIELDS = [
    "codigo_doc", "responsavel", "armazenamento", "fabricante",
    "data_treinamento", "obs_treinamento", "data_homologacao", "obs_homologacao",
]

# A planilha mestra traz o mesmo equipamento em duas linhas, cada uma com seu
# código IT — a mesclagem produziria um conjunto misto. Estes são os códigos
# oficiais, confirmados pelo time: todo documento do canônico passa a usá-lo.
#   PlateSpin  -> .28 (a linha 'PLATESPIN'/.54 é a duplicata)
#   L-PLATE SHAKER 100-240V -> .55, cujo SKU correto é 01.000517
CODIGO_OFICIAL = {7: "IT.PRE.LC.02.28", 8: "IT.PRE.LC.02.55"}
SKU_OFICIAL    = {8: "01.000517"}


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
    return (r, -d.id)   # desempate: documento mais antigo vence


def ativos_de(equip_id):
    return Documento.query.filter(
        Documento.ativo == True, Documento.equipamento_id == equip_id).all()


def main():
    with app.app_context():
        print(f"\n{'APLICANDO' if APPLY else 'DRY-RUN'} — reconciliação de órfãos\n" + "=" * 78)
        migrados = descartados = campos = reativados = limpos = absorvidos = 0
        normalizados = 0

        for oid, cid in sorted(PARES.items()):
            orfao = db.session.get(Equipamento, oid)
            canon = db.session.get(Equipamento, cid)
            print(f"\n[{oid}] '{orfao.nome}' (inativo)  ->  [{cid}] '{canon.nome}' (ativo)")

            for f in FILL_FIELDS:
                if getattr(canon, f) in (None, "", 0):
                    v = getattr(orfao, f)
                    if v not in (None, "", 0):
                        print(f"      campo {f}: (vazio) <- '{v}'")
                        campos += 1
                        if APPLY:
                            setattr(canon, f, v)

            por_tipo = {}
            for d in ativos_de(oid) + ativos_de(cid):
                por_tipo.setdefault(d.tipo_doc, []).append(d)

            for tipo, lst in sorted(por_tipo.items()):
                melhor = max(lst, key=doc_rank)
                for d in lst:
                    if d is melhor:
                        if d.equipamento_id != canon.id:
                            print(f"      {tipo:<28} migra doc {d.id} "
                                  f"(status={d.status!r}) -> [{cid}]")
                            migrados += 1
                            if APPLY:
                                d.equipamento_id = canon.id
                                d.equipamento = canon.nome
                    else:
                        for f in DOC_FILL_FIELDS:
                            if not getattr(melhor, f) and getattr(d, f):
                                print(f"      {tipo:<28} doc {melhor.id} absorve "
                                      f"{f}={getattr(d, f)!r} do doc {d.id}")
                                absorvidos += 1
                                if APPLY:
                                    setattr(melhor, f, getattr(d, f))
                        print(f"      {tipo:<28} descarta doc {d.id} "
                              f"(status={d.status!r}, do equip {d.equipamento_id})")
                        descartados += 1
                        if APPLY:
                            d.ativo = False
                            d.deleted_at = datetime.now()

        for eid in REATIVAR:
            e = db.session.get(Equipamento, eid)
            n = len(ativos_de(eid))
            print(f"\n[{eid}] '{e.nome}' — sem gêmeo, {n} docs com conteúdo real -> REATIVA equipamento")
            reativados += 1
            if APPLY:
                e.ativo = True
                e.updated_em = datetime.now()

        for eid in LIMPAR:
            e = db.session.get(Equipamento, eid)
            docs = ativos_de(eid)
            print(f"\n[{eid}] '{e.nome}' — sem gêmeo, {len(docs)} docs todos vazios -> desativa docs")
            for d in docs:
                limpos += 1
                if APPLY:
                    d.ativo = False
                    d.deleted_at = datetime.now()

        # Identidade final: o Equipamento é a fonte única do SKU e do código IT.
        # Roda depois da mesclagem, sobre o conjunto já consolidado do canônico.
        print("\n" + "-" * 78)
        print("Normalização de identidade nos canônicos:")
        for cid in sorted(set(PARES.values()) | set(REATIVAR)):
            canon = db.session.get(Equipamento, cid)

            sku_ok = SKU_OFICIAL.get(cid)
            if sku_ok and canon.sku != sku_ok:
                print(f"  [{cid}] '{canon.nome}' SKU {canon.sku!r} -> {sku_ok!r} (oficial)")
                if APPLY:
                    canon.sku = sku_ok

            cod_ok = CODIGO_OFICIAL.get(cid)
            for d in ativos_de(cid):
                if canon.sku and d.sku != canon.sku:
                    normalizados += 1
                    if APPLY:
                        d.sku = canon.sku
                if cod_ok and d.codigo_doc and d.codigo_doc != cod_ok:
                    print(f"  [{cid}] doc {d.id} {d.tipo_doc}: codigo_doc "
                          f"{d.codigo_doc!r} -> {cod_ok!r} (oficial)")
                    normalizados += 1
                    if APPLY:
                        d.codigo_doc = cod_ok

        if APPLY:
            db.session.commit()

        print("\n" + "=" * 78)
        print(f"Resumo: {migrados} docs migrados; {descartados} docs descartados (vazios/piores); "
              f"{absorvidos} campos de doc absorvidos do perdedor; "
              f"{campos} campos de equip. preenchidos; {reativados} equip. reativado(s); "
              f"{limpos} docs limpos; {normalizados} campos normalizados (SKU/código IT).")
        if not APPLY:
            print("\n>> DRY-RUN. Nada foi alterado. Rode com --apply para aplicar.")


if __name__ == "__main__":
    main()
