"""
Testes da API dos fluxos de revisão (fluxos/routes.py).

Cenário de referência: o Manual do Usuário PT de um equipamento. Giullia escreve
e revisa, Marcos diagrama, o gestor inicia. Um técnico de fora (tecnico@test.com)
não participa de nada.
"""
import io

import pytest

SENHA = "demo123"


# ── cenário ──────────────────────────────────────────────────────────────────

@pytest.fixture
def cena(app, client):
    from models import db, User, Documento, Projeto, Entregavel
    from fluxos.models import semear_modelo_padrao, FluxoModelo

    with app.app_context():
        for nome, email in (("Giullia Teste", "giullia@test.com"),
                            ("Marcos Teste", "marcos@test.com")):
            u = User(nome=nome, email=email, role="tecnico", ativo=True)
            u.set_senha(SENHA)
            db.session.add(u)
        manual = Documento(setor="Manuais", equipamento="Analisador X1",
                           documento="Manual X1 PT", tipo_doc="Manual_Usuario",
                           status="Elaborar")
        it = Documento(setor="PRE", equipamento="Analisador X1", documento="IT X1",
                       tipo_doc="IT", status="Elaborar")
        p = Projeto(nome="Analisador X1", tipo="OEM", status="execucao")
        db.session.add_all([manual, it, p])
        db.session.flush()
        ent = Entregavel(projeto_id=p.id, tipo="Manual do usuário", categoria="Documentação")
        db.session.add(ent)
        db.session.commit()
        semear_modelo_padrao()
        ids = {
            "giullia": User.query.filter_by(email="giullia@test.com").first().id,
            "marcos": User.query.filter_by(email="marcos@test.com").first().id,
            "gestor": User.query.filter_by(email="gestor@test.com").first().id,
            "tecnico": User.query.filter_by(email="tecnico@test.com").first().id,
            "manual": manual.id, "it": it.id, "projeto": p.id, "ent": ent.id,
            "modelo": FluxoModelo.query.first().id,
        }

    def token(email):
        r = client.post("/api/auth/login", json={"email": email, "senha": SENHA})
        assert r.status_code == 200, r.get_json()
        return r.get_json()["access_token"]

    ids["tk"] = {k: token(f"{k}@test.com") for k in ("giullia", "marcos", "gestor", "tecnico")}
    return ids


@pytest.fixture(autouse=True)
def _blobs(monkeypatch, tmp_path):
    import arquivos_store
    monkeypatch.setattr(arquivos_store, "RAIZ", str(tmp_path / "blobs"))


def H(tk):
    return {"Authorization": f"Bearer {tk}"}


def iniciar(client, c, ref_tipo="documento", ref_id=None, tk=None):
    return client.post("/fluxos/api/fluxos", headers=H(tk or c["tk"]["gestor"]), json={
        "ref_tipo": ref_tipo, "ref_id": ref_id or c["manual"], "modelo_id": c["modelo"],
        "participantes": {"autor": c["giullia"], "diagramador": c["marcos"]}})


def agir(client, fluxo, tk, acao, comentario="", arquivos=()):
    data = {"acao": acao, "comentario": comentario, "versao": str(fluxo["versao"])}
    if arquivos:
        data["arquivos"] = [(io.BytesIO(conteudo), nome) for nome, conteudo in arquivos]
    return client.post(f"/fluxos/api/fluxos/{fluxo['fluxo_id']}/acao", headers=H(tk),
                       data=data, content_type="multipart/form-data")


def notificacoes(client, tk):
    return client.get("/api/notificacoes", headers=H(tk)).get_json()["notificacoes"]


# ── iniciar ──────────────────────────────────────────────────────────────────

def test_iniciar_no_manual_poe_em_andamento_e_avisa_a_autora(app, client, cena):
    from models import db, Documento
    r = iniciar(client, cena)
    assert r.status_code == 201, r.get_json()
    f = r.get_json()["fluxo"]
    assert f["etapa_nome"] == "Escrita"
    assert f["responsavel"]["id"] == cena["giullia"]
    assert f["rodada"] == 1
    with app.app_context():
        assert db.session.get(Documento, cena["manual"]).status == "Em andamento"

    avisos = notificacoes(client, cena["tk"]["giullia"])
    assert [a["tipo"] for a in avisos] == ["acao"]
    assert avisos[0]["titulo"] == "É sua vez: Escrita"
    assert avisos[0]["link"] == f"/?doc={cena['manual']}"
    assert [a["tipo"] for a in notificacoes(client, cena["tk"]["marcos"])] == ["info"]
    assert notificacoes(client, cena["tk"]["gestor"]) == []      # quem agiu não é avisado


