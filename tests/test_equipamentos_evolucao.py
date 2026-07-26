"""Testes da evolução do módulo de Equipamentos.

Cobre o que mudou de comportamento: ICE calculado no servidor (com validade
ANVISA vencida deixando de contar), trilha de-para, série temporal, integridade
de SKU, export com filtros e a linha de produto que era campo morto.
"""
from datetime import date, timedelta

import pytest


def _criar(client, h, **campos):
    payload = {"nome": campos.pop("nome", "EqTeste"), **campos}
    res = client.post("/api/equipamentos", json=payload, headers=h)
    assert res.status_code == 201, res.get_json()
    return res.get_json()["equipamento"]


def _completude(client, h, equip_id):
    res = client.get("/api/equipamentos/completude", headers=h)
    assert res.status_code == 200
    itens = {i["id"]: i for i in res.get_json()["itens"]}
    return itens[equip_id]


def _dias(n):
    return (date.today() + timedelta(days=n)).isoformat()


# ── ICE: a correção da validade vencida ──────────────────────────────────────
def test_validade_vencida_nao_conta_como_preenchida(client, admin_token, auth_headers):
    """Era o furo antigo: o cliente só olhava se o campo tinha texto, então um
    registro vencido em 2023 dava 100% de regulatório."""
    h = auth_headers(admin_token)
    base = {"classificacao_reg": "IVD", "anvisa": "123", "anvisa_registro": "2020-01-01"}
    vencido = _criar(client, h, nome="Vencido", anvisa_validade="2023-01-01", **base)
    valido = _criar(client, h, nome="Valido", anvisa_validade=_dias(400), **base)

    assert _completude(client, h, vencido["id"])["reg"] == 75    # 3 de 4 campos
    assert _completude(client, h, valido["id"])["reg"] == 100


