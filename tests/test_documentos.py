"""Testes CRUD de documentos, soft delete e snapshot no audit."""
import json


def _doc_id(client, headers, equip="MAQ-A"):
    docs = client.get("/api/documentos", headers=headers).get_json()
    return next(d["id"] for d in docs if d["equipamento"] == equip)


def test_listagem_so_ativos(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    docs = client.get("/api/documentos", headers=h).get_json()
    assert len(docs) == 3
    assert all(d["ativo"] for d in docs)


def test_create_documento(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    res = client.post("/api/documentos",
                      json={"equipamento": "MAQ-NEW", "documento": "POP-NEW",
                            "categoria": "Qualidade", "tipo_documento": "Qualidade"},
                      headers=h)
    assert res.status_code == 201
    assert res.get_json()["documento"]["equipamento"] == "MAQ-NEW"
    docs = client.get("/api/documentos", headers=h).get_json()
    assert len(docs) == 4


def test_create_sem_equipamento_falha(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    res = client.post("/api/documentos", json={"documento": "x"}, headers=h)
    assert res.status_code == 400


def test_soft_delete_remove_da_listagem(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h, "MAQ-A")

    res = client.delete(f"/api/documentos/{doc_id}", headers=h)
    assert res.status_code == 200

    # Sumiu da listagem
    docs = client.get("/api/documentos", headers=h).get_json()
    ids = [d["id"] for d in docs]
    assert doc_id not in ids
    assert len(docs) == 2


def test_soft_delete_persiste_snapshot_no_audit(client, admin_token, auth_headers, app):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h, "MAQ-A")
    client.delete(f"/api/documentos/{doc_id}", headers=h)

    # Verificar audit
    logs = client.get("/api/audit", headers=h).get_json()
    delete_logs = [l for l in logs if l["acao"] == "DELETE" and l["documento_id"] == doc_id]
    assert len(delete_logs) >= 1
    snapshot = json.loads(delete_logs[0]["valor_antigo"])
    assert snapshot["equipamento"] == "MAQ-A"
    assert snapshot["documento"] == "POP-001"


def test_soft_delete_marca_no_db(client, admin_token, auth_headers, app):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h, "MAQ-A")
    client.delete(f"/api/documentos/{doc_id}", headers=h)

    from models import Documento
    with app.app_context():
        doc = Documento.query.filter_by(id=doc_id).first()
        assert doc is not None  # ainda existe
        assert doc.ativo is False
        assert doc.deleted_at is not None


def test_get_documento_inexistente(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    res = client.get("/api/documentos/99999", headers=h)
    assert res.status_code == 404


def test_get_documento_soft_deleted(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h, "MAQ-A")
    client.delete(f"/api/documentos/{doc_id}", headers=h)
    # GET após delete não encontra (filtro ativo=True)
    res = client.get(f"/api/documentos/{doc_id}", headers=h)
    assert res.status_code == 404
