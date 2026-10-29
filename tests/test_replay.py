"""
Replay do tempo real: quem reconecta recebe o que perdeu — e só o que receberia
ao vivo.

`audit_logs` é ao mesmo tempo trilha de auditoria e event store, e guarda mais do
que o barramento emite: as linhas de `log_action` (login, exclusão, acesso
negado) e os eventos de sala restrita (`TEMPO_*` vai só para o dono). Antes, o
`replay_request` e o `GET /api/events/replay` devolviam essa tabela inteira para
qualquer conexão autenticada. O critério agora é o mesmo do envio ao vivo:
`event_bus._resolve_rooms` precisa incluir uma sala da conexão.
"""
import json
from datetime import datetime

import pytest


def _login(client, email, senha="demo123"):
    r = client.post("/api/auth/login", json={"email": email, "senha": senha})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["access_token"]


def _uid(app, email):
    from models import User
    with app.app_context():
        return User.query.filter_by(email=email).first().id


def _ultimo_id(app):
    from models import db, AuditLog
    with app.app_context():
        return db.session.query(db.func.max(AuditLog.id)).scalar() or 0


def _grava(app, acao, payload=None, email="gestor@test.com"):
    """Uma linha como publish_event (payload) ou log_action (sem payload) grava."""
    from models import db, AuditLog
    with app.app_context():
        log = AuditLog(usuario_email=email, acao=acao, entidade="teste",
                       payload_json=json.dumps(payload) if payload is not None else None,
                       timestamp=datetime.now())
        db.session.add(log)
        db.session.commit()
        return log.id


@pytest.fixture
def ws(app):
    from servidor import socketio
    clientes = []

    def _conectar(token):
        c = socketio.test_client(app, flask_test_client=app.test_client(),
                                 auth={"token": token})
        assert c.is_connected()
        c.get_received()                       # descarta o "connected"
        clientes.append(c)
        return c
    yield _conectar
    for c in clientes:
        if c.is_connected():
            c.disconnect()


def _replay(c, since, **extra):
    c.emit("replay_request", dict(since=since, **extra))
    msgs = [m for m in c.get_received() if m["name"] == "replay"]
    assert len(msgs) == 1, msgs
    return msgs[0]["args"][0]


def _tipos(resposta):
    return [(e["event_type"], e["payload"].get("marca")) for e in resposta["events"]]


@pytest.fixture
def cena(app, client):
    """Uma linha de cada tipo de destino, gravadas depois dos logins."""
    toks = {k: _login(client, f"{k}@test.com", "admin123" if k == "admin" else "demo123")
            for k in ("admin", "gestor", "tecnico", "leitura")}
    tec, ges = _uid(app, "tecnico@test.com"), _uid(app, "gestor@test.com")
    since = _ultimo_id(app)
    ids = {
        "tempo_do_gestor": _grava(app, "TEMPO_APONTAMENTO_CREATED", {"user_id": ges, "marca": "tempo-gestor"}),
        "tempo_do_tecnico": _grava(app, "TEMPO_APONTAMENTO_CREATED", {"user_id": tec, "marca": "tempo-tecnico"}),
        "missao": _grava(app, "MISSAO_CARTAO_MOVIDO", {"missao_id": 1, "marca": "missao"}),
        "doc": _grava(app, "DOCUMENT_STATUS_UPDATED", {"documento_id": 7, "setor": "PRE", "marca": "doc"}),
        "login": _grava(app, "LOGIN"),                       # log_action: sem payload
        "nota_tecnico": _grava(app, "NOTIFICATION", {"target_user_id": tec, "marca": "nota-tecnico"}),
        "nota_gestor": _grava(app, "NOTIFICATION", {"target_user_id": ges, "marca": "nota-gestor"}),
    }
    return {"tk": toks, "since": since, "ids": ids, "tec": tec, "ges": ges}


# ── socket ───────────────────────────────────────────────────────────────────

def test_tecnico_so_recebe_o_que_receberia_ao_vivo(cena, ws):
    r = _replay(ws(cena["tk"]["tecnico"]), cena["since"])
    assert _tipos(r) == [("TEMPO_APONTAMENTO_CREATED", "tempo-tecnico"),
                         ("MISSAO_CARTAO_MOVIDO", "missao"),
                         ("NOTIFICATION", "nota-tecnico")]


