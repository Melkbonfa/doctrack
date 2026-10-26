"""
notificacoes/models.py — a caixa de entrada de cada pessoa (o sino).

Uma tabela só. É genérica de propósito: nasceu para os fluxos de revisão, mas
qualquer módulo que precise avisar UMA pessoa de algo grava aqui — e é daqui que
um envio por e-mail leria, no dia em que o TI liberar uma conta de serviço.

## Por que tabela e não só o barramento de eventos

`publish_event` grava em `audit_logs` e emite para salas. Ele não serve para
aviso pessoal por dois motivos:

  1. **Quem estava fora não recebe.** O socket entrega a quem está com a tela
     aberta; a pessoa que entra amanhã precisa achar o aviso esperando por ela.
  2. **O replay vazaria.** `replay_request` (servidor.py) devolve a trilha de
     `audit_logs` inteira para qualquer conexão, sem filtrar por sala. Um aviso
     pessoal gravado ali chegaria a quem reconectasse. Por isso a notificação
     NUNCA passa por `publish_event`: o sino consulta a contagem pela API.
"""
from datetime import datetime

from models import db

TIPOS_NOTIFICACAO = ["acao", "info"]   # acao = "é sua vez"; info = andamento


class Notificacao(db.Model):
    __tablename__ = "notificacoes"

    id = db.Column(db.Integer, primary_key=True)
    # CASCADE pelo mesmo motivo de tempo_apontamentos.user_id: auth.py apaga o
    # User de verdade (?permanente=true), e sem isto o Postgres recusaria.
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False)
    tipo        = db.Column(db.String(10), nullable=False, default="info")  # acao|info
    titulo      = db.Column(db.String(200), nullable=False, default="")
    texto       = db.Column(db.String(400), default="")
    # Relativo ("/?doc=12", "/projetos?projeto=3&entregavel=9"): o mesmo banco
    # serve pela rede interna e pelo túnel, com hosts diferentes.
    link        = db.Column(db.String(300), default="")
    # De onde veio (ex.: 'fluxo' + id do fluxo). Sem FK: a origem pode ser de
    # qualquer módulo, e o aviso sobrevive a ela.
    origem_tipo = db.Column(db.String(20), default="")
    origem_id   = db.Column(db.Integer, nullable=True)
    criada_em   = db.Column(db.DateTime, nullable=False, default=datetime.now)
    lida_em     = db.Column(db.DateTime, nullable=True)        # NULL = não lida

    __table_args__ = (
        # Toda leitura é "as minhas, não lidas primeiro, mais novas primeiro".
        db.Index("ix_notificacoes_user_lida", "user_id", "lida_em", "criada_em"),
    )

    def to_dict(self):
        return {
            "id":          self.id,
            "tipo":        self.tipo or "info",
            "titulo":      self.titulo or "",
            "texto":       self.texto or "",
            "link":        self.link or "",
            "origem_tipo": self.origem_tipo or "",
            "origem_id":   self.origem_id,
            "criada_em":   self.criada_em.strftime("%d/%m/%Y %H:%M") if self.criada_em else "",
            "criada_em_iso": self.criada_em.isoformat() if self.criada_em else "",
            "lida":        self.lida_em is not None,
        }
