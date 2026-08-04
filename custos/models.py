"""
custos/models.py — Modelos SQLAlchemy do módulo Custos (formação de custo).

Reutiliza o `db` da plataforma mestre. Tabelas prefixadas `custo_` para não
colidir com o domínio de Documentos/Projetos/Equipamentos.

Domínio:  Composicao (folha de custo de um produto)
            → Lancamento  (as linhas, separadas em NRE e COGS)
            → Versao      (baseline congelado, no molde do ProjetoBaseline)
          Cotacao         (série de câmbio, independente das composições)

## Duas decisões que valem a explicação

**1. `Numeric`, não `Float`.** Todo o `models.py` do mestre usa `db.Float` para
dinheiro. Aqui a aritmética é encadeada — câmbio × alíquota × rateio × margem —
e o erro de ponto flutuante se acumula ao longo da cadeia. Um custo unitário que
fecha em `114732.41999999999` não é defensável numa reunião. Valores em
`Numeric(14,2)`, taxas de câmbio em `Numeric(14,6)`, alíquotas em `Numeric(8,4)`.
A divergência do resto da base é deliberada; o cálculo vive em `custos/core.py`
e é todo em `Decimal`.

**2. NRE e COGS são naturezas distintas, não um campo cosmético.** Custo não
recorrente (desenvolvimento, ferramental, homologação) amortiza sobre o volume
projetado; custo de mercadoria não amortiza nunca. Somar os dois numa coluna só
produz um "custo do projeto" que é, na prática, o custo de uma unidade — e todo
indicador derivado dele (margem, payback) sai errado. `Lancamento.natureza` é o
que impede isso, e `aplicavel` de fato exclui do total.
"""
from datetime import datetime

from models import db   # mesma instância SQLAlchemy do mestre

# ── CONSTANTES DE DOMÍNIO ─────────────────────────────────────────────────────

# Categorias fixas: comparar composições entre si exige vocabulário compartilhado.
# Texto livre aqui inviabilizaria a visão de portfólio por categoria.
CATEGORIAS_CUSTO = [
    "Parceiro OEM",
    "Integração Local",
    "Regulatório",
    "Logística e Tributos",
    "Comercial",
]

NATUREZAS = ["nre", "cogs"]
NATUREZAS_LABELS = {
    "nre": "NRE — custo não recorrente do projeto",
    "cogs": "COGS — custo recorrente por unidade",
}

# Como o valor da linha é obtido.
#   fob        — o valor FOB unitário da composição (a mercadoria)
#   montante   — valor fixo, na moeda da linha
#   horas      — horas × custo/hora do perfil
#   percentual — alíquota sobre o FOB em BRL (tributos de importação)
#   reserva    — percentual sobre a exposição em moeda estrangeira
TIPOS_CALCULO = ["fob", "montante", "horas", "percentual", "reserva"]

PERFIS_HORA = ["eng", "prod"]
PERFIS_HORA_LABELS = {"eng": "Engenharia", "prod": "Produção"}

# De onde veio o número. Uma estimativa e uma DI não podem pesar igual.
PROCEDENCIAS = ["estimativa", "cotacao", "invoice", "di", "nf", "politica"]
PROCEDENCIAS_LABELS = {
    "estimativa": "Estimativa",
    "cotacao": "Cotação do fornecedor",
    "invoice": "Invoice",
    "di": "Declaração de importação",
    "nf": "Nota fiscal",
    "politica": "Política interna",
}

CONFIANCAS = ["baixa", "media", "alta"]

STATUS_COMPOSICAO = ["rascunho", "vigente", "arquivada"]
TIPOS_COMPOSICAO = ["OEM", "Revenda"]

MOEDAS = ["BRL", "USD", "EUR"]
MOEDAS_ESTRANGEIRAS = ["USD", "EUR"]

INCOTERMS = ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP",
             "DAP", "DPU", "DDP"]

TIPOS_COTACAO = ["ptax_venda", "ptax_compra", "spot"]
FONTES_COTACAO = ["bcb_olinda", "manual"]

# Mexer nestes campos versiona a composição — mesmo contrato do CAMPOS_BASELINE
# de entregaveis.py, pelo mesmo motivo: são eles que definem contra o que o
# realizado será medido.
CAMPOS_BASELINE = ("taxa_planejamento", "preco_venda", "volume_projetado")

