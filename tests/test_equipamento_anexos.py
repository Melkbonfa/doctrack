"""Anexos do EQUIPAMENTO: docs agregados e repositório de software/firmware.

Diferente do `DocumentoArquivo`, estes arquivos penduram no equipamento e não em
um dos 12 tipos de documento — logo, ficam fora da completude. O que estes testes
fixam:

  * **Allowlist por categoria.** 'agregado' aceita o mesmo que um documento
    (PDF/Office/imagem); só 'software' e 'firmware' aceitam binário. Se um dia
    alguém unificar as duas listas, o teste do 415 quebra — e deve quebrar: seria
    abrir o campo "Arquivos" de qualquer IT para executável.
  * **Binário nunca abre inline.** Content-Disposition de anexo e mime genérico:
    o navegador não interpreta o conteúdo, ele desce para o disco.
  * **A ordem é a data de LIBERAÇÃO, não a do upload.** Cadastrar hoje a versão
    do ano passado não pode colocá-la no topo do repositório.
  * **O blob é compartilhado com `documento_arquivos`.** Remover de um lado não
    pode apagar o conteúdo que o outro ainda exibe.

Como em test_documento_arquivos, a raiz dos blobs é trocada por uma pasta
descartável (o módulo relê `arquivos_store.RAIZ` a cada chamada de propósito).
"""
import io

import pytest

import arquivos_store
from models import db, Equipamento, EquipamentoArquivo


@pytest.fixture(autouse=True)
def _raiz_temporaria(tmp_path, monkeypatch):
    monkeypatch.setattr(arquivos_store, "RAIZ", str(tmp_path / "arquivos"))
    yield


@pytest.fixture
def equip_id(app):
    """Um equipamento em que pendurar os anexos (o seed só tem documentos)."""
    e = Equipamento(nome="Extracta 16", sku="SKU-EX16", ativo=True)
    db.session.add(e)
    db.session.commit()
    return e.id


def _envia(client, token, equip_id, nome="Laudo.pdf", conteudo=b"%PDF-1.4 x",
           categoria="agregado", **campos):
    dados = {"arquivo": (io.BytesIO(conteudo), nome), "categoria": categoria}
    dados.update({k: v for k, v in campos.items() if v is not None})
    return client.post(
        f"/api/equipamentos/{equip_id}/anexos",
        data=dados,
        content_type="multipart/form-data",
        headers={"Authorization": f"Bearer {token}"},
    )


