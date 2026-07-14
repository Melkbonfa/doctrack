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
    from models import TIPOS_DOC_TODOS
    h = auth_headers(admin_token)
    res = client.post("/api/documentos",
                      json={"setor": "PRE", "equipamento": "MAQ-NEW", "documento": "POP-NEW",
                            "sku": "SKU-NEW", "codigo_doc": "COD-NEW"},
                      headers=h)
    assert res.status_code == 201
    assert res.get_json()["documento"]["equipamento"] == "MAQ-NEW"

    # Criar um documento para um equipamento novo gera automaticamente os 12 tipos
    # (equipamento = entidade central); os opcionais nascem em N/A (aplicavel=False),
    # existem mas ficam fora da completude — ver tests/test_taxonomia_docs.py.
    docs = client.get("/api/documentos", headers=h).get_json()
    maq_new = [d for d in docs if d["equipamento"] == "MAQ-NEW"]
    assert len(maq_new) == len(TIPOS_DOC_TODOS)
    assert {d["tipo_doc"] for d in maq_new} == set(TIPOS_DOC_TODOS)

    # O tipo selecionado (IT, primeiro do setor PRE) recebe os dados do payload;
    # os demais nascem em branco.
    it_doc = next(d for d in maq_new if d["tipo_doc"] == "IT")
    assert it_doc["documento"] == "POP-NEW"
    assert it_doc["codigo_doc"] == "COD-NEW"


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
    """A identidade (SKU) é canônica no Equipamento e imutável pelo documento.
    Editar o SKU do equipamento propaga para todos os documentos vinculados."""
    from models import TIPOS_DOC_TODOS
    h = auth_headers(admin_token)

    # 1. Criar um documento para "MAQ-A" gera os 12 tipos canônicos que faltam;
    #    todos herdam o SKU do equipamento (SKU-A). O documento do seed tem tipo_doc
    #    vazio (não canônico e sem equipamento_id), então filtramos pelos canônicos.
    res_create = client.post("/api/documentos",
                             json={"setor": "Manuais", "equipamento": "MAQ-A",
                                   "documento": "Manual do Usuário - MAQ-A",
                                   "tipo_doc": "Manual_Usuario", "fabricante": "TestFab"},
                             headers=h)
    assert res_create.status_code == 201

    docs = client.get("/api/documentos", headers=h).get_json()
    canonicos = [d for d in docs if d["equipamento"] == "MAQ-A" and d["tipo_doc"] in TIPOS_DOC_TODOS]
    assert len(canonicos) == len(TIPOS_DOC_TODOS)
    for d in canonicos:
        assert d["sku"] == "SKU-A"

    # 2. Editar o SKU pelo Equipamento (fonte única de identidade) propaga aos docs.
    equips = client.get("/api/equipamentos", headers=h).get_json()
    equip_a = next(e for e in equips if e["nome"] == "MAQ-A")
    res_update = client.patch(f"/api/equipamentos/{equip_a['id']}",
                              json={"sku": "SKU-NOVO"}, headers=h)
    assert res_update.status_code == 200

    # 3. Todos os documentos canônicos de "MAQ-A" agora têm SKU "SKU-NOVO".
    docs_after = client.get("/api/documentos", headers=h).get_json()
    canonicos_after = [d for d in docs_after if d["equipamento"] == "MAQ-A" and d["tipo_doc"] in TIPOS_DOC_TODOS]
    assert len(canonicos_after) == len(TIPOS_DOC_TODOS)
    for d in canonicos_after:
        assert d["sku"] == "SKU-NOVO"

    # 4. A auditoria registrou o update de SKU do equipamento.
    audit = client.get("/api/audit", headers=h).get_json()
    sku_updates = [l for l in audit if l["acao"] == "UPDATE" and "sku" in (l.get("campo") or "")]
    assert len(sku_updates) >= 1


