r"""seed_demo.py — dados de amostra para o ambiente de DEMONSTRAÇÃO (Render).

Por que existe
-------------
Um banco vazio não sobe vazio: o `init_app()` do servidor já importa as planilhas
versionadas em `data/` e `pdr/data/`, então Documentos, Equipamentos e PDR nascem
com dados reais. Entregáveis, Missões e Consumíveis, não — essas três telas abrem
zeradas e, numa apresentação, passam a impressão de módulo quebrado.

Este script preenche exatamente essas três lacunas. Ele NÃO roda no servidor
interno: quem o chama é o `startCommand` do `render.yaml`, e só porque lá o banco
é descartável. Rodar contra o banco de produção acrescentaria projetos e
consumíveis fictícios ao acervo real.

Uso:
    python scripts/seed_demo.py             # semeia se ainda não houver amostra
    python scripts/seed_demo.py --forcar    # apaga a amostra anterior e recria
    python scripts/seed_demo.py --remover   # só apaga a amostra

Idempotente por desenho. Com a amostra já gravada ele sai em ~1s, sem sequer
importar o servidor — o custo some do cold start do Render, que reexecuta o
`startCommand` toda vez que o serviço acorda.

Tudo que este script cria carrega a marca `MARCA_DEMO` (na descrição do projeto e
da missão, no `sku_importacao` do consumível). É o que permite `--remover` apagar
a amostra sem tocar em nada que tenha vindo das planilhas ou de uso real.
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MARCA_DEMO = "[DEMO]"
HOJE = date.today()
AGORA = datetime.now()


def _url_banco():
    """Mesma resolução do servidor.py — inclusive o postgres:// legado do Render."""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    url = os.environ.get("DATABASE_URL") or f"sqlite:///{os.path.join(ROOT, 'doctrack.db')}"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def _ja_semeado(url):
    """Checagem barata (sem importar o servidor): as três tabelas têm linhas?

    Erro aqui significa banco novo, sem schema — e portanto sem amostra.
    """
    from sqlalchemy import create_engine, text
    eng = create_engine(url)
    try:
        with eng.connect() as con:
            for tabela in ("projetos", "missoes", "consumiveis"):
                if not con.execute(text(f"SELECT COUNT(*) FROM {tabela}")).scalar():
                    return False
        return True
    except Exception:
        return False
    finally:
        eng.dispose()


# ── ENTREGÁVEIS / PMO ────────────────────────────────────────────────────────