def test_documento_pre_nao_tem_o_status_tocado(app, client, cena):
    from models import db, Documento
    assert iniciar(client, cena, ref_id=cena["it"]).status_code == 201
    with app.app_context():
        assert db.session.get(Documento, cena["it"]).status == "Elaborar"


def test_iniciar_no_entregavel_poe_em_progresso(app, client, cena):
    from models import db, Entregavel
    r = iniciar(client, cena, ref_tipo="entregavel", ref_id=cena["ent"])
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["fluxo"]["link"] == \
        f"/projetos?projeto={cena['projeto']}&entregavel={cena['ent']}"
    with app.app_context():
        e = db.session.get(Entregavel, cena["ent"])
        assert e.status == "em_progresso"
        assert [h.status_novo for h in e.historico] == ["em_progresso"]


def test_segundo_fluxo_ativo_e_409(client, cena):
    assert iniciar(client, cena).status_code == 201
    assert iniciar(client, cena).status_code == 409


def test_entregavel_na_nao_inicia(app, client, cena):
    from models import db, Entregavel
    with app.app_context():
        db.session.get(Entregavel, cena["ent"]).status = "na"
        db.session.commit()
    assert iniciar(client, cena, ref_tipo="entregavel", ref_id=cena["ent"]).status_code == 400


def test_papel_sem_pessoa_e_400(client, cena):
    r = client.post("/fluxos/api/fluxos", headers=H(cena["tk"]["gestor"]), json={
        "ref_tipo": "documento", "ref_id": cena["manual"], "modelo_id": cena["modelo"],
        "participantes": {"autor": cena["giullia"]}})
    assert r.status_code == 400
    assert "Diagramador" in r.get_json()["erro"]


def test_leitura_fica_fora(client, cena, leitura_token):
    r = client.get(f"/fluxos/api/por-ref?ref_tipo=documento&ref_id={cena['manual']}",
                   headers=H(leitura_token))
    assert r.status_code == 403


def test_tecnico_de_fora_nao_ve_fluxo_de_entregavel(client, cena):
    f = iniciar(client, cena, ref_tipo="entregavel", ref_id=cena["ent"]).get_json()["fluxo"]
    r = client.get(f"/fluxos/api/fluxos/{f['fluxo_id']}", headers=H(cena["tk"]["tecnico"]))
    assert r.status_code == 403
    # ...mas a Giullia, participante, vê mesmo sem ser responsável no projeto.
    r = client.get(f"/fluxos/api/fluxos/{f['fluxo_id']}", headers=H(cena["tk"]["giullia"]))
    assert r.status_code == 200


# ── o ciclo ──────────────────────────────────────────────────────────────────

def test_ciclo_completo_com_devolucao(app, client, cena):
    from models import db, Documento, DocumentoArquivo
    tk = cena["tk"]
    f = iniciar(client, cena).get_json()["fluxo"]

    r = agir(client, f, tk["giullia"], "enviar", arquivos=[("texto.docx", b"texto v1")])
    assert r.status_code == 200, r.get_json()
    f = r.get_json()["fluxo"]
    assert f["etapa_nome"] == "Diagramação" and f["responsavel"]["id"] == cena["marcos"]

    r = agir(client, f, tk["marcos"], "enviar", arquivos=[("manual-v1.pdf", b"%PDF v1")])
    f = r.get_json()["fluxo"]
    assert f["etapa_nome"] == "Revisão" and f["responsavel"]["id"] == cena["giullia"]

    r = agir(client, f, tk["giullia"], "devolver", comentario="Trocar a figura 4",
             arquivos=[("marcado.pdf", b"%PDF marcas")])
    f = r.get_json()["fluxo"]
    assert f["etapa_nome"] == "Diagramação" and f["rodada"] == 2
    volta = notificacoes(client, tk["marcos"])[0]
    assert volta["tipo"] == "acao"
    assert volta["titulo"] == "Voltou para você: Diagramação (rodada 2)"
    assert "Trocar a figura 4" in volta["texto"]

    r = agir(client, f, tk["marcos"], "enviar", arquivos=[("manual-v2.pdf", b"%PDF v2")])
    f = r.get_json()["fluxo"]
    r = agir(client, f, tk["giullia"], "aprovar")
    assert r.status_code == 200
    f = r.get_json()["fluxo"]
    assert f["status"] == "aprovado" and f["acoes"] == []
    assert [p["acao"] for p in f["passagens"]] == \
        ["aprovar", "enviar", "devolver", "enviar", "enviar", "iniciar"]

    with app.app_context():
        doc = db.session.get(Documento, cena["manual"])
        assert doc.status == "Concluído"
        finais = DocumentoArquivo.query.filter_by(documento_id=doc.id).all()
        assert [a.nome_original for a in finais] == ["manual-v2.pdf"]
        assert "rodada 2" in finais[0].observacao

    assert notificacoes(client, tk["marcos"])[0]["titulo"].startswith("Aprovado:")


