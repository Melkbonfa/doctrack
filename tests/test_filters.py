"""Testes dos filtros (norm, status_global, busca textual, F2/F4/F9)."""


def test_norm_helper():
    from servidor import norm
    assert norm("Homologação") == "homologacao"
    assert norm("  POP  ") == "pop"
    assert norm("Ímpar") == "impar"
    assert norm(None) == ""
    assert norm("") == ""


def test_filter_busca_case_insensitive(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    r1 = client.get("/api/documentos?q=POP", headers=h).get_json()
    r2 = client.get("/api/documentos?q=pop", headers=h).get_json()
    r3 = client.get("/api/documentos?q=Pop", headers=h).get_json()
    assert len(r1) == len(r2) == len(r3)
    assert all("pop" in d["documento"].lower() or "pop" in d["subtipo"].lower() for d in r1)


def test_filter_busca_acento_insensitive(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    # Não temos acentos nos seeds, mas validamos que não dá erro
    r = client.get("/api/documentos?q=t%C3%A9cnico", headers=h)  # técnico
    assert r.status_code == 200
    r2 = client.get("/api/documentos?q=tecnico", headers=h)
    assert r2.status_code == 200
    assert len(r.get_json()) == len(r2.get_json())


def test_filter_status_global_finalizado(client, admin_token, auth_headers):
    r = client.get("/api/documentos?status_global=Finalizado", headers=auth_headers(admin_token))
    assert r.status_code == 200
    docs = r.get_json()
    # MAQ-A é o único com tudo concluído
    assert len(docs) == 1
    assert docs[0]["equipamento"] == "MAQ-A"
    assert docs[0]["status_global"] == "Finalizado"


def test_filter_status_global_pendente(client, admin_token, auth_headers):
    r = client.get("/api/documentos?status_global=Pendente", headers=auth_headers(admin_token))
    docs = r.get_json()
    assert all(d["status_global"] == "Pendente" for d in docs)


def test_filter_status_global_em_progresso(client, admin_token, auth_headers):
    r = client.get("/api/documentos?status_global=Em%20progresso", headers=auth_headers(admin_token))
    docs = r.get_json()
    # MAQ-B tem etapa_elaboracao em andamento
    assert len(docs) == 1
    assert docs[0]["equipamento"] == "MAQ-B"


def test_filter_categoria_exato(client, admin_token, auth_headers):
    r = client.get("/api/documentos?categoria=Qualidade", headers=auth_headers(admin_token))
    docs = r.get_json()
    assert all(d["categoria"] == "Qualidade" for d in docs)


def test_filter_origem(client, admin_token, auth_headers):
    r = client.get("/api/documentos?origem=Producao", headers=auth_headers(admin_token))
    docs = r.get_json()
    assert all(d["origem"] == "Producao" for d in docs)


def test_filter_combinado(client, admin_token, auth_headers):
    r = client.get("/api/documentos?categoria=Qualidade&status_global=Finalizado",
                   headers=auth_headers(admin_token))
    docs = r.get_json()
    assert len(docs) == 1
    assert docs[0]["categoria"] == "Qualidade"
    assert docs[0]["status_global"] == "Finalizado"


def test_filter_sem_resultados(client, admin_token, auth_headers):
    r = client.get("/api/documentos?categoria=Inexistente", headers=auth_headers(admin_token))
    assert r.get_json() == []


def test_busca_em_multiplos_campos(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    # MAQ é parte do nome do equipamento
    r = client.get("/api/documentos?q=MAQ", headers=h).get_json()
    assert len(r) == 3
    # P&D é a origem do MAQ-B
    r2 = client.get("/api/documentos?q=P%26D", headers=h).get_json()
    assert len(r2) == 1
    assert r2[0]["equipamento"] == "MAQ-B"
