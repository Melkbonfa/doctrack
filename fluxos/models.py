"""
fluxos/models.py — modelos de fluxo, fluxos em andamento e a trilha de passagens.

Tabelas prefixadas `fluxo_` (mais `fluxos`, a instância), no `db` do mestre.

## Decisões

**Etapas e papéis em JSON.** São poucas linhas, editadas sempre juntas e copiadas
inteiras do modelo para o fluxo na hora em que ele começa. Ninguém consulta
"fluxos cuja etapa 2 é X". Mesmo racional de `projetos.modelo_conhecidos`.

**O fluxo copia as etapas do modelo.** Editar o modelo depois não mexe em quem já
está andando — a mesma regra de "editar o modelo de entregáveis não altera
projetos já criados".

**Vínculo tipado sem FK rígida** (`ref_tipo` + `ref_id`), o desenho de
`MissaoCartao` e `Apontamento`. A integridade fica no código: `routes._alvo()`
valida na criação, e documento/entregável recusam sair de cena com fluxo ativo.

**Um fluxo ativo por item, garantido NO BANCO.** Índice parcial e único em
`(ref_tipo, ref_id) WHERE status = 'andamento'`. Precisa de `sqlite_where` E
`postgresql_where` — a mesma armadilha documentada em tempos/models.py: com um
só, o outro dialeto criaria um UNIQUE puro e o item nunca teria um segundo fluxo,
nem depois de aprovado o primeiro.

**FKs para `users` com SET NULL.** auth.py apaga o User de verdade
(?permanente=true). O fluxo e a trilha sobrevivem a isso; o papel que ficou sem
pessoa aparece como "sem responsável" e a gestão reatribui.

**Passagens e arquivos são imutáveis.** São o registro das rodadas: o PDF que
foi revisado na rodada 2 tem de continuar sendo aquele. Arquivo errado se corrige
na passagem seguinte.
"""
import json
from datetime import datetime

from models import db

REF_TIPOS_FLUXO = ["documento", "entregavel"]
STATUS_FLUXO = ["andamento", "aprovado", "cancelado"]
ACOES_PASSAGEM = ["iniciar", "enviar", "aprovar", "devolver", "reatribuir", "cancelar"]


def _json(texto, padrao):
    try:
        v = json.loads(texto) if texto else padrao
        return v if isinstance(v, type(padrao)) else padrao
    except (TypeError, ValueError):
        return padrao


def _fmt(dt):
    return dt.strftime("%d/%m/%Y %H:%M") if dt else ""


def tem_fluxo_ativo(ref_tipo, ref_id):
    """True se o item tem um fluxo em andamento. É a trava que documentos,
    entregáveis e modelo_sync consultam antes de tirar o item de cena."""
    return (Fluxo.query.filter_by(ref_tipo=ref_tipo, ref_id=ref_id, status="andamento")
            .first() is not None)


MSG_FLUXO_ATIVO = "Há um fluxo de revisão em andamento neste item. Cancele o fluxo antes."


class FluxoModelo(db.Model):
    __tablename__ = "fluxo_modelos"

    id        = db.Column(db.Integer, primary_key=True)
    nome      = db.Column(db.String(80), nullable=False)    # único sem diferenciar maiúsculas (código)
    descricao = db.Column(db.Text, default="")
    papeis    = db.Column(db.Text, nullable=False, default="[]")  # JSON [{chave, nome, padrao_user_id}]
    etapas    = db.Column(db.Text, nullable=False, default="[]")  # JSON [{chave, nome, papel, tipo, devolve_para}]
    # Arquivar em vez de excluir: um modelo com fluxo nunca sai do banco, e o
    # arquivado só deixa de aparecer na hora de iniciar.
    ativo     = db.Column(db.Boolean, nullable=False, default=True, index=True)
    criado_em      = db.Column(db.DateTime, default=datetime.now)
    criado_por     = db.Column(db.String(120), default="")
    atualizado_em  = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    atualizado_por = db.Column(db.String(120), default="")

    def papeis_lista(self):
        return _json(self.papeis, [])

    def etapas_lista(self):
        return _json(self.etapas, [])

    def to_dict(self, n_fluxos=None):
        d = {
            "id":        self.id,
            "nome":      self.nome or "",
            "descricao": self.descricao or "",
            "papeis":    self.papeis_lista(),
            "etapas":    self.etapas_lista(),
            "ativo":     bool(self.ativo),
            "atualizado_em":  _fmt(self.atualizado_em),
            "atualizado_por": self.atualizado_por or "",
        }
        if n_fluxos is not None:
            d["n_fluxos"] = n_fluxos
        return d


