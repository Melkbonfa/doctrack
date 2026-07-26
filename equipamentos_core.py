"""equipamentos_core.py — cálculo do ICE e do IDP no servidor (fonte única).

Antes os dois índices só existiam em `static/equipamentos.js`: o dashboard, o
export e qualquer relatório precisariam reimplementar a mesma regra, e o cliente
tinha de baixar TODOS os documentos do sistema só para dividir finalizados por
aplicáveis. Aqui a regra mora num lugar só e o front consome o resultado.

Duas correções em relação à versão que rodava no cliente:

  1) Validade ANVISA vencida não conta mais como campo preenchido. O plano do
     módulo sempre pediu "validade não vencida"; a versão anterior só olhava se
     o campo tinha texto, então um registro vencido em 2023 dava 100% de
     regulatório — justamente na dimensão de risco.
  2) O denominador documental de quem ainda não tem documentos carregados usa
     os 12 tipos reais (TIPOS_DOC_TODOS), não o 9 de quando o módulo nasceu.

Funções puras: recebem o Equipamento e a lista de Documentos dele, não tocam
em db.session nem em request.
"""
from datetime import date, datetime

from models import TIPOS_DOC_TODOS

# ── ICE — Índice de Completude do Equipamento ────────────────────────────────
# Média simples de três subíndices: Cadastro, Regulatório e Documental.
CAMPOS_CADASTRO = ["sku", "sku_importacao", "nome_tecnico", "fabricante",
                   "categoria_id", "familia_id"]
LABEL_CADASTRO = {
    "sku": "SKU de Venda", "sku_importacao": "SKU de Importação",
    "nome_tecnico": "Nome técnico", "fabricante": "Fabricante",
    "categoria_id": "Categoria", "familia_id": "Família",
}
LABEL_REGULATORIO = {
    "classificacao_reg": "Classificação (RUO/IVD)", "anvisa": "Registro ANVISA",
    "anvisa_registro": "Data de registro", "anvisa_validade": "Validade ANVISA",
}
LABEL_DOC_FALTANDO = "Docs não finalizados"

# Sem documentos carregados o denominador cai nos 12 tipos que todo equipamento
# passa a ter ao ser criado (_ensure_docs_for_equip).
NDOC_PADRAO = len(TIPOS_DOC_TODOS)

# Quantos dias antes do vencimento o registro já entra como "vencendo".
ALERTA_VENCIMENTO_DIAS = 90

# ── IDP — Índice de Desenvolvimento de Produto ───────────────────────────────
# 6 itens de revisão: 3 marcados à mão no equipamento, 3 derivados do status dos
# documentos. IDP = Revisados / (6 − N/A) × 100.
ITENS_IDP = ["cadastro", "estrutura", "it", "checklists", "manual_usuario", "descritivo"]
LABEL_IDP = {
    "cadastro": "Cadastro", "estrutura": "Estrutura", "it": "IT",
    "checklists": "Checklists", "manual_usuario": "Manual usuário",
    "descritivo": "Descritivo",
}
CAMPO_IDP_MANUAL = {"cadastro": "rev_cadastro", "estrutura": "rev_estrutura",
                    "descritivo": "rev_descritivo"}
TIPOS_CHECKLIST = ["Checklist_Conferencia", "Checklist_BurnIn",
                   "Checklist_Limpeza_Embalagem", "Checklist_Produto"]

_FORMATOS_DATA = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d")


def parse_data(valor):
    """Datas do equipamento são texto (padrão do projeto) e chegam de origens
    diferentes: do input date ('YYYY-MM-DD') e das planilhas ('dd/mm/yyyy').
    Retorna date ou None quando não dá para interpretar."""
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()[:10]
    for fmt in _FORMATOS_DATA:
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    return None


def status_validade(equip, hoje=None):
    """Situação do registro ANVISA: 'sem_data' | 'vencido' | 'vencendo' | 'ok'.

    'dias' é positivo enquanto falta prazo e negativo depois de vencido.
    """
    hoje = hoje or date.today()
    validade = parse_data(getattr(equip, "anvisa_validade", "") or "")
    if not validade:
        return {"estado": "sem_data", "data": "", "dias": None}
    dias = (validade - hoje).days
    if dias < 0:
        estado = "vencido"
    elif dias <= ALERTA_VENCIMENTO_DIAS:
        estado = "vencendo"
    else:
        estado = "ok"
    return {"estado": estado, "data": validade.isoformat(), "dias": dias}


def campos_regulatorios(equip):
    """RUO (uso em pesquisa) não tem registro ANVISA: basta a classificação."""
    if (getattr(equip, "classificacao_reg", "") or "") == "RUO":
        return ["classificacao_reg"]
    return ["classificacao_reg", "anvisa", "anvisa_registro", "anvisa_validade"]


def preenchido(equip, campo, hoje=None):
    """Campo conta como completo? Validade vencida NÃO conta (era o furo antigo)."""
    if campo == "anvisa_validade":
        return status_validade(equip, hoje)["estado"] in ("ok", "vencendo")
    valor = getattr(equip, campo, None)
    if campo.endswith("_id"):
        return bool(valor)
    return bool(valor and str(valor).strip())


# ── estados de revisão derivados do documento ────────────────────────────────
def _estado_pre(status):
    if status == "Homologado":
        return "Revisado"
    if not status or status == "Elaborar":
        return "Pendente"
    return "Em revisão"


def _estado_manuais(status):
    if status == "Concluído":
        return "Revisado"
    if not status or status == "Elaborar":
        return "Pendente"
    return "Em revisão"