# Desvio a partir do qual a taxa travada destoa da referência de mercado.
LIMITE_DESVIO_CAMBIO = 0.03


def _f(v):
    """Decimal/None -> float/None, para serializar em JSON."""
    return None if v is None else float(v)


# ── ESTRUTURA PADRÃO DE UMA COMPOSIÇÃO NOVA ───────────────────────────────────
# Sem isto, cada composição nova é uma folha em branco e a estrutura de custo de
# importação acaba redigitada — diferente a cada vez, o que inviabiliza comparar
# produtos entre si depois.
#
# As alíquotas são o ponto de partida usual de equipamento laboratorial
# importado; **devem ser conferidas por NCM** em cada operação. A automação que
# resolve isso de vez (tabela de alíquotas por NCM) está mapeada e ainda não foi
# feita — enquanto isso o número fica visível e editável na tela, em vez de
# escondido numa fórmula.
_ALIQ_PADRAO = {"ii": 16, "ipi": 0, "pis": 2.1, "cofins": 10.45, "icms": 18}

LANCAMENTOS_PADRAO_COGS = [
    dict(natureza="cogs", categoria="Parceiro OEM",
         subcategoria="Mercadoria (FOB unitário)",
         descricao="Preço unitário acordado com o fornecedor",
         tipo_calculo="fob", procedencia="cotacao", confianca="alta"),
    dict(natureza="cogs", categoria="Logística e Tributos",
         subcategoria="Frete internacional",
         descricao="Frete, seguro e transporte internacional",
         tipo_calculo="montante", moeda="USD", procedencia="estimativa", confianca="media"),
    dict(natureza="cogs", categoria="Logística e Tributos",
         subcategoria="Taxa Siscomex",
         descricao="Registro da declaração de importação",
         tipo_calculo="montante", moeda="BRL", procedencia="estimativa", confianca="media"),
    dict(natureza="cogs", categoria="Logística e Tributos",
         subcategoria="II — Imposto de Importação", descricao="Sobre o valor aduaneiro",
         tipo_calculo="percentual", aliquota=_ALIQ_PADRAO["ii"],
         procedencia="estimativa", confianca="media"),
    dict(natureza="cogs", categoria="Logística e Tributos",
         subcategoria="IPI", descricao="Sobre o valor aduaneiro acrescido do II",
         tipo_calculo="percentual", aliquota=_ALIQ_PADRAO["ipi"],
         procedencia="estimativa", confianca="media"),
    dict(natureza="cogs", categoria="Logística e Tributos",
         subcategoria="PIS/Pasep — Importação", descricao="Contribuição sobre importação",
         tipo_calculo="percentual", aliquota=_ALIQ_PADRAO["pis"],
         procedencia="estimativa", confianca="media"),
    dict(natureza="cogs", categoria="Logística e Tributos",
         subcategoria="Cofins — Importação", descricao="Contribuição sobre importação",
         tipo_calculo="percentual", aliquota=_ALIQ_PADRAO["cofins"],
         procedencia="estimativa", confianca="media"),
    dict(natureza="cogs", categoria="Logística e Tributos",
         subcategoria="ICMS", descricao="Alíquota interna do estado",
         tipo_calculo="percentual", aliquota=_ALIQ_PADRAO["icms"],
         procedencia="estimativa", confianca="media"),
    dict(natureza="cogs", categoria="Logística e Tributos",
         subcategoria="Despachante aduaneiro",
         descricao="Liberação alfandegária e armazenagem",
         tipo_calculo="montante", moeda="BRL", procedencia="cotacao", confianca="media"),
    dict(natureza="cogs", categoria="Logística e Tributos",
         subcategoria="Reserva cambial",
         descricao="Percentual sobre a exposição em moeda estrangeira",
         tipo_calculo="reserva", aliquota=10, procedencia="politica", confianca="media"),
]

