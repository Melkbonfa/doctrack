"""Testes de compute_kpis e endpoint /api/metrics."""


def test_compute_kpis_basico():
    from servidor import compute_kpis
    docs = [
        {"setor": "PRE", "status": "Homologado", "status_global": "Finalizado"},
        {"setor": "Fabricante", "status": "Elaborar", "status_global": "Pendente"},
    ]
    k = compute_kpis(docs)
    assert k["total"] == 2
    assert k["finalizados"] == 1
    assert k["pendentes"] == 1
    assert k["em_progresso"] == 0
    assert k["pct_concluidos"] == 50.0
    assert k["por_setor"] == {"PRE": 1, "Fabricante": 1, "PDE": 0}
    assert k["global_counts"] == {"Finalizado": 1, "Em progresso": 0, "Pendente": 1}
    assert k["status_counts"]["PRE"]["Homologado"] == 1
    assert k["status_counts"]["Fabricante"]["Elaborar"] == 1


def test_compute_kpis_lista_vazia():
    from servidor import compute_kpis
    k = compute_kpis([])
    assert k["total"] == 0
    assert k["finalizados"] == 0
    assert k["pct_concluidos"] == 0
    assert k["por_setor"] == {"PRE": 0, "Fabricante": 0, "PDE": 0}


def test_metrics_endpoint(client, admin_token, auth_headers):
    res = client.get("/api/metrics", headers=auth_headers(admin_token))
    assert res.status_code == 200
    m = res.get_json()
    # Estrutura esperada na v4.0
    for key in ("total", "finalizados", "em_progresso", "pendentes",
                "backlog", "pct_concluidos", "por_setor", "status_counts", "global_counts"):
        assert key in m, f"Falta chave: {key}"
    assert m["total"] == 3
    assert m["finalizados"] == 1    # MAQ-A (PRE Homologado -> Finalizado)
    assert m["em_progresso"] == 1   # MAQ-B (Fabricante Em andamento -> Em progresso)
    assert m["pendentes"] == 1      # MAQ-C (PDE Elaborar -> Pendente)


def test_data_endpoint_inclui_kpis(client, admin_token, auth_headers):
    res = client.get("/api/data", headers=auth_headers(admin_token))
    data = res.get_json()
    assert "items" in data
    assert "kpis" in data
    assert data["kpis"]["total"] == 3