def _semear_projetos(db, models):
    """Quatro projetos que cobrem as faixas do semáforo de EVM.

    Os números são escolhidos para cair em cada faixa (SPI/CPI >= 0.95 verde,
    0.85-0.95 amarelo, < 0.85 vermelho): um dashboard de PMO onde tudo está verde
    não demonstra o dashboard.
    """
    Projeto, Entregavel, ProjetoMensal = models
    SPAN = 200          # dias de cronograma (início previsto → fim previsto)
    NOMES = ["Especificação técnica", "Projeto mecânico", "Projeto elétrico",
             "Protótipo", "Testes de bancada", "Documentação", "Homologação",
             "Treinamento", "Validação de campo", "Liberação final"]
    CATEGORIAS = ["Produto", "Sistema", "Documentação", "Capacitação", "Marketing"]
    RESPONSAVEIS = ["Carlos Mota", "Beatriz Souza", "Ana Lima", "Diego Ferreira"]

    def datas(pct_decorrido):
        passados = round(SPAN * pct_decorrido / 100)
        return ((HOJE - timedelta(days=passados)).isoformat(),
                (HOJE + timedelta(days=SPAN - passados)).isoformat())

    def criar(nome, tipo, sku, descricao, orcamento, pct_decorrido,
              n_concluidos, progressos, n_pendentes, ac_total, status="execucao"):
        ini, fim = datas(pct_decorrido)
        p = Projeto(nome=nome, tipo=tipo, sku=sku,
                    descricao=f"{descricao} {MARCA_DEMO}",
                    ano=HOJE.year, ativo=True, status=status,
                    orcamento=float(orcamento), moscow="Must",
                    data_inicio_prev=ini, data_inicio_real=ini, data_fim_prev=fim,
                    lancamento=str(HOJE.year))
        if status == "concluido":
            p.data_fim_real = HOJE.isoformat()
        db.session.add(p)
        db.session.flush()

        # `progressos` é a lista de percentuais dos entregáveis em andamento —
        # eles entram entre os concluídos e os pendentes. Sem essa faixa o funil
        # do dashboard mostrava "Em progresso: 0" e parecia um projeto parado.
        total = n_concluidos + len(progressos) + n_pendentes
        for i in range(total):
            if i < n_concluidos:
                status_e, percentual = "concluido", 100
            elif i < n_concluidos + len(progressos):
                status_e, percentual = "em_progresso", progressos[i - n_concluidos]
            else:
                status_e, percentual = "pendente", 0
            # Espalha as conclusões no passado para a curva-S ter inclinação.
            dt_concl = ((HOJE - timedelta(days=120 - i * 18)).isoformat()
                        if status_e == "concluido" else "")
            # O primeiro não-concluído vence 20 dias atrás: é o que popula
            # "atrasados" — um por projeto, o bastante para o alerta aparecer.
            fim_prev = (HOJE + timedelta(days=(i - n_concluidos) * 25 - 20)).isoformat()
            db.session.add(Entregavel(
                projeto_id=p.id, tipo=NOMES[i % len(NOMES)],
                categoria=CATEGORIAS[i % len(CATEGORIAS)],
                status=status_e, percentual=percentual,
                peso=2.0 if NOMES[i % len(NOMES)] == "Homologação" else 1.0,
                responsaveis=RESPONSAVEIS[i % len(RESPONSAVEIS)],
                data_inicio_prev=ini, data_fim_prev=fim_prev,
                data_inicio="" if status_e == "pendente" else ini,
                data_conclusao=dt_concl))

        # Custo real (AC) distribuído nos últimos 4 meses fechados.
        comps, ref = [], HOJE.replace(day=1)
        for _ in range(4):
            ref = (ref - timedelta(days=1)).replace(day=1)
            comps.insert(0, ref.strftime("%Y-%m"))
        parcela, acumulado = round(ac_total / len(comps)), 0
        for i, comp in enumerate(comps):
            valor = ac_total - acumulado if i == len(comps) - 1 else parcela
            acumulado += valor
            db.session.add(ProjetoMensal(projeto_id=p.id, competencia=comp,
                                         custo_mes=float(valor)))
        db.session.flush()
        p.recompute_acumulados()
        return p

    # Os quatro cobrem as faixas do semáforo de EVM. As cores saem da relação
    # entre prazo decorrido, avanço ponderado e custo — mexer em qualquer um dos
    # números recoloca o projeto em outra faixa, então confira com
    # `pmo_metrics()` depois de editar.
    projetos = [
        # 75% do prazo, 36% entregue, 70% do orçamento → SPI 0.48 / CPI 0.51.
        criar("Plataforma IoT Sentinela", "OEM", "IOT-SEN-01",
              "Gateway industrial de monitoramento", 100000, 75, 3, [50, 50], 5, 70000),
        # 74% do prazo, 67% entregue, 74% do orçamento → SPI e CPI ~0.90.
        criar("Linha de Envase Compacta", "Revenda", "ENV-CMP-02",
              "Envasadora semiautomática", 100000, 74, 5, [40, 30], 1, 74000),
        # 76% do prazo, 84% entregue, 76% do orçamento → SPI e CPI ~1.10.
        criar("Esteira de Inspeção Visão IA", "OEM", "INS-IA-03",
              "Inspeção óptica com visão computacional", 100000, 76, 7, [70, 50], 1, 76000),
        criar("Bancada de Calibração Modular", "OEM", "CAL-MOD-04",
              "Bancada de calibração multiponto", 80000, 100, 10, [], 0, 78000,
              status="concluido"),
    ]
    db.session.commit()
    return projetos


# ── MISSÕES (kanban) ─────────────────────────────────────────────────────────

