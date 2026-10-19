"""Testes da trava de emergência (killswitch.py).

O que estes testes protegem, em ordem de importância:

  1. travado, NADA responde — nem admin, nem página, nem token válido;
  2. `/api/version` continua respondendo (é o health check do Render; se ela
     travasse, a plataforma reiniciaria o serviço em laço e a trava viraria um
     ciclo de reboot);
  3. destravar encerra as sessões antigas E deixa entrar de novo — o segundo
     ponto é fácil de quebrar sem perceber, porque o corte por `iat` pode
     recusar o próprio login feito logo depois do desbloqueio.
"""
import time

import pytest

TOKEN = "token-do-gatilho-para-teste-1234"
SENHA = "senha-mestra-de-teste"


def _virar_o_segundo():
    """Espera o relógio passar do segundo corrente.

    O `iat` do JWT tem resolução de um segundo, então o corte de sessão só
    distingue "antes" de "depois" da trava se houver uma borda de segundo entre
    os dois. Num incidente real sobra tempo — a trava dura minutos; num teste
    tudo acontece no mesmo milissegundo, e sem esta espera o cenário testado
    seria um que não existe em produção.
    """
    agora = time.time()
    time.sleep(1.05 - (agora % 1))


@pytest.fixture
def configurado(app, monkeypatch):
    """Publica os dois segredos no ambiente, como hash bcrypt."""
    from models import bcrypt

    with app.app_context():
        monkeypatch.setenv("DOCTRACK_KILL_TOKEN_HASH",
                           bcrypt.generate_password_hash(TOKEN).decode())
        monkeypatch.setenv("DOCTRACK_UNLOCK_HASH",
                           bcrypt.generate_password_hash(SENHA).decode())
    yield


@pytest.fixture
def travar(client, configurado):
    def _travar(motivo="teste"):
        res = client.post("/api/kill-switch/lock",
                          json={"motivo": motivo},
                          headers={"X-Kill-Token": TOKEN})
        assert res.status_code == 200, res.get_json()
        return res
    return _travar


# ── ESTADO E CONFIGURAÇÃO ─────────────────────────────────────────────────────

def test_status_e_publico_e_nasce_destravado(client):
    res = client.get("/api/kill-switch/status")
    assert res.status_code == 200
    assert res.get_json()["travado"] is False


def test_sem_segredos_no_ambiente_o_gatilho_recusa_travar(client, monkeypatch):
    """Travar sem senha de desbloqueio cadastrada seria destruir o sistema."""
    monkeypatch.delenv("DOCTRACK_KILL_TOKEN_HASH", raising=False)
    monkeypatch.delenv("DOCTRACK_UNLOCK_HASH", raising=False)

    res = client.post("/api/kill-switch/lock", headers={"X-Kill-Token": "qualquer"})
    assert res.status_code == 503
    assert client.get("/api/kill-switch/status").get_json()["travado"] is False


def test_so_o_token_do_gatilho_trava(client, configurado):
    res = client.post("/api/kill-switch/lock", headers={"X-Kill-Token": "errado"})
    assert res.status_code == 401
    assert client.get("/api/kill-switch/status").get_json()["travado"] is False


# ── EFEITO DA TRAVA ───────────────────────────────────────────────────────────

def test_travado_barra_ate_o_admin(client, admin_token, auth_headers, travar):
    # Antes: passa normalmente.
    assert client.get("/api/data", headers=auth_headers(admin_token)).status_code == 200

    travar()

    res = client.get("/api/data", headers=auth_headers(admin_token))
    assert res.status_code == 423
    assert res.get_json()["travado"] is True


def test_travado_barra_o_proprio_login(client, travar):
    travar()
    res = client.post("/api/auth/login",
                      json={"email": "admin@test.com", "senha": "admin123"})
    assert res.status_code == 423


def test_travado_as_paginas_viram_tela_de_bloqueio(client, travar):
    travar(motivo="credencial vazada")
    res = client.get("/equipamentos")
    assert res.status_code == 423
    corpo = res.get_data(as_text=True)
    assert "Sistema travado" in corpo
    assert "credencial vazada" in corpo          # o motivo chega a quem vê a tela


def test_travado_o_health_check_continua_respondendo(client, travar):
    """Se /api/version travasse, o Render reiniciaria o serviço em laço."""
    travar()
    assert client.get("/api/version").status_code == 200


def test_travado_a_tela_de_desbloqueio_continua_acessivel(client, travar):
    travar()
    res = client.get("/travado")
    assert res.status_code == 423
    assert "Senha de desbloqueio" in res.get_data(as_text=True)


# ── DESBLOQUEIO ───────────────────────────────────────────────────────────────

def test_senha_errada_nao_destrava(client, travar):
    travar()
    res = client.post("/api/kill-switch/unlock", json={"senha": "chute"})
    assert res.status_code == 401
    assert client.get("/api/kill-switch/status").get_json()["travado"] is True


