"""Testes do módulo PMO/EVM.

Modelo automático: previsto = baseline linear pelas datas; realizado = avanço dos
entregáveis (vivo) reconstruído pelas conclusões das tarefas; custo é manual (mensal).
"""

import datetime as _dt
import pytest


def _hoje_iso():
    return _dt.date.today().isoformat()


# ── Baseline (previsto pelas datas) ──────────────────────────────────────────

def test_previsto_em_baseline_linear(app):
    from models import db, Projeto
    with app.app_context():
        p = Projeto(nome="Baseline", ano=2026,
                    data_inicio_prev="2026-01-01", data_fim_prev="2026-12-31")
        db.session.add(p)
        db.session.commit()
        assert p.previsto_em("2025-12") == 0      # antes do início
        assert p.previsto_em("2026-12") == 100    # mês do término
        assert p.previsto_em("2027-03") == 100    # depois do fim
        assert 45 < p.previsto_em("2026-06") < 60 # ~metade
        sem = Projeto(nome="Sem datas", ano=2026)
        db.session.add(sem); db.session.commit()
        assert sem.previsto_em("2026-06") is None


# ── Realizado reconstruído pelas conclusões das tarefas ──────────────────────

def test_realizado_em_pelas_conclusoes(app):
    from models import db, Projeto, Entregavel
    with app.app_context():
        p = Projeto(nome="Conclusões", ano=2020,
                    data_inicio_prev="2020-01-01", data_fim_prev="2020-12-31")
        db.session.add(p); db.session.flush()
        db.session.add_all([
            Entregavel(projeto_id=p.id, tipo="A", categoria="Produto",
                       status="concluido", data_conclusao="2020-03-15"),
            Entregavel(projeto_id=p.id, tipo="B", categoria="Produto",
                       status="concluido", data_conclusao="2020-09-15"),
        ])
        db.session.commit()
        assert p.realizado_em(_dt.date(2020, 1, 1)) == 0     # nada concluído ainda
        assert p.realizado_em(_dt.date(2020, 4, 1)) == 50    # só A
        assert p.realizado_em(_dt.date(2020, 12, 1)) == 100  # A e B


# ── EVM ao vivo (datas no passado → baseline = 100) ──────────────────────────

def test_evm_live_atrasado_e_estourando(app):
    from models import db, Projeto, Entregavel, ProjetoMensal
    with app.app_context():
        # plano inteiramente no passado → previsto (decorrido) = 100
        p = Projeto(nome="EVM live", ano=2020, orcamento=200000.0,
                    data_inicio_prev="2020-01-01", data_fim_prev="2020-12-31")
        db.session.add(p); db.session.flush()
        db.session.add_all([     # 2 concluídos + 2 pendentes → avanço 50
            Entregavel(projeto_id=p.id, tipo="A", categoria="Produto", status="concluido"),
            Entregavel(projeto_id=p.id, tipo="B", categoria="Produto", status="concluido"),
            Entregavel(projeto_id=p.id, tipo="C", categoria="Produto", status="pendente"),
            Entregavel(projeto_id=p.id, tipo="D", categoria="Produto", status="pendente"),
        ])
        db.session.add(ProjetoMensal(projeto_id=p.id, competencia="2020-06",
                                     custo_mes=150000.0))
        db.session.commit()
        m = p.pmo_metrics()
        assert m["pct_previsto"] == 100      # baseline (decorrido) no passado
        assert m["pct_realizado"] == 50      # avanço vivo dos entregáveis
        assert m["spi"] == 0.5               # 50/100
        assert m["ev"] == 100000.0           # 200k * 50%
        assert m["ac"] == 150000.0
        assert m["cpi"] == 0.667             # 100k/150k
        assert m["status_prazo"] == "critico"
        assert m["status_custo"] == "critico"
        assert m["tem_dados"] is True


def test_evm_live_adiantado(app):
    """Horizonte muito longo → baseline pequena no presente → SPI > 1."""
    from models import db, Projeto, Entregavel
    with app.app_context():
        p = Projeto(nome="Adiantado", ano=2020, orcamento=100000.0,
                    data_inicio_prev="2020-01-01", data_fim_prev="2120-01-01")
        db.session.add(p); db.session.flush()
        db.session.add_all([
            Entregavel(projeto_id=p.id, tipo="A", categoria="Produto", status="concluido"),
            Entregavel(projeto_id=p.id, tipo="B", categoria="Produto", status="pendente"),
        ])  # avanço 50
        db.session.commit()
        m = p.pmo_metrics()
        assert m["pct_realizado"] == 50
        assert m["pct_previsto"] < 50        # ainda no comecinho do horizonte
        assert m["spi"] > 1
        assert m["status_prazo"] == "ok"