def _semear_missoes(db, models, equipamentos, projetos, usuarios):
    """Dois boards com cartões distribuídos pelas colunas, com aging e atraso.

    Cartões concluídos recebem `criado_em`/`concluido_em` no passado: sem eles o
    lead time e o gráfico de fluxo saem vazios mesmo com o board cheio.
    """
    Missao, MissaoColuna, MissaoCartao, MissaoCartaoItem, MissaoCartaoComentario = models
    COLUNAS = [("A fazer", "todo", "#94a3b8"), ("Fazendo", "doing", "#f59e0b"),
               ("Concluído", "done", "#10b981")]

    def criar_board(nome, descricao, accent, ordem, cartoes):
        m = Missao(nome=nome, descricao=f"{descricao} {MARCA_DEMO}", accent=accent,
                   ordem=ordem, criado_por="admin@pde.com",
                   criado_em=AGORA - timedelta(days=45))
        db.session.add(m)
        db.session.flush()

        cols = []
        for i, (nome_col, cat, cor) in enumerate(COLUNAS):
            c = MissaoColuna(missao_id=m.id, nome=nome_col, categoria=cat, cor=cor,
                             ordem=i, limite_wip=4 if cat == "doing" else 0)
            db.session.add(c)
            cols.append(c)
        db.session.flush()

        for ordem_cartao, dados in enumerate(cartoes):
            idx_col = dados["coluna"]
            concluido = COLUNAS[idx_col][1] == "done"
            idade = dados.get("idade", 10)
            cartao = MissaoCartao(
                missao_id=m.id, coluna_id=cols[idx_col].id,
                titulo=dados["titulo"], descricao=dados.get("descricao", ""),
                responsaveis=dados.get("resp", ""),
                prazo=dados.get("prazo", ""), prioridade=dados.get("pri", "media"),
                etiquetas=dados.get("tags", ""), concluido=concluido,
                ordem=ordem_cartao, peso=dados.get("peso", 1.0),
                ref_tipo=dados.get("ref_tipo", ""), ref_id=dados.get("ref_id"),
                criado_por="admin@pde.com", atualizado_por="admin@pde.com",
                criado_em=AGORA - timedelta(days=idade),
                entrou_coluna_em=AGORA - timedelta(days=dados.get("parado", 3)),
                data_inicio=(HOJE - timedelta(days=idade)).isoformat(),
                concluido_em=(AGORA - timedelta(days=dados["fechado_ha"])
                              if concluido else None),
                concluido_por="admin@pde.com" if concluido else "",
            )
            db.session.add(cartao)
            db.session.flush()
            # Vincula os responsáveis também pelo N:N (a UI filtra por usuário).
            for nome_resp in [n.strip() for n in dados.get("resp", "").split(",") if n.strip()]:
                u = usuarios.get(nome_resp)
                if u:
                    cartao.responsaveis_users.append(u)
            for j, (texto, feito) in enumerate(dados.get("itens", [])):
                db.session.add(MissaoCartaoItem(cartao_id=cartao.id, texto=texto,
                                                feito=feito, ordem=j))
            for texto, por, dias in dados.get("comentarios", []):
                db.session.add(MissaoCartaoComentario(cartao_id=cartao.id, texto=texto,
                                                      por=por, em=AGORA - timedelta(days=dias)))
        return m

    # `ref` liga o cartão a um equipamento real — é o chip de contexto no cartão.
    eq = lambda i: {"ref_tipo": "equipamento", "ref_id": equipamentos[i].id} if len(equipamentos) > i else {}
    pj = lambda i: {"ref_tipo": "projeto", "ref_id": projetos[i].id} if len(projetos) > i else {}

    board_doc = criar_board(
        "Documentação Técnica — Ciclo 2026", "Fila de elaboração e revisão de ITs",
        "#2563eb", 0,
        [
            dict(coluna=0, titulo="Revisar IT de operação da Extracta 96",
                 descricao="Atualizar o passo a passo após a mudança do bloco térmico.",
                 resp="Ana Lima", pri="alta", tags="IT,revisão",
                 prazo=(HOJE - timedelta(days=4)).isoformat(), idade=22, parado=12,
                 itens=[("Levantar versão vigente", True), ("Conferir fotos", False),
                        ("Enviar para homologação", False)],
                 comentarios=[("Bloco térmico novo chegou, dá para fotografar.", "Ana Lima", 3)],
                 **eq(0)),
            dict(coluna=0, titulo="Checklist de conferência — linha de extração",
                 resp="Diego Ferreira", pri="media", tags="checklist",
                 prazo=(HOJE + timedelta(days=12)).isoformat(), idade=15, parado=15),
            dict(coluna=0, titulo="Padronizar cabeçalho dos manuais do fabricante",
                 resp="Beatriz Souza", pri="baixa", tags="manuais,padronização",
                 idade=30, parado=30),
            dict(coluna=1, titulo="Elaborar IT de manutenção preventiva",
                 descricao="Primeira versão a partir do manual do fabricante.",
                 resp="Ana Lima, Diego Ferreira", pri="urgente", tags="IT,preventiva",
                 prazo=(HOJE + timedelta(days=3)).isoformat(), idade=18, parado=6, peso=2.0,
                 itens=[("Extrair procedimento do manual", True),
                        ("Escrever passo a passo", True), ("Revisão técnica", False)],
                 **eq(1)),
            dict(coluna=1, titulo="Treinamento piloto — equipe de campo",
                 resp="Carlos Mota", pri="alta", tags="treinamento",
                 prazo=(HOJE + timedelta(days=8)).isoformat(), idade=25, parado=9),
            dict(coluna=2, titulo="Homologar IT de instalação",
                 resp="Beatriz Souza", pri="media", tags="IT,homologado",
                 idade=52, parado=14, fechado_ha=14,
                 itens=[("Revisão 1", True), ("Revisão 2", True), ("Aprovação", True)]),
            dict(coluna=2, titulo="Publicar manual traduzido do fabricante",
                 resp="Diego Ferreira", pri="baixa", tags="manuais",
                 idade=60, parado=28, fechado_ha=28),
            dict(coluna=2, titulo="Mapear documentos sem responsável definido",
                 resp="Carlos Mota", pri="media", tags="auditoria",
                 idade=40, parado=7, fechado_ha=7),
        ])

    board_proj = criar_board(
        "Portfólio PDE — Acompanhamento", "Frentes de engenharia por projeto",
        "#7c3aed", 1,
        [
            dict(coluna=0, titulo="Definir escopo do gateway industrial",
                 resp="Carlos Mota", pri="alta", tags="escopo",
                 prazo=(HOJE + timedelta(days=20)).isoformat(), idade=12, parado=12, **pj(0)),
            dict(coluna=0, titulo="Cotação de fornecedores — sensores",
                 resp="Beatriz Souza", pri="media", tags="suprimentos",
                 prazo=(HOJE - timedelta(days=2)).isoformat(), idade=26, parado=18),
            dict(coluna=1, titulo="Montagem do protótipo da esteira",
                 descricao="Integração da câmera com o CLP.",
                 resp="Diego Ferreira", pri="urgente", tags="protótipo,hardware",
                 prazo=(HOJE + timedelta(days=5)).isoformat(), idade=33, parado=4, peso=3.0,
                 itens=[("Estrutura mecânica", True), ("Câmera integrada", True),
                        ("Rotina de inspeção", False), ("Ensaio de repetibilidade", False)],
                 comentarios=[("Lente atual não cobre a largura da esteira.", "Diego Ferreira", 2)],
                 **pj(2)),
            dict(coluna=1, titulo="Validar consumo energético da envasadora",
                 resp="Ana Lima", pri="media", tags="ensaio",
                 prazo=(HOJE + timedelta(days=15)).isoformat(), idade=20, parado=8, **pj(1)),
            dict(coluna=2, titulo="Encerrar bancada de calibração modular",
                 resp="Carlos Mota", pri="alta", tags="entrega",
                 idade=90, parado=5, fechado_ha=5, peso=2.0,
                 itens=[("Ensaio final", True), ("Documentação entregue", True)]),
            dict(coluna=2, titulo="Aprovar orçamento do ciclo 2026",
                 resp="Beatriz Souza", pri="media", tags="pmo",
                 idade=75, parado=35, fechado_ha=35),
        ])

    db.session.commit()
    return [board_doc, board_proj]


