"""
importar_entregaveis.py — Importação única da aba "Controle Projetos 2026"
da planilha "Entregáveis - Engenharia (rev fev).xlsm" para o doctrack.db.

A importação já foi executada e o módulo /entregaveis substituiu a planilha. Na
limpeza de jul/2026 o .xlsm (1,7 MB) saiu do repositório e foi para o arquivo
morto em C:\\Apps\\doctrack-arquivo\\files\\. Para reexecutar, aponte XLSM para lá
ou copie a planilha de volta.

Uso:
  ./venv/Scripts/python.exe importar_entregaveis.py            # importa (aborta se já houver dados)
  ./venv/Scripts/python.exe importar_entregaveis.py --substituir  # apaga projetos do ano e reimporta
  ./venv/Scripts/python.exe importar_entregaveis.py --dry-run     # só mostra o resumo, não grava
  ./venv/Scripts/python.exe importar_entregaveis.py --atualizar --arquivo "C:\\...\\planilha.xlsm"
      # revisão nova da planilha: só ajusta status/percentual dos entregáveis
      # que mudaram, preservando responsáveis, datas, pesos e histórico
  ./venv/Scripts/python.exe importar_entregaveis.py --incluir-abas --arquivo "C:\\...\\planilha.xlsm"
      # cria os projetos das outras abas (ABAS_EXTRAS) que ainda não existem
"""
import os
import re
import sys
import argparse
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

XLSM = os.path.join(ROOT, "files", "Entregáveis - Engenharia (rev fev).xlsm")
ABA = "Controle Projetos 2026"
ANO = 2026
CATEGORIAS_VALIDAS = ["Produto", "Sistema", "Documentação", "Capacitação", "Marketing"]
# Cabeçalhos (linha 2) das colunas de metadados, em lower
META = {"ordem", "moscow", "prioridade", "entregáveis", "descrição", "consumível?",
        "cronograma mapeado", "sku", "lançamentos"}

# Abas que não são o controle do ano mas trazem projetos que o módulo também
# acompanha (--incluir-abas). Cada uma tem o seu desenho de cabeçalho:
#   linhas = índices 0-based das linhas de (categoria, tipo, responsável)
#   nome   = cabeçalho da coluna com o nome do projeto
#   marca  = coluna com a anotação solta da planilha ("D", "?"), se houver
ABAS_EXTRAS = [
    dict(aba="Controle Projetos 2025", ano=2025, linhas=(0, 1, 2), nome="entregáveis"),
    dict(aba="Outros Projetos ou CV", ano=ANO, linhas=(0, 2, 3), nome="ciclo de vida",
         descricao="Ciclo de vida", marca=0),
]
# Projetos da aba de 2025 que seguem em 2026 com outro nome (mesmo SKU):
# incluí-los de novo duplicaria o projeto.
RENOMEADOS = {
    "lmr multimodal": "LMR Multimodal (software)",
    "pixcell ®": "Pixcell ® / Fluo",
    "extracta® 768": "Extracta® 768 (Saturno)",
}
# A aba de ciclo de vida grafa três entregáveis de outro jeito; sem unificar, os
# painéis por tipo de entregável os contariam como tipos distintos.
ALIAS_TIPO = {
    "manual de serviços original": "Manual de Serviços",
    "qi/qo/qd versão orginal": "QI/QO/QD versão Original",
    "checklist": "Checklists",
}


def extrair_colunas(linha1, linha2, linha3):
    """Retorna [(idx0, tipo, categoria, responsaveis)] das colunas de entregável.

    Categoria vem da linha 1 com forward-fill; corta quando a categoria
    deixa de ser uma das válidas (ex.: '% janeiro') ou o tipo começa com '%'.
    """
    cols, categoria = [], None
    for i, tipo in enumerate(linha2):
        cab1 = linha1[i] if i < len(linha1) else None
        if isinstance(cab1, str) and cab1.strip():
            categoria = cab1.strip()
        nome = (tipo or "").strip() if isinstance(tipo, str) else ""
        if not nome or nome.lower() in META:
            continue
        nl = nome.lower()
        # Colunas de resumo/indicadores encerram a região de entregáveis
        if (nome.startswith("%") or nl.startswith("idp")
                or nl in ("idc", "andamento", "esperado", "executado",
                          "lançamento previsto", "lançamento real")):
            break
        if categoria not in CATEGORIAS_VALIDAS:
            # primeira coluna de % mensal encerra a região de entregáveis
            if categoria is not None:
                break
            continue
        resp = linha3[i] if i < len(linha3) else None
        resp = (resp or "").strip() if isinstance(resp, str) else ""
        # normaliza quebras de linha em nomes tipo "Software\nNeutro"
        nome = " ".join(nome.split())
        cols.append((i, nome, categoria, resp))
    return cols


