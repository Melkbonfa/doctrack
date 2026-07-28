"""Arquivos hospedados na plataforma (DocumentoArquivo + arquivos_store).

Os arquivos enviados aqui são CÓPIAS de conveniência — o mestre continua no
servidor da engenharia. Um documento comporta VÁRIOS arquivos convivendo
(manual PT e ES); enviar adiciona, não substitui. Desenho de permissão que
estes testes fixam: adicionar/remover é de admin+gestor, mas ler e baixar é de
qualquer autenticado, inclusive `leitura`. Restringir download seria teatro:
quem acessa o DocTrack já acessa as pastas de rede onde está o mestre.

`DOCTRACK_ARQUIVOS` não é lido do ambiente aqui — a fixture troca
`arquivos_store.RAIZ` direto, porque o módulo lê a variável do módulo a cada
chamada justamente para permitir isso.
"""
import io
import os

import pytest

import arquivos_store
from models import db, Documento, DocumentoArquivo, AuditLog


@pytest.fixture(autouse=True)
def _raiz_temporaria(tmp_path, monkeypatch):
    """Isola os blobs deste teste numa pasta descartável."""
    monkeypatch.setattr(arquivos_store, "RAIZ", str(tmp_path / "arquivos"))
    yield


def _upload(client, token, doc_id, nome="Manual.pdf", conteudo=b"%PDF-1.4 conteudo",
            observacao=None):
    dados = {"arquivo": (io.BytesIO(conteudo), nome)}
    if observacao is not None:
        dados["observacao"] = observacao
    return client.post(
        f"/api/documentos/{doc_id}/arquivos",
        data=dados,
        content_type="multipart/form-data",
        headers={"Authorization": f"Bearer {token}"},
    )


def _um_documento(client, h):
    return client.get("/api/documentos", headers=h).get_json()[0]["id"]


# ── permissão ────────────────────────────────────────────────────────────────
def test_tecnico_nao_pode_enviar_arquivo(client, tecnico_token, admin_token, auth_headers):
    doc_id = _um_documento(client, auth_headers(admin_token))
    assert _upload(client, tecnico_token, doc_id).status_code == 403


def test_gestor_pode_enviar_arquivo(client, gestor_token, auth_headers):
    doc_id = _um_documento(client, auth_headers(gestor_token))
    res = _upload(client, gestor_token, doc_id, observacao="revisão 3")
    assert res.status_code == 201
    arq = res.get_json()["arquivo"]
    assert arq["versao"] == 1
    assert arq["nome"] == "Manual.pdf"
    assert arq["observacao"] == "revisão 3"
    assert arq["pode_visualizar"] is True
    assert res.get_json()["documento"]["tem_arquivo"] is True


def test_leitura_pode_baixar(client, admin_token, leitura_token, auth_headers):
    doc_id = _um_documento(client, auth_headers(admin_token))
    arq_id = _upload(client, admin_token, doc_id).get_json()["arquivo"]["id"]

    res = client.get(f"/api/documentos/arquivos/{arq_id}/conteudo",
                     headers={"Authorization": f"Bearer {leitura_token}"})
    assert res.status_code == 200
    assert res.data == b"%PDF-1.4 conteudo"


def test_tecnico_nao_pode_remover(client, admin_token, tecnico_token, auth_headers):
    doc_id = _um_documento(client, auth_headers(admin_token))
    arq_id = _upload(client, admin_token, doc_id).get_json()["arquivo"]["id"]

    res = client.delete(f"/api/documentos/arquivos/{arq_id}",
                        headers={"Authorization": f"Bearer {tecnico_token}"})
    assert res.status_code == 403


# ── múltiplos arquivos por documento ─────────────────────────────────────────
def test_segundo_upload_adiciona_em_vez_de_substituir(client, admin_token, auth_headers):
    """Um documento comporta vários arquivos convivendo (manual PT e ES)."""
    h = auth_headers(admin_token)
    doc_id = _um_documento(client, h)
    _upload(client, admin_token, doc_id, "Manual PT.pdf", b"portugues")
    res = _upload(client, admin_token, doc_id, "Manual ES.pdf", b"espanhol")
    assert res.status_code == 201
    assert res.get_json()["arquivo"]["versao"] == 2        # sequencial de envio

    itens = client.get(f"/api/documentos/{doc_id}/arquivos", headers=h).get_json()["arquivos"]
    assert [a["versao"] for a in itens] == [2, 1]          # mais novo primeiro
    assert all(a["ativo"] for a in itens)                  # os dois convivem

    # o documento lista os dois, na mesma ordem
    doc = client.get(f"/api/documentos/{doc_id}", headers=h).get_json()
    assert [a["nome"] for a in doc["arquivos"]] == ["Manual ES.pdf", "Manual PT.pdf"]
    assert doc["tem_arquivo"] is True

    # e ambos continuam baixáveis
    for item, esperado in [(itens[0], b"espanhol"), (itens[1], b"portugues")]:
        r = client.get(f"/api/documentos/arquivos/{item['id']}/conteudo", headers=h)
        assert r.data == esperado


