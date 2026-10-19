"""Testes: aplicar mudanças do modelo aos projetos existentes (modelo_sync +
rotas /api/modelos/propagacao)."""
import pytest


@pytest.fixture
def h(admin_token, auth_headers):
    return auth_headers(admin_token)


def _modelo(client, h, itens, tipo="OEM"):
    ids = {}
    for cat, nome, extra in itens:
        r = client.post("/api/modelos", json={"tipo_projeto": tipo, "categoria": cat,
                                              "tipo": nome, **extra}, headers=h)
        assert r.status_code == 201, r.get_json()
        ids[nome] = r.get_json()["modelo"]["id"]
    return ids


def _projeto(client, h, nome="P", tipo="OEM"):
    r = client.post("/api/projetos", json={"nome": nome, "tipo": tipo}, headers=h)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["projeto"]["id"]


def _ents(client, h, pid):
    det = client.get(f"/api/projetos/{pid}", headers=h).get_json()
    return {e["tipo"]: e for c in det["categorias"] for e in c["entregaveis"]}


def _previa(client, h, tipo="OEM"):
    r = client.get(f"/api/modelos/propagacao/previa?tipo={tipo}", headers=h)
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def _proj_previa(previa, pid):
    return next(p for p in previa["projetos"] if p["id"] == pid)


def _aplicar(client, h, previa, pids, decisoes=None, motivo="Revisão do modelo", tipo="OEM"):
    sel = {str(pid): _proj_previa(previa, pid)["versao"] for pid in pids}
    return client.post("/api/modelos/propagacao", json={
        "tipo": tipo, "projetos": sel, "decisoes": decisoes or {}, "motivo": motivo}, headers=h)


BASE = [("Produto", "Protótipo", {"peso": 2}),
        ("Documentação", "Manual", {"responsavel_padrao": "Doc"}),
        ("Produto", "Lote piloto", {})]


# ── vínculo na criação ───────────────────────────────────────────────────────

def test_projeto_novo_nasce_ligado_ao_modelo(client, h):
    _modelo(client, h, BASE)
    pid = _projeto(client, h)
    client.post(f"/api/projetos/{pid}/entregaveis", json={"tipo": "Avulso", "categoria": "Produto"},
                headers=h)
    ents = _ents(client, h, pid)
    assert all(ents[n]["do_modelo"] for n in ("Protótipo", "Manual", "Lote piloto"))
    assert ents["Avulso"]["do_modelo"] is False
    assert _proj_previa(_previa(client, h), pid)["mudancas"] == []


def test_lista_do_modal_mantem_vinculo_so_com_chave_do_modelo(client, h):
    _modelo(client, h, BASE)
    chaves = {m["tipo"]: m["chave"] for m in
              client.get("/api/modelos?tipo=OEM", headers=h).get_json()["modelos"]["OEM"]}
    r = client.post("/api/projetos", json={"nome": "Modal", "tipo": "OEM", "entregaveis": [
        {"tipo": "Protótipo", "categoria": "Produto", "modelo_chave": chaves["Protótipo"]},
        {"tipo": "Manual", "categoria": "Documentação", "modelo_chave": "inventada"},
        {"tipo": "Extra", "categoria": "Produto"}]}, headers=h)
    ents = _ents(client, h, r.get_json()["projeto"]["id"])
    assert ents["Protótipo"]["do_modelo"] is True
    assert ents["Manual"]["do_modelo"] is False and ents["Extra"]["do_modelo"] is False


# ── prévia: comparação de três lados ─────────────────────────────────────────

