"""
Ligações projeto ↔ equipamento ↔ documento (vinculos.py e as rotas que o usam).

Cenário: o modelo OEM diz que "Manual do usuário" É o Manual do Usuário PT e
"Checklists" SÃO os 4 checklists; "Protótipo" é validação (sem efeito nesta onda).
"""
from datetime import date, datetime, timedelta

import pytest

import vinculos


def H(tk):
    return {"Authorization": f"Bearer {tk}", "Content-Type": "application/json"}


# ── núcleo, sem rotas ────────────────────────────────────────────────────────

class _Doc:
    def __init__(self, setor="Manuais", status="Elaborar", aplicavel=True,
                 concluido_em=None, id=1):
        self.setor, self.status, self.aplicavel = setor, status, aplicavel
        self.concluido_em, self.id = concluido_em, id


@pytest.mark.parametrize("setor,status,esperado", [
    ("Manuais", "Elaborar", ("pendente", 0)),
    ("Manuais", "Em andamento", ("em_progresso", 50)),
    ("Manuais", "Concluído", ("concluido", 100)),
    ("PRE", "Treinamento Piloto", ("em_progresso", 33)),
    ("PRE", "Enviado para Homologação", ("em_progresso", 67)),
    ("PRE", "Homologado", ("concluido", 100)),
    ("Manuais", "status legado", ("pendente", 0)),
])
def test_estado_do_documento(setor, status, esperado):
    assert vinculos.estado_do_documento(_Doc(setor, status)) == esperado


def test_documento_na_vira_na():
    assert vinculos.estado_do_documento(_Doc(aplicavel=False)) == ("na", None)


INICIO = date(2026, 9, 1)


def test_concluido_depois_do_inicio_conta():
    d = _Doc(status="Concluído", concluido_em=datetime(2026, 10, 1))
    esp = vinculos.espelho([d], INICIO)
    assert esp["status"] == "concluido" and esp["conclusao"] == date(2026, 10, 1)


def test_concluido_antes_do_inicio_e_pendente_no_projeto():
    d = _Doc(status="Concluído", concluido_em=datetime(2025, 3, 1), id=7)
    esp = vinculos.espelho([d], INICIO)
    assert esp["status"] == "pendente" and esp["antes_do_projeto"] == [7]


def test_concluido_sem_data_vale_o_que_o_projeto_dizia():
    d = _Doc(status="Concluído", concluido_em=None)
    assert vinculos.espelho([d], INICIO, "concluido")["status"] == "concluido"
    assert vinculos.espelho([d], INICIO, "pendente")["status"] == "pendente"


def test_checklists_agregam():
    novo = datetime(2026, 10, 1)
    feitos = [_Doc("PRE", "Homologado", concluido_em=novo, id=i) for i in range(4)]
    assert vinculos.espelho(feitos, INICIO)["status"] == "concluido"
    meio = feitos[:3] + [_Doc("PRE", "Elaborar", id=9)]
    esp = vinculos.espelho(meio, INICIO)
    assert esp["status"] == "em_progresso" and esp["percentual"] == 75
    um_na = feitos[:3] + [_Doc("PRE", "Elaborar", aplicavel=False, id=9)]
    assert vinculos.espelho(um_na, INICIO)["status"] == "concluido"
    todos_na = [_Doc(aplicavel=False, id=i) for i in range(4)]
    assert vinculos.espelho(todos_na, INICIO)["status"] == "na"


def test_validar_natureza_alvo():
    assert vinculos.validar_natureza_alvo("documento", "Manual_Usuario")[2] is None
    assert vinculos.validar_natureza_alvo("documento", "")[2]
    assert vinculos.validar_natureza_alvo("documento", "Inventado")[2]
    assert vinculos.validar_natureza_alvo("validacao", "qualquer") == ("validacao", "", None)
    assert vinculos.validar_natureza_alvo("nenhuma", "")[2]
    assert vinculos.validar_natureza_alvo("nenhuma", "", no_entregavel=True)[2] is None


