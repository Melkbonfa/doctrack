"""
missoes.py — Módulo Missões (kanban nativo tipo Planner)
Rotas (todas técnico+; `leitura` recebe 403):
  GET    /api/missoes                    — lista missões ativas (leve)
  POST   /api/missoes                    — criar (semeia 3 colunas padrão)
  GET    /api/missoes/<id>               — board completo (colunas + cartões, sem descrição)
  PATCH  /api/missoes/<id>               — renomear/cor/arquivar
  DELETE /api/missoes/<id>               — excluir (cascade)
  POST   /api/missoes/<id>/colunas       — criar coluna
  PATCH  /api/missoes/colunas/<id>       — renomear/cor/categoria
  DELETE /api/missoes/colunas/<id>       — excluir coluna (cascade nos cartões)
  POST   /api/missoes/colunas/<id>/cartoes — criar cartão
  GET    /api/missoes/cartoes/<id>       — cartão completo (com descrição)
  PATCH  /api/missoes/cartoes/<id>       — editar (guardado por `versao` → 409)
  DELETE /api/missoes/cartoes/<id>       — excluir cartão
  POST   /api/missoes/reordenar          — reordenar/mover (transação; `versao` → 409)
  GET    /api/missoes/refs               — busca Equipamento/Projeto/Documento p/ vínculo

Decisões (pesquisa em planner-missoes-pesquisa/report.md): ordem int reindexada
em transação (suficiente no MVP; fractional/LexoRank só em escala), `versao` como
lock otimista (equivalente do @odata.etag/412 do Graph), board sem `descricao`
(split leve/pesado do plannerTask↔plannerTaskDetails).
"""
import re
from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity

from models import (db, Missao, MissaoColuna, MissaoCartao,
                    PRIORIDADES_CARTAO, REF_TIPOS_CARTAO, CATEGORIAS_COLUNA,
                    Equipamento, Projeto, Documento, User)
from auth import require_role, log_action, get_client_ip

# SQLite não aplica String(n) — os limites precisam ser validados aqui.
_RE_ISO_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_COR_HEX  = re.compile(r"^#[0-9a-fA-F]{3,8}$")
MAX_TITULO, MAX_NOME_MISSAO, MAX_NOME_COLUNA = 200, 160, 80
MAX_RESPONSAVEIS, MAX_ETIQUETAS = 200, 300


def _erro_tamanho(valor, maximo, campo):
    if valor and len(valor) > maximo:
        return f"{campo} muito longo (máx. {maximo} caracteres)"
    return None

missoes_bp = Blueprint("missoes", __name__)

COLUNAS_PADRAO = [("A fazer", "todo"), ("Fazendo", "doing"), ("Concluído", "done")]

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


def _validar_ref(ref_tipo, ref_id):
    """Vínculo opcional: confere existência ao gravar (sem FK rígida).
    Devolve (ref_tipo, ref_id, erro|None)."""
    if not ref_tipo:
        return "", None, None
    if ref_tipo not in REF_TIPOS_CARTAO:
        return None, None, f"ref_tipo inválido. Use: {', '.join(REF_TIPOS_CARTAO)}"
    try:
        rid = int(ref_id)
    except (TypeError, ValueError):
        return None, None, "ref_id deve ser número"
    modelo = {"equipamento": Equipamento, "projeto": Projeto, "documento": Documento}[ref_tipo]
    alvo = modelo.query.get(rid)
    if not alvo or not alvo.ativo:
        return None, None, f"{ref_tipo} {rid} não encontrado"
    return ref_tipo, rid, None


# ── MISSÕES ──────────────────────────────────────────────────────────────────

@missoes_bp.route("/api/missoes", methods=["GET"])
@require_role("admin", "gestor", "tecnico")
def listar_missoes():
    arquivadas = request.args.get("arquivadas", "").strip() == "1"
    missoes = (Missao.query.filter_by(arquivado=arquivadas)
               .order_by(Missao.ordem, Missao.id).all())
    # contagem agregada numa query só (evita carregar os cartões de cada missão)
    counts = dict(db.session.query(MissaoCartao.missao_id, db.func.count(MissaoCartao.id))
                  .group_by(MissaoCartao.missao_id).all())
    return jsonify({"missoes": [m.to_dict(n_cartoes=counts.get(m.id, 0)) for m in missoes]})


