"""
servidor.py — DocTrack v4.0 Enterprise Backend
"""
import os, sys, json, argparse, io, csv, zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, request, send_from_directory, send_file
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, jwt_required, get_jwt_identity, get_jwt, decode_token
)
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

# ── CAMINHOS (compatível com PyInstaller / executável "congelado") ─────────────
# ASSET_DIR: assets somente-leitura (templates, static, js/html da raiz, files/)
# RUN_DIR  : pasta gravável ao lado do .exe (banco doctrack.db, .env, planilha)
if getattr(sys, "frozen", False):
    ASSET_DIR = sys._MEIPASS
    RUN_DIR   = os.path.dirname(sys.executable)
else:
    ASSET_DIR = os.path.dirname(os.path.abspath(__file__))
    RUN_DIR   = ASSET_DIR

load_dotenv(os.path.join(RUN_DIR, ".env"))

# ── APP SETUP ─────────────────────────────────────────────────────────────────
app = Flask(__name__,
            template_folder=os.path.join(ASSET_DIR, "templates"),
            static_folder=os.path.join(ASSET_DIR, "static"))

_jwt_secret = os.environ.get("JWT_SECRET")
if not _jwt_secret:
    raise RuntimeError("JWT_SECRET environment variable is required.")

_cors_origins = [
    o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()
]
# origins="*" + supports_credentials=True é uma combinação inválida: o navegador
# rejeita `Access-Control-Allow-Origin: *` em requisições com credenciais, e o
# flask-cors passa a refletir a origem recebida — o pior dos dois mundos. Só
# habilita credenciais quando há uma allowlist real configurada em CORS_ORIGINS.
_allow_all_origins = _cors_origins == ["*"]
CORS(app, origins=_cors_origins, supports_credentials=not _allow_all_origins)

# Confiança em cabeçalhos de proxy (X-Forwarded-For/-Proto) só quando o app está
# atrás de um proxy reverso conhecido (IIS/nginx). Sem isso, X-Forwarded-For é
# forjável pelo cliente — e esse IP vai para o audit log. Habilite com TRUST_PROXY=1.
if os.environ.get("TRUST_PROXY", "").lower() in ("true", "1", "t"):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

BASE_DIR   = ASSET_DIR                                   # assets de leitura (js/html da raiz, files/)
# Planilha legada de seed: procura em data/ (layout do repositório) e na raiz
# (layout do .exe empacotado, onde fica ao lado do executável).
EXCEL_PATH = os.path.join(RUN_DIR, "data", "Lista_de_Documentos_IT_padronizada_1.xlsx")
if not os.path.exists(EXCEL_PATH):
    EXCEL_PATH = os.path.join(RUN_DIR, "Lista_de_Documentos_IT_padronizada_1.xlsx")
DB_PATH    = os.path.join(RUN_DIR, "doctrack.db")

# Versão da aplicação (lida do arquivo VERSION na raiz). Exposta em /api/version.
try:
    with open(os.path.join(ASSET_DIR, "VERSION"), encoding="utf-8") as _vf:
        APP_VERSION = _vf.read().strip()
except Exception:
    APP_VERSION = "dev"

_database_url = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")
if _database_url.startswith("postgres://"):
    _database_url = _database_url.replace("postgres://", "postgresql://", 1)

_flask_debug = os.environ.get("FLASK_DEBUG", "False").lower() in ("true", "1", "t")

app.config["SQLALCHEMY_DATABASE_URI"]        = _database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
# Só recarrega templates a cada request em desenvolvimento; em produção o
# custo de checar o mtime de cada template por requisição é desnecessário.
app.config["TEMPLATES_AUTO_RELOAD"]          = _flask_debug
app.config["SQLALCHEMY_ENGINE_OPTIONS"]      = {"pool_pre_ping": True}
app.config["JWT_SECRET_KEY"]                 = _jwt_secret
app.config["JWT_ACCESS_TOKEN_EXPIRES"]       = timedelta(hours=1)
app.config["JWT_REFRESH_TOKEN_EXPIRES"]      = timedelta(days=7)
app.config["SECRET_KEY"]                     = _jwt_secret
app.config["JWT_TOKEN_LOCATION"]             = ["headers", "query_string"]
app.config["JWT_QUERY_STRING_NAME"]          = "token"

from models import (
    db, bcrypt, User, Documento, Equipamento, AuditLog, RevokedToken, Responsavel,
    CategoriaEquipamento, FamiliaEquipamento, LinhaProduto, EquipamentoItem, ITEM_TIPOS,
    Consumivel, TipoConsumivel, ConsumivelEquipamento, FORNECIMENTO, TIPOS_CONSUMIVEL_SEED,
    SETORES, STATUS_PRE, STATUS_FABRICANTE, STATUS_MAP,
    TIPOS_DOC_PRE, TIPOS_DOC_FABRICANTE, TIPOS_DOC_TODOS, SETOR_DO_TIPO,
    TIPOS_DOC_LABELS, ESTADOS_REVISAO
)
from auth import auth_bp, log_action, require_role, get_client_ip
from event_bus import publish_event, get_events_since, EventType
from utils import norm, norm_sku

db.init_app(app)
bcrypt.init_app(app)
jwt = JWTManager(app)
app.register_blueprint(auth_bp)

from entregaveis import entregaveis_bp, init_realtime as entregaveis_init_realtime
app.register_blueprint(entregaveis_bp)

# Módulo Documentos — CRUD de documentos + acesso a arquivos do equipamento.
from documentos import documentos_bp, init_realtime as documentos_init_realtime
app.register_blueprint(documentos_bp)

# Módulo PDR (P&D de reagentes) — montado sob /pdr, usa o mesmo db/login/auditoria.
from pdr import pdr_bp, init_realtime as pdr_init_realtime
app.register_blueprint(pdr_bp)

# Módulo Missões — kanban nativo (tipo Planner) da área PDE.
from missoes import missoes_bp, init_realtime as missoes_init_realtime
app.register_blueprint(missoes_bp)

# ── SOCKETIO ──────────────────────────────────────────────────────────────────
socketio = SocketIO(
    app,
    async_mode="threading",
    cors_allowed_origins="*" if _allow_all_origins else _cors_origins,
    ping_interval=25,
    ping_timeout=60,
    logger=False,
    engineio_logger=False,
)

entregaveis_init_realtime(socketio, publish_event, AuditLog, EventType)
documentos_init_realtime(socketio, publish_event, AuditLog, EventType)
pdr_init_realtime(socketio, publish_event, AuditLog, EventType)
missoes_init_realtime(socketio, publish_event, AuditLog, EventType)

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

@app.after_request
def add_security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://cdn.socket.io; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self' ws: wss: http: https:;"
    )
    return response

