"""
notificacoes/routes.py — a caixa de entrada pela API.

  GET  /api/notificacoes             as minhas (?nao_lidas=1, ?limite=N até 100)
  GET  /api/notificacoes/contagem    {nao_lidas} — o que o sino consulta
  POST /api/notificacoes/<id>/lida   marca uma das minhas
  POST /api/notificacoes/lidas       marca todas as minhas

Escopo é sempre "as minhas": não há parâmetro de usuário, nem para gestão. A
notificação de outra pessoa responde 404 e não 403 — o id é sequencial, e um 403
confirmaria que aquele aviso existe.

`leitura` fica fora (403), como em Missões e Tempos: nenhum módulo avisa esse
perfil de nada, e o sino nem aparece para ele.
"""
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity

from models import db, User
from auth import require_role

from .models import Notificacao

notificacoes_bp = Blueprint("notificacoes", __name__)

LIMITE_PADRAO = 30
LIMITE_MAX = 100


def so_membros(fn):
    return require_role("admin", "gestor", "tecnico")(fn)


def _eu():
    return User.query.filter_by(email=get_jwt_identity()).first()


@notificacoes_bp.route("/api/notificacoes", methods=["GET"])
@so_membros
def listar():
    u = _eu()
    try:
        limite = max(1, min(LIMITE_MAX, int(request.args.get("limite", LIMITE_PADRAO))))
    except (TypeError, ValueError):
        limite = LIMITE_PADRAO
    q = Notificacao.query.filter_by(user_id=u.id)
    if request.args.get("nao_lidas") == "1":
        q = q.filter(Notificacao.lida_em.is_(None))
    # Não lidas primeiro; dentro de cada grupo, as mais novas.
    linhas = (q.order_by(Notificacao.lida_em.isnot(None), Notificacao.criada_em.desc(),
                         Notificacao.id.desc())
              .limit(limite).all())
    return jsonify({"notificacoes": [n.to_dict() for n in linhas]})


@notificacoes_bp.route("/api/notificacoes/contagem", methods=["GET"])
@so_membros
def contagem():
    u = _eu()
    n = Notificacao.query.filter_by(user_id=u.id, lida_em=None).count()
    return jsonify({"nao_lidas": n})


@notificacoes_bp.route("/api/notificacoes/<int:nid>/lida", methods=["POST"])
@so_membros
def marcar_lida(nid):
    u = _eu()
    n = Notificacao.query.filter_by(id=nid, user_id=u.id).first()
    if n is None:
        return jsonify({"erro": "Notificação não encontrada"}), 404
    if n.lida_em is None:
        n.lida_em = datetime.now()
        db.session.commit()
    return jsonify({"notificacao": n.to_dict()})


@notificacoes_bp.route("/api/notificacoes/lidas", methods=["POST"])
@so_membros
def marcar_todas():
    u = _eu()
    n = (Notificacao.query.filter_by(user_id=u.id, lida_em=None)
         .update({"lida_em": datetime.now()}, synchronize_session=False))
    db.session.commit()
    return jsonify({"marcadas": n})
