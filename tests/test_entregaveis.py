"""Testes do módulo de Entregáveis (Projeto, Entregavel, API, export)."""


# ── Conversão célula → status ────────────────────────────────────────────────

def test_converter_celula():
    from models import converter_celula
    assert converter_celula(1) == ("concluido", 100)
    assert converter_celula(1.0) == ("concluido", 100)
    assert converter_celula(0) == ("pendente", 0)
    assert converter_celula(0.85) == ("em_progresso", 85)
    assert converter_celula(0.5) == ("em_progresso", 50)
    assert converter_celula("NA") == ("na", None)
    assert converter_celula("na") == ("na", None)
    assert converter_celula("N/A") == ("na", None)
    assert converter_celula(None) == ("na", None)
    assert converter_celula("") == ("na", None)
    # Lixo de fórmula → na
    assert converter_celula("#REF!") == ("na", None)


# ── Avanço calculado ─────────────────────────────────────────────────────────

def test_avanco_projeto(app):
    from models import db, Projeto, Entregavel
    with app.app_context():
        p = Projeto(nome="Teste X", ano=2026)
        db.session.add(p)
        db.session.flush()
        db.session.add_all([
            Entregavel(projeto_id=p.id, tipo="A", categoria="Produto", status="concluido"),
            Entregavel(projeto_id=p.id, tipo="B", categoria="Produto", status="pendente"),
            Entregavel(projeto_id=p.id, tipo="C", categoria="Sistema",
                       status="em_progresso", percentual=50),
            Entregavel(projeto_id=p.id, tipo="D", categoria="Sistema", status="na"),
        ])
        db.session.commit()
        # (100 + 0 + 50) / 3 aplicáveis = 50
        assert p.avanco == 50


def test_avanco_projeto_sem_entregaveis(app):
    from models import db, Projeto
    with app.app_context():
        p = Projeto(nome="Vazio", ano=2026)
        db.session.add(p)
        db.session.commit()
        assert p.avanco == 0


def test_avanco_projeto_todos_na(app):
    from models import db, Projeto, Entregavel
    with app.app_context():
        p = Projeto(nome="Só NA", ano=2026)
        db.session.add(p)
        db.session.flush()
        db.session.add(Entregavel(projeto_id=p.id, tipo="A", categoria="Produto", status="na"))
        db.session.commit()
        assert p.avanco == 0


# ── Parser da planilha ───────────────────────────────────────────────────────

def test_extrair_colunas_entregaveis():
    """Forward-fill de categorias e corte nas colunas de % mensal."""
    from importar_entregaveis import extrair_colunas
    # Simula linhas 1-3 da aba (listas alinhadas por índice de coluna, 0-based)
    linha1 = [None]*10 + ["Produto", None, "Sistema", None, "% janeiro", None]
    linha2 = ["Ordem", "MoSCoW", "Prioridade", "Entregáveis", None, "Descrição",
              "Consumível?", "Cronograma Mapeado", "SKU", "Lançamentos",
              "Validação Técnica", "Protótipo", "Software Neutro", "Embalagem",
              "% janeiro", "%fevereiro"]
    linha3 = [None]*10 + ["Paulo/Giullia", "Julio/ Diego", "Paulo", "Paulo/Giullia", None, None]
    cols = extrair_colunas(linha1, linha2, linha3)
    assert cols == [
        (10, "Validação Técnica", "Produto", "Paulo/Giullia"),
        (11, "Protótipo", "Produto", "Julio/ Diego"),
        (12, "Software Neutro", "Sistema", "Paulo"),
        (13, "Embalagem", "Sistema", "Paulo/Giullia"),
    ]


# ── Fixtures locais ──────────────────────────────────────────────────────────

import pytest


@pytest.fixture
def projeto_seed(app):
    """Projeto com 3 entregáveis para testes de API."""
    from models import db, Projeto, Entregavel
    with app.app_context():
        p = Projeto(nome="Amplio Teste", sku="01.000001", moscow="Must",
                    prioridade=1, lancamento="2026", ano=2026)
        db.session.add(p)
        db.session.flush()
        db.session.add_all([
            Entregavel(projeto_id=p.id, tipo="Protótipo", categoria="Produto",
                       status="concluido", responsaveis="Julio/Diego"),
            Entregavel(projeto_id=p.id, tipo="Manual do Usuário PT", categoria="Documentação",
                       status="pendente", responsaveis="Guilherme/Melk"),
            Entregavel(projeto_id=p.id, tipo="Software Neutro", categoria="Sistema",
                       status="em_progresso", percentual=90, responsaveis="Paulo"),
        ])
        db.session.commit()
        return p.id


