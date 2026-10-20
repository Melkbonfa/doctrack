"""
cadernos/routes.py — Blueprint do módulo Cadernos (cadernos de laboratório).

Montado sob /cadernos. Reutiliza autenticação, audit log e o blob store do mestre.
Plano completo: docs/planos/PLANO_cadernos.md.

## Acesso

Toda rota de dados é `@jwt_required()` e passa por `_carregar()`, que resolve o
papel da pessoa NAQUELE caderno (`core.papel_efetivo`): admin, dono, membro
explícito, ou o `acesso_area` do caderno para quem tem a área. Nenhuma rota
decide permissão por conta própria — é o mesmo princípio do gate de dono do
módulo Tempos, aplicado por caderno. Toda recusa (o 403 e o 404 de caderno sem
acesso) vai para a trilha como ACESSO_NEGADO, deduplicada (ver auth.py).

## Rotas

  GET    /cadernos/                                   página
  GET    /cadernos/api/meta?area=                     eu, área, modelos, pessoas
  GET    /cadernos/api/cadernos?area=                 cadernos visíveis
  POST   /cadernos/api/cadernos                       cria (com modelo de seções)
  GET    /cadernos/api/cadernos/<uuid>                detalhe + membros
  PATCH  /cadernos/api/cadernos/<uuid>                renomeia, cor, acesso
  DELETE /cadernos/api/cadernos/<uuid>                lixeira
  POST   /cadernos/api/cadernos/<uuid>/restaurar      tira da lixeira
  PUT    /cadernos/api/cadernos/<uuid>/membros        define os membros
  GET    /cadernos/api/cadernos/<uuid>/arvore         grupos, seções, páginas
  POST   /cadernos/api/cadernos/<uuid>/nos            novo grupo/seção
  PATCH  /cadernos/api/nos/<uuid>                     renomeia, cor
  DELETE /cadernos/api/nos/<uuid>                     lixeira
  POST   /cadernos/api/nos/<uuid>/restaurar           tira da lixeira
  POST   /cadernos/api/nos/<uuid>/mover               reordena / troca de grupo
  POST   /cadernos/api/secoes/<uuid>/paginas          nova página
  GET    /cadernos/api/paginas/<uuid>                 conteúdo (marca nada como lido ainda)
  PATCH  /cadernos/api/paginas/<uuid>                 título, data, recolhida
  PUT    /cadernos/api/paginas/<uuid>                 grava o conteúdo (exige a trava)
  DELETE /cadernos/api/paginas/<uuid>                 lixeira
  POST   /cadernos/api/paginas/<uuid>/restaurar       tira da lixeira
  POST   /cadernos/api/paginas/<uuid>/mover           move a página e suas subpáginas
  POST   /cadernos/api/paginas/<uuid>/nivel           promove / rebaixa
  POST   /cadernos/api/paginas/<uuid>/edicao          pega a trava
  PUT    /cadernos/api/paginas/<uuid>/edicao          renova a trava
  DELETE /cadernos/api/paginas/<uuid>/edicao          solta a trava (fecha a sessão)
  POST   /cadernos/api/paginas/<uuid>/edicao/tomar    dono toma a edição
  GET    /cadernos/api/paginas/<uuid>/versoes         histórico
  GET    /cadernos/api/paginas/<uuid>/versoes/<v>     uma versão
  POST   /cadernos/api/paginas/<uuid>/versoes/<v>/restaurar
  POST   /cadernos/api/paginas/<uuid>/imagens         imagem colada/enviada no editor
  GET    /cadernos/api/arquivos?caderno=&escopo=&ref= arquivos de um escopo
  POST   /cadernos/api/arquivos                       envia (QUALQUER extensão)
  GET    /cadernos/api/arquivos/<uuid>/versoes        versões do arquivo
  POST   /cadernos/api/arquivos/<uuid>/versao         nova versão
  PATCH  /cadernos/api/arquivos/<uuid>                pasta, descrição, exportação
  DELETE /cadernos/api/arquivos/<uuid>                lixeira (todas as versões)
  GET    /cadernos/api/arquivos/<uuid>/conteudo       baixa / exibe (?atual=1: versão vigente)
  POST   /cadernos/api/cadernos/<uuid>/exportacao/previa  páginas + arquivos candidatos
  POST   /cadernos/api/cadernos/<uuid>/exportacoes    gera o zip para a liderança (tarefa)
  GET    /cadernos/api/tarefas/<id>                   progresso de exportação/importação
  GET    /cadernos/api/cadernos/<uuid>/exportacoes    histórico de exportações
  GET    /cadernos/api/exportacoes/<uuid>/zip         baixa o zip gerado
  GET    /cadernos/api/onenote/assistente             baixa o assistente (.cmd) de extração
  POST   /cadernos/api/importacoes                    recebe o .zip do assistente (resumo)
  POST   /cadernos/api/importacoes/<id>/iniciar       confirma e grava (tarefa)
  DELETE /cadernos/api/importacoes/<id>               descarta o pacote recebido
  GET    /cadernos/api/busca?area=&q=&caderno=        busca no texto
  GET    /cadernos/api/lixeira?caderno=               o que foi excluído
"""
import io
import json
import os
import uuid as _uuid
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required

import arquivos_store
from auth import log_action, get_client_ip, negar_acesso, registrar_acesso_negado
from models import db, User
from utils import norm

from . import core, exportacao, tarefas
from .models import (
    Caderno, CadernoMembro, CadernoNo, CadernoPagina, CadernoPaginaVersao,
    CadernoArquivo, CadernoExportacao, ACESSOS_AREA, TIPOS_NO, TIPOS_PAGINA, ESCOPOS_ARQUIVO, PAPEIS,
)

cadernos_bp = Blueprint(
    "cadernos", __name__,
    url_prefix="/cadernos",
    template_folder="templates",
)

_rt = {"socketio": None, "publish_event": None, "AuditLog": None, "EventType": None}


def init_realtime(socketio, publish_event, AuditLog, EventType):
    """Mesmo contrato dos outros módulos. Nesta fase o módulo não emite eventos:
    quem está lendo uma página descobre a trava por consulta periódica, e o
    autosave não pode virar uma linha de audit_logs por gravação."""
    _rt.update(socketio=socketio, publish_event=publish_event,
               AuditLog=AuditLog, EventType=EventType)


# Arquivos de imagem que o editor aceita e que abrem no navegador.
EXT_IMAGEM = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
EXT_INLINE = EXT_IMAGEM | {".pdf"}
MIME_INLINE = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".webp": "image/webp", ".pdf": "application/pdf"}
LIXEIRA_DIAS = int(os.environ.get("CADERNOS_LIXEIRA_DIAS", "60"))


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def current_user():
    return User.query.filter_by(email=get_jwt_identity(), ativo=True).first()


def _erro(msg, status):
    return jsonify({"erro": msg}), status


def _papel(u, cad):
    membro = CadernoMembro.query.filter_by(caderno_id=cad.id, user_id=u.id).first()
    return core.papel_efetivo(
        user_id=u.id, user_role=u.role, tem_area=u.tem_area(cad.area),
        caderno_dono_id=cad.dono_id, acesso_area=cad.acesso_area,
        papel_membro=membro.papel if membro else None,
    )


def _carregar(cad, minimo="leitor", excluido_ok=False):
    """(user, papel, None) ou (None, None, resposta de erro).

    Caderno na lixeira só é alcançável por quem pode restaurá-lo (dono).
    """
    u = current_user()
    if not u:
        return None, None, _erro("Usuário inválido", 401)
    if not cad:
        return None, None, _erro("Não encontrado", 404)
    papel = _papel(u, cad)
    if papel is None:
        # 404 para não revelar que o caderno existe; a auditoria, que o
        # cliente não vê, registra a tentativa como o 403 que ela é.
        registrar_acesso_negado(f"sem acesso ao caderno {cad.nome}")
        return None, None, _erro("Não encontrado", 404)
    if cad.excluido_em and not (excluido_ok and core.pode(papel, "dono")):
        return None, None, _erro("Caderno na lixeira", 404)
    if not core.pode(papel, minimo):
        registrar_acesso_negado(f"papel {papel} no caderno {cad.nome} (exige {minimo})")
        return None, None, _erro("Sem permissão para esta ação", 403)
    return u, papel, None


def _caderno(uuid_):
    return Caderno.query.filter_by(uuid=uuid_).first()


def _no(uuid_):
    return CadernoNo.query.filter_by(uuid=uuid_).first()


def _pagina(uuid_):
    return CadernoPagina.query.filter_by(uuid=uuid_).first()


def _nomes(ids):
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {u.id: u.nome for u in User.query.filter(User.id.in_(ids)).all()}


def _no_visivel(no):
    """Seção/grupo visível = nem ele nem algum ancestral na lixeira."""
    atual = no
    while atual is not None:
        if atual.excluido_em:
            return False
        atual = db.session.get(CadernoNo, atual.parent_id) if atual.parent_id else None
    return True


def _paginas_da_secao(secao_id):
    return (CadernoPagina.query
            .filter_by(secao_id=secao_id, excluido_em=None)
            .order_by(CadernoPagina.ordem, CadernoPagina.id).all())


def _gravar_ordem(paginas_por_id, itens):
    """Persiste uma lista [(id, nivel)] já normalizada como a ordem da seção."""
    for ordem, (pid, nivel) in enumerate(itens):
        p = paginas_por_id[pid]
        p.ordem = ordem
        p.nivel = nivel


def _trava_info(p, agora=None):
    agora = agora or datetime.now()
    if p.editando_por and p.editando_ate and p.editando_ate > agora:
        return {"por_id": p.editando_por,
                "por": _nomes([p.editando_por]).get(p.editando_por, "—"),
                "ate": p.editando_ate.isoformat()}
    return None


