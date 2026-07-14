"""Testes da sincronização Documento → Cartão (missões).

O documento é a fonte da verdade: mudar seu status move os cartões vinculados
para a coluna da categoria alvo (todo/doing/done) da respectiva missão.
"""


def _setup_board_com_cartao(client, h, doc_id):
    """Cria missão (colunas padrão todo/doing/done) + cartão vinculado ao doc."""
    m = client.post("/api/missoes", json={"nome": "Missão Sync"}, headers=h).get_json()["missao"]
    colunas = {c["categoria"]: c for c in m["colunas"]}
    res = client.post(f"/api/missoes/colunas/{colunas['todo']['id']}/cartoes",
                      json={"titulo": "Cartão do doc", "ref_tipo": "documento",
                            "ref_id": doc_id}, headers=h)
    assert res.status_code == 201
    return m, colunas, res.get_json()["cartao"]


def _get_cartao(client, h, cid):
    return client.get(f"/api/missoes/cartoes/{cid}", headers=h).get_json()["cartao"]


def _doc_id(client, h, equip="MAQ-A"):
    docs = client.get("/api/documentos", headers=h).get_json()
    return next(d["id"] for d in docs if d["equipamento"] == equip)


def test_status_intermediario_move_para_doing(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h)          # seed: PRE, status Homologado
    # volta o doc para Elaborar primeiro (cartão nasce em todo)
    client.patch(f"/api/documentos/{doc_id}", json={"status": "Elaborar"}, headers=h)
    m, colunas, cartao = _setup_board_com_cartao(client, h, doc_id)

    res = client.patch(f"/api/documentos/{doc_id}",
                       json={"status": "Treinamento Piloto"}, headers=h)
    assert res.status_code == 200
    c = _get_cartao(client, h, cartao["id"])
    assert c["coluna_id"] == colunas["doing"]["id"]
    assert c["concluido"] is False
    assert c["versao"] > cartao["versao"]        # invalida drags concorrentes


def test_status_final_move_para_done_e_conclui(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h)
    client.patch(f"/api/documentos/{doc_id}", json={"status": "Elaborar"}, headers=h)
    m, colunas, cartao = _setup_board_com_cartao(client, h, doc_id)

    # via PUT /status (o outro endpoint que muda status)
    res = client.put(f"/api/documento/{doc_id}/status",
                     json={"status": "Homologado"}, headers=h)
    assert res.status_code == 200
    c = _get_cartao(client, h, cartao["id"])
    assert c["coluna_id"] == colunas["done"]["id"]
    assert c["concluido"] is True


def test_regressao_reabre_cartao(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h)          # já está Homologado no seed
    m, colunas, cartao = _setup_board_com_cartao(client, h, doc_id)
    client.put(f"/api/documento/{doc_id}/status", json={"status": "Homologado"}, headers=h)

    # regressão: Homologado → Enviado para Homologação
    res = client.patch(f"/api/documentos/{doc_id}",
                       json={"status": "Enviado para Homologação"}, headers=h)
    assert res.status_code == 200
    c = _get_cartao(client, h, cartao["id"])
    assert c["coluna_id"] == colunas["doing"]["id"]
    assert c["concluido"] is False        # reaberto


def test_missao_sem_coluna_da_categoria_nao_move(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h)
    client.patch(f"/api/documentos/{doc_id}", json={"status": "Elaborar"}, headers=h)
    m, colunas, cartao = _setup_board_com_cartao(client, h, doc_id)
    # remove a categoria da coluna 'doing' → não há alvo para intermediários
    res = client.patch(f"/api/missoes/colunas/{colunas['doing']['id']}",
                       json={"categoria": ""}, headers=h)
    assert res.status_code == 200

    client.patch(f"/api/documentos/{doc_id}",
                 json={"status": "Treinamento Piloto"}, headers=h)
    c = _get_cartao(client, h, cartao["id"])
    assert c["coluna_id"] == colunas["todo"]["id"]    # não moveu (no-op)


def test_cartao_sem_vinculo_nao_e_afetado(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h)
    client.patch(f"/api/documentos/{doc_id}", json={"status": "Elaborar"}, headers=h)
    m = client.post("/api/missoes", json={"nome": "Missão Livre"}, headers=h).get_json()["missao"]
    colunas = {c["categoria"]: c for c in m["colunas"]}
    solto = client.post(f"/api/missoes/colunas/{colunas['todo']['id']}/cartoes",
                        json={"titulo": "Sem vínculo"}, headers=h).get_json()["cartao"]

    client.patch(f"/api/documentos/{doc_id}",
                 json={"status": "Treinamento Piloto"}, headers=h)
    c = _get_cartao(client, h, solto["id"])
    assert c["coluna_id"] == colunas["todo"]["id"]
    assert c["versao"] == solto["versao"]


def test_sync_registra_auditoria(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h)
    client.patch(f"/api/documentos/{doc_id}", json={"status": "Elaborar"}, headers=h)
    _setup_board_com_cartao(client, h, doc_id)
    client.patch(f"/api/documentos/{doc_id}",
                 json={"status": "Treinamento Piloto"}, headers=h)

    logs = client.get("/api/audit", headers=h).get_json()
    movidos = [l for l in logs if l["acao"] == "MISSAO_CARTAO_MOVIDO"
               or "MISSAO_CARTAO_MOVIDO" in str(l.get("acao", ""))]
    # o publish_event grava o evento em audit_logs com origem doc-sync
    assert any("doc-sync" in str(l) for l in logs) or movidos


# ── R2: status vivo no payload + endpoint de cartões vinculados ──────────────

def test_board_traz_ref_status_do_documento(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h)
    client.patch(f"/api/documentos/{doc_id}",
                 json={"status": "Treinamento Piloto"}, headers=h)
    m, colunas, cartao = _setup_board_com_cartao(client, h, doc_id)

    board = client.get(f"/api/missoes/{m['id']}", headers=h).get_json()["missao"]
    todos = [c for col in board["colunas"] for c in col["cartoes"]]
    c = next(c for c in todos if c["id"] == cartao["id"])
    assert c["ref_status"] == "Treinamento Piloto"
    assert c["ref_status_global"] == "Em progresso"
    assert c["ref_label"]           # nome do documento resolvido em lote


def test_cartoes_vinculados_batch(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h)
    m, colunas, cartao = _setup_board_com_cartao(client, h, doc_id)

    res = client.get(f"/api/missoes/cartoes-vinculados?tipo=documento&ids={doc_id}",
                     headers=h)
    assert res.status_code == 200
    cartoes = res.get_json()["cartoes"]
    assert len(cartoes) == 1
    c = cartoes[0]
    assert c["id"] == cartao["id"]
    assert c["ref_id"] == doc_id
    assert c["missao_nome"] == "Missão Sync"
    assert c["coluna_categoria"] == "todo"

    # ids vazios → lista vazia; tipo inválido → 400
    assert client.get("/api/missoes/cartoes-vinculados?tipo=documento&ids=",
                      headers=h).get_json()["cartoes"] == []
    assert client.get("/api/missoes/cartoes-vinculados?tipo=xxx&ids=1",
                      headers=h).status_code == 400


def test_cartoes_vinculados_leitura_403(client, leitura_token, auth_headers):
    h = auth_headers(leitura_token)
    res = client.get("/api/missoes/cartoes-vinculados?tipo=documento&ids=1", headers=h)
    assert res.status_code == 403
