"""Pastas por grupo de documentos (EquipamentoPasta).

A estrutura real de rede não é uma pasta por equipamento nem uma pasta por
documento: manuais ficam numa pasta, IT e checklists em outra, QI/QO/QD em
outra. Antes só existiam dois níveis (pasta do equipamento e exceção por
documento), então apontar os 4 manuais para a pasta deles exigia marcar 4
exceções — e a tela chamava de anomalia o que era a regra.

Os caminhos usam `P:` de propósito: a suíte fixa o apelido `P:=\\\\test-srv\\Projetos$`
(ver conftest), então estes testes também cobrem a canonização na entrada.
"""
import pytest

from models import db, Documento, Equipamento, EquipamentoPasta

UNC = r"\\test-srv\Projetos$"
BASE = r"P:\Eng\Produto X"
PASTA_MANUAIS = BASE + r"\Documentos\Manuais"


def _equip_com_docs(client, h, nome):
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": nome}, headers=h)
    docs = [d for d in client.get("/api/documentos", headers=h).get_json()
            if d["equipamento"] == nome]
    return docs[0]["equipamento_id"], {d["tipo_doc"]: d for d in docs}


# ── resolução em 3 níveis ────────────────────────────────────────────────────
def test_documento_herda_o_caminho_da_pasta(client, admin_token, auth_headers, app):
    h = auth_headers(admin_token)
    eid, por_tipo = _equip_com_docs(client, h, "EQ-PASTA-1")
    client.patch(f"/api/equipamentos/{eid}", json={"armazenamento_base": BASE}, headers=h)

    res = client.post(f"/api/equipamentos/{eid}/pastas",
                      json={"nome": "Manuais", "caminho": PASTA_MANUAIS}, headers=h)
    assert res.status_code == 201
    pasta = res.get_json()["pasta"]
    assert pasta["caminho"] == UNC + r"\Eng\Produto X\Documentos\Manuais"  # canonizado

    manual = por_tipo["Manual_Servico"]
    res = client.patch(f"/api/documentos/{manual['id']}",
                       json={"pasta_id": pasta["id"]}, headers=h)
    assert res.status_code == 200
    d = res.get_json()["documento"]
    assert d["armazenamento"] == ""                    # não virou exceção
    assert d["pasta_nome"] == "Manuais"
    assert d["armazenamento_efetivo"] == pasta["caminho"]
    assert d["armazenamento_origem"] == "pasta"

    # o irmão sem pasta continua no caminho do equipamento
    it = client.get(f"/api/documentos/{por_tipo['IT']['id']}", headers=h).get_json()
    assert it["armazenamento_efetivo"] == UNC + r"\Eng\Produto X"
    assert it["armazenamento_origem"] == "equipamento"


def test_excecao_do_documento_vence_a_pasta(client, admin_token, auth_headers):
    """Manual ES em \\LATAM enquanto o resto do grupo está em \\Manuais: isso sim
    é exceção, e precisa continuar possível."""
    h = auth_headers(admin_token)
    eid, por_tipo = _equip_com_docs(client, h, "EQ-PASTA-2")
    client.patch(f"/api/equipamentos/{eid}", json={"armazenamento_base": BASE}, headers=h)
    pasta = client.post(f"/api/equipamentos/{eid}/pastas",
                        json={"nome": "Manuais", "caminho": PASTA_MANUAIS},
                        headers=h).get_json()["pasta"]

    doc_id = por_tipo["Manual_ES"]["id"]
    client.patch(f"/api/documentos/{doc_id}", json={"pasta_id": pasta["id"]}, headers=h)
    res = client.patch(f"/api/documentos/{doc_id}",
                       json={"armazenamento": PASTA_MANUAIS + r"\LATAM"}, headers=h)
    d = res.get_json()["documento"]
    assert d["armazenamento_origem"] == "documento"
    assert d["armazenamento_efetivo"] == pasta["caminho"] + r"\LATAM"
    assert d["pasta_id"] == pasta["id"]      # segue no grupo, com endereço próprio


def test_salvar_o_caminho_da_propria_pasta_nao_cria_excecao(client, admin_token, auth_headers):
    """Digitar à mão o caminho que a pasta já fornece deve continuar herdando —
    senão qualquer save do formulário criava uma exceção silenciosa."""
    h = auth_headers(admin_token)
    eid, por_tipo = _equip_com_docs(client, h, "EQ-PASTA-3")
    pasta = client.post(f"/api/equipamentos/{eid}/pastas",
                        json={"nome": "Manuais", "caminho": PASTA_MANUAIS},
                        headers=h).get_json()["pasta"]
    doc_id = por_tipo["Manual_Usuario"]["id"]
    client.patch(f"/api/documentos/{doc_id}", json={"pasta_id": pasta["id"]}, headers=h)

    # mesmo caminho, colado na OUTRA grafia (UNC em vez de P:)
    res = client.patch(f"/api/documentos/{doc_id}",
                       json={"armazenamento": pasta["caminho"]}, headers=h)
    d = res.get_json()["documento"]
    assert d["armazenamento"] == ""
    assert d["armazenamento_origem"] == "pasta"