class Fluxo(db.Model):
    __tablename__ = "fluxos"

    id = db.Column(db.Integer, primary_key=True)
    ref_tipo = db.Column(db.String(20), nullable=False)    # documento|entregavel
    ref_id   = db.Column(db.Integer, nullable=False)
    modelo_id   = db.Column(db.Integer, db.ForeignKey("fluxo_modelos.id"), nullable=True)
    modelo_nome = db.Column(db.String(80), default="")     # congelado na criação
    # Congelado: "Manual do Usuário PT · Analisador X1". Sobrevive ao documento
    # renomeado e é o que a notificação e a lista "Em andamento" mostram.
    titulo      = db.Column(db.String(300), default="")
    etapas      = db.Column(db.Text, nullable=False, default="[]")   # cópia do modelo
    papeis      = db.Column(db.Text, nullable=False, default="[]")   # cópia do modelo (nomes)
    etapa_atual = db.Column(db.String(40), default="")     # chave; vazio quando encerrado
    status      = db.Column(db.String(12), nullable=False, default="andamento", index=True)
    rodada      = db.Column(db.Integer, nullable=False, default=1)  # soma a cada devolução
    prazo       = db.Column(db.Date, nullable=True)
    iniciado_por_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"),
                                nullable=True)
    iniciado_em     = db.Column(db.DateTime, default=datetime.now)
    entrou_etapa_em = db.Column(db.DateTime, default=datetime.now)   # aging da etapa
    concluido_em    = db.Column(db.DateTime, nullable=True)
    versao          = db.Column(db.Integer, nullable=False, default=1)  # lock otimista

    participantes = db.relationship("FluxoParticipante", back_populates="fluxo",
                                    cascade="all, delete-orphan", lazy="selectin")
    passagens = db.relationship("FluxoPassagem", back_populates="fluxo",
                                cascade="all, delete-orphan",
                                order_by="FluxoPassagem.id")
    iniciado_por = db.relationship("User", foreign_keys=[iniciado_por_id])

    __table_args__ = (
        # Com `status` no fim de propósito: só (ref_tipo, ref_id) teria as mesmas
        # colunas do índice parcial abaixo, e _sync_schema trata índice com as
        # mesmas colunas como equivalente — não o recriaria num banco que o perdeu.
        db.Index("ix_fluxos_ref_status", "ref_tipo", "ref_id", "status"),
        db.Index("uq_fluxo_ativo", "ref_tipo", "ref_id", unique=True,
                 sqlite_where=db.text("status = 'andamento'"),
                 postgresql_where=db.text("status = 'andamento'")),
    )

    def etapas_lista(self):
        return _json(self.etapas, [])

    def papeis_lista(self):
        return _json(self.papeis, [])

    def mapa_participantes(self):
        """{papel: user_id} — o formato que o core espera."""
        return {p.papel: p.user_id for p in self.participantes}


class FluxoParticipante(db.Model):
    __tablename__ = "fluxo_participantes"

    id = db.Column(db.Integer, primary_key=True)
    fluxo_id = db.Column(db.Integer, db.ForeignKey("fluxos.id"), nullable=False, index=True)
    papel    = db.Column(db.String(40), nullable=False)
    user_id  = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"),
                         nullable=True, index=True)

    fluxo   = db.relationship("Fluxo", back_populates="participantes")
    usuario = db.relationship("User", lazy="joined")

    __table_args__ = (db.UniqueConstraint("fluxo_id", "papel", name="uq_fluxo_papel"),)


