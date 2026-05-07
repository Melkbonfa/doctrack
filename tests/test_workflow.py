"""Testes de workflow de etapas, optimistic lock, validação de enums."""


def _doc_id(client, headers, equip="MAQ-B"):
    docs = client.get("/api/documentos", headers=headers).get_json()
    return next(d["id"] for d in docs if d["equipamento"] == equip)


def test_status_change_avanca_etapa(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h, "MAQ-B")  # elaboracao=Em andamento
    res = client.put(f"/api/documento/{doc_id}/status",
                     json={"etapa": "etapa_elaboracao", "status": "Concluído"},
                     headers=h)
    assert res.status_code == 200
    assert res.get_json()["documento"]["etapa_elaboracao"] == "Concluído"


def test_status_change_bloqueia_pular_etapa(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h, "MAQ-C")  # tudo Pendente
    # Tentar avançar revisao1 sem concluir elaboração → deve falhar
    res = client.put(f"/api/documento/{doc_id}/status",
                     json={"etapa": "etapa_revisao1", "status": "Em andamento"},
                     headers=h)
    assert res.status_code == 400
    assert "etapa_bloqueante" in res.get_json()


def test_status_change_etapa_invalida(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h, "MAQ-A")
    res = client.put(f"/api/documento/{doc_id}/status",
                     json={"etapa": "etapa_inexistente", "status": "Concluído"},
                     headers=h)
    assert res.status_code == 400


def test_status_change_status_invalido(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h, "MAQ-A")
    res = client.put(f"/api/documento/{doc_id}/status",
                     json={"etapa": "etapa_elaboracao", "status": "Inventado"},
                     headers=h)
    assert res.status_code == 400


def test_optimistic_lock_version_correto(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h, "MAQ-B")
    doc = client.get(f"/api/documentos/{doc_id}", headers=h).get_json()
    v = doc["version"]
    res = client.put(f"/api/documento/{doc_id}/status",
                     json={"etapa": "etapa_elaboracao", "status": "Concluído", "version": v},
                     headers=h)
    assert res.status_code == 200
    assert res.get_json()["documento"]["version"] == v + 1


def test_optimistic_lock_version_errado(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h, "MAQ-B")
    res = client.put(f"/api/documento/{doc_id}/status",
                     json={"etapa": "etapa_elaboracao", "status": "Concluído", "version": 999},
                     headers=h)
    assert res.status_code == 409
    assert res.get_json()["current_version"] == 0


def test_patch_valida_enum_etapa(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h, "MAQ-A")
    res = client.patch(f"/api/documentos/{doc_id}",
                       json={"etapa_elaboracao": "ValorInvalido"}, headers=h)
    assert res.status_code == 400
    assert "valores_validos" in res.get_json()


def test_patch_valida_enum_tipo(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h, "MAQ-A")
    res = client.patch(f"/api/documentos/{doc_id}",
                       json={"tipo_documento": "Inexistente"}, headers=h)
    assert res.status_code == 400


def test_patch_aceita_enum_valido(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h, "MAQ-A")
    res = client.patch(f"/api/documentos/{doc_id}",
                       json={"tipo_documento": "Engenharia"}, headers=h)
    assert res.status_code == 200
