"""Testes da evolução do módulo de Projetos.

Cobre o que foi acrescentado nos 4 blocos:
  1) correções (update parcial, precedência de datas, curva sem degrau, avanço médio)
  2) peso do entregável e ciclo de vida do projeto
  3) responsáveis como FK e permissão do técnico
  4) snapshot, linha de base versionada e alertas
"""
import datetime as _dt

import pytest


def _hoje():
    return _dt.date.today()


def _iso(d):
    return d.isoformat()


@pytest.fixture
def proj(client, gestor_token, auth_headers):
    """Projeto com cronograma e orçamento, sem entregáveis."""
    res = client.post("/api/projetos", headers=auth_headers(gestor_token), json={
        "nome": "Projeto Evolução", "tipo": "OEM", "orcamento": "100.000,00",
        "data_inicio_prev": "2026-01-01", "data_fim_prev": "2026-12-31",
        "entregaveis": [],
    })
    assert res.status_code == 201, res.get_json()
    return res.get_json()["projeto"]["id"]


def _add(client, tok, hdr, pid, **kw):
    body = {"tipo": kw.pop("tipo", "Tarefa"), "categoria": "Produto"}
    body.update(kw)
    res = client.post(f"/api/projetos/{pid}/entregaveis", headers=hdr(tok), json=body)
    assert res.status_code == 201, res.get_json()
    return res.get_json()["entregavel"]["id"]


# ══ BLOCO 1 — correções ══════════════════════════════════════════════════════

def test_update_invalido_nao_grava_nada(client, gestor_token, auth_headers, proj):
    """Validação falha → NENHUM campo é persistido.

    Antes, log_action() commitava dentro do laço de campos: o `nome` já tinha
    sido gravado quando o `tipo` inválido devolvia 400.
    """
    antes = client.get(f"/api/projetos/{proj}", headers=auth_headers(gestor_token)).get_json()
    res = client.put(f"/api/projetos/{proj}", headers=auth_headers(gestor_token),
                     json={"nome": "Nome Novo", "tipo": "Inexistente"})
    assert res.status_code == 400
    depois = client.get(f"/api/projetos/{proj}", headers=auth_headers(gestor_token)).get_json()
    assert depois["nome"] == antes["nome"]


def test_datas_invalidas_recusadas(client, gestor_token, auth_headers, proj):
    res = client.put(f"/api/projetos/{proj}", headers=auth_headers(gestor_token),
                     json={"data_fim_prev": "31/12/2026"})
    assert res.status_code == 400
    res = client.put(f"/api/projetos/{proj}", headers=auth_headers(gestor_token),
                     json={"data_inicio_prev": "2026-06-01", "data_fim_prev": "2026-01-01"})
    assert res.status_code == 400


def test_precedencia_de_datas_consistente(app):
    """PV do SPI e previsto da curva-S partem da MESMA data (a planejada).

    Com início real diferente do planejado, as duas fórmulas usavam
    precedências invertidas e mostravam previstos divergentes.
    """
    from models import db, Projeto
    with app.app_context():
        p = Projeto(nome="Precedência", ano=2020,
                    data_inicio_prev="2020-01-01", data_inicio_real="2020-07-01",
                    data_fim_prev="2020-12-31")
        db.session.add(p)
        db.session.commit()
        # ambos ancorados em 2020-01-01 → plano todo no passado → 100
        assert p.pct_prazo_decorrido == 100
        assert p.previsto_em("2020-06") == p.previsto_em("2020-06")
        assert 40 < p.previsto_em("2020-06") < 60   # meio do plano, não do real


def test_curva_s_sem_degrau_no_ponto_atual(app):
    """Passado e presente usam a mesma fórmula (ponderada), então uma tarefa
    parcial não faz o último ponto da curva pular de escala."""
    from models import db, Projeto, Entregavel
    with app.app_context():
        ontem = _hoje() - _dt.timedelta(days=1)
        p = Projeto(nome="Sem degrau", ano=_hoje().year,
                    data_inicio_prev=_iso(_hoje() - _dt.timedelta(days=60)),
                    data_fim_prev=_iso(_hoje() + _dt.timedelta(days=60)))
        db.session.add(p)
        db.session.flush()
        db.session.add_all([
            Entregavel(projeto_id=p.id, tipo="A", status="concluido",
                       data_conclusao=_iso(_hoje() - _dt.timedelta(days=30))),
            Entregavel(projeto_id=p.id, tipo="B", status="em_progresso", percentual=50),
        ])
        db.session.commit()
        # hoje: (100 + 50) / 2 = 75 — igual ao avanço vivo, sem outra escala
        assert p.realizado_em(_hoje()) == p.avanco == 75
        # ontem: só A contava (B não tem histórico anterior) → 50
        assert p.realizado_em(ontem) == 50