def _pagina_resumo(p, agora=None):
    return {
        "uuid":          p.uuid,
        "secao_id":      p.secao_id,
        "tipo":          p.tipo,
        "titulo":        p.titulo,
        "nivel":         p.nivel,
        "ordem":         p.ordem,
        "recolhida":     bool(p.recolhida),
        "data_pagina":   p.data_pagina.isoformat() if p.data_pagina else None,
        "atualizado_em": p.atualizado_em.isoformat() if p.atualizado_em else None,
        "editando":      _trava_info(p, agora),
    }


def _pagina_completa(p, papel):
    cad = db.session.get(Caderno, p.caderno_id)
    secao = db.session.get(CadernoNo, p.secao_id)
    nomes = _nomes([p.criado_por, p.atualizado_por])
    d = _pagina_resumo(p)
    d.update({
        "html":            p.conteudo_html or "",
        "ficha":           core.ficha_de_json(p.ficha_json),
        "versao":          p.versao,
        "criado_por":      nomes.get(p.criado_por, ""),
        "criado_em":       p.criado_em.isoformat() if p.criado_em else None,
        "atualizado_por":  nomes.get(p.atualizado_por, ""),
        "origem_autores":  p.origem_autores or "",
        "caderno":         {"uuid": cad.uuid, "nome": cad.nome},
        "secao":           {"uuid": secao.uuid, "nome": secao.nome} if secao else None,
        "papel":           papel,
    })
    return d


def _garantir_versao(p, motivo, autor_id):
    """Guarda o estado ATUAL da página como versão, se ainda não houver uma com
    este número. Chamado ao abrir e fechar a sessão de edição e antes de
    excluir/restaurar — assim o estado de antes de qualquer mudança sempre volta."""
    existe = CadernoPaginaVersao.query.filter_by(pagina_id=p.id, versao=p.versao).first()
    if existe:
        return existe
    v = CadernoPaginaVersao(
        pagina_id=p.id, versao=p.versao, titulo=p.titulo,
        conteudo_html=p.conteudo_html or "", ficha_json=p.ficha_json or "",
        autor_id=p.atualizado_por or autor_id, motivo=motivo,
    )
    db.session.add(v)
    return v


def _parse_data_hora(valor):
    if not valor:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(valor)[:19], fmt)
        except ValueError:
            continue
    return False


# ══════════════════════════════════════════════════════════════════════════════
# PÁGINA
# ══════════════════════════════════════════════════════════════════════════════

@cadernos_bp.route("/")
@cadernos_bp.route("")
def index():
    # Casca: o token é validado no front e todo dado vem de /cadernos/api/*.
    from servidor import _static_version
    return render_template("cadernos/cadernos.html", asset_v=_static_version())


# ══════════════════════════════════════════════════════════════════════════════
# META
# ══════════════════════════════════════════════════════════════════════════════

@cadernos_bp.route("/api/meta", methods=["GET"])
@jwt_required()
def meta():
    """Quem sou eu, a área, os modelos e as pessoas da área (ficha e membros)."""
    from areas import get_area
    u = current_user()
    if not u:
        return _erro("Usuário inválido", 401)
    area = (request.args.get("area") or "pdr").strip().lower()
    a = get_area(area)
    if not a:
        return _erro("Área inválida", 400)
    if not u.tem_area(area):
        return negar_acesso(f"sem a área {area}", "Sem acesso a esta área")
    pessoas = [{"id": x.id, "nome": x.nome}
               for x in User.query.filter_by(ativo=True).order_by(User.nome).all()
               if x.tem_area(area)]
    return jsonify({
        "eu": {"id": u.id, "nome": u.nome, "role": u.role},
        "area": {"slug": a["slug"], "nome": a["nome"], "accent": a.get("accent", "")},
        "pode_criar": u.role in ("admin", "gestor", "tecnico"),
        "modelos": [{"id": k, "nome": v["nome"]} for k, v in core.MODELOS_CADERNO.items()],
        "acessos_area": ACESSOS_AREA,
        "resultados": core.RESULTADOS,
        "pessoas": pessoas,
        "limite_arquivo_mb": arquivos_store.MAX_BIN_MB,
        "trava_segundos": core.TRAVA_SEGUNDOS,
    })


# ══════════════════════════════════════════════════════════════════════════════
# CADERNOS
# ══════════════════════════════════════════════════════════════════════════════

@cadernos_bp.route("/api/cadernos", methods=["GET"])
@jwt_required()
def listar_cadernos():
    """Cadernos que a pessoa enxerga na área."""
    u = current_user()
    if not u:
        return _erro("Usuário inválido", 401)
    area = (request.args.get("area") or "pdr").strip().lower()
    saida = []
    for cad in (Caderno.query.filter_by(area=area, excluido_em=None)
                .order_by(Caderno.nome).all()):
        papel = _papel(u, cad)
        if papel is None:
            continue
        d = cad.to_dict(papel=papel)
        d["paginas"] = CadernoPagina.query.filter_by(caderno_id=cad.id, excluido_em=None).count()
        saida.append(d)
    return jsonify({"cadernos": saida})


@cadernos_bp.route("/api/cadernos", methods=["POST"])
@jwt_required()
def criar_caderno():
    """Cria um caderno. Quem cria vira dono; o modelo define as seções iniciais."""
    u = current_user()
    if not u:
        return _erro("Usuário inválido", 401)
    if u.role not in ("admin", "gestor", "tecnico"):
        return negar_acesso(f"perfil {u.role} não cria cadernos", "Seu perfil não cria cadernos")
    data = request.get_json(silent=True) or {}
    area = (data.get("area") or "pdr").strip().lower()
    if not u.tem_area(area):
        return negar_acesso(f"sem a área {area}", "Sem acesso a esta área")
    nome = (data.get("nome") or "").strip()[:200]
    if not nome:
        return _erro("Informe o nome do caderno", 400)
    acesso = (data.get("acesso_area") or "editor").strip()
    if acesso not in ACESSOS_AREA:
        return _erro("Acesso inválido", 400)
    modelo = (data.get("modelo") or "projeto_pdr").strip()
    if modelo not in core.MODELOS_CADERNO:
        return _erro("Modelo inválido", 400)

    cad = Caderno(uuid=str(_uuid.uuid4()), nome=nome, area=area, acesso_area=acesso,
                  cor=(data.get("cor") or "#a855f7")[:9], modelo=modelo,
                  descricao=(data.get("descricao") or "").strip(), dono_id=u.id)
    db.session.add(cad)
    db.session.flush()
    for ordem, (nome_secao, tipo_pag) in enumerate(core.MODELOS_CADERNO[modelo]["secoes"]):
        db.session.add(CadernoNo(uuid=str(_uuid.uuid4()), caderno_id=cad.id, tipo="secao",
                                 nome=nome_secao, ordem=ordem, tipo_pagina_padrao=tipo_pag))
    log_action(u.email, "CREATE", entidade=f"caderno:{nome}", campo="caderno",
               novo=modelo, ip=get_client_ip())
    return jsonify({"caderno": cad.to_dict(papel="dono")}), 201


@cadernos_bp.route("/api/cadernos/<uuid_>", methods=["GET"])
@jwt_required()
def detalhe_caderno(uuid_):
    """Caderno, papel da pessoa e (para o dono) os membros."""
    cad = _caderno(uuid_)
    u, papel, err = _carregar(cad, excluido_ok=True)
    if err:
        return err
    d = cad.to_dict(papel=papel)
    if core.pode(papel, "dono"):
        membros = CadernoMembro.query.filter_by(caderno_id=cad.id).all()
        nomes = _nomes([m.user_id for m in membros])
        d["membros"] = [{"user_id": m.user_id, "nome": nomes.get(m.user_id, ""),
                         "papel": m.papel} for m in membros]
    return jsonify({"caderno": d})


@cadernos_bp.route("/api/cadernos/<uuid_>", methods=["PATCH"])
@jwt_required()
def editar_caderno(uuid_):
    """Nome, cor, descrição, acesso da área, arquivado."""
    cad = _caderno(uuid_)
    u, papel, err = _carregar(cad, "dono")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if "nome" in data:
        nome = (data.get("nome") or "").strip()[:200]
        if not nome:
            return _erro("O nome não pode ficar vazio", 400)
        cad.nome = nome
    if "cor" in data:
        cad.cor = (data.get("cor") or "")[:9]
    if "descricao" in data:
        cad.descricao = (data.get("descricao") or "").strip()
    if "acesso_area" in data:
        if data["acesso_area"] not in ACESSOS_AREA:
            return _erro("Acesso inválido", 400)
        cad.acesso_area = data["acesso_area"]
    if "arquivado" in data:
        cad.arquivado = bool(data["arquivado"])
    cad.atualizado_em = datetime.now()
    log_action(u.email, "UPDATE", entidade=f"caderno:{cad.nome}", campo="caderno",
               ip=get_client_ip())
    return jsonify({"caderno": cad.to_dict(papel=papel)})


@cadernos_bp.route("/api/cadernos/<uuid_>", methods=["DELETE"])
@jwt_required()
def excluir_caderno(uuid_):
    """Manda o caderno para a lixeira (some para todos; o dono restaura)."""
    cad = _caderno(uuid_)
    u, papel, err = _carregar(cad, "dono")
    if err:
        return err
    cad.excluido_em = datetime.now()
    cad.excluido_por = u.id
    log_action(u.email, "DELETE", entidade=f"caderno:{cad.nome}", campo="caderno",
               ip=get_client_ip())
    return jsonify({"ok": True})


