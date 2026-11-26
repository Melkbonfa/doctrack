"""Testes: carga por planilha pela tela (carga_web.py, /api/carga/*)."""
import io
import os

import pytest
from openpyxl import load_workbook

import carga_web


@pytest.fixture
def h(admin_token, auth_headers):
    return auth_headers(admin_token)


@pytest.fixture(autouse=True)
def _sem_previas():
    carga_web._previas.clear()
    yield
    carga_web._previas.clear()


@pytest.fixture
def backups(monkeypatch):
    """Backup falso: registra as chamadas e não escreve em backups/ do repo."""
    feitos = []

    def falso():
        feitos.append(1)
        return f"doctrack_teste_{len(feitos)}.sql"
    monkeypatch.setattr(carga_web, "fazer_backup", falso)
    return feitos


def _semear(client, h):
    for cat, nome in [("Produto", "Protótipo"), ("Documentação", "Manual")]:
        r = client.post("/api/modelos", json={"tipo_projeto": "OEM", "categoria": cat,
                                              "tipo": nome}, headers=h)
        assert r.status_code == 201, r.get_json()
    r = client.post("/api/projetos", json={"nome": "P", "tipo": "OEM"}, headers=h)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["projeto"]["id"]


def _ents(client, h, pid):
    det = client.get(f"/api/projetos/{pid}", headers=h).get_json()
    return {e["tipo"]: e for c in det["categorias"] for e in c["entregaveis"]}


def _baixar(client, h):
    r = client.get("/api/carga/planilha", headers=h)
    assert r.status_code == 200
    assert "DocTrack_carga_" in r.headers["Content-Disposition"]
    return load_workbook(io.BytesIO(r.data))