def test_avanco_medio_ignora_projeto_sem_escopo(client, gestor_token, auth_headers, proj):
    """Projeto sem entregável devolve avanço 0 e puxava a média para baixo."""
    pid2 = client.post("/api/projetos", headers=auth_headers(gestor_token),
                       json={"nome": "Com escopo", "entregaveis": []}).get_json()["projeto"]["id"]
    eid = _add(client, gestor_token, auth_headers, pid2)
    client.put(f"/api/entregaveis/{eid}", headers=auth_headers(gestor_token),
               json={"status": "concluido"})
    r = client.get("/api/entregaveis/resumo", headers=auth_headers(gestor_token)).get_json()
    # `proj` não tem entregáveis: fica fora da média, que é 100 (só o outro)
    assert r["avanco_medio"] == 100
    assert r["projetos_com_escopo"] == 1


# ══ BLOCO 2 — peso e ciclo de vida ═══════════════════════════════════════════

def test_avanco_ponderado_por_peso(app):
    from models import db, Projeto, Entregavel
    with app.app_context():
        p = Projeto(nome="Pesos", ano=2026)
        db.session.add(p)
        db.session.flush()
        db.session.add_all([
            Entregavel(projeto_id=p.id, tipo="Homologação", status="concluido", peso=8),
            Entregavel(projeto_id=p.id, tipo="Folder", status="pendente", peso=1),
            Entregavel(projeto_id=p.id, tipo="Banner", status="pendente", peso=1),
        ])
        db.session.commit()
        # média simples daria 33; ponderada dá 80 — o que reflete o esforço
        assert p.avanco == 80


def test_peso_invalido_recusado(client, gestor_token, auth_headers, proj):
    res = client.post(f"/api/projetos/{proj}/entregaveis",
                      headers=auth_headers(gestor_token),
                      json={"tipo": "X", "peso": 0})
    assert res.status_code == 400
    res = client.post(f"/api/projetos/{proj}/entregaveis",
                      headers=auth_headers(gestor_token),
                      json={"tipo": "X", "peso": "abc"})
    assert res.status_code == 400


def test_arquivar_distingue_concluido_de_cancelado(client, gestor_token, auth_headers):
    """`ativo=False` não dizia se o projeto terminou ou morreu no meio."""
    def novo(nome):
        return client.post("/api/projetos", headers=auth_headers(gestor_token),
                           json={"nome": nome, "entregaveis": []}).get_json()["projeto"]["id"]

    ok = novo("Terminou bem")
    eid = _add(client, gestor_token, auth_headers, ok)
    client.put(f"/api/entregaveis/{eid}", headers=auth_headers(gestor_token),
               json={"status": "concluido"})
    res = client.delete(f"/api/projetos/{ok}", headers=auth_headers(gestor_token))
    assert res.get_json()["projeto"]["status"] == "concluido"
    assert res.get_json()["projeto"]["data_fim_real"]      # preenchido automaticamente

    morto = novo("Morreu no meio")
    _add(client, gestor_token, auth_headers, morto)
    res = client.delete(f"/api/projetos/{morto}", headers=auth_headers(gestor_token))
    assert res.get_json()["projeto"]["status"] == "cancelado"


def test_filtro_por_status(client, gestor_token, auth_headers, proj):
    client.put(f"/api/projetos/{proj}", headers=auth_headers(gestor_token),
               json={"status": "suspenso"})
    r = client.get("/api/projetos?status=suspenso", headers=auth_headers(gestor_token))
    assert [p["id"] for p in r.get_json()["projetos"]] == [proj]
    r = client.get("/api/projetos?status=planejado", headers=auth_headers(gestor_token))
    assert r.get_json()["projetos"] == []
    r = client.get("/api/projetos?status=xpto", headers=auth_headers(gestor_token))
    assert r.status_code == 400


# ══ BLOCO 3 — responsáveis e permissão do técnico ════════════════════════════

def _tecnico(app):
    from models import User
    with app.app_context():
        return User.query.filter_by(email="tecnico@test.com").first().id


