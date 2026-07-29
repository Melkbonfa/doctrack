"""
pdr/routes.py — Blueprint do módulo PDR (P&D de reagentes).

Montado sob /pdr no servidor mestre (DocTrack). Reutiliza autenticação,
audit log e event_bus do mestre. O acesso é controlado por
`require_pdr_access` (admin ou usuários com a flag `pode_pdr`).
"""
import csv
import io
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity

from models import db, User
from auth import require_pdr_access, log_action, get_client_ip
from event_bus import EventType

from .models import (
    Produto, Apresentacao, PdrDocumento,
    ROLES, LINHAS, TIPOS_DOC, TIPOS_DOC_LABELS,
    STATUS_PROTHEUS, STATUS_ANVISA, STATUS_DOC,
)
from .importer import importar_planilha

pdr_bp = Blueprint(
    "pdr", __name__,
    url_prefix="/pdr",
    template_folder="templates",
    static_folder="static",
)

# Versão dos assets (busca cache) — renovada a cada start do servidor.
ASSET_V = datetime.now().strftime("%Y%m%d%H%M%S")


# preenchido por servidor.py para emitir tempo real sem import circular
_rt = {"socketio": None, "publish_event": None, "AuditLog": None, "EventType": None}


def init_realtime(socketio, publish_event, AuditLog, EventType):
    _rt.update(socketio=socketio, publish_event=publish_event,
               AuditLog=AuditLog, EventType=EventType)

    @socketio.on("join_apresentacao")
    def _on_join_apres(data):
        from flask_socketio import join_room
        aid = (data or {}).get("apresentacao_id")
        if aid:
            join_room(f"apres:{aid}")


def current_user():
    return User.query.filter_by(email=get_jwt_identity()).first()


def _emit(event_type, payload):
    if _rt["socketio"] and _rt["publish_event"]:
        u = current_user()
        try:
            _rt["publish_event"](event_type, payload,
                                 user_id=u.id if u else None,
                                 user_email=u.email if u else None,
                                 db=db, AuditLog=_rt["AuditLog"],
                                 socketio=_rt["socketio"])
        except Exception:
            pass  # tempo real é best-effort; a gravação já foi feita


# ── PÁGINA ──────────────────────────────────────────────────────────────────────
@pdr_bp.route("/")
@pdr_bp.route("")
def index():
    # A própria página valida o token no front (igual ao hub); o acesso de dados
    # é protegido em cada rota /pdr/api/* por require_pdr_access.
    # Nome com namespace "pdr/" para não colidir com o dashboard.html do mestre.
    return render_template("pdr/dashboard.html", asset_v=ASSET_V)


@pdr_bp.route("/api/meta", methods=["GET"])
@require_pdr_access()
def api_meta():
    """Vocabulários controlados para preencher selects no frontend."""
    return jsonify({
        "roles": ROLES,
        "linhas": LINHAS,
        "tipos_doc": TIPOS_DOC,
        "tipos_doc_labels": TIPOS_DOC_LABELS,
        "status_protheus": STATUS_PROTHEUS,
        "status_anvisa": STATUS_ANVISA,
        "status_doc": STATUS_DOC,
    }), 200


