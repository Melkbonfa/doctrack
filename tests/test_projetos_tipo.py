"""Testes: tipos de projeto (cadastráveis), modelos de entregáveis e exclusão."""


def _seed_modelo(app, tipo_projeto="OEM"):
    from models import db, ModeloEntregavel
    with app.app_context():
        db.session.add_all([
            ModeloEntregavel(tipo_projeto=tipo_projeto, categoria="Produto",
                             tipo="Protótipo", responsavel_padrao="Eng", ordem=0),
            ModeloEntregavel(tipo_projeto=tipo_projeto, categoria="Documentação",
                             tipo="Manual", responsavel_padrao="Doc", ordem=1),
        ])
        db.session.commit()


# ── Criação com tipo copia o modelo ──────────────────────────────────────────

def test_criar_projeto_com_tipo_copia_modelo(app, client, admin_token, auth_headers):
    _seed_modelo(app, "OEM")
    h = auth_headers(admin_token)
    res = client.post("/api/projetos", json={"nome": "Novo OEM", "tipo": "OEM"}, headers=h)
    assert res.status_code == 201, res.get_json()
    pid = res.get_json()["projeto"]["id"]

    det = client.get(f"/api/projetos/{pid}", headers=h).get_json()
    nomes = sorted(e["tipo"] for c in det["categorias"] for e in c["entregaveis"])
    assert nomes == ["Manual", "Protótipo"]
    assert det["tipo"] == "OEM"


def test_criar_projeto_com_lista_explicita_ignora_modelo(app, client, admin_token, auth_headers):
    _seed_modelo(app, "OEM")
    h = auth_headers(admin_token)
    res = client.post("/api/projetos", json={
        "nome": "Lista própria", "tipo": "OEM",
        "entregaveis": [{"tipo": "Só esse", "categoria": "Produto"}],
    }, headers=h)
    assert res.status_code == 201
    pid = res.get_json()["projeto"]["id"]
    det = client.get(f"/api/projetos/{pid}", headers=h).get_json()
    nomes = [e["tipo"] for c in det["categorias"] for e in c["entregaveis"]]
    assert nomes == ["Só esse"]


def test_lista_do_projeto_independe_do_modelo(app, client, admin_token, auth_headers):
    _seed_modelo(app, "OEM")
    h = auth_headers(admin_token)
    pid = client.post("/api/projetos", json={"nome": "P", "tipo": "OEM"},
                      headers=h).get_json()["projeto"]["id"]
    # apaga TODOS os itens do modelo OEM
    mods = client.get("/api/modelos?tipo=OEM", headers=h).get_json()["modelos"]["OEM"]
    for m in mods:
        client.delete(f"/api/modelos/{m['id']}", headers=h)
    # o projeto mantém seus entregáveis (cópia independente)
    det = client.get(f"/api/projetos/{pid}", headers=h).get_json()
    total = sum(len(c["entregaveis"]) for c in det["categorias"])
    assert total == 2


