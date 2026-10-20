"""Revogação imediata: desativar, excluir ou mudar o perfil corta o acesso na
hora (Análise de Riscos, R-46).

Antes, require_role decidia pelo perfil gravado no JWT, e o access token de uma
conta desativada (ou rebaixada) valia até vencer — até 1 hora. O POP de
controle de acesso precisava avisar disso. O que estes testes fixam:

  * conta inativa ou excluída: access e refresh recusados (401) na requisição
    seguinte, inclusive quando a desativação não passou pela API;
  * perfil trocado: o access token antigo é recusado, o refresh devolve um token
    com o perfil novo, sem novo login;
  * as conexões de tempo real abertas da conta caem junto.
"""
import pytest

from models import db, User

H = lambda token: {"Authorization": f"Bearer {token}"}   # noqa: E731


def _login(client, email, senha="demo123"):
    res = client.post("/api/auth/login", json={"email": email, "senha": senha})
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def _uid(email):
    return User.query.filter_by(email=email).first().id


def _renova(client, refresh):
    return client.post("/api/auth/refresh", headers=H(refresh))


# ── desativação e exclusão ────────────────────────────────────────────────────

def test_desativar_corta_o_access_token_na_hora(client, admin_token):
    sessao = _login(client, "tecnico@test.com")
    assert client.get("/api/documentos", headers=H(sessao["access_token"])).status_code == 200

    assert client.delete(f"/api/users/{_uid('tecnico@test.com')}",
                         headers=H(admin_token)).status_code == 200

    assert client.get("/api/documentos", headers=H(sessao["access_token"])).status_code == 401
    assert _renova(client, sessao["refresh_token"]).status_code == 401


def test_desativar_pela_edicao_tambem_corta(client, admin_token):
    sessao = _login(client, "gestor@test.com")
    assert client.patch(f"/api/users/{_uid('gestor@test.com')}", json={"ativo": False},
                        headers=H(admin_token)).status_code == 200
    # rota de perfil (require_role) e rota só autenticada (jwt_required)
    assert client.get("/api/users", headers=H(sessao["access_token"])).status_code == 401
    assert client.get("/api/auth/me", headers=H(sessao["access_token"])).status_code == 401


def test_desativacao_fora_da_api_tambem_corta(client):
    """A checagem é por requisição, não um gatilho da tela de usuários."""
    sessao = _login(client, "tecnico@test.com")
    User.query.filter_by(email="tecnico@test.com").first().ativo = False
    db.session.commit()
    assert client.get("/api/documentos", headers=H(sessao["access_token"])).status_code == 401


def test_excluir_de_vez_corta(client, admin_token):
    sessao = _login(client, "leitura@test.com")
    assert client.delete(f"/api/users/{_uid('leitura@test.com')}?permanente=true",
                         headers=H(admin_token)).status_code == 200
    assert client.get("/api/documentos", headers=H(sessao["access_token"])).status_code == 401


def test_trocar_o_email_invalida_os_tokens_do_email_antigo(client, admin_token):
    sessao = _login(client, "tecnico@test.com")
    assert client.patch(f"/api/users/{_uid('tecnico@test.com')}",
                        json={"email": "tecnico.novo@test.com"},
                        headers=H(admin_token)).status_code == 200
    assert client.get("/api/documentos", headers=H(sessao["access_token"])).status_code == 401
    assert _renova(client, sessao["refresh_token"]).status_code == 401


def test_reset_de_senha_nao_derruba_quem_esta_logado(client, admin_token):
    """Fora do escopo do R-46: o reset invalida a senha, não a sessão aberta.
    Fixado aqui para que uma mudança nisso seja decisão, não efeito colateral."""
    sessao = _login(client, "tecnico@test.com")
    assert client.post(f"/api/users/{_uid('tecnico@test.com')}/reset-senha",
                       headers=H(admin_token)).status_code == 200
    assert client.get("/api/documentos", headers=H(sessao["access_token"])).status_code == 200


# ── troca de perfil ───────────────────────────────────────────────────────────

def test_rebaixar_recusa_o_token_antigo_e_o_refresh_traz_o_perfil_novo(client, admin_token):
    sessao = _login(client, "gestor@test.com")
    assert client.get("/api/users", headers=H(sessao["access_token"])).status_code == 200

    assert client.patch(f"/api/users/{_uid('gestor@test.com')}", json={"role": "leitura"},
                        headers=H(admin_token)).status_code == 200

    # o token que dizia "gestor" não vale mais...
    assert client.get("/api/users", headers=H(sessao["access_token"])).status_code == 401
    # ...o refresh continua valendo e devolve um token com o perfil do banco
    res = _renova(client, sessao["refresh_token"])
    assert res.status_code == 200
    novo = res.get_json()["access_token"]
    assert client.get("/api/users", headers=H(novo)).status_code == 403
    assert client.get("/api/documentos", headers=H(novo)).status_code == 200


def test_promover_tambem_renova_pelo_refresh(client, admin_token):
    sessao = _login(client, "leitura@test.com")
    assert client.patch(f"/api/users/{_uid('leitura@test.com')}", json={"role": "gestor"},
                        headers=H(admin_token)).status_code == 200
    assert client.get("/api/users", headers=H(sessao["access_token"])).status_code == 401
    novo = _renova(client, sessao["refresh_token"]).get_json()["access_token"]
    assert client.get("/api/users", headers=H(novo)).status_code == 200


def test_mudar_so_nome_ou_area_nao_derruba_ninguem(client, admin_token):
    sessao = _login(client, "tecnico@test.com")
    assert client.patch(f"/api/users/{_uid('tecnico@test.com')}",
                        json={"nome": "Outro Nome", "areas": ["pdr"]},
                        headers=H(admin_token)).status_code == 200
    assert client.get("/api/documentos", headers=H(sessao["access_token"])).status_code == 200


# ── tempo real ────────────────────────────────────────────────────────────────

@pytest.fixture
def socketio_client(app):
    from servidor import socketio
    clientes = []

    def _conectar(token):
        c = socketio.test_client(app, flask_test_client=app.test_client(),
                                 auth={"token": token})
        clientes.append(c)
        return c
    yield _conectar
    for c in clientes:
        if c.is_connected():
            c.disconnect()


def test_desativar_derruba_a_conexao_de_tempo_real(client, admin_token, socketio_client):
    sessao = _login(client, "tecnico@test.com")
    ws = socketio_client(sessao["access_token"])
    assert ws.is_connected()
    outro = socketio_client(_login(client, "gestor@test.com")["access_token"])

    assert client.delete(f"/api/users/{_uid('tecnico@test.com')}",
                         headers=H(admin_token)).status_code == 200

    assert not ws.is_connected()
    assert outro.is_connected()            # só a conta desativada cai
    # e não volta: o handshake recusa a conta inativa
    assert not socketio_client(sessao["access_token"]).is_connected()


def test_trocar_perfil_derruba_a_conexao_para_reentrar_na_sala_certa(
        client, admin_token, socketio_client):
    sessao = _login(client, "gestor@test.com")
    ws = socketio_client(sessao["access_token"])
    assert ws.is_connected()
    assert client.patch(f"/api/users/{_uid('gestor@test.com')}", json={"role": "tecnico"},
                        headers=H(admin_token)).status_code == 200
    assert not ws.is_connected()

    novo = _renova(client, sessao["refresh_token"]).get_json()["access_token"]
    ws2 = socketio_client(novo)
    assert ws2.is_connected()
    conectado = [m for m in ws2.get_received() if m["name"] == "connected"][0]["args"][0]
    assert "role:tecnico" in conectado["rooms"]
