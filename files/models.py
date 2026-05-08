"""
models.py
=========
Esquema do DocTrack v4. Mudanças vs v3:

  - AuditLog ganhou: usuario_id, entidade_id, payload_json (JSON serializado
    do evento completo). Isso transforma audit_logs em event store funcional.
  - NOVO: Responsavel — relacionamento N:N entre Documentos e Users com role
    (elaborador, revisor, aprovador). Permite editar responsáveis sem mexer
    nas colunas do documento.
  - Documento ganhou helpers: snapshot() e diff(other) para gerar payloads
    de evento limpos.

Mantido do v3:
  - Status global calculado dinamicamente
  - Versionamento otimista (campo `versao`)
"""

from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


# ---------------------------------------------------------------------------
# Roles de responsável (enum lógico)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Users (mantido do v3 com pequenos ajustes)
# ---------------------------------------------------------------------------
class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    nome = db.Column(db.String(120))
    senha_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="leitura")
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    ultimo_login = db.Column(db.DateTime)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relacionamento com responsabilidades (N:N via Responsavel).
    # foreign_keys explícito porque Responsavel tem 2 FKs para users
    # (user_id = quem é responsável, atribuido_por_id = quem atribuiu).
    responsabilidades = db.relationship(
        "Responsavel",
        back_populates="user",
        foreign_keys="Responsavel.user_id",
        cascade="all, delete-orphan",
    )

    def set_password(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def check_password(self, senha):
        return check_password_hash(self.senha_hash, senha)

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "nome": self.nome,
            "role": self.role,
            "ativo": self.ativo,
        }


# ---------------------------------------------------------------------------
# Documentos
# ---------------------------------------------------------------------------
class Documento(db.Model):
    __tablename__ = "documentos"

    id = db.Column(db.Integer, primary_key=True)
    equipamento = db.Column(db.String(120), index=True)
    origem = db.Column(db.String(120), index=True)         # categoria/setor
    titulo = db.Column(db.String(255))
    descricao = db.Column(db.Text)

    # Etapas (mantido do v3 — cada uma tem status próprio)
    etapa_elaboracao = db.Column(db.String(50), default="Pendente")
    etapa_revisao1 = db.Column(db.String(50), default="Pendente")
    etapa_revisao2 = db.Column(db.String(50), default="Pendente")
    etapa_aprovacao = db.Column(db.String(50), default="Pendente")

    # Datas
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    atualizado_em = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    prazo = db.Column(db.DateTime)

    # Versionamento otimista (mantido do v3)
    versao = db.Column(db.Integer, default=1, nullable=False)

    responsaveis = db.relationship(
        "Responsavel", back_populates="documento", cascade="all, delete-orphan"
    )

    # ---- Status global calculado em runtime (mantido do v3) ----
    @property
    def status_global(self):
        etapas = [self.etapa_elaboracao, self.etapa_revisao1,
                  self.etapa_revisao2, self.etapa_aprovacao]
        if all(e == "Concluído" for e in etapas):
            return "Finalizado"
        if any(e == "Em andamento" for e in etapas):
            return "Em Progresso"
        if any(e == "Atrasado" for e in etapas):
            return "Atrasado"
        return "Pendente"

    @property
    def esta_atrasado(self):
        return (
            self.prazo is not None
            and self.prazo < datetime.now(timezone.utc)
            and self.status_global != "Finalizado"
        )

    def snapshot(self):
        """Estado serializável — usado em payloads de evento e API."""
        return {
            "id": self.id,
            "equipamento": self.equipamento,
            "origem": self.origem,
            "titulo": self.titulo,
            "descricao": self.descricao,
            "etapa_elaboracao": self.etapa_elaboracao,
            "etapa_revisao1": self.etapa_revisao1,
            "etapa_revisao2": self.etapa_revisao2,
            "etapa_aprovacao": self.etapa_aprovacao,
            "status_global": self.status_global,
            "esta_atrasado": self.esta_atrasado,
            "prazo": self.prazo.isoformat() if self.prazo else None,
            "atualizado_em": self.atualizado_em.isoformat() if self.atualizado_em else None,
            "versao": self.versao,
            "responsaveis": [r.to_dict() for r in self.responsaveis],
        }

    def diff(self, snapshot_anterior: dict) -> dict:
        """Compara snapshot atual com anterior, retorna apenas campos alterados."""
        atual = self.snapshot()
        return {
            k: {"old": snapshot_anterior.get(k), "new": atual.get(k)}
            for k in atual
            if atual.get(k) != snapshot_anterior.get(k)
        }


# ---------------------------------------------------------------------------
# Responsavel — N:N entre Documento e User com role
# ---------------------------------------------------------------------------
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
    role = db.Column(db.String(40), nullable=False)  # ResponsavelRole.*

    atribuido_em = db.Column(db.DateTime,
                             default=lambda: datetime.now(timezone.utc))
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


# ---------------------------------------------------------------------------
# AuditLog — agora também é o Event Store
# ---------------------------------------------------------------------------
class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    usuario_email = db.Column(db.String(120), index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)

    acao = db.Column(db.String(60), index=True)   # event_type
    entidade = db.Column(db.String(60))            # 'documento', 'responsavel', etc
    entidade_id = db.Column(db.Integer, index=True)

    valor_antigo = db.Column(db.Text)              # JSON serializado
    valor_novo = db.Column(db.Text)                # JSON serializado
    payload_json = db.Column(db.Text)              # evento completo serializado

    criado_em = db.Column(db.DateTime,
                          default=lambda: datetime.now(timezone.utc),
                          index=True)

    def to_dict(self):
        import json
        try:
            payload = json.loads(self.payload_json) if self.payload_json else {}
        except (TypeError, json.JSONDecodeError):
            payload = {}
        return {
            "id": self.id,
            "event_type": self.acao,
            "user_email": self.usuario_email,
            "user_id": self.usuario_id,
            "entidade": self.entidade,
            "entidade_id": self.entidade_id,
            "payload": payload,
            "timestamp": self.criado_em.isoformat() if self.criado_em else None,
        }
