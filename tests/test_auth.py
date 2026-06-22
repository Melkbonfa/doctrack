"""Testes de autenticação JWT, login, logout, blocklist."""


def test_login_success_returns_token(client):
    res = client.post("/api/auth/login", json={"email": "admin@test.com", "senha": "admin123"})
    assert res.status_code == 200
    data = res.get_json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["usuario"]["role"] == "admin"


def test_login_wrong_password(client):
    res = client.post("/api/auth/login", json={"email": "admin@test.com", "senha": "errada"})
    assert res.status_code == 401
    assert "erro" in res.get_json()


def test_login_email_inexistente(client):
    res = client.post("/api/auth/login", json={"email": "nope@test.com", "senha": "x"})
    assert res.status_code == 401


def test_login_missing_fields(client):
    res = client.post("/api/auth/login", json={})
    assert res.status_code == 400


def test_protected_endpoint_without_token(client):
    res = client.get("/api/documentos")
    assert res.status_code == 401


def test_logout_revokes_token(client, admin_token, auth_headers):
    # Token funciona antes do logout
    r1 = client.get("/api/documentos", headers=auth_headers(admin_token))
    assert r1.status_code == 200

    # Logout
    r2 = client.post("/api/auth/logout", headers=auth_headers(admin_token))
    assert r2.status_code == 200

    # Token não funciona mais
    r3 = client.get("/api/documentos", headers=auth_headers(admin_token))
    assert r3.status_code == 401


def test_jwt_secret_required(monkeypatch):
    """Importar servidor sem JWT_SECRET (env e .env) levanta RuntimeError."""
    import os, sys, importlib
    
    # Backup do módulo servidor original
    orig_servidor = sys.modules.get("servidor")
    
    monkeypatch.delenv("JWT_SECRET", raising=False)
    # Neutralizar load_dotenv para não recuperar o valor de .env
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)
    
    sys.modules.pop("servidor", None)
    try:
        importlib.import_module("servidor")
        raised = False
    except RuntimeError:
        raised = True
    finally:
        # Restaurar o módulo servidor original
        if orig_servidor:
            sys.modules["servidor"] = orig_servidor
        else:
            sys.modules.pop("servidor", None)
            
    assert raised, "RuntimeError esperado quando JWT_SECRET ausente"


# ── PRIMEIRO ACESSO / CONVITE / RESET ──────────────────────────────────────────

def _criar_convite(client, admin_token, auth_headers, email="novo@test.com"):
    """Admin cria usuário sem senha e devolve (codigo, user_id)."""
    res = client.post("/api/users", headers=auth_headers(admin_token),
                      json={"nome": "Novo User", "email": email, "role": "tecnico"})
    assert res.status_code == 201, res.get_json()
    data = res.get_json()
    return data["codigo_ativacao"], data["usuario"]["id"], data


def test_create_user_sem_senha_gera_codigo(client, admin_token, auth_headers):
    codigo, uid, data = _criar_convite(client, admin_token, auth_headers)
    assert codigo and len(codigo) >= 6
    assert data["usuario"]["precisa_definir_senha"] is True


def test_login_bloqueado_conta_pendente(client, admin_token, auth_headers):
    _criar_convite(client, admin_token, auth_headers, email="pend@test.com")
    res = client.post("/api/auth/login", json={"email": "pend@test.com", "senha": "qualquer"})
    assert res.status_code == 403
    assert res.get_json().get("precisa_definir_senha") is True


def test_primeiro_acesso_com_codigo_correto(client, admin_token, auth_headers):
    codigo, _uid, _ = _criar_convite(client, admin_token, auth_headers, email="ok@test.com")
    res = client.post("/api/auth/primeiro-acesso",
                      json={"email": "ok@test.com", "codigo": codigo, "senha": "novaSenha1"})
    assert res.status_code == 200, res.get_json()
    assert "access_token" in res.get_json()
    # Agora o login normal funciona
    login = client.post("/api/auth/login", json={"email": "ok@test.com", "senha": "novaSenha1"})
    assert login.status_code == 200


