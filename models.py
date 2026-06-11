"""
models.py — Modelos SQLAlchemy para o DocTrack v4.0
Tabelas: User, Documento, AuditLog, RevokedToken, Responsavel
Nova estrutura: 3 setores (PRE, Fabricante, PDE) com status lineares.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from datetime import datetime
import json

db = SQLAlchemy()
bcrypt = Bcrypt()

# ── CONSTANTES DE DOMÍNIO ─────────────────────────────────────────────────────

SETORES = ["PRE", "Manuais"]

STATUS_PRE = ["Elaborar", "Treinamento Piloto", "Enviado para Homologação", "Homologado"]
STATUS_FABRICANTE = ["Elaborar", "Em andamento", "Concluído"]

STATUS_MAP = {
    "PRE": STATUS_PRE,
    "Manuais": STATUS_FABRICANTE,
}

TIPOS_DOC_FABRICANTE = ["Manual_ES", "Manual_Servico", "Manual_Usuario", "QIQOQD", "Spare_Parts"]

TIPOS_DOC_LABELS = {
    "Manual_ES": "Manual ES",
    "Manual_Servico": "Manual de Serviço",
    "Manual_Usuario": "Manual do Usuário",
    "QIQOQD": "QI/QO/QD",
    "Spare_Parts": "Spare Parts",
}

ACOES_AUDIT = [
    "CREATE", "UPDATE", "DELETE", "STATUS_CHANGE", "LOGIN", "REIMPORT",
    "DOCUMENT_CREATED", "DOCUMENT_UPDATED", "DOCUMENT_DELETED",
    "DOCUMENT_STATUS_UPDATED", "ETAPA_COMPLETED",
    "RESPONSAVEL_ASSIGNED", "RESPONSAVEL_REMOVED",
    "NOTIFICATION", "USER_CONNECTED", "USER_DISCONNECTED",
]


# ── Roles de responsável ─────────────────────────────────────────────────────
class ResponsavelRole:
    ELABORADOR = "elaborador"
    REVISOR_1 = "revisor_1"
    REVISOR_2 = "revisor_2"
    APROVADOR = "aprovador"
    GESTOR = "gestor"

    @classmethod
    def all(cls):
        return [cls.ELABORADOR, cls.REVISOR_1, cls.REVISOR_2, cls.APROVADOR, cls.GESTOR]


# ── USER ──────────────────────────────────────────────────────────────────────

class User(db.Model):
    __tablename__ = "users"

    id         = db.Column(db.Integer, primary_key=True)
    nome       = db.Column(db.String(120), nullable=False)
    email      = db.Column(db.String(120), unique=True, nullable=False, index=True)
    senha_hash = db.Column(db.String(256), nullable=False)
    role       = db.Column(db.String(20), nullable=False, default="tecnico")
    ativo      = db.Column(db.Boolean, default=True)
    criado_em  = db.Column(db.DateTime, default=datetime.now)
    ultimo_login = db.Column(db.DateTime, nullable=True)

    responsabilidades = db.relationship(
        "Responsavel", back_populates="user",
        foreign_keys="Responsavel.user_id"
    )

    def set_senha(self, senha):
        self.senha_hash = bcrypt.generate_password_hash(senha).decode("utf-8")

    def check_senha(self, senha):
        return bcrypt.check_password_hash(self.senha_hash, senha)

    def to_dict(self):
        return {
            "id":           self.id,
            "nome":         self.nome,
            "email":        self.email,
            "role":         self.role,
            "ativo":        bool(self.ativo),
            "criado_em":    self.criado_em.strftime("%d/%m/%Y %H:%M") if self.criado_em else "",
            "ultimo_login": self.ultimo_login.strftime("%d/%m/%Y %H:%M") if self.ultimo_login else "—",
        }


# ── DOCUMENTO ─────────────────────────────────────────────────────────────────

class Documento(db.Model):
    __tablename__ = "documentos"

    id              = db.Column(db.Integer, primary_key=True)
    setor           = db.Column(db.String(30), nullable=False, index=True)
    equipamento     = db.Column(db.String(200), nullable=False, default="")
    sku             = db.Column(db.String(50), default="")
    codigo_doc      = db.Column(db.String(50), default="")
    documento       = db.Column(db.String(300), nullable=False, default="")
    responsavel     = db.Column(db.String(200), default="")
    status          = db.Column(db.String(60), default="Elaborar")
    tipo_doc        = db.Column(db.String(60), default="")
    fabricante      = db.Column(db.String(200), default="")
    data_treinamento  = db.Column(db.DateTime, nullable=True)
    obs_treinamento   = db.Column(db.Text, default="")
    data_homologacao  = db.Column(db.DateTime, nullable=True)
    obs_homologacao   = db.Column(db.Text, default="")
    armazenamento   = db.Column(db.String(500), default="")
    criado_em       = db.Column(db.DateTime, default=datetime.now)
    updated_em      = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    ativo           = db.Column(db.Boolean, default=True, nullable=False, index=True)
    deleted_at      = db.Column(db.DateTime, nullable=True)
    version         = db.Column(db.Integer, default=0, nullable=False)

    responsaveis = db.relationship(
        "Responsavel", back_populates="documento", cascade="all, delete-orphan"
    )

    @property
    def status_global(self):
        s = (self.status or "Elaborar").strip()
        setor = (self.setor or "").strip()

        if setor == "PRE":
            if s == "Homologado":
                return "Finalizado"
            elif s in ("Treinamento Piloto", "Enviado para Homologação"):
                return "Em progresso"
            else:
                return "Pendente"
        else:
            if s == "Concluído":
                return "Finalizado"
            elif s == "Em andamento":
                return "Em progresso"
            else:
                return "Pendente"

    @property
    def tipo_doc_label(self):
        return TIPOS_DOC_LABELS.get(self.tipo_doc, self.tipo_doc or "")

    def to_dict(self):
        return {
            "id":               self.id,
            "setor":            self.setor or "",
            "equipamento":      self.equipamento or "",
            "sku":              self.sku or "",
            "codigo_doc":       self.codigo_doc or "",
            "documento":        self.documento or "",
            "responsavel":      self.responsavel or "",
            "status":           self.status or "Elaborar",
            "tipo_doc":         self.tipo_doc or "",
            "tipo_doc_label":   self.tipo_doc_label,
            "fabricante":       self.fabricante or "",
            "data_treinamento": self.data_treinamento.strftime("%d/%m/%Y") if self.data_treinamento else "",
            "obs_treinamento":  self.obs_treinamento or "",
            "data_homologacao": self.data_homologacao.strftime("%d/%m/%Y") if self.data_homologacao else "",
            "obs_homologacao":  self.obs_homologacao or "",
            "armazenamento":    self.armazenamento or "",
            "status_global":    self.status_global,
            "criado_em":        self.criado_em.strftime("%d/%m/%Y %H:%M") if self.criado_em else "",
            "updated_em":       self.updated_em.strftime("%d/%m/%Y %H:%M") if self.updated_em else "",
            "ativo":            bool(self.ativo),
            "deleted_at":       self.deleted_at.isoformat() if self.deleted_at else None,
            "version":          self.version or 0,
        }

    def snapshot(self):
        return self.to_dict()

    def diff(self, snapshot_anterior: dict) -> dict:
        atual = self.to_dict()
        return {
            k: {"old": snapshot_anterior.get(k), "new": atual.get(k)}
            for k in atual if atual.get(k) != snapshot_anterior.get(k)
        }


# ── RESPONSAVEL ───────────────────────────────────────────────────────────────

class Responsavel(db.Model):
    __tablename__ = "responsaveis"
    __table_args__ = (
        db.UniqueConstraint("documento_id", "user_id", "role",
                            name="uq_doc_user_role"),
    )

    id = db.Column(db.Integer, primary_key=True)
    documento_id = db.Column(db.Integer, db.ForeignKey("documentos.id"),
                             nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                        nullable=False, index=True)
    role = db.Column(db.String(40), nullable=False)
    atribuido_em = db.Column(db.DateTime, default=datetime.now)
    atribuido_por_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    documento = db.relationship("Documento", back_populates="responsaveis")
    user = db.relationship("User", foreign_keys=[user_id],
                           back_populates="responsabilidades")

    def to_dict(self):
        return {
            "id": self.id,
            "documento_id": self.documento_id,
            "user_id": self.user_id,
            "user_email": self.user.email if self.user else None,
            "user_nome": self.user.nome if self.user else None,
            "role": self.role,
            "atribuido_em": self.atribuido_em.isoformat() if self.atribuido_em else None,
        }


# ── AUDIT LOG ─────────────────────────────────────────────────────────────────

class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id            = db.Column(db.Integer, primary_key=True)
    usuario_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    usuario_email = db.Column(db.String(120))
    documento_id  = db.Column(db.Integer, nullable=True)
    acao          = db.Column(db.String(60))
    entidade      = db.Column(db.String(200))
    campo         = db.Column(db.String(80))
    valor_antigo  = db.Column(db.Text)
    valor_novo    = db.Column(db.Text)
    payload_json  = db.Column(db.Text, nullable=True)
    timestamp     = db.Column(db.DateTime, default=datetime.now)
    ip            = db.Column(db.String(50))

    def to_dict(self):
        return {
            "id":           self.id,
            "usuario":      self.usuario_email or "—",
            "usuario_id":   self.usuario_id,
            "documento_id": self.documento_id,
            "acao":         self.acao,
            "entidade":     self.entidade or "—",
            "campo":        self.campo or "—",
            "valor_antigo": self.valor_antigo or "",
            "valor_novo":   self.valor_novo or "",
            "timestamp":    self.timestamp.strftime("%d/%m/%Y %H:%M") if self.timestamp else "",
        }


# ── REVOKED TOKEN (JWT blocklist) ─────────────────────────────────────────────

class RevokedToken(db.Model):
    __tablename__ = "revoked_tokens"

    id         = db.Column(db.Integer, primary_key=True)
    jti        = db.Column(db.String(64), unique=True, nullable=False, index=True)
    revoked_at = db.Column(db.DateTime, default=datetime.now, nullable=False)


# ── ENTREGÁVEIS DE PROJETO ───────────────────────────────────────────────────

CATEGORIAS_ENTREGAVEL = ["Produto", "Sistema", "Documentação", "Capacitação", "Marketing"]
STATUS_ENTREGAVEL = ["na", "pendente", "em_progresso", "concluido"]
MOSCOW = ["Must", "Should", "Could", "Wont"]


def converter_celula(valor):
    """Converte valor de célula da planilha para (status, percentual).

    1 → concluido/100 · 0 → pendente/0 · 0<x<1 → em_progresso/round(x*100)
    NA/vazio/lixo de fórmula → na/None
    """
    if valor is None:
        return ("na", None)
    if isinstance(valor, str):
        v = valor.strip().lower()
        if v in ("", "na", "n/a") or v.startswith("#"):
            return ("na", None)
        try:
            valor = float(v.replace(",", "."))
        except ValueError:
            return ("na", None)
    try:
        x = float(valor)
    except (TypeError, ValueError):
        return ("na", None)
    if x >= 1:
        return ("concluido", 100)
    if x <= 0:
        return ("pendente", 0)
    return ("em_progresso", round(x * 100))


class Projeto(db.Model):
    __tablename__ = "projetos"

    id          = db.Column(db.Integer, primary_key=True)
    nome        = db.Column(db.String(200), nullable=False)
    descricao   = db.Column(db.String(400), default="")
    sku         = db.Column(db.String(50), default="")
    moscow      = db.Column(db.String(10), default="")
    prioridade  = db.Column(db.Integer, default=0)
    consumivel  = db.Column(db.Boolean, default=False)
    lancamento  = db.Column(db.String(40), default="")   # data ou ano em texto livre
    ano         = db.Column(db.Integer, default=2026, index=True)
    ativo       = db.Column(db.Boolean, default=True, nullable=False, index=True)
    criado_em   = db.Column(db.DateTime, default=datetime.now)

    entregaveis = db.relationship("Entregavel", back_populates="projeto",
                                  cascade="all, delete-orphan")

    @property
    def avanco(self):
        """Avanço 0-100: média dos entregáveis aplicáveis (status != na)."""
        valores = []
        for e in self.entregaveis:
            if e.status == "na":
                continue
            if e.status == "concluido":
                valores.append(100)
            elif e.status == "em_progresso":
                valores.append(e.percentual or 0)
            else:
                valores.append(0)
        return round(sum(valores) / len(valores)) if valores else 0

    @property
    def pendentes(self):
        return sum(1 for e in self.entregaveis if e.status == "pendente")

    def to_dict(self, com_entregaveis=False):
        d = {
            "id":         self.id,
            "nome":       (self.nome or "").strip(),
            "descricao":  self.descricao or "",
            "sku":        self.sku or "",
            "moscow":     self.moscow or "",
            "prioridade": self.prioridade or 0,
            "consumivel": bool(self.consumivel),
            "lancamento": self.lancamento or "",
            "ano":        self.ano,
            "ativo":      bool(self.ativo),
            "avanco":     self.avanco,
            "pendentes":  self.pendentes,
            "total_entregaveis": sum(1 for e in self.entregaveis if e.status != "na"),
        }
        if com_entregaveis:
            d["entregaveis"] = [e.to_dict() for e in self.entregaveis]
        return d


class Entregavel(db.Model):
    __tablename__ = "entregaveis"

    id             = db.Column(db.Integer, primary_key=True)
    projeto_id     = db.Column(db.Integer, db.ForeignKey("projetos.id"),
                               nullable=False, index=True)
    tipo           = db.Column(db.String(120), nullable=False)
    categoria      = db.Column(db.String(40), default="Produto")
    status         = db.Column(db.String(20), default="pendente", index=True)
    percentual     = db.Column(db.Integer, nullable=True)
    responsaveis   = db.Column(db.String(200), default="")
    atualizado_por = db.Column(db.String(120), default="")
    atualizado_em  = db.Column(db.DateTime, default=datetime.now,
                               onupdate=datetime.now)

    projeto = db.relationship("Projeto", back_populates="entregaveis")

    def to_dict(self):
        return {
            "id":             self.id,
            "projeto_id":     self.projeto_id,
            "tipo":           (self.tipo or "").strip(),
            "categoria":      self.categoria or "",
            "status":         self.status or "pendente",
            "percentual":     self.percentual,
            "responsaveis":   self.responsaveis or "",
            "atualizado_por": self.atualizado_por or "",
            "atualizado_em":  self.atualizado_em.strftime("%d/%m/%Y %H:%M") if self.atualizado_em else "",
        }
