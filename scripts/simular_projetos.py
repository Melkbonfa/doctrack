r"""Simulação de portfólio: cria 3 projetos para demonstração —
um na ZONA DE RISCO (vermelho), um na ZONA DE ALERTA (amarelo) e um SAUDÁVEL (verde).
Escreve no mesmo banco SQLite que o servidor usa (doctrack.db).

Uso: .\venv\Scripts\python.exe simular_projetos.py
Idempotente: se o projeto (pelo nome) já existir, ele é recriado.
"""
import os
import sys
from datetime import date, timedelta

from dotenv import load_dotenv
from flask import Flask

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

load_dotenv()
DB_PATH = os.path.join(ROOT, "doctrack.db")
url = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql://", 1)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

from models import (db, bcrypt, Projeto, Entregavel, ProjetoMensal,  # noqa: E402
                    ProjetoSnapshot, User)
db.init_app(app)
bcrypt.init_app(app)

HOJE = date.today()
SPAN = 200  # dias de cronograma total (início → fim previsto)


def datas_por_prazo(pct_prev):
    """Datas (início_prev, fim_prev) para que ~pct_prev% do prazo já tenha decorrido hoje."""
    elapsed = round(SPAN * pct_prev / 100)
    ini = HOJE - timedelta(days=elapsed)
    fim = HOJE + timedelta(days=SPAN - elapsed)
    return ini.isoformat(), fim.isoformat()


# Peso relativo por entregável: homologação/validação custam muito mais que um
# treinamento. Sem isso o avanço tratava tudo como equivalente.
PESOS = {
    "Especificação técnica": 2, "Projeto mecânico": 5, "Projeto elétrico": 5,
    "Protótipo": 8, "Testes de bancada": 4, "Documentação": 2,
    "Homologação": 8, "Treinamento": 1, "Validação de campo": 5,
    "Liberação final": 3,
}


def entregaveis_lista(n_concluidos, n_pendentes, ini_iso, atrasar=0):
    """Gera entregáveis com peso e plano por tarefa.

    `atrasar` = quantos pendentes recebem término previsto já vencido (para
    demonstrar os alertas de atraso).
    """
    nomes = [
        "Especificação técnica", "Projeto mecânico", "Projeto elétrico",
        "Protótipo", "Testes de bancada", "Documentação", "Homologação",
        "Treinamento", "Validação de campo", "Liberação final",
    ]
    itens = []
    # datas de conclusão espalhadas nos últimos meses
    for i in range(n_concluidos):
        nome = nomes[i % len(nomes)]
        dt_concl = (HOJE - timedelta(days=120 - i * 18)).isoformat()
        itens.append(dict(tipo=nome, categoria="Produto",
                          status="concluido", percentual=100, peso=PESOS.get(nome, 1),
                          data_inicio_prev=ini_iso, data_fim_prev=dt_concl,
                          data_inicio=ini_iso, data_conclusao=dt_concl))
    for i in range(n_pendentes):
        nome = nomes[(n_concluidos + i) % len(nomes)]
        # os primeiros `atrasar` já venceram; os demais vencem no futuro
        delta = -(10 + i * 7) if i < atrasar else (15 + i * 12)
        itens.append(dict(tipo=nome, categoria="Produto",
                          status="pendente", percentual=0, peso=PESOS.get(nome, 1),
                          data_inicio_prev=ini_iso,
                          data_fim_prev=(HOJE + timedelta(days=delta)).isoformat(),
                          data_inicio=ini_iso, data_conclusao=""))
    return itens


def mensais_lista(total_ac, competencias):
    """Distribui o custo total (AC) entre as competências informadas."""
    n = len(competencias)
    base = round(total_ac / n)
    out = []
    soma = 0
    for i, comp in enumerate(competencias):
        valor = total_ac - soma if i == n - 1 else base   # ajusta o último p/ fechar o total
        soma += valor
        out.append((comp, float(valor)))
    return out


def _equipe():
    """Usuários que podem receber entregáveis (técnicos e gestores)."""
    return User.query.filter(User.ativo.is_(True),
                             User.role.in_(("gestor", "tecnico"))).order_by(User.id).all()


def _semear_snapshots(p, dias=63, passo=7):
    """Reconstrói a série de indicadores dos últimos meses.

    Não é número inventado: cada ponto usa `realizado_em`/`previsto_em` na data
    e o custo acumulado até ali. Serve para a aba de tendência já nascer com
    história em vez de esperar semanas de uso.
    """
    custos = sorted((m.competencia, m.custo_mes or 0.0) for m in p.mensais)
    bac = p.orcamento or 0.0
    for d in range(dias, -1, -passo):
        ref = HOJE - timedelta(days=d)
        comp = f"{ref.year:04d}-{ref.month:02d}"
        prev = p.previsto_em(comp)
        real = p.realizado_em(ref)
        ac = sum(v for c, v in custos if c <= comp)
        spi = (real / prev) if prev else None
        ev = bac * real / 100 if bac else None
        cpi = (ev / ac) if (ev is not None and ac) else None
        db.session.add(ProjetoSnapshot(
            projeto_id=p.id, data=ref.isoformat(), avanco=real,
            pct_previsto=prev,
            spi=round(spi, 3) if spi is not None else None,
            cpi=round(cpi, 3) if cpi is not None else None,
            ac=round(ac, 2) if ac else None, bac=bac or None))


