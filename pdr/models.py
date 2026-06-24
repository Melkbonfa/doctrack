"""
pdr/models.py — Modelos SQLAlchemy do módulo PDR (P&D de reagentes)

Reutiliza o `db` da plataforma mestre (DocTrack). User, AuditLog, RevokedToken
e a autenticação são compartilhados com o mestre — aqui só vivem as entidades
específicas do PDR, com tabelas prefixadas `pdr_` para não colidir com o
domínio de Documentos/Projetos do DocTrack.

Domínio:  Produto (família/KIT)  →  Apresentação (SKU)  →  PdrDocumento (4 tipos)
"""
from datetime import datetime

from models import db   # mesma instância SQLAlchemy do mestre

# ── CONSTANTES DE DOMÍNIO ─────────────────────────────────────────────────────

ROLES = ["admin", "gestor", "tecnico", "leitura"]

LINHAS = ["Extracta KITs", "Outros Produtos", "Pré-Tratamento"]

# Os 4 documentos rastreados por apresentação
TIPOS_DOC = ["especificacao", "descritivo", "instrucao_trabalho", "manual"]
TIPOS_DOC_LABELS = {
    "especificacao": "Especificação do Produto",
    "descritivo": "Descritivo",
    "instrucao_trabalho": "Instrução de Trabalho",
    "manual": "Manual",
}

# Vocabulários controlados (derivados do uso real + Legenda da planilha)
STATUS_PROTHEUS = ["OK", "BLOQUEADO", "DESCONTINUADO", "OBSOLETO", "PARA CORREÇÃO"]
STATUS_ANVISA = ["RUO", "Registrado", "Não Registrado", "Kit Bloqueado"]
STATUS_DOC = [
    "PENDENTE", "EM ELABORAÇÃO", "ELABORAÇÃO", "REVISÃO", "REVISÃO PDR",
    "SEPARAR VERSÕES", "REQUISIÇÃO ABERTA", "ADEQUAÇÃO PROMPT",
    "ADEQUAR PADRONIZAÇÃO", "MAPEADO", "AGUARDANDO HOMOLOGAÇÃO",
    "HOMOLOGADO", "FINALIZADO", "FINALIZADO/LIBERADO", "DESCONTINUADO",
]

# Status que contam como "concluído" no cálculo de avanço/global
STATUS_OK = {"FINALIZADO", "FINALIZADO/LIBERADO", "HOMOLOGADO", "LIBERADO"}
STATUS_DESCONTINUADO = {"DESCONTINUADO", "OBSOLETO"}


# ── PRODUTO (família / KIT) ───────────────────────────────────────────────────
class Produto(db.Model):
    __tablename__ = "pdr_produtos"

    id          = db.Column(db.Integer, primary_key=True)
    nome        = db.Column(db.String(200), nullable=False, index=True)
    sigla       = db.Column(db.String(40), default="")
    linha       = db.Column(db.String(60), default="Extracta KITs", index=True)
    observacoes = db.Column(db.Text, default="")
    ativo       = db.Column(db.Boolean, default=True, nullable=False, index=True)
    criado_em   = db.Column(db.DateTime, default=datetime.now)

    apresentacoes = db.relationship(
        "Apresentacao", back_populates="produto",
        cascade="all, delete-orphan",
    )

    @property
    def total_apresentacoes(self):
        return sum(1 for a in self.apresentacoes if a.ativo)

    @property
    def avanco(self):
        """% médio de documentos finalizados nas apresentações ativas."""
        docs = [d for a in self.apresentacoes if a.ativo for d in a.documentos]
        validos = [d for d in docs if not d.is_descontinuado]
        if not validos:
            return 0
        ok = sum(1 for d in validos if d.is_ok)
        return round(ok * 100 / len(validos))

    @property
    def pendencias(self):
        """Documentos ainda não finalizados (e não descontinuados)."""
        return sum(
            1 for a in self.apresentacoes if a.ativo
            for d in a.documentos if not d.is_ok and not d.is_descontinuado
        )

    def to_dict(self, com_apresentacoes=False):
        d = {
            "id": self.id,
            "nome": self.nome,
            "sigla": self.sigla or "",
            "linha": self.linha or "",
            "observacoes": self.observacoes or "",
            "ativo": bool(self.ativo),
            "total_apresentacoes": self.total_apresentacoes,
            "avanco": self.avanco,
            "pendencias": self.pendencias,
        }
        if com_apresentacoes:
            d["apresentacoes"] = [a.to_dict(com_documentos=True) for a in self.apresentacoes if a.ativo]
        return d