# ── HELPERS ───────────────────────────────────────────────────────────────────
# require_role vem de auth.py (fonte única): já embute @jwt_required(), então não
# depende de o chamador lembrar de empilhá-lo — evita rota sem autenticação por
# esquecimento. Por isso as rotas com @require_role NÃO empilham @jwt_required()
# (seria verificação dupla); o decorator explícito fica só nas rotas sem restrição
# de perfil (apenas login exigido).

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
        import pandas as pd   # lazy: só necessário ao semear via Excel (não vai no .exe)
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
                    "Manuais ES": "Manual_ES",
                    "Manual ES": "Manual_ES",
                    "Manual de Serviço": "Manual_Servico",
                    "Manual do Usuário": "Manual_Usuario",
                    "QI/QO/QD": "QIQOQD",
                    "Spare Parts": "Spare_Parts"
                }
                for col_name, tipo_code in cols_tipos.items():
                    status_val = s(col_name)
                    if status_val:
                        docs_to_add.append(Documento(
                            setor="Manuais",
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

# ── PÁGINAS ───────────────────────────────────────────────────────────────────
def _static_version():
    """Token de cache-busting baseado no mtime dos estáticos (muda só quando o arquivo muda)."""
    try:
        files = ["static/app.js", "static/style.css"]
        latest = max(os.path.getmtime(os.path.join(BASE_DIR, f)) for f in files if os.path.exists(os.path.join(BASE_DIR, f)))
        return str(int(latest))
    except Exception:
        return "1"

@app.route("/")
def index():
    return render_template("dashboard.html", asset_v=_static_version())

@app.route("/projetos")
@app.route("/entregaveis")   # alias antigo, mantido para não quebrar links salvos
def entregaveis_page():
    return render_template("entregaveis.html", asset_v=_static_version())

@app.route("/equipamentos")
def equipamentos_page():
    # Módulo Equipamentos (área PDE). Acesso validado no front (token + áreas).
    return render_template("equipamentos.html", asset_v=_static_version())

@app.route("/missoes")
def missoes_page():
    # Módulo Missões (kanban da área PDE). Acesso real barrado nas APIs (técnico+).
    return render_template("missoes.html", asset_v=_static_version())

@app.route("/hub")
def hub_page():
    from areas import AREAS
    return render_template("hub.html", asset_v=_static_version(), areas=AREAS)

@app.route("/hub/<slug>")
def subhub_page(slug):
    # Sub-hub de uma área (ex.: /hub/pde → Documentos + Projetos). O acesso real
    # é validado no front (token + áreas do usuário) como no hub.
    from areas import AREAS, get_area
    area = get_area(slug)
    if not area:
        return render_template("hub.html", asset_v=_static_version(), areas=AREAS), 404
    return render_template("subhub.html", asset_v=_static_version(), area=area)

@app.route("/config")
@app.route("/configuracoes")   # alias amigável
def config_page():
    # Página servida a qualquer um; o acesso real é barrado no front (token + role)
    # e nas APIs (audit/users já exigem gestor+).
    from areas import AREAS
    return render_template("config.html", asset_v=_static_version(), areas=AREAS)

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

# ── API — EQUIPAMENTOS (entidade central) ────────────────────────────────────
@app.route("/api/equipamentos", methods=["GET"])
@jwt_required()
def api_equipamentos():
    q = norm(request.args.get("q", ""))
    query = Equipamento.query.filter(Equipamento.ativo == True)
    for campo, col in (("categoria_id", Equipamento.categoria_id),
                       ("familia_id", Equipamento.familia_id)):
        val = request.args.get(campo)
        if val:
            query = query.filter(col == int(val))
    if request.args.get("status"):
        query = query.filter(Equipamento.status == request.args.get("status"))
    bloq = request.args.get("bloqueado")
    if bloq in ("0", "false", "nao"):
        query = query.filter(Equipamento.bloqueado == False)
    elif bloq in ("1", "true", "sim"):
        query = query.filter(Equipamento.bloqueado == True)

    equips = [e.to_dict() for e in query.order_by(Equipamento.nome).all()]
    if q:
        def matches(e):
            blob = " ".join(norm(str(e.get(f, ""))) for f in
                            ("nome", "nome_original", "nome_tecnico", "sku", "sku_importacao",
                             "codigo_fabricante", "anvisa", "fabricante", "familia", "categoria"))
            return q in blob
        equips = [e for e in equips if matches(e)]
    return jsonify(equips), 200

@app.route("/api/equipamentos/<int:equip_id>", methods=["GET"])
@jwt_required()
def get_equipamento(equip_id):
    equip = Equipamento.query.filter(Equipamento.ativo == True, Equipamento.id == equip_id).first()
    if not equip:
        return jsonify({"erro": "Equipamento não encontrado"}), 404
    d = equip.to_dict()
    d["docs_count"] = Documento.query.filter(Documento.ativo == True, Documento.equipamento_id == equip.id).count()
    itens = EquipamentoItem.query.filter_by(equipamento_id=equip.id, ativo=True) \
                                 .order_by(EquipamentoItem.ordem, EquipamentoItem.id).all()
    d["consumiveis"] = [i.to_dict() for i in itens if i.tipo == "consumivel"]
    d["acessorios"]  = [i.to_dict() for i in itens if i.tipo == "acessorio"]
    # vínculos do catálogo de consumíveis (N:N); o mesmo vínculo lido pelo lado do equipamento
    vinc = ConsumivelEquipamento.query.filter_by(equipamento_id=equip.id, ativo=True).all()
    vinc = [v for v in vinc if v.consumivel and v.consumivel.ativo]
    vinc.sort(key=lambda v: (v.consumivel.nome or "").lower())
    d["consumiveis_vinc"] = [v.to_dict_cons() for v in vinc]
    return jsonify(d), 200

def _ensure_docs_for_equip(equip):
    """Garante os 9 tipos de documento do equipamento (paridade com o módulo
    Documentos). Cria só os que faltam. Retorna quantos criou. Idempotente."""
    existentes = {d.tipo_doc for d in Documento.query.filter(
        Documento.ativo == True, Documento.equipamento_id == equip.id).all() if d.tipo_doc}
    n = 0
    for t in TIPOS_DOC_TODOS:
        if t in existentes:
            continue
        label = TIPOS_DOC_LABELS.get(t, t)
        db.session.add(Documento(
            setor=SETOR_DO_TIPO[t], equipamento=equip.nome, equipamento_id=equip.id,
            sku=equip.sku, fabricante=equip.fabricante, codigo_doc="",
            documento=f"{label} - {equip.nome}", tipo_doc=t, status="Elaborar",
            armazenamento=equip.armazenamento_base))
        n += 1
    return n

@app.route("/api/equipamentos", methods=["POST"])
@require_role("admin", "gestor", "tecnico")
def create_equipamento():
    caller = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    nome = (data.get("nome") or "").strip()
    if not nome:
        return jsonify({"erro": "Informe o nome do equipamento"}), 400
    equip = Equipamento(nome=nome)
    _aplicar_campos_equip(equip, data)
    db.session.add(equip)
    db.session.commit()
    # Paridade: o novo equipamento já nasce com seus 9 documentos no módulo Documentos.
    if _ensure_docs_for_equip(equip):
        db.session.commit()
    log_action(caller, "CREATE", entidade=f"Equipamento: {equip.nome}", campo="nome", novo=nome, ip=get_client_ip())
    return jsonify({"mensagem": "Equipamento criado", "equipamento": equip.to_dict()}), 201

_EQUIP_STR = ["nome", "nome_original", "nome_tecnico", "descricao",
              "sku", "sku_importacao", "classificacao_reg",
              "anvisa", "anvisa_registro", "anvisa_validade",
              "fabricante", "codigo_fabricante", "status", "observacoes", "armazenamento_base"]
_EQUIP_INT = ["categoria_id", "familia_id"]
# Itens de revisão manuais do IDP (editáveis por PATCH, validados contra ESTADOS_REVISAO).
# pareto_classe/qtd_saidas NÃO entram aqui — só o importador Pareto os grava.
_EQUIP_REV = ["rev_cadastro", "rev_estrutura", "rev_descritivo"]

def _aplicar_campos_equip(equip, data):
    """Aplica os campos do payload ao equipamento. Devolve a lista de campos mudados."""
    mudou = []
    for campo in _EQUIP_STR:
        if campo in data:
            novo = (data.get(campo) or "").strip()
            if novo != (getattr(equip, campo) or ""):
                setattr(equip, campo, novo); mudou.append(campo)
    if "bloqueado" in data:
        novo = bool(data.get("bloqueado"))
        if novo != bool(equip.bloqueado):
            equip.bloqueado = novo; mudou.append("bloqueado")
    for campo in _EQUIP_REV:
        if campo in data:
            novo = (data.get(campo) or "").strip()
            if novo not in ESTADOS_REVISAO:
                continue  # valor inválido: ignora (mantém o estado atual)
            if novo != (getattr(equip, campo) or ""):
                setattr(equip, campo, novo); mudou.append(campo)
    for campo in _EQUIP_INT:
        if campo in data:
            raw = data.get(campo)
            novo = int(raw) if raw not in (None, "", 0, "0") else None
            if novo != getattr(equip, campo):
                setattr(equip, campo, novo); mudou.append(campo)
    # Família precisa pertencer à categoria escolhida; senão zera.
    if equip.familia_id:
        fam = FamiliaEquipamento.query.get(equip.familia_id)
        if not fam or (equip.categoria_id and fam.categoria_id != equip.categoria_id):
            equip.familia_id = None
    return mudou

@app.route("/api/equipamentos/<int:equip_id>", methods=["PATCH", "PUT"])
@require_role("admin", "gestor", "tecnico")
def update_equipamento(equip_id):
    caller = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    equip = Equipamento.query.filter(Equipamento.ativo == True, Equipamento.id == equip_id).first()
    if not equip:
        return jsonify({"erro": "Equipamento não encontrado"}), 404

    nome_antigo, sku_antigo = equip.nome, equip.sku
    mudou = _aplicar_campos_equip(equip, data)
    # Identidade replicada nos documentos vinculados (fonte única = Equipamento).
    # Casa por equipamento_id; nome/SKU/fabricante alimentam grouping, card e KPIs.
    _prop = {}
    if "nome" in mudou:       _prop[Documento.equipamento] = equip.nome
    if "sku" in mudou:        _prop[Documento.sku] = equip.sku
    if "fabricante" in mudou: _prop[Documento.fabricante] = equip.fabricante
    if _prop:
        Documento.query.filter(Documento.equipamento_id == equip.id).update(
            _prop, synchronize_session=False)
    if mudou:
        equip.updated_em = datetime.now()
        db.session.commit()
        log_action(caller, "UPDATE", entidade=f"Equipamento: {equip.nome}",
                   campo=",".join(mudou), antigo=nome_antigo if "nome" in mudou else "",
                   novo="", ip=get_client_ip())
    return jsonify({"mensagem": "Equipamento atualizado", "equipamento": equip.to_dict()}), 200

@app.route("/api/equipamentos/<int:equip_id>", methods=["DELETE"])
@require_role("admin", "gestor")
def delete_equipamento(equip_id):
    caller = get_jwt_identity()
    equip = Equipamento.query.filter(Equipamento.ativo == True, Equipamento.id == equip_id).first()
    if not equip:
        return jsonify({"erro": "Equipamento não encontrado"}), 404
    equip.ativo = False                       # soft delete (reversível no banco)
    equip.updated_em = datetime.now()
    # Paridade: excluir o equipamento também remove (soft) seus documentos, para
    # não sobrar card órfão no módulo Documentos nem o backfill recriá-los.
    ndocs = Documento.query.filter(
        Documento.equipamento_id == equip.id, Documento.ativo == True).update(
        {Documento.ativo: False, Documento.deleted_at: datetime.now()},
        synchronize_session=False)
    db.session.commit()
    log_action(caller, "DELETE", entidade=f"Equipamento: {equip.nome}",
               campo="ativo", novo=f"False (+{ndocs} docs)", ip=get_client_ip())
    return jsonify({"mensagem": "Equipamento excluído", "docs_removidos": ndocs}), 200

@app.route("/api/equipamentos/export", methods=["GET"])
@jwt_required()
def export_equipamentos():
    import csv
    equips = Equipamento.query.filter(Equipamento.ativo == True).order_by(Equipamento.nome).all()
    cols = ["sku", "sku_importacao", "nome", "nome_tecnico",
            "categoria", "familia", "status", "bloqueado",
            "classificacao_reg", "anvisa", "fabricante", "codigo_fabricante"]
    buf = io.StringIO(); w = csv.writer(buf, delimiter=";")
    w.writerow(cols)
    for e in equips:
        d = e.to_dict(); w.writerow([d.get(c, "") for c in cols])
    out = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    return send_file(out, mimetype="text/csv", as_attachment=True, download_name="equipamentos.csv")

@app.route("/api/equipamentos/import", methods=["POST"])
@require_role("admin", "gestor")
def import_equipamentos():
    caller = get_jwt_identity()
    dryrun = request.args.get("dryrun", "1") not in ("0", "false")
    file_bytes = None
    if "arquivo" in request.files:
        file_bytes = request.files["arquivo"].read()
    try:
        from equipamentos_importer import importar_equipamentos
        rel = importar_equipamentos(file_bytes=file_bytes, dryrun=dryrun)
    except FileNotFoundError:
        return jsonify({"erro": "Planilha mestra não encontrada. Faça upload do arquivo."}), 404
    except Exception as e:
        return jsonify({"erro": f"Falha ao importar: {e}"}), 500
    if rel.get("erro"):
        return jsonify(rel), 400
    if not dryrun:
        log_action(caller, "REIMPORT", entidade="Equipamentos (planilha mestra)",
                   campo="import", novo=f"criados={rel['a_criar']} atualizados={rel['a_atualizar']}",
                   ip=get_client_ip())
    return jsonify(rel), 200


@app.route("/api/equipamentos/import-pareto", methods=["POST"])
@require_role("admin", "gestor")
def import_pareto():
    """Importa a aba Pareto 80-20 (Qtd de saídas + Classe ABC) casando por SKU de Venda."""
    caller = get_jwt_identity()
    dryrun = request.args.get("dryrun", "1") not in ("0", "false")
    file_bytes = None
    if "arquivo" in request.files:
        file_bytes = request.files["arquivo"].read()
    if not file_bytes:
        return jsonify({"erro": "Faça upload da planilha do Pareto."}), 400
    try:
        from pareto_importer import importar_pareto as _importar_pareto
        rel = _importar_pareto(file_bytes=file_bytes, dryrun=dryrun)
    except Exception as e:
        return jsonify({"erro": f"Falha ao importar: {e}"}), 500
    if rel.get("erro"):
        return jsonify(rel), 400
    if not dryrun:
        log_action(caller, "REIMPORT", entidade="Equipamentos (Pareto ABC)",
                   campo="import", novo=f"atualizados={rel['a_atualizar']} sem_match={rel['sem_match_n']}",
                   ip=get_client_ip())
    return jsonify(rel), 200

# ── API — TAXONOMIA (Categorias · Famílias · Linhas) ─────────────────────────
@app.route("/api/equip-taxonomia", methods=["GET"])
@jwt_required()
def api_taxonomia():
    cats = CategoriaEquipamento.query.filter_by(ativo=True).order_by(CategoriaEquipamento.nome).all()
    def uso(model, attr, _id):
        return Equipamento.query.filter(Equipamento.ativo == True, getattr(Equipamento, attr) == _id).count()
    return jsonify({
        "categorias": [{**c.to_dict(com_familias=True),
                        "uso": uso(None, "categoria_id", c.id),
                        "familias": [{**f.to_dict(), "uso": uso(None, "familia_id", f.id)} for f in c.familias if f.ativo]}
                       for c in cats],
    }), 200

def _tax_uso(attr, _id):
    return Equipamento.query.filter(getattr(Equipamento, attr) == _id).count()

@app.route("/api/categorias-equipamento", methods=["POST"])
@require_role("admin", "gestor", "tecnico")
def add_categoria():
    nome = ((request.get_json(silent=True) or {}).get("nome") or "").strip()
    if not nome: return jsonify({"erro": "Informe o nome"}), 400
    c = CategoriaEquipamento(nome=nome); db.session.add(c); db.session.commit()
    return jsonify(c.to_dict()), 201

@app.route("/api/categorias-equipamento/<int:cid>", methods=["PATCH", "DELETE"])
@require_role("admin", "gestor", "tecnico")
def edit_categoria(cid):
    c = CategoriaEquipamento.query.get(cid)
    if not c: return jsonify({"erro": "Não encontrada"}), 404
    if request.method == "DELETE":
        Equipamento.query.filter(Equipamento.categoria_id == cid).update(
            {Equipamento.categoria_id: None, Equipamento.familia_id: None}, synchronize_session=False)
        db.session.delete(c); db.session.commit()
        return jsonify({"mensagem": "Categoria excluída"}), 200
    nome = ((request.get_json(silent=True) or {}).get("nome") or "").strip()
    if nome: c.nome = nome; db.session.commit()
    return jsonify(c.to_dict()), 200

@app.route("/api/familias-equipamento", methods=["POST"])
@require_role("admin", "gestor", "tecnico")
def add_familia():
    data = request.get_json(silent=True) or {}
    nome = (data.get("nome") or "").strip(); cid = data.get("categoria_id")
    if not nome or not cid: return jsonify({"erro": "Informe nome e categoria"}), 400
    f = FamiliaEquipamento(nome=nome, categoria_id=int(cid)); db.session.add(f); db.session.commit()
    return jsonify(f.to_dict()), 201

@app.route("/api/familias-equipamento/<int:fid>", methods=["PATCH", "DELETE"])
@require_role("admin", "gestor", "tecnico")
def edit_familia(fid):
    f = FamiliaEquipamento.query.get(fid)
    if not f: return jsonify({"erro": "Não encontrada"}), 404
    if request.method == "DELETE":
        Equipamento.query.filter(Equipamento.familia_id == fid).update(
            {Equipamento.familia_id: None}, synchronize_session=False)
        db.session.delete(f); db.session.commit()
        return jsonify({"mensagem": "Família excluída"}), 200
    nome = ((request.get_json(silent=True) or {}).get("nome") or "").strip()
    if nome: f.nome = nome; db.session.commit()
    return jsonify(f.to_dict()), 200

# ── API — ITENS DO EQUIPAMENTO (Consumíveis · Acessórios) ────────────────────
@app.route("/api/equipamentos/<int:equip_id>/itens", methods=["GET"])
@jwt_required()
def list_equip_itens(equip_id):
    itens = EquipamentoItem.query.filter_by(equipamento_id=equip_id, ativo=True) \
                                 .order_by(EquipamentoItem.ordem, EquipamentoItem.id).all()
    return jsonify({
        "consumiveis": [i.to_dict() for i in itens if i.tipo == "consumivel"],
        "acessorios":  [i.to_dict() for i in itens if i.tipo == "acessorio"],
    }), 200

@app.route("/api/equipamentos/<int:equip_id>/itens", methods=["POST"])
@require_role("admin", "gestor", "tecnico")
def add_equip_item(equip_id):
    caller = get_jwt_identity()
    equip = Equipamento.query.filter(Equipamento.ativo == True, Equipamento.id == equip_id).first()
    if not equip:
        return jsonify({"erro": "Equipamento não encontrado"}), 404
    data = request.get_json(silent=True) or {}
    tipo = (data.get("tipo") or "").strip()
    if tipo not in ITEM_TIPOS:
        return jsonify({"erro": "Tipo inválido (use consumivel ou acessorio)"}), 400
    nome = (data.get("nome") or "").strip()
    if not nome:
        return jsonify({"erro": "Informe o nome do item"}), 400
    item = EquipamentoItem(
        equipamento_id=equip_id, tipo=tipo, nome=nome,
        sku=(data.get("sku") or "").strip(),
        sku_importacao=(data.get("sku_importacao") or "").strip())
    db.session.add(item); db.session.commit()
    log_action(caller, "UPDATE", entidade=f"Equipamento: {equip.nome}",
               campo=f"{tipo}+", novo=nome, ip=get_client_ip())
    return jsonify(item.to_dict()), 201

@app.route("/api/equip-itens/<int:item_id>", methods=["PATCH", "DELETE"])
@require_role("admin", "gestor", "tecnico")
def edit_equip_item(item_id):
    caller = get_jwt_identity()
    item = EquipamentoItem.query.filter_by(id=item_id, ativo=True).first()
    if not item:
        return jsonify({"erro": "Item não encontrado"}), 404
    equip = Equipamento.query.get(item.equipamento_id)
    if request.method == "DELETE":
        item.ativo = False; db.session.commit()
        log_action(caller, "UPDATE", entidade=f"Equipamento: {equip.nome if equip else ''}",
                   campo=f"{item.tipo}-", novo=item.nome, ip=get_client_ip())
        return jsonify({"mensagem": "Item excluído"}), 200
    data = request.get_json(silent=True) or {}
    for campo in ("nome", "sku", "sku_importacao"):
        if campo in data:
            setattr(item, campo, (data.get(campo) or "").strip())
    db.session.commit()
    return jsonify(item.to_dict()), 200

# ── API — CONSUMÍVEIS (catálogo + compatibilidade N:N + descritivo) ──────────
def _build_import_ctx():
    """Pré-carrega, uma vez por request de import, os mapas usados na dedup de
    consumíveis e na resolução de equipamentos/tipos. Antes, cada item varria a
    tabela inteira de consumíveis e fazia até 2 queries de equipamento por
    vínculo (N varreduras por import). As chaves usam norm() para casar de forma
    tolerante a acentos e à caixa (o lower() do SQLite é ASCII-only, então
    "SOLUÇÃO" não casaria com "solução")."""
    ctx = {"cons_sku": {}, "cons_nome": {}, "eq_sku": {}, "eq_nome": {},
           "tipo_nome": {}, "tipo_campos": {}}
    for c in Consumivel.query.filter(Consumivel.ativo == True).all():
        k = norm_sku(c.sku)
        if k:
            ctx["cons_sku"].setdefault(k, c)
        nk = norm(c.nome)
        if nk:
            ctx["cons_nome"].setdefault(nk, c)
    for e in Equipamento.query.filter(Equipamento.ativo == True).all():
        if e.sku:
            ctx["eq_sku"].setdefault(e.sku, e)
        nk = norm(e.nome)
        if nk:
            ctx["eq_nome"].setdefault(nk, e)
    for t in TipoConsumivel.query.all():
        nk = norm(t.nome)
        if nk:
            ctx["tipo_nome"].setdefault(nk, t.id)
        ctx["tipo_campos"][t.id] = {cp["chave"] for cp in t.campos_list()}
    return ctx

def _ctx_registrar_consumivel(ctx, c):
    """Registra um consumível recém-criado nos mapas para que os itens seguintes
    do mesmo lote deduplicem contra ele (evita duplicata em imports com SKUs
    repetidos no mesmo arquivo)."""
    k = norm_sku(c.sku)
    if k:
        ctx["cons_sku"].setdefault(k, c)
    nk = norm(c.nome)
    if nk:
        ctx["cons_nome"].setdefault(nk, c)

@app.route("/api/tipos-consumivel", methods=["GET"])
@jwt_required()
def list_tipos_consumivel():
    tipos = TipoConsumivel.query.filter_by(ativo=True).order_by(TipoConsumivel.ordem, TipoConsumivel.nome).all()
    # Uso por tipo em uma única query agregada (antes: 1 COUNT por tipo — N+1
    # num endpoint chamado a cada carga do catálogo).
    usos = dict(db.session.query(Consumivel.tipo_id, db.func.count(Consumivel.id))
                .filter(Consumivel.ativo == True)
                .group_by(Consumivel.tipo_id).all())
    return jsonify([{**t.to_dict(), "uso": usos.get(t.id, 0)} for t in tipos]), 200

def _sanitize_campos(campos):
    """Normaliza a lista de campos de um tipo para o contrato {chave, rotulo,
    tipo_dado, unidade}. Sem isto, um POST pode gravar uma lista de strings
    (ex.: ["material"]) que depois quebra campo["chave"] no descritivo-modelo
    e no import (TypeError → 500). Devolve (lista_ok, erro|None)."""
    if not isinstance(campos, list):
        return [], None
    limpos = []
    for c in campos:
        if not isinstance(c, dict):
            return None, "Cada campo deve ser um objeto com 'chave' e 'rotulo'."
        chave = (c.get("chave") or "").strip()
        if not chave:
            return None, "Cada campo precisa de uma 'chave' não vazia."
        limpos.append({
            "chave": chave,
            "rotulo": (c.get("rotulo") or chave).strip(),
            "tipo_dado": (c.get("tipo_dado") or "texto").strip(),
            "unidade": (c.get("unidade") or "").strip(),
        })
    return limpos, None

@app.route("/api/tipos-consumivel", methods=["POST"])
@require_role("admin", "gestor", "tecnico")
def add_tipo_consumivel():
    data = request.get_json(silent=True) or {}
    nome = (data.get("nome") or "").strip()
    if not nome:
        return jsonify({"erro": "Informe o nome"}), 400
    campos, erro = _sanitize_campos(data.get("campos"))
    if erro:
        return jsonify({"erro": erro}), 400
    t = TipoConsumivel(nome=nome, campos=json.dumps(campos, ensure_ascii=False))
    db.session.add(t); db.session.commit()
    return jsonify(t.to_dict()), 201

@app.route("/api/tipos-consumivel/<int:tid>", methods=["PATCH", "DELETE"])
@require_role("admin", "gestor", "tecnico")
def edit_tipo_consumivel(tid):
    t = TipoConsumivel.query.get(tid)
    if not t:
        return jsonify({"erro": "Tipo não encontrado"}), 404
    if request.method == "DELETE":
        Consumivel.query.filter(Consumivel.tipo_id == tid).update(
            {Consumivel.tipo_id: None}, synchronize_session=False)
        db.session.delete(t); db.session.commit()
        return jsonify({"mensagem": "Tipo excluído"}), 200
    data = request.get_json(silent=True) or {}
    if "nome" in data:
        nome = (data.get("nome") or "").strip()
        if nome:
            t.nome = nome
    if "campos" in data:
        campos, erro = _sanitize_campos(data["campos"])
        if erro:
            return jsonify({"erro": erro}), 400
        t.campos = json.dumps(campos, ensure_ascii=False)
    db.session.commit()
    return jsonify(t.to_dict()), 200

def _aplicar_campos_consumivel(c, data):
    if "nome" in data:
        c.nome = (data.get("nome") or "").strip()
    for campo in ("sku", "sku_importacao", "fabricante", "descricao", "status"):
        if campo in data:
            setattr(c, campo, (data.get(campo) or "").strip())
    if "tipo_id" in data:
        c.tipo_id = data.get("tipo_id") or None
    if "atributos" in data and isinstance(data["atributos"], dict):
        c.atributos = json.dumps(data["atributos"], ensure_ascii=False)
    c.marcar_pendencia_sku()

@app.route("/api/consumiveis", methods=["GET"])
@jwt_required()
def list_consumiveis():
    q = Consumivel.query.filter_by(ativo=True).order_by(Consumivel.nome).all()
    return jsonify([c.to_dict() for c in q]), 200

@app.route("/api/consumiveis/<int:cid>", methods=["GET"])
@jwt_required()
def get_consumivel(cid):
    c = Consumivel.query.filter_by(id=cid, ativo=True).first()
    if not c:
        return jsonify({"erro": "Consumível não encontrado"}), 404
    return jsonify(c.to_dict(com_equip=True)), 200

@app.route("/api/consumiveis", methods=["POST"])
@require_role("admin", "gestor", "tecnico")
def create_consumivel():
    caller = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    nome = (data.get("nome") or "").strip()
    if not nome:
        return jsonify({"erro": "Informe o nome do consumível"}), 400
    c = Consumivel(nome=nome)
    _aplicar_campos_consumivel(c, data)
    db.session.add(c); db.session.commit()
    log_action(caller, "CREATE", entidade=f"Consumível: {c.nome}", ip=get_client_ip())
    return jsonify(c.to_dict()), 201

@app.route("/api/consumiveis/<int:cid>", methods=["PATCH", "PUT"])
@require_role("admin", "gestor", "tecnico")
def update_consumivel(cid):
    caller = get_jwt_identity()
    c = Consumivel.query.filter_by(id=cid, ativo=True).first()
    if not c:
        return jsonify({"erro": "Consumível não encontrado"}), 404
    _aplicar_campos_consumivel(c, request.get_json(silent=True) or {})
    db.session.commit()
    log_action(caller, "UPDATE", entidade=f"Consumível: {c.nome}", ip=get_client_ip())
    return jsonify(c.to_dict(com_equip=True)), 200

@app.route("/api/consumiveis/<int:cid>", methods=["DELETE"])
@require_role("admin", "gestor")
def delete_consumivel(cid):
    caller = get_jwt_identity()
    c = Consumivel.query.filter_by(id=cid, ativo=True).first()
    if not c:
        return jsonify({"erro": "Consumível não encontrado"}), 404
    c.ativo = False; db.session.commit()
    log_action(caller, "DELETE", entidade=f"Consumível: {c.nome}", ip=get_client_ip())
    return jsonify({"mensagem": "Consumível excluído"}), 200

def _upsert_vinculo(cid, equipamento_id, fornecimento="nao_informado", obrigatorio=False, observacao=""):
    v = ConsumivelEquipamento.query.filter_by(consumivel_id=cid, equipamento_id=equipamento_id).first()
    if v:
        v.ativo = True
        if fornecimento:
            v.fornecimento = fornecimento
        v.obrigatorio = bool(obrigatorio)
        if observacao:
            v.observacao = observacao
    else:
        v = ConsumivelEquipamento(consumivel_id=cid, equipamento_id=equipamento_id,
                                  fornecimento=fornecimento or "nao_informado",
                                  obrigatorio=bool(obrigatorio), observacao=observacao or "")
        db.session.add(v)
    return v

@app.route("/api/consumiveis/<int:cid>/equipamentos", methods=["POST"])
@require_role("admin", "gestor", "tecnico")
def add_vinculo_consumivel(cid):
    c = Consumivel.query.filter_by(id=cid, ativo=True).first()
    if not c:
        return jsonify({"erro": "Consumível não encontrado"}), 404
    data = request.get_json(silent=True) or {}
    eid = data.get("equipamento_id")
    if not eid or not Equipamento.query.filter_by(id=eid, ativo=True).first():
        return jsonify({"erro": "Equipamento inválido"}), 400
    forn = data.get("fornecimento") or "nao_informado"
    if forn not in FORNECIMENTO:
        forn = "nao_informado"
    v = _upsert_vinculo(cid, int(eid), forn, data.get("obrigatorio", False),
                        (data.get("observacao") or "").strip())
    db.session.commit()
    return jsonify(v.to_dict_equip()), 201

@app.route("/api/consumivel-equipamento/<int:vid>", methods=["PATCH", "DELETE"])
@require_role("admin", "gestor", "tecnico")
def edit_vinculo_consumivel(vid):
    v = ConsumivelEquipamento.query.filter_by(id=vid).first()
    if not v:
        return jsonify({"erro": "Vínculo não encontrado"}), 404
    if request.method == "DELETE":
        v.ativo = False; db.session.commit()
        return jsonify({"mensagem": "Vínculo removido"}), 200
    data = request.get_json(silent=True) or {}
    if data.get("fornecimento") in FORNECIMENTO:
        v.fornecimento = data["fornecimento"]
    if "obrigatorio" in data:
        v.obrigatorio = bool(data["obrigatorio"])
    if "observacao" in data:
        v.observacao = (data.get("observacao") or "").strip()
    db.session.commit()
    return jsonify(v.to_dict_equip()), 200

@app.route("/api/equipamentos/<int:equip_id>/consumiveis", methods=["GET"])
@jwt_required()
def list_consumiveis_do_equip(equip_id):
    vinc = ConsumivelEquipamento.query.filter_by(equipamento_id=equip_id, ativo=True).all()
    vinc = [v for v in vinc if v.consumivel and v.consumivel.ativo]
    vinc.sort(key=lambda v: (v.consumivel.nome or "").lower())
    return jsonify([v.to_dict_cons() for v in vinc]), 200

# ── descritivo (import/export do "layout" portável, round-trip) ──────────────
def _consumivel_descritivo(c):
    return {
        "tipo": (c.tipo_rel.nome if c.tipo_rel else ""),
        "nome": c.nome or "", "sku": c.sku or "", "sku_importacao": c.sku_importacao or "",
        "fabricante": c.fabricante or "", "descricao": c.descricao or "",
        "atributos": c.atributos_dict(),
        "compatibilidade": [
            {"equipamento": v.equipamento.nome if v.equipamento else "",
             "sku": v.equipamento.sku if v.equipamento else "",
             "fornecimento": v.fornecimento or "nao_informado"}
            for v in (c.vinculos or []) if v.ativo
        ],
    }

@app.route("/api/consumiveis/<int:cid>/descritivo", methods=["GET"])
@jwt_required()
def export_descritivo(cid):
    c = Consumivel.query.filter_by(id=cid, ativo=True).first()
    if not c:
        return jsonify({"erro": "Consumível não encontrado"}), 404
    return jsonify(_consumivel_descritivo(c)), 200

@app.route("/api/tipos-consumivel/<int:tid>/descritivo-modelo", methods=["GET"])
@jwt_required()
def export_descritivo_modelo(tid):
    t = TipoConsumivel.query.get(tid)
    if not t:
        return jsonify({"erro": "Tipo não encontrado"}), 404
    return jsonify({
        "tipo": t.nome, "nome": "", "sku": "", "sku_importacao": "",
        "fabricante": "", "descricao": "",
        "atributos": {campo["chave"]: "" for campo in t.campos_list()},
        "compatibilidade": [],
    }), 200

def _processar_descritivo(item, dryrun, ctx):
    """Importa 1 descritivo (dict). Dedup por SKU e nome (via ctx pré-carregado);
    campos fora do modelo do tipo entram como 'extras' em atributos (híbrido).
    Devolve resumo."""
    nome = (item.get("nome") or "").strip()
    sku = (item.get("sku") or "").strip()
    if not nome and not sku:
        return {"acao": "ignorado", "motivo": "sem nome e sem SKU"}
    tipo_nome = (item.get("tipo") or "").strip()
    tipo_id = ctx["tipo_nome"].get(norm(tipo_nome)) if tipo_nome else None
    campos_chaves = ctx["tipo_campos"].get(tipo_id, set()) if tipo_id else set()
    atributos = item.get("atributos") if isinstance(item.get("atributos"), dict) else {}
    extras = [k for k in atributos.keys() if k not in campos_chaves] if campos_chaves else list(atributos.keys())
    compat = item.get("compatibilidade") if isinstance(item.get("compatibilidade"), list) else []

    # Dedup: primeiro por SKU; se o item não tem SKU (ou não casou), tenta por
    # nome normalizado. Sem esse fallback, reaplicar um descritivo sem SKU cria
    # uma duplicata a cada clique em "Aplicar".
    existente = ctx["cons_sku"].get(norm_sku(sku)) if sku else None
    if not existente and nome:
        existente = ctx["cons_nome"].get(norm(nome))
    # Sem correspondência e sem nome (só um SKU órfão) → não dá para criar um
    # consumível identificável; criaria um card em branco. Ignora.
    if not existente and not nome:
        return {"acao": "ignorado", "motivo": "sem nome para criar (apenas SKU sem correspondência)"}
    resumo = {"acao": "atualizar" if existente else "criar",
              "nome": nome or (existente.nome if existente else ""),
              "sku": sku, "tipo": tipo_nome, "extras": extras, "vinculos": len(compat)}
    if dryrun:
        return resumo

    c = existente or Consumivel(nome=nome)
    if nome:
        c.nome = nome
    if sku:
        c.sku = sku
    for campo in ("sku_importacao", "fabricante", "descricao"):
        if item.get(campo):
            setattr(c, campo, str(item.get(campo)).strip())
    if tipo_id:
        c.tipo_id = tipo_id
    if atributos:
        merged = c.atributos_dict(); merged.update(atributos)
        c.atributos = json.dumps(merged, ensure_ascii=False)
    c.marcar_pendencia_sku()
    if not existente:
        db.session.add(c)
    db.session.flush()   # garante c.id para os vínculos
    if not existente:
        _ctx_registrar_consumivel(ctx, c)

    for link in compat:
        eq_nome = (link.get("equipamento") or "").strip()
        eq_sku = (link.get("sku") or "").strip()
        forn = link.get("fornecimento") or "nao_informado"
        if forn not in FORNECIMENTO:
            forn = "nao_informado"
        eq = ctx["eq_sku"].get(eq_sku) if eq_sku else None
        if not eq and eq_nome:
            eq = ctx["eq_nome"].get(norm(eq_nome))
        if eq:
            _upsert_vinculo(c.id, eq.id, forn)
        else:
            resumo.setdefault("equip_nao_encontrado", []).append(eq_nome or eq_sku)
    return resumo

@app.route("/api/consumiveis/descritivo/import", methods=["POST"])
@require_role("admin", "gestor", "tecnico")
def import_descritivo():
    caller = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    dryrun = bool(data.get("dryrun", True))
    payload = data.get("descritivo")
    if isinstance(payload, dict):
        itens = [payload]
    elif isinstance(payload, list):
        itens = payload
    else:
        return jsonify({"erro": "Envie 'descritivo' como objeto ou lista"}), 400
    resultados = []
    try:
        ctx = _build_import_ctx()
        for it in itens:
            if isinstance(it, dict):
                resultados.append(_processar_descritivo(it, dryrun, ctx))
        if not dryrun:
            db.session.commit()
            log_action(caller, "UPDATE", entidade="Consumíveis (descritivo)",
                       novo=f"{len(resultados)} item(ns)", ip=get_client_ip())
    except Exception as e:
        db.session.rollback()
        return jsonify({"erro": f"Falha ao importar: {e}"}), 400
    return jsonify({
        "aplicado": not dryrun, "total": len(resultados),
        "a_criar": sum(1 for r in resultados if r.get("acao") == "criar"),
        "a_atualizar": sum(1 for r in resultados if r.get("acao") == "atualizar"),
        "itens": resultados,
    }), 200

# ── importar descritivo a partir de um Word (.docx) ───────────────────────────
# Lê o "Descrição Técnica do Produto" (mesmo modelo do 01.000983) e devolve o item
# JSON no formato que a rota /descritivo/import já consome (prévia → aplicar por SKU).
# Só captura as 4 seções da ficha; as demais seções do Word são ignoradas.
_DOCX_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_DESCR_IDENT = {
    "titulo": ("col", "nome"), "codigo": ("d", "identificacao", "codigo"),
    "area": ("d", "identificacao", "area"), "sku protheus": ("col", "sku"),
    "fornecedor": ("col", "fabricante"), "origem": ("d", "identificacao", "origem"),
    "criticidade": ("d", "identificacao", "criticidade"),
}
_DESCR_DESC = {
    "nome comercial": ("d", "descricao", "nome_comercial"), "descricao": ("col", "descricao"),
    "categoria": ("d", "descricao", "categoria"), "aplicacao": ("d", "descricao", "aplicacao"),
}
_DESCR_TECN = {
    "material": ("d", "tecnicas", "material"), "dimensoes": ("d", "tecnicas", "dimensoes"),
    "desempenho": ("d", "tecnicas", "desempenho"), "esterilidade": ("d", "tecnicas", "esterilidade"),
    "compatibilidade": ("d", "tecnicas", "compatibilidade"),
}
_DESCR_EMB = {
    "tipo primaria": ("d", "embalagem", "tipo_primaria"),
    "tipo secundaria": ("d", "embalagem", "tipo_secundaria"),
    "quantidade": ("d", "embalagem", "quantidade"),
}
_DESCR_SECOES = {
    "identificacao": _DESCR_IDENT, "descricao do produto": _DESCR_DESC,
    "caracteristicas tecnicas": _DESCR_TECN, "embalagem": _DESCR_EMB,
}

def _docx_paragrafos(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    root = ET.fromstring(xml)
    out = []
    for p in root.iter(_DOCX_W + "p"):   # inclui parágrafos dentro de tabelas
        out.append("".join(t.text for t in p.iter(_DOCX_W + "t") if t.text))
    return out

def _descritivo_item_de_paragrafos(paras):
    item = {}
    d = {"identificacao": {}, "descricao": {}, "tecnicas": {}, "embalagem": {}}
    atual = None
    for raw in paras:
        line = (raw or "").strip()
        if not line:
            continue
        # cabeçalho de seção: linha toda em maiúsculas, sem ":" (ex.: "IDENTIFICAÇÃO")
        if ":" not in line and line == line.upper() and any(ch.isalpha() for ch in line):
            atual = _DESCR_SECOES.get(norm(line))   # None se não for uma das 4 seções
            continue
        if atual is None or ":" not in line:
            continue
        label, _, value = line.partition(":")
        value = value.strip()
        alvo = atual.get(norm(label))
        if not alvo or not value:
            continue
        if alvo[0] == "col":
            item[alvo[1]] = value
        else:
            d[alvo[1]][alvo[2]] = value
    item["atributos"] = {"descritivo": d}
    return item

@app.route("/api/consumiveis/descritivo/import-docx", methods=["POST"])
@require_role("admin", "gestor", "tecnico")
def import_descritivo_docx():
    f = request.files.get("arquivo")
    if not f:
        return jsonify({"erro": "Envie o arquivo .docx no campo 'arquivo'"}), 400
    if not (f.filename or "").lower().endswith(".docx"):
        return jsonify({"erro": "Formato inválido: envie um arquivo .docx"}), 400
    try:
        paras = _docx_paragrafos(f.read())
    except Exception as e:
        return jsonify({"erro": f"Não foi possível ler o .docx: {e}"}), 400
    item = _descritivo_item_de_paragrafos(paras)
    if not (item.get("sku") or item.get("nome")):
        return jsonify({"erro": "Não encontrei 'Título' nem 'SKU Protheus' no documento. "
                                "Confira se o Word segue o modelo (seções em MAIÚSCULAS e 'Campo: valor')."}), 400
    return jsonify({"item": item}), 200

@app.route("/api/consumiveis/export", methods=["GET"])
@jwt_required()
def export_consumiveis_csv():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Nome", "SKU de Venda", "SKU de Importação", "Tipo", "Fabricante",
                "Pendente SKU", "Nº equipamentos", "Equipamentos"])
    for c in Consumivel.query.filter_by(ativo=True).order_by(Consumivel.nome).all():
        eqs = "; ".join(f"{v.equipamento.nome} ({v.fornecimento})"
                        for v in (c.vinculos or []) if v.ativo and v.equipamento)
        w.writerow([c.nome, c.sku, c.sku_importacao, (c.tipo_rel.nome if c.tipo_rel else ""),
                    c.fabricante, "sim" if c.pendente_sku else "não",
                    len([v for v in (c.vinculos or []) if v.ativo]), eqs])
    out.seek(0)
    return send_file(io.BytesIO(out.getvalue().encode("utf-8-sig")),
                     mimetype="text/csv", as_attachment=True, download_name="consumiveis.csv")

# ── API — PDF REPORT ─────────────────────────────────────────────────────────
@app.route("/api/report/pdf", methods=["POST"])
@require_role("admin", "gestor", "tecnico")
def api_report_pdf():
    try:
        import sys
        files_dir = os.path.join(BASE_DIR, "files")
        if files_dir not in sys.path:
            sys.path.append(files_dir)
        import generate_report
        
        payload = request.get_json(force=True, silent=True) or {}
        kpis = payload.get("kpis") or payload
        pdf_bytes = generate_report.render_pdf(kpis)
        
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="DocTrack_Enterprise_KPIs.pdf",
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"erro": f"Erro na geração do PDF: {e}"}), 500

