"""
fluxos/routes.py — Blueprint dos fluxos de revisão, montado sob /fluxos.

Um fluxo pendura num documento ou num entregável e anda por etapas com dono:
Escrita (autora) → Diagramação (diagramador) → Revisão (autora), com devoluções
até aprovar. Cada passagem fica registrada com comentário e arquivos, e quem
passa a ter a etapa é avisado pelo sino (pacote `notificacoes`).

## Acesso

Técnico para cima; `leitura` recebe 403 (um fluxo expõe quem está fazendo o quê,
como o quadro de Missões). Dentro disso:

  ver      gestão vê tudo; o técnico vê os fluxos de documento (Documentos é de
           toda a área), os fluxos em que é participante e os de entregável de
           um projeto que ele já enxerga no modo restrito
  agir     enviar/aprovar/devolver: o responsável pela etapa atual, ou a gestão
           EM NOME dele (fica gravado em `em_nome_de_id`)
  gerir    reatribuir e cancelar: gestão ou quem iniciou, com motivo
  modelos  criar/editar/arquivar: admin e gestor

## Rotas

  GET    /fluxos/                              página (casca)
  GET    /fluxos/api/modelos                   modelos ativos (?todos=1 inclui arquivados)
  POST   /fluxos/api/modelos                   cria (admin, gestor)
  PUT    /fluxos/api/modelos/<id>              edita / reativa (admin, gestor)
  DELETE /fluxos/api/modelos/<id>              arquiva (admin, gestor)
  GET    /fluxos/api/pessoas                   quem pode ocupar um papel (picker)
  GET    /fluxos/api/por-ref                   fluxo ativo + anteriores de um item
  GET    /fluxos/api/por-refs                  resumo em lote (chips das listas)
  GET    /fluxos/api/em-andamento              lista da página
  GET    /fluxos/api/comigo                    o que espera por mim
  POST   /fluxos/api/fluxos                    inicia
  GET    /fluxos/api/fluxos/<id>               detalhe com passagens e arquivos
  POST   /fluxos/api/fluxos/<id>/acao          enviar | aprovar | devolver (multipart)
  POST   /fluxos/api/fluxos/<id>/reatribuir    troca a pessoa de um papel
  POST   /fluxos/api/fluxos/<id>/cancelar      encerra sem aprovar
  GET    /fluxos/api/arquivos/<id>/conteudo    baixa/visualiza um anexo

## Transação

Passagem, arquivos, troca de etapa, status do documento/entregável e
notificações entram num commit só; auditoria e tempo real saem depois, como em
`documentos.update_status`. O blob vai para o disco antes do commit — um blob
órfão é inofensivo, o nome dele é o hash do conteúdo.
"""
import json
import os
from datetime import date, datetime

from flask import Blueprint, jsonify, render_template, request, send_file
from flask_jwt_extended import get_jwt_identity
from sqlalchemy.exc import IntegrityError

from models import (db, User, Documento, DocumentoArquivo, Entregavel, Projeto,
                    STATUS_FABRICANTE)
from auth import require_role, negar_acesso
import arquivos_store
from notificacoes.core import notificar

from . import core
from .models import (FluxoModelo, Fluxo, FluxoParticipante, FluxoPassagem,
                     FluxoArquivo, REF_TIPOS_FLUXO)

fluxos_bp = Blueprint("fluxos", __name__, url_prefix="/fluxos",
                      template_folder="templates")

# Setores cujo pipeline é Elaborar → Em andamento → Concluído. O PRE (IT e
# checklists) tem marcos externos — treinamento, homologação — que o fluxo não
# conhece, então o status dele não é tocado.
SETORES_SINCRONIZADOS = {"Manuais", "PDE"}

MAX_ARQUIVOS_POR_PASSAGEM = 10
MAX_COMENTARIO = 4000
PAPEIS_MEMBROS = ("admin", "gestor", "tecnico")

_rt = {"socketio": None, "publish_event": None, "AuditLog": None, "EventType": None}


def init_realtime(socketio, publish_event, AuditLog, EventType):
    _rt.update(socketio=socketio, publish_event=publish_event,
               AuditLog=AuditLog, EventType=EventType)


def so_membros(fn):
    return require_role("admin", "gestor", "tecnico")(fn)


def so_gestao(fn):
    return require_role("admin", "gestor")(fn)


def _eu():
    return User.query.filter_by(email=get_jwt_identity()).first()


def _e_gestao(u):
    return bool(u and u.role in ("admin", "gestor"))


def _emit(event_type, fluxo, u, **extra):
    """Tempo real + trilha, best-effort. Sem chave `id` no payload: publish_event
    a leria como documento_id da linha de auditoria."""
    if not (_rt["socketio"] and _rt["publish_event"]):
        return
    payload = {"entidade": "fluxo", "fluxo_id": fluxo.id, "ref_tipo": fluxo.ref_tipo,
               "ref_id": fluxo.ref_id, "status": fluxo.status,
               "etapa_atual": fluxo.etapa_atual or "", "titulo": fluxo.titulo or ""}
    payload.update(extra)
    try:
        _rt["publish_event"](event_type, payload, user_id=u.id if u else None,
                             user_email=u.email if u else None, db=db,
                             AuditLog=_rt["AuditLog"], socketio=_rt["socketio"])
    except Exception:
        pass


