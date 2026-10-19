"""Módulo Cadernos (cadernos de laboratório que substituem o OneNote do PDR).

O que estes testes fixam, e por quê:

  * **Níveis de página.** Subpágina não tem parent_id: é ordem + nível, com as
    invariantes do OneNote (primeira página no nível 1, sem pular nível, até 3).
    Mover/rebaixar uma página leva a série junto.
  * **Saneamento.** O servidor guarda o resultado de `sanear_html`, nunca o que
    chegou. Script, on*=, javascript:, url() em CSS e imagem externa somem; o
    token que o front põe no src das imagens nunca chega ao banco.
  * **Trava de edição.** Uma pessoa por vez; trava viva bloqueia (423), versão
    velha é recusada (409), trava expirada é liberada, e o dono pode tomar.
  * **Arquivos de qualquer extensão.** Aceitos SÓ aqui, e servidos como download
    com mime genérico — é isso que torna seguro aceitar um .html.
  * **Permissão por caderno.** Área, papel de membro, teto do perfil leitura.
"""
import base64
import io
from datetime import datetime, timedelta

import pytest

import arquivos_store
from models import db, User
from cadernos import core
from cadernos.models import Caderno, CadernoPagina, CadernoArquivo, CadernoPaginaVersao


@pytest.fixture(autouse=True)
def _raiz_temporaria(tmp_path, monkeypatch):
    monkeypatch.setattr(arquivos_store, "RAIZ", str(tmp_path / "arquivos"))
    yield


@pytest.fixture
def area_pdr(app):
    """Gestor, técnico e leitura com a área PDR no cadastro (o seed vem sem área)."""
    for email in ("gestor@test.com", "tecnico@test.com", "leitura@test.com"):
        u = User.query.filter_by(email=email).first()
        u.areas = "pdr"
    db.session.commit()


def H(token):
    return {"Authorization": f"Bearer {token}"}


def _criar_caderno(client, token, **extra):
    corpo = {"area": "pdr", "nome": "Projeto L-037", "modelo": "projeto_pdr"}
    corpo.update(extra)
    res = client.post("/cadernos/api/cadernos", json=corpo, headers=H(token))
    assert res.status_code == 201, res.get_json()
    return res.get_json()["caderno"]["uuid"]


def _arvore(client, token, cad):
    res = client.get(f"/cadernos/api/cadernos/{cad}/arvore", headers=H(token))
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def _secao(client, token, cad, nome="Desenvolvimento"):
    return next(n["uuid"] for n in _arvore(client, token, cad)["nos"] if n["nome"] == nome)


def _nova_pagina(client, token, secao, **extra):
    res = client.post(f"/cadernos/api/secoes/{secao}/paginas", json=extra, headers=H(token))
    assert res.status_code == 201, res.get_json()
    return res.get_json()["pagina"]


# ══════════════════════════════════════════════════════════════════════════════
# CORE — níveis
# ══════════════════════════════════════════════════════════════════════════════

def test_normalizar_niveis_aplica_as_tres_invariantes():
    assert core.normalizar_niveis([3, 3, 1, 3, 2, 9]) == [1, 2, 1, 2, 2, 3]
    assert core.normalizar_niveis([]) == []
    assert core.normalizar_niveis(["x", 0]) == [1, 1]


def test_mover_serie_leva_as_subpaginas_com_o_recuo_relativo():
    itens = [(1, 1), (2, 2), (3, 3), (4, 1)]
    serie, resto = core.extrair_serie(itens, 0)
    assert serie == [(1, 1), (2, 2), (3, 3)]
    assert resto == [(4, 1)]
    assert core.inserir_serie(resto, 1, serie) == [(4, 1), (1, 1), (2, 2), (3, 3)]


def test_inserir_serie_no_topo_forca_nivel_1():
    resto = [(9, 1)]
    assert core.inserir_serie(resto, 0, [(5, 2), (6, 3)]) == [(5, 1), (6, 2), (9, 1)]


def test_rebaixar_leva_a_serie_e_respeita_o_teto():
    itens = [(1, 1), (2, 1), (3, 2), (4, 1)]
    assert core.alterar_nivel(itens, 1, +1) == [(1, 1), (2, 2), (3, 3), (4, 1)]
    # A primeira página não sai do nível 1.
    assert core.alterar_nivel(itens, 0, +1)[0] == (1, 1)