class FluxoPassagem(db.Model):
    __tablename__ = "fluxo_passagens"

    id = db.Column(db.Integer, primary_key=True)
    fluxo_id   = db.Column(db.Integer, db.ForeignKey("fluxos.id"), nullable=False, index=True)
    acao       = db.Column(db.String(12), nullable=False)   # ver ACOES_PASSAGEM
    de_etapa   = db.Column(db.String(40), default="")
    para_etapa = db.Column(db.String(40), default="")       # vazio = encerrou
    rodada     = db.Column(db.Integer, nullable=False, default=1)
    comentario = db.Column(db.Text, default="")
    por_id     = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"),
                           nullable=True)
    # Preenchido quando a gestão agiu no lugar do responsável da etapa: a trilha
    # mostra "Gestor, em nome de Marcos" em vez de fingir que foi o Marcos.
    em_nome_de_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"),
                              nullable=True)
    em = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)

    fluxo      = db.relationship("Fluxo", back_populates="passagens")
    por        = db.relationship("User", foreign_keys=[por_id], lazy="joined")
    em_nome_de = db.relationship("User", foreign_keys=[em_nome_de_id], lazy="joined")
    arquivos   = db.relationship("FluxoArquivo", back_populates="passagem",
                                 cascade="all, delete-orphan", lazy="selectin",
                                 order_by="FluxoArquivo.id")


class FluxoArquivo(db.Model):
    """Arquivo anexado a uma passagem. `sha256` é o nome do blob em disco
    (arquivos_store): o mesmo PDF em vários lugares ocupa um arquivo só — por isso
    `documentos._sha_orfao` precisa contar esta tabela também."""
    __tablename__ = "fluxo_arquivos"

    id = db.Column(db.Integer, primary_key=True)
    passagem_id   = db.Column(db.Integer, db.ForeignKey("fluxo_passagens.id"),
                              nullable=False, index=True)
    sha256        = db.Column(db.String(64), nullable=False, index=True)
    nome_original = db.Column(db.String(300), nullable=False, default="")
    ext           = db.Column(db.String(10), default="")
    mime          = db.Column(db.String(120), default="")
    tamanho       = db.Column(db.Integer, default=0)

    passagem = db.relationship("FluxoPassagem", back_populates="arquivos")

    def to_dict(self):
        import arquivos_store
        return {
            "id":       self.id,
            "nome":     self.nome_original or "",
            "ext":      (self.ext or "").lstrip("."),
            "tamanho":  self.tamanho or 0,
            "pode_visualizar": arquivos_store.pode_visualizar(self.nome_original or ""),
        }


# ── SEMENTE ───────────────────────────────────────────────────────────────────
# O caso que motivou o módulo: a autora escreve, o diagramador diagrama, a
# autora revisa e devolve até aprovar. Semeado só num banco sem nenhum modelo —
# apagar ou renomear depois é decisão da gestão, e a subida não o recria.
MODELO_PADRAO = {
    "nome": "Manual",
    "descricao": "Escrita do texto, diagramação e revisão com idas e voltas.",
    "papeis": [{"chave": "autor", "nome": "Autor(a)", "padrao_user_id": None},
               {"chave": "diagramador", "nome": "Diagramador(a)", "padrao_user_id": None}],
    "etapas": [{"chave": "escrita", "nome": "Escrita", "papel": "autor",
                "tipo": "execucao", "devolve_para": ""},
               {"chave": "diagramacao", "nome": "Diagramação", "papel": "diagramador",
                "tipo": "execucao", "devolve_para": ""},
               {"chave": "revisao", "nome": "Revisão", "papel": "autor",
                "tipo": "revisao", "devolve_para": "diagramacao"}],
}


def semear_modelo_padrao():
    """Cria o modelo "Manual" se não houver modelo nenhum. Devolve True se criou."""
    if FluxoModelo.query.first() is not None:
        return False
    db.session.add(FluxoModelo(
        nome=MODELO_PADRAO["nome"], descricao=MODELO_PADRAO["descricao"],
        papeis=json.dumps(MODELO_PADRAO["papeis"], ensure_ascii=False),
        etapas=json.dumps(MODELO_PADRAO["etapas"], ensure_ascii=False),
        criado_por="sistema", atualizado_por="sistema"))
    db.session.commit()
    return True
