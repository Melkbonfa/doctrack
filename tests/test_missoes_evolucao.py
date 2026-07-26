"""Testes da evolução do módulo de Missões (migration 010).

Cobre o que o módulo não tinha: marcos temporais, trilha do cartão, responsáveis
N:N, WIP, checklist, comentários, recorrência, modelos, métricas, alertas e
export — além das validações e do soft delete que faltavam.
"""


def _missao(client, h, nome="Missão Teste", **extra):
    body = {"nome": nome}
    body.update(extra)
    r = client.post("/api/missoes", json=body, headers=h)
    assert r.status_code == 201, r.get_json()
    m = r.get_json()["missao"]
    return m, {c["categoria"]: c for c in m["colunas"]}


def _cartao(client, h, coluna_id, titulo="Cartão", **extra):
    body = {"titulo": titulo}
    body.update(extra)
    r = client.post(f"/api/missoes/colunas/{coluna_id}/cartoes", json=body, headers=h)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["cartao"]


def _get(client, h, cid):
    return client.get(f"/api/missoes/cartoes/{cid}", headers=h).get_json()["cartao"]


def _doc_id(client, h, equip="MAQ-A"):
    docs = client.get("/api/documentos", headers=h).get_json()
    return next(d["id"] for d in docs if d["equipamento"] == equip)


# ── Validações que faltavam ──────────────────────────────────────────────────

def test_prazo_precisa_ser_data_real(client, admin_token, auth_headers):
    """O regex de formato deixava passar 2026-02-31 e 2026-13-45."""
    h = auth_headers(admin_token)
    _, cols = _missao(client, h)
    for ruim in ("2026-02-31", "2026-13-01", "0000-00-00", "26-01-01"):
        r = client.post(f"/api/missoes/colunas/{cols['todo']['id']}/cartoes",
                        json={"titulo": "X", "prazo": ruim}, headers=h)
        assert r.status_code == 400, f"{ruim} deveria ser recusado"
    assert client.post(f"/api/missoes/colunas/{cols['todo']['id']}/cartoes",
                       json={"titulo": "X", "prazo": "2026-02-28"},
                       headers=h).status_code == 201