# ── DASHBOARD / KPIs ────────────────────────────────────────────────────────────
@pdr_bp.route("/api/dashboard", methods=["GET"])
@require_pdr_access()
def api_dashboard():
    apres = Apresentacao.query.filter_by(ativo=True).all()
    total_apres = len(apres)
    total_prod = Produto.query.filter_by(ativo=True).count()

    por_linha, por_fornecedor, por_anvisa, por_protheus, por_status = {}, {}, {}, {}, {}
    docs_ok = docs_total = 0
    funil = {t: {"ok": 0, "pendente": 0, "descontinuado": 0} for t in TIPOS_DOC}

    for a in apres:
        linha = a.produto.linha if a.produto else "—"
        por_linha[linha] = por_linha.get(linha, 0) + 1
        forn = a.fornecedor or "—"
        por_fornecedor[forn] = por_fornecedor.get(forn, 0) + 1
        anv = a.anvisa or "—"
        por_anvisa[anv] = por_anvisa.get(anv, 0) + 1
        prot = a.cadastro_protheus or "—"
        por_protheus[prot] = por_protheus.get(prot, 0) + 1
        sg = a.status_global
        por_status[sg] = por_status.get(sg, 0) + 1
        for d in a.documentos:
            if d.is_descontinuado:
                funil[d.tipo]["descontinuado"] += 1
                continue
            docs_total += 1
            if d.is_ok:
                docs_ok += 1
                funil[d.tipo]["ok"] += 1
            else:
                funil[d.tipo]["pendente"] += 1

    def top(d, n=8):
        return sorted(d.items(), key=lambda x: -x[1])[:n]

    ultimas = (Apresentacao.query.filter_by(ativo=True)
               .order_by(Apresentacao.updated_em.desc()).limit(10).all())

    return jsonify({
        "total_produtos": total_prod,
        "total_apresentacoes": total_apres,
        "descontinuadas": por_status.get("Descontinuado", 0),
        "finalizadas": por_status.get("Finalizado", 0),
        "avanco_geral": round(docs_ok * 100 / docs_total) if docs_total else 0,
        "por_linha": [{"label": k, "value": v} for k, v in top(por_linha)],
        "por_fornecedor": [{"label": k, "value": v} for k, v in top(por_fornecedor)],
        "por_anvisa": [{"label": k, "value": v} for k, v in top(por_anvisa)],
        "por_protheus": [{"label": k, "value": v} for k, v in top(por_protheus)],
        "por_status": [{"label": k, "value": v} for k, v in por_status.items()],
        "funil": [{"tipo": TIPOS_DOC_LABELS[t], **funil[t]} for t in TIPOS_DOC],
        "ultimas": [a.to_dict(com_documentos=False) for a in ultimas],
        "atualizado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
    }), 200


# ── PRODUTOS ────────────────────────────────────────────────────────────────────
@pdr_bp.route("/api/produtos", methods=["GET"])
@require_pdr_access()
def list_produtos():
    q = Produto.query.filter_by(ativo=True)
    linha = request.args.get("linha")
    if linha:
        q = q.filter_by(linha=linha)
    produtos = q.order_by(Produto.nome).all()
    return jsonify([p.to_dict() for p in produtos]), 200


@pdr_bp.route("/api/produtos/<int:pid>", methods=["GET"])
@require_pdr_access()
def get_produto(pid):
    p = Produto.query.get(pid)
    if not p:
        return jsonify({"erro": "Produto não encontrado"}), 404
    return jsonify(p.to_dict(com_apresentacoes=True)), 200


@pdr_bp.route("/api/produtos", methods=["POST"])
@require_pdr_access("admin", "gestor")
def create_produto():
    data = request.get_json(silent=True) or {}
    nome = (data.get("nome") or "").strip()
    if not nome:
        return jsonify({"erro": "Nome é obrigatório"}), 400
    p = Produto(nome=nome, sigla=(data.get("sigla") or "").strip(),
                linha=(data.get("linha") or "Extracta KITs").strip(),
                observacoes=(data.get("observacoes") or "").strip())
    db.session.add(p)
    db.session.commit()
    _emit(EventType.PRODUTO_CREATED, {"entidade": "produto", "id": p.id,
                                      "new_value": p.nome})
    return jsonify({"mensagem": "Produto criado", "produto": p.to_dict()}), 201


@pdr_bp.route("/api/produtos/<int:pid>", methods=["PATCH"])
@require_pdr_access("admin", "gestor")
def update_produto(pid):
    p = Produto.query.get(pid)
    if not p:
        return jsonify({"erro": "Produto não encontrado"}), 404
    data = request.get_json(silent=True) or {}
    for campo in ("nome", "sigla", "linha", "observacoes"):
        if campo in data:
            setattr(p, campo, (data[campo] or "").strip())
    db.session.commit()
    _emit(EventType.PRODUTO_UPDATED, {"entidade": "produto", "id": p.id,
                                      "new_value": p.nome})
    return jsonify({"mensagem": "Produto atualizado", "produto": p.to_dict()}), 200


@pdr_bp.route("/api/produtos/<int:pid>", methods=["DELETE"])
@require_pdr_access("admin", "gestor")
def delete_produto(pid):
    p = Produto.query.get(pid)
    if not p:
        return jsonify({"erro": "Produto não encontrado"}), 404
    p.ativo = False
    for a in p.apresentacoes:
        a.ativo = False
    db.session.commit()
    _emit(EventType.PRODUTO_DELETED, {"entidade": "produto", "id": p.id,
                                      "old_value": p.nome})
    return jsonify({"mensagem": "Produto desativado"}), 200


