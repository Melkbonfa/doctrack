"""
tempos/models.py — Modelo SQLAlchemy do módulo Tempos (apontamento de horas).

Reutiliza o `db` da plataforma mestre. Tabela prefixada `tempo_` para não colidir
com o domínio de Documentos/Projetos/Equipamentos.

Domínio: uma tabela só, `Apontamento` — um intervalo de trabalho de uma pessoa,
opcionalmente amarrado a um projeto, entregável, cartão de missão ou equipamento
(ou a nada, quando a tarefa não existe na plataforma).

## Quatro decisões que valem a explicação

**1. Pausar FECHA o intervalo; retomar abre outro.** A alternativa (uma linha com
`pausado_em` + segundos acumulados) cria um terceiro estado que envenena a
invariante do cronômetro único: pausado conta como "em curso"? Se sim, o índice
parcial trava a pessoa durante o almoço; se não, acumulam-se N linhas pausadas
esquecidas sem regra de qual "retomar" alcança. Aqui uma linha é SEMPRE um
intervalo fechado, então `duracao_s == fim - inicio` vale sempre e todo relatório
é um `SUM`. Corrigir "esqueci de voltar do almoço" vira editar um horário que se
confere contra um relógio, e não um acumulador sem referente externo.

O preço é que um dia com 4 pausas são 5 linhas. `sessao_id` paga isso: é o id do
PRIMEIRO trecho da corrente, e `GROUP BY sessao_id` devolve a sessão inteira.

Consequência: **pausar e parar são a mesma escrita** — fecham a linha e calculam
`duracao_s`, diferindo só em `encerrado_por`. É essa coluna que torna a linha
elegível a retomada. Um caminho de código (`core.fechar`), nenhuma máquina de
estado.

**2. `DateTime` real, não a string ISO de Projeto/Entregavel/MissaoCartao.** Ali a
data é um rótulo; aqui a aritmética abaixo do dia É o produto, e comparar `inicio`
como texto para montar a janela do relatório seria comparação lexicográfica.
`Documento` e os marcos de `MissaoCartao` (criado_em/concluido_em) já usam
DateTime pelo mesmo motivo. Naive local, como o resto do repositório — ver a nota
de fuso em `core.py`.

**3. `duracao_s` é `Integer`, derivado e persistido.** Nem `Float` nem o `Numeric`
de custos: o argumento lá é sobre aritmética *encadeada* acumulando erro, e aqui é
uma subtração e um `SUM`. Segundo inteiro é exato por construção. Persistido
porque calcular no SQL exigiria `julianday()` no SQLite e `EXTRACT(EPOCH FROM …)`
no Postgres — dois dialetos de agregação num projeto que roda nos dois. A
invariante é mantida em um lugar só: `core.fechar()`.

**4. Um cronômetro em curso por pessoa, garantido NO BANCO.** Índice parcial e
único em `(user_id) WHERE fim IS NULL`. SQLite (>= 3.8, 2013) e PostgreSQL aceitam
a mesma sintaxe. SQLAlchemy não tem `where=` neutro de dialeto: são obrigatórios
`sqlite_where=` E `postgresql_where=`, cada dialeto emite o seu e ignora o outro.
Num terceiro dialeto ambos seriam ignorados e sobraria um `UNIQUE(user_id)` puro —
um apontamento por pessoa, para sempre. Não é alcançável aqui, mas é o motivo de
esta linha nunca poder ser "simplificada" para um `where=` só.
"""
import os
from datetime import datetime

from models import db, Projeto, Entregavel, MissaoCartao, Equipamento
from utils import norm

# ── CONSTANTES DE DOMÍNIO ─────────────────────────────────────────────────────

# Alvos cronometráveis. 'livre' é a tarefa que não existe na plataforma: sem
# ref_id, com `titulo` obrigatório. Sem ela o módulo mediria só o trabalho que já
# está cadastrado — e some justamente a reunião, o suporte e o imprevisto, que é
# onde as horas costumam vazar.
REF_TIPOS_TEMPO = ["projeto", "entregavel", "missao_cartao", "equipamento", "livre"]
REF_TIPOS_LABELS = {
    "projeto":       "Projeto",
    "entregavel":    "Entregável",
    "missao_cartao": "Cartão de missão",
    "equipamento":   "Equipamento",
    "livre":         "Tarefa livre",
}

# Quem fechou o intervalo. 'pausa' é o que torna a linha elegível a retomada;
# 'guarda' marca o corte automático do cronômetro abandonado (ver core).
ENCERRAMENTOS = ["usuario", "pausa", "guarda"]

ORIGENS = ["cronometro", "manual"]

# ── LIMITES OPERACIONAIS ──────────────────────────────────────────────────────
# Todos configuráveis por ambiente porque são política, não regra de domínio.


def _env_int(nome, padrao):
    try:
        return int(os.environ.get(nome, "") or padrao)
    except ValueError:
        return padrao