# ── API — METRICS / ENUMS / AUDIT / EXPORT ───────────────────────────────────

@app.route("/api/metrics")
@jwt_required()
def api_metrics():
    docs = [d.to_dict() for d in Documento.query.filter(Documento.ativo == True).all()]
    return jsonify(compute_kpis(docs)), 200

@app.route("/api/version")
def api_version():
    return jsonify({"version": APP_VERSION}), 200

@app.route("/api/enums")
@jwt_required()
def api_enums():
    familias = [f[0] for f in db.session.query(Equipamento.familia)
                .filter(Equipamento.ativo == True, Equipamento.familia != "")
                .distinct().order_by(Equipamento.familia).all()]
    return jsonify({
        "setores": SETORES,
        "status_map": STATUS_MAP,
        "tipos_doc_pre": TIPOS_DOC_PRE,
        "tipos_doc_fabricante": TIPOS_DOC_FABRICANTE,
        "tipos_doc_todos": TIPOS_DOC_TODOS,
        "setor_do_tipo": SETOR_DO_TIPO,
        "tipos_doc_labels": TIPOS_DOC_LABELS,
        "familias": familias,
    }), 200

def _filter_audit_dates(query):
    """Aplica filtro de intervalo de datas (inicio/fim no formato YYYY-MM-DD) sobre AuditLog.timestamp."""
    inicio = request.args.get("inicio", "").strip()
    fim = request.args.get("fim", "").strip()
    if inicio:
        try:
            query = query.filter(AuditLog.timestamp >= datetime.strptime(inicio, "%Y-%m-%d"))
        except Exception:
            pass
    if fim:
        try:
            query = query.filter(AuditLog.timestamp < datetime.strptime(fim, "%Y-%m-%d") + timedelta(days=1))
        except Exception:
            pass
    return query