def test_abrir_pasta_caminho_vazio(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    res = client.post("/api/documentos/abrir-pasta", json={"caminho": ""}, headers=h)
    assert res.status_code == 400
    assert "Caminho não fornecido" in res.get_json()["erro"]


def test_abrir_pasta_caminho_inexistente(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    import os
    from unittest.mock import patch
    raiz = os.path.dirname(os.path.abspath(__file__))
    # Dentro do allowlist, porém inexistente → 404 (e não 403).
    caminho = os.path.join(raiz, "Inexistente", "Diretorio", "Falso.pdf")
    with patch("documentos.ARQUIVOS_ROOTS", [raiz]), patch("os.path.exists", return_value=False):
        res = client.post("/api/documentos/abrir-pasta", json={"caminho": caminho}, headers=h)
        assert res.status_code == 404
        assert "Caminho não encontrado" in res.get_json()["erro"]


def test_abrir_pasta_fora_das_raizes_bloqueado(client, admin_token, auth_headers):
    """Caminho fora do allowlist é rejeitado com 403 — proteção contra sondagem
    de caminhos arbitrários do servidor e shares UNC de terceiros."""
    h = auth_headers(admin_token)
    import os
    from unittest.mock import patch
    raiz = os.path.dirname(os.path.abspath(__file__))
    with patch("documentos.ARQUIVOS_ROOTS", [raiz]), patch("os.startfile") as mock_startfile, \
         patch("subprocess.Popen") as mock_popen:
        res = client.post("/api/documentos/abrir-pasta",
                          json={"caminho": r"C:\Windows\System32"}, headers=h)
        assert res.status_code == 403
        assert "fora das pastas permitidas" in res.get_json()["erro"]
        mock_startfile.assert_not_called()
        mock_popen.assert_not_called()


def test_abrir_pasta_diretorio_sucesso(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    import os
    from unittest.mock import patch
    diretorio_real = os.path.dirname(os.path.abspath(__file__))

    with patch("documentos.ARQUIVOS_ROOTS", [diretorio_real]), patch("os.startfile") as mock_startfile:
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
    raiz = os.path.dirname(arquivo_real)

    with patch("documentos.ARQUIVOS_ROOTS", [raiz]), patch("subprocess.Popen") as mock_popen:
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

    with patch("documentos.ARQUIVOS_ROOTS", [diretorio_real]), patch("os.startfile") as mock_startfile:
        res = client.post("/api/documentos/abrir-pasta", json={"caminho": caminho_falso}, headers=h)
        assert res.status_code == 200
        data = res.get_json()
        # A resolução ancestral agora é sinalizada pelo campo "tipo" (a mensagem é
        # sempre "Pasta aberta com sucesso"), e a pasta aberta é o ancestral existente.
        assert data["tipo"] == "ancestral"
        assert data["local"] is True
        assert data["caminho_aberto"] == os.path.normpath(diretorio_real)
        mock_startfile.assert_called_once_with(os.path.normpath(diretorio_real))


def test_abrir_pasta_acesso_remoto(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    import os
    from unittest.mock import patch
    diretorio_real = os.path.dirname(os.path.abspath(__file__))

    # Simula IP do cliente como 192.168.1.99 (acesso remoto)
    with patch("documentos.ARQUIVOS_ROOTS", [diretorio_real]):
        res = client.post("/api/documentos/abrir-pasta",
                          json={"caminho": diretorio_real},
                          headers=h,
                          environ_overrides={"REMOTE_ADDR": "192.168.1.99"})

    assert res.status_code == 200
    data = res.get_json()
    assert data["local"] is False
    assert "Acesso remoto" in data["mensagem"]
    assert data["caminho_aberto"] == os.path.normpath(diretorio_real)






def test_documento_nasce_aplicavel(client, admin_token, auth_headers):
    """Todo documento nasce aplicável; o dict expõe aplicavel/motivo_na."""
    h = auth_headers(admin_token)
    res = client.post("/api/documentos",
                      json={"setor": "PRE", "equipamento": "MAQ-APL", "sku": "SKU-APL"},
                      headers=h)
    assert res.status_code == 201
    doc = res.get_json()["documento"]
    assert doc["aplicavel"] is True
    assert doc["motivo_na"] == ""


def _doc_de_tipo(client, headers, equipamento, tipo):
    docs = client.get("/api/documentos", headers=headers).get_json()
    return next(d for d in docs if d["equipamento"] == equipamento and d["tipo_doc"] == tipo)


def test_aplicabilidade_gestor_marca_na(client, admin_token, gestor_token, auth_headers):
    ha, hg = auth_headers(admin_token), auth_headers(gestor_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-NA"}, headers=ha)
    doc = _doc_de_tipo(client, ha, "MAQ-NA", "Manual_ES")

    res = client.put(f"/api/documentos/{doc['id']}/aplicabilidade",
                     json={"aplicavel": False, "motivo_na": "produto sem versão ES"},
                     headers=hg)
    assert res.status_code == 200
    d = res.get_json()["documento"]
    assert d["aplicavel"] is False
    assert d["motivo_na"] == "produto sem versão ES"
    assert d["status"] == "Elaborar"        # marcar N/A não mexe no status


def test_aplicabilidade_tecnico_negado(client, admin_token, tecnico_token, auth_headers):
    ha, ht = auth_headers(admin_token), auth_headers(tecnico_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-NA2"}, headers=ha)
    doc = _doc_de_tipo(client, ha, "MAQ-NA2", "Manual_ES")

    res = client.put(f"/api/documentos/{doc['id']}/aplicabilidade",
                     json={"aplicavel": False}, headers=ht)
    assert res.status_code == 403


def test_religar_na_preserva_dados(client, admin_token, auth_headers):
    """Religar um documento N/A devolve status, código e responsável intactos."""
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-NA3"}, headers=h)
    doc = _doc_de_tipo(client, h, "MAQ-NA3", "Manual_Servico")

    client.patch(f"/api/documentos/{doc['id']}",
                 json={"codigo_doc": "MS-77", "responsavel": "Ana", "status": "Em andamento"},
                 headers=h)
    client.put(f"/api/documentos/{doc['id']}/aplicabilidade",
               json={"aplicavel": False, "motivo_na": "sem serviço em campo"}, headers=h)
    res = client.put(f"/api/documentos/{doc['id']}/aplicabilidade",
                     json={"aplicavel": True}, headers=h)

    assert res.status_code == 200
    d = res.get_json()["documento"]
    assert d["aplicavel"] is True
    assert d["motivo_na"] == ""              # religar limpa o motivo
    assert d["codigo_doc"] == "MS-77"
    assert d["responsavel"] == "Ana"
    assert d["status"] == "Em andamento"


def test_kpis_ignoram_documentos_na(client, admin_token, auth_headers):
    """Documento em N/A sai do total e da contagem de pendentes."""
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-KPI"}, headers=h)

    antes = client.get("/api/metrics", headers=h).get_json()
    doc = _doc_de_tipo(client, h, "MAQ-KPI", "Manual_Servico")
    client.put(f"/api/documentos/{doc['id']}/aplicabilidade",
               json={"aplicavel": False}, headers=h)
    depois = client.get("/api/metrics", headers=h).get_json()

    assert depois["total"] == antes["total"] - 1
    assert depois["pendentes"] == antes["pendentes"] - 1
