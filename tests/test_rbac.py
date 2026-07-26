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


def test_reimport_nao_existe_mais(client, gestor_token, admin_token, auth_headers):
    """A rota que dropava as tabelas de documentos foi removida.

    Ela aceitava qualquer gestor e apagava `documentos` + `documento_historico`
    para reinserir a planilha. O teste antigo garantia que gestor conseguia
    chamá-la; este garante que ninguém consegue — nem o admin.
    """
    for token in (gestor_token, admin_token):
        assert client.post("/api/reimport",
                           headers=auth_headers(token)).status_code == 404


def test_tarefas_diarias_so_admin(client, admin_token, gestor_token, auth_headers):
    """O disparo manual das fotos do dia é exclusivo de admin."""
    assert client.post("/api/admin/tarefas-diarias",
                       headers=auth_headers(gestor_token)).status_code == 403
    res = client.post("/api/admin/tarefas-diarias", headers=auth_headers(admin_token))
    assert res.status_code == 200
    assert res.get_json()["executado"] is True


def test_status_exige_gestor(client, tecnico_token, gestor_token, auth_headers):
    """/api/status era anônima e devolvia os caminhos absolutos do servidor."""
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status",
                      headers=auth_headers(tecnico_token)).status_code == 403
    dados = client.get("/api/status", headers=auth_headers(gestor_token)).get_json()
    assert "db_path" not in dados and "excel_path" not in dados
    assert dados["db_engine"] == "SQLite"


def test_tecnico_pode_atualizar_status(client, tecnico_token, admin_token, auth_headers):
    docs = client.get("/api/documentos", headers=auth_headers(admin_token)).get_json()
    doc_id = next(d["id"] for d in docs if d["equipamento"] == "MAQ-B")
    res = client.put(f"/api/documento/{doc_id}/status",
                     json={"status": "Concluído"},
                     headers=auth_headers(tecnico_token))
    assert res.status_code == 200
