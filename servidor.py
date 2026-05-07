"""
servidor.py — DocTrack v4.0 Enterprise Backend
"""
import os, sys, json, argparse, unicodedata, io, csv
from functools import wraps
from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, request, send_from_directory, send_file
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
EXCEL_PATH = os.path.join(BASE_DIR, "Lista_de_Documentos_IT_padronizada_1.xlsx")
DB_PATH    = os.path.join(BASE_DIR, "doctrack.db")

_database_url = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")
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
    SETORES, STATUS_PRE, STATUS_FABRICANTE, STATUS_PDE, STATUS_MAP, TIPOS_DOC_FABRICANTE, TIPOS_DOC_LABELS
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

def compute_kpis(docs):
    total = len(docs)
    por_setor = {s: 0 for s in SETORES}
    status_counts = {s: {} for s in SETORES}
    global_counts = {"Pendente": 0, "Em progresso": 0, "Finalizado": 0}
    
    for d in docs:
        setor = d.get("setor")
        if setor in por_setor:
            por_setor[setor] += 1
            st = d.get("status") or "Elaborar"
            status_counts[setor][st] = status_counts[setor].get(st, 0) + 1
        
        sg = d.get("status_global") or "Pendente"
        global_counts[sg] = global_counts.get(sg, 0) + 1

    fin = global_counts.get("Finalizado", 0)
    
    return {
        "total": total, 
        "finalizados": fin, 
        "em_progresso": global_counts.get("Em progresso", 0), 
        "pendentes": global_counts.get("Pendente", 0),
        "backlog": total - fin,
        "pct_concluidos": round(fin / total * 100, 1) if total else 0,
        "por_setor": por_setor,
        "status_counts": status_counts,
        "global_counts": global_counts,
    }

# ── INIT DB + SEED ────────────────────────────────────────────────────────────
def init_db(reset=False):
    with app.app_context():
        if reset:
            db.drop_all()
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
        if reset or Documento.query.count() == 0:
            if os.path.exists(EXCEL_PATH):
                _import_excel_to_db()
        print(f"\n[OK] Banco criado/atualizado em: {DB_PATH}")

