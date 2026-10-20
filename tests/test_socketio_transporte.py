"""Testes: transporte do Socket.IO conforme o servidor que sobe o app.

O waitress da produção não faz WebSocket; oferecer o upgrade ali gerava um
traceback por aba aberta no err.log (ver servidor.websocket_disponivel).
"""
import json
import sys

import pytest
from flask import Flask
from flask_socketio import SocketIO

from servidor import opcoes_transporte, websocket_disponivel


def _handshake(client):
    r = client.get("/socket.io/?EIO=4&transport=polling")
    assert r.status_code == 200, r.data
    corpo = r.get_data(as_text=True)
    assert corpo.startswith("0"), corpo          # pacote OPEN do engineio
    return json.loads(corpo[1:])


@pytest.fixture
def sem_override(monkeypatch):
    monkeypatch.delenv("DOCTRACK_WEBSOCKET", raising=False)


def test_waitress_desliga_o_websocket(monkeypatch, sem_override):
    monkeypatch.setitem(sys.modules, "waitress", sys)   # basta estar importado
    assert websocket_disponivel() is False


def test_sem_waitress_mantem_o_websocket(monkeypatch, sem_override):
    monkeypatch.delitem(sys.modules, "waitress", raising=False)
    assert websocket_disponivel() is True


@pytest.mark.parametrize("valor, esperado", [("0", False), ("false", False), ("off", False),
                                             ("1", True), ("true", True), ("on", True)])
def test_variavel_forca_a_decisao(monkeypatch, valor, esperado):
    monkeypatch.setitem(sys.modules, "waitress", sys)
    monkeypatch.setenv("DOCTRACK_WEBSOCKET", valor)
    assert websocket_disponivel() is esperado


def _servidor(websocket):
    app = Flask(__name__)
    SocketIO(app, async_mode="threading", **opcoes_transporte(websocket))
    return app.test_client()


def test_sem_websocket_handshake_nao_anuncia_upgrade():
    assert _handshake(_servidor(False))["upgrades"] == []


def test_pedido_de_websocket_sem_suporte_leva_400_e_nao_estoura():
    r = _servidor(False).get("/socket.io/?EIO=4&transport=websocket")
    assert r.status_code == 400


def test_com_websocket_handshake_anuncia_upgrade():
    assert _handshake(_servidor(True))["upgrades"] == ["websocket"]


def test_app_real_nos_testes_segue_com_websocket(client):
    # A suíte não roda sob waitress: o app de verdade anuncia o upgrade.
    assert _handshake(client)["upgrades"] == ["websocket"]


def test_clientes_comecam_por_polling():
    """Nenhum cliente pode pedir websocket primeiro: sob waitress, cada aba
    aberta voltaria a gerar uma tentativa recusada."""
    import pathlib
    import re
    raiz = pathlib.Path(__file__).resolve().parent.parent
    arquivos = [raiz / "static" / "entregaveis.js", raiz / "static" / "missoes.js",
                raiz / "static" / "socket-client.js", raiz / "pdr" / "static" / "app.js"]
    for arq in arquivos:
        texto = arq.read_text(encoding="utf-8")
        listas = re.findall(r"transports\s*:\s*\[([^\]]*)\]", texto)
        assert listas, f"{arq.name}: sem transports explícito"
        for lst in listas:
            primeiro = lst.split(",")[0].strip().strip("'\"")
            assert primeiro == "polling", f"{arq.name}: começa por {primeiro}"
