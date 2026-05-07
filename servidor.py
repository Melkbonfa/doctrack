"""
servidor.py — DocTrack v3.5 Enterprise Backend (v3 + WebSocket)
Local:  python servidor.py
        python servidor.py --init
Prod:   gunicorn --worker-class eventlet -w 1 servidor:app
Acesse: http://localhost:5000 (local) ou URL do Render (prod)
"""
import os, sys, json, argparse, unicodedata
from functools import wraps
from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, jwt_required, get_jwt_identity, get_jwt, decode_token
)
from flask_socketio import SocketIO, emit, join_room, leave_room
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# ── APP SETUP ─────────────────────────────────────────────────────────────────
app = Flask(__name__)

_jwt_secret = os.environ.get("JWT_SECRET")
if not _jwt_secret:
    raise RuntimeError("JWT_SECRET environment variable is required.")

_cors_origins = [
    o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()
]
CORS(app, origins=_cors_origins, supports_credentials=True)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
EXCEL_PATH = os.path.join(BASE_DIR, "Consolidado_Dashboard_Documentos.xlsx")
DB_PATH    = os.path.join(BASE_DIR, "doctrack.db")

# PostgreSQL em produção (Render injeta DATABASE_URL), SQLite local como fallback
_database_url = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")
# Render usa 'postgres://' mas SQLAlchemy precisa de 'postgresql://'
if _database_url.startswith("postgres://"):
    _database_url = _database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"]        = _database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"]      = {"pool_pre_ping": True}
app.config["JWT_SECRET_KEY"]                 = _jwt_secret
app.config["JWT_ACCESS_TOKEN_EXPIRES"]       = timedelta(hours=1)
app.config["JWT_REFRESH_TOKEN_EXPIRES"]      = timedelta(days=7)
app.config["SECRET_KEY"]                     = _jwt_secret

from models import (
    db, bcrypt, User, Documento, AuditLog, RevokedToken, Responsavel,
    ResponsavelRole, ETAPA_ORDER, ETAPA_STATUS, TIPOS_DOCUMENTO, SUBTIPOS_DOCUMENTO
)
from auth import auth_bp, log_action
from event_bus import publish_event, get_events_since, EventType

db.init_app(app)
bcrypt.init_app(app)
jwt = JWTManager(app)
app.register_blueprint(auth_bp)

# ── SOCKETIO ──────────────────────────────────────────────────────────────────
socketio = SocketIO(
    app,
    async_mode="threading",
    cors_allowed_origins="*",
    ping_interval=25,
    ping_timeout=60,
    logger=False,
    engineio_logger=False,
)

# ── JWT HOOKS ─────────────────────────────────────────────────────────────────
@jwt.additional_claims_loader
def add_claims(identity):
    with app.app_context():
        user = User.query.filter_by(email=identity).first()
        if user:
            return {"role": user.role, "nome": user.nome}
    return {}

@jwt.token_in_blocklist_loader
def check_revoked(jwt_header, jwt_payload):
    jti = jwt_payload.get("jti")
    if not jti:
        return False
    return db.session.query(RevokedToken.id).filter_by(jti=jti).first() is not None