def test_previa_e_aplicacao_respeitam_ajuste_do_projeto(client, h):
    ids = _modelo(client, h, BASE)
    pid = _projeto(client, h)
    ents = _ents(client, h, pid)
    # o projeto ajusta o peso do Protótipo; o Manual fica como veio
    client.put(f"/api/entregaveis/{ents['Protótipo']['id']}", json={"peso": 5}, headers=h)
    # o modelo muda peso dos dois, renomeia um e ganha um item novo
    client.put(f"/api/modelos/{ids['Protótipo']}", json={"peso": 3}, headers=h)
    client.put(f"/api/modelos/{ids['Manual']}", json={"tipo": "Manual do usuário",
                                                       "responsavel_padrao": "Qualidade"}, headers=h)
    client.put(f"/api/modelos/{ids['Lote piloto']}", json={"peso": 4}, headers=h)
    _modelo(client, h, [("Produto", "Teste de campo", {})])

    pv = _proj_previa(_previa(client, h), pid)
    acoes = sorted((c["acao"], c["entregavel"], c.get("campo", "")) for c in pv["mudancas"])
    assert acoes == [("criar", "Teste de campo", ""),
                     ("mantido", "Protótipo", "peso"),
                     ("peso", "Lote piloto", "peso"),
                     ("renomeado", "Manual", "tipo"),
                     ("responsavel", "Manual", "responsavel")]
    assert pv["alteracoes"] == 4

    r = _aplicar(client, h, _previa(client, h), [pid])
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["mudanca"]["n_alteracoes"] == 4

    ents = _ents(client, h, pid)
    assert ents["Protótipo"]["peso"] == 5            # ajuste do projeto ficou
    assert ents["Lote piloto"]["peso"] == 4
    assert ents["Manual do usuário"]["responsaveis"] == "Qualidade"
    assert ents["Teste de campo"]["do_modelo"] and ents["Teste de campo"]["status"] == "pendente"
    # em dia: a próxima prévia não repete nada, nem o "mantido"
    assert _proj_previa(_previa(client, h), pid)["mudancas"] == []


def test_aplicar_nao_conta_como_atualizacao_do_entregavel(app, client, h):
    ids = _modelo(client, h, BASE)
    pid = _projeto(client, h)
    from models import db, Entregavel
    from datetime import datetime
    antigo = datetime(2026, 1, 1, 8, 0)
    with app.app_context():
        e = Entregavel.query.filter_by(projeto_id=pid, tipo="Protótipo").first()
        db.session.execute(Entregavel.__table__.update().where(Entregavel.id == e.id)
                           .values(atualizado_em=antigo))
        db.session.commit()
        eid = e.id
    client.put(f"/api/modelos/{ids['Protótipo']}", json={"tipo": "Protótipo v2"}, headers=h)
    assert _aplicar(client, h, _previa(client, h), [pid]).status_code == 201
    with app.app_context():
        e = db.session.get(Entregavel, eid)
        assert e.tipo == "Protótipo v2" and e.atualizado_em == antigo


def test_avulso_de_mesmo_nome_e_vinculado_em_vez_de_duplicado(client, h):
    _modelo(client, h, BASE)
    pid = _projeto(client, h)
    client.post(f"/api/projetos/{pid}/entregaveis", json={"tipo": "teste de campo",
                                                          "categoria": "Produto"}, headers=h)
    _modelo(client, h, [("Produto", "Teste de campo", {})])
    pv = _proj_previa(_previa(client, h), pid)
    assert [c["acao"] for c in pv["mudancas"]] == ["vincular"]
    assert _aplicar(client, h, _previa(client, h), [pid]).status_code == 201
    ents = _ents(client, h, pid)
    assert len(ents) == 4 and ents["teste de campo"]["do_modelo"] is True


# ── remoção: decisão caso a caso ─────────────────────────────────────────────

def test_item_removido_sem_andamento_e_apagado(client, h):
    ids = _modelo(client, h, BASE)
    pid = _projeto(client, h)
    client.delete(f"/api/modelos/{ids['Lote piloto']}", headers=h)
    pv = _proj_previa(_previa(client, h), pid)
    assert pv["mudancas"][0]["acao"] == "remover" and pv["mudancas"][0]["andamento"] is False
    assert pv["decisoes_pendentes"] == 0
    assert _aplicar(client, h, _previa(client, h), [pid]).status_code == 201
    assert "Lote piloto" not in _ents(client, h, pid)


def test_item_removido_com_andamento_exige_decisao(client, h):
    ids = _modelo(client, h, BASE)
    p1, p2, p3 = (_projeto(client, h, n) for n in ("A", "B", "C"))
    for pid in (p1, p2, p3):
        eid = _ents(client, h, pid)["Lote piloto"]["id"]
        client.put(f"/api/entregaveis/{eid}", json={"status": "em_progresso", "percentual": 30},
                   headers=h)
    client.delete(f"/api/modelos/{ids['Lote piloto']}", headers=h)
    pv = _previa(client, h)
    assert all(_proj_previa(pv, p)["decisoes_pendentes"] == 1 for p in (p1, p2, p3))

    r = _aplicar(client, h, pv, [p1, p2, p3])
    assert r.status_code == 400 and "decida o destino" in r.get_json()["erro"]

    e1, e2, e3 = (_ents(client, h, p)["Lote piloto"]["id"] for p in (p1, p2, p3))
    r = _aplicar(client, h, pv, [p1, p2, p3],
                 decisoes={str(e1): "apagar", str(e2): "manter", str(e3): "na"})
    assert r.status_code == 201, r.get_json()

    assert "Lote piloto" not in _ents(client, h, p1)
    mantido = _ents(client, h, p2)["Lote piloto"]
    assert mantido["status"] == "em_progresso" and mantido["do_modelo"] is False
    na = _ents(client, h, p3)["Lote piloto"]
    assert na["status"] == "na" and na["do_modelo"] is False
    hist = client.get(f"/api/entregaveis/{e3}/historico", headers=h).get_json()
    assert any(x["status_novo"] == "na" for x in hist["historico"])
    # desvinculados não voltam a aparecer
    pv = _previa(client, h)
    assert all(_proj_previa(pv, p)["mudancas"] == [] for p in (p1, p2, p3))


