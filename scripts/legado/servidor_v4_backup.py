"""
servidor.py
===========
Orquestrador principal do DocTrack v4.

Stack: Flask 3 + Flask-SocketIO 5.6 + SQLAlchemy + JWT.

Modo async: 'threading' (sem eventlet/gevent). Adequado para até ~50
usuários simultâneos em dev local. Para produção on-premise:
    pip install eventlet
    socketio = SocketIO(app, async_mode="eventlet", ...)
    # E rodar com: eventlet.monkey_patch() no topo

Fluxo das mutações (REGRA DE OURO):

    POST /api/documentos/<id>
        |
        v
    valida + persiste no DB
        |
        v
    publish_event(...)
        |
        +--> AuditLog (event store)
        +--> socketio.emit() para rooms relevantes
"""

import os
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, jwt_required, get_jwt_identity,
    decode_token, create_access_token,
)
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect

from models import db, User, Documento, Responsavel, AuditLog, ResponsavelRole
from event_bus import publish_event, get_events_since, EventType


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DOCTRACK_DB", "sqlite:///doctrack.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = os.environ.get(
        "JWT_SECRET", "dev-secret-troque-em-prod"
    )
    app.config["SECRET_KEY"] = app.config["JWT_SECRET_KEY"]

    db.init_app(app)
    JWTManager(app)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    return app


app = create_app()
socketio = SocketIO(
    app,
    async_mode="threading",
    cors_allowed_origins="*",
    ping_interval=25,    # heartbeat a cada 25s
    ping_timeout=60,     # desconecta se cliente não responder em 60s
    logger=False,
    engineio_logger=False,
)


# ---------------------------------------------------------------------------
# Helper — pega user atual a partir do JWT (em rotas REST)
# ---------------------------------------------------------------------------
def current_user():
    identity = get_jwt_identity()
    if not identity:
        return None
    return User.query.get(identity)