def test_carga_por_responsavel_usa_usuario_nao_texto(
        client, app, gestor_token, auth_headers, proj):
    """Texto livre gerava 'Melk' e 'Guilherme/Melk' como pessoas diferentes."""
    tid = _tecnico(app)
    _add(client, gestor_token, auth_headers, proj, tipo="T1", responsaveis_ids=[tid])
    _add(client, gestor_token, auth_headers, proj, tipo="T2", responsaveis_ids=[tid])
    r = client.get("/api/entregaveis/resumo", headers=auth_headers(gestor_token)).get_json()
    assert list(r["por_responsavel"].keys()) == ["Tecnico Test"]
    assert len(r["por_responsavel"]["Tecnico Test"]) == 2


def test_tecnico_atualiza_apenas_o_proprio_entregavel(
        client, app, gestor_token, tecnico_token, auth_headers, proj):
    tid = _tecnico(app)
    meu = _add(client, gestor_token, auth_headers, proj, tipo="Meu", responsaveis_ids=[tid])
    alheio = _add(client, gestor_token, auth_headers, proj, tipo="Alheio")

    res = client.put(f"/api/entregaveis/{meu}", headers=auth_headers(tecnico_token),
                     json={"status": "em_progresso", "percentual": 40})
    assert res.status_code == 200
    assert res.get_json()["entregavel"]["percentual"] == 40

    res = client.put(f"/api/entregaveis/{alheio}", headers=auth_headers(tecnico_token),
                     json={"status": "concluido"})
    assert res.status_code == 403


def test_tecnico_nao_altera_responsavel_peso_nem_plano(
        client, app, gestor_token, tecnico_token, auth_headers, proj):
    tid = _tecnico(app)
    eid = _add(client, gestor_token, auth_headers, proj, tipo="Meu", responsaveis_ids=[tid])
    for corpo in ({"responsaveis_ids": []}, {"peso": 5}, {"data_fim_prev": "2026-01-01"}):
        res = client.put(f"/api/entregaveis/{eid}", headers=auth_headers(tecnico_token),
                         json=corpo)
        assert res.status_code == 403, corpo


def test_leitura_continua_barrado(client, leitura_token, auth_headers, proj):
    assert client.get("/api/projetos", headers=auth_headers(leitura_token)).status_code == 403


# ══ BLOCO 4 — snapshot, linha de base e alertas ══════════════════════════════

def test_baseline_v1_no_nascimento_e_versao_ao_replanejar(
        client, gestor_token, auth_headers, proj):
    r = client.get(f"/api/projetos/{proj}/baselines", headers=auth_headers(gestor_token))
    assert [b["versao"] for b in r.get_json()["baselines"]] == [1]

    client.put(f"/api/projetos/{proj}", headers=auth_headers(gestor_token),
               json={"data_fim_prev": "2027-06-30",
                     "motivo_replanejamento": "Atraso do fornecedor"})
    r = client.get(f"/api/projetos/{proj}/baselines", headers=auth_headers(gestor_token))
    bs = r.get_json()["baselines"]
    assert [b["versao"] for b in bs] == [1, 2]
    # a v1 preserva o plano ORIGINAL — replanejar não apaga o compromisso anterior
    assert bs[0]["data_fim_prev"] == "2026-12-31"
    assert bs[1]["data_fim_prev"] == "2027-06-30"
    assert bs[1]["motivo"] == "Atraso do fornecedor"


def test_editar_campo_fora_da_baseline_nao_versiona(
        client, gestor_token, auth_headers, proj):
    client.put(f"/api/projetos/{proj}", headers=auth_headers(gestor_token),
               json={"sku": "SKU-9"})
    r = client.get(f"/api/projetos/{proj}/baselines", headers=auth_headers(gestor_token))
    assert len(r.get_json()["baselines"]) == 1


def test_snapshot_registra_foto_do_dia(client, gestor_token, auth_headers, proj):
    eid = _add(client, gestor_token, auth_headers, proj)
    client.put(f"/api/entregaveis/{eid}", headers=auth_headers(gestor_token),
               json={"status": "concluido"})
    d = client.get(f"/api/projetos/{proj}", headers=auth_headers(gestor_token)).get_json()
    hoje = _iso(_hoje())
    fotos = [s for s in d["tendencia"] if s["data"] == hoje]
    assert len(fotos) == 1          # idempotente no dia
    assert fotos[0]["avanco"] == 100