# ══════════════════════════════════════════════════════════════════════════════
# CORE — permissão
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("role,tem_area,acesso,membro,dono,esperado", [
    ("admin",   False, "nenhum", None,     None, "dono"),
    ("tecnico", True,  "editor", None,     None, "editor"),
    ("tecnico", True,  "leitor", None,     None, "leitor"),
    ("tecnico", True,  "nenhum", None,     None, None),
    ("tecnico", False, "editor", None,     None, None),
    ("tecnico", False, "nenhum", "editor", None, "editor"),   # membro vence a área
    ("gestor",  True,  "editor", None,     None, "dono"),
    ("gestor",  True,  "nenhum", None,     None, None),        # privado é privado
    ("leitura", True,  "editor", None,     None, "leitor"),    # teto do perfil
    ("leitura", True,  "editor", "dono",   None, "leitor"),
    ("tecnico", False, "nenhum", None,     7,    "dono"),      # quem criou
])
def test_papel_efetivo(role, tem_area, acesso, membro, dono, esperado):
    assert core.papel_efetivo(user_id=7, user_role=role, tem_area=tem_area,
                              caderno_dono_id=dono, acesso_area=acesso,
                              papel_membro=membro) == esperado


# ══════════════════════════════════════════════════════════════════════════════
# CORE — saneamento
# ══════════════════════════════════════════════════════════════════════════════

UUID = "12345678-1234-1234-1234-123456789012"


@pytest.mark.parametrize("sujo,proibido", [
    ("<p>a<script>alert(1)</script>b</p>", "alert"),
    ('<p onclick="x()">a</p>', "onclick"),
    ('<a href="javascript:alert(1)">x</a>', "javascript"),
    ('<p style="background:url(http://x)">a</p>', "url("),
    ('<img src="x" onerror="alert(1)">', "onerror"),
    ('<iframe src="http://x"></iframe>', "iframe"),
    ('<svg><script>alert(1)</script></svg>', "alert"),
    ('<p style="width:expression(alert(1))">a</p>', "expression"),
    ('<input type="text" value="x">', "text"),
    ("<!-- comentário --><p>a</p>", "comentário"),
])
def test_sanear_remove_o_perigoso(sujo, proibido):
    limpo, _ = core.sanear_html(sujo)
    assert proibido not in limpo


def test_sanear_preserva_o_conteudo_do_onenote():
    limpo, _ = core.sanear_html(
        '<figure class="table"><table><thead><tr><th>Reagente</th></tr></thead>'
        '<tbody><tr><td style="background-color:#9BBB59">Mix</td></tr></tbody></table></figure>'
        '<p><mark class="marker-yellow">realce</mark> <strong>forte</strong> H<sub>2</sub>O</p>'
        '<ul class="todo-list"><li><label class="todo-list__label"><input type="checkbox" checked>'
        '<span class="todo-list__label__description">feito</span></label></li></ul>')
    for trecho in ('background-color:#9BBB59', 'class="marker-yellow"', "<strong>forte</strong>",
                   "<sub>2</sub>", 'class="table"', 'type="checkbox"', 'disabled="disabled"'):
        assert trecho in limpo


def test_sanear_troca_src_por_referencia_e_tira_o_token():
    limpo, imgs = core.sanear_html(
        f'<img src="/cadernos/api/arquivos/{UUID}/conteudo?token=SEGREDO" alt="gel">'
        '<img src="https://externo.com/x.png">')
    assert f'data-arquivo="{UUID}"' in limpo
    assert "SEGREDO" not in limpo and "src=" not in limpo
    assert "externo" not in limpo
    assert imgs == {UUID}


def test_sanear_grava_imagem_colada_como_data_uri():
    guardadas = []

    def guardar(mime, dados):
        guardadas.append((mime, dados))
        return UUID

    png = base64.b64encode(b"\x89PNG fake").decode()
    limpo, _ = core.sanear_html(f'<img src="data:image/png;base64,{png}">', guardar_imagem=guardar)
    assert guardadas == [("image/png", b"\x89PNG fake")]
    assert f'data-arquivo="{UUID}"' in limpo and "base64" not in limpo


def test_validar_ficha():
    f, erro = core.validar_ficha({"numero": "49", "resp_teste_id": 2, "inicio": "2026-09-12",
                                  "termino": "2026-09-14", "resultado": "aprovado"}, {2})
    assert erro is None and f["resp_teste_id"] == 2 and f["resultado"] == "aprovado"
    assert core.validar_ficha({"resp_teste_id": 99}, {2})[1]
    assert core.validar_ficha({"inicio": "12/09/2026"}, set())[1]
    assert core.validar_ficha({"inicio": "2026-09-14", "termino": "2026-09-12"}, set())[1]
    assert core.validar_ficha({"resultado": "talvez"}, set())[1]


