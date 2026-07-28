"""Normalização de caminhos UNC × unidade mapeada (módulo `caminhos`).

O caso real que originou o módulo: a mesma pasta chegava ao sistema como
`P:\\Engenharia\\...` (copiada da barra do Explorer) e como
`\\\\loccus-srv03\\Projetos$\\Engenharia\\...` (copiada de outro registro), e só a
segunda passava pela allowlist — o usuário via "fora das pastas permitidas" numa
pasta que existe e que ele acabara de abrir no Explorer.

O mapa de apelidos é fixado por fixture: carregado do ambiente ele depende de
quais unidades a máquina tem montadas, e a suíte passaria conforme a estação.
"""
import pytest

import caminhos

UNC = r"\\loccus-srv03\Projetos$"
RAIZ = UNC + r"\Engenharia"
PASTA_REAL = r"\Engenharia\Projetos\1. Produtos\AmpliGene Lite (PC-96)\Documentos\POP"


@pytest.fixture(autouse=True)
def aliases_fixos():
    original = dict(caminhos.ALIASES)
    caminhos.definir_aliases({"P:": UNC, "Z:": r"\\LOCCUS-SRV02\Publico$"})
    yield
    caminhos.definir_aliases(original)


# ── normalizar ────────────────────────────────────────────────────────────────
def test_unidade_mapeada_vira_unc():
    assert caminhos.normalizar("P:" + PASTA_REAL) == UNC + PASTA_REAL


def test_unc_permanece_intacta():
    assert caminhos.normalizar(UNC + PASTA_REAL) == UNC + PASTA_REAL


def test_normalizar_e_idempotente():
    uma = caminhos.normalizar("P:" + PASTA_REAL)
    assert caminhos.normalizar(uma) == uma


@pytest.mark.parametrize("entrada", [
    '"P:\\Engenharia\\Projetos"',      # "Copiar como caminho" do Explorer traz aspas
    "  P:\\Engenharia\\Projetos  ",    # espaço colado junto
    "P:/Engenharia/Projetos",          # barra normal (vem de planilha)
    "P:\\Engenharia\\Projetos\\",      # barra final
    "P:\\\\Engenharia\\\\Projetos",    # separador duplicado
    "p:\\engenharia\\Projetos",        # letra minúscula
])
def test_sujeira_da_entrada_e_absorvida(entrada):
    """Tudo isto é o que o usuário realmente cola — nenhum deve virar um caminho
    diferente no banco."""
    assert caminhos.normalizar(entrada).lower() == (UNC + r"\Engenharia\Projetos").lower()


def test_caminho_sem_apelido_nao_e_traduzido():
    assert caminhos.normalizar(r"C:\Apps\doctrack") == r"C:\Apps\doctrack"


def test_vazio_vira_string_vazia():
    assert caminhos.normalizar(None) == ""
    assert caminhos.normalizar("   ") == ""


# ── para_exibicao ─────────────────────────────────────────────────────────────
def test_exibicao_devolve_a_letra_que_o_usuario_reconhece():
    assert caminhos.para_exibicao(UNC + PASTA_REAL) == "P:" + PASTA_REAL


def test_exibicao_sem_apelido_devolve_o_proprio_caminho():
    fora = r"\\outro-srv\Share\x"
    assert caminhos.para_exibicao(fora) == fora


def test_exibicao_prefere_o_apelido_mais_especifico():
    caminhos.definir_aliases({"P:": UNC, "Q:": RAIZ})
    assert caminhos.para_exibicao(RAIZ + r"\Projetos") == r"Q:\Projetos"


# ── allowlist ─────────────────────────────────────────────────────────────────
def test_raiz_em_unc_autoriza_caminho_com_letra():
    """O bug original: a raiz declarada em UNC rejeitava o caminho colado com P:."""
    assert caminhos.dentro_das_raizes("P:" + PASTA_REAL, [RAIZ]) == UNC + PASTA_REAL


def test_raiz_com_letra_autoriza_caminho_em_unc():
    assert caminhos.dentro_das_raizes(UNC + PASTA_REAL, [r"P:\Engenharia"]) == UNC + PASTA_REAL


def test_travessia_com_pontopontos_e_bloqueada():
    assert caminhos.dentro_das_raizes(r"P:\Engenharia\..\..\Windows", [RAIZ]) is None


def test_share_de_terceiro_e_bloqueado():
    assert caminhos.dentro_das_raizes(r"\\atacante\share\x", [RAIZ]) is None


def test_prefixo_parecido_nao_vaza():
    """`...\\Engenharia2` não pode passar por estar sob `...\\Engenharia`."""
    assert caminhos.dentro_das_raizes(UNC + r"\Engenharia2\x", [RAIZ]) is None


def test_a_propria_raiz_e_autorizada():
    assert caminhos.dentro_das_raizes("P:\\Engenharia", [RAIZ]) == RAIZ


# ── resolução no filesystem ───────────────────────────────────────────────────
def test_resolver_devolve_a_variante_que_existe(tmp_path, monkeypatch):
    """Quando só a forma com letra abre (ou só a UNC), é ela que deve ser usada
    para o I/O — é o que evita o falso 'pasta não encontrada'."""
    real = str(tmp_path)
    caminhos.definir_aliases({"X:": real})
    monkeypatch.setattr(caminhos.os.path, "exists", lambda p: p == "X:\\sub")
    assert caminhos.resolver(real + "\\sub") == "X:\\sub"
    assert caminhos.existe(real + "\\sub") is True


def test_resolver_devolve_none_quando_nenhuma_variante_existe(monkeypatch):
    monkeypatch.setattr(caminhos.os.path, "exists", lambda p: False)
    assert caminhos.resolver("P:" + PASTA_REAL) is None
    assert caminhos.existe("P:" + PASTA_REAL) is False


# ── carregamento de configuração ──────────────────────────────────────────────
def test_env_define_apelidos(monkeypatch):
    monkeypatch.setenv("DOCTRACK_PATH_ALIASES", r"P:=\\srv\a; Q:=\\srv\b\ ")
    assert caminhos._aliases_do_env() == [("P:", r"\\srv\a"), ("Q:", r"\\srv\b")]


def test_env_ignora_entrada_malformada(monkeypatch):
    monkeypatch.setenv("DOCTRACK_PATH_ALIASES", r"lixo;P:=C:\nao_unc;Q:=\\srv\ok")
    assert caminhos._aliases_do_env() == [("Q:", r"\\srv\ok")]


def test_configuracao_vence_a_autodeteccao(monkeypatch):
    """Em produção o serviço não tem mapeamento nenhum; o .env é a fonte. E um
    apelido declarado não pode ser sobrescrito pelo que a sessão local montou."""
    monkeypatch.setenv("DOCTRACK_PATH_ALIASES", r"P:=\\declarado\share")
    monkeypatch.setattr(caminhos, "_aliases_do_windows",
                        lambda: [("P:", r"\\detectado\share"), ("W:", r"\\so-detectado\x")])
    mapa = caminhos.carregar_aliases()
    assert mapa["P:"] == r"\\declarado\share"
    assert mapa["W:"] == r"\\so-detectado\x"


def test_raizes_aceitam_varias_separadas_por_ponto_e_virgula(monkeypatch):
    monkeypatch.setenv("DOCTRACK_FILE_ROOTS", r"P:\Engenharia;\\outro\share\Docs")
    assert caminhos.carregar_raizes() == [RAIZ, r"\\outro\share\Docs"]