# ── ALVO (documento | entregável) ─────────────────────────────────────────────

def _carregar_alvo(ref_tipo, ref_id):
    """O objeto vinculado, ou None. Documento excluído conta como inexistente."""
    if ref_tipo == "documento":
        return Documento.query.filter_by(id=ref_id, ativo=True).first()
    if ref_tipo == "entregavel":
        return db.session.get(Entregavel, ref_id)
    return None


def _titulo_do_alvo(ref_tipo, alvo):
    if ref_tipo == "documento":
        nome = alvo.tipo_doc_label or alvo.documento or f"Documento #{alvo.id}"
        return f"{nome} · {alvo.equipamento}" if alvo.equipamento else nome
    projeto = alvo.projeto.nome if alvo.projeto else ""
    return f"{alvo.tipo} · {projeto}" if projeto else alvo.tipo


def _link(ref_tipo, ref_id, projeto_id=None):
    if ref_tipo == "documento":
        return f"/?doc={ref_id}"
    return f"/projetos?projeto={projeto_id}&entregavel={ref_id}"


def _link_do_fluxo(f):
    if f.ref_tipo == "entregavel":
        e = db.session.get(Entregavel, f.ref_id)
        return _link(f.ref_tipo, f.ref_id, e.projeto_id if e else "")
    return _link(f.ref_tipo, f.ref_id)


class _Visao:
    """Quem vê o quê, com cache por requisição (listas pedem a mesma coisa várias
    vezes). A regra está no docstring do módulo."""

    def __init__(self, u):
        self.u = u
        self._projetos = {}

    def _ve_projeto(self, projeto_id):
        if projeto_id not in self._projetos:
            from entregaveis import _responsavel_por
            p = db.session.get(Projeto, projeto_id)
            self._projetos[projeto_id] = bool(
                p and any(_responsavel_por(e, self.u) for e in p.entregaveis))
        return self._projetos[projeto_id]

    def alvo(self, ref_tipo, alvo):
        if _e_gestao(self.u) or ref_tipo == "documento":
            return True
        return self._ve_projeto(alvo.projeto_id)

    def fluxo(self, f):
        if _e_gestao(self.u) or f.ref_tipo == "documento":
            return True
        if any(p.user_id == self.u.id for p in f.participantes):
            return True
        if f.iniciado_por_id == self.u.id:
            return True
        e = db.session.get(Entregavel, f.ref_id)
        return bool(e and self._ve_projeto(e.projeto_id))


# ── SERIALIZAÇÃO ──────────────────────────────────────────────────────────────

def _pessoa(u):
    return {"id": u.id, "nome": u.nome, "ativo": bool(u.ativo)} if u else None


def _dias_desde(dt):
    return max(0, (datetime.now() - dt).days) if dt else 0


def _resumo(f):
    """O mínimo para um chip ou uma linha de lista."""
    etapas = f.etapas_lista()
    e = core.etapa(etapas, f.etapa_atual) if f.etapa_atual else None
    resp_id = core.responsavel(f.mapa_participantes(), etapas, f.etapa_atual) if e else None
    resp = db.session.get(User, resp_id) if resp_id else None
    return {
        "fluxo_id":     f.id,
        "ref_tipo":     f.ref_tipo,
        "ref_id":       f.ref_id,
        "titulo":       f.titulo or "",
        "modelo_nome":  f.modelo_nome or "",
        "status":       f.status,
        "rodada":       f.rodada or 1,
        "etapa_atual":  f.etapa_atual or "",
        "etapa_nome":   e["nome"] if e else "",
        "etapa_tipo":   e["tipo"] if e else "",
        "responsavel":  _pessoa(resp),
        "dias_na_etapa": _dias_desde(f.entrou_etapa_em) if f.status == "andamento" else 0,
        "prazo":        f.prazo.isoformat() if f.prazo else "",
        "atrasado":     bool(f.status == "andamento" and f.prazo and f.prazo < date.today()),
        "iniciado_em":  f.iniciado_em.strftime("%d/%m/%Y") if f.iniciado_em else "",
        "concluido_em": f.concluido_em.strftime("%d/%m/%Y %H:%M") if f.concluido_em else "",
        "link":         _link_do_fluxo(f),
    }


def _nome_etapa(etapas, chave):
    e = core.etapa(etapas, chave) if chave else None
    return e["nome"] if e else ""


def _passagem_dict(p, etapas):
    return {
        "id":          p.id,
        "acao":        p.acao,
        "de_etapa":    _nome_etapa(etapas, p.de_etapa),
        "para_etapa":  _nome_etapa(etapas, p.para_etapa),
        "rodada":      p.rodada or 1,
        "comentario":  p.comentario or "",
        "por":         p.por.nome if p.por else "(usuário removido)",
        "em_nome_de":  p.em_nome_de.nome if p.em_nome_de else "",
        "em":          p.em.strftime("%d/%m/%Y %H:%M") if p.em else "",
        "arquivos":    [a.to_dict() for a in p.arquivos],
    }


