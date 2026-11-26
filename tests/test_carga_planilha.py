"""Testes: carga em massa de modelos e projetos por planilha
(scripts/carga_planilha.py)."""
import pytest
from openpyxl import load_workbook

import carga_planilha as cp


@pytest.fixture
def h(admin_token, auth_headers):
    return auth_headers(admin_token)


def _modelo(client, h, itens, tipo="OEM"):
    for cat, nome, extra in itens:
        r = client.post("/api/modelos", json={"tipo_projeto": tipo, "categoria": cat,
                                              "tipo": nome, **extra}, headers=h)
        assert r.status_code == 201, r.get_json()


def _projeto(client, h, nome="P", tipo="OEM"):
    r = client.post("/api/projetos", json={"nome": nome, "tipo": tipo}, headers=h)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["projeto"]["id"]


def _ents(client, h, pid):
    det = client.get(f"/api/projetos/{pid}", headers=h).get_json()
    return {e["tipo"]: e for c in det["categorias"] for e in c["entregaveis"]}


def _exportar(app, tmp_path):
    caminho = tmp_path / "carga.xlsx"
    cp.exportar(str(caminho))
    return caminho


def _linhas(wb, aba):
    ws = wb[aba]
    return [list(r) for r in ws.iter_rows(values_only=True)]


def _regravar(wb, aba, linhas):
    ws = wb[aba]
    ws.delete_rows(1, ws.max_row)
    for l in linhas:
        ws.append(l)


def _rodar(app, caminho, aplicar=True, motivo="Carga de teste"):
    """Na mesma sessão das requisições do teste (a fixture `app` mantém um
    app_context aberto e o client o reaproveita): uma sessão à parte deixaria
    a do client com objetos velhos no identity map."""
    from models import db
    dados = cp.ler_planilha(str(caminho))
    try:
        rel = cp.processar(dados, "admin@test.com", motivo)
    except cp.ErroCarga:
        db.session.rollback()
        raise
    if aplicar:
        db.session.commit()
    else:
        db.session.rollback()
    return rel


BASE = [("Produto", "Protótipo", {"peso": 2}),
        ("Documentação", "Manual", {}),
        ("Produto", "Lote piloto", {})]


def test_exportar_e_reler_sem_mudar_nada(app, client, h, tmp_path):
    _modelo(client, h, BASE)
    _projeto(client, h)
    caminho = _exportar(app, tmp_path)
    wb = load_workbook(caminho)
    assert {"LEIA-ME", "Modelos", "Itens do modelo", "Projetos", "Listas"} <= set(wb.sheetnames)
    rel = _rodar(app, caminho)
    assert rel.contagem == {}


def test_previa_nao_grava(app, client, h, tmp_path):
    _modelo(client, h, BASE)
    pid = _projeto(client, h)
    caminho = _exportar(app, tmp_path)
    wb = load_workbook(caminho)
    itens = _linhas(wb, "Itens do modelo")
    itens.append(["OEM", "Produto", "Item novo", 1, "", "", "", None])
    _regravar(wb, "Itens do modelo", itens)
    wb.save(caminho)
    rel = _rodar(app, caminho, aplicar=False)
    assert rel.contagem["itens de modelo criados"] == 1
    assert rel.contagem["entregáveis criados"] == 1
    assert "Item novo" not in _ents(client, h, pid)


def test_itens_editados_criados_e_excluidos_chegam_aos_projetos(app, client, h, tmp_path):
    _modelo(client, h, BASE)
    pid = _projeto(client, h)
    ents = _ents(client, h, pid)
    # Lote piloto já teve andamento: sair do modelo não pode apagá-lo
    client.put(f"/api/entregaveis/{ents['Lote piloto']['id']}",
               json={"status": "em_progresso", "percentual": 30}, headers=h)
    caminho = _exportar(app, tmp_path)
    wb = load_workbook(caminho)
    cab, *itens = _linhas(wb, "Itens do modelo")
    novos = [cab]
    for l in itens:
        if l[2] == "Protótipo":
            l[3] = 4                       # peso
        if l[2] in ("Manual", "Lote piloto"):
            continue                       # saem do modelo
        novos.append(l)
    novos.append(["OEM", "Documentação", "Manual do usuário", 1, "Qualidade", "", "", None])
    _regravar(wb, "Itens do modelo", novos)
    wb.save(caminho)

    rel = _rodar(app, caminho)
    ents = _ents(client, h, pid)
    assert ents["Protótipo"]["peso"] == 4
    assert "Manual" not in ents                         # pendente: apagado
    assert ents["Lote piloto"]["status"] == "na"        # com andamento: N/A
    assert ents["Manual do usuário"]["do_modelo"] is True
    assert rel.contagem["entregáveis que viraram N/A"] == 1
    hist = client.get("/api/modelos/propagacao/historico?tipo=OEM", headers=h).get_json()
    assert hist["mudancas"][0]["motivo"] == "Carga de teste"