def test_trocar_de_pasta_desfaz_a_excecao_anterior(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    eid, por_tipo = _equip_com_docs(client, h, "EQ-PASTA-4")
    p1 = client.post(f"/api/equipamentos/{eid}/pastas",
                     json={"nome": "Manuais", "caminho": PASTA_MANUAIS},
                     headers=h).get_json()["pasta"]
    p2 = client.post(f"/api/equipamentos/{eid}/pastas",
                     json={"nome": "QI/QO/QD", "caminho": BASE + r"\Documentos\QIQOQD"},
                     headers=h).get_json()["pasta"]

    doc_id = por_tipo["QIQOQD"]["id"]
    client.patch(f"/api/documentos/{doc_id}",
                 json={"armazenamento": BASE + r"\Solto"}, headers=h)
    res = client.patch(f"/api/documentos/{doc_id}", json={"pasta_id": p2["id"]}, headers=h)
    d = res.get_json()["documento"]
    assert d["armazenamento"] == ""                       # exceção desfeita
    assert d["armazenamento_efetivo"] == p2["caminho"]
    assert p1["id"] != p2["id"]


# ── API de pastas ────────────────────────────────────────────────────────────
def test_nome_duplicado_e_rejeitado(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    eid, _ = _equip_com_docs(client, h, "EQ-PASTA-5")
    client.post(f"/api/equipamentos/{eid}/pastas",
                json={"nome": "Manuais", "caminho": PASTA_MANUAIS}, headers=h)
    res = client.post(f"/api/equipamentos/{eid}/pastas",
                      json={"nome": "manuais", "caminho": BASE + r"\Outra"}, headers=h)
    assert res.status_code == 409


def test_pasta_de_outro_equipamento_e_rejeitada(client, admin_token, auth_headers):
    """Sem esta checagem um documento poderia apontar para a pasta de outro produto."""
    h = auth_headers(admin_token)
    eid_a, por_tipo_a = _equip_com_docs(client, h, "EQ-PASTA-6A")
    eid_b, _ = _equip_com_docs(client, h, "EQ-PASTA-6B")
    alheia = client.post(f"/api/equipamentos/{eid_b}/pastas",
                         json={"nome": "Manuais", "caminho": PASTA_MANUAIS},
                         headers=h).get_json()["pasta"]
    res = client.patch(f"/api/documentos/{por_tipo_a['IT']['id']}",
                       json={"pasta_id": alheia["id"]}, headers=h)
    assert res.status_code == 400
    assert "Pasta inválida" in res.get_json()["erro"]


@pytest.mark.parametrize("bruto", ["abc", "1; DROP TABLE", 1.5, [3], {"id": 3}])
def test_pasta_id_nao_numerico_da_400_e_nao_500(client, admin_token, auth_headers, bruto):
    """O id vem do cliente: `int()` cru virava ValueError não tratado — 500 onde
    a resposta certa é a mesma de uma pasta que não existe."""
    h = auth_headers(admin_token)
    _, por_tipo = _equip_com_docs(client, h, f"EQ-PASTA-ID-{abs(hash(str(bruto)))}")
    res = client.patch(f"/api/documentos/{por_tipo['IT']['id']}",
                       json={"pasta_id": bruto}, headers=h)
    assert res.status_code == 400
    assert "Pasta inválida" in res.get_json()["erro"]


def test_lista_de_equipamentos_nao_consulta_pastas_uma_vez_por_linha(
        client, admin_token, auth_headers, app):
    """`Equipamento.to_dict()` serializa as pastas e `/api/equipamentos`
    serializa a lista inteira: com o backref em `lazy="select"` era uma consulta
    por equipamento — o mesmo N+1 que `DocumentoArquivo` já evitava com
    `selectin`."""
    from sqlalchemy import event

    h = auth_headers(admin_token)
    for i in range(4):
        eid, _ = _equip_com_docs(client, h, f"EQ-NMAIS1-{i}")
        client.post(f"/api/equipamentos/{eid}/pastas",
                    json={"nome": "Manuais", "caminho": PASTA_MANUAIS}, headers=h)

    consultas = []
    engine = db.engines[None]

    def _contar(conn, cursor, stmt, params, ctx, many):
        if "equipamento_pastas" in stmt.lower():
            consultas.append(stmt)

    event.listen(engine, "before_cursor_execute", _contar)
    try:
        res = client.get("/api/equipamentos", headers=h)
    finally:
        event.remove(engine, "before_cursor_execute", _contar)

    assert res.status_code == 200
    assert len(res.get_json()) >= 4
    assert len(consultas) <= 1, f"N+1: {len(consultas)} consultas de pastas na lista"


def test_remover_pasta_devolve_os_documentos_ao_equipamento(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    eid, por_tipo = _equip_com_docs(client, h, "EQ-PASTA-7")
    client.patch(f"/api/equipamentos/{eid}", json={"armazenamento_base": BASE}, headers=h)
    pasta = client.post(f"/api/equipamentos/{eid}/pastas",
                        json={"nome": "Manuais", "caminho": PASTA_MANUAIS},
                        headers=h).get_json()["pasta"]
    doc_id = por_tipo["Manual_Servico"]["id"]
    client.patch(f"/api/documentos/{doc_id}", json={"pasta_id": pasta["id"]}, headers=h)

    res = client.delete(f"/api/equipamentos/{eid}/pastas/{pasta['id']}", headers=h)
    assert res.status_code == 200
    assert res.get_json()["documentos_desvinculados"] == 1

    d = client.get(f"/api/documentos/{doc_id}", headers=h).get_json()
    assert d["pasta_id"] is None
    assert d["armazenamento_efetivo"] == UNC + r"\Eng\Produto X"
    assert client.get(f"/api/equipamentos/{eid}/pastas", headers=h).get_json() == []


def test_pastas_aparecem_no_equipamento(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    eid, _ = _equip_com_docs(client, h, "EQ-PASTA-8")
    client.post(f"/api/equipamentos/{eid}/pastas",
                json={"nome": "Manuais", "caminho": PASTA_MANUAIS, "ordem": 1}, headers=h)
    client.post(f"/api/equipamentos/{eid}/pastas",
                json={"nome": "IT e Checklist", "caminho": BASE + r"\Documentos\IT", "ordem": 0},
                headers=h)
    eq = client.get(f"/api/equipamentos/{eid}", headers=h).get_json()
    assert [p["nome"] for p in eq["pastas"]] == ["IT e Checklist", "Manuais"]


# ── backfill a partir dos dados já existentes ────────────────────────────────
def test_backfill_materializa_os_grupos_existentes(app, client, admin_token, auth_headers):
    """Reproduz o Amplio 16 dos dados reais: base para IT/checklists e três
    caminhos distintos entre os manuais. O backfill tem de virar 4 pastas sem
    mudar o caminho efetivo de nenhum documento."""
    from servidor import _backfill_pastas_equipamento
    h = auth_headers(admin_token)
    eid, por_tipo = _equip_com_docs(client, h, "EQ-BACKFILL")

    manuais = BASE + r"\Documentos\Manuais"
    latam = BASE + r"\Documentos\Manual de Usuário\LATAM"
    dash = BASE + r"\Documentos\Manual de Usuário\Manual Dash"
    with app.app_context():
        equip = Equipamento.query.get(eid)
        equip.armazenamento_base = BASE
        atribui = {"Manual_Servico": manuais, "Spare_Parts": manuais,
                   "QIQOQD": manuais, "Manual_ES": latam, "Manual_Usuario": dash}
        for tipo, caminho in atribui.items():
            Documento.query.get(por_tipo[tipo]["id"]).armazenamento = caminho
        db.session.commit()

        # canonizado dos dois lados: o seed acima escreve direto no banco, sem
        # passar pela API que canoniza — a comparação é de LOCAL, não de grafia
        import caminhos as _c
        antes = {d.tipo_doc: _c.normalizar(d.armazenamento_efetivo)
                 for d in Documento.query.filter_by(equipamento_id=eid).all()}
        _backfill_pastas_equipamento()

        pastas = EquipamentoPasta.query.filter_by(equipamento_id=eid).all()
        assert len(pastas) == 4
        assert {p.nome for p in pastas} == {"Principal", "Manuais", "LATAM", "Manual Dash"}

        depois = {}
        for d in Documento.query.filter_by(equipamento_id=eid).all():
            depois[d.tipo_doc] = _c.normalizar(d.armazenamento_efetivo)
            assert d.armazenamento == ""      # o caminho passou para a pasta
            assert d.pasta_id is not None
        assert depois == antes                # nenhum documento mudou de lugar

        # idempotente: rodar de novo não duplica
        _backfill_pastas_equipamento()
        assert EquipamentoPasta.query.filter_by(equipamento_id=eid).count() == 4


def test_backfill_desempata_folhas_de_mesmo_nome(app, client, admin_token, auth_headers):
    """`...\\A\\Manuais` e `...\\B\\Manuais` não podem virar duas pastas "Manuais"."""
    from servidor import _backfill_pastas_equipamento
    h = auth_headers(admin_token)
    eid, por_tipo = _equip_com_docs(client, h, "EQ-BACKFILL-2")
    with app.app_context():
        Equipamento.query.get(eid).armazenamento_base = BASE
        Documento.query.get(por_tipo["Manual_ES"]["id"]).armazenamento = BASE + r"\A\Manuais"
        Documento.query.get(por_tipo["Manual_Servico"]["id"]).armazenamento = BASE + r"\B\Manuais"
        db.session.commit()
        _backfill_pastas_equipamento()
        nomes = {p.nome for p in EquipamentoPasta.query.filter_by(equipamento_id=eid).all()}
        assert len(nomes) == 3
        assert nomes == {"Principal", "A\\Manuais", "B\\Manuais"}
