r"""Semeia dados de DEMONSTRAÇÃO em Documentos, Equipamentos e Missões.

Complementa `simular_projetos.py` (que cobre o portfólio/PMO) nos módulos que
ficaram sem história sintética: as métricas de fluxo de Documentos e Missões
dependem de uma TRILHA de transições ao longo do tempo, e num banco recém
instrumentado essa trilha está vazia — o painel nasce com throughput 0 e sem
tempo de ciclo, o que é correto mas não dá para testar.

O que este script gera, e por quê:
  • Equipamentos com taxonomia e regulatório preenchidos → ICE/IDP saem do zero
  • Os 12 documentos canônicos de cada um, em estágios variados do pipeline
  • TRILHA retroativa com transições REAIS (status_antigo preenchido), espalhada
    nos últimos ~6 meses → cycle time, throughput por semana e aging
  • Responsáveis via N:N → carga por pessoa
  • Prazos vencidos, a vencer e ausentes → alertas nas três severidades
  • Alguns N/A com motivo da lista fechada → agregado de motivos
  • Missão com kanban, cartões em várias colunas e trilha própria
  • Snapshots retroativos semanais → gráficos de evolução com série de verdade

TUDO é marcado com o prefixo `DEMO ` no nome do equipamento e da missão, então
a limpeza é exaustiva e não toca em dado real:

    .\venv\Scripts\python.exe scripts\semear_demo.py            # cria
    .\venv\Scripts\python.exe scripts\semear_demo.py --limpar   # remove só o DEMO

Determinístico (semente fixa): rodar duas vezes dá o mesmo resultado, e criar
de novo recria do zero em vez de duplicar.
"""
import argparse
import os
import random
import sys
from datetime import date, datetime, time, timedelta

from dotenv import load_dotenv
from flask import Flask

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

load_dotenv(os.path.join(ROOT, ".env"))
DB_PATH = os.path.join(ROOT, "doctrack.db")
url = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql://", 1)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

from models import (  # noqa: E402
    db, bcrypt, User, Documento, DocumentoHistorico, Equipamento,
    EquipamentoSnapshot, Missao, MissaoColuna, MissaoCartao,
    MissaoCartaoHistorico, MissaoSnapshot,
    CategoriaEquipamento, FamiliaEquipamento, LinhaProduto,
    TIPOS_DOC_TODOS, TIPOS_DOC_OPCIONAIS, SETOR_DO_TIPO, TIPOS_DOC_LABELS,
    STATUS_PRE, STATUS_FABRICANTE, MOTIVOS_NA,
)

db.init_app(app)
bcrypt.init_app(app)

PREFIXO = "DEMO "          # marca de tudo que este script cria
AUTOR = "demo@doctrack"    # autor das linhas de trilha sintéticas
HOJE = date.today()
random.seed(20260726)      # determinístico

# ── CATÁLOGO INVENTADO ───────────────────────────────────────────────────────
# Nomes plausíveis para um fabricante de equipamentos laboratoriais, mas todos
# claramente fictícios e prefixados.
EQUIPAMENTOS = [
    # (nome, modelo, fabricante, familia, classe_risco, anvisa, tecnologia, maturidade)
    # maturidade 0..1 = quão avançado está o pacote documental
    ("Analisador Hemato H-900", "H-900", "Zentrix Medical", "Hematologia",
     "II", "80142310099", "Citometria de fluxo por impedância", 0.95),
    ("Analisador Bioquímico BQ-450", "BQ-450", "Zentrix Medical", "Bioquímica",
     "II", "80142310100", "Espectrofotometria de absorção", 0.75),
    ("Termociclador RT-Pulse 96", "RT-P96", "Nordic Biotech", "Molecular",
     "III", "80142310101", "PCR em tempo real com óptica multiplex", 0.55),
    ("Centrífuga Refrigerada CR-16", "CR-16", "Vortec Instrumentos", "Preparo de amostra",
     "I", "", "Rotor angular refrigerado a compressor", 0.40),
    ("Coagulômetro Coag-4X", "CG-4X", "Nordic Biotech", "Hemostasia",
     "II", "80142310102", "Turbidimetria de 4 canais", 0.25),
    ("Lavadora de Microplacas WP-8", "WP-8", "Vortec Instrumentos", "Imunoensaio",
     "I", "", "Aspiração e dispensa programável de 8 canais", 0.10),
    ("Leitor de Microplacas ELISA-Pro", "EL-PRO", "Helix Diagnóstica", "Imunoensaio",
     "II", "80142310103", "Fotometria de filtro em 6 comprimentos", 0.65),
    ("Autoclave Vertical AV-75", "AV-75", "Vortec Instrumentos", "Esterilização",
     "II", "80142310104", "Vapor saturado com secagem a vácuo", 0.85),
]

