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
import os

from models import db, User, AuditLog, RevokedToken
from areas import dump_areas, parse_areas, AREA_SLUGS
import ratelimit

auth_bp = Blueprint("auth", __name__)

# Mínimo de caracteres para uma senha nova. Eram 6 — curto o bastante para
# caber num ataque de dicionário e abaixo de qualquer recomendação atual.
# Só afeta senhas NOVAS; as existentes continuam valendo até a próxima troca.
SENHA_MIN = int(os.environ.get("DOCTRACK_SENHA_MIN", "8"))
ERRO_SENHA_CURTA = f"Senha deve ter pelo menos {SENHA_MIN} caracteres"


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


def require_area(slug, *roles):
    """Exige acesso a uma Área de P&D e, opcionalmente, um dos perfis informados.

    Acesso: admin (sempre) ou usuário com `slug` em `areas`.
    Se `roles` for informado, também exige que o perfil esteja na lista
    (usado nas rotas de escrita / módulos como Projetos). Sem `roles`, basta o acesso.
    """
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            email = get_jwt_identity()
            user  = User.query.filter_by(email=email, ativo=True).first()
            if not user or not user.tem_area(slug):
                return jsonify({"erro": "Sem acesso a esta área"}), 403
            if roles and user.role not in roles:
                return jsonify({"erro": "Acesso negado para este perfil"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_pdr_access(*roles):
    """Compat: acesso à área PDR (P&D de reagentes)."""
    return require_area("pdr", *roles)


def get_client_ip():
    # remote_addr já reflete o cliente real quando TRUST_PROXY está ativo (ProxyFix
    # aplica o X-Forwarded-For). Sem proxy confiável, não lemos o cabeçalho — ele é
    # forjável e este IP é gravado no audit log.
    return request.remote_addr or ""


# ── LOGIN ─────────────────────────────────────────────────────────────────────

@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    data  = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    senha = data.get("senha", "")

    if not email or not senha:
        return jsonify({"erro": "Email e senha são obrigatórios"}), 400

    # Limite de tentativas antes de tocar o banco: o bcrypt é a parte caríssima
    # da requisição, então checar depois seria pagar o custo do ataque.
    chaves = ratelimit.chaves_login(email)
    travado = ratelimit.checar(chaves, ratelimit.LIMITE_LOGIN, ratelimit.JANELA_LOGIN)
    if travado is not None:
        return travado

    user = User.query.filter_by(email=email, ativo=True).first()

    # Conta pendente de primeiro acesso/reset: orienta a definir a senha
    if user and user.precisa_definir_senha:
        return jsonify({
            "erro": "Esta conta ainda não tem senha. Use o código de ativação para definir sua senha no primeiro acesso.",
            "precisa_definir_senha": True,
        }), 403

    if not user or not user.check_senha(senha):
        for chave in chaves:
            ratelimit.registrar_falha(chave)
        return jsonify({"erro": "Email ou senha incorretos"}), 401

    ratelimit.limpar_chave(chaves[0])

    # Atualiza último login
    user.ultimo_login = datetime.now()
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


# ── PRIMEIRO ACESSO (definir a própria senha) ──────────────────────────────────

@auth_bp.route("/api/auth/primeiro-acesso", methods=["POST"])
def primeiro_acesso():
    """Rota pública: o usuário troca o código de ativação pela própria senha.

    Usada tanto no convite (admin cria a conta) quanto após um reset de senha.
    """
    data   = request.get_json(silent=True) or {}
    email  = data.get("email",  "").strip().lower()
    codigo = data.get("codigo", "").strip()
    senha  = data.get("senha",  "")

    if not email or not codigo or not senha:
        return jsonify({"erro": "E-mail, código e nova senha são obrigatórios"}), 400
    if len(senha) < SENHA_MIN:
        return jsonify({"erro": ERRO_SENHA_CURTA}), 400

    # Um código de ativação é 8 caracteres que valem uma conta inteira — é o
    # alvo mais atraente do sistema e o que mais precisava de limite.
    chaves = ratelimit.chaves_ativacao(email)
    travado = ratelimit.checar(chaves, ratelimit.LIMITE_ATIVACAO, ratelimit.JANELA_ATIVACAO)
    if travado is not None:
        return travado

    user = User.query.filter_by(email=email, ativo=True).first()

    # Mensagens distintas para orientar o usuário (ferramenta interna)
    if not user or not user.precisa_definir_senha or not user.ativacao_codigo_hash:
        return jsonify({"erro": "Não há primeiro acesso pendente para este e-mail. Confira o e-mail digitado."}), 400
    if user.ativacao_expira and datetime.now() > user.ativacao_expira:
        return jsonify({"erro": "Código de ativação expirado. Peça um novo ao administrador."}), 400
    if not user.check_codigo(codigo):
        for chave in chaves:
            ratelimit.registrar_falha(chave)
        return jsonify({"erro": "Código de ativação incorreto."}), 400

    ratelimit.limpar_chave(chaves[0])
    user.set_senha(senha)          # também limpa o código e o estado pendente
    user.ultimo_login = datetime.now()
    db.session.commit()

    log_action(user.email, "FIRST_ACCESS", entidade=user.email, ip=get_client_ip())

    # Já autentica o usuário para entrar direto
    additional = {"role": user.role, "nome": user.nome}
    access_token  = create_access_token(identity=user.email, additional_claims=additional)
    refresh_token = create_refresh_token(identity=user.email, additional_claims=additional)

    return jsonify({
        "mensagem": "Senha definida com sucesso",
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "usuario": user.to_dict(),
    }), 200


# ── LISTAR USUÁRIOS ────────────────────────────────────────────────────────────

@auth_bp.route("/api/users", methods=["GET"])
@require_role("admin", "gestor")
def list_users():
    caller_email = get_jwt_identity()
    user = User.query.filter_by(email=caller_email).first()
    
    if user and user.role == "admin":
        users = User.query.order_by(User.nome).all()
    else:
        users = User.query.filter_by(ativo=True).order_by(User.nome).all()
        
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
    if not nome or not email:
        return jsonify({"erro": "Nome e email são obrigatórios"}), 400
    if role not in ("admin", "gestor", "tecnico", "leitura"):
        return jsonify({"erro": "Role inválido. Use: admin, gestor, tecnico, leitura"}), 400
    if senha and len(senha) < SENHA_MIN:
        return jsonify({"erro": ERRO_SENHA_CURTA}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"erro": "Este e-mail já está cadastrado"}), 409

    user = User(nome=nome, email=email, role=role)

    # Áreas de acesso (lista de slugs). Admin acessa todas por padrão da lógica;
    # para os demais, vale exatamente o que foi selecionado no cadastro.
    user.areas = dump_areas(data.get("areas") or [])
    # Compat: mantém a flag legada coerente com a área PDR selecionada.
    user.pode_pdr = "pdr" in parse_areas(user.areas)

    codigo = None
    if senha:
        # Admin já definiu uma senha (comportamento antigo)
        user.set_senha(senha)
    else:
        # Convite: usuário define a própria senha no primeiro acesso
        codigo = user.gerar_codigo_ativacao()

    db.session.add(user)
    db.session.commit()

    log_action(caller_email, "CREATE", entidade=email,
               campo="role", novo=role, ip=get_client_ip())

    resp = {"mensagem": "Usuário criado com sucesso", "usuario": user.to_dict()}
    if codigo:
        # Mostrado uma única vez para o admin repassar ao usuário
        resp["codigo_ativacao"] = codigo
        resp["validade_dias"]   = User.ATIVACAO_VALIDADE_DIAS
    return jsonify(resp), 201


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

    if "areas" in data:
        novas = dump_areas(data["areas"] or [])
        if novas != (user.areas or ""):
            changes.append(("areas", user.areas or "", novas))
            user.areas = novas
            user.pode_pdr = "pdr" in parse_areas(novas)   # compat com a flag legada
    elif "pode_pdr" in data:
        # Compat: edição antiga que ainda manda só a flag do PDR.
        novo_pdr = bool(data["pode_pdr"])
        if novo_pdr != bool(user.pode_pdr):
            changes.append(("pode_pdr", user.pode_pdr, novo_pdr))
            user.pode_pdr = novo_pdr
            atuais = parse_areas(user.areas)
            if novo_pdr and "pdr" not in atuais:
                atuais.append("pdr")
            elif not novo_pdr and "pdr" in atuais:
                atuais.remove("pdr")
            user.areas = dump_areas(atuais)

    if "senha" in data:
        nova_senha = data["senha"].strip()
        if len(nova_senha) < SENHA_MIN:
            return jsonify({"erro": ERRO_SENHA_CURTA}), 400
        user.set_senha(nova_senha)
        changes.append(("senha", "***", "***atualizada***"))

    db.session.commit()

    # Audit log — uma entrada por campo alterado
    for campo, antigo, novo in changes:
        log_action(caller_email, "UPDATE", entidade=user.email,
                   campo=campo, antigo=antigo, novo=novo, ip=get_client_ip())

    return jsonify({"mensagem": "Usuário atualizado", "usuario": user.to_dict()}), 200


# ── DESATIVAR (soft) OU EXCLUIR (permanente) USUÁRIO ───────────────────────────

@auth_bp.route("/api/users/<int:user_id>", methods=["DELETE"])
@require_role("admin")
def delete_user(user_id):
    """DELETE soft (ativo=False) por padrão.

    Com ?permanente=true remove o usuário de vez: desfaz as responsabilidades
    dele e desvincula (sem apagar) o histórico de auditoria, preservando a
    rastreabilidade pelo e-mail já gravado em cada log.
    """
    caller_email = get_jwt_identity()
    permanente = str(request.args.get("permanente", "")).lower() in ("1", "true", "yes")

    user = User.query.get(user_id)
    if not user:
        return jsonify({"erro": "Usuário não encontrado"}), 404

    # Protege: não deixa o admin se auto-excluir/desativar
    if user.email == caller_email:
        return jsonify({"erro": "Você não pode excluir ou desativar a própria conta"}), 400

    if not permanente:
        user.ativo = False
        db.session.commit()
        log_action(caller_email, "DELETE", entidade=user.email, ip=get_client_ip())
        return jsonify({"mensagem": f"Usuário {user.email} desativado com sucesso"}), 200

    # Exclusão permanente — limpar dependências para não violar FKs
    email = user.email
    AuditLog.query.filter_by(usuario_id=user.id).update(
        {"usuario_id": None}, synchronize_session=False)

    db.session.delete(user)
    db.session.commit()

    log_action(caller_email, "DELETE", entidade=email,
               campo="permanente", novo="true", ip=get_client_ip())

    return jsonify({"mensagem": f"Usuário {email} excluído permanentemente"}), 200


# ── RESETAR SENHA (gera novo código de primeiro acesso) ────────────────────────

@auth_bp.route("/api/users/<int:user_id>/reset-senha", methods=["POST"])
@require_role("admin")
def reset_senha(user_id):
    """Devolve a conta ao estado de primeiro acesso: limpa a senha e gera um
    novo código de ativação que o usuário troca pela nova senha."""
    caller_email = get_jwt_identity()

    user = User.query.get(user_id)
    if not user:
        return jsonify({"erro": "Usuário não encontrado"}), 404

    codigo = user.gerar_codigo_ativacao()
    db.session.commit()

    log_action(caller_email, "PASSWORD_RESET", entidade=user.email, ip=get_client_ip())

    return jsonify({
        "mensagem": f"Senha de {user.email} resetada. Repasse o código de ativação.",
        "codigo_ativacao": codigo,
        "validade_dias":   User.ATIVACAO_VALIDADE_DIAS,
        "usuario":         user.to_dict(),
    }), 200
