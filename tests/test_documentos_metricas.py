"""Testes da instrumentação e das métricas de fluxo dos Documentos.

Cobre o que a migration 011 destravou: marcos temporais gravados nas trocas de
status, responsáveis tipados (N:N) e as leituras que a trilha já permitia mas
ninguém fazia — aging, cycle time, throughput, carga por pessoa e o agregado
dos motivos de N/A.
"""
from datetime import datetime, timedelta


def _doc_de(client, headers, equipamento, tipo="IT"):
    docs = client.get("/api/documentos", headers=headers).get_json()
    return next(d for d in docs if d["equipamento"] == equipamento
                and d["tipo_doc"] == tipo)


# ── MARCOS TEMPORAIS ─────────────────────────────────────────────────────────

def test_documento_nasce_com_entrada_no_status(client, admin_token, auth_headers):
    """Sem `entrou_status_em` o aging de um documento novo não teria referência."""
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-M1"},
                headers=h)
    doc = _doc_de(client, h, "MAQ-M1")
    assert doc["dias_no_status"] == 0
    assert doc["concluido"] is False
    assert doc["concluido_em"] == ""
    assert doc["peso"] == 1.0


def test_troca_de_status_move_o_marco_de_aging(client, admin_token, auth_headers, app):
    """Trocar de status reinicia a contagem de dias parado."""
    from models import db, Documento
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-M2"},
                headers=h)
    doc = _doc_de(client, h, "MAQ-M2")

    # envelhece o documento 40 dias no status inicial
    with app.app_context():
        d = db.session.get(Documento, doc["id"])
        d.entrou_status_em = datetime.now() - timedelta(days=40)
        db.session.commit()

    assert _doc_de(client, h, "MAQ-M2")["dias_no_status"] == 40

    client.put(f"/api/documento/{doc['id']}/status",
               json={"status": "Treinamento Piloto"}, headers=h)
    assert _doc_de(client, h, "MAQ-M2")["dias_no_status"] == 0


def test_conclusao_grava_data_e_autor(client, admin_token, auth_headers):
    """`concluido_em` é o que permite throughput e cycle time."""
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-M3"},
                headers=h)
    doc = _doc_de(client, h, "MAQ-M3")

    client.put(f"/api/documento/{doc['id']}/status",
               json={"status": "Homologado"}, headers=h)
    atualizado = _doc_de(client, h, "MAQ-M3")
    assert atualizado["concluido"] is True
    assert atualizado["concluido_em"] != ""
    assert atualizado["concluido_por"] == "admin@test.com"
    assert atualizado["dias_ciclo"] == 0


def test_reabrir_documento_limpa_a_conclusao(client, admin_token, auth_headers):
    """Reabrir e concluir de novo não pode contar duas vezes no throughput."""
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-M4"},
                headers=h)
    doc = _doc_de(client, h, "MAQ-M4")

    client.put(f"/api/documento/{doc['id']}/status",
               json={"status": "Homologado"}, headers=h)
    assert _doc_de(client, h, "MAQ-M4")["concluido_em"] != ""

    client.put(f"/api/documento/{doc['id']}/status",
               json={"status": "Elaborar"}, headers=h)
    reaberto = _doc_de(client, h, "MAQ-M4")
    assert reaberto["concluido"] is False
    assert reaberto["concluido_em"] == ""
    assert reaberto["concluido_por"] == ""
    assert reaberto["dias_ciclo"] is None


# ── RESPONSÁVEIS TIPADOS ─────────────────────────────────────────────────────

def test_responsaveis_ids_alimentam_o_texto_legado(client, admin_token, auth_headers):
    """O N:N é a fonte; `responsavel` segue existindo como texto exibido."""
    h = auth_headers(admin_token)
    users = client.get("/api/documentos/responsaveis", headers=h).get_json()
    tecnico = next(u for u in users if u["role"] == "tecnico")

    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-M5"},
                headers=h)
    doc = _doc_de(client, h, "MAQ-M5")

    res = client.patch(f"/api/documentos/{doc['id']}",
                       json={"responsaveis_ids": [tecnico["id"]]}, headers=h)
    assert res.status_code == 200
    atualizado = res.get_json()["documento"]
    assert atualizado["responsaveis_ids"] == [tecnico["id"]]
    assert atualizado["responsaveis_nomes"] == [tecnico["nome"]]
    assert atualizado["responsavel"] == tecnico["nome"]


def test_responsavel_inexistente_e_rejeitado(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-M6"},
                headers=h)
    doc = _doc_de(client, h, "MAQ-M6")
    res = client.patch(f"/api/documentos/{doc['id']}",
                       json={"responsaveis_ids": [99999]}, headers=h)
    assert res.status_code == 400