def test_proximo_numero_teste_entende_os_formatos_do_l037():
    assert core.proximo_numero_teste(["Teste 47", "62", "T-048", None, ""]) == "63"
    assert core.proximo_numero_teste([]) == "1"


# ══════════════════════════════════════════════════════════════════════════════
# API — cadernos e permissão
# ══════════════════════════════════════════════════════════════════════════════

def test_modelo_projeto_pdr_cria_as_secoes_das_fases(client, tecnico_token, area_pdr):
    cad = _criar_caderno(client, tecnico_token)
    nomes = [n["nome"] for n in _arvore(client, tecnico_token, cad)["nos"]]
    assert nomes[0] == "Desenvolvimento" and "Estabilidade" in nomes and len(nomes) == 7


def test_leitura_nao_cria_caderno(client, leitura_token, area_pdr):
    res = client.post("/cadernos/api/cadernos", json={"area": "pdr", "nome": "x"}, headers=H(leitura_token))
    assert res.status_code == 403


def test_sem_a_area_nao_enxerga(client, tecnico_token, gestor_token, area_pdr):
    cad = _criar_caderno(client, tecnico_token)
    u = User.query.filter_by(email="gestor@test.com").first()
    u.areas = ""
    db.session.commit()
    assert client.get(f"/cadernos/api/cadernos/{cad}/arvore", headers=H(gestor_token)).status_code == 404
    assert client.get("/cadernos/api/meta?area=pdr", headers=H(gestor_token)).status_code == 403


def test_caderno_privado_so_para_membros(client, tecnico_token, gestor_token, area_pdr):
    cad = _criar_caderno(client, tecnico_token, acesso_area="nenhum")
    assert client.get(f"/cadernos/api/cadernos/{cad}/arvore", headers=H(gestor_token)).status_code == 404
    gestor = User.query.filter_by(email="gestor@test.com").first()
    res = client.put(f"/cadernos/api/cadernos/{cad}/membros",
                     json={"membros": [{"user_id": gestor.id, "papel": "leitor"}]}, headers=H(tecnico_token))
    assert res.status_code == 200
    assert _arvore(client, gestor_token, cad)["caderno"]["papel"] == "leitor"


# ══════════════════════════════════════════════════════════════════════════════
# API — páginas, trava e versões
# ══════════════════════════════════════════════════════════════════════════════

def test_registro_de_teste_nasce_com_ficha_e_estrutura(client, tecnico_token, area_pdr):
    cad = _criar_caderno(client, tecnico_token)
    p = _nova_pagina(client, tecnico_token, _secao(client, tecnico_token, cad), tipo="registro_teste")
    assert p["ficha"]["numero"] == "1" and p["ficha"]["resultado"] == "em_andamento"
    assert "Materiais e métodos" in p["html"] and "Número de série" in p["html"]
    p2 = _nova_pagina(client, tecnico_token, _secao(client, tecnico_token, cad), tipo="registro_teste")
    assert p2["ficha"]["numero"] == "2"


def test_trava_de_edicao_completa(client, tecnico_token, gestor_token, area_pdr):
    cad = _criar_caderno(client, tecnico_token)
    p = _nova_pagina(client, tecnico_token, _secao(client, tecnico_token, cad))
    url = f"/cadernos/api/paginas/{p['uuid']}"

    # Gravar sem a trava não pode.
    assert client.put(url, json={"versao_base": 1, "html": "<p>x</p>"}, headers=H(tecnico_token)).status_code == 409

    assert client.post(url + "/edicao", headers=H(tecnico_token)).status_code == 200
    # Outra pessoa (mesmo sendo dona via gestor) bate na trava.
    res = client.post(url + "/edicao", headers=H(gestor_token))
    assert res.status_code == 423 and res.get_json()["editando"]["por"] == "Tecnico Test"
    assert client.put(url, json={"versao_base": 1, "html": "<p>y</p>"}, headers=H(gestor_token)).status_code == 423

    res = client.put(url, json={"versao_base": 1, "titulo": "Teste 1", "html": "<p>a<script>x</script></p>"},
                     headers=H(tecnico_token))
    assert res.status_code == 200 and res.get_json()["versao"] == 2
    assert "<script>" not in CadernoPagina.query.filter_by(uuid=p["uuid"]).first().conteudo_html
    # Versão velha é recusada.
    assert client.put(url, json={"versao_base": 1, "html": "<p>b</p>"}, headers=H(tecnico_token)).status_code == 409

    assert client.delete(url + "/edicao", headers=H(tecnico_token)).status_code == 200
    vs = client.get(url + "/versoes", headers=H(tecnico_token)).get_json()["versoes"]
    assert [v["versao"] for v in vs] == [2, 1]          # antes e depois da sessão