# ── cenário com banco ────────────────────────────────────────────────────────

@pytest.fixture
def oem(app):
    """Modelo OEM com naturezas. Devolve as chaves dos itens."""
    from models import db, ModeloEntregavel, TipoProjeto
    with app.app_context():
        t = TipoProjeto.query.filter_by(nome="OEM").first()
        t.area = "pde"
        itens = [("Produto", "Protótipo", "validacao", ""),
                 ("Documentação", "Manual do usuário", "documento", "Manual_Usuario"),
                 ("Documentação", "Checklists", "documento", "checklists"),
                 ("Marketing", "Folder", "", "")]
        chaves = {}
        for i, (cat, nome, nat, alvo) in enumerate(itens):
            m = ModeloEntregavel(tipo_projeto="OEM", categoria=cat, tipo=nome,
                                 natureza=nat, alvo=alvo, ordem=i)
            db.session.add(m)
            db.session.flush()
            chaves[nome] = m.chave
        db.session.commit()
        return chaves


def _criar_projeto(client, gestor_token, oem, **extra):
    corpo = {"nome": "Analisador X1", "tipo": "OEM", "sku": "SKU-X1",
             "data_inicio_prev": date.today().isoformat(),
             "entregaveis": [{"tipo": n, "categoria": c, "modelo_chave": oem[n]}
                             for c, n in [("Produto", "Protótipo"),
                                          ("Documentação", "Manual do usuário"),
                                          ("Documentação", "Checklists"),
                                          ("Marketing", "Folder")]]}
    corpo.update(extra)
    return client.post("/api/projetos", headers=H(gestor_token), json=corpo)


def _ent(app, pid, nome):
    from models import Entregavel
    with app.app_context():
        e = Entregavel.query.filter_by(projeto_id=pid, tipo=nome).first()
        return {"id": e.id, "status": e.status, "percentual": e.percentual}


def _doc(app, equip_id, tipo):
    from models import Documento
    with app.app_context():
        return Documento.query.filter_by(equipamento_id=equip_id, tipo_doc=tipo).first().id


def test_projeto_novo_cria_o_equipamento_com_os_documentos(app, client, gestor_token, oem):
    from models import db, Equipamento, Documento
    r = _criar_projeto(client, gestor_token, oem, criar_equipamento=True)
    assert r.status_code == 201, r.get_json()
    p = r.get_json()["projeto"]
    assert p["equipamento"]["nome"] == "Analisador X1"
    assert p["equipamento"]["sku"] == "SKU-X1"
    with app.app_context():
        eq = db.session.get(Equipamento, p["equipamento_id"])
        assert Documento.query.filter_by(equipamento_id=eq.id, ativo=True).count() == 12


def test_sku_ja_usado_pede_para_ligar(app, client, gestor_token, oem):
    from models import db, Equipamento
    with app.app_context():
        db.session.add(Equipamento(nome="Já existe", sku="SKU-X1", ativo=True))
        db.session.commit()
    r = _criar_projeto(client, gestor_token, oem, criar_equipamento=True)
    assert r.status_code == 409
    assert r.get_json()["sku_duplicado"]["nome"] == "Já existe"


def test_projeto_fora_do_pde_nao_cria_equipamento(app, client, gestor_token, oem):
    from models import db, TipoProjeto
    with app.app_context():
        TipoProjeto.query.filter_by(nome="OEM").first().area = "inov"
        db.session.commit()
    r = _criar_projeto(client, gestor_token, oem, criar_equipamento=True)
    assert r.status_code == 400


