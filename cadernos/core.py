"""
cadernos/core.py — Regra de negócio do módulo Cadernos. Puro: sem Flask, sem
`request`, sem sessão do banco. Testável isolado (tests/test_cadernos.py).

O que mora aqui:

  * níveis de página (subpáginas): invariantes, série, mover, promover/rebaixar;
  * papel efetivo de uma pessoa num caderno;
  * trava de edição;
  * ficha do "Registro de teste";
  * saneamento do HTML que o editor manda (a parte crítica de segurança);
  * modelos de caderno e de página.
"""
import base64
import binascii
import html
import json
import re
from datetime import timedelta
from html.parser import HTMLParser

from utils import norm


# ══════════════════════════════════════════════════════════════════════════════
# NÍVEIS DE PÁGINA (subpáginas)
# ══════════════════════════════════════════════════════════════════════════════
#
# As páginas de uma seção são uma lista ordenada de (id, nivel). A subpágina é
# deduzida: as páginas logo abaixo com nível maior são a "série" da de cima.
# Mesmo modelo do OneNote ([MS-ONE] §2.3.74, PageLevel 1..3).

NIVEL_MAX = 3


def normalizar_niveis(niveis):
    """Aplica as invariantes e devolve a lista corrigida.

    1. a primeira página tem nível 1;
    2. nenhuma pula nível: nivel[i] <= nivel[i-1] + 1;
    3. 1 <= nivel <= NIVEL_MAX.

    Corrige em vez de rejeitar: a entrada inválida mais provável é o resultado de
    mover uma série para o topo, e recusar o movimento seria pior que ajustá-lo.
    """
    saida = []
    for i, n in enumerate(niveis):
        try:
            n = int(n)
        except (TypeError, ValueError):
            n = 1
        n = max(1, min(NIVEL_MAX, n))
        teto = 1 if i == 0 else saida[-1] + 1
        saida.append(min(n, teto))
    return saida


def fim_da_serie(niveis, i):
    """Índice (exclusivo) onde termina a série da página `i`."""
    j = i + 1
    while j < len(niveis) and niveis[j] > niveis[i]:
        j += 1
    return j


def extrair_serie(itens, i):
    """Separa a página `i` e suas subpáginas. `itens` = [(id, nivel), ...].

    Devolve (serie, resto). Não normaliza: quem chama decide onde a série entra.
    """
    niveis = [n for _, n in itens]
    fim = fim_da_serie(niveis, i)
    return itens[i:fim], itens[:i] + itens[fim:]


def inserir_serie(itens, pos, serie, nivel_base=None):
    """Insere a série na posição `pos`, preservando o recuo relativo interno.

    `nivel_base` é o nível que a primeira página da série passa a ter (None =
    mantém). As subpáginas acompanham pela diferença. O resultado é normalizado.
    """
    if not serie:
        return list(itens)
    primeiro = serie[0][1]
    base = primeiro if nivel_base is None else nivel_base
    ajustada = [(pid, base + (n - primeiro)) for pid, n in serie]
    nova = list(itens[:pos]) + ajustada + list(itens[pos:])
    corrigidos = normalizar_niveis([n for _, n in nova])
    return [(pid, n) for (pid, _), n in zip(nova, corrigidos)]


def alterar_nivel(itens, i, delta):
    """Promove (delta=-1) ou rebaixa (delta=+1) a página `i` COM a sua série.

    Levar as subpáginas junto é o que o usuário espera ao recuar uma página que
    tem filhas: sem isso, as filhas ficariam penduradas na página de cima.
    """
    niveis = [n for _, n in itens]
    fim = fim_da_serie(niveis, i)
    novos = list(niveis)
    for k in range(i, fim):
        novos[k] = niveis[k] + delta
    corrigidos = normalizar_niveis(novos)
    return [(pid, n) for (pid, _), n in zip(itens, corrigidos)]


# ══════════════════════════════════════════════════════════════════════════════
# PERMISSÃO
# ══════════════════════════════════════════════════════════════════════════════

PESO_PAPEL = {None: 0, "leitor": 1, "editor": 2, "dono": 3}