# ── validação de entrada ─────────────────────────────────────────────────────
def test_extensao_fora_da_allowlist_recusada(client, admin_token, auth_headers, tmp_path):
    doc_id = _um_documento(client, auth_headers(admin_token))
    res = _upload(client, admin_token, doc_id, "virus.exe", b"MZ...")
    assert res.status_code == 415
    # e nada foi gravado no disco
    assert not os.path.isdir(arquivos_store.RAIZ) or not any(
        os.scandir(arquivos_store.RAIZ)
    )


def test_post_sem_arquivo_da_400(client, admin_token, auth_headers):
    doc_id = _um_documento(client, auth_headers(admin_token))
    res = client.post(f"/api/documentos/{doc_id}/arquivos",
                      data={}, content_type="multipart/form-data",
                      headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 400


def test_acima_do_teto_recusado(client, admin_token, auth_headers, monkeypatch):
    """O teto é checado durante a gravação, não só pelo Content-Length."""
    monkeypatch.setattr(arquivos_store, "MAX_BYTES", 10)
    doc_id = _um_documento(client, auth_headers(admin_token))
    res = _upload(client, admin_token, doc_id, "grande.pdf", b"x" * 500)
    assert res.status_code == 413


# ── dedup por conteúdo ───────────────────────────────────────────────────────
def test_mesmo_conteudo_em_dois_documentos_usa_um_blob_so(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    docs = client.get("/api/documentos", headers=h).get_json()
    d1, d2 = docs[0]["id"], docs[1]["id"]
    conteudo = b"conteudo identico nos dois"

    a1 = _upload(client, admin_token, d1, "Copia A.pdf", conteudo).get_json()["arquivo"]
    a2 = _upload(client, admin_token, d2, "Copia B.pdf", conteudo).get_json()["arquivo"]

    linhas = DocumentoArquivo.query.filter(
        DocumentoArquivo.id.in_([a1["id"], a2["id"]])).all()
    shas = {l.sha256 for l in linhas}
    assert len(shas) == 1                                  # mesmo blob
    assert os.path.isfile(arquivos_store.caminho_de(shas.pop()))

    # apagar um NÃO pode deixar o outro sem arquivo
    assert client.delete(f"/api/documentos/arquivos/{a1['id']}", headers=h).status_code == 200
    res = client.get(f"/api/documentos/arquivos/{a2['id']}/conteudo", headers=h)
    assert res.status_code == 200
    assert res.data == conteudo


def test_remover_ultima_referencia_apaga_o_blob(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    doc_id = _um_documento(client, h)
    arq = _upload(client, admin_token, doc_id).get_json()["arquivo"]
    sha = DocumentoArquivo.query.get(arq["id"]).sha256
    assert os.path.isfile(arquivos_store.caminho_de(sha))

    res = client.delete(f"/api/documentos/arquivos/{arq['id']}", headers=h)
    assert res.status_code == 200
    assert res.get_json()["documento"]["tem_arquivo"] is False
    assert not os.path.isfile(arquivos_store.caminho_de(sha))


# ── auditoria ────────────────────────────────────────────────────────────────
def test_upload_registra_auditoria(client, admin_token, auth_headers):
    doc_id = _um_documento(client, auth_headers(admin_token))
    _upload(client, admin_token, doc_id, "Manual.pdf")

    log = (AuditLog.query.filter_by(acao="UPLOAD", documento_id=doc_id)
           .order_by(AuditLog.id.desc()).first())
    assert log is not None
    assert log.campo == "arquivo"
    assert log.valor_novo == "Manual.pdf"
    assert log.usuario_email == "admin@test.com"


# ── o módulo de armazenamento, isolado ───────────────────────────────────────
def test_store_grava_por_hash_e_nao_deixa_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(arquivos_store, "RAIZ", str(tmp_path))
    sha, tam = arquivos_store.guardar(io.BytesIO(b"abc"), "x.pdf")
    assert tam == 3
    # SHA-256 de "abc"
    assert sha == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert os.path.isfile(arquivos_store.caminho_de(sha))
    # o nome em disco é o hash, distribuído em 2 níveis
    assert arquivos_store.caminho_de(sha).endswith(os.path.join("ba", "78", sha))
    assert not os.listdir(os.path.join(str(tmp_path), "_tmp"))


def test_store_descarta_parcial_quando_estoura(tmp_path, monkeypatch):
    monkeypatch.setattr(arquivos_store, "RAIZ", str(tmp_path))
    monkeypatch.setattr(arquivos_store, "MAX_BYTES", 4)
    with pytest.raises(arquivos_store.ArquivoGrandeDemais):
        arquivos_store.guardar(io.BytesIO(b"x" * 100), "x.pdf")
    # nenhum blob truncado ficou para trás com nome válido
    assert not os.listdir(os.path.join(str(tmp_path), "_tmp"))