def criar_projeto(nome, tipo, sku, descricao, orcamento, pct_prev,
                  n_concluidos, n_pendentes, total_ac, competencias,
                  status="execucao", atrasar=0, replanejou=None):
    # remove projeto homônimo (recriação limpa)
    antigo = Projeto.query.filter_by(nome=nome).first()
    if antigo:
        db.session.delete(antigo)
        db.session.commit()

    ini_iso, fim_iso = datas_por_prazo(pct_prev)
    p = Projeto(
        nome=nome, tipo=tipo, sku=sku, descricao=descricao, ano=HOJE.year,
        ativo=True, status=status, orcamento=float(orcamento),
        data_inicio_prev=ini_iso, data_inicio_real=ini_iso, data_fim_prev=fim_iso,
        lancamento=str(HOJE.year),
    )
    db.session.add(p)
    db.session.flush()

    equipe = _equipe()
    for i, e in enumerate(entregaveis_lista(n_concluidos, n_pendentes, ini_iso, atrasar)):
        ent = Entregavel(projeto_id=p.id, **e)
        p.entregaveis.append(ent)   # precisa estar na sessão ANTES do vínculo N:N
        # distribui responsáveis reais (FK) — é o que alimenta a carga por pessoa
        if equipe:
            ent.responsaveis_users = [equipe[i % len(equipe)]]
            ent.responsaveis = equipe[i % len(equipe)].nome.split(" ")[0]

    for comp, valor in mensais_lista(total_ac, competencias):
        p.mensais.append(ProjetoMensal(competencia=comp, custo_mes=valor))

    db.session.flush()
    p.recompute_acumulados()

    # Linha de base v1 (o plano original) e, se houve replanejamento, a v2.
    p.registrar_baseline("simulacao@doctrack", motivo="Linha de base inicial")
    if replanejou:
        p.data_fim_prev = (date.fromisoformat(fim_iso)
                           + timedelta(days=replanejou[0])).isoformat()
        p.registrar_baseline("simulacao@doctrack", motivo=replanejou[1])

    _semear_snapshots(p)
    db.session.commit()
    return p


with app.app_context():
    comps = ["2026-03", "2026-04", "2026-05", "2026-06"]

    # 🔴 ZONA DE RISCO (vermelho): SPI ~0.40, CPI ~0.43
    risco = criar_projeto(
        nome="Plataforma IoT Sentinela",
        tipo="OEM", sku="IOT-SEN-01",
        descricao="Gateway industrial de monitoramento (DEMO — zona de risco)",
        orcamento=100000, pct_prev=75,
        n_concluidos=3, n_pendentes=7,        # avanço = 30%
        total_ac=70000, competencias=comps,
        atrasar=4,                            # 4 entregáveis já vencidos
        replanejou=(60, "Atraso na homologação do fornecedor"),
    )

    # 🟡 ZONA DE ALERTA (amarelo): SPI ~0.90, CPI ~0.90
    alerta = criar_projeto(
        nome="Linha de Envase Compacta",
        tipo="Revenda", sku="ENV-CMP-02",
        descricao="Envasadora semiautomática (DEMO — zona de alerta)",
        orcamento=100000, pct_prev=69,
        n_concluidos=5, n_pendentes=3,        # avanço = 62%
        total_ac=69000, competencias=comps,
        atrasar=1,
    )

    # 🟢 SAUDÁVEL (verde): SPI ~1.05, CPI ~1.05 (adiantado e dentro do orçamento)
    saudavel = criar_projeto(
        nome="Esteira de Inspeção Visão IA",
        tipo="OEM", sku="INS-IA-03",
        descricao="Inspeção óptica com visão computacional (DEMO — no alvo)",
        orcamento=100000, pct_prev=76,
        n_concluidos=8, n_pendentes=2,        # avanço = 80%
        total_ac=76000, competencias=comps,
    )

    print("\n=== RESULTADO DA SIMULAÇÃO ===")
    for p in (risco, alerta, saudavel):
        m = p.pmo_metrics()
        print(f"\n• {p.nome}  [{p.tipo}]")
        print(f"   avanço={m['pct_realizado']}%  prazo_decorrido={m['pct_previsto']}%  "
              f"AC=R${m['ac']:.0f}  EV=R${m['ev']:.0f}")
        print(f"   SPI={m['spi']} ({m['status_prazo']})   "
              f"CPI={m['cpi']} ({m['status_custo']})")
    print("\nOK — projetos de simulação gravados.")
