"""Testes: tipo de projeto (OEM/Revenda), modelos de entregáveis e exclusão."""


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


# ── Arquivar / restaurar projeto ─────────────────────────────────────────────

def test_arquivar_some_da_lista_e_restaurar_traz_de_volta(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    pid = client.post("/api/projetos", json={"nome": "Arquivável"}, headers=h).get_json()["projeto"]["id"]

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