def test_entregavel_espelha_o_documento(app, client, gestor_token, oem):
    from models import db, EntregavelHistorico
    p = _criar_projeto(client, gestor_token, oem, criar_equipamento=True).get_json()["projeto"]
    manual = _doc(app, p["equipamento_id"], "Manual_Usuario")
    r = client.put(f"/api/documento/{manual}/status", headers=H(gestor_token),
                   json={"status": "Em andamento"})
    assert r.status_code == 200
    e = _ent(app, p["id"], "Manual do usuário")
    assert e["status"] == "em_progresso" and e["percentual"] == 50
    r = client.put(f"/api/documento/{manual}/status", headers=H(gestor_token),
                   json={"status": "Concluído"})
    assert _ent(app, p["id"], "Manual do usuário")["status"] == "concluido"
    with app.app_context():
        trilha = [h.status_novo for h in EntregavelHistorico.query.filter_by(entregavel_id=e["id"])]
    assert trilha == ["em_progresso", "concluido"]
    # O que não é documento não se mexe.
    assert _ent(app, p["id"], "Protótipo")["status"] == "pendente"


def test_patch_generico_e_na_tambem_espelham(app, client, gestor_token, oem):
    p = _criar_projeto(client, gestor_token, oem, criar_equipamento=True).get_json()["projeto"]
    manual = _doc(app, p["equipamento_id"], "Manual_Usuario")
    r = client.patch(f"/api/documentos/{manual}", headers=H(gestor_token),
                     json={"status": "Em andamento"})
    assert r.status_code == 200, r.get_json()
    assert _ent(app, p["id"], "Manual do usuário")["status"] == "em_progresso"
    r = client.put(f"/api/documentos/{manual}/aplicabilidade", headers=H(gestor_token),
                   json={"aplicavel": False, "motivo_na_codigo": "nao_se_aplica_produto"})
    assert r.status_code == 200, r.get_json()
    assert _ent(app, p["id"], "Manual do usuário")["status"] == "na"


def test_checklists_no_projeto(app, client, gestor_token, oem):
    p = _criar_projeto(client, gestor_token, oem, criar_equipamento=True).get_json()["projeto"]
    conf = _doc(app, p["equipamento_id"], "Checklist_Conferencia")
    client.put(f"/api/documento/{conf}/status", headers=H(gestor_token),
               json={"status": "Homologado"})
    e = _ent(app, p["id"], "Checklists")
    assert e["status"] == "em_progresso" and e["percentual"] == 25


def test_put_do_entregavel_ligado_nao_muda_status(app, client, gestor_token, oem):
    p = _criar_projeto(client, gestor_token, oem, criar_equipamento=True).get_json()["projeto"]
    e = _ent(app, p["id"], "Manual do usuário")
    r = client.put(f"/api/entregaveis/{e['id']}", headers=H(gestor_token),
                   json={"status": "concluido"})
    assert r.status_code == 409
    assert "documento" in r.get_json()["erro"]
    # Mandar o mesmo status (o popover reenvia tudo) e mexer no peso passa.
    r = client.put(f"/api/entregaveis/{e['id']}", headers=H(gestor_token),
                   json={"status": "pendente", "peso": 3})
    assert r.status_code == 200, r.get_json()


def test_desvincular_no_entregavel(app, client, gestor_token, oem):
    p = _criar_projeto(client, gestor_token, oem, criar_equipamento=True).get_json()["projeto"]
    e = _ent(app, p["id"], "Manual do usuário")
    r = client.put(f"/api/entregaveis/{e['id']}", headers=H(gestor_token),
                   json={"natureza": "nenhuma"})
    assert r.status_code == 200, r.get_json()
    assert client.put(f"/api/entregaveis/{e['id']}", headers=H(gestor_token),
                      json={"status": "na"}).status_code == 200


def test_detalhe_do_projeto_traz_o_artefato(app, client, gestor_token, oem):
    p = _criar_projeto(client, gestor_token, oem, criar_equipamento=True).get_json()["projeto"]
    d = client.get(f"/api/projetos/{p['id']}", headers=H(gestor_token)).get_json()
    ents = {e["tipo"]: e for c in d["categorias"] for e in c["entregaveis"]}
    art = ents["Manual do usuário"]["artefato"]
    assert art["alvo_rotulo"] == "Manual do Usuário PT"
    assert [x["tipo_doc"] for x in art["documentos"]] == ["Manual_Usuario"]
    assert len(ents["Checklists"]["artefato"]["documentos"]) == 4
    assert ents["Folder"]["artefato"] is None and ents["Protótipo"]["artefato"] is None


