"""
models.py — Modelos SQLAlchemy para o DocTrack v4.0
Tabelas: User, Documento, DocumentoHistorico, AuditLog, RevokedToken
Nova estrutura: 3 setores (PRE, Manuais, PDE) com status lineares.
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

# Setores de documento DE EQUIPAMENTO. É esta lista que define a completude, os
# cards e os KPIs — todo documento de equipamento tem um destes dois pipelines.
SETORES = ["PRE", "Manuais"]

# Documentos de PROCESSO da área (POPs e ITs do próprio P&D: "IT - Elaboração do
# Manual de Serviço"). Não pertencem a nenhum equipamento, então ficam fora da
# completude e do grid — mas são documentos reais, editáveis, com pipeline.
SETOR_PROCESSO = "PDE"
SETORES_TODOS = SETORES + [SETOR_PROCESSO]

STATUS_PRE = ["Elaborar", "Treinamento Piloto", "Enviado para Homologação", "Homologado"]
STATUS_FABRICANTE = ["Elaborar", "Em andamento", "Concluído"]

STATUS_MAP = {
    "PRE": STATUS_PRE,
    "Manuais": STATUS_FABRICANTE,
    # Processo usa o pipeline curto: sem ele, STATUS_MAP.get("PDE") devolvia []
    # e TODO PATCH/PUT de status destes documentos morria em 400 — eles eram
    # permanentemente ineditáveis.
    SETOR_PROCESSO: STATUS_FABRICANTE,
}

# Tipos de documento por setor. Todo equipamento nasce com 1 documento de cada um
# dos 12 tipos; os opcionais nascem em N/A (aplicavel=False) e só entram na
# completude quando alguém os liga.
# Processo PRE: a IT finalizada vem vinculada a 4 checklists.
TIPOS_DOC_PRE = [
    "IT", "Checklist_Conferencia", "Checklist_BurnIn",
    "Checklist_Limpeza_Embalagem", "Checklist_Produto",
]
TIPOS_DOC_FABRICANTE = [
    "Manual_Usuario", "Manual_ES", "Manual_Servico",
    "Spare_Parts", "Dossie", "Guia_Instalacao", "QIQOQD",
]
TIPOS_DOC_TODOS = TIPOS_DOC_PRE + TIPOS_DOC_FABRICANTE

# Opcionais: nascem marcados como "não se aplica" (aplicavel=False). O documento
# existe (a aba Escopo do modal liga/desliga), mas fica fora da completude.
TIPOS_DOC_OPCIONAIS = ["Spare_Parts", "Dossie", "QIQOQD"]

# setor (pipeline de status) de cada tipo de documento
SETOR_DO_TIPO = {t: "PRE" for t in TIPOS_DOC_PRE}
SETOR_DO_TIPO.update({t: "Manuais" for t in TIPOS_DOC_FABRICANTE})

TIPOS_DOC_LABELS = {
    "IT":                          "Instrução de Trabalho",
    "Checklist_Conferencia":       "Checklist de Conferência",
    "Checklist_BurnIn":            "Checklist de Burn-In",
    "Checklist_Limpeza_Embalagem": "Checklist de Limpeza e Embalagem",
    "Checklist_Produto":           "Checklist de Produto",
    "Manual_Usuario":  "Manual do Usuário PT",
    "Manual_ES":       "Manual do Usuário ES",
    "Manual_Servico":  "Manual de Serviço",
    "Spare_Parts":     "Spare Parts",
    "Dossie":          "Dossiê",
    "Guia_Instalacao": "Guia de Instalação",
    "QIQOQD":          "QI/QO/QD",
}

# Estados de cada item de revisão do Índice de Desenvolvimento de Produto (IDP).
# O índice conta só "Revisado"; "N/A" sai do denominador (item não se aplica).
ESTADOS_REVISAO = ["Pendente", "Em revisão", "Revisado", "N/A"]

# Motivos canônicos para marcar um documento como "não se aplica" (N/A).
# Lista fechada de propósito: marcar N/A muda o denominador da completude de
# todo mundo, e motivo em texto livre não é analisável (dos 47 N/A existentes
# quando isto foi criado, ZERO tinham motivo preenchido — o campo era opcional).
# 'outro' é a válvula de escape e exige a descrição livre em motivo_na.
MOTIVOS_NA = {
    "nao_se_aplica_produto": "Não se aplica a este produto",
    "fornecido_fabricante":  "Fornecido pelo fabricante",
    "coberto_outro_doc":     "Coberto por outro documento",
    "equipamento_legado":    "Equipamento legado / fora de linha",
    "sem_registro_anvisa":   "Produto sem registro ANVISA",
    "outro":                 "Outro (descrever)",
}
MOTIVO_NA_LIVRE = "outro"

ACOES_AUDIT = [
    "CREATE", "UPDATE", "DELETE", "STATUS_CHANGE", "LOGIN", "REIMPORT",
    "DOCUMENT_CREATED", "DOCUMENT_UPDATED", "DOCUMENT_DELETED",
    "DOCUMENT_STATUS_UPDATED", "ETAPA_COMPLETED",
    "RESPONSAVEL_ASSIGNED", "RESPONSAVEL_REMOVED",
    "NOTIFICATION", "USER_CONNECTED", "USER_DISCONNECTED",
    "FIRST_ACCESS", "PASSWORD_RESET",
]


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

# N:N documento ↔ usuário. `Documento.responsavel` segue sendo o texto exibido
# (e o que veio da planilha), mas quem responde "é meu?" é esta tabela. Mesmo
# desenho de entregavel_responsaveis e missao_cartao_responsaveis: era o único
# dos três módulos onde responsabilidade ainda era string digitada à mão, o que
# impedia qualquer agregação por pessoa.
documento_responsaveis = db.Table(
    "documento_responsaveis",
    db.Column("documento_id", db.Integer,
              db.ForeignKey("documentos.id", ondelete="CASCADE"),
              primary_key=True),
    db.Column("user_id", db.Integer,
              db.ForeignKey("users.id", ondelete="CASCADE"),
              primary_key=True),
)


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
    # data_treinamento / data_homologacao são datas REALIZADAS (o que aconteceu).
    # `prazo` é a data ALVO de conclusão — sem ela nada pode estar "atrasado".
    data_treinamento  = db.Column(db.DateTime, nullable=True)
    obs_treinamento   = db.Column(db.Text, default="")
    data_homologacao  = db.Column(db.DateTime, nullable=True)
    obs_homologacao   = db.Column(db.Text, default="")
    prazo             = db.Column(db.Date, nullable=True, index=True)
    # Caminho da pasta. Vazio = herda o Equipamento.armazenamento_base (o caso
    # normal: o caminho é do equipamento, não de cada um dos 12 documentos).
    # Preenchido = override deliberado só deste documento.
    armazenamento   = db.Column(db.String(500), default="")
    criado_em       = db.Column(db.DateTime, default=datetime.now)
    updated_em      = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    # ── marcos temporais ─────────────────────────────────────────────────────
    # Documento era o modelo menos instrumentado do sistema, apesar de ser o
    # maior conjunto de dados: `updated_em` é sobrescrito a cada save, então não
    # havia como responder "quanto tempo levou para homologar", "há quantos dias
    # está parado neste status" ou "quantos foram concluídos em março" sem varrer
    # a trilha inteira. Missões e Entregáveis já tinham estas colunas.
    concluido_em     = db.Column(db.DateTime, nullable=True, index=True)
    concluido_por    = db.Column(db.String(120), default="")
    # Quando o documento entrou no status atual — aging sem varrer o histórico
    # (a trilha continua sendo a fonte da série completa).
    entrou_status_em = db.Column(db.DateTime, nullable=True)
    # Início efetivo do trabalho. Com `prazo` fecha a duração planejada.
    data_inicio      = db.Column(db.Date, nullable=True)
    peso             = db.Column(db.Float, default=1.0)   # esforço relativo
    ativo           = db.Column(db.Boolean, default=True, nullable=False, index=True)
    deleted_at      = db.Column(db.DateTime, nullable=True)
    version         = db.Column(db.Integer, default=0, nullable=False)
    # Escopo de documentos do equipamento: aplicavel=False → "não se aplica" (N/A).
    # O documento continua existindo (status, código, histórico preservados), mas
    # sai do denominador da completude (card, chips, KPIs, IDP). Reversível.
    aplicavel       = db.Column(db.Boolean, default=True, nullable=False, index=True)
    # motivo_na_codigo: chave de MOTIVOS_NA (analisável, obrigatória ao marcar N/A).
    # motivo_na: descrição livre — obrigatória apenas quando o código é 'outro'.
    motivo_na_codigo = db.Column(db.String(40), default="")
    motivo_na       = db.Column(db.String(300), default="")

    # Identidade do equipamento (fonte única). joined evita N+1 ao serializar listas.
    equipamento_rel = db.relationship("Equipamento", foreign_keys=[equipamento_id],
                                      lazy="joined")
    responsaveis_users = db.relationship("User", secondary=documento_responsaveis,
                                         backref=db.backref("documentos_atribuidos",
                                                            lazy="dynamic"))
    historico = db.relationship(
        "DocumentoHistorico", back_populates="documento",
        cascade="all, delete-orphan", order_by="DocumentoHistorico.em.desc()")

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

    @property
    def armazenamento_efetivo(self):
        """Caminho que vale para este documento: o override, ou o do equipamento.

        O caminho é atributo do EQUIPAMENTO — antes ele era copiado nas 12 linhas
        de documento, e editá-lo numa aba não refletia nas outras 11.
        """
        proprio = (self.armazenamento or "").strip()
        if proprio:
            return proprio
        eq = self.equipamento_rel
        return (eq.armazenamento_base or "").strip() if eq else ""

    @property
    def motivo_na_label(self):
        """Texto do motivo de N/A: rótulo canônico + detalhe livre, se houver."""
        if self.aplicavel:
            return ""
        base = MOTIVOS_NA.get(self.motivo_na_codigo or "", "")
        detalhe = (self.motivo_na or "").strip()
        if self.motivo_na_codigo == MOTIVO_NA_LIVRE:
            return detalhe or base
        return f"{base} — {detalhe}" if (base and detalhe) else (base or detalhe)

    @property
    def dias_para_prazo(self):
        """Dias até o prazo (negativo = atrasado). None quando não há prazo."""
        if not self.prazo:
            return None
        return (self.prazo - datetime.now().date()).days

    @property
    def atrasado(self):
        """Prazo vencido e documento ainda não finalizado. N/A nunca atrasa."""
        if not self.prazo or not self.aplicavel:
            return False
        if self.status_global == "Finalizado":
            return False
        return self.prazo < datetime.now().date()

    @property
    def concluido(self):
        """Estado terminal, na definição dos KPIs: status_global 'Finalizado'
        (Homologado no PRE, Concluído nos demais setores)."""
        return self.status_global == "Finalizado"

    @property
    def dias_no_status(self):
        """Aging: dias no status atual. É o que separa backlog novo de documento
        parado há dois anos — os dois aparecem como "Elaborar" na lista."""
        base = self.entrou_status_em or self.criado_em
        return (datetime.now() - base).days if base else 0

    @property
    def dias_ciclo(self):
        """Da criação à conclusão, em dias (None enquanto não concluído)."""
        if not self.concluido_em or not self.criado_em:
            return None
        return max((self.concluido_em - self.criado_em).days, 0)

    @property
    def responsaveis_nomes(self):
        """Nomes dos responsáveis: os usuários vinculados quando existem, senão
        o texto livre legado (a planilha só tem nome digitado)."""
        nomes = [u.nome for u in self.responsaveis_users]
        if nomes:
            return nomes
        texto = (self.responsavel or "").strip()
        return [n.strip() for n in texto.split(",") if n.strip()] if texto else []

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
            "prazo":            self.prazo.strftime("%Y-%m-%d") if self.prazo else "",
            "dias_para_prazo":  self.dias_para_prazo,
            "atrasado":         self.atrasado,
            # armazenamento = override do documento (vazio = herda);
            # armazenamento_base = o do equipamento; efetivo = o que vale de fato.
            "armazenamento":    self.armazenamento or "",
            "armazenamento_base": ((self.equipamento_rel.armazenamento_base or "")
                                   if self.equipamento_rel else ""),
            "armazenamento_efetivo": self.armazenamento_efetivo,
            "status_global":    self.status_global,
            "criado_em":        self.criado_em.strftime("%d/%m/%Y %H:%M") if self.criado_em else "",
            "updated_em":       self.updated_em.strftime("%d/%m/%Y %H:%M") if self.updated_em else "",
            # Marcos temporais e responsabilidade tipada
            "responsaveis_ids":   [u.id for u in self.responsaveis_users],
            "responsaveis_nomes": self.responsaveis_nomes,
            "data_inicio":      self.data_inicio.strftime("%Y-%m-%d") if self.data_inicio else "",
            "peso":             self.peso if self.peso is not None else 1.0,
            "concluido":        self.concluido,
            "concluido_em":     self.concluido_em.strftime("%d/%m/%Y %H:%M") if self.concluido_em else "",
            "concluido_por":    self.concluido_por or "",
            "dias_no_status":   self.dias_no_status,
            "dias_ciclo":       self.dias_ciclo,
            "ativo":            bool(self.ativo),
            "deleted_at":       self.deleted_at.isoformat() if self.deleted_at else None,
            "version":          self.version or 0,
            "aplicavel":        bool(self.aplicavel),
            "motivo_na_codigo": self.motivo_na_codigo or "",
            "motivo_na":        self.motivo_na or "",
            "motivo_na_label":  self.motivo_na_label,
        }

    def snapshot(self):
        return self.to_dict()

    def diff(self, snapshot_anterior: dict) -> dict:
        atual = self.to_dict()
        return {
            k: {"old": snapshot_anterior.get(k), "new": atual.get(k)}
            for k in atual if atual.get(k) != snapshot_anterior.get(k)
        }


class DocumentoHistorico(db.Model):
    """Trilha de mudanças de status/escopo de um documento.

    O AuditLog genérico registra "alguém mexeu", mas não serve de série temporal:
    é por usuário/entidade, com valores em texto, e sem ele não dá para responder
    quanto tempo um documento levou de Elaborar até Homologado, há quantos dias
    está parado, ou quantos foram concluídos em março. Mesmo papel do
    EntregavelHistorico no módulo de projetos.

    `evento`: 'status' (mudou de etapa) | 'escopo' (entrou/saiu do N/A).
    """
    __tablename__ = "documento_historico"

    id            = db.Column(db.Integer, primary_key=True)
    documento_id  = db.Column(db.Integer, db.ForeignKey("documentos.id"),
                              nullable=False, index=True)
    evento        = db.Column(db.String(20), default="status", index=True)
    status_antigo = db.Column(db.String(60), default="")
    status_novo   = db.Column(db.String(60), default="")
    aplicavel     = db.Column(db.Boolean, nullable=True)
    motivo        = db.Column(db.String(300), default="")
    em            = db.Column(db.DateTime, default=datetime.now, index=True)
    por           = db.Column(db.String(120), default="")

    documento = db.relationship("Documento", back_populates="historico")

    def to_dict(self):
        return {
            "id":            self.id,
            "documento_id":  self.documento_id,
            "evento":        self.evento or "status",
            "status_antigo": self.status_antigo or "",
            "status_novo":   self.status_novo or "",
            "aplicavel":     self.aplicavel,
            "motivo":        self.motivo or "",
            "em":            self.em.strftime("%d/%m/%Y %H:%M") if self.em else "",
            "em_iso":        self.em.isoformat() if self.em else "",
            "por":           self.por or "",
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
    # SKU de Venda é a chave de junção do importador mestre, do Pareto e dos
    # documentos: indexado para não varrer a tabela em cada casamento e porque
    # a checagem de duplicidade (servidor) consulta por ele a cada gravação.
    sku                = db.Column(db.String(50), default="", index=True)   # SKU de Venda (chave de junção)
    sku_importacao     = db.Column(db.String(50), default="")   # SKU de Importação
    classificacao_reg  = db.Column(db.String(20), default="")   # "RUO" | "IVD" | "" (nem todo equip. tem registro ANVISA)
    anvisa             = db.Column(db.String(60), default="")   # nº de registro ANVISA
    anvisa_registro    = db.Column(db.String(40), default="")   # data (texto, padrão do projeto)
    anvisa_validade    = db.Column(db.String(40), default="")   # data (texto)
    # Situação do registro e classe de risco previstas no plano do módulo. Ficam
    # FORA do denominador do ICE de propósito: incluí-las derrubaria o índice de
    # toda a frota de uma vez e tornaria ilegível o efeito da correção da
    # validade vencida. Para passar a exigi-las, basta acrescentá-las em
    # equipamentos_core.campos_regulatorios().
    classe_risco         = db.Column(db.String(10), default="")   # I | II | III | IV (RDC 751)
    situacao_regulatoria = db.Column(db.String(30), default="")   # Vigente | Em renovação | Cancelado | Não aplicável
    # Descritores técnicos do plano (antes só existia "campos técnicos avançados
    # crescem por fase" escrito na aba).
    modelo             = db.Column(db.String(120), default="")
    tecnologia         = db.Column(db.String(200), default="")
    aplicacao          = db.Column(db.String(300), default="")
    fabricante         = db.Column(db.String(200), default="")
    codigo_fabricante  = db.Column(db.String(80), default="")   # código interno do fabricante (part number)
    familia            = db.Column(db.String(120), default="")  # LEGADO (texto); migrar p/ familia_id
    status             = db.Column(db.String(40), default="Ativo")  # Ativo/Obsoleto/Descontinuado
    bloqueado          = db.Column(db.Boolean, default=False, nullable=False, index=True)
    observacoes        = db.Column(db.Text, default="")
    armazenamento_base = db.Column(db.String(500), default="")
    # Dono do cadastro. A worklist do dashboard listava o que está incompleto sem
    # dizer para quem cobrar; o responsável do documento é por documento, não
    # cobre os campos de cadastro/regulatório do próprio equipamento.
    responsavel        = db.Column(db.String(120), default="")
    # Revisões manuais do IDP (Índice de Desenvolvimento de Produto). Os itens
    # Manual do usuário / IT / Checklists são derivados do status dos documentos
    # (não persistidos aqui); estes três são marcados à mão. Valores: ESTADOS_REVISAO.
    rev_cadastro       = db.Column(db.String(20), default="Pendente")
    rev_estrutura      = db.Column(db.String(20), default="Pendente")
    rev_descritivo     = db.Column(db.String(20), default="Pendente")
    # Retrato do último import da planilha Pareto (priorização comercial).
    pareto_classe      = db.Column(db.String(1), default="")   # "A" | "B" | "C" | ""
    qtd_saidas         = db.Column(db.Integer, default=0)
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
    historico     = db.relationship("EquipamentoHistorico", back_populates="equipamento",
                                    cascade="all, delete-orphan",
                                    order_by="EquipamentoHistorico.em.desc()")
    snapshots     = db.relationship("EquipamentoSnapshot", back_populates="equipamento",
                                    cascade="all, delete-orphan",
                                    order_by="EquipamentoSnapshot.data")

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
            "classe_risco":         self.classe_risco or "",
            "situacao_regulatoria": self.situacao_regulatoria or "",
            "modelo":             self.modelo or "",
            "tecnologia":         self.tecnologia or "",
            "aplicacao":          self.aplicacao or "",
            "fabricante":         self.fabricante or "",
            "codigo_fabricante":  self.codigo_fabricante or "",
            "status":             self.status or "Ativo",
            "bloqueado":          bool(self.bloqueado),
            "observacoes":        self.observacoes or "",
            "armazenamento_base": self.armazenamento_base or "",
            "responsavel":        self.responsavel or "",
            "rev_cadastro":       self.rev_cadastro or "Pendente",
            "rev_estrutura":      self.rev_estrutura or "Pendente",
            "rev_descritivo":     self.rev_descritivo or "Pendente",
            "pareto_classe":      self.pareto_classe or "",
            "qtd_saidas":         self.qtd_saidas or 0,
            "categoria_id":       self.categoria_id,
            "categoria":          (self.categoria_rel.nome if self.categoria_rel else ""),
            "familia_id":         self.familia_id,
            "familia":            (self.familia_rel.nome if self.familia_rel else (self.familia or "")),
            "linha_id":           self.linha_id,
            "linha":              (self.linha_rel.nome if self.linha_rel else ""),
            "ativo":              bool(self.ativo),
            # Sem as datas não dá para responder "quais cadastros estão parados
            # há meses" — a coluna existia e nunca chegava ao cliente.
            "criado_em":          self.criado_em.strftime("%d/%m/%Y %H:%M") if self.criado_em else "",
            "updated_em":         self.updated_em.strftime("%d/%m/%Y %H:%M") if self.updated_em else "",
            "updated_iso":        self.updated_em.isoformat() if self.updated_em else "",
        }


class EquipamentoHistorico(db.Model):
    """Trilha de-para das alterações do equipamento (campo, antigo, novo, quem).

    O AuditLog registrava só QUAIS campos mudaram — `valor_novo` ia vazio e o
    antigo só existia para o nome. Num módulo com pretensão regulatória
    (ISO 13485 / RDC 665) o de-para é justamente o que precisa ser auditável.
    Mesmo papel do DocumentoHistorico, e é isto que alimenta a aba Histórico da
    ficha (que era um texto fixo prometendo "Fase 3").
    """
    __tablename__ = "equipamento_historico"

    id             = db.Column(db.Integer, primary_key=True)
    equipamento_id = db.Column(db.Integer, db.ForeignKey("equipamentos.id"),
                               nullable=False, index=True)
    evento         = db.Column(db.String(20), default="update", index=True)  # create|update|delete|import
    campo          = db.Column(db.String(60), default="", index=True)
    valor_antigo   = db.Column(db.Text, default="")
    valor_novo     = db.Column(db.Text, default="")
    em             = db.Column(db.DateTime, default=datetime.now, index=True)
    por            = db.Column(db.String(120), default="")

    equipamento = db.relationship("Equipamento", back_populates="historico")

    def to_dict(self):
        return {
            "id":             self.id,
            "equipamento_id": self.equipamento_id,
            "evento":         self.evento or "update",
            "campo":          self.campo or "",
            "valor_antigo":   self.valor_antigo or "",
            "valor_novo":     self.valor_novo or "",
            "em":             self.em.strftime("%d/%m/%Y %H:%M") if self.em else "",
            "em_iso":         self.em.isoformat() if self.em else "",
            "por":            self.por or "",
        }


class EquipamentoSnapshot(db.Model):
    """Foto diária dos índices do equipamento (ICE e suas 3 dimensões + IDP).

    Sem isto o ICE é sempre recalculado com os dados de hoje: dá para dizer que
    a frota está em 61%, nunca que subiu de 48% no trimestre nem quem mais
    avançou. Um registro por (equipamento, data), como o ProjetoSnapshot.
    """
    __tablename__ = "equipamento_snapshot"
    __table_args__ = (
        db.UniqueConstraint("equipamento_id", "data", name="uq_snapshot_equip_data"),
    )

    id             = db.Column(db.Integer, primary_key=True)
    equipamento_id = db.Column(db.Integer, db.ForeignKey("equipamentos.id"),
                               nullable=False, index=True)
    data           = db.Column(db.String(10), nullable=False, index=True)   # 'YYYY-MM-DD'
    ice            = db.Column(db.Integer, default=0)
    cad            = db.Column(db.Integer, default=0)
    reg            = db.Column(db.Integer, default=0)
    doc            = db.Column(db.Integer, default=0)
    idp            = db.Column(db.Integer, nullable=True)
    docs_finais    = db.Column(db.Integer, default=0)
    docs_alvo      = db.Column(db.Integer, default=0)
    docs_atrasados = db.Column(db.Integer, default=0)
    criado_em      = db.Column(db.DateTime, default=datetime.now)

    equipamento = db.relationship("Equipamento", back_populates="snapshots")

    def to_dict(self):
        return {
            "data": self.data, "ice": self.ice or 0, "cad": self.cad or 0,
            "reg": self.reg or 0, "doc": self.doc or 0, "idp": self.idp,
            "docs_finais": self.docs_finais or 0, "docs_alvo": self.docs_alvo or 0,
            "docs_atrasados": self.docs_atrasados or 0,
        }


class ImportacaoLog(db.Model):
    """Execução de um importador (planilha mestra ou Pareto), com o relatório.

    Antes ficava uma única linha resumida no AuditLog ("criados=3 atualizados=8"):
    quem importou não conseguia mais rever quais SKUs não casaram nem quais
    linhas vieram inconsistentes, e não havia como comparar duas importações.
    O relatório é gravado como JSON, igual ao que a prévia mostra na tela.
    """
    __tablename__ = "importacao_log"

    id         = db.Column(db.Integer, primary_key=True)
    origem     = db.Column(db.String(30), nullable=False, index=True)  # 'mestra' | 'pareto'
    por        = db.Column(db.String(120), default="")
    em         = db.Column(db.DateTime, default=datetime.now, index=True)
    criados    = db.Column(db.Integer, default=0)
    atualizados = db.Column(db.Integer, default=0)
    sem_match  = db.Column(db.Integer, default=0)
    inconsistencias = db.Column(db.Integer, default=0)
    relatorio  = db.Column(db.Text, default="")   # JSON do relatório completo

    def to_dict(self, com_relatorio=False):
        d = {
            "id": self.id, "origem": self.origem or "", "por": self.por or "",
            "em": self.em.strftime("%d/%m/%Y %H:%M") if self.em else "",
            "em_iso": self.em.isoformat() if self.em else "",
            "criados": self.criados or 0, "atualizados": self.atualizados or 0,
            "sem_match": self.sem_match or 0,
            "inconsistencias": self.inconsistencias or 0,
        }
        if com_relatorio:
            try:
                d["relatorio"] = json.loads(self.relatorio or "{}")
            except (ValueError, TypeError):
                d["relatorio"] = {}
        return d


class ParetoHistorico(db.Model):
    """Retrato de cada importação do Pareto (classe ABC + quantidade de saídas).

    O import sobrescreve `pareto_classe`/`qtd_saidas` e zera quem saiu da
    planilha: existia o retrato de hoje e nenhuma tendência de demanda. Aqui
    fica uma linha por equipamento por importação.
    """
    __tablename__ = "pareto_historico"

    id             = db.Column(db.Integer, primary_key=True)
    equipamento_id = db.Column(db.Integer, db.ForeignKey("equipamentos.id"),
                               nullable=False, index=True)
    data           = db.Column(db.String(10), nullable=False, index=True)   # 'YYYY-MM-DD'
    classe         = db.Column(db.String(1), default="")
    qtd_saidas     = db.Column(db.Integer, default=0)
    criado_em      = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {"data": self.data, "classe": self.classe or "",
                "qtd_saidas": self.qtd_saidas or 0}


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


# ── CONSUMÍVEIS (catálogo global + compatibilidade N:N) ──────────────────────
# Consumível é entidade própria (uma linha por SKU). A compatibilidade com os
# equipamentos é N:N via ConsumivelEquipamento, que carrega o "fornecimento"
# (atributo da RELAÇÃO, não do consumível). Campos que variam por tipo (poços,
# dimensões, volume…) moram em `atributos` (JSON), guiados pelo modelo de campos
# do tipo (TipoConsumivel.campos). Campos extras avulsos por item também entram
# em `atributos` — modelo HÍBRIDO: padrão por tipo + exceções por item.

FORNECIMENTO = ["exclusivo_loccus", "pode_fornecer", "nao_fornecido", "nao_informado"]
FORNECIMENTO_LABEL = {
    "exclusivo_loccus": "Exclusivo Loccus",
    "pode_fornecer":    "Loccus pode fornecer",
    "nao_fornecido":    "Não fornecido pela Loccus",
    "nao_informado":    "Não informado",
}

# Modelo de campos semeado por tipo (o "layout de descritivo" inicial). Cada campo:
# {chave, rotulo, tipo_dado (texto|numero|bool), unidade, aba}. Editável na UI depois.
TIPOS_CONSUMIVEL_SEED = {
    "Ponteira": [
        {"chave": "volume", "rotulo": "Volume", "tipo_dado": "numero", "unidade": "µL", "aba": "espec"},
        {"chave": "com_filtro", "rotulo": "Com filtro", "tipo_dado": "bool", "unidade": "", "aba": "espec"},
        {"chave": "esterilidade", "rotulo": "Esterilidade", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
        {"chave": "material", "rotulo": "Material", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
        {"chave": "apresentacao", "rotulo": "Apresentação", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
    ],
    "Placa PCR": [
        {"chave": "pocos", "rotulo": "Poços", "tipo_dado": "numero", "unidade": "", "aba": "espec"},
        {"chave": "saia", "rotulo": "Saia", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
        {"chave": "volume_poco", "rotulo": "Volume por poço", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
        {"chave": "material", "rotulo": "Material", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
        {"chave": "dimensoes", "rotulo": "Dimensões", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
        {"chave": "esterilidade", "rotulo": "Esterilidade", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
    ],
    "Placa deepwell": [
        {"chave": "pocos", "rotulo": "Poços", "tipo_dado": "numero", "unidade": "", "aba": "espec"},
        {"chave": "volume_poco", "rotulo": "Volume por poço", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
        {"chave": "fundo", "rotulo": "Fundo", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
        {"chave": "material", "rotulo": "Material", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
        {"chave": "dimensoes", "rotulo": "Dimensões", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
    ],
    "Placa": [
        {"chave": "pocos", "rotulo": "Poços", "tipo_dado": "numero", "unidade": "", "aba": "espec"},
        {"chave": "fundo", "rotulo": "Fundo", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
        {"chave": "material", "rotulo": "Material", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
        {"chave": "dimensoes", "rotulo": "Dimensões", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
    ],
    "Kit de extração": [
        {"chave": "metodo", "rotulo": "Método", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
        {"chave": "alvo", "rotulo": "Alvo (DNA/RNA)", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
        {"chave": "reacoes", "rotulo": "Reações", "tipo_dado": "numero", "unidade": "", "aba": "espec"},
    ],
    "MasterMix / Reagente": [
        {"chave": "volume", "rotulo": "Volume", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
        {"chave": "concentracao", "rotulo": "Concentração", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
        {"chave": "reacoes", "rotulo": "Reações", "tipo_dado": "numero", "unidade": "", "aba": "espec"},
        {"chave": "armazenamento", "rotulo": "Armazenamento", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
    ],
    "Filme de vedação": [
        {"chave": "largura", "rotulo": "Largura", "tipo_dado": "texto", "unidade": "mm", "aba": "espec"},
        {"chave": "comprimento", "rotulo": "Comprimento", "tipo_dado": "texto", "unidade": "m", "aba": "espec"},
        {"chave": "material", "rotulo": "Material", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
        {"chave": "aplicacao", "rotulo": "Aplicação", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
    ],
    "Cartucho": [
        {"chave": "volume", "rotulo": "Volume", "tipo_dado": "texto", "unidade": "mL", "aba": "espec"},
        {"chave": "material", "rotulo": "Material", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
    ],
    "Tip comb / tira": [
        {"chave": "canais", "rotulo": "Canais", "tipo_dado": "numero", "unidade": "", "aba": "espec"},
        {"chave": "material", "rotulo": "Material", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
    ],
    "Lâmina": [
        {"chave": "material", "rotulo": "Material", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
        {"chave": "aplicacao", "rotulo": "Aplicação", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
    ],
    "Reservatório": [
        {"chave": "volume", "rotulo": "Volume", "tipo_dado": "texto", "unidade": "mL", "aba": "espec"},
        {"chave": "calhas", "rotulo": "Calhas", "tipo_dado": "numero", "unidade": "", "aba": "espec"},
        {"chave": "material", "rotulo": "Material", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
    ],
    "Tampa": [
        {"chave": "material", "rotulo": "Material", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
        {"chave": "aplicacao", "rotulo": "Aplicação", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
    ],
    "Tubo": [
        {"chave": "volume", "rotulo": "Volume", "tipo_dado": "texto", "unidade": "mL", "aba": "espec"},
        {"chave": "material", "rotulo": "Material", "tipo_dado": "texto", "unidade": "", "aba": "espec"},
    ],
    "Outro": [],
}


class TipoConsumivel(db.Model):
    __tablename__ = "tipos_consumivel"
    id     = db.Column(db.Integer, primary_key=True)
    nome   = db.Column(db.String(120), nullable=False, index=True)
    ordem  = db.Column(db.Integer, default=0)
    ativo  = db.Column(db.Boolean, default=True, nullable=False, index=True)
    campos = db.Column(db.Text, default="[]")   # JSON: modelo de campos do tipo

    def campos_list(self):
        try:
            v = json.loads(self.campos or "[]")
            return v if isinstance(v, list) else []
        except Exception:
            return []

    def to_dict(self):
        return {"id": self.id, "nome": self.nome or "", "ordem": self.ordem or 0,
                "ativo": bool(self.ativo), "campos": self.campos_list()}


class Consumivel(db.Model):
    __tablename__ = "consumiveis"
    id             = db.Column(db.Integer, primary_key=True)
    nome           = db.Column(db.String(200), nullable=False, index=True)
    sku            = db.Column(db.String(50), default="", index=True)   # SKU de Venda (chave de dedup)
    sku_importacao = db.Column(db.String(50), default="")
    fabricante     = db.Column(db.String(200), default="")
    descricao      = db.Column(db.Text, default="")
    tipo_id        = db.Column(db.Integer, db.ForeignKey("tipos_consumivel.id"), nullable=True, index=True)
    atributos      = db.Column(db.Text, default="{}")   # JSON: valores (campos do modelo + extras)
    pendente_sku   = db.Column(db.Boolean, default=False, nullable=False, index=True)
    status         = db.Column(db.String(40), default="Ativo")
    ativo          = db.Column(db.Boolean, default=True, nullable=False, index=True)
    criado_em      = db.Column(db.DateTime, default=datetime.now)
    updated_em     = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    tipo_rel = db.relationship("TipoConsumivel", foreign_keys=[tipo_id], lazy="joined")

    def atributos_dict(self):
        try:
            v = json.loads(self.atributos or "{}")
            return v if isinstance(v, dict) else {}
        except Exception:
            return {}

    def marcar_pendencia_sku(self):
        """Deriva pendente_sku do SKU atual (sem SKU → pendente). Fonte única da
        fórmula: chame após qualquer escrita em `sku` para manter o flag coerente."""
        self.pendente_sku = not bool((self.sku or "").strip())

    def to_dict(self, com_equip=False):
        vinc = [v for v in (self.vinculos or []) if v.ativo]
        d = {
            "id": self.id, "nome": self.nome or "", "sku": self.sku or "",
            "sku_importacao": self.sku_importacao or "", "fabricante": self.fabricante or "",
            "descricao": self.descricao or "", "tipo_id": self.tipo_id,
            "tipo": (self.tipo_rel.nome if self.tipo_rel else ""),
            "atributos": self.atributos_dict(),
            "pendente_sku": bool(self.pendente_sku), "status": self.status or "Ativo",
            "ativo": bool(self.ativo), "n_equip": len(vinc),
        }
        if com_equip:
            d["equipamentos"] = [v.to_dict_equip() for v in vinc]
        return d


class ConsumivelEquipamento(db.Model):
    __tablename__ = "consumivel_equipamento"
    __table_args__ = (db.UniqueConstraint("consumivel_id", "equipamento_id", name="uq_cons_equip"),)

    id             = db.Column(db.Integer, primary_key=True)
    consumivel_id  = db.Column(db.Integer, db.ForeignKey("consumiveis.id"), nullable=False, index=True)
    equipamento_id = db.Column(db.Integer, db.ForeignKey("equipamentos.id"), nullable=False, index=True)
    fornecimento   = db.Column(db.String(30), default="nao_informado")
    obrigatorio    = db.Column(db.Boolean, default=False)
    observacao     = db.Column(db.String(300), default="")
    ativo          = db.Column(db.Boolean, default=True, nullable=False, index=True)
    criado_em      = db.Column(db.DateTime, default=datetime.now)

    consumivel  = db.relationship("Consumivel", backref=db.backref("vinculos", lazy="selectin"))
    equipamento = db.relationship("Equipamento", lazy="joined")

    def to_dict_equip(self):
        e = self.equipamento
        return {"vinculo_id": self.id, "equipamento_id": self.equipamento_id,
                "equipamento_nome": (e.nome if e else ""), "equipamento_sku": (e.sku if e else ""),
                "fornecimento": self.fornecimento or "nao_informado",
                "obrigatorio": bool(self.obrigatorio), "observacao": self.observacao or ""}

    def to_dict_cons(self):
        c = self.consumivel
        return {"vinculo_id": self.id, "consumivel_id": self.consumivel_id,
                "nome": (c.nome if c else ""), "sku": (c.sku if c else ""),
                "tipo": (c.tipo_rel.nome if c and c.tipo_rel else ""),
                "pendente_sku": bool(c.pendente_sku) if c else False,
                "fornecimento": self.fornecimento or "nao_informado",
                "obrigatorio": bool(self.obrigatorio), "observacao": self.observacao or ""}


# ── RESPONSAVEL (removido) ────────────────────────────────────────────────────
# O modelo `Responsavel` (N:N documento↔usuário com papéis elaborador/revisor_1/
# revisor_2/aprovador) foi removido: nasceu para um fluxo de aprovação que nunca
# existiu — zero linhas, nenhuma rota ativa (o CRUD ficou no servidor_v4, hoje
# só no histórico do git) e nenhuma UI. Quem responde pelo
# documento é `Documento.responsavel`, agora alimentado por um seletor dos
# usuários reais (GET /api/documentos/responsaveis).
# A TABELA `responsaveis` não é derrubada — só deixa de ser mapeada.


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
    # index: /api/audit e /api/export/audit ordenam por timestamp DESC e filtram
    # por período. Sem ele, a tela de auditoria fazia full scan + sort na tabela
    # que mais cresce no banco.
    timestamp     = db.Column(db.DateTime, default=datetime.now, index=True)
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

# Ciclo de vida do projeto. Ortogonal a `ativo` (que é só arquivamento): um
# projeto arquivado pode ter terminado bem (concluido) ou morrido no meio
# (cancelado) — sem esta coluna as duas coisas eram indistinguíveis.
STATUS_PROJETO = ["planejado", "execucao", "suspenso", "concluido", "cancelado"]
STATUS_PROJETO_ABERTO = ("planejado", "execucao", "suspenso")


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


#: Chaves monetárias removidas de um projeto serializado quando o perfil não
#: pode ver dinheiro. Manter em um só lugar evita vazar um campo novo por
#: esquecimento — quem adicionar métrica em R$ acrescenta a chave aqui.
CAMPOS_FINANCEIROS_PROJETO = ("orcamento",)
#: `sv`/`cv` são variações em R$ (EV−PV e EV−AC), não percentuais — entram aqui.
CAMPOS_FINANCEIROS_PMO = ("bac", "pv", "ev", "ac", "sv", "cv", "cpi", "eac",
                          "status_custo")


def _despir_financeiro(d):
    """Remove in-place os valores em R$ de um projeto já serializado."""
    for k in CAMPOS_FINANCEIROS_PROJETO:
        d.pop(k, None)
    pmo = d.get("pmo")
    if isinstance(pmo, dict):
        for k in CAMPOS_FINANCEIROS_PMO:
            pmo.pop(k, None)
    for linha in (d.get("serie_mensal") or []):
        linha.pop("custo_mes", None)
        linha.pop("custo_acumulado", None)
    for b in (d.get("baselines") or []):
        b.pop("orcamento", None)
    for s in (d.get("tendencia") or []):
        for k in ("ac", "bac", "cpi"):
            s.pop(k, None)
    return d


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


# Responsáveis de um entregável — N:N com users. O campo texto `responsaveis`
# continua existindo como legado/rótulo livre, mas quem manda nas métricas de
# carga é esta tabela (texto livre gerava "Melk" e "Guilherme/Melk" como pessoas
# diferentes).
entregavel_responsaveis = db.Table(
    "entregavel_responsaveis",
    db.Column("entregavel_id", db.Integer, db.ForeignKey("entregaveis.id", ondelete="CASCADE"),
              primary_key=True),
    db.Column("user_id", db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
              primary_key=True),
)


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
    ano         = db.Column(db.Integer, default=lambda: datetime.now().year, index=True)
    status      = db.Column(db.String(20), default="execucao", nullable=False, index=True)
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
    snapshots = db.relationship("ProjetoSnapshot", back_populates="projeto",
                                cascade="all, delete-orphan",
                                order_by="ProjetoSnapshot.data")
    baselines = db.relationship("ProjetoBaseline", back_populates="projeto",
                                cascade="all, delete-orphan",
                                order_by="ProjetoBaseline.versao")

    @property
    def avanco(self):
        """Avanço 0-100: média dos entregáveis aplicáveis (status != na),
        ponderada pelo `peso` de cada um — 'Homologação ANVISA' não vale o mesmo
        que 'Folder de divulgação'."""
        soma = base = 0.0
        for e in self.entregaveis:
            if e.status == "na":
                continue
            peso = e.peso if e.peso and e.peso > 0 else 1.0
            base += peso
            if e.status == "concluido":
                soma += peso * 100
            elif e.status == "em_progresso":
                soma += peso * (e.percentual or 0)
        return round(soma / base) if base else 0

    @property
    def pendentes(self):
        return sum(1 for e in self.entregaveis if e.status == "pendente")

    @property
    def atrasados(self):
        """Entregáveis aplicáveis cujo término previsto já passou sem conclusão."""
        hoje = datetime.now().date()
        n = 0
        for e in self.entregaveis:
            if e.status in ("na", "concluido"):
                continue
            fim = _parse_iso(e.data_fim_prev)
            if fim and fim < hoje:
                n += 1
        return n

    # ── PMO / EVM ────────────────────────────────────────────────────────────
    @property
    def pct_prazo_decorrido(self):
        """% do cronograma já decorrido, medido sobre a LINHA DE BASE.

        Usa o início planejado (e só cai para o real se não houver planejado),
        na mesma precedência de `previsto_em` — senão o PV do SPI e a curva-S
        partiriam de datas diferentes e mostrariam previstos divergentes.
        """
        ini = _parse_iso(self.data_inicio_prev) or _parse_iso(self.data_inicio_real)
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
        """% realizado (ponderado por peso) na data `ref`.

        Fórmula ÚNICA para passado e presente. Antes o passado era contagem de
        tarefas concluídas e o ponto de hoje era o avanço vivo (que soma
        parciais) — duas escalas diferentes no mesmo gráfico, o que produzia um
        degrau artificial no último ponto da curva-S.

        Cada entregável contribui com `peso × pct_em(ref)`; `pct_em` usa o
        histórico de status quando existe e reconstrói pela data de conclusão
        quando não existe (projetos anteriores ao histórico).
        """
        soma = base = 0.0
        for e in self.entregaveis:
            if e.status == "na":
                continue
            peso = e.peso if e.peso and e.peso > 0 else 1.0
            base += peso
            soma += peso * e.pct_em(ref)
        return round(soma / base) if base else 0

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

    def previsao_termino(self):
        """Data provável de término pela velocidade real observada.

        Complementa o SPI: em vez de um índice abstrato, devolve uma data que o
        gestor compara direto com o fim planejado. None enquanto não houver
        histórico suficiente (menos de 14 dias corridos ou avanço 0/100).
        """
        ini = _parse_iso(self.data_inicio_real) or _parse_iso(self.data_inicio_prev)
        if not ini:
            return None
        dias = (datetime.now().date() - ini).days
        av = self.avanco
        if dias < 14 or av <= 0 or av >= 100:
            return None
        return (ini + timedelta(days=round(dias * 100 / av))).isoformat()

    # ── Linha de base e snapshots ────────────────────────────────────────────
    def baseline_atual(self):
        """Última versão da linha de base (maior `versao`, não a última da lista:
        a coleção pode ter itens ainda não ordenados pelo banco)."""
        return max(self.baselines, key=lambda b: b.versao or 0, default=None)

    def registrar_baseline(self, email="", motivo=""):
        """Congela cronograma + orçamento atuais como uma nova versão da linha
        de base. Não commita — quem chama controla a transação."""
        atual = self.baseline_atual()
        nova = ProjetoBaseline(
            versao=(atual.versao + 1) if atual else 1,
            data_inicio_prev=self.data_inicio_prev or "",
            data_fim_prev=self.data_fim_prev or "",
            orcamento=self.orcamento or 0.0,
            motivo=(motivo or "").strip(),
            criado_por=email or "",
        )
        # Entra na COLEÇÃO: duas chamadas na mesma transação precisam enxergar a
        # anterior, senão as duas nascem como versão 1 e violam o unique.
        self.baselines.append(nova)
        return nova

    def registrar_snapshot(self):
        """Grava (ou atualiza) a foto de HOJE. Idempotente no dia — chamar a
        cada mutação é barato e dispensa agendador externo. Não commita."""
        hoje = datetime.now().date().isoformat()
        m = self.pmo_metrics()
        snap = next((s for s in self.snapshots if s.data == hoje), None)
        if snap is None:
            snap = ProjetoSnapshot(data=hoje)
            self.snapshots.append(snap)   # a cascata cuida do INSERT
        snap.avanco = self.avanco
        snap.pct_previsto = m.get("pct_previsto")
        snap.spi = m.get("spi")
        snap.cpi = m.get("cpi")
        snap.ac = m.get("ac")
        snap.bac = m.get("bac")
        return snap

    def to_dict(self, com_entregaveis=False, com_pmo=False, com_financeiro=True):
        """Serializa o projeto.

        `com_financeiro=False` remove orçamento, custos e derivados (para
        perfis sem direito a ver dinheiro — ver entregaveis.pode_ver_financeiro).
        """
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
            "status":     self.status or "execucao",
            "ativo":      bool(self.ativo),
            "avanco":     self.avanco,
            "pendentes":  self.pendentes,
            "atrasados":  self.atrasados,
            "total_entregaveis": sum(1 for e in self.entregaveis if e.status != "na"),
            "data_inicio_prev": self.data_inicio_prev or "",
            "data_inicio_real": self.data_inicio_real or "",
            "data_fim_prev":    self.data_fim_prev or "",
            "data_fim_real":    self.data_fim_real or "",
            "orcamento":        self.orcamento or 0.0,
            "previsao_termino": self.previsao_termino(),
            "pmo":              self.pmo_metrics(),
        }
        if com_entregaveis:
            d["entregaveis"] = [e.to_dict() for e in self.entregaveis]
        if com_pmo:
            d["serie_mensal"] = self.serie_mensal()
            d["baselines"]    = [b.to_dict() for b in self.baselines]
            d["tendencia"]    = [s.to_dict() for s in self.snapshots][-90:]
        if not com_financeiro:
            _despir_financeiro(d)
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
    peso           = db.Column(db.Float, default=1.0)       # esforço relativo (EVM)
    responsaveis   = db.Column(db.String(200), default="")  # legado / rótulo livre
    data_inicio_prev = db.Column(db.String(40), default="") # ISO — planejado
    data_fim_prev    = db.Column(db.String(40), default="") # ISO — planejado
    data_inicio    = db.Column(db.String(40), default="")   # ISO — quando a tarefa começou
    data_conclusao = db.Column(db.String(40), default="")   # ISO — quando foi concluída
    atualizado_por = db.Column(db.String(120), default="")
    atualizado_em  = db.Column(db.DateTime, default=datetime.now,
                               onupdate=datetime.now)

    projeto = db.relationship("Projeto", back_populates="entregaveis")
    responsaveis_users = db.relationship("User", secondary=entregavel_responsaveis,
                                         backref=db.backref("entregaveis_atribuidos",
                                                            lazy="dynamic"))
    historico = db.relationship("EntregavelHistorico", back_populates="entregavel",
                                cascade="all, delete-orphan",
                                order_by="EntregavelHistorico.em")

    @property
    def atrasado(self):
        """Passou do término previsto sem estar concluído."""
        if self.status in ("na", "concluido"):
            return False
        fim = _parse_iso(self.data_fim_prev)
        return bool(fim and fim < datetime.now().date())

    def pct_em(self, ref):
        """% concluído DESTE entregável na data `ref` (0-100).

        Presente/futuro: estado atual. Passado: último registro do histórico
        até `ref`; sem histórico (ou sem registro anterior a `ref`), reconstrói
        pela data de conclusão, como faziam os projetos antigos.
        """
        if ref >= datetime.now().date():
            if self.status == "concluido":
                return 100
            return (self.percentual or 0) if self.status == "em_progresso" else 0

        anterior = None
        for h in self.historico:                      # já vem ordenado por `em`
            if h.em and h.em.date() <= ref:
                anterior = h
            else:
                break
        if anterior is not None:
            if anterior.status_novo == "concluido":
                return 100
            return (anterior.percentual or 0) if anterior.status_novo == "em_progresso" else 0

        # Sem histórico aplicável: cai para a data de conclusão. Exige o status
        # atual 'concluido' para não contar tarefa reaberta como pronta.
        dc = _parse_iso(self.data_conclusao)
        return 100 if (dc and dc <= ref and self.status == "concluido") else 0

    def to_dict(self):
        return {
            "id":             self.id,
            "projeto_id":     self.projeto_id,
            "tipo":           (self.tipo or "").strip(),
            "categoria":      self.categoria or "",
            "status":         self.status or "pendente",
            "percentual":     self.percentual,
            "peso":           self.peso if self.peso is not None else 1.0,
            "responsaveis":   self.responsaveis or "",
            "responsaveis_ids":   [u.id for u in self.responsaveis_users],
            "responsaveis_nomes": [u.nome for u in self.responsaveis_users],
            "data_inicio_prev": self.data_inicio_prev or "",
            "data_fim_prev":    self.data_fim_prev or "",
            "data_inicio":    self.data_inicio or "",
            "data_conclusao": self.data_conclusao or "",
            "atrasado":       self.atrasado,
            "atualizado_por": self.atualizado_por or "",
            "atualizado_em":  self.atualizado_em.strftime("%d/%m/%Y %H:%M") if self.atualizado_em else "",
        }


class EntregavelHistorico(db.Model):
    """Trilha de mudanças de status/percentual de um entregável.

    É o que permite responder "como estava este projeto em março?" depois que
    alguém reabre uma tarefa — antes, reabrir apagava `data_conclusao` e a
    curva-S histórica mudava retroativamente.
    """
    __tablename__ = "entregavel_historico"

    id            = db.Column(db.Integer, primary_key=True)
    entregavel_id = db.Column(db.Integer, db.ForeignKey("entregaveis.id"),
                              nullable=False, index=True)
    status_antigo = db.Column(db.String(20), default="")
    status_novo   = db.Column(db.String(20), default="")
    percentual    = db.Column(db.Integer, nullable=True)
    em            = db.Column(db.DateTime, default=datetime.now, index=True)
    por           = db.Column(db.String(120), default="")

    entregavel = db.relationship("Entregavel", back_populates="historico")

    def to_dict(self):
        return {
            "id":            self.id,
            "status_antigo": self.status_antigo or "",
            "status_novo":   self.status_novo or "",
            "percentual":    self.percentual,
            "em":            self.em.strftime("%d/%m/%Y %H:%M") if self.em else "",
            "por":           self.por or "",
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
    peso          = db.Column(db.Float, default=1.0)   # esforço relativo padrão
    responsavel_padrao = db.Column(db.String(200), default="")
    ordem         = db.Column(db.Integer, default=0)

    def to_dict(self):
        return {
            "id":                 self.id,
            "tipo_projeto":       self.tipo_projeto,
            "categoria":          self.categoria or "Produto",
            "tipo":               (self.tipo or "").strip(),
            "peso":               self.peso if self.peso is not None else 1.0,
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


class ProjetoSnapshot(db.Model):
    """Foto diária do projeto: avanço, previsto e índices no dia em que foram medidos.

    Sem isto, todo indicador é recalculado com as datas de HOJE — mexer no
    cronograma reescrevia o passado e não existia série temporal de SPI/CPI.
    Um registro por (projeto, data).
    """
    __tablename__ = "projeto_snapshot"
    __table_args__ = (
        db.UniqueConstraint("projeto_id", "data", name="uq_snapshot_projeto_data"),
    )

    id            = db.Column(db.Integer, primary_key=True)
    projeto_id    = db.Column(db.Integer, db.ForeignKey("projetos.id"),
                              nullable=False, index=True)
    data          = db.Column(db.String(10), nullable=False, index=True)   # 'YYYY-MM-DD'
    avanco        = db.Column(db.Integer, default=0)
    pct_previsto  = db.Column(db.Integer, nullable=True)
    spi           = db.Column(db.Float, nullable=True)
    cpi           = db.Column(db.Float, nullable=True)
    ac            = db.Column(db.Float, nullable=True)
    bac           = db.Column(db.Float, nullable=True)
    criado_em     = db.Column(db.DateTime, default=datetime.now)

    projeto = db.relationship("Projeto", back_populates="snapshots")

    def to_dict(self):
        return {
            "data":         self.data,
            "avanco":       self.avanco or 0,
            "pct_previsto": self.pct_previsto,
            "spi":          self.spi,
            "cpi":          self.cpi,
            "ac":           self.ac,
            "bac":          self.bac,
        }


class ProjetoBaseline(db.Model):
    """Linha de base versionada (cronograma + orçamento aprovados).

    Replanejar deixa de ser indistinguível de maquiar indicador: cada mudança
    de datas/orçamento cria uma versão nova, com autor e motivo, e a anterior
    fica preservada para comparação.
    """
    __tablename__ = "projeto_baseline"
    __table_args__ = (
        db.UniqueConstraint("projeto_id", "versao", name="uq_baseline_projeto_versao"),
    )

    id               = db.Column(db.Integer, primary_key=True)
    projeto_id       = db.Column(db.Integer, db.ForeignKey("projetos.id"),
                                 nullable=False, index=True)
    versao           = db.Column(db.Integer, nullable=False, default=1)
    data_inicio_prev = db.Column(db.String(40), default="")
    data_fim_prev    = db.Column(db.String(40), default="")
    orcamento        = db.Column(db.Float, default=0.0)
    motivo           = db.Column(db.String(300), default="")
    criado_por       = db.Column(db.String(120), default="")
    criado_em        = db.Column(db.DateTime, default=datetime.now)

    projeto = db.relationship("Projeto", back_populates="baselines")

    def to_dict(self):
        return {
            "id":               self.id,
            "versao":           self.versao,
            "data_inicio_prev": self.data_inicio_prev or "",
            "data_fim_prev":    self.data_fim_prev or "",
            "orcamento":        self.orcamento or 0.0,
            "motivo":           self.motivo or "",
            "criado_por":       self.criado_por or "",
            "criado_em":        self.criado_em.strftime("%d/%m/%Y %H:%M") if self.criado_em else "",
        }


# ── MISSÕES (kanban nativo tipo Planner) ─────────────────────────────────────
# Hierarquia flat Missão → Coluna → Cartão (≈ plannerPlan → bucket → task).
# Ordenação por `ordem` int reindexado em transação; `versao` no cartão é o lock
# otimista (equivalente barato do @odata.etag do Graph — conflito devolve 409).
# Referência: planner-missoes-pesquisa/report.md.

PRIORIDADES_CARTAO = ["baixa", "media", "alta", "urgente"]
REF_TIPOS_CARTAO   = ["equipamento", "projeto", "documento"]
CATEGORIAS_COLUNA  = ["todo", "doing", "done"]
# Obrigação periódica (calibração, requalificação, revisão anual): ao concluir,
# o cartão se reagenda sozinho. Valor = passo aplicado ao prazo.
RECORRENCIAS_CARTAO = {
    "":            None,
    "semanal":     ("dias", 7),
    "quinzenal":   ("dias", 14),
    "mensal":      ("meses", 1),
    "bimestral":   ("meses", 2),
    "trimestral":  ("meses", 3),
    "semestral":   ("meses", 6),
    "anual":       ("meses", 12),
}
# Eventos da trilha do cartão (ver MissaoCartaoHistorico)
EVENTOS_CARTAO = ["criado", "movido", "concluido", "reaberto", "campo"]

# N:N cartão ↔ usuário. O CSV `responsaveis` continua sendo o texto exibido, mas
# quem responde "é meu?" é esta tabela — o LIKE por nome casava "Ana" com
# "Mariana" e quebrava ao renomear o usuário. Mesmo desenho do
# entregavel_responsaveis (migration 007).
missao_cartao_responsaveis = db.Table(
    "missao_cartao_responsaveis",
    db.Column("cartao_id", db.Integer,
              db.ForeignKey("missao_cartoes.id", ondelete="CASCADE"),
              primary_key=True),
    db.Column("user_id", db.Integer,
              db.ForeignKey("users.id", ondelete="CASCADE"),
              primary_key=True),
)


class Missao(db.Model):
    __tablename__ = "missoes"

    id         = db.Column(db.Integer, primary_key=True)
    nome       = db.Column(db.String(160), nullable=False)
    descricao  = db.Column(db.Text, default="")
    accent     = db.Column(db.String(9), default="")        # cor hex opcional
    arquivado  = db.Column(db.Boolean, default=False, index=True)
    ordem      = db.Column(db.Integer, default=0)
    criado_por = db.Column(db.String(120), default="")
    criado_em  = db.Column(db.DateTime, default=datetime.now)

    colunas = db.relationship("MissaoColuna", back_populates="missao",
                              cascade="all, delete-orphan",
                              order_by="MissaoColuna.ordem")
    cartoes = db.relationship("MissaoCartao", back_populates="missao",
                              cascade="all, delete-orphan")
    snapshots = db.relationship("MissaoSnapshot", back_populates="missao",
                                cascade="all, delete-orphan",
                                order_by="MissaoSnapshot.data")

    def to_dict(self, com_colunas=False, n_cartoes=None, n_abertos=None,
                refs_map=None, extras_map=None):
        d = {
            "id":         self.id,
            "nome":       (self.nome or "").strip(),
            "descricao":  self.descricao or "",
            "accent":     self.accent or "",
            "arquivado":  bool(self.arquivado),
            "ordem":      self.ordem or 0,
            "criado_por": self.criado_por or "",
            "criado_em":  self.criado_em.strftime("%d/%m/%Y") if self.criado_em else "",
            # n_cartoes pré-computado evita carregar os cartões só para contar (N+1 na lista)
            "n_cartoes":  len(self.cartoes) if n_cartoes is None else n_cartoes,
        }
        # O badge da sidebar mostra o que ainda dá trabalho: uma missão 38/40
        # pronta exibia "40" e parecia intocada.
        d["n_abertos"] = (len([c for c in self.cartoes if not c.concluido])
                          if n_abertos is None else n_abertos)
        if com_colunas:
            d["colunas"] = [c.to_dict(com_cartoes=True, refs_map=refs_map,
                                      extras_map=extras_map)
                            for c in self.colunas]
        return d


class MissaoColuna(db.Model):
    __tablename__ = "missao_colunas"

    id        = db.Column(db.Integer, primary_key=True)
    missao_id = db.Column(db.Integer, db.ForeignKey("missoes.id"),
                          nullable=False, index=True)
    nome      = db.Column(db.String(80), nullable=False)
    cor       = db.Column(db.String(9), default="")
    ordem     = db.Column(db.Integer, default=0)
    # Tag opcional p/ rollup/relatório sem virar enum global (à la Notion/Linear):
    # a coluna É o estado; a categoria só classifica (todo|doing|done).
    categoria = db.Column(db.String(10), default="")
    # Limite de trabalho em progresso. 0 = sem limite. Sinal SOFT: o board pinta
    # a coluna e os alertas avisam, mas nada bloqueia o arrasto — kanban trata
    # estouro como conversa, não como erro de sistema.
    limite_wip = db.Column(db.Integer, default=0)

    missao  = db.relationship("Missao", back_populates="colunas")
    cartoes = db.relationship("MissaoCartao", back_populates="coluna",
                              cascade="all, delete-orphan",
                              order_by="MissaoCartao.ordem")

    def to_dict(self, com_cartoes=False, refs_map=None, extras_map=None):
        d = {
            "id":         self.id,
            "missao_id":  self.missao_id,
            "nome":       (self.nome or "").strip(),
            "cor":        self.cor or "",
            "ordem":      self.ordem or 0,
            "categoria":  self.categoria or "",
            "limite_wip": self.limite_wip or 0,
        }
        if com_cartoes:
            # refs_map (ver _mapa_refs em missoes.py) evita 1 query por cartão
            vazio = {"label": "", "status": "", "status_global": ""}
            d["cartoes"] = [
                c.to_dict(ref_info=(refs_map.get((c.ref_tipo, c.ref_id), vazio)
                                    if refs_map is not None else None),
                          extras=(extras_map.get(c.id) if extras_map is not None else None))
                for c in self.cartoes]
        return d


class MissaoCartao(db.Model):
    __tablename__ = "missao_cartoes"

    id             = db.Column(db.Integer, primary_key=True)
    missao_id      = db.Column(db.Integer, db.ForeignKey("missoes.id"),
                               nullable=False, index=True)
    coluna_id      = db.Column(db.Integer, db.ForeignKey("missao_colunas.id"),
                               nullable=False, index=True)
    titulo         = db.Column(db.String(200), nullable=False)
    descricao      = db.Column(db.Text, default="")          # pesado: fora da query do board
    responsaveis   = db.Column(db.String(200), default="")   # CSV (convenção do Entregavel)
    prazo          = db.Column(db.String(40), default="")    # ISO 'YYYY-MM-DD'
    prioridade     = db.Column(db.String(10), default="media")
    etiquetas      = db.Column(db.String(300), default="")   # CSV
    concluido      = db.Column(db.Boolean, default=False)
    ordem          = db.Column(db.Integer, default=0)
    versao         = db.Column(db.Integer, default=0)        # lock otimista (move/patch)
    # Vínculo opcional, tipado, sem FK rígida (módulo solto; validação ao gravar).
    ref_tipo       = db.Column(db.String(20), default="")    # equipamento|projeto|documento|""
    ref_id         = db.Column(db.Integer, nullable=True)
    criado_por     = db.Column(db.String(120), default="")
    atualizado_por = db.Column(db.String(120), default="")
    atualizado_em  = db.Column(db.DateTime, default=datetime.now,
                               onupdate=datetime.now)
    # ── marcos temporais ─────────────────────────────────────────────────────
    # Sem eles nada de fluxo era calculável: `atualizado_em` é sobrescrito a cada
    # save, então nem a idade do cartão dava para derivar.
    criado_em        = db.Column(db.DateTime, default=datetime.now, index=True)
    concluido_em     = db.Column(db.DateTime, nullable=True, index=True)
    concluido_por    = db.Column(db.String(120), default="")
    # Momento em que o cartão entrou na coluna atual — aging sem varrer o
    # histórico (o histórico continua sendo a fonte da série completa).
    entrou_coluna_em = db.Column(db.DateTime, default=datetime.now)
    data_inicio      = db.Column(db.String(40), default="")   # ISO; com `prazo` dá duração planejada
    peso             = db.Column(db.Float, default=1.0)       # esforço relativo (avanço ponderado)
    recorrencia      = db.Column(db.String(20), default="")   # ver RECORRENCIAS_CARTAO

    __table_args__ = (
        db.Index("ix_missao_cartoes_coluna_ordem", "coluna_id", "ordem"),
        # cartoes-vinculados é chamado a cada abertura de ficha no dashboard e
        # fazia full scan por (ref_tipo, ref_id).
        db.Index("ix_missao_cartoes_ref", "ref_tipo", "ref_id"),
    )

    missao = db.relationship("Missao", back_populates="cartoes")
    coluna = db.relationship("MissaoColuna", back_populates="cartoes")
    responsaveis_users = db.relationship("User", secondary=missao_cartao_responsaveis,
                                         backref=db.backref("cartoes_atribuidos",
                                                            lazy="dynamic"))
    historico = db.relationship("MissaoCartaoHistorico", back_populates="cartao",
                                cascade="all, delete-orphan",
                                order_by="MissaoCartaoHistorico.em")
    itens = db.relationship("MissaoCartaoItem", back_populates="cartao",
                            cascade="all, delete-orphan",
                            order_by="MissaoCartaoItem.ordem")
    comentarios = db.relationship("MissaoCartaoComentario", back_populates="cartao",
                                  cascade="all, delete-orphan",
                                  order_by="MissaoCartaoComentario.em")

    @property
    def atrasado(self):
        """Passou do prazo sem estar concluído."""
        if self.concluido or not self.prazo:
            return False
        d = _parse_iso(self.prazo)
        return bool(d and d < datetime.now().date())

    @property
    def dias_parado(self):
        """Dias na coluna atual — o aging que denuncia cartão esquecido."""
        base = self.entrou_coluna_em or self.criado_em
        return (datetime.now() - base).days if base else 0

    @property
    def dias_ciclo(self):
        """Da criação à conclusão, em dias (None enquanto aberto)."""
        if not self.concluido_em or not self.criado_em:
            return None
        return max((self.concluido_em - self.criado_em).days, 0)

    def _ref_meta(self):
        """Metadados leves do vínculo (chip): label + status vivo (documento).
        1 query por cartão — em listagens grandes, passe ref_info pré-computado
        ao to_dict (ver _mapa_refs em missoes.py) para evitar N+1.

        `ativo=False` quando a entidade existe mas foi desativada: antes o chip
        simplesmente sumia e o cartão perdia o contexto sem avisar ninguém."""
        meta = {"label": "", "status": "", "status_global": "", "ativo": True}
        if not self.ref_tipo or not self.ref_id:
            return meta
        try:
            if self.ref_tipo == "equipamento":
                e = Equipamento.query.get(self.ref_id)
                if e:
                    meta.update(label=e.nome, ativo=bool(e.ativo))
            elif self.ref_tipo == "projeto":
                p = Projeto.query.get(self.ref_id)
                if p:
                    meta.update(label=p.nome, ativo=bool(p.ativo))
            elif self.ref_tipo == "documento":
                doc = Documento.query.get(self.ref_id)
                if doc:
                    meta.update(label=doc.documento, status=doc.status or "",
                                status_global=doc.status_global, ativo=bool(doc.ativo))
        except Exception:
            pass
        return meta

    def ref_label(self):
        """Rótulo leve do vínculo (compat; prefira _ref_meta)."""
        return self._ref_meta()["label"]

    def to_dict(self, com_descricao=False, ref_info=None, extras=None):
        ref = ref_info if ref_info is not None else self._ref_meta()
        d = {
            "id":             self.id,
            "missao_id":      self.missao_id,
            "coluna_id":      self.coluna_id,
            "titulo":         (self.titulo or "").strip(),
            "responsaveis":   self.responsaveis or "",
            "prazo":          self.prazo or "",
            "data_inicio":    self.data_inicio or "",
            "prioridade":     self.prioridade or "media",
            "etiquetas":      self.etiquetas or "",
            "concluido":      bool(self.concluido),
            "ordem":          self.ordem or 0,
            "versao":         self.versao or 0,
            "peso":           self.peso if self.peso is not None else 1.0,
            "recorrencia":    self.recorrencia or "",
            "ref_tipo":       self.ref_tipo or "",
            "ref_id":         self.ref_id,
            "ref_label":      ref.get("label", ""),
            "ref_status":     ref.get("status", ""),
            "ref_status_global": ref.get("status_global", ""),
            "ref_ativo":      ref.get("ativo", True),
            "tem_descricao":  bool((self.descricao or "").strip()),
            "atrasado":       self.atrasado,
            "dias_parado":    self.dias_parado,
            "criado_por":     self.criado_por or "",
            "criado_em":      self.criado_em.strftime("%d/%m/%Y %H:%M") if self.criado_em else "",
            "criado_em_iso":  self.criado_em.isoformat() if self.criado_em else "",
            "concluido_em":   self.concluido_em.strftime("%d/%m/%Y %H:%M") if self.concluido_em else "",
            "concluido_por":  self.concluido_por or "",
            "atualizado_por": self.atualizado_por or "",
            "atualizado_em":  self.atualizado_em.strftime("%d/%m/%Y %H:%M") if self.atualizado_em else "",
        }
        # extras pré-computado (ver _mapa_extras em missoes.py): contar checklist
        # e comentários por cartão no board seria 2 queries por cartão.
        if extras is not None:
            d["n_itens"]        = extras.get("itens", 0)
            d["n_itens_feitos"] = extras.get("itens_feitos", 0)
            d["n_comentarios"]  = extras.get("comentarios", 0)
        if com_descricao:
            d["descricao"] = self.descricao or ""
            d["itens"] = [i.to_dict() for i in self.itens]
            d["comentarios"] = [c.to_dict() for c in self.comentarios]
            d["n_itens"] = len(self.itens)
            d["n_itens_feitos"] = len([i for i in self.itens if i.feito])
            d["n_comentarios"] = len(self.comentarios)
        return d


class MissaoCartaoHistorico(db.Model):
    """Trilha temporal do cartão — o que o AuditLog não consegue ser.

    O `publish_event` já grava cada mutação em audit_logs, mas em texto genérico
    por usuário/entidade: não responde quanto tempo o cartão ficou em "Fazendo",
    quantos foram concluídos na semana passada nem onde está o gargalo do fluxo.
    Mesmo papel do DocumentoHistorico e do EntregavelHistorico nos outros
    módulos — Missões era o único que nunca recebeu esse passo.

    `evento`: criado | movido | concluido | reaberto | campo (ver EVENTOS_CARTAO).
    `origem`: 'manual' | 'doc-sync' | 'recorrencia' — separa o que a pessoa fez
    do que o sistema fez por ela (antes só existia no payload do socket, que
    não fica gravado em lugar nenhum consultável).
    """
    __tablename__ = "missao_cartao_historico"

    id               = db.Column(db.Integer, primary_key=True)
    cartao_id        = db.Column(db.Integer,
                                 db.ForeignKey("missao_cartoes.id", ondelete="CASCADE"),
                                 nullable=False, index=True)
    missao_id        = db.Column(db.Integer, db.ForeignKey("missoes.id"),
                                 nullable=False, index=True)
    evento           = db.Column(db.String(20), default="campo", index=True)
    coluna_origem_id  = db.Column(db.Integer, nullable=True)
    coluna_destino_id = db.Column(db.Integer, nullable=True)
    campo            = db.Column(db.String(40), default="")
    valor_antigo     = db.Column(db.Text, default="")
    valor_novo       = db.Column(db.Text, default="")
    origem           = db.Column(db.String(20), default="manual")
    em               = db.Column(db.DateTime, default=datetime.now, index=True)
    por              = db.Column(db.String(120), default="")

    cartao = db.relationship("MissaoCartao", back_populates="historico")

    def to_dict(self, nomes_coluna=None):
        nomes = nomes_coluna or {}
        return {
            "id":           self.id,
            "cartao_id":    self.cartao_id,
            "missao_id":    self.missao_id,
            "evento":       self.evento or "campo",
            "coluna_origem":  nomes.get(self.coluna_origem_id, ""),
            "coluna_destino": nomes.get(self.coluna_destino_id, ""),
            "campo":        self.campo or "",
            "valor_antigo": self.valor_antigo or "",
            "valor_novo":   self.valor_novo or "",
            "origem":       self.origem or "manual",
            "em":           self.em.strftime("%d/%m/%Y %H:%M") if self.em else "",
            "em_iso":       self.em.isoformat() if self.em else "",
            "por":          self.por or "",
        }


class MissaoSnapshot(db.Model):
    """Foto diária dos indicadores da missão.

    Recalcular com as datas de hoje reescreve o passado — mesma razão do
    ProjetoSnapshot e do EquipamentoSnapshot. É o que permite burndown e
    tendência de WIP sem depender de reprocessar o histórico inteiro."""
    __tablename__ = "missao_snapshot"

    id             = db.Column(db.Integer, primary_key=True)
    missao_id      = db.Column(db.Integer, db.ForeignKey("missoes.id"),
                               nullable=False, index=True)
    data           = db.Column(db.String(10), nullable=False, index=True)  # ISO
    total          = db.Column(db.Integer, default=0)
    abertos        = db.Column(db.Integer, default=0)
    concluidos     = db.Column(db.Integer, default=0)
    atrasados      = db.Column(db.Integer, default=0)
    wip            = db.Column(db.Integer, default=0)   # cartões em coluna 'doing'
    sem_responsavel = db.Column(db.Integer, default=0)
    peso_total     = db.Column(db.Float, default=0.0)
    peso_concluido = db.Column(db.Float, default=0.0)
    criado_em      = db.Column(db.DateTime, default=datetime.now)

    __table_args__ = (db.UniqueConstraint("missao_id", "data",
                                          name="uq_missao_snapshot_dia"),)

    missao = db.relationship("Missao", back_populates="snapshots")

    def to_dict(self):
        return {
            "data":            self.data,
            "total":           self.total or 0,
            "abertos":         self.abertos or 0,
            "concluidos":      self.concluidos or 0,
            "atrasados":       self.atrasados or 0,
            "wip":             self.wip or 0,
            "sem_responsavel": self.sem_responsavel or 0,
            "peso_total":      round(self.peso_total or 0.0, 2),
            "peso_concluido":  round(self.peso_concluido or 0.0, 2),
        }


class MissaoCartaoItem(db.Model):
    """Item de checklist do cartão (paridade com o checklistItem do Planner)."""
    __tablename__ = "missao_cartao_itens"

    id        = db.Column(db.Integer, primary_key=True)
    cartao_id = db.Column(db.Integer,
                          db.ForeignKey("missao_cartoes.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    texto     = db.Column(db.String(300), nullable=False)
    feito     = db.Column(db.Boolean, default=False)
    ordem     = db.Column(db.Integer, default=0)
    criado_em = db.Column(db.DateTime, default=datetime.now)

    cartao = db.relationship("MissaoCartao", back_populates="itens")

    def to_dict(self):
        return {"id": self.id, "texto": (self.texto or "").strip(),
                "feito": bool(self.feito), "ordem": self.ordem or 0}


class MissaoCartaoComentario(db.Model):
    """Comentário do cartão — onde nasce o registro do 'por que isso travou',
    hoje perdido em conversa fora do sistema."""
    __tablename__ = "missao_cartao_comentarios"

    id        = db.Column(db.Integer, primary_key=True)
    cartao_id = db.Column(db.Integer,
                          db.ForeignKey("missao_cartoes.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    texto     = db.Column(db.Text, nullable=False)
    por       = db.Column(db.String(120), default="")
    em        = db.Column(db.DateTime, default=datetime.now, index=True)

    cartao = db.relationship("MissaoCartao", back_populates="comentarios")

    def to_dict(self):
        return {"id": self.id, "texto": self.texto or "", "por": self.por or "",
                "em": self.em.strftime("%d/%m/%Y %H:%M") if self.em else "",
                "em_iso": self.em.isoformat() if self.em else ""}


class MissaoModelo(db.Model):
    """Template de missão: colunas (com WIP e categoria) + cartões iniciais.

    Toda missão nascia com as mesmas 3 colunas vazias, mas os processos daqui
    se repetem (validação de equipamento novo, submissão ANVISA). Mesma função
    do modelos_entregavel em Projetos; a estrutura vai em JSON porque o template
    é lido inteiro de uma vez e nunca consultado por parte."""
    __tablename__ = "missao_modelos"

    id         = db.Column(db.Integer, primary_key=True)
    nome       = db.Column(db.String(160), nullable=False)
    descricao  = db.Column(db.Text, default="")
    accent     = db.Column(db.String(9), default="")
    estrutura  = db.Column(db.Text, default="[]")   # JSON: [{nome, categoria, limite_wip, cartoes:[…]}]
    criado_por = db.Column(db.String(120), default="")
    criado_em  = db.Column(db.DateTime, default=datetime.now)

    def colunas(self):
        try:
            dados = json.loads(self.estrutura or "[]")
            return dados if isinstance(dados, list) else []
        except (ValueError, TypeError):
            return []

    def to_dict(self, com_estrutura=False):
        cols = self.colunas()
        d = {
            "id":         self.id,
            "nome":       (self.nome or "").strip(),
            "descricao":  self.descricao or "",
            "accent":     self.accent or "",
            "n_colunas":  len(cols),
            "n_cartoes":  sum(len(c.get("cartoes") or []) for c in cols),
            "criado_por": self.criado_por or "",
            "criado_em":  self.criado_em.strftime("%d/%m/%Y") if self.criado_em else "",
        }
        if com_estrutura:
            d["colunas"] = cols
        return d