def test_validade_proxima_ainda_conta_mas_sinaliza(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    eq = _criar(client, h, nome="Vencendo", classificacao_reg="IVD", anvisa="123",
                anvisa_registro="2020-01-01", anvisa_validade=_dias(30))
    c = _completude(client, h, eq["id"])
    assert c["reg"] == 100                 # ainda válido
    assert c["reg_estado"] == "vencendo"   # mas precisa renovar
    assert 0 < c["reg_dias"] <= 90


def test_ruo_nao_exige_anvisa(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    eq = _criar(client, h, nome="RUO", classificacao_reg="RUO")
    assert _completude(client, h, eq["id"])["reg"] == 100


def test_denominador_documental_usa_os_12_tipos(client, admin_token, auth_headers):
    """O fallback do cliente era 9 (número de quando o módulo nasceu)."""
    h = auth_headers(admin_token)
    eq = _criar(client, h, nome="DozeTipos")
    c = _completude(client, h, eq["id"])
    # Nasce com 12 documentos, 3 deles opcionais (N/A) → 9 aplicáveis.
    assert c["docs_total"] == 12
    assert c["docs_alvo"] == 9
    assert c["doc"] == 0


def test_completude_traz_idp_e_revisoes(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    eq = _criar(client, h, nome="ComIDP")
    client.patch(f"/api/equipamentos/{eq['id']}",
                 json={"rev_cadastro": "Revisado", "rev_estrutura": "N/A"}, headers=h)
    c = _completude(client, h, eq["id"])
    assert c["rev"]["cadastro"] == "Revisado"
    assert c["rev"]["estrutura"] == "N/A"
    assert c["idp"] == 20   # 1 revisado de 5 aplicáveis (6 − 1 N/A)


def test_completude_expõe_atraso_dos_documentos(client, admin_token, auth_headers):
    """prazo/atrasado já vinham no payload de documentos e não eram usados."""
    from models import db, Documento
    h = auth_headers(admin_token)
    eq = _criar(client, h, nome="ComAtraso")
    doc = Documento.query.filter_by(equipamento_id=eq["id"]).first()
    doc.prazo = date.today() - timedelta(days=5)
    db.session.commit()
    c = _completude(client, h, eq["id"])
    assert c["docs_atrasados"] == 1
    assert c["atraso_max"] == 5


# ── trilha de-para ───────────────────────────────────────────────────────────
def test_update_grava_valor_antigo_e_novo(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    eq = _criar(client, h, nome="Antes", fabricante="ACME")
    client.patch(f"/api/equipamentos/{eq['id']}",
                 json={"nome": "Depois", "fabricante": "Globex"}, headers=h)
    linhas = client.get(f"/api/equipamentos/{eq['id']}/historico", headers=h).get_json()
    por_campo = {l["campo"]: l for l in linhas if l["evento"] == "update"}
    assert por_campo["nome"]["valor_antigo"] == "Antes"
    assert por_campo["nome"]["valor_novo"] == "Depois"
    assert por_campo["fabricante"]["valor_antigo"] == "ACME"
    assert por_campo["fabricante"]["valor_novo"] == "Globex"


def test_historico_acessivel_ao_tecnico(client, admin_token, tecnico_token, auth_headers):
    """/api/audit exige gestor+; quem edita a ficha precisa ver o próprio histórico."""
    eq = _criar(client, auth_headers(admin_token), nome="HistTecnico")
    res = client.get(f"/api/equipamentos/{eq['id']}/historico",
                     headers=auth_headers(tecnico_token))
    assert res.status_code == 200
    assert any(l["evento"] == "create" for l in res.get_json())


# ── integridade do cadastro ──────────────────────────────────────────────────
def test_sku_duplicado_e_recusado(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    _criar(client, h, nome="PlateSpin", sku="1.000404")
    res = client.post("/api/equipamentos", json={"nome": "PLATESPIN", "sku": "01.000404"},
                      headers=h)
    assert res.status_code == 409
    assert res.get_json()["sku_duplicado"]["nome"] == "PlateSpin"


def test_sku_duplicado_pode_ser_forcado(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    _criar(client, h, nome="Original", sku="1.000500")
    res = client.post("/api/equipamentos",
                      json={"nome": "Copia", "sku": "1.000500", "ignorar_sku_duplicado": True},
                      headers=h)
    assert res.status_code == 201


def test_patch_nao_bloqueia_o_proprio_sku(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    eq = _criar(client, h, nome="MesmoSku", sku="1.000600")
    res = client.patch(f"/api/equipamentos/{eq['id']}",
                       json={"sku": "1.000600", "nome": "MesmoSku v2"}, headers=h)
    assert res.status_code == 200


def test_saude_aponta_duplicatas_e_orfaos(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    _criar(client, h, nome="Amplio Rx", sku="1.000918")
    _criar(client, h, nome="Amplio RX", sku="1.000918", ignorar_sku_duplicado=True)
    res = client.get("/api/equipamentos/saude", headers=h)
    assert res.status_code == 200
    saude = res.get_json()
    assert len(saude["sku_duplicado"]) == 1
    assert len(saude["sku_duplicado"][0]["itens"]) == 2
    # O seed do conftest tem 2 documentos ativos sem equipamento_id.
    assert len(saude["docs_orfaos"]) >= 2


def test_saude_aponta_registro_vencido(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    _criar(client, h, nome="RegVencido", classificacao_reg="IVD",
           anvisa="9", anvisa_validade="2020-05-01")
    saude = client.get("/api/equipamentos/saude", headers=h).get_json()
    assert [x["nome"] for x in saude["registro_vencido"]] == ["RegVencido"]


# ── campos que existiam e não eram graváveis ─────────────────────────────────
def test_codigo_interno_agora_e_gravavel(client, admin_token, auth_headers):
    """Estava no to_dict e fora de _EQUIP_STR: a coluna nunca podia ser escrita."""
    h = auth_headers(admin_token)
    eq = _criar(client, h, nome="ComCodigo", codigo_interno="INT-77")
    assert eq["codigo_interno"] == "INT-77"


def test_linha_de_produto_deixa_de_ser_campo_morto(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    linha = client.post("/api/linhas-produto", json={"nome": "Diagnóstico"}, headers=h)
    assert linha.status_code == 201
    lid = linha.get_json()["id"]

    eq = _criar(client, h, nome="ComLinha", linha_id=lid)
    assert eq["linha_id"] == lid and eq["linha"] == "Diagnóstico"

    tax = client.get("/api/equip-taxonomia", headers=h).get_json()
    assert tax["linhas"][0]["uso"] == 1

    # Excluir a linha desvincula em vez de deixar FK apontando para o nada.
    assert client.delete(f"/api/linhas-produto/{lid}", headers=h).status_code == 200
    detalhe = client.get(f"/api/equipamentos/{eq['id']}", headers=h).get_json()
    assert detalhe["linha_id"] is None


def test_responsavel_do_equipamento(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    eq = _criar(client, h, nome="ComDono", responsavel="Ana Souza")
    assert eq["responsavel"] == "Ana Souza"


# ── série temporal ───────────────────────────────────────────────────────────
def test_snapshot_e_idempotente_no_mesmo_dia(client, admin_token, auth_headers):
    from models import EquipamentoSnapshot
    h = auth_headers(admin_token)
    eq = _criar(client, h, nome="ComSnapshot")
    for _ in range(2):
        assert client.post("/api/equipamentos/snapshot", headers=h).status_code == 200
    linhas = EquipamentoSnapshot.query.filter_by(equipamento_id=eq["id"]).all()
    assert len(linhas) == 1


def test_evolucao_do_equipamento(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    eq = _criar(client, h, nome="ComEvolucao", classificacao_reg="RUO")
    client.post("/api/equipamentos/snapshot", headers=h)
    res = client.get(f"/api/equipamentos/{eq['id']}/evolucao", headers=h)
    assert res.status_code == 200
    corpo = res.get_json()
    assert len(corpo["snapshots"]) == 1
    assert corpo["snapshots"][0]["ice"] == corpo["atual"]["ice"]


def test_evolucao_da_frota_agrega_por_dia(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    _criar(client, h, nome="Frota1")
    _criar(client, h, nome="Frota2")
    client.post("/api/equipamentos/snapshot", headers=h)
    serie = client.get("/api/equipamentos/evolucao", headers=h).get_json()
    assert len(serie) == 1 and serie[0]["n"] == 2


def test_import_pareto_guarda_historico(app, client, admin_token, auth_headers):
    """O import sobrescrevia qtd_saidas/classe sem guardar o valor anterior."""
    from models import db, ParetoHistorico
    from pareto_importer import _gravar_historico
    h = auth_headers(admin_token)
    eq = _criar(client, h, nome="ComPareto", sku="1.000700")
    _gravar_historico([(eq["id"], "A", 120)], dia="2026-01-10")
    _gravar_historico([(eq["id"], "B", 40)], dia="2026-02-10")
    db.session.commit()
    linhas = ParetoHistorico.query.filter_by(equipamento_id=eq["id"]).order_by(
        ParetoHistorico.data).all()
    assert [(l.classe, l.qtd_saidas) for l in linhas] == [("A", 120), ("B", 40)]


# ── export ───────────────────────────────────────────────────────────────────
def test_export_respeita_filtros_e_traz_indices(client, admin_token, auth_headers):
    """O CSV ignorava os filtros da tela e não trazia ICE/IDP/Pareto."""
    h = auth_headers(admin_token)
    _criar(client, h, nome="ExpAtivo", sku="1.000801")
    _criar(client, h, nome="ExpObsoleto", sku="1.000802", status="Obsoleto")

    csv_todos = client.get("/api/equipamentos/export", headers=h).get_data(as_text=True)
    assert "ExpAtivo" in csv_todos and "ExpObsoleto" in csv_todos
    cabecalho = csv_todos.splitlines()[0]
    for coluna in ("ice", "idp", "docs_atrasados", "pareto_classe", "registro_situacao"):
        assert coluna in cabecalho

    filtrado = client.get("/api/equipamentos/export?status=Obsoleto",
                          headers=h).get_data(as_text=True)
    assert "ExpObsoleto" in filtrado and "ExpAtivo" not in filtrado

    busca = client.get("/api/equipamentos/export?q=ExpAtivo", headers=h).get_data(as_text=True)
    assert "ExpAtivo" in busca and "ExpObsoleto" not in busca


def test_completude_respeita_filtros(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    _criar(client, h, nome="FiltroAtivo")
    _criar(client, h, nome="FiltroObsoleto", status="Obsoleto")
    res = client.get("/api/equipamentos/completude?status=Obsoleto", headers=h)
    assert res.get_json()["total"] == 1


def test_campos_do_plano_sao_coletados_mas_ficam_fora_do_ice(client, admin_token, auth_headers):
    """Classe de risco e situação entram no cadastro sem derrubar o índice de
    toda a frota de uma vez (decisão comentada em models.Equipamento)."""
    h = auth_headers(admin_token)
    eq = _criar(client, h, nome="ComPlano", classe_risco="II",
                situacao_regulatoria="Vigente", modelo="X-200",
                tecnologia="PCR em tempo real", aplicacao="Diagnóstico molecular",
                classificacao_reg="IVD", anvisa="1", anvisa_registro="2021-01-01",
                anvisa_validade=_dias(500))
    assert eq["classe_risco"] == "II"
    assert eq["situacao_regulatoria"] == "Vigente"
    assert eq["modelo"] == "X-200" and eq["tecnologia"] == "PCR em tempo real"
    assert _completude(client, h, eq["id"])["reg"] == 100

    csv = client.get("/api/equipamentos/export", headers=h).get_data(as_text=True)
    assert "classe_risco" in csv.splitlines()[0] and "X-200" in csv


# ── rastreabilidade das importações ──────────────────────────────────────────
def test_importacao_guarda_relatorio_completo(client, admin_token, auth_headers):
    from models import db
    from servidor import _registrar_importacao
    h = auth_headers(admin_token)
    _registrar_importacao("pareto", "admin@test.com", {
        "a_criar": 0, "a_atualizar": 7, "sem_match_n": 2, "inconsistencias_n": 1,
        "sem_match": [{"sku": "9.999999", "classe": "A"}],
    })
    db.session.commit()
    linhas = client.get("/api/equipamentos/importacoes?detalhe=1", headers=h).get_json()
    assert linhas[0]["origem"] == "pareto"
    assert linhas[0]["atualizados"] == 7 and linhas[0]["sem_match"] == 2
    # o que antes se perdia: quais SKUs não casaram
    assert linhas[0]["relatorio"]["sem_match"][0]["sku"] == "9.999999"


def test_importacoes_exigem_gestor(client, tecnico_token, auth_headers):
    res = client.get("/api/equipamentos/importacoes", headers=auth_headers(tecnico_token))
    assert res.status_code == 403


def test_export_ordena_como_a_tela(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    baixo = _criar(client, h, nome="ZZZBaixoIce")
    alto = _criar(client, h, nome="AAAAltoIce", sku="1.000901", sku_importacao="2.000901",
                  nome_tecnico="Tec", fabricante="ACME", classificacao_reg="RUO")
    csv = client.get("/api/equipamentos/export?ordem=ice-desc", headers=h).get_data(as_text=True)
    linhas = [l for l in csv.splitlines()[1:] if l.strip()]
    assert linhas[0].startswith("1.000901")            # maior ICE primeiro
    assert any(l.split(";")[3] == "ZZZBaixoIce" for l in linhas)
    assert alto["id"] != baixo["id"]


def test_export_exclui_obsoletos_como_a_lista(client, admin_token, auth_headers):
    """A tela esconde bloqueado E obsoleto/descontinuado; o CSV não tinha o
    equivalente e trazia obsoletos que a lista escondia."""
    h = auth_headers(admin_token)
    _criar(client, h, nome="VisivelNaLista")
    _criar(client, h, nome="EscondidoObsoleto", status="Obsoleto")
    csv = client.get("/api/equipamentos/export?incluir_bloqueados=0",
                     headers=h).get_data(as_text=True)
    assert "VisivelNaLista" in csv and "EscondidoObsoleto" not in csv


def test_leitura_nao_altera_equipamento(client, leitura_token, admin_token, auth_headers):
    eq = _criar(client, auth_headers(admin_token), nome="SomenteLeitura")
    h = auth_headers(leitura_token)
    assert client.get("/api/equipamentos/completude", headers=h).status_code == 200
    assert client.patch(f"/api/equipamentos/{eq['id']}",
                        json={"nome": "Hackeado"}, headers=h).status_code == 403