# ── projeto antigo e ciclo do projeto ────────────────────────────────────────

@pytest.fixture
def equip_pronto(app):
    """Equipamento que já existe, com o Manual concluído no ano passado."""
    from models import db, Equipamento, Documento
    from servidor import _ensure_docs_for_equip
    with app.app_context():
        eq = Equipamento(nome="Analisador X1 v1", sku="SKU-V1", ativo=True)
        db.session.add(eq)
        db.session.flush()
        _ensure_docs_for_equip(eq)
        db.session.flush()
        m = Documento.query.filter_by(equipamento_id=eq.id, tipo_doc="Manual_Usuario").first()
        m.status, m.concluido_em = "Concluído", datetime.now() - timedelta(days=400)
        db.session.commit()
        return eq.id


def test_prévia_e_ciclo_ao_ligar_equipamento_existente(app, client, gestor_token, oem, equip_pronto):
    p = _criar_projeto(client, gestor_token, oem).get_json()["projeto"]
    assert p["equipamento_id"] is None
    r = client.get(f"/api/projetos/{p['id']}/vinculo-previa?equipamento_id={equip_pronto}",
                   headers=H(gestor_token))
    assert r.status_code == 200
    previa = {x["tipo"]: x for x in r.get_json()["entregaveis"]}
    assert previa["Manual do usuário"]["depois"]["status"] == "pendente"
    assert previa["Manual do usuário"]["antes_do_projeto"] is True

    r = client.put(f"/api/projetos/{p['id']}", headers=H(gestor_token),
                   json={"equipamento_id": equip_pronto})
    assert r.status_code == 200, r.get_json()
    assert _ent(app, p["id"], "Manual do usuário")["status"] == "pendente"
    d = client.get(f"/api/projetos/{p['id']}", headers=H(gestor_token)).get_json()
    art = [e for c in d["categorias"] for e in c["entregaveis"]
           if e["tipo"] == "Manual do usuário"][0]["artefato"]
    assert art["antes_do_projeto"] is True


def test_fluxo_reabre_o_documento_e_conclui_no_projeto(app, client, gestor_token, oem, equip_pronto):
    from fluxos.models import semear_modelo_padrao
    from models import db, User, Documento
    p = _criar_projeto(client, gestor_token, oem, equipamento_id=equip_pronto).get_json()["projeto"]
    manual = _doc(app, equip_pronto, "Manual_Usuario")
    with app.app_context():
        semear_modelo_padrao()
        from fluxos.models import FluxoModelo
        mid = FluxoModelo.query.first().id
        tec = User.query.filter_by(email="tecnico@test.com").first().id
    r = client.post("/fluxos/api/fluxos", headers=H(gestor_token), json={
        "ref_tipo": "documento", "ref_id": manual, "modelo_id": mid,
        "participantes": {"autor": tec, "diagramador": tec}})
    assert r.status_code == 201, r.get_json()
    with app.app_context():
        assert db.session.get(Documento, manual).status == "Em andamento"
    assert _ent(app, p["id"], "Manual do usuário")["status"] == "em_progresso"

    f = r.get_json()["fluxo"]
    for acao in ("enviar", "enviar", "aprovar"):
        f = client.post(f"/fluxos/api/fluxos/{f['fluxo_id']}/acao", headers=H(gestor_token),
                        json={"acao": acao, "versao": f["versao"]}).get_json()["fluxo"]
    assert f["status"] == "aprovado"
    assert _ent(app, p["id"], "Manual do usuário")["status"] == "concluido"


def test_fluxo_no_entregavel_ligado_e_recusado(app, client, gestor_token, oem):
    from fluxos.models import semear_modelo_padrao, FluxoModelo
    p = _criar_projeto(client, gestor_token, oem, criar_equipamento=True).get_json()["projeto"]
    e = _ent(app, p["id"], "Manual do usuário")
    with app.app_context():
        semear_modelo_padrao()
        mid = FluxoModelo.query.first().id
    r = client.post("/fluxos/api/fluxos", headers=H(gestor_token), json={
        "ref_tipo": "entregavel", "ref_id": e["id"], "modelo_id": mid, "participantes": {}})
    assert r.status_code == 409
    assert "documento" in r.get_json()["erro"]