def test_primeiro_acesso_codigo_errado(client, admin_token, auth_headers):
    _criar_convite(client, admin_token, auth_headers, email="bad@test.com")
    res = client.post("/api/auth/primeiro-acesso",
                      json={"email": "bad@test.com", "codigo": "ZZZZZZZZ", "senha": "novaSenha1"})
    assert res.status_code == 400


def test_primeiro_acesso_senha_curta(client, admin_token, auth_headers):
    codigo, _uid, _ = _criar_convite(client, admin_token, auth_headers, email="short@test.com")
    res = client.post("/api/auth/primeiro-acesso",
                      json={"email": "short@test.com", "codigo": codigo, "senha": "123"})
    assert res.status_code == 400


def test_reset_senha_admin(client, admin_token, auth_headers):
    # Técnico do seed já tem senha; admin reseta
    users = client.get("/api/users", headers=auth_headers(admin_token)).get_json()
    tecnico = next(u for u in users if u["email"] == "tecnico@test.com")
    res = client.post(f"/api/users/{tecnico['id']}/reset-senha", headers=auth_headers(admin_token))
    assert res.status_code == 200
    codigo = res.get_json()["codigo_ativacao"]
    # Senha antiga não funciona mais
    assert client.post("/api/auth/login",
                       json={"email": "tecnico@test.com", "senha": "demo123"}).status_code == 403
    # Usuário redefine via primeiro acesso
    assert client.post("/api/auth/primeiro-acesso",
                       json={"email": "tecnico@test.com", "codigo": codigo,
                             "senha": "outraSenha1"}).status_code == 200
    assert client.post("/api/auth/login",
                       json={"email": "tecnico@test.com", "senha": "outraSenha1"}).status_code == 200


def test_reset_senha_requer_admin(client, tecnico_token, auth_headers):
    res = client.post("/api/users/1/reset-senha", headers=auth_headers(tecnico_token))
    assert res.status_code == 403


def test_delete_permanente_remove_usuario(client, admin_token, auth_headers):
    _codigo, uid, _ = _criar_convite(client, admin_token, auth_headers, email="del@test.com")
    res = client.delete(f"/api/users/{uid}?permanente=true", headers=auth_headers(admin_token))
    assert res.status_code == 200
    assert "permanentemente" in res.get_json()["mensagem"]
    # Some do da listagem e não loga mais
    users = client.get("/api/users", headers=auth_headers(admin_token)).get_json()
    assert all(u["email"] != "del@test.com" for u in users)
    login = client.post("/api/auth/login", json={"email": "del@test.com", "senha": "x"})
    assert login.status_code == 401


def test_delete_permanente_com_auditoria_vinculada(client, admin_token, auth_headers):
    """Usuário com log de auditoria próprio (FIRST_ACCESS) deve excluir sem violar FK."""
    codigo, uid, _ = _criar_convite(client, admin_token, auth_headers, email="aud@test.com")
    # Gera um AuditLog com usuario_id = aud@test.com
    client.post("/api/auth/primeiro-acesso",
                json={"email": "aud@test.com", "codigo": codigo, "senha": "senhaForte1"})
    res = client.delete(f"/api/users/{uid}?permanente=true", headers=auth_headers(admin_token))
    assert res.status_code == 200


def test_delete_permanente_self_bloqueado(client, admin_token, auth_headers):
    users = client.get("/api/users", headers=auth_headers(admin_token)).get_json()
    admin = next(u for u in users if u["email"] == "admin@test.com")
    res = client.delete(f"/api/users/{admin['id']}?permanente=true", headers=auth_headers(admin_token))
    assert res.status_code == 400


def test_delete_soft_continua_padrao(client, admin_token, auth_headers):
    _codigo, uid, _ = _criar_convite(client, admin_token, auth_headers, email="soft@test.com")
    res = client.delete(f"/api/users/{uid}", headers=auth_headers(admin_token))
    assert res.status_code == 200
    assert "desativado" in res.get_json()["mensagem"]
    # Continua existindo, apenas inativo
    users = client.get("/api/users", headers=auth_headers(admin_token)).get_json()
    alvo = next(u for u in users if u["email"] == "soft@test.com")
    assert alvo["ativo"] is False
