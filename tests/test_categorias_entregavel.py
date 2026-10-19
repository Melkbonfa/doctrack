"""Testes: categorias de entregável cadastráveis (criar, usar, ordenar,
renomear, excluir)."""
import pytest

URL = "/api/categorias-entregavel"


def _cats(client, token, auth_headers):
    return client.get(URL, headers=auth_headers(token)).get_json()["categorias"]


def _cat(client, token, auth_headers, nome):
    return next(c for c in _cats(client, token, auth_headers) if c["nome"] == nome)


@pytest.fixture
def projeto(app):
    """Um projeto com um entregável de Produto e um de Sistema."""
    from models import db, Projeto, Entregavel
    with app.app_context():
        p = Projeto(nome="Cats", ano=2026)
        db.session.add(p)
        db.session.flush()
        db.session.add_all([
            Entregavel(projeto_id=p.id, tipo="A", categoria="Produto"),
            Entregavel(projeto_id=p.id, tipo="B", categoria="Sistema")])
        db.session.commit()
        return p.id


def _abas(client, token, auth_headers, pid):
    det = client.get(f"/api/projetos/{pid}", headers=auth_headers(token)).get_json()
    return [c["categoria"] for c in det["categorias"]]


# ── Listar / criar ───────────────────────────────────────────────────────────

def test_lista_as_padrao_com_uso(client, gestor_token, auth_headers, projeto):
    cats = _cats(client, gestor_token, auth_headers)
    assert [c["nome"] for c in cats] == [
        "Produto", "Sistema", "Documentação", "Capacitação", "Marketing"]
    assert cats[0]["entregaveis"] == 1 and cats[0]["itens_modelo"] == 0
    assert cats[2]["entregaveis"] == 0


def test_criar_categoria_entra_no_fim(client, gestor_token, auth_headers):
    res = client.post(URL, json={"nome": "  Regulatório  "}, headers=auth_headers(gestor_token))
    assert res.status_code == 201, res.get_json()
    assert res.get_json()["categoria"]["nome"] == "Regulatório"
    assert _cats(client, gestor_token, auth_headers)[-1]["nome"] == "Regulatório"


@pytest.mark.parametrize("nome, status", [("", 400), ("x" * 41, 400), ("produto", 409)])
def test_criar_categoria_invalida(client, gestor_token, auth_headers, nome, status):
    res = client.post(URL, json={"nome": nome}, headers=auth_headers(gestor_token))
    assert res.status_code == status


def test_tecnico_le_mas_nao_cria(client, tecnico_token, auth_headers):
    h = auth_headers(tecnico_token)
    assert client.get(URL, headers=h).status_code == 200
    assert client.post(URL, json={"nome": "Nova"}, headers=h).status_code == 403


# ── Uso nos entregáveis e modelos ────────────────────────────────────────────

def test_categoria_nova_vale_no_entregavel_e_no_modelo(client, gestor_token, auth_headers, projeto):
    h = auth_headers(gestor_token)
    client.post(URL, json={"nome": "Regulatório"}, headers=h)
    res = client.post(f"/api/projetos/{projeto}/entregaveis", headers=h,
                      json={"tipo": "Registro", "categoria": "regulatório"})
    assert res.status_code == 201, res.get_json()
    assert res.get_json()["entregavel"]["categoria"] == "Regulatório"   # nome do cadastro
    assert _abas(client, gestor_token, auth_headers, projeto)[-1] == "Regulatório"

    res = client.post("/api/modelos", headers=h, json={
        "tipo_projeto": "OEM", "tipo": "Registro", "categoria": "Regulatório"})
    assert res.status_code == 201, res.get_json()


def test_categoria_fora_do_cadastro_e_recusada(client, gestor_token, auth_headers, projeto):
    h = auth_headers(gestor_token)
    res = client.post(f"/api/projetos/{projeto}/entregaveis", headers=h,
                      json={"tipo": "X", "categoria": "Inexistente"})
    assert res.status_code == 400
    res = client.post("/api/modelos", headers=h, json={
        "tipo_projeto": "OEM", "tipo": "X", "categoria": "Inexistente"})
    assert res.status_code == 400
    res = client.post("/api/projetos", headers=h, json={
        "nome": "P", "tipo": "OEM",
        "entregaveis": [{"tipo": "X", "categoria": "Inexistente"}]})
    assert res.status_code == 400