def test_alerta_de_entregavel_atrasado(client, gestor_token, auth_headers, proj):
    _add(client, gestor_token, auth_headers, proj, tipo="Atrasado",
         data_fim_prev=_iso(_hoje() - _dt.timedelta(days=5)))
    _add(client, gestor_token, auth_headers, proj, tipo="No prazo",
         data_fim_prev=_iso(_hoje() + _dt.timedelta(days=5)))
    r = client.get("/api/projetos/alertas", headers=auth_headers(gestor_token)).get_json()
    atrasos = [a for a in r["alertas"] if a["tipo"] == "entregavel_atrasado"]
    assert len(atrasos) == 1
    assert "Atrasado" in atrasos[0]["titulo"]
    assert atrasos[0]["severidade"] == "critico"


def test_alerta_de_projeto_vencido(client, gestor_token, auth_headers):
    pid = client.post("/api/projetos", headers=auth_headers(gestor_token), json={
        "nome": "Venceu", "entregaveis": [],
        "data_inicio_prev": "2020-01-01", "data_fim_prev": "2020-12-31",
    }).get_json()["projeto"]["id"]
    _add(client, gestor_token, auth_headers, pid)
    r = client.get("/api/projetos/alertas", headers=auth_headers(gestor_token)).get_json()
    tipos = {a["tipo"] for a in r["alertas"] if a["projeto_id"] == pid}
    assert "projeto_vencido" in tipos


def test_tecnico_nao_ve_alerta_financeiro(client, app, gestor_token, tecnico_token,
                                          auth_headers, proj):
    tid = _tecnico(app)
    _add(client, gestor_token, auth_headers, proj, tipo="Meu", responsaveis_ids=[tid])
    r = client.get("/api/projetos/alertas", headers=auth_headers(tecnico_token)).get_json()
    assert all(a["tipo"] != "estouro_orcamento" for a in r["alertas"])


def test_previsao_termino_por_velocidade(app):
    from models import db, Projeto, Entregavel
    with app.app_context():
        ini = _hoje() - _dt.timedelta(days=100)
        p = Projeto(nome="Velocidade", ano=_hoje().year, data_inicio_real=_iso(ini),
                    data_fim_prev=_iso(_hoje() + _dt.timedelta(days=20)))
        db.session.add(p)
        db.session.flush()
        db.session.add_all([
            Entregavel(projeto_id=p.id, tipo="A", status="concluido"),
            Entregavel(projeto_id=p.id, tipo="B", status="pendente"),
        ])
        db.session.commit()
        # 50% em 100 dias → 200 dias no total
        assert p.previsao_termino() == _iso(ini + _dt.timedelta(days=200))


def test_previsao_sem_historico_suficiente(app):
    from models import db, Projeto, Entregavel
    with app.app_context():
        p = Projeto(nome="Recente", ano=_hoje().year,
                    data_inicio_real=_iso(_hoje() - _dt.timedelta(days=3)))
        db.session.add(p)
        db.session.flush()
        db.session.add(Entregavel(projeto_id=p.id, tipo="A", status="pendente"))
        db.session.commit()
        assert p.previsao_termino() is None


def test_historico_de_entregavel_exposto(client, gestor_token, auth_headers, proj):
    eid = _add(client, gestor_token, auth_headers, proj)
    client.put(f"/api/entregaveis/{eid}", headers=auth_headers(gestor_token),
               json={"status": "em_progresso", "percentual": 30})
    client.put(f"/api/entregaveis/{eid}", headers=auth_headers(gestor_token),
               json={"status": "concluido"})
    r = client.get(f"/api/entregaveis/{eid}/historico",
                   headers=auth_headers(gestor_token)).get_json()
    assert [h["status_novo"] for h in r["historico"]] == ["em_progresso", "concluido"]


def test_auditoria_grava_uma_linha_por_fato(client, app, gestor_token, auth_headers, proj):
    """Antes cada mutação escrevia em audit_logs duas vezes (log_action + evento)."""
    from models import AuditLog
    with app.app_context():
        antes = AuditLog.query.filter(AuditLog.acao == "PROJETO_UPDATED").count()
    client.put(f"/api/projetos/{proj}", headers=auth_headers(gestor_token),
               json={"sku": "SKU-AUDIT"})
    with app.app_context():
        linhas = (AuditLog.query.filter(AuditLog.acao == "PROJETO_UPDATED")
                  .order_by(AuditLog.id).all())[antes:]
        campos = [l.campo for l in linhas]
        assert campos.count("sku") == 1
        sku = next(l for l in linhas if l.campo == "sku")
        assert sku.valor_novo == "SKU-AUDIT"
        assert sku.entidade.startswith("Projeto:")