def _import_excel_to_db():
    try:
        wb = pd.ExcelFile(EXCEL_PATH)
        docs_to_add = []
        
        # 1. PRE
        if "DOCs - Produção (PRE)" in wb.sheet_names:
            df_pre = pd.read_excel(wb, sheet_name="DOCs - Produção (PRE)", skiprows=2)
            for _, row in df_pre.iterrows():
                eq = str(row.get("Equipamento", "")).strip()
                if not eq or eq in ("nan", "None"): continue
                
                def s(col):
                    v = row.get(col, "")
                    return "" if str(v).strip() in ("nan", "None", "—") else str(v).strip()
                
                doc_nome = s("DOCUMENTOS - PRODUÇÃO (PRE) - ITs E CHECKLISTS")
                if not doc_nome: doc_nome = f"IT/Checklist - {eq}"
                
                dt_treino = row.get("Data Treinamento Piloto")
                dt_homol = row.get("Data Envio Homologação")
                
                docs_to_add.append(Documento(
                    setor="PRE",
                    equipamento=eq,
                    sku=s("SKU"),
                    codigo_doc=s("Código do Doc"),
                    documento=doc_nome,
                    responsavel=s("Responsável"),
                    status=s("Status") or "Elaborar",
                    data_treinamento=pd.to_datetime(dt_treino) if pd.notna(dt_treino) else None,
                    obs_treinamento=s("Obs. Treinamento Piloto"),
                    data_homologacao=pd.to_datetime(dt_homol) if pd.notna(dt_homol) else None,
                    obs_homologacao=s("Obs. Envio Homologação"),
                    armazenamento=s("Armazenamento - Pasta de Projetos")
                ))

        # 2. Fabricante
        if "DOCs - Fabricante" in wb.sheet_names:
            df_fab = pd.read_excel(wb, sheet_name="DOCs - Fabricante", skiprows=2)
            for _, row in df_fab.iterrows():
                eq = str(row.get("Equipamento", "")).strip()
                if not eq or eq in ("nan", "None"): continue
                
                def s(col):
                    v = row.get(col, "")
                    return "" if str(v).strip() in ("nan", "None", "—") else str(v).strip()

                sku = s("SKU")
                cod = s("Código do Doc")
                fab = s("Fabricante")
                armazenamento = s("Armazenamento - Pasta de Projetos")
                
                # Para cada tipo de documento na linha
                cols_tipos = {
                    "Manual de Serviço": "Manual_Servico",
                    "Manual do Usuário": "Manual_Usuario",
                    "QI/QO/QD": "QIQOQD",
                    "Spare Parts": "Spare_Parts"
                }
                for col_name, tipo_code in cols_tipos.items():
                    status_val = s(col_name)
                    if status_val:
                        docs_to_add.append(Documento(
                            setor="Fabricante",
                            equipamento=eq,
                            sku=sku,
                            codigo_doc=cod,
                            documento=f"{col_name} - {eq}",
                            fabricante=fab,
                            tipo_doc=tipo_code,
                            status=status_val,
                            armazenamento=armazenamento
                        ))

        # 3. PDE
        if "DOCs - P&D Equipamentos (PDE)" in wb.sheet_names:
            df_pde = pd.read_excel(wb, sheet_name="DOCs - P&D Equipamentos (PDE)", skiprows=2)
            for _, row in df_pde.iterrows():
                doc_nome = str(row.get("Documento", "")).strip()
                if not doc_nome or doc_nome in ("nan", "None"): continue
                
                def s(col):
                    v = row.get(col, "")
                    return "" if str(v).strip() in ("nan", "None", "—") else str(v).strip()

                docs_to_add.append(Documento(
                    setor="PDE",
                    equipamento="P&D (Processos)",
                    codigo_doc=s("Código do Doc"),
                    documento=doc_nome,
                    status=s("Status") or "Elaborar",
                    armazenamento=s("Armazenamento - Pasta de Projetos")
                ))

        # Soft delete existing docs se o schema estiver OK, ou drop/create se houver mudança.
        # Para forçar a atualização do banco em nuvem (Render), nós dropamos as tabelas e recriamos com as novas colunas.
        try:
            Responsavel.__table__.drop(db.engine, checkfirst=True)
            Documento.__table__.drop(db.engine, checkfirst=True)
            Documento.__table__.create(db.engine)
            Responsavel.__table__.create(db.engine)
        except Exception as e:
            print(f"Erro ao recriar tabelas: {e}")
            pass # fallback caso sqlite local reclame
            
        for d in docs_to_add:
            db.session.add(d)
            
        db.session.commit()
        print(f"[OK] Planilha importada com sucesso: {len(docs_to_add)} novos documentos.")
    except Exception as e:
        db.session.rollback()
        print(f"  Aviso: não foi possível importar Planilha — {e}")
        raise e

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
    q       = norm(request.args.get("q", ""))
    setor   = request.args.get("setor", "")
    
    query = Documento.query.filter(Documento.ativo == True)
    if setor: query = query.filter(Documento.setor == setor)
    
    docs = [d.to_dict() for d in query.order_by(Documento.equipamento).all()]
    if q:
        def matches(d):
            blob = " ".join(norm(str(d.get(f, ""))) for f in ("equipamento","documento","codigo_doc","sku","responsavel","armazenamento","tipo_doc","fabricante"))
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
    setor = data.get("setor")
    if setor not in SETORES:
        return jsonify({"erro": f"Setor inválido. Escolha entre {SETORES}"}), 400

    doc = Documento(
        setor=setor,
        equipamento=data.get("equipamento", ""),
        sku=data.get("sku", ""),
        codigo_doc=data.get("codigo_doc", ""),
        documento=data.get("documento", ""),
        responsavel=data.get("responsavel", ""),
        status=data.get("status", "Elaborar"),
        tipo_doc=data.get("tipo_doc", ""),
        fabricante=data.get("fabricante", ""),
        obs_treinamento=data.get("obs_treinamento", ""),
        obs_homologacao=data.get("obs_homologacao", ""),
        armazenamento=data.get("armazenamento", "")
    )
    
    if data.get("data_treinamento"):
        try: doc.data_treinamento = datetime.strptime(data["data_treinamento"], "%Y-%m-%d")
        except: pass
    if data.get("data_homologacao"):
        try: doc.data_homologacao = datetime.strptime(data["data_homologacao"], "%Y-%m-%d")
        except: pass

    db.session.add(doc); db.session.commit()
    log_action(caller, "CREATE", entidade=doc.documento, campo="setor", novo=setor, documento_id=doc.id, ip=get_client_ip())
    
    try:
        publish_event(EventType.DOCUMENT_CREATED,
            payload={"documento_id": doc.id, "documento": doc.to_dict(), "setor": doc.setor, "equipamento": doc.equipamento},
            user_email=caller, db=db, AuditLog=AuditLog, socketio=socketio)
    except Exception: pass
    return jsonify({"mensagem": "Documento criado", "documento": doc.to_dict()}), 201

