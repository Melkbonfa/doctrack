"""Testes de RBAC — quem pode fazer o quê."""


def test_leitura_nao_pode_criar_doc(client, leitura_token, auth_headers):
    res = client.post("/api/documentos",
                      json={"setor": "PRE", "equipamento": "X", "documento": "Y"},
                      headers=auth_headers(leitura_token))
    assert res.status_code == 403


def test_leitura_nao_pode_deletar(client, leitura_token, admin_token, auth_headers):
    docs = client.get("/api/documentos", headers=auth_headers(admin_token)).get_json()
    doc_id = docs[0]["id"]
    res = client.delete(f"/api/documentos/{doc_id}", headers=auth_headers(leitura_token))
    assert res.status_code == 403


def test_tecnico_nao_pode_deletar(client, tecnico_token, admin_token, auth_headers):
    docs = client.get("/api/documentos", headers=auth_headers(admin_token)).get_json()
    doc_id = docs[0]["id"]
    res = client.delete(f"/api/documentos/{doc_id}", headers=auth_headers(tecnico_token))
    assert res.status_code == 403


def test_gestor_pode_deletar(client, gestor_token, auth_headers):
    docs = client.get("/api/documentos", headers=auth_headers(gestor_token)).get_json()
    doc_id = docs[0]["id"]
    res = client.delete(f"/api/documentos/{doc_id}", headers=auth_headers(gestor_token))
    assert res.status_code == 200


def test_tecnico_nao_pode_audit(client, tecnico_token, auth_headers):
    res = client.get("/api/audit", headers=auth_headers(tecnico_token))
    assert res.status_code == 403


def test_leitura_nao_pode_audit(client, leitura_token, auth_headers):
    res = client.get("/api/audit", headers=auth_headers(leitura_token))
    assert res.status_code == 403


def test_gestor_pode_audit(client, gestor_token, auth_headers):
    res = client.get("/api/audit", headers=auth_headers(gestor_token))
    assert res.status_code == 200


def test_reimport_permissao(client, gestor_token, tecnico_token, auth_headers):
    # Técnico não pode fazer reimport
    r1 = client.post("/api/reimport", headers=auth_headers(tecnico_token))
    assert r1.status_code == 403

    # Gestor pode fazer reimport (pode retornar 200 ou 404 se a planilha excel não existir no ambiente de testes, mas não 403)
    r2 = client.post("/api/reimport", headers=auth_headers(gestor_token))
    assert r2.status_code in (200, 404)


def test_tecnico_pode_atualizar_status(client, tecnico_token, admin_token, auth_headers):
    docs = client.get("/api/documentos", headers=auth_headers(admin_token)).get_json()
    doc_id = next(d["id"] for d in docs if d["equipamento"] == "MAQ-B")
    res = client.put(f"/api/documento/{doc_id}/status",
                     json={"status": "Concluído"},
                     headers=auth_headers(tecnico_token))
    assert res.status_code == 200
