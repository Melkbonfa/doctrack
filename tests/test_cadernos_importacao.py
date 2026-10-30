"""Cadernos: importação do OneNote pela tela, e o assistente que gera o pacote.

Pacote SINTÉTICO, com a forma do que o extrator gera (nenhum dado real aqui).
O que estes testes fixam:

  * **O caminho da tela**: enviar o .zip → resumo → confirmar → caderno gravado,
    com a página, a imagem, o arquivo inserido na página do OneNote como anexo no
    texto e os .one originais guardados fora da exportação.
  * **Reimportar** atualiza a página que ninguém editou e pula a editada.
  * **O zip é validado** antes de qualquer gravação (caminho fora da pasta,
    arquivo que não é zip, pacote sem manifesto).
  * **O assistente** é um .cmd só, com o extrator dentro, e não usa
    Invoke-Expression (padrão que antivírus bloqueia).
  * **O assistente manda sozinho**: o .cmd baixado com ticket conta a etapa e
    envia o pacote sem login; a tela acompanha e recebe o resumo. O ticket é de
    uso único, só quem o criou o vê, e o que vai dentro do .cmd é validado.
"""
import base64
import io
import json
import re
import zipfile

import pytest
from PIL import Image

import arquivos_store
from models import db, AuditLog, User
from cadernos import importacao
from cadernos.models import Caderno, CadernoArquivo, CadernoPagina

NS = 'xmlns:one="http://schemas.microsoft.com/office/onenote/2013/onenote"'
CACHE = r"C:\Users\x\AppData\Local\Microsoft\OneNote\16.0\cache\00001A.bin"


@pytest.fixture(autouse=True)
def _pastas_temporarias(tmp_path, monkeypatch):
    monkeypatch.setattr(arquivos_store, "RAIZ", str(tmp_path / "arquivos"))
    monkeypatch.setattr(importacao, "PASTA_TEMP", str(tmp_path / "importacoes"))
    monkeypatch.setattr(importacao, "_tickets", {})
    yield


@pytest.fixture
def area_pdr(app):
    for email in ("gestor@test.com", "tecnico@test.com", "leitura@test.com"):
        User.query.filter_by(email=email).first().areas = "pdr"
    db.session.commit()


def H(token):
    return {"Authorization": f"Bearer {token}"}


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (30, 10), (0, 120, 0)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _pagina_xml(titulo, texto, anexo=True):
    arq = (f'<one:OE><one:InsertedFile pathCache="{CACHE}" pathSource="C:\\dados\\placa_0912.xlsx" '
           f'preferredName="placa_0912.xlsx"/></one:OE>') if anexo else ""
    return (f'<?xml version="1.0"?><one:Page {NS} name="{titulo}" dateTime="2026-01-07T12:00:00.000Z" '
            f'lastModifiedTime="2026-03-24T12:00:00.000Z" pageLevel="1"><one:Outline><one:OEChildren>'
            f'<one:OE author="Fulana [Loccus]" creationTime="2026-01-07T12:00:00.000Z">'
            f'<one:T><![CDATA[{texto}]]></one:T></one:OE>'
            f'<one:OE><one:Image><one:Size width="30" height="10"/><one:Data>{_png()}</one:Data></one:Image></one:OE>'
            f'{arq}</one:OEChildren></one:Outline></one:Page>')


