"""
models.py — Modelos SQLAlchemy para o DocTrack v3.5
Tabelas: User, Documento, AuditLog, RevokedToken, Responsavel
Merge: schema v3 (compatível com frontend) + Responsavel e event-store do v4.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from datetime import datetime
import json

db = SQLAlchemy()
bcrypt = Bcrypt()

# ── CONSTANTES DE DOMÍNIO ─────────────────────────────────────────────────────

ETAPA_STATUS = ["Pendente", "Em andamento", "Concluído"]

ETAPA_ORDER = [
    "etapa_elaboracao",
    "etapa_revisao1",
    "etapa_diagramacao",
    "etapa_revisao2",
]

TIPOS_DOCUMENTO = ["Técnico", "Qualidade", "Engenharia"]

SUBTIPOS_DOCUMENTO = [
    "POP", "IT", "Manual", "P&D",
    "Manual_Usuario", "Manual_Servico", "QIQOQD",
]

ACOES_AUDIT = [
    "CREATE", "UPDATE", "DELETE", "STATUS_CHANGE", "LOGIN", "REIMPORT",
    "DOCUMENT_CREATED", "DOCUMENT_UPDATED", "DOCUMENT_DELETED",
    "DOCUMENT_STATUS_UPDATED", "ETAPA_COMPLETED",
    "RESPONSAVEL_ASSIGNED", "RESPONSAVEL_REMOVED",
    "NOTIFICATION", "USER_CONNECTED", "USER_DISCONNECTED",
]


# ── Roles de responsável (v4) ────────────────────────────────────────────────
class ResponsavelRole:
    ELABORADOR = "elaborador"
    REVISOR_1 = "revisor_1"
    REVISOR_2 = "revisor_2"
    APROVADOR = "aprovador"
    GESTOR = "gestor"

    @classmethod
    def all(cls):
        return [cls.ELABORADOR, cls.REVISOR_1, cls.REVISOR_2,
                cls.APROVADOR, cls.GESTOR]


# ── USER ──────────────────────────────────────────────────────────────────────

class User(db.Model):
    __tablename__ = "users"

    id         = db.Column(db.Integer, primary_key=True)
    nome       = db.Column(db.String(120), nullable=False)
    email      = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash = db.Column(db.String(256), nullable=False)
    role       = db.Column(db.String(20), nullable=False, default="tecnico")
    ativo      = db.Column(db.Boolean, default=True)
    criado_em  = db.Column(db.DateTime, default=datetime.utcnow)
    ultimo_login = db.Column(db.DateTime, nullable=True)

    responsabilidades = db.relationship(
        "Responsavel", back_populates="user",
        foreign_keys="Responsavel.user_id",
        cascade="all, delete-orphan",
    )

    def set_senha(self, senha_plain):
        self.senha_hash = bcrypt.generate_password_hash(senha_plain).decode("utf-8")

    # Alias para compatibilidade com v4
    def set_password(self, senha):
        self.set_senha(senha)

    def check_senha(self, senha_plain):
        return bcrypt.check_password_hash(self.senha_hash, senha_plain)

    def check_password(self, senha):
        return self.check_senha(senha)

    def to_dict(self):
        return {
            "id":          self.id,
            "nome":        self.nome,
            "email":       self.email,
            "role":        self.role,
            "ativo":       self.ativo,
            "criado_em":   self.criado_em.strftime("%d/%m/%Y") if self.criado_em else "",
            "ultimo_login": self.ultimo_login.strftime("%d/%m/%Y %H:%M") if self.ultimo_login else "—",
        }


# ── DOCUMENTO ─────────────────────────────────────────────────────────────────

class Documento(db.Model):
    __tablename__ = "documentos"

    id              = db.Column(db.Integer, primary_key=True)
    origem          = db.Column(db.String(200), nullable=False, default="")
    categoria       = db.Column(db.String(200), nullable=False, default="")
    documento       = db.Column(db.String(300), nullable=False, default="")
    equipamento     = db.Column(db.String(200), nullable=False)
    versao          = db.Column(db.String(50), default="")
    status_principal = db.Column(db.String(60), default="")
    etapa_elaboracao  = db.Column(db.String(60), default="Pendente")
    etapa_revisao1    = db.Column(db.String(60), default="Pendente")
    etapa_diagramacao = db.Column(db.String(60), default="Pendente")
    etapa_revisao2    = db.Column(db.String(60), default="Pendente")
    local           = db.Column(db.String(500), default="")
    tipo_documento  = db.Column(db.String(100), default="")
    subtipo         = db.Column(db.String(100), default="")
    criado_em       = db.Column(db.DateTime, default=datetime.utcnow)
    updated_em      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    ativo           = db.Column(db.Boolean, default=True, nullable=False, index=True)
    deleted_at      = db.Column(db.DateTime, nullable=True)
    version         = db.Column(db.Integer, default=0, nullable=False)

    responsaveis = db.relationship(
        "Responsavel", back_populates="documento", cascade="all, delete-orphan"
    )

    @property
    def status_global(self):
        etapas = [
            self.etapa_elaboracao or "",
            self.etapa_revisao1 or "",
            self.etapa_diagramacao or "",
            self.etapa_revisao2 or "",
        ]
        concluidas = sum(1 for e in etapas if e == "Concluído")
        em_andamento = sum(1 for e in etapas if e == "Em andamento")

        if concluidas == 4:
            return "Finalizado"
        elif em_andamento > 0 or concluidas > 0:
            return "Em progresso"
        else:
            return "Pendente"

    def to_dict(self):
        return {
            "id":               self.id,
            "origem":           self.origem or "",
            "categoria":        self.categoria or "",
            "documento":        self.documento or "",
            "equipamento":      self.equipamento or "",
            "versao":           self.versao or "",
            "status_principal": self.status_principal or "",
            "etapa_elaboracao":  self.etapa_elaboracao or "",
            "etapa_revisao1":    self.etapa_revisao1 or "",
            "etapa_diagramacao": self.etapa_diagramacao or "",
            "etapa_revisao2":    self.etapa_revisao2 or "",
            "local":            self.local or "",
            "tipo_documento":   self.tipo_documento or "",
            "subtipo":          self.subtipo or "",
            "status_global":    self.status_global,
            "criado_em":        self.criado_em.strftime("%d/%m/%Y %H:%M") if self.criado_em else "",
            "updated_em":       self.updated_em.strftime("%d/%m/%Y %H:%M") if self.updated_em else "",
            "ativo":            bool(self.ativo),
            "deleted_at":       self.deleted_at.isoformat() if self.deleted_at else None,
            "version":          self.version or 0,
        }

    def snapshot(self):
        """Alias para compatibilidade com event_bus v4."""
        return self.to_dict()

    def diff(self, snapshot_anterior: dict) -> dict:
        atual = self.to_dict()
        return {
            k: {"old": snapshot_anterior.get(k), "new": atual.get(k)}
            for k in atual if atual.get(k) != snapshot_anterior.get(k)
        }


# ── RESPONSAVEL (v4) ─────────────────────────────────────────────────────────

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
    atribuido_em = db.Column(db.DateTime, default=datetime.utcnow)
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
    timestamp     = db.Column(db.DateTime, default=datetime.utcnow)
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
    revoked_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
