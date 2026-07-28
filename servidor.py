"""
servidor.py — DocTrack v4.0 Enterprise Backend
"""
import os, sys, json, argparse, io, csv, re, zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, date

from flask import Flask, jsonify, render_template, request, send_file
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, jwt_required, get_jwt_identity, get_jwt, decode_token
)
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

# ── CAMINHOS (compatível com PyInstaller / executável "congelado") ─────────────
# ASSET_DIR: assets somente-leitura (templates/, static/)
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

BASE_DIR   = ASSET_DIR                                   # assets de leitura (templates/, static/)
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
# Custo do bcrypt. 12 é o padrão e o valor de produção; a suíte de testes baixa
# para 4 via ambiente (187ms -> 1ms por hash). Precisa estar no config ANTES do
# bcrypt.init_app() abaixo — o Flask-Bcrypt lê o valor uma única vez.
app.config["BCRYPT_LOG_ROUNDS"]              = int(os.environ.get("BCRYPT_LOG_ROUNDS", "12"))
# Teto de corpo da requisição. Vale para TODO upload (planilha de import,
# arquivo de documento). Antes disto não havia teto nenhum: encher o disco do
# servidor era um POST. Ajuste por DOCTRACK_UPLOAD_MAX_MB.
import arquivos_store
app.config["MAX_CONTENT_LENGTH"]             = arquivos_store.MAX_BYTES


@app.errorhandler(413)
def _erro_arquivo_grande(_e):
    """O Flask aborta com HTML quando o corpo estoura MAX_CONTENT_LENGTH; o
    front faz res.json() em toda resposta, então precisa ser JSON."""
    return jsonify({"erro": f"Arquivo maior que {arquivos_store.MAX_MB} MB"}), 413


from models import (
    db, bcrypt, User, Documento, DocumentoHistorico, DocumentoArquivo, Equipamento,
    AuditLog, RevokedToken,
    EquipamentoHistorico, EquipamentoSnapshot, EquipamentoPasta, ParetoHistorico, ImportacaoLog,
    CategoriaEquipamento, FamiliaEquipamento, EquipamentoItem, ITEM_TIPOS,
    Consumivel, TipoConsumivel, ConsumivelEquipamento, FORNECIMENTO, TIPOS_CONSUMIVEL_SEED,
    SETORES, SETOR_PROCESSO, SETORES_TODOS, STATUS_PRE, STATUS_FABRICANTE, STATUS_MAP,
    TIPOS_DOC_PRE, TIPOS_DOC_FABRICANTE, TIPOS_DOC_TODOS,
    TIPOS_DOC_OPCIONAIS, SETOR_DO_TIPO, TIPOS_DOC_LABELS, ESTADOS_REVISAO,
    MOTIVOS_NA, MOTIVO_NA_LIVRE
)
from auth import auth_bp, log_action, require_role, get_client_ip
from event_bus import publish_event, get_events_since, EventType
from utils import norm, norm_sku
import caminhos
from scheduler import iniciar_agendador, rodar_uma_vez, agendador_habilitado
import equipamentos_core as eqcore

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
    # SAMEORIGIN e não DENY: o visor de documento enquadra o próprio endpoint de
    # conteúdo (PDF/imagem) num <iframe>, e DENY bloqueia isso até em mesma
    # origem. O que clickjacking exige é impedir que OUTRO site enquadre o
    # DocTrack — e disso SAMEORIGIN dá conta igual.
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    # Sem CDN em nenhuma diretiva: as bibliotecas JS já eram servidas de
    # /static/vendor porque o app roda em rede fabril, que pode não ter saída
    # externa — mas o Google Fonts continuava liberado em style-src/font-src e
    # os templates ainda o carregavam. As fontes agora vêm da pilha do sistema
    # (ver --font-body em static/style.css), então a política fecha de vez.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; "
        "img-src 'self' data:; "
        # frame-ancestors é a diretiva que substitui X-Frame-Options nos
        # navegadores modernos; sem ela a política herda default-src e o
        # cabeçalho acima ficaria sendo a única regra.
        "frame-ancestors 'self'; "
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
    """KPIs dos documentos DE EQUIPAMENTO (PRE + Manuais).

    Dois filtros, nesta ordem:
      1) N/A ("não se aplica a este equipamento") sai de TODA a contagem — não é
         backlog, não é pendência e não puxa o pct_concluidos para baixo.
      2) Setor fora de SETORES (documentos de processo, setor 'PDE') também sai.
         Antes eles entravam no `total` e no `global_counts` mas não no
         `por_setor` — o card dizia 475 documentos e o donut somava 469.
    A contagem dos documentos de processo vai separada em `processos`.
    """
    docs = [d for d in docs if d.get("aplicavel", True)]
    processos = sum(1 for d in docs if d.get("setor") not in SETORES)
    docs = [d for d in docs if d.get("setor") in SETORES]
    total = len(docs)
    por_setor = {s: 0 for s in SETORES}
    status_counts = {s: {} for s in SETORES}
    global_counts = {"Pendente": 0, "Em progresso": 0, "Finalizado": 0}
    atrasados = 0

    for d in docs:
        setor = d.get("setor")
        por_setor[setor] += 1
        st = d.get("status") or "Elaborar"
        status_counts[setor][st] = status_counts[setor].get(st, 0) + 1

        sg = d.get("status_global") or "Pendente"
        global_counts[sg] = global_counts.get(sg, 0) + 1
        if d.get("atrasado"):
            atrasados += 1

    fin = global_counts.get("Finalizado", 0)

    return {
        "total": total,
        "finalizados": fin,
        "em_progresso": global_counts.get("Em progresso", 0),
        "pendentes": global_counts.get("Pendente", 0),
        "backlog": total - fin,
        "atrasados": atrasados,
        "processos": processos,
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
                    armazenamento=caminhos.normalizar(s("Armazenamento - Pasta de Projetos"))
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
                armazenamento = caminhos.normalizar(s("Armazenamento - Pasta de Projetos"))

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
                    armazenamento=caminhos.normalizar(s("Armazenamento - Pasta de Projetos"))
                ))

        # SÓ SEMEIA BANCO VAZIO. Aqui existia um
        # DROP TABLE documento_historico + DROP TABLE documentos + CREATE,
        # herdado de quando o schema mudava a cada deploy no Render. Com o banco
        # em uso isso apagava os 522 documentos e as 526 linhas de trilha, junto
        # com tudo que a planilha não tem (prazo, aplicavel, motivo_na_codigo,
        # equipamento_id, version) e deixava os cartões de missão apontando para
        # ids inexistentes. A planilha é a origem do seed, não a fonte da verdade.
        existentes = Documento.query.count()
        if existentes:
            print(f"[SKIP] Planilha ignorada: já existem {existentes} documentos "
                  f"no banco (o seed por planilha só roda em banco vazio).")
            return 0

        for d in docs_to_add:
            db.session.add(d)

        db.session.commit()
        print(f"[OK] Planilha importada com sucesso: {len(docs_to_add)} novos documentos.")
        return len(docs_to_add)
    except Exception as e:
        db.session.rollback()
        print(f"  Aviso: não foi possível importar Planilha — {e}")
        return 0

# ── PÁGINAS ───────────────────────────────────────────────────────────────────
def _static_version():
    """Token de cache-busting baseado no mtime dos estáticos (muda só quando o arquivo muda)."""
    try:
        files = ["static/app.js", "static/auth.js", "static/common.js",
                 "static/style.css", "static/socket-client.js",
                 "static/app-realtime.js"]
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

# ── API — DADOS ───────────────────────────────────────────────────────────────
@app.route("/api/data")
@jwt_required()
def api_data():
    docs = [d.to_dict() for d in Documento.query.filter(Documento.ativo == True).order_by(Documento.equipamento).all()]
    return jsonify({"updated_at": datetime.now().strftime("%d/%m/%Y %H:%M"), "items": docs, "kpis": compute_kpis(docs)}), 200

# ── API — EQUIPAMENTOS (entidade central) ────────────────────────────────────
_EQUIP_BUSCA = ("nome", "nome_original", "nome_tecnico", "sku", "sku_importacao",
                "codigo_fabricante", "anvisa", "fabricante",
                "familia", "categoria", "responsavel")


def _query_equipamentos():
    """Filtros de equipamento em um lugar só: a listagem e o export usavam
    critérios diferentes (o export ignorava os filtros da tela)."""
    query = Equipamento.query.filter(Equipamento.ativo == True)
    for campo, col in (("categoria_id", Equipamento.categoria_id),
                       ("familia_id", Equipamento.familia_id)):
        val = request.args.get(campo)
        if val:
            try:
                query = query.filter(col == int(val))
            except (TypeError, ValueError):
                pass
    if request.args.get("status"):
        query = query.filter(Equipamento.status == request.args.get("status"))
    if request.args.get("pareto_classe"):
        query = query.filter(Equipamento.pareto_classe == request.args.get("pareto_classe"))
    bloq = request.args.get("bloqueado")
    if bloq in ("0", "false", "nao"):
        query = query.filter(Equipamento.bloqueado == False)
    elif bloq in ("1", "true", "sim"):
        query = query.filter(Equipamento.bloqueado == True)
    # "Bloqueado" na tela também abrange Obsoleto/Descontinuado; sem este filtro
    # o CSV trazia obsoletos que a lista escondia.
    if request.args.get("incluir_bloqueados") in ("0", "false", "nao"):
        query = query.filter(Equipamento.bloqueado == False,
                             Equipamento.status.notin_(["Obsoleto", "Descontinuado"]))
    return query.order_by(Equipamento.nome)


def _filtrar_busca(equips, termo):
    q = norm(termo or "")
    if not q:
        return equips
    return [e for e in equips
            if q in " ".join(norm(str(e.get(f, ""))) for f in _EQUIP_BUSCA)]


def _docs_dos_equipamentos(equip_ids=None):
    """Documentos ativos vinculados, já agrupados por equipamento."""
    query = Documento.query.filter(Documento.ativo == True,
                                   Documento.equipamento_id.isnot(None))
    if equip_ids is not None:
        ids = list(equip_ids)
        if not ids:
            return {}
        query = query.filter(Documento.equipamento_id.in_(ids))
    return eqcore.agrupar_documentos(query.all())


