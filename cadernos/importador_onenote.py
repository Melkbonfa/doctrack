"""
cadernos/importador_onenote.py — Converte uma página do OneNote (XML 2013, como a
API COM devolve) no HTML do módulo Cadernos. Puro: sem Flask e sem banco.

Quem usa: cadernos/importacao.py (a tela "Importar do OneNote" e o
scripts/importar_onenote.py), que lê o pacote gerado pelo extrator
(scripts/onenote/extrair_onenote.ps1) e grava no banco.

As regras abaixo saíram do caderno L-037 (inventário de 2026-10-05,
docs/planos/PLANO_cadernos.md seção 2.12), não da especificação em abstrato:

  * **Seções do modelo viram títulos.** No "Modelo de Registro de Teste" as
    seções são itens de lista NUMERADA, em MAIÚSCULAS, no nível de topo
    ("1. DESCRIÇÃO DETALHADA") e as subseções são parágrafos "2.1 …". Como
    lista, o relatório para a liderança não teria estrutura; como <h2>/<h3>, tem.
  * **Cabeçalho do registro vira ficha.** A tabela de uma coluna com "Projeto:",
    "Número do teste:", responsáveis e datas sai do corpo e vira `ficha`.
  * **Tabela mantém a cor de cada célula** (`shadingColor`) e a largura relativa
    das colunas: 12% das células do L-037 são coloridas, e a cor tem significado
    (grupos de amostra num mapa de placa).
  * **Realce do OneNote** (`mso-highlight`) vira `<mark class="marker-…">` nas
    seis cores que o editor oferece.
  * **Arquivo inserido na página vira anexo no texto**, no mesmo lugar: o link
    `<a data-arquivo>` que o editor também cria (o arquivo vem do pacote).
  * **Nada some em silêncio**: o que não converte (tinta, formato de imagem que
    o navegador não abre) vira aviso na página e no relatório da importação.
"""
import base64
import binascii
import hashlib
import html
import os
import re
import uuid as _uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser

from utils import norm

from . import core

NS = "{http://schemas.microsoft.com/office/onenote/2013/onenote}"

# Cores de realce do OneNote → classes do editor (static/cadernos.css).
MARCADORES = {"yellow": "marker-yellow", "lime": "marker-lime", "fuchsia": "marker-fuchsia",
              "magenta": "marker-fuchsia", "red": "marker-red", "aqua": "marker-aqua",
              "cyan": "marker-aqua", "silver": "marker-silver", "gray": "marker-silver"}
# Cor de texto que é o padrão e não precisa virar estilo.
_COR_PADRAO = {"black", "#000000", "#000", "windowtext", "automatic", "auto"}

PT_PARA_PX = 96 / 72


@dataclass
class ImagemImportada:
    uuid: str
    dados: bytes
    mime: str
    ext: str
    ocr: str = ""
    alt: str = ""


@dataclass
class AnexoImportado:
    """Arquivo inserido na página do OneNote (Inserir › Arquivo, gravação de
    áudio/vídeo). O XML só traz o caminho do cache local do OneNote; o extrator
    copia esse cache para `anexos/` do pacote e o manifesto liga os dois pelo
    `cache`. No HTML vira o mesmo link de anexo que o editor cria."""
    uuid: str
    nome: str
    cache: str = ""
    origem: str = ""


@dataclass
class PaginaImportada:
    titulo: str
    tipo: str
    html: str
    ficha: dict
    data_pagina: datetime | None
    modificado: datetime | None
    criado: datetime | None
    autores: list
    imagens: list = field(default_factory=list)
    anexos: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    tabelas: int = 0
    tinta: int = 0
    links_externos: int = 0

    @property
    def texto_ocr(self):
        return " ".join(i.ocr for i in self.imagens if i.ocr)


# ── datas ────────────────────────────────────────────────────────────────────

def data_local(valor):
    """'2026-01-07T12:51:21.000Z' (UTC) → datetime local sem fuso, como o resto
    do repositório guarda."""
    if not valor:
        return None
    try:
        dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().replace(tzinfo=None)