def papel_efetivo(*, user_id, user_role, tem_area, caderno_dono_id, acesso_area,
                  papel_membro=None):
    """O papel de uma pessoa num caderno: None, 'leitor', 'editor' ou 'dono'.

    Ordem das regras (a primeira que decide, vence):

      1. admin é dono de tudo;
      2. quem criou o caderno é dono;
      3. papel explícito de membro (CadernoMembro);
      4. sem a área do caderno, nada;
      5. gestor da área é dono dos cadernos de equipe (acesso_area != 'nenhum') —
         é quem organiza; caderno privado continua privado também para ele;
      6. o resto da área recebe `acesso_area`.

    E um teto: o perfil `leitura` (auditoria externa) nunca passa de leitor.
    """
    if user_role == "admin":
        return "dono"

    if caderno_dono_id is not None and user_id == caderno_dono_id:
        papel = "dono"
    elif papel_membro in PESO_PAPEL and papel_membro:
        papel = papel_membro
    elif not tem_area or acesso_area == "nenhum":
        papel = None
    elif user_role == "gestor":
        papel = "dono"
    else:
        papel = acesso_area if acesso_area in ("leitor", "editor") else None

    if user_role == "leitura" and papel is not None:
        papel = "leitor"
    return papel


def pode(papel, minimo):
    return PESO_PAPEL.get(papel, 0) >= PESO_PAPEL[minimo]


# ══════════════════════════════════════════════════════════════════════════════
# TRAVA DE EDIÇÃO
# ══════════════════════════════════════════════════════════════════════════════
#
# Uma pessoa edita a página por vez. O front renova a trava a cada ~30 s; sem
# renovação ela expira em TRAVA_SEGUNDOS. Expirar sozinha é o que impede uma aba
# fechada (ou uma máquina que dormiu) de deixar a página presa.

TRAVA_SEGUNDOS = 120


def trava_de_outro(editando_por, editando_ate, user_id, agora):
    """id de quem segura a página, se for outra pessoa e a trava estiver viva."""
    if not editando_por or editando_por == user_id:
        return None
    if editando_ate is None or editando_ate <= agora:
        return None
    return editando_por


def nova_validade(agora):
    return agora + timedelta(seconds=TRAVA_SEGUNDOS)


# ══════════════════════════════════════════════════════════════════════════════
# FICHA DO REGISTRO DE TESTE
# ══════════════════════════════════════════════════════════════════════════════
#
# Os campos vêm do "Modelo de Registro de Teste Homologado" que o PDR já usa no
# OneNote (cabeçalho do modelo), mais o resultado — que é o que a tabela-resumo
# do relatório para a liderança precisa.

CAMPOS_FICHA = ["projeto", "numero", "resp_teste_id", "resp_execucao_id",
                "inicio", "termino", "resultado"]
RESULTADOS = ["", "em_andamento", "aprovado", "reprovado", "inconclusivo"]
_RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validar_ficha(dados, ids_validos):
    """(ficha normalizada, erro). `ids_validos` = ids de usuário aceitos."""
    if dados in (None, ""):
        return {}, None
    if not isinstance(dados, dict):
        return None, "ficha inválida"
    f = {}
    f["projeto"] = str(dados.get("projeto") or "").strip()[:80]
    f["numero"] = str(dados.get("numero") or "").strip()[:40]
    # Nome em texto: o responsável que veio do OneNote e ainda não casou com um
    # usuário do DocTrack. Guardado para não se perder na primeira edição.
    for campo in ("resp_teste_nome", "resp_execucao_nome"):
        f[campo] = str(dados.get(campo) or "").strip()[:120]
    for campo in ("resp_teste_id", "resp_execucao_id"):
        v = dados.get(campo)
        if v in (None, "", 0, "0"):
            f[campo] = None
            continue
        try:
            v = int(v)
        except (TypeError, ValueError):
            return None, f"{campo} inválido"
        if v not in ids_validos:
            return None, f"{campo}: usuário não encontrado"
        f[campo] = v
    for campo in ("inicio", "termino"):
        v = str(dados.get(campo) or "").strip()
        if v and not _RE_DATA.match(v):
            return None, f"{campo}: use AAAA-MM-DD"
        f[campo] = v
    if f["inicio"] and f["termino"] and f["termino"] < f["inicio"]:
        return None, "término antes do início"
    r = str(dados.get("resultado") or "").strip()
    if r not in RESULTADOS:
        return None, "resultado inválido"
    f["resultado"] = r
    return f, None


def ficha_de_json(texto):
    try:
        v = json.loads(texto) if texto else {}
        return v if isinstance(v, dict) else {}
    except (TypeError, ValueError):
        return {}