def test_decisao_invalida(client, h):
    ids = _modelo(client, h, BASE)
    pid = _projeto(client, h)
    client.delete(f"/api/modelos/{ids['Lote piloto']}", headers=h)
    eid = _ents(client, h, pid)["Lote piloto"]["id"]
    r = _aplicar(client, h, _previa(client, h), [pid], decisoes={str(eid): "sumir"})
    assert r.status_code == 400


# ── alcance, controle e permissões ───────────────────────────────────────────

def test_so_projetos_escolhidos_mudam_e_inelegiveis_ficam_fora(client, h):
    ids = _modelo(client, h, BASE)
    a, b = _projeto(client, h, "A"), _projeto(client, h, "B")
    concl, arq = _projeto(client, h, "Concluído"), _projeto(client, h, "Arquivado")
    client.put(f"/api/projetos/{concl}", json={"status": "concluido"}, headers=h)
    client.delete(f"/api/projetos/{arq}", headers=h)
    client.put(f"/api/modelos/{ids['Manual']}", json={"tipo": "Manual v2"}, headers=h)

    pv = _previa(client, h)
    assert sorted(p["id"] for p in pv["projetos"]) == sorted([a, b])
    assert _aplicar(client, h, pv, [a]).status_code == 201
    assert "Manual v2" in _ents(client, h, a)
    assert "Manual" in _ents(client, h, b)
    assert "Manual" in _ents(client, h, concl)


def test_previa_desatualizada_e_recusada(client, h):
    ids = _modelo(client, h, BASE)
    pid = _projeto(client, h)
    client.put(f"/api/modelos/{ids['Manual']}", json={"tipo": "Manual v2"}, headers=h)
    pv = _previa(client, h)
    client.put(f"/api/modelos/{ids['Manual']}", json={"tipo": "Manual v3"}, headers=h)
    r = _aplicar(client, h, pv, [pid])
    assert r.status_code == 409
    assert "Manual" in _ents(client, h, pid)        # nada foi escrito


@pytest.mark.parametrize("motivo", ["", "   ", "ok"])
def test_motivo_obrigatorio(client, h, motivo):
    ids = _modelo(client, h, BASE)
    pid = _projeto(client, h)
    client.put(f"/api/modelos/{ids['Manual']}", json={"tipo": "Manual v2"}, headers=h)
    r = _aplicar(client, h, _previa(client, h), [pid], motivo=motivo)
    assert r.status_code == 400 and "motivo" in r.get_json()["erro"]


def test_sem_projeto_ou_em_dia(client, h):
    _modelo(client, h, BASE)
    pid = _projeto(client, h)
    r = client.post("/api/modelos/propagacao", json={"tipo": "OEM", "projetos": {},
                                                     "motivo": "Revisão"}, headers=h)
    assert r.status_code == 400
    r = _aplicar(client, h, _previa(client, h), [pid])
    assert r.status_code == 400 and "em dia" in r.get_json()["erro"]


def test_gestor_nao_aplica_mas_ve_historico(client, h, gestor_token, auth_headers):
    ids = _modelo(client, h, BASE)
    pid = _projeto(client, h)
    client.put(f"/api/modelos/{ids['Manual']}", json={"tipo": "Manual v2"}, headers=h)
    g = auth_headers(gestor_token)
    assert client.get("/api/modelos/propagacao/previa?tipo=OEM", headers=g).status_code == 403
    pv = _previa(client, h)
    sel = {str(pid): _proj_previa(pv, pid)["versao"]}
    r = client.post("/api/modelos/propagacao", json={"tipo": "OEM", "projetos": sel,
                                                     "motivo": "Revisão"}, headers=g)
    assert r.status_code == 403
    assert _aplicar(client, h, pv, [pid]).status_code == 201
    hist = client.get("/api/modelos/propagacao/historico?tipo=OEM", headers=g)
    assert hist.status_code == 200 and len(hist.get_json()["mudancas"]) == 1