def test_aprovar_no_entregavel_conclui(app, client, cena):
    from models import db, Entregavel
    tk = cena["tk"]
    f = iniciar(client, cena, ref_tipo="entregavel", ref_id=cena["ent"]).get_json()["fluxo"]
    f = agir(client, f, tk["giullia"], "enviar").get_json()["fluxo"]
    f = agir(client, f, tk["marcos"], "enviar").get_json()["fluxo"]
    assert agir(client, f, tk["giullia"], "aprovar").status_code == 200
    with app.app_context():
        e = db.session.get(Entregavel, cena["ent"])
        assert e.status == "concluido" and e.percentual == 100 and e.data_conclusao


def test_cartao_vinculado_acompanha_o_documento(app, client, cena):
    from models import db, Missao, MissaoColuna, MissaoCartao
    with app.app_context():
        m = Missao(nome="Manuais")
        db.session.add(m)
        db.session.flush()
        cols = [MissaoColuna(missao_id=m.id, nome=n, categoria=c, ordem=i)
                for i, (n, c) in enumerate([("A fazer", "todo"), ("Fazendo", "doing"),
                                            ("Feito", "done")])]
        db.session.add_all(cols)
        db.session.flush()
        cartao = MissaoCartao(missao_id=m.id, coluna_id=cols[0].id, titulo="Manual X1",
                              ref_tipo="documento", ref_id=cena["manual"])
        db.session.add(cartao)
        db.session.commit()
        cid, fazendo, feito = cartao.id, cols[1].id, cols[2].id

    tk = cena["tk"]
    f = iniciar(client, cena).get_json()["fluxo"]
    with app.app_context():
        assert db.session.get(MissaoCartao, cid).coluna_id == fazendo
    f = agir(client, f, tk["giullia"], "enviar").get_json()["fluxo"]
    f = agir(client, f, tk["marcos"], "enviar").get_json()["fluxo"]
    agir(client, f, tk["giullia"], "aprovar")
    with app.app_context():
        c = db.session.get(MissaoCartao, cid)
        assert c.coluna_id == feito and c.concluido


# ── quem pode agir ───────────────────────────────────────────────────────────

def test_so_o_responsavel_age(client, cena):
    f = iniciar(client, cena).get_json()["fluxo"]
    assert agir(client, f, cena["tk"]["marcos"], "enviar").status_code == 403
    assert agir(client, f, cena["tk"]["tecnico"], "enviar").status_code == 403


def test_gestor_age_em_nome_do_responsavel(app, client, cena):
    from fluxos.models import FluxoPassagem
    f = iniciar(client, cena).get_json()["fluxo"]
    r = agir(client, f, cena["tk"]["gestor"], "enviar")
    assert r.status_code == 200
    with app.app_context():
        p = FluxoPassagem.query.filter_by(acao="enviar").first()
        assert p.em_nome_de_id == cena["giullia"] and p.por_id == cena["gestor"]
    # A Giullia é avisada do que fizeram em nome dela.
    textos = [a["titulo"] for a in notificacoes(client, cena["tk"]["giullia"])]
    assert any("em nome de Giullia" in t for t in textos)


def test_versao_velha_e_409(client, cena):
    f = iniciar(client, cena).get_json()["fluxo"]
    assert agir(client, f, cena["tk"]["giullia"], "enviar").status_code == 200
    r = agir(client, f, cena["tk"]["marcos"], "enviar")       # versão de antes
    assert r.status_code == 409
    assert r.get_json()["fluxo"]["etapa_nome"] == "Diagramação"