@cadernos_bp.route("/api/cadernos/<uuid_>/restaurar", methods=["POST"])
@jwt_required()
def restaurar_caderno(uuid_):
    """Tira o caderno da lixeira."""
    cad = _caderno(uuid_)
    u, papel, err = _carregar(cad, "dono", excluido_ok=True)
    if err:
        return err
    cad.excluido_em = None
    cad.excluido_por = None
    log_action(u.email, "RESTORE", entidade=f"caderno:{cad.nome}", campo="caderno",
               ip=get_client_ip())
    return jsonify({"caderno": cad.to_dict(papel=papel)})


@cadernos_bp.route("/api/cadernos/<uuid_>/membros", methods=["PUT"])
@jwt_required()
def definir_membros(uuid_):
    """Substitui a lista de membros explícitos: [{user_id, papel}]."""
    cad = _caderno(uuid_)
    u, papel, err = _carregar(cad, "dono")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    itens = data.get("membros") or []
    novos = {}
    for it in itens:
        try:
            uid = int(it.get("user_id"))
        except (TypeError, ValueError, AttributeError):
            return _erro("user_id inválido", 400)
        p = (it.get("papel") or "").strip()
        if p not in PAPEIS:
            return _erro("Papel inválido", 400)
        if not db.session.get(User, uid):
            return _erro("Usuário não encontrado", 400)
        novos[uid] = p
    CadernoMembro.query.filter_by(caderno_id=cad.id).delete()
    for uid, p in novos.items():
        db.session.add(CadernoMembro(caderno_id=cad.id, user_id=uid, papel=p))
    log_action(u.email, "UPDATE", entidade=f"caderno:{cad.nome}", campo="membros",
               novo=str(len(novos)), ip=get_client_ip())
    return jsonify({"ok": True, "membros": len(novos)})


@cadernos_bp.route("/api/cadernos/<uuid_>/arvore", methods=["GET"])
@jwt_required()
def arvore(uuid_):
    """Grupos, seções e páginas (sem conteúdo), com quem está editando."""
    cad = _caderno(uuid_)
    u, papel, err = _carregar(cad)
    if err:
        return err
    nos = (CadernoNo.query.filter_by(caderno_id=cad.id)
           .order_by(CadernoNo.ordem, CadernoNo.id).all())
    visiveis = [n for n in nos if _no_visivel(n)]
    ids_secoes = {n.id for n in visiveis if n.tipo == "secao"}
    agora = datetime.now()
    paginas = (CadernoPagina.query.filter_by(caderno_id=cad.id, excluido_em=None)
               .order_by(CadernoPagina.secao_id, CadernoPagina.ordem, CadernoPagina.id).all())
    return jsonify({
        "caderno": cad.to_dict(papel=papel),
        "nos": [n.to_dict() for n in visiveis],
        "paginas": [_pagina_resumo(p, agora) for p in paginas if p.secao_id in ids_secoes],
    })


# ══════════════════════════════════════════════════════════════════════════════
# GRUPOS E SEÇÕES
# ══════════════════════════════════════════════════════════════════════════════

@cadernos_bp.route("/api/cadernos/<uuid_>/nos", methods=["POST"])
@jwt_required()
def criar_no(uuid_):
    """Novo grupo de seções ou seção, no fim do nível escolhido."""
    cad = _caderno(uuid_)
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    tipo = (data.get("tipo") or "secao").strip()
    if tipo not in TIPOS_NO:
        return _erro("Tipo inválido", 400)
    nome = (data.get("nome") or "").strip()[:200]
    if not nome:
        return _erro("Informe o nome", 400)
    parent = None
    if data.get("parent_uuid"):
        parent = _no(data["parent_uuid"])
        if not parent or parent.caderno_id != cad.id or parent.tipo != "grupo":
            return _erro("Grupo inválido", 400)
    tipo_pag = (data.get("tipo_pagina_padrao") or "nota").strip()
    if tipo_pag not in TIPOS_PAGINA:
        tipo_pag = "nota"
    ultimo = (CadernoNo.query.filter_by(caderno_id=cad.id,
                                        parent_id=parent.id if parent else None)
              .order_by(CadernoNo.ordem.desc()).first())
    no = CadernoNo(uuid=str(_uuid.uuid4()), caderno_id=cad.id,
                   parent_id=parent.id if parent else None, tipo=tipo, nome=nome,
                   cor=(data.get("cor") or "")[:9], tipo_pagina_padrao=tipo_pag,
                   ordem=(ultimo.ordem + 1) if ultimo else 0)
    db.session.add(no)
    db.session.commit()
    return jsonify({"no": no.to_dict()}), 201


@cadernos_bp.route("/api/nos/<uuid_>", methods=["PATCH"])
@jwt_required()
def editar_no(uuid_):
    """Renomeia, muda a cor ou o tipo de página padrão."""
    no = _no(uuid_)
    cad = db.session.get(Caderno, no.caderno_id) if no else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if "nome" in data:
        nome = (data.get("nome") or "").strip()[:200]
        if not nome:
            return _erro("O nome não pode ficar vazio", 400)
        no.nome = nome
    if "cor" in data:
        no.cor = (data.get("cor") or "")[:9]
    if "tipo_pagina_padrao" in data and data["tipo_pagina_padrao"] in TIPOS_PAGINA:
        no.tipo_pagina_padrao = data["tipo_pagina_padrao"]
    db.session.commit()
    return jsonify({"no": no.to_dict()})


@cadernos_bp.route("/api/nos/<uuid_>", methods=["DELETE"])
@jwt_required()
def excluir_no(uuid_):
    """Manda a seção (ou o grupo, com tudo dentro) para a lixeira."""
    no = _no(uuid_)
    cad = db.session.get(Caderno, no.caderno_id) if no else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    no.excluido_em = datetime.now()
    no.excluido_por = u.id
    log_action(u.email, "DELETE", entidade=f"caderno:{cad.nome}", campo=f"{no.tipo}:{no.nome}",
               ip=get_client_ip())
    return jsonify({"ok": True})


@cadernos_bp.route("/api/nos/<uuid_>/restaurar", methods=["POST"])
@jwt_required()
def restaurar_no(uuid_):
    """Tira a seção/grupo da lixeira."""
    no = _no(uuid_)
    cad = db.session.get(Caderno, no.caderno_id) if no else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    no.excluido_em = None
    no.excluido_por = None
    log_action(u.email, "RESTORE", entidade=f"caderno:{cad.nome}", campo=f"{no.tipo}:{no.nome}",
               ip=get_client_ip())
    return jsonify({"no": no.to_dict()})


@cadernos_bp.route("/api/nos/<uuid_>/mover", methods=["POST"])
@jwt_required()
def mover_no(uuid_):
    """Reordena entre irmãos e/ou troca de grupo: {parent_uuid|null, apos_uuid|null}."""
    no = _no(uuid_)
    cad = db.session.get(Caderno, no.caderno_id) if no else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    parent = _no(data["parent_uuid"]) if data.get("parent_uuid") else None
    if parent is not None:
        if parent.caderno_id != cad.id or parent.tipo != "grupo":
            return _erro("Grupo inválido", 400)
        # Um grupo não pode entrar em si mesmo nem num descendente.
        atual = parent
        while atual is not None:
            if atual.id == no.id:
                return _erro("Não dá para mover um grupo para dentro dele mesmo", 400)
            atual = db.session.get(CadernoNo, atual.parent_id) if atual.parent_id else None
    irmaos = [n for n in (CadernoNo.query
                          .filter_by(caderno_id=cad.id, parent_id=parent.id if parent else None)
                          .order_by(CadernoNo.ordem, CadernoNo.id).all()) if n.id != no.id]
    pos = 0
    if data.get("apos_uuid"):
        ids = [n.uuid for n in irmaos]
        if data["apos_uuid"] not in ids:
            return _erro("Referência de posição inválida", 400)
        pos = ids.index(data["apos_uuid"]) + 1
    irmaos.insert(pos, no)
    no.parent_id = parent.id if parent else None
    for i, n in enumerate(irmaos):
        n.ordem = i
    db.session.commit()
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
# PÁGINAS
# ══════════════════════════════════════════════════════════════════════════════

@cadernos_bp.route("/api/secoes/<uuid_>/paginas", methods=["POST"])
@jwt_required()
def criar_pagina(uuid_):
    """Nova página: no fim, logo após outra (`apos_uuid`) ou como subpágina
    (`subpagina_de`). Registro de teste já nasce com a estrutura do modelo."""
    secao = _no(uuid_)
    if secao and secao.tipo != "secao":
        return _erro("Páginas só existem dentro de seções", 400)
    cad = db.session.get(Caderno, secao.caderno_id) if secao else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    tipo = (data.get("tipo") or secao.tipo_pagina_padrao or "nota").strip()
    if tipo not in TIPOS_PAGINA:
        return _erro("Tipo de página inválido", 400)

    paginas = _paginas_da_secao(secao.id)
    itens = [(p.id, p.nivel) for p in paginas]
    pos, nivel = len(itens), 1
    ref_uuid = data.get("subpagina_de") or data.get("apos_uuid")
    if ref_uuid:
        uuids = [p.uuid for p in paginas]
        if ref_uuid not in uuids:
            return _erro("Página de referência inválida", 400)
        i = uuids.index(ref_uuid)
        pos = core.fim_da_serie([n for _, n in itens], i)
        nivel = itens[i][1] + (1 if data.get("subpagina_de") else 0)

    ficha, conteudo = {}, ""
    titulo = (data.get("titulo") or "").strip()[:300]
    if tipo == "registro_teste":
        numeros = [core.ficha_de_json(p.ficha_json).get("numero")
                   for p in CadernoPagina.query.filter_by(caderno_id=cad.id).all()]
        numero = core.proximo_numero_teste(numeros)
        ficha = {"projeto": cad.nome[:80], "numero": numero, "resp_teste_id": u.id,
                 "resp_execucao_id": None, "inicio": datetime.now().strftime("%Y-%m-%d"),
                 "termino": "", "resultado": "em_andamento"}
        conteudo = core.HTML_REGISTRO_TESTE
        titulo = titulo or f"Teste {numero} – "
    titulo = titulo or "Sem título"

    p = CadernoPagina(uuid=str(_uuid.uuid4()), secao_id=secao.id, caderno_id=cad.id,
                      tipo=tipo, titulo=titulo, conteudo_html=conteudo,
                      ficha_json=json.dumps(ficha) if ficha else "",
                      criado_por=u.id, atualizado_por=u.id, nivel=nivel)
    p.texto_busca = core.montar_texto_busca(titulo, conteudo, ficha)
    db.session.add(p)
    db.session.flush()
    novos = core.inserir_serie(itens, pos, [(p.id, nivel)], nivel_base=nivel)
    _gravar_ordem({**{x.id: x for x in paginas}, p.id: p}, novos)
    db.session.commit()
    return jsonify({"pagina": _pagina_completa(p, papel)}), 201