@app.route("/api/documentos/<int:doc_id>", methods=["PATCH", "PUT"])
@jwt_required()
@require_role("admin", "gestor", "tecnico")
def update_documento(doc_id):
    caller = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    doc = Documento.query.filter(Documento.ativo == True, Documento.id == doc_id).first()
    if not doc: return jsonify({"erro": "Não encontrado"}), 404
    
    CAMPOS_STR = ["equipamento", "sku", "codigo_doc", "documento", "responsavel", "tipo_doc", "fabricante", "obs_treinamento", "obs_homologacao", "armazenamento"]
    
    for campo in CAMPOS_STR:
        if campo in data:
            antigo = getattr(doc, campo); novo = data[campo]
            if str(antigo) != str(novo):
                log_action(caller, "UPDATE", entidade=doc.documento, campo=campo, antigo=antigo, novo=novo, documento_id=doc.id, ip=get_client_ip())
                setattr(doc, campo, novo)
                
    if "data_treinamento" in data:
        try: 
            doc.data_treinamento = datetime.strptime(data["data_treinamento"], "%Y-%m-%d") if data["data_treinamento"] else None
        except: pass
    if "data_homologacao" in data:
        try: 
            doc.data_homologacao = datetime.strptime(data["data_homologacao"], "%Y-%m-%d") if data["data_homologacao"] else None
        except: pass

    doc.updated_em = datetime.now()
    doc.version = (doc.version or 0) + 1
    db.session.commit()
    try:
        publish_event(EventType.DOCUMENT_UPDATED,
            payload={"documento_id": doc.id, "documento": doc.to_dict(), "setor": doc.setor, "equipamento": doc.equipamento},
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
    nome = doc.documento
    doc.ativo = False; doc.deleted_at = datetime.now(); db.session.commit()
    log_action(caller, "DELETE", entidade=nome, campo="*", documento_id=doc.id, ip=get_client_ip())
    try:
        publish_event(EventType.DOCUMENT_DELETED,
            payload={"documento_id": doc_id, "setor": doc.setor, "equipamento": doc.equipamento},
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
    novo = data.get("status", "")
    expected_version = data.get("version")
    
    doc = Documento.query.filter(Documento.ativo == True, Documento.id == doc_id).first()
    if not doc: return jsonify({"erro": "Não encontrado"}), 404
    
    if expected_version is not None and doc.version != expected_version:
        return jsonify({"erro": "Documento alterado por outro usuário.", "current_version": doc.version, "documento": doc.to_dict()}), 409
        
    setor_status_list = STATUS_MAP.get(doc.setor, [])
    if novo not in setor_status_list:
        return jsonify({"erro": f"Status inválido para o setor {doc.setor}. Use: {', '.join(setor_status_list)}"}), 400

    antigo = doc.status
    doc.status = novo
    doc.updated_em = datetime.now()
    doc.version = (doc.version or 0) + 1
    db.session.commit()
    log_action(caller, "STATUS_CHANGE", entidade=doc.documento, campo="status", antigo=antigo, novo=novo, documento_id=doc.id, ip=get_client_ip())
    try:
        publish_event(EventType.DOCUMENT_STATUS_UPDATED,
            payload={"documento_id": doc.id, "old_value": antigo, "new_value": novo, "status_global": doc.status_global, "setor": doc.setor, "equipamento": doc.equipamento},
            user_email=caller, db=db, AuditLog=AuditLog, socketio=socketio)
    except Exception: pass
    return jsonify({"mensagem": f"Status atualizado", "documento": doc.to_dict()}), 200

# ── API — METRICS / ENUMS / AUDIT / EXPORT ───────────────────────────────────
@app.route("/api/metrics")
@jwt_required()
def api_metrics():
    docs = [d.to_dict() for d in Documento.query.filter(Documento.ativo == True).all()]
    return jsonify(compute_kpis(docs)), 200

@app.route("/api/enums")
@jwt_required()
def api_enums():
    return jsonify({
        "setores": SETORES, 
        "status_map": STATUS_MAP,
        "tipos_doc_fabricante": TIPOS_DOC_FABRICANTE,
        "tipos_doc_labels": TIPOS_DOC_LABELS
    }), 200

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

@app.route("/api/export/audit")
@jwt_required()
@require_role("admin", "gestor")
def export_audit():
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).all()
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['ID', 'Usuario', 'Acao', 'Entidade', 'Campo', 'Valor Antigo', 'Valor Novo', 'Data'])
    for log in logs:
        cw.writerow([
            log.id, 
            log.usuario_email, 
            log.acao, 
            log.entidade, 
            log.campo, 
            log.valor_antigo, 
            log.valor_novo, 
            log.timestamp.strftime("%d/%m/%Y %H:%M:%S") if log.timestamp else ""
        ])
    return send_file(
        io.BytesIO(si.getvalue().encode('utf-8-sig')),
        mimetype="text/csv",
        as_attachment=True,
        download_name="audit_log.csv"
    )