# ── GET /api/projetos ────────────────────────────────────────────────────────

def test_listar_projetos(client, gestor_token, auth_headers, projeto_seed):
    res = client.get("/api/projetos", headers=auth_headers(gestor_token))
    assert res.status_code == 200
    projetos = res.get_json()["projetos"]
    assert len(projetos) == 1
    p = projetos[0]
    assert p["nome"] == "Amplio Teste"
    assert p["avanco"] == 63           # (100+0+90)/3 = 63.33 → 63
    assert p["pendentes"] == 1


def test_listar_projetos_sem_token(client, projeto_seed):
    res = client.get("/api/projetos")
    assert res.status_code == 401


# Técnico entra em modo restrito: só vê projeto onde tem entregável atribuído.
# Sem atribuição, a lista vem vazia (não é 403 — ele tem acesso ao módulo).
def test_listar_projetos_tecnico_sem_atribuicao_ve_lista_vazia(
        client, tecnico_token, auth_headers, projeto_seed):
    res = client.get("/api/projetos", headers=auth_headers(tecnico_token))
    assert res.status_code == 200
    assert res.get_json()["projetos"] == []


def test_listar_projetos_tecnico_nao_recebe_financeiro(
        client, gestor_token, tecnico_token, auth_headers, projeto_seed):
    from models import db, Entregavel, User
    with client.application.app_context():
        tec = User.query.filter_by(email="tecnico@test.com").first()
        e = Entregavel.query.filter_by(projeto_id=projeto_seed).first()
        e.responsaveis_users = [tec]
        db.session.commit()
    res = client.get("/api/projetos", headers=auth_headers(tecnico_token))
    assert res.status_code == 200
    body = res.get_json()
    assert body["financeiro"] is False
    projs = body["projetos"]
    assert len(projs) == 1
    assert "orcamento" not in projs[0]
    # nenhum valor em R$ pode escapar — inclusive sv/cv, que são variações
    # monetárias (EV−PV e EV−AC), não percentuais
    for k in ("bac", "pv", "ev", "ac", "sv", "cv", "cpi", "eac"):
        assert k not in projs[0]["pmo"], k
    # gestor continua vendo tudo
    res_g = client.get("/api/projetos", headers=auth_headers(gestor_token))
    assert "orcamento" in res_g.get_json()["projetos"][0]


def test_listar_projetos_leitura_negado(client, leitura_token, auth_headers, projeto_seed):
    res = client.get("/api/projetos", headers=auth_headers(leitura_token))
    assert res.status_code == 403


def test_detalhe_projeto_agrupado(client, gestor_token, auth_headers, projeto_seed):
    res = client.get(f"/api/projetos/{projeto_seed}", headers=auth_headers(gestor_token))
    assert res.status_code == 200
    body = res.get_json()
    assert body["nome"] == "Amplio Teste"
    cats = body["categorias"]
    assert [c["categoria"] for c in cats] == ["Produto", "Sistema", "Documentação"]
    assert cats[2]["entregaveis"][0]["tipo"] == "Manual do Usuário PT"


# ── PUT /api/entregaveis/<id> ────────────────────────────────────────────────

def _primeiro_entregavel_id(client, token, auth_headers, projeto_id):
    res = client.get(f"/api/projetos/{projeto_id}", headers=auth_headers(token))
    return res.get_json()["categorias"][0]["entregaveis"][0]["id"]


def test_gestor_atualiza_entregavel(client, gestor_token, auth_headers, projeto_seed):
    eid = _primeiro_entregavel_id(client, gestor_token, auth_headers, projeto_seed)
    res = client.put(f"/api/entregaveis/{eid}", headers=auth_headers(gestor_token),
                     json={"status": "em_progresso", "percentual": 40})
    assert res.status_code == 200
    body = res.get_json()
    assert body["entregavel"]["status"] == "em_progresso"
    assert body["entregavel"]["percentual"] == 40
    assert body["entregavel"]["atualizado_por"] == "gestor@test.com"
    assert "avanco_projeto" in body


def test_tecnico_nao_edita(client, gestor_token, tecnico_token, auth_headers, projeto_seed):
    eid = _primeiro_entregavel_id(client, gestor_token, auth_headers, projeto_seed)
    res = client.put(f"/api/entregaveis/{eid}", headers=auth_headers(tecnico_token),
                     json={"status": "concluido"})
    assert res.status_code == 403


