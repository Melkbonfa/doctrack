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


# ── IP DE ORIGEM ──────────────────────────────────────────────────────────────
# O IP sempre foi gravado em audit_logs.ip, mas nem a tela nem o relatório o
# mostravam — numa tentativa de acesso recusada, é o dado que mais importa.

IP = "10.20.30.40"


def _login_de(client, ip, email="gestor@test.com", senha="demo123"):
    return client.post("/api/auth/login", json={"email": email, "senha": senha},
                       environ_base={"REMOTE_ADDR": ip})


def test_audit_mostra_o_ip(client, admin_token, auth_headers):
    _login_de(client, IP, senha="errada")
    logs = client.get("/api/audit", headers=auth_headers(admin_token)).get_json()
    falha = next(l for l in logs if l["acao"] == "LOGIN_FALHA")
    assert falha["ip"] == IP
    assert falha["usuario"] == "gestor@test.com"


def test_audit_busca_por_ip(client, admin_token, auth_headers):
    _login_de(client, IP)
    logs = client.get(f"/api/audit?q={IP}", headers=auth_headers(admin_token)).get_json()
    assert logs and all(l["ip"] == IP for l in logs)


def test_export_audit_inclui_o_ip(client, admin_token, auth_headers):
    _login_de(client, IP)
    res = client.get("/api/export/audit", headers=auth_headers(admin_token))
    assert res.status_code == 200
    assert f'"IP": "{IP}"' in res.get_data(as_text=True)


def test_export_audit_nao_deixa_o_email_digitado_fechar_o_script(client, admin_token,
                                                                  auth_headers):
    """O e-mail de uma LOGIN_FALHA é texto de quem nem tem conta, gravado como
    veio, e o relatório o embute num <script> — numa página com o JWT na URL."""
    import os
    hostil = "</script><script>alert(document.location)</script>@x.com"
    assert _login_de(client, IP, email=hostil, senha="x").status_code == 401

    corpo = client.get("/api/export/audit",
                       headers=auth_headers(admin_token)).get_data(as_text=True)

    modelo = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "templates", "audit_log_report.html")
    with open(modelo, encoding="utf-8") as f:
        fechamentos_do_modelo = f.read().count("</script>")
    assert corpo.count("</script>") == fechamentos_do_modelo
    assert "<script>alert" not in corpo
    # E o dado continua lá, só escapado — o JS lê \u003c como "<".
    assert "\\u003c/script\\u003e\\u003cscript\\u003ealert" in corpo
