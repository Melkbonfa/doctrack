"""
entregaveis.py — Módulo de Entregáveis por Projeto
Rotas:
  GET    /api/projetos                — lista com avanço calculado + filtros
  POST   /api/projetos                — criar (admin/gestor)
  GET    /api/projetos/<id>           — detalhe agrupado por categoria
  PUT    /api/projetos/<id>           — editar metadados (admin/gestor)
  DELETE /api/projetos/<id>           — arquivar (admin/gestor)
  PUT    /api/entregaveis/<id>        — atualizar status/percentual/responsáveis (tecnico+)
  POST   /api/projetos/<id>/entregaveis — adicionar entregável (admin/gestor)
  GET    /api/entregaveis/resumo      — KPIs e visão por responsável
  GET    /api/entregaveis/export      — Excel limpo
"""
import io
from datetime import datetime

from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import get_jwt_identity

from models import (db, Projeto, Entregavel, ProjetoMensal, CATEGORIAS_ENTREGAVEL,
                    STATUS_ENTREGAVEL, MOSCOW, _parse_iso)
from auth import require_role, log_action, get_client_ip

entregaveis_bp = Blueprint("entregaveis", __name__)

# Campos de cronograma do projeto (datas ISO em texto livre)
DATAS_PROJETO = ("data_inicio_prev", "data_inicio_real", "data_fim_prev", "data_fim_real")

import re
_RE_COMPET = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")   # 'YYYY-MM'


def _parse_orcamento(v):
    """Aceita número ou string ('1.234,56' / '1234.56'); retorna float >= 0 ou None se inválido."""
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v) if v >= 0 else None
    s = str(v).strip().replace("R$", "").replace(" ", "")
    # 1.234,56 -> 1234.56 ; 1234.56 -> 1234.56
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        f = float(s)
    except ValueError:
        return None
    return f if f >= 0 else None

# preenchido por servidor.py para emitir tempo real sem import circular
_rt = {"socketio": None, "publish_event": None, "AuditLog": None, "EventType": None}


def init_realtime(socketio, publish_event, AuditLog, EventType):
    _rt.update(socketio=socketio, publish_event=publish_event,
               AuditLog=AuditLog, EventType=EventType)


def _emit(event_type, payload, email):
    if _rt["socketio"] and _rt["publish_event"]:
        try:
            _rt["publish_event"](event_type, payload, user_email=email,
                                 db=db, AuditLog=_rt["AuditLog"],
                                 socketio=_rt["socketio"])
        except Exception:
            pass  # tempo real é best-effort; a gravação já foi feita


# ── PROJETOS ─────────────────────────────────────────────────────────────────

@entregaveis_bp.route("/api/projetos", methods=["GET"])
@require_role("admin", "gestor")
def listar_projetos():
    q = Projeto.query.filter_by(ativo=True)
    ano = request.args.get("ano", type=int)
    if ano:
        q = q.filter_by(ano=ano)
    moscow = request.args.get("moscow", "").strip()
    if moscow:
        q = q.filter(Projeto.moscow.ilike(moscow))
    busca = request.args.get("busca", "").strip()
    if busca:
        q = q.filter(Projeto.nome.ilike(f"%{busca}%"))
    projetos = q.all()
    com_ent = request.args.get("com_entregaveis", "").strip() == "1"
    resp = request.args.get("responsavel", "").strip().lower()
    out = []
    for p in projetos:
        d = p.to_dict(com_entregaveis=com_ent)
        if resp:
            tipos = [e.to_dict() for e in p.entregaveis
                     if resp in (e.responsaveis or "").lower() and e.status != "na"]
            if not tipos:
                continue
            d["entregaveis_do_responsavel"] = tipos
        out.append(d)
    out.sort(key=lambda d: (d["prioridade"] or 999, d["nome"]))
    return jsonify({"projetos": out})


