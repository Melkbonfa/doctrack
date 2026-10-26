"""
vinculos.py — como projeto, entregável e produto se ligam.

Desenho completo em docs/planos/ESTUDO_ligacoes_entregaveis.md. Aqui ficam as
ondas A e B:

  * **projeto ↔ equipamento** (`Projeto.equipamento_id`): o produto que o projeto
    desenvolve, só no PDE. Projeto novo pode criar o equipamento na hora, e ele
    nasce com os 12 documentos.
  * **natureza do entregável**: o que ele É. Fica no item do modelo (vale para
    todos os projetos do modelo) e pode ser sobrescrita no próprio entregável.
    Nesta onda só a natureza "documento" tem efeito; as demais já podem ser
    cadastradas e ganham comportamento nas próximas ondas.

## A regra: o artefato manda, o entregável espelha

O artefato é CALCULADO — equipamento do projeto + alvo da natureza → documento(s)
— e nunca guardado: trocar o equipamento do projeto, ou o alvo no modelo, leva
tudo junto, sem FK para dessincronizar.

O status do entregável, por outro lado, é GRAVADO por sincronização (como o
cartão de missão já faz): avanço, EVM, snapshots, curva-S, alertas e exports
leem `entregavel.status` em dezenas de lugares, e cada mudança entra em
`entregavel_historico` — a curva-S continua fiel.

## O ciclo do projeto

Para o projeto, o documento só conta como pronto se foi concluído DEPOIS do
início dele. Sem isso, a versão 2 de um produto ligada ao equipamento da versão 1
nasceria com o manual concluído. O documento concluído antes aparece como
pendente, com a marca `antes_do_projeto`; iniciar um fluxo de revisão reabre o
documento (fluxos/routes._ao_iniciar).

Quando a data de conclusão do documento é desconhecida (documentos antigos), vale
o que o próprio entregável já dizia: se o projeto já o dava como concluído, o
ciclo era dele.
"""
from datetime import date, datetime

from models import (db, Projeto, Entregavel, ModeloEntregavel, Documento, Equipamento,
                    TipoProjeto, STATUS_MAP, TIPOS_DOC_TODOS, TIPOS_DOC_LABELS,
                    AREA_PROJETO_LEGADO, _parse_iso)

# Ordem = a do seletor. A chave vazia é "não definida" (nenhum vínculo).
NATUREZAS = [
    ("", "Não definida"),
    ("documento", "Documento controlado"),
    ("doc_fabricante", "Documento do fabricante"),
    ("comunicacao", "Peça de comunicação"),
    ("software", "Software"),
    ("cadastro", "Cadastro"),
    ("validacao", "Validação"),
    ("capacitacao", "Capacitação"),
]
NATUREZA_ROTULO = dict(NATUREZAS)
# Só no entregável: desliga o vínculo herdado do modelo ("este projeto não faz o
# Manual ES"). No modelo não faz sentido — lá basta deixar a natureza vazia.
SEM_VINCULO = "nenhuma"

ALVO_CHECKLISTS = "checklists"
TIPOS_CHECKLIST = ["Checklist_Conferencia", "Checklist_BurnIn",
                   "Checklist_Limpeza_Embalagem", "Checklist_Produto"]


def alvos_documento():
    """[(alvo, rótulo)]: os 12 tipos de documento e os 4 checklists juntos."""
    out = [(t, TIPOS_DOC_LABELS.get(t, t)) for t in TIPOS_DOC_TODOS]
    out.append((ALVO_CHECKLISTS, "Checklists (os 4)"))
    return out


def rotulo_alvo(alvo):
    return dict(alvos_documento()).get(alvo, alvo or "")


def tipos_do_alvo(alvo):
    if alvo == ALVO_CHECKLISTS:
        return list(TIPOS_CHECKLIST)
    return [alvo] if alvo in TIPOS_DOC_TODOS else []


def validar_natureza_alvo(natureza, alvo, *, no_entregavel=False):
    """(natureza, alvo, erro). Documento exige um alvo válido; as demais
    naturezas ainda não usam alvo e o descartam."""
    natureza = (natureza or "").strip()
    alvo = (alvo or "").strip()
    validas = [n for n, _ in NATUREZAS] + ([SEM_VINCULO] if no_entregavel else [])
    if natureza not in validas:
        return None, None, "natureza inválida"
    if natureza == "documento":
        if not tipos_do_alvo(alvo):
            return None, None, "escolha qual documento do equipamento este entregável é"
        return natureza, alvo, None
    return natureza, "", None


# ── natureza e artefato ──────────────────────────────────────────────────────

def modelos_por_chave(chaves):
    chaves = {c for c in chaves if c}
    if not chaves:
        return {}
    return {m.chave: m for m in ModeloEntregavel.query.filter(ModeloEntregavel.chave.in_(chaves))}


