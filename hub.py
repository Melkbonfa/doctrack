"""
hub.py — números das vitrines do hub (/hub) e dos sub-hubs (/hub/<área>).

  GET /api/hub/resumo   tudo o que as duas telas mostram, numa chamada só

As vitrines mostram 3 números por módulo e uma linha "o que espera por você".
Em vez de cada tela disparar meia dúzia de requisições aos endpoints dos
módulos (vários deles pesados: a lista de Missões traz os cartões inteiros, o
resumo de Projetos traz a carga por responsável), este endpoint devolve só as
contagens, já recortadas pelo perfil de quem pede.

## Acesso

Qualquer usuário logado. Cada bloco segue o mesmo corte de perfil do módulo que
ele resume — o que o perfil não abre, não sai daqui:

  equip, docs   todos (os módulos são de toda a área, inclusive leitura)
  missoes       técnico para cima
  tempos        técnico para cima (só os apontamentos DO PRÓPRIO usuário)
  fluxos        técnico para cima
  ent           admin/gestor (no sub-hub Projetos é card de gestão; o técnico
                entra lá em modo restrito, que este resumo não reproduz)
  custos        admin/gestor (custo é dinheiro: mesmo corte de custos/routes.py)

O bloco que falhar sai como ausente e o erro vai para o log: um número quebrado
não pode derrubar a primeira tela depois do login.
"""
import logging
from datetime import datetime, timedelta

from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from models import (db, User, Documento, Equipamento, CategoriaEquipamento,
                    Projeto, Entregavel, Missao, MissaoCartao, TipoProjeto,
                    AREA_PROJETO_LEGADO)

log = logging.getLogger(__name__)

hub_bp = Blueprint("hub", __name__)

GESTAO = ("admin", "gestor")
MEMBROS = ("admin", "gestor", "tecnico")


def _eu():
    return User.query.filter_by(email=get_jwt_identity(), ativo=True).first()


def _area_dos_tipos():
    """{tipo de projeto em minúsculas: slug da área} — a mesma regra de
    entregaveis._areas_dos_tipos (tipo vazio ou desconhecido = área legada)."""
    return {t.nome.lower(): (t.area or AREA_PROJETO_LEGADO) for t in TipoProjeto.query.all()}


def _area_do_projeto(p, mapa):
    return mapa.get((p.tipo or "").lower(), AREA_PROJETO_LEGADO)


# ── blocos ───────────────────────────────────────────────────────────────────

def _equip(_u):
    total = Equipamento.query.count()
    ativos = Equipamento.query.filter(Equipamento.status == "Ativo").count()
    return {"total": total, "ativos": ativos,
            "categorias": CategoriaEquipamento.query.count()}


def _docs(u):
    """Documentos vivos (ativos e aplicáveis). "Em andamento" e "atrasado" usam
    as propriedades do modelo — a mesma definição dos KPIs do dashboard."""
    docs = (Documento.query
            .filter(Documento.ativo == True, Documento.aplicavel == True)  # noqa: E712
            .all())
    andamento = [d for d in docs if not d.concluido]
    nome = (u.nome or "").strip().lower()
    # `responsavel` é texto livre ("Ana", "Ana / Bruno"): conta o documento em
    # andamento cujo responsável cita o nome da pessoa.
    meus = [d for d in andamento
            if len(nome) >= 3 and nome in (d.responsavel or "").lower()] if nome else []
    return {"total": len(docs), "andamento": len(andamento),
            "atrasados": sum(1 for d in andamento if d.atrasado),
            "meus": len(meus), "meus_atrasados": sum(1 for d in meus if d.atrasado)}


def _ent(_u):
    """Por área: projetos ativos, avanço médio e entregáveis atrasados — as
    contas de /api/entregaveis/resumo (média só dos projetos com escopo)."""
    from sqlalchemy.orm import selectinload
    mapa = _area_dos_tipos()
    projetos = (Projeto.query.options(selectinload(Projeto.entregaveis))
                .filter_by(ativo=True).all())
    out = {}
    for p in projetos:
        a = out.setdefault(_area_do_projeto(p, mapa),
                           {"projetos": 0, "atrasados": 0, "_avancos": []})
        a["projetos"] += 1
        a["atrasados"] += p.atrasados
        if any(e.status != "na" for e in p.entregaveis):
            a["_avancos"].append(p.avanco)
    for a in out.values():
        av = a.pop("_avancos")
        a["avanco_medio"] = round(sum(av) / len(av)) if av else 0
    return out