@entregaveis_bp.route("/api/projetos", methods=["POST"])
@require_role("admin", "gestor")
def criar_projeto():
    data = request.get_json(silent=True) or {}
    nome = (data.get("nome") or "").strip()
    if not nome:
        return jsonify({"erro": "nome é obrigatório"}), 400
    moscow = (data.get("moscow") or "").strip()
    if moscow and moscow not in MOSCOW:
        return jsonify({"erro": f"moscow inválido. Use: {', '.join(MOSCOW)}"}), 400
    orc = _parse_orcamento(data.get("orcamento"))
    if orc is None:
        return jsonify({"erro": "orçamento inválido"}), 400
    p = Projeto(
        nome=nome,
        descricao=(data.get("descricao") or "").strip(),
        sku=(data.get("sku") or "").strip(),
        moscow=moscow,
        prioridade=int(data.get("prioridade") or 0),
        consumivel=bool(data.get("consumivel")),
        lancamento=(data.get("lancamento") or "").strip(),
        ano=int(data.get("ano") or datetime.now().year),
        orcamento=orc,
        **{c: (data.get(c) or "").strip() for c in DATAS_PROJETO},
    )
    db.session.add(p)
    db.session.commit()
    email = get_jwt_identity()
    log_action(email, "CREATE", entidade=f"Projeto:{p.nome}", ip=get_client_ip())
    _emit("PROJETO_CREATED", {"projeto": p.to_dict()}, email)
    return jsonify({"projeto": p.to_dict()}), 201


@entregaveis_bp.route("/api/projetos/<int:pid>", methods=["GET"])
@require_role("admin", "gestor")
def detalhe_projeto(pid):
    p = Projeto.query.get_or_404(pid)
    grupos = {c: [] for c in CATEGORIAS_ENTREGAVEL}
    extras = {}
    for e in p.entregaveis:
        (grupos if e.categoria in grupos else extras).setdefault(e.categoria, [])
        (grupos.get(e.categoria) if e.categoria in grupos
         else extras[e.categoria]).append(e.to_dict())
    categorias = [{"categoria": c, "entregaveis": grupos[c]}
                  for c in CATEGORIAS_ENTREGAVEL if grupos[c]]
    categorias += [{"categoria": c, "entregaveis": v} for c, v in extras.items()]
    d = p.to_dict(com_pmo=True)
    d["categorias"] = categorias
    return jsonify(d)


@entregaveis_bp.route("/api/projetos/<int:pid>", methods=["PUT"])
@require_role("admin", "gestor")
def editar_projeto(pid):
    p = Projeto.query.get_or_404(pid)
    data = request.get_json(silent=True) or {}
    email = get_jwt_identity()
    for campo in ("nome", "descricao", "sku", "moscow", "lancamento", *DATAS_PROJETO):
        if campo in data:
            novo = (data.get(campo) or "").strip()
            antigo = getattr(p, campo) or ""
            if campo == "moscow" and novo and novo not in MOSCOW:
                return jsonify({"erro": "moscow inválido"}), 400
            if campo == "nome" and not novo:
                return jsonify({"erro": "nome não pode ficar vazio"}), 400
            if novo != antigo:
                setattr(p, campo, novo)
                log_action(email, "UPDATE", entidade=f"Projeto:{p.nome}",
                           campo=campo, antigo=antigo, novo=novo, ip=get_client_ip())
    if "orcamento" in data:
        orc = _parse_orcamento(data.get("orcamento"))
        if orc is None:
            return jsonify({"erro": "orçamento inválido"}), 400
        if orc != (p.orcamento or 0.0):
            log_action(email, "UPDATE", entidade=f"Projeto:{p.nome}",
                       campo="orcamento", antigo=p.orcamento, novo=orc, ip=get_client_ip())
            p.orcamento = orc
    if "prioridade" in data:
        p.prioridade = int(data.get("prioridade") or 0)
    if "consumivel" in data:
        p.consumivel = bool(data.get("consumivel"))
    db.session.commit()
    _emit("PROJETO_UPDATED", {"projeto": p.to_dict()}, email)
    return jsonify({"projeto": p.to_dict()})