def _detalhe(f, u):
    d = _resumo(f)
    etapas = f.etapas_lista()
    papeis = {p["chave"]: p["nome"] for p in f.papeis_lista()}
    d["etapas"] = [{"chave": e["chave"], "nome": e["nome"], "tipo": e["tipo"],
                    "papel": e["papel"], "papel_nome": papeis.get(e["papel"], e["papel"])}
                   for e in etapas]
    d["participantes"] = [{"papel": p.papel, "papel_nome": papeis.get(p.papel, p.papel),
                           "pessoa": _pessoa(p.usuario)}
                          for p in sorted(f.participantes,
                                          key=lambda x: list(papeis).index(x.papel)
                                          if x.papel in papeis else 99)]
    d["iniciado_por"] = f.iniciado_por.nome if f.iniciado_por else ""
    d["versao"] = f.versao
    d["passagens"] = [_passagem_dict(p, etapas) for p in reversed(f.passagens)]
    pode, _ = _pode_agir(u, f)
    d["acoes"] = ([{"acao": a, "rotulo": core.rotulo_acao(etapas, f.etapa_atual, a)}
                   for a in core.acoes_possiveis(etapas, f.etapa_atual)]
                  if pode and f.status == "andamento" else [])
    d["em_nome_de"] = bool(pode and d["responsavel"] and d["responsavel"]["id"] != u.id)
    d["pode_gerir"] = f.status == "andamento" and (_e_gestao(u) or f.iniciado_por_id == u.id)
    return d


# ── REGRAS DE QUEM AGE ────────────────────────────────────────────────────────

def _pode_agir(u, f):
    """(pode, em_nome_de_id). A gestão age no lugar do responsável, registrado."""
    if f.status != "andamento":
        return False, None
    resp = core.responsavel(f.mapa_participantes(), f.etapas_lista(), f.etapa_atual)
    if u and resp == u.id:
        return True, None
    if _e_gestao(u):
        return True, resp
    return False, None


def _membro_ativo(uid):
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return None
    u = db.session.get(User, uid)
    return u if (u and u.ativo and u.role in PAPEIS_MEMBROS) else None


# ── STATUS DO ITEM VINCULADO ──────────────────────────────────────────────────

def _ao_iniciar(f, alvo, u):
    """Iniciar leva o item para 'em andamento'. Devolve o que publicar depois."""
    if f.ref_tipo == "documento":
        if alvo.setor in SETORES_SINCRONIZADOS and alvo.status == STATUS_FABRICANTE[0]:
            from documentos import aplicar_status_documento
            antigo = alvo.status
            return ("documento", alvo, antigo,
                    aplicar_status_documento(alvo, STATUS_FABRICANTE[1], u.email))
        return None
    if alvo.status == "pendente":
        from entregaveis import aplicar_status_entregavel
        return ("entregavel", alvo, aplicar_status_entregavel(alvo, "em_progresso", u.email), None)
    return None


def _ao_aprovar(f, alvo, u):
    """Aprovar conclui o item e, no documento, publica os arquivos finais."""
    if alvo is None:
        return None
    if f.ref_tipo == "documento":
        _copiar_finais_para_documento(f, alvo, u)
        if alvo.setor in SETORES_SINCRONIZADOS and alvo.status != STATUS_FABRICANTE[-1]:
            from documentos import aplicar_status_documento
            antigo = alvo.status
            return ("documento", alvo, antigo,
                    aplicar_status_documento(alvo, STATUS_FABRICANTE[-1], u.email))
        return None
    if alvo.status != "concluido":
        from entregaveis import aplicar_status_entregavel
        return ("entregavel", alvo, aplicar_status_entregavel(alvo, "concluido", u.email), None)
    return None


def _copiar_finais_para_documento(f, doc, u):
    """Os arquivos da última passagem de execução com anexo entram na lista de
    arquivos do documento — mesmo sha256, então nada é copiado em disco."""
    ultima = next((p for p in reversed(f.passagens) if p.acao == "enviar" and p.arquivos), None)
    if ultima is None:
        return
    versao = max((a.versao or 0 for a in (doc.arquivos or [])), default=0)
    for a in ultima.arquivos:
        versao += 1
        db.session.add(DocumentoArquivo(
            documento_id=doc.id, versao=versao, sha256=a.sha256,
            nome_original=a.nome_original, ext=a.ext, mime=a.mime, tamanho=a.tamanho,
            observacao=f"Aprovado no fluxo #{f.id}, rodada {f.rodada}"[:300],
            enviado_por=u.email))


def _publicar_item(mudanca, u):
    if not mudanca:
        return
    tipo, alvo, antigo, eventos = mudanca
    if tipo == "documento":
        from documentos import publicar_troca_status
        publicar_troca_status(alvo, antigo, u.email, eventos)
    else:
        from entregaveis import publicar_entregavel
        publicar_entregavel(alvo, u.email, antigo)


# ── NOTIFICAÇÕES ──────────────────────────────────────────────────────────────

def _avisar(f, *, para_etapa, encerra, ator, texto_acao, titulo_info, texto_info,
            titulo_acao=None):
    etapas = f.etapas_lista()
    ids_acao, ids_info = core.destinatarios(
        f.mapa_participantes(), etapas, para_etapa,
        iniciador_id=f.iniciado_por_id, ator_id=ator.id, encerra=encerra)
    link = _link_do_fluxo(f)
    if ids_acao:
        notificar(ids_acao, tipo="acao",
                  titulo=titulo_acao or f"É sua vez: {_nome_etapa(etapas, para_etapa)}",
                  texto=texto_acao, link=link, origem_tipo="fluxo", origem_id=f.id)
    if ids_info:
        notificar(ids_info, tipo="info", titulo=titulo_info, texto=texto_info,
                  link=link, origem_tipo="fluxo", origem_id=f.id)