# Só para OEM: revenda não tem desenvolvimento, e lançar horas aplicáveis num
# produto de revenda dispararia alarme de saúde por um custo que não existe.
LANCAMENTOS_PADRAO_NRE = [
    dict(natureza="nre", categoria="Integração Local",
         subcategoria="Engenharia — desenvolvimento e integração",
         descricao="Horas de P&D, adaptação e validação",
         tipo_calculo="horas", perfil_hora="eng",
         procedencia="estimativa", confianca="baixa"),
    dict(natureza="nre", categoria="Integração Local",
         subcategoria="Produção — protótipo",
         descricao="Horas de usinagem, montagem e acabamento",
         tipo_calculo="horas", perfil_hora="prod",
         procedencia="estimativa", confianca="baixa"),
]


def lancamentos_padrao(tipo="OEM"):
    """Estrutura inicial de lançamentos conforme o tipo da composição."""
    base = [dict(x) for x in LANCAMENTOS_PADRAO_COGS]
    if (tipo or "OEM") == "OEM":
        base += [dict(x) for x in LANCAMENTOS_PADRAO_NRE]
    return base


# ── COMPOSIÇÃO ────────────────────────────────────────────────────────────────
class Composicao(db.Model):
    """A folha de custo de um produto: identidade, parâmetros e taxa travada."""
    __tablename__ = "custo_composicoes"

    id       = db.Column(db.Integer, primary_key=True)
    codigo   = db.Column(db.String(30), default="", index=True)   # CC-2026-001
    produto  = db.Column(db.String(200), nullable=False, index=True)
    sku      = db.Column(db.String(50), default="", index=True)

    # Vínculos com o que já existe. Ambos opcionais: uma composição pode nascer
    # antes de o projeto existir, e revenda pode não ter projeto nenhum.
    projeto_id     = db.Column(db.Integer, db.ForeignKey("projetos.id"), nullable=True, index=True)
    equipamento_id = db.Column(db.Integer, db.ForeignKey("equipamentos.id"), nullable=True, index=True)

    fornecedor = db.Column(db.String(200), default="")
    tipo       = db.Column(db.String(20), default="OEM")       # OEM | Revenda
    incoterm   = db.Column(db.String(10), default="FOB")
    moeda_base = db.Column(db.String(3), default="USD")
    status     = db.Column(db.String(20), default="rascunho", nullable=False, index=True)
    versao     = db.Column(db.Integer, default=1, nullable=False)

    # Parâmetros do cálculo
    valor_fob        = db.Column(db.Numeric(14, 2), default=0)   # unitário, na moeda_base
    qtd_invoice      = db.Column(db.Integer, default=1)
    volume_projetado = db.Column(db.Integer, default=1)          # amortiza o NRE
    preco_venda      = db.Column(db.Numeric(14, 2), nullable=True)

    custo_hora_engenharia = db.Column(db.Numeric(14, 2), default=0)
    custo_hora_producao   = db.Column(db.Numeric(14, 2), default=0)
    reserva_cambial_pct   = db.Column(db.Numeric(8, 4), default=10)

    # A taxa de planejamento é travada: é a única que orça, e carrega quem
    # decidiu e por quê. Sem isso ela vira um número herdado que ninguém defende.
    taxa_planejamento              = db.Column(db.Numeric(14, 6), default=1)
    taxa_planejamento_data         = db.Column(db.String(10), default="")   # ISO
    taxa_planejamento_autor        = db.Column(db.String(120), default="")
    taxa_planejamento_justificativa = db.Column(db.Text, default="")

    # A taxa realizada chega com a DI e fecha o ciclo contra o baseline.
    taxa_realizada = db.Column(db.Numeric(14, 6), nullable=True)
    di_numero      = db.Column(db.String(40), default="")
    di_data        = db.Column(db.String(10), default="")

    observacoes = db.Column(db.Text, default="")

    ativo      = db.Column(db.Boolean, default=True, nullable=False, index=True)
    criado_em  = db.Column(db.DateTime, default=datetime.now)
    criado_por = db.Column(db.String(120), default="")
    updated_em = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    lancamentos = db.relationship(
        "Lancamento", back_populates="composicao",
        cascade="all, delete-orphan", lazy="selectin",
        order_by="Lancamento.natureza.desc(), Lancamento.ordem, Lancamento.id",
    )
    versoes = db.relationship(
        "Versao", back_populates="composicao",
        cascade="all, delete-orphan",
        order_by="Versao.numero.desc()",
    )
    projeto     = db.relationship("Projeto", lazy="joined")
    equipamento = db.relationship("Equipamento", lazy="joined")

    def to_dict(self, com_lancamentos=False, com_calculo=False):
        d = {
            "id": self.id,
            "codigo": self.codigo or "",
            "produto": self.produto or "",
            "sku": self.sku or "",
            "projeto_id": self.projeto_id,
            "projeto_nome": self.projeto.nome if self.projeto else "",
            "equipamento_id": self.equipamento_id,
            "fornecedor": self.fornecedor or "",
            "tipo": self.tipo or "OEM",
            "incoterm": self.incoterm or "",
            "moeda_base": self.moeda_base or "USD",
            "status": self.status or "rascunho",
            "versao": self.versao or 1,
            "valor_fob": _f(self.valor_fob) or 0.0,
            "qtd_invoice": self.qtd_invoice or 1,
            "volume_projetado": self.volume_projetado or 1,
            "preco_venda": _f(self.preco_venda),
            "custo_hora_engenharia": _f(self.custo_hora_engenharia) or 0.0,
            "custo_hora_producao": _f(self.custo_hora_producao) or 0.0,
            "reserva_cambial_pct": _f(self.reserva_cambial_pct) or 0.0,
            "taxa_planejamento": _f(self.taxa_planejamento) or 0.0,
            "taxa_planejamento_data": self.taxa_planejamento_data or "",
            "taxa_planejamento_autor": self.taxa_planejamento_autor or "",
            "taxa_planejamento_justificativa": self.taxa_planejamento_justificativa or "",
            "taxa_realizada": _f(self.taxa_realizada),
            "di_numero": self.di_numero or "",
            "di_data": self.di_data or "",
            "observacoes": self.observacoes or "",
            "ativo": bool(self.ativo),
            "criado_em": self.criado_em.strftime("%d/%m/%Y %H:%M") if self.criado_em else "",
            "criado_por": self.criado_por or "",
        }
        if com_lancamentos:
            d["lancamentos"] = [l.to_dict() for l in self.lancamentos if l.ativo]
        if com_calculo:
            from .core import calcular
            d["calculo"] = calcular(self)
        return d