@app.route("/api/events/replay", methods=["GET"])
@jwt_required()
def replay_events():
    since = int(request.args.get("since", 0))
    events = get_events_since(since, db=db, AuditLog=AuditLog, limit=500)
    return jsonify(events)

import threading

def _run_import_bg():
    with app.app_context():
        try:
            _import_excel_to_db()
            print("Importação background finalizada com sucesso.")
        except Exception as e:
            print(f"Erro no import background: {e}")
            try:
                db.session.rollback()
            except:
                pass

@app.route("/api/reimport", methods=["POST"])
@jwt_required()
@require_role("admin", "gestor")
def api_reimport():
    if not os.path.exists(EXCEL_PATH): return jsonify({"erro": "Excel não encontrado"}), 404
    
    threading.Thread(target=_run_import_bg).start()
    return jsonify({"mensagem": "Sincronização iniciada. Os dados serão atualizados em instantes (aprox. 30 a 60 segundos). Recarregue a página para ver."}), 200

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
        if any(room.startswith(p) for p in ("setor:", "equipamento:", "doc:")):
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
    emit("pong_app", {"t": datetime.now().isoformat()})

# ── INIT PARA GUNICORN (produção) ─────────────────────────────────────────────
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
    print("  DocTrack v4.0 Enterprise — Sector Based + WebSocket")
    print("="*55)
    if args.init: init_db(reset=True)
    print(f"  Acesse: http://localhost:5000")
    print("="*55 + "\n")
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