# ── APRESENTAÇÃO (SKU) ────────────────────────────────────────────────────────
class Apresentacao(db.Model):
    __tablename__ = "pdr_apresentacoes"

    id          = db.Column(db.Integer, primary_key=True)
    produto_id  = db.Column(db.Integer, db.ForeignKey("pdr_produtos.id"), nullable=False, index=True)

    apresentacao = db.Column(db.String(120), default="")
    descricao    = db.Column(db.String(300), default="")
    modelo       = db.Column(db.String(120), default="")
    sku          = db.Column(db.String(50), default="", index=True)

    cadastro_protheus        = db.Column(db.String(40), default="")
    anvisa                   = db.Column(db.String(40), default="")
    numero_anvisa            = db.Column(db.String(60), default="")
    fornecedor               = db.Column(db.String(120), default="", index=True)
    etiqueta                 = db.Column(db.String(60), default="")
    rotulagem                = db.Column(db.String(60), default="")
    planilha_rastreabilidade = db.Column(db.String(60), default="")
    observacoes              = db.Column(db.Text, default="")

    ativo      = db.Column(db.Boolean, default=True, nullable=False, index=True)
    version    = db.Column(db.Integer, default=0, nullable=False)
    criado_em  = db.Column(db.DateTime, default=datetime.now)
    updated_em = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    produto    = db.relationship("Produto", back_populates="apresentacoes")
    documentos = db.relationship(
        "PdrDocumento", back_populates="apresentacao",
        cascade="all, delete-orphan",
    )

    @property
    def is_descontinuada(self):
        return (self.cadastro_protheus or "").upper() in STATUS_DESCONTINUADO

    @property
    def status_global(self):
        """Pendente / Em progresso / Finalizado / Descontinuado a partir dos 4 docs."""
        if self.is_descontinuada:
            return "Descontinuado"
        docs = [d for d in self.documentos if not d.is_descontinuado]
        if not docs:
            return "Pendente"
        oks = sum(1 for d in docs if d.is_ok)
        if oks == len(docs):
            return "Finalizado"
        if oks == 0:
            return "Pendente"
        return "Em progresso"

    @property
    def avanco(self):
        docs = [d for d in self.documentos if not d.is_descontinuado]
        if not docs:
            return 0
        return round(sum(1 for d in docs if d.is_ok) * 100 / len(docs))

    def to_dict(self, com_documentos=True):
        d = {
            "id": self.id,
            "produto_id": self.produto_id,
            "produto_nome": self.produto.nome if self.produto else "",
            "linha": self.produto.linha if self.produto else "",
            "apresentacao": self.apresentacao or "",
            "descricao": self.descricao or "",
            "modelo": self.modelo or "",
            "sku": self.sku or "",
            "cadastro_protheus": self.cadastro_protheus or "",
            "anvisa": self.anvisa or "",
            "numero_anvisa": self.numero_anvisa or "",
            "fornecedor": self.fornecedor or "",
            "etiqueta": self.etiqueta or "",
            "rotulagem": self.rotulagem or "",
            "planilha_rastreabilidade": self.planilha_rastreabilidade or "",
            "observacoes": self.observacoes or "",
            "ativo": bool(self.ativo),
            "version": self.version or 0,
            "status_global": self.status_global,
            "avanco": self.avanco,
            "updated_em": self.updated_em.strftime("%d/%m/%Y %H:%M") if self.updated_em else "",
        }
        if com_documentos:
            d["documentos"] = [doc.to_dict() for doc in self.documentos]
        return d

    def snapshot(self):
        return self.to_dict()


# ── DOCUMENTO (1 por tipo, por apresentação) ──────────────────────────────────
class PdrDocumento(db.Model):
    __tablename__ = "pdr_documentos"

    id              = db.Column(db.Integer, primary_key=True)
    apresentacao_id = db.Column(db.Integer, db.ForeignKey("pdr_apresentacoes.id"),
                                nullable=False, index=True)
    tipo        = db.Column(db.String(40), nullable=False)   # ver TIPOS_DOC
    fase        = db.Column(db.String(60), default="")        # resumo (PENDENTE/FINALIZADO/...)
    status      = db.Column(db.String(80), default="")        # status detalhado de workflow
    codificacao = db.Column(db.String(80), default="")        # só IT
    versao      = db.Column(db.String(40), default="")
    updated_em  = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    apresentacao = db.relationship("Apresentacao", back_populates="documentos")

    @property
    def tipo_label(self):
        return TIPOS_DOC_LABELS.get(self.tipo, self.tipo)

    @property
    def is_ok(self):
        v = (self.status or self.fase or "").upper()
        return v in STATUS_OK

    @property
    def is_descontinuado(self):
        v = (self.status or self.fase or "").upper()
        return v in STATUS_DESCONTINUADO

    def to_dict(self):
        return {
            "id": self.id,
            "apresentacao_id": self.apresentacao_id,
            "tipo": self.tipo,
            "tipo_label": self.tipo_label,
            "fase": self.fase or "",
            "status": self.status or "",
            "codificacao": self.codificacao or "",
            "versao": self.versao or "",
            "is_ok": self.is_ok,
        }