def natureza_alvo(e, modelos=None):
    """(natureza, alvo) efetivos: os do próprio entregável ou os do item do modelo."""
    propria = (e.natureza or "").strip()
    if propria == SEM_VINCULO:
        return "", ""
    if propria:
        return propria, (e.alvo or "")
    if e.modelo_chave:
        m = (modelos.get(e.modelo_chave) if modelos is not None
             else ModeloEntregavel.query.filter_by(chave=e.modelo_chave).first())
        if m and (m.natureza or "").strip():
            return m.natureza, (m.alvo or "")
    return "", ""


def area_do_projeto(p):
    t = (TipoProjeto.query.filter(db.func.lower(TipoProjeto.nome) == (p.tipo or "").lower())
         .first()) if p.tipo else None
    return (t.area if t and t.area else AREA_PROJETO_LEGADO)


def inicio_do_projeto(p):
    """Início real, senão o previsto, senão a criação do projeto."""
    for v in (p.data_inicio_real, p.data_inicio_prev):
        d = _parse_iso(v)
        if d:
            return d
    return p.criado_em.date() if p.criado_em else date.today()


def documentos_do(e, modelos=None, equipamento_id=None):
    """Os documentos que este entregável É. `equipamento_id` substitui o do
    projeto (prévia de uma ligação que ainda não foi gravada)."""
    nat, alvo = natureza_alvo(e, modelos)
    if nat != "documento":
        return []
    eid = equipamento_id if equipamento_id is not None else (e.projeto.equipamento_id
                                                            if e.projeto else None)
    tipos = tipos_do_alvo(alvo)
    if not eid or not tipos:
        return []
    docs = Documento.query.filter(Documento.ativo == True, Documento.equipamento_id == eid,
                                  Documento.tipo_doc.in_(tipos)).all()
    return sorted(docs, key=lambda d: (tipos.index(d.tipo_doc), d.id))


def estado_do_documento(doc):
    """(status do entregável, percentual) que o documento sozinho implica."""
    if not doc.aplicavel:
        return "na", None
    fluxo = STATUS_MAP.get(doc.setor) or []
    i = fluxo.index(doc.status) if doc.status in fluxo else 0
    if len(fluxo) < 2 or i == 0:
        return "pendente", 0
    if i >= len(fluxo) - 1:
        return "concluido", 100
    return "em_progresso", round(100 * i / (len(fluxo) - 1))


def espelho(docs, inicio, status_atual=""):
    """O status do entregável a partir dos seus documentos, com o ciclo do projeto.

    Devolve {status, percentual, antes_do_projeto: [ids], conclusao: date|None}
    ou None sem documentos. Vários documentos (os checklists): todos prontos →
    concluído; nenhum começado → pendente; qualquer outra mistura → em progresso
    com a média. Documento N/A sai da conta; todos N/A → N/A.
    """
    if not docs:
        return None
    itens, antes = [], []
    for d in docs:
        st, pct = estado_do_documento(d)
        if st == "concluido":
            quando = d.concluido_em.date() if d.concluido_em else None
            conta = (quando >= inicio) if quando else (status_atual == "concluido")
            if not conta:
                st, pct = "pendente", 0
                antes.append(d.id)
        itens.append((d, st, pct))
    aplicaveis = [x for x in itens if x[1] != "na"]
    if not aplicaveis:
        return {"status": "na", "percentual": None, "antes_do_projeto": antes, "conclusao": None}
    if all(x[1] == "concluido" for x in aplicaveis):
        datas = [x[0].concluido_em.date() for x in aplicaveis if x[0].concluido_em]
        return {"status": "concluido", "percentual": 100, "antes_do_projeto": antes,
                "conclusao": max(datas) if datas else None}
    if all(x[1] == "pendente" for x in aplicaveis):
        return {"status": "pendente", "percentual": 0, "antes_do_projeto": antes, "conclusao": None}
    media = round(sum(x[2] or 0 for x in aplicaveis) / len(aplicaveis))
    return {"status": "em_progresso", "percentual": max(1, min(99, media)),
            "antes_do_projeto": antes, "conclusao": None}


def _doc_dict(d, antes):
    return {"id": d.id, "tipo_doc": d.tipo_doc, "titulo": d.tipo_doc_label or d.documento,
            "status": d.status or "", "setor": d.setor, "aplicavel": bool(d.aplicavel),
            "concluido_em": d.concluido_em.strftime("%d/%m/%Y") if d.concluido_em else "",
            "antes_do_projeto": d.id in antes, "link": f"/?doc={d.id}"}


def artefato_do(e, modelos=None):
    """O que a tela mostra do artefato do entregável, ou None se ele não tem."""
    nat, alvo = natureza_alvo(e, modelos)
    p = e.projeto
    if nat != "documento" or not p or not p.equipamento_id:
        return None
    docs = documentos_do(e, modelos)
    esp = espelho(docs, inicio_do_projeto(p), e.status)
    equip = p.equipamento
    return {
        "natureza": nat, "natureza_rotulo": NATUREZA_ROTULO.get(nat, nat),
        "alvo": alvo, "alvo_rotulo": rotulo_alvo(alvo),
        "equipamento": {"id": equip.id, "nome": equip.nome} if equip else None,
        "documentos": [_doc_dict(d, esp["antes_do_projeto"] if esp else []) for d in docs],
        "status": esp["status"] if esp else None,
        "percentual": esp["percentual"] if esp else None,
        "antes_do_projeto": bool(esp and esp["antes_do_projeto"]),
    }