def test_evm_sem_orcamento_calcula_spi_mas_nao_cpi(app):
    from models import db, Projeto, Entregavel
    with app.app_context():
        p = Projeto(nome="Sem orçamento", ano=2020, orcamento=0.0,
                    data_inicio_prev="2020-01-01", data_fim_prev="2020-12-31")
        db.session.add(p); db.session.flush()
        db.session.add_all([
            Entregavel(projeto_id=p.id, tipo="A", categoria="Produto", status="concluido"),
            Entregavel(projeto_id=p.id, tipo="B", categoria="Produto", status="pendente"),
            Entregavel(projeto_id=p.id, tipo="C", categoria="Produto", status="pendente"),
            Entregavel(projeto_id=p.id, tipo="D", categoria="Produto", status="pendente"),
        ])  # avanço 25
        db.session.commit()
        m = p.pmo_metrics()
        assert m["pct_realizado"] == 25
        assert m["spi"] == 0.25            # 25/100, sem precisar de BAC
        assert m["status_prazo"] == "critico"
        assert m["cpi"] is None
        assert m["status_custo"] == "sem_dados"


def test_evm_sem_datas_nao_calcula_spi(app):
    from models import db, Projeto, Entregavel, ProjetoMensal
    with app.app_context():
        p = Projeto(nome="Sem datas", ano=2026, orcamento=100000.0)
        db.session.add(p); db.session.flush()
        db.session.add(Entregavel(projeto_id=p.id, tipo="A", categoria="Produto",
                                  status="concluido"))
        db.session.add(ProjetoMensal(projeto_id=p.id, competencia="2026-05",
                                     custo_mes=50000.0))
        db.session.commit()
        m = p.pmo_metrics()
        assert m["pct_previsto"] is None
        assert m["spi"] is None
        assert m["status_prazo"] == "sem_dados"
        assert m["cpi"] is not None        # custo + BAC presentes


def test_evm_sem_dados(app):
    from models import db, Projeto
    with app.app_context():
        p = Projeto(nome="Vazio", ano=2026, orcamento=50000.0)
        db.session.add(p); db.session.commit()
        m = p.pmo_metrics()
        assert m["tem_dados"] is False
        assert m["spi"] is None and m["cpi"] is None


# ── Curva-S automática ───────────────────────────────────────────────────────

def test_serie_mensal_automatica(app):
    from models import db, Projeto, Entregavel
    with app.app_context():
        p = Projeto(nome="Curva", ano=2020,
                    data_inicio_prev="2020-01-01", data_fim_prev="2020-12-31")
        db.session.add(p); db.session.flush()
        db.session.add_all([
            Entregavel(projeto_id=p.id, tipo="A", categoria="Produto",
                       status="concluido", data_conclusao="2020-03-15"),
            Entregavel(projeto_id=p.id, tipo="B", categoria="Produto",
                       status="concluido", data_conclusao="2020-06-15"),
        ])
        db.session.commit()
        serie = p.serie_mensal()
        assert len(serie) >= 12               # de jan/2020 até hoje (passado distante)
        ponto = {s["competencia"]: s for s in serie}
        assert ponto["2020-02"]["pct_realizado"] == 0
        assert ponto["2020-04"]["pct_realizado"] == 50
        assert ponto["2020-07"]["pct_realizado"] == 100
        assert ponto["2020-06"]["pct_previsto"] is not None   # baseline pelas datas


# ── Fixture: projeto via API ─────────────────────────────────────────────────

@pytest.fixture
def projeto_id(client, gestor_token, auth_headers):
    res = client.post("/api/projetos", headers=auth_headers(gestor_token),
                      json={"nome": "Projeto PMO", "ano": 2026, "orcamento": "150.000,00",
                            "data_inicio_prev": "2026-01-01", "data_fim_prev": "2026-12-31"})
    assert res.status_code == 201
    return res.get_json()["projeto"]["id"]


def _add_entregavel(client, token, auth_headers, pid, tipo="Tarefa X"):
    res = client.post(f"/api/projetos/{pid}/entregaveis", headers=auth_headers(token),
                      json={"tipo": tipo, "categoria": "Produto"})
    assert res.status_code == 201
    return res.get_json()["entregavel"]["id"]


# ── Concluir tarefa define data de conclusão automaticamente ─────────────────

def test_concluir_tarefa_define_data_conclusao(client, gestor_token, auth_headers, projeto_id):
    eid = _add_entregavel(client, gestor_token, auth_headers, projeto_id)
    res = client.put(f"/api/entregaveis/{eid}", headers=auth_headers(gestor_token),
                     json={"status": "concluido"})
    assert res.status_code == 200
    assert res.get_json()["entregavel"]["data_conclusao"] == _hoje_iso()