@cadernos_bp.route("/api/paginas/<uuid_>", methods=["GET"])
@jwt_required()
def ler_pagina(uuid_):
    """Conteúdo completo da página (HTML saneado, ficha, versão, trava)."""
    p = _pagina(uuid_)
    cad = db.session.get(Caderno, p.caderno_id) if p else None
    u, papel, err = _carregar(cad)
    if err:
        return err
    secao = db.session.get(CadernoNo, p.secao_id)
    if p.excluido_em or not secao or not _no_visivel(secao):
        return _erro("Página na lixeira", 404)
    if request.args.get("leve") == "1":
        # Consulta periódica de quem está lendo: só versão e trava, sem o HTML.
        return jsonify({"pagina": dict(_pagina_resumo(p), versao=p.versao)})
    return jsonify({"pagina": _pagina_completa(p, papel)})


@cadernos_bp.route("/api/paginas/<uuid_>", methods=["PATCH"])
@jwt_required()
def editar_pagina_meta(uuid_):
    """Título, data da página e recolher/expandir — sem passar pela trava,
    exceto o título enquanto outra pessoa edita (ela sobrescreveria ao salvar)."""
    p = _pagina(uuid_)
    cad = db.session.get(Caderno, p.caderno_id) if p else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    agora = datetime.now()
    if "titulo" in data:
        if core.trava_de_outro(p.editando_por, p.editando_ate, u.id, agora):
            return _erro("A página está sendo editada por outra pessoa", 423)
        titulo = (data.get("titulo") or "").strip()[:300]
        if not titulo:
            return _erro("O título não pode ficar vazio", 400)
        p.titulo = titulo
        p.texto_busca = core.montar_texto_busca(p.titulo, p.conteudo_html,
                                                core.ficha_de_json(p.ficha_json))
    if "data_pagina" in data:
        dt = _parse_data_hora(data.get("data_pagina"))
        if dt is False:
            return _erro("Data inválida", 400)
        p.data_pagina = dt
    if "recolhida" in data:
        p.recolhida = bool(data["recolhida"])
    db.session.commit()
    return jsonify({"pagina": _pagina_resumo(p)})


def _guardar_imagem_factory(p, u):
    """Grava imagem colada como data URI e devolve o uuid do arquivo criado."""
    def guardar(mime, dados):
        if len(dados) > arquivos_store.MAX_BYTES:
            return None
        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
               "image/webp": ".webp"}.get(mime, ".png")
        sha, tamanho = arquivos_store.guardar(io.BytesIO(dados), f"imagem{ext}",
                                              permitidas=EXT_IMAGEM)
        novo = str(_uuid.uuid4())
        db.session.add(CadernoArquivo(
            uuid=novo, grupo=novo, caderno_id=p.caderno_id, escopo="pagina",
            escopo_id=p.id, nome_original=f"imagem{ext}", ext=ext, mime=mime,
            sha256=sha, tamanho=tamanho, embutido=True, enviado_por=u.id))
        return novo
    return guardar


@cadernos_bp.route("/api/paginas/<uuid_>", methods=["PUT"])
@jwt_required()
def salvar_pagina(uuid_):
    """Grava o conteúdo (autosave). Exige a trava e a versão em que o editor
    começou: sem isso, uma aba esquecida aberta poderia sobrescrever o trabalho
    de outra pessoa que pegou a trava depois."""
    p = _pagina(uuid_)
    cad = db.session.get(Caderno, p.caderno_id) if p else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    agora = datetime.now()
    if p.editando_por != u.id or not p.editando_ate or p.editando_ate <= agora:
        dono = core.trava_de_outro(p.editando_por, p.editando_ate, u.id, agora)
        if dono:
            return _erro(f"A página está sendo editada por {_nomes([dono]).get(dono, 'outra pessoa')}", 423)
        return _erro("Sua sessão de edição expirou. Clique em Editar de novo.", 409)
    data = request.get_json(silent=True) or {}
    try:
        base = int(data.get("versao_base"))
    except (TypeError, ValueError):
        return _erro("versao_base obrigatória", 400)
    if base != p.versao:
        return _erro("A página mudou desde que você abriu. Recarregue.", 409)

    if "titulo" in data:
        titulo = (data.get("titulo") or "").strip()[:300]
        if titulo:
            p.titulo = titulo
    if "html" in data:
        limpo, _ = core.sanear_html(data.get("html") or "",
                                    guardar_imagem=_guardar_imagem_factory(p, u))
        p.conteudo_html = limpo
    if "ficha" in data and p.tipo == "registro_teste":
        ids = {x.id for x in User.query.filter_by(ativo=True).all()}
        ficha, erro = core.validar_ficha(data.get("ficha"), ids)
        if erro:
            return _erro(erro, 400)
        p.ficha_json = json.dumps(ficha)
    if "data_pagina" in data:
        dt = _parse_data_hora(data.get("data_pagina"))
        if dt is False:
            return _erro("Data inválida", 400)
        p.data_pagina = dt

    p.texto_busca = core.montar_texto_busca(p.titulo, p.conteudo_html,
                                            core.ficha_de_json(p.ficha_json))
    p.versao += 1
    p.atualizado_por = u.id
    p.atualizado_em = agora
    p.editando_ate = core.nova_validade(agora)       # gravar também renova a trava
    db.session.commit()
    return jsonify({"versao": p.versao, "atualizado_em": p.atualizado_em.isoformat(),
                    "html": p.conteudo_html})


@cadernos_bp.route("/api/paginas/<uuid_>", methods=["DELETE"])
@jwt_required()
def excluir_pagina(uuid_):
    """Manda a página para a lixeira (as subpáginas sobem um nível)."""
    p = _pagina(uuid_)
    cad = db.session.get(Caderno, p.caderno_id) if p else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    agora = datetime.now()
    dono = core.trava_de_outro(p.editando_por, p.editando_ate, u.id, agora)
    if dono:
        return _erro(f"A página está sendo editada por {_nomes([dono]).get(dono, 'outra pessoa')}", 423)
    _garantir_versao(p, "antes_excluir", u.id)
    p.excluido_em = agora
    p.excluido_por = u.id
    p.editando_por = None
    p.editando_ate = None
    restantes = _paginas_da_secao(p.secao_id)
    restantes = [x for x in restantes if x.id != p.id]
    itens = list(zip([x.id for x in restantes],
                     core.normalizar_niveis([x.nivel for x in restantes])))
    _gravar_ordem({x.id: x for x in restantes}, itens)
    log_action(u.email, "DELETE", entidade=f"caderno:{cad.nome}", campo="pagina",
               antigo=p.titulo, ip=get_client_ip())
    return jsonify({"ok": True})


@cadernos_bp.route("/api/paginas/<uuid_>/restaurar", methods=["POST"])
@jwt_required()
def restaurar_pagina(uuid_):
    """Tira a página da lixeira (volta para o fim da seção; a seção também volta)."""
    p = _pagina(uuid_)
    cad = db.session.get(Caderno, p.caderno_id) if p else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    secao = db.session.get(CadernoNo, p.secao_id)
    atual = secao
    while atual is not None:           # a seção (e os grupos acima) voltam junto
        atual.excluido_em = None
        atual = db.session.get(CadernoNo, atual.parent_id) if atual.parent_id else None
    irmas = _paginas_da_secao(p.secao_id)
    p.excluido_em = None
    p.excluido_por = None
    p.ordem = (max([x.ordem for x in irmas]) + 1) if irmas else 0
    p.nivel = 1
    log_action(u.email, "RESTORE", entidade=f"caderno:{cad.nome}", campo="pagina",
               novo=p.titulo, ip=get_client_ip())
    return jsonify({"pagina": _pagina_resumo(p)})