# ── CONSUMÍVEIS ──────────────────────────────────────────────────────────────

def _semear_consumiveis(db, models, equipamentos):
    """Catálogo pequeno mas representativo, com compatibilidade N:N real.

    Dois itens saem sem SKU de propósito: é o que faz o filtro "pendente de SKU"
    ter o que mostrar.
    """
    Consumivel, TipoConsumivel, ConsumivelEquipamento = models
    tipos = {t.nome: t for t in TipoConsumivel.query.all()}

    CATALOGO = [
        ("Ponteira 200 µL com filtro", "CON-PT-200F", "Ponteira", "Loccus",
         {"volume": 200, "com_filtro": True, "esterilidade": "Estéril",
          "material": "Polipropileno", "apresentacao": "Rack com 96"},
         "exclusivo_loccus", True),
        ("Ponteira 1000 µL sem filtro", "CON-PT-1000", "Ponteira", "Loccus",
         {"volume": 1000, "com_filtro": False, "esterilidade": "Não estéril",
          "material": "Polipropileno", "apresentacao": "Saco com 500"},
         "pode_fornecer", True),
        ("Ponteira 10 µL baixa retenção", "", "Ponteira", "Genérico",
         {"volume": 10, "com_filtro": True, "esterilidade": "Estéril",
          "material": "Polipropileno", "apresentacao": "Rack com 96"},
         "nao_informado", False),
        ("Placa PCR 96 poços saia completa", "CON-PL-96SC", "Placa PCR", "Loccus",
         {"pocos": 96, "saia": "Completa", "volume_poco": "200 µL",
          "material": "Polipropileno", "dimensoes": "128 x 86 mm", "esterilidade": "Estéril"},
         "exclusivo_loccus", True),
        ("Placa PCR 384 poços", "CON-PL-384", "Placa PCR", "Loccus",
         {"pocos": 384, "saia": "Completa", "volume_poco": "40 µL",
          "material": "Polipropileno", "dimensoes": "128 x 86 mm", "esterilidade": "Estéril"},
         "pode_fornecer", False),
        ("Placa deepwell 96 x 2 mL", "CON-DW-96", "Placa deepwell", "Loccus",
         {"pocos": 96, "volume_poco": "2 mL", "fundo": "U",
          "material": "Polipropileno", "dimensoes": "128 x 86 mm"},
         "exclusivo_loccus", True),
        ("Kit de extração magnética — DNA/RNA", "CON-KIT-MAG", "Kit de extração", "Loccus",
         {"metodo": "Beads magnéticas", "alvo": "DNA/RNA", "reacoes": 96},
         "exclusivo_loccus", True),
        ("MasterMix qPCR 2x", "CON-MM-2X", "MasterMix / Reagente", "Loccus",
         {"volume": "1,25 mL", "concentracao": "2x", "reacoes": 200,
          "armazenamento": "-20 °C"},
         "exclusivo_loccus", False),
        ("Filme de vedação óptico", "CON-FV-OPT", "Filme de vedação", "Genérico",
         {"largura": "80", "comprimento": "50", "material": "Poliéster",
          "aplicacao": "qPCR"},
         "pode_fornecer", True),
        ("Reservatório 25 mL 8 calhas", "CON-RS-25", "Reservatório", "Genérico",
         {"volume": "25", "calhas": 8, "material": "Poliestireno"},
         "nao_fornecido", False),
        ("Tubo cônico 15 mL", "CON-TB-15", "Tubo", "Genérico",
         {"volume": "15", "material": "Polipropileno"},
         "nao_fornecido", False),
        ("Tip comb 8 canais", "", "Tip comb / tira", "Loccus",
         {"canais": 8, "material": "Polipropileno"},
         "nao_informado", False),
    ]

    criados = []
    for i, (nome, sku, tipo_nome, fabricante, atributos, fornecimento, obrigatorio) in enumerate(CATALOGO):
        c = Consumivel(nome=nome, sku=sku, sku_importacao=MARCA_DEMO,
                       fabricante=fabricante,
                       descricao=f"Item de catálogo para demonstração — {tipo_nome.lower()}.",
                       tipo_id=tipos[tipo_nome].id if tipo_nome in tipos else None,
                       atributos=json.dumps(atributos, ensure_ascii=False),
                       status="Ativo", ativo=True)
        c.marcar_pendencia_sku()
        db.session.add(c)
        db.session.flush()
        criados.append(c)

        # Cada consumível serve de 2 a 4 equipamentos — a matriz N:N é o ponto
        # do módulo, um vínculo por item não demonstraria nada.
        if equipamentos:
            for j in range(2 + (i % 3)):
                eqp = equipamentos[(i * 3 + j) % len(equipamentos)]
                existe = ConsumivelEquipamento.query.filter_by(
                    consumivel_id=c.id, equipamento_id=eqp.id).first()
                if existe:
                    continue
                db.session.add(ConsumivelEquipamento(
                    consumivel_id=c.id, equipamento_id=eqp.id,
                    fornecimento=fornecimento, obrigatorio=obrigatorio and j == 0,
                    observacao="Compatibilidade validada em bancada." if j == 0 else ""))
    db.session.commit()
    return criados


