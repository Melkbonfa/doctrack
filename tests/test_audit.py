"""Testes do audit log (F5/F6)."""


def test_audit_lista_logs_de_login(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    logs = client.get("/api/audit", headers=h).get_json()
    assert any(l["acao"] == "LOGIN" for l in logs)


def test_audit_documento_id_invalido_retorna_400(client, admin_token, auth_headers):
    res = client.get("/api/audit?documento_id=abc", headers=auth_headers(admin_token))
    assert res.status_code == 400
    assert "documento_id" in res.get_json()["erro"].lower()


def test_audit_documento_id_numerico_funciona(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    res = client.get("/api/audit?documento_id=1", headers=h)
    assert res.status_code == 200


def test_audit_busca_em_valor_antigo(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    # Criar um audit com valor_antigo conhecido (UPDATE)
    docs = client.get("/api/documentos", headers=h).get_json()
    doc_id = docs[0]["id"]
    client.patch(f"/api/documentos/{doc_id}",
                 json={"versao": "9.9-NEW-MARCADO"}, headers=h)

    res = client.get("/api/audit?q=NEW-MARCADO", headers=h)
    assert res.status_code == 200
    logs = res.get_json()
    assert any("9.9-NEW-MARCADO" in (l.get("valor_novo") or "") for l in logs)


def test_audit_filtro_por_acao(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    res = client.get("/api/audit?acao=LOGIN", headers=h)
    logs = res.get_json()
    assert all(l["acao"] == "LOGIN" for l in logs)


def test_audit_limit_invalido_retorna_400(client, admin_token, auth_headers):
    res = client.get("/api/audit?limit=abc", headers=auth_headers(admin_token))
    assert res.status_code == 400