def test_trava_expirada_e_liberada(client, tecnico_token, gestor_token, area_pdr):
    cad = _criar_caderno(client, tecnico_token)
    p = _nova_pagina(client, tecnico_token, _secao(client, tecnico_token, cad))
    url = f"/cadernos/api/paginas/{p['uuid']}"
    client.post(url + "/edicao", headers=H(tecnico_token))
    pag = CadernoPagina.query.filter_by(uuid=p["uuid"]).first()
    pag.editando_ate = datetime.now() - timedelta(seconds=1)
    db.session.commit()
    assert client.post(url + "/edicao", headers=H(gestor_token)).status_code == 200


def test_dono_toma_a_edicao(client, tecnico_token, gestor_token, area_pdr):
    cad = _criar_caderno(client, gestor_token)
    p = _nova_pagina(client, gestor_token, _secao(client, gestor_token, cad))
    url = f"/cadernos/api/paginas/{p['uuid']}"
    assert client.post(url + "/edicao", headers=H(tecnico_token)).status_code == 200
    assert client.post(url + "/edicao/tomar", headers=H(tecnico_token)).status_code == 403
    assert client.post(url + "/edicao/tomar", headers=H(gestor_token)).status_code == 200
    # O técnico perdeu a trava.
    assert client.put(url, json={"versao_base": 1, "html": "<p>x</p>"}, headers=H(tecnico_token)).status_code == 423


def test_leitura_le_mas_nao_edita(client, tecnico_token, leitura_token, area_pdr):
    cad = _criar_caderno(client, tecnico_token)
    p = _nova_pagina(client, tecnico_token, _secao(client, tecnico_token, cad))
    assert client.get(f"/cadernos/api/paginas/{p['uuid']}", headers=H(leitura_token)).status_code == 200
    assert client.post(f"/cadernos/api/paginas/{p['uuid']}/edicao", headers=H(leitura_token)).status_code == 403


def test_restaurar_versao_guarda_o_estado_atual_antes(client, tecnico_token, area_pdr):
    cad = _criar_caderno(client, tecnico_token)
    p = _nova_pagina(client, tecnico_token, _secao(client, tecnico_token, cad))
    url = f"/cadernos/api/paginas/{p['uuid']}"
    client.post(url + "/edicao", headers=H(tecnico_token))
    client.put(url, json={"versao_base": 1, "html": "<p>segunda</p>"}, headers=H(tecnico_token))
    client.delete(url + "/edicao", headers=H(tecnico_token))
    res = client.post(url + "/versoes/1/restaurar", headers=H(tecnico_token))
    assert res.status_code == 200
    assert res.get_json()["pagina"]["versao"] == 3
    vs = [v["versao"] for v in client.get(url + "/versoes", headers=H(tecnico_token)).get_json()["versoes"]]
    assert vs == [3, 2, 1]


def test_mover_pagina_leva_a_subpagina(client, tecnico_token, area_pdr):
    cad = _criar_caderno(client, tecnico_token)
    sec = _secao(client, tecnico_token, cad)
    p1 = _nova_pagina(client, tecnico_token, sec, titulo="P1")
    p2 = _nova_pagina(client, tecnico_token, sec, titulo="P2", subpagina_de=p1["uuid"])
    p3 = _nova_pagina(client, tecnico_token, sec, titulo="P3")
    res = client.post(f"/cadernos/api/paginas/{p1['uuid']}/mover",
                      json={"secao_uuid": sec, "apos_uuid": p3["uuid"]}, headers=H(tecnico_token))
    assert res.status_code == 200
    pags = [p for p in _arvore(client, tecnico_token, cad)["paginas"]]
    pags.sort(key=lambda x: x["ordem"])
    assert [(p["titulo"], p["nivel"]) for p in pags] == [("P3", 1), ("P1", 1), ("P2", 2)]
    assert p2  # usado


