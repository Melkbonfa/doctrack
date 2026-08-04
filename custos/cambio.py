"""
custos/cambio.py — Sincronização da PTAX com o Banco Central (API Olinda).

Esta é a **primeira chamada HTTP externa do DocTrack**. Não havia precedente de
timeout/retry/cache para copiar, então as regras estão explicitadas aqui:

1. **Falhar é normal e nunca bloqueia.** A rede fabril pode não ter saída
   (`scheduler.py` já registra isso). Toda função devolve lista vazia em erro e
   loga `[WARN]`. O módulo é utilizável com taxa manual; a busca é conveniência.
2. **Timeout curto, sem retry.** Uma tarefa diária que trava seguraria as outras
   da mesma tupla. Se falhou hoje, a janela do dia seguinte recupera o atraso.
3. **Busca uma janela, não "hoje".** A PTAX só publica em dia útil, no fim da
   tarde — e o agendador dispara no primeiro tick após a virada do dia, ou seja,
   sempre *antes* de a cotação daquele dia existir. Pedir só "hoje" não traria
   nada, nunca.
4. **Consolida por data.** O Olinda devolve vários boletins por dia; o que vale
   é o fechamento (o último). Sem isso a série vira ruído intradiário.
5. **Upsert por (moeda, data, tipo).** O agendador guarda estado só em memória:
   um restart no meio do dia refaz a tarefa. A unicidade da tabela é o que
   torna rodar duas vezes inofensivo.

Desligável com `DOCTRACK_CAMBIO=0` (rede sem saída, ou para não bater no BCB em
homologação).
"""
import os
from datetime import date, datetime, timedelta

from models import db
from .models import Cotacao, MOEDAS_ESTRANGEIRAS

BASE_URL = ("https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
            "CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,"
            "dataFinalCotacao=@dataFinalCotacao)")

TIMEOUT = int(os.environ.get("DOCTRACK_CAMBIO_TIMEOUT", "8"))
JANELA_DIAS = int(os.environ.get("DOCTRACK_CAMBIO_JANELA", "15"))


def habilitado():
    return os.environ.get("DOCTRACK_CAMBIO", "1") not in ("0", "false", "False")


def buscar_ptax(moeda, dias=None):
    """Devolve [(date, Decimal-like float)] do fechamento de cada dia útil.

    Lista vazia em qualquer falha — rede, timeout, JSON inesperado ou `requests`
    ausente. Nenhuma exceção escapa: quem chama não deve precisar tratar.
    """
    if not habilitado():
        return []
    if moeda not in MOEDAS_ESTRANGEIRAS:
        return []
    try:
        import requests   # import tardio: o módulo carrega sem a dependência
    except ImportError:
        print("[WARN] Câmbio: 'requests' não instalado — sincronização desativada")
        return []

    dias = dias or JANELA_DIAS
    fim = date.today()
    ini = fim - timedelta(days=dias)
    # A URL é montada à mão de propósito: o Olinda é OData e exige `@` e `$`
    # literais nos parâmetros. Passar isto pelo `params=` do requests os escapa
    # (%40, %24) e a API responde 400.
    url = (f"{BASE_URL}"
           f"?@moeda='{moeda}'"
           f"&@dataInicial='{ini:%m-%d-%Y}'"
           f"&@dataFinalCotacao='{fim:%m-%d-%Y}'"
           f"&$format=json"
           f"&$select=cotacaoVenda,dataHoraCotacao"
           f"&$orderby=dataHoraCotacao%20asc")
    try:
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        linhas = (r.json() or {}).get("value") or []
    except Exception as e:
        print(f"[WARN] Câmbio: falha ao consultar PTAX {moeda} — {e}")
        return []

    # Vários boletins por dia; fica o último (o fechamento).
    por_dia = {}
    for x in linhas:
        carimbo = x.get("dataHoraCotacao") or ""
        venda = x.get("cotacaoVenda")
        if not carimbo or venda is None:
            continue
        dia = carimbo[:10]
        if dia not in por_dia or carimbo > por_dia[dia][0]:
            por_dia[dia] = (carimbo, venda)

    out = []
    for dia in sorted(por_dia):
        try:
            out.append((datetime.strptime(dia, "%Y-%m-%d").date(), float(por_dia[dia][1])))
        except (ValueError, TypeError):
            continue
    return out


def gravar(moeda, serie, tipo="ptax_venda", fonte="bcb_olinda"):
    """Upsert da série. Devolve (novas, atualizadas)."""
    novas = atualizadas = 0
    for dia, valor in serie:
        existente = Cotacao.query.filter_by(moeda=moeda, data=dia, tipo=tipo).first()
        if existente:
            if float(existente.valor) != float(valor):
                existente.valor = valor
                existente.fonte = fonte
                existente.obtido_em = datetime.now()
                atualizadas += 1
        else:
            db.session.add(Cotacao(moeda=moeda, data=dia, tipo=tipo,
                                   valor=valor, fonte=fonte))
            novas += 1
    return novas, atualizadas


def sincronizar(moedas=None, dias=None):
    """Tarefa diária: busca a janela de cada moeda e faz upsert.

    Registrada na tupla de `rodar_tarefas_diarias()` em servidor.py. Idempotente
    por (moeda, data, tipo) — rodar duas vezes no mesmo dia não duplica nada.
    """
    if not habilitado():
        return "desativado (DOCTRACK_CAMBIO=0)"
    resultado = {}
    for moeda in (moedas or MOEDAS_ESTRANGEIRAS):
        serie = buscar_ptax(moeda, dias=dias)
        if not serie:
            resultado[moeda] = "sem dados"
            continue
        novas, atualizadas = gravar(moeda, serie)
        resultado[moeda] = f"{novas} nova(s), {atualizadas} atualizada(s)"
    db.session.commit()
    return resultado


def referencia(moeda="USD", tipo="ptax_venda"):
    """Cotação mais recente no banco. (valor, date) ou (None, None)."""
    c = (Cotacao.query.filter_by(moeda=moeda, tipo=tipo)
         .order_by(Cotacao.data.desc()).first())
    return (float(c.valor), c.data) if c else (None, None)