CATEGORIAS = ["Diagnóstico In Vitro", "Apoio Laboratorial"]
LINHAS = ["Linha Premium", "Linha Essencial"]

# Peso relativo por tipo: um manual de serviço não custa o mesmo que um
# checklist de uma página. É o que faz o avanço ponderado divergir do simples.
PESOS_TIPO = {
    "IT": 3, "Checklist_Conferencia": 1, "Checklist_BurnIn": 2,
    "Checklist_Limpeza_Embalagem": 1, "Checklist_Produto": 2,
    "Manual_Usuario": 5, "Manual_ES": 4, "Manual_Servico": 8,
    "Spare_Parts": 3, "Dossie": 8, "Guia_Instalacao": 3, "QIQOQD": 5,
}

MOTIVOS = [m for m in MOTIVOS_NA if m != "outro"]

CARTOES_MISSAO = [
    ("Fechar especificação do rotor da CR-16", "alta", ["Engenharia"]),
    ("Revisar laudo de compatibilidade eletromagnética", "alta", ["Regulatório"]),
    ("Traduzir manual do usuário do H-900 para espanhol", "media", ["Documentação"]),
    ("Refazer teste de burn-in do lote piloto", "alta", ["Qualidade"]),
    ("Cotar fornecedor alternativo de óptica do RT-Pulse", "media", ["Suprimentos"]),
    ("Atualizar dossiê técnico do Coag-4X", "alta", ["Regulatório"]),
    ("Preparar treinamento de campo do ELISA-Pro", "baixa", ["Treinamento"]),
    ("Padronizar etiquetas de embalagem da linha Essencial", "baixa", ["Produção"]),
    ("Validar firmware 2.4 do BQ-450", "media", ["Engenharia"]),
    ("Levantar peças de reposição da autoclave AV-75", "media", ["Suprimentos"]),
    ("Corrigir divergência de SKU no cadastro da WP-8", "alta", ["Qualidade"]),
    ("Escrever guia rápido de instalação do H-900", "baixa", ["Documentação"]),
]

COLUNAS_MISSAO = [
    ("A fazer", "backlog", "#64748b", 0),
    ("Em andamento", "doing", "#22d3ee", 4),
    ("Em revisão", "doing", "#a78bfa", 3),
    ("Concluído", "done", "#10b981", 0),
]


def _dt(dias_atras, hora=10):
    """Datetime a N dias no passado, em horário comercial (a trilha fica legível)."""
    return datetime.combine(HOJE - timedelta(days=dias_atras),
                            time(hour=hora, minute=random.randint(0, 59)))