# ── sincronização ────────────────────────────────────────────────────────────

def sincronizar_entregavel(e, email, modelos=None):
    """Aplica o espelho no entregável. (mudou, status_antigo). NÃO comita."""
    p = e.projeto
    if not p or not p.equipamento_id or not p.ativo:
        return False, e.status
    docs = documentos_do(e, modelos)
    esp = espelho(docs, inicio_do_projeto(p), e.status)
    if esp is None:
        return False, e.status
    novo, pct = esp["status"], esp["percentual"]
    if novo == e.status and (novo != "em_progresso" or pct == e.percentual):
        return False, e.status
    from entregaveis import aplicar_status_entregavel     # import tardio: entregaveis importa este
    antigo = aplicar_status_entregavel(e, novo, email, percentual=pct)
    if novo == "concluido" and esp["conclusao"]:
        e.data_conclusao = esp["conclusao"].isoformat()
    return True, antigo


def sincronizar_projeto(p, email):
    """Todos os entregáveis ligados do projeto. [(entregável, status_antigo)]."""
    if not p.equipamento_id:
        return []
    modelos = modelos_por_chave(e.modelo_chave for e in p.entregaveis)
    out = []
    for e in p.entregaveis:
        mudou, antigo = sincronizar_entregavel(e, email, modelos)
        if mudou:
            out.append((e, antigo))
    return out


def entregaveis_do_documento(doc, so_ativos=True):
    """[(projeto, entregável)] que SÃO este documento."""
    if not doc.equipamento_id or not doc.tipo_doc:
        return []
    q = Projeto.query.filter_by(equipamento_id=doc.equipamento_id)
    if so_ativos:
        q = q.filter_by(ativo=True)
    projetos = q.all()
    modelos = modelos_por_chave(e.modelo_chave for p in projetos for e in p.entregaveis)
    out = []
    for p in projetos:
        for e in p.entregaveis:
            nat, alvo = natureza_alvo(e, modelos)
            if nat == "documento" and doc.tipo_doc in tipos_do_alvo(alvo):
                out.append((p, e))
    return out


def sincronizar_do_documento(doc, email):
    """O documento mudou: espelha nos entregáveis que são ele. [(entregável, antigo)]."""
    out = []
    for p, e in entregaveis_do_documento(doc):
        mudou, antigo = sincronizar_entregavel(e, email)
        if mudou:
            out.append((e, antigo))
    return out


def previa_vinculo(p, equipamento_id):
    """O que muda nos entregáveis se o projeto passar a apontar para
    `equipamento_id` (None = desligar). Não grava nada."""
    modelos = modelos_por_chave(e.modelo_chave for e in p.entregaveis)
    inicio = inicio_do_projeto(p)
    out = []
    for e in p.entregaveis:
        if equipamento_id:
            docs = documentos_do(e, modelos, equipamento_id=equipamento_id)
            esp = espelho(docs, inicio, e.status)
        else:
            docs, esp = [], None
        if esp is None:
            continue
        mudanca = (esp["status"] != e.status
                   or (esp["status"] == "em_progresso" and esp["percentual"] != e.percentual))
        out.append({"entregavel_id": e.id, "tipo": e.tipo,
                    "antes": {"status": e.status, "percentual": e.percentual},
                    "depois": {"status": esp["status"], "percentual": esp["percentual"]},
                    "muda": mudanca, "antes_do_projeto": bool(esp["antes_do_projeto"]),
                    "documentos": [_doc_dict(d, esp["antes_do_projeto"]) for d in docs]})
    return out


# ── equipamento do projeto ───────────────────────────────────────────────────

def criar_equipamento_para(p, email):
    """Cria o equipamento do projeto (nome e SKU do projeto) com os 12
    documentos. NÃO comita. Mesmo caminho do POST /api/equipamentos."""
    from servidor import _ensure_docs_for_equip, _registrar_historico   # import tardio
    equip = Equipamento(nome=p.nome, sku=(p.sku or "").strip(), ativo=True)
    db.session.add(equip)
    db.session.flush()
    _ensure_docs_for_equip(equip)
    _registrar_historico(equip.id, {"nome": ("", equip.nome), "projeto": ("", p.nome)},
                         email, evento="create")
    return equip


def projetos_do_equipamento(equip_id, so_ativos=True):
    q = Projeto.query.filter_by(equipamento_id=equip_id)
    if so_ativos:
        q = q.filter_by(ativo=True)
    return q.order_by(Projeto.id).all()


def projetos_por_equipamento(equip_ids):
    """{equipamento_id: [{id, nome}]} dos projetos ativos — para listas."""
    ids = [i for i in equip_ids if i]
    if not ids:
        return {}
    out = {}
    for p in (Projeto.query.filter(Projeto.equipamento_id.in_(ids), Projeto.ativo == True)
              .order_by(Projeto.id)):
        out.setdefault(p.equipamento_id, []).append({"id": p.id, "nome": p.nome})
    return out