@missoes_bp.route("/api/missoes", methods=["POST"])
@require_role("admin", "gestor", "tecnico")
def criar_missao():
    data = request.get_json(silent=True) or {}
    nome = (data.get("nome") or "").strip()
    if not nome:
        return jsonify({"erro": "nome é obrigatório"}), 400
    erro = _erro_tamanho(nome, MAX_NOME_MISSAO, "nome")
    if erro:
        return jsonify({"erro": erro}), 400
    accent = (data.get("accent") or "").strip()
    if accent and not _RE_COR_HEX.match(accent):
        return jsonify({"erro": "accent deve ser cor hex (#rrggbb)"}), 400
    email = get_jwt_identity()
    ult = Missao.query.order_by(Missao.ordem.desc()).first()
    m = Missao(nome=nome,
               descricao=(data.get("descricao") or "").strip(),
               accent=accent,
               ordem=(ult.ordem + 1) if ult else 0,
               criado_por=email)
    db.session.add(m)
    db.session.flush()   # garante m.id para as colunas
    for i, (nome_col, cat) in enumerate(COLUNAS_PADRAO):
        db.session.add(MissaoColuna(missao_id=m.id, nome=nome_col,
                                    categoria=cat, ordem=i))
    db.session.commit()
    log_action(email, "CREATE", entidade=f"Missão: {m.nome}", ip=get_client_ip())
    _emit("MISSAO_CREATED", {"missao": m.to_dict()}, email)
    return jsonify({"missao": m.to_dict(com_colunas=True)}), 201


@missoes_bp.route("/api/missoes/<int:mid>", methods=["GET"])
@require_role("admin", "gestor", "tecnico")
def detalhe_missao(mid):
    # eager-load colunas+cartões em 3 queries (sem isso o board faz 1 query por coluna)
    m = (Missao.query
         .options(db.selectinload(Missao.colunas).selectinload(MissaoColuna.cartoes))
         .get_or_404(mid))
    return jsonify({"missao": m.to_dict(com_colunas=True)})


@missoes_bp.route("/api/missoes/<int:mid>", methods=["PATCH"])
@require_role("admin", "gestor", "tecnico")
def editar_missao(mid):
    m = Missao.query.get_or_404(mid)
    data = request.get_json(silent=True) or {}
    email = get_jwt_identity()
    if "nome" in data:
        nome = (data.get("nome") or "").strip()
        if not nome:
            return jsonify({"erro": "nome não pode ficar vazio"}), 400
        erro = _erro_tamanho(nome, MAX_NOME_MISSAO, "nome")
        if erro:
            return jsonify({"erro": erro}), 400
        m.nome = nome
    if "descricao" in data:
        m.descricao = (data.get("descricao") or "").strip()
    if "accent" in data:
        accent = (data.get("accent") or "").strip()
        if accent and not _RE_COR_HEX.match(accent):
            return jsonify({"erro": "accent deve ser cor hex (#rrggbb)"}), 400
        m.accent = accent
    if "arquivado" in data:
        m.arquivado = bool(data.get("arquivado"))
    db.session.commit()
    log_action(email, "UPDATE", entidade=f"Missão: {m.nome}", ip=get_client_ip())
    _emit("MISSAO_UPDATED", {"missao": m.to_dict()}, email)
    return jsonify({"missao": m.to_dict()})


@missoes_bp.route("/api/missoes/<int:mid>", methods=["DELETE"])
@require_role("admin", "gestor", "tecnico")
def excluir_missao(mid):
    m = Missao.query.get_or_404(mid)
    nome = m.nome
    db.session.delete(m)   # cascade: colunas + cartões
    db.session.commit()
    email = get_jwt_identity()
    log_action(email, "DELETE", entidade=f"Missão: {nome}", ip=get_client_ip())
    _emit("MISSAO_DELETED", {"missao_id": mid}, email)
    return jsonify({"ok": True})


# ── COLUNAS ──────────────────────────────────────────────────────────────────

