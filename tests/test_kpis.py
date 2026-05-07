"""Testes de compute_kpis e endpoint /api/metrics."""


def test_compute_kpis_basico():
    from servidor import compute_kpis
    docs = [
        {"status_global": "Finalizado", "categoria": "A", "origem": "X",
         "tipo_documento": "T", "subtipo": "S", "versao": "1.0", "local": "/x",
         "etapa_elaboracao": "Concluído", "etapa_revisao1": "Concluído",
         "etapa_diagramacao": "Concluído", "etapa_revisao2": "Concluído",
         "status_principal": ""},
        {"status_global": "Pendente", "categoria": "B", "origem": "Y",
         "tipo_documento": "T2", "subtipo": "S2", "versao": "", "local": "",
         "etapa_elaboracao": "Pendente", "etapa_revisao1": "Pendente",
         "etapa_diagramacao": "Pendente", "etapa_revisao2": "Pendente",
         "status_principal": ""},
    ]
    k = compute_kpis(docs)
    assert k["total"] == 2
    assert k["finalizados"] == 1
    assert k["pendentes"] == 1
    assert k["em_progresso"] == 0
    assert k["pct_concluidos"] == 50.0
    assert k["cat_counts"] == {"A": 1, "B": 1}
    assert k["origem_counts"] == {"X": 1, "Y": 1}
    assert k["pct_versao"] == 50.0
    assert k["pct_local"] == 50.0
    assert k["etapas"]["elaboracao"] == 1
    assert k["etapas_breakdown"]["elaboracao"]["Concluído"] == 1
    assert k["etapas_breakdown"]["elaboracao"]["Pendente"] == 1


def test_compute_kpis_lista_vazia():
    from servidor import compute_kpis
    k = compute_kpis([])
    assert k["total"] == 0
    assert k["finalizados"] == 0
    assert k["pct_concluidos"] == 0
    assert k["cat_counts"] == {}


def test_metrics_endpoint(client, admin_token, auth_headers):
    res = client.get("/api/metrics", headers=auth_headers(admin_token))
    assert res.status_code == 200
    m = res.get_json()
    # Estrutura esperada
    for key in ("total", "finalizados", "em_progresso", "pendentes",
                "etapas", "etapas_breakdown", "por_tipo", "por_subtipo",
                "cat_counts", "origem_counts", "global_counts"):
        assert key in m, f"Falta chave: {key}"
    assert m["total"] == 3
    # MAQ-A está finalizado (todas etapas concluídas)
    assert m["finalizados"] == 1
    assert m["em_progresso"] == 1  # MAQ-B
    assert m["pendentes"] == 1     # MAQ-C


def test_data_endpoint_inclui_kpis(client, admin_token, auth_headers):
    res = client.get("/api/data", headers=auth_headers(admin_token))
    data = res.get_json()
    assert "items" in data
    assert "kpis" in data
    assert data["kpis"]["total"] == 3