def test_devolver_sem_comentario_e_400(client, cena):
    tk = cena["tk"]
    f = iniciar(client, cena).get_json()["fluxo"]
    f = agir(client, f, tk["giullia"], "enviar").get_json()["fluxo"]
    f = agir(client, f, tk["marcos"], "enviar").get_json()["fluxo"]
    assert agir(client, f, tk["giullia"], "devolver").status_code == 400


def test_acao_que_nao_cabe_na_etapa_e_400(client, cena):
    f = iniciar(client, cena).get_json()["fluxo"]
    assert agir(client, f, cena["tk"]["giullia"], "aprovar").status_code == 400


def test_extensao_nao_aceita_e_415(client, cena):
    f = iniciar(client, cena).get_json()["fluxo"]
    r = agir(client, f, cena["tk"]["giullia"], "enviar", arquivos=[("x.exe", b"MZ")])
    assert r.status_code == 415


def test_arquivo_grande_e_413(client, cena, monkeypatch):
    import arquivos_store
    monkeypatch.setattr(arquivos_store, "MAX_BYTES", 10)
    f = iniciar(client, cena).get_json()["fluxo"]
    r = agir(client, f, cena["tk"]["giullia"], "enviar", arquivos=[("a.pdf", b"x" * 50)])
    assert r.status_code == 413


# ── gerir ────────────────────────────────────────────────────────────────────

def test_reatribuir_passa_a_vez(client, cena):
    f = iniciar(client, cena).get_json()["fluxo"]
    r = client.post(f"/fluxos/api/fluxos/{f['fluxo_id']}/reatribuir", headers=H(cena["tk"]["gestor"]),
                    json={"papel": "autor", "user_id": cena["tecnico"], "motivo": "férias",
                          "versao": f["versao"]})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["fluxo"]["responsavel"]["id"] == cena["tecnico"]
    assert notificacoes(client, cena["tk"]["tecnico"])[0]["tipo"] == "acao"
    assert notificacoes(client, cena["tk"]["giullia"])[0]["titulo"].startswith("Você saiu")


def test_reatribuir_e_cancelar_exigem_motivo_e_gestao(client, cena):
    f = iniciar(client, cena).get_json()["fluxo"]
    url = f"/fluxos/api/fluxos/{f['fluxo_id']}/cancelar"
    assert client.post(url, headers=H(cena["tk"]["gestor"]),
                       json={"versao": f["versao"]}).status_code == 400
    assert client.post(url, headers=H(cena["tk"]["giullia"]),
                       json={"versao": f["versao"], "motivo": "x"}).status_code == 403


def test_cancelar_nao_mexe_no_status_e_libera_novo_fluxo(app, client, cena):
    from models import db, Documento
    f = iniciar(client, cena).get_json()["fluxo"]
    r = client.post(f"/fluxos/api/fluxos/{f['fluxo_id']}/cancelar", headers=H(cena["tk"]["gestor"]),
                    json={"versao": f["versao"], "motivo": "Escopo mudou"})
    assert r.status_code == 200 and r.get_json()["fluxo"]["status"] == "cancelado"
    with app.app_context():
        assert db.session.get(Documento, cena["manual"]).status == "Em andamento"
    assert iniciar(client, cena).status_code == 201


# ── consultas ────────────────────────────────────────────────────────────────

def test_comigo_por_ref_e_por_refs(client, cena):
    f = iniciar(client, cena, ref_tipo="entregavel", ref_id=cena["ent"]).get_json()["fluxo"]
    comigo = client.get("/fluxos/api/comigo", headers=H(cena["tk"]["giullia"])).get_json()
    assert [x["fluxo_id"] for x in comigo["fluxos"]] == [f["fluxo_id"]]
    assert client.get("/fluxos/api/comigo", headers=H(cena["tk"]["marcos"])).get_json()["fluxos"] == []

    r = client.get(f"/fluxos/api/por-ref?ref_tipo=entregavel&ref_id={cena['ent']}",
                   headers=H(cena["tk"]["gestor"])).get_json()
    assert r["ativo"]["fluxo_id"] == f["fluxo_id"] and r["pode_iniciar"] is False

    r = client.get(f"/fluxos/api/por-refs?ref_tipo=entregavel&ids={cena['ent']},999",
                   headers=H(cena["tk"]["gestor"])).get_json()
    assert list(r["resumos"]) == [str(cena["ent"])]
    assert r["resumos"][str(cena["ent"])]["etapa_nome"] == "Escrita"


