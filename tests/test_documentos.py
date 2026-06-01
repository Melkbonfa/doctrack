"""Testes CRUD de documentos, soft delete e snapshot no audit."""
import json


def _doc_id(client, headers, equip="MAQ-A"):
    docs = client.get("/api/documentos", headers=headers).get_json()
    return next(d["id"] for d in docs if d["equipamento"] == equip)


def test_listagem_so_ativos(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    docs = client.get("/api/documentos", headers=h).get_json()
    assert len(docs) == 2
    assert all(d["ativo"] for d in docs)


def test_create_documento(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    res = client.post("/api/documentos",
                      json={"setor": "PRE", "equipamento": "MAQ-NEW", "documento": "POP-NEW",
                            "sku": "SKU-NEW", "codigo_doc": "COD-NEW"},
                      headers=h)
    assert res.status_code == 201
    assert res.get_json()["documento"]["equipamento"] == "MAQ-NEW"
    docs = client.get("/api/documentos", headers=h).get_json()
    assert len(docs) == 3


def test_create_setor_invalido_falha(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    res = client.post("/api/documentos", json={"setor": "Invalido", "documento": "x"}, headers=h)
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
    assert len(docs) == 1


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


def test_propagacao_global_sku(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    
    # 1. Cria um documento do setor "Manuais" para o mesmo equipamento "MAQ-A" (que tem SKU "SKU-A" na fixture)
    res_create = client.post("/api/documentos",
                             json={"setor": "Manuais", "equipamento": "MAQ-A", "documento": "Manual do Usuário - MAQ-A",
                                   "tipo_doc": "Manual_Usuario", "fabricante": "TestFab"},
                             headers=h)
    assert res_create.status_code == 201
    
    # Todos os manuais criados devem ter herdado "SKU-A"
    docs = client.get("/api/documentos", headers=h).get_json()
    maq_a_docs = [d for d in docs if d["equipamento"] == "MAQ-A"]
    # Devem ser: 1 (original do seed de PRE) + 5 (manuais criados) = 6 documentos
    assert len(maq_a_docs) == 6
    for d in maq_a_docs:
        assert d["sku"] == "SKU-A"
        
    # 2. Atualizar o SKU do documento original do setor "PRE" (MAQ-A) para "SKU-NOVO"
    doc_pre_id = next(d["id"] for d in maq_a_docs if d["setor"] == "PRE")
    res_update = client.patch(f"/api/documentos/{doc_pre_id}",
                              json={"sku": "SKU-NOVO"},
                              headers=h)
    assert res_update.status_code == 200
    
    # 3. Verificar se todos os documentos de "MAQ-A" agora têm SKU "SKU-NOVO"
    docs_after = client.get("/api/documentos", headers=h).get_json()
    maq_a_docs_after = [d for d in docs_after if d["equipamento"] == "MAQ-A"]
    assert len(maq_a_docs_after) == 6
    for d in maq_a_docs_after:
        assert d["sku"] == "SKU-NOVO"
        
    # 4. Verificar se a auditoria registrou os updates
    audit = client.get("/api/audit", headers=h).get_json()
    sku_updates = [l for l in audit if l["acao"] == "UPDATE" and l["campo"] == "sku" and l["valor_novo"] == "SKU-NOVO"]
    # O documento de PRE editado gera um log 'sku' na atualização principal.
    # Os outros 5 manuais geram logs individuais 'sku' no loop de propagação global.
    # Total de logs de update de SKU deve ser 6.
    assert len(sku_updates) == 6


def test_abrir_pasta_caminho_vazio(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    res = client.post("/api/documentos/abrir-pasta", json={"caminho": ""}, headers=h)
    assert res.status_code == 400
    assert "Caminho não fornecido" in res.get_json()["erro"]


def test_abrir_pasta_caminho_inexistente(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    from unittest.mock import patch
    with patch("os.path.exists", return_value=False):
        res = client.post("/api/documentos/abrir-pasta", json={"caminho": "Z:/Inexistente/Diretorio/Falso.pdf"}, headers=h)
        assert res.status_code == 404
        assert "Caminho não encontrado" in res.get_json()["erro"]


def test_abrir_pasta_diretorio_sucesso(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    import os
    from unittest.mock import patch
    diretorio_real = os.path.dirname(os.path.abspath(__file__))
    
    with patch("os.startfile") as mock_startfile:
        res = client.post("/api/documentos/abrir-pasta", json={"caminho": diretorio_real}, headers=h)
        assert res.status_code == 200
        data = res.get_json()
        assert data["local"] is True
        mock_startfile.assert_called_once_with(os.path.normpath(diretorio_real))


def test_abrir_pasta_arquivo_sucesso(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    import os
    from unittest.mock import patch
    arquivo_real = os.path.abspath(__file__)
    
    with patch("subprocess.Popen") as mock_popen:
        res = client.post("/api/documentos/abrir-pasta", json={"caminho": arquivo_real}, headers=h)
        assert res.status_code == 200
        data = res.get_json()
        assert data["local"] is True
        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        assert args[0][0] == "explorer"
        assert args[0][1].startswith("/select,")


def test_abrir_pasta_ancestral_sucesso(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    import os
    from unittest.mock import patch
    diretorio_real = os.path.dirname(os.path.abspath(__file__))
    caminho_falso = os.path.join(diretorio_real, "PastaNaoExistente", "ArquivoFalso.pdf")
    
    with patch("os.startfile") as mock_startfile:
        res = client.post("/api/documentos/abrir-pasta", json={"caminho": caminho_falso}, headers=h)
        assert res.status_code == 200
        data = res.get_json()
        assert "Pasta ancestral aberta" in data["mensagem"] or "raiz" in data["mensagem"]
        assert data["local"] is True
        assert data["caminho_aberto"] == os.path.normpath(diretorio_real)
        mock_startfile.assert_called_once_with(os.path.normpath(diretorio_real))


def test_abrir_pasta_acesso_remoto(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    import os
    diretorio_real = os.path.dirname(os.path.abspath(__file__))
    
    # Simula IP do cliente como 192.168.1.99 (acesso remoto)
    res = client.post("/api/documentos/abrir-pasta", 
                      json={"caminho": diretorio_real}, 
                      headers=h,
                      environ_overrides={"REMOTE_ADDR": "192.168.1.99"})
                      
    assert res.status_code == 200
    data = res.get_json()
    assert data["local"] is False
    assert "Acesso remoto" in data["mensagem"]
    assert data["caminho_aberto"] == os.path.normpath(diretorio_real)




