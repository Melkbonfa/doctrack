"""Testes da evolução do módulo de Documentos.

Cobre o que foi corrigido/criado: KPIs que fecham com o donut, documentos de
processo (setor PDE) editáveis, trilha de status, caminho herdado do
equipamento, prazo/atraso, export CSV e diagnóstico de arquivos.
"""
from datetime import date, timedelta


def _doc_de_tipo(client, headers, equipamento, tipo):
    docs = client.get("/api/documentos", headers=headers).get_json()
    return next(d for d in docs if d["equipamento"] == equipamento and d["tipo_doc"] == tipo)


# ── KPIs ─────────────────────────────────────────────────────────────────────
def test_kpi_total_fecha_com_o_donut(client, admin_token, auth_headers, app):
    """total == soma de por_setor. Documento de processo não infla o total.

    Era a divergência do dashboard: o card dizia 475 documentos e o donut
    somava 469 — a diferença eram 6 documentos de setor 'PDE', contados no
    total mas fora de por_setor.
    """
    from models import db, Documento
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-KPI2"}, headers=h)

    with app.app_context():
        db.session.add(Documento(setor="PDE", equipamento="P&D (Processos)",
                                 documento="POP - Fluxo", codigo_doc="POP.01",
                                 status="Elaborar"))
        db.session.commit()

    kpis = client.get("/api/metrics", headers=h).get_json()
    assert kpis["total"] == sum(kpis["por_setor"].values())
    assert kpis["processos"] == 1
    assert sum(kpis["global_counts"].values()) == kpis["total"]


# ── Documentos de processo (setor PDE) ───────────────────────────────────────
def test_documento_processo_aceita_troca_de_status(client, admin_token, auth_headers, app):
    """Documento de processo era ineditável: STATUS_MAP não tinha a chave 'PDE'
    e todo PATCH/PUT de status devolvia 400."""
    from models import db, Documento
    h = auth_headers(admin_token)
    with app.app_context():
        d = Documento(setor="PDE", equipamento="P&D (Processos)",
                      documento="IT - Elaboração de QI/QO/QD",
                      codigo_doc="IT.PDE.01", status="Elaborar")
        db.session.add(d)
        db.session.commit()
        doc_id = d.id

    res = client.put(f"/api/documento/{doc_id}/status",
                     json={"status": "Em andamento"}, headers=h)
    assert res.status_code == 200
    assert res.get_json()["documento"]["status"] == "Em andamento"

    invalido = client.put(f"/api/documento/{doc_id}/status",
                          json={"status": "Homologado"}, headers=h)
    assert invalido.status_code == 400