def test_texto_livre_ainda_conta_como_responsavel(client, admin_token, auth_headers):
    """A planilha só tem nome digitado: quem não casou com um usuário continua
    valendo, senão 520 documentos apareceriam como 'sem responsável'."""
    h = auth_headers(admin_token)
    docs = client.get("/api/documentos", headers=h).get_json()
    doc = next(d for d in docs if d["equipamento"] == "MAQ-A")
    assert doc["responsaveis_ids"] == []
    assert doc["responsaveis_nomes"] == ["Carlos Mota"]


# ── MÉTRICAS ─────────────────────────────────────────────────────────────────

def test_metricas_totais_e_wip(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-W1"},
                headers=h)
    doc = _doc_de(client, h, "MAQ-W1")
    client.put(f"/api/documento/{doc['id']}/status",
               json={"status": "Treinamento Piloto"}, headers=h)

    m = client.get("/api/documentos/metricas", headers=h).get_json()
    assert m["totais"]["wip"] >= 1
    assert m["totais"]["total"] == m["totais"]["abertos"] + m["totais"]["concluidos"]
    assert any(s["status"] == "Treinamento Piloto" for s in m["por_status"])


def test_metricas_ignoram_documentos_na(client, admin_token, auth_headers):
    """N/A sai do fluxo (mesma regra dos KPIs) e vira linha em motivos_na."""
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-NA"},
                headers=h)
    doc = _doc_de(client, h, "MAQ-NA")

    antes = client.get("/api/documentos/metricas", headers=h).get_json()
    client.put(f"/api/documentos/{doc['id']}/aplicabilidade",
               json={"aplicavel": False, "motivo_na_codigo": "nao_se_aplica_produto"},
               headers=h)
    depois = client.get("/api/documentos/metricas", headers=h).get_json()

    assert depois["totais"]["total"] == antes["totais"]["total"] - 1
    assert depois["totais"]["nao_aplicaveis"] == antes["totais"]["nao_aplicaveis"] + 1
    motivo = next(m for m in depois["motivos_na"]
                  if m["codigo"] == "nao_se_aplica_produto")
    assert motivo["n"] >= 1
    assert motivo["label"]      # rótulo canônico, não o código cru


def test_metricas_throughput_e_cycle_time(client, admin_token, auth_headers, app):
    """Concluídos na janela alimentam throughput por semana e os percentis."""
    from models import db, Documento
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-TP"},
                headers=h)
    doc = _doc_de(client, h, "MAQ-TP")
    client.put(f"/api/documento/{doc['id']}/status",
               json={"status": "Homologado"}, headers=h)

    # 10 dias entre criação e conclusão
    with app.app_context():
        d = db.session.get(Documento, doc["id"])
        d.criado_em = datetime.now() - timedelta(days=10)
        db.session.commit()

    m = client.get("/api/documentos/metricas?dias=30", headers=h).get_json()
    assert m["throughput"]["concluidos"] >= 1
    assert len(m["throughput"]["por_semana"]) >= 1
    assert m["cycle_time"]["amostra"] >= 1
    assert m["cycle_time"]["p85"] is not None


def test_metricas_janela_exclui_conclusao_antiga(client, admin_token, auth_headers, app):
    from models import db, Documento
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-TP2"},
                headers=h)
    doc = _doc_de(client, h, "MAQ-TP2")
    client.put(f"/api/documento/{doc['id']}/status",
               json={"status": "Homologado"}, headers=h)

    with app.app_context():
        d = db.session.get(Documento, doc["id"])
        d.concluido_em = datetime.now() - timedelta(days=200)
        db.session.commit()

    m = client.get("/api/documentos/metricas?dias=30", headers=h).get_json()
    ids_semana = sum(s["n"] for s in m["throughput"]["por_semana"])
    assert ids_semana == m["throughput"]["concluidos"]
    # o documento continua concluído no total, mas fora da janela
    assert m["totais"]["concluidos"] >= 1