# ── LIMPEZA ──────────────────────────────────────────────────────────────────
def limpar():
    """Remove tudo que este script cria. Só toca no que tem o prefixo DEMO."""
    equips = Equipamento.query.filter(Equipamento.nome.like(f"{PREFIXO}%")).all()
    ids = [e.id for e in equips]
    nomes = [e.nome for e in equips]

    docs = Documento.query.filter(
        db.or_(Documento.equipamento_id.in_(ids) if ids else db.false(),
               Documento.equipamento.in_(nomes) if nomes else db.false())).all()
    n_docs = len(docs)
    for d in docs:
        DocumentoHistorico.query.filter_by(documento_id=d.id).delete()
        d.responsaveis_users = []
        db.session.delete(d)

    for e in equips:
        EquipamentoSnapshot.query.filter_by(equipamento_id=e.id).delete()
        db.session.delete(e)

    missoes = Missao.query.filter(Missao.nome.like(f"{PREFIXO}%")).all()
    for m in missoes:
        MissaoSnapshot.query.filter_by(missao_id=m.id).delete()
        MissaoCartaoHistorico.query.filter_by(missao_id=m.id).delete()
        for c in MissaoCartao.query.filter_by(missao_id=m.id).all():
            c.responsaveis_users = []
            db.session.delete(c)
        db.session.delete(m)

    # Taxonomia criada aqui só sai se ninguém mais estiver usando.
    for modelo in (LinhaProduto, FamiliaEquipamento, CategoriaEquipamento):
        for t in modelo.query.filter(modelo.nome.like(f"{PREFIXO}%")).all():
            db.session.delete(t)

    db.session.commit()
    print(f"[OK] Removidos: {len(equips)} equipamento(s), {n_docs} documento(s), "
          f"{len(missoes)} missão(ões) de demonstração.")


# ── TAXONOMIA ────────────────────────────────────────────────────────────────
def semear_taxonomia():
    """Categoria → Família (a família pertence a uma categoria) + Linha solta."""
    cats, fams, linhas = {}, {}, {}
    for nome in CATEGORIAS:
        c = CategoriaEquipamento(nome=PREFIXO + nome)
        db.session.add(c)
        cats[nome] = c
    db.session.flush()

    # Famílias de diagnóstico ficam na categoria DIV; as de apoio, na de apoio.
    APOIO = {"Preparo de amostra", "Esterilização"}
    for i, (nome, mod, fab, familia, *_ ) in enumerate(EQUIPAMENTOS):
        if familia in fams:
            continue
        cat = cats[CATEGORIAS[1] if familia in APOIO else CATEGORIAS[0]]
        f = FamiliaEquipamento(nome=PREFIXO + familia, categoria_id=cat.id)
        db.session.add(f)
        fams[familia] = f

    for nome in LINHAS:
        linha = LinhaProduto(nome=PREFIXO + nome)
        db.session.add(linha)
        linhas[nome] = linha
    db.session.flush()
    return cats, fams, linhas


# ── DOCUMENTOS + TRILHA ──────────────────────────────────────────────────────
def _plano_do_documento(tipo, maturidade):
    """Decide o destino de um documento: (status_final, dias_atras_da_conclusao).

    `maturidade` do equipamento inclina o sorteio — um produto maduro tem o
    pacote quase completo, um recém-iniciado tem quase tudo em Elaborar. Sem
    esse viés todos os equipamentos ficariam com o mesmo ICE e o ranking de
    completude não mostraria nada.
    """
    setor = SETOR_DO_TIPO[tipo]
    pipeline = STATUS_PRE if setor == "PRE" else STATUS_FABRICANTE
    sorteio = random.random()
    # quanto maior a maturidade, mais para o fim do pipeline o documento chega
    if sorteio < maturidade * 0.85:
        idx = len(pipeline) - 1                      # terminal
    elif sorteio < maturidade * 0.85 + 0.25:
        idx = random.randint(1, len(pipeline) - 2)   # meio do caminho
    else:
        idx = 0                                      # ainda em Elaborar
    return pipeline, idx


def _marcos(nascimento, fim, n):
    """`n` datas (em dias atrás) entre o nascimento e `fim`, da mais antiga para
    a mais recente. Interpola com jitter para as transições não ficarem em
    intervalos idênticos."""
    if n <= 0:
        return []
    span = max(1, nascimento - fim)
    out = []
    for i in range(1, n + 1):
        base = nascimento - round(span * i / n)
        if span > 20:
            base += random.randint(-3, 3)
        out.append(max(fim, min(nascimento - 1, base)))
    return sorted(out, reverse=True)