def require_role(*roles):
    """Decorator que restringe rota a roles específicos."""
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user or user.role not in roles:
                return jsonify({"erro": "Permissão negada"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ===========================================================================
# AUTENTICAÇÃO (mínimo necessário — você já tem isso no auth.py)
# ===========================================================================
@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    user = User.query.filter_by(email=data.get("email", "").lower()).first()
    if not user or not user.check_password(data.get("senha", "")):
        return jsonify({"erro": "Credenciais inválidas"}), 401
    if not user.ativo:
        return jsonify({"erro": "Usuário inativo"}), 403

    user.ultimo_login = datetime.now(timezone.utc)
    db.session.commit()

    token = create_access_token(identity=user.id, additional_claims={
        "role": user.role, "email": user.email,
    })
    return jsonify({"token": token, "user": user.to_dict()})


# ===========================================================================
# ROTAS REST — DOCUMENTOS (CRUD melhorado, prioridade #1)
# ===========================================================================
@app.route("/api/documentos", methods=["GET"])
@jwt_required()
def listar_documentos():
    """Listagem com filtros básicos."""
    q = Documento.query
    if request.args.get("origem"):
        q = q.filter_by(origem=request.args["origem"])
    if request.args.get("equipamento"):
        q = q.filter_by(equipamento=request.args["equipamento"])

    docs = q.order_by(Documento.atualizado_em.desc()).all()
    return jsonify([d.snapshot() for d in docs])


@app.route("/api/documentos/<int:doc_id>", methods=["GET"])
@jwt_required()
def obter_documento(doc_id):
    doc = Documento.query.get_or_404(doc_id)
    return jsonify(doc.snapshot())


@app.route("/api/documentos", methods=["POST"])
@require_role("admin", "gestor")
def criar_documento():
    user = current_user()
    data = request.get_json() or {}

    doc = Documento(
        equipamento=data.get("equipamento"),
        origem=data.get("origem"),
        titulo=data.get("titulo"),
        descricao=data.get("descricao"),
        prazo=datetime.fromisoformat(data["prazo"]) if data.get("prazo") else None,
    )
    db.session.add(doc)
    db.session.commit()

    publish_event(
        EventType.DOCUMENT_CREATED,
        payload={
            "documento_id": doc.id,
            "documento": doc.snapshot(),
            "origem": doc.origem,
            "equipamento": doc.equipamento,
            "new_value": doc.snapshot(),
        },
        user_id=user.id, user_email=user.email,
        db=db, AuditLog=AuditLog, socketio=socketio,
    )

    return jsonify(doc.snapshot()), 201


@app.route("/api/documentos/<int:doc_id>", methods=["PUT"])
@require_role("admin", "gestor", "tecnico")
def atualizar_documento(doc_id):
    """
    Atualização granular. Suporta:
      - Edição de campos comuns (titulo, descricao, equipamento, prazo)
      - Edição de etapas (etapa_elaboracao, etapa_revisao1, ...)
      - Versionamento otimista via campo 'versao'

    Cada campo alterado pode gerar um evento específico.
    """
    user = current_user()
    doc = Documento.query.get_or_404(doc_id)
    data = request.get_json() or {}

    # ---- versionamento otimista ----
    versao_cliente = data.get("versao")
    if versao_cliente is not None and versao_cliente != doc.versao:
        return jsonify({
            "erro": "Conflito de versão. Outro usuário editou este documento.",
            "versao_atual": doc.versao,
            "documento": doc.snapshot(),
        }), 409

    snapshot_antes = doc.snapshot()

    # ---- aplica mudanças ----
    campos_simples = ["equipamento", "origem", "titulo", "descricao"]
    for c in campos_simples:
        if c in data:
            setattr(doc, c, data[c])

    if "prazo" in data:
        doc.prazo = datetime.fromisoformat(data["prazo"]) if data["prazo"] else None

    # Etapas — cada uma vira um evento próprio para granularidade
    etapas_alteradas = []
    for etapa in ["etapa_elaboracao", "etapa_revisao1",
                  "etapa_revisao2", "etapa_aprovacao"]:
        if etapa in data and data[etapa] != getattr(doc, etapa):
            old = getattr(doc, etapa)
            setattr(doc, etapa, data[etapa])
            etapas_alteradas.append((etapa, old, data[etapa]))

    doc.versao += 1
    doc.atualizado_em = datetime.now(timezone.utc)
    db.session.commit()

    # ---- emite eventos ----
    base_payload = {
        "documento_id": doc.id,
        "origem": doc.origem,
        "equipamento": doc.equipamento,
    }

    # Evento geral de update (sempre)
    publish_event(
        EventType.DOCUMENT_UPDATED,
        payload={
            **base_payload,
            "documento": doc.snapshot(),
            "diff": doc.diff(snapshot_antes),
            "old_value": snapshot_antes,
            "new_value": doc.snapshot(),
        },
        user_id=user.id, user_email=user.email,
        db=db, AuditLog=AuditLog, socketio=socketio,
    )

    # Eventos específicos por etapa (granular para a UI atualizar células)
    for etapa, old, new in etapas_alteradas:
        publish_event(
            EventType.DOCUMENT_STATUS_UPDATED,
            payload={
                **base_payload,
                "etapa": etapa,
                "old_value": old,
                "new_value": new,
                "status_global": doc.status_global,
            },
            user_id=user.id, user_email=user.email,
            db=db, AuditLog=AuditLog, socketio=socketio,
        )

        if new == "Concluído":
            publish_event(
                EventType.ETAPA_COMPLETED,
                payload={**base_payload, "etapa": etapa},
                user_id=user.id, user_email=user.email,
                db=db, AuditLog=AuditLog, socketio=socketio,
            )

    return jsonify(doc.snapshot())


@app.route("/api/documentos/<int:doc_id>", methods=["DELETE"])
@require_role("admin")
def deletar_documento(doc_id):
    user = current_user()
    doc = Documento.query.get_or_404(doc_id)
    snapshot = doc.snapshot()

    db.session.delete(doc)
    db.session.commit()

    publish_event(
        EventType.DOCUMENT_DELETED,
        payload={
            "documento_id": doc_id,
            "origem": snapshot["origem"],
            "equipamento": snapshot["equipamento"],
            "old_value": snapshot,
        },
        user_id=user.id, user_email=user.email,
        db=db, AuditLog=AuditLog, socketio=socketio,
    )

    return jsonify({"ok": True})


# ===========================================================================
# ROTAS REST — RESPONSÁVEIS (novidade do v4)
# ===========================================================================
@app.route("/api/documentos/<int:doc_id>/responsaveis", methods=["GET"])
@jwt_required()
def listar_responsaveis(doc_id):
    doc = Documento.query.get_or_404(doc_id)
    return jsonify([r.to_dict() for r in doc.responsaveis])


@app.route("/api/documentos/<int:doc_id>/responsaveis", methods=["POST"])
@require_role("admin", "gestor")
def atribuir_responsavel(doc_id):
    """
    Body: { "user_id": 5, "role": "revisor_1" }
    """
    user = current_user()
    doc = Documento.query.get_or_404(doc_id)
    data = request.get_json() or {}

    target_user_id = data.get("user_id")
    role = data.get("role")

    if not target_user_id or role not in ResponsavelRole.all():
        return jsonify({"erro": "user_id e role válidos são obrigatórios"}), 400

    target = User.query.get(target_user_id)
    if not target:
        return jsonify({"erro": "Usuário alvo não encontrado"}), 404

    # Idempotência — se já existe, retorna o existente
    existente = Responsavel.query.filter_by(
        documento_id=doc_id, user_id=target_user_id, role=role
    ).first()
    if existente:
        return jsonify(existente.to_dict()), 200

    resp = Responsavel(
        documento_id=doc_id,
        user_id=target_user_id,
        role=role,
        atribuido_por_id=user.id,
    )
    db.session.add(resp)
    db.session.commit()

    publish_event(
        EventType.RESPONSAVEL_ASSIGNED,
        payload={
            "documento_id": doc_id,
            "origem": doc.origem,
            "equipamento": doc.equipamento,
            "responsavel": resp.to_dict(),
            "target_user_id": target_user_id,
            "new_value": resp.to_dict(),
        },
        user_id=user.id, user_email=user.email,
        db=db, AuditLog=AuditLog, socketio=socketio,
    )

    # Notificação direta para o usuário atribuído
    publish_event(
        EventType.NOTIFICATION,
        payload={
            "target_user_id": target_user_id,
            "titulo": "Você foi atribuído como responsável",
            "mensagem": f"Documento #{doc_id} ({doc.titulo or doc.equipamento}) — papel: {role}",
            "documento_id": doc_id,
            "severidade": "info",
        },
        user_id=user.id, user_email=user.email,
        db=db, AuditLog=AuditLog, socketio=socketio,
    )

    return jsonify(resp.to_dict()), 201


@app.route("/api/documentos/<int:doc_id>/responsaveis/<int:resp_id>", methods=["DELETE"])
@require_role("admin", "gestor")
def remover_responsavel(doc_id, resp_id):
    user = current_user()
    resp = Responsavel.query.filter_by(id=resp_id, documento_id=doc_id).first_or_404()
    doc = resp.documento
    snapshot = resp.to_dict()

    db.session.delete(resp)
    db.session.commit()

    publish_event(
        EventType.RESPONSAVEL_REMOVED,
        payload={
            "documento_id": doc_id,
            "origem": doc.origem,
            "equipamento": doc.equipamento,
            "responsavel": snapshot,
            "old_value": snapshot,
        },
        user_id=user.id, user_email=user.email,
        db=db, AuditLog=AuditLog, socketio=socketio,
    )

    return jsonify({"ok": True})


# ===========================================================================
# ROTAS REST — AUDITORIA / REPLAY
# ===========================================================================
@app.route("/api/audit", methods=["GET"])
@require_role("admin", "gestor")
def listar_audit():
    limit = int(request.args.get("limit", 200))
    since = request.args.get("since_id")
    q = AuditLog.query
    if since:
        q = q.filter(AuditLog.id > int(since))
    rows = q.order_by(AuditLog.id.desc()).limit(limit).all()
    return jsonify([r.to_dict() for r in rows])


@app.route("/api/events/replay", methods=["GET"])
@jwt_required()
def replay_events():
    """
    Cliente passa ?since=<event_id> e recebe todos os eventos posteriores.
    Útil quando o socket reconecta após queda.
    """
    since = int(request.args.get("since", 0))
    events = get_events_since(since, db=db, AuditLog=AuditLog, limit=500)
    return jsonify(events)


# ===========================================================================
# WEBSOCKET — handshake, rooms e resiliência
# ===========================================================================
@socketio.on("connect")
def on_connect(auth):
    """
    Handshake autenticado. Cliente envia:
        socket = io({ auth: { token: '<JWT>' } })

    Validamos o JWT, extraímos user/role, e fazemos join nas rooms apropriadas.
    """
    token = (auth or {}).get("token") if auth else None
    if not token:
        emit("auth_error", {"erro": "Token ausente"})
        return False  # rejeita a conexão

    try:
        decoded = decode_token(token)
        user_id = decoded["sub"]
        user = User.query.get(user_id)
        if not user or not user.ativo:
            raise ValueError("Usuário inválido")
    except Exception as e:
        emit("auth_error", {"erro": f"Token inválido: {e}"})
        return False

    sid = request.sid

    # Rooms: por role, por user, e o cliente pode entrar em rooms de
    # categoria/equipamento sob demanda via 'subscribe'
    join_room(f"role:{user.role}", sid=sid)
    join_room(f"user:{user.id}", sid=sid)

    # Guarda contexto na session do socket
    from flask import session
    session["user_id"] = user.id
    session["user_email"] = user.email
    session["user_role"] = user.role

    emit("connected", {
        "user": user.to_dict(),
        "rooms": [f"role:{user.role}", f"user:{user.id}"],
        "server_time": datetime.now(timezone.utc).isoformat(),
    })

    # Log de conexão (não vai pro broadcast, só audit)
    publish_event(
        EventType.USER_CONNECTED,
        payload={"sid": sid},
        user_id=user.id, user_email=user.email,
        db=db, AuditLog=AuditLog, socketio=socketio,
    )


@socketio.on("disconnect")
def on_disconnect(reason=None):
    from flask import session
    user_id = session.get("user_id")
    user_email = session.get("user_email")
    if user_id:
        publish_event(
            EventType.USER_DISCONNECTED,
            payload={"reason": str(reason) if reason else "unknown"},
            user_id=user_id, user_email=user_email,
            db=db, AuditLog=AuditLog, socketio=socketio,
        )


@socketio.on("subscribe")
def on_subscribe(data):
    """
    Cliente entra em rooms específicas (categoria, equipamento, doc).
    Útil quando abre a tela de um documento e quer receber só os updates dele.
    """
    from flask import session
    if not session.get("user_id"):
        return  # não autenticado

    rooms = data.get("rooms", [])
    permitidas = ("categoria:", "equipamento:", "doc:")

    for room in rooms:
        if any(room.startswith(p) for p in permitidas):
            join_room(room)

    emit("subscribed", {"rooms": rooms})


@socketio.on("unsubscribe")
def on_unsubscribe(data):
    rooms = data.get("rooms", [])
    for room in rooms:
        leave_room(room)
    emit("unsubscribed", {"rooms": rooms})


@socketio.on("replay_request")
def on_replay_request(data):
    """
    Cliente pede replay de eventos via socket (alternativa ao endpoint REST).
        socket.emit('replay_request', { since: 1234 })
    """
    since = int(data.get("since", 0))
    events = get_events_since(since, db=db, AuditLog=AuditLog, limit=500)
    emit("replay", {"since": since, "events": events, "count": len(events)})


@socketio.on("ping_app")
def on_ping(data):
    """Heartbeat customizado (Socket.IO já tem o seu próprio, isto é extra)."""
    emit("pong_app", {"t": datetime.now(timezone.utc).isoformat()})


# ===========================================================================
# BOOTSTRAP
# ===========================================================================
def init_db():
    with app.app_context():
        db.create_all()

        # Cria usuário admin padrão se não existir (apenas em dev)
        if not User.query.filter_by(email="admin@doctrack.local").first():
            admin = User(email="admin@doctrack.local", nome="Admin",
                         role="admin", ativo=True)
            admin.set_password("admin123")
            db.session.add(admin)
            db.session.commit()
            print(">> Admin padrão criado: admin@doctrack.local / admin123")


if __name__ == "__main__":
    init_db()
    print(">> DocTrack v4 rodando em http://0.0.0.0:5000")
    print(">> Modo async:", socketio.async_mode)
    socketio.run(app, host="0.0.0.0", port=5000, debug=True,
                 allow_unsafe_werkzeug=True)