@cadernos_bp.route("/api/paginas/<uuid_>/mover", methods=["POST"])
@jwt_required()
def mover_pagina(uuid_):
    """Move a página e suas subpáginas: {secao_uuid, apos_uuid|null, nivel|null}.

    Nesta fase só dentro do mesmo caderno — mover entre cadernos mexe em
    permissão e nos arquivos da página, e fica para quando houver demanda.
    """
    p = _pagina(uuid_)
    cad = db.session.get(Caderno, p.caderno_id) if p else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    destino = _no(data.get("secao_uuid")) if data.get("secao_uuid") else \
        db.session.get(CadernoNo, p.secao_id)
    if not destino or destino.caderno_id != cad.id or destino.tipo != "secao":
        return _erro("Seção de destino inválida", 400)

    origem = _paginas_da_secao(p.secao_id)
    por_id = {x.id: x for x in origem}
    itens = [(x.id, x.nivel) for x in origem]
    i = [x.id for x in origem].index(p.id)
    serie, resto = core.extrair_serie(itens, i)

    if destino.id == p.secao_id:
        alvo_itens, alvo_por_id = resto, dict(por_id)
    else:
        alvo = _paginas_da_secao(destino.id)
        alvo_itens = [(x.id, x.nivel) for x in alvo]
        alvo_por_id = {x.id: x for x in alvo}
        alvo_por_id.update({pid: por_id[pid] for pid, _ in serie})
        restantes = list(zip([pid for pid, _ in resto],
                             core.normalizar_niveis([n for _, n in resto])))
        _gravar_ordem(por_id, restantes)

    pos = 0
    if data.get("apos_uuid"):
        uuid_por_id = {x.id: x.uuid for x in alvo_por_id.values()}
        ids = [pid for pid, _ in alvo_itens]
        alvo_uuid = [uuid_por_id[pid] for pid in ids]
        if data["apos_uuid"] not in alvo_uuid:
            return _erro("Referência de posição inválida", 400)
        k = alvo_uuid.index(data["apos_uuid"])
        pos = core.fim_da_serie([n for _, n in alvo_itens], k)
    nivel = data.get("nivel")
    novos = core.inserir_serie(alvo_itens, pos, serie,
                               nivel_base=int(nivel) if nivel else None)
    for pid, _ in serie:
        alvo_por_id[pid].secao_id = destino.id
    _gravar_ordem(alvo_por_id, novos)
    db.session.commit()
    return jsonify({"ok": True})


@cadernos_bp.route("/api/paginas/<uuid_>/nivel", methods=["POST"])
@jwt_required()
def mudar_nivel(uuid_):
    """Promove (delta -1) ou rebaixa (+1) a página junto com suas subpáginas."""
    p = _pagina(uuid_)
    cad = db.session.get(Caderno, p.caderno_id) if p else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    try:
        delta = int((request.get_json(silent=True) or {}).get("delta"))
    except (TypeError, ValueError):
        return _erro("delta deve ser -1 ou 1", 400)
    if delta not in (-1, 1):
        return _erro("delta deve ser -1 ou 1", 400)
    paginas = _paginas_da_secao(p.secao_id)
    itens = [(x.id, x.nivel) for x in paginas]
    i = [x.id for x in paginas].index(p.id)
    _gravar_ordem({x.id: x for x in paginas}, core.alterar_nivel(itens, i, delta))
    db.session.commit()
    return jsonify({"nivel": p.nivel})


# ══════════════════════════════════════════════════════════════════════════════
# TRAVA DE EDIÇÃO
# ══════════════════════════════════════════════════════════════════════════════

@cadernos_bp.route("/api/paginas/<uuid_>/edicao", methods=["POST"])
@jwt_required()
def iniciar_edicao(uuid_):
    """Pega a trava. Devolve a página fresca: o editor tem de começar da versão
    que está no banco, não da que estava na tela."""
    p = _pagina(uuid_)
    cad = db.session.get(Caderno, p.caderno_id) if p else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    if p.excluido_em:
        return _erro("Página na lixeira", 404)
    agora = datetime.now()
    dono = core.trava_de_outro(p.editando_por, p.editando_ate, u.id, agora)
    if dono:
        return jsonify({"erro": "Página em edição", "editando": _trava_info(p, agora)}), 423
    if p.editando_por != u.id or not p.editando_ate or p.editando_ate <= agora:
        p.sessao_versao = p.versao
        _garantir_versao(p, "sessao", u.id)
    p.editando_por = u.id
    p.editando_ate = core.nova_validade(agora)
    db.session.commit()
    return jsonify({"pagina": _pagina_completa(p, papel)})


@cadernos_bp.route("/api/paginas/<uuid_>/edicao", methods=["PUT"])
@jwt_required()
def renovar_edicao(uuid_):
    """Renova a trava (o front chama a cada ~30 s enquanto o editor está aberto)."""
    p = _pagina(uuid_)
    cad = db.session.get(Caderno, p.caderno_id) if p else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    agora = datetime.now()
    if p.editando_por != u.id:
        dono = core.trava_de_outro(p.editando_por, p.editando_ate, u.id, agora)
        if dono:
            return jsonify({"erro": "Página em edição", "editando": _trava_info(p, agora)}), 423
        return _erro("Sua sessão de edição expirou", 409)
    p.editando_ate = core.nova_validade(agora)
    db.session.commit()
    return jsonify({"ate": p.editando_ate.isoformat()})


@cadernos_bp.route("/api/paginas/<uuid_>/edicao", methods=["DELETE"])
@jwt_required()
def encerrar_edicao(uuid_):
    """Solta a trava e fecha a sessão: o estado final vira uma versão."""
    p = _pagina(uuid_)
    cad = db.session.get(Caderno, p.caderno_id) if p else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    if p.editando_por == u.id:
        mudou = p.sessao_versao is not None and p.versao != p.sessao_versao
        if mudou:
            _garantir_versao(p, "sessao", u.id)
            log_action(u.email, "UPDATE", entidade=f"caderno:{cad.nome}", campo="pagina",
                       novo=f"{p.titulo} (v{p.versao})", ip=get_client_ip())
        p.editando_por = None
        p.editando_ate = None
        p.sessao_versao = None
    db.session.commit()
    return jsonify({"ok": True, "versao": p.versao})


@cadernos_bp.route("/api/paginas/<uuid_>/edicao/tomar", methods=["POST"])
@jwt_required()
def tomar_edicao(uuid_):
    """O dono do caderno toma a edição. O que já foi gravado pela outra pessoa
    vira versão antes da troca; o que ela não chegou a gravar (menos de 2 s de
    digitação, pelo autosave) é o único risco, e é aceito."""
    p = _pagina(uuid_)
    cad = db.session.get(Caderno, p.caderno_id) if p else None
    u, papel, err = _carregar(cad, "dono")
    if err:
        return err
    anterior = p.editando_por
    _garantir_versao(p, "sessao", u.id)
    agora = datetime.now()
    p.editando_por = u.id
    p.editando_ate = core.nova_validade(agora)
    p.sessao_versao = p.versao
    log_action(u.email, "UPDATE", entidade=f"caderno:{cad.nome}", campo="trava_tomada",
               antigo=_nomes([anterior]).get(anterior, ""), novo=p.titulo, ip=get_client_ip())
    return jsonify({"pagina": _pagina_completa(p, papel)})


# ══════════════════════════════════════════════════════════════════════════════
# VERSÕES
# ══════════════════════════════════════════════════════════════════════════════

@cadernos_bp.route("/api/paginas/<uuid_>/versoes", methods=["GET"])
@jwt_required()
def listar_versoes(uuid_):
    """Histórico da página, da mais nova para a mais antiga."""
    p = _pagina(uuid_)
    cad = db.session.get(Caderno, p.caderno_id) if p else None
    u, papel, err = _carregar(cad)
    if err:
        return err
    vs = (CadernoPaginaVersao.query.filter_by(pagina_id=p.id)
          .order_by(CadernoPaginaVersao.versao.desc()).all())
    nomes = _nomes([v.autor_id for v in vs])
    return jsonify({"atual": p.versao, "versoes": [{
        "versao": v.versao, "titulo": v.titulo, "motivo": v.motivo,
        "autor": nomes.get(v.autor_id, ""),
        "criado_em": v.criado_em.isoformat() if v.criado_em else None,
        "tamanho": len(v.conteudo_html or ""),
    } for v in vs]})


@cadernos_bp.route("/api/paginas/<uuid_>/versoes/<int:numero>", methods=["GET"])
@jwt_required()
def ler_versao(uuid_, numero):
    """Conteúdo de uma versão."""
    p = _pagina(uuid_)
    cad = db.session.get(Caderno, p.caderno_id) if p else None
    u, papel, err = _carregar(cad)
    if err:
        return err
    v = CadernoPaginaVersao.query.filter_by(pagina_id=p.id, versao=numero).first()
    if not v:
        return _erro("Versão não encontrada", 404)
    return jsonify({"versao": {"versao": v.versao, "titulo": v.titulo,
                               "html": v.conteudo_html or "",
                               "ficha": core.ficha_de_json(v.ficha_json),
                               "motivo": v.motivo}})


@cadernos_bp.route("/api/paginas/<uuid_>/versoes/<int:numero>/restaurar", methods=["POST"])
@jwt_required()
def restaurar_versao(uuid_, numero):
    """Volta a página para uma versão. O estado atual vira versão antes — restaurar
    nunca perde nada, nem o que se está desfazendo."""
    p = _pagina(uuid_)
    cad = db.session.get(Caderno, p.caderno_id) if p else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    agora = datetime.now()
    dono = core.trava_de_outro(p.editando_por, p.editando_ate, u.id, agora)
    if dono:
        return _erro(f"A página está sendo editada por {_nomes([dono]).get(dono, 'outra pessoa')}", 423)
    v = CadernoPaginaVersao.query.filter_by(pagina_id=p.id, versao=numero).first()
    if not v:
        return _erro("Versão não encontrada", 404)
    _garantir_versao(p, "antes_restaurar", u.id)
    p.titulo, p.conteudo_html, p.ficha_json = v.titulo, v.conteudo_html, v.ficha_json
    p.texto_busca = core.montar_texto_busca(p.titulo, p.conteudo_html,
                                            core.ficha_de_json(p.ficha_json))
    p.versao += 1
    p.atualizado_por = u.id
    p.atualizado_em = agora
    _garantir_versao(p, "sessao", u.id)
    log_action(u.email, "RESTORE", entidade=f"caderno:{cad.nome}", campo="pagina",
               antigo=f"v{numero}", novo=f"v{p.versao}", ip=get_client_ip())
    return jsonify({"pagina": _pagina_completa(p, papel)})


# ══════════════════════════════════════════════════════════════════════════════
# ARQUIVOS
# ══════════════════════════════════════════════════════════════════════════════

