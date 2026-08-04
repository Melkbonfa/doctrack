"""
custos/core.py — Motor de cálculo do módulo Custos.

Fonte única do número, no molde de `equipamentos_core.py`: o servidor calcula,
o front só exibe. Nenhuma fórmula é reimplementada em JavaScript — foi
exatamente a duplicação de fórmula entre abas que tornou a planilha de origem
indefensável.

Toda a aritmética é `Decimal`. Misturar float aqui reintroduz o erro que a
escolha de `Numeric` nos modelos existe para evitar.
"""
from decimal import Decimal, ROUND_HALF_UP

from .models import LIMITE_DESVIO_CAMBIO, MOEDAS_ESTRANGEIRAS

ZERO = Decimal("0")
CEM = Decimal("100")
_02 = Decimal("0.01")


def D(v):
    """Qualquer coisa -> Decimal. None e vazio viram zero."""
    if v is None or v == "":
        return ZERO
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def q2(v):
    """Arredonda para centavos (ROUND_HALF_UP — o arredondamento comercial)."""
    return D(v).quantize(_02, rounding=ROUND_HALF_UP)


def f2(v):
    """Decimal -> float com 2 casas, para JSON."""
    return None if v is None else float(q2(v))


# ── VALOR DE UMA LINHA ────────────────────────────────────────────────────────

def fob_brl(comp):
    """Valor FOB unitário convertido pela taxa de planejamento."""
    return D(comp.valor_fob) * D(comp.taxa_planejamento)


def exposicao_cambial(comp):
    """Soma, na moeda base, do que é efetivamente pago em moeda estrangeira.

    É a base correta da reserva cambial: tributos são apurados em BRL sobre o
    valor aduaneiro já convertido na taxa da DI, então não têm exposição — e
    incluí-los infla a reserva sem cobrir risco nenhum.
    """
    total = D(comp.valor_fob)
    for l in comp.lancamentos:
        if not l.ativo or not l.aplicavel:
            continue
        if l.tipo_calculo == "montante" and (l.moeda or "") in MOEDAS_ESTRANGEIRAS:
            total += D(l.valor_moeda)
    return total


def orcado(lanc, comp):
    """Valor orçado da linha, em BRL. None quando a linha não foi estimada."""
    if not lanc.aplicavel:
        return ZERO
    tipo = lanc.tipo_calculo or "montante"
    taxa = D(comp.taxa_planejamento)

    if tipo == "fob":
        return fob_brl(comp)
    if tipo == "montante":
        v = D(lanc.valor_moeda)
        return v if (lanc.moeda or "BRL") == "BRL" else v * taxa
    if tipo == "percentual":
        return D(lanc.aliquota) / CEM * fob_brl(comp)
    if tipo == "reserva":
        return D(lanc.aliquota) / CEM * exposicao_cambial(comp) * taxa
    if tipo == "horas":
        custo = (comp.custo_hora_engenharia if lanc.perfil_hora == "eng"
                 else comp.custo_hora_producao)
        return D(lanc.horas) * D(custo)
    return ZERO


def realizado(lanc, comp):
    """Valor realizado da linha, em BRL. None quando ainda não foi lançado.

    A mercadoria é o único caso convertido na hora: o realizado dela é o mesmo
    FOB à taxa da DI. Todo o resto chega já em BRL (é assim que a DI vem).
    """
    if lanc.tipo_calculo == "fob":
        if comp.taxa_realizada is None:
            return None
        return D(comp.valor_fob) * D(comp.taxa_realizada)
    if lanc.realizado_valor_brl is None:
        return None
    return D(lanc.realizado_valor_brl)


# ── CÁLCULO DA COMPOSIÇÃO ─────────────────────────────────────────────────────