def test_tipo_invalido_retorna_400(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    res = client.post("/api/projetos", json={"nome": "X", "tipo": "Outro"}, headers=h)
    assert res.status_code == 400


# ── Excluir entregável ───────────────────────────────────────────────────────

def test_excluir_entregavel(app, client, admin_token, auth_headers):
    from models import db, Projeto, Entregavel
    h = auth_headers(admin_token)
    with app.app_context():
        p = Projeto(nome="Del", ano=2026)
        db.session.add(p); db.session.flush()
        e = Entregavel(projeto_id=p.id, tipo="X", categoria="Produto", status="pendente")
        db.session.add(e); db.session.commit()
        eid = e.id
    res = client.delete(f"/api/entregaveis/{eid}", headers=h)
    assert res.status_code == 200
    assert client.delete(f"/api/entregaveis/{eid}", headers=h).status_code == 404


def test_excluir_entregavel_negado_para_leitura(app, client, leitura_token, auth_headers):
    from models import db, Projeto, Entregavel
    with app.app_context():
        p = Projeto(nome="Del2", ano=2026)
        db.session.add(p); db.session.flush()
        e = Entregavel(projeto_id=p.id, tipo="X", categoria="Produto")
        db.session.add(e); db.session.commit()
        eid = e.id
    res = client.delete(f"/api/entregaveis/{eid}", headers=auth_headers(leitura_token))
    assert res.status_code in (401, 403)


# ── CRUD de modelos ──────────────────────────────────────────────────────────

def test_modelos_crud(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    # adicionar
    res = client.post("/api/modelos", json={
        "tipo_projeto": "Revenda", "categoria": "Marketing",
        "tipo": "Catálogo", "responsavel_padrao": "Mkt"}, headers=h)
    assert res.status_code == 201
    mid = res.get_json()["modelo"]["id"]
    # listar
    data = client.get("/api/modelos", headers=h).get_json()
    assert any(m["tipo"] == "Catálogo" for m in data["modelos"]["Revenda"])
    # editar
    r = client.put(f"/api/modelos/{mid}", json={"tipo": "Catálogo 2"}, headers=h)
    assert r.status_code == 200 and r.get_json()["modelo"]["tipo"] == "Catálogo 2"
    # excluir
    assert client.delete(f"/api/modelos/{mid}", headers=h).status_code == 200


def test_modelo_tipo_projeto_invalido(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    res = client.post("/api/modelos", json={"tipo_projeto": "X", "tipo": "Y"}, headers=h)
    assert res.status_code == 400


# ── Tipos de projeto cadastráveis ────────────────────────────────────────────

def _tipos(client, h):
    return {t["nome"]: t for t in
            client.get("/api/tipos-projeto", headers=h).get_json()["tipos"]}


def test_tipos_padrao_vem_do_cadastro(client, admin_token, auth_headers):
    assert list(_tipos(client, auth_headers(admin_token))) == ["OEM", "Revenda"]


def test_criar_tipo_libera_projeto_e_modelo(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    # antes de existir, o tipo é recusado
    assert client.post("/api/projetos", json={"nome": "P", "tipo": "Locação"},
                       headers=h).status_code == 400

    res = client.post("/api/tipos-projeto", json={"nome": "  Locação ", "area": "pde"}, headers=h)
    assert res.status_code == 201, res.get_json()
    assert res.get_json()["tipo"]["nome"] == "Locação"

    # passa a valer no modelo e no projeto, que nasce com a lista do tipo novo
    assert client.post("/api/modelos", json={"tipo_projeto": "Locação", "tipo": "Contrato"},
                       headers=h).status_code == 201
    modelos = client.get("/api/modelos", headers=h).get_json()
    assert modelos["tipos"] == ["OEM", "Revenda", "Locação"]
    pid = client.post("/api/projetos", json={"nome": "P", "tipo": "Locação"},
                      headers=h).get_json()["projeto"]["id"]
    det = client.get(f"/api/projetos/{pid}", headers=h).get_json()
    assert [e["tipo"] for c in det["categorias"] for e in c["entregaveis"]] == ["Contrato"]

    t = _tipos(client, h)["Locação"]
    assert (t["projetos"], t["itens_modelo"]) == (1, 1)


def test_criar_tipo_copiando_modelo_de_outro(app, client, admin_token, auth_headers):
    _seed_modelo(app, "OEM")
    h = auth_headers(admin_token)
    res = client.post("/api/tipos-projeto", json={"nome": "ODM", "area": "pde", "copiar_de": "OEM"}, headers=h)
    assert res.status_code == 201 and res.get_json()["tipo"]["itens_modelo"] == 2
    modelos = client.get("/api/modelos", headers=h).get_json()["modelos"]
    assert [m["tipo"] for m in modelos["ODM"]] == ["Protótipo", "Manual"]
    # cópia independente: o modelo de origem continua com os itens dele
    assert len(modelos["OEM"]) == 2

    assert client.post("/api/tipos-projeto", json={"nome": "X", "area": "pde", "copiar_de": "Nada"},
                       headers=h).status_code == 400


def test_nome_de_tipo_invalido(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    assert client.post("/api/tipos-projeto", json={"nome": "  ", "area": "pde"}, headers=h).status_code == 400
    assert client.post("/api/tipos-projeto", json={"nome": "x" * 21, "area": "pde"}, headers=h).status_code == 400
    # duplicado, sem diferenciar maiúsculas
    assert client.post("/api/tipos-projeto", json={"nome": "oem", "area": "pde"}, headers=h).status_code == 409


def test_renomear_tipo_propaga_para_projetos_e_modelo(app, client, admin_token, auth_headers):
    _seed_modelo(app, "Revenda")
    h = auth_headers(admin_token)
    pid = client.post("/api/projetos", json={"nome": "P", "tipo": "Revenda"},
                      headers=h).get_json()["projeto"]["id"]
    client.delete(f"/api/projetos/{pid}", headers=h)   # arquivado também é renomeado
    tid = _tipos(client, h)["Revenda"]["id"]

    assert client.put(f"/api/tipos-projeto/{tid}", json={"nome": "OEM"},
                      headers=h).status_code == 409
    res = client.put(f"/api/tipos-projeto/{tid}", json={"nome": "Distribuição"}, headers=h)
    assert res.status_code == 200 and res.get_json()["tipo"]["nome"] == "Distribuição"

    assert client.get(f"/api/projetos/{pid}", headers=h).get_json()["tipo"] == "Distribuição"
    modelos = client.get("/api/modelos", headers=h).get_json()
    assert modelos["tipos"] == ["OEM", "Distribuição"]
    assert len(modelos["modelos"]["Distribuição"]) == 2
    assert "Revenda" not in modelos["modelos"]


def test_excluir_tipo_em_uso_e_recusado(app, client, admin_token, auth_headers):
    _seed_modelo(app, "Revenda")
    h = auth_headers(admin_token)
    pid = client.post("/api/projetos", json={"nome": "P", "tipo": "Revenda"},
                      headers=h).get_json()["projeto"]["id"]
    tid = _tipos(client, h)["Revenda"]["id"]

    # em uso — e arquivar o projeto não libera
    assert client.delete(f"/api/tipos-projeto/{tid}", headers=h).status_code == 409
    client.delete(f"/api/projetos/{pid}", headers=h)
    assert client.delete(f"/api/tipos-projeto/{tid}", headers=h).status_code == 409

    # trocado o tipo do projeto, sai o tipo e o modelo dele junto
    client.post(f"/api/projetos/{pid}/restaurar", headers=h)
    assert client.put(f"/api/projetos/{pid}", json={"tipo": "OEM"}, headers=h).status_code == 200
    assert client.delete(f"/api/tipos-projeto/{tid}", headers=h).status_code == 200
    modelos = client.get("/api/modelos", headers=h).get_json()
    assert modelos["tipos"] == ["OEM"] and "Revenda" not in modelos["modelos"]
    assert client.post("/api/projetos", json={"nome": "Q", "tipo": "Revenda"},
                       headers=h).status_code == 400


def test_editar_projeto_mantem_tipo_fora_do_cadastro(app, client, admin_token, auth_headers):
    """O formulário reenvia o tipo em toda edição: dado legado não pode travá-la."""
    from models import db, Projeto
    h = auth_headers(admin_token)
    with app.app_context():
        p = Projeto(nome="Legado", ano=2026, tipo="Antigo")
        db.session.add(p); db.session.commit()
        pid = p.id
    res = client.put(f"/api/projetos/{pid}", json={"nome": "Legado 2", "tipo": "Antigo"}, headers=h)
    assert res.status_code == 200, res.get_json()
    # mas trocar PARA um tipo inexistente continua recusado
    assert client.put(f"/api/projetos/{pid}", json={"tipo": "Outro"}, headers=h).status_code == 400


def test_tipos_so_gestao_altera(client, tecnico_token, leitura_token, auth_headers):
    ht = auth_headers(tecnico_token)
    assert client.get("/api/tipos-projeto", headers=ht).status_code == 200
    assert client.post("/api/tipos-projeto", json={"nome": "T"}, headers=ht).status_code in (401, 403)
    assert client.delete("/api/tipos-projeto/1", headers=ht).status_code in (401, 403)
    assert client.get("/api/tipos-projeto",
                      headers=auth_headers(leitura_token)).status_code in (401, 403)


# ── Arquivar / restaurar projeto ─────────────────────────────────────────────

def test_arquivar_some_da_lista_e_restaurar_traz_de_volta(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    pid = client.post("/api/projetos", json={"nome": "Arquivável", "tipo": "OEM"}, headers=h).get_json()["projeto"]["id"]

    # arquiva → some da lista de ativos, aparece na de arquivados
    assert client.delete(f"/api/projetos/{pid}", headers=h).status_code == 200
    ativos = client.get("/api/projetos", headers=h).get_json()["projetos"]
    assert all(p["id"] != pid for p in ativos)
    arq = client.get("/api/projetos?arquivados=1", headers=h).get_json()["projetos"]
    assert any(p["id"] == pid for p in arq)

    # restaura → volta para ativos
    r = client.post(f"/api/projetos/{pid}/restaurar", headers=h)
    assert r.status_code == 200 and r.get_json()["projeto"]["ativo"] is True
    ativos2 = client.get("/api/projetos", headers=h).get_json()["projetos"]
    assert any(p["id"] == pid for p in ativos2)