# Além disto o cronômetro é considerado abandonado e cortado (ver
# core.encerrar_abandonados). 8h truncaria um dia longo legítimo; 12h só pega
# esquecimento de verdade e ainda corta sexta->segunda para um número defensável.
LIMITE_CRONOMETRO_H = _env_int("DOCTRACK_TEMPO_LIMITE_H", 12)

# Janela em que uma pausa continua oferecível como "retomar".
JANELA_RETOMADA_H = _env_int("DOCTRACK_TEMPO_RETOMADA_H", 12)

# Teto de um apontamento manual. Uma linha de 400 horas é erro de digitação.
LIMITE_APONTAMENTO_H = _env_int("DOCTRACK_TEMPO_MAX_H", 16)

# Quão para trás se pode lançar. Barra o 1970 de um campo mal interpretado.
RETROATIVO_DIAS = _env_int("DOCTRACK_TEMPO_RETROATIVO_DIAS", 90)

# Tolerância de relógio ao aceitar um `fim` "agora" vindo do cliente.
FOLGA_RELOGIO_S = 120


def fmt_dur(segundos):
    """Segundos -> '2h 05m'. Sempre com minutos: '2h' sozinho parece arredondado."""
    s = max(0, int(segundos or 0))
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


class Apontamento(db.Model):
    __tablename__ = "tempo_apontamentos"

    id = db.Column(db.Integer, primary_key=True)

    # FK real, e não o vínculo solto usado em `ref_tipo/ref_id` abaixo: a pessoa é
    # a chave do módulo inteiro e apontamento órfão não tem leitura possível.
    # CASCADE porque auth.py:454 apaga o User de verdade (?permanente=true) e só
    # sabe limpar audit_logs — sem isto aquele endpoint passaria a estourar FK no
    # Postgres assim que alguém com horas lançadas fosse removido.
    user_id = db.Column(db.Integer,
                        db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False)

    # Vínculo tipado, sem FK rígida — mesmo desenho de MissaoCartao.ref_tipo /
    # ref_id (models.py:2083), validado na gravação por core.validar_ref().
    ref_tipo = db.Column(db.String(20), nullable=False, default="livre")
    ref_id   = db.Column(db.Integer, nullable=True)

    # Rótulo congelado na gravação. Num alvo da plataforma é redundante com
    # _ref_meta() e existe só para o relatório sobreviver ao equipamento renomeado
    # ou ao cartão apagado; em 'livre' é o dado em si.
    titulo       = db.Column(db.String(200), default="")
    titulo_chave = db.Column(db.String(200), default="")   # norm(titulo)

    # Rollup denormalizado, resolvido UMA vez na gravação (core.resolver_projeto).
    # É fato congelado, não cache: se um entregável for remanejado daqui a seis
    # meses, as horas já lançadas pertencem ao projeto em que foram gastas —
    # mesma leitura de Lancamento.taxa_aplicada ficar congelada na linha
    # (custos/models.py:312). Recalcular faria total histórico mudar sozinho.
    projeto_id = db.Column(db.Integer, db.ForeignKey("projetos.id"), nullable=True)

    inicio    = db.Column(db.DateTime, nullable=False)
    fim       = db.Column(db.DateTime, nullable=True)      # NULL = em curso
    duracao_s = db.Column(db.Integer, nullable=False, default=0)

    origem        = db.Column(db.String(12), nullable=False, default="cronometro")
    encerrado_por = db.Column(db.String(12), default="")

    # Encadeia os trechos de uma sessão pausada/retomada: id do PRIMEIRO trecho.
    # Auto-referência sem FK — a linha ainda não tem id quando é montada, então o
    # valor é gravado após o flush (ver core.abrir).
    sessao_id = db.Column(db.Integer, nullable=True)

    nota = db.Column(db.Text, default="")

    criado_em   = db.Column(db.DateTime, default=datetime.now)
    criado_por  = db.Column(db.String(120), default="")    # e-mail (convenção)
    editado_em  = db.Column(db.DateTime, onupdate=datetime.now)
    editado_por = db.Column(db.String(120), default="")

    usuario = db.relationship("User", lazy="joined")

    __table_args__ = (
        # O filtro é sempre (pessoa, janela) — "meu mês", "o mês do fulano". Por
        # isso `user_id` não leva index=True na coluna: seria índice redundante
        # com o prefixo deste aqui.
        db.Index("ix_tempo_user_inicio", "user_id", "inicio"),
        # "quanto já se gastou neste cartão/equipamento?", chamada pelas fichas
        # dos outros módulos. Mesmo motivo do ix_missao_cartoes_ref
        # (models.py:2107): sem ele é full scan por (ref_tipo, ref_id).
        db.Index("ix_tempo_ref", "ref_tipo", "ref_id"),
        db.Index("ix_tempo_projeto_inicio", "projeto_id", "inicio"),
        db.Index("ix_tempo_sessao", "sessao_id"),
        # A invariante do cronômetro único (ver o item 4 do docstring do módulo).
        db.Index("uq_tempo_em_curso", "user_id", unique=True,
                 sqlite_where=db.text("fim IS NULL"),
                 postgresql_where=db.text("fim IS NULL")),
    )

    # ── DERIVADOS ─────────────────────────────────────────────────────────────

    @property
    def em_curso(self):
        return self.fim is None

    @property
    def duracao_viva(self):
        """Segundos decorridos — conta o relógio enquanto a linha está aberta.

        O front recebe isto só como valor inicial; a contagem que ele exibe é
        ancorada em `servidor_agora` (ver a rota /atual). Sem essa âncora o dado
        estaria certo e o usuário veria '-3h 12m' num relógio adiantado.
        """
        if self.fim is not None:
            return int(self.duracao_s or 0)
        if not self.inicio:
            return 0
        return max(0, int((datetime.now() - self.inicio).total_seconds()))

    def _ref_meta(self):
        """Metadados leves do vínculo (chip): rótulo + se a entidade segue ativa.

        1 query por apontamento — em listagens grandes passe `ref_info`
        pré-computado ao to_dict, como faz o _mapa_refs de missoes.py.

        `ativo=False` quando a entidade existe mas foi desativada: sem isso o chip
        simplesmente sumiria e a linha perderia o contexto sem avisar ninguém —
        exatamente o que MissaoCartao._ref_meta (models.py:2146) aprendeu.
        """
        meta = {"label": "", "ativo": True}
        if self.ref_tipo == "livre" or not self.ref_id:
            return meta
        try:
            if self.ref_tipo == "projeto":
                p = Projeto.query.get(self.ref_id)
                if p:
                    meta.update(label=p.nome, ativo=bool(p.ativo))
            elif self.ref_tipo == "entregavel":
                e = Entregavel.query.get(self.ref_id)
                if e:
                    meta.update(label=(e.tipo or "").strip())
            elif self.ref_tipo == "missao_cartao":
                c = MissaoCartao.query.get(self.ref_id)
                if c:
                    meta.update(label=(c.titulo or "").strip())
            elif self.ref_tipo == "equipamento":
                eq = Equipamento.query.get(self.ref_id)
                if eq:
                    meta.update(label=eq.nome, ativo=bool(eq.ativo))
        except Exception:
            pass
        return meta

    def rotulo(self, ref_info=None):
        """O que mostrar na folha: o rótulo vivo do alvo, ou o título congelado."""
        ref = ref_info if ref_info is not None else self._ref_meta()
        return ref.get("label") or (self.titulo or "").strip() or "(sem título)"

    def to_dict(self, ref_info=None):
        ref = ref_info if ref_info is not None else self._ref_meta()
        return {
            "id":            self.id,
            "user_id":       self.user_id,
            "usuario_nome":  self.usuario.nome if self.usuario else "",
            "ref_tipo":      self.ref_tipo or "livre",
            "ref_id":        self.ref_id,
            "ref_label":     ref.get("label", ""),
            "ref_ativo":     ref.get("ativo", True),
            "titulo":        self.titulo or "",
            "rotulo":        self.rotulo(ref),
            "projeto_id":    self.projeto_id,
            "inicio":        self.inicio.strftime("%d/%m/%Y %H:%M") if self.inicio else "",
            "inicio_iso":    self.inicio.isoformat() if self.inicio else "",
            "fim":           self.fim.strftime("%d/%m/%Y %H:%M") if self.fim else "",
            "fim_iso":       self.fim.isoformat() if self.fim else "",
            "dia_iso":       self.inicio.date().isoformat() if self.inicio else "",
            "em_curso":      self.em_curso,
            "duracao_s":     self.duracao_viva,
            "duracao":       fmt_dur(self.duracao_viva),
            "origem":        self.origem or "cronometro",
            "encerrado_por": self.encerrado_por or "",
            "sessao_id":     self.sessao_id,
            "nota":          self.nota or "",
            "criado_por":    self.criado_por or "",
            # Só faz sentido exibir quando alguém que não é o dono mexeu. O MVP
            # não tem aprovação; gestor reescrevendo horas em silêncio *é*
            # aprovação com o consentimento removido. Tornar o poder visível
            # mantém honesto sem precisar de máquina de estado.
            "editado_por":   self.editado_por or "",
            "editado_em":    self.editado_em.strftime("%d/%m/%Y %H:%M") if self.editado_em else "",
            "editado":       bool(self.editado_por and self.editado_por != self.criado_por),
        }


def chave_titulo(titulo):
    """Chave de agrupamento do título livre. Reusa utils.norm (era a 4ª cópia
    possível dessa normalização no repositório)."""
    return norm(titulo)[:200]