def _quem(u, em_nome_de_id):
    if em_nome_de_id:
        outro = db.session.get(User, em_nome_de_id)
        return f"{u.nome} (em nome de {outro.nome if outro else 'responsável'})"
    return u.nome


# ── PÁGINA ────────────────────────────────────────────────────────────────────

@fluxos_bp.route("/")
@fluxos_bp.route("")
def index():
    # A página valida o token no front (igual a Tempos e Custos); os dados são
    # barrados em cada rota /fluxos/api/*.
    from servidor import _static_version
    return render_template("fluxos/dashboard.html", asset_v=_static_version())


# ── MODELOS ───────────────────────────────────────────────────────────────────

def _contagem_por_modelo():
    linhas = (db.session.query(Fluxo.modelo_id, db.func.count(Fluxo.id))
              .group_by(Fluxo.modelo_id).all())
    return {mid: n for mid, n in linhas}


@fluxos_bp.route("/api/modelos", methods=["GET"])
@so_membros
def listar_modelos():
    u = _eu()
    q = FluxoModelo.query
    if not (request.args.get("todos") == "1" and _e_gestao(u)):
        q = q.filter_by(ativo=True)
    n = _contagem_por_modelo()
    modelos = sorted(q.all(), key=lambda m: (not m.ativo, (m.nome or "").lower()))
    return jsonify({"modelos": [m.to_dict(n_fluxos=n.get(m.id, 0)) for m in modelos]})


def _validar_corpo_modelo(data, ignorar_id=None):
    nome = (data.get("nome") or "").strip()[:80]
    if not nome:
        return None, "Informe o nome do modelo"
    for m in FluxoModelo.query.all():
        if m.id != ignorar_id and (m.nome or "").strip().lower() == nome.lower():
            return None, f"Já existe um modelo chamado {m.nome}"
    papeis, etapas, erro = core.validar_modelo(data.get("papeis"), data.get("etapas"))
    if erro:
        return None, erro
    for p in papeis:
        if p["padrao_user_id"] and not _membro_ativo(p["padrao_user_id"]):
            return None, f"A pessoa padrão do papel {p['nome']} não está ativa"
    return {"nome": nome, "descricao": (data.get("descricao") or "").strip()[:1000],
            "papeis": papeis, "etapas": etapas}, None


@fluxos_bp.route("/api/modelos", methods=["POST"])
@so_gestao
def criar_modelo():
    u = _eu()
    corpo, erro = _validar_corpo_modelo(request.get_json(silent=True) or {})
    if erro:
        return jsonify({"erro": erro}), 400
    m = FluxoModelo(nome=corpo["nome"], descricao=corpo["descricao"],
                    papeis=json.dumps(corpo["papeis"], ensure_ascii=False),
                    etapas=json.dumps(corpo["etapas"], ensure_ascii=False),
                    criado_por=u.email, atualizado_por=u.email)
    db.session.add(m)
    db.session.commit()
    return jsonify({"modelo": m.to_dict(n_fluxos=0)}), 201


@fluxos_bp.route("/api/modelos/<int:mid>", methods=["PUT"])
@so_gestao
def editar_modelo(mid):
    u = _eu()
    m = db.session.get(FluxoModelo, mid)
    if m is None:
        return jsonify({"erro": "Modelo não encontrado"}), 404
    data = request.get_json(silent=True) or {}
    # Reativar/arquivar sozinho, sem mexer em etapas.
    if set(data) == {"ativo"}:
        m.ativo = bool(data["ativo"])
    else:
        corpo, erro = _validar_corpo_modelo(
            {"nome": data.get("nome", m.nome), "descricao": data.get("descricao", m.descricao),
             "papeis": data.get("papeis", m.papeis_lista()),
             "etapas": data.get("etapas", m.etapas_lista())}, ignorar_id=m.id)
        if erro:
            return jsonify({"erro": erro}), 400
        # Os fluxos em andamento guardam a própria cópia das etapas: editar aqui
        # vale só para os próximos.
        m.nome, m.descricao = corpo["nome"], corpo["descricao"]
        m.papeis = json.dumps(corpo["papeis"], ensure_ascii=False)
        m.etapas = json.dumps(corpo["etapas"], ensure_ascii=False)
        if "ativo" in data:
            m.ativo = bool(data["ativo"])
    m.atualizado_por = u.email
    db.session.commit()
    return jsonify({"modelo": m.to_dict(n_fluxos=_contagem_por_modelo().get(m.id, 0))})


@fluxos_bp.route("/api/modelos/<int:mid>", methods=["DELETE"])
@so_gestao
def arquivar_modelo(mid):
    u = _eu()
    m = db.session.get(FluxoModelo, mid)
    if m is None:
        return jsonify({"erro": "Modelo não encontrado"}), 404
    m.ativo = False
    m.atualizado_por = u.email
    db.session.commit()
    return jsonify({"modelo": m.to_dict()})