# ── EQUIPAMENTOS E DOCUMENTOS (enriquecimento) ───────────────────────────────
# Diferente do resto deste arquivo, o que vem abaixo ALTERA linhas que vieram das
# planilhas em vez de criar linhas novas — por isso só roda com DOCTRACK_SEED_DEMO=1
# (que o render.yaml define) ou com --enriquecer. Rodar sem querer contra o banco
# interno preencheria responsável e prazo de 522 documentos reais.
#
# O motivo de existir: a planilha traz nome e SKU do equipamento e mais nada.
# Sem categoria, sem dados regulatórios e sem dono, o ICE da frota inteira fica
# abaixo de 50% e o dashboard de equipamentos vira uma parede de zeros — os
# gráficos de risco regulatório e de distribuição por categoria ficam vazios.
#
# Nada preenchido é sobrescrito: cada campo só é tocado se estiver vazio, então
# rodar de novo não muda nada e `--remover` não precisa desfazer.

CATEGORIAS_SEED = {
    "Extração de ácidos nucleicos": ["Extratores automáticos", "Extratores manuais"],
    "Amplificação / PCR":           ["Termocicladores", "qPCR em tempo real"],
    "Preparo de amostras":          ["Homogeneizadores", "Centrífugas"],
    "Sequenciamento":               ["Preparo de biblioteca"],
    "Suporte laboratorial":         ["Incubadoras", "Bancada e acessórios"],
}
FABRICANTES = ["Loccus", "Loccus do Brasil", "Kasvi", "Bioer", "Hangzhou Allsheng"]
DONOS = ["Carlos Mota", "Beatriz Souza", "Ana Lima", "Diego Ferreira"]