@missoes_bp.route("/api/missoes/<int:mid>/colunas", methods=["POST"])
@require_role("admin", "gestor", "tecnico")
def criar_coluna(mid):
    m = Missao.query.get_or_404(mid)
    data = request.get_json(silent=True) or {}
    nome = (data.get("nome") or "").strip()
    if not nome:
        return jsonify({"erro": "nome é obrigatório"}), 400
    erro = _erro_tamanho(nome, MAX_NOME_COLUNA, "nome")
    if erro:
        return jsonify({"erro": erro}), 400
    cat = (data.get("categoria") or "").strip()
    if cat and cat not in CATEGORIAS_COLUNA:
        return jsonify({"erro": f"categoria inválida. Use: {', '.join(CATEGORIAS_COLUNA)}"}), 400
    ult = (MissaoColuna.query.filter_by(missao_id=m.id)
           .order_by(MissaoColuna.ordem.desc()).first())
    c = MissaoColuna(missao_id=m.id, nome=nome, categoria=cat,
                     cor=(data.get("cor") or "").strip(),
                     ordem=(ult.ordem + 1) if ult else 0)
    db.session.add(c)
    db.session.commit()
    email = get_jwt_identity()
    log_action(email, "CREATE", entidade=f"Missão: {m.nome} · Coluna: {nome}", ip=get_client_ip())
    _emit("MISSAO_COLUNA_CREATED", {"missao_id": m.id, "coluna": c.to_dict(com_cartoes=True)}, email)
    return jsonify({"coluna": c.to_dict(com_cartoes=True)}), 201


@missoes_bp.route("/api/missoes/colunas/<int:cid>", methods=["PATCH"])
@require_role("admin", "gestor", "tecnico")
def editar_coluna(cid):
    c = MissaoColuna.query.get_or_404(cid)
    data = request.get_json(silent=True) or {}
    if "nome" in data:
        nome = (data.get("nome") or "").strip()
        if not nome:
            return jsonify({"erro": "nome não pode ficar vazio"}), 400
        erro = _erro_tamanho(nome, MAX_NOME_COLUNA, "nome")
        if erro:
            return jsonify({"erro": erro}), 400
        c.nome = nome
    if "cor" in data:
        c.cor = (data.get("cor") or "").strip()
    if "categoria" in data:
        cat = (data.get("categoria") or "").strip()
        if cat and cat not in CATEGORIAS_COLUNA:
            return jsonify({"erro": f"categoria inválida. Use: {', '.join(CATEGORIAS_COLUNA)}"}), 400
        c.categoria = cat
    db.session.commit()
    email = get_jwt_identity()
    _emit("MISSAO_COLUNA_UPDATED", {"missao_id": c.missao_id, "coluna": c.to_dict()}, email)
    return jsonify({"coluna": c.to_dict()})


@missoes_bp.route("/api/missoes/colunas/<int:cid>", methods=["DELETE"])
@require_role("admin", "gestor", "tecnico")
def excluir_coluna(cid):
    c = MissaoColuna.query.get_or_404(cid)
    mid, nome = c.missao_id, c.nome
    db.session.delete(c)   # cascade nos cartões da coluna
    db.session.commit()
    email = get_jwt_identity()
    log_action(email, "DELETE", entidade=f"Coluna de missão: {nome}", ip=get_client_ip())
    _emit("MISSAO_COLUNA_DELETED", {"missao_id": mid, "coluna_id": cid}, email)
    return jsonify({"ok": True})


# ── CARTÕES ──────────────────────────────────────────────────────────────────

_CARTAO_STR = ("responsaveis", "prazo", "etiquetas")