@fluxos_bp.route("/api/pessoas", methods=["GET"])
@so_membros
def pessoas():
    us = (User.query.filter(User.ativo == True, User.role.in_(PAPEIS_MEMBROS))
          .order_by(User.nome).all())
    return jsonify({"pessoas": [{"id": x.id, "nome": x.nome} for x in us]})


# ── CONSULTAS ─────────────────────────────────────────────────────────────────

def _ref_da_query():
    ref_tipo = (request.args.get("ref_tipo") or "").strip()
    if ref_tipo not in REF_TIPOS_FLUXO:
        return None, None, (jsonify({"erro": f"ref_tipo inválido. Use: {', '.join(REF_TIPOS_FLUXO)}"}), 400)
    return ref_tipo, request.args.get("ref_id", type=int), None


@fluxos_bp.route("/api/por-ref", methods=["GET"])
@so_membros
def por_ref():
    u = _eu()
    ref_tipo, ref_id, erro = _ref_da_query()
    if erro:
        return erro
    alvo = _carregar_alvo(ref_tipo, ref_id)
    if alvo is None:
        return jsonify({"erro": "Item não encontrado"}), 404
    visao = _Visao(u)
    if not visao.alvo(ref_tipo, alvo):
        ativo = Fluxo.query.filter_by(ref_tipo=ref_tipo, ref_id=ref_id, status="andamento").first()
        if not (ativo and visao.fluxo(ativo)):
            return negar_acesso(f"fluxo de {ref_tipo} #{ref_id} fora do alcance",
                                "Você não tem acesso a este item")
    fluxos = (Fluxo.query.filter_by(ref_tipo=ref_tipo, ref_id=ref_id)
              .order_by(Fluxo.id.desc()).all())
    ativo = next((f for f in fluxos if f.status == "andamento"), None)
    pode_iniciar = ativo is None and not (ref_tipo == "entregavel" and alvo.status == "na")
    return jsonify({
        "ativo": _detalhe(ativo, u) if ativo else None,
        "anteriores": [_resumo(f) for f in fluxos if f.status != "andamento"],
        "pode_iniciar": pode_iniciar,
        "titulo": _titulo_do_alvo(ref_tipo, alvo),
    })


@fluxos_bp.route("/api/por-refs", methods=["GET"])
@so_membros
def por_refs():
    u = _eu()
    ref_tipo, _, erro = _ref_da_query()
    if erro:
        return erro
    try:
        ids = [int(x) for x in (request.args.get("ids") or "").split(",") if x.strip()][:500]
    except ValueError:
        return jsonify({"erro": "ids deve ser uma lista de números"}), 400
    if not ids:
        return jsonify({"resumos": {}})
    visao = _Visao(u)
    fluxos = Fluxo.query.filter(Fluxo.ref_tipo == ref_tipo, Fluxo.ref_id.in_(ids),
                                Fluxo.status == "andamento").all()
    return jsonify({"resumos": {str(f.ref_id): _resumo(f) for f in fluxos if visao.fluxo(f)}})


@fluxos_bp.route("/api/em-andamento", methods=["GET"])
@so_membros
def em_andamento():
    u = _eu()
    visao = _Visao(u)
    out = []
    for f in Fluxo.query.filter_by(status="andamento").all():
        if not visao.fluxo(f):
            continue
        r = _resumo(f)
        r["responsavel_inativo"] = bool(r["responsavel"] is None or not r["responsavel"]["ativo"])
        out.append(r)
    out.sort(key=lambda r: (-r["dias_na_etapa"], r["titulo"]))
    return jsonify({"fluxos": out})


@fluxos_bp.route("/api/comigo", methods=["GET"])
@so_membros
def comigo():
    """Os fluxos cuja etapa atual é minha — o estado vivo, não as notificações."""
    u = _eu()
    meus = (Fluxo.query.join(FluxoParticipante)
            .filter(Fluxo.status == "andamento", FluxoParticipante.user_id == u.id)
            .distinct().all())
    out = [_resumo(f) for f in meus
           if core.responsavel(f.mapa_participantes(), f.etapas_lista(), f.etapa_atual) == u.id]
    out.sort(key=lambda r: -r["dias_na_etapa"])
    return jsonify({"fluxos": out})


def _fluxo_visivel(fid, u):
    f = db.session.get(Fluxo, fid)
    if f is None:
        return None, (jsonify({"erro": "Fluxo não encontrado"}), 404)
    if not _Visao(u).fluxo(f):
        return None, negar_acesso(f"fluxo #{fid} fora do alcance",
                                  "Você não tem acesso a este fluxo")
    return f, None


@fluxos_bp.route("/api/fluxos/<int:fid>", methods=["GET"])
@so_membros
def detalhe(fid):
    u = _eu()
    f, erro = _fluxo_visivel(fid, u)
    if erro:
        return erro
    return jsonify({"fluxo": _detalhe(f, u)})


# ── INICIAR ───────────────────────────────────────────────────────────────────