def _semear_taxonomia(db, Categoria, Familia):
    """Categorias e famílias (get-or-create pelo nome, nunca apagadas)."""
    cats, fams = {}, []
    for ordem, (nome_cat, nomes_fam) in enumerate(CATEGORIAS_SEED.items()):
        cat = Categoria.query.filter_by(nome=nome_cat).first()
        if not cat:
            cat = Categoria(nome=nome_cat, ordem=ordem, ativo=True)
            db.session.add(cat)
            db.session.flush()
        cats[nome_cat] = cat
        for i, nome_fam in enumerate(nomes_fam):
            fam = Familia.query.filter_by(categoria_id=cat.id, nome=nome_fam).first()
            if not fam:
                fam = Familia(categoria_id=cat.id, nome=nome_fam, ordem=i, ativo=True)
                db.session.add(fam)
                db.session.flush()
            fams.append(fam)
    db.session.commit()
    return cats, fams


def _enriquecer_equipamentos(db, equipamentos, cats, fams):
    """Distribui a frota em três faixas de completude (ICE).

    Uma frota toda verde não demonstra o índice, e uma toda vermelha (o estado de
    hoje) não demonstra nada. A cada três equipamentos: um completo, um parcial,
    um intocado.
    """
    lista_cats = list(cats.values())
    faixas = {"completo": 0, "parcial": 0, "intocado": 0}

    def preencher(obj, campo, valor):
        """Só escreve em campo vazio — o que veio da planilha manda."""
        if not (getattr(obj, campo, "") or "").strip():
            setattr(obj, campo, valor)

    for i, eq in enumerate(equipamentos):
        tier = i % 3
        if tier == 2:
            faixas["intocado"] += 1
            continue

        fam = fams[i % len(fams)]
        preencher(eq, "nome_tecnico", f"{eq.nome} — sistema automatizado de bancada")
        preencher(eq, "fabricante", FABRICANTES[i % len(FABRICANTES)])
        preencher(eq, "responsavel", DONOS[i % len(DONOS)])
        if not eq.categoria_id:
            eq.categoria_id = (fam.categoria_id if fam else lista_cats[i % len(lista_cats)].id)

        if tier == 0:
            # Completo: cadastro cheio e registro ANVISA válido.
            faixas["completo"] += 1
            preencher(eq, "sku_importacao", f"IMP-{1000 + i}")
            if not eq.familia_id:
                eq.familia_id = fam.id if fam else None
            preencher(eq, "classificacao_reg", "IVD")
            preencher(eq, "anvisa", f"8010{i:03d}0{i % 10}")
            preencher(eq, "anvisa_registro",
                      (HOJE - timedelta(days=900 + i * 7)).isoformat())
            # Duas validades vencidas e três vencendo em <=90 dias: sem elas os
            # cartões de risco regulatório do dashboard ficam zerados.
            posicao = i // 3
            if posicao % 7 == 1:
                dias = -45 - posicao            # vencido
            elif posicao % 7 in (2, 4):
                dias = 30 + posicao * 5         # vencendo (<= 90)
            else:
                dias = 500 + posicao * 30       # tranquilo
            preencher(eq, "anvisa_validade", (HOJE + timedelta(days=dias)).isoformat())
            for campo in ("rev_cadastro", "rev_estrutura", "rev_descritivo"):
                if (getattr(eq, campo, "") or "Pendente") == "Pendente":
                    setattr(eq, campo, "Revisado")
        else:
            # Parcial: RUO não exige registro ANVISA, então o subíndice
            # regulatório fecha só com a classificação — sem família, o cadastro
            # fica incompleto de propósito.
            faixas["parcial"] += 1
            preencher(eq, "classificacao_reg", "RUO")
            if (eq.rev_cadastro or "Pendente") == "Pendente":
                eq.rev_cadastro = "Revisado"

    db.session.commit()
    return faixas