# ── APRESENTAÇÕES ───────────────────────────────────────────────────────────────
@pdr_bp.route("/api/apresentacoes", methods=["GET"])
@require_pdr_access()
def list_apresentacoes():
    q = Apresentacao.query.filter_by(ativo=True)
    if request.args.get("produto_id"):
        q = q.filter_by(produto_id=int(request.args["produto_id"]))
    apres = q.join(Produto).order_by(Produto.nome, Apresentacao.apresentacao).all()

    linha = request.args.get("linha")
    fornecedor = request.args.get("fornecedor")
    anvisa = request.args.get("anvisa")
    status = request.args.get("status")
    busca = (request.args.get("busca") or "").strip().lower()

    out = []
    for a in apres:
        if linha and (a.produto.linha if a.produto else "") != linha:
            continue
        if fornecedor and a.fornecedor != fornecedor:
            continue
        if anvisa and a.anvisa != anvisa:
            continue
        if status and a.status_global != status:
            continue
        if busca:
            campos = " ".join([
                a.sku or "", a.apresentacao or "", a.modelo or "", a.descricao or "",
                a.fornecedor or "", a.produto.nome if a.produto else "",
            ]).lower()
            if busca not in campos:
                continue
        out.append(a.to_dict(com_documentos=True))
    return jsonify(out), 200


@pdr_bp.route("/api/apresentacoes/<int:aid>", methods=["GET"])
@require_pdr_access()
def get_apresentacao(aid):
    a = Apresentacao.query.get(aid)
    if not a:
        return jsonify({"erro": "Apresentação não encontrada"}), 404
    return jsonify(a.to_dict(com_documentos=True)), 200


@pdr_bp.route("/api/apresentacoes", methods=["POST"])
@require_pdr_access("admin", "gestor")
def create_apresentacao():
    data = request.get_json(silent=True) or {}
    produto_id = data.get("produto_id")
    if not produto_id or not Produto.query.get(produto_id):
        return jsonify({"erro": "produto_id inválido"}), 400
    a = Apresentacao(produto_id=produto_id)
    for campo in ("apresentacao", "descricao", "modelo", "sku", "cadastro_protheus",
                  "anvisa", "numero_anvisa", "fornecedor", "etiqueta", "rotulagem",
                  "planilha_rastreabilidade", "observacoes"):
        if campo in data:
            setattr(a, campo, (data[campo] or "").strip())
    db.session.add(a)
    db.session.flush()
    for tipo in TIPOS_DOC:
        db.session.add(PdrDocumento(apresentacao_id=a.id, tipo=tipo))
    db.session.commit()
    _emit(EventType.APRESENTACAO_CREATED, {"entidade": "apresentacao",
                                           "apresentacao_id": a.id, "new_value": a.sku})
    return jsonify({"mensagem": "Apresentação criada", "apresentacao": a.to_dict()}), 201


@pdr_bp.route("/api/apresentacoes/<int:aid>", methods=["PATCH"])
@require_pdr_access("admin", "gestor", "tecnico")
def update_apresentacao(aid):
    a = Apresentacao.query.get(aid)
    if not a:
        return jsonify({"erro": "Apresentação não encontrada"}), 404
    data = request.get_json(silent=True) or {}

    # Optimistic locking
    cli_v = data.get("version")
    if cli_v is not None and int(cli_v) != a.version:
        return jsonify({"erro": "Apresentação alterada por outro usuário.",
                        "current_version": a.version,
                        "apresentacao": a.to_dict()}), 409

    campos = ("apresentacao", "descricao", "modelo", "sku", "cadastro_protheus",
              "anvisa", "numero_anvisa", "fornecedor", "etiqueta", "rotulagem",
              "planilha_rastreabilidade", "observacoes")
    mudancas = []
    for campo in campos:
        if campo in data:
            novo = (data[campo] or "").strip()
            antigo = getattr(a, campo) or ""
            if novo != antigo:
                mudancas.append((campo, antigo, novo))
                setattr(a, campo, novo)

    # Documentos embutidos (status/versão/codificação)
    for doc in data.get("documentos", []):
        d = PdrDocumento.query.get(doc.get("id"))
        if d and d.apresentacao_id == a.id:
            for f in ("fase", "status", "codificacao", "versao"):
                if f in doc:
                    novo = (doc[f] or "").strip()
                    if novo != (getattr(d, f) or ""):
                        mudancas.append((f"{d.tipo}.{f}", getattr(d, f) or "", novo))
                        setattr(d, f, novo)

    if mudancas:
        a.version += 1
        db.session.commit()
        u = current_user()
        for campo, antigo, novo in mudancas:
            log_action(u.email if u else "system", "UPDATE",
                       entidade=f"pdr:apresentacao#{a.id} ({a.sku})", campo=campo,
                       antigo=antigo, novo=novo, ip=get_client_ip(), documento_id=a.id)
        _emit(EventType.APRESENTACAO_UPDATED, {"entidade": "apresentacao",
                                               "apresentacao_id": a.id, "new_value": a.sku})
    return jsonify({"mensagem": "Apresentação atualizada", "apresentacao": a.to_dict()}), 200