def test_data_conclusao_explicita(client, gestor_token, auth_headers, projeto_id):
    eid = _add_entregavel(client, gestor_token, auth_headers, projeto_id)
    res = client.put(f"/api/entregaveis/{eid}", headers=auth_headers(gestor_token),
                     json={"status": "concluido", "data_conclusao": "2026-03-10"})
    assert res.status_code == 200
    assert res.get_json()["entregavel"]["data_conclusao"] == "2026-03-10"


def test_desconcluir_limpa_data(client, gestor_token, auth_headers, projeto_id):
    eid = _add_entregavel(client, gestor_token, auth_headers, projeto_id)
    client.put(f"/api/entregaveis/{eid}", headers=auth_headers(gestor_token),
               json={"status": "concluido"})
    res = client.put(f"/api/entregaveis/{eid}", headers=auth_headers(gestor_token),
                     json={"status": "pendente"})
    assert res.status_code == 200
    assert res.get_json()["entregavel"]["data_conclusao"] == ""


# ── Lançamento mensal (custo) ────────────────────────────────────────────────

def test_lancar_custo_mensal(client, gestor_token, auth_headers, projeto_id):
    res = client.put(f"/api/projetos/{projeto_id}/mensal", headers=auth_headers(gestor_token),
                     json={"competencia": "2026-05", "custo_acumulado": "100.000,00"})
    assert res.status_code == 200
    assert res.get_json()["mensal"]["custo_acumulado"] == 100000.0


def test_custo_atualiza_mesma_competencia(client, gestor_token, auth_headers, projeto_id):
    for v in (40000, 55000):
        client.put(f"/api/projetos/{projeto_id}/mensal", headers=auth_headers(gestor_token),
                   json={"competencia": "2026-05", "custo_acumulado": v})
    res = client.get(f"/api/projetos/{projeto_id}/mensal", headers=auth_headers(gestor_token))
    serie = [s for s in res.get_json()["serie"] if s["competencia"] == "2026-05"]
    assert len(serie) == 1
    assert serie[0]["custo_acumulado"] == 55000.0


def test_custo_invalido(client, gestor_token, auth_headers, projeto_id):
    res = client.put(f"/api/projetos/{projeto_id}/mensal", headers=auth_headers(gestor_token),
                     json={"competencia": "2026-05", "custo_acumulado": "abc"})
    assert res.status_code == 400


def test_mensal_competencia_invalida(client, gestor_token, auth_headers, projeto_id):
    res = client.put(f"/api/projetos/{projeto_id}/mensal", headers=auth_headers(gestor_token),
                     json={"competencia": "05/2026", "custo_acumulado": 1000})
    assert res.status_code == 400


def test_remover_custo_mensal(client, gestor_token, auth_headers, projeto_id):
    client.put(f"/api/projetos/{projeto_id}/mensal", headers=auth_headers(gestor_token),
               json={"competencia": "2026-07", "custo_acumulado": 1000})
    res = client.delete(f"/api/projetos/{projeto_id}/mensal/2026-07",
                        headers=auth_headers(gestor_token))
    assert res.status_code == 200


# ── Detalhe expõe série automática ───────────────────────────────────────────

def test_detalhe_serie_automatica(client, gestor_token, auth_headers, projeto_id):
    eid = _add_entregavel(client, gestor_token, auth_headers, projeto_id)
    client.put(f"/api/entregaveis/{eid}", headers=auth_headers(gestor_token),
               json={"status": "concluido", "data_conclusao": "2026-03-10"})
    res = client.get(f"/api/projetos/{projeto_id}", headers=auth_headers(gestor_token))
    body = res.get_json()
    assert "serie_mensal" in body and len(body["serie_mensal"]) >= 1
    # baseline calculada e realizado reconstruído pela conclusão
    assert body["serie_mensal"][0]["pct_previsto"] is not None
    assert body["pmo"]["tem_dados"] is True


# ── Permissões: módulo restrito a gestor+ ────────────────────────────────────

def test_mensal_tecnico_negado(client, tecnico_token, auth_headers, projeto_id):
    res = client.put(f"/api/projetos/{projeto_id}/mensal", headers=auth_headers(tecnico_token),
                     json={"competencia": "2026-05", "custo_acumulado": 1000})
    assert res.status_code == 403


def test_mensal_leitura_negado(client, leitura_token, auth_headers, projeto_id):
    res = client.get(f"/api/projetos/{projeto_id}/mensal", headers=auth_headers(leitura_token))
    assert res.status_code == 403


def test_mensal_sem_token(client, projeto_id):
    res = client.get(f"/api/projetos/{projeto_id}/mensal")
    assert res.status_code == 401