@app.route("/api/equipamentos", methods=["GET"])
@jwt_required()
def api_equipamentos():
    equips = [e.to_dict() for e in _query_equipamentos().all()]
    return jsonify(_filtrar_busca(equips, request.args.get("q", ""))), 200


@app.route("/api/equipamentos/completude", methods=["GET"])
@jwt_required()
def api_equipamentos_completude():
    """ICE, IDP e sinais de risco de todos os equipamentos, calculados aqui.

    Existe porque o módulo baixava `/api/documentos` inteiro (todos os documentos
    do sistema) só para dividir finalizados por aplicáveis — e reimplementava a
    fórmula no cliente. Agora a regra é a mesma do export e do snapshot.
    """
    equips = _query_equipamentos().all()
    por_equip = _docs_dos_equipamentos([e.id for e in equips])
    itens = [eqcore.indices(e, por_equip.get(e.id, [])) for e in equips]
    return jsonify({
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "total": len(itens),
        "itens": itens,
    }), 200

@app.route("/api/equipamentos/<int:equip_id>", methods=["GET"])
@jwt_required()
def get_equipamento(equip_id):
    equip = Equipamento.query.filter(Equipamento.ativo == True, Equipamento.id == equip_id).first()
    if not equip:
        return jsonify({"erro": "Equipamento não encontrado"}), 404
    d = equip.to_dict()
    docs = Documento.query.filter(Documento.ativo == True,
                                  Documento.equipamento_id == equip.id).all()
    d["docs_count"] = len(docs)
    d["completude"] = eqcore.indices(equip, docs)
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
    """Garante os 12 tipos de documento do equipamento (paridade com o módulo
    Documentos). Os opcionais nascem em N/A (aplicavel=False) — existem, mas fora
    da completude, até alguém ligá-los na aba Escopo. Cria só o que falta.
    Retorna quantos criou. Idempotente."""
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
            aplicavel=(t not in TIPOS_DOC_OPCIONAIS),
            # nasce herdando o caminho do equipamento (armazenamento vazio =
            # herda); copiar aqui recriaria as 12 cópias divergentes.
            armazenamento=""))
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
    dup = sku_duplicado(data.get("sku"))
    if dup and not data.get("ignorar_sku_duplicado"):
        return jsonify({"erro": f'SKU "{(data.get("sku") or "").strip()}" já está em '
                                f'"{dup.nome}". Corrija o SKU ou reenvie com '
                                f'ignorar_sku_duplicado.',
                        "sku_duplicado": {"id": dup.id, "nome": dup.nome, "sku": dup.sku or ""}}), 409
    equip = Equipamento(nome=nome)
    mudou = _aplicar_campos_equip(equip, data)
    db.session.add(equip)
    db.session.commit()
    # Paridade: o novo equipamento já nasce com seus 12 documentos no módulo Documentos.
    if _ensure_docs_for_equip(equip):
        db.session.commit()
    _registrar_historico(equip.id, {"nome": ("", nome), **mudou}, caller, evento="create")
    db.session.commit()
    log_action(caller, "CREATE", entidade=f"Equipamento: {equip.nome}", campo="nome", novo=nome, ip=get_client_ip())
    return jsonify({"mensagem": "Equipamento criado", "equipamento": equip.to_dict()}), 201

_EQUIP_STR = ["nome", "nome_original", "nome_tecnico", "descricao",
              "sku", "sku_importacao", "classificacao_reg",
              "anvisa", "anvisa_registro", "anvisa_validade",
              "classe_risco", "situacao_regulatoria",
              "fabricante", "codigo_fabricante", "status", "observacoes",
              "armazenamento_base", "responsavel"]
_EQUIP_INT = ["categoria_id", "familia_id"]
# Itens de revisão manuais do IDP (editáveis por PATCH, validados contra ESTADOS_REVISAO).
# pareto_classe/qtd_saidas NÃO entram aqui — só o importador Pareto os grava.
_EQUIP_REV = ["rev_cadastro", "rev_estrutura", "rev_descritivo"]


def sku_duplicado(sku, ignorar_id=None):
    """Outro equipamento ativo com o MESMO SKU de Venda (normalizado).

    `sku` é a chave de junção do importador mestre, do Pareto e dos documentos,
    e nada impedia gravar repetido: no banco havia SKUs duplicados só por
    diferença de caixa ("PlateSpin"/"PLATESPIN"). Compara pelo norm_sku quando o
    SKU segue o padrão NN.NNNNNN e cai em texto normalizado quando não segue.
    """
    alvo = (sku or "").strip()
    if not alvo:
        return None
    chave = norm_sku(alvo) or norm(alvo)
    query = Equipamento.query.filter(Equipamento.ativo == True,
                                     Equipamento.sku.isnot(None))
    if ignorar_id:
        query = query.filter(Equipamento.id != ignorar_id)
    for outro in query.all():
        atual = (outro.sku or "").strip()
        if atual and (norm_sku(atual) or norm(atual)) == chave:
            return outro
    return None


def _aplicar_campos_equip(equip, data):
    """Aplica os campos do payload. Devolve {campo: (antigo, novo)}.

    Antes devolvia só os nomes dos campos, e o audit gravava `valor_novo` vazio.
    Guardar o par é o que torna a alteração auditável e a aba Histórico possível.
    """
    mudou = {}

    def _troca(campo, novo):
        antigo = getattr(equip, campo)
        if novo != antigo:
            setattr(equip, campo, novo)
            mudou[campo] = (antigo, novo)

    for campo in _EQUIP_STR:
        if campo in data:
            # o caminho da pasta é canonizado na entrada (unidade mapeada → UNC)
            # para o banco não guardar duas grafias do mesmo diretório
            if campo == "armazenamento_base":
                _troca(campo, caminhos.normalizar(data.get(campo)))
            else:
                _troca(campo, (data.get(campo) or "").strip())
    if "bloqueado" in data:
        _troca("bloqueado", bool(data.get("bloqueado")))
    for campo in _EQUIP_REV:
        if campo in data:
            novo = (data.get(campo) or "").strip()
            if novo not in ESTADOS_REVISAO:
                continue  # valor inválido: ignora (mantém o estado atual)
            _troca(campo, novo)
    for campo in _EQUIP_INT:
        if campo in data:
            raw = data.get(campo)
            _troca(campo, int(raw) if raw not in (None, "", 0, "0") else None)
    # Família precisa pertencer à categoria escolhida; senão zera.
    if equip.familia_id:
        fam = FamiliaEquipamento.query.get(equip.familia_id)
        if not fam or (equip.categoria_id and fam.categoria_id != equip.categoria_id):
            if "familia_id" in mudou:
                mudou["familia_id"] = (mudou["familia_id"][0], None)
            elif equip.familia_id is not None:
                mudou["familia_id"] = (equip.familia_id, None)
            equip.familia_id = None
    return mudou


def _registrar_historico(equip_id, mudou, autor, evento="update"):
    """Uma linha de EquipamentoHistorico por campo alterado (o de-para)."""
    agora = datetime.now()
    for campo, (antigo, novo) in (mudou or {}).items():
        db.session.add(EquipamentoHistorico(
            equipamento_id=equip_id, evento=evento, campo=campo,
            valor_antigo="" if antigo is None else str(antigo),
            valor_novo="" if novo is None else str(novo),
            em=agora, por=autor or ""))


def _resumo_mudancas(mudou, limite=6):
    """Texto curto de-para para o AuditLog (que só tem colunas de texto)."""
    partes = [f"{c}: {a if a not in (None, '') else '—'} → {n if n not in (None, '') else '—'}"
              for c, (a, n) in list((mudou or {}).items())[:limite]]
    if len(mudou or {}) > limite:
        partes.append(f"(+{len(mudou) - limite})")
    return " | ".join(partes)

@app.route("/api/equipamentos/<int:equip_id>", methods=["PATCH", "PUT"])
@require_role("admin", "gestor", "tecnico")
def update_equipamento(equip_id):
    caller = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    equip = Equipamento.query.filter(Equipamento.ativo == True, Equipamento.id == equip_id).first()
    if not equip:
        return jsonify({"erro": "Equipamento não encontrado"}), 404

    if "sku" in data:
        dup = sku_duplicado(data.get("sku"), ignorar_id=equip.id)
        if dup and not data.get("ignorar_sku_duplicado"):
            return jsonify({"erro": f'SKU "{(data.get("sku") or "").strip()}" já está em '
                                    f'"{dup.nome}". Corrija o SKU ou reenvie com '
                                    f'ignorar_sku_duplicado.',
                            "sku_duplicado": {"id": dup.id, "nome": dup.nome, "sku": dup.sku or ""}}), 409

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
        _registrar_historico(equip.id, mudou, caller)
        db.session.commit()
        log_action(caller, "UPDATE", entidade=f"Equipamento: {equip.nome}",
                   campo=",".join(mudou),
                   antigo=" | ".join(f"{c}={a if a not in (None, '') else '—'}"
                                     for c, (a, _n) in mudou.items()),
                   novo=_resumo_mudancas(mudou), ip=get_client_ip())
    d = equip.to_dict()
    docs = Documento.query.filter(Documento.ativo == True,
                                  Documento.equipamento_id == equip.id).all()
    d["completude"] = eqcore.indices(equip, docs)
    return jsonify({"mensagem": "Equipamento atualizado", "equipamento": d}), 200

# ── Pastas do equipamento (grupos de documentos) ─────────────────────────────
# Cada equipamento declara as SUAS pastas de rede porque a estrutura varia:
# manuais numa, IT e checklists em outra, QI/QO/QD em outra, com caminhos que
# mudam de produto para produto. Ver EquipamentoPasta.

def _equip_ativo(equip_id):
    return Equipamento.query.filter(Equipamento.ativo == True,
                                    Equipamento.id == equip_id).first()


def _pastas_do_equip(equip_id):
    return EquipamentoPasta.query.filter(
        EquipamentoPasta.equipamento_id == equip_id,
        EquipamentoPasta.ativo == True).order_by(
        EquipamentoPasta.ordem, EquipamentoPasta.nome).all()