def test_lixeira_e_restauracao_de_pagina(client, tecnico_token, area_pdr):
    cad = _criar_caderno(client, tecnico_token)
    p = _nova_pagina(client, tecnico_token, _secao(client, tecnico_token, cad), titulo="Some")
    assert client.delete(f"/cadernos/api/paginas/{p['uuid']}", headers=H(tecnico_token)).status_code == 200
    assert client.get(f"/cadernos/api/paginas/{p['uuid']}", headers=H(tecnico_token)).status_code == 404
    itens = client.get(f"/cadernos/api/lixeira?caderno={cad}", headers=H(tecnico_token)).get_json()["itens"]
    assert any(i["uuid"] == p["uuid"] for i in itens)
    assert client.post(f"/cadernos/api/paginas/{p['uuid']}/restaurar", headers=H(tecnico_token)).status_code == 200
    assert client.get(f"/cadernos/api/paginas/{p['uuid']}", headers=H(tecnico_token)).status_code == 200


def test_busca_sem_acento(client, tecnico_token, area_pdr):
    cad = _criar_caderno(client, tecnico_token)
    p = _nova_pagina(client, tecnico_token, _secao(client, tecnico_token, cad), titulo="Extração")
    url = f"/cadernos/api/paginas/{p['uuid']}"
    client.post(url + "/edicao", headers=H(tecnico_token))
    client.put(url, json={"versao_base": 1, "html": "<p>Curva de amplificação do CMV</p>"}, headers=H(tecnico_token))
    res = client.get("/cadernos/api/busca?area=pdr&q=amplificacao cmv", headers=H(tecnico_token)).get_json()
    assert [r["uuid"] for r in res["resultados"]] == [p["uuid"]]


# ══════════════════════════════════════════════════════════════════════════════
# API — arquivos
# ══════════════════════════════════════════════════════════════════════════════

def _envia(client, token, cad, escopo, ref, nome, conteudo=b"dados"):
    return client.post("/cadernos/api/arquivos", data={
        "caderno": cad, "escopo": escopo, "ref": ref, "arquivo": (io.BytesIO(conteudo), nome)},
        content_type="multipart/form-data", headers=H(token))


def test_qualquer_extensao_entra_e_desce_como_download(client, tecnico_token, area_pdr):
    cad = _criar_caderno(client, tecnico_token)
    p = _nova_pagina(client, tecnico_token, _secao(client, tecnico_token, cad))
    for nome in ("corrida_0912.tlpd", "pagina.html", "analise.exe"):
        res = _envia(client, tecnico_token, cad, "pagina", p["uuid"], nome, b"<script>alert(1)</script>")
        assert res.status_code == 201, res.get_json()
        uuid_ = res.get_json()["arquivo"]["uuid"]
        baixa = client.get(f"/cadernos/api/arquivos/{uuid_}/conteudo", headers=H(tecnico_token))
        assert baixa.status_code == 200
        assert baixa.headers["Content-Type"].startswith("application/octet-stream")
        assert baixa.headers["Content-Disposition"].startswith("attachment")


def test_imagem_e_pdf_podem_abrir_no_navegador(client, tecnico_token, area_pdr):
    cad = _criar_caderno(client, tecnico_token)
    uuid_ = _envia(client, tecnico_token, cad, "caderno", "", "laudo.pdf", b"%PDF-1.4").get_json()["arquivo"]["uuid"]
    baixa = client.get(f"/cadernos/api/arquivos/{uuid_}/conteudo", headers=H(tecnico_token))
    assert baixa.headers["Content-Type"] == "application/pdf"
    assert baixa.headers["Content-Disposition"].startswith("inline")


def test_token_na_query_string_serve_imagem(client, tecnico_token, area_pdr):
    """<img> não manda cabeçalho: o src carrega o token em ?token=."""
    cad = _criar_caderno(client, tecnico_token)
    uuid_ = _envia(client, tecnico_token, cad, "caderno", "", "gel.png", b"\x89PNG").get_json()["arquivo"]["uuid"]
    assert client.get(f"/cadernos/api/arquivos/{uuid_}/conteudo?token={tecnico_token}").status_code == 200
    assert client.get(f"/cadernos/api/arquivos/{uuid_}/conteudo").status_code == 401


def test_qualquer_extensao_nao_vaza_para_outras_rotas(client, admin_token):
    """A exceção é do módulo Cadernos: o anexo de equipamento continua com allowlist."""
    from models import Equipamento
    e = Equipamento(nome="Extracta 16", sku="SKU-EX16", ativo=True)
    db.session.add(e)
    db.session.commit()
    res = client.post(f"/api/equipamentos/{e.id}/anexos", data={
        "arquivo": (io.BytesIO(b"x"), "corrida.tlpd"), "categoria": "agregado"},
        content_type="multipart/form-data", headers=H(admin_token))
    assert res.status_code == 415


