"""
models.py — Modelos SQLAlchemy para o DocTrack v4.0
Tabelas: User, Documento, AuditLog, RevokedToken, Responsavel
Nova estrutura: 3 setores (PRE, Fabricante, PDE) com status lineares.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from datetime import datetime, timedelta
import json
import secrets

from areas import AREA_SLUGS, parse_areas

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

# Tipos de documento por setor. Cada equipamento tem 1 documento de cada tipo.
TIPOS_DOC_PRE = ["IT", "Checklist"]
TIPOS_DOC_FABRICANTE = [
    "Manual_Usuario", "Manual_ES", "Manual_Servico",
    "Spare_Parts", "Dossie", "Guia_Instalacao", "QIQOQD",
]
TIPOS_DOC_TODOS = TIPOS_DOC_PRE + TIPOS_DOC_FABRICANTE

# setor (pipeline de status) de cada tipo de documento
SETOR_DO_TIPO = {t: "PRE" for t in TIPOS_DOC_PRE}
SETOR_DO_TIPO.update({t: "Manuais" for t in TIPOS_DOC_FABRICANTE})

TIPOS_DOC_LABELS = {
    "IT":              "Instrução de Trabalho",
    "Checklist":       "Checklist",
    "Manual_Usuario":  "Manual do Usuário PT",
    "Manual_ES":       "Manual do Usuário ES",
    "Manual_Servico":  "Manual de Serviço",
    "Spare_Parts":     "Spare Parts",
    "Dossie":          "Dossiê",
    "Guia_Instalacao": "Guia de Instalação",
    "QIQOQD":          "QI/QO/QD",
}

ACOES_AUDIT = [
    "CREATE", "UPDATE", "DELETE", "STATUS_CHANGE", "LOGIN", "REIMPORT",
    "DOCUMENT_CREATED", "DOCUMENT_UPDATED", "DOCUMENT_DELETED",
    "DOCUMENT_STATUS_UPDATED", "ETAPA_COMPLETED",
    "RESPONSAVEL_ASSIGNED", "RESPONSAVEL_REMOVED",
    "NOTIFICATION", "USER_CONNECTED", "USER_DISCONNECTED",
    "FIRST_ACCESS", "PASSWORD_RESET",
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

    # Acesso ao módulo PDR (P&D de reagentes). Legado: substituído pela coluna
    # `areas`; mantido só para compatibilidade da migração (backfill de áreas).
    pode_pdr   = db.Column(db.Boolean, default=False, nullable=False)

    # Áreas de P&D que o usuário acessa (CSV de slugs, ex.: "pde,pdr").
    # Admin sempre acessa todas — ver area_slugs(). Fonte dos slugs: areas.py.
    areas      = db.Column(db.String(200), default="", nullable=False)

    # Primeiro acesso / reset de senha (modelo de convite)
    # Conta pendente: precisa_definir_senha=True, senha_hash inutilizável e
    # um código de ativação (hash) que o usuário troca pela própria senha.
    precisa_definir_senha = db.Column(db.Boolean, default=False, nullable=False)
    ativacao_codigo_hash  = db.Column(db.String(256), nullable=True)
    ativacao_expira       = db.Column(db.DateTime, nullable=True)

    responsabilidades = db.relationship(
        "Responsavel", back_populates="user",
        foreign_keys="Responsavel.user_id"
    )

    # Validade padrão do código de ativação
    ATIVACAO_VALIDADE_DIAS = 7

    def set_senha(self, senha):
        self.senha_hash = bcrypt.generate_password_hash(senha).decode("utf-8")
        # Definir uma senha conclui qualquer pendência de primeiro acesso/reset
        self.precisa_definir_senha = False
        self.ativacao_codigo_hash  = None
        self.ativacao_expira       = None

    def check_senha(self, senha):
        # Conta pendente (sem senha utilizável) nunca autentica por senha
        if self.precisa_definir_senha or not self.senha_hash:
            return False
        return bcrypt.check_password_hash(self.senha_hash, senha)

    def gerar_codigo_ativacao(self):
        """Coloca a conta em estado de primeiro acesso e devolve o código em
        texto puro (mostrado uma única vez para o admin)."""
        codigo = secrets.token_hex(4).upper()          # ex.: "A1B2C3D4"
        self.ativacao_codigo_hash = bcrypt.generate_password_hash(codigo).decode("utf-8")
        self.ativacao_expira      = datetime.now() + timedelta(days=self.ATIVACAO_VALIDADE_DIAS)
        self.precisa_definir_senha = True
        # Hash inutilizável: mantém senha_hash NOT NULL sem permitir login por senha
        self.senha_hash = bcrypt.generate_password_hash(secrets.token_urlsafe(32)).decode("utf-8")
        return codigo

    def check_codigo(self, codigo):
        """Valida o código de ativação (existe, não expirou e confere)."""
        if not self.precisa_definir_senha or not self.ativacao_codigo_hash:
            return False
        if self.ativacao_expira and datetime.now() > self.ativacao_expira:
            return False
        return bcrypt.check_password_hash(self.ativacao_codigo_hash, (codigo or "").strip().upper())

    def area_slugs(self):
        """Áreas que o usuário acessa. Admin acessa todas."""
        if self.role == "admin":
            return list(AREA_SLUGS)
        return parse_areas(self.areas)

    def tem_area(self, slug):
        return self.role == "admin" or slug in parse_areas(self.areas)

    def to_dict(self):
        return {
            "id":           self.id,
            "nome":         self.nome,
            "email":        self.email,
            "role":         self.role,
            "ativo":        bool(self.ativo),
            "pode_pdr":     bool(self.pode_pdr),
            "areas":        self.area_slugs(),
            "precisa_definir_senha": bool(self.precisa_definir_senha),
            "criado_em":    self.criado_em.strftime("%d/%m/%Y %H:%M") if self.criado_em else "",
            "ultimo_login": self.ultimo_login.strftime("%d/%m/%Y %H:%M") if self.ultimo_login else "—",
        }


# ── DOCUMENTO ─────────────────────────────────────────────────────────────────

class Documento(db.Model):
    __tablename__ = "documentos"

    id              = db.Column(db.Integer, primary_key=True)
    setor           = db.Column(db.String(30), nullable=False, index=True)
    equipamento     = db.Column(db.String(200), nullable=False, default="")
    # Vínculo com a entidade Equipamento (identidade compartilhada). Nullable
    # durante a transição; backfill no startup preenche para os docs existentes.
    equipamento_id  = db.Column(db.Integer, db.ForeignKey("equipamentos.id"),
                                nullable=True, index=True)
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
    # Identidade do equipamento (fonte única). joined evita N+1 ao serializar listas.
    equipamento_rel = db.relationship("Equipamento", foreign_keys=[equipamento_id],
                                      lazy="joined")

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
            "equipamento_id":   self.equipamento_id,
            # Identidade vinda da entidade Equipamento (vazio se ainda não vinculado)
            "nome_original":    (self.equipamento_rel.nome_original if self.equipamento_rel else ""),
            "anvisa":           (self.equipamento_rel.anvisa if self.equipamento_rel else ""),
            "familia":          (self.equipamento_rel.familia if self.equipamento_rel else ""),
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


# ── EQUIPAMENTO ───────────────────────────────────────────────────────────────
# Fonte única da identidade do equipamento. Os documentos (9 por equipamento)
# referenciam esta entidade via Documento.equipamento_id. Campos que descrevem o
# equipamento (não o documento) moram aqui: nome original, ANVISA, família, etc.

class Equipamento(db.Model):
    __tablename__ = "equipamentos"

    id                 = db.Column(db.Integer, primary_key=True)
    nome               = db.Column(db.String(200), nullable=False, index=True)  # Nome comercial / chave de junção
    nome_original      = db.Column(db.String(300), default="")
    nome_tecnico       = db.Column(db.String(400), default="")  # nome longo/descritivo (planilha mestra)
    descricao          = db.Column(db.Text, default="")         # descritivo livre (≠ nome_tecnico ≠ observacoes)
    codigo_interno     = db.Column(db.String(50), default="")
    sku                = db.Column(db.String(50), default="")   # SKU de Venda (chave de junção)
    sku_importacao     = db.Column(db.String(50), default="")   # SKU de Importação
    classificacao_reg  = db.Column(db.String(20), default="")   # "RUO" | "IVD" | "" (nem todo equip. tem registro ANVISA)
    anvisa             = db.Column(db.String(60), default="")   # nº de registro ANVISA
    anvisa_registro    = db.Column(db.String(40), default="")   # data (texto, padrão do projeto)
    anvisa_validade    = db.Column(db.String(40), default="")   # data (texto)
    fabricante         = db.Column(db.String(200), default="")
    codigo_fabricante  = db.Column(db.String(80), default="")   # código interno do fabricante (part number)
    familia            = db.Column(db.String(120), default="")  # LEGADO (texto); migrar p/ familia_id
    status             = db.Column(db.String(40), default="Ativo")  # Ativo/Obsoleto/Descontinuado
    bloqueado          = db.Column(db.Boolean, default=False, nullable=False, index=True)
    observacoes        = db.Column(db.Text, default="")
    armazenamento_base = db.Column(db.String(500), default="")
    # Taxonomia gerenciada (família aninhada na categoria)
    categoria_id       = db.Column(db.Integer, db.ForeignKey("categorias_equipamento.id"), nullable=True, index=True)
    familia_id         = db.Column(db.Integer, db.ForeignKey("familias_equipamento.id"), nullable=True, index=True)
    linha_id           = db.Column(db.Integer, db.ForeignKey("linhas_produto.id"), nullable=True, index=True)
    ativo              = db.Column(db.Boolean, default=True, nullable=False, index=True)
    criado_em          = db.Column(db.DateTime, default=datetime.now)
    updated_em         = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    categoria_rel = db.relationship("CategoriaEquipamento", foreign_keys=[categoria_id], lazy="joined")
    familia_rel   = db.relationship("FamiliaEquipamento", foreign_keys=[familia_id], lazy="joined")
    linha_rel     = db.relationship("LinhaProduto", foreign_keys=[linha_id], lazy="joined")

    def to_dict(self):
        return {
            "id":                 self.id,
            "nome":               self.nome or "",
            "nome_original":      self.nome_original or "",
            "nome_tecnico":       self.nome_tecnico or "",
            "descricao":          self.descricao or "",
            "codigo_interno":     self.codigo_interno or "",
            "sku":                self.sku or "",
            "sku_importacao":     self.sku_importacao or "",
            "classificacao_reg":  self.classificacao_reg or "",
            "anvisa":             self.anvisa or "",
            "anvisa_registro":    self.anvisa_registro or "",
            "anvisa_validade":    self.anvisa_validade or "",
            "fabricante":         self.fabricante or "",
            "codigo_fabricante":  self.codigo_fabricante or "",
            "status":             self.status or "Ativo",
            "bloqueado":          bool(self.bloqueado),
            "observacoes":        self.observacoes or "",
            "armazenamento_base": self.armazenamento_base or "",
            "categoria_id":       self.categoria_id,
            "categoria":          (self.categoria_rel.nome if self.categoria_rel else ""),
            "familia_id":         self.familia_id,
            "familia":            (self.familia_rel.nome if self.familia_rel else (self.familia or "")),
            "ativo":              bool(self.ativo),
        }


# ── TAXONOMIA DE EQUIPAMENTOS (gerenciável) ──────────────────────────────────
# Categoria → Famílias (aninhadas) · Linhas (lista plana). O vínculo de cada
# equipamento é feito na ficha do card; estas tabelas só guardam as listas.

class CategoriaEquipamento(db.Model):
    __tablename__ = "categorias_equipamento"
    id    = db.Column(db.Integer, primary_key=True)
    nome  = db.Column(db.String(120), nullable=False, index=True)
    ordem = db.Column(db.Integer, default=0)
    ativo = db.Column(db.Boolean, default=True, nullable=False, index=True)
    familias = db.relationship("FamiliaEquipamento", back_populates="categoria",
                               order_by="FamiliaEquipamento.nome", cascade="all, delete-orphan")

    def to_dict(self, com_familias=False):
        d = {"id": self.id, "nome": self.nome or "", "ordem": self.ordem or 0, "ativo": bool(self.ativo)}
        if com_familias:
            d["familias"] = [f.to_dict() for f in self.familias if f.ativo]
        return d


class FamiliaEquipamento(db.Model):
    __tablename__ = "familias_equipamento"
    id           = db.Column(db.Integer, primary_key=True)
    categoria_id = db.Column(db.Integer, db.ForeignKey("categorias_equipamento.id"), nullable=False, index=True)
    nome         = db.Column(db.String(120), nullable=False, index=True)
    ordem        = db.Column(db.Integer, default=0)
    ativo        = db.Column(db.Boolean, default=True, nullable=False, index=True)
    categoria = db.relationship("CategoriaEquipamento", back_populates="familias")

    def to_dict(self):
        return {"id": self.id, "categoria_id": self.categoria_id,
                "categoria_nome": self.categoria.nome if self.categoria else "",
                "nome": self.nome or "", "ordem": self.ordem or 0, "ativo": bool(self.ativo)}


class LinhaProduto(db.Model):
    __tablename__ = "linhas_produto"
    id    = db.Column(db.Integer, primary_key=True)
    nome  = db.Column(db.String(120), nullable=False, index=True)
    ordem = db.Column(db.Integer, default=0)
    ativo = db.Column(db.Boolean, default=True, nullable=False, index=True)

    def to_dict(self):
        return {"id": self.id, "nome": self.nome or "", "ordem": self.ordem or 0, "ativo": bool(self.ativo)}


# ── ITENS DO EQUIPAMENTO (consumíveis e acessórios) ──────────────────────────
# Cada equipamento tem N consumíveis e N acessórios. Item mínimo: nome + SKUs.

ITEM_TIPOS = ["consumivel", "acessorio"]

class EquipamentoItem(db.Model):
    __tablename__ = "equip_itens"

    id             = db.Column(db.Integer, primary_key=True)
    equipamento_id = db.Column(db.Integer, db.ForeignKey("equipamentos.id"),
                               nullable=False, index=True)
    tipo           = db.Column(db.String(20), nullable=False, index=True)  # "consumivel" | "acessorio"
    nome           = db.Column(db.String(200), nullable=False, default="")
    sku            = db.Column(db.String(50), default="")   # SKU de Venda
    sku_importacao = db.Column(db.String(50), default="")   # SKU de Importação
    ordem          = db.Column(db.Integer, default=0)
    ativo          = db.Column(db.Boolean, default=True, nullable=False, index=True)
    criado_em      = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "id":             self.id,
            "equipamento_id": self.equipamento_id,
            "tipo":           self.tipo or "",
            "nome":           self.nome or "",
            "sku":            self.sku or "",
            "sku_importacao": self.sku_importacao or "",
            "ordem":          self.ordem or 0,
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
TIPOS_PROJETO = ["OEM", "Revenda"]   # tipo do projeto → define o modelo de entregáveis


# ── PMO / EVM ────────────────────────────────────────────────────────────────
# Faixas de semáforo para índices de desempenho (SPI/CPI).
# >= 0.95 ok · 0.85–0.95 atenção · < 0.85 crítico
PMO_OK, PMO_ATENCAO = 0.95, 0.85


def _parse_iso(s):
    """'2026-06-15' / '2026-06' / '15/06/2026' / '2026' → date | None."""
    if not s:
        return None
    s = str(s).strip()
    import re
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3])).date()
        except ValueError:
            return None
    m = re.match(r"^(\d{4})-(\d{2})$", s)            # competência ano-mês
    if m:
        return datetime(int(m[1]), int(m[2]), 1).date()
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        try:
            return datetime(int(m[3]), int(m[2]), int(m[1])).date()
        except ValueError:
            return None
    m = re.match(r"^(\d{4})$", s)
    if m:
        return datetime(int(m[1]), 1, 1).date()
    return None


def _classificar_indice(idx):
    """SPI/CPI → 'ok' | 'atencao' | 'critico' | 'sem_dados'."""
    if idx is None:
        return "sem_dados"
    if idx >= PMO_OK:
        return "ok"
    if idx >= PMO_ATENCAO:
        return "atencao"
    return "critico"


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
    tipo        = db.Column(db.String(20), default="")    # "OEM" | "Revenda" | "" (projetos antigos)
    sku         = db.Column(db.String(50), default="")
    moscow      = db.Column(db.String(10), default="")
    prioridade  = db.Column(db.Integer, default=0)
    consumivel  = db.Column(db.Boolean, default=False)
    lancamento  = db.Column(db.String(40), default="")   # data ou ano em texto livre
    ano         = db.Column(db.Integer, default=2026, index=True)
    ativo       = db.Column(db.Boolean, default=True, nullable=False, index=True)
    criado_em   = db.Column(db.DateTime, default=datetime.now)

    # ── PMO: cronograma (datas ISO em texto) + orçamento (BAC) ──
    data_inicio_prev = db.Column(db.String(40), default="")
    data_inicio_real = db.Column(db.String(40), default="")
    data_fim_prev    = db.Column(db.String(40), default="")
    data_fim_real    = db.Column(db.String(40), default="")
    orcamento        = db.Column(db.Float, default=0.0)   # BAC – Budget At Completion

    entregaveis = db.relationship("Entregavel", back_populates="projeto",
                                  cascade="all, delete-orphan")
    mensais = db.relationship("ProjetoMensal", back_populates="projeto",
                              cascade="all, delete-orphan",
                              order_by="ProjetoMensal.competencia")

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

    # ── PMO / EVM ────────────────────────────────────────────────────────────
    @property
    def pct_prazo_decorrido(self):
        """% do cronograma já decorrido (início real ou previsto → fim previsto)."""
        ini = _parse_iso(self.data_inicio_real) or _parse_iso(self.data_inicio_prev)
        fim = _parse_iso(self.data_fim_prev)
        if not ini or not fim or fim <= ini:
            return None
        hoje = datetime.now().date()
        if hoje <= ini:
            return 0
        if hoje >= fim:
            return 100
        return round((hoje - ini).days / (fim - ini).days * 100)

    def previsto_em(self, competencia):
        """Baseline linear: % que DEVERIA estar pronto ao fim da competência (AAAA-MM),
        em função das datas planejadas (início → fim previsto). None sem datas válidas."""
        import re, calendar
        m = re.match(r"^(\d{4})-(\d{2})$", competencia or "")
        if not m:
            return None
        ini = _parse_iso(self.data_inicio_prev) or _parse_iso(self.data_inicio_real)
        fim = _parse_iso(self.data_fim_prev)
        if not ini or not fim or fim <= ini:
            return None
        y, mo = int(m.group(1)), int(m.group(2))
        ref = datetime(y, mo, calendar.monthrange(y, mo)[1]).date()   # último dia do mês
        if ref <= ini:
            return 0
        if ref >= fim:
            return 100
        return round((ref - ini).days / (fim - ini).days * 100)

    def _aplicaveis(self):
        return [e for e in self.entregaveis if e.status != "na"]

    def realizado_em(self, ref):
        """% realizado até a data `ref`, pela CONCLUSÃO das tarefas (count-based).
        No ponto presente/futuro usa o avanço vivo (que inclui parciais em andamento)."""
        aplic = self._aplicaveis()
        if not aplic:
            return 0
        if ref >= datetime.now().date():
            return self.avanco
        done = sum(1 for e in aplic
                   if (_parse_iso(e.data_conclusao) and _parse_iso(e.data_conclusao) <= ref))
        return round(done / len(aplic) * 100)

    def recompute_acumulados(self):
        """Recalcula custo_acumulado de cada mês como a soma corrida dos custos
        mensais (custo_mes), em ordem de competência. Chamar após inserir/editar/
        remover um lançamento para manter o acumulado (AC) sempre coerente."""
        total = 0.0
        for m in sorted(self.mensais, key=lambda x: x.competencia or ""):
            total += (m.custo_mes or 0.0)
            m.custo_acumulado = round(total, 2)

    @property
    def _custo_atual(self):
        """Custo total gasto (AC) = soma de todos os custos mensais lançados."""
        if not self.mensais:
            return None
        return round(sum(m.custo_mes or 0.0 for m in self.mensais), 2)

    def pmo_metrics(self):
        """Métricas EVM ao vivo.

        Previsto = baseline linear pelas datas, na data de hoje (PV).
        Realizado = avanço dos entregáveis, ao vivo (EV) — caminha com as tarefas concluídas.
        SPI = EV/PV (prazo) · CPI = EV/AC (custo, AC = último custo lançado) · EAC = BAC/CPI.
        """
        bac = self.orcamento or 0.0
        aplic = self._aplicaveis()
        pct_prev = self.pct_prazo_decorrido                 # baseline em 'hoje'
        pct_real = self.avanco if aplic else None           # avanço vivo dos entregáveis
        ac = self._custo_atual

        pv = bac * pct_prev / 100 if (bac and pct_prev is not None) else None
        ev = bac * pct_real / 100 if (bac and pct_real is not None) else None

        spi = (pct_real / pct_prev) if (pct_prev not in (None, 0) and pct_real is not None) else None
        cpi = (ev / ac) if (ev is not None and ac) else None
        eac = (bac / cpi) if (cpi and bac) else None

        hoje = datetime.now().date()
        return {
            "competencia":     f"{hoje.year:04d}-{hoje.month:02d}",
            "bac":             round(bac, 2),
            "pv":              round(pv, 2) if pv is not None else None,
            "ev":              round(ev, 2) if ev is not None else None,
            "ac":              round(ac, 2) if ac is not None else None,
            "pct_previsto":    pct_prev,
            "pct_realizado":   pct_real,
            "sv":              round(ev - pv, 2) if (ev is not None and pv is not None) else None,
            "cv":              round(ev - ac, 2) if (ev is not None and ac is not None) else None,
            "spi":             round(spi, 3) if spi is not None else None,
            "cpi":             round(cpi, 3) if cpi is not None else None,
            "eac":             round(eac, 2) if eac is not None else None,
            "status_prazo":    _classificar_indice(spi),
            "status_custo":    _classificar_indice(cpi),
            "pct_prazo_decorrido": pct_prev,
            "tem_dados":       bool((pct_prev is not None and pct_real is not None) or ac),
        }

    def serie_mensal(self):
        """Curva-S automática: para cada mês do início até hoje, previsto (baseline) e
        realizado (reconstruído pelas conclusões das tarefas). Custo vem dos lançamentos."""
        import calendar
        ini = _parse_iso(self.data_inicio_real) or _parse_iso(self.data_inicio_prev)
        datas_tarefas = [d for e in self.entregaveis
                         for d in (_parse_iso(e.data_inicio), _parse_iso(e.data_conclusao)) if d]
        if not ini and datas_tarefas:
            ini = min(datas_tarefas)
        if not ini:
            return []
        hoje = datetime.now().date()
        if ini > hoje:
            ini = hoje
        # Término da curva: fim do cronograma (real ou previsto). Se ainda não
        # houver fim definido, acompanha até hoje. Estende até hoje caso o projeto
        # já tenha passado do prazo mas ainda registre andamento.
        fim = _parse_iso(self.data_fim_real) or _parse_iso(self.data_fim_prev) or hoje
        datas_concl = [d for e in self.entregaveis if (d := _parse_iso(e.data_conclusao))]
        if datas_concl:
            fim = max(fim, max(datas_concl))
        if fim < ini:
            fim = ini
        custos_mes = {m.competencia: m.custo_mes for m in self.mensais}
        out = []
        y, mo, count, acum = ini.year, ini.month, 0, 0.0
        tem_custo = False
        while (y < fim.year or (y == fim.year and mo <= fim.month)) and count < 48:
            comp = f"{y:04d}-{mo:02d}"
            ref = datetime(y, mo, calendar.monthrange(y, mo)[1]).date()
            cm = custos_mes.get(comp)
            if cm is not None:
                acum += cm
                tem_custo = True
            out.append({
                "competencia":     comp,
                "pct_previsto":    self.previsto_em(comp),
                "pct_realizado":   self.realizado_em(ref),
                "custo_mes":       cm,
                # acumulado corre desde o primeiro lançamento; antes disso fica None
                "custo_acumulado": round(acum, 2) if tem_custo else None,
            })
            mo += 1
            if mo > 12:
                mo = 1; y += 1
            count += 1
        return out

    def resumo_periodo(self, ini_comp, fim_comp):
        """Tarefas iniciadas/concluídas dentro de um intervalo de competências (AAAA-MM)."""
        ini = _parse_iso(ini_comp + "-01") if ini_comp else None
        fim_d = _parse_iso(fim_comp + "-01") if fim_comp else None
        if fim_d:
            import calendar
            fim_d = datetime(fim_d.year, fim_d.month,
                             calendar.monthrange(fim_d.year, fim_d.month)[1]).date()
        def dentro(d):
            return d and (not ini or d >= ini) and (not fim_d or d <= fim_d)
        iniciadas, concluidas = [], []
        for e in self.entregaveis:
            di, dc = _parse_iso(e.data_inicio), _parse_iso(e.data_conclusao)
            if dentro(di):
                iniciadas.append(e.to_dict())
            if dentro(dc):
                concluidas.append(e.to_dict())
        return {"iniciadas": iniciadas, "concluidas": concluidas}

    def to_dict(self, com_entregaveis=False, com_pmo=False):
        d = {
            "id":         self.id,
            "nome":       (self.nome or "").strip(),
            "descricao":  self.descricao or "",
            "tipo":       self.tipo or "",
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
            "data_inicio_prev": self.data_inicio_prev or "",
            "data_inicio_real": self.data_inicio_real or "",
            "data_fim_prev":    self.data_fim_prev or "",
            "data_fim_real":    self.data_fim_real or "",
            "orcamento":        self.orcamento or 0.0,
            "pmo":              self.pmo_metrics(),
        }
        if com_entregaveis:
            d["entregaveis"] = [e.to_dict() for e in self.entregaveis]
        if com_pmo:
            d["serie_mensal"] = self.serie_mensal()
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
    data_inicio    = db.Column(db.String(40), default="")   # ISO — quando a tarefa começou
    data_conclusao = db.Column(db.String(40), default="")   # ISO — quando foi concluída
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
            "data_inicio":    self.data_inicio or "",
            "data_conclusao": self.data_conclusao or "",
            "atualizado_por": self.atualizado_por or "",
            "atualizado_em":  self.atualizado_em.strftime("%d/%m/%Y %H:%M") if self.atualizado_em else "",
        }


class ModeloEntregavel(db.Model):
    """Item de modelo (template) de entregável por tipo de projeto (OEM/Revenda).

    Ao criar um projeto de um tipo, estes itens são COPIADOS para o projeto como
    entregáveis editáveis. Editar/excluir aqui só afeta projetos criados depois —
    nunca os já existentes (que possuem cópias independentes).
    """
    __tablename__ = "modelos_entregavel"

    id            = db.Column(db.Integer, primary_key=True)
    tipo_projeto  = db.Column(db.String(20), nullable=False, index=True)   # "OEM" | "Revenda"
    categoria     = db.Column(db.String(40), default="Produto")
    tipo          = db.Column(db.String(120), nullable=False)              # nome do entregável
    responsavel_padrao = db.Column(db.String(200), default="")
    ordem         = db.Column(db.Integer, default=0)

    def to_dict(self):
        return {
            "id":                 self.id,
            "tipo_projeto":       self.tipo_projeto,
            "categoria":          self.categoria or "Produto",
            "tipo":               (self.tipo or "").strip(),
            "responsavel_padrao": self.responsavel_padrao or "",
            "ordem":              self.ordem or 0,
        }


class ProjetoMensal(db.Model):
    """Acompanhamento mensal (PMO): previsto × realizado × custo por competência.

    `competencia` é 'YYYY-MM'. Valores são acumulados até o mês (curva-S).
    Um registro por (projeto, competência).
    """
    __tablename__ = "projeto_mensal"
    __table_args__ = (
        db.UniqueConstraint("projeto_id", "competencia", name="uq_projeto_competencia"),
    )

    id              = db.Column(db.Integer, primary_key=True)
    projeto_id      = db.Column(db.Integer, db.ForeignKey("projetos.id"),
                                nullable=False, index=True)
    competencia     = db.Column(db.String(7), nullable=False)   # 'YYYY-MM'
    pct_previsto    = db.Column(db.Integer, default=0)          # % planejado acumulado
    pct_realizado   = db.Column(db.Integer, default=0)          # % executado acumulado
    custo_mes       = db.Column(db.Float, default=0.0)          # R$ gasto NO mês (incremental)
    custo_acumulado = db.Column(db.Float, default=0.0)          # R$ gasto acumulado (AC) — derivado
    atualizado_por  = db.Column(db.String(120), default="")
    atualizado_em   = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    projeto = db.relationship("Projeto", back_populates="mensais")

    def to_dict(self):
        return {
            "id":              self.id,
            "projeto_id":      self.projeto_id,
            "competencia":     self.competencia,
            "pct_previsto":    self.pct_previsto or 0,
            "pct_realizado":   self.pct_realizado or 0,
            "custo_mes":       self.custo_mes or 0.0,
            "custo_acumulado": self.custo_acumulado or 0.0,
            "atualizado_por":  self.atualizado_por or "",
            "atualizado_em":   self.atualizado_em.strftime("%d/%m/%Y %H:%M") if self.atualizado_em else "",
        }