def _pacote(*, texto="Curva padrão", com_anexo_no_pacote=True, extra=None, raiz=""):
    man = {
        "formato": "doctrack-onenote-1", "extraido_em": "2026-10-05T10:00:00", "maquina": "PC-TESTE",
        "caderno": {"nome": "Projeto L-999", "cor": "#B79CAB", "caminho": "C:\\Users\\x\\Desktop\\Projeto L-999"},
        "secoes": [{"indice": 1, "nome": "Desenvolvimento", "cor": "#8AA8E4", "grupos": []}],
        "paginas": [{"n": 1, "arquivo": "0001.xml", "secao": 1, "nome": "Teste 1", "nivel": 1,
                     "data": "2026-01-07T12:00:00.000Z", "recolhida": False, "imagens": 1, "tinta": 0,
                     "pdf": None,
                     "anexos": [{"arquivo": "0001_01.xlsx", "nome": "placa_0912.xlsx", "cache": CACHE}]}],
        "contagens": {"paginas": 1, "imagens": 1, "anexos": 1, "anexos_copiados": 1, "tinta": 0, "originais": 1},
        "avisos": [],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(raiz + "manifesto.json", json.dumps(man))
        zf.writestr(raiz + "paginas/0001.xml", _pagina_xml("Teste 1", texto))
        if com_anexo_no_pacote:
            zf.writestr(raiz + "anexos/0001_01.xlsx", b"PK planilha da placa")
        zf.writestr(raiz + "originais_onenote/Desenvolvimento.one", b"onenote binario")
        for nome, dados in (extra or {}).items():
            zf.writestr(nome, dados)
    buf.seek(0)
    return buf


def _enviar(client, token, buf, nome="Projeto L-999 (DocTrack).zip"):
    return client.post("/cadernos/api/importacoes", data={"area": "pdr", "pacote": (buf, nome)},
                       content_type="multipart/form-data", headers=H(token))


def _importar(client, token, buf, nome=None):
    res = _enviar(client, token, buf)
    assert res.status_code == 201, res.get_json()
    r = res.get_json()
    ini = client.post(f"/cadernos/api/importacoes/{r['id']}/iniciar", json={"nome": nome or ""}, headers=H(token))
    assert ini.status_code == 202, ini.get_json()
    t = ini.get_json()["tarefa"]
    assert t["estado"] == "pronta", t
    return r, t["resultado"]["relatorio"]


def test_importacao_pela_tela_grava_o_caderno_completo(client, tecnico_token, area_pdr):
    res = _enviar(client, tecnico_token, _pacote())
    assert res.status_code == 201, res.get_json()
    r = res.get_json()
    assert r["existente"] is None
    assert (r["resumo"]["caderno"], r["resumo"]["paginas"], r["resumo"]["anexos"]) == ("Projeto L-999", 1, 1)

    ini = client.post(f"/cadernos/api/importacoes/{r['id']}/iniciar", json={"nome": "L-999 no DocTrack"},
                      headers=H(tecnico_token))
    rel = ini.get_json()["tarefa"]["resultado"]["relatorio"]
    assert rel["criadas"] == 1 and rel["contagens"]["anexos_importados"] == 1
    assert rel["contagens"]["originais_onenote"] == 1

    cad = Caderno.query.filter_by(uuid=rel["caderno"]["uuid"]).first()
    assert cad.nome == "L-999 no DocTrack" and cad.area == "pdr"
    assert cad.dono_id == User.query.filter_by(email="tecnico@test.com").first().id
    p = CadernoPagina.query.filter_by(caderno_id=cad.id).one()
    anexo = CadernoArquivo.query.filter_by(escopo="pagina", escopo_id=p.id, embutido=False).one()
    # O arquivo inserido na página do OneNote vira anexo NO TEXTO, no mesmo lugar.
    assert f'<a data-arquivo="{anexo.uuid}">placa_0912.xlsx</a>' in p.conteudo_html
    assert anexo.incluir_exportacao and anexo.origem == "onenote"
    with open(arquivos_store.caminho_de(anexo.sha256), "rb") as fh:
        assert fh.read() == b"PK planilha da placa"
    assert CadernoArquivo.query.filter_by(escopo="pagina", escopo_id=p.id, embutido=True).count() == 1
    orig = CadernoArquivo.query.filter_by(escopo="caderno", caderno_id=cad.id).one()
    assert (orig.pasta, orig.nome_original, orig.incluir_exportacao) == ("OneNote original", "Desenvolvimento.one", False)
    # A pasta temporária do pacote foi limpa.
    assert importacao.recebido(r["id"], cad.dono_id) is None


def test_anexo_que_nao_veio_no_pacote_vira_aviso(client, tecnico_token, area_pdr):
    _, rel = _importar(client, tecnico_token, _pacote(com_anexo_no_pacote=False))
    p = CadernoPagina.query.filter_by(titulo="Teste 1").one()
    assert "data-arquivo=" not in p.conteudo_html.replace('<img data-arquivo=', "")
    assert "placa_0912.xlsx" in p.conteudo_html and "não veio no pacote" in p.conteudo_html
    assert rel["contagens"]["anexos_faltando"] == 1
    assert any("placa_0912.xlsx" in a for a in rel["avisos"])


def test_reimportar_atualiza_o_que_ninguem_editou(client, tecnico_token, area_pdr):
    _, rel = _importar(client, tecnico_token, _pacote(texto="primeira"))
    r2 = _enviar(client, tecnico_token, _pacote(texto="segunda")).get_json()
    assert r2["existente"]["uuid"] == rel["caderno"]["uuid"] and r2["existente"]["pode_atualizar"]
    t = client.post(f"/cadernos/api/importacoes/{r2['id']}/iniciar", json={}, headers=H(tecnico_token)).get_json()["tarefa"]
    assert t["resultado"]["relatorio"]["atualizadas"] == 1
    p = CadernoPagina.query.filter_by(titulo="Teste 1").one()
    assert "segunda" in p.conteudo_html
    # Sem duplicar imagem nem anexo.
    assert CadernoArquivo.query.filter_by(escopo="pagina", escopo_id=p.id).count() == 2
    assert Caderno.query.count() == 1

    # Editada no DocTrack: a próxima reimportação pula.
    p.versao = 2
    db.session.commit()
    _, rel3 = _importar(client, tecnico_token, _pacote(texto="terceira"))
    assert rel3["puladas_editadas_no_doctrack"] == ["Teste 1"]
    assert "segunda" in CadernoPagina.query.filter_by(titulo="Teste 1").one().conteudo_html


def test_pacote_maior_que_o_limite_global_de_upload_entra(client, tecnico_token, area_pdr, app):
    """O pacote de um caderno passa fácil dos 80 MB do upload comum (o L-037 tem
    96 MB): a rota sobe o limite ANTES de ler o formulário."""
    antes = app.config["MAX_CONTENT_LENGTH"]
    app.config["MAX_CONTENT_LENGTH"] = 1024             # 1 KB global, só neste teste
    try:
        assert _enviar(client, tecnico_token, _pacote()).status_code == 201
    finally:
        app.config["MAX_CONTENT_LENGTH"] = antes


def test_pacote_dentro_de_uma_pasta_tambem_vale(client, tecnico_token, area_pdr):
    res = _enviar(client, tecnico_token, _pacote(raiz="Projeto L-999 2026-10-05/"))
    assert res.status_code == 201, res.get_json()


@pytest.mark.parametrize("conteudo,trecho", [
    (b"isto nao e um zip", "não é um .zip"),
    (None, "manifesto.json"),
])
def test_zip_invalido_e_recusado(client, tecnico_token, area_pdr, conteudo, trecho):
    if conteudo is None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("qualquer.txt", "x")
        buf.seek(0)
    else:
        buf = io.BytesIO(conteudo)
    res = _enviar(client, tecnico_token, buf)
    assert res.status_code == 400 and trecho in res.get_json()["erro"]


def test_zip_com_caminho_fora_da_pasta_e_recusado(client, tecnico_token, area_pdr, tmp_path):
    res = _enviar(client, tecnico_token, _pacote(extra={"../../fora.txt": b"x"}))
    assert res.status_code == 400 and "Caminho inválido" in res.get_json()["erro"]
    assert not (tmp_path / "fora.txt").exists()


def test_leitura_nao_importa(client, leitura_token, area_pdr):
    assert _enviar(client, leitura_token, _pacote()).status_code == 403
    assert client.get("/cadernos/api/onenote/assistente", headers=H(leitura_token)).status_code == 403


def test_pacote_recebido_e_so_de_quem_enviou(client, tecnico_token, gestor_token, area_pdr):
    r = _enviar(client, tecnico_token, _pacote()).get_json()
    assert client.post(f"/cadernos/api/importacoes/{r['id']}/iniciar", json={},
                       headers=H(gestor_token)).status_code == 404


def test_assistente_e_um_cmd_so_com_o_extrator_dentro(client, tecnico_token):
    res = client.get(f"/cadernos/api/onenote/assistente?token={tecnico_token}")
    assert res.status_code == 200
    assert res.headers["Content-Disposition"].startswith("attachment")
    dados = res.data
    assert dados.startswith(b"<# :\r\n@echo off\r\n")          # sem BOM: o cmd lê a 1ª linha
    texto = dados.decode("utf-8")
    assert "\n" not in texto.replace("\r\n", "")                 # CRLF em todas as linhas
    assert "function Extrair-OneNote {" in texto and "GetPageContent" in texto
    assert "Cadernos-Abertos" in texto                           # o menu do assistente
    assert "iex " not in texto and "Invoke-Expression" not in texto
    assert texto.index("#>") < texto.index("function Extrair-OneNote")


# ══════════════════════════════════════════════════════════════════════════════
# O ASSISTENTE MANDA SOZINHO (ticket)
# ══════════════════════════════════════════════════════════════════════════════

def _ticket(client, token):
    res = client.post("/cadernos/api/importacoes/tickets", json={"area": "pdr"}, headers=H(token))
    assert res.status_code == 201, res.get_json()
    return res.get_json()["id"]


def _cmd_com_ticket(client, token, id_):
    res = client.get(f"/cadernos/api/onenote/assistente?ticket={id_}&token={token}")
    assert res.status_code == 200, res.get_json()
    return res.data.decode("utf-8")


def _segredo(texto):
    return re.search(r"^\$DT_TICKET = '([^']+)'\r$", texto, re.M).group(1)


def _estado(client, token, id_):
    return client.get(f"/cadernos/api/importacoes/tickets/{id_}", headers=H(token))


def _aviso(client, segredo, **dados):
    return client.post("/cadernos/api/importacoes/assistente/aviso", json=dados,
                       headers={"X-DocTrack-Ticket": segredo})


def _pacote_do_assistente(client, segredo, buf):
    return client.post("/cadernos/api/importacoes/assistente/pacote", data=buf.getvalue(),
                       content_type="application/zip", headers={"X-DocTrack-Ticket": segredo})


def test_assistente_com_ticket_manda_o_pacote_e_a_tela_acompanha(client, tecnico_token, area_pdr):
    id_ = _ticket(client, tecnico_token)
    texto = _cmd_com_ticket(client, tecnico_token, id_)
    assert "$DT_SERVIDOR = 'http://localhost'\r\n" in texto
    segredo = _segredo(texto)
    assert segredo not in id_
    assert texto.index("$DT_TICKET") < texto.index("function Extrair-OneNote")

    assert _estado(client, tecnico_token, id_).get_json()["estado"] == "aguardando"

    assert _aviso(client, segredo, etapa="Extraindo a página 3 de 96: Teste 1", feito=3, total=96).status_code == 200
    e = _estado(client, tecnico_token, id_).get_json()
    assert (e["estado"], e["etapa"], e["feito"], e["total"]) == ("trabalhando", "Extraindo a página 3 de 96: Teste 1", 3, 96)
    assert "segredo" not in json.dumps(e) and segredo not in json.dumps(e)

    res = _pacote_do_assistente(client, segredo, _pacote())
    assert res.status_code == 201, res.get_json()
    assert res.get_json()["caderno"] == "Projeto L-999"

    e = _estado(client, tecnico_token, id_).get_json()
    assert e["estado"] == "recebido"
    assert e["pacote"]["resumo"]["caderno"] == "Projeto L-999" and e["pacote"]["existente"] is None

    # A conferência é a mesma do envio à mão: confirmar grava o caderno.
    ini = client.post(f"/cadernos/api/importacoes/{e['pacote']['id']}/iniciar", json={}, headers=H(tecnico_token))
    assert ini.status_code == 202 and ini.get_json()["tarefa"]["estado"] == "pronta"
    assert Caderno.query.filter_by(nome="Projeto L-999").count() == 1


def test_ticket_e_de_uso_unico_e_so_de_quem_criou(client, tecnico_token, gestor_token, area_pdr):
    id_ = _ticket(client, tecnico_token)
    segredo = _segredo(_cmd_com_ticket(client, tecnico_token, id_))

    assert _estado(client, gestor_token, id_).status_code == 404
    assert client.get(f"/cadernos/api/onenote/assistente?ticket={id_}&token={gestor_token}").status_code == 404

    errado = _aviso(client, "nao-e-o-segredo", etapa="x")
    assert errado.status_code == 404 and "expirou" in errado.get_json()["erro"]
    assert _aviso(client, "", etapa="x").status_code == 404

    assert _pacote_do_assistente(client, segredo, _pacote()).status_code == 201
    de_novo = _pacote_do_assistente(client, segredo, _pacote())
    assert de_novo.status_code == 404 and "já enviou" in de_novo.get_json()["erro"]
    assert _aviso(client, segredo, etapa="x").status_code == 404


def test_assistente_que_para_aparece_na_tela_e_pode_rodar_de_novo(client, tecnico_token, area_pdr):
    id_ = _ticket(client, tecnico_token)
    segredo = _segredo(_cmd_com_ticket(client, tecnico_token, id_))

    _aviso(client, segredo, erro="O assistente foi fechado sem exportar.")
    e = _estado(client, tecnico_token, id_).get_json()
    assert (e["estado"], e["erro"]) == ("erro", "O assistente foi fechado sem exportar.")

    # Pacote ruim: a tela vê o motivo, e o mesmo .cmd ainda serve.
    ruim = _pacote_do_assistente(client, segredo, io.BytesIO(b"isto nao e um zip"))
    assert ruim.status_code == 400
    e = _estado(client, tecnico_token, id_).get_json()
    assert e["estado"] == "erro" and "não é um .zip" in e["erro"]

    _aviso(client, segredo, etapa="Abrindo a cópia baixada no OneNote")
    assert _estado(client, tecnico_token, id_).get_json()["estado"] == "trabalhando"
    assert _pacote_do_assistente(client, segredo, _pacote()).status_code == 201


def test_ticket_expira(client, tecnico_token, area_pdr, monkeypatch):
    id_ = _ticket(client, tecnico_token)
    segredo = _segredo(_cmd_com_ticket(client, tecnico_token, id_))
    monkeypatch.setattr(importacao, "VALIDADE_TICKET_HORAS", -1)
    assert _estado(client, tecnico_token, id_).status_code == 404
    assert _pacote_do_assistente(client, segredo, _pacote()).status_code == 404


def test_leitura_nao_cria_ticket(client, leitura_token, area_pdr):
    res = client.post("/cadernos/api/importacoes/tickets", json={"area": "pdr"}, headers=H(leitura_token))
    assert res.status_code == 403
    # Como nas outras rotas da importação, a negação vai para a trilha (R-06).
    assert AuditLog.query.filter_by(acao="ACESSO_NEGADO").count() == 1


def test_assistente_sem_ticket_nao_manda_nada(client, tecnico_token):
    texto = client.get(f"/cadernos/api/onenote/assistente?token={tecnico_token}").data.decode("utf-8")
    assert "$DT_TICKET =" not in texto and "$DT_SERVIDOR =" not in texto


def test_endereco_estranho_nao_vira_codigo_no_assistente(client, tecnico_token, area_pdr):
    """O endereço vem do Host do navegador e vai entre aspas no PowerShell: o
    que não parece endereço deixa o assistente sem envio (fica o caminho à mão)."""
    id_ = _ticket(client, tecnico_token)
    res = client.get(f"/cadernos/api/onenote/assistente?ticket={id_}&token={tecnico_token}",
                     headers={"Host": "x';Remove-Item C: -Recurse;'"})
    texto = res.data.decode("utf-8")
    assert res.status_code == 200
    assert "$DT_TICKET =" not in texto and "Remove-Item C:" not in texto