def _janela_de_vida(terminal):
    """(nascimento, fim) em dias atrás, para a trilha de um documento.

    Para os CONCLUÍDOS o sorteio começa pelo fim e pelo tempo de ciclo, e o
    nascimento é derivado — não o contrário. Sorteando os dois de forma
    independente, todo documento nascia há 150-320 dias e concluía agora, o que
    dava p85 de 300 dias em tudo. Aqui o ciclo é a variável de interesse
    (25 a 170 dias, com cauda), e 40% das conclusões caem nos últimos 28 dias
    para a janela padrão de 30 dias do painel não nascer vazia.
    """
    if terminal:
        fim = random.randint(1, 28) if random.random() < 0.40 else random.randint(29, 150)
        ciclo = random.choice([random.randint(25, 70),      # rápido
                               random.randint(60, 120),     # típico
                               random.randint(110, 170)])   # cauda longa
        return fim + ciclo, fim
    # em curso: nasceu em algum momento e a última mexida foi depois disso
    nascimento = random.randint(40, 320)
    return nascimento, random.randint(1, max(2, nascimento - 10))


def semear_documentos(equip, maturidade, equipe):
    """Cria os 12 documentos canônicos do equipamento com trilha retroativa."""
    criados = []
    for tipo in TIPOS_DOC_TODOS:
        setor = SETOR_DO_TIPO[tipo]
        pipeline, idx_final = _plano_do_documento(tipo, maturidade)
        label = TIPOS_DOC_LABELS.get(tipo, tipo)

        # Opcionais com pouca maturidade nascem fora do escopo (N/A), com motivo
        # da lista fechada — é o dado que alimenta o agregado de motivos.
        na = tipo in TIPOS_DOC_OPCIONAIS and random.random() > maturidade
        motivo = random.choice(MOTIVOS) if na else ""

        terminal = pipeline[idx_final] in ("Homologado", "Concluído")
        nascimento, fim = _janela_de_vida(terminal)
        doc = Documento(
            setor=setor,
            equipamento=equip.nome,
            equipamento_id=equip.id,
            sku=equip.sku,
            codigo_doc=f"{tipo[:3].upper()}.{equip.modelo}.{random.randint(1, 9):02d}",
            documento=f"{label} - {equip.nome}",
            tipo_doc=tipo,
            fabricante=equip.fabricante,
            status=pipeline[idx_final],
            peso=float(PESOS_TIPO.get(tipo, 1)),
            aplicavel=not na,
            motivo_na_codigo=motivo,
            criado_em=_dt(nascimento, 9),
            data_inicio=(HOJE - timedelta(days=nascimento)),
        )
        db.session.add(doc)
        db.session.flush()

        # ── trilha: uma transição por etapa percorrida ────────────────────────
        # A primeira linha é o marco de criação (status_antigo vazio, como o
        # sistema faz de verdade); as seguintes são transições REAIS, que é o
        # que o cálculo de conclusão exige para não inventar throughput.
        db.session.add(DocumentoHistorico(
            documento_id=doc.id, evento="status", status_antigo="",
            status_novo=pipeline[0], em=doc.criado_em, por=AUTOR,
            motivo="Documento criado"))

        dias = nascimento
        for i, marco in enumerate(_marcos(nascimento, fim, idx_final), start=1):
            dias = marco
            em = _dt(dias, random.randint(8, 17))
            db.session.add(DocumentoHistorico(
                documento_id=doc.id, evento="status",
                status_antigo=pipeline[i - 1], status_novo=pipeline[i],
                em=em, por=AUTOR))
            doc.entrou_status_em = em

        if idx_final == 0:
            doc.entrou_status_em = doc.criado_em

        # Conclusão coerente com a trilha: só quem chegou ao terminal tem data.
        if pipeline[idx_final] in ("Homologado", "Concluído"):
            doc.concluido_em = doc.entrou_status_em
            doc.concluido_por = AUTOR

        if na:
            db.session.add(DocumentoHistorico(
                documento_id=doc.id, evento="escopo", aplicavel=False,
                status_antigo=doc.status, status_novo=doc.status,
                em=_dt(max(1, dias - 5), 14), por=AUTOR,
                motivo=MOTIVOS_NA.get(motivo, "")))

        # ── prazo: vencido, a vencer ou ausente ──────────────────────────────
        if doc.concluido_em is None and doc.aplicavel:
            sorte = random.random()
            if sorte < 0.30:
                doc.prazo = HOJE - timedelta(days=random.randint(3, 90))   # vencido
            elif sorte < 0.75:
                doc.prazo = HOJE + timedelta(days=random.randint(5, 120))  # a vencer
            # os ~25% restantes ficam sem prazo (alerta informativo)

        # ── responsáveis (N:N) ──────────────────────────────────────────────
        # ~20% ficam sem ninguém, de propósito: é o alerta mais comum na vida real.
        if equipe and random.random() > 0.20:
            escolhidos = random.sample(equipe, k=1 if random.random() < 0.8 else 2)
            doc.responsaveis_users = escolhidos
            doc.responsavel = ", ".join(u.nome for u in escolhidos)

        criados.append(doc)
    return criados