@pdr_bp.route("/api/apresentacoes/<int:aid>", methods=["DELETE"])
@require_pdr_access("admin", "gestor")
def delete_apresentacao(aid):
    a = Apresentacao.query.get(aid)
    if not a:
        return jsonify({"erro": "Apresentação não encontrada"}), 404
    a.ativo = False
    db.session.commit()
    _emit(EventType.APRESENTACAO_DELETED, {"entidade": "apresentacao",
                                           "apresentacao_id": a.id, "old_value": a.sku})
    return jsonify({"mensagem": "Apresentação desativada"}), 200


# ── REIMPORT ────────────────────────────────────────────────────────────────────
@pdr_bp.route("/api/reimport", methods=["POST"])
@require_pdr_access("admin")
def api_reimport():
    PdrDocumento.query.delete()
    Apresentacao.query.delete()
    Produto.query.delete()
    db.session.commit()
    n = importar_planilha()
    _emit(EventType.REIMPORT, {"entidade": "sistema", "new_value": f"{n} apresentações"})
    return jsonify({"mensagem": f"Reimportação concluída: {n} apresentações"}), 200


# ── EXPORT CSV ──────────────────────────────────────────────────────────────────
@pdr_bp.route("/api/export/apresentacoes.csv", methods=["GET"])
@require_pdr_access()
def export_csv():
    """CSV das apresentações conforme os filtros da aba.

    O export ignorava os filtros e devolvia sempre o catálogo inteiro. Os
    critérios abaixo são os mesmos de `renderApres()` (pdr/static/app.js): linha,
    fornecedor, ANVISA, status global e a busca livre.
    """
    linha = request.args.get("linha", "").strip()
    fornecedor = request.args.get("fornecedor", "").strip()
    anvisa = request.args.get("anvisa", "").strip()
    status = request.args.get("status", "").strip()
    busca = (request.args.get("busca", "") or "").strip().lower()

    itens = Apresentacao.query.filter_by(ativo=True).join(Produto).order_by(Produto.nome).all()
    if linha:
        itens = [a for a in itens if (a.produto.linha if a.produto else "") == linha]
    if fornecedor:
        itens = [a for a in itens if (a.fornecedor or "") == fornecedor]
    if anvisa:
        itens = [a for a in itens if (a.anvisa or "") == anvisa]
    if status:
        itens = [a for a in itens if (a.status_global or "") == status]
    if busca:
        def _alvo(a):
            return " ".join(str(x or "") for x in (
                a.produto.nome if a.produto else "", a.sku, a.apresentacao,
                a.modelo, a.fornecedor, a.descricao)).lower()
        itens = [a for a in itens if busca in _alvo(a)]

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Produto", "Linha", "Sigla", "Apresentação", "SKU", "Modelo",
                "Cadastro Protheus", "ANVISA", "Nº ANVISA", "Fornecedor",
                "Status Global", "Avanço %",
                "Espec.", "Descritivo", "IT", "Manual"])
    for a in itens:
        docs = {d.tipo: d for d in a.documentos}
        w.writerow([
            a.produto.nome if a.produto else "", a.produto.linha if a.produto else "",
            a.produto.sigla if a.produto else "", a.apresentacao, a.sku, a.modelo,
            a.cadastro_protheus, a.anvisa, a.numero_anvisa, a.fornecedor,
            a.status_global, a.avanco,
            docs.get("especificacao").status if docs.get("especificacao") else "",
            docs.get("descritivo").status if docs.get("descritivo") else "",
            docs.get("instrucao_trabalho").status if docs.get("instrucao_trabalho") else "",
            docs.get("manual").status if docs.get("manual") else "",
        ])
    mem = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True,
                     download_name=f"apresentacoes_pdr_{datetime.now():%Y%m%d}.csv")
