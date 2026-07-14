"""Testes das revisões manuais do IDP (campos rev_* do equipamento)."""


def _criar_equip(client, h, nome="RevTest"):
    res = client.post("/api/equipamentos", json={"nome": nome}, headers=h)
    assert res.status_code == 201, res.get_json()
    return res.get_json()["equipamento"]["id"]


def test_to_dict_expoe_campos_novos(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    eq = client.post("/api/equipamentos", json={"nome": "RevDefault"}, headers=h).get_json()["equipamento"]
    # Defaults: revisões "Pendente", Pareto vazio/zero.
    assert eq["rev_cadastro"] == "Pendente"
    assert eq["rev_estrutura"] == "Pendente"
    assert eq["rev_descritivo"] == "Pendente"
    assert eq["pareto_classe"] == ""
    assert eq["qtd_saidas"] == 0


def test_patch_aceita_estado_valido(client, tecnico_token, auth_headers):
    h = auth_headers(tecnico_token)
    eq_id = _criar_equip(client, h)
    res = client.patch(f"/api/equipamentos/{eq_id}",
                       json={"rev_cadastro": "Revisado", "rev_estrutura": "Em revisão",
                             "rev_descritivo": "N/A"}, headers=h)
    assert res.status_code == 200
    eq = res.get_json()["equipamento"]
    assert eq["rev_cadastro"] == "Revisado"
    assert eq["rev_estrutura"] == "Em revisão"
    assert eq["rev_descritivo"] == "N/A"


def test_patch_ignora_estado_invalido(client, tecnico_token, auth_headers):
    h = auth_headers(tecnico_token)
    eq_id = _criar_equip(client, h, nome="RevInvalido")
    # valor fora de ESTADOS_REVISAO não deve alterar o estado (fica no default).
    res = client.patch(f"/api/equipamentos/{eq_id}",
                       json={"rev_cadastro": "Concluído??"}, headers=h)
    assert res.status_code == 200
    assert res.get_json()["equipamento"]["rev_cadastro"] == "Pendente"


def test_patch_nao_grava_pareto_pelo_usuario(client, admin_token, auth_headers):
    """pareto_classe/qtd_saidas só entram pelo importador, não pelo PATCH comum."""
    h = auth_headers(admin_token)
    eq_id = _criar_equip(client, h, nome="RevPareto")
    res = client.patch(f"/api/equipamentos/{eq_id}",
                       json={"pareto_classe": "A", "qtd_saidas": 999}, headers=h)
    assert res.status_code == 200
    eq = res.get_json()["equipamento"]
    assert eq["pareto_classe"] == ""
    assert eq["qtd_saidas"] == 0