# ── SNAPSHOTS RETROATIVOS ────────────────────────────────────────────────────
def semear_snapshots_equipamento(equip, docs, semanas=16):
    """Reconstrói a série semanal de ICE/IDP.

    Não é número inventado: em cada data passada conta quantos documentos JÁ
    estavam concluídos naquele dia (pela trilha) e recalcula o índice. É o que
    faz o gráfico de evolução nascer com história em vez de um ponto só.
    """
    import equipamentos_core as eqcore

    # cad/reg/idp vêm do cálculo REAL do sistema (mesma função que a tela usa),
    # então o último ponto da série coincide com o que a ficha mostra hoje. Só a
    # parte documental é recalculada por data, porque é a única que muda ao
    # longo da janela simulada.
    atual = eqcore.indices(equip, docs)
    cad, reg, idp_hoje = atual["cad"], atual["reg"], atual["idp"]

    aplicaveis = [d for d in docs if d.aplicavel]
    alvo = len(aplicaveis) or 1
    for s in range(semanas, -1, -1):
        ref = HOJE - timedelta(weeks=s)
        limite = datetime.combine(ref, time(23, 59))
        finais = sum(1 for d in aplicaveis
                     if d.concluido_em and d.concluido_em <= limite)
        atrasados = sum(1 for d in aplicaveis
                        if d.prazo and d.prazo < ref
                        and not (d.concluido_em and d.concluido_em <= limite))
        doc_pct = round(100 * finais / alvo)
        db.session.add(EquipamentoSnapshot(
            equipamento_id=equip.id, data=ref.isoformat(),
            ice=round((cad + reg + doc_pct) / 3), cad=cad, reg=reg, doc=doc_pct,
            # IDP acompanha a completude documental na proporção do valor atual
            idp=round(idp_hoje * doc_pct / (atual["doc"] or 100)),
            docs_finais=finais, docs_alvo=alvo, docs_atrasados=atrasados))