def _enriquecer_documentos(db, Documento, DocumentoHistorico, equipamentos):
    """Dono, idade, prazo e aging nos documentos; conclui parte do primeiro tier.

    Quatro painéis do dashboard dependem disto e hoje aparecem vazios ou zerados:
    "Carga por responsável" (2 dos 522 documentos têm dono), "Precisa de atenção"
    (nenhum documento tem prazo, logo nenhum está atrasado), "Parados há mais
    tempo" (o backfill carimba `entrou_status_em` no instante da importação, e
    todo documento nasce com 0 dia parado) e o tempo de ciclo (todo documento tem
    `criado_em` na data do import, então concluir hoje daria ciclo zero).

    Concluir um documento aqui exige gravar a transição em `documento_historico`,
    não só escrever `concluido_em`: `_backfill_marcos_documentos` APAGA, a cada
    subida do servidor, toda data de conclusão sem transição real na trilha —
    exatamente para não inventar throughput. Sem a linha de histórico, o seed
    seria desfeito no primeiro boot.
    """
    docs = Documento.query.filter_by(ativo=True).order_by(Documento.id).all()
    # O ICE só chega a "completo" com o subíndice documental alto; estes são os
    # equipamentos do tier 0 de _enriquecer_equipamentos.
    ids_completos = {e.id for i, e in enumerate(equipamentos) if i % 3 == 0}
    n_dono = n_prazo = n_idade = n_final = 0

    for i, d in enumerate(docs):
        if not (d.responsavel or "").strip():
            d.responsavel = DONOS[i % len(DONOS)]
            n_dono += 1

        # Idade do documento: 120 a 540 dias. É o que dá lastro ao tempo de
        # ciclo — a conclusão sempre cai depois da criação.
        idade = 120 + (i * 23) % 420
        if d.criado_em is None or d.criado_em.date() >= HOJE:
            d.criado_em = AGORA - timedelta(days=idade)
            n_idade += 1
        else:
            idade = max((AGORA - d.criado_em).days, 2)

        finalizado = d.status_global == "Finalizado"
        # 2 de cada 3 documentos dos equipamentos "completos" passam a
        # finalizados — sem isso o subíndice documental trava o ICE deles.
        vai_finalizar = (not finalizado and d.equipamento_id in ids_completos
                         and i % 3 != 0 and (d.status or "") == "Elaborar")

        if vai_finalizar:
            antigo = d.status or "Elaborar"
            d.status = "Homologado" if (d.setor or "") == "PRE" else "Concluído"
            # Conclusões de 2 a 87 dias atrás: parte cai na janela de 30 dias do
            # throughput, o resto alimenta o tempo de ciclo.
            quando = AGORA - timedelta(days=min(2 + (i * 11) % 85, idade - 1))
            d.concluido_em = quando
            d.concluido_por = d.responsavel or "admin@pde.com"
            d.entrou_status_em = quando
            db.session.add(DocumentoHistorico(
                documento_id=d.id, evento="status", status_antigo=antigo,
                status_novo=d.status, em=quando,
                por=d.responsavel or "admin@pde.com"))
            n_final += 1
            continue

        if finalizado:
            continue

        # Aging do que segue aberto: 3 a ~250 dias parado, sempre depois da
        # criação. O backfill só recalcula quando a coluna está nula, então o
        # valor espalhado aqui sobrevive.
        d.entrou_status_em = AGORA - timedelta(days=min(3 + (i * 17) % 250, idade - 1))

        if d.prazo is None:
            # 1 em cada 4 vence no passado → alimenta "atrasados".
            offset = -((i * 11) % 60) - 5 if i % 4 == 0 else ((i * 13) % 120) + 5
            d.prazo = HOJE + timedelta(days=offset)
            n_prazo += 1

    db.session.commit()
    return {"responsavel": n_dono, "prazo": n_prazo, "idade": n_idade, "finalizados": n_final}


# ── REMOÇÃO ──────────────────────────────────────────────────────────────────

def _remover_demo(db, mods):
    """Apaga só o que carrega a MARCA_DEMO. O cascade cuida dos filhos."""
    n = 0
    for p in mods["Projeto"].query.filter(mods["Projeto"].descricao.like(f"%{MARCA_DEMO}%")).all():
        db.session.delete(p); n += 1
    for m in mods["Missao"].query.filter(mods["Missao"].descricao.like(f"%{MARCA_DEMO}%")).all():
        db.session.delete(m); n += 1
    for c in mods["Consumivel"].query.filter_by(sku_importacao=MARCA_DEMO).all():
        for v in mods["ConsumivelEquipamento"].query.filter_by(consumivel_id=c.id).all():
            db.session.delete(v)
        db.session.delete(c); n += 1
    db.session.commit()
    return n