def test_conteudo_do_anexo(client, cena):
    f = iniciar(client, cena).get_json()["fluxo"]
    f = agir(client, f, cena["tk"]["giullia"], "enviar",
             arquivos=[("texto.pdf", b"%PDF conteudo")]).get_json()["fluxo"]
    aid = f["passagens"][0]["arquivos"][0]["id"]
    r = client.get(f"/fluxos/api/arquivos/{aid}/conteudo", headers=H(cena["tk"]["marcos"]))
    assert r.status_code == 200 and r.data == b"%PDF conteudo"


# ── travas no resto do sistema ───────────────────────────────────────────────

def test_documento_em_fluxo_nao_vira_na_nem_e_excluido(client, cena):
    iniciar(client, cena)
    gk = H(cena["tk"]["gestor"])
    r = client.put(f"/api/documentos/{cena['manual']}/aplicabilidade", headers=gk,
                   json={"aplicavel": False, "motivo_na_codigo": "nao_se_aplica_produto"})
    assert r.status_code == 409
    assert client.delete(f"/api/documentos/{cena['manual']}", headers=gk).status_code == 409


def test_entregavel_em_fluxo_nao_vira_na_nem_e_excluido(client, cena):
    iniciar(client, cena, ref_tipo="entregavel", ref_id=cena["ent"])
    gk = H(cena["tk"]["gestor"])
    assert client.put(f"/api/entregaveis/{cena['ent']}", headers=gk,
                      json={"status": "na"}).status_code == 409
    assert client.delete(f"/api/entregaveis/{cena['ent']}", headers=gk).status_code == 409


def test_tem_andamento_conta_fluxo_ativo(app, client, cena):
    from models import db, Entregavel
    from modelo_sync import tem_andamento
    iniciar(client, cena, ref_tipo="entregavel", ref_id=cena["ent"])
    with app.app_context():
        e = db.session.get(Entregavel, cena["ent"])
        e.status = "pendente"           # alguém reabriu à mão
        e.historico.clear()
        db.session.commit()
        assert tem_andamento(db.session.get(Entregavel, cena["ent"]))


def test_blob_de_fluxo_nao_e_orfao(app, client, cena):
    from documentos import _sha_orfao
    from fluxos.models import FluxoArquivo
    f = iniciar(client, cena).get_json()["fluxo"]
    agir(client, f, cena["tk"]["giullia"], "enviar", arquivos=[("t.pdf", b"%PDF unico")])
    with app.app_context():
        assert not _sha_orfao(FluxoArquivo.query.first().sha256)


# ── modelos ──────────────────────────────────────────────────────────────────

def test_modelo_crud_e_nome_unico(client, cena):
    gk = H(cena["tk"]["gestor"])
    corpo = {"nome": "IT", "papeis": [{"nome": "Elaborador"}, {"nome": "Revisor"}],
             "etapas": [{"nome": "Elaboração", "papel": "elaborador"},
                        {"nome": "Revisão técnica", "papel": "revisor", "tipo": "revisao"}]}
    r = client.post("/fluxos/api/modelos", headers=gk, json=corpo)
    assert r.status_code == 201, r.get_json()
    mid = r.get_json()["modelo"]["id"]
    assert client.post("/fluxos/api/modelos", headers=gk,
                       json=dict(corpo, nome="it")).status_code == 400
    assert client.post("/fluxos/api/modelos", headers=H(cena["tk"]["giullia"]),
                       json=dict(corpo, nome="Outro")).status_code == 403
    assert client.delete(f"/fluxos/api/modelos/{mid}", headers=gk).status_code == 200
    ativos = client.get("/fluxos/api/modelos", headers=gk).get_json()["modelos"]
    assert "IT" not in [m["nome"] for m in ativos]


def test_editar_modelo_nao_mexe_no_fluxo_andando(client, cena):
    f = iniciar(client, cena).get_json()["fluxo"]
    gk = H(cena["tk"]["gestor"])
    r = client.put(f"/fluxos/api/modelos/{cena['modelo']}", headers=gk, json={
        "etapas": [{"nome": "Escrita", "papel": "autor"}]})
    assert r.status_code == 200, r.get_json()
    d = client.get(f"/fluxos/api/fluxos/{f['fluxo_id']}", headers=gk).get_json()["fluxo"]
    assert [e["nome"] for e in d["etapas"]] == ["Escrita", "Diagramação", "Revisão"]