def _data_br(texto):
    """'12/09/2025', '12/09/25', '12.09.2025' → '2025-09-12'. None se não der."""
    m = re.search(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", texto or "")
    if not m:
        return None
    d, mth, a = (int(x) for x in m.groups())
    if a < 100:
        a += 2000
    try:
        return datetime(a, mth, d).strftime("%Y-%m-%d")
    except ValueError:
        return None


def chave_origem(*partes):
    """Chave estável para reimportar. O ID do OneNote muda quando o caderno é
    reaberto de outro lugar (cópia local × SharePoint), então não serve."""
    return "onenote:" + hashlib.sha1("\x1f".join(str(p or "") for p in partes).encode("utf-8")).hexdigest()


def autor_limpo(nome):
    """O L-037 tem a mesma pessoa como 'Fulana' e 'Fulana [Loccus]'."""
    return re.sub(r"\s*\[[^\]]*\]\s*$", "", (nome or "").strip())


# ── texto inline (o CDATA do one:T) ──────────────────────────────────────────

class _Inline(HTMLParser):
    """Converte os <span style=…> do OneNote em marcação semântica.

    O saneador do Cadernos só deixa passar `color` e `background-color` em
    estilo; negrito, itálico, sublinhado, tachado e sobrescrito precisam virar
    tag, senão sumiriam.
    """

    # Tags cujo CONTEÚDO some junto (mesma regra do saneador em core.py).
    _SOME = {"script", "style", "iframe", "object", "embed", "svg", "math", "template", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.saida = []
        self.pilha = []
        self.pular = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SOME:
            self.pular += 1
            return
        if self.pular:
            return
        a = dict(attrs)
        if tag == "span":
            estilo = {}
            for decl in (a.get("style") or "").split(";"):
                if ":" in decl:
                    k, v = decl.split(":", 1)
                    estilo[k.strip().lower()] = v.strip().lower()
            abrir = []
            if estilo.get("font-weight") in ("bold", "700", "800", "900"):
                abrir.append(("strong", ""))
            if estilo.get("font-style") == "italic":
                abrir.append(("i", ""))
            deco = estilo.get("text-decoration", "")
            if "underline" in deco:
                abrir.append(("u", ""))
            if "line-through" in deco:
                abrir.append(("s", ""))
            va = estilo.get("vertical-align", "")
            if va == "super":
                abrir.append(("sup", ""))
            elif va == "sub":
                abrir.append(("sub", ""))
            realce = estilo.get("mso-highlight")
            if realce and realce in MARCADORES:
                abrir.append(("mark", f' class="{MARCADORES[realce]}"'))
            elif estilo.get("background") and estilo["background"] not in ("transparent", "none", "white", "#ffffff"):
                abrir.append(("span", f' style="background-color:{html.escape(estilo["background"])}"'))
            cor = estilo.get("color")
            if cor and cor not in _COR_PADRAO:
                abrir.append(("span", f' style="color:{html.escape(cor)}"'))
            for t, at in abrir:
                self.saida.append(f"<{t}{at}>")
            self.pilha.append([t for t, _ in abrir])
        elif tag == "a":
            href = a.get("href") or ""
            self.saida.append(f'<a href="{html.escape(href, quote=True)}">')
            self.pilha.append(["a"])
        elif tag == "br":
            self.saida.append("<br>")
        elif tag in ("b", "strong", "i", "em", "u", "s", "sup", "sub"):
            self.saida.append(f"<{tag}>")
            self.pilha.append([tag])
        else:
            self.pilha.append([])

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.saida.append("<br>")

    def handle_endtag(self, tag):
        if tag in self._SOME:
            self.pular = max(0, self.pular - 1)
            return
        if self.pular:
            return
        if tag in ("span", "a", "b", "strong", "i", "em", "u", "s", "sup", "sub") and self.pilha:
            for t in reversed(self.pilha.pop()):
                self.saida.append(f"</{t}>")

    def handle_data(self, data):
        if not self.pular:
            self.saida.append(html.escape(data, quote=False))

    def resultado(self):
        while self.pilha:
            for t in reversed(self.pilha.pop()):
                self.saida.append(f"</{t}>")
        return "".join(self.saida)


def inline(cdata):
    p = _Inline()
    p.feed(cdata or "")
    p.close()
    return p.resultado().strip()


def texto_plano(cdata):
    return html.unescape(re.sub(r"<[^>]+>", "", cdata or "")).replace("\xa0", " ").strip()


# ── conversão de blocos ──────────────────────────────────────────────────────

def _tipo_imagem(dados):
    if dados[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", ".png"
    if dados[:3] == b"\xff\xd8\xff":
        return "image/jpeg", ".jpg"
    if dados[:4] == b"GIF8":
        return "image/gif", ".gif"
    if dados[:4] == b"RIFF" and dados[8:12] == b"WEBP":
        return "image/webp", ".webp"
    if dados[:2] == b"BM":
        return "image/bmp", ".bmp"
    return None, None


class _Conversor:
    def __init__(self):
        self.imagens = []
        self.anexos = []
        self.avisos = []
        self.tabelas = 0
        self.tinta = 0
        self.links_externos = 0
        self.autores = {}            # nome limpo → primeira criação (para ordenar)

    # autores de cada OE
    def _autoria(self, oe):
        for attr in ("author", "lastModifiedBy"):
            nome = autor_limpo(oe.get(attr))
            if nome:
                quando = oe.get("creationTime") or oe.get("lastModifiedTime") or "9999"
                if nome not in self.autores or quando < self.autores[nome]:
                    self.autores[nome] = quando

    @staticmethod
    def _numero(oe):
        lst = oe.find(NS + "List")
        if lst is None:
            return None
        n = lst.find(NS + "Number")
        return (n.get("text") or "").strip() if n is not None else None

    def _e_titulo(self, oe, nivel):
        """(tag, texto) se o OE é uma seção do modelo; senão None."""
        if nivel != 0:
            return None
        t = oe.find(NS + "T")
        texto = texto_plano(t.text if t is not None else "")
        if not texto or len(texto) > 80:
            return None
        numero = self._numero(oe)
        letras = [c for c in texto if c.isalpha()]
        if numero and letras and texto == texto.upper() and len(texto) <= 70:
            return "h2", f"{numero} {texto}".strip()
        if self._numero(oe) is None and oe.find(NS + "List") is None \
                and re.match(r"^\d+\.\d+(\.\d+)?\s+\S", texto):
            return "h3", texto
        return None

    def oes(self, filhos, nivel):
        """Renderiza uma sequência de OEs, agrupando os itens de lista.

        `filhos` é um elemento OEChildren ou uma LISTA deles: o esquema 2013
        permite vários OEChildren seguidos no mesmo pai (Outline ou OE), e ler só
        o primeiro perdia 73 imagens e 23 tabelas do L-037.
        """
        if filhos is None:
            return []
        if isinstance(filhos, list):
            itens = [oe for f in filhos for oe in f.findall(NS + "OE")]
        else:
            itens = filhos.findall(NS + "OE")
        saida, i = [], 0
        while i < len(itens):
            oe = itens[i]
            lst = oe.find(NS + "List")
            if lst is not None and not self._e_titulo(oe, nivel):
                tipo = "ol" if lst.find(NS + "Number") is not None else "ul"
                grupo = []
                while i < len(itens):
                    o = itens[i]
                    lo = o.find(NS + "List")
                    if lo is None or self._e_titulo(o, nivel):
                        break
                    if ("ol" if lo.find(NS + "Number") is not None else "ul") != tipo:
                        break
                    grupo.append(o)
                    i += 1
                saida.append(self.lista(tipo, grupo, nivel))
                continue
            saida.extend(self.oe(oe, nivel))
            i += 1
        return saida

    def lista(self, tipo, itens, nivel):
        inicio = ""
        if tipo == "ol":
            m = re.match(r"(\d+)", self._numero(itens[0]) or "")
            if m and m.group(1) != "1":
                inicio = f' start="{m.group(1)}"'
        partes = [f"<{tipo}{inicio}>"]
        for oe in itens:
            self._autoria(oe)
            t = oe.find(NS + "T")
            conteudo = inline(t.text if t is not None else "")
            extra = self._conteudo_nao_texto(oe)
            filhos = "".join(self.oes(oe.findall(NS + "OEChildren"), nivel + 1))
            partes.append(f"<li>{conteudo}{extra}{filhos}</li>")
        partes.append(f"</{tipo}>")
        return "".join(partes)

    def _conteudo_nao_texto(self, oe):
        partes = []
        tabela = oe.find(NS + "Table")
        if tabela is not None:
            partes.append(self.tabela(tabela))
        for img in oe.findall(NS + "Image"):
            partes.append(self.imagem(img))
        for arq in oe.findall(NS + "InsertedFile") + oe.findall(NS + "MediaFile"):
            partes.append(self.anexo(arq))
        for tag in ("InkDrawing", "InkWord", "InkParagraph"):
            achados = oe.findall(NS + tag)
            if achados:
                self.tinta += len(achados)
                partes.append("<p><mark class=\"marker-silver\">[desenho à mão do OneNote — ver o PDF "
                              "original nos arquivos da página]</mark></p>")
        return "".join(partes)

    def oe(self, oe, nivel):
        self._autoria(oe)
        titulo = self._e_titulo(oe, nivel)
        if titulo:
            tag, texto = titulo
            return [f"<{tag}>{html.escape(texto)}</{tag}>"] + self.oes(oe.findall(NS + "OEChildren"), 0)
        saida = []
        t = oe.find(NS + "T")
        if t is not None:
            conteudo = inline(t.text)
            estilos = []
            if nivel > 0:
                estilos.append(f"margin-left:{40 * nivel}px")
            alinhamento = oe.get("alignment")
            if alinhamento in ("center", "right"):
                estilos.append(f"text-align:{alinhamento}")
            st = f' style="{";".join(estilos)}"' if estilos else ""
            saida.append(f"<p{st}>{conteudo}</p>" if conteudo else "<p></p>")
        extra = self._conteudo_nao_texto(oe)
        if extra:
            saida.append(extra)
        saida.extend(self.oes(oe.findall(NS + "OEChildren"), nivel + 1))
        return saida

    def tabela(self, tbl):
        self.tabelas += 1
        larguras = []
        for col in tbl.findall(NS + "Columns/" + NS + "Column"):
            try:
                larguras.append(float(col.get("width") or 0))
            except ValueError:
                larguras.append(0.0)
        total = sum(larguras) or 1
        colgroup = ""
        if larguras and all(larguras):
            colgroup = "<colgroup>" + "".join(
                f'<col style="width:{100 * w / total:.2f}%">' for w in larguras) + "</colgroup>"
        linhas = tbl.findall(NS + "Row")
        cabecalho = tbl.get("hasHeaderRow") == "true" and len(linhas) > 1

        def celula(cell, tag):
            conteudo = "".join(self.oes(cell.findall(NS + "OEChildren"), 0))
            conteudo = re.sub(r"^(<p></p>)+|(<p></p>)+$", "", conteudo)
            # Célula de um parágrafo só, sem estilo, grava sem <p> (como o CKEditor).
            if conteudo.startswith("<p>") and conteudo.endswith("</p>") and conteudo.count("<p") == 1:
                conteudo = conteudo[3:-4]
            cor = (cell.get("shadingColor") or "").strip()
            st = f' style="background-color:{cor}"' if cor and cor.lower() != "none" else ""
            return f"<{tag}{st}>{conteudo}</{tag}>"

        partes = ['<figure class="table"><table>', colgroup]
        corpo = linhas
        if cabecalho:
            partes.append("<thead><tr>" + "".join(celula(c, "th") for c in linhas[0].findall(NS + "Cell"))
                          + "</tr></thead>")
            corpo = linhas[1:]
        partes.append("<tbody>")
        for row in corpo:
            partes.append("<tr>" + "".join(celula(c, "td") for c in row.findall(NS + "Cell")) + "</tr>")
        partes.append("</tbody></table></figure>")
        return "".join(partes)

    def anexo(self, arq):
        nome = os.path.basename((arq.get("preferredName") or arq.get("pathSource") or "arquivo")
                                .replace("\\", "/")) or "arquivo"
        a = AnexoImportado(uuid=str(_uuid.uuid4()), nome=nome[:300],
                           cache=arq.get("pathCache") or "", origem=arq.get("pathSource") or "")
        self.anexos.append(a)
        return f'<p><a data-arquivo="{a.uuid}">{html.escape(a.nome)}</a></p>'

    def imagem(self, img):
        dado = img.find(NS + "Data")
        if dado is None or not (dado.text or "").strip():
            self.avisos.append("Imagem sem conteúdo no XML (o OneNote ainda não tinha baixado?).")
            return "<p><mark class=\"marker-silver\">[imagem não disponível na extração]</mark></p>"
        try:
            dados = base64.b64decode(re.sub(r"\s+", "", dado.text), validate=True)
        except (binascii.Error, ValueError):
            self.avisos.append("Imagem com base64 inválido.")
            return ""
        mime, ext = _tipo_imagem(dados)
        if mime is None or ext == ".bmp":
            self.avisos.append(f"Imagem em formato que o navegador não abre ({dados[:4]!r}); não importada.")
            return "<p><mark class=\"marker-silver\">[imagem em formato não suportado]</mark></p>"
        ocr_el = img.find(NS + "OCRData/" + NS + "OCRText")
        ocr = (ocr_el.text or "").strip() if ocr_el is not None else ""
        alt = (img.get("alt") or "").strip()[:200]
        uid = str(_uuid.uuid4())
        self.imagens.append(ImagemImportada(uuid=uid, dados=dados, mime=mime, ext=ext, ocr=ocr, alt=alt))
        largura = ""
        tam = img.find(NS + "Size")
        if tam is not None:
            try:
                px = round(float(tam.get("width") or 0) * PT_PARA_PX)
                if px > 0:
                    largura = f' style="width:{px}px"'
            except ValueError:
                pass
        classes = "image image_resized" if largura else "image"
        return (f'<figure class="{classes}"{largura}>'
                f'<img data-arquivo="{uid}" alt="{html.escape(alt, quote=True)}"></figure>')


# ── ficha do registro de teste ───────────────────────────────────────────────

_ROTULOS_FICHA = {
    "projeto": "projeto",
    "numero do teste": "numero",
    "responsavel pelo teste": "resp_teste_nome",
    "responsavel pela execucao": "resp_execucao_nome",
    "data de inicio": "inicio",
    "data de termino": "termino",
}


def _ficha_da_tabela(tbl):
    """(ficha, linhas_aproveitadas) se a tabela é o cabeçalho do registro; senão
    (None, []).

    Só as linhas cujo valor foi TODO aproveitado na ficha saem do corpo. O resto
    fica — no L-037 o cabeçalho tem a linha "Arquivos relacionados:" com os links
    para os arquivos de corrida, e tirar a tabela inteira perdia 46 links.
    """
    linhas = tbl.findall(NS + "Row")
    if not linhas:
        return None, []
    pares, por_chave = {}, {}
    for row in linhas:
        if row.find(".//" + NS + "Image") is not None or row.find(".//" + NS + "Table") is not None:
            continue
        cdata = " ".join((t.text or "") for t in row.iter(NS + "T"))
        if "<a " in cdata:              # link não cabe na ficha
            continue
        texto = texto_plano(cdata)
        if ":" not in texto:
            continue
        rotulo, valor = texto.split(":", 1)
        chave = _ROTULOS_FICHA.get(norm(rotulo).strip())
        if chave:
            pares[chave] = valor.strip()
            por_chave[chave] = row
    if "projeto" not in pares or "numero" not in pares:
        return None, []
    ficha = {"projeto": pares.get("projeto", "")[:80], "numero": pares.get("numero", "")[:40],
             "resp_teste_id": None, "resp_execucao_id": None,
             "resp_teste_nome": pares.get("resp_teste_nome", "")[:120],
             "resp_execucao_nome": pares.get("resp_execucao_nome", "")[:120],
             "inicio": "", "termino": "", "resultado": ""}
    aproveitadas = [por_chave[k] for k in ("projeto", "numero", "resp_teste_nome", "resp_execucao_nome")
                    if k in por_chave]
    for campo in ("inicio", "termino"):
        bruto = pares.get(campo, "")
        iso = _data_br(bruto) if bruto else ""
        if iso is not None:              # vazio ou convertido: a linha pode sair
            ficha[campo] = iso
            if campo in por_chave:
                aproveitadas.append(por_chave[campo])
    return ficha, aproveitadas


# ── página ───────────────────────────────────────────────────────────────────

def converter_pagina(xml_texto):
    """XML de uma página → PaginaImportada (HTML ainda não gravado, imagens em memória)."""
    raiz = ET.fromstring(xml_texto)
    conv = _Conversor()

    titulo = (raiz.get("name") or "").strip()
    if not titulo:
        t = raiz.find(NS + "Title/" + NS + "OE/" + NS + "T")
        titulo = texto_plano(t.text) if t is not None else ""

    # Caixas de conteúdo na ordem de leitura: de cima para baixo, depois da
    # esquerda para a direita. Caixas lado a lado ficam uma embaixo da outra.
    outlines = []
    for o in raiz.findall(NS + "Outline"):
        pos = o.find(NS + "Position")
        y = float(pos.get("y", 0)) if pos is not None else 0
        x = float(pos.get("x", 0)) if pos is not None else 0
        outlines.append((y, x, o))
    outlines.sort(key=lambda t: (t[0], t[1]))
    if len(outlines) > 1:
        conv.avisos.append(f"{len(outlines)} caixas de conteúdo na página foram empilhadas na ordem de leitura.")

    ficha, tipo = {}, "nota"
    blocos = []
    for _, _, o in outlines:
        filhos = o.findall(NS + "OEChildren")
        if not filhos:
            continue
        # O cabeçalho do registro é uma tabela perto do topo da primeira caixa.
        if not ficha:
            for oe in [x for f in filhos for x in f.findall(NS + "OE")][:6]:
                tbl = oe.find(NS + "Table")
                if tbl is None:
                    continue
                f, aproveitadas = _ficha_da_tabela(tbl)
                if f:
                    ficha, tipo = f, "registro_teste"
                    for row in aproveitadas:    # a ficha substitui estas linhas
                        tbl.remove(row)
                    if not tbl.findall(NS + "Row"):
                        oe.remove(tbl)
                    break
        blocos.extend(conv.oes(filhos, 0))

    # Conteúdo solto na página, fora de caixa: imagem, arquivo e TINTA ficam
    # direto sob <Page> no esquema 2013.
    for img in raiz.findall(NS + "Image"):
        blocos.append(conv.imagem(img))
    for arq in raiz.findall(NS + "InsertedFile") + raiz.findall(NS + "MediaFile"):
        blocos.append(conv.anexo(arq))
    tinta = len(raiz.findall(NS + "InkDrawing"))
    if tinta:
        conv.tinta += tinta
        blocos.insert(0, "<p><mark class=\"marker-silver\">[esta página tem desenho à mão do OneNote — "
                         "ver o PDF original nos arquivos da página]</mark></p>")

    corpo = "".join(blocos)
    corpo = re.sub(r"(<p></p>){2,}", "<p></p>", corpo)          # linhas em branco seguidas
    corpo = re.sub(r"^(<p></p>)+|(<p></p>)+$", "", corpo)
    limpo, refs = core.sanear_html(corpo)
    esperadas = {i.uuid for i in conv.imagens}
    if refs != esperadas:
        conv.avisos.append("Algumas imagens não sobreviveram ao saneamento do HTML.")
    conv.links_externos = len(re.findall(r'href="https?://', limpo))

    autores = [n for n, _ in sorted(conv.autores.items(), key=lambda kv: kv[1])]
    criado = min((v for v in conv.autores.values() if v and v != "9999"), default=None)
    return PaginaImportada(
        titulo=titulo[:300] or "Sem título", tipo=tipo, html=limpo, ficha=ficha,
        data_pagina=data_local(raiz.get("dateTime")), modificado=data_local(raiz.get("lastModifiedTime")),
        criado=data_local(criado), autores=autores, imagens=conv.imagens, anexos=conv.anexos,
        avisos=conv.avisos,
        tabelas=conv.tabelas, tinta=conv.tinta, links_externos=conv.links_externos,
    )