def test_nova_versao_mantem_a_anterior_baixavel(client, tecnico_token, area_pdr):
    cad = _criar_caderno(client, tecnico_token)
    v1 = _envia(client, tecnico_token, cad, "caderno", "", "analise_placa.exe", b"v1").get_json()["arquivo"]
    res = client.post(f"/cadernos/api/arquivos/{v1['uuid']}/versao", data={
        "arquivo": (io.BytesIO(b"v2"), "analise_placa.exe")},
        content_type="multipart/form-data", headers=H(tecnico_token))
    assert res.status_code == 201 and res.get_json()["arquivo"]["versao"] == 2
    lista = client.get(f"/cadernos/api/arquivos?caderno={cad}&escopo=caderno", headers=H(tecnico_token)).get_json()
    assert [a["versao"] for a in lista["arquivos"]] == [2]
    assert client.get(f"/cadernos/api/arquivos/{v1['uuid']}/conteudo", headers=H(tecnico_token)).data == b"v1"


def test_imagem_do_editor_e_gravada_sem_token(client, tecnico_token, area_pdr):
    cad = _criar_caderno(client, tecnico_token)
    p = _nova_pagina(client, tecnico_token, _secao(client, tecnico_token, cad))
    url = f"/cadernos/api/paginas/{p['uuid']}"
    up = client.post(url + "/imagens", data={"upload": (io.BytesIO(b"\x89PNG"), "gel.png")},
                     content_type="multipart/form-data", headers=H(tecnico_token))
    assert up.status_code == 201
    img = up.get_json()["uuid"]
    client.post(url + "/edicao", headers=H(tecnico_token))
    png = base64.b64encode(b"\x89PNG colada").decode()
    client.put(url, json={"versao_base": 1, "html":
                          f'<img src="/cadernos/api/arquivos/{img}/conteudo?token={tecnico_token}">'
                          f'<img src="data:image/png;base64,{png}">'}, headers=H(tecnico_token))
    html = CadernoPagina.query.filter_by(uuid=p["uuid"]).first().conteudo_html
    assert tecnico_token not in html and "base64" not in html
    assert html.count("data-arquivo=") == 2
    assert CadernoArquivo.query.filter_by(embutido=True).count() == 2


def test_blob_do_caderno_conta_para_o_orfao_e_sai_na_purga(client, tecnico_token, area_pdr):
    from documentos import _sha_orfao
    from cadernos import purgar_lixeira
    cad = _criar_caderno(client, tecnico_token)
    a = _envia(client, tecnico_token, cad, "caderno", "", "dados.csv", b"conteudo unico").get_json()["arquivo"]
    linha = CadernoArquivo.query.filter_by(uuid=a["uuid"]).first()
    assert not _sha_orfao(linha.sha256)
    assert client.delete(f"/cadernos/api/arquivos/{a['uuid']}", headers=H(tecnico_token)).status_code == 200
    assert arquivos_store.existe(linha.sha256)      # na lixeira, o blob fica
    contagem = purgar_lixeira(agora=datetime.now() + timedelta(days=61))
    assert contagem["arquivos"] == 1 and contagem["blobs"] == 1
    assert not arquivos_store.existe(linha.sha256)


def test_purga_apaga_pagina_e_versoes(client, tecnico_token, area_pdr):
    from cadernos import purgar_lixeira
    cad = _criar_caderno(client, tecnico_token)
    p = _nova_pagina(client, tecnico_token, _secao(client, tecnico_token, cad))
    client.delete(f"/cadernos/api/paginas/{p['uuid']}", headers=H(tecnico_token))
    pid = CadernoPagina.query.filter_by(uuid=p["uuid"]).first().id
    assert CadernoPaginaVersao.query.filter_by(pagina_id=pid).count() == 1
    assert purgar_lixeira(agora=datetime.now() + timedelta(days=30))["paginas"] == 0
    assert purgar_lixeira(agora=datetime.now() + timedelta(days=61))["paginas"] == 1
    assert CadernoPagina.query.filter_by(uuid=p["uuid"]).first() is None
    assert CadernoPaginaVersao.query.filter_by(pagina_id=pid).count() == 0
    assert Caderno.query.filter_by(uuid=cad).first() is not None