def _escopo_alvo(cad, escopo, ref_uuid):
    """id do alvo do escopo (caderno/seção/página), validando que é do caderno."""
    if escopo == "caderno":
        return cad.id
    if escopo == "secao":
        no = _no(ref_uuid)
        return no.id if no and no.caderno_id == cad.id and no.tipo == "secao" else None
    if escopo == "pagina":
        p = _pagina(ref_uuid)
        return p.id if p and p.caderno_id == cad.id else None
    return None


@cadernos_bp.route("/api/paginas/<uuid_>/imagens", methods=["POST"])
@jwt_required()
def enviar_imagem(uuid_):
    """Imagem colada ou enviada no editor. Vira arquivo embutido da página."""
    p = _pagina(uuid_)
    cad = db.session.get(Caderno, p.caderno_id) if p else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    request.max_content_length = arquivos_store.MAX_BYTES + 1024 * 1024
    f = request.files.get("upload") or request.files.get("arquivo")
    if not f or not (f.filename or "").strip():
        return _erro("Nenhuma imagem enviada", 400)
    nome = os.path.basename(f.filename.strip()) or "imagem.png"
    ext = arquivos_store.ext_de(nome)
    if ext not in EXT_IMAGEM:
        return _erro("Formato de imagem não aceito (png, jpg, gif, webp)", 415)
    try:
        sha, tamanho = arquivos_store.guardar(f.stream, nome, permitidas=EXT_IMAGEM)
    except arquivos_store.ArquivoGrandeDemais:
        return _erro(f"Imagem maior que {arquivos_store.MAX_MB} MB", 413)
    novo = str(_uuid.uuid4())
    db.session.add(CadernoArquivo(
        uuid=novo, grupo=novo, caderno_id=cad.id, escopo="pagina", escopo_id=p.id,
        nome_original=nome, ext=ext, mime=MIME_INLINE.get(ext, ""), sha256=sha,
        tamanho=tamanho, embutido=True, enviado_por=u.id))
    db.session.commit()
    return jsonify({"uuid": novo, "url": f"/cadernos/api/arquivos/{novo}/conteudo"}), 201


@cadernos_bp.route("/api/arquivos", methods=["GET"])
@jwt_required()
def listar_arquivos():
    """Arquivos (versão atual) de um escopo: ?caderno=&escopo=&ref=."""
    cad = _caderno(request.args.get("caderno") or "")
    u, papel, err = _carregar(cad)
    if err:
        return err
    escopo = (request.args.get("escopo") or "pagina").strip()
    if escopo not in ESCOPOS_ARQUIVO:
        return _erro("Escopo inválido", 400)
    alvo = _escopo_alvo(cad, escopo, request.args.get("ref") or "")
    if alvo is None:
        return _erro("Referência inválida", 400)
    itens = (CadernoArquivo.query
             .filter_by(caderno_id=cad.id, escopo=escopo, escopo_id=alvo,
                        ativo=True, embutido=False, excluido_em=None)
             .order_by(CadernoArquivo.pasta, CadernoArquivo.nome_original).all())
    nomes = _nomes([a.enviado_por for a in itens])
    # Arquivo citado no texto da página (anexo dentro da nota). O link aponta
    # para uma versão; a marca vale para a família toda.
    grupos_no_texto = set()
    if escopo == "pagina":
        refs = core.anexos_no_html(db.session.get(CadernoPagina, alvo).conteudo_html)
        if refs:
            grupos_no_texto = {g for (g,) in db.session.query(CadernoArquivo.grupo)
                               .filter(CadernoArquivo.uuid.in_(refs)).all()}
    saida = []
    for a in itens:
        d = a.to_dict()
        d["enviado_por_nome"] = nomes.get(a.enviado_por, "")
        d["no_texto"] = a.grupo in grupos_no_texto
        d["versoes"] = CadernoArquivo.query.filter_by(grupo=a.grupo, excluido_em=None).count()
        saida.append(d)
    return jsonify({"arquivos": saida})


def _receber_arquivo(f):
    """(sha, tamanho, nome, erro). QUALQUER extensão: este é o espaço onde o PDR
    guarda programas e arquivos de equipamento (.tlpd, .eds...). A segurança não
    vem da allowlist e sim de como o arquivo é servido (ver `conteudo_arquivo`)."""
    if not f or not (f.filename or "").strip():
        return None, None, None, _erro("Nenhum arquivo enviado", 400)
    nome = os.path.basename(f.filename.strip().replace("\\", "/"))[:300] or "arquivo"
    try:
        sha, tamanho = arquivos_store.guardar(f.stream, nome,
                                              permitidas=arquivos_store.QUALQUER,
                                              limite=arquivos_store.MAX_BIN_BYTES)
    except arquivos_store.ArquivoGrandeDemais:
        return None, None, None, _erro(f"Arquivo maior que {arquivos_store.MAX_BIN_MB} MB", 413)
    except OSError as e:
        return None, None, None, _erro(f"Erro ao gravar o arquivo: {e}", 500)
    return sha, tamanho, nome, None


@cadernos_bp.route("/api/arquivos", methods=["POST"])
@jwt_required()
def enviar_arquivo():
    """Envia um arquivo de qualquer extensão para o caderno, uma seção ou página."""
    request.max_content_length = arquivos_store.MAX_BIN_BYTES + 1024 * 1024
    cad = _caderno(request.form.get("caderno") or "")
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    escopo = (request.form.get("escopo") or "pagina").strip()
    if escopo not in ESCOPOS_ARQUIVO:
        return _erro("Escopo inválido", 400)
    alvo = _escopo_alvo(cad, escopo, request.form.get("ref") or "")
    if alvo is None:
        return _erro("Referência inválida", 400)
    sha, tamanho, nome, erro = _receber_arquivo(request.files.get("arquivo"))
    if erro:
        return erro
    novo = str(_uuid.uuid4())
    a = CadernoArquivo(
        uuid=novo, grupo=novo, caderno_id=cad.id, escopo=escopo, escopo_id=alvo,
        pasta=(request.form.get("pasta") or "").strip()[:120],
        descricao=(request.form.get("descricao") or "").strip(),
        nome_original=nome, ext=arquivos_store.ext_de(nome),
        mime=MIME_INLINE.get(arquivos_store.ext_de(nome), "application/octet-stream"),
        sha256=sha, tamanho=tamanho, enviado_por=u.id,
        # Programa de 300 MB no caderno não deveria entrar em todo zip por acidente.
        incluir_exportacao=(escopo == "pagina"),
    )
    db.session.add(a)
    log_action(u.email, "UPLOAD", entidade=f"caderno:{cad.nome}", campo=f"arquivo:{escopo}",
               novo=nome, ip=get_client_ip())
    return jsonify({"arquivo": a.to_dict()}), 201


@cadernos_bp.route("/api/arquivos/<uuid_>/versoes", methods=["GET"])
@jwt_required()
def versoes_arquivo(uuid_):
    """Todas as versões do arquivo (a mais nova primeiro)."""
    a = CadernoArquivo.query.filter_by(uuid=uuid_).first()
    cad = db.session.get(Caderno, a.caderno_id) if a else None
    u, papel, err = _carregar(cad)
    if err:
        return err
    vs = (CadernoArquivo.query.filter_by(grupo=a.grupo, excluido_em=None)
          .order_by(CadernoArquivo.versao.desc()).all())
    nomes = _nomes([v.enviado_por for v in vs])
    return jsonify({"versoes": [dict(v.to_dict(), enviado_por_nome=nomes.get(v.enviado_por, ""))
                                for v in vs]})


@cadernos_bp.route("/api/arquivos/<uuid_>/versao", methods=["POST"])
@jwt_required()
def nova_versao_arquivo(uuid_):
    """Substitui o arquivo por uma versão nova; a anterior continua baixável."""
    request.max_content_length = arquivos_store.MAX_BIN_BYTES + 1024 * 1024
    atual = CadernoArquivo.query.filter_by(uuid=uuid_).first()
    cad = db.session.get(Caderno, atual.caderno_id) if atual else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    if atual.excluido_em:
        return _erro("Arquivo na lixeira", 404)
    sha, tamanho, nome, erro = _receber_arquivo(request.files.get("arquivo"))
    if erro:
        return erro
    ultimo = (CadernoArquivo.query.filter_by(grupo=atual.grupo)
              .order_by(CadernoArquivo.versao.desc()).first())
    CadernoArquivo.query.filter_by(grupo=atual.grupo, ativo=True).update({"ativo": False})
    novo = CadernoArquivo(
        uuid=str(_uuid.uuid4()), grupo=atual.grupo, caderno_id=cad.id,
        escopo=atual.escopo, escopo_id=atual.escopo_id, pasta=atual.pasta,
        descricao=atual.descricao, nome_original=nome, ext=arquivos_store.ext_de(nome),
        mime=MIME_INLINE.get(arquivos_store.ext_de(nome), "application/octet-stream"),
        sha256=sha, tamanho=tamanho, versao=ultimo.versao + 1, enviado_por=u.id,
        incluir_exportacao=atual.incluir_exportacao,
    )
    db.session.add(novo)
    log_action(u.email, "UPLOAD", entidade=f"caderno:{cad.nome}", campo="arquivo:versao",
               antigo=atual.nome_original, novo=f"{nome} (v{novo.versao})", ip=get_client_ip())
    return jsonify({"arquivo": novo.to_dict()}), 201