def test_senha_certa_destrava_e_o_sistema_volta(client, travar):
    travar()
    _virar_o_segundo()
    res = client.post("/api/kill-switch/unlock", json={"senha": SENHA})
    assert res.status_code == 200

    assert client.get("/api/kill-switch/status").get_json()["travado"] is False
    # E dá para entrar de novo — o corte por `iat` não pode recusar o primeiro
    # login feito logo após o desbloqueio.
    novo = client.post("/api/auth/login",
                       json={"email": "admin@test.com", "senha": "admin123"})
    assert novo.status_code == 200
    token = novo.get_json()["access_token"]
    assert client.get("/api/data",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_desbloqueio_encerra_as_sessoes_anteriores(client, admin_token, auth_headers, travar):
    """O token de antes da trava não volta a valer depois dela."""
    travar()
    _virar_o_segundo()
    client.post("/api/kill-switch/unlock", json={"senha": SENHA})

    res = client.get("/api/data", headers=auth_headers(admin_token))
    assert res.status_code in (401, 422)


# ── FORÇA BRUTA ───────────────────────────────────────────────────────────────

def test_tentativas_de_desbloqueio_sao_limitadas(client, travar):
    travar()
    for _ in range(3):
        assert client.post("/api/kill-switch/unlock",
                           json={"senha": "chute"}).status_code == 401

    res = client.post("/api/kill-switch/unlock", json={"senha": "chute"})
    assert res.status_code == 429
    # E o limite não abre uma brecha: a senha certa também espera a janela.
    assert client.post("/api/kill-switch/unlock",
                       json={"senha": SENHA}).status_code == 429


def test_unlock_sem_trava_previa_nao_derruba_as_sessoes(client, configurado,
                                                        tecnico_token):
    """Destravar um sistema que nunca travou não pode ser um apagão.

    `_corte_de_sessao` se ancora em `travado_em`; sem trava anterior esse valor é
    None e o corte caía sobre `agora`, invalidando TODA sessão viva. A rota é a
    porta mais exposta do sistema (responde travado), então chamá-la fora de um
    incidente precisa ser inócuo.
    """
    import killswitch

    h = {"Authorization": f"Bearer {tecnico_token}"}
    assert client.get("/tempos/api/atual", headers=h).status_code == 200

    res = client.post("/api/kill-switch/unlock", json={"senha": SENHA})
    assert res.status_code == 200
    assert res.get_json()["travado"] is False

    killswitch.invalidar_cache()
    assert client.get("/tempos/api/atual", headers=h).status_code == 200, \
        "unlock sem trava prévia revogou os tokens de todo mundo"


# ── AUDITORIA DAS TENTATIVAS RECUSADAS ────────────────────────────────────────

IP_ATACANTE = "10.66.6.6"


def _auditoria(acao):
    from models import AuditLog
    return AuditLog.query.filter_by(acao=acao).order_by(AuditLog.id).all()


def _nenhuma_coluna_contem(segredo):
    from models import AuditLog
    for linha in AuditLog.query.all():
        for coluna in AuditLog.__table__.columns:
            assert segredo not in str(getattr(linha, coluna.name) or ""), \
                f"segredo gravado em audit_logs.{coluna.name} ({linha.acao})"


def test_token_errado_no_gatilho_vai_para_a_auditoria(client, configurado):
    chute = "chute-de-token-bem-especifico"
    res = client.post("/api/kill-switch/lock", headers={"X-Kill-Token": chute},
                      environ_base={"REMOTE_ADDR": IP_ATACANTE})
    assert res.status_code == 401

    [linha] = _auditoria("KILL_SWITCH_LOCK_FALHA")
    assert linha.ip == IP_ATACANTE
    assert linha.usuario_email == "kill-switch"
    _nenhuma_coluna_contem(chute)


def test_senha_errada_no_desbloqueio_vai_para_a_auditoria(client, travar):
    travar()
    chute = "chute-de-senha-bem-especifico"
    res = client.post("/api/kill-switch/unlock", json={"senha": chute},
                      environ_base={"REMOTE_ADDR": IP_ATACANTE})
    assert res.status_code == 401

    [linha] = _auditoria("KILL_SWITCH_UNLOCK_FALHA")
    assert linha.ip == IP_ATACANTE
    _nenhuma_coluna_contem(chute)


def test_bloqueio_do_desbloqueio_grava_uma_linha_so(client, travar):
    travar()
    for _ in range(3):
        client.post("/api/kill-switch/unlock", json={"senha": "chute"},
                    environ_base={"REMOTE_ADDR": IP_ATACANTE})
    for _ in range(4):
        assert client.post("/api/kill-switch/unlock", json={"senha": "chute"},
                           environ_base={"REMOTE_ADDR": IP_ATACANTE}).status_code == 429

    assert len(_auditoria("KILL_SWITCH_UNLOCK_FALHA")) == 3
    [bloqueio] = _auditoria("KILL_SWITCH_BLOQUEADO")
    assert bloqueio.ip == IP_ATACANTE
    assert bloqueio.valor_novo == "limite do unlock"