def _aplicar_campos_cartao(cartao, data):
    """Aplica campos simples do payload ao cartão. Devolve erro|None."""
    if "titulo" in data:
        titulo = (data.get("titulo") or "").strip()
        if not titulo:
            return "titulo não pode ficar vazio"
        erro = _erro_tamanho(titulo, MAX_TITULO, "titulo")
        if erro:
            return erro
        cartao.titulo = titulo
    if "descricao" in data:
        cartao.descricao = (data.get("descricao") or "").strip()
    _maximos = {"responsaveis": MAX_RESPONSAVEIS, "etiquetas": MAX_ETIQUETAS, "prazo": 40}
    for campo in _CARTAO_STR:
        if campo in data:
            valor = (data.get(campo) or "").strip()
            if campo == "prazo" and valor and not _RE_ISO_DATA.match(valor):
                return "prazo deve estar no formato AAAA-MM-DD"
            erro = _erro_tamanho(valor, _maximos[campo], campo)
            if erro:
                return erro
            setattr(cartao, campo, valor)
    if "prioridade" in data:
        pri = (data.get("prioridade") or "media").strip()
        if pri not in PRIORIDADES_CARTAO:
            return f"prioridade inválida. Use: {', '.join(PRIORIDADES_CARTAO)}"
        cartao.prioridade = pri
    if "concluido" in data:
        cartao.concluido = bool(data.get("concluido"))
    if "ref_tipo" in data or "ref_id" in data:
        ref_tipo, ref_id, erro = _validar_ref(
            (data.get("ref_tipo") or "").strip(), data.get("ref_id"))
        if erro:
            return erro
        cartao.ref_tipo, cartao.ref_id = ref_tipo, ref_id
    return None


@missoes_bp.route("/api/missoes/colunas/<int:cid>/cartoes", methods=["POST"])
@require_role("admin", "gestor", "tecnico")
def criar_cartao(cid):
    col = MissaoColuna.query.get_or_404(cid)
    data = request.get_json(silent=True) or {}
    titulo = (data.get("titulo") or "").strip()
    if not titulo:
        return jsonify({"erro": "titulo é obrigatório"}), 400
    email = get_jwt_identity()
    ult = (MissaoCartao.query.filter_by(coluna_id=col.id)
           .order_by(MissaoCartao.ordem.desc()).first())
    cartao = MissaoCartao(missao_id=col.missao_id, coluna_id=col.id,
                          titulo=titulo, criado_por=email, atualizado_por=email,
                          ordem=(ult.ordem + 1) if ult else 0)
    erro = _aplicar_campos_cartao(cartao, data)
    if erro:
        return jsonify({"erro": erro}), 400
    db.session.add(cartao)
    db.session.commit()
    log_action(email, "CREATE", entidade=f"Cartão: {titulo}", ip=get_client_ip())
    _emit("MISSAO_CARTAO_CREATED",
          {"missao_id": col.missao_id, "cartao": cartao.to_dict()}, email)
    return jsonify({"cartao": cartao.to_dict()}), 201


@missoes_bp.route("/api/missoes/cartoes/<int:cid>", methods=["GET"])
@require_role("admin", "gestor", "tecnico")
def detalhe_cartao(cid):
    cartao = MissaoCartao.query.get_or_404(cid)
    return jsonify({"cartao": cartao.to_dict(com_descricao=True)})


@missoes_bp.route("/api/missoes/cartoes/<int:cid>", methods=["PATCH"])
@require_role("admin", "gestor", "tecnico")
def editar_cartao(cid):
    cartao = MissaoCartao.query.get_or_404(cid)
    data = request.get_json(silent=True) or {}
    # Lock otimista: se o cliente mandou a versão que leu e ela não bate mais,
    # outro usuário editou no meio — 409 e o cliente recarrega o cartão.
    if "versao" in data and int(data.get("versao") or 0) != (cartao.versao or 0):
        return jsonify({"erro": "conflito de edição — recarregue o cartão",
                        "cartao": cartao.to_dict(com_descricao=True)}), 409
    erro = _aplicar_campos_cartao(cartao, data)
    if erro:
        return jsonify({"erro": erro}), 400
    email = get_jwt_identity()
    cartao.versao = (cartao.versao or 0) + 1
    cartao.atualizado_por = email
    cartao.atualizado_em = datetime.now()
    db.session.commit()
    _emit("MISSAO_CARTAO_UPDATED",
          {"missao_id": cartao.missao_id, "cartao": cartao.to_dict()}, email)
    return jsonify({"cartao": cartao.to_dict(com_descricao=True)})