def test_marco_de_migracao_nao_vira_data_de_conclusao(client, admin_token,
                                                     auth_headers, app):
    """Regressão: o backfill não pode inventar throughput.

    `_backfill_historico_documentos` grava um marco com status_antigo='' e a
    data de updated_em. Aceitá-lo como data de conclusão fazia os 64 documentos
    já concluídos do banco real aparecerem todos como "concluídos nos últimos 30
    dias", com tempo de ciclo zero. Concluído antes da instrumentação tem data
    DESCONHECIDA — e a resposta declara quantos são.
    """
    from models import db, Documento, DocumentoHistorico
    from servidor import _backfill_marcos_documentos
    h = auth_headers(admin_token)

    with app.app_context():
        d = Documento(setor="PRE", equipamento="MAQ-LEGADO", documento="IT antiga",
                      tipo_doc="IT", status="Homologado")
        db.session.add(d)
        db.session.commit()
        # só o marco de migração: status_antigo vazio, autor 'system'
        db.session.add(DocumentoHistorico(
            documento_id=d.id, evento="status", status_antigo="",
            status_novo="Homologado", em=datetime.now(), por="system",
            motivo="Marco inicial (migração)"))
        db.session.commit()
        _backfill_marcos_documentos()
        atualizado = db.session.get(Documento, d.id)
        assert atualizado.concluido is True
        assert atualizado.entrou_status_em is not None   # aging tem referência
        assert atualizado.concluido_em is None           # conclusão é desconhecida

    m = client.get("/api/documentos/metricas", headers=h).get_json()
    assert m["throughput"]["sem_data"] >= 1
    # conta no total e no avanço, mas não no throughput nem no ciclo
    assert m["totais"]["concluidos"] >= 1
    assert m["cycle_time"]["amostra"] == 0
    assert m["cycle_time"]["p85"] is None


def test_backfill_limpa_conclusao_sintetica(app):
    """Bancos que passaram pela versão anterior do backfill são corrigidos."""
    from models import db, Documento, DocumentoHistorico
    from servidor import _backfill_marcos_documentos

    with app.app_context():
        d = Documento(setor="PRE", equipamento="MAQ-SINT", documento="IT sint",
                      tipo_doc="IT", status="Homologado",
                      entrou_status_em=datetime.now(),
                      concluido_em=datetime.now(), concluido_por="system")
        db.session.add(d)
        db.session.commit()
        db.session.add(DocumentoHistorico(
            documento_id=d.id, evento="status", status_antigo="",
            status_novo="Homologado", em=datetime.now(), por="system"))
        db.session.commit()

        _backfill_marcos_documentos()
        atualizado = db.session.get(Documento, d.id)
        assert atualizado.concluido_em is None
        assert atualizado.concluido_por == ""


def test_conclusao_real_sobrevive_ao_backfill(app):
    """Transição registrada de verdade continua contando como conclusão."""
    from models import db, Documento, DocumentoHistorico
    from servidor import _backfill_marcos_documentos

    with app.app_context():
        d = Documento(setor="PRE", equipamento="MAQ-REAL", documento="IT real",
                      tipo_doc="IT", status="Homologado")
        db.session.add(d)
        db.session.commit()
        db.session.add(DocumentoHistorico(
            documento_id=d.id, evento="status",
            status_antigo="Enviado para Homologação", status_novo="Homologado",
            em=datetime.now() - timedelta(days=3), por="alguem@test.com"))
        db.session.commit()

        _backfill_marcos_documentos()
        assert db.session.get(Documento, d.id).concluido_em is not None


def test_metricas_carga_por_responsavel(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    users = client.get("/api/documentos/responsaveis", headers=h).get_json()
    gestor = next(u for u in users if u["role"] == "gestor")

    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-CG"},
                headers=h)
    doc = _doc_de(client, h, "MAQ-CG")
    client.patch(f"/api/documentos/{doc['id']}",
                 json={"responsaveis_ids": [gestor["id"]], "peso": 3},
                 headers=h)

    m = client.get("/api/documentos/metricas", headers=h).get_json()
    reg = next(r for r in m["por_responsavel"] if r["nome"] == gestor["nome"])
    assert reg["abertos"] >= 1
    assert reg["peso"] >= 3.0
    # quem não tem ninguém atribuído aparece agrupado, não desaparece
    assert any(r["nome"] == "(sem responsável)" for r in m["por_responsavel"])


def test_metricas_avanco_ponderado_usa_peso(client, admin_token, auth_headers):
    """Um manual de 300 páginas não vale o mesmo que um checklist."""
    h = auth_headers(admin_token)
    m = client.get("/api/documentos/metricas", headers=h).get_json()
    assert m["avanco"]["peso_total"] > 0
    assert 0 <= m["avanco"]["ponderado"] <= 100
    assert 0 <= m["avanco"]["por_documento"] <= 100