def _com_item_novo(wb, nome="Item novo", categoria="Produto"):
    wb["Itens do modelo"].append(["OEM", categoria, nome, 1, "", "", "", None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _previa(client, h, conteudo, nome="carga.xlsx"):
    data = {"arquivo": (io.BytesIO(conteudo), nome)}
    return client.post("/api/carga/previa", data=data, headers=h,
                       content_type="multipart/form-data")


def test_rotas_sao_so_de_admin(client, gestor_token, auth_headers):
    hg = auth_headers(gestor_token)
    assert client.get("/api/carga/planilha", headers=hg).status_code == 403
    assert _previa(client, hg, b"x").status_code == 403
    assert client.post("/api/carga/aplicar", json={"token": "x", "motivo": "teste"},
                       headers=hg).status_code == 403


def test_baixar_traz_as_abas(client, h):
    _semear(client, h)
    wb = _baixar(client, h)
    assert {"LEIA-ME", "Modelos", "Itens do modelo", "Projetos", "Listas"} <= set(wb.sheetnames)
    nomes = [r[2] for r in wb["Itens do modelo"].iter_rows(min_row=2, values_only=True)]
    assert nomes == ["Protótipo", "Manual"]


def test_previa_mostra_e_nao_grava(client, h, backups):
    pid = _semear(client, h)
    r = _previa(client, h, _com_item_novo(_baixar(client, h)))
    assert r.status_code == 200, r.get_json()
    corpo = r.get_json()
    resumo = {x["rotulo"]: x["n"] for x in corpo["relatorio"]["resumo"]}
    assert resumo["itens de modelo criados"] == 1
    assert resumo["entregáveis criados"] == 1
    assert corpo["token"] and corpo["relatorio"]["vazio"] is False
    assert "Item novo" not in _ents(client, h, pid)
    assert backups == []


def test_projeto_renomeado_fica_numa_secao_so(client, h):
    pid = _semear(client, h)
    wb = _baixar(client, h)
    for row in wb["Projetos"].iter_rows(min_row=2):
        if row[0].value == pid:
            row[1].value = "P renomeado"
    secoes = _previa(client, h, _com_item_novo(wb)).get_json()["relatorio"]["secoes"]
    titulos = [s["titulo"] for s in secoes if s["titulo"].startswith(f"Projeto {pid} ")]
    assert titulos == [f"Projeto {pid} · P"]


def test_previa_sem_mudanca_nao_gera_token(client, h):
    _semear(client, h)
    wb = _baixar(client, h)
    buf = io.BytesIO()
    wb.save(buf)
    corpo = _previa(client, h, buf.getvalue()).get_json()
    assert corpo["relatorio"]["vazio"] is True and corpo["token"] is None


def test_previa_com_erro_lista_os_problemas(client, h):
    _semear(client, h)
    r = _previa(client, h, _com_item_novo(_baixar(client, h), categoria="Inexistente"))
    assert r.status_code == 422
    erros = r.get_json()["erros"]
    assert any("Itens do modelo linha" in e and "Inexistente" in e for e in erros)


def test_arquivo_que_nao_e_planilha(client, h):
    assert _previa(client, h, b"isto nao e xlsx").status_code == 422
    assert _previa(client, h, b"x", nome="carga.csv").status_code == 400


def test_aplicar_grava_o_que_a_previa_mostrou(client, h, backups):
    pid = _semear(client, h)
    token = _previa(client, h, _com_item_novo(_baixar(client, h))).get_json()["token"]

    r = client.post("/api/carga/aplicar", json={"token": token, "motivo": "Carga pela tela"},
                    headers=h)
    assert r.status_code == 200, r.get_json()
    corpo = r.get_json()
    assert corpo["backup"] == "doctrack_teste_1.sql" and backups == [1]
    assert _ents(client, h, pid)["Item novo"]["do_modelo"] is True
    hist = client.get("/api/modelos/propagacao/historico?tipo=OEM", headers=h).get_json()
    assert hist["mudancas"][0]["motivo"] == "Carga pela tela"

    # O token vale uma vez só.
    r = client.post("/api/carga/aplicar", json={"token": token, "motivo": "De novo"}, headers=h)
    assert r.status_code == 409


def test_aplicar_exige_motivo_e_token_valido(client, h, backups):
    _semear(client, h)
    token = _previa(client, h, _com_item_novo(_baixar(client, h))).get_json()["token"]
    assert client.post("/api/carga/aplicar", json={"token": token, "motivo": "ok"},
                       headers=h).status_code == 400
    assert client.post("/api/carga/aplicar", json={"token": "outro", "motivo": "Motivo bom"},
                       headers=h).status_code == 409
    # Prévia de outra pessoa não é aplicável por este admin.
    carga_web._previas[token]["email"] = "outro@test.com"
    assert client.post("/api/carga/aplicar", json={"token": token, "motivo": "Motivo bom"},
                       headers=h).status_code == 409
    assert backups == []


def test_backup_falhou_nada_e_gravado(client, h, monkeypatch):
    pid = _semear(client, h)
    token = _previa(client, h, _com_item_novo(_baixar(client, h))).get_json()["token"]

    def falha():
        raise carga_web.ErroBackup("pg_dump não encontrado")
    monkeypatch.setattr(carga_web, "fazer_backup", falha)
    r = client.post("/api/carga/aplicar", json={"token": token, "motivo": "Carga pela tela"},
                    headers=h)
    assert r.status_code == 503
    assert "pg_dump não encontrado" in r.get_json()["erro"]
    assert "Item novo" not in _ents(client, h, pid)
    assert token in carga_web._previas          # dá para tentar de novo


def test_dados_mudaram_depois_da_previa(client, h, backups):
    _semear(client, h)
    wb = _baixar(client, h)
    token = _previa(client, h, _com_item_novo(wb)).get_json()["token"]
    # Alguém exclui pela tela um item que a planilha ainda referencia por id.
    mid = next(r[7] for r in wb["Itens do modelo"].iter_rows(min_row=2, values_only=True)
               if r[2] == "Manual")
    assert client.delete(f"/api/modelos/{mid}", headers=h).status_code in (200, 204)
    r = client.post("/api/carga/aplicar", json={"token": token, "motivo": "Carga pela tela"},
                    headers=h)
    assert r.status_code == 422
    assert any(f"id {mid} não existe" in e for e in r.get_json()["erros"])


def test_auditoria_so_no_aplicar(client, h, backups):
    from models import AuditLog
    _semear(client, h)
    token = _previa(client, h, _com_item_novo(_baixar(client, h))).get_json()["token"]
    assert AuditLog.query.filter_by(ip="planilha").count() == 0
    assert AuditLog.query.filter(AuditLog.entidade.like("%/api/carga/previa%")).count() == 0
    client.post("/api/carga/aplicar", json={"token": token, "motivo": "Carga pela tela"}, headers=h)
    resumo = AuditLog.query.filter_by(ip="planilha", campo="carga_planilha").one()
    assert resumo.usuario_email == "admin@test.com" and "Carga pela tela" in resumo.valor_novo


def test_backup_sqlite_de_verdade(app, tmp_path):
    app.config["CARGA_BACKUP_DIR"] = str(tmp_path / "bk")
    try:
        nome = carga_web.fazer_backup()
    finally:
        app.config.pop("CARGA_BACKUP_DIR")
    caminho = tmp_path / "bk" / nome
    assert nome.startswith("doctrack_carga_") and os.path.getsize(caminho) > 0


def test_pagina_de_configuracoes_tem_a_aba(client):
    html = client.get("/config").get_data(as_text=True)
    assert 'id="page-carga"' in html and "/static/carga.js" in html