# ── MISSÃO (KANBAN) ──────────────────────────────────────────────────────────
def semear_missao(equipe, docs_por_nome):
    m = Missao(nome=f"{PREFIXO}Sprint de Documentação Técnica",
               descricao="Frente de trabalho de demonstração — cartões, fluxo e métricas.",
               accent="#22d3ee", criado_por=AUTOR, criado_em=_dt(120, 9))
    db.session.add(m)
    db.session.flush()

    colunas = []
    for ordem, (nome, categoria, cor, wip) in enumerate(COLUNAS_MISSAO):
        col = MissaoColuna(missao_id=m.id, nome=nome, categoria=categoria,
                           cor=cor, ordem=ordem, limite_wip=wip)
        db.session.add(col)
        colunas.append(col)
    db.session.flush()

    for i, (titulo, prioridade, etiquetas) in enumerate(CARTOES_MISSAO):
        # distribui os cartões pelas colunas; o excesso em "Em andamento"
        # estoura o limite de WIP de propósito, para o alerta aparecer
        destino = min(i % 4 + (1 if i in (4, 8) else 0), 3)
        nascimento = random.randint(20, 110)
        criado = _dt(nascimento, 9)
        c = MissaoCartao(
            missao_id=m.id, coluna_id=colunas[destino].id, titulo=titulo,
            descricao="Cartão de demonstração gerado por scripts/semear_demo.py.",
            prioridade=prioridade, etiquetas=",".join(etiquetas),
            ordem=i, criado_por=AUTOR, criado_em=criado,
            peso=float(random.choice([1, 2, 3, 5, 8])),
            concluido=(destino == 3),
        )
        # prazo: alguns vencidos para alimentar os alertas críticos
        if random.random() < 0.65:
            delta = -random.randint(2, 40) if random.random() < 0.4 else random.randint(4, 60)
            c.prazo = (HOJE + timedelta(days=delta)).isoformat()

        # O cartão precisa estar NA SESSÃO antes do vínculo N:N (mesma armadilha
        # anotada em simular_projetos.py): atribuir a coleção antes disso deixa o
        # backref sem saber do objeto e emite SAWarning.
        db.session.add(c)
        db.session.flush()

        if equipe and random.random() > 0.20:
            escolhidos = random.sample(equipe, k=1)
            c.responsaveis_users = escolhidos
            c.responsaveis = ", ".join(u.nome for u in escolhidos)

        # vínculo com um documento real (chip de referência na ficha)
        alvo = docs_por_nome.get(i % max(1, len(docs_por_nome)))
        if alvo is not None:
            c.ref_tipo, c.ref_id = "documento", alvo.id
        db.session.flush()

        # trilha do cartão: criação + um movimento por coluna percorrida
        db.session.add(MissaoCartaoHistorico(
            cartao_id=c.id, missao_id=m.id, evento="criado",
            coluna_destino_id=colunas[0].id, campo="titulo",
            valor_antigo="", valor_novo=titulo, origem="demo",
            em=criado, por=AUTOR))
        dias = nascimento
        for passo in range(1, destino + 1):
            dias = max(1, dias - random.randint(4, 20))
            em = _dt(dias, random.randint(8, 17))
            db.session.add(MissaoCartaoHistorico(
                cartao_id=c.id, missao_id=m.id, evento="movido",
                coluna_origem_id=colunas[passo - 1].id,
                coluna_destino_id=colunas[passo].id,
                campo="coluna", valor_antigo=colunas[passo - 1].nome,
                valor_novo=colunas[passo].nome, origem="demo", em=em, por=AUTOR))
            c.entrou_coluna_em = em
        if destino == 0:
            c.entrou_coluna_em = criado
        if c.concluido:
            c.concluido_em = c.entrou_coluna_em
            c.concluido_por = AUTOR

    db.session.flush()

    # série semanal da missão, contada pela mesma regra do snapshot real
    cartoes = MissaoCartao.query.filter_by(missao_id=m.id).all()
    for s in range(16, -1, -1):
        ref = HOJE - timedelta(weeks=s)
        limite = datetime.combine(ref, time(23, 59))
        vivos = [c for c in cartoes if c.criado_em and c.criado_em <= limite]
        if not vivos:
            continue
        feitos = [c for c in vivos if c.concluido_em and c.concluido_em <= limite]
        abertos = [c for c in vivos if c not in feitos]
        db.session.add(MissaoSnapshot(
            missao_id=m.id, data=ref.isoformat(), total=len(vivos),
            abertos=len(abertos), concluidos=len(feitos),
            atrasados=sum(1 for c in abertos
                          if c.prazo and c.prazo < ref.isoformat()),
            wip=sum(1 for c in abertos
                    if c.coluna and (c.coluna.categoria or "") == "doing"),
            sem_responsavel=sum(1 for c in abertos if not (c.responsaveis or "").strip()),
            peso_total=round(sum(c.peso or 1.0 for c in vivos), 1),
            peso_concluido=round(sum(c.peso or 1.0 for c in feitos), 1)))
    return m