# ── Trilha de status ─────────────────────────────────────────────────────────
def test_historico_registra_transicoes(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-HIST"}, headers=h)
    doc = _doc_de_tipo(client, h, "MAQ-HIST", "IT")

    client.put(f"/api/documento/{doc['id']}/status",
               json={"status": "Treinamento Piloto"}, headers=h)
    client.patch(f"/api/documentos/{doc['id']}",
                 json={"status": "Enviado para Homologação"}, headers=h)

    res = client.get(f"/api/documentos/{doc['id']}/historico", headers=h)
    assert res.status_code == 200
    body = res.get_json()
    transicoes = [(x["status_antigo"], x["status_novo"]) for x in body["historico"]
                  if x["evento"] == "status"]
    assert ("Treinamento Piloto", "Enviado para Homologação") in transicoes
    assert ("Elaborar", "Treinamento Piloto") in transicoes
    assert ("", "Elaborar") in transicoes          # marco de criação
    assert body["status"] == "Enviado para Homologação"
    assert body["dias_no_status"] == 0


def test_historico_registra_escopo(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-HIST2"}, headers=h)
    doc = _doc_de_tipo(client, h, "MAQ-HIST2", "Manual_ES")

    client.put(f"/api/documentos/{doc['id']}/aplicabilidade",
               json={"aplicavel": False, "motivo_na_codigo": "nao_se_aplica_produto"},
               headers=h)

    hist = client.get(f"/api/documentos/{doc['id']}/historico", headers=h).get_json()
    escopo = [x for x in hist["historico"] if x["evento"] == "escopo"]
    assert len(escopo) == 1
    assert escopo[0]["aplicavel"] is False
    assert escopo[0]["motivo"] == "Não se aplica a este produto"


# ── Armazenamento herdado ────────────────────────────────────────────────────
# A unidade P: é apelido de \\test-srv\Projetos$ na suíte (ver conftest): o
# caminho colado com letra é gravado na forma canônica UNC.
_UNC = r"\\test-srv\Projetos$"


def test_armazenamento_herda_do_equipamento(client, admin_token, auth_headers):
    """Salvar o caminho num documento sobe para o equipamento e vale para os 12.

    Antes, o mesmo caminho era copiado nas 12 linhas e editar numa aba não
    refletia nas outras 11.
    """
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-ARM"}, headers=h)
    it = _doc_de_tipo(client, h, "MAQ-ARM", "IT")

    res = client.patch(f"/api/documentos/{it['id']}",
                       json={"armazenamento": r"P:\Engenharia\MAQ-ARM"}, headers=h)
    assert res.status_code == 200
    d = res.get_json()["documento"]
    assert d["armazenamento"] == ""                                   # sem override
    assert d["armazenamento_efetivo"] == _UNC + r"\Engenharia\MAQ-ARM"

    # o irmão de outro tipo enxerga o mesmo caminho, sem ter sido editado
    manual = _doc_de_tipo(client, h, "MAQ-ARM", "Manual_Servico")
    assert manual["armazenamento_efetivo"] == _UNC + r"\Engenharia\MAQ-ARM"
    assert manual["armazenamento_base"] == _UNC + r"\Engenharia\MAQ-ARM"


def test_armazenamento_divergente_vira_override(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-ARM2"}, headers=h)
    it = _doc_de_tipo(client, h, "MAQ-ARM2", "IT")
    client.patch(f"/api/documentos/{it['id']}",
                 json={"armazenamento": r"P:\Engenharia\MAQ-ARM2"}, headers=h)

    chk = _doc_de_tipo(client, h, "MAQ-ARM2", "Checklist_Produto")
    res = client.patch(f"/api/documentos/{chk['id']}",
                       json={"armazenamento": r"P:\Engenharia\MAQ-ARM2\Checklists"}, headers=h)
    d = res.get_json()["documento"]
    assert d["armazenamento"] == _UNC + r"\Engenharia\MAQ-ARM2\Checklists"  # override real
    assert d["armazenamento_efetivo"] == _UNC + r"\Engenharia\MAQ-ARM2\Checklists"
    # o equipamento continua com o caminho base
    assert d["armazenamento_base"] == _UNC + r"\Engenharia\MAQ-ARM2"


def test_caminho_com_letra_nao_vira_override_falso(client, admin_token, auth_headers):
    """O bug do dia a dia: o base gravado em UNC e o mesmo caminho colado do
    Explorer como `P:\\...`. Sem canonizar, a comparação por string dizia que
    eram pastas diferentes e criava um override que ninguém pediu."""
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-ARM3"}, headers=h)
    it = _doc_de_tipo(client, h, "MAQ-ARM3", "IT")
    client.patch(f"/api/documentos/{it['id']}",
                 json={"armazenamento": _UNC + r"\Engenharia\MAQ-ARM3"}, headers=h)

    chk = _doc_de_tipo(client, h, "MAQ-ARM3", "Checklist_Produto")
    res = client.patch(f"/api/documentos/{chk['id']}",
                       json={"armazenamento": r"P:\Engenharia\MAQ-ARM3"}, headers=h)
    d = res.get_json()["documento"]
    assert d["armazenamento"] == ""            # mesma pasta do equipamento: herda
    assert d["armazenamento_efetivo"] == _UNC + r"\Engenharia\MAQ-ARM3"


# ── Prazo e atraso ───────────────────────────────────────────────────────────
def test_prazo_marca_atraso(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-PRZ"}, headers=h)
    doc = _doc_de_tipo(client, h, "MAQ-PRZ", "IT")

    ontem = (date.today() - timedelta(days=1)).isoformat()
    res = client.patch(f"/api/documentos/{doc['id']}", json={"prazo": ontem}, headers=h)
    assert res.status_code == 200
    d = res.get_json()["documento"]
    assert d["prazo"] == ontem
    assert d["dias_para_prazo"] == -1
    assert d["atrasado"] is True

    kpis = client.get("/api/metrics", headers=h).get_json()
    assert kpis["atrasados"] >= 1

    # documento finalizado não fica atrasado
    fim = client.patch(f"/api/documentos/{doc['id']}", json={"status": "Homologado"}, headers=h)
    assert fim.get_json()["documento"]["atrasado"] is False


def test_prazo_invalido_rejeitado(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-PRZ2"}, headers=h)
    doc = _doc_de_tipo(client, h, "MAQ-PRZ2", "IT")
    res = client.patch(f"/api/documentos/{doc['id']}", json={"prazo": "31/12/2026"}, headers=h)
    assert res.status_code == 400


def test_prazo_invalido_nao_grava_nada(client, admin_token, auth_headers):
    """PATCH rejeitado não pode gravar pela metade.

    log_action() dá commit, então validar o prazo depois de escrever os outros
    campos deixaria o código salvo e devolveria 400.
    """
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-PRZ4"}, headers=h)
    doc = _doc_de_tipo(client, h, "MAQ-PRZ4", "IT")

    res = client.patch(f"/api/documentos/{doc['id']}",
                       json={"codigo_doc": "NAO-DEVE-GRAVAR", "prazo": "ontem"}, headers=h)
    assert res.status_code == 400
    depois = _doc_de_tipo(client, h, "MAQ-PRZ4", "IT")
    assert depois["codigo_doc"] == doc["codigo_doc"]
    assert depois["version"] == doc["version"]


def test_documento_na_nunca_atrasa(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-PRZ3"}, headers=h)
    doc = _doc_de_tipo(client, h, "MAQ-PRZ3", "Manual_ES")
    ontem = (date.today() - timedelta(days=1)).isoformat()
    client.patch(f"/api/documentos/{doc['id']}", json={"prazo": ontem}, headers=h)
    res = client.put(f"/api/documentos/{doc['id']}/aplicabilidade",
                     json={"aplicavel": False, "motivo_na_codigo": "fornecido_fabricante"},
                     headers=h)
    assert res.get_json()["documento"]["atrasado"] is False


# ── Export / picker / diagnóstico ────────────────────────────────────────────
def test_export_csv(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    res = client.get("/api/documentos/export", headers=h)
    assert res.status_code == 200
    assert "text/csv" in res.headers["Content-Type"]
    texto = res.data.decode("utf-8-sig")
    linhas = [l for l in texto.splitlines() if l.strip()]
    assert linhas[0].startswith("Equipamento;SKU;")
    assert any("MAQ-A" in l for l in linhas[1:])


def test_export_respeita_filtro_de_setor(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    texto = client.get("/api/documentos/export?setor=Manuais", headers=h).data.decode("utf-8-sig")
    linhas = [l for l in texto.splitlines() if l.strip()][1:]
    assert linhas and all(";Manuais;" in l for l in linhas)


def test_picker_de_responsaveis(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    res = client.get("/api/documentos/responsaveis", headers=h)
    assert res.status_code == 200
    emails = {u["email"] for u in res.get_json()}
    assert "admin@test.com" in emails and "gestor@test.com" in emails


def test_diagnostico_aponta_documento_sem_nenhuma_fonte(client, admin_token,
                                                        tecnico_token, auth_headers):
    """Contrato da rota. As regras do confronto em si estão em test_diagnostico.py."""
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-DIAG"}, headers=h)

    res = client.get("/api/documentos/diagnostico", headers=h)
    assert res.status_code == 200
    rel = res.get_json()
    assert "SEM_ARQUIVO" in {i["tipo"] for i in rel["issues"]}
    assert rel["stats"]["sem_nenhuma_fonte"] >= 1

    # o apontamento traz o contexto para agir, para cada documento do grupo
    sem_arquivo = next(i for i in rel["issues"] if i["tipo"] == "SEM_ARQUIVO")
    assert sem_arquivo["qtd"] == len(sem_arquivo["documentos"])
    primeiro = sem_arquivo["documentos"][0]
    assert primeiro["equipamento"] and primeiro["tipo_doc_label"] and primeiro["id"]

    # técnico não vê diagnóstico (admin/gestor)
    assert client.get("/api/documentos/diagnostico",
                      headers=auth_headers(tecnico_token)).status_code == 403


def test_diagnostico_nao_acusa_documento_com_arquivo_na_plataforma(
        client, admin_token, auth_headers, tmp_path, monkeypatch):
    """Regressão do falso positivo: o upload nunca preenche `armazenamento`, e o
    documento que vive só na plataforma era reportado como 'sem local'."""
    import io
    import arquivos_store
    monkeypatch.setattr(arquivos_store, "RAIZ", str(tmp_path / "blobs"))

    h = auth_headers(admin_token)
    doc = client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-UP"},
                      headers=h).get_json()["documento"]
    envio = client.post(f"/api/documentos/{doc['id']}/arquivos",
                        data={"arquivo": (io.BytesIO(b"%PDF-1.4"), "Manual.pdf")},
                        content_type="multipart/form-data", headers=h)
    assert envio.status_code == 201

    rel = client.get("/api/documentos/diagnostico", headers=h).get_json()
    afetados = {d["id"] for i in rel["issues"] for d in i["documentos"]}
    assert doc["id"] not in afetados