def calcular(comp):
    """Devolve os totais e indicadores da composição, já em float para JSON.

    Três distinções que parecem detalhe e não são:

    * **efetivo ≠ realizado.** `cogs_realizado` soma só o que de fato foi
      lançado — se nada chegou, é `None`, não zero. Mas o *custo unitário* usa o
      valor efetivo (realizado quando existe, orçado quando não), senão uma
      composição recém-criada mostraria custo zero e margem de 100%.
    * **o desvio só compara o comparável.** Subtrair o orçado inteiro de um
      realizado parcial produziria um desvio negativo enorme enquanto a DI não
      chega. Aqui ele soma apenas as linhas que têm os dois lados.
    * **o payback usa o NRE efetivo**, pela mesma razão do primeiro item.
    """
    nre_orc = nre_efet = cogs_orc = cogs_efet = ZERO
    cogs_real = orc_comparavel = ZERO
    tem_realizado = False
    linhas = []

    for l in comp.lancamentos:
        if not l.ativo:
            continue
        o = orcado(l, comp)
        r = realizado(l, comp)
        linhas.append({
            "id": l.id,
            "natureza": l.natureza,
            "subcategoria": l.subcategoria or "",
            "categoria": l.categoria or "",
            "orcado": f2(o),
            "realizado": f2(r) if r is not None else None,
            "desvio": f2(r - o) if r is not None else None,
        })
        efetivo = o if r is None else r
        if l.natureza == "nre":
            nre_orc += o
            nre_efet += efetivo
        else:
            cogs_orc += o
            cogs_efet += efetivo
            if r is not None:
                tem_realizado = True
                cogs_real += r
                orc_comparavel += o

    volume = max(1, int(comp.volume_projetado or 1))
    nre_unit = nre_efet / Decimal(volume)
    custo_unit = cogs_efet + nre_unit
    preco = D(comp.preco_venda) if comp.preco_venda is not None else None

    margem_r = margem_p = payback = None
    if preco and preco > ZERO:
        margem_r = preco - custo_unit
        margem_p = margem_r / preco
        if margem_r > ZERO:
            payback = nre_efet / margem_r

    desvio = (cogs_real - orc_comparavel) if tem_realizado else None
    desvio_pct = (desvio / orc_comparavel) if (tem_realizado and orc_comparavel) else None

    return {
        "nre_orcado": f2(nre_orc),
        "nre_realizado": f2(nre_efet),
        "nre_unitario": f2(nre_unit),
        "cogs_orcado": f2(cogs_orc),
        "cogs_efetivo": f2(cogs_efet),
        "cogs_realizado": f2(cogs_real) if tem_realizado else None,
        "custo_unitario": f2(custo_unit),
        "preco_venda": f2(preco) if preco is not None else None,
        "margem_valor": f2(margem_r) if margem_r is not None else None,
        "margem_pct": round(float(margem_p), 4) if margem_p is not None else None,
        "payback_unidades": round(float(payback), 3) if payback is not None else None,
        "desvio": f2(desvio) if desvio is not None else None,
        "desvio_pct": round(float(desvio_pct), 4) if desvio_pct is not None else None,
        "exposicao_cambial": f2(exposicao_cambial(comp)),
        "volume_projetado": volume,
        "linhas": linhas,
    }


def recalcular_linha(lanc, comp):
    """Persiste `valor_brl` e congela a taxa usada. Chamar após criar/editar."""
    lanc.valor_brl = q2(orcado(lanc, comp))
    if (lanc.tipo_calculo in ("fob", "percentual", "reserva")
            or (lanc.tipo_calculo == "montante" and (lanc.moeda or "BRL") != "BRL")):
        lanc.taxa_aplicada = D(comp.taxa_planejamento)
        lanc.taxa_data = comp.taxa_planejamento_data or ""
        lanc.taxa_fonte = "planejamento"
    return lanc


# ── DIAGNÓSTICO (aba Saúde) ───────────────────────────────────────────────────

PESO_SEVERIDADE = {"falha": 3, "aviso": 2, "obs": 1}


def _razao(bons, total):
    return 1.0 if not total else bons / float(total)


