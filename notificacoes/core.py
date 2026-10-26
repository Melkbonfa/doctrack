"""
notificacoes/core.py — regra de negócio do sino, sem Flask.

`notificar()` só enfileira na sessão: o commit é do chamador, para que o aviso
entre na MESMA transação da ação que o gerou. Uma passagem de fluxo que falha
não pode deixar para trás um "é sua vez" de algo que não aconteceu.
"""
from datetime import datetime, timedelta

from models import db, User

from .models import Notificacao

# Dias que uma notificação JÁ LIDA fica guardada. As não lidas nunca saem
# sozinhas: um aviso que ninguém viu não perde a validade por ter envelhecido.
RETENCAO_LIDAS_DIAS = 90


def notificar(user_ids, *, tipo="info", titulo, texto="", link="",
              origem_tipo="", origem_id=None, exceto=None):
    """Enfileira uma notificação para cada pessoa de `user_ids`.

    Deduplica (uma pessoa com dois papéis no mesmo fluxo recebe um aviso só),
    pula `exceto` (quem agiu não é avisado da própria ação) e pula usuário
    inativo. Devolve quantas foram criadas. NÃO comita.
    """
    alvo = []
    for uid in user_ids or []:
        if uid and uid != exceto and uid not in alvo:
            alvo.append(uid)
    if not alvo:
        return 0
    ativos = {u.id for u in User.query.filter(User.id.in_(alvo), User.ativo == True)}
    agora = datetime.now()
    n = 0
    for uid in alvo:
        if uid not in ativos:
            continue
        db.session.add(Notificacao(
            user_id=uid, tipo=tipo, titulo=(titulo or "")[:200],
            texto=(texto or "")[:400], link=(link or "")[:300],
            origem_tipo=origem_tipo or "", origem_id=origem_id, criada_em=agora))
        n += 1
    return n


def purgar_lidas(dias=RETENCAO_LIDAS_DIAS):
    """Apaga as notificações lidas há mais de `dias`. Tarefa diária; comita."""
    corte = datetime.now() - timedelta(days=dias)
    n = (Notificacao.query
         .filter(Notificacao.lida_em.isnot(None), Notificacao.lida_em < corte)
         .delete(synchronize_session=False))
    db.session.commit()
    return n
