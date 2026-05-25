"""Testes do audit log."""


def test_audit_lista_logs_de_login(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    logs = client.get("/api/audit", headers=h).get_json()
    assert any(l["acao"] == "LOGIN" for l in logs)


def test_audit_busca_por_usuario(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    # login gera logs com usuário "admin@test.com"
    res = client.get("/api/audit?q=admin", headers=h)
    assert res.status_code == 200
    logs = res.get_json()
    assert len(logs) >= 1
    assert all("admin" in l["usuario"].lower() for l in logs)


def test_audit_filtro_por_acao(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    res = client.get("/api/audit?acao=LOGIN", headers=h)
    logs = res.get_json()
    assert all(l["acao"] == "LOGIN" for l in logs)


def test_audit_limit_invalido_retorna_400(client, admin_token, auth_headers):
    res = client.get("/api/audit?limit=abc", headers=auth_headers(admin_token))
    assert res.status_code == 400