@missoes_bp.route("/api/missoes/cartoes/<int:cid>", methods=["DELETE"])
@require_role("admin", "gestor", "tecnico")
def excluir_cartao(cid):
    cartao = MissaoCartao.query.get_or_404(cid)
    mid, titulo = cartao.missao_id, cartao.titulo
    db.session.delete(cartao)
    db.session.commit()
    email = get_jwt_identity()
    log_action(email, "DELETE", entidade=f"Cartão: {titulo}", ip=get_client_ip())
    _emit("MISSAO_CARTAO_DELETED", {"missao_id": mid, "cartao_id": cid}, email)
    return jsonify({"ok": True})


# ── REORDENAR / MOVER ────────────────────────────────────────────────────────

def _reindexar(coluna_id, ids):
    """Reatribui ordem = índice para os cartões da coluna, na ordem enviada.
    Cartões da coluna fora da lista vão para o fim (ordem preservada)."""
    ids = [int(i) for i in ids]
    cartoes = {c.id: c for c in MissaoCartao.query.filter_by(coluna_id=coluna_id).all()}
    pos = 0
    for i in ids:
        c = cartoes.pop(i, None)
        if c is not None:
            c.ordem = pos
            pos += 1
    for c in sorted(cartoes.values(), key=lambda x: x.ordem or 0):
        c.ordem = pos
        pos += 1


@missoes_bp.route("/api/missoes/reordenar", methods=["POST"])
@require_role("admin", "gestor", "tecnico")
def reordenar():
    """Duas formas (tudo numa única transação, ordem = índice da lista):
      {coluna_id, ids:[...]}                                — reordenar na coluna
      {cartao_id, versao, coluna_destino_id, ids:[...],
       ids_origem:[...]}                                    — mover entre colunas
    O move é guardado pela `versao` do cartão (conflito ⇒ 409)."""
    data = request.get_json(silent=True) or {}
    email = get_jwt_identity()

    cartao_id = data.get("cartao_id")
    if cartao_id:
        cartao = MissaoCartao.query.get_or_404(int(cartao_id))
        destino = MissaoColuna.query.get_or_404(int(data.get("coluna_destino_id") or 0))
        if destino.missao_id != cartao.missao_id:
            return jsonify({"erro": "coluna de outra missão"}), 400
        # Lock otimista do move: dois usuários arrastando o mesmo cartão não
        # podem se sobrescrever em silêncio (pesquisa: @odata.etag → 412/409).
        if "versao" in data and int(data.get("versao") or 0) != (cartao.versao or 0):
            return jsonify({"erro": "conflito — o cartão foi movido por outro usuário",
                            "cartao": cartao.to_dict()}), 409
        origem_id = cartao.coluna_id
        cartao.coluna_id = destino.id
        cartao.versao = (cartao.versao or 0) + 1
        cartao.atualizado_por = email
        cartao.atualizado_em = datetime.now()
        db.session.flush()
        _reindexar(destino.id, data.get("ids") or [])
        if origem_id != destino.id:
            _reindexar(origem_id, data.get("ids_origem") or [])
        db.session.commit()
        _emit("MISSAO_CARTAO_MOVIDO",
              {"missao_id": cartao.missao_id, "cartao": cartao.to_dict(),
               "coluna_origem_id": origem_id}, email)
        return jsonify({"cartao": cartao.to_dict()})

    coluna_id = data.get("coluna_id")
    if coluna_id:
        col = MissaoColuna.query.get_or_404(int(coluna_id))
        _reindexar(col.id, data.get("ids") or [])
        db.session.commit()
        _emit("MISSAO_COLUNA_REORDENADA",
              {"missao_id": col.missao_id, "coluna": col.to_dict(com_cartoes=True)}, email)
        return jsonify({"coluna": col.to_dict(com_cartoes=True)})

    # Reordenar as próprias colunas do board: {missao_id, colunas_ids:[...]}
    missao_id = data.get("missao_id")
    if missao_id and isinstance(data.get("colunas_ids"), list):
        m = Missao.query.get_or_404(int(missao_id))
        colunas = {c.id: c for c in m.colunas}
        pos = 0
        for i in data["colunas_ids"]:
            c = colunas.pop(int(i), None)
            if c is not None:
                c.ordem = pos
                pos += 1
        for c in sorted(colunas.values(), key=lambda x: x.ordem or 0):
            c.ordem = pos
            pos += 1
        db.session.commit()
        _emit("MISSAO_COLUNAS_REORDENADAS", {"missao_id": m.id}, email)
        return jsonify({"ok": True})

    return jsonify({"erro": "envie coluna_id, cartao_id ou missao_id"}), 400