def carregar_planilha(arquivo=None, aba=ABA):
    from openpyxl import load_workbook
    wb = load_workbook(arquivo or XLSM, read_only=True, data_only=True)
    ws = wb[aba]
    linhas = list(ws.iter_rows(values_only=True))
    return linhas


def indices_metadados(linha2):
    """Mapeia cabeçalho de metadado → índice de coluna (0-based)."""
    idx = {}
    for i, v in enumerate(linha2):
        if isinstance(v, str) and v.strip().lower() in META:
            # setdefault: a planilha repete "Entregáveis" como coluna de
            # contagem no fim — só a primeira ocorrência vale
            idx.setdefault(v.strip().lower(), i)
    return idx


def _chave(texto):
    """Nome de projeto/entregável normalizado para casar planilha × banco."""
    return " ".join(str(texto or "").split()).casefold()


def atualizar(arquivo=None, dry_run=False):
    """Aplica uma revisão nova da planilha sobre os projetos que já existem.

    Só toca em status/percentual, e só onde a célula diverge do banco — o
    `--substituir` apagaria responsáveis, datas, pesos e histórico. Projeto casa
    por nome e entregável por tipo. As regras de transição são as mesmas do
    PUT /api/entregaveis/<id> (entregaveis.atualizar_entregavel), inclusive o
    registro em `entregavel_historico`, que é o que sustenta a curva-S.
    """
    os.environ.setdefault("JWT_SECRET", "import-local-secret-32-chars-xxxxxxxx")
    from servidor import app
    from models import db, Projeto, Entregavel, EntregavelHistorico, converter_celula

    linhas = carregar_planilha(arquivo)
    l1, l2, l3 = linhas[0], linhas[1], linhas[2]
    cols = extrair_colunas(l1, l2, l3)
    meta = indices_metadados(l2)
    planilha = {}
    for row in linhas[3:]:
        nome = row[meta["entregáveis"]] if meta.get("entregáveis") is not None else None
        if not (isinstance(nome, str) and nome.strip()):
            if planilha:
                break
            continue
        planilha[_chave(nome)] = (" ".join(nome.split()), row)

    with app.app_context():
        agora = datetime.now()
        hoje_iso = agora.strftime("%Y-%m-%d")
        projetos = {_chave(p.nome): p for p in Projeto.query.filter_by(ano=ANO).all()}
        mudancas = criados = 0

        for chave, (nome, row) in planilha.items():
            p = projetos.get(chave)
            if p is None:
                print(f"  ! {nome}: não existe no banco — ignorado (crie o projeto antes)")
                continue
            por_tipo = {}
            for e in p.entregaveis:
                por_tipo.setdefault(_chave(e.tipo), e)
            alterou = False
            for (i, tipo, categoria, resp) in cols:
                status, pct = converter_celula(row[i] if i < len(row) else None)
                e = por_tipo.get(_chave(tipo))
                if e is None:
                    if status == "na":
                        continue          # ausente e não aplicável: nada a acompanhar
                    e = Entregavel(projeto_id=p.id, tipo=tipo, categoria=categoria,
                                   responsaveis=resp, status="pendente", percentual=0)
                    p.entregaveis.append(e)
                    criados += 1
                    print(f"  + {p.nome} · {tipo}: criado")
                if (e.status, e.percentual) == (status, pct):
                    continue
                print(f"  ~ {p.nome} · {tipo}: {e.status}/{e.percentual} -> {status}/{pct}")
                antigo = e.status
                e.status, e.percentual = status, pct
                if status == "concluido":
                    if not (e.data_conclusao or "").strip():
                        e.data_conclusao = hoje_iso
                    if not (e.data_inicio or "").strip():
                        e.data_inicio = e.data_conclusao
                elif status == "na":
                    e.data_conclusao = ""
                elif status == "em_progresso" and not (e.data_inicio or "").strip():
                    e.data_inicio = hoje_iso
                # 'pendente' preserva data_conclusao de propósito (ver a rota).
                e.historico.append(EntregavelHistorico(
                    status_antigo=antigo or "", status_novo=status,
                    percentual=pct, em=agora, por="importacao"))
                e.atualizado_por = "importacao"
                e.atualizado_em = agora
                mudancas += 1
                alterou = True
            if alterou and not dry_run:
                p.registrar_snapshot()

        fora = [p.nome for k, p in projetos.items() if k not in planilha and p.ativo]
        if fora:
            print(f"\nAtivos no banco e fora da planilha (não alterados): {', '.join(fora)}")
        print(f"\n{len(planilha)} projetos na planilha · {mudancas} entregáveis alterados"
              f" · {criados} criados.")
        if dry_run:
            db.session.rollback()
            print("--dry-run: nada gravado.")
            return
        db.session.commit()
        print("OK: gravado no banco.")


