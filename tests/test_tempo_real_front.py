"""
O tempo real do front quebrou em silêncio uma vez: a tela de Documentos nunca
ligava o socket (app-realtime.js lia o token de uma chave que não existe mais e
initRealtime() não era chamado por ninguém), e nada no navegador acusava. Estes
testes leem os arquivos e travam os pontos que quebrariam do mesmo jeito.
"""
import os
import re

from event_bus import EventType

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ler(rel):
    with open(os.path.join(RAIZ, rel), encoding="utf-8") as fh:
        return fh.read()


FLUXO = [t for t in EventType.all() if t.startswith("FLUXO_")]


def test_documentos_liga_o_socket_com_o_token_atual():
    rt = ler("static/app-realtime.js")
    assert 'getItem("jwt")' not in rt and "getItem('jwt')" not in rt
    assert "getToken()" in rt
    # As salas de setor são o que faz o técnico receber DOCUMENT_* (ver
    # event_bus._resolve_rooms) — e as únicas que o `subscribe` aceita.
    for sala in ("setor:PRE", "setor:Manuais", "setor:PDE"):
        assert sala in rt


def test_app_avisa_quando_a_tela_esta_pronta():
    app = ler("static/app.js")
    rt = ler("static/app-realtime.js")
    assert "dt:docs-prontos" in app and "__docsProntos" in app
    assert "dt:docs-prontos" in rt and "__docsProntos" in rt


def test_app_realtime_nao_redefine_globais_do_app():
    """Declarado no topo, um `function showToast` aqui vencia o do app.js, que
    carrega antes — era o que acontecia com o modelo antigo."""
    rt = ler("static/app-realtime.js")
    assert not re.search(r"^function\s+\w+", rt, re.M)


def test_cliente_escuta_e_repassa_os_eventos_de_fluxo():
    sc = ler("static/socket-client.js")
    for t in FLUXO:
        assert f'"{t}"' in sc, f"socket-client.js não escuta {t}"
    assert 'new CustomEvent("dt:evento"' in sc


def test_projetos_e_missoes_repassam_os_eventos_de_fluxo():
    for arq in ("static/entregaveis.js", "static/missoes.js"):
        src = ler(arq)
        for t in FLUXO:
            assert f'"{t}"' in src, f"{arq} não escuta {t}"
        assert '"dt:evento"' in src


def test_painel_do_fluxo_e_sino_escutam_o_repasse():
    for arq in ("static/fluxos-painel.js", "static/notificacoes-widget.js"):
        assert '"dt:evento"' in ler(arq), f"{arq} não escuta dt:evento"


def test_pagina_de_fluxos_carrega_o_socket(client):
    html = client.get("/fluxos/").get_data(as_text=True)
    assert "socket.io.min.js" in html and "socket-client.js" in html