def test_metricas_aging_ordena_pelos_mais_parados(client, admin_token, auth_headers, app):
    from models import db, Documento
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-AG"},
                headers=h)
    doc = _doc_de(client, h, "MAQ-AG")
    with app.app_context():
        d = db.session.get(Documento, doc["id"])
        d.entrou_status_em = datetime.now() - timedelta(days=365)
        db.session.commit()

    m = client.get("/api/documentos/metricas", headers=h).get_json()
    assert m["aging"][0]["documento_id"] == doc["id"]
    assert m["aging"][0]["dias"] >= 365
    dias = [a["dias"] for a in m["aging"]]
    assert dias == sorted(dias, reverse=True)


def test_metricas_tempo_medio_por_status_vem_da_trilha(client, admin_token,
                                                       auth_headers, app):
    """Intervalo fechado (evento → evento seguinte) é lido do histórico."""
    from models import db, Documento, DocumentoHistorico
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-TM"},
                headers=h)
    doc = _doc_de(client, h, "MAQ-TM")
    client.put(f"/api/documento/{doc['id']}/status",
               json={"status": "Treinamento Piloto"}, headers=h)

    # afasta os dois eventos em 20 dias
    with app.app_context():
        linhas = (DocumentoHistorico.query
                  .filter_by(documento_id=doc["id"])
                  .order_by(DocumentoHistorico.em).all())
        linhas[0].em = datetime.now() - timedelta(days=20)
        db.session.commit()

    m = client.get("/api/documentos/metricas", headers=h).get_json()
    elaborar = next(s for s in m["por_status"] if s["status"] == "Elaborar")
    assert elaborar["amostras"] >= 1
    assert elaborar["dias_medios"] > 0


def test_metricas_filtra_por_setor(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    m = client.get("/api/documentos/metricas?setor=PRE", headers=h).get_json()
    assert m["setor"] == "PRE"
    assert set(m["por_setor"]) <= {"PRE"}


def test_metricas_exige_login(client):
    assert client.get("/api/documentos/metricas").status_code == 401


# ── ALERTAS ──────────────────────────────────────────────────────────────────

def test_alertas_prazo_vencido_e_critico(client, admin_token, auth_headers):
    from datetime import date
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-AL1"},
                headers=h)
    doc = _doc_de(client, h, "MAQ-AL1")
    passado = (date.today() - timedelta(days=5)).isoformat()
    client.patch(f"/api/documentos/{doc['id']}", json={"prazo": passado}, headers=h)

    dados = client.get("/api/documentos/alertas", headers=h).get_json()
    alerta = next(a for a in dados["alertas"]
                  if a["documento_id"] == doc["id"]
                  and a["tipo"] == "documento_vencido")
    assert alerta["severidade"] == "critico"
    assert "5 dia(s) em atraso" in alerta["detalhe"]
    assert dados["criticos"] >= 1
    # críticos vêm primeiro
    assert dados["alertas"][0]["severidade"] == "critico"


def test_alertas_documento_parado(client, admin_token, auth_headers, app):
    from models import db, Documento
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-AL2"},
                headers=h)
    doc = _doc_de(client, h, "MAQ-AL2")
    with app.app_context():
        d = db.session.get(Documento, doc["id"])
        d.entrou_status_em = datetime.now() - timedelta(days=45)
        db.session.commit()

    dados = client.get("/api/documentos/alertas?dias_parado=30", headers=h).get_json()
    assert any(a["documento_id"] == doc["id"] and a["tipo"] == "documento_parado"
               for a in dados["alertas"])
    # com o limite acima do aging, o alerta desaparece
    dados2 = client.get("/api/documentos/alertas?dias_parado=90", headers=h).get_json()
    assert not any(a["documento_id"] == doc["id"] and a["tipo"] == "documento_parado"
                   for a in dados2["alertas"])


def test_alertas_ignoram_concluidos_e_na(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-AL3"},
                headers=h)
    doc = _doc_de(client, h, "MAQ-AL3")
    client.put(f"/api/documento/{doc['id']}/status",
               json={"status": "Homologado"}, headers=h)

    dados = client.get("/api/documentos/alertas", headers=h).get_json()
    assert not any(a["documento_id"] == doc["id"] for a in dados["alertas"])


def test_alertas_mesmo_formato_dos_outros_modulos(client, admin_token, auth_headers):
    """{tipo, severidade, titulo, detalhe} — o front consome os três módulos
    com o mesmo componente."""
    h = auth_headers(admin_token)
    dados = client.get("/api/documentos/alertas", headers=h).get_json()
    assert set(dados) == {"alertas", "total", "criticos"}
    for a in dados["alertas"]:
        assert {"tipo", "severidade", "titulo", "detalhe"} <= set(a)
        assert a["severidade"] in ("critico", "atencao", "info")