@entregaveis_bp.route("/api/projetos/<int:pid>", methods=["DELETE"])
@require_role("admin", "gestor")
def arquivar_projeto(pid):
    p = Projeto.query.get_or_404(pid)
    p.ativo = False
    db.session.commit()
    email = get_jwt_identity()
    log_action(email, "DELETE", entidade=f"Projeto:{p.nome}", ip=get_client_ip())
    _emit("PROJETO_UPDATED", {"projeto": p.to_dict()}, email)
    return jsonify({"ok": True})


# ── ACOMPANHAMENTO MENSAL (PMO / EVM) ────────────────────────────────────────

def _validar_pct(v, campo):
    """int 0-100 ou erro (str)."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None, f"{campo} deve ser número"
    if not (0 <= n <= 100):
        return None, f"{campo} deve estar entre 0 e 100"
    return n, None


@entregaveis_bp.route("/api/projetos/<int:pid>/mensal", methods=["GET"])
@require_role("admin", "gestor")
def listar_mensal(pid):
    p = Projeto.query.get_or_404(pid)
    return jsonify({
        "projeto_id": p.id,
        "orcamento": p.orcamento or 0.0,
        "serie": p.serie_mensal(),
        "pmo": p.pmo_metrics(),
    })


@entregaveis_bp.route("/api/projetos/<int:pid>/mensal", methods=["PUT"])
@require_role("admin", "gestor")
def upsert_mensal(pid):
    """Cria ou atualiza o CUSTO acumulado de uma competência (YYYY-MM).

    O realizado (avanço) é automático, vindo da conclusão das tarefas — não se informa aqui.
    O previsto é calculado pelas datas. Este lançamento serve só ao custo (para o CPI).
    """
    p = Projeto.query.get_or_404(pid)
    data = request.get_json(silent=True) or {}
    comp = (data.get("competencia") or "").strip()
    if not _RE_COMPET.match(comp):
        return jsonify({"erro": "competência inválida (use AAAA-MM)"}), 400

    # Aceita 'custo_mes' (incremental, novo) ou 'custo_acumulado' (compat. antiga).
    bruto = data.get("custo_mes", data.get("custo_acumulado"))
    custo = _parse_orcamento(bruto)
    if custo is None:
        return jsonify({"erro": "custo do mês inválido"}), 400

    email = get_jwt_identity()
    reg = ProjetoMensal.query.filter_by(projeto_id=p.id, competencia=comp).first()
    acao = "MENSAL_UPDATED"
    if reg is None:
        reg = ProjetoMensal(projeto_id=p.id, competencia=comp)
        db.session.add(reg)
        acao = "MENSAL_CREATED"
    reg.pct_previsto = p.previsto_em(comp) or 0      # informativo
    reg.pct_realizado = p.realizado_em(_parse_iso(comp + "-28") or datetime.now().date())  # informativo
    reg.custo_mes = custo
    reg.atualizado_por = email
    reg.atualizado_em = datetime.now()
    db.session.flush()           # garante que reg participe do recálculo
    p.recompute_acumulados()     # atualiza o custo acumulado (AC) de toda a série
    db.session.commit()

    log_action(email, "UPDATE", entidade=f"{p.nome} · {comp}",
               campo="custo_mensal", novo=f"R$ {custo:.2f}", ip=get_client_ip())
    _emit(acao, {"projeto_id": p.id, "mensal": reg.to_dict(),
                 "pmo": p.pmo_metrics()}, email)
    return jsonify({"mensal": reg.to_dict(), "pmo": p.pmo_metrics()})


@entregaveis_bp.route("/api/projetos/<int:pid>/mensal/<competencia>", methods=["DELETE"])
@require_role("admin", "gestor")
def remover_mensal(pid, competencia):
    p = Projeto.query.get_or_404(pid)
    reg = ProjetoMensal.query.filter_by(projeto_id=p.id, competencia=competencia).first()
    if reg is None:
        return jsonify({"erro": "lançamento não encontrado"}), 404
    db.session.delete(reg)
    db.session.flush()
    p.recompute_acumulados()     # reajusta o acumulado dos meses restantes
    db.session.commit()
    email = get_jwt_identity()
    log_action(email, "DELETE", entidade=f"{p.nome} · {competencia}",
               campo="acompanhamento_mensal", ip=get_client_ip())
    _emit("MENSAL_DELETED", {"projeto_id": p.id, "competencia": competencia,
                             "pmo": p.pmo_metrics()}, email)
    return jsonify({"ok": True, "pmo": p.pmo_metrics()})


# ── ENTREGÁVEIS ──────────────────────────────────────────────────────────────

@entregaveis_bp.route("/api/entregaveis/<int:eid>", methods=["PUT"])
@require_role("admin", "gestor")
def atualizar_entregavel(eid):
    e = Entregavel.query.get_or_404(eid)
    data = request.get_json(silent=True) or {}
    email = get_jwt_identity()
    mudancas = []

    hoje_iso = datetime.now().strftime("%Y-%m-%d")
    # datas explícitas primeiro (aceita ISO yyyy-mm-dd ou ""), para que os
    # autopreenchimentos abaixo respeitem o que o usuário informou.
    if "data_inicio" in data:
        e.data_inicio = (data.get("data_inicio") or "").strip()
    if "data_conclusao" in data:
        e.data_conclusao = (data.get("data_conclusao") or "").strip()

    if "status" in data:
        novo = (data.get("status") or "").strip()
        if novo not in STATUS_ENTREGAVEL:
            return jsonify({"erro": f"status inválido. Use: {', '.join(STATUS_ENTREGAVEL)}"}), 400
        if novo != e.status:
            mudancas.append(("status", e.status, novo))
            e.status = novo
        if novo == "concluido":
            e.percentual = 100
            if not (e.data_conclusao or "").strip():       # conclusão = hoje (se não veio explícita)
                e.data_conclusao = hoje_iso
            if not (e.data_inicio or "").strip():          # início = conclusão (se não veio)
                e.data_inicio = e.data_conclusao
        elif novo in ("pendente", "na"):
            e.percentual = 0 if novo == "pendente" else None
            e.data_conclusao = ""                           # deixou de estar concluído
        elif novo == "em_progresso" and not (e.data_inicio or "").strip():
            e.data_inicio = hoje_iso

    if "percentual" in data and e.status == "em_progresso":
        try:
            pct = int(data.get("percentual"))
        except (TypeError, ValueError):
            return jsonify({"erro": "percentual deve ser número"}), 400
        if not (0 <= pct <= 100):
            return jsonify({"erro": "percentual deve estar entre 0 e 100"}), 400
        if pct != e.percentual:
            mudancas.append(("percentual", e.percentual, pct))
            e.percentual = pct

    if "responsaveis" in data:
        novo = (data.get("responsaveis") or "").strip()
        if novo != (e.responsaveis or ""):
            mudancas.append(("responsaveis", e.responsaveis, novo))
            e.responsaveis = novo

    e.atualizado_por = email
    e.atualizado_em = datetime.now()
    db.session.commit()

    for campo, antigo, novo in mudancas:
        log_action(email, "ENTREGAVEL_UPDATED",
                   entidade=f"{e.projeto.nome} · {e.tipo}",
                   campo=campo, antigo=antigo, novo=novo, ip=get_client_ip())
    _emit("ENTREGAVEL_UPDATED",
          {"entregavel": e.to_dict(), "projeto_id": e.projeto_id,
           "avanco_projeto": e.projeto.avanco}, email)
    return jsonify({"entregavel": e.to_dict(), "avanco_projeto": e.projeto.avanco})


@entregaveis_bp.route("/api/projetos/<int:pid>/entregaveis", methods=["POST"])
@require_role("admin", "gestor")
def adicionar_entregavel(pid):
    p = Projeto.query.get_or_404(pid)
    data = request.get_json(silent=True) or {}
    tipo = (data.get("tipo") or "").strip()
    if not tipo:
        return jsonify({"erro": "tipo é obrigatório"}), 400
    categoria = (data.get("categoria") or "Produto").strip()
    e = Entregavel(projeto_id=p.id, tipo=tipo, categoria=categoria,
                   status=(data.get("status") or "pendente"),
                   responsaveis=(data.get("responsaveis") or "").strip(),
                   atualizado_por=get_jwt_identity())
    db.session.add(e)
    db.session.commit()
    return jsonify({"entregavel": e.to_dict()}), 201


# ── RESUMO ───────────────────────────────────────────────────────────────────

@entregaveis_bp.route("/api/entregaveis/resumo", methods=["GET"])
@require_role("admin", "gestor")
def resumo():
    projetos = Projeto.query.filter_by(ativo=True).all()
    pend = conc = prog = 0
    por_resp = {}
    for p in projetos:
        for e in p.entregaveis:
            if e.status == "pendente":
                pend += 1
            elif e.status == "concluido":
                conc += 1
            elif e.status == "em_progresso":
                prog += 1
            if e.status in ("pendente", "em_progresso") and e.responsaveis:
                por_resp.setdefault(e.responsaveis, []).append(
                    {"projeto": p.nome, "tipo": e.tipo, "status": e.status,
                     "percentual": e.percentual, "id": e.id})
    avancos = [p.avanco for p in projetos]
    return jsonify({
        "projetos": len(projetos),
        "avanco_medio": round(sum(avancos) / len(avancos)) if avancos else 0,
        "pendentes": pend, "em_progresso": prog, "concluidos": conc,
        "por_responsavel": por_resp,
    })


# ── EXPORT EXCEL ─────────────────────────────────────────────────────────────

@entregaveis_bp.route("/api/entregaveis/export", methods=["GET"])
@require_role("admin", "gestor")
def exportar_excel():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    projetos = (Projeto.query.filter_by(ativo=True)
                .order_by(Projeto.prioridade, Projeto.nome).all())
    # união ordenada de tipos (categoria, tipo) preservando ordem de aparição
    tipos = []
    for p in projetos:
        for e in p.entregaveis:
            chave = (e.categoria, e.tipo)
            if chave not in tipos:
                tipos.append(chave)

    wb = Workbook()
    ws = wb.active
    ws.title = "Entregáveis 2026"
    CORES = {"concluido": "C6EFCE", "em_progresso": "FFEB9C",
             "pendente": "FFC7CE", "na": "D9D9D9"}
    cab = Font(bold=True, color="FFFFFF")
    azul = PatternFill("solid", fgColor="1F4E5F")

    headers = ["Projeto", "MoSCoW", "SKU", "Lançamento", "Avanço %"] + \
              [f"{t}\n({c})" for c, t in tipos]
    for j, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=j, value=h)
        cell.font = cab
        cell.fill = azul
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for i, p in enumerate(projetos, 2):
        ws.cell(row=i, column=1, value=p.nome).font = Font(bold=True)
        ws.cell(row=i, column=2, value=p.moscow)
        ws.cell(row=i, column=3, value=p.sku)
        ws.cell(row=i, column=4, value=p.lancamento)
        ws.cell(row=i, column=5, value=p.avanco)
        mapa = {(e.categoria, e.tipo): e for e in p.entregaveis}
        for j, chave in enumerate(tipos, 6):
            e = mapa.get(chave)
            if e is None:
                continue
            if e.status == "concluido":
                v = "OK"
            elif e.status == "em_progresso":
                v = f"{e.percentual or 0}%"
            elif e.status == "pendente":
                v = "Pendente"
            else:
                v = "NA"
            cell = ws.cell(row=i, column=j, value=v)
            cell.fill = PatternFill("solid", fgColor=CORES[e.status])
            cell.alignment = Alignment(horizontal="center")
    ws.column_dimensions["A"].width = 24
    for j in range(2, len(headers) + 1):
        ws.column_dimensions[get_column_letter(j)].width = 13
    ws.freeze_panes = "B2"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    nome = f"Entregaveis_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return send_file(
        buf, as_attachment=True, download_name=nome,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