@app.route("/api/audit")
@require_role("admin", "gestor")
def api_audit():
    q = norm(request.args.get("q", ""))
    acao = request.args.get("acao", "")
    try: limit = max(1, min(int(request.args.get("limit", 200)), 1000))
    except: return jsonify({"erro": "limit deve ser numérico"}), 400
    query = AuditLog.query.order_by(AuditLog.timestamp.desc())
    if acao: query = query.filter(AuditLog.acao == acao)
    query = _filter_audit_dates(query)
    result = [l.to_dict() for l in query.limit(limit).all()]
    if q: result = [l for l in result if q in norm(l.get("usuario")) or q in norm(l.get("entidade")) or q in norm(l.get("campo"))]
    return jsonify(result), 200

@app.route("/api/export/audit")
@require_role("admin", "gestor")
def export_audit():
    logs = _filter_audit_dates(AuditLog.query.order_by(AuditLog.timestamp.desc())).all()
    
    # Caminho para o template do relatório HTML
    template_path = os.path.join(BASE_DIR, "audit_log_report.html")
    if not os.path.exists(template_path):
        return jsonify({"erro": "Template de relatório não encontrado"}), 500
        
    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()
        
    # Formata os logs no mesmo padrão da variável RAW no frontend
    raw_list = []
    for log in logs:
        raw_list.append({
            "ID": log.id,
            "Usuario": log.usuario_email or "",
            "Acao": log.acao or "",
            "Entidade": log.entidade or "",
            "Campo": log.campo or "",
            "ValorAntigo": log.valor_antigo or "",
            "ValorNovo": log.valor_novo or "",
            "Data": log.timestamp.strftime("%d/%m/%Y %H:%M:%S") if log.timestamp else ""
        })
        
    raw_json = json.dumps(raw_list, ensure_ascii=False)

    # Substitui a definição const RAW no javascript usando index para máxima segurança
    start_str = "const RAW = ["
    start_idx = html_content.find(start_str)
    if start_idx != -1:
        end_idx = html_content.find("];", start_idx)
        if end_idx != -1:
            html_content = html_content[:start_idx] + f"const RAW = {raw_json}" + html_content[end_idx + 1:]
            
    # Atualiza a data de exportação no cabeçalho
    import re
    current_date = datetime.now().strftime("%d/%m/%Y")
    html_content = re.sub(
        r'exportado em \d{2}/\d{2}/\d{4}',
        f'exportado em {current_date}',
        html_content
    )
    
    return send_file(
        io.BytesIO(html_content.encode('utf-8')),
        mimetype="text/html",
        as_attachment=False
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
def _sync_schema():
    """Adiciona colunas novas a tabelas já existentes (cross-dialect, idempotente).

    db.create_all() cria tabelas faltantes, mas não altera tabelas existentes.
    Em produção (Postgres) as colunas de PMO/EVM precisam ser adicionadas aqui,
    já que as migrations 004/005 são apenas para SQLite local.
    """
    from sqlalchemy import inspect as _sa_inspect, text
    insp = _sa_inspect(db.engine)
    existentes = set(insp.get_table_names())
    # Boolean DEFAULT difere entre dialetos (Postgres exige FALSE, SQLite aceita 0)
    _bool_false = "FALSE" if db.engine.dialect.name == "postgresql" else "0"
    novas_colunas = {
        "users": [
            ("precisa_definir_senha", f"BOOLEAN DEFAULT {_bool_false} NOT NULL"),
            ("ativacao_codigo_hash",  "VARCHAR(256)"),
            ("ativacao_expira",       "TIMESTAMP"),
            ("pode_pdr",              f"BOOLEAN DEFAULT {_bool_false} NOT NULL"),
            ("areas",                 "VARCHAR(200) DEFAULT '' NOT NULL"),
        ],
        "projetos": [
            ("data_inicio_prev", "VARCHAR(10) DEFAULT ''"),
            ("data_inicio_real", "VARCHAR(10) DEFAULT ''"),
            ("data_fim_prev",    "VARCHAR(10) DEFAULT ''"),
            ("data_fim_real",    "VARCHAR(10) DEFAULT ''"),
            ("orcamento",        "FLOAT DEFAULT 0"),
            ("tipo",             "VARCHAR(20) DEFAULT ''"),
        ],
        "entregaveis": [
            ("data_inicio",    "VARCHAR(10) DEFAULT ''"),
            ("data_conclusao", "VARCHAR(10) DEFAULT ''"),
        ],
        "projeto_mensal": [
            ("custo_mes", "FLOAT DEFAULT 0"),
        ],
        "documentos": [
            ("equipamento_id", "INTEGER"),
        ],
        "equipamentos": [
            ("nome_tecnico",      "VARCHAR(400) DEFAULT ''"),
            ("descricao",         "TEXT DEFAULT ''"),
            ("codigo_interno",    "VARCHAR(50) DEFAULT ''"),
            ("sku_importacao",    "VARCHAR(50) DEFAULT ''"),
            ("status",            "VARCHAR(40) DEFAULT 'Ativo'"),
            ("bloqueado",         f"BOOLEAN DEFAULT {_bool_false} NOT NULL"),
            ("observacoes",       "TEXT DEFAULT ''"),
            ("categoria_id",      "INTEGER"),
            ("familia_id",        "INTEGER"),
            ("linha_id",          "INTEGER"),
            ("classificacao_reg", "VARCHAR(20) DEFAULT ''"),
            ("codigo_fabricante", "VARCHAR(80) DEFAULT ''"),
            ("rev_cadastro",      "VARCHAR(20) DEFAULT 'Pendente'"),
            ("rev_estrutura",     "VARCHAR(20) DEFAULT 'Pendente'"),
            ("rev_descritivo",    "VARCHAR(20) DEFAULT 'Pendente'"),
            ("pareto_classe",     "VARCHAR(1) DEFAULT ''"),
            ("qtd_saidas",        "INTEGER DEFAULT 0"),
        ],
    }
    adicionadas = set()
    for tabela, colunas in novas_colunas.items():
        if tabela not in existentes:
            continue  # tabela nova: já criada por create_all() com o schema completo
        cols_atuais = {c["name"] for c in insp.get_columns(tabela)}
        for nome, ddl in colunas:
            if nome not in cols_atuais:
                db.session.execute(
                    text(f'ALTER TABLE {tabela} ADD COLUMN {nome} {ddl}'))
                adicionadas.add(f"{tabela}.{nome}")
                print(f"[INFO] Schema: coluna {tabela}.{nome} adicionada")
    db.session.commit()

    # Acesso ao PDR: ao criar a coluna, libera automaticamente para os admins.
    if "users.pode_pdr" in adicionadas:
        _bool_true = "TRUE" if db.engine.dialect.name == "postgresql" else "1"
        db.session.execute(text(
            f"UPDATE users SET pode_pdr = {_bool_true} WHERE role = 'admin'"))
        db.session.commit()
        print("[INFO] Schema: pode_pdr liberado para os administradores")

    # Áreas: ao criar a coluna, todos viram membros de 'pde' (são usuários de
    # equipamentos hoje); quem tinha pode_pdr também recebe 'pdr'.
    if "users.areas" in adicionadas:
        _bool_true = "TRUE" if db.engine.dialect.name == "postgresql" else "1"
        db.session.execute(text("UPDATE users SET areas = 'pde'"))
        db.session.execute(text(
            f"UPDATE users SET areas = 'pde,pdr' WHERE pode_pdr = {_bool_true}"))
        db.session.commit()
        print("[INFO] Schema: áreas inicializadas (pde; pdr p/ quem tinha PDR)")

    # Retroalimenta a conclusão dos entregáveis já concluídos com a última
    # atualização, para que projetos antigos já exibam alguma Curva-S. Só roda
    # quando a coluna acaba de ser criada (espelha a migration 005). O CAST torna
    # o substr compatível com Postgres (timestamp) e SQLite (texto).
    # Converte dados antigos do modelo "acumulado" para o novo "incremental":
    # ao criar custo_mes, deriva o custo de cada mês a partir do delta do
    # custo_acumulado por projeto (ordenado por competência).
    if "projeto_mensal.custo_mes" in adicionadas:
        rows = db.session.execute(text(
            "SELECT projeto_id, competencia, custo_acumulado FROM projeto_mensal "
            "ORDER BY projeto_id, competencia")).fetchall()
        anterior = {}
        for projeto_id, competencia, acum in rows:
            acum = acum or 0.0
            mes = round(acum - anterior.get(projeto_id, 0.0), 2)
            anterior[projeto_id] = acum
            db.session.execute(
                text("UPDATE projeto_mensal SET custo_mes = :v "
                     "WHERE projeto_id = :p AND competencia = :c"),
                {"v": mes, "p": projeto_id, "c": competencia})
        db.session.commit()
        print(f"[INFO] Schema: custo_mes derivado de {len(rows)} lançamento(s) existentes")

    if "entregaveis.data_conclusao" in adicionadas:
        res = db.session.execute(text("""
            UPDATE entregaveis
               SET data_conclusao = substr(CAST(atualizado_em AS VARCHAR), 1, 10)
             WHERE status = 'concluido'
               AND (data_conclusao IS NULL OR data_conclusao = '')
               AND atualizado_em IS NOT NULL
        """))
        db.session.commit()
        print(f"[INFO] Schema: {res.rowcount} entregável(is) com conclusão retroalimentada")

    # Semeia os modelos de entregáveis (OEM/Revenda) a partir dos entregáveis
    # distintos já existentes — só quando a tabela está vazia (espelha a
    # migration 006). Cross-dialect (Postgres/SQLite).
    if "modelos_entregavel" in set(_sa_inspect(db.engine).get_table_names()):
        ja = db.session.execute(text("SELECT COUNT(*) FROM modelos_entregavel")).scalar()
        if not ja:
            base = db.session.execute(text("""
                SELECT categoria, tipo,
                       COALESCE((SELECT responsaveis FROM entregaveis e2
                                 WHERE e2.categoria = e1.categoria AND e2.tipo = e1.tipo
                                 ORDER BY e2.id LIMIT 1), '') AS resp,
                       MIN(id) AS ord
                  FROM entregaveis e1
                 GROUP BY categoria, tipo
                 ORDER BY ord
            """)).fetchall()
            from models import TIPOS_PROJETO as _TP
            n = 0
            for tp in _TP:
                for ordem, (categoria, tipo, resp, _min) in enumerate(base):
                    db.session.execute(text(
                        "INSERT INTO modelos_entregavel "
                        "(tipo_projeto, categoria, tipo, responsavel_padrao, ordem) "
                        "VALUES (:tp, :cat, :tipo, :resp, :ord)"),
                        {"tp": tp, "cat": categoria or "Produto", "tipo": tipo,
                         "resp": resp or "", "ord": ordem})
                    n += 1
            db.session.commit()
            if n:
                print(f"[INFO] Schema: {n} itens de modelo de entregável semeados")


def _backfill_equipamentos():
    """Cria a entidade Equipamento, vincula os documentos e completa os 9 tipos
    por equipamento. Idempotente — roda a cada boot e após o seed do Excel."""
    # 1) PRE legado sem tipo_doc → IT (antes de contar os tipos existentes)
    Documento.query.filter(
        Documento.setor == "PRE",
        Documento.ativo == True,
        db.or_(Documento.tipo_doc == None, Documento.tipo_doc == ""),
    ).update({Documento.tipo_doc: "IT"}, synchronize_session=False)
    db.session.commit()

    # 2) Agrupa os documentos de equipamento (PRE + Manuais) por nome.
    #    PDE (processos) fica de fora — não é equipamento.
    docs_equip = Documento.query.filter(
        Documento.ativo == True,
        Documento.setor.in_(["PRE", "Manuais"]),
    ).all()
    grupos = {}
    for d in docs_equip:
        nome = (d.equipamento or "").strip()
        if nome:
            grupos.setdefault(nome, []).append(d)

    def _primeiro(docs, attr):
        for d in docs:
            v = getattr(d, attr, None)
            if v:
                return v
        return ""

    novos_equip = novos_docs = 0
    for nome, docs in grupos.items():
        equip = Equipamento.query.filter_by(nome=nome).first()
        if not equip:
            equip = Equipamento(
                nome=nome,
                sku=_primeiro(docs, "sku"),
                fabricante=_primeiro(docs, "fabricante"),
                armazenamento_base=_primeiro(docs, "armazenamento"),
            )
            db.session.add(equip)
            db.session.flush()           # garante equip.id
            novos_equip += 1

        for d in docs:                   # vincula só documentos ainda soltos
            if not d.equipamento_id:     # (não reatribui já vinculados — evita
                d.equipamento_id = equip.id  #  "pingar" entre entidades homônimas)

    db.session.flush()

    # 3) Paridade total Equipamentos ↔ Documentos: TODO equipamento ativo —
    #    inclusive os importados da planilha (sem documentos) — recebe os 9 tipos
    #    faltantes, para aparecer também no módulo Documentos. Idempotente: só
    #    cria o que falta (verifica os tipos já existentes por equipamento_id).
    for equip in Equipamento.query.filter(Equipamento.ativo == True).all():
        novos_docs += _ensure_docs_for_equip(equip)

    db.session.commit()
    if novos_equip or novos_docs:
        print(f"[INFO] Equipamentos: {novos_equip} criados; {novos_docs} documentos completados.")


def _seed_tipos_consumivel():
    """Semeia os tipos de consumível + o modelo de campos de cada um (só quando
    a tabela está vazia). As tabelas de consumíveis são criadas por create_all().
    Idempotente."""
    if TipoConsumivel.query.count() > 0:
        return
    n = 0
    for ordem, (nome, campos) in enumerate(TIPOS_CONSUMIVEL_SEED.items()):
        db.session.add(TipoConsumivel(nome=nome, ordem=ordem,
                                      campos=json.dumps(campos, ensure_ascii=False)))
        n += 1
    db.session.commit()
    if n:
        print(f"[INFO] Consumíveis: {n} tipos semeados com modelo de campos")


with app.app_context():
    try:
        db.create_all()
        _sync_schema()
        _seed_tipos_consumivel()
        # Migração automática de 'Fabricante' para 'Manuais' nos registros existentes
        from sqlalchemy import text
        db.session.execute(text("UPDATE documentos SET setor = 'Manuais' WHERE setor = 'Fabricante'"))
        db.session.commit()

        if User.query.count() == 0:
            init_db()

        # Reestruturação: entidade Equipamento + 9 tipos por equipamento.
        # Após o seed, para cobrir também instalações novas. Idempotente.
        _backfill_equipamentos()

        # PDR: na primeira subida as tabelas pdr_* já foram criadas por create_all();
        # importa a Lista Mestra de Reagentes (versionada em pdr/data/) se estiver vazia.
        try:
            from pdr.models import Apresentacao as _PdrApres
            if _PdrApres.query.count() == 0:
                from pdr.importer import importar_planilha as _importar_pdr
                _importar_pdr()
        except Exception as _pdr_err:
            print(f"[WARN] Importação inicial do PDR: {_pdr_err}")
    except Exception as _startup_err:
        print(f"[WARN] Erro na inicialização do banco: {_startup_err}")

# ── MAIN (desenvolvimento local) ─────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true")
    args = parser.parse_args()
    print("\n" + "="*55)
    print("  DocTrack v4.0 Enterprise — Sector Based + WebSocket")
    print("="*55)
    if args.init: init_db(reset=True)
    socketio.run(app, host="0.0.0.0", port=5000, debug=_flask_debug, allow_unsafe_werkzeug=True)
