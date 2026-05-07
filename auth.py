"""
auth.py — Autenticação JWT e CRUD de usuários com RBAC
Rotas:
  POST /api/auth/login
  POST /api/auth/refresh
  GET  /api/auth/me
  GET  /api/users
  POST /api/users
  GET  /api/users/<id>
  PATCH /api/users/<id>
  DELETE /api/users/<id>
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity, get_jwt
)
from datetime import datetime
from functools import wraps

from models import db, User, AuditLog, RevokedToken

auth_bp = Blueprint("auth", __name__)


# ── HELPERS ──────────────────────────────────────────────────────────────────

def log_action(user_email, acao, entidade="", campo="", antigo="", novo="",
               ip="", documento_id=None):
    """Grava uma entrada no audit log com rastreabilidade completa."""
    user = User.query.filter_by(email=user_email).first()
    entry = AuditLog(
        usuario_id=user.id if user else None,
        usuario_email=user_email,
        documento_id=documento_id,
        acao=acao,
        entidade=entidade,
        campo=campo,
        valor_antigo=str(antigo) if antigo is not None else "",
        valor_novo=str(novo) if novo is not None else "",
        ip=ip,
    )
    db.session.add(entry)
    db.session.commit()


def require_role(*roles):
    """Decorator: exige que o usuário tenha um dos roles listados."""
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            identity = get_jwt_identity()          # email do usuário
            claims   = get_jwt()                    # claims extras (role)
            role     = claims.get("role", "")
            if role not in roles:
                return jsonify({"erro": "Acesso negado para este perfil"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def get_client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "")


# ── LOGIN ─────────────────────────────────────────────────────────────────────

@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    data  = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    senha = data.get("senha", "")

    if not email or not senha:
        return jsonify({"erro": "Email e senha são obrigatórios"}), 400

    user = User.query.filter_by(email=email, ativo=True).first()

    if not user or not user.check_senha(senha):
        return jsonify({"erro": "Email ou senha incorretos"}), 401

    # Atualiza último login
    user.ultimo_login = datetime.utcnow()
    db.session.commit()

    # Cria tokens com role como claim extra
    additional = {"role": user.role, "nome": user.nome}
    access_token  = create_access_token(identity=user.email, additional_claims=additional)
    refresh_token = create_refresh_token(identity=user.email, additional_claims=additional)

    log_action(user.email, "LOGIN", ip=get_client_ip())

    return jsonify({
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "usuario": user.to_dict(),
    }), 200


@auth_bp.route("/api/auth/logout", methods=["POST"])
@jwt_required()
def logout():
    """B2: revoga o JTI do token atual (blocklist)."""
    jti = get_jwt().get("jti")
    if jti:
        try:
            db.session.add(RevokedToken(jti=jti))
            db.session.commit()
        except Exception:
            db.session.rollback()
    return jsonify({"mensagem": "Logout realizado"}), 200


@auth_bp.route("/api/auth/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    identity = get_jwt_identity()
    claims   = get_jwt()
    user = User.query.filter_by(email=identity, ativo=True).first()
    if not user:
        return jsonify({"erro": "Usuário não encontrado"}), 404
    additional   = {"role": user.role, "nome": user.nome}
    access_token = create_access_token(identity=identity, additional_claims=additional)
    return jsonify({"access_token": access_token}), 200


@auth_bp.route("/api/auth/me", methods=["GET"])
@jwt_required()
def me():
    identity = get_jwt_identity()
    user = User.query.filter_by(email=identity).first()
    if not user:
        return jsonify({"erro": "Usuário não encontrado"}), 404
    return jsonify(user.to_dict()), 200


# ── LISTAR USUÁRIOS ────────────────────────────────────────────────────────────

@auth_bp.route("/api/users", methods=["GET"])
@require_role("admin", "gestor")
def list_users():
    users = User.query.order_by(User.nome).all()
    return jsonify([u.to_dict() for u in users]), 200


# ── CRIAR USUÁRIO ──────────────────────────────────────────────────────────────

@auth_bp.route("/api/users", methods=["POST"])
@require_role("admin")
def create_user():
    caller_email = get_jwt_identity()
    data  = request.get_json(silent=True) or {}

    nome  = data.get("nome",  "").strip()
    email = data.get("email", "").strip().lower()
    senha = data.get("senha", "").strip()
    role  = data.get("role",  "tecnico").strip()

    # Validações
    if not nome or not email or not senha:
        return jsonify({"erro": "Nome, email e senha são obrigatórios"}), 400
    if role not in ("admin", "gestor", "tecnico", "leitura"):
        return jsonify({"erro": "Role inválido. Use: admin, gestor, tecnico, leitura"}), 400
    if len(senha) < 6:
        return jsonify({"erro": "Senha deve ter pelo menos 6 caracteres"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"erro": "Este e-mail já está cadastrado"}), 409

    user = User(nome=nome, email=email, role=role)
    user.set_senha(senha)
    db.session.add(user)
    db.session.commit()

    log_action(caller_email, "CREATE", entidade=email,
               campo="role", novo=role, ip=get_client_ip())

    return jsonify({"mensagem": "Usuário criado com sucesso", "usuario": user.to_dict()}), 201


# ── BUSCAR USUÁRIO POR ID ──────────────────────────────────────────────────────

@auth_bp.route("/api/users/<int:user_id>", methods=["GET"])
@jwt_required()
def get_user(user_id):
    caller_email = get_jwt_identity()
    claims = get_jwt()
    caller_role = claims.get("role", "")

    user = User.query.get(user_id)
    if not user:
        return jsonify({"erro": "Usuário não encontrado"}), 404

    # Técnico e leitura só podem ver o próprio perfil
    if caller_role in ("tecnico", "leitura") and user.email != caller_email:
        return jsonify({"erro": "Acesso negado"}), 403

    return jsonify(user.to_dict()), 200


# ── EDITAR USUÁRIO ─────────────────────────────────────────────────────────────

@auth_bp.route("/api/users/<int:user_id>", methods=["PATCH"])
@require_role("admin")
def update_user(user_id):
    caller_email = get_jwt_identity()
    data = request.get_json(silent=True) or {}

    user = User.query.get(user_id)
    if not user:
        return jsonify({"erro": "Usuário não encontrado"}), 404

    changes = []

    if "nome" in data:
        novo_nome = data["nome"].strip()
        if novo_nome and novo_nome != user.nome:
            changes.append(("nome", user.nome, novo_nome))
            user.nome = novo_nome

    if "email" in data:
        novo_email = data["email"].strip().lower()
        if novo_email and novo_email != user.email:
            existente = User.query.filter_by(email=novo_email).first()
            if existente and existente.id != user_id:
                return jsonify({"erro": "Este e-mail já está em uso"}), 409
            changes.append(("email", user.email, novo_email))
            user.email = novo_email

    if "role" in data:
        novo_role = data["role"].strip()
        if novo_role not in ("admin", "gestor", "tecnico", "leitura"):
            return jsonify({"erro": "Role inválido"}), 400
        if novo_role != user.role:
            changes.append(("role", user.role, novo_role))
            user.role = novo_role

    if "ativo" in data:
        novo_ativo = bool(data["ativo"])
        if novo_ativo != user.ativo:
            changes.append(("ativo", user.ativo, novo_ativo))
            user.ativo = novo_ativo

    if "senha" in data:
        nova_senha = data["senha"].strip()
        if len(nova_senha) < 6:
            return jsonify({"erro": "Senha deve ter pelo menos 6 caracteres"}), 400
        user.set_senha(nova_senha)
        changes.append(("senha", "***", "***atualizada***"))

    db.session.commit()

    # Audit log — uma entrada por campo alterado
    for campo, antigo, novo in changes:
        log_action(caller_email, "UPDATE", entidade=user.email,
                   campo=campo, antigo=antigo, novo=novo, ip=get_client_ip())

    return jsonify({"mensagem": "Usuário atualizado", "usuario": user.to_dict()}), 200


# ── DESATIVAR USUÁRIO (soft delete) ────────────────────────────────────────────

@auth_bp.route("/api/users/<int:user_id>", methods=["DELETE"])
@require_role("admin")
def delete_user(user_id):
    caller_email = get_jwt_identity()

    user = User.query.get(user_id)
    if not user:
        return jsonify({"erro": "Usuário não encontrado"}), 404

    # Protege: não deixa desativar o próprio usuário
    if user.email == caller_email:
        return jsonify({"erro": "Você não pode desativar sua própria conta"}), 400

    user.ativo = False
    db.session.commit()

    log_action(caller_email, "DELETE", entidade=user.email, ip=get_client_ip())

    return jsonify({"mensagem": f"Usuário {user.email} desativado com sucesso"}), 200