def test_projeto_troca_de_modelo_e_aproveita_mesmo_nome(app, client, h, tmp_path):
    _modelo(client, h, BASE)
    pid = _projeto(client, h)
    ents = _ents(client, h, pid)
    client.put(f"/api/entregaveis/{ents['Protótipo']['id']}",
               json={"status": "concluido"}, headers=h)
    caminho = _exportar(app, tmp_path)
    wb = load_workbook(caminho)
    _regravar(wb, "Modelos", _linhas(wb, "Modelos") + [["NOVO 27", "pde"]])
    itens = _linhas(wb, "Itens do modelo")
    itens += [["NOVO 27", "Documentação", "protótipo", 3, "", "", "", None],
              ["NOVO 27", "Produto", "Validação final", 1, "", "", "", None]]
    _regravar(wb, "Itens do modelo", itens)
    cab, *projs = _linhas(wb, "Projetos")
    i_modelo = cab.index("modelo")
    for l in projs:
        if l[0] == pid:
            l[i_modelo] = "novo 27"         # maiúsculas não importam
    _regravar(wb, "Projetos", [cab] + projs)
    wb.save(caminho)

    _rodar(app, caminho)
    det = client.get(f"/api/projetos/{pid}", headers=h).get_json()
    assert det["tipo"] == "NOVO 27"
    ents = _ents(client, h, pid)
    # o Protótipo concluído casou pelo nome: ficou, com andamento, categoria e peso novos
    assert ents["protótipo"]["status"] == "concluido"
    assert ents["protótipo"]["categoria"] == "Documentação" and ents["protótipo"]["peso"] == 3
    assert ents["Validação final"]["do_modelo"] is True
    # os pendentes do modelo antigo saíram
    assert "Manual" not in ents and "Lote piloto" not in ents
    # aplicar de novo não propõe nada
    prev = client.get("/api/modelos/propagacao/previa?tipo=NOVO 27", headers=h).get_json()
    assert all(not p["mudancas"] for p in prev["projetos"])


def test_planilha_com_erro_nao_grava_nada(app, client, h, tmp_path):
    _modelo(client, h, BASE)
    _projeto(client, h)
    caminho = _exportar(app, tmp_path)
    wb = load_workbook(caminho)
    itens = _linhas(wb, "Itens do modelo")
    itens.append(["OEM", "Produto", "Válido", 1, "", "", "", None])
    itens.append(["OEM", "Inexistente", "Ruim", 1, "", "", "", None])
    itens.append(["OEM", "Produto", "Peso ruim", "abc", "", "", "", None])
    itens.append(["XYZ", "Produto", "Sem modelo", 1, "", "", "", None])
    _regravar(wb, "Itens do modelo", itens)
    wb.save(caminho)
    with pytest.raises(cp.ErroCarga) as exc:
        _rodar(app, caminho)
    texto = "\n".join(exc.value.erros)
    assert "categoria 'Inexistente'" in texto and "peso 'abc'" in texto and "'XYZ'" in texto
    nomes = [m["tipo"] for m in
             client.get("/api/modelos?tipo=OEM", headers=h).get_json()["modelos"]["OEM"]]
    assert "Válido" not in nomes


def test_projeto_arquivado_nao_troca_de_modelo(app, client, h, tmp_path):
    _modelo(client, h, BASE)
    pid = _projeto(client, h)
    client.delete(f"/api/projetos/{pid}", json={"status": "concluido"}, headers=h)
    caminho = _exportar(app, tmp_path)
    wb = load_workbook(caminho)
    _regravar(wb, "Modelos", _linhas(wb, "Modelos") + [["OUTRO", "pde"]])
    cab, *projs = _linhas(wb, "Projetos")
    for l in projs:
        if l[0] == pid:
            l[cab.index("modelo")] = "OUTRO"
            l[cab.index("nome")] = "P renomeado"
    _regravar(wb, "Projetos", [cab] + projs)
    wb.save(caminho)
    rel = _rodar(app, caminho)
    assert any("NÃO foi trocado" in a for a in rel.avisos)
    from models import Projeto, db
    p = db.session.get(Projeto, pid)
    assert p.tipo == "OEM" and p.nome == "P renomeado"


def test_aplicar_grava_auditoria(app, client, h, tmp_path):
    _modelo(client, h, BASE)
    caminho = _exportar(app, tmp_path)
    wb = load_workbook(caminho)
    _regravar(wb, "Itens do modelo",
              _linhas(wb, "Itens do modelo") + [["OEM", "Produto", "Extra", 1, "", "", "", None]])
    wb.save(caminho)
    _rodar(app, caminho)
    from models import AuditLog
    campos = {a.campo for a in AuditLog.query.filter_by(ip="planilha").all()}
    assert {"modelo_criado", "carga_planilha"} <= campos


def test_rodar_a_mesma_planilha_de_novo_nao_muda_nada(app, client, h, tmp_path):
    """Linha sem id que já foi criada casa pelo nome na segunda vez: sem isso
    os itens seriam excluídos e recriados, e os entregáveis junto."""
    _modelo(client, h, BASE)
    pid = _projeto(client, h)
    caminho = _exportar(app, tmp_path)
    wb = load_workbook(caminho)
    _regravar(wb, "Modelos", _linhas(wb, "Modelos") + [["NOVO", "pdr"]])
    _regravar(wb, "Itens do modelo", _linhas(wb, "Itens do modelo") + [
        ["NOVO", "Produto", "Protótipo", 2, "", "", "", None],
        ["NOVO", "Produto", "Estabilidade", 1, "", "", "", None]])
    cab, *projs = _linhas(wb, "Projetos")
    for l in projs:
        if l[0] == pid:
            l[cab.index("modelo")] = "NOVO"
    _regravar(wb, "Projetos", [cab] + projs)
    wb.save(caminho)
    _rodar(app, caminho)
    ids_antes = {n: e["id"] for n, e in _ents(client, h, pid).items()}
    rel = _rodar(app, caminho)
    assert rel.contagem == {}
    assert {n: e["id"] for n, e in _ents(client, h, pid).items()} == ids_antes