def _lista(client, token, equip_id, categoria=None):
    url = f"/api/equipamentos/{equip_id}/anexos"
    if categoria:
        url += f"?categoria={categoria}"
    res = client.get(url, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.get_json()
    return res.get_json()["anexos"]


# ── permissão ────────────────────────────────────────────────────────────────
def test_tecnico_nao_pode_enviar_anexo(client, tecnico_token, equip_id):
    assert _envia(client, tecnico_token, equip_id).status_code == 403


def test_tecnico_nao_pode_remover_anexo(client, admin_token, tecnico_token, equip_id):
    aid = _envia(client, admin_token, equip_id).get_json()["anexo"]["id"]
    res = client.delete(f"/api/equipamentos/anexos/{aid}",
                        headers={"Authorization": f"Bearer {tecnico_token}"})
    assert res.status_code == 403


def test_leitura_pode_listar_e_baixar(client, admin_token, leitura_token, equip_id):
    """Travar o download seria teatro — mesma decisão do DocumentoArquivo."""
    aid = _envia(client, admin_token, equip_id).get_json()["anexo"]["id"]
    assert len(_lista(client, leitura_token, equip_id)) == 1

    res = client.get(f"/api/equipamentos/anexos/{aid}/conteudo",
                     headers={"Authorization": f"Bearer {leitura_token}"})
    assert res.status_code == 200
    assert res.data == b"%PDF-1.4 x"


# ── docs agregados ───────────────────────────────────────────────────────────
def test_gestor_envia_doc_agregado(client, gestor_token, equip_id):
    res = _envia(client, gestor_token, equip_id, "Laudo EMC.pdf",
                 titulo="Laudo de compatibilidade", notas="Emitido pelo INMETRO")
    assert res.status_code == 201
    a = res.get_json()["anexo"]
    assert a["categoria"] == "agregado"
    assert a["titulo"] == "Laudo de compatibilidade"
    assert a["notas"] == "Emitido pelo INMETRO"
    assert a["pode_visualizar"] is True
    # Campos de versão não existem fora do repositório: preenchê-los seria
    # inventar um versionamento que a categoria não tem.
    assert a["versao_rotulo"] == "" and a["data_release"] == ""


def test_titulo_vazio_cai_no_nome_do_arquivo(client, admin_token, equip_id):
    a = _envia(client, admin_token, equip_id, "Datasheet.pdf").get_json()["anexo"]
    assert a["titulo"] == "Datasheet.pdf"


def test_agregado_recusa_binario(client, admin_token, equip_id):
    """A porta larga é só do repositório de software/firmware."""
    res = _envia(client, admin_token, equip_id, "instalador.exe", b"MZ...",
                 categoria="agregado")
    assert res.status_code == 415
    assert "exe" not in res.get_json()["erro"]


def test_categoria_invalida(client, admin_token, equip_id):
    assert _envia(client, admin_token, equip_id, categoria="qualquer").status_code == 400


# ── repositório de software / firmware ───────────────────────────────────────
def test_software_aceita_binario(client, admin_token, equip_id):
    res = _envia(client, admin_token, equip_id, "Setup-2.4.1.zip", b"PK\x03\x04dados",
                 categoria="software", titulo="Software de aquisição",
                 versao_rotulo="v2.4.1", data_release="2026-05-10",
                 notas="Corrige o export de CSV")
    assert res.status_code == 201
    a = res.get_json()["anexo"]
    assert a["categoria"] == "software"
    assert a["versao_rotulo"] == "v2.4.1"
    assert a["data_release"] == "2026-05-10"
    # Binário não é visualizável: não há visor para .zip, e oferecer o botão
    # levaria a um iframe vazio.
    assert a["pode_visualizar"] is False


def test_firmware_binario_desce_como_anexo(client, admin_token, leitura_token, equip_id):
    """Mime genérico + attachment: o navegador não tem como interpretar o conteúdo."""
    aid = _envia(client, admin_token, equip_id, "fw-3.02.bin", b"\x00\x01\x02\x03",
                 categoria="firmware", versao_rotulo="FW 3.02").get_json()["anexo"]["id"]

    res = client.get(f"/api/equipamentos/anexos/{aid}/conteudo",
                     headers={"Authorization": f"Bearer {leitura_token}"})
    assert res.status_code == 200
    assert res.data == b"\x00\x01\x02\x03"
    assert res.mimetype == "application/octet-stream"
    assert "attachment" in res.headers.get("Content-Disposition", "")


def test_ordem_e_pela_data_de_liberacao(client, admin_token, equip_id):
    """Cadastrar depois não é ser mais novo: quem manda é a data do fabricante."""
    _envia(client, admin_token, equip_id, "nova.zip", b"nova", categoria="software",
           versao_rotulo="v3.0", data_release="2026-06-01")
    _envia(client, admin_token, equip_id, "antiga.zip", b"antiga", categoria="software",
           versao_rotulo="v1.0", data_release="2025-01-15")
    # sem data de liberação: cai para o fim da lista, não para o topo
    _envia(client, admin_token, equip_id, "sem-data.zip", b"sem", categoria="software",
           versao_rotulo="v2.0")

    itens = _lista(client, admin_token, equip_id, "software")
    assert [a["versao_rotulo"] for a in itens] == ["v3.0", "v1.0", "v2.0"]


def test_tetos_de_tamanho_sao_por_categoria(client, admin_token, equip_id, monkeypatch):
    """O binário tem teto próprio; o agregado continua preso ao teto de documento.

    Os limites são reduzidos aqui para não trafegar 80 MB no teste. O que importa
    é que a rota escolhe o teto pela categoria — se um dia passar a usar um teto
    só, o primeiro caso deixa de dar 413.
    """
    monkeypatch.setattr(arquivos_store, "MAX_BYTES", 1000)
    monkeypatch.setattr(arquivos_store, "MAX_BIN_BYTES", 50_000)
    grande = b"x" * 5000

    res = _envia(client, admin_token, equip_id, "Laudo.pdf", grande, categoria="agregado")
    assert res.status_code == 413

    res = _envia(client, admin_token, equip_id, "sw.zip", grande, categoria="software")
    assert res.status_code == 201


def test_data_de_liberacao_invalida(client, admin_token, equip_id):
    res = _envia(client, admin_token, equip_id, "x.zip", b"x", categoria="software",
                 data_release="10/05/2026")
    assert res.status_code == 400


def test_filtro_por_categoria_separa_as_duas_abas(client, admin_token, equip_id):
    _envia(client, admin_token, equip_id, "Laudo.pdf", categoria="agregado")
    _envia(client, admin_token, equip_id, "sw.zip", b"sw", categoria="software")
    _envia(client, admin_token, equip_id, "fw.bin", b"fw", categoria="firmware")

    assert len(_lista(client, admin_token, equip_id)) == 3
    assert len(_lista(client, admin_token, equip_id, "agregado")) == 1
    assert len(_lista(client, admin_token, equip_id, "firmware")) == 1


# ── correção de metadados ────────────────────────────────────────────────────
def test_patch_corrige_versao_sem_reenviar(client, admin_token, auth_headers, equip_id):
    aid = _envia(client, admin_token, equip_id, "sw.zip", b"sw", categoria="software",
                 versao_rotulo="v2.41").get_json()["anexo"]["id"]

    res = client.patch(f"/api/equipamentos/anexos/{aid}",
                       json={"versao_rotulo": "v2.4.1", "notas": "corrigido"},
                       headers=auth_headers(admin_token))
    assert res.status_code == 200
    a = res.get_json()["anexo"]
    assert a["versao_rotulo"] == "v2.4.1" and a["notas"] == "corrigido"
    assert a["nome"] == "sw.zip"          # o binário não foi tocado


def test_patch_nao_inventa_versao_em_doc_agregado(client, admin_token, auth_headers, equip_id):
    aid = _envia(client, admin_token, equip_id, "Laudo.pdf").get_json()["anexo"]["id"]
    res = client.patch(f"/api/equipamentos/anexos/{aid}",
                       json={"versao_rotulo": "v9", "data_release": "2026-01-01"},
                       headers=auth_headers(admin_token))
    assert res.status_code == 200
    assert res.get_json()["anexo"]["versao_rotulo"] == ""
    assert res.get_json()["anexo"]["data_release"] == ""


# ── remoção ──────────────────────────────────────────────────────────────────
def test_remover_apaga_o_blob_e_some_da_lista(client, admin_token, equip_id):
    a = _envia(client, admin_token, equip_id).get_json()["anexo"]
    sha = db.session.get(EquipamentoArquivo, a["id"]).sha256
    assert arquivos_store.existe(sha)

    res = client.delete(f"/api/equipamentos/anexos/{a['id']}",
                        headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    assert _lista(client, admin_token, equip_id) == []
    assert not arquivos_store.existe(sha)
    # a linha sobrevive para a trilha; o conteúdo, não
    assert db.session.get(EquipamentoArquivo, a["id"]).ativo is False


def test_remover_duas_vezes(client, admin_token, equip_id):
    aid = _envia(client, admin_token, equip_id).get_json()["anexo"]["id"]
    h = {"Authorization": f"Bearer {admin_token}"}
    assert client.delete(f"/api/equipamentos/anexos/{aid}", headers=h).status_code == 200
    assert client.delete(f"/api/equipamentos/anexos/{aid}", headers=h).status_code == 404


def test_blob_compartilhado_com_documento_sobrevive(client, admin_token, auth_headers, equip_id):
    """O mesmo PDF nos dois lugares ocupa UM blob (dedup por conteúdo).

    Sem consultar as duas tabelas antes de apagar, remover o anexo do equipamento
    deixaria o arquivo do documento apontando para o vazio.
    """
    h = auth_headers(admin_token)
    conteudo = b"%PDF-1.4 identico"
    doc_id = client.get("/api/documentos", headers=h).get_json()[0]["id"]

    arq = client.post(
        f"/api/documentos/{doc_id}/arquivos",
        data={"arquivo": (io.BytesIO(conteudo), "Manual.pdf")},
        content_type="multipart/form-data",
        headers={"Authorization": f"Bearer {admin_token}"},
    ).get_json()["arquivo"]

    anexo = _envia(client, admin_token, equip_id, "Manual.pdf", conteudo).get_json()["anexo"]
    sha = db.session.get(EquipamentoArquivo, anexo["id"]).sha256

    client.delete(f"/api/equipamentos/anexos/{anexo['id']}",
                  headers={"Authorization": f"Bearer {admin_token}"})

    assert arquivos_store.existe(sha)     # o documento ainda aponta para ele
    res = client.get(f"/api/documentos/arquivos/{arq['id']}/conteudo", headers=h)
    assert res.status_code == 200 and res.data == conteudo


def test_equipamento_inexistente(client, admin_token):
    assert _envia(client, admin_token, 99999).status_code == 404
    res = client.get("/api/equipamentos/99999/anexos",
                     headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 404