@app.route("/api/equipamentos/<int:equip_id>/pastas", methods=["GET"])
@jwt_required()
def listar_pastas_equipamento(equip_id):
    if not _equip_ativo(equip_id):
        return jsonify({"erro": "Equipamento não encontrado"}), 404
    return jsonify([p.to_dict() for p in _pastas_do_equip(equip_id)]), 200


@app.route("/api/equipamentos/<int:equip_id>/pastas", methods=["POST"])
@require_role("admin", "gestor", "tecnico")
def criar_pasta_equipamento(equip_id):
    caller = get_jwt_identity()
    equip = _equip_ativo(equip_id)
    if not equip:
        return jsonify({"erro": "Equipamento não encontrado"}), 404
    data = request.get_json(silent=True) or {}
    nome = (data.get("nome") or "").strip()[:80]
    if not nome:
        return jsonify({"erro": "Nome da pasta é obrigatório"}), 400
    existentes = _pastas_do_equip(equip_id)
    if any((p.nome or "").lower() == nome.lower() for p in existentes):
        return jsonify({"erro": f'Já existe uma pasta "{nome}" neste equipamento'}), 409

    pasta = EquipamentoPasta(
        equipamento_id=equip_id, nome=nome,
        caminho=caminhos.normalizar(data.get("caminho")),
        ordem=int(data.get("ordem") or len(existentes)), ativo=True)
    db.session.add(pasta)
    db.session.commit()
    log_action(caller, "CREATE", entidade=f"Equipamento: {equip.nome}",
               campo=f"pasta:{nome}", novo=pasta.caminho, ip=get_client_ip())
    return jsonify({"mensagem": "Pasta criada", "pasta": pasta.to_dict()}), 201


@app.route("/api/equipamentos/<int:equip_id>/pastas/<int:pasta_id>", methods=["PATCH", "PUT"])
@require_role("admin", "gestor", "tecnico")
def atualizar_pasta_equipamento(equip_id, pasta_id):
    caller = get_jwt_identity()
    equip = _equip_ativo(equip_id)
    if not equip:
        return jsonify({"erro": "Equipamento não encontrado"}), 404
    pasta = EquipamentoPasta.query.filter(
        EquipamentoPasta.id == pasta_id,
        EquipamentoPasta.equipamento_id == equip_id,
        EquipamentoPasta.ativo == True).first()
    if not pasta:
        return jsonify({"erro": "Pasta não encontrada"}), 404

    data = request.get_json(silent=True) or {}
    mudou = {}
    if "nome" in data:
        nome = (data.get("nome") or "").strip()[:80]
        if not nome:
            return jsonify({"erro": "Nome da pasta é obrigatório"}), 400
        if any((p.nome or "").lower() == nome.lower() and p.id != pasta.id
               for p in _pastas_do_equip(equip_id)):
            return jsonify({"erro": f'Já existe uma pasta "{nome}" neste equipamento'}), 409
        if nome != pasta.nome:
            mudou["nome"] = (pasta.nome, nome)
            pasta.nome = nome
    if "caminho" in data:
        novo = caminhos.normalizar(data.get("caminho"))
        if novo != (pasta.caminho or ""):
            mudou["caminho"] = (pasta.caminho or "", novo)
            pasta.caminho = novo
    if "ordem" in data:
        try:
            pasta.ordem = int(data.get("ordem") or 0)
        except (TypeError, ValueError):
            pass

    if mudou:
        db.session.commit()
        log_action(caller, "UPDATE", entidade=f"Equipamento: {equip.nome}",
                   campo=f"pasta:{pasta.nome}",
                   antigo=" | ".join(f"{c}={a or '—'}" for c, (a, _n) in mudou.items()),
                   novo=" | ".join(f"{c}={n or '—'}" for c, (_a, n) in mudou.items()),
                   ip=get_client_ip())
    return jsonify({"mensagem": "Pasta atualizada", "pasta": pasta.to_dict()}), 200


@app.route("/api/equipamentos/<int:equip_id>/pastas/<int:pasta_id>", methods=["DELETE"])
@require_role("admin", "gestor")
def remover_pasta_equipamento(equip_id, pasta_id):
    """Remove a pasta e devolve os documentos dela ao caminho do equipamento.

    Soft delete: desvincular os documentos antes é o que evita deixá-los
    apontando para uma pasta que sumiu — nesse estado o caminho efetivo cairia
    silenciosamente para o do equipamento sem ninguém saber por quê.
    """
    caller = get_jwt_identity()
    equip = _equip_ativo(equip_id)
    if not equip:
        return jsonify({"erro": "Equipamento não encontrado"}), 404
    pasta = EquipamentoPasta.query.filter(
        EquipamentoPasta.id == pasta_id,
        EquipamentoPasta.equipamento_id == equip_id,
        EquipamentoPasta.ativo == True).first()
    if not pasta:
        return jsonify({"erro": "Pasta não encontrada"}), 404

    soltos = Documento.query.filter(Documento.pasta_id == pasta.id).update(
        {Documento.pasta_id: None}, synchronize_session=False)
    pasta.ativo = False
    db.session.commit()
    log_action(caller, "DELETE", entidade=f"Equipamento: {equip.nome}",
               campo=f"pasta:{pasta.nome}", antigo=pasta.caminho or "",
               novo=f"removida (+{soltos} docs desvinculados)", ip=get_client_ip())
    return jsonify({"mensagem": "Pasta removida", "documentos_desvinculados": soltos}), 200


@app.route("/api/equipamentos/<int:equip_id>", methods=["DELETE"])
@require_role("admin", "gestor")
def delete_equipamento(equip_id):
    caller = get_jwt_identity()
    equip = Equipamento.query.filter(Equipamento.ativo == True, Equipamento.id == equip_id).first()
    if not equip:
        return jsonify({"erro": "Equipamento não encontrado"}), 404
    equip.ativo = False                       # soft delete (reversível no banco)
    equip.updated_em = datetime.now()
    _registrar_historico(equip.id, {"ativo": (True, False)}, caller, evento="delete")
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
    """CSV conforme os filtros da tela, com os índices que o dashboard calcula.

    O export ignorava os filtros e devolvia 12 colunas fixas: quem exportava
    perdia exatamente ICE/IDP, classe ABC, saídas, descrição e observações — os
    campos pelos quais a tela ordena.
    """
    import csv
    equips = _query_equipamentos().all()
    termo = request.args.get("q", "")
    if termo:
        ids = {e["id"] for e in _filtrar_busca([e.to_dict() for e in equips], termo)}
        equips = [e for e in equips if e.id in ids]
    por_equip = _docs_dos_equipamentos([e.id for e in equips])
    indices = {e.id: eqcore.indices(e, por_equip.get(e.id, [])) for e in equips}

    # Mesma ordenação da tela (o CSV sempre saía por nome, mesmo com a lista
    # ordenada por ICE ou atraso).
    _CLASSE = {"A": 0, "B": 1, "C": 2, "": 3}
    _ORDENS = {
        "ice":        lambda e: (indices[e.id]["ice"], (e.nome or "").lower()),
        "ice-desc":   lambda e: (-indices[e.id]["ice"], (e.nome or "").lower()),
        "atraso":     lambda e: (-indices[e.id]["docs_atrasados"],
                                 -indices[e.id]["atraso_max"], indices[e.id]["ice"]),
        "classe":     lambda e: (_CLASSE.get(e.pareto_classe or "", 3), -(e.qtd_saidas or 0)),
        "atualizado": lambda e: (e.updated_em or datetime.min),
    }
    chave = _ORDENS.get(request.args.get("ordem", ""))
    if chave:
        equips = sorted(equips, key=chave)

    cols = ["sku", "sku_importacao", "nome", "nome_tecnico",
            "categoria", "familia", "status", "bloqueado", "responsavel",
            "classificacao_reg", "anvisa", "anvisa_registro", "anvisa_validade",
            "classe_risco", "situacao_regulatoria",
            "fabricante", "codigo_fabricante",
            "descricao", "observacoes", "criado_em", "updated_em"]
    extras = ["ice", "ice_cadastro", "ice_regulatorio", "ice_documental", "idp",
              "docs_finais", "docs_alvo", "docs_atrasados", "registro_situacao",
              "pareto_classe", "qtd_saidas"]
    buf = io.StringIO(); w = csv.writer(buf, delimiter=";")
    w.writerow(cols + extras)
    for e in equips:
        d = e.to_dict()
        c = indices[e.id]
        w.writerow([d.get(k, "") for k in cols] + [
            c["ice"], c["cad"], c["reg"], c["doc"],
            "" if c["idp"] is None else c["idp"],
            c["docs_finais"], c["docs_alvo"], c["docs_atrasados"], c["reg_estado"],
            d.get("pareto_classe", ""), d.get("qtd_saidas", 0),
        ])
    out = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    return send_file(out, mimetype="text/csv", as_attachment=True, download_name="equipamentos.csv")


@app.route("/api/equipamentos/<int:equip_id>/historico", methods=["GET"])
@jwt_required()
def api_equipamento_historico(equip_id):
    """Trilha de alterações do equipamento (o que a aba Histórico da ficha mostra).

    Endpoint próprio em vez de reusar /api/audit: aquele exige gestor+ e não
    filtra por entidade, então o técnico que edita a ficha não veria o próprio
    histórico.
    """
    equip = Equipamento.query.filter(Equipamento.id == equip_id).first()
    if not equip:
        return jsonify({"erro": "Equipamento não encontrado"}), 404
    try:
        limite = max(1, min(int(request.args.get("limit", 100)), 500))
    except (TypeError, ValueError):
        return jsonify({"erro": "limit deve ser numérico"}), 400
    linhas = (EquipamentoHistorico.query
              .filter(EquipamentoHistorico.equipamento_id == equip_id)
              .order_by(EquipamentoHistorico.em.desc(), EquipamentoHistorico.id.desc())
              .limit(limite).all())
    return jsonify([l.to_dict() for l in linhas]), 200