# ── PRINCIPAL ────────────────────────────────────────────────────────────────
def semear():
    equipe = User.query.filter(User.ativo.is_(True),
                               User.role.in_(("gestor", "tecnico", "admin"))
                               ).order_by(User.id).all()
    if not equipe:
        print("[ERRO] Nenhum usuário ativo — rode o servidor uma vez antes.")
        return

    cats, fams, linhas = semear_taxonomia()
    total_docs, todos_docs = 0, []

    for i, (nome, modelo, fab, familia, risco, anvisa, tec, maturidade) in enumerate(EQUIPAMENTOS):
        equip = Equipamento(
            nome=PREFIXO + nome,
            nome_original=nome,
            nome_tecnico=f"{nome} ({tec})",
            descricao=f"Equipamento fictício de demonstração. {tec}.",
            modelo=modelo, fabricante=fab, familia=familia,
            sku=f"DEMO-{modelo}",
            codigo_interno=f"DM{1000 + i}",
            codigo_fabricante=f"{fab.split()[0][:3].upper()}-{modelo}",
            tecnologia=tec,
            aplicacao="Uso laboratorial em diagnóstico in vitro (demonstração).",
            classe_risco=risco,
            classificacao_reg="Registro" if anvisa else "Notificação",
            anvisa=anvisa, anvisa_registro=anvisa,
            anvisa_validade=((HOJE + timedelta(days=random.randint(120, 1200))).isoformat()
                             if anvisa else ""),
            situacao_regulatoria="Vigente" if anvisa else "Isento",
            status="Ativo",
            armazenamento_base=rf"P:\Engenharia\DEMO\{modelo}",
            responsavel=random.choice(equipe).nome,
            familia_id=fams[familia].id,
            # a categoria vem da FAMÍLIA, senão a taxonomia do equipamento
            # aponta para uma categoria que não contém a família dele
            categoria_id=fams[familia].categoria_id,
            linha_id=linhas[LINHAS[i % len(LINHAS)]].id,
            rev_cadastro="Aprovado" if maturidade > 0.5 else "Pendente",
            rev_estrutura="Aprovado" if maturidade > 0.7 else "Pendente",
            rev_descritivo="Aprovado" if maturidade > 0.6 else "Pendente",
            pareto_classe="ABC"[i % 3],
            qtd_saidas=random.randint(5, 400),
            ativo=True,
            criado_em=_dt(random.randint(200, 400), 9),
        )
        db.session.add(equip)
        db.session.flush()

        docs = semear_documentos(equip, maturidade, equipe)
        db.session.flush()
        semear_snapshots_equipamento(equip, docs)
        total_docs += len(docs)
        todos_docs.extend(docs)
        print(f"  + {equip.nome}: {len(docs)} documentos "
              f"(maturidade {int(maturidade * 100)}%)")

    db.session.commit()

    missao = semear_missao(equipe, dict(enumerate(todos_docs[:12])))
    db.session.commit()

    # ── resumo do que ficou no banco ─────────────────────────────────────────
    concluidos = [d for d in todos_docs if d.concluido_em]
    ciclos = [d.dias_ciclo for d in concluidos if d.dias_ciclo is not None]
    print(f"\n=== RESUMO ===")
    print(f"  equipamentos ........ {len(EQUIPAMENTOS)}")
    print(f"  documentos .......... {total_docs}")
    print(f"    concluídos ........ {len(concluidos)} (todos com data real de trilha)")
    print(f"    N/A com motivo .... {sum(1 for d in todos_docs if not d.aplicavel)}")
    print(f"    atrasados ......... {sum(1 for d in todos_docs if d.atrasado)}")
    print(f"    sem responsável ... {sum(1 for d in todos_docs if not d.responsaveis_nomes)}")
    if ciclos:
        print(f"  tempo de ciclo ...... média {sum(ciclos)//len(ciclos)}d, "
              f"min {min(ciclos)}d, máx {max(ciclos)}d")
    print(f"  linhas de trilha .... {DocumentoHistorico.query.count()}")
    print(f"  missão .............. {missao.nome} "
          f"({len(CARTOES_MISSAO)} cartões, {len(COLUNAS_MISSAO)} colunas)")
    print(f"  snapshots ........... 17 semanas por equipamento e para a missão")
    print(f"\nOK — para remover: python scripts\\semear_demo.py --limpar")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limpar", action="store_true",
                    help="remove os dados de demonstração e sai")
    args = ap.parse_args()
    with app.app_context():
        if args.limpar:
            limpar()
        else:
            limpar()      # recria do zero em vez de duplicar
            semear()