def test_inicio_depois_do_prazo_e_recusado(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    _, cols = _missao(client, h)
    r = client.post(f"/api/missoes/colunas/{cols['todo']['id']}/cartoes",
                    json={"titulo": "X", "data_inicio": "2026-05-10",
                          "prazo": "2026-05-01"}, headers=h)
    assert r.status_code == 400


def test_cor_da_coluna_precisa_ser_hex(client, admin_token, auth_headers):
    """A cor cai num atributo style=""; sem validar, aceitava CSS arbitrário."""
    h = auth_headers(admin_token)
    m, cols = _missao(client, h)
    ruim = "red;background-image:url(http://externo/x.png)"
    assert client.post(f"/api/missoes/{m['id']}/colunas",
                       json={"nome": "C", "cor": ruim}, headers=h).status_code == 400
    assert client.patch(f"/api/missoes/colunas/{cols['todo']['id']}",
                        json={"cor": ruim}, headers=h).status_code == 400
    assert client.patch(f"/api/missoes/colunas/{cols['todo']['id']}",
                        json={"cor": "#ff8800"}, headers=h).status_code == 200


def test_limite_wip_validado(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    m, cols = _missao(client, h)
    assert client.patch(f"/api/missoes/colunas/{cols['doing']['id']}",
                        json={"limite_wip": "abc"}, headers=h).status_code == 400
    assert client.patch(f"/api/missoes/colunas/{cols['doing']['id']}",
                        json={"limite_wip": -1}, headers=h).status_code == 400
    r = client.patch(f"/api/missoes/colunas/{cols['doing']['id']}",
                     json={"limite_wip": 3}, headers=h)
    assert r.status_code == 200 and r.get_json()["coluna"]["limite_wip"] == 3


# ── Marcos temporais ─────────────────────────────────────────────────────────

def test_cartao_nasce_com_criado_em(client, admin_token, auth_headers):
    """Sem `criado_em` nem a idade do cartão era derivável."""
    h = auth_headers(admin_token)
    _, cols = _missao(client, h)
    c = _cartao(client, h, cols["todo"]["id"])
    assert c["criado_em"] and c["criado_em_iso"]
    assert c["dias_parado"] == 0
    assert c["concluido_em"] == ""


def test_conclusao_grava_quando_e_quem(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    _, cols = _missao(client, h)
    c = _cartao(client, h, cols["todo"]["id"])
    r = client.patch(f"/api/missoes/cartoes/{c['id']}",
                     json={"concluido": True, "versao": c["versao"]}, headers=h)
    assert r.status_code == 200
    d = r.get_json()["cartao"]
    assert d["concluido"] is True
    assert d["concluido_em"] and d["concluido_por"] == "admin@test.com"
    # reabrir limpa os marcos
    r = client.patch(f"/api/missoes/cartoes/{c['id']}",
                     json={"concluido": False, "versao": d["versao"]}, headers=h)
    d = r.get_json()["cartao"]
    assert d["concluido"] is False and d["concluido_em"] == ""


def test_atrasado_derivado_do_prazo(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    _, cols = _missao(client, h)
    c = _cartao(client, h, cols["todo"]["id"], prazo="2020-01-01")
    assert _get(client, h, c["id"])["atrasado"] is True
    client.patch(f"/api/missoes/cartoes/{c['id']}",
                 json={"concluido": True, "versao": c["versao"]}, headers=h)
    assert _get(client, h, c["id"])["atrasado"] is False   # concluído não atrasa


# ── Trilha temporal ──────────────────────────────────────────────────────────

def test_historico_registra_criacao_movimento_e_campos(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    m, cols = _missao(client, h)
    c = _cartao(client, h, cols["todo"]["id"], titulo="Original")

    client.patch(f"/api/missoes/cartoes/{c['id']}",
                 json={"titulo": "Renomeado", "prioridade": "alta",
                       "versao": c["versao"]}, headers=h)
    atual = _get(client, h, c["id"])
    client.post("/api/missoes/reordenar",
                json={"cartao_id": c["id"], "versao": atual["versao"],
                      "coluna_destino_id": cols["doing"]["id"], "ids": [c["id"]]},
                headers=h)

    hist = client.get(f"/api/missoes/cartoes/{c['id']}/historico",
                      headers=h).get_json()["historico"]
    eventos = [x["evento"] for x in hist]
    assert "criado" in eventos and "movido" in eventos and "campo" in eventos
    campos = {x["campo"]: x for x in hist if x["evento"] == "campo"}
    assert campos["titulo"]["valor_antigo"] == "Original"
    assert campos["titulo"]["valor_novo"] == "Renomeado"
    assert campos["prioridade"]["valor_novo"] == "alta"
    movido = next(x for x in hist if x["evento"] == "movido")
    assert movido["coluna_origem"] == "A fazer"
    assert movido["coluna_destino"] == "Fazendo"


def test_historico_da_missao_e_filtravel(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    m, cols = _missao(client, h)
    a = _cartao(client, h, cols["todo"]["id"], titulo="A")
    b = _cartao(client, h, cols["todo"]["id"], titulo="B")
    todos = client.get(f"/api/missoes/{m['id']}/historico", headers=h).get_json()
    assert todos["total"] >= 2
    so_a = client.get(f"/api/missoes/{m['id']}/historico?cartao_id={a['id']}",
                      headers=h).get_json()["historico"]
    assert so_a and all(x["cartao_id"] == a["id"] for x in so_a)
    assert all(x["cartao"] == "A" for x in so_a)
    assert b["id"] not in [x["cartao_id"] for x in so_a]


def test_sync_de_documento_marca_origem_no_historico(client, admin_token, auth_headers):
    """A marca 'doc-sync' só existia no payload do socket, que não fica gravado."""
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h)
    client.patch(f"/api/documentos/{doc_id}", json={"status": "Elaborar"}, headers=h)
    _, cols = _missao(client, h)
    c = _cartao(client, h, cols["todo"]["id"], ref_tipo="documento", ref_id=doc_id)

    client.patch(f"/api/documentos/{doc_id}",
                 json={"status": "Treinamento Piloto"}, headers=h)
    hist = client.get(f"/api/missoes/cartoes/{c['id']}/historico",
                      headers=h).get_json()["historico"]
    assert any(x["origem"] == "doc-sync" and x["evento"] == "movido" for x in hist)


# ── A coluna é o estado ──────────────────────────────────────────────────────

def test_arrastar_para_done_conclui_o_cartao(client, admin_token, auth_headers):
    """Cartão na coluna de concluído com `concluido` falso sumia do throughput
    e continuava contando como WIP."""
    h = auth_headers(admin_token)
    m, cols = _missao(client, h)
    c = _cartao(client, h, cols["todo"]["id"])
    r = client.post("/api/missoes/reordenar",
                    json={"cartao_id": c["id"], "versao": c["versao"],
                          "coluna_destino_id": cols["done"]["id"], "ids": [c["id"]]},
                    headers=h)
    assert r.status_code == 200
    assert r.get_json()["cartao"]["concluido"] is True
    # voltar para 'doing' reabre
    atual = _get(client, h, c["id"])
    r = client.post("/api/missoes/reordenar",
                    json={"cartao_id": c["id"], "versao": atual["versao"],
                          "coluna_destino_id": cols["doing"]["id"], "ids": [c["id"]]},
                    headers=h)
    assert r.get_json()["cartao"]["concluido"] is False


def test_lock_otimista_no_patch_e_no_move(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    m, cols = _missao(client, h)
    c = _cartao(client, h, cols["todo"]["id"])
    assert client.patch(f"/api/missoes/cartoes/{c['id']}",
                        json={"titulo": "Novo", "versao": 999},
                        headers=h).status_code == 409
    assert client.post("/api/missoes/reordenar",
                       json={"cartao_id": c["id"], "versao": 999,
                             "coluna_destino_id": cols["doing"]["id"], "ids": []},
                       headers=h).status_code == 409


# ── Responsáveis N:N ─────────────────────────────────────────────────────────

def test_meus_cartoes_nao_casa_por_substring(client, tecnico_token, auth_headers):
    """O ILIKE '%nome%' fazia "Ana" casar com "Mariana"."""
    h = auth_headers(tecnico_token)
    _, cols = _missao(client, h)
    meu = _cartao(client, h, cols["todo"]["id"], titulo="Meu",
                  responsaveis="Tecnico Test")
    alheio = _cartao(client, h, cols["todo"]["id"], titulo="Do xará",
                     responsaveis="Tecnico Testador da Silva")
    r = client.get("/api/missoes/meus-cartoes", headers=h).get_json()
    ids = [c["id"] for c in r["cartoes"]]
    assert meu["id"] in ids
    assert alheio["id"] not in ids


def test_meus_cartoes_ignora_concluidos_e_arquivadas(client, tecnico_token, auth_headers):
    h = auth_headers(tecnico_token)
    m, cols = _missao(client, h)
    aberto = _cartao(client, h, cols["todo"]["id"], responsaveis="Tecnico Test")
    feito = _cartao(client, h, cols["todo"]["id"], responsaveis="Tecnico Test",
                    titulo="Pronto")
    client.patch(f"/api/missoes/cartoes/{feito['id']}",
                 json={"concluido": True, "versao": feito["versao"]}, headers=h)
    ids = [c["id"] for c in client.get("/api/missoes/meus-cartoes",
                                       headers=h).get_json()["cartoes"]]
    assert aberto["id"] in ids and feito["id"] not in ids

    client.patch(f"/api/missoes/{m['id']}", json={"arquivado": True}, headers=h)
    assert client.get("/api/missoes/meus-cartoes", headers=h).get_json()["total"] == 0


def test_meus_cartoes_conta_atrasados(client, tecnico_token, auth_headers):
    h = auth_headers(tecnico_token)
    _, cols = _missao(client, h)
    _cartao(client, h, cols["todo"]["id"], responsaveis="Tecnico Test",
            prazo="2020-01-01")
    r = client.get("/api/missoes/meus-cartoes", headers=h).get_json()
    assert r["total"] == 1 and r["atrasados"] == 1


# ── Arquivar em vez de destruir ──────────────────────────────────────────────

def test_delete_missao_arquiva_por_padrao(client, admin_token, auth_headers):
    """O DELETE era cascade e levaria a série histórica inteira junto."""
    h = auth_headers(admin_token)
    m, cols = _missao(client, h)
    _cartao(client, h, cols["todo"]["id"])
    r = client.delete(f"/api/missoes/{m['id']}", headers=h)
    assert r.status_code == 200 and r.get_json()["arquivado"] is True
    assert m["id"] not in [x["id"] for x in
                           client.get("/api/missoes", headers=h).get_json()["missoes"]]
    arq = client.get("/api/missoes?arquivadas=1", headers=h).get_json()["missoes"]
    assert m["id"] in [x["id"] for x in arq]
    # desarquivar traz de volta com os cartões intactos
    client.patch(f"/api/missoes/{m['id']}", json={"arquivado": False}, headers=h)
    board = client.get(f"/api/missoes/{m['id']}", headers=h).get_json()["missao"]
    assert sum(len(c["cartoes"]) for c in board["colunas"]) == 1


def test_exclusao_definitiva_so_admin(client, admin_token, tecnico_token, auth_headers):
    ha, ht = auth_headers(admin_token), auth_headers(tecnico_token)
    m, _ = _missao(client, ht, nome="Do técnico")
    assert client.delete(f"/api/missoes/{m['id']}?definitivo=1",
                         headers=ht).status_code == 403
    r = client.delete(f"/api/missoes/{m['id']}?definitivo=1", headers=ha)
    assert r.status_code == 200 and r.get_json()["definitivo"] is True
    assert client.get(f"/api/missoes/{m['id']}", headers=ha).status_code == 404


def test_tecnico_nao_arquiva_missao_alheia(client, admin_token, tecnico_token, auth_headers):
    """`criado_por` era gravado e nunca consultado."""
    ha, ht = auth_headers(admin_token), auth_headers(tecnico_token)
    m, _ = _missao(client, ha, nome="Da gestão")
    assert client.delete(f"/api/missoes/{m['id']}", headers=ht).status_code == 403
    assert client.patch(f"/api/missoes/{m['id']}", json={"arquivado": True},
                        headers=ht).status_code == 403
    # a própria, pode
    minha, _ = _missao(client, ht, nome="Minha")
    assert client.delete(f"/api/missoes/{minha['id']}", headers=ht).status_code == 200


def test_excluir_coluna_move_cartoes(client, admin_token, auth_headers):
    """Os cartões migram em vez de serem destruídos junto com a coluna."""
    h = auth_headers(admin_token)
    m, cols = _missao(client, h)
    c = _cartao(client, h, cols["doing"]["id"])
    r = client.delete(f"/api/missoes/colunas/{cols['doing']['id']}"
                      f"?destino_id={cols['todo']['id']}", headers=h)
    assert r.status_code == 200 and r.get_json()["cartoes_movidos"] == 1
    assert _get(client, h, c["id"])["coluna_id"] == cols["todo"]["id"]
    hist = client.get(f"/api/missoes/cartoes/{c['id']}/historico",
                      headers=h).get_json()["historico"]
    assert any(x["campo"] == "coluna_excluida" for x in hist)


def test_nao_exclui_a_unica_coluna_com_cartoes(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    m, cols = _missao(client, h)
    _cartao(client, h, cols["todo"]["id"])
    client.delete(f"/api/missoes/colunas/{cols['doing']['id']}", headers=h)
    client.delete(f"/api/missoes/colunas/{cols['done']['id']}", headers=h)
    assert client.delete(f"/api/missoes/colunas/{cols['todo']['id']}",
                         headers=h).status_code == 400


# ── Contadores da sidebar ────────────────────────────────────────────────────

def test_lista_traz_abertos_e_total(client, admin_token, auth_headers):
    """A missão 38/40 pronta mostrava "40" e parecia intocada."""
    h = auth_headers(admin_token)
    m, cols = _missao(client, h)
    a = _cartao(client, h, cols["todo"]["id"], titulo="A")
    _cartao(client, h, cols["todo"]["id"], titulo="B")
    client.patch(f"/api/missoes/cartoes/{a['id']}",
                 json={"concluido": True, "versao": a["versao"]}, headers=h)
    linha = next(x for x in client.get("/api/missoes", headers=h).get_json()["missoes"]
                 if x["id"] == m["id"])
    assert linha["n_cartoes"] == 2 and linha["n_abertos"] == 1


# ── Checklist e comentários ──────────────────────────────────────────────────

def test_checklist_crud_e_contagem_no_board(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    m, cols = _missao(client, h)
    c = _cartao(client, h, cols["todo"]["id"])
    i1 = client.post(f"/api/missoes/cartoes/{c['id']}/itens",
                     json={"texto": "Passo 1"}, headers=h).get_json()["item"]
    client.post(f"/api/missoes/cartoes/{c['id']}/itens",
                json={"texto": "Passo 2"}, headers=h)
    client.patch(f"/api/missoes/itens/{i1['id']}", json={"feito": True}, headers=h)

    d = _get(client, h, c["id"])
    assert d["n_itens"] == 2 and d["n_itens_feitos"] == 1
    assert [x["texto"] for x in d["itens"]] == ["Passo 1", "Passo 2"]

    board = client.get(f"/api/missoes/{m['id']}", headers=h).get_json()["missao"]
    no_board = board["colunas"][0]["cartoes"][0]
    assert no_board["n_itens"] == 2 and no_board["n_itens_feitos"] == 1

    client.delete(f"/api/missoes/itens/{i1['id']}", headers=h)
    assert _get(client, h, c["id"])["n_itens"] == 1
    assert client.post(f"/api/missoes/cartoes/{c['id']}/itens",
                       json={"texto": "  "}, headers=h).status_code == 400


def test_comentarios_e_permissao_de_apagar(client, admin_token, tecnico_token, auth_headers):
    ha, ht = auth_headers(admin_token), auth_headers(tecnico_token)
    m, cols = _missao(client, ha)
    c = _cartao(client, ha, cols["todo"]["id"])
    com = client.post(f"/api/missoes/cartoes/{c['id']}/comentarios",
                      json={"texto": "Travou no fornecedor"},
                      headers=ha).get_json()["comentario"]
    assert com["por"] == "Admin Test"
    d = _get(client, ha, c["id"])
    assert d["n_comentarios"] == 1 and d["comentarios"][0]["texto"] == "Travou no fornecedor"
    # técnico não apaga comentário alheio; o autor sim
    assert client.delete(f"/api/missoes/comentarios/{com['id']}",
                         headers=ht).status_code == 403
    assert client.delete(f"/api/missoes/comentarios/{com['id']}",
                         headers=ha).status_code == 200


# ── Recorrência ──────────────────────────────────────────────────────────────

def test_concluir_cartao_recorrente_reagenda(client, admin_token, auth_headers):
    """Fechava-se o cartão e a próxima calibração dependia de alguém lembrar."""
    h = auth_headers(admin_token)
    m, cols = _missao(client, h)
    c = _cartao(client, h, cols["doing"]["id"], titulo="Calibração anual",
                prazo="2026-03-15", recorrencia="anual", responsaveis="Admin Test")
    client.post(f"/api/missoes/cartoes/{c['id']}/itens",
                json={"texto": "Emitir certificado"}, headers=h)
    r = client.patch(f"/api/missoes/cartoes/{c['id']}",
                     json={"concluido": True, "versao": c["versao"]}, headers=h)
    assert r.status_code == 200
    novo = r.get_json().get("recorrencia")
    assert novo and novo["prazo"] == "2027-03-15"

    gerado = _get(client, h, novo["cartao_id"])
    assert gerado["titulo"] == "Calibração anual"
    assert gerado["coluna_id"] == cols["todo"]["id"]     # volta para o início
    assert gerado["concluido"] is False
    assert gerado["recorrencia"] == "anual"
    assert gerado["n_itens"] == 1 and gerado["n_itens_feitos"] == 0   # checklist zerado
    hist = client.get(f"/api/missoes/cartoes/{gerado['id']}/historico",
                      headers=h).get_json()["historico"]
    assert any(x["origem"] == "recorrencia" for x in hist)


def test_recorrencia_mensal_respeita_calendario(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    _, cols = _missao(client, h)
    c = _cartao(client, h, cols["todo"]["id"], prazo="2026-01-31", recorrencia="mensal")
    r = client.patch(f"/api/missoes/cartoes/{c['id']}",
                     json={"concluido": True, "versao": c["versao"]}, headers=h)
    assert r.get_json()["recorrencia"]["prazo"] == "2026-02-28"


def test_recorrencia_invalida_recusada(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    _, cols = _missao(client, h)
    assert client.post(f"/api/missoes/colunas/{cols['todo']['id']}/cartoes",
                       json={"titulo": "X", "recorrencia": "de vez em quando"},
                       headers=h).status_code == 400


# ── Vínculos ─────────────────────────────────────────────────────────────────

def test_vinculo_desativado_fica_visivel(client, admin_token, auth_headers):
    """O chip sumia sem aviso e o cartão perdia o contexto."""
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h)
    m, cols = _missao(client, h)
    c = _cartao(client, h, cols["todo"]["id"], ref_tipo="documento", ref_id=doc_id)
    assert _get(client, h, c["id"])["ref_ativo"] is True

    client.delete(f"/api/documentos/{doc_id}", headers=h)
    board = client.get(f"/api/missoes/{m['id']}", headers=h).get_json()["missao"]
    no_board = board["colunas"][0]["cartoes"][0]
    assert no_board["ref_label"]              # continua identificável
    assert no_board["ref_ativo"] is False     # mas marcado como morto


def test_cartao_rapido_a_partir_do_documento(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _doc_id(client, h)
    m, cols = _missao(client, h)
    r = client.post("/api/missoes/cartao-rapido",
                    json={"missao_id": m["id"], "titulo": "Revisar POP",
                          "ref_tipo": "documento", "ref_id": doc_id,
                          "prazo": "2026-08-01"}, headers=h)
    assert r.status_code == 201
    j = r.get_json()
    assert j["coluna_nome"] == "A fazer" and j["missao_nome"] == m["nome"]
    assert j["cartao"]["ref_id"] == doc_id
    vinculados = client.get(
        f"/api/missoes/cartoes-vinculados?tipo=documento&ids={doc_id}",
        headers=h).get_json()["cartoes"]
    assert [c["titulo"] for c in vinculados] == ["Revisar POP"]


# ── Etiquetas ────────────────────────────────────────────────────────────────

def test_etiquetas_devolve_vocabulario_com_frequencia(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    _, cols = _missao(client, h)
    _cartao(client, h, cols["todo"]["id"], titulo="A", etiquetas="hardware, anvisa")
    _cartao(client, h, cols["todo"]["id"], titulo="B", etiquetas="hardware")
    tags = client.get("/api/missoes/etiquetas", headers=h).get_json()["etiquetas"]
    assert tags[0] == {"nome": "hardware", "n": 2}
    assert {"nome": "anvisa", "n": 1} in tags


# ── Métricas e alertas ───────────────────────────────────────────────────────

def test_metricas_da_missao(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    m, cols = _missao(client, h)
    client.patch(f"/api/missoes/colunas/{cols['doing']['id']}",
                 json={"limite_wip": 1}, headers=h)
    feito = _cartao(client, h, cols["todo"]["id"], titulo="Feito", peso=3)
    _cartao(client, h, cols["doing"]["id"], titulo="Andando",
            responsaveis="Admin Test", prazo="2020-01-01")
    _cartao(client, h, cols["doing"]["id"], titulo="Também andando")
    client.patch(f"/api/missoes/cartoes/{feito['id']}",
                 json={"concluido": True, "versao": feito["versao"]}, headers=h)

    met = client.get(f"/api/missoes/{m['id']}/metricas", headers=h).get_json()
    t = met["totais"]
    assert t["total"] == 3 and t["abertos"] == 2 and t["concluidos"] == 1
    assert t["atrasados"] == 1 and t["wip"] == 2 and t["sem_responsavel"] == 1
    # peso: 3 concluído de 5 no total (3 + 1 + 1)
    assert met["avanco"]["ponderado"] == 60
    assert met["avanco"]["por_cartao"] == 33
    doing = next(c for c in met["por_coluna"] if c["nome"] == "Fazendo")
    assert doing["excedido"] is True and doing["limite_wip"] == 1
    assert met["throughput"]["concluidos"] == 1
    assert met["cycle_time"]["amostra"] == 1
    nomes = [r["nome"] for r in met["por_responsavel"]]
    assert "Admin Test" in nomes and "(sem responsável)" in nomes


def test_alertas_lista_fatos_acionaveis(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    m, cols = _missao(client, h)
    _cartao(client, h, cols["todo"]["id"], titulo="Vencido",
            prazo="2020-01-01", responsaveis="Admin Test")
    _cartao(client, h, cols["done"]["id"], titulo="Na coluna errada")

    r = client.get("/api/missoes/alertas", headers=h).get_json()
    tipos = {a["tipo"] for a in r["alertas"]}
    assert "cartao_vencido" in tipos
    assert "cartao_sem_responsavel" in tipos
    assert "cartao_done_nao_concluido" in tipos
    assert r["criticos"] >= 1
    assert r["alertas"][0]["severidade"] == "critico"   # ordenado por severidade
    assert all("missao" in a and "cartao_id" in a for a in r["alertas"])


def test_alertas_meus_filtra_por_responsavel(client, tecnico_token, auth_headers):
    h = auth_headers(tecnico_token)
    _, cols = _missao(client, h)
    _cartao(client, h, cols["todo"]["id"], titulo="Meu vencido",
            prazo="2020-01-01", responsaveis="Tecnico Test")
    _cartao(client, h, cols["todo"]["id"], titulo="De outro",
            prazo="2020-01-01", responsaveis="Gestor Test")
    r = client.get("/api/missoes/alertas?meus=1", headers=h).get_json()
    assert {a["cartao"] for a in r["alertas"]} == {"Meu vencido"}


def test_alerta_de_wip_excedido(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    m, cols = _missao(client, h)
    client.patch(f"/api/missoes/colunas/{cols['doing']['id']}",
                 json={"limite_wip": 1}, headers=h)
    _cartao(client, h, cols["doing"]["id"], titulo="1", responsaveis="Admin Test")
    _cartao(client, h, cols["doing"]["id"], titulo="2", responsaveis="Admin Test")
    r = client.get("/api/missoes/alertas", headers=h).get_json()
    wip = [a for a in r["alertas"] if a["tipo"] == "wip_excedido"]
    assert len(wip) == 1 and wip[0]["coluna"] == "Fazendo"


# ── Snapshots ────────────────────────────────────────────────────────────────

def test_snapshot_do_dia_e_idempotente(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    m, cols = _missao(client, h)
    _cartao(client, h, cols["todo"]["id"], prazo="2020-01-01")
    _cartao(client, h, cols["doing"]["id"])
    assert client.post("/api/missoes/snapshot", headers=h).status_code == 200
    client.post("/api/missoes/snapshot", headers=h)      # de novo no mesmo dia
    snaps = client.get(f"/api/missoes/{m['id']}/snapshots", headers=h).get_json()["snapshots"]
    assert len(snaps) == 1                                # atualiza, não duplica
    assert snaps[0]["total"] == 2 and snaps[0]["abertos"] == 2
    assert snaps[0]["atrasados"] == 1 and snaps[0]["wip"] == 1


def test_snapshot_e_restrito_a_gestao(client, tecnico_token, auth_headers):
    assert client.post("/api/missoes/snapshot",
                       headers=auth_headers(tecnico_token)).status_code == 403


# ── Modelos de missão ────────────────────────────────────────────────────────

def test_modelo_salva_e_materializa_nova_missao(client, admin_token, auth_headers):
    """Toda missão nascia com as mesmas 3 colunas vazias."""
    h = auth_headers(admin_token)
    m, cols = _missao(client, h, nome="Validação equipamento")
    client.patch(f"/api/missoes/colunas/{cols['doing']['id']}",
                 json={"limite_wip": 2}, headers=h)
    _cartao(client, h, cols["todo"]["id"], titulo="Abrir RDM", prioridade="alta")

    r = client.post("/api/missoes/modelos",
                    json={"missao_id": m["id"], "nome": "Validação padrão"}, headers=h)
    assert r.status_code == 201
    modelo = r.get_json()["modelo"]
    assert modelo["n_colunas"] == 3 and modelo["n_cartoes"] == 1

    nova = client.post("/api/missoes",
                       json={"nome": "Equipamento Z", "modelo_id": modelo["id"]},
                       headers=h).get_json()["missao"]
    board = client.get(f"/api/missoes/{nova['id']}", headers=h).get_json()["missao"]
    por_nome = {c["nome"]: c for c in board["colunas"]}
    assert set(por_nome) == {"A fazer", "Fazendo", "Concluído"}
    assert por_nome["Fazendo"]["limite_wip"] == 2
    cartoes = por_nome["A fazer"]["cartoes"]
    assert [c["titulo"] for c in cartoes] == ["Abrir RDM"]
    assert cartoes[0]["prioridade"] == "alta"
    # o cartão materializado também nasce com trilha
    hist = client.get(f"/api/missoes/cartoes/{cartoes[0]['id']}/historico",
                      headers=h).get_json()["historico"]
    assert any(x["origem"] == "modelo" for x in hist)


def test_modelo_sem_cartoes(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    m, cols = _missao(client, h)
    _cartao(client, h, cols["todo"]["id"], titulo="Não vai junto")
    modelo = client.post("/api/missoes/modelos",
                         json={"missao_id": m["id"], "nome": "Só estrutura",
                               "com_cartoes": False}, headers=h).get_json()["modelo"]
    assert modelo["n_cartoes"] == 0
    assert client.delete(f"/api/missoes/modelos/{modelo['id']}",
                         headers=h).status_code == 200
    assert client.get("/api/missoes/modelos", headers=h).get_json()["modelos"] == []


# ── Export ───────────────────────────────────────────────────────────────────

def test_export_excel(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    m, cols = _missao(client, h, nome="Missão Export")
    _cartao(client, h, cols["todo"]["id"], titulo="Item", responsaveis="Admin Test")
    r = client.get(f"/api/missoes/{m['id']}/export", headers=h)
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["Content-Type"]
    assert r.data[:2] == b"PK"                     # xlsx é um zip
    assert "Missao_Missao_Export" in r.headers["Content-Disposition"]


# ── Permissões gerais do módulo ──────────────────────────────────────────────

def test_leitura_nao_acessa_nada_de_missoes(client, leitura_token, auth_headers):
    h = auth_headers(leitura_token)
    for url in ("/api/missoes", "/api/missoes/alertas", "/api/missoes/etiquetas",
                "/api/missoes/1/metricas", "/api/missoes/modelos"):
        assert client.get(url, headers=h).status_code == 403, url