@app.route("/api/equipamentos/<int:equip_id>/evolucao", methods=["GET"])
@jwt_required()
def api_equipamento_evolucao(equip_id):
    """Série temporal do equipamento: ICE/IDP por dia + histórico de Pareto."""
    equip = Equipamento.query.filter(Equipamento.ativo == True,
                                     Equipamento.id == equip_id).first()
    if not equip:
        return jsonify({"erro": "Equipamento não encontrado"}), 404
    snaps = (EquipamentoSnapshot.query
             .filter(EquipamentoSnapshot.equipamento_id == equip_id)
             .order_by(EquipamentoSnapshot.data).all())
    pareto = (ParetoHistorico.query
              .filter(ParetoHistorico.equipamento_id == equip_id)
              .order_by(ParetoHistorico.data).all())
    docs = Documento.query.filter(Documento.ativo == True,
                                  Documento.equipamento_id == equip_id).all()
    return jsonify({
        "snapshots": [s.to_dict() for s in snaps],
        "pareto": [p.to_dict() for p in pareto],
        "atual": eqcore.indices(equip, docs),
    }), 200


@app.route("/api/equipamentos/evolucao", methods=["GET"])
@jwt_required()
def api_equipamentos_evolucao():
    """Média da frota por dia — a curva que responde 'o cadastro está avançando?'."""
    from sqlalchemy import func
    linhas = (db.session.query(
                  EquipamentoSnapshot.data,
                  func.avg(EquipamentoSnapshot.ice),
                  func.avg(EquipamentoSnapshot.cad),
                  func.avg(EquipamentoSnapshot.reg),
                  func.avg(EquipamentoSnapshot.doc),
                  func.avg(EquipamentoSnapshot.idp),
                  func.count(EquipamentoSnapshot.id))
              .group_by(EquipamentoSnapshot.data)
              .order_by(EquipamentoSnapshot.data).all())
    return jsonify([{
        "data": data, "ice": round(ice or 0), "cad": round(cad or 0),
        "reg": round(reg or 0), "doc": round(doc or 0),
        "idp": None if idp is None else round(idp), "n": n,
    } for data, ice, cad, reg, doc, idp, n in linhas]), 200


def _chave_sku(sku):
    texto = (sku or "").strip()
    return (norm_sku(texto) or norm(texto)) if texto else ""


# Caracteres de encoding quebrado (mojibake) que sobraram de importações antigas:
# "Extracta� Prep" está gravado assim no banco e é invisível na tela.
_MOJIBAKE = ("�", "Ã©", "Ã£", "Ãµ", "Ã§", "Ã¡", "Ã­", "Ã³", "Ãº", "Â")


@app.route("/api/equipamentos/saude", methods=["GET"])
@jwt_required()
def api_equipamentos_saude():
    """Problemas de integridade do cadastro que só apareciam rodando script.

    Duplicidade de SKU/nome, texto corrompido, equipamento sem documento e
    documento ativo sem equipamento — tudo o que quebra o casamento por SKU dos
    importadores e some do ICE sem aviso.
    """
    equips = Equipamento.query.filter(Equipamento.ativo == True).order_by(Equipamento.nome).all()
    por_equip = _docs_dos_equipamentos([e.id for e in equips])

    def _agrupar(chave_fn):
        grupos = {}
        for e in equips:
            k = chave_fn(e)
            if k:
                grupos.setdefault(k, []).append(e)
        return [{"chave": k, "itens": [{"id": x.id, "nome": x.nome, "sku": x.sku or ""} for x in v]}
                for k, v in sorted(grupos.items()) if len(v) > 1]

    def _tem_mojibake(e):
        blob = " ".join(str(getattr(e, c, "") or "") for c in
                        ("nome", "nome_tecnico", "nome_original", "descricao", "fabricante"))
        return any(m in blob for m in _MOJIBAKE)

    sem_docs = [{"id": e.id, "nome": e.nome, "sku": e.sku or ""}
                for e in equips if not por_equip.get(e.id)]
    sem_sku = [{"id": e.id, "nome": e.nome} for e in equips if not (e.sku or "").strip()]
    corrompidos = [{"id": e.id, "nome": e.nome, "sku": e.sku or ""}
                   for e in equips if _tem_mojibake(e)]
    orfaos = Documento.query.filter(Documento.ativo == True,
                                    Documento.equipamento_id.is_(None)).all()
    vencidos, vencendo = [], []
    for e in equips:
        st = eqcore.status_validade(e)
        item = {"id": e.id, "nome": e.nome, "validade": st["data"], "dias": st["dias"]}
        if st["estado"] == "vencido":
            vencidos.append(item)
        elif st["estado"] == "vencendo":
            vencendo.append(item)

    return jsonify({
        "total": len(equips),
        "sku_duplicado":  _agrupar(lambda e: _chave_sku(e.sku)),
        "nome_duplicado": _agrupar(lambda e: norm(e.nome)),
        "texto_corrompido": corrompidos,
        "sem_documentos": sem_docs,
        "sem_sku": sem_sku,
        "docs_orfaos": [{"id": d.id, "documento": d.documento or "",
                         "equipamento": d.equipamento or "", "sku": d.sku or ""}
                        for d in orfaos],
        "registro_vencido": sorted(vencidos, key=lambda x: x["dias"] or 0),
        "registro_vencendo": sorted(vencendo, key=lambda x: x["dias"] or 0),
    }), 200


def _snapshot_equipamentos(dia=None):
    """Grava (ou atualiza) a foto do dia para todos os equipamentos ativos.

    Idempotente: rodar duas vezes no mesmo dia sobrescreve a linha em vez de
    duplicar — a UniqueConstraint (equipamento, data) é quem garante isso.
    """
    dia = dia or date.today().isoformat()
    equips = Equipamento.query.filter(Equipamento.ativo == True).all()
    if not equips:
        return 0
    por_equip = _docs_dos_equipamentos([e.id for e in equips])
    existentes = {s.equipamento_id: s for s in EquipamentoSnapshot.query.filter(
        EquipamentoSnapshot.data == dia).all()}
    for e in equips:
        c = eqcore.indices(e, por_equip.get(e.id, []))
        snap = existentes.get(e.id) or EquipamentoSnapshot(equipamento_id=e.id, data=dia)
        snap.ice, snap.cad, snap.reg, snap.doc = c["ice"], c["cad"], c["reg"], c["doc"]
        snap.idp = c["idp"]
        snap.docs_finais, snap.docs_alvo = c["docs_finais"], c["docs_alvo"]
        snap.docs_atrasados = c["docs_atrasados"]
        if e.id not in existentes:
            db.session.add(snap)
    db.session.commit()
    return len(equips)


@app.route("/api/equipamentos/snapshot", methods=["POST"])
@require_role("admin", "gestor")
def api_equipamentos_snapshot():
    n = _snapshot_equipamentos(request.args.get("data"))
    return jsonify({"mensagem": "Snapshot gravado", "equipamentos": n}), 200

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
        _registrar_importacao("mestra", caller, rel)
        log_action(caller, "REIMPORT", entidade="Equipamentos (planilha mestra)",
                   campo="import", novo=f"criados={rel['a_criar']} atualizados={rel['a_atualizar']}",
                   ip=get_client_ip())
    return jsonify(rel), 200


def _registrar_importacao(origem, autor, rel):
    """Guarda o relatório completo da importação aplicada.

    Só sobrava uma linha resumida no AuditLog: depois de aplicar não dava mais
    para rever quais SKUs não casaram nem quais linhas vieram inconsistentes.
    """
    db.session.add(ImportacaoLog(
        origem=origem, por=autor or "",
        criados=rel.get("a_criar", 0), atualizados=rel.get("a_atualizar", 0),
        sem_match=rel.get("sem_match_n", 0),
        inconsistencias=rel.get("inconsistencias_n", 0),
        relatorio=json.dumps(rel, ensure_ascii=False, default=str)))
    db.session.commit()


@app.route("/api/equipamentos/importacoes", methods=["GET"])
@require_role("admin", "gestor")
def api_importacoes():
    try:
        limite = max(1, min(int(request.args.get("limit", 20)), 100))
    except (TypeError, ValueError):
        return jsonify({"erro": "limit deve ser numérico"}), 400
    linhas = (ImportacaoLog.query.order_by(ImportacaoLog.em.desc())
              .limit(limite).all())
    detalhe = request.args.get("detalhe") in ("1", "true", "sim")
    return jsonify([l.to_dict(com_relatorio=detalhe) for l in linhas]), 200


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
        _registrar_importacao("pareto", caller, rel)
        log_action(caller, "REIMPORT", entidade="Equipamentos (Pareto ABC)",
                   campo="import", novo=f"atualizados={rel['a_atualizar']} sem_match={rel['sem_match_n']}",
                   ip=get_client_ip())
    return jsonify(rel), 200

# ── API — TAXONOMIA (Categorias · Famílias) ──────────────────────────────────
# A linha de produto saiu daqui: era um agrupamento transversal que na prática
# repetia a família, e manter os dois obrigava a classificar o equipamento duas
# vezes pela mesma coisa.
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
        "setor_processo": SETOR_PROCESSO,
        "setores_todos": SETORES_TODOS,
        "status_map": STATUS_MAP,
        "tipos_doc_pre": TIPOS_DOC_PRE,
        "tipos_doc_fabricante": TIPOS_DOC_FABRICANTE,
        "tipos_doc_todos": TIPOS_DOC_TODOS,
        "tipos_doc_opcionais": TIPOS_DOC_OPCIONAIS,
        "setor_do_tipo": SETOR_DO_TIPO,
        "tipos_doc_labels": TIPOS_DOC_LABELS,
        "motivos_na": MOTIVOS_NA,
        "motivo_na_livre": MOTIVO_NA_LIVRE,
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
    
    # Template do relatório HTML. Mora em templates/, mas é lido como arquivo
    # cru (substituição de string abaixo), não renderizado pelo Jinja.
    template_path = os.path.join(BASE_DIR, "templates", "audit_log_report.html")
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

# /api/reimport foi REMOVIDA. Ela disparava _import_excel_to_db() numa thread
# solta, e aquela função dropava as tabelas `documentos` e `documento_historico`
# antes de reinserir a planilha — um POST de qualquer gestor apagava o banco de
# documentos inteiro. O botão da UI já tinha sido retirado, então a rota estava
# sem chamador nenhum: só o estrago continuava alcançável. O seed por planilha
# segue existindo em `servidor.py --init` (init_db), agora sem destruir nada.
# Para atualizar dados em massa use o import de equipamentos ou a própria UI.