def _do_tipo(docs, tipos):
    return [d for d in docs if (getattr(d, "tipo_doc", "") or "") in tipos]


def _aplicaveis(docs):
    return [d for d in docs if getattr(d, "aplicavel", True) is not False]


def estado_revisao(equip, item, docs):
    """Estado de um dos 6 itens do IDP. Documento marcado como N/A no módulo
    Documentos vira item N/A aqui (sai do denominador, como o N/A manual)."""
    campo = CAMPO_IDP_MANUAL.get(item)
    if campo:
        return getattr(equip, campo, None) or "Pendente"

    if item == "it":
        todos = _do_tipo(docs, ["IT"])
        apl = _aplicaveis(todos)
        if todos and not apl:
            return "N/A"
        return _estado_pre(getattr(apl[0], "status", "") if apl else "")

    if item == "manual_usuario":
        todos = _do_tipo(docs, ["Manual_Usuario"])
        apl = _aplicaveis(todos)
        if todos and not apl:
            return "N/A"
        return _estado_manuais(getattr(apl[0], "status", "") if apl else "")

    if item == "checklists":
        todos = _do_tipo(docs, TIPOS_CHECKLIST)
        apl = _aplicaveis(todos)
        if todos and not apl:
            return "N/A"
        if not apl:
            return "Pendente"
        estados = [_estado_pre(getattr(d, "status", "")) for d in apl]
        if all(e == "Revisado" for e in estados):
            return "Revisado"
        if all(e == "Pendente" for e in estados):
            return "Pendente"
        return "Em revisão"

    return "Pendente"


def revisoes(equip, docs):
    return {item: estado_revisao(equip, item, docs) for item in ITENS_IDP}


def idp(equip, docs, revs=None):
    """Revisados / (6 − N/A) × 100. None quando todos os itens são N/A."""
    revs = revs if revs is not None else revisoes(equip, docs)
    aplicaveis = [e for e in revs.values() if e != "N/A"]
    if not aplicaveis:
        return None
    return round(sum(1 for e in aplicaveis if e == "Revisado") / len(aplicaveis) * 100)


# ── resultado consolidado ────────────────────────────────────────────────────
def indices(equip, docs=None, hoje=None):
    """Índices e sinais de risco de um equipamento.

    `docs` são os documentos ATIVOS do equipamento (a lista já filtrada); vazio
    é tratado como "ainda não tem documentos" e cai no denominador padrão.
    """
    hoje = hoje or date.today()
    docs = list(docs or [])

    # Cadastro
    faltando_cad = [c for c in CAMPOS_CADASTRO if not preenchido(equip, c, hoje)]
    cad = round((len(CAMPOS_CADASTRO) - len(faltando_cad)) / len(CAMPOS_CADASTRO) * 100)

    # Regulatório
    campos_reg = campos_regulatorios(equip)
    faltando_reg = [c for c in campos_reg if not preenchido(equip, c, hoje)]
    reg = round((len(campos_reg) - len(faltando_reg)) / len(campos_reg) * 100)
    validade = status_validade(equip, hoje)

    # Documental
    docs_apl = _aplicaveis(docs)
    finais = [d for d in docs_apl if getattr(d, "status_global", "") == "Finalizado"]
    alvo = len(docs_apl) or NDOC_PADRAO
    doc = round(min(alvo, len(finais)) / alvo * 100)

    # Risco vindo dos documentos — dado que já era carregado e nunca usado
    atrasados = [d for d in docs_apl if getattr(d, "atrasado", False)]
    dias = [getattr(d, "dias_para_prazo", None) for d in atrasados]
    atraso_max = max((-d for d in dias if d is not None), default=0)
    responsaveis = sorted({(getattr(d, "responsavel", "") or "").strip()
                           for d in docs_apl if (getattr(d, "responsavel", "") or "").strip()})

    revs = revisoes(equip, docs)

    lacunas = ([LABEL_CADASTRO[c] for c in faltando_cad] +
               [LABEL_REGULATORIO[c] for c in faltando_reg])
    return {
        "id": equip.id,
        "cad": cad,
        "reg": reg,
        "doc": doc,
        "ice": round((cad + reg + doc) / 3),
        "idp": idp(equip, docs, revs),
        "rev": revs,
        "docs_total": len(docs),
        "docs_aplicaveis": len(docs_apl),
        "docs_finais": len(finais),
        "docs_alvo": alvo,
        "docs_atrasados": len(atrasados),
        "atraso_max": atraso_max,
        "responsaveis": responsaveis,
        "reg_estado": validade["estado"],
        "reg_validade": validade["data"],
        "reg_dias": validade["dias"],
        "lacunas": lacunas,
        "docs_faltando": max(0, alvo - min(alvo, len(finais))),
    }


def faixa(valor):
    """Mesma escala de cor usada no dashboard."""
    if valor is None:
        return ""
    return "completo" if valor >= 85 else "parcial" if valor >= 50 else "inicial"


def agrupar_documentos(docs):
    """Lista plana de Documento → {equipamento_id: [docs]}."""
    por_equip = {}
    for d in docs:
        if d.equipamento_id:
            por_equip.setdefault(d.equipamento_id, []).append(d)
    return por_equip


def calcular_lote(equips, docs, hoje=None):
    """Índices de vários equipamentos de uma vez (uma query de documentos)."""
    por_equip = agrupar_documentos(docs)
    return [indices(e, por_equip.get(e.id, []), hoje) for e in equips]