def _metadados(row, meta):
    """Campos de projeto de uma linha da planilha; coluna ausente vira vazio."""
    def mv(chave):
        i = meta.get(chave)
        return row[i] if i is not None and i < len(row) else None
    lanc = mv("lançamentos")
    if hasattr(lanc, "strftime"):
        lanc = lanc.strftime("%d/%m/%Y")
    prio = str(mv("prioridade") or "").strip()
    return dict(
        descricao=str(mv("descrição") or "").strip(),
        sku=str(mv("sku") or "").strip(),
        moscow=str(mv("moscow") or "").strip(),
        prioridade=int(prio) if prio.isdigit() else 0,
        consumivel=str(mv("consumível?") or "").strip().lower() == "sim",
        lancamento=str(lanc or "").strip(),
    )


def incluir(arquivo=None, dry_run=False):
    """Cria os projetos das ABAS_EXTRAS que ainda não existem no banco.

    Só inclui: projeto que já existe (pelo nome, em qualquer ano) ou que consta
    em RENOMEADOS é pulado — quem mantém os existentes é o `--atualizar`. O
    projeto nasce como na rota POST /api/projetos: linha de base v1 e a primeira
    foto, com os responsáveis do texto ligados a usuários pelo primeiro nome
    quando ele é inequívoco (mesma regra da migração 007).
    """
    os.environ.setdefault("JWT_SECRET", "import-local-secret-32-chars-xxxxxxxx")
    from servidor import app
    from models import db, Projeto, Entregavel, User, converter_celula

    with app.app_context():
        hoje_iso = datetime.now().strftime("%Y-%m-%d")
        existentes = {_chave(p.nome) for p in Projeto.query.all()}
        por_primeiro = {}
        for u in User.query.filter_by(ativo=True).all():
            por_primeiro.setdefault(_chave(u.nome).split(" ")[0], []).append(u)
        criados = 0

        for cfg in ABAS_EXTRAS:
            linhas = carregar_planilha(arquivo, cfg["aba"])
            i_cat, i_tipo, i_resp = cfg["linhas"]
            cab = linhas[i_tipo]
            cols = extrair_colunas(linhas[i_cat], cab, linhas[i_resp])
            meta = indices_metadados(cab)
            col_nome = next(i for i, v in enumerate(cab)
                            if isinstance(v, str) and v.strip().lower() == cfg["nome"])
            print(f"\n{cfg['aba']} ({len(cols)} tipos de entregável):")
            achou = False
            for row in linhas[i_resp + 1:]:
                nome = row[col_nome] if col_nome < len(row) else None
                if not (isinstance(nome, str) and nome.strip()):
                    if achou:
                        break             # bloco contíguo, como na aba principal
                    continue
                achou = True
                nome = " ".join(nome.split())
                chave = _chave(nome)
                if chave in RENOMEADOS:
                    print(f"  = {nome}: já existe como '{RENOMEADOS[chave]}'")
                    continue
                if chave in existentes:
                    continue
                campos = _metadados(row, meta)
                if cfg.get("descricao") and not campos["descricao"]:
                    campos["descricao"] = cfg["descricao"]
                    marca = row[cfg["marca"]] if cfg.get("marca") is not None else None
                    if isinstance(marca, str) and marca.strip():
                        campos["descricao"] += f' · marcado "{marca.strip()}" na planilha'
                p = Projeto(nome=nome, ano=cfg["ano"], **campos)
                db.session.add(p)
                for (i, tipo, categoria, resp) in cols:
                    status, pct = converter_celula(row[i] if i < len(row) else None)
                    e = Entregavel(tipo=ALIAS_TIPO.get(_chave(tipo), tipo),
                                   categoria=categoria, responsaveis=resp,
                                   status=status, percentual=pct,
                                   atualizado_por="importacao")
                    if status == "concluido":
                        e.data_conclusao = e.data_inicio = hoje_iso
                    elif status == "em_progresso":
                        e.data_inicio = hoje_iso
                    for parte in re.split(r"[/,;&]| e ", resp):
                        cands = por_primeiro.get(_chave(parte)) or []
                        # nome ambíguo não é adivinhado: fica só o texto
                        if len(cands) == 1 and cands[0] not in e.responsaveis_users:
                            e.responsaveis_users.append(cands[0])
                    p.entregaveis.append(e)
                p.registrar_baseline("importacao", motivo="Linha de base inicial")
                existentes.add(chave)
                criados += 1
                aplic = sum(1 for e in p.entregaveis if e.status != "na")
                print(f"  + {nome}  [{cfg['ano']}]  {aplic} aplicáveis · avanço {p.avanco}%")
                if not dry_run:
                    db.session.flush()
                    p.registrar_snapshot()

        print(f"\n{criados} projetos novos.")
        if dry_run:
            db.session.rollback()
            print("--dry-run: nada gravado.")
            return
        db.session.commit()
        print("OK: gravado no banco.")