def main():
    ap = argparse.ArgumentParser(description="Dados de amostra para demonstração.")
    ap.add_argument("--forcar", action="store_true", help="apaga a amostra anterior e recria")
    ap.add_argument("--remover", action="store_true", help="só apaga a amostra")
    ap.add_argument("--enriquecer", action="store_true",
                    help="preenche campos vazios dos equipamentos e documentos "
                         "vindos das planilhas (implícito com DOCTRACK_SEED_DEMO=1)")
    args = ap.parse_args()
    # O enriquecimento altera linhas existentes, então exige intenção explícita:
    # o render.yaml declara DOCTRACK_SEED_DEMO=1, o servidor interno não.
    enriquecer = args.enriquecer or os.environ.get(
        "DOCTRACK_SEED_DEMO", "").lower() in ("1", "true", "t")

    url = _url_banco()
    if not args.forcar and not args.remover and _ja_semeado(url):
        print("[seed_demo] amostra já presente — nada a fazer.")
        return 0

    # A partir daqui o servidor é necessário: `init_app()` garante schema, os
    # usuários demo e os equipamentos que os vínculos abaixo referenciam.
    os.chdir(ROOT)
    import servidor
    from models import (db, Projeto, Entregavel, ProjetoMensal, Equipamento, User,
                        Documento, DocumentoHistorico,
                        CategoriaEquipamento, FamiliaEquipamento,
                        Consumivel, TipoConsumivel, ConsumivelEquipamento,
                        Missao, MissaoColuna, MissaoCartao, MissaoCartaoItem,
                        MissaoCartaoComentario)

    servidor.init_app()
    with servidor.app.app_context():
        mods = {"Projeto": Projeto, "Missao": Missao, "Consumivel": Consumivel,
                "ConsumivelEquipamento": ConsumivelEquipamento}
        if args.forcar or args.remover:
            print(f"[seed_demo] removidos {_remover_demo(db, mods)} registro(s) de amostra.")
            if args.remover:
                return 0

        frota = (Equipamento.query.filter_by(ativo=True)
                 .order_by(Equipamento.nome).all())
        # Os vínculos de consumível usam só uma fatia: espalhar 12 consumíveis
        # por 43 equipamentos deixaria quase toda ficha com nenhum item.
        equipamentos = frota[:24]
        usuarios = {u.nome: u for u in User.query.all()}

        if enriquecer:
            cats, fams = _semear_taxonomia(db, CategoriaEquipamento, FamiliaEquipamento)
            faixas = _enriquecer_equipamentos(db, frota, cats, fams)
            print(f"[seed_demo] taxonomia: {len(cats)} categoria(s), {len(fams)} família(s); "
                  f"frota: {faixas['completo']} completo(s), {faixas['parcial']} parcial(is), "
                  f"{faixas['intocado']} intocado(s).")
            n = _enriquecer_documentos(db, Documento, DocumentoHistorico, frota)
            print(f"[seed_demo] documentos: {n['responsavel']} com dono, {n['prazo']} com prazo, "
                  f"{n['idade']} datados, {n['finalizados']} finalizados com trilha.")

        projetos = _semear_projetos(db, (Projeto, Entregavel, ProjetoMensal))
        print(f"[seed_demo] {len(projetos)} projeto(s) + entregáveis e custos mensais.")

        boards = _semear_missoes(
            db, (Missao, MissaoColuna, MissaoCartao, MissaoCartaoItem, MissaoCartaoComentario),
            equipamentos, projetos, usuarios)
        print(f"[seed_demo] {len(boards)} board(s) de missões com cartões.")

        consumiveis = _semear_consumiveis(
            db, (Consumivel, TipoConsumivel, ConsumivelEquipamento), equipamentos)
        print(f"[seed_demo] {len(consumiveis)} consumível(is) com compatibilidade por equipamento.")

    print("[seed_demo] OK — amostra pronta.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as err:
        # Falha aqui não pode derrubar o deploy: o Render encadeia este script
        # com o gunicorn no mesmo `startCommand`, e a plataforma sem a amostra
        # ainda é melhor do que a plataforma fora do ar.
        print(f"[seed_demo] FALHOU (seguindo assim mesmo): {err}")
        sys.exit(0)
