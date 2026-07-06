"""Testes de workflow de status, optimistic lock e patch de campos."""


def _doc_id(client, headers, equip="MAQ-B"):
    docs = client.get("/api/documentos", headers=headers).get_json()
    return next(d["id"] for d in docs if d["equipamento"] == equip)


def test_status_change_valido(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h, "MAQ-B")  # Setor: Manuais, Status: Em andamento
    res = client.put(f"/api/documento/{doc_id}/status",
                     json={"status": "Concluído"},
                     headers=h)
    assert res.status_code == 200
    assert res.get_json()["documento"]["status"] == "Concluído"
    assert res.get_json()["documento"]["status_global"] == "Finalizado"


def test_status_change_status_invalido(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h, "MAQ-B")  # Setor: Manuais
    # "Homologado" só é válido para o setor PRE, não para Manuais
    res = client.put(f"/api/documento/{doc_id}/status",
                     json={"status": "Homologado"},
                     headers=h)
    assert res.status_code == 400
    assert "erro" in res.get_json()


def test_optimistic_lock_version_correto(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h, "MAQ-B")
    doc = client.get(f"/api/documentos/{doc_id}", headers=h).get_json()
    v = doc["version"]
    res = client.put(f"/api/documento/{doc_id}/status",
                     json={"status": "Concluído", "version": v},
                     headers=h)
    assert res.status_code == 200
    assert res.get_json()["documento"]["version"] == v + 1


def test_optimistic_lock_version_errado(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h, "MAQ-B")
    res = client.put(f"/api/documento/{doc_id}/status",
                     json={"status": "Concluído", "version": 999},
                     headers=h)
    assert res.status_code == 409
    assert res.get_json()["current_version"] == 0


def test_patch_documento_campos_str(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h, "MAQ-B")
    res = client.patch(f"/api/documentos/{doc_id}",
                       json={"documento": "Manual Siemens v2", "sku": "SKU-B-NEW"},
                       headers=h)
    assert res.status_code == 200
    data = res.get_json()["documento"]
    assert data["documento"] == "Manual Siemens v2"
    # SKU é identidade imutável pelo documento (canônica no Equipamento): o valor
    # enviado no PATCH é ignorado, o SKU original permanece.
    assert data["sku"] == "SKU-B"
