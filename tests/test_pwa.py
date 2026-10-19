"""Testes da build PWA — o que torna o DocTrack instalável no celular.

Três coisas são fáceis de quebrar sem perceber num deploy futuro, e é por elas
que estes testes existem:

  1. o service worker sair de `/sw.js`. Servido de qualquer subpasta, o escopo
     dele encolhe para aquela subpasta e a instalação vira enfeite — sem
     nenhum erro visível em lugar nenhum;
  2. `/sw.js` ou `/manifest.webmanifest` entrarem na lista de LIBERADOS do kill
     switch. São rotas de infraestrutura e parecem inofensivas, mas travado o
     sistema tem que responder 423 em tudo;
  3. o parcial `_pwa_head.html` deixar de ser incluído em alguma página. São
     seis templates, cinco deles com <head> próprio — exatamente o arranjo em
     que se esquece um.
"""
import json

import pytest

TOKEN = "token-do-gatilho-para-teste-1234"
SENHA = "senha-mestra-de-teste"


# ── ROTAS ─────────────────────────────────────────────────────────────────────

def test_service_worker_e_servido_da_raiz(client):
    """Na raiz, e em nenhum outro lugar.

    O escopo de um service worker é o diretório de onde ele foi baixado: em
    /static/sw.js ele controlaria /static/* e nenhuma página do app.
    """
    res = client.get("/sw.js")
    assert res.status_code == 200
    assert "javascript" in res.headers["Content-Type"]
    # É mesmo o worker, e não uma página de erro com status 200.
    assert b"addEventListener" in res.data


def test_service_worker_nao_pode_ser_cacheado_pelo_navegador(client):
    """Um sw.js preso no cache do aparelho é um deploy que nunca chega."""
    res = client.get("/sw.js")
    assert "no-cache" in res.headers.get("Cache-Control", "")


def test_manifesto_e_servido_com_o_mime_certo(client):
    res = client.get("/manifest.webmanifest")
    assert res.status_code == 200
    assert res.headers["Content-Type"].startswith("application/manifest+json")


def test_manifesto_e_json_valido_e_coerente(client):
    """O navegador descarta o manifesto inteiro e em silêncio se ele não parseia."""
    dados = json.loads(client.get("/manifest.webmanifest").data)

    assert dados["start_url"] == "/hub"
    assert dados["scope"] == "/"
    # start_url precisa estar dentro do scope, senão a instalação é recusada.
    assert dados["start_url"].startswith(dados["scope"])
    assert dados["display"] == "standalone"


def test_manifesto_tem_os_icones_que_a_instalacao_exige(client):
    """Android exige 192 e 512 em `any`, e um `maskable` para recortar sem
    comer a marca. Faltando qualquer um, o convite de instalação não aparece."""
    dados = json.loads(client.get("/manifest.webmanifest").data)
    tamanhos = {i["sizes"] for i in dados["icons"]}
    assert {"192x192", "512x512"} <= tamanhos

    propositos = {p for i in dados["icons"] for p in i["purpose"].split()}
    assert "any" in propositos and "maskable" in propositos


@pytest.mark.parametrize("caminho", [
    "/static/icons/icone-192.png",
    "/static/icons/icone-512.png",
    "/static/icons/icone-maskable-512.png",
    "/static/icons/apple-touch-icon.png",
    "/static/offline.html",
])
def test_arquivos_apontados_existem(client, caminho):
    """Manifesto e worker referenciam arquivos por caminho fixo; um `git add`
    esquecido nos ícones só apareceria no celular de alguém."""
    res = client.get(caminho)
    assert res.status_code == 200, f"{caminho} não está sendo servido"
    assert len(res.data) > 0


def test_rotas_do_manifesto_batem_com_rotas_reais(client, app):
    """Todo `url` de atalho do manifesto tem que existir de fato — um atalho
    para 404 é pior que atalho nenhum, e só se descobre com o app instalado."""
    dados = json.loads(client.get("/manifest.webmanifest").data)
    registradas = {str(r.rule) for r in app.url_map.iter_rules()}

    for atalho in dados["shortcuts"]:
        assert atalho["url"] in registradas, f"atalho aponta para rota inexistente: {atalho['url']}"


# ── INTERAÇÃO COM O KILL SWITCH ───────────────────────────────────────────────

@pytest.fixture
def travado(client, app, monkeypatch):
    """Deixa o sistema travado, como no incidente real."""
    from models import bcrypt

    with app.app_context():
        monkeypatch.setenv("DOCTRACK_KILL_TOKEN_HASH",
                           bcrypt.generate_password_hash(TOKEN).decode())
        monkeypatch.setenv("DOCTRACK_UNLOCK_HASH",
                           bcrypt.generate_password_hash(SENHA).decode())

    res = client.post("/api/kill-switch/lock",
                      json={"motivo": "teste de pwa"},
                      headers={"X-Kill-Token": TOKEN})
    assert res.status_code == 200, res.get_json()
    yield


@pytest.mark.parametrize("caminho", ["/sw.js", "/manifest.webmanifest"])
def test_rotas_do_pwa_travam_junto_com_o_resto(client, travado, caminho):
    """Não são exceção. Só `/api/version` e as rotas do próprio kill switch são,
    e essas duas não têm por que entrar na lista: o worker já instalado repassa
    navegação para a rede sem consultar cache, então a tela de bloqueio aparece
    mesmo sem conseguir se atualizar."""
    assert client.get(caminho).status_code == 423


# ── PRESENÇA NAS PÁGINAS ──────────────────────────────────────────────────────

# As dez páginas do app. Quatro têm <head> próprio e recebem o parcial na mão —
# é o arranjo em que se esquece uma. Custos, Tempos e PDR faltavam nesta lista:
# os dois primeiros estendem base.html e vieram de graça, mas o PDR tem <head>
# próprio e é exatamente o caso que o teste existe para pegar.
@pytest.mark.parametrize("rota", [
    "/",            # dashboard (estende base.html)
    "/hub",         # start_url do manifesto
    "/hub/pde",     # subhub
    "/projetos",    # entregáveis
    "/equipamentos",
    "/missoes",
    "/config",
    "/custos",
    "/tempos",
    "/pdr",         # <head> próprio
])
def test_toda_pagina_se_declara_instalavel(client, rota):
    html = client.get(rota).data.decode("utf-8")
    assert '<link rel="manifest" href="/manifest.webmanifest">' in html, \
        f"{rota} não inclui _pwa_head.html"
    assert "/static/pwa.js" in html, f"{rota} não carrega o registro do worker"
    assert "/static/mobile.css" in html, f"{rota} não carrega o passe de celular"


def test_tela_de_bloqueio_nao_carrega_js_de_aplicacao(client, travado):
    """travado.html é deliberadamente autossuficiente: é a única porta que
    responde com o sistema comprometido, e quanto menos código de aplicação ela
    executa, menor a superfície. O parcial de PWA não entra ali."""
    html = client.get("/").data.decode("utf-8")
    assert "/static/pwa.js" not in html
    assert '<link rel="manifest"' not in html