# ── USUÁRIOS (p/ o seletor de responsáveis) ──────────────────────────────────

@missoes_bp.route("/api/missoes/usuarios", methods=["GET"])
@require_role("admin", "gestor", "tecnico")
def listar_usuarios_leve():
    """Só nomes de usuários ativos, para o autocomplete de responsáveis.
    (O /api/users completo é gestor+; aqui técnicos precisam da lista, então
    expõe-se apenas o nome — nada de email/role/áreas.)"""
    users = User.query.filter_by(ativo=True).order_by(User.nome).all()
    return jsonify({"usuarios": [u.nome for u in users if (u.nome or "").strip()]})


# ── MEUS CARTÕES (visão cross-missão por responsável) ────────────────────────

@missoes_bp.route("/api/missoes/meus-cartoes", methods=["GET"])
@require_role("admin", "gestor", "tecnico")
def meus_cartoes():
    """Cartões (não concluídos, de missões ativas) onde o usuário logado está
    nos responsáveis. Match pelo nome do usuário dentro do CSV — a mesma
    convenção do módulo Projetos (Entregavel.responsaveis)."""
    email = get_jwt_identity()
    user = User.query.filter_by(email=email).first()
    nome = (user.nome or "").strip() if user else ""
    if not nome:
        return jsonify({"cartoes": []})
    cartoes = (MissaoCartao.query
               .join(Missao, MissaoCartao.missao_id == Missao.id)
               .filter(Missao.arquivado == False,
                       MissaoCartao.concluido == False,
                       MissaoCartao.responsaveis.ilike(f"%{nome}%"))
               .order_by(MissaoCartao.prazo == "", MissaoCartao.prazo,
                         MissaoCartao.missao_id, MissaoCartao.ordem)
               .all())
    out = []
    for c in cartoes:
        d = c.to_dict()
        d["missao_nome"] = c.missao.nome if c.missao else ""
        d["coluna_nome"] = c.coluna.nome if c.coluna else ""
        out.append(d)
    return jsonify({"cartoes": out})


# ── BUSCA DE REFERÊNCIAS (p/ o seletor de vínculo do modal) ──────────────────

@missoes_bp.route("/api/missoes/refs", methods=["GET"])
@require_role("admin", "gestor", "tecnico")
def buscar_refs():
    """Busca leve por tipo p/ o dropdown de vínculo. ?tipo=equipamento&q=..."""
    tipo = (request.args.get("tipo") or "").strip()
    q = (request.args.get("q") or "").strip()
    if tipo not in REF_TIPOS_CARTAO:
        return jsonify({"erro": f"tipo inválido. Use: {', '.join(REF_TIPOS_CARTAO)}"}), 400
    out = []
    if tipo == "equipamento":
        query = Equipamento.query.filter(Equipamento.ativo == True)
        if q:
            query = query.filter(Equipamento.nome.ilike(f"%{q}%"))
        out = [{"id": e.id, "label": e.nome} for e in
               query.order_by(Equipamento.nome).limit(20).all()]
    elif tipo == "projeto":
        query = Projeto.query.filter(Projeto.ativo == True)
        if q:
            query = query.filter(Projeto.nome.ilike(f"%{q}%"))
        out = [{"id": p.id, "label": p.nome} for p in
               query.order_by(Projeto.nome).limit(20).all()]
    else:  # documento
        query = Documento.query.filter(Documento.ativo == True)
        if q:
            query = query.filter(Documento.documento.ilike(f"%{q}%"))
        out = [{"id": d.id, "label": d.documento} for d in
               query.order_by(Documento.documento).limit(20).all()]
    return jsonify({"itens": out})