def test_tecnico_nao_ve_historico(client, tecnico_token, auth_headers):
    r = client.get("/api/modelos/propagacao/historico?tipo=OEM",
                   headers=auth_headers(tecnico_token))
    assert r.status_code == 403


# ── histórico ────────────────────────────────────────────────────────────────

def test_historico_registra_antes_depois_por_projeto(client, h):
    ids = _modelo(client, h, BASE)
    a, b = _projeto(client, h, "A"), _projeto(client, h, "B")
    client.put(f"/api/entregaveis/{_ents(client, h, b)['Protótipo']['id']}", json={"peso": 9},
               headers=h)
    client.put(f"/api/modelos/{ids['Protótipo']}", json={"tipo": "Protótipo v2", "peso": 3},
               headers=h)
    r = _aplicar(client, h, _previa(client, h), [a, b], motivo="Norma nova de protótipo")
    mid = r.get_json()["mudanca"]["id"]

    lista = client.get("/api/modelos/propagacao/historico?tipo=OEM", headers=h).get_json()
    m = lista["mudancas"][0]
    assert m["motivo"] == "Norma nova de protótipo" and m["feito_por"] == "admin@test.com"
    assert m["n_projetos"] == 2 and m["n_alteracoes"] == 3   # 2 renomes + 1 peso (B mantido)

    det = client.get(f"/api/modelos/propagacao/{mid}", headers=h).get_json()
    por_proj = {g["projeto"]: sorted((i["acao"], i["antes"], i["depois"]) for i in g["itens"])
                for g in det["projetos"]}
    assert por_proj["A"] == [("peso", "2", "3"), ("renomeado", "Protótipo", "Protótipo v2")]
    assert por_proj["B"] == [("mantido", "9", "3"), ("renomeado", "Protótipo", "Protótipo v2")]

    proj = client.get(f"/api/projetos/{b}/mudancas-modelo", headers=h).get_json()
    assert proj["mudancas"][0]["mudanca"]["id"] == mid
    assert len(proj["mudancas"][0]["itens"]) == 2


def test_projeto_que_trocou_de_modelo(client, h):
    _modelo(client, h, BASE)
    _modelo(client, h, [("Marketing", "Catálogo", {})], tipo="Revenda")
    pid = _projeto(client, h)
    eid = _ents(client, h, pid)["Protótipo"]["id"]
    client.put(f"/api/entregaveis/{eid}", json={"status": "concluido"}, headers=h)
    client.put(f"/api/projetos/{pid}", json={"tipo": "Revenda"}, headers=h)

    pv = _proj_previa(_previa(client, h, "Revenda"), pid)
    assert sorted(c["acao"] for c in pv["mudancas"]) == ["criar", "remover", "remover", "remover"]
    assert pv["decisoes_pendentes"] == 1           # só o Protótipo tem andamento
    r = _aplicar(client, h, _previa(client, h, "Revenda"), [pid], tipo="Revenda",
                 decisoes={str(eid): "manter"})
    assert r.status_code == 201, r.get_json()
    assert sorted(_ents(client, h, pid)) == ["Catálogo", "Protótipo"]


# ── vínculo dos dados antigos ────────────────────────────────────────────────

def test_vincular_legado_liga_pelo_nome_e_e_idempotente(app, client, h):
    _modelo(client, h, BASE)
    from models import db, Projeto, Entregavel, ModeloEntregavel
    import modelo_sync
    with app.app_context():
        ModeloEntregavel.query.filter_by(tipo="Lote piloto").update({"chave": None})
        p = Projeto(nome="Antigo", tipo="OEM", ano=2025)
        db.session.add(p)
        db.session.flush()
        for cat, nome, peso in [("Produto", "protótipo", 7), ("Documentação", "Manual", 1),
                                ("Produto", "Lote piloto", 1), ("Produto", "Só do projeto", 1)]:
            db.session.add(Entregavel(projeto_id=p.id, tipo=nome, categoria=cat, peso=peso))
        db.session.flush()
        # linha anterior ao vínculo: o ORM gravaria o default "", não NULL
        db.session.execute(Entregavel.__table__.update()
                           .where(Entregavel.projeto_id == p.id).values(modelo_origem=None))
        db.session.commit()
        db.session.expire_all()
        pid = p.id

        # (itens de modelo com chave nova, entregáveis ligados, projetos avaliados)
        assert modelo_sync.vincular_legado() == (1, 3, 1)
        db.session.commit()
        assert modelo_sync.vincular_legado() == (0, 0, 0)

    ents = _ents(client, h, pid)
    assert [n for n, e in ents.items() if not e["do_modelo"]] == ["Só do projeto"]
    # o peso 7 que o projeto já tinha conta como ajuste do projeto: nada a fazer
    assert _proj_previa(_previa(client, h), pid)["mudancas"] == []


