"""Conversão OneNote (XML 2013) → HTML do módulo Cadernos.

XML SINTÉTICO, montado com a mesma forma do L-037 (nenhum dado real aqui). Cada
teste fixa uma regra que, quando faltou, perdeu conteúdo de verdade na primeira
importação do L-037:

  * vários OEChildren no mesmo pai (perdia 73 imagens e 23 tabelas);
  * linha "Arquivos relacionados:" no cabeçalho do registro (perdia 46 links);
  * tinta direto sob <Page> (as 3 páginas com desenho não eram sinalizadas).
"""
import base64

from cadernos.importador_onenote import (converter_pagina, chave_origem, autor_limpo,
                                         data_local, inline)

NS = 'xmlns:one="http://schemas.microsoft.com/office/onenote/2013/onenote"'
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 32).decode()


def T(cdata):
    return f"<one:T><![CDATA[{cdata}]]></one:T>"


def OE(conteudo, extra="", attrs='alignment="left"'):
    return f"<one:OE {attrs} author=\"Fulana [Loccus]\" creationTime=\"2026-01-07T12:00:00.000Z\">{extra}{conteudo}</one:OE>"


def pagina(*caixas, solto=""):
    outlines = "".join(
        f'<one:Outline><one:Position x="36" y="{86 + i}" z="0"/>{c}</one:Outline>' for i, c in enumerate(caixas))
    return (f'<?xml version="1.0"?><one:Page {NS} name="Teste 9 – Curva" '
            f'dateTime="2026-01-07T12:51:21.000Z" lastModifiedTime="2026-03-24T12:00:26.000Z" pageLevel="1">'
            f"{outlines}{solto}</one:Page>")


def filhos(*oes):
    return "<one:OEChildren>" + "".join(oes) + "</one:OEChildren>"


NUM = '<one:List><one:Number numberSequence="0" numberFormat="##." text="{n}"/></one:List>'
BUL = '<one:List><one:Bullet bullet="2"/></one:List>'


def celula(texto, cor=None):
    st = f' shadingColor="{cor}"' if cor else ""
    return f"<one:Cell{st}>{filhos(OE(T(texto)))}</one:Cell>"


def tabela(linhas, header=True, larguras=(100, 300)):
    cols = "".join(f'<one:Column index="{i}" width="{w}"/>' for i, w in enumerate(larguras))
    rows = "".join("<one:Row>" + "".join(linha) + "</one:Row>" for linha in linhas)
    return OE(f'<one:Table bordersVisible="true" hasHeaderRow="{"true" if header else "false"}">'
              f"<one:Columns>{cols}</one:Columns>{rows}</one:Table>")


def test_secoes_do_modelo_viram_titulos_e_passos_ficam_lista():
    xml = pagina(filhos(
        OE(T("<span style='font-weight:bold'>DESCRIÇÃO DETALHADA</span>"), extra=NUM.format(n="1."),
           ) .replace("</one:OE>", filhos(OE(T("Preparar a curva"), extra=BUL)) + "</one:OE>"),
        OE(T("2.1 Condições do laboratório")),
        OE(T("Adicionar 15 µL da mistura reacional para PCR previamente preparada aos poços"), extra=NUM.format(n="1.")),
        OE(T("Selar a placa"), extra=NUM.format(n="2.")),
    ))
    r = converter_pagina(xml)
    assert "<h2>1. DESCRIÇÃO DETALHADA</h2>" in r.html
    assert "<h3>2.1 Condições do laboratório</h3>" in r.html
    assert "<ul><li>Preparar a curva</li></ul>" in r.html
    assert "<ol><li>Adicionar 15 µL" in r.html and "<li>Selar a placa</li></ol>" in r.html


def test_formatacao_inline_do_onenote():
    h = inline("<span style='font-weight:bold'>forte</span> <span style='font-style:italic'>it</span> "
               "<span style='background:yellow;mso-highlight:yellow'>realce</span> "
               "Cy<span style='vertical-align:super'>5</span> "
               "<span style='color:#C00000'>vermelho</span> <span style='color:black'>preto</span>")
    assert "<strong>forte</strong>" in h and "<i>it</i>" in h
    assert '<mark class="marker-yellow">realce</mark>' in h
    assert "Cy<sup>5</sup>" in h
    assert 'style="color:#c00000"' in h
    assert "preto" in h and "color:black" not in h


def test_tabela_mantem_cor_da_celula_cabecalho_e_largura():
    r = converter_pagina(pagina(filhos(tabela([
        [celula("Reagente"), celula("Lote")],
        [celula("Mix", "#9BBB59"), celula("2410")],
    ]))))
    assert "<thead><tr><th>Reagente</th><th>Lote</th></tr></thead>" in r.html
    assert '<td style="background-color:#9BBB59">Mix</td>' in r.html
    assert '<col style="width:25.00%">' in r.html and '<col style="width:75.00%">' in r.html
    assert r.tabelas == 1