def test_sem_categoria_cai_na_primeira(client, gestor_token, auth_headers, projeto):
    res = client.post(f"/api/projetos/{projeto}/entregaveis",
                      headers=auth_headers(gestor_token), json={"tipo": "Sem cat"})
    assert res.status_code == 201
    assert res.get_json()["entregavel"]["categoria"] == "Produto"


def test_item_de_modelo_legado_continua_editavel(app, client, gestor_token, auth_headers):
    """Categoria que não está no cadastro não trava a edição do resto do item."""
    from models import db, ModeloEntregavel
    with app.app_context():
        m = ModeloEntregavel(tipo_projeto="OEM", categoria="Antiga", tipo="Item")
        db.session.add(m)
        db.session.commit()
        mid = m.id
    res = client.put(f"/api/modelos/{mid}", headers=auth_headers(gestor_token),
                     json={"tipo": "Item 2", "categoria": "Antiga"})
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["modelo"]["categoria"] == "Antiga"


# ── Ordem ────────────────────────────────────────────────────────────────────

def test_ordem_do_cadastro_e_a_das_abas(client, gestor_token, auth_headers, projeto):
    assert _abas(client, gestor_token, auth_headers, projeto) == ["Produto", "Sistema"]
    ids = [c["id"] for c in _cats(client, gestor_token, auth_headers)]
    ids[0], ids[1] = ids[1], ids[0]
    res = client.put(f"{URL}/ordem", json={"ids": ids}, headers=auth_headers(gestor_token))
    assert res.status_code == 200, res.get_json()
    assert _abas(client, gestor_token, auth_headers, projeto) == ["Sistema", "Produto"]


def test_reordenar_exige_todas(client, gestor_token, auth_headers):
    ids = [c["id"] for c in _cats(client, gestor_token, auth_headers)]
    res = client.put(f"{URL}/ordem", json={"ids": ids[:-1]}, headers=auth_headers(gestor_token))
    assert res.status_code == 400


# ── Renomear / excluir ───────────────────────────────────────────────────────

def test_renomear_propaga_sem_contar_como_atualizacao(app, client, gestor_token,
                                                      auth_headers, projeto):
    from models import Entregavel, ModeloEntregavel, db
    with app.app_context():
        db.session.add(ModeloEntregavel(tipo_projeto="OEM", categoria="Produto", tipo="M"))
        db.session.commit()
        antes = {e.id: e.atualizado_em for e in Entregavel.query.filter_by(projeto_id=projeto)}
    cid = _cat(client, gestor_token, auth_headers, "Produto")["id"]
    res = client.put(f"{URL}/{cid}", json={"nome": "Hardware"}, headers=auth_headers(gestor_token))
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["categoria"]["entregaveis"] == 1
    assert _abas(client, gestor_token, auth_headers, projeto) == ["Hardware", "Sistema"]
    with app.app_context():
        assert ModeloEntregavel.query.filter_by(categoria="Hardware").count() == 1
        assert ModeloEntregavel.query.filter_by(categoria="Produto").count() == 0
        depois = {e.id: e.atualizado_em for e in Entregavel.query.filter_by(projeto_id=projeto)}
    assert depois == antes


def test_renomear_para_nome_existente_e_recusado(client, gestor_token, auth_headers):
    cid = _cat(client, gestor_token, auth_headers, "Produto")["id"]
    res = client.put(f"{URL}/{cid}", json={"nome": "SISTEMA"}, headers=auth_headers(gestor_token))
    assert res.status_code == 409


def test_excluir_categoria_em_uso_e_recusado(client, gestor_token, auth_headers, projeto):
    cid = _cat(client, gestor_token, auth_headers, "Produto")["id"]
    res = client.delete(f"{URL}/{cid}", headers=auth_headers(gestor_token))
    assert res.status_code == 409
    assert "Produto" in [c["nome"] for c in _cats(client, gestor_token, auth_headers)]


def test_excluir_categoria_sem_uso(client, gestor_token, auth_headers):
    cid = _cat(client, gestor_token, auth_headers, "Marketing")["id"]
    res = client.delete(f"{URL}/{cid}", headers=auth_headers(gestor_token))
    assert res.status_code == 200
    assert "Marketing" not in [c["nome"] for c in _cats(client, gestor_token, auth_headers)]


def test_nao_exclui_a_ultima(client, gestor_token, auth_headers):
    h = auth_headers(gestor_token)
    *outras, ultima = _cats(client, gestor_token, auth_headers)
    for c in outras:
        assert client.delete(f"{URL}/{c['id']}", headers=h).status_code == 200
    assert client.delete(f"{URL}/{ultima['id']}", headers=h).status_code == 409
