"""
fluxos/core.py — a máquina de estados dos fluxos de revisão, sem Flask e sem banco.

Um fluxo é uma lista de etapas copiada do modelo na hora em que começa. Cada
etapa tem um papel (quem faz) e um tipo:

  execucao  uma saída: `enviar` para a próxima — ou encerra, se for a última
  revisao   duas saídas: `aprovar` (próxima ou encerra) e `devolver`
            (volta para `devolve_para` e soma 1 à rodada)

Tudo aqui é função pura sobre listas de dicionários: a rota carrega o fluxo,
pergunta ao core o que acontece e grava. É o que deixa as regras testáveis sem
subir o app (tests/test_fluxos_core.py).
"""
import unicodedata

TIPOS_ETAPA = ["execucao", "revisao"]
ACOES_POR_TIPO = {"execucao": ["enviar"], "revisao": ["aprovar", "devolver"]}

MAX_NOME = 80


def _slug(texto):
    s = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    s = "".join(c if c.isalnum() else "_" for c in s)
    return "_".join(p for p in s.split("_") if p)[:40]


def _texto(v):
    return (v or "").strip() if isinstance(v, str) else ""


def validar_modelo(papeis, etapas):
    """Normaliza e valida papéis e etapas. Devolve (papeis, etapas, erro|None).

    Chave ausente sai do nome ("Revisor Técnico" → "revisor_tecnico"). Revisão
    nunca é a primeira etapa (não há o que revisar) e só devolve para uma etapa
    ANTERIOR — devolver para frente seria pular a revisão.
    """
    if not isinstance(papeis, list) or not papeis:
        return None, None, "O modelo precisa de pelo menos um papel"
    if not isinstance(etapas, list) or not etapas:
        return None, None, "O modelo precisa de pelo menos uma etapa"

    papeis_n = []
    for p in papeis:
        p = p if isinstance(p, dict) else {}
        nome = _texto(p.get("nome"))[:MAX_NOME]
        if not nome:
            return None, None, "Todo papel precisa de nome"
        chave = _slug(_texto(p.get("chave")) or nome)
        if any(x["chave"] == chave for x in papeis_n):
            return None, None, f"Papel repetido: {nome}"
        padrao = p.get("padrao_user_id")
        try:
            padrao = int(padrao) if padrao not in (None, "") else None
        except (TypeError, ValueError):
            return None, None, f"Pessoa padrão inválida no papel {nome}"
        papeis_n.append({"chave": chave, "nome": nome, "padrao_user_id": padrao})
    chaves_papel = {p["chave"] for p in papeis_n}

    etapas_n = []
    for i, e in enumerate(etapas):
        e = e if isinstance(e, dict) else {}
        nome = _texto(e.get("nome"))[:MAX_NOME]
        if not nome:
            return None, None, "Toda etapa precisa de nome"
        chave = _slug(_texto(e.get("chave")) or nome)
        if any(x["chave"] == chave for x in etapas_n):
            return None, None, f"Etapa repetida: {nome}"
        papel = _texto(e.get("papel"))
        if papel not in chaves_papel:
            return None, None, f"A etapa {nome} cita um papel que não existe"
        tipo = _texto(e.get("tipo")) or "execucao"
        if tipo not in TIPOS_ETAPA:
            return None, None, f"Tipo de etapa inválido em {nome}. Use: {', '.join(TIPOS_ETAPA)}"
        devolve = ""
        if tipo == "revisao":
            if i == 0:
                return None, None, "A primeira etapa não pode ser de revisão"
            devolve = _texto(e.get("devolve_para")) or etapas_n[-1]["chave"]
            if devolve not in {x["chave"] for x in etapas_n}:
                return None, None, f"A revisão {nome} só pode devolver para uma etapa anterior"
        etapas_n.append({"chave": chave, "nome": nome, "papel": papel,
                         "tipo": tipo, "devolve_para": devolve})
    return papeis_n, etapas_n, None


def etapa(etapas, chave):
    return next((e for e in etapas if e["chave"] == chave), None)


def _indice(etapas, chave):
    return next((i for i, e in enumerate(etapas) if e["chave"] == chave), -1)


def acoes_possiveis(etapas, etapa_atual):
    e = etapa(etapas, etapa_atual)
    return list(ACOES_POR_TIPO.get(e["tipo"], [])) if e else []


def transicao(etapas, etapa_atual, acao):
    """(para_etapa | None, encerra, soma_rodada). Ação fora do tipo → ValueError."""
    if acao not in acoes_possiveis(etapas, etapa_atual):
        raise ValueError(f"Ação '{acao}' não se aplica a esta etapa")
    if acao == "devolver":
        return etapa(etapas, etapa_atual)["devolve_para"], False, True
    i = _indice(etapas, etapa_atual)
    if i + 1 >= len(etapas):
        return None, True, False
    return etapas[i + 1]["chave"], False, False


def rotulo_acao(etapas, etapa_atual, acao):
    para, encerra, _ = transicao(etapas, etapa_atual, acao)
    if acao == "aprovar":
        return "Aprovar"
    if encerra:
        return "Concluir"
    verbo = "Devolver para" if acao == "devolver" else "Enviar para"
    return f"{verbo} {etapa(etapas, para)['nome']}"


def responsavel(participantes, etapas, chave_etapa):
    """user_id de quem faz a etapa. `participantes` é {papel: user_id}."""
    e = etapa(etapas, chave_etapa)
    return participantes.get(e["papel"]) if e else None


def destinatarios(participantes, etapas, para_etapa, *, iniciador_id, ator_id, encerra):
    """(ids_acao, ids_info) de uma passagem, sem repetição e sem quem agiu.

    Quem passa a ter a etapa recebe "é sua vez" (acao); os demais participantes
    e quem iniciou recebem o andamento (info). Ao encerrar, todos recebem info.
    """
    acao = []
    if not encerra:
        uid = responsavel(participantes, etapas, para_etapa)
        if uid and uid != ator_id:
            acao = [uid]
    info = []
    for uid in list(participantes.values()) + [iniciador_id]:
        if uid and uid != ator_id and uid not in acao and uid not in info:
            info.append(uid)
    return acao, info