# ── LANÇAMENTO ────────────────────────────────────────────────────────────────
class Lancamento(db.Model):
    """Uma linha da folha de custo, com natureza, procedência e confiança."""
    __tablename__ = "custo_lancamentos"

    id            = db.Column(db.Integer, primary_key=True)
    composicao_id = db.Column(db.Integer, db.ForeignKey("custo_composicoes.id"),
                              nullable=False, index=True)
    ordem         = db.Column(db.Integer, default=0)

    natureza    = db.Column(db.String(10), default="cogs", nullable=False, index=True)
    categoria   = db.Column(db.String(60), default="", index=True)
    subcategoria = db.Column(db.String(120), default="")
    descricao   = db.Column(db.String(300), default="")
    observacao  = db.Column(db.Text, default="")

    # Diferente da planilha de origem, este flag realmente exclui do total.
    aplicavel   = db.Column(db.Boolean, default=True, nullable=False)

    tipo_calculo = db.Column(db.String(20), default="montante", nullable=False)
    moeda        = db.Column(db.String(3), default="BRL")
    valor_moeda  = db.Column(db.Numeric(14, 2), default=0)
    horas        = db.Column(db.Numeric(10, 2), default=0)
    perfil_hora  = db.Column(db.String(10), default="")
    aliquota     = db.Column(db.Numeric(8, 4), default=0)        # em %

    # A taxa fica congelada na linha: saber "quanto custou" exige saber
    # "convertido a quanto, e quando".
    taxa_aplicada = db.Column(db.Numeric(14, 6), nullable=True)
    taxa_data     = db.Column(db.String(10), default="")
    taxa_fonte    = db.Column(db.String(20), default="")

    valor_brl   = db.Column(db.Numeric(14, 2), default=0)        # derivado, persistido
    procedencia = db.Column(db.String(20), default="estimativa")
    confianca   = db.Column(db.String(10), default="media")

    realizado_valor_brl = db.Column(db.Numeric(14, 2), nullable=True)
    realizado_data      = db.Column(db.String(10), default="")
    realizado_doc       = db.Column(db.String(60), default="")

    ativo      = db.Column(db.Boolean, default=True, nullable=False)
    criado_em  = db.Column(db.DateTime, default=datetime.now)
    updated_em = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    composicao = db.relationship("Composicao", back_populates="lancamentos")

    def to_dict(self):
        return {
            "id": self.id,
            "composicao_id": self.composicao_id,
            "ordem": self.ordem or 0,
            "natureza": self.natureza or "cogs",
            "categoria": self.categoria or "",
            "subcategoria": self.subcategoria or "",
            "descricao": self.descricao or "",
            "observacao": self.observacao or "",
            "aplicavel": bool(self.aplicavel),
            "tipo_calculo": self.tipo_calculo or "montante",
            "moeda": self.moeda or "BRL",
            "valor_moeda": _f(self.valor_moeda) or 0.0,
            "horas": _f(self.horas) or 0.0,
            "perfil_hora": self.perfil_hora or "",
            "aliquota": _f(self.aliquota) or 0.0,
            "taxa_aplicada": _f(self.taxa_aplicada),
            "taxa_data": self.taxa_data or "",
            "taxa_fonte": self.taxa_fonte or "",
            "valor_brl": _f(self.valor_brl) or 0.0,
            "procedencia": self.procedencia or "",
            "confianca": self.confianca or "",
            "realizado_valor_brl": _f(self.realizado_valor_brl),
            "realizado_data": self.realizado_data or "",
            "realizado_doc": self.realizado_doc or "",
        }