@app.route("/api/admin/tarefas-diarias", methods=["POST"])
@require_role("admin")
def api_tarefas_diarias():
    """Dispara agora as fotos do dia (equipamentos, missões, projetos).

    O agendador interno já faz isso todo dia (ver scheduler.py); esta rota é o
    escape para quando alguém quer a medição na hora, sem reiniciar o serviço.
    """
    resultado = rodar_uma_vez(app, rodar_tarefas_diarias, forcar=True)
    return jsonify({"executado": bool(resultado),
                    "mensagem": "Tarefas diárias executadas."}), 200


@app.route("/api/status")
@require_role("admin", "gestor")
def api_status():
    """Estado do ambiente — infra real para a tela de Configurações.

    Exigia zero autenticação e devolvia o caminho absoluto do banco e da
    planilha no servidor, mais a contagem de usuários: um mapa da instalação
    para quem só conseguisse alcançar a porta. Os caminhos completos saíram;
    ficou o nome do arquivo, que é o que a tela precisa mostrar.
    """
    exists = os.path.exists(EXCEL_PATH)
    mtime = datetime.fromtimestamp(os.path.getmtime(EXCEL_PATH)).strftime("%d/%m/%Y %H:%M") if exists else ""
    dialeto = db.engine.dialect.name
    return jsonify({
        "excel_found": exists,
        "excel_nome": os.path.basename(EXCEL_PATH),
        "excel_modified": mtime,
        "db_nome": os.path.basename(DB_PATH) if dialeto == "sqlite" else "doctrack",
        "db_engine": "SQLite" if dialeto == "sqlite" else dialeto.capitalize(),
        "versao": APP_VERSION,
        "usuarios": User.query.count(),
        "documentos": Documento.query.filter(Documento.ativo == True).count(),
        "agendador": agendador_habilitado(),
    }), 200

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
    _bool_true  = "TRUE"  if db.engine.dialect.name == "postgresql" else "1"
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
            ("status",           "VARCHAR(20) DEFAULT 'execucao' NOT NULL"),
        ],
        "entregaveis": [
            ("data_inicio",    "VARCHAR(10) DEFAULT ''"),
            ("data_conclusao", "VARCHAR(10) DEFAULT ''"),
            ("peso",           "FLOAT DEFAULT 1"),
            ("data_inicio_prev", "VARCHAR(10) DEFAULT ''"),
            ("data_fim_prev",    "VARCHAR(10) DEFAULT ''"),
        ],
        "modelos_entregavel": [
            ("peso", "FLOAT DEFAULT 1"),
        ],
        "projeto_mensal": [
            ("custo_mes", "FLOAT DEFAULT 0"),
        ],
        # Documentos já existentes nascem aplicavel=TRUE pelo DEFAULT da coluna —
        # é o backfill que queremos: existir significa que se aplica.
        "documentos": [
            ("equipamento_id", "INTEGER"),
            ("aplicavel",      f"BOOLEAN DEFAULT {_bool_true} NOT NULL"),
            ("motivo_na",      "VARCHAR(300) DEFAULT ''"),
            ("motivo_na_codigo", "VARCHAR(40) DEFAULT ''"),
            ("prazo",          "DATE"),
            # Marcos temporais: nascem nulos (ADD COLUMN não aceita default não
            # constante) e são preenchidos por _backfill_marcos_documentos a
            # partir da trilha. Ver migration 011.
            ("concluido_em",     "TIMESTAMP"),
            ("concluido_por",    "VARCHAR(120) DEFAULT ''"),
            ("entrou_status_em", "TIMESTAMP"),
            ("data_inicio",      "DATE"),
            ("peso",             "FLOAT DEFAULT 1"),
            # Grupo de pastas do equipamento (ver EquipamentoPasta). A tabela
            # em si é criada por create_all; aqui só a FK na tabela existente.
            ("pasta_id",         "INTEGER"),
        ],
        "equipamentos": [
            ("nome_tecnico",      "VARCHAR(400) DEFAULT ''"),
            ("descricao",         "TEXT DEFAULT ''"),
            ("sku_importacao",    "VARCHAR(50) DEFAULT ''"),
            ("status",            "VARCHAR(40) DEFAULT 'Ativo'"),
            ("bloqueado",         f"BOOLEAN DEFAULT {_bool_false} NOT NULL"),
            ("observacoes",       "TEXT DEFAULT ''"),
            ("categoria_id",      "INTEGER"),
            ("familia_id",        "INTEGER"),
            ("classificacao_reg", "VARCHAR(20) DEFAULT ''"),
            ("codigo_fabricante", "VARCHAR(80) DEFAULT ''"),
            ("rev_cadastro",      "VARCHAR(20) DEFAULT 'Pendente'"),
            ("rev_estrutura",     "VARCHAR(20) DEFAULT 'Pendente'"),
            ("rev_descritivo",    "VARCHAR(20) DEFAULT 'Pendente'"),
            ("pareto_classe",     "VARCHAR(1) DEFAULT ''"),
            ("qtd_saidas",        "INTEGER DEFAULT 0"),
            ("responsavel",       "VARCHAR(120) DEFAULT ''"),
            ("classe_risco",         "VARCHAR(10) DEFAULT ''"),
            ("situacao_regulatoria", "VARCHAR(30) DEFAULT ''"),
        ],
        # Missões: o módulo gravava estado, não processo. Os marcos temporais
        # nascem nulos (ADD COLUMN não aceita default não-constante) e são
        # preenchidos no backfill logo abaixo. Ver migration 010.
        "missao_colunas": [
            ("limite_wip", "INTEGER DEFAULT 0"),
        ],
        "missao_cartoes": [
            ("criado_em",        "TIMESTAMP"),
            ("concluido_em",     "TIMESTAMP"),
            ("concluido_por",    "VARCHAR(120) DEFAULT ''"),
            ("entrou_coluna_em", "TIMESTAMP"),
            ("data_inicio",      "VARCHAR(40) DEFAULT ''"),
            ("peso",             "FLOAT DEFAULT 1"),
            ("recorrencia",      "VARCHAR(20) DEFAULT ''"),
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

    # Índices em tabelas que já existiam: create_all() cria a tabela nova com os
    # índices do modelo, mas não adiciona índice a tabela existente.
    novos_indices = [
        # /api/audit e o export ordenam por timestamp DESC e filtram por período.
        # A coluna não tinha índice: cada abertura da tela de auditoria era um
        # full scan + sort da tabela que mais cresce no sistema.
        ("ix_audit_logs_timestamp", "audit_logs", "timestamp"),
    ]
    for nome_idx, tabela, coluna in novos_indices:
        if tabela not in existentes:
            continue
        if nome_idx in {i["name"] for i in insp.get_indexes(tabela)}:
            continue
        try:
            db.session.execute(text(
                f"CREATE INDEX {nome_idx} ON {tabela} ({coluna})"))
            db.session.commit()
            print(f"[INFO] Schema: índice {nome_idx} criado")
        except Exception as e:
            db.session.rollback()
            print(f"[WARN] Schema: índice {nome_idx} não criado — {e}")

    # Missões: os cartões que já existiam não têm criação registrada em lugar
    # nenhum — `atualizado_em` é o limite superior conhecido e não inventa data
    # futura. Sem isso nem a idade do cartão era derivável.
    if "missao_cartoes.criado_em" in adicionadas:
        db.session.execute(text(
            "UPDATE missao_cartoes SET criado_em = atualizado_em WHERE criado_em IS NULL"))
        db.session.execute(text(
            "UPDATE missao_cartoes SET entrou_coluna_em = COALESCE(atualizado_em, criado_em) "
            "WHERE entrou_coluna_em IS NULL"))
        db.session.execute(text(
            f"UPDATE missao_cartoes SET concluido_em = atualizado_em "
            f"WHERE concluido = {_bool_true} AND concluido_em IS NULL"))
        db.session.commit()
        print("[INFO] Missões: marcos temporais dos cartões existentes preenchidos")

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

    # Ciclo de vida: projetos já arquivados não eram distinguíveis entre
    # "terminou" e "morreu no meio". Deduz pelo avanço uma única vez.
    if "projetos.status" in adicionadas:
        db.session.execute(text(
            "UPDATE projetos SET status = 'execucao' WHERE ativo = %s" % _bool_true))
        arquivados = db.session.execute(text(
            "SELECT id FROM projetos WHERE ativo = %s" % _bool_false)).fetchall()
        from models import Projeto as _P
        for (pid,) in arquivados:
            proj = db.session.get(_P, pid)
            if proj is None:
                continue
            proj.status = "concluido" if proj.avanco >= 100 else "cancelado"
        db.session.commit()
        print(f"[INFO] Schema: status deduzido para {len(arquivados)} projeto(s) arquivado(s)")

    # Linha de base v1 para projetos que nasceram antes do versionamento — sem
    # isto o histórico começaria vazio e não haveria com o que comparar.
    _tabelas = set(_sa_inspect(db.engine).get_table_names())
    if "projeto_baseline" in _tabelas:
        from models import Projeto as _P, ProjetoBaseline as _B
        sem_base = (db.session.query(_P.id)
                    .outerjoin(_B, _B.projeto_id == _P.id)
                    .filter(_B.id.is_(None)).all())
        for (pid,) in sem_base:
            proj = db.session.get(_P, pid)
            if proj is not None:
                proj.registrar_baseline("system", motivo="Linha de base inicial (migração)")
        if sem_base:
            db.session.commit()
            print(f"[INFO] Schema: linha de base v1 criada para {len(sem_base)} projeto(s)")

    # Responsáveis: liga o texto livre ("Guilherme/Melk") aos usuários reais.
    # Best-effort pelo primeiro nome; o que não casar continua só como texto.
    if "entregavel_responsaveis" in _tabelas:
        ja = db.session.execute(
            text("SELECT COUNT(*) FROM entregavel_responsaveis")).scalar()
        if not ja:
            from models import Entregavel as _E, User as _U
            usuarios = _U.query.filter_by(ativo=True).all()
            por_primeiro = {}
            for u in usuarios:
                chave = (u.nome or "").strip().split(" ")[0].lower()
                if chave:
                    por_primeiro.setdefault(chave, []).append(u)
            ligados = 0
            for e in _E.query.filter(_E.responsaveis != "").all():
                achados = []
                for parte in re.split(r"[/,;e&]| e ", (e.responsaveis or "").lower()):
                    parte = parte.strip()
                    cands = por_primeiro.get(parte) or []
                    # nome ambíguo (dois "Carlos") não é adivinhado: fica só texto
                    if len(cands) == 1 and cands[0] not in achados:
                        achados.append(cands[0])
                if achados:
                    e.responsaveis_users = achados
                    ligados += 1
            db.session.commit()
            print(f"[INFO] Schema: {ligados} entregável(is) com responsáveis vinculados a usuários")

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


def _migrar_taxonomia_docs():
    """Migração one-time da taxonomia de tipos (idempotente, roda a cada boot):
    1) 'Checklist' genérico → 'Checklist_Conferencia' (o processo real tem 4
       checklists por IT; o genérico herda os dados no de Conferência).
    2) Opcionais (Spare Parts / Dossiê / QIQOQD) ATIVOS e em branco viram N/A
       (aplicavel=False): continuam existindo, fora da completude, até alguém
       ligá-los na aba Escopo. Os que têm qualquer dado preenchido continuam
       aplicáveis.

    Documentos INATIVOS nunca são tocados. A migração não ressuscita nada: um
    soft delete é uma decisão de alguém (exclusão manual, cascade do equipamento,
    deduplicação) e desfazê-la a cada boot ressuscitaria o que foi apagado de
    propósito. Se um tipo ficar sem documento ativo, quem repõe é o
    _backfill_equipamentos, criando UMA linha nova em N/A — o que também evita
    a duplicata (só existe 1 documento ativo por equipamento × tipo).
    Os 3 checklists novos que faltarem são criados pelo mesmo backfill
    (via TIPOS_DOC_TODOS), que roda logo depois."""
    # 1) rename do tipo genérico, preservando dados
    renomeados = 0
    for d in Documento.query.filter(Documento.tipo_doc == "Checklist").all():
        d.tipo_doc = "Checklist_Conferencia"
        # atualiza só o nome-padrão ("Checklist - X"); nomes customizados ficam
        if (d.documento or "").startswith("Checklist - "):
            d.documento = d.documento.replace(
                "Checklist - ", "Checklist de Conferência - ", 1)
        renomeados += 1

    # 2) opcionais ATIVOS e em branco → N/A (critério conservador: qualquer dado salva).
    #    Os inativos ficam como estão — ver docstring: nada é ressuscitado aqui.
    marcados = 0
    base_por_equip = {e.id: (e.armazenamento_base or "").strip()
                      for e in Equipamento.query.all()}
    candidatos = Documento.query.filter(
        Documento.ativo == True,
        Documento.tipo_doc.in_(TIPOS_DOC_OPCIONAIS)).all()
    for d in candidatos:
        arm = (d.armazenamento or "").strip()
        arm_base = base_por_equip.get(d.equipamento_id, "")
        em_branco = (
            not (d.codigo_doc or "").strip()
            and not (d.responsavel or "").strip()
            and (d.status or "Elaborar") == "Elaborar"
            and d.data_treinamento is None and d.data_homologacao is None
            and not (d.obs_treinamento or "").strip()
            and not (d.obs_homologacao or "").strip()
            and (not arm or arm == arm_base)
        )
        if not em_branco:
            continue                     # tem dado → aplicável, não se mexe
        if d.aplicavel:                   # idempotente: só conta quem de fato mudou
            d.aplicavel = False
            marcados += 1

    if renomeados or marcados:
        db.session.commit()
        print(f"[INFO] Taxonomia de documentos: {renomeados} 'Checklist' renomeados; "
              f"{marcados} opcionais em branco marcados como N/A.")


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

    novos_equip = novos_docs = revinculados = 0
    # A busca do equipamento precisa considerar SÓ os ativos. Sem esse filtro, um
    # documento ativo se prendia a uma entidade já excluída: seguia visível em
    # Documentos e invisível em Equipamentos — foi essa a origem da divergência
    # entre os dois módulos (18 equipamentos, 139 documentos, jul/2026).
    ativos_por_nome = {e.nome: e for e in
                       Equipamento.query.filter(Equipamento.ativo == True).all()}

    for nome, docs in grupos.items():
        equip = ativos_por_nome.get(nome)
        if not equip:
            equip = Equipamento(
                nome=nome,
                sku=_primeiro(docs, "sku"),
                fabricante=_primeiro(docs, "fabricante"),
                armazenamento_base=_primeiro(docs, "armazenamento"),
            )
            db.session.add(equip)
            db.session.flush()           # garante equip.id
            ativos_por_nome[nome] = equip
            novos_equip += 1

        for d in docs:
            if not d.equipamento_id:     # documento ainda solto
                d.equipamento_id = equip.id
            elif d.equipamento_id != equip.id and not (
                    d.equipamento_rel and d.equipamento_rel.ativo):
                # Preso a um equipamento excluído: devolve ao ativo de mesmo nome.
                # Homônimos ATIVOS não são reatribuídos — evita "pingar" entre eles.
                d.equipamento_id = equip.id
                revinculados += 1

    db.session.flush()

    # 3) Paridade total Equipamentos ↔ Documentos: TODO equipamento ativo —
    #    inclusive os importados da planilha (sem documentos) — recebe os 9 tipos
    #    faltantes, para aparecer também no módulo Documentos. Idempotente: só
    #    cria o que falta (verifica os tipos já existentes por equipamento_id).
    for equip in Equipamento.query.filter(Equipamento.ativo == True).all():
        novos_docs += _ensure_docs_for_equip(equip)

    db.session.commit()
    if novos_equip or novos_docs or revinculados:
        print(f"[INFO] Equipamentos: {novos_equip} criados; {novos_docs} documentos "
              f"completados; {revinculados} documentos revinculados a equipamento ativo.")


def _normalizar_caminhos_armazenados():
    """Canoniza os caminhos já gravados (unidade mapeada → UNC). Idempotente.

    O banco acumulou as duas grafias do MESMO diretório porque cada usuário
    colava o que via: quem copiou da barra do Explorer gravou `P:\\Engenharia\\...`,
    quem copiou de outro registro gravou a UNC. As formas com letra falhavam na
    allowlist e no acesso a disco do serviço (que não tem mapeamento de unidade),
    e ainda impediam `_consolidar_armazenamento` de reconhecer que documento e
    equipamento apontam para a mesma pasta.

    Roda no boot, antes da consolidação, para que ela compare valores canônicos.
    """
    ajustados = 0
    for equip in Equipamento.query.all():
        atual = equip.armazenamento_base or ""
        novo = caminhos.normalizar(atual)
        if novo != atual:
            equip.armazenamento_base = novo
            ajustados += 1
    for doc in Documento.query.all():
        atual = doc.armazenamento or ""
        novo = caminhos.normalizar(atual)
        if novo != atual:
            doc.armazenamento = novo
            ajustados += 1
    if ajustados:
        db.session.commit()
        print(f"[INFO] Armazenamento: {ajustados} caminho(s) canonizados para a forma UNC.")


def _consolidar_armazenamento():
    """Elege o caminho PADRÃO do equipamento e limpa as cópias redundantes.

    ATENÇÃO — a premissa original desta rotina ("1 caminho distinto por
    equipamento em 100% dos casos") está errada e foi medida como tal: 14
    equipamentos têm de 2 a 4 pastas distintas, porque a estrutura real separa
    manuais, IT/checklists e QI/QO/QD em pastas diferentes. Quem representa isso
    hoje é EquipamentoPasta; o que sobra aqui é eleger o caminho padrão do
    equipamento (o mais frequente) e evitar 12 cópias da mesma string.

    Editar numa aba não refletia nas outras 11. Aqui:
      1) equipamento sem armazenamento_base herda o caminho mais frequente entre
         os seus documentos;
      2) documento cujo caminho é igual ao do equipamento passa a herdar (fica
         em branco). Caminho DIFERENTE é preservado — é um override real.
    Idempotente.
    """
    promovidos = limpos = 0
    equips = Equipamento.query.filter(Equipamento.ativo == True).all()
    for equip in equips:
        docs = Documento.query.filter(Documento.ativo == True,
                                      Documento.equipamento_id == equip.id).all()
        if not docs:
            continue
        base = (equip.armazenamento_base or "").strip()
        if not base:
            freq = {}
            for d in docs:
                p = (d.armazenamento or "").strip()
                if p:
                    freq[p] = freq.get(p, 0) + 1
            if freq:
                base = max(freq.items(), key=lambda kv: kv[1])[0]
                equip.armazenamento_base = base
                promovidos += 1
        if not base:
            continue
        for d in docs:
            if (d.armazenamento or "").strip() == base:
                d.armazenamento = ""      # passa a herdar do equipamento
                limpos += 1
    if promovidos or limpos:
        db.session.commit()
        print(f"[INFO] Armazenamento: {promovidos} equipamento(s) receberam o caminho base; "
              f"{limpos} documento(s) passaram a herdar (cópias redundantes removidas).")


def _nomes_de_pastas(lista_caminhos, base):
    """Nome curto e único para cada pasta, derivado do próprio caminho.

    A pasta igual à do equipamento vira "Principal"; as demais herdam o nome da
    folha (`...\\Documentos\\Manuais` → "Manuais"). Quando duas folhas colidem
    (`...\\A\\Manuais` e `...\\B\\Manuais`), TODAS as envolvidas sobem um nível
    ("A\\Manuais", "B\\Manuais"). Desambiguar só a segunda deixaria "Manuais" e
    "B\\Manuais" lado a lado, e ninguém saberia qual é qual.

    Devolve {caminho: nome}.
    """
    import ntpath
    import collections

    bruto = {}
    for caminho in lista_caminhos:
        if base and caminho.lower() == base.lower():
            bruto[caminho] = "Principal"
        else:
            bruto[caminho] = ntpath.basename(caminho) or caminho

    repetidos = {n.lower() for n, c in collections.Counter(bruto.values()).items() if c > 1}
    nomes, usados = {}, set()
    for caminho, nome in bruto.items():
        if nome.lower() in repetidos:
            pai = ntpath.basename(ntpath.dirname(caminho))
            if pai:
                nome = f"{pai}\\{nome}"
        final, n = nome, 2
        while final.lower() in usados:      # empate que sobreviveu: numera
            final = f"{nome} ({n})"
            n += 1
        usados.add(final.lower())
        nomes[caminho] = final
    return nomes


def _backfill_pastas_equipamento():
    """Converte os caminhos já gravados em pastas nomeadas por equipamento.

    Até aqui a estrutura real de rede — manuais numa pasta, IT e checklists em
    outra — só era representável marcando uma "exceção" em cada documento. Este
    backfill lê o que já está no banco e materializa os grupos: cada caminho
    EFETIVO distinto de um equipamento vira uma EquipamentoPasta, e os documentos
    que apontavam para ele passam a apontar para a pasta.

    Preserva o caminho efetivo de todo documento (só muda de onde ele vem), e o
    `armazenamento` do documento é limpo porque a informação passou para a pasta.
    Idempotente: equipamento que já tem pasta é pulado.
    """
    criadas = vinculados = 0
    equips = Equipamento.query.filter(Equipamento.ativo == True).all()
    ja_tem = {p.equipamento_id for p in EquipamentoPasta.query.all()}

    for equip in equips:
        if equip.id in ja_tem:
            continue
        docs = Documento.query.filter(Documento.ativo == True,
                                      Documento.equipamento_id == equip.id).all()
        base = caminhos.normalizar(equip.armazenamento_base)
        # caminho efetivo de cada documento, na ordem em que aparecem
        efetivos = []
        for d in docs:
            efet = caminhos.normalizar(d.armazenamento) or base
            if efet and efet.lower() not in {e.lower() for e in efetivos}:
                efetivos.append(efet)
        if base and base.lower() not in {e.lower() for e in efetivos}:
            efetivos.insert(0, base)
        if not efetivos:
            continue

        # a pasta do equipamento vem primeiro; as demais na ordem encontrada
        efetivos.sort(key=lambda c: (0 if base and c.lower() == base.lower() else 1))
        nomes = _nomes_de_pastas(efetivos, base)
        por_caminho = {}
        for i, caminho in enumerate(efetivos):
            pasta = EquipamentoPasta(equipamento_id=equip.id, nome=nomes[caminho],
                                     caminho=caminho, ordem=i, ativo=True)
            db.session.add(pasta)
            por_caminho[caminho.lower()] = pasta
            criadas += 1
        db.session.flush()          # precisa dos ids para vincular os documentos

        for d in docs:
            efet = caminhos.normalizar(d.armazenamento) or base
            pasta = por_caminho.get(efet.lower()) if efet else None
            if pasta is None:
                continue
            d.pasta_id = pasta.id
            d.armazenamento = ""    # o caminho passou a viver na pasta
            vinculados += 1

    if criadas or vinculados:
        db.session.commit()
        print(f"[INFO] Pastas: {criadas} pasta(s) criadas a partir dos caminhos existentes; "
              f"{vinculados} documento(s) vinculados ao seu grupo.")


def _backfill_historico_documentos():
    """Cria o marco inicial da trilha de status dos documentos que não têm nenhum.

    Sem uma linha de partida, o histórico começaria vazio e o aging ("há quantos
    dias parado") não teria data de referência. Grava UMA linha por documento com
    a data que melhor aproxima o último movimento conhecido (updated_em, ou
    criado_em), marcada como 'system' para não se confundir com registro real.
    Roda uma única vez: quem já tem histórico não é tocado.
    """
    from sqlalchemy import inspect as _sa_inspect
    if "documento_historico" not in set(_sa_inspect(db.engine).get_table_names()):
        return
    if DocumentoHistorico.query.first() is not None:
        return
    docs = Documento.query.filter(Documento.ativo == True).all()
    for d in docs:
        db.session.add(DocumentoHistorico(
            documento_id=d.id, evento="status",
            status_antigo="", status_novo=d.status or "Elaborar",
            em=(d.updated_em or d.criado_em or datetime.now()),
            por="system", motivo="Marco inicial (migração)"))
    if docs:
        db.session.commit()
        print(f"[INFO] Histórico: marco inicial criado para {len(docs)} documento(s)")


def _data_conclusao_real(doc_id, status):
    """Data em que o documento ENTROU no status terminal, se ela existir de fato.

    Só aceita uma transição real: a linha da trilha precisa ter `status_antigo`
    preenchido. O marco de migração criado por _backfill_historico_documentos
    grava `status_antigo=''` com a data de `updated_em` — usá-lo como data de
    conclusão inventaria um throughput que nunca aconteceu (no banco atual, os
    522 marcos são de 24/07, o que faria os 64 documentos já concluídos há
    tempos aparecerem todos como "concluídos nos últimos 30 dias", com tempo de
    ciclo zero). Documento concluído antes de existir instrumentação tem data
    de conclusão DESCONHECIDA, e é isso que None quer dizer.
    """
    return (db.session.query(db.func.max(DocumentoHistorico.em))
            .filter(DocumentoHistorico.documento_id == doc_id,
                    DocumentoHistorico.status_novo == status,
                    db.func.coalesce(DocumentoHistorico.status_antigo, "") != "")
            .scalar())


def _backfill_marcos_documentos():
    """Deriva os marcos temporais dos documentos a partir da trilha (migration 011).

    A trilha (`documento_historico`) já registrava cada troca de status desde a
    migration 008 — só ninguém a lia para nada além de exibir a lista na ficha.
    Aqui ela paga a dívida: `entrou_status_em` vem da última troca registrada
    (aí o marco de migração serve: é o limite superior conhecido do aging e não
    inventa data futura) e `concluido_em` só de uma transição real — ver
    _data_conclusao_real.

    Idempotente: só toca documento com a coluna nula.
    """
    from sqlalchemy import inspect as _sa_inspect
    tabelas = set(_sa_inspect(db.engine).get_table_names())
    if "documentos" not in tabelas:
        return
    cols = {c["name"] for c in _sa_inspect(db.engine).get_columns("documentos")}
    if "entrou_status_em" not in cols:
        return   # schema antigo: _sync_schema roda antes e cria as colunas

    com_trilha = "documento_historico" in tabelas

    # Correção de uma versão anterior deste backfill, que aceitava o marco de
    # migração como data de conclusão. Roda uma vez e some (idempotente).
    if com_trilha:
        suspeitos = [d for d in Documento.query.filter(
            Documento.concluido_em.isnot(None)).all()
            if _data_conclusao_real(d.id, d.status) is None]
        if suspeitos:
            for d in suspeitos:
                d.concluido_em = None
                d.concluido_por = ""
            db.session.commit()
            print(f"[INFO] Documentos: data de conclusão sintética removida de "
                  f"{len(suspeitos)} documento(s) (sem transição real na trilha)")

    pendentes = Documento.query.filter(
        db.or_(Documento.entrou_status_em.is_(None), Documento.peso.is_(None))).all()
    if not pendentes:
        return

    n_conclusao = 0
    for d in pendentes:
        if d.peso is None:
            d.peso = 1.0
        if d.entrou_status_em is None:
            marco = None
            if com_trilha:
                marco = (db.session.query(db.func.max(DocumentoHistorico.em))
                         .filter(DocumentoHistorico.documento_id == d.id,
                                 db.func.coalesce(DocumentoHistorico.evento,
                                                  "status") == "status")
                         .scalar())
            d.entrou_status_em = marco or d.updated_em or d.criado_em or datetime.now()
        if d.concluido and d.concluido_em is None and com_trilha:
            real = _data_conclusao_real(d.id, d.status)
            if real is not None:
                d.concluido_em = real
                n_conclusao += 1

    db.session.commit()
    print(f"[INFO] Documentos: marcos temporais preenchidos em {len(pendentes)} "
          f"documento(s) ({n_conclusao} com data de conclusão conhecida)")


def _backfill_responsaveis_documentos():
    """Liga `Documento.responsavel` (texto) aos usuários reais — espelha 011.

    Por nome COMPLETO exato: casar por primeiro nome reintroduziria a colisão
    ("Ana" casando com "Mariana") que a tabela N:N veio corrigir. O que não
    casar continua valendo como texto (ver Documento.responsaveis_nomes).
    Roda uma vez: se a tabela já tem qualquer linha, não faz nada.
    """
    from sqlalchemy import inspect as _sa_inspect
    from models import documento_responsaveis
    if "documento_responsaveis" not in set(_sa_inspect(db.engine).get_table_names()):
        return
    if db.session.query(documento_responsaveis).count() > 0:
        return

    por_nome = {}
    for u in User.query.filter_by(ativo=True).all():
        chave = (u.nome or "").strip().lower()
        if chave:
            por_nome.setdefault(chave, []).append(u)

    ligados = 0
    for d in Documento.query.filter(Documento.responsavel != "").all():
        achados = []
        for parte in (d.responsavel or "").split(","):
            cands = por_nome.get(parte.strip().lower()) or []
            if len(cands) == 1 and cands[0] not in achados:
                achados.append(cands[0])
        if achados:
            d.responsaveis_users = achados
            ligados += 1
    if ligados:
        db.session.commit()
        print(f"[INFO] Documentos: responsáveis de {ligados} documento(s) "
              f"vinculados a usuários")


def _backfill_historico_equipamentos():
    """Marco inicial da trilha de-para dos equipamentos que já existiam.

    Mesmo papel do marco dos documentos: sem uma linha de partida a aba
    Histórico da ficha abriria vazia para todo o cadastro atual, sem sequer
    dizer desde quando ele está assim. Roda uma vez só."""
    from sqlalchemy import inspect as _sa_inspect
    if "equipamento_historico" not in set(_sa_inspect(db.engine).get_table_names()):
        return
    if EquipamentoHistorico.query.first() is not None:
        return
    equips = Equipamento.query.filter(Equipamento.ativo == True).all()
    for e in equips:
        db.session.add(EquipamentoHistorico(
            equipamento_id=e.id, evento="create", campo="nome",
            valor_antigo="", valor_novo=e.nome or "",
            em=(e.updated_em or e.criado_em or datetime.now()),
            por="system"))
    if equips:
        db.session.commit()
        print(f"[INFO] Equipamentos: marco inicial de histórico para {len(equips)} item(ns)")


def _snapshot_do_dia():
    """Garante a foto de hoje da série de ICE/IDP.

    Chamada na subida e todo dia pelo agendador interno (ver scheduler.py e
    rodar_tarefas_diarias). `POST /api/equipamentos/snapshot` continua servindo
    para um disparo manual. Idempotente — se a linha de hoje já existe, sai."""
    from sqlalchemy import inspect as _sa_inspect
    if "equipamento_snapshot" not in set(_sa_inspect(db.engine).get_table_names()):
        return 0
    hoje = date.today().isoformat()
    if EquipamentoSnapshot.query.filter(EquipamentoSnapshot.data == hoje).first():
        return 0
    n = _snapshot_equipamentos(hoje)
    if n:
        print(f"[INFO] Equipamentos: snapshot de {hoje} gravado ({n} equipamento(s))")
    return n


def _backfill_missoes():
    """Missões: liga responsáveis texto → usuário e cria o marco inicial da
    trilha dos cartões que já existiam (espelha a migration 010).

    O N:N é ligado por nome COMPLETO exato: o CSV do cartão é preenchido pelo
    seletor de usuários, então bate 1:1 — adivinhar por primeiro nome aqui
    reintroduziria a colisão ("Ana" casando com "Mariana") que a tabela veio
    corrigir. Idempotentes."""
    from sqlalchemy import inspect as _sa_inspect
    from models import (Missao, MissaoCartao, MissaoCartaoHistorico,
                        missao_cartao_responsaveis)
    tabelas = set(_sa_inspect(db.engine).get_table_names())
    if "missao_cartao_historico" not in tabelas:
        return

    if db.session.query(missao_cartao_responsaveis).count() == 0:
        por_nome = {}
        for u in User.query.filter_by(ativo=True).all():
            chave = (u.nome or "").strip().lower()
            if chave:
                por_nome.setdefault(chave, []).append(u)
        ligados = 0
        for c in MissaoCartao.query.filter(MissaoCartao.responsaveis != "").all():
            achados = []
            for parte in (c.responsaveis or "").split(","):
                cands = por_nome.get(parte.strip().lower()) or []
                if len(cands) == 1 and cands[0] not in achados:
                    achados.append(cands[0])
            if achados:
                c.responsaveis_users = achados
                ligados += 1
        if ligados:
            db.session.commit()
            print(f"[INFO] Missões: responsáveis de {ligados} cartão(ões) "
                  f"vinculados a usuários")

    if MissaoCartaoHistorico.query.count() == 0:
        cartoes = MissaoCartao.query.all()
        agora = datetime.now()
        for c in cartoes:
            db.session.add(MissaoCartaoHistorico(
                cartao_id=c.id, missao_id=c.missao_id, evento="criado",
                coluna_destino_id=c.coluna_id, campo="titulo",
                valor_antigo="", valor_novo=(c.titulo or "").strip(),
                origem="migracao", em=(c.criado_em or c.atualizado_em or agora),
                por="system"))
        if cartoes:
            db.session.commit()
            print(f"[INFO] Missões: marco inicial de histórico para "
                  f"{len(cartoes)} cartão(ões)")


def _snapshot_missoes_do_dia():
    """Foto do dia das missões ativas — mesmo gancho diário do ICE/IDP.
    `POST /api/missoes/snapshot` cobre o disparo manual. Idempotente:
    reexecutar no mesmo dia atualiza a linha."""
    from sqlalchemy import inspect as _sa_inspect
    if "missao_snapshot" not in set(_sa_inspect(db.engine).get_table_names()):
        return 0
    from missoes import snapshot_do_dia
    n = snapshot_do_dia()
    if n:
        print(f"[INFO] Missões: snapshot de {date.today().isoformat()} "
              f"gravado ({n} missão(ões))")
    return n


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


def _snapshot_projetos_do_dia():
    """Foto do dia dos projetos ativos.

    Projeto já grava snapshot a cada mutação (`registrar_snapshot`), então a
    curva-S tem pontos — mas só nos dias em que alguém mexeu. Um projeto parado
    duas semanas virava uma reta entre dois pontos distantes, escondendo que o
    previsto continuou subindo enquanto o realizado não. Idempotente no dia."""
    from sqlalchemy import inspect as _sa_inspect
    if "projeto_snapshot" not in set(_sa_inspect(db.engine).get_table_names()):
        return 0
    from models import Projeto
    projetos = Projeto.query.filter(Projeto.ativo == True).all()
    for p in projetos:
        p.registrar_snapshot()
    if projetos:
        db.session.commit()
        print(f"[INFO] Projetos: snapshot de {date.today().isoformat()} "
              f"gravado ({len(projetos)} projeto(s))")
    return len(projetos)


def _purgar_auditoria():
    """Descarta linhas de auditoria mais antigas que DOCTRACK_AUDIT_RETENCAO_DIAS.

    Desligado por padrão (0 = guardar tudo): auditoria é registro de conformidade
    e apagar por conta própria seria pior que a tabela crescer. Quem tem política
    de retenção definida liga a variável e a limpeza passa a rodar no diário.
    """
    dias = int(os.environ.get("DOCTRACK_AUDIT_RETENCAO_DIAS", "0") or 0)
    if dias <= 0:
        return 0
    corte = datetime.now() - timedelta(days=dias)
    n = AuditLog.query.filter(AuditLog.timestamp < corte).delete(synchronize_session=False)
    db.session.commit()
    if n:
        print(f"[INFO] Auditoria: {n} registro(s) anteriores a "
              f"{corte.strftime('%d/%m/%Y')} descartados (retenção {dias} dias)")
    return n


def rodar_tarefas_diarias():
    """As tarefas que precisam de uma execução por dia, em um lugar só.

    Chamada pelo agendador interno (scheduler.py), pelo init_app na subida e por
    `scripts/snapshot_diario.py`. Cada etapa é idempotente no dia e isolada: uma
    falha não impede as seguintes, porque perder a foto dos equipamentos não é
    motivo para perder também a das missões.
    """
    resultado = {}
    for nome, fn in (("equipamentos", _snapshot_do_dia),
                     ("missoes", _snapshot_missoes_do_dia),
                     ("projetos", _snapshot_projetos_do_dia),
                     ("auditoria", _purgar_auditoria)):
        try:
            resultado[nome] = fn()
        except Exception as e:
            db.session.rollback()
            resultado[nome] = f"erro: {e}"
            print(f"[WARN] Tarefa diária '{nome}' falhou — {e}")
    return resultado


def init_app(app_=None):
    """Prepara o banco para o app subir: schema, seeds, backfills e foto do dia.

    Isto NÃO roda no import de propósito. Enquanto rodava, qualquer `import
    servidor` — inclusive o do pytest e o de um script solto — executava
    create_all, o UPDATE de setor, todos os backfills e as escritas de snapshot
    contra o banco real do desenvolvedor, sem que ninguém tivesse pedido.
    Quem sobe o servidor chama esta função explicitamente (ver __main__ e
    wsgi.py); quem só importa o módulo não paga nada.

    Todas as etapas são idempotentes: chamar de novo não duplica nada.
    """
    alvo = (app_ or app)
    with alvo.app_context():
        try:
            # Diz em voz alta qual banco está sendo preparado. Quando isto
            # acontecia no import, era impossível saber de onde tinha partido a
            # escrita — a linha abaixo torna qualquer preparação inesperada
            # visível no log em vez de silenciosa.
            uri = alvo.config.get("SQLALCHEMY_DATABASE_URI", "")
            print(f"[INFO] init_app: preparando {uri.rsplit('/', 1)[-1] or uri}")
            db.create_all()
            _sync_schema()
            _seed_tipos_consumivel()
            # Migração automática de 'Fabricante' para 'Manuais' nos registros existentes
            from sqlalchemy import text
            db.session.execute(text("UPDATE documentos SET setor = 'Manuais' WHERE setor = 'Fabricante'"))
            db.session.commit()

            if User.query.count() == 0:
                init_db()

            # Reestruturação: entidade Equipamento + tipos por equipamento.
            # A migração de taxonomia roda ANTES do backfill (o rename evita que o
            # backfill crie um Checklist_Conferencia duplicado). Idempotente.
            _migrar_taxonomia_docs()
            _backfill_equipamentos()
            # Caminho da pasta é do equipamento (documento só guarda override) e
            # todo documento nasce com um marco na trilha de status. Idempotentes.
            # A canonização vem ANTES: consolidar compara caminhos por igualdade
            # de string, e `P:\...` vs UNC do mesmo diretório não casariam.
            _normalizar_caminhos_armazenados()
            _consolidar_armazenamento()
            # Materializa os grupos de pastas a partir dos caminhos já gravados.
            # Roda DEPOIS da consolidação para ver os caminhos efetivos finais.
            _backfill_pastas_equipamento()
            _backfill_historico_documentos()
            # Documentos: marcos temporais derivados da trilha + responsáveis
            # tipados. Idempotentes.
            _backfill_marcos_documentos()
            _backfill_responsaveis_documentos()
            # Equipamentos: trilha de-para do ICE/IDP. Idempotente.
            _backfill_historico_equipamentos()
            # Missões: trilha temporal do cartão + N:N de responsáveis. Idempotentes.
            _backfill_missoes()
            # Fotos do dia (equipamentos, missões, projetos): a subida garante a
            # de hoje; o agendador cuida das próximas. Idempotentes.
            rodar_tarefas_diarias()

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
    print(f"  DocTrack v{APP_VERSION} — Sector Based + WebSocket")
    print("="*55)
    if args.init: init_db(reset=True)
    init_app()
    iniciar_agendador(app, rodar_tarefas_diarias)
    socketio.run(app, host="0.0.0.0", port=5000, debug=_flask_debug, allow_unsafe_werkzeug=True)
