"""Testes dos filtros de busca e setor (norm, setor, busca textual)."""


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
    assert len(r1) == 1
    assert r1[0]["documento"] == "POP-001"


def test_filter_busca_acento_insensitive(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    # "Carlos Mota" é responsavel em MAQ-A
    r = client.get("/api/documentos?q=c%C3%A1rlos", headers=h)  # cárlos
    assert r.status_code == 200
    r2 = client.get("/api/documentos?q=carlos", headers=h)
    assert r2.status_code == 200
    assert len(r.get_json()) == len(r2.get_json())
    assert len(r.get_json()) == 1
    assert r.get_json()[0]["equipamento"] == "MAQ-A"


def test_filter_setor_pre(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    r = client.get("/api/documentos?setor=PRE", headers=h)
    assert r.status_code == 200
    docs = r.get_json()
    assert len(docs) == 1
    assert docs[0]["setor"] == "PRE"


def test_filter_setor_fabricante(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    r = client.get("/api/documentos?setor=Fabricante", headers=h)
    assert r.status_code == 200
    docs = r.get_json()
    assert len(docs) == 1
    assert docs[0]["setor"] == "Fabricante"


def test_filter_setor_pde(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    r = client.get("/api/documentos?setor=PDE", headers=h)
    assert r.status_code == 200
    docs = r.get_json()
    assert len(docs) == 1
    assert docs[0]["setor"] == "PDE"


def test_filter_sem_resultados(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    r = client.get("/api/documentos?setor=Inexistente", headers=h)
    assert r.status_code == 200
    assert r.get_json() == []


def test_busca_em_multiplos_campos(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    # MAQ é parte do nome do equipamento em MAQ-A e MAQ-B
    r = client.get("/api/documentos?q=MAQ", headers=h).get_json()
    assert len(r) == 2
    
    # Siemens é a fabricante em MAQ-B
    r2 = client.get("/api/documentos?q=siemens", headers=h).get_json()
    assert len(r2) == 1
    assert r2[0]["equipamento"] == "MAQ-B"