def test_chip_do_entregavel_mostra_o_fluxo_do_documento(app, client, gestor_token, oem):
    from fluxos.models import semear_modelo_padrao, FluxoModelo
    from models import User
    p = _criar_projeto(client, gestor_token, oem, criar_equipamento=True).get_json()["projeto"]
    e = _ent(app, p["id"], "Manual do usuário")
    manual = _doc(app, p["equipamento_id"], "Manual_Usuario")
    with app.app_context():
        semear_modelo_padrao()
        mid = FluxoModelo.query.first().id
        tec = User.query.filter_by(email="tecnico@test.com").first().id
    client.post("/fluxos/api/fluxos", headers=H(gestor_token), json={
        "ref_tipo": "documento", "ref_id": manual, "modelo_id": mid,
        "participantes": {"autor": tec, "diagramador": tec}})
    r = client.get(f"/fluxos/api/por-refs?ref_tipo=entregavel&ids={e['id']}",
                   headers=H(gestor_token)).get_json()
    assert r["resumos"][str(e["id"])]["ref_tipo"] == "documento"


# ── modelo e caminhos de volta ───────────────────────────────────────────────

def test_mudar_o_alvo_no_modelo_ressincroniza(app, client, gestor_token, oem):
    from models import ModeloEntregavel
    p = _criar_projeto(client, gestor_token, oem, criar_equipamento=True).get_json()["projeto"]
    servico = _doc(app, p["equipamento_id"], "Manual_Servico")
    client.put(f"/api/documento/{servico}/status", headers=H(gestor_token),
               json={"status": "Em andamento"})
    assert _ent(app, p["id"], "Manual do usuário")["status"] == "pendente"
    with app.app_context():
        mid = ModeloEntregavel.query.filter_by(chave=oem["Manual do usuário"]).first().id
    r = client.put(f"/api/modelos/{mid}", headers=H(gestor_token),
                   json={"natureza": "documento", "alvo": "Manual_Servico"})
    assert r.status_code == 200, r.get_json()
    assert _ent(app, p["id"], "Manual do usuário")["status"] == "em_progresso"
    r = client.put(f"/api/modelos/{mid}", headers=H(gestor_token),
                   json={"natureza": "documento", "alvo": "Inventado"})
    assert r.status_code == 400


def test_equipamento_e_documento_mostram_o_projeto(app, client, gestor_token, oem):
    p = _criar_projeto(client, gestor_token, oem, criar_equipamento=True).get_json()["projeto"]
    eq = client.get(f"/api/equipamentos/{p['equipamento_id']}", headers=H(gestor_token)).get_json()
    assert [x["nome"] for x in eq["projetos"]] == ["Analisador X1"]
    lista = client.get("/api/equipamentos", headers=H(gestor_token)).get_json()
    assert [x for x in lista if x["id"] == p["equipamento_id"]][0]["projetos"][0]["id"] == p["id"]
    manual = _doc(app, p["equipamento_id"], "Manual_Usuario")
    r = client.get(f"/api/projetos/por-documento/{manual}", headers=H(gestor_token)).get_json()
    assert r["vinculos"][0]["entregavel_tipo"] == "Manual do usuário"
    assert r["vinculos"][0]["link"].startswith(f"/projetos?projeto={p['id']}&entregavel=")


def test_opcoes_de_equipamento_sugerem_pelo_sku(app, client, gestor_token, equip_pronto):
    r = client.get("/api/projetos/equipamentos-opcoes?sku=sku-v1", headers=H(gestor_token)).get_json()
    assert r["opcoes"][0]["id"] == equip_pronto and r["opcoes"][0]["mesmo_sku"] is True
