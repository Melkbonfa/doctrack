"""Trava que impede a referência técnica de envelhecer.

`docs/referencia/` é gerado por `scripts/gerar_docs.py` a partir do código. Sem
este teste, o gerador seria só mais um script que alguém lembra de rodar — e o
histórico deste repositório mostra o que acontece com documentação que depende
de alguém lembrar: quatro guias de implantação divergentes e uma tabela no
README mandando rodar um script de backup que já tinha sido removido.

Com ele, adicionar uma rota, um modelo ou uma variável de ambiente sem regerar
a documentação quebra a suíte. O conserto é uma linha:

    python scripts/gerar_docs.py

Só cobre a camada gerada. Arquitetura, ADRs, runbook e os documentos
funcionais são escritos à mão e nenhum teste garante que estejam certos — é uma
limitação real, e o motivo de a camada gerada ser o máximo possível do total.
"""
import os
import re

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REFERENCIA = os.path.join(RAIZ, "docs", "referencia")

# Pastas cuja documentação é mantida ativamente. `planos/`, `superpowers/` e os
# guias históricos ficam de fora de propósito: são registros datados, e um link
# que envelheceu neles é informação (aquilo mudou), não defeito a corrigir.
PASTAS_VIVAS = ["referencia", "arquitetura", "operacao", "funcional"]

RE_LINK = re.compile(r"\[[^\]]*\]\((?!https?://|mailto:)([^)#]+)(?:#[^)]*)?\)")
RE_FENCE = re.compile(r"```.*?```", re.S)
RE_INLINE = re.compile(r"`[^`\n]*`")


@pytest.fixture(scope="module")
def gerado():
    """Roda o gerador uma vez e devolve {nome do arquivo: conteúdo esperado}."""
    import sys
    sys.path.insert(0, os.path.join(RAIZ, "scripts"))
    import gerar_docs

    return gerar_docs.gerar()


@pytest.mark.parametrize("nome", ["api.md", "dados.md", "permissoes.md", "config.md"])
def test_referencia_em_dia(gerado, nome):
    caminho = os.path.join(REFERENCIA, nome)
    assert os.path.exists(caminho), (
        f"docs/referencia/{nome} não existe. Rode: python scripts/gerar_docs.py"
    )

    with open(caminho, encoding="utf-8", newline="") as fh:
        no_disco = fh.read()

    assert no_disco == gerado[nome], (
        f"docs/referencia/{nome} está defasado em relação ao código.\n"
        f"Rode: python scripts/gerar_docs.py"
    )


def test_todo_modelo_tem_dominio():
    """Modelo novo sem domínio derruba o gerador — aqui a mensagem é melhor.

    `coletar_tabelas()` levanta SystemExit quando encontra uma classe fora de
    DOMINIOS. Chamar aqui transforma isso num teste com nome, para quem criou o
    modelo entender o que fazer sem abrir o gerador.
    """
    import sys
    sys.path.insert(0, os.path.join(RAIZ, "scripts"))
    import gerar_docs

    try:
        tabelas = gerar_docs.coletar_tabelas()
    except SystemExit as e:
        pytest.fail(str(e))

    assert tabelas, "nenhuma tabela coletada — o gerador não enxergou os modelos"


def test_rotas_publicas_sao_as_esperadas():
    """A superfície pública muda com revisão, não por acidente.

    Rota de API sem decorator é alcançável por qualquer um na rede. São oito, e
    cada uma tem motivo: as duas de autenticação, as três do kill switch (que
    precisa funcionar justamente quando ninguém consegue logar), o health check
    e as duas do assistente do OneNote — quem chama é o .cmd na máquina da
    pessoa, sem o token de login, e o que autoriza é o segredo de um ticket de
    uso único, que só deixa contar a etapa e pôr um pacote na área de espera
    (gravar exige a pessoa logada; ver cadernos/importacao.py). Uma nona
    aparecendo aqui é uma decisão de segurança que alguém precisa ter tomado de
    propósito.
    """
    import sys
    sys.path.insert(0, os.path.join(RAIZ, "scripts"))
    import gerar_docs

    rotas = gerar_docs.coletar_rotas()
    publicas = {
        r["path"] for r in rotas if r["acesso"] == "publico" and r["api"]
    }

    esperadas = {
        "/api/auth/login",
        "/api/auth/primeiro-acesso",
        "/api/kill-switch/lock",
        "/api/kill-switch/unlock",
        "/api/kill-switch/status",
        "/api/version",
        "/cadernos/api/importacoes/assistente/aviso",
        "/cadernos/api/importacoes/assistente/pacote",
    }

    novas = publicas - esperadas
    assert not novas, (
        f"Rotas de API abertas sem token que ninguém aprovou: {sorted(novas)}. "
        "Se for intencional, adicione à lista deste teste junto com o motivo."
    )

    sumidas = esperadas - publicas
    assert not sumidas, (
        f"Rotas que eram públicas deixaram de ser: {sorted(sumidas)}. "
        "Se foi de propósito, atualize este teste — e confira se o kill switch "
        "e o primeiro acesso ainda funcionam para quem não consegue logar."
    )


def _docs_vivas():
    """Todo .md das pastas mantidas ativamente, mais os dois índices."""
    caminhos = []
    for pasta in PASTAS_VIVAS:
        base = os.path.join(RAIZ, "docs", pasta)
        for dir_atual, _, arquivos in os.walk(base):
            caminhos += [os.path.join(dir_atual, a)
                         for a in arquivos if a.endswith(".md")]
    caminhos.append(os.path.join(RAIZ, "docs", "README.md"))
    caminhos.append(os.path.join(RAIZ, "README.md"))
    return caminhos


def test_links_internos_resolvem():
    """Nenhum link relativo apontando para arquivo que não existe.

    Documentação que se referencia entre si só vale enquanto os links funcionam,
    e renomear um arquivo quebra os links dos outros em silêncio. Cobre só as
    pastas mantidas ativamente (PASTAS_VIVAS).

    Blocos de código são removidos antes: um trecho Python com `[...](...)`
    seria lido como link markdown.
    """
    quebrados = []
    for caminho in _docs_vivas():
        with open(caminho, encoding="utf-8") as fh:
            texto = fh.read()
        texto = RE_FENCE.sub("", texto)
        texto = RE_INLINE.sub("", texto)

        for m in RE_LINK.finditer(texto):
            destino = m.group(1).strip()
            alvo = os.path.normpath(
                os.path.join(os.path.dirname(caminho), destino))
            if not os.path.exists(alvo):
                quebrados.append(
                    f"{os.path.relpath(caminho, RAIZ)} -> {destino}")

    assert not quebrados, "Links internos quebrados:\n  " + "\n  ".join(quebrados)