def _missoes(u):
    from missoes import _cond_responsavel
    vivos = (MissaoCartao.query
             .join(Missao, MissaoCartao.missao_id == Missao.id)
             .filter(Missao.arquivado == False, MissaoCartao.concluido == False))  # noqa: E712
    meus = vivos.filter(_cond_responsavel(u)).all()
    return {"meus": len(meus), "meus_atrasados": sum(1 for c in meus if c.atrasado),
            "equipe_andamento": vivos.count()}


def _custos(_u):
    from custos.models import Composicao
    base = Composicao.query.filter(Composicao.ativo == True)  # noqa: E712
    return {"composicoes": base.filter(Composicao.status != "arquivada").count(),
            "vigentes": base.filter(Composicao.status == "vigente").count(),
            "rascunhos": base.filter(Composicao.status == "rascunho").count()}


def _tempos(u):
    from tempos.models import Apontamento
    from tempos import core
    agora = datetime.now()
    hoje = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    segunda = hoje - timedelta(days=hoje.weekday())
    semana = (Apontamento.query
              .filter(Apontamento.user_id == u.id, Apontamento.inicio >= segunda)
              .all())
    do_dia = [a for a in semana if a.inicio >= hoje]
    fechados_hoje = [a.fim for a in do_dia if a.fim]
    return {
        "hoje_s": sum(core.segundos(a) for a in do_dia),
        "semana_s": sum(core.segundos(a) for a in semana),
        "projetos_semana": len({a.projeto_id for a in semana if a.projeto_id}),
        "em_curso": any(a.fim is None for a in semana),
        "ultimo_fim": max(fechados_hoje).strftime("%H:%M") if fechados_hoje else None,
    }


def _fluxos(u):
    """`comigo` por área: fluxo de documento é da área de Documentos (pde); de
    entregável, da área do projeto. Mesma regra de "é comigo" de
    /fluxos/api/comigo (responsável pela etapa atual)."""
    from fluxos.models import Fluxo, FluxoParticipante
    from fluxos import core
    meus = (Fluxo.query.join(FluxoParticipante)
            .filter(Fluxo.status == "andamento", FluxoParticipante.user_id == u.id)
            .distinct().all())
    meus = [f for f in meus
            if core.responsavel(f.mapa_participantes(), f.etapas_lista(), f.etapa_atual) == u.id]
    comigo = {}
    ent_ids = [f.ref_id for f in meus if f.ref_tipo == "entregavel"]
    area_ent = {}
    if ent_ids:
        mapa = _area_dos_tipos()
        for e_id, tipo in (db.session.query(Entregavel.id, Projeto.tipo)
                           .join(Projeto, Entregavel.projeto_id == Projeto.id)
                           .filter(Entregavel.id.in_(ent_ids)).all()):
            area_ent[e_id] = mapa.get((tipo or "").lower(), AREA_PROJETO_LEGADO)
    for f in meus:
        area = area_ent.get(f.ref_id, AREA_PROJETO_LEGADO) if f.ref_tipo == "entregavel" else "pde"
        comigo[area] = comigo.get(area, 0) + 1
    ano = datetime(datetime.now().year, 1, 1)
    return {
        "comigo": comigo, "comigo_total": len(meus),
        "andamento": Fluxo.query.filter(Fluxo.status == "andamento").count(),
        "concluidos_ano": Fluxo.query.filter(Fluxo.status == "aprovado",
                                             Fluxo.concluido_em >= ano).count(),
    }


BLOCOS = [
    ("equip",   None,    _equip),
    ("docs",    None,    _docs),
    ("ent",     GESTAO,  _ent),
    ("missoes", MEMBROS, _missoes),
    ("custos",  GESTAO,  _custos),
    ("tempos",  MEMBROS, _tempos),
    ("fluxos",  MEMBROS, _fluxos),
]


@hub_bp.route("/api/hub/resumo", methods=["GET"])
@jwt_required()
def resumo():
    u = _eu()
    if u is None:
        return jsonify({"erro": "Usuário não encontrado"}), 401
    out = {}
    for chave, perfis, fn in BLOCOS:
        if perfis and u.role not in perfis:
            continue
        try:
            out[chave] = fn(u)
        except Exception:   # um bloco quebrado não derruba a tela
            log.exception("hub: falha ao montar o bloco %s", chave)
            db.session.rollback()
    return jsonify({"perfil": u.role, "modulos": out})
