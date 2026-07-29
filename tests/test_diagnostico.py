"""Diagnóstico: cadastro × arquivos que existem de fato.

Testa o módulo puro (`diagnostico.diagnosticar`), sem banco e sem Flask: o que
importa aqui é o confronto com o filesystem, e cada caso precisa de um estado de
disco montado à mão. O contrato da rota fica em test_documentos_evolucao.py.

Regra que organiza tudo: um documento tem DUAS fontes de arquivo — a pasta de
rede e a cópia hospedada na plataforma — e ter uma das duas basta.
"""
import os

import pytest

import arquivos_store
import diagnostico


@pytest.fixture(autouse=True)
def _raiz_temporaria(tmp_path, monkeypatch):
    """Isola os blobs: sem isto o teste consultaria a pasta real de arquivos."""
    monkeypatch.setattr(arquivos_store, "RAIZ", str(tmp_path / "blobs"))


def _doc(id=1, caminho="", arquivos=(), concluido=False, equipamento="MAQ-1",
         tipo="Manual do usuário"):
    return {"id": id, "equipamento": equipamento, "documento": f"DOC-{id}",
            "tipo_doc_label": tipo, "setor": "PRE", "status": "Elaborar",
            "concluido": concluido, "caminho": caminho, "arquivos": list(arquivos)}


def _blob(tmp_path, conteudo=b"conteudo"):
    """Grava um blob de verdade e devolve o sha (o nome em disco é o hash)."""
    import io
    sha, _ = arquivos_store.guardar(io.BytesIO(conteudo), "Manual.pdf")
    return sha


def _tipos(rel):
    return {i["tipo"] for i in rel["issues"]}


# ── as duas fontes ───────────────────────────────────────────────────────────
def test_arquivo_hospedado_dispensa_caminho_de_rede(tmp_path):
    """O falso positivo que motivou a reescrita: depois que os arquivos passaram
    a viver na plataforma, o upload nunca preenche `armazenamento` — e o
    diagnóstico acusava 'sem local' um documento que tem o arquivo."""
    sha = _blob(tmp_path)
    rel = diagnostico.diagnosticar([_doc(caminho="", arquivos=[{"sha256": sha, "nome": "Manual.pdf"}])])

    assert rel["issues"] == []
    assert rel["stats"]["ok"] == 1
    assert rel["stats"]["com_arquivo_hospedado"] == 1


def test_blob_sumido_e_apontado(tmp_path):
    """Ponto cego anterior: nada verificava se o blob referenciado pelo banco
    ainda está em disco. É o risco que o próprio arquivos_store documenta —
    a pasta de arquivos dentro de `_internal\\` some no primeiro deploy."""
    rel = diagnostico.diagnosticar([
        _doc(caminho="", arquivos=[{"sha256": "a" * 64, "nome": "Manual.pdf"}])])

    assert _tipos(rel) == {"ARQUIVO_SUMIDO"}
    assert rel["issues"][0]["severidade"] == "error"
    assert rel["stats"]["arquivos_sumidos"] == 1


def test_blob_sumido_agrupa_os_documentos_que_compartilham_o_conteudo():
    """O store deduplica por conteúdo: um blob perdido derruba todos os
    documentos que apontam para ele, e isso é UM problema, não N."""
    arq = [{"sha256": "b" * 64, "nome": "IT.docx"}]
    rel = diagnostico.diagnosticar([_doc(id=1, arquivos=arq), _doc(id=2, arquivos=arq),
                                    _doc(id=3, arquivos=arq)])

    sumidos = [i for i in rel["issues"] if i["tipo"] == "ARQUIVO_SUMIDO"]
    assert len(sumidos) == 1
    assert sumidos[0]["qtd"] == 3
    assert rel["stats"]["arquivos_sumidos"] == 1
    assert rel["stats"]["documentos_afetados"] == 3


# ── pasta de rede ────────────────────────────────────────────────────────────
def test_pasta_com_arquivo_dentro_passa(tmp_path):
    pasta = tmp_path / "MAQ-1"
    pasta.mkdir()
    (pasta / "Manual.pdf").write_bytes(b"x")

    rel = diagnostico.diagnosticar([_doc(caminho=str(pasta))])
    assert rel["issues"] == []
    assert rel["stats"]["ok"] == 1


def test_pasta_vazia_e_apontada(tmp_path):
    """O que o cadastro não sabe dizer: 'Homologado' no sistema não prova que
    alguém depositou o arquivo na pasta."""
    pasta = tmp_path / "MAQ-VAZIA"
    pasta.mkdir()
    (pasta / "Thumbs.db").write_bytes(b"")   # lixo do Windows não conta como conteúdo

    rel = diagnostico.diagnosticar([_doc(caminho=str(pasta))])
    assert _tipos(rel) == {"PASTA_VAZIA"}
    assert rel["issues"][0]["severidade"] == "warning"
    assert rel["stats"]["pastas_vazias"] == 1


def test_pasta_com_subpasta_nao_e_considerada_vazia(tmp_path):
    """Critério conservador: subpasta é conteúdo. Descer a árvore inteira num
    share de rede custaria caro e o falso positivo seria pior que o silêncio."""
    pasta = tmp_path / "MAQ-ARVORE"
    (pasta / "Manuais").mkdir(parents=True)

    assert diagnostico.diagnosticar([_doc(caminho=str(pasta))])["issues"] == []


