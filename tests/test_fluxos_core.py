"""
Testes da máquina de estados dos fluxos (fluxos/core.py) — sem banco, sem Flask.

O caso de referência é o modelo "Manual": Escrita (autor) → Diagramação
(diagramador) → Revisão (autor, devolve para Diagramação).
"""
import pytest

from fluxos import core

PAPEIS = [{"chave": "autor", "nome": "Autor"},
          {"chave": "diagramador", "nome": "Diagramador", "padrao_user_id": 7}]
ETAPAS = [{"chave": "escrita", "nome": "Escrita", "papel": "autor", "tipo": "execucao"},
          {"chave": "diagramacao", "nome": "Diagramação", "papel": "diagramador",
           "tipo": "execucao"},
          {"chave": "revisao", "nome": "Revisão", "papel": "autor", "tipo": "revisao"}]


def _ok():
    papeis, etapas, erro = core.validar_modelo(PAPEIS, ETAPAS)
    assert erro is None
    return papeis, etapas


# ── validação do modelo ──────────────────────────────────────────────────────

def test_modelo_manual_valido_e_devolve_para_a_anterior_por_padrao():
    papeis, etapas = _ok()
    assert [e["chave"] for e in etapas] == ["escrita", "diagramacao", "revisao"]
    assert etapas[2]["devolve_para"] == "diagramacao"
    assert etapas[0]["devolve_para"] == ""
    assert papeis[1]["padrao_user_id"] == 7
    assert papeis[0]["padrao_user_id"] is None


def test_chave_sai_do_nome_quando_falta():
    papeis, etapas, erro = core.validar_modelo(
        [{"nome": "Revisor Técnico"}],
        [{"nome": "Elaboração da IT", "papel": "revisor_tecnico", "tipo": "execucao"}])
    assert erro is None
    assert papeis[0]["chave"] == "revisor_tecnico"
    assert etapas[0]["chave"] == "elaboracao_da_it"


@pytest.mark.parametrize("papeis,etapas,trecho", [
    (PAPEIS, [], "pelo menos uma etapa"),
    ([], ETAPAS, "pelo menos um papel"),
    (PAPEIS, ETAPAS + [dict(ETAPAS[0])], "repetida"),
    (PAPEIS + [dict(PAPEIS[0])], ETAPAS, "repetido"),
    (PAPEIS, [dict(ETAPAS[0], papel="fantasma")], "papel"),
    (PAPEIS, [dict(ETAPAS[2])], "primeira"),
    (PAPEIS, [dict(ETAPAS[0], tipo="aprovacao")], "Tipo de etapa"),
    (PAPEIS, ETAPAS[:2] + [dict(ETAPAS[2], devolve_para="revisao")], "anterior"),
    (PAPEIS, ETAPAS[:2] + [dict(ETAPAS[2], devolve_para="nao_existe")], "anterior"),
    (PAPEIS, [dict(ETAPAS[0], nome="")], "nome"),
])
def test_modelo_invalido(papeis, etapas, trecho):
    _, _, erro = core.validar_modelo(papeis, etapas)
    assert erro and trecho in erro


# ── transições ───────────────────────────────────────────────────────────────

def test_execucao_so_envia():
    _, etapas = _ok()
    assert core.acoes_possiveis(etapas, "escrita") == ["enviar"]
    assert core.acoes_possiveis(etapas, "revisao") == ["aprovar", "devolver"]
    with pytest.raises(ValueError):
        core.transicao(etapas, "escrita", "aprovar")
    with pytest.raises(ValueError):
        core.transicao(etapas, "revisao", "enviar")


def test_enviar_avanca_sem_mexer_na_rodada():
    _, etapas = _ok()
    assert core.transicao(etapas, "escrita", "enviar") == ("diagramacao", False, False)
    assert core.transicao(etapas, "diagramacao", "enviar") == ("revisao", False, False)


def test_aprovar_na_ultima_encerra():
    _, etapas = _ok()
    assert core.transicao(etapas, "revisao", "aprovar") == (None, True, False)


def test_devolver_volta_e_soma_rodada():
    _, etapas = _ok()
    assert core.transicao(etapas, "revisao", "devolver") == ("diagramacao", False, True)


def test_enviar_na_ultima_etapa_de_execucao_encerra():
    _, etapas, _ = core.validar_modelo(PAPEIS, ETAPAS[:2])
    assert core.transicao(etapas, "diagramacao", "enviar") == (None, True, False)


def test_aprovar_no_meio_avanca():
    _, etapas, erro = core.validar_modelo(PAPEIS, ETAPAS + [
        {"chave": "final", "nome": "Arte-final", "papel": "diagramador", "tipo": "execucao"}])
    assert erro is None
    assert core.transicao(etapas, "revisao", "aprovar") == ("final", False, False)


def test_rotulos():
    _, etapas = _ok()
    assert core.rotulo_acao(etapas, "escrita", "enviar") == "Enviar para Diagramação"
    assert core.rotulo_acao(etapas, "revisao", "aprovar") == "Aprovar"
    assert core.rotulo_acao(etapas, "revisao", "devolver") == "Devolver para Diagramação"
    _, curtas, _ = core.validar_modelo(PAPEIS, ETAPAS[:2])
    assert core.rotulo_acao(curtas, "diagramacao", "enviar") == "Concluir"


# ── quem age e quem é avisado ────────────────────────────────────────────────

GIULLIA, MARCOS, GESTOR = 1, 2, 3
PART = {"autor": GIULLIA, "diagramador": MARCOS}


def test_responsavel_da_etapa():
    _, etapas = _ok()
    assert core.responsavel(PART, etapas, "revisao") == GIULLIA
    assert core.responsavel(PART, etapas, "diagramacao") == MARCOS


def test_marcos_envia_para_revisao():
    _, etapas = _ok()
    acao, info = core.destinatarios(PART, etapas, "revisao", iniciador_id=GESTOR,
                                    ator_id=MARCOS, encerra=False)
    assert acao == [GIULLIA]
    assert info == [GESTOR]            # Giullia não recebe também um "info"


def test_giullia_com_dois_papeis_nao_recebe_aviso_da_propria_acao():
    _, etapas = _ok()
    acao, info = core.destinatarios(PART, etapas, "diagramacao", iniciador_id=GIULLIA,
                                    ator_id=GIULLIA, encerra=False)
    assert acao == [MARCOS]
    assert info == []


def test_ao_encerrar_todos_recebem_info():
    _, etapas = _ok()
    acao, info = core.destinatarios(PART, etapas, None, iniciador_id=GESTOR,
                                    ator_id=GIULLIA, encerra=True)
    assert acao == []
    assert sorted(info) == [MARCOS, GESTOR]