def _projeto_legado(app, tipo, itens):
    """Projeto como estava antes do vínculo: entregáveis com origem NULL e sem
    a lista de itens conhecidos."""
    from models import db, Projeto, Entregavel
    with app.app_context():
        p = Projeto(nome=f"Legado {len(itens)}", tipo=tipo, ano=2025)
        db.session.add(p)
        db.session.flush()
        for cat, nome in itens:
            db.session.add(Entregavel(projeto_id=p.id, tipo=nome, categoria=cat))
        db.session.flush()
        db.session.execute(Entregavel.__table__.update()
                           .where(Entregavel.projeto_id == p.id).values(modelo_origem=None))
        db.session.commit()
        return p.id


def _rodar_backfill(app):
    import modelo_sync
    from models import db
    with app.app_context():
        r = modelo_sync.vincular_legado()
        db.session.commit()
        return r


def test_legado_casa_pelo_nome_mesmo_com_categoria_diferente(app, client, h):
    _modelo(client, h, [("Marketing", "Requisição de Projetos", {}), ("Produto", "Protótipo", {})])
    # o projeto nasceu com o item em outra categoria e o nome escrito diferente
    pid = _projeto_legado(app, "OEM", [("Documentação", "requisicao de  projetos"),
                                      ("Produto", "Protótipo")])
    _rodar_backfill(app)
    ents = _ents(client, h, pid)
    e = ents["requisicao de  projetos"]
    assert e["do_modelo"] is True and e["categoria"] == "Documentação"   # a do projeto fica
    assert _proj_previa(_previa(client, h), pid)["mudancas"] == []


def test_legado_nao_propoe_itens_que_o_projeto_nunca_teve(app, client, h):
    _modelo(client, h, BASE)
    pid = _projeto_legado(app, "OEM", [("Produto", "Protótipo")])   # só 1 dos 3 itens
    _rodar_backfill(app)
    assert _proj_previa(_previa(client, h), pid)["mudancas"] == []
    # o que entrar no modelo depois do backfill é novo para o projeto
    _modelo(client, h, [("Produto", "Teste de campo", {})])
    pv = _proj_previa(_previa(client, h), pid)
    assert [(c["acao"], c["entregavel"]) for c in pv["mudancas"]] == [("criar", "Teste de campo")]


def test_item_tirado_no_modal_nao_volta_na_previa(client, h):
    _modelo(client, h, BASE)
    modelo = client.get("/api/modelos?tipo=OEM", headers=h).get_json()["modelos"]["OEM"]
    escolhidos = [m for m in modelo if m["tipo"] != "Manual"]   # o usuário tirou o Manual
    pid = client.post("/api/projetos", json={"nome": "Sem manual", "tipo": "OEM", "entregaveis": [
        {"tipo": m["tipo"], "categoria": m["categoria"], "modelo_chave": m["chave"]}
        for m in escolhidos]}, headers=h).get_json()["projeto"]["id"]
    assert _proj_previa(_previa(client, h), pid)["mudancas"] == []
    _modelo(client, h, [("Produto", "Teste de campo", {})])
    pv = _proj_previa(_previa(client, h), pid)
    assert [c["entregavel"] for c in pv["mudancas"]] == ["Teste de campo"]   # o Manual não


def test_aplicar_torna_o_item_conhecido_e_desmarcado_continua_vendo(client, h):
    _modelo(client, h, BASE)
    a, b = _projeto(client, h, "A"), _projeto(client, h, "B")
    _modelo(client, h, [("Produto", "Teste de campo", {})])
    assert _aplicar(client, h, _previa(client, h), [a]).status_code == 201
    # A recebeu e passou a conhecer: apagar o item à mão não o traz de volta
    eid = _ents(client, h, a)["Teste de campo"]["id"]
    client.delete(f"/api/entregaveis/{eid}", headers=h)
    pv = _previa(client, h)
    assert _proj_previa(pv, a)["mudancas"] == []
    # B ficou de fora da aplicação: o item continua novo para ele
    assert [c["acao"] for c in _proj_previa(pv, b)["mudancas"]] == ["criar"]