# ── COTAÇÃO ───────────────────────────────────────────────────────────────────
class Cotacao(db.Model):
    """Série de câmbio. Referência e histórico — nunca substitui a taxa travada.

    A unicidade por (moeda, data, tipo) é o que torna a sincronização idempotente:
    o agendador guarda estado só em memória, então um restart no meio do dia
    refaz a tarefa. Mesmo contrato do ProjetoSnapshot.
    """
    __tablename__ = "custo_cotacoes"
    __table_args__ = (
        db.UniqueConstraint("moeda", "data", "tipo", name="uq_custo_cotacao"),
    )

    id        = db.Column(db.Integer, primary_key=True)
    moeda     = db.Column(db.String(3), nullable=False, index=True)
    data      = db.Column(db.Date, nullable=False, index=True)
    tipo      = db.Column(db.String(20), default="ptax_venda", nullable=False)
    valor     = db.Column(db.Numeric(14, 6), nullable=False)
    fonte     = db.Column(db.String(20), default="bcb_olinda")
    obtido_em = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "moeda": self.moeda,
            "data": self.data.strftime("%d/%m/%Y") if self.data else "",
            "data_iso": self.data.isoformat() if self.data else "",
            "tipo": self.tipo,
            "valor": _f(self.valor),
            "fonte": self.fonte or "",
            "obtido_em": self.obtido_em.strftime("%d/%m/%Y %H:%M") if self.obtido_em else "",
        }


# ── VERSÃO ────────────────────────────────────────────────────────────────────
class Versao(db.Model):
    """Baseline congelado da composição. A v1 é o estimado; o realizado é medido
    contra ela. Molde do ProjetoBaseline (models.py) — mesma razão de existir."""
    __tablename__ = "custo_versoes"

    id            = db.Column(db.Integer, primary_key=True)
    composicao_id = db.Column(db.Integer, db.ForeignKey("custo_composicoes.id"),
                              nullable=False, index=True)
    numero        = db.Column(db.Integer, nullable=False)
    motivo        = db.Column(db.String(300), default="")
    snapshot_json = db.Column(db.Text, default="")
    criado_por    = db.Column(db.String(120), default="")
    criado_em     = db.Column(db.DateTime, default=datetime.now)

    composicao = db.relationship("Composicao", back_populates="versoes")

    def to_dict(self):
        import json
        try:
            snap = json.loads(self.snapshot_json) if self.snapshot_json else {}
        except (ValueError, TypeError):
            snap = {}
        return {
            "id": self.id,
            "composicao_id": self.composicao_id,
            "numero": self.numero,
            "motivo": self.motivo or "",
            "criado_por": self.criado_por or "",
            "criado_em": self.criado_em.strftime("%d/%m/%Y %H:%M") if self.criado_em else "",
            "snapshot": snap,
        }