def test_gestor_recebe_documentos_mas_nao_o_tempo_alheio(cena, ws):
    r = _replay(ws(cena["tk"]["gestor"]), cena["since"])
    marcas = [m for _, m in _tipos(r)]
    assert "doc" in marcas and "tempo-gestor" in marcas and "missao" in marcas
    assert "tempo-tecnico" not in marcas and "nota-tecnico" not in marcas
    assert None not in marcas                         # a linha de LOGIN não sai


def test_admin_recebe_tudo(cena, ws):
    r = _replay(ws(cena["tk"]["admin"]), cena["since"])
    assert [e["event_id"] for e in r["events"]] == sorted(cena["ids"].values())


def test_sala_fina_pedida_no_replay_entra(cena, ws):
    """Ao reconectar, o cliente pede o replay ANTES de se reinscrever nas salas
    finas; por isso elas vão junto no pedido."""
    r = _replay(ws(cena["tk"]["tecnico"]), cena["since"], rooms=["doc:7"])
    assert ("DOCUMENT_STATUS_UPDATED", "doc") in _tipos(r)


def test_sala_ja_assinada_entra(cena, ws):
    c = ws(cena["tk"]["tecnico"])
    c.emit("subscribe", {"rooms": ["setor:PRE"]})
    c.get_received()
    assert ("DOCUMENT_STATUS_UPDATED", "doc") in _tipos(_replay(c, cena["since"]))


def test_sala_que_nao_se_assina_e_ignorada(cena, ws):
    r = _replay(ws(cena["tk"]["tecnico"]), cena["since"],
                rooms=["role:admin", "role:gestor", f"user:{cena['ges']}"])
    marcas = [m for _, m in _tipos(r)]
    assert "tempo-gestor" not in marcas and "nota-gestor" not in marcas and "doc" not in marcas


def test_ate_avanca_mesmo_quando_tudo_e_filtrado(cena, ws):
    """Sem `ate`, o cliente voltaria a pedir as mesmas linhas filtradas a cada
    reconexão — e a varredura recomeçaria do mesmo ponto para sempre."""
    r = _replay(ws(cena["tk"]["leitura"]), cena["since"])
    assert r["events"] == []
    assert r["ate"] == max(cena["ids"].values())


def test_limite_conta_so_o_que_e_entregue(app, cena, ws, monkeypatch):
    import servidor
    monkeypatch.setattr(servidor, "REPLAY_LIMITE", 2)
    for i in range(5):
        _grava(app, "LOGIN")                          # só admin vê
    ultimo = _grava(app, "MISSAO_CARTAO_MOVIDO", {"marca": "depois"})
    r = _replay(ws(cena["tk"]["tecnico"]), cena["since"])
    assert len(r["events"]) == 2
    # Parou no limite: `ate` é o último ENTREGUE, para o resto vir no próximo pedido.
    assert r["ate"] == r["events"][-1]["event_id"]
    r2 = _replay(ws(cena["tk"]["tecnico"]), r["ate"])
    assert [e["event_id"] for e in r2["events"]][-1] == ultimo


# ── HTTP ─────────────────────────────────────────────────────────────────────

def test_rota_http_aplica_o_mesmo_filtro(client, cena):
    H = {"Authorization": f"Bearer {cena['tk']['tecnico']}"}
    r = client.get(f"/api/events/replay?since={cena['since']}", headers=H)
    assert r.status_code == 200
    marcas = [e["payload"].get("marca") for e in r.get_json()["events"]]
    assert marcas == ["tempo-tecnico", "missao", "nota-tecnico"]

    r = client.get(f"/api/events/replay?since={cena['since']}&rooms=doc:7&rooms=role:admin",
                   headers=H)
    marcas = [e["payload"].get("marca") for e in r.get_json()["events"]]
    assert "doc" in marcas and None not in marcas


def test_rota_http_para_admin_traz_tudo(client, cena):
    H = {"Authorization": f"Bearer {cena['tk']['admin']}"}
    eventos = client.get(f"/api/events/replay?since={cena['since']}", headers=H).get_json()["events"]
    assert [e["event_id"] for e in eventos] == sorted(cena["ids"].values())