def test_leitura_nao_edita(client, gestor_token, leitura_token, auth_headers, projeto_seed):
    eid = _primeiro_entregavel_id(client, gestor_token, auth_headers, projeto_seed)
    res = client.put(f"/api/entregaveis/{eid}", headers=auth_headers(leitura_token),
                     json={"status": "concluido"})
    assert res.status_code == 403


def test_percentual_invalido(client, gestor_token, auth_headers, projeto_seed):
    eid = _primeiro_entregavel_id(client, gestor_token, auth_headers, projeto_seed)
    res = client.put(f"/api/entregaveis/{eid}", headers=auth_headers(gestor_token),
                     json={"status": "em_progresso", "percentual": 150})
    assert res.status_code == 400


def test_status_invalido(client, gestor_token, auth_headers, projeto_seed):
    eid = _primeiro_entregavel_id(client, gestor_token, auth_headers, projeto_seed)
    res = client.put(f"/api/entregaveis/{eid}", headers=auth_headers(gestor_token),
                     json={"status": "fazendo"})
    assert res.status_code == 400


def test_concluido_forca_percentual_100(client, gestor_token, auth_headers, projeto_seed):
    eid = _primeiro_entregavel_id(client, gestor_token, auth_headers, projeto_seed)
    res = client.put(f"/api/entregaveis/{eid}", headers=auth_headers(gestor_token),
                     json={"status": "concluido", "percentual": 37})
    assert res.status_code == 200
    assert res.get_json()["entregavel"]["percentual"] == 100


def test_edicao_gera_audit_log(client, gestor_token, admin_token, auth_headers, projeto_seed):
    eid = _primeiro_entregavel_id(client, gestor_token, auth_headers, projeto_seed)
    client.put(f"/api/entregaveis/{eid}", headers=auth_headers(gestor_token),
               json={"status": "pendente"})
    res = client.get("/api/audit?limit=10", headers=auth_headers(admin_token))
    assert res.status_code == 200
    # /api/audit retorna uma lista JSON direta (sem chave "logs"/"entries")
    acoes = [e.get("acao") for e in res.get_json()]
    assert "ENTREGAVEL_UPDATED" in acoes


# ── CRUD de projetos (admin/gestor) ──────────────────────────────────────────

def test_criar_projeto_gestor(client, gestor_token, auth_headers):
    res = client.post("/api/projetos", headers=auth_headers(gestor_token),
                      json={"nome": "Novo Produto", "moscow": "Should", "ano": 2026})
    assert res.status_code == 201
    assert res.get_json()["projeto"]["nome"] == "Novo Produto"


def test_criar_projeto_tecnico_negado(client, tecnico_token, auth_headers):
    res = client.post("/api/projetos", headers=auth_headers(tecnico_token),
                      json={"nome": "X"})
    assert res.status_code == 403


def test_arquivar_projeto(client, admin_token, auth_headers, projeto_seed):
    res = client.delete(f"/api/projetos/{projeto_seed}", headers=auth_headers(admin_token))
    assert res.status_code == 200
    # some da listagem padrão
    res = client.get("/api/projetos", headers=auth_headers(admin_token))
    assert res.get_json()["projetos"] == []


# ── Resumo e export ──────────────────────────────────────────────────────────

def test_resumo(client, gestor_token, auth_headers, projeto_seed):
    res = client.get("/api/entregaveis/resumo", headers=auth_headers(gestor_token))
    assert res.status_code == 200
    body = res.get_json()
    assert body["projetos"] == 1
    assert body["pendentes"] == 1
    assert body["concluidos"] == 1
    assert "Guilherme/Melk" in body["por_responsavel"]


def test_resumo_leitura_negado(client, leitura_token, auth_headers, projeto_seed):
    res = client.get("/api/entregaveis/resumo", headers=auth_headers(leitura_token))
    assert res.status_code == 403


def test_export_excel(client, gestor_token, auth_headers, projeto_seed):
    res = client.get("/api/entregaveis/export", headers=auth_headers(gestor_token))
    assert res.status_code == 200
    assert res.content_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    # arquivo xlsx começa com assinatura PK (zip)
    assert res.data[:2] == b"PK"


def test_export_tecnico_negado(client, tecnico_token, auth_headers, projeto_seed):
    res = client.get("/api/entregaveis/export", headers=auth_headers(tecnico_token))
    assert res.status_code == 403


# ── Página ───────────────────────────────────────────────────────────────────

def test_pagina_entregaveis(client):
    res = client.get("/entregaveis")
    assert res.status_code == 200
    assert b"Entreg" in res.data


# -- Pagina hub -----------------------------------------------------------------

def test_pagina_hub(client):
    res = client.get("/hub")
    assert res.status_code == 200
    assert b"DOCTRACK" in res.data
