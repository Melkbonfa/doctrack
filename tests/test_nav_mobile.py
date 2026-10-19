# -*- coding: utf-8 -*-
"""Testes da gaveta lateral no celular — a navegação inteira do app abaixo de 900px.

Existem por causa de uma falha que não aparece em teste de rota nem em revisão de
diff: a gaveta é DECLARADA em template (`<nav class="sidebar">` + o botão ☰) e
LIGADA em JavaScript, e as duas metades moravam em arquivos diferentes. Quando
uma faltava, a página continuava respondendo 200 com o HTML completo — e no
aparelho o módulo simplesmente não tinha navegação:

  • Tempos e Custos estendiam base.html, então tinham o ☰ na tela, mas nenhum
    dos dois carregava um `toggleSidebar`. O botão não fazia nada.
  • O PDR tem <head> e corpo próprios: tinha a <nav>, tinha o CSS do ☰ em
    pdr/static/style.css, e nunca teve o botão no HTML.

Os dois testes daqui fecham cada metade: um exige as duas peças no HTML de toda
página que tem gaveta, o outro exige que quem as liga continue sendo um só.
"""
import os
import re

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Toda página do app que tem gaveta. Projetos, hub e sub-hub ficam de fora com
# razão: são telas de uma coluna só, sem <nav class="sidebar">.
PAGINAS_COM_GAVETA = [
    "/",              # Documentos (estende base.html)
    "/equipamentos",
    "/missoes",
    "/config",
    "/custos",
    "/tempos",
    "/pdr",           # <head> e corpo próprios — o caso que faltava
]


@pytest.mark.parametrize("rota", PAGINAS_COM_GAVETA)
def test_pagina_com_gaveta_tem_o_botao_e_o_ligador(client, rota):
    """Ter a <nav> não basta: sem o ☰ ela fica em translateX(-100%) para sempre.

    Abaixo de 900px a sidebar vira gaveta (style.css) e o único caminho para
    abri-la é o botão. Sem ele o módulo perde a navegação, o "Voltar aos
    módulos" e o "Sair" — e nada nisso falha de forma visível no servidor.
    """
    html = client.get(rota).data.decode("utf-8")

    assert 'class="sidebar"' in html, f"{rota} deixou de ter gaveta — revise esta lista"
    assert 'id="sidebar-toggle"' in html, f"{rota} tem gaveta e não tem o botão ☰"
    assert 'id="sidebar-backdrop"' in html, f"{rota} tem gaveta e não tem o fundo escuro"
    assert "/static/nav-mobile.js" in html, f"{rota} não carrega quem liga a gaveta"


def test_a_gaveta_tem_um_dono_so():
    """Guarda contra a volta das cópias.

    Eram quatro implementações da mesma função, e as cópias já tinham divergido:
    duas não fechavam a gaveta ao tocar num item, e a de Missões ligava os itens
    um a um no carregamento — o que nunca pegava nenhum, porque ali os itens da
    gaveta são as missões e nascem depois do fetch. Copiar de novo é o jeito
    natural de "resolver" isso no próximo módulo; este teste torna a cópia
    visível na hora.
    """
    estatico = os.path.join(RAIZ, "static")
    culpados = []
    for nome in os.listdir(estatico):
        if not nome.endswith(".js") or nome == "nav-mobile.js":
            continue
        with open(os.path.join(estatico, nome), encoding="utf-8") as f:
            corpo = f.read()
        # Comentário que aponta para o dono é esperado; código que pega o
        # elemento para ligar um listener, não.
        if re.search(r"getElementById\(\s*[\"']sidebar-(toggle|backdrop)[\"']", corpo):
            culpados.append(nome)

    assert not culpados, (
        "estes arquivos voltaram a ligar a gaveta por conta própria: "
        + ", ".join(culpados)
        + " — o dono é static/nav-mobile.js, carregado por _pwa_head.html"
    )