# ── HELPERS ───────────────────────────────────────────────────────────────────
def require_role(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            claims = get_jwt()
            if claims.get("role", "") not in roles:
                return jsonify({"erro": "Acesso negado"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return deco

def norm(s):
    if s is None: return ""
    s = str(s).strip().lower()
    return unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode("ASCII")

def get_client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "")

def infer_tipo_subtipo(categoria, origem, documento_nome):
    cat = (categoria or "").lower()
    doc = (documento_nome or "").lower()
    if "qualidade" in cat or "pop" in cat or "qiqoqd" in cat: tipo = "Qualidade"
    elif "p&d" in cat or "engenharia" in cat: tipo = "Engenharia"
    else: tipo = "Técnico"
    if "manual" in doc and "usuario" in doc: subtipo = "Manual_Usuario"
    elif "manual" in doc and "servico" in doc: subtipo = "Manual_Servico"
    elif "manual" in doc: subtipo = "Manual"
    elif "pop" in cat or "pop" in doc: subtipo = "POP"
    elif "qiqoqd" in cat: subtipo = "QIQOQD"
    elif "p&d" in cat or "p&d" in doc: subtipo = "P&D"
    else: subtipo = "IT"
    return tipo, subtipo

def compute_kpis(docs):
    total = len(docs)
    status_counts, cat_counts, origem_counts, global_counts = {}, {}, {}, {}
    por_tipo, por_subtipo = {}, {}
    etapas_done = {"elaboracao": 0, "revisao1": 0, "diagramacao": 0, "revisao2": 0}
    etapas_breakdown = {k: {"Pendente": 0, "Em andamento": 0, "Concluído": 0}
                        for k in ("elaboracao", "revisao1", "diagramacao", "revisao2")}
    field_to_key = [("etapa_elaboracao","elaboracao"),("etapa_revisao1","revisao1"),
                    ("etapa_diagramacao","diagramacao"),("etapa_revisao2","revisao2")]
    for d in docs:
        s = d.get("status_principal") or ""
        if s: status_counts[s] = status_counts.get(s, 0) + 1
        c = d.get("categoria") or ""
        if c: cat_counts[c] = cat_counts.get(c, 0) + 1
        o = d.get("origem") or ""
        if o: origem_counts[o] = origem_counts.get(o, 0) + 1
        sg = d.get("status_global") or "Pendente"
        global_counts[sg] = global_counts.get(sg, 0) + 1
        t = d.get("tipo_documento") or "Não classificado"
        por_tipo[t] = por_tipo.get(t, 0) + 1
        st = d.get("subtipo") or "Não classificado"
        por_subtipo[st] = por_subtipo.get(st, 0) + 1
        for field, key in field_to_key:
            val = d.get(field) or "Pendente"
            if val == "Concluído": etapas_done[key] += 1
            if val in etapas_breakdown[key]: etapas_breakdown[key][val] += 1
    fin = global_counts.get("Finalizado", 0)
    emp = global_counts.get("Em progresso", 0)
    pen = global_counts.get("Pendente", 0)
    return {
        "total": total, "finalizados": fin, "em_progresso": emp, "pendentes": pen,
        "backlog": total - fin,
        "pct_concluidos": round(fin / total * 100, 1) if total else 0,
        "pct_versao": round(sum(1 for d in docs if d.get("versao")) / total * 100, 1) if total else 0,
        "pct_local": round(sum(1 for d in docs if d.get("local")) / total * 100, 1) if total else 0,
        "status_counts": status_counts, "cat_counts": cat_counts,
        "origem_counts": origem_counts, "global_counts": global_counts,
        "por_tipo": por_tipo, "por_subtipo": por_subtipo,
        "etapas": etapas_done, "etapas_breakdown": etapas_breakdown,
    }

# ── INIT DB + SEED ────────────────────────────────────────────────────────────
def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(email="admin@pde.com").first():
            admin = User(nome="Admin Sistemas", email="admin@pde.com", role="admin")
            admin.set_senha("admin123")
            db.session.add(admin)
        demo_users = [
            ("Carlos Mota","carlos.m@pde.com","gestor","demo123"),
            ("Beatriz Souza","beatriz.s@pde.com","gestor","demo123"),
            ("Ana Lima","ana.l@pde.com","tecnico","demo123"),
            ("Diego Ferreira","diego.f@pde.com","tecnico","demo123"),
            ("Auditora Ext.","auditora@iso.com","leitura","demo123"),
        ]
        for nome, email, role, senha in demo_users:
            if not User.query.filter_by(email=email).first():
                u = User(nome=nome, email=email, role=role)
                u.set_senha(senha)
                db.session.add(u)
        db.session.commit()
        if Documento.query.count() == 0 and os.path.exists(EXCEL_PATH):
            _import_excel_to_db()
        print(f"\n[OK] Banco criado/atualizado em: {DB_PATH}")

def _import_excel_to_db():
    try:
        df = pd.read_excel(EXCEL_PATH, sheet_name="Base_Consolidada")
        df.columns = [str(c).strip() for c in df.columns]
        df = df.dropna(subset=["Equipamento"])
        existing = {(d.equipamento, d.documento): d for d in Documento.query.all()}
        keys_in_excel, inserted, updated = set(), 0, 0
        for _, row in df.iterrows():
            eq = str(row.get("Equipamento", "")).strip()
            if not eq or eq in ("nan", "None"): continue
            def s(col):
                v = row.get(col, "")
                return "" if str(v).strip() in ("nan", "None", "—") else str(v).strip()
            categoria, origem, doc_nome = s("Categoria"), s("Origem"), s("Documento")
            tipo, subtipo = infer_tipo_subtipo(categoria, origem, doc_nome)
            payload = dict(
                origem=origem, categoria=categoria, documento=doc_nome, equipamento=eq,
                versao=s("Versao"), status_principal=s("Status_Principal"),
                etapa_elaboracao=s("Etapa_Elaboracao") or "Pendente",
                etapa_revisao1=s("Etapa_Revisao1") or "Pendente",
                etapa_diagramacao=s("Etapa_Diagramacao") or "Pendente",
                etapa_revisao2=s("Etapa_Revisao2") or "Pendente",
                local=s("Local"), tipo_documento=tipo, subtipo=subtipo,
            )
            key = (eq, doc_nome)
            keys_in_excel.add(key)
            if key in existing:
                doc = existing[key]
                for k, v in payload.items(): setattr(doc, k, v)
                doc.ativo = True; doc.deleted_at = None; updated += 1
            else:
                db.session.add(Documento(**payload)); inserted += 1
        now = datetime.utcnow()
        soft_deleted = 0
        for key, doc in existing.items():
            if key not in keys_in_excel and doc.ativo:
                doc.ativo = False; doc.deleted_at = now; soft_deleted += 1
        db.session.commit()
        print(f"[OK] Excel importado: {inserted} novos, {updated} atualizados, {soft_deleted} soft-deleted")
    except Exception as e:
        print(f"  Aviso: não foi possível importar Excel — {e}")

# ── PÁGINAS ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("dashboard.html")

@app.route("/socket-client.js")
def serve_socket_client():
    return send_from_directory(BASE_DIR, "socket-client.js")

@app.route("/app-realtime.js")
def serve_app_realtime():
    return send_from_directory(BASE_DIR, "app-realtime.js")

# ── API — DADOS ───────────────────────────────────────────────────────────────
@app.route("/api/data")
@jwt_required()
def api_data():
    docs = [d.to_dict() for d in Documento.query.filter(Documento.ativo == True).order_by(Documento.equipamento).all()]
    return jsonify({"updated_at": datetime.now().strftime("%d/%m/%Y %H:%M"), "items": docs, "kpis": compute_kpis(docs)}), 200

# ── API — CRUD DOCUMENTOS ────────────────────────────────────────────────────
@app.route("/api/documentos")
@jwt_required()
def api_documentos():
    q          = norm(request.args.get("q", ""))
    status_g   = request.args.get("status_global", "")
    categoria  = request.args.get("categoria", "")
    origem     = request.args.get("origem", "")
    tipo       = request.args.get("tipo_documento", "")
    subtipo    = request.args.get("subtipo", "")
    equip      = request.args.get("equipamento", "")
    query = Documento.query.filter(Documento.ativo == True)
    if categoria: query = query.filter(Documento.categoria == categoria)
    if origem:    query = query.filter(Documento.origem == origem)
    if tipo:      query = query.filter(Documento.tipo_documento == tipo)
    if subtipo:   query = query.filter(Documento.subtipo == subtipo)
    if equip:     query = query.filter(Documento.equipamento == equip)
    docs = [d.to_dict() for d in query.order_by(Documento.equipamento).all()]
    if status_g: docs = [d for d in docs if d.get("status_global") == status_g]
    if q:
        def matches(d):
            blob = " ".join(norm(d.get(f, "")) for f in ("equipamento","documento","categoria","origem","tipo_documento","subtipo","versao","local"))
            return q in blob
        docs = [d for d in docs if matches(d)]
    return jsonify(docs), 200

@app.route("/api/documentos/<int:doc_id>", methods=["GET"])
@jwt_required()
def get_documento(doc_id):
    doc = Documento.query.filter(Documento.ativo == True, Documento.id == doc_id).first()
    if not doc: return jsonify({"erro": "Não encontrado"}), 404
    return jsonify(doc.to_dict()), 200

@app.route("/api/documentos", methods=["POST"])
@jwt_required()
@require_role("admin", "gestor", "tecnico")
def create_documento():
    caller = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    if not data.get("equipamento"):
        return jsonify({"erro": "Campo 'equipamento' é obrigatório"}), 400
    doc = Documento(
        origem=data.get("origem",""), categoria=data.get("categoria",""),
        documento=data.get("documento",""), equipamento=data.get("equipamento",""),
        versao=data.get("versao",""), status_principal=data.get("status_principal",""),
        etapa_elaboracao=data.get("etapa_elaboracao","Pendente"),
        etapa_revisao1=data.get("etapa_revisao1","Pendente"),
        etapa_diagramacao=data.get("etapa_diagramacao","Pendente"),
        etapa_revisao2=data.get("etapa_revisao2","Pendente"),
        local=data.get("local",""),
        tipo_documento=data.get("tipo_documento",""), subtipo=data.get("subtipo",""),
    )
    db.session.add(doc); db.session.commit()
    log_action(caller, "CREATE", entidade=doc.equipamento, campo="documento",
               novo=doc.documento, documento_id=doc.id, ip=get_client_ip())
    # WebSocket broadcast
    try:
        publish_event(EventType.DOCUMENT_CREATED,
            payload={"documento_id": doc.id, "documento": doc.to_dict(),
                     "origem": doc.origem, "equipamento": doc.equipamento},
            user_email=caller, db=db, AuditLog=AuditLog, socketio=socketio)
    except Exception: pass
    return jsonify({"mensagem": "Documento criado", "documento": doc.to_dict()}), 201

ENUM_VALIDATORS = {
    "etapa_elaboracao": ETAPA_STATUS, "etapa_revisao1": ETAPA_STATUS,
    "etapa_diagramacao": ETAPA_STATUS, "etapa_revisao2": ETAPA_STATUS,
    "tipo_documento": TIPOS_DOCUMENTO, "subtipo": SUBTIPOS_DOCUMENTO,
}

@app.route("/api/documentos/<int:doc_id>", methods=["PATCH", "PUT"])
@jwt_required()
@require_role("admin", "gestor", "tecnico")
def update_documento(doc_id):
    caller = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    doc = Documento.query.filter(Documento.ativo == True, Documento.id == doc_id).first()
    if not doc: return jsonify({"erro": "Não encontrado"}), 404
    for campo, allowed in ENUM_VALIDATORS.items():
        if campo in data and data[campo] and data[campo] not in allowed:
            return jsonify({"erro": f"Valor inválido para '{campo}'", "valores_validos": list(allowed)}), 400
    CAMPOS = ["origem","categoria","documento","equipamento","versao","status_principal",
              "etapa_elaboracao","etapa_revisao1","etapa_diagramacao","etapa_revisao2",
              "local","tipo_documento","subtipo"]
    snapshot_antes = doc.to_dict()
    for campo in CAMPOS:
        if campo in data:
            antigo = getattr(doc, campo); novo = data[campo]
            if str(antigo) != str(novo):
                log_action(caller, "UPDATE", entidade=doc.equipamento, campo=campo,
                           antigo=antigo, novo=novo, documento_id=doc.id, ip=get_client_ip())
                setattr(doc, campo, novo)
    doc.updated_em = datetime.utcnow()
    doc.version = (doc.version or 0) + 1
    db.session.commit()
    try:
        publish_event(EventType.DOCUMENT_UPDATED,
            payload={"documento_id": doc.id, "documento": doc.to_dict(),
                     "origem": doc.origem, "equipamento": doc.equipamento},
            user_email=caller, db=db, AuditLog=AuditLog, socketio=socketio)
    except Exception: pass
    return jsonify({"mensagem": "Documento atualizado", "documento": doc.to_dict()}), 200

@app.route("/api/documentos/<int:doc_id>", methods=["DELETE"])
@jwt_required()
@require_role("admin", "gestor")
def delete_documento(doc_id):
    caller = get_jwt_identity()
    doc = Documento.query.filter(Documento.ativo == True, Documento.id == doc_id).first()
    if not doc: return jsonify({"erro": "Não encontrado"}), 404
    nome = doc.equipamento
    doc.ativo = False; doc.deleted_at = datetime.utcnow(); db.session.commit()
    log_action(caller, "DELETE", entidade=nome, campo="*", documento_id=doc.id, ip=get_client_ip())
    try:
        publish_event(EventType.DOCUMENT_DELETED,
            payload={"documento_id": doc_id, "origem": doc.origem, "equipamento": nome},
            user_email=caller, db=db, AuditLog=AuditLog, socketio=socketio)
    except Exception: pass
    return jsonify({"mensagem": f"Documento '{nome}' excluído"}), 200

# ── API — STATUS FLOW ─────────────────────────────────────────────────────────
@app.route("/api/documento/<int:doc_id>/status", methods=["PUT"])
@jwt_required()
@require_role("admin", "gestor", "tecnico")
def update_status(doc_id):
    caller = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    etapa, novo = data.get("etapa",""), data.get("status","")
    expected_version = data.get("version")
    if etapa not in ETAPA_ORDER:
        return jsonify({"erro": f"Etapa inválida. Use: {', '.join(ETAPA_ORDER)}"}), 400
    if novo not in ETAPA_STATUS:
        return jsonify({"erro": f"Status inválido. Use: {', '.join(ETAPA_STATUS)}"}), 400
    doc = Documento.query.filter(Documento.ativo == True, Documento.id == doc_id).first()
    if not doc: return jsonify({"erro": "Não encontrado"}), 404
    if expected_version is not None and doc.version != expected_version:
        return jsonify({"erro": "Documento alterado por outro usuário.", "current_version": doc.version, "documento": doc.to_dict()}), 409
    idx = ETAPA_ORDER.index(etapa)
    if idx > 0 and novo in ("Em andamento", "Concluído"):
        etapa_ant = ETAPA_ORDER[idx - 1]
        val_ant = getattr(doc, etapa_ant) or "Pendente"
        if val_ant != "Concluído":
            return jsonify({"erro": f"Etapa anterior precisa estar concluída primeiro.", "etapa_bloqueante": etapa_ant, "status_etapa_anterior": val_ant}), 400
    antigo = getattr(doc, etapa) or "Pendente"
    setattr(doc, etapa, novo)
    doc.updated_em = datetime.utcnow()
    doc.version = (doc.version or 0) + 1
    db.session.commit()
    log_action(caller, "STATUS_CHANGE", entidade=doc.equipamento, campo=etapa, antigo=antigo, novo=novo, documento_id=doc.id, ip=get_client_ip())
    try:
        publish_event(EventType.DOCUMENT_STATUS_UPDATED,
            payload={"documento_id": doc.id, "etapa": etapa, "old_value": antigo,
                     "new_value": novo, "status_global": doc.status_global,
                     "origem": doc.origem, "equipamento": doc.equipamento},
            user_email=caller, db=db, AuditLog=AuditLog, socketio=socketio)
    except Exception: pass
    return jsonify({"mensagem": f"Status de '{etapa}' atualizado", "documento": doc.to_dict()}), 200

# ── API — METRICS / ENUMS / AUDIT ────────────────────────────────────────────
@app.route("/api/metrics")
@jwt_required()
def api_metrics():
    docs = [d.to_dict() for d in Documento.query.filter(Documento.ativo == True).all()]
    return jsonify(compute_kpis(docs)), 200

@app.route("/api/enums")
@jwt_required()
def api_enums():
    return jsonify({"tipos_documento": TIPOS_DOCUMENTO, "subtipos": SUBTIPOS_DOCUMENTO,
                    "etapa_status": ETAPA_STATUS, "etapa_order": ETAPA_ORDER}), 200

@app.route("/api/audit")
@jwt_required()
@require_role("admin", "gestor")
def api_audit():
    q = norm(request.args.get("q", ""))
    acao = request.args.get("acao", "")
    try: limit = max(1, min(int(request.args.get("limit", 200)), 1000))
    except: return jsonify({"erro": "limit deve ser numérico"}), 400
    query = AuditLog.query.order_by(AuditLog.timestamp.desc())
    if acao: query = query.filter(AuditLog.acao == acao)
    result = [l.to_dict() for l in query.limit(limit).all()]
    if q: result = [l for l in result if q in norm(l.get("usuario")) or q in norm(l.get("entidade")) or q in norm(l.get("campo"))]
    return jsonify(result), 200

@app.route("/api/events/replay", methods=["GET"])
@jwt_required()
def replay_events():
    since = int(request.args.get("since", 0))
    events = get_events_since(since, db=db, AuditLog=AuditLog, limit=500)
    return jsonify(events)

# ── API — REIMPORT / STATUS ───────────────────────────────────────────────────
@app.route("/api/reimport", methods=["POST"])
@jwt_required()
@require_role("admin")
def api_reimport():
    if not os.path.exists(EXCEL_PATH): return jsonify({"erro": "Excel não encontrado"}), 404
    _import_excel_to_db()
    count = Documento.query.filter(Documento.ativo == True).count()
    return jsonify({"mensagem": f"{count} documentos ativos após reimport"}), 200

@app.route("/api/status")
def api_status():
    exists = os.path.exists(EXCEL_PATH)
    mtime = datetime.fromtimestamp(os.path.getmtime(EXCEL_PATH)).strftime("%d/%m/%Y %H:%M") if exists else ""
    return jsonify({"excel_found": exists, "excel_path": EXCEL_PATH, "excel_modified": mtime,
                    "db_path": DB_PATH, "usuarios": User.query.count(),
                    "documentos": Documento.query.filter(Documento.ativo == True).count()}), 200

# ── WEBSOCKET HANDLERS ────────────────────────────────────────────────────────
@socketio.on("connect")
def on_connect(auth=None):
    token = (auth or {}).get("token") if auth else None
    if not token:
        emit("auth_error", {"erro": "Token ausente"})
        return False
    try:
        decoded = decode_token(token)
        identity = decoded["sub"]
        user = User.query.filter_by(email=identity).first()
        if not user or not user.ativo: raise ValueError("Inválido")
    except Exception as e:
        emit("auth_error", {"erro": f"Token inválido: {e}"})
        return False
    from flask import session
    session["user_id"] = user.id
    session["user_email"] = user.email
    session["user_role"] = user.role
    join_room(f"role:{user.role}")
    join_room(f"user:{user.id}")
    emit("connected", {"user": user.to_dict(), "rooms": [f"role:{user.role}", f"user:{user.id}"]})

@socketio.on("disconnect")
def on_disconnect(reason=None):
    pass

@socketio.on("subscribe")
def on_subscribe(data):
    from flask import session
    if not session.get("user_id"): return
    for room in data.get("rooms", []):
        if any(room.startswith(p) for p in ("categoria:", "equipamento:", "doc:")):
            join_room(room)
    emit("subscribed", {"rooms": data.get("rooms", [])})

@socketio.on("unsubscribe")
def on_unsubscribe(data):
    for room in data.get("rooms", []):
        leave_room(room)

@socketio.on("replay_request")
def on_replay_request(data):
    since = int(data.get("since", 0))
    events = get_events_since(since, db=db, AuditLog=AuditLog, limit=500)
    emit("replay", {"since": since, "events": events, "count": len(events)})

@socketio.on("ping_app")
def on_ping(data):
    emit("pong_app", {"t": datetime.utcnow().isoformat()})

# ── INIT PARA GUNICORN (produção) ─────────────────────────────────────────────
# Gunicorn importa 'servidor:app', então precisamos inicializar aqui
with app.app_context():
    db.create_all()
    if User.query.count() == 0:
        init_db()

# ── MAIN (desenvolvimento local) ─────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true")
    args = parser.parse_args()
    print("\n" + "="*55)
    print("  DocTrack v3.5 Enterprise — WebSocket Enabled")
    print("="*55)
    if args.init: init_db()
    print(f"  Acesse: http://localhost:5000")
    print("="*55 + "\n")
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