@cadernos_bp.route("/api/arquivos/<uuid_>", methods=["PATCH"])
@jwt_required()
def editar_arquivo(uuid_):
    """Pasta, descrição e se entra na exportação (vale para a família toda)."""
    a = CadernoArquivo.query.filter_by(uuid=uuid_).first()
    cad = db.session.get(Caderno, a.caderno_id) if a else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    campos = {}
    if "pasta" in data:
        campos["pasta"] = (data.get("pasta") or "").strip()[:120]
    if "descricao" in data:
        campos["descricao"] = (data.get("descricao") or "").strip()
    if "incluir_exportacao" in data:
        campos["incluir_exportacao"] = bool(data["incluir_exportacao"])
    if campos:
        CadernoArquivo.query.filter_by(grupo=a.grupo).update(campos)
    db.session.commit()
    return jsonify({"arquivo": db.session.get(CadernoArquivo, a.id).to_dict()})


@cadernos_bp.route("/api/arquivos/<uuid_>", methods=["DELETE"])
@jwt_required()
def excluir_arquivo(uuid_):
    """Manda o arquivo (todas as versões) para a lixeira. O blob só sai na purga."""
    a = CadernoArquivo.query.filter_by(uuid=uuid_).first()
    cad = db.session.get(Caderno, a.caderno_id) if a else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    agora = datetime.now()
    CadernoArquivo.query.filter_by(grupo=a.grupo, excluido_em=None).update(
        {"excluido_em": agora, "excluido_por": u.id})
    log_action(u.email, "DELETE", entidade=f"caderno:{cad.nome}", campo="arquivo",
               antigo=a.nome_original, ip=get_client_ip())
    return jsonify({"ok": True})


@cadernos_bp.route("/api/arquivos/<uuid_>/conteudo", methods=["GET"])
@jwt_required()
def conteudo_arquivo(uuid_):
    """Serve o arquivo. Imagem e PDF podem abrir no navegador; todo o resto desce
    como download com mime genérico — é isso, e não uma allowlist de extensão,
    que impede um .html ou .svg enviado de executar algo no navegador de quem abre.
    (`X-Content-Type-Options: nosniff` já é global.) Aceita o token também em
    `?token=`, porque `<img>` não manda cabeçalho."""
    a = CadernoArquivo.query.filter_by(uuid=uuid_).first()
    cad = db.session.get(Caderno, a.caderno_id) if a else None
    u, papel, err = _carregar(cad)
    if err:
        return err
    if request.args.get("atual") == "1" and not a.ativo:
        # Link no texto da página: baixa a versão vigente do arquivo, não a que
        # existia quando o link foi posto.
        vigente = CadernoArquivo.query.filter_by(grupo=a.grupo, ativo=True, excluido_em=None).first()
        if vigente:
            a = vigente
    if a.excluido_em:
        return _erro("Arquivo na lixeira", 404)
    real = arquivos_store.caminho_de(a.sha256)
    if not os.path.isfile(real):
        return _erro("Arquivo não está mais disponível no servidor", 404)
    ext = (a.ext or "").lower()
    inline = ext in EXT_INLINE and request.args.get("download") != "1"
    resp = send_file(
        real,
        as_attachment=not inline,
        download_name=a.nome_original or f"arquivo{ext}",
        mimetype=MIME_INLINE.get(ext) if inline else "application/octet-stream",
        conditional=True,
        max_age=3600 if a.embutido else 0,
    )
    return resp


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTAÇÃO (zip para a liderança)
# ══════════════════════════════════════════════════════════════════════════════
# Quem lê o caderno pode exportar: o pacote não revela nada que a pessoa já não
# possa abrir e baixar, e toda exportação fica registrada (caderno_exportacoes +
# audit log). Se o PDR quiser restringir ao gestor, é trocar o mínimo abaixo.
PAPEL_EXPORTAR = "leitor"


def _paginas_pedidas(cad, data):
    uuids = data.get("paginas")
    if not isinstance(uuids, list) or not uuids:
        return None
    return exportacao.paginas_em_ordem(cad, [str(x) for x in uuids])


@cadernos_bp.route("/api/cadernos/<uuid_>/exportacao/previa", methods=["POST"])
@jwt_required()
def previa_exportacao(uuid_):
    """Páginas escolhidas + todos os arquivos que podem ir no pacote, com o que
    vem marcado por padrão. Nada é gerado aqui."""
    cad = _caderno(uuid_)
    u, papel, err = _carregar(cad, PAPEL_EXPORTAR)
    if err:
        return err
    paginas = _paginas_pedidas(cad, request.get_json(silent=True) or {})
    if not paginas:
        return _erro("Escolha ao menos uma página", 400)
    return jsonify(exportacao.previa(cad, paginas))


@cadernos_bp.route("/api/cadernos/<uuid_>/exportacoes", methods=["POST"])
@jwt_required()
def criar_exportacao(uuid_):
    """Gera o zip (relatório .docx + imagens + arquivos marcados + LEIA-ME)."""
    cad = _caderno(uuid_)
    u, papel, err = _carregar(cad, PAPEL_EXPORTAR)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    paginas = _paginas_pedidas(cad, data)
    if not paginas:
        return _erro("Escolha ao menos uma página", 400)
    arquivos = data.get("arquivos") or []
    if not isinstance(arquivos, list):
        return _erro("Lista de arquivos inválida", 400)
    if len(tarefas.em_andamento("exportacao")) >= 2:
        return _erro("Já há duas exportações sendo geradas. Tente de novo em instantes.", 429)
    t = tarefas.iniciar("exportacao", u.id, exportacao.executar, cad.id, [p.uuid for p in paginas],
                        [str(x) for x in arquivos], u.id, get_client_ip())
    return jsonify({"tarefa": t.to_dict()}), 202


@cadernos_bp.route("/api/tarefas/<id_>", methods=["GET"])
@jwt_required()
def ver_tarefa(id_):
    """Progresso de uma exportação/importação (só quem a iniciou vê)."""
    u = current_user()
    t = tarefas.obter(id_, u.id) if u else None
    if not t:
        return _erro("Tarefa não encontrada (o servidor pode ter reiniciado; refaça)", 404)
    return jsonify({"tarefa": t.to_dict()})


@cadernos_bp.route("/api/cadernos/<uuid_>/exportacoes", methods=["GET"])
@jwt_required()
def listar_exportacoes(uuid_):
    """Histórico: o que já foi enviado deste caderno, por quem e quando."""
    cad = _caderno(uuid_)
    u, papel, err = _carregar(cad, PAPEL_EXPORTAR)
    if err:
        return err
    itens = (CadernoExportacao.query.filter_by(caderno_id=cad.id)
             .order_by(CadernoExportacao.criado_em.desc()).limit(100).all())
    nomes = _nomes([e.criado_por for e in itens])
    saida = []
    for e in itens:
        d = e.to_dict()
        d["criado_por_nome"] = nomes.get(e.criado_por, "")
        d["disponivel"] = os.path.isfile(exportacao.caminho_zip(e.uuid))
        saida.append(d)
    return jsonify({"exportacoes": saida})


@cadernos_bp.route("/api/exportacoes/<uuid_>/zip", methods=["GET"])
@jwt_required()
def baixar_exportacao(uuid_):
    """Baixa o zip gerado (fica disponível por um dia). Aceita `?token=`."""
    exp = CadernoExportacao.query.filter_by(uuid=uuid_).first()
    cad = db.session.get(Caderno, exp.caderno_id) if exp else None
    u, papel, err = _carregar(cad, PAPEL_EXPORTAR)
    if err:
        return err
    caminho = exportacao.caminho_zip(exp.uuid)
    if not os.path.isfile(caminho):
        return _erro(f"O pacote expirou (fica {exportacao.VALIDADE_HORAS} h). Gere de novo.", 410)
    return send_file(caminho, as_attachment=True, download_name=exp.nome_zip,
                     mimetype="application/zip", max_age=0)


# ══════════════════════════════════════════════════════════════════════════════
# IMPORTAÇÃO DO ONENOTE (pela tela)
# ══════════════════════════════════════════════════════════════════════════════
# 1. a pessoa baixa o assistente (.cmd) e roda na máquina dela, onde está o
#    OneNote: sai um .zip; 2. envia o .zip aqui e vê o resumo; 3. confirma, e a
#    gravação roda como tarefa. Quem importa é quem pode criar caderno na área.

def _pode_importar(u, area):
    return u is not None and u.role in ("admin", "gestor", "tecnico") and u.tem_area(area)


def _negar_importacao(u, area):
    if u is not None and u.role in ("admin", "gestor", "tecnico"):
        motivo = f"sem a área {area}"
    else:
        motivo = f"perfil {u.role if u else '—'} não importa cadernos"
    return negar_acesso(motivo, "Seu perfil não importa cadernos nesta área")


@cadernos_bp.route("/api/onenote/assistente", methods=["GET"])
@jwt_required()
def baixar_assistente():
    """O .cmd que extrai um caderno do OneNote na máquina de quem o tem aberto."""
    from . import onenote_assistente
    u = current_user()
    if u is None or u.role not in ("admin", "gestor", "tecnico"):
        return negar_acesso(f"perfil {u.role if u else '—'} não importa cadernos",
                            "Seu perfil não importa cadernos")
    return send_file(io.BytesIO(onenote_assistente.montar()), as_attachment=True,
                     download_name=onenote_assistente.NOME_ARQUIVO,
                     mimetype="application/octet-stream", max_age=0)


@cadernos_bp.route("/api/importacoes", methods=["POST"])
@jwt_required()
def receber_importacao():
    """Recebe o .zip do assistente, valida e devolve o resumo para confirmar."""
    from .importacao import LIMITE_UPLOAD_MB, caderno_existente, receber, resumo_do_manifesto
    # Antes de tocar em request.form: ler o formulário já aplica o limite global.
    request.max_content_length = LIMITE_UPLOAD_MB * 1024 * 1024
    u = current_user()
    area = (request.form.get("area") or "pdr").strip().lower()
    if not _pode_importar(u, area):
        return _negar_importacao(u, area)
    f = request.files.get("pacote")
    if not f or not (f.filename or "").strip():
        return _erro("Envie o .zip gerado pelo assistente", 400)
    try:
        id_, man = receber(f, u.id, area)
    except tarefas.ErroDaTarefa as e:
        return _erro(str(e), 400)
    existente = caderno_existente(man)
    ex = None
    if existente:
        papel = _papel(u, existente)
        ex = {"uuid": existente.uuid, "nome": existente.nome, "area": existente.area,
              "pode_atualizar": core.pode(papel, "editor")}
    return jsonify({"id": id_, "resumo": resumo_do_manifesto(man), "existente": ex}), 201