def test_cabecalho_do_registro_vira_ficha_e_preserva_a_linha_de_links():
    cab = tabela([
        [celula("<span style='font-weight:bold'>Projeto: </span>L-000 Kit demo")],
        [celula("<span style='font-weight:bold'>Número do teste: </span>56")],
        [celula("Responsável pelo teste: Fulana de Tal")],
        [celula("Data de início: 20/03/2026")],
        [celula("Data de término: 21/03/2026")],
        [celula('Arquivos relacionados: <a href="https://loccus.sharepoint.com/:u:/s/x/E1">corrida.tlpd</a>')],
    ], header=False, larguras=(375,))
    r = converter_pagina(pagina(filhos(cab, OE(T("corpo")))))
    assert r.tipo == "registro_teste"
    assert r.ficha["numero"] == "56" and r.ficha["projeto"] == "L-000 Kit demo"
    assert r.ficha["resp_teste_nome"] == "Fulana de Tal"
    assert (r.ficha["inicio"], r.ficha["termino"]) == ("2026-03-20", "2026-03-21")
    assert "Número do teste" not in r.html                       # linha aproveitada saiu
    assert 'href="https://loccus.sharepoint.com/:u:/s/x/E1"' in r.html   # o link ficou
    assert "corrida.tlpd" in r.html


def test_data_que_nao_converte_mantem_a_linha():
    cab = tabela([[celula("Projeto: X")], [celula("Número do teste: 1")],
                  [celula("Data de início: começo de março")]], header=False, larguras=(375,))
    r = converter_pagina(pagina(filhos(cab)))
    assert r.ficha["inicio"] == ""
    assert "começo de março" in r.html


def test_varios_oechildren_no_mesmo_pai_nao_perdem_conteudo():
    img = f'<one:Image><one:Size width="300" height="100"/><one:Data>{PNG}</one:Data></one:Image>'
    caixa = filhos(OE(T("primeiro bloco"))) + filhos(OE(img), OE(T("terceiro")))
    r = converter_pagina(pagina(caixa))
    assert "primeiro bloco" in r.html and "terceiro" in r.html
    assert len(r.imagens) == 1


def test_imagem_vira_referencia_com_ocr_e_largura():
    img = (f'<one:Image alt="gel"><one:Size width="300" height="100"/><one:Data>{PNG}</one:Data>'
           "<one:OCRData><one:OCRText><![CDATA[CMV 24,3]]></one:OCRText></one:OCRData></one:Image>")
    r = converter_pagina(pagina(filhos(OE(img))))
    i = r.imagens[0]
    assert i.mime == "image/png" and i.ocr == "CMV 24,3"
    assert f'data-arquivo="{i.uuid}"' in r.html
    assert 'style="width:400px"' in r.html                   # 300 pt → 400 px
    assert "base64" not in r.html


def test_tinta_solta_na_pagina_e_sinalizada():
    r = converter_pagina(pagina(filhos(OE(T("x"))), solto="<one:InkDrawing/>"))
    assert r.tinta == 1 and "desenho à mão" in r.html


def test_varias_caixas_viram_aviso_e_entram_em_ordem_de_leitura():
    r = converter_pagina(pagina(filhos(OE(T("de cima"))), filhos(OE(T("de baixo")))))
    assert r.html.index("de cima") < r.html.index("de baixo")
    assert any("caixas" in a for a in r.avisos)


def test_arquivo_inserido_vira_anexo_no_texto():
    arq = ('<one:InsertedFile pathCache="C:\\cache\\0A.bin" pathSource="C:\\dados\\placa.xlsx" '
           'preferredName="placa.xlsx"/>')
    r = converter_pagina(pagina(filhos(OE(T("antes")), OE(arq))))
    a = r.anexos[0]
    assert (a.nome, a.cache) == ("placa.xlsx", "C:\\cache\\0A.bin")
    assert f'<a data-arquivo="{a.uuid}">placa.xlsx</a>' in r.html
    assert r.html.index("antes") < r.html.index("placa.xlsx")
    assert not any("copiado à parte" in x for x in r.avisos)


def test_saneamento_vale_tambem_para_o_importado():
    r = converter_pagina(pagina(filhos(OE(T("a<script>alert(1)</script>b")))))
    assert "<script" not in r.html and "alert(1)" not in r.html


def test_metadados():
    r = converter_pagina(pagina(filhos(OE(T("x")))))
    assert r.titulo == "Teste 9 – Curva"
    assert r.autores == ["Fulana"]                            # sufixo [Loccus] removido
    assert r.data_pagina == data_local("2026-01-07T12:51:21.000Z")
    assert autor_limpo("Inaê C. [Loccus]") == "Inaê C."
    assert chave_origem("a", "b") == chave_origem("a", "b") != chave_origem("a", "c")
