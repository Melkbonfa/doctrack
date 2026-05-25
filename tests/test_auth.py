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
