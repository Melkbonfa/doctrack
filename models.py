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

    @property
    def _custo_atual(self):
        """Custo acumulado mais recente (AC), do último lançamento mensal de custo."""
        return self.mensais[-1].custo_acumulado if self.mensais else None

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
        custos = {m.competencia: m.custo_acumulado for m in self.mensais}
        out = []
        y, mo, count = ini.year, ini.month, 0
        while (y < hoje.year or (y == hoje.year and mo <= hoje.month)) and count < 48:
            comp = f"{y:04d}-{mo:02d}"
            ref = datetime(y, mo, calendar.monthrange(y, mo)[1]).date()
            out.append({
                "competencia":     comp,
                "pct_previsto":    self.previsto_em(comp),
                "pct_realizado":   self.realizado_em(ref),
                "custo_acumulado": custos.get(comp),
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
    custo_acumulado = db.Column(db.Float, default=0.0)          # R$ gasto acumulado (AC)
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
            "custo_acumulado": self.custo_acumulado or 0.0,
            "atualizado_por":  self.atualizado_por or "",
            "atualizado_em":   self.atualizado_em.strftime("%d/%m/%Y %H:%M") if self.atualizado_em else "",
        }