@fluxos_bp.route("/api/fluxos", methods=["POST"])
@so_membros
def iniciar():
    u = _eu()
    data = request.get_json(silent=True) or {}
    ref_tipo = (data.get("ref_tipo") or "").strip()
    if ref_tipo not in REF_TIPOS_FLUXO:
        return jsonify({"erro": f"ref_tipo inválido. Use: {', '.join(REF_TIPOS_FLUXO)}"}), 400
    try:
        ref_id = int(data.get("ref_id"))
    except (TypeError, ValueError):
        return jsonify({"erro": "ref_id inválido"}), 400
    alvo = _carregar_alvo(ref_tipo, ref_id)
    if alvo is None:
        return jsonify({"erro": "Item não encontrado"}), 404
    if not _Visao(u).alvo(ref_tipo, alvo):
        return negar_acesso(f"iniciar fluxo em {ref_tipo} #{ref_id} fora do alcance",
                            "Você não tem acesso a este item")
    if ref_tipo == "entregavel" and alvo.status == "na":
        return jsonify({"erro": "Entregável marcado como não se aplica não recebe fluxo"}), 400
    if ref_tipo == "documento" and not alvo.aplicavel:
        return jsonify({"erro": "Documento marcado como não se aplica não recebe fluxo"}), 400
    if Fluxo.query.filter_by(ref_tipo=ref_tipo, ref_id=ref_id, status="andamento").first():
        return jsonify({"erro": "Este item já tem um fluxo em andamento"}), 409

    m = db.session.get(FluxoModelo, data.get("modelo_id") or 0)
    if m is None or not m.ativo:
        return jsonify({"erro": "Escolha um modelo de fluxo ativo"}), 400
    papeis, etapas = m.papeis_lista(), m.etapas_lista()
    escolhidos = data.get("participantes") or {}
    if not isinstance(escolhidos, dict):
        return jsonify({"erro": "participantes deve ser {papel: pessoa}"}), 400
    participantes = {}
    for p in papeis:
        uid = escolhidos.get(p["chave"]) or p.get("padrao_user_id")
        pessoa = _membro_ativo(uid) if uid else None
        if pessoa is None:
            return jsonify({"erro": f"Escolha quem faz o papel {p['nome']}"}), 400
        participantes[p["chave"]] = pessoa.id

    prazo = None
    if data.get("prazo"):
        try:
            prazo = datetime.strptime(str(data["prazo"])[:10], "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"erro": "prazo deve ser AAAA-MM-DD"}), 400

    agora = datetime.now()
    primeira = etapas[0]["chave"]
    f = Fluxo(ref_tipo=ref_tipo, ref_id=ref_id, modelo_id=m.id, modelo_nome=m.nome,
              titulo=_titulo_do_alvo(ref_tipo, alvo)[:300],
              etapas=json.dumps(etapas, ensure_ascii=False),
              papeis=json.dumps(papeis, ensure_ascii=False),
              etapa_atual=primeira, status="andamento", rodada=1, prazo=prazo,
              iniciado_por_id=u.id, iniciado_em=agora, entrou_etapa_em=agora, versao=1)
    db.session.add(f)
    for chave, uid in participantes.items():
        f.participantes.append(FluxoParticipante(papel=chave, user_id=uid))
    f.passagens.append(FluxoPassagem(
        acao="iniciar", de_etapa="", para_etapa=primeira, rodada=1,
        comentario=(data.get("comentario") or "").strip()[:MAX_COMENTARIO],
        por_id=u.id, em=agora))
    try:
        db.session.flush()
    except IntegrityError:
        # Corrida: outra pessoa iniciou no mesmo instante. O índice parcial
        # único é quem decide — aqui só traduzimos.
        db.session.rollback()
        return jsonify({"erro": "Este item já tem um fluxo em andamento"}), 409

    mudanca = _ao_iniciar(f, alvo, u)
    resp = db.session.get(User, participantes[etapas[0]["papel"]])
    _avisar(f, para_etapa=primeira, encerra=False, ator=u,
            texto_acao=f"{f.titulo} — {u.nome} iniciou o fluxo {m.nome}",
            titulo_info=f"Fluxo iniciado: {f.titulo}",
            texto_info=f"{u.nome} iniciou; agora em {etapas[0]['nome']} com {resp.nome}")
    db.session.commit()
    _publicar_item(mudanca, u)
    _emit("FLUXO_INICIADO", f, u)
    return jsonify({"fluxo": _detalhe(f, u)}), 201


# ── AGIR ──────────────────────────────────────────────────────────────────────

def _versao_confere(f, enviada):
    try:
        return enviada is not None and int(enviada) == f.versao
    except (TypeError, ValueError):
        return False


def _conflito(f, u):
    return jsonify({"erro": "O fluxo mudou desde que você abriu. A tela foi atualizada.",
                    "fluxo": _detalhe(f, u)}), 409


def _guardar_arquivos(enviados):
    """[(sha, tamanho, nome)] ou resposta de erro. Valida tudo antes de gravar."""
    enviados = [a for a in enviados if a and (a.filename or "").strip()]
    if len(enviados) > MAX_ARQUIVOS_POR_PASSAGEM:
        return None, (jsonify({"erro": f"No máximo {MAX_ARQUIVOS_POR_PASSAGEM} arquivos por envio"}), 400)
    for a in enviados:
        nome = os.path.basename(a.filename.strip())
        if not arquivos_store.extensao_ok(nome):
            permitidas = ", ".join(sorted(e.lstrip(".") for e in arquivos_store.EXT_PERMITIDAS))
            return None, (jsonify({"erro": f"Formato não aceito ({nome}). Aceitos: {permitidas}"}), 415)
    out = []
    for a in enviados:
        nome = os.path.basename(a.filename.strip())
        try:
            sha, tamanho = arquivos_store.guardar(a.stream, nome)
        except arquivos_store.ArquivoGrandeDemais:
            return None, (jsonify({"erro": f"{nome} é maior que {arquivos_store.MAX_MB} MB"}), 413)
        except OSError as e:
            return None, (jsonify({"erro": f"Erro ao gravar {nome}: {e}"}), 500)
        out.append((sha, tamanho, nome))
    return out, None


@fluxos_bp.route("/api/fluxos/<int:fid>/acao", methods=["POST"])
@so_membros
def agir(fid):
    u = _eu()
    f, erro = _fluxo_visivel(fid, u)
    if erro:
        return erro
    dados = request.form if (request.form or request.files) else (request.get_json(silent=True) or {})
    if f.status != "andamento":
        return jsonify({"erro": "Este fluxo já foi encerrado", "fluxo": _detalhe(f, u)}), 409
    if not _versao_confere(f, dados.get("versao")):
        return _conflito(f, u)
    pode, em_nome_de = _pode_agir(u, f)
    if not pode:
        return negar_acesso(f"agir no fluxo #{f.id} sem ser o responsável",
                            "Só o responsável pela etapa atual pode agir agora")

    acao = (dados.get("acao") or "").strip()
    etapas = f.etapas_lista()
    try:
        para, encerra, soma_rodada = core.transicao(etapas, f.etapa_atual, acao)
    except ValueError as e:
        return jsonify({"erro": str(e)}), 400
    comentario = (dados.get("comentario") or "").strip()[:MAX_COMENTARIO]
    if acao == "devolver" and not comentario:
        return jsonify({"erro": "Para devolver, descreva os apontamentos"}), 400

    arquivos, erro = _guardar_arquivos(request.files.getlist("arquivos"))
    if erro:
        return erro

    agora = datetime.now()
    de = f.etapa_atual
    de_nome = _nome_etapa(etapas, de)
    if soma_rodada:
        f.rodada = (f.rodada or 1) + 1
    p = FluxoPassagem(acao=acao, de_etapa=de, para_etapa=para or "", rodada=f.rodada,
                      comentario=comentario, por_id=u.id, em_nome_de_id=em_nome_de, em=agora)
    for sha, tamanho, nome in arquivos:
        p.arquivos.append(FluxoArquivo(sha256=sha, nome_original=nome,
                                       ext=arquivos_store.ext_de(nome),
                                       mime=arquivos_store.mime_de(nome), tamanho=tamanho))
    f.passagens.append(p)
    f.versao = (f.versao or 1) + 1

    mudanca = None
    quem = _quem(u, em_nome_de)
    anexos = f" com {len(arquivos)} arquivo(s)" if arquivos else ""
    if encerra:
        f.status, f.etapa_atual, f.concluido_em = "aprovado", "", agora
        db.session.flush()        # a passagem nova precisa estar em f.passagens
        mudanca = _ao_aprovar(f, _carregar_alvo(f.ref_tipo, f.ref_id), u)
        _avisar(f, para_etapa=None, encerra=True, ator=u, texto_acao="",
                titulo_info=f"Aprovado: {f.titulo}",
                texto_info=f"{quem} concluiu o fluxo na rodada {f.rodada}")
    else:
        f.etapa_atual, f.entrou_etapa_em = para, agora
        para_nome = _nome_etapa(etapas, para)
        if acao == "devolver":
            _avisar(f, para_etapa=para, encerra=False, ator=u,
                    titulo_acao=f"Voltou para você: {para_nome} (rodada {f.rodada})",
                    texto_acao=f"{f.titulo} — {quem}: {comentario[:150]}",
                    titulo_info=f"{quem} devolveu para {para_nome}",
                    texto_info=f"{f.titulo} — rodada {f.rodada}")
        else:
            verbo = "aprovou" if acao == "aprovar" else "enviou"
            _avisar(f, para_etapa=para, encerra=False, ator=u,
                    texto_acao=f"{f.titulo} — {quem} {verbo} {de_nome}{anexos}",
                    titulo_info=f"{quem} {verbo} para {para_nome}",
                    texto_info=f.titulo)
    db.session.commit()
    _publicar_item(mudanca, u)
    _emit("FLUXO_CONCLUIDO" if encerra else "FLUXO_MOVIDO", f, u, acao=acao)
    return jsonify({"fluxo": _detalhe(f, u)})


# ── GERIR ─────────────────────────────────────────────────────────────────────

def _gerivel(f, u, dados):
    """Resposta de erro, ou None se a gestão desta ação pode seguir."""
    if f.status != "andamento":
        return jsonify({"erro": "Este fluxo já foi encerrado", "fluxo": _detalhe(f, u)}), 409
    if not (_e_gestao(u) or f.iniciado_por_id == u.id):
        return negar_acesso(f"gerir o fluxo #{f.id}",
                            "Só a gestão ou quem iniciou o fluxo pode fazer isto")
    if not _versao_confere(f, dados.get("versao")):
        return _conflito(f, u)
    if not (dados.get("motivo") or "").strip():
        return jsonify({"erro": "Informe o motivo"}), 400
    return None


@fluxos_bp.route("/api/fluxos/<int:fid>/reatribuir", methods=["POST"])
@so_membros
def reatribuir(fid):
    u = _eu()
    f, erro = _fluxo_visivel(fid, u)
    if erro:
        return erro
    dados = request.get_json(silent=True) or {}
    erro = _gerivel(f, u, dados)
    if erro:
        return erro
    papel = (dados.get("papel") or "").strip()
    part = next((p for p in f.participantes if p.papel == papel), None)
    if part is None:
        return jsonify({"erro": "Papel não existe neste fluxo"}), 400
    nova = _membro_ativo(dados.get("user_id"))
    if nova is None:
        return jsonify({"erro": "Escolha uma pessoa ativa"}), 400
    if part.user_id == nova.id:
        return jsonify({"erro": "Essa pessoa já ocupa o papel"}), 400

    papeis = {p["chave"]: p["nome"] for p in f.papeis_lista()}
    antiga = db.session.get(User, part.user_id) if part.user_id else None
    part.user_id = nova.id
    motivo = dados["motivo"].strip()[:500]
    f.passagens.append(FluxoPassagem(
        acao="reatribuir", de_etapa=f.etapa_atual, para_etapa=f.etapa_atual, rodada=f.rodada,
        comentario=f"{papeis.get(papel, papel)}: {antiga.nome if antiga else '—'} → {nova.nome}. "
                   f"Motivo: {motivo}",
        por_id=u.id, em=datetime.now()))
    f.versao = (f.versao or 1) + 1

    etapas = f.etapas_lista()
    e = core.etapa(etapas, f.etapa_atual)
    link = _link_do_fluxo(f)
    if e and e["papel"] == papel:
        notificar([nova.id], tipo="acao", exceto=u.id, titulo=f"É sua vez: {e['nome']}",
                  texto=f"{f.titulo} — {u.nome} passou o papel {papeis.get(papel, papel)} para você",
                  link=link, origem_tipo="fluxo", origem_id=f.id)
    else:
        notificar([nova.id], tipo="info", exceto=u.id,
                  titulo=f"Você entrou no fluxo como {papeis.get(papel, papel)}",
                  texto=f.titulo, link=link, origem_tipo="fluxo", origem_id=f.id)
    if antiga:
        notificar([antiga.id], tipo="info", exceto=u.id,
                  titulo=f"Você saiu do fluxo: {f.titulo}",
                  texto=f"{u.nome} passou o papel {papeis.get(papel, papel)} para {nova.nome}. {motivo}",
                  link=link, origem_tipo="fluxo", origem_id=f.id)
    db.session.commit()
    _emit("FLUXO_MOVIDO", f, u, acao="reatribuir")
    return jsonify({"fluxo": _detalhe(f, u)})


@fluxos_bp.route("/api/fluxos/<int:fid>/cancelar", methods=["POST"])
@so_membros
def cancelar(fid):
    u = _eu()
    f, erro = _fluxo_visivel(fid, u)
    if erro:
        return erro
    dados = request.get_json(silent=True) or {}
    erro = _gerivel(f, u, dados)
    if erro:
        return erro
    motivo = dados["motivo"].strip()[:500]
    agora = datetime.now()
    f.passagens.append(FluxoPassagem(
        acao="cancelar", de_etapa=f.etapa_atual, para_etapa="", rodada=f.rodada,
        comentario=motivo, por_id=u.id, em=agora))
    f.status, f.etapa_atual, f.concluido_em = "cancelado", "", agora
    f.versao = (f.versao or 1) + 1
    # Cancelar não mexe no status do item: o trabalho pode ter andado, e quem
    # decide o que ele vira é quem cancelou, pela tela do próprio item.
    _avisar(f, para_etapa=None, encerra=True, ator=u, texto_acao="",
            titulo_info=f"Fluxo cancelado: {f.titulo}", texto_info=f"{u.nome}: {motivo}")
    db.session.commit()
    _emit("FLUXO_CANCELADO", f, u)
    return jsonify({"fluxo": _detalhe(f, u)})


# ── ARQUIVOS ──────────────────────────────────────────────────────────────────

@fluxos_bp.route("/api/arquivos/<int:aid>/conteudo", methods=["GET"])
@so_membros
def conteudo_arquivo(aid):
    u = _eu()
    a = db.session.get(FluxoArquivo, aid)
    if a is None:
        return jsonify({"erro": "Arquivo não encontrado"}), 404
    f, erro = _fluxo_visivel(a.passagem.fluxo_id, u)
    if erro:
        return erro
    # O caminho vem do SHA gravado, nunca da requisição.
    real = arquivos_store.caminho_de(a.sha256)
    if not os.path.isfile(real):
        return jsonify({"erro": "Arquivo não está mais disponível no servidor"}), 404
    inline = arquivos_store.abre_inline(a.nome_original) and request.args.get("download") != "1"
    return send_file(real, as_attachment=not inline,
                     download_name=a.nome_original or f"arquivo{a.ext or ''}",
                     mimetype=a.mime or None, conditional=True)