def importar(substituir=False, dry_run=False, arquivo=None):
    os.environ.setdefault("JWT_SECRET", "import-local-secret-32-chars-xxxxxxxx")
    from servidor import app
    from models import db, Projeto, Entregavel, converter_celula

    linhas = carregar_planilha(arquivo)
    l1, l2, l3 = linhas[0], linhas[1], linhas[2]
    cols = extrair_colunas(l1, l2, l3)
    meta = indices_metadados(l2)
    ignoradas = 0
    projetos = []

    for row in linhas[3:]:
        nome = row[meta["entregáveis"]] if meta.get("entregáveis") is not None else None
        if not (isinstance(nome, str) and nome.strip()):
            if projetos:
                # bloco de projetos é contíguo: primeira linha em branco após
                # os dados encerra (abaixo há rodapé de "Equipe"/totais)
                break
            continue
        p = dict(nome=" ".join(str(nome).split()), entregaveis=[],
                 **_metadados(row, meta))
        for (i, tipo, categoria, resp) in cols:
            valor = row[i] if i < len(row) else None
            status, pct = converter_celula(valor)
            if isinstance(valor, str) and valor.strip().startswith("#"):
                ignoradas += 1
            p["entregaveis"].append(dict(tipo=tipo, categoria=categoria,
                                         responsaveis=resp, status=status,
                                         percentual=pct))
        projetos.append(p)

    total_e = sum(len(p["entregaveis"]) for p in projetos)
    print(f"Planilha lida: {len(projetos)} projetos, {total_e} entregáveis, "
          f"{len(cols)} tipos de entregável, {ignoradas} células com lixo de fórmula.")
    for p in projetos:
        aplic = sum(1 for e in p["entregaveis"] if e["status"] != "na")
        print(f"  - {p['nome']}  [{p['moscow'] or '—'}]  {aplic} entregáveis aplicáveis")

    if dry_run:
        print("\n--dry-run: nada gravado.")
        return

    with app.app_context():
        db.create_all()
        existentes = Projeto.query.filter_by(ano=ANO).count()
        if existentes and not substituir:
            print(f"\nABORTADO: já existem {existentes} projetos de {ANO} no banco. "
                  f"Use --substituir para apagar e reimportar.")
            sys.exit(1)
        if existentes and substituir:
            Projeto.query.filter_by(ano=ANO).delete()
            db.session.commit()
            print(f"Projetos de {ANO} anteriores removidos.")
        for p in projetos:
            proj = Projeto(nome=p["nome"], descricao=p["descricao"], sku=p["sku"],
                           moscow=p["moscow"], prioridade=p["prioridade"],
                           consumivel=p["consumivel"], lancamento=p["lancamento"],
                           ano=ANO)
            db.session.add(proj)
            db.session.flush()
            for e in p["entregaveis"]:
                db.session.add(Entregavel(projeto_id=proj.id, **e,
                                          atualizado_por="importacao"))
        db.session.commit()
        print(f"\nOK: {len(projetos)} projetos e {total_e} entregáveis gravados no banco.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--substituir", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--atualizar", action="store_true",
                    help="ajusta só status/percentual dos entregáveis existentes")
    ap.add_argument("--incluir-abas", action="store_true",
                    help="cria os projetos das outras abas que ainda não existem")
    ap.add_argument("--arquivo", default=None, help="caminho do .xlsm (padrão: files/)")
    args = ap.parse_args()
    if args.atualizar:
        atualizar(arquivo=args.arquivo, dry_run=args.dry_run)
    elif args.incluir_abas:
        incluir(arquivo=args.arquivo, dry_run=args.dry_run)
    else:
        importar(substituir=args.substituir, dry_run=args.dry_run, arquivo=args.arquivo)
