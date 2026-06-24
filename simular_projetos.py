r"""Simulação de portfólio: cria 3 projetos para demonstração —
um na ZONA DE RISCO (vermelho), um na ZONA DE ALERTA (amarelo) e um SAUDÁVEL (verde).
Escreve no mesmo banco SQLite que o servidor usa (doctrack.db).

Uso: .\venv\Scripts\python.exe simular_projetos.py
Idempotente: se o projeto (pelo nome) já existir, ele é recriado.
"""
import os
from datetime import date, timedelta

from dotenv import load_dotenv
from flask import Flask

load_dotenv()

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "doctrack.db")
url = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql://", 1)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

from models import db, bcrypt, Projeto, Entregavel, ProjetoMensal  # noqa: E402
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


def entregaveis_lista(n_concluidos, n_pendentes, ini_iso):
    """Gera entregáveis: alguns concluídos (com data) e alguns pendentes."""
    nomes = [
        "Especificação técnica", "Projeto mecânico", "Projeto elétrico",
        "Protótipo", "Testes de bancada", "Documentação", "Homologação",
        "Treinamento", "Validação de campo", "Liberação final",
    ]
    itens = []
    # datas de conclusão espalhadas nos últimos meses
    for i in range(n_concluidos):
        dt_concl = (HOJE - timedelta(days=120 - i * 18)).isoformat()
        itens.append(dict(tipo=nomes[i % len(nomes)], categoria="Produto",
                          status="concluido", percentual=100,
                          data_inicio=ini_iso, data_conclusao=dt_concl))
    for i in range(n_pendentes):
        itens.append(dict(tipo=nomes[(n_concluidos + i) % len(nomes)], categoria="Produto",
                          status="pendente", percentual=0,
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


def criar_projeto(nome, tipo, sku, descricao, orcamento, pct_prev,
                  n_concluidos, n_pendentes, total_ac, competencias):
    # remove projeto homônimo (recriação limpa)
    antigo = Projeto.query.filter_by(nome=nome).first()
    if antigo:
        db.session.delete(antigo)
        db.session.commit()

    ini_iso, fim_iso = datas_por_prazo(pct_prev)
    p = Projeto(
        nome=nome, tipo=tipo, sku=sku, descricao=descricao, ano=HOJE.year,
        ativo=True, orcamento=float(orcamento),
        data_inicio_prev=ini_iso, data_inicio_real=ini_iso, data_fim_prev=fim_iso,
        lancamento=str(HOJE.year),
    )
    db.session.add(p)
    db.session.flush()

    for e in entregaveis_lista(n_concluidos, n_pendentes, ini_iso):
        db.session.add(Entregavel(projeto_id=p.id, **e))

    for comp, valor in mensais_lista(total_ac, competencias):
        db.session.add(ProjetoMensal(projeto_id=p.id, competencia=comp, custo_mes=valor))

    db.session.flush()
    p.recompute_acumulados()
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
    )

    # 🟡 ZONA DE ALERTA (amarelo): SPI ~0.90, CPI ~0.90
    alerta = criar_projeto(
        nome="Linha de Envase Compacta",
        tipo="Revenda", sku="ENV-CMP-02",
        descricao="Envasadora semiautomática (DEMO — zona de alerta)",
        orcamento=100000, pct_prev=69,
        n_concluidos=5, n_pendentes=3,        # avanço = 62%
        total_ac=69000, competencias=comps,
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