def test_pasta_ausente_agrupa_por_caminho(tmp_path):
    """A herança faz os 9 documentos do equipamento compartilharem o caminho:
    uma pasta que sumiu é UMA linha no relatório, não nove."""
    sumida = str(tmp_path / "nao-existe")
    rel = diagnostico.diagnosticar([_doc(id=i, caminho=sumida) for i in range(1, 10)])

    ausentes = [i for i in rel["issues"] if i["tipo"] == "PASTA_AUSENTE"]
    assert len(ausentes) == 1
    assert ausentes[0]["qtd"] == 9
    assert rel["stats"]["pastas_ausentes"] == 1


def test_caminho_repetido_toca_a_rede_uma_vez_so(tmp_path, monkeypatch):
    """Cada consulta é um round-trip SMB. A versão anterior fazia até 4 por
    documento sobre o MESMO diretório."""
    chamadas = []
    real = diagnostico.caminhos.resolver
    monkeypatch.setattr(diagnostico.caminhos, "resolver",
                        lambda c: (chamadas.append(c), real(c))[1])

    pasta = str(tmp_path / "MAQ-1")
    diagnostico.diagnosticar([_doc(id=i, caminho=pasta) for i in range(20)])
    assert len(chamadas) == 1


# ── proteção contra o share fora do ar ───────────────────────────────────────
def test_share_fora_do_ar_nao_vira_centena_de_falso_positivo(tmp_path):
    """Todo caminho falhar é evidência de rede caída, não de pastas apagadas em
    massa no mesmo dia. Reportar 'sumiram todas' seria pior que não reportar."""
    docs = [_doc(id=i, caminho=str(tmp_path / f"sumida-{i}")) for i in range(1, 6)]
    rel = diagnostico.diagnosticar(docs)

    assert rel["rede_indisponivel"] is True
    assert "PASTA_AUSENTE" not in _tipos(rel)
    assert rel["stats"]["pastas_ausentes"] == 0


def test_com_share_no_ar_a_pasta_que_sumiu_continua_sendo_apontada(tmp_path):
    """Contraprova do teste acima: com caminhos bons no meio, a heurística não
    dispara e o apontamento real aparece."""
    boa = tmp_path / "existe"
    boa.mkdir()
    (boa / "Manual.pdf").write_bytes(b"x")
    docs = [_doc(id=1, caminho=str(boa)), _doc(id=2, caminho=str(boa / ".." / "existe")),
            _doc(id=3, caminho=str(tmp_path / "sumida"))]

    rel = diagnostico.diagnosticar(docs)
    assert rel["rede_indisponivel"] is False
    assert "PASTA_AUSENTE" in _tipos(rel)


def test_orcamento_estourado_descarta_a_checagem_de_rede(tmp_path):
    """Sem teto, o timeout SMB de centenas de caminhos deixa a rota pendurada."""
    sha = _blob(tmp_path)
    docs = [_doc(id=1, caminho=str(tmp_path / "sumida")),
            _doc(id=2, arquivos=[{"sha256": sha, "nome": "ok.pdf"}]),
            _doc(id=3, arquivos=[{"sha256": "c" * 64, "nome": "perdido.pdf"}])]

    rel = diagnostico.diagnosticar(docs, orcamento_s=0)
    assert rel["orcamento_estourado"] is True
    assert rel["rede_indisponivel"] is True
    assert rel["stats"]["pastas_verificadas"] == 0
    # o que não depende do share segue sendo verificado
    assert "ARQUIVO_SUMIDO" in _tipos(rel)


# ── severidade ───────────────────────────────────────────────────────────────
def test_sem_arquivo_pesa_conforme_o_documento_estar_pronto():
    """Documento em elaboração ainda não ter arquivo é o curso normal das
    coisas. O que não fecha é o que consta como concluído e não tem nada."""
    rel = diagnostico.diagnosticar([
        _doc(id=1, equipamento="MAQ-EM-CURSO", concluido=False),
        _doc(id=2, equipamento="MAQ-PRONTA", concluido=True)])

    por_tipo = {i["tipo"]: i for i in rel["issues"]}
    assert por_tipo["SEM_ARQUIVO"]["severidade"] == "info"
    assert por_tipo["FINALIZADO_SEM_ARQUIVO"]["severidade"] == "error"
    # erro antes de info: a tela mostra os primeiros e corta o resto
    assert rel["issues"][0]["tipo"] == "FINALIZADO_SEM_ARQUIVO"
    assert rel["stats"]["sem_nenhuma_fonte"] == 2


def test_documento_sem_apontamento_nao_entra_na_conta_de_afetados(tmp_path):
    sha = _blob(tmp_path)
    rel = diagnostico.diagnosticar([
        _doc(id=1, arquivos=[{"sha256": sha, "nome": "ok.pdf"}]),
        _doc(id=2, concluido=True)])

    assert rel["stats"]["documentos"] == 2
    assert rel["stats"]["documentos_afetados"] == 1
    assert rel["stats"]["ok"] == 1