def diagnostico(composicoes, referencia=None, referencia_data=None, hoje_iso=None):
    """Verificações contínuas sobre o que torna um custo defensável.

    Cada verificação devolve a fração do que passa (`frac`), não um booleano:
    "3 de 4 composições sem preço" não pode pesar igual a "tudo quebrado". O
    índice pondera essa fração pela gravidade.
    """
    comps = list(composicoes)
    n = len(comps)
    checks = []

    def add(cid, sev, titulo, qtd, detalhe, frac, alvo):
        checks.append({
            "id": cid, "severidade": sev, "titulo": titulo, "quantidade": qtd,
            "detalhe": detalhe, "frac": round(frac, 4), "ok": qtd == 0, "alvo": alvo,
        })

    # 1. Câmbio dentro da política
    fora = []
    if referencia:
        ref = D(referencia)
        for c in comps:
            tp = D(c.taxa_planejamento)
            if ref > ZERO and abs((tp - ref) / ref) > Decimal(str(LIMITE_DESVIO_CAMBIO)):
                fora.append(c)
        add("cambio", "aviso", "Câmbio dentro da política", len(fora),
            (f"{len(fora)} de {n} composições estão a mais de "
             f"{LIMITE_DESVIO_CAMBIO:.0%} da referência de mercado. Folga é legítima "
             f"como política — o aviso pede revisão a cada ciclo.")
            if fora else
            f"Todas as taxas travadas estão a menos de {LIMITE_DESVIO_CAMBIO:.0%} da referência.",
            _razao(n - len(fora), n), "cotacoes")

    # 2. Preço de venda cadastrado
    sem_preco = [c for c in comps if not c.preco_venda]
    add("preco", "aviso", "Preço de venda cadastrado", len(sem_preco),
        f"{len(sem_preco)} de {n} composições sem preço — ficam de fora do "
        f"comparativo de rentabilidade." if sem_preco else
        "Todas as composições têm preço de venda.",
        _razao(n - len(sem_preco), n), "composicoes")

    # 3. Esforço interno precificado
    com_hora = [c for c in comps
                if any(l.ativo and l.aplicavel and l.tipo_calculo == "horas"
                       for l in c.lancamentos)]
    sem_hora = [c for c in com_hora
                if not D(c.custo_hora_engenharia) and not D(c.custo_hora_producao)]
    add("hora", "falha", "Esforço interno precificado", len(sem_hora),
        f"{len(sem_hora)} de {len(com_hora)} composições com lançamento por hora "
        f"estão com custo/hora zerado — o esforço da equipe não entra no NRE."
        if sem_hora else "Custo/hora definido onde há lançamento por hora.",
        _razao(len(com_hora) - len(sem_hora), len(com_hora)), "composicoes")

    # 4 e 5. Confiança e procedência dos lançamentos
    total_l = baixa = sem_proc = 0
    for c in comps:
        for l in c.lancamentos:
            if not l.ativo or not l.aplicavel:
                continue
            total_l += 1
            if l.confianca == "baixa":
                baixa += 1
            if not l.procedencia:
                sem_proc += 1
    add("confianca", "obs", "Confiança dos lançamentos", baixa,
        f"{baixa} de {total_l} lançamentos aplicáveis são estimativa de confiança "
        f"baixa. Revisar antes de congelar a próxima versão." if baixa else
        "Nenhum lançamento aplicável está em confiança baixa.",
        _razao(total_l - baixa, total_l), "composicoes")
    add("procedencia", "obs", "Procedência registrada", sem_proc,
        f"{sem_proc} de {total_l} lançamentos aplicáveis sem procedência — não dá "
        f"para dizer de onde veio o número." if sem_proc else
        f"Todos os {total_l} lançamentos aplicáveis têm procedência.",
        _razao(total_l - sem_proc, total_l), "composicoes")

    # 6. Ciclo fechado contra a DI
    sem_real = [c for c in comps
                if not any(l.ativo and l.realizado_valor_brl is not None
                           for l in c.lancamentos)]
    add("realizado", "aviso", "Ciclo fechado contra a DI", len(sem_real),
        f"{len(sem_real)} de {n} composições ainda sem realizado lançado — o "
        f"desvio não pode ser medido." if sem_real else
        "Todas as composições têm realizado lançado.",
        _razao(n - len(sem_real), n), "composicoes")

    # 7. Composições publicadas
    rasc = [c for c in comps if c.status == "rascunho"]
    add("rascunho", "obs", "Composições publicadas", len(rasc),
        f"{len(rasc)} de {n} composições em rascunho — não entram nos totais do "
        f"portfólio." if rasc else "Nenhuma composição pendente de publicação.",
        _razao(n - len(rasc), n), "composicoes")

    # 8. Cotação sincronizada
    sinc = bool(referencia_data and hoje_iso and referencia_data == hoje_iso)
    add("cotacao", "obs", "Cotação sincronizada hoje", 0 if sinc else 1,
        f"PTAX de {referencia_data} já no banco." if sinc else
        (f"Última sincronização em {referencia_data}. A PTAX publica em dia útil, "
         f"no fim da tarde." if referencia_data else
         "Sem cotação sincronizada — o registro manual segue disponível."),
        1.0 if sinc else 0.0, "cotacoes")

    peso_total = sum(PESO_SEVERIDADE[c["severidade"]] for c in checks)
    peso_bom = sum(PESO_SEVERIDADE[c["severidade"]] * c["frac"] for c in checks)
    indice = round(peso_bom / peso_total * 100) if peso_total else 100

    return {
        "indice": indice,
        "verificacoes": checks,
        "total": len(checks),
        "ok": sum(1 for c in checks if c["ok"]),
        "falhas": sum(1 for c in checks if not c["ok"] and c["severidade"] == "falha"),
        "avisos": sum(1 for c in checks if not c["ok"] and c["severidade"] == "aviso"),
        "observacoes": sum(1 for c in checks if not c["ok"] and c["severidade"] == "obs"),
    }