def proximo_numero_teste(numeros):
    """Sugere o próximo "Teste N" a partir dos números já usados no caderno.

    Os registros do L-037 numeram como "Teste 47", "47" ou "T-047"; o que
    importa é o maior inteiro encontrado.
    """
    maior = 0
    for n in numeros:
        m = re.search(r"(\d+)\s*$", str(n or ""))
        if m:
            maior = max(maior, int(m.group(1)))
    return str(maior + 1)


# ══════════════════════════════════════════════════════════════════════════════
# SANEAMENTO DO HTML
# ══════════════════════════════════════════════════════════════════════════════
#
# O servidor NUNCA guarda o que chegou: guarda o resultado desta função. O
# esquema do CKEditor já limita o HTML no navegador, mas o navegador é do
# usuário — uma requisição montada à mão chega aqui sem passar por ele.
#
# Allowlist, não blocklist: tag desconhecida perde a marcação e fica o texto;
# atributo desconhecido some; CSS só com as propriedades listadas e valores sem
# url()/expression. Tags cujo CONTEÚDO é perigoso somem inteiras.

_TAGS = {
    "p", "h1", "h2", "h3", "h4", "ul", "ol", "li", "figure", "figcaption",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "colgroup", "col",
    "img", "blockquote", "pre", "code", "hr", "br", "a", "strong", "b", "i",
    "em", "u", "s", "del", "sub", "sup", "mark", "span", "label", "input", "div",
}
_VAZIAS = {"img", "br", "hr", "col", "input"}
_SOME_COM_CONTEUDO = {
    "script", "style", "iframe", "object", "embed", "noscript", "template",
    "svg", "math", "form", "button", "textarea", "select", "frame", "frameset",
    "head", "title", "meta", "link", "base",
}
_ATRIBUTOS = {
    "*": {"style", "class"},
    "a": {"href", "data-ref", "data-arquivo"},
    "img": {"alt", "width", "height", "data-arquivo"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
    "ol": {"start", "reversed"},
    "input": {"type", "checked", "disabled"},
}
_CSS = {
    "color", "background-color", "font-size", "text-align", "margin-left",
    "padding-left", "width", "height", "aspect-ratio", "vertical-align",
    "list-style-type", "border", "border-color", "border-style", "border-width",
    "border-top", "border-right", "border-bottom", "border-left", "float",
}
_CSS_PROIBIDO = re.compile(r"url\s*\(|expression|javascript:|@import|[<>\\]", re.I)
_CLASSES = re.compile(
    r"^(marker-[a-z]+|pen-[a-z]+|table|image|image_resized|image-style-[a-z-]+|"
    r"image-inline|todo-list(__[a-z_]+)?|text-(tiny|small|big|huge)|"
    r"ck-table-resized)$"
)
_RE_ARQUIVO_SRC = re.compile(r"/cadernos/api/arquivos/([0-9a-f-]{36})/conteudo")
_RE_DATA_URI = re.compile(r"^data:(image/(?:png|jpeg|gif|webp));base64,(.+)$", re.I | re.S)


def _css_limpo(valor):
    partes = []
    for decl in (valor or "").split(";"):
        if ":" not in decl:
            continue
        prop, v = decl.split(":", 1)
        prop, v = prop.strip().lower(), v.strip()
        if prop == "background" and not _CSS_PROIBIDO.search(v):
            prop = "background-color"     # o Word e o OneNote mandam "background"
        if prop not in _CSS or not v or _CSS_PROIBIDO.search(v):
            continue
        partes.append(f"{prop}:{v}")
    return ";".join(partes)


def _href_limpo(v):
    v = (v or "").strip()
    baixo = v.lower()
    if baixo.startswith(("http://", "https://", "mailto:")):
        return v
    if v.startswith("#") or (v.startswith("/") and not v.startswith("//")):
        return v
    return None


class _Saneador(HTMLParser):
    def __init__(self, guardar_imagem=None):
        super().__init__(convert_charrefs=True)
        self.saida = []
        self.pilha = []
        self.pular = 0          # profundidade dentro de tag que some com conteúdo
        self.guardar_imagem = guardar_imagem
        self.imagens = set()

    # ── atributos ──
    def _attrs(self, tag, attrs):
        ok = _ATRIBUTOS["*"] | _ATRIBUTOS.get(tag, set())
        saida = {}
        for nome, valor in attrs:
            nome = (nome or "").lower()
            valor = "" if valor is None else valor
            if nome.startswith("on") or nome not in ok:
                continue
            if nome == "style":
                valor = _css_limpo(valor)
                if not valor:
                    continue
            elif nome == "class":
                classes = [c for c in valor.split() if _CLASSES.match(c)]
                if not classes:
                    continue
                valor = " ".join(classes)
            elif nome == "href":
                valor = _href_limpo(valor)
                if valor is None:
                    continue
                m = _RE_ARQUIVO_SRC.search(valor)
                if m:   # link para arquivo do caderno: guarda a referência, não a URL
                    saida["data-arquivo"] = m.group(1)
                    continue
            elif nome in ("colspan", "rowspan", "start", "width", "height"):
                if not valor.isdigit():
                    continue
            elif nome == "data-arquivo":
                if not re.fullmatch(r"[0-9a-f-]{36}", valor):
                    continue
            elif nome == "data-ref":
                if not re.fullmatch(r"[a-z_]+:[0-9A-Za-z-]{1,64}", valor):
                    continue
            elif nome == "type":
                if valor != "checkbox":
                    continue
            saida[nome] = valor
        return saida

    def _img(self, attrs):
        """Imagem só fica se apontar para um arquivo do caderno.

        `src` nunca é guardado: vira `data-arquivo`. Imagem colada como data URI
        é gravada como arquivo (se houver onde) e também vira `data-arquivo`.
        Qualquer outra origem (URL externa) some — a CSP nem deixaria carregar.
        """
        brutos = dict((k.lower(), v or "") for k, v in attrs)
        a = self._attrs("img", attrs)
        src = brutos.get("src", "")
        ref = a.get("data-arquivo")
        if not ref:
            m = _RE_ARQUIVO_SRC.search(src)
            if m:
                ref = m.group(1)
        if not ref:
            m = _RE_DATA_URI.match(src.strip())
            if m and self.guardar_imagem:
                try:
                    dados = base64.b64decode(re.sub(r"\s+", "", m.group(2)), validate=True)
                except (binascii.Error, ValueError):
                    dados = None
                if dados:
                    ref = self.guardar_imagem(m.group(1).lower(), dados)
        if not ref:
            return None
        a["data-arquivo"] = ref
        self.imagens.add(ref)
        return a

    def _abrir(self, tag, attrs, vazia):
        if tag == "img":
            a = self._img(attrs)
            if a is None:
                return
        else:
            a = self._attrs(tag, attrs)
        if tag == "input":
            if a.get("type") != "checkbox":
                return
            a["disabled"] = "disabled"
        txt = "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in a.items())
        self.saida.append(f"<{tag}{txt}>")
        if not vazia and tag not in _VAZIAS:
            self.pilha.append(tag)

    # ── eventos do parser ──
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _SOME_COM_CONTEUDO:
            if tag not in _VAZIAS:
                self.pular += 1
            return
        if self.pular or tag not in _TAGS:
            return
        self._abrir(tag, attrs, vazia=False)

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if self.pular or tag in _SOME_COM_CONTEUDO or tag not in _TAGS:
            return
        self._abrir(tag, attrs, vazia=True)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _SOME_COM_CONTEUDO:
            if self.pular:
                self.pular -= 1
            return
        if self.pular or tag not in self.pilha:
            return
        while self.pilha:
            topo = self.pilha.pop()
            self.saida.append(f"</{topo}>")
            if topo == tag:
                break

    def handle_data(self, data):
        if not self.pular:
            self.saida.append(html.escape(data, quote=False))

    # Comentários, declarações e instruções de processamento somem.
    def handle_comment(self, data):
        pass

    def handle_decl(self, decl):
        pass

    def handle_pi(self, data):
        pass

    def unknown_decl(self, data):
        pass

    def resultado(self):
        while self.pilha:
            self.saida.append(f"</{self.pilha.pop()}>")
        return "".join(self.saida)


def sanear_html(conteudo, guardar_imagem=None):
    """(html_limpo, {uuids de imagem referenciados}).

    `guardar_imagem(mime, bytes) -> uuid | None` grava imagem colada como data URI.
    Sem ele, a imagem embutida simplesmente some.
    """
    p = _Saneador(guardar_imagem=guardar_imagem)
    p.feed(conteudo or "")
    p.close()
    return p.resultado(), p.imagens


_RE_ANEXO = re.compile(r'<a\b[^>]*\sdata-arquivo="([0-9a-f-]{36})"')
_RE_IMAGEM = re.compile(r'<img\b[^>]*\sdata-arquivo="([0-9a-f-]{36})"')


def anexos_no_html(conteudo):
    """uuids dos arquivos citados como anexo (link no texto) no HTML guardado,
    na ordem em que aparecem. O anexo aponta para uma VERSÃO; quem resolve para
    a versão vigente é quem serve o arquivo (`?atual=1`)."""
    return list(dict.fromkeys(_RE_ANEXO.findall(conteudo or "")))


def imagens_no_html(conteudo):
    """uuids das imagens do HTML guardado, na ordem em que aparecem."""
    return list(dict.fromkeys(_RE_IMAGEM.findall(conteudo or "")))


def texto_de(conteudo):
    """Texto puro do HTML (para a busca e para o diff de versões)."""
    sem_tags = re.sub(r"<(br|/p|/h\d|/li|/tr|/td|/th)[^>]*>", "\n", conteudo or "", flags=re.I)
    sem_tags = re.sub(r"<[^>]+>", " ", sem_tags)
    return re.sub(r"[ \t\r\f\v]+", " ", html.unescape(sem_tags)).strip()


def montar_texto_busca(titulo, conteudo, ficha):
    partes = [titulo or "", texto_de(conteudo)]
    if ficha:
        partes += [str(ficha.get("numero") or ""), str(ficha.get("projeto") or "")]
    return norm(" ".join(partes))


# ══════════════════════════════════════════════════════════════════════════════
# MODELOS
# ══════════════════════════════════════════════════════════════════════════════

# Seções do caderno de projeto do PDR: as mesmas do L-037 (inventário de
# 2026-10-05), que seguem as fases do projeto.
MODELOS_CADERNO = {
    "projeto_pdr": {
        "nome": "Projeto PDR (fases do projeto)",
        "secoes": [
            ("Desenvolvimento", "registro_teste"),
            ("Validação Equipamentos", "registro_teste"),
            ("Validação Externa", "registro_teste"),
            ("Validação Fornecedor", "registro_teste"),
            ("Validação Materiais e Reagentes", "registro_teste"),
            ("Estabilidade", "registro_teste"),
            ("Transferência de Projeto", "nota"),
        ],
    },
    "em_branco": {"nome": "Em branco", "secoes": [("Geral", "nota")]},
}

# Corpo do "Registro de teste": a estrutura do "Modelo de Registro de Teste
# Homologado" do PDR. O cabeçalho (projeto, número, responsáveis, datas) não está
# aqui — virou a ficha, que é dado estruturado e não texto.
def _tabela(cabecalhos):
    th = "".join(f"<th>{html.escape(c)}</th>" for c in cabecalhos)
    td = "".join("<td>&nbsp;</td>" for _ in cabecalhos)
    return (f'<figure class="table"><table><thead><tr>{th}</tr></thead>'
            f"<tbody><tr>{td}</tr></tbody></table></figure>")


HTML_REGISTRO_TESTE = "".join([
    "<h2>1. Descrição detalhada</h2><p>&nbsp;</p>",
    "<h2>2. Materiais e métodos</h2>",
    "<h3>2.1 Condições do laboratório</h3>", _tabela(["Temperatura (°C)", "Umidade (%)"]),
    "<h3>2.2 Reagentes utilizados</h3>", _tabela(["Reagente", "Lote", "Validade", "SKU/Cat. Number"]),
    "<h3>2.3 Materiais utilizados</h3>", _tabela(["Item", "Lote", "Validade", "SKU/Cat. Number"]),
    "<h3>2.4 Equipamentos utilizados</h3>", _tabela(["Equipamento", "Número de série", "Data de calibração"]),
    "<h3>2.5 Amostras utilizadas</h3><p>&nbsp;</p>",
    "<h3>2.6 Protocolo detalhado</h3><p>&nbsp;</p>",
    "<h2>3. Resultados</h2>",
    "<h3>3.1 Dados brutos</h3><p>&nbsp;</p>",
    "<h3>3.2 Interpretação e discussão dos resultados</h3><p>&nbsp;</p>",
    "<h2>4. Observações e comentários adicionais</h2><p>&nbsp;</p>",
    "<h2>5. Conclusão</h2><p>&nbsp;</p>",
    "<h2>6. Próximos passos</h2><p>&nbsp;</p>",
    "<h2>7. Referências</h2><p>&nbsp;</p>",
])