@cadernos_bp.route("/api/importacoes/<id_>/iniciar", methods=["POST"])
@jwt_required()
def iniciar_importacao(id_):
    """Confirma: grava o caderno (tarefa). Reimportar exige ser editor do caderno."""
    from . import importacao
    u = current_user()
    rec = importacao.recebido(id_, u.id) if u else None
    if not rec:
        return _erro("Pacote não encontrado. Envie o .zip de novo.", 404)
    if not _pode_importar(u, rec["area"]):
        return _negar_importacao(u, rec["area"])
    existente = importacao.caderno_existente(importacao.ler_manifesto(rec["raiz"]))
    if existente and not core.pode(_papel(u, existente), "editor"):
        return negar_acesso(
            f"reimportar o caderno {existente.nome} sem ser editor dele",
            f'O caderno "{existente.nome}" já foi importado e você não é editor dele.')
    if tarefas.em_andamento("importacao"):
        return _erro("Já há uma importação em andamento. Tente de novo quando ela terminar.", 429)
    data = request.get_json(silent=True) or {}
    nome = (data.get("nome") or "").strip()[:200] or None
    t = tarefas.iniciar("importacao", u.id, importacao.executar, id_, u.id, nome, get_client_ip())
    return jsonify({"tarefa": t.to_dict()}), 202


@cadernos_bp.route("/api/importacoes/<id_>", methods=["DELETE"])
@jwt_required()
def descartar_importacao(id_):
    from . import importacao
    u = current_user()
    if u and importacao.recebido(id_, u.id):
        importacao.descartar(id_)
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
# BUSCA E LIXEIRA
# ══════════════════════════════════════════════════════════════════════════════

def _trecho(p, termos):
    texto = core.texto_de(p.conteudo_html)
    alvo = norm(texto)
    pos = min([alvo.find(t) for t in termos if alvo.find(t) >= 0] or [0])
    ini = max(0, pos - 60)
    pedaco = texto[ini:ini + 200].replace("\n", " ")
    return ("…" if ini else "") + pedaco + ("…" if ini + 200 < len(texto) else "")


@cadernos_bp.route("/api/busca", methods=["GET"])
@jwt_required()
def buscar():
    """Busca por todas as palavras (sem acento, sem caixa) nos cadernos visíveis."""
    u = current_user()
    if not u:
        return _erro("Usuário inválido", 401)
    termos = [t for t in norm(request.args.get("q") or "").split() if len(t) >= 2][:6]
    if not termos:
        return jsonify({"resultados": []})
    area = (request.args.get("area") or "pdr").strip().lower()
    cads = Caderno.query.filter_by(area=area, excluido_em=None)
    if request.args.get("caderno"):
        cads = cads.filter_by(uuid=request.args["caderno"])
    visiveis = {c.id: c for c in cads.all() if _papel(u, c)}
    if not visiveis:
        return jsonify({"resultados": []})
    q = CadernoPagina.query.filter(CadernoPagina.caderno_id.in_(list(visiveis)),
                                   CadernoPagina.excluido_em.is_(None))
    for t in termos:
        q = q.filter(CadernoPagina.texto_busca.like(f"%{t}%"))
    saida = []
    for p in q.order_by(CadernoPagina.atualizado_em.desc()).limit(50).all():
        secao = db.session.get(CadernoNo, p.secao_id)
        if not secao or not _no_visivel(secao):
            continue
        saida.append({"uuid": p.uuid, "titulo": p.titulo,
                      "caderno": {"uuid": visiveis[p.caderno_id].uuid,
                                  "nome": visiveis[p.caderno_id].nome},
                      "secao": secao.nome, "trecho": _trecho(p, termos)})
    return jsonify({"resultados": saida})


@cadernos_bp.route("/api/lixeira", methods=["GET"])
@jwt_required()
def lixeira():
    """O que foi excluído no caderno nos últimos dias (seções, grupos, páginas, arquivos)."""
    cad = _caderno(request.args.get("caderno") or "")
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    nos = CadernoNo.query.filter(CadernoNo.caderno_id == cad.id,
                                 CadernoNo.excluido_em.isnot(None)).all()
    paginas = CadernoPagina.query.filter(CadernoPagina.caderno_id == cad.id,
                                         CadernoPagina.excluido_em.isnot(None)).all()
    arquivos = (CadernoArquivo.query
                .filter(CadernoArquivo.caderno_id == cad.id,
                        CadernoArquivo.excluido_em.isnot(None),
                        CadernoArquivo.ativo.is_(True))
                .all())
    nomes = _nomes([x.excluido_por for x in nos + paginas + arquivos])

    def item(tipo, uuid_, nome, quando, por):
        expira = (quando + timedelta(days=LIXEIRA_DIAS)) if quando else None
        return {"tipo": tipo, "uuid": uuid_, "nome": nome,
                "excluido_em": quando.isoformat() if quando else None,
                "por": nomes.get(por, ""),
                "expira_em": expira.isoformat() if expira else None}

    itens = ([item(n.tipo, n.uuid, n.nome, n.excluido_em, n.excluido_por) for n in nos]
             + [item("pagina", p.uuid, p.titulo, p.excluido_em, p.excluido_por) for p in paginas]
             + [item("arquivo", a.uuid, a.nome_original, a.excluido_em, a.excluido_por)
                for a in arquivos if not a.embutido])
    itens.sort(key=lambda x: x["excluido_em"] or "", reverse=True)
    return jsonify({"itens": itens, "dias": LIXEIRA_DIAS})


@cadernos_bp.route("/api/arquivos/<uuid_>/restaurar", methods=["POST"])
@jwt_required()
def restaurar_arquivo(uuid_):
    """Tira o arquivo (todas as versões) da lixeira."""
    a = CadernoArquivo.query.filter_by(uuid=uuid_).first()
    cad = db.session.get(Caderno, a.caderno_id) if a else None
    u, papel, err = _carregar(cad, "editor")
    if err:
        return err
    CadernoArquivo.query.filter_by(grupo=a.grupo).update(
        {"excluido_em": None, "excluido_por": None})
    log_action(u.email, "RESTORE", entidade=f"caderno:{cad.nome}", campo="arquivo",
               novo=a.nome_original, ip=get_client_ip())
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
# PURGA (agendador diário)
# ══════════════════════════════════════════════════════════════════════════════

def purgar_lixeira(dias=None, agora=None):
    """Apaga de vez o que está na lixeira há mais de `dias`. Chamado pela tarefa
    diária. Os blobs só saem se ninguém mais (em nenhuma das tabelas que usam o
    blob store) apontar para eles."""
    from documentos import _sha_orfao
    dias = LIXEIRA_DIAS if dias is None else dias
    limite = (agora or datetime.now()) - timedelta(days=dias)
    contagem = {"cadernos": 0, "secoes": 0, "paginas": 0, "arquivos": 0, "blobs": 0}
    shas = set()

    def apagar_pagina(p):
        for a in CadernoArquivo.query.filter_by(escopo="pagina", escopo_id=p.id).all():
            shas.add(a.sha256)
            db.session.delete(a)
            contagem["arquivos"] += 1
        CadernoPaginaVersao.query.filter_by(pagina_id=p.id).delete()
        db.session.delete(p)
        contagem["paginas"] += 1

    for a in CadernoArquivo.query.filter(CadernoArquivo.excluido_em.isnot(None),
                                         CadernoArquivo.excluido_em < limite).all():
        shas.add(a.sha256)
        db.session.delete(a)
        contagem["arquivos"] += 1
    for p in CadernoPagina.query.filter(CadernoPagina.excluido_em.isnot(None),
                                        CadernoPagina.excluido_em < limite).all():
        apagar_pagina(p)
    for no in CadernoNo.query.filter(CadernoNo.excluido_em.isnot(None),
                                     CadernoNo.excluido_em < limite).all():
        pilha, ids = [no], []
        while pilha:
            n = pilha.pop()
            ids.append(n)
            pilha.extend(CadernoNo.query.filter_by(parent_id=n.id).all())
        for n in ids:
            for p in CadernoPagina.query.filter_by(secao_id=n.id).all():
                apagar_pagina(p)
            for a in CadernoArquivo.query.filter_by(escopo="secao", escopo_id=n.id).all():
                shas.add(a.sha256)
                db.session.delete(a)
        for n in reversed(ids):
            db.session.delete(n)
            contagem["secoes"] += 1
    for cad in Caderno.query.filter(Caderno.excluido_em.isnot(None),
                                    Caderno.excluido_em < limite).all():
        for p in CadernoPagina.query.filter_by(caderno_id=cad.id).all():
            apagar_pagina(p)
        for a in CadernoArquivo.query.filter_by(caderno_id=cad.id).all():
            shas.add(a.sha256)
            db.session.delete(a)
        CadernoNo.query.filter_by(caderno_id=cad.id).delete()
        CadernoMembro.query.filter_by(caderno_id=cad.id).delete()
        db.session.delete(cad)
        contagem["cadernos"] += 1
    db.session.flush()
    for sha in shas:
        if _sha_orfao(sha):
            arquivos_store.remover(sha)
            contagem["blobs"] += 1
    db.session.commit()
    return contagem
